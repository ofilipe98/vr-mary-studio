"""Paired VR Ultra benchmark for the opt-in ERP code-analysis worker."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .classpath import ClasspathPolicyStore
from .code_index import JavaCodeIndex
from .config import MarySettings
from .db import MaryDatabase
from .erp_releases import ErpReleaseCatalog
from .models import RuntimeEvent
from .orchestrator import ChatOrchestrator


BENCHMARK_SCHEMA_VERSION = 1
SAFE_DATA_CLASSIFICATIONS = {"anonymized", "synthetic"}
VALID_RESPONSE_MODES = {"auto", "training", "support", "implementation"}
REAL_CASE_COUNT_RANGE = (5, 10)
PLACEHOLDER_MARKERS = {
    "substituir",
    "descrever",
    "aaaa-mm-dd",
    "classeoumetodoconfirmado",
    "causa conhecida",
    "hipotese ja descartada",
    "hipótese já descartada",
}
SENSITIVE_TEXT_PATTERNS = (
    (
        "email",
        re.compile(
            r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
            r"(?![A-Za-z0-9_-])"
        ),
    ),
    (
        "telefone",
        re.compile(
            r"(?<!\d)(?:\+?55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)"
            r"(?:9\d{4}|\d{4})[\s.-]?\d{4}(?!\d)"
        ),
    ),
    (
        "endereco_ip",
        re.compile(
            r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)"
            r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"
        ),
    ),
    ("url", re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)),
    (
        "caminho_usuario",
        re.compile(r"(?:[A-Za-z]:\\Users\\[^\\\s]+|/Users/[^/\s]+|/home/[^/\s]+)"),
    ),
    (
        "credencial",
        re.compile(
            r"\b(?:password|senha|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+",
            re.IGNORECASE,
        ),
    ),
)


class CodeAnalysisBenchmarkError(RuntimeError):
    """Controlled benchmark validation or execution failure."""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    title: str
    question: str
    response_mode: str
    module: str
    target_jars: tuple[str, ...]
    known_root_cause: str
    root_cause_evidence: str
    resolved_at: str
    expected_terms: tuple[str, ...]
    expected_code_symbols: tuple[str, ...]
    expected_citation_sources: tuple[str, ...]
    forbidden_terms: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkSuite:
    suite_id: str
    release_id: str
    data_classification: str
    candidate_pool_size: int
    selection_method: str
    anonymization_review_id: str
    cases: tuple[BenchmarkCase, ...]


VariantExecutor = Callable[[BenchmarkCase, bool], dict[str, Any]]


def load_benchmark_suite(path: str | Path) -> BenchmarkSuite:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodeAnalysisBenchmarkError(
            f"Não foi possível ler a suíte: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise CodeAnalysisBenchmarkError("A suíte precisa ser um objeto JSON.")
    if int(payload.get("schema_version") or 0) != BENCHMARK_SCHEMA_VERSION:
        raise CodeAnalysisBenchmarkError(
            f"schema_version precisa ser {BENCHMARK_SCHEMA_VERSION}."
        )
    suite_id = _identifier(payload.get("suite_id"), "suite_id")
    release_id = str(payload.get("release_id") or "").strip()
    if not release_id:
        raise CodeAnalysisBenchmarkError("release_id é obrigatório.")
    classification = str(payload.get("data_classification") or "").casefold()
    if classification not in SAFE_DATA_CLASSIFICATIONS:
        raise CodeAnalysisBenchmarkError(
            "data_classification deve ser anonymized ou synthetic; "
            "casos brutos de clientes não são aceitos."
        )
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CodeAnalysisBenchmarkError("A suíte precisa conter ao menos um caso.")
    try:
        candidate_pool_size = int(payload.get("candidate_pool_size") or 0)
    except (TypeError, ValueError) as exc:
        raise CodeAnalysisBenchmarkError(
            "candidate_pool_size precisa ser um número inteiro."
        ) from exc
    selection_method = str(payload.get("selection_method") or "").strip()
    anonymization_review_id = str(
        payload.get("anonymization_review_id") or ""
    ).strip()
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, dict):
            raise CodeAnalysisBenchmarkError(f"Caso {index} não é um objeto.")
        case_id = _identifier(raw.get("case_id"), f"cases[{index}].case_id")
        if case_id in seen:
            raise CodeAnalysisBenchmarkError(f"case_id duplicado: {case_id}")
        seen.add(case_id)
        question = str(raw.get("question") or "").strip()
        if not question:
            raise CodeAnalysisBenchmarkError(f"Caso {case_id} não possui question.")
        response_mode = str(raw.get("response_mode") or "support").casefold()
        if response_mode not in VALID_RESPONSE_MODES:
            raise CodeAnalysisBenchmarkError(
                f"Modo de resposta inválido no caso {case_id}: {response_mode}"
            )
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                title=str(raw.get("title") or case_id).strip(),
                question=question,
                response_mode=response_mode,
                module=str(raw.get("module") or "").strip(),
                target_jars=_string_tuple(raw.get("target_jars")),
                known_root_cause=str(raw.get("known_root_cause") or "").strip(),
                root_cause_evidence=str(
                    raw.get("root_cause_evidence") or ""
                ).strip(),
                resolved_at=str(raw.get("resolved_at") or "").strip(),
                expected_terms=_string_tuple(raw.get("expected_terms")),
                expected_code_symbols=_string_tuple(
                    raw.get("expected_code_symbols")
                ),
                expected_citation_sources=_string_tuple(
                    raw.get("expected_citation_sources")
                ),
                forbidden_terms=_string_tuple(raw.get("forbidden_terms")),
            )
        )
    return BenchmarkSuite(
        suite_id,
        release_id,
        classification,
        candidate_pool_size,
        selection_method,
        anonymization_review_id,
        tuple(cases),
    )


def audit_benchmark_intake(suite: BenchmarkSuite) -> dict[str, Any]:
    """Audit real-case selection and obvious sensitive data without model calls."""

    errors: list[str] = []
    warnings: list[str] = []
    case_count = len(suite.cases)
    findings = _benchmark_sensitive_findings(suite)
    if findings:
        errors.append(
            "Foram encontrados dados potencialmente sensíveis; anonimize os campos "
            "indicados antes de congelar a suíte."
        )

    if suite.data_classification == "anonymized":
        minimum, maximum = REAL_CASE_COUNT_RANGE
        if not minimum <= case_count <= maximum:
            errors.append(
                f"A suíte real precisa conter entre {minimum} e {maximum} casos."
            )
        if suite.candidate_pool_size < case_count:
            errors.append(
                "candidate_pool_size precisa ser maior ou igual ao total selecionado."
            )
        if len(suite.selection_method) < 20 or _contains_placeholder(
            (suite.selection_method,)
        ):
            errors.append(
                "selection_method precisa explicar como os casos foram escolhidos "
                "antes da execução."
            )
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", suite.anonymization_review_id
        ):
            errors.append(
                "anonymization_review_id precisa identificar a revisão manual sem "
                "incluir nome ou dado pessoal."
            )

    case_reports: list[dict[str, Any]] = []
    for case in suite.cases:
        case_errors: list[str] = []
        case_findings = [
            finding for finding in findings if finding["case_id"] == case.case_id
        ]
        if suite.data_classification == "anonymized":
            if not case.module:
                case_errors.append("module é obrigatório.")
            if len(case.root_cause_evidence) < 20 or _contains_placeholder(
                (case.root_cause_evidence,)
            ):
                case_errors.append(
                    "root_cause_evidence precisa registrar como a causa foi confirmada."
                )
            if not _valid_past_date(case.resolved_at):
                case_errors.append(
                    "resolved_at precisa ser uma data ISO válida e não futura."
                )
        case_reports.append(
            {
                "case_id": case.case_id,
                "module": case.module,
                "ready": not case_errors and not case_findings,
                "errors": case_errors,
                "sensitive_finding_count": len(case_findings),
            }
        )
        errors.extend(f"{case.case_id}: {error}" for error in case_errors)

    modules = Counter(case.module or "não informado" for case in suite.cases)
    response_modes = Counter(case.response_mode for case in suite.cases)
    if suite.data_classification == "anonymized" and len(modules) < 2:
        warnings.append(
            "A amostra cobre apenas um módulo; não generalize o resultado para todo o ERP."
        )
    if case_count and max(modules.values()) / case_count > 0.6:
        warnings.append(
            "Mais de 60% dos casos pertencem ao mesmo módulo; registre esse viés "
            "na interpretação."
        )

    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "suite_id": suite.suite_id,
        "release_id": suite.release_id,
        "data_classification": suite.data_classification,
        "checked_at": _utc_now(),
        "ready": not errors and all(item["ready"] for item in case_reports),
        "errors": errors,
        "warnings": warnings,
        "case_count": case_count,
        "required_case_count": (
            {"minimum": REAL_CASE_COUNT_RANGE[0], "maximum": REAL_CASE_COUNT_RANGE[1]}
            if suite.data_classification == "anonymized"
            else None
        ),
        "candidate_pool_size": suite.candidate_pool_size,
        "selection_method_present": bool(suite.selection_method),
        "anonymization_review_id": suite.anonymization_review_id,
        "module_distribution": dict(sorted(modules.items())),
        "response_mode_distribution": dict(sorted(response_modes.items())),
        "sensitive_findings": findings,
        "cases": case_reports,
    }


def benchmark_suite_fingerprint(suite: BenchmarkSuite) -> str:
    encoded = json.dumps(
        asdict(suite),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_benchmark_intake_manifest(suite: BenchmarkSuite) -> dict[str, Any]:
    audit = audit_benchmark_intake(suite)
    if not audit["ready"]:
        raise CodeAnalysisBenchmarkError(
            "Intake reprovado: " + "; ".join(str(item) for item in audit["errors"])
        )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "suite_id": suite.suite_id,
        "release_id": suite.release_id,
        "data_classification": suite.data_classification,
        "suite_fingerprint": benchmark_suite_fingerprint(suite),
        "frozen_at": _utc_now(),
        "audit": {
            "case_count": audit["case_count"],
            "candidate_pool_size": audit["candidate_pool_size"],
            "module_distribution": audit["module_distribution"],
            "response_mode_distribution": audit["response_mode_distribution"],
            "sensitive_finding_count": len(audit["sensitive_findings"]),
            "warnings": audit["warnings"],
        },
    }


def load_benchmark_intake_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodeAnalysisBenchmarkError(
            f"Não foi possível ler o manifesto de intake: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise CodeAnalysisBenchmarkError(
            "O manifesto de intake precisa ser um objeto JSON."
        )
    return payload


def verify_benchmark_intake_manifest(
    suite: BenchmarkSuite, manifest: dict[str, Any] | None
) -> dict[str, Any]:
    if suite.data_classification == "synthetic" and manifest is None:
        return {
            "required": False,
            "ready": True,
            "status": "not_required",
            "suite_fingerprint": benchmark_suite_fingerprint(suite),
            "errors": [],
        }
    errors: list[str] = []
    if not isinstance(manifest, dict):
        errors.append(
            "A suíte anonimizada exige manifesto criado por freeze-code-analysis-cases."
        )
        manifest = {}
    expected_fingerprint = benchmark_suite_fingerprint(suite)
    checks = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "suite_id": suite.suite_id,
        "release_id": suite.release_id,
        "data_classification": suite.data_classification,
        "suite_fingerprint": expected_fingerprint,
    }
    for field, expected in checks.items():
        if manifest.get(field) != expected:
            errors.append(f"Manifesto de intake não corresponde ao campo {field}.")
    if not _valid_past_date(str(manifest.get("frozen_at") or "")):
        errors.append("Manifesto de intake não possui frozen_at válido.")
    return {
        "required": suite.data_classification == "anonymized",
        "ready": not errors,
        "status": "verified" if not errors else "invalid",
        "suite_fingerprint": expected_fingerprint,
        "frozen_at": str(manifest.get("frozen_at") or ""),
        "errors": errors,
    }


def preflight_benchmark_suite(
    suite: BenchmarkSuite,
    root: str | Path,
    *,
    intake_manifest: dict[str, Any] | None = None,
    catalog: ErpReleaseCatalog | None = None,
    code_index: JavaCodeIndex | None = None,
    classpath_policy: ClasspathPolicyStore | None = None,
) -> dict[str, Any]:
    """Validate that cases are measurable against the selected local index."""

    project_root = Path(root).resolve()
    release_catalog = catalog or ErpReleaseCatalog(project_root)
    index = code_index or JavaCodeIndex(project_root)
    release = release_catalog.status(suite.release_id)
    coverage = index.coverage(suite.release_id)
    index_status = index.status(suite.release_id)
    policy = classpath_policy or ClasspathPolicyStore(
        project_root, catalog=release_catalog
    )
    classpath = policy.status(suite.release_id)
    covered_jars = set(str(item) for item in coverage.get("covered_jars") or [])
    intake = audit_benchmark_intake(suite)
    manifest = verify_benchmark_intake_manifest(suite, intake_manifest)
    errors: list[str] = list(intake["errors"])
    errors.extend(manifest["errors"])
    warnings: list[str] = list(intake["warnings"])
    if release.get("state") != "ready" or release.get("freshness") != "fresh":
        errors.append("A release selecionada não está pronta e atualizada.")
    if int(index_status.get("sources") or 0) < 1:
        errors.append("A release selecionada não possui fontes no índice de código.")
    if str(classpath.get("classpath_status") or "unknown") != "resolved":
        warnings.append(
            "A ordem completa do classpath não foi confirmada; ambiguidades devem "
            "permanecer explícitas nas respostas."
        )

    case_reports: list[dict[str, Any]] = []
    for case in suite.cases:
        case_errors: list[str] = []
        case_warnings: list[str] = []
        if not case.known_root_cause:
            case_errors.append("known_root_cause é obrigatório para aferir correção.")
        if not case.target_jars:
            case_errors.append("target_jars precisa declarar ao menos um JAR esperado.")
        uncovered = [item for item in case.target_jars if item not in covered_jars]
        if uncovered:
            case_errors.append(
                "JARs esperados fora da cobertura integral: " + ", ".join(uncovered)
            )
        if not (
            case.expected_terms
            or case.expected_code_symbols
            or case.expected_citation_sources
        ):
            case_errors.append("O caso não possui critérios objetivos esperados.")
        placeholder_values = (
            case.title,
            case.question,
            case.known_root_cause,
            *case.expected_terms,
            *case.expected_code_symbols,
            *case.expected_citation_sources,
            *case.forbidden_terms,
        )
        if _contains_placeholder(placeholder_values):
            case_errors.append("O caso ainda contém marcadores do template.")

        symbol_checks: list[dict[str, Any]] = []
        for symbol in case.expected_code_symbols:
            matches = index.search(symbol, release_id=suite.release_id, limit=10)
            selected = next(
                (
                    item
                    for item in matches
                    if not case.target_jars
                    or str(item.get("jar_relative_path") or "") in case.target_jars
                ),
                None,
            )
            symbol_checks.append(
                {
                    "symbol": symbol,
                    "found": selected is not None,
                    "jar_relative_path": (
                        str(selected.get("jar_relative_path") or "")
                        if selected
                        else ""
                    ),
                    "qualified_name": (
                        str(selected.get("qualified_name") or "") if selected else ""
                    ),
                    "citation": str(selected.get("citation") or "") if selected else "",
                    "freshness": str(selected.get("freshness") or "") if selected else "",
                    "classpath_resolution": (
                        str(selected.get("classpath_resolution") or "")
                        if selected
                        else ""
                    ),
                }
            )
            if selected is None:
                case_errors.append(
                    f"Símbolo esperado não localizado nos JARs-alvo: {symbol}"
                )
            elif str(selected.get("classpath_resolution") or "") in {
                "ambiguous",
                "shadowed",
                "unknown",
            }:
                case_warnings.append(
                    f"{symbol}: classpath {selected.get('classpath_resolution')}."
                )
        case_reports.append(
            {
                "case_id": case.case_id,
                "module": case.module,
                "target_jars": list(case.target_jars),
                "ready": not case_errors,
                "errors": case_errors,
                "warnings": case_warnings,
                "symbol_checks": symbol_checks,
            }
        )

    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "suite_id": suite.suite_id,
        "release_id": suite.release_id,
        "checked_at": _utc_now(),
        "ready": not errors and all(item["ready"] for item in case_reports),
        "errors": errors,
        "warnings": warnings,
        "intake": intake,
        "intake_manifest": manifest,
        "coverage": {
            "covered_jar_count": int(coverage.get("covered_jar_count") or 0),
            "expected_jar_count": int(coverage.get("expected_jar_count") or 0),
            "covered_jars": sorted(covered_jars, key=str.casefold),
            "classpath_status": str(classpath.get("classpath_status") or "unknown"),
        },
        "index": {
            "sources": int(index_status.get("sources") or 0),
            "symbols": int(index_status.get("symbols") or 0),
            "jar_count": int(index_status.get("jar_count") or 0),
        },
        "cases": case_reports,
    }


def run_paired_benchmark(
    suite: BenchmarkSuite,
    execute_variant: VariantExecutor,
    *,
    max_cases: int = 0,
) -> dict[str, Any]:
    selected = suite.cases[: max(0, int(max_cases))] if max_cases else suite.cases
    results: list[dict[str, Any]] = []
    for index, case in enumerate(selected):
        order = (False, True) if index % 2 == 0 else (True, False)
        variants: dict[str, dict[str, Any]] = {}
        for enabled in order:
            raw = execute_variant(case, enabled)
            scored = {**raw, "score": score_variant(case, raw)}
            variants["on" if enabled else "off"] = scored
        results.append(
            {
                "case": asdict(case),
                "execution_order": ["on" if item else "off" for item in order],
                "off": variants["off"],
                "on": variants["on"],
                "comparison": compare_variants(variants["off"], variants["on"]),
                "human_review": {
                    "off_correctness": None,
                    "on_correctness": None,
                    "preferred": "",
                    "notes": "",
                },
            }
        )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_id": f"benchmark-{uuid.uuid4().hex[:16]}",
        "suite_id": suite.suite_id,
        "release_id": suite.release_id,
        "data_classification": suite.data_classification,
        "created_at": _utc_now(),
        "case_count": len(results),
        "results": results,
        "summary": summarize_results(results),
    }


def score_variant(case: BenchmarkCase, result: dict[str, Any]) -> dict[str, Any]:
    answer = str(result.get("answer") or "")
    citations = " ".join(str(item) for item in result.get("code_citations") or [])
    searchable = _normalize(f"{answer} {citations}")
    citation_searchable = _normalize(citations)
    expected_terms = [item for item in case.expected_terms if item]
    expected_symbols = [item for item in case.expected_code_symbols if item]
    expected_sources = [item for item in case.expected_citation_sources if item]
    matched_terms = [item for item in expected_terms if _normalize(item) in searchable]
    matched_symbols = [item for item in expected_symbols if _normalize(item) in searchable]
    matched_sources = [
        item for item in expected_sources if _normalize(item) in citation_searchable
    ]
    forbidden_hits = [
        item for item in case.forbidden_terms if _normalize(item) in searchable
    ]
    expected_total = len(expected_terms) + len(expected_symbols) + len(expected_sources)
    matched_total = len(matched_terms) + len(matched_symbols) + len(matched_sources)
    recall = matched_total / expected_total if expected_total else None
    objective = None
    if recall is not None:
        objective = max(0.0, round(recall - min(0.5, 0.2 * len(forbidden_hits)), 4))
    return {
        "objective": objective,
        "expected_recall": round(recall, 4) if recall is not None else None,
        "matched_terms": matched_terms,
        "matched_code_symbols": matched_symbols,
        "matched_citation_sources": matched_sources,
        "forbidden_hits": forbidden_hits,
        "grounded_code": bool(result.get("code_citations")),
        "completed": str(result.get("status") or "") == "completed",
    }


def compare_variants(off: dict[str, Any], on: dict[str, Any]) -> dict[str, Any]:
    off_score = off.get("score") or {}
    on_score = on.get("score") or {}
    off_objective = off_score.get("objective")
    on_objective = on_score.get("objective")
    delta = (
        round(float(on_objective) - float(off_objective), 4)
        if off_objective is not None and on_objective is not None
        else None
    )
    off_tokens = int(off.get("total_tokens") or 0)
    on_tokens = int(on.get("total_tokens") or 0)
    off_latency = int(off.get("elapsed_ms") or 0)
    on_latency = int(on.get("elapsed_ms") or 0)
    if not on_score.get("completed") or not on.get("code_agent_started"):
        decision = "inconclusive"
    elif delta is None:
        decision = "requires_human_review"
    elif delta > 0:
        decision = "supports_opt_in"
    else:
        decision = "no_measurable_gain"
    return {
        "objective_delta": delta,
        "token_delta": on_tokens - off_tokens,
        "token_ratio": _ratio(on_tokens, off_tokens),
        "latency_delta_ms": on_latency - off_latency,
        "latency_ratio": _ratio(on_latency, off_latency),
        "code_evidence_gained": bool(on.get("code_citations"))
        and not bool(off.get("code_citations")),
        "decision": decision,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(item["comparison"]["decision"] for item in results)
    deltas = [
        float(item["comparison"]["objective_delta"])
        for item in results
        if item["comparison"]["objective_delta"] is not None
    ]
    return {
        "decisions": dict(sorted(decisions.items())),
        "mean_objective_delta": round(sum(deltas) / len(deltas), 4)
        if deltas
        else None,
        "cases_with_code_evidence": sum(
            1 for item in results if item["comparison"]["code_evidence_gained"]
        ),
        "human_review_pending": len(results),
    }


def build_blind_review_packet(
    report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    benchmark_id = str(report.get("benchmark_id") or "").strip()
    results = report.get("results")
    if not benchmark_id or not isinstance(results, list) or not results:
        raise CodeAnalysisBenchmarkError(
            "Relatório inválido para preparar a revisão cega."
        )
    review_id = f"review-{uuid.uuid4().hex[:16]}"
    cases: list[dict[str, Any]] = []
    mappings: dict[str, dict[str, str]] = {}
    for item in results:
        case = item.get("case") or {}
        case_id = str(case.get("case_id") or "").strip()
        if not case_id or not isinstance(item.get("off"), dict) or not isinstance(
            item.get("on"), dict
        ):
            raise CodeAnalysisBenchmarkError(
                "Relatório contém caso sem variantes off/on válidas."
            )
        on_first = int(
            hashlib.sha256(f"{benchmark_id}:{case_id}".encode("utf-8")).hexdigest(),
            16,
        ) % 2 == 0
        mapping = {"A": "on", "B": "off"} if on_first else {"A": "off", "B": "on"}
        mappings[case_id] = mapping
        responses = {
            label: {
                "answer": str(item[variant].get("answer") or ""),
                "citations": [
                    str(value) for value in item[variant].get("code_citations") or []
                ],
            }
            for label, variant in mapping.items()
        }
        cases.append(
            {
                "case_id": case_id,
                "title": str(case.get("title") or case_id),
                "question": str(case.get("question") or ""),
                "module": str(case.get("module") or ""),
                "responses": responses,
                "review": {
                    "A": {"correctness": None, "grounding": None},
                    "B": {"correctness": None, "grounding": None},
                    "preferred": "",
                    "notes": "",
                },
            }
        )
    packet = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "review_id": review_id,
        "benchmark_id": benchmark_id,
        "suite_id": str(report.get("suite_id") or ""),
        "created_at": _utc_now(),
        "instructions": (
            "Avalie A e B sem consultar a chave. Use notas de 0 a 4 para "
            "correctness e grounding; preferred deve ser A, B ou tie."
        ),
        "cases": cases,
    }
    fingerprint = _blind_packet_fingerprint(packet)
    packet["content_fingerprint"] = fingerprint
    key = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "review_id": review_id,
        "benchmark_id": benchmark_id,
        "content_fingerprint": fingerprint,
        "created_at": _utc_now(),
        "mappings": mappings,
    }
    return packet, key


def apply_blind_review(
    report: dict[str, Any],
    packet: dict[str, Any],
    key: dict[str, Any],
) -> dict[str, Any]:
    benchmark_id = str(report.get("benchmark_id") or "")
    if not benchmark_id or benchmark_id != str(packet.get("benchmark_id") or ""):
        raise CodeAnalysisBenchmarkError("Pacote de revisão não pertence ao relatório.")
    if benchmark_id != str(key.get("benchmark_id") or ""):
        raise CodeAnalysisBenchmarkError("Chave de revisão não pertence ao relatório.")
    if str(packet.get("review_id") or "") != str(key.get("review_id") or ""):
        raise CodeAnalysisBenchmarkError("Pacote e chave possuem review_id diferentes.")
    fingerprint = _blind_packet_fingerprint(packet)
    if fingerprint != str(packet.get("content_fingerprint") or "") or fingerprint != str(
        key.get("content_fingerprint") or ""
    ):
        raise CodeAnalysisBenchmarkError(
            "As respostas do pacote foram alteradas depois do cegamento."
        )
    mappings = key.get("mappings")
    if not isinstance(mappings, dict):
        raise CodeAnalysisBenchmarkError("Chave de revisão não possui mappings válidos.")
    raw_packet_cases = packet.get("cases") or []
    if not isinstance(raw_packet_cases, list):
        raise CodeAnalysisBenchmarkError("Pacote de revisão não possui casos válidos.")
    packet_cases = {
        str(item.get("case_id") or ""): item
        for item in raw_packet_cases
        if isinstance(item, dict)
    }
    report_case_ids = {
        str((item.get("case") or {}).get("case_id") or "")
        for item in report.get("results") or []
        if isinstance(item, dict)
    }
    if (
        len(packet_cases) != len(raw_packet_cases)
        or set(packet_cases) != report_case_ids
        or set(mappings) != report_case_ids
    ):
        raise CodeAnalysisBenchmarkError(
            "Casos do relatório, pacote e chave não correspondem exatamente."
        )
    if any(
        not isinstance(mapping, dict)
        or set(mapping) != {"A", "B"}
        or set(str(value) for value in mapping.values()) != {"off", "on"}
        for mapping in mappings.values()
    ):
        raise CodeAnalysisBenchmarkError("A chave possui mapeamento A/B inválido.")
    reviewed = json.loads(json.dumps(report, ensure_ascii=False))
    correctness_deltas: list[float] = []
    grounding_deltas: list[float] = []
    preferences: Counter[str] = Counter()
    for item in reviewed.get("results") or []:
        case_id = str((item.get("case") or {}).get("case_id") or "")
        review_case = packet_cases.get(case_id)
        mapping = mappings.get(case_id)
        if review_case is None or not isinstance(mapping, dict):
            raise CodeAnalysisBenchmarkError(f"Revisão ausente para o caso {case_id}.")
        review = review_case.get("review") or {}
        label_scores: dict[str, dict[str, float]] = {}
        for label in ("A", "B"):
            raw_scores = review.get(label) or {}
            label_scores[label] = {
                "correctness": _review_score(
                    raw_scores.get("correctness"), case_id, label, "correctness"
                ),
                "grounding": _review_score(
                    raw_scores.get("grounding"), case_id, label, "grounding"
                ),
            }
        preferred_label = str(review.get("preferred") or "").strip().upper()
        if preferred_label not in {"A", "B", "TIE"}:
            raise CodeAnalysisBenchmarkError(
                f"Caso {case_id}: preferred precisa ser A, B ou tie."
            )
        variant_scores = {
            str(mapping[label]): label_scores[label] for label in ("A", "B")
        }
        preferred_variant = (
            "tie" if preferred_label == "TIE" else str(mapping[preferred_label])
        )
        preferences[preferred_variant] += 1
        correctness_deltas.append(
            variant_scores["on"]["correctness"]
            - variant_scores["off"]["correctness"]
        )
        grounding_deltas.append(
            variant_scores["on"]["grounding"]
            - variant_scores["off"]["grounding"]
        )
        item["human_review"] = {
            "off_correctness": variant_scores["off"]["correctness"],
            "on_correctness": variant_scores["on"]["correctness"],
            "off_grounding": variant_scores["off"]["grounding"],
            "on_grounding": variant_scores["on"]["grounding"],
            "preferred": preferred_variant,
            "notes": str(review.get("notes") or ""),
            "review_id": str(packet.get("review_id") or ""),
        }
    human_summary = {
        "reviewed_cases": len(correctness_deltas),
        "preferences": dict(sorted(preferences.items())),
        "mean_correctness_delta": _mean(correctness_deltas),
        "mean_grounding_delta": _mean(grounding_deltas),
    }
    reviewed.setdefault("summary", {})["human_review"] = human_summary
    reviewed["summary"]["human_review_pending"] = 0
    reviewed["blind_review"] = {
        "review_id": str(packet.get("review_id") or ""),
        "content_fingerprint": fingerprint,
        "finalized_at": _utc_now(),
    }
    return reviewed


class OrchestratorBenchmarkExecutor:
    def __init__(
        self,
        settings: MarySettings,
        database: MaryDatabase,
        *,
        provider: str,
        model: str,
        effort: str,
        release_id: str,
        timeout_seconds: int,
    ) -> None:
        self.settings = settings
        self.database = database
        self.provider = str(provider).strip().casefold()
        self.model = str(model).strip()
        self.effort = str(effort).strip().casefold() or "medium"
        self.release_id = str(release_id).strip()
        self.timeout_seconds = max(30, int(timeout_seconds))
        self.orchestrator = ChatOrchestrator(settings, database)
        status = ErpReleaseCatalog(settings.root).status(self.release_id)
        if status.get("state") != "ready" or status.get("freshness") != "fresh":
            raise CodeAnalysisBenchmarkError(
                "A release do benchmark precisa estar inventariada e atualizada."
            )
        self.code_index_status = JavaCodeIndex(settings.root).status(self.release_id)
        if int(self.code_index_status.get("sources") or 0) < 1:
            raise CodeAnalysisBenchmarkError(
                "A release selecionada ainda não possui fontes no índice de código."
            )
        if not self.orchestrator.provider_status().get(self.provider, False):
            raise CodeAnalysisBenchmarkError(
                f"Provedor indisponível para o benchmark: {self.provider}"
            )

    def __call__(self, case: BenchmarkCase, enabled: bool) -> dict[str, Any]:
        conversation_id = self.orchestrator.new_conversation(
            self.provider,
            self.model,
            effort=self.effort,
            defer_provider_start=True,
            vr_mode="ultra",
        )
        events: list[RuntimeEvent] = []
        done = threading.Event()

        def callback(event: RuntimeEvent) -> None:
            events.append(event)
            if event.kind == "turn_completed":
                done.set()

        started = time.monotonic()
        self.orchestrator.send(
            conversation_id,
            case.question,
            callback,
            use_vr=True,
            vr_mode="ultra",
            code_analysis_enabled=enabled,
            code_analysis_release=self.release_id,
            response_mode=case.response_mode,
        )
        if not done.wait(self.timeout_seconds):
            self.orchestrator.interrupt(conversation_id)
            raise CodeAnalysisBenchmarkError(
                f"Timeout no caso {case.case_id}, variante {'on' if enabled else 'off'}."
            )
        self.orchestrator.drain_turn_finalizations(timeout=30)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        messages = self.database.messages(conversation_id)
        answer = next(
            (
                str(row["content"] or "")
                for row in reversed(messages)
                if str(row["role"] or "") == "assistant"
            ),
            "",
        )
        event_counts = Counter(event.kind for event in events)
        lifecycle = [
            _event_summary(event)
            for event in events
            if event.kind in {"agent_started", "agent_completed", "agent_failed"}
        ]
        code_events = [
            event
            for event in events
            if str(event.payload.get("worker_id") or "") == "fanout_codigo"
        ]
        code_citations = [
            str(citation)
            for event in code_events
            if event.kind == "agent_completed"
            for citation in event.payload.get("citations") or []
        ]
        agent_tokens = sum(
            _usage_total(event.payload.get("tokenUsage") or {})
            for event in events
            if event.kind == "agent_usage"
        )
        conversation = self.database.get_conversation(conversation_id)
        main_tokens = int(conversation["total_processed_tokens"] or 0) if conversation else 0
        status = "completed" if answer and not event_counts.get("error") else "failed"
        return {
            "variant": "on" if enabled else "off",
            "conversation_id": conversation_id,
            "status": status,
            "answer": answer,
            "elapsed_ms": elapsed_ms,
            "main_tokens": main_tokens,
            "agent_tokens": agent_tokens,
            "total_tokens": main_tokens + agent_tokens,
            "event_counts": dict(sorted(event_counts.items())),
            "workers": lifecycle,
            "code_agent_started": any(
                event.kind == "agent_started" for event in code_events
            ),
            "code_agent_status": next(
                (
                    str(event.payload.get("status") or "completed")
                    for event in reversed(code_events)
                    if event.kind == "agent_completed"
                ),
                "failed"
                if any(event.kind == "agent_failed" for event in code_events)
                else "disabled",
            ),
            "code_citations": code_citations,
        }


def execute_benchmark_suite(
    settings: MarySettings,
    database: MaryDatabase,
    suite_path: str | Path,
    *,
    provider: str,
    model: str,
    effort: str = "medium",
    timeout_seconds: int = 600,
    max_cases: int = 0,
    intake_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    suite = load_benchmark_suite(suite_path)
    if int(max_cases) < 0:
        raise CodeAnalysisBenchmarkError("--max-cases não pode ser negativo.")
    if (
        suite.data_classification == "anonymized"
        and max_cases
        and int(max_cases) != len(suite.cases)
    ):
        raise CodeAnalysisBenchmarkError(
            "--max-cases não pode reduzir uma suíte real congelada; execute todos "
            "os casos ou use uma suíte synthetic para ensaios."
        )
    intake_manifest = (
        load_benchmark_intake_manifest(intake_manifest_path)
        if intake_manifest_path
        else None
    )
    preflight = preflight_benchmark_suite(
        suite, settings.root, intake_manifest=intake_manifest
    )
    if not preflight["ready"]:
        problems = list(preflight["errors"])
        problems.extend(
            f"{item['case_id']}: {error}"
            for item in preflight["cases"]
            for error in item["errors"]
        )
        raise CodeAnalysisBenchmarkError(
            "Preflight do benchmark reprovado: " + "; ".join(problems)
        )
    executor = OrchestratorBenchmarkExecutor(
        settings,
        database,
        provider=provider,
        model=model,
        effort=effort,
        release_id=suite.release_id,
        timeout_seconds=timeout_seconds,
    )
    report = run_paired_benchmark(suite, executor, max_cases=max_cases)
    report["provider"] = provider
    report["model"] = model
    report["effort"] = effort
    report["preflight"] = preflight
    report["code_index"] = executor.code_index_status
    output_dir = settings.index_dir / "evaluations" / "code-analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{suite.suite_id}-{report['benchmark_id']}.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(output)
    return {**report, "report_path": settings.relative_path(output)}


def benchmark_template() -> dict[str, Any]:
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "suite_id": "chamados-causa-codigo-v1",
        "release_id": "current",
        "data_classification": "anonymized",
        "candidate_pool_size": 0,
        "selection_method": (
            "Descrever a regra aplicada ao conjunto de candidatos antes da execução."
        ),
        "anonymization_review_id": "anon-review-001",
        "cases": [
            {
                "case_id": "chamado-001",
                "title": "Substituir por título anonimizado",
                "question": "Substituir pela pergunta anonimizada do chamado.",
                "response_mode": "support",
                "module": "VRPdv",
                "target_jars": ["VRPdv.jar"],
                "known_root_cause": (
                    "Substituir pela causa-raiz confirmada após a resolução."
                ),
                "root_cause_evidence": (
                    "Descrever a evidência local que confirmou a causa-raiz."
                ),
                "resolved_at": "AAAA-MM-DD",
                "expected_terms": ["causa conhecida"],
                "expected_code_symbols": ["ClasseOuMetodoConfirmado"],
                "expected_citation_sources": ["VRPdv.jar"],
                "forbidden_terms": ["hipótese já descartada"],
            }
        ],
    }


def _event_summary(event: RuntimeEvent) -> dict[str, Any]:
    return {
        "kind": event.kind,
        "worker_id": str(event.payload.get("worker_id") or ""),
        "worker_name": str(event.payload.get("worker_name") or ""),
        "module": str(event.payload.get("module") or ""),
        "status": str(event.payload.get("status") or ""),
        "output": str(event.payload.get("output") or "")[:600],
        "error": str(event.payload.get("error") or "")[:400],
    }


def _usage_total(payload: dict[str, Any]) -> int:
    last = payload.get("last") or {}
    if not isinstance(last, dict):
        return 0
    total = int(last.get("totalTokens") or last.get("total_tokens") or 0)
    if total:
        return total
    return (
        int(last.get("inputTokens") or last.get("input_tokens") or 0)
        + int(last.get("outputTokens") or last.get("output_tokens") or 0)
        + int(last.get("reasoningTokens") or last.get("reasoning_tokens") or 0)
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        dict.fromkeys(str(item).strip() for item in value if str(item).strip())
    )


def _identifier(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", normalized):
        raise CodeAnalysisBenchmarkError(f"Identificador inválido em {field}.")
    return normalized


def _normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _contains_placeholder(values: tuple[str, ...]) -> bool:
    searchable = _normalize(" ".join(values))
    return any(_normalize(marker) in searchable for marker in PLACEHOLDER_MARKERS)


def _benchmark_sensitive_findings(suite: BenchmarkSuite) -> list[dict[str, str]]:
    fields: list[tuple[str, str, str]] = [
        ("", "selection_method", suite.selection_method),
    ]
    for case in suite.cases:
        fields.extend(
            [
                (case.case_id, "title", case.title),
                (case.case_id, "question", case.question),
                (case.case_id, "known_root_cause", case.known_root_cause),
                (case.case_id, "root_cause_evidence", case.root_cause_evidence),
                *(
                    (case.case_id, f"expected_terms[{index}]", value)
                    for index, value in enumerate(case.expected_terms)
                ),
                *(
                    (case.case_id, f"forbidden_terms[{index}]", value)
                    for index, value in enumerate(case.forbidden_terms)
                ),
            ]
        )
    findings: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for case_id, field, value in fields:
        matches: list[tuple[str, str]] = []
        for kind, pattern in SENSITIVE_TEXT_PATTERNS:
            matches.extend((kind, item.group(0)) for item in pattern.finditer(value))
        for candidate in re.findall(r"(?<!\d)[\d./-]{11,18}(?!\d)", value):
            digits = re.sub(r"\D", "", candidate)
            if _valid_cpf(digits):
                matches.append(("cpf", candidate))
            elif _valid_cnpj(digits):
                matches.append(("cnpj", candidate))
        for kind, matched in matches:
            fingerprint = hashlib.sha256(
                f"{kind}:{matched.casefold()}".encode("utf-8")
            ).hexdigest()[:12]
            key = (case_id, field, kind, fingerprint)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "case_id": case_id,
                    "field": field,
                    "kind": kind,
                    "fingerprint": fingerprint,
                }
            )
    return findings


def _valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    numbers = [int(item) for item in digits]
    first = (sum(numbers[index] * (10 - index) for index in range(9)) * 10) % 11
    first = 0 if first == 10 else first
    second = (sum(numbers[index] * (11 - index) for index in range(10)) * 10) % 11
    second = 0 if second == 10 else second
    return numbers[9:] == [first, second]


def _valid_cnpj(digits: str) -> bool:
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    numbers = [int(item) for item in digits]

    def check(values: list[int], weights: list[int]) -> int:
        remainder = sum(value * weight for value, weight in zip(values, weights)) % 11
        return 0 if remainder < 2 else 11 - remainder

    first = check(numbers[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = check(numbers[:12] + [first], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return numbers[12:] == [first, second]


def _valid_past_date(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc)


def _blind_packet_fingerprint(packet: dict[str, Any]) -> str:
    immutable = {
        "review_id": str(packet.get("review_id") or ""),
        "benchmark_id": str(packet.get("benchmark_id") or ""),
        "cases": [
            {
                "case_id": str(item.get("case_id") or ""),
                "title": str(item.get("title") or ""),
                "question": str(item.get("question") or ""),
                "module": str(item.get("module") or ""),
                "responses": item.get("responses") or {},
            }
            for item in packet.get("cases") or []
            if isinstance(item, dict)
        ],
    }
    encoded = json.dumps(
        immutable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _review_score(value: object, case_id: str, label: str, field: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise CodeAnalysisBenchmarkError(
            f"Caso {case_id}, resposta {label}: {field} precisa ser uma nota de 0 a 4."
        ) from exc
    if not math.isfinite(score) or score < 0 or score > 4:
        raise CodeAnalysisBenchmarkError(
            f"Caso {case_id}, resposta {label}: {field} precisa ficar entre 0 e 4."
        )
    return score


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "BenchmarkCase",
    "BenchmarkSuite",
    "CodeAnalysisBenchmarkError",
    "OrchestratorBenchmarkExecutor",
    "apply_blind_review",
    "audit_benchmark_intake",
    "benchmark_template",
    "benchmark_suite_fingerprint",
    "build_blind_review_packet",
    "build_benchmark_intake_manifest",
    "compare_variants",
    "execute_benchmark_suite",
    "load_benchmark_suite",
    "load_benchmark_intake_manifest",
    "preflight_benchmark_suite",
    "run_paired_benchmark",
    "score_variant",
    "summarize_results",
    "verify_benchmark_intake_manifest",
]

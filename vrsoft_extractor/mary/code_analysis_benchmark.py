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
PLACEHOLDER_MARKERS = {
    "substituir",
    "classeoumetodoconfirmado",
    "causa conhecida",
    "hipotese ja descartada",
    "hipótese já descartada",
}


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
    expected_terms: tuple[str, ...]
    expected_code_symbols: tuple[str, ...]
    expected_citation_sources: tuple[str, ...]
    forbidden_terms: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkSuite:
    suite_id: str
    release_id: str
    data_classification: str
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
    return BenchmarkSuite(suite_id, release_id, classification, tuple(cases))


def preflight_benchmark_suite(
    suite: BenchmarkSuite,
    root: str | Path,
    *,
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
    errors: list[str] = []
    warnings: list[str] = []
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
) -> dict[str, Any]:
    suite = load_benchmark_suite(suite_path)
    preflight = preflight_benchmark_suite(suite, settings.root)
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
    "benchmark_template",
    "build_blind_review_packet",
    "compare_variants",
    "execute_benchmark_suite",
    "load_benchmark_suite",
    "preflight_benchmark_suite",
    "run_paired_benchmark",
    "score_variant",
    "summarize_results",
]

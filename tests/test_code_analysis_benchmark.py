from __future__ import annotations

import json
from pathlib import Path

import pytest

from vrsoft_extractor.mary.code_analysis_benchmark import (
    CodeAnalysisBenchmarkError,
    apply_blind_review,
    audit_benchmark_intake,
    benchmark_template,
    build_benchmark_intake_manifest,
    build_blind_review_packet,
    execute_benchmark_suite,
    load_benchmark_suite,
    preflight_benchmark_suite,
    run_paired_benchmark,
    verify_benchmark_intake_manifest,
)
from vrsoft_extractor.mary.cli import build_parser
from vrsoft_extractor.mary.cli import main as cli_main


def _write_suite(path: Path, *, classification: str = "synthetic") -> Path:
    payload = {
        "schema_version": 1,
        "suite_id": "resolved-code-cases",
        "release_id": "r1",
        "data_classification": classification,
        "candidate_pool_size": 2,
        "selection_method": "Seleção sintética determinada antes da execução.",
        "anonymization_review_id": "anon-review-test",
        "cases": [
            {
                "case_id": "case-1",
                "title": "Falha de fechamento",
                "question": "Por que o fechamento não conclui?",
                "response_mode": "support",
                "module": "VRPdv",
                "target_jars": ["VRPdv.jar"],
                "known_root_cause": "A validação final rejeita o estado aberto.",
                "root_cause_evidence": "Correção reproduzida e confirmada em teste.",
                "resolved_at": "2026-01-10",
                "expected_terms": ["validação final"],
                "expected_code_symbols": ["CaixaService.fechar"],
                "expected_citation_sources": ["VRPdv.jar"],
                "forbidden_terms": ["corrigir tabela manualmente"],
            },
            {
                "case_id": "case-2",
                "title": "Erro fiscal",
                "question": "Qual a causa confirmada do erro fiscal?",
                "response_mode": "support",
                "module": "VRPdv",
                "target_jars": ["VRPdv.jar"],
                "known_root_cause": "O retorno fiscal rejeitado interrompe o envio.",
                "root_cause_evidence": "Stack trace e correção confirmaram o fluxo.",
                "resolved_at": "2026-01-11",
                "expected_terms": ["retorno rejeitado"],
                "expected_code_symbols": ["NfeService.enviar"],
                "expected_citation_sources": ["VRPdv.jar"],
                "forbidden_terms": [],
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_real_suite(path: Path, *, sensitive: bool = False) -> Path:
    payload = json.loads(_write_suite(path).read_text(encoding="utf-8"))
    payload["data_classification"] = "anonymized"
    payload["candidate_pool_size"] = 12
    payload["selection_method"] = (
        "Amostragem dos chamados encerrados com causa confirmada em código."
    )
    base_cases = payload["cases"]
    payload["cases"] = []
    modules = ["VRPdv", "VRMaster", "VRAutorizador", "VRPdv", "VRMaster"]
    jars = [
        "VRPdv.jar",
        "VRMaster.jar",
        "VRAutorizador.jar",
        "VRPdv.jar",
        "VRMaster.jar",
    ]
    for index in range(5):
        case = dict(base_cases[index % len(base_cases)])
        case["case_id"] = f"case-{index + 1}"
        case["title"] = f"Falha resolvida {index + 1}"
        case["question"] = f"Qual componente explica a falha {index + 1}?"
        case["module"] = modules[index]
        case["target_jars"] = [jars[index]]
        case["expected_citation_sources"] = [jars[index]]
        payload["cases"].append(case)
    if sensitive:
        payload["cases"][0]["question"] = (
            "Cliente 529.982.247-25 informou contato pessoa@cliente.com."
        )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_suite_requires_anonymized_or_synthetic_cases(tmp_path: Path) -> None:
    source = _write_suite(tmp_path / "cases.json", classification="customer_raw")

    with pytest.raises(CodeAnalysisBenchmarkError, match="anonymized ou synthetic"):
        load_benchmark_suite(source)


def test_real_intake_blocks_sensitive_data_without_echoing_values(tmp_path: Path) -> None:
    suite = load_benchmark_suite(_write_real_suite(tmp_path / "real.json", sensitive=True))

    audit = audit_benchmark_intake(suite)
    rendered = json.dumps(audit, ensure_ascii=False)

    assert audit["ready"] is False
    assert {item["kind"] for item in audit["sensitive_findings"]} >= {"cpf", "email"}
    assert "529.982.247-25" not in rendered
    assert "pessoa@cliente.com" not in rendered
    with pytest.raises(CodeAnalysisBenchmarkError, match="Intake reprovado"):
        build_benchmark_intake_manifest(suite)


@pytest.mark.parametrize(
    ("value", "expected_kind"),
    [
        ("pessoa@cliente.com", "email"),
        ("(11) 98765-4321", "telefone"),
        ("529.982.247-25", "cpf"),
        ("04.252.011/0001-10", "cnpj"),
        ("10.0.0.12", "endereco_ip"),
        ("https://cliente.local/erro", "url"),
        (r"C:\Users\cliente\erro.log", "caminho_usuario"),
        ("token=abc123", "credencial"),
    ],
)
def test_intake_sensitive_detectors(
    tmp_path: Path, value: str, expected_kind: str
) -> None:
    source = _write_suite(tmp_path / f"{expected_kind}.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["cases"][0]["question"] = f"Falha observada em {value}."
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    audit = audit_benchmark_intake(load_benchmark_suite(source))

    assert expected_kind in {
        finding["kind"] for finding in audit["sensitive_findings"]
    }
    assert value not in json.dumps(audit, ensure_ascii=False)


def test_frozen_intake_manifest_detects_any_suite_change(tmp_path: Path) -> None:
    source = _write_real_suite(tmp_path / "real.json")
    suite = load_benchmark_suite(source)
    audit = audit_benchmark_intake(suite)
    manifest = build_benchmark_intake_manifest(suite)

    assert audit["ready"] is True
    assert verify_benchmark_intake_manifest(suite, manifest)["ready"] is True

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["cases"][0]["question"] = "Pergunta modificada após o congelamento."
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    changed = load_benchmark_suite(source)
    verification = verify_benchmark_intake_manifest(changed, manifest)

    assert verification["ready"] is False
    assert any("suite_fingerprint" in item for item in verification["errors"])


def test_real_execution_cannot_reduce_the_frozen_sample(tmp_path: Path) -> None:
    source = _write_real_suite(tmp_path / "real.json")

    with pytest.raises(CodeAnalysisBenchmarkError, match="não pode reduzir"):
        execute_benchmark_suite(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            source,
            provider="codex",
            model="test",
            max_cases=1,
        )
    with pytest.raises(CodeAnalysisBenchmarkError, match="não pode ser negativo"):
        execute_benchmark_suite(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            _write_suite(tmp_path / "synthetic.json"),
            provider="codex",
            model="test",
            max_cases=-1,
        )


def test_paired_benchmark_alternates_order_and_measures_gain(tmp_path: Path) -> None:
    suite = load_benchmark_suite(_write_suite(tmp_path / "cases.json"))
    calls: list[tuple[str, bool]] = []

    def execute(case, enabled):
        calls.append((case.case_id, enabled))
        expected = case.expected_terms[0]
        symbol = case.expected_code_symbols[0]
        return {
            "variant": "on" if enabled else "off",
            "status": "completed",
            "answer": f"{expected}; {symbol}" if enabled else "Hipótese documental.",
            "elapsed_ms": 240 if enabled else 100,
            "total_tokens": 450 if enabled else 100,
            "code_agent_started": enabled,
            "code_citations": [f"VRPdv.jar · {symbol}"] if enabled else [],
        }

    report = run_paired_benchmark(suite, execute)

    assert calls == [
        ("case-1", False),
        ("case-1", True),
        ("case-2", True),
        ("case-2", False),
    ]
    assert report["case_count"] == 2
    assert report["summary"]["decisions"] == {"supports_opt_in": 2}
    assert report["summary"]["mean_objective_delta"] == 1.0
    first = report["results"][0]
    assert first["comparison"]["token_ratio"] == 4.5
    assert first["comparison"]["latency_ratio"] == 2.4
    assert first["comparison"]["code_evidence_gained"] is True
    assert first["human_review"]["preferred"] == ""


def test_template_is_valid_and_cli_requires_explicit_cost_approval(tmp_path: Path) -> None:
    source = tmp_path / "template.json"
    source.write_text(
        json.dumps(benchmark_template(), ensure_ascii=False), encoding="utf-8"
    )

    suite = load_benchmark_suite(source)
    args = build_parser().parse_args(["benchmark-code-analysis", str(source)])

    assert suite.data_classification == "anonymized"
    assert args.approve_model_usage is False


def test_preflight_checks_coverage_symbols_and_template_placeholders(
    tmp_path: Path,
) -> None:
    suite = load_benchmark_suite(_write_suite(tmp_path / "cases.json"))

    class Catalog:
        def status(self, release_id):
            assert release_id in {"r1", "current"}
            return {"state": "ready", "freshness": "fresh"}

    class Index:
        def coverage(self, release_id):
            return {
                "expected_jar_count": 46,
                "covered_jar_count": 12,
                "covered_jars": ["VRPdv.jar"],
            }

        def status(self, release_id):
            return {"sources": 100, "symbols": 200, "jar_count": 12}

        def search(self, symbol, *, release_id, limit):
            return [
                {
                    "jar_relative_path": "VRPdv.jar",
                    "qualified_name": symbol.rsplit(".", 1)[0],
                    "citation": f"VRPdv.jar · {symbol}",
                    "freshness": "fresh",
                    "classpath_resolution": "ambiguous",
                }
            ]

    class Policy:
        def status(self, release_id):
            return {"classpath_status": "partial"}

    result = preflight_benchmark_suite(
        suite,
        tmp_path,
        catalog=Catalog(),
        code_index=Index(),
        classpath_policy=Policy(),
    )
    template = load_benchmark_suite(
        _write_json(tmp_path / "template.json", benchmark_template())
    )
    template_result = preflight_benchmark_suite(
        template,
        tmp_path,
        catalog=Catalog(),
        code_index=Index(),
        classpath_policy=Policy(),
    )

    assert result["ready"] is True
    assert result["intake_manifest"]["status"] == "not_required"
    assert result["cases"][0]["symbol_checks"][0]["found"] is True
    assert result["coverage"]["classpath_status"] == "partial"
    assert template_result["ready"] is False
    assert template_result["intake_manifest"]["status"] == "invalid"
    assert "manifesto" in template_result["intake_manifest"]["errors"][0].casefold()
    assert "marcadores do template" in template_result["cases"][0]["errors"][-1]


def test_blind_review_separates_key_and_maps_human_scores(tmp_path: Path) -> None:
    suite = load_benchmark_suite(_write_suite(tmp_path / "cases.json"))

    def execute(case, enabled):
        return {
            "variant": "on" if enabled else "off",
            "status": "completed",
            "answer": f"Resposta {'com' if enabled else 'sem'} código para {case.case_id}",
            "elapsed_ms": 10,
            "total_tokens": 20,
            "code_agent_started": enabled,
            "code_citations": ["VRPdv.jar"] if enabled else [],
        }

    report = run_paired_benchmark(suite, execute)
    packet, key = build_blind_review_packet(report)
    assert "mappings" not in packet
    assert key["mappings"]
    for case in packet["cases"]:
        case["review"]["A"] = {"correctness": 4, "grounding": 3}
        case["review"]["B"] = {"correctness": 2, "grounding": 1}
        case["review"]["preferred"] = "A"
    reviewed = apply_blind_review(report, packet, key)

    for result in reviewed["results"]:
        case_id = result["case"]["case_id"]
        assert result["human_review"]["preferred"] == key["mappings"][case_id]["A"]
    assert reviewed["summary"]["human_review"]["reviewed_cases"] == 2

    packet["cases"][0]["responses"]["A"]["answer"] = "resposta adulterada"
    with pytest.raises(CodeAnalysisBenchmarkError, match="alteradas"):
        apply_blind_review(report, packet, key)

    clean_packet, clean_key = build_blind_review_packet(report)
    for case in clean_packet["cases"]:
        case["review"]["A"] = {"correctness": "NaN", "grounding": 3}
        case["review"]["B"] = {"correctness": 2, "grounding": 1}
        case["review"]["preferred"] = "A"
    with pytest.raises(CodeAnalysisBenchmarkError, match="entre 0 e 4"):
        apply_blind_review(report, clean_packet, clean_key)


def test_cli_writes_utf8_template_without_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "casos-código.json"

    assert cli_main(["benchmark-code-analysis-template", "--output", str(output)]) == 0
    assert "título anonimizado" in output.read_text(encoding="utf-8")
    assert cli_main(["benchmark-code-analysis-template", "--output", str(output)]) == 2


def test_cli_audits_and_freezes_real_cases_without_workspace_startup(
    tmp_path: Path,
) -> None:
    source = _write_real_suite(tmp_path / "real.json")
    manifest = tmp_path / "real.intake.json"

    assert cli_main(["audit-code-analysis-cases", str(source)]) == 0
    assert cli_main(
        ["freeze-code-analysis-cases", str(source), "--output", str(manifest)]
    ) == 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["suite_id"] == "resolved-code-cases"
    assert len(payload["suite_fingerprint"]) == 64
    assert payload["audit"]["sensitive_finding_count"] == 0
    assert cli_main(
        ["freeze-code-analysis-cases", str(source), "--output", str(manifest)]
    ) == 2


def test_cli_prepares_and_finalizes_separate_blind_review(tmp_path: Path) -> None:
    suite = load_benchmark_suite(_write_suite(tmp_path / "cases.json"))

    def execute(case, enabled):
        return {
            "variant": "on" if enabled else "off",
            "status": "completed",
            "answer": f"Resposta {case.case_id}",
            "elapsed_ms": 10,
            "total_tokens": 20,
            "code_agent_started": enabled,
            "code_citations": ["VRPdv.jar"] if enabled else [],
        }

    report = _write_json(tmp_path / "report.json", run_paired_benchmark(suite, execute))
    review = tmp_path / "review.json"
    key = tmp_path / "review-key.json"
    finalized = tmp_path / "reviewed.json"

    assert cli_main(
        [
            "--root",
            str(tmp_path),
            "prepare-code-analysis-review",
            str(report),
            "--output",
            str(review),
            "--key-output",
            str(key),
        ]
    ) == 0
    packet = json.loads(review.read_text(encoding="utf-8"))
    assert "mappings" not in packet
    for case in packet["cases"]:
        case["review"]["A"] = {"correctness": 4, "grounding": 4}
        case["review"]["B"] = {"correctness": 3, "grounding": 2}
        case["review"]["preferred"] = "A"
    review.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")

    assert cli_main(
        [
            "--root",
            str(tmp_path),
            "finalize-code-analysis-review",
            str(report),
            str(review),
            str(key),
            "--output",
            str(finalized),
        ]
    ) == 0
    payload = json.loads(finalized.read_text(encoding="utf-8"))
    assert payload["summary"]["human_review_pending"] == 0
    assert payload["summary"]["human_review"]["reviewed_cases"] == 2


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path

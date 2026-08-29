from __future__ import annotations

import json
from pathlib import Path

import pytest

from vrsoft_extractor.mary.code_analysis_benchmark import (
    CodeAnalysisBenchmarkError,
    benchmark_template,
    load_benchmark_suite,
    run_paired_benchmark,
)
from vrsoft_extractor.mary.cli import build_parser
from vrsoft_extractor.mary.cli import main as cli_main


def _write_suite(path: Path, *, classification: str = "anonymized") -> Path:
    payload = {
        "schema_version": 1,
        "suite_id": "resolved-code-cases",
        "release_id": "r1",
        "data_classification": classification,
        "cases": [
            {
                "case_id": "case-1",
                "title": "Falha de fechamento",
                "question": "Por que o fechamento não conclui?",
                "response_mode": "support",
                "expected_terms": ["validação final"],
                "expected_code_symbols": ["CaixaService.fechar"],
                "forbidden_terms": ["corrigir tabela manualmente"],
            },
            {
                "case_id": "case-2",
                "title": "Erro fiscal",
                "question": "Qual a causa confirmada do erro fiscal?",
                "response_mode": "support",
                "expected_terms": ["retorno rejeitado"],
                "expected_code_symbols": ["NfeService.enviar"],
                "forbidden_terms": [],
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_suite_requires_anonymized_or_synthetic_cases(tmp_path: Path) -> None:
    source = _write_suite(tmp_path / "cases.json", classification="customer_raw")

    with pytest.raises(CodeAnalysisBenchmarkError, match="anonymized ou synthetic"):
        load_benchmark_suite(source)


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


def test_cli_writes_utf8_template_without_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "casos-código.json"

    assert cli_main(["benchmark-code-analysis-template", "--output", str(output)]) == 0
    assert "título anonimizado" in output.read_text(encoding="utf-8")
    assert cli_main(["benchmark-code-analysis-template", "--output", str(output)]) == 2

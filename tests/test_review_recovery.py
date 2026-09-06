"""Regression coverage for structured reviews and post-rewrite recovery."""
import json
from types import SimpleNamespace

import pytest

import test_mary_vr_ultra as ultra
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.models import EvidenceBundle, EvidenceCandidate, QueryProfile
from vrsoft_extractor.mary.supervision import (
    FinalResponseValidation, ResponseViolation, build_controlled_failure,
    normalize_review_claims,
)


def test_operational_review_preserves_separate_structured_findings(monkeypatch):
    orch = object.__new__(ChatOrchestrator)
    monkeypatch.setattr(orch, "_run_ephemeral_turn", lambda *a, **k: json.dumps({
        "supported": False,
        "unsupported_claims": [
            {"claim": "Configuração do rodapé", "reason": "Sem comprovação."},
            {"claim": "Importação por marca", "reason": "Não documentada."},
        ],
    }))
    violations = orch._check_operational_evidence(
        "c", "r", None, None, "Pedido de compra",
        SimpleNamespace(answer_markdown="Procedimento"), SimpleNamespace(candidates=[]))
    assert len(violations) == 2
    assert "Sem comprovação" in violations[0].detail
    answer = build_controlled_failure(FinalResponseValidation(
        verdict="reject", missing_sections=tuple(v.detail for v in violations)))
    assert "'claim'" not in answer and "'reason'" not in answer
    assert "- Importação por marca" in answer


def test_structured_review_is_readable_and_keeps_the_reason():
    claims = normalize_review_claims([
        {"claim": "Configuração do rodapé", "reason": "Não consta na documentação."},
        {"reason": "A importação por marca precisa ser confirmada."},
        {"unexpected": {"secret": "INTERNAL"}},
    ])
    assert len(claims) == 2
    answer = build_controlled_failure(FinalResponseValidation(
        verdict="reject", unsupported_claims=tuple(claims)))
    assert "Configuração do rodapé" in answer
    assert "Não consta na documentação" in answer
    assert "'claim'" not in answer and "'reason'" not in answer
    assert "INTERNAL" not in answer


@pytest.mark.parametrize("persistent", [False, True])
def test_direct_review_repairs_remaining_details(tmp_path, monkeypatch, persistent):
    _, _, orch, provider, cid, _ = ultra._orchestrator(tmp_path, "vr")
    monkeypatch.setattr(provider, "close", lambda: None, raising=False)
    evidence = EvidenceCandidate('known', 'wiki', 's', 0, 0, 'Pedido', 'Pedido',
                                 'functional', '', '', 'Pedido registrado.')
    orch._pending_evidence_bundles[cid] = EvidenceBundle(
        QueryProfile(query='Pedido', intents={}), candidates=(evidence,))
    monkeypatch.setattr('vrsoft_extractor.mary.orchestrator.validate_normal_response',
                        lambda *a, **k: ())
    prompts = []

    def respond(*args, **kwargs):
        prompts.append(args[4])
        if args[2] == "vr_evidence_correction":
            return "Pedido registrado."
        supported = len(prompts) == 5 and not persistent
        return json.dumps({"supported": supported, "unsupported_claims": [] if supported else [
            {"claim": "Rodapé", "reason": "Sem documentação."}]})

    monkeypatch.setattr(orch, '_run_ephemeral_turn', respond)
    try:
        answer = orch._validate_direct_response(cid, "Sempre registrado.")
        assert len(prompts) == 5
        assert "'claim'" not in answer and "'reason'" not in answer
        assert (answer == "Pedido registrado.") is not persistent
        if persistent:
            assert "Não consegui produzir" in answer
    finally:
        orch.close()


@pytest.mark.parametrize("persistently_unsupported", [False, True])
def test_review_after_rewrite_gets_bounded_repair(tmp_path, monkeypatch, persistently_unsupported):
    _, db, orch, provider, cid, events = ultra._orchestrator(tmp_path, "ultra")
    monkeypatch.setattr(provider, "close", lambda: None, raising=False)
    drafts = []
    reviews = []

    def synthesize(*args, **kwargs):
        drafts.append(args[6])
        payload = {"answer_markdown": "incomplete", "used_evidence_ids": []}
        if len(drafts) > 1:
            payload = {
                "answer_markdown": "Acesse Nota Fiscal > Saída e clique em Incluir. "
                                   "O fechamento de caixa ainda precisa ser confirmado.",
                "used_evidence_ids": ["wiki:nf-fiscal:1"],
                "answer_status": "partially_answered",
            }
        return json.dumps(payload), {}, {}

    def review(*args, **kwargs):
        reviews.append(True)
        if persistently_unsupported or len(reviews) == 1:
            return (ResponseViolation("unsupported_claims", "Rodapé sem comprovação",
                                      "Remova o detalhe do rodapé."),)
        return ()

    monkeypatch.setattr(orch, "_run_buffered_main_turn", synthesize)
    monkeypatch.setattr(orch, "_check_operational_evidence", review)
    try:
        ultra._run_send(orch, cid, events)
        answer = db.messages(cid)[-1]["content"]
        assert len(drafts) == 3 and len(reviews) == 2
        assert "Rodapé sem comprovação" in drafts[-1]
        if persistently_unsupported:
            assert "Não consegui produzir" in answer
            assert "Acesse Nota Fiscal" not in answer
        else:
            assert "Acesse Nota Fiscal" in answer
            assert "https://wiki.example/nf" in answer
            assert "Não consegui produzir" not in answer
    finally:
        orch.close()

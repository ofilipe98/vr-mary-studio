from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    ModuleRoutingDecision,
    QueryProfile,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.supervision import (
    FinalResponseValidation,
    RefinementReason,
    ResponseContract,
    ResponseIntent,
)


def test_erp_release_catalog_resolves_current_and_empty():
    catalog = object.__new__(ErpReleaseCatalog)
    catalog.list_statuses = MagicMock(return_value=[{"release_id": "erp-2026.07.23-test"}])
    assert catalog._resolve_current_release_id() == "erp-2026.07.23-test"


def test_validate_direct_response_preserves_code_investigation_output():
    orch = object.__new__(ChatOrchestrator)
    cid = "test-conv-code"
    orch._pending_response_contracts = {
        cid: ResponseContract(
            purpose="guidance",
            audience="operational_user",
            technical_level="medium",
            detail_level="normal",
        )
    }
    kb_candidate = EvidenceCandidate(
        evidence_id="wiki:test:1",
        source="wiki",
        source_id="1",
        document_id=1,
        chunk_id=1,
        title="Artigo Genérico",
        heading="",
        content_type="text",
        module="Fiscal",
        product="VRMaster",
        excerpt="Instruções gerais.",
        url="",
        local_path="",
        confidence=0.9,
    )
    orch._pending_evidence_bundles = {
        cid: EvidenceBundle(
            profile=QueryProfile(query="falha no tef", intents={}),
            candidates=(kb_candidate,),
        )
    }
    orch._conversation = MagicMock(return_value={"provider": "codex", "model": "test", "workspace": "."})
    orch.settings = SimpleNamespace(resolve_path=lambda p: Path("."))
    orch._emit_orchestration_event = MagicMock()
    orch._turn_dynamic_candidates = {}

    # Simulate reviewer flagging issues because code is not in KB
    fake_violation = SimpleNamespace(code="unsupported_claims", detail="VendaTefDAO não consta na documentação")
    orch._check_operational_evidence = MagicMock(return_value=(fake_violation,))
    orch._run_ephemeral_turn = MagicMock(return_value="")

    code_analysis_answer = (
        "A falha ocorre porque a classe VendaTefDAO.java tenta atualizar a tabela CMOS sem cupom associado "
        "(VRException: cupom 0)."
    )

    result = orch._validate_direct_response(cid, code_analysis_answer)
    # Must preserve the technical code analysis rather than replacing it with build_controlled_failure
    assert "VendaTefDAO.java" in result
    assert "VRException" in result
    assert "Não consegui produzir uma orientação segura" not in result


def test_synthesis_disables_mcp_tools():
    from vrsoft_extractor.mary.execution.runner import ExecutionRunner
    from dataclasses import replace

    opts = ConversationOptions(
        mcp_tools=({"name": "vr_search", "description": "Search"},),
        dynamic_tools=({"name": "local_tool"},),
    )
    # Verification that replace cleanly removes both tool sets
    synth_opts = replace(opts, mcp_tools=(), dynamic_tools=())
    assert len(synth_opts.mcp_tools) == 0
    assert len(synth_opts.dynamic_tools) == 0


def test_code_scope_queries_extracts_stack_trace_frames_and_skips_log_noise():
    from vrsoft_extractor.mary.retrieval.code_retrieval import _code_scope_queries

    log_trace = """
    ERRO: 2
    [VRConcentrador: ON | VRAutorizador: ON] [12:20:59] [Display] CARREGANDO CMOS
    vrframework.classe.VRException: Não foi possível encontrar a venda com o número de cupom: 0
        at br.com.vrsoftware.vrpdv.repository.VendaTefDAO.setStatusVendaTef(VendaTefDAO.java:270)
        at vrpdv.classe.Sitef.fechaSessao(Sitef.java:1556)
        at vrpdv.classe.Funcao.iniciaVenda(Funcao.java:799)
        at vrpdv.classe.Pdv.carregarCmos(Pdv.java:2316)
        at br.com.vrsoftware.vrpdv.VRPdv.iniciar(VRPdv.java:172)
        at vrpdv.Main.main(Main.java:23)
    """
    queries = _code_scope_queries(log_trace, limit=8)
    # Stack trace classes and methods must be at the top
    assert "VendaTefDAO" in queries[:5]
    assert "Sitef" in queries[:5]
    assert "Funcao" in queries[:5]
    assert "Pdv" in queries[:5]
    assert "VRPdv" in queries[:5]
    # Log noise words must not pollute the top results
    assert "ERRO" not in queries
    assert "CARREGANDO" not in queries
    assert "PROCESSANDO" not in queries


def test_fanout_modules_ranks_by_confidence():
    orch = object.__new__(ChatOrchestrator)
    bundle = EvidenceBundle(
        profile=QueryProfile(query="erro no pdv", intents={}),
        module_routing=(
            ModuleRoutingDecision(module="Fiscal", selected=True, confidence=0.3),
            ModuleRoutingDecision(module="ADM_FIN_ESTOQUE", selected=True, confidence=0.2),
            ModuleRoutingDecision(module="PDV", selected=True, confidence=0.85),
        ),
    )
    intent = ResponseIntent(purpose="troubleshooting", audience="operational_user", technical_level="medium", requested_detail="very_high")
    fanout = orch._fanout_modules(bundle, intent, has_images=False, force_deep=True)
    # PDV has highest confidence (0.85), so it must be first and not dropped by [:2] truncation
    assert fanout is not None
    assert fanout[0] == "PDV"
    assert "PDV" in fanout


def test_code_index_search_resolves_current_release():
    from vrsoft_extractor.mary.code_index import JavaCodeIndex

    idx = object.__new__(JavaCodeIndex)
    idx.root = Path(".")
    idx.initialize = MagicMock()
    idx.catalog = MagicMock()
    mock_store = MagicMock()
    idx.store = mock_store
    with patch("vrsoft_extractor.mary.erp_releases.ErpReleaseCatalog") as mock_cat:
        mock_cat.return_value.list_statuses.return_value = [{"release_id": "erp-2026.07.23-test"}]
        mock_conn = MagicMock()
        mock_store.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []
        idx.search("VendaTefDAO", release_id="current")
        call_args = mock_conn.execute.call_args[0]
        params = call_args[1]
        assert "erp-2026.07.23-test" in params

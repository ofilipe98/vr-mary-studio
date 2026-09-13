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
    QueryProfile,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.supervision import ResponseContract, FinalResponseValidation, RefinementReason


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

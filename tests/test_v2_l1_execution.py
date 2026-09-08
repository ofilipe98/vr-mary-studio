"""
Contratos e testes de separação da execução e recuperação (Lote L1).

Valida os módulos vrsoft_extractor.mary.execution (contracts e runner)
e vrsoft_extractor.mary.retrieval (service), garantindo:
1. Independência absoluta de Qt/QML no núcleo de execução.
2. Paridade comportamental da fachada RetrievalService com KnowledgeRouter.
3. Planejamento determinístico de estágios no ExecutionRunner.
4. Isolamento e contratos estritos de ExecutionContext e StageExecutionResult.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.execution import (
    ExecutionContext,
    ExecutionRunner,
    ResearchFanoutPlan,
    ResearchStagePlan,
    StageExecutionResult,
    StageStatus,
)
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.models import (
    EvidenceBundle,
    KnowledgeDocument,
    ModelRef,
    QueryProfile,
)
from vrsoft_extractor.mary.retrieval import RetrievalService


# ---------------------------------------------------------------------------
# 2. Execution Contracts (Context, Stages, Results)
# ---------------------------------------------------------------------------

class TestExecutionContracts:
    def test_execution_context_initialization_and_elapsed(self) -> None:
        ctx = ExecutionContext(
            conversation_id="c-fanout-1",
            run_id="run-abc-123",
            workspace=Path("/test/workspace"),
            owner_message_id=42,
        )
        assert ctx.conversation_id == "c-fanout-1"
        assert ctx.run_id == "run-abc-123"
        assert ctx.workspace == Path("/test/workspace")
        assert ctx.owner_message_id == 42
        assert not ctx.cancelled
        assert ctx.elapsed_seconds >= 0.0
        assert ctx.metadata == {}

    def test_stage_execution_result_properties(self) -> None:
        success = StageExecutionResult(
            stage_id="stage_fiscal",
            worker_id="fanout_fiscal",
            role="module_research",
            status=StageStatus.COMPLETED,
            output={"findings": 3},
            duration_seconds=1.45,
        )
        assert success.succeeded
        assert success.status == StageStatus.COMPLETED
        assert success.error == ""

        failure = StageExecutionResult(
            stage_id="stage_contabil",
            worker_id="fanout_contabil",
            role="module_research",
            status=StageStatus.FAILED,
            error="Timeout in model communication",
            duration_seconds=5.0,
        )
        assert not failure.succeeded
        assert failure.status == StageStatus.FAILED
        assert "Timeout" in failure.error

    def test_research_stage_plan_serialization(self) -> None:
        plan = ResearchStagePlan(
            id="fanout_fiscal",
            agent_id="fanout_fiscal",
            label="Pesquisador Fiscal",
            role="module_research",
            module="Fiscal",
            source="wiki,kb",
            task="Pesquisar módulo Fiscal",
            reason="Especialista do módulo",
            model={"provider": "codex", "model": "gpt-5"},
            effort="low",
            final=False,
            required=True,
            priority=90,
        )
        d = plan.to_dict()
        assert d["id"] == "fanout_fiscal"
        assert d["agent"] == "vr_fanout_fiscal"
        assert d["worker_id"] == "fanout_fiscal"
        assert d["worker_name"] == "Pesquisador Fiscal"
        assert d["role"] == "module_research"
        assert d["required"] is True


# ---------------------------------------------------------------------------
# 3. RetrievalService Facade Contract & Parity
# ---------------------------------------------------------------------------

class TestRetrievalServiceContract:
    @pytest.fixture
    def setup_retrieval(self, tmp_path: Path):
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        db = MaryDatabase(settings.database_path, root=settings.root)
        db.upsert_document(KnowledgeDocument(
            source="wiki",
            source_id="doc-fiscal",
            source_origin="vrwiki",
            title="Manual Fiscal",
            url="https://wiki.vr.internal/fiscal",
            markdown="Instruções sobre apuração de ICMS e SPED Fiscal no sistema.",
            module="Fiscal",
            review_status="approved",
            content_hash="h-fiscal-1",
        ))
        router = KnowledgeRouter(db, settings.root)
        service = RetrievalService(router)
        return service, router

    def test_retrieval_service_search_delegation(self, setup_retrieval) -> None:
        service, router = setup_retrieval
        res = service.search("ICMS SPED", limit=5)
        assert isinstance(res, dict)
        assert res["total"] >= 1
        assert res["results"][0]["source_origin"] == "vrwiki"
        assert "Manual Fiscal" in res["results"][0]["title"]

    def test_retrieval_service_route_and_classify_parity(self, setup_retrieval) -> None:
        service, router = setup_retrieval
        bundle = service.route("ICMS SPED")
        assert isinstance(bundle, EvidenceBundle)
        assert len(bundle.candidates) >= 1

        profile = service.classify("ICMS SPED")
        assert isinstance(profile, QueryProfile)
        assert profile.query == "ICMS SPED"

        # Enabled origins parity
        assert service.enabled_origins("wiki") == router._enabled_origins("wiki")


# ---------------------------------------------------------------------------
# 4. ExecutionRunner Planning and Stage Coordination
# ---------------------------------------------------------------------------

class TestExecutionRunnerContract:
    def test_runner_plan_fanout_stages_structure(self, tmp_path: Path) -> None:
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        main_model = ModelRef(provider="codex", model="gpt-5", display_name="Codex GPT-5")

        mock_retrieval = MagicMock()
        mock_emitter = MagicMock()
        mock_ephemeral = MagicMock()
        mock_buffered = MagicMock()

        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=mock_retrieval,
            event_emitter=mock_emitter,
            ephemeral_turn_runner=mock_ephemeral,
            buffered_turn_runner=mock_buffered,
            looks_like_final_envelope=lambda x: False,
        )

        plan = runner.plan_fanout(
            run_id="run-test-plan-1",
            modules=("Fiscal", "Contabil"),
            main_model=main_model,
            synthesis_effort="medium",
            code_analysis_enabled=True,
            code_analysis_release="vr-2026.1",
        )

        assert isinstance(plan, ResearchFanoutPlan)
        assert plan.run_id == "run-test-plan-1"
        assert plan.modules == ("Fiscal", "Contabil")

        stage_ids = [s["id"] for s in plan.runtime_stages]
        assert "fanout_fiscal" in stage_ids
        assert "fanout_contabil" in stage_ids
        assert "fanout_codigo" in stage_ids
        assert "fanout_synthesis" in stage_ids

        synth_stage = next(s for s in plan.runtime_stages if s["id"] == "fanout_synthesis")
        assert synth_stage["final"] is True
        assert synth_stage["effort"] == "medium"

        code_stage = next(s for s in plan.runtime_stages if s["id"] == "fanout_codigo")
        assert code_stage["final"] is False
        assert code_stage["release_id"] == "vr-2026.1"

    def test_orchestrator_wires_execution_and_retrieval(self, tmp_path: Path) -> None:
        from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        db = MaryDatabase(settings.database_path, root=settings.root)
        orch = ChatOrchestrator(settings, db)
        assert hasattr(orch, "retrieval_service")
        assert isinstance(orch.retrieval_service, RetrievalService)
        assert hasattr(orch, "execution_runner")
        assert isinstance(orch.execution_runner, ExecutionRunner)

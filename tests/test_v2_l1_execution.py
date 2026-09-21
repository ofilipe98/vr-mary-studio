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

import json
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
    UltraSourceFanoutPlan,
)
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    KnowledgeDocument,
    ModelRef,
    QueryProfile,
)
from vrsoft_extractor.mary.retrieval import RetrievalService
from vrsoft_extractor.mary.supervision import ResponseIntent, build_response_contract


def _report_json(claim: str, evidence_ids: list[str], *, status: str = "found") -> str:
    return json.dumps(
        {
            "source_status": status,
            "findings": [
                {
                    "claim": claim,
                    "evidence_ids": evidence_ids,
                    "kind": "fact",
                    "confidence": 0.9,
                }
            ],
            "sources": list(evidence_ids),
        }
    )


def _synthesis_json(answer: str, evidence_ids: list[str]) -> str:
    return json.dumps(
        {
            "answer_status": "answered",
            "answer_markdown": answer,
            "used_evidence_ids": evidence_ids,
            "warnings": [],
            "missing_information": [],
            "follow_up_suggestions": [],
        }
    )


def _candidate(evidence_id: str, *, source: str = "wiki", local_path: str = "") -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=evidence_id,
        source=source,
        source_id=evidence_id,
        document_id=1,
        chunk_id=0,
        title=f"Título {evidence_id}",
        heading="",
        content_type=source,
        module="Fiscal",
        product="",
        excerpt=f"Conteúdo de {evidence_id}",
        score=0.8,
        local_path=local_path,
    )


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
            markdown="Instruções sobre apuração de ICMS e SPED Fiscal no sistema. Escopo global Ultra.",
            module="Fiscal",
            review_status="approved",
            content_hash="h-fiscal-1",
        ))
        db.upsert_document(KnowledgeDocument(
            source="wiki",
            source_id="doc-pdv-endoo",
            source_origin="endoo",
            title="Manual PDV complementar",
            url="https://endoo.example/pdv",
            markdown="Orientações complementares do escopo global Ultra no PDV.",
            module="PDV",
            review_status="approved",
            content_hash="h-pdv-endoo-1",
        ))
        db.upsert_document(KnowledgeDocument(
            source="kb",
            source_id="kb-estoque",
            source_origin="movidesk",
            title="Inventário e saldo",
            url="https://kb.example/estoque",
            markdown="Procedimento para inventário e conferência de saldo.",
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="h-kb-1",
        ))
        db.upsert_document(KnowledgeDocument(
            source="schema",
            source_id="schema-produto",
            source_origin="local",
            title="Tabela produto",
            url="",
            markdown="A tabela produto armazena o identificador e a descrição.",
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="h-schema-1",
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

    def test_route_source_is_global_and_strictly_source_scoped(
        self, setup_retrieval
    ) -> None:
        service, _router = setup_retrieval

        wiki = service.route_source("escopo global Ultra", "wiki")
        assert {item.source for item in wiki.candidates} == {"wiki"}
        assert {item.module for item in wiki.candidates} >= {"Fiscal", "PDV"}
        wiki_report = wiki.source_report("wiki")
        assert wiki_report is not None
        assert {item.source_origin for item in wiki_report.origin_reports} == {
            "vrwiki",
            "endoo",
        }

        kb = service.route_source("inventário saldo", "kb")
        assert kb.candidates and {item.source for item in kb.candidates} == {"kb"}
        schema = service.route_source("tabela produto", "schema")
        assert schema.candidates and {item.source for item in schema.candidates} == {
            "schema"
        }

    def test_route_source_rejects_unknown_source(self, setup_retrieval) -> None:
        service, _router = setup_retrieval
        with pytest.raises(ValueError, match="Fonte inválida"):
            service.route_source("consulta", "code")

    def test_route_source_wiki_reports_exhausted_origin_and_keeps_bundle(
        self, setup_retrieval
    ) -> None:
        service, _router = setup_retrieval

        bundle = service.route_source("apuração de ICMS e SPED Fiscal", "wiki")

        assert bundle.candidates
        assert {item.source_origin for item in bundle.candidates} == {"vrwiki"}
        report = bundle.source_report("wiki")
        assert report is not None
        assert report.status == "found"
        statuses = {
            item.source_origin: item.status for item in report.origin_reports
        }
        assert statuses == {"vrwiki": "found", "endoo": "exhausted"}

    def test_route_source_wiki_isolates_origin_failure(
        self, setup_retrieval, monkeypatch
    ) -> None:
        service, router = setup_retrieval
        original = router._search_lane_origin

        def flaky(profile, source, *, module="", source_origin=""):
            if source_origin == "endoo":
                raise RuntimeError("endoo fora do ar")
            return original(
                profile, source, module=module, source_origin=source_origin
            )

        monkeypatch.setattr(router, "_search_lane_origin", flaky)

        bundle = service.route_source("escopo global Ultra", "wiki")

        assert bundle.candidates
        assert all(
            item.source_origin == "vrwiki" for item in bundle.candidates
        )
        report = bundle.source_report("wiki")
        assert report is not None
        assert report.status == "found"
        statuses = {
            item.source_origin: (item.status, item.error)
            for item in report.origin_reports
        }
        assert statuses["vrwiki"] == ("found", "")
        assert statuses["endoo"][0] == "unavailable"
        assert "endoo" in statuses["endoo"][1]
        assert any("endoo" in warning for warning in bundle.warnings)


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

    def test_runner_plans_fixed_ultra_sources_and_optional_code(
        self, tmp_path: Path
    ) -> None:
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=MagicMock(),
            event_emitter=MagicMock(),
            ephemeral_turn_runner=MagicMock(),
            buffered_turn_runner=MagicMock(),
            looks_like_final_envelope=lambda _text: False,
        )
        main_model = ModelRef(provider="codex", model="gpt-5")

        without_code = runner.plan_ultra_source_fanout(
            "ultra-1", main_model, "high"
        )
        assert isinstance(without_code, UltraSourceFanoutPlan)
        assert [stage["id"] for stage in without_code.runtime_stages] == [
            "ultra_wiki",
            "ultra_kb",
            "ultra_schema",
            "ultra_synthesis",
        ]

        with_code = runner.plan_ultra_source_fanout(
            "ultra-2",
            main_model,
            "high",
            code_analysis_enabled=True,
        )
        assert [stage["id"] for stage in with_code.runtime_stages] == [
            "ultra_wiki",
            "ultra_kb",
            "ultra_schema",
            "ultra_code",
            "ultra_synthesis",
        ]

        expected = {
            "ultra_wiki": {
                "agent_id": "ultra_wiki",
                "worker_id": "ultra_wiki",
                "parent_id": "vr_ultra_fanout",
                "role": "source_research",
                "source": "wiki",
                "required": True,
                "final": False,
            },
            "ultra_kb": {
                "agent_id": "ultra_kb",
                "worker_id": "ultra_kb",
                "parent_id": "vr_ultra_fanout",
                "role": "source_research",
                "source": "kb",
                "required": True,
                "final": False,
            },
            "ultra_schema": {
                "agent_id": "ultra_schema",
                "worker_id": "ultra_schema",
                "parent_id": "vr_ultra_fanout",
                "role": "source_research",
                "source": "schema",
                "required": True,
                "final": False,
            },
            "ultra_code": {
                "agent_id": "ultra_code",
                "worker_id": "ultra_code",
                "parent_id": "vr_ultra_fanout",
                "role": "code_research",
                "source": "code",
                "required": False,
                "final": False,
            },
            "ultra_synthesis": {
                "agent_id": "ultra_synthesis",
                "worker_id": "ultra_synthesis",
                "parent_id": "vr_ultra_fanout",
                "role": "final_synthesis",
                "source": "",
                "required": True,
                "final": True,
            },
        }
        assert len(with_code.runtime_stages) == len(expected)
        for stage in with_code.runtime_stages:
            for key, value in expected[stage["id"]].items():
                assert stage[key] == value, (stage["id"], key)


class TestEvidenceCollectedBeforeParse:
    def _runner(
        self,
        tmp_path: Path,
        *,
        raw_report: str,
        collect_evidence,
        buffered_spy: list[dict],
    ) -> ExecutionRunner:
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()

        research_finished = False

        def fake_ephemeral(cid, run_id, agent_id, *args, **kwargs):
            nonlocal research_finished
            research_finished = True
            return raw_report

        def collect_after_research(run_id):
            return collect_evidence(run_id) if research_finished else ()

        def fake_buffered(cid, native_id, provider, model, effort, workspace, prompt, options, skills, **kwargs):
            buffered_spy.append({"prompt": prompt, "options": options})
            answer_ids = []
            if "read:novo" in prompt:
                answer_ids.append("read:novo")
            if "read:cache" in prompt:
                answer_ids.append("read:cache")
            return (
                _synthesis_json("Resposta apoiada nas evidências coletadas.", answer_ids),
                {},
                {},
            )

        mock_retrieval = MagicMock()
        mock_retrieval.prompt_for_role.return_value = "contexto de evidências"

        return ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=mock_retrieval,
            event_emitter=lambda *args: None,
            ephemeral_turn_runner=fake_ephemeral,
            buffered_turn_runner=fake_buffered,
            looks_like_final_envelope=lambda text: False,
            collect_evidence=collect_after_research if collect_evidence is not None else None,
        )

    def _execute(self, runner: ExecutionRunner, tmp_path: Path, run_id: str):
        bundle = EvidenceBundle(
            profile=QueryProfile(query="fluxo fiscal", intents={}, module="Fiscal"),
            candidates=(_candidate("wiki:base"),),
        )
        intent = ResponseIntent(topic="Fiscal", user_goal="answer_question")
        contract = build_response_contract(intent)
        options = ConversationOptions(vr_mode="ultra")
        context = ExecutionContext(
            conversation_id="conv-evidence",
            run_id=run_id,
            workspace=tmp_path,
        )
        return runner.execute_fanout(
            context=context,
            conversation={"provider": "codex", "model": "gpt-5"},
            native_id="native-evidence",
            provider=MagicMock(),
            options=options,
            skills=[],
            bundle=bundle,
            intent=intent,
            contract=contract,
            modules=("Fiscal",),
            request="fluxo fiscal",
        )

    def test_collected_evidence_is_allowed_before_researcher_parse(self, tmp_path: Path) -> None:
        captured: dict = {}

        def collect(run_id: str):
            captured["called"] = True
            return (_candidate("read:novo"),)

        buffered_spy: list[dict] = []
        runner = self._runner(
            tmp_path,
            raw_report=_report_json("Achado ancorado na leitura.", ["read:novo"]),
            collect_evidence=collect,
            buffered_spy=buffered_spy,
        )

        result = self._execute(runner, tmp_path, "run-evidence-1")

        assert captured.get("called") is True
        assert "read:novo" in {item.evidence_id for item in result.synthesis_bundle.candidates}
        assert result.draft is not None
        assert "read:novo" in result.draft.used_evidence_ids
        assert result.violations == ()
        finding = result.ordered[0].report.findings[0]
        assert finding.evidence_ids == ("read:novo",)
        assert finding.kind == "inference"
        assert finding.confidence == 0.65
        assert buffered_spy and not buffered_spy[0]["options"].tools_enabled
        assert buffered_spy[0]["options"].mcp_tools == ()
        assert buffered_spy[0]["options"].dynamic_tools == ()

    def test_collected_evidence_is_unavailable_without_collector(self, tmp_path: Path) -> None:
        runner = self._runner(
            tmp_path,
            raw_report=_report_json("Achado ancorado na leitura.", ["read:novo"]),
            collect_evidence=None,
            buffered_spy=[],
        )

        result = self._execute(runner, tmp_path, "run-evidence-2")

        assert "read:novo" not in {item.evidence_id for item in result.synthesis_bundle.candidates}
        assert result.draft is not None
        assert "read:novo" not in result.draft.used_evidence_ids
        finding = result.ordered[0].report.findings[0]
        assert finding.evidence_ids == ()
        assert finding.kind == "hypothesis"
        assert finding.confidence == 0.35

    def test_unknown_id_is_rejected_even_with_collector(self, tmp_path: Path) -> None:
        runner = self._runner(
            tmp_path,
            raw_report=_report_json("Referência desconhecida.", ["read:inventado"]),
            collect_evidence=lambda run_id: (_candidate("read:novo"),),
            buffered_spy=[],
        )
        result = self._execute(runner, tmp_path, "run-unknown")
        finding = result.ordered[0].report.findings[0]
        assert finding.evidence_ids == ()
        assert finding.kind == "hypothesis"
        assert "read:inventado" not in {c.evidence_id for c in result.synthesis_bundle.candidates}

    def test_collected_cache_path_is_kept_on_candidate(self, tmp_path: Path) -> None:
        captured: dict = {}

        def collect(run_id: str):
            captured["called"] = True
            return (
                _candidate(
                    "read:cache",
                    source="code",
                    local_path="indice/codigo/decompilation/Sped.java",
                ),
            )

        runner = self._runner(
            tmp_path,
            raw_report=_report_json("Achado ancorado na leitura em cache.", ["read:cache"]),
            collect_evidence=collect,
            buffered_spy=[],
        )

        result = self._execute(runner, tmp_path, "run-evidence-3")

        assert captured.get("called") is True
        merged = {item.evidence_id: item for item in result.synthesis_bundle.candidates}
        assert merged["read:cache"].local_path == "indice/codigo/decompilation/Sped.java"
        assert result.draft is not None
        assert "read:cache" in result.draft.used_evidence_ids

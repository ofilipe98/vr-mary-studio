"""
Testes de validação integrada end-to-end e entrega final (Lote L8).

Valida os requisitos de PLANO_V2_ULTRA_BUSCA_ARQUITETURA.md:
1. Fluxo integrado completo do Ultra com orçamento global (ExecutionBudget),
   cancelamento cooperativo (CancellationToken) e persistência SQLite
   (ResearchRepository).
2. Busca híbrida (FTS5 + SemanticIndex via RRF) alimentando o EvidenceBundle.
3. Expansão limitada de contexto (ContextExpander) recuperando relações de 1º grau.
4. Síntese final produzindo resposta fundamentada com citações verificáveis e envelope estruturado.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.execution import (
    CancellationToken,
    ExecutionBudget,
    ExecutionContext,
    ExecutionRunner,
    ResearchRepository,
    ExecutionCancelledError,
)
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    KnowledgeDocument,
    QueryProfile,
    SourceSearchReport,
)
from vrsoft_extractor.mary.retrieval import (
    DocumentRelation,
    RelationRepository,
    RetrievalService,
    SemanticIndex,
)
from vrsoft_extractor.mary.supervision import ResponseIntent, build_response_contract


class _SourceRetrievalStub:
    """Deterministic per-source retrieval used by the Ultra executor."""

    def __init__(self, profile: QueryProfile, candidates: dict[str, EvidenceCandidate]):
        self.profile = profile
        self.candidates = candidates

    def classify(self, _query: str) -> QueryProfile:
        return self.profile

    def route_source(self, _query: str, source: str) -> EvidenceBundle:
        candidate = self.candidates[source]
        return EvidenceBundle(
            profile=self.profile,
            candidates=(candidate,),
            source_reports=(
                SourceSearchReport(
                    source=source,
                    status="found",
                    selected_evidence_ids=(candidate.evidence_id,),
                ),
            ),
        )

    def prompt_for_role(self, _bundle, _role, module: str = "") -> str:
        return "Trecho de evidência relevante."


class TestUltraEndToEndIntegration:
    @pytest.fixture
    def environment(self, tmp_path: Path):
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        db_path = settings.database_path
        db = MaryDatabase(db_path, root=settings.root)

        # 1. Populate documents
        doc_fiscal = KnowledgeDocument(
            source="wiki",
            source_id="wiki-icms",
            source_origin="vrwiki",
            title="Apuração de ICMS",
            url="https://vr/icms",
            markdown="Apuração de ICMS mensal no Bloco C e E. Salva na TB_NFE_CABECALHO.",
            module="Fiscal",
            review_status="approved",
            content_hash="h1",
        )
        doc_schema = KnowledgeDocument(
            source="schema",
            source_id="schema-tb-nfe",
            source_origin="schema",
            title="Tabela de NFe",
            url="https://vr/tb_nfe",
            markdown="TB_NFE_CABECALHO armazena cabeçalhos fiscais e valores apurados.",
            module="Fiscal",
            review_status="approved",
            content_hash="h2",
        )
        db.upsert_document(doc_fiscal)
        db.upsert_document(doc_schema)

        # 2. Setup semantic index & relations
        sem_index = SemanticIndex(settings.root / "indice" / "semantic.db")
        sem_index.index_document("wiki-icms", doc_fiscal.markdown)
        sem_index.index_document("schema-tb-nfe", doc_schema.markdown)

        rel_repo = RelationRepository(db_path)
        rel_repo.save_relations([
            DocumentRelation("wiki-icms", "schema-tb-nfe", "schema_table", 0.95),
        ])

        research_repo = ResearchRepository(db_path)
        return settings, db, sem_index, rel_repo, research_repo

    def test_full_ultra_lifecycle_with_budget_and_persistence(
        self,
        environment,
    ) -> None:
        settings, db, sem_index, rel_repo, research_repo = environment

        # Track model turn invocations
        ephemeral_invocations: list[str] = []

        def mock_ephemeral_turn(cid, run_id, agent_id, *args, **kwargs):
            ephemeral_invocations.append(agent_id)
            source = agent_id.rsplit("_", 1)[-1]
            return json.dumps({
                "source_status": "found",
                "findings": [
                    {
                        "claim": f"Achado do agente {agent_id}",
                        "evidence_ids": [evidence_ids[source]],
                        "kind": "fact",
                        "confidence": 0.95,
                    }
                ],
                "conflicts": [],
                "missing_information": [],
                "warnings": [],
                "sources": [evidence_ids[source]],
            })

        def mock_buffered_turn(*args, **kwargs):
            envelope = {
                "answer_status": "answered",
                "answer_markdown": "A apuração de ICMS consolida os dados na TB_NFE_CABECALHO.",
                "used_evidence_ids": ["wiki-icms"],
                "warnings": [],
                "missing_information": [],
                "follow_up_suggestions": ["Verifique os CFOPs configurados."],
            }
            return json.dumps(envelope), {}, {}

        events_emitted: list[tuple[str, str, dict]] = []

        def event_emitter(cid, kind, text, payload):
            events_emitted.append((kind, text, payload))

        profile = QueryProfile(
            query="apuracao icms tabelas", intents={}, module="Fiscal"
        )
        evidence_ids = {
            "wiki": "wiki-icms",
            "kb": "kb-inventario",
            "schema": "schema-tb-nfe",
        }
        candidates = {
            source: EvidenceCandidate(
                evidence_id=evidence_ids[source],
                source=source,
                source_id=evidence_ids[source],
                document_id=1,
                chunk_id=1,
                title=f"Doc {source}",
                heading="H",
                content_type="section",
                module="Fiscal",
                product="",
                excerpt="conteudo relevante",
                url="",
            )
            for source in ("wiki", "kb", "schema")
        }
        retrieval_stub = _SourceRetrievalStub(profile, candidates)

        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=retrieval_stub,
            event_emitter=event_emitter,
            ephemeral_turn_runner=mock_ephemeral_turn,
            buffered_turn_runner=mock_buffered_turn,
            looks_like_final_envelope=lambda t: "answered" in str(t),
            repository=research_repo,
        )

        # Setup context with strict budget
        budget = ExecutionBudget(max_calls=10, max_active_seconds=30.0, reserved_synthesis_calls=1)
        cancellation = CancellationToken()

        context_1 = ExecutionContext(
            conversation_id="conv-ultra-1",
            run_id="run-step-1",
            workspace=settings.root,
            budget=budget,
            cancellation=cancellation,
        )

        # Build evidence candidates and expand through the retrieval service.
        primary_cand = candidates["wiki"]
        mock_router = MagicMock()
        mock_router.database = db
        mock_router.retrieval_revision.get.return_value = ""
        mock_router._enabled_origins.side_effect = lambda source: {
            "wiki": ("vrwiki", "endoo"),
            "kb": ("movidesk",),
            "schema": ("schema",),
        }.get(source, ())
        retrieval_service = RetrievalService(
            router=mock_router,
            semantic_index=sem_index,
            relation_repository=rel_repo,
        )
        expanded_candidates = retrieval_service.expand_candidates([primary_cand])
        assert {item.evidence_id for item in expanded_candidates} == {
            "wiki-icms",
            "schema-tb-nfe",
        }

        intent = ResponseIntent(topic="Fiscal", user_goal="answer_question")
        contract = build_response_contract(intent)
        options = ConversationOptions(vr_mode="ultra")

        # -------------------------------------------------------------
        # PHASE 1: Run the Ultra source fan-out and persist each step
        # -------------------------------------------------------------
        res_fanout_1 = runner.execute_ultra_source_fanout(
            context=context_1,
            conversation={"provider": "codex", "model": "gpt-5"},
            native_id="native-1",
            provider=MagicMock(),
            options=options,
            skills=[],
            intent=intent,
            contract=contract,
            request="apuracao icms",
        )

        assert set(ephemeral_invocations) == {
            "vr_fanout_ultra_wiki",
            "vr_fanout_ultra_kb",
            "vr_fanout_ultra_schema",
        }
        assert len(res_fanout_1.reports) == 3
        assert budget.remaining_calls() < 10

        # Check that steps are stored in SQLite
        steps_run_1 = research_repo.get_steps_for_run("run-step-1")
        assert len(steps_run_1) == 3
        assert {step["status"] for step in steps_run_1} == {"completed"}
        assert {step["worker_id"] for step in steps_run_1} == {
            "ultra_wiki",
            "ultra_kb",
            "ultra_schema",
        }

        # Check synthesis output
        assert res_fanout_1.draft is not None
        assert res_fanout_1.draft.answer_status == "answered"
        assert "TB_NFE_CABECALHO" in res_fanout_1.draft.answer_markdown
        assert "wiki-icms" in res_fanout_1.draft.used_evidence_ids

    def test_cooperative_cancellation_stops_execution_cleanly(self, environment) -> None:
        settings, db, sem_index, rel_repo, research_repo = environment

        cancellation = CancellationToken()
        cancellation.cancel()  # Signal cancellation prior to or during run

        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=MagicMock(),
            event_emitter=lambda *args: None,
            ephemeral_turn_runner=lambda *args, **kwargs: "{}",
            buffered_turn_runner=lambda *args, **kwargs: ("{}", {}, {}),
            looks_like_final_envelope=lambda t: False,
            repository=research_repo,
        )

        budget = ExecutionBudget(max_calls=5, max_active_seconds=10.0)
        context = ExecutionContext(
            conversation_id="conv-cancel-test",
            run_id="run-cancel-1",
            workspace=settings.root,
            budget=budget,
            cancellation=cancellation,
        )
        intent = ResponseIntent(topic="Fiscal", user_goal="answer_question")

        # Must raise ExecutionCancelledError and stop immediately without orphan threads
        with pytest.raises(ExecutionCancelledError):
            runner.execute_ultra_source_fanout(
                context=context,
                conversation={"provider": "codex", "model": "gpt-5"},
                native_id="native-cancel",
                provider=MagicMock(),
                options=ConversationOptions(vr_mode="ultra"),
                skills=[],
                intent=intent,
                contract=build_response_contract(intent),
                request="cancel query",
            )

"""
Testes de persistência e retomada de investigações do Ultra (Lote L3).

Valida os requisitos especificados em PLANO_V2_ULTRA_BUSCA_ARQUITETURA.md:
1. Migração/criação das tabelas sem perda de dados existentes (idempotência).
2. Persistência transacional de run, steps e attempts.
3. Retomada segura com reaproveitamento de etapa concluída (reused) sem chamada ao modelo.
4. Rejeição de retomada quando contrato, prompt ou modelo sofrem mutação (hash divergente).
5. Registro de tentativas falhas com erro estruturado.
6. Consulta de histórico recuperando o rastro estruturado.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.execution import (
    ExecutionContext,
    ExecutionRunner,
    ResearchRepository,
    compute_step_input_hash,
)
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    QueryProfile,
)
from vrsoft_extractor.mary.supervision import (
    ResponseIntent,
    build_response_contract,
)


class TestResearchRepositorySchemaAndCrud:
    def test_schema_creation_is_idempotent_and_preserves_existing_data(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_research.db"
        repo1 = ResearchRepository(db_path)

        # Insert a run
        repo1.create_run(
            run_id="run-101",
            conversation_id="conv-1",
            plan_dict={"stages": [{"id": "s1"}]},
            request_text="Explique apuração de ICMS",
            budget_dict={"max_calls": 5},
        )

        # Re-running ensure_schema must be idempotent and preserve existing run
        repo2 = ResearchRepository(db_path)
        run = repo2.get_run("run-101")
        assert run is not None
        assert run["conversation_id"] == "conv-1"
        assert run["status"] == "running"
        assert run["request_text"] == "Explique apuração de ICMS"

    def test_record_step_attempts_and_step_results(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_research.db"
        repo = ResearchRepository(db_path)

        repo.create_run(
            run_id="run-202",
            conversation_id="conv-2",
            plan_dict={},
            request_text="Dúvida fiscal",
            budget_dict={},
        )

        input_hash = compute_step_input_hash("Fiscal", "prompt fiscal", {"model": "gpt-5"})

        # Record failed attempt 1
        repo.record_step_attempt(
            "run-202:fanout_fiscal",
            attempt_number=1,
            status="failed",
            error="API rate limit exceeded",
            duration_seconds=1.2,
        )

        # Record successful attempt 2
        repo.record_step_attempt(
            "run-202:fanout_fiscal",
            attempt_number=2,
            status="completed",
            output={"raw": "{\"findings\": []}"},
            duration_seconds=2.4,
        )

        # Save step result
        repo.save_step_result(
            run_id="run-202",
            stage_id="fanout_fiscal",
            worker_id="fanout_fiscal",
            role="module_research",
            module="Fiscal",
            input_hash=input_hash,
            status="completed",
            output={"raw": "{\"findings\": []}"},
            attempts=2,
            duration_seconds=3.6,
        )

        steps = repo.get_steps_for_run("run-202")
        assert len(steps) == 1
        step = steps[0]
        assert step["status"] == "completed"
        assert step["attempts_count"] == 2
        assert step["input_hash"] == input_hash

        attempts = repo.get_attempts_for_step("run-202:fanout_fiscal")
        assert len(attempts) == 2
        assert attempts[0]["status"] == "failed"
        assert "rate limit" in attempts[0]["error"]
        assert attempts[1]["status"] == "completed"


class TestSafeResumption:
    def test_safe_resumption_reuses_completed_stage_without_calling_model(self, tmp_path: Path) -> None:
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        db_path = settings.database_path
        repo = ResearchRepository(db_path)

        # Set up runner with mock turn runners
        ephemeral_calls: list[str] = []

        def fake_ephemeral(cid, run_id, agent_id, *args, **kwargs):
            ephemeral_calls.append(agent_id)
            return json.dumps({
                "source_status": "found",
                "findings": [{"claim": f"Achado novo de {agent_id}", "evidence_ids": [], "kind": "fact", "confidence": 0.9}],
                "conflicts": [],
                "missing_information": [],
                "warnings": [],
                "sources": [],
            })

        def fake_buffered(*args, **kwargs):
            return '{"answer_status":"grounded","answer_markdown":"Síntese completa.","cited_evidence_ids":[],"warnings":[],"missing_information":[],"follow_up_suggestions":[]}', {}, {}

        events_emitted: list[tuple[str, str, dict]] = []

        def fake_emitter(cid, kind, text, payload):
            events_emitted.append((kind, text, payload))

        mock_retrieval = MagicMock()
        mock_retrieval.prompt_for_role.return_value = "contexto fixo"

        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=mock_retrieval,
            event_emitter=fake_emitter,
            ephemeral_turn_runner=fake_ephemeral,
            buffered_turn_runner=fake_buffered,
            looks_like_final_envelope=lambda x: False,
            repository=repo,
        )

        bundle = EvidenceBundle(
            profile=QueryProfile(query="apuracao", intents={}, module="Fiscal"),
            candidates=(),
        )
        intent = ResponseIntent(topic="Fiscal", user_goal="answer_question")
        contract = build_response_contract(intent)
        options = ConversationOptions(vr_mode="ultra")

        # RUN 1: Run with Fiscal only -> executes model turn and saves step
        ctx1 = ExecutionContext(
            conversation_id="conv-1",
            run_id="run-1",
            workspace=tmp_path,
        )
        runner.execute_fanout(
            context=ctx1,
            conversation={"provider": "codex", "model": "gpt-5"},
            native_id="native-1",
            provider=MagicMock(),
            options=options,
            skills=[],
            bundle=bundle,
            intent=intent,
            contract=contract,
            modules=("Fiscal",),
            request="apuracao icms",
        )
        assert "vr_fanout_fiscal" in ephemeral_calls
        ephemeral_calls.clear()

        # Explicitly resume the same conversation; unrelated runs cannot share private results.
        ctx2 = ExecutionContext(
            conversation_id="conv-1",
            run_id="run-1",
            workspace=tmp_path,
            metadata={"resume_run_id": "run-1"},
        )
        runner.execute_fanout(
            context=ctx2,
            conversation={"provider": "codex", "model": "gpt-5"},
            native_id="native-2",
            provider=MagicMock(),
            options=options,
            skills=[],
            bundle=bundle,
            intent=intent,
            contract=contract,
            modules=("Fiscal", "Contabil"),
            request="apuracao icms",
        )

        # Fiscal was NOT called again on the model because it was reused!
        assert "vr_fanout_fiscal" not in ephemeral_calls
        # Contabil WAS called because it is new!
        assert "vr_fanout_contabil" in ephemeral_calls

        # Check that event and repository recorded 'reused'
        reused_events = [e for e in events_emitted if e[2].get("reused") is True]
        assert len(reused_events) >= 1
        assert "reaproveitado do cache" in reused_events[0][1]

        steps_run2 = repo.get_steps_for_run("run-1")
        fiscal_step = next(s for s in steps_run2 if s["module"] == "Fiscal")
        assert fiscal_step["status"] == "reused"

    def test_divergence_rejects_resumption_and_reexecutes(self, tmp_path: Path) -> None:
        """Changing the model or prompt changes the input hash, requiring re-execution."""
        repo = ResearchRepository(tmp_path / "test_divergence.db")

        # Step saved with gpt-5
        hash_v1 = compute_step_input_hash("Fiscal", "prompt A", {"model": "gpt-5"})
        repo.create_run("run-old", "conv-1", {}, "prompt A", {})
        repo.save_step_result(
            "run-old", "fanout_fiscal", "fanout_fiscal", "module_research", "Fiscal",
            hash_v1, "completed", output={"raw": "{}"},
        )

        # Lookup with same hash succeeds
        assert repo.find_reusable_step(hash_v1, run_id="run-old") is not None

        # Lookup with modified model (e.g. gpt-5-mini) produces different hash -> rejects reuse
        hash_v2 = compute_step_input_hash("Fiscal", "prompt A", {"model": "gpt-5-mini"})
        assert repo.find_reusable_step(hash_v2, run_id="run-old") is None

        # Lookup with modified contract version produces different hash -> rejects reuse
        hash_v3 = compute_step_input_hash("Fiscal", "prompt A", {"model": "gpt-5"}, contract_version="3.0.0")
        assert repo.find_reusable_step(hash_v3, run_id="run-old") is None

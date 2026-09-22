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

import pytest

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
    def test_contract_20_run_cannot_be_resumed_under_contract_21(
        self, tmp_path: Path
    ) -> None:
        repo = ResearchRepository(tmp_path / "old-contract.db")
        repo.create_run(
            "run-contract-20",
            "conv-contract",
            {},
            "pergunta",
            {},
            contract_version="2.0.0",
        )
        repo.update_run_status("run-contract-20", "failed")

        with pytest.raises(ValueError, match="incompatível"):
            repo.claim_resume("run-contract-20", "conv-contract")

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


class TestUltraStageIdentityPersistence:
    def test_ultra_dev_java_step_keeps_ultra_identity(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        repo = ResearchRepository(settings.database_path)
        monkeypatch.setattr(
            "vrsoft_extractor.mary.execution.runner.retrieve_code_candidates",
            lambda *args, **kwargs: ([], [], []),
        )

        retrieval = MagicMock()
        profile = QueryProfile(query="pergunta", intents={})
        retrieval.classify.return_value = profile
        retrieval.prompt_for_role.return_value = "contexto"
        retrieval.route_source.side_effect = (
            lambda query, source: EvidenceBundle(profile=profile)
        )

        def fake_buffered(*args, **kwargs):
            return (
                json.dumps(
                    {
                        "answer_markdown": "Sem evidência suficiente.",
                        "used_evidence_ids": [],
                        "answer_status": "insufficient_evidence",
                    }
                ),
                {},
                {},
            )

        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=retrieval,
            event_emitter=lambda *args: None,
            ephemeral_turn_runner=lambda *args, **kwargs: json.dumps(
                {"source_status": "found", "findings": []}
            ),
            buffered_turn_runner=fake_buffered,
            looks_like_final_envelope=lambda _text: False,
            repository=repo,
        )
        intent = ResponseIntent(topic="", user_goal="answer_question")
        result = runner.execute_ultra_source_fanout(
            context=ExecutionContext(
                conversation_id="conv-ultra",
                run_id="run-ultra-1",
                workspace=tmp_path,
            ),
            conversation={"provider": "codex", "model": "gpt-5"},
            native_id="native-ultra",
            provider=MagicMock(),
            options=ConversationOptions(effort="medium", vr_mode="ultra"),
            skills=[],
            intent=intent,
            contract=build_response_contract(intent),
            code_analysis_enabled=True,
            request="pergunta",
        )

        assert result.draft is not None
        steps = repo.get_steps_for_run("run-ultra-1")
        code_step = next(step for step in steps if step["stage_id"] == "ultra_code")
        assert code_step["worker_id"] == "ultra_code"
        assert code_step["role"] == "code_research"
        assert code_step["module"] == "code"

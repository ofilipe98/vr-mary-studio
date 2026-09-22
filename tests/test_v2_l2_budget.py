"""
Testes de orçamento global e cancelamento do Ultra (Lote L2).

Valida os requisitos especificados em PLANO_V2_ULTRA_BUSCA_ARQUITETURA.md:
1. Reserva atômica de chamadas entre workers concorrentes.
2. Cálculo dinâmico de timeout baseado no prazo restante.
3. Reserva estrita de capacidade para síntese e validação.
4. Contabilização de tokens (real, estimado, desconhecido).
5. Cancelamento cooperativo imediato durante esperas e retry backoff.
6. Preservação de achados parciais em caso de esgotamento de orçamento ou falha isolada de worker.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.execution import (
    CallReservationError,
    CancellationToken,
    ExecutionBudget,
    ExecutionContext,
    ExecutionCancelledError,
    ExecutionRunner,
)
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    QueryProfile,
    SourceSearchReport,
)
from vrsoft_extractor.mary.research_fanout import (
    ULTRA_MAX_PARALLEL_RESEARCHERS,
)
from vrsoft_extractor.mary.supervision import (
    ResponseIntent,
    build_response_contract,
)


# ---------------------------------------------------------------------------
# 1. Atomic Reservation & Competing Workers
# ---------------------------------------------------------------------------

class TestBudgetAtomicReservation:
    def test_competing_workers_disputing_last_call(self) -> None:
        """Multiple concurrent workers competing for the last available slot."""
        # max_calls = 5, reserved_synthesis_calls = 2 -> only 3 researcher calls allowed
        budget = ExecutionBudget(
            max_active_seconds=60.0,
            max_calls=5,
            reserved_synthesis_calls=2,
        )

        successful_reservations = 0
        lock = threading.Lock()

        def try_reserve():
            nonlocal successful_reservations
            try:
                budget.acquire_call(is_synthesis=False)
                with lock:
                    successful_reservations += 1
            except CallReservationError:
                pass

        # 10 workers concurrently compete
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(try_reserve) for _ in range(10)]
            for f in futures:
                f.result()

        assert successful_reservations == 3
        assert budget.remaining_calls() == 2
        for _ in range(successful_reservations):
            budget.release_call()
        # Now synthesis can acquire the remaining 2 calls
        t1 = budget.acquire_call(is_synthesis=True)
        t2 = budget.acquire_call(is_synthesis=True)
        assert t1 > 0
        assert t2 > 0
        assert budget.remaining_calls() == 0

        # Further synthesis call raises error
        with pytest.raises(CallReservationError):
            budget.acquire_call(is_synthesis=True)


# ---------------------------------------------------------------------------
# 2. Dynamic Timeout and Controlled Clock
# ---------------------------------------------------------------------------

class TestBudgetDynamicTimeout:
    def test_timeout_is_min_of_requested_and_remaining(self) -> None:
        simulated_time = 1000.0

        def clock():
            return simulated_time

        budget = ExecutionBudget(
            max_active_seconds=30.0,
            max_calls=10,
            clock=clock,
        )

        # Initially 30s remaining
        assert budget.time_remaining() == 30.0
        # Requested 150s, but only 30s left -> returns 30s
        t = budget.acquire_call(is_synthesis=False, requested_timeout=150.0)
        assert t == 30.0
        budget.release_call()

        # Advance simulated time by 25s -> only 5s left
        simulated_time += 25.0
        assert budget.time_remaining() == 5.0
        t2 = budget.acquire_call(is_synthesis=False, requested_timeout=10.0)
        assert t2 == 5.0
        budget.release_call()

        # Advance simulated time past deadline
        simulated_time += 10.0
        assert budget.is_time_exhausted()
        with pytest.raises(CallReservationError, match="Tempo máximo de execução esgotado"):
            budget.acquire_call(is_synthesis=True)


# ---------------------------------------------------------------------------
# 3. Token Accounting
# ---------------------------------------------------------------------------

class TestTokenAccounting:
    def test_tokens_distinguish_real_estimated_unknown(self) -> None:
        budget = ExecutionBudget(max_calls=10)
        budget.record_tokens(150, kind="real")
        budget.record_tokens(300, kind="estimated")
        budget.record_tokens(50, kind="unknown")

        tokens = budget.tokens
        assert tokens.real == 150
        assert tokens.estimated == 300
        assert tokens.unknown == 50
        assert tokens.total_known == 450

        d = budget.to_dict()
        assert d["tokens"]["real"] == 150
        assert d["tokens"]["estimated"] == 300
        assert d["tokens"]["unknown"] == 50
        assert d["tokens"]["total_known"] == 450


# ---------------------------------------------------------------------------
# 4. Cooperative Cancellation
# ---------------------------------------------------------------------------

class TestCooperativeCancellation:
    def test_cancellation_wakes_wait_immediately(self) -> None:
        token = CancellationToken()
        assert not token.is_cancelled

        callback_called = False

        def on_cancel():
            nonlocal callback_called
            callback_called = True

        token.register_callback(on_cancel)

        # Start a thread that waits for 10 seconds
        wait_result = []

        def wait_worker():
            cancelled = token.wait(10.0)
            wait_result.append(cancelled)

        t = threading.Thread(target=wait_worker)
        t.start()

        # Cancel after 50ms
        time.sleep(0.05)
        token.cancel(reason="user_stop")
        t.join(timeout=1.0)

        assert not t.is_alive()
        assert wait_result == [True]
        assert callback_called is True
        assert token.is_cancelled
        assert token.reason == "user_stop"

        with pytest.raises(ExecutionCancelledError, match="user_stop"):
            token.check_cancelled()


# ---------------------------------------------------------------------------
# 5. ExecutionRunner Integration with Budget and Cancellation
# ---------------------------------------------------------------------------

class TestUltraSourceFanoutBudget:
    def _runner(
        self,
        tmp_path: Path,
        *,
        ephemeral,
        buffered,
    ) -> tuple[ExecutionRunner, list[tuple[str, str, dict]]]:
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        profile = QueryProfile(query="pergunta", intents={})
        retrieval = MagicMock()
        retrieval.classify.return_value = profile
        retrieval.prompt_for_role.return_value = "contexto"

        def bundle_for(source: str) -> EvidenceBundle:
            candidate = EvidenceCandidate(
                evidence_id=f"{source}:doc-1:1",
                source=source,
                source_id="doc-1",
                document_id=1,
                chunk_id=1,
                title=f"Doc {source}",
                heading="H",
                content_type="section",
                module="Fiscal",
                product="",
                excerpt="conteudo",
                url="",
            )
            return EvidenceBundle(
                profile=profile,
                candidates=(candidate,),
                source_reports=(
                    SourceSearchReport(
                        source=source,
                        status="found",
                        selected_evidence_ids=(candidate.evidence_id,),
                    ),
                ),
            )

        retrieval.route_source.side_effect = (
            lambda query, source: bundle_for(source)
        )
        events: list[tuple[str, str, dict]] = []
        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=retrieval,
            event_emitter=(
                lambda cid, kind, text, payload: events.append(
                    (kind, text, payload)
                )
            ),
            ephemeral_turn_runner=ephemeral,
            buffered_turn_runner=buffered,
            looks_like_final_envelope=lambda _text: False,
        )
        return runner, events

    @staticmethod
    def _buffered(*args, **kwargs):
        return (
            json.dumps(
                {
                    "answer_markdown": "Resultado final do Ultra.",
                    "used_evidence_ids": [],
                    "answer_status": "insufficient_evidence",
                }
            ),
            {},
            {},
        )

    @staticmethod
    def _report(*args, **kwargs) -> str:
        return json.dumps({"source_status": "found", "findings": []})

    def _execute(
        self,
        runner: ExecutionRunner,
        tmp_path: Path,
        *,
        run_id: str,
        budget: ExecutionBudget,
        code_analysis_enabled: bool = False,
    ):
        intent = ResponseIntent(topic="", user_goal="answer_question")
        context = ExecutionContext(
            conversation_id=f"conv-{run_id}",
            run_id=run_id,
            workspace=tmp_path,
            budget=budget,
        )
        return runner.execute_ultra_source_fanout(
            context=context,
            conversation={"provider": "codex", "model": "gpt-5"},
            native_id=f"native-{run_id}",
            provider=MagicMock(),
            options=ConversationOptions(vr_mode="ultra"),
            skills=[],
            intent=intent,
            contract=build_response_contract(intent),
            code_analysis_enabled=code_analysis_enabled,
            request="pergunta",
        )

    def test_ultra_executor_limits_parallelism_to_budget(self, tmp_path: Path) -> None:
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_ephemeral(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            with lock:
                active -= 1
            return self._report()

        runner, _events = self._runner(
            tmp_path, ephemeral=fake_ephemeral, buffered=self._buffered
        )
        budget = ExecutionBudget(
            max_active_seconds=60.0,
            max_calls=15,
            max_parallel=2,
            reserved_synthesis_calls=2,
        )

        result = self._execute(
            runner, tmp_path, run_id="run-ultra-parallel", budget=budget
        )

        assert result.draft is not None
        assert peak == 2, "o executor deve limitar a concorrência ao orçamento"
        assert budget.calls_in_flight == 0

    def test_ultra_executor_runs_four_workers_when_budget_permits(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        barrier = threading.Barrier(4, timeout=5)
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_ephemeral(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait()
            finally:
                with lock:
                    active -= 1
            return self._report()

        def fake_code(root, query, **kwargs):
            candidate = EvidenceCandidate(
                evidence_id="code:doc-1:1",
                source="code",
                source_id="doc-1",
                document_id=1,
                chunk_id=1,
                title="Trecho Java",
                heading="H",
                content_type="section",
                module="",
                product="",
                excerpt="codigo",
                url="",
            )
            return ([candidate], [], [])

        monkeypatch.setattr(
            "vrsoft_extractor.mary.execution.runner.retrieve_code_candidates",
            fake_code,
        )
        runner, _events = self._runner(
            tmp_path, ephemeral=fake_ephemeral, buffered=self._buffered
        )
        runner.research_max_parallel = ULTRA_MAX_PARALLEL_RESEARCHERS
        budget = ExecutionBudget(
            max_active_seconds=60.0,
            max_calls=15,
            max_parallel=ULTRA_MAX_PARALLEL_RESEARCHERS,
            reserved_synthesis_calls=2,
        )

        result = self._execute(
            runner,
            tmp_path,
            run_id="run-ultra-four-workers",
            budget=budget,
            code_analysis_enabled=True,
        )

        assert result.draft is not None
        assert not barrier.broken, "as quatro frentes precisam coexistir"
        assert peak == ULTRA_MAX_PARALLEL_RESEARCHERS
        assert budget.calls_in_flight == 0

    def test_ultra_executor_preserves_synthesis_reservation(
        self, tmp_path: Path
    ) -> None:
        runner, events = self._runner(
            tmp_path, ephemeral=self._report, buffered=self._buffered
        )
        # 3 calls total, 2 reserved for synthesis -> exactly one researcher runs.
        budget = ExecutionBudget(
            max_active_seconds=60.0,
            max_calls=3,
            max_parallel=4,
            reserved_synthesis_calls=2,
        )

        result = self._execute(
            runner, tmp_path, run_id="run-ultra-reserved", budget=budget
        )

        assert result.draft is not None
        assert budget.remaining_calls() == 1
        failures = [
            payload for kind, _text, payload in events if kind == "agent_failed"
        ]
        assert len(failures) == 2
        assert all(
            "reservada" in str(payload.get("error")) for payload in failures
        )

    def test_ultra_executor_cancellation_prevents_synthesis(
        self, tmp_path: Path
    ) -> None:
        buffered_calls: list[str] = []

        def fake_buffered(*args, **kwargs):
            buffered_calls.append("synthesis")
            return self._buffered()

        runner, _events = self._runner(
            tmp_path, ephemeral=self._report, buffered=fake_buffered
        )
        intent = ResponseIntent(topic="", user_goal="answer_question")
        context = ExecutionContext(
            conversation_id="conv-ultra-cancel",
            run_id="run-ultra-cancel",
            workspace=tmp_path,
            budget=ExecutionBudget(max_active_seconds=60.0, max_calls=15),
        )
        context.cancellation.cancel("user_stop")

        with pytest.raises(ExecutionCancelledError, match="user_stop"):
            runner.execute_ultra_source_fanout(
                context=context,
                conversation={"provider": "codex", "model": "gpt-5"},
                native_id="native-cancel",
                provider=MagicMock(),
                options=ConversationOptions(vr_mode="ultra"),
                skills=[],
                intent=intent,
                contract=build_response_contract(intent),
                request="pergunta",
            )
        assert buffered_calls == []

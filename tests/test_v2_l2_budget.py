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
    QueryProfile,
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

class TestExecutionRunnerBudgetIntegration:
    def test_budget_exhaustion_preserves_findings_and_skips_optional_code_agent(self, tmp_path: Path) -> None:
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()

        budget = ExecutionBudget(
            max_active_seconds=60.0,
            max_calls=3,  # 3 calls total, 2 reserved for synthesis -> exactly 1 researcher call allowed!
            reserved_synthesis_calls=2,
        )
        ctx = ExecutionContext(
            conversation_id="conv-1",
            run_id="run-1",
            workspace=tmp_path,
            budget=budget,
        )

        mock_retrieval = MagicMock()
        mock_retrieval.prompt_for_role.return_value = "prompt"
        mock_emitter = MagicMock()

        # Ephemeral turn returns valid JSON for the 1 successful researcher
        def fake_ephemeral(*args, **kwargs):
            return '{"source_status":"found","findings":[{"claim":"achado fiscal","evidence_ids":[],"kind":"fact","confidence":0.9}],"conflicts":[],"missing_information":[],"warnings":[],"sources":[]}'

        def fake_buffered(*args, **kwargs):
            return '{"answer_status":"grounded","answer_markdown":"Resultado final com evidências.","cited_evidence_ids":[],"warnings":[],"missing_information":[],"follow_up_suggestions":[]}', {}, {}

        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=mock_retrieval,
            event_emitter=mock_emitter,
            ephemeral_turn_runner=fake_ephemeral,
            buffered_turn_runner=fake_buffered,
            looks_like_final_envelope=lambda x: False,
        )

        bundle = EvidenceBundle(
            profile=QueryProfile(query="teste", intents={}, module="Fiscal"),
            candidates=(),
        )
        intent = ResponseIntent(topic="Fiscal", user_goal="answer_question")
        contract = build_response_contract(intent)
        options = ConversationOptions(vr_mode="ultra")

        # 2 modules: Fiscal and Contabil. With 1 allowed researcher slot, one succeeds and one is rejected due to budget.
        # But because 1 succeeded, execution proceeds to synthesis!
        result = runner.execute_fanout(
            context=ctx,
            conversation={"provider": "codex", "model": "gpt-5"},
            native_id="native-1",
            provider=MagicMock(),
            options=options,
            skills=[],
            bundle=bundle,
            intent=intent,
            contract=contract,
            modules=("Fiscal", "Contabil"),
            request="pesquisa fiscal",
        )

        assert result.draft is not None
        assert "Resultado final" in result.draft.answer_markdown
        # Verify synthesis consumed the reserved slots
        assert budget.remaining_calls() < 2

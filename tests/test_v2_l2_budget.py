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
from vrsoft_extractor.mary.research_fanout import ULTRA_MAX_PARALLEL_RESEARCHERS
from vrsoft_extractor.mary.supervision import ResponseIntent, build_response_contract


class TestExecutionTelemetry:
    def test_more_than_one_hundred_acquisitions_never_exhaust(self) -> None:
        now = [100.0]
        budget = ExecutionBudget(max_parallel=2, clock=lambda: now[0])
        for _ in range(125):
            assert budget.acquire_call(requested_timeout=1.0) is None
        assert budget.calls_made == 125
        assert budget.calls_in_flight == 125
        assert budget.remaining_calls() is None
        assert budget.time_remaining() is None
        assert budget.has_synthesis_capacity() is True
        assert budget.is_time_exhausted() is False
        for _ in range(125):
            budget.release_call(tokens_used=3, token_kind="estimated")
        assert budget.calls_in_flight == 0
        assert budget.tokens.estimated == 375
        assert budget.tokens.total_known == 375

    def test_concurrent_acquisitions_are_telemetry_only(self) -> None:
        budget = ExecutionBudget(max_parallel=1)
        acquired: list[int] = []
        lock = threading.Lock()

        def worker() -> None:
            budget.acquire_call()
            with lock:
                acquired.append(budget.calls_made)
            budget.release_call()

        with ThreadPoolExecutor(max_workers=20) as executor:
            list(executor.map(lambda _: worker(), range(120)))
        assert len(acquired) == 120
        assert budget.calls_made == 120
        assert budget.calls_in_flight == 0

    def test_large_elapsed_clock_does_not_stop_new_calls(self) -> None:
        now = [0.0]
        budget = ExecutionBudget(clock=lambda: now[0])
        now[0] = 10_000.0
        budget.acquire_call()
        budget.release_call()
        assert budget.elapsed_seconds() == 10_000.0
        assert budget.acquire_call() is None
        assert budget.calls_made == 2

    def test_token_categories_and_snapshot_are_preserved(self) -> None:
        now = [10.0]
        budget = ExecutionBudget(max_parallel=3, clock=lambda: now[0])
        budget.record_tokens(7, kind="real")
        budget.record_tokens(11, kind="estimated")
        budget.record_tokens(13, kind="unknown")
        budget.acquire_call()
        snapshot = budget.to_dict()
        assert snapshot["unlimited"] is True
        assert set(snapshot) == {
            "unlimited",
            "max_parallel",
            "calls_made",
            "calls_in_flight",
            "elapsed_seconds",
            "tokens",
        }
        restored = ExecutionBudget.from_snapshot(snapshot, clock=lambda: now[0])
        assert restored.max_parallel == 3
        assert restored.calls_in_flight == 0
        assert restored.tokens.to_dict() == budget.tokens.to_dict()
        assert restored.remaining_calls() is None
        assert restored.time_remaining() is None

        legacy = {
            "max_active_seconds": 1,
            "max_calls": 1,
            "max_retries_per_worker": 0,
            "token_limit": 1,
            "calls_made": 40,
            "elapsed_seconds": 500,
            "tokens": {"real": 2, "estimated": 0, "unknown": 0},
        }
        resumed = ExecutionBudget.from_snapshot(legacy, clock=lambda: now[0])
        assert resumed.calls_made == 40
        assert resumed.acquire_call() is None
        assert resumed.tokens.real == 2


class TestCooperativeCancellation:
    def test_cancellation_wakes_wait_immediately(self) -> None:
        token = CancellationToken()
        called = threading.Event()

        def on_cancel() -> None:
            called.set()

        token.register_callback(on_cancel)
        result: list[bool] = []

        def worker() -> None:
            result.append(token.wait(10.0))

        thread = threading.Thread(target=worker)
        thread.start()
        token.cancel(reason="user_stop")
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert result == [True]
        assert called.is_set()
        with pytest.raises(ExecutionCancelledError, match="user_stop"):
            token.check_cancelled()


class TestUltraSourceFanoutTelemetry:
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

        retrieval.route_source.side_effect = lambda query, source: bundle_for(source)
        events: list[tuple[str, str, dict]] = []
        runner = ExecutionRunner(
            settings=settings,
            providers={},
            retrieval=retrieval,
            event_emitter=lambda cid, kind, text, payload: events.append(
                (kind, text, payload)
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

    def test_scheduler_caps_workers_without_budget_failure(self, tmp_path: Path) -> None:
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
        budget = ExecutionBudget(max_parallel=2)
        result = self._execute(
            runner, tmp_path, run_id="run-ultra-parallel", budget=budget
        )
        assert result.draft is not None
        assert peak == 2
        assert budget.calls_made >= 4
        assert budget.calls_in_flight == 0

    def test_four_workers_can_share_the_scheduler(self, tmp_path: Path, monkeypatch) -> None:
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
        budget = ExecutionBudget(max_parallel=ULTRA_MAX_PARALLEL_RESEARCHERS)
        result = self._execute(
            runner,
            tmp_path,
            run_id="run-ultra-four-workers",
            budget=budget,
            code_analysis_enabled=True,
        )
        assert result.draft is not None
        assert not barrier.broken
        assert peak == ULTRA_MAX_PARALLEL_RESEARCHERS
        assert budget.calls_in_flight == 0

    def test_cancellation_prevents_synthesis(self, tmp_path: Path) -> None:
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
            budget=ExecutionBudget(),
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

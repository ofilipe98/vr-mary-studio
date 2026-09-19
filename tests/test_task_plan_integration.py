import json

import pytest
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.models import RuntimeEvent

pytestmark = pytest.mark.qml


def test_plan_survives_followup_and_conversation_switch_without_false_completion(
    tmp_path,
):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(
        app_dir=tmp_path, root=tmp_path / "data", old_root=tmp_path / "old"
    )
    db = MaryDatabase(
        settings.database_path, root=settings.root, backup_portable_migration=False
    )
    cid = db.create_conversation("Tasks", "codex", "test", settings.root)
    bridge = ChatBridge(
        settings, db, QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )
    try:
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        def emit(kind, text="", payload=None, at="2026-09-13T12:00:00Z"):
            orch._handle_event(RuntimeEvent(cid, kind, text, payload or {}, at))

        emit("turn_started")
        emit(
            "runtime_event",
            "turn/plan/updated",
            {
                "plan": [
                    {"step": "Read", "status": "inProgress"},
                    {"step": "Check", "status": "pending"},
                ]
            },
        )
        assert [x["state"] for x in bridge.taskSteps] == ["running", "pending"]
        assert bridge.taskPlanVisible
        emit(
            "runtime_event",
            "turn/plan/updated",
            {
                "plan": [
                    {"step": "Read", "status": "completed"},
                    {"step": "Check", "status": "pending"},
                ]
            },
            "2026-09-13T12:00:05Z",
        )
        bridge._queue_terminal_state("turn_completed")
        assert bridge.taskSteps[1]["state"] == "pending"
        assert not bridge.taskPlanVisible
        emit("turn_started")
        assert not bridge.taskPlanVisible
        emit("assistant_delta", "Follow-up without a new plan")
        bridge._queue_terminal_state("orchestration_cancelled")
        expected = bridge.taskSteps
        assert expected[0]["durationMs"] == 5000
        assert expected[1]["state"] == "pending"
        assert len(db.task_plan_events(cid)) == 2
        assert (
            json.loads(db.task_plan_events(cid)[-1]["payload_json"])["steps"][1][
                "state"
            ]
            == "pending"
        )
        bridge.startNewChat()
        assert bridge.taskSteps == []
        bridge._restore_activity_from_history(cid)
        assert bridge.taskSteps == expected
        other = db.create_conversation("Other", "codex", "test", settings.root)
        bridge._restore_activity_from_history(other)
        assert bridge.taskSteps == []
        emit("runtime_event", "turn/plan/updated", {"plan": []})
        bridge._restore_activity_from_history(cid)
        assert bridge.taskSteps == []
        emit(
            "task_tool_result",
            payload={
                "name": "TaskCreate",
                "input": {"subject": "Read"},
                "result": {"task": {"id": "1", "subject": "Read"}},
            },
        )
        emit(
            "task_tool_result",
            payload={
                "name": "TaskUpdate",
                "input": {"taskId": "1", "status": "completed"},
                "result": {"success": True},
            },
        )
        bridge._restore_activity_from_history(cid)
        assert bridge.taskSteps[0]["state"] == "completed"
        assert not bridge.taskPlanVisible
        before = len(db.task_plan_events(cid))
        orch._finalized_turns.add(cid)
        emit("runtime_event", "turn/plan/updated", {"plan": []})
        assert len(db.task_plan_events(cid)) == before
    finally:
        bridge.close()
        app.processEvents()


def _make_bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(
        app_dir=tmp_path, root=tmp_path / "data", old_root=tmp_path / "old"
    )
    db = MaryDatabase(
        settings.database_path, root=settings.root, backup_portable_migration=False
    )
    bridge = ChatBridge(
        settings, db, QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )
    return app, settings, db, bridge


def test_active_progress_lifecycle_and_followup_reactivation(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("Tasks", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        def emit(kind, text="", payload=None, at="2026-09-13T12:00:00Z"):
            orch._handle_event(RuntimeEvent(cid, kind, text, payload or {}, at))

        emit("turn_started")
        emit(
            "runtime_event",
            "turn/plan/updated",
            {
                "plan": [
                    {"step": "Read", "status": "inProgress"},
                    {"step": "Check", "status": "pending"},
                    {"step": "Ship", "status": "pending"},
                ]
            },
        )
        assert bridge.taskProgress == {
            "step": "Read",
            "completed": 0,
            "total": 3,
        }
        assert "Read" in bridge.statusText
        emit(
            "runtime_event",
            "turn/plan/updated",
            {
                "plan": [
                    {"step": "Read", "status": "completed"},
                    {"step": "Check", "status": "inProgress"},
                    {"step": "Ship", "status": "pending"},
                ]
            },
            "2026-09-13T12:00:04Z",
        )
        assert bridge.taskProgress == {
            "step": "Check",
            "completed": 1,
            "total": 3,
        }
        # Terminal clears active progress without falsifying completion.
        bridge._queue_terminal_state("turn_completed")
        assert bridge.taskProgress == {}
        assert bridge.taskSteps[1]["state"] == "running"
        assert bridge.taskSteps[2]["state"] == "pending"
        # Follow-up without a new plan preserves the snapshot, no progress.
        emit("turn_started")
        assert bridge.taskProgress == {}
        assert [s["state"] for s in bridge.taskSteps] == [
            "completed",
            "running",
            "pending",
        ] or [s["state"] for s in bridge.taskSteps] == [
            "completed",
            "pending",
            "pending",
        ]
        # A fresh plan in the follow-up reactivates progress.
        emit(
            "runtime_event",
            "turn/plan/updated",
            {
                "plan": [
                    {"step": "Read", "status": "completed"},
                    {"step": "Check", "status": "completed"},
                    {"step": "Ship", "status": "inProgress"},
                ]
            },
            "2026-09-13T12:00:09Z",
        )
        assert bridge.taskProgress == {
            "step": "Ship",
            "completed": 2,
            "total": 3,
        }
        bridge._queue_terminal_state("error")
        assert bridge.taskProgress == {}
        assert bridge.taskSteps[2]["state"] in {"pending", "running"}
    finally:
        bridge.close()
        app.processEvents()


def test_background_conversations_keep_independent_progress(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid_a = db.create_conversation("A", "codex", "test", bridge._settings.root)
        cid_b = db.create_conversation("B", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid_a)
        orch = bridge._orchestrator
        orch._external_callbacks[cid_a] = bridge._on_runtime_event
        orch._external_callbacks[cid_b] = bridge._on_runtime_event

        def emit(cid, kind, text="", payload=None, at="2026-09-13T12:00:00Z"):
            orch._handle_event(RuntimeEvent(cid, kind, text, payload or {}, at))

        emit(cid_a, "turn_started")
        emit(cid_b, "turn_started")
        db.update_conversation(cid_a, status="running")
        db.update_conversation(cid_b, status="running")
        emit(
            cid_a,
            "runtime_event",
            "turn/plan/updated",
            {"plan": [{"step": "Alpha", "status": "inProgress"}]},
        )
        # Selected is A: its drawer shows Alpha.
        assert bridge.taskProgress == {"step": "Alpha", "completed": 0, "total": 1}
        selected_steps = list(bridge.taskSteps)
        assert [s["text"] for s in selected_steps] == ["Alpha"]
        # Background update for B must not contaminate the selection.
        emit(
            cid_b,
            "runtime_event",
            "turn/plan/updated",
            {
                "plan": [
                    {"step": "Beta", "status": "completed"},
                    {"step": "Gamma", "status": "inProgress"},
                ]
            },
        )
        assert [s["text"] for s in bridge.taskSteps] == ["Alpha"]
        assert bridge.taskProgress == {"step": "Alpha", "completed": 0, "total": 1}
        # Sidebar rows carry independent progress.
        bridge.refresh()
        rows = {r["conversationId"]: r for r in bridge._all_conversations}
        assert rows[cid_a]["taskStep"] == "Alpha"
        assert (rows[cid_a]["taskCompleted"], rows[cid_a]["taskTotal"]) == (0, 1)
        assert rows[cid_b]["taskStep"] == "Gamma"
        assert (rows[cid_b]["taskCompleted"], rows[cid_b]["taskTotal"]) == (1, 2)
        # Terminal in A does not affect B.
        bridge.selectConversationId(cid_a)
        bridge._queue_terminal_state("turn_completed")
        db.update_conversation(cid_a, status="idle")
        bridge.refresh()
        assert bridge.taskProgress == {}
        rows = {r["conversationId"]: r for r in bridge._all_conversations}
        # A lost active progress, B keeps Gamma (still running).
        assert rows[cid_a]["taskStep"] == ""
        assert rows[cid_b]["taskStep"] == "Gamma"
        # Returning to B restores its snapshot immediately.
        bridge.selectConversationId(cid_b)
        assert [s["text"] for s in bridge.taskSteps] == ["Beta", "Gamma"]
        assert bridge.taskProgress == {"step": "Gamma", "completed": 1, "total": 2}
        # Explicit empty plan clears.
        emit(cid_b, "runtime_event", "turn/plan/updated", {"plan": []})
        assert bridge.taskSteps == []
        assert bridge.taskProgress == {}
    finally:
        bridge.close()
        app.processEvents()


def test_cancel_error_and_late_events_do_not_resurrect_plan(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("Tasks", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        def emit(kind, text="", payload=None, at="2026-09-13T12:00:00Z"):
            orch._handle_event(RuntimeEvent(cid, kind, text, payload or {}, at))

        emit("turn_started")
        emit(
            "runtime_event",
            "turn/plan/updated",
            {"plan": [{"step": "Work", "status": "inProgress"}]},
        )
        assert bridge.taskProgress != {}
        bridge._queue_terminal_state("orchestration_cancelled")
        assert bridge.taskProgress == {}
        assert bridge.taskSteps[0]["state"] == "running" or bridge.taskSteps[0]["state"] == "pending"
        # Late plan after finalization is ignored by the orchestrator guard.
        orch._finalized_turns.add(cid)
        before = len(db.task_plan_events(cid))
        emit("runtime_event", "turn/plan/updated", {"plan": [{"step": "Late", "status": "inProgress"}]})
        assert len(db.task_plan_events(cid)) == before
    finally:
        bridge.close()
        app.processEvents()


def test_streaming_backlog_clears_active_progress_immediately_while_draining(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("StreamTerminal", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        orch._handle_event(RuntimeEvent(cid, "turn_started"))
        orch._handle_event(RuntimeEvent(
            cid,
            "task_plan_updated",
            payload={"steps": [
                {"text": "Step 1", "state": "completed"},
                {"text": "Step 2", "state": "running"},
                {"text": "Step 3", "state": "pending"},
            ]},
        ))
        assert bridge.taskPlanVisible is True
        assert bridge.taskProgress == {"step": "Step 2", "completed": 1, "total": 3}

        # Simulate streaming backlog
        bridge._stream_pending_text = "More streaming text pending to be displayed"
        bridge._stream_terminal_kind = ""

        # Terminal arrives while streaming is still pending
        bridge._queue_terminal_state("turn_completed", conversation_id=cid)

        # Invariants: active progress & visibility vanish IMMEDIATELY
        assert bridge.taskProgress == {}
        assert bridge.taskPlanVisible is False
        assert bridge._status_text == "Finalizando resposta…"
        assert bridge._pending_terminal is not None
        assert bridge._pending_terminal["conversation_id"] == cid
        assert bridge._pending_terminal["kind"] == "turn_completed"

        # Sidebar conversation task info is also cleared immediately
        bridge.refresh()
        row = next(r for r in bridge._all_conversations if r["conversationId"] == cid)
        assert row["taskStep"] == ""

        # Persisted plan remains intact with original states (does NOT mark pending as completed)
        assert len(bridge.taskSteps) == 3
        assert bridge.taskSteps[1]["state"] == "running"
        assert bridge.taskSteps[2]["state"] == "pending"

        # Now simulate flushing the remaining stream
        bridge._stream_pending_text = ""
        bridge._flush_stream_step()

        # Terminal state fully finalized
        assert bridge._status_text == "Pronto"
        assert bridge._pending_terminal is None
        assert bridge.taskSteps[2]["state"] == "pending"
    finally:
        bridge.close()
        app.processEvents()


def test_switch_conversation_during_terminal_flush(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid_a = db.create_conversation("ConvA", "codex", "test", bridge._settings.root)
        cid_b = db.create_conversation("ConvB", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid_a)
        orch = bridge._orchestrator
        orch._external_callbacks[cid_a] = bridge._on_runtime_event
        orch._external_callbacks[cid_b] = bridge._on_runtime_event

        # Turn starts on Conv A with plan
        orch._handle_event(RuntimeEvent(cid_a, "turn_started"))
        orch._handle_event(RuntimeEvent(
            cid_a,
            "task_plan_updated",
            payload={"steps": [
                {"text": "A Step 1", "state": "running"},
                {"text": "A Step 2", "state": "pending"},
            ]},
        ))
        assert bridge.taskProgress == {"step": "A Step 1", "completed": 0, "total": 2}

        # Conv A enters pending terminal due to streaming text
        bridge._stream_pending_text = "Pending output for A"
        bridge._queue_terminal_state("turn_completed", conversation_id=cid_a)
        assert bridge.taskProgress == {}
        assert bridge._pending_terminal is not None
        assert bridge._pending_terminal["conversation_id"] == cid_a

        # User switches to Conv B while A is flushing
        bridge.selectConversationId(cid_b)

        # Invariants: Conv B does not inherit A's pending terminal or stream text
        assert bridge._selected_conversation_id() == cid_b
        assert bridge._pending_terminal is None
        assert bridge._stream_pending_text == ""
        assert bridge._status_text == "Pronto"
        assert bridge.taskProgress == {}

        # Switching back to Conv A shows it properly finalized and clean
        bridge.selectConversationId(cid_a)
        assert bridge._selected_conversation_id() == cid_a
        assert bridge._stream_pending_text == ""
        assert bridge.taskProgress == {}
        assert bridge._status_text == "Pronto"
        # Persisted plan for A survived
        assert len(bridge.taskSteps) == 2
        assert bridge.taskSteps[0]["text"] == "A Step 1"
    finally:
        bridge.close()
        app.processEvents()


def test_two_concurrent_terminals_interleaved(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid_a = db.create_conversation("ConvA", "codex", "test", bridge._settings.root)
        cid_b = db.create_conversation("ConvB", "codex", "test", bridge._settings.root)
        db.update_conversation(cid_a, status="running")
        db.update_conversation(cid_b, status="running")
        bridge.refresh()
        bridge.selectConversationId(cid_a)
        orch = bridge._orchestrator
        orch._external_callbacks[cid_a] = bridge._on_runtime_event
        orch._external_callbacks[cid_b] = bridge._on_background_runtime_event

        # Both turns active
        orch._handle_event(RuntimeEvent(cid_a, "turn_started"))
        orch._handle_event(RuntimeEvent(cid_b, "turn_started"))
        orch._handle_event(RuntimeEvent(
            cid_a, "task_plan_updated", payload={"steps": [{"text": "Plan A", "state": "running"}]}
        ))
        orch._handle_event(RuntimeEvent(
            cid_b, "task_plan_updated", payload={"steps": [{"text": "Plan B", "state": "running"}]}
        ))

        assert bridge.taskProgress == {"step": "Plan A", "completed": 0, "total": 1}
        bridge.refresh()
        rows = {r["conversationId"]: r for r in bridge._all_conversations}
        assert rows[cid_a]["taskStep"] == "Plan A"
        assert rows[cid_b]["taskStep"] == "Plan B"

        # Background terminal for B arrives
        db.update_conversation(cid_b, status="idle")
        bridge._on_background_runtime_event(RuntimeEvent(cid_b, "turn_completed"))
        assert cid_b not in bridge._active_turns
        bridge.refresh()
        rows = {r["conversationId"]: r for r in bridge._all_conversations}
        assert rows[cid_b]["taskStep"] == ""
        # Conv A remains active in foreground
        assert rows[cid_a]["taskStep"] == "Plan A"
        assert bridge.taskProgress == {"step": "Plan A", "completed": 0, "total": 1}

        # Terminal for A arrives
        db.update_conversation(cid_a, status="idle")
        bridge._on_runtime_event(RuntimeEvent(cid_a, "turn_completed"))
        assert cid_a not in bridge._active_turns
        assert bridge.taskProgress == {}

        # Check persisted plans of both remain intact
        assert bridge._task_plans[cid_a].steps[0]["text"] == "Plan A"
        assert bridge._task_plans[cid_b].steps[0]["text"] == "Plan B"
    finally:
        bridge.close()
        app.processEvents()


def test_malformed_snapshot_does_not_resurrect_persisted_plan(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("MalformedTest", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        # Previous turn had a plan
        orch._handle_event(RuntimeEvent(cid, "turn_started"))
        orch._handle_event(RuntimeEvent(
            cid, "task_plan_updated", payload={"steps": [{"text": "Old Plan", "state": "running"}]}
        ))
        assert bridge.taskPlanVisible is True
        bridge._on_runtime_event(RuntimeEvent(cid, "turn_completed"))
        assert bridge.taskPlanVisible is False
        assert bridge.taskProgress == {}

        # Follow-up turn starts without a plan
        orch._handle_event(RuntimeEvent(cid, "turn_started"))
        assert bridge._is_task_plan_current(cid) is False
        assert bridge.taskPlanVisible is False
        assert bridge.taskProgress == {}

        # Malformed snapshot arrives: must be strictly a no-op
        applied = bridge._apply_task_snapshot(
            cid,
            [{"invalid_key": "no text or state"}],
            "2026-09-13T12:00:00Z",
        )
        assert applied is False
        assert bridge._is_task_plan_current(cid) is False
        assert bridge.taskPlanVisible is False
        assert bridge.taskProgress == {}
        # Old plan persisted steps still untouched
        assert bridge._task_plans[cid].steps[0]["text"] == "Old Plan"
    finally:
        bridge.close()
        app.processEvents()


def test_empty_snapshot_clears_active_plan(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("EmptySnapshot", "codex", "test", bridge._settings.root)
        db.update_conversation(cid, status="running")
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        orch._handle_event(RuntimeEvent(cid, "turn_started"))
        orch._handle_event(RuntimeEvent(
            cid, "task_plan_updated", payload={"steps": [{"text": "Active Step", "state": "running"}]}
        ))
        assert bridge.taskPlanVisible is True
        assert bridge.taskProgress == {"step": "Active Step", "completed": 0, "total": 1}

        # Empty snapshot [] arrives
        orch._handle_event(RuntimeEvent(cid, "task_plan_updated", payload={"steps": []}))
        assert bridge.taskSteps == []
        assert bridge.taskProgress == {}
        assert bridge.taskPlanVisible is False

        bridge.refresh()
        row = next(r for r in bridge._all_conversations if r["conversationId"] == cid)
        assert row["taskStep"] == ""
    finally:
        bridge.close()
        app.processEvents()


def test_antigravity_plan_updated_e2e(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("AG", "antigravity", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        from vrsoft_extractor.mary.provider_adapters.antigravity import AntigravityProvider

        provider = AntigravityProvider()
        state = {"session": "sess_ag", "cancelled": False}

        orch._handle_event(RuntimeEvent(cid, "turn_started"))

        # ACP sends session/update with PlanUpdated
        params = {
            "sessionId": "sess_ag",
            "update": {
                "sessionUpdate": "PlanUpdated",
                "entries": [
                    {"content": "Step 1", "status": "completed"},
                    {"content": "Step 2", "status": "in_progress"},
                    {"content": "Step 3", "status": "pending"},
                ],
            },
        }
        # Provider updates and dispatches canonical event to callback (orch._handle_event)
        provider._update(cid, state, orch._handle_event, "session/update", params)

        assert bridge.taskPlanVisible is True
        assert bridge.taskProgress == {"step": "Step 2", "completed": 1, "total": 3}
        assert [s["state"] for s in bridge.taskSteps] == ["completed", "running", "pending"]

        # Terminal clears active progress
        bridge._on_runtime_event(RuntimeEvent(cid, "turn_completed"))
        assert bridge.taskProgress == {}
        assert bridge.taskPlanVisible is False
        assert [s["state"] for s in bridge.taskSteps] == ["completed", "running", "pending"]
    finally:
        bridge.close()
        app.processEvents()


def test_immediate_followup_survives_previous_pending_terminal(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("Followup", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        def emit(kind, text="", payload=None, at="2026-09-13T12:00:00Z"):
            orch._handle_event(RuntimeEvent(cid, kind, text, payload or {}, at))

        # 1. Turn A starts
        emit("turn_started", payload={"execution_id": 100})
        emit(
            "task_plan_updated",
            payload={
                "execution_id": 100,
                "steps": [
                    {"text": "Step A1", "state": "running"},
                    {"text": "Step A2", "state": "pending"},
                ],
            },
        )
        assert bridge.taskPlanVisible is True
        assert bridge.taskProgress == {"step": "Step A1", "completed": 0, "total": 2}

        # Assistant delta for Turn A
        emit("assistant_delta", "Delta response from turn A", payload={"execution_id": 100})

        # 2. Force visual backlog and queue terminal for Turn A
        bridge._stream_pending_text = "Draining text backlog from turn A"
        bridge._queue_terminal_state("turn_completed", conversation_id=cid, execution_id=100)

        # Invariants: pending terminal exists, active progress cleared, turnRunning is False
        assert bridge._pending_terminal is not None
        assert bridge._pending_terminal["conversation_id"] == cid
        assert bridge._pending_terminal["execution_id"] == 100
        assert bridge.turnRunning is False
        assert bridge.taskProgress == {}

        # 3. User sends immediate follow-up B
        with patch.object(bridge._orchestrator, "send"):
            bridge.sendMessage("Follow-up message B")

        # Invariant: Turn B is running and pending terminal from A cannot clear B
        assert bridge.turnRunning is True
        assert cid in bridge._active_turns
        assert bridge._pending_terminal is None
        assert bridge._stream_pending_text == ""

        # Draining / flushing from Turn A or stale terminal step cannot clear B
        bridge._flush_stream_step()
        assert bridge.turnRunning is True
        assert cid in bridge._active_turns

        # 4. A fresh task plan arrives for Turn B
        emit(
            "task_plan_updated",
            payload={
                "execution_id": 101,
                "steps": [
                    {"text": "Step B1", "state": "running"},
                    {"text": "Step B2", "state": "pending"},
                ],
            },
        )
        assert bridge.taskProgress != {}
        assert bridge.taskProgress == {"step": "Step B1", "completed": 0, "total": 2}
        assert bridge.taskPlanVisible is True

        # 5. Finalize B and assert normal cleanup
        bridge._queue_terminal_state("turn_completed", conversation_id=cid, execution_id=101)
        assert bridge.turnRunning is False
        assert bridge.taskProgress == {}
        assert bridge.taskPlanVisible is False
    finally:
        bridge.close()
        app.processEvents()


def test_execution_id_isolation_between_consecutive_turns(tmp_path):
    app, _settings, db, bridge = _make_bridge(tmp_path)
    try:
        cid = db.create_conversation("Isolation", "codex", "test", bridge._settings.root)
        bridge.refresh()
        bridge.selectConversationId(cid)
        orch = bridge._orchestrator
        orch._external_callbacks[cid] = bridge._on_runtime_event

        def emit(kind, text="", payload=None, at="2026-09-13T12:00:00Z"):
            orch._handle_event(RuntimeEvent(cid, kind, text, payload or {}, at))

        # Turn A with execution_id = 100 starts and finishes
        emit("turn_started", payload={"execution_id": 100})
        emit(
            "task_plan_updated",
            payload={
                "execution_id": 100,
                "steps": [{"text": "Plan A", "state": "running"}],
            },
        )
        assert bridge.taskPlanVisible is True
        bridge._queue_terminal_state("turn_completed", conversation_id=cid, execution_id=100)
        assert bridge.turnRunning is False
        assert bridge.taskProgress == {}

        # Turn B with execution_id = 101 starts and supplies its plan
        emit("turn_started", payload={"execution_id": 101})
        emit(
            "task_plan_updated",
            payload={
                "execution_id": 101,
                "steps": [
                    {"text": "Plan B1", "state": "running"},
                    {"text": "Plan B2", "state": "pending"},
                ],
            },
        )
        assert bridge.turnRunning is True
        assert bridge.taskPlanVisible is True
        assert bridge.taskProgress == {"step": "Plan B1", "completed": 0, "total": 2}
        status_before = bridge.statusText

        # Any terminal with execution_id = 100 arriving late cannot alter Turn B's state
        bridge._queue_terminal_state("turn_completed", conversation_id=cid, execution_id=100)
        bridge._finalize_terminal_state("turn_completed", conversation_id=cid, execution_id=100)
        emit("turn_completed", payload={"execution_id": 100})

        # Turn B remains completely unaffected: still running, plan visible, progress intact
        assert bridge.turnRunning is True
        assert cid in bridge._active_turns
        assert bridge.taskPlanVisible is True
        assert bridge.taskProgress == {"step": "Plan B1", "completed": 0, "total": 2}
        assert bridge.statusText == status_before
        assert bridge.statusText != "Pronto"

        # Terminal for Turn B (execution_id = 101) finalizes normally
        emit("turn_completed", payload={"execution_id": 101})
        assert bridge.turnRunning is False
        assert bridge.taskProgress == {}
        assert bridge.taskPlanVisible is False
    finally:
        bridge.close()
        app.processEvents()

import json

import pytest
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

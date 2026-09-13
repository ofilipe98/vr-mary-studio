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

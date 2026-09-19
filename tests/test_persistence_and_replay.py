"""Tests for Stage 6: Persistence and Replay.

Validates:
- Deterministic replay of tool activities from runtime_events table.
- Monotonic terminal state protection during replay (completed/error cannot regress to running).
- Non-masking invariant: tools left running on interrupted/error turns are restored as
  'interrupted' or 'error', NEVER blindly converted to 'completed'.
- Preservation of rich presentation fields (command, durationLabel, badgeText, cwd, diffs)
  across reload.
"""
from pathlib import Path
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.models import RuntimeEvent

pytestmark = pytest.mark.qml


@pytest.fixture
def chat_env(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "data", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    bridge = ChatBridge(settings, db, prefs)
    try:
        yield bridge, db
    finally:
        bridge.close()
        app.processEvents()


def test_replay_historical_completed_tools_preserves_presentation(chat_env):
    bridge, db = chat_env
    cid = db.create_conversation("Replay Test", "codex", "gpt-5.6", bridge._settings.root)
    eid = db.add_message(cid, "user", "Execute o comando de teste")

    # Save a command execution started and completed
    db.add_event(RuntimeEvent(
        cid, "tool_event", "Executando pytest",
        {
            "execution_id": eid,
            "lifecycle": "tool_started",
            "item": {
                "id": "tool_cmd_1",
                "name": "commandExecution",
                "type": "commandExecution",
                "command": "pytest tests/unit",
                "cwd": "/workspace/project",
            },
        }
    ))
    db.add_event(RuntimeEvent(
        cid, "tool_event", "Comando executado",
        {
            "execution_id": eid,
            "lifecycle": "tool_completed",
            "item": {
                "id": "tool_cmd_1",
                "name": "commandExecution",
                "type": "commandExecution",
                "command": "pytest tests/unit",
                "cwd": "/workspace/project",
                "exit_code": 0,
            },
            "output": "3 passed in 0.2s",
            "success": True,
        }
    ))

    # Add assistant response
    db.add_event(RuntimeEvent(
        cid, "assistant_completed", "",
        {"execution_id": eid, "message_key": f"{eid}:1", "final_text": "Testes executados com sucesso!"}
    ))
    db.upsert_assistant_message(cid, "Testes executados com sucesso!", execution_id=eid, execution_ordinal=1)

    # Replay timeline
    rows = db.messages(cid)
    assert bridge._reload_execution_timeline(cid, rows) is True

    # Validate messages in bridge
    items = bridge.messages._items
    activity_msg = next((m for m in items if m.get("role") == "activity"), None)
    assert activity_msg is not None

    tool_data = activity_msg["activityData"][0]
    assert tool_data["id"] == "tool_cmd_1"
    assert tool_data["state"] == "completed"
    assert tool_data["command"] == "pytest tests/unit"
    assert tool_data["cwd"] == "/workspace/project"
    assert "3 passed" in tool_data["output"]
    assert tool_data["badgeVariant"] == "success"


def test_replay_uncompleted_tool_is_marked_interrupted_not_completed(chat_env):
    bridge, db = chat_env
    cid = db.create_conversation("Interrupted Turn", "codex", "gpt-5.6", bridge._settings.root)
    eid = db.add_message(cid, "user", "Comece uma tarefa longa")

    # Tool starts but never gets a completion event before conversation terminates
    db.add_event(RuntimeEvent(
        cid, "tool_event", "Baixando pacote",
        {
            "execution_id": eid,
            "lifecycle": "tool_started",
            "item": {
                "id": "tool_long_run",
                "name": "commandExecution",
                "type": "commandExecution",
                "command": "npm install",
            },
        }
    ))
    # Turn completed unexpectedly or application shut down
    db.add_event(RuntimeEvent(
        cid, "turn_completed", "",
        {"execution_id": eid}
    ))

    rows = db.messages(cid)
    assert bridge._reload_execution_timeline(cid, rows) is True

    items = bridge.messages._items
    activity_msg = next((m for m in items if m.get("role") == "activity"), None)
    assert activity_msg is not None

    tool_data = activity_msg["activityData"][0]
    assert tool_data["id"] == "tool_long_run"
    # Mandatory invariant: must NOT be 'completed'
    assert tool_data["state"] == "interrupted"
    assert tool_data["badgeText"] == "interrompido"
    assert tool_data["badgeVariant"] == "warning"


def test_replay_error_turn_marks_uncompleted_tool_as_error(chat_env):
    bridge, db = chat_env
    cid = db.create_conversation("Error Turn", "codex", "gpt-5.6", bridge._settings.root)
    # Set conversation status to error
    db.update_conversation(cid, status="error")
    eid = db.add_message(cid, "user", "Execute tarefa que falha")

    db.add_event(RuntimeEvent(
        cid, "tool_event", "Iniciando processo",
        {
            "execution_id": eid,
            "lifecycle": "tool_started",
            "item": {
                "id": "tool_err_1",
                "name": "commandExecution",
                "type": "commandExecution",
                "command": "python crash.py",
            },
        }
    ))
    db.add_event(RuntimeEvent(
        cid, "error", "Process crashed fatally",
        {"execution_id": eid}
    ))

    rows = db.messages(cid)
    assert bridge._reload_execution_timeline(cid, rows) is True

    items = bridge.messages._items
    activity_msg = next((m for m in items if m.get("role") == "activity"), None)
    assert activity_msg is not None

    tool_data = activity_msg["activityData"][0]
    assert tool_data["state"] == "error"
    assert tool_data["badgeText"] == "falhou"
    assert tool_data["badgeVariant"] == "error"


def test_replay_out_of_order_events_cannot_revert_terminal_state(chat_env):
    bridge, db = chat_env
    cid = db.create_conversation("Order Test", "codex", "gpt-5.6", bridge._settings.root)
    eid = db.add_message(cid, "user", "Teste de ordenacao")

    # 1. Tool completes first
    db.add_event(RuntimeEvent(
        cid, "tool_event", "Comando finalizado",
        {
            "execution_id": eid,
            "lifecycle": "tool_completed",
            "item": {
                "id": "tool_ord_1",
                "name": "commandExecution",
                "type": "commandExecution",
                "command": "git status",
            },
            "output": "nothing to commit",
            "success": True,
        }
    ))
    # 2. Out-of-order stale "started" event arrives late in log
    db.add_event(RuntimeEvent(
        cid, "tool_event", "Comando iniciando",
        {
            "execution_id": eid,
            "lifecycle": "tool_started",
            "item": {
                "id": "tool_ord_1",
                "name": "commandExecution",
                "type": "commandExecution",
                "command": "git status",
            },
        }
    ))
    db.add_event(RuntimeEvent(
        cid, "turn_completed", "",
        {"execution_id": eid}
    ))

    rows = db.messages(cid)
    assert bridge._reload_execution_timeline(cid, rows) is True

    items = bridge.messages._items
    activity_msg = next((m for m in items if m.get("role") == "activity"), None)
    assert activity_msg is not None

    tool_data = activity_msg["activityData"][0]
    # Late running event MUST NOT revert completed state!
    assert tool_data["state"] == "completed"
    assert tool_data["badgeVariant"] == "success"

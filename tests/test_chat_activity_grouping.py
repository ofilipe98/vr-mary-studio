"""Unit tests verifying tool calling deduplication and grouping in chat activity."""
import pytest
from PySide6.QtCore import QSettings

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.frontend.chat import ChatBridge


@pytest.fixture
def chat_bridge(tmp_path):
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    bridge = ChatBridge(settings, db, prefs)
    try:
        yield bridge, db
    finally:
        bridge.close()


def test_live_tool_events_are_grouped_into_single_activity(chat_bridge):
    """Multiple tool_events in the same turn must be grouped into one activity card."""
    bridge, db = chat_bridge
    cid = db.create_conversation("Teste Grouping", "codex", "gpt-5.6", bridge._settings.root)
    bridge.refresh()
    bridge.selectConversation(0)

    # Simulate turn started
    bridge._on_runtime_event(RuntimeEvent(cid, "turn_started", "", {"execution_id": 100}))

    # 7 tool calls run sequentially
    for i in range(1, 8):
        bridge._on_runtime_event(RuntimeEvent(
            cid, "tool_event", f"Executando tool {i}",
            {
                "execution_id": 100,
                "lifecycle": "tool_started",
                "item": {"id": f"call_{i}", "name": f"test_tool_{i}", "type": "tool"},
            }
        ))
        # Complete the tool
        bridge._on_runtime_event(RuntimeEvent(
            cid, "tool_event", f"Concluiu tool {i}",
            {
                "execution_id": 100,
                "lifecycle": "tool_completed",
                "item": {"id": f"call_{i}", "name": f"test_tool_{i}", "type": "tool"},
                "success": True,
            }
        ))

    # Check messages in bridge
    activity_messages = [m for m in bridge.messages._items if m.get("role") == "activity"]
    assert len(activity_messages) == 1, f"Expected exactly 1 activity card, found {len(activity_messages)}"

    activity = activity_messages[0]
    assert activity["messageKey"] == "activity:100:0"
    assert len(activity["activityData"]) == 7
    for idx, tool in enumerate(activity["activityData"], start=1):
        assert tool["id"] == f"call_{idx}"
        assert tool["state"] == "completed"

    # Now assistant starts
    bridge._on_runtime_event(RuntimeEvent(cid, "assistant_started", "", {"execution_id": 100, "message_key": "100:1"}))
    assert activity["isStreaming"] is False

    # Turn completes
    bridge._on_runtime_event(RuntimeEvent(cid, "turn_completed", "", {"execution_id": 100}))
    assert activity["isStreaming"] is False


def test_reload_execution_timeline_groups_historical_tools(chat_bridge):
    """Historical tool events from runtime_events must be grouped on reload."""
    bridge, db = chat_bridge
    cid = db.create_conversation("Historical Grouping", "codex", "gpt-5.6", bridge._settings.root)
    user_msg_id = db.add_message(cid, "user", "Como funciona?")

    # Insert 7 historical tool events in runtime_events table
    for i in range(1, 8):
        db.add_event(RuntimeEvent(
            cid, "tool_event", f"Ferramenta {i}",
            {
                "execution_id": user_msg_id,
                "lifecycle": "tool_completed",
                "item": {"id": f"hist_tool_{i}", "name": f"tool_{i}", "type": "tool"},
                "success": True,
            }
        ))

    # Insert assistant completed event and message
    db.add_event(RuntimeEvent(
        cid, "assistant_completed", "",
        {"execution_id": user_msg_id, "message_key": f"{user_msg_id}:1", "final_text": "Resposta final"}
    ))
    db.upsert_assistant_message(cid, "Resposta final", execution_id=user_msg_id, execution_ordinal=1)

    # Reload timeline
    rows = db.messages(cid)
    reloaded = bridge._reload_execution_timeline(cid, rows)
    assert reloaded is True

    # Check that messages in bridge contain 1 user message, 1 grouped activity card, and 1 assistant message
    messages = bridge.messages._items
    roles = [m.get("role") for m in messages]
    assert roles == ["user", "activity", "assistant"]

    activity = messages[1]
    assert len(activity["activityData"]) == 7
    assert [t["id"] for t in activity["activityData"]] == [f"hist_tool_{i}" for i in range(1, 8)]


def test_late_tool_completion_updates_original_group_live_and_after_reload(chat_bridge):
    bridge, db = chat_bridge
    cid = db.create_conversation("Interleaved", "codex", "test", bridge._settings.root)
    eid = db.add_message(cid, "user", "test")
    bridge.refresh()
    bridge.selectConversation(0)
    changes = []
    bridge.messages.dataChanged.connect(lambda *args: changes.append(args))
    events = [
        RuntimeEvent(cid, "tool_event", "read details", {"execution_id": eid, "lifecycle": "tool_started",
                     "item": {"id": "tool-1", "name": "read", "type": "tool"}}),
        RuntimeEvent(cid, "assistant_started", payload={"execution_id": eid, "message_key": f"{eid}:1"}),
        RuntimeEvent(cid, "tool_event", payload={"execution_id": eid, "lifecycle": "tool_completed",
                     "item": {"id": "tool-1", "name": "read", "type": "tool"}, "success": True}),
    ]
    for event in events:
        db.add_event(event)
        bridge._on_runtime_event(event)
    assert changes, "Qt model must notify rendered delegates"
    activities = [r for r in bridge.messages._items if r["role"] == "activity"]
    assert len(activities) == 1
    assert activities[0]["activityData"][0]["state"] == "completed"
    bridge._reload_execution_timeline(cid, db.messages(cid))
    activities = [r for r in bridge.messages._items if r["role"] == "activity"]
    assert len(activities) == 1
    assert activities[0]["activityData"][0]["state"] == "completed"

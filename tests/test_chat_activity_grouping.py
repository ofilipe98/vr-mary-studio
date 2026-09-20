"""Unit tests verifying tool calling deduplication and grouping in chat activity."""
import logging

import pytest
from PySide6.QtCore import QSettings

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.provider_adapters.antigravity import AntigravityProvider


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


def _antigravity_tool_event(
    provider: AntigravityProvider,
    conversation_id: str,
    execution_id: int,
    update: dict,
) -> RuntimeEvent:
    """Build the RuntimeEvent through the production ACP provider adapter."""
    emitted = []
    provider._update(
        conversation_id,
        {"session": "session-1", "cancelled": False},
        emitted.append,
        "session/update",
        {"sessionId": "session-1", "update": update},
    )
    assert len(emitted) == 1
    source = emitted[0]
    assert source.kind == "tool_event"
    payload = dict(source.payload)
    payload["execution_id"] = execution_id
    return RuntimeEvent(
        conversation_id,
        source.kind,
        source.text,
        payload,
        source.created_at,
    )


def _typed_tool_sequence(
    provider: AntigravityProvider,
    conversation_id: str,
    execution_id: int,
    tool_id: str,
    *,
    command: str,
    title: str,
) -> list[RuntimeEvent]:
    updates = [
        {
            "sessionUpdate": "tool_call",
            "toolCallId": tool_id,
            "title": title,
            "kind": "execute",
            "status": "in_progress",
            "rawInput": {"CommandLine": command},
        },
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": tool_id,
            "status": "in_progress",
            "rawOutput": {"combinedOutput": "iniciando"},
        },
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": tool_id,
            "status": "in_progress",
            "rawOutput": {"combinedOutput": "iniciando\nconcluindo"},
        },
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": tool_id,
            "status": "completed",
            "rawOutput": {"combinedOutput": "iniciando\nconcluindo\npronto", "exitCode": 0},
        },
    ]
    return [
        _antigravity_tool_event(
            provider, conversation_id, execution_id, update
        )
        for update in updates
    ]


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


def test_antigravity_typed_acp_completed_turn_has_no_active_tool_rows(
    chat_bridge, caplog
) -> None:
    bridge, db = chat_bridge
    provider = AntigravityProvider()
    cid = db.create_conversation(
        "Antigravity typed ACP", "antigravity", "gemini", bridge._settings.root
    )
    execution_id = db.add_message(cid, "user", "Execute os testes")
    bridge.refresh()
    bridge.selectConversationId(cid)

    caplog.set_level(logging.WARNING, logger="mary.tool_activity")
    bridge._on_runtime_event(
        RuntimeEvent(cid, "turn_started", payload={"execution_id": execution_id})
    )
    for event in _typed_tool_sequence(
        provider,
        cid,
        execution_id,
        "tool-1",
        command="pytest -q",
        title="Executar testes",
    ):
        bridge._on_runtime_event(event)
    bridge._on_runtime_event(
        RuntimeEvent(cid, "turn_completed", payload={"execution_id": execution_id})
    )

    activities = [row for row in bridge.messages._items if row["role"] == "activity"]
    assert len(activities) == 1
    assert activities[0]["isStreaming"] is False
    assert len(activities[0]["activityData"]) == 1
    tool = activities[0]["activityData"][0]
    assert tool["id"] == "tool-1"
    assert tool["state"] == "completed"
    assert all(
        entry["state"] not in {"running", "waiting_approval"}
        for entry in activities[0]["activityData"]
    )
    assert "was still active at turn completion" not in caplog.text
    assert "anon:exec:noid" not in caplog.text

    # Parallel ACP tools keep independent identities even with interleaved updates.
    parallel_cid = db.create_conversation(
        "Antigravity parallel ACP", "antigravity", "gemini", bridge._settings.root
    )
    parallel_execution = db.add_message(parallel_cid, "user", "Execute em paralelo")
    bridge.refresh()
    bridge.selectConversationId(parallel_cid)
    bridge._on_runtime_event(
        RuntimeEvent(
            parallel_cid,
            "turn_started",
            payload={"execution_id": parallel_execution},
        )
    )
    sequences = {
        "tool-a": _typed_tool_sequence(
            provider,
            parallel_cid,
            parallel_execution,
            "tool-a",
            command="ruff check .",
            title="Validar lint",
        ),
        "tool-b": _typed_tool_sequence(
            provider,
            parallel_cid,
            parallel_execution,
            "tool-b",
            command="pytest -q",
            title="Validar testes",
        ),
    }
    for index in range(4):
        bridge._on_runtime_event(sequences["tool-a"][index])
        bridge._on_runtime_event(sequences["tool-b"][index])
    bridge._on_runtime_event(
        RuntimeEvent(
            parallel_cid,
            "turn_completed",
            payload={"execution_id": parallel_execution},
        )
    )
    parallel_rows = [
        row for row in bridge.messages._items if row["role"] == "activity"
    ]
    assert len(parallel_rows) == 1
    assert {tool["id"] for tool in parallel_rows[0]["activityData"]} == {
        "tool-a",
        "tool-b",
    }
    assert all(
        tool["state"] == "completed" for tool in parallel_rows[0]["activityData"]
    )
    assert not any(
        tool["id"].startswith("anon:")
        for tool in parallel_rows[0]["activityData"]
    )
    assert "was still active at turn completion" not in caplog.text
    assert "anon:exec:noid" not in caplog.text


def test_antigravity_typed_acp_replay_preserves_single_completed_tool(
    chat_bridge,
) -> None:
    bridge, db = chat_bridge
    provider = AntigravityProvider()
    cid = db.create_conversation(
        "Antigravity replay", "antigravity", "gemini", bridge._settings.root
    )
    execution_id = db.add_message(cid, "user", "Liste os arquivos")
    bridge.refresh()
    bridge.selectConversationId(cid)
    events = [
        RuntimeEvent(cid, "turn_started", payload={"execution_id": execution_id}),
        *_typed_tool_sequence(
            provider,
            cid,
            execution_id,
            "tool-replay",
            command="rg --files",
            title="Listar arquivos",
        ),
        RuntimeEvent(
            cid, "turn_completed", payload={"execution_id": execution_id}
        ),
    ]
    for event in events:
        db.add_event(event)
        bridge._on_runtime_event(event)

    live_rows = [row for row in bridge.messages._items if row["role"] == "activity"]
    assert len(live_rows) == 1
    assert len(live_rows[0]["activityData"]) == 1
    live_tool = dict(live_rows[0]["activityData"][0])

    assert bridge._reload_execution_timeline(cid, db.messages(cid)) is True
    replay_rows = [
        row for row in bridge.messages._items if row["role"] == "activity"
    ]
    assert len(replay_rows) == 1
    assert len(replay_rows[0]["activityData"]) == 1
    replay_tool = replay_rows[0]["activityData"][0]
    for key in ("id", "state", "text", "title", "command", "exitCode"):
        assert replay_tool[key] == live_tool[key]
    assert replay_tool["id"] == "tool-replay"
    assert replay_tool["state"] == "completed"


def test_antigravity_orphan_still_warns_and_is_interrupted(
    chat_bridge, caplog
) -> None:
    bridge, db = chat_bridge
    provider = AntigravityProvider()
    cid = db.create_conversation(
        "Antigravity orphan", "antigravity", "gemini", bridge._settings.root
    )
    execution_id = db.add_message(cid, "user", "Inicie e interrompa")
    bridge.refresh()
    bridge.selectConversationId(cid)
    caplog.set_level(logging.WARNING, logger="mary.tool_activity")

    bridge._on_runtime_event(
        RuntimeEvent(cid, "turn_started", payload={"execution_id": execution_id})
    )
    bridge._on_runtime_event(
        _antigravity_tool_event(
            provider,
            cid,
            execution_id,
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "tool-orphan",
                "title": "Processo sem terminal",
                "kind": "execute",
                "status": "in_progress",
                "rawInput": {"CommandLine": "sleep 10"},
            },
        )
    )
    bridge._on_runtime_event(
        RuntimeEvent(cid, "turn_completed", payload={"execution_id": execution_id})
    )

    activities = [row for row in bridge.messages._items if row["role"] == "activity"]
    assert len(activities) == 1
    assert activities[0]["activityData"][0]["id"] == "tool-orphan"
    assert activities[0]["activityData"][0]["state"] == "interrupted"
    assert "Tool tool-orphan was still active at turn completion" in caplog.text

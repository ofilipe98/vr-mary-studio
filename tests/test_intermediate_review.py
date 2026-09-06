"""Acceptance regressions reproducing defects found in the Opus implementation.

Included in the regular test suite after the fixes.
Only temporary databases and mock providers are used.
"""
import os
import runpy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from vrsoft_extractor.mary.models import RuntimeEvent, ConversationOptions
from vrsoft_extractor.mary.orchestrator import _ExecutionState

ROOT = Path(__file__).resolve().parents[1]
helpers = runpy.run_path(str(ROOT / "tests/test_intermediate_messages.py"))


@pytest.fixture
def session(tmp_path):
    orch, db = helpers["TestCancellationAndError"]()._make_orchestrator(tmp_path)
    cid = helpers["_create_conversation"](db)
    orch._execution_states[cid] = _ExecutionState(execution_id=100)
    orch._pending_response_modes[cid] = "native"
    orch._assistant_buffers[cid] = []
    orch._pending_user_messages[cid] = 100
    return orch, db, cid


def emit(orch, cid, kind, text="", **payload):
    orch._handle_event(RuntimeEvent(cid, kind, text, payload))


def answers(db, cid):
    return [r["content"] for r in db.messages(cid) if r["role"] == "assistant"]


def test_second_turn_preserves_first_turn(session):
    orch, db, cid = session
    emit(orch, cid, "assistant_started", itemId="A")
    emit(orch, cid, "assistant_completed", final_text="Answer A")
    orch._finalize_turn_completed(RuntimeEvent(cid, "turn_completed"), "", False, "", "", orch._execution_states[cid])
    # Same initialization as send() for the next admitted execution.
    orch._execution_states[cid] = _ExecutionState(execution_id=200)
    orch._pending_response_modes[cid] = "native"
    orch._pending_user_messages[cid] = 200
    emit(orch, cid, "assistant_started", itemId="B")
    emit(orch, cid, "assistant_completed", final_text="Answer B")
    assert answers(db, cid) == ["Answer A", "Answer B"]


def test_commentary_deltas_are_public_messages(session):
    orch, db, cid = session
    emit(orch, cid, "assistant_started", itemId="M1", phase="commentary")
    emit(orch, cid, "assistant_delta", "Vou verificar.", itemId="M1", phase="commentary")
    emit(orch, cid, "assistant_completed", itemId="M1", phase="commentary")
    assert answers(db, cid) == ["Vou verificar."]


def test_completed_old_item_does_not_complete_new_item(session):
    orch, db, cid = session
    emit(orch, cid, "assistant_started", itemId="M1")
    emit(orch, cid, "assistant_completed", itemId="M1", final_text="First")
    emit(orch, cid, "assistant_started", itemId="M2")
    emit(orch, cid, "assistant_delta", "Second", itemId="M2")
    emit(orch, cid, "assistant_completed", itemId="M1", final_text="First")
    assert answers(db, cid) == ["First"]
    assert orch._execution_states[cid].current_text() == "Second"


def test_completed_item_releases_active_key(session):
    orch, db, cid = session
    emit(orch, cid, "assistant_started", itemId="M1")
    emit(orch, cid, "assistant_completed", itemId="M1", final_text="First")
    assert orch._execution_states[cid].current_message_key == ""


@pytest.mark.parametrize("terminal", ["cancelled", "error"])
def test_partial_message_survives_controlled_terminal(session, terminal):
    orch, db, cid = session
    emit(orch, cid, "assistant_started", itemId="M1")
    emit(orch, cid, "assistant_completed", itemId="M1", final_text="First")
    emit(orch, cid, "assistant_started", itemId="M2")
    emit(orch, cid, "assistant_delta", "Partial second", itemId="M2")
    orch._finalize_turn_completed(RuntimeEvent(cid, "turn_completed"), "Partial second", False, terminal, "", orch._execution_states[cid])
    assert answers(db, cid) == ["First", "Partial second"]
    assert db.messages(cid)[-1]["message_status"] in {"interrupted", "cancelled", "error", "failed"}


def test_buffered_vr_draft_is_not_published(session, tmp_path):
    orch, db, cid = session
    orch._pending_response_modes[cid] = "vr"
    published = []
    orch._external_callbacks[cid] = published.append
    draft = '{"answer":"Unvalidated draft","evidence_ids":[]}'
    provider = MagicMock()

    def send(*args):
        callback = args[6]
        callback(RuntimeEvent(cid, "turn_started"))
        callback(RuntimeEvent(cid, "assistant_started", payload={"itemId": "draft"}))
        callback(RuntimeEvent(cid, "assistant_delta", draft))
        callback(RuntimeEvent(cid, "assistant_completed", payload={"itemId": "draft", "final_text": draft}))
        callback(RuntimeEvent(cid, "turn_completed"))

    provider.send_message.side_effect = send
    result = orch._run_buffered_main_turn(cid, "native", provider, "model", "medium", tmp_path, "prompt", ConversationOptions(), [])
    assert result[0] == draft
    assert answers(db, cid) == []
    assert not [e for e in published if e.kind in {"assistant_started", "assistant_completed"}]


@pytest.fixture
def bridge(tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from vrsoft_extractor.mary.config import MarySettings
    from vrsoft_extractor.mary.db import MaryDatabase
    from vrsoft_extractor.mary.frontend.chat import ChatBridge
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation("Audit", "codex", "test", settings.root)
    chat = ChatBridge(settings, db, QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat))
    chat._selected = {"conversationId": cid}
    chat._messages.replace([])
    chat._active_turns.add(cid)
    chat._vr_mode = "off"
    chat._sync_selected_turn_state()
    try:
        yield chat, db, cid
    finally:
        chat.close()


def incoming(chat, cid, kind, text="", **payload):
    chat._on_runtime_event(RuntimeEvent(cid, kind, text, payload))


def test_bridge_flush_does_not_copy_m1_into_m2(bridge):
    chat, db, cid = bridge
    incoming(chat, cid, "assistant_started", message_key="100:1")
    incoming(chat, cid, "assistant_delta", "First")
    chat._flush_stream_step()
    incoming(chat, cid, "assistant_completed", message_key="100:1", final_text="First")
    incoming(chat, cid, "assistant_started", message_key="100:2")
    incoming(chat, cid, "assistant_delta", "Second")
    chat._flush_stream_step()
    rows = [r for r in chat._messages._items if r.get("messageKey") == "100:2"]
    assert rows[0]["content"] == "Second"


def test_tool_between_message_deltas_does_not_duplicate_row(bridge):
    chat, db, cid = bridge
    incoming(chat, cid, "assistant_started", message_key="100:1", execution_id=100)
    incoming(chat, cid, "assistant_delta", "First", message_key="100:1", execution_id=100)
    incoming(chat, cid, "tool_event", "Read", execution_id=100, item={"id": "tool", "type": "commandExecution"})
    incoming(chat, cid, "assistant_delta", " part", message_key="100:1", execution_id=100)
    chat._flush_stream_step()
    assert len([r for r in chat._messages._items if r["role"] == "assistant"]) == 1
    incoming(chat, cid, "assistant_completed", message_key="100:1", execution_id=100, final_text="First part")
    incoming(chat, cid, "assistant_delta", "late", message_key="100:1", execution_id=100)
    chat._flush_stream_step()
    assert chat._messages._items[0]["content"] == "First part"


def test_bridge_rejects_old_execution_queued_started(bridge):
    chat, db, cid = bridge
    incoming(chat, cid, "assistant_started", message_key="200:1", execution_id=200)
    incoming(chat, cid, "assistant_started", message_key="100:1", execution_id=100)
    assert chat._current_message_key == "200:1"
    assert len(chat._messages._items) == 1


def test_reload_preserves_message_keys(bridge):
    chat, db, cid = bridge
    db.upsert_assistant_message(cid, "First", provider_message_id="M1", execution_ordinal=1)
    db.upsert_assistant_message(cid, "Second", provider_message_id="M2", execution_ordinal=2)
    chat._reload_selected_messages()
    keys = [r["messageKey"] for r in chat._messages._items if r["role"] == "assistant"]
    assert all(keys) and len(set(keys)) == 2


def test_cancel_does_not_complete_pending_plan_steps(bridge):
    chat, db, cid = bridge
    chat._activity_steps = [{"text": "Done", "state": "completed"}, {"text": "Running", "state": "running"}, {"text": "Never run", "state": "pending"}]
    # Defer UI teardown; inspect the terminal transition itself.
    chat._stream_pending_text = "pending flush"
    chat._queue_terminal_state("orchestration_cancelled")
    assert chat._activity_steps[-1]["state"] != "completed"


def test_codex_completed_reads_existing_text_shape(session):
    import threading
    from vrsoft_extractor.mary.providers import CodexProvider
    orch, db, cid = session
    events = []
    provider = CodexProvider.__new__(CodexProvider)
    provider._state_lock = threading.Lock()
    provider._native_to_local = {"thread": cid}
    provider._callbacks = {cid: events.append}
    provider._active_turns = {cid: "turn"}
    provider._completed_turn_ids = {}
    provider._item_turn_ids = {}
    provider._assistant_item_keys = {}
    provider._assistant_item_phases = {}
    provider._handle_server_message({"method": "item/completed", "params": {"threadId": "thread", "turnId": "turn", "item": {"type": "agentMessage", "id": "M1", "phase": "commentary", "text": "Vou verificar."}}})
    assert events[0].payload["final_text"] == "Vou verificar."


def test_vr_final_waits_for_validation(session):
    orch, db, cid = session
    orch._pending_response_modes[cid] = "vr"
    events = []
    orch._external_callbacks[cid] = events.append
    emit(orch, cid, "assistant_started", itemId="final", phase="final_answer")
    emit(orch, cid, "assistant_delta", "unvalidated", itemId="final")
    emit(orch, cid, "assistant_completed", itemId="final", final_text="unvalidated")
    assert answers(db, cid) == [] and events == []
    orch._validate_direct_response = MagicMock(return_value="validated")
    orch._finalize_turn_completed(RuntimeEvent(cid, "turn_completed"), "", False, "", "", orch._execution_states[cid])
    assert answers(db, cid) == ["validated"]
    assert [e.payload["final_text"] for e in events if e.kind == "assistant_completed"] == ["validated"]


def test_finalizer_of_a_does_not_mutate_b(session):
    orch, db, cid = session
    old = orch._execution_states[cid]
    old.start_message()
    old.append_delta("A")
    orch._pending_user_messages[cid] = 200
    orch._callback_generations[cid] = 2
    cb = MagicMock()
    orch._external_callbacks[cid] = cb
    db.update_conversation(cid, status="running")
    event = RuntimeEvent(cid, "turn_completed", payload={"_owner_generation": 1, "_owner_message": 100})
    orch._finalize_turn_completed(event, "A", False, "", "", old)
    assert answers(db, cid) == []
    assert db.get_conversation(cid)["status"] == "running"
    assert orch._pending_user_messages[cid] == 200
    assert orch._external_callbacks[cid] is cb
    cb.assert_not_called()


def test_replay_preserves_interleaving_and_active_message(bridge):
    chat, db, cid = bridge
    owner = db.begin_user_turn(cid, "User")
    for kind, text, payload in [
        ("assistant_started", "", {"message_key": f"{owner}:1"}),
        ("assistant_delta", "First", {"message_key": f"{owner}:1"}),
        ("assistant_completed", "", {"message_key": f"{owner}:1", "final_text": "First"}),
        ("tool_event", "Read file", {"item": {"id": "tool1", "type": "commandExecution"}, "lifecycle": "item/completed"}),
        ("assistant_started", "", {"message_key": f"{owner}:2"}),
        ("assistant_delta", "Second", {"message_key": f"{owner}:2"}),
    ]:
        payload["execution_id"] = owner
        # Equal timestamps must not change event order.
        db.add_event(RuntimeEvent(cid, kind, text, payload, "2026-09-06T12:00:00Z"))
    db.upsert_assistant_message(cid, "First", execution_id=owner, execution_ordinal=1)
    chat._reload_selected_messages()
    assert [r["role"] for r in chat._messages._items] == ["user", "assistant", "activity", "assistant"]
    assert chat._current_message_key == f"{owner}:2"
    incoming(chat, cid, "assistant_delta", " continued", message_key=f"{owner}:2", execution_id=owner)
    chat._flush_stream_step()
    assert [r["content"] for r in chat._messages._items if r["role"] == "assistant"] == ["First", "Second continued"]


def test_provider_consumers_with_real_event_shapes(tmp_path):
    import io
    import json
    import threading
    from vrsoft_extractor.mary.providers import ClaudeProvider, OpenCodeProvider
    from vrsoft_extractor.mary.antigravity import AntigravityProvider

    def process(events):
        proc = MagicMock()
        proc.stdout = io.StringIO("\n".join(json.dumps(e) for e in events))
        proc.stderr = io.StringIO("")
        proc.stdin = io.StringIO()
        proc.wait.return_value = proc.poll.return_value = 0
        return proc

    claude = ClaudeProvider.__new__(ClaudeProvider)
    claude._state_lock = threading.Lock()
    claude._active = {}
    native = []
    for mid, text in [("M1", "First"), ("M2", "Second")]:
        native.extend([
            {"type": "stream_event", "event": {"type": "message_start", "message": {"id": mid}}},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}},
            {"type": "stream_event", "event": {"type": "message_stop"}},
        ])
    events = []
    claude._consume("c", process(native), events.append)
    assert [e.payload["final_text"] for e in events if e.kind == "assistant_completed"] == ["First", "Second"]
    assert sum(e.kind == "turn_completed" for e in events) == 1

    opencode = OpenCodeProvider.__new__(OpenCodeProvider)
    opencode._state_lock = threading.Lock()
    opencode._active = {}
    opencode._sessions = {}
    events = []
    native = [{"type": "text", "part": {"id": "p1", "messageID": "M1", "text": text}} for text in ["First", "First", "First part"]]
    native += [{"type": "text", "part": {"id": "p2", "messageID": "M2", "text": "Second"}}]
    opencode._consume("c", "n", process(native), events.append)
    assert [e.payload["final_text"] for e in events if e.kind == "assistant_completed"] == ["First part", "Second"]
    assert "".join(e.text for e in events if e.kind == "assistant_delta") == "First partSecond"

    antigravity = AntigravityProvider.__new__(AntigravityProvider)
    antigravity._lock = threading.Lock()
    antigravity._active = {}
    events = []
    native = [{"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "Only final"}}, {"event": "result", "result": {"status": "SUCCESS"}}]
    antigravity._consume("c", process(native), "request", events.append)
    assert "".join(e.text for e in events if e.kind == "assistant_delta") == "Only final"
    assert not [e for e in events if e.kind == "error"]

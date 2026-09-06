"""Tests for intermediate assistant messages within a single turn.

These tests validate the multi-message lifecycle:
  M1 â†’ activity â†’ M2 â†’ activity â†’ M3 final

Covers: identity, late events, cancellation, migration, dedup,
conversation switching, Task Bar isolation, and provider compatibility.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.orchestrator import (
    ChatOrchestrator,
    _ExecutionState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> MaryDatabase:
    """Create a test database at tmp_path."""
    db = MaryDatabase(tmp_path / "test.db")
    return db


def _create_conversation(db: MaryDatabase, cid: str = "conv-1", workspace: Path | None = None) -> str:
    with db.connect() as conn:
        now = "2026-09-06T00:00:00Z"
        conn.execute(
            """INSERT INTO conversations
               (id, title, provider, model, effort, service_tier, approval_profile,
                collaboration_mode, vr_enabled, vr_mode, workspace, cloned_from, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, "Test", "codex", "test-model", "medium", "", "auto", "default", 0, "off", str(workspace or "."), "", now, now),
        )
    return cid


# ---------------------------------------------------------------------------
# 1. _ExecutionState unit tests
# ---------------------------------------------------------------------------

class TestExecutionState:
    """Validate per-turn message tracking in _ExecutionState."""

    def test_single_message_lifecycle(self) -> None:
        state = _ExecutionState(execution_id=42)
        assert state.message_seq == 0
        assert state.current_message_key == ""

        key = state.start_message()
        assert key == "42:1"
        assert state.current_message_key == key
        assert state.message_seq == 1

        state.append_delta("Hello ")
        state.append_delta("world")
        assert state.current_text() == "Hello world"

        k, text, ordinal = state.complete_message()
        assert k == key
        assert text == "Hello world"
        assert ordinal == 1

    def test_multiple_messages(self) -> None:
        state = _ExecutionState(execution_id=10)
        k1 = state.start_message()
        state.append_delta("First")
        k1_result, t1, o1 = state.complete_message()
        state.completed_messages.append((k1_result, t1, o1, ""))
        assert k1_result == "10:1"

        k2 = state.start_message()
        state.append_delta("Second")
        k2_result, t2, o2 = state.complete_message()
        state.completed_messages.append((k2_result, t2, o2, ""))
        assert k2_result == "10:2"
        assert t2 == "Second"
        assert state.has_completed_messages
        assert len(state.completed_messages) == 2

    def test_auto_start_on_delta(self) -> None:
        state = _ExecutionState(execution_id=7)
        assert state.current_message_key == ""
        state.append_delta("implicit")
        assert state.current_message_key == "7:1"
        assert state.current_text() == "implicit"

    def test_complete_with_authoritative_text(self) -> None:
        state = _ExecutionState(execution_id=5)
        state.start_message()
        state.append_delta("partial delta")
        k, text, o = state.complete_message(final_text="  authoritative  ")
        assert text == "authoritative"

    def test_all_accumulated_text(self) -> None:
        state = _ExecutionState(execution_id=1)
        state.start_message()
        state.append_delta("M1")
        k, t, o = state.complete_message()
        state.completed_messages.append((k, t, o, ""))

        state.start_message()
        state.append_delta("M2")
        assert state.all_accumulated_text() == "M1M2"

    def test_complete_no_active_message(self) -> None:
        state = _ExecutionState(execution_id=1)
        k, t, o = state.complete_message()
        assert k == ""
        assert t == ""


# ---------------------------------------------------------------------------
# 2. Database migration and upsert tests
# ---------------------------------------------------------------------------

class TestDatabaseIntermediateMessages:

    def test_add_message_with_new_columns(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        cid = _create_conversation(db, "conv-db-1")
        msg_id = db.add_message(
            cid, "assistant", "Hello",
            execution_ordinal=1,
            message_status="completed",
            provider_message_id="item-abc",
        )
        assert msg_id > 0
        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 1
        assert assistant_rows[0]["execution_ordinal"] == 1
        assert assistant_rows[0]["message_status"] == "completed"
        assert assistant_rows[0]["provider_message_id"] == "item-abc"

    def test_upsert_inserts_then_updates(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        cid = _create_conversation(db, "conv-db-2")
        id1 = db.upsert_assistant_message(
            cid, "Draft",
            execution_ordinal=1,
            message_status="streaming",
        )
        assert id1 > 0
        id2 = db.upsert_assistant_message(
            cid, "Final text",
            execution_ordinal=1,
            message_status="completed",
        )
        assert id2 == id1
        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 1
        assert assistant_rows[0]["content"] == "Final text"
        assert assistant_rows[0]["message_status"] == "completed"

    def test_upsert_different_ordinals(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        cid = _create_conversation(db, "conv-db-3")
        db.upsert_assistant_message(cid, "M1", execution_ordinal=1)
        db.upsert_assistant_message(cid, "M2", execution_ordinal=2)
        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 2
        assert assistant_rows[0]["content"] == "M1"
        assert assistant_rows[1]["content"] == "M2"

    def test_add_message_backward_compat(self, tmp_path: Path) -> None:
        """Old-style add_message without new params still works."""
        db = _make_db(tmp_path)
        cid = _create_conversation(db, "conv-db-4")
        msg_id = db.add_message(cid, "assistant", "Legacy message")
        assert msg_id > 0
        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert assistant_rows[0]["execution_ordinal"] == 0
        assert assistant_rows[0]["message_status"] == ""


# ---------------------------------------------------------------------------
# 3. Codex provider lifecycle event mapping
# ---------------------------------------------------------------------------

class TestCodexAgentMessageEvents:
    """Verify that agentMessage items emit assistant_started/completed."""

    def test_agent_message_started(self) -> None:
        from vrsoft_extractor.mary.providers import CodexProvider
        events: list[RuntimeEvent] = []

        provider = CodexProvider.__new__(CodexProvider)
        provider._state_lock = threading.Lock()
        provider._native_to_local = {"thread-1": "conv-1"}
        provider._callbacks = {"conv-1": lambda ev: events.append(ev)}
        provider._active_turns = {"conv-1": "turn-1"}
        provider._completed_turn_ids = {}
        provider._item_turn_ids = {}
        provider._assistant_item_keys = {}
        provider._assistant_item_phases = {}

        provider._handle_server_message({
            "method": "item/started",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {
                    "id": "item-1",
                    "type": "agentMessage",
                    "phase": "",
                },
            },
        })
        assert len(events) == 1
        assert events[0].kind == "assistant_started"
        assert events[0].payload["itemId"] == "item-1"

    def test_agent_message_completed_with_text(self) -> None:
        from vrsoft_extractor.mary.providers import CodexProvider
        events: list[RuntimeEvent] = []

        provider = CodexProvider.__new__(CodexProvider)
        provider._state_lock = threading.Lock()
        provider._native_to_local = {"thread-1": "conv-1"}
        provider._callbacks = {"conv-1": lambda ev: events.append(ev)}
        provider._active_turns = {"conv-1": "turn-1"}
        provider._completed_turn_ids = {}
        provider._item_turn_ids = {("thread-1", "item-1"): "turn-1"}
        provider._assistant_item_keys = {}
        provider._assistant_item_phases = {}

        provider._handle_server_message({
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {
                    "id": "item-1",
                    "type": "agentMessage",
                    "content": [{"type": "text", "text": "Hello world"}],
                },
            },
        })
        assert len(events) == 1
        assert events[0].kind == "assistant_completed"
        assert events[0].payload["final_text"] == "Hello world"

    def test_non_agent_message_stays_tool_event(self) -> None:
        from vrsoft_extractor.mary.providers import CodexProvider
        events: list[RuntimeEvent] = []

        provider = CodexProvider.__new__(CodexProvider)
        provider._state_lock = threading.Lock()
        provider._native_to_local = {"thread-1": "conv-1"}
        provider._callbacks = {"conv-1": lambda ev: events.append(ev)}
        provider._active_turns = {"conv-1": "turn-1"}
        provider._completed_turn_ids = {}
        provider._item_turn_ids = {("thread-1", "item-2"): "turn-1"}
        provider._assistant_item_keys = {}
        provider._assistant_item_phases = {}

        provider._handle_server_message({
            "method": "item/started",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {
                    "id": "item-2",
                    "type": "commandExecution",
                },
            },
        })
        assert len(events) == 1
        assert events[0].kind == "tool_event"


# ---------------------------------------------------------------------------
# 4. Orchestrator lifecycle integration
# ---------------------------------------------------------------------------

class TestOrchestratorMultiMessage:
    """Integration tests for multi-message handling in the orchestrator."""

    def _make_orchestrator(self, tmp_path: Path) -> tuple[ChatOrchestrator, MaryDatabase]:
        db = _make_db(tmp_path)
        settings = MagicMock()
        settings.root = tmp_path
        settings.endoo_wiki_enabled = False
        with patch.object(ChatOrchestrator, "__init__", lambda self, *a, **kw: None):
            orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch.settings = settings
        orch.database = db
        orch._assistant_buffers = {}
        orch._execution_states = {}
        orch._external_callbacks = {}
        orch._callback_generations = {}
        orch._pending_user_messages = {}
        orch._pending_response_modes = {}
        orch._pending_evidence_bundles = {}
        orch._pending_used_evidence_ids = {}
        orch._pending_response_contracts = {}
        orch._cancelled_conversations = set()
        orch._active_orchestration_runs = {}
        orch._terminal_turn_states = {}
        orch._finalized_turns = set()
        orch._agent_run_lock = threading.RLock()
        orch._dynamic_tool_callbacks = {}
        return orch, db

    def test_assistant_started_creates_execution_state_message(self, tmp_path: Path) -> None:
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-orch-1")

        orch._execution_states[cid] = _ExecutionState(execution_id=100)
        orch._pending_response_modes[cid] = "native"

        events: list[RuntimeEvent] = []
        orch._external_callbacks[cid] = lambda ev: events.append(ev)

        orch._handle_event(RuntimeEvent(
            cid, "assistant_started", payload={"itemId": "item-1"}
        ))

        state = orch._execution_states[cid]
        assert state.current_message_key == "100:1"
        assert state.message_seq == 1

    def test_assistant_completed_persists_message(self, tmp_path: Path) -> None:
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-orch-2")

        orch._execution_states[cid] = _ExecutionState(execution_id=200)
        orch._pending_response_modes[cid] = "native"
        orch._assistant_buffers[cid] = []

        orch._handle_event(RuntimeEvent(cid, "assistant_started", payload={"itemId": "x"}))
        orch._handle_event(RuntimeEvent(cid, "assistant_delta", "Hello "))
        orch._handle_event(RuntimeEvent(cid, "assistant_delta", "world"))
        orch._handle_event(RuntimeEvent(
            cid, "assistant_completed",
            payload={"itemId": "x", "final_text": "Hello world"},
        ))

        state = orch._execution_states[cid]
        assert state.has_completed_messages
        assert len(state.completed_messages) == 1
        assert state.completed_messages[0][1] == "Hello world"

        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 1
        assert assistant_rows[0]["content"] == "Hello world"
        assert assistant_rows[0]["message_status"] == "completed"

    def test_implicit_start_on_delta_without_assistant_started(self, tmp_path: Path) -> None:
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-orch-3")

        orch._execution_states[cid] = _ExecutionState(execution_id=300)
        orch._pending_response_modes[cid] = "native"
        orch._assistant_buffers[cid] = []

        events: list[RuntimeEvent] = []
        orch._external_callbacks[cid] = lambda ev: events.append(ev)

        orch._handle_event(RuntimeEvent(cid, "assistant_delta", "Hello"))

        state = orch._execution_states[cid]
        assert state.current_message_key == "300:1"
        assert state.current_text() == "Hello"

        started_events = [e for e in events if e.kind == "assistant_started"]
        assert len(started_events) == 1
        assert started_events[0].payload.get("implicit") is True

    def test_three_messages_per_turn(self, tmp_path: Path) -> None:
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-orch-4")

        orch._execution_states[cid] = _ExecutionState(execution_id=400)
        orch._pending_response_modes[cid] = "native"
        orch._assistant_buffers[cid] = []

        for i, label in enumerate(["First", "Second", "Third"], 1):
            orch._handle_event(RuntimeEvent(cid, "assistant_started", payload={"itemId": f"m{i}"}))
            orch._handle_event(RuntimeEvent(cid, "assistant_delta", f"{label} message"))
            orch._handle_event(RuntimeEvent(cid, "assistant_completed", payload={"itemId": f"m{i}", "final_text": f"{label} message"}))

        state = orch._execution_states[cid]
        assert len(state.completed_messages) == 3

        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 3
        assert [r["content"] for r in assistant_rows] == [
            "First message", "Second message", "Third message"
        ]
        ordinals = [r["execution_ordinal"] for r in assistant_rows]
        assert ordinals == sorted(ordinals)
        assert len(set(ordinals)) == 3

    def test_late_events_from_old_turn_blocked(self, tmp_path: Path) -> None:
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-orch-5")

        orch._finalized_turns.add(cid)

        orch._handle_event(RuntimeEvent(cid, "assistant_started", payload={}))
        orch._handle_event(RuntimeEvent(cid, "assistant_delta", "late"))
        orch._handle_event(RuntimeEvent(cid, "assistant_completed", payload={}))

        rows = db.messages(cid)
        assert len([r for r in rows if r["role"] == "assistant"]) == 0

    def test_turn_completed_with_intermediate_no_aggregate(self, tmp_path: Path) -> None:
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-orch-6")

        exec_state = _ExecutionState(execution_id=600)
        exec_state.completed_messages.append(("600:1", "First", 1, ""))
        exec_state.completed_messages.append(("600:2", "Second", 2, ""))

        db.upsert_assistant_message(cid, "First", execution_ordinal=1, message_status="completed")
        db.upsert_assistant_message(cid, "Second", execution_ordinal=2, message_status="completed")

        orch._pending_response_modes[cid] = "native"
        orch._external_callbacks[cid] = lambda ev: None
        orch._callback_generations[cid] = 1

        orch._finalize_turn_completed(
            RuntimeEvent(cid, "turn_completed"),
            "FirstSecond",
            False, "", "", exec_state,
        )

        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 2

    def test_legacy_single_message_path(self, tmp_path: Path) -> None:
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-orch-7")

        orch._pending_response_modes[cid] = "native"
        orch._external_callbacks[cid] = lambda ev: None
        orch._callback_generations[cid] = 1

        orch._finalize_turn_completed(
            RuntimeEvent(cid, "turn_completed"),
            "Single response",
            False, "", "", None,
        )

        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 1
        assert assistant_rows[0]["content"] == "Single response"

    def test_dedup_by_ordinal(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        cid = _create_conversation(db, "conv-dedup")

        db.upsert_assistant_message(cid, "Hello", execution_ordinal=1, message_status="completed")
        db.upsert_assistant_message(cid, "Hello updated", execution_ordinal=1, message_status="completed")

        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 1
        assert assistant_rows[0]["content"] == "Hello updated"


# ---------------------------------------------------------------------------
# 5. Cancellation, Error, and Isolation
# ---------------------------------------------------------------------------

class TestCancellationAndError:
    """Validate cancellation, errors, and cross-execution isolation."""

    def _make_orchestrator(self, tmp_path: Path) -> tuple[ChatOrchestrator, MaryDatabase]:
        db = _make_db(tmp_path)
        settings = MagicMock()
        settings.root = tmp_path
        settings.endoo_wiki_enabled = False
        with patch.object(ChatOrchestrator, "__init__", lambda self, *a, **kw: None):
            orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch.settings = settings
        orch.database = db
        orch._assistant_buffers = {}
        orch._execution_states = {}
        orch._external_callbacks = {}
        orch._callback_generations = {}
        orch._pending_user_messages = {}
        orch._pending_response_modes = {}
        orch._pending_evidence_bundles = {}
        orch._pending_used_evidence_ids = {}
        orch._pending_response_contracts = {}
        orch._cancelled_conversations = set()
        orch._active_orchestration_runs = {}
        orch._terminal_turn_states = {}
        orch._finalized_turns = set()
        orch._agent_run_lock = threading.RLock()
        orch._dynamic_tool_callbacks = {}
        return orch, db

    def test_error_after_m1_preserves_m1(self, tmp_path: Path) -> None:
        """M1 completes and persists. Error arrives after M1. M1 remains in DB."""
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-err-1")

        orch._execution_states[cid] = _ExecutionState(execution_id=101)
        orch._pending_response_modes[cid] = "native"
        orch._assistant_buffers[cid] = []

        # M1 succeeds
        orch._handle_event(RuntimeEvent(cid, "assistant_started", payload={"itemId": "m1"}))
        orch._handle_event(RuntimeEvent(cid, "assistant_delta", "Step 1 complete"))
        orch._handle_event(RuntimeEvent(cid, "assistant_completed", payload={"itemId": "m1", "final_text": "Step 1 complete"}))

        # Error occurs before M2
        orch._handle_event(RuntimeEvent(cid, "error", "Process crashed"))

        # DB has M1 preserved
        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) == 1
        assert assistant_rows[0]["content"] == "Step 1 complete"

        # Conversation status is error
        conv = db.get_conversation(cid)
        assert conv["status"] == "error"

    def test_cancellation_preserves_prior_completed(self, tmp_path: Path) -> None:
        """M1 completes. User cancels during M2. M1 is preserved in DB."""
        orch, db = self._make_orchestrator(tmp_path)
        cid = _create_conversation(db, "conv-cancel-1")

        orch._execution_states[cid] = _ExecutionState(execution_id=102)
        orch._pending_response_modes[cid] = "native"
        orch._assistant_buffers[cid] = []

        # M1 completes
        orch._handle_event(RuntimeEvent(cid, "assistant_started", payload={"itemId": "m1"}))
        orch._handle_event(RuntimeEvent(cid, "assistant_completed", payload={"itemId": "m1", "final_text": "M1 text"}))

        # M2 starts streaming
        orch._handle_event(RuntimeEvent(cid, "assistant_started", payload={"itemId": "m2"}))
        orch._handle_event(RuntimeEvent(cid, "assistant_delta", "M2 partial"))

        # Cancelled
        orch._handle_event(RuntimeEvent(cid, "orchestration_cancelled"))

        conv = db.get_conversation(cid)
        assert conv["status"] == "cancelled"

        rows = db.messages(cid)
        assistant_rows = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant_rows) >= 1
        assert assistant_rows[0]["content"] == "M1 text"

    def test_cross_conversation_isolation(self, tmp_path: Path) -> None:
        """Late events from conv A do not leak into conv B."""
        orch, db = self._make_orchestrator(tmp_path)
        cid_a = _create_conversation(db, "conv-a")
        cid_b = _create_conversation(db, "conv-b")

        orch._finalized_turns.add(cid_a)

        orch._execution_states[cid_b] = _ExecutionState(execution_id=202)
        orch._pending_response_modes[cid_b] = "native"
        orch._assistant_buffers[cid_b] = []

        # Late delta for A
        orch._handle_event(RuntimeEvent(cid_a, "assistant_delta", "late for A"))

        # B receives delta
        orch._handle_event(RuntimeEvent(cid_b, "assistant_started", payload={"itemId": "b1"}))
        orch._handle_event(RuntimeEvent(cid_b, "assistant_delta", "B text"))
        orch._handle_event(RuntimeEvent(cid_b, "assistant_completed", payload={"itemId": "b1", "final_text": "B text"}))

        # Verify B has only its own text
        rows_b = db.messages(cid_b)
        asst_b = [r for r in rows_b if r["role"] == "assistant"]
        assert len(asst_b) == 1
        assert asst_b[0]["content"] == "B text"

        # Verify A received no messages
        rows_a = db.messages(cid_a)
        assert len([r for r in rows_a if r["role"] == "assistant"]) == 0


# ---------------------------------------------------------------------------
# 6. Database Migration Idempotence
# ---------------------------------------------------------------------------

class TestDatabaseMigrationIdempotence:

    def test_legacy_database_migration(self, tmp_path: Path) -> None:
        """Create a DB with legacy schema missing execution_ordinal and message_status,
        then verify MaryDatabase migrates it cleanly and idempotently."""
        import sqlite3
        db_path = tmp_path / "legacy.db"

        # Manually create legacy messages table without new columns
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    effort TEXT NOT NULL DEFAULT 'medium',
                    service_tier TEXT NOT NULL DEFAULT '',
                    approval_profile TEXT NOT NULL DEFAULT 'auto',
                    collaboration_mode TEXT NOT NULL DEFAULT 'default',
                    vr_enabled INTEGER NOT NULL DEFAULT 0,
                    vr_mode TEXT NOT NULL DEFAULT 'off',
                    workspace TEXT NOT NULL,
                    cloned_from TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider_message_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    edited_from_message_id INTEGER,
                    response_mode TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)
            # Insert a pre-existing message
            conn.execute("""
                INSERT INTO messages (conversation_id, role, content, created_at)
                VALUES ('c1', 'user', 'Hello old world', '2026-09-01T00:00:00Z')
            """)

        # First migration pass
        db1 = MaryDatabase(db_path)
        rows = db1.messages("c1")
        assert len(rows) == 1
        assert rows[0]["content"] == "Hello old world"
        assert rows[0]["execution_ordinal"] == 0
        assert rows[0]["message_status"] == ""

        # Second migration pass (idempotence)
        db2 = MaryDatabase(db_path)
        new_id = db2.upsert_assistant_message("c1", "New assistant", execution_ordinal=1, message_status="completed")
        assert new_id > 0
        rows2 = db2.messages("c1")
        assert len(rows2) == 2


# ---------------------------------------------------------------------------
# 7. Provider Fallback Fixtures
# ---------------------------------------------------------------------------

class TestProviderFallbacks:
    """Validate that providers without explicit assistant_started work seamlessly."""

    def test_implicit_start_and_single_turn_completion(self, tmp_path: Path) -> None:
        """Providers like Claude/OpenCode/Antigravity that stream deltas without
        item/started are normalized into a single coherent message."""
        db = _make_db(tmp_path)
        cid = _create_conversation(db, "conv-fallback")

        state = _ExecutionState(execution_id=555)
        # Delta arrives with no explicit assistant_started
        state.append_delta("Delta 1. ")
        state.append_delta("Delta 2.")

        assert state.current_message_key == "555:1"
        assert state.current_text() == "Delta 1. Delta 2."

        k, final_text, ordinal = state.complete_message()
        assert final_text == "Delta 1. Delta 2."
        assert ordinal == 1

        db.upsert_assistant_message(cid, final_text, execution_ordinal=ordinal, message_status="completed")
        rows = db.messages(cid)
        asst = [r for r in rows if r["role"] == "assistant"]
        assert len(asst) == 1
        assert asst[0]["content"] == "Delta 1. Delta 2."


# ---------------------------------------------------------------------------
# 8. MessageListModel and Timeline Interleaving
# ---------------------------------------------------------------------------

class TestMessageListModelMultiMessage:
    """Validate MessageListModel update_by_key and multi-message representation."""

    def test_update_by_key_updates_correct_message(self) -> None:
        from vrsoft_extractor.mary.frontend.chat import MessageListModel
        model = MessageListModel()

        model.append({
            "messageId": 1,
            "role": "user",
            "content": "Do task",
            "displayContent": "Do task",
            "segments": [],
            "createdAt": "",
            "responseMode": "vr",
            "messageKey": "",
            "isStreaming": False,
        })
        model.append({
            "messageId": -1,
            "role": "assistant",
            "content": "M1 partial",
            "displayContent": "M1 partial",
            "segments": [],
            "createdAt": "",
            "responseMode": "vr",
            "messageKey": "10:1",
            "isStreaming": True,
        })
        model.append({
            "messageId": -2,
            "role": "activity",
            "content": "",
            "displayContent": "",
            "segments": [],
            "createdAt": "",
            "responseMode": "activity",
            "messageKey": "",
            "isStreaming": False,
        })
        model.append({
            "messageId": -1,
            "role": "assistant",
            "content": "M2 partial",
            "displayContent": "M2 partial",
            "segments": [],
            "createdAt": "",
            "responseMode": "vr",
            "messageKey": "10:2",
            "isStreaming": True,
        })

        assert model.rowCount() == 4

        # Update M1 by key
        success = model.update_by_key(
            "messageKey", "10:1",
            content="M1 finished",
            displayContent="M1 finished",
            isStreaming=False,
        )
        assert success is True

        # Verify M1 was updated and M2 was untouched
        assert model._items[1]["content"] == "M1 finished"
        assert model._items[1]["isStreaming"] is False
        assert model._items[3]["content"] == "M2 partial"
        assert model._items[3]["isStreaming"] is True

        # Update M2 by key
        success_m2 = model.update_by_key(
            "messageKey", "10:2",
            content="M2 finished",
            displayContent="M2 finished",
            isStreaming=False,
        )
        assert success_m2 is True
        assert model._items[3]["content"] == "M2 finished"
        assert model._items[3]["isStreaming"] is False

    def test_update_by_key_returns_false_for_missing_key(self) -> None:
        from vrsoft_extractor.mary.frontend.chat import MessageListModel
        model = MessageListModel()
        model.append({"messageKey": "existing", "content": "text"})
        assert model.update_by_key("messageKey", "nonexistent", content="other") is False

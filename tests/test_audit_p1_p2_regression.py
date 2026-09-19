from dataclasses import asdict
from vrsoft_extractor.mary.provider_adapters.tool_normalizer import (
    normalize_codex_event,
    normalize_antigravity_event,
    normalize_opencode_event,
    normalize_claude_event,
    normalize_generic_event,
)

"""Mandatory regression tests for audit 13731f0 follow-up (P1/P2).

Covers:
- P1 draft identity: repeated content failure before persistence restores current attempt.
- P1 menu target: pin/archive act on conversationMenuConversationId, not selection.
- P1 reducer authority: unfinished tool -> interrupted (never completed); live == reload.
- P2 explicit delta vs snapshot semantics.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.tool_activity import (
    NormalizedToolEvent,
    ToolEventKind,
    ToolLifecycleReducer,
    ToolStatus,
    coalesce_output,
)


def _settings(root: Path) -> MarySettings:
    return MarySettings(
        app_dir=root,
        root=root / "VRProject",
        old_root=root / "legacy-source",
    )


def _database(settings: MarySettings) -> MaryDatabase:
    return MaryDatabase(
        settings.database_path,
        root=settings.root,
        backup_portable_migration=False,
    )


class AuditRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._settings = _settings(root)
        self._database = _database(self._settings)
        self._preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
        self._bridge = ChatBridge(self._settings, self._database, self._preferences)
        self.addCleanup(self._bridge.close)

    # P1: repeated content must not cause false persisted=True
    def test_p1_repeated_content_failure_before_persist_restores_current_attempt(self):
        chat1 = self._database.create_conversation("Chat", "codex", "modelo", self._settings.root)
        # Pre-existing history with same content
        self._database.begin_user_turn(chat1, "teste")
        self._database.update_conversation(chat1, status="idle")
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)

        before_count = len(self._database.messages(chat1))
        self.assertTrue(before_count >= 1)

        restored = []
        self._bridge.draftRestored.connect(restored.append)
        with patch.object(
            self._bridge._orchestrator, "send",
            side_effect=RuntimeError("fail before begin_user_turn"),
        ):
            self._bridge._send_message("teste")

        after = self._database.messages(chat1)
        # No NEW user message persisted
        self.assertEqual(len(after), before_count)
        # Draft restored with current attempt
        self.assertIn(chat1, self._bridge._draft_records)
        self.assertEqual(self._bridge._draft_records[chat1]["text"], "teste")
        self.assertIn("teste", restored)

    def test_p2_snapshot_reflects_current_attempt_not_stale_draft(self):
        chat1 = self._database.create_conversation("Chat", "codex", "modelo", self._settings.root)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)
        # Stale saved draft
        self.assertTrue(self._bridge.saveCurrentDraft("texto antigo"))
        self.assertEqual(self._bridge._draft_records[chat1]["text"], "texto antigo")
        with patch.object(
            self._bridge._orchestrator, "send",
            side_effect=RuntimeError("fail before persist"),
        ):
            self._bridge._send_message("texto novo")
        self.assertEqual(self._bridge._draft_records[chat1]["text"], "texto novo")

    # P1: menu target isolation
    def test_p1_pin_acts_on_menu_target_not_selection(self):
        c1 = self._database.create_conversation("Chat 1", "codex", "modelo", self._settings.root)
        c2 = self._database.create_conversation("Chat 2", "codex", "modelo", self._settings.root)
        self._bridge.refresh()
        self._bridge.selectConversationId(c1)
        self._bridge.togglePinnedConversation(c2)
        self.assertIn(c2, self._bridge._pinned_conversation_ids)
        self.assertNotIn(c1, self._bridge._pinned_conversation_ids)
        self.assertEqual(self._bridge._selected_conversation_id(), c1)

    def test_p1_archive_acts_on_menu_target_while_other_runs(self):
        c1 = self._database.create_conversation("Chat 1", "codex", "modelo", self._settings.root)
        c2 = self._database.create_conversation("Chat 2", "codex", "modelo", self._settings.root)
        self._database.update_conversation(c1, status="running")
        self._bridge._active_turns.add(c1)
        self._bridge.refresh()
        self._bridge.selectConversationId(c1)
        self._bridge.archiveConversation(c2)
        row2 = self._database.get_conversation(c2)
        self.assertEqual(int(row2["archived"]), 1)
        # Chat 1 untouched
        self.assertEqual(str(self._database.get_conversation(c1)["status"]), "running")
        self.assertIn(c1, self._bridge._active_turns)
        self.assertEqual(self._bridge._selected_conversation_id(), c1)

    def test_p1_qml_menu_uses_explicit_target_for_all_actions(self):
        qml = (
            Path(__file__).resolve().parent.parent
            / "vrsoft_extractor" / "mary" / "frontend" / "qml"
            / "pages" / "ChatPreview.qml"
        ).read_text(encoding="utf-8")
        self.assertIn("togglePinnedConversation(targetId)", qml)
        self.assertIn("archiveConversation(targetId)", qml)
        self.assertIn("trashConversation(targetId)", qml)
        self.assertIn("conversationMenuConversationId", qml)

    # P1: reducer authority live (preserve in-memory cards across terminal reload)
    def _run_live_turn(self, chat_id, tool_events, terminal_kind="turn_completed", execution_id=7):
        self._database.update_conversation(chat_id, status="running")
        self._bridge._active_turns.add(chat_id)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat_id)
        # Preserve live re-rendered cards: stub timeline reload (DB has no
        # runtime_events in this unit path; real runs persist them and reload
        # rebuilds identical states via _timeline_reducers).
        orig_reload = self._bridge._reload_execution_timeline
        self._bridge._reload_execution_timeline = lambda cid, rows: True  # type: ignore
        try:
            for ev in tool_events:
                payload = dict(ev)
                payload.setdefault("execution_id", execution_id)
                self._bridge._on_runtime_event(RuntimeEvent(chat_id, "tool_event", "", payload))
                self.application.processEvents()
            self._bridge._on_runtime_event(
                RuntimeEvent(chat_id, terminal_kind, "", {"execution_id": execution_id})
            )
            self.application.processEvents()
        finally:
            self._bridge._reload_execution_timeline = orig_reload  # type: ignore
        msg = next((m for m in self._bridge._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(msg)
        return {t["id"]: t for t in msg.get("activityData", [])}

    def test_p1_unfinished_tool_becomes_interrupted_not_completed(self):
        chat1 = self._database.create_conversation("T", "codex", "modelo", self._settings.root)
        cards = self._run_live_turn(chat1, [
            {"toolCallId": "t1", "step_type": "commandExecution", "status": "running", "event_id": "e1"},
        ])
        self.assertEqual(cards["t1"]["state"], "interrupted")
        self.assertNotEqual(cards["t1"]["state"], "completed")
        # Reducer popped after terminal
        self.assertNotIn((chat1, 7), getattr(self._bridge, "_tool_reducers", {}))

    def test_p1_completed_tool_stays_completed(self):
        chat1 = self._database.create_conversation("T", "codex", "modelo", self._settings.root)
        cards = self._run_live_turn(chat1, [
            {"toolCallId": "t1", "step_type": "commandExecution", "status": "running", "event_id": "e1"},
            {"toolCallId": "t1", "step_type": "commandExecution", "status": "success", "output": "ok", "event_id": "e2"},
        ])
        self.assertEqual(cards["t1"]["state"], "completed")

    def test_p1_failed_tool_stays_error(self):
        chat1 = self._database.create_conversation("T", "codex", "modelo", self._settings.root)
        cards = self._run_live_turn(chat1, [
            {"toolCallId": "t1", "step_type": "commandExecution", "status": "running", "event_id": "e1"},
            {"toolCallId": "t1", "step_type": "commandExecution", "status": "error", "error": "boom", "event_id": "e2"},
        ])
        self.assertEqual(cards["t1"]["state"], "error")

    # P2: explicit output semantics
    def test_p2_delta_repeats_append(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.STARTED))
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta"))
        tool = r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta"))
        self.assertEqual(tool.output, "AA")

    def test_p2_delta_retry_lines_append(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.STARTED))
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="retrying\n", output_mode="delta"))
        tool = r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="retrying\n", output_mode="delta"))
        self.assertEqual(tool.output, "retrying\nretrying\n")

    def test_p2_snapshot_coalesces(self):
        self.assertEqual(coalesce_output(None, new_output="A", output_mode="snapshot"), "A")
        out = coalesce_output("A", new_output="AB", output_mode="snapshot")
        out = coalesce_output(out, new_output="ABC", output_mode="snapshot")
        self.assertEqual(out, "ABC")
        self.assertEqual(coalesce_output("ABC", new_output="ABC", output_mode="snapshot"), "ABC")

    def test_p2_event_id_dedup_still_works_for_retries(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.STARTED))
        e = NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="x", output_mode="delta", event_id="evt-1")
        r.reduce(e)
        tool = r.reduce(e)
        self.assertEqual(tool.output, "x")

    def test_p1_reload_matches_live_for_three_scenarios(self):
        # Persist runtime_events so timeline reload rebuilds; live stubbed above
        # already verified interrupted/completed/error. Here verify reload path.

        def reload_state(tool_payloads, terminal="turn_completed"):
            cid = self._database.create_conversation("R", "codex", "modelo", self._settings.root)
            eid = 11
            for p in tool_payloads:
                payload = dict(p)
                payload.setdefault("execution_id", eid)
                self._database.add_event(RuntimeEvent(cid, "tool_event", "", payload))
            self._database.add_event(RuntimeEvent(cid, terminal, "", {"execution_id": eid}))
            # Minimal user message row so reload has a timeline anchor
            self._database.begin_user_turn(cid, "hi")
            rows = self._database.messages(cid)
            bridge2_prefs = QSettings(str(Path(self._tmp.name) / f"{cid}.ini"), QSettings.IniFormat)
            bridge2 = ChatBridge(self._settings, self._database, bridge2_prefs)
            self.addCleanup(bridge2.close)
            bridge2._selected = {"conversationId": cid}
            ok = bridge2._reload_execution_timeline(cid, rows)
            self.assertTrue(ok)
            cards = {}
            for m in bridge2._messages._items:
                for t in m.get("activityData", []):
                    cards[t["id"]] = t
            return cards

        c_unfinished = reload_state([{"toolCallId": "u1", "step_type": "commandExecution", "status": "running"}])
        self.assertEqual(c_unfinished["u1"]["state"], "interrupted")
        c_ok = reload_state([
            {"toolCallId": "o1", "step_type": "commandExecution", "status": "running"},
            {"toolCallId": "o1", "step_type": "commandExecution", "status": "success", "output": "ok"},
        ])
        self.assertEqual(c_ok["o1"]["state"], "completed")
        c_err = reload_state([
            {"toolCallId": "e1", "step_type": "commandExecution", "status": "running"},
            {"toolCallId": "e1", "step_type": "commandExecution", "status": "error", "error": "boom"},
        ])
        self.assertEqual(c_err["e1"]["state"], "error")



    def test_p1_roundtrip_all_providers_preserves_event_id_and_sequence(self):
        # 1. Codex
        codex_payload = {
            "item": {
                "id": "codex-item-1",
                "type": "commandExecution",
                "command": "git status",
                "status": "in_progress",
                "event_id": "codex-ev-100",
                "sequence": 15,
            }
        }
        codex_norm = normalize_codex_event(codex_payload, "item/started", "cid-rt")
        self.assertIsNotNone(codex_norm)
        self.assertEqual(codex_norm.event_id, "codex-ev-100")
        self.assertEqual(codex_norm.sequence, 15)
        rt_codex = RuntimeEvent("cid-rt", "tool_event", "", {"canonical_event": asdict(codex_norm)})
        gen_codex = normalize_generic_event(rt_codex)
        self.assertIsNotNone(gen_codex)
        self.assertEqual(gen_codex.event_id, "codex-ev-100")
        self.assertEqual(gen_codex.sequence, 15)
        r = ToolLifecycleReducer()
        t_codex = r.reduce(gen_codex)
        self.assertEqual(t_codex.id, "codex-item-1")
        self.assertEqual(t_codex.sequence, 15)

        # 2. Antigravity
        anti_payload = {
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {
                    "toolCallId": "anti-call-200",
                    "name": "read_file",
                    "title": "Lendo",
                    "eventId": "anti-ev-200",
                    "seq": 25,
                },
            }
        }
        anti_norm = normalize_antigravity_event(anti_payload, "session/update", "cid-rt")
        self.assertIsNotNone(anti_norm)
        self.assertEqual(anti_norm.event_id, "anti-ev-200")
        self.assertEqual(anti_norm.sequence, 25)
        rt_anti = RuntimeEvent("cid-rt", "tool_event", "", {"canonical_event": asdict(anti_norm)})
        gen_anti = normalize_generic_event(rt_anti)
        self.assertIsNotNone(gen_anti)
        self.assertEqual(gen_anti.event_id, "anti-ev-200")
        self.assertEqual(gen_anti.sequence, 25)
        t_anti = r.reduce(gen_anti)
        self.assertEqual(t_anti.id, "anti-call-200")
        self.assertEqual(t_anti.sequence, 25)

        # 3. OpenCode
        # CORR-TC-SEQ-01: output_index is NOT a monotonic sequence.
        open_payload = {
            "part": {
                "type": "tool",
                "callID": "open-call-300",
                "tool": "terminal",
                "state": "running",
                "update_id": "open-ev-300",
                "output_index": 35,
            }
        }
        open_norm = normalize_opencode_event(open_payload, "cid-rt")
        self.assertIsNotNone(open_norm)
        self.assertEqual(open_norm.event_id, "open-ev-300")
        self.assertEqual(open_norm.sequence, 0)
        self.assertEqual(open_norm.metadata["part"]["output_index"], 35)
        rt_open = RuntimeEvent("cid-rt", "tool_event", "", {"canonical_event": asdict(open_norm)})
        gen_open = normalize_generic_event(rt_open)
        self.assertIsNotNone(gen_open)
        self.assertEqual(gen_open.event_id, "open-ev-300")
        self.assertEqual(gen_open.sequence, 0)
        t_open = r.reduce(gen_open)
        self.assertEqual(t_open.id, "open-call-300")
        self.assertEqual(t_open.sequence, 0)

        # 4. Claude
        # CORR-TC-SEQ-01: index is NOT a monotonic sequence.
        claude_payload = {
            "type": "tool_use",
            "id": "claude-call-400",
            "name": "edit",
            "updateId": "claude-ev-400",
            "index": 45,
        }
        claude_norm = normalize_claude_event(claude_payload, "cid-rt")
        self.assertIsNotNone(claude_norm)
        self.assertEqual(claude_norm.event_id, "claude-ev-400")
        self.assertEqual(claude_norm.sequence, 0)
        rt_claude = RuntimeEvent("cid-rt", "tool_event", "", {"canonical_event": asdict(claude_norm)})
        gen_claude = normalize_generic_event(rt_claude)
        self.assertIsNotNone(gen_claude)
        self.assertEqual(gen_claude.event_id, "claude-ev-400")
        self.assertEqual(gen_claude.sequence, 0)
        t_claude = r.reduce(gen_claude)
        self.assertEqual(t_claude.id, "claude-call-400")
        self.assertEqual(t_claude.sequence, 0)

    def test_p1_canonical_event_defense_never_overwrites_explicit_identity(self):
        raw_canonical = asdict(NormalizedToolEvent(tool_id="def-1", kind=ToolEventKind.STARTED))
        raw_canonical["event_id"] = "orig-id"
        raw_canonical["sequence"] = 12
        payload = {
            "canonical_event": raw_canonical,
            "event_id": "different-id",
            "sequence": 99,
        }
        ev = normalize_generic_event(RuntimeEvent("cid", "tool_event", "", payload))
        self.assertEqual(ev.event_id, "orig-id")
        self.assertEqual(ev.sequence, 12)

        # But if canonical event is missing event_id/sequence, enrich from outer payload
        raw_canonical_empty = asdict(NormalizedToolEvent(tool_id="def-2", kind=ToolEventKind.STARTED))
        raw_canonical_empty["event_id"] = ""
        raw_canonical_empty["sequence"] = 0
        payload_enrich = {
            "canonical_event": raw_canonical_empty,
            "event_id": "enriched-id",
            "sequence": 77,
        }
        ev_enrich = normalize_generic_event(RuntimeEvent("cid", "tool_event", "", payload_enrich))
        self.assertEqual(ev_enrich.event_id, "enriched-id")
        self.assertEqual(ev_enrich.sequence, 77)

    def test_p2_snapshot_divergent_and_out_of_order(self):
        # Identical snapshot maintains output
        self.assertEqual(coalesce_output("output A", new_output="output A", output_mode="snapshot"), "output A")
        # Progressive snapshot replaces
        self.assertEqual(coalesce_output("step 1", new_output="step 1\nstep 2", output_mode="snapshot"), "step 1\nstep 2")
        # Divergent / disjoint snapshot replaces without string concatenation
        self.assertEqual(coalesce_output("phase 1", new_output="final result", output_mode="snapshot"), "final result")
        # Stale sequence in snapshot mode is ignored
        self.assertEqual(
            coalesce_output("current buffer", new_output="stale buffer", output_mode="snapshot", sequence=1, current_sequence=2),
            "current buffer",
        )

        # Reducer integration: sequence order authoritative
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="s1", kind=ToolEventKind.STARTED, sequence=1))
        r.reduce(NormalizedToolEvent(tool_id="s1", kind=ToolEventKind.UPDATED, output="seq 2 result", output_mode="snapshot", sequence=2))
        # Out-of-order event with sequence 1 arrives late -> ignored
        tool = r.reduce(NormalizedToolEvent(tool_id="s1", kind=ToolEventKind.UPDATED, output="seq 1 result", output_mode="snapshot", sequence=1))
        self.assertEqual(tool.output, "seq 2 result")
        # Newer event sequence 3 replaces
        tool = r.reduce(NormalizedToolEvent(tool_id="s1", kind=ToolEventKind.UPDATED, output="seq 3 result", output_mode="snapshot", sequence=3))
        self.assertEqual(tool.output, "seq 3 result")

    def test_p2_delta_distinct_event_ids_append_vs_retry_dedup(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="d1", kind=ToolEventKind.STARTED))
        # Two legitimate distinct chunks with identical text but distinct event_id must accumulate
        r.reduce(NormalizedToolEvent(tool_id="d1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", event_id="chunk-1"))
        tool = r.reduce(NormalizedToolEvent(tool_id="d1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", event_id="chunk-2"))
        self.assertEqual(tool.output, "AA")

        # But a retry of chunk-2 with the exact same event_id must be ignored
        tool = r.reduce(NormalizedToolEvent(tool_id="d1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", event_id="chunk-2"))
        self.assertEqual(tool.output, "AA")

    def test_p2_context_menu_pin_labels_all_four_scenarios(self):
        chat1 = self._database.create_conversation("Chat 1", "codex", "modelo", self._settings.root)
        chat2 = self._database.create_conversation("Chat 2", "codex", "modelo", self._settings.root)
        self._bridge.refresh()

        # Scenario 1: Chat 1 selected & pinned; Chat 2 unpinned. Context menu opened on Chat 2.
        self._bridge.selectConversationId(chat1)
        self.assertEqual(self._bridge._selected_conversation_id(), chat1)
        self._bridge.togglePinnedConversation(chat1)
        self.assertTrue(self._bridge.isConversationPinned(chat1))
        self.assertFalse(self._bridge.isConversationPinned(chat2))
        # Menu for target chat2 must display "Fixar conversa", NOT "Desafixar conversa"
        self.assertEqual(self._bridge.conversationPinLabel(chat2), "Fixar conversa")
        self.assertEqual(self._bridge.conversationPinLabel(chat1), "Desafixar conversa")

        # Scenario 2: Chat 2 is pinned; Chat 1 is selected and unpinned. Context menu opened on Chat 2.
        self._bridge.togglePinnedConversation(chat1)  # unpin chat1
        self._bridge.togglePinnedConversation(chat2)  # pin chat2
        self.assertFalse(self._bridge.isConversationPinned(chat1))
        self.assertTrue(self._bridge.isConversationPinned(chat2))
        self._bridge.selectConversationId(chat1)
        self.assertEqual(self._bridge._selected_conversation_id(), chat1)
        # Target is chat2 (pinned), selection is chat1 (unpinned) -> menu on chat2 must display "Desafixar conversa"
        self.assertEqual(self._bridge.conversationPinLabel(chat2), "Desafixar conversa")
        self.assertEqual(self._bridge.conversationPinLabel(chat1), "Fixar conversa")

        # Scenario 3: Action executed from menu operates on target chat2, NOT on selected chat1
        self._bridge.togglePinnedConversation(chat2)
        # Chat 2 is now unpinned; Chat 1 remains unpinned and still selected
        self.assertFalse(self._bridge.isConversationPinned(chat2))
        self.assertFalse(self._bridge.isConversationPinned(chat1))
        self.assertEqual(self._bridge._selected_conversation_id(), chat1)

        # Scenario 4: Target pin label verification matches target pin state dynamically
        self.assertEqual(self._bridge.conversationPinLabel(chat2), "Fixar conversa")
        self._bridge.togglePinnedConversation(chat2)
        self.assertEqual(self._bridge.conversationPinLabel(chat2), "Desafixar conversa")

    def test_p3_timeline_reducers_cleanup_no_leaks(self):
        cid = self._database.create_conversation("Leak Test", "codex", "modelo", self._settings.root)
        eid = 42
        for i in range(3):
            self._database.add_event(RuntimeEvent(cid, "tool_event", "", {
                "execution_id": eid,
                "toolCallId": f"t-{i}",
                "step_type": "commandExecution",
                "status": "success",
                "output": f"ok-{i}",
            }))
        self._database.add_event(RuntimeEvent(cid, "turn_completed", "", {"execution_id": eid}))
        self._database.begin_user_turn(cid, "hello")
        rows = self._database.messages(cid)

        # Reload timeline multiple times
        for _ in range(5):
            ok = self._bridge._reload_execution_timeline(cid, rows)
            self.assertTrue(ok)
            # Reconstructed finished turn removes reducers without leak
            self.assertEqual(len(self._bridge._timeline_reducers), 0)

        # close() clears map
        self._bridge._timeline_reducers[(cid, 999)] = ToolLifecycleReducer()
        self.assertEqual(len(self._bridge._timeline_reducers), 1)
        self._bridge.close()
        self.assertEqual(len(self._bridge._timeline_reducers), 0)

    # Follow-up P1 Tests:

    def test_p1_sequence_idempotency_scenarios(self):
        """P1: sequence idempotency priority and monotonicity."""
        # 1. Retry with same sequence: delta "A", seq=10; retry delta "A", seq=10 -> "A"
        r1 = ToolLifecycleReducer()
        r1.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        r1.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", sequence=10, provider="codex"))
        tool1 = r1.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", sequence=10, provider="codex"))
        self.assertEqual(tool1.output, "A")

        # 2. Distinct event: delta "A", seq=10; delta "A", seq=11 -> "AA"
        r2 = ToolLifecycleReducer()
        r2.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        r2.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", sequence=10, provider="codex"))
        tool2 = r2.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", sequence=11, provider="codex"))
        self.assertEqual(tool2.output, "AA")

        # 3. Priority event_id: delta "A", event_id=x, seq=10; delta "A", event_id=x, seq=11 -> "A"
        r3 = ToolLifecycleReducer()
        r3.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        r3.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", event_id="ev-fixed", sequence=10, provider="codex"))
        tool3 = r3.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", event_id="ev-fixed", sequence=11, provider="codex"))
        self.assertEqual(tool3.output, "A")

    def test_p1_terminal_priority_error_cancel_vs_turn_completed(self):
        """P1: error -> turn_completed divergence: terminal priority error > cancelled > completed."""
        def reload_multiterminal(tool_payloads, terminals):
            cid = self._database.create_conversation("R", "codex", "modelo", self._settings.root)
            eid = 25
            for p in tool_payloads:
                payload = dict(p)
                payload.setdefault("execution_id", eid)
                self._database.add_event(RuntimeEvent(cid, "tool_event", "", payload))
            for term in terminals:
                self._database.add_event(RuntimeEvent(cid, term, "", {"execution_id": eid}))
            self._database.begin_user_turn(cid, "hi")
            rows = self._database.messages(cid)
            bridge2_prefs = QSettings(str(Path(self._tmp.name) / f"{cid}_term.ini"), QSettings.IniFormat)
            bridge2 = ChatBridge(self._settings, self._database, bridge2_prefs)
            self.addCleanup(bridge2.close)
            bridge2._selected = {"conversationId": cid}
            ok = bridge2._reload_execution_timeline(cid, rows)
            self.assertTrue(ok)
            cards = {}
            for m in bridge2._messages._items:
                for t in m.get("activityData", []):
                    cards[t["id"]] = t
            return cards

        # 1. Error followed by turn_completed -> live = failure, reload = failure
        chat_err = self._database.create_conversation("C1", "codex", "m", self._settings.root)
        self._run_live_turn(
            chat_err,
            [{"toolCallId": "t1", "step_type": "commandExecution", "status": "running"}],
            terminal_kind="error",
        )
        self._bridge._on_runtime_event(
            RuntimeEvent(chat_err, "turn_completed", "", {"execution_id": 7})
        )
        self.application.processEvents()
        msg = next((m for m in self._bridge._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(msg)
        live_cards = {t["id"]: t for t in msg.get("activityData", [])}
        self.assertEqual(live_cards["t1"]["state"], "error")

        reloaded_err = reload_multiterminal(
            [{"toolCallId": "t1", "step_type": "commandExecution", "status": "running"}],
            ["error", "turn_completed"],
        )
        self.assertEqual(reloaded_err["t1"]["state"], "error")

        # 2. Cancelled followed by turn_completed -> live = cancelled, reload = cancelled
        chat_cancel = self._database.create_conversation("C2", "codex", "m", self._settings.root)
        self._run_live_turn(
            chat_cancel,
            [{"toolCallId": "t2", "step_type": "commandExecution", "status": "running"}],
            terminal_kind="orchestration_cancelled",
        )
        self._bridge._on_runtime_event(
            RuntimeEvent(chat_cancel, "turn_completed", "", {"execution_id": 7})
        )
        self.application.processEvents()
        msg2 = next((m for m in self._bridge._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(msg2)
        live_cancel_cards = {t["id"]: t for t in msg2.get("activityData", [])}
        self.assertEqual(live_cancel_cards["t2"]["state"], "cancelled")

        reloaded_cancel = reload_multiterminal(
            [{"toolCallId": "t2", "step_type": "commandExecution", "status": "running"}],
            ["orchestration_cancelled", "turn_completed"],
        )
        self.assertEqual(reloaded_cancel["t2"]["state"], "cancelled")

        # 3. turn_completed simple -> live = interrupted, reload = interrupted
        chat_comp = self._database.create_conversation("C3", "codex", "m", self._settings.root)
        live_comp = self._run_live_turn(
            chat_comp,
            [{"toolCallId": "t3", "step_type": "commandExecution", "status": "running"}],
            terminal_kind="turn_completed",
        )
        self.assertEqual(live_comp["t3"]["state"], "interrupted")

        reloaded_comp = reload_multiterminal(
            [{"toolCallId": "t3", "step_type": "commandExecution", "status": "running"}],
            ["turn_completed"],
        )
        self.assertEqual(reloaded_comp["t3"]["state"], "interrupted")

    def test_p1_background_tool_progression_no_regression(self):
        """P1: tool output maintains progression and avoids regression during tab switching."""
        cid1 = self._database.create_conversation("Chat1", "codex", "m1", self._settings.root)
        cid2 = self._database.create_conversation("Chat2", "codex", "m2", self._settings.root)
        self._database.begin_user_turn(cid1, "hello")
        self._bridge._active_turns.add(cid1)
        self._bridge.refresh()

        eid = 33

        # Step 1: Select Chat 1 and emit delta "A"
        self._bridge.selectConversationId(cid1)
        ev_start = {"toolCallId": "t1", "step_type": "commandExecution", "status": "running", "execution_id": eid}
        ev_a = {"toolCallId": "t1", "step_type": "commandExecution", "status": "running", "delta": "A", "output_mode": "delta", "execution_id": eid}
        self._bridge._on_runtime_event(RuntimeEvent(cid1, "tool_event", "", ev_start))
        self._bridge._on_runtime_event(RuntimeEvent(cid1, "tool_event", "", ev_a))
        self._database.add_event(RuntimeEvent(cid1, "tool_event", "", ev_start))
        self._database.add_event(RuntimeEvent(cid1, "tool_event", "", ev_a))
        self.application.processEvents()

        msg1 = next((m for m in self._bridge._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(msg1)
        cards1 = {t["id"]: t for t in msg1.get("activityData", [])}
        self.assertEqual(cards1["t1"]["output"], "A")

        # Step 2: Switch to Chat 2
        self._bridge.selectConversationId(cid2)
        self.application.processEvents()

        # Step 3: Emit background event delta "B" for Chat 1
        ev_b = {"toolCallId": "t1", "step_type": "commandExecution", "status": "running", "delta": "B", "output_mode": "delta", "execution_id": eid}
        self._bridge._on_runtime_event(RuntimeEvent(cid1, "tool_event", "", ev_b))
        self._database.add_event(RuntimeEvent(cid1, "tool_event", "", ev_b))
        self.application.processEvents()

        # Step 4: Switch back to Chat 1 -> verify UI reflects "AB"
        self._bridge.selectConversationId(cid1)
        self.application.processEvents()

        msg1 = next((m for m in self._bridge._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(msg1)
        cards1 = {t["id"]: t for t in msg1.get("activityData", [])}
        self.assertEqual(cards1["t1"]["output"], "AB")

        # Step 5: Emit delta "C" while Chat 1 is selected
        ev_c = {"toolCallId": "t1", "step_type": "commandExecution", "status": "running", "delta": "C", "output_mode": "delta", "execution_id": eid}
        self._bridge._on_runtime_event(RuntimeEvent(cid1, "tool_event", "", ev_c))
        self._database.add_event(RuntimeEvent(cid1, "tool_event", "", ev_c))
        self.application.processEvents()

        msg1 = next((m for m in self._bridge._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(msg1)
        cards1 = {t["id"]: t for t in msg1.get("activityData", [])}
        self.assertEqual(cards1["t1"]["output"], "ABC")

        # Verify live reducer output
        self.assertIn((cid1, eid), self._bridge._tool_reducers)
        live_tool = self._bridge._tool_reducers[(cid1, eid)].get_tool("t1")
        self.assertIsNotNone(live_tool)
        self.assertEqual(live_tool.output, "ABC")

        # Verify reload also produces "ABC"
        rows = self._database.messages(cid1)
        bridge_reload = ChatBridge(self._settings, self._database, QSettings(str(Path(self._tmp.name) / "test_reload.ini"), QSettings.IniFormat))
        self.addCleanup(bridge_reload.close)
        bridge_reload._selected = {"conversationId": cid1}
        bridge_reload._reload_execution_timeline(cid1, rows)
        msg_rel = next((m for m in bridge_reload._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(msg_rel)
        cards_rel = {t["id"]: t for t in msg_rel.get("activityData", [])}
        self.assertEqual(cards_rel["t1"]["output"], "ABC")

    # CORR-TC-SEQ-01: event_id has priority over sequence.
    def test_corr_tc_seq_01_new_event_id_same_sequence_is_processed(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", event_id="e1", sequence=10, provider="codex",
        ))
        tool = r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="B",
            output_mode="delta", event_id="e2", sequence=10, provider="codex",
        ))
        self.assertEqual(tool.output, "AB")

    def test_corr_tc_seq_01_same_event_id_different_sequence_is_retry(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", event_id="e1", sequence=10, provider="codex",
        ))
        tool = r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", event_id="e1", sequence=11, provider="codex",
        ))
        self.assertEqual(tool.output, "A")

    def test_corr_tc_seq_01_sequence_dedup_without_event_id(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", sequence=10, provider="codex",
        ))
        tool = r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", sequence=10, provider="codex",
        ))
        self.assertEqual(tool.output, "A")

    def test_corr_tc_seq_01_same_sequence_different_providers_independent(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", sequence=10, provider="codex",
        ))
        tool = r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="B",
            output_mode="delta", sequence=10, provider="antigravity",
        ))
        self.assertEqual(tool.output, "AB")

    def test_corr_tc_seq_01_index_output_index_never_become_sequence(self):
        ev_idx = normalize_opencode_event(
            {"part": {"type": "tool", "callID": "t-idx", "tool": "exec",
                      "index": 7, "delta": "A"}},
        )
        self.assertIsNotNone(ev_idx)
        self.assertEqual(ev_idx.sequence, 0)
        ev_oidx = normalize_antigravity_event(
            {"update": {"sessionUpdate": "tool_call",
                        "toolCall": {"toolCallId": "t-oidx", "output_index": 7,
                                     "delta": "B"}}},
            "session/update",
        )
        self.assertIsNotNone(ev_oidx)
        self.assertEqual(ev_oidx.sequence, 0)

        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t-idx", kind=ToolEventKind.STARTED, provider="opencode"))
        t1 = r.reduce(NormalizedToolEvent(
            tool_id="t-idx", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", provider="opencode",
            metadata={"index": 7},
        ))
        self.assertEqual(t1.output, "A")
        t2 = r.reduce(NormalizedToolEvent(
            tool_id="t-idx", kind=ToolEventKind.UPDATED, delta="B",
            output_mode="delta", provider="opencode",
            metadata={"output_index": 7},
        ))
        self.assertEqual(t2.output, "AB")

    def test_corr_tc_seq_01_started_completed_same_sequence_distinct_ids(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.STARTED,
            event_id="start-1", sequence=10, provider="codex",
        ))
        tool = r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.COMPLETED,
            event_id="done-1", sequence=10, provider="codex",
        ))
        self.assertEqual(tool.status, ToolStatus.SUCCESS)

    def test_corr_tc_seq_01_legacy_processed_sequences_ignored(self):
        r = ToolLifecycleReducer.from_dict({
            "tools": [],
            "processed_event_ids": [],
            "processed_digests": [],
            "processed_sequences": [["t1", 10]],
            "processed_provider_sequences": [],
        })
        r.reduce(NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, provider="codex"))
        tool = r.reduce(NormalizedToolEvent(
            tool_id="t1", kind=ToolEventKind.UPDATED, delta="A",
            output_mode="delta", event_id="e-new", sequence=10, provider="codex",
        ))
        self.assertEqual(tool.output, "A")

    # CORR-TC-TERM-02: first accepted terminal wins, live == reload.
    def _run_live_two_terminals(self, chat_id, tool_events, first_terminal,
                                second_terminal, execution_id=7):
        self._database.update_conversation(chat_id, status="running")
        self._bridge._active_turns.add(chat_id)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat_id)
        orig_reload = self._bridge._reload_execution_timeline
        self._bridge._reload_execution_timeline = lambda cid, rows: True  # type: ignore
        try:
            for ev in tool_events:
                payload = dict(ev)
                payload.setdefault("execution_id", execution_id)
                self._bridge._on_runtime_event(RuntimeEvent(chat_id, "tool_event", "", payload))
                self.application.processEvents()
            self._bridge._on_runtime_event(
                RuntimeEvent(chat_id, first_terminal, "", {"execution_id": execution_id})
            )
            self.application.processEvents()
            msg_first = next(
                (m for m in self._bridge._messages._items if m.get("role") == "activity"), None,
            )
            self.assertIsNotNone(msg_first)
            snapshot_first = {t["id"]: dict(t) for t in msg_first.get("activityData", [])}
            count_first = len(self._bridge._messages._items)
            self._bridge._on_runtime_event(
                RuntimeEvent(chat_id, second_terminal, "", {"execution_id": execution_id})
            )
            self.application.processEvents()
            msg_second = next(
                (m for m in self._bridge._messages._items if m.get("role") == "activity"), None,
            )
            self.assertIsNotNone(msg_second)
            snapshot_second = {t["id"]: dict(t) for t in msg_second.get("activityData", [])}
            count_second = len(self._bridge._messages._items)
        finally:
            self._bridge._reload_execution_timeline = orig_reload  # type: ignore
        return snapshot_first, snapshot_second, count_first, count_second

    def _reload_two_terminals(self, tool_payloads, terminals, execution_id=25):
        cid = self._database.create_conversation("R", "codex", "modelo", self._settings.root)
        for p in tool_payloads:
            payload = dict(p)
            payload.setdefault("execution_id", execution_id)
            self._database.add_event(RuntimeEvent(cid, "tool_event", "", payload))
        for term in terminals:
            self._database.add_event(RuntimeEvent(cid, term, "", {"execution_id": execution_id}))
        self._database.begin_user_turn(cid, "hi")
        rows = self._database.messages(cid)
        bridge2_prefs = QSettings(str(Path(self._tmp.name) / f"{cid}_term02.ini"), QSettings.IniFormat)
        bridge2 = ChatBridge(self._settings, self._database, bridge2_prefs)
        self.addCleanup(bridge2.close)
        bridge2._selected = {"conversationId": cid}
        ok = bridge2._reload_execution_timeline(cid, rows)
        self.assertTrue(ok)
        cards = {}
        for m in bridge2._messages._items:
            for t in m.get("activityData", []):
                cards[t["id"]] = t
        return cards

    def test_corr_tc_term_02_error_then_completed_keeps_failure(self):
        chat_id = self._database.create_conversation("C1", "codex", "m", self._settings.root)
        first, second, _, _ = self._run_live_two_terminals(
            chat_id,
            [{"toolCallId": "t1", "step_type": "commandExecution", "status": "running"}],
            "error", "turn_completed",
        )
        self.assertEqual(first["t1"]["state"], "error")
        self.assertEqual(second["t1"]["state"], "error")
        reloaded = self._reload_two_terminals(
            [{"toolCallId": "t1", "step_type": "commandExecution", "status": "running"}],
            ["error", "turn_completed"],
        )
        self.assertEqual(reloaded["t1"]["state"], "error")

    def test_corr_tc_term_02_cancelled_then_completed_keeps_cancelled(self):
        chat_id = self._database.create_conversation("C2", "codex", "m", self._settings.root)
        first, second, _, _ = self._run_live_two_terminals(
            chat_id,
            [{"toolCallId": "t2", "step_type": "commandExecution", "status": "running"}],
            "orchestration_cancelled", "turn_completed",
        )
        self.assertEqual(first["t2"]["state"], "cancelled")
        self.assertEqual(second["t2"]["state"], "cancelled")
        reloaded = self._reload_two_terminals(
            [{"toolCallId": "t2", "step_type": "commandExecution", "status": "running"}],
            ["orchestration_cancelled", "turn_completed"],
        )
        self.assertEqual(reloaded["t2"]["state"], "cancelled")

    def test_corr_tc_term_02_completed_then_error_keeps_interrupted(self):
        chat_id = self._database.create_conversation("C3", "codex", "m", self._settings.root)
        eid = 7
        first, second, count_first, count_second = self._run_live_two_terminals(
            chat_id,
            [{"toolCallId": "t3", "step_type": "commandExecution", "status": "running"}],
            "turn_completed", "error", execution_id=eid,
        )
        self.assertEqual(first["t3"]["state"], "interrupted")
        # Late terminal must not alter the card.
        self.assertEqual(second, first)
        self.assertEqual(count_second, count_first)
        # Reducer must not be recreated for the terminated execution.
        self.assertNotIn((chat_id, eid), getattr(self._bridge, "_tool_reducers", {}))
        # Exactly the terminated execution is recorded, no second visual terminal.
        term_execs = [k for k in self._bridge._ui_terminal_executions if k[0] == chat_id]
        self.assertEqual(term_execs, [(chat_id, eid)])
        reloaded = self._reload_two_terminals(
            [{"toolCallId": "t3", "step_type": "commandExecution", "status": "running"}],
            ["turn_completed", "error"],
        )
        self.assertEqual(reloaded["t3"]["state"], "interrupted")

    def test_corr_tc_term_02_completed_then_cancelled_keeps_interrupted(self):
        chat_id = self._database.create_conversation("C4", "codex", "m", self._settings.root)
        eid = 7
        first, second, count_first, count_second = self._run_live_two_terminals(
            chat_id,
            [{"toolCallId": "t4", "step_type": "commandExecution", "status": "running"}],
            "turn_completed", "orchestration_cancelled", execution_id=eid,
        )
        self.assertEqual(first["t4"]["state"], "interrupted")
        self.assertEqual(second, first)
        self.assertEqual(count_second, count_first)
        self.assertNotIn((chat_id, eid), getattr(self._bridge, "_tool_reducers", {}))
        term_execs = [k for k in self._bridge._ui_terminal_executions if k[0] == chat_id]
        self.assertEqual(term_execs, [(chat_id, eid)])
        reloaded = self._reload_two_terminals(
            [{"toolCallId": "t4", "step_type": "commandExecution", "status": "running"}],
            ["turn_completed", "orchestration_cancelled"],
        )
        self.assertEqual(reloaded["t4"]["state"], "interrupted")

    def test_corr_tc_term_02_explicit_success_survives_late_error(self):
        tool_events = [
            {"toolCallId": "t5", "step_type": "commandExecution", "status": "running"},
            {"toolCallId": "t5", "step_type": "commandExecution", "status": "success", "output": "ok"},
        ]
        chat_id = self._database.create_conversation("C5", "codex", "m", self._settings.root)
        first, second, _, _ = self._run_live_two_terminals(
            chat_id, tool_events, "turn_completed", "error",
        )
        self.assertEqual(first["t5"]["state"], "completed")
        self.assertEqual(second["t5"]["state"], "completed")
        reloaded = self._reload_two_terminals(tool_events, ["turn_completed", "error"])
        self.assertEqual(reloaded["t5"]["state"], "completed")

    def test_corr_tc_term_02_no_dead_terminal_priority_code(self):
        root = Path(__file__).resolve().parent.parent / "vrsoft_extractor" / "mary" / "frontend"
        for rel in ("bridges/activity.py", "chat.py", "bridges/conversations.py"):
            text = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn("TERMINAL_PRIORITY", text)
            self.assertNotIn("_ui_terminal_kinds", text)


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

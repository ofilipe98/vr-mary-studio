"""Regression tests for conversation-delete lifecycle and isolation.

Covers: per-conversation execution gating, deletion of error chats,
draft cleanup on send failure, residual _active_turns reconciliation,
background terminal cleanup, and explicit trashConversation targeting.
"""

import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.models import RuntimeEvent


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


def _wait_for_trash_idle(bridge: ChatBridge, timeout_s: float = 10.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while bridge.conversationDeleteRunning and time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        time.sleep(0.01)
    if app is not None:
        app.processEvents()


def _active_ids(bridge: ChatBridge) -> list[str]:
    return [
        item["conversationId"] for item in bridge._all_conversations
    ]


def _make_two_chats(bridge: ChatBridge, database: MaryDatabase, settings: MarySettings):
    chat1 = database.create_conversation(
        "Chat 1", "codex", "modelo", settings.root
    )
    chat2 = database.create_conversation(
        "Chat 2", "codex", "modelo", settings.root
    )
    database.add_message(chat1, "user", "mensagem do chat 1")
    database.add_message(chat2, "user", "mensagem do chat 2")
    bridge.refresh()
    return chat1, chat2


class DeleteIsolationTestMixin:
    application = None
    _bridges: list = []

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self._bridges = []
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._settings = _settings(root)
        self._database = _database(self._settings)
        self._preferences = QSettings(
            str(root / "preferences.ini"), QSettings.IniFormat
        )
        self._bridge = ChatBridge(
            self._settings, self._database, self._preferences
        )
        self._bridges.append(self._bridge)

    def tearDown(self):
        for bridge in reversed(self._bridges):
            bridge.close()
        self.application.processEvents()


import unittest


class ConversationDeleteIsolationTest(DeleteIsolationTestMixin, unittest.TestCase):
    def test_a_running_chat_cannot_be_deleted(self):
        chat1, _chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)

        self._bridge.trashConversation(chat1)

        self.assertFalse(self._bridge.conversationDeleteRunning)
        self.assertIn(chat1, _active_ids(self._bridge))
        self.assertIn("execução", self._bridge.statusText)
        row = self._database.get_conversation(chat1)
        self.assertEqual(int(row["archived"]), 0)
        self.assertEqual(str(row["trashed_at"] or ""), "")

    def test_b_other_chat_can_be_deleted_while_one_runs(self):
        chat1, chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat2)

        self._bridge.trashConversation(chat2)
        _wait_for_trash_idle(self._bridge)

        self.assertFalse(self._bridge.conversationDeleteRunning)
        self.assertNotIn(chat2, _active_ids(self._bridge))
        row2 = self._database.get_conversation(chat2)
        self.assertEqual(int(row2["archived"]), 1)
        self.assertTrue(str(row2["trashed_at"] or ""))
        # Chat 1 keeps running undisturbed.
        self.assertIn(chat1, self._bridge._active_turns)
        self.assertEqual(
            str(self._database.get_conversation(chat1)["status"]), "running"
        )
        self.assertIn("lixeira", self._bridge.statusText)

    def test_c_context_menu_target_without_reselecting(self):
        chat1, chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)

        # Explicit target: delete chat 2 while chat 1 stays selected.
        self._bridge.trashConversation(chat2)
        _wait_for_trash_idle(self._bridge)

        self.assertNotIn(chat2, _active_ids(self._bridge))
        self.assertIn(chat1, _active_ids(self._bridge))
        self.assertEqual(self._bridge._selected_conversation_id(), chat1)
        self.assertEqual(
            str(self._database.get_conversation(chat1)["status"]), "running"
        )

    def test_d_error_chat_can_be_deleted(self):
        chat1, _chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="error")
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)

        self._bridge.trashConversation(chat1)
        _wait_for_trash_idle(self._bridge)

        self.assertNotIn(chat1, _active_ids(self._bridge))
        row = self._database.get_conversation(chat1)
        self.assertEqual(int(row["archived"]), 1)
        self.assertTrue(str(row["trashed_at"] or ""))

    def test_send_failure_before_persistence_restores_draft(self):
        """P1 requirement: failure before begin_user_turn() -> message remains
        recoverable and draft is restored."""
        chat1 = self._database.create_conversation(
            "Falha antes de persistir", "codex", "modelo", self._settings.root
        )
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)
        self.assertTrue(self._bridge.saveCurrentDraft("texto ainda não enviado"))
        self._bridge.refresh()
        self.assertIn(chat1, self._bridge._draft_records)

        restored_texts = []
        self._bridge.draftRestored.connect(restored_texts.append)

        with patch.object(
            self._bridge._orchestrator,
            "send",
            side_effect=RuntimeError("connection refused before persist"),
        ):
            self._bridge._send_message("texto ainda não enviado")

        # Invariants:
        # - message was NOT persisted
        self.assertEqual(len(self._database.messages(chat1)), 0)
        # - draft restored
        self.assertIn(chat1, self._bridge._draft_records)
        self.assertEqual(
            self._bridge._draft_records[chat1]["text"],
            "texto ainda não enviado",
        )
        # - draftRestored signal emitted with content
        self.assertIn("texto ainda não enviado", restored_texts)

    def test_send_failure_after_persistence_does_not_restore_draft_and_leaves_deletable(self):
        """P1 requirement: failure after begin_user_turn() -> message remains in history,
        draft does NOT return, conversation stays error/failed and deletable."""
        chat1 = self._database.create_conversation(
            "Falha após persistência", "codex", "modelo", self._settings.root
        )
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)
        self.assertTrue(self._bridge.saveCurrentDraft("texto confirmado para envio"))
        self._bridge.refresh()
        self.assertIn(chat1, self._bridge._draft_records)

        restored_texts = []
        self._bridge.draftRestored.connect(restored_texts.append)

        def fail_after_begin_user_turn(*args, **kwargs):
            self._database.begin_user_turn(chat1, "texto confirmado para envio")
            raise RuntimeError("provider crashed mid-turn")

        with patch.object(
            self._bridge._orchestrator,
            "send",
            side_effect=fail_after_begin_user_turn,
        ):
            self._bridge._send_message("texto confirmado para envio")

        # Invariants:
        # - message WAS persisted in DB
        db_msgs = self._database.messages(chat1)
        self.assertTrue(any(m["role"] == "user" and m["content"] == "texto confirmado para envio" for m in db_msgs))
        # - draft NOT restored
        self.assertNotIn(chat1, self._bridge._draft_records)
        self.assertNotIn("texto confirmado para envio", restored_texts)
        # - conversation status set to 'error' (failed turn)
        row = self._database.get_conversation(chat1)
        self.assertEqual(str(row["status"]), "error")
        # - conversation is deletable
        self._bridge.trashConversation(chat1)
        _wait_for_trash_idle(self._bridge)
        self.assertNotIn(chat1, _active_ids(self._bridge))

    def test_persisted_running_status_blocks_trash_even_if_not_in_active_turns(self):
        """P2 requirement: database status 'running' must be authority to block trash,
        even if cid is absent from _active_turns."""
        chat1, _ = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.discard(chat1)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)

        self._bridge.trashConversation(chat1)

        self.assertFalse(self._bridge.conversationDeleteRunning)
        self.assertEqual(self._bridge._selected_conversation_id(), chat1)
        self.assertEqual(self._bridge.statusText, "Esta conversa ainda está em execução.")
        row = self._database.get_conversation(chat1)
        self.assertEqual(int(row["archived"]), 0)
        self.assertEqual(str(row["trashed_at"] or ""), "")

    def test_real_qml_context_menu_delete_keeps_running_chat_intact(self):
        """P2 requirement: Real Qt/QML component test:
        Chat 1 running and selected, Chat 2 idle.
        Open context menu for Chat 2, click Excluir, confirm dialog.
        Result: only Chat 2 is moved to trash; Chat 1 continues running;
        Chat 1 continues in _active_turns; no cancellation on Chat 1;
        composer not cleared; target of deletion is Chat 2."""
        from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
        from vrsoft_extractor.mary.frontend.studio import StudioBridge
        from vrsoft_extractor.mary.frontend.app import create_engine
        from PySide6.QtCore import QObject

        chat1, chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)

        frontend = FrontendBridge(self._settings, self._preferences, initial_page="Chat VR")
        studio = StudioBridge(self._settings, self._database, self._preferences)
        engine = create_engine(frontend, self._bridge, studio)
        self.application.processEvents()

        root_obj = engine.rootObjects()[0]
        chat_page = root_obj.findChild(QObject, "chatPage")
        self.assertIsNotNone(chat_page)

        composer = chat_page.property("composerInput")
        composer.setProperty("text", "draft em progresso no chat 1")
        self.application.processEvents()

        # Open context menu specifically targeting Chat 2
        chat_page.openConversationMenu(chat2, 100, 100)
        self.application.processEvents()

        # Verify chat 1 is still selected and conversationMenuConversationId is chat2
        self.assertEqual(self._bridge._selected_conversation_id(), chat1)
        self.assertEqual(chat_page.property("conversationMenuConversationId"), chat2)

        # Open delete dialog
        del_dialog = chat_page.findChild(QObject, "conversationDeleteDialog")
        del_dialog.open()
        self.application.processEvents()

        # Click confirm delete
        confirm_btn = del_dialog.findChild(QObject, "confirmDeleteButton")
        self.assertIsNotNone(confirm_btn)
        confirm_btn.clicked.emit()
        self.application.processEvents()

        _wait_for_trash_idle(self._bridge)

        # Invariants:
        # - only Chat 2 is moved to trash
        self.assertNotIn(chat2, _active_ids(self._bridge))
        self.assertEqual(int(self._database.get_conversation(chat2)["archived"]), 1)
        # - Chat 1 continues running and in _active_turns
        self.assertIn(chat1, _active_ids(self._bridge))
        self.assertIn(chat1, self._bridge._active_turns)
        self.assertEqual(
            str(self._database.get_conversation(chat1)["status"]), "running"
        )
        # - Chat 1 remains selected
        self.assertEqual(self._bridge._selected_conversation_id(), chat1)
        # - Composer is not cleared
        self.assertEqual(composer.property("text"), "draft em progresso no chat 1")

        studio.close()

    def test_tool_activity_ui_lifecycle_reducer_full_flow(self):
        """P2 requirement: Tool Activity UI pipeline:
        started -> updated -> duplicate updated -> completed -> delayed running event.
        Result: single card, no duplication, completed remains terminal, output not duplicated."""
        chat1 = self._database.create_conversation(
            "Tool UI Test", "codex", "modelo", self._settings.root
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)

        # 1. started
        self._bridge._on_runtime_event(
            RuntimeEvent(chat1, "tool_event", "Iniciando comando", {
                "execution_id": 1,
                "toolCallId": "call_pytest_1",
                "step_type": "commandExecution",
                "status": "running",
                "name": "run_pytest",
                "command": "pytest -v",
            })
        )
        self.application.processEvents()

        # 2. updated
        self._bridge._on_runtime_event(
            RuntimeEvent(chat1, "tool_event", "Executando", {
                "execution_id": 1,
                "toolCallId": "call_pytest_1",
                "step_type": "commandExecution",
                "status": "running",
                "delta": "test_1 passed\n",
            })
        )
        self.application.processEvents()

        # 3. updated duplicate
        self._bridge._on_runtime_event(
            RuntimeEvent(chat1, "tool_event", "Executando", {
                "execution_id": 1,
                "toolCallId": "call_pytest_1",
                "step_type": "commandExecution",
                "status": "running",
                "delta": "test_1 passed\n",
            })
        )
        self.application.processEvents()

        # 4. completed
        self._bridge._on_runtime_event(
            RuntimeEvent(chat1, "tool_event", "Concluído com sucesso", {
                "execution_id": 1,
                "toolCallId": "call_pytest_1",
                "step_type": "commandExecution",
                "status": "success",
                "delta": "test_2 passed\n",
            })
        )
        self.application.processEvents()

        # 5. delayed running event arriving after completed
        self._bridge._on_runtime_event(
            RuntimeEvent(chat1, "tool_event", "Evento atrasado", {
                "execution_id": 1,
                "toolCallId": "call_pytest_1",
                "step_type": "commandExecution",
                "status": "running",
                "delta": "delayed chunk",
            })
        )
        self.application.processEvents()

        # Find activity message in _messages
        activity_msg = next((m for m in self._bridge._messages._items if m.get("role") == "activity"), None)
        self.assertIsNotNone(activity_msg)
        activity_data = activity_msg.get("activityData", [])

        # Invariants:
        # - Single card (no duplicate cards)
        self.assertEqual(len(activity_data), 1)
        card = activity_data[0]
        self.assertEqual(card["id"], "call_pytest_1")

        # - Completed remains terminal (not reverted to running by delayed event)
        self.assertEqual(card["state"], "completed")

        # - Output does not duplicate
        self.assertEqual(card["output"], "test_1 passed\ntest_2 passed\n")

    def test_f_residual_active_turn_with_error_status_is_reconciled(self):
        chat1, _chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="error")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()

        self._bridge.trashConversation(chat1)
        _wait_for_trash_idle(self._bridge)

        self.assertNotIn(chat1, self._bridge._active_turns)
        self.assertNotIn(chat1, _active_ids(self._bridge))
        row = self._database.get_conversation(chat1)
        self.assertEqual(int(row["archived"]), 1)

    def test_g_genuinely_running_chat_stays_protected(self):
        chat1, _chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()

        self._bridge.trashConversation(chat1)

        self.assertIn(chat1, self._bridge._active_turns)
        self.assertIn(chat1, _active_ids(self._bridge))
        self.assertIn("execução", self._bridge.statusText)

    def test_h_background_terminal_event_clears_only_that_chat(self):
        chat1, chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._database.update_conversation(chat1, status="running")
        self._bridge._active_turns.add(chat1)
        self._bridge.refresh()
        self._bridge.selectConversationId(chat2)

        self._database.update_conversation(chat1, status="error")
        self._bridge._on_runtime_event(
            RuntimeEvent(chat1, "error", "falha em background")
        )
        self.application.processEvents()

        self.assertNotIn(chat1, self._bridge._active_turns)
        self.assertIn(chat2, _active_ids(self._bridge))
        self.assertEqual(self._bridge._selected_conversation_id(), chat2)

    def test_trash_current_conversation_remains_a_selected_wrapper(self):
        _chat1, chat2 = _make_two_chats(
            self._bridge, self._database, self._settings
        )
        self._bridge.selectConversationId(chat2)

        self._bridge.trashCurrentConversation()
        _wait_for_trash_idle(self._bridge)

        self.assertNotIn(chat2, _active_ids(self._bridge))

    def test_qml_delete_uses_explicit_menu_target(self):
        chat_qml = (
            Path(__file__).resolve().parent.parent
            / "vrsoft_extractor" / "mary" / "frontend" / "qml"
            / "pages" / "ChatPreview.qml"
        ).read_text(encoding="utf-8")
        self.assertIn("conversationMenuConversationId", chat_qml)
        self.assertIn("trashConversation(targetId)", chat_qml)


if __name__ == "__main__":
    unittest.main()

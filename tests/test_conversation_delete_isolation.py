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

    def test_e_failed_send_does_not_stay_draft(self):
        chat1 = self._database.create_conversation(
            "Falha no envio", "codex", "modelo", self._settings.root
        )
        self._bridge.refresh()
        self._bridge.selectConversationId(chat1)
        self.assertTrue(self._bridge.saveCurrentDraft("texto ainda não enviado"))
        self._bridge.refresh()
        self.assertIn(chat1, self._bridge._draft_records)

        with patch.object(
            self._bridge._orchestrator,
            "send",
            side_effect=RuntimeError("provider offline"),
        ):
            self._bridge._send_message("texto confirmado para envio")

        self.assertNotIn(chat1, self._bridge._draft_records)
        self.assertFalse(
            next(
                item
                for item in self._bridge._all_conversations
                if item["conversationId"] == chat1
            )["editing"]
        )
        # The confirmed send is not a draft even though the provider failed;
        # the conversation remains deletable through the trash lifecycle.
        self._bridge.trashConversation(chat1)
        _wait_for_trash_idle(self._bridge)
        self.assertNotIn(chat1, _active_ids(self._bridge))

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

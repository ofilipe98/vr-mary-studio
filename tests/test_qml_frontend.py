import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary import brand
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import MAIN_QML, create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge, NAVIGATION_ITEMS
from vrsoft_extractor.mary.frontend.chat import ChatBridge, markdown_for_display
from vrsoft_extractor.mary.models import RuntimeEvent


class QmlFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def _settings(self, root: Path) -> MarySettings:
        return MarySettings(
            app_dir=root,
            root=root / "VRProject",
            old_root=root / "legacy-source",
        )

    def _bridge(
        self,
        root: Path,
        *,
        theme: str = "light",
        initial_page: str = "Dashboard",
    ) -> FrontendBridge:
        settings = self._settings(root)
        preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
        return FrontendBridge(
            settings,
            preferences,
            theme_override=theme,
            initial_page=initial_page,
        )

    def test_brand_palette_keeps_existing_vr_identity(self):
        light = brand.brand_palette("light")
        dark = brand.brand_palette("dark_orange")

        self.assertEqual(light["brandOrange"], "#FF7200")
        self.assertEqual(light["accessibleOrange"], "#C45100")
        self.assertEqual(light["brandNavy"], "#02021E")
        self.assertEqual(light["navigationBackground"], "#000000")
        self.assertEqual(light["navText"], "#E9E9F0")
        self.assertEqual(light["navHover"], "#19191D")
        self.assertEqual(light["background"], "#F3F3F3")
        self.assertEqual(dark["background"], "#12100F")
        self.assertEqual(dark["surface"], "#1B1816")

    def test_bridge_exposes_current_navigation_without_business_services(self):
        with TemporaryDirectory() as temporary:
            bridge = self._bridge(Path(temporary), initial_page="Chat VR")

            self.assertEqual(
                [item["title"] for item in bridge.navigationItems],
                [title for title, _icon in NAVIGATION_ITEMS],
            )
            self.assertEqual(bridge.currentPage, 1)
            self.assertEqual(bridge.currentPageTitle, "Chat VR")
            self.assertTrue(bridge.brandSymbolUrl.startswith("file:"))

    def test_bridge_persists_only_frontend_preferences(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            settings = MarySettings(
                app_dir=root,
                root=root / "VRProject",
                old_root=root / "legacy-source",
            )
            bridge = FrontendBridge(settings, preferences)

            bridge.setTheme("dark_orange")
            bridge.toggleNavigation()

            self.assertEqual(bridge.themeId, "dark_orange")
            self.assertEqual(preferences.value("appearance/theme"), "dark_orange")
            self.assertIsNotNone(preferences.value("appearance/nav_collapsed"))

    def test_qml_shell_loads_with_the_frontend_bridge(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            bridge = self._bridge(root, initial_page="Chat VR")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Conversa de validação",
                "codex",
                "gpt-5.6",
                settings.root / "Cliente",
            )
            database.add_message(conversation_id, "user", "Mensagem de teste")
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()

            self.assertTrue(MAIN_QML.exists())
            self.assertEqual(len(engine.rootObjects()), 1)
            window = engine.rootObjects()[0]
            self.assertEqual(window.property("title"), "VR Norte Studio")
            self.assertGreaterEqual(window.property("minimumWidth"), 1120)
            self.assertIsNotNone(window.findChild(QObject, "chatModelPicker"))
            self.assertIsNotNone(window.findChild(QObject, "modelPickerPopup"))
            self.assertIsNotNone(window.findChild(QObject, "chatReasoningPicker"))
            self.assertIsNotNone(window.findChild(QObject, "chatPermissionPicker"))
            self.assertIsNotNone(window.findChild(QObject, "contextUsageButton"))
            self.assertIsNotNone(window.findChild(QObject, "contextUsagePopup"))
            new_chat_button = window.findChild(QObject, "newChatButton")
            self.assertIsNotNone(new_chat_button)
            sidebar_toggles = window.findChildren(QObject, "conversationSidebarToggle")
            self.assertEqual(len(sidebar_toggles), 1)
            surface_toggle = window.findChild(QObject, "surfaceToggleButton")
            surface_add = window.findChild(QObject, "surfaceAddButton")
            surface_picker = window.findChild(QObject, "surfacePickerPopup")
            self.assertIsNotNone(surface_toggle)
            self.assertIsNotNone(surface_add)
            self.assertIsNotNone(surface_picker)
            self.assertIsNotNone(window.findChild(QObject, "conversationSidebar"))
            self.assertIsNone(window.findChild(QObject, "navigationRail"))
            self.assertIsNotNone(window.findChild(QObject, "surfacePanel"))
            conversation_menu = window.findChild(QObject, "conversationContextMenu")
            self.assertIsNotNone(conversation_menu)
            chat_page = window.findChild(QObject, "chatPage")
            self.assertIsNotNone(chat_page)
            chat_page.openConversationMenu(0, 50, 50)
            self.application.processEvents()
            self.assertTrue(conversation_menu.property("visible"))
            conversation_menu.close()
            surface_toggle.click()
            chat_page.openSurface(1)
            chat_page.openSurface(2)
            self.application.processEvents()
            self.assertEqual(
                len(chat_page.property("openSurfaceTabs").toVariant()), 2
            )
            self.assertEqual(chat_page.property("surfaceIndex"), 2)
            self.assertIsNotNone(window.findChild(QObject, "terminalCommandInput"))
            terminal_background = window.findChild(
                QObject, "terminalSurfaceBackground"
            )
            terminal_output_background = window.findChild(
                QObject, "terminalOutputBackground"
            )
            file_preview_background = window.findChild(
                QObject, "filePreviewBackground"
            )
            self.assertEqual(
                terminal_background.property("color"),
                QColor(bridge.palette["chatSidebar"]),
            )
            self.assertEqual(
                terminal_output_background.property("color"),
                QColor(bridge.palette["chatSidebar"]),
            )
            self.assertEqual(
                file_preview_background.property("color"),
                QColor(bridge.palette["chatSidebar"]),
            )
            bridge.setTheme("dark_orange")
            self.application.processEvents()
            self.assertEqual(
                terminal_background.property("color"),
                QColor(bridge.palette["chatSidebar"]),
            )
            self.assertEqual(
                terminal_output_background.property("color"),
                QColor(bridge.palette["chatSidebar"]),
            )
            bridge.setTheme("light")
            self.application.processEvents()
            self.assertEqual(
                terminal_background.property("color"),
                QColor(bridge.palette["chatSidebar"]),
            )
            chat_page.closeSurface(2)
            self.application.processEvents()
            self.assertEqual(
                len(chat_page.property("openSurfaceTabs").toVariant()), 1
            )
            self.assertEqual(chat_page.property("surfaceIndex"), 1)
            surface_add.click()
            self.application.processEvents()
            self.assertTrue(surface_picker.property("visible"))
            surface_picker.close()
            new_chat_button.click()
            self.application.processEvents()
            self.assertTrue(chat_bridge.isDraft)
            project_selector_popup = window.findChild(QObject, "projectSelectorPopup")
            self.assertIsNotNone(project_selector_popup)
            self.assertTrue(project_selector_popup.property("visible"))
            self.assertIsNotNone(window.findChild(QObject, "newChatProjectSearch"))
            self.assertIsNotNone(window.findChild(QObject, "newChatProjectList"))
            bridge.setCurrentPage(7)
            self.application.processEvents()
            settings_navigation = window.findChild(QObject, "settingsNavigation")
            self.assertIsNotNone(settings_navigation)
            self.assertEqual(
                settings_navigation.property("color"),
                QColor(bridge.palette["navigationBackground"]),
            )
            window.close()
            engine.deleteLater()
            self.application.processEvents()

    def test_chat_bridge_reads_and_filters_existing_conversations(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Configuração fiscal",
                "codex",
                "gpt-5.6",
                settings.root / "Cliente Norte",
            )
            database.add_message(conversation_id, "user", "Como configurar a NFC-e?")
            database.add_message(conversation_id, "assistant", "Consulte o cadastro fiscal.")

            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            bridge = ChatBridge(settings, database, preferences)

            self.assertEqual(bridge.conversationCount, 1)
            self.assertTrue(bridge.hasSelection)
            self.assertEqual(bridge.selectedTitle, "Configuração fiscal")
            self.assertEqual(bridge.messages.rowCount(), 2)

            bridge.setSearch("inexistente")
            self.assertEqual(bridge.conversationCount, 0)
            self.assertFalse(bridge.hasSelection)

            bridge.setSearch("fiscal")
            self.assertEqual(bridge.conversationCount, 1)
            self.assertEqual(bridge.selectedProject, "Cliente Norte")

            bridge.copyMessage(0)
            self.assertEqual(
                self.application.clipboard().text(), "Como configurar a NFC-e?"
            )

    def test_chat_model_favorites_are_exposed_and_persisted(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            bridge = ChatBridge(settings, database, preferences)
            original = bridge.modelItems[0]
            key = original["key"]

            bridge.toggleModelFavorite(0)

            selected = next(item for item in bridge.modelItems if item["key"] == key)
            stored = json.loads(str(preferences.value("chat/favorite_models")))
            self.assertTrue(selected["favorite"])
            self.assertIn(key, stored)

            bridge.toggleModelFavorite(
                next(
                    index
                    for index, item in enumerate(bridge.modelItems)
                    if item["key"] == key
                )
            )
            selected = next(item for item in bridge.modelItems if item["key"] == key)
            self.assertFalse(selected["favorite"])

    def test_chat_project_filter_and_new_draft_do_not_create_database_rows(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            project_north = settings.root / "Cliente Norte"
            project_south = settings.root / "Cliente Sul"
            project_north.mkdir(parents=True)
            project_south.mkdir(parents=True)
            database.create_conversation(
                "Conversa Norte", "codex", "gpt-5.6", project_north
            )
            database.create_conversation(
                "Conversa Sul", "claude", "sonnet", project_south
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            bridge = ChatBridge(settings, database, preferences)

            self.assertTrue(
                any(Path(item["path"]) == settings.root for item in bridge.projectItems if item["path"])
            )

            north_index = next(
                index
                for index, item in enumerate(bridge.projectItems)
                if item["label"] == "Cliente Norte"
            )
            bridge.setProject(north_index)
            self.assertEqual(bridge.conversationCount, 1)
            self.assertEqual(bridge.selectedTitle, "Conversa Norte")

            before = len(database.list_conversations(state="active"))
            bridge.startNewChat()

            self.assertTrue(bridge.isDraft)
            self.assertFalse(bridge.hasSelection)
            self.assertEqual(bridge.selectedTitle, "Nova conversa")
            self.assertEqual(bridge.selectedProject, "Cliente Norte")
            self.assertEqual(
                len(database.list_conversations(state="active")), before
            )

    def test_new_chat_reuses_last_model_effort_tier_and_permission(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            database.create_conversation(
                "Conversa configurada",
                "codex",
                "gpt-5.6-sol",
                settings.root / "Cliente",
                effort="high",
                service_tier="fast",
                approval_profile="full_access",
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            bridge = ChatBridge(settings, database, preferences)

            bridge.startNewChat()

            selected_model = bridge.modelItems[bridge.modelIndex]
            self.assertEqual(selected_model["value"], "gpt-5.6-sol")
            self.assertEqual(bridge.effortItems[bridge.effortIndex]["value"], "high")
            self.assertEqual(
                bridge.serviceTierItems[bridge.serviceTierIndex]["value"], "fast"
            )
            self.assertEqual(
                bridge.approvalItems[bridge.approvalIndex]["value"], "full_access"
            )
            self.assertEqual(preferences.value("chat/last_model/codex"), "gpt-5.6-sol")

    def test_effort_and_service_tier_options_follow_selected_model_metadata(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            bridge = ChatBridge(settings, database, preferences)
            bridge._provider = "opencode"
            bridge._model = "opencode/ox-alpha"
            bridge._model_items = [
                {
                    "label": "OX Alpha",
                    "displayName": "OX Alpha",
                    "value": "opencode/ox-alpha",
                    "provider": "opencode",
                    "key": "opencode:opencode/ox-alpha",
                    "efforts": ["low", "high", "max"],
                    "serviceTiers": [],
                }
            ]
            bridge._effort = "medium"

            bridge._restore_effort_for_current_model()

            self.assertEqual(
                [item["value"] for item in bridge.effortItems],
                ["low", "high", "max"],
            )
            self.assertEqual(bridge.effortItems[bridge.effortIndex]["value"], "low")
            self.assertEqual(bridge.serviceTierItems, [])
            bridge.setEffort(1)
            saved = json.loads(str(preferences.value("chat/model_efforts")))
            self.assertEqual(saved["opencode:opencode/ox-alpha"], "high")

    def test_chat_bridge_exposes_live_orchestration_plan_and_agent_output(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Execução VR", "codex", "gpt-5.6", settings.root
            )
            database.add_message(conversation_id, "user", "Revise o fluxo.")
            database.add_message(conversation_id, "assistant", "Fluxo revisado.")
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )

            bridge._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "plan_created",
                    "Plano preparado.",
                    {
                        "plan": {
                            "agents": [
                                {
                                    "id": "agent-1",
                                    "label": "VR Fiscal",
                                    "task": "Validar a regra fiscal",
                                    "model": {
                                        "provider": "codex",
                                        "model": "gpt-5.6",
                                    },
                                    "effort": "high",
                                }
                            ]
                        }
                    },
                )
            )
            bridge._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "agent_completed",
                    "VR Fiscal concluiu.",
                    {"agent_id": "agent-1", "output": "Regra validada."},
                )
            )

            self.assertEqual(len(bridge.agentItems), 1)
            self.assertEqual(bridge.agentItems[0]["status"], "concluído")
            self.assertEqual(bridge.agentItems[0]["output"], "Regra validada.")
            self.assertEqual(len(bridge.activitySteps), 2)
            bridge._reasoning_text = "Validação concluída com as evidências locais."
            bridge._reload_selected_messages()
            self.assertEqual(
                [bridge.messages.item(index)["role"] for index in range(3)],
                ["user", "activity", "assistant"],
            )
            self.assertEqual(
                bridge.reasoningText,
                "Validação concluída com as evidências locais.",
            )

    def test_chat_bridge_restores_latest_persisted_task_timeline(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Revisão persistida", "codex", "gpt-5.6", settings.root
            )
            database.add_message(conversation_id, "user", "Revise o cadastro.")
            database.add_message(
                conversation_id, "assistant", "O cadastro foi revisado."
            )
            for event in (
                RuntimeEvent(
                    conversation_id,
                    "response_plan_created",
                    "Plano de resposta criado",
                    {
                        "steps": [
                            "Ler o cadastro local",
                            "Validar a regra fiscal",
                            "Preparar a resposta",
                        ]
                    },
                ),
                RuntimeEvent(conversation_id, "turn_started", "Execução iniciada"),
                RuntimeEvent(
                    conversation_id,
                    "reasoning_delta",
                    "Conferindo evidências locais.",
                ),
                RuntimeEvent(
                    conversation_id,
                    "assistant_delta",
                    "O cadastro foi revisado.",
                ),
                RuntimeEvent(conversation_id, "turn_completed", "Pronto"),
            ):
                database.add_event(event)

            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )

            self.assertEqual(
                [bridge.messages.item(index)["role"] for index in range(3)],
                ["user", "activity", "assistant"],
            )
            self.assertEqual(
                [step["text"] for step in bridge.activitySteps],
                [
                    "Ler o cadastro local",
                    "Validar a regra fiscal",
                    "Preparar a resposta",
                ],
            )
            self.assertTrue(
                all(step["state"] == "completed" for step in bridge.activitySteps)
            )
            self.assertEqual(
                bridge.reasoningText, "Conferindo evidências locais."
            )

    def test_markdown_display_repairs_glued_sentences_without_touching_code(self):
        source = "Versão pronta.Próximo passo: `arquivo.MD`."

        self.assertEqual(
            markdown_for_display(source),
            "Versão pronta. Próximo passo: `arquivo.MD`.",
        )

    def test_chat_file_surface_previews_only_project_text_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            document = settings.root / "instrucoes.md"
            document.write_text("# Instruções VR", encoding="utf-8")
            outside = root / "fora.txt"
            outside.write_text("não deve abrir", encoding="utf-8")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )

            self.assertEqual(bridge.readFilePreview(str(document)), "# Instruções VR")
            self.assertIn("fora do projeto", bridge.readFilePreview(str(outside)))

    def test_application_entrypoint_dispatches_qml_by_default(self):
        from vrsoft_extractor.mary import ui

        with patch(
            "vrsoft_extractor.mary.frontend.app.main", return_value=23
        ) as qml_main:
            result = ui.main(["--project-dir", "demo"])

        self.assertEqual(result, 23)
        qml_main.assert_called_once_with(["--project-dir", "demo"])

    def test_qml_preview_remains_a_compatibility_alias(self):
        from vrsoft_extractor.mary import ui

        with patch(
            "vrsoft_extractor.mary.frontend.app.main", return_value=23
        ) as qml_main:
            result = ui.main(["--qml-preview", "--project-dir", "demo"])

        self.assertEqual(result, 23)
        qml_main.assert_called_once_with(["--project-dir", "demo"])

    def test_legacy_frontend_flag_is_explicitly_parsed(self):
        from vrsoft_extractor.mary import ui

        args, unknown = ui.build_parser().parse_known_args(
            ["--legacy-frontend", "--project-dir", "demo"]
        )

        self.assertTrue(args.legacy_frontend)
        self.assertEqual(args.project_dir, "demo")
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()

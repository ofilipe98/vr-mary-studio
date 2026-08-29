import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QSettings, Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary import brand
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import MAIN_QML, create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge, NAVIGATION_ITEMS
from vrsoft_extractor.mary.frontend.chat import ChatBridge, markdown_for_display
from vrsoft_extractor.mary.frontend.studio import StudioBridge
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
        self.assertEqual(light["navigationBackground"], "#FFFFFF")
        self.assertEqual(light["navText"], "#02021E")
        self.assertEqual(light["navHover"], "#F1F1F4")
        self.assertEqual(light["background"], "#F3F3F3")
        self.assertEqual(light["accentSoft"], "#FFE8D6")
        self.assertEqual(dark["accentSoft"], "#462813")
        self.assertEqual(brand.ACCENT_SOFT, "#FFE8D6")
        self.assertEqual(brand.DARK_ACCENT_SOFT, "#462813")
        self.assertNotEqual(light["surfaceRaised"], light["surface"])
        self.assertEqual(dark["background"], "#000000")
        self.assertEqual(dark["surface"], "#131110")
        self.assertEqual(dark["surfaceRaised"], "#1B1816")
        self.assertEqual(dark["border"], "#2C2823")

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

    def test_ui_scale_preference_persists_and_ignores_invalid_values(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            settings = self._settings(root)
            bridge = FrontendBridge(settings, preferences)

            self.assertEqual(bridge.uiScale, "auto")
            self.assertEqual(preferences.value("appearance/ui_scale"), "auto")
            self.assertEqual(
                int(preferences.value("appearance/ui_scale_version")), 2
            )
            bridge.setUiScale("105")
            self.assertEqual(bridge.uiScale, "105")
            self.assertEqual(preferences.value("appearance/ui_scale"), "105")
            bridge.setUiScale("999")
            bridge.setUiScale("abc")
            self.assertEqual(bridge.uiScale, "105")
            for granular_scale in ("101", "102", "103", "104", "105"):
                bridge.setUiScale(granular_scale)
                self.assertEqual(bridge.uiScale, granular_scale)
            bridge.setUiScale("150%")
            self.assertEqual(bridge.uiScale, "150")

    def test_legacy_ui_scale_is_migrated_to_automatic(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            preferences.setValue("appearance/ui_scale", "110")
            preferences.sync()

            bridge = FrontendBridge(self._settings(root), preferences)

            self.assertEqual(bridge.uiScale, "auto")
            self.assertEqual(preferences.value("appearance/ui_scale"), "auto")

    def test_startup_applies_saved_ui_scale_to_qt_environment(self):
        from vrsoft_extractor.mary.frontend import app as app_module

        with TemporaryDirectory() as temporary:
            preferences = QSettings(
                str(Path(temporary) / "preferences.ini"), QSettings.IniFormat
            )
            os.environ.pop("QT_SCALE_FACTOR", None)

            app_module.apply_ui_scale_environment(preferences)
            self.assertNotIn("QT_SCALE_FACTOR", os.environ)

            os.environ.pop("QT_SCALE_FACTOR", None)
            preferences.setValue("appearance/ui_scale", "100")
            preferences.sync()
            app_module.apply_ui_scale_environment(preferences)
            self.assertNotIn("QT_SCALE_FACTOR", os.environ)

            preferences.setValue("appearance/ui_scale", "150")
            preferences.sync()
            app_module.apply_ui_scale_environment(preferences)
            self.assertNotIn("QT_SCALE_FACTOR", os.environ)

            os.environ["QT_SCALE_FACTOR"] = "2.0"
            app_module.apply_ui_scale_environment(preferences)
            self.assertEqual(os.environ.get("QT_SCALE_FACTOR"), "2.0")
            os.environ.pop("QT_SCALE_FACTOR", None)

    def test_qml_shell_loads_with_the_frontend_bridge(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            project_file = settings.root / "Cliente" / "src" / "project_file.py"
            project_file.parent.mkdir(parents=True)
            project_file.write_text("print('project file')", encoding="utf-8")
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
            self.assertEqual(
                len(engine.rootObjects()),
                1,
                [warning.toString() for warning in engine._qml_warnings],
            )
            window = engine.rootObjects()[0]
            self.assertEqual(window.property("title"), "VR Norte Studio")
            self.assertGreaterEqual(window.property("minimumWidth"), 1120)
            model_picker = window.findChild(QObject, "chatModelPicker")
            reasoning_picker = window.findChild(QObject, "chatReasoningPicker")
            permission_picker = window.findChild(QObject, "chatPermissionPicker")
            self.assertIsNotNone(model_picker)
            self.assertIsNotNone(reasoning_picker)
            self.assertIsNotNone(permission_picker)
            for picker, popup_name in (
                (model_picker, "modelPickerPopup"),
                (reasoning_picker, "reasoningPickerPopup"),
                (permission_picker, "permissionPickerPopup"),
            ):
                popup = window.findChild(QObject, popup_name)
                self.assertIsNotNone(popup)
                picker.click()
                self.application.processEvents()
                self.assertTrue(popup.property("visible"), popup_name)
                picker.click()
                self.application.processEvents()
                self.assertFalse(popup.property("visible"), popup_name)
            self.assertIsNotNone(window.findChild(QObject, "contextUsageButton"))
            self.assertIsNotNone(window.findChild(QObject, "contextUsagePopup"))
            composer_input = window.findChild(QObject, "chatComposerInput")
            self.assertIsNotNone(composer_input)
            self.assertIsNone(window.findChild(QObject, "chatAttachButton"))
            self.assertIsNotNone(window.findChild(QObject, "chatComposerDropArea"))
            self.assertIsNotNone(window.findChild(QObject, "chatAttachmentList"))
            self.assertIsNotNone(window.findChild(QObject, "chatTaskBar"))
            new_chat_button = window.findChild(QObject, "newChatButton")
            self.assertIsNotNone(new_chat_button)
            add_project_button = window.findChild(QObject, "addProjectButton")
            self.assertIsNotNone(add_project_button)
            add_project_button.click()
            self.application.processEvents()
            add_project_popup = window.findChild(QObject, "addProjectPopup")
            self.assertIsNotNone(add_project_popup)
            self.assertTrue(add_project_popup.property("visible"))
            chat_page = window.findChild(QObject, "chatPage")
            self.assertIsNotNone(chat_page)
            chat_page.openLocalFolderBrowser()
            self.application.processEvents()
            self.assertEqual(chat_page.property("addProjectView"), "folder")
            self.assertIsNotNone(window.findChild(QObject, "projectFolderPathField"))
            self.assertIsNotNone(window.findChild(QObject, "projectFolderList"))
            folder_back = window.findChild(QObject, "projectFolderBackButton")
            self.assertIsNotNone(folder_back)
            folder_back.click()
            self.application.processEvents()
            self.assertEqual(chat_page.property("addProjectView"), "sources")
            add_project_popup.close()
            project_index = next(
                index
                for index, item in enumerate(chat_bridge.projectItems)
                if item["label"] == "Cliente"
            )
            chat_page.openProjectSelectorMenu()
            self.application.processEvents()
            QTest.qWait(50)
            project_selector_menu = window.findChild(QObject, "projectSelectorMenu")
            self.assertIsNotNone(project_selector_menu)
            self.assertTrue(project_selector_menu.property("visible"))
            chat_page.clickProjectSettingsButton(project_index)
            self.application.processEvents()
            project_settings_page = window.findChild(QObject, "projectSettingsPage")
            self.assertIsNotNone(project_settings_page)
            self.assertTrue(project_settings_page.property("visible"))
            self.assertFalse(project_selector_menu.property("visible"))
            self.assertEqual(
                chat_page.property("projectSettingsPath"), str(settings.root / "Cliente")
            )
            self.assertIsNotNone(window.findChild(QObject, "projectSettingsName"))
            self.assertIsNotNone(window.findChild(QObject, "projectSettingsOpenFolder"))
            new_chat_button.click()
            self.application.processEvents()
            QTest.qWait(50)
            self.assertFalse(project_settings_page.property("visible"))
            new_chat_project_popup = window.findChild(QObject, "projectSelectorPopup")
            self.assertIsNotNone(new_chat_project_popup)
            self.assertTrue(new_chat_project_popup.property("visible"))
            new_chat_project_popup.close()
            chat_page.openProjectSettings(project_index)
            self.application.processEvents()
            self.assertTrue(project_settings_page.property("visible"))
            project_settings_back = window.findChild(QObject, "projectSettingsBack")
            self.assertIsNotNone(project_settings_back)
            project_settings_back.click()
            self.application.processEvents()
            self.assertFalse(project_settings_page.property("visible"))
            chat_bridge.setProject(0)
            sidebar_toggles = window.findChildren(QObject, "conversationSidebarToggle")
            self.assertEqual(len(sidebar_toggles), 1)
            surface_toggle = window.findChild(QObject, "surfaceToggleButton")
            surface_add = window.findChild(QObject, "surfaceAddButton")
            surface_picker = window.findChild(QObject, "surfacePickerPopup")
            self.assertIsNotNone(surface_toggle)
            self.assertIsNotNone(surface_add)
            self.assertIsNotNone(surface_picker)
            surface_collapse = window.findChild(QObject, "surfaceCollapseButton")
            self.assertIsNotNone(surface_collapse)
            self.assertIsNotNone(window.findChild(QObject, "conversationSidebar"))
            self.assertIsNone(window.findChild(QObject, "navigationRail"))
            self.assertIsNotNone(window.findChild(QObject, "surfacePanel"))
            conversation_menu = window.findChild(QObject, "conversationContextMenu")
            self.assertIsNotNone(conversation_menu)
            chat_page.openConversationMenu(0, 50, 50)
            self.application.processEvents()
            self.assertTrue(conversation_menu.property("visible"))
            conversation_menu.close()
            surface_toggle.click()
            chat_page.openSurface(1)
            chat_page.openSurface(2)
            self.application.processEvents()
            self.assertTrue(chat_page.property("surfaceVisible"))
            self.assertEqual(
                len(chat_page.property("openSurfaceTabs").toVariant()), 2
            )
            self.assertEqual(chat_page.property("surfaceIndex"), 2)
            surface_collapse.click()
            self.application.processEvents()
            self.assertFalse(chat_page.property("surfaceVisible"))
            surface_toggle.click()
            self.application.processEvents()
            self.assertTrue(chat_page.property("surfaceVisible"))
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
            composer_input.setProperty("text", "")
            composer_input.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Return)
            self.application.processEvents()
            self.assertEqual(composer_input.property("text"), "")
            QTest.keyClick(window, Qt.Key_Return, Qt.ShiftModifier)
            self.application.processEvents()
            self.assertIn("\n", composer_input.property("text"))
            composer_input.setProperty("text", "")
            chat_page.closeSurface(2)
            self.application.processEvents()
            self.assertEqual(
                len(chat_page.property("openSurfaceTabs").toVariant()), 1
            )
            self.assertEqual(chat_page.property("surfaceIndex"), 1)
            chat_page.openSurface(3)
            for _attempt in range(30):
                self.application.processEvents()
                QTest.qWait(50)
                surface_files = chat_page.property("surfaceFiles")
                if any(
                    item["label"] == "Cliente/src/project_file.py"
                    for item in surface_files
                ):
                    break
            self.assertTrue(
                any(
                    item["label"] == "Cliente/src/project_file.py"
                    for item in surface_files
                ),
                surface_files,
            )
            chat_page.closeSurface(3)
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
            settings_page = window.findChild(QObject, "settingsPage")
            self.assertIsNotNone(settings_page)
            settings_page.setProperty("tabIndex", 2)
            self.application.processEvents()
            self.assertIsNotNone(window.findChild(QObject, "vrUltraSettingsPage"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraAgentPool"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraAgentModelPicker"))
            settings_navigation = window.findChild(QObject, "settingsNavigation")
            self.assertIsNotNone(settings_navigation)
            self.assertEqual(
                settings_navigation.property("color"),
                QColor(bridge.palette["navigationBackground"]),
            )
            window.close()
            engine.deleteLater()
            self.application.processEvents()

    def test_assistant_markdown_message_gets_t3_styling(self):
        from PySide6.QtGui import QTextFormat, QTextFrameFormat, QTextLength, QTextTable

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            bridge = self._bridge(root, initial_page="Chat VR", theme="dark_orange")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Conversa de tabela",
                "codex",
                "gpt-5.6",
                settings.root / "Cliente",
            )
            markdown = (
                "| Titulo | Caminho |\n"
                "|---|---|\n"
                "| Verba | conhecimento/verba.md |\n\n"
                "> Observação validada.\n\n"
                "---\n\n"
                "Parágrafo final com `codigo`.\n\n"
                "```python\n"
                "def exemplo():\n"
                "    return 1\n"
                "```\n"
            )
            database.add_message(conversation_id, "assistant", markdown)
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()
            try:
                self.assertEqual(
                    len(engine.rootObjects()),
                    1,
                    [warning.toString() for warning in engine._qml_warnings],
                )
                window = engine.rootObjects()[0]
                window.show()
                QTest.qWait(300)
                self.application.processEvents()
                chat_bridge.selectConversation(0)

                def find_qml_item(item, name):
                    if item.objectName() == name:
                        return item
                    for child in item.childItems():
                        found = find_qml_item(child, name)
                        if found is not None:
                            return found
                    return None

                def find_qml_items(item, name, acc):
                    if item.objectName() == name:
                        acc.append(item)
                    for child in item.childItems():
                        find_qml_items(child, name, acc)
                    return acc

                message_body = None
                segment_bodies = []
                code_card = None
                content_item = window.property("contentItem")
                for _attempt in range(30):
                    self.application.processEvents()
                    if content_item is not None:
                        message_body = find_qml_item(content_item, "messageBody")
                        segment_bodies = find_qml_items(
                            content_item, "messageSegment", []
                        )
                        code_cards = find_qml_items(content_item, "codeBlockCard", [])
                        code_card = code_cards[0] if code_cards else None
                    if (
                        message_body is not None
                        and segment_bodies
                        and code_card is not None
                    ):
                        break
                    QTest.qWait(100)
                self.assertEqual(chat_bridge.messages.rowCount(), 1)
                self.assertIsNotNone(message_body)
                self.assertEqual(len(segment_bodies), 1)
                self.assertIsNotNone(code_card)
                self.assertEqual(
                    code_card.property("code"), "def exemplo():\n    return 1"
                )
                self.assertEqual(code_card.property("language"), "python")
                self.assertEqual(code_card.property("badge"), "Py")
                segments = chat_bridge.messages.item(0)["segments"]
                self.assertEqual(
                    [segment["kind"] for segment in segments],
                    ["text", "code"],
                )
                quick_document = segment_bodies[0].property("textDocument")
                self.assertIsNotNone(quick_document)
                document = quick_document.textDocument()

                tables = []
                stack = [document.rootFrame()]
                while stack:
                    frame = stack.pop()
                    for child in frame.childFrames():
                        if isinstance(child, QTextTable):
                            tables.append(child)
                        stack.append(child)
                self.assertEqual(len(tables), 1)
                table_format = tables[0].format()
                self.assertEqual(table_format.border(), 1)
                self.assertEqual(
                    table_format.borderBrush().color().name(), "#3f3f46"
                )
                self.assertEqual(
                    table_format.borderStyle(),
                    QTextFrameFormat.BorderStyle_Solid,
                )
                self.assertEqual(
                    table_format.width().type(), QTextLength.PercentageLength
                )
                header_cell = tables[0].cellAt(0, 0).format().toTableCellFormat()
                self.assertEqual(header_cell.background().color().name(), "#26262b")

                quote_blocks = []
                rule_blocks = []
                code_blocks = []
                code_backgrounds = []
                block = document.firstBlock()
                while block.isValid():
                    block_format = block.blockFormat()
                    if block_format.hasProperty(int(QTextFormat.BlockQuoteLevel)):
                        quote_blocks.append(block_format)
                    elif block_format.hasProperty(
                        int(QTextFormat.BlockCodeLanguage)
                    ):
                        code_blocks.append(block_format)
                    elif not block.text() and block_format.hasProperty(
                        int(QTextFormat.BackgroundBrush)
                    ):
                        rule_blocks.append(block_format)
                    iterator = block.begin()
                    while not iterator.atEnd():
                        fragment = iterator.fragment()
                        char_format = fragment.charFormat()
                        if char_format.fontFixedPitch():
                            code_backgrounds.append(
                                char_format.background().color().name()
                            )
                        iterator += 1
                    block = block.next()
                self.assertEqual(len(quote_blocks), 1)
                self.assertEqual(
                    quote_blocks[0].background().color().name(), "#232327"
                )
                self.assertEqual(len(rule_blocks), 1)
                self.assertEqual(rule_blocks[0].lineHeight(), 2.0)
                self.assertIn("#26262b", code_backgrounds)
                self.assertEqual(len(code_blocks), 0)

                def find_text_edit(item):
                    if "TextEdit" in item.metaObject().className():
                        return item
                    for child in item.childItems():
                        found = find_text_edit(child)
                        if found is not None:
                            return found
                    return None

                card_body = find_text_edit(code_card)
                self.assertIsNotNone(card_body)
                self.assertTrue(code_card.property("wrapEnabled"))
                wrap_buttons = find_qml_items(content_item, "codeBlockWrap", [])
                self.assertEqual(len(wrap_buttons), 1)
                wrap_buttons[0].setProperty("checked", False)
                self.application.processEvents()
                self.assertFalse(code_card.property("wrapEnabled"))
                QTest.qWait(120)
                self.application.processEvents()

                card_quick_document = card_body.property("textDocument")
                self.assertIsNotNone(card_quick_document)
                card_document = card_quick_document.textDocument()
                keyword_colors = []
                card_block = card_document.firstBlock()
                while card_block.isValid():
                    for card_range in card_block.layout().formats():
                        keyword_colors.append(
                            card_range.format.foreground().color().name()
                        )
                    card_block = card_block.next()
                self.assertIn("#ff7ab2", keyword_colors)
            finally:
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

    def test_legacy_codex_model_is_hidden_and_migrated_to_sol(self):
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
            preferences.setValue("chat/last_provider", "codex")
            preferences.setValue("chat/last_model/codex", "gpt-5.6")
            preferences.sync()

            bridge = ChatBridge(settings, database, preferences)
            selected_model = bridge.modelItems[bridge.modelIndex]

            self.assertEqual(selected_model["value"], "gpt-5.6-sol")
            self.assertFalse(
                any(item["value"] == "gpt-5.6" for item in bridge.modelItems)
            )
            self.assertEqual(
                preferences.value("chat/last_model/codex"), "gpt-5.6-sol"
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

    def test_chat_project_name_is_saved_and_restored(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            project = settings.root / "Cliente"
            project.mkdir()
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            database.create_conversation(
                "Conversa do projeto", "codex", "gpt-5.6", project
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            bridge = ChatBridge(settings, database, preferences)
            project_index = next(
                index
                for index, item in enumerate(bridge.projectItems)
                if item["path"] == str(project)
            )

            self.assertTrue(bridge.renameProject(project_index, "  Projeto Norte  "))
            self.assertEqual(bridge.projectItems[project_index]["label"], "Projeto Norte")
            self.assertEqual(
                bridge._conversations._items[0]["projectLabel"], "Projeto Norte"
            )
            self.assertFalse(bridge.renameProject(0, "Inválido"))
            self.assertFalse(bridge.renameProject(project_index, "   "))

            restored = ChatBridge(settings, database, preferences)
            restored_item = next(
                item
                for item in restored.projectItems
                if item["path"] == str(project)
            )
            self.assertEqual(restored_item["label"], "Projeto Norte")

    def test_chat_project_can_be_removed_from_the_selector_and_added_again(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            project = settings.root / "Cliente"
            project.mkdir()
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            preferences.setValue(
                "chat/projects", json.dumps([{"path": str(project)}])
            )
            bridge = ChatBridge(settings, database, preferences)
            project_index = next(
                index
                for index, item in enumerate(bridge.projectItems)
                if item["path"] == str(project)
            )

            self.assertTrue(bridge.removeProject(project_index))
            self.assertFalse(
                any(item["path"] == str(project) for item in bridge.projectItems)
            )

            self.assertEqual(bridge._add_project_path(project), str(project))
            self.assertTrue(
                any(item["path"] == str(project) for item in bridge.projectItems)
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

    def test_vr_mode_tri_state_persists_and_cycles(self):
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
            conversation_id = bridge._orchestrator.new_conversation(
                "codex", "sol", defer_provider_start=True, vr_mode="vr"
            )
            database.update_conversation(conversation_id, title="c")
            bridge.refresh()
            target = next(
                (
                    index
                    for index, item in enumerate(bridge._conversations._items)
                    if item["conversationId"] == conversation_id
                ),
                None,
            )
            assert target is not None
            bridge.selectConversation(target)

            bridge.setVrMode("ultra")
            self.assertEqual(bridge.vrMode, "ultra")
            self.assertEqual(
                database.get_conversation(conversation_id)["vr_mode"], "ultra"
            )
            self.assertEqual(
                str(preferences.value("chat/vr_mode")), "ultra"
            )

            bridge.cycleVrMode()
            self.assertEqual(bridge.vrMode, "off")
            bridge.cycleVrMode()
            self.assertEqual(bridge.vrMode, "vr")

    def test_research_config_slots_apply_to_orchestrator(self):
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
            bridge._model_items = [
                {
                    "label": "Sol",
                    "value": "sol",
                    "key": "codex:sol",
                    "provider": "codex",
                }
            ]

            bridge.setResearchModels(["codex:sol"])
            bridge.setResearchMaxParallel(1)

            self.assertEqual(bridge.researchModelKeys, ["codex:sol"])
            self.assertEqual(bridge.researchMaxParallel, 1)
            pool = bridge._orchestrator._research_pool
            self.assertEqual(
                [(ref.provider, ref.model) for ref in pool], [("codex", "sol")]
            )
            self.assertEqual(bridge._orchestrator._research_max_parallel, 1)

    def test_code_analysis_config_is_opt_in_and_persisted(self):
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

            self.assertFalse(bridge.codeAnalysisEnabled)
            self.assertEqual(bridge.codeAnalysisRelease, "current")
            bridge.setCodeAnalysisEnabled(True)
            bridge.setCodeAnalysisRelease("2026.08.29")

            self.assertTrue(bridge.codeAnalysisEnabled)
            self.assertEqual(bridge.codeAnalysisRelease, "2026.08.29")
            self.assertEqual(
                str(preferences.value("research/code_analysis_enabled")).casefold(),
                "true",
            )
            reopened = ChatBridge(settings, database, preferences)
            self.assertTrue(reopened.codeAnalysisEnabled)
            self.assertEqual(reopened.codeAnalysisRelease, "2026.08.29")

    def test_senior_profile_unlocks_and_persists_explicit_response_mode(self):
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

            self.assertFalse(bridge.seniorProfileEnabled)
            self.assertEqual(bridge.vrResponseMode, "auto")
            bridge.setVrResponseMode("support")
            self.assertEqual(bridge.vrResponseMode, "auto")

            bridge.setSeniorProfileEnabled(True)
            bridge.setVrResponseMode("implementation")
            self.assertTrue(bridge.seniorProfileEnabled)
            self.assertEqual(bridge.vrResponseMode, "implementation")

            reopened = ChatBridge(settings, database, preferences)
            self.assertTrue(reopened.seniorProfileEnabled)
            self.assertEqual(reopened.vrResponseMode, "implementation")

            reopened.setSeniorProfileEnabled(False)
            self.assertEqual(reopened.vrResponseMode, "auto")

    def test_project_folder_browser_lists_directories_and_adds_current_path(self):
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
            folder = root / "Projetos"
            (folder / "Alpha").mkdir(parents=True)
            (folder / "beta").mkdir()
            (folder / "arquivo.txt").write_text("x", encoding="utf-8")

            bridge.browseProjectFolder(str(folder))

            self.assertEqual(bridge.projectFolderPath, str(folder.resolve()))
            self.assertEqual(
                [item["label"] for item in bridge.projectFolderItems],
                ["Alpha", "beta"],
            )
            self.assertEqual(bridge.addCurrentProjectFolder(), str(folder.resolve()))
            self.assertTrue(
                any(item["path"] == str(folder.resolve()) for item in bridge.projectItems)
            )

    def test_pesquisa_command_requires_vr(self):
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
            bridge.setVrMode("off")

            bridge.sendMessage("/pesquisa onde grava o SPED")

            self.assertIn("Ative o VR", bridge._status_text)
            self.assertEqual(len(database.list_conversations()), 0)

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
                ["auto", "low", "high", "max"],
            )
            self.assertEqual(bridge.effortItems[bridge.effortIndex]["value"], "low")
            self.assertEqual(bridge.serviceTierItems, [])
            bridge.setEffort(2)
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
            self.assertEqual(bridge.activitySteps, [])
            self.assertEqual(
                [item["kind"] for item in bridge.activityItems],
                ["plan_created", "agent_completed"],
            )
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

    def test_chat_bridge_animates_streamed_text_instead_of_revealing_it_at_once(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Streaming", "codex", "gpt-5.6", settings.root
            )
            database.add_message(conversation_id, "user", "Explique o fluxo.")
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            response = (
                "A resposta é apresentada progressivamente para preservar o "
                "acompanhamento visual durante a execução."
            )

            bridge._on_runtime_event(
                RuntimeEvent(conversation_id, "assistant_delta", response)
            )

            streaming = bridge.messages.item(bridge.messages.rowCount() - 1)
            self.assertEqual(streaming["role"], "assistant")
            self.assertEqual(streaming["displayContent"], "")
            bridge._flush_stream_step()
            first_frame = bridge.messages.item(bridge.messages.rowCount() - 1)
            self.assertGreater(len(first_frame["displayContent"]), 0)
            self.assertLess(len(first_frame["displayContent"]), len(response))
            while bridge._stream_pending_text:
                bridge._flush_stream_step()
            final_frame = bridge.messages.item(bridge.messages.rowCount() - 1)
            self.assertEqual(final_frame["displayContent"], response)
            bridge._reset_stream_state()

    def test_chat_bridge_exposes_tool_calls_as_one_expandable_lifecycle_item(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Ferramentas", "codex", "gpt-5.6", settings.root
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            bridge._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Executando terminal",
                    {
                        "lifecycle": "started",
                        "item": {
                            "id": "tool-1",
                            "name": "Terminal",
                            "command": "rg -n fonte VRProject",
                        },
                    },
                )
            )
            bridge._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Terminal concluído",
                    {
                        "lifecycle": "completed",
                        "success": True,
                        "output": "3 resultados",
                        "item": {"id": "tool-1", "name": "Terminal"},
                    },
                )
            )
            bridge._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Read",
                    {
                        "type": "tool_use",
                        "id": "tool-2",
                        "name": "Read",
                        "input": {"path": "VRProject/manual.md"},
                    },
                )
            )

            self.assertEqual(len(bridge.activityItems), 2)
            item = bridge.activityItems[0]
            self.assertEqual(item["kind"], "tool")
            self.assertEqual(item["state"], "completed")
            self.assertIn("3 resultados", item["detail"])
            self.assertIn("VRProject/manual.md", bridge.activityItems[1]["detail"])

    def test_chat_bridge_processes_background_turn_events_without_blocking_composer(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            selected_id = database.create_conversation(
                "Selecionada", "codex", "gpt-5.6", settings.root
            )
            database.add_message(selected_id, "user", "Mensagem na selecionada.")
            background_id = database.create_conversation(
                "Segundo plano", "codex", "gpt-5.6", settings.root
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            selected_index = next(
                index
                for index, item in enumerate(bridge._conversations._items)
                if item["conversationId"] == selected_id
            )
            bridge.selectConversation(selected_index)
            self.assertEqual(bridge.selectedTitle, "Selecionada")
            database.update_conversation(background_id, status="running")
            bridge.refresh()
            approvals = []
            bridge.approvalRequested.connect(
                lambda payload: approvals.append(dict(payload))
            )

            bridge._on_runtime_event(
                RuntimeEvent(
                    background_id, "approval_requested", "", {"request_id": "req-1"}
                )
            )

            self.assertEqual(
                bridge._approval_request.get("conversation_id"), background_id
            )
            self.assertEqual(approvals[-1].get("request_id"), "req-1")
            self.assertEqual(bridge.statusText, "Pronto")
            self.assertFalse(bridge.turnRunning)

            database.update_conversation(background_id, status="idle")
            bridge._on_runtime_event(RuntimeEvent(background_id, "turn_completed"))

            self.assertFalse(bridge.turnRunning)
            self.assertEqual(bridge.statusText, "Pronto")
            self.assertEqual(
                [
                    bridge.messages.item(index)["role"]
                    for index in range(bridge.messages.rowCount())
                ],
                ["user"],
            )

    def test_switching_conversation_discards_visual_stream_and_keeps_other_composer_free(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            first_id = database.create_conversation(
                "Conversa A", "codex", "gpt-5.6", settings.root
            )
            second_id = database.create_conversation(
                "Conversa B", "codex", "gpt-5.6", settings.root
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            first_index = next(
                index
                for index, item in enumerate(bridge._conversations._items)
                if item["conversationId"] == first_id
            )
            second_index = next(
                index
                for index, item in enumerate(bridge._conversations._items)
                if item["conversationId"] == second_id
            )
            bridge.selectConversation(first_index)
            bridge._active_turns.add(first_id)
            bridge._sync_selected_turn_state()
            bridge._on_runtime_event(
                RuntimeEvent(first_id, "assistant_delta", "SEGREDO-DA-CONVERSA-A")
            )

            bridge.selectConversation(second_index)

            self.assertEqual(bridge.selectedTitle, "Conversa B")
            self.assertFalse(bridge.turnRunning)
            self.assertNotIn(
                "SEGREDO-DA-CONVERSA-A",
                " ".join(
                    str(item.get("content") or "")
                    for item in bridge.messages._items
                ),
            )
            with patch.object(bridge._orchestrator, "send") as send:
                bridge.sendMessage("Mensagem independente")
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0], second_id)

    def test_non_codex_image_attachment_is_sent_as_visible_file_reference(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            image = settings.root / "evidencia.png"
            image.write_bytes(b"png")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Claude", "claude", "sonnet", settings.root
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            index = next(
                index
                for index, item in enumerate(bridge._conversations._items)
                if item["conversationId"] == conversation_id
            )
            bridge.selectConversation(index)
            bridge._attachments = [{"name": image.name, "path": str(image)}]

            with patch.object(bridge._orchestrator, "send") as send:
                bridge.sendMessage("Analise a evidência")

            self.assertIn(f'@"{image}"', send.call_args.args[1])
            self.assertEqual(send.call_args.kwargs["image_paths"], [str(image)])

    def test_chat_file_suggestions_use_background_cache_and_reemit_updates(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            (settings.root / "Notas Fiscal.md").write_text("# Notas", encoding="utf-8")
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
            updates = []
            bridge.fileSuggestionsChanged.connect(
                lambda: updates.append(bridge.fileSuggestions("fiscal"))
            )

            self.assertEqual(bridge.fileSuggestions("fiscal"), [])
            for _attempt in range(60):
                self.application.processEvents()
                QTest.qWait(25)
                if bridge.fileSuggestions("fiscal"):
                    break

            results = bridge.fileSuggestions("fiscal")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["label"], "Notas Fiscal.md")
            self.assertTrue(results[0]["path"].endswith("Notas Fiscal.md"))
            self.assertTrue(updates)
            self.assertEqual(updates[-1], results)

    def test_studio_bridge_loads_pages_lazily_and_tracks_video_descendants(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = StudioBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )

            self.assertEqual(bridge._loaded_pages, set())
            self.assertEqual(bridge.videoModel.rowCount(), 0)
            bridge._all_video_items = [
                {
                    "nodeId": "root",
                    "ancestorIds": [],
                    "expandable": True,
                },
                {
                    "nodeId": "root:module",
                    "ancestorIds": ["root"],
                    "expandable": True,
                },
                {
                    "nodeId": "root:module:folder",
                    "ancestorIds": ["root", "root:module"],
                    "expandable": True,
                },
                {
                    "nodeId": "video:1",
                    "ancestorIds": ["root", "root:module", "root:module:folder"],
                    "expandable": False,
                },
            ]

            self.assertEqual(
                bridge.videoDescendantNodeIds("root"),
                ["root:module", "root:module:folder"],
            )

    def test_bridge_shutdown_is_idempotent_and_closes_orchestrator(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            chat = ChatBridge(settings, database)
            studio = StudioBridge(settings, database)
            with patch.object(chat._orchestrator, "close") as close_orchestrator:
                studio.close()
                studio.close()
                chat.close()
                chat.close()
            close_orchestrator.assert_called_once_with()

    def test_settings_and_logs_do_not_expose_configured_passwords(self):
        with TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "MOVIDESK_PASSWORD": "movidesk-super-secret",
                "ENDOO_PASSWORD": "endoo-super-secret",
            },
            clear=False,
        ):
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            studio = StudioBridge(settings, database)
            studio._refresh_settings()
            studio._append_log(
                "credenciais movidesk-super-secret e endoo-super-secret"
            )

            self.assertEqual(studio.settingsValues["movideskPassword"], "")
            self.assertEqual(studio.settingsValues["endooPassword"], "")
            self.assertTrue(studio.settingsValues["movideskPasswordConfigured"])
            self.assertTrue(studio.settingsValues["endooPasswordConfigured"])
            self.assertNotIn("movidesk-super-secret", studio.logText)
            self.assertNotIn("endoo-super-secret", studio.logText)
            self.assertIn("[REDACTED]", studio.logText)

    def test_review_actions_target_preview_unless_selection_is_explicit(self):
        review_qml = (
            MAIN_QML.parent / "pages" / "ReviewPage.qml"
        ).read_text(encoding="utf-8")
        self.assertIn("applyDecision(action, [studio.currentReviewId])", review_qml)
        self.assertIn("studio.reviewSelectionCount > 0", review_qml)

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = StudioBridge(settings, database)
            bridge._review.replace(
                [
                    {"reviewId": 101, "title": "Revisão A"},
                    {"reviewId": 202, "title": "Revisão B"},
                ]
            )
            bridge.selectReview(1)
            bridge.setReviewSelected(101, True)

            self.assertEqual(bridge.currentReviewId, 202)
            self.assertEqual(bridge.selectedReviewIds, [101])
            bridge.searchReviewsAdvanced("", {})
            self.assertEqual(bridge.reviewSelectionCount, 0)

    def test_restoring_archive_refreshes_chat_bridge_through_shared_signal(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Arquivada", "codex", "gpt-5.6", settings.root
            )
            chat = ChatBridge(settings, database)
            studio = StudioBridge(
                settings,
                database,
                chat_orchestrator=chat._orchestrator,
            )
            studio.conversationRestored.connect(chat.refresh)
            chat._orchestrator.archive(conversation_id)
            chat.refresh()
            self.assertNotIn(
                conversation_id,
                [item["conversationId"] for item in chat._all_conversations],
            )

            studio.restoreArchived(conversation_id)

            self.assertIn(
                conversation_id,
                [item["conversationId"] for item in chat._all_conversations],
            )
            studio.close()
            chat.close()

    def test_qml_chat_actions_keep_archive_only_and_enable_safe_source_links(self):
        chat_qml = (
            MAIN_QML.parent / "pages" / "ChatPreview.qml"
        ).read_text(encoding="utf-8")
        knowledge_qml = (
            MAIN_QML.parent / "pages" / "KnowledgePage.qml"
        ).read_text(encoding="utf-8")
        settings_qml = (
            MAIN_QML.parent / "pages" / "SettingsPage.qml"
        ).read_text(encoding="utf-8")

        self.assertIn("Arquivar conversa", chat_qml)
        self.assertNotIn("Mover para lixeira", chat_qml)
        self.assertIn("Keys.onReturnPressed", chat_qml)
        self.assertIn("Keys.onEnterPressed", chat_qml)
        self.assertIn("onLinkActivated", chat_qml)
        self.assertIn("onLinkActivated", knowledge_qml)
        self.assertIn("Digite EXCLUIR", settings_qml)
        self.assertIn('objectName: "conversationSidebarToggle"', chat_qml)
        self.assertNotIn(
            "conversationSidebar.x + conversationSidebar.width", chat_qml
        )

    def test_qml_motion_system_keeps_chat_transitions_consistent_and_accessible(self):
        qml_root = MAIN_QML.parent
        theme_qml = (qml_root / "theme" / "Theme.qml").read_text(encoding="utf-8")
        main_qml = MAIN_QML.read_text(encoding="utf-8")
        chat_qml = (qml_root / "pages" / "ChatPreview.qml").read_text(
            encoding="utf-8"
        )
        components = qml_root / "components"

        for token in (
            "pressDuration",
            "motionDuration",
            "pageDuration",
            "motionDistance",
        ):
            self.assertIn(token, theme_qml)

        self.assertIn("Behavior on opacity", main_qml)
        self.assertIn("Theme.pageDuration", main_qml)
        self.assertIn("enabled: !frontend.reduceMotion", main_qml)
        self.assertIn("conversationSidebarWidth", chat_qml)
        self.assertIn("surfacePanelWidth", chat_qml)
        self.assertIn('objectName: "surfaceContentStack"', chat_qml)
        self.assertIn("surfaceSwitch", chat_qml)
        self.assertIn("root.displayedSurfaceIndex = root.surfaceIndex", chat_qml)

        for component_name in (
            "VrButton.qml",
            "VrIconButton.qml",
            "VrModelPicker.qml",
            "VrReasoningPicker.qml",
            "VrPermissionPicker.qml",
            "VrContextButton.qml",
        ):
            source = (components / component_name).read_text(encoding="utf-8")
            self.assertIn("Behavior on scale", source, component_name)
            self.assertIn("!frontend.reduceMotion", source, component_name)

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
                    "2026-08-23T12:00:00+00:00",
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
                RuntimeEvent(
                    conversation_id,
                    "turn_completed",
                    "Pronto",
                    created_at="2026-08-23T12:01:05+00:00",
                ),
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
            self.assertEqual(bridge.activityElapsedLabel, "1m 05s")

    def test_markdown_display_repairs_glued_sentences_without_touching_code(self):
        source = "Versão pronta.Próximo passo: `arquivo.MD`."

        self.assertEqual(
            markdown_for_display(source),
            "Versão pronta. Próximo passo: `arquivo.MD`.",
        )

    def test_segments_for_display_splits_fenced_code_cards(self):
        from vrsoft_extractor.mary.frontend.chat import segments_for_display

        segments = segments_for_display(
            "Intro com `codigo`.\n\n```python\nprint(1)\n```\n\nFim."
        )
        self.assertEqual(
            [segment["kind"] for segment in segments],
            ["text", "code", "text"],
        )
        self.assertEqual(segments[1]["language"], "python")
        self.assertEqual(segments[1]["badge"], "Py")
        self.assertEqual(segments[1]["content"], "print(1)")
        self.assertIn("Fim.", segments[2]["content"])
        self.assertEqual(segments_for_display("Resposta sem fence."), [])
        self.assertEqual(segments_for_display(""), [])

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

    def test_chat_file_surface_loads_project_files_without_a_search_term(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            expected = settings.root / "src" / "main.py"
            expected.parent.mkdir()
            expected.write_text("print('VR')", encoding="utf-8")
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
            updates: list[bool] = []
            bridge.fileSuggestionsChanged.connect(lambda: updates.append(True))

            self.assertEqual(bridge.fileSuggestions(""), [])
            for _attempt in range(30):
                self.application.processEvents()
                QTest.qWait(50)
                values = bridge.fileSuggestions("")
                if values:
                    break

            self.assertTrue(updates)
            selected = next(item for item in values if item["label"] == "src/main.py")
            self.assertEqual(Path(selected["path"]), expected)

    def test_chat_drop_stages_existing_local_files_without_picker(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            image = settings.root / "evidencia.png"
            image.write_bytes(b"png")
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

            added = bridge.addDroppedAttachments(
                [QUrl.fromLocalFile(str(image)), QUrl.fromLocalFile(str(image))]
            )

            self.assertEqual(added, 1)
            self.assertEqual(bridge.attachments, [{"name": image.name, "path": str(image)}])

    def test_ultra_agent_pool_is_independent_from_the_orchestrator_selection(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
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

            bridge._model_items = [
                {"key": "codex:a", "provider": "codex", "value": "a", "label": "A"},
                {"key": "claude:b", "provider": "claude", "value": "b", "label": "B"},
                {"key": "opencode:c", "provider": "opencode", "value": "c", "label": "C"},
                {"key": "codex:d", "provider": "codex", "value": "d", "label": "D"},
            ]

            with patch.object(bridge, "refresh"):
                bridge.setModel(1)
            bridge.setResearchModels(
                ["codex:a", "opencode:c", "codex:d", "claude:b", "codex:a"]
            )

            self.assertEqual((bridge._provider, bridge._model), ("claude", "b"))
            self.assertEqual(bridge.researchModelKeys, ["codex:a"])

    def test_model_picker_keeps_provider_filters_without_hover_dialogs(self):
        picker_qml = (
            MAIN_QML.parent / "components" / "VrModelPicker.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('property string providerFilter: "all"', picker_qml)
        self.assertIn('{key: "favorites"', picker_qml)
        self.assertIn('{key: "codex"', picker_qml)
        self.assertNotIn("ToolTip.visible", picker_qml)
        self.assertIn("CloseOnPressOutsideParent", picker_qml)

        chat_qml = (
            MAIN_QML.parent / "pages" / "ChatPreview.qml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("createLinearGradient", chat_qml)

    def test_videos_page_starts_with_libraries_collapsed(self):
        videos_qml = (
            MAIN_QML.parent / "pages" / "VideosPage.qml"
        ).read_text(encoding="utf-8")
        self.assertIn("function ensureInitialCollapse", videos_qml)
        self.assertIn("onCountChanged: root.ensureInitialCollapse()", videos_qml)

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = self._bridge(root, initial_page="Vídeos")
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            studio_bridge = StudioBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            # Keep the lazy page load from racing the real async inventory
            # refresh; the QML side must collapse on the model change itself.
            studio_bridge._loaded_pages.add(5)
            engine = create_engine(bridge, chat_bridge, studio_bridge)
            self.application.processEvents()
            self.assertEqual(
                len(engine.rootObjects()),
                1,
                [warning.toString() for warning in engine._qml_warnings],
            )
            studio_bridge._all_video_items = [
                {
                    "nodeId": "root",
                    "ancestorIds": [],
                    "expandable": True,
                    "title": "Cursos",
                    "depth": 0,
                },
                {
                    "nodeId": "root:library",
                    "ancestorIds": ["root"],
                    "expandable": True,
                    "title": "Biblioteca",
                    "depth": 1,
                },
                {
                    "nodeId": "video:1",
                    "ancestorIds": ["root", "root:library"],
                    "expandable": False,
                    "title": "Aula 01",
                    "depth": 2,
                },
            ]
            studio_bridge._apply_video_filters()
            studio_bridge.videosChanged.emit()
            self.application.processEvents()

            window = engine.rootObjects()[0]
            page = window.findChild(QObject, "videosPage")
            self.assertIsNotNone(page)
            collapsed_value = page.property("collapsedNodeIds")
            collapsed = list(
                collapsed_value.toVariant()
                if hasattr(collapsed_value, "toVariant")
                else (collapsed_value or [])
            )
            self.assertIn("root", collapsed)
            self.assertIn("root:library", collapsed)
            self.assertNotIn("video:1", collapsed)

    def test_application_entrypoint_dispatches_qml_by_default(self):
        from vrsoft_extractor.mary import ui

        with patch(
            "vrsoft_extractor.mary.frontend.app.main", return_value=23
        ) as qml_main:
            result = ui.main(["--project-dir", "demo"])

        self.assertEqual(result, 23)
        qml_main.assert_called_once_with(["--project-dir", "demo"])

    def test_settings_tabs_use_canonical_tab_bar_with_accent_token(self):
        from vrsoft_extractor.mary.frontend import app as app_module

        components_dir = MAIN_QML.parent / "components"
        tab_bar_qml = (components_dir / "VrTabBar.qml").read_text(encoding="utf-8")
        button_qml = (components_dir / "VrButton.qml").read_text(encoding="utf-8")
        settings_qml = (
            MAIN_QML.parent / "pages" / "SettingsPage.qml"
        ).read_text(encoding="utf-8")
        app_source = Path(app_module.__file__).read_text(encoding="utf-8")

        self.assertIn("Accessible.role: Accessible.PageTab", tab_bar_qml)
        self.assertIn("Keys.onLeftPressed", tab_bar_qml)
        self.assertIn("Keys.onRightPressed", tab_bar_qml)
        self.assertIn("frontend.palette.accentSoft", tab_bar_qml)
        self.assertNotIn('"primary" : "ghost"', settings_qml)
        self.assertNotIn("variant: root.tabIndex === index", settings_qml)
        self.assertIn("objectName: \"settingsTabBar\"", settings_qml)
        self.assertIn("variant: \"danger\"", settings_qml)
        self.assertIn("enabled: deleteConfirmField.text === \"EXCLUIR\"", settings_qml)
        self.assertIn("Escala da interface", settings_qml)
        self.assertIn("objectName: \"uiScaleCombo\"", settings_qml)
        self.assertIn("VrPageColumn {", settings_qml)
        page_column_qml = (
            components_dir / "VrPageColumn.qml"
        ).read_text(encoding="utf-8")
        self.assertIn("property int maximumWidth: 1120", page_column_qml)
        main_qml = MAIN_QML.read_text(encoding="utf-8")
        self.assertIn("Screen.desktopAvailableWidth", main_qml)
        self.assertIn("Screen.desktopAvailableHeight", main_qml)
        self.assertIn("chatVisited", main_qml)
        hub_qml = (
            MAIN_QML.parent / "pages" / "SettingsHub.qml"
        ).read_text(encoding="utf-8")
        self.assertIn("visitedPages", hub_qml)
        self.assertNotIn("Repeater {\n                model: root.hubPages", hub_qml)
        for page in (
            "DashboardPreview.qml",
            "KnowledgePage.qml",
            "ReviewPage.qml",
            "VideosPage.qml",
            "LogsPage.qml",
            "SyncPage.qml",
        ):
            page_qml = (MAIN_QML.parent / "pages" / page).read_text(
                encoding="utf-8"
            )
            # Data pages fill the window; only Configurações caps the width.
            self.assertNotIn("VrPageColumn", page_qml, page)
            self.assertIn("anchors.fill: parent", page_qml, page)
        self.assertIn("apply_ui_scale_environment(preferences)", app_source)
        self.assertIn("control.variant === \"danger\"", button_qml)

    def test_settings_page_loads_with_tab_bar_in_engine(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = self._bridge(root, initial_page="Configurações")
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()

            self.assertEqual(
                len(engine.rootObjects()),
                1,
                [warning.toString() for warning in engine._qml_warnings],
            )
            window = engine.rootObjects()[0]
            tab_bar = window.findChild(QObject, "settingsTabBar")
            self.assertIsNotNone(tab_bar)
            self.assertEqual(tab_bar.property("count"), 5)
            self.assertEqual(tab_bar.property("currentIndex"), 0)
            ui_scale_combo = window.findChild(QObject, "uiScaleCombo")
            self.assertIsNotNone(ui_scale_combo)
            scale_preview = window.findChild(QObject, "uiScalePreviewText")
            self.assertIsNotNone(scale_preview)
            scale_description = window.findChild(QObject, "uiScaleDescription")
            self.assertIsNotNone(scale_description)
            self.assertIn("Automática ativa", scale_description.property("text"))

            window.setProperty("width", 1120)
            window.setProperty("height", 700)
            self.application.processEvents()
            small_window_pixel_size = scale_preview.property("font").pixelSize()
            window.setProperty("width", 3840)
            window.setProperty("height", 2160)
            self.application.processEvents()
            self.assertGreater(
                scale_preview.property("font").pixelSize(), small_window_pixel_size
            )

            ui_scale_combo.activated.emit(1)
            self.application.processEvents()
            manual_100_pixel_size = scale_preview.property("font").pixelSize()
            ui_scale_combo.activated.emit(6)
            self.application.processEvents()
            self.assertEqual(bridge.uiScale, "105")
            self.assertGreater(
                scale_preview.property("font").pixelSize(), manual_100_pixel_size
            )

            tab_bar.activate(2)
            self.application.processEvents()
            self.assertEqual(tab_bar.property("currentIndex"), 2)
            self.assertEqual(bridge.currentPage, 7)

            tab_bar.activate(99)
            self.application.processEvents()
            self.assertEqual(tab_bar.property("currentIndex"), 2)

            tab_bar.activate(0)
            self.application.processEvents()
            quick_window = tab_bar.window()
            QTest.keyClick(quick_window, Qt.Key_Right)
            self.application.processEvents()
            self.assertEqual(tab_bar.property("currentIndex"), 1)
            QTest.keyClick(quick_window, Qt.Key_Right)
            self.application.processEvents()
            self.assertEqual(tab_bar.property("currentIndex"), 2)
            QTest.keyClick(quick_window, Qt.Key_Left)
            self.application.processEvents()
            self.assertEqual(tab_bar.property("currentIndex"), 1)
            QTest.keyClick(quick_window, Qt.Key_Return)
            self.application.processEvents()
            self.assertEqual(tab_bar.property("currentIndex"), 1)

    def test_all_pages_load_in_engine_with_centered_page_column(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = self._bridge(root, initial_page="Dashboard")
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            studio_bridge = StudioBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            engine = create_engine(bridge, chat_bridge, studio_bridge)
            self.application.processEvents()

            self.assertEqual(
                len(engine.rootObjects()),
                1,
                [warning.toString() for warning in engine._qml_warnings],
            )
            for page_index in (0, 2, 3, 4, 5, 6, 7):
                bridge.setCurrentPage(page_index)
                self.application.processEvents()
                self.assertEqual(bridge.currentPage, page_index)

            self.assertEqual(
                [
                    warning.toString()
                    for warning in engine._qml_warnings
                    if "VrPageColumn" in warning.toString()
                ],
                [],
            )



if __name__ == "__main__":
    unittest.main()

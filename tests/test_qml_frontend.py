import pytest

import json
import os
import threading
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QPoint, QPointF, QSettings, Qt, QUrl, QMetaObject
from PySide6.QtGui import QColor, QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary import brand
from vrsoft_extractor.mary.code_processing_audit import CodeProcessingAudit
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.frontend.app import MAIN_QML, create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge, NAVIGATION_ITEMS
from vrsoft_extractor.mary.frontend.bridges import codeadmin
from vrsoft_extractor.mary.frontend.chat import (
    CODE_PROCESSING_HARDWARE,
    DEFAULT_ERP_JAR_SOURCE_PATH,
    ChatBridge,
    markdown_for_display,
)
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.settings_service import diagnostic_text

pytestmark = pytest.mark.qml


class QmlFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        # ChatBridge owns timers, provider reader threads and optional local
        # processing workers.  Tests used to rely on QObject/Python garbage
        # collection, which is non-deterministic and can leave native Qt work
        # alive after a TemporaryDirectory has been removed on Windows.
        self._chat_bridges: list[ChatBridge] = []
        original_init = ChatBridge.__init__

        def tracked_init(instance, *args, **kwargs):
            original_init(instance, *args, **kwargs)
            self._chat_bridges.append(instance)

        self._chat_bridge_init_patch = patch.object(
            ChatBridge,
            "__init__",
            tracked_init,
        )
        self._chat_bridge_init_patch.start()

    def tearDown(self):
        self._chat_bridge_init_patch.stop()
        for bridge in reversed(self._chat_bridges):
            bridge.close()
        self.application.processEvents()

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

    def _import_release(
        self,
        settings: MarySettings,
        release_id: str,
        marker: bytes = b"release",
    ) -> None:
        jar = settings.root / "ERP" / "releases" / release_id / "jars" / "ERP.jar"
        jar.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
            archive.writestr("br/vr/App.class", marker)
        ErpReleaseCatalog(settings.root, expected_jar_count=1).import_release(release_id)

    def test_application_font_resolves_real_semibold_on_windows(self):
        import sys
        from PySide6.QtGui import QFont, QFontInfo
        from vrsoft_extractor.mary.frontend.app import _apply_application_font

        if sys.platform != "win32" or not Path(r"C:\Windows\Fonts\seguisb.ttf").exists():
            self.skipTest("Windows Segoe UI Semibold is unavailable")
        previous_font = self.application.font()
        try:
            _apply_application_font(self.application)
            font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
            resolved = QFontInfo(font)
            self.assertEqual(resolved.styleName(), "Semibold")
            self.assertEqual(resolved.weight(), QFont.Weight.DemiBold)
        finally:
            self.application.setFont(previous_font)

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

            bridge.setTheme("light")
            bridge.setTheme("dark_orange")
            bridge.toggleNavigation()
            bridge.setTypography("Arial", 16, "Cascadia Code", 13, False)
            bridge.setBrowserZoom("125")
            bridge.setBrowserViewport("390x844")
            bridge.setBrowserAppearance("dark")
            bridge.setBrowserAgentAccess(False)
            bridge.setBrowserAutoShowPreview(False)

            self.assertEqual(bridge.themeId, "dark_orange")
            self.assertEqual(preferences.value("appearance/theme"), "dark_orange")
            self.assertIsNotNone(preferences.value("appearance/nav_collapsed"))
            self.assertEqual(bridge.interfaceFontFamily, "Arial")
            self.assertEqual(bridge.interfaceFontSize, 16)
            self.assertEqual(bridge.monospaceFontFamily, "Cascadia Code")
            self.assertFalse(bridge.wordWrap)
            self.assertEqual(bridge.browserZoom, "125")
            self.assertEqual(bridge.browserViewport, "390x844")
            self.assertEqual(bridge.browserAppearance, "dark")
            self.assertFalse(bridge.browserAgentAccess)
            self.assertFalse(bridge.browserAutoShowPreview)

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
                int(preferences.value("appearance/ui_scale_version")), FrontendBridge.UI_SCALE_PREFERENCE_VERSION
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
            self.assertEqual(window.property("minimumWidth"), 390)
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
            chat_bridge.startNewChat()
            self.application.processEvents()
            item_agy = {
                "provider": "antigravity",
                "value": "gemini-3.8-flash-high",
                "displayName": "Gemini 3.8 Flash (High)",
                "key": "antigravity:gemini-3.8-flash-high",
            }
            chat_bridge._model_items.append(item_agy)
            chat_bridge.setModel(len(chat_bridge._model_items) - 1)
            self.application.processEvents()
            self.assertFalse(chat_bridge.supportsReasoning)
            self.assertFalse(reasoning_picker.property("visible"))
            chat_bridge.setModel(0)
            self.application.processEvents()
            self.assertTrue(chat_bridge.supportsReasoning)
            self.assertTrue(reasoning_picker.property("visible"))
            chat_bridge.selectConversation(0)
            self.application.processEvents()
            self.assertIsNotNone(window.findChild(QObject, "contextUsageButton"))
            self.assertIsNotNone(window.findChild(QObject, "contextUsagePopup"))
            composer_input = window.findChild(QObject, "chatComposerInput")
            self.assertIsNotNone(composer_input)
            self.assertIsNotNone(window.findChild(QObject, "chatAttachButton"))
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
            profiles = chat_page.property("expertProfiles").toVariant()
            self.assertEqual(profiles[0]["key"], "adaptive")
            self.assertEqual(profiles[0]["label"], "Adaptativa")
            self.assertEqual(profiles[0]["icon"], "expertSenior")
            chat_bridge.setVrMode("vr")
            self.application.processEvents()
            for profile_key, response_mode in (
                ("adaptive", "auto"),
                ("training", "training"),
                ("support", "support"),
                ("implementation", "implementation"),
            ):
                chat_page.activateExpertProfile(profile_key)
                self.assertTrue(chat_bridge.expertProfileEnabled)
                self.assertEqual(chat_bridge.vrResponseMode, response_mode)
                self.assertTrue(chat_page.expertProfileSelected(profile_key))
                self.assertEqual(
                    [
                        item["key"]
                        for item in profiles
                        if chat_page.expertProfileSelected(item["key"])
                    ],
                    [profile_key],
                )
                chat_page.activateExpertProfile(profile_key)
                self.assertFalse(chat_bridge.expertProfileEnabled)
                self.assertEqual(chat_bridge.vrResponseMode, "auto")
                self.assertFalse(
                    any(chat_page.expertProfileSelected(item["key"]) for item in profiles)
                )
            chat_bridge.setExpertProfileEnabled(True)
            chat_bridge.setVrResponseMode("support")
            chat_bridge.setVrMode("off")
            QTest.qWait(300)
            self.application.processEvents()
            expert_profile_strip = window.findChild(QObject, "expertProfileStrip")
            self.assertIsNotNone(expert_profile_strip)
            self.assertFalse(expert_profile_strip.property("visible"))
            self.assertFalse(expert_profile_strip.property("enabled"))
            self.assertTrue(chat_bridge.expertProfileEnabled)
            self.assertFalse(chat_page.expertProfileSelected("support"))
            chat_page.activateExpertProfile("adaptive")
            self.assertTrue(chat_bridge.expertProfileEnabled)
            self.assertEqual(chat_bridge.vrResponseMode, "support")
            chat_bridge.setVrMode("vr")
            self.assertTrue(chat_page.expertProfileSelected("support"))
            chat_bridge.setExpertProfileEnabled(False)
            self.assertTrue(chat_page.activateProjectSource("local"))
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
            self.assertTrue(chat_page.clickProjectSelectorItem(project_index))
            self.application.processEvents()
            self.assertEqual(chat_bridge.currentProjectIndex, project_index)
            self.assertFalse(project_selector_menu.property("visible"))
            chat_page.openProjectSelectorMenu()
            self.application.processEvents()
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
            for _attempt in range(40):
                self.application.processEvents()
                if window.findChild(QObject, "vrUltraSettingsPage") is not None:
                    break
                QTest.qWait(10)
            self.assertIsNotNone(window.findChild(QObject, "vrUltraSettingsPage"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraSettingsScroll"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraAgentPool"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraAgentModelPicker"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraExpertProfileCard"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraCodeAnalysisCard"))

            manage_apps_btn = window.findChild(QObject, "vrUltraManageAppsButton")
            self.assertIsNotNone(manage_apps_btn)
            QMetaObject.invokeMethod(manage_apps_btn, "click")
            for _attempt in range(40):
                self.application.processEvents()
                if window.findChild(QObject, "appsSettingsPage") is not None:
                    break
                QTest.qWait(10)
            self.assertEqual(settings_page.property("tabIndex"), 3)
            self.assertEqual(window.findChild(QObject, "settingsTabBar").property("currentIndex"), 3)
            self.assertIsNotNone(window.findChild(QObject, "appsSettingsPage"))
            self.assertIsNotNone(window.findChild(QObject, "appsCatalogView"))
            self.assertIsNotNone(window.findChild(QObject, "appSelector"))
            self.assertIsNotNone(window.findChild(QObject, "appsImportCard"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraJarDirectoryCard"))
            self.assertIsNotNone(window.findChild(QObject, "exportDecompiledCodeButton"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraJarDirectoryPicker"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraJarScopePicker"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraSingleJarRow"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraSingleJarPath"))
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraSelectSingleJarButton")
            )
            self.assertIsNotNone(window.findChild(QObject, "vrUltraReleaseIdField"))
            self.assertIsNotNone(window.findChild(QObject, "vrUltraAddReleaseButton"))
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraReleaseSnapshotStatus")
            )
            self.assertIsNotNone(window.findChild(QObject, "vrUltraCodeProcessingCard"))
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingProgress")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingProgressLabel")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingCurrentBatch")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingTelemetry")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingEta")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingHeapPicker")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingTimeoutPicker")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingCpuPicker")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingDiskPicker")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingWindowPicker")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCodeProcessingRetryPicker")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraStartCodeProcessing")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraPauseCodeProcessing")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraCancelCodeProcessing")
            )
            self.assertIsNotNone(
                window.findChild(QObject, "vrUltraRetryCodeProcessing")
            )
            settings_navigation = window.findChild(QObject, "settingsNavigation")
            self.assertIsNotNone(settings_navigation)
            self.assertEqual(
                settings_navigation.property("color"),
                QColor(bridge.palette["navigationBackground"]),
            )
            window.close()
            engine.deleteLater()
            self.application.processEvents()

    def test_composer_pickers_flip_up_and_stay_inside_the_window(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            bridge = self._bridge(root, initial_page="Chat VR")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            provider_labels = {"codex": "Codex", "opencode": "OpenCode"}
            chat_bridge._model_items = [
                {
                    "provider": provider,
                    "value": value,
                    "displayName": name,
                    "label": name,
                    "key": f"{provider}:{value}",
                    "providerLabel": provider_labels[provider],
                }
                for provider, value, name in (
                    ("opencode", "deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
                    ("codex", "gpt-6-astra", "GPT-6-Astra"),
                )
            ]
            chat_bridge._favorite_model_keys = {
                "opencode:deepseek-v4.1-flash",
                "codex:gpt-6-astra",
            }
            with patch.object(chat_bridge, "refreshModels"):
                engine = create_engine(bridge, chat_bridge)
                self.application.processEvents()
                window = engine.rootObjects()[0]
                pickers = (
                    ("chatModelPicker", "modelPickerPopup"),
                    ("chatReasoningPicker", "reasoningPickerPopup"),
                    ("chatPermissionPicker", "permissionPickerPopup"),
                )
                # T3 relies on the Base UI positioner: popups prefer opening
                # below, flip up when they do not fit, and cap their height to
                # the available side so they never leave the viewport.
                for height, must_flip, must_stay_below in (
                    (1000, set(), {name for _, name in pickers}),
                    (700, {"modelPickerPopup", "reasoningPickerPopup"}, set()),
                    (500, {name for _, name in pickers}, set()),
                ):
                    window.setWidth(700)
                    window.setHeight(height)
                    QTest.qWait(120)
                    for picker_name, popup_name in pickers:
                        picker = window.findChild(QObject, picker_name)
                        picker.click()
                        QTest.qWait(60)
                        popup = window.findChild(QObject, popup_name)
                        self.assertTrue(popup.property("visible"), popup_name)
                        content = popup.property("contentItem")
                        padding = float(popup.property("padding"))
                        top = content.mapToScene(QPointF(0, 0)).y() - padding
                        popup_height = float(popup.property("height"))
                        bottom = top + popup_height
                        self.assertGreaterEqual(top, -0.5, popup_name)
                        self.assertLessEqual(bottom, height + 0.5, popup_name)
                        self.assertLessEqual(
                            popup_height,
                            float(popup.property("naturalHeight")) + 0.5,
                            popup_name,
                        )
                        if popup_name in must_flip:
                            self.assertTrue(
                                popup.property("openAbove"),
                                f"{popup_name} should flip up in a {height}px window",
                            )
                        if popup_name in must_stay_below:
                            self.assertFalse(
                                popup.property("openAbove"),
                                f"{popup_name} should stay below in a {height}px window",
                            )
                        picker.click()
                        QTest.qWait(40)
                window.close()
                engine.deleteLater()
                self.application.processEvents()

    def test_text_fields_expose_themed_edit_context_menu(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            bridge = self._bridge(root, initial_page="Chat VR")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()
            window = engine.rootObjects()[0]

            composer_input = window.findChild(QObject, "chatComposerInput")
            self.assertIsNotNone(composer_input)
            # The themed menu is created lazily on the first context-menu
            # request, so the control must receive one before it can be found.
            composer_input.forceActiveFocus()
            self.application.processEvents()
            context_event = QContextMenuEvent(
                QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(10, 10)
            )
            self.application.sendEvent(composer_input, context_event)
            self.application.processEvents()
            menu = composer_input.findChild(QObject, "textEditContextMenu")
            self.assertIsNotNone(menu)

            expected = {
                "textEditContextCut": "Recortar",
                "textEditContextCopy": "Copiar",
                "textEditContextPaste": "Colar",
                "textEditContextSelectAll": "Selecionar tudo",
            }
            for object_name, label in expected.items():
                entry = menu.findChild(QObject, object_name)
                self.assertIsNotNone(entry, object_name)
                self.assertEqual(entry.property("text"), label)

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
                    if message_body is not None:
                        QTest.qWait(120)
                        break
                    QTest.qWait(100)
                self.assertEqual(chat_bridge.messages.rowCount(), 1)
                self.assertIsNotNone(message_body)
                self.assertEqual(segment_bodies, [])
                self.assertIsNotNone(code_card)
                self.assertTrue(message_body.property("selectByMouse"))
                self.assertGreaterEqual(message_body.property("font").pixelSize(), 14)
                quick_document = message_body.property("textDocument")
                self.assertIsNotNone(quick_document)
                document = quick_document.textDocument()

                table_body = find_qml_item(content_item, "tableBody")
                self.assertIsNotNone(table_body)
                self.assertTrue(table_body.property("selectByMouse"))
                tables = []
                table_quick_document = table_body.property("textDocument")
                table_document = table_quick_document.textDocument()
                stack = [table_document.rootFrame()]
                while stack:
                    frame = stack.pop()
                    for child in frame.childFrames():
                        if isinstance(child, QTextTable):
                            tables.append(child)
                        stack.append(child)
                self.assertEqual(len(tables), 1)
                table_format = tables[0].format()
                self.assertEqual(table_format.border(), 0)
                self.assertEqual(
                    table_format.borderBrush().color().name(), "#2c2c30"
                )
                self.assertEqual(
                    table_format.borderStyle(),
                    QTextFrameFormat.BorderStyle_Solid,
                )
                self.assertEqual(
                    table_format.width().type(), QTextLength.PercentageLength
                )
                header_cell = tables[0].cellAt(0, 0).format().toTableCellFormat()
                self.assertFalse(header_cell.hasProperty(int(QTextFormat.BackgroundBrush)))
                self.assertEqual(header_cell.bottomBorder(), 1)
                self.assertEqual(header_cell.leftBorder(), 0)

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
                self.assertIn("def exemplo():", code_card.property("code"))
                message_body.selectAll()
                self.assertIn("Parágrafo final", message_body.property("selectedText"))
                self.assertIn("return 1", code_card.property("code"))
                chat_bridge.copyConversation()
                self.assertIn(markdown, self.application.clipboard().text())
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

    def test_chat_project_icon_modes_are_saved_and_restored(self):
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

            self.assertFalse(bridge.setProjectIconKind(0, "layers"))
            self.assertFalse(bridge.applyProjectIcon(project_index, kind="unknown_kind"))
            self.assertFalse(bridge.applyProjectIcon(project_index, color="nope"))
            self.assertFalse(bridge.applyProjectIcon(project_index, text="ABC"))

            self.assertTrue(
                bridge.applyProjectIcon(
                    project_index, kind="layers", color="#D946EF", emoji="", text=""
                )
            )
            item = bridge.projectItems[project_index]
            self.assertEqual(item["iconKind"], "layers")
            self.assertEqual(item["iconColor"], "#D946EF")

            self.assertTrue(bridge.setProjectIconText(project_index, "ab"))
            item = bridge.projectItems[project_index]
            self.assertEqual(item["iconText"], "ab")
            self.assertEqual(item["iconKind"], "")

            restored = ChatBridge(settings, database, preferences)
            restored_item = next(
                item
                for item in restored.projectItems
                if item["path"] == str(project)
            )
            self.assertEqual(restored_item["iconText"], "ab")

            self.assertTrue(restored.clearProjectIcon(project_index))
            cleared = next(
                item
                for item in restored.projectItems
                if item["path"] == str(project)
            )
            self.assertEqual(cleared["iconKind"], "")
            self.assertEqual(cleared["iconText"], "")
            self.assertEqual(cleared["iconColor"], "")

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

    def test_research_parallelism_allows_four_ultra_lanes(self):
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

            self.assertIsNone(preferences.value("research/max_parallel"))
            self.assertEqual(bridge.researchMaxParallel, 4)
            self.assertEqual(bridge._orchestrator._research_max_parallel, 4)

            bridge.setResearchMaxParallel(4)
            self.assertEqual(bridge.researchMaxParallel, 4)
            self.assertEqual(
                int(preferences.value("research/max_parallel")), 4
            )
            self.assertEqual(bridge._orchestrator._research_max_parallel, 4)

            bridge.setResearchMaxParallel(9)
            self.assertEqual(bridge.researchMaxParallel, 4)
            self.assertEqual(bridge._orchestrator._research_max_parallel, 4)

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
            self._import_release(settings, "current", b"current")
            self._import_release(settings, "2026.08.29", b"new")
            bridge = ChatBridge(settings, database, preferences)

            self.assertFalse(bridge.codeAnalysisEnabled)
            self.assertEqual(bridge.codeAnalysisRelease, "current")
            self.assertFalse(bridge.codeAnalysisReleaseItems[0]["coverageLoaded"])
            bridge.refreshCodeAnalysisReleases()
            for _ in range(200):
                if bridge.codeAnalysisReleaseItems[0]["coverageLoaded"]:
                    break
                QTest.qWait(25)
            self.assertTrue(bridge.codeAnalysisReleaseItems[0]["coverageLoaded"])
            self.assertIn("0/1 JARs indexados", bridge.codeAnalysisReleaseItems[0]["label"])
            self.assertIn(
                "classpath desconhecido", bridge.codeAnalysisReleaseItems[0]["label"]
            )
            self.assertIn(
                "resultados conflitantes",
                bridge.codeAnalysisReleaseItems[0]["warning"],
            )
            # A processing package alone is no longer an Ultra application context.
            bridge.setCodeAnalysisEnabled(True)
            bridge.setCodeAnalysisRelease("2026.08.29")

            self.assertFalse(bridge.codeAnalysisEnabled)
            self.assertEqual(bridge.codeAnalysisRelease, "2026.08.29")
            self.assertEqual(
                str(preferences.value("research/code_analysis_enabled")).casefold(),
                "false",
            )
            reopened = ChatBridge(settings, database, preferences)
            self.assertFalse(reopened.codeAnalysisEnabled)
            self.assertEqual(reopened.codeAnalysisRelease, "2026.08.29")
            self.assertEqual(
                [item["releaseId"] for item in reopened.codeAnalysisReleaseItems],
                ["2026.08.29", "current"],
            )
            bridge.close()
            reopened.close()

    def test_code_analysis_release_selector_rejects_unknown_and_marks_stale(self):
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
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database, preferences)

            self.assertEqual(bridge.codeAnalysisRelease, "r1")
            bridge.setCodeAnalysisRelease("release-inexistente")
            self.assertEqual(bridge.codeAnalysisRelease, "r1")

            jar = settings.root / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
            with zipfile.ZipFile(jar, "a") as archive:
                archive.writestr("br/vr/Nova.class", b"changed")
            bridge.refreshCodeAnalysisReleases()

            self.assertEqual(
                bridge.codeAnalysisReleaseItems[0]["freshness"], "stale"
            )
            self.assertIn("desatualizado", bridge.codeAnalysisReleaseItems[0]["label"])
            bridge.setCodeAnalysisEnabled(True)
            self.assertFalse(bridge.codeAnalysisEnabled)
            bridge.close()

    def test_code_processing_limits_are_safe_and_persisted_per_workspace(self):
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
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database, preferences)

            self.assertEqual(bridge.codeProcessingMaxHeapMb, 2048)
            self.assertEqual(bridge.codeProcessingTimeoutSeconds, 300)
            self.assertEqual(
                bridge.codeProcessingMaxCpuCores,
                CODE_PROCESSING_HARDWARE.recommended_cpu_cores,
            )
            self.assertEqual(bridge.codeProcessingDiskMultiplier, 10)
            self.assertEqual(bridge.codeProcessingWindow, "always")
            self.assertEqual(
                [item["value"] for item in bridge.codeProcessingHeapOptions],
                [1024, 2048, 4096],
            )
            self.assertEqual(
                [item["value"] for item in bridge.codeProcessingTimeoutOptions],
                [300, 600, 1200],
            )
            self.assertEqual(
                [item["value"] for item in bridge.codeProcessingCpuCoreOptions],
                list(CODE_PROCESSING_HARDWARE.cpu_options),
            )
            self.assertEqual(
                [item["label"] for item in bridge.codeProcessingCpuCoreOptions],
                [
                    f"{value} núcleo(s) · Turbo"
                    if value >= 4
                    else f"{value} núcleo(s)"
                    for value in CODE_PROCESSING_HARDWARE.cpu_options
                ],
            )
            self.assertIn("Hardware detectado", bridge.codeProcessingHardwareSummary)
            self.assertEqual(
                bridge.codeProcessingParallelWorkers,
                CODE_PROCESSING_HARDWARE.recommended_parallel_workers,
            )
            self.assertEqual(
                [item["value"] for item in bridge.codeProcessingDiskMultiplierOptions],
                [5, 8, 10],
            )
            self.assertEqual(
                [item["label"] for item in bridge.codeProcessingDiskMultiplierOptions],
                ["Até 5x", "Até 8x", "Até 10x"],
            )
            self.assertEqual(
                [item["value"] for item in bridge.codeProcessingWindowOptions],
                ["always", "night", "off_hours"],
            )
            bridge._apply_code_processing_coverage(
                {
                    "expected_jar_count": 1,
                    "covered_jar_count": 0,
                    "remaining_jar_count": 1,
                    "progress_percent": 4.8,
                    "capacity": {
                        "used_bytes": 1024,
                        "budget_bytes": 4096,
                        "physical_used_bytes": 8192,
                        "orphaned_bytes": 2048,
                        "orphaned_item_count": 1,
                        "orphan_scan_errors": [],
                    },
                }
            )
            self.assertTrue(bridge.codeProcessingCanCleanOrphans)
            self.assertEqual(bridge.codeProcessingProgress, 4.8)
            self.assertIn("Dados ativos: 0.0 MB de 0.0 MB", bridge.codeProcessingCapacitySummary)
            self.assertEqual(bridge.codeProcessingCapacity["orphaned_bytes"], 2048)
            bridge.setCodeProcessingMaxHeapMb(4096)
            bridge.setCodeProcessingTimeoutSeconds(1200)
            bridge.setCodeProcessingMaxCpuCores(4)
            bridge.setCodeProcessingDiskMultiplier(8)
            bridge.setCodeProcessingWindow("off_hours")

            reopened = ChatBridge(settings, database, preferences)
            self.assertEqual(reopened.codeProcessingMaxHeapMb, 4096)
            self.assertEqual(reopened.codeProcessingTimeoutSeconds, 1200)
            self.assertEqual(reopened.codeProcessingMaxCpuCores, 4)
            self.assertEqual(reopened.codeProcessingDiskMultiplier, 8)
            self.assertEqual(reopened.codeProcessingWindow, "off_hours")
            reopened.setCodeProcessingMaxHeapMb(1234)
            reopened.setCodeProcessingTimeoutSeconds(1)
            reopened.setCodeProcessingMaxCpuCores(3)
            reopened.setCodeProcessingDiskMultiplier(11)
            reopened.setCodeProcessingWindow("invalid")
            self.assertEqual(reopened.codeProcessingMaxHeapMb, 4096)
            self.assertEqual(reopened.codeProcessingTimeoutSeconds, 1200)
            self.assertEqual(reopened.codeProcessingMaxCpuCores, 4)
            self.assertEqual(reopened.codeProcessingDiskMultiplier, 8)
            self.assertEqual(reopened.codeProcessingWindow, "off_hours")
            bridge.close()
            reopened.close()

    def test_jar_source_defaults_to_vr_exec_and_is_scoped_by_workspace(self):
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
            self._import_release(settings, "current")
            bridge = ChatBridge(settings, database, preferences)

            self.assertEqual(bridge.codeAnalysisJarSource, "vr_exec")
            self.assertEqual(
                Path(bridge.codeAnalysisJarSourcePath),
                DEFAULT_ERP_JAR_SOURCE_PATH.resolve(strict=False),
            )
            self.assertEqual(
                [item["value"] for item in bridge.codeAnalysisJarSourceItems],
                ["vr_exec", "workspace"],
            )

            bridge.setCodeAnalysisJarSource("workspace")
            expected_workspace = settings.erp_releases_dir.resolve()
            self.assertEqual(bridge.codeAnalysisJarSource, "workspace")
            self.assertEqual(
                Path(bridge.codeAnalysisJarSourcePath), expected_workspace
            )
            reopened = ChatBridge(settings, database, preferences)
            self.assertEqual(reopened.codeAnalysisJarSource, "workspace")

            other_settings = self._settings(root / "other")
            other_database = MaryDatabase(
                other_settings.database_path,
                root=other_settings.root,
                backup_portable_migration=False,
            )
            other = ChatBridge(other_settings, other_database, preferences)
            self.assertEqual(other.codeAnalysisJarSource, "vr_exec")

    def test_partial_directory_snapshot_is_ready_without_complete_base(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            source = settings.erp_releases_dir
            source.mkdir(parents=True)
            for name in ("VRMaster.jar", "VRPdv.jar"):
                with zipfile.ZipFile(source / name, "w") as archive:
                    archive.writestr(
                        "META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n"
                    )
                    archive.writestr(f"br/vr/{Path(name).stem}.class", b"release")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            bridge = ChatBridge(settings, database, preferences)
            bridge.setCodeAnalysisJarSource("workspace")

            self.assertTrue(bridge.snapshotCodeAnalysisRelease("partial-14"))
            for _attempt in range(100):
                self.application.processEvents()
                QTest.qWait(25)
                threading.Event().wait(0.001)
                if not bridge.releaseSnapshotRunning:
                    break

            self.assertFalse(bridge.releaseSnapshotRunning)
            self.assertIn("Release parcial: 2 de 46 JARs", bridge.releaseSnapshotStatus)
            manifest = ErpReleaseCatalog(settings.root).load_manifest("partial-14")
            self.assertEqual(manifest["state"], "ready")
            self.assertEqual(manifest["analysis_scope"], "partial_release")
            self.assertEqual(manifest["jar_count"], 2)
            self.assertEqual(manifest["expected_jar_count"], 46)

            bridge.close()

    def test_single_jar_snapshot_runs_locally_in_background_and_refreshes_selector(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "vr" / "exec"
            jar = source / "ERP.jar"
            jar.parent.mkdir(parents=True)
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr(
                    "META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n"
                )
                archive.writestr("br/vr/App.class", b"release")
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )

            with patch(
                "vrsoft_extractor.mary.frontend.chat.DEFAULT_ERP_JAR_SOURCE_PATH",
                source,
            ):
                bridge = ChatBridge(settings, database, preferences)
                bridge.setCodeAnalysisSnapshotScope("single_jar")
                self.assertTrue(bridge.setCodeAnalysisSingleJarPath(str(jar)))
                self.assertEqual(bridge.codeAnalysisSnapshotExpectedJarCount, 1)
                with patch.object(bridge._orchestrator, "send") as model_send:
                    self.assertTrue(bridge.snapshotCodeAnalysisRelease("2026.08.30"))
                    self.assertTrue(bridge.releaseSnapshotRunning)
                    self.assertFalse(bridge.snapshotCodeAnalysisRelease("outra"))
                    for _attempt in range(100):
                        self.application.processEvents()
                        QTest.qWait(25)
                        threading.Event().wait(0.001)
                        if not bridge.releaseSnapshotRunning:
                            break

                    self.assertFalse(bridge.releaseSnapshotRunning)
                    self.assertEqual(bridge.codeAnalysisRelease, "2026.08.30")
                    self.assertIn(
                        "1 JAR copiado e verificado localmente",
                        bridge.releaseSnapshotStatus,
                    )
                    self.assertEqual(
                        [
                            item["releaseId"]
                            for item in bridge.codeAnalysisReleaseItems
                        ],
                        ["2026.08.30"],
                    )
                    model_send.assert_not_called()

                managed = (
                    settings.erp_releases_dir
                    / "2026.08.30"
                    / "jars"
                    / "ERP"
                    / "unknown"
                    / "ERP.jar"
                )
                before = managed.read_bytes()
                self.assertTrue(bridge.snapshotCodeAnalysisRelease("2026.08.30"))
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(25)
                    threading.Event().wait(0.001)
                    if not bridge.releaseSnapshotRunning:
                        break
                self.assertFalse(bridge.releaseSnapshotRunning)
                self.assertIn("detectada e adicionada", bridge.releaseSnapshotStatus)
                self.assertEqual(managed.read_bytes(), before)
                manifest = ErpReleaseCatalog(settings.root).load_manifest("2026.08.30")
                self.assertEqual(manifest["analysis_scope"], "single_jar")
                self.assertEqual(manifest["expected_jar_count"], 1)
                bridge.close()

    def test_single_jar_snapshot_auto_detects_application_release_without_llm(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            jar = root / "vr" / "exec" / "VRPdv.jar"
            jar.parent.mkdir(parents=True)
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr(
                    "META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n"
                )
                archive.writestr("br/vr/App.class", b"release")
                archive.writestr(
                    "vrpdv.properties",
                    "\n".join(
                        (
                            "versao.major=4",
                            "versao.minor=4",
                            "versao.release=25",
                            "versao.build=0",
                            "versao.beta=0",
                            "app.data=31/08/2026",
                        )
                    ),
                )
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = ChatBridge(settings, database)
            bridge.setCodeAnalysisSnapshotScope("single_jar")
            self.assertTrue(bridge.setCodeAnalysisSingleJarPath(str(jar)))

            with patch.object(bridge._orchestrator, "send") as model_send:
                self.assertTrue(bridge.snapshotCodeAnalysisRelease(""))
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(25)
                    threading.Event().wait(0.001)
                    if not bridge.releaseSnapshotRunning:
                        break

            self.assertFalse(bridge.releaseSnapshotRunning)
            self.assertTrue(bridge.codeAnalysisRelease.startswith("VRPdv-4.4.25.0-"))
            self.assertIn("detectada e adicionada", bridge.releaseSnapshotStatus)
            model_send.assert_not_called()
            manifest = ErpReleaseCatalog(settings.root).load_manifest(
                bridge.codeAnalysisRelease
            )
            self.assertTrue(manifest["auto_detected"])
            self.assertEqual(manifest["updated_applications"], ["VRPdv"])
            bridge.close()

    def test_vr_ultra_release_import_explains_auto_detection_and_partial_packages(self):
        qml = (
            MAIN_QML.parent / "pages" / "ApplicationsSettingsPage.qml"
        ).read_text(encoding="utf-8")

        self.assertIn("Automático: aplicação e versão do vr*.properties", qml)
        self.assertIn("Pacote completo ou parcial", qml)
        self.assertIn("quantidades menores serão indexadas como release parcial", qml)
        self.assertIn("vrUltraCodeProcessingHardwareSummary", qml)
        self.assertIn("Modo paralelo automático", qml)
        self.assertIn("Preparar prévia", qml)
        self.assertIn("chat.confirmApplicationImport()", qml)
        self.assertNotIn("releaseIdField.text.trim().length > 0", qml)

    def test_vr_ultra_release_removal_requires_confirmation(self):
        qml = (
            MAIN_QML.parent / "pages" / "ApplicationsSettingsPage.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('objectName: "vrUltraRemoveReleaseButton"', qml)
        self.assertIn('objectName: "vrUltraRemoveReleaseDialog"', qml)
        self.assertIn("Os JARs de origem serão preservados", qml)
        self.assertIn("chat.removeCodeAnalysisRelease(releaseId)", qml)

    def test_vr_ultra_orphan_cleanup_requires_confirmation(self):
        qml = (
            MAIN_QML.parent / "pages" / "ApplicationsSettingsPage.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('objectName: "vrUltraCodeProcessingCapacity"', qml)
        self.assertIn('objectName: "vrUltraCleanCodeProcessingOrphans"', qml)
        self.assertIn('objectName: "vrUltraCleanOrphansDialog"', qml)
        self.assertIn("chat.cleanCodeProcessingOrphans()", qml)
        self.assertIn("Bancos compartilhados", qml)

    def test_local_code_processing_ui_uses_explicit_progress_and_lazy_tab(self):
        qml_root = MAIN_QML.parent
        settings_qml = (qml_root / "pages" / "SettingsPage.qml").read_text(
            encoding="utf-8"
        )
        apps_qml = (
            qml_root / "pages" / "ApplicationsSettingsPage.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('objectName: "appsSettingsLoader"', settings_qml)
        self.assertIn("active: root.tabIndex === 3", settings_qml)
        self.assertIn("root.appsVisited", settings_qml)
        self.assertIn("asynchronous: true", settings_qml)
        self.assertTrue("VrProgressBar {" in apps_qml or "ProgressBar {" in apps_qml)
        self.assertIn('objectName: "vrUltraCodeProcessingProgressLabel"', apps_qml)
        self.assertIn("chat.codeProcessingCoveredJars", apps_qml)
        self.assertIn("enabled: chat.codeProcessingRunning", apps_qml)

    def test_ocr_removed_from_settings_and_dashboard_ui(self):
        qml_root = MAIN_QML.parent
        settings_qml = (qml_root / "pages" / "SettingsPage.qml").read_text(
            encoding="utf-8"
        )
        dashboard_qml = (qml_root / "pages" / "DashboardPreview.qml").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("install" + "OcrAction", settings_qml)
        self.assertNotIn('runSync("' + "ocr" + '")', settings_qml)
        self.assertNotIn("dashboardMetrics." + "ocr", dashboard_qml)
        self.assertNotIn('label: "OCR"', dashboard_qml)
        self.assertIn('label: "Documentos"', dashboard_qml)
        self.assertIn('label: "Pendentes"', dashboard_qml)
        self.assertIn('label: "Conversas"', dashboard_qml)
        self.assertIn(
            "columns: width < Theme.scaledGeometry(480) ? 2 : 3",
            dashboard_qml,
        )
        knowledge_qml = (qml_root / "pages" / "KnowledgePage.qml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("OCR", knowledge_qml)

    def test_diagnostic_text_does_not_mention_ocr(self):
        with TemporaryDirectory() as temporary:
            settings = self._settings(Path(temporary))

            text = diagnostic_text(settings)

        self.assertIn("Projeto Codex", text)
        self.assertNotIn("OCR", text)
        self.assertNotIn("Tesseract", text)

    def test_background_state_properties_do_not_block_or_poll_the_ui_thread(self):
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
            bridge._release_snapshot_running = True
            bridge._code_processing_running = True

            with (
                patch("vrsoft_extractor.mary.frontend.chat.time.sleep") as sleep,
                patch.object(bridge, "_poll_release_snapshot") as poll_snapshot,
                patch.object(bridge, "_poll_code_processing") as poll_processing,
            ):
                self.assertTrue(bridge.releaseSnapshotRunning)
                self.assertTrue(bridge.codeProcessingRunning)

            sleep.assert_not_called()
            poll_snapshot.assert_not_called()
            poll_processing.assert_not_called()
            bridge._release_snapshot_running = False
            bridge._code_processing_running = False
            bridge.close()

    def test_orphan_cleanup_runs_in_background_and_preserves_source_jar(self):
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
            self._import_release(settings, "r1")
            orphan = (
                settings.root
                / "indice"
                / "codigo"
                / "decompilation"
                / "plan-orphan"
            )
            orphan.mkdir(parents=True)
            (orphan / "Old.java").write_text("class Old {}", encoding="utf-8")
            source_jar = settings.root / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
            bridge = ChatBridge(settings, database, preferences)
            bridge._apply_code_processing_coverage(
                {
                    "expected_jar_count": 1,
                    "covered_jar_count": 0,
                    "remaining_jar_count": 1,
                    "capacity": ErpReleaseCatalog(settings.root).storage_status(),
                }
            )

            self.assertTrue(bridge.codeProcessingCanCleanOrphans)
            self.assertTrue(bridge.cleanCodeProcessingOrphans())
            self.assertTrue(bridge.releaseSnapshotRunning)
            for _attempt in range(100):
                self.application.processEvents()
                QTest.qWait(25)
                threading.Event().wait(0.001)
                if not bridge.releaseSnapshotRunning:
                    break

            self.assertFalse(bridge.releaseSnapshotRunning)
            self.assertFalse(orphan.exists())
            self.assertTrue(source_jar.is_file())
            self.assertIn("Limpeza concluída", bridge.releaseSnapshotStatus)
            self.assertIn("JARs de origem foram preservados", bridge.releaseSnapshotStatus)
            bridge.close()

    def test_release_removal_runs_in_background_and_selects_remaining_release(self):
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
            self._import_release(settings, "r1")
            self._import_release(settings, "r2")
            bridge = ChatBridge(settings, database, preferences)
            bridge.setCodeAnalysisRelease("r1")

            self.assertTrue(bridge.removeCodeAnalysisRelease("r1"))
            self.assertTrue(bridge.releaseSnapshotRunning)
            self.assertFalse(bridge.removeCodeAnalysisRelease("r2"))
            for _attempt in range(100):
                self.application.processEvents()
                QTest.qWait(25)
                threading.Event().wait(0.001)
                if not bridge.releaseSnapshotRunning:
                    break

            self.assertFalse(bridge.releaseSnapshotRunning)
            self.assertEqual(bridge.codeAnalysisRelease, "r2", bridge.releaseSnapshotStatus)
            self.assertEqual(
                [item["releaseId"] for item in bridge.codeAnalysisReleaseItems],
                ["r2"],
            )
            self.assertIn("Release r1 removida do índice", bridge.releaseSnapshotStatus)
            self.assertIn("JARs de origem foram preservados", bridge.releaseSnapshotStatus)
            self.assertFalse(
                (settings.root / "indice" / "codigo" / "releases" / "r1").exists()
            )
            self.assertTrue((settings.erp_releases_dir / "r1" / "jars").is_dir())
            bridge.close()

    def test_local_code_processing_completes_without_model_or_network(self):
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
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database, preferences)
            manifest_hash = ErpReleaseCatalog(settings.root).load_manifest("r1")[
                "release_manifest_sha256"
            ]

            class FakeToolchain:
                def __init__(self, _root, **_kwargs):
                    pass

                def doctor(self):
                    return {
                        "java": {"available": True},
                        "vineflower": {"available": True},
                        "cfr": {"available": False},
                    }

            class FakeExecutor:
                def retry(self, _batch_id):
                    raise AssertionError("retry não esperado")

            class FakeCoverage:
                def __init__(self):
                    self.covered = 0
                    self.executor = FakeExecutor()
                    self.advance_kwargs = []

                def payload(self):
                    return {
                        "release_manifest_sha256": manifest_hash,
                        "expected_jar_count": 2,
                        "covered_jar_count": self.covered,
                        "remaining_jar_count": 2 - self.covered,
                        "active_plans": [],
                        "blocked_plans": [],
                    }

                def status(self, _release_id):
                    return self.payload()

                def advance(self, _release_id, **_kwargs):
                    self.advance_kwargs.append(dict(_kwargs))
                    self.covered += 1
                    return {
                        "coverage": self.payload(),
                        "executed": [
                            {
                                "state": "completed",
                                "telemetry": {
                                    "duration_ms": 250,
                                    "peak_rss_bytes": 64 * 1024 * 1024,
                                    "cpu_user_ms": 100,
                                    "cpu_kernel_ms": 25,
                                    "input_bytes": 1024,
                                    "output_bytes": 2048,
                                    "timed_out": False,
                                    "metrics_available": True,
                                },
                            }
                        ],
                    }

            manager = FakeCoverage()
            bridge.setCodeProcessingMaxHeapMb(4096)
            bridge.setCodeProcessingTimeoutSeconds(600)
            bridge.setCodeProcessingMaxCpuCores(4)
            with (
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.JvmToolchain",
                    FakeToolchain,
                ),
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.ErpCodeCoverage",
                    return_value=manager,
                ),
                patch.object(bridge._orchestrator, "send") as model_send,
            ):
                self.assertTrue(bridge.startCodeProcessing())
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(20)
                    threading.Event().wait(0.001)
                    if not bridge.codeProcessingRunning:
                        break

            self.assertFalse(bridge.codeProcessingRunning)
            self.assertEqual(
                bridge.codeProcessingProgress,
                100,
                msg=bridge.codeProcessingStatus,
            )
            self.assertEqual(bridge.codeProcessingCoveredJars, 2)
            self.assertIn("concluído", bridge.codeProcessingStatus)
            self.assertEqual(bridge.codeProcessingFrozenRelease, "r1")
            self.assertEqual(bridge.codeProcessingFrozenManifestHash, manifest_hash)
            self.assertTrue(manager.advance_kwargs)
            self.assertEqual(
                {
                    (
                        item["max_heap_mb"],
                        item["timeout_seconds"],
                        item["max_cpu_cores"],
                        item["parallel_workers"],
                        item["process_priority"],
                        item["batch_limit"],
                        item["processing_window"],
                    )
                    for item in manager.advance_kwargs
                },
                {(4096, 600, 4, 2, "normal", 2, "always")},
            )
            self.assertEqual(bridge.codeProcessingTelemetry["processed_batches"], 2)
            self.assertEqual(bridge.codeProcessingTelemetry["peak_rss_bytes"], 64 * 1024 * 1024)
            self.assertEqual(bridge.codeProcessingTelemetry["output_bytes"], 4096)
            self.assertIn("pico Java 64.0 MB", bridge.codeProcessingTelemetrySummary)
            model_send.assert_not_called()
            audit_path = (
                settings.root / "indice" / "codigo" / "processing-runs.jsonl"
            )
            audit = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [item["event"] for item in audit],
                ["started", "toolchain_validated", "progress", "progress", "completed"],
            )
            self.assertEqual({item["release_id"] for item in audit}, {"r1"})
            self.assertEqual(
                {item["release_manifest_sha256"] for item in audit},
                {manifest_hash},
            )
            self.assertEqual(len({item["run_id"] for item in audit}), 1)
            self.assertEqual(audit[0]["details"]["max_heap_mb"], 4096)
            self.assertEqual(audit[0]["details"]["timeout_seconds"], 600)
            self.assertEqual(audit[0]["details"]["global_java_concurrency"], 2)
            self.assertEqual(
                audit[-1]["details"]["telemetry"]["processed_batches"], 2
            )
            bridge.close()

    def test_local_code_processing_pause_is_cooperative_between_batches(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database)
            manifest_hash = ErpReleaseCatalog(settings.root).load_manifest("r1")[
                "release_manifest_sha256"
            ]
            batch_started = threading.Event()
            allow_batch_finish = threading.Event()

            class FakeToolchain:
                def __init__(self, _root, **_kwargs):
                    pass

                def doctor(self):
                    return {
                        "java": {"available": True},
                        "vineflower": {"available": True},
                        "cfr": {"available": True},
                    }

            class FakeCoverage:
                def __init__(self):
                    self.covered = 0
                    self.executor = object()

                def payload(self):
                    return {
                        "release_manifest_sha256": manifest_hash,
                        "expected_jar_count": 2,
                        "covered_jar_count": self.covered,
                        "remaining_jar_count": 2 - self.covered,
                        "active_plans": [],
                        "blocked_plans": [],
                    }

                def status(self, _release_id):
                    return self.payload()

                def advance(self, _release_id, **_kwargs):
                    batch_started.set()
                    allow_batch_finish.wait(timeout=2)
                    self.covered = 1
                    return {
                        "coverage": self.payload(),
                        "executed": [{"state": "completed"}],
                    }

            with (
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.JvmToolchain",
                    FakeToolchain,
                ),
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.ErpCodeCoverage",
                    return_value=FakeCoverage(),
                ),
            ):
                self.assertTrue(bridge.startCodeProcessing())
                self.assertTrue(batch_started.wait(timeout=2))
                bridge.pauseCodeProcessing()
                self.assertTrue(bridge.codeProcessingPauseRequested)
                self.assertIn("lotes Java atuais", bridge.codeProcessingStatus)
                allow_batch_finish.set()
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(20)
                    threading.Event().wait(0.001)
                    if not bridge.codeProcessingRunning:
                        break

            self.assertFalse(bridge.codeProcessingRunning)
            self.assertFalse(bridge.codeProcessingPauseRequested)
            self.assertEqual(bridge.codeProcessingCoveredJars, 1)
            self.assertIn("pausado entre lotes", bridge.codeProcessingStatus)
            bridge.close()

    def test_local_code_processing_cancel_running(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database)
            manifest_hash = ErpReleaseCatalog(settings.root).load_manifest("r1")[
                "release_manifest_sha256"
            ]
            batch_started = threading.Event()
            allow_batch_finish = threading.Event()

            class FakeToolchain:
                def __init__(self, _root, **_kwargs):
                    pass

                def doctor(self):
                    return {
                        "java": {"available": True},
                        "vineflower": {"available": True},
                        "cfr": {"available": True},
                    }

            class FakeCoverage:
                def __init__(self):
                    self.covered = 0
                    self.cancelled = False
                    self.executor = object()

                def payload(self):
                    return {
                        "release_manifest_sha256": manifest_hash,
                        "expected_jar_count": 2,
                        "covered_jar_count": self.covered,
                        "remaining_jar_count": 2 - self.covered,
                        "active_plans": [] if self.cancelled else ["plan-1"],
                        "blocked_plans": [],
                    }

                def status(self, _release_id):
                    return self.payload()

                def advance(self, _release_id, **_kwargs):
                    batch_started.set()
                    allow_batch_finish.wait(timeout=2)
                    self.covered = 1
                    return {
                        "coverage": self.payload(),
                        "executed": [{"state": "completed"}],
                    }

                def cancel(self, _release_id):
                    self.cancelled = True
                    return ["plan-1"]

            with (
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.JvmToolchain",
                    FakeToolchain,
                ),
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.ErpCodeCoverage",
                    return_value=FakeCoverage(),
                ),
            ):
                self.assertTrue(bridge.startCodeProcessing())
                self.assertTrue(batch_started.wait(timeout=2))
                bridge.cancelCodeProcessing()
                self.assertTrue(bridge.codeProcessingCancelRequested)
                self.assertIn("Cancelamento solicitado", bridge.codeProcessingStatus)
                allow_batch_finish.set()
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(20)
                    threading.Event().wait(0.001)
                    if not bridge.codeProcessingRunning:
                        break

            self.assertFalse(bridge.codeProcessingRunning)
            self.assertFalse(bridge.codeProcessingCancelRequested)
            self.assertFalse(bridge.codeProcessingCanCancel)
            self.assertIn("cancelada pelo usuário", bridge.codeProcessingStatus)
            bridge.close()

    def test_local_code_processing_cancel_paused(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database)
            manifest_hash = ErpReleaseCatalog(settings.root).load_manifest("r1")[
                "release_manifest_sha256"
            ]

            coverage = {
                "release_manifest_sha256": manifest_hash,
                "expected_jar_count": 1,
                "covered_jar_count": 0,
                "remaining_jar_count": 1,
                "progress_percent": 5.0,
                "active_plans": ["plan-1"],
                "blocked_plans": [],
            }
            audit_event = {
                "event": "paused",
                "release_id": "r1",
                "release_manifest_sha256": manifest_hash,
                "run_id": "run-1",
            }
            bridge._apply_code_processing_coverage(coverage)
            bridge._restore_code_processing_audit(audit_event, coverage)

            self.assertFalse(bridge.codeProcessingRunning)
            self.assertTrue(bridge.codeProcessingCanCancel)
            self.assertIn("pausado entre lotes", bridge.codeProcessingStatus)

            bridge.cancelCodeProcessing()

            self.assertFalse(bridge.codeProcessingRunning)
            self.assertFalse(bridge.codeProcessingCancelRequested)
            self.assertFalse(bridge.codeProcessingCanCancel)
            self.assertIn("cancelada pelo usuário", bridge.codeProcessingStatus)
            bridge.close()

    def test_local_code_processing_stops_before_planning_without_toolchain(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database)

            class MissingToolchain:
                def __init__(self, _root, **_kwargs):
                    pass

                def doctor(self):
                    return {
                        "java": {"available": False},
                        "vineflower": {"available": False},
                        "cfr": {"available": False},
                    }

            with (
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.JvmToolchain",
                    MissingToolchain,
                ),
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.ErpCodeCoverage"
                ) as coverage,
            ):
                self.assertTrue(bridge.startCodeProcessing())
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(20)
                    threading.Event().wait(0.001)
                    if not bridge.codeProcessingRunning:
                        break

            self.assertFalse(bridge.codeProcessingRunning)
            self.assertIn("Java 17 isolado", bridge.codeProcessingStatus)
            coverage.assert_not_called()
            audit_path = (
                settings.root / "indice" / "codigo" / "processing-runs.jsonl"
            )
            self.assertEqual(
                [
                    json.loads(line)["event"]
                    for line in audit_path.read_text(encoding="utf-8").splitlines()
                ],
                ["started", "failed"],
            )
            bridge.close()

    def test_local_code_processing_retries_first_attention_batch(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            self._import_release(settings, "r1")
            bridge = ChatBridge(settings, database)
            manifest_hash = ErpReleaseCatalog(settings.root).load_manifest("r1")[
                "release_manifest_sha256"
            ]

            class FakeToolchain:
                def __init__(self, _root, **_kwargs):
                    pass

                def doctor(self):
                    return {
                        "java": {"available": True},
                        "vineflower": {"available": True},
                        "cfr": {"available": True},
                    }

            class FakeExecutor:
                def __init__(self, owner):
                    self.owner = owner
                    self.retried = []

                def retry(self, batch_id):
                    self.retried.append(batch_id)
                    self.owner.blocked = False

            class FakeCoverage:
                def __init__(self):
                    self.covered = 0
                    self.blocked = True
                    self.executor = FakeExecutor(self)

                def payload(self):
                    return {
                        "release_manifest_sha256": manifest_hash,
                        "expected_jar_count": 1,
                        "covered_jar_count": self.covered,
                        "remaining_jar_count": 1 - self.covered,
                        "active_plans": [],
                        "blocked_plans": (
                            [
                                {
                                    "selected_jars": ["VRPdv.jar"],
                                    "attention_batches": [
                                        {
                                            "batch_id": "batch-1",
                                            "jar_relative_path": "VRPdv.jar",
                                            "ordinal": 0,
                                            "state": "failed",
                                        },
                                        {
                                            "batch_id": "batch-2",
                                            "jar_relative_path": "VRPdv.jar",
                                            "ordinal": 1,
                                            "state": "partial",
                                        },
                                    ],
                                }
                            ]
                            if self.blocked
                            else []
                        ),
                    }

                def status(self, _release_id):
                    return self.payload()

                def advance(self, _release_id, **_kwargs):
                    self.covered = 1
                    return {
                        "coverage": self.payload(),
                        "executed": [{"state": "completed"}],
                    }

            manager = FakeCoverage()
            with patch(
                "vrsoft_extractor.mary.frontend.bridges.codeadmin.ErpCodeCoverage",
                return_value=manager,
            ):
                bridge.refreshCodeProcessingStatus()
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(20)
                    threading.Event().wait(0.001)
                    if not bridge.codeProcessingStatusLoading:
                        break
            self.assertTrue(bridge.codeProcessingCanRetry)
            self.assertEqual(
                [item["batchId"] for item in bridge.codeProcessingAttentionBatches],
                ["batch-1", "batch-2"],
            )
            bridge.setCodeProcessingRetryBatch("batch-2")
            self.assertEqual(bridge.codeProcessingRetryBatch, "batch-2")
            self.assertEqual(bridge.codeProcessingCurrentBatch, "batch-2")

            with (
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.JvmToolchain",
                    FakeToolchain,
                ),
                patch(
                    "vrsoft_extractor.mary.frontend.bridges.codeadmin.ErpCodeCoverage",
                    return_value=manager,
                ),
            ):
                self.assertTrue(bridge.retryCodeProcessing())
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(20)
                    threading.Event().wait(0.001)
                    if not bridge.codeProcessingRunning:
                        break

            self.assertEqual(manager.executor.retried, ["batch-2"])
            self.assertEqual(
                bridge.codeProcessingProgress,
                100,
                msg=bridge.codeProcessingStatus,
            )
            self.assertFalse(bridge.codeProcessingCanRetry)
            audit = [
                json.loads(line)
                for line in (
                    settings.root / "indice" / "codigo" / "processing-runs.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(audit[0]["details"]["retry_batch_id"], "batch-2")
            retried_event = next(
                item for item in audit if item["event"] == "batch_retried"
            )
            self.assertEqual(retried_event["details"]["batch_id"], "batch-2")
            bridge.close()

    def test_local_code_processing_restores_last_run_and_current_batch(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            self._import_release(settings, "r1")
            manifest_hash = ErpReleaseCatalog(settings.root).load_manifest("r1")[
                "release_manifest_sha256"
            ]
            CodeProcessingAudit(settings.root).record(
                "paused",
                run_id="processing-run-1",
                release_id="r1",
                manifest_sha256=manifest_hash,
                details={
                    "covered_jar_count": 1,
                    "expected_jar_count": 2,
                    "telemetry": {
                        "processed_batches": 1,
                        "wall_duration_ms": 2500,
                        "peak_rss_bytes": 32 * 1024 * 1024,
                        "cpu_user_ms": 500,
                        "cpu_kernel_ms": 100,
                        "output_bytes": 1024,
                        "metrics_available": True,
                    },
                },
            )
            coverage = {
                "release_manifest_sha256": manifest_hash,
                "expected_jar_count": 2,
                "covered_jar_count": 1,
                "remaining_jar_count": 1,
                "remaining_jars": ["VRPdv.jar"],
                "active_plans": [
                    {
                        "current_batch": {
                            "batch_id": "batch-7",
                            "jar_relative_path": "VRPdv.jar",
                            "state": "pending",
                        },
                        "attention_batches": [],
                    }
                ],
                "blocked_plans": [],
            }

            with patch(
                "vrsoft_extractor.mary.frontend.bridges.codeadmin.ErpCodeCoverage"
            ) as coverage_manager:
                coverage_manager.return_value.status.return_value = coverage
                bridge = ChatBridge(settings, database)
                bridge.refreshCodeProcessingStatus()
                for _attempt in range(100):
                    self.application.processEvents()
                    QTest.qWait(20)
                    threading.Event().wait(0.001)
                    if bridge.codeProcessingFrozenRelease == "r1":
                        break

            self.assertFalse(bridge.codeProcessingRunning)
            self.assertEqual(bridge.codeProcessingFrozenRelease, "r1")
            self.assertEqual(bridge.codeProcessingFrozenManifestHash, manifest_hash)
            self.assertEqual(bridge.codeProcessingCurrentJar, "VRPdv.jar")
            self.assertEqual(bridge.codeProcessingCurrentBatch, "batch-7")
            self.assertIn("pausado entre lotes", bridge.codeProcessingStatus)
            self.assertIn("pico Java 32.0 MB", bridge.codeProcessingTelemetrySummary)
            bridge.close()

    def test_code_analysis_cannot_be_enabled_without_inventoried_release(self):
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

            bridge.setCodeAnalysisEnabled(True)

            self.assertFalse(bridge.codeAnalysisEnabled)
            self.assertEqual(bridge.codeAnalysisRelease, "")
            self.assertEqual(bridge.codeAnalysisReleaseItems, [])

    def test_expert_profile_unlocks_and_persists_explicit_response_mode(self):
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

            self.assertFalse(bridge.expertProfileEnabled)
            self.assertEqual(bridge.vrResponseMode, "auto")
            bridge.setVrResponseMode("support")
            self.assertEqual(bridge.vrResponseMode, "auto")

            bridge.setExpertProfileEnabled(True)
            bridge.setVrResponseMode("implementation")
            self.assertTrue(bridge.expertProfileEnabled)
            self.assertEqual(bridge.vrResponseMode, "implementation")

            reopened = ChatBridge(settings, database, preferences)
            self.assertTrue(reopened.expertProfileEnabled)
            self.assertEqual(reopened.vrResponseMode, "implementation")

            reopened.setExpertProfileEnabled(False)
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

    def test_pesquisa_literal_follows_normal_send_path(self):
        def send_call_for(text: str):
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
                conversation_id = database.create_conversation(
                    "Conversa", "codex", "gpt-5", settings.root
                )
                bridge.refresh()
                bridge.selectConversationId(conversation_id)
                with patch.object(bridge._orchestrator, "send") as send_mock:
                    self.assertTrue(bridge.sendMessage(text))
                send_mock.assert_called_once()
                call = send_mock.call_args
                self.assertEqual(call.args[0], conversation_id)
                self.assertNotIn("force_research", call.kwargs)
                return call, bridge

        literal, literal_bridge = send_call_for("/pesquisa onde grava o SPED")
        plain, plain_bridge = send_call_for("onde grava o SPED")

        self.assertEqual(literal.args[1], "/pesquisa onde grava o SPED")
        self.assertEqual(literal.args[4], "/pesquisa onde grava o SPED")
        self.assertEqual(literal.args[5], "/pesquisa onde grava o SPED")
        self.assertEqual(len(literal.args), len(plain.args), "mesmo caminho de envio")
        self.assertEqual(literal.args[3], plain.args[3])
        self.assertEqual(literal.args[6], plain.args[6])
        self.assertEqual(sorted(literal.kwargs), sorted(plain.kwargs))
        self.assertNotIn("Ative o VR", literal_bridge._status_text)
        self.assertEqual(literal_bridge._status_text, "Executando…")
        self.assertEqual(literal_bridge._status_text, plain_bridge._status_text)

    def test_command_palette_does_not_offer_pesquisa(self):
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
            chat_bridge = ChatBridge(settings, database, preferences)
            frontend_bridge = self._bridge(root, initial_page="Chat VR")
            engine = create_engine(frontend_bridge, chat_bridge)
            self.application.processEvents()
            window = engine.rootObjects()[0]
            window.show()
            QTest.qWait(150)
            try:
                page = window.findChild(QObject, "chatPage")
                composer = window.findChild(QObject, "chatComposerInput")
                self.assertIsNotNone(page)
                self.assertIsNotNone(composer)
                composer.setProperty("text", "/")
                QTest.qWait(50)
                with patch.object(
                    chat_bridge, "skillSuggestions", return_value=[]
                ):
                    self.assertTrue(
                        QMetaObject.invokeMethod(page, "updateComposerSuggestions")
                    )
                suggestions = page.property("composerSuggestions")
                if hasattr(suggestions, "toVariant"):
                    suggestions = suggestions.toVariant()
                self.assertTrue(suggestions, "o palette deveria listar comandos")
                labels = {str(item.get("label") or "") for item in suggestions}
                self.assertNotIn("/pesquisa", labels)
                actions = {str(item.get("action") or "") for item in suggestions}
                self.assertNotIn("pesquisa", actions)
                self.assertIn("/vr", labels)
            finally:
                window.close()
                engine.deleteLater()
                self.application.processEvents()

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

    def test_chat_bridge_builds_t3_style_trace_without_mixing_final_answer(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Trace", "codex", "gpt-5.6", settings.root
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )

            for event in (
                RuntimeEvent(conversation_id, "turn_started", "Execução iniciada"),
                RuntimeEvent(
                    conversation_id,
                    "reasoning_delta",
                    "Analisando a estrutura atual.",
                    {"itemId": "reasoning-1", "summaryIndex": 0},
                ),
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Comando iniciado",
                    {
                        "lifecycle": "item/started",
                        "item": {
                            "id": "command-1",
                            "type": "commandExecution",
                            "command": "rg -n reasoning vrsoft_extractor",
                        },
                    },
                ),
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Comando concluído",
                    {
                        "lifecycle": "item/completed",
                        "item": {
                            "id": "command-1",
                            "type": "commandExecution",
                            "command": "rg -n reasoning vrsoft_extractor",
                        },
                    },
                ),
                RuntimeEvent(
                    conversation_id,
                    "assistant_delta",
                    "O trace já preserva a ordem dos eventos.",
                    {"itemId": "commentary-1", "phase": "commentary"},
                ),
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Arquivo alterado",
                    {
                        "lifecycle": "item/completed",
                        "item": {
                            "id": "files-1",
                            "type": "fileChange",
                            "changes": [
                                {
                                    "path": "tests/test_trace.py",
                                    "kind": "update",
                                    "diff": "@@ -1 +1 @@\n-old\n+new\n",
                                }
                            ],
                        },
                    },
                ),
                RuntimeEvent(
                    conversation_id,
                    "assistant_delta",
                    "Implementação concluída.",
                    {"itemId": "final-1", "phase": "final_answer"},
                ),
            ):
                bridge._on_runtime_event(event)

            self.assertEqual(
                [item["kind"] for item in bridge.traceItems],
                ["commentary", "action_group", "commentary", "file_changes"],
            )
            self.assertEqual(bridge.traceItems[1]["text"], "Executou 1 comando")
            self.assertEqual(bridge.traceItems[3]["fileCount"], 1)
            self.assertEqual(bridge.traceItems[3]["additions"], 1)
            self.assertEqual(bridge.traceItems[3]["deletions"], 1)
            self.assertEqual(bridge._streaming_text, "Implementação concluída.")
            self.assertNotIn("O trace já preserva", bridge._streaming_text)

    def test_chat_bridge_restores_the_same_trace_order_from_runtime_events(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Histórico", "codex", "gpt-5.6", settings.root
            )
            database.add_message(conversation_id, "user", "Revise o trace")
            database.add_message(conversation_id, "assistant", "Trace revisado")
            for event in (
                RuntimeEvent(conversation_id, "turn_started", "Execução iniciada"),
                RuntimeEvent(
                    conversation_id,
                    "reasoning_delta",
                    "Conferindo os eventos.",
                    {"itemId": "reasoning-1", "summaryIndex": 0},
                ),
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Comando concluído",
                    {
                        "lifecycle": "item/completed",
                        "item": {
                            "id": "command-1",
                            "type": "commandExecution",
                            "command": "pytest -q",
                        },
                    },
                ),
                RuntimeEvent(
                    conversation_id,
                    "assistant_delta",
                    "Os testes passaram.",
                    {"itemId": "commentary-1", "phase": "commentary"},
                ),
                RuntimeEvent(
                    conversation_id,
                    "assistant_delta",
                    "Trace revisado",
                    {"itemId": "final-1", "phase": "final_answer"},
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
                [item["kind"] for item in bridge.traceItems],
                ["commentary", "action_group", "commentary"],
            )
            self.assertTrue(all(item["state"] == "completed" for item in bridge.traceItems))
            self.assertEqual(bridge._streaming_text, "Trace revisado")

    def test_changed_files_trace_card_loads_with_real_diff_statistics(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Arquivos", "codex", "gpt-5.6", settings.root
            )
            database.add_message(conversation_id, "user", "Ajuste o arquivo")
            database.add_message(conversation_id, "assistant", "Arquivo ajustado")
            for event in (
                RuntimeEvent(conversation_id, "turn_started", "Execução iniciada"),
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "Arquivo alterado",
                    {
                        "lifecycle": "item/completed",
                        "item": {
                            "id": "files-1",
                            "type": "fileChange",
                            "changes": [
                                {
                                    "path": "src/app.py",
                                    "kind": "update",
                                    "diff": "@@ -1 +1,2 @@\n-old\n+new\n+extra\n",
                                }
                            ],
                        },
                    },
                ),
                RuntimeEvent(conversation_id, "turn_completed", "Pronto"),
            ):
                database.add_event(event)

            frontend_bridge = self._bridge(root, initial_page="Chat VR")
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            self.assertEqual(chat_bridge.traceItems[0]["kind"], "file_changes")
            engine = create_engine(frontend_bridge, chat_bridge)
            self.application.processEvents()
            window = engine.rootObjects()[0]
            window.show()
            try:
                def find_qml_item(item, name):
                    if item.objectName() == name:
                        return item
                    for child in item.childItems():
                        found = find_qml_item(child, name)
                        if found is not None:
                            return found
                    return None

                card = None
                content_item = window.property("contentItem")
                activity = find_qml_item(content_item, "chatActivity")
                self.assertIsNotNone(activity)
                activity.setProperty("cardExpanded", True)
                self.application.processEvents()
                for _attempt in range(20):
                    self.application.processEvents()
                    card = find_qml_item(content_item, "changedFilesCard")
                    if card is not None:
                        break
                    QTest.qWait(50)
                self.assertIsNotNone(card)
                self.assertEqual(card.property("fileCount"), 1)
                self.assertEqual(card.property("additions"), 2)
                self.assertEqual(card.property("deletions"), 1)
                self.assertTrue(card.property("hasDiff"))
                card.setProperty("diffExpanded", True)
                self.application.processEvents()
                QTest.qWait(50)
                self.assertTrue(card.property("diffExpanded"))
                diff_body = find_qml_item(content_item, "changedFilesDiffBody")
                self.assertIsNotNone(diff_body)
            finally:
                window.close()

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
            ignored = settings.root / ".git" / "objects"
            ignored.mkdir(parents=True)
            (ignored / "fiscal-ignorado.txt").write_text("objeto", encoding="utf-8")
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
            self.assertNotIn(".git", "\n".join(item["path"] for item in results))

    def test_chat_qml_exposes_refined_search_profiles_links_and_scrolling(self):
        chat_qml = (MAIN_QML.parent / "pages" / "ChatPreview.qml").read_text(
            encoding="utf-8"
        )
        composer_qml = (MAIN_QML.parent / "components" / "VrChatComposer.qml").read_text(
            encoding="utf-8"
        )
        profile_qml = (
            MAIN_QML.parent / "components" / "VrProfileIcon.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('objectName: "conversationSearch"', chat_qml)
        self.assertIn('iconKind: "newChat"', chat_qml)
        self.assertNotRegex(chat_qml, r'(?m)^\s+text: "Nova conversa"$')
        self.assertIn('objectName: "chatSettingsButton"', chat_qml)
        self.assertIn('Accessible.name: "Abrir Configurações"', chat_qml)
        self.assertLess(
            chat_qml.index('objectName: "conversationSearch"'),
            chat_qml.index('objectName: "newChatButton"'),
        )
        self.assertIn('objectName: "expertProfileStrip"', chat_qml)
        self.assertIn("Behavior on expertReveal", chat_qml)
        self.assertIn("VrProfileIcon", chat_qml)
        self.assertIn('key: "adaptive"', chat_qml)
        self.assertIn('label: "Adaptativa"', chat_qml)
        self.assertIn("expertSenior", chat_qml)
        self.assertIn("expertTraining", chat_qml)
        self.assertIn('"Treinamento"', chat_qml)
        line_icon_qml = (
            MAIN_QML.parent / "components" / "VrLineIcon.qml"
        ).read_text(encoding="utf-8")
        lucide_paths_js = (
            MAIN_QML.parent / "theme" / "LucidePaths.js"
        ).read_text(encoding="utf-8")
        self.assertIn('"expertTraining"', lucide_paths_js)
        self.assertIn("LucidePaths.paths[root.kind]", line_icon_qml)
        self.assertIn("Theme.palette.chatControl", profile_qml)
        self.assertIn("VrChatComposer {", chat_qml)
        self.assertIn("contentHeight + topPadding + bottomPadding", composer_qml)
        self.assertIn("Math.min(composerCard.page.chatMainHandle.height * 0.28, Math.max(Theme.scaledGeometry(54)", composer_qml)
        self.assertIn(
            'variant: composerCard.page.chatBridge.vrMode !== "off" ? "primary" : "ghost"',
            composer_qml,
        )
        self.assertIn('objectName: "chatAttachmentThumbnail"', composer_qml)
        self.assertIn("hasImageAttachments", composer_qml)
        self.assertIn("fillMode: Image.PreserveAspectCrop", composer_qml)
        markdown_qml = (MAIN_QML.parent / "components" / "VrMarkdownContent.qml").read_text(encoding="utf-8")
        self.assertIn("Theme.bodySize", markdown_qml)
        self.assertIn("Qt.PointingHandCursor", markdown_qml)
        self.assertIn('objectName: "messageScrollBar"', chat_qml)
        self.assertIn("if (followTail) tailTimer.restart()", chat_qml)
        self.assertIn("ScrollBar.vertical: VrScrollBar", chat_qml)
        self.assertIn('"Como posso ajudar no projeto " + projectLabel + "?"', chat_qml)

    def test_trashing_a_conversation_does_not_block_the_ui_thread(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Excluir sem travar", "codex", "gpt-5.6", settings.root
            )
            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = ChatBridge(settings, database, preferences)
            bridge.selectConversation(0)
            started = threading.Event()
            release = threading.Event()
            original_trash = bridge._orchestrator.trash

            def slow_trash(target_id: str) -> None:
                started.set()
                if not release.wait(2):
                    raise TimeoutError("teste não liberou a exclusão")
                original_trash(target_id)

            with patch.object(
                bridge._orchestrator,
                "trash",
                side_effect=slow_trash,
            ):
                bridge.trashCurrentConversation()
                self.assertTrue(started.wait(0.5))
                self.assertTrue(bridge.conversationDeleteRunning)
                self.assertTrue(bridge.isDraft)
                self.assertNotIn(
                    conversation_id,
                    [item["conversationId"] for item in bridge._all_conversations],
                )
                release.set()
                for _attempt in range(200):
                    self.application.processEvents()
                    # Release the GIL so the filesystem/SQLite worker can progress.
                    threading.Event().wait(0.01)
                    if not bridge.conversationDeleteRunning:
                        break

            self.assertFalse(bridge.conversationDeleteRunning)
            self.assertEqual(
                database.get_conversation(conversation_id)["archived"],
                1,
            )
            self.assertIn("lixeira", bridge.statusText)

    def test_chat_composer_grows_with_wrapped_text_and_caps_its_height(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            frontend = self._bridge(root, initial_page="Chat VR")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            chat = ChatBridge(settings, database)
            engine = create_engine(frontend, chat)
            self.application.processEvents()
            try:
                window = engine.rootObjects()[0]
                window.setProperty("width", 1120)
                window.setProperty("height", 700)
                window.show()
                QTest.qWait(200)
                composer = window.findChild(QObject, "chatComposerScroll") or window.findChild(QObject, "chatComposerInput")
                self.assertIsNotNone(composer)
                compact_height = composer.property("height")

                composer.setProperty("text", " ".join(["crossdocking"] * 90))
                QTest.qWait(100)
                self.application.processEvents()

                self.assertGreater(composer.property("height"), compact_height)
                self.assertLessEqual(composer.property("height"), 200)

                scroll_bar = window.findChild(QObject, "chatComposerScrollBar")
                self.assertIsNotNone(scroll_bar)
                self.assertTrue(scroll_bar.property("visible"))
                self.assertLess(scroll_bar.property("size"), 1.0)
                self.assertAlmostEqual(
                    scroll_bar.property("x") + scroll_bar.property("width"),
                    composer.property("width"),
                    delta=0.5,
                )
                self.assertAlmostEqual(
                    scroll_bar.property("height"),
                    composer.property("height"),
                    delta=0.5,
                )

                input_item = composer.property("contentItem")
                before_y = input_item.property("contentY")
                thumb_y = (scroll_bar.property("visualPosition")
                           + scroll_bar.property("visualSize") / 2) * scroll_bar.property("height")
                start = scroll_bar.mapToScene(
                    QPointF(scroll_bar.property("width") / 2, thumb_y)).toPoint()
                end = scroll_bar.mapToScene(
                    QPointF(scroll_bar.property("width") / 2, thumb_y + scroll_bar.property("height") / 3)).toPoint()
                QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
                QTest.mouseMove(window, end, 20)
                QTest.qWait(50)
                self.assertGreater(input_item.property("contentY"), before_y)
                QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
            finally:
                if engine.rootObjects():
                    engine.rootObjects()[0].close()
                engine.deleteLater()
                self.application.processEvents()

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

    def test_live_sync_and_log_models_append_without_resetting_the_view(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            studio = StudioBridge(settings, database)
            sync_resets = []
            sync_insertions = []
            studio.syncLogModel.modelReset.connect(lambda: sync_resets.append(True))
            studio.syncLogModel.rowsInserted.connect(
                lambda _parent, first, last: sync_insertions.append((first, last))
            )

            studio._apply_sync_progress("item 1 sincronizado")
            studio._apply_sync_progress("item 2 sincronizado")

            self.assertEqual(studio.syncLogModel.rowCount(), 2)
            self.assertEqual(
                studio.syncLogModel.data(
                    studio.syncLogModel.index(1, 0), Qt.UserRole + 1
                ),
                "item 2 sincronizado",
            )
            self.assertEqual(sync_resets, [])
            self.assertEqual(sync_insertions, [(0, 0), (1, 1)])
            self.assertEqual(studio.logModel.rowCount(), 2)

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
        composer_qml = (
            MAIN_QML.parent / "components" / "VrChatComposer.qml"
        ).read_text(encoding="utf-8")
        knowledge_qml = (
            MAIN_QML.parent / "pages" / "KnowledgePage.qml"
        ).read_text(encoding="utf-8")
        settings_qml = (
            MAIN_QML.parent / "pages" / "SettingsPage.qml"
        ).read_text(encoding="utf-8")

        self.assertIn("Arquivar conversa", chat_qml)
        self.assertIn("Excluir conversa", chat_qml)
        self.assertIn("Keys.onReturnPressed", composer_qml)
        self.assertIn("Keys.onEnterPressed", composer_qml)
        markdown_qml = (MAIN_QML.parent / "components" / "VrMarkdownContent.qml").read_text(encoding="utf-8")
        self.assertIn("onLinkActivated", markdown_qml)
        self.assertIn("onLinkActivated", knowledge_qml)
        self.assertNotIn("Digite EXCLUIR", settings_qml)
        header_qml = (MAIN_QML.parent / "components" / "VrChatHeader.qml").read_text(encoding="utf-8")
        self.assertIn('objectName: "conversationSidebarToggle"', header_qml)
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
            folder = next(item for item in values if item["label"] == "src")
            self.assertTrue(folder["isDirectory"])
            self.assertEqual(folder["depth"], 0)
            selected = next(item for item in values if item["label"] == "src/main.py")
            self.assertEqual(Path(selected["path"]), expected)
            self.assertFalse(selected["isDirectory"])
            self.assertEqual(selected["parent"], "src")
            self.assertEqual(selected["depth"], 1)

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

    def test_image_attachment_in_composer_shows_thumbnail(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            image = settings.root / "evidencia.png"
            image.write_bytes(b"png data")
            bridge = self._bridge(root, initial_page="Chat VR")
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            chat_bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()
            try:
                window = engine.rootObjects()[0]
                composer = window.findChild(QObject, "chatComposerCard")
                self.assertIsNotNone(composer)
                self.assertFalse(composer.property("hasImageAttachments"))
                chat_bridge.addDroppedAttachments([QUrl.fromLocalFile(str(image))])
                self.application.processEvents()
                self.assertTrue(composer.property("hasImageAttachments"))
                self.assertEqual(chat_bridge.attachmentSizeLabel(str(image)), "8 B")
                thumbnails_list = window.findChild(QObject, "chatAttachmentThumbnailsList")
                self.assertIsNotNone(thumbnails_list)
                thumbnails_list.forceLayout()
                self.application.processEvents()
                content_item = thumbnails_list.property("contentItem")
                thumbnail = next((sub for item in content_item.childItems() for sub in item.childItems() if sub.property("objectName") == "chatAttachmentThumbnail"), None)
                self.assertIsNotNone(thumbnail)
                self.assertTrue(thumbnail.property("visible"))
                self.assertEqual(thumbnail.property("width"), 60)
                self.assertEqual(thumbnail.property("height"), 60)
                attachment_list = window.findChild(QObject, "chatAttachmentList")
                self.assertIsNotNone(attachment_list)
                self.assertEqual(attachment_list.property("count"), 1)
            finally:
                window.close()
                engine.deleteLater()

    def test_unsent_text_and_images_are_persisted_as_a_separate_draft(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            settings.root.mkdir(parents=True)
            image = settings.root / "rascunho.png"
            image.write_bytes(b"png")
            preferences = QSettings(
                str(root / "preferences.ini"), QSettings.IniFormat
            )
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = ChatBridge(settings, database, preferences)
            bridge.addDroppedAttachments([QUrl.fromLocalFile(str(image))])

            self.assertTrue(bridge.saveCurrentDraft("Texto ainda não enviado"))
            self.assertEqual(bridge.conversationCount, 1)
            draft = bridge.conversations.item(0)
            self.assertTrue(draft["editing"])
            self.assertEqual(draft["section"], "Rascunhos")
            conversation_id = draft["conversationId"]

            bridge.startNewChat()
            self.assertEqual(bridge.attachments, [])
            restored: list[str] = []
            bridge.draftRestored.connect(restored.append)
            bridge.selectConversationId(conversation_id)
            self.assertEqual(restored[-1], "Texto ainda não enviado")
            self.assertEqual(bridge.attachments[0]["path"], str(image))

            reloaded = ChatBridge(settings, database, preferences)
            self.assertTrue(reloaded.conversations.item(0)["editing"])

            # Discarding empty draft removes it and trashes empty conversation
            self.assertTrue(reloaded.discardDraft(conversation_id))
            self.assertEqual(reloaded.conversationCount, 0)
            self.assertEqual(len(database.list_conversations(state="active")), 0)

    def test_discard_draft_preserves_conversation_with_messages(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            cid = database.create_conversation("Conversa Existente", "codex", "gpt-5.6", settings.root)
            database.add_message(cid, "user", "Olá")
            database.add_message(cid, "assistant", "Olá! Como posso ajudar?")
            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = ChatBridge(settings, database, preferences)
            bridge.selectConversationId(cid)
            bridge.saveCurrentDraft("Rascunho de nova mensagem")
            self.assertTrue(bridge.conversations.item(0)["editing"])
            self.assertEqual(bridge.conversations.item(0)["section"], "Rascunhos")

            # Discarding draft removes draft status but keeps conversation and messages
            self.assertTrue(bridge.discardDraft(cid))
            self.assertEqual(bridge.conversationCount, 1)
            self.assertFalse(bridge.conversations.item(0)["editing"])
            self.assertEqual(bridge.conversations.item(0)["section"], "Conversas")
            self.assertEqual(len(database.messages(cid)), 2)

    def test_pinned_conversations_sort_before_regular_active_chats(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            first = database.create_conversation(
                "Primeira", "codex", "modelo", settings.root
            )
            second = database.create_conversation(
                "Segunda", "codex", "modelo", settings.root
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            bridge.selectConversationId(first)
            bridge.togglePinnedCurrent()

            self.assertEqual(bridge.conversations.item(0)["conversationId"], first)
            self.assertTrue(bridge.conversations.item(0)["pinned"])
            self.assertEqual(bridge.conversations.item(1)["conversationId"], second)

    def test_conversations_expose_vr_mode_and_badge_roles(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            off_id = database.create_conversation(
                "Normal Chat", "codex", "modelo", settings.root, vr_enabled=False, vr_mode="off"
            )
            vr_id = database.create_conversation(
                "VR Chat", "codex", "modelo", settings.root, vr_enabled=True, vr_mode="vr"
            )
            ultra_id = database.create_conversation(
                "Ultra Chat", "codex", "modelo", settings.root, vr_enabled=True, vr_mode="ultra"
            )

            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = ChatBridge(settings, database, preferences)

            items = {
                bridge.conversations.item(i)["conversationId"]: bridge.conversations.item(i)
                for i in range(bridge.conversationCount)
            }

            self.assertEqual(items[off_id]["vrMode"], "off")
            self.assertFalse(items[off_id]["vrEnabled"])

            self.assertEqual(items[vr_id]["vrMode"], "vr")
            self.assertTrue(items[vr_id]["vrEnabled"])

            self.assertEqual(items[ultra_id]["vrMode"], "ultra")
            self.assertTrue(items[ultra_id]["vrEnabled"])

            bridge.selectConversationId(off_id)
            bridge.setVrMode("vr")
            updated_item = next(
                bridge.conversations.item(i)
                for i in range(bridge.conversationCount)
                if bridge.conversations.item(i)["conversationId"] == off_id
            )
            self.assertEqual(updated_item["vrMode"], "vr")
            self.assertTrue(updated_item["vrEnabled"])

            chat_preview_qml = (
                MAIN_QML.parent / "pages" / "ChatPreview.qml"
            ).read_text(encoding="utf-8")
            self.assertIn('objectName: "conversationVrBadge"', chat_preview_qml)
            self.assertIn("required property string vrMode", chat_preview_qml)
            self.assertIn("required property bool vrEnabled", chat_preview_qml)
            self.assertIn('text: conversationItem.vrMode === "ultra" ? "VR Ultra" : "VR"', chat_preview_qml)
            self.assertIn("Theme.palette.accessibleOrange", chat_preview_qml)
            composer_qml = (
                MAIN_QML.parent / "components" / "VrChatComposer.qml"
            ).read_text(encoding="utf-8")
            theme_qml = (
                MAIN_QML.parent / "theme" / "Theme.qml"
            ).read_text(encoding="utf-8")
            # VR/VR Ultra keep the fixed orange identity (ring/halo/label)
            # instead of inheriting the theme's remapped accent.
            self.assertIn("readonly property color vrAccent", theme_qml)
            # A aura laranja saiu do contorno do composer: em repouso e no foco
            # o campo mantém a borda neutra; o laranja fica só no arraste.
            self.assertNotIn("composerCard.vrActive && !composerCard.isCompact", composer_qml)
            self.assertNotIn("Qt.alpha(Theme.vrAccent, 0.45)", composer_qml)
            self.assertIn("composerCard.vrActive ? Theme.vrAccent : Theme.palette.brandOrange", composer_qml)
            self.assertIn("? Theme.vrAccent", composer_qml)
            self.assertIn("Qt.alpha(Theme.vrAccent, 0.12)", chat_preview_qml)
            # O anel do Ultra só existe no composer expandido.
            self.assertIn(
                'visible: root.chatBridge.vrMode === "ultra" && !composerCard.isCompact',
                chat_preview_qml,
            )

    def test_vr_mode_tag_stays_fixed_until_question_sent_with_different_mode(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            cid = database.create_conversation(
                "VR Chat", "codex", "modelo", settings.root, vr_enabled=True, vr_mode="vr"
            )
            database.add_message(cid, "user", "Pergunta em VR")
            database.add_message(cid, "assistant", "Resposta em VR")

            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = ChatBridge(settings, database, preferences)

            item = next(
                bridge.conversations.item(i)
                for i in range(bridge.conversationCount)
                if bridge.conversations.item(i)["conversationId"] == cid
            )
            self.assertEqual(item["vrMode"], "vr")
            self.assertTrue(item["vrEnabled"])

            bridge.selectConversationId(cid)
            self.assertEqual(bridge.vrMode, "vr")

            # 1. Changing composer mode to ultra must NOT change the conversation item's tag
            bridge.setVrMode("ultra")
            self.assertEqual(bridge.vrMode, "ultra")
            self.assertEqual(database.get_conversation(cid)["vr_mode"], "vr")

            item_during_edit = next(
                bridge.conversations.item(i)
                for i in range(bridge.conversationCount)
                if bridge.conversations.item(i)["conversationId"] == cid
            )
            self.assertEqual(item_during_edit["vrMode"], "vr")
            self.assertTrue(item_during_edit["vrEnabled"])

            # 2. Saving a draft in ultra mode must also NOT change the conversation item's tag
            bridge.saveCurrentDraft("Rascunho no modo ultra")
            item_with_draft = next(
                bridge.conversations.item(i)
                for i in range(bridge.conversationCount)
                if bridge.conversations.item(i)["conversationId"] == cid
            )
            self.assertEqual(item_with_draft["vrMode"], "vr")

            # 3. Sending another question with ultra mode now changes the tag to 'ultra'
            from tests.test_mary_orchestration import FakeProvider
            fake_provider = FakeProvider("codex")
            bridge._orchestrator.providers["codex"] = fake_provider
            bridge.sendMessage("Pergunta enviada no modo ultra")
            for _ in range(400):
                status = str(database.get_conversation(cid)["status"] or "idle")
                if status != "running":
                    break
                self.application.processEvents()
                QTest.qWait(50)
            bridge._finalize_terminal_state("turn_completed")

            item_after_ultra = next(
                bridge.conversations.item(i)
                for i in range(bridge.conversationCount)
                if bridge.conversations.item(i)["conversationId"] == cid
            )
            self.assertEqual(item_after_ultra["vrMode"], "ultra")
            self.assertTrue(item_after_ultra["vrEnabled"])
            self.assertEqual(database.get_conversation(cid)["vr_mode"], "ultra")

            # 4. Changing composer mode to off must keep tag at 'ultra' until question is sent
            bridge.setVrMode("off")
            self.assertEqual(bridge.vrMode, "off")
            self.assertEqual(database.get_conversation(cid)["vr_mode"], "ultra")

            # 5. Sending question in off mode now changes the tag to off
            bridge.sendMessage("Pergunta enviada no modo off")
            for _ in range(400):
                status = str(database.get_conversation(cid)["status"] or "idle")
                if status != "running":
                    break
                self.application.processEvents()
                QTest.qWait(50)
            bridge._finalize_terminal_state("turn_completed")

            item_after_off = next(
                bridge.conversations.item(i)
                for i in range(bridge.conversationCount)
                if bridge.conversations.item(i)["conversationId"] == cid
            )
            self.assertEqual(item_after_off["vrMode"], "off")
            self.assertFalse(item_after_off["vrEnabled"])
            self.assertEqual(database.get_conversation(cid)["vr_mode"], "off")
            bridge.close()


    def test_context_uses_provider_model_metadata_and_hides_without_it(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            conversation_id = database.create_conversation(
                "Contexto", "codex", "gpt-provider", settings.root
            )
            database.update_conversation(
                conversation_id,
                context_used_tokens=25_800,
                context_window_tokens=200_000,
            )
            bridge = ChatBridge(
                settings,
                database,
                QSettings(str(root / "preferences.ini"), QSettings.IniFormat),
            )
            bridge.selectConversationId(conversation_id)
            bridge._model_items = [{
                "key": "codex:gpt-provider",
                "provider": "codex",
                "value": "gpt-provider",
                "displayName": "GPT Provider",
                "contextWindow": 258_000,
            }]

            self.assertTrue(bridge.hasContextWindow)
            self.assertEqual(bridge.contextUsageFraction, 0.1)
            self.assertIn("258.000", bridge.contextUsageLabel)
            database.update_conversation(conversation_id, context_used_tokens=0)
            self.assertFalse(bridge.hasContextWindow)
            database.update_conversation(conversation_id, context_used_tokens=25_800)
            self.assertTrue(bridge.hasContextWindow)
            bridge._model_items[0].pop("contextWindow")
            self.assertFalse(bridge.hasContextWindow)

            browser_event = RuntimeEvent(
                conversation_id,
                "tool_event",
                payload={
                    "item": {
                        "type": "browser_navigation",
                        "url": "https://example.com/preview",
                    }
                },
            )
            self.assertEqual(
                bridge._browser_address_from_event(browser_event),
                "https://example.com/preview",
            )

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

    def test_model_picker_opens_favorites_and_builds_enabled_provider_filters(self):
        picker_qml = (
            MAIN_QML.parent / "components" / "VrModelPicker.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('property string providerFilter: "favorites"', picker_qml)
        self.assertIn('{key: "favorites"', picker_qml)
        self.assertIn("model: control.providerTabs()", picker_qml)
        self.assertIn("if (item.inactive === true) return false", picker_qml)
        self.assertNotIn('{key: "all"', picker_qml)
        self.assertNotIn("ToolTip.visible", picker_qml)
        self.assertIn("CloseOnPressOutsideParent", picker_qml)

        self.assertNotIn("createLinearGradient", picker_qml)

    def test_draft_catalog_moves_away_from_a_disabled_provider(self):
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
            preferences.setValue("providers/claude/enabled", False)
            preferences.sync()
            bridge = ChatBridge(settings, database, preferences)
            bridge._draft = True
            bridge._provider = "claude"
            bridge._model = "claude-sonnet"
            bridge._model_items = [{
                "key": "claude:claude-sonnet",
                "provider": "claude",
                "value": "claude-sonnet",
                "label": "Claude Sonnet",
            }]

            bridge._apply_model_catalog([{
                "key": "codex:gpt-test",
                "provider": "codex",
                "value": "gpt-test",
                "label": "GPT Test",
            }])

            self.assertEqual((bridge._provider, bridge._model), ("codex", "gpt-test"))
            self.assertFalse(any(item.get("inactive") for item in bridge.modelItems))

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
        self.assertIn("Flickable.HorizontalFlick", tab_bar_qml)
        self.assertNotIn("Flow {", tab_bar_qml)
        self.assertIn("Theme.palette.accentSoft", tab_bar_qml)
        self.assertNotIn('"primary" : "ghost"', settings_qml)
        self.assertNotIn("variant: root.tabIndex === index", settings_qml)
        self.assertIn("objectName: \"settingsTabBar\"", settings_qml)
        self.assertIn("variant: \"danger\"", settings_qml)
        self.assertNotIn("deleteConfirmField", settings_qml)
        self.assertIn('"Aparência", "Browser"', settings_qml)
        self.assertIn('objectName: "interfaceFontCombo"', settings_qml)
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
        self.assertIn("pages[6] = true", hub_qml)
        self.assertIn('objectName: "settingsConversationSearch"', hub_qml)
        self.assertIn('objectName: "settingsReturnButton"', hub_qml)
        self.assertIn('Accessible.name: "Retornar ao Chat VR"', hub_qml)
        self.assertNotIn('visible: root.settingsActive', hub_qml)
        self.assertNotIn('Accessible.name: "Abrir Configurações"', hub_qml)
        self.assertNotIn('title: "Chat VR"', hub_qml)
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
            window.setWidth(1280)
            window.setHeight(820)
            window.show()
            QTest.qWait(100)
            tab_bar = window.findChild(QObject, "settingsTabBar")
            self.assertIsNotNone(tab_bar)
            settings_search = window.findChild(QObject, "settingsConversationSearch")
            settings_return = window.findChild(QObject, "settingsReturnButton")
            settings_navigation = window.findChild(QObject, "settingsNavigation")
            settings_results = window.findChild(QObject, "settingsSearchResults")
            settings_hub = window.findChild(QObject, "settingsHub")
            self.assertIsNotNone(settings_search)
            self.assertIsNotNone(settings_return)
            self.assertIsNotNone(settings_navigation)
            self.assertIsNotNone(settings_results)
            self.assertIsNotNone(settings_hub)
            self.assertTrue(settings_return.property("visible"))
            self.assertGreater(
                settings_return.property("y"),
                settings_navigation.property("height") * 0.65,
            )
            settings_search.setProperty("text", "JAR")
            self.application.processEvents()
            self.assertTrue(settings_results.property("visible"))
            self.assertGreater(settings_results.property("count"), 0)
            self.assertEqual(chat_bridge.search, "")
            self.assertEqual(tab_bar.property("count"), 8)
            self.assertEqual(tab_bar.property("currentIndex"), 0)
            self.assertTrue(settings_hub.activateSettingSearchResult(0))
            self.application.processEvents()
            self.assertEqual(tab_bar.property("currentIndex"), 3)
            settings_search.clear()
            self.application.processEvents()
            tab_bar.activate(0)
            self.application.processEvents()
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
            # Under the new auto-scale architecture (High-DPI / system DPI based, not window-dimension based),
            # resizing window dimensions preserves stable font rendering.
            self.assertEqual(
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

            # All settings tabs share the compact navigation behavior.
            window.setWidth(390)
            QTest.qWait(80)
            compact_return = window.findChild(QObject, "settingsCompactReturn")
            for tab in range(6):
                tab_bar.activate(tab)
                self.application.processEvents()
                self.assertFalse(settings_navigation.property("visible"))
                self.assertTrue(compact_return.property("visible"))
            window.setWidth(1280)
            QTest.qWait(80)
            self.assertTrue(settings_navigation.property("visible"))

            bridge.setCurrentPage(0)
            self.application.processEvents()
            self.assertTrue(settings_return.property("visible"))

            settings_return.click()
            self.application.processEvents()
            self.assertEqual(bridge.currentPage, 1)
            self.assertFalse(settings_return.property("visible"))
            chat_settings = window.findChild(QObject, "chatSettingsButton")
            self.assertIsNotNone(chat_settings)
            self.assertTrue(chat_settings.property("visible"))

    def test_sidebar_hover_transition_never_darkens_below_its_endpoints(self):
        from test_chat_presentation import find_items

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path,
                root=settings.root,
                backup_portable_migration=False,
            )
            bridge = self._bridge(root, theme="ocean", initial_page="Configurações")
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
            window.setWidth(1280)
            window.setHeight(820)
            window.show()
            QTest.qWait(250)
            self.assertFalse(bridge.reduceMotion)

            items = {
                item.property("title"): item
                for item in find_items(window.contentItem(), "settingsNavItem")
            }
            self.assertIn("Revisão", items)
            self.assertIn("Vídeos", items)
            review = items["Revisão"]

            def sample_row(item):
                image = window.grabWindow()
                ratio = image.devicePixelRatio()
                point = item.mapToScene(QPointF(item.width() - 8, item.height() / 2))
                return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))

            def luminance(color):
                return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()

            rest = sample_row(review)
            target = review.mapToScene(
                QPointF(review.width() / 2, review.height() / 2)
            ).toPoint()
            QTest.mouseMove(window, target)
            frames = []
            for _ in range(24):
                QTest.qWait(8)
                frames.append(sample_row(review))
            QTest.qWait(140)
            hovered = sample_row(review)
            self.assertGreater(luminance(hovered), luminance(rest))
            floor = min(luminance(rest), luminance(hovered)) - 0.02
            for index, frame in enumerate(frames):
                self.assertGreaterEqual(
                    luminance(frame),
                    floor,
                    f"hover frame {index} darker than the endpoints: {frame.name()}",
                )

            QTest.mouseMove(window, QPoint(1, 1))
            window.close()
            engine.deleteLater()
            self.application.processEvents()

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



    def test_chat_page_survives_first_navigation_and_hover(self):
        import cProfile
        from PySide6.QtCore import QPoint
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            bridge = self._bridge(root, initial_page='Chat VR')
            database = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
            chat_bridge = ChatBridge(settings, database, QSettings(str(root / 'preferences.ini'), QSettings.IniFormat))
            with patch.object(chat_bridge, 'refreshModels'):
                engine = create_engine(bridge, chat_bridge)
                self.application.processEvents()
                window = engine.rootObjects()[0]
                page = window.findChild(QObject, 'chatPage')
                self.assertIsNotNone(page)
                for destination in (7, 1, 0, 1, 7, 1):
                    bridge.setCurrentPage(destination)
                    self.application.processEvents()
                    self.assertIs(window.findChild(QObject, 'chatPage'), page)
                QTest.qWait(250)
                profiler = cProfile.Profile()
                profiler.enable()
                for x in range(300, 1000, 10):
                    QTest.mouseMove(window, QPoint(x, window.height() - 85))
                    self.application.processEvents()
                profiler.disable()
                palette_calls = sum(entry.callcount for entry in profiler.getstats()
                                    if getattr(entry.code, 'co_name', '') == 'palette'
                                    and 'frontend' in getattr(entry.code, 'co_filename', ''))
                self.assertEqual(palette_calls, 0)
                errors = [warning.toString() for warning in engine._qml_warnings
                          if 'incubation' in warning.toString() or 'Cannot create delegate' in warning.toString()]
                self.assertEqual(errors, [])
                window.close()
                engine.deleteLater()
                self.application.processEvents()



    def test_antigravity_models_do_not_expose_reasoning_effort_picker(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
            bridge = ChatBridge(settings, database, QSettings(str(root / "preferences.ini"), QSettings.IniFormat))
            bridge._provider = "antigravity"
            bridge._model = "gemini-3.8-flash-high"
            bridge._effort = "low"
            item = {"provider": "antigravity", "value": "gemini-3.8-flash-high",
                    "key": "antigravity:gemini-3.8-flash-high", "displayName": "Gemini 3.8 Flash (High)",
                    "aliases": ["gemini-3.8-flash-high"],
                    "efforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}]}
            with patch.object(bridge, "_enabled_provider_names", return_value=["antigravity"]):
                bridge._apply_model_catalog([item])
            self.assertEqual(len(bridge.modelItems), 1)
            self.assertEqual(bridge.modelItems[bridge.modelIndex]["displayName"], "Gemini 3.8 Flash (High)")
            self.assertEqual(bridge.effortItems, [])
            self.assertFalse(bridge.supportsReasoning)
            self.assertEqual(bridge.effortIndex, -1)


    def test_apps_settings_page_app_selector_filtering_and_selection(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = self._bridge(root, initial_page="Configurações")
            chat_bridge = ChatBridge(settings, database, preferences)

            sample_catalog = [
                {
                    "appId": "vradm",
                    "name": "VRAdm",
                    "versionCount": 3,
                    "readyCount": 3,
                    "pendingCount": 0,
                    "failedCount": 0,
                    "hasUnidentified": False,
                    "hasVariants": False,
                },
                {
                    "appId": "vratacado",
                    "name": "VRAtacado",
                    "versionCount": 1,
                    "readyCount": 1,
                    "pendingCount": 0,
                    "failedCount": 0,
                    "hasUnidentified": False,
                    "hasVariants": False,
                },
            ]
            chat_bridge._applications_catalog = sample_catalog
            chat_bridge.stateChanged.emit()

            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()
            window = engine.rootObjects()[0]
            window.setWidth(1280)
            window.setHeight(820)
            window.show()
            try:
                settings_page = window.findChild(QObject, "settingsPage")
                self.assertIsNotNone(settings_page)
                settings_page.setProperty("tabIndex", 3)
                # The page auto-refreshes the real catalog on load, which
                # replaces the injected sample when it finishes. Let that
                # worker start and settle first, then (re)inject the sample so
                # the selector assertions below are deterministic.
                for _attempt in range(100):
                    self.application.processEvents()
                    if (
                        chat_bridge._apps_catalog_thread is not None
                        or chat_bridge.applicationsCatalogLoaded
                    ):
                        break
                    QTest.qWait(10)
                for _attempt in range(600):
                    self.application.processEvents()
                    if chat_bridge._apps_catalog_thread is None:
                        break
                    QTest.qWait(10)
                self.assertIsNone(chat_bridge._apps_catalog_thread)
                chat_bridge._applications_catalog = sample_catalog
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                for _attempt in range(40):
                    self.application.processEvents()
                    if window.findChild(QObject, "appSelector") is not None:
                        break
                    QTest.qWait(10)

                app_selector = window.findChild(QObject, "appSelector")
                self.assertIsNotNone(app_selector)
                self.assertTrue(app_selector.property("visible"))

                apps_page = window.findChild(QObject, "appsSettingsPage")
                export_button = window.findChild(QObject, "exportDecompiledCodeButton")
                import_card = window.findChild(QObject, "appsImportCard")
                packages_panel = window.findChild(QObject, "applicationsPackagesPanel")
                import_toggle = window.findChild(QObject, "toggleImportToolsButton")
                packages_toggle = window.findChild(QObject, "togglePackagesButton")
                administration_bar = window.findChild(
                    QObject, "applicationsAdministrationBar"
                )
                self.assertIsNotNone(apps_page)
                self.assertIsNotNone(export_button)
                self.assertIsNotNone(import_card)
                self.assertIsNotNone(packages_panel)
                self.assertIsNotNone(import_toggle)
                self.assertIsNotNone(packages_toggle)
                self.assertIsNotNone(administration_bar)
                self.assertEqual(apps_page.property("navigationLevel"), 0)
                self.assertEqual(apps_page.property("totalApplications"), 2)
                self.assertEqual(apps_page.property("totalVersions"), 4)
                self.assertEqual(apps_page.property("totalReadyVersions"), 4)
                self.assertEqual(apps_page.property("totalPendingVersions"), 0)
                self.assertEqual(apps_page.property("totalFailedVersions"), 0)
                self.assertIsNotNone(
                    window.findChild(QObject, "applicationsCatalogHeader")
                )
                self.assertIsNotNone(
                    window.findChild(QObject, "applicationsCatalogMetrics")
                )
                self.assertLess(app_selector.y(), administration_bar.y())
                self.assertFalse(import_card.isVisible())
                self.assertFalse(packages_panel.isVisible())
                import_toggle.clicked.emit()
                self.application.processEvents()
                self.assertTrue(import_card.isVisible())
                import_toggle.clicked.emit()
                self.application.processEvents()
                self.assertFalse(import_card.isVisible())
                packages_toggle.clicked.emit()
                self.application.processEvents()
                self.assertTrue(packages_panel.isVisible())
                packages_toggle.clicked.emit()
                self.application.processEvents()
                self.assertFalse(packages_panel.isVisible())
                self.assertIsNone(
                    window.findChild(QObject, "appSelectorHeaderBatchDecompile")
                )
                self.assertIsNone(
                    window.findChild(QObject, "appSelectorBatchDecompile")
                )
                self.assertFalse(export_button.isVisible())
                ancestor = export_button.parent()
                while ancestor is not None:
                    self.assertIsNot(ancestor, import_card)
                    ancestor = ancestor.parent()

                chat_bridge._selected_app_id = "vrmaster"
                chat_bridge._selected_app_version = "4.1.0"
                chat_bridge._selected_app_variant_id = "sha-master"
                chat_bridge._selected_app_origin_id = "release-a"
                chat_bridge._selected_version_details = {
                    "indexed_classes": 1,
                    "origin_packages": [{"package_id": "release-a", "index_state": "ready"}],
                }
                apps_page.setProperty("navigationLevel", 1)
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertTrue(
                    window.findChild(QObject, "applicationHistoryContextCard").isVisible()
                )
                apps_page.setProperty("navigationLevel", 2)
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertTrue(export_button.isVisible())
                self.assertTrue(export_button.property("enabled"))
                self.assertIsNotNone(
                    window.findChild(QObject, "applicationVersionContextCard")
                )
                self.assertIsNotNone(
                    window.findChild(QObject, "applicationVersionTabs")
                )
                apps_page.setProperty("versionSubTab", 1)
                self.application.processEvents()
                advanced_panel = window.findChild(QObject, "processingAdvancedPanel")
                advanced_toggle = window.findChild(QObject, "processingAdvancedToggle")
                self.assertIsNotNone(advanced_panel)
                self.assertIsNotNone(advanced_toggle)
                self.assertFalse(advanced_panel.isVisible())
                advanced_toggle.clicked.emit()
                self.application.processEvents()
                self.assertTrue(advanced_panel.isVisible())
                advanced_toggle.clicked.emit()
                self.application.processEvents()
                self.assertFalse(advanced_panel.isVisible())
                apps_page.setProperty("versionSubTab", 0)
                self.application.processEvents()

                comparison_metrics = [
                    window.findChild(QObject, "applicationComparisonAddedMetric"),
                    window.findChild(QObject, "applicationComparisonModifiedMetric"),
                    window.findChild(QObject, "applicationComparisonRemovedMetric"),
                    window.findChild(QObject, "applicationComparisonUnchangedMetric"),
                ]
                for metric in comparison_metrics:
                    self.assertIsNotNone(metric)
                self.assertEqual(
                    len({metric.property("radius") for metric in comparison_metrics}), 1
                )
                self.assertEqual(
                    len({metric.property("color").name() for metric in comparison_metrics}), 1
                )

                pause_button = window.findChild(QObject, "appsBatchPauseButton")
                cancel_button = window.findChild(QObject, "appsBatchCancelButton")
                self.assertIsNotNone(pause_button)
                self.assertIsNotNone(cancel_button)
                self.assertGreaterEqual(pause_button.property("implicitHeight"), 28)
                self.assertGreaterEqual(cancel_button.property("implicitHeight"), 28)

                pending_only_button = window.findChild(QObject, "appSelectorPendingOnlyButton")
                clear_selection_button = window.findChild(QObject, "appSelectorClearSelectionButton")
                self.assertIsNotNone(pending_only_button)
                self.assertIsNotNone(clear_selection_button)
                self.assertGreaterEqual(pending_only_button.property("implicitHeight"), 28)
                app_selector.openSelector()
                app_selector.setProperty("selectedAppIds", ["vratacado", "vradm"])
                app_selector.setProperty("searchText", "")
                self.application.processEvents()
                self.assertTrue(clear_selection_button.property("visible"))
                self.assertGreaterEqual(clear_selection_button.property("implicitHeight"), 28)
                app_selector.setProperty("selectedAppIds", [])
                app_selector.closeSelector()
                self.application.processEvents()
                self.assertGreaterEqual(clear_selection_button.property("implicitHeight"), 28)
                app_selector.setProperty("selectedAppIds", [])
                self.application.processEvents()

                export_calls = []

                def fake_export(*args, **kwargs):
                    export_calls.append((args, kwargs))
                    return {"success": True, "destination": str(root), "file_count": 1, "total_bytes": 1}

                with patch.object(codeadmin.QFileDialog, "getExistingDirectory", return_value=str(root)):
                    with patch.object(codeadmin, "export_decompiled_source", side_effect=fake_export):
                        self.assertTrue(QMetaObject.invokeMethod(export_button, "click"))
                        for _attempt in range(100):
                            self.application.processEvents()
                            if export_calls and not chat_bridge.releaseSnapshotRunning:
                                break
                            QTest.qWait(10)

                self.assertEqual(len(export_calls), 1)
                self.assertEqual(export_calls[0][1]["application_id"], "vrmaster")
                self.assertEqual(export_calls[0][1]["version"], "4.1.0")
                self.assertEqual(export_calls[0][1]["variant_id"], "sha-master")
                self.assertEqual(export_calls[0][1]["origin_id"], "release-a")

                for field in ("_selected_app_origin_id", "_selected_app_variant_id"):
                    previous = getattr(chat_bridge, field)
                    setattr(chat_bridge, field, "")
                    chat_bridge.stateChanged.emit()
                    self.application.processEvents()
                    self.assertFalse(export_button.property("enabled"), field)
                    setattr(chat_bridge, field, previous)

                chat_bridge._code_processing_running = True
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertFalse(export_button.property("enabled"))
                chat_bridge._code_processing_running = False
                chat_bridge._decompiled_export_running = True
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertFalse(export_button.property("enabled"))
                chat_bridge._decompiled_export_running = False
                chat_bridge.stateChanged.emit()
                self.application.processEvents()

                app_selector.setProperty("searchText", "atacado")
                filtered_raw = app_selector.property("filteredApps")
                filtered = (
                    filtered_raw.toVariant()
                    if hasattr(filtered_raw, "toVariant")
                    else filtered_raw
                )
                self.assertEqual(len(filtered), 1)
                self.assertEqual(filtered[0]["appId"], "vratacado")

                app_selector.setProperty("searchText", "")
                filtered_all_raw = app_selector.property("filteredApps")
                filtered_all = (
                    filtered_all_raw.toVariant()
                    if hasattr(filtered_all_raw, "toVariant")
                    else filtered_all_raw
                )
                self.assertEqual(len(filtered_all), 2)

                selected = []
                app_selector.applicationSelected.connect(selected.append)
                app_selector.applicationSelected.emit("vratacado")
                self.assertEqual(selected, ["vratacado"])

                popup = window.findChild(QObject, "appSelectorPopup")
                self.assertIsNotNone(popup)
                self.assertFalse(popup.property("opened"))

                app_selector.toggleSelector()
                self.application.processEvents()
                self.assertTrue(popup.property("opened"))

                app_selector.toggleSelector()
                self.application.processEvents()
                self.assertFalse(popup.property("opened"))

                selector_qml = (MAIN_QML.parent / "components" / "VrAppSelector.qml").read_text(encoding="utf-8")
                self.assertIn("CloseOnPressOutsideParent", selector_qml)
                self.assertIn("VrCheckBox", selector_qml)
                self.assertIn("batchDecompileRequested", selector_qml)
                self.assertIn("selectedAppIds", selector_qml)
                self.assertIn("allFilteredSelected", selector_qml)

                settings_qml = (MAIN_QML.parent / "pages" / "ApplicationsSettingsPage.qml").read_text(encoding="utf-8")
                self.assertIn("onBatchDecompileRequested", settings_qml)
                self.assertIn("startBatchAppsProcessing", settings_qml)
                self.assertIn("appsBatchActionCard", settings_qml)
                self.assertIn("appsBatchProcessingStatusCard", settings_qml)
            finally:
                window.close()
                engine.deleteLater()
                self.application.processEvents()


    def test_app_selector_batch_selection_component(self):
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        engine = QQmlEngine()
        engine.addImportPath(str(MAIN_QML.parent))
        component = QQmlComponent(engine, str(MAIN_QML.parent / "components" / "VrAppSelector.qml"))
        self.assertEqual(component.status(), QQmlComponent.Status.Ready, [e.toString() for e in component.errors()])
        item = component.create()
        self.assertIsNotNone(item)
        try:
            item.setProperty("model", [
                {"appId": "vradm", "name": "VRAdm", "pendingCount": 1},
                {"appId": "vratacado", "name": "VRAtacado", "pendingCount": 0},
            ])
            selected_ids = item.property("selectedAppIds")
            if hasattr(selected_ids, "toVariant"):
                selected_ids = selected_ids.toVariant()
            self.assertEqual(selected_ids, [])
            self.assertFalse(item.property("allFilteredSelected"))

            item.setProperty("selectedAppIds", ["vradm"])
            self.assertFalse(item.property("allFilteredSelected"))

            item.setProperty("selectedAppIds", ["vradm", "vratacado"])
            self.assertTrue(item.property("allFilteredSelected"))

            item.setProperty("selectedAppIds", [])
            self.assertFalse(item.property("allFilteredSelected"))

            self.assertTrue(QMetaObject.invokeMethod(item, "selectAllFiltered"))
            selected_ids = item.property("selectedAppIds")
            if hasattr(selected_ids, "toVariant"):
                selected_ids = selected_ids.toVariant()
            self.assertEqual(selected_ids, ["vradm", "vratacado"])

            self.assertTrue(QMetaObject.invokeMethod(item, "deselectAllFiltered"))
            selected_ids = item.property("selectedAppIds")
            if hasattr(selected_ids, "toVariant"):
                selected_ids = selected_ids.toVariant()
            self.assertEqual(selected_ids, [])

            self.assertTrue(QMetaObject.invokeMethod(item, "selectPendingOnly"))
            selected_ids = item.property("selectedAppIds")
            if hasattr(selected_ids, "toVariant"):
                selected_ids = selected_ids.toVariant()
            self.assertEqual(selected_ids, ["vradm"])

            self.assertTrue(QMetaObject.invokeMethod(item, "clearSelection"))
            selected_ids = item.property("selectedAppIds")
            if hasattr(selected_ids, "toVariant"):
                selected_ids = selected_ids.toVariant()
            self.assertEqual(selected_ids, [])

            batch_emitted = []
            item.batchDecompileRequested.connect(batch_emitted.append)
            item.batchDecompileRequested.emit(["vradm", "vratacado"])
            self.assertEqual(batch_emitted, [["vradm", "vratacado"]])
        finally:
            item.deleteLater()
            engine.deleteLater()
            self.application.processEvents()


    def test_global_decompile_config_dialog_and_buttons(self):
        qml = (MAIN_QML.parent / "pages" / "ApplicationsSettingsPage.qml").read_text(encoding="utf-8")
        self.assertIn('objectName: "globalDecompileConfigHeaderButton"', qml)
        self.assertIn('objectName: "batchDecompileSettingsButton"', qml)
        self.assertIn('objectName: "globalDecompileConfigDialog"', qml)
        self.assertIn('objectName: "globalDecompileHeapPicker"', qml)
        self.assertIn('objectName: "globalDecompileTimeoutPicker"', qml)
        self.assertIn('objectName: "globalDecompileCpuPicker"', qml)
        self.assertIn('objectName: "globalDecompileDiskPicker"', qml)
        self.assertIn('objectName: "globalDecompileWindowPicker"', qml)
        self.assertIn('objectName: "globalDecompileCloseButton"', qml)

    def test_applications_overhaul_uses_shared_navigation_and_progressive_disclosure(self):
        apps_qml = (
            MAIN_QML.parent / "pages" / "ApplicationsSettingsPage.qml"
        ).read_text(encoding="utf-8")
        selector_qml = (
            MAIN_QML.parent / "components" / "VrAppSelector.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('text: "Aplicativos e versões"', apps_qml)
        self.assertIn('objectName: "applicationsCatalogMetrics"', apps_qml)
        self.assertIn('objectName: "applicationHistoryContextCard"', apps_qml)
        self.assertIn('text: "Abrir versão"', apps_qml)
        self.assertIn('objectName: "applicationVersionContextCard"', apps_qml)
        self.assertIn('objectName: "appVariantPicker"', apps_qml)
        self.assertIn('objectName: "appOriginPicker"', apps_qml)
        self.assertIn('objectName: "applicationVersionActions"', apps_qml)
        self.assertIn('objectName: "applicationVersionTabs"', apps_qml)
        self.assertIn(
            'model: ["Resumo", "Processamento", "Comparação", "Origens", "Código"]',
            apps_qml,
        )
        self.assertIn('chat.loadApplicationSources("", 0, "")', apps_qml)
        self.assertIn('objectName: "processingAdvancedToggle"', apps_qml)
        self.assertIn('objectName: "processingAdvancedPanel"', apps_qml)
        self.assertIn('visible: root.processingAdvancedExpanded', apps_qml)
        self.assertIn('objectName: "applicationSourceList"', apps_qml)
        self.assertIn('objectName: "applicationSourceBrowserGrid"', apps_qml)
        self.assertIn('columns: width >= 900 ? 2 : 1', apps_qml)
        self.assertIn(
            'studio.copyText(root.applicationSourceDisplayBody())', apps_qml
        )
        self.assertIn('objectName: "applicationSourceCleanModeButton"', apps_qml)
        self.assertIn('objectName: "applicationSourceRawModeButton"', apps_qml)
        self.assertIn('objectName: "applicationSourceViewNote"', apps_qml)
        self.assertIn('objectName: "applicationSourceKindNote"', apps_qml)
        self.assertIn('font.family: Theme.monospaceFontFamily', apps_qml)
        self.assertIn('wrapMode: TextEdit.NoWrap', apps_qml)
        self.assertNotIn('objectName: "applicationSourcePicker"', apps_qml)
        self.assertNotIn('objectName: "appSelectorHeaderBatchDecompile"', selector_qml)
        self.assertNotIn('objectName: "appSelectorBatchDecompile"', selector_qml)


    def test_applications_source_browser_interaction_and_responsive_layout(self) -> None:
        from vrsoft_extractor.mary.code_index import JavaCodeIndex
        from vrsoft_extractor.mary.jvm_batches import (
            DecompilationBatchExecutor,
            DecompilationBatchPlanner,
        )
        from vrsoft_extractor.mary.jvm_toolchain import DecompileResult

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path, root=settings.root, backup_portable_migration=False
            )
            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = self._bridge(root, initial_page="Configurações")
            chat_bridge = ChatBridge(settings, database, preferences)
            studio_bridge = StudioBridge(settings, database, preferences)

            source_body = (
                "package vr.app;\n"
                "public class App {\n"
                "    public int value() { return 2; }\n"
                "}\n"
            )
            source = root / "package-1"
            source.mkdir()
            with zipfile.ZipFile(source / "VRApp.jar", "w") as jar:
                jar.writestr("META-INF/MANIFEST.MF", "Main-Class: App\n")
                jar.writestr(
                    "vrapp.properties",
                    "versao.major=1\nversao.minor=0\nversao.release=0\n"
                    "versao.build=0\nversao.beta=0\n",
                )
                jar.writestr("App.class", "fixture bytecode")
            catalog = ErpReleaseCatalog(settings.root, expected_jar_count=1)
            catalog.import_release("package-1", source)

            class PreviewAdapter:
                name = "vineflower"

                def decompile(self, request):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    (request.output_dir / "App.java").write_text(source_body, encoding="utf-8")
                    return DecompileResult(
                        tool=self.name,
                        status="completed",
                        duration_ms=1,
                        exit_code=0,
                        output_dir=str(request.output_dir),
                    )

            plan = DecompilationBatchPlanner(settings.root, catalog=catalog).plan("package-1")
            DecompilationBatchExecutor(
                settings.root, catalog=catalog, adapters=(PreviewAdapter(),)
            ).run(plan["plan_id"], limit=10)
            JavaCodeIndex(settings.root, catalog=catalog).index_plan(plan["plan_id"])
            chat_bridge.refreshApplicationsCatalog()
            for _attempt in range(600):
                self.application.processEvents()
                if chat_bridge._apps_catalog_thread is None:
                    break
                QTest.qWait(10)
            self.assertIsNone(chat_bridge._apps_catalog_thread)

            engine = create_engine(bridge, chat_bridge, studio_bridge)
            self.application.processEvents()
            window = engine.rootObjects()[0]
            window.setWidth(1280)
            window.setHeight(820)
            window.show()
            try:
                settings_page = window.findChild(QObject, "settingsPage")
                self.assertIsNotNone(settings_page)
                settings_page.setProperty("tabIndex", 3)
                QTest.qWait(150)
                apps_page = window.findChild(QObject, "appsSettingsPage")
                self.assertIsNotNone(apps_page)

                chat_bridge.selectApplication("vrapp")
                self.assertEqual(len(chat_bridge.appVersions), 1)
                chat_bridge.selectAppVersion(chat_bridge.appVersions[0]["version"])
                self.assertEqual(len(chat_bridge.appVariants), 1)
                chat_bridge.selectAppVariant(chat_bridge.appVariants[0]["variant_id"])
                chat_bridge.selectAppOrigin("package-1")
                self.assertEqual(chat_bridge.selectedAppOriginId, "package-1")
                apps_page.setProperty("navigationLevel", 2)
                apps_page.setProperty("versionSubTab", 4)
                self.application.processEvents()
                QTest.qWait(80)

                self.assertTrue(chat_bridge.loadApplicationSources("", 0, ""))
                for _attempt in range(600):
                    self.application.processEvents()
                    if chat_bridge._app_sources_thread is None:
                        break
                    QTest.qWait(10)
                self.assertIsNone(chat_bridge._app_sources_thread)
                sources = chat_bridge.applicationSources["sources"]
                self.assertTrue(sources)

                source_list = window.findChild(QObject, "applicationSourceList")
                self.assertIsNotNone(source_list)
                self.assertEqual(source_list.property("count"), len(sources))
                source_key = sources[0]["source_key"]

                source_scroll = window.findChild(QObject, "appsSettingsScroll").property(
                    "contentItem"
                )
                source_scroll.setProperty(
                    "contentY",
                    max(
                        0,
                        source_scroll.property("contentHeight")
                        - source_scroll.property("height"),
                    ),
                )
                QTest.qWait(60)
                source_grid = window.findChild(QObject, "applicationSourceBrowserGrid")
                list_panel = window.findChild(QObject, "applicationSourceListPanel")
                body_panel = window.findChild(QObject, "applicationSourceBodyPanel")
                self.assertIsNotNone(source_grid)
                self.assertIsNotNone(list_panel)
                self.assertIsNotNone(body_panel)
                self.assertGreaterEqual(source_grid.property("width"), 900)
                self.assertLess(abs(list_panel.property("y") - body_panel.property("y")), 1)

                scene_point = source_list.mapToScene(QPointF(source_list.width() / 2, 19))
                QTest.mouseClick(
                    window,
                    Qt.LeftButton,
                    Qt.NoModifier,
                    QPoint(round(scene_point.x()), round(scene_point.y())),
                )
                for _attempt in range(600):
                    self.application.processEvents()
                    if chat_bridge._app_sources_thread is None:
                        break
                    QTest.qWait(10)
                self.assertIsNone(chat_bridge._app_sources_thread)
                self.assertEqual(chat_bridge.applicationSources["source_key"], source_key)
                self.assertIn("public class App", chat_bridge.applicationSources["body"])

                copy_button = window.findChild(QObject, "copyApplicationSourceButton")
                self.assertIsNotNone(copy_button)
                clean_button = window.findChild(
                    QObject, "applicationSourceCleanModeButton"
                )
                raw_button = window.findChild(QObject, "applicationSourceRawModeButton")
                view_note = window.findChild(QObject, "applicationSourceViewNote")
                kind_note = window.findChild(QObject, "applicationSourceKindNote")
                body_area = window.findChild(QObject, "applicationSourceBody")
                self.assertIsNotNone(clean_button)
                self.assertIsNotNone(raw_button)
                self.assertIsNotNone(view_note)
                self.assertIsNotNone(kind_note)
                self.assertIsNotNone(body_area)

                def click_control(control):
                    point = control.mapToScene(
                        QPointF(control.width() / 2, control.height() / 2)
                    )
                    QTest.mouseClick(
                        window,
                        Qt.LeftButton,
                        Qt.NoModifier,
                        QPoint(round(point.x()), round(point.y())),
                    )
                    self.application.processEvents()

                click_control(copy_button)
                self.assertEqual(
                    QApplication.clipboard().text(),
                    chat_bridge.applicationSources["body"],
                )

                # Drive the toggle from deliberately different isolated bodies.
                chat_bridge._app_sources.update({
                    "body": "RAW\nBODY\n",
                    "clean_body": "CLEAN\nBODY\n",
                    "clean_available": True,
                    "clean_status": "cleaned",
                    "clean_note": (
                        "Visualização limpa gerada sem alterar identificadores, "
                        "literais ou lógica."
                    ),
                    "source_kind": "type",
                    "source_relative_path": "vr/app/App.java",
                    "decompiler_tool": "vineflower",
                })
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                QTest.qWait(60)

                self.assertTrue(
                    apps_page.property("cleanApplicationSourceMode")
                )
                self.assertEqual(body_area.property("text"), "CLEAN\nBODY\n")
                self.assertTrue(view_note.property("visible"))

                click_control(raw_button)
                self.assertEqual(body_area.property("text"), "RAW\nBODY\n")
                click_control(copy_button)
                self.assertEqual(
                    QApplication.clipboard().text(), "RAW\nBODY\n"
                )
                click_control(clean_button)
                self.assertEqual(body_area.property("text"), "CLEAN\nBODY\n")

                chat_bridge._app_sources["clean_available"] = False
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                QTest.qWait(60)
                self.assertFalse(clean_button.property("enabled"))
                self.assertTrue(raw_button.property("enabled"))
                self.assertEqual(body_area.property("text"), "RAW\nBODY\n")

                chat_bridge._app_sources["source_kind"] = "package_info"
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                QTest.qWait(60)
                self.assertTrue(kind_note.property("visible"))

                window.setWidth(390)
                window.setHeight(844)
                QTest.qWait(150)
                self.application.processEvents()
                self.assertLess(abs(list_panel.property("x") - body_panel.property("x")), 1)
                self.assertGreaterEqual(
                    body_panel.property("y"),
                    list_panel.property("y") + list_panel.property("height"),
                )
            finally:
                window.close()
                engine.deleteLater()
                studio_bridge.close()
                self.application.processEvents()


    def test_applications_portable_package_import_and_export_flows(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path, root=settings.root, backup_portable_migration=False
            )
            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = self._bridge(root, initial_page="Configurações")
            chat_bridge = ChatBridge(settings, database, preferences)
            chat_bridge._packages_catalog = [{
                "package_id": "release-a",
                "name": "Pacote A",
                "imported_at": "2026-01-01T00:00:00+00:00",
                "composition": [],
            }]
            chat_bridge.stateChanged.emit()

            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()
            window = engine.rootObjects()[0]
            window.setWidth(1280)
            window.setHeight(820)
            window.show()
            try:
                settings_page = window.findChild(QObject, "settingsPage")
                self.assertIsNotNone(settings_page)
                settings_page.setProperty("tabIndex", 3)
                QTest.qWait(150)
                apps_page = window.findChild(QObject, "appsSettingsPage")
                self.assertIsNotNone(apps_page)
                for _attempt in range(600):
                    self.application.processEvents()
                    if chat_bridge._apps_catalog_thread is None:
                        break
                    QTest.qWait(10)
                self.assertIsNone(chat_bridge._apps_catalog_thread)
                chat_bridge._packages_catalog = [{
                    "package_id": "release-a",
                    "name": "Pacote A",
                    "imported_at": "2026-01-01T00:00:00+00:00",
                    "composition": [],
                }]
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                QTest.qWait(50)

                def descendants(item):
                    for child in item.childItems():
                        yield child
                        yield from descendants(child)

                def find_by_name(item, name):
                    if item.objectName() == name:
                        return item
                    for child in item.childItems():
                        found = find_by_name(child, name)
                        if found is not None:
                            return found
                    return None

                def find_by_text(item, text):
                    return next(
                        (
                            child for child in descendants(item)
                            if child.property("text") == text
                        ),
                        None,
                    )

                def has_ancestor(item, ancestor):
                    current = item.parentItem()
                    while current is not None:
                        if current is ancestor:
                            return True
                        current = current.parentItem()
                    return False

                import_card = window.findChild(QObject, "appsImportCard")
                import_package_button = window.findChild(
                    QObject, "importDecompiledPackageButton"
                )
                self.assertIsNotNone(import_card)
                self.assertIsNotNone(import_package_button)
                self.assertTrue(has_ancestor(import_package_button, import_card))

                packages_toggle = window.findChild(QObject, "togglePackagesButton")
                packages_panel = window.findChild(QObject, "applicationsPackagesPanel")
                packages_toggle.clicked.emit()
                self.application.processEvents()
                QTest.qWait(50)
                export_package_button = find_by_name(
                    window.contentItem(), "exportDecompiledPackageButton"
                )
                self.assertIsNotNone(export_package_button)
                self.assertTrue(has_ancestor(export_package_button, packages_panel))
                self.assertIsNone(find_by_text(import_card, "Exportar pacote descompilado"))

                export_calls = []

                def fake_package_export(workspace, destination, *, package_id, progress=None):
                    export_calls.append((str(destination), package_id))
                    return {
                        "success": True,
                        "destination": str(destination),
                        "file_count": 3,
                        "total_bytes": 3,
                        "artifact_count": 1,
                        "package_id": package_id,
                    }

                output_file = root / "Pacote-decompiled.zip"
                with (
                    patch.object(
                        codeadmin, "export_decompiled_package", side_effect=fake_package_export
                    ),
                    patch.object(
                        codeadmin.QFileDialog,
                        "getSaveFileName",
                        return_value=(str(output_file), ""),
                    ),
                ):
                    self.assertTrue(QMetaObject.invokeMethod(export_package_button, "click"))
                    for _attempt in range(200):
                        self.application.processEvents()
                        if export_calls and not chat_bridge.releaseSnapshotRunning:
                            break
                        QTest.qWait(10)
                self.assertEqual(len(export_calls), 1)
                self.assertEqual(export_calls[0][1], "release-a")
                self.assertTrue(export_calls[0][0].endswith(".zip"))
                self.assertFalse(chat_bridge.releaseSnapshotRunning)

                export_progress_card = find_by_name(
                    window.contentItem(), "decompiledExportProgressCard"
                )
                export_progress_bar = find_by_name(
                    window.contentItem(), "decompiledExportProgressBar"
                )
                self.assertIsNotNone(export_progress_card)
                self.assertIsNotNone(export_progress_bar)
                self.assertFalse(export_progress_card.property("visible"))
                chat_bridge._decompiled_export_running = True
                chat_bridge._decompiled_export_progress = 42.5
                chat_bridge._decompiled_export_processed = 425
                chat_bridge._decompiled_export_total = 1000
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertTrue(export_progress_card.property("visible"))
                self.assertAlmostEqual(
                    float(export_progress_bar.property("value")), 42.5, places=1
                )
                self.assertFalse(bool(export_progress_bar.property("indeterminate")))
                chat_bridge._decompiled_export_running = False
                chat_bridge._decompiled_export_progress = 0.0
                chat_bridge._decompiled_export_processed = 0
                chat_bridge._decompiled_export_total = 0
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertFalse(export_progress_card.property("visible"))

                packages_toggle.clicked.emit()
                self.application.processEvents()

                dialog = window.findChild(QObject, "decompiledImportDialog")
                self.assertIsNotNone(dialog)
                self.assertFalse(dialog.property("visible"))

                portable_result = {
                    "is_valid": True,
                    "portable_package": True,
                    "scope": "package",
                    "source_archive": str(root / "Pacote-decompiled.zip"),
                    "suggested_release_id": "release-a",
                    "suggested_name": "Pacote A",
                    "applications": [{"app_id": "vrmaster"}],
                    "total_java_files": 3,
                }
                with (
                    patch.object(
                        codeadmin,
                        "detect_decompiled_package_archive",
                        return_value=portable_result,
                    ),
                    patch.object(
                        codeadmin.QFileDialog,
                        "getOpenFileName",
                        return_value=(portable_result["source_archive"], ""),
                    ),
                ):
                    self.assertTrue(QMetaObject.invokeMethod(import_package_button, "click"))
                    for _attempt in range(200):
                        self.application.processEvents()
                        if dialog.property("visible"):
                            break
                        QTest.qWait(10)
                self.assertTrue(dialog.property("visible"))
                detection = apps_page.property("decompiledDetectionResult")
                if hasattr(detection, "toVariant"):
                    detection = detection.toVariant()
                self.assertTrue(detection["portable_package"])
                self.assertTrue(
                    has_ancestor(import_package_button, import_card)
                )
                self.assertIsNotNone(
                    find_by_text(dialog.property("contentItem"), "Pacote portátil VRStudio (.zip)")
                )

                import_calls = []

                def fake_package_import(workspace, archive, *, release_id="", package_name="", progress=None):
                    import_calls.append((str(archive), release_id, package_name))
                    return {
                        "success": True,
                        "release_id": release_id,
                        "package_name": package_name,
                        "total_indexed_sources": 3,
                        "imported_applications": 1,
                        "package": {},
                    }

                confirm_button = find_by_text(dialog.property("contentItem"), "Importar e Indexar")
                self.assertIsNotNone(confirm_button)
                with patch.object(
                    codeadmin,
                    "import_decompiled_package_archive",
                    side_effect=fake_package_import,
                ):
                    self.assertTrue(QMetaObject.invokeMethod(confirm_button, "click"))
                    for _attempt in range(200):
                        self.application.processEvents()
                        if import_calls and not chat_bridge.releaseSnapshotRunning:
                            break
                        QTest.qWait(10)
                self.assertFalse(dialog.property("visible"))
                self.assertEqual(
                    import_calls,
                    [(
                        portable_result["source_archive"],
                        "release-a",
                        "Pacote A",
                    )],
                )

                import_progress_card = find_by_name(
                    window.contentItem(), "decompiledImportProgressCard"
                )
                import_progress_bar = find_by_name(
                    window.contentItem(), "decompiledImportProgressBar"
                )
                self.assertIsNotNone(import_progress_card)
                self.assertIsNotNone(import_progress_bar)
                self.assertFalse(import_progress_card.property("visible"))
                chat_bridge._decompiled_import_running = True
                chat_bridge._decompiled_import_progress = 42.5
                chat_bridge._decompiled_import_processed = 425
                chat_bridge._decompiled_import_total = 1000
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertTrue(import_progress_card.property("visible"))
                self.assertAlmostEqual(
                    float(import_progress_bar.property("value")), 42.5, places=1
                )
                self.assertFalse(bool(import_progress_bar.property("indeterminate")))
                chat_bridge._decompiled_import_running = False
                chat_bridge._decompiled_import_progress = 0.0
                chat_bridge._decompiled_import_processed = 0
                chat_bridge._decompiled_import_total = 0
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertFalse(import_progress_card.property("visible"))

            finally:
                window.close()
                engine.deleteLater()
                self.application.processEvents()


    def test_imported_package_ultra_choice_dialog_flow(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = self._settings(root)
            database = MaryDatabase(
                settings.database_path, root=settings.root, backup_portable_migration=False
            )
            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            bridge = self._bridge(root, initial_page="Configurações")
            chat_bridge = ChatBridge(settings, database, preferences)

            engine = create_engine(bridge, chat_bridge)
            self.application.processEvents()
            window = engine.rootObjects()[0]
            window.setWidth(1280)
            window.setHeight(820)
            window.show()

            def named_objects(name):
                return window.findChildren(QObject, name)

            try:
                settings_page = window.findChild(QObject, "settingsPage")
                self.assertIsNotNone(settings_page)
                settings_page.setProperty("tabIndex", 3)
                apps_page = window.findChild(QObject, "appsSettingsPage")
                self.assertIsNotNone(apps_page)
                for _attempt in range(600):
                    self.application.processEvents()
                    if chat_bridge._apps_catalog_thread is None:
                        break
                    QTest.qWait(10)
                self.assertIsNone(chat_bridge._apps_catalog_thread)

                # Sem pendência o diálogo não existe na árvore.
                self.assertIsNone(
                    window.findChild(QObject, "importedPackageUltraChoiceDialog")
                )
                self.assertIsNone(
                    window.findChild(QObject, "useImportedPackageInUltraButton")
                )
                self.assertIsNone(
                    window.findChild(QObject, "chooseImportedPackageAppsButton")
                )

                chat_bridge._apps_catalog_data = {
                    "data": {
                        "applications": {
                            "vrmaster": {
                                "name": "VRMaster",
                                "versions": {
                                    "4.1.0": {
                                        "variants": {
                                            "sha-master": {
                                                "variant_id": "sha-master",
                                                "origin_packages": [
                                                    {
                                                        "package_id": "pkg-ready",
                                                        "index_state": "ready",
                                                    },
                                                    {
                                                        "package_id": "pkg-one",
                                                        "index_state": "ready",
                                                    },
                                                ],
                                            }
                                        }
                                    }
                                },
                            },
                            "vrpdv": {
                                "name": "VRPdv",
                                "versions": {
                                    "3.2.0": {
                                        "variants": {
                                            "sha-pdv": {
                                                "variant_id": "sha-pdv",
                                                "origin_packages": [
                                                    {
                                                        "package_id": "pkg-one",
                                                        "index_state": "ready",
                                                    }
                                                ],
                                            }
                                        }
                                    }
                                },
                            },
                        },
                        "packages": {
                            "pkg-one": {
                                "package_id": "pkg-one",
                                "name": "Pacote Importado",
                                "composition": [
                                    {
                                        "app_id": "vrmaster",
                                        "version": "4.1.0",
                                        "variant_id": "sha-master",
                                    },
                                    {"app_id": "vrpdv", "version": "3.2.0"},
                                ],
                            }
                        },
                    }
                }
                chat_bridge._ultra_application_contexts = [
                    {
                        "app_id": "vrmaster",
                        "version": "4.1.0",
                        "variant_id": "sha-master",
                        "package_id": "pkg-ready",
                    }
                ]
                chat_bridge._CodeAdmin_domain._save_application_contexts()
                chat_bridge.setCodeAnalysisEnabled(True)
                self.application.processEvents()
                self.assertTrue(chat_bridge.ultraApplicationContextsReady)
                self.assertTrue(chat_bridge.codeAnalysisEnabled)
                ready_contexts = [
                    dict(item) for item in chat_bridge._ultra_application_contexts
                ]

                chat_bridge._pending_ultra_package_choice_id = "pkg-one"
                chat_bridge.stateChanged.emit()
                self.application.processEvents()

                dialogs = named_objects("importedPackageUltraChoiceDialog")
                self.assertEqual(len(dialogs), 1)
                self.assertEqual(
                    len(named_objects("useImportedPackageInUltraButton")), 1
                )
                self.assertEqual(
                    len(named_objects("chooseImportedPackageAppsButton")), 1
                )
                dialog = dialogs[0]
                self.assertTrue(dialog.property("visible"))
                self.assertTrue(dialog.property("opened"))
                self.assertEqual(dialog.property("packageId"), "pkg-one")
                self.assertEqual(dialog.property("applicationCount"), 2)

                # stateChanged sem mudar o packageId não duplica o diálogo.
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertEqual(
                    len(named_objects("importedPackageUltraChoiceDialog")), 1
                )

                # Composição estruturalmente inválida: falha isolada, sem tocar
                # no estado do catálogo nem na prontidão do escopo atual.
                use_button = window.findChild(
                    QObject, "useImportedPackageInUltraButton"
                )
                self.assertTrue(QMetaObject.invokeMethod(use_button, "click"))
                self.application.processEvents()
                self.assertEqual(chat_bridge.applicationsCatalogError, "")
                self.assertEqual(chat_bridge._pending_ultra_package_choice_id, "pkg-one")
                self.assertTrue(
                    chat_bridge.pendingImportedPackageForUltra.get("error")
                )
                self.assertEqual(
                    chat_bridge.pendingImportedPackageForUltra.get("packageId"),
                    "pkg-one",
                )
                dialog = window.findChild(QObject, "importedPackageUltraChoiceDialog")
                self.assertIsNotNone(dialog)
                self.assertTrue(dialog.property("visible"))
                self.assertTrue(dialog.property("opened"))
                error_text = window.findChild(
                    QObject, "importedPackageUltraChoiceError"
                )
                self.assertIsNotNone(error_text)
                self.assertTrue(error_text.property("visible"))
                self.assertIn("composição", error_text.property("text"))
                self.assertEqual(chat_bridge._ultra_application_contexts, ready_contexts)
                self.assertTrue(chat_bridge.ultraApplicationContextsReady)
                self.assertTrue(chat_bridge.codeAnalysisEnabled)

                # Escolher por aplicativo descarta a falha e preserva o escopo.
                apps_page.setProperty("navigationLevel", 1)
                apps_page.setProperty("importToolsExpanded", True)
                self.application.processEvents()
                choose_button = window.findChild(
                    QObject, "chooseImportedPackageAppsButton"
                )
                self.assertTrue(QMetaObject.invokeMethod(choose_button, "click"))
                QTest.qWait(1)
                self.assertEqual(chat_bridge.pendingImportedPackageForUltra, {})
                self.assertEqual(chat_bridge._pending_ultra_package_choice_error, "")
                self.assertEqual(apps_page.property("navigationLevel"), 0)
                self.assertFalse(bool(apps_page.property("importToolsExpanded")))
                self.assertEqual(chat_bridge._ultra_application_contexts, ready_contexts)
                self.assertTrue(chat_bridge.ultraApplicationContextsReady)
                self.assertTrue(chat_bridge.codeAnalysisEnabled)
                self.assertEqual(
                    named_objects("importedPackageUltraChoiceDialog"), []
                )
                self.assertEqual(
                    named_objects("importedPackageUltraChoiceError"), []
                )

                # Composição válida: resolve a pendência e destrói o diálogo.
                chat_bridge._apps_catalog_data["data"]["packages"]["pkg-one"][
                    "composition"
                ] = [
                    {
                        "app_id": "vrmaster",
                        "version": "4.1.0",
                        "variant_id": "sha-master",
                    },
                    {"app_id": "vrpdv", "version": "3.2.0", "variant_id": "sha-pdv"},
                ]
                chat_bridge._pending_ultra_package_choice_id = "pkg-one"
                chat_bridge.stateChanged.emit()
                self.application.processEvents()
                self.assertEqual(
                    len(named_objects("importedPackageUltraChoiceDialog")), 1
                )
                use_button = window.findChild(
                    QObject, "useImportedPackageInUltraButton"
                )
                self.assertTrue(QMetaObject.invokeMethod(use_button, "click"))
                QTest.qWait(1)
                self.assertEqual(chat_bridge.pendingImportedPackageForUltra, {})
                contexts = chat_bridge._ultra_application_contexts
                self.assertEqual(len(contexts), 2)
                self.assertTrue(
                    all(item["package_id"] == "pkg-one" for item in contexts)
                )
                self.assertEqual(
                    {item["app_id"] for item in contexts}, {"vrmaster", "vrpdv"}
                )
                self.assertEqual(
                    named_objects("importedPackageUltraChoiceDialog"), []
                )
                self.assertEqual(
                    named_objects("useImportedPackageInUltraButton"), []
                )
                self.assertEqual(
                    named_objects("chooseImportedPackageAppsButton"), []
                )

                # Pacote já importado: o cartão reabre a pergunta do Ultra.
                chat_bridge._packages_catalog = [
                    {
                        "package_id": "pkg-one",
                        "name": "Pacote Importado",
                        "imported_at": "2026-01-01T00:00:00+00:00",
                        "composition": [
                            {
                                "app_id": "vrmaster",
                                "version": "4.1.0",
                                "variant_id": "sha-master",
                            },
                            {
                                "app_id": "vrpdv",
                                "version": "3.2.0",
                                "variant_id": "sha-pdv",
                            },
                        ],
                    }
                ]
                chat_bridge.stateChanged.emit()
                apps_page.setProperty("navigationLevel", 0)
                apps_page.setProperty("packagesExpanded", True)
                self.application.processEvents()
                QTest.qWait(50)
                def find_by_name(item, name):
                    if item.objectName() == name:
                        return item
                    for child in item.childItems():
                        found = find_by_name(child, name)
                        if found is not None:
                            return found
                    return None

                use_package_button = find_by_name(
                    window.contentItem(), "usePackageInUltraButton"
                )
                self.assertIsNotNone(use_package_button)
                self.assertTrue(
                    QMetaObject.invokeMethod(use_package_button, "click")
                )
                self.application.processEvents()
                QTest.qWait(1)
                dialogs = named_objects("importedPackageUltraChoiceDialog")
                self.assertEqual(len(dialogs), 1)
                self.assertEqual(dialogs[0].property("packageId"), "pkg-one")
                self.assertTrue(dialogs[0].property("visible"))
                choose_button = window.findChild(
                    QObject, "chooseImportedPackageAppsButton"
                )
                self.assertTrue(QMetaObject.invokeMethod(choose_button, "click"))
                QTest.qWait(1)
                self.assertEqual(chat_bridge.pendingImportedPackageForUltra, {})
                self.assertEqual(
                    named_objects("importedPackageUltraChoiceDialog"), []
                )
            finally:
                window.close()
                engine.deleteLater()
                self.application.processEvents()

    def test_software_rendering_flags_and_safe_mode_args(self):
        from vrsoft_extractor.mary.frontend.app import build_parser

        parser = build_parser()
        args1, _ = parser.parse_known_args(["--software-rendering"])
        self.assertTrue(args1.software_rendering)

        args2, _ = parser.parse_known_args(["--gpu-safe-mode"])
        self.assertTrue(args2.software_rendering)

        args3, _ = parser.parse_known_args([])
        self.assertFalse(args3.software_rendering)
        self.assertFalse(args3.hardware_acceleration)

        args4, _ = parser.parse_known_args(["--hardware-acceleration"])
        self.assertTrue(args4.hardware_acceleration)

        args5, _ = parser.parse_known_args(["--enable-gpu"])
        self.assertTrue(args5.hardware_acceleration)

    def test_install_crash_handlers_captures_unhandled_exception(self):
        import sys
        from vrsoft_extractor.mary.frontend.app import install_crash_handlers

        original_hook = sys.excepthook
        with TemporaryDirectory() as temporary:
            log_dir = Path(temporary) / "logs"
            install_crash_handlers(log_dir)
            try:
                try:
                    raise RuntimeError("Teste de protecao contra crash")
                except RuntimeError:
                    exc_type, exc_val, exc_tb = sys.exc_info()
                    sys.excepthook(exc_type, exc_val, exc_tb)

                crash_log = log_dir / "crash.log"
                self.assertTrue(crash_log.is_file())
                content = crash_log.read_text(encoding="utf-8")
                self.assertIn("Teste de protecao contra crash", content)
                self.assertIn("RuntimeError", content)
            finally:
                sys.excepthook = original_hook

    def test_chat_stop_button_icon_has_high_contrast(self):
        assets_dir = MAIN_QML.parent.parent.parent / "assets"
        stop_svg = (assets_dir / "chat-stop.svg").read_text(encoding="utf-8")
        self.assertIn('fill="#FFFFFF"', stop_svg)
        self.assertNotIn('fill="#A1261D"', stop_svg)


    def test_vr_app_icon_resolves_bundled_asset_path_without_external_failure(self):
        from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

        engine = QQmlApplicationEngine()
        component_path = MAIN_QML.parent / "components" / "VrAppIcon.qml"
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(component_path)))
        item = component.create()
        self.assertIsNotNone(item, f"Failed to create VrAppIcon: {component.errors()}")
        try:
            item.setProperty("appName", "VRAdm")
            self.application.processEvents()

            canonical = item.property("canonical")
            asset_path = item.property("assetPath")
            active_source = item.property("activeSource")
            official_path = item.property("officialPath")

            self.assertEqual(canonical, "VRAdm")
            self.assertTrue(asset_path.endswith("assets/app_icons/VRAdm.ico"))
            self.assertFalse(asset_path.startswith("file:///D:/Codex/4.5.95_com_PDV"))
            self.assertEqual(active_source, asset_path)
            self.assertEqual(official_path, asset_path)
            self.assertTrue(item.property("hasIcon"))
            self.assertFalse(item.property("imageFailed"))
        finally:
            item.deleteLater()


    def test_qml_contains_no_explanatory_tooltips(self) -> None:
        remaining = [
            str(path)
            for path in MAIN_QML.parent.rglob("*.qml")
            if "ToolTip." in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(
            remaining,
            [],
            f"Expected no QML files with ToolTip., but found: {remaining}",
        )


if __name__ == "__main__":
    unittest.main()

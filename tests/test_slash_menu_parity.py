import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge


class SlashMenuParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_slash_menu_suggestions_and_parity_across_themes(self):
        themes = ["slate_zinc", "light", "dark_orange", "nightfall", "github_dark"]

        for theme in themes:
            with TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
                settings.root.mkdir(parents=True, exist_ok=True)
                prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
                db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
                db.create_conversation("Slash Parity Test", "codex", "gpt-5.6", settings.root)

                frontend = FrontendBridge(settings, prefs, theme_override=theme, initial_page="Chat VR")
                chat = ChatBridge(settings, db, prefs)
                studio = StudioBridge(settings, db, prefs)

                mock_skills = [
                    {
                        "id": "antigravity:customize-opencode",
                        "name": "Customize Opencode",
                        "displayName": "Customize Opencode",
                        "description": "Use ONLY when the user is editing or creating opencode components",
                        "shortDescription": "Use ONLY when the user is editing or creating opencode components",
                        "scope": "provider",
                        "source": "provider_native",
                        "provider": "antigravity",
                    }
                ]

                with patch.object(chat._orchestrator, "search_skills", return_value=mock_skills), \
                     patch.object(chat, "refreshModels"), \
                     patch.object(chat, "refreshUsageLimits", lambda *a, **k: None):
                    engine = create_engine(frontend, chat, studio)
                    self.assertTrue(engine.rootObjects())
                    window = engine.rootObjects()[0]
                    window.setWidth(1120)
                    window.setHeight(720)
                    window.show()
                    self.application.processEvents()

                    # Find ChatPreview root item
                    def find_by_prop(item, prop, val):
                        res = []
                        if item.property(prop) == val:
                            res.append(item)
                        for c in item.childItems():
                            res.extend(find_by_prop(c, prop, val))
                        return res

                    content = window.contentItem()
                    # Trigger slash menu
                    inputs = find_by_prop(content, "objectName", "chatComposerInput")
                    if not inputs:
                        def find_type(item, name):
                            res = []
                            if name in item.metaObject().className():
                                res.append(item)
                            for c in item.childItems():
                                res.extend(find_type(c, name))
                            return res
                        inputs = find_type(content, "TextArea")

                    self.assertTrue(inputs, "Chat composer input not found")
                    inp = inputs[0]
                    inp.setProperty("text", "/")
                    QTest.qWait(250)

                    # Verify that suggestions were populated
                    chat_preview = inp
                    while chat_preview and "composerSuggestions" not in [
                        chat_preview.metaObject().property(i).name()
                        for i in range(chat_preview.metaObject().propertyCount())
                    ]:
                        chat_preview = chat_preview.parentItem()

                    self.assertIsNotNone(chat_preview, "Could not find ChatPreview root with composerSuggestions")
                    suggestions_val = chat_preview.property("composerSuggestions")
                    suggestions = suggestions_val.toVariant() if hasattr(suggestions_val, "toVariant") else suggestions_val
                    labels = [s.get("label") if isinstance(s, dict) else s["label"] for s in suggestions]

                    # Assert standard T3 commands exist
                    self.assertIn("/model", labels)
                    self.assertIn("/init", labels)
                    self.assertIn("/review", labels)
                    self.assertIn("/usage-limits", labels)

                    # Assert skill prefix and badge parity
                    skill_item = next((s for s in suggestions if s.get("label") == "/skill:Customize Opencode"), None)
                    self.assertIsNotNone(skill_item, "Skill with /skill: prefix not found in suggestions")
                    self.assertEqual(skill_item.get("prefix"), "/skill:")
                    self.assertEqual(skill_item.get("mainLabel"), "Customize Opencode")
                    self.assertEqual(skill_item.get("badge"), "Provider")

                    studio.close()
                    chat.close()
                    window.close()

"""Exercise the model picker with mixed generations and original catalog indices."""
import pytest

from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt

from test_chat_presentation import (
    QApplication, QSettings, QTest, QObject, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine, find_items,
)

pytestmark = pytest.mark.qml


def test_frontier_and_legacy_navigation_search_favorites_and_selection(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "project", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    frontend = FrontendBridge(settings, prefs, initial_page="Chat VR", theme_override="dark_orange")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    catalog = [
        ("codex", "gpt-5.5", "GPT-5.5"),
        ("codex", "gpt-6-astra", "GPT-6-Astra"),
        ("codex", "gpt-5.6-sol", "GPT-5.6-Sol"),
        ("codex", "gpt-5.6-terra", "GPT-5.6-Terra"),
        ("codex", "gpt-5.6-luna", "GPT-5.6-Luna"),
        ("codex", "gpt-5.4-mini", "GPT-5.4-Mini"),
        ("antigravity", "gemini-3.7-flash-high", "Gemini 3.7 Flash (High)"),
        ("antigravity", "gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
        ("antigravity", "opaque-medium", "Gemini 3.8 Flash (Medium)"),
        ("antigravity", "gemini-3.8-flash-low", "Gemini 3.8 Flash (Low)"),
        ("codex", "hidden", "Hidden"),
    ]
    chat._model_items = [
        dict(provider=provider, value=value, displayName=name, label=name,
             key=f"{provider}:{value}", inactive=value == "hidden")
        for provider, value, name in catalog
    ]
    chat._favorite_model_keys = {"codex:gpt-5.5", "codex:gpt-6-astra"}

    def rows(picker):
        return picker.property("visibleItems").toVariant()

    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(900)
            QTest.qWait(150)
            picker = window.findChild(QObject, "chatModelPicker")
            picker.click()
            QTest.qWait(80)
            assert [x["value"] for x in rows(picker)] == ["gpt-6-astra"]
            legacy = window.findChild(QObject, "modelPickerLegacy")
            assert legacy.property("visible")
            legacy.click()
            assert [x["value"] for x in rows(picker)] == ["gpt-5.5"]
            window.findChild(QObject, "modelPickerBack").click()
            picker.setProperty("providerFilter", "codex")
            assert len(rows(picker)) == 4
            assert len(picker.property("legacyItems").toVariant()) == 2
            picker.setProperty("providerFilter", "antigravity")
            assert len(rows(picker)) == 3
            assert len(picker.property("legacyItems").toVariant()) == 1
            search = window.findChild(QObject, "modelPickerSearch")
            search.setProperty("text", "3.7")
            assert rows(picker) == []
            assert legacy.property("visible")
            legacy.click()
            assert [x["sourceIndex"] for x in rows(picker)] == [6]
            search.setProperty("text", "missing")
            assert rows(picker) == []
            search.setProperty("text", "")
            window.findChild(QObject, "modelPickerBack").click()
            QTest.qWait(100)
            # A filtered row must select the original catalog entry, not index 0.
            model_list = window.findChild(QObject, "modelPickerList")
            delegates = find_items(model_list, "modelPickerRow")
            selected_row = next(x for x in delegates if x.property("sourceIndex") == 7)
            point = selected_row.mapToScene(QPoint(80, 25)).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            assert chat.modelItems[chat.modelIndex]["value"] == "gemini-3.8-flash-high"
            picker.click()
            QTest.qWait(80)
            assert not picker.property("showingLegacy")
            assert picker.property("providerFilter") == "favorites"
            assert search.property("text") == ""
            assert not engine._qml_warnings, [w.toString() for w in engine._qml_warnings]
    finally:
        if window:
            window.close()
            engine.deleteLater()
        studio.close()
        chat.close()
        app.processEvents()

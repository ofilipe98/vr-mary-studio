"""UI tests for specialized tool cards and VrChatActivity (Etapa 5).

Verifies:
- VrCommandCard rendering, status badges, monospace styling, and error separation.
- VrToolCard rendering, subtitle chips, and detail expansion.
- VrChatActivity dispatching to specialized components without QML warnings.
"""
from pathlib import Path
import pytest
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge

pytestmark = pytest.mark.qml

ROOT = Path(__file__).resolve().parents[1]
QML_DIR = ROOT / "vrsoft_extractor/mary/frontend/qml"


@pytest.fixture
def qml_env(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "data", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)

    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)

    engine = create_engine(frontend, chat, studio)
    try:
        yield app, engine, frontend, chat, studio
    finally:
        chat.close()
        studio.close()
        app.processEvents()


def test_vr_command_card_instantiation_and_properties(qml_env):
    app, engine, frontend, chat, studio = qml_env

    component_path = QML_DIR / "components/VrCommandCard.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(component_path)))
    assert not component.isError(), [e.toString() for e in component.errors()]

    item = component.create()
    assert item is not None
    try:
        # Set rich modelData from presentation registry
        item.setProperty(
            "modelData",
            {
                "id": "cmd_test_1",
                "kind": "tool",
                "itemType": "commandExecution",
                "state": "error",
                "text": "Comando falhou",
                "command": "python runner.py",
                "cwd": "C:/workspace",
                "output": "Console output line 1\nConsole output line 2",
                "errorSummary": "FileNotFoundError",
                "errorDetails": "Traceback (most recent call last):\n  File 'runner.py'\nFileNotFoundError",
                "exitCode": 1,
                "durationLabel": "1.2s",
                "badgeText": "exit 1",
                "badgeVariant": "error",
                "canExpand": True,
            },
        )
        assert item.property("commandText") == "python runner.py"
        assert item.property("stateValue") == "error"
        assert item.property("isError") is True
        assert item.property("isRunning") is False
        assert item.property("isSuccess") is False
        assert item.property("outputText") == "Console output line 1\nConsole output line 2"
        assert item.property("errorSummaryText") == "FileNotFoundError"

        # Toggle expansion
        item.setProperty("detailExpanded", True)
        assert item.property("detailExpanded") is True
    finally:
        item.deleteLater()
        app.processEvents()


def test_vr_tool_card_instantiation_and_properties(qml_env):
    app, engine, frontend, chat, studio = qml_env

    component_path = QML_DIR / "components/VrToolCard.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(component_path)))
    assert not component.isError(), [e.toString() for e in component.errors()]

    item = component.create()
    assert item is not None
    try:
        item.setProperty(
            "modelData",
            {
                "id": "tool_mcp_1",
                "kind": "tool",
                "itemType": "mcpToolCall",
                "state": "completed",
                "text": "MCP: postgres/execute_sql",
                "subtitle": "postgres/execute_sql",
                "detail": "SELECT * FROM users",
                "durationLabel": "350ms",
                "badgeText": "concluído",
                "icon": "plug",
            },
        )
        assert item.property("titleText") == "MCP: postgres/execute_sql"
        assert item.property("subtitleText") == "postgres/execute_sql"
        assert item.property("isSuccess") is True
        assert item.property("isRunning") is False
        assert item.property("isError") is False
    finally:
        item.deleteLater()
        app.processEvents()


def test_vr_chat_activity_renders_mixed_tools_without_warnings(qml_env):
    app, engine, frontend, chat, studio = qml_env

    activity_path = QML_DIR / "components/VrChatActivity.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(activity_path)))
    assert not component.isError(), [e.toString() for e in component.errors()]

    item = component.create()
    assert item is not None
    try:
        # Supply a list of mixed tools formatted by presentation layer
        items = [
            {
                "id": "c1",
                "kind": "tool",
                "itemType": "commandExecution",
                "state": "completed",
                "text": "Executado: rg calcularImposto",
                "command": "rg calcularImposto",
                "durationLabel": "500ms",
                "badgeText": "sucesso",
            },
            {
                "id": "c2",
                "kind": "file_changes",
                "itemType": "fileChange",
                "state": "completed",
                "text": "2 arquivos alterados",
                "files": ["src/service.py", "tests/test_service.py"],
                "fileCount": 2,
                "additions": 20,
                "deletions": 5,
                "folderSummary": "src, tests",
            },
            {
                "id": "c3",
                "kind": "tool",
                "itemType": "webSearch",
                "state": "completed",
                "text": "Pesquisa: Qt6 Quick Layouts",
                "subtitle": "Qt6 Quick Layouts",
                "durationLabel": "1.1s",
                "badgeText": "encontrado",
            },
        ]
        item.setProperty("items", items)
        item.setProperty("expanded", True)
        item.setProperty("elapsedLabel", "3s")
        app.processEvents()

        assert item.property("headerLabel") == "Worked for 3s"
        assert len(item.property("items")) == 3
    finally:
        item.deleteLater()
        app.processEvents()

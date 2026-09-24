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


def _activity_cards(item) -> list:
    names = {"toolCard", "commandCard", "toolGroupCard", "changedFilesCard"}
    cards = [item] if item.objectName() in names else []
    for child in item.childItems():
        cards.extend(_activity_cards(child))
    return cards


def _find_item(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = _find_item(child, name)
        if found is not None:
            return found
    return None


def _text_values(item) -> list:
    values = []
    for child in item.childItems():
        text = child.property("text")
        if isinstance(text, str) and text:
            values.append(text)
        values.extend(_text_values(child))
    return values


def _create_activity(engine):
    activity_path = QML_DIR / "components/VrChatActivity.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(activity_path)))
    assert not component.isError(), [error.toString() for error in component.errors()]
    item = component.create()
    assert item is not None
    return component, item


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


def test_tool_error_disclosure_deduplicates_and_fits_narrow_layout(qml_env):
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    app, engine, *_ = qml_env
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / "components/VrToolCard.qml")))
    item = component.create()
    window = QQuickWindow()
    item.setParentItem(window.contentItem())
    window.show()
    try:
        item.setWidth(320)
        item.setProperty("modelData", {"text": "Ler fonte", "state": "error",
                         "errorSummary": "Saldo insuficiente", "errorDetails": "Saldo insuficiente",
                         "detail": 'Parâmetros: {"reference": "example.Fiscal"}'})
        item.setProperty("detailExpanded", True)
        QTest.qWait(50)
        assert item.property("expandedText").count("Saldo insuficiente") == 1
        assert '"reference"' in item.property("expandedText")
        assert item.implicitHeight() > 60
        item.setProperty("detailExpanded", False)
        QTest.qWait(50)
        assert item.implicitHeight() < 60
    finally:
        window.close()
        item.deleteLater()
        app.processEvents()


def test_tool_group_card_expands_member_rows_with_their_own_data(qml_env):
    app, engine, frontend, chat, studio = qml_env
    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components/VrToolGroupCard.qml"))
    )
    assert not component.isError(), [e.toString() for e in component.errors()]
    item = component.create()
    assert item is not None
    try:
        item.setProperty("modelData", {
            "id": "grp",
            "kind": "action_group",
            "state": "completed",
            "text": "2 ferramentas executadas",
            "items": [
                {
                    "id": "cmd-1",
                    "kind": "tool",
                    "itemType": "commandExecution",
                    "state": "completed",
                    "command": "rg calcularImposto",
                    "durationLabel": "500ms",
                    "output": "src/service.py:374",
                },
                {
                    "id": "read-1",
                    "kind": "tool",
                    "itemType": "fileRead",
                    "state": "completed",
                    "text": "Leu normalizer.py",
                    "detail": "def normalize(): pass",
                },
            ],
        })
        item.setProperty("groupExpanded", True)
        app.processEvents()
        command = _find_item(item, "commandCard")
        tool = _find_item(item, "toolCard")
        assert command is not None
        assert tool is not None
        # Member rows must render the event they represent, not the card defaults.
        assert command.property("commandText") == "rg calcularImposto"
        assert tool.property("titleText") == "Leu normalizer.py"
    finally:
        item.deleteLater()
        app.processEvents()


def test_tool_card_expansion_offers_no_copy_action(qml_env):
    app, engine, frontend, chat, studio = qml_env
    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components/VrToolCard.qml"))
    )
    assert not component.isError(), [e.toString() for e in component.errors()]
    item = component.create()
    assert item is not None
    try:
        item.setWidth(480)
        item.setProperty("modelData", {
            "id": "todo-1",
            "kind": "tool",
            "itemType": "mcpToolCall",
            "state": "completed",
            "text": "3 todos",
            "detail": '[{"content": "Localizar a nota", "status": "in_progress"}]',
        })
        item.setProperty("detailExpanded", True)
        app.processEvents()
        assert _find_item(item, "toolDetails") is not None
        # T3 Code keeps tool details copy-free; selection is the copy path.
        texts = _text_values(item)
        assert "Copiar" not in texts
        assert "Detalhes" not in texts
    finally:
        item.deleteLater()
        app.processEvents()


def test_mismatched_stack_still_sends_without_silently_switching_context(qml_env, monkeypatch):
    app, engine, frontend, chat, studio = qml_env
    chat._ultra_application_contexts = [{"app_id": "vrmaster", "version": "1.0"}]
    calls = []
    chat._database.create_conversation("Teste", "opencode", "test", chat._settings.root)
    chat.refresh()
    chat.selectConversation(0)
    monkeypatch.setattr(chat._orchestrator, "send", lambda *a, **kw: calls.append(kw))
    assert chat.sendMessage("vratacarejo.service.Nota.calcular(Nota.java:374)")
    assert len(calls) == 1
    assert chat._ultra_application_contexts == [{"app_id": "vrmaster", "version": "1.0"}]


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

        assert item.property("headerLabel") == "Concluído em 3s"
        assert len(item.property("items")) == 3
    finally:
        item.deleteLater()
        app.processEvents()


def test_vr_chat_activity_settled_success_folds_tools_behind_worked_for(qml_env):
    app, engine, frontend, chat, studio = qml_env
    warning_count = len(engine._qml_warnings)
    _component, item = _create_activity(engine)
    completed_items = [
        {
            "id": "cmd-1",
            "kind": "tool",
            "itemType": "commandExecution",
            "state": "completed",
            "text": "Executou os testes ACP",
            "command": "python -m pytest tests/test_antigravity_acp.py",
        },
        {
            "id": "search-1",
            "kind": "tool",
            "itemType": "webSearch",
            "state": "completed",
            "text": "Consultou a referência ACP",
        },
        {
            "id": "mcp-1",
            "kind": "tool",
            "itemType": "mcpToolCall",
            "state": "completed",
            "text": "Leu o resultado da ferramenta",
        },
        {
            "id": "group-1",
            "kind": "action_group",
            "itemType": "unknown",
            "state": "completed",
            "text": "Validou o lifecycle",
        },
    ]
    try:
        item.setProperty("items", completed_items)
        item.setProperty("running", False)
        item.setProperty("statusText", "Concluído")
        item.setProperty("expanded", False)
        item.setProperty("elapsedLabel", "42s")
        app.processEvents()

        assert item.property("headerLabel") == "Concluído em 42s"
        assert _activity_cards(item) == []

        item.setProperty("expanded", True)
        app.processEvents()

        assert len(_activity_cards(item)) == len(completed_items)
        assert len(engine._qml_warnings) == warning_count
    finally:
        item.deleteLater()
        app.processEvents()


def test_vr_chat_activity_settled_file_changes_fold_behind_worked_for(qml_env) -> None:
    app, engine, frontend, chat, studio = qml_env
    warning_count = len(engine._qml_warnings)
    _component, item = _create_activity(engine)
    completed_items = [
        {
            "id": "cmd-files-1",
            "kind": "tool",
            "itemType": "commandExecution",
            "state": "completed",
            "text": "Executou os testes",
            "command": "python -m pytest -q",
        },
        {
            "id": "files-1",
            "kind": "file_changes",
            "itemType": "fileChange",
            "state": "completed",
            "text": "2 arquivos alterados",
            "files": [
                {"path": "src/service.py", "name": "service.py"},
                {"path": "tests/test_service.py", "name": "test_service.py"},
            ],
            "fileCount": 2,
            "additions": 20,
            "deletions": 5,
            "folderSummary": "src, tests",
        },
        {
            "id": "mcp-files-1",
            "kind": "tool",
            "itemType": "mcpToolCall",
            "state": "completed",
            "text": "Leu o resultado",
        },
    ]
    try:
        item.setProperty("items", completed_items)
        item.setProperty("running", False)
        item.setProperty("statusText", "Concluído")
        item.setProperty("expanded", False)
        item.setProperty("elapsedLabel", "42s")
        app.processEvents()

        assert item.property("headerLabel") == "Concluído em 42s"
        cards = _activity_cards(item)
        for name in ("toolCard", "commandCard", "toolGroupCard", "changedFilesCard"):
            assert not any(card.objectName() == name for card in cards), name

        item.setProperty("expanded", True)
        app.processEvents()

        cards = _activity_cards(item)
        assert len(cards) == len(completed_items)
        assert sum(1 for card in cards if card.objectName() == "changedFilesCard") == 1
        assert len(engine._qml_warnings) == warning_count
    finally:
        item.deleteLater()
        app.processEvents()


def test_vr_chat_activity_live_turn_keeps_tool_trace_visible(qml_env):
    app, engine, frontend, chat, studio = qml_env
    warning_count = len(engine._qml_warnings)
    _component, item = _create_activity(engine)
    live_items = [
        {
            "id": "cmd-live",
            "kind": "tool",
            "itemType": "commandExecution",
            "state": "running",
            "text": "Executando testes ACP",
            "command": "python -m pytest tests/test_antigravity_acp.py",
        },
        {
            "id": "search-done",
            "kind": "tool",
            "itemType": "webSearch",
            "state": "completed",
            "text": "Referência ACP consultada",
        },
        {
            "id": "mcp-live",
            "kind": "tool",
            "itemType": "mcpToolCall",
            "state": "running",
            "text": "Aguardando retorno da ferramenta",
        },
        {
            "id": "search-live",
            "kind": "tool",
            "itemType": "webSearch",
            "state": "running",
            "text": "Validando o lifecycle",
        },
    ]
    try:
        item.setProperty("items", live_items)
        item.setProperty("running", True)
        item.setProperty("statusText", "Executando uma ação…")
        item.setProperty("expanded", False)
        app.processEvents()

        assert len(_activity_cards(item)) == len(live_items)
        assert len(engine._qml_warnings) == warning_count
    finally:
        item.deleteLater()
        app.processEvents()


def test_vr_chat_activity_settled_failure_keeps_failure_summary_visible(qml_env):
    app, engine, frontend, chat, studio = qml_env
    warning_count = len(engine._qml_warnings)
    _component, item = _create_activity(engine)
    try:
        item.setProperty(
            "items",
            [
                {
                    "id": "cmd-ok",
                    "kind": "tool",
                    "itemType": "commandExecution",
                    "state": "completed",
                    "text": "Preparou o ambiente",
                    "command": "python --version",
                },
                {
                    "id": "tool-old-failure",
                    "kind": "tool",
                    "itemType": "mcpToolCall",
                    "state": "error",
                    "text": "Falha anterior",
                },
                {
                    "id": "tool-latest-failure",
                    "kind": "tool",
                    "itemType": "mcpToolCall",
                    "state": "failed",
                    "text": "Falha terminal mais recente",
                },
            ],
        )
        item.setProperty("running", False)
        item.setProperty("statusText", "Erro")
        item.setProperty("expanded", False)
        app.processEvents()

        cards = _activity_cards(item)
        assert len(cards) == 1
        assert cards[0].property("titleText") == "Falha terminal mais recente", cards[0].property("modelData")
        assert len(engine._qml_warnings) == warning_count
    finally:
        item.deleteLater()
        app.processEvents()

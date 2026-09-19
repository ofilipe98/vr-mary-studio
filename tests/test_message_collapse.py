"""Mostrar mais / Mostrar menos collapse behavior inside the real chat."""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge

pytestmark = pytest.mark.qml

SHORT_TEXT = "Mensagem curta de teste."
LONG_PARAGRAPHS = "# Resposta longa\n\n" + ("Paragrafo de teste.\n\n" * 40)
LONG_CODE_MARKDOWN = (
    "# Titulo\n\n"
    + ("Introducao.\n\n" * 8)
    + "```python\nprint('ok')\n```\n\n"
    + ("Conclusao.\n\n" * 8)
)
# Mixed-shape response: prose, code, prose, table, prose.
MIXED_MARKDOWN = (
    "# Relatorio\n\n"
    + ("Resumo do ponto.\n\n" * 6)
    + "```sql\nSELECT codigo FROM funcoes;\n```\n\n"
    + ("Detalhe apurado.\n\n" * 6)
    + "| Area | Situacao |\n| --- | --- |\n| PDV | OK |\n\n"
    + ("Encerramento.\n\n" * 6)
)
TARGET_LONG = "# Alvo\n\n" + ("Paragrafo alvo.\n\n" * 60)
FILLER_LONG = "## Contexto\n\n" + ("Paragrafo de contexto.\n\n" * 30)


def find_items(item, name):
    result = [item] if item.objectName() == name else []
    for child in item.childItems():
        result.extend(find_items(child, name))
    return result


def open_chat(tmp_path, messages):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(
        app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy"
    )
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(
        settings.database_path, root=settings.root, backup_portable_migration=False
    )
    cid = db.create_conversation("Collapse", "codex", "test", settings.root)
    for role, content in messages:
        db.add_message(cid, role, content)
    frontend = FrontendBridge(settings, prefs, initial_page="Chat VR")
    frontend.setReduceMotion(True)
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    return app, settings, frontend, chat, studio


def test_short_message_shows_no_toggle(tmp_path):
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("user", SHORT_TEXT)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(400)
            collapsibles = find_items(
                window.contentItem(), "collapsibleMessageContent"
            )
            assert collapsibles, "user message must use the collapsible wrapper"
            assert not bool(collapsibles[0].property("overflows"))
            toggles = find_items(window.contentItem(), "messageExpandButton")
            assert toggles
            assert not bool(toggles[0].property("visible"))
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_long_message_collapses_expands_and_preserves_state(tmp_path):
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("assistant", LONG_PARAGRAPHS)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(450)
            timeline = window.findChild(QObject, "messageList")
            timeline.setProperty("followTail", False)
            timeline.setProperty("contentY", 0)
            QTest.qWait(100)

            collapsibles = [
                item
                for item in find_items(
                    window.contentItem(), "collapsibleMessageContent"
                )
                if bool(item.property("overflows"))
            ]
            assert collapsibles, "long content must report real overflow"
            collapsible = collapsibles[0]
            assert not bool(collapsible.property("expanded"))
            collapsed_height = float(collapsible.property("implicitHeight"))

            toggle = next(
                item
                for item in find_items(window.contentItem(), "messageExpandButton")
                if bool(item.property("visible"))
            )
            assert toggle.property("text") == "Mostrar mais"
            # Semantic action: keyboard-focusable button with visible focus state.
            assert int(toggle.property("focusPolicy")) != 0

            bodies_before = find_items(window.contentItem(), "messageBody")
            assert bodies_before

            toggle.click()
            QTest.qWait(200)
            assert bool(collapsible.property("expanded"))
            assert toggle.property("text") == "Mostrar menos"
            assert float(collapsible.property("implicitHeight")) > collapsed_height
            # Expanding while reading old content must not yank the viewport.
            assert abs(float(timeline.property("contentY"))) < 1
            # Internal renderers are only clipped, never recreated.
            assert find_items(window.contentItem(), "messageBody") == bodies_before

            toggle.click()
            QTest.qWait(200)
            assert not bool(collapsible.property("expanded"))
            assert toggle.property("text") == "Mostrar mais"
            assert (
                abs(float(collapsible.property("implicitHeight")) - collapsed_height)
                < 2
            )
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_overflow_updates_when_content_grows(tmp_path):
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("assistant", SHORT_TEXT)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(400)
            collapsible = find_items(
                window.contentItem(), "collapsibleMessageContent"
            )[0]
            assert not bool(collapsible.property("overflows"))
            chat.messages.update_last(
                content=LONG_PARAGRAPHS, displayContent=LONG_PARAGRAPHS
            )
            QTest.qWait(350)
            assert bool(collapsible.property("overflows"))
            toggles = [
                item
                for item in find_items(window.contentItem(), "messageExpandButton")
                if bool(item.property("visible"))
            ]
            assert toggles
            assert toggles[0].property("text") == "Mostrar mais"
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_code_block_survives_expand_collapse(tmp_path):
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("assistant", LONG_CODE_MARKDOWN)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(450)
            code_before = find_items(window.contentItem(), "codeBlockCard")
            assert code_before, "fixture must render a code block"
            toggle = next(
                item
                for item in find_items(window.contentItem(), "messageExpandButton")
                if bool(item.property("visible"))
            )
            toggle.click()
            QTest.qWait(200)
            assert find_items(window.contentItem(), "codeBlockCard")[0] is code_before[0]
            toggle.click()
            QTest.qWait(200)
            assert find_items(window.contentItem(), "codeBlockCard")[0] is code_before[0]
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_long_user_message_collapses(tmp_path):
    long_user = "Linha do usuario.\n" * 60
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("user", long_user)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(450)
            collapsibles = [
                item
                for item in find_items(
                    window.contentItem(), "collapsibleMessageContent"
                )
                if bool(item.property("overflows"))
            ]
            assert collapsibles
            toggle = next(
                item
                for item in find_items(window.contentItem(), "messageExpandButton")
                if bool(item.property("visible"))
            )
            collapsed_height = float(collapsibles[0].property("implicitHeight"))
            toggle.click()
            QTest.qWait(200)
            assert bool(collapsibles[0].property("expanded"))
            assert float(collapsibles[0].property("implicitHeight")) > collapsed_height
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_block_spacing_matches_pre_collapse_rhythm(tmp_path):
    """Assistant blocks keep spacing 12; plain user text keeps 0."""
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("assistant", MIXED_MARKDOWN)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(500)
            columns = find_items(
                window.contentItem(), "collapsibleContentColumn"
            )
            assert columns, "collapsible content column must exist"
            # The mixed fixture renders prose, code, table blocks.
            assert find_items(window.contentItem(), "codeBlockCard")
            assert find_items(window.contentItem(), "tableBlock")
            assert float(columns[0].property("spacing")) == 12.0
            collapsibles = find_items(
                window.contentItem(), "collapsibleMessageContent"
            )
            assert float(collapsibles[0].property("contentSpacing")) == 12.0
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_user_content_column_has_no_block_spacing(tmp_path):
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("user", "Linha do usuario.\n" * 60)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(450)
            columns = find_items(
                window.contentItem(), "collapsibleContentColumn"
            )
            assert columns
            assert float(columns[0].property("spacing")) == 0.0
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def open_scrolling_chat(tmp_path):
    """Target long message first, then tall trailing fillers."""
    return open_chat(
        tmp_path,
        [
            ("assistant", TARGET_LONG),
            ("assistant", FILLER_LONG),
            ("assistant", FILLER_LONG),
        ],
    )


def target_parts(window):
    """Return (collapsible, toggle) of the first (target) message, in order."""
    collapsibles = [
        item
        for item in find_items(window.contentItem(), "collapsibleMessageContent")
        if bool(item.property("overflows"))
    ]
    toggles = [
        item
        for item in find_items(window.contentItem(), "messageExpandButton")
        if bool(item.property("visible"))
    ]
    assert len(collapsibles) == 3, "fixture needs three overflowing messages"
    assert len(toggles) == 3
    return collapsibles[0], toggles[0]


def test_expand_message_above_viewport_preserves_reading_position(tmp_path):
    _app, _settings, frontend, chat, studio = open_scrolling_chat(tmp_path)
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(500)
            timeline = window.findChild(QObject, "messageList")
            timeline.setProperty("followTail", False)
            collapsible, toggle = target_parts(window)
            collapsed_height = float(collapsible.property("implicitHeight"))
            # Park the viewport mid-conversation, below the collapsed target.
            # The message top (y=0) sits above contentY, so expanding must
            # shift contentY down by the growth to keep the read area stable.
            anchor = collapsed_height + 80.0
            timeline.setProperty("contentY", anchor)
            QTest.qWait(100)
            assert abs(float(timeline.property("contentY")) - anchor) < 1
            toggle.click()
            QTest.qWait(200)
            assert bool(collapsible.property("expanded"))
            growth = float(collapsible.property("implicitHeight")) - collapsed_height
            assert growth > 200
            assert (
                abs(float(timeline.property("contentY")) - (anchor + growth)) < 3.0
            )
            # No preserveReader() snap-back may revert the compensation.
            QTest.qWait(250)
            assert (
                abs(float(timeline.property("contentY")) - (anchor + growth)) < 3.0
            )
            # Siblings stay collapsed.
            others = [
                item
                for item in find_items(
                    window.contentItem(), "collapsibleMessageContent"
                )
                if bool(item.property("overflows")) and item is not collapsible
            ]
            assert all(not bool(item.property("expanded")) for item in others)
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_collapse_message_above_viewport_compensates_height(tmp_path):
    _app, _settings, frontend, chat, studio = open_scrolling_chat(tmp_path)
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(500)
            timeline = window.findChild(QObject, "messageList")
            collapsible, toggle = target_parts(window)
            collapsed_height = float(collapsible.property("implicitHeight"))
            toggle.click()
            QTest.qWait(200)
            assert bool(collapsible.property("expanded"))
            expanded_height = float(collapsible.property("implicitHeight"))
            shrink = expanded_height - collapsed_height
            assert shrink > 200
            timeline.setProperty("followTail", True)
            timeline.positionViewAtEnd()
            QTest.qWait(200)
            timeline.setProperty("followTail", False)
            end_y = float(timeline.property("contentY"))
            # Precondition: the expanded target sits fully above the viewport
            # (tall trailing fillers + spacer fill more than one screen).
            assert end_y > expanded_height + 100.0
            toggle.click()
            QTest.qWait(200)
            assert not bool(collapsible.property("expanded"))
            assert abs(float(timeline.property("contentY")) - (end_y - shrink)) < 3.0
            # No restoreReader() may undo the compensation afterwards.
            QTest.qWait(250)
            assert abs(float(timeline.property("contentY")) - (end_y - shrink)) < 3.0
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_streaming_hides_toggle_and_keeps_manual_state(tmp_path):
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("assistant", TARGET_LONG)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(500)
            collapsible = [
                item
                for item in find_items(
                    window.contentItem(), "collapsibleMessageContent"
                )
                if bool(item.property("overflows"))
            ][0]
            collapsed_height = float(collapsible.property("implicitHeight"))
            chat.messages.update_last(isStreaming=True)
            QTest.qWait(250)
            # Full content visible, manual state untouched, no dead control.
            assert bool(collapsible.property("effectiveExpanded"))
            assert not bool(collapsible.property("expanded"))
            assert not any(
                bool(item.property("visible"))
                for item in find_items(window.contentItem(), "messageExpandButton")
            )
            assert float(collapsible.property("implicitHeight")) > collapsed_height
            chat.messages.update_last(isStreaming=False)
            QTest.qWait(250)
            # A long message never expanded manually returns to collapsed.
            assert not bool(collapsible.property("expanded"))
            assert bool(collapsible.property("overflows"))
            toggles = [
                item
                for item in find_items(window.contentItem(), "messageExpandButton")
                if bool(item.property("visible"))
            ]
            assert toggles
            assert toggles[0].property("text") == "Mostrar mais"
            assert (
                abs(float(collapsible.property("implicitHeight")) - collapsed_height)
                < 3.0
            )
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_toggle_keyboard_activation_and_state(tmp_path):
    _app, _settings, frontend, chat, studio = open_chat(
        tmp_path, [("assistant", TARGET_LONG)]
    )
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(500)
            collapsible = [
                item
                for item in find_items(
                    window.contentItem(), "collapsibleMessageContent"
                )
                if bool(item.property("overflows"))
            ][0]
            toggle = next(
                item
                for item in find_items(window.contentItem(), "messageExpandButton")
                if bool(item.property("visible"))
            )
            assert int(toggle.property("focusPolicy")) == int(Qt.StrongFocus)
            toggle.click()
            QTest.qWait(200)
            assert bool(toggle.property("activeFocus"))
            assert bool(collapsible.property("expanded"))
            assert toggle.property("text") == "Mostrar menos"
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(200)
            assert not bool(collapsible.property("expanded"))
            assert toggle.property("text") == "Mostrar mais"
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(200)
            assert bool(collapsible.property("expanded"))
            assert toggle.property("text") == "Mostrar menos"
            assert not engine._qml_warnings, [
                x.toString() for x in engine._qml_warnings
            ]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()

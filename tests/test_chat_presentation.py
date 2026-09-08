"""Behavior checks for the presentation layer; no live provider calls."""
import pytest

import os
from unittest.mock import patch

os.environ.setdefault("QSG_RHI_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.frontend.text_rendering import presentation_blocks
from vrsoft_extractor.mary.frontend.text_rendering import CodeSyntaxHighlighter

pytestmark = pytest.mark.qml


def test_sources_preserve_prose_code_and_incomplete_links():
    text = "Introdução\n\n**Fontes consultadas**:\n\n- [Manual](https://example.com/manual)\n- [Outro](https://example.com/outro)\n\nConclusão."
    result = presentation_blocks(text)
    assert [x["kind"] for x in result] == ["text", "source", "source", "text"]
    assert result[0]["content"] == "Introdução"
    assert result[-1]["content"] == "Conclusão."
    assert result[1]["origin"] == "example.com"
    incomplete = "Fontes consultadas:\n- [Manual](https://example.com/"
    assert presentation_blocks(incomplete) == [{"kind": "text", "content": incomplete}]
    code = "```text\nFontes consultadas:\n- [Manual](https://example.com)\n```"
    assert [x["kind"] for x in presentation_blocks(code)] == ["code"]
    ordinary = "Leia [Manual](https://example.com)."
    assert presentation_blocks(ordinary) == [{"kind": "text", "content": ordinary}]


def find_items(item, name):
    result = [item] if item.objectName() == name else []
    for child in item.childItems():
        result.extend(find_items(child, name))
    return result


def test_streaming_preserves_blocks_scroll_copy_and_theme(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation("Visual", "codex", "gpt-5.6", settings.root)
    markdown = "# Resultado\n\n" + ("Parágrafo de teste.\n\n" * 20) + "```python\nprint('ok')\n```\n\nResposta"
    db.add_message(cid, "assistant", markdown)
    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setPosition(0, 0)
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(200)
            timeline = window.findChild(QObject, "messageList")
            timeline.setProperty("followTail", False)
            timeline.setProperty("contentY", 0)
            code = find_items(window.contentItem(), "codeBlockCard")[0]
            code_body = find_items(window.contentItem(), "codeBlockBody")[0]
            code_body.selectAll()
            QTest.qWait(100)
            timeline.setProperty("followTail", False)
            timeline.setProperty("contentY", 0)
            for token in (" progressiva", " sem", " recriar", " blocos."):
                markdown += token
                chat.messages.update_last(content=markdown, displayContent=markdown)
                QTest.qWait(90)
                assert abs(timeline.property("contentY")) < 1
            assert abs(timeline.property("contentY")) < 1
            assert find_items(window.contentItem(), "codeBlockCard")[0] is code
            assert code_body.property("selectedText") == "print('ok')"
            code.copyCode()
            assert app.clipboard().text() == "print('ok')"
            assert code.property("copied")
            timeline.setProperty("followTail", True)
            timeline.positionViewAtEnd()
            markdown += "\n\n" + "Nova linha.\n\n" * 8
            chat.messages.update_last(content=markdown, displayContent=markdown)
            QTest.qWait(250)
            assert timeline.property("atYEnd")
            frontend.setTheme("light")
            QTest.qWait(150)
            body = find_items(window.contentItem(), "messageBody")[0]
            quick_doc = body.property("textDocument")
            doc = quick_doc.textDocument()
            assert doc.firstBlock().begin().fragment().charFormat().foreground().color().name() == "#18181b"
            code_doc = code_body.property("textDocument")
            highlighters = code_doc.textDocument().findChildren(CodeSyntaxHighlighter)
            assert len(highlighters) == 1
            assert highlighters[0].keyword_format.foreground().color().name() == "#9b2861"
            markdown += "\n\nFontes consultadas:\n" + "\n".join(
                f"- [Documento {i}](https://example.com/{i})" for i in range(6))
            chat.messages.update_last(content=markdown, displayContent=markdown)
            QTest.qWait(150)
            assert len(find_items(window.contentItem(), "sourceCitation")) == 4
            find_items(window.contentItem(), "sourcesExpandButton")[0].click()
            QTest.qWait(50)
            assert len(find_items(window.contentItem(), "sourceCitation")) == 6
            wrap_button = find_items(window.contentItem(), "codeBlockWrap")[0]
            wrap_button.setProperty("checked", False)
            code.setProperty("code", "value = '" + "long " * 120 + "'")
            QTest.qWait(100)
            viewport = find_items(window.contentItem(), "codeViewport")[0]
            assert viewport.property("contentWidth") > viewport.width()
            wrap_button.setProperty("checked", True)
            QTest.qWait(100)
            assert viewport.property("contentWidth") == viewport.width()
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()

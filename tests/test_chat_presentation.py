"""Behavior checks for the presentation layer; no live provider calls."""
import pytest

import os
from unittest.mock import patch

os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QSettings, Qt
from PySide6.QtGui import QColor, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vrsoft_extractor.mary.brand import brand_palette
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.frontend.text_rendering import presentation_blocks
from vrsoft_extractor.mary.frontend.text_rendering import CodeSyntaxHighlighter
from vrsoft_extractor.mary.frontend.text_rendering import apply_message_document_style

pytestmark = pytest.mark.qml


def test_file_reference_anchors_render_as_chips():
    QApplication.instance() or QApplication([])
    markdown = (
        "Veja [file_links.py · L12](vr-file:mary/frontend/file_links.py#L12) "
        "e [site](https://example.com)."
    )
    document = QTextDocument()
    document.setMarkdown(markdown)
    apply_message_document_style(document, markdown, dark=True, monospace_family="Consolas")
    formats = {}
    iterator = document.firstBlock().begin()
    while not iterator.atEnd():
        fragment = iterator.fragment()
        formats[fragment.text()] = fragment.charFormat()
        iterator += 1
    chip = formats["file_links.py · L12"]
    assert chip.anchorHref() == "vr-file:mary/frontend/file_links.py#L12"
    assert chip.fontFamilies() == ["Consolas"]
    assert chip.background().style() != Qt.BrushStyle.NoBrush
    assert not chip.fontUnderline()
    # t3code parity: the chip follows the theme foreground, not the link accent.
    assert chip.foreground().color().name() == "#d6d6d9"
    assert chip.foreground().color().name() != "#ffad70"
    link = formats["site"]
    assert link.anchorHref() == "https://example.com"
    assert link.background().style() == Qt.BrushStyle.NoBrush
    assert link.foreground().color().name() == "#ffad70"


def test_message_style_follows_active_palette():
    QApplication.instance() or QApplication([])
    palette = dict(brand_palette("light"))
    palette.update({
        "text": "#102a43",
        "headingText": "#0b1f33",
        "link": "#0055ff",
        "inlineCodeSurface": "#eef4ff",
        "chatBorder": "#c7d2fe",
    })
    markdown = "# Título\n\n`código` e [link](https://example.com) e [a.py](vr-file:a.py#L1)."
    document = QTextDocument()
    document.setMarkdown(markdown)
    apply_message_document_style(document, markdown, palette=palette, monospace_family="Consolas")
    formats = {}
    block = document.firstBlock()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            formats.setdefault(fragment.text(), fragment.charFormat())
            iterator += 1
        block = block.next()
    assert formats["Título"].foreground().color().name() == "#0b1f33"
    assert formats["código"].foreground().color().name() == "#102a43"
    assert formats["código"].background().color().name() == "#eef4ff"
    assert formats["link"].foreground().color().name() == "#0055ff"
    chip = formats["a.py"]
    assert chip.foreground().color().name() == "#102a43"
    assert chip.background().color().name() == "#eef4ff"


def test_bridge_styles_messages_with_active_theme_palette(tmp_path):
    QApplication.instance() or QApplication([])

    class QuickDocument(QObject):
        def __init__(self, document):
            super().__init__()
            self._document = document

        def textDocument(self):
            return self._document

    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    frontend = FrontendBridge(settings, prefs, theme_override="nightfall", initial_page="Chat VR")
    palette = frontend.palette
    assert palette["link"] == "#7dcfff"
    document = QTextDocument()
    markdown = "`código` e [link](https://example.com)."
    document.setMarkdown(markdown)
    frontend.styleMessageDocument(QuickDocument(document), markdown)
    formats = {}
    iterator = document.firstBlock().begin()
    while not iterator.atEnd():
        fragment = iterator.fragment()
        formats.setdefault(fragment.text(), fragment.charFormat())
        iterator += 1
    assert formats["código"].foreground().color().name() == QColor(palette["text"]).name()
    assert formats["link"].foreground().color().name() == palette["link"]


def test_open_file_reference_resolves_and_emits(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    try:
        target = settings.root / "mary" / "file_links.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        received = []
        chat.filePreviewRequested.connect(
            lambda path, line, column: received.append((path, line, column))
        )
        chat.openFileReference("vr-file:mary/file_links.py#L12:C3")
        assert received == [(str(target.resolve()), 12, 3)]
        chat.openFileReference("calcularImpostoItem")
        assert len(received) == 1
    finally:
        chat.close()


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
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits", lambda *a, **k: None):
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
            table_markdown = "| Área | Responsabilidade |\n| --- | --- |\n| VR Ultra | **Análise**, fontes e código |"
            markdown += "\n\n" + table_markdown
            chat.messages.update_last(content=markdown, displayContent=markdown)
            window.setWidth(390)
            QTest.qWait(180)
            table = find_items(window.contentItem(), "tableBlock")[0]
            table_body = find_items(window.contentItem(), "tableBody")[0]
            table_body.selectAll()
            assert "Análise" in table_body.property("selectedText")
            table.copyTable("markdown")
            assert app.clipboard().text() == table_markdown
            table.copyTable("csv")
            assert '"Análise, fontes e código"' in app.clipboard().text()
            table.copyTable("tsv")
            assert "VR Ultra\tAnálise, fontes e código" in app.clipboard().text()
            find_items(window.contentItem(), "tableExpandButton")[0].click()
            QTest.qWait(100)
            table_viewport = find_items(window.contentItem(), "tableViewport")[0]
            assert table_viewport.property("contentWidth") > table_viewport.width()
            timeline.setProperty("followTail", False)
            timeline.setProperty("contentY", 0)
            markdown += "\n| Aplicativos | Catálogo e versões |"
            chat.messages.update_last(content=markdown, displayContent=markdown)
            QTest.qWait(180)
            assert find_items(window.contentItem(), "tableBlock")[0] is table
            assert table.property("expanded")
            assert abs(timeline.property("contentY")) < 1
            assert len(find_items(window.contentItem(), "tableRowRule")) == 3
            find_items(window.contentItem(), "tableExpandButton")[0].click()
            frontend.setUiScale("150")
            QTest.qWait(150)
            assert table_viewport.width() <= timeline.width()
            edges = [item.y() for item in find_items(window.contentItem(), "tableRowRule")]
            assert edges == sorted(edges)
            assert edges[-1] <= table_viewport.height()
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_chat_opens_file_reference_in_files_surface(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    target = settings.root / "mary" / "frontend" / "file_links.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("linha um\nlinha dois\nlinha tres", encoding="utf-8")
    cid = db.create_conversation("Arquivos", "codex", "gpt-5.6", settings.root)
    db.add_message(cid, "assistant", "Veja `mary/frontend/file_links.py:2`.")
    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits", lambda *a, **k: None):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(250)
            displays = [
                str(chat.messages.item(index).get("displayContent") or "")
                for index in range(chat.messages.rowCount())
            ]
            assert any(
                "vr-file:mary/frontend/file_links.py#L2" in display
                for display in displays
            ), displays
            page = window.findChild(QObject, "chatPage")
            chat.openFileReference("vr-file:mary/frontend/file_links.py#L2")
            QTest.qWait(250)
            assert page.property("surfaceVisible")
            assert page.property("surfaceIndex") == 3
            assert page.property("surfaceFilePath") == str(target.resolve())
            assert page.property("surfaceFileLine") == 2
            assert page.property("surfaceFilePreview") == "linha um\nlinha dois\nlinha tres"
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_open_decompiled_reference_resolves_and_emits(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    chat.decompiledPreviewRequested.connect(lambda payload: received.append(dict(payload)))
    fake_payload = {
        "state": "ready",
        "title": "NotaSaidaFiscalService",
        "target_symbol": "calcularImpostoItem",
        "clean_target_line": 42,
    }
    try:
        with patch("vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference", return_value=fake_payload):
            chat.openDecompiledReference("vr-code:NotaSaidaFiscalService.calcularImpostoItem")
            for _ in range(150):
                QTest.qWait(20)
                if received:
                    break
            assert len(received) == 1
            assert received[0]["state"] == "ready"
            assert received[0]["title"] == "NotaSaidaFiscalService"
            assert received[0]["clean_target_line"] == 42
            assert chat.decompiledPreviewPayload["title"] == "NotaSaidaFiscalService"
    finally:
        chat.close()


def test_open_decompiled_reference_discards_superseded_request(tmp_path):
    import time
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    chat.decompiledPreviewRequested.connect(lambda payload: received.append(dict(payload)))

    def slow_resolve(ref, **kwargs):
        if "First" in str(ref):
            time.sleep(0.15)
            return {"state": "ready", "title": "First"}
        return {"state": "ready", "title": "Second"}

    try:
        with patch("vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference", side_effect=slow_resolve):
            chat.openDecompiledReference("vr-code:First.m")
            chat.openDecompiledReference("vr-code:Second.m")
            for _ in range(150):
                QTest.qWait(20)
                if len(received) >= 1 and received[-1]["title"] == "Second":
                    break
            assert len(received) == 1
            assert received[0]["title"] == "Second"
    finally:
        chat.close()


def test_open_decompiled_reference_handles_unexpected_error(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    chat.decompiledPreviewRequested.connect(lambda payload: received.append(dict(payload)))

    try:
        with patch("vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference", side_effect=RuntimeError("Index crash")):
            chat.openDecompiledReference("vr-code:Broken.method")
            for _ in range(150):
                QTest.qWait(20)
                if received:
                    break
            assert len(received) == 1
            assert received[0]["state"] == "error"
            assert "Index crash" in received[0]["message"]
    finally:
        chat.close()


def test_chat_opens_decompiled_code_surface(tmp_path):
    QApplication.instance() or QApplication([])
    (tmp_path / "VRProject").mkdir(parents=True, exist_ok=True)
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation("Chat", "codex", "gpt-5.6", settings.root)
    db.add_message(cid, "assistant", "Veja `NotaSaidaFiscalService.calcularImpostoItem`.")
    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    fake_payload = {
        "state": "ready",
        "title": "NotaSaidaFiscalService",
        "package_name": "br.com.vrsoft.fiscal",
        "qualified_name": "br.com.vrsoft.fiscal.NotaSaidaFiscalService",
        "target_symbol": "calcularImpostoItem",
        "clean_status": "cleaned",
        "tool": "CFR",
        "raw_target_line": 15,
        "clean_target_line": 5,
        "truncated": False,
        "body": "package br.com.vrsoft.fiscal;\n\npublic class NotaSaidaFiscalService {\n    // raw body\n}",
        "clean_body": "package br.com.vrsoft.fiscal;\n\npublic class NotaSaidaFiscalService {\n    // clean body line 4\n    public void calcularImpostoItem() {\n        int x = 1;\n    }\n}",
    }
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits", lambda *a, **k: None), patch("vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference", return_value=fake_payload):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(250)
            page = window.findChild(QObject, "chatPage")
            chat.openDecompiledReference("vr-code:NotaSaidaFiscalService.calcularImpostoItem")
            for _ in range(150):
                QTest.qWait(20)
                if page.property("surfaceVisible") and page.property("surfaceIndex") == 6:
                    break
            assert page.property("surfaceVisible")
            assert page.property("surfaceIndex") == 6
            surface_view = window.findChild(QObject, "decompiledSurfaceView")
            assert surface_view is not None
            assert surface_view.property("hasCode")
            assert "calcularImpostoItem" in surface_view.property("displayedCode")
            code_body = window.findChild(QObject, "decompiledCodeBody")
            assert code_body is not None
            assert "calcularImpostoItem" in code_body.property("text")
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_chat_decompiled_surface_not_found(tmp_path):
    QApplication.instance() or QApplication([])
    (tmp_path / "VRProject").mkdir(parents=True, exist_ok=True)
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    fake_payload = {
        "state": "not_found",
        "reference": "UnknownClass.method",
        "message": "Classe ou método não encontrado na release ativa.",
    }
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits", lambda *a, **k: None), patch("vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference", return_value=fake_payload):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(250)
            page = window.findChild(QObject, "chatPage")
            chat.openDecompiledReference("vr-code:UnknownClass.method")
            for _ in range(150):
                QTest.qWait(20)
                if page.property("surfaceVisible") and page.property("surfaceIndex") == 6:
                    break
            assert page.property("surfaceVisible")
            assert page.property("surfaceIndex") == 6
            surface_view = window.findChild(QObject, "decompiledSurfaceView")
            assert surface_view is not None
            assert not surface_view.property("hasCode")
            status_notice = window.findChild(QObject, "decompiledStatusNotice")
            assert status_notice is not None
            assert "não encontrado" in status_notice.property("text")
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_chat_decompiled_surface_ambiguous(tmp_path):
    QApplication.instance() or QApplication([])
    (tmp_path / "VRProject").mkdir(parents=True, exist_ok=True)
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    fake_payload = {
        "state": "ambiguous",
        "reference": "CommonService.execute",
        "message": "Múltiplas classes encontradas. Selecione um candidato:",
        "candidates": [
            {"canonical": "br.com.vr.pkg1.CommonService.execute", "package_name": "br.com.vr.pkg1"},
            {"canonical": "br.com.vr.pkg2.CommonService.execute", "package_name": "br.com.vr.pkg2"},
        ],
    }
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits", lambda *a, **k: None), patch("vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference", return_value=fake_payload):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [x.toString() for x in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(250)
            page = window.findChild(QObject, "chatPage")
            chat.openDecompiledReference("vr-code:CommonService.execute")
            for _ in range(150):
                QTest.qWait(20)
                if page.property("surfaceVisible") and page.property("surfaceIndex") == 6:
                    break
            assert page.property("surfaceVisible")
            assert page.property("surfaceIndex") == 6
            surface_view = window.findChild(QObject, "decompiledSurfaceView")
            assert surface_view is not None
            assert surface_view.property("state") == "ambiguous"
            ambiguous_list = window.findChild(QObject, "decompiledAmbiguousList")
            assert ambiguous_list is not None
            assert ambiguous_list.property("count") == 2
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()

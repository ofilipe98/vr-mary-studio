"""Behavior checks for the presentation layer; no live provider calls."""
import pytest

import os
import threading
from unittest.mock import patch

os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QMetaObject, QObject, QSettings, Qt
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


def wait_until(predicate, timeout_ms=3000):
    for _ in range(max(1, timeout_ms // 10)):
        if predicate():
            return True
        QTest.qWait(10)
    return bool(predicate())


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


def test_open_decompiled_reference_resolves_and_emits_from_worker(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    delivery_threads = []
    calls = []
    qt_thread = threading.get_ident()

    def receive(payload):
        received.append(dict(payload))
        delivery_threads.append(threading.get_ident())

    chat.decompiledSourcePreviewRequested.connect(receive)

    def resolve(reference, **kwargs):
        calls.append((reference, kwargs, threading.get_ident(), threading.current_thread().name))
        return {
            "state": "ready",
            "reference": reference,
            "release_id": kwargs["release_id"],
            "title": "NotaSaidaFiscalService",
            "clean_target_line": 42,
        }

    try:
        with patch(
            "vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference",
            side_effect=resolve,
        ):
            chat.openDecompiledReference(
                "vr-code:NotaSaidaFiscalService.calcularImpostoItem"
            )
            assert received[0]["state"] == "loading"
            assert wait_until(lambda: len(received) == 2)

        assert [payload["state"] for payload in received] == ["loading", "ready"]
        assert delivery_threads == [qt_thread, qt_thread]
        assert type(calls[0][0]) is str
        assert calls[0][0] == "NotaSaidaFiscalService.calcularImpostoItem"
        assert calls[0][1] == {"release_id": received[0]["release_id"]}
        assert calls[0][2] != qt_thread
        assert calls[0][3] == "vr-code-preview"
    finally:
        chat.close()


def test_open_decompiled_reference_discards_superseded_request(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    first_started = threading.Event()
    release_first = threading.Event()
    chat.decompiledSourcePreviewRequested.connect(
        lambda payload: received.append(dict(payload))
    )

    def resolve(reference, **kwargs):
        if str(reference).startswith("First"):
            first_started.set()
            release_first.wait(2.0)
        return {"state": "ready", "reference": reference, "title": str(reference)}

    try:
        with patch(
            "vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference",
            side_effect=resolve,
        ):
            chat.openDecompiledReference("vr-code:First.method")
            assert first_started.wait(1.0)
            chat.openDecompiledReference("vr-code:Second.method")
            release_first.set()
            assert wait_until(
                lambda: any(
                    payload["state"] == "ready" and payload["title"] == "Second.method"
                    for payload in received
                )
            )
            QTest.qWait(100)

        assert [payload["state"] for payload in received[:2]] == [
            "loading",
            "loading",
        ]
        assert [
            payload["title"]
            for payload in received
            if payload["state"] == "ready"
        ] == ["Second.method"]
    finally:
        release_first.set()
        chat.close()


def test_open_decompiled_reference_close_discards_late_result(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    entered = threading.Event()
    release_worker = threading.Event()
    closed = False
    chat.decompiledSourcePreviewRequested.connect(
        lambda payload: received.append(dict(payload))
    )

    def resolve(reference, **kwargs):
        entered.set()
        release_worker.wait(2.0)
        return {"state": "ready", "reference": reference, "title": "Late"}

    try:
        with patch(
            "vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference",
            side_effect=resolve,
        ):
            chat.openDecompiledReference("vr-code:Late.method")
            assert entered.wait(1.0)
            chat.close()
            closed = True
            release_worker.set()
            QTest.qWait(150)

        assert [payload["state"] for payload in received] == ["loading"]
    finally:
        release_worker.set()
        if not closed:
            chat.close()


def test_open_decompiled_reference_rejects_invalid_uri_and_raw_reference(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    chat.decompiledSourcePreviewRequested.connect(
        lambda payload: received.append(dict(payload))
    )

    try:
        with patch(
            "vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference"
        ) as resolver:
            chat.openDecompiledReference("NotaSaidaFiscalService.calcularImpostoItem")
            chat.openDecompiledReference("vr-code:invalid%20reference")
            QTest.qWait(100)

        resolver.assert_not_called()
        assert received == []
    finally:
        chat.close()


def test_open_decompiled_reference_handles_unexpected_error(tmp_path):
    QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, prefs)
    received = []
    chat.decompiledSourcePreviewRequested.connect(
        lambda payload: received.append(dict(payload))
    )

    try:
        with patch(
            "vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference",
            side_effect=RuntimeError("Index crash"),
        ):
            chat.openDecompiledReference("vr-code:Broken.method")
            assert wait_until(lambda: len(received) == 2)

        assert [payload["state"] for payload in received] == ["loading", "error"]
        assert received[1]["reference"] == "Broken.method"
        assert received[1]["release_id"] == received[0]["release_id"]
        assert "Index crash" in received[1]["message"]
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
    clean_lines = ["class NotaSaidaFiscalService {"]
    clean_lines.extend(f"    private int field{index};" for index in range(1, 41))
    clean_lines.append("}")
    clean_lines.insert(29, "    public void calcularImpostoItem() {")
    clean_body = "\n".join(clean_lines)
    raw_body = "class NotaSaidaFiscalService {\n" + "\n".join(
        f"    private int rawField{index};" for index in range(1, 46)
    ) + "\n}"
    fake_payload = {
        "state": "ready",
        "reference": "NotaSaidaFiscalService.calcularImpostoItem",
        "release_id": "r1",
        "title": "NotaSaidaFiscalService",
        "qualified_name": "br.com.vrsoft.fiscal.NotaSaidaFiscalService",
        "jar_relative_path": "lib/nota-fiscal.jar",
        "target_symbol": "calcularImpostoItem",
        "overload_count": 1,
        "raw_target_line": 35,
        "clean_target_line": 30,
        "clean_available": True,
        "clean_status": "cleaned",
        "truncated": True,
        "body": raw_body,
        "clean_body": clean_body,
    }
    received = []
    chat.decompiledSourcePreviewRequested.connect(
        lambda payload: received.append(dict(payload))
    )
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits", lambda *a, **k: None), patch(
            "vrsoft_extractor.mary.frontend.bridges.codepreview.JavaCodeIndex.resolve_decompiled_reference",
            return_value=fake_payload,
        ):
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
                "vr-code:NotaSaidaFiscalService.calcularImpostoItem" in display
                for display in displays
            )
            page = window.findChild(QObject, "chatPage")
            chat.openDecompiledReference(
                "vr-code:NotaSaidaFiscalService.calcularImpostoItem"
            )
            assert wait_until(
                lambda: sum(item["state"] == "ready" for item in received) == 1
            )
            chat.openDecompiledReference(
                "vr-code:NotaSaidaFiscalService.calcularImpostoItem"
            )
            assert wait_until(
                lambda: sum(item["state"] == "ready" for item in received) == 2
            )
            QTest.qWait(150)

            assert page.property("surfaceVisible")
            assert page.property("surfaceIndex") == 6
            tabs = page.property("openSurfaceTabs")
            tabs = tabs.toVariant() if hasattr(tabs, "toVariant") else tabs
            assert sum(int(tab["page"]) == 6 for tab in tabs) == 1
            source_viewer = window.findChild(QObject, "decompiledSourceViewer")
            source_viewport = window.findChild(QObject, "decompiledSourceViewport")
            source_body = window.findChild(QObject, "decompiledSourceBody")
            assert source_viewer is not None
            assert source_viewport is not None
            assert source_body is not None
            assert source_viewer.property("code") == clean_body
            assert source_viewer.property("targetLine") == 30
            assert source_viewer.property("language") == "java"
            assert source_body.property("text") == clean_body

            clean_button = window.findChild(QObject, "decompiledCodeCleanModeButton")
            raw_button = window.findChild(QObject, "decompiledCodeRawModeButton")
            copy_button = window.findChild(QObject, "copyDecompiledCodeButton")
            assert clean_button is not None
            assert raw_button is not None
            assert copy_button is not None
            assert clean_button.property("enabled")

            raw_button.click()
            QTest.qWait(100)
            assert not page.property("decompiledCodeCleanMode")
            assert source_viewer.property("code") == raw_body
            assert source_viewer.property("targetLine") == 35
            copy_button.click()
            QTest.qWait(50)
            assert QApplication.instance().clipboard().text() == raw_body

            clean_button.click()
            QTest.qWait(100)
            assert page.property("decompiledCodeCleanMode")
            assert source_viewer.property("code") == clean_body
            assert source_viewer.property("targetLine") == 30
            copy_button.click()
            QTest.qWait(50)
            assert QApplication.instance().clipboard().text() == clean_body

            source_body.select(0, 5)
            selected_text = source_body.property("selectedText")
            cursor_position = source_body.property("cursorPosition")
            assert selected_text
            QMetaObject.invokeMethod(source_viewer, "revealLine")
            QTest.qWait(100)
            assert source_body.property("selectedText") == selected_text
            assert source_body.property("cursorPosition") == cursor_position
            assert source_viewport.property("contentY") > 0

            for removed_name in (
                "decompiledSurfaceView",
                "decompiledCodeScroll",
                "decompiledCodeBody",
                "decompiledStatusNotice",
                "decompiledAmbiguousList",
                "lineGutter",
                "gutterText",
            ):
                assert find_items(window.contentItem(), removed_name) == []
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
            assert wait_until(
                lambda: page.property("surfaceIndex") == 6
                and window.findChild(QObject, "decompiledCodeStatusMessage") is not None
                and "não encontrado"
                in window.findChild(QObject, "decompiledCodeStatusMessage").property("text")
            )
            assert page.property("surfaceVisible")
            assert page.property("surfaceIndex") == 6
            status_notice = window.findChild(QObject, "decompiledCodeStatusMessage")
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
        "message": "Múltiplas classes encontradas.",
        "candidates": [
            {
                "qualified_name": f"br.com.vr.pkg{index}.CommonService",
                "jar_relative_path": f"lib/common-{index}.jar",
            }
            for index in range(22)
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
            assert wait_until(
                lambda: window.findChild(QObject, "decompiledCodeCandidateList") is not None
                and window.findChild(
                    QObject, "decompiledCodeCandidateList"
                ).property("count") == 20
            )
            assert page.property("surfaceVisible")
            assert page.property("surfaceIndex") == 6
            assert "Múltiplas" in window.findChild(
                QObject, "decompiledCodeAmbiguousMessage"
            ).property("text")
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_vr_shimmer_text_fluid_properties():
    import re
    from PySide6.QtCore import QUrl
    from PySide6.QtQuick import QQuickView

    app = QApplication.instance() or QApplication([])
    view = QQuickView()
    view.setSource(QUrl.fromLocalFile("vrsoft_extractor/mary/frontend/qml/components/VrShimmerText.qml"))
    item = view.rootObject()
    assert item is not None
    item.setProperty("text", "Trabalhando há 5s")
    item.setProperty("running", True)

    # Boundaries (-0.4 and 1.4) must match resting color without popping
    item.setProperty("phase", -0.4)
    markup_left = item.shimmerMarkup("Trabalhando há 5s")
    item.setProperty("phase", 1.4)
    markup_right = item.shimmerMarkup("Trabalhando há 5s")
    assert markup_left == markup_right

    # Mid phase must provide smooth highlight
    item.setProperty("phase", 0.5)
    markup_mid = item.shimmerMarkup("Trabalhando há 5s")
    colors_mid = re.findall(r'<font color="#([0-9a-f]{6})">', markup_mid)
    colors_rest = re.findall(r'<font color="#([0-9a-f]{6})">', markup_left)
    assert any(c != colors_rest[0] for c in colors_mid)

    # Empty string handling
    assert item.shimmerMarkup("") == ""

    # Non-running state turns off shimmering
    item.setProperty("running", False)
    assert not item.property("shimmering")

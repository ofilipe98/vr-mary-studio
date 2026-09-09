"""Authored content must survive formatting, streaming, and clipboard export."""
import csv
import io

import pytest
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.frontend.bridges.presentation import (
    markdown_for_display, segments_for_display,
)
from vrsoft_extractor.mary.frontend.text_rendering import (
    CodeSyntaxHighlighter, presentation_blocks, table_clipboard_text,
)


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("fence", ["```", "````", "~~~", "~~~~"])
def test_fences_keep_code_verbatim_and_share_display_boundaries(fence):
    code = 'Texto pronto.Próximo passo.\n| Coluna |\n| --- |\n'
    if len(fence) > 3:
        code += fence[:3] + "\n"
    source = f"Antes pronto.Próximo.\n\n{fence}text\n{code}{fence}\n\nDepois."
    blocks = presentation_blocks(markdown_for_display(source))
    assert [block["kind"] for block in blocks] == ["text", "code", "text"]
    assert blocks[0]["content"] == "Antes pronto. Próximo."
    assert blocks[1]["content"] == code[:-1]
    assert segments_for_display(source)[1]["content"] == code[:-1]
    # Unclosed fences are already code, with authored whitespace preserved.
    partial = f"{fence}python\nprint('https://host/#anchor')\n\n"
    assert presentation_blocks(partial)[0]["content"].endswith("\n\n")
    assert markdown_for_display(partial) == partial


def test_tables_require_complete_delimiter_and_keep_neighboring_prose():
    table = "| **Área** | Caminho |\n| :--- | ---: |\n| Fiscal | `a\\|b` |"
    result = presentation_blocks("Introdução.\n\n" + table + "\n\nConclusão.")
    assert [block["kind"] for block in result] == ["text", "table", "text"]
    assert result[1] == {"kind": "table", "content": table, "columns": "2"}
    assert result[-1]["content"] == "Conclusão."
    for partial in ("| A | B |\n| --", "| A | B |\n| --- |", "    | A |\n    | --- |"):
        assert all(block["kind"] == "text" for block in presentation_blocks(partial))


def test_table_exports_rendered_cells_with_csv_escaping(application):
    source = '| Nome | Valor |\n| --- | --- |\n| **Área** | a, "b" |\n| `x` | [Manual](https://example.com) |'
    assert table_clipboard_text(source, "markdown") == source
    expected = [["Nome", "Valor"], ["Área", 'a, "b"'], ["x", "Manual"]]
    for format_name, delimiter in (("csv", ","), ("tsv", "\t")):
        assert list(csv.reader(io.StringIO(table_clipboard_text(source, format_name)), delimiter=delimiter)) == expected


def test_highlighting_does_not_treat_strings_as_comments_or_color_prompts(application):
    document = QTextDocument()
    text = 'emoji = "😀"; url = "https://host/#anchor"; return 42 # comment'
    document.setPlainText(text)
    highlighter = CodeSyntaxHighlighter(document, "python")
    highlighter.set_theme(True)
    formats = document.firstBlock().layout().formats()
    url_start = len(text[:text.index('"https')].encode("utf-16-le")) // 2
    span = next(span for span in formats if span.start == url_start)
    assert span.format.foreground() == highlighter.string_format.foreground()
    return_start = len(text[:text.index("return")].encode("utf-16-le")) // 2
    assert next(span for span in formats if span.start == return_start).format.foreground() == highlighter.keyword_format.foreground()
    highlighter.language = "text"
    highlighter.rehighlight()
    assert document.firstBlock().layout().formats() == []

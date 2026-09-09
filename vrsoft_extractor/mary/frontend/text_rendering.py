"""Markdown and code presentation helpers used by the QML frontend."""

from __future__ import annotations

import csv
import io
import re
from urllib.parse import urlparse

from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImageReader,
    QSyntaxHighlighter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
    QTextLength,
    QTextTable,
    QTextTableCellFormat,
)
from PySide6.QtWidgets import QApplication
from ..brand import brand_palette

class CodeSyntaxHighlighter(QSyntaxHighlighter):
    """Small, dependency-free highlighter for chat code blocks."""

    _GENERAL_KEYWORDS = {
        "and", "as", "assert", "async", "await", "break", "case", "catch",
        "class", "const", "continue", "def", "default", "del", "do", "elif",
        "else", "enum", "except", "export", "extends", "false", "finally",
        "for", "from", "function", "if", "import", "in", "interface", "is",
        "lambda", "let", "match", "new", "none", "not", "null", "or", "pass",
        "raise", "return", "static", "switch", "throw", "true", "try", "var",
        "while", "with", "yield",
    }
    _SQL_KEYWORDS = {
        "all", "and", "as", "asc", "by", "case", "count", "create", "delete",
        "desc", "distinct", "else", "end", "false", "from", "full", "group",
        "having", "in", "inner", "insert", "into", "is", "join", "left", "like",
        "limit", "not", "null", "on", "or", "order", "outer", "right", "select",
        "set", "table", "then", "true", "union", "update", "values", "when",
        "where", "with",
    }

    def __init__(self, document: QTextDocument, language: str = ""):
        super().__init__(document)
        self.language = str(language or "").strip().casefold()
        self.keyword_format = QTextCharFormat()
        self.keyword_format.setForeground(QColor("#FF7AB2"))
        self.keyword_format.setFontWeight(QFont.Bold)
        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor("#43D17B"))
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#7F8C98"))
        self.number_format = QTextCharFormat()
        self.number_format.setForeground(QColor("#67B7FF"))

    def set_theme(self, dark: bool) -> None:
        self.keyword_format.setForeground(QColor("#E99ABF" if dark else "#9B2861"))
        self.string_format.setForeground(QColor("#A5C99A" if dark else "#376B2B"))
        self.comment_format.setForeground(QColor("#96969F" if dark else "#62626E"))
        self.number_format.setForeground(QColor("#A3BDD9" if dark else "#275C8A"))
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        # Plain-text prompts and unknown languages should stay neutral.
        if self.language not in {
            "python", "py", "sql", "postgres", "postgresql", "plsql", "json",
            "javascript", "js", "typescript", "ts", "jsx", "tsx", "java",
            "c", "cpp", "c++", "csharp", "cs", "go", "rust", "rs", "qml",
            "bash", "sh", "shell", "powershell", "ps1", "yaml", "yml",
        }:
            return
        sql = self.language in {"sql", "postgres", "postgresql", "plsql"}
        keywords = self._SQL_KEYWORDS if sql else self._GENERAL_KEYWORDS
        comment_pattern = (
            r"--.*$" if sql else r"#.*$" if self.language in {
                "python", "py", "bash", "sh", "shell", "powershell", "ps1", "yaml", "yml"
            } else r"(?!)" if self.language == "json" else r"//.*$"
        )
        token_re = re.compile(
            r"(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
            + r"|(?P<comment>" + comment_pattern + r")"
            + r"|(?P<number>\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b)"
            + r"|(?P<keyword>\b(?:" + "|".join(sorted(keywords, key=len, reverse=True)) + r")\b)",
            re.IGNORECASE if sql else 0,
        )
        # Match in source order: a URL or # inside a string is not a comment.
        formats = {"string": self.string_format, "comment": self.comment_format,
                   "number": self.number_format, "keyword": self.keyword_format}
        # Qt indexes UTF-16 units. Build offsets once, including emoji, instead
        # of re-encoding a growing prefix for every token of a long code line.
        offsets = [0]
        for character in text:
            offsets.append(offsets[-1] + (2 if ord(character) > 0xFFFF else 1))
        for match in token_re.finditer(text):
            self.setFormat(
                offsets[match.start()],
                offsets[match.end()] - offsets[match.start()],
                formats[match.lastgroup],
            )


FENCE_START_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)$")


def fenced_blocks(markdown: str) -> list[dict[str, str]]:
    """Share fence boundaries between display normalization and QML cards."""
    lines = markdown.splitlines(keepends=True)
    blocks = []
    pending = []
    index = 0
    while index < len(lines):
        opening = FENCE_START_RE.fullmatch(lines[index].rstrip("\r\n"))
        if opening is None or (opening[1][0] == "`" and "`" in opening[2]):
            pending.append(lines[index])
            index += 1
            continue
        if pending:
            blocks.append({"kind": "text", "content": "".join(pending)})
        pending = []
        start = index
        fence, info = opening.groups()
        closing = re.compile(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$")
        index += 1
        body = []
        while index < len(lines) and not closing.fullmatch(lines[index].rstrip("\r\n")):
            body.append(lines[index])
            index += 1
        content = "".join(body)
        if index < len(lines):
            content = content.removesuffix("\n").removesuffix("\r")
            index += 1
        blocks.append({"kind": "code", "content": content,
                       "language": info.strip().split()[0].casefold() if info.strip() else "text",
                       "raw": "".join(lines[start:index])})
    if pending:
        blocks.append({"kind": "text", "content": "".join(pending)})
    return blocks


def _table_cells(line: str) -> list[str]:
    """Split GFM cells without treating an escaped pipe as a separator."""
    cells = []
    start = 0
    escaped = False
    line = line.strip()
    for index, character in enumerate(line):
        if character == "|" and not escaped:
            cells.append(line[start:index])
            start = index + 1
        escaped = character == "\\" and not escaped
    cells.append(line[start:])
    if cells and not cells[0]:
        cells.pop(0)
    if cells and not cells[-1]:
        cells.pop()
    return [cell.strip() for cell in cells]


def _prose_tables(text: str) -> list[dict[str, str]]:
    lines = text.splitlines(keepends=True)
    blocks = []
    pending = []
    index = 0
    while index < len(lines):
        header = lines[index]
        delimiter = _table_cells(lines[index + 1]) if index + 1 < len(lines) else []
        is_table = (
            "|" in header and not header.startswith(("    ", "\t"))
            and not re.match(r" {0,3}(?:>|#|[-+*]\s|\d+[.)]\s)", header)
            and delimiter and len(delimiter) == len(_table_cells(header))
            and all(re.fullmatch(r":?-+:?", cell) for cell in delimiter)
        )
        if not is_table:
            pending.append(header)
            index += 1
            continue
        if "".join(pending).strip():
            blocks.append({"kind": "text", "content": "".join(pending).strip()})
        pending = []
        end = index + 2
        while end < len(lines) and "|" in lines[end] and lines[end].strip():
            if lines[end].startswith(("    ", "\t", ">", "#")):
                break
            end += 1
        blocks.append({"kind": "table", "content": "".join(lines[index:end]).strip(),
                       "columns": str(len(delimiter))})
        index = end
    if "".join(pending).strip():
        blocks.append({"kind": "text", "content": "".join(pending).strip()})
    return blocks


def table_clipboard_text(markdown: str, format_name: str) -> str:
    """Export rendered cell text using Qt's existing Markdown parser."""
    if format_name == "markdown":
        return markdown
    document = QTextDocument()
    document.setMarkdown(markdown)
    table = next((frame for frame in document.rootFrame().childFrames()
                  if isinstance(frame, QTextTable)), None)
    if table is None:
        return markdown
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t" if format_name == "tsv" else ",")
    for row in range(table.rows()):
        values = []
        for column in range(table.columns()):
            cell = table.cellAt(row, column)
            cursor = cell.firstCursorPosition()
            cursor.setPosition(cell.lastPosition(), QTextCursor.KeepAnchor)
            values.append(cursor.selectedText().replace("\u2029", "\n"))
        writer.writerow(values)
    return output.getvalue()


def table_row_edges(document: QTextDocument) -> list[float]:
    """Qt Quick omits per-cell borders; expose actual layout edges for QML."""
    layout = document.documentLayout()
    edges = []
    for table in document.rootFrame().childFrames():
        if not isinstance(table, QTextTable):
            continue
        for row in range(table.rows()):
            bottom = max(
                layout.blockBoundingRect(table.cellAt(row, column).lastCursorPosition().block()).bottom()
                for column in range(table.columns())
            )
            edges.append(bottom + table.format().cellPadding())
    return edges


def presentation_blocks(markdown: str) -> list[dict[str, str]]:
    """Presentation only: preserve prose; extract fences and explicit source lists.

    Only complete Markdown links on standalone list lines become citations.
    Incomplete streaming links and prose remain in the selectable document.
    """
    blocks: list[dict[str, str]] = []

    def prose(text: str) -> None:
        lines = text.splitlines(keepends=True)
        pending = []
        sources = False
        heading_index = None
        for line in lines:
            if re.fullmatch(r'\s*(?:#{1,6}\s*)?(?:\*\*)?(?:Fontes(?: consultadas)?|Sources|Referências)(?:\*\*)?:?\s*', line, re.I):
                sources = True
                heading_index = len(pending)
                pending.append(line)
                continue
            match = re.fullmatch(r'\s*(?:[-*+]\s+|\d+[.)]\s+)?\[([^\]]+)\]\((https?://[^\s]+)\)\s*', line)
            if sources and match:
                title, url = match.groups()
                # Remove the heading only after a citation is actually found.
                if heading_index is not None:
                    pending = pending[:heading_index]
                    heading_index = None
                if ''.join(pending).strip():
                    blocks.extend(_prose_tables(''.join(pending)))
                pending = []
                blocks.append({'kind': 'source', 'content': title, 'url': url,
                               'origin': urlparse(url).netloc})
            else:
                if line.strip() and not re.search(r'Fontes|Sources|Referências', line, re.I):
                    sources = False
                    heading_index = None
                pending.append(line)
        if ''.join(pending).strip():
            blocks.extend(_prose_tables(''.join(pending)))

    for block in fenced_blocks(markdown):
        if block["kind"] == "code":
            blocks.append({key: value for key, value in block.items() if key != "raw"})
        else:
            prose(block["content"])
    return blocks

_LANGUAGE_BADGES = {
    "python": "Py",
    "py": "Py",
    "sql": "DB",
    "postgres": "DB",
    "postgresql": "DB",
    "json": "{}",
    "javascript": "JS",
    "js": "JS",
    "typescript": "TS",
    "ts": "TS",
    "powershell": ">_",
    "shell": ">_",
    "bash": ">_",
}


def code_language_badge(language: str) -> str:
    normalized = str(language or "text").strip().casefold() or "text"
    return _LANGUAGE_BADGES.get(
        normalized,
        "<>" if normalized == "text" else normalized[:3].upper(),
    )


_THEMATIC_BREAK_RE = re.compile(
    r"(?:^|\n)[ \t]*\n[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*(?:\n|$)"
    r"|^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*(?:\n|$)"
)


def _count_horizontal_rules(markdown: str) -> int:
    return len(_THEMATIC_BREAK_RE.findall(str(markdown or "")))


def _style_document_tables(
    document: QTextDocument,
    dark: bool,
    ranges: list[tuple[int, int]],
) -> None:
    """Style tables with quiet horizontal rules and record their extents."""
    palette = brand_palette("dark_orange" if dark else "light")
    border = QColor(palette["chatBorder"])

    def visit(frame) -> None:
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                table_format = child.format()
                table_format.setBorder(0)
                table_format.setBorderBrush(border)
                table_format.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
                table_format.setBorderCollapse(False)
                table_format.setCellPadding(8)
                table_format.setCellSpacing(0)
                table_format.setWidth(QTextLength(QTextLength.PercentageLength, 100))
                child.setFormat(table_format)
                for row in range(child.rows()):
                    for column in range(child.columns()):
                        cell = child.cellAt(row, column)
                        if not cell.isValid():
                            continue
                        # Qt's importer can leave an empty paragraph in the
                        # first header cell when a table follows a blockquote.
                        start = cell.firstCursorPosition()
                        if (not start.block().text() and start.block().next().isValid()
                                and start.block().next().position() < cell.lastPosition()):
                            start.setPosition(start.block().next().position(), QTextCursor.KeepAnchor)
                            start.removeSelectedText()
                        cell_format = QTextTableCellFormat(cell.format())
                        cell_format.setLeftBorder(0)
                        cell_format.setRightBorder(0)
                        cell_format.setTopBorder(0)
                        cell_format.setBottomBorder(1)
                        cell_format.setBorderBrush(border)
                        cell_format.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
                        cell_format.clearBackground()
                        if row == 0:
                            header_cursor = cell.firstCursorPosition()
                            header_cursor.setPosition(cell.lastPosition(), QTextCursor.KeepAnchor)
                            header_style = QTextCharFormat()
                            header_style.setFontWeight(QFont.Weight.DemiBold)
                            header_cursor.mergeCharFormat(header_style)
                        cell.setFormat(cell_format)
                ranges.append((child.firstPosition(), child.lastPosition() + 1))
            visit(child)

    visit(document.rootFrame())


def apply_message_document_style(
    document: QTextDocument,
    markdown: str = "",
    dark: bool | None = None,
    monospace_family: str = "Consolas",
) -> None:
    """Commit formatting once instead of laying out after every fragment."""
    cursor = QTextCursor(document)
    cursor.beginEditBlock()
    try:
        _apply_message_document_style(document, markdown, dark, monospace_family)
    finally:
        cursor.endEditBlock()


def _apply_message_document_style(
    document: QTextDocument,
    markdown: str = "",
    dark: bool | None = None,
    monospace_family: str = "Consolas",
) -> None:
    """Apply the T3-like rhythm that Qt's Markdown importer omits."""
    if dark is None:
        application = QApplication.instance()
        dark = bool(
            application
            and application.property("vr_theme") == "dark_orange"
        )
    palette = brand_palette("dark_orange" if dark else "light")
    text_color = QColor(palette["text"])
    heading_color = QColor(palette["headingText"])
    muted_color = QColor(palette["mutedText"])
    link_color = QColor(palette["link"])
    code_text = text_color
    code_background = QColor(palette["inlineCodeSurface"])
    quote_background = QColor(palette["quoteSurface"])
    rule_color = QColor(palette["chatDivider"])
    document.setIndentWidth(18)
    base_px = document.defaultFont().pixelSize()
    if base_px <= 0:
        base_px = document.defaultFont().pointSizeF() * 96 / 72

    table_ranges: list[tuple[int, int]] = []
    _style_document_tables(document, dark, table_ranges)
    rule_budget = _count_horizontal_rules(markdown)

    def inside_table(position: int) -> bool:
        return any(start <= position < end for start, end in table_ranges)

    def quote_level_of(block_format: QTextBlockFormat) -> int:
        key = int(QTextFormat.BlockQuoteLevel)
        if not block_format.hasProperty(key):
            return 0
        return int(block_format.property(key))

    def is_code_block(block_format: QTextBlockFormat) -> bool:
        return block_format.hasProperty(int(QTextFormat.BlockCodeLanguage))

    block = document.firstBlock()
    previous_quote = False
    previous_code = False
    while block.isValid():
        block_format = block.blockFormat()
        block_format.setLineHeight(
            base_px * 1.6,
            QTextBlockFormat.FixedHeight.value,
        )
        heading_level = block_format.headingLevel()
        text_list = block.textList()
        quote_level = quote_level_of(block_format)
        code_flag = is_code_block(block_format)
        in_table = inside_table(block.position())
        next_block = block.next()
        if in_table:
            block_format.clearBackground()
            block_format.setLineHeight(base_px * 1.5, QTextBlockFormat.FixedHeight.value)
            block_format.setTopMargin(0)
            block_format.setBottomMargin(0)
            block_format.setLeftMargin(0)
            block_format.setRightMargin(0)
            block_cursor = QTextCursor(block)
            block_cursor.setBlockFormat(block_format)
        if not in_table:
            if heading_level:
                block_format.setLineHeight(base_px * 1.9, QTextBlockFormat.FixedHeight.value)
                block_format.setTopMargin(0 if block == document.firstBlock() else 22)
                block_format.setBottomMargin(8)
            elif text_list is not None:
                same_list_continues = (
                    next_block.isValid() and next_block.textList() is text_list
                )
                block_format.setTopMargin(0)
                block_format.setBottomMargin(3 if same_list_continues else 10)
            elif quote_level:
                quote_continues = next_block.isValid() and bool(
                    quote_level_of(next_block.blockFormat())
                )
                block_format.setTopMargin(0 if previous_quote else 12)
                block_format.setBottomMargin(0 if quote_continues else 11)
                block_format.setLeftMargin(10)
                block_format.setRightMargin(6)
                block_format.setBackground(QBrush(quote_background))
            elif code_flag:
                code_continues = next_block.isValid() and is_code_block(
                    next_block.blockFormat()
                )
                block_format.setTopMargin(0 if previous_code else 12)
                block_format.setBottomMargin(0 if code_continues else 10)
                block_format.setLeftMargin(10)
                block_format.setRightMargin(10)
                block_format.setBackground(QBrush(code_background))
            elif not block.text() and rule_budget > 0:
                rule_budget -= 1
                block_format.setLineHeight(2.0, QTextBlockFormat.FixedHeight.value)
                block_format.setBackground(QBrush(rule_color))
                block_format.setTopMargin(10)
                block_format.setBottomMargin(12)
            else:
                block_format.setTopMargin(0)
                block_format.setBottomMargin(0 if not next_block.isValid() else 12)
            previous_quote = bool(quote_level)
            previous_code = code_flag
            block_cursor = QTextCursor(block)
            block_cursor.setBlockFormat(block_format)

        in_quote = bool(quote_level)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            fragment_format = fragment.charFormat()
            if fragment_format.isImageFormat():
                image_format = fragment_format.toImageFormat()
                image_url = QUrl(image_format.name())
                image_path = (
                    image_url.toLocalFile()
                    if image_url.isLocalFile()
                    else image_format.name()
                )
                image_size = QImageReader(image_path).size()
                if image_size.isValid() and image_size.width() > 0:
                    scale = min(
                        1.0,
                        480.0 / image_size.width(),
                        320.0 / image_size.height(),
                    )
                    image_format.setWidth(image_size.width() * scale)
                    image_format.setHeight(image_size.height() * scale)
                fragment_cursor = QTextCursor(document)
                fragment_cursor.setPosition(fragment.position())
                fragment_cursor.setPosition(
                    fragment.position() + fragment.length(),
                    QTextCursor.KeepAnchor,
                )
                fragment_cursor.mergeCharFormat(image_format)
                iterator += 1
                continue
            if code_flag or fragment_format.fontFixedPitch():
                fragment_format.setFontFamilies([monospace_family])
                fragment_format.setProperty(QTextFormat.FontPixelSize, round(base_px * 0.9))
                fragment_format.setForeground(code_text)
                fragment_format.setBackground(code_background)
            elif heading_level:
                fragment_format.setProperty(QTextFormat.FontPixelSize,
                    round(base_px * {1: 1.5, 2: 1.28, 3: 1.1}.get(heading_level, 1.0)))
                fragment_format.setFontWeight(QFont.Weight.DemiBold)
                fragment_format.setForeground(heading_color)
            elif fragment_format.isAnchor():
                fragment_format.setForeground(link_color)
                fragment_format.setFontUnderline(False)
            elif in_quote:
                fragment_format.setForeground(muted_color)
            else:
                fragment_format.setForeground(text_color)
            fragment_cursor = QTextCursor(document)
            fragment_cursor.setPosition(fragment.position())
            fragment_cursor.setPosition(
                fragment.position() + fragment.length(),
                QTextCursor.KeepAnchor,
            )
            fragment_cursor.mergeCharFormat(fragment_format)
            iterator += 1
        block = next_block

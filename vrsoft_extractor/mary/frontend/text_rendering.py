"""Markdown and code presentation helpers used by the QML frontend."""

from __future__ import annotations

import re

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

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        sql = self.language in {"sql", "postgres", "postgresql", "plsql"}
        keywords = self._SQL_KEYWORDS if sql else self._GENERAL_KEYWORDS
        keyword_re = re.compile(
            r"\b(?:" + "|".join(sorted(keywords, key=len, reverse=True)) + r")\b",
            re.IGNORECASE if sql else 0,
        )
        for match in keyword_re.finditer(text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.keyword_format
            )
        for match in re.finditer(r"\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b", text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.number_format
            )
        for match in re.finditer(r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")", text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.string_format
            )
        comment_pattern = r"--.*$" if sql else r"#.*$|//.*$"
        for match in re.finditer(comment_pattern, text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.comment_format
            )


FENCE_RE = re.compile(
    r"^```([^\n`]*)\n(.*?)(?:\n```[ \t]*(?=\n|$)|\Z)",
    re.MULTILINE | re.DOTALL,
)

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
    """Give imported tables the bordered T3 look and record their extents."""
    border = QColor("#3F3F46" if dark else "#D8D8E0")
    header_background = QColor("#26262B" if dark else "#F0F0F4")

    def visit(frame) -> None:
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                table_format = child.format()
                table_format.setBorder(1)
                table_format.setBorderBrush(border)
                table_format.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
                table_format.setBorderCollapse(True)
                table_format.setCellPadding(6)
                table_format.setCellSpacing(0)
                table_format.setWidth(QTextLength(QTextLength.PercentageLength, 100))
                child.setFormat(table_format)
                ranges.append((child.firstPosition(), child.lastPosition() + 1))
                for row in range(child.rows()):
                    for column in range(child.columns()):
                        cell = child.cellAt(row, column)
                        if not cell.isValid():
                            continue
                        cell_format = QTextTableCellFormat(cell.format())
                        cell_format.setLeftBorder(1)
                        cell_format.setRightBorder(1)
                        cell_format.setTopBorder(1)
                        cell_format.setBottomBorder(1)
                        cell_format.setBorderBrush(border)
                        cell_format.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
                        if row == 0:
                            cell_format.setBackground(header_background)
                        cell.setFormat(cell_format)
            visit(child)

    visit(document.rootFrame())


def apply_message_document_style(
    document: QTextDocument,
    markdown: str = "",
    dark: bool | None = None,
) -> None:
    """Apply the T3-like rhythm that Qt's Markdown importer omits."""
    if dark is None:
        application = QApplication.instance()
        dark = bool(
            application
            and application.property("vr_theme") == "dark_orange"
        )
    text_color = QColor("#D6D6D9" if dark else "#27272A")
    heading_color = QColor("#ECECEF" if dark else "#18181B")
    muted_color = QColor("#96969F" if dark else "#52525B")
    link_color = QColor("#73B7FF" if dark else "#075EAD")
    code_text = QColor("#DEDEE2" if dark else "#27272A")
    code_background = QColor("#26262B" if dark else "#ECECF1")
    quote_background = QColor("#232327" if dark else "#F4F4F7")
    rule_color = QColor("#3F3F46" if dark else "#C9C9D3")
    document.setIndentWidth(18)

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
            148.0,
            QTextBlockFormat.ProportionalHeight.value,
        )
        heading_level = block_format.headingLevel()
        text_list = block.textList()
        quote_level = quote_level_of(block_format)
        code_flag = is_code_block(block_format)
        in_table = inside_table(block.position())
        next_block = block.next()
        if not in_table:
            if heading_level:
                block_format.setTopMargin(0 if block == document.firstBlock() else 18)
                block_format.setBottomMargin(8)
            elif text_list is not None:
                same_list_continues = (
                    next_block.isValid() and next_block.textList() is text_list
                )
                block_format.setTopMargin(0)
                block_format.setBottomMargin(5 if same_list_continues else 11)
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
            if fragment_format.fontFixedPitch():
                fragment_format.setFontFamilies(["Consolas"])
                fragment_format.setFontPointSize(9.5)
                fragment_format.setForeground(code_text)
                fragment_format.setBackground(code_background)
            elif heading_level:
                fragment_format.setFontPointSize(
                    {1: 15.0, 2: 12.75, 3: 11.25}.get(
                        heading_level,
                        10.5,
                    )
                )
                fragment_format.setFontWeight(QFont.Weight.DemiBold)
                fragment_format.setForeground(heading_color)
            elif fragment_format.isAnchor():
                fragment_format.setForeground(link_color)
                fragment_format.setFontUnderline(True)
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

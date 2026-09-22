"""Presentation-only cleaning for decompiled Java sources.

The decompiled text stored in the index remains the source of truth. This
module derives a readable view without touching identifiers, literals,
operators, annotations, imports, expressions, control flow, synthetic or
bridge members or declaration order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_BANNER_TOOLS = frozenset({"cfr", "vineflower"})
_EDGE_WHITESPACE = " \t"
_INITIAL_WHITESPACE = "\ufeff \t\r\n"

_NORMAL = 0
_STRING = 1
_CHAR = 2
_TEXT_BLOCK = 3
_LINE_COMMENT = 4
_BLOCK_COMMENT = 5
_UNTERMINATED_STATES = frozenset({_STRING, _CHAR, _TEXT_BLOCK, _BLOCK_COMMENT})

_UNSUPPORTED_NOTE = "Limpeza automática disponível apenas para fontes Java."
_FALLBACK_NOTE = (
    "A estrutura léxica não pôde ser validada; exibindo o descompilado original."
)
_CLEANED_NOTE = (
    "Visualização limpa gerada sem alterar identificadores, literais ou lógica."
)
_UNCHANGED_NOTE = "O descompilado já está no formato seguro de leitura."


@dataclass(frozen=True)
class CleanSourceResult:
    body: str
    available: bool
    status: Literal["cleaned", "unchanged", "unsupported", "fallback"]
    note: str


def clean_decompiled_source(
    body: str,
    *,
    source_relative_path: str,
    tool: str,
) -> CleanSourceResult:
    """Derive a clean reading view of a decompiled source without rewriting it."""
    if Path(source_relative_path).suffix.casefold() != ".java":
        return CleanSourceResult(
            body=body,
            available=False,
            status="unsupported",
            note=_UNSUPPORTED_NOTE,
        )
    spans = _scan_protected(body)
    if spans is None:
        return CleanSourceResult(
            body=body,
            available=True,
            status="fallback",
            note=_FALLBACK_NOTE,
        )
    text = body
    active_spans = spans
    banner = _initial_banner(body, spans, tool)
    if banner is not None:
        start, end = banner
        delta = end - start
        text = body[:start] + body[end:]
        active_spans = [
            (s - delta if s >= end else s, e - delta if e > end else e)
            for s, e in spans
            if not (s >= start and e <= end)
        ]
    if text.startswith("\ufeff"):
        text = text[1:]
        active_spans = [(s - 1, e - 1) for s, e in active_spans]
    cleaned = _normalize(text, active_spans)
    if cleaned == body:
        return CleanSourceResult(
            body=body,
            available=True,
            status="unchanged",
            note=_UNCHANGED_NOTE,
        )
    return CleanSourceResult(
        body=cleaned,
        available=True,
        status="cleaned",
        note=_CLEANED_NOTE,
    )


def _scan_protected(body: str) -> list[tuple[int, int]] | None:
    """Return protected spans, or None when a protected token never closes."""
    spans: list[tuple[int, int]] = []
    length = len(body)
    state = _NORMAL
    start = 0
    index = 0
    while index < length:
        char = body[index]
        if state == _NORMAL:
            if char == '"':
                if body.startswith('"""', index):
                    state = _TEXT_BLOCK
                    start = index
                    index += 3
                else:
                    state = _STRING
                    start = index
                    index += 1
            elif char == "'":
                state = _CHAR
                start = index
                index += 1
            elif char == "/" and body.startswith("//", index):
                state = _LINE_COMMENT
                start = index
                index += 2
            elif char == "/" and body.startswith("/*", index):
                state = _BLOCK_COMMENT
                start = index
                index += 2
            else:
                index += 1
        elif state == _STRING:
            if char == "\\":
                index += 2
            elif char == '"':
                index += 1
                spans.append((start, index))
                state = _NORMAL
            else:
                index += 1
        elif state == _CHAR:
            if char == "\\":
                index += 2
            elif char == "'":
                index += 1
                spans.append((start, index))
                state = _NORMAL
            else:
                index += 1
        elif state == _TEXT_BLOCK:
            if body.startswith('"""', index):
                index += 3
                spans.append((start, index))
                state = _NORMAL
            else:
                index += 1
        elif state == _LINE_COMMENT:
            if char == "\n":
                spans.append((start, index))
                state = _NORMAL
            index += 1
        else:  # _BLOCK_COMMENT
            if body.startswith("*/", index):
                index += 2
                spans.append((start, index))
                state = _NORMAL
            else:
                index += 1
    if state in _UNTERMINATED_STATES:
        return None
    if state == _LINE_COMMENT:
        spans.append((start, length))
    return spans


def _initial_banner(
    body: str,
    spans: list[tuple[int, int]],
    tool: str,
) -> tuple[int, int] | None:
    """Locate at most one initial decompiler banner before any declaration."""
    tool_key = str(tool or "").strip().casefold()
    if tool_key not in _BANNER_TOOLS:
        return None
    comment_index = None
    for position, (start, _end) in enumerate(spans):
        if body.startswith(("//", "/*"), start):
            comment_index = position
            break
    if comment_index is None:
        return None
    start, end = spans[comment_index]
    if body[:start].strip(_INITIAL_WHITESPACE) != "":
        return None
    first_text = body[start:end].casefold()
    if "decompiled" not in first_text or tool_key not in first_text:
        return None
    if body.startswith("/*", start):
        return start, end
    run_end = end
    position = comment_index + 1
    while position < len(spans):
        next_start, next_end = spans[position]
        if not body.startswith("//", next_start):
            break
        if body[run_end:next_start].strip(_INITIAL_WHITESPACE) != "":
            break
        run_end = next_end
        position += 1
    return start, run_end


def _normalize(text: str, spans: list[tuple[int, int]]) -> str:
    """Trim presentation-only whitespace outside strings and comments."""
    flags = bytearray(len(text))
    for start, end in spans:
        flags[start:end] = b"\x01" * (end - start)
    lines: list[tuple[int, int]] = []
    position = 0
    length = len(text)
    while position <= length:
        newline = text.find("\n", position)
        if newline == -1:
            if position < length:
                lines.append((position, length))
            break
        lines.append((position, newline))
        position = newline + 1
    span_index = 0
    processed: list[tuple[str, bool]] = []
    for line_start, line_end in lines:
        while span_index < len(spans) and spans[span_index][1] <= line_start:
            span_index += 1
        crossing = (
            span_index < len(spans) and spans[span_index][0] < line_start
        )
        protected = crossing
        if not protected and line_end > line_start:
            protected = flags[line_start:line_end].find(b"\x01") != -1
        content_end = line_end
        while (
            content_end > line_start
            and flags[content_end - 1] == 0
            and text[content_end - 1] in _EDGE_WHITESPACE
        ):
            content_end -= 1
        processed.append((text[line_start:content_end], protected))
    result: list[str] = []
    pending_blanks = 0
    started = False
    for content, protected in processed:
        if not protected and content == "":
            pending_blanks += 1
            continue
        if pending_blanks:
            if started:
                result.append("")
            pending_blanks = 0
        result.append(content)
        started = True
    if not result:
        return ""
    return "\n".join(result) + "\n"

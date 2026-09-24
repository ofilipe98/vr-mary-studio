from __future__ import annotations

import re
from urllib.parse import quote, unquote

from ..code_references import JavaCodeReference, parse_java_code_reference
from .text_rendering import fenced_blocks

CODE_REFERENCE_SCHEME: str = "vr-code"

_INLINE_CODE_RE = re.compile(r"(?<![`\\])(`+)([^`\n]+?)\1(?![`])")


def _inside_link_label(content: str, start: int) -> bool:
    return content.count("[", 0, start) > content.count("]", 0, start)


def encode_code_reference(reference: JavaCodeReference) -> str:
    encoded_canonical = quote(reference.canonical, safe=".")
    return f"{CODE_REFERENCE_SCHEME}:{encoded_canonical}"


def parse_code_reference(value: str) -> JavaCodeReference | None:
    if not value or not isinstance(value, str):
        return None
    prefix = f"{CODE_REFERENCE_SCHEME}:"
    if not value.startswith(prefix):
        return None
    payload = unquote(value[len(prefix) :])
    return parse_java_code_reference(payload)


def linkify_code_references(markdown: str) -> str:
    if not markdown:
        return ""
    result: list[str] = []
    for block in fenced_blocks(markdown):
        if block["kind"] == "code":
            result.append(block["raw"])
            continue

        content = block["content"]
        chunks: list[str] = []
        last_index = 0
        for match in _INLINE_CODE_RE.finditer(content):
            if match.group(1) != "`" or _inside_link_label(content, match.start()):
                continue

            raw_code = match.group(2)
            reference = parse_java_code_reference(raw_code)
            if reference is None:
                continue

            chunks.append(content[last_index : match.start()])
            encoded = encode_code_reference(reference)
            chunks.append(f"[{raw_code}]({encoded})")
            last_index = match.end()

        chunks.append(content[last_index:])
        result.append("".join(chunks))

    return "".join(result)

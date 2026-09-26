from __future__ import annotations

from dataclasses import dataclass
import re
import string

_ASCII_UPPERCASE = frozenset(string.ascii_uppercase)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class JavaCodeReference:
    raw: str
    canonical: str
    class_name: str
    qualified_class_name: str | None
    member_name: str | None


def parse_java_code_reference(value: str) -> JavaCodeReference | None:
    if not value or not isinstance(value, str):
        return None

    if any(c.isspace() for c in value):
        return None

    has_empty_parens = False
    clean_val = value
    if clean_val.endswith(")"):
        if not clean_val.endswith("()"):
            return None
        clean_val = clean_val[:-2]
        has_empty_parens = True

    if "(" in clean_val or ")" in clean_val:
        return None

    if "#" in clean_val:
        if clean_val.count("#") != 1:
            return None
        class_part, member_part = clean_val.split("#", 1)
        if not class_part or not member_part:
            return None
        if not _IDENTIFIER_RE.match(member_part):
            return None

        segments = class_part.split(".")
        for seg in segments:
            if not _IDENTIFIER_RE.match(seg):
                return None

        class_seg = segments[-1]
        if class_seg[0] not in _ASCII_UPPERCASE:
            return None

        for pkg_seg in segments[:-1]:
            if pkg_seg[0] in _ASCII_UPPERCASE:
                return None

        class_name = class_seg
        qualified_class_name = class_part if len(segments) > 1 else None
        member_name = member_part
        canonical = f"{class_part}.{member_name}"
        return JavaCodeReference(
            raw=value,
            canonical=canonical,
            class_name=class_name,
            qualified_class_name=qualified_class_name,
            member_name=member_name,
        )

    segments = clean_val.split(".")
    for seg in segments:
        if not _IDENTIFIER_RE.match(seg):
            return None

    if len(segments) < 2:
        return None

    if segments[0][0] in _ASCII_UPPERCASE:
        if len(segments) != 2:
            return None
        class_name = segments[0]
        member_name = segments[1]
        qualified_class_name = None
        canonical = f"{class_name}.{member_name}"
        return JavaCodeReference(
            raw=value,
            canonical=canonical,
            class_name=class_name,
            qualified_class_name=qualified_class_name,
            member_name=member_name,
        )

    class_idx = None
    for i, seg in enumerate(segments):
        if seg[0] in _ASCII_UPPERCASE:
            class_idx = i
            break

    if class_idx is None or class_idx == 0:
        return None

    for seg in segments[:class_idx]:
        if seg[0] in _ASCII_UPPERCASE:
            return None

    class_name = segments[class_idx]
    qualified_class_name = ".".join(segments[: class_idx + 1])
    remaining = segments[class_idx + 1 :]

    if len(remaining) == 0:
        if has_empty_parens:
            return None
        member_name = None
        canonical = qualified_class_name
    elif len(remaining) == 1:
        member_name = remaining[0]
        canonical = f"{qualified_class_name}.{member_name}"
    else:
        return None

    return JavaCodeReference(
        raw=value,
        canonical=canonical,
        class_name=class_name,
        qualified_class_name=qualified_class_name,
        member_name=member_name,
    )

"""File-reference detection for chat Markdown, mirroring t3code's file chips.

Inline code such as ``src/app.py`` or ``Makefile:12`` becomes a clickable
``vr-file:`` link; commands, identifiers, git refs and globs stay untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from .text_rendering import fenced_blocks

FILE_REFERENCE_SCHEME = "vr-file"

_KNOWN_EXTENSIONS = frozenset({
    "bash", "bat", "c", "cfg", "cmd", "conf", "cpp", "cs", "css", "csv",
    "dart", "env", "go", "gradle", "h", "hpp", "htm", "html", "ini", "java",
    "js", "json", "jsonc", "jsx", "kt", "kts", "less", "log", "md", "mdx",
    "mjs", "php", "properties", "ps1", "py", "pyw", "qml", "rb", "rs",
    "sass", "scss", "sh", "sql", "svelte", "swift", "toml", "ts", "tsv",
    "tsx", "txt", "vue", "xml", "yaml", "yml", "zsh",
})

_EXTENSIONLESS_NAMES = frozenset({
    ".dockerignore", ".editorconfig", ".gitattributes", ".gitignore",
    ".npmrc", "brewfile", "dockerfile", "gemfile", "jenkinsfile", "justfile",
    "makefile", "procfile", "rakefile", "vagrantfile",
})

_LINE_SUFFIX_RE = re.compile(
    r"(?::(?P<line>\d+)(?::(?P<column>\d+))?"
    r"|#L(?P<hash_line>\d+)(?::C(?P<hash_column>\d+)|C(?P<hash_column_plain>\d+))?)$"
)

_INLINE_CODE_RE = re.compile(r"(?<![`\\])(`+)([^`\n]+?)\1(?![`])")

_FORBIDDEN_RE = re.compile(r"[\s*?\[\]{}|<>;\"'=`]")

_HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")

_GIT_RANGE_RE = re.compile(r"^[A-Za-z0-9._/-]+\.\.[A-Za-z0-9._/-]+$")

_POSITION_RE = re.compile(r"L(\d+)(?::C(\d+))?")


@dataclass(frozen=True)
class FileLinkMeta:
    """A validated file reference extracted from Markdown."""

    path: str
    basename: str
    line: int | None = None
    column: int | None = None


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _parent_parts(path: str) -> list[str]:
    return [part for part in path.split("/")[:-1] if part not in ("", ".")]


def _split_position(value: str) -> tuple[str, int | None, int | None]:
    match = _LINE_SUFFIX_RE.search(value)
    if match is None:
        return value, None, None
    line = match.group("line") or match.group("hash_line")
    column = (
        match.group("column")
        or match.group("hash_column")
        or match.group("hash_column_plain")
    )
    return (
        value[:match.start()],
        int(line, 10) if line else None,
        int(column, 10) if column else None,
    )


def _local_path_from_url(value: str) -> str:
    local = unquote(value[7:])
    if re.match(r"^/[A-Za-z]:/", local):
        return local[1:]
    return local


def _meta_from_path(
    path: str, line: int | None, column: int | None
) -> FileLinkMeta | None:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized or normalized.endswith("/") or normalized.startswith("-"):
        return None
    if _FORBIDDEN_RE.search(normalized) or _GIT_RANGE_RE.fullmatch(normalized):
        return None
    basename = _basename(normalized)
    if not basename or basename in (".", ".."):
        return None
    extension = basename.rsplit(".", 1)[-1].casefold() if "." in basename else ""
    has_separator = "/" in normalized
    allowlisted = basename.casefold() in _EXTENSIONLESS_NAMES
    # t3code parity: require a path separator, or a line suffix with a known
    # extension/allowlisted name. Bare names such as `AGENTS.md` stay code.
    if not has_separator and not (
        line is not None and (extension in _KNOWN_EXTENSIONS or allowlisted)
    ):
        return None
    if has_separator and not normalized.startswith(("./", "../")):
        first = normalized.split("/", 1)[0]
        if _HOST_RE.fullmatch(first):
            return None
    # POSIX absolute paths need an explicit file shape to avoid app routes
    # such as /chat/settings being treated as files.
    if (
        normalized.startswith("/")
        and not normalized.startswith("//")
        and line is None
        and extension not in _KNOWN_EXTENSIONS
        and not allowlisted
    ):
        return None
    return FileLinkMeta(path=normalized, basename=basename, line=line, column=column)


def resolve_inline_code_file_link(text: str) -> FileLinkMeta | None:
    """Resolve one inline-code span, rejecting commands and identifiers."""
    value = str(text or "").strip()
    if not value or len(value) > 400:
        return None
    if value.casefold().startswith("file://"):
        value = _local_path_from_url(value)
    value = value.strip("\"'")
    if not value or "://" in value or any(character.isspace() for character in value):
        return None
    path, line, column = _split_position(value)
    return _meta_from_path(path, line, column)


def resolve_markdown_file_link(href: str) -> FileLinkMeta | None:
    """Resolve a Markdown link destination that points at a local file."""
    value = unquote(str(href or "").strip())
    if not value:
        return None
    if value.casefold().startswith(FILE_REFERENCE_SCHEME + ":"):
        parsed = parse_file_reference(value)
        if parsed is None:
            return None
        path, line, column = parsed
        return _meta_from_path(path, line, column)
    if value.casefold().startswith("file://"):
        path, line, column = _split_position(_local_path_from_url(value))
        return _meta_from_path(path, line, column)
    if "://" in value or value.startswith("#") or _HOST_RE.fullmatch(value):
        return None
    path, line, column = _split_position(value)
    return _meta_from_path(path, line, column)


def build_parent_suffixes(paths: list[str]) -> dict[str, str]:
    """Minimal parent suffix per path, only where basenames collide."""
    normalized = [str(path or "").replace("\\", "/") for path in paths]
    groups: dict[str, list[str]] = {}
    for path in normalized:
        groups.setdefault(_basename(path).casefold(), []).append(path)
    suffixes = {path: "" for path in normalized}
    for members in groups.values():
        if len(members) < 2:
            continue
        parents = {path: _parent_parts(path) for path in members}
        for path in members:
            parts = parents[path]
            for depth in range(1, len(parts) + 1):
                suffix = "/".join(parts[-depth:])
                matches = sum(
                    1
                    for other in members
                    if "/".join(parents[other][-depth:]) == suffix
                )
                if matches == 1:
                    suffixes[path] = suffix
                    break
    return suffixes


def file_link_label(meta: FileLinkMeta, parent_suffix: str = "") -> str:
    parts = [meta.basename]
    if parent_suffix:
        parts.append(parent_suffix)
    if meta.line:
        parts.append(f"L{meta.line}" + (f":C{meta.column}" if meta.column else ""))
    return " · ".join(parts)


def encode_file_reference(meta: FileLinkMeta) -> str:
    reference = FILE_REFERENCE_SCHEME + ":" + quote(meta.path, safe="/:")
    if meta.line:
        reference += f"#L{meta.line}"
        if meta.column:
            reference += f":C{meta.column}"
    return reference


def parse_file_reference(value: str) -> tuple[str, int | None, int | None] | None:
    text = str(value or "").strip()
    if not text.casefold().startswith(FILE_REFERENCE_SCHEME + ":"):
        return None
    payload = text[len(FILE_REFERENCE_SCHEME) + 1:]
    position = ""
    if "#" in payload:
        payload, position = payload.split("#", 1)
    path = unquote(payload).strip()
    if not path:
        return None
    line = column = None
    match = _POSITION_RE.fullmatch(position)
    if match:
        line = int(match.group(1), 10)
        column = int(match.group(2), 10) if match.group(2) else None
    return path, line, column


def _inside_link_label(content: str, start: int) -> bool:
    return content.count("[", 0, start) > content.count("]", 0, start)


def linkify_file_references(markdown: str) -> str:
    """Rewrite inline-code file paths as ``vr-file:`` Markdown links."""
    text = str(markdown or "")
    if "`" not in text:
        return text
    blocks = fenced_blocks(text)
    metas: dict[tuple[int, int], FileLinkMeta] = {}
    for position, block in enumerate(blocks):
        if block["kind"] != "text":
            continue
        content = block["content"]
        for match in _INLINE_CODE_RE.finditer(content):
            if match.group(1) != "`" or _inside_link_label(content, match.start()):
                continue
            meta = resolve_inline_code_file_link(match.group(2))
            if meta is not None:
                metas[(position, match.start())] = meta
    if not metas:
        return text
    suffixes = build_parent_suffixes([meta.path for meta in metas.values()])
    result = []
    for position, block in enumerate(blocks):
        if block["kind"] == "code":
            result.append(block["raw"])
            continue
        content = block["content"]

        def replace(match, position=position):
            if match.group(1) != "`":
                return match.group(0)
            meta = metas.get((position, match.start()))
            if meta is None:
                return match.group(0)
            label = file_link_label(meta, suffixes.get(meta.path, ""))
            return f"[{label}]({encode_file_reference(meta)})"

        result.append(_INLINE_CODE_RE.sub(replace, content))
    return "".join(result)


__all__ = [
    "FILE_REFERENCE_SCHEME",
    "FileLinkMeta",
    "build_parent_suffixes",
    "encode_file_reference",
    "file_link_label",
    "linkify_file_references",
    "parse_file_reference",
    "resolve_inline_code_file_link",
    "resolve_markdown_file_link",
]

from __future__ import annotations

import re
from pathlib import Path


PORTABLE_ANCHORS = {
    ".codex",
    "agentes",
    "assets",
    "conhecimento",
    "indice",
    "tools",
    "trabalhovr",
    # Compatibility anchor for paths persisted by older installations.
    "trabalhomary",
    "videos",
}


def to_portable_path(root: Path, value: str | Path | None) -> str:
    """Store VR-owned paths relative to the project root.

    Stale absolute paths from an older machine are recovered from the first
    known VR directory (for example ``conhecimento`` or ``assets``).
    Paths outside the VR project are preserved verbatim.
    """

    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""

    root = root.resolve()
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve(strict=False).relative_to(root).as_posix()
        except ValueError:
            anchored = _anchored_relative(raw)
            return anchored or raw

    normalized = raw.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def resolve_portable_path(root: Path, value: str | Path | None) -> Path:
    """Resolve a portable path and repair a stale absolute VR path."""

    root = root.resolve()
    raw = str(value or "").strip()
    if not raw:
        return root
    candidate = Path(raw)
    if not candidate.is_absolute():
        relative = Path(*[part for part in re.split(r"[\\/]+", raw) if part])
        return (root / relative).resolve(strict=False)
    if candidate.exists():
        return candidate.resolve()
    anchored = _anchored_relative(raw)
    if anchored:
        return (root / Path(anchored)).resolve(strict=False)
    return candidate.resolve(strict=False)


def _anchored_relative(value: str) -> str:
    parts = [part for part in re.split(r"[\\/]+", value) if part]
    for index, part in enumerate(parts):
        if part.casefold() in PORTABLE_ANCHORS:
            return "/".join(parts[index:])
    return ""

"""Paged access to the selected project's files, without a global file index."""
from __future__ import annotations

import os
from pathlib import Path


def _files(root: Path):
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if not name.startswith(".") and name not in {"__pycache__", "node_modules"}
                            and (Path(directory) / name).resolve().is_relative_to(root))
        for name in sorted(files):
            path = Path(directory) / name
            if name.startswith(".") or not path.resolve().is_relative_to(root):
                continue
            yield path


def list_sources(workspace: str, *, cursor: int = 0, limit: int = 20, query: str = "") -> dict:
    if not workspace:
        return {"state": "scope_required", "results": [], "has_more": False}
    root = Path(workspace).resolve()
    results = []
    skipped = 0
    terms = query.casefold().split()
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        if terms:
            with path.open("rb") as stream:
                raw = stream.read(65536)
            text = relative + "\n" + (raw.decode("utf-8", errors="replace") if b"\0" not in raw else "")
            if not any(term in text.casefold() for term in terms):
                continue
        if skipped < cursor:
            skipped += 1
            continue
        results.append({"reference": "project:" + relative, "evidence_id": "project:" + relative,
                        "source": "project", "source_id": relative, "title": relative,
                        "excerpt": "Arquivo do projeto selecionado; use vr_read para consultar."})
        if len(results) > limit:
            break
    more = len(results) > limit
    return {"state": "available", "results": results[:limit], "has_more": more,
            "next_cursor": cursor + limit if more else None,
            "search_scope": "names_and_first_64KiB" if query else "inventory"}


def read_source(workspace: str, reference: str, *, cursor: int = 0, limit: int = 4000) -> dict:
    if not workspace:
        return {"state": "scope_required", "error": "Nenhum projeto selecionado."}
    root = Path(workspace).resolve()
    relative = reference.removeprefix("project:")
    path = (root / relative).resolve()
    if (not path.is_relative_to(root) or not path.is_file()
            or any(part.startswith(".") for part in Path(relative).parts)):
        return {"state": "no_results", "error": "Arquivo fora das fontes do projeto."}
    # Text streams advance in characters. Skip incrementally instead of loading large files.
    with path.open("rb") as stream:
        if b"\0" in stream.read(8192):
            return {"state": "unsupported", "error": "Arquivo binario; utilize um extrator compativel."}
    with path.open(encoding="utf-8", errors="replace") as stream:
        remaining = cursor
        while remaining:
            chunk = stream.read(min(8192, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        content = stream.read(limit + 1)
    more = len(content) > limit
    return {"state": "available", "reference": reference, "evidence_id": reference,
            "source": "project", "source_id": relative, "title": relative,
            "content": content[:limit], "cursor": cursor, "has_more": more,
            "next_cursor": cursor + limit if more else None}

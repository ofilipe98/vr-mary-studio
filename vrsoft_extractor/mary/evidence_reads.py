"""Register actual read results against trusted local source identities."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path


def capture_read(event, root: Path, candidates, *, max_chars=24000):
    if event.kind != "tool_event":
        return None
    part = event.payload.get("part", {})
    state = part.get("state", {})
    if part.get("tool") != "read" or state.get("status") != "completed":
        return None
    args = state.get("input", {})
    name = args.get("filePath")
    if not isinstance(name, str):
        return None
    path = Path(name)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root.resolve()):
        return None
    original = next((c for c in candidates if c.local_path
                     and (root / c.local_path).resolve() == path), None)
    if original is None:
        original = _indexed_source(path, root, candidates)
    if original is None:
        return None
    try:
        if path.stat().st_size > 2_000_000:
            return None
        raw = path.read_bytes()
        lines = raw.decode("utf-8-sig").splitlines()
        start = max(1, int(args.get("offset", 1)))
        count = max(1, min(500, int(args.get("limit", 2000))))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    excerpt_lines = []
    used = 0
    for line in lines[start - 1:start - 1 + count]:
        if used + len(line) + 1 > max_chars:
            break
        excerpt_lines.append(line)
        used += len(line) + 1
    if not excerpt_lines:
        return None
    digest = hashlib.sha256(raw).hexdigest()
    expected_hash = original.entities.get("source_sha256", ())
    normalized_digest = hashlib.sha256(raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()
    if expected_hash and normalized_digest not in expected_hash:
        return None
    end = start + len(excerpt_lines) - 1
    identity = hashlib.sha256(f"{original.evidence_id}:{digest}:{start}:{end}".encode()).hexdigest()[:24]
    return replace(original, evidence_id=f"read:{identity}",
                   excerpt="\n".join(excerpt_lines),
                   title=f"{original.title} · leitura linhas {start}-{end} · SHA-256 {digest}",
                   heading=f"{original.heading} · linhas {start}-{end}")


def _indexed_source(path, root, candidates):
    """Allow additional indexed files only from the already selected releases."""
    seeds = [c for c in candidates if c.source == "code" and c.source_id]
    database = root / "indice" / "codigo" / "processing.sqlite"
    if not seeds or not database.is_file():
        return None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            keys = [c.source_id for c in seeds]
            rows = connection.execute(
                "SELECT source_key, qualified_name, output_reference, source_relative_path, source_sha256 "
                "FROM code_sources WHERE release_id IN (SELECT release_id FROM code_sources WHERE source_key IN ("
                + ",".join("?" for _ in keys) + ")) AND source_relative_path LIKE ?",
                [*keys, "%" + path.name],
            ).fetchall()
            for row in rows:
                candidate_path = (root / row["output_reference"] / row["source_relative_path"]).resolve()
                if candidate_path == path:
                    return replace(seeds[0], evidence_id="code:" + row["source_key"],
                                   source_id=row["source_key"], title=row["qualified_name"],
                                   heading=row["qualified_name"], local_path=path.relative_to(root).as_posix(),
                                   entities={"source_sha256": (row["source_sha256"],)}, excerpt="")
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return None
    return None

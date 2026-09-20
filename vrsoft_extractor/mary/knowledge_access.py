"""Immutable scope and bounded results shared by native and MCP tools."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from .models import EvidenceCandidate


def create_scope() -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vr-access.json", delete=False, encoding="utf-8") as stream:
        json.dump({"active": False}, stream)
        return stream.name


def publish_scope(path: str, scope: dict) -> None:
    target = Path(path)
    staging = target.with_suffix(".tmp")
    staging.write_text(json.dumps({"active": True, "scope": scope}), encoding="utf-8")
    staging.replace(target)


def load_scope(path: str) -> dict:
    if not path:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not value.get("active"):
        raise ValueError("O turno foi encerrado ou o contexto ainda nao esta pronto.")
    return value["scope"]


def close_scope(path: str) -> None:
    if path:
        for target in (Path(path), Path(path + ".events"), Path(path + ".claude.json")):
            target.unlink(missing_ok=True)


def invalidate_scope(path: str) -> None:
    if path and Path(path).exists():
        Path(path).write_text('{"active": false}', encoding="utf-8")


def bounded_candidates(candidates, max_chars: int = 32000) -> tuple[EvidenceCandidate, ...]:
    """Bound serialized evidence, retaining representation of each source lane."""
    from dataclasses import replace
    lanes = {}
    for candidate in candidates:
        lanes.setdefault(candidate.source, []).append(candidate)
    ordered = [lane[i] for i in range(max((len(lane) for lane in lanes.values()), default=0))
               for lane in lanes.values() if i < len(lane)]
    result, seen, used = [], set(), 0
    for candidate in ordered:
        if candidate.evidence_id in seen:
            continue
        compact = replace(candidate, excerpt=candidate.excerpt[:2000])
        size = len(json.dumps(compact.to_dict(), ensure_ascii=False)) + 2
        if used + size > max_chars:
            continue
        result.append(compact)
        seen.add(compact.evidence_id)
        used += size
    return tuple(result)


def mcp_command(root: Path, scope_path: str = "", monitor_session_id: str = "") -> list[str]:
    command = [sys.executable]
    if getattr(sys, "frozen", False):
        command += ["--knowledge-mcp"]
    else:
        # Absolute bootstrap works from a project outside the source checkout.
        command += [str(Path(__file__).with_name("mcp_server.py"))]
    command += ["--root", str(root.resolve())]
    if scope_path:
        command += ["--context", scope_path]
    if monitor_session_id:
        command += ["--monitor-session", monitor_session_id]
    return command


def result_candidates(payload: dict) -> list[EvidenceCandidate]:
    items = payload.get("results", [])
    if payload.get("content") and not payload.get("error"):
        items = [payload]
    candidates = []
    for item in items:
        reference = str(item.get("evidence_id") or item.get("reference") or "")
        if not reference or not item.get("source"):
            continue
        candidates.append(EvidenceCandidate(
            evidence_id=reference, source=item["source"],
            source_id=str(item.get("source_id") or reference),
            document_id=int(item.get("document_id") or 0), chunk_id=int(item.get("chunk_id") or 0),
            title=str(item.get("title") or reference), heading=str(item.get("heading") or ""),
            content_type=str(item.get("content_type") or "text"), module=str(item.get("module") or ""),
            product=str(item.get("product") or ""), excerpt=str(item.get("content") or item.get("excerpt") or "")[:2000],
            url=str(item.get("url") or ""), local_path=str(item.get("local_path") or ""),
            confidence=float(item.get("confidence") or 0.7),
            entities={**{key: tuple(value) for key, value in (item.get("entities") or {}).items()}, **{key: (str(item[key]),) for key in (
                "context_id", "release_id", "release_manifest_sha256", "source_sha256",
                "jar_relative_path", "line_start", "line_end") if key in item}},
        ))
    return candidates

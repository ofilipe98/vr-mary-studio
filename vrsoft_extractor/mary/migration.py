from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import MarySettings
from .models import utc_now


SAFE_AGENT_DIRS = {
    "Atlas",
    "Caixa",
    "Cora",
    "Fisco",
    "MentorVR",
    "Padronizador",
    "SchemaVR",
    "Yao",
}
SOURCE_AGENT_FILES = {"VRWiki/AGENTS.md", "KB/AGENTS.md"}
ROOT_ALLOWLIST = {
    "AGENTS.md",
    "produtos_filas.md",
    "prompt_avaliadorvr.md",
    "prompt_vr_agent_codex.md",
}
BLOCKED_PARTS = {
    "VRWiki",
    "KB",
    "output",
    "tmp",
    ".git",
    ".codex",
    ".agents",
    "__pycache__",
    "hf_cache",
    "asr_pydeps",
    "node_modules",
    "artefatos",
}
BLOCKED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".exe",
    ".dll",
    ".bin",
    ".onnx",
    ".mp4",
    ".wav",
    ".srt",
}
MOJIBAKE_MARKERS = ("Ã£", "Ã§", "Ã©", "â€™", "�")


@dataclass
class MigrationItem:
    source: str
    destination: str
    sha256: str
    reason: str
    status: str


def build_manifest(settings: MarySettings) -> list[MigrationItem]:
    items: list[MigrationItem] = []
    if not settings.old_root.exists():
        return items
    candidates: list[tuple[Path, str]] = []
    for name in ROOT_ALLOWLIST:
        path = settings.old_root / name
        if path.is_file():
            candidates.append((path, "arquivo funcional da raiz"))
    for relative_name in SOURCE_AGENT_FILES:
        path = settings.old_root / Path(relative_name)
        if path.is_file():
            candidates.append((path, "prompt operacional da fonte, sem conteúdo extraído"))
    for directory_name in SAFE_AGENT_DIRS:
        directory = settings.old_root / directory_name
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            if any(part in BLOCKED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() in BLOCKED_SUFFIXES:
                continue
            if path.name == "AGENTS.md" or directory_name == "SchemaVR":
                candidates.append((path, "instrução de agente ou schema validado"))
    tests_dir = settings.old_root / "tests"
    if tests_dir.exists():
        for path in tests_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".py", ".json", ".md"}:
                candidates.append((path, "teste funcional legado"))
    candidates.extend(_validated_capsules(settings.old_root))

    seen: set[Path] = set()
    for source, reason in candidates:
        if source in seen:
            continue
        seen.add(source)
        relative = source.relative_to(settings.old_root)
        destination = settings.root / "agentes" / relative
        status = "ready"
        try:
            data = source.read_bytes()
            if source.suffix.lower() in {".md", ".txt", ".json", ".py"}:
                text = data.decode("utf-8")
                if any(marker in text for marker in MOJIBAKE_MARKERS):
                    status = "rejected_mojibake"
        except (UnicodeDecodeError, OSError):
            data = source.read_bytes()
            status = "rejected_encoding"
        items.append(
            MigrationItem(
                source=str(source),
                destination=str(destination),
                sha256=hashlib.sha256(data).hexdigest(),
                reason=reason,
                status=status,
            )
        )
    return items


def migrate(settings: MarySettings) -> dict[str, int]:
    items = build_manifest(settings)
    settings.root.mkdir(parents=True, exist_ok=True)
    copied = 0
    rejected = 0
    for item in items:
        if item.status != "ready":
            rejected += 1
            continue
        source = Path(item.source)
        destination = Path(item.destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        _rewrite_agent_references(destination)
        item.status = "copied"
        copied += 1

    old_agents = settings.root / "agentes" / "AGENTS.md"
    root_agents = settings.root / "AGENTS.md"
    if old_agents.exists():
        shutil.copy2(old_agents, root_agents)
    manifest = {
        "source_root": str(settings.old_root),
        "destination_root": str(settings.root),
        "created_at": utc_now(),
        "copied": copied,
        "rejected": rejected,
        "items": [asdict(item) for item in items],
    }
    (settings.root / "migration_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"copied": copied, "rejected": rejected, "total": len(items)}


def _validated_capsules(old_root: Path) -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    base = old_root / "ConhecimentoMary"
    if not base.exists():
        return result
    for manifest in base.rglob("*.json"):
        if any(part in BLOCKED_PARTS for part in manifest.parts):
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        status = str(
            payload.get("status")
            or payload.get("validation_status")
            or payload.get("estado")
            or ""
        ).lower()
        if status not in {"validado", "validated", "approved", "aprovado"}:
            continue
        for path in manifest.parent.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in {".md", ".json", ".txt"}
                and not any(part in BLOCKED_PARTS for part in path.parts)
            ):
                result.append((path, "cápsula explicitamente validada"))
    return result


def _rewrite_agent_references(path: Path) -> None:
    if path.suffix.lower() not in {".md", ".txt"}:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    names = sorted(SAFE_AGENT_DIRS | {"VRWiki", "KB"}, key=len, reverse=True)
    for name in names:
        text = text.replace(f"`{name}/", f"`agentes/{name}/")
        text = text.replace(f" {name}/AGENTS.md", f" agentes/{name}/AGENTS.md")
    text = text.replace("`produtos_filas.md`", "`agentes/produtos_filas.md`")
    path.write_text(text, encoding="utf-8")

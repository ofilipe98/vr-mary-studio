from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import MaryDatabase
from .indexer import export_catalog
from .portable_project import ensure_portable_project, write_portable_manifest


EXCLUDED_TOP_LEVEL = {".state", ".trash", "downloads", "logs"}
EXCLUDED_NAMES = {".env", "thumbs.db", "desktop.ini"}
EXCLUDED_SUFFIXES = {".sqlite-shm", ".sqlite-wal", ".tmp", ".log"}
VIDEO_SUFFIXES = {
    ".avi",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".wav",
    ".webm",
}
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".toml", ".txt", ".yaml", ".yml"}
ABSOLUTE_MARY_PATH = re.compile(
    r"(?i)[a-z]:[\\/](?:[^\\/\r\n]+[\\/])*"
    r"(\.codex|agentes|assets|conhecimento|indice|tools|TrabalhoMary|videos)[\\/]"
)
RELATIVE_MARY_PATH = re.compile(
    r"(?i)(\.codex|agentes|assets|conhecimento|indice|tools|TrabalhoMary|videos)"
    r"[\\/][^\s<>\"')\]]+"
)


@dataclass(frozen=True)
class PortableExportResult:
    destination: Path
    files: int
    bytes: int
    excluded_files: int
    manifest: Path


def audit_portable_project(root: Path) -> dict[str, object]:
    root = root.resolve()
    required = (
        "AGENTS.md",
        ".codex/config.toml",
        "tools/mary-search.ps1",
        "indice/catalogo.jsonl",
        "indice/conhecimento.sqlite",
    )
    missing = [relative for relative in required if not (root / relative).is_file()]
    sensitive: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = [part.casefold() for part in relative.parts]
        if relative.name.casefold() == ".env" or ".state" in parts:
            sensitive.append(relative.as_posix())
        if relative.suffix.casefold() in {".pem", ".key"}:
            sensitive.append(relative.as_posix())

    absolute_database_paths = 0
    database_path = root / "indice" / "conhecimento.sqlite"
    if database_path.is_file():
        with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True) as connection:
            checks = (
                ("documents", ("local_path", "assets_json")),
                ("conversations", ("workspace", "original_workspace")),
                ("artifacts", ("path",)),
            )
            for table, columns in checks:
                query = " OR ".join(
                    f"instr({column}, ':\\\\') > 0 OR instr({column}, ':/') > 0"
                    for column in columns
                )
                absolute_database_paths += int(
                    connection.execute(
                        f"SELECT count(*) FROM {table} WHERE {query}"
                    ).fetchone()[0]
                )

    catalog_path = root / "indice" / "catalogo.jsonl"
    catalog_has_absolute_paths = False
    if catalog_path.is_file():
        catalog_has_absolute_paths = bool(
            ABSOLUTE_MARY_PATH.search(catalog_path.read_text(encoding="utf-8"))
        )
    issues = (
        len(missing)
        + len(sensitive)
        + absolute_database_paths
        + int(catalog_has_absolute_paths)
    )
    return {
        "root": str(root),
        "ready": issues == 0,
        "missing": missing,
        "sensitive_files": sensitive,
        "absolute_database_paths": absolute_database_paths,
        "catalog_has_absolute_paths": catalog_has_absolute_paths,
    }


def export_portable_project(source: Path, destination: Path) -> PortableExportResult:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination or source in destination.parents:
        raise ValueError("O destino portátil deve ficar fora da base de origem.")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"O destino não está vazio: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    database_relative = Path("indice") / "conhecimento.sqlite"
    files = 0
    bytes_total = 0
    excluded = 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if relative == database_relative or _excluded(relative):
            excluded += 1
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.casefold() in TEXT_SUFFIXES:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeError:
                shutil.copy2(path, target)
            else:
                target.write_text(_portable_text(content), encoding="utf-8", newline="\n")
        else:
            shutil.copy2(path, target)
        files += 1
        bytes_total += target.stat().st_size

    source_database = source / database_relative
    if source_database.is_file():
        target_database = destination / database_relative
        target_database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source_database) as source_connection:
            with sqlite3.connect(target_database) as target_connection:
                source_connection.backup(target_connection)
        portable_database = MaryDatabase(
            target_database,
            root=destination,
            backup_portable_migration=False,
        )
        export_catalog(portable_database, destination / "indice")
        files += 1
        bytes_total += target_database.stat().st_size

    ensure_portable_project(destination)
    _audit_sensitive_files(destination)
    manifest = write_portable_manifest(destination)
    return PortableExportResult(destination, files, bytes_total, excluded, manifest)


def _excluded(relative: Path) -> bool:
    parts = [part.casefold() for part in relative.parts]
    if not parts:
        return False
    if parts[0] in EXCLUDED_TOP_LEVEL or "__pycache__" in parts:
        return True
    name = relative.name.casefold()
    if name in EXCLUDED_NAMES:
        return True
    if any(name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return True
    return parts[0] == "videos" and relative.suffix.casefold() in VIDEO_SUFFIXES


def _portable_text(content: str) -> str:
    content = ABSOLUTE_MARY_PATH.sub(lambda match: f"{match.group(1)}/", content)
    return RELATIVE_MARY_PATH.sub(lambda match: match.group(0).replace("\\", "/"), content)


def _audit_sensitive_files(root: Path) -> None:
    forbidden = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        lowered = [part.casefold() for part in relative.parts]
        if relative.name.casefold() == ".env" or ".state" in lowered:
            forbidden.append(relative.as_posix())
        if relative.suffix.casefold() in {".pem", ".key"}:
            forbidden.append(relative.as_posix())
    if forbidden:
        raise RuntimeError(
            "Arquivos sensíveis encontrados no pacote: " + ", ".join(forbidden[:10])
        )

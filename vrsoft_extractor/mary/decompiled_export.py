"""Read-only export of indexed decompiled application sources.

The integrity contract is the indexed text encoded as UTF-8.  A physical
source file is reused only when its byte hash matches ``source_sha256``;
otherwise the indexed body is authoritative.  This intentionally permits a
CRLF physical file to export as the indexed LF text rather than changing the
meaning of the index hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from .apps_catalog import AppsCatalogStore

LOGGER = logging.getLogger(__name__)
SUPPORTED_SOURCE_SUFFIXES = frozenset({".java", ".kt"})
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _safe_export_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-") or fallback
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"{cleaned}-export"
    return cleaned[:100].rstrip(" .") or fallback


def _relative_source_path(value: str) -> Path:
    raw = str(value or "").replace("\\", "/")
    relative = PurePosixPath(raw)
    if (not raw or relative.is_absolute() or PureWindowsPath(raw).is_absolute()
            or ".." in relative.parts):
        raise ValueError("O índice contém um caminho de fonte inválido.")
    for component in relative.parts:
        if (component.endswith((".", " "))
                or any(char in component for char in '<>:"|?*')
                or any(ord(char) < 32 for char in component)):
            raise ValueError(
                "O índice contém um caminho incompatível com Windows: "
                f"{raw}"
            )
        if component.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
            raise ValueError(
                "O índice contém um caminho incompatível com Windows: "
                f"{raw}"
            )
    path = Path(*relative.parts)
    if path.suffix.casefold() not in SUPPORTED_SOURCE_SUFFIXES:
        raise ValueError("O índice contém um tipo de fonte não suportado.")
    return path


def _require_within(path: Path, root: Path, message: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(message) from exc
    return resolved


def _available_destination(parent: Path, base_name: str) -> Path:
    candidate = parent / base_name
    number = 2
    while candidate.exists():
        candidate = parent / f"{base_name}-{number}"
        number += 1
    return candidate


def export_decompiled_source(
    workspace: str | Path,
    destination_parent: str | Path,
    *,
    application_id: str,
    version: str,
    variant_id: str,
    origin_id: str,
    apps_store: AppsCatalogStore | None = None,
) -> dict[str, Any]:
    """Export exactly one catalog application/version/variant/origin selection."""
    workspace_root = Path(workspace).resolve(strict=True)
    parent = Path(destination_parent).resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("A pasta de destino selecionada não existe.")

    store = apps_store or AppsCatalogStore(root=workspace_root)
    catalog = store.load_catalog()
    app = catalog.get("applications", {}).get(application_id)
    if not app:
        raise ValueError("O aplicativo selecionado não foi encontrado no catálogo.")
    variant = app.get("versions", {}).get(version, {}).get("variants", {}).get(variant_id)
    if not variant:
        raise ValueError("A versão ou variante selecionada não foi encontrada no catálogo.")
    origin = next(
        (item for item in variant.get("origin_packages", []) if item.get("package_id") == origin_id),
        None,
    )
    if not origin:
        raise ValueError("A origem selecionada não pertence à versão escolhida.")

    artifact_sha256 = str(variant.get("sha256") or "")
    jar_relative_path = str(origin.get("relative_path") or variant.get("relative_path") or "")
    database = workspace_root / "indice" / "codigo" / "processing.sqlite"
    if not database.is_file():
        raise ValueError("O índice de código não está disponível.")

    app_name = str(app.get("name") or application_id)
    base_name = (
        f"{_safe_export_component(app_name, 'Aplicativo')}-"
        f"{_safe_export_component(version, 'versao')}-decompiled"
    )
    destination = _available_destination(parent, base_name)
    staging = parent / f".{destination.name}.tmp-{uuid4().hex}"
    file_count = 0
    total_bytes = 0
    exported_paths: dict[str, str] = {}
    exported_spellings: dict[str, str] = {}
    try:
        staging.mkdir()
        staging_root = staging.resolve(strict=True)
        uri = f"{database.as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT output_reference, source_relative_path, source_sha256, body
                     FROM code_sources
                    WHERE release_id = ? AND artifact_sha256 = ? AND jar_relative_path = ?
                    ORDER BY source_relative_path, id""",
                (origin_id, artifact_sha256, jar_relative_path),
            )
            found_source = False
            for row in rows:
                found_source = True
                output_raw = str(row["output_reference"] or "").replace("\\", "/")
                output_reference = PurePosixPath(output_raw)
                if (output_raw and (output_reference.is_absolute()
                        or PureWindowsPath(output_raw).is_absolute()
                        or ".." in output_reference.parts)):
                    raise ValueError("O índice contém uma referência de saída inválida.")
                relative = _relative_source_path(row["source_relative_path"])
                expected_hash = str(row["source_sha256"] or "").strip().casefold()
                content: bytes | None = None
                if output_raw:
                    source = _require_within(
                        workspace_root.joinpath(*output_reference.parts, relative),
                        workspace_root,
                        "O índice referencia um arquivo fora do workspace.",
                    )
                    if source.is_file():
                        physical_content = source.read_bytes()
                        if hashlib.sha256(physical_content).hexdigest() == expected_hash:
                            content = physical_content
                        else:
                            physical_content = None
                if content is None and row["body"] is not None:
                    body_content = str(row["body"]).encode("utf-8")
                    if hashlib.sha256(body_content).hexdigest() == expected_hash:
                        content = body_content
                if content is None:
                    raise ValueError(
                        "A fonte indexada foi alterada ou está inconsistente: "
                        f"{relative.as_posix()}"
                    )

                content_hash = hashlib.sha256(content).hexdigest()
                key = relative.as_posix().casefold()
                previous_hash = exported_paths.get(key)
                if previous_hash is not None:
                    previous_spelling = exported_spellings[key]
                    if previous_spelling != relative.as_posix():
                        raise ValueError(
                            "O índice contém caminhos incompatíveis com Windows: "
                            f"{previous_spelling} / {relative.as_posix()}"
                        )
                    previous_content = (staging_root / relative).read_bytes()
                    if previous_hash != content_hash or previous_content != content:
                        raise ValueError(
                            f"O índice contém fontes conflitantes para: {relative.as_posix()}"
                        )
                    continue

                target = _require_within(
                    staging_root / relative,
                    staging_root,
                    "O caminho de destino do fonte é inválido.",
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                exported_paths[key] = content_hash
                exported_spellings[key] = relative.as_posix()
                file_count += 1
                total_bytes += len(content)

            if not found_source:
                raise ValueError("Nenhum código decompilado disponível para esta versão e origem.")

        manifest = {
            "schema_version": 1,
            "application": app_name,
            "application_id": application_id,
            "version": version,
            "variant_id": variant_id,
            "release_id": origin_id,
            "origin_id": origin_id,
            "artifact_sha256": artifact_sha256,
            "jar_relative_path": jar_relative_path,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "file_count": file_count,
            "total_bytes": total_bytes,
        }
        (staging / "vrstudio-export.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging.replace(destination)
    except Exception:
        LOGGER.exception("Failed to export decompiled sources for %s %s", application_id, version)
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "success": True,
        "destination": str(destination),
        "file_count": file_count,
        "total_bytes": total_bytes,
    }

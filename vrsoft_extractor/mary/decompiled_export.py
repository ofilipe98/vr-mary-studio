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
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from uuid import uuid4

from .apps_catalog import AppsCatalogStore

LOGGER = logging.getLogger(__name__)
SUPPORTED_SOURCE_SUFFIXES = frozenset({".java", ".kt"})
PORTABLE_PACKAGE_FORMAT = "vrstudio-decompiled-package"
PORTABLE_PACKAGE_SCHEMA_VERSION = 1
PORTABLE_PACKAGE_MANIFEST = "vrstudio-package-export.json"
_PROGRESS_REPORT_INTERVAL = 250
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


def _resolve_indexed_content(
    workspace_root: Path,
    row: Any,
    relative: Path,
) -> bytes:
    """Resolve one indexed source against the shared integrity contract.

    The physical file wins only when its byte hash matches ``source_sha256``;
    otherwise the indexed body is authoritative.  Both exporter paths share
    this rule so a single implementation guards every exported source.
    """
    output_raw = str(row["output_reference"] or "").replace("\\", "/")
    output_reference = PurePosixPath(output_raw)
    if (output_raw and (output_reference.is_absolute()
            or PureWindowsPath(output_raw).is_absolute()
            or ".." in output_reference.parts)):
        raise ValueError("O índice contém uma referência de saída inválida.")
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
    if content is None and row["body"] is not None:
        body_content = str(row["body"]).encode("utf-8")
        if hashlib.sha256(body_content).hexdigest() == expected_hash:
            content = body_content
    if content is None:
        raise ValueError(
            "A fonte indexada foi alterada ou está inconsistente: "
            f"{relative.as_posix()}"
        )
    return content


def _indexed_path_collisions(
    connection: sqlite3.Connection,
    release_id: str,
    artifact_sha256: str,
    jar_relative_path: str,
) -> dict[str, int]:
    """Map colliding artifact paths to their lowest indexed class version.

    A multi-release or shaded JAR keeps several bytecode entries that decompile
    to the same relative path.  The lowest class version stays at the logical
    path; the remaining variants move under ``META-INF/versions/<v>`` so every
    indexed source can be exported without losing provenance.
    """
    collisions: dict[str, int] = {}
    for row in connection.execute(
        """SELECT replace(source_relative_path, '\\', '/') AS path_key,
                  min(class_version) AS base_version
             FROM code_sources
            WHERE release_id = ? AND artifact_sha256 = ? AND jar_relative_path = ?
            GROUP BY path_key
           HAVING count(*) > 1""",
        (release_id, artifact_sha256, jar_relative_path),
    ):
        collisions[str(row["path_key"])] = int(row["base_version"] or 0)
    return collisions


def _multi_release_source_path(
    relative: Path,
    class_version: int,
    base_version: int,
) -> Path:
    """Move a non-base multi-release variant under its ``META-INF/versions`` path."""
    if class_version <= base_version:
        return relative
    parts = relative.parts
    if (len(parts) >= 2 and parts[0].upper() == "META-INF"
            and parts[1].casefold() == "versions"):
        return relative
    return Path("META-INF", "versions", str(class_version), *parts)


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
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Export exactly one catalog application/version/variant/origin selection.

    ``progress`` receives ``{"current": int, "total": int}`` while indexed
    sources are written so callers can render a determinate progress bar.
    """
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
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            collisions = _indexed_path_collisions(
                connection, origin_id, artifact_sha256, jar_relative_path
            )
            total_sources = int(connection.execute(
                """SELECT count(*) FROM code_sources
                    WHERE release_id = ? AND artifact_sha256 = ? AND jar_relative_path = ?""",
                (origin_id, artifact_sha256, jar_relative_path),
            ).fetchone()[0])
            if progress is not None:
                progress({"current": 0, "total": total_sources})
            rows = connection.execute(
                """SELECT output_reference, source_relative_path, source_sha256, body,
                          class_version
                     FROM code_sources
                    WHERE release_id = ? AND artifact_sha256 = ? AND jar_relative_path = ?
                    ORDER BY source_relative_path, id""",
                (origin_id, artifact_sha256, jar_relative_path),
            )
            found_source = False
            processed = 0
            for row in rows:
                found_source = True
                processed += 1
                if progress is not None and processed % _PROGRESS_REPORT_INTERVAL == 0:
                    progress({"current": processed, "total": total_sources})
                raw_relative = str(row["source_relative_path"] or "").replace("\\", "/")
                relative = _relative_source_path(raw_relative)
                content = _resolve_indexed_content(workspace_root, row, relative)
                base_version = collisions.get(raw_relative)
                if base_version is not None:
                    relative = _multi_release_source_path(
                        relative, int(row["class_version"] or 0), base_version
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

            if progress is not None and total_sources > 0:
                progress({"current": total_sources, "total": total_sources})
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


def _available_zip_destination(parent: Path, base_name: str) -> Path:
    candidate = parent / f"{base_name}.zip"
    number = 2
    while candidate.exists():
        candidate = parent / f"{base_name}-{number}.zip"
        number += 1
    return candidate


def _portable_artifact_identity(
    catalog: dict[str, Any],
    composition_item: dict[str, Any],
) -> tuple[str, int, int]:
    """Return application display name, class count and size for a composition entry."""
    app_id = str(composition_item.get("app_id") or "")
    version = str(composition_item.get("version") or "")
    variant_id = str(composition_item.get("variant_id") or "")
    app = catalog.get("applications", {}).get(app_id, {})
    variant = app.get("versions", {}).get(version, {}).get("variants", {}).get(variant_id, {})
    app_name = str(composition_item.get("app_name") or app.get("name") or app_id)
    return app_name, int(variant.get("class_count") or 0), int(variant.get("size_bytes") or 0)


def export_decompiled_package(
    workspace: str | Path,
    destination_file: str | Path,
    *,
    package_id: str,
    apps_store: AppsCatalogStore | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Export every indexed source of one catalog package as a portable ZIP.

    The archive carries a single ``vrstudio-package-export.json`` manifest at
    its root plus one entry per indexed source.  Dependencies indexed for the
    release are exported as dependencies, not converted into applications.

    ``progress`` receives ``{"current": int, "total": int}`` while indexed
    sources are written so callers can render a determinate progress bar.
    """
    workspace_root = Path(workspace).resolve(strict=True)
    selected_package = str(package_id or "").strip()
    store = apps_store or AppsCatalogStore(root=workspace_root)
    catalog = store.load_catalog()
    package = catalog.get("packages", {}).get(selected_package)
    if not package:
        raise ValueError("O pacote selecionado não foi encontrado no catálogo.")

    destination = Path(destination_file).expanduser().resolve(strict=False)
    if destination.suffix.casefold() != ".zip":
        destination = destination.with_name(f"{destination.name}.zip")
    parent = destination.parent
    if not parent.is_dir():
        raise ValueError("A pasta de destino selecionada não existe.")
    destination = _available_zip_destination(parent, destination.stem)

    database = workspace_root / "indice" / "codigo" / "processing.sqlite"
    if not database.is_file():
        raise ValueError("O índice de código não está disponível.")

    composition_items = [
        item for item in package.get("composition", []) if isinstance(item, dict)
    ]
    dependency_items = [
        item for item in package.get("dependencies", []) if isinstance(item, dict)
    ]
    composition_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for item in composition_items:
        composition_lookup.setdefault(
            (str(item.get("sha256") or ""), str(item.get("jar_path") or "")), item
        )
    dependency_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for item in dependency_items:
        key = (str(item.get("sha256") or ""), str(item.get("relative_path") or ""))
        if key not in composition_lookup:
            dependency_lookup.setdefault(key, item)

    def _artifact_sort(key: tuple[str, str]) -> tuple[str, str]:
        return (key[1], key[0])

    ordered_applications = sorted(composition_lookup, key=_artifact_sort)
    ordered_dependencies = sorted(dependency_lookup, key=_artifact_sort)

    staging = parent / f".{destination.name}.tmp-{uuid4().hex}.zip"
    file_count = 0
    total_bytes = 0
    try:
        uri = f"{database.as_uri()}?mode=ro"
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                index_keys = [
                    (
                        str(row["artifact_sha256"] or ""),
                        str(row["jar_relative_path"] or ""),
                    )
                    for row in connection.execute(
                        """SELECT DISTINCT jar_relative_path, artifact_sha256
                             FROM code_sources
                            WHERE release_id = ?
                            ORDER BY jar_relative_path, artifact_sha256""",
                        (selected_package,),
                    )
                ]
                ordered_orphans = sorted(
                    (
                        key for key in index_keys
                        if key not in composition_lookup and key not in dependency_lookup
                    ),
                    key=_artifact_sort,
                )

                artifacts: list[dict[str, Any]] = []
                artifact_by_key: dict[tuple[str, str], dict[str, Any]] = {}

                def _append_artifact(
                    key: tuple[str, str], artifact: dict[str, Any]
                ) -> None:
                    artifact["artifact_index"] = len(artifacts) + 1
                    artifacts.append(artifact)
                    artifact_by_key[key] = artifact

                for key in ordered_applications:
                    item = composition_lookup[key]
                    app_name, class_count, size_bytes = _portable_artifact_identity(
                        catalog, item
                    )
                    _append_artifact(key, {
                        "role": "application",
                        "artifact_sha256": key[0],
                        "jar_relative_path": key[1],
                        "size_bytes": size_bytes,
                        "source_count": 0,
                        "sources": [],
                        "application_id": str(item.get("app_id") or ""),
                        "application_name": app_name,
                        "version": str(item.get("version") or ""),
                        "variant_id": str(item.get("variant_id") or ""),
                        "distribution_id": str(item.get("distribution_id") or ""),
                        "class_count": class_count,
                        "_source_bytes": 0,
                    })
                for key in ordered_dependencies:
                    _append_artifact(key, {
                        "role": "dependency",
                        "artifact_sha256": key[0],
                        "jar_relative_path": key[1],
                        "size_bytes": int(dependency_lookup[key].get("size_bytes") or 0),
                        "source_count": 0,
                        "sources": [],
                        "_source_bytes": 0,
                    })
                for key in ordered_orphans:
                    _append_artifact(key, {
                        "role": "dependency",
                        "artifact_sha256": key[0],
                        "jar_relative_path": key[1],
                        "size_bytes": 0,
                        "source_count": 0,
                        "sources": [],
                        "_source_bytes": 0,
                    })

                total_sources = int(connection.execute(
                    "SELECT count(*) FROM code_sources WHERE release_id = ?",
                    (selected_package,),
                ).fetchone()[0])
                if progress is not None:
                    progress({"current": 0, "total": total_sources})

                current_key: tuple[str, str] | None = None
                current_artifact: dict[str, Any] | None = None
                exported_paths: dict[str, str] = {}
                exported_spellings: dict[str, str] = {}
                collisions: dict[str, int] = {}
                processed = 0

                rows = connection.execute(
                    """SELECT id, jar_relative_path, artifact_sha256,
                              source_relative_path, source_sha256,
                              output_reference, body, class_version
                         FROM code_sources
                        WHERE release_id = ?
                        ORDER BY jar_relative_path, artifact_sha256,
                                 source_relative_path, id""",
                    (selected_package,),
                )
                for row in rows:
                    processed += 1
                    if progress is not None and processed % _PROGRESS_REPORT_INTERVAL == 0:
                        progress({"current": processed, "total": total_sources})
                    artifact_key = (
                        str(row["artifact_sha256"] or ""),
                        str(row["jar_relative_path"] or ""),
                    )
                    if artifact_key != current_key:
                        current_key = artifact_key
                        current_artifact = artifact_by_key.get(artifact_key)
                        exported_paths = {}
                        exported_spellings = {}
                        collisions = _indexed_path_collisions(
                            connection, selected_package, *artifact_key
                        )
                    if current_artifact is None:
                        raise ValueError(
                            "O índice mudou durante a exportação; gere o pacote novamente."
                        )

                    raw_relative = str(row["source_relative_path"] or "").replace("\\", "/")
                    relative = _relative_source_path(raw_relative)
                    content = _resolve_indexed_content(workspace_root, row, relative)
                    base_version = collisions.get(raw_relative)
                    if base_version is not None:
                        relative = _multi_release_source_path(
                            relative, int(row["class_version"] or 0), base_version
                        )

                    content_hash = hashlib.sha256(content).hexdigest()
                    key = relative.as_posix().casefold()
                    previous_hash = exported_paths.get(key)
                    if previous_hash is not None:
                        if exported_spellings[key] != relative.as_posix():
                            raise ValueError(
                                "O índice contém caminhos incompatíveis com Windows: "
                                f"{exported_spellings[key]} / {relative.as_posix()}"
                            )
                        if previous_hash != content_hash:
                            raise ValueError(
                                f"O índice contém fontes conflitantes para: {relative.as_posix()}"
                            )
                        continue

                    archive_path = (
                        f"sources/{int(current_artifact['artifact_index']):04d}/"
                        f"{relative.as_posix()}"
                    )
                    archive.writestr(archive_path, content)
                    current_artifact["sources"].append({
                        "source_relative_path": relative.as_posix(),
                        "source_sha256": content_hash,
                        "archive_path": archive_path,
                    })
                    current_artifact["source_count"] += 1
                    current_artifact["_source_bytes"] += len(content)
                    exported_paths[key] = content_hash
                    exported_spellings[key] = relative.as_posix()
                    file_count += 1
                    total_bytes += len(content)

            if progress is not None and total_sources > 0:
                progress({"current": total_sources, "total": total_sources})
            if file_count == 0:
                raise ValueError("Nenhum código decompilado disponível para este pacote.")

            for artifact in artifacts:
                if not artifact["size_bytes"]:
                    artifact["size_bytes"] = artifact.pop("_source_bytes")
                else:
                    artifact.pop("_source_bytes", None)

            manifest = {
                "format": PORTABLE_PACKAGE_FORMAT,
                "schema_version": PORTABLE_PACKAGE_SCHEMA_VERSION,
                "package_id": selected_package,
                "package_name": str(package.get("name") or selected_package),
                "package_manifest_sha256": str(package.get("manifest_sha256") or ""),
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "file_count": file_count,
                "total_bytes": total_bytes,
                "artifacts": artifacts,
            }
            archive.writestr(
                PORTABLE_PACKAGE_MANIFEST,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
        staging.replace(destination)
    except Exception:
        LOGGER.exception("Failed to export decompiled package %s", selected_package)
        staging.unlink(missing_ok=True)
        raise

    return {
        "success": True,
        "destination": str(destination),
        "package_id": selected_package,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "artifact_count": len(artifacts),
    }


"""Detection and direct ingestion of already-decompiled Java sources.

Supports migrating decompiled applications (e.g. VRMaster, VRAdm) or full packages
from Machine 1 to Machine 2 without requiring JVM decompiler toolchains.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from uuid import uuid4

from .apps_catalog import AppsCatalogStore, _transaction
from .code_index import (
    CODE_INDEX_SCHEMA_VERSION,
    JavaCodeIndex,
    _code_source_key,
    parse_java_source,
    parse_kotlin_source,
)
from .decompiled_export import (
    PORTABLE_PACKAGE_FORMAT,
    PORTABLE_PACKAGE_MANIFEST,
    PORTABLE_PACKAGE_SCHEMA_VERSION,
    _PROGRESS_REPORT_INTERVAL,
    _relative_source_path,
    _require_within,
)
from .erp_releases import _safe_component
from .jvm_batches import PROCESSING_SCHEMA_VERSION, DecompilationBatchStore


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMLINK_FILE_MODE = 0o120000
LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _portable_archive_error(message: str) -> dict[str, Any]:
    return {
        "is_valid": False,
        "portable_package": True,
        "error": message,
        "applications": [],
        "total_java_files": 0,
    }


def _validate_zip_entry_name(name: str, *, label: str = "entrada") -> str:
    """Reject ZIP slip variants before any path is used."""
    raw = str(name or "")
    if not raw:
        raise ValueError(f"O pacote contém uma {label} ZIP sem nome.")
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//") or PurePosixPath(normalized).is_absolute():
        raise ValueError(f"O pacote contém um caminho absoluto: {raw}")
    if PureWindowsPath(raw).is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"O pacote contém um caminho com unidade Windows: {raw}")
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError(f"O pacote contém um caminho com '..': {raw}")
    return normalized


def _archive_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == _SYMLINK_FILE_MODE


def _read_validated_archive_source(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    archive_path: str,
    expected_hash: str,
) -> bytes:
    normalized = str(archive_path or "").replace("\\", "/")
    info = entries.get(normalized)
    if info is None:
        raise ValueError(f"O pacote não contém a fonte referenciada: {archive_path}")
    content = archive.read(info.filename)
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError(f"A fonte do pacote está corrompida: {archive_path}")
    return content


def detect_decompiled_package_archive(source_archive: str | Path) -> dict[str, Any]:
    """Validate a portable decompiled package ZIP without mutating anything."""
    archive_path = Path(source_archive).expanduser()
    try:
        resolved = archive_path.resolve(strict=True)
    except OSError:
        return _portable_archive_error(f"Arquivo não encontrado: {archive_path}")
    if not resolved.is_file() or resolved.suffix.casefold() != ".zip":
        return _portable_archive_error("Selecione um arquivo ZIP de pacote descompilado.")
    if not zipfile.is_zipfile(resolved):
        return _portable_archive_error("O arquivo selecionado não é um ZIP válido.")
    try:
        with zipfile.ZipFile(resolved) as archive:
            normalized_names: list[str] = []
            entries: dict[str, zipfile.ZipInfo] = {}
            for info in archive.infolist():
                normalized = _validate_zip_entry_name(info.filename)
                if _archive_entry_is_symlink(info):
                    raise ValueError("O pacote contém uma entrada simbólica não suportada.")
                if normalized in entries:
                    raise ValueError(
                        f"O pacote contém entradas ZIP duplicadas: {normalized}"
                    )
                entries[normalized] = info
                normalized_names.append(normalized)
            if sum(
                1 for name in normalized_names if name == PORTABLE_PACKAGE_MANIFEST
            ) != 1:
                raise ValueError("O pacote não contém o manifesto de exportação na raiz.")
            try:
                manifest = json.loads(
                    archive.read(PORTABLE_PACKAGE_MANIFEST).decode("utf-8")
                )
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("O manifesto do pacote é inválido.") from exc
            if not isinstance(manifest, dict):
                raise ValueError("O manifesto do pacote é inválido.")
            if manifest.get("format") != PORTABLE_PACKAGE_FORMAT:
                raise ValueError("O arquivo não é um pacote portátil do VRStudio.")
            if int(manifest.get("schema_version") or 0) != PORTABLE_PACKAGE_SCHEMA_VERSION:
                raise ValueError("Versão do manifesto de pacote não suportada.")
            package_id = str(manifest.get("package_id") or "").strip()
            if not package_id:
                raise ValueError("O manifesto do pacote não possui identificador.")
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, list):
                raise ValueError("O manifesto do pacote não possui artefatos.")

            applications: list[dict[str, Any]] = []
            verified_paths: dict[str, str] = {}
            artifact_indexes: set[int] = set()
            total_sources = 0
            total_source_bytes = 0
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise ValueError("O manifesto do pacote contém um artefato inválido.")
                role = str(artifact.get("role") or "")
                if role not in {"application", "dependency"}:
                    raise ValueError("O manifesto do pacote contém um papel de artefato inválido.")
                try:
                    artifact_index = int(artifact.get("artifact_index"))
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "O manifesto do pacote contém um índice de artefato inválido."
                    ) from exc
                if artifact_index < 1:
                    raise ValueError(
                        "O manifesto do pacote contém um índice de artefato inválido."
                    )
                if artifact_index in artifact_indexes:
                    raise ValueError(
                        "O manifesto do pacote contém índices de artefato duplicados."
                    )
                artifact_indexes.add(artifact_index)
                artifact_sha = str(artifact.get("artifact_sha256") or "")
                if not artifact_sha:
                    raise ValueError("O manifesto do pacote contém um artefato sem SHA-256.")
                _validate_zip_entry_name(
                    str(artifact.get("jar_relative_path") or ""), label="origem"
                )
                sources = artifact.get("sources")
                if not isinstance(sources, list):
                    raise ValueError("O manifesto do pacote contém uma lista de fontes inválida.")
                source_count = 0
                for source in sources:
                    if not isinstance(source, dict):
                        raise ValueError("O manifesto do pacote contém uma fonte inválida.")
                    relative = _relative_source_path(
                        str(source.get("source_relative_path") or "")
                    )
                    expected_hash = str(source.get("source_sha256") or "").strip().casefold()
                    if not _HEX64_RE.fullmatch(expected_hash):
                        raise ValueError(
                            "O manifesto do pacote contém hash inválido para: "
                            f"{relative.as_posix()}"
                        )
                    archive_entry = _validate_zip_entry_name(
                        str(source.get("archive_path") or ""), label="fonte"
                    )
                    expected_archive_path = (
                        f"sources/{artifact_index:04d}/{relative.as_posix()}"
                    )
                    if archive_entry != expected_archive_path:
                        raise ValueError(
                            "O manifesto do pacote contém um caminho de fonte "
                            f"inconsistente: {archive_entry}"
                        )
                    previous_hash = verified_paths.get(archive_entry)
                    if previous_hash is not None:
                        if previous_hash != expected_hash:
                            raise ValueError(
                                "O pacote referencia a mesma fonte com conteúdos conflitantes."
                            )
                    else:
                        content = _read_validated_archive_source(
                            archive, entries, archive_entry, expected_hash
                        )
                        verified_paths[archive_entry] = expected_hash
                        total_source_bytes += len(content)
                    source_count += 1
                if int(artifact.get("source_count") or 0) != source_count:
                    raise ValueError(
                        "O manifesto do pacote contém contagens de fontes inconsistentes."
                    )
                if role == "application":
                    application_id = str(artifact.get("application_id") or "").strip()
                    version = str(artifact.get("version") or "").strip()
                    if not application_id or not version:
                        raise ValueError("O manifesto do pacote contém um aplicativo incompleto.")
                    applications.append({
                        "app_id": application_id,
                        "app_name": str(artifact.get("application_name") or application_id),
                        "version": version,
                        "variant_id": str(artifact.get("variant_id") or ""),
                        "sha256": artifact_sha,
                        "source_count": source_count,
                    })
                total_sources += source_count
            if int(manifest.get("file_count") or 0) != total_sources:
                raise ValueError(
                    "O manifesto do pacote contém um total de arquivos inconsistente."
                )
            if int(manifest.get("total_bytes") or 0) != total_source_bytes:
                raise ValueError(
                    "O manifesto do pacote contém um total de bytes inconsistente."
                )
    except ValueError as exc:
        return _portable_archive_error(str(exc))
    except (OSError, zipfile.BadZipFile) as exc:
        return _portable_archive_error(str(exc) or "Falha ao ler o pacote portátil.")

    return {
        "is_valid": True,
        "portable_package": True,
        "scope": "package",
        "source_archive": str(resolved),
        "suggested_release_id": package_id,
        "suggested_name": str(manifest.get("package_name") or package_id),
        "applications": applications,
        "total_java_files": total_sources,
        "manifest": manifest,
    }


def _purge_portable_release_rows(
    batch_store: DecompilationBatchStore,
    release_id: str,
) -> None:
    """Remove the imported release rows explicitly, without relying on cascades."""
    with batch_store.connect() as connection:
        source_ids = [
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM code_sources WHERE release_id = ?", (release_id,)
            )
        ]
        for source_id in source_ids:
            connection.execute(
                "DELETE FROM code_relations WHERE source_id = ?", (source_id,)
            )
            connection.execute(
                "DELETE FROM code_symbols WHERE source_id = ?", (source_id,)
            )
        connection.execute(
            "DELETE FROM code_sources WHERE release_id = ?", (release_id,)
        )
        connection.execute(
            "DELETE FROM decompilation_plans WHERE release_id = ?", (release_id,)
        )
        connection.commit()


def _find_portable_variant(
    catalog: dict[str, Any],
    application_id: str,
    sha256: str,
) -> tuple[str, dict[str, Any]] | None:
    app = catalog.get("applications", {}).get(application_id)
    if not isinstance(app, dict):
        return None
    for version_key, version in app.get("versions", {}).items():
        if not isinstance(version, dict):
            continue
        for variant in version.get("variants", {}).values():
            if isinstance(variant, dict) and str(variant.get("sha256") or "") == sha256:
                return str(version_key), variant
    return None


@_transaction
def _publish_portable_package(
    store: AppsCatalogStore,
    release_id: str,
    package_name: str,
    source_path: str,
    manifest: dict[str, Any],
    catalog_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Register the package and remap computed distribution IDs in one snapshot."""
    registered = store.register_package(
        manifest,
        package_id=release_id,
        package_name=package_name,
        source_path=source_path,
    )
    catalog = store.load_catalog()
    package = catalog.get("packages", {}).get(release_id, {})
    for artifact in catalog_artifacts:
        if str(artifact.get("artifact_role") or "") != "application":
            continue
        application_id = str(artifact.get("application_key") or "")
        sha256 = str(artifact.get("sha256") or "")
        jar_path = str(artifact.get("relative_path") or "")
        portable_distribution = str(artifact.get("distribution_id") or "")
        found = _find_portable_variant(catalog, application_id, sha256)
        if found is None:
            continue
        version_key, variant = found
        if portable_distribution:
            computed = ""
            for origin in variant.get("origin_packages", []):
                if str(origin.get("package_id") or "") != release_id:
                    continue
                computed = str(origin.get("distribution_id") or "")
                origin["distribution_id"] = portable_distribution
            if computed and computed != portable_distribution:
                contexts = variant.setdefault("distribution_contexts", {})
                context = contexts.pop(computed, None)
                if context is not None:
                    context["distribution_id"] = portable_distribution
                    contexts[portable_distribution] = context
            for entry in package.get("composition", []):
                if (str(entry.get("sha256") or "") == sha256
                        and str(entry.get("jar_path") or "") == jar_path):
                    entry["distribution_id"] = portable_distribution
        source_total = int(artifact.get("decompiled_classes") or 0)
        if source_total > 0:
            store.update_variant_state(
                application_id,
                version_key,
                sha256,
                "ready",
                decompilation_state="ready",
                class_count=int(artifact.get("class_count") or 0) or source_total,
                indexed_classes=source_total,
                decompiled_classes=source_total,
            )
    return registered


def _import_decompiled_package_archive(
    store: AppsCatalogStore,
    workspace: str | Path,
    source_archive: str | Path,
    *,
    release_id: str = "",
    package_name: str = "",
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Ingest a validated portable ZIP into a fresh catalog/workspace.

    ``progress`` receives ``{"current": int, "total": int}`` while archive
    sources are extracted and indexed so callers can render a determinate
    progress bar.
    """
    ws = Path(workspace).resolve()
    detection = detect_decompiled_package_archive(source_archive)
    if not detection.get("is_valid"):
        raise ValueError(detection.get("error") or "Pacote portátil inválido.")

    selected_release_id = (
        str(release_id or "").strip() or detection["suggested_release_id"]
    ).strip()
    if not selected_release_id or _safe_component(selected_release_id) != selected_release_id:
        raise ValueError("Identificador de release inválido.")
    selected_pkg_name = (
        str(package_name or "").strip()
        or str(detection.get("suggested_name") or "").strip()
        or selected_release_id
    )

    if store.get_package(selected_release_id):
        raise ValueError("Já existe um pacote com este identificador; use outro identificador.")
    decomp_root = (ws / "indice" / "codigo" / "decompilation" / selected_release_id)
    if decomp_root.resolve().exists():
        raise ValueError("O diretório de destino já existe; use outro identificador.")
    code_index = JavaCodeIndex(ws)
    code_index.initialize()
    batch_store = code_index.store
    with batch_store.connect() as conn:
        if conn.execute(
            "SELECT 1 FROM code_sources WHERE release_id = ? LIMIT 1",
            (selected_release_id,),
        ).fetchone() or conn.execute(
            "SELECT 1 FROM decompilation_plans WHERE release_id = ? LIMIT 1",
            (selected_release_id,),
        ).fetchone():
            raise ValueError("Já existem dados indexados com este identificador; use outro identificador.")

    manifest = detection["manifest"]
    artifacts = manifest["artifacts"]
    release_hash = hashlib.sha256(selected_release_id.encode("utf-8")).hexdigest()
    portable_manifest_hash = str(manifest.get("package_manifest_sha256") or "").strip()
    now = _utc_now()
    relative_root = f"indice/codigo/decompilation/{selected_release_id}"
    decomp_root.parent.mkdir(parents=True, exist_ok=True)
    staging = decomp_root.parent / f".{selected_release_id}.tmp-{uuid4().hex}"
    total_indexed = 0
    total_sources = sum(len(artifact.get("sources") or []) for artifact in artifacts)
    processed = 0
    catalog_artifacts: list[dict[str, Any]] = []
    published = False
    if progress is not None:
        progress({"current": 0, "total": total_sources})
    try:
        with zipfile.ZipFile(detection["source_archive"]) as archive:
            entries = {
                info.filename.replace("\\", "/"): info
                for info in archive.infolist()
            }
            with batch_store.connect() as conn:
                conn.execute(
                    """INSERT INTO decompilation_plans
                       (plan_id, schema_version, release_id, release_hash, state,
                        max_classes, max_bytes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?)""",
                    (
                        selected_release_id,
                        PROCESSING_SCHEMA_VERSION,
                        selected_release_id,
                        release_hash,
                        int(manifest.get("file_count") or 0),
                        0,
                        now,
                        now,
                    ),
                )
                for artifact in artifacts:
                    artifact_index = int(artifact["artifact_index"])
                    role = str(artifact["role"])
                    artifact_sha = str(artifact["artifact_sha256"])
                    jar_path = _validate_zip_entry_name(
                        str(artifact.get("jar_relative_path") or ""), label="origem"
                    )
                    artifact_dir = f"artifacts/{artifact_index:04d}"
                    output_ref = f"{relative_root}/{artifact_dir}"
                    if role == "application":
                        catalog_artifacts.append({
                            "artifact_role": "application",
                            "application": str(
                                artifact.get("application_name")
                                or artifact.get("application_id")
                                or ""
                            ),
                            "application_key": str(artifact.get("application_id") or ""),
                            "application_name": str(artifact.get("application_name") or ""),
                            "version_detected": str(artifact.get("version") or ""),
                            "sha256": artifact_sha,
                            "size_bytes": int(artifact.get("size_bytes") or 0),
                            "relative_path": jar_path,
                            "class_count": int(artifact.get("class_count") or 0)
                                or int(artifact.get("source_count") or 0),
                            "decompiled_classes": int(artifact.get("source_count") or 0),
                            "distribution_id": str(artifact.get("distribution_id") or ""),
                        })
                    else:
                        catalog_artifacts.append({
                            "artifact_role": "library",
                            "relative_path": jar_path,
                            "sha256": artifact_sha,
                            "size_bytes": int(artifact.get("size_bytes") or 0),
                        })

                    for source in artifact["sources"]:
                        relative = _relative_source_path(
                            str(source["source_relative_path"])
                        )
                        expected_hash = str(source["source_sha256"]).strip().casefold()
                        content = _read_validated_archive_source(
                            archive,
                            entries,
                            str(source["archive_path"]),
                            expected_hash,
                        )
                        body = content.decode("utf-8")
                        target_file = _require_within(
                            staging / artifact_dir / relative,
                            staging,
                            "O pacote contém um caminho de fonte inválido.",
                        )
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        target_file.write_bytes(content)
                        file_hash = hashlib.sha256(content).hexdigest()
                        fallback_qualified = relative.as_posix().rsplit(".", 1)[0].replace("/", ".")
                        parser = (
                            parse_kotlin_source
                            if relative.suffix.casefold() == ".kt"
                            else parse_java_source
                        )
                        parsed = parser(body, fallback_qualified=fallback_qualified)
                        source_key = _code_source_key(
                            release_id=selected_release_id,
                            release_hash=release_hash,
                            artifact_sha256=artifact_sha,
                            class_version=52,
                            qualified_name=parsed.qualified_name,
                            content_hashes=[file_hash],
                        )
                        symbols_text = " ".join(
                            dict.fromkeys(
                                [parsed.qualified_name]
                                + [str(item["simple_name"]) for item in parsed.symbols]
                                + [str(item["signature"]) for item in parsed.symbols]
                                + [str(item["target"]) for item in parsed.relations]
                            )
                        )
                        if conn.execute(
                            "SELECT 1 FROM code_sources WHERE source_key = ?",
                            (source_key,),
                        ).fetchone() is None:
                            cursor = conn.execute(
                                """INSERT INTO code_sources
                                   (source_key, schema_version, release_id, release_hash,
                                    jar_relative_path, artifact_sha256, batch_id,
                                    class_version, tool,
                                    output_reference, source_relative_path, source_sha256,
                                    package_name, primary_type, qualified_name,
                                    logical_names_json, content_hashes_json, occurrence_count,
                                    parser_kind, syntax_error_count, symbols_text, body, indexed_at)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    source_key,
                                    CODE_INDEX_SCHEMA_VERSION,
                                    selected_release_id,
                                    release_hash,
                                    jar_path,
                                    artifact_sha,
                                    f"batch-{selected_release_id}-package-{artifact_index:04d}",
                                    52,
                                    "decompiled_package_import",
                                    output_ref,
                                    relative.as_posix(),
                                    file_hash,
                                    parsed.package_name,
                                    parsed.primary_type,
                                    parsed.qualified_name,
                                    json.dumps([parsed.qualified_name]),
                                    json.dumps([file_hash]),
                                    1,
                                    parsed.parser_kind,
                                    parsed.syntax_error_count,
                                    symbols_text,
                                    body,
                                    now,
                                ),
                            )
                            source_id = cursor.lastrowid
                            conn.executemany(
                                """INSERT INTO code_symbols
                                   (source_id, kind, simple_name, qualified_name, signature, visibility, line_start)
                                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                [(source_id, item["kind"], item["simple_name"], item["qualified_name"],
                                  item["signature"], item["visibility"], item["line_start"])
                                 for item in parsed.symbols],
                            )
                            conn.executemany(
                                """INSERT INTO code_relations
                                   (source_id, kind, target, source_symbol, confidence, line_start)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                [(source_id, item["kind"], item["target"], item.get("source_symbol", ""),
                                  float(item.get("confidence", 0.0)), item["line_start"])
                                 for item in parsed.relations],
                            )
                            total_indexed += 1
                        processed += 1
                        if (
                            progress is not None
                            and processed % _PROGRESS_REPORT_INTERVAL == 0
                        ):
                            progress({"current": processed, "total": total_sources})

                if progress is not None and total_sources > 0:
                    progress({"current": total_sources, "total": total_sources})

                synthetic_manifest = {
                    "release_id": selected_release_id,
                    "release_manifest_sha256": portable_manifest_hash or release_hash,
                    "source_dir": relative_root,
                    "source_origin_dir": relative_root,
                    "analysis_scope": "package",
                    "artifacts": catalog_artifacts,
                    "indexed_at": now,
                }
                staging.replace(decomp_root)
                published = True
                conn.commit()
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if published and decomp_root.is_dir():
            shutil.rmtree(decomp_root, ignore_errors=True)
            try:
                _purge_portable_release_rows(batch_store, selected_release_id)
            except Exception as cleanup_error:
                LOGGER.error(
                    "Falha ao limpar o índice importado de %s: %s",
                    selected_release_id,
                    cleanup_error,
                )
        raise

    try:
        registered_pkg = _publish_portable_package(
            store,
            selected_release_id,
            selected_pkg_name,
            relative_root,
            synthetic_manifest,
            catalog_artifacts,
        )
    except Exception:
        shutil.rmtree(decomp_root, ignore_errors=True)
        try:
            _purge_portable_release_rows(batch_store, selected_release_id)
        except Exception as cleanup_error:
            LOGGER.error(
                "Falha ao compensar a importação de %s: %s",
                selected_release_id,
                cleanup_error,
            )
        raise

    return {
        "success": True,
        "release_id": selected_release_id,
        "package_name": selected_pkg_name,
        "imported_applications": sum(
            1 for artifact in artifacts if str(artifact.get("role")) == "application"
        ),
        "total_indexed_sources": total_indexed,
        "package": registered_pkg,
    }


def import_decompiled_package_archive(
    workspace: str | Path,
    source_archive: str | Path,
    *,
    release_id: str = "",
    package_name: str = "",
    apps_store: AppsCatalogStore | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    store = apps_store or AppsCatalogStore(root=workspace)
    return _import_decompiled_package_archive(
        store,
        workspace,
        source_archive,
        release_id=release_id,
        package_name=package_name,
        progress=progress,
    )


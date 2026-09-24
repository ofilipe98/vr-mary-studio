"""Portable export and import of VRWiki, Endoo wiki and Movidesk KB knowledge.

The ``documents`` row is authoritative: the canonical ``.md`` published in the
package is regenerated with :func:`canonical_markdown`, so an outdated physical
file never changes the meaning of an exported package.  Endoo is authenticated
content and is only exported when its origin is listed explicitly, mirroring
the ``--include-endoo`` opt-in of the portable project export.

Assets referenced by the exported documents are always packaged so the other
machine keeps working images and attachments; missing physical assets are
skipped and reported in the manifest instead of aborting the export.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from uuid import uuid4

from .classifier import classify
from .content import (
    KNOWLEDGE_MODULES,
    canonical_markdown,
    preserve_validated_classification,
    sha256_text,
    write_and_persist_document,
)
from .db import MaryDatabase
from .decompiled_detection import _archive_entry_is_symlink, _validate_zip_entry_name
from .decompiled_export import _PROGRESS_REPORT_INTERVAL, _available_zip_destination
from .indexer import export_catalog
from .models import KnowledgeDocument
from .paths import resolve_portable_path

LOGGER = logging.getLogger(__name__)

KNOWLEDGE_PACKAGE_FORMAT = "vrstudio-knowledge-package"
KNOWLEDGE_PACKAGE_SCHEMA_VERSION = 1
KNOWLEDGE_PACKAGE_MANIFEST = "vrstudio-knowledge-export.json"
KNOWLEDGE_RECORDS_FILE = "documents.jsonl"
KNOWLEDGE_ORIGINS: tuple[tuple[str, str], ...] = (
    ("wiki", "vrwiki"),
    ("wiki", "endoo"),
    ("kb", "movidesk"),
)
DEFAULT_EXPORT_ORIGINS: tuple[tuple[str, str], ...] = (
    ("wiki", "vrwiki"),
    ("kb", "movidesk"),
)
ORIGIN_ASSET_DIRS = {
    ("wiki", "vrwiki"): "assets/wiki",
    ("wiki", "endoo"): "assets/wiki/endoo",
    ("kb", "movidesk"): "assets/kb",
}
ORIGIN_LABELS = {
    "wiki/vrwiki": "VRWiki pública",
    "wiki/endoo": "Wiki Endoo",
    "kb/movidesk": "KB Movidesk",
}
IMPORT_MODES = ("merge", "restore")
MAX_ERROR_DETAILS = 20
_MAX_PREVIEW = 50
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def origin_label(source: str, source_origin: str) -> str:
    return ORIGIN_LABELS.get(f"{source}/{source_origin}", f"{source}/{source_origin}")


def _package_error(message: str) -> dict[str, Any]:
    return {
        "is_valid": False,
        "knowledge_package": True,
        "error": message,
        "origins": [],
        "modules": [],
        "document_count": 0,
        "asset_count": 0,
        "total_bytes": 0,
    }


def _normalize_origins(origins: Iterable[Any]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in origins or ():
        if isinstance(item, str):
            source, _, source_origin = item.partition("/")
        else:
            try:
                source, source_origin = item
            except (TypeError, ValueError) as exc:
                raise ValueError("Origem de conhecimento inválida.") from exc
        pair = (str(source).strip().casefold(), str(source_origin).strip().casefold())
        if pair not in ORIGIN_ASSET_DIRS:
            raise ValueError(
                f"Origem de conhecimento inválida: {source}/{source_origin}"
            )
        if pair not in pairs:
            pairs.append(pair)
    if not pairs:
        raise ValueError("Selecione pelo menos uma origem de conhecimento.")
    return tuple(pairs)


def _portable_relative(
    value: Any,
    *,
    prefixes: tuple[str, ...],
    label: str,
) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError(f"O índice contém {label} sem caminho.")
    if raw.startswith("/") or _DRIVE_RE.match(raw):
        raise ValueError(f"O índice contém {label} absoluto: {raw}")
    relative = PurePosixPath(raw)
    if ".." in relative.parts:
        raise ValueError(f"O índice contém {label} com '..': {raw}")
    if not raw.startswith(prefixes):
        raise ValueError(f"O índice contém {label} fora da área permitida: {raw}")
    return relative


def _resolve_within(root: Path, relative: str) -> Path:
    target = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"O pacote tentou gravar fora do projeto: {relative}"
        ) from exc
    return target


def _write_bytes_atomic(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _assets_from_json(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _document_from_row(row: sqlite3.Row) -> KnowledgeDocument:
    return KnowledgeDocument(
        source=str(row["source"]),
        source_origin=str(row["source_origin"]),
        source_id=str(row["source_id"]),
        title=str(row["title"]),
        url=str(row["url"]),
        markdown=str(row["markdown"] or ""),
        module=str(row["module"]),
        classification_confidence=float(row["classification_confidence"] or 0.0),
        review_status=str(row["review_status"] or "pending"),
        status=str(row["status"] or "active"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        synced_at=str(row["synced_at"] or ""),
        revision=str(row["revision"] or ""),
        content_hash=str(row["content_hash"] or ""),
        category=str(row["category"] or ""),
        product=str(row["product"] or ""),
        assets=_assets_from_json(row["assets_json"]),
        local_path=str(row["local_path"] or ""),
    )


def _document_query(
    origins: tuple[tuple[str, str], ...],
    module_filter: str,
) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    for source, source_origin in origins:
        clauses.append("(source=? AND source_origin=?)")
        params.extend([source, source_origin])
    conditions = ["status='active'", "(" + " OR ".join(clauses) + ")"]
    if module_filter:
        conditions.append("module=?")
        params.append(module_filter)
    sql = f"""SELECT source,source_origin,source_id,title,url,module,
                     classification_confidence,review_status,status,
                     created_at,updated_at,synced_at,revision,content_hash,
                     category,product,markdown,local_path,assets_json
                FROM documents
               WHERE {' AND '.join(conditions)}
               ORDER BY source,source_origin,module,title COLLATE NOCASE,source_id"""
    return sql, params


def export_knowledge_package(
    workspace: str | Path,
    destination_file: str | Path,
    *,
    origins: Iterable[Any] = DEFAULT_EXPORT_ORIGINS,
    module: str = "",
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Export active Wiki/Endoo/KB documents as one portable ZIP package.

    ``progress`` receives ``{"current": int, "total": int}`` while documents
    and referenced assets are packaged so callers can render a determinate
    progress bar.
    """
    workspace_root = Path(workspace).resolve(strict=True)
    database_path = workspace_root / "indice" / "conhecimento.sqlite"
    if not database_path.is_file():
        raise ValueError("A base de conhecimento local não está disponível.")
    pairs = _normalize_origins(origins)
    module_filter = str(module or "").strip()
    if module_filter in {"Todos", "Todas"}:
        module_filter = ""
    if module_filter and module_filter not in KNOWLEDGE_MODULES:
        raise ValueError(f"Módulo de conhecimento inválido: {module_filter}")

    destination = Path(destination_file).expanduser().resolve(strict=False)
    if destination.suffix.casefold() != ".zip":
        destination = destination.with_name(f"{destination.name}.zip")
    parent = destination.parent
    if not parent.is_dir():
        raise ValueError("A pasta de destino selecionada não existe.")
    destination = _available_zip_destination(parent, destination.stem)

    sql, params = _document_query(pairs, module_filter)
    uri = f"{database_path.as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(sql, params).fetchall()
    if not rows:
        raise ValueError("Nenhum documento corresponde às origens selecionadas.")

    documents: list[tuple[KnowledgeDocument, PurePosixPath]] = []
    asset_sources: dict[str, Path] = {}
    missing_assets = 0
    for row in rows:
        document = _document_from_row(row)
        local_path = _portable_relative(
            document.local_path,
            prefixes=("conhecimento/",),
            label="um caminho de documento",
        )
        if local_path.suffix.casefold() != ".md":
            raise ValueError(
                f"O índice contém um documento sem extensão .md: {local_path.as_posix()}"
            )
        documents.append((document, local_path))
        for asset in document.assets:
            relative = _portable_relative(
                asset, prefixes=("assets/",), label="um caminho de anexo"
            )
            key = relative.as_posix()
            if key in asset_sources:
                continue
            source_path = resolve_portable_path(workspace_root, key)
            if not source_path.is_file() or not source_path.is_relative_to(workspace_root):
                missing_assets += 1
                continue
            asset_sources[key] = source_path

    asset_paths = sorted(asset_sources)
    total_units = len(documents) + len(asset_paths)
    origin_stats: dict[tuple[str, str], list[int]] = {
        pair: [0, 0] for pair in pairs
    }
    staging = parent / f".{destination.name}.tmp-{uuid4().hex}.zip"
    file_count = 0
    document_bytes = 0
    asset_bytes = 0
    current_units = 0

    def _report() -> None:
        if progress is not None:
            progress({"current": current_units, "total": total_units})

    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            _report()
            records: list[dict[str, Any]] = []
            packaged_assets: dict[str, str] = {}
            for document, local_path in documents:
                pair = (document.source, document.source_origin)
                document_assets: list[dict[str, str]] = []
                packaged_relative: list[str] = []
                for asset in document.assets:
                    relative = _portable_relative(
                        asset, prefixes=("assets/",), label="um caminho de anexo"
                    )
                    key = relative.as_posix()
                    source_path = asset_sources.get(key)
                    if source_path is None or key in packaged_relative:
                        continue
                    if key not in packaged_assets:
                        content = source_path.read_bytes()
                        digest = hashlib.sha256(content).hexdigest()
                        archive.writestr(key, content)
                        packaged_assets[key] = digest
                        asset_bytes += len(content)
                        file_count += 1
                        origin_stats[pair][1] += 1
                        current_units += 1
                        if current_units % _PROGRESS_REPORT_INTERVAL == 0:
                            _report()
                    document_assets.append({
                        "relative_path": key,
                        "package_path": key,
                        "sha256": packaged_assets[key],
                    })
                    packaged_relative.append(key)
                document.assets = packaged_relative
                content = canonical_markdown(document).encode("utf-8")
                archive.writestr(f"files/{local_path.as_posix()}", content)
                document_bytes += len(content)
                file_count += 1
                origin_stats[pair][0] += 1
                records.append({
                    "source": document.source,
                    "source_origin": document.source_origin,
                    "source_id": document.source_id,
                    "title": document.title,
                    "url": document.url,
                    "module": document.module,
                    "classification_confidence": document.classification_confidence,
                    "review_status": document.review_status,
                    "status": document.status,
                    "created_at": document.created_at,
                    "updated_at": document.updated_at,
                    "synced_at": document.synced_at,
                    "revision": document.revision,
                    "content_hash": document.content_hash,
                    "category": document.category,
                    "product": document.product,
                    "markdown": document.markdown,
                    "document_path": f"files/{local_path.as_posix()}",
                    "assets": document_assets,
                })
                current_units += 1
                if current_units % _PROGRESS_REPORT_INTERVAL == 0:
                    _report()

            payload = (
                "\n".join(json.dumps(item, ensure_ascii=False) for item in records)
                + "\n"
            ).encode("utf-8")
            archive.writestr(KNOWLEDGE_RECORDS_FILE, payload)
            records_sha256 = hashlib.sha256(payload).hexdigest()
            identity = json.dumps(
                {
                    "origins": [f"{source}/{origin}" for source, origin in pairs],
                    "module": module_filter,
                    "records_sha256": records_sha256,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            manifest = {
                "format": KNOWLEDGE_PACKAGE_FORMAT,
                "schema_version": KNOWLEDGE_PACKAGE_SCHEMA_VERSION,
                "package_id": "knowledge-"
                + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
                "exported_at": _utc_now(),
                "origins": [
                    {
                        "source": source,
                        "source_origin": source_origin,
                        "label": origin_label(source, source_origin),
                        "documents": origin_stats[(source, source_origin)][0],
                        "assets": origin_stats[(source, source_origin)][1],
                    }
                    for source, source_origin in pairs
                ],
                "modules": sorted({document.module for document, _ in documents}),
                "document_count": len(documents),
                "asset_count": len(packaged_assets),
                "missing_asset_count": missing_assets,
                "file_count": file_count,
                "document_bytes": document_bytes,
                "asset_bytes": asset_bytes,
                "total_bytes": document_bytes + asset_bytes,
                "records_sha256": records_sha256,
            }
            archive.writestr(
                KNOWLEDGE_PACKAGE_MANIFEST,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
        if progress is not None:
            progress({"current": total_units, "total": total_units})
        staging.replace(destination)
    except Exception:
        LOGGER.exception("Failed to export knowledge package to %s", destination)
        staging.unlink(missing_ok=True)
        raise

    return {
        "success": True,
        "destination": str(destination),
        "package_id": manifest["package_id"],
        "document_count": len(documents),
        "asset_count": len(packaged_assets),
        "missing_asset_count": missing_assets,
        "file_count": file_count,
        "total_bytes": manifest["total_bytes"],
    }


def _validated_record(record: dict[str, Any]) -> dict[str, Any]:
    source = str(record.get("source") or "").strip().casefold()
    source_origin = str(record.get("source_origin") or "").strip().casefold()
    if (source, source_origin) not in ORIGIN_ASSET_DIRS:
        raise ValueError(
            f"O pacote contém uma origem inválida: {source}/{source_origin}"
        )
    source_id = str(record.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("O pacote contém um documento sem identificador.")
    module = str(record.get("module") or "").strip()
    if module not in KNOWLEDGE_MODULES:
        raise ValueError(f"O pacote contém um módulo inválido: {module}")
    review_status = str(record.get("review_status") or "").strip().casefold()
    if review_status not in {"pending", "approved", "kept"}:
        raise ValueError(
            f"O pacote contém um estado de revisão inválido: {review_status}"
        )
    status = str(record.get("status") or "").strip().casefold() or "active"
    if status not in {"active", "inactive"}:
        raise ValueError(f"O pacote contém um estado inválido: {status}")
    markdown = record.get("markdown")
    if not isinstance(markdown, str):
        raise ValueError("O pacote contém um documento sem conteúdo.")
    title = str(record.get("title") or "")
    content_hash = str(record.get("content_hash") or "").strip().casefold()
    computed_hash = sha256_text("\n".join([title, markdown]))
    if content_hash and content_hash != computed_hash:
        raise ValueError(
            "O conteúdo de um documento do pacote está corrompido: "
            f"{title or source_id}"
        )
    document_path = _portable_relative(
        record.get("document_path"),
        prefixes=("files/",),
        label="um caminho de documento",
    )
    if document_path.suffix.casefold() != ".md":
        raise ValueError(
            f"O pacote contém um documento sem extensão .md: {document_path.as_posix()}"
        )
    local_path = document_path.relative_to("files").as_posix()
    if not local_path.startswith("conhecimento/"):
        raise ValueError(
            f"O pacote contém um documento fora de conhecimento/: {local_path}"
        )
    raw_assets = record.get("assets") or []
    if not isinstance(raw_assets, list):
        raise ValueError("O pacote contém uma lista de anexos inválida.")
    assets: list[dict[str, str]] = []
    for asset in raw_assets:
        if not isinstance(asset, dict):
            raise ValueError("O pacote contém um anexo inválido.")
        relative = _portable_relative(
            asset.get("relative_path"), prefixes=("assets/",), label="um anexo"
        )
        package_path = _portable_relative(
            asset.get("package_path"), prefixes=("assets/",), label="um anexo"
        )
        digest = str(asset.get("sha256") or "").strip().casefold()
        if not _HEX64_RE.match(digest):
            raise ValueError(
                f"O pacote contém um anexo sem hash válido: {package_path.as_posix()}"
            )
        if relative.as_posix() != package_path.as_posix():
            raise ValueError(
                "O pacote contém um anexo com caminhos divergentes: "
                f"{relative.as_posix()} / {package_path.as_posix()}"
            )
        assets.append({
            "relative_path": relative.as_posix(),
            "package_path": package_path.as_posix(),
            "sha256": digest,
        })
    try:
        confidence = float(record.get("classification_confidence") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("O pacote contém uma confiança de classificação inválida.") from exc
    return {
        "source": source,
        "source_origin": source_origin,
        "source_id": source_id,
        "title": title,
        "url": str(record.get("url") or ""),
        "module": module,
        "classification_confidence": confidence,
        "review_status": review_status,
        "status": status,
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
        "synced_at": str(record.get("synced_at") or ""),
        "revision": str(record.get("revision") or ""),
        "content_hash": content_hash or computed_hash,
        "category": str(record.get("category") or ""),
        "product": str(record.get("product") or ""),
        "markdown": markdown,
        "document_path": document_path.as_posix(),
        "local_path": local_path,
        "assets": assets,
    }


def _parse_records(payload: bytes) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("A lista de documentos do pacote é inválida.") from exc
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"A lista de documentos do pacote é inválida (linha {number})."
            ) from exc
        if not isinstance(record, dict):
            raise ValueError(
                f"A lista de documentos do pacote é inválida (linha {number})."
            )
        records.append(_validated_record(record))
    if not records:
        raise ValueError("O pacote não contém documentos de conhecimento.")
    return records


def _load_package(
    source_archive: str | Path,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]], dict[str, zipfile.ZipInfo]]:
    archive_path = Path(source_archive).expanduser()
    try:
        resolved = archive_path.resolve(strict=True)
    except OSError:
        raise ValueError(f"Arquivo não encontrado: {archive_path}") from None
    if resolved.suffix.casefold() != ".zip" or not zipfile.is_zipfile(resolved):
        raise ValueError("O arquivo selecionado não é um pacote ZIP válido.")
    with zipfile.ZipFile(resolved) as archive:
        entries: dict[str, zipfile.ZipInfo] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            if _archive_entry_is_symlink(info):
                raise ValueError("O pacote contém uma entrada simbólica não suportada.")
            name = _validate_zip_entry_name(info.filename, label="entrada")
            if name in entries:
                raise ValueError(f"O pacote contém entradas duplicadas: {name}")
            entries[name] = info
        if KNOWLEDGE_PACKAGE_MANIFEST not in entries:
            raise ValueError("O pacote não contém o manifesto de exportação na raiz.")
        try:
            manifest = json.loads(
                archive.read(KNOWLEDGE_PACKAGE_MANIFEST).decode("utf-8")
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("O manifesto do pacote é inválido.") from exc
        if not isinstance(manifest, dict):
            raise ValueError("O manifesto do pacote é inválido.")
        if str(manifest.get("format") or "") != KNOWLEDGE_PACKAGE_FORMAT:
            raise ValueError("O arquivo não é um pacote de conhecimento VRStudio.")
        if int(manifest.get("schema_version") or 0) != KNOWLEDGE_PACKAGE_SCHEMA_VERSION:
            raise ValueError("A versão do pacote de conhecimento não é suportada.")
        if not str(manifest.get("package_id") or "").strip():
            raise ValueError("O pacote não informa um identificador.")
        if KNOWLEDGE_RECORDS_FILE not in entries:
            raise ValueError("O pacote não contém os documentos de conhecimento.")
        payload = archive.read(KNOWLEDGE_RECORDS_FILE)
        expected = str(manifest.get("records_sha256") or "").strip().casefold()
        if (
            not _HEX64_RE.match(expected)
            or hashlib.sha256(payload).hexdigest() != expected
        ):
            raise ValueError("A lista de documentos do pacote está corrompida.")
        records = _parse_records(payload)

        document_count = int(manifest.get("document_count") or 0)
        if document_count != len(records):
            raise ValueError("A contagem de documentos do pacote é inconsistente.")
        asset_paths: set[str] = set()
        asset_bytes = 0
        document_bytes = 0
        for record in records:
            if record["document_path"] not in entries:
                raise ValueError(
                    f"O pacote não contém o documento: {record['document_path']}"
                )
            document = _document_from_record(record)
            document_bytes += len(canonical_markdown(document).encode("utf-8"))
            for asset in record["assets"]:
                package_path = asset["package_path"]
                if package_path not in entries:
                    raise ValueError(f"O pacote não contém o anexo: {package_path}")
                if package_path not in asset_paths:
                    asset_paths.add(package_path)
                    asset_bytes += entries[package_path].file_size
        if len(asset_paths) != int(manifest.get("asset_count") or 0):
            raise ValueError("A contagem de anexos do pacote é inconsistente.")
        if int(manifest.get("document_bytes") or 0) != document_bytes:
            raise ValueError("O tamanho dos documentos do pacote é inconsistente.")
        if int(manifest.get("asset_bytes") or 0) != asset_bytes:
            raise ValueError("O tamanho dos anexos do pacote é inconsistente.")
        if int(manifest.get("total_bytes") or 0) != document_bytes + asset_bytes:
            raise ValueError("O tamanho total do pacote é inconsistente.")
        if int(manifest.get("file_count") or 0) != len(records) + len(asset_paths):
            raise ValueError("A contagem de arquivos do pacote é inconsistente.")
    return resolved, manifest, records, entries


def detect_knowledge_package_archive(
    source_archive: str | Path,
    *,
    database: MaryDatabase | None = None,
) -> dict[str, Any]:
    """Validate a knowledge package ZIP without mutating anything."""
    try:
        resolved, manifest, records, _entries = _load_package(source_archive)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return _package_error(str(exc))

    origin_counts: dict[tuple[str, str], dict[str, int]] = {}
    for record in records:
        pair = (record["source"], record["source_origin"])
        stats = origin_counts.setdefault(pair, {"documents": 0, "assets": 0})
        stats["documents"] += 1
        stats["assets"] += len(record["assets"])
    preview: list[dict[str, Any]] = []
    if database is not None:
        for record in records[:_MAX_PREVIEW]:
            try:
                current = database.get_document(
                    record["source"], record["source_id"]
                )
            except Exception:
                current = None
            preview.append({
                "source": record["source"],
                "source_origin": record["source_origin"],
                "source_id": record["source_id"],
                "title": record["title"],
                "module": record["module"],
                "review_status": record["review_status"],
                "action": "update" if current is not None else "new",
            })
    return {
        "is_valid": True,
        "knowledge_package": True,
        "scope": "knowledge",
        "source_archive": str(resolved),
        "package_id": str(manifest.get("package_id") or ""),
        "suggested_name": str(manifest.get("package_id") or ""),
        "exported_at": str(manifest.get("exported_at") or ""),
        "origins": [
            {
                "source": source,
                "source_origin": source_origin,
                "label": origin_label(source, source_origin),
                "documents": stats["documents"],
                "assets": stats["assets"],
            }
            for (source, source_origin), stats in sorted(origin_counts.items())
        ],
        "modules": sorted({record["module"] for record in records}),
        "document_count": len(records),
        "asset_count": int(manifest.get("asset_count") or 0),
        "total_bytes": int(manifest.get("total_bytes") or 0),
        "missing_asset_count": int(manifest.get("missing_asset_count") or 0),
        "manifest": manifest,
        "preview": preview,
    }


def _document_from_record(record: dict[str, Any]) -> KnowledgeDocument:
    return KnowledgeDocument(
        source=str(record["source"]),
        source_origin=str(record["source_origin"]),
        source_id=str(record["source_id"]),
        title=str(record["title"]),
        url=str(record["url"]),
        markdown=str(record["markdown"]),
        module=str(record["module"]),
        classification_confidence=float(record["classification_confidence"]),
        review_status=str(record["review_status"]),
        status=str(record["status"]),
        created_at=str(record["created_at"]),
        updated_at=str(record["updated_at"]),
        synced_at=str(record["synced_at"]),
        revision=str(record["revision"]),
        content_hash=str(record["content_hash"]),
        category=str(record["category"]),
        product=str(record["product"]),
        assets=[str(asset["relative_path"]) for asset in record["assets"]],
        local_path=str(record.get("local_path") or ""),
    )


def import_knowledge_package_archive(
    workspace: str | Path,
    source_archive: str | Path,
    *,
    mode: str = "merge",
    origins: Iterable[Any] | None = None,
    database: MaryDatabase | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Import a knowledge package, merging or restoring local documents.

    Every record and asset hash is verified before the first write, so a
    corrupted package never leaves partial state.  ``merge`` preserves local
    approved/kept modules through :func:`preserve_validated_classification`
    and re-queues reviews exactly like the sync flows; ``restore`` writes the
    package module/review_status verbatim.
    """
    selected_mode = str(mode or "merge").strip().casefold()
    if selected_mode not in IMPORT_MODES:
        raise ValueError("Modo de importação inválido.")
    resolved, manifest, records, entries = _load_package(source_archive)
    workspace_root = Path(workspace).resolve(strict=True)
    db = database or MaryDatabase(
        workspace_root / "indice" / "conhecimento.sqlite",
        root=workspace_root,
        backup_portable_migration=False,
    )
    origin_filter = _normalize_origins(origins) if origins else None
    if origin_filter is not None:
        records = [
            record
            for record in records
            if (record["source"], record["source_origin"]) in origin_filter
        ]
        if not records:
            raise ValueError(
                "Nenhum documento do pacote corresponde às origens selecionadas."
            )

    asset_entries: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(resolved) as archive:
        verified: dict[str, str] = {}
        for record in records:
            for asset in record["assets"]:
                package_path = asset["package_path"]
                asset_entries.setdefault(package_path, asset)
                digest = verified.get(package_path)
                if digest is None:
                    content = archive.read(entries[package_path].filename)
                    digest = hashlib.sha256(content).hexdigest()
                    verified[package_path] = digest
                if digest != asset["sha256"]:
                    raise ValueError(
                        f"O anexo do pacote está corrompido: {package_path}"
                    )

    total_units = len(records) + len(asset_entries)
    current_units = 0
    written_assets: set[str] = set()
    counts = {"created": 0, "updated": 0, "unchanged": 0, "review_queued": 0}
    errors: list[dict[str, str]] = []
    error_count = 0

    def _report() -> None:
        if progress is not None:
            progress({"current": current_units, "total": total_units})

    with zipfile.ZipFile(resolved) as archive:
        _report()
        for record in records:
            try:
                for asset in record["assets"]:
                    package_path = asset["package_path"]
                    if package_path in written_assets:
                        continue
                    content = archive.read(entries[package_path].filename)
                    target = _resolve_within(
                        workspace_root, asset["relative_path"]
                    )
                    if not target.is_file() or target.read_bytes() != content:
                        _write_bytes_atomic(target, content)
                    written_assets.add(package_path)
                    current_units += 1
                    if current_units % _PROGRESS_REPORT_INTERVAL == 0:
                        _report()
                document = _document_from_record(record)
                current_row = db.get_document(document.source, document.source_id)
                validated_module_changed = False
                if selected_mode == "merge":
                    validated_module_changed = preserve_validated_classification(
                        current_row, document
                    )
                document_id, action = write_and_persist_document(
                    workspace_root,
                    document,
                    lambda: db.upsert_document(
                        document,
                        preserve_local_review=selected_mode == "merge",
                    ),
                    previous_path=current_row["local_path"] if current_row else None,
                )
                if selected_mode == "merge" and (
                    document.review_status != "approved"
                    or validated_module_changed
                ):
                    result = classify(
                        document.title,
                        document.markdown,
                        document.category,
                        document.product,
                    )
                    queued = db.queue_review(
                        document_id,
                        result.module,
                        result.confidence,
                        result.reasons,
                        str(current_row["module"]) if current_row else "",
                        validated_module_changed,
                    )
                    counts["review_queued"] += int(queued)
                counts[action] += 1
            except Exception as exc:
                error_count += 1
                if len(errors) < MAX_ERROR_DETAILS:
                    errors.append({
                        "source": str(record["source"]),
                        "source_origin": str(record["source_origin"]),
                        "source_id": str(record["source_id"]),
                        "title": str(record["title"]),
                        "error": str(exc),
                    })
            current_units += 1
            if current_units % _PROGRESS_REPORT_INTERVAL == 0:
                _report()

    if progress is not None:
        progress({"current": total_units, "total": total_units})
    export_catalog(db, workspace_root / "indice")

    return {
        "success": True,
        "package_id": str(manifest.get("package_id") or ""),
        "mode": selected_mode,
        "document_count": len(records),
        "asset_count": len(asset_entries),
        "created": counts["created"],
        "updated": counts["updated"],
        "unchanged": counts["unchanged"],
        "review_queued": counts["review_queued"],
        "error_count": error_count,
        "errors": errors,
    }

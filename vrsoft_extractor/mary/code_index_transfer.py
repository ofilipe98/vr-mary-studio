"""Hash-verified offline transfer for release-scoped ERP code indexes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .code_index import CODE_INDEX_SCHEMA_VERSION, JavaCodeIndex, _code_source_key
from .erp_releases import ErpReleaseCatalog, sha256_file
from .jvm_batches import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_CLASSES,
    PROCESSING_SCHEMA_VERSION,
    DecompilationBatchStore,
)


TRANSFER_SCHEMA_VERSION = 1
PACKAGE_MANIFEST = "index-package.json"
PACKAGE_PAYLOAD = "code-sources.jsonl"


class CodeIndexTransferError(RuntimeError):
    """Controlled integrity, identity, or portability failure."""


class CodeIndexTransfer:
    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        store: DecompilationBatchStore | None = None,
        code_index: JavaCodeIndex | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.store = store or DecompilationBatchStore(self.root)
        self.code_index = code_index or JavaCodeIndex(
            self.root, catalog=self.catalog, store=self.store
        )

    def export_release(
        self,
        release_id: str,
        destination: str | Path,
    ) -> dict[str, Any]:
        manifest = self.catalog.load_manifest(release_id)
        status = self.catalog.status(release_id, full_hash=True)
        if status.get("freshness") != "fresh" or manifest.get("state") != "ready":
            raise CodeIndexTransferError(
                "A release precisa estar pronta e fresca para exportar o índice."
            )
        self.code_index.initialize()
        coverage = self.code_index.coverage(release_id)
        covered_jars = [str(item) for item in coverage.get("covered_jars") or []]
        if not covered_jars:
            raise CodeIndexTransferError("A release ainda não possui JAR indexado.")
        artifacts = {
            str(item.get("relative_path") or ""): str(item.get("sha256") or "")
            for item in manifest.get("artifacts") or []
            if isinstance(item, dict) and item.get("relative_path")
        }
        selected_artifacts = [
            {"relative_path": jar, "sha256": artifacts[jar]}
            for jar in covered_jars
        ]
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise CodeIndexTransferError(
                "O pacote de destino já existe; nenhum arquivo foi sobrescrito."
            )
        target.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="vr-index-export-", dir=str(target.parent)
        ) as temporary_dir:
            payload_path = Path(temporary_dir) / PACKAGE_PAYLOAD
            source_count = self._write_payload(release_id, payload_path)
            payload_hash = sha256_file(payload_path)
            exported_at = _utc_now()
            package_identity = {
                "schema_version": TRANSFER_SCHEMA_VERSION,
                "release_id": release_id,
                "release_manifest_sha256": manifest["release_manifest_sha256"],
                "code_index_schema_version": CODE_INDEX_SCHEMA_VERSION,
                "processing_schema_version": PROCESSING_SCHEMA_VERSION,
                "payload_sha256": payload_hash,
                "payload_size_bytes": payload_path.stat().st_size,
                "source_count": source_count,
                "covered_artifacts": selected_artifacts,
            }
            package_id = hashlib.sha256(
                json.dumps(
                    package_identity,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            package_manifest = {
                **package_identity,
                "package_id": package_id,
                "exported_at": exported_at,
                "requires_network": False,
                "requires_model": False,
                "contains_source_jars": False,
            }
            staging = target.with_name(f".{target.name}.tmp")
            try:
                with zipfile.ZipFile(
                    staging, "w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    archive.writestr(
                        PACKAGE_MANIFEST,
                        json.dumps(
                            package_manifest,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                    )
                    archive.write(payload_path, PACKAGE_PAYLOAD)
                staging.replace(target)
            finally:
                staging.unlink(missing_ok=True)
        return {
            **package_manifest,
            "path": str(target),
            "package_size_bytes": target.stat().st_size,
        }

    def import_package(
        self,
        package_path: str | Path,
        *,
        release_id: str = "",
    ) -> dict[str, Any]:
        package = Path(package_path).expanduser().resolve()
        if not package.is_file():
            raise CodeIndexTransferError(f"Pacote não encontrado: {package}")
        try:
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                if names != {PACKAGE_MANIFEST, PACKAGE_PAYLOAD}:
                    raise CodeIndexTransferError(
                        "O pacote deve conter somente manifesto e payload do índice."
                    )
                manifest_info = archive.getinfo(PACKAGE_MANIFEST)
                if manifest_info.file_size > 1024 * 1024:
                    raise CodeIndexTransferError("Manifesto do pacote excede 1 MB.")
                package_manifest = json.loads(archive.read(PACKAGE_MANIFEST).decode("utf-8"))
                if not isinstance(package_manifest, dict):
                    raise CodeIndexTransferError("Manifesto do pacote inválido.")
                self._validate_package_manifest(package_manifest)
                selected_release = str(
                    release_id or package_manifest.get("release_id") or ""
                ).strip()
                if selected_release != str(package_manifest.get("release_id") or ""):
                    raise CodeIndexTransferError(
                        "O release_id local deve ser igual ao release_id assinado no pacote."
                    )
                local_manifest = self.catalog.load_manifest(selected_release)
                local_status = self.catalog.status(selected_release, full_hash=True)
                if local_status.get("freshness") != "fresh":
                    raise CodeIndexTransferError(
                        "A release local mudou; o pacote não será importado."
                    )
                if (
                    local_manifest.get("release_manifest_sha256")
                    != package_manifest.get("release_manifest_sha256")
                ):
                    raise CodeIndexTransferError(
                        "O hash da release local não corresponde ao pacote."
                    )
                self._validate_artifacts(local_manifest, package_manifest)
                payload_info = archive.getinfo(PACKAGE_PAYLOAD)
                declared_size = int(
                    package_manifest.get("payload_size_bytes") or -1
                )
                if payload_info.file_size != declared_size:
                    raise CodeIndexTransferError(
                        "O tamanho do payload não corresponde ao manifesto do pacote."
                    )
                self.catalog.paths.code_index.mkdir(parents=True, exist_ok=True)
                if declared_size > shutil.disk_usage(self.root).free:
                    raise CodeIndexTransferError(
                        "Espaço em disco insuficiente para verificar o pacote."
                    )
                with tempfile.TemporaryDirectory(
                    prefix="vr-index-import-",
                    dir=str(self.catalog.paths.code_index),
                ) as temporary_dir:
                    payload_path = Path(temporary_dir) / PACKAGE_PAYLOAD
                    digest = hashlib.sha256()
                    actual_size = 0
                    with archive.open(PACKAGE_PAYLOAD) as source, payload_path.open(
                        "wb"
                    ) as target:
                        while chunk := source.read(4 * 1024 * 1024):
                            actual_size += len(chunk)
                            digest.update(chunk)
                            target.write(chunk)
                    if actual_size != declared_size:
                        raise CodeIndexTransferError(
                            "O tamanho extraído não corresponde ao manifesto do pacote."
                        )
                    if digest.hexdigest() != package_manifest.get("payload_sha256"):
                        raise CodeIndexTransferError(
                            "O SHA-256 do payload não corresponde ao manifesto do pacote."
                        )
                    self.code_index.initialize()
                    imported, unchanged = self._import_payload(
                        selected_release,
                        str(package_manifest["release_manifest_sha256"]),
                        str(package_manifest["package_id"]),
                        payload_path,
                        expected_source_count=int(
                            package_manifest.get("source_count") or 0
                        ),
                        covered_artifacts={
                            str(item["relative_path"]): str(item["sha256"])
                            for item in package_manifest["covered_artifacts"]
                        },
                    )
        except CodeIndexTransferError:
            raise
        except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
            raise CodeIndexTransferError(
                f"Pacote de índice inválido: {type(exc).__name__}: {exc}"
            ) from exc

        self._record_imported_coverage(selected_release, package_manifest)
        return {
            "schema_version": TRANSFER_SCHEMA_VERSION,
            "package_id": package_manifest["package_id"],
            "release_id": selected_release,
            "release_manifest_sha256": package_manifest[
                "release_manifest_sha256"
            ],
            "imported_sources": imported,
            "unchanged_sources": unchanged,
            "covered_jar_count": len(package_manifest["covered_artifacts"]),
            "verified": True,
            "requires_network": False,
            "requires_model": False,
        }

    def _write_payload(self, release_id: str, path: Path) -> int:
        count = 0
        with self.store.connect() as connection, path.open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            sources = connection.execute(
                """SELECT * FROM code_sources
                   WHERE release_id = ? AND schema_version = ? ORDER BY id""",
                (release_id, CODE_INDEX_SCHEMA_VERSION),
            )
            for source in sources:
                symbols = [
                    dict(item)
                    for item in connection.execute(
                        """SELECT kind, simple_name, qualified_name, signature,
                                  visibility, line_start
                           FROM code_symbols WHERE source_id = ? ORDER BY id""",
                        (source["id"],),
                    )
                ]
                relations = [
                    dict(item)
                    for item in connection.execute(
                        """SELECT kind, target, source_symbol, confidence, line_start
                           FROM code_relations WHERE source_id = ? ORDER BY id""",
                        (source["id"],),
                    )
                ]
                record = {
                    key: source[key]
                    for key in (
                        "class_version",
                        "jar_relative_path",
                        "artifact_sha256",
                        "source_relative_path",
                        "source_sha256",
                        "package_name",
                        "primary_type",
                        "qualified_name",
                        "logical_names_json",
                        "content_hashes_json",
                        "occurrence_count",
                        "parser_kind",
                        "syntax_error_count",
                        "symbols_text",
                        "body",
                    )
                }
                record["symbols"] = symbols
                record["relations"] = relations
                stream.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                )
                count += 1
        return count

    @staticmethod
    def _validate_package_manifest(package_manifest: dict[str, Any]) -> None:
        if int(package_manifest.get("schema_version") or 0) != TRANSFER_SCHEMA_VERSION:
            raise CodeIndexTransferError("Versão do pacote de índice incompatível.")
        if int(package_manifest.get("code_index_schema_version") or 0) != CODE_INDEX_SCHEMA_VERSION:
            raise CodeIndexTransferError("Schema do índice de código incompatível.")
        if int(package_manifest.get("processing_schema_version") or 0) != PROCESSING_SCHEMA_VERSION:
            raise CodeIndexTransferError("Schema de processamento incompatível.")
        if not package_manifest.get("package_id") or not package_manifest.get(
            "payload_sha256"
        ):
            raise CodeIndexTransferError("Manifesto do pacote incompleto.")
        identity = {
            key: package_manifest.get(key)
            for key in (
                "schema_version",
                "release_id",
                "release_manifest_sha256",
                "code_index_schema_version",
                "processing_schema_version",
                "payload_sha256",
                "payload_size_bytes",
                "source_count",
                "covered_artifacts",
            )
        }
        expected_package_id = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if expected_package_id != package_manifest.get("package_id"):
            raise CodeIndexTransferError("A assinatura hash do pacote é inválida.")

    @staticmethod
    def _validate_artifacts(
        local_manifest: dict[str, Any],
        package_manifest: dict[str, Any],
    ) -> None:
        local = {
            str(item.get("relative_path") or ""): str(item.get("sha256") or "")
            for item in local_manifest.get("artifacts") or []
            if isinstance(item, dict)
        }
        covered = package_manifest.get("covered_artifacts")
        if not isinstance(covered, list) or not covered:
            raise CodeIndexTransferError("O pacote não declara JARs cobertos.")
        for item in covered:
            if not isinstance(item, dict):
                raise CodeIndexTransferError("Artefato inválido no pacote.")
            relative_path = str(item.get("relative_path") or "")
            digest = str(item.get("sha256") or "")
            if local.get(relative_path) != digest:
                raise CodeIndexTransferError(
                    f"O artefato local não corresponde ao pacote: {relative_path}"
                )

    def _import_payload(
        self,
        release_id: str,
        release_hash: str,
        package_id: str,
        payload_path: Path,
        *,
        expected_source_count: int,
        covered_artifacts: dict[str, str],
    ) -> tuple[int, int]:
        imported = 0
        unchanged = 0
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            with payload_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    imported, unchanged = self._import_record(
                        connection,
                        line_number,
                        line,
                        release_id=release_id,
                        release_hash=release_hash,
                        package_id=package_id,
                        covered_artifacts=covered_artifacts,
                        imported=imported,
                        unchanged=unchanged,
                    )
            if imported + unchanged != max(0, int(expected_source_count)):
                raise CodeIndexTransferError(
                    "A quantidade de fontes não corresponde ao manifesto do pacote."
                )
            connection.commit()
        return imported, unchanged

    @staticmethod
    def _import_record(
        connection: sqlite3.Connection,
        line_number: int,
        line: str,
        *,
        release_id: str,
        release_hash: str,
        package_id: str,
        covered_artifacts: dict[str, str],
        imported: int,
        unchanged: int,
    ) -> tuple[int, int]:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise CodeIndexTransferError(
                        f"Registro inválido no payload, linha {line_number}."
                    ) from exc
                if not isinstance(record, dict):
                    raise CodeIndexTransferError(
                        f"Registro inválido no payload, linha {line_number}."
                    )
                jar_relative_path = str(record.get("jar_relative_path") or "")
                artifact_sha256 = str(record.get("artifact_sha256") or "")
                if covered_artifacts.get(jar_relative_path) != artifact_sha256:
                    raise CodeIndexTransferError(
                        f"Fonte fora dos artefatos cobertos, linha {line_number}."
                    )
                body = str(record.get("body") or "")
                if hashlib.sha256(body.encode("utf-8")).hexdigest() != str(
                    record.get("source_sha256") or ""
                ):
                    raise CodeIndexTransferError(
                        f"Fonte com SHA-256 inválido, linha {line_number}."
                    )
                content_hashes = json.loads(
                    str(record.get("content_hashes_json") or "[]")
                )
                source_key = _code_source_key(
                    release_id=release_id,
                    release_hash=release_hash,
                    artifact_sha256=str(record.get("artifact_sha256") or ""),
                    class_version=int(record.get("class_version") or 0),
                    qualified_name=str(record.get("qualified_name") or ""),
                    content_hashes=content_hashes,
                )
                if connection.execute(
                    "SELECT 1 FROM code_sources WHERE source_key = ?", (source_key,)
                ).fetchone():
                    unchanged += 1
                    return imported, unchanged
                cursor = connection.execute(
                    """INSERT INTO code_sources
                       (source_key, schema_version, release_id, release_hash,
                        jar_relative_path, artifact_sha256, batch_id,
                        class_version, tool, output_reference,
                        source_relative_path, source_sha256, package_name,
                        primary_type, qualified_name, logical_names_json,
                        content_hashes_json, occurrence_count, parser_kind,
                        syntax_error_count, symbols_text, body, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'imported', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_key,
                        CODE_INDEX_SCHEMA_VERSION,
                        release_id,
                        release_hash,
                        jar_relative_path,
                        artifact_sha256,
                        f"import-{package_id[:24]}",
                        int(record.get("class_version") or 0),
                        str(record.get("source_relative_path") or ""),
                        str(record.get("source_sha256") or ""),
                        str(record.get("package_name") or ""),
                        str(record.get("primary_type") or ""),
                        str(record.get("qualified_name") or ""),
                        str(record.get("logical_names_json") or "[]"),
                        str(record.get("content_hashes_json") or "[]"),
                        int(record.get("occurrence_count") or 0),
                        str(record.get("parser_kind") or "structural_fallback"),
                        int(record.get("syntax_error_count") or 0),
                        str(record.get("symbols_text") or ""),
                        body,
                        _utc_now(),
                    ),
                )
                source_id = int(cursor.lastrowid)
                symbols = record.get("symbols") or []
                relations = record.get("relations") or []
                if not isinstance(symbols, list) or not isinstance(relations, list):
                    raise CodeIndexTransferError(
                        f"Símbolos/relações inválidos, linha {line_number}."
                    )
                connection.executemany(
                    """INSERT INTO code_symbols
                       (source_id, kind, simple_name, qualified_name, signature,
                        visibility, line_start) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            source_id,
                            str(item.get("kind") or ""),
                            str(item.get("simple_name") or ""),
                            str(item.get("qualified_name") or ""),
                            str(item.get("signature") or ""),
                            str(item.get("visibility") or ""),
                            int(item.get("line_start") or 0),
                        )
                        for item in symbols
                        if isinstance(item, dict)
                    ],
                )
                connection.executemany(
                    """INSERT INTO code_relations
                       (source_id, kind, target, source_symbol, confidence, line_start)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            source_id,
                            str(item.get("kind") or ""),
                            str(item.get("target") or ""),
                            str(item.get("source_symbol") or ""),
                            float(item.get("confidence") or 0.0),
                            int(item.get("line_start") or 0),
                        )
                        for item in relations
                        if isinstance(item, dict)
                    ],
                )
                imported += 1
                return imported, unchanged

    def _record_imported_coverage(
        self,
        release_id: str,
        package_manifest: dict[str, Any],
    ) -> None:
        package_id = str(package_manifest["package_id"])
        plan_id = "import-" + hashlib.sha256(
            f"{release_id}:{package_id}".encode("utf-8")
        ).hexdigest()
        now = _utc_now()
        artifacts = list(package_manifest["covered_artifacts"])
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO decompilation_plans
                   (plan_id, schema_version, release_id, release_hash, state,
                    max_classes, max_bytes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?)""",
                (
                    plan_id,
                    PROCESSING_SCHEMA_VERSION,
                    release_id,
                    package_manifest["release_manifest_sha256"],
                    DEFAULT_MAX_CLASSES,
                    DEFAULT_MAX_BYTES,
                    now,
                    now,
                ),
            )
            connection.executemany(
                """INSERT OR IGNORE INTO plan_artifacts
                   (plan_id, ordinal, relative_path, artifact_sha256)
                   VALUES (?, ?, ?, ?)""",
                [
                    (
                        plan_id,
                        ordinal,
                        str(item["relative_path"]),
                        str(item["sha256"]),
                    )
                    for ordinal, item in enumerate(artifacts)
                ],
            )
            connection.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = ["CodeIndexTransfer", "CodeIndexTransferError"]

"""Versioned ERP JAR inventory used by VR code analysis.

This module deliberately stops before decompilation.  It establishes the
release identity, provenance and freshness guarantees that every later code
index and worker query must inherit.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


MANIFEST_SCHEMA_VERSION = 1
DEFAULT_EXPECTED_JAR_COUNT = 46
DEFAULT_MAX_RELEASES = 3
DEFAULT_STORAGE_BUDGET_MULTIPLIER = 10
_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ErpReleaseError(RuntimeError):
    """Controlled failure while importing or managing an ERP release."""


@dataclass(frozen=True)
class ErpReleasePaths:
    root: Path

    @property
    def source_releases(self) -> Path:
        return self.root / "ERP" / "releases"

    @property
    def code_index(self) -> Path:
        return self.root / "indice" / "codigo"

    @property
    def indexed_releases(self) -> Path:
        return self.code_index / "releases"

    @property
    def artifacts(self) -> Path:
        return self.code_index / "artifacts"

    def source_for(self, release_id: str) -> Path:
        return self.source_releases / release_id / "jars"

    def index_for(self, release_id: str) -> Path:
        return self.indexed_releases / release_id

    def manifest_for(self, release_id: str) -> Path:
        return self.index_for(release_id) / "manifest.json"


class ErpReleaseCatalog:
    """Import, validate and safely remove versioned ERP JAR inventories."""

    def __init__(
        self,
        root: str | Path,
        expected_jar_count: int = DEFAULT_EXPECTED_JAR_COUNT,
        max_releases: int = DEFAULT_MAX_RELEASES,
        storage_budget_multiplier: int = DEFAULT_STORAGE_BUDGET_MULTIPLIER,
    ) -> None:
        self.paths = ErpReleasePaths(Path(root).resolve())
        self.expected_jar_count = max(1, int(expected_jar_count))
        self.max_releases = max(1, int(max_releases))
        self.storage_budget_multiplier = max(1, int(storage_budget_multiplier))

    def ensure_dirs(self) -> None:
        for path in (
            self.paths.source_releases,
            self.paths.indexed_releases,
            self.paths.artifacts,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def import_release(
        self,
        release_id: str,
        source_dir: str | Path | None = None,
        *,
        source_origin_dir: str | Path | None = None,
        analysis_scope: str | None = None,
    ) -> dict[str, Any]:
        release_id = validate_release_id(release_id)
        source = Path(source_dir or self.paths.source_for(release_id)).resolve()
        if not source.is_dir():
            raise ErpReleaseError(f"Pasta da release não encontrada: {source}")

        self.ensure_dirs()
        indexed = {
            path.name
            for path in self.paths.indexed_releases.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        }
        if release_id not in indexed and len(indexed) >= self.max_releases:
            raise ErpReleaseError(
                f"O limite de {self.max_releases} releases indexadas foi atingido; "
                "remova uma delas com aprovação antes de importar outra."
            )
        jar_paths = sorted(
            (
                path
                for path in source.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".jar"
            ),
            key=lambda path: path.relative_to(source).as_posix().casefold(),
        )
        if not jar_paths:
            raise ErpReleaseError(f"Nenhum JAR encontrado em: {source}")

        artifacts: list[dict[str, Any]] = []
        class_owners: dict[str, str] = {}
        duplicate_classes: set[str] = set()
        class_names: list[str] = []
        warnings: list[str] = []

        for jar_path in jar_paths:
            relative_path = jar_path.relative_to(source).as_posix()
            artifact, names = self._inventory_jar(jar_path, relative_path)
            artifacts.append(artifact)
            class_names.extend(names)
            for class_name in names:
                previous = class_owners.setdefault(class_name, relative_path)
                if previous != relative_path:
                    duplicate_classes.add(class_name)
            self._write_artifact_metadata(artifact)

        invalid_count = sum(1 for item in artifacts if item.get("error"))
        if len(artifacts) != self.expected_jar_count:
            warnings.append(
                f"Esperados {self.expected_jar_count} JARs, encontrados {len(artifacts)}."
            )
        if invalid_count:
            warnings.append(f"{invalid_count} JAR(s) não puderam ser inspecionados.")
        if duplicate_classes:
            warnings.append(
                f"{len(duplicate_classes)} classe(s) aparecem em mais de um JAR; "
                "a ordem do classpath precisa ser confirmada."
            )

        classpath_declarations = [
            {
                "jar": item["relative_path"],
                "entries": item["manifest_class_path"],
            }
            for item in artifacts
            if item.get("manifest_class_path")
        ]
        release_hash = aggregate_release_hash(artifacts)
        ready = len(artifacts) == self.expected_jar_count and invalid_count == 0
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "release_id": release_id,
            "release_manifest_sha256": release_hash,
            "indexed_at": _utc_now(),
            "source_dir": self._portable_path(source),
            "source_origin_dir": self._portable_path(
                Path(source_origin_dir).resolve()
                if source_origin_dir is not None
                else source
            ),
            "snapshot_managed": source_origin_dir is not None,
            "analysis_scope": str(
                analysis_scope
                or (
                    "full_release"
                    if self.expected_jar_count == DEFAULT_EXPECTED_JAR_COUNT
                    else "custom"
                )
            ),
            "expected_jar_count": self.expected_jar_count,
            "jar_count": len(artifacts),
            "source_size_bytes": sum(int(item["size_bytes"]) for item in artifacts),
            "state": "ready" if ready else "incomplete",
            "freshness": "fresh",
            "invalid_jar_count": invalid_count,
            "classpath_status": "partial" if classpath_declarations else "unknown",
            "classpath_order_known": False,
            "classpath_declarations": classpath_declarations,
            "duplicate_class_count": len(duplicate_classes),
            "duplicate_class_samples": sorted(duplicate_classes)[:200],
            "obfuscation": estimate_obfuscation(class_names),
            "warnings": warnings,
            "artifacts": artifacts,
        }
        _atomic_write_json(self.paths.manifest_for(release_id), manifest)
        self._write_catalog_metadata(manifest["source_size_bytes"])
        return manifest

    def snapshot_release(
        self,
        release_id: str,
        source_dir: str | Path,
        *,
        analysis_scope: str | None = None,
    ) -> dict[str, Any]:
        """Copy a complete release or one explicitly selected JAR before indexing."""

        release_id = validate_release_id(release_id)
        source = Path(source_dir).resolve()
        destination = self.paths.source_for(release_id).resolve()
        if self.paths.manifest_for(release_id).is_file():
            raise ErpReleaseError(
                "A release já está inventariada; use outro release_id para não "
                "substituir o manifesto e o índice existentes."
            )
        if source == destination:
            return self.import_release(release_id, destination)
        selected_single_jar = source.is_file()
        if selected_single_jar:
            if source.suffix.casefold() != ".jar":
                raise ErpReleaseError(f"O arquivo selecionado não é um JAR: {source}")
            if self.expected_jar_count != 1:
                raise ErpReleaseError(
                    "A análise de um arquivo exige o escopo de JAR único."
                )
            source_root = source.parent
            jar_paths = [source]
            analysis_scope = "single_jar"
        else:
            if not source.is_dir():
                raise ErpReleaseError(f"Pasta da release não encontrada: {source}")
            source_root = source
            jar_paths = sorted(
                (
                    path
                    for path in source.rglob("*")
                    if path.is_file() and path.suffix.casefold() == ".jar"
                ),
                key=lambda path: path.relative_to(source).as_posix().casefold(),
            )
        if destination.exists():
            raise ErpReleaseError(
                "O snapshot da release já existe; use outro release_id ou remova "
                "a release existente com aprovação."
            )

        self.ensure_dirs()
        indexed = {
            path.name
            for path in self.paths.indexed_releases.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        }
        if release_id not in indexed and len(indexed) >= self.max_releases:
            raise ErpReleaseError(
                f"O limite de {self.max_releases} releases indexadas foi atingido; "
                "remova uma delas com aprovação antes de importar outra."
            )

        if len(jar_paths) != self.expected_jar_count:
            raise ErpReleaseError(
                f"O snapshot exige exatamente {self.expected_jar_count} JARs; "
                    f"foram encontrados {len(jar_paths)} em {source}."
            )

        source_artifacts: list[dict[str, Any]] = []
        for jar_path in jar_paths:
            resolved = jar_path.resolve()
            _require_child(resolved, source_root)
            try:
                with zipfile.ZipFile(resolved) as archive:
                    archive.infolist()
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise ErpReleaseError(
                    f"JAR ilegível na origem: {jar_path.relative_to(source_root).as_posix()} "
                    f"({type(exc).__name__}: {exc})"
                ) from exc
            before = resolved.stat()
            digest = sha256_file(resolved)
            after = resolved.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise ErpReleaseError(
                    "Um JAR mudou durante o preflight; tente novamente quando a "
                    "atualização do ERP terminar."
                )
            source_artifacts.append(
                {
                    "path": resolved,
                    "relative_path": jar_path.relative_to(source_root),
                    "sha256": digest,
                    "size_bytes": after.st_size,
                }
            )

        release_root = destination.parent
        staging_root = self.paths.source_releases / (
            f".{release_id}.snapshot-{uuid4().hex}"
        )
        staging_jars = staging_root / "jars"
        try:
            for artifact in source_artifacts:
                target = staging_jars / artifact["relative_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(artifact["path"], target)
                if target.stat().st_size != int(artifact["size_bytes"]):
                    raise ErpReleaseError(
                        f"Tamanho divergente no snapshot: {artifact['relative_path']}"
                    )
                if sha256_file(target) != artifact["sha256"]:
                    raise ErpReleaseError(
                        f"SHA-256 divergente no snapshot: {artifact['relative_path']}"
                    )
            if release_root.exists():
                raise ErpReleaseError(
                    "A pasta gerenciada da release surgiu durante o snapshot; "
                    "nenhum arquivo existente foi sobrescrito."
                )
            staging_root.replace(release_root)
        except Exception:
            if staging_root.is_dir():
                shutil.rmtree(staging_root)
            raise

        manifest = self.import_release(
            release_id,
            destination,
            source_origin_dir=source,
            analysis_scope=analysis_scope,
        )
        manifest["snapshot"] = {
            "created_at": manifest["indexed_at"],
            "source_dir": self._portable_path(source),
            "destination_dir": self._portable_path(destination),
            "jar_count": len(source_artifacts),
            "source_size_bytes": sum(
                int(item["size_bytes"]) for item in source_artifacts
            ),
            "verified": True,
        }
        _atomic_write_json(self.paths.manifest_for(release_id), manifest)
        return manifest

    def status(self, release_id: str, *, full_hash: bool = False) -> dict[str, Any]:
        manifest = self.load_manifest(release_id)
        source = self._resolve_source(str(manifest.get("source_dir") or ""))
        result = {
            "release_id": manifest["release_id"],
            "state": manifest.get("state", "incomplete"),
            "freshness": "fresh",
            "release_manifest_sha256": manifest.get("release_manifest_sha256", ""),
            "indexed_at": manifest.get("indexed_at", ""),
            "source_dir": str(manifest.get("source_dir") or ""),
            "jar_count": manifest.get("jar_count", 0),
            "expected_jar_count": manifest.get("expected_jar_count", 0),
            "analysis_scope": manifest.get("analysis_scope", "full_release"),
            "warnings": list(manifest.get("warnings") or []),
        }
        if not source.is_dir():
            result["freshness"] = "missing"
            result["warnings"].append("A pasta de origem da release não existe mais.")
            return result

        expected = {
            str(item["relative_path"]): item
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        }
        current = {
            path.relative_to(source).as_posix(): path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".jar"
        }
        if set(expected) != set(current):
            result["freshness"] = "stale"
            result["warnings"].append("A lista de JARs mudou depois da indexação.")
            return result

        changed: list[str] = []
        for relative_path, jar_path in current.items():
            previous = expected[relative_path]
            stat = jar_path.stat()
            metadata_changed = (
                int(previous.get("size_bytes", -1)) != stat.st_size
                or int(previous.get("modified_ns", -1)) != stat.st_mtime_ns
            )
            if full_hash:
                metadata_changed = sha256_file(jar_path) != previous.get("sha256")
            if metadata_changed:
                changed.append(relative_path)
        if changed:
            result["freshness"] = "stale"
            result["changed_jars"] = changed
            result["warnings"].append(
                f"{len(changed)} JAR(s) mudaram depois da indexação."
            )
        return result

    def list_statuses(self, *, full_hash: bool = False) -> list[dict[str, Any]]:
        if not self.paths.indexed_releases.is_dir():
            return []
        statuses: list[dict[str, Any]] = []
        paths = sorted(
            self.paths.indexed_releases.iterdir(),
            key=lambda item: item.name.casefold(),
        )
        for path in paths:
            if path.is_dir() and (path / "manifest.json").is_file():
                try:
                    statuses.append(self.status(path.name, full_hash=full_hash))
                except (ErpReleaseError, OSError, ValueError) as exc:
                    statuses.append(
                        {
                            "release_id": path.name,
                            "state": "failed",
                            "freshness": "unknown",
                            "warnings": [str(exc)],
                        }
                    )
        return statuses

    def storage_status(self) -> dict[str, Any]:
        """Report the generated-index quota without counting source JAR folders."""

        catalog_path = self.paths.code_index / "catalog.json"
        payload: dict[str, Any] = {}
        if catalog_path.is_file():
            try:
                payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                payload = {}
        used = _directory_size(self.paths.code_index) if self.paths.code_index.is_dir() else 0
        budget = int(payload.get("storage_budget_bytes") or 0)
        return {
            "used_bytes": used,
            "budget_bytes": budget,
            "remaining_bytes": max(0, budget - used) if budget else 0,
            "usage_ratio": round(used / budget, 6) if budget else 0.0,
            "max_releases": int(payload.get("max_releases") or self.max_releases),
            "indexed_releases": len(self.list_statuses()),
        }

    def set_storage_budget_multiplier(self, multiplier: int) -> dict[str, Any]:
        """Update the generated-index budget without touching source JARs."""

        selected = int(multiplier)
        if selected < 1 or selected > DEFAULT_STORAGE_BUDGET_MULTIPLIER:
            raise ErpReleaseError(
                "O limite de disco deve ficar entre 1x e "
                f"{DEFAULT_STORAGE_BUDGET_MULTIPLIER}x o tamanho da release."
            )
        self.storage_budget_multiplier = selected
        baseline = 0
        catalog_path = self.paths.code_index / "catalog.json"
        if catalog_path.is_file():
            try:
                payload = json.loads(catalog_path.read_text(encoding="utf-8"))
                baseline = int(payload.get("baseline_source_size_bytes") or 0)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                baseline = 0
        if baseline <= 0:
            manifests = [
                self.load_manifest(str(item.get("release_id") or ""))
                for item in self.list_statuses()
                if item.get("release_id")
            ]
            baseline = max(
                (int(item.get("source_size_bytes") or 0) for item in manifests),
                default=0,
            )
        self.ensure_dirs()
        _atomic_write_json(
            catalog_path,
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "max_releases": self.max_releases,
                "storage_budget_multiplier": selected,
                "baseline_source_size_bytes": baseline,
                "storage_budget_bytes": baseline * selected,
                "updated_at": _utc_now(),
            },
        )
        return self.storage_status()

    def inspect_class_metrics(
        self,
        release_id: str,
        relative_jars: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Measure class-level deduplication before committing to decompilation."""

        manifest = self.load_manifest(release_id)
        source = self._resolve_source(str(manifest.get("source_dir") or ""))
        if not source.is_dir():
            raise ErpReleaseError("A pasta de origem da release não está disponível.")
        artifacts = {
            str(item.get("relative_path") or ""): item
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        }
        requested = tuple(dict.fromkeys(str(item).replace("\\", "/") for item in relative_jars))
        selected = requested or tuple(sorted(artifacts, key=str.casefold))
        missing = [item for item in selected if item not in artifacts]
        if missing:
            raise ErpReleaseError(
                "JARs não encontrados no manifesto: " + ", ".join(missing)
            )

        started = time.monotonic()
        content_hashes: set[str] = set()
        logical_classes: dict[str, list[Any]] = {}
        conflict_samples: list[dict[str, str]] = []
        total_entries = 0
        total_bytecode_bytes = 0
        multi_release_entries = 0
        errors: list[dict[str, str]] = []
        per_jar: list[dict[str, Any]] = []

        for relative_path in selected:
            jar_path = (source / relative_path).resolve()
            _require_child(jar_path, source.resolve())
            jar_entries = 0
            jar_bytes = 0
            jar_hashes: set[str] = set()
            try:
                with zipfile.ZipFile(jar_path) as archive:
                    for info in archive.infolist():
                        normalized = normalize_class_entry(info.filename)
                        if normalized is None:
                            continue
                        logical_name, class_version = normalized
                        digest = hashlib.sha256()
                        with archive.open(info) as handle:
                            while chunk := handle.read(1024 * 1024):
                                digest.update(chunk)
                        class_hash = digest.hexdigest()
                        total_entries += 1
                        jar_entries += 1
                        total_bytecode_bytes += info.file_size
                        jar_bytes += info.file_size
                        if class_version:
                            multi_release_entries += 1
                        content_hashes.add(class_hash)
                        jar_hashes.add(class_hash)

                        current = logical_classes.get(logical_name)
                        if current is None:
                            logical_classes[logical_name] = [
                                class_hash,
                                relative_path,
                                1,
                                False,
                            ]
                        else:
                            current[2] += 1
                            if class_hash != current[0]:
                                if not current[3] and len(conflict_samples) < 200:
                                    conflict_samples.append(
                                        {
                                            "class": logical_name,
                                            "first_jar": str(current[1]),
                                            "first_sha256": str(current[0]),
                                            "conflicting_jar": relative_path,
                                            "conflicting_sha256": class_hash,
                                        }
                                    )
                                current[3] = True
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                errors.append(
                    {"jar": relative_path, "error": f"{type(exc).__name__}: {exc}"}
                )
            per_jar.append(
                {
                    "jar": relative_path,
                    "class_entries": jar_entries,
                    "unique_content_hashes": len(jar_hashes),
                    "class_bytecode_bytes": jar_bytes,
                }
            )

        duplicate_logical_names = sum(
            1 for value in logical_classes.values() if int(value[2]) > 1
        )
        conflicting_logical_names = sum(
            1 for value in logical_classes.values() if bool(value[3])
        )
        report = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "release_id": release_id,
            "release_manifest_sha256": manifest.get("release_manifest_sha256", ""),
            "inspected_at": _utc_now(),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "selected_jars": list(selected),
            "selected_jar_count": len(selected),
            "total_class_entries": total_entries,
            "unique_logical_class_count": len(logical_classes),
            "duplicate_logical_class_count": duplicate_logical_names,
            "conflicting_logical_class_count": conflicting_logical_names,
            "unique_class_content_count": len(content_hashes),
            "duplicate_content_entries": max(0, total_entries - len(content_hashes)),
            "multi_release_entries": multi_release_entries,
            "class_bytecode_bytes": total_bytecode_bytes,
            "conflict_samples": conflict_samples,
            "errors": errors,
            "per_jar": per_jar,
        }
        _atomic_write_json(
            self.paths.index_for(release_id) / "class-metrics.json",
            report,
        )
        return report

    def load_manifest(self, release_id: str) -> dict[str, Any]:
        release_id = validate_release_id(release_id)
        path = self.paths.manifest_for(release_id)
        if not path.is_file():
            raise ErpReleaseError(f"Release ainda não indexada: {release_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ErpReleaseError(f"Manifesto inválido da release {release_id}.") from exc
        if payload.get("release_id") != release_id:
            raise ErpReleaseError("O manifesto não corresponde à pasta da release.")
        return payload

    def remove_index(self, release_id: str, *, approved: bool = False) -> dict[str, Any]:
        """Remove only generated index data, never the manually supplied JARs."""

        release_id = validate_release_id(release_id)
        if not approved:
            raise ErpReleaseError("A remoção do índice exige aprovação explícita.")
        release_dir = self.paths.index_for(release_id).resolve()
        _require_child(release_dir, self.paths.indexed_releases.resolve())
        if not release_dir.is_dir():
            raise ErpReleaseError(f"Índice da release não encontrado: {release_id}")

        manifest = self.load_manifest(release_id)
        candidate_hashes = {
            str(item.get("sha256") or "")
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and _HASH_RE.fullmatch(str(item.get("sha256") or ""))
        }
        reclaimed = _directory_size(release_dir)
        shared_release_hash = any(
            str(item.get("release_id") or "") != release_id
            and str(item.get("release_manifest_sha256") or "")
            == str(manifest.get("release_manifest_sha256") or "")
            for item in self.list_statuses()
        )
        processing = self._purge_release_processing_data(
            release_id,
            preserve_occurrences=shared_release_hash,
        )
        reclaimed += int(processing["reclaimed_bytes"])
        shutil.rmtree(release_dir)

        referenced = self._referenced_artifact_hashes()
        removed_artifacts = 0
        for artifact_hash in sorted(candidate_hashes - referenced):
            artifact_dir = (self.paths.artifacts / artifact_hash).resolve()
            _require_child(artifact_dir, self.paths.artifacts.resolve())
            if artifact_dir.is_dir():
                reclaimed += _directory_size(artifact_dir)
                shutil.rmtree(artifact_dir)
                removed_artifacts += 1
        return {
            "release_id": release_id,
            "removed": True,
            "removed_artifacts": removed_artifacts,
            "removed_search_sources": processing["removed_search_sources"],
            "removed_processing_plans": processing["removed_processing_plans"],
            "preserved_shared_decompilation_dirs": processing[
                "preserved_shared_decompilation_dirs"
            ],
            "reclaimed_bytes": reclaimed,
            "source_jars_removed": False,
        }

    def _purge_release_processing_data(
        self,
        release_id: str,
        *,
        preserve_occurrences: bool,
    ) -> dict[str, int]:
        database_path = self.paths.code_index / "processing.sqlite"
        if not database_path.is_file():
            return {
                "removed_search_sources": 0,
                "removed_processing_plans": 0,
                "preserved_shared_decompilation_dirs": 0,
                "reclaimed_bytes": 0,
            }
        plan_ids: list[str] = []
        removed_sources = 0
        remaining_references: list[str] = []
        connection = sqlite3.connect(database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "decompilation_plans" not in tables:
                return {
                    "removed_search_sources": 0,
                    "removed_processing_plans": 0,
                    "preserved_shared_decompilation_dirs": 0,
                    "reclaimed_bytes": 0,
                }
            plan_ids = [
                str(row["plan_id"])
                for row in connection.execute(
                    "SELECT plan_id FROM decompilation_plans WHERE release_id = ?",
                    (release_id,),
                )
            ]
            connection.execute("BEGIN IMMEDIATE")
            if "code_sources" in tables:
                removed_sources = int(
                    connection.execute(
                        "SELECT count(*) FROM code_sources WHERE release_id = ?",
                        (release_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    "DELETE FROM code_sources WHERE release_id = ?", (release_id,)
                )
            if plan_ids:
                placeholders = ",".join("?" for _ in plan_ids)
                connection.execute(
                    f"""DELETE FROM batch_members WHERE batch_id IN
                         (SELECT batch_id FROM decompilation_batches
                          WHERE plan_id IN ({placeholders}))""",
                    plan_ids,
                )
                connection.execute(
                    f"DELETE FROM decompilation_batches WHERE plan_id IN ({placeholders})",
                    plan_ids,
                )
                connection.execute(
                    f"DELETE FROM plan_artifacts WHERE plan_id IN ({placeholders})",
                    plan_ids,
                )
                connection.execute(
                    f"DELETE FROM decompilation_plans WHERE plan_id IN ({placeholders})",
                    plan_ids,
                )
            if "class_occurrences" in tables and not preserve_occurrences:
                connection.execute(
                    "DELETE FROM class_occurrences WHERE release_id = ?", (release_id,)
                )
            if "class_contents" in tables and "class_occurrences" in tables:
                connection.execute(
                    """DELETE FROM class_contents
                       WHERE NOT EXISTS (
                         SELECT 1 FROM class_occurrences o
                         WHERE o.content_sha256 = class_contents.content_sha256
                       )"""
                )
                remaining_references = [
                    str(row["output_reference"])
                    for row in connection.execute(
                        """SELECT DISTINCT output_reference FROM class_contents
                           WHERE output_reference != ''"""
                    )
                ]
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        reclaimed = 0
        preserved = 0
        decompilation_root = (self.paths.code_index / "decompilation").resolve()
        for plan_id in plan_ids:
            plan_dir = (decompilation_root / plan_id).resolve()
            _require_child(plan_dir, decompilation_root)
            relative = self._portable_path(plan_dir).replace("\\", "/").rstrip("/")
            shared = any(
                reference.replace("\\", "/").startswith(relative + "/")
                for reference in remaining_references
            )
            if shared:
                preserved += 1
            elif plan_dir.is_dir():
                reclaimed += _directory_size(plan_dir)
                shutil.rmtree(plan_dir)
        return {
            "removed_search_sources": removed_sources,
            "removed_processing_plans": len(plan_ids),
            "preserved_shared_decompilation_dirs": preserved,
            "reclaimed_bytes": reclaimed,
        }

    def _inventory_jar(
        self, jar_path: Path, relative_path: str
    ) -> tuple[dict[str, Any], list[str]]:
        before = jar_path.stat()
        digest = sha256_file(jar_path)
        after = jar_path.stat()
        error = ""
        class_names: list[str] = []
        manifest: dict[str, str] = {}
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            error = "O arquivo mudou durante a importação."
        else:
            try:
                with zipfile.ZipFile(jar_path) as archive:
                    members = archive.namelist()
                    class_names = sorted(
                        name[:-6].replace("/", ".")
                        for name in members
                        if name.endswith(".class") and not name.endswith("/")
                    )
                    manifest_name = next(
                        (name for name in members if name.casefold() == "meta-inf/manifest.mf"),
                        "",
                    )
                    if manifest_name:
                        manifest = parse_manifest_bytes(archive.read(manifest_name))
            except (OSError, RuntimeError, zipfile.BadZipFile, KeyError) as exc:
                error = f"{type(exc).__name__}: {exc}"

        artifact = {
            "relative_path": relative_path,
            "sha256": digest,
            "size_bytes": after.st_size,
            "modified_ns": after.st_mtime_ns,
            "class_count": len(class_names),
            "manifest_main_class": manifest.get("Main-Class", ""),
            "manifest_implementation_version": manifest.get(
                "Implementation-Version", ""
            ),
            "manifest_class_path": manifest.get("Class-Path", "").split(),
            "error": error,
        }
        return artifact, class_names

    def _write_artifact_metadata(self, artifact: dict[str, Any]) -> None:
        artifact_hash = str(artifact["sha256"])
        destination = self.paths.artifacts / artifact_hash / "artifact.json"
        if destination.is_file():
            return
        portable = {
            key: value
            for key, value in artifact.items()
            if key not in {"relative_path", "modified_ns"}
        }
        portable["schema_version"] = MANIFEST_SCHEMA_VERSION
        portable["created_at"] = _utc_now()
        _atomic_write_json(destination, portable)

    def _write_catalog_metadata(self, source_size_bytes: int) -> None:
        path = self.paths.code_index / "catalog.json"
        baseline = int(source_size_bytes)
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                baseline = max(
                    baseline,
                    int(existing.get("baseline_source_size_bytes") or 0),
                )
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                pass
        _atomic_write_json(
            path,
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "max_releases": self.max_releases,
                "storage_budget_multiplier": self.storage_budget_multiplier,
                "baseline_source_size_bytes": baseline,
                "storage_budget_bytes": baseline * self.storage_budget_multiplier,
                "updated_at": _utc_now(),
            },
        )

    def _referenced_artifact_hashes(self) -> set[str]:
        referenced: set[str] = set()
        if not self.paths.indexed_releases.is_dir():
            return referenced
        for path in self.paths.indexed_releases.glob("*/manifest.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            for item in payload.get("artifacts", []):
                value = str(item.get("sha256") or "") if isinstance(item, dict) else ""
                if _HASH_RE.fullmatch(value):
                    referenced.add(value)
        return referenced

    def _portable_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.paths.root).as_posix()
        except ValueError:
            return str(path.resolve())

    def _resolve_source(self, value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else self.paths.root / path).resolve()


def validate_release_id(value: str) -> str:
    release_id = str(value or "").strip()
    if not _RELEASE_ID_RE.fullmatch(release_id):
        raise ErpReleaseError(
            "Identificador de release inválido; use letras, números, ponto, "
            "hífen ou underscore."
        )
    return release_id


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_release_hash(artifacts: Iterable[dict[str, Any]]) -> str:
    identity = [
        {
            "relative_path": str(item["relative_path"]),
            "sha256": str(item["sha256"]),
            "size_bytes": int(item["size_bytes"]),
        }
        for item in artifacts
    ]
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_manifest_bytes(value: bytes) -> dict[str, str]:
    text = value.decode("utf-8", errors="replace").replace("\r\n", "\n")
    unfolded: list[str] = []
    for line in text.split("\n"):
        if line.startswith(" ") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    parsed: dict[str, str] = {}
    for line in unfolded:
        key, separator, raw = line.partition(":")
        if separator and key.strip():
            parsed[key.strip()] = raw.lstrip()
    return parsed


def estimate_obfuscation(class_names: Iterable[str]) -> dict[str, Any]:
    names = []
    for qualified in class_names:
        simple = qualified.rsplit(".", 1)[-1].split("$", 1)[0]
        if simple not in {"module-info", "package-info"}:
            names.append(simple)
    if not names:
        return {"status": "inconclusive", "class_count": 0, "short_name_ratio": 0.0}
    short = sum(1 for name in names if len(name) <= 2)
    ratio = short / len(names)
    status = "probable" if ratio >= 0.40 else "possible" if ratio >= 0.15 else "not_detected"
    return {
        "status": status,
        "class_count": len(names),
        "short_name_ratio": round(ratio, 4),
        "method": "heuristic_class_name_length",
    }


def normalize_class_entry(value: str) -> tuple[str, int] | None:
    normalized = str(value or "").replace("\\", "/")
    if not normalized.casefold().endswith(".class"):
        return None
    class_version = 0
    match = re.match(
        r"^META-INF/versions/(\d+)/(.*\.class)$",
        normalized,
        re.IGNORECASE,
    )
    if match:
        class_version = int(match.group(1))
        normalized = match.group(2)
    logical_name = normalized[:-6].replace("/", ".")
    return logical_name, class_version


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _require_child(path: Path, parent: Path) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ErpReleaseError("Destino calculado fora do índice de código.") from exc


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

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
import warnings
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .apps_catalog import AppsCatalogStore


warnings.filterwarnings(
    "ignore",
    message=r"Overlapped entries: .*possible zip bomb.*",
    category=UserWarning,
)


MANIFEST_SCHEMA_VERSION = 1
DEFAULT_EXPECTED_JAR_COUNT = 46
DEFAULT_MAX_RELEASES = 0  # App versions are independent of the number of package origins.
DEFAULT_STORAGE_BUDGET_MULTIPLIER = 10
_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_VR_VERSION_KEYS = (
    "versao.major",
    "versao.minor",
    "versao.release",
    "versao.build",
    "versao.beta",
    "app.data",
)


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
    def apps_catalog(self) -> Path:
        return self.code_index / "apps_catalog.json"

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
        self.max_releases = max(0, int(max_releases))
        self.storage_budget_multiplier = max(1, int(storage_budget_multiplier))
        self.apps_store = AppsCatalogStore(self.paths.root, self.paths.apps_catalog)

    def ensure_dirs(self) -> None:
        for path in (
            self.paths.source_releases,
            self.paths.indexed_releases,
            self.paths.artifacts,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def detect_package(self, source_dir: str | Path) -> dict[str, Any]:
        """Read only application release metadata from JAR-local properties."""

        source = Path(source_dir).resolve()
        if source.is_file():
            if source.suffix.casefold() != ".jar":
                raise ErpReleaseError(f"O arquivo selecionado não é um JAR: {source}")
            source_root = source.parent
            jar_paths = [source]
        elif source.is_dir():
            source_root = source
            jar_paths = self._source_jars(source)
        else:
            raise ErpReleaseError(f"Origem dos JARs não encontrada: {source}")
        if not jar_paths:
            raise ErpReleaseError(f"Nenhum JAR encontrado em: {source}")

        components: list[dict[str, Any]] = []
        seen_applications: dict[str, str] = {}
        duplicate_applications: list[str] = []
        for jar_path in jar_paths:
            identity = detect_jar_release(jar_path)
            relative = jar_path.relative_to(source_root).as_posix()
            identity["source_relative_path"] = relative
            identity["source_path"] = self._portable_path(jar_path)
            application_key = str(identity["application_key"])
            previous = seen_applications.setdefault(application_key, relative)
            if previous != relative:
                duplicate_applications.append(str(identity["application"]))
            components.append(identity)

        if duplicate_applications:
            raise ErpReleaseError(
                "O pacote contém mais de um JAR para a mesma aplicação: "
                + ", ".join(sorted(set(duplicate_applications), key=str.casefold))
                + ". Separe os pacotes antes de importar."
            )
        detected_count = sum(bool(item.get("version_detected")) for item in components)
        latest_date = max(
            (str(item.get("application_date_iso") or "") for item in components),
            default="",
        )
        identity_hash = package_identity_hash(components)
        if len(components) == 1:
            suggested_release_id = component_release_id(components[0], identity_hash)
        else:
            date_label = latest_date.replace("-", ".") if latest_date else "sem-data"
            suggested_release_id = validate_release_id(
                f"erp-{date_label}-{identity_hash[:8]}"
            )
        return {
            "source_dir": self._portable_path(source),
            "jar_count": len(components),
            "expected_jar_count": self.expected_jar_count,
            "complete": len(components) == self.expected_jar_count,
            "partial": len(components) < self.expected_jar_count,
            "detected_version_count": detected_count,
            "fallback_count": len(components) - detected_count,
            "latest_application_date": latest_date,
            "package_identity_sha256": identity_hash,
            "suggested_release_id": suggested_release_id,
            "components": components,
        }

    def count_source_jars(self, source_dir: str | Path) -> int:
        source = Path(source_dir).resolve()
        if source.is_file():
            return int(source.suffix.casefold() == ".jar")
        return len(self._source_jars(source)) if source.is_dir() else 0

    def _source_jars(self, source: Path) -> list[Path]:
        """List input JARs without re-importing managed snapshots below releases/."""

        source = source.resolve()
        managed_root = self.paths.source_releases.resolve()
        paths: list[Path] = []
        for path in source.rglob("*"):
            if not path.is_file() or path.suffix.casefold() != ".jar":
                continue
            relative = path.relative_to(source)
            if source == managed_root:
                parts = relative.parts
                if len(parts) >= 3 and parts[1].casefold() == "jars":
                    continue
                if parts and parts[0].startswith("."):
                    continue
            paths.append(path)
        return sorted(
            paths,
            key=lambda path: path.relative_to(source).as_posix().casefold(),
        )

    def import_release(
        self,
        release_id: str,
        source_dir: str | Path | None = None,
        *,
        source_origin_dir: str | Path | None = None,
        analysis_scope: str | None = None,
        expected_jar_count: int | None = None,
    ) -> dict[str, Any]:
        release_id = validate_release_id(release_id)
        effective_expected_count = max(
            1,
            int(
                self.expected_jar_count
                if expected_jar_count is None
                else expected_jar_count
            ),
        )
        source = Path(source_dir or self.paths.source_for(release_id)).resolve()
        if not source.is_dir():
            raise ErpReleaseError(f"Pasta da release não encontrada: {source}")

        self.ensure_dirs()
        indexed = {
            path.name
            for path in self.paths.indexed_releases.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        }
        if self.max_releases and release_id not in indexed and len(indexed) >= self.max_releases:
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
        if len(artifacts) != effective_expected_count:
            warnings.append(
                f"Esperados {effective_expected_count} JARs, encontrados {len(artifacts)}."
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
        partial_scope = str(analysis_scope or "") == "partial_release"
        count_is_accepted = len(artifacts) == effective_expected_count or (
            partial_scope and len(artifacts) < effective_expected_count
        )
        ready = count_is_accepted and invalid_count == 0
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
                    if effective_expected_count == DEFAULT_EXPECTED_JAR_COUNT
                    else "custom"
                )
            ),
            "expected_jar_count": effective_expected_count,
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
        self.apps_store.register_package(manifest, package_id=release_id)
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
        if self.max_releases and release_id not in indexed and len(indexed) >= self.max_releases:
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

        try:
            manifest = self.import_release(
                release_id,
                destination,
                source_origin_dir=source,
                analysis_scope=analysis_scope,
            )
        except Exception:
            _require_child(release_root, self.paths.source_releases)
            if release_root.is_dir():
                shutil.rmtree(release_root)
            raise
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

    def snapshot_detected_release(
        self,
        source_dir: str | Path,
        *,
        release_id: str = "",
        base_release_id: str = "",
        analysis_scope: str | None = None,
    ) -> dict[str, Any]:
        """Create a categorized snapshot, composing partial VR update packages."""

        source = Path(source_dir).resolve()
        package = self.detect_package(source)
        single_jar = source.is_file() or analysis_scope == "single_jar"
        package_components = list(package["components"])
        source_root = source.parent if source.is_file() else source
        provided: dict[str, dict[str, Any]] = {}
        for component in package_components:
            jar_path = (source_root / str(component["source_relative_path"])).resolve()
            _require_child(jar_path, source_root)
            before = jar_path.stat()
            digest = sha256_file(jar_path)
            after = jar_path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise ErpReleaseError(
                    "Um JAR mudou durante a detecção; tente novamente quando a "
                    "atualização do ERP terminar."
                )
            key = str(component["application_key"])
            provided[key] = {
                "component": component,
                "path": jar_path,
                "sha256": digest,
                "size_bytes": after.st_size,
                "origin": "package",
                "source_release_id": "",
            }

        base_manifest: dict[str, Any] | None = None
        combined: dict[str, dict[str, Any]] = {}
        if not single_jar and base_release_id:
            base_manifest = self._complete_base_manifest(base_release_id)
            base_applications = {
                str(item.get("application_key") or "")
                for item in (base_manifest or {}).get("artifacts") or []
                if isinstance(item, dict) and item.get("application_key")
            }
            unknown_applications = sorted(set(provided) - base_applications)
            if unknown_applications:
                raise ErpReleaseError(
                    "O pacote incremental contém aplicações ausentes da base: "
                    + ", ".join(unknown_applications)
                    + "."
                )
        if base_manifest is not None:
            base_source = self._resolve_source(str(base_manifest.get("source_dir") or ""))
            if not base_source.is_dir():
                raise ErpReleaseError(
                    f"A base completa {base_manifest['release_id']} não está disponível."
                )
            for artifact in base_manifest.get("artifacts") or []:
                if not isinstance(artifact, dict) or not artifact.get("relative_path"):
                    continue
                base_jar = (base_source / str(artifact["relative_path"])).resolve()
                _require_child(base_jar, base_source)
                if not base_jar.is_file():
                    raise ErpReleaseError(
                        "A base completa perdeu o JAR: " + str(artifact["relative_path"])
                    )
                component = _component_from_artifact(artifact, base_jar)
                key = str(component["application_key"])
                combined[key] = {
                    "component": component,
                    "path": base_jar,
                    "sha256": str(artifact.get("sha256") or sha256_file(base_jar)),
                    "size_bytes": int(artifact.get("size_bytes") or base_jar.stat().st_size),
                    "origin": "base",
                    "source_release_id": str(base_manifest["release_id"]),
                }
        combined.update(provided)

        expected = 1 if single_jar else (
            int(base_manifest.get("jar_count") or 0)
            if base_manifest is not None
            else self.expected_jar_count
        )
        if base_manifest is not None and len(combined) != expected:
            raise ErpReleaseError(
                f"A composição deveria resultar em {expected} aplicações/JARs; "
                f"resultou em {len(combined)}. Verifique aplicações novas ou ausentes."
            )
        if base_manifest is None and not single_jar and len(combined) > expected:
            raise ErpReleaseError(
                f"O pacote completo admite {expected} aplicações/JARs; "
                f"foram encontradas {len(combined)}."
            )

        categorized: list[dict[str, Any]] = []
        for item in combined.values():
            target_relative = categorized_jar_path(
                item["component"],
                item["path"].name,
            ).as_posix()
            categorized.append({**item, "target_relative_path": target_relative})
        categorized.sort(key=lambda item: item["target_relative_path"].casefold())
        composite_hash = aggregate_release_hash(
            {
                "relative_path": item["target_relative_path"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
            for item in categorized
        )
        if release_id:
            selected_release_id = validate_release_id(release_id)
        elif single_jar:
            selected_release_id = validate_release_id(
                f"{component_release_id(categorized[0]['component'])}-{composite_hash[:8]}"
            )
        else:
            latest_date = str(package.get("latest_application_date") or "")
            date_label = latest_date.replace("-", ".") if latest_date else "sem-data"
            selected_release_id = validate_release_id(
                f"erp-{date_label}-{composite_hash[:8]}"
            )

        existing_manifest = self.paths.manifest_for(selected_release_id)
        if existing_manifest.is_file():
            existing = self.load_manifest(selected_release_id)
            if str(existing.get("release_manifest_sha256") or "") == composite_hash:
                return existing
            raise ErpReleaseError(
                f"A release {selected_release_id} já existe com outro conteúdo."
            )
        self.ensure_dirs()
        indexed = {
            path.name
            for path in self.paths.indexed_releases.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        }
        if self.max_releases and selected_release_id not in indexed and len(indexed) >= self.max_releases:
            raise ErpReleaseError(
                f"O limite de {self.max_releases} releases indexadas foi atingido; "
                "remova uma delas com aprovação antes de importar outra."
            )

        destination = self.paths.source_for(selected_release_id).resolve()
        release_root = destination.parent
        if release_root.exists():
            raise ErpReleaseError(
                f"A pasta da release já existe e não será sobrescrita: {release_root}"
            )
        staging_root = self.paths.source_releases / (
            f".{selected_release_id}.snapshot-{uuid4().hex}"
        )
        staging_jars = staging_root / "jars"
        materialization: list[dict[str, str]] = []
        try:
            for item in categorized:
                target = staging_jars / item["target_relative_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                # A snapshot must remain immutable even if an updater edits a
                # source JAR in place. Hard links would violate that guarantee.
                shutil.copy2(item["path"], target)
                method = "copy"
                if target.stat().st_size != int(item["size_bytes"]):
                    raise ErpReleaseError(
                        f"Tamanho divergente no snapshot: {item['target_relative_path']}"
                    )
                if sha256_file(target) != item["sha256"]:
                    raise ErpReleaseError(
                        f"SHA-256 divergente no snapshot: {item['target_relative_path']}"
                    )
                materialization.append(
                    {"jar": item["target_relative_path"], "method": method}
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

        effective_scope = (
            "single_jar"
            if single_jar
            else "incremental_release"
            if base_manifest is not None
            else "full_release"
            if len(combined) == expected
            else "partial_release"
        )
        try:
            manifest = self.import_release(
                selected_release_id,
                destination,
                source_origin_dir=source,
                analysis_scope=effective_scope,
                expected_jar_count=expected,
            )
        except Exception:
            _require_child(release_root, self.paths.source_releases)
            if release_root.is_dir():
                shutil.rmtree(release_root)
            raise
        provenance = {
            str(item["component"]["application_key"]): item for item in categorized
        }
        for artifact in manifest.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            item = provenance.get(str(artifact.get("application_key") or ""))
            if item:
                artifact["provenance"] = {
                    "origin": item["origin"],
                    "source_release_id": item["source_release_id"],
                    "package_source": self._portable_path(source),
                    "source_relative_path": str(item["component"].get("source_relative_path") or ""),
                }
        warnings = list(manifest.get("warnings") or [])
        warnings.extend(
            str(item["component"].get("warning") or "")
            for item in categorized
            if item["component"].get("warning")
        )
        if base_manifest is not None:
            warnings.append(
                f"Pacote incremental composto sobre a base {base_manifest['release_id']}; "
                f"{len(provided)} aplicação(ões) atualizada(s)."
            )
        manifest.update(
            {
                "release_manifest_sha256": composite_hash,
                "auto_detected": True,
                "categorization": "application/version",
                "base_release_id": (
                    str(base_manifest["release_id"]) if base_manifest else ""
                ),
                "package_jar_count": len(provided),
                "updated_applications": sorted(
                    (str(item["component"]["application"]) for item in provided.values()),
                    key=str.casefold,
                ),
                "carried_forward_jar_count": len(combined) - len(provided),
                "component_versions": [
                    {
                        "application": item["component"]["application"],
                        "version": item["component"]["application_version"],
                        "properties_entry": item["component"]["version_properties_entry"],
                        "version_detected": item["component"]["version_detected"],
                        "jar": item["target_relative_path"],
                        "origin": item["origin"],
                        "source_release_id": item["source_release_id"],
                    }
                    for item in categorized
                ],
                "warnings": list(dict.fromkeys(warnings)),
                "snapshot": {
                    "created_at": manifest["indexed_at"],
                    "source_dir": self._portable_path(source),
                    "destination_dir": self._portable_path(destination),
                    "package_jar_count": len(provided),
                    "composed_jar_count": len(combined),
                    "base_release_id": (
                        str(base_manifest["release_id"]) if base_manifest else ""
                    ),
                    "hardlinked_jar_count": sum(
                        item["method"] == "hardlink" for item in materialization
                    ),
                    "copied_jar_count": sum(
                        item["method"] == "copy" for item in materialization
                    ),
                    "verified": True,
                },
            }
        )
        _atomic_write_json(self.paths.manifest_for(selected_release_id), manifest)
        self.apps_store.register_package(manifest, package_id=selected_release_id)
        return manifest

    def _complete_base_manifest(self, release_id: str = "") -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        if release_id:
            candidates = [self.load_manifest(validate_release_id(release_id))]
        else:
            if self.paths.indexed_releases.is_dir():
                for path in self.paths.indexed_releases.glob("*/manifest.json"):
                    try:
                        candidates.append(
                            json.loads(path.read_text(encoding="utf-8"))
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        continue
            candidates.sort(
                key=lambda item: str(item.get("indexed_at") or ""),
                reverse=True,
            )
        for manifest in candidates:
            scope = str(manifest.get("analysis_scope") or "full_release")
            jar_count = int(manifest.get("jar_count") or 0)
            if (
                str(manifest.get("state") or "") == "ready"
                and scope == "full_release"
                and jar_count > 0
                and jar_count == self.expected_jar_count
                and int(manifest.get("invalid_jar_count") or 0) == 0
            ):
                return manifest
        requested = f" {release_id}" if release_id else ""
        raise ErpReleaseError(
            "Nenhuma release-base completa"
            + requested
            + " está disponível. Importe primeiro o pacote com todos os JARs."
        )

    @property
    def apps_catalog_store(self) -> AppsCatalogStore:
        return self.apps_store

    def ensure_apps_catalog_synced(self) -> None:
        if any(self.paths.indexed_releases.glob("*/manifest.json")):
            self.apps_store.sync_legacy_releases()

    def list_applications(self) -> list[dict[str, Any]]:
        self.ensure_apps_catalog_synced()
        return self.apps_store.list_applications()

    def get_application(self, app_id: str) -> dict[str, Any] | None:
        self.ensure_apps_catalog_synced()
        return self.apps_store.get_application(app_id)

    def list_versions(self, app_id: str) -> list[dict[str, Any]]:
        self.ensure_apps_catalog_synced()
        return self.apps_store.list_versions(app_id)

    def get_version(self, app_id: str, version: str) -> dict[str, Any] | None:
        self.ensure_apps_catalog_synced()
        return self.apps_store.get_version(app_id, version)

    def list_variants(self, app_id: str, version: str) -> list[dict[str, Any]]:
        self.ensure_apps_catalog_synced()
        return self.apps_store.list_variants(app_id, version)

    def get_variant(self, app_id: str, version: str, variant_id: str) -> dict[str, Any] | None:
        self.ensure_apps_catalog_synced()
        return self.apps_store.get_variant(app_id, version, variant_id)

    def list_packages(self) -> list[dict[str, Any]]:
        self.ensure_apps_catalog_synced()
        return self.apps_store.list_packages()

    def get_package(self, package_id: str) -> dict[str, Any] | None:
        self.ensure_apps_catalog_synced()
        return self.apps_store.get_package(package_id)

    def unlink_package(self, package_id: str, *, delete_data: bool = False) -> dict[str, Any]:
        pkg_id = str(package_id or "").strip()
        if not pkg_id or _safe_component(pkg_id) != pkg_id:
            raise ErpReleaseError("Identificador de pacote inválido.")
        if not self.apps_store.get_package(pkg_id):
            raise ErpReleaseError(f"Pacote '{pkg_id}' não encontrado no catálogo.")
        if delete_data:
            targets = [
                (self.paths.code_index / "releases", pkg_id),
            ]
            directories = []
            for parent, name in targets:
                target = (parent / name).resolve()
                _require_child(target, parent.resolve())
                directories.append(target)
            self._purge_release_processing_data(pkg_id, preserve_occurrences=False)
            for directory in directories:
                if directory.is_dir():
                    shutil.rmtree(directory)

        result = self.apps_store.unlink_package(pkg_id, clean_orphaned_versions=True)
        result["deleted_data"] = delete_data
        return result

    def rename_package(self, package_id: str, new_name: str) -> dict[str, Any]:
        return self.apps_store.rename_package(package_id, new_name)

    def delete_source_jars(self, package_id: str) -> dict[str, Any]:
        selected = validate_release_id(package_id)
        manifest = self.load_manifest(selected) if self.paths.manifest_for(selected).is_file() else None
        return self.apps_store.delete_source_jars(selected, manifest=manifest)

    def override_version(
        self, app_id: str, current_version: str, manual_version: str, *, variant_id: str = ""
    ) -> dict[str, Any]:
        return self.apps_store.override_version(app_id, current_version, manual_version, variant_id=variant_id)

    def compare_versions(
        self,
        app_id: str,
        base_version: str,
        target_version: str,
        *,
        base_variant_id: str = "",
        target_variant_id: str = "",
    ) -> dict[str, Any]:
        return self.apps_store.compare_versions(
            app_id,
            base_version,
            target_version,
            base_variant_id=base_variant_id,
            target_variant_id=target_variant_id,
        )

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
        statuses.sort(
            key=lambda item: str(item.get("indexed_at") or ""),
            reverse=True,
        )
        return statuses

    def storage_status(self) -> dict[str, Any]:
        """Report quota payload separately from physical and orphaned data.

        The quota applies to registered decompilation payloads. Shared databases,
        manifests and audit files are still reported as physical overhead, but do
        not consume the same allowance again. This keeps a ``10x`` allowance from
        rejecting a first plan merely because its catalog already exists.
        """

        catalog_path = self.paths.code_index / "catalog.json"
        payload: dict[str, Any] = {}
        if catalog_path.is_file():
            try:
                payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                payload = {}
        inventory = self.inspect_orphaned_index_data()
        physical_used = (
            _directory_size(self.paths.code_index)
            if self.paths.code_index.is_dir()
            else 0
        )
        used = int(inventory["live_payload_bytes"])
        orphaned = int(inventory["orphaned_bytes"])
        overhead = max(0, physical_used - used - orphaned)
        multiplier = int(
            payload.get("storage_budget_multiplier")
            or self.storage_budget_multiplier
        )
        baseline = self._indexed_source_size_bytes()
        budget = baseline * multiplier
        return {
            "used_bytes": used,
            "budget_bytes": budget,
            "remaining_bytes": max(0, budget - used) if budget else 0,
            "usage_ratio": round(used / budget, 6) if budget else 0.0,
            "storage_budget_multiplier": multiplier,
            "baseline_source_size_bytes": baseline,
            "physical_used_bytes": physical_used,
            "orphaned_bytes": orphaned,
            "orphaned_item_count": int(inventory["orphaned_item_count"]),
            "overhead_bytes": overhead,
            "orphan_scan_errors": list(inventory["errors"]),
            "max_releases": int(payload.get("max_releases") or self.max_releases),
            "indexed_releases": len(self.list_statuses()),
        }

    def inspect_orphaned_index_data(self) -> dict[str, Any]:
        """List removable generated payload that has no live database reference."""

        decompilation_root = self.paths.code_index / "decompilation"
        artifacts_root = self.paths.artifacts
        referenced_plans: set[str] = set()
        referenced_outputs: set[str] = set()
        errors: list[str] = []
        database_path = self.paths.code_index / "processing.sqlite"
        if database_path.is_file():
            try:
                connection = sqlite3.connect(database_path, timeout=5)
                connection.row_factory = sqlite3.Row
                try:
                    tables = {
                        str(row["name"])
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if "decompilation_plans" in tables:
                        referenced_plans.update(
                            str(row["plan_id"])
                            for row in connection.execute(
                                "SELECT plan_id FROM decompilation_plans"
                            )
                            if row["plan_id"]
                        )
                    if "class_contents" in tables:
                        referenced_outputs.update(
                            str(row["output_reference"])
                            .replace("\\", "/")
                            .casefold()
                            for row in connection.execute(
                                """SELECT DISTINCT output_reference FROM class_contents
                                   WHERE output_reference != ''"""
                            )
                            if row["output_reference"]
                        )
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                errors.append(f"processing.sqlite: {exc}")

        items: list[dict[str, Any]] = []
        live_payload_bytes = 0
        decompilation_dirs = (
            sorted(decompilation_root.iterdir(), key=lambda item: item.name.casefold())
            if decompilation_root.is_dir()
            else []
        )
        for path in decompilation_dirs:
            if not path.is_dir():
                continue
            portable = self._portable_path(path).replace("\\", "/").casefold()
            referenced = path.name in referenced_plans or any(
                output == portable or output.startswith(portable + "/")
                for output in referenced_outputs
            )
            size = _directory_size(path)
            if referenced or errors:
                live_payload_bytes += size
            else:
                items.append(
                    {
                        "kind": "decompilation_plan",
                        "path": self._portable_path(path),
                        "size_bytes": size,
                    }
                )

        referenced_artifacts = self._referenced_artifact_hashes()
        artifact_dirs = (
            sorted(artifacts_root.iterdir(), key=lambda item: item.name.casefold())
            if artifacts_root.is_dir()
            else []
        )
        for path in artifact_dirs:
            if not path.is_dir() or path.name in referenced_artifacts:
                continue
            items.append(
                {
                    "kind": "artifact_metadata",
                    "path": self._portable_path(path),
                    "size_bytes": _directory_size(path),
                }
            )

        return {
            "items": items,
            "orphaned_item_count": len(items),
            "orphaned_bytes": sum(int(item["size_bytes"]) for item in items),
            "live_payload_bytes": live_payload_bytes,
            "errors": errors,
            "source_jars_included": False,
        }

    def purge_orphaned_index_data(self, *, approved: bool = False) -> dict[str, Any]:
        """Remove only generated payload proven to be unreferenced."""

        if not approved:
            raise ErpReleaseError(
                "A limpeza de artefatos órfãos exige aprovação explícita."
            )
        inspection = self.inspect_orphaned_index_data()
        if inspection["errors"]:
            raise ErpReleaseError(
                "A limpeza foi bloqueada porque as referências do índice não "
                "puderam ser verificadas: " + "; ".join(inspection["errors"])
            )
        removed: list[dict[str, Any]] = []
        for item in inspection["items"]:
            path = (self.paths.root / str(item["path"])).resolve()
            if item["kind"] == "decompilation_plan":
                _require_child(path, (self.paths.code_index / "decompilation").resolve())
            elif item["kind"] == "artifact_metadata":
                _require_child(path, self.paths.artifacts.resolve())
            else:
                continue
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(dict(item))
        return {
            "removed_items": removed,
            "removed_item_count": len(removed),
            "reclaimed_bytes": sum(int(item["size_bytes"]) for item in removed),
            "source_jars_removed": False,
            "storage": self.storage_status(),
        }

    def set_storage_budget_multiplier(
        self, multiplier: int, *, inspect_storage: bool = True
    ) -> dict[str, Any]:
        """Update the generated-index budget without touching source JARs."""

        selected = int(multiplier)
        if selected < 1 or selected > DEFAULT_STORAGE_BUDGET_MULTIPLIER:
            raise ErpReleaseError(
                "O limite de disco deve ficar entre 1x e "
                f"{DEFAULT_STORAGE_BUDGET_MULTIPLIER}x o tamanho da release."
            )
        self.storage_budget_multiplier = selected
        catalog_path = self.paths.code_index / "catalog.json"
        baseline = self._indexed_source_size_bytes()
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
        return self.storage_status() if inspect_storage else {
            "storage_budget_multiplier": selected,
            "storage_budget_bytes": baseline * selected,
        }

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
                with zipfile.ZipFile(jar_path) as archive, warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r"Overlapped entries: .*possible zip bomb.*",
                        category=UserWarning,
                    )
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

    def _resolve_current_release_id(self) -> str:
        statuses = self.list_statuses(full_hash=False)
        if not statuses:
            raise ErpReleaseError("Nenhuma release indexada encontrada.")
        return str(statuses[0]["release_id"])

    def load_manifest(self, release_id: str) -> dict[str, Any]:
        normalized = str(release_id or "").strip()
        if normalized in ("current", "") and not self.paths.manifest_for("current").is_file():
            release_id = self._resolve_current_release_id()
        else:
            release_id = validate_release_id(normalized)
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
        self._write_catalog_metadata(0)
        if self.apps_store.get_package(release_id):
            self.apps_store.unlink_package(release_id)
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
            directory = (self.paths.code_index / "decompilation" / release_id).resolve()
            _require_child(directory, (self.paths.code_index / "decompilation").resolve())
            if directory.is_dir():
                shutil.rmtree(directory)
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
            if "decompilation_plans" in tables:
                plan_ids = [
                    str(row["plan_id"])
                    for row in connection.execute(
                        "SELECT plan_id FROM decompilation_plans WHERE release_id = ?",
                        (release_id,),
                    )
                ]
            # Validate every filesystem destination before committing any deletion.
            decompilation_root = (self.paths.code_index / "decompilation").resolve()
            for plan_id in set(plan_ids + [release_id]):
                _require_child((decompilation_root / plan_id).resolve(), decompilation_root)
            if "code_symbols" in tables:
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_code_symbols_source_id ON code_symbols(source_id)"
                )
            if "code_relations" in tables:
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_code_relations_source_id ON code_relations(source_id)"
                )
            if "batch_members" in tables:
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_batch_members_occurrence ON batch_members(occurrence_id)"
                )
            if "class_occurrences" in tables:
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_occurrences_release_id ON class_occurrences(release_id)"
                )
            connection.execute("BEGIN IMMEDIATE")
            if "code_sources" in tables:
                removed_sources = int(
                    connection.execute(
                        "SELECT count(*) FROM code_sources WHERE release_id = ?",
                        (release_id,),
                    ).fetchone()[0]
                )
                if "code_relations" in tables:
                    connection.execute(
                        "DELETE FROM code_relations WHERE source_id IN (SELECT id FROM code_sources WHERE release_id = ?)",
                        (release_id,),
                    )
                if "code_symbols" in tables:
                    connection.execute(
                        "DELETE FROM code_symbols WHERE source_id IN (SELECT id FROM code_sources WHERE release_id = ?)",
                        (release_id,),
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
            if "code_sources" in tables:
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(code_sources)")}
                if "output_reference" in columns:
                    remaining_references.extend(
                        str(row[0]) for row in connection.execute(
                            "SELECT DISTINCT output_reference FROM code_sources WHERE output_reference != ''"
                        )
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        reclaimed = 0
        preserved = 0
        decompilation_root = (self.paths.code_index / "decompilation").resolve()
        remaining_set = {
            ref.replace("\\", "/").rstrip("/") for ref in remaining_references if ref
        }
        for plan_id in set(plan_ids + [release_id]):
            plan_dir = (decompilation_root / plan_id).resolve()
            _require_child(plan_dir, decompilation_root)
            relative = self._portable_path(plan_dir).replace("\\", "/").rstrip("/")
            rel_prefix = relative + "/"
            shared = any(
                ref == relative or ref.startswith(rel_prefix)
                for ref in remaining_set
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
        identity: dict[str, Any] = {
            "application": jar_path.stem,
            "application_key": _safe_component(jar_path.stem).casefold(),
            "application_version": "unknown",
            "application_date": "",
            "application_date_iso": "",
            "version_properties_entry": "",
            "version_detected": False,
            "version_components": {},
            "warning": "",
        }
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            error = "O arquivo mudou durante a importação."
        else:
            try:
                with zipfile.ZipFile(jar_path) as archive:
                    identity = _detect_jar_release_from_archive(jar_path, archive)
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
            **identity,
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
        multiplier = self.storage_budget_multiplier
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                multiplier = int(
                    existing.get("storage_budget_multiplier") or multiplier
                )
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                pass
        baseline = self._indexed_source_size_bytes()
        if baseline <= 0:
            baseline = max(0, int(source_size_bytes))
        _atomic_write_json(
            path,
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "max_releases": self.max_releases,
                "storage_budget_multiplier": multiplier,
                "baseline_source_size_bytes": baseline,
                "storage_budget_bytes": baseline * multiplier,
                "updated_at": _utc_now(),
            },
        )

    def _indexed_source_size_bytes(self) -> int:
        total = 0
        if not self.paths.indexed_releases.is_dir():
            return total
        for path in self.paths.indexed_releases.glob("*/manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                total += max(0, int(manifest.get("source_size_bytes") or 0))
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                continue
        return total

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


def parse_java_properties(value: bytes) -> dict[str, str]:
    """Parse the small, non-secret version subset used by VR properties files."""

    text = value.decode("iso-8859-1").replace("\r\n", "\n").replace("\r", "\n")
    logical_lines: list[str] = []
    pending = ""
    for raw_line in text.split("\n"):
        line = pending + raw_line
        trailing = len(line) - len(line.rstrip("\\"))
        if trailing % 2:
            pending = line[:-1]
            continue
        pending = ""
        logical_lines.append(line)
    if pending:
        logical_lines.append(pending)

    parsed: dict[str, str] = {}
    for raw_line in logical_lines:
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        match = re.match(r"^([^:=\s]+)\s*(?:[:=]|\s)\s*(.*)$", line)
        if not match:
            continue
        key = match.group(1).strip()
        if key not in _VR_VERSION_KEYS:
            continue
        parsed[key] = _decode_java_property_escapes(match.group(2).strip())
    return parsed


def detect_jar_release(path: str | Path) -> dict[str, Any]:
    """Identify the owning VR application without exposing unrelated properties."""

    jar_path = Path(path).resolve()
    try:
        with zipfile.ZipFile(jar_path) as archive:
            return _detect_jar_release_from_archive(jar_path, archive)
    except (OSError, RuntimeError, zipfile.BadZipFile, KeyError) as exc:
        raise ErpReleaseError(
            f"JAR ilegível ao detectar release: {jar_path.name} "
            f"({type(exc).__name__}: {exc})"
        ) from exc


def _detect_jar_release_from_archive(
    jar_path: Path,
    archive: zipfile.ZipFile,
) -> dict[str, Any]:
    application = jar_path.stem
    application_key = _safe_component(application).casefold()
    expected_property = f"{application.casefold()}.properties"
    property_entry = ""
    properties: dict[str, str] = {}
    candidates = sorted(
        (
            info
            for info in archive.infolist()
            if not info.is_dir()
            and Path(info.filename).name.casefold() == expected_property
        ),
        key=lambda info: ("/" in info.filename, info.filename.casefold()),
    )
    if candidates:
        selected = candidates[0]
        property_entry = selected.filename
        properties = parse_java_properties(archive.read(selected))

    components = {
        "major": properties.get("versao.major", ""),
        "minor": properties.get("versao.minor", ""),
        "release": properties.get("versao.release", ""),
        "build": properties.get("versao.build", "0"),
        "beta": properties.get("versao.beta", "0"),
    }
    required = (components["major"], components["minor"], components["release"])
    version_detected = bool(property_entry and all(required))
    version = "unknown"
    if version_detected:
        version = ".".join(
            (
                components["major"],
                components["minor"],
                components["release"],
                components["build"] or "0",
            )
        )
        if components["beta"] not in {"", "0"}:
            version += f"-beta{components['beta']}"
    raw_date = properties.get("app.data", "")
    application_date_iso = ""
    if raw_date:
        try:
            application_date_iso = datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
        except ValueError:
            application_date_iso = ""
    warning = ""
    if not property_entry:
        warning = (
            f"{jar_path.name} não possui {expected_property}; aplicação identificada "
            "pelo nome e versão diferenciada pelo SHA-256."
        )
    elif not version_detected:
        warning = f"{property_entry} não contém a versão VR completa."
    return {
        "application": application,
        "application_key": application_key,
        "application_version": version,
        "application_date": raw_date,
        "application_date_iso": application_date_iso,
        "version_properties_entry": property_entry,
        "version_detected": version_detected,
        "version_components": components,
        "warning": warning,
    }


def package_identity_hash(components: Iterable[dict[str, Any]]) -> str:
    identity = [
        {
            "application_key": str(item.get("application_key") or ""),
            "application_version": str(item.get("application_version") or "unknown"),
            "source_relative_path": str(item.get("source_relative_path") or ""),
        }
        for item in components
    ]
    encoded = json.dumps(
        sorted(identity, key=lambda item: item["application_key"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def component_release_id(component: dict[str, Any], identity_hash: str = "") -> str:
    application = _safe_component(str(component.get("application") or "jar"))
    version = _safe_component(str(component.get("application_version") or "unknown"))
    suffix = f"-{identity_hash[:8]}" if version == "unknown" and identity_hash else ""
    return validate_release_id(f"{application}-{version}{suffix}"[:80])


def categorized_jar_path(component: dict[str, Any], jar_name: str) -> Path:
    application = _safe_component(str(component.get("application") or Path(jar_name).stem))
    version = _safe_component(str(component.get("application_version") or "unknown"))
    return Path(application) / version / Path(jar_name).name


def _component_from_artifact(
    artifact: dict[str, Any],
    jar_path: Path,
) -> dict[str, Any]:
    if artifact.get("application_key") and artifact.get("application_version"):
        return {
            "application": str(artifact.get("application") or jar_path.stem),
            "application_key": str(artifact["application_key"]),
            "application_version": str(artifact["application_version"]),
            "application_date": str(artifact.get("application_date") or ""),
            "application_date_iso": str(artifact.get("application_date_iso") or ""),
            "version_properties_entry": str(
                artifact.get("version_properties_entry") or ""
            ),
            "version_detected": bool(artifact.get("version_detected")),
            "version_components": dict(artifact.get("version_components") or {}),
            "warning": str(artifact.get("warning") or ""),
        }
    return detect_jar_release(jar_path)


def _safe_component(value: str) -> str:
    cleaned = _SAFE_COMPONENT_RE.sub("-", str(value or "").strip()).strip("-._")
    return cleaned or "unknown"


def _decode_java_property_escapes(value: str) -> str:
    def replace_unicode(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    decoded = re.sub(r"\\u([0-9a-fA-F]{4})", replace_unicode, value)
    return (
        decoded.replace(r"\t", "\t")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\:", ":")
        .replace(r"\=", "=")
        .replace(r"\\", "\\")
    )


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
    if path == parent:
        raise ErpReleaseError("Destino calculado coincide com a raiz protegida.")
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ErpReleaseError("Destino calculado fora do índice de código.") from exc


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

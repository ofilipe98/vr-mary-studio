"""Catalog of applications, versions, variants and packages for VRStudio.

Organizes the code repository around Applications and their Versions,
supporting deduplication across packages, variant tracking, dependency
distribution contexts, manual version correction, and version comparison.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import warnings
import zipfile
from functools import wraps
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

warnings.filterwarnings(
    "ignore",
    message=r"Overlapped entries: .*possible zip bomb.*",
    category=UserWarning,
)


UNIDENTIFIED_VERSION = "Versão não identificada"
CATALOG_SCHEMA_VERSION = 1
_SAFE_KEY_RE = re.compile(r"[^a-z0-9._-]+")
_WRITE_LOCK = threading.RLock()


class AppsCatalogError(RuntimeError):
    """Controlled failure in application and package catalog operations."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_app_id(value: str) -> str:
    cleaned = _SAFE_KEY_RE.sub("-", str(value or "").strip().casefold()).strip("-.")
    return cleaned or "app"


def _safe_variant_id(sha256_hash: str) -> str:
    cleaned = str(sha256_hash or "").strip().casefold()
    if not cleaned:
        raise AppsCatalogError("Artefato sem SHA-256 não pode identificar uma variante.")
    return cleaned


def _transaction(method):
    """Serialize writers across processes and publish one complete JSON snapshot."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with _WRITE_LOCK:
            return run(self, *args, **kwargs)

    def run(self, *args, **kwargs):
        if getattr(self, "_snapshot", None) is not None:
            raise AppsCatalogError("Uma projeção de leitura não pode alterar o catálogo.")
        if getattr(self, "_transaction_data", None) is not None:
            return method(self, *args, **kwargs)
        self.catalog_file.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(self.catalog_file) + ".lock.sqlite", timeout=30)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            original = self.load_catalog()
            self._transaction_data = json.loads(json.dumps(original))
            self._transaction_owner = threading.get_ident()
            try:
                result = method(self, *args, **kwargs)
                if self._transaction_data != original:
                    if self.catalog_file.exists():
                        backup = self.catalog_file.with_suffix(".json.before-apps-audit.bak")
                        if not backup.exists():
                            shutil.copy2(self.catalog_file, backup)
                    _atomic_write_json(self.catalog_file, self._transaction_data)
                return result
            finally:
                self._transaction_data = None
                self._transaction_owner = None
    return wrapped


def is_application_artifact(artifact: dict[str, Any] | str, jar_name: str = "") -> bool:
    """Classify whether a JAR represents an application or an auxiliary library."""
    if isinstance(artifact, str):
        artifact = {"relative_path": artifact}
    if artifact.get("artifact_role") in {"application", "library"}:
        return artifact["artifact_role"] == "application"
    key = str(artifact.get("application_key") or Path(str(artifact.get("relative_path") or "")).stem).casefold()
    if key in {"vrframework", "vrutil", "vr_common"}:
        return False
    if bool(artifact.get("version_detected")):
        return True
    if bool(artifact.get("manifest_main_class")):
        return True
    app_key = str(artifact.get("application_key") or "").strip().casefold()
    if app_key.startswith("vr") and app_key not in {"vrframework", "vrutil", "vr_common"}:
        return True
    name = jar_name or Path(str(artifact.get("relative_path") or "")).name
    name_stem = Path(name).stem.casefold()
    if name_stem.startswith("vr") and not name_stem.startswith(("vrframework", "vrutil", "vr_common")):
        return True
    return False


def compute_distribution_id(variant_sha256: str, dependency_hashes: Iterable[str]) -> str:
    """Compute a stable distribution ID based on main JAR and sorted dependency hashes."""
    sorted_deps = sorted(str(h).strip().casefold() for h in dependency_hashes if h)
    payload = f"{variant_sha256.strip().casefold()}:{','.join(sorted_deps)}".encode("utf-8")
    return "dist-" + hashlib.sha256(payload).hexdigest()[:12]


def _atomic_write_json(destination: Path, data: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + f".tmp.{uuid4().hex}")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)


class AppsCatalogStore:
    """Manages the application and package catalog metadata."""

    def __init__(self, root: Path, catalog_file: Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.catalog_file = (
            Path(catalog_file).resolve()
            if catalog_file is not None
            else self.root / "indice" / "codigo" / "apps_catalog.json"
        )

    def load_catalog(self) -> dict[str, Any]:
        """Load catalog from disk or return a fresh schema structure."""
        if getattr(self, "_snapshot", None) is not None:
            return self._snapshot
        if (getattr(self, "_transaction_data", None) is not None
                and getattr(self, "_transaction_owner", None) == threading.get_ident()):
            return self._transaction_data
        if not self.catalog_file.is_file():
            return {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "applications": {},
                "packages": {},
                "updated_at": _utc_now(),
            }
        try:
            content = self.catalog_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise AppsCatalogError("apps_catalog.json corrompido ou formato inválido.")
            data.setdefault("schema_version", CATALOG_SCHEMA_VERSION)
            data.setdefault("applications", {})
            data.setdefault("packages", {})
            if data["schema_version"] != CATALOG_SCHEMA_VERSION:
                raise AppsCatalogError("Versão do catálogo não suportada; dados preservados.")
            if not isinstance(data["applications"], dict) or not isinstance(data["packages"], dict):
                raise AppsCatalogError("Estrutura do catálogo inválida; dados preservados.")
            return data
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppsCatalogError(f"Falha ao carregar apps_catalog.json: {exc}") from exc

    def read_view(self, data: dict[str, Any]) -> AppsCatalogStore:
        """Expose an in-memory processing projection without enabling disk writes."""
        view = AppsCatalogStore(self.root, self.catalog_file)
        view._snapshot = data
        return view

    @_transaction
    def save_catalog(self, catalog: dict[str, Any]) -> None:
        """Persist catalog atomically."""
        catalog["updated_at"] = _utc_now()
        self._transaction_data = catalog

    @_transaction
    def register_package(
        self,
        manifest: dict[str, Any],
        *,
        package_id: str = "",
        package_name: str = "",
        source_path: str = "",
    ) -> dict[str, Any]:
        """Register or update an imported package and its components into the catalog."""
        catalog = self.load_catalog()
        pkg_id = str(package_id or manifest.get("release_id") or "").strip()
        if not pkg_id:
            raise AppsCatalogError("package_id é obrigatório para registrar pacote.")
        catalog.setdefault("unlinked_packages", {}).pop(pkg_id, None)
        # Replacing a manifest must first remove its obsolete reverse links.
        for app in catalog["applications"].values():
            for ver in app.get("versions", {}).values():
                for variant in ver.get("variants", {}).values():
                    variant["origin_packages"] = [
                        origin for origin in variant.get("origin_packages", [])
                        if origin.get("package_id") != pkg_id
                    ]

        pkg_name = str(package_name or pkg_id).strip()
        manifest_sha256 = str(manifest.get("release_manifest_sha256") or "")
        imported_at = str(manifest.get("indexed_at") or _utc_now())
        src_path = str(source_path or manifest.get("source_dir") or manifest.get("source_origin_dir") or "")

        artifacts = manifest.get("artifacts") or []
        if not isinstance(artifacts, list):
            artifacts = []

        # Classify into applications vs libraries/dependencies
        app_artifacts: list[dict[str, Any]] = []
        dep_artifacts: list[dict[str, Any]] = []

        for item in artifacts:
            if not isinstance(item, dict):
                continue
            if is_application_artifact(item) or (manifest.get("analysis_scope") == "single_jar" and len(artifacts) == 1):
                app_artifacts.append(item)
            else:
                dep_artifacts.append(item)

        # Build list of dependencies for this package
        package_dependencies = [
            {
                "relative_path": str(dep.get("relative_path") or ""),
                "sha256": str(dep.get("sha256") or ""),
                "size_bytes": int(dep.get("size_bytes") or 0),
            }
            for dep in dep_artifacts
        ]
        dep_hashes = [d["sha256"] for d in package_dependencies if d.get("sha256")]

        package_composition: list[dict[str, Any]] = []

        for item in app_artifacts:
            app_name = str(item.get("application") or Path(str(item.get("relative_path") or "")).stem).strip()
            raw_key = str(item.get("application_key") or app_name).strip().casefold()
            app_id = _safe_app_id(raw_key)

            detected_version = str(
                item.get("application_version")
                or (item.get("version_detected") if isinstance(item.get("version_detected"), str) else "")
                or item.get("version")
                or ""
            ).strip()

            is_identified = bool(
                detected_version
                and detected_version.casefold() not in {"unknown", "indefinida", "versão não identificada"}
            )
            if not is_identified:
                version_key = UNIDENTIFIED_VERSION
                original_version = UNIDENTIFIED_VERSION
            else:
                version_key = detected_version
                original_version = detected_version

            jar_sha256 = str(item.get("sha256") or "").strip()
            variant_id = _safe_variant_id(jar_sha256)
            override_key = json.dumps([app_id, original_version, jar_sha256])
            version_key = catalog.get("version_overrides", {}).get(override_key, version_key)
            distribution_inputs = [json.dumps({"path": dep["relative_path"], "sha256": dep["sha256"]}, sort_keys=True)
                                   for dep in package_dependencies]
            distribution_inputs.append(json.dumps({"declared_classpath": item.get("manifest_class_path", [])}))
            dist_id = compute_distribution_id(jar_sha256, distribution_inputs)

            apps = catalog["applications"]
            if app_id not in apps:
                apps[app_id] = {
                    "app_id": app_id,
                    "name": app_name,
                    "is_application": True,
                    "description": "",
                    "created_at": imported_at,
                    "updated_at": imported_at,
                    "versions": {},
                }
            app_entry = apps[app_id]
            app_entry["updated_at"] = imported_at

            versions = app_entry["versions"]
            if version_key not in versions:
                versions[version_key] = {
                    "version": version_key,
                    "is_identified": is_identified or version_key != original_version,
                    "original_version": original_version,
                    "user_version": version_key if version_key != original_version else None,
                    "manual_override": version_key != original_version,
                    "created_at": imported_at,
                    "updated_at": imported_at,
                    "variants": {},
                }
            ver_entry = versions[version_key]
            ver_entry["updated_at"] = imported_at

            variants = ver_entry["variants"]
            variant_id = next((key for key, value in variants.items()
                               if value.get("sha256") == jar_sha256), variant_id)
            if variant_id not in variants:
                variants[variant_id] = {
                    "variant_id": variant_id,
                    "sha256": jar_sha256,
                    "size_bytes": int(item.get("size_bytes") or 0),
                    "class_count": int(item.get("class_count") or 0),
                    "relative_path": str(item.get("relative_path") or ""),
                    "manifest_main_class": str(item.get("manifest_main_class") or ""),
                    "origin_packages": [],
                    "distribution_contexts": {},
                    "decompilation_state": "pending",
                    "decompiled_classes": 0,
                    "index_state": "pending",
                    "indexed_classes": 0,
                    "error_message": "",
                    "created_at": imported_at,
                    "updated_at": imported_at,
                }
            var_entry = variants[variant_id]
            var_entry.setdefault("original_versions", [])
            if original_version not in var_entry["original_versions"]:
                var_entry["original_versions"].append(original_version)
            var_entry["updated_at"] = imported_at
            if item.get("class_signatures"):
                var_entry["class_signatures"] = item["class_signatures"]

            # Add package origin if not already present
            existing_origins = {orig.get("package_id") for orig in var_entry["origin_packages"] if isinstance(orig, dict)}
            if pkg_id not in existing_origins:
                var_entry["origin_packages"].append({
                    "package_id": pkg_id,
                    "package_name": pkg_name,
                    "imported_at": imported_at,
                    "relative_path": str(item.get("relative_path") or ""),
                    "distribution_id": dist_id,
                })

            # Add distribution context
            dist_contexts = var_entry.setdefault("distribution_contexts", {})
            if dist_id not in dist_contexts:
                dist_contexts[dist_id] = {
                    "distribution_id": dist_id,
                    "dependencies_hash": hashlib.sha256(",".join(sorted(dep_hashes)).encode("utf-8")).hexdigest()[:12],
                    "dependencies": package_dependencies,
                }

            package_composition.append({
                "app_id": app_id,
                "app_name": app_name,
                "version": version_key,
                "variant_id": variant_id,
                "distribution_id": dist_id,
                "jar_path": str(item.get("relative_path") or ""),
                "sha256": jar_sha256,
                "is_application": True,
            })

        # Register package record
        catalog["packages"][pkg_id] = {
            "package_id": pkg_id,
            "name": pkg_name,
            "source_path": src_path,
            "manifest_sha256": manifest_sha256,
            "imported_at": imported_at,
            "composition": package_composition,
            "dependencies": package_dependencies,
            "registration_fingerprint": hashlib.sha256(
                json.dumps(manifest, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

        self.save_catalog(catalog)
        return catalog["packages"][pkg_id]

    def register_single_jar(
        self,
        artifact: dict[str, Any],
        *,
        source_path: str = "",
        package_id: str = "",
    ) -> dict[str, Any]:
        """Register a standalone JAR as an application version and synthetic single-jar package."""
        pkg_id = package_id or f"single-{artifact.get('sha256', '')[:12]}"
        synthetic_manifest = {
            "release_id": pkg_id,
            "release_manifest_sha256": artifact.get("sha256", ""),
            "indexed_at": _utc_now(),
            "source_dir": source_path,
            "source_origin_dir": source_path,
            "analysis_scope": "single_jar",
            "artifacts": [artifact],
        }
        return self.register_package(
            synthetic_manifest,
            package_id=pkg_id,
            package_name=f"JAR Avulso: {Path(source_path).name if source_path else artifact.get('relative_path', '')}",
            source_path=source_path,
        )

    @_transaction
    def unlink_package(self, package_id: str, *, clean_orphaned_versions: bool = True) -> dict[str, Any]:
        """Unlink a package from all application variants without deleting data used by others."""
        catalog = self.load_catalog()
        pkg_id = str(package_id or "").strip()
        package = catalog["packages"].get(pkg_id)
        if not package:
            raise AppsCatalogError(f"Pacote {package_id} não encontrado no catálogo.")

        unlinked_variants = 0
        orphaned_variants = 0

        apps_to_delete = []
        for app_id, app_entry in catalog["applications"].items():
            versions = app_entry.get("versions", {})
            vers_to_delete = []
            for ver_key, ver_entry in versions.items():
                variants = ver_entry.get("variants", {})
                for var_id, var_entry in variants.items():
                    origins = var_entry.get("origin_packages", [])
                    remaining = [orig for orig in origins if orig.get("package_id") != pkg_id]
                    if len(remaining) != len(origins):
                        var_entry["origin_packages"] = remaining
                        unlinked_variants += 1
                        if not remaining:
                            orphaned_variants += 1
                if clean_orphaned_versions:
                    # If all variants have 0 remaining origins, mark version for removal
                    if all(len(v.get("origin_packages", [])) == 0 for v in variants.values()):
                        vers_to_delete.append(ver_key)
            for vkey in vers_to_delete:
                del versions[vkey]
            if clean_orphaned_versions and not versions:
                apps_to_delete.append(app_id)

        for aid in apps_to_delete:
            del catalog["applications"][aid]

        del catalog["packages"][pkg_id]
        catalog.setdefault("unlinked_packages", {})[pkg_id] = True
        self.save_catalog(catalog)

        return {
            "package_id": pkg_id,
            "unlinked": True,
            "unlinked_variants": unlinked_variants,
            "orphaned_variants": orphaned_variants,
        }

    @_transaction
    def rename_package(self, package_id: str, new_name: str) -> dict[str, Any]:
        """Rename an imported package, updating its display name and linked variant origins."""
        catalog = self.load_catalog()
        pkg_id = str(package_id or "").strip()
        package = catalog.get("packages", {}).get(pkg_id)
        if not package:
            raise AppsCatalogError(f"Pacote '{package_id}' não encontrado no catálogo.")

        cleaned_name = str(new_name or "").strip()
        if not cleaned_name:
            raise AppsCatalogError("O novo nome do pacote não pode ser vazio.")

        package["name"] = cleaned_name

        updated_origins = 0
        for app_entry in catalog.get("applications", {}).values():
            for ver_entry in app_entry.get("versions", {}).values():
                for var_entry in ver_entry.get("variants", {}).values():
                    for origin in var_entry.get("origin_packages", []):
                        if origin.get("package_id") == pkg_id:
                            origin["package_name"] = cleaned_name
                            updated_origins += 1

        self.save_catalog(catalog)
        return {
            "package_id": pkg_id,
            "name": cleaned_name,
            "updated_origins": updated_origins,
        }

    def delete_source_jars(self, package_id: str, *, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        """Safely delete original source JARs after import/snapshot, preserving internal indexes."""
        catalog = self.load_catalog()
        pkg_id = str(package_id or "").strip()
        package = catalog.get("packages", {}).get(pkg_id)
        if not package:
            raise AppsCatalogError(f"Pacote '{package_id}' não encontrado no catálogo.")

        source_path_str = str(package.get("source_path") or "").strip()
        components = package.get("composition", []) + package.get("dependencies", [])
        snapshot_root = None
        if manifest and manifest.get("snapshot_managed"):
            source_path_str = str(manifest.get("source_origin_dir") or "").strip()
            snapshot_root = (self.root / str(manifest["source_dir"])).resolve()
            components = [item for item in manifest.get("artifacts", [])
                          if item.get("provenance", {}).get("origin") != "base"]
        if not source_path_str:
            raise AppsCatalogError(f"O pacote '{package_id}' não possui caminho de origem registrado.")

        source_path = Path(source_path_str)
        source_path = (self.root / source_path).resolve() if not source_path.is_absolute() else source_path.resolve()
        protected = (self.root / "indice").resolve()
        deleted: list[str] = []
        freed_bytes = 0
        candidates: dict[Path, str] = {}
        for comp in components:
            provenance_path = comp.get("provenance", {}).get("source_relative_path")
            rel = provenance_path or comp.get("jar_path") or comp.get("relative_path")
            if not rel:
                continue
            jar_file = source_path if source_path.is_file() else (source_path / rel).resolve()
            if snapshot_root and manifest.get("auto_detected") and not provenance_path and source_path.is_dir():
                # Older manifests did not retain the original path before categorization.
                matches = [p.resolve() for p in source_path.rglob(Path(rel).name) if p.is_file()]
                if len(matches) > 1:
                    raise AppsCatalogError("Há múltiplos JARs com o mesmo nome na origem.")
                if not matches:
                    continue
                jar_file = matches[0]
            if source_path.is_dir() and not jar_file.is_relative_to(source_path):
                raise AppsCatalogError("JAR fora da pasta de origem registrada.")
            if jar_file.is_relative_to(protected) or (snapshot_root and jar_file.is_relative_to(snapshot_root)):
                raise AppsCatalogError("Não é permitido excluir JARs do índice interno.")
            if jar_file.is_file() and jar_file.suffix.casefold() == ".jar":
                candidates[jar_file] = str(comp.get("sha256") or "")
        # Verify the complete selection before deleting: a source may have been replaced.
        for jar_file, expected_hash in candidates.items():
            with jar_file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != expected_hash:
                raise AppsCatalogError(f"O JAR de origem foi alterado: {jar_file.name}")
        for jar_file in candidates:
            size = jar_file.stat().st_size
            jar_file.unlink()
            freed_bytes += size
            deleted.append(jar_file.name)

        return {
            "package_id": pkg_id,
            "deleted_count": len(deleted),
            "deleted_files": deleted,
            "freed_bytes": freed_bytes,
        }

    @_transaction
    def override_version(
        self,
        app_id: str,
        current_version: str,
        manual_version: str,
        *, variant_id: str = "",
    ) -> dict[str, Any]:
        """Manually identify or correct an application version, preserving original metadata."""
        app_key = _safe_app_id(app_id)
        cur_ver = str(current_version or "").strip()
        new_ver = str(manual_version or "").strip()

        if not new_ver:
            raise AppsCatalogError("A nova versão não pode ser vazia.")
        if cur_ver == new_ver:
            return self.get_version(app_key, cur_ver) or {}

        catalog = self.load_catalog()
        app = catalog["applications"].get(app_key)
        if not app:
            raise AppsCatalogError(f"Aplicativo '{app_id}' não encontrado.")

        versions = app.setdefault("versions", {})
        old_ver_entry = versions.get(cur_ver)
        if not old_ver_entry:
            raise AppsCatalogError(f"Versão '{cur_ver}' do aplicativo '{app_id}' não encontrada.")

        all_variants = old_ver_entry.get("variants", {})
        if variant_id and variant_id not in all_variants:
            raise AppsCatalogError("A variante selecionada não pertence a esta versão.")
        moving = {key: value for key, value in all_variants.items() if not variant_id or key == variant_id}
        remaining = {key: value for key, value in all_variants.items() if key not in moving}
        original_entry = old_ver_entry
        old_ver_entry = {**old_ver_entry, "variants": moving}
        orig_version = old_ver_entry.get("original_version") or cur_ver
        for var_data in old_ver_entry.get("variants", {}).values():
            for original in var_data.get("original_versions", [orig_version]):
                key = json.dumps([app_key, original, var_data["sha256"]])
                catalog.setdefault("version_overrides", {})[key] = new_ver

        if new_ver in versions:
            # Merge variants into the existing version entry
            target_entry = versions[new_ver]
            target_variants = target_entry.setdefault("variants", {})
            for var_id, var_data in old_ver_entry.get("variants", {}).items():
                if var_id not in target_variants:
                    target_variants[var_id] = var_data
                else:
                    target_variants[var_id].setdefault("distribution_contexts", {}).update(
                        var_data.get("distribution_contexts", {})
                    )
                    target_variants[var_id]["original_versions"] = sorted(set(
                        target_variants[var_id].get("original_versions", [])
                        + var_data.get("original_versions", [orig_version])
                    ))
                    # Merge origin packages
                    existing_origs = {o.get("package_id") for o in target_variants[var_id].get("origin_packages", [])}
                    for orig in var_data.get("origin_packages", []):
                        if orig.get("package_id") not in existing_origs:
                            target_variants[var_id]["origin_packages"].append(orig)
            del versions[cur_ver]
            res_entry = target_entry
            res_entry.update(user_version=new_ver, manual_override=True, is_identified=True)
        else:
            # Move and update
            old_ver_entry["version"] = new_ver
            old_ver_entry["user_version"] = new_ver
            old_ver_entry["manual_override"] = True
            old_ver_entry["is_identified"] = True
            old_ver_entry["original_version"] = orig_version
            old_ver_entry["updated_at"] = _utc_now()
            versions[new_ver] = old_ver_entry
            del versions[cur_ver]
            res_entry = old_ver_entry

        if remaining:
            versions[cur_ver] = {**original_entry, "variants": remaining}

        # Update references in package compositions
        for pkg in catalog.get("packages", {}).values():
            for comp in pkg.get("composition", []):
                if (comp.get("app_id") == app_key and comp.get("version") == cur_ver
                        and comp.get("variant_id") in moving):
                    comp["version"] = new_ver

        self.save_catalog(catalog)
        return res_entry

    def list_applications(self) -> list[dict[str, Any]]:
        """List all applications with summary counts and status."""
        catalog = self.load_catalog()
        result: list[dict[str, Any]] = []

        for app_id, app in sorted(catalog.get("applications", {}).items(), key=lambda item: item[1].get("name", item[0]).casefold()):
            versions = app.get("versions", {})
            total_versions = len(versions)
            ready_versions = 0
            pending_versions = 0
            failed_versions = 0
            has_variants = False
            has_unidentified = False

            for ver_key, ver in versions.items():
                if ver_key == UNIDENTIFIED_VERSION or not ver.get("is_identified", True):
                    has_unidentified = True
                variants = ver.get("variants", {})
                if len(variants) > 1:
                    has_variants = True
                # Check states of variants
                all_ready = bool(variants) and all(v.get("index_state") == "ready" for v in variants.values())
                any_failed = any(v.get("index_state") == "failed" or v.get("decompilation_state") == "failed" for v in variants.values())
                if all_ready:
                    ready_versions += 1
                elif any_failed:
                    failed_versions += 1
                else:
                    pending_versions += 1

            result.append({
                "appId": app_id,
                "name": app.get("name", app_id),
                "isApplication": app.get("is_application", True),
                "versionCount": total_versions,
                "readyCount": ready_versions,
                "pendingCount": pending_versions,
                "failedCount": failed_versions,
                "hasVariants": has_variants,
                "hasUnidentified": has_unidentified,
                "updatedAt": app.get("updated_at", ""),
            })

        return result

    @_transaction
    def update_variant_state(
        self,
        app_id: str,
        version: str,
        variant_id_or_hash: str,
        index_state: str | None = None,
        *,
        decompilation_state: str | None = None,
        class_count: int | None = None,
        indexed_classes: int | None = None,
        decompiled_classes: int | None = None,
        class_signatures: dict[str, str] | None = None,
    ) -> bool:
        """Update processing state and class signatures for a variant."""
        catalog = self.load_catalog()
        app_key = _safe_app_id(app_id)
        app = catalog.get("applications", {}).get(app_key)
        if not app:
            return False
        ver = app.get("versions", {}).get(version)
        if not ver:
            return False
        variants = ver.get("variants", {})
        target_variant = None
        for vid, vdata in variants.items():
            if vid == variant_id_or_hash or vdata.get("sha256") == variant_id_or_hash or vid == _safe_variant_id(variant_id_or_hash):
                target_variant = vdata
                break
        if not target_variant:
            return False

        if index_state is not None:
            target_variant["index_state"] = index_state
        if decompilation_state is not None:
            target_variant["decompilation_state"] = decompilation_state
        if class_count is not None:
            target_variant["class_count"] = class_count
        if indexed_classes is not None:
            target_variant["indexed_classes"] = indexed_classes
        if decompiled_classes is not None:
            target_variant["decompiled_classes"] = decompiled_classes
        if class_signatures is not None:
            target_variant["class_signatures"] = class_signatures
        target_variant["updated_at"] = _utc_now()
        self.save_catalog(catalog)
        return True

    def get_application(self, app_id: str) -> dict[str, Any] | None:
        """Get application details by ID."""
        catalog = self.load_catalog()
        app_key = _safe_app_id(app_id)
        app = catalog.get("applications", {}).get(app_key)
        if not app:
            return None
        versions = app.get("versions", {})
        has_unident = any(k == UNIDENTIFIED_VERSION or not v.get("is_identified", True) for k, v in versions.items())
        has_vars = any(len(v.get("variants", {})) > 1 for v in versions.values())
        res = dict(app)
        res["hasUnidentified"] = has_unident
        res["hasVariants"] = has_vars
        return res

    def list_versions(self, app_id: str) -> list[dict[str, Any]]:
        """List all versions for an application."""
        app = self.get_application(app_id)
        if not app:
            return []
        result: list[dict[str, Any]] = []

        def version_sort(item):
            return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                         for part in re.split(r"(\d+)", item[0]))

        for ver_key, ver in sorted(app.get("versions", {}).items(), key=version_sort, reverse=True):
            variants = ver.get("variants", {})
            decomp_states = [v.get("decompilation_state", "pending") for v in variants.values()]
            index_states = [v.get("index_state", "pending") for v in variants.values()]

            overall_decomp = "ready" if decomp_states and all(s == "ready" for s in decomp_states) else (
                "failed" if "failed" in decomp_states else ("partial" if "partial" in decomp_states or "ready" in decomp_states else "pending")
            )
            overall_index = "ready" if index_states and all(s == "ready" for s in index_states) else (
                "failed" if "failed" in index_states else ("partial" if "partial" in index_states or "ready" in index_states else "pending")
            )

            total_classes = sum(int(v.get("class_count", 0)) for v in variants.values())
            decompiled_classes = sum(int(v.get("decompiled_classes", 0)) for v in variants.values())
            indexed_classes = sum(int(v.get("indexed_classes", 0)) for v in variants.values())
            progress = round(indexed_classes * 100 / total_classes, 1) if total_classes else 0.0

            origins_count = sum(len(v.get("origin_packages", [])) for v in variants.values())

            result.append({
                "version": ver_key,
                "isIdentified": bool(ver.get("is_identified", True)),
                "userVersion": ver.get("user_version") or "",
                "originalVersion": ver.get("original_version") or ver_key,
                "manualOverride": bool(ver.get("manual_override", False)),
                "variantCount": len(variants),
                "hasVariants": len(variants) > 1,
                "decompilationState": overall_decomp,
                "indexState": overall_index,
                "classCount": total_classes,
                "decompiledClasses": decompiled_classes,
                "indexedClasses": indexed_classes,
                "progressPercent": progress,
                "originCount": origins_count,
            })

        return result

    def get_version(self, app_id: str, version: str) -> dict[str, Any] | None:
        """Get version details by app_id and version string."""
        app = self.get_application(app_id)
        if not app:
            return None
        ver = app.get("versions", {}).get(version)
        if not ver:
            return None
        res = dict(ver)
        all_origins = []
        seen_pkg_ids = set()
        for v in ver.get("variants", {}).values():
            for orig in v.get("origin_packages", []):
                pid = orig.get("package_id")
                if pid not in seen_pkg_ids:
                    seen_pkg_ids.add(pid)
                    all_origins.append(orig)
        res["origin_packages"] = all_origins
        return res

    def list_variants(self, app_id: str, version: str) -> list[dict[str, Any]]:
        """List all variants for a version."""
        ver = self.get_version(app_id, version)
        if not ver:
            return []
        return list(ver.get("variants", {}).values())

    def get_variant(self, app_id: str, version: str, variant_id: str) -> dict[str, Any] | None:
        """Get a specific variant by ID."""
        ver = self.get_version(app_id, version)
        if not ver:
            return None
        return ver.get("variants", {}).get(variant_id)

    def list_packages(self) -> list[dict[str, Any]]:
        """List all registered packages."""
        catalog = self.load_catalog()
        return sorted(
            catalog.get("packages", {}).values(),
            key=lambda pkg: str(pkg.get("imported_at") or ""),
            reverse=True,
        )

    def get_package(self, package_id: str) -> dict[str, Any] | None:
        """Get package details by package_id."""
        catalog = self.load_catalog()
        return catalog.get("packages", {}).get(package_id)

    @_transaction
    def update_variant_processing(
        self,
        app_id: str,
        version: str,
        variant_id: str,
        *,
        decompilation_state: str | None = None,
        index_state: str | None = None,
        decompiled_classes: int | None = None,
        indexed_classes: int | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """Update decompilation or indexing state for a specific variant."""
        catalog = self.load_catalog()
        app_key = _safe_app_id(app_id)
        var = catalog.get("applications", {}).get(app_key, {}).get("versions", {}).get(version, {}).get("variants", {}).get(variant_id)
        if not var:
            raise AppsCatalogError(f"Variante '{variant_id}' não encontrada em {app_id} v{version}.")

        if decompilation_state is not None:
            var["decompilation_state"] = decompilation_state
        if index_state is not None:
            var["index_state"] = index_state
        if decompiled_classes is not None:
            var["decompiled_classes"] = max(0, int(decompiled_classes))
        if indexed_classes is not None:
            var["indexed_classes"] = max(0, int(indexed_classes))
        if error_message is not None:
            var["error_message"] = str(error_message)

        var["updated_at"] = _utc_now()
        self.save_catalog(catalog)
        return var

    @_transaction
    def sync_legacy_releases(self) -> int:
        """Scan indexed releases on disk and migrate them idempotently into the apps catalog."""
        indexed_dir = self.root / "indice" / "codigo" / "releases"
        if not indexed_dir.is_dir():
            return 0
        count = 0
        catalog = self.load_catalog()
        for manifest_file in indexed_dir.glob("*/manifest.json"):
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                pkg_id = str(manifest.get("release_id") or manifest_file.parent.name)
                if pkg_id in catalog.get("unlinked_packages", {}):
                    continue
                fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
                if catalog["packages"].get(pkg_id, {}).get("registration_fingerprint") == fingerprint:
                    continue
                self.register_package(manifest, package_id=pkg_id)
                count += 1
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise AppsCatalogError(f"Migração interrompida em {manifest_file}: {exc}") from exc
        return count

    def _resolve_classes_from_jar(self, variant: dict[str, Any]) -> dict[str, str] | None:
        """Read class names and sha256 bytecode hashes from the JAR file or cached signatures."""
        if "class_signatures" in variant:
            return dict(variant["class_signatures"])
        rel_path = str(variant.get("relative_path") or "")
        if not rel_path:
            return None
        # Try candidate paths
        candidate_paths: list[Path] = []
        for orig in variant.get("origin_packages", []):
            pkg_id = orig.get("package_id")
            if pkg_id:
                origin_path = str(orig.get("relative_path") or rel_path)
                manifest_file = self.root / "indice" / "codigo" / "releases" / pkg_id / "manifest.json"
                if manifest_file.is_file():
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    source = Path(manifest.get("source_dir") or "")
                    if not source.is_absolute():
                        source = self.root / source
                    candidate_paths.append(source / origin_path)
                candidate_paths.append(self.root / "ERP" / "releases" / pkg_id / "jars" / origin_path)
                candidate_paths.append(self.root / "ERP" / "releases" / pkg_id / origin_path)
        candidate_paths.append(self.root / "ERP" / "releases" / rel_path)

        jar_file: Path | None = None
        for cand in candidate_paths:
            if cand.is_file():
                digest = hashlib.sha256()
                with cand.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != variant.get("sha256"):
                    continue
                jar_file = cand
                break

        if not jar_file:
            return None

        classes: dict[str, str] = {}
        try:
            with zipfile.ZipFile(jar_file) as archive, warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"Overlapped entries: .*possible zip bomb.*",
                    category=UserWarning,
                )
                for info in archive.infolist():
                    name = info.filename
                    if name.endswith(".class") and not name.endswith("/"):
                        cls_name = name[:-6].replace("/", ".")
                        content_hash = hashlib.sha256(archive.read(info)).hexdigest()
                        classes[cls_name] = content_hash
        except (OSError, zipfile.BadZipFile):
            return None
        return classes

    def compare_versions(
        self,
        app_id: str,
        base_version: str,
        target_version: str,
        *,
        base_variant_id: str = "",
        target_variant_id: str = "",
        class_inventory_resolver: Callable[[dict[str, Any]], dict[str, str] | None] | None = None,
    ) -> dict[str, Any]:
        """Compare two versions of an application.

        Reports added, removed, modified and unchanged classes.
        If either version has pending processing, incomplete comparison will
        NOT report unprocessed classes as removed.
        """
        app_key = _safe_app_id(app_id)
        catalog = self.load_catalog()
        app = catalog.get("applications", {}).get(app_key)
        if not app:
            raise AppsCatalogError(f"Aplicativo '{app_id}' não encontrado.")

        base_ver = app.get("versions", {}).get(base_version)
        target_ver = app.get("versions", {}).get(target_version)
        if not base_ver:
            raise AppsCatalogError(f"Versão base '{base_version}' não encontrada.")
        if not target_ver:
            raise AppsCatalogError(f"Versão de destino '{target_version}' não encontrada.")

        base_variants = base_ver.get("variants", {})
        target_variants = target_ver.get("variants", {})

        def choose(variants, selected):
            if selected:
                if selected not in variants:
                    raise AppsCatalogError("Variante selecionada não encontrada.")
                return variants[selected]
            if len(variants) != 1:
                raise AppsCatalogError("Selecione explicitamente a variante de cada versão.")
            return next(iter(variants.values()))

        b_var = choose(base_variants, base_variant_id)
        t_var = choose(target_variants, target_variant_id)

        if not b_var or not t_var:
            raise AppsCatalogError("Variantes necessárias para comparação não encontradas.")

        b_ready = (b_var.get("index_state") == "ready")
        t_ready = (t_var.get("index_state") == "ready")
        is_complete = b_ready and t_ready

        # Resolve classes map: class_name -> content_sha256
        resolver = class_inventory_resolver or self._resolve_classes_from_jar
        b_inventory = resolver(b_var)
        t_inventory = resolver(t_var)
        b_classes = b_inventory or {}
        t_classes = t_inventory or {}
        # A stale ready flag cannot prove that a missing/corrupt JAR was inventoried.
        b_ready = b_ready and b_inventory is not None and len(b_classes) >= int(b_var.get("class_count") or 0)
        t_ready = t_ready and t_inventory is not None and len(t_classes) >= int(t_var.get("class_count") or 0)
        is_complete = b_ready and t_ready

        # Compare sets
        b_names = set(b_classes.keys())
        t_names = set(t_classes.keys())

        common = b_names & t_names
        unchanged_count = 0
        modified_classes: list[str] = []

        for name in sorted(common):
            b_hash = b_classes.get(name)
            t_hash = t_classes.get(name)
            if b_hash and t_hash and b_hash == t_hash:
                unchanged_count += 1
            else:
                modified_classes.append(name)

        added_classes = sorted(t_names - b_names) if b_ready else []

        # Crucial rule: If target processing is pending, classes missing in target
        # cannot be assumed removed!
        removed_classes: list[str] = []
        pending_verification_classes: list[str] = []

        missing_in_target = sorted(b_names - t_names)
        if t_ready:
            removed_classes = missing_in_target
        else:
            pending_verification_classes = missing_in_target
        if not b_ready:
            pending_verification_classes = sorted(set(pending_verification_classes) | (t_names - b_names))

        status_label = "complete" if is_complete else "pending_processing"
        pending_note = ""
        if not is_complete:
            pending_note = (
                "Uma ou ambas as versões possuem processamento pendente. "
                "Classes ainda não processadas não são tratadas como removidas."
            )

        return {
            "appId": app_key,
            "appName": app.get("name", app_key),
            "baseVersion": base_version,
            "targetVersion": target_version,
            "baseVariantId": b_var.get("variant_id", ""),
            "targetVariantId": t_var.get("variant_id", ""),
            "state": status_label,
            "comparisonState": status_label,
            "isComplete": is_complete,
            "pendingNote": pending_note,
            "summary": {
                "added": len(added_classes),
                "removed": len(removed_classes),
                "modified": len(modified_classes),
                "unchanged": unchanged_count,
                "pendingVerification": len(pending_verification_classes),
            },
            "addedClasses": added_classes,
            "removedClasses": removed_classes,
            "modifiedClasses": modified_classes,
            "unchangedCount": unchanged_count,
            "pendingVerificationClasses": pending_verification_classes,
        }

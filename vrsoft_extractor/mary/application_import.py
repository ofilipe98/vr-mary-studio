"""Read-only import preview; confirmation is tied to the inspected bytes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .apps_catalog import UNIDENTIFIED_VERSION, is_application_artifact
from .erp_releases import ErpReleaseCatalog, ErpReleaseError


def validate_preview_fingerprint(
    source: str | Path,
    fingerprint: list[dict[str, Any]],
    *,
    single: bool = False,
    catalog: ErpReleaseCatalog | None = None,
    workspace_root: str | Path | None = None,
) -> None:
    """Validate candidate JARs against preview fingerprint using cheap stat() checks.

    Directory mode binds the fingerprint to the exact ``relative_path`` set
    shown in the preview. Any added, removed, renamed or moved JAR invalidates
    the preview before any expensive re-hash. Size/mtime only fail fast; the
    SHA-256 calculated during streaming copy remains the final guarantee.
    """
    candidate = Path(source).resolve(strict=False)
    if single:
        if not candidate.is_file():
            raise ErpReleaseError(f"Arquivo JAR não encontrado: {candidate}")
        if not fingerprint:
            raise ErpReleaseError("Os JARs mudaram após a prévia. Gere uma nova prévia antes de importar.")
        fp = fingerprint[0]
        st = candidate.stat()
        if "size_bytes" in fp and st.st_size != int(fp["size_bytes"]):
            raise ErpReleaseError(
                "Os JARs mudaram após a prévia. Gere uma nova prévia antes de importar."
            )
        if "modified_ns" in fp and st.st_mtime_ns != int(fp["modified_ns"]):
            raise ErpReleaseError(
                "Os JARs mudaram após a prévia. Gere uma nova prévia antes de importar."
            )
        return

    if not candidate.is_dir():
        raise ErpReleaseError(f"Pasta de JARs não encontrada: {candidate}")

    fp_by_rel = {item["relative_path"]: item for item in fingerprint if "relative_path" in item}
    # Current discovery with the same semantics as `_source_jars`: recursive
    # os.walk, followlinks=False and pruning of irrelevant dirs. Identity is
    # the `relative_path` set, never list index, count or bare file name.
    if catalog is not None:
        current_jars = catalog._source_jars(candidate)
    elif workspace_root is not None:
        current_jars = ErpReleaseCatalog(workspace_root)._source_jars(candidate)
    else:
        import os as _os

        from .erp_releases import _PRUNED_SOURCE_DIRS as _PRUNED

        current_jars = []
        for root_str, dirs, files in _os.walk(candidate, followlinks=False):
            dirs[:] = [d for d in dirs if d.casefold() not in _PRUNED]
            root_path = Path(root_str)
            for name in files:
                if name.casefold().endswith(".jar"):
                    path = root_path / name
                    if path.is_file():
                        current_jars.append(path)
    preview_paths = set(fp_by_rel.keys())
    current_paths = {
        path.relative_to(candidate).as_posix() for path in current_jars
    }
    if current_paths != preview_paths:
        raise ErpReleaseError(
            "Os JARs mudaram após a prévia. Gere uma nova prévia antes de importar."
        )
    for rel_path, fp in fp_by_rel.items():
        jar_path = candidate / rel_path
        if not jar_path.is_file():
            raise ErpReleaseError(
                "Os JARs mudaram após a prévia. Gere uma nova prévia antes de importar."
            )
        st = jar_path.stat()
        if "size_bytes" in fp and st.st_size != int(fp["size_bytes"]):
            raise ErpReleaseError(
                "Os JARs mudaram após a prévia. Gere uma nova prévia antes de importar."
            )
        if "modified_ns" in fp and st.st_mtime_ns != int(fp["modified_ns"]):
            raise ErpReleaseError(
                "Os JARs mudaram após a prévia. Gere uma nova prévia antes de importar."
            )


def preview_application_import(
    root: Path,
    source: str,
    *,
    single: bool,
    progress_callback: Any = None,
) -> dict[str, Any]:
    catalog = ErpReleaseCatalog(root)
    candidate = Path(source).resolve(strict=False)
    if single:
        if not candidate.is_file():
            raise ErpReleaseError(f"Arquivo JAR não encontrado: {candidate}")
        if candidate.suffix.casefold() != ".jar":
            raise ErpReleaseError(f"O arquivo selecionado não é um JAR: {candidate}")
    else:
        if not candidate.exists():
            raise ErpReleaseError(f"Pasta de JARs não encontrada: {candidate}")
        if not candidate.is_dir():
            raise ErpReleaseError(f"A origem especificada não é um diretório: {candidate}")

    package = catalog.detect_package(candidate, progress_callback=progress_callback)
    data = catalog.apps_store.load_catalog()
    rows: list[dict[str, Any]] = []
    fingerprint: list[dict[str, Any]] = []
    components = package["components"]
    total = len(components)

    for idx, component in enumerate(components):
        relative = component["source_relative_path"]
        path = candidate if single else candidate / relative
        if progress_callback:
            progress_callback({
                "operation": "preview",
                "event": "progress",
                "stage": "hash",
                "current": idx + 1,
                "total": total,
                "file": Path(relative).name,
            })
        artifact, _classes = catalog._inventory_jar(path, relative)
        if artifact.get("error"):
            raise ErpReleaseError(f"{relative}: {artifact['error']}")
        app_id = artifact["application_key"]
        version = artifact.get("application_version") or UNIDENTIFIED_VERSION
        if version == "unknown":
            version = UNIDENTIFIED_VERSION
        version = data.get("version_overrides", {}).get(
            json.dumps([app_id, version, artifact["sha256"]]), version
        )
        fingerprint.append({
            "relative_path": relative,
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
            "modified_ns": artifact["modified_ns"],
            "application": artifact["application"],
            "application_key": app_id,
            "application_version": version,
        })
        app = data["applications"].get(app_id)
        variants = (app or {}).get("versions", {}).get(version, {}).get("variants", {})
        role = "application" if single or is_application_artifact(artifact) else "dependency"
        status = (
            "Dependência"
            if role == "dependency"
            else "Novo aplicativo"
            if not app
            else "Nova versão"
            if not variants
            else "Já existente — reutilizar"
            if any(v["sha256"] == artifact["sha256"] for v in variants.values())
            else "Nova variante"
        )
        rows.append({
            "application": artifact["application"],
            "version": version,
            "sha256": artifact["sha256"],
            "relative_path": relative,
            "role": role,
            "status": status,
        })
    return {
        "source": str(candidate),
        "single": single,
        "rows": rows,
        "fingerprint": sorted(fingerprint, key=lambda a: a["relative_path"]),
        "suggested_release_id": package["suggested_release_id"],
    }

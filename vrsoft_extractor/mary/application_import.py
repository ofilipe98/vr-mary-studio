"""Read-only import preview; confirmation is tied to the inspected bytes."""
from pathlib import Path
from typing import Any

from .apps_catalog import UNIDENTIFIED_VERSION, is_application_artifact
from .erp_releases import ErpReleaseCatalog, ErpReleaseError


def preview_application_import(root: Path, source: str, *, single: bool) -> dict[str, Any]:
    catalog = ErpReleaseCatalog(root)
    candidate = Path(source).resolve()
    if single != candidate.is_file():
        raise ErpReleaseError("Selecione um JAR individual ou uma pasta de pacote válida.")
    package = catalog.detect_package(candidate)
    data = catalog.apps_store.load_catalog()
    rows, fingerprint = [], []
    for component in package["components"]:
        relative = component["source_relative_path"]
        path = candidate if single else candidate / relative
        artifact, _classes = catalog._inventory_jar(path, relative)
        if artifact.get("error"):
            raise ErpReleaseError(f"{relative}: {artifact['error']}")
        fingerprint.append({"relative_path": relative, "sha256": artifact["sha256"]})
        app_id = artifact["application_key"]
        version = artifact.get("application_version") or UNIDENTIFIED_VERSION
        if version == "unknown":
            version = UNIDENTIFIED_VERSION
        import json
        version = data.get("version_overrides", {}).get(json.dumps([app_id, version, artifact["sha256"]]), version)
        app = data["applications"].get(app_id)
        variants = (app or {}).get("versions", {}).get(version, {}).get("variants", {})
        role = "application" if single or is_application_artifact(artifact) else "dependency"
        status = ("Dependência" if role == "dependency" else "Novo aplicativo" if not app
                  else "Nova versão" if not variants else "Já existente — reutilizar"
                  if any(v["sha256"] == artifact["sha256"] for v in variants.values()) else "Nova variante")
        rows.append({"application": artifact["application"], "version": version,
                     "sha256": artifact["sha256"], "relative_path": relative, "role": role, "status": status})
    return {"source": str(candidate), "single": single, "rows": rows,
            "fingerprint": sorted(fingerprint, key=lambda a: a["relative_path"]),
            "suggested_release_id": package["suggested_release_id"]}

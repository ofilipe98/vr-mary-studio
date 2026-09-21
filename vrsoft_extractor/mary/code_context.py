"""Explicit application contexts shared by UI, execution and code retrieval."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from .apps_catalog import AppsCatalogError
from .erp_releases import ErpReleaseCatalog

LOGGER = logging.getLogger(__name__)
MASTER_APP_ID = "vrmaster"


def _normalized_app_id(item: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]", "", str(item.get("app_id") or "").casefold())


def application_context_warning(text: str, contexts: list[dict[str, Any]] | None) -> str:
    """Detect explicit product stack frames; never infer from shared library names."""
    if not contexts:
        return ""
    products = {"vratacarejo": "VRAtacarejo", "vrpdv": "VRPdv",
                "vrmaster": "VRMaster", "vrfrente": "VRFrente"}
    mentioned = set(re.findall(
        r"\b(vratacarejo|vrpdv|vrmaster|vrfrente)\.[\w.$]+\([^\n)]*\.java:\d+\)",
        text, re.IGNORECASE
    ))
    selected = [_normalized_app_id(c) for c in contexts]
    # VRMaster is consulted as a fallback by the code retrieval, so a Master
    # stack frame must not discard the selected contexts.
    missing = [products[p.lower()] for p in mentioned
               if p.casefold() != MASTER_APP_ID
               and not any(s.startswith(p.lower()) for s in selected)]
    if not missing:
        return ""
    return ("O stack trace pertence a " + ", ".join(sorted(missing))
            + ", mas esse aplicativo não está no contexto selecionado. "
            "Selecione o aplicativo e a versão em Aplicativos antes de investigar esse código.")


def freeze_application_contexts(root: Path, selections: list[dict[str, Any]], *, full_hash: bool = True) -> list[dict[str, Any]]:
    """Resolve exact variants and distributions. Never fall back to a package/latest version."""
    if not selections:
        raise AppsCatalogError("Selecione pelo menos um aplicativo e sua versão para o Ultra.")
    catalog = ErpReleaseCatalog(root)
    catalog.ensure_apps_catalog_synced()
    data = catalog.apps_store.load_catalog()
    result, seen = [], set()
    for selection in selections:
        app_id, version, variant_id, package_id = (str(selection.get(k) or "") for k in
                                                   ("app_id", "version", "variant_id", "package_id"))
        if app_id in seen:
            raise AppsCatalogError("Selecione apenas uma versão/distribuição por aplicativo no mesmo contexto.")
        seen.add(app_id)
        app = data["applications"].get(app_id, {})
        variant = app.get("versions", {}).get(version, {}).get("variants", {}).get(variant_id)
        package = data["packages"].get(package_id)
        if not variant or not package:
            raise AppsCatalogError(f"Contexto de {app_id} {version} indisponível; selecione novamente.")
        composition = next((c for c in package["composition"] if c["app_id"] == app_id
                            and c["version"] == version and c["variant_id"] == variant_id), None)
        if not composition:
            raise AppsCatalogError("A origem não contém a variante selecionada.")
        status = catalog.status(package_id, full_hash=full_hash)
        if status.get("freshness") != "fresh" or status.get("state") != "ready":
            raise AppsCatalogError(f"Origem {package_id} desatualizada ou incompleta; importe novamente.")
        manifest = catalog.load_manifest(package_id)
        by_path = {a["relative_path"]: a for a in manifest["artifacts"]}
        expected = [{"relative_path": composition["jar_path"], "sha256": variant["sha256"], "role": "application"}]
        expected += [{"relative_path": a["relative_path"], "sha256": a["sha256"], "role": "dependency"}
                     for a in package.get("dependencies", [])]
        for item in expected:
            if by_path.get(item["relative_path"], {}).get("sha256") != item["sha256"]:
                raise AppsCatalogError("O conteúdo da distribuição mudou; selecione novamente o aplicativo.")
        frozen = {"app_id": app_id, "application": app.get("name", app_id), "version": version,
                  "variant_id": variant_id, "sha256": variant["sha256"], "package_id": package_id,
                  "distribution_id": composition["distribution_id"],
                  "manifest_sha256": manifest["release_manifest_sha256"], "artifacts": expected}
        frozen["label"] = f"{frozen['application']} {version} · {variant['sha256'][:12]} · {package_id}"
        frozen["context_id"] = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
        result.append(frozen)
    return sorted(result, key=lambda c: c["app_id"])


def master_fallback_context(root: Path, contexts: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Resolve the central VRMaster context of the same package for fallback.

    Returns ``None`` when there is no explicit scope, when VRMaster is already
    part of it, or when no package offers an available VRMaster context.  A
    missing Master never fails the turn; it only leaves the primary scope.
    """
    if not contexts:
        return None
    if any(_normalized_app_id(item) == MASTER_APP_ID for item in contexts):
        return None
    try:
        catalog = ErpReleaseCatalog(root)
        catalog.ensure_apps_catalog_synced()
        packages = catalog.apps_store.load_catalog().get("packages", {})
        for package_id in dict.fromkeys(str(item.get("package_id") or "") for item in contexts):
            package = packages.get(package_id)
            if not package:
                continue
            composition = next(
                (entry for entry in package.get("composition", [])
                 if _normalized_app_id(entry) == MASTER_APP_ID),
                None,
            )
            if composition is None:
                continue
            selection = {key: composition.get(key) for key in ("app_id", "version", "variant_id")}
            selection["package_id"] = package_id
            return freeze_application_contexts(root, [selection], full_hash=False)[0]
    except (AppsCatalogError, ValueError, RuntimeError, KeyError) as exc:
        LOGGER.warning("VRMaster indisponível como fallback: %s", exc)
    return None


def validate_application_contexts(root: Path, contexts: list[dict[str, Any]]) -> None:
    current = freeze_application_contexts(root, contexts)
    if current != contexts:
        raise AppsCatalogError("O contexto de aplicativos mudou durante a execução; inicie uma nova análise.")


def artifact_sql_filter(artifacts: list[dict[str, Any]] | None, manifest_hash: str, *, alias: str = "s") -> tuple[str, list[Any]]:
    """Filter before SQL LIMIT; an explicit empty scope yields no results."""
    sql, params = "", []
    if manifest_hash:
        sql += f" AND {alias}.release_hash = ?"
        params.append(manifest_hash)
    if artifacts is not None:
        if not artifacts:
            return sql + " AND 0", params
        sql += " AND (" + " OR ".join(f"({alias}.jar_relative_path = ? AND {alias}.artifact_sha256 = ?)" for _ in artifacts) + ")"
        for item in artifacts:
            params.extend((item["relative_path"], item["sha256"]))
    return sql, params

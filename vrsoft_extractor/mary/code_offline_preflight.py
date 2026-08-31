"""Deterministic readiness report for local ERP JAR processing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .code_coverage import ErpCodeCoverage
from .erp_releases import DEFAULT_EXPECTED_JAR_COUNT, ErpReleaseCatalog
from .jvm_toolchain import JvmToolchain


class OfflineCodePreflight:
    """Validate a release without invoking a model or changing its source."""

    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        coverage: ErpCodeCoverage | None = None,
        toolchain: JvmToolchain | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.coverage = coverage or ErpCodeCoverage(
            self.root, catalog=self.catalog
        )
        self.toolchain = toolchain or JvmToolchain(self.root)

    def run(self, release_id: str) -> dict[str, Any]:
        release = self.catalog.status(release_id)
        manifest = self.catalog.load_manifest(release_id)
        coverage = self.coverage.status(release_id)
        doctor = self.toolchain.doctor()
        blockers: list[str] = []
        warnings = [str(item) for item in release.get("warnings") or []]

        jar_count = int(release.get("jar_count") or 0)
        expected = int(
            release.get("expected_jar_count") or DEFAULT_EXPECTED_JAR_COUNT
        )
        analysis_scope = str(manifest.get("analysis_scope") or "full_release")
        if release.get("state") != "ready":
            blockers.append("O manifesto da release não está no estado ready.")
        if release.get("freshness") != "fresh":
            blockers.append("A origem da release está ausente ou desatualizada.")
        if jar_count != expected:
            blockers.append(
                f"O escopo exige exatamente {expected} JAR(s); encontrados {jar_count}."
            )

        artifacts = [
            item
            for item in manifest.get("artifacts") or []
            if isinstance(item, dict)
        ]
        if len(artifacts) != expected or any(
            not item.get("relative_path") or not item.get("sha256")
            for item in artifacts
        ):
            blockers.append(
                f"O manifesto não possui {expected} artefato(s) com caminho e SHA-256."
            )
        if analysis_scope == "single_jar":
            warnings.append(
                "Escopo parcial: esta base cobre somente o JAR selecionado, não os "
                f"{DEFAULT_EXPECTED_JAR_COUNT} JARs do ERP."
            )

        java = dict(doctor.get("java") or {})
        decompilers = [
            dict(doctor.get(name) or {}) for name in ("vineflower", "cfr")
        ]
        verified_decompilers = [
            item
            for item in decompilers
            if item.get("available") and item.get("checksum_verified")
        ]
        if not java.get("available"):
            blockers.append("Java 17 isolado não está disponível.")
        if not verified_decompilers:
            blockers.append("Nenhum decompilador com checksum aprovado está disponível.")

        capacity = dict(coverage.get("capacity") or {})
        if capacity.get("state") == "insufficient":
            blockers.append("O espaço livre ou orçamento do índice é insuficiente.")
        elif capacity.get("state") == "tight":
            warnings.append("A capacidade do índice está próxima do limite configurado.")
        if not coverage.get("classpath_order_known"):
            warnings.append(
                "A ordem efetiva do classpath ainda não foi confirmada; conflitos "
                "precisam continuar sinalizados."
            )

        return {
            "ready": not blockers,
            "release_id": str(release.get("release_id") or release_id),
            "release_manifest_sha256": str(
                manifest.get("release_manifest_sha256") or ""
            ),
            "release_state": str(release.get("state") or "unknown"),
            "freshness": str(release.get("freshness") or "unknown"),
            "jar_count": jar_count,
            "expected_jar_count": expected,
            "analysis_scope": analysis_scope,
            "covered_jar_count": int(coverage.get("covered_jar_count") or 0),
            "remaining_jar_count": int(coverage.get("remaining_jar_count") or 0),
            "capacity": capacity,
            "java": java,
            "verified_decompilers": verified_decompilers,
            "classpath_status": str(
                coverage.get("classpath_status") or "unknown"
            ),
            "blockers": list(dict.fromkeys(blockers)),
            "warnings": list(dict.fromkeys(warnings)),
            "guarantees": {
                "requires_model": False,
                "requires_network": False,
                "source_is_read_only": True,
                "explicit_release_required": True,
                "global_java_concurrency": 1,
            },
        }


__all__ = ["OfflineCodePreflight"]

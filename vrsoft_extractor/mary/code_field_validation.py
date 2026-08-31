"""Offline acceptance report for release-scoped ERP code indexes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .code_index import JavaCodeIndex
from .code_processing_audit import CodeProcessingAudit
from .erp_releases import ErpReleaseCatalog, validate_release_id


class CodeFieldValidationError(RuntimeError):
    """Controlled invalid validation request."""


class CodeFieldValidator:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.catalog = ErpReleaseCatalog(self.root)
        self.index = JavaCodeIndex(self.root, catalog=self.catalog)
        self.audit = CodeProcessingAudit(self.root)

    def validate(
        self,
        release_ids: Iterable[str],
        *,
        probe_symbol: str = "",
        require_distinct_hashes: bool = False,
    ) -> dict[str, Any]:
        releases = list(
            dict.fromkeys(validate_release_id(str(item)) for item in release_ids)
        )
        if not releases:
            raise CodeFieldValidationError("Informe ao menos uma release.")
        if len(releases) > 3:
            raise CodeFieldValidationError(
                "A validaÃ§Ã£o local aceita no mÃ¡ximo trÃªs releases simultÃ¢neas."
            )
        probe = str(probe_symbol or "").strip()
        blockers: list[str] = []
        warnings: list[str] = []
        reports: list[dict[str, Any]] = []
        hashes: list[str] = []
        for release_id in releases:
            release = self.catalog.status(release_id, full_hash=True)
            manifest = self.catalog.load_manifest(release_id)
            coverage = self.index.coverage(release_id)
            release_hash = str(manifest.get("release_manifest_sha256") or "")
            hashes.append(release_hash)
            if release.get("state") != "ready":
                blockers.append(f"{release_id}: inventÃ¡rio nÃ£o estÃ¡ pronto.")
            if release.get("freshness") != "fresh":
                blockers.append(f"{release_id}: origem nÃ£o estÃ¡ fresca.")
            if int(coverage.get("covered_jar_count") or 0) != int(
                coverage.get("expected_jar_count") or 0
            ):
                blockers.append(f"{release_id}: cobertura de JARs incompleta.")
            matches = (
                self.index.search(probe, release_id=release_id, limit=5)
                if probe
                else []
            )
            if probe and not matches:
                blockers.append(
                    f"{release_id}: sÃ­mbolo de prova nÃ£o encontrado: {probe}."
                )
            if any(str(item.get("release_id") or "") != release_id for item in matches):
                blockers.append(f"{release_id}: resultado contaminado por outra release.")
            latest = self.audit.latest(release_id=release_id)
            telemetry = (
                dict((latest.get("details") or {}).get("telemetry") or {})
                if isinstance(latest, dict)
                else {}
            )
            if not telemetry:
                warnings.append(f"{release_id}: ainda nÃ£o hÃ¡ telemetria de campo.")
            reports.append(
                {
                    "release_id": release_id,
                    "release_manifest_sha256": release_hash,
                    "freshness": release.get("freshness", "unknown"),
                    "covered_jar_count": int(
                        coverage.get("covered_jar_count") or 0
                    ),
                    "expected_jar_count": int(
                        coverage.get("expected_jar_count") or 0
                    ),
                    "probe_symbol": probe,
                    "probe_match_count": len(matches),
                    "probe_citations": [
                        str(item.get("citation") or "") for item in matches
                    ],
                    "probe_source_hashes": sorted(
                        {
                            str(item.get("source_sha256") or "")
                            for item in matches
                            if item.get("source_sha256")
                        }
                    ),
                    "telemetry": telemetry,
                }
            )
        distinct_hashes = len(set(hashes)) == len(hashes)
        if require_distinct_hashes and len(releases) > 1 and not distinct_hashes:
            blockers.append(
                "As releases selecionadas possuem o mesmo hash de manifesto."
            )
        return {
            "ready": not blockers,
            "workspace": str(self.root),
            "release_count": len(releases),
            "releases": reports,
            "release_hashes_distinct": distinct_hashes,
            "blockers": blockers,
            "warnings": warnings,
            "offline_contract": {
                "requires_network": False,
                "requires_model": False,
                "source_jars_read_only": True,
                "release_scoped_queries": True,
                "max_simultaneous_releases": 3,
            },
        }


__all__ = ["CodeFieldValidationError", "CodeFieldValidator"]

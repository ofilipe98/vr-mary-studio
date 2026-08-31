from __future__ import annotations

from pathlib import Path

from vrsoft_extractor.mary.code_offline_preflight import OfflineCodePreflight


class _Catalog:
    def __init__(
        self,
        *,
        freshness: str = "fresh",
        jar_count: int = 46,
        analysis_scope: str = "full_release",
    ) -> None:
        self.freshness = freshness
        self.jar_count = jar_count
        self.analysis_scope = analysis_scope

    def status(self, release_id: str):
        return {
            "release_id": release_id,
            "state": "ready",
            "freshness": self.freshness,
            "jar_count": self.jar_count,
            "expected_jar_count": self.jar_count,
            "warnings": [],
        }

    def load_manifest(self, release_id: str):
        return {
            "release_id": release_id,
            "release_manifest_sha256": "a" * 64,
            "analysis_scope": self.analysis_scope,
            "artifacts": [
                {"relative_path": f"jar-{index}.jar", "sha256": f"{index:064x}"}
                for index in range(self.jar_count)
            ],
        }


class _Coverage:
    def __init__(self, *, capacity: str = "ready") -> None:
        self.capacity = capacity

    def status(self, _release_id: str):
        return {
            "covered_jar_count": 12,
            "remaining_jar_count": 34,
            "capacity": {
                "state": self.capacity,
                "free_disk_bytes": 100 * 1024**3,
            },
            "classpath_order_known": False,
            "classpath_status": "partial",
        }


class _Toolchain:
    def doctor(self):
        return {
            "java": {"available": True, "version": "17.0.20"},
            "vineflower": {
                "available": True,
                "checksum_verified": True,
                "version": "1.12.0",
            },
            "cfr": {
                "available": False,
                "checksum_verified": False,
                "version": "0.152",
            },
        }


def test_offline_preflight_is_ready_with_one_verified_decompiler(
    tmp_path: Path,
) -> None:
    result = OfflineCodePreflight(
        tmp_path,
        catalog=_Catalog(),
        coverage=_Coverage(),
        toolchain=_Toolchain(),
    ).run("release-1")

    assert result["ready"] is True
    assert result["release_manifest_sha256"] == "a" * 64
    assert result["verified_decompilers"][0]["version"] == "1.12.0"
    assert result["guarantees"] == {
        "requires_model": False,
        "requires_network": False,
        "source_is_read_only": True,
        "explicit_release_required": True,
        "global_java_concurrency": 1,
    }
    assert "classpath" in " ".join(result["warnings"])


def test_offline_preflight_blocks_stale_release_and_insufficient_capacity(
    tmp_path: Path,
) -> None:
    result = OfflineCodePreflight(
        tmp_path,
        catalog=_Catalog(freshness="stale"),
        coverage=_Coverage(capacity="insufficient"),
        toolchain=_Toolchain(),
    ).run("release-1")

    assert result["ready"] is False
    assert any("desatualizada" in item for item in result["blockers"])
    assert any("insuficiente" in item for item in result["blockers"])


def test_offline_preflight_accepts_and_labels_single_jar_scope(tmp_path: Path) -> None:
    result = OfflineCodePreflight(
        tmp_path,
        catalog=_Catalog(jar_count=1, analysis_scope="single_jar"),
        coverage=_Coverage(),
        toolchain=_Toolchain(),
    ).run("release-jar")

    assert result["ready"] is True
    assert result["expected_jar_count"] == 1
    assert result["analysis_scope"] == "single_jar"
    assert any("Escopo parcial" in item for item in result["warnings"])

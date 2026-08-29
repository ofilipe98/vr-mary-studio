from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.erp_releases import (
    ErpReleaseCatalog,
    ErpReleaseError,
    parse_manifest_bytes,
)


def _jar(
    path: Path,
    *,
    classes: tuple[str, ...] = ("br/com/vr/App.class",),
    version: str = "1.0",
    class_path: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = [
        "Manifest-Version: 1.0",
        "Main-Class: br.com.vr.App",
        f"Implementation-Version: {version}",
    ]
    if class_path:
        manifest.append(f"Class-Path: {class_path}")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "\r\n".join(manifest) + "\r\n")
        for class_name in classes:
            archive.writestr(class_name, b"bytecode")


def test_import_release_builds_deterministic_manifest_and_artifact_cache(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ERP" / "releases" / "2026.08" / "jars"
    _jar(source / "VRMaster.jar", class_path="lib/VRCore.jar")
    _jar(source / "lib" / "VRCore.jar", classes=("br/com/vr/Core.class",))

    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=2)
    first = catalog.import_release("2026.08")
    second = catalog.import_release("2026.08")

    assert first["state"] == "ready"
    assert first["jar_count"] == 2
    assert first["classpath_status"] == "partial"
    assert first["classpath_order_known"] is False
    assert first["release_manifest_sha256"] == second["release_manifest_sha256"]
    assert catalog.status("2026.08")["freshness"] == "fresh"
    for artifact in first["artifacts"]:
        metadata = (
            tmp_path
            / "indice"
            / "codigo"
            / "artifacts"
            / artifact["sha256"]
            / "artifact.json"
        )
        assert metadata.is_file()
    storage = catalog.storage_status()
    assert storage["max_releases"] == 3
    assert storage["budget_bytes"] == first["source_size_bytes"] * 10


def test_import_release_marks_missing_jar_and_duplicate_class(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ERP" / "releases" / "cliente-a" / "jars"
    _jar(source / "A.jar", classes=("br/com/vr/Shared.class",))
    _jar(source / "B.jar", classes=("br/com/vr/Shared.class",))

    manifest = ErpReleaseCatalog(tmp_path, expected_jar_count=3).import_release(
        "cliente-a"
    )

    assert manifest["state"] == "incomplete"
    assert manifest["duplicate_class_count"] == 1
    assert any("Esperados 3" in warning for warning in manifest["warnings"])
    assert any("classpath" in warning for warning in manifest["warnings"])


def test_status_detects_changed_and_missing_source(tmp_path: Path) -> None:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    jar = source / "ERP.jar"
    _jar(jar)
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    catalog.import_release("r1")

    _jar(jar, version="2.0")
    assert catalog.status("r1", full_hash=True)["freshness"] == "stale"

    jar.unlink()
    source.rmdir()
    status = catalog.status("r1")
    assert status["freshness"] == "missing"


def test_invalid_jar_is_recorded_without_hiding_partial_inventory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ERP" / "releases" / "broken" / "jars"
    source.mkdir(parents=True)
    (source / "broken.jar").write_bytes(b"not-a-zip")

    manifest = ErpReleaseCatalog(tmp_path, expected_jar_count=1).import_release(
        "broken"
    )

    assert manifest["state"] == "incomplete"
    assert manifest["invalid_jar_count"] == 1
    assert "BadZipFile" in manifest["artifacts"][0]["error"]


def test_remove_requires_approval_preserves_sources_and_shared_artifacts(
    tmp_path: Path,
) -> None:
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    first_source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    second_source = tmp_path / "ERP" / "releases" / "r2" / "jars"
    _jar(first_source / "ERP.jar")
    _jar(second_source / "ERP.jar")
    first = catalog.import_release("r1")
    catalog.import_release("r2")
    artifact_dir = (
        tmp_path / "indice" / "codigo" / "artifacts" / first["artifacts"][0]["sha256"]
    )

    with pytest.raises(ErpReleaseError, match="aprovação explícita"):
        catalog.remove_index("r1")

    result = catalog.remove_index("r1", approved=True)
    assert result["source_jars_removed"] is False
    assert first_source.is_dir()
    assert artifact_dir.is_dir()

    catalog.remove_index("r2", approved=True)
    assert not artifact_dir.exists()


def test_release_id_cannot_escape_index_root(tmp_path: Path) -> None:
    catalog = ErpReleaseCatalog(tmp_path)
    with pytest.raises(ErpReleaseError, match="Identificador"):
        catalog.import_release("../outside")


def test_catalog_enforces_three_release_limit_without_automatic_deletion(
    tmp_path: Path,
) -> None:
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1, max_releases=1)
    first = tmp_path / "ERP" / "releases" / "r1" / "jars"
    second = tmp_path / "ERP" / "releases" / "r2" / "jars"
    _jar(first / "ERP.jar")
    _jar(second / "ERP.jar")
    catalog.import_release("r1")

    with pytest.raises(ErpReleaseError, match="limite de 1 releases"):
        catalog.import_release("r2")

    assert first.is_dir()
    assert second.is_dir()


def test_manifest_parser_unfolds_continuation_lines() -> None:
    parsed = parse_manifest_bytes(
        b"Manifest-Version: 1.0\r\nClass-Path: lib/A.jar lib/\r\n B.jar\r\n"
    )
    assert parsed["Class-Path"] == "lib/A.jar lib/B.jar"


def test_manifest_written_with_portable_source_path(tmp_path: Path) -> None:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    _jar(source / "ERP.jar")
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    catalog.import_release("r1")

    payload = json.loads(
        (tmp_path / "indice" / "codigo" / "releases" / "r1" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["source_dir"] == "ERP/releases/r1/jars"

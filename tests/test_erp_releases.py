from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from vrsoft_extractor.mary.cli import build_parser, main as cli_main
from vrsoft_extractor.mary.erp_releases import (
    ErpReleaseCatalog,
    ErpReleaseError,
    normalize_class_entry,
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


def test_storage_budget_multiplier_is_configurable_but_capped_at_ten(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    _jar(source / "ERP.jar")
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    manifest = catalog.import_release("r1")

    status = catalog.set_storage_budget_multiplier(5)

    assert status["budget_bytes"] == manifest["source_size_bytes"] * 5
    with pytest.raises(ErpReleaseError, match="entre 1x e 10x"):
        catalog.set_storage_budget_multiplier(11)


def test_manifest_parser_unfolds_continuation_lines() -> None:
    parsed = parse_manifest_bytes(
        b"Manifest-Version: 1.0\r\nClass-Path: lib/A.jar lib/\r\n B.jar\r\n"
    )
    assert parsed["Class-Path"] == "lib/A.jar lib/B.jar"


def test_normalize_class_entry_understands_multi_release_jars() -> None:
    assert normalize_class_entry("br/com/vr/App.class") == ("br.com.vr.App", 0)
    assert normalize_class_entry("META-INF/versions/17/br/com/vr/App.class") == (
        "br.com.vr.App",
        17,
    )
    assert normalize_class_entry("META-INF/MANIFEST.MF") is None


def test_deep_class_metrics_detect_content_dedup_and_conflicts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    source.mkdir(parents=True)
    with zipfile.ZipFile(source / "A.jar", "w") as archive:
        archive.writestr("br/com/vr/App.class", b"version-a")
        archive.writestr(
            "META-INF/versions/17/br/com/vr/App.class",
            b"version-a-17",
        )
    with zipfile.ZipFile(source / "B.jar", "w") as archive:
        archive.writestr("br/com/vr/App.class", b"version-b")
        archive.writestr("br/com/vr/Copy.class", b"version-b")
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=2)
    catalog.import_release("r1")

    report = catalog.inspect_class_metrics("r1", ("A.jar", "B.jar"))

    assert report["total_class_entries"] == 4
    assert report["unique_logical_class_count"] == 2
    assert report["duplicate_logical_class_count"] == 1
    assert report["conflicting_logical_class_count"] == 1
    assert report["unique_class_content_count"] == 3
    assert report["duplicate_content_entries"] == 1
    assert report["multi_release_entries"] == 1
    assert report["conflict_samples"][0]["class"] == "br.com.vr.App"
    assert (
        tmp_path
        / "indice"
        / "codigo"
        / "releases"
        / "r1"
        / "class-metrics.json"
    ).is_file()


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


def test_snapshot_release_copies_and_verifies_external_jars(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "vr" / "exec"
    first = source / "VRMaster.jar"
    second = source / "lib" / "VRCore.jar"
    _jar(first, version="1.0")
    _jar(second, version="1.0")
    source_bytes = {
        path.relative_to(source): path.read_bytes() for path in (first, second)
    }
    source_mtimes = {
        path.relative_to(source): path.stat().st_mtime_ns for path in (first, second)
    }

    catalog = ErpReleaseCatalog(workspace, expected_jar_count=2)
    result = catalog.snapshot_release("2026.08", source)
    managed = workspace / "ERP" / "releases" / "2026.08" / "jars"

    assert result["state"] == "ready"
    assert result["snapshot"]["verified"] is True
    assert result["snapshot"]["jar_count"] == 2
    assert result["source_dir"] == "ERP/releases/2026.08/jars"
    assert result["source_origin_dir"] == str(source.resolve())
    assert result["snapshot_managed"] is True
    assert (managed / "VRMaster.jar").read_bytes() == source_bytes[Path("VRMaster.jar")]
    assert (managed / "lib" / "VRCore.jar").read_bytes() == source_bytes[
        Path("lib/VRCore.jar")
    ]
    assert {
        path.relative_to(source): path.stat().st_mtime_ns for path in (first, second)
    } == source_mtimes
    persisted = catalog.load_manifest("2026.08")
    assert persisted["snapshot"]["verified"] is True

    _jar(first, version="2.0")
    assert catalog.status("2026.08", full_hash=True)["freshness"] == "fresh"


def test_snapshot_release_accepts_one_explicitly_selected_jar(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "vr" / "exec"
    selected = source / "VRPdv.jar"
    ignored = source / "VRMaster.jar"
    _jar(selected, version="4.4.101")
    _jar(ignored, version="4.4.101")

    result = ErpReleaseCatalog(
        workspace,
        expected_jar_count=1,
    ).snapshot_release(
        "4.4.101-vrpdv",
        selected,
        analysis_scope="single_jar",
    )

    managed = workspace / "ERP" / "releases" / "4.4.101-vrpdv" / "jars"
    assert result["state"] == "ready"
    assert result["analysis_scope"] == "single_jar"
    assert result["expected_jar_count"] == 1
    assert result["jar_count"] == 1
    assert result["artifacts"][0]["relative_path"] == "VRPdv.jar"
    assert (managed / "VRPdv.jar").is_file()
    assert not (managed / "VRMaster.jar").exists()
    assert selected.is_file()
    assert ignored.is_file()


def test_snapshot_release_requires_exact_count_and_never_overwrites(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "vr" / "exec"
    _jar(source / "ERP.jar")
    catalog = ErpReleaseCatalog(workspace, expected_jar_count=2)

    with pytest.raises(ErpReleaseError, match="exatamente 2 JARs"):
        catalog.snapshot_release("r1", source)
    assert not (workspace / "ERP" / "releases" / "r1").exists()

    _jar(source / "VRPdv.jar")
    catalog.snapshot_release("r1", source)
    managed = workspace / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
    before = managed.read_bytes()

    with pytest.raises(ErpReleaseError, match="release já está inventariada"):
        catalog.snapshot_release("r1", source)
    assert managed.read_bytes() == before

    external = tmp_path / "external"
    _jar(external / "A.jar")
    _jar(external / "B.jar")
    catalog.import_release("external-release", external)
    with pytest.raises(ErpReleaseError, match="release já está inventariada"):
        catalog.snapshot_release("external-release", external)


def test_snapshot_release_rejects_unreadable_jar_before_copy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "vr" / "exec"
    source.mkdir(parents=True)
    (source / "broken.jar").write_bytes(b"not-a-zip")

    with pytest.raises(ErpReleaseError, match="JAR ilegível"):
        ErpReleaseCatalog(workspace, expected_jar_count=1).snapshot_release(
            "broken", source
        )

    assert not (workspace / "ERP" / "releases" / "broken").exists()


def test_snapshot_release_cli_uses_explicit_local_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "vr" / "exec"
    _jar(source / "ERP.jar")

    with patch.dict("os.environ", {}, clear=True):
        assert cli_main(
            [
                "--root",
                str(workspace),
                "snapshot-erp-release",
                "r1",
                "--source",
                str(source),
                "--expected-jars",
                "1",
            ]
        ) == 0
    assert (workspace / "ERP" / "releases" / "r1" / "jars" / "ERP.jar").is_file()


def test_snapshot_release_cli_accepts_one_jar_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    selected = tmp_path / "vr" / "exec" / "VRPdv.jar"
    _jar(selected)

    assert cli_main(
        [
            "--root",
            str(workspace),
            "snapshot-erp-release",
            "r1-vrpdv",
            "--source",
            str(selected),
            "--expected-jars",
            "1",
        ]
    ) == 0
    manifest = ErpReleaseCatalog(workspace).load_manifest("r1-vrpdv")
    assert manifest["analysis_scope"] == "single_jar"
    assert manifest["artifacts"][0]["relative_path"] == "VRPdv.jar"


def test_snapshot_release_cli_defaults_to_vr_exec() -> None:
    args = build_parser().parse_args(["snapshot-erp-release", "r1"])

    assert args.source == r"C:\vr\exec"

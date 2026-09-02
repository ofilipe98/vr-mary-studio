from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from vrsoft_extractor.mary.cli import build_parser, main as cli_main
from vrsoft_extractor.mary.erp_releases import (
    ErpReleaseCatalog,
    ErpReleaseError,
    detect_jar_release,
    normalize_class_entry,
    parse_java_properties,
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


def _vr_jar(
    path: Path,
    version: tuple[int, int, int, int],
    *,
    app_date: str = "31/08/2026",
) -> None:
    _jar(path, version=".".join(str(item) for item in version))
    major, minor, release, build = version
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            f"{path.stem.casefold()}.properties",
            "\n".join(
                (
                    f"versao.major = {major}",
                    f"versao.minor = {minor}",
                    f"versao.release = {release}",
                    f"versao.build = {build}",
                    "versao.beta = 0",
                    f"app.data = {app_date}",
                    "posthog.api.key = must-not-be-returned",
                )
            ),
        )


def test_detect_jar_release_uses_matching_vr_properties_without_leaking_other_keys(
    tmp_path: Path,
) -> None:
    jar = tmp_path / "VRMaster.jar"
    _vr_jar(jar, (4, 4, 102, 0))

    identity = detect_jar_release(jar)

    assert identity["application"] == "VRMaster"
    assert identity["application_version"] == "4.4.102.0"
    assert identity["application_date_iso"] == "2026-08-31"
    assert identity["version_properties_entry"] == "vrmaster.properties"
    assert identity["version_detected"] is True
    assert "posthog" not in json.dumps(identity).casefold()


def test_java_properties_parser_keeps_only_release_metadata() -> None:
    parsed = parse_java_properties(
        b"versao.major=4\nversao.minor : 4\napp.data=31/08/2026\nsecret=x\n"
    )

    assert parsed == {
        "versao.major": "4",
        "versao.minor": "4",
        "app.data": "31/08/2026",
    }


def test_detect_package_builds_automatic_id_and_falls_back_for_missing_properties(
    tmp_path: Path,
) -> None:
    source = tmp_path / "package"
    _vr_jar(source / "VRMaster.jar", (4, 4, 102, 0))
    _jar(source / "lib" / "VRMobileServer.jar")

    package = ErpReleaseCatalog(tmp_path, expected_jar_count=2).detect_package(source)

    assert package["complete"] is True
    assert package["detected_version_count"] == 1
    assert package["fallback_count"] == 1
    assert package["suggested_release_id"].startswith("erp-2026.08.31-")
    mobile = next(
        item for item in package["components"] if item["application"] == "VRMobileServer"
    )
    assert mobile["application_version"] == "unknown"
    assert "SHA-256" in mobile["warning"]


def test_detected_snapshot_categorizes_full_package_by_application_and_version(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "full"
    _vr_jar(source / "VRMaster.jar", (4, 4, 102, 0))
    _vr_jar(source / "lib" / "VRCore.jar", (4, 4, 7, 3), app_date="30/08/2026")
    catalog = ErpReleaseCatalog(workspace, expected_jar_count=2)

    manifest = catalog.snapshot_detected_release(source)

    release_id = manifest["release_id"]
    managed = workspace / "ERP" / "releases" / release_id / "jars"
    assert manifest["state"] == "ready"
    assert manifest["auto_detected"] is True
    assert manifest["categorization"] == "application/version"
    assert manifest["base_release_id"] == ""
    assert manifest["package_jar_count"] == 2
    assert manifest["carried_forward_jar_count"] == 0
    assert (managed / "VRMaster" / "4.4.102.0" / "VRMaster.jar").is_file()
    assert (managed / "VRCore" / "4.4.7.3" / "VRCore.jar").is_file()
    assert {item["application"] for item in manifest["component_versions"]} == {
        "VRMaster",
        "VRCore",
    }


def test_detected_snapshot_composes_partial_package_over_latest_complete_base(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    full = tmp_path / "full"
    _vr_jar(full / "VRMaster.jar", (4, 4, 101, 0), app_date="30/08/2026")
    _vr_jar(full / "VRCore.jar", (4, 4, 7, 3), app_date="30/08/2026")
    catalog = ErpReleaseCatalog(workspace, expected_jar_count=2)
    base = catalog.snapshot_detected_release(full)

    update = tmp_path / "update"
    _vr_jar(update / "VRMaster.jar", (4, 4, 102, 0))
    composed = catalog.snapshot_detected_release(update)

    assert composed["analysis_scope"] == "incremental_release"
    assert composed["base_release_id"] == base["release_id"]
    assert composed["updated_applications"] == ["VRMaster"]
    assert composed["package_jar_count"] == 1
    assert composed["carried_forward_jar_count"] == 1
    assert composed["jar_count"] == 2
    versions = {
        item["application"]: (item["version"], item["origin"])
        for item in composed["component_versions"]
    }
    assert versions == {
        "VRCore": ("4.4.7.3", "base"),
        "VRMaster": ("4.4.102.0", "package"),
    }
    managed = workspace / "ERP" / "releases" / composed["release_id"] / "jars"
    assert (managed / "VRMaster" / "4.4.102.0" / "VRMaster.jar").is_file()
    assert (managed / "VRCore" / "4.4.7.3" / "VRCore.jar").is_file()


def test_detected_partial_package_requires_complete_base(tmp_path: Path) -> None:
    source = tmp_path / "partial"
    _vr_jar(source / "VRMaster.jar", (4, 4, 102, 0))

    with pytest.raises(ErpReleaseError, match="release-base completa"):
        ErpReleaseCatalog(tmp_path / "workspace", expected_jar_count=2).snapshot_detected_release(
            source
        )


def test_detected_single_jar_uses_application_release_and_hash(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    jar = tmp_path / "VRPdv.jar"
    _vr_jar(jar, (4, 4, 25, 0))

    manifest = ErpReleaseCatalog(
        workspace,
        expected_jar_count=1,
    ).snapshot_detected_release(jar, analysis_scope="single_jar")

    assert manifest["release_id"].startswith("VRPdv-4.4.25.0-")
    assert manifest["analysis_scope"] == "single_jar"
    assert manifest["updated_applications"] == ["VRPdv"]


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


def test_storage_budget_sums_all_retained_release_sources(tmp_path: Path) -> None:
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    first_source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    second_source = tmp_path / "ERP" / "releases" / "r2" / "jars"
    _jar(first_source / "A.jar", classes=("br/vr/A.class",))
    _jar(second_source / "B.jar", classes=("br/vr/B.class", "br/vr/C.class"))
    first = catalog.import_release("r1")
    second = catalog.import_release("r2")

    status = catalog.set_storage_budget_multiplier(8)

    assert status["budget_bytes"] == (
        first["source_size_bytes"] + second["source_size_bytes"]
    ) * 8
    catalog.remove_index("r1", approved=True)
    assert catalog.storage_status()["budget_bytes"] == second["source_size_bytes"] * 8


def test_orphan_cleanup_preserves_live_payload_and_source_jars(tmp_path: Path) -> None:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    jar = source / "ERP.jar"
    _jar(jar)
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    catalog.import_release("r1")
    decompilation = tmp_path / "indice" / "codigo" / "decompilation"
    live = decompilation / "plan-live"
    orphan = decompilation / "plan-orphan"
    live.mkdir(parents=True)
    orphan.mkdir(parents=True)
    (live / "Live.java").write_bytes(b"live")
    (orphan / "Old.java").write_bytes(b"orphaned")
    database = tmp_path / "indice" / "codigo" / "processing.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE decompilation_plans (plan_id TEXT PRIMARY KEY)")
        connection.execute(
            "INSERT INTO decompilation_plans (plan_id) VALUES ('plan-live')"
        )

    inspection = catalog.inspect_orphaned_index_data()

    assert inspection["live_payload_bytes"] == 4
    assert [item["path"] for item in inspection["items"]] == [
        "indice/codigo/decompilation/plan-orphan"
    ]
    with pytest.raises(ErpReleaseError, match="aprovação explícita"):
        catalog.purge_orphaned_index_data()

    result = catalog.purge_orphaned_index_data(approved=True)

    assert result["removed_item_count"] == 1
    assert not orphan.exists()
    assert live.is_dir()
    assert jar.is_file()
    assert result["source_jars_removed"] is False


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


def test_detect_release_cli_reports_versions_without_model(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "package"
    _vr_jar(source / "VRMaster.jar", (4, 4, 102, 0))

    assert cli_main(
        [
            "--root",
            str(workspace),
            "detect-erp-release",
            "--source",
            str(source),
            "--expected-jars",
            "1",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["complete"] is True
    assert payload["components"][0]["application"] == "VRMaster"
    assert payload["components"][0]["application_version"] == "4.4.102.0"


def test_snapshot_release_cli_auto_detects_when_id_is_omitted(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    jar = tmp_path / "VRPdv.jar"
    _vr_jar(jar, (4, 4, 25, 0))

    assert cli_main(
        [
            "--root",
            str(workspace),
            "snapshot-erp-release",
            "--source",
            str(jar),
            "--expected-jars",
            "1",
        ]
    ) == 0
    statuses = ErpReleaseCatalog(workspace, expected_jar_count=1).list_statuses()
    assert len(statuses) == 1
    release_id = statuses[0]["release_id"]
    assert release_id.startswith("VRPdv-4.4.25.0-")
    managed = workspace / "ERP" / "releases" / release_id / "jars"
    assert (managed / "VRPdv" / "4.4.25.0" / "VRPdv.jar").is_file()


def test_detected_snapshot_rolls_back_managed_copy_when_inventory_fails(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    jar = tmp_path / "VRMaster.jar"
    _vr_jar(jar, (4, 4, 102, 0))
    catalog = ErpReleaseCatalog(workspace, expected_jar_count=1)

    with patch.object(catalog, "import_release", side_effect=RuntimeError("falha")):
        with pytest.raises(RuntimeError, match="falha"):
            catalog.snapshot_detected_release(jar, analysis_scope="single_jar")

    releases = workspace / "ERP" / "releases"
    assert not any(path.is_dir() for path in releases.iterdir())

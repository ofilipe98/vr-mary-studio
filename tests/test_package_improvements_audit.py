"""Regression coverage for package deletion and portable source ingestion."""
import hashlib
import sqlite3

import pytest

from vrsoft_extractor.mary import decompiled_detection as detection
from vrsoft_extractor.mary.apps_catalog import AppsCatalogError, AppsCatalogStore, UNIDENTIFIED_VERSION
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog, ErpReleaseError


def source(root, name="Main"):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.java").write_text(
        f"package vr.master; import java.util.List; public class {name} {{ public void execute() {{}} }}",
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("identifier", ["..", "../outside", "a/b", "C:/outside", "."])
def test_reject_unsafe_paths_before_mutation(tmp_path, identifier):
    workspace = tmp_path / "workspace"
    src = source(tmp_path / "src")
    with pytest.raises(ValueError):
        detection.import_decompiled_source(workspace, src, release_id=identifier)
    with pytest.raises(ErpReleaseError):
        ErpReleaseCatalog(workspace).unlink_package(identifier, delete_data=True)
    assert (src / "Main.java").is_file()
    assert not (workspace / "indice/codigo/decompilation").exists()


def test_missing_package_never_purges(tmp_path, monkeypatch):
    catalog = ErpReleaseCatalog(tmp_path)
    monkeypatch.setattr(catalog, "_purge_release_processing_data", lambda *a, **k: pytest.fail("purged missing package"))
    with pytest.raises(ErpReleaseError):
        catalog.unlink_package("missing", delete_data=True)


def test_import_symbols_relations_variant_filter_and_duplicate(tmp_path):
    ws, src = tmp_path / "ws", source(tmp_path / "src")
    result = detection.import_decompiled_source(ws, src, release_id="one")
    variant = result["package"]["composition"][0]["sha256"]
    with sqlite3.connect(ws / "indice/codigo/processing.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM code_sources WHERE artifact_sha256 = ?", (variant,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM code_symbols WHERE simple_name = 'execute'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM code_relations").fetchone()[0] > 0
    with pytest.raises(ValueError, match="identificador"):
        detection.import_decompiled_source(ws, src, release_id="one")
    assert AppsCatalogStore(ws).get_package("one")


def test_import_failure_rolls_back_sql_catalog_and_files(tmp_path, monkeypatch):
    ws, src = tmp_path / "ws", source(tmp_path / "src")
    source(src, "Second")
    parser = detection.parse_java_source
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("parser failed")
        return parser(*args, **kwargs)

    monkeypatch.setattr(detection, "parse_java_source", fail_second)
    with pytest.raises(RuntimeError, match="parser failed"):
        detection.import_decompiled_source(ws, src, release_id="one")
    assert not AppsCatalogStore(ws).get_package("one")
    assert not (ws / "indice/codigo/decompilation/one").exists()
    with sqlite3.connect(ws / "indice/codigo/processing.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM code_sources").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM decompilation_plans").fetchone()[0] == 0


def test_unlink_failure_is_reported_and_package_remains(tmp_path, monkeypatch):
    ws, src = tmp_path / "ws", source(tmp_path / "src")
    detection.import_decompiled_source(ws, src, release_id="one")
    catalog = ErpReleaseCatalog(ws)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database locked")

    monkeypatch.setattr(catalog, "_purge_release_processing_data", fail)
    with pytest.raises(sqlite3.OperationalError):
        catalog.unlink_package("one", delete_data=True)
    assert catalog.apps_store.get_package("one")
    assert (ws / "indice/codigo/decompilation/one").exists()


def test_unlink_preserves_sources_referenced_by_another_release(tmp_path):
    ws, src = tmp_path / "ws", source(tmp_path / "src")
    detection.import_decompiled_source(ws, src, release_id="one")
    detection.import_decompiled_source(ws, src, release_id="two")
    with sqlite3.connect(ws / "indice/codigo/processing.sqlite") as conn:
        conn.execute("UPDATE code_sources SET output_reference = 'indice/codigo/decompilation/one/vrmaster' WHERE release_id = 'two'")
    ErpReleaseCatalog(ws).unlink_package("one", delete_data=True)
    assert (ws / "indice/codigo/decompilation/one/vrmaster/Main.java").exists()
    with sqlite3.connect(ws / "indice/codigo/processing.sqlite") as conn:
        assert conn.execute("SELECT release_id FROM code_sources").fetchall() == [("two",)]


def test_detect_resources_and_multiple_apps_without_inventing_versions(tmp_path):
    src = source(tmp_path / "src")
    resources = src / "resources"
    resources.mkdir()
    (resources / "vrmaster.properties").write_text("versao.major=4\nversao.minor=4\nversao.release=102\n")
    result = detection.detect_decompiled_source(src)
    assert result["is_valid"] and result["total_java_files"] == 1
    (resources / "vrmaster.properties").unlink()
    (src / "Other.java").write_text("package vr.adm; public class Other {}")
    result = detection.detect_decompiled_source(src)
    assert result["scope"] == "package"
    assert {app["app_id"] for app in result["applications"]} == {"vrmaster", "vradm"}
    assert all(app["version"] == UNIDENTIFIED_VERSION for app in result["applications"])


@pytest.mark.parametrize("internal", [False, True])
def test_delete_jars_rejects_changed_or_internal_files(tmp_path, internal):
    store = AppsCatalogStore(tmp_path)
    folder = tmp_path / ("indice/codigo/artifacts" if internal else "source")
    folder.mkdir(parents=True)
    jar = folder / "app.jar"
    jar.write_bytes(b"original" if internal else b"replacement")
    store.register_package({"release_id": "one", "artifacts": [{
        "application_key": "vrapp", "version_detected": "1.0", "relative_path": "app.jar",
        "sha256": hashlib.sha256(b"original").hexdigest(),
    }]}, source_path=str(folder))
    with pytest.raises(AppsCatalogError):
        store.delete_source_jars("one")
    assert jar.is_file()


def test_delete_original_jars_preserves_categorized_snapshot(tmp_path):
    from test_erp_releases import _vr_jar

    src = tmp_path / "source"
    original = src / "lib/VRMaster.jar"
    _vr_jar(original, (4, 4, 102, 0))
    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=1)
    manifest = catalog.snapshot_detected_release(src)
    snapshot = catalog.paths.source_for(manifest["release_id"]) / manifest["artifacts"][0]["relative_path"]
    assert snapshot.exists()
    result = catalog.delete_source_jars(manifest["release_id"])
    assert result["deleted_count"] == 1
    assert not original.exists()
    assert snapshot.exists()

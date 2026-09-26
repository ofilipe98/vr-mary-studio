"""Regression coverage for package deletion and portable source ingestion."""
import hashlib
import sqlite3

import pytest

from test_decompiled_detection import _PORTABLE_BODY, _minimal_manifest, _write_portable_zip

from vrsoft_extractor.mary import decompiled_detection as detection
from vrsoft_extractor.mary.apps_catalog import AppsCatalogError, AppsCatalogStore
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog, ErpReleaseError


def portable_archive(root, name="Pacote-decompiled.zip"):
    archive = root / name
    _write_portable_zip(
        archive,
        _minimal_manifest(),
        {"sources/0001/br/App.java": _PORTABLE_BODY},
    )
    return archive


@pytest.mark.parametrize("identifier", ["..", "../outside", "a/b", "C:/outside", "."])
def test_reject_unsafe_paths_before_mutation(tmp_path, identifier):
    workspace = tmp_path / "workspace"
    archive = portable_archive(tmp_path)
    with pytest.raises(ValueError):
        detection.import_decompiled_package_archive(workspace, archive, release_id=identifier)
    with pytest.raises(ErpReleaseError):
        ErpReleaseCatalog(workspace).unlink_package(identifier, delete_data=True)
    assert archive.is_file()
    assert not (workspace / "indice/codigo/decompilation").exists()


def test_missing_package_never_purges(tmp_path, monkeypatch):
    catalog = ErpReleaseCatalog(tmp_path)
    monkeypatch.setattr(catalog, "_purge_release_processing_data", lambda *a, **k: pytest.fail("purged missing package"))
    with pytest.raises(ErpReleaseError):
        catalog.unlink_package("missing", delete_data=True)


def test_unlink_failure_is_reported_and_package_remains(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    detection.import_decompiled_package_archive(
        ws, portable_archive(tmp_path), release_id="one", package_name="One"
    )
    catalog = ErpReleaseCatalog(ws)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database locked")

    monkeypatch.setattr(catalog, "_purge_release_processing_data", fail)
    with pytest.raises(sqlite3.OperationalError):
        catalog.unlink_package("one", delete_data=True)
    assert catalog.apps_store.get_package("one")
    assert (ws / "indice/codigo/decompilation/one").exists()


def test_unlink_preserves_sources_referenced_by_another_release(tmp_path):
    ws = tmp_path / "ws"
    archive = portable_archive(tmp_path)
    detection.import_decompiled_package_archive(ws, archive, release_id="one", package_name="One")
    detection.import_decompiled_package_archive(ws, archive, release_id="two", package_name="Two")
    database = ws / "indice/codigo/processing.sqlite"
    with sqlite3.connect(database) as conn:
        shared_ref = conn.execute(
            "SELECT output_reference FROM code_sources WHERE release_id = 'one' LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "UPDATE code_sources SET output_reference = ? WHERE release_id = 'two'",
            (shared_ref,),
        )
    ErpReleaseCatalog(ws).unlink_package("one", delete_data=True)
    assert (ws / shared_ref / "br/App.java").is_file()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT release_id FROM code_sources").fetchall() == [("two",)]


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

"""Tests for application import, preview, snapshot, pruning, and bridge concurrency."""
from __future__ import annotations

import os
import queue
import threading
import time
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.application_import import (
    preview_application_import,
    validate_preview_fingerprint,
)
from vrsoft_extractor.mary.apps_catalog import AppsCatalogStore
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.erp_releases import (
    DEFAULT_EXPECTED_JAR_COUNT,
    ErpReleaseCatalog,
    ErpReleaseError,
)
from vrsoft_extractor.mary.frontend.bridges import codeadmin
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from test_apps_catalog_audit import register
from test_erp_releases import _vr_jar, _jar


def wait_until(predicate, timeout=6.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        QApplication.processEvents()
        assert time.monotonic() < deadline, "Qt task did not complete within deadline"
        time.sleep(0.005)


@pytest.fixture
def bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(
        app_dir=tmp_path,
        root=tmp_path / "workspace",
        old_root=tmp_path / "old",
    )
    db = MaryDatabase(
        settings.database_path,
        root=settings.root,
        backup_portable_migration=False,
    )
    chat = ChatBridge(
        settings, db, QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )
    wait_until(lambda: chat._apps_catalog_thread is None)
    yield chat
    chat.close()
    app.processEvents()


# Scenario 1
@pytest.mark.qml
def test_scenario_01_nonexistent_directory_package_fails_fast(bridge, tmp_path):
    non_existent = tmp_path / "does_not_exist_folder"
    result = bridge.previewApplicationImport(str(non_existent), single=False)
    assert result is False
    assert not bridge.releaseSnapshotRunning
    assert "Pasta de JARs não encontrada:" in bridge.releaseSnapshotStatus
    assert bridge._application_preview_thread is None
    assert not bridge._release_snapshot_poll_timer.isActive()


# Scenario 2
@pytest.mark.qml
def test_scenario_02_nonexistent_single_jar_fails_fast(bridge, tmp_path):
    non_existent = tmp_path / "does_not_exist.jar"
    result = bridge.previewApplicationImport(str(non_existent), single=True)
    assert result is False
    assert not bridge.releaseSnapshotRunning
    assert "Arquivo JAR não encontrado:" in bridge.releaseSnapshotStatus
    assert bridge._application_preview_thread is None
    assert not bridge._release_snapshot_poll_timer.isActive()


# Scenario 3
@pytest.mark.qml
def test_scenario_03_non_jar_file_in_single_mode_fails_fast(bridge, tmp_path):
    txt_file = tmp_path / "file.txt"
    txt_file.write_text("not a jar", encoding="utf-8")
    result = bridge.previewApplicationImport(str(txt_file), single=True)
    assert result is False
    assert not bridge.releaseSnapshotRunning
    assert "O arquivo selecionado não é um JAR:" in bridge.releaseSnapshotStatus
    assert bridge._application_preview_thread is None


# Scenario 4
@pytest.mark.qml
def test_scenario_04_file_passed_as_package_dir_fails_fast(bridge, tmp_path):
    txt_file = tmp_path / "file.txt"
    txt_file.write_text("file", encoding="utf-8")
    result = bridge.previewApplicationImport(str(txt_file), single=False)
    assert result is False
    assert not bridge.releaseSnapshotRunning
    assert "A origem especificada não é um diretório:" in bridge.releaseSnapshotStatus
    assert bridge._application_preview_thread is None


# Scenario 5
def test_scenario_05_preview_discovery_and_progress(tmp_path):
    source = tmp_path / "package"
    source.mkdir()
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))
    _vr_jar(source / "vrpdv.jar", (2, 0, 0, 0))

    events = []
    preview = preview_application_import(
        tmp_path / "workspace",
        source,
        single=False,
        progress_callback=events.append,
    )
    assert len(preview["rows"]) == 2
    assert len(preview["fingerprint"]) == 2
    for fp in preview["fingerprint"]:
        assert "sha256" in fp
        assert "size_bytes" in fp
        assert "modified_ns" in fp
        assert "relative_path" in fp
    assert any(ev.get("stage") == "hash" and ev.get("current") == 1 for ev in events)
    assert any(ev.get("stage") == "hash" and ev.get("current") == 2 for ev in events)


# Scenario 6
def test_scenario_06_in_place_byte_change_detected_and_staging_cleaned(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    jar_file = source / "VRApp.jar"
    _vr_jar(jar_file, (1, 0, 0, 0))
    st = jar_file.stat()
    orig_size = st.st_size
    orig_mtime_ns = st.st_mtime_ns

    preview = preview_application_import(tmp_path / "ws", source, single=False)
    known_hashes = {
        item["relative_path"]: item["sha256"] for item in preview["fingerprint"]
    }

    data = bytearray(jar_file.read_bytes())
    data[10] = (data[10] + 1) % 256
    jar_file.write_bytes(bytes(data))
    assert jar_file.stat().st_size == orig_size
    os.utime(jar_file, ns=(orig_mtime_ns, orig_mtime_ns))

    validate_preview_fingerprint(source, preview["fingerprint"], single=False)

    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=1)
    with pytest.raises(ErpReleaseError, match="SHA-256 divergente no snapshot"):
        catalog.snapshot_detected_release(
            source,
            release_id="test-rel",
            known_hashes=known_hashes,
        )

    staging_dirs = list(catalog.paths.source_releases.glob(".*snapshot-*"))
    assert len(staging_dirs) == 0


# Scenario 7
def test_scenario_07_size_change_detected_in_preflight(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    jar_file = source / "VRApp.jar"
    _vr_jar(jar_file, (1, 0, 0, 0))

    preview = preview_application_import(tmp_path / "ws", source, single=False)

    with jar_file.open("ab") as f:
        f.write(b"appended_extra_bytes")

    with pytest.raises(ErpReleaseError, match="mudou após a prévia"):
        validate_preview_fingerprint(source, preview["fingerprint"], single=False)


# Scenario 8
def test_scenario_08_mtime_change_detected_in_preflight(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    jar_file = source / "VRApp.jar"
    _vr_jar(jar_file, (1, 0, 0, 0))

    preview = preview_application_import(tmp_path / "ws", source, single=False)

    st = jar_file.stat()
    new_mtime = st.st_mtime_ns + 5_000_000_000
    os.utime(jar_file, ns=(new_mtime, new_mtime))

    with pytest.raises(ErpReleaseError, match="mudou após a prévia"):
        validate_preview_fingerprint(source, preview["fingerprint"], single=False)


# Scenario 9
def test_scenario_09_reusing_hashes_skips_redundant_sha_on_preflight(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _vr_jar(source / "VRApp.jar", (1, 0, 0, 0))

    preview = preview_application_import(tmp_path / "ws", source, single=False)
    known_hashes = {
        item["relative_path"]: item["sha256"] for item in preview["fingerprint"]
    }

    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=1)

    import vrsoft_extractor.mary.erp_releases as erp_mod
    original_sha256_file = erp_mod.sha256_file
    sha_calls = []

    def mocked_sha(p, *args, **kwargs):
        sha_calls.append(str(p))
        return original_sha256_file(p, *args, **kwargs)

    monkeypatch.setattr(erp_mod, "sha256_file", mocked_sha)

    catalog.snapshot_detected_release(
        source,
        release_id="rel-reuse",
        known_hashes=known_hashes,
    )
    assert len(sha_calls) == 0


# Scenario 10
def test_scenario_10_progress_events_emitted_in_order(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _vr_jar(source / "app1.jar", (1, 0, 0, 0))
    _vr_jar(source / "app2.jar", (2, 0, 0, 0))

    events = []
    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=2)
    catalog.snapshot_detected_release(
        source,
        release_id="rel-prog",
        progress_callback=events.append,
    )

    stages = [ev.get("stage") for ev in events if ev.get("event") == "progress"]
    assert "copy" in stages
    assert "inventory" in stages
    copy_idx = stages.index("copy")
    inv_idx = stages.index("inventory")
    assert copy_idx < inv_idx


# Scenario 11
@pytest.mark.qml
def test_scenario_11_progress_events_keep_running_state(bridge):
    bridge._release_snapshot_running = True
    bridge._release_snapshot_poll_timer.start()

    progress_event = {
        "operation": "snapshot",
        "event": "progress",
        "stage": "copy",
        "current": 5,
        "total": 10,
        "file": "test.jar",
    }
    bridge._release_snapshot_results.put(progress_event)
    bridge._poll_release_snapshot()

    assert bridge.releaseSnapshotRunning is True
    assert bridge._release_snapshot_poll_timer.isActive()
    assert "Copiando JARs — 5/10 · test.jar" in bridge.releaseSnapshotStatus


# Scenario 12
@pytest.mark.qml
def test_scenario_12_catalog_remains_visible_during_snapshot(bridge):
    store = ErpReleaseCatalog(bridge._settings.root).apps_store
    register(store, "app_alpha")
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: len(bridge.applicationsCatalog) == 1)

    bridge._release_snapshot_running = True
    store.register_package({
        "release_id": "app_beta",
        "artifacts": [{
            "application": "VROther",
            "application_key": "vrother",
            "application_version": "1.0",
            "version_detected": True,
            "relative_path": "VROther.jar",
            "class_count": 1,
            "sha256": "b" * 64,
        }],
    })
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: len(bridge.applicationsCatalog) == 2)
    assert any(a["appId"] == "vrapp" for a in bridge.applicationsCatalog)
    assert any(a["appId"] == "vrother" for a in bridge.applicationsCatalog)


# Scenario 13
def test_scenario_13_immutability_managed_release_unaffected_by_source_mutation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    jar_file = source / "VRApp.jar"
    _vr_jar(jar_file, (1, 0, 0, 0))
    orig_bytes = jar_file.read_bytes()

    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=1)
    catalog.snapshot_detected_release(source, release_id="rel-immutable")

    managed_jars = list(catalog.paths.source_for("rel-immutable").rglob("*.jar"))
    assert len(managed_jars) == 1
    managed_jar = managed_jars[0]
    assert managed_jar.is_file()
    assert managed_jar.read_bytes() == orig_bytes

    jar_file.write_bytes(b"corrupted_source_data_post_snapshot")
    assert managed_jar.read_bytes() == orig_bytes


# Scenario 14
@pytest.mark.qml
def test_scenario_14_async_jar_sources_count_keeps_ui_responsive(bridge, tmp_path):
    source = tmp_path / "custom_jars"
    source.mkdir()
    _vr_jar(source / "app1.jar", (1, 0, 0, 0))
    _vr_jar(source / "app2.jar", (2, 0, 0, 0))

    bridge._preferences.setValue(
        bridge._workspace_research_preference("custom_jar_source_dir"),
        str(source),
    )
    bridge._preferences.sync()

    bridge._refresh_code_analysis_jar_sources()
    custom_item = next(
        item for item in bridge.codeAnalysisJarSourceItems
        if item["value"] == codeadmin.ERP_JAR_SOURCE_CUSTOM
    )
    assert custom_item["status"] in ("Verificando…", "2 JAR(s) encontrados")

    wait_until(lambda: any(
        item["value"] == codeadmin.ERP_JAR_SOURCE_CUSTOM and item["jarCount"] == 2
        for item in bridge.codeAnalysisJarSourceItems
    ))


# Scenario 15
@pytest.mark.qml
def test_scenario_15_stale_source_count_results_ignored(bridge):
    bridge._refresh_code_analysis_jar_sources()
    current_gen = bridge._jar_sources_generation

    stale_result = (
        current_gen - 1,
        bridge._settings.root,
        {item["path"]: 999 for item in bridge.codeAnalysisJarSourceItems},
    )
    bridge._on_jar_sources_counted(stale_result)

    for item in bridge.codeAnalysisJarSourceItems:
        assert item["jarCount"] != 999


# Scenario 16
def test_scenario_16_source_jars_pruning_and_nested_discovery(tmp_path):
    root = tmp_path / "source_root"
    root.mkdir()

    for ignored_dir in [".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"]:
        d = root / ignored_dir
        d.mkdir(parents=True)
        _vr_jar(d / "ignored.jar", (1, 0, 0, 0))

    valid_nested = root / "sub" / "package"
    valid_nested.mkdir(parents=True)
    _vr_jar(valid_nested / "nested.jar", (2, 0, 0, 0))

    _vr_jar(root / "root.jar", (3, 0, 0, 0))

    catalog = ErpReleaseCatalog(tmp_path / "ws")
    found = catalog._source_jars(root)
    found_names = [f.name for f in found]
    assert set(found_names) == {"nested.jar", "root.jar"}
    assert "ignored.jar" not in found_names

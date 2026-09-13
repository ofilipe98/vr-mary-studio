"""Exercise the real Qt facade across catalog refresh, import and processing."""
import threading
import time

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.apps_catalog import AppsCatalogStore
from vrsoft_extractor.mary.frontend.bridges import codeadmin
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from test_apps_catalog_audit import register
from test_erp_releases import _vr_jar

pytestmark = pytest.mark.qml


def wait_until(predicate):
    deadline = time.monotonic() + 6
    while not predicate():
        QApplication.processEvents()
        assert time.monotonic() < deadline, "Qt task did not complete"
        time.sleep(0.005)


@pytest.fixture
def bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "workspace", old_root=tmp_path / "old")
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    wait_until(lambda: chat._apps_catalog_thread is None)
    yield chat
    chat.close()
    app.processEvents()


def test_catalog_refresh_preserves_selection_and_clears_removed_app(bridge):
    store = ErpReleaseCatalog(bridge._settings.root).apps_store
    register(store, "one")
    register(store, "two", "2.0")
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: len(bridge.applicationsCatalog) == 1)
    assert bridge.selectedAppId == ""
    bridge.selectApplication("vrapp")
    assert bridge.selectedAppVersion == ""
    bridge.selectAppVersion("1.0")
    variant = bridge.selectedAppVariantId
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    assert bridge.selectedAppVersion == "1.0"
    assert bridge.selectedAppVariantId == variant
    store.unlink_package("one")
    store.unlink_package("two")
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    assert bridge.selectedAppId == ""
    assert not bridge.selectedVersionDetails


def test_import_runs_off_qt_thread_and_reports_error(bridge, tmp_path, monkeypatch):
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    threads = []

    def snapshot(self, source, **kwargs):
        threads.append(threading.get_ident())
        entered.set()
        release.wait(5)
        raise RuntimeError("injected import failure")

    monkeypatch.setattr(ErpReleaseCatalog, "snapshot_detected_release", snapshot)
    try:
        assert bridge.importPackage(str(tmp_path))
        assert entered.wait(2)
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert threads != [threading.get_ident()]
        assert not bridge.importPackage(str(tmp_path))
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert "injected import failure" in bridge.releaseSnapshotStatus


@pytest.mark.parametrize("operation", ["detect", "import", "delete"])
def test_decompiled_tasks_keep_qt_responsive_and_reject_overlap(bridge, tmp_path, monkeypatch, operation):
    entered, release, heartbeat = (threading.Event() for _ in range(3))

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(5)
        raise RuntimeError("decompiled failure")

    if operation == "delete":
        monkeypatch.setattr(ErpReleaseCatalog, "delete_source_jars", blocked)
    else:
        monkeypatch.setattr(codeadmin, f"{operation}_decompiled_source", blocked)
    try:
        result = (bridge.detectDecompiledDirectory(str(tmp_path)) if operation == "detect"
                  else bridge.deleteSourceJars("one") if operation == "delete"
                  else bridge.importDecompiledDirectory(str(tmp_path), "one", "One"))
        assert result["pending"]
        assert entered.wait(2)
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert not bridge.unlinkPackage("one", False)
        assert bridge.importDecompiledDirectory(str(tmp_path))["busy"]
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert "decompiled failure" in bridge.releaseSnapshotStatus


def test_ready_state_is_projected_from_real_coverage(bridge, tmp_path, monkeypatch):
    source = tmp_path / "source"
    _vr_jar(source / "VRApp.jar", (1, 0, 0, 0))
    catalog = ErpReleaseCatalog(bridge._settings.root, expected_jar_count=1)
    catalog.import_release("one", source)
    monkeypatch.setattr(codeadmin.JavaCodeIndex, "coverage", lambda self, release: {
        "covered_jars": ["VRApp.jar"], "indexed_source_jars": ["VRApp.jar"]})
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    bridge.selectApplication("vrapp")
    assert bridge.appVersions[0]["indexState"] == "ready"
    assert bridge.appVersions[0]["decompilationState"] == "ready"
    # The JSON does not become a second writable source of processing truth.
    assert catalog.apps_store.list_versions("vrapp")[0]["indexState"] == "pending"


def test_variant_processing_scopes_to_selected_application(bridge, tmp_path, monkeypatch):
    source = tmp_path / "source"
    _vr_jar(source / "VRApp.jar", (1, 0, 0, 0))
    _vr_jar(source / "VROther.jar", (1, 0, 0, 0))
    catalog = ErpReleaseCatalog(bridge._settings.root, expected_jar_count=2)
    catalog.import_release("one", source)
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge._apps_catalog_thread is None and any(app.get("appId") == "vrapp" for app in bridge.applicationsCatalog))
    bridge.selectApplication("vrapp")
    wait_until(lambda: len(bridge.appVersions) > 0)
    bridge.selectAppVersion(bridge.appVersions[0]["version"])
    calls = []
    monkeypatch.setattr(codeadmin.CodeAdminDomain, "_start_code_processing", lambda self, **kwargs: calls.append(bridge._code_processing_relative_jars) or True)
    assert bridge.startVariantProcessing("vrapp", bridge.selectedAppVersion, bridge.selectedAppVariantId)
    assert calls == [("VRApp.jar",)]


def test_scoped_coverage_stops_without_processing_other_app():
    coverage = {"covered_jars": ["VRApp.jar"], "remaining_jars": ["VROther.jar"],
                "active_plans": [], "blocked_plans": []}
    scoped = codeadmin.CodeAdminDomain._scope_processing_coverage(coverage, ("VRApp.jar",))
    assert scoped["remaining_jar_count"] == 0
    assert scoped["covered_jar_count"] == scoped["expected_jar_count"] == 1
    coverage["active_plans"] = [{"selected_jars": ["VROther.jar"]}]
    with pytest.raises(codeadmin.CodeCoverageError):
        codeadmin.CodeAdminDomain._scope_processing_coverage(coverage, ("VRApp.jar",))


def test_refresh_rejects_old_snapshot_and_keeps_qt_responsive(bridge, monkeypatch):
    store = ErpReleaseCatalog(bridge._settings.root).apps_store
    register(store, "one")
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    original = AppsCatalogStore.list_applications
    calls, displayed = [], []

    def load(self):
        result = original(self)
        calls.append(threading.get_ident())
        if len(calls) == 1:
            entered.set()
            release.wait(5)
        return result

    monkeypatch.setattr(AppsCatalogStore, "list_applications", load)
    bridge.stateChanged.connect(lambda: displayed.extend(a["versionCount"] for a in bridge.applicationsCatalog))
    try:
        bridge.refreshApplicationsCatalog()
        assert entered.wait(2)
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        register(store, "two", "2.0")
        bridge.refreshApplicationsCatalog()
        bridge.refreshApplicationsCatalog()
    finally:
        release.set()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    assert calls and all(t != threading.get_ident() for t in calls)
    assert len(calls) == 2
    assert bridge.applicationsCatalog[0]["versionCount"] == 2
    assert 1 not in displayed


def test_late_comparison_does_not_replace_new_selection(bridge, monkeypatch):
    store = ErpReleaseCatalog(bridge._settings.root).apps_store
    register(store, "one")
    register(store, "two", "2.0")
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    bridge.selectApplication("vrapp")
    bridge.selectAppVersion("1.0")
    entered, release = threading.Event(), threading.Event()

    def compare(self, *args, **kwargs):
        entered.set()
        release.wait(5)
        return {"state": "complete", "baseVersion": "1.0"}

    monkeypatch.setattr(AppsCatalogStore, "compare_versions", compare)
    try:
        assert bridge.compareAppVersions("vrapp", "1.0", "2.0")["state"] == "running"
        assert entered.wait(2)
        bridge.selectAppVersion("2.0")
    finally:
        release.set()
    wait_until(lambda: bridge._app_comparison_thread is None)
    assert bridge.versionComparisonResult == {}


def test_removal_waits_for_catalog_reader_outside_qt(bridge, tmp_path, monkeypatch):
    source = tmp_path / "source"
    _vr_jar(source / "VRApp.jar", (1, 0, 0, 0))
    catalog = ErpReleaseCatalog(bridge._settings.root, expected_jar_count=1)
    catalog.import_release("one", source)
    catalog.import_release("two", source)
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    original = AppsCatalogStore.list_applications

    def load(self):
        result = original(self)
        entered.set()
        release.wait(5)
        return result

    monkeypatch.setattr(AppsCatalogStore, "list_applications", load)
    try:
        bridge.refreshApplicationsCatalog()
        assert entered.wait(2)
        assert bridge.removeCodeAnalysisRelease("one")
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert bridge.releaseSnapshotRunning
        assert catalog.paths.manifest_for("one").exists()
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert not catalog.paths.manifest_for("one").exists(), bridge.releaseSnapshotStatus
    assert catalog.paths.manifest_for("two").exists()

def test_unlink_package_delete_data_runs_async_and_purges(bridge, tmp_path):
    source = tmp_path / "source"
    _vr_jar(source / "VRApp.jar", (1, 0, 0, 0))
    catalog = ErpReleaseCatalog(bridge._settings.root, expected_jar_count=1)
    catalog.import_release("one", source)
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    assert catalog.paths.manifest_for("one").exists()

    assert bridge.unlinkPackage("one", delete_data=True)
    assert bridge.releaseSnapshotRunning
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert not catalog.paths.manifest_for("one").exists()
    assert "sucesso" in bridge.releaseSnapshotStatus.lower()

def test_start_batch_apps_processing_scopes_to_selected_jars(bridge, tmp_path, monkeypatch):
    source = tmp_path / "source"
    _vr_jar(source / "VRApp.jar", (1, 0, 0, 0))
    _vr_jar(source / "VROther.jar", (1, 0, 0, 0))
    _vr_jar(source / "VRThird.jar", (1, 0, 0, 0))
    catalog = ErpReleaseCatalog(bridge._settings.root, expected_jar_count=3)
    catalog.import_release("one", source)
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge._apps_catalog_thread is None)

    calls = []
    monkeypatch.setattr(codeadmin.CodeAdminDomain, "_start_code_processing", lambda self, **kwargs: calls.append(self._code_processing_relative_jars) or True)

    assert not bridge.startBatchAppsProcessing([])
    assert not bridge.startBatchAppsProcessing(["nonexistent_app"])

    assert bridge.startBatchAppsProcessing(["vrapp", "vrother"])
    assert len(calls) == 1
    assert set(calls[0]) == {"VRApp.jar", "VROther.jar"}
    assert bridge._code_processing_total_jars == 2



def test_global_decompile_configuration_persistence(bridge):
    bridge.setCodeProcessingMaxHeapMb(4096)
    bridge.setCodeProcessingTimeoutSeconds(600)
    bridge.setCodeProcessingMaxCpuCores(4)
    bridge.setCodeProcessingDiskMultiplier(8)
    bridge.setCodeProcessingWindow("night")

    assert int(bridge._preferences.value("code_processing/max_heap_mb")) == 4096
    assert int(bridge._preferences.value("code_processing/timeout_seconds")) == 600
    assert int(bridge._preferences.value("code_processing/max_cpu_cores")) == 4
    assert int(bridge._preferences.value("code_processing/disk_multiplier")) == 8
    assert str(bridge._preferences.value("code_processing/window")) == "night"

    from scripts.batch_decompile import load_global_decompile_config
    cfg = load_global_decompile_config(bridge._preferences)
    assert cfg["heap_mb"] == 4096
    assert cfg["timeout_seconds"] == 600
    assert cfg["max_cpu_cores"] == 4
    assert cfg["max_workers"] == codeadmin.CODE_PROCESSING_HARDWARE.parallel_workers_for(4, 4096)

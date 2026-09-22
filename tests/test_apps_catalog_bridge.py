"""Exercise the real Qt facade across catalog refresh, import and processing."""
import os
import threading
import time
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.apps_catalog import AppsCatalogStore
from vrsoft_extractor.mary.frontend.bridges import codeadmin
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
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


def test_refresh_loading_flag_flips_immediately_and_clears(bridge):
    """refreshApplicationsCatalog() must notify loading on the same tick."""
    notifications = []
    bridge.stateChanged.connect(lambda: notifications.append(True))
    assert bridge.applicationsCatalogLoading is False
    bridge.refreshApplicationsCatalog()
    assert bridge.applicationsCatalogLoading is True
    assert len(notifications) >= 1
    wait_until(lambda: bridge._apps_catalog_thread is None)
    QApplication.processEvents()
    assert bridge.applicationsCatalogLoading is False


def test_refresh_keeps_previous_catalog_and_error_hides_empty(bridge):
    """Previous list stays visible in refresh; error never shows empty state."""
    store = ErpReleaseCatalog(bridge._settings.root).apps_store
    register(store, "one")
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: len(bridge.applicationsCatalog) == 1)
    previous = list(bridge.applicationsCatalog)

    bridge.refreshApplicationsCatalog()
    assert bridge.applicationsCatalogLoading is True
    assert bridge.applicationsCatalog == previous
    wait_until(lambda: bridge._apps_catalog_thread is None)
    assert bridge.applicationsCatalog == previous

    bridge._on_applications_loaded(
        {"root": bridge._settings.root, "error": "boom"}
    )
    assert bridge.applicationsCatalogError == "boom"
    assert bridge.applicationsCatalog == previous
    assert bridge.applicationsCatalogLoading is False
    # Mirror of the ApplicationsSettingsPage empty-hint visible binding.
    empty_visible = (
        (bridge.applicationsCatalogLoading or bridge.applicationsCatalogLoaded)
        and len(bridge.applicationsCatalog) == 0
        and bridge.applicationsCatalogError == ""
    )
    assert empty_visible is False


def test_ready_phase_reports_real_version_totals(bridge):
    """versionsCount must count versions, not applications or packages."""
    store = ErpReleaseCatalog(bridge._settings.root).apps_store
    register(store, "one")
    register(store, "two", "2.0")
    phases = []
    bridge.applicationsCatalogPhase.connect(
        lambda phase, apps, versions: phases.append((phase, apps, versions))
    )
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    QApplication.processEvents()
    ready = [item for item in phases if item[0] == "ready"]
    assert ready, phases
    _phase, apps_count, versions_count = ready[-1]
    assert apps_count == 1
    assert versions_count == 2
    loading = [item for item in phases if item[0] == "loading_versions"]
    assert loading and loading[-1][2] == 2


def test_studio_save_settings_root_change_stays_on_old_root(tmp_path, monkeypatch):
    """Strategy A: new root persists to .env; live bridges keep the old root."""
    for key in (
        "VR_ROOT",
        "MOVIDESK_EMAIL",
        "MOVIDESK_PASSWORD",
        "ENDOO_EMAIL",
        "ENDOO_PASSWORD",
        "VR_SYNC_INTERVAL_MINUTES",
        "VR_DEFAULT_EFFORT",
    ):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)

    old_root = tmp_path / "workspace"
    old_root.mkdir(parents=True, exist_ok=True)
    settings = MarySettings(app_dir=tmp_path, root=old_root, old_root=tmp_path / "old")
    monkeypatch.setenv("VR_ROOT", str(old_root))
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    studio = StudioBridge(settings, db, prefs)
    try:
        toasts = []
        studio.toastRequested.connect(lambda msg, kind: toasts.append((msg, kind)))

        new_root = tmp_path / "novo_workspace"
        studio.saveSettings(
            str(new_root), "new@vr.com.br", "", "endoo@vr.com.br", "", "240"
        )

        # Live backend untouched: still the old root everywhere.
        assert studio._settings.root == old_root
        assert os.environ["VR_ROOT"] == str(old_root)
        # Immediate-effect settings aligned in the running process.
        assert os.environ["MOVIDESK_EMAIL"] == "new@vr.com.br"
        assert os.environ["ENDOO_EMAIL"] == "endoo@vr.com.br"
        assert os.environ["VR_SYNC_INTERVAL_MINUTES"] == "240"
        # New root persisted for the next launch.
        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert str(new_root) in env_text
        assert any(kind == "warning" for _msg, kind in toasts)

        # Same-root save swaps settings and applies immediately.
        toasts.clear()
        studio.saveSettings(
            str(old_root), "second@vr.com.br", "", "endoo2@vr.com.br", "", "60"
        )
        assert studio._settings.root == old_root
        assert studio._settings.sync_interval_minutes == 60
        assert os.environ["MOVIDESK_EMAIL"] == "second@vr.com.br"
        assert os.environ["VR_SYNC_INTERVAL_MINUTES"] == "60"
        assert any(kind == "success" for _msg, kind in toasts)
    finally:
        studio.close()


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


def test_delete_jars_task_keeps_qt_responsive_and_rejects_overlap(bridge, monkeypatch):
    entered, release, heartbeat = (threading.Event() for _ in range(3))

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(5)
        raise RuntimeError("decompiled failure")

    monkeypatch.setattr(ErpReleaseCatalog, "delete_source_jars", blocked)
    try:
        result = bridge.deleteSourceJars("one")
        assert result["pending"]
        assert entered.wait(2)
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert not bridge.unlinkPackage("one", False)
        assert bridge.deleteSourceJars("one")["error"] == "Aguarde a operação em andamento."
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert "decompiled failure" in bridge.releaseSnapshotStatus


def _select_exportable_decompiled_code(bridge):
    bridge._selected_app_id = "vrmaster"
    bridge._selected_app_version = "4.1.0"
    bridge._selected_app_variant_id = "sha-master"
    bridge._selected_app_origin_id = "release-a"
    bridge._selected_version_details = {
        "indexed_classes": 2,
        "origin_packages": [{"package_id": "release-a", "index_state": "ready"}],
    }


def test_export_slot_cancel_is_silent_and_does_not_start(bridge, monkeypatch):
    _select_exportable_decompiled_code(bridge)
    before = bridge.releaseSnapshotStatus
    monkeypatch.setattr(codeadmin.QFileDialog, "getExistingDirectory", lambda *args: "")

    result = bridge.exportDecompiledCode("")

    assert result == {"success": False, "canceled": True}
    assert bridge.releaseSnapshotRunning is False
    assert bridge.decompiledExportRunning is False
    assert bridge.releaseSnapshotStatus == before
    assert bridge.metaObject().indexOfMethod("exportDecompiledCode(QString)") >= 0


def test_export_runs_off_qt_thread_rejects_overlap_and_clears_busy(bridge, tmp_path, monkeypatch):
    _select_exportable_decompiled_code(bridge)
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    worker_threads = []

    def blocked(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        release.wait(5)
        return {"success": True, "destination": str(tmp_path), "file_count": 1248, "total_bytes": 10}

    monkeypatch.setattr(codeadmin, "export_decompiled_source", blocked)
    try:
        assert bridge.exportDecompiledCode(str(tmp_path))["pending"]
        assert entered.wait(2)
        assert bridge.releaseSnapshotRunning is True
        assert bridge.decompiledExportRunning is True
        assert bridge.exportDecompiledCode(str(tmp_path))["busy"]
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert worker_threads != [threading.get_ident()]
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert bridge.decompiledExportRunning is False
    assert "1.248 arquivos exportados" in bridge.releaseSnapshotStatus


def test_export_failure_clears_running_state(bridge, tmp_path, monkeypatch):
    _select_exportable_decompiled_code(bridge)
    bridge._ultra_application_contexts = [{
        "app_id": "vrmaster", "version": "4.1.0",
        "variant_id": "sha-master", "package_id": "release-a",
    }]
    bridge._apps_catalog_data = {"data": {"applications": {"vrmaster": {"name": "VRMaster", "versions": {
        "4.1.0": {"variants": {"sha-master": {"origin_packages": [{
            "package_id": "release-a", "index_state": "ready",
        }]}}}
    }}}}}
    before_error = bridge.applicationsCatalogError
    assert bridge.ultraApplicationContextsReady is True
    monkeypatch.setattr(
        codeadmin, "export_decompiled_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("fonte ausente")),
    )

    assert bridge.exportDecompiledCode(str(tmp_path))["pending"]
    wait_until(lambda: not bridge.releaseSnapshotRunning)

    assert bridge.decompiledExportRunning is False
    assert bridge.releaseSnapshotStatus == "Não foi possível exportar o código descompilado: fonte ausente"
    assert bridge.applicationsCatalogError == before_error
    assert bridge.ultraApplicationContextsReady is True


def test_export_from_previous_workspace_only_clears_running_state(bridge, tmp_path, monkeypatch):
    _select_exportable_decompiled_code(bridge)
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(5)
        return {"success": True, "destination": str(tmp_path), "file_count": 1, "total_bytes": 1}

    monkeypatch.setattr(codeadmin, "export_decompiled_source", blocked)
    assert bridge.exportDecompiledCode(str(tmp_path))["pending"]
    assert entered.wait(2)
    object.__setattr__(bridge._settings, "root", tmp_path / "workspace-b")
    bridge._release_snapshot_status = "Estado do workspace B"
    release.set()

    wait_until(lambda: not bridge.releaseSnapshotRunning)

    assert bridge.decompiledExportRunning is False
    assert bridge.releaseSnapshotStatus == "Estado do workspace B"


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


def test_package_portable_slots_are_exposed(bridge):
    for signature in (
        "detectDecompiledPackageArchive(QString)",
        "importDecompiledPackageArchive(QString,QString,QString)",
        "exportDecompiledPackage(QString)",
        "exportDecompiledPackage(QString,QString)",
    ):
        assert bridge.metaObject().indexOfMethod(signature) >= 0, signature


def test_package_detect_cancel_does_not_change_state(bridge, monkeypatch):
    before_status = bridge.releaseSnapshotStatus
    before_error = bridge.applicationsCatalogError
    monkeypatch.setattr(codeadmin.QFileDialog, "getOpenFileName", lambda *args: ("", ""))

    result = bridge.detectDecompiledPackageArchive("")

    assert result == {"is_valid": False, "portable_package": True, "canceled": True}
    assert bridge.releaseSnapshotRunning is False
    assert bridge.decompiledExportRunning is False
    assert bridge.releaseSnapshotStatus == before_status
    assert bridge.applicationsCatalogError == before_error


def test_package_export_save_dialog_cancel_is_silent(bridge, monkeypatch):
    before_status = bridge.releaseSnapshotStatus
    before_error = bridge.applicationsCatalogError
    monkeypatch.setattr(codeadmin.QFileDialog, "getSaveFileName", lambda *args: ("", ""))

    result = bridge.exportDecompiledPackage("release-a")

    assert result == {"success": False, "canceled": True}
    assert bridge.releaseSnapshotRunning is False
    assert bridge.decompiledExportRunning is False
    assert bridge.releaseSnapshotStatus == before_status
    assert bridge.applicationsCatalogError == before_error


def test_package_export_runs_off_qt_thread_rejects_overlap_and_clears_busy(
    bridge, tmp_path, monkeypatch
):
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    worker_threads = []

    def blocked(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        release.wait(5)
        return {
            "success": True,
            "destination": str(tmp_path / "Pacote.zip"),
            "file_count": 7,
            "total_bytes": 10,
            "artifact_count": 2,
        }

    monkeypatch.setattr(codeadmin, "export_decompiled_package", blocked)
    try:
        assert bridge.exportDecompiledPackage("release-a", str(tmp_path / "Pacote.zip"))["pending"]
        assert entered.wait(2)
        assert bridge.releaseSnapshotRunning is True
        assert bridge.decompiledExportRunning is True
        assert bridge.exportDecompiledPackage("release-a", str(tmp_path / "Pacote.zip"))["busy"]
        assert bridge.exportDecompiledCode(str(tmp_path))["busy"]
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert worker_threads != [threading.get_ident()]
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert bridge.decompiledExportRunning is False
    assert "7 arquivos exportados" in bridge.releaseSnapshotStatus


def test_package_export_reports_progress_through_poll_timer(bridge, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, progress=None, **kwargs):
        entered.set()
        progress({"current": 0, "total": 2000})
        progress({"current": 250, "total": 2000})
        release.wait(5)
        progress({"current": 2000, "total": 2000})
        return {
            "success": True,
            "destination": str(tmp_path / "Pacote.zip"),
            "file_count": 2000,
            "total_bytes": 10,
            "artifact_count": 1,
        }

    monkeypatch.setattr(codeadmin, "export_decompiled_package", blocked)
    try:
        assert bridge.exportDecompiledPackage(
            "release-a", str(tmp_path / "Pacote.zip")
        )["pending"]
        assert entered.wait(2)
        wait_until(lambda: bridge.decompiledExportProgress == 12.5)
        assert bridge.decompiledExportRunning is True
        assert bridge.decompiledExportProcessed == 250
        assert bridge.decompiledExportTotal == 2000
        assert bridge.releaseSnapshotStatus.startswith("Exportando código descompilado")
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert bridge.decompiledExportRunning is False
    assert "2.000 arquivos exportados" in bridge.releaseSnapshotStatus


def test_package_import_reports_progress_through_poll_timer(bridge, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, progress=None, **kwargs):
        entered.set()
        progress({"current": 0, "total": 40})
        progress({"current": 10, "total": 40})
        release.wait(5)
        progress({"current": 40, "total": 40})
        return {
            "success": True,
            "release_id": "release-a",
            "package_name": "Pacote A",
            "imported_applications": 1,
            "total_indexed_sources": 40,
            "package": {},
        }

    monkeypatch.setattr(codeadmin, "import_decompiled_package_archive", blocked)
    archive = tmp_path / "Pacote-decompiled.zip"
    archive.write_bytes(b"zip")
    try:
        assert bridge.importDecompiledPackageArchive(
            str(archive), "release-a", "Pacote A"
        )["pending"]
        assert entered.wait(2)
        wait_until(lambda: bridge.decompiledImportProgress == 25.0)
        assert bridge.decompiledImportRunning is True
        assert bridge.decompiledImportProcessed == 10
        assert bridge.decompiledImportTotal == 40
        assert bridge.releaseSnapshotStatus.startswith("Importando código descompilado")
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert bridge.decompiledImportRunning is False
    assert "Importação concluída: 40 fontes indexados" in bridge.releaseSnapshotStatus


def test_package_import_runs_off_qt_thread_and_rejects_overlap(bridge, tmp_path, monkeypatch):
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    worker_threads = []

    def blocked(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        release.wait(5)
        return {
            "success": True,
            "release_id": "release-a",
            "package_name": "Pacote A",
            "imported_applications": 2,
            "total_indexed_sources": 3,
            "package": {},
        }

    monkeypatch.setattr(codeadmin, "import_decompiled_package_archive", blocked)
    archive = tmp_path / "Pacote-decompiled.zip"
    archive.write_bytes(b"zip")
    try:
        assert bridge.importDecompiledPackageArchive(
            str(archive), "release-a", "Pacote A"
        )["pending"]
        assert entered.wait(2)
        assert bridge.releaseSnapshotRunning is True
        assert bridge.importDecompiledPackageArchive(
            str(archive), "release-a", "Pacote A"
        )["busy"]
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert worker_threads != [threading.get_ident()]
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert "3 fontes indexados" in bridge.releaseSnapshotStatus


def test_package_export_failure_preserves_catalog_error(bridge, tmp_path, monkeypatch):
    bridge._apps_catalog_error = "erro anterior do catálogo"
    monkeypatch.setattr(
        codeadmin,
        "export_decompiled_package",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("pacote ausente")),
    )

    assert bridge.exportDecompiledPackage("release-a", str(tmp_path / "Pacote.zip"))["pending"]
    wait_until(lambda: not bridge.releaseSnapshotRunning)

    assert bridge.decompiledExportRunning is False
    assert bridge.applicationsCatalogError == "erro anterior do catálogo"
    assert bridge.releaseSnapshotStatus == (
        "Não foi possível exportar o código descompilado: pacote ausente"
    )


def test_chat_turn_without_application_selection_sends_no_explicit_scope(bridge):
    """Sem seleção em Aplicativos, o turno usa a release disponível (None)."""
    without_scope = bridge._database.create_conversation(
        "Sem seleção", "codex", "test", bridge._settings.root
    )
    with_scope = bridge._database.create_conversation(
        "Com seleção", "codex", "test", bridge._settings.root
    )
    bridge.refresh()
    bridge.selectConversationId(without_scope)
    with patch.object(bridge._orchestrator, "send") as send:
        bridge.sendMessage("Pergunta sem aplicativo")
    assert send.call_args.kwargs["application_contexts"] is None
    assert send.call_args.kwargs["code_analysis_enabled"] is False

    bridge._ultra_application_contexts = [{
        "app_id": "vrmaster", "version": "4.1.0",
        "variant_id": "sha-master", "package_id": "release-a",
    }]
    bridge.selectConversationId(with_scope)
    with patch.object(bridge._orchestrator, "send") as send:
        bridge.sendMessage("Pergunta com aplicativo")
    assert send.call_args.kwargs["application_contexts"][0]["app_id"] == "vrmaster"

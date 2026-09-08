"""Exercise the coverage worker with a live Qt event loop and blocked I/O."""

import json
import sqlite3
import threading
import time
from dataclasses import replace

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.bridges import codeadmin
from vrsoft_extractor.mary.frontend.chat import ChatBridge

pytestmark = pytest.mark.qml


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "Qt coverage result did not arrive"
        QApplication.processEvents()
        time.sleep(0.005)


@pytest.fixture
def coverage_bridge(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    statuses = []
    monkeypatch.setattr(codeadmin.ErpReleaseCatalog, "list_statuses", lambda self: list(statuses))
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "workspace", old_root=tmp_path / "old")
    database = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    preferences = QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat)
    bridge = ChatBridge(settings, database, preferences)
    # This suite isolates release-list coverage; processing status has its own worker tests.
    monkeypatch.setattr(bridge, "refreshCodeProcessingStatus", lambda: None)
    statuses.append({
        "release_id": "r1", "release_manifest_sha256": "hash1",
        "state": "completed", "freshness": "fresh", "jar_count": 1,
    })
    try:
        yield bridge, statuses
    finally:
        bridge.close()
        app.processEvents()


def test_refresh_keeps_qt_responsive_and_coalesces_queries(coverage_bridge, monkeypatch):
    bridge, _ = coverage_bridge
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    calls, writes = [], []
    main_thread = threading.get_ident()
    save = codeadmin.CodeAdminDomain._save_cached_release_coverage

    def coverage(self, release_id):
        calls.append(threading.get_ident())
        entered.set()
        release.wait(5)
        return {"release_manifest_sha256": "hash1", "covered_jar_count": 1}

    def record_save(self):
        writes.append(threading.get_ident())
        save(self)

    monkeypatch.setattr(codeadmin.JavaCodeIndex, "coverage", coverage)
    monkeypatch.setattr(codeadmin.CodeAdminDomain, "_save_cached_release_coverage", record_save)
    try:
        bridge.refreshCodeAnalysisReleases()
        assert entered.wait(2)
        for _ in range(3):
            bridge.refreshCodeAnalysisReleases()
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert calls and calls != [main_thread]
        assert len(calls) == 1
        assert not bridge.codeAnalysisReleaseItems[0]["coverageLoaded"]
        assert writes == []
    finally:
        release.set()
    wait_until(lambda: bridge.codeAnalysisReleaseItems[0]["coverageLoaded"])
    assert "1/1 JARs indexados" in bridge.codeAnalysisReleaseItems[0]["label"]
    assert writes == [main_thread]
    bridge.refreshCodeAnalysisReleases()
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["processing", "snapshot", "manifest", "workspace"])
def test_old_coverage_cannot_replace_changed_inputs(coverage_bridge, monkeypatch, change):
    bridge, statuses = coverage_bridge
    entered, release = threading.Event(), threading.Event()
    calls, displayed = [], []

    def coverage(self, release_id):
        manifest = statuses[0]["release_manifest_sha256"]
        count = len(calls)
        calls.append((self.root, manifest))
        if count == 0:
            entered.set()
            release.wait(5)
        return {"release_manifest_sha256": manifest, "covered_jar_count": count}

    def record_display():
        displayed.extend(item["coveredJarCount"] for item in bridge.codeAnalysisReleaseItems
                         if item["coverageLoaded"])

    monkeypatch.setattr(codeadmin.JavaCodeIndex, "coverage", coverage)
    bridge.stateChanged.connect(record_display)
    try:
        bridge.refreshCodeAnalysisReleases()
        assert entered.wait(2)
        if change == "processing":
            bridge._code_processing_results.put({"kind": "completed"})
            bridge._poll_code_processing()
        elif change == "snapshot":
            bridge._release_snapshot_results.put({"ok": True, "release_id": "r1"})
            bridge._poll_release_snapshot()
        elif change == "manifest":
            # The manifest can change even without a UI refresh while a query runs.
            statuses[0]["release_manifest_sha256"] = "hash2"
        else:
            bridge._settings = replace(bridge._settings, root=bridge._settings.root / "other")
            bridge.refreshCodeAnalysisReleases()
    finally:
        release.set()
    wait_until(lambda: bridge.codeAnalysisReleaseItems[0]["coverageLoaded"])
    assert len(calls) == 2
    assert bridge.codeAnalysisReleaseItems[0]["coveredJarCount"] == 1
    assert 0 not in displayed


def test_failed_query_waits_for_explicit_retry(coverage_bridge, monkeypatch):
    bridge, _ = coverage_bridge
    calls = []

    def coverage(self, release_id):
        calls.append(release_id)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"release_manifest_sha256": "hash1", "covered_jar_count": 1}

    monkeypatch.setattr(codeadmin.JavaCodeIndex, "coverage", coverage)
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge._release_coverage_thread is None)
    assert calls == ["r1"]
    assert not bridge.codeAnalysisReleaseItems[0]["coverageLoaded"]
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge.codeAnalysisReleaseItems[0]["coverageLoaded"])
    assert calls == ["r1", "r1"]


def test_queued_result_after_close_does_not_write_preferences(coverage_bridge, monkeypatch):
    bridge, _ = coverage_bridge
    monkeypatch.setattr(codeadmin.JavaCodeIndex, "coverage", lambda self, release_id: {
        "release_manifest_sha256": "hash1", "covered_jar_count": 1,
    })
    bridge.refreshCodeAnalysisReleases()
    bridge._release_coverage_thread.join(timeout=2)
    assert not bridge._release_coverage_thread.is_alive()
    bridge.close()
    QApplication.processEvents()
    assert bridge._release_coverage_cache == {}
    assert not bridge._preferences.contains(bridge._workspace_research_preference("release_coverage_cache"))


def test_close_stops_remaining_coverage_queries(coverage_bridge, monkeypatch):
    bridge, statuses = coverage_bridge
    statuses.append(dict(statuses[0], release_id="r2"))
    entered, release = threading.Event(), threading.Event()
    calls = []

    def coverage(self, release_id):
        calls.append(release_id)
        entered.set()
        release.wait(5)
        return {"release_manifest_sha256": "hash1", "covered_jar_count": 1}

    monkeypatch.setattr(codeadmin.JavaCodeIndex, "coverage", coverage)
    bridge.refreshCodeAnalysisReleases()
    try:
        assert entered.wait(2)
        unblock = threading.Timer(0.01, release.set)
        unblock.start()
        bridge.close()
        unblock.join()
        assert not bridge._release_coverage_thread.is_alive()
        QApplication.processEvents()
        assert calls == ["r1"]
        assert bridge._release_coverage_cache == {}
    finally:
        release.set()


def test_persisted_coverage_is_scoped_to_workspace_and_validated(coverage_bridge, monkeypatch):
    bridge, _ = coverage_bridge
    calls = []

    def coverage(self, release_id):
        calls.append(self.root)
        return {"release_manifest_sha256": "hash1", "covered_jar_count": len(calls)}

    monkeypatch.setattr(codeadmin.JavaCodeIndex, "coverage", coverage)
    original_settings = bridge._settings
    first_key = bridge._workspace_research_preference("release_coverage_cache")
    bridge._preferences.setValue(first_key, json.dumps({
        "r1:hash1": {"covered_jar_count": "invalid"}, "bad": None,
    }))
    assert bridge._CodeAdmin_domain._load_cached_release_coverage() == {}
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge.codeAnalysisReleaseItems[0]["coverageLoaded"])
    bridge._settings = replace(original_settings, root=original_settings.root / "other")
    bridge.refreshCodeAnalysisReleases()
    assert not bridge.codeAnalysisReleaseItems[0]["coverageLoaded"]
    wait_until(lambda: bridge.codeAnalysisReleaseItems[0]["coverageLoaded"])
    assert bridge.codeAnalysisReleaseItems[0]["coveredJarCount"] == 2
    bridge._settings = original_settings
    bridge.refreshCodeAnalysisReleases()
    assert bridge.codeAnalysisReleaseItems[0]["coveredJarCount"] == 1
    assert len(calls) == 2

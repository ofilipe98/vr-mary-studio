"""Tests for application import, preview, snapshot, pruning, and bridge concurrency."""
from __future__ import annotations

import os
import threading
import time

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.application_import import (
    preview_application_import,
    validate_preview_fingerprint,
)
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
from test_erp_releases import _vr_jar


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

    with pytest.raises(ErpReleaseError, match="mudaram após a prévia"):
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

    with pytest.raises(ErpReleaseError, match="mudaram após a prévia"):
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


def _wait_preview_ready(bridge, timeout=10.0):
    wait_until(
        lambda: bridge.applicationImportPreview.get("state") in ("ready", "error"),
        timeout=timeout,
    )


def _wait_snapshot_idle(bridge, timeout=15.0):
    wait_until(lambda: not bridge.releaseSnapshotRunning, timeout=timeout)


def _catalog_package_ids(bridge):
    try:
        return {
            str(item.get("package_id") or item.get("packageId") or "")
            for item in ErpReleaseCatalog(bridge._settings.root).apps_store.load_catalog().get(
                "packages", {}
            )
        } | {
            str(item.get("packageId") or "")
            for item in bridge._packages_catalog or []
        }
    except Exception:
        return set()


# Scenario 17 — novo JAR após preview invalida confirmação (bridge real)
@pytest.mark.qml
def test_scenario_17_added_jar_after_preview_invalidates_confirm(bridge, tmp_path):
    source = tmp_path / "source_added"
    source.mkdir()
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))

    assert bridge.previewApplicationImport(str(source), False, "") is True
    _wait_preview_ready(bridge)
    assert bridge.applicationImportPreview.get("state") == "ready"

    _vr_jar(source / "vrpdv.jar", (2, 0, 0, 0))

    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)
    assert "mudaram após a prévia" in bridge.releaseSnapshotStatus
    # Snapshot não publicado: nenhum pacote novo no catálogo final.
    wait_until(lambda: bridge._apps_catalog_thread is None)
    QApplication.processEvents()
    catalog = ErpReleaseCatalog(bridge._settings.root)
    assert catalog.list_packages() == []


# Scenario 18 — JAR removido após preview invalida confirmação (bridge real)
@pytest.mark.qml
def test_scenario_18_removed_jar_after_preview_invalidates_confirm(bridge, tmp_path):
    source = tmp_path / "source_removed"
    source.mkdir()
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))
    _vr_jar(source / "vrpdv.jar", (2, 0, 0, 0))

    assert bridge.previewApplicationImport(str(source), False, "") is True
    _wait_preview_ready(bridge)
    assert bridge.applicationImportPreview.get("state") == "ready"

    (source / "vrpdv.jar").unlink()

    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)
    assert "mudaram após a prévia" in bridge.releaseSnapshotStatus
    wait_until(lambda: bridge._apps_catalog_thread is None)
    assert ErpReleaseCatalog(bridge._settings.root).list_packages() == []


# Scenario 19 — rename/path change invalida confirmação (bridge real + helper)
def test_scenario_19_rename_invalidates_fingerprint(tmp_path):
    source = tmp_path / "source_rename"
    source.mkdir()
    jar = source / "vrmaster.jar"
    _vr_jar(jar, (1, 0, 0, 0))

    preview = preview_application_import(tmp_path / "ws", source, single=False)

    renamed = source / "vrmaster-renamed.jar"
    jar.rename(renamed)
    # Mesmo conteúdo/tamanho; mtime preservado pelo rename na maioria dos FS.
    # Mesmo que o mtime mude, o relative_path já deve invalidar.
    with pytest.raises(ErpReleaseError, match="mudaram após a prévia"):
        validate_preview_fingerprint(source, preview["fingerprint"], single=False)


@pytest.mark.qml
def test_scenario_19b_subdir_move_invalidates_confirm_via_bridge(bridge, tmp_path):
    source = tmp_path / "source_moved"
    (source / "master").mkdir(parents=True)
    _vr_jar(source / "master" / "vrmaster.jar", (1, 0, 0, 0))

    assert bridge.previewApplicationImport(str(source), False, "") is True
    _wait_preview_ready(bridge)
    assert bridge.applicationImportPreview.get("state") == "ready"

    (source / "outro").mkdir(parents=True)
    (source / "master" / "vrmaster.jar").rename(source / "outro" / "vrmaster.jar")
    try:
        (source / "master").rmdir()
    except OSError:
        pass

    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)
    assert "mudaram após a prévia" in bridge.releaseSnapshotStatus
    assert ErpReleaseCatalog(bridge._settings.root).list_packages() == []


# Scenario 20 — nenhum segundo preview na confirmação (spy explícito)
@pytest.mark.qml
def test_scenario_20_confirm_does_not_call_preview_again(bridge, tmp_path, monkeypatch):
    import vrsoft_extractor.mary.application_import as app_import_mod

    source = tmp_path / "source_nosecond"
    source.mkdir()
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))

    assert bridge.previewApplicationImport(str(source), False, "") is True
    _wait_preview_ready(bridge)
    assert bridge.applicationImportPreview.get("state") == "ready"

    original = app_import_mod.preview_application_import
    calls: list[tuple] = []

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(app_import_mod, "preview_application_import", spy)

    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)

    assert calls == []
    # Confirmação legítima deve ter concluído o snapshot parcial.
    assert "Não foi possível" not in bridge.releaseSnapshotStatus


# Scenario 21 — bytes alterados com mesmo size+mtime falham no SHA final (bridge)
@pytest.mark.qml
def test_scenario_21_sha_catches_same_size_mtime_tamper_via_bridge(bridge, tmp_path):
    source = tmp_path / "source_sha"
    source.mkdir()
    jar_file = source / "vrmaster.jar"
    _vr_jar(jar_file, (1, 0, 0, 0))

    assert bridge.previewApplicationImport(str(source), False, "") is True
    _wait_preview_ready(bridge)
    assert bridge.applicationImportPreview.get("state") == "ready"

    st = jar_file.stat()
    orig_size = st.st_size
    orig_mtime_ns = st.st_mtime_ns
    data = bytearray(jar_file.read_bytes())
    data[10] = (data[10] + 1) % 256
    jar_file.write_bytes(bytes(data))
    assert jar_file.stat().st_size == orig_size
    os.utime(jar_file, ns=(orig_mtime_ns, orig_mtime_ns))

    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)
    assert "SHA-256 divergente" in bridge.releaseSnapshotStatus
    catalog = ErpReleaseCatalog(bridge._settings.root)
    assert catalog.list_packages() == []
    staging = list(catalog.paths.source_releases.glob(".*snapshot-*"))
    assert staging == []


def test_scenario_21b_sha_same_size_mtime_staging_cleaned_and_catalog_empty(tmp_path):
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

    # Metadata validation pode passar; SHA durante copy deve falhar.
    validate_preview_fingerprint(source, preview["fingerprint"], single=False)

    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=1)
    with pytest.raises(ErpReleaseError, match="SHA-256 divergente no snapshot"):
        catalog.snapshot_detected_release(
            source,
            release_id="test-rel-sha",
            known_hashes=known_hashes,
        )
    assert list(catalog.paths.source_releases.glob(".*snapshot-*")) == []
    assert not catalog.paths.manifest_for("test-rel-sha").is_file()
    assert catalog.list_packages() == []


# Scenario 22 — progresso monotônico por fase
def test_scenario_22_progress_monotonic_per_stage(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _vr_jar(source / "app1.jar", (1, 0, 0, 0))
    _vr_jar(source / "app2.jar", (2, 0, 0, 0))
    _vr_jar(source / "app3.jar", (3, 0, 0, 0))
    total_jars = 3

    preview_events: list[dict] = []
    preview_application_import(
        tmp_path / "ws", source, single=False, progress_callback=preview_events.append
    )
    snapshot_events: list[dict] = []
    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=3)
    catalog.snapshot_detected_release(
        source, release_id="rel-mono", progress_callback=snapshot_events.append
    )
    assert preview_events, "esperava eventos de progresso na preview"
    assert snapshot_events, "esperava eventos de progresso no snapshot"

    def _group(events: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for ev in events:
            if ev.get("event") != "progress":
                continue
            assert "stage" in ev and "current" in ev and "total" in ev and "file" in ev
            grouped.setdefault(str(ev["stage"]), []).append(ev)
        return grouped

    def _assert_monotonic(grouped: dict[str, list[dict]], stages: tuple[str, ...]) -> None:
        for expected in stages:
            assert expected in grouped, f"fase ausente: {expected}"
            staged = grouped[expected]
            assert len(staged) == total_jars, f"fase {expected}: {len(staged)} != {total_jars}"
            seen: list[int] = []
            for ev in staged:
                current = int(ev["current"])
                total = int(ev["total"])
                assert total == total_jars
                assert 1 <= current <= total
                assert str(ev["file"]).endswith(".jar")
                seen.append(current)
            assert seen == sorted(seen), f"fase {expected} não monotônica: {seen}"
            assert seen == list(range(1, total_jars + 1))

    _assert_monotonic(_group(preview_events), ("detect", "hash"))
    _assert_monotonic(_group(snapshot_events), ("detect", "copy", "inventory"))


# Scenario 23 — polling: terminal não é perdido e progress atrasado não sobrescreve
@pytest.mark.qml
def test_scenario_23_poll_progress_then_terminal(bridge):
    bridge._release_snapshot_running = True
    bridge._release_snapshot_poll_timer.start()
    for current in (1, 2, 3):
        bridge._release_snapshot_results.put({
            "operation": "snapshot",
            "event": "progress",
            "stage": "copy",
            "current": current,
            "total": 3,
            "file": f"app{current}.jar",
        })
        bridge._poll_release_snapshot()
        assert bridge.releaseSnapshotRunning is True
        assert bridge._release_snapshot_poll_timer.isActive()
    assert "Copiando JARs — 3/3" in bridge.releaseSnapshotStatus

    bridge._release_snapshot_results.put({
        "ok": False,
        "release_id": "rel-x",
        "error": "falha terminal de teste",
    })
    bridge._poll_release_snapshot()
    assert bridge.releaseSnapshotRunning is False
    assert not bridge._release_snapshot_poll_timer.isActive()
    assert "falha terminal de teste" in bridge.releaseSnapshotStatus


@pytest.mark.qml
def test_scenario_23b_late_progress_does_not_overwrite_terminal(bridge):
    bridge._release_snapshot_running = True
    bridge._release_snapshot_poll_timer.start()
    bridge._release_snapshot_results.put({
        "operation": "snapshot",
        "event": "progress",
        "stage": "copy",
        "current": 1,
        "total": 2,
        "file": "app1.jar",
    })
    bridge._poll_release_snapshot()
    bridge._release_snapshot_results.put({
        "ok": True,
        "release_id": "rel-final",
        "jar_count": 2,
        "package_jar_count": 2,
        "base_release_id": "",
        "analysis_scope": "partial_release",
        "expected_jar_count": 46,
        "updated_applications": [],
    })
    bridge._poll_release_snapshot()
    assert bridge.releaseSnapshotRunning is False
    final_status = bridge.releaseSnapshotStatus
    assert "rel-final" in final_status

    # Progress atrasado após terminal deve ser ignorado.
    bridge._release_snapshot_results.put({
        "operation": "snapshot",
        "event": "progress",
        "stage": "copy",
        "current": 2,
        "total": 2,
        "file": "late.jar",
    })
    bridge._poll_release_snapshot()
    assert bridge.releaseSnapshotRunning is False
    assert not bridge._release_snapshot_poll_timer.isActive()
    assert bridge.releaseSnapshotStatus == final_status


# Scenario 24 — race real de stale worker na contagem de JARs
@pytest.mark.qml
def test_scenario_24_real_stale_count_race_ignored(bridge, tmp_path, monkeypatch):
    import vrsoft_extractor.mary.erp_releases as erp_mod

    dir_a = tmp_path / "jars_a"
    dir_a.mkdir()
    _vr_jar(dir_a / "only_a.jar", (1, 0, 0, 0))
    dir_b = tmp_path / "jars_b"
    dir_b.mkdir()
    _vr_jar(dir_b / "b1.jar", (1, 0, 0, 0))
    _vr_jar(dir_b / "b2.jar", (2, 0, 0, 0))

    bridge._preferences.setValue(
        bridge._workspace_research_preference("custom_jar_source_dir"), str(dir_a)
    )
    bridge._preferences.sync()

    original_count = erp_mod.ErpReleaseCatalog.count_source_jars
    block = threading.Event()
    release = threading.Event()
    call_index = {"n": 0}

    def blocking_count(self, source_dir):
        call_index["n"] += 1
        if call_index["n"] == 1:
            block.set()
            assert release.wait(timeout=10), "worker A não foi liberado"
        return original_count(self, source_dir)

    monkeypatch.setattr(erp_mod.ErpReleaseCatalog, "count_source_jars", blocking_count)

    bridge._refresh_code_analysis_jar_sources()
    gen_a = bridge._jar_sources_generation
    assert block.wait(timeout=10), "worker A não iniciou"

    # Config muda para B enquanto A está bloqueado; monkeypatch removido p/ B ser rápido.
    monkeypatch.undo()
    bridge._preferences.setValue(
        bridge._workspace_research_preference("custom_jar_source_dir"), str(dir_b)
    )
    bridge._preferences.sync()
    bridge._refresh_code_analysis_jar_sources()
    gen_b = bridge._jar_sources_generation
    assert gen_b == gen_a + 1

    wait_until(lambda: any(
        item["value"] == codeadmin.ERP_JAR_SOURCE_CUSTOM and item["jarCount"] == 2
        for item in bridge.codeAnalysisJarSourceItems
    ), timeout=10)
    workspace = bridge._settings.root

    # Libera A; resultado antigo (gen A, workspace A) deve ser ignorado.
    release.set()
    # Dá tempo p/ A terminar e tentar entregar resultado stale.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    bridge._poll_release_snapshot()
    QApplication.processEvents()

    custom = next(
        item for item in bridge.codeAnalysisJarSourceItems
        if item["value"] == codeadmin.ERP_JAR_SOURCE_CUSTOM
    )
    assert custom["jarCount"] == 2
    assert str(dir_b.resolve()) in custom["path"]
    assert bridge._jar_sources_generation == gen_b
    assert workspace == bridge._settings.root


# Scenario 25 — identidade da contagem usa workspace/path/generation, não índice
@pytest.mark.qml
def test_scenario_25_old_path_result_does_not_update_new_path(bridge, tmp_path):
    old_dir = tmp_path / "old_jars"
    old_dir.mkdir()
    _vr_jar(old_dir / "old.jar", (1, 0, 0, 0))
    new_dir = tmp_path / "new_jars"
    new_dir.mkdir()
    _vr_jar(new_dir / "new.jar", (1, 0, 0, 0))

    bridge._preferences.setValue(
        bridge._workspace_research_preference("custom_jar_source_dir"), str(old_dir)
    )
    bridge._preferences.sync()
    bridge._refresh_code_analysis_jar_sources()
    wait_until(lambda: any(
        item["value"] == codeadmin.ERP_JAR_SOURCE_CUSTOM and item["jarCount"] == 1
        for item in bridge.codeAnalysisJarSourceItems
    ))

    bridge._preferences.setValue(
        bridge._workspace_research_preference("custom_jar_source_dir"), str(new_dir)
    )
    bridge._preferences.sync()
    bridge._refresh_code_analysis_jar_sources()
    current_gen = bridge._jar_sources_generation
    wait_until(lambda: any(
        item["value"] == codeadmin.ERP_JAR_SOURCE_CUSTOM
        and str(new_dir.resolve()) in item["path"]
        for item in bridge.codeAnalysisJarSourceItems
    ))

    # Resultado antigo referencia o path antigo com contagem absurda.
    stale = (current_gen - 1, bridge._settings.root, {str(old_dir.resolve()): 999})
    bridge._on_jar_sources_counted(stale)
    custom = next(
        item for item in bridge.codeAnalysisJarSourceItems
        if item["value"] == codeadmin.ERP_JAR_SOURCE_CUSTOM
    )
    assert str(new_dir.resolve()) in custom["path"]
    assert custom["jarCount"] != 999


# Scenario 26 — partial release inalterado não é rejeitado pelo set comparison
def test_scenario_26_partial_release_unchanged_passes(tmp_path):
    source = tmp_path / "partial"
    source.mkdir()
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))
    _vr_jar(source / "vrpdv.jar", (2, 0, 0, 0))

    preview = preview_application_import(tmp_path / "ws", source, single=False)
    validate_preview_fingerprint(source, preview["fingerprint"], single=False)

    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=DEFAULT_EXPECTED_JAR_COUNT)
    manifest = catalog.snapshot_detected_release(source, release_id="partial-ok")
    assert manifest["analysis_scope"] == "partial_release"
    assert manifest["jar_count"] == 2


# Scenario 27 — full release 46 JARs funciona quando nada mudou
def test_scenario_27_full_release_46_jars(tmp_path):
    source = tmp_path / "full"
    source.mkdir()
    for i in range(DEFAULT_EXPECTED_JAR_COUNT):
        _vr_jar(source / f"vr_app_{i:02d}.jar", (1, 0, 0, i))

    preview = preview_application_import(tmp_path / "ws", source, single=False)
    assert len(preview["fingerprint"]) == DEFAULT_EXPECTED_JAR_COUNT
    validate_preview_fingerprint(source, preview["fingerprint"], single=False)

    catalog = ErpReleaseCatalog(tmp_path / "ws", expected_jar_count=DEFAULT_EXPECTED_JAR_COUNT)
    known = {item["relative_path"]: item["sha256"] for item in preview["fingerprint"]}
    manifest = catalog.snapshot_detected_release(
        source, release_id="full-ok", known_hashes=known
    )
    assert manifest["jar_count"] == DEFAULT_EXPECTED_JAR_COUNT
    assert manifest["analysis_scope"] == "full_release"


# Scenario 28 — single JAR preserva todos os casos
def test_scenario_28_single_jar_cases(tmp_path):
    ws = tmp_path / "ws"
    jar = tmp_path / "single.jar"
    _vr_jar(jar, (1, 0, 0, 0))

    preview = preview_application_import(ws, str(jar), single=True)
    validate_preview_fingerprint(str(jar), preview["fingerprint"], single=True)

    catalog = ErpReleaseCatalog(ws, expected_jar_count=1)
    manifest = catalog.snapshot_detected_release(str(jar), release_id="single-ok")
    assert manifest["analysis_scope"] == "single_jar"

    with pytest.raises(ErpReleaseError, match="Arquivo JAR não encontrado"):
        validate_preview_fingerprint(str(tmp_path / "missing.jar"), preview["fingerprint"], single=True)

    txt = tmp_path / "notajar.txt"
    txt.write_text("x", encoding="utf-8")
    with pytest.raises(ErpReleaseError):
        preview_application_import(ws, str(txt), single=True)

    with jar.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"ZZ")
    with pytest.raises(ErpReleaseError, match="mudaram após a prévia"):
        validate_preview_fingerprint(str(jar), preview["fingerprint"], single=True)

    # Restaura bytes originais p/ testar tamper com size+mtime preservados.
    _vr_jar(jar, (1, 0, 0, 0))
    preview2 = preview_application_import(ws, str(jar), single=True)
    known2 = {item["relative_path"]: item["sha256"] for item in preview2["fingerprint"]}
    st2 = jar.stat()
    size2 = st2.st_size
    mtime2 = st2.st_mtime_ns
    data = bytearray(jar.read_bytes())
    data[5] = (data[5] + 7) % 256
    jar.write_bytes(bytes(data))
    assert jar.stat().st_size == size2
    os.utime(jar, ns=(mtime2, mtime2))
    validate_preview_fingerprint(str(jar), preview2["fingerprint"], single=True)
    catalog2 = ErpReleaseCatalog(tmp_path / "ws2", expected_jar_count=1)
    with pytest.raises(ErpReleaseError, match="SHA-256 divergente"):
        catalog2.snapshot_detected_release(str(jar), release_id="single-tamper", known_hashes=known2)


@pytest.mark.qml
def test_package_import_publishes_ultra_choice_after_catalog_loads(bridge, tmp_path):
    source = tmp_path / "package"
    source.mkdir()
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))
    _vr_jar(source / "vrpdv.jar", (2, 0, 0, 0))

    assert bridge.previewApplicationImport(str(source), False, "") is True
    _wait_preview_ready(bridge)
    assert bridge.applicationImportPreview.get("state") == "ready"
    assert bridge.pendingImportedPackageForUltra == {}

    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)
    wait_until(lambda: bridge._apps_catalog_thread is None)
    QApplication.processEvents()

    pending = bridge.pendingImportedPackageForUltra
    assert pending["packageId"] == bridge._pending_ultra_package_choice_id
    assert pending["packageName"]
    assert pending["applicationCount"] == 2
    assert any(
        item.get("package_id") == pending["packageId"]
        for item in bridge.packagesCatalog
    )


@pytest.mark.qml
def test_pending_ultra_choice_is_hidden_until_catalog_has_package(bridge):
    bridge._pending_ultra_package_choice_id = "one"
    bridge._apps_catalog_data = {}
    assert bridge.pendingImportedPackageForUltra == {}


@pytest.mark.qml
def test_single_jar_import_does_not_publish_ultra_choice(bridge, tmp_path):
    jar = tmp_path / "single.jar"
    _vr_jar(jar, (1, 0, 0, 0))

    assert bridge.previewApplicationImport(str(jar), True, "") is True
    _wait_preview_ready(bridge)
    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)
    wait_until(lambda: bridge._apps_catalog_thread is None)
    QApplication.processEvents()
    assert bridge._pending_ultra_package_choice_id == ""
    assert bridge.pendingImportedPackageForUltra == {}


@pytest.mark.qml
def test_failed_package_snapshot_does_not_publish_ultra_choice(bridge, tmp_path):
    source = tmp_path / "source_changed"
    source.mkdir()
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))

    assert bridge.previewApplicationImport(str(source), False, "") is True
    _wait_preview_ready(bridge)
    assert bridge.applicationImportPreview.get("state") == "ready"

    _vr_jar(source / "vrpdv.jar", (2, 0, 0, 0))
    assert bridge.confirmApplicationImport() is True
    _wait_snapshot_idle(bridge)
    wait_until(lambda: bridge._apps_catalog_thread is None)
    QApplication.processEvents()
    assert "mudaram após a prévia" in bridge.releaseSnapshotStatus
    assert bridge._pending_ultra_package_choice_id == ""
    assert bridge.pendingImportedPackageForUltra == {}


@pytest.mark.qml
def test_dismiss_ultra_choice_clears_question_without_touching_contexts(bridge):
    bridge._ultra_application_contexts = [{
        "app_id": "vrapp",
        "version": "1.0.0",
        "variant_id": "sha-app",
        "package_id": "one",
    }]
    bridge._CodeAdmin_domain._save_application_contexts()
    bridge._apps_catalog_data = {
        "data": {
            "applications": {},
            "packages": {
                "one": {
                    "package_id": "one",
                    "name": "Pacote A",
                    "composition": [
                        {"app_id": "vrapp", "version": "1.0.0", "variant_id": "sha-app"},
                        {"app_id": "vrdep", "version": "2.0.0", "variant_id": "sha-dep"},
                    ],
                }
            },
        }
    }
    bridge._pending_ultra_package_choice_id = "one"
    bridge.stateChanged.emit()
    assert bridge.pendingImportedPackageForUltra["packageId"] == "one"
    assert bridge.pendingImportedPackageForUltra["packageName"] == "Pacote A"
    assert bridge.pendingImportedPackageForUltra["applicationCount"] == 2
    before = bridge.ultraApplicationContexts

    bridge.dismissImportedPackageUltraChoice("one")
    assert bridge.pendingImportedPackageForUltra == {}
    assert bridge.ultraApplicationContexts == before
    assert not bridge.codeAnalysisEnabled


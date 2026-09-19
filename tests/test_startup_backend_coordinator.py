"""Regressions for atomic backend builds, fail-closed bootstrap and async setup."""

from __future__ import annotations

import os
import time

import pytest
from PySide6.QtCore import QObject, QSettings, Signal, Slot
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import load_vr_settings
from vrsoft_extractor.mary.frontend.bootstrap import BootstrapBridge
from vrsoft_extractor.mary.frontend.startup import StartupBackendCoordinator
from vrsoft_extractor.mary.settings_service import SETUP_KEY_COMPLETED


def wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        QApplication.processEvents()
        assert time.monotonic() < deadline, "Qt task did not complete"
        time.sleep(0.005)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env_root(tmp_path, monkeypatch, qapp):
    root_dir = tmp_path / "vr_root"
    root_dir.mkdir(parents=True, exist_ok=True)
    app_dir = tmp_path / "app_dir"
    app_dir.mkdir(parents=True, exist_ok=True)
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
    monkeypatch.setenv("VR_ROOT", str(root_dir))
    settings = load_vr_settings(str(app_dir), str(root_dir))
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    prefs.clear()
    return {"settings": settings, "prefs": prefs, "root": root_dir}


class FakeChat(QObject):
    applicationsCatalogPhase = Signal(str, int, int)
    _applicationsLoaded = Signal(object)
    conversationArchived = Signal(str)

    def __init__(self, auto_ready=True):
        super().__init__()
        self._orchestrator = object()
        self._closed = False
        self.refresh_calls = 0
        self.auto_ready = auto_ready

    @Slot()
    def refresh(self):
        pass

    def refreshApplicationsCatalog(self):
        self.refresh_calls += 1
        if self.auto_ready:
            self.applicationsCatalogPhase.emit("loading_versions", 1, 2)
            self.applicationsCatalogPhase.emit("ready", 1, 2)

    def close(self):
        self._closed = True


class FakeStudio(QObject):
    conversationRestored = Signal()

    def __init__(self):
        super().__init__()
        self._closed = False

    def refreshArchived(self, _value=""):
        pass

    def close(self):
        self._closed = True


class StubWindow(QObject):
    frameSwapped = Signal()


def make_coordinator(env, **overrides):
    bootstrap = BootstrapBridge(
        env["settings"],
        env["prefs"],
        initial_state=overrides.pop("initial_state", "initializing"),
    )
    defaults = {
        "initialize_workspace_fn": lambda settings, refresh_conversations=False: object(),
        "chat_factory": lambda settings, db, prefs: FakeChat(),
        "studio_factory": lambda settings, db, prefs, orchestrator: FakeStudio(),
    }
    defaults.update(overrides)
    coordinator = StartupBackendCoordinator(
        settings=env["settings"],
        bootstrap_bridge=bootstrap,
        preferences=env["prefs"],
        **defaults,
    )
    return coordinator, bootstrap


def test_start_bootstrap_without_chat_fails_closed(env_root):
    """start_bootstrap() with no ChatBridge is an error, never ready."""
    bootstrap = make_coordinator(env_root)[1]
    assert bootstrap._chat_bridge is None
    bootstrap.start_bootstrap()
    assert bootstrap.state == "error"
    assert bootstrap.isReady is False
    assert bootstrap.errorMessage != ""


def test_partial_backend_never_published_and_retry_rebuilds_all(env_root):
    """Chat ok + Studio failure publishes nothing; retry rebuilds everything."""
    calls = {"chat": 0, "studio": 0}
    created_chats = []

    def chat_factory(settings, db, prefs):
        calls["chat"] += 1
        chat = FakeChat()
        created_chats.append(chat)
        return chat

    def studio_factory(settings, db, prefs, orchestrator):
        calls["studio"] += 1
        if calls["studio"] == 1:
            raise RuntimeError("studio offline")
        return FakeStudio()

    coordinator, bootstrap = make_coordinator(
        env_root, chat_factory=chat_factory, studio_factory=studio_factory
    )

    with pytest.raises(RuntimeError, match="studio offline"):
        coordinator.setup_backend(env_root["settings"])

    # Nothing partial published: refs untouched, bootstrap unattached.
    assert coordinator.database is None
    assert coordinator.chat_bridge is None
    assert coordinator.studio_bridge is None
    assert bootstrap._chat_bridge is None
    assert coordinator.is_backend_ready() is False
    # The partial chat was closed, never leaked as live backend.
    assert created_chats[0]._closed is True

    # Retry rebuilds the entire backend (never ready without StudioBridge).
    coordinator.bootstrap_or_retry()
    assert calls == {"chat": 2, "studio": 2}
    assert coordinator.is_backend_ready() is True
    assert bootstrap.isAttachedTo(coordinator.chat_bridge) is True
    wait_until(lambda: bootstrap.state == "ready")
    assert bootstrap.isReady is True


def test_backend_failure_before_chat_rebuilds_on_retry(env_root):
    """initialize_workspace failure -> error; retry runs the whole init again."""
    attempts = {"count": 0}

    def flaky_init(settings, refresh_conversations=False):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("disk offline")
        return object()

    coordinator, bootstrap = make_coordinator(
        env_root, initialize_workspace_fn=flaky_init
    )
    coordinator.bootstrap_or_retry()
    assert bootstrap.state == "error"
    assert bootstrap.isReady is False
    assert coordinator.is_backend_ready() is False

    coordinator.bootstrap_or_retry()
    assert attempts["count"] == 2
    assert coordinator.is_backend_ready() is True
    wait_until(lambda: bootstrap.state == "ready")


def test_catalog_failure_reuses_valid_backend(env_root):
    """Backend complete + catalog error -> retry reloads catalog only."""
    built = {"chat": 0, "studio": 0}

    def chat_factory(settings, db, prefs):
        built["chat"] += 1
        return FakeChat(auto_ready=False)

    def studio_factory(settings, db, prefs, orchestrator):
        built["studio"] += 1
        return FakeStudio()

    coordinator, bootstrap = make_coordinator(
        env_root, chat_factory=chat_factory, studio_factory=studio_factory
    )
    coordinator.bootstrap_or_retry()
    chat = coordinator.chat_bridge
    assert coordinator.is_backend_ready() is True
    assert chat.refresh_calls == 1

    # Catalog fails after the backend is complete.
    bootstrap._on_catalog_phase("error", 0, 0)
    assert bootstrap.state == "error"

    coordinator.bootstrap_or_retry()
    assert built == {"chat": 1, "studio": 1}
    assert coordinator.chat_bridge is chat
    assert chat.refresh_calls == 2


def test_setup_async_completion_marks_completed_only_on_success(env_root):
    """save -> initializing + completed false; success -> completed + catalog."""
    coordinator = make_coordinator(env_root)[0]

    requested = []
    completed = []
    bootstrap2 = BootstrapBridge(
        env_root["settings"],
        env_root["prefs"],
        initial_state="setup",
        on_setup_completed=requested.append,
    )
    bootstrap2.setupCompleted.connect(completed.append)

    bootstrap2.saveSetup(
        str(env_root["root"]),
        "admin@vr.com.br",
        "",
        "admin@vr.com.br",
        "",
        "120",
    )
    assert bootstrap2.state == "initializing"
    assert len(requested) == 1
    assert completed == []
    assert str(env_root["prefs"].value(SETUP_KEY_COMPLETED, "false")).lower() != "true"

    # Coordinator finishes the backend after the loading frame (sync here).
    coordinator._bootstrap = bootstrap2
    coordinator._run_setup_backend(requested[0])
    assert str(env_root["prefs"].value(SETUP_KEY_COMPLETED)).lower() == "true"
    assert len(completed) == 1
    assert coordinator.is_backend_ready() is True
    assert coordinator.chat_bridge.refresh_calls == 1


def test_setup_async_failure_keeps_setup_open(env_root):
    """save -> initializing; backend failure -> setup + completed false."""
    requested = []
    bootstrap = BootstrapBridge(
        env_root["settings"],
        env_root["prefs"],
        initial_state="setup",
        on_setup_completed=requested.append,
    )
    bootstrap.saveSetup(
        str(env_root["root"]),
        "admin@vr.com.br",
        "",
        "admin@vr.com.br",
        "",
        "120",
    )
    assert bootstrap.state == "initializing"

    bootstrap.setupInitializationFailed("db offline")
    assert bootstrap.state == "setup"
    assert bootstrap.isSetupActive is True
    assert bootstrap.errorMessage != ""
    assert str(env_root["prefs"].value(SETUP_KEY_COMPLETED, "false")).lower() != "true"


def test_root_pending_restart_shows_persisted_values(env_root, tmp_path):
    """A/120 -> save B/240: backend stays A, UI shows B/240 + restart flag."""
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    from vrsoft_extractor.mary.db import MaryDatabase

    old_root = env_root["root"]
    settings = env_root["settings"]
    prefs = env_root["prefs"]
    db = MaryDatabase(settings.database_path, root=settings.root)
    studio = StudioBridge(settings, db, prefs)
    try:
        new_root = tmp_path / "workspace_b"
        studio.saveSettings(str(new_root), "b@vr.com.br", "", "endoo@vr.com.br", "", "240")

        assert studio._settings.root == old_root
        assert os.environ["VR_ROOT"] == str(old_root)
        assert str(new_root) in (settings.app_dir / ".env").read_text(encoding="utf-8")
        assert studio.settingsValues["root"] == str(new_root)
        assert studio.settingsValues["interval"] == "240"
        assert studio.settingsValues["movideskEmail"] == "b@vr.com.br"
        assert studio.restartRequiredForRoot is True

        # Same-root save clears the pending restart.
        studio.saveSettings(str(old_root), "c@vr.com.br", "", "endoo@vr.com.br", "", "60")
        assert studio.restartRequiredForRoot is False
        assert studio.settingsValues["interval"] == "60"
    finally:
        studio.close()


def test_coordinator_with_real_bridges_normal_flow(env_root):
    """Real database + ChatBridge + StudioBridge: shell -> backend -> catalog -> ready."""
    from vrsoft_extractor.mary.workspace import initialize_workspace

    bootstrap = BootstrapBridge(
        env_root["settings"], env_root["prefs"], initial_state="initializing"
    )
    coordinator = StartupBackendCoordinator(
        settings=env_root["settings"],
        bootstrap_bridge=bootstrap,
        preferences=env_root["prefs"],
        initialize_workspace_fn=initialize_workspace,
    )
    assert coordinator.is_backend_ready() is False

    coordinator.bootstrap_or_retry()
    assert coordinator.is_backend_ready() is True
    assert bootstrap.isAttachedTo(coordinator.chat_bridge) is True
    wait_until(lambda: bootstrap.state == "ready", timeout=20.0)
    assert bootstrap.isReady is True
    assert bootstrap.appsCount == 0
    coordinator.chat_bridge.close()
    coordinator.studio_bridge.close()


def test_backend_starts_only_after_first_frame(env_root):
    """The frameSwapped gate: no backend work before the first presented frame."""
    built = []
    coordinator = make_coordinator(
        env_root,
        initialize_workspace_fn=lambda settings, refresh_conversations=False: built.append(True) or object(),
    )[0]
    window = StubWindow()
    coordinator.request_normal_startup(window)
    QApplication.processEvents()
    assert built == []

    window.frameSwapped.emit()
    wait_until(lambda: built != [])
    wait_until(lambda: coordinator.is_backend_ready() is True)

    # A second frame never rebuilds the backend.
    window.frameSwapped.emit()
    QApplication.processEvents()
    assert len(built) == 1


def test_coordinator_normal_flow_shell_to_ready(env_root):
    """Normal: shell -> backend -> catalog -> ready via the real coordinator."""
    coordinator, bootstrap = make_coordinator(env_root)
    window = StubWindow()
    coordinator.request_normal_startup(window)
    assert coordinator.is_backend_ready() is False

    window.frameSwapped.emit()
    wait_until(lambda: bootstrap.state == "ready", timeout=15.0)
    assert bootstrap.isReady is True
    assert coordinator.is_backend_ready() is True


def test_coordinator_firstrun_flow_setup_to_ready(env_root):
    """First run: setup -> save -> frame -> backend -> completed -> catalog -> ready."""
    coordinator, _ = make_coordinator(env_root)
    window = StubWindow()
    coordinator.set_window(window)
    bootstrap = BootstrapBridge(
        env_root["settings"],
        env_root["prefs"],
        initial_state="setup",
        on_setup_completed=coordinator.request_setup_backend,
        on_bootstrap_retry=coordinator.bootstrap_or_retry,
    )
    coordinator._bootstrap = bootstrap

    assert bootstrap.state == "setup"
    bootstrap.saveSetup(
        str(env_root["root"]),
        "admin@vr.com.br",
        "",
        "admin@vr.com.br",
        "",
        "120",
    )
    assert bootstrap.state == "initializing"
    assert coordinator.is_backend_ready() is False
    assert str(env_root["prefs"].value(SETUP_KEY_COMPLETED, "false")).lower() != "true"

    window.frameSwapped.emit()
    wait_until(lambda: bootstrap.state == "ready", timeout=15.0)
    assert bootstrap.isReady is True
    assert coordinator.is_backend_ready() is True
    assert str(env_root["prefs"].value(SETUP_KEY_COMPLETED)).lower() == "true"

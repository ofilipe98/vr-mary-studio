"""Regressions for atomic backend builds, fail-closed bootstrap and async setup."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import pytest
from PySide6.QtCore import QObject, QSettings, QTimer, Signal, Slot
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
    wait_until(lambda: coordinator.is_backend_ready() is True)
    assert calls == {"chat": 2, "studio": 2}
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
    wait_until(lambda: bootstrap.state == "error")
    assert bootstrap.isReady is False
    assert coordinator.is_backend_ready() is False

    coordinator.bootstrap_or_retry()
    wait_until(lambda: attempts["count"] == 2)
    wait_until(lambda: coordinator.is_backend_ready() is True)
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
    wait_until(lambda: coordinator.is_backend_ready() is True)
    chat = coordinator.chat_bridge
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
    )
    bootstrap2.setupInitializationRequested.connect(requested.append)
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

    # Coordinator finishes the backend on its worker, then publishes on UI.
    coordinator._bootstrap = bootstrap2
    coordinator._run_setup_backend(requested[0])
    wait_until(lambda: coordinator.is_backend_ready() is True)
    wait_until(lambda: len(completed) == 1)
    assert str(env_root["prefs"].value(SETUP_KEY_COMPLETED)).lower() == "true"
    assert coordinator.chat_bridge.refresh_calls == 1


def test_setup_async_failure_keeps_setup_open(env_root):
    """save -> initializing; backend failure -> setup + completed false."""
    requested = []
    bootstrap = BootstrapBridge(
        env_root["settings"],
        env_root["prefs"],
        initial_state="setup",
    )
    bootstrap.setupInitializationRequested.connect(requested.append)
    bootstrap.saveSetup(
        str(env_root["root"]),
        "admin@vr.com.br",
        "",
        "admin@vr.com.br",
        "",
        "120",
    )
    assert bootstrap.state == "initializing"
    assert len(requested) == 1

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
    wait_until(lambda: coordinator.is_backend_ready() is True, timeout=20.0)
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
        on_bootstrap_retry=coordinator.bootstrap_or_retry,
    )
    bootstrap.setupInitializationRequested.connect(coordinator.request_setup_backend)
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


def test_first_frame_handler_disconnects_after_first_frame(env_root):
    """frameSwapped is a real one-shot: 3 frames run the action exactly once."""
    coordinator = make_coordinator(env_root)[0]
    window = StubWindow()
    runs: list[int] = []
    coordinator._arm_first_frame(lambda: runs.append(1), window)
    QApplication.processEvents()
    assert runs == []
    assert coordinator._frame_connected is True

    window.frameSwapped.emit()
    wait_until(lambda: runs == [1])
    assert coordinator._frame_connected is False

    # Frames 2 and 3 must not invoke the handler again (no ~60 FPS drain).
    window.frameSwapped.emit()
    window.frameSwapped.emit()
    QApplication.processEvents()
    QApplication.processEvents()
    assert runs == [1]

    # Re-arming installs exactly one new one-shot connection.
    coordinator._arm_first_frame(lambda: runs.append(2), window)
    assert coordinator._frame_connected is True
    window.frameSwapped.emit()
    wait_until(lambda: runs == [1, 2])
    window.frameSwapped.emit()
    QApplication.processEvents()
    assert runs == [1, 2]


def test_prepare_worker_keeps_ui_responsive_and_publishes_on_ui_thread(env_root):
    """Blocked prepare: loading stays alive, publish happens on UI thread."""
    entered = threading.Event()
    release = threading.Event()
    main_ident = threading.get_ident()
    factory_idents: list[int] = []
    calls = []

    def blocked_init(settings, refresh_conversations=False):
        calls.append(1)
        entered.set()
        assert release.wait(10), "worker was never released"
        return object()

    def chat_factory(settings, database, prefs):
        factory_idents.append(threading.get_ident())
        return FakeChat()

    coordinator, bootstrap = make_coordinator(
        env_root,
        initialize_workspace_fn=blocked_init,
        chat_factory=chat_factory,
        studio_factory=lambda settings, db, prefs, orchestrator: FakeStudio(),
    )
    coordinator.bootstrap_or_retry()
    assert entered.wait(5)
    assert coordinator.is_preparing() is True

    # The Qt event loop still runs while the worker is blocked.
    beat: list[bool] = []
    QTimer.singleShot(0, lambda: beat.append(True))
    wait_until(lambda: beat == [True])
    # Nothing is published before the worker finishes (atomicity kept).
    assert coordinator.is_backend_ready() is False
    assert coordinator.chat_bridge is None

    release.set()
    wait_until(lambda: coordinator.is_backend_ready() is True)
    wait_until(lambda: bootstrap.state == "ready")
    assert calls == [1]
    # QObject bridges were created on the UI thread, never on the worker.
    assert factory_idents == [main_ident]


def test_retry_while_preparing_does_not_spawn_second_worker(env_root):
    """A fast retry during an in-flight prepare is ignored, never doubled."""
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def counting_init(settings, refresh_conversations=False):
        calls.append(1)
        entered.set()
        assert release.wait(10), "worker was never released"
        return object()

    coordinator, bootstrap = make_coordinator(
        env_root, initialize_workspace_fn=counting_init
    )
    coordinator.bootstrap_or_retry()
    assert entered.wait(5)
    # Retry while busy: no second worker, same generation still in flight.
    coordinator.bootstrap_or_retry()
    coordinator.bootstrap_or_retry()
    QApplication.processEvents()
    assert coordinator.is_preparing() is True

    release.set()
    wait_until(lambda: coordinator.is_backend_ready() is True)
    wait_until(lambda: bootstrap.state == "ready")
    assert len(calls) == 1


def test_shutdown_drops_late_worker_result(env_root):
    """Closing during bootstrap never publishes a late backend afterwards."""
    entered = threading.Event()
    release = threading.Event()

    def blocked_init(settings, refresh_conversations=False):
        entered.set()
        assert release.wait(10), "worker was never released"
        return object()

    coordinator, bootstrap = make_coordinator(
        env_root, initialize_workspace_fn=blocked_init
    )
    coordinator.bootstrap_or_retry()
    assert entered.wait(5)
    coordinator.shutdown()
    release.set()
    # Let the queued worker completion (now stale) arrive and be dropped.
    wait_until(lambda: coordinator.is_preparing() is False)
    QApplication.processEvents()
    QApplication.processEvents()
    assert coordinator.is_backend_ready() is False
    assert coordinator.chat_bridge is None
    assert bootstrap.state == "initializing"


def test_restore_runs_only_for_new_backend(env_root):
    """Catalog-only retry reuses the backend without repeating the restore."""
    restores: list[Any] = []

    def chat_factory(settings, database, prefs):
        return FakeChat(auto_ready=False)

    bootstrap = BootstrapBridge(
        env_root["settings"], env_root["prefs"], initial_state="initializing"
    )
    coordinator = StartupBackendCoordinator(
        settings=env_root["settings"],
        bootstrap_bridge=bootstrap,
        preferences=env_root["prefs"],
        initialize_workspace_fn=lambda settings, refresh_conversations=False: object(),
        chat_factory=chat_factory,
        studio_factory=lambda settings, db, prefs, orchestrator: FakeStudio(),
        on_backend_started=restores.append,
    )
    coordinator.bootstrap_or_retry()
    wait_until(lambda: coordinator.is_backend_ready() is True)
    assert len(restores) == 1
    assert coordinator.chat_bridge.refresh_calls == 1

    # Catalog fails after a valid backend: retry reloads the catalog only.
    bootstrap._on_catalog_phase("error", 0, 0)
    assert bootstrap.state == "error"
    coordinator.bootstrap_or_retry()
    wait_until(lambda: coordinator.chat_bridge.refresh_calls == 2)
    assert coordinator.is_backend_ready() is True
    assert len(restores) == 1

    # A genuinely rebuilt backend schedules the restore exactly once more.
    bootstrap.detach_chat_bridge()
    assert coordinator.is_backend_ready() is False
    coordinator.bootstrap_or_retry()
    wait_until(lambda: coordinator.is_backend_ready() is True)
    assert len(restores) == 2


def test_setup_request_uses_single_signal_contract(env_root):
    """saveSetup fires setupInitializationRequested exactly once, no callback."""
    bridge = BootstrapBridge(
        env_root["settings"], env_root["prefs"], initial_state="setup"
    )
    assert not hasattr(bridge, "_on_setup_completed")
    requested: list[Any] = []
    bridge.setupInitializationRequested.connect(requested.append)
    bridge.saveSetup(
        str(env_root["root"]),
        "admin@vr.com.br",
        "",
        "admin@vr.com.br",
        "",
        "120",
    )
    assert bridge.state == "initializing"
    assert len(requested) == 1


def test_stale_ready_completion_never_clobbers_newer_worker(env_root):
    """A finishes with completion pending -> B starts -> stale A runs.

    B must stay recognised as active, an extra retry must not create C,
    and only B may publish the backend.
    """
    entered_a = threading.Event()
    release_a = threading.Event()
    entered_b = threading.Event()
    release_b = threading.Event()
    calls: list[int] = []

    def counting_init(settings, refresh_conversations=False):
        calls.append(1)
        if len(calls) == 1:
            entered_a.set()
            assert release_a.wait(10), "worker A was never released"
            return object()
        entered_b.set()
        assert release_b.wait(10), "worker B was never released"
        return object()

    coordinator, bootstrap = make_coordinator(
        env_root, initialize_workspace_fn=counting_init
    )
    coordinator.bootstrap_or_retry()
    assert entered_a.wait(5)
    thread_a = coordinator._prepare_thread
    assert thread_a is not None
    assert coordinator.is_preparing() is True

    # Let A terminate but keep its queued completion undelivered.
    release_a.set()
    deadline = time.monotonic() + 5.0
    while thread_a.is_alive():
        assert time.monotonic() < deadline, "worker A did not terminate"
        time.sleep(0.005)

    # B starts before A's stale completion is processed.
    coordinator.bootstrap_or_retry()
    assert entered_b.wait(5)
    thread_b = coordinator._prepare_thread
    assert thread_b is not None and thread_b is not thread_a
    assert coordinator.is_preparing() is True

    # Deliver the stale A completion: B stays the active worker.
    QApplication.processEvents()
    QApplication.processEvents()
    assert coordinator._prepare_thread is thread_b
    assert coordinator.is_preparing() is True
    assert coordinator.is_backend_ready() is False

    # An extra retry while B is in flight must not spawn worker C.
    coordinator.bootstrap_or_retry()
    QApplication.processEvents()
    assert len(calls) == 2
    assert coordinator._prepare_thread is thread_b
    assert coordinator.is_preparing() is True

    # Only B publishes the backend.
    release_b.set()
    wait_until(lambda: coordinator.is_backend_ready() is True)
    wait_until(lambda: bootstrap.state == "ready")
    assert len(calls) == 2


def test_stale_failed_completion_never_clobbers_newer_worker(env_root):
    """A stale failure must not clear a newer in-flight worker."""

    class _AliveThread:
        def is_alive(self) -> bool:
            return True

    coordinator, bootstrap = make_coordinator(env_root)
    newer = _AliveThread()
    coordinator._prepare_thread = newer  # type: ignore[assignment]
    coordinator._prepare_generation = 7
    coordinator._prepare_is_setup = False

    # Stale generation 6 arrives while generation 7 is active.
    coordinator._on_prepare_failed(6, RuntimeError("stale"))
    assert coordinator._prepare_thread is newer
    assert coordinator.is_preparing() is True
    assert bootstrap.state == "initializing"

    # The current generation still reports its own failure normally.
    coordinator._on_prepare_failed(7, RuntimeError("current"))
    assert coordinator._prepare_thread is None
    assert bootstrap.state == "error"


def test_prepare_preserves_gc_when_enabled(env_root):
    """Worker leaves the cyclic GC enabled when it started enabled."""
    import gc as gc_module

    previous = gc_module.isenabled()
    try:
        gc_module.enable()
        assert gc_module.isenabled() is True
        coordinator, bootstrap = make_coordinator(env_root)
        coordinator.bootstrap_or_retry()
        wait_until(lambda: coordinator.is_backend_ready() is True)
        wait_until(lambda: bootstrap.state == "ready")
        assert gc_module.isenabled() is True
    finally:
        if not previous:
            gc_module.disable()
        else:
            gc_module.enable()


def test_prepare_preserves_gc_when_disabled(env_root):
    """Worker never re-enables a GC that was already disabled."""
    import gc as gc_module

    previous = gc_module.isenabled()
    try:
        gc_module.disable()
        assert gc_module.isenabled() is False
        coordinator, bootstrap = make_coordinator(env_root)
        coordinator.bootstrap_or_retry()
        wait_until(lambda: coordinator.is_backend_ready() is True)
        wait_until(lambda: bootstrap.state == "ready")
        assert gc_module.isenabled() is False
    finally:
        if previous:
            gc_module.enable()
        else:
            gc_module.disable()


def test_shutdown_during_worker_touches_nothing(env_root):
    """Shutdown during prepare: no publish, no context props, no restore."""
    entered = threading.Event()
    release = threading.Event()
    restores: list[Any] = []
    context_calls: list[tuple[str, Any]] = []

    def blocked_init(settings, refresh_conversations=False):
        entered.set()
        assert release.wait(10), "worker was never released"
        return object()

    class _FakeContext:
        def setContextProperty(self, name: str, value: Any) -> None:
            context_calls.append((name, value))

    class _FakeEngine:
        def __init__(self) -> None:
            self._ctx = _FakeContext()

        def rootContext(self) -> _FakeContext:
            return self._ctx

    bootstrap = BootstrapBridge(
        env_root["settings"], env_root["prefs"], initial_state="initializing"
    )
    coordinator = StartupBackendCoordinator(
        settings=env_root["settings"],
        bootstrap_bridge=bootstrap,
        preferences=env_root["prefs"],
        initialize_workspace_fn=blocked_init,
        chat_factory=lambda settings, db, prefs: FakeChat(),
        studio_factory=lambda settings, db, prefs, orchestrator: FakeStudio(),
        on_backend_started=restores.append,
    )
    engine = _FakeEngine()
    coordinator.set_engine(engine)  # type: ignore[arg-type]
    coordinator.bootstrap_or_retry()
    assert entered.wait(5)
    coordinator.shutdown()
    release.set()
    wait_until(lambda: coordinator.is_preparing() is False)
    QApplication.processEvents()
    QApplication.processEvents()
    assert coordinator.is_backend_ready() is False
    assert coordinator.chat_bridge is None
    assert coordinator.studio_bridge is None
    assert bootstrap.state == "initializing"
    assert bootstrap._chat_bridge is None
    assert restores == []
    assert context_calls == []


def test_backend_failure_retry_transitions_immediately_to_initializing_and_completes_to_ready(
    env_root,
):
    """Backend failure -> error; retry transitions immediately to initializing -> ready."""
    attempts = {"count": 0}
    worker_running = threading.Event()
    worker_release = threading.Event()

    def flaky_init(settings, refresh_conversations=False):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("primeira falha no banco")
        worker_running.set()
        assert worker_release.wait(10), "worker nunca foi liberado"
        return object()

    coordinator, bootstrap = make_coordinator(
        env_root, initialize_workspace_fn=flaky_init
    )
    bootstrap._on_bootstrap_retry = coordinator.bootstrap_or_retry

    # Initial run fails
    coordinator.bootstrap_or_retry()
    wait_until(lambda: bootstrap.state == "error")
    assert bootstrap.state == "error"
    assert "primeira falha no banco" in bootstrap.errorMessage
    assert bootstrap.isReady is False
    assert bootstrap.isBusy is False
    assert coordinator.is_backend_ready() is False

    # Retry triggered
    bootstrap.retryBootstrap()

    # Must be immediately in initializing while worker is still blocked
    assert worker_running.wait(5)
    assert bootstrap.state == "initializing"
    assert bootstrap.isBusy is True
    assert bootstrap.isReady is False
    assert bootstrap.errorMessage == ""
    assert coordinator.is_preparing() is True

    # Allow worker to complete
    worker_release.set()
    wait_until(lambda: attempts["count"] == 2)
    wait_until(lambda: coordinator.is_backend_ready() is True)
    wait_until(lambda: bootstrap.state == "ready")
    assert bootstrap.isReady is True
    assert bootstrap.isBusy is False


def test_retry_failure_transitions_through_initializing_to_error_with_new_message(
    env_root,
):
    """Error -> retry -> initializing -> worker fails again -> error with new message."""
    attempts = {"count": 0}
    worker_running = threading.Event()
    worker_release = threading.Event()

    def flaky_init(settings, refresh_conversations=False):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("falha 1")
        worker_running.set()
        assert worker_release.wait(10), "worker nunca foi liberado"
        raise RuntimeError("falha 2")

    coordinator, bootstrap = make_coordinator(
        env_root, initialize_workspace_fn=flaky_init
    )
    bootstrap._on_bootstrap_retry = coordinator.bootstrap_or_retry

    # Initial failure
    coordinator.bootstrap_or_retry()
    wait_until(lambda: bootstrap.state == "error")
    assert "falha 1" in bootstrap.errorMessage

    # Retry
    bootstrap.retryBootstrap()

    # Immediately initializing
    assert worker_running.wait(5)
    assert bootstrap.state == "initializing"
    assert bootstrap.errorMessage == ""
    assert coordinator.is_preparing() is True

    # Allow worker to fail
    worker_release.set()
    wait_until(lambda: bootstrap.state == "error")
    assert "falha 2" in bootstrap.errorMessage
    assert bootstrap.isReady is False
    assert bootstrap.isBusy is False


def test_retry_in_flight_prevents_duplicate_worker_and_preserves_busy(env_root):
    """Calling retry while a worker is already running does not spawn another worker."""
    attempts = {"count": 0}
    worker_running = threading.Event()
    worker_release = threading.Event()

    def blocked_init(settings, refresh_conversations=False):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("falha inicial")
        worker_running.set()
        assert worker_release.wait(10), "worker nunca foi liberado"
        return object()

    coordinator, bootstrap = make_coordinator(
        env_root, initialize_workspace_fn=blocked_init
    )
    bootstrap._on_bootstrap_retry = coordinator.bootstrap_or_retry

    # Initial failure
    coordinator.bootstrap_or_retry()
    wait_until(lambda: bootstrap.state == "error")

    # Start retry worker
    bootstrap.retryBootstrap()
    assert worker_running.wait(5)
    assert coordinator.is_preparing() is True
    assert bootstrap.state == "initializing"
    assert bootstrap.isBusy is True

    initial_thread = coordinator._prepare_thread
    initial_gen = coordinator._prepare_generation

    # Second retry attempt while busy
    coordinator.bootstrap_or_retry()
    assert coordinator._prepare_thread is initial_thread
    assert coordinator._prepare_generation == initial_gen
    assert attempts["count"] == 2
    assert bootstrap.state == "initializing"
    assert bootstrap.isBusy is True

    # Let worker finish
    worker_release.set()
    wait_until(lambda: coordinator.is_backend_ready() is True)
    wait_until(lambda: bootstrap.state == "ready")


def test_catalog_failure_retry_never_enters_initializing(env_root):
    """Backend valid + catalog error: retry goes to loading_apps without entering initializing."""
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
    bootstrap._on_bootstrap_retry = coordinator.bootstrap_or_retry

    coordinator.bootstrap_or_retry()
    wait_until(lambda: coordinator.is_backend_ready() is True)
    chat = coordinator.chat_bridge
    assert chat.refresh_calls == 1

    # Simulate catalog failure
    bootstrap._on_catalog_phase("error", 0, 0)
    assert bootstrap.state == "error"

    recorded_states: list[str] = []
    bootstrap.stateChanged.connect(lambda: recorded_states.append(bootstrap.state))

    # Retry
    bootstrap.retryBootstrap()

    # State must transition directly to loading_apps, NEVER initializing
    assert "initializing" not in recorded_states
    assert bootstrap.state == "loading_apps"
    assert built == {"chat": 1, "studio": 1}
    assert coordinator.chat_bridge is chat
    assert chat.refresh_calls == 2

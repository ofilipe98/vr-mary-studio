"""Testable coordinator for the shell-first startup lifecycle.

Normal launch and first-run setup share one coordinator:

    FIRST RUN  app -> setup -> save -> loading frame -> backend
               -> setup/completed -> apps -> versions -> ready -> main
    NORMAL     app -> loading frame -> backend -> apps -> versions
               -> ready -> main

The coordinator owns the three backend references (database, ChatBridge,
StudioBridge) and publishes them atomically: everything is built in local
variables first and swapped in only after ChatBridge AND StudioBridge exist.
A failure discards the partial objects (closing the new bridges), keeps the
previous backend untouched when one is live, and never attaches the
BootstrapBridge to an incomplete backend.

Heavy work never runs before the loading shell has presented at least one
real frame: backend starts from the window ``frameSwapped`` signal (one-shot),
falling back to a queued ``QTimer.singleShot(0, ...)`` only when no window or
no such signal exists (headless/tests). No sleeps, no fake delays.

Threading model (responsive loading):

    UI THREAD     loading frame presented
                      |
    WORKER        prepare workspace: ensure_dirs, portable project files,
                  MaryDatabase construction + migrations. MaryDatabase keeps
                  no open SQLite connection (every operation opens its own
                  ``sqlite3.connect`` via the ``connect()`` context manager
                  and closes it), so building it off the UI thread is safe.
                  No QObject is ever created here.
                      |
    UI THREAD     create ChatBridge + StudioBridge (QObjects), connect
                  signals, publish atomically, attach bootstrap, close the
                  previous backend. Catalog refresh is async inside ChatBridge.
"""

from __future__ import annotations

import gc
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal, Slot

from ..config import MarySettings
from ..db import MaryDatabase
from ..workspace import initialize_workspace


def _default_chat_factory(
    settings: MarySettings,
    database: MaryDatabase,
    preferences: QSettings | None,
) -> Any:
    from .chat import ChatBridge

    return ChatBridge(settings, database, preferences, open_new_chat=True)


def _default_studio_factory(
    settings: MarySettings,
    database: MaryDatabase,
    preferences: QSettings | None,
    orchestrator: Any,
) -> Any:
    from .studio import StudioBridge

    return StudioBridge(
        settings,
        database,
        preferences,
        chat_orchestrator=orchestrator,
    )


def _safe_close(bridge: Any) -> None:
    if bridge is None:
        return
    try:
        bridge.close()
    except Exception:
        pass


class StartupBackendCoordinator(QObject):
    """Owns backend construction, readiness checks and deferred startup."""

    # Worker -> UI handoff. Emitted from the prepare thread; the slots run
    # on the UI thread via QueuedConnection and publish the backend there.
    _prepareReady = Signal(int, object)
    _prepareFailed = Signal(int, object)

    def __init__(
        self,
        *,
        settings: MarySettings,
        bootstrap_bridge: Any,
        frontend_bridge: Any = None,
        preferences: QSettings | None = None,
        initialize_workspace_fn: Callable[..., MaryDatabase] | None = None,
        chat_factory: Callable[..., Any] | None = None,
        studio_factory: Callable[..., Any] | None = None,
        on_backend_started: Callable[[Any], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._bootstrap = bootstrap_bridge
        self._frontend = frontend_bridge
        self._preferences = preferences
        self._init_workspace = initialize_workspace_fn or initialize_workspace
        self._chat_factory = chat_factory or _default_chat_factory
        self._studio_factory = studio_factory or _default_studio_factory
        self._on_backend_started = on_backend_started
        self.database: MaryDatabase | None = None
        self.chat_bridge: Any = None
        self.studio_bridge: Any = None
        self._engine: Any = None
        self._window: Any = None
        self._pending_setup_settings: MarySettings | None = None
        self._pending_frame_actions: list[Callable[[], None]] = []
        self._frame_connected = False
        self._frame_signal: Any = None
        # Async prepare lifecycle: only one worker at a time. The generation
        # invalidates stale completions (retry shadowing, shutdown).
        self._prepare_generation = 0
        self._prepare_thread: threading.Thread | None = None
        self._prepare_is_setup = False
        self._shutdown = False
        self._prepareReady.connect(
            self._on_prepare_ready, Qt.ConnectionType.QueuedConnection
        )
        self._prepareFailed.connect(
            self._on_prepare_failed, Qt.ConnectionType.QueuedConnection
        )

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_engine(self, engine: Any) -> None:
        self._engine = engine

    def set_window(self, window: Any) -> None:
        self._window = window

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    def is_backend_ready(self) -> bool:
        """Explicit backend check: database + both bridges + bootstrap link.

        A non-None ``chat_bridge`` alone never proves readiness: after a
        partial build (e.g. StudioBridge failed) the bootstrap is not
        attached to the current chat, so this returns False and the retry
        path rebuilds the whole backend instead of reusing the partial one.
        """
        if (
            self.database is None
            or self.chat_bridge is None
            or self.studio_bridge is None
        ):
            return False
        if getattr(self.chat_bridge, "_closed", False):
            return False
        if getattr(self.studio_bridge, "_closed", False):
            return False
        is_attached = getattr(self._bootstrap, "isAttachedTo", None)
        if callable(is_attached):
            return bool(is_attached(self.chat_bridge))
        return getattr(self._bootstrap, "_chat_bridge", None) is self.chat_bridge

    # ------------------------------------------------------------------
    # Atomic backend construction (UI thread; bridges are QObjects)
    # ------------------------------------------------------------------

    def _prepare_workspace(self, target_settings: MarySettings) -> MaryDatabase:
        """Heavy, QObject-free preparation. Safe to run on a worker thread.

        Covers directory creation/verification, portable project files and
        database migrations. MaryDatabase keeps no open SQLite connection
        (see ``MaryDatabase.connect``: one ``sqlite3.connect`` per use),
        so constructing it here never shares a thread-affine connection
        with the UI thread. No ChatBridge/StudioBridge (QObjects) is
        created here.
        """
        return self._init_workspace(target_settings, refresh_conversations=False)

    def _publish_backend(
        self, target_settings: MarySettings, new_database: MaryDatabase
    ) -> None:
        """Create the QObject bridges and publish atomically. UI thread only.

        Raises the original exception on failure after closing any partially
        created new bridges. Previously published references are left
        untouched so an existing usable backend survives a failed rebuild.
        """
        new_chat = None
        new_studio = None
        try:
            new_chat = self._chat_factory(
                target_settings, new_database, self._preferences
            )
            try:
                new_studio = self._studio_factory(
                    target_settings,
                    new_database,
                    self._preferences,
                    getattr(new_chat, "_orchestrator", None),
                )
            except Exception:
                _safe_close(new_chat)
                raise
        except Exception:
            # MaryDatabase holds no open connection (per-operation sqlite
            # connects), so dropping the reference is enough for it.
            raise

        old_chat, old_studio = self.chat_bridge, self.studio_bridge
        self._bootstrap.detach_chat_bridge()
        self.database = new_database
        self.chat_bridge = new_chat
        self.studio_bridge = new_studio
        self.settings = target_settings
        new_studio.conversationRestored.connect(new_chat.refresh)
        new_chat.conversationArchived.connect(
            lambda _conversation_id: new_studio.refreshArchived("")
        )
        if self._frontend is not None:
            self._frontend.update_settings(target_settings)
        if self._engine is not None:
            self._engine.rootContext().setContextProperty("chat", new_chat)
            self._engine.rootContext().setContextProperty("studio", new_studio)
            self._engine._chat_bridge = new_chat  # type: ignore[attr-defined]
            self._engine._studio_bridge = new_studio  # type: ignore[attr-defined]
        self._bootstrap.attach_chat_bridge(new_chat)
        # Previous backend goes away only after the new one is fully live.
        _safe_close(old_studio)
        _safe_close(old_chat)

    def setup_backend(self, target_settings: MarySettings) -> None:
        """Build database + bridges and publish them only on full success.

        Synchronous UI-thread path kept for deterministic captures, smoke
        tests and unit tests. Production startup uses the async worker
        below so the loading page never freezes during ``initialize``.
        """
        new_database = self._prepare_workspace(target_settings)
        self._publish_backend(target_settings, new_database)

    # ------------------------------------------------------------------
    # Normal startup / retry / setup continuations
    # ------------------------------------------------------------------

    def _schedule_restore(self) -> None:
        if self._on_backend_started is not None and self.studio_bridge is not None:
            try:
                self._on_backend_started(self.studio_bridge)
            except Exception:
                pass

    def is_preparing(self) -> bool:
        """True while a workspace prepare worker is in flight."""
        thread = self._prepare_thread
        return thread is not None and thread.is_alive()

    def shutdown(self) -> None:
        """Invalidate in-flight workers so late results are never published."""
        self._shutdown = True
        self._prepare_generation += 1
        self._disconnect_frame()
        self._pending_frame_actions.clear()
        self._pending_setup_settings = None

    def _start_prepare(self, target_settings: MarySettings, *, is_setup: bool) -> bool:
        """Start the worker preparing the workspace. Returns False if busy.

        Only one worker runs at a time: a fast retry while a prepare is in
        flight is ignored instead of spawning a second worker. The heavy
        ``initialize_workspace`` runs off the UI thread; bridge creation
        and the atomic publish happen later in the UI-thread slots.
        """
        if self._shutdown or self.is_preparing():
            return False
        self._prepare_generation += 1
        generation = self._prepare_generation
        self._prepare_is_setup = is_setup
        if is_setup:
            self._pending_setup_settings = target_settings

        def _load() -> None:
            # Never run cyclic GC on this worker: collecting here could
            # finalize main-thread QObjects (bridge signal/slot cycles keep
            # them alive past refcount zero) from the wrong thread, which
            # corrupts the heap. Collection resumes on the UI thread, where
            # teardown is safe. The flag is process-wide but the prepare is
            # short-lived, so the pause is harmless.
            gc.disable()
            try:
                try:
                    database = self._prepare_workspace(target_settings)
                except Exception as exc:  # noqa: BLE001 - forwarded to UI slot
                    try:
                        self._prepareFailed.emit(generation, exc)
                    except RuntimeError:
                        pass
                    return
                try:
                    self._prepareReady.emit(generation, database)
                except RuntimeError:
                    pass
            finally:
                gc.enable()

        thread = threading.Thread(target=_load, daemon=True)
        self._prepare_thread = thread
        thread.start()
        return True

    def _drop_stale_prepare(self, generation: int) -> bool:
        """True when a worker result must be ignored (stale or shutdown)."""
        return (
            self._shutdown or generation != self._prepare_generation
        )

    @Slot(int, object)
    def _on_prepare_ready(self, generation: int, database: object) -> None:
        self._prepare_thread = None
        if self._drop_stale_prepare(generation):
            return
        target = self.settings if not self._prepare_is_setup else (
            self._pending_setup_settings or self.settings
        )
        is_setup = self._prepare_is_setup
        self._prepare_is_setup = False
        try:
            self._publish_backend(target, database)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - mapped to bootstrap state
            if is_setup:
                self._pending_setup_settings = None
                self._bootstrap.setupInitializationFailed(
                    f"Não foi possível inicializar o ambiente: {exc}"
                )
            else:
                self._bootstrap.set_error(
                    f"Não foi possível inicializar o ambiente: {exc}"
                )
            return
        # A genuinely new backend was published: continue the flow and
        # schedule the Antigravity restore exactly once for it.
        if is_setup:
            self._pending_setup_settings = None
            self._bootstrap.setupInitializationSucceeded(target)
            self._bootstrap.start_bootstrap()
            self._schedule_restore()
        else:
            self._bootstrap.start_bootstrap()
            self._schedule_restore()

    @Slot(int, object)
    def _on_prepare_failed(self, generation: int, error: object) -> None:
        self._prepare_thread = None
        if self._drop_stale_prepare(generation):
            return
        is_setup = self._prepare_is_setup
        self._prepare_is_setup = False
        if is_setup:
            self._pending_setup_settings = None
            self._bootstrap.setupInitializationFailed(
                f"Não foi possível inicializar o ambiente: {error}"
            )
        else:
            self._bootstrap.set_error(
                f"Não foi possível inicializar o ambiente: {error}"
            )

    def bootstrap_or_retry(self) -> None:
        """Retry path: async rebuild of a missing backend, else catalog only.

        When the backend is already valid only the catalog reloads (fast,
        synchronous dispatch into ChatBridge's own worker) and the
        Antigravity restore is NOT repeated. When the backend is missing,
        a single prepare worker starts and the publish/catalog/restore
        continue on the UI thread once it finishes.
        """
        if self._shutdown:
            return
        if self.is_backend_ready():
            self._bootstrap.start_bootstrap()
            return
        self._start_prepare(self.settings, is_setup=False)

    def _run_setup_backend(self, new_settings: MarySettings) -> None:
        """Start the setup prepare after the loading frame was presented."""
        if self._shutdown:
            return
        self._start_prepare(new_settings, is_setup=True)

    def request_setup_backend(
        self, new_settings: MarySettings, window: Any = None
    ) -> None:
        """Handle BootstrapBridge.setupInitializationRequested (async).

        Only arms the deferred backend run; returns to the event loop so the
        loading page paints its first frame before initialize_workspace().
        """
        self._pending_setup_settings = new_settings
        self._arm_first_frame(
            lambda: self._run_setup_backend(new_settings), window or self._window
        )

    def request_normal_startup(self, window: Any = None) -> None:
        """Arm the deferred normal startup after the first loading frame."""
        self._arm_first_frame(self.bootstrap_or_retry, window or self._window)

    # ------------------------------------------------------------------
    # First-frame gate
    # ------------------------------------------------------------------

    def _arm_first_frame(
        self, action: Callable[[], None], window: Any = None
    ) -> None:
        self._pending_frame_actions.append(action)
        if self._frame_connected:
            return
        signal = getattr(window, "frameSwapped", None) if window is not None else None
        if signal is None:
            # Headless/tests without a real scene graph: still deferred to
            # the event loop, never synchronous with the caller.
            QTimer.singleShot(0, self._drain_frame_actions)
            return
        try:
            signal.connect(
                self._on_first_frame,
                Qt.ConnectionType.QueuedConnection,
            )
        except (RuntimeError, TypeError):
            QTimer.singleShot(0, self._drain_frame_actions)
            return
        self._frame_connected = True
        self._frame_signal = signal

    def _disconnect_frame(self) -> None:
        """Detach the one-shot frameSwapped handler, tolerating teardown."""
        if not self._frame_connected:
            self._frame_signal = None
            return
        self._frame_connected = False
        signal = self._frame_signal
        self._frame_signal = None
        if signal is None:
            return
        try:
            signal.disconnect(self._on_first_frame)
        except (RuntimeError, TypeError):
            pass

    @Slot()
    def _on_first_frame(self) -> None:
        """Run pending backend work once, after a real frame was swapped.

        Truly one-shot: the handler disconnects from frameSwapped before
        draining, so animated windows never keep invoking this Python slot
        at ~60 FPS and re-arming never stacks connections. Already-queued
        duplicate invocations find no pending actions and are no-ops.
        """
        self._disconnect_frame()
        self._drain_frame_actions()

    def _drain_frame_actions(self) -> None:
        actions, self._pending_frame_actions = self._pending_frame_actions, []
        for action in actions:
            action()

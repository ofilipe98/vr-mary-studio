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
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Slot

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

    def setup_backend(self, target_settings: MarySettings) -> None:
        """Build database + bridges and publish them only on full success.

        Raises the original exception on failure after closing any partially
        created new bridges. Previously published references are left
        untouched so an existing usable backend survives a failed rebuild.
        """
        new_database = self._init_workspace(
            target_settings, refresh_conversations=False
        )
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

    # ------------------------------------------------------------------
    # Normal startup / retry / setup continuations
    # ------------------------------------------------------------------

    def _schedule_restore(self) -> None:
        if self._on_backend_started is not None and self.studio_bridge is not None:
            try:
                self._on_backend_started(self.studio_bridge)
            except Exception:
                pass

    def bootstrap_or_retry(self) -> None:
        """Retry path: rebuild a missing backend, else reload catalog only."""
        if not self.is_backend_ready():
            try:
                self.setup_backend(self.settings)
            except Exception as exc:
                self._bootstrap.set_error(
                    f"Não foi possível inicializar o ambiente: {exc}"
                )
                return
        self._bootstrap.start_bootstrap()
        self._schedule_restore()

    def _run_setup_backend(self, new_settings: MarySettings) -> None:
        """Finish a setup request after the loading frame was presented."""
        try:
            self.setup_backend(new_settings)
        except Exception as exc:
            self._bootstrap.setupInitializationFailed(
                f"Não foi possível inicializar o ambiente: {exc}"
            )
            return
        self._bootstrap.setupInitializationSucceeded(new_settings)
        self._bootstrap.start_bootstrap()
        self._schedule_restore()

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

    @Slot()
    def _on_first_frame(self) -> None:
        """Run pending backend work once, after a real frame was swapped."""
        self._frame_connected = False
        self._drain_frame_actions()

    def _drain_frame_actions(self) -> None:
        actions, self._pending_frame_actions = self._pending_frame_actions, []
        for action in actions:
            action()

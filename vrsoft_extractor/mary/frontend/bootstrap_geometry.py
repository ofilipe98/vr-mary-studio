"""Compact bootstrap window geometry for setup/loading states.

During bootstrap (setup, initializing, loading_apps, loading_versions and
startup errors) the VRStudio window uses a small centered envelope
(``BOOTSTRAP_WIDTH`` x ``BOOTSTRAP_HEIGHT`` logical pixels) instead of the
full Studio size. Once the bootstrap reaches ``ready``, the previously
captured normal geometry (size, position and maximized state) is restored.

Rules:

* The compact geometry is never persisted as the user's normal preference:
  this controller keeps the captured normal geometry in memory only and
  writes nothing to ``QSettings``.
* Centering uses the window's current screen ``availableGeometry`` (DPI
  aware logical pixels, multi-monitor capable) and the result is clamped so
  the window is never placed outside the visible area.
* Small screens shrink the envelope instead of overflowing it.
* Setup, loading and error states share the same envelope.
* Normal-size contract: ``Main.qml`` declares its initial ``width``/``height``
  as bindings proportional to the screen. Setting an explicit size from
  Python (``setProperty``) intentionally replaces those one-time initial
  bindings — the same happens on any manual user resize. This controller
  therefore owns the normal geometry explicitly: it captures the pre-
  bootstrap size/position/visibility, applies the compact envelope, and
  restores the captured values on ``ready``. After ``ready`` the window
  keeps an explicit size (fully resizable by the user, movable across
  monitors) instead of re-evaluating the startup-proportional expression.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Slot

BOOTSTRAP_WIDTH = 760
BOOTSTRAP_HEIGHT = 560

#: States that keep the compact bootstrap envelope.
BOOTSTRAP_GEOMETRY_STATES = frozenset(
    {"setup", "initializing", "loading_apps", "loading_versions", "error"}
)


def is_bootstrap_geometry_state(state: str) -> bool:
    """True when the bootstrap state uses the compact window envelope."""
    return str(state or "") in BOOTSTRAP_GEOMETRY_STATES


def compute_bootstrap_rect(
    available_x: float,
    available_y: float,
    available_width: float,
    available_height: float,
    *,
    width: float = BOOTSTRAP_WIDTH,
    height: float = BOOTSTRAP_HEIGHT,
) -> tuple[int, int, int, int]:
    """Center the bootstrap envelope inside the available screen area.

    Returns ``(x, y, width, height)`` as integer logical pixels, clamped so
    the window always stays fully visible, even on small screens. The
    result never exceeds the available area, including areas smaller than
    the logical 320px minimum (the envelope shrinks below the minimum
    instead of overflowing).
    """
    try:
        avail_w = max(0.0, float(available_width))
    except (TypeError, ValueError):
        avail_w = 0.0
    try:
        avail_h = max(0.0, float(available_height))
    except (TypeError, ValueError):
        avail_h = 0.0
    if avail_w:
        # Leave 32px breathing room when the screen allows it, but never
        # exceed the available width — tiny screens use the full area.
        room_w = avail_w - 32.0
        if room_w < 1.0:
            room_w = avail_w
        target_w = min(float(width), room_w, avail_w)
        target_w = max(1, int(target_w))
        target_w = min(target_w, int(avail_w))
    else:
        target_w = max(1, int(float(width)))
    if avail_h:
        room_h = avail_h - 32.0
        if room_h < 1.0:
            room_h = avail_h
        target_h = min(float(height), room_h, avail_h)
        target_h = max(1, int(target_h))
        target_h = min(target_h, int(avail_h))
    else:
        target_h = max(1, int(float(height)))
    if avail_w:
        pos_x = int(available_x + max(0.0, (avail_w - target_w) / 2.0))
        pos_x = max(int(available_x), min(pos_x, int(available_x + avail_w - target_w)))
    else:
        pos_x = int(available_x)
    if avail_h:
        pos_y = int(available_y + max(0.0, (avail_h - target_h) / 2.0))
        pos_y = max(int(available_y), min(pos_y, int(available_y + avail_h - target_h)))
    else:
        pos_y = int(available_y)
    return pos_x, pos_y, target_w, target_h


def _window_visibility(window: Any) -> int:
    try:
        value = window.property("visibility")
    except (RuntimeError, AttributeError):
        return 2
    try:
        return int(value)
    except (TypeError, ValueError):
        return 2


class BootstrapGeometryController(QObject):
    """Apply the compact envelope during bootstrap, restore afterwards.

    The normal geometry is captured on the first transition into a
    bootstrap state and restored exactly once when ``ready`` arrives. An
    in-app refresh never re-enters the compact envelope because the
    bootstrap bridge ignores catalog phases once ready.
    """

    def __init__(
        self,
        window: Any,
        bootstrap: Any,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._bootstrap = bootstrap
        self._compact_active = False
        self._normal: dict[str, Any] | None = None
        try:
            state_changed = getattr(bootstrap, "stateChanged", None)
            if state_changed is not None:
                state_changed.connect(
                    self._apply_for_state,
                )
        except (RuntimeError, TypeError):
            pass
        self._apply_for_state()

    @property
    def compact_active(self) -> bool:
        return self._compact_active

    def _available_geometry(self) -> tuple[float, float, float, float] | None:
        window = self._window
        if window is None:
            return None
        screen = None
        try:
            screen_fn = getattr(window, "screen", None)
            if callable(screen_fn):
                screen = screen_fn()
        except (RuntimeError, AttributeError):
            screen = None
        if screen is None:
            try:
                from PySide6.QtGui import QGuiApplication

                screen = QGuiApplication.primaryScreen()
            except Exception:
                screen = None
        if screen is None:
            return None
        try:
            geometry = screen.availableGeometry()
        except (RuntimeError, AttributeError):
            return None
        try:
            return (
                float(geometry.x()),
                float(geometry.y()),
                float(geometry.width()),
                float(geometry.height()),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    def _capture_normal(self) -> None:
        window = self._window
        if window is None or self._normal is not None:
            return
        try:
            self._normal = {
                "width": window.property("width"),
                "height": window.property("height"),
                "x": window.property("x"),
                "y": window.property("y"),
                "visibility": _window_visibility(window),
            }
        except (RuntimeError, AttributeError):
            self._normal = None

    def enterBootstrapGeometry(self) -> None:  # noqa: N802
        """Switch to the compact centered envelope (idempotent)."""
        window = self._window
        if window is None or self._compact_active:
            return
        self._capture_normal()
        visibility = _window_visibility(window)
        # 4 == Window.Maximized, 5 == Window.FullScreen: both must leave the
        # special state via showNormal() before the compact envelope applies.
        # Restore distinguishes them (showMaximized vs showFullScreen).
        was_special = visibility in (4, 5)
        if was_special:
            try:
                show_normal = getattr(window, "showNormal", None)
                if callable(show_normal):
                    show_normal()
            except (RuntimeError, AttributeError):
                pass
        available = self._available_geometry()
        if available is None:
            pos_x, pos_y, target_w, target_h = 0, 0, BOOTSTRAP_WIDTH, BOOTSTRAP_HEIGHT
            try:
                window.setProperty("width", target_w)
                window.setProperty("height", target_h)
            except (RuntimeError, AttributeError):
                return
            self._compact_active = True
            return
        pos_x, pos_y, target_w, target_h = compute_bootstrap_rect(*available)
        try:
            window.setProperty("width", target_w)
            window.setProperty("height", target_h)
            window.setProperty("x", pos_x)
            window.setProperty("y", pos_y)
        except (RuntimeError, AttributeError):
            return
        self._compact_active = True

    def restoreMainGeometry(self) -> None:  # noqa: N802
        """Restore the captured normal geometry (idempotent)."""
        window = self._window
        if window is None or not self._compact_active:
            return
        self._compact_active = False
        normal = self._normal
        self._normal = None
        if not normal:
            return
        try:
            if normal.get("width") is not None:
                window.setProperty("width", normal["width"])
            if normal.get("height") is not None:
                window.setProperty("height", normal["height"])
            if normal.get("x") is not None:
                window.setProperty("x", normal["x"])
            if normal.get("y") is not None:
                window.setProperty("y", normal["y"])
        except (RuntimeError, AttributeError):
            return
        # QWindow visibility: 4 == Maximized, 5 == FullScreen. A fullscreen
        # window must return via showFullScreen(), never showMaximized().
        visibility = normal.get("visibility")
        if visibility == 5:
            try:
                show_fullscreen = getattr(window, "showFullScreen", None)
                if callable(show_fullscreen):
                    show_fullscreen()
                    return
                window.setProperty("visibility", visibility)
            except (RuntimeError, AttributeError):
                pass
        elif visibility == 4:
            try:
                show_maximized = getattr(window, "showMaximized", None)
                if callable(show_maximized):
                    show_maximized()
                    return
                window.setProperty("visibility", visibility)
            except (RuntimeError, AttributeError):
                pass

    @Slot()
    def _apply_for_state(self) -> None:
        if self._window is None or self._bootstrap is None:
            return
        try:
            raw = getattr(self._bootstrap, "state", "")
            state = str(raw() if callable(raw) else raw)
        except (RuntimeError, AttributeError, TypeError):
            return
        if state == "ready":
            self.restoreMainGeometry()
        elif is_bootstrap_geometry_state(state):
            self.enterBootstrapGeometry()

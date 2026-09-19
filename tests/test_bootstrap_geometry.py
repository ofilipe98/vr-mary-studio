"""Unit tests for the compact bootstrap window geometry.

The calculation/state logic is tested without a window manager: fake
windows and screens drive BootstrapGeometryController, so these tests stay
deterministic on headless CI. Real placement is validated manually.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.frontend.bootstrap_geometry import (
    BOOTSTRAP_HEIGHT,
    BOOTSTRAP_WIDTH,
    BootstrapGeometryController,
    compute_bootstrap_rect,
    is_bootstrap_geometry_state,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeScreen:
    def __init__(self, rect: QRect) -> None:
        self._rect = rect

    def availableGeometry(self) -> QRect:
        return self._rect


class FakeWindow:
    """Duck-typed window: properties, screen and show helpers."""

    def __init__(
        self,
        width=1480,
        height=900,
        x=100,
        y=80,
        visibility=2,
        screen=None,
    ) -> None:
        self._props = {
            "width": width,
            "height": height,
            "x": x,
            "y": y,
            "visibility": visibility,
        }
        self._screen = screen
        self.show_normal_calls = 0
        self.show_maximized_calls = 0
        self.show_fullscreen_calls = 0

    def property(self, name: str):
        return self._props.get(name)

    def setProperty(self, name: str, value) -> bool:
        self._props[name] = value
        return True

    def screen(self):
        return self._screen

    def showNormal(self) -> None:
        self.show_normal_calls += 1
        self._props["visibility"] = 2

    def showMaximized(self) -> None:
        self.show_maximized_calls += 1
        self._props["visibility"] = 4

    def showFullScreen(self) -> None:
        self.show_fullscreen_calls += 1
        self._props["visibility"] = 5


class FakeBootstrap(QObject):
    stateChanged = Signal()

    def __init__(self, state: str) -> None:
        super().__init__()
        self._state = state

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        self._state = state
        self.stateChanged.emit()


def test_bootstrap_geometry_states() -> None:
    for state in ("setup", "initializing", "loading_apps", "loading_versions", "error"):
        assert is_bootstrap_geometry_state(state) is True
    assert is_bootstrap_geometry_state("ready") is False
    assert is_bootstrap_geometry_state("") is False


def test_compute_bootstrap_rect_centers_on_primary_screen() -> None:
    assert compute_bootstrap_rect(0, 0, 1920, 1080) == (580, 260, 760, 560)


def test_compute_bootstrap_rect_respects_screen_offset() -> None:
    # Second monitor starting at x=1920: the compact window stays on it.
    assert compute_bootstrap_rect(1920, 0, 1920, 1080) == (2500, 260, 760, 560)


def test_compute_bootstrap_rect_shrinks_on_small_screens() -> None:
    x, y, width, height = compute_bootstrap_rect(0, 0, 400, 400)
    assert width <= 400 and height <= 400
    assert x >= 0 and y >= 0
    assert x + width <= 400 and y + height <= 400


def test_setup_state_applies_compact_geometry(qapp) -> None:
    window = FakeWindow(screen=FakeScreen(QRect(0, 0, 1920, 1080)))
    bootstrap = FakeBootstrap("setup")
    controller = BootstrapGeometryController(window, bootstrap)
    assert controller.compact_active is True
    assert window.property("width") == BOOTSTRAP_WIDTH
    assert window.property("height") == BOOTSTRAP_HEIGHT
    assert window.property("x") == 580
    assert window.property("y") == 260


def test_loading_and_error_keep_compact_envelope(qapp) -> None:
    window = FakeWindow(screen=FakeScreen(QRect(0, 0, 1920, 1080)))
    bootstrap = FakeBootstrap("setup")
    controller = BootstrapGeometryController(window, bootstrap)
    assert controller.compact_active is True
    for state in ("initializing", "loading_apps", "loading_versions", "error"):
        bootstrap.set_state(state)
        QApplication.processEvents()
        assert controller.compact_active is True
        assert window.property("width") == BOOTSTRAP_WIDTH
        assert window.property("height") == BOOTSTRAP_HEIGHT


def test_ready_restores_normal_geometry(qapp) -> None:
    window = FakeWindow(
        width=1480, height=900, x=100, y=80, screen=FakeScreen(QRect(0, 0, 1920, 1080))
    )
    bootstrap = FakeBootstrap("loading_versions")
    controller = BootstrapGeometryController(window, bootstrap)
    assert controller.compact_active is True

    bootstrap.set_state("ready")
    QApplication.processEvents()
    assert controller.compact_active is False
    assert window.property("width") == 1480
    assert window.property("height") == 900
    assert window.property("x") == 100
    assert window.property("y") == 80


def test_maximized_normal_geometry_is_restored(qapp) -> None:
    window = FakeWindow(
        width=1920,
        height=1040,
        visibility=4,
        screen=FakeScreen(QRect(0, 0, 1920, 1080)),
    )
    bootstrap = FakeBootstrap("initializing")
    controller = BootstrapGeometryController(window, bootstrap)
    assert controller.compact_active is True
    assert window.show_normal_calls == 1

    bootstrap.set_state("ready")
    QApplication.processEvents()
    assert controller.compact_active is False
    assert window.show_maximized_calls == 1
    assert window.show_fullscreen_calls == 0


def test_fullscreen_normal_geometry_is_restored_as_fullscreen(qapp) -> None:
    """Window.FullScreen (5) must return via showFullScreen, not maximized."""
    window = FakeWindow(
        width=1920,
        height=1080,
        visibility=5,
        screen=FakeScreen(QRect(0, 0, 1920, 1080)),
    )
    bootstrap = FakeBootstrap("initializing")
    controller = BootstrapGeometryController(window, bootstrap)
    assert controller.compact_active is True
    assert window.show_normal_calls == 1

    bootstrap.set_state("ready")
    QApplication.processEvents()
    assert controller.compact_active is False
    assert window.show_fullscreen_calls == 1
    assert window.show_maximized_calls == 0


def test_compute_bootstrap_rect_never_exceeds_tiny_area() -> None:
    """Areas smaller than the logical minimum still fully contain the window."""
    for avail_w, avail_h in ((200, 150), (240, 200), (100, 100), (33, 33)):
        x, y, width, height = compute_bootstrap_rect(0, 0, avail_w, avail_h)
        assert width <= avail_w, (avail_w, avail_h, width)
        assert height <= avail_h, (avail_w, avail_h, height)
        assert x >= 0 and y >= 0
        assert x + width <= avail_w
        assert y + height <= avail_h


def test_normal_window_stays_resizable_after_ready(qapp) -> None:
    """Explicit Python geometry keeps the normal window contract after ready.

    Main.qml declares its initial size as screen-proportional bindings; the
    controller intentionally takes explicit ownership during bootstrap (as a
    manual resize would). After ready the window must stay resizable,
    movable across monitors and free from recompaction.
    """
    window = FakeWindow(
        width=1480, height=900, x=100, y=80, screen=FakeScreen(QRect(0, 0, 1920, 1080))
    )
    bootstrap = FakeBootstrap("loading_versions")
    controller = BootstrapGeometryController(window, bootstrap)
    assert controller.compact_active is True

    bootstrap.set_state("ready")
    QApplication.processEvents()
    assert controller.compact_active is False
    assert window.property("width") == 1480
    assert window.property("height") == 900

    # Manual resize after ready keeps working and never recompacts.
    window.setProperty("width", 1200)
    window.setProperty("height", 800)
    assert window.property("width") == 1200
    assert window.property("height") == 800
    bootstrap.set_state("ready")
    QApplication.processEvents()
    assert controller.compact_active is False
    assert window.property("width") == 1200
    assert window.property("height") == 800


def test_ready_without_bootstrap_never_recompacts(qapp) -> None:
    """An in-app refresh after ready must not return to the compact window."""
    window = FakeWindow(screen=FakeScreen(QRect(0, 0, 1920, 1080)))
    bootstrap = FakeBootstrap("ready")
    controller = BootstrapGeometryController(window, bootstrap)
    assert controller.compact_active is False
    assert window.property("width") == 1480
    # Catalog refreshes emit stateChanged with ready: still no compacting.
    bootstrap.set_state("ready")
    QApplication.processEvents()
    assert controller.compact_active is False
    assert window.property("width") == 1480

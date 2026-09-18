"""Regression: UI scale migration must preserve custom interface font family.

Covers P0 spec: Arial+14 v2 -> Arial+16 v3 (not Segoe UI).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _settings(root: Path) -> MarySettings:
    return MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy")


def _migrate(*, family, size, scale="auto", version=2):
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        prefs = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
        if family is not None:
            prefs.setValue("appearance/interface_font_family", family)
        if size is not None:
            prefs.setValue("appearance/interface_font_size", size)
        prefs.setValue("appearance/ui_scale", scale)
        prefs.setValue("appearance/ui_scale_version", version)
        prefs.sync()
        bridge = FrontendBridge(_settings(root), prefs)
        return (
            bridge.interfaceFontFamily,
            bridge.interfaceFontSize,
            prefs.value("appearance/interface_font_family"),
            prefs.value("appearance/interface_font_size"),
            int(prefs.value("appearance/ui_scale_version")),
            bridge.uiScale,
        )


def test_arial_14_preserves_family_and_bumps_to_16(qt_app):
    family, size, stored_family, stored_size, version, _scale = _migrate(
        family="Arial", size=14
    )
    assert family == "Arial"
    assert size == 16
    assert stored_family == "Arial"
    assert int(stored_size) == 16
    assert version == FrontendBridge.UI_SCALE_PREFERENCE_VERSION


@pytest.mark.parametrize("family", ["Segoe UI", "Arial", "Inter"])
def test_legacy_14_preserves_each_family(qt_app, family):
    got_family, got_size, _, _, _, _ = _migrate(family=family, size=14)
    assert got_family == family
    assert got_size == 16


def test_string_14_preserves_family(qt_app):
    got_family, got_size, _, _, _, _ = _migrate(family="Arial", size="14")
    assert got_family == "Arial"
    assert got_size == 16


def test_custom_size_is_preserved(qt_app):
    got_family, got_size, _, _, _, _ = _migrate(family="Arial", size=18)
    assert got_family == "Arial"
    assert got_size == 18


def test_missing_size_defaults_to_16_segoe(qt_app):
    got_family, got_size, _, _, _, _ = _migrate(family=None, size=None)
    assert got_family == "Segoe UI"
    assert got_size == 16


def test_valid_manual_scale_migrates_without_corrupting_typography(qt_app):
    got_family, got_size, _, _, version, scale = _migrate(
        family="Arial", size=14, scale="125", version=2
    )
    assert got_family == "Arial"
    assert got_size == 16
    assert version == FrontendBridge.UI_SCALE_PREFERENCE_VERSION
    # Current policy resets legacy scale entries to auto on version bump.
    assert scale == "auto"

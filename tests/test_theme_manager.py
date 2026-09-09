"""Tests for the Appearance and Theme Management engine."""

from pathlib import Path
import json
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication

from vrsoft_extractor.mary.theme_manager import (
    ThemeManager,
    BUILTIN_THEMES,
    parse_imported_theme,
    _is_valid_hex,
)


def _create_manager(tmp_path: Path) -> ThemeManager:
    _app = QGuiApplication.instance() or QGuiApplication([])
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    return ThemeManager(settings)


def test_builtin_themes_exist_and_are_valid():
    assert "dark_orange" in BUILTIN_THEMES
    assert "light" in BUILTIN_THEMES
    assert "nightfall" in BUILTIN_THEMES
    assert "slate_zinc" in BUILTIN_THEMES
    assert "github_dark" in BUILTIN_THEMES
    assert "sepia_solar" in BUILTIN_THEMES

    for theme_id, t in BUILTIN_THEMES.items():
        assert t.id == theme_id
        assert t.appearance in ("light", "dark")
        assert len(t.palette) > 10
        assert _is_valid_hex(t.palette["background"])
        assert _is_valid_hex(t.palette["text"])


def test_theme_manager_defaults():
    with TemporaryDirectory() as tmp:
        mgr = _create_manager(Path(tmp))
        assert mgr.appearanceMode in ("system", "light", "dark")
        assert mgr.themeLight == "light"
        assert mgr.themeDark == "dark_orange"
        assert mgr.appearanceContrast == 100
        assert mgr.glassOpacity == 80
        assert mgr.panelAnimationDurationMs == 0
        assert mgr.typographyAdvanced is False
        assert mgr.wordWrap is True


def test_independent_theme_and_mode_switching():
    with TemporaryDirectory() as tmp:
        mgr = _create_manager(Path(tmp))

        # Force Light mode
        mgr.setAppearanceMode("light")
        assert mgr.appearanceMode == "light"
        assert mgr.resolvedAppearance == "light"
        assert mgr.activeThemeId == "light"

        # Change light theme to sepia
        mgr.setThemeForAppearance("light", "sepia_solar")
        assert mgr.themeLight == "sepia_solar"
        assert mgr.activeThemeId == "sepia_solar"

        # Force Dark mode
        mgr.setAppearanceMode("dark")
        assert mgr.appearanceMode == "dark"
        assert mgr.resolvedAppearance == "dark"
        assert mgr.activeThemeId == "dark_orange"

        # Change dark theme to nightfall
        mgr.setThemeForAppearance("dark", "nightfall")
        assert mgr.themeDark == "nightfall"
        assert mgr.activeThemeId == "nightfall"

        # Switch back to light: sepia is still remembered!
        mgr.setAppearanceMode("light")
        assert mgr.activeThemeId == "sepia_solar"


def test_contrast_and_glass_opacity():
    with TemporaryDirectory() as tmp:
        mgr = _create_manager(Path(tmp))

        mgr.setAppearanceContrast(150)
        assert mgr.appearanceContrast == 150
        palette = mgr.palette
        assert "background" in palette

        mgr.resetSetting("contrast")
        assert mgr.appearanceContrast == 100

        mgr.setGlassOpacity(60)
        assert mgr.glassOpacity == 60
        mgr.resetSetting("glass")
        assert mgr.glassOpacity == 80


def test_panel_animations_and_reduce_motion():
    with TemporaryDirectory() as tmp:
        mgr = _create_manager(Path(tmp))

        mgr.setPanelAnimationDurationMs(200)
        assert mgr.panelAnimationDurationMs == 200
        assert mgr.rawPanelAnimationDurationMs == 200

        # When reduce motion is active, duration is forced to 0
        mgr.setReduceMotion(True)
        assert mgr.panelAnimationDurationMs == 0
        assert mgr.rawPanelAnimationDurationMs == 200

        mgr.setReduceMotion(False)
        assert mgr.panelAnimationDurationMs == 200


def test_typography_settings_and_reset():
    with TemporaryDirectory() as tmp:
        mgr = _create_manager(Path(tmp))

        mgr.setInterfaceTypography("Arial", 16)
        assert mgr.interfaceFontFamily == "Arial"
        assert mgr.interfaceFontSize == 16

        mgr.setCodeTypography("Cascadia Code", 14)
        assert mgr.codeFontFamily == "Cascadia Code"
        assert mgr.codeFontSize == 14

        mgr.setPromptTypography("Consolas", 15)
        assert mgr.promptFontFamily == "Consolas"
        assert mgr.promptFontSize == 15

        mgr.resetSetting("interfaceFont")
        assert mgr.interfaceFontFamily == "Segoe UI"
        assert mgr.interfaceFontSize == 14


def test_custom_themes_crud_and_fallback():
    with TemporaryDirectory() as tmp:
        mgr = _create_manager(Path(tmp))

        # Create custom theme
        new_id = mgr.createCustomTheme("Custom Blue", "dark", "nightfall")
        assert new_id
        theme_names = [t["name"] for t in mgr.availableThemes]
        assert "Custom Blue" in theme_names

        # Use it as dark theme
        mgr.setThemeForAppearance("dark", new_id)
        assert mgr.themeDark == new_id

        # Duplicate it
        dup_id = mgr.duplicateTheme(new_id, "Custom Blue 2")
        assert dup_id
        assert dup_id != new_id

        # Export it
        json_str = mgr.exportThemeJson(new_id)
        assert "Custom Blue" in json_str

        # Delete it: fallback must safely revert themeDark to dark_orange!
        deleted = mgr.deleteCustomTheme(new_id)
        assert deleted is True
        assert mgr.themeDark == "dark_orange"


def test_defensive_theme_import_native():
    sample = {
        "version": 1,
        "name": "Super Retro",
        "appearance": "dark",
        "palette": {
            "background": "#050505",
            "surface": "#121212",
            "text": "#eeeeee",
            "brandOrange": "#ff5500",
        },
    }
    success, msg, theme = parse_imported_theme(json.dumps(sample))
    assert success is True
    assert theme is not None
    assert theme.name == "Super Retro"
    assert theme.appearance == "dark"
    assert theme.palette["background"] == "#050505"


def test_defensive_theme_import_t3_code():
    t3_sample = {
        "name": "T3 Tokyo Night",
        "canvas": "#1a1b26",
        "accent": "#7aa2f7",
        "colors": {
            "error": "#f7768e",
        },
    }
    success, msg, theme = parse_imported_theme(json.dumps(t3_sample))
    assert success is True
    assert theme is not None
    assert theme.name == "T3 Tokyo Night"
    assert theme.appearance == "dark"
    assert theme.palette["danger"] == "#f7768e"


def test_defensive_theme_import_vscode():
    vscode_sample = {
        "name": "Monokai Theme",
        "type": "dark",
        "colors": {
            "editor.background": "#272822",
            "editor.foreground": "#f8f8f2",
            "activityBarBadge.background": "#a6e22e",
        },
    }
    success, msg, theme = parse_imported_theme(json.dumps(vscode_sample))
    assert success is True
    assert theme is not None
    assert theme.name == "Monokai Theme"
    assert theme.appearance == "dark"
    assert theme.palette["background"] == "#272822"


def test_defensive_theme_import_malformed_and_invalid():
    # Invalid JSON
    success, msg, theme = parse_imported_theme("{ bad json")
    assert success is False
    assert "JSON inválido" in msg

    # Missing required keys
    success, msg, theme = parse_imported_theme(json.dumps({"foo": "bar"}))
    assert success is False
    assert "não reconhecido" in msg

    # Invalid hex colors in T3 format
    success, msg, theme = parse_imported_theme(json.dumps({"canvas": "not-a-color", "accent": "#123"}))
    assert success is False

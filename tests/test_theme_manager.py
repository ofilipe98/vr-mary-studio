"""Tests for the Appearance and Theme Management engine."""

from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication

from vrsoft_extractor.mary.theme_manager import (
    ThemeManager,
    BUILTIN_THEMES,
    DEFAULT_TEXT_RENDERING,
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
        assert mgr.environmentIdentification == "artwork"


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

        mgr.setEnvironmentIdentification("artwork")
        assert mgr.environmentIdentification == "artwork"
        mgr.resetSetting("environment")
        assert mgr.environmentIdentification == "artwork"


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

        mgr.setInterfaceTypography("Arial", 18)
        assert mgr.interfaceFontFamily == "Arial"
        assert mgr.interfaceFontSize == 18

        mgr.setCodeTypography("Cascadia Code", 14)
        assert mgr.codeFontFamily == "Cascadia Code"
        assert mgr.codeFontSize == 14

        mgr.setTypographyAdvanced(True)
        mgr.setPromptTypography("Consolas", 15)
        assert mgr.promptFontFamily == "Consolas"
        assert mgr.promptFontSize == 15

        mgr.resetSetting("interfaceFont")
        assert mgr.interfaceFontFamily == "Segoe UI"
        assert mgr.interfaceFontSize == 16


def test_simple_typography_inherits_and_advanced_restores_preferences(tmp_path):
    mgr = _create_manager(tmp_path)
    mgr.setInterfaceTypography("Arial", 16)
    mgr.setCodeTypography("Consolas", 15)
    mgr.setPromptTypography("Courier New", 18)
    mgr.setTerminalTypography("Courier New", 17)
    assert (mgr.promptFontFamily, mgr.promptFontSize) == ("Arial", 16)
    assert (mgr.terminalFontFamily, mgr.terminalFontSize) == ("Consolas", 15)
    mgr.setTypographyAdvanced(True)
    assert (mgr.promptFontFamily, mgr.promptFontSize) == ("Courier New", 18)
    assert (mgr.terminalFontFamily, mgr.terminalFontSize) == ("Courier New", 17)
    mgr.setTypographyAdvanced(False)
    restored = _create_manager(tmp_path)
    assert (restored.terminalFontFamily, restored.terminalFontSize) == ("Consolas", 15)
    restored.setTypographyAdvanced(True)
    assert (restored.terminalFontFamily, restored.terminalFontSize) == ("Courier New", 17)


def test_text_rendering_mode_persists_and_resets(tmp_path):
    mgr = _create_manager(tmp_path)
    if sys.platform == "darwin":
        # macOS keeps deriving the mode from the legacy smoothing toggle.
        mgr.setFontSmoothing(False)
        assert mgr.textRenderingMode == "qt"
        mgr.setFontSmoothing(True)
        assert mgr.textRenderingMode == "native"
        return

    assert mgr.textRenderingMode == DEFAULT_TEXT_RENDERING
    mgr.setTextRenderingMode("native")
    assert mgr.textRenderingMode == "native"
    restored = _create_manager(tmp_path)
    assert restored.textRenderingMode == "native"
    restored.setTextRenderingMode("invalid")
    assert restored.textRenderingMode == "native"
    restored.resetSetting("textRendering")
    assert restored.textRenderingMode == DEFAULT_TEXT_RENDERING


def test_t3_themes_map_inline_code_to_the_muted_surface():
    """T3 `.chat-markdown :not(pre)>code` fills with --muted, not the accent."""
    for theme_id, colors in (("ocean", ("#233544", "#405567")),
                             ("grove", ("#253e31", "#415f4f")),
                             ("ember", ("#432e23", "#664c3f"))):
        palette = BUILTIN_THEMES[theme_id].palette
        assert palette["inlineCodeSurface"] == colors[0]
        assert palette["inlineCodeSurface"] == palette["mutedSurface"]
        assert palette["chatBorder"] == colors[1]

    imported = {
        "name": "Ocean import",
        "appearance": "dark",
        "colors": {"canvas": "#17212b", "accent": "#70b9ee", "muted": "#233544",
                   "border": "#405567", "text": "#fffaff"},
    }
    ok, _message, theme = parse_imported_theme(json.dumps(imported))
    assert ok and theme is not None
    assert theme.palette["inlineCodeSurface"] == "#233544"
    assert theme.palette["chatBorder"] == "#405567"


def test_theme_lookup_and_duplication_are_independent_of_active_mode(tmp_path):
    mgr = _create_manager(tmp_path)
    mgr.setAppearanceMode("light")
    mgr.setThemeForAppearance("dark", "ocean")
    mgr.setThemeForAppearance("light", "iris")
    assert mgr.themeDark == "ocean"
    assert mgr.themeLight == "iris-light"
    duplicate = mgr.duplicateTheme("ocean", "Ocean copy")
    exported = json.loads(mgr.exportThemeJson(duplicate))
    assert exported["appearance"] == "dark"
    assert exported["palette"]["background"] == BUILTIN_THEMES["ocean"].palette["background"]
    mgr.setThemeForAppearance("light", duplicate)
    assert mgr.themeLight == "iris-light"
    mgr.setAppearanceMode("dark")
    assert mgr.activeThemeId == "ocean"


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


def test_t3_oklch_variants_import_atomically_and_persist(tmp_path):
    mgr = _create_manager(tmp_path)
    payload = {
        "label": "Paired theme", "appearance": "light",
        "colors": {"canvas": "oklch(1 0 0)", "accent": "#3155aa", "text": "#111111"},
        "variants": {"dark": {"canvas": "oklch(0 0 0)", "accent": "#99bbff", "text": "#eeeeee"}},
    }
    result = mgr.importThemeJson(json.dumps(payload))
    assert result["success"]
    themes = [t for t in mgr.availableThemes if not t["builtIn"]]
    assert len(themes) == 2
    assert {t["appearance"] for t in themes} == {"light", "dark"}
    assert {t["collection"] for t in themes} == {result["themeId"]}
    assert {t["palette"]["background"] for t in themes} == {"#ffffff", "#000000"}
    restored = _create_manager(tmp_path)
    assert [t for t in restored.availableThemes if not t["builtIn"]] == themes
    exported = mgr.exportThemeJson(result["themeId"])
    assert mgr.importThemeJson(exported)["success"]
    assert len([t for t in mgr.availableThemes if not t["builtIn"]]) == 4
    count = len(mgr.availableThemes)
    payload["variants"]["dark"]["canvas"] = "oklch(invalid)"
    assert not mgr.importThemeJson(json.dumps(payload))["success"]
    assert len(mgr.availableThemes) == count


def test_native_partial_palette_is_completed_and_edit_updates_swatch(tmp_path):
    mgr = _create_manager(tmp_path)
    result = mgr.importThemeJson(json.dumps({
        "name": "Small theme", "appearance": "dark",
        "palette": {"background": "#112233", "text": "#eeeeee", "brandOrange": "#4477bb"},
    }))
    assert result["success"]
    mgr.setAppearanceMode("dark")
    mgr.setThemeForAppearance("dark", result["themeId"])
    assert mgr.palette["background"] == "#112233"
    assert {"chatComposer", "chatControl", "headingText", "border"} <= mgr.palette.keys()
    assert mgr.updateCustomTheme(result["themeId"], "Edited", "dark", {"background": "#223344"})
    assert mgr.palette["previewCanvas"] == "#223344"
    assert not mgr.importThemeJson(json.dumps({"palette": {"text": "broken"}}))["success"]

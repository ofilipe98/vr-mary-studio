"""Interactions against the rendered Appearance page and persisted preferences."""
import json
from unittest.mock import patch

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from scripts.visual_appearance_review import appearance_window, find_item

pytestmark = pytest.mark.qml


@pytest.fixture
def appearance(tmp_path):
    with appearance_window(tmp_path) as (frontend, engine, window, warnings):
        yield frontend, window
        assert not warnings


def item(window, name):
    found = find_item(window.contentItem(), name)
    assert found is not None, name
    return found


def reveal(window, control):
    scroll = window.findChild(QObject, "appearanceSettingsScroll")
    flick = scroll.property("contentItem")
    y = control.mapToItem(flick, QPointF(0, 0)).y()
    if y < 20 or y + control.height() > flick.height() - 20:
        flick.setProperty("contentY", max(0, min(flick.property("contentHeight") - flick.height(), flick.property("contentY") + y - 30)))
        QTest.qWait(50)


def click(window, name):
    control = item(window, name)
    reveal(window, control)
    point = control.mapToScene(QPointF(control.width() / 2, control.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(60)
    return control


def test_theme_halves_switch_independently_and_highlight(appearance):
    frontend, window = appearance
    click(window, "themeVariant_iris-light")
    assert frontend.themeLight == "iris-light"
    assert frontend.themeDark == "ocean"
    assert frontend.resolvedAppearance == "dark"
    assert item(window, "themeVariant_iris-light").property("isActive")
    click(window, "colorScheme_light")
    assert frontend.themeId == "iris-light"
    click(window, "themeVariant_ember")
    assert frontend.themeDark == "ember"
    assert frontend.themeId == "iris-light"
    click(window, "colorScheme_dark")
    assert frontend.themeId == "ember"
    click(window, "colorScheme_system")
    assert frontend.appearanceMode == "system"


def test_sliders_reset_keyboard_motion_and_environment(appearance):
    frontend, window = appearance
    for name, prop, step in [("contrast", "appearanceContrast", 5), ("glass", "glassOpacity", 5), ("motion", "rawPanelAnimationDurationMs", 25)]:
        slider = item(window, name + "Slider")
        reveal(window, slider)
        original = getattr(frontend, prop)
        slider.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Right)
        assert getattr(frontend, prop) == original + step
        click(window, name + "Reset")
        assert getattr(frontend, prop) == original
    frontend.setPanelAnimationDurationMs(200)
    preview = item(window, "panelAnimationsPreview")
    reveal(window, preview)
    old = preview.property("panelsOpen")
    click(window, "panelAnimationsPreview")
    assert preview.property("panelsOpen") != old
    frontend.setReduceMotion(True)
    assert preview.property("animDuration") == 0
    assert frontend.rawPanelAnimationDurationMs == 200
    combo = item(window, "environmentIdentificationCombo")
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Down)
    assert frontend.environmentIdentification == "artwork"
    click(window, "environmentReset")
    assert frontend.environmentIdentification == "pill"


def test_typography_advanced_font_search_size_and_wrap(appearance):
    frontend, window = appearance
    click(window, "typographyAdvancedSwitch")
    assert frontend.typographyAdvanced
    assert item(window, "promptFontSetting").isVisible()
    assert item(window, "terminalFontSetting").isVisible()
    click(window, "interfaceFontFamily")
    search = item(window, "fontSearchField")
    assert search.isVisible() and search.hasActiveFocus()
    search.setProperty("text", "Arial")
    QTest.qWait(30)
    fonts = item(window, "fontPickerList")
    assert fonts.property("count") > 0
    QTest.keyClick(window, Qt.Key_Return)
    assert frontend.interfaceFontFamily == "Arial"
    combo = item(window, "codeFontSize")
    reveal(window, combo)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Down)
    assert frontend.codeFontSize == 14
    assert item(window, "codeFontPreviewLine").property("font").pixelSize() == 14
    click(window, "appearanceWordWrapSwitch")
    assert not frontend.wordWrap
    click(window, "wordWrapReset")
    assert frontend.wordWrap
    click(window, "typographyAdvancedSwitch")
    assert not frontend.typographyAdvanced
    assert frontend.promptFontFamily == "Arial"
    assert frontend.terminalFontSize == frontend.codeFontSize


def test_theme_duplicate_editor_escape_and_import_feedback(appearance):
    frontend, window = appearance
    before = len(frontend.availableThemes)
    click(window, "duplicateTheme_ocean")
    assert len(frontend.availableThemes) == before + 2
    editor = window.findChild(QObject, "themeEditorModal")
    assert editor.property("visible")
    color_field = item(window, "colorBackgroundInput")
    color_field.setProperty("text", "#invalid")
    assert not item(window, "themeSaveButton").property("enabled")
    color_field.setProperty("text", "#123456")
    assert item(window, "themeSaveButton").property("enabled")
    custom = next(t for t in frontend.availableThemes if not t["builtIn"])
    assert custom["appearance"] == "dark"
    assert custom["palette"]["background"] == frontend.palette["background"]
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.qWait(30)
    assert not editor.property("visible")
    exported = json.loads(frontend.exportThemeJson(custom["id"]))
    assert exported["name"] == custom["name"]
    assert frontend.importThemeJson(json.dumps(exported))["success"]
    assert not frontend.importThemeJson("{invalid")["success"]
    click(window, "importThemeButton")
    modal = window.findChild(QObject, "themeImportModal")
    assert modal.property("visible")
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.qWait(30)
    assert not modal.property("visible")


def test_hardware_acceleration_toggle(appearance):
    frontend, window = appearance
    assert frontend.hardwareAcceleration is False
    switch = item(window, "hardwareAccelerationSwitch")
    reveal(window, switch)
    click(window, "hardwareAccelerationSwitch")
    assert frontend.hardwareAcceleration is True
    assert str(frontend._preferences.value("appearance/hardware_acceleration")).lower() in ("true", "1")
    click(window, "hardwareAccelerationSwitch")
    assert frontend.hardwareAcceleration is False
    assert str(frontend._preferences.value("appearance/hardware_acceleration")).lower() in ("false", "0")


def test_preferences_reach_brand_header_and_actual_composer(tmp_path):
    with appearance_window(tmp_path, full=True) as (frontend, engine, window, warnings):
        window.setWidth(1280)
        window.setHeight(820)
        frontend.setEnvironmentIdentification("artwork")
        QTest.qWait(20)
        assert item(window, "environmentArtwork").isVisible()
        assert not item(window, "environmentVersionPill").isVisible()
        frontend.setEnvironmentIdentification("none")
        assert not item(window, "environmentArtwork").isVisible()
        chat = engine.rootContext().contextProperty("chat")
        studio = engine.rootContext().contextProperty("studio")
        with patch.object(chat, "refreshModels"), patch.object(studio, "refreshProviders"):
            frontend.setCurrentPage(1)
            QTest.qWait(200)
        frontend.setTypographyAdvanced(True)
        frontend.setPromptTypography("Consolas", 18)
        frontend.setGlassOpacity(60)
        QTest.qWait(20)
        composer = item(window, "chatComposerCard")
        prompt = item(window, "chatComposerInput")
        assert prompt.property("font").family() == "Consolas"
        assert prompt.property("font").pixelSize() == 18
        assert composer.property("color").alphaF() == pytest.approx(.6, abs=.01)
        frontend.setUiScale("150")
        QTest.qWait(20)
        assert prompt.property("font").pixelSize() == 27
        frontend.setCurrentPage(7)
        QTest.qWait(100)
        window.findChild(QObject, "settingsPage").setProperty("tabIndex", 4)
        QTest.qWait(50)
        assert item(window, "interfaceFontFamily").property("font").pixelSize() == 20
        frontend.setInterfaceTypography("Arial", 16)
        QTest.qWait(20)
        assert window.property("font").family() == "Arial"
        assert window.property("font").pixelSize() == 24
        assert item(window, "interfaceFontFamily").property("font").pixelSize() == 22
        assert not warnings

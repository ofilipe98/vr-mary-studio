"""Presentation-only state exposed to the QML frontend."""

from __future__ import annotations

import sys

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QSettings, QUrl, Signal, Slot

from ... import __version__
from ..brand import (
    APP_TITLE,
    ASSET_DIR,
    ORGANIZATION_NAME,
    SETTINGS_APP_NAME,
)
from ..theme_manager import ThemeManager
from .text_rendering import (
    CodeSyntaxHighlighter,
    apply_message_document_style,
    presentation_blocks,
    table_clipboard_text,
    table_row_edges,
)
from ..config import MarySettings


NAVIGATION_ITEMS = (
    ("Dashboard", "nav-dashboard.svg"),
    ("Chat VR", "nav-chat.svg"),
    ("Conhecimento", "nav-knowledge.svg"),
    ("Sincronizações", "nav-sync.svg"),
    ("Revisão", "nav-review.svg"),
    ("Vídeos", "nav-videos.svg"),
    ("Logs", "nav-logs.svg"),
    ("Configurações", "sidebar-settings.svg"),
)


def _file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path.resolve())).toString()


def _stored_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


UI_SCALE_OPTIONS = (
    "auto",
    "100",
    "101",
    "102",
    "103",
    "104",
    "105",
    "110",
    "125",
    "150",
)
UI_SCALE_PREFERENCE_VERSION = 2
INTERFACE_FONT_OPTIONS = ("Segoe UI", "Arial", "Inter", "Tahoma")
MONOSPACE_FONT_OPTIONS = ("Consolas", "Cascadia Code", "Courier New")
BROWSER_VIEWPORT_OPTIONS = ("fill", "1280x720", "1440x900", "390x844")
BROWSER_ZOOM_OPTIONS = ("75", "90", "100", "110", "125", "150")
BROWSER_APPEARANCE_OPTIONS = ("system", "light", "dark")


def normalized_ui_scale(value: object, default: str = "auto") -> str:
    """Return a supported interface scale percentage (no percent sign)."""
    text = str(value or "").strip().rstrip("%").strip()
    return text if text in UI_SCALE_OPTIONS else default


class FrontendBridge(QObject):
    """Stable QML-facing state; business rules remain in the existing backend."""

    themeChanged = Signal()
    currentPageChanged = Signal()
    navigationCollapsedChanged = Signal()
    reduceMotionChanged = Signal()
    uiScaleChanged = Signal()
    hardwareAccelerationChanged = Signal()
    typographyChanged = Signal()
    browserPreferencesChanged = Signal()

    # T3 Code Appearance Parity Signals
    appearanceModeChanged = Signal()
    resolvedAppearanceChanged = Signal()
    themesListChanged = Signal()
    contrastChanged = Signal()
    glassOpacityChanged = Signal()
    motionChanged = Signal()
    themeImportStatus = Signal(bool, str)
    environmentIdentificationChanged = Signal()

    def __init__(
        self,
        settings: MarySettings,
        preferences: QSettings | None = None,
        *,
        theme_override: str = "",
        initial_page: str = "Chat VR",
        navigation_override: bool | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._preferences = preferences or QSettings(
            ORGANIZATION_NAME, SETTINGS_APP_NAME
        )

        # Initialize ThemeManager
        self._theme_manager = ThemeManager(self._preferences, self)
        if theme_override:
            self._theme_manager.setTheme(theme_override)

        self._theme_manager.themeChanged.connect(self.themeChanged)
        self._theme_manager.appearanceModeChanged.connect(self.appearanceModeChanged)
        self._theme_manager.resolvedAppearanceChanged.connect(self.resolvedAppearanceChanged)
        self._theme_manager.themesListChanged.connect(self.themesListChanged)
        self._theme_manager.contrastChanged.connect(self.contrastChanged)
        self._theme_manager.glassOpacityChanged.connect(self.glassOpacityChanged)
        self._theme_manager.motionChanged.connect(self.motionChanged)
        self._theme_manager.motionChanged.connect(self.reduceMotionChanged)
        self._theme_manager.typographyChanged.connect(self.typographyChanged)
        self._theme_manager.themeImportStatus.connect(self.themeImportStatus)
        self._theme_manager.environmentIdentificationChanged.connect(self.environmentIdentificationChanged)

        self._navigation_collapsed = (
            _stored_bool(self._preferences.value("appearance/nav_collapsed", False))
            if navigation_override is None
            else bool(navigation_override)
        )
        scale_version = int(
            self._preferences.value("appearance/ui_scale_version", 0) or 0
        )
        if scale_version < UI_SCALE_PREFERENCE_VERSION:
            self._ui_scale = "auto"
            self._preferences.setValue("appearance/ui_scale", self._ui_scale)
            self._preferences.setValue(
                "appearance/ui_scale_version", UI_SCALE_PREFERENCE_VERSION
            )
            self._preferences.sync()
        else:
            self._ui_scale = normalized_ui_scale(
                self._preferences.value("appearance/ui_scale", "auto")
            )

        self._hardware_acceleration = _stored_bool(
            self._preferences.value("appearance/hardware_acceleration", False), False
        )

        self._browser_agent_access = _stored_bool(
            self._preferences.value("browser/agent_access", True), True
        )
        self._browser_viewport = self._stored_choice(
            "browser/default_viewport", "fill", BROWSER_VIEWPORT_OPTIONS
        )
        self._browser_zoom = self._stored_choice(
            "browser/default_zoom", "100", BROWSER_ZOOM_OPTIONS
        )
        self._browser_appearance = self._stored_choice(
            "browser/appearance", "system", BROWSER_APPEARANCE_OPTIONS
        )
        self._browser_auto_show = _stored_bool(
            self._preferences.value("browser/auto_show_preview", True), True
        )

        page_names = [title for title, _icon in NAVIGATION_ITEMS]
        try:
            self._current_page = page_names.index(initial_page)
        except ValueError:
            self._current_page = 0
        self._styling_document = False

    def _stored_choice(
        self, key: str, default: str, choices: tuple[str, ...]
    ) -> str:
        value = str(self._preferences.value(key, default) or default)
        return value if value in choices else default

    def _stored_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self._preferences.value(key, default) or default)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @Property(str, constant=True)
    def appName(self) -> str:  # noqa: N802 - QML property naming
        return APP_TITLE

    @Property(str, constant=True)
    def appVersion(self) -> str:  # noqa: N802 - QML property naming
        return f"v{__version__}"

    @Property(str, constant=True)
    def environmentStage(self) -> str:  # noqa: N802
        if "dev" in __version__.lower():
            return "Nightly"
        return "" if getattr(sys, "frozen", False) else "Dev"

    @Property(str, constant=True)
    def version(self) -> str:
        return __version__

    @Property(str, constant=True)
    def projectName(self) -> str:  # noqa: N802 - QML property naming
        return self._settings.root.name or "VRProject"

    @Property(str, constant=True)
    def projectPath(self) -> str:  # noqa: N802 - QML property naming
        return str(self._settings.root)

    @Property(str, constant=True)
    def brandSymbolUrl(self) -> str:  # noqa: N802 - QML property naming
        return _file_url(ASSET_DIR / "vrnorte-symbol.png")

    @Property(str, constant=True)
    def appIcon(self) -> str:  # noqa: N802 - QML property naming
        return _file_url(ASSET_DIR / "vr-brand-mark.svg")

    @Property("QVariantList", constant=True)
    def navigationItems(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            {
                "title": title,
                "icon": _file_url(ASSET_DIR / icon),
                "settings": title == "Configurações",
            }
            for title, icon in NAVIGATION_ITEMS
        ]

    # ------------------------------------------------------------------------
    # Theme & Palette Properties
    # ------------------------------------------------------------------------

    @Property(str, notify=themeChanged)
    def themeId(self) -> str:  # noqa: N802 - QML property naming
        return self._theme_manager.activeThemeId

    @Property("QVariantMap", notify=themeChanged)
    def palette(self) -> dict[str, str]:
        return self._theme_manager.palette

    @Property(str, notify=appearanceModeChanged)
    def appearanceMode(self) -> str:  # noqa: N802
        return self._theme_manager.appearanceMode

    @Property(str, notify=resolvedAppearanceChanged)
    def resolvedAppearance(self) -> str:  # noqa: N802
        return self._theme_manager.resolvedAppearance

    @Property(str, notify=themeChanged)
    def themeLight(self) -> str:  # noqa: N802
        return self._theme_manager.themeLight

    @Property(str, notify=themeChanged)
    def themeDark(self) -> str:  # noqa: N802
        return self._theme_manager.themeDark

    @Property("QVariantList", notify=themesListChanged)
    def availableThemes(self) -> list[dict[str, Any]]:  # noqa: N802
        return self._theme_manager.availableThemes

    # ------------------------------------------------------------------------
    # Appearance Sliders (Contrast, Glass, Motion)
    # ------------------------------------------------------------------------

    @Property(int, notify=contrastChanged)
    def appearanceContrast(self) -> int:  # noqa: N802
        return self._theme_manager.appearanceContrast

    @Property(int, notify=glassOpacityChanged)
    def glassOpacity(self) -> int:  # noqa: N802
        return self._theme_manager.glassOpacity

    @Property(str, notify=environmentIdentificationChanged)
    def environmentIdentification(self) -> str:  # noqa: N802
        return self._theme_manager.environmentIdentification

    @Property(int, notify=motionChanged)
    def panelAnimationDurationMs(self) -> int:  # noqa: N802
        return self._theme_manager.panelAnimationDurationMs

    @Property(int, notify=motionChanged)
    def rawPanelAnimationDurationMs(self) -> int:  # noqa: N802
        return self._theme_manager.rawPanelAnimationDurationMs

    @Property(bool, notify=reduceMotionChanged)
    def reduceMotion(self) -> bool:  # noqa: N802
        return self._theme_manager.reduceMotion

    # ------------------------------------------------------------------------
    # Typography Properties (Simple + Advanced)
    # ------------------------------------------------------------------------

    @Property(bool, notify=typographyChanged)
    def typographyAdvanced(self) -> bool:  # noqa: N802
        return self._theme_manager.typographyAdvanced

    @Property(str, notify=typographyChanged)
    def interfaceFontFamily(self) -> str:  # noqa: N802
        return self._theme_manager.interfaceFontFamily

    @Property(str, notify=typographyChanged)
    def effectiveInterfaceFontFamily(self) -> str:  # noqa: N802
        fam = self._theme_manager.interfaceFontFamily
        if fam in ("Segoe UI", "") and sys.platform == "win32":
            from PySide6.QtGui import QFontDatabase

            if "Segoe UI Variable Text" in set(QFontDatabase.families()):
                return "Segoe UI Variable Text"
        return fam or "Segoe UI"

    @Property(int, notify=typographyChanged)
    def interfaceFontSize(self) -> int:  # noqa: N802
        return self._theme_manager.interfaceFontSize

    @Property(str, notify=typographyChanged)
    def promptFontFamily(self) -> str:  # noqa: N802
        return self._theme_manager.promptFontFamily

    @Property(int, notify=typographyChanged)
    def promptFontSize(self) -> int:  # noqa: N802
        return self._theme_manager.promptFontSize

    @Property(str, notify=typographyChanged)
    def monospaceFontFamily(self) -> str:  # noqa: N802
        return self._theme_manager.monospaceFontFamily

    @Property(int, notify=typographyChanged)
    def monospaceFontSize(self) -> int:  # noqa: N802
        return self._theme_manager.monospaceFontSize

    @Property(str, notify=typographyChanged)
    def codeFontFamily(self) -> str:  # noqa: N802
        return self._theme_manager.codeFontFamily

    @Property(int, notify=typographyChanged)
    def codeFontSize(self) -> int:  # noqa: N802
        return self._theme_manager.codeFontSize

    @Property(str, notify=typographyChanged)
    def terminalFontFamily(self) -> str:  # noqa: N802
        return self._theme_manager.terminalFontFamily

    @Property(int, notify=typographyChanged)
    def terminalFontSize(self) -> int:  # noqa: N802
        return self._theme_manager.terminalFontSize

    @Property(bool, notify=typographyChanged)
    def fontSmoothing(self) -> bool:  # noqa: N802
        return self._theme_manager.fontSmoothing

    @Property(bool, notify=typographyChanged)
    def isMacOS(self) -> bool:  # noqa: N802
        return self._theme_manager.isMacOS

    @Property(bool, notify=typographyChanged)
    def wordWrap(self) -> bool:  # noqa: N802
        return self._theme_manager.wordWrap

    @Property("QVariantList", constant=True)
    def systemFontFamilies(self) -> list[str]:  # noqa: N802
        return self._theme_manager.systemFontFamilies

    @Property("QVariantList", constant=True)
    def monospaceFontFamilies(self) -> list[str]:  # noqa: N802
        return self._theme_manager.monospaceFontFamilies

    # ------------------------------------------------------------------------
    # Navigation & Scale Properties
    # ------------------------------------------------------------------------

    @Property(int, notify=currentPageChanged)
    def currentPage(self) -> int:  # noqa: N802 - QML property naming
        return self._current_page

    @Property(str, notify=currentPageChanged)
    def currentPageTitle(self) -> str:  # noqa: N802 - QML property naming
        return NAVIGATION_ITEMS[self._current_page][0]

    @Property(bool, notify=navigationCollapsedChanged)
    def navigationCollapsed(self) -> bool:  # noqa: N802
        return self._navigation_collapsed

    @Property(str, notify=uiScaleChanged)
    def uiScale(self) -> str:  # noqa: N802 - QML property naming
        return self._ui_scale

    @Property(float, notify=uiScaleChanged)
    def uiScaleFactor(self) -> float:  # noqa: N802 - QML property naming
        return 1.0 if self._ui_scale == "auto" else int(self._ui_scale) / 100.0

    @Property(bool, notify=hardwareAccelerationChanged)
    def hardwareAcceleration(self) -> bool:  # noqa: N802
        return self._hardware_acceleration

    # ------------------------------------------------------------------------
    # Browser Properties
    # ------------------------------------------------------------------------

    @Property(bool, notify=browserPreferencesChanged)
    def browserAgentAccess(self) -> bool:  # noqa: N802
        return self._browser_agent_access

    @Property(str, notify=browserPreferencesChanged)
    def browserViewport(self) -> str:  # noqa: N802
        return self._browser_viewport

    @Property(float, notify=browserPreferencesChanged)
    def browserZoomFactor(self) -> float:  # noqa: N802
        return int(self._browser_zoom) / 100.0

    @Property(str, notify=browserPreferencesChanged)
    def browserZoom(self) -> str:  # noqa: N802
        return self._browser_zoom

    @Property(str, notify=browserPreferencesChanged)
    def browserAppearance(self) -> str:  # noqa: N802
        return self._browser_appearance

    @Property(bool, notify=browserPreferencesChanged)
    def browserAutoShowPreview(self) -> bool:  # noqa: N802
        return self._browser_auto_show

    # ------------------------------------------------------------------------
    # Slots: Theme & Appearance
    # ------------------------------------------------------------------------

    @Slot(str)
    def setTheme(self, theme_id: str) -> None:  # noqa: N802
        self._preferences.setValue("appearance/theme", theme_id)
        self._preferences.sync()
        self._theme_manager.setTheme(theme_id)

    @Slot()
    def toggleTheme(self) -> None:  # noqa: N802
        new_mode = "light" if self._theme_manager.resolvedAppearance == "dark" else "dark"
        self._theme_manager.setAppearanceMode(new_mode)

    @Slot(str)
    def setAppearanceMode(self, mode: str) -> None:  # noqa: N802
        self._theme_manager.setAppearanceMode(mode)

    @Slot(str, str)
    def setThemeForAppearance(self, appearance: str, theme_id: str) -> None:  # noqa: N802
        self._theme_manager.setThemeForAppearance(appearance, theme_id)

    @Slot(int)
    def setAppearanceContrast(self, contrast: int) -> None:  # noqa: N802
        self._theme_manager.setAppearanceContrast(contrast)

    @Slot(int)
    def setGlassOpacity(self, opacity: int) -> None:  # noqa: N802
        self._theme_manager.setGlassOpacity(opacity)

    @Slot(str)
    def setEnvironmentIdentification(self, mode: str) -> None:  # noqa: N802
        self._theme_manager.setEnvironmentIdentification(mode)

    @Slot(int)
    def setPanelAnimationDurationMs(self, duration_ms: int) -> None:  # noqa: N802
        self._theme_manager.setPanelAnimationDurationMs(duration_ms)

    @Slot(bool)
    def setReduceMotion(self, enabled: bool) -> None:  # noqa: N802
        self._theme_manager.setReduceMotion(enabled)

    @Slot(bool)
    def setTypographyAdvanced(self, advanced: bool) -> None:  # noqa: N802
        self._theme_manager.setTypographyAdvanced(advanced)

    @Slot(str, int)
    def setInterfaceTypography(self, family: str, size: int) -> None:  # noqa: N802
        self._theme_manager.setInterfaceTypography(family, size)

    @Slot(str, int)
    def setPromptTypography(self, family: str, size: int) -> None:  # noqa: N802
        self._theme_manager.setPromptTypography(family, size)

    @Slot(str, int)
    def setCodeTypography(self, family: str, size: int) -> None:  # noqa: N802
        self._theme_manager.setCodeTypography(family, size)

    @Slot(str, int)
    def setTerminalTypography(self, family: str, size: int) -> None:  # noqa: N802
        self._theme_manager.setTerminalTypography(family, size)

    @Slot(bool)
    def setFontSmoothing(self, enabled: bool) -> None:  # noqa: N802
        self._theme_manager.setFontSmoothing(enabled)

    @Slot(bool)
    def setWordWrap(self, enabled: bool) -> None:  # noqa: N802
        self._theme_manager.setWordWrap(enabled)

    @Slot(str)
    def resetAppearanceSetting(self, setting_name: str) -> None:  # noqa: N802
        self._theme_manager.resetSetting(setting_name)

    @Slot(str, str, str, result=str)
    def createCustomTheme(self, name: str, appearance: str, seed_theme_id: str) -> str:  # noqa: N802
        return self._theme_manager.createCustomTheme(name, appearance, seed_theme_id)

    @Slot(str, str, str, "QVariantMap", result=bool)
    def updateCustomTheme(self, theme_id: str, name: str, appearance: str, palette_map: dict[str, Any]) -> bool:  # noqa: N802
        return self._theme_manager.updateCustomTheme(theme_id, name, appearance, palette_map)

    @Slot(str, str, result=str)
    def duplicateTheme(self, theme_id: str, new_name: str) -> str:  # noqa: N802
        return self._theme_manager.duplicateTheme(theme_id, new_name)

    @Slot(str, result=bool)
    def deleteCustomTheme(self, theme_id: str) -> bool:  # noqa: N802
        return self._theme_manager.deleteCustomTheme(theme_id)

    @Slot(str, result=str)
    def exportThemeJson(self, theme_id: str) -> str:  # noqa: N802
        return self._theme_manager.exportThemeJson(theme_id)

    @Slot(str, result="QVariantMap")
    def importThemeJson(self, json_string: str) -> dict[str, Any]:  # noqa: N802
        return self._theme_manager.importThemeJson(json_string)

    @Slot(str, result=bool)
    def isMonospaceFont(self, family_name: str) -> bool:  # noqa: N802
        return self._theme_manager.isMonospace(family_name)

    @Slot(str, result=bool)
    def isFontAvailable(self, family_name: str) -> bool:  # noqa: N802
        return self._theme_manager.isFontAvailable(family_name)

    @Slot(str, int, str, int, bool)
    def setTypography(
        self,
        interface_family: str,
        interface_size: int,
        monospace_family: str,
        monospace_size: int,
        word_wrap: bool,
    ) -> None:  # noqa: N802
        self._theme_manager.setInterfaceTypography(interface_family, interface_size)
        self._theme_manager.setCodeTypography(monospace_family, monospace_size)
        self._theme_manager.setWordWrap(word_wrap)

    # ------------------------------------------------------------------------
    # Slots: Text & Highlighting
    # ------------------------------------------------------------------------

    @Slot(str, result="QVariantList")
    def messageBlocks(self, markdown: str):
        return presentation_blocks(markdown)

    @Slot(str, str, result=str)
    def tableClipboardText(self, markdown: str, format_name: str) -> str:
        return table_clipboard_text(markdown, format_name)

    @Slot(QObject, result="QVariantList")
    def tableRowEdges(self, quick_document):
        if quick_document is None:
            return []
        return table_row_edges(quick_document.textDocument())

    @Slot(QObject, str)
    def styleMessageDocument(self, quick_document, markdown: str) -> None:
        """Restyle a QML TextEdit markdown document with the T3-like rhythm."""
        if self._styling_document or quick_document is None:
            return
        text_document_factory = getattr(quick_document, "textDocument", None)
        if text_document_factory is None:
            return
        document = text_document_factory()
        if document is None:
            return
        self._styling_document = True
        try:
            apply_message_document_style(
                document,
                str(markdown or ""),
                dark=self.themeId == "dark_orange" or self.resolvedAppearance == "dark",
                monospace_family=self.monospaceFontFamily,
            )
        finally:
            self._styling_document = False

    @Slot(QObject, str)
    def highlightCodeDocument(self, quick_document, language: str) -> None:
        """Attach the shared syntax highlighter to a QML code card document."""
        if quick_document is None:
            return
        text_document_factory = getattr(quick_document, "textDocument", None)
        if text_document_factory is None:
            return
        document = text_document_factory()
        if document is None:
            return
        highlighter = document.findChild(CodeSyntaxHighlighter)
        if highlighter is None:
            highlighter = CodeSyntaxHighlighter(document, str(language or ""))
            highlighter.setParent(document)
        highlighter.language = str(language or "").strip().casefold()
        highlighter.set_theme(self.themeId == "dark_orange" or self.resolvedAppearance == "dark")

    # ------------------------------------------------------------------------
    # Slots: General Navigation & Scale
    # ------------------------------------------------------------------------

    @Slot(int)
    def setCurrentPage(self, index: int) -> None:  # noqa: N802
        if index < 0 or index >= len(NAVIGATION_ITEMS):
            return
        if index == self._current_page:
            return
        self._current_page = index
        self.currentPageChanged.emit()

    @Slot()
    def toggleNavigation(self) -> None:  # noqa: N802
        self._navigation_collapsed = not self._navigation_collapsed
        self._preferences.setValue(
            "appearance/nav_collapsed", self._navigation_collapsed
        )
        self._preferences.sync()
        self.navigationCollapsedChanged.emit()

    @Slot(str)
    def setUiScale(self, value: str) -> None:  # noqa: N802
        selected = normalized_ui_scale(value, default=self._ui_scale)
        if selected == self._ui_scale:
            return
        self._ui_scale = selected
        self._preferences.setValue("appearance/ui_scale", selected)
        self._preferences.setValue(
            "appearance/ui_scale_version", UI_SCALE_PREFERENCE_VERSION
        )
        self._preferences.sync()
        self.uiScaleChanged.emit()

    @Slot(bool)
    def setHardwareAcceleration(self, enabled: bool) -> None:  # noqa: N802
        flag = bool(enabled)
        if flag == self._hardware_acceleration:
            return
        self._hardware_acceleration = flag
        self._preferences.setValue("appearance/hardware_acceleration", flag)
        self._preferences.sync()
        self.hardwareAccelerationChanged.emit()

    # ------------------------------------------------------------------------
    # Slots: Browser
    # ------------------------------------------------------------------------

    @Slot(bool)
    def setBrowserAgentAccess(self, enabled: bool) -> None:  # noqa: N802
        self._set_browser_preference("_browser_agent_access", "browser/agent_access", bool(enabled))

    @Slot(str)
    def setBrowserViewport(self, value: str) -> None:  # noqa: N802
        selected = value if value in BROWSER_VIEWPORT_OPTIONS else "fill"
        self._set_browser_preference("_browser_viewport", "browser/default_viewport", selected)

    @Slot(str)
    def setBrowserZoom(self, value: str) -> None:  # noqa: N802
        selected = value if value in BROWSER_ZOOM_OPTIONS else "100"
        self._set_browser_preference("_browser_zoom", "browser/default_zoom", selected)

    @Slot(str)
    def setBrowserAppearance(self, value: str) -> None:  # noqa: N802
        selected = value if value in BROWSER_APPEARANCE_OPTIONS else "system"
        self._set_browser_preference("_browser_appearance", "browser/appearance", selected)

    @Slot(bool)
    def setBrowserAutoShowPreview(self, enabled: bool) -> None:  # noqa: N802
        self._set_browser_preference(
            "_browser_auto_show", "browser/auto_show_preview", bool(enabled)
        )

    def _set_browser_preference(self, attribute: str, key: str, value: object) -> None:
        if getattr(self, attribute) == value:
            return
        setattr(self, attribute, value)
        self._preferences.setValue(key, value)
        self._preferences.sync()
        self.browserPreferencesChanged.emit()

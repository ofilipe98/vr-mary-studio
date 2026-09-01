"""Presentation-only state exposed to the QML frontend."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Property, QSettings, QUrl, Signal, Slot

from ... import __version__
from ..brand import (
    APP_TITLE,
    ASSET_DIR,
    ORGANIZATION_NAME,
    SETTINGS_APP_NAME,
    brand_palette,
)
from .text_rendering import CodeSyntaxHighlighter, apply_message_document_style
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
    typographyChanged = Signal()
    browserPreferencesChanged = Signal()

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
        saved_theme = str(
            self._preferences.value("appearance/theme", "light") or "light"
        )
        selected_theme = theme_override or saved_theme
        self._theme_id = (
            "dark_orange" if selected_theme == "dark_orange" else "light"
        )
        self._navigation_collapsed = (
            _stored_bool(self._preferences.value("appearance/nav_collapsed", False))
            if navigation_override is None
            else bool(navigation_override)
        )
        self._reduce_motion = _stored_bool(
            self._preferences.value("appearance/reduce_motion", False)
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
        self._interface_font_family = self._stored_choice(
            "appearance/interface_font_family", "Segoe UI", INTERFACE_FONT_OPTIONS
        )
        self._interface_font_size = self._stored_int(
            "appearance/interface_font_size", 14, 11, 22
        )
        self._monospace_font_family = self._stored_choice(
            "appearance/monospace_font_family", "Consolas", MONOSPACE_FONT_OPTIONS
        )
        self._monospace_font_size = self._stored_int(
            "appearance/monospace_font_size", 12, 10, 20
        )
        self._word_wrap = _stored_bool(
            self._preferences.value("appearance/word_wrap", True), True
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
        self._palette_cache: dict[str, str] | None = None
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

    @Property(str, notify=themeChanged)
    def themeId(self) -> str:  # noqa: N802 - QML property naming
        return self._theme_id

    @Property("QVariantMap", notify=themeChanged)
    def palette(self) -> dict[str, str]:
        # Rebuilt on demand and cached: QML evaluates this property for every
        # color binding, so rebuilding the dict per read shows up as tab-switch
        # latency on page creation.
        if self._palette_cache is None:
            self._palette_cache = brand_palette(self._theme_id)
        return self._palette_cache

    @Property(int, notify=currentPageChanged)
    def currentPage(self) -> int:  # noqa: N802 - QML property naming
        return self._current_page

    @Property(str, notify=currentPageChanged)
    def currentPageTitle(self) -> str:  # noqa: N802 - QML property naming
        return NAVIGATION_ITEMS[self._current_page][0]

    @Property(bool, notify=navigationCollapsedChanged)
    def navigationCollapsed(self) -> bool:  # noqa: N802
        return self._navigation_collapsed

    @Property(bool, notify=reduceMotionChanged)
    def reduceMotion(self) -> bool:  # noqa: N802
        return self._reduce_motion

    @Property(str, notify=uiScaleChanged)
    def uiScale(self) -> str:  # noqa: N802 - QML property naming
        return self._ui_scale

    @Property(float, notify=uiScaleChanged)
    def uiScaleFactor(self) -> float:  # noqa: N802 - QML property naming
        return 1.0 if self._ui_scale == "auto" else int(self._ui_scale) / 100.0

    @Property(str, notify=typographyChanged)
    def interfaceFontFamily(self) -> str:  # noqa: N802
        return self._interface_font_family

    @Property(int, notify=typographyChanged)
    def interfaceFontSize(self) -> int:  # noqa: N802
        return self._interface_font_size

    @Property(str, notify=typographyChanged)
    def monospaceFontFamily(self) -> str:  # noqa: N802
        return self._monospace_font_family

    @Property(int, notify=typographyChanged)
    def monospaceFontSize(self) -> int:  # noqa: N802
        return self._monospace_font_size

    @Property(bool, notify=typographyChanged)
    def wordWrap(self) -> bool:  # noqa: N802
        return self._word_wrap

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

    @Slot(str)
    def setTheme(self, theme_id: str) -> None:  # noqa: N802
        selected = "dark_orange" if theme_id == "dark_orange" else "light"
        if selected == self._theme_id:
            return
        self._theme_id = selected
        self._palette_cache = None
        self._preferences.setValue("appearance/theme", selected)
        self._preferences.sync()
        self.themeChanged.emit()

    @Slot()
    def toggleTheme(self) -> None:  # noqa: N802
        self.setTheme("light" if self._theme_id == "dark_orange" else "dark_orange")

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
                dark=self._theme_id == "dark_orange",
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
        highlighter = CodeSyntaxHighlighter(document, str(language or ""))
        highlighter.setParent(document)

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

    @Slot(bool)
    def setReduceMotion(self, enabled: bool) -> None:  # noqa: N802
        selected = bool(enabled)
        if selected == self._reduce_motion:
            return
        self._reduce_motion = selected
        self._preferences.setValue("appearance/reduce_motion", selected)
        self._preferences.sync()
        self.reduceMotionChanged.emit()

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

    @Slot(str, int, str, int, bool)
    def setTypography(
        self,
        interface_family: str,
        interface_size: int,
        monospace_family: str,
        monospace_size: int,
        word_wrap: bool,
    ) -> None:  # noqa: N802
        interface = (
            interface_family
            if interface_family in INTERFACE_FONT_OPTIONS
            else "Segoe UI"
        )
        monospace = (
            monospace_family
            if monospace_family in MONOSPACE_FONT_OPTIONS
            else "Consolas"
        )
        values = (
            interface,
            max(11, min(22, int(interface_size))),
            monospace,
            max(10, min(20, int(monospace_size))),
            bool(word_wrap),
        )
        current = (
            self._interface_font_family,
            self._interface_font_size,
            self._monospace_font_family,
            self._monospace_font_size,
            self._word_wrap,
        )
        if values == current:
            return
        (
            self._interface_font_family,
            self._interface_font_size,
            self._monospace_font_family,
            self._monospace_font_size,
            self._word_wrap,
        ) = values
        for key, value in (
            ("appearance/interface_font_family", interface),
            ("appearance/interface_font_size", values[1]),
            ("appearance/monospace_font_family", monospace),
            ("appearance/monospace_font_size", values[3]),
            ("appearance/word_wrap", values[4]),
        ):
            self._preferences.setValue(key, value)
        self._preferences.sync()
        self.typographyChanged.emit()

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

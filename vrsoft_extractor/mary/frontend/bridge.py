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
from ..chat_widgets import CodeSyntaxHighlighter, apply_message_document_style
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


UI_SCALE_OPTIONS = ("auto", "100", "105", "110", "125", "150")
UI_SCALE_PREFERENCE_VERSION = 2


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
        self._palette_cache: dict[str, str] | None = None
        page_names = [title for title, _icon in NAVIGATION_ITEMS]
        try:
            self._current_page = page_names.index(initial_page)
        except ValueError:
            self._current_page = 0
        self._styling_document = False

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

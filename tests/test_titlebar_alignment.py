from unittest.mock import patch
import pytest
from PySide6.QtGui import QColor
from test_chat_presentation import (
    QApplication, QSettings, QTest, QObject, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
)


def _find_items(item, name):
    result = [item] if item.objectName() == name else []
    for child in item.childItems():
        result.extend(_find_items(child, name))
    return result

@pytest.mark.qml
def test_titlebar_and_settings_hub_divider_pixel_alignment(tmp_path):
    _app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    frontend = FrontendBridge(settings, prefs, initial_page="Configurações")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    engine = None
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1200)
            window.setHeight(800)
            QTest.qWait(400)

            title_bar = window.findChild(QObject, "vrTitleBar")
            assert title_bar is not None
            hub_page = window.findChild(QObject, "settingsHub")
            assert hub_page is not None
            nav = window.findChild(QObject, "settingsNavigation")
            assert nav is not None

            # Title bar sidebar width matches settingsNavigation width + 4
            nav_w = nav.property("width")
            tb_sidebar_w = title_bar.property("sidebarWidth")
            assert tb_sidebar_w == nav_w + 4

            # Title bar hairline border is inside sidebarBg anchored at right (width: 1),
            # so its X coordinate in window coordinates is (sidebarWidth - 1).
            # In SettingsHub, the SplitHandle is 7px wide, centerLine is centered at offset 3
            # relative to the nav width (so its X coordinate is nav_w + 3).
            # Therefore: (nav_w + 4) - 1 == nav_w + 3. Perfect alignment!
            tb_divider_x = tb_sidebar_w - 1
            hub_divider_x = nav_w + 3
            assert tb_divider_x == hub_divider_x

            hub_center_line = window.findChild(QObject, "hubCenterLine")
            assert hub_center_line is not None
            assert hub_center_line.property("height") > 0
            assert hub_center_line.property("width") == 1
    finally:
        if window is not None:
            window.close()
        if engine is not None:
            engine.deleteLater()
        studio.close()
        chat.close()

@pytest.mark.qml
def test_titlebar_and_chat_sidebar_divider_pixel_alignment(tmp_path):
    _app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    frontend = FrontendBridge(settings, prefs, initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    engine = None
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1200)
            window.setHeight(800)
            QTest.qWait(400)

            title_bar = window.findChild(QObject, "vrTitleBar")
            assert title_bar is not None
            chat_page = window.findChild(QObject, "chatPage")
            assert chat_page is not None
            chat_sidebar = window.findChild(QObject, "conversationSidebar")
            assert chat_sidebar is not None

            tb_sidebar_w = title_bar.property("sidebarWidth")
            sb_w = chat_sidebar.property("width")
            assert tb_sidebar_w == sb_w + 4

            tb_divider_x = tb_sidebar_w - 1
            chat_divider_x = sb_w + 3
            assert tb_divider_x == chat_divider_x

            chat_center_line = window.findChild(QObject, "chatCenterLine")
            assert chat_center_line is not None
            assert chat_center_line.property("height") > 0
            assert chat_center_line.property("width") == 1
    finally:
        if window is not None:
            window.close()
        if engine is not None:
            engine.deleteLater()
        studio.close()
        chat.close()


@pytest.mark.qml
def test_chat_divider_slices_match_each_boundary_background(tmp_path):
    _app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    frontend = FrontendBridge(settings, prefs, initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    engine = None
    try:
        with patch.object(chat, "refreshModels"), patch.object(chat, "refreshUsageLimits"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(900)
            frontend.setReduceMotion(True)
            QTest.qWait(400)

            chat_page = window.findChild(QObject, "chatPage")
            assert chat_page is not None
            chat_page.setProperty("surfaceVisible", True)
            QTest.qWait(250)

            panel = window.findChild(QObject, "surfacePanel")
            assert panel is not None and panel.isVisible()
            panel_x = panel.mapToItem(window.contentItem(), 0, 0).x()
            assert panel_x > 0

            left_slices = _find_items(window.contentItem(), "chatSplitLeftSlice")
            right_slices = _find_items(window.contentItem(), "chatSplitRightSlice")
            assert len(left_slices) == len(right_slices) == 2

            def window_x(rect):
                return rect.mapToItem(window.contentItem(), 0, 0).x()

            # The handle left of the panel mirrors its slices: chat on the
            # left, sidebar-colored panel on the right, without a color band.
            surface_left = max(left_slices, key=window_x)
            surface_right = max(right_slices, key=window_x)
            assert window_x(surface_left) + surface_left.width() <= panel_x
            assert QColor(frontend.palette["chatBackground"]) == surface_left.property("color")
            assert QColor(frontend.palette["chatSidebar"]) == surface_right.property("color")

            # The sidebar handle keeps the default sidebar|chat pair.
            sidebar_left = min(left_slices, key=window_x)
            sidebar_right = min(right_slices, key=window_x)
            assert QColor(frontend.palette["chatSidebar"]) == sidebar_left.property("color")
            assert QColor(frontend.palette["chatBackground"]) == sidebar_right.property("color")

            frontend.setTheme("light")
            QTest.qWait(150)
            assert QColor(frontend.palette["chatBackground"]) == surface_left.property("color")
            assert QColor(frontend.palette["chatSidebar"]) == surface_right.property("color")
    finally:
        if window is not None:
            window.close()
        if engine is not None:
            engine.deleteLater()
        studio.close()
        chat.close()

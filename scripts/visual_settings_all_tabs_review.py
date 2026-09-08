"""Offline render and warning checker for all tabs in SettingsPage."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import ExitStack
import json

from visual_chat_review import (
    QApplication, QSettings, QObject, QTest, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
    _apply_application_font, repaint_icons, find_items, Qt,
)
from PySide6.QtCore import QPointF

def check_geometry(item, viewport_width):
    """Catch collapsed cards and overlapping layout children, even without QML warnings."""
    if not item.isVisible():
        return
    name = item.objectName() or item.metaObject().className()
    if item.objectName().startswith("vrUltra") and item.objectName().endswith("Card"):
        assert item.height() > 30, (name, "collapsed card", item.height())
        for child in item.childItems():
            assert child.y() + child.height() <= item.height() + 1, (name, "content outside card")
    if "Layout" in item.metaObject().className():
        children = [c for c in item.childItems() if c.isVisible() and c.width() > 1 and c.height() > 1]
        for index, child in enumerate(children):
            for other in children[index + 1:]:
                overlap_x = min(child.x() + child.width(), other.x() + other.width()) - max(child.x(), other.x())
                overlap_y = min(child.y() + child.height(), other.y() + other.height()) - max(child.y(), other.y())
                assert overlap_x < 1 or overlap_y < 1, (name, "overlap", child.objectName(), other.objectName())
    if item.objectName() in {"rootField", "movideskEmail", "movideskPassword", "endooEmail", "endooPassword", "interfaceFontCombo", "browserZoomCombo", "vrUltraAddReleaseButton"}:
        left = item.mapToScene(QPointF(0, 0)).x()
        assert left >= -1 and left + item.width() <= viewport_width + 1, (name, "horizontal overflow", left, item.width())
        assert item.height() >= 30, (name, "collapsed control")
    for child in item.childItems():
        check_geometry(child, viewport_width)


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".test-tmp/settings_review")
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy")
        prefs = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Configurações")
        frontend.setReduceMotion(True)
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)

        items = [dict(id=p, name=n, enabled=True, available=True,
                      command="C:\\Users\\example\\AppData\\Local\\" + p + "\\bin\\" + p + ".exe",
                      accountStatus="Autenticação OK",
                      description=d)
                 for p, n, d in [("codex", "Codex", "Codex App Server local"),
                                 ("antigravity", "Antigravity", "Antigravity CLI")]]
        studio._providers = items

        with ExitStack() as patches:
            for target, method in [(chat, "refreshModels"), (studio, "refreshProviders")]:
                patches.enter_context(patch.object(target, method))
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [w.toString() for w in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1280)
            window.setHeight(820)
            QTest.qWait(300)

            page = window.findChild(QObject, "settingsPage")
            assert page is not None, "settingsPage not found"

            tab_names = ["0_geral", "1_provedores", "2_vr_ultra", "3_aparencia", "4_browser", "5_arquivados"]

            scenarios = [(1280, 820, "100"), (1920, 1080, "100"), (768, 1024, "100"), (390, 844, "100"), (1280, 820, "150")]
            captures = []
            for theme in ["dark_orange", "light"]:
                frontend.setTheme(theme)
                for width, height, scale in scenarios:
                    window.setWidth(width)
                    window.setHeight(height)
                    frontend.setUiScale(scale)
                    for idx, name in enumerate(tab_names):
                        page.setProperty("tabIndex", idx)
                        QTest.qWait(120)
                        app.processEvents()
                        scroll_name = {0: "generalScroll", 2: "vrUltraSettingsScroll", 3: "appearanceSettingsScroll", 4: "browserSettingsScroll"}.get(idx)
                        scroll = window.findChild(QObject, scroll_name) if scroll_name else None
                        flick = scroll.property("contentItem") if scroll else None
                        if flick:
                            flick.setProperty("contentY", 0)
                        QTest.qWait(30)
                        if idx != 1:
                            try:
                                check_geometry(page, width)
                            except AssertionError:
                                window.grabWindow().save(str(out_dir / "geometry-failure.png"))
                                raise
                        for position in (["top", "bottom"] if flick and flick.property("contentHeight") > flick.property("height") else ["top"]):
                            if position == "bottom":
                                flick.setProperty("contentY", max(0, flick.property("contentHeight") - flick.property("height")))
                            repaint_icons(window.contentItem())
                            QTest.qWait(25)
                            filename = f"{theme}_{width}x{height}_{scale}_{name}_{position}.png"
                            assert window.grabWindow().save(str(out_dir / filename))
                            captures.append(filename)
                        if idx == 5:
                            archive_list = window.findChild(QObject, "archivedList")
                            assert archive_list.property("height") > 100, "Archive list lost its available height"
                    print(f"Verified all tabs: {theme}, {width}x{height}, scale {scale}%", flush=True)

            # Exercise real QML controls and local persistence with disposable preferences.
            window.setWidth(1280)
            window.setHeight(820)
            frontend.setUiScale("100")
            page.setProperty("tabIndex", 2)
            QTest.qWait(80)
            toggle = window.findChild(QObject, "vrUltraSeniorProfileToggle")
            toggle.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            assert chat.seniorProfileEnabled
            picker = window.findChild(QObject, "vrUltraResponseModePicker")
            picker.activated.emit(2)
            assert chat.vrResponseMode == "support"
            page.setProperty("tabIndex", 4)
            window.findChild(QObject, "browserZoomCombo").activated.emit(4)
            assert frontend.browserZoom == "125"

            # Populated, filtered, and restored archive states.
            cid = db.create_conversation("Revisão visual de configurações", "codex", "gpt-5.6", settings.root)
            chat._orchestrator.archive(cid)
            studio.refreshArchived("")
            page.setProperty("tabIndex", 5)
            for width in [1280, 390]:
                window.setWidth(width)
                QTest.qWait(120)
                check_geometry(page, width)
                filename = f"archive-populated-{width}.png"
                assert window.grabWindow().save(str(out_dir / filename))
                captures.append(filename)
            search = window.findChild(QObject, "archivedSearch")
            search.setProperty("text", "sem correspondencia")
            QTest.qWait(240)
            assert archive_list.property("count") == 0
            search.setProperty("text", "")
            QTest.qWait(240)
            assert archive_list.property("count") == 1
            row = find_items(window.contentItem(), "archivedConversationRow")[0]
            def descendants(item):
                for child in item.childItems():
                    yield child
                    yield from descendants(child)
            restore = next(child for child in descendants(row) if child.property("text") == "Restaurar")
            restore.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(80)
            assert archive_list.property("count") == 0

            print(f"Total QML warnings: {len(engine._qml_warnings)}")
            for w in engine._qml_warnings:
                print("WARNING:", w.toString())
            assert len(engine._qml_warnings) == 0, f"Found {len(engine._qml_warnings)} warnings!"
            (out_dir / "results.json").write_text(json.dumps({"captures": captures, "qml_warnings": 0, "geometry": "passed", "controls_and_archive": "passed"}, indent=2), encoding="utf-8")
            print("SUCCESS: All tabs rendered without warnings!")
            window.close()
            studio.close()
            chat.close()

if __name__ == "__main__":
    main()

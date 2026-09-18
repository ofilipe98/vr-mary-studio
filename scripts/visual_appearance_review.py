"""Render Appearance with isolated preferences, including real Settings navigation.

Usage: python scripts/visual_appearance_review.py .test-tmp/appearance-review
The standalone captures match the supplied 1450x1249 reference canvas. The full
window captures check integration with VRStudio's navigation and compact layout.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QPointF, QSettings, QUrl, QMetaObject, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem  # noqa: F401 - registers QQuickItem converters
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge


def find_item(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = find_item(child, name)
        if found is not None:
            return found
    return None


@contextmanager
def appearance_window(root, full=False):
    app = QApplication.instance() or QApplication([])
    previous_font = app.font()
    registered_fonts = []
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "consola.ttf", "consolab.ttf", "arial.ttf"):
        font_path = Path("C:/Windows/Fonts") / name
        if font_path.exists():
            registered_fonts.append(QFontDatabase.addApplicationFont(str(font_path)))
    app.setFont(QFont("Segoe UI"))
    settings = MarySettings(app_dir=root, root=root / "data", old_root=root / "old")
    prefs = QSettings(str(root / "prefs.ini"), QSettings.IniFormat)
    frontend = FrontendBridge(settings, prefs, initial_page="Configurações")
    frontend.setTheme("ocean")
    frontend.setThemeForAppearance("light", "t3-code-light")
    frontend.setUiScale("100")
    warnings = []
    db = chat = studio = None
    if full:
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        chat, studio = ChatBridge(settings, db, prefs), StudioBridge(settings, db, prefs)
        with patch.object(chat, "refreshModels"), patch.object(studio, "refreshProviders"):
            engine = create_engine(frontend, chat, studio)
        warnings.extend(w.toString() for w in engine._qml_warnings)
    else:
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("frontend", frontend)
        qml = (Path(__file__).resolve().parents[1] / "vrsoft_extractor/mary/frontend/qml").as_uri()
        engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
        engine.loadData(f'''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "{qml}/theme"
import "{qml}/settings/appearance"
ApplicationWindow {{
    visible: true; width: 1450; height: 1249; color: Theme.palette.background
    ScrollView {{
        id: scroll; objectName: "appearanceSettingsScroll"
        anchors.fill: parent; topPadding: 66; bottomPadding: 44; rightPadding: 8
        contentWidth: availableWidth; clip: true
        Item {{
            width: scroll.availableWidth; implicitHeight: appearance.implicitHeight
            AppearanceSettingsView {{
                id: appearance; anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(848, parent.width - 32)
            }}
        }}
    }}
}}'''.encode(), QUrl.fromLocalFile(str(root / "appearance.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    if full:
        engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
        QTest.qWait(150)
        window.findChild(QObject, "settingsPage").setProperty("tabIndex", 4)
    QTest.qWait(120)
    try:
        yield frontend, engine, window, warnings
    finally:
        if chat:
            chat.close()
        if studio:
            studio.close()
        window.close()
        engine.deleteLater()
        app.processEvents()
        QTest.qWait(20)
        app.setFont(previous_font)
        for font_id in registered_fonts:
            if font_id >= 0:
                QFontDatabase.removeApplicationFont(font_id)


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else ".test-tmp/appearance-review")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    captures, warnings = [], []
    for full in (False, True):
        with TemporaryDirectory() as tmp, appearance_window(Path(tmp), full) as (frontend, engine, window, messages):
            for theme, width, height, scale in [
                ("t3-code", 1450, 1249, "100"), ("t3-code", 390, 844, "100"),
                ("t3-code", 1280, 820, "150"), ("t3-code", 390, 844, "150"),
                ("ocean", 1450, 1249, "100"), ("t3-code-light", 1450, 1249, "100"),
                ("ocean", 768, 1024, "100"), ("ocean", 390, 844, "100"),
                ("t3-code-light", 390, 844, "100"), ("ocean", 1280, 820, "150"),
            ]:
                frontend.setTheme(theme); frontend.setUiScale(scale)
                window.setWidth(width); window.setHeight(height)
                QTest.qWait(150)
                scroll = window.findChild(QObject, "appearanceSettingsScroll")
                flick = scroll.property("contentItem")
                for advanced in (False, True):
                    frontend.setTypographyAdvanced(advanced)
                    QTest.qWait(80)
                    for position in ("top", "bottom"):
                        flick.setProperty("contentY", 0 if position == "top" else max(0, flick.property("contentHeight") - flick.property("height")))
                        QTest.qWait(40)
                        name = f'{"app" if full else "reference"}-{theme}-{width}-{scale}-{"advanced" if advanced else "simple"}-{position}.png'
                        assert window.grabWindow().save(str(output / name))
                        captures.append(name)
                    view = find_item(window.contentItem(), "appearanceSettingsView")
                    for control_name in ("interfaceFontFamily", "interfaceFontSize", "codeFontFamily", "codeFontSize", "environmentIdentificationCombo"):
                        control = find_item(view, control_name)
                        left = control.mapToScene(QPointF(0, 0)).x()
                        assert left >= 0 and left + control.width() <= window.width(), (name, control_name, left, control.width())
                print(f'Checked {"app" if full else "reference"}: {theme}, {width}px, {scale}%', flush=True)
            frontend.setTheme("t3-code")
            frontend.setUiScale("100")
            for width in (1280, 390):
                window.setWidth(width); window.setHeight(844)
                QTest.qWait(80)
                for name in ("themeEditorModal", "themeImportModal", "themeExportModal"):
                    modal = window.findChild(QObject, name)
                    QMetaObject.invokeMethod(modal, "open")
                    QTest.qWait(80)
                    filename = f'{"app" if full else "reference"}-{name}-{width}.png'
                    assert window.grabWindow().save(str(output / filename))
                    captures.append(filename)
                    assert modal.property("x") >= 0 and modal.property("y") >= 0
                    assert modal.property("width") <= width
                    QTest.keyClick(window, Qt.Key_Escape)
                    QTest.qWait(40)
                    assert not modal.property("visible")
            if not full:
                # Match the exact saved typography state in the supplied reference.
                window.setWidth(1450); window.setHeight(1249)
                frontend.setTypographyAdvanced(False)
                frontend.setInterfaceTypography("Segoe UI", 16)
                QTest.qWait(100)
                flick = window.findChild(QObject, "appearanceSettingsScroll").property("contentItem")
                for position in ("top", "bottom"):
                    flick.setProperty("contentY", 0 if position == "top" else max(0, flick.property("contentHeight") - flick.property("height")))
                    QTest.qWait(50)
                    filename = f"target-{position}.png"
                    assert window.grabWindow().save(str(output / filename))
                    captures.append(filename)
            warnings.extend(messages)
    (output / "review.json").write_text(json.dumps({"captures": captures, "warnings": warnings}, indent=2), encoding="utf-8")
    assert not warnings, warnings
    print(f"{len(captures)} captures; zero QML warnings", flush=True)
    app.processEvents()


if __name__ == "__main__":
    main()

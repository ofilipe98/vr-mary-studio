"""Offline render of every VrProgressBar state for visual review.

Renders determinate values (0, 2, 5, 42.5, 100), the indeterminate beam, the
reduce-motion fallback, the pace marker and the semantic thresholds in both
themes and two widths, then asserts no QML warnings were emitted.
"""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine, _apply_application_font
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge

QML_DIR = Path(__file__).resolve().parents[1] / "vrsoft_extractor/mary/frontend/qml"

HARNESS_QML = """
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import "components"
import "theme"

Window {
    id: harness
    objectName: "progressHarness"
    width: 640
    height: body.implicitHeight + 48
    color: Theme.palette.background

    ColumnLayout {
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 24
        spacing: Theme.spaceMd

        Text {
            text: "Determinada com percentual"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeCaption
        }

        Repeater {
            model: [0, 2, 5, 42.5, 100]
            delegate: ColumnLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.spaceXs

                Text {
                    text: "valor " + modelData
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMicro
                }

                VrProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: 100
                    value: modelData
                    showPercentage: true
                }
            }
        }

        Text {
            text: "Indeterminada e fallback sem movimento"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeCaption
        }

        VrProgressBar {
            Layout.fillWidth: true
            indeterminate: true
        }

        Text {
            text: "Marcador de ritmo e limiares semânticos"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeCaption
        }

        VrProgressBar {
            Layout.fillWidth: true
            from: 0
            to: 100
            value: 35
            markerPosition: 0.6
            warningThreshold: 0.3
            dangerThreshold: 0.6
        }
    }
}
"""


def main():
    output = Path(
        sys.argv[1] if len(sys.argv) > 1 else ".test-tmp/progress-review"
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        settings = MarySettings(app_dir=root, root=root / "data", old_root=root / "old")
        prefs = QSettings(str(root / "prefs.ini"), QSettings.IniFormat)
        db = MaryDatabase(
            settings.database_path, root=settings.root, backup_portable_migration=False
        )
        frontend = FrontendBridge(settings, prefs, theme_override="dark_orange")
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)
        window = None
        try:
            with patch.object(chat, "refreshModels"):
                engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [str(w) for w in engine._qml_warnings]

            component = QQmlComponent(engine)
            component.setData(
                HARNESS_QML.encode("utf-8"),
                QUrl.fromLocalFile(str(QML_DIR / "_progress_review_harness.qml")),
            )
            assert not component.isError(), [
                error.toString() for error in component.errors()
            ]
            window = component.create()
            assert window is not None
            window.show()

            for theme in ("dark_orange", "light"):
                frontend.setTheme(theme)
                for width in (640, 390):
                    window.setWidth(width)
                    QTest.qWait(200)
                    name = f"progress-{theme}-{width}.png"
                    assert window.grabWindow().save(str(output / name)), name
                frontend.setReduceMotion(True)
                QTest.qWait(120)
                name = f"progress-{theme}-{width}-reduce-motion.png"
                assert window.grabWindow().save(str(output / name)), name
                frontend.setReduceMotion(False)

            warnings = [warning.toString() for warning in engine._qml_warnings]
            (output / "qml-warnings.txt").write_text(
                "\n".join(warnings), encoding="utf-8"
            )
            assert not warnings, warnings
        finally:
            if window is not None:
                window.close()
            chat.close()
            studio.close()
            app.processEvents()
    print(output)


if __name__ == "__main__":
    main()

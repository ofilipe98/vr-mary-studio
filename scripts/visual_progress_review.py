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

from PySide6.QtCore import QObject, QSettings, QUrl
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
        frontend = FrontendBridge(
            settings, prefs, theme_override="dark_orange", initial_page="Configurações"
        )
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)
        harness = None
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
            harness = component.create()
            assert harness is not None
            harness.show()

            for theme in ("dark_orange", "light"):
                frontend.setTheme(theme)
                for width in (640, 390):
                    harness.setWidth(width)
                    QTest.qWait(200)
                    name = f"progress-{theme}-{width}.png"
                    assert harness.grabWindow().save(str(output / name)), name
                    frontend.setReduceMotion(True)
                    QTest.qWait(120)
                    name = f"progress-{theme}-{width}-reduce-motion.png"
                    assert harness.grabWindow().save(str(output / name)), name
                    frontend.setReduceMotion(False)
            harness.close()
            harness = None

            # Real settings cards while their operations are running.
            window = engine.rootObjects()[0]
            window.setWidth(1280)
            window.setHeight(900)
            window.show()

            class _IdleThread:
                def is_alive(self):
                    return False

                def join(self, timeout=None):
                    return None

            chat._apps_catalog_thread = _IdleThread()
            chat._apps_catalog_phase = "indexing_coverage"
            chat._apps_catalog_progress_current = 4
            chat._apps_catalog_progress_total = 10
            chat._decompiled_export_running = True
            chat._decompiled_export_progress = 42.5
            chat._decompiled_export_processed = 425
            chat._decompiled_export_total = 1000
            chat._decompiled_import_running = True
            chat._decompiled_import_progress = 42.5
            chat._decompiled_import_processed = 425
            chat._decompiled_import_total = 1000
            chat._knowledge_transfer_running = True
            chat._knowledge_transfer_operation = "export_knowledge"
            chat._knowledge_transfer_progress = 42.5
            chat._knowledge_transfer_processed = 425
            chat._knowledge_transfer_total = 1000
            chat._release_snapshot_status = "Exportando conhecimento — 425/1.000 itens"
            chat._application_import_preview = {"state": "running"}
            chat._release_snapshot_running = True
            chat._release_snapshot_progress = 42.5
            chat.stateChanged.emit()
            settings_page = window.findChild(QObject, "settingsPage")
            assert settings_page is not None
            for theme in ("dark_orange", "light"):
                frontend.setTheme(theme)
                for tab, name in (
                    (8, "knowledge-progress"),
                    (3, "applications-progress"),
                ):
                    settings_page.setProperty("tabIndex", tab)
                    QTest.qWait(250)
                    filename = f"{name}-{theme}.png"
                    assert window.grabWindow().save(str(output / filename)), filename

            warnings = [warning.toString() for warning in engine._qml_warnings]
            (output / "qml-warnings.txt").write_text(
                "\n".join(warnings), encoding="utf-8"
            )
            assert not warnings, warnings
        finally:
            if harness is not None:
                harness.close()
            if window is not None:
                window.close()
            chat.close()
            studio.close()
            app.processEvents()
    print(output)


if __name__ == "__main__":
    main()

"""Render production V2 QML components in an isolated, offline application."""
from pathlib import Path
import json
import os
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QSG_RHI_BACKEND', 'software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
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


def main():
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)
    with TemporaryDirectory() as temp:
        root = Path(temp)
        settings = MarySettings(app_dir=root, root=root/'VRProject', old_root=root/'legacy')
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        prefs = QSettings(str(root/'preferences.ini'), QSettings.IniFormat)
        frontend = FrontendBridge(settings, prefs, theme_override='dark_orange', initial_page='Chat VR')
        frontend.setReduceMotion(True)
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)
        with patch.object(chat, 'refreshModels'):
            engine = create_engine(frontend, chat, studio)
            qml_root = Path(__file__).resolve().parents[1]/'vrsoft_extractor/mary/frontend/qml'
            component = QQmlComponent(engine)
            component.setData(b'''
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import "components"
import "theme"
Window {
    id: reviewWindow
    visible: true
    width: 700; height: 580
    color: Theme.palette.background
    property var research: ({runId: "fixture", callsRemaining: 8, secondsRemaining: 130})
    ColumnLayout {
        anchors { fill: parent; margins: 20 }
        spacing: 24
        VrRetrievalSettings { Layout.fillWidth: true; bridge: chat.retrievalSettings }
        Item { Layout.fillHeight: true }
        VrResearchResume { Layout.fillWidth: true; research: reviewWindow.research }
    }
}
''', QUrl.fromLocalFile(str(qml_root/'V2Review.qml')))
            window = component.create()
            if window is None:
                raise RuntimeError([e.toString() for e in component.errors()])
            records = []
            for theme in ('dark_orange', 'light'):
                frontend.setTheme(theme)
                for width in (700, 390):
                    window.setWidth(width)
                    # Recreate the offscreen surface after resizing; the software
                    # renderer can otherwise retain clipped glyph textures.
                    window.hide()
                    QTest.qWait(30)
                    window.show()
                    for state in ('ready', 'missing-model', 'preparing', 'exhausted', 'publication'):
                        bridge = chat.retrievalSettings
                        bridge._busy = state == 'preparing'
                        bridge._status = {'missing-model': 'Busca textual: modelo local ainda não preparado. Use o botão de preparo para baixar os arquivos.',
                            'preparing': 'Índice: 47%', 'exhausted': 'Orçamento esgotado; os achados foram preservados.'}.get(state, 'Busca textual. Modelo local opcional.')
                        bridge.changed.emit()
                        window.setProperty('research', {'runId':'fixture', 'callsRemaining':0 if state in ('exhausted','publication') else 8,
                            'secondsRemaining':0 if state in ('exhausted','publication') else 130, 'publicationReady':state=='publication'})
                        QTest.qWait(150)
                        name = f'{theme}-{width}-{state}.png'
                        assert window.grabWindow().save(str(output/name))
                        records.append(name)
            warnings = [w.toString() for w in engine._qml_warnings]
            (output/'result.json').write_text(json.dumps({'captures':records,'qml_warnings':warnings}, indent=2), encoding='utf-8')
            print(f'{len(records)} captures; {len(warnings)} QML warnings')
            window.close()
            engine.rootObjects()[0].close()
        studio.close()
        chat.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    main()

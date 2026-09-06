from pathlib import Path
from unittest.mock import patch

from test_chat_presentation import (
    QApplication, QSettings, QTest, QObject, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def test_centered_landing_project_picker_and_image_paste(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / 'VRProject', old_root=tmp_path / 'old')
    prefs = QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    frontend = FrontendBridge(settings, prefs, initial_page='Chat VR', theme_override='dark_orange')
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, 'refreshModels'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(200)
            card = window.findChild(QObject, 'chatComposerCard')
            landing = window.findChild(QObject, 'chatLanding')
            assert 0 < card.y() < window.height() * .7
            assert abs(card.x() + card.width()/2 - landing.x() - landing.width()/2) < 1
            assert abs(card.y() - landing.y() - landing.height() - 24) < 1
            button = window.findChild(QObject, 'landingProjectButton')
            button.click()
            QTest.qWait(100)
            menu = window.findChild(QObject, 'landingProjectMenu')
            assert menu.property('opened')
            window.grabWindow().save(str(tmp_path / 'landing.png'))
            print('SCREENSHOT', tmp_path / 'landing.png')
            window.findChild(QObject, 'landingChooseFolder').click()
            QTest.qWait(100)
            assert window.findChild(QObject, 'addProjectPopup').property('opened')
            project = tmp_path / 'Meu Projeto'
            project.mkdir()
            chat.browseProjectFolder(str(project))
            assert chat.addCurrentProjectFolder()
            window.findChild(QObject, 'addProjectPopup').close()
            QTest.qWait(80)
            assert 'Meu Projeto' in button.property('text')
            editor = window.findChild(QObject, 'chatComposerInput')
            editor.forceActiveFocus()
            picture = QImage(32, 24, QImage.Format_ARGB32)
            picture.fill(Qt.red)
            app.clipboard().setImage(picture)
            QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
            QTest.qWait(80)
            assert len(chat.attachments) == 1
            saved = QImage(chat.attachments[0]['path'])
            assert saved.size() == picture.size()
            assert editor.property('text') == ''
            app.clipboard().setText('Texto colado')
            QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
            assert editor.property('text') == 'Texto colado'
            assert len(chat.attachments) == 1
            image_path = chat.attachments[0]['path']
            cid = db.create_conversation('Imagem', 'codex', 'test', project)
            chat.refresh()
            chat.selectConversationId(cid)
            chat.addDroppedAttachments([image_path])
            editor.setProperty('text', '')
            editor.forceActiveFocus()
            with patch.object(chat._orchestrator, 'send') as send:
                QTest.keyClick(window, Qt.Key_Return)
                assert send.called
                assert send.call_args.kwargs['image_paths'] == [image_path]
            assert not engine._qml_warnings, [w.toString() for w in engine._qml_warnings]
    finally:
        app.clipboard().clear()
        if window:
            window.close()
        studio.close()
        chat.close()

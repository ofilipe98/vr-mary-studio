import pytest

from unittest.mock import patch

from test_chat_presentation import (
    QApplication, QSettings, QTest, QObject, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

pytestmark = pytest.mark.qml


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
            title_bar = window.findChild(QObject, 'vrTitleBar')
            canvas_center = (window.height() - title_bar.height()) / 2
            assert abs(card.y() + card.height()/2 - canvas_center) < 2
            button = window.findChild(QObject, 'landingProjectButton')
            assert button.property('text') == 'Como posso ajudar no projeto VRProject?'
            heading = window.findChild(QObject, 'landingHeadingText')
            link = window.findChild(QObject, 'landingProjectLink')
            assert heading is not None and link is not None
            assert heading.property('lineHeight') == link.property('lineHeight')
            assert abs(button.y() - heading.y()) < 1
            button.click()
            QTest.qWait(100)
            menu = window.findChild(QObject, 'landingProjectMenu')
            assert menu.property('opened')
            window.grabWindow().save(str(tmp_path / 'landing.png'))
            print('SCREENSHOT', tmp_path / 'landing.png')
            assert window.findChild(QObject, 'landingChooseFolder') is None
            window.findChild(QObject, 'landingNewProject').click()
            QTest.qWait(100)
            assert window.findChild(QObject, 'addProjectPopup').property('opened')
            project = tmp_path / 'Meu Projeto'
            project.mkdir()
            chat.browseProjectFolder(str(project))
            assert chat.addCurrentProjectFolder()
            window.findChild(QObject, 'addProjectPopup').close()
            QTest.qWait(80)
            assert button.property('text') == 'Como posso ajudar no projeto Meu Projeto?'
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


def test_settings_lazy_tabs_and_archived_rows_follow_theme(tmp_path):
    from test_chat_presentation import find_items

    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / 'VRProject', old_root=tmp_path / 'old')
    prefs = QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    for index in range(2):
        cid = db.create_conversation(f'Arquivada {index}', 'codex', 'test', settings.root)
        db.update_conversation(cid, archived=1)
    frontend = FrontendBridge(settings, prefs, initial_page='Chat VR', theme_override='dark_orange')
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, 'refreshModels'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            frontend.setCurrentPage(7)
            QTest.qWait(400)
            page = window.findChild(QObject, 'settingsPage')
            providers = window.findChild(QObject, 'providerSettingsLoader')
            ultra = window.findChild(QObject, 'vrUltraSettingsLoader')
            assert not providers.property('active')
            assert not ultra.property('active')
            for tab, loader in ((1, providers), (2, ultra)):
                page.setProperty('tabIndex', tab)
                for _ in range(100):
                    QTest.qWait(10)
                    if loader.property('item') is not None:
                        break
                item = loader.property('item')
                assert item is not None
                page.setProperty('tabIndex', 0)
                app.processEvents()
                assert loader.property('item') is item
            studio.refreshArchived('')
            tabs = window.findChild(QObject, 'settingsTabBar').property('model')
            labels = tabs.toVariant() if hasattr(tabs, 'toVariant') else tabs
            page.setProperty('tabIndex', labels.index('Projetos arquivados'))
            QTest.qWait(100)
            rows = find_items(window.contentItem(), 'archivedConversationRow')
            assert len(rows) == 2
            for theme in ('dark_orange', 'light', 'dark_orange'):
                frontend.setTheme(theme)
                app.processEvents()
                for row in rows:
                    color = row.property('color')
                    if row.property('index') % 2:
                        assert color.name() == frontend.palette['chatSidebar'].lower()
                    else:
                        assert color.alpha() == 0
            assert not engine._qml_warnings, [w.toString() for w in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()


def test_app_opens_on_new_conversation_when_conversations_exist(tmp_path):
    _app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / 'VRProject', old_root=tmp_path / 'old')
    prefs = QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)

    cid = db.create_conversation('Conversa Existente', 'codex', 'test', settings.root)
    db.add_message(cid, 'user', 'Ola mundo')
    db.add_message(cid, 'assistant', 'Ola! Como posso ajudar?')

    frontend = FrontendBridge(settings, prefs, initial_page='Chat VR')
    chat = ChatBridge(settings, db, prefs, open_new_chat=True)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        assert chat.conversationCount == 1
        assert chat.isDraft
        assert not chat.hasSelection
        assert chat.selectedIndex == -1
        assert chat.selectedTitle == 'Nova conversa'
        assert chat.messages.rowCount() == 0

        with patch.object(chat, 'refreshModels'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            QTest.qWait(200)
            landing = window.findChild(QObject, 'chatLanding')
            assert landing is not None
            assert landing.property('visible')
            composer_input = window.findChild(QObject, 'chatComposerInput')
            assert composer_input is not None
            assert composer_input.property('text') == ''
            from test_chat_presentation import find_items
            from PySide6.QtGui import QFont

            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(200)
            titles = find_items(window.contentItem(), 'conversationTitle')
            assert len(titles) == 1
            title = titles[0]
            assert title.property('text') == 'Conversa Existente'
            assert title.property('font').weight() == QFont.Weight.Medium
            chat.selectConversationId(cid)
            QTest.qWait(100)
            title = find_items(window.contentItem(), 'conversationTitle')[0]
            assert title.property('font').weight() == QFont.Weight.Medium
            assert not engine._qml_warnings, [w.toString() for w in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()

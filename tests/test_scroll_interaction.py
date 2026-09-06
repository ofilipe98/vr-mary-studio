"""Real pointer events against the chat viewport, including streaming updates."""
from unittest.mock import patch
import pytest

from test_chat_presentation import (
    QApplication, QSettings, QTest, QObject, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
)
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent, QTextDocument
from vrsoft_extractor.mary.frontend.text_rendering import apply_message_document_style


def test_long_message_formatting_commits_one_layout():
    app = QApplication.instance() or QApplication([])
    document = QTextDocument()
    document.setMarkdown('Texto **formatado** e normal.\n\n' * 500)
    document.setTextWidth(700)
    document.size()
    layouts = []
    document.documentLayout().documentSizeChanged.connect(lambda *args: layouts.append(1))
    apply_message_document_style(document)
    assert len(layouts) == 1


@pytest.mark.parametrize('history_size', [0, 30])
def test_mouse_wheel_and_scrollbar_keep_control_during_updates(tmp_path, history_size):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / 'VRProject', old_root=tmp_path / 'old')
    prefs = QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation('Scroll', 'codex', 'test', settings.root)
    for i in range(history_size):
        db.add_message(cid, 'user' if i % 2 else 'assistant',
                       ('Parágrafo **formatado**.\n\n' * (1 + i % 9)))
    markdown = '# Resposta longa\n\n' + 'Parágrafo para testar a rolagem.\n\n' * 100
    markdown += '\n\n| Etapa | Detalhe |\n|---|---|\n' + '| Compra | Conferir **itens** e fornecedor. |\n' * 20
    db.add_message(cid, 'assistant', markdown)
    frontend = FrontendBridge(settings, prefs, initial_page='Chat VR')
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, 'refreshModels'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(350)
            timeline = window.findChild(QObject, 'messageList')
            bar = window.findChild(QObject, 'messageScrollBar')
            timeline.setProperty('followTail', False)
            # Traverse the entire mixed-height history, not just one response.
            # Neither the document height nor thumb size may change on scroll.
            height = timeline.property('contentHeight')
            thumb_size = bar.property('size')
            for step in range(11):
                timeline.setProperty('contentY', (height - timeline.height()) * step / 10)
                QTest.qWait(40)
                assert abs(timeline.property('contentHeight') - height) < 1
                assert abs(bar.property('size') - thumb_size) < .001
            timeline.setProperty('contentY', 500)
            QTest.qWait(150)

            def wheel(angle, pixel=0):
                local = timeline.mapToScene(QPointF(timeline.width() / 2, timeline.height() / 2))
                event = QWheelEvent(local, QPointF(window.mapToGlobal(local.toPoint())),
                                    QPoint(0, pixel), QPoint(0, angle), Qt.NoButton,
                                    Qt.NoModifier, Qt.NoScrollPhase, False)
                QApplication.sendEvent(window, event)
                immediate_y = timeline.property('contentY')
                samples = [immediate_y]
                for _ in range(8):
                    QTest.qWait(20)
                    samples.append(timeline.property('contentY'))
                return samples

            before = timeline.property('contentY')
            samples = wheel(-120)
            assert samples[0] == before
            assert len(set(samples)) >= 3
            assert all(a <= b for a, b in zip(samples, samples[1:]))
            assert 20 < samples[-1] - before < 100
            assert timeline.property('contentY') > before + 20
            before = timeline.property('contentY')
            samples = wheel(120)
            assert all(a >= b for a, b in zip(samples, samples[1:]))
            assert timeline.property('contentY') < before - 20
            before = timeline.property('contentY')
            assert wheel(0, -75)[0] > before + 60
            assert timeline.property('contentY') > before + 60

            # Start pinned at the bottom, grab the thumb, then stream new text.
            timeline.setProperty('followTail', True)
            timeline.positionViewAtEnd()
            QTest.qWait(100)
            thumb_y = (bar.property('visualPosition') + bar.property('visualSize') / 2) * bar.height()
            start = bar.mapToScene(QPointF(bar.width() / 2, thumb_y)).toPoint()
            end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() / 3)).toPoint()
            QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
            QTest.mouseMove(window, end, 20)
            QTest.qWait(50)
            assert bar.property('pressed')
            assert not timeline.property('followTail')
            before = timeline.property('contentY')
            chat.messages.update_last(content=markdown + '\nNova linha.', displayContent=markdown + '\nNova linha.')
            QTest.qWait(150)
            assert abs(timeline.property('contentY') - before) < 5
            QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
            assert not timeline.property('followTail')
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()

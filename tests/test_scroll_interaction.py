"""Real pointer events against the chat viewport, including streaming updates."""
from unittest.mock import patch
import pytest

from test_chat_presentation import (
    QApplication, QSettings, QTest, QObject, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine, find_items,
)
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent, QTextDocument
from vrsoft_extractor.mary.frontend.text_rendering import apply_message_document_style


pytestmark = pytest.mark.qml


def test_long_message_formatting_commits_one_layout():
    _app = QApplication.instance() or QApplication([])
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
    _app = QApplication.instance() or QApplication([])
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
        with patch.object(chat, 'refreshModels'), patch.object(chat, 'refreshUsageLimits'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(350)
            # Long messages start collapsed; expand to exercise scrolling
            # over the full-height content this test targets.
            for toggle in find_items(window.contentItem(), "messageExpandButton"):
                if toggle.property("visible"):
                    toggle.click()
                    QTest.qWait(80)
            QTest.qWait(150)
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


def test_composer_restores_expanded_at_page_end_while_turn_running(tmp_path):
    """T3 parity: reaching the timeline end lifts the resting composer even
    while the turn is still streaming; a running turn never rests it by itself."""
    _app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / 'VRProject', old_root=tmp_path / 'old')
    prefs = QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation('RestoreAtEnd', 'codex', 'test', settings.root)
    for i in range(12):
        db.add_message(cid, 'user' if i % 2 else 'assistant', ('Mensagem no historico.\n\n' * 6))
    frontend = FrontendBridge(settings, prefs, initial_page='Chat VR')
    frontend.setReduceMotion(True)
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, 'refreshModels'), patch.object(chat, 'refreshUsageLimits'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1000)
            window.setHeight(600)
            QTest.qWait(350)
            timeline = window.findChild(QObject, 'messageList')
            composer = window.findChild(QObject, 'chatComposerCard')
            compact_height = composer.property('compactHeight')
            normal_height = composer.property('normalHeight')

            chat._active_turns.add(cid)
            chat.stateChanged.emit()
            QTest.qWait(200)
            assert chat.turnRunning

            # Pinned at the end with a running turn: the composer stays expanded.
            timeline.setProperty('followTail', True)
            timeline.positionViewAtEnd()
            QTest.qWait(300)
            assert composer.property('isAtBottom')
            assert not composer.property('isCompact')
            assert abs(composer.height() - normal_height) < 1

            # Scrolling away rests it while the turn keeps running.
            max_y = timeline.property('contentHeight') - timeline.property('height')
            timeline.setProperty('followTail', False)
            timeline.setProperty('contentY', max_y - 120)
            QTest.qWait(300)
            assert not composer.property('isAtBottom')
            assert composer.property('isCompact')
            assert abs(composer.height() - compact_height) < 1

            # Returning to the end restores it without stopping the turn.
            timeline.positionViewAtEnd()
            timeline.setProperty('followTail', True)
            QTest.qWait(300)
            assert chat.turnRunning
            assert composer.property('isAtBottom')
            assert not composer.property('isCompact')
            assert abs(composer.height() - normal_height) < 1
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window is not None:
            window.close()
        studio.close()
        chat.close()


@pytest.mark.parametrize('reduce_motion', [False, True])
def test_composer_expands_only_when_reaching_bottom_of_page(tmp_path, reduce_motion):
    _app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / 'VRProject', old_root=tmp_path / 'old')
    prefs = QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation('ExpandAtBottom', 'codex', 'test', settings.root)
    for i in range(10):
        db.add_message(cid, 'user' if i % 2 else 'assistant', ('Mensagem no historico.\n\n' * 5))
    frontend = FrontendBridge(settings, prefs, initial_page='Chat VR')
    frontend.setReduceMotion(reduce_motion)
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, 'refreshModels'), patch.object(chat, 'refreshUsageLimits'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1000)
            window.setHeight(600)
            QTest.qWait(350)
            timeline = window.findChild(QObject, 'messageList')
            composer = window.findChild(QObject, 'chatComposerCard')

            timeline.setProperty('followTail', True)
            timeline.positionViewAtEnd()
            QTest.qWait(300)
            compact_height = composer.property('compactHeight')
            normal_height = composer.property('normalHeight')
            assert abs(composer.height() - normal_height) < 1
            heights = []
            composer.heightChanged.connect(lambda: heights.append(composer.height()))

            max_y = timeline.property('contentHeight') - timeline.property('height')
            timeline.setProperty('followTail', False)
            timeline.setProperty('contentY', max_y - 60)
            QTest.qWait(300)
            assert not composer.property('isAtBottom')
            assert composer.property('isCompact')
            assert abs(composer.height() - compact_height) < 1
            compact_surface_height = composer.property('compactSurfaceHeight')
            surface = window.findChild(QObject, 'chatComposerSurface')
            tray = window.findChild(QObject, 'chatComposerControlsBox')
            assert compact_height > compact_surface_height
            assert surface is not None
            assert tray is not None
            assert tray.property('visible')
            assert tray.property('opacity') > 0.99
            assert surface.height() < composer.height()
            assert tray.y() < surface.height()
            assert tray.y() + tray.height() <= composer.height() + 1
            assert abs((tray.y() + tray.height()) - composer.height()) < 1
            assert bool(any(compact_height + 1 < h < normal_height - 1 for h in heights)) == (not reduce_motion)
            assert all(a >= b for a, b in zip(heights, heights[1:]))
            assert abs(timeline.property('contentY') - (max_y - 60)) < 1

            # Retraído: o anel do VR Ultra sai de cena para não desenhar sobre
            # a bandeja de controles.
            chat.setVrMode('ultra')
            QTest.qWait(80)
            ultra_border = window.findChild(QObject, 'chatUltraBorder')
            assert ultra_border is not None
            assert not ultra_border.property('visible')
            chat.setVrMode('off')
            QTest.qWait(80)

            heights.clear()
            timeline.positionViewAtEnd()
            timeline.setProperty('followTail', True)
            QTest.qWait(300)
            assert composer.property('isAtBottom')
            assert not composer.property('isCompact')
            assert abs(composer.height() - normal_height) < 1
            # Expandido: card único; a linha de controles fica integrada à
            # base da superfície, sem bandeja separada abaixo do composer.
            assert abs(surface.height() - composer.height()) < 1
            assert 0 < tray.y()
            # T3 Code footer uses pb-4 (16px) below the integrated controls.
            assert abs((tray.y() + tray.height()) - (composer.height() - 16)) < 1
            assert tray.x() >= 0
            assert tray.x() + tray.width() <= surface.width() + 1
            assert bool(any(compact_height + 1 < h < normal_height - 1 for h in heights)) == (not reduce_motion)
            assert all(a <= b for a, b in zip(heights, heights[1:]))
            # Expandido: o anel do VR Ultra volta a envolver o card inteiro.
            chat.setVrMode('ultra')
            QTest.qWait(80)
            assert ultra_border.property('visible')
            assert abs(ultra_border.width() - (composer.width() + 8)) < 1
            assert abs(ultra_border.height() - (composer.height() + 8)) < 1
            assert abs((ultra_border.x() + ultra_border.width() / 2)
                       - (composer.x() + composer.width() / 2)) < 1
            assert abs((ultra_border.y() + ultra_border.height() / 2)
                       - (composer.y() + composer.height() / 2)) < 1
            chat.setVrMode('off')
            QTest.qWait(80)
            assert not ultra_border.property('visible')
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window is not None:
            window.close()
        studio.close()
        chat.close()


def test_composer_expands_on_focus_while_scrolled_up_without_jumping_to_end(tmp_path):
    _app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / 'VRProject', old_root=tmp_path / 'old')
    prefs = QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation('ExpandInPlace', 'codex', 'test', settings.root)
    for i in range(12):
        db.add_message(cid, 'user' if i % 2 else 'assistant', ('Mensagem no historico.\\n\\n' * 6))
    frontend = FrontendBridge(settings, prefs, initial_page='Chat VR')
    frontend.setReduceMotion(True)
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        with patch.object(chat, 'refreshModels'), patch.object(chat, 'refreshUsageLimits'):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1000)
            window.setHeight(600)
            QTest.qWait(350)
            timeline = window.findChild(QObject, 'messageList')
            composer = window.findChild(QObject, 'chatComposerCard')
            composer_input = window.findChild(QObject, 'chatComposerInput')

            timeline.setProperty('followTail', True)
            timeline.positionViewAtEnd()
            QTest.qWait(300)
            assert composer.property('isAtBottom')
            assert not composer.property('isCompact')

            max_y = timeline.property('contentHeight') - timeline.property('height')
            target_y = max_y - 120
            timeline.setProperty('followTail', False)
            timeline.setProperty('contentY', target_y)
            QTest.qWait(300)
            assert not composer.property('isAtBottom')
            assert composer.property('isCompact')
            compact_height = composer.property('compactHeight')
            normal_height = composer.property('normalHeight')
            assert abs(composer.height() - compact_height) < 1

            composer_input.forceActiveFocus()
            QTest.qWait(300)

            assert composer_input.property('activeFocus')
            assert not composer.property('isCompact')
            assert abs(composer.height() - normal_height) < 1
            assert abs(timeline.property('contentY') - target_y) < 1
            assert not timeline.property('followTail')
            assert not composer.property('isAtBottom')

            timeline.forceActiveFocus()
            QTest.qWait(300)
            assert not composer_input.property('activeFocus')
            assert composer.property('isCompact')
            assert abs(composer.height() - compact_height) < 1
            assert abs(timeline.property('contentY') - target_y) < 1

            composer_input.setProperty('text', 'Ola Mary')
            QTest.qWait(100)
            assert not composer.property('isCompact')
            assert abs(composer.height() - normal_height) < 1
            assert abs(timeline.property('contentY') - target_y) < 1

            pill = window.findChild(QObject, 'scrollToEndPill')
            pill.jump()
            QTest.qWait(300)
            assert composer.property('isAtBottom')
            assert not composer.property('isCompact')
            assert timeline.property('followTail')
            assert not engine._qml_warnings, [x.toString() for x in engine._qml_warnings]
    finally:
        if window is not None:
            window.close()
        studio.close()
        chat.close()

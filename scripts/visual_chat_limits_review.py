"""Offline visual regression checks for the composer border and usage panel."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sys
import time

from visual_chat_review import (
    QApplication, QSettings, QObject, QTest, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
    _apply_application_font, repaint_icons, find_items,
)
from PySide6.QtCore import QPointF, QPoint, Qt


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else '.test-tmp/chat-refinement')
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)
    results = []
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = MarySettings(app_dir=root, root=root / 'VRProject', old_root=root / 'old')
        prefs = QSettings(str(root / 'ui.ini'), QSettings.IniFormat)
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        frontend = FrontendBridge(settings, prefs, initial_page='Chat VR', theme_override='dark_orange')
        frontend.setReduceMotion(True)
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)
        accounts = [dict(provider='codex', account=name, plan='plus', windows=[
            dict(label='Session', remainingPercent=percent, resetInText='resets in 2h 58m',
                 resetAt=time.time() + 10680, windowDurationMins=300),
            dict(label='Weekly', remainingPercent=weekly, resetInText='resets in 5d 20h',
                 resetAt=time.time() + 504000, windowDurationMins=10080),
        ]) for name, percent, weekly in [('Codex_If', 34, 55), ('Codex_VR', 0, 21)]]
        chat._usage_snapshot = dict(status='available', supported=True, accounts=accounts)
        window = None
        try:
            with patch.object(chat, 'refreshModels'), patch.object(chat, 'refreshUsageLimits'), patch.object(studio, 'refreshProviders'):
                engine = create_engine(frontend, chat, studio)
                assert engine.rootObjects(), [w.toString() for w in engine._qml_warnings]
                window = engine.rootObjects()[0]
                chat.setVrMode('ultra')
                QTest.qWait(150)
                card = window.findChild(QObject, 'chatComposerCard')
                landing = window.findChild(QObject, 'chatLanding')
                dialog = window.findChild(QObject, 'vrUsageLimitsDialog')
                arc = window.findChild(QObject, 'chatUltraBorder')
                dialog.open()
                for theme in ('dark_orange', 'light'):
                    frontend.setTheme(theme)
                    for width, height, scale in [(1366, 768, '100'), (1920, 1080, '100'), (768, 1024, '100'), (390, 844, '100'), (1024, 600, '100'), (390, 844, '150'), (1280, 820, '150')]:
                        window.setWidth(width)
                        window.setHeight(height)
                        frontend.setUiScale(scale)
                        QTest.qWait(160)
                        repaint_icons(window.contentItem())
                        QTest.qWait(40)
                        content = dialog.property('contentItem')
                        pos = content.mapToScene(QPointF(0, 0))
                        card_pos = card.mapToScene(QPointF(0, 0))
                        filename = f'limits-{theme}-{width}-{scale}.png'
                        assert window.grabWindow().save(str(output / filename))
                        assert abs(pos.x() + content.width() / 2 - card_pos.x() - card.width() / 2) < 2
                        assert pos.y() >= 0, (filename, pos.y())
                        assert pos.y() + content.height() <= card_pos.y(), filename
                        assert card_pos.y() + card.height() <= height, filename
                        assert landing.y() + landing.height() < card.y() - dialog.property('height'), filename
                        assert pos.x() >= 0 and pos.x() + content.width() <= width, filename
                        tracks = find_items(content, 'usageTrack')
                        assert len(tracks) == 4
                        for track in tracks:
                            assert track.width() >= 40
                            p = track.mapToScene(QPointF(0, 0))
                            assert pos.x() <= p.x() and p.x() + track.width() <= pos.x() + content.width() + 1
                        assert max(t.width() for t in tracks) - min(t.width() for t in tracks) < 1
                        results.append(filename)
                        if content.property('contentHeight') > content.height():
                            content.setProperty('contentY', content.property('contentHeight') - content.height())
                            QTest.qWait(50)
                            last = tracks[-1].mapToScene(QPointF(0, tracks[-1].height()))
                            assert last.y() <= pos.y() + content.height() + 1
                            name = filename.replace('.png', '-bottom.png')
                            window.grabWindow().save(str(output / name))
                            results.append(name)
                            content.setProperty('contentY', 0)
                # Unknown percentages and plans must not become fabricated quotas/subscriptions.
                chat._usage_snapshot = dict(status='available', supported=True, windows=[dict(label='Session', remainingPercent=None)], provider='codex')
                chat.usageLimitsChanged.emit()
                QTest.qWait(80)
                assert find_items(dialog.property('contentItem'), 'usageRemaining')[0].property('text') == '—'
                assert find_items(dialog.property('contentItem'), 'usageAccountTitle')[0].property('text') == 'Codex'
                close = window.findChild(QObject, 'usageLimitsClose')
                point = close.mapToScene(QPointF(close.width() / 2, close.height() / 2))
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
                QTest.qWait(80)
                assert not dialog.property('visible')
                assert abs(card.y() - landing.y() - landing.height() - 24) < 1
                # Inspect several animation positions, including the wrap boundary.
                frontend.setTheme('dark_orange')
                frontend.setUiScale('100')
                window.setWidth(1366)
                window.setHeight(768)
                for phase in (0, 0.25, 0.5, 0.75, 1):
                    arc.setProperty('sweep', phase)
                    repaint_icons(window.contentItem())
                    QTest.qWait(60)
                    name = f'border-{phase}.png'
                    window.grabWindow().save(str(output / name))
                    results.append(name)
                frontend.setReduceMotion(False)
                QTest.qWait(100)
                phase = arc.property('sweep')
                QTest.qWait(150)
                assert arc.property('sweep') != phase
                frontend.setReduceMotion(True)
                QTest.qWait(40)
                phase = arc.property('sweep')
                QTest.qWait(100)
                assert arc.property('sweep') == phase
                # Existing conversation placement uses the same composer anchor.
                cid = db.create_conversation('Usage review', 'codex', 'gpt-6-astra', settings.root)
                db.add_message(cid, 'user', 'Mensagem de teste visual')
                chat.refresh()
                chat.selectConversationId(cid)
                chat._usage_snapshot = dict(status='available', supported=True, accounts=accounts)
                chat.usageLimitsChanged.emit()
                dialog.open()
                QTest.qWait(120)
                window.grabWindow().save(str(output / 'limits-conversation.png'))
                results.append('limits-conversation.png')
                assert dialog.property('contentItem').mapToScene(QPointF(0, 0)).y() > 0
                QTest.keyClick(window, Qt.Key_Escape)
                QTest.qWait(80)
                assert not dialog.property('visible')
                # Retraído com VR Ultra: o contorno segue a silhueta campo +
                # bandeja, sem recuo lateral e sem sobra sob os cantos da bandeja.
                for _ in range(12):
                    db.add_message(cid, 'user', 'Mensagem para rolagem.\n\n' * 3)
                    db.add_message(cid, 'assistant', 'Resposta para rolagem.\n\n' * 3)
                chat.refresh()
                chat.selectConversationId(cid)
                QTest.qWait(120)
                chat.setVrMode('ultra')
                timeline = window.findChild(QObject, 'messageList')
                timeline.setProperty('followTail', False)
                timeline.setProperty('contentY', 0)
                QTest.qWait(250)
                assert card.property('isCompact')
                assert arc.property('visible')
                assert abs(arc.width() - (card.width() + 8)) < 1
                assert abs(arc.height() - (card.height() + 8)) < 1
                # O realce do Ultra não pode herdar o acento do tema (ocean usa
                # messageAction teal); captura os dois temas para inspeção.
                for theme in ('dark_orange', 'ocean'):
                    frontend.setTheme(theme)
                    QTest.qWait(120)
                    repaint_icons(window.contentItem())
                    QTest.qWait(40)
                    name = f'border-compact-{theme}.png'
                    window.grabWindow().save(str(output / name))
                    results.append(name)
                warnings = [w.toString() for w in engine._qml_warnings]
                assert not warnings, warnings
                (output / 'results.json').write_text(json.dumps(dict(captures=results, warnings=warnings), indent=2), encoding='utf-8')
                print(f'{len(results)} captures; geometry, close/Escape, unknown data, motion and conversation checks passed; zero QML warnings.')
        finally:
            if window:
                window.close()
            studio.close()
            chat.close()


if __name__ == '__main__':
    main()

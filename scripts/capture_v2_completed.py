"""Reopen the persisted real resume result and verify the settled GUI is idle."""
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch
from validate_v2_runtime import (QApplication, QSettings, QTest, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine, _apply_application_font)

output = Path('reports/v2/conclusao/runtime-final').resolve()
record = json.loads((output/'result.json').read_text(encoding='utf-8'))
source = MarySettings(app_dir=output, root=output/'VRProject', old_root=output/'legacy')
settings = MarySettings(app_dir=output/'reopened-ui', root=output/'reopened-ui/VRProject', old_root=output/'reopened-ui/legacy')
settings.ensure_dirs()
with sqlite3.connect(source.database_path) as original, sqlite3.connect(settings.database_path) as copied:
    original.backup(copied)
db = MaryDatabase(settings.database_path, root=settings.root)
app = QApplication.instance() or QApplication([])
_apply_application_font(app)
prefs = QSettings(str(output/'reopened-ui/preferences.ini'), QSettings.IniFormat)
frontend = FrontendBridge(settings, prefs, theme_override='dark_orange', initial_page='Chat VR')
chat = ChatBridge(settings, db, prefs)
studio = StudioBridge(settings, db, prefs)
with patch.object(chat, 'refreshModels'):
    engine = create_engine(frontend, chat, studio)
    window = engine.rootObjects()[0]
    window.setWidth(1366)
    window.setHeight(768)
    cid = record['resume']['after']['conversation_id']
    chat.selectConversation(next(i for i,row in enumerate(chat._conversations._items) if row['conversationId']==cid))
    QTest.qWait(1200)
    assert not chat.turnRunning and db.get_conversation(cid)['status'] != 'running'
    assert window.grabWindow().save(str(output/'resume-after-reopened.png'))
    result = {'ui_idle':not chat.turnRunning, 'conversation_status':db.get_conversation(cid)['status'],
        'qml_warnings':[w.toString() for w in engine._qml_warnings]}
    (output/'reopened-ui.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result)
    window.close()
studio.close()
chat.close()
engine.deleteLater()
app.processEvents()

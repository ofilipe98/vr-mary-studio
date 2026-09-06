"""Render a deterministic QML fixture with real semantic timeline events."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.frontend.app import create_engine

app = QApplication.instance() or QApplication([])
for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename))
with tempfile.TemporaryDirectory(prefix="mary-qml-review-") as directory:
    root = Path(directory)
    settings = MarySettings(app_dir=root, root=root / "project", old_root=root / "legacy")
    prefs = QSettings(str(root / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation("Validação de mensagens intermediárias", "codex", "teste", settings.root)
    owner = db.begin_user_turn(cid, "Verifique a implementação e execute os testes.")
    for index, text in enumerate(("Vou localizar o fluxo de mensagens e verificar como os turnos são identificados.", "O histórico agora preserva cada mensagem. Vou conferir o cancelamento.", "Validação concluída. As mensagens permanecem separadas e a Task Bar foi reutilizada."), 1):
        payload = {"execution_id": owner, "message_key": f"{owner}:{index}", "seq": index}
        db.add_event(RuntimeEvent(cid, "assistant_started", payload=payload))
        db.upsert_assistant_message(cid, text, execution_id=owner, execution_ordinal=index)
        db.add_event(RuntimeEvent(cid, "assistant_completed", payload={**payload, "final_text": text}))
        if index < 3:
            db.add_event(RuntimeEvent(cid, "tool_event", "Leitura de arquivos" if index == 1 else "Execução de testes", {"execution_id": owner, "item": {"id": f"tool{index}", "type": "commandExecution"}, "lifecycle": "item/completed"}))
    db.add_event(RuntimeEvent(cid, "turn_completed", payload={"execution_id": owner}))
    db.finish_user_turn(cid, owner, "idle")
    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    window = None
    try:
        chat._selected["conversationId"] = cid
        chat._reload_selected_messages()
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects()
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(900)
            QTest.qWait(400)
            assert not engine._qml_warnings, [e.toString() for e in engine._qml_warnings]
            rows = chat._messages._items
            assert [r["role"] for r in rows] == ["user", "assistant", "activity", "assistant", "activity", "assistant"]
            path = Path(__file__).with_name("qml-timeline.png")
            assert window.grabWindow().save(str(path))
            chat._active_turns.add(cid)
            chat._sync_selected_turn_state()
            chat._activity_steps = [{"text": "Analisar fluxo", "state": "completed"}, {"text": "Revisar persistência", "state": "completed"}, {"text": "Validar interface", "state": "running"}]
            chat.stateChanged.emit()
            QTest.qWait(200)
            assert window.grabWindow().save(str(path.with_name("qml-timeline-active.png")))
            Path(__file__).with_name("smoke-visual-result.json").write_text(json.dumps({"status": "passed", "qml_warnings": 0, "roles": [r["role"] for r in rows], "screenshot": path.name}), encoding="utf-8")
            print(path.resolve())
    finally:
        if window:
            window.close()
        studio.close()
        chat.close()

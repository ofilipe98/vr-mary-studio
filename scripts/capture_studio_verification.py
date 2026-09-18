"""Visual verification script to capture project selector and toolcalling exactly as rendered."""
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine, _apply_application_font
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.models import RuntimeEvent


def find_items(item, name):
    result = [item] if item.objectName() == name else []
    for child in item.childItems():
        result.extend(find_items(child, name))
    return result


def main():
    out_dir = Path(".test-tmp/visual-compare")
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy")
        prefs = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)

        # Populate projects exactly matching T3 Code reference:
        # VRStudio (layers, magenta), Codex (cx, yellow), VRNorteTools (wrench, blue), VRDBTools (vs, green)
        projects = [
            {"path": "D:/Codex/VRStudio", "label": "VRStudio", "iconKind": "layers", "iconColor": "#D946EF"},
            {"path": "D:/Codex", "label": "Codex", "iconText": "cx", "iconColor": "#EAB308"},
            {"path": "D:/Tools", "label": "VRNorteTools", "iconKind": "wrench", "iconColor": "#3B82F6"},
            {"path": "D:/DBTools", "label": "VRDBTools", "iconText": "vs", "iconColor": "#10B981"},
        ]
        prefs.setValue("chat/projects", json.dumps(projects))

        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        cid = db.create_conversation("Teste T3 Toolcalling", "codex", "gpt-5.6", settings.root)
        db.add_message(cid, "user", "git status e busca de arquivos")
        db.add_message(cid, "assistant", "Aqui estão as verificações realizadas.")
        for event in [RuntimeEvent(cid, "turn_started", "Execução iniciada"),
                      RuntimeEvent(cid, "turn_completed", "Pronto")]:
            db.add_event(event)

        frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
        frontend.setReduceMotion(True)
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)

        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            window = engine.rootObjects()[0]
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(500)

            # 1. Select first project (VRStudio) so it's highlighted
            chat.setProject(1)
            QTest.qWait(200)

            # Open project selector popup
            proj_sel = window.findChild(QObject, "projectSelector")
            if proj_sel:
                proj_sel.openSelectorMenu()
                QTest.qWait(300)
                window.grabWindow().save(str(out_dir / "project-selector-open.png"))

            # 2. Capture Tool Calling activity
            activity_items = [
                {"text": "Running git", "state": "running", "kind": "tool", "itemType": "commandExecution"},
                {"text": "<path>D:\\Codex\\VRStudio\\docs\\DEVELOPMENT.md</path> <type>file</type> <content> 1: # Desenvolvimento...", "state": "completed", "kind": "tool", "itemType": "fileRead", "detail": "1: # Desenvolvimento do VRStudio"},
                {"text": "git status --short; echo \"---\"; git log --oneline -15", "state": "completed", "kind": "tool", "itemType": "commandExecution", "detail": "M tests/test_chat_landing.py"},
                {"text": "<path>D:\\Codex\\VRStudio\\vrsoft_extractor\\mary\\orchestrator.py</path> <type>file</type> <content> 1: from...", "state": "completed", "kind": "tool", "itemType": "fileRead"},
                {"text": "Found 75 matches D:\\Codex\\VRStudio\\README.md: Line 78: local. O **VR Ultra** acrescenta pesquisadores mod...", "state": "completed", "kind": "tool", "itemType": "webSearch"},
                {"text": "git diff --stat; echo \"===\"; git diff -- vrsoft_extractor/mary/orchestrator.py", "state": "completed", "kind": "tool", "itemType": "commandExecution"},
                {"text": "<path>D:\\Codex\\VRStudio\\vrsoft_extractor\\mary\\execution\\runner.py</path> <type>file</type> <content> 1: ...", "state": "completed", "kind": "tool", "itemType": "fileChange"},
            ]

            activities = find_items(window.contentItem(), "chatActivity")
            if activities:
                act = activities[0]
                act.setProperty("elapsedLabel", "26s")
                act.setProperty("statusText", "Trabalhando…")
                act.setProperty("running", True)
                act.setProperty("expanded", True)
                act.setProperty("items", activity_items)
                QTest.qWait(300)
                window.grabWindow().save(str(out_dir / "toolcalling-t3-expanded.png"))

                # Also capture collapsed/running state
                act.setProperty("expanded", False)
                QTest.qWait(300)
                window.grabWindow().save(str(out_dir / "toolcalling-t3-collapsed.png"))

    print("Captured screenshots to:", out_dir)


if __name__ == "__main__":
    main()

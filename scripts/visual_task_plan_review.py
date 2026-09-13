"""Capture the task drawer in the real chat using isolated provider snapshots."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QSettings, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine, _apply_application_font
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.models import RuntimeEvent


def main():
    output = Path(
        sys.argv[1] if len(sys.argv) > 1 else ".test-tmp/task-plan-review"
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
        cid = db.create_conversation(
            "Tarefas do agente", "codex", "gpt-5.6", settings.root
        )
        db.add_message(cid, "user", "Revise a implementação e valide os testes.")
        db.add_message(
            cid,
            "assistant",
            "A revisão está em andamento. As tarefas abaixo acompanham o plano do agente.",
        )
        frontend = FrontendBridge(
            settings, prefs, theme_override="dark_orange", initial_page="Chat VR"
        )
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)
        try:
            with patch.object(chat, "refreshModels"):
                engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [str(w) for w in engine._qml_warnings]
            window = engine.rootObjects()[0]
            frontend.setReduceMotion(True)
            bar = window.findChild(QObject, "chatTaskBar")
            header = window.findChild(QObject, "taskPlanHeader")
            chat._active_turns.add(cid)
            chat._sync_selected_turn_state()
            steps = [
                {
                    "text": "Inspecionar os componentes e o fluxo de eventos",
                    "state": "completed",
                },
                {
                    "text": "Atualizar a interface e preservar o histórico de tarefas",
                    "state": "running",
                },
                {
                    "text": "Executar os testes e revisar o resultado",
                    "state": "pending",
                },
            ]
            chat._record_execution_event(
                RuntimeEvent(
                    cid,
                    "task_plan_updated",
                    payload={"steps": [{**steps[0], "state": "running"}, *steps[1:]]},
                    created_at="2026-09-13T12:00:00Z",
                )
            )
            chat._record_execution_event(
                RuntimeEvent(
                    cid,
                    "task_plan_updated",
                    payload={"steps": steps},
                    created_at="2026-09-13T12:00:14Z",
                )
            )
            for theme in ("dark_orange", "light"):
                frontend.setTheme(theme)
                for width, height in ((1366, 768), (390, 844)):
                    window.setWidth(width)
                    window.setHeight(height)
                    QTest.qWait(200)
                    for expanded in (False, True):
                        if bar.property("expanded") != expanded:
                            point = header.mapToScene(QPoint(20, 12))
                            QTest.mouseClick(
                                window, Qt.LeftButton, Qt.NoModifier, point.toPoint()
                            )
                        QTest.qWait(100)
                        assert bar.property("expanded") == expanded
                        assert bar.property("visible")
                        window.grabWindow().save(
                            str(
                                output
                                / f"tasks-{theme}-{width}-{'expanded' if expanded else 'collapsed'}.png"
                            )
                        )
            many = [
                {
                    "text": f"Etapa {index + 1}: validar o comportamento e a integração com os componentes da aplicação",
                    "state": "pending",
                }
                for index in range(18)
            ]
            chat._record_execution_event(
                RuntimeEvent(cid, "task_plan_updated", payload={"steps": many})
            )
            QTest.qWait(150)
            scroll = window.findChild(QObject, "taskPlanScroll")
            assert scroll.property("contentHeight") > scroll.property("height")
            flickable = scroll.property("contentItem")
            flickable.setProperty(
                "contentY", scroll.property("contentHeight") - scroll.property("height")
            )
            QTest.qWait(100)
            window.grabWindow().save(str(output / "tasks-long-list-scrolled.png"))
            frontend.setUiScale("150")
            window.setWidth(1366)
            window.setHeight(900)
            QTest.qWait(200)
            window.grabWindow().save(str(output / "tasks-scale-150.png"))
            header.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(80)
            assert not bar.property("expanded")
            QTest.keyClick(window, Qt.Key_Return)
            QTest.qWait(80)
            assert bar.property("expanded")
            chat._record_execution_event(
                RuntimeEvent(
                    cid,
                    "task_plan_updated",
                    payload={"steps": [{"text": "Concluída", "state": "completed"}]},
                )
            )
            QTest.qWait(80)
            assert not bar.property("visible")
            warnings = [w.toString() for w in engine._qml_warnings]
            (output / "qml-warnings.txt").write_text(
                "\n".join(warnings), encoding="utf-8"
            )
            assert not warnings, warnings
            window.close()
            engine.deleteLater()
        finally:
            chat.close()
            app.processEvents()
    print(output)


if __name__ == "__main__":
    main()

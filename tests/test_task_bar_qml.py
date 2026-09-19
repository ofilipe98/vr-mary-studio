"""Parity checks for the task drawer, sidebar and activity surfaces."""

import pytest
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.bridges.presentation import ConversationListModel

pytestmark = pytest.mark.qml

ROOT = Path(__file__).resolve().parents[1]
TASK_BAR = ROOT / "vrsoft_extractor/mary/frontend/qml/components/VrTaskBar.qml"
CHAT_PREVIEW = ROOT / "vrsoft_extractor/mary/frontend/qml/pages/ChatPreview.qml"
ACTIVITY = ROOT / "vrsoft_extractor/mary/frontend/qml/components/VrChatActivity.qml"


def _bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(
        app_dir=tmp_path, root=tmp_path / "data", old_root=tmp_path / "old"
    )
    db = MaryDatabase(
        settings.database_path, root=settings.root, backup_portable_migration=False
    )
    bridge = ChatBridge(
        settings, db, QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )
    return app, bridge


def test_bridge_exposes_compact_task_progress_for_qml(tmp_path):
    app, bridge = _bridge(tmp_path)
    try:
        meta = bridge.metaObject()
        names = {meta.property(index).name() for index in range(meta.propertyCount())}
        assert "taskSteps" in names
        assert "taskPlanVisible" in names
        assert "taskProgress" in names
        assert bridge.taskProgress == {}
        cid = bridge._database.create_conversation(
            "T", "codex", "test", bridge._settings.root
        )
        bridge.refresh()
        bridge.selectConversationId(cid)
        bridge._active_turns.add(cid)
        bridge._apply_task_snapshot(
            cid,
            [
                {"text": "A", "state": "completed"},
                {"text": "B longa " * 20, "state": "running"},
                {"text": "C", "state": "pending"},
            ],
            "2026-09-13T12:00:00Z",
        )
        assert bridge.taskProgress == {
            "step": bridge.taskSteps[1]["text"].strip(),
            "completed": 1,
            "total": 3,
        }
        assert bridge.taskPlanVisible
    finally:
        bridge.close()
        app.processEvents()


def test_conversation_model_carries_task_roles(tmp_path):
    app, bridge = _bridge(tmp_path)
    try:
        assert "taskStep" in ConversationListModel.ROLE_NAMES
        assert "taskCompleted" in ConversationListModel.ROLE_NAMES
        assert "taskTotal" in ConversationListModel.ROLE_NAMES
        cid = bridge._database.create_conversation(
            "T", "codex", "test", bridge._settings.root
        )
        bridge._database.update_conversation(cid, status="running")
        bridge.refresh()
        bridge.selectConversationId(cid)
        bridge._active_turns.add(cid)
        bridge._apply_task_snapshot(
            cid, [{"text": "Step", "state": "running"}], "2026-09-13T12:00:00Z"
        )
        bridge.refresh()
        row = next(
            item
            for item in bridge._all_conversations
            if item["conversationId"] == cid
        )
        assert row["taskStep"] == "Step"
        assert (row["taskCompleted"], row["taskTotal"]) == (0, 1)
    finally:
        bridge.close()
        app.processEvents()


def test_vr_task_bar_uses_backend_progress_and_keeps_a11y():
    text = TASK_BAR.read_text(encoding="utf-8")
    assert "property var progress" in text
    assert "effectiveCompleted()" in text
    assert "effectiveCurrentStep()" in text
    assert "objectName: \"taskPlanHeader\"" in text
    assert "objectName: \"taskPlanScroll\"" in text
    assert "Keys.onSpacePressed" in text
    assert "Keys.onReturnPressed" in text
    assert "Accessible.role" in text
    assert "ScrollBar.horizontal.policy: ScrollBar.AlwaysOff" in text
    assert "elide: Text.ElideRight" in text
    # Visual identity stays on Theme tokens; no hardcoded drawer colors.
    assert "Theme.palette" in text
    assert "#18A8E8" not in text


def test_chat_preview_sidebar_activity_and_approval_priority():
    preview = CHAT_PREVIEW.read_text(encoding="utf-8")
    # Sidebar shows compact progress with elide, preserving elapsed on top.
    assert "taskStep" in preview
    assert "taskCompleted" in preview
    assert "taskTotal" in preview
    assert "ElideRight" in preview
    # Drawer receives backend progress, not a recomputed plan.
    assert "progress: root.chatBridge.taskProgress" in preview
    # Activity surface gets the current step discretely.
    assert "taskStep:" in preview
    assert "root.chatBridge.taskProgress" in preview
    # Approvals take precedence over drawer expansion.
    assert "root.taskBarExpanded = false" in preview
    assert "!approvalDialog.opened" in preview
    activity = ACTIVITY.read_text(encoding="utf-8")
    assert "property string taskStep" in activity
    assert "taskStep" in activity


def test_vr_task_bar_runtime_interactions_and_lifecycle(tmp_path):
    from unittest.mock import patch
    from PySide6.QtCore import QObject, QPoint, Qt
    from PySide6.QtTest import QTest
    from vrsoft_extractor.mary.frontend.app import create_engine
    from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    from vrsoft_extractor.mary.models import RuntimeEvent

    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "data", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    cid = db.create_conversation("TaskBar Test", "codex", "gpt-5.6", settings.root)
    db.add_message(cid, "user", "Hello")

    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
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
        assert bar is not None
        assert header is not None

        # Initially idle: not visible
        assert not bar.property("visible")

        # Start turn and supply task plan
        chat._active_turns.add(cid)
        chat._sync_selected_turn_state()
        steps = [
            {"text": "Task Step 1 with long description for narrow testing", "state": "running"},
            {"text": "Task Step 2", "state": "pending"},
        ]
        chat._apply_task_snapshot(cid, steps, "2026-09-13T12:00:00Z")
        chat.stateChanged.emit()
        app.processEvents()

        # Invariants: Bar is now visible and collapsed
        assert chat.taskPlanVisible is True
        assert bar.property("visible") is True
        assert bar.property("expanded") is False

        # 1. Click toggle (expanding)
        point = header.mapToScene(QPoint(20, 12)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        app.processEvents()
        assert bar.property("expanded") is True

        # Click again to collapse (re-map point as drawer geometry shifted)
        point = header.mapToScene(QPoint(20, 12)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        app.processEvents()
        assert bar.property("expanded") is False

        # 2. Keyboard toggle (Space)
        header.forceActiveFocus()
        app.processEvents()
        assert header.property("activeFocus") is True
        QTest.keyClick(window, Qt.Key_Space)
        app.processEvents()
        assert bar.property("expanded") is True

        # Keyboard toggle (Return)
        QTest.keyClick(window, Qt.Key_Return)
        app.processEvents()
        assert bar.property("expanded") is False

        # 3. Narrow width layout test
        window.setWidth(360)
        app.processEvents()
        assert bar.property("visible") is True

        # 4. Expand, then trigger approval: drawer must collapse
        QTest.keyClick(window, Qt.Key_Space)
        app.processEvents()
        assert bar.property("expanded") is True

        chat._on_runtime_event(RuntimeEvent(
            cid,
            "approval_requested",
            payload={"request_id": "req_1", "kind": "command", "command": "echo 1"}
        ))
        app.processEvents()
        # VrTaskBar.expanded: root.taskBarExpanded && !approvalDialog.opened
        assert bar.property("expanded") is False

        # Discard approval
        chat._Activity_domain._discard_conversation_approvals(cid)
        app.processEvents()

        # 5. Terminal state hides TaskBar
        chat._queue_terminal_state("turn_completed", conversation_id=cid)
        app.processEvents()
        assert chat.taskPlanVisible is False
        assert bar.property("visible") is False
    finally:
        chat.close()
        app.processEvents()

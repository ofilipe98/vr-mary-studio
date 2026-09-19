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

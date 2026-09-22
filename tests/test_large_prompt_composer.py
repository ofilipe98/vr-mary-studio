import time

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_tool_ui_components import qml_env as qml_env
from vrsoft_extractor.mary.models import RuntimeEvent

pytestmark = pytest.mark.qml


def find(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = find(child, name)
        if found is not None:
            return found
    return None


def click(window, item):
    pos = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(50)


def test_thousand_line_composer_sends_and_stop_button_remains_reachable(qml_env, monkeypatch):
    app, engine, frontend, chat, studio = qml_env
    cid = chat._database.create_conversation("Texto longo", "opencode", "test", chat._settings.root)
    chat.refresh()
    chat.selectConversation(0)
    sent, stopped = [], []
    def send(target, text, callback, *args, **kwargs):
        sent.append(text)
        owner = chat._database.begin_user_turn(target, text)
        callback(RuntimeEvent(target, "turn_started", payload={"execution_id": owner}))

    monkeypatch.setattr(chat._orchestrator, "send", send)

    def stop(target):
        stopped.append(target)
        chat._database.update_conversation(target, status="cancelled")
        chat._runtimeEvent.emit(RuntimeEvent(target, "orchestration_cancelled", "Interrompido"))
        chat._runtimeEvent.emit(RuntimeEvent(target, "turn_completed"))

    monkeypatch.setattr(chat._orchestrator, "interrupt", stop)
    window = engine.rootObjects()[0]
    window.setWidth(1100)
    window.setHeight(800)
    window.show()
    QTest.qWait(150)
    field = find(window.contentItem(), "chatComposerInput")
    button = find(window.contentItem(), "chatSendButton")
    text = "\n".join(f"linha {i}: texto de teste" for i in range(1000))
    field.setProperty("text", text)
    QTest.qWait(300)
    click(window, button)
    assert sent == [text]
    assert field.property("text") == ""
    assert chat.turnRunning
    click(window, button)
    deadline = time.monotonic() + 3
    while chat.turnRunning and time.monotonic() < deadline:
        QTest.qWait(20)
    assert stopped == [cid]
    assert not chat.turnRunning


def test_rejected_send_keeps_thousand_lines_and_shows_reason(qml_env, monkeypatch):
    app, engine, frontend, chat, studio = qml_env
    chat._vr_mode = "off"

    def fail_new_conversation(*args, **kwargs):
        raise RuntimeError("provedor indisponível")

    monkeypatch.setattr(chat._orchestrator, "new_conversation", fail_new_conversation)
    window = engine.rootObjects()[0]
    window.show()
    QTest.qWait(150)
    field = find(window.contentItem(), "chatComposerInput")
    button = find(window.contentItem(), "chatSendButton")
    text = "\n".join(f"linha {i}: texto de teste" for i in range(1000))
    field.setProperty("text", text)
    QTest.qWait(300)
    click(window, button)
    assert field.property("text") == text
    warning = find(window.contentItem(), "chatSubmissionError")
    assert warning.isVisible()
    assert "Falha" in warning.property("text")

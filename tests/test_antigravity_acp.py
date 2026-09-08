import json
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vrsoft_extractor.mary.antigravity_acp import AcpClient, AcpError, acp_environment
from vrsoft_extractor.mary.antigravity_auth import AntigravityAuthManager
from vrsoft_extractor.mary.antigravity_provider import AntigravityProvider
from vrsoft_extractor.mary.models import ConversationOptions
from vrsoft_extractor.mary.providers import ProviderError

SESSION = {"sessionId": "native", "models": {"currentModelId": "gemini-test", "availableModels": [
    {"modelId": "gemini-test", "name": "Gemini Test"}]},
    "modes": {"currentModeId": "default", "availableModes": [{"id": "default"}, {"id": "yolo"}]}}


class FakeClient:
    instances = []
    session_error = False

    def __init__(self, **kwargs):
        self.callbacks = kwargs
        self.calls = []
        self.closed = False
        self.capabilities = {"sessionCapabilities": {"resume": {}}, "promptCapabilities": {"image": True}}
        self.process = None
        self.instances.append(self)

    def start(self):
        assert not self.closed

    def request(self, method, params, timeout=None):
        self.calls.append((method, params))
        if method in ("session/new", "session/resume", "session/load"):
            if self.session_error:
                raise AcpError(method, -32603)
            return SESSION
        if method == "session/prompt":
            self.callbacks["on_notification"]("session/update", {"sessionId": "native", "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OK"}}})
            return {"stopReason": "end_turn"}
        return {}

    def close(self):
        self.closed = True

    def notify(self, method, params):
        self.calls.append((method, params))


@pytest.fixture
def fake_runtime():
    FakeClient.instances = []
    FakeClient.session_error = False
    with patch("vrsoft_extractor.mary.provider_adapters.antigravity.AcpClient", FakeClient), \
            patch("vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account", return_value=True), \
            patch("vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp", return_value="acp"):
        yield


@pytest.mark.parametrize("native", ["", "acp:native"])
def test_conversation_uses_acp_auth_and_persists_native_id(fake_runtime, tmp_path, native):
    provider = AntigravityProvider()
    done, events = threading.Event(), []
    def receive(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()
    provider.send_message("conversation", native, "gemini-test", "auto", tmp_path, "Hello", receive)
    assert done.wait(2)
    assert [e.text for e in events if e.kind == "assistant_delta"] == ["OK"]
    assert not any(e.kind == "error" for e in events)
    client = FakeClient.instances[0]
    methods = [m for m, _ in client.calls]
    assert methods[0] == "authenticate"
    assert ("session/resume" if native else "session/new") in methods
    assert methods[-1] == "session/prompt"
    if not native:
        assert next(e for e in events if e.kind == "native_session_started").payload["native_id"] == "acp:native"
    assert client.closed and not provider._active


def test_catalog_comes_from_acp_session(fake_runtime):
    models = AntigravityProvider().list_models()
    assert models[0]["id"] == "gemini-test"
    assert models[0]["displayName"] == "Gemini Test"
    assert [m for m, _ in FakeClient.instances[0].calls] == ["authenticate", "session/new"]


def test_legacy_session_is_not_silently_resumed_with_another_account():
    with pytest.raises(ProviderError, match="histórico"):
        AntigravityProvider().resume_conversation("chat", "cli-session", "default", "auto", Path.cwd())


def test_no_saved_profile_does_not_start_implicit_oauth():
    with patch("vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account", return_value=False), \
            patch.object(AntigravityProvider, "available", return_value=True), \
            patch("vrsoft_extractor.mary.provider_adapters.antigravity.AcpClient") as client:
        provider = AntigravityProvider()
        assert provider.list_models() == []
        with pytest.raises(ProviderError, match="Entre com Google"):
            provider.send_message("chat", "", "default", "auto", Path.cwd(), "Hello", lambda _: None)
    client.assert_not_called()


def test_profile_is_shared_and_environment_is_sanitized(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_HOME", "unrelated-profile")
    monkeypatch.setenv("BROWSER", "untrusted-browser")
    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path):
        first, second = acp_environment(), acp_environment()
    assert first == second
    assert first["GEMINI_HOME"] == str(tmp_path)
    assert "GEMINI_API_KEY" not in first
    assert first["AGY_ACP_FORCE_FILE_STORAGE"] == "1"
    assert "-File" in first["BROWSER"] and "antigravity-browser-noop.ps1" in first["BROWSER"]
    assert "untrusted-browser" not in first["BROWSER"]


def test_login_authenticate_response_confirms_account_without_session_new():
    changed = threading.Event()
    manager = AntigravityAuthManager(lambda: "acp", lambda: {})
    manager._on_state_changed = lambda: changed.set() if manager.account_state == "authenticated" else None
    with patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", FakeClient):
        manager.start_login()
        assert changed.wait(2)
    assert manager.active_attempt.state == "succeeded"
    assert [m for m, _ in manager.active_attempt.client.calls] == ["authenticate"]
    manager.mark_session_or_model_error("failed")
    assert manager.account_state == "authenticated"


def test_session_failure_never_becomes_new_authentication(fake_runtime, tmp_path):
    FakeClient.session_error = True
    done, events = threading.Event(), []
    def receive(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()
    AntigravityProvider().send_message("chat", "", "default", "auto", tmp_path, "Hello", receive)
    assert done.wait(2)
    error = next(e for e in events if e.kind == "error")
    assert "session/new" in error.text and "-32603" in error.text
    assert [m for m, _ in FakeClient.instances[0].calls].count("authenticate") == 1


def test_supervised_request_reaches_ui_and_approval_returns_selected_option():
    provider = AntigravityProvider()
    client, events = MagicMock(), []
    state = {"client": client, "cancelled": False, "options": ConversationOptions(approval_profile="supervised")}
    provider._permission("chat", state, events.append, 7, "session/request_permission", {
        "toolCall": {"title": "Write file"}, "options": [{"kind": "allow_once", "optionId": "approve"}]})
    assert events[0].kind == "approval_requested"
    provider.approve_action(events[0].payload["request_id"], True)
    client.respond.assert_called_once_with(7, {"outcome": {"outcome": "selected", "optionId": "approve"}})


def test_plan_never_auto_approves_tools():
    provider = AntigravityProvider()
    client = MagicMock()
    state = {"client": client, "cancelled": False, "options": ConversationOptions(collaboration_mode="plan")}
    provider._permission("chat", state, lambda _: pytest.fail("Plan must reject tools"), 8,
                         "session/request_permission", {"options": [{"kind": "allow_once", "optionId": "approve"}]})
    client.respond.assert_called_once_with(8, {"outcome": {"outcome": "cancelled"}})


def test_rpc_response_errors_are_redacted_and_do_not_corrupt_other_requests():
    from concurrent.futures import Future
    client = AcpClient(command="test", env={})
    success, failure = Future(), Future()
    client._pending = {1: (success, "initialize"), 2: (failure, "authenticate")}
    client._receive(json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"code": -32603, "message": "SECRET"}}))
    client._receive(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}}))
    assert success.result()["protocolVersion"] == 1
    with pytest.raises(AcpError) as error:
        failure.result()
    assert "SECRET" not in str(error.value)


def test_closed_client_cannot_launch_a_late_process():
    client = AcpClient(command="test", env={})
    client.close()
    with patch("vrsoft_extractor.mary.antigravity_acp.subprocess.Popen") as popen:
        with pytest.raises(AcpError):
            client.start()
    popen.assert_not_called()


def test_oauth_diagnostic_with_runtime_log_prefix_is_captured():
    from vrsoft_extractor.mary.antigravity_auth import AuthStreamParser
    urls = []
    url = "https://accounts.google.com/o/oauth2/v2/auth?state=test"
    parser = AuthStreamParser(urls.append)
    parser.feed(("INFO runtime: Open the following link to authenticate the ACP server: " + url + "\n").encode())
    assert urls == [url]


@pytest.mark.parametrize("profile,mode", [("supervised", "default"), ("auto_edits", "auto_edit"), ("full_access", "yolo")])
def test_permissions_use_advertised_acp_modes(profile, mode):
    client = MagicMock()
    session = {**SESSION, "modes": {"availableModes": [{"id": x} for x in ("default", "auto_edit", "yolo")]}}
    AntigravityProvider()._configure(client, "native", session, "default", "auto", ConversationOptions(approval_profile=profile))
    client.request.assert_called_once_with("session/set_mode", {"sessionId": "native", "modeId": mode})


def test_usage_is_context_occupancy_not_billed_total():
    events = []
    AntigravityProvider()._update("chat", {"session": "native", "cancelled": False}, events.append,
        "session/update", {"sessionId": "native", "update": {"sessionUpdate": "usage_update", "used": 42, "size": 1000}})
    usage = events[0].payload["tokenUsage"]
    assert usage["contextOnly"] is True
    assert usage["last"]["totalTokens"] == 42
    assert usage["modelContextWindow"] == 1000


def test_real_stdio_transport_handles_fragmented_frames_and_closes_owned_process(tmp_path):
    import subprocess
    script = tmp_path / "acp_fixture.py"
    script.write_text('''import sys, json, os
for line in sys.stdin:
    request = json.loads(line)
    if request['method'] == 'initialize':
        result = {'protocolVersion': 1, 'agentCapabilities': {}, 'authMethods': [{'id': 'oauth-personal'}]}
    else:
        result = {'sessionId': 'fixture'}
    frame = (json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}) + '\\n').encode()
    os.write(sys.stdout.fileno(), frame[:7])
    os.write(sys.stdout.fileno(), frame[7:])
''', encoding="utf-8")
    popen = subprocess.Popen
    def launch(command, **kwargs):
        return popen([sys.executable, "-u", str(script)], **kwargs)
    client = AcpClient(command="fixture")
    try:
        with patch("vrsoft_extractor.mary.antigravity_acp.subprocess.Popen", side_effect=launch):
            assert client.start()["protocolVersion"] == 1
            assert client.request("session/new", {})["sessionId"] == "fixture"
    finally:
        client.close()
    assert client.process.poll() is not None
    assert all(not reader.is_alive() for reader in client._readers)

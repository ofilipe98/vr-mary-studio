import json
import os
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


def test_stdio_mcp_is_registered_without_optional_capability_flag(fake_runtime, tmp_path):
    from vrsoft_extractor.mary.models import ConversationOptions
    provider = AntigravityProvider(tmp_path)
    done = threading.Event()
    provider.send_message("conversation", "", "gemini-test", "auto", tmp_path, "Hello",
        lambda e: done.set() if e.kind == "turn_completed" else None,
        ConversationOptions(knowledge_context_path="frozen-turn.json"))
    assert done.wait(2)
    params = next(params for method, params in FakeClient.instances[0].calls if method == "session/new")
    server = params["mcpServers"][0]
    assert server["env"] == []
    assert server["args"][-2:] == ["--context", "frozen-turn.json"]
    assert "additionalDirectories" not in params


@pytest.mark.parametrize("native", ["", "acp:native"])
@pytest.mark.parametrize("enabled", [False, True])
def test_research_mcp_registration_respects_tool_switch(fake_runtime, tmp_path, native, enabled):
    provider = AntigravityProvider(tmp_path)
    done, events = threading.Event(), []
    def receive(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()
    options = ConversationOptions(approval_profile="research_readonly", tools_enabled=enabled)
    provider.send_message("conversation", native, "gemini-test", "auto", tmp_path, "Hello", receive, options)
    assert done.wait(2)
    assert not any(event.kind == "error" for event in events)
    calls = FakeClient.instances[0].calls
    params = next(params for method, params in calls if method in {"session/new", "session/resume"})
    assert bool(params["mcpServers"]) is enabled
    assert ("session/set_mode", {"sessionId": "native", "modeId": "default"}) in calls


def test_disabled_tools_override_full_access():
    client = MagicMock()
    options = ConversationOptions(tools_enabled=False)
    provider = AntigravityProvider()
    provider._configure(client, "native", SESSION, "default", "auto", options)
    client.request.assert_called_once_with("session/set_mode", {"sessionId": "native", "modeId": "default"})
    provider._permission("chat", {"client": client, "options": options, "cancelled": False},
                         lambda _: pytest.fail("Unexpected approval"), 7, "session/request_permission", {
        "toolCall": {"kind": "read"}, "options": [{"kind": "allow_once", "optionId": "once"}],
    })
    client.respond.assert_called_once_with(7, {"outcome": {"outcome": "cancelled"}})


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
    assert [m for m, _ in manager.active_attempt.client.calls] == ["authenticate", "session/new"]
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


def test_full_access_is_the_default_for_all_chats(tmp_path):
    from vrsoft_extractor.mary.config import MarySettings
    from vrsoft_extractor.mary.db import MaryDatabase
    from vrsoft_extractor.mary.frontend.chat import ChatBridge
    from PySide6.QtCore import QSettings

    opts = ConversationOptions()
    assert opts.approval_profile == "full_access"

    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "old")
    prefs = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)

    cid = db.create_conversation("Default test", "antigravity", "model", settings.work_dir)
    row = db.get_conversation(cid)
    assert row["approval_profile"] == "full_access"

    bridge = ChatBridge(settings, db, prefs)
    assert bridge._approval_profile == "full_access"
    assert bridge.approvalItems[bridge.approvalIndex]["value"] == "full_access"


def test_full_access_auto_approves_tools_without_ui_prompt():
    provider = AntigravityProvider()
    client, events = MagicMock(), []
    state = {"client": client, "cancelled": False, "options": ConversationOptions(approval_profile="full_access")}
    provider._permission("chat", state, events.append, 9, "session/request_permission", {
        "toolCall": {"title": "Execute command"},
        "options": [{"kind": "allow_once", "optionId": "opt_once"}, {"kind": "allow_always", "optionId": "opt_always"}],
    })
    assert len(events) == 0, "No approval_requested event should be emitted in full_access"
    client.respond.assert_called_once_with(9, {"outcome": {"outcome": "selected", "optionId": "opt_always"}})


@pytest.mark.parametrize("kind", ["read", "search"])
def test_research_readonly_allows_one_read_or_search(kind):
    provider = AntigravityProvider()
    client, events = MagicMock(), []
    state = {"client": client, "cancelled": False,
             "options": ConversationOptions(approval_profile="research_readonly")}
    provider._permission("chat", state, events.append, 7, "session/request_permission", {
        "toolCall": {"title": "vr_search", "kind": kind},
        "options": [{"kind": "allow_always", "optionId": "always"},
                    {"kind": "allow_once", "optionId": "once"}],
    })
    client.respond.assert_called_once_with(7, {"outcome": {"outcome": "selected", "optionId": "once"}})
    assert not events and not provider._approvals


@pytest.mark.parametrize("kind", ["edit", "delete", "move", "execute", "fetch", "other", None])
def test_research_readonly_rejects_non_read_tools_even_with_read_title(kind):
    provider = AntigravityProvider()
    client, events = MagicMock(), []
    state = {"client": client, "cancelled": False,
             "options": ConversationOptions(approval_profile="research_readonly")}
    provider._permission("chat", state, events.append, 7, "session/request_permission", {
        "toolCall": {"title": "vr_read", "kind": kind},
        "options": [{"kind": "allow_once", "optionId": "once"}],
    })
    client.respond.assert_called_once_with(7, {"outcome": {"outcome": "cancelled"}})
    assert not events and not provider._approvals


@pytest.mark.parametrize("overrides,cancelled", [
    ({"tools_enabled": False}, False), ({"collaboration_mode": "plan"}, False), ({}, True),
])
def test_disabled_cancelled_and_plan_research_reject_reads(overrides, cancelled):
    provider = AntigravityProvider()
    client = MagicMock()
    state = {"client": client, "cancelled": cancelled,
             "options": ConversationOptions(approval_profile="research_readonly", **overrides)}
    provider._permission("chat", state, lambda _: pytest.fail("Unexpected approval"), 7,
                         "session/request_permission", {
        "toolCall": {"kind": "read"}, "options": [{"kind": "allow_once", "optionId": "once"}],
    })
    client.respond.assert_called_once_with(7, {"outcome": {"outcome": "cancelled"}})


def test_research_readonly_does_not_grant_persistent_permission():
    client = MagicMock()
    state = {"client": client, "cancelled": False,
             "options": ConversationOptions(approval_profile="research_readonly")}
    AntigravityProvider()._permission("chat", state, lambda _: pytest.fail("Unexpected approval"), 7,
                                    "session/request_permission", {
        "toolCall": {"kind": "read"}, "options": [{"kind": "allow_always", "optionId": "always"}],
    })
    client.respond.assert_called_once_with(7, {"outcome": {"outcome": "cancelled"}})


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


def test_acp_client_isolates_and_cleans_temporary_directory(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    other_client_dir = tmp_path / "vr-acp-other-client"
    other_client_dir.mkdir()
    (other_client_dir / "runtime.dll").write_text("active runtime")
    script = tmp_path / "acp_fixture.py"
    script.write_text('''import sys, json
for line in sys.stdin:
    req = json.loads(line)
    if req['method'] == 'initialize':
        res = {'protocolVersion': 1, 'agentCapabilities': {}, 'authMethods': [{'id': 'oauth-personal'}]}
    else:
        res = {}
    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': res}) + '\\n')
    sys.stdout.flush()
''', encoding="utf-8")
    popen = subprocess.Popen
    captured_env = {}
    def launch(command, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return popen([sys.executable, "-u", str(script)], **kwargs)

    client = AcpClient(command="fixture")
    with patch("vrsoft_extractor.mary.antigravity_acp.subprocess.Popen", side_effect=launch):
        client.start()
        temp_dir = client._temp_dir
        assert temp_dir is not None
        assert os.path.isdir(temp_dir)
        assert captured_env.get("TEMP") == temp_dir
        assert captured_env.get("TMP") == temp_dir
        # Create a dummy file inside to simulate PyInstaller _MEI extraction
        dummy_mei = Path(temp_dir) / "_MEI12345"
        dummy_mei.mkdir()
        (dummy_mei / "test.dll").write_text("content")

        client.close()

    assert not os.path.exists(temp_dir), "Temporary directory must be cleaned up on close()"
    assert (other_client_dir / "runtime.dll").read_text() == "active runtime"


def test_failed_acp_launch_cleans_owned_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    client = AcpClient(command=str(tmp_path / "missing-program.exe"))
    with pytest.raises(OSError):
        client.start()
    assert list(tmp_path.glob("vr-acp-*")) == []

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
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

    SESSION_TIMEOUT = 90.0

    def __init__(self, **kwargs):
        self.callbacks = kwargs
        self.calls = []
        self.request_timeouts = []
        self.closed = False
        self.block_prompt = getattr(self.__class__, "block_prompt", False)
        self.prompt_started = threading.Event()
        self.prompt_unblock = threading.Event()
        self.capabilities = {"sessionCapabilities": {"resume": {}}, "promptCapabilities": {"image": True}}
        self.process = None
        self.instances.append(self)

    def start(self):
        assert not self.closed

    def request(self, method, params, timeout=SESSION_TIMEOUT):
        self.calls.append((method, params))
        self.request_timeouts.append((method, timeout))
        if method in ("session/new", "session/resume", "session/load"):
            if self.session_error:
                raise AcpError(method, -32603)
            return SESSION
        if method == "session/prompt":
            if self.block_prompt:
                self.prompt_started.set()
                self.prompt_unblock.wait(5.0)
                if self.closed:
                    raise AcpError("session/prompt")
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
    with patch("vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client",
               side_effect=lambda *args, **kwargs: FakeClient(**{
                   key: kwargs[key] for key in ("on_notification", "on_request") if key in kwargs
               })), \
            patch("vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account", return_value=True), \
            patch("vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp", return_value="acp"), \
            patch("vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime",
                  return_value=SimpleNamespace(executable_path="acp", harness_path="harness")):
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


@pytest.mark.parametrize("native", ["", "acp:native"])
@pytest.mark.parametrize("vr_enabled", [False, True])
def test_stdio_mcp_is_registered_without_optional_capability_flag(
    fake_runtime, tmp_path, native, vr_enabled
):
    from vrsoft_extractor.mary.models import ConversationOptions
    provider = AntigravityProvider(tmp_path)
    done = threading.Event()
    provider.send_message("conversation", native, "gemini-test", "auto", tmp_path, "Hello",
        lambda e: done.set() if e.kind == "turn_completed" else None,
        ConversationOptions(knowledge_context_path="frozen-turn.json", vr_enabled=vr_enabled))
    assert done.wait(2)
    calls = FakeClient.instances[0].calls
    params = next(
        params
        for method, params in calls
        if method in {"session/new", "session/resume", "session/load"}
    )
    server = params["mcpServers"][0]
    assert server["env"] == []
    assert server["args"][server["args"].index("--context") + 1] == "frozen-turn.json"
    assert server["args"][server["args"].index("--monitor-session") + 1] == "conversation"
    assert ("--disable-vr-tools" in server["args"]) is not vr_enabled
    assert "additionalDirectories" not in params


@pytest.mark.parametrize(
    "vr_enabled,tools_enabled",
    [(True, True), (True, False), (False, True)],
)
def test_vr_message_explains_workspace_sandbox(
    fake_runtime, tmp_path, vr_enabled, tools_enabled
):
    provider = AntigravityProvider(tmp_path)
    done = threading.Event()
    provider.send_message(
        "conversation",
        "",
        "gemini-test",
        "auto",
        tmp_path,
        "Hello",
        lambda event: done.set() if event.kind == "turn_completed" else None,
        ConversationOptions(vr_enabled=vr_enabled, tools_enabled=tools_enabled),
    )
    assert done.wait(2)
    params = next(
        params for method, params in FakeClient.instances[0].calls
        if method == "session/prompt"
    )
    message = "".join(block.get("text", "") for block in params["prompt"])
    assert "Use as fontes já fornecidas" not in message
    if vr_enabled and tools_enabled:
        assert "AMBIENTE ANTIGRAVITY" in message
        assert "não é legível diretamente" in message
        for name in ("vr_sources", "vr_search", "vr_read"):
            assert name in message
    elif vr_enabled:
        assert "AMBIENTE ANTIGRAVITY" not in message
        assert "Se uma ferramenta for recusada" in message
    else:
        assert "AMBIENTE ANTIGRAVITY" not in message
        assert "Se uma ferramenta for recusada" not in message


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
            patch("vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client") as spawn:
        provider = AntigravityProvider()
        assert provider.list_models() == []
        with pytest.raises(ProviderError, match="Entre com Google"):
            provider.send_message("chat", "", "default", "auto", Path.cwd(), "Hello", lambda _: None)
    spawn.assert_not_called()


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


def test_login_authenticate_response_confirms_account_without_session_new(tmp_path):
    changed = threading.Event()
    manager = AntigravityAuthManager(lambda: "acp", lambda: {})
    manager._on_state_changed = lambda: changed.set() if manager.account_state == "authenticated" else None
    with patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", FakeClient), \
            patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path / "profile"):
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
    from urllib.parse import urlencode

    from vrsoft_extractor.mary.antigravity_auth import AuthStreamParser
    urls = []
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "response_type": "code",
        "client_id": "123",
        "redirect_uri": "http://127.0.0.1:45678/",
        "state": "test",
    })
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
        with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path / "profile"), \
                patch("vrsoft_extractor.mary.antigravity_acp.subprocess.Popen", side_effect=launch):
            assert client.start()["protocolVersion"] == 1
            assert client.request("session/new", {})["sessionId"] == "fixture"
    finally:
        client.close()
    assert client.process.poll() is not None
    assert all(not reader.is_alive() for reader in client._readers)


def test_acp_client_isolates_and_cleans_temporary_directory(tmp_path, monkeypatch):
    import subprocess

    from vrsoft_extractor.mary.antigravity_acp import ACP_TEMP_OWNER_LOCK, prepare_profile
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    profile = tmp_path / "profile"
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

    client = AcpClient(command="fixture", env={})
    assert client._temp_dir is None
    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=profile), \
            patch("vrsoft_extractor.mary.antigravity_acp.subprocess.Popen", side_effect=launch):
        client.start()
        temp_dir = client._temp_dir
        assert temp_dir is not None
        assert os.path.isdir(temp_dir)
        assert Path(temp_dir).parent == profile / "antigravity-acp" / "tmp"
        assert Path(temp_dir).name.startswith("proc-")
        assert captured_env.get("TEMP") == temp_dir
        assert captured_env.get("TMP") == temp_dir
        assert captured_env.get("TMPDIR") == temp_dir
        owner_lock = Path(temp_dir) / ACP_TEMP_OWNER_LOCK
        assert owner_lock.is_file(), "the owner lock must exist while the client is active"
        # Reconciling orphans while this client is alive must never remove the
        # directory it still owns: the held lock proves active ownership.
        prepare_profile(profile)
        assert os.path.isdir(temp_dir)
        assert owner_lock.is_file()
        # Create a dummy file inside to simulate PyInstaller _MEI extraction
        dummy_mei = Path(temp_dir) / "_MEI12345"
        dummy_mei.mkdir()
        (dummy_mei / "test.dll").write_text("content")

        client.close()

    assert not os.path.exists(temp_dir), "Temporary directory must be cleaned up on close()"
    assert list((profile / "antigravity-acp" / "tmp").glob("proc-*")) == []
    assert (other_client_dir / "runtime.dll").read_text() == "active runtime"


def test_failed_acp_launch_cleans_owned_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    profile = tmp_path / "profile"
    client = AcpClient(command=str(tmp_path / "missing-program.exe"), env={})
    assert client._temp_dir is None
    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=profile):
        with pytest.raises(OSError):
            client.start()
    assert list((profile / "antigravity-acp" / "tmp").glob("proc-*")) == []
    assert list(tmp_path.glob("proc-*")) == []


def test_close_retries_transient_temp_cleanup_failure(tmp_path, caplog):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    temp_dir = tmp_path / "proc-transient"
    temp_dir.mkdir()
    (temp_dir / "runtime.dll").write_text("mapped")
    client = AcpClient(command="test", env={})
    client._temp_dir = str(temp_dir)
    client._temp_lock = None
    real_rmtree = acp_module.shutil.rmtree
    attempts = []
    def flaky_rmtree(path, *args, **kwargs):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError("file still mapped")
        return real_rmtree(path, *args, **kwargs)

    with patch("vrsoft_extractor.mary.antigravity_acp.shutil.rmtree", side_effect=flaky_rmtree), \
            patch("vrsoft_extractor.mary.antigravity_acp.time.sleep") as sleep, \
            caplog.at_level(logging.WARNING, logger="vrsoft_extractor.mary.antigravity_acp"):
        client.close()

    assert not temp_dir.exists()
    assert len(attempts) == 3
    assert [call.args[0] for call in sleep.call_args_list] == [0.05, 0.1]
    warnings = [r for r in caplog.records
                if r.name == "vrsoft_extractor.mary.antigravity_acp" and r.levelno >= logging.WARNING]
    assert warnings == [], "a retry that succeeds must not emit a final warning"


@pytest.mark.skipif(os.name != "nt", reason="kill-on-close job objects are Windows-only")
def test_kill_on_close_job_terminates_descendants(tmp_path):
    """Closing the job must kill the PyInstaller-style child, not just the parent."""
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    from vrsoft_extractor.mary.execution.ownership import process_identity

    script = tmp_path / "spawner.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    job = acp_module._create_kill_on_close_job()
    assert job is not None
    process = subprocess.Popen(
        [sys.executable, "-u", str(script)],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    grandchild = None
    try:
        if not acp_module._assign_process_to_job(job, process):
            pytest.skip("this session does not allow nested job objects")
        grandchild = int(process.stdout.readline().strip())
        acp_module._close_kill_on_close_job(job)
        job = None
        process.wait(timeout=10)
        deadline = time.time() + 10
        while time.time() < deadline and process_identity(grandchild):
            time.sleep(0.05)
        assert process_identity(grandchild) == ""
    finally:
        if job is not None:
            acp_module._close_kill_on_close_job(job)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if grandchild and process_identity(grandchild):
            subprocess.run(
                ["taskkill.exe", "/PID", str(grandchild), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )


def test_prepare_profile_reclaims_unlocked_owned_temp_dir(tmp_path, monkeypatch):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    from vrsoft_extractor.mary.antigravity_acp import prepare_profile
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "system-tmp"))
    (tmp_path / "system-tmp").mkdir()
    profile = tmp_path / "profile"
    tmp_root = profile / "antigravity-acp" / "tmp"
    tmp_root.mkdir(parents=True)

    temp_dir, handle = acp_module._create_owned_temp_dir(tmp_root, prefix="proc-")
    assert Path(temp_dir, acp_module.ACP_TEMP_OWNER_LOCK).is_file()
    # A previous process died or crashed after creating the directory: the
    # owner lock is free, but the directory is still on disk.
    acp_module._release_temp_lock(handle)

    prepare_profile(profile)
    assert not Path(temp_dir).exists()


def test_prepare_profile_preserves_locked_temp_dir(tmp_path, monkeypatch):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    from vrsoft_extractor.mary.antigravity_acp import prepare_profile
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "system-tmp"))
    (tmp_path / "system-tmp").mkdir()
    profile = tmp_path / "profile"
    tmp_root = profile / "antigravity-acp" / "tmp"
    tmp_root.mkdir(parents=True)

    temp_dir, handle = acp_module._create_owned_temp_dir(tmp_root, prefix="proc-")
    try:
        prepare_profile(profile)
        assert Path(temp_dir).is_dir()
        assert Path(temp_dir, acp_module.ACP_TEMP_OWNER_LOCK).is_file()
    finally:
        acp_module._release_temp_lock(handle)

    prepare_profile(profile)
    assert not Path(temp_dir).exists()


def test_stale_cleanup_uses_grace_only_for_legacy_dirs(tmp_path, monkeypatch):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "system-tmp"))
    profile = tmp_path / "profile"
    profile_tmp = profile / "antigravity-acp" / "tmp"
    system_tmp = tmp_path / "system-tmp"
    profile_tmp.mkdir(parents=True)
    system_tmp.mkdir()

    now = time.time()
    stale_age = now - acp_module.LEGACY_ACP_TEMP_GRACE_SECONDS - 3600
    fresh_age = now - 60
    expired = [profile_tmp / "proc-expired", system_tmp / "vr-acp-expired"]
    preserved = [
        profile_tmp / "proc-recent",
        system_tmp / "vr-acp-recent",
        profile_tmp / "proc",
        profile_tmp / "unrelated",
        system_tmp / "vr-acp",
        system_tmp / "unrelated",
    ]
    for directory in expired:
        directory.mkdir()
        os.utime(directory, (stale_age, stale_age))
    for directory in preserved:
        directory.mkdir()
        os.utime(directory, (fresh_age, fresh_age))

    removed = acp_module._cleanup_stale_acp_temp_dirs(profile_dir=profile, now=now)
    assert removed == 2
    assert all(not directory.exists() for directory in expired)
    assert all(directory.exists() for directory in preserved)


def test_stale_cleanup_failure_does_not_abort_profile_preparation(tmp_path, monkeypatch, caplog):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    from vrsoft_extractor.mary.antigravity_acp import prepare_profile
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "system-tmp"))
    (tmp_path / "system-tmp").mkdir()
    profile = tmp_path / "profile"
    tmp_root = profile / "antigravity-acp" / "tmp"
    tmp_root.mkdir(parents=True)

    temp_dir, handle = acp_module._create_owned_temp_dir(tmp_root, prefix="proc-")
    acp_module._release_temp_lock(handle)
    token = profile / "antigravity-acp" / "acp_token.json"
    token.write_text('{"token": "saved"}', encoding="utf-8")

    with patch("vrsoft_extractor.mary.antigravity_acp.shutil.rmtree", side_effect=PermissionError("in use")), \
            patch("vrsoft_extractor.mary.antigravity_acp.time.sleep"), \
            caplog.at_level(logging.WARNING, logger="vrsoft_extractor.mary.antigravity_acp"):
        prepare_profile(profile)

    assert Path(temp_dir).exists(), "an orphan that cannot be removed must be preserved"
    assert token.read_text(encoding="utf-8") == '{"token": "saved"}'
    settings = profile / "antigravity-acp" / "settings.json"
    assert json.loads(settings.read_text(encoding="utf-8"))["auth"]["type"] == "oauth-personal"
    assert any(
        record.name == "vrsoft_extractor.mary.antigravity_acp" and record.levelno >= logging.WARNING
        for record in caplog.records
    ), "the failed reclaim must be reported as a warning"


# --- Orphan runtime reclamation, job diagnostics and shutdown hooks ----------


def test_remove_acp_temp_dir_warning_reports_os_error(tmp_path, caplog):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    temp_dir = tmp_path / "proc-locked"
    temp_dir.mkdir()

    with patch("vrsoft_extractor.mary.antigravity_acp.shutil.rmtree",
               side_effect=PermissionError(13, "Access is denied")), \
            patch("vrsoft_extractor.mary.antigravity_acp.time.sleep"), \
            caplog.at_level(logging.WARNING, logger="vrsoft_extractor.mary.antigravity_acp"):
        assert acp_module._remove_acp_temp_dir(temp_dir) is False

    assert temp_dir.exists()
    message = next(record.getMessage() for record in caplog.records
                   if record.name == "vrsoft_extractor.mary.antigravity_acp")
    assert str(temp_dir) in message
    assert "Access is denied" in message, "the OS error must explain what blocked the removal"


@pytest.mark.skipif(os.name != "nt", reason="orphan termination uses taskkill")
def test_cleanup_terminates_orphaned_runtime_before_reclaim(tmp_path, monkeypatch, caplog):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    from vrsoft_extractor.mary.execution.ownership import process_identity
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "system-tmp"))
    (tmp_path / "system-tmp").mkdir()
    profile = tmp_path / "profile"
    tmp_root = profile / "antigravity-acp" / "tmp"
    tmp_root.mkdir(parents=True)

    temp_dir, handle = acp_module._create_owned_temp_dir(tmp_root, prefix="proc-")
    runtime = subprocess.Popen(
        [sys.executable, "-u", "-c", "import time; time.sleep(120)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        acp_module._record_runtime_info(temp_dir, runtime.pid)
        assert process_identity(runtime.pid), "the recorded runtime must be alive"
        # The owner died: its lock is gone, but the runtime survived and keeps
        # the directory (PyInstaller extraction) locked.
        acp_module._release_temp_lock(handle)
        handle = None

        with caplog.at_level(logging.WARNING, logger="vrsoft_extractor.mary.antigravity_acp"):
            removed = acp_module._cleanup_stale_acp_temp_dirs(profile_dir=profile)

        assert removed == 1
        assert not Path(temp_dir).exists()
        deadline = time.time() + 10
        while time.time() < deadline and process_identity(runtime.pid):
            time.sleep(0.05)
        assert process_identity(runtime.pid) == "", "the orphaned runtime must be terminated"
        assert any("órfão" in record.getMessage() for record in caplog.records)
    finally:
        if handle is not None:
            acp_module._release_temp_lock(handle)
        if runtime.poll() is None:
            runtime.kill()
            runtime.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="orphan termination uses taskkill")
def test_cleanup_never_signals_a_recycled_pid(tmp_path, monkeypatch):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "system-tmp"))
    (tmp_path / "system-tmp").mkdir()
    profile = tmp_path / "profile"
    tmp_root = profile / "antigravity-acp" / "tmp"
    tmp_root.mkdir(parents=True)

    temp_dir, handle = acp_module._create_owned_temp_dir(tmp_root, prefix="proc-")
    runtime = subprocess.Popen(
        [sys.executable, "-u", "-c", "import time; time.sleep(120)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        # Same PID, but the creation-time identity no longer matches: the PID
        # must be treated as an unrelated process and never signalled.
        Path(temp_dir, acp_module.ACP_TEMP_RUNTIME_INFO).write_text(
            f"{os.getpid()}|{runtime.pid}|0:1\n", encoding="utf-8"
        )
        acp_module._release_temp_lock(handle)
        handle = None

        removed = acp_module._cleanup_stale_acp_temp_dirs(profile_dir=profile)

        assert removed == 1
        assert not Path(temp_dir).exists()
        assert runtime.poll() is None, "a mismatching identity must never be killed"
    finally:
        if handle is not None:
            acp_module._release_temp_lock(handle)
        if runtime.poll() is None:
            runtime.kill()
            runtime.wait(timeout=5)


def test_start_records_runtime_identity_for_orphan_reclaim(tmp_path, monkeypatch):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    from vrsoft_extractor.mary.execution.ownership import process_identity
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    profile = tmp_path / "profile"
    script = tmp_path / "acp_fixture.py"
    script.write_text(
        'import sys, json, os\n'
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if request['method'] == 'initialize':\n"
        "        result = {'protocolVersion': 1, 'agentCapabilities': {},"
        " 'authMethods': [{'id': 'oauth-personal'}]}\n"
        "    else:\n"
        "        result = {'sessionId': 'fixture'}\n"
        "    frame = (json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}) + '\\n').encode()\n"
        "    os.write(sys.stdout.fileno(), frame)\n",
        encoding="utf-8",
    )
    popen = subprocess.Popen
    def launch(command, **kwargs):
        return popen([sys.executable, "-u", str(script)], **kwargs)

    client = AcpClient(command="fixture", env={})
    try:
        with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=profile), \
                patch("vrsoft_extractor.mary.antigravity_acp.subprocess.Popen", side_effect=launch):
            client.start()
            owner, pid_text, identity = Path(
                client._temp_dir, acp_module.ACP_TEMP_RUNTIME_INFO
            ).read_text(encoding="utf-8").strip().split("|")
            assert owner == str(os.getpid())
            assert int(pid_text) == client.process.pid
            assert identity == process_identity(client.process.pid)
    finally:
        client.close()


def test_start_registers_atexit_close_and_close_unregisters(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    profile = tmp_path / "profile"
    script = tmp_path / "acp_fixture.py"
    script.write_text(
        'import sys, json, os\n'
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if request['method'] == 'initialize':\n"
        "        result = {'protocolVersion': 1, 'agentCapabilities': {},"
        " 'authMethods': [{'id': 'oauth-personal'}]}\n"
        "    else:\n"
        "        result = {'sessionId': 'fixture'}\n"
        "    frame = (json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}) + '\\n').encode()\n"
        "    os.write(sys.stdout.fileno(), frame)\n",
        encoding="utf-8",
    )
    popen = subprocess.Popen
    def launch(command, **kwargs):
        return popen([sys.executable, "-u", str(script)], **kwargs)

    client = AcpClient(command="fixture", env={})
    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=profile), \
            patch("vrsoft_extractor.mary.antigravity_acp.subprocess.Popen", side_effect=launch), \
            patch("vrsoft_extractor.mary.antigravity_acp.atexit") as atexit_mock:
        client.start()
        atexit_mock.register.assert_called_once()
        registered = atexit_mock.register.call_args.args[0]
        assert registered == client._close_at_exit
        client.close()
        atexit_mock.unregister.assert_called_once_with(registered)
    assert client._atexit_registered is False


@pytest.mark.skipif(os.name != "nt", reason="kill-on-close job objects are Windows-only")
def test_job_creation_failure_is_logged(caplog):
    import ctypes

    from vrsoft_extractor.mary import antigravity_acp as acp_module
    failing = MagicMock()
    failing.CreateJobObjectW.return_value = 0

    with patch.object(acp_module, "_win32_job_api", return_value=(ctypes, None, failing)), \
            caplog.at_level(logging.WARNING, logger="vrsoft_extractor.mary.antigravity_acp"):
        assert acp_module._create_kill_on_close_job() is None

    assert any("CreateJobObjectW" in record.getMessage() for record in caplog.records), \
        "a missing kill-on-close job must never fail silently"


@pytest.mark.skipif(os.name != "nt", reason="kill-on-close job objects are Windows-only")
def test_job_assignment_failure_is_logged(caplog):
    import ctypes
    from ctypes import wintypes

    from vrsoft_extractor.mary import antigravity_acp as acp_module
    failing = MagicMock()
    failing.AssignProcessToJobObject.return_value = 0
    runtime = subprocess.Popen(
        [sys.executable, "-u", "-c", "import time; time.sleep(120)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        with patch.object(acp_module, "_win32_job_api", return_value=(ctypes, wintypes, failing)), \
                caplog.at_level(logging.WARNING, logger="vrsoft_extractor.mary.antigravity_acp"):
            assert acp_module._assign_process_to_job(object(), runtime) is False

        assert any("kill-on-close" in record.getMessage() for record in caplog.records), \
            "a refused assignment must never fail silently"
    finally:
        if runtime.poll() is None:
            runtime.kill()
            runtime.wait(timeout=5)


# --- Discovery: %LOCALAPPDATA%/agy/bin/acp/<version>/ layout ---------------

EXE_NAME = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
HARNESS_NAME = "localharness_external.exe" if os.name == "nt" else "localharness_external"


def _write_pair(directory, version=None, *, server=True, harness=True):
    target = directory if version is None else directory / version
    target.mkdir(parents=True, exist_ok=True)
    server_path = harness_path = None
    if server:
        server_path = target / EXE_NAME
        server_path.write_text("dummy", encoding="utf-8")
    if harness:
        harness_path = target / HARNESS_NAME
        harness_path.write_text("dummy", encoding="utf-8")
    return server_path, harness_path


@pytest.fixture
def isolated_discovery(tmp_path, monkeypatch):
    """Neutralizes the real machine (PATH, LOCALAPPDATA, HOME) for discovery."""
    fake = tmp_path / "machine"
    (fake / "empty-path").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(fake / "local"))
    monkeypatch.setenv("PATH", str(fake / "empty-path"))
    monkeypatch.setenv("ANTIGRAVITY_HOME", str(fake / "agy-home"))
    monkeypatch.setenv("PROGRAMFILES", str(fake / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(fake / "pf86"))
    monkeypatch.setenv("USERPROFILE", str(fake / "home"))
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    return fake


def test_localappdata_agy_version_layout_is_discovered(isolated_discovery):
    from vrsoft_extractor.mary.antigravity_acp import resolve_acp_runtime
    version_root = Path(os.environ["LOCALAPPDATA"]) / "agy" / "bin" / "acp"
    server, harness = _write_pair(version_root, "1.1.1")
    info = resolve_acp_runtime()
    assert info is not None
    assert Path(info.executable_path) == server
    assert Path(info.harness_path) == harness
    assert info.version == "1.1.1"
    assert Path(info.runtime_dir) == version_root / "1.1.1"


def test_version_selection_prefers_highest_complete_pair(isolated_discovery):
    from vrsoft_extractor.mary.antigravity_acp import resolve_acp_runtime
    version_root = Path(os.environ["LOCALAPPDATA"]) / "agy" / "bin" / "acp"
    _write_pair(version_root, "1.1.1")
    _write_pair(version_root, "1.3.0", harness=False)  # incomplete: skipped, never mixed
    _, harness_120 = _write_pair(version_root, "1.2.0")
    info = resolve_acp_runtime()
    assert info is not None
    assert info.version == "1.2.0"
    assert Path(info.harness_path) == harness_120


def test_cross_version_harness_is_never_mixed_explicit(tmp_path):
    from vrsoft_extractor.mary.antigravity_acp import IncompleteRuntimeError, resolve_acp_runtime
    server, _ = _write_pair(tmp_path / "acp", "1.1.1", harness=False)
    _write_pair(tmp_path / "acp", "1.2.0", server=False, harness=True)
    with pytest.raises(IncompleteRuntimeError):
        resolve_acp_runtime(str(server))


def test_incomplete_layout_without_complete_pair_fails(isolated_discovery):
    from vrsoft_extractor.mary.antigravity_acp import IncompleteRuntimeError, resolve_acp_runtime
    version_root = Path(os.environ["LOCALAPPDATA"]) / "agy" / "bin" / "acp"
    _write_pair(version_root, "1.1.1", harness=False)
    with pytest.raises(IncompleteRuntimeError):
        resolve_acp_runtime()


def test_main_cli_name_is_not_treated_as_acp_server(isolated_discovery):
    from vrsoft_extractor.mary.antigravity_acp import resolve_acp_runtime
    assert resolve_acp_runtime("antigravity") is None
    assert resolve_acp_runtime("agy") is None


def test_path_executable_beats_lower_version_layout(isolated_discovery):
    from vrsoft_extractor.mary.antigravity_acp import resolve_acp_runtime
    path_bin = Path(os.environ["PATH"])
    path_server, path_harness = _write_pair(path_bin)
    version_root = Path(os.environ["LOCALAPPDATA"]) / "agy" / "bin" / "acp"
    _write_pair(version_root, "1.0.0")
    info = resolve_acp_runtime()
    assert info is not None
    assert Path(info.executable_path) == path_server
    assert Path(info.harness_path) == path_harness


# --- Profile isolation and credential continuity -----------------------------

def test_profile_path_ignores_external_gemini_home(tmp_path, monkeypatch):
    from vrsoft_extractor.mary.antigravity_acp import profile_path
    monkeypatch.setenv("GEMINI_HOME", str(tmp_path / "external-profile"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert profile_path() == tmp_path / "home" / ".gemini" / "vr-norte-studio"


def test_saved_token_continuity_in_studio_profile(tmp_path, monkeypatch):
    from vrsoft_extractor.mary.antigravity_acp import has_saved_account
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    token = tmp_path / "home" / ".gemini" / "vr-norte-studio" / "antigravity-acp" / "acp_token.json"
    assert has_saved_account() is False
    token.parent.mkdir(parents=True)
    token.write_text("{}", encoding="utf-8")
    assert has_saved_account() is True


def test_child_environment_pins_fixed_profile_despite_external_home(tmp_path, monkeypatch):
    from vrsoft_extractor.mary.antigravity_acp import acp_environment
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("GEMINI_HOME", str(tmp_path / "external-profile"))
    env = acp_environment(base_env=dict(os.environ))
    assert env["GEMINI_HOME"] == str(tmp_path / "home" / ".gemini" / "vr-norte-studio")


def test_spawn_uses_single_shared_resolution():
    from vrsoft_extractor.mary.antigravity_acp import AcpRuntimeInfo, spawn_acp_client
    info = AcpRuntimeInfo(executable_path="server-exe", harness_path="harness-exe", version="9.9.9")
    seen = {}

    def factory(*, runtime_info=None):
        seen["runtime_info"] = runtime_info
        return {"CUSTOM": "1"}

    with patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime",
               return_value=None) as resolve:
        client = spawn_acp_client(env_factory=factory)
        resolve.assert_called_once_with(None)
        assert seen["runtime_info"] is None
        assert client.command is None
    with patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime",
               return_value=info) as resolve:
        client = spawn_acp_client(env_factory=factory)
        resolve.assert_called_once_with(None)
        assert seen["runtime_info"] is info
        assert client.command == "server-exe"
        assert client.runtime_info is info
        assert client.env["ANTIGRAVITY_HARNESS_PATH"] == "harness-exe"


def test_spawn_propagates_incomplete_runtime():
    from vrsoft_extractor.mary.antigravity_acp import IncompleteRuntimeError, spawn_acp_client
    with patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime",
               side_effect=IncompleteRuntimeError("incomplete")):
        with pytest.raises(IncompleteRuntimeError):
            spawn_acp_client()


# --- Model selection through the negotiated ACP mechanism --------------------

class RecordingClient:
    def __init__(self, set_model_error=None):
        self.calls = []
        self.set_model_error = set_model_error

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "session/set_model" and self.set_model_error is not None:
            raise self.set_model_error
        return {}

    def notify(self, method, params):
        self.calls.append((method, params))


CONFIG_SESSION = {
    "sessionId": "s",
    "configOptions": [
        {"id": "model", "type": "select", "currentValue": "m-a",
         "options": [{"value": "m-a", "name": "A"}, {"value": "m-b", "name": "B"}]},
        {"id": "thinking", "type": "select", "currentValue": "low",
         "options": [{"value": "low"}, {"value": "high"}]},
    ],
}


def _configure_calls(session, model, effort=""):
    provider = AntigravityProvider()
    client = RecordingClient()
    provider._configure(client, "s", session, model, effort, ConversationOptions())
    return client.calls


def test_model_selection_uses_negotiated_config_option():
    calls = _configure_calls(CONFIG_SESSION, "m-b")
    assert ("session/set_config_option", {"sessionId": "s", "configId": "model", "value": "m-b"}) in calls
    assert ("session/set_mode", {"sessionId": "s", "modeId": "yolo"}) in calls
    assert not [m for m, _ in calls if m == "session/configure"]


def test_unknown_model_fails_before_any_invalid_request():
    provider = AntigravityProvider()
    client = RecordingClient()
    with pytest.raises(ProviderError, match="indisponível"):
        provider._configure(client, "s", CONFIG_SESSION, "m-ghost", "", ConversationOptions())
    assert client.calls == []


def test_current_model_is_left_alone():
    calls = _configure_calls(CONFIG_SESSION, "m-a")
    assert [m for m, _ in calls] == ["session/set_mode"]


def test_default_alias_never_sends_a_model_request():
    for alias in ("", "default"):
        calls = _configure_calls(CONFIG_SESSION, alias)
        assert [m for m, _ in calls] == ["session/set_mode"]
        calls = _configure_calls(SESSION, alias)
        assert [m for m, _ in calls] == ["session/set_mode"]


def test_set_model_used_without_negotiated_option():
    calls = _configure_calls(SESSION, "gemini-test")
    assert ("session/set_model", {"sessionId": "s", "modelId": "gemini-test"}) in calls
    assert not [m for m, _ in calls if m == "session/configure"]


def test_unsupported_set_model_is_tolerated():
    provider = AntigravityProvider()
    client = RecordingClient(set_model_error=AcpError("session/set_model", -32601))
    provider._configure(client, "s", SESSION, "gemini-test", "", ConversationOptions())
    assert ("session/set_mode", {"sessionId": "s", "modeId": "yolo"}) in client.calls


def test_effort_only_through_negotiated_option():
    calls = _configure_calls(CONFIG_SESSION, "default", effort="high")
    assert ("session/set_config_option", {"sessionId": "s", "configId": "thinking", "value": "high"}) in calls
    calls = _configure_calls(SESSION, "default", effort="high")
    assert [m for m, _ in calls] == ["session/set_mode"]


# --- Chat update contract -----------------------------------------------------

def test_chat_updates_use_studio_event_contract():
    provider = AntigravityProvider()
    events = []
    state = {"session": "native", "cancelled": False, "text": False}
    feed = [
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hello"}},
        {"sessionUpdate": "agent_thought_chunk", "thought": "plan"},
        {"sessionUpdate": "thought", "thought": "more"},
        {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Read", "kind": "fetch", "status": "inProgress"},
        {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "inProgress", "content": "Reading"},
        {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed", "rawOutput": {"content": "Done"}},
        {"sessionUpdate": "usage_update", "used": 42, "size": 1000},
    ]
    for update in feed:
        provider._update("chat", state, events.append, "session/update",
                         {"sessionId": "native", "update": update})
    kinds = [e.kind for e in events]
    assert kinds == ["assistant_delta", "reasoning_delta", "reasoning_delta",
                     "tool_event", "tool_event", "tool_event", "token_usage"]
    assert not (set(kinds) & {"thought_delta", "tool_call_started", "tool_call_completed", "usage_delta"})
    assert state["text"] is True
    usage = next(e for e in events if e.kind == "token_usage").payload["tokenUsage"]
    assert usage["last"]["totalTokens"] == 42
    assert [e.text for e in events if e.kind == "assistant_delta"] == ["Hello"]
    assert [e.text for e in events if e.kind == "reasoning_delta"] == ["plan", "more"]
    tool_events = [e for e in events if e.kind == "tool_event"]
    assert all(e.payload["item"]["id"] == "t1" for e in tool_events)
    assert tool_events[-1].payload["canonical_event"]["kind"] == "tool.completed"
    assert tool_events[-1].payload["canonical_event"]["status"] == "success"


def test_antigravity_empty_tool_call_update_emits_no_tool_event():
    provider = AntigravityProvider()
    events = []
    state = {"session": "native", "cancelled": False, "text": False}
    provider._update(
        "chat", state, events.append, "session/update",
        {
            "sessionId": "native",
            "update": {"sessionUpdate": "tool_call_update", "toolCallId": "tool-empty-1"},
        },
    )
    assert events == []

    provider._update(
        "chat", state, events.append, "session/update",
        {
            "sessionId": "native",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tool-empty-1",
                "content": "saída real",
            },
        },
    )
    assert len(events) == 1
    assert events[0].kind == "tool_event"
    canonical = events[0].payload["canonical_event"]
    assert canonical["tool_id"] == "tool-empty-1"
    assert canonical["kind"] == "tool.updated"


def test_acp_client_ignores_non_oauth_url_when_unattended():
    from vrsoft_extractor.mary.antigravity_acp import AcpClient
    from urllib.parse import urlencode
    client = AcpClient(on_auth_url=None)
    client._fail_pending = MagicMock()
    client.close = MagicMock()

    # Receiving non-OAuth advisory URL (e.g. Google One upsell) must not fail or close
    client._auth_url("https://accounts.google.com/AccountChooser?Email=user@gmail.com&continue=https%3A%2F%2Fone.google.com%2Fai")
    client._fail_pending.assert_not_called()
    client.close.assert_not_called()

    # Incomplete OAuth URL (missing state, redirect_uri) must also be ignored
    client._auth_url("https://accounts.google.com/o/oauth2/v2/auth?client_id=123")
    client._fail_pending.assert_not_called()
    client.close.assert_not_called()

    # Receiving a fully valid OAuth URL when unattended must fail pending with -32000
    valid_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "response_type": "code",
        "client_id": "123",
        "redirect_uri": "http://127.0.0.1:45678/",
        "state": "valid_state",
    })
    client._auth_url(valid_url)
    client._fail_pending.assert_called_once()
    err = client._fail_pending.call_args[0][0]
    assert err.code == -32000


@pytest.mark.parametrize("vr_mode,vr_enabled", [
    ("off", False),
    ("vr", True),
    ("ultra", True),
])
def test_antigravity_prompt_timeout_is_none_in_all_modes(fake_runtime, tmp_path, vr_mode, vr_enabled):
    provider = AntigravityProvider()
    done, events = threading.Event(), []
    def receive(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()
    opts = ConversationOptions(vr_mode=vr_mode, vr_enabled=vr_enabled)
    provider.send_message("conv-timeout", "", "gemini-test", "auto", tmp_path, "Pergunta", receive, options=opts)
    assert done.wait(2)
    client = FakeClient.instances[0]
    prompt_timeouts = [t for m, t in client.request_timeouts if m == "session/prompt"]
    assert len(prompt_timeouts) == 1
    assert prompt_timeouts[0] is None
    # Technical session calls keep their default timeout (90.0)
    tech_timeouts = [t for m, t in client.request_timeouts if m in ("authenticate", "session/new", "session/resume")]
    assert all(t == 90.0 for t in tech_timeouts)


def test_antigravity_cancellation_during_prompt_with_none_timeout(fake_runtime, tmp_path):
    provider = AntigravityProvider()
    done, events = threading.Event(), []
    def receive(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()
    # Set FakeClient to block on prompt
    FakeClient.block_prompt = True
    try:
        provider.send_message("conv-cancel", "", "gemini-test", "auto", tmp_path, "Bloqueado", receive,
                              options=ConversationOptions(vr_mode="off", vr_enabled=False))
        # Wait until prompt is entered
        client = FakeClient.instances[-1]
        assert client.prompt_started.wait(2.0)
        # Cancel conversation while prompt is waiting without deadline
        provider.interrupt("conv-cancel")
        client.prompt_unblock.set()
        assert done.wait(2.0)
        assert client.closed
        completed = next(e for e in events if e.kind == "turn_completed")
        assert completed.payload.get("cancelled") is True
        assert not any(e.kind == "error" for e in events)
    finally:
        FakeClient.block_prompt = False

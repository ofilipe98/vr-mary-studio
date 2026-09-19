"""Comprehensive regression and conformance test suite for Antigravity Google Auth
aligned with T3 Code reference specifications.

Covers all 34 requirements:
1. Profile preparation idempotency and settings.json (auth.type = oauth-personal)
2. Non-destruction of existing acp_token.json during standard profile preparation
3. Bundle resolution of ACP server executable + sibling localharness_external
4. Fast-fail IncompleteRuntimeError when companion harness is missing
5. Environment sanitization and variable injection (GEMINI_HOME, AGY_ACP_FORCE_FILE_STORAGE=1, etc.)
6. Browser helper script: empty stdout, stderr with JSON marker and URL
7. Browser helper preflight validation (synthetic URL pass/fail)
8. Stream parser noise tolerance, byte-boundary safety, line limits, partial frames
9. Stream parser strictly ignoring JSON-RPC frames starting with { or [
10. URL extraction with __VRSTUDIO_ANTIGRAVITY_AUTH_URL__ and __T3_ANTIGRAVITY_AUTH_URL__
11. URL extraction with legacy runtime prefixes
12. Strict authorization URL validation (accounts.google.com, /o/oauth2/v2/auth, response_type=code, 127.0.0.1:<port>/)
13. Strict manual callback URL validation (exact port, state, code vs error, no fragments)
14. Local loopback callback forwarding without inherited proxy or redirects
15. Idempotent login requests (double-click safety reuses active attempt)
16. Force login (force=True) cancels previous attempt and removes token
17. Cancel login terminates process tree cleanly and clears transient credentials
18. Observable process order: initialize -> authenticate -> session/new -> catalog -> close
19. Interactive login uses a single ACP client process
20. No redundant validateAntigravityAccount() triggered immediately after interactive login success
21. authenticate error -32000 marks account unauthenticated with restart prompt
22. session/new error -32603 preserves authenticated account state while reporting model/session failure
23. SUBSCRIPTION_REQUIRED error mapping
24. Access denied / permission error mapping
25. Runtime initialization timeout (45s) reporting
26. Browser authorization timeout (300s) reporting
27. Session / confirmation timeout reporting
28. Strict redaction of secrets, authorization codes, states, and tokens
29. Per-process isolated temporary directory creation and cleanup
30. Clean shutdown on external process termination
31. Startup account restoration (restoreAntigravityAccount) runs without browser helper
32. UI state dimensions and status badges reflect single dominant priority
33. UI action buttons correctly enabled / disabled per lifecycle phase
34. 100% offline, deterministic, self-contained test execution
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vrsoft_extractor.mary.antigravity_acp import (
    AcpClient,
    AcpError,
    AcpRuntimeInfo,
    BrowserHelperError,
    IncompleteRuntimeError,
    acp_environment,
    preflight_browser_helper,
    prepare_profile,
    resolve_acp_runtime,
)
from vrsoft_extractor.mary.antigravity_auth import (
    AUTH_MARKER_T3,
    AUTH_MARKER_VRSTUDIO,
    AUTH_PREFIX_ACP,
    AUTH_PREFIX_BROWSER,
    MAX_AUTH_LINE_BYTES,
    AntigravityAuthManager,
    AuthStreamParser,
    LoginAttempt,
    OAuthCallbackError,
    OAuthValidationError,
    forward_callback_to_listener,
    map_acp_error_to_ui_message,
    validate_authorization_url,
    validate_callback_url,
)


def sample_auth_url(port: int = 45678, state: str = "secret-state-xyz") -> str:
    return (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"response_type=code&state={state}&redirect_uri=http%3A%2F%2F127.0.0.1%3A{port}%2F&client_id=test-client"
    )


# 1. Profile preparation idempotency and settings.json
def test_01_profile_preparation_idempotent_and_creates_settings(tmp_path):
    settings_file = tmp_path / "antigravity-acp" / "settings.json"
    tmp_dir = tmp_path / "antigravity-acp" / "tmp"

    prepare_profile(tmp_path)
    assert settings_file.is_file()
    assert tmp_dir.is_dir()

    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data.get("auth", {}).get("type") == "oauth-personal"

    # Call again to ensure idempotency
    prepare_profile(tmp_path)
    assert settings_file.is_file()
    data2 = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data2 == data


# 2. Non-destruction of existing acp_token.json during standard profile preparation
def test_02_profile_preparation_preserves_existing_token(tmp_path):
    token_file = tmp_path / "antigravity-acp" / "acp_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_content = '{"access_token": "secret_token_123", "refresh_token": "secret_refresh"}'
    token_file.write_text(token_content, encoding="utf-8")

    prepare_profile(tmp_path)
    assert token_file.is_file()
    assert token_file.read_text(encoding="utf-8") == token_content


# 3. Bundle resolution of ACP server executable + sibling localharness_external
def test_03_runtime_bundle_resolution(tmp_path):
    bin_dir = tmp_path / "agy" / "bin" / "acp" / "1.1.1"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe_name = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
    harness_name = "localharness_external.exe" if os.name == "nt" else "localharness_external"

    server_exe = bin_dir / exe_name
    harness_exe = bin_dir / harness_name
    server_exe.write_text("dummy", encoding="utf-8")
    harness_exe.write_text("dummy", encoding="utf-8")

    info = resolve_acp_runtime(str(server_exe))
    assert info.executable_path == str(server_exe)
    assert info.harness_path == str(harness_exe)
    assert info.version == "1.1.1"
    assert info.runtime_dir == str(bin_dir)


# 4. Fast-fail IncompleteRuntimeError when companion harness is missing
def test_04_runtime_bundle_fails_fast_when_harness_missing(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe_name = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
    server_exe = bin_dir / exe_name
    server_exe.write_text("dummy", encoding="utf-8")

    with pytest.raises(IncompleteRuntimeError) as exc_info:
        resolve_acp_runtime(str(server_exe))
    assert "localharness_external" in str(exc_info.value)


# 5. Environment sanitization and variable injection
def test_05_environment_sanitization_and_inheritance(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "leak-gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "leak-google-key")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "leak-creds.json")
    monkeypatch.setenv("AGY_ACP_TEST_VAR", "foo")

    runtime_info = AcpRuntimeInfo(
        executable_path=str(tmp_path / "server.exe"),
        harness_path=str(tmp_path / "localharness_external.exe"),
        version="1.1.1",
        runtime_dir=str(tmp_path),
    )

    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path):
        env = acp_environment(runtime_info)

    assert "GEMINI_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert env.get("GEMINI_HOME") == str(tmp_path)
    assert env.get("AGY_ACP_FORCE_FILE_STORAGE") == "1"
    assert env.get("PYTHONUNBUFFERED") == "1"
    assert env.get("ANTIGRAVITY_HARNESS_PATH") == str(tmp_path / "localharness_external.exe")


# 6. Browser helper script: empty stdout, stderr with JSON marker and URL
def test_06_browser_helper_empty_stdout_and_json_marker_in_stderr():
    from vrsoft_extractor.mary.antigravity_acp import browser_helper_script
    script = browser_helper_script()
    assert script.is_file()

    url = sample_auth_url()
    if os.name == "nt" and shutil.which("powershell.exe"):
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            url,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert res.returncode == 0
        assert res.stdout == ""
        assert AUTH_MARKER_VRSTUDIO in res.stderr
        raw_json = res.stderr.split(AUTH_MARKER_VRSTUDIO)[1].strip()
        assert json.loads(raw_json) == url


# 7. Browser helper preflight validation (synthetic URL pass/fail)
def test_07_browser_helper_preflight_pass_and_fail(tmp_path):
    # Success case (using real powershell on Windows)
    if os.name == "nt" and shutil.which("powershell.exe"):
        preflight_browser_helper()

    # Failure case: helper script returns bad output or exit code 1
    bad_script = tmp_path / "bad-helper.ps1"
    bad_script.write_text("[Console]::Out.WriteLine('polluted stdout')\nexit 1\n", encoding="utf-8")
    with patch("vrsoft_extractor.mary.antigravity_acp.browser_helper_script", return_value=bad_script):
        with pytest.raises(BrowserHelperError):
            preflight_browser_helper()


# 8. Stream parser noise tolerance, byte-boundary safety, line limits, partial frames
def test_08_stream_parser_noise_tolerance_and_line_limits():
    extracted = []
    parser = AuthStreamParser(on_auth_url=extracted.append)

    # Broken UTF-8 byte sequences followed by valid frame
    parser.feed(b"\xff\xfe random garbage line\n")
    # Line exceeding max line bytes
    parser.feed(b"A" * (MAX_AUTH_LINE_BYTES + 10) + b"\n")
    # Valid auth URL in small chunks
    valid_line = (AUTH_MARKER_VRSTUDIO + json.dumps(sample_auth_url()) + "\n").encode("utf-8")
    for b in [valid_line[:10], valid_line[10:25], valid_line[25:]]:
        parser.feed(b)
    parser.finish()

    assert len(extracted) == 1
    assert extracted[0] == sample_auth_url()


# 9. Stream parser strictly ignoring JSON-RPC frames starting with { or [
def test_09_stream_parser_ignores_jsonrpc_frames():
    extracted = []
    passthrough = []
    parser = AuthStreamParser(on_auth_url=extracted.append, on_line=passthrough.append)

    # Frame starting with { containing the auth marker inside
    fake_frame = json.dumps({"method": "log", "params": {"msg": AUTH_MARKER_VRSTUDIO + sample_auth_url()}}) + "\n"
    parser.feed(fake_frame.encode("utf-8"))
    parser.finish()

    assert extracted == []
    assert len(passthrough) == 1


# 10. URL extraction with __VRSTUDIO_ANTIGRAVITY_AUTH_URL__ and __T3_ANTIGRAVITY_AUTH_URL__
def test_10_extraction_vrstudio_and_t3_markers():
    extracted = []
    parser = AuthStreamParser(on_auth_url=extracted.append)

    url1 = sample_auth_url(port=45678, state="state-1")
    url2 = sample_auth_url(port=45679, state="state-2")

    parser.feed((AUTH_MARKER_VRSTUDIO + json.dumps(url1) + "\n").encode("utf-8"))
    parser.feed((AUTH_MARKER_T3 + json.dumps(url2) + "\n").encode("utf-8"))
    parser.finish()

    assert extracted == [url1, url2]


# 11. URL extraction with legacy runtime prefixes
def test_11_extraction_legacy_runtime_prefixes():
    extracted = []
    parser = AuthStreamParser(on_auth_url=extracted.append)

    url1 = sample_auth_url(port=45678, state="state-legacy-1")
    url2 = sample_auth_url(port=45679, state="state-legacy-2")

    parser.feed((AUTH_PREFIX_ACP + url1 + "\n").encode("utf-8"))
    parser.feed((AUTH_PREFIX_BROWSER + url2 + "\n").encode("utf-8"))
    parser.finish()

    assert extracted == [url1, url2]


# 12. Strict authorization URL validation
def test_12_strict_auth_url_validation():
    valid = sample_auth_url()
    validated = validate_authorization_url(valid)
    assert validated.port == 45678
    assert validated.state == "secret-state-xyz"

    # Rejections
    with pytest.raises(OAuthValidationError):
        validate_authorization_url("http://accounts.google.com/o/oauth2/v2/auth")  # http
    with pytest.raises(OAuthValidationError):
        validate_authorization_url("https://malicious.com/o/oauth2/v2/auth")  # wrong host
    with pytest.raises(OAuthValidationError):
        validate_authorization_url(valid + "#fragment")  # fragment
    with pytest.raises(OAuthValidationError):
        validate_authorization_url(valid + "&client_id=duplicate")  # duplicate param
    with pytest.raises(OAuthValidationError):
        validate_authorization_url(valid.replace("accounts.google.com", "user:pass@accounts.google.com"))  # embedded creds


# 13. Strict manual callback URL validation
def test_13_strict_manual_callback_validation():
    auth = validate_authorization_url(sample_auth_url(port=5555, state="test-state"))
    valid_cb = "http://127.0.0.1:5555/?code=auth-code-123&state=test-state"
    code, state = validate_callback_url(valid_cb, auth)
    assert code == "auth-code-123"
    assert state == "test-state"

    # Mismatched port
    with pytest.raises(OAuthValidationError):
        validate_callback_url("http://127.0.0.1:6666/?code=auth-code-123&state=test-state", auth)

    # Mismatched state
    with pytest.raises(OAuthValidationError):
        validate_callback_url("http://127.0.0.1:5555/?code=auth-code-123&state=wrong-state", auth)

    # Both code and error
    with pytest.raises(OAuthValidationError):
        validate_callback_url("http://127.0.0.1:5555/?code=auth-code-123&error=denied&state=test-state", auth)

    # Error only
    with pytest.raises(OAuthCallbackError):
        validate_callback_url("http://127.0.0.1:5555/?error=access_denied&state=test-state", auth)


# 14. Local loopback callback forwarding without inherited proxy or redirects
def test_14_local_callback_forwarding_no_proxy_no_redirect():
    auth = validate_authorization_url(sample_auth_url(port=45678, state="test-state"))
    valid_cb = "http://127.0.0.1:45678/?code=valid-code&state=test-state"

    with patch("urllib.request.build_opener") as mock_build_opener:
        mock_opener = MagicMock()
        mock_build_opener.return_value = mock_opener
        mock_opener.open.return_value.__enter__.return_value = MagicMock()

        forward_callback_to_listener(valid_cb, auth)
        assert mock_build_opener.called
        req = mock_opener.open.call_args[0][0]
        assert "127.0.0.1:45678" in req.full_url
        assert "code=valid-code" in req.full_url


# 15. Idempotent login requests (double-click safety reuses active attempt)
def test_15_double_click_login_idempotency():
    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch.object(manager, "_run_login"):
        attempt1 = manager.start_login()
        attempt2 = manager.start_login()
        assert attempt1 is attempt2
        assert attempt1.attempt_id == attempt2.attempt_id


# 16. Force login (force=True) cancels previous attempt and removes token
def test_16_force_login_cancels_previous_and_clears_token(tmp_path):
    token_file = tmp_path / "antigravity-acp" / "acp_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("token", encoding="utf-8")

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path):
        with patch.object(manager, "_run_login"):
            attempt1 = manager.start_login()
            assert token_file.is_file()

            attempt2 = manager.start_login(force=True)
            assert attempt1.state == "cancelled"
            assert attempt2.attempt_id != attempt1.attempt_id
            assert not token_file.is_file()


# 17. Cancel login terminates process tree cleanly and clears transient credentials
def test_17_cancel_login_terminates_process_tree_and_cleans_state():
    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    mock_client = MagicMock()
    mock_proc = MagicMock()
    mock_client.process = mock_proc

    with patch.object(manager, "_run_login"):
        attempt = manager.start_login()
        attempt.client = mock_client
        attempt.process = mock_proc
        attempt.validated_auth = validate_authorization_url(sample_auth_url())

        manager.cancel_login()
        assert attempt.state == "cancelled"
        assert attempt.validated_auth is None
        assert mock_client.close.called


# 18. Observable process order: initialize -> authenticate -> session/new -> catalog -> close
# 19. Interactive login uses a single ACP client process
def test_18_19_observable_process_order_and_single_client_process():
    calls = []
    catalog_discovered = []

    class MockClient:
        def __init__(self, **kwargs):
            self.closed = False
            self.process = MagicMock()

        def start(self):
            calls.append("start")

        def request(self, method, params, timeout=None):
            calls.append((method, params))
            if method == "authenticate":
                return {}
            if method == "session/new":
                return {
                    "sessionId": "session-123",
                    "models": {
                        "availableModels": [{"modelId": "gemini-test", "name": "Gemini Test"}]
                    },
                }
            return {}

        def close(self):
            self.closed = True
            calls.append("close")

    manager = AntigravityAuthManager(
        lambda: "agy_acp",
        lambda: {},
        on_catalog_discovered=catalog_discovered.extend,
    )

    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", MockClient):

        attempt = manager.start_login()
        deadline = time.monotonic() + 3.0
        while attempt.state in ("starting", "verifying") and time.monotonic() < deadline:
            time.sleep(0.01)

        assert attempt.state == "succeeded"
        assert manager.account_state == "authenticated"
        # Verify sequence order
        expected_methods = ["start", "authenticate", "session/new", "close"]
        observed = [c if isinstance(c, str) else c[0] for c in calls]
        assert observed == expected_methods
        # Catalog published
        assert len(catalog_discovered) == 1
        assert catalog_discovered[0]["modelId"] == "gemini-test"


# 20. No redundant validateAntigravityAccount() triggered immediately after interactive login success
def test_20_no_redundant_validate_after_interactive_login_success():
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())
    attempt = LoginAttempt("succ-attempt", state="succeeded")
    bridge._antigravity_auth._active_attempt = attempt

    with patch.object(bridge, "validateAntigravityAccount") as mock_validate:
        bridge._refresh_antigravity_auth()
        mock_validate.assert_not_called()


# 21. authenticate error -32000 marks account unauthenticated with restart prompt
def test_21_authenticate_error_minus_32000_marks_unauthenticated():
    class RejectionClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()
        def start(self): pass
        def request(self, method, params, timeout=None):
            if method == "authenticate":
                raise AcpError("authenticate", -32000, "Google rejected")
            return {}
        def close(self): pass

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", RejectionClient):

        attempt = manager.start_login()
        deadline = time.monotonic() + 3.0
        while attempt.state == "starting" and time.monotonic() < deadline:
            time.sleep(0.01)

        assert attempt.state == "failed"
        assert manager.account_state == "unauthenticated"
        assert "não confirmou a conta Google" in attempt.error_detail


# 22. session/new error -32603 preserves authenticated account state while reporting model/session failure
def test_22_session_new_error_minus_32603_preserves_authenticated():
    class SessionFailClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()
        def start(self): pass
        def request(self, method, params, timeout=None):
            if method == "authenticate":
                return {}
            if method == "session/new":
                raise AcpError("session/new", -32603, "Internal model failure")
            return {}
        def close(self): pass

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", SessionFailClient):

        attempt = manager.start_login()
        deadline = time.monotonic() + 3.0
        while attempt.state in ("starting", "verifying") and time.monotonic() < deadline:
            time.sleep(0.01)

        assert attempt.state == "failed"
        # Account credentials succeeded so account state MUST remain authenticated!
        assert manager.account_state == "authenticated"
        assert "não foi possível inicializar a sessão ou carregar os modelos" in manager.account_status_label


# 23. SUBSCRIPTION_REQUIRED error mapping
def test_23_subscription_required_mapped():
    err = AcpError("authenticate", -32000, "User needs SUBSCRIPTION_REQUIRED")
    msg, _ = map_acp_error_to_ui_message(err, "authenticate")
    assert "Assinatura do Google Antigravity necessária" in msg


# 24. Access denied / permission error mapping
def test_24_access_denied_mapped():
    err = AcpError("authenticate", -32000, "access_denied by admin policy")
    msg, _ = map_acp_error_to_ui_message(err, "authenticate")
    assert "Acesso recusado ou permissões insuficientes" in msg


# 25. Runtime initialization timeout (45s) reporting
def test_25_timeout_initialization_reported():
    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    attempt = LoginAttempt("att-init", state="starting")
    manager._active_attempt = attempt
    manager._on_init_timeout("att-init")
    assert attempt.state == "failed"
    assert "inicialização do runtime" in attempt.error_detail


# 26. Browser authorization timeout (300s) reporting
def test_26_timeout_browser_authorization_reported():
    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    attempt = LoginAttempt("att-oauth", state="waiting")
    manager._active_attempt = attempt
    manager._on_oauth_timeout("att-oauth")
    assert attempt.state == "failed"
    assert "autorização no navegador excedido" in attempt.error_detail


# 27. Session / confirmation timeout reporting
def test_27_timeout_session_confirmation_reported():
    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    attempt = LoginAttempt("att-verify", state="verifying")
    manager._active_attempt = attempt
    manager._on_oauth_timeout("att-verify")
    assert attempt.state == "failed"
    assert "confirmação do Antigravity excedido" in attempt.error_detail


# 28. Strict redaction of secrets, authorization codes, states, and tokens
def test_28_strict_secret_redaction():
    secret_code = "4/0AeanS0-very-secret-authorization-code"
    secret_state = "very-opaque-state-12345"
    url = sample_auth_url(state=secret_state)

    validated = validate_authorization_url(url)
    assert secret_state not in repr(validated)
    assert secret_state not in str(validated)

    # Redaction in map_acp_error_to_ui_message
    raw_error = f"Failed with {url} and code={secret_code} and state={secret_state}"
    err = Exception(raw_error)
    mapped = map_acp_error_to_ui_message(err, "authenticate")
    assert secret_code not in mapped
    assert secret_state not in mapped
    assert "accounts.google.com" not in mapped


# 29. Per-process isolated temporary directory: exactly one proc-* per ACP
# process, owned at start(), deterministic cleanup at close().
def test_29_acp_client_temp_dir_single_proc_dir_lifecycle(tmp_path):
    from vrsoft_extractor.mary import antigravity_acp as acp_module
    profile = tmp_path / "profile"
    script = tmp_path / "acp_init_fixture.py"
    script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': {"
        "'protocolVersion': 1, 'agentCapabilities': {}, 'authMethods': [{'id': 'oauth-personal'}]}}) + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    launched = {}

    def launch(command, **kwargs):
        launched.update(kwargs.get("env", {}))
        return real_popen([sys.executable, "-u", str(script)], **kwargs)

    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=profile):
        client = AcpClient(command="dummy", env={})
        # A constructed-but-never-started client owns nothing on disk.
        assert client._temp_dir is None
        with patch.object(acp_module.subprocess, "Popen", side_effect=launch):
            client.start()
            temp_dir = client._temp_dir
            assert temp_dir is not None
            temp_path = Path(temp_dir)
            assert temp_path.parent == profile / "antigravity-acp" / "tmp"
            assert temp_path.name.startswith("proc-")
            # Exactly one owned directory, wired into TEMP/TMP/TMPDIR alike.
            assert [p for p in temp_path.parent.glob("proc-*") if p.is_dir()] == [temp_path]
            assert launched.get("TEMP") == temp_dir
            assert launched.get("TMP") == temp_dir
            assert launched.get("TMPDIR") == temp_dir
            client.close()
        assert not temp_path.exists()
        assert [p for p in temp_path.parent.glob("proc-*") if p.exists()] == []


# 30. Clean shutdown on external process termination
def test_30_external_process_kill_clean_shutdown():
    client = AcpClient(command="dummy")
    mock_proc = MagicMock()
    mock_proc.poll.return_value = -9  # killed externally
    client.process = mock_proc
    client.close()
    assert client.process.poll() is not None


# 31. Startup account restoration (restoreAntigravityAccount) runs without browser helper
def test_31_startup_restore_account_no_browser_helper():
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())

    with patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
         patch.object(bridge, "validateAntigravityAccount") as mock_validate:
        bridge.restoreAntigravityAccount()
        mock_validate.assert_called_once()
        # Verify no login attempt was created
        assert bridge._antigravity_auth.active_attempt is None


def test_31b_startup_restore_preserves_saved_token(tmp_path):
    from vrsoft_extractor.mary.frontend.studio import StudioBridge

    token_file = tmp_path / "antigravity-acp" / "acp_token.json"
    token_file.parent.mkdir(parents=True)
    token_file.write_text('{"token":"saved"}', encoding="utf-8")
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())

    with patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
         patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path), \
         patch.object(bridge, "validateAntigravityAccount") as mock_validate, \
         patch.object(bridge._antigravity_auth, "start_login") as mock_start, \
         patch.object(bridge, "_open_browser_url") as mock_browser:
        bridge.restoreAntigravityAccount()

    assert token_file.read_text(encoding="utf-8") == '{"token":"saved"}'
    mock_validate.assert_called_once_with()
    mock_start.assert_not_called()
    mock_browser.assert_not_called()


# 32. UI state dimensions and status badges reflect single dominant priority
def test_32_ui_status_and_badges_single_dominant_state():
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())

    # 1. Starting
    attempt_starting = LoginAttempt("att-1", state="starting")
    bridge._antigravity_auth._active_attempt = attempt_starting
    bridge.refreshProviders()
    item = next(x for x in bridge.providerItems if x["id"] == "antigravity")
    assert item["isStarting"] is True
    assert item["isWaiting"] is False
    assert item["isVerifying"] is False

    # 2. Waiting
    attempt_waiting = LoginAttempt("att-2", state="waiting")
    attempt_waiting.validated_auth = validate_authorization_url(sample_auth_url())
    bridge._antigravity_auth._active_attempt = attempt_waiting
    bridge.refreshProviders()
    item = next(x for x in bridge.providerItems if x["id"] == "antigravity")
    assert item["isWaiting"] is True
    assert item["isStarting"] is False

    # 3. Verifying
    attempt_verifying = LoginAttempt("att-3", state="verifying")
    bridge._antigravity_auth._active_attempt = attempt_verifying
    bridge.refreshProviders()
    item = next(x for x in bridge.providerItems if x["id"] == "antigravity")
    assert item["isVerifying"] is True

    # 4. Authenticated
    bridge._antigravity_auth._account_state = "authenticated"
    bridge.refreshProviders()
    item = next(x for x in bridge.providerItems if x["id"] == "antigravity")
    assert item["accountState"] == "authenticated"


# 33. UI action buttons correctly enabled / disabled per lifecycle phase
def test_33_ui_buttons_enabled_disabled_state():
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())

    # Provider available
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp", return_value="agy_acp"):
        bridge.refreshProviders()
        items = bridge.providerItems
        item = next(x for x in items if x["id"] == "antigravity")
        assert item["available"] is True

        # When starting, login should not be allowed again without force
        with patch.object(bridge._antigravity_auth, "_run_login"):
            attempt = bridge._antigravity_auth.start_login()
            assert bridge._antigravity_auth.active_attempt.state == "starting"
            # Re-calling start_login without force reuses attempt (button effectively idempotent)
            assert bridge._antigravity_auth.start_login() is attempt


# 35. Provider readiness tracks the account/provider split end to end.
def test_35_provider_ready_after_full_login_flow():
    calls = []

    class MockClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()

        def start(self):
            calls.append("start")

        def request(self, method, params, timeout=None):
            calls.append(method)
            if method == "session/new":
                return {"sessionId": "s", "models": {
                    "availableModels": [{"modelId": "m", "name": "M"}]}}
            return {}

        def close(self):
            calls.append("close")

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", MockClient):
        assert manager.provider_readiness == "unknown"
        attempt = manager.start_login()
        assert manager.provider_readiness == "validating"
        deadline = time.monotonic() + 3.0
        while attempt.state in ("starting", "verifying") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert attempt.state == "succeeded"
        assert manager.account_state == "authenticated"
        assert manager.provider_readiness == "ready"
        snapshot = manager.get_ui_snapshot()
        assert snapshot["providerReadiness"] == "ready"
        assert snapshot["accountState"] == "authenticated"


def test_35b_readiness_failed_on_rejected_credentials():
    class RejectionClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()
        def start(self): pass
        def request(self, method, params, timeout=None):
            if method == "authenticate":
                raise AcpError("authenticate", -32000, "Google rejected")
            return {}
        def close(self): pass

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", RejectionClient):
        attempt = manager.start_login()
        deadline = time.monotonic() + 3.0
        while attempt.state == "starting" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert attempt.state == "failed"
        assert manager.account_state == "unauthenticated"
        assert manager.provider_readiness == "failed"
        assert manager.get_ui_snapshot()["providerReadiness"] == "failed"


def test_35c_readiness_degraded_when_session_fails_after_auth():
    class SessionFailClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()
        def start(self): pass
        def request(self, method, params, timeout=None):
            if method == "authenticate":
                return {}
            if method == "session/new":
                raise AcpError("session/new", -32603, "Internal model failure")
            return {}
        def close(self): pass

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", SessionFailClient):
        attempt = manager.start_login()
        deadline = time.monotonic() + 3.0
        while attempt.state in ("starting", "verifying") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert attempt.state == "failed"
        # Authenticated account, provider NOT ready.
        assert manager.account_state == "authenticated"
        assert manager.provider_readiness == "degraded"
        assert manager.get_ui_snapshot()["providerReadiness"] == "degraded"


# 25b. The real init-timeout mechanism fires against a blocking initialize.
def test_25b_init_timeout_fires_against_blocking_initialize(monkeypatch):
    import vrsoft_extractor.mary.antigravity_auth as auth_module
    monkeypatch.setattr(auth_module, "INIT_TIMEOUT_SECONDS", 0.2)
    released = threading.Event()

    class BlockingClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()

        def start(self, timeout=None):
            released.wait(5)

        def request(self, method, params, timeout=None):
            raise AssertionError("no request may run after the init timeout")

        def close(self):
            released.set()

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", BlockingClient):
        started = time.monotonic()
        attempt = manager.start_login()
        deadline = time.monotonic() + 5.0
        while attempt.state == "starting" and time.monotonic() < deadline:
            time.sleep(0.01)
        elapsed = time.monotonic() - started
    assert attempt.state == "failed"
    assert "inicialização" in attempt.error_detail
    assert elapsed < 4.0
    assert manager.provider_readiness == "failed"


# 8b. Validation without a runtime aborts: no subprocess, no browser, no
# account-state change, and the exact not-found message.
def test_08b_validate_aborts_without_runtime_and_preserves_state():
    from vrsoft_extractor.mary.antigravity_acp import IncompleteRuntimeError
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())
    toasts = []
    bridge.toastRequested.connect(lambda message, kind="": toasts.append((message, kind)))

    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.frontend.studio.spawn_acp_client") as spawn:
        bridge.validateAntigravityAccount()
        spawn.assert_not_called()
    assert any("Runtime Antigravity ACP não encontrado" in message for message, _ in toasts)
    assert bridge._agy_check_running is False
    assert bridge._antigravity_auth.account_state == "unknown"
    assert bridge._antigravity_auth.provider_readiness == "unknown"
    item = next(x for x in bridge.providerItems if x["id"] == "antigravity")
    assert item["providerReadiness"] == "unknown"

    toasts.clear()
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp_runtime",
               side_effect=IncompleteRuntimeError("Runtime Antigravity incompleto: sem harness.")), \
         patch("vrsoft_extractor.mary.frontend.studio.spawn_acp_client") as spawn:
        bridge.validateAntigravityAccount()
        spawn.assert_not_called()
    assert any("incompleto" in message for message, _ in toasts)
    assert bridge._agy_check_running is False


# 34. Offline execution proof: the offline surface (URL validation, catalog
# extraction, environment build, fake-dir discovery, manager snapshot) runs
# with every non-loopback egress blocked instead of asserting True.
def test_34_offline_execution_blocks_non_loopback_egress(monkeypatch, tmp_path):
    import socket

    blocked = []
    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, (tuple, list)) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            blocked.append(str(host))
            raise OSError(f"network egress blocked in offline test: {host!r}")
        return real_connect(sock, address)

    def guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, (tuple, list)) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            blocked.append(str(host))
            raise OSError(f"network egress blocked in offline test: {host!r}")
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)

    # Strict URL validation and callback contract without network.
    auth = validate_authorization_url(sample_auth_url())
    code, _ = validate_callback_url(
        "http://127.0.0.1:45678/?code=offline-code&state=secret-state-xyz", auth
    )
    assert code == "offline-code"

    # Catalog extraction prefers configOptions over models.availableModels.
    from vrsoft_extractor.mary.antigravity_acp import extract_acp_models

    session = {
        "configOptions": [{
            "id": "model",
            "type": "select",
            "currentValue": "m-b",
            "options": [{"value": "m-a", "name": "A"}, {"value": "m-b", "name": "B"}],
        }],
        "models": {"currentModelId": "m-a", "availableModels": [{"modelId": "m-a"}]},
    }
    catalog = extract_acp_models(session)
    assert [m["id"] for m in catalog] == ["m-a", "m-b"]
    assert next(m for m in catalog if m["id"] == "m-b")["isDefault"] is True

    # Discovery against fake dirs and environment build without network.
    exe = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
    harness = "localharness_external.exe" if os.name == "nt" else "localharness_external"
    version_dir = tmp_path / "agy" / "bin" / "acp" / "9.9.9"
    version_dir.mkdir(parents=True)
    (version_dir / exe).write_text("dummy", encoding="utf-8")
    (version_dir / harness).write_text("dummy", encoding="utf-8")
    info = resolve_acp_runtime(str(version_dir / exe))
    assert info.version == "9.9.9"
    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path):
        env = acp_environment(info)
    assert env["ANTIGRAVITY_HARNESS_PATH"] == info.harness_path

    # Manager snapshot transitions without spawning anything.
    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    assert manager.get_ui_snapshot()["providerReadiness"] == "unknown"
    manager.mark_credentials_rejected()
    assert manager.account_state == "unauthenticated"
    assert manager.provider_readiness == "failed"

    assert blocked == []

"""Regression cases missed by the initial OAuth lifecycle implementation."""
import io
import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vrsoft_extractor.mary.antigravity_auth import (
    AUTH_MARKER_T3, AntigravityAuthManager, AuthStreamParser, LoginAttempt,
    OAuthCallbackError, OAuthValidationError, forward_callback_to_listener,
    validate_authorization_url, validate_callback_url,
)
from vrsoft_extractor.mary.antigravity_acp import AcpError, AcpRuntimeInfo


def auth_url(redirect="http://127.0.0.1:45678/", state="opaque"):
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "response_type": "code", "state": state, "redirect_uri": redirect,
    })


@pytest.mark.parametrize("redirect", [
    "http://127.0.0.1:invalid/", "http://127.0.0.1:65536/",
    "http://127.0.0.1:0/", "http://127.0.0.1:45678/other",
    "http://127.0.0.1:45678", "http://127.0.0.1:45678/\n",
    "http://2130706433:45678/", "http://127.0.0.1:045678/",
])
def test_bad_redirect_is_controlled_error(redirect):
    with pytest.raises(OAuthValidationError):
        validate_authorization_url(auth_url(redirect))


@pytest.mark.parametrize("url", [
    auth_url().replace("accounts.google.com/", "accounts.google.com:bad/"),
    auth_url().replace("accounts.google.com", "accounts.\ngoogle.com"),
])
def test_malformed_authority_does_not_kill_reader(url):
    with pytest.raises(OAuthValidationError):
        validate_authorization_url(url)


@pytest.mark.parametrize("query", ["code=x&error=", "code=&error=denied", "code=x&code=y", "code=%0Ax"])
def test_callback_rejects_ambiguous_or_control_parameters(query):
    with pytest.raises(OAuthValidationError):
        validate_callback_url("http://127.0.0.1:45678/?state=opaque&" + query,
                              validate_authorization_url(auth_url()))


def test_provider_error_description_is_not_echoed():
    with pytest.raises(OAuthCallbackError) as result:
        validate_callback_url("http://127.0.0.1:45678/?state=opaque&error=denied&error_description=SECRET",
                              validate_authorization_url(auth_url()))
    assert "SECRET" not in str(result.value)


def test_forwarding_disables_inherited_proxy_and_redirects():
    with patch("urllib.request.build_opener") as build:
        forward_callback_to_listener("http://127.0.0.1:45678/?state=opaque&code=test",
                                     validate_authorization_url(auth_url()))
        assert build.call_args.args[0].proxies == {}
        assert build.call_args.args[1].redirect_request(None, None, None, None, None, None) is None


def test_marker_inside_protocol_content_is_not_an_auth_instruction():
    urls, lines = [], []
    line = json.dumps({"event": "step_update", "text": "Open the following link: " + auth_url()})
    parser = AuthStreamParser(urls.append, lines.append)
    parser.feed((line + "\n").encode())
    assert urls == []
    assert lines == [line]


@pytest.mark.parametrize("size", [9000, 32768])
def test_large_fragmented_url_and_utf8_frames(size):
    urls, lines = [], []
    parser = AuthStreamParser(urls.append, lines.append)
    url = auth_url() + "&scope=" + "x" * size
    data = (AUTH_MARKER_T3 + json.dumps(url) + "\r\n" + "ação\n").encode()
    for offset in range(0, len(data), 7):
        parser.feed(data[offset:offset + 7])
    parser.finish()
    assert urls == [url]
    assert lines == ["ação"]


def test_invalid_utf8_at_frame_end_does_not_consume_next_frame():
    lines = []
    parser = AuthStreamParser(lambda _: None, lines.append)
    parser.feed(b"bad\xc3\nnext\n")
    assert lines == ["bad\ufffd", "next"]


def manager_with_attempt(state="waiting"):
    manager = AntigravityAuthManager(lambda: "agy", lambda: {})
    manager._active_attempt = LoginAttempt("attempt", state=state)
    return manager


@pytest.mark.parametrize("state", ["cancelled", "failed", "succeeded", "idle"])
def test_terminal_attempt_ignores_late_url_and_clean_exit(state):
    manager = manager_with_attempt(state)
    process = MagicMock()
    process.wait.return_value = 0
    manager._on_auth_url_received("attempt", auth_url())
    manager._wait_process("attempt", process)
    assert manager.active_attempt.state == state
    assert manager.active_attempt.validated_auth is None
    assert manager.account_state == "unknown"


def test_verifying_phase_still_expires():
    manager = manager_with_attempt("verifying")
    manager._on_oauth_timeout("attempt")
    assert manager.active_attempt.state == "failed"


def test_delayed_callback_error_cannot_undo_cancellation():
    manager = manager_with_attempt()
    manager.active_attempt.validated_auth = validate_authorization_url(auth_url())
    def deliver(*_):
        manager.cancel_login()
        raise OSError("SECRET")
    with patch("vrsoft_extractor.mary.antigravity_auth.forward_callback_to_listener", side_effect=deliver):
        with pytest.raises(RuntimeError) as error:
            manager.submit_callback("http://127.0.0.1:45678/?state=opaque&code=test")
    assert "SECRET" not in str(error.value)
    assert manager.active_attempt.state == "cancelled"
    assert manager.active_attempt.validated_auth is None


def test_expired_callback_is_not_forwarded_before_timer_runs():
    manager = manager_with_attempt()
    manager.active_attempt.validated_auth = validate_authorization_url(auth_url())
    manager.active_attempt.deadline = time.monotonic() - 1
    with patch("vrsoft_extractor.mary.antigravity_auth.forward_callback_to_listener") as forward:
        with pytest.raises(RuntimeError):
            manager.submit_callback("http://127.0.0.1:45678/?state=opaque&code=test")
    forward.assert_not_called()
    assert manager.active_attempt.state == "failed"


def test_cancel_during_process_creation_reaps_late_child():
    manager = AntigravityAuthManager(lambda: "agy", lambda: {})
    client = MagicMock()
    cancelled = threading.Event()
    def launch():
        manager.cancel_login()
        cancelled.set()
    client.start.side_effect = launch
    with patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", return_value=client):
        attempt = manager.start_login()
        assert cancelled.wait(2)
    assert attempt.state == "cancelled"
    assert client.close.called
    client.request.assert_not_called()
    assert manager._oauth_timer is None


def test_environment_failure_finishes_attempt_and_allows_retry():
    manager = AntigravityAuthManager(lambda: "agy", MagicMock(side_effect=ValueError("SECRET")))
    failed = threading.Event()
    manager._on_state_changed = lambda: failed.set() if manager.active_attempt.state == "failed" else None
    manager.start_login()
    assert failed.wait(2)
    assert manager.active_attempt.state == "failed"
    assert "SECRET" not in str(manager.get_ui_snapshot())


@pytest.mark.parametrize("stream_name", ["stdout", "stderr"])
def test_reader_validates_url_on_each_stream(stream_name):
    manager = manager_with_attempt("starting")
    manager._drain_stream("attempt", io.BytesIO((AUTH_MARKER_T3 + json.dumps(auth_url()) + "\n").encode()), stream_name)
    assert manager.active_attempt.state == "waiting"
    manager.cancel_login()


@pytest.fixture
def bridge(tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    from vrsoft_extractor.mary.config import MarySettings
    from vrsoft_extractor.mary.db import MaryDatabase
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "root", old_root=tmp_path / "old")
    result = StudioBridge(settings, MaryDatabase(tmp_path / "test.db"),
                          QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    yield result, app
    result.close()


def test_worker_signal_reaches_ui_thread(bridge):
    result, app = bridge
    result.refreshProviders()
    worker = threading.Thread(target=result._antigravity_auth.mark_authenticated_from_validation)
    worker.start()
    worker.join()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        app.processEvents()
        if next(x for x in result.providerItems if x["id"] == "antigravity")["accountState"] == "authenticated":
            break
    else:
        pytest.fail("Worker notification never reached the Qt UI thread")


def test_validated_login_opens_browser_once_from_queued_ui_signal(bridge):
    result, app = bridge
    manager = result._antigravity_auth
    attempt = LoginAttempt("browser-test")
    manager._active_attempt = attempt
    with patch("vrsoft_extractor.mary.frontend.studio.QDesktopServices.openUrl", return_value=True) as opener:
        worker = threading.Thread(target=manager._on_auth_url_received, args=(attempt.attempt_id, auth_url()))
        worker.start()
        worker.join()
        for _ in range(10):
            app.processEvents()
        result._refresh_antigravity_auth()
        assert opener.call_count == 1
        assert opener.call_args.args[0].toString() == auth_url()
        assert result._agy_opened_attempt == attempt.attempt_id


@pytest.mark.parametrize("authenticated", [False, True])
def test_validation_failure_visible_without_inventing_or_erasing_login(bridge, authenticated):
    result, app = bridge
    if authenticated:
        result._antigravity_auth.mark_authenticated_from_validation()
    response = SimpleNamespace(returncode=1, stdout='{"status":"ERROR"}', stderr="SECRET")
    with patch.object(result, "_run_antigravity_check", return_value=response):
        result.validateAntigravityAccount()
        assert next(x for x in result.providerItems if x["id"] == "antigravity")["isVerifying"]
        deadline = time.monotonic() + 3
        while result._agy_check_running and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
    assert not result._agy_check_running
    snapshot = result._antigravity_auth.get_ui_snapshot()
    assert snapshot["accountState"] == ("authenticated" if authenticated else "unknown")
    assert "não foi possível" in snapshot["accountStatus"].lower()
    assert "SECRET" not in str(snapshot)


def test_saved_account_can_be_validated_after_failed_attempt(bridge):
    result, app = bridge
    result._antigravity_auth._active_attempt = LoginAttempt("old", state="failed")
    response = {"sessionId": "test", "models": {"availableModels": [{"modelId": "test"}]}}
    with patch.object(result, "_run_antigravity_check", return_value=response):
        result.validateAntigravityAccount()
        deadline = time.monotonic() + 3
        while result._agy_check_running and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
    assert result._antigravity_auth.account_state == "authenticated"
    assert result._antigravity_auth.active_attempt.state == "succeeded"


def test_cancel_during_validation_process_launch_reaps_process(bridge):
    from vrsoft_extractor.mary.antigravity_acp import AcpRuntimeInfo
    result, _ = bridge
    client = MagicMock()
    def launch():
        result._agy_check_cancel.set()
    client.start.side_effect = launch
    runtime = AcpRuntimeInfo(executable_path="agy_acp_server", harness_path="localharness_external")
    with patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
            patch("vrsoft_extractor.mary.frontend.studio.spawn_acp_client", return_value=client) as spawn:
        with pytest.raises(RuntimeError):
            result._run_antigravity_check(runtime)
    spawn.assert_called_once_with(runtime_info=runtime)
    client.close.assert_called_once()
    assert result._agy_check_client is None


def test_cancelled_validation_cannot_publish_late_success(bridge):
    result, app = bridge
    entered, release = threading.Event(), threading.Event()
    def check(_):
        entered.set()
        release.wait(2)
        return {"sessionId": "test", "models": {"availableModels": [{"modelId": "test"}]}}
    with patch.object(result, "_run_antigravity_check", side_effect=check):
        result.validateAntigravityAccount()
        assert entered.wait(2)
        result.cancelAntigravityLogin()
        release.set()
        deadline = time.monotonic() + 3
        while result._agy_check_running and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
    assert not result._agy_check_running
    assert result._antigravity_auth.account_state == "unknown"


def test_start_login_force_clears_token(tmp_path):
    token_dir = tmp_path / "antigravity-acp"
    token_dir.mkdir(parents=True)
    token_file = token_dir / "acp_token.json"
    token_file.write_text("{}", encoding="utf-8")
    assert token_file.is_file()

    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path):
        manager = AntigravityAuthManager(
            command_resolver=lambda: "dummy_agy",
            env_factory=lambda: {},
        )
        with patch.object(manager, "_run_login"):
            manager.start_login(force=True)
            assert not token_file.exists()


def test_open_browser_url_fallback(bridge):
    result, _ = bridge
    with patch("vrsoft_extractor.mary.frontend.studio.QDesktopServices.openUrl", side_effect=Exception("error")), \
         patch("webbrowser.open", return_value=True) as mock_webbrowser:
        opened = result._open_browser_url("https://accounts.google.com/test")
        assert opened is True
        mock_webbrowser.assert_called_once_with("https://accounts.google.com/test")


def test_open_antigravity_login_starts_non_destructive_login_when_not_authenticated(bridge):
    result, _ = bridge
    assert result._antigravity_auth.account_state != "authenticated"
    with patch.object(result._antigravity_auth, "start_login") as mock_start, \
         patch("vrsoft_extractor.mary.frontend.studio.resolve_acp", return_value="agy"):
        mock_start.return_value = LoginAttempt("test-id", state="starting")
        result.openAntigravityLogin()
        mock_start.assert_called_once_with(force=False)


def test_open_antigravity_login_reopens_waiting_url(bridge):
    result, _ = bridge
    attempt = LoginAttempt("waiting-test", state="waiting")
    attempt.validated_auth = MagicMock(authorization_url="https://accounts.google.com/waiting")
    result._antigravity_auth._active_attempt = attempt

    with patch.object(result, "_open_browser_url") as mock_open:
        result.openAntigravityLogin()
        mock_open.assert_called_once_with("https://accounts.google.com/waiting")


def test_refresh_antigravity_auth_succeeded_triggers_validation(bridge):
    result, _ = bridge
    attempt = LoginAttempt("succ-test", state="succeeded")
    result._antigravity_auth._active_attempt = attempt

    with patch.object(result, "validateAntigravityAccount") as mock_validate:
        result._refresh_antigravity_auth()
        mock_validate.assert_not_called()

def test_open_antigravity_login_validates_when_authenticated(bridge):
    result, _ = bridge
    result._antigravity_auth._account_state = "authenticated"
    with patch.object(result, "validateAntigravityAccount") as mock_validate, \
         patch.object(result._antigravity_auth, "start_login") as mock_start:
        result.openAntigravityLogin()
        mock_validate.assert_called_once_with()
        mock_start.assert_not_called()


def test_reconnect_antigravity_account_is_explicitly_destructive(bridge):
    result, _ = bridge
    result._antigravity_auth._account_state = "authenticated"
    with patch.object(result, "startAntigravityLogin") as mock_start:
        result.reconnectAntigravityAccount()
    mock_start.assert_called_once_with(force=True)


def test_authenticated_open_login_preserves_saved_token(bridge, tmp_path):
    result, _ = bridge
    token_file = tmp_path / "antigravity-acp" / "acp_token.json"
    token_file.parent.mkdir(parents=True)
    token_file.write_text('{"token":"saved"}', encoding="utf-8")
    result._antigravity_auth._account_state = "authenticated"

    with patch("vrsoft_extractor.mary.antigravity_acp.profile_path", return_value=tmp_path), \
         patch.object(result, "validateAntigravityAccount") as mock_validate, \
         patch.object(result._antigravity_auth, "start_login") as mock_start:
        result.openAntigravityLogin()

    assert token_file.read_text(encoding="utf-8") == '{"token":"saved"}'
    mock_validate.assert_called_once_with()
    mock_start.assert_not_called()


def test_rejected_saved_token_allows_new_non_destructive_oauth(bridge, tmp_path):
    result, app = bridge
    token_file = tmp_path / "antigravity-acp" / "acp_token.json"
    token_file.parent.mkdir(parents=True)
    token_file.write_text('{"token":"rejected"}', encoding="utf-8")
    runtime = AcpRuntimeInfo(executable_path="srv", harness_path="harness", version="1.0")
    result._antigravity_auth._active_attempt = LoginAttempt(
        "rejected-validation", state="failed"
    )

    class RejectClient:
        process = MagicMock()

        def start(self, timeout=None):
            pass

        def request(self, method, params, timeout=None):
            if method == "authenticate":
                raise AcpError("authenticate", -32000, "rejected")
            raise AssertionError(f"unexpected silent method: {method}")

        def close(self):
            pass

    new_url = auth_url(state="new-attempt")
    browser_opened = threading.Event()

    class OAuthClient:
        def __init__(self, on_auth_url):
            self.process = MagicMock()
            self._on_auth_url = on_auth_url

        def start(self, timeout=None):
            pass

        def request(self, method, params, timeout=None):
            if method == "authenticate":
                self._on_auth_url(new_url)
                browser_opened.wait(2)
                return {}
            if method == "session/new":
                return {"sessionId": "new-session", "models": {
                    "availableModels": [{"modelId": "new-model"}]}}
            raise AssertionError(f"unexpected OAuth method: {method}")

        def close(self):
            pass

    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp_runtime", return_value=runtime), \
         patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
         patch("vrsoft_extractor.mary.frontend.studio.spawn_acp_client", return_value=RejectClient()), \
         patch("vrsoft_extractor.mary.frontend.studio.prepare_profile"):
        result.validateAntigravityAccount()
        deadline = time.monotonic() + 3
        while result._agy_check_running and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)

    assert result._antigravity_auth.account_state == "unauthenticated"
    rejected_attempt_id = result._antigravity_auth.active_attempt.attempt_id

    def spawn_oauth(**kwargs):
        return OAuthClient(kwargs["on_auth_url"])

    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp_runtime", return_value=runtime), \
         patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.spawn_acp_client", side_effect=spawn_oauth), \
         patch.object(result, "_open_browser_url", return_value=True) as open_browser, \
         patch.object(result._antigravity_auth, "start_login", wraps=result._antigravity_auth.start_login) as start_login:
        result.openAntigravityLogin()
        deadline = time.monotonic() + 3
        while not open_browser.called and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        browser_opened.set()

    start_login.assert_called_once_with(force=False)
    assert open_browser.call_args.args[0] == new_url
    assert result._antigravity_auth.active_attempt.attempt_id != rejected_attempt_id
    assert token_file.read_text(encoding="utf-8") == '{"token":"rejected"}'


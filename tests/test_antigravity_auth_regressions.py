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
    result, _ = bridge
    client = MagicMock()
    def launch():
        result._agy_check_cancel.set()
    client.start.side_effect = launch
    with patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
            patch("vrsoft_extractor.mary.frontend.studio.AcpClient", return_value=client):
        with pytest.raises(RuntimeError):
            result._run_antigravity_check("agy")
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

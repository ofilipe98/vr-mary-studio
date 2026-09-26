import http.server
import json
import os
import re
import threading
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vrsoft_extractor.mary.antigravity_auth import (
    AUTH_MARKER_T3,
    AntigravityAuthManager,
    AuthStreamParser,
    LoginAttempt,
    OAuthCallbackError,
    OAuthValidationError,
    ValidatedAuthUrl,
    forward_callback_to_listener,
    validate_authorization_url,
    validate_callback_url,
)


class TestValidateAuthorizationUrl(unittest.TestCase):
    def setUp(self):
        self.valid_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            "response_type=code&"
            "client_id=test-client.apps.googleusercontent.com&"
            "redirect_uri=http%3A%2F%2F127.0.0.1%3A45678%2F&"
            "scope=openid%20profile&"
            "state=opaque_state_12345"
        )

    def test_valid_url_success(self):
        validated = validate_authorization_url(self.valid_url)
        self.assertEqual(validated.port, 45678)
        self.assertEqual(validated.path, "/")
        self.assertEqual(validated.state, "opaque_state_12345")
        self.assertEqual(validated.redirect_uri, "http://127.0.0.1:45678/")

    def test_credentials_redacted_in_repr_and_str(self):
        validated = validate_authorization_url(self.valid_url)
        repr_text = repr(validated)
        str_text = str(validated)
        self.assertNotIn("opaque_state_12345", repr_text)
        self.assertNotIn("opaque_state_12345", str_text)
        self.assertIn("REDACTED", repr_text)

    def test_reject_scheme_http(self):
        url = self.valid_url.replace("https://", "http://")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_non_google_host(self):
        url = self.valid_url.replace("accounts.google.com", "attacker.com")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_embedded_credentials(self):
        url = self.valid_url.replace("https://", "https://user:pass@")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_wrong_path(self):
        url = self.valid_url.replace("/o/oauth2/v2/auth", "/o/oauth2/auth")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_fragment(self):
        url = self.valid_url + "#fragment"
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_duplicate_params(self):
        url = self.valid_url + "&state=second_state"
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_missing_response_type(self):
        url = self.valid_url.replace("response_type=code&", "")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_empty_state(self):
        url = self.valid_url.replace("state=opaque_state_12345", "state=")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_control_characters_in_state(self):
        url = self.valid_url.replace("state=opaque_state_12345", "state=bad%0D%0Astate")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_redirect_uri_localhost(self):
        url = self.valid_url.replace("127.0.0.1", "localhost")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_redirect_uri_missing_port(self):
        url = self.valid_url.replace("%3A45678", "")
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)

    def test_reject_redirect_uri_with_fragment_or_query(self):
        bad_redirect = urllib.parse.quote("http://127.0.0.1:45678/?foo=bar")
        url = re.sub(r"redirect_uri=[^&]+", f"redirect_uri={bad_redirect}", self.valid_url)
        with self.assertRaises(OAuthValidationError):
            validate_authorization_url(url)


class TestAuthStreamParser(unittest.TestCase):
    def _valid_url(self, extra=""):
        """Builds a fully valid OAuth URL for parser tests."""
        from urllib.parse import urlencode
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "response_type": "code",
            "client_id": "test-client.apps.googleusercontent.com",
            "redirect_uri": "http://127.0.0.1:45678/",
            "state": "parser_test_state",
        }) + extra

    def test_parse_t3_json_marker_in_chunks(self):
        captured = []
        parser = AuthStreamParser(on_auth_url=captured.append)

        url = self._valid_url()
        line = f'{AUTH_MARKER_T3}{json.dumps(url)}\n'
        encoded = line.encode("utf-8")

        # Split across two chunks
        parser.feed(encoded[:15])
        self.assertEqual(len(captured), 0)
        parser.feed(encoded[15:])
        self.assertEqual(captured, [url])

    def test_parse_browser_prefix(self):
        captured = []
        parser = AuthStreamParser(on_auth_url=captured.append)

        url = self._valid_url()
        line = f"Open the following link in your browser: {url}\r\n"
        parser.feed(line.encode("utf-8"))
        self.assertEqual(captured, [url])

    def test_parse_acp_prefix(self):
        captured = []
        parser = AuthStreamParser(on_auth_url=captured.append)

        url = self._valid_url()
        line = f"Open the following link to authenticate the ACP server: {url}\n"
        parser.feed(line.encode("utf-8"))
        self.assertEqual(captured, [url])

    def test_preserve_non_auth_lines(self):
        captured_urls = []
        captured_lines = []
        parser = AuthStreamParser(
            on_auth_url=captured_urls.append,
            on_line=captured_lines.append,
        )

        protocol_line = '{"event": "init", "session_id": "123"}\n'
        parser.feed(protocol_line.encode("utf-8"))
        self.assertEqual(captured_urls, [])
        self.assertEqual(captured_lines, ['{"event": "init", "session_id": "123"}'])

    def test_bounded_line_limit_discards_oversized_line(self):
        captured_urls = []
        captured_lines = []
        parser = AuthStreamParser(
            on_auth_url=captured_urls.append,
            on_line=captured_lines.append,
            max_line_bytes=100,
        )

        # Feed 150 bytes without newline
        parser.feed(b"A" * 150)
        # Now finish oversized line
        parser.feed(b" tail\n")
        # Ensure oversized line was discarded and not passed
        self.assertEqual(captured_lines, [])

        # Feed normal line afterwards
        parser.feed(b"normal line\n")
        self.assertEqual(captured_lines, ["normal line"])

    def test_eof_pending_line(self):
        captured_lines = []
        parser = AuthStreamParser(
            on_auth_url=lambda u: None,
            on_line=captured_lines.append,
        )
        parser.feed(b"trailing line without newline")
        self.assertEqual(captured_lines, [])
        parser.finish()
        self.assertEqual(captured_lines, ["trailing line without newline"])

    def test_ignore_account_chooser_and_promotional_urls(self):
        captured_urls = []
        captured_lines = []
        parser = AuthStreamParser(
            on_auth_url=captured_urls.append,
            on_line=captured_lines.append,
        )
        line = '__VRSTUDIO_ANTIGRAVITY_AUTH_URL__"https://accounts.google.com/AccountChooser?Email=user@gmail.com&continue=https%3A%2F%2Fone.google.com%2Fai"\n'
        parser.feed(line.encode("utf-8"))
        self.assertEqual(captured_urls, [])
        self.assertEqual(len(captured_lines), 1)

    def test_is_oauth_authorization_url(self):
        from vrsoft_extractor.mary.antigravity_auth import is_oauth_authorization_url
        from urllib.parse import urlencode
        # Full valid URL must be True
        full = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "response_type": "code",
            "client_id": "xyz",
            "redirect_uri": "http://127.0.0.1:45678/",
            "state": "test_state",
        })
        self.assertTrue(is_oauth_authorization_url(full))
        # Incomplete URL (missing state, redirect_uri) must now be False
        self.assertFalse(is_oauth_authorization_url("https://accounts.google.com/o/oauth2/v2/auth?client_id=xyz"))
        # Legacy /o/oauth2/auth path is rejected by strict validator
        self.assertFalse(is_oauth_authorization_url("https://accounts.google.com/o/oauth2/auth?client_id=xyz"))
        # Non-OAuth URLs
        self.assertFalse(is_oauth_authorization_url("https://accounts.google.com/AccountChooser?continue=https://one.google.com"))
        self.assertFalse(is_oauth_authorization_url("https://one.google.com/ai"))
        self.assertFalse(is_oauth_authorization_url("http://accounts.google.com/o/oauth2/v2/auth?client_id=xyz"))
        self.assertFalse(is_oauth_authorization_url("https://malicious.com/o/oauth2/v2/auth"))
        self.assertFalse(is_oauth_authorization_url(""))


class TestCallbackValidationAndForwarding(unittest.TestCase):
    def setUp(self):
        self.validated_auth = ValidatedAuthUrl(
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            redirect_uri="http://127.0.0.1:51234/",
            state="secret_state_xyz",
            port=51234,
            path="/",
        )

    def test_validate_callback_success(self):
        callback_url = "http://127.0.0.1:51234/?code=auth_code_999&state=secret_state_xyz"
        code, state = validate_callback_url(callback_url, self.validated_auth)
        self.assertEqual(code, "auth_code_999")
        self.assertEqual(state, "secret_state_xyz")

    def test_validate_callback_mismatched_state(self):
        callback_url = "http://127.0.0.1:51234/?code=auth_code_999&state=wrong_state"
        with self.assertRaises(OAuthValidationError):
            validate_callback_url(callback_url, self.validated_auth)

    def test_validate_callback_mismatched_port(self):
        callback_url = "http://127.0.0.1:9999/?code=auth_code_999&state=secret_state_xyz"
        with self.assertRaises(OAuthValidationError):
            validate_callback_url(callback_url, self.validated_auth)

    def test_validate_callback_oauth_error(self):
        callback_url = "http://127.0.0.1:51234/?error=access_denied&state=secret_state_xyz"
        with self.assertRaises(OAuthCallbackError):
            validate_callback_url(callback_url, self.validated_auth)

    def test_validate_callback_both_code_and_error(self):
        callback_url = "http://127.0.0.1:51234/?code=123&error=access_denied&state=secret_state_xyz"
        with self.assertRaises(OAuthValidationError):
            validate_callback_url(callback_url, self.validated_auth)

    def test_forward_callback_to_listener(self):
        # Start a local test server
        received_path = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                received_path.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        auth = ValidatedAuthUrl(
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            redirect_uri=f"http://127.0.0.1:{port}/",
            state="test_state",
            port=port,
            path="/",
        )

        callback_url = f"http://127.0.0.1:{port}/?code=test_code&state=test_state"
        forward_callback_to_listener(callback_url, auth, timeout=2.0)
        server_thread.join(timeout=2.0)
        server.server_close()

        self.assertEqual(len(received_path), 1)
        self.assertIn("code=test_code", received_path[0])
        self.assertIn("state=test_state", received_path[0])


class TestAntigravityAuthManager(unittest.TestCase):
    def test_double_click_reuses_active_attempt(self):
        stop_event = threading.Event()
        started = threading.Event()
        client = MagicMock()
        client.start.side_effect = lambda: started.set()
        client.request.side_effect = lambda *args: (stop_event.wait(2) and {})
        with patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", return_value=client) as factory:
            manager = AntigravityAuthManager(
                command_resolver=lambda: "dummy_agy",
                env_factory=lambda: {},
            )
            try:
                attempt1 = manager.start_login()
                self.assertTrue(started.wait(10))
                attempt2 = manager.start_login()
                self.assertEqual(attempt1.attempt_id, attempt2.attempt_id)
                self.assertEqual(factory.call_count, 1)
            finally:
                stop_event.set()
                manager.cancel_login()

    def test_conflict_detection_two_different_urls_in_same_attempt(self):
        manager = AntigravityAuthManager(
            command_resolver=lambda: "dummy_agy",
            env_factory=lambda: {},
        )
        url1 = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            "response_type=code&state=state1&redirect_uri=http%3A%2F%2F127.0.0.1%3A1111%2F"
        )
        url2 = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            "response_type=code&state=state2&redirect_uri=http%3A%2F%2F127.0.0.1%3A2222%2F"
        )

        attempt = LoginAttempt(attempt_id="att_1", state="starting")
        manager._active_attempt = attempt

        manager._on_auth_url_received("att_1", url1)
        self.assertEqual(attempt.state, "waiting")
        self.assertIsNotNone(attempt.validated_auth)

        # Same URL repeated: ignored
        manager._on_auth_url_received("att_1", url1)
        self.assertEqual(attempt.state, "waiting")

        # Different URL: CONFLICT -> attempt marked failed
        manager._on_auth_url_received("att_1", url2)
        self.assertEqual(attempt.state, "failed")
        self.assertIn("Conflito", attempt.error_detail)

    def test_session_or_model_error_does_not_clear_authenticated_state(self):
        manager = AntigravityAuthManager(
            command_resolver=lambda: "dummy_agy",
            env_factory=lambda: {},
        )
        manager.mark_authenticated_from_validation()
        self.assertEqual(manager.account_state, "authenticated")

        manager.mark_session_or_model_error("Falha temporária de modelo")
        self.assertEqual(manager.account_state, "authenticated")
        self.assertIn("autenticada, mas não foi possível inicializar", manager.account_status_label)

    def test_cancel_login_terminates_process_and_clears_sensitive_fields(self):
        manager = AntigravityAuthManager(
            command_resolver=lambda: "dummy_agy",
            env_factory=lambda: {},
        )
        proc_mock = MagicMock()
        proc_mock.poll.return_value = None
        attempt = LoginAttempt(
            attempt_id="att_cancel",
            state="waiting",
            validated_auth=ValidatedAuthUrl(
                authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
                redirect_uri="http://127.0.0.1:40000/",
                state="sensitive_state",
                port=40000,
                path="/",
            ),
            process=proc_mock,
        )
        manager._active_attempt = attempt

        manager.cancel_login()
        self.assertEqual(attempt.state, "cancelled")
        self.assertIsNone(attempt.validated_auth)
        proc_mock.terminate.assert_called_once()

    def test_init_timeout_marks_failed(self):
        manager = AntigravityAuthManager(
            command_resolver=lambda: "dummy_agy",
            env_factory=lambda: {},
        )
        proc_mock = MagicMock()
        proc_mock.poll.return_value = None
        attempt = LoginAttempt(attempt_id="att_timeout", state="starting", process=proc_mock)
        manager._active_attempt = attempt

        manager._on_init_timeout("att_timeout")
        self.assertEqual(attempt.state, "failed")
        self.assertIn("45s", attempt.error_detail)
        proc_mock.terminate.assert_called_once()

    def test_oauth_timeout_marks_failed(self):
        manager = AntigravityAuthManager(
            command_resolver=lambda: "dummy_agy",
            env_factory=lambda: {},
        )
        proc_mock = MagicMock()
        proc_mock.poll.return_value = None
        attempt = LoginAttempt(attempt_id="att_oauth_timeout", state="waiting", process=proc_mock)
        manager._active_attempt = attempt

        manager._on_oauth_timeout("att_oauth_timeout")
        self.assertEqual(attempt.state, "failed")
        self.assertIn("300s", attempt.error_detail)
        proc_mock.terminate.assert_called_once()

    def test_process_exit_zero_does_not_prove_authentication(self):
        manager = AntigravityAuthManager(
            command_resolver=lambda: "dummy_agy",
            env_factory=lambda: {},
        )
        proc_mock = MagicMock()
        proc_mock.wait.return_value = 0
        attempt = LoginAttempt(attempt_id="att_ok", state="verifying", process=proc_mock)
        manager._active_attempt = attempt

        manager._wait_process("att_ok", proc_mock)
        self.assertEqual(attempt.state, "idle")
        self.assertEqual(manager.account_state, "unknown")
        self.assertIn("Validar conta", manager.account_status_label)


class TestStudioAntigravityAuthIntegration(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def test_studio_refresh_providers_exposes_dimensions(self):
        from vrsoft_extractor.mary.frontend.studio import StudioBridge
        from vrsoft_extractor.mary.config import MarySettings
        from vrsoft_extractor.mary.db import MaryDatabase
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            settings = MarySettings(app_dir=Path(tmp), root=Path(tmp) / "root", old_root=Path(tmp) / "old")
            db = MaryDatabase(Path(tmp) / "test.db")
            bridge = StudioBridge(settings=settings, database=db)
            try:
                bridge.refreshProviders()
                items = bridge.providerItems
                agy_item = next(item for item in items if item["id"] == "antigravity")
                self.assertIn("attemptState", agy_item)
                self.assertIn("accountState", agy_item)
                self.assertIn("authUrl", agy_item)
                self.assertIn("expiresAt", agy_item)
                self.assertIn("isWaiting", agy_item)
                self.assertIn("isVerifying", agy_item)
                self.assertEqual(agy_item["attemptState"], "idle")
            finally:
                bridge.close()

    def test_studio_open_and_cancel_login(self):
        from vrsoft_extractor.mary.frontend.studio import StudioBridge
        from vrsoft_extractor.mary.config import MarySettings
        from vrsoft_extractor.mary.db import MaryDatabase
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            settings = MarySettings(app_dir=Path(tmp), root=Path(tmp) / "root", old_root=Path(tmp) / "old")
            db = MaryDatabase(Path(tmp) / "test.db")
            bridge = StudioBridge(settings=settings, database=db)
            try:
                with patch.object(bridge._antigravity_auth, "start_login") as mock_start:
                    auth_obj = MagicMock(authorization_url="https://accounts.google.com/o/oauth2/v2/auth")
                    attempt_mock = MagicMock(state="waiting", validated_auth=auth_obj)
                    mock_start.return_value = attempt_mock
                    with patch("PySide6.QtGui.QDesktopServices.openUrl") as mock_open:
                        bridge.openAntigravityLogin()
                        mock_start.assert_called_once()
                        mock_open.assert_called_once()

                with patch.object(bridge._antigravity_auth, "cancel_login") as mock_cancel:
                    bridge.cancelAntigravityLogin()
                    mock_cancel.assert_called_once()
            finally:
                bridge.close()

    def test_studio_submit_callback(self):
        from vrsoft_extractor.mary.frontend.studio import StudioBridge
        from vrsoft_extractor.mary.config import MarySettings
        from vrsoft_extractor.mary.db import MaryDatabase
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            settings = MarySettings(app_dir=Path(tmp), root=Path(tmp) / "root", old_root=Path(tmp) / "old")
            db = MaryDatabase(Path(tmp) / "test.db")
            bridge = StudioBridge(settings=settings, database=db)
            try:
                with patch.object(bridge._antigravity_auth, "submit_callback") as mock_submit:
                    bridge.submitAntigravityCallback("http://127.0.0.1:40000/?code=xyz&state=abc")
                    # allow pool task to run
                    import time
                    time.sleep(0.05)
                    mock_submit.assert_called_once_with("http://127.0.0.1:40000/?code=xyz&state=abc")
            finally:
                bridge.close()

    def test_studio_close_cancels_auth(self):
        from vrsoft_extractor.mary.frontend.studio import StudioBridge
        from vrsoft_extractor.mary.config import MarySettings
        from vrsoft_extractor.mary.db import MaryDatabase
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            settings = MarySettings(app_dir=Path(tmp), root=Path(tmp) / "root", old_root=Path(tmp) / "old")
            db = MaryDatabase(Path(tmp) / "test.db")
            bridge = StudioBridge(settings=settings, database=db)
            with patch.object(bridge._antigravity_auth, "cancel_login") as mock_cancel:
                bridge.close()
                mock_cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()

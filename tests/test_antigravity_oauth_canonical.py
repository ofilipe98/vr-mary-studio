"""Canonical OAuth validation tests — mandatory scenarios for the final fix.

Covers the single-source-of-truth validation contract, log safety,
transport normalization, retry classification, and rendering correctness.
"""
import logging
import os
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vrsoft_extractor.mary.antigravity_auth import (
    OAuthValidationError,
    ValidatedAuthUrl,
    is_oauth_authorization_url,
    normalize_browser_url,
    try_validate_authorization_url,
    validate_authorization_url,
    AuthStreamParser,
    LoginAttempt,
    AntigravityAuthManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_oauth_url(
    redirect="http://127.0.0.1:45678/",
    state="opaque_state_12345",
    client_id="test-client.apps.googleusercontent.com",
    response_type="code",
):
    """Builds a fully valid OAuth URL with all required parameters."""
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect,
        "scope": "openid profile",
        "state": state,
    })


# ===========================================================================
# Scenario 1 — AccountChooser must be ignored
# ===========================================================================

class TestAccountChooserIgnored:
    ACCOUNT_CHOOSER = (
        "https://accounts.google.com/AccountChooser?"
        "Email=user@example.com&continue=https%3A%2F%2Fone.google.com%2Fai"
    )

    def test_not_classified_as_oauth(self):
        assert is_oauth_authorization_url(self.ACCOUNT_CHOOSER) is False

    def test_try_validate_returns_none(self):
        assert try_validate_authorization_url(self.ACCOUNT_CHOOSER) is None

    def test_parser_does_not_emit_auth_url(self):
        captured = []
        parser = AuthStreamParser(on_auth_url=captured.append)
        marker = f'__VRSTUDIO_ANTIGRAVITY_AUTH_URL__"{self.ACCOUNT_CHOOSER}"\n'
        parser.feed(marker.encode("utf-8"))
        assert captured == []

    def test_auth_manager_ignores_and_does_not_log_email(self, caplog):
        manager = AntigravityAuthManager(lambda: "agy", lambda: {})
        attempt = LoginAttempt("att_ac", state="starting")
        manager._active_attempt = attempt
        with caplog.at_level(logging.DEBUG):
            manager._on_auth_url_received("att_ac", self.ACCOUNT_CHOOSER)
        # Attempt must not transition to waiting
        assert attempt.state == "starting"
        assert attempt.validated_auth is None
        # Email must never appear in logs
        for record in caplog.records:
            assert "user@example.com" not in record.getMessage()
            assert "Email=" not in record.getMessage()


# ===========================================================================
# Scenario 2 — Google One direct URL ignored
# ===========================================================================

class TestGoogleOneIgnored:
    GOOGLE_ONE = "https://one.google.com/ai"

    def test_not_classified_as_oauth(self):
        assert is_oauth_authorization_url(self.GOOGLE_ONE) is False

    def test_try_validate_returns_none(self):
        assert try_validate_authorization_url(self.GOOGLE_ONE) is None


# ===========================================================================
# Scenario 3 — Incomplete OAuth URL does not generate auth_required
# ===========================================================================

class TestIncompleteOAuthIgnored:
    INCOMPLETE = "https://accounts.google.com/o/oauth2/v2/auth?client_id=123"

    def test_not_classified_as_oauth(self):
        """An OAuth path without response_type, state, redirect_uri is incomplete."""
        assert is_oauth_authorization_url(self.INCOMPLETE) is False

    def test_try_validate_returns_none(self):
        assert try_validate_authorization_url(self.INCOMPLETE) is None

    def test_acp_client_unattended_does_not_fail_pending(self):
        """Incomplete OAuth URL must not trigger ACP -32000."""
        from vrsoft_extractor.mary.antigravity_acp import AcpClient
        client = AcpClient(on_auth_url=None)
        client._fail_pending = MagicMock()
        client.close = MagicMock()

        client._auth_url(self.INCOMPLETE)
        client._fail_pending.assert_not_called()
        client.close.assert_not_called()


# ===========================================================================
# Scenario 4 — Valid OAuth URL is fully accepted
# ===========================================================================

class TestValidOAuthAccepted:
    def test_validate_authorization_url_succeeds(self):
        url = _valid_oauth_url()
        validated = validate_authorization_url(url)
        assert isinstance(validated, ValidatedAuthUrl)
        assert validated.port == 45678
        assert validated.state == "opaque_state_12345"
        assert validated.redirect_uri == "http://127.0.0.1:45678/"
        assert validated.path == "/"

    def test_is_oauth_returns_true(self):
        assert is_oauth_authorization_url(_valid_oauth_url()) is True

    def test_try_validate_returns_validated(self):
        result = try_validate_authorization_url(_valid_oauth_url())
        assert result is not None
        assert isinstance(result, ValidatedAuthUrl)

    def test_parser_emits_valid_url(self):
        captured = []
        parser = AuthStreamParser(on_auth_url=captured.append)
        url = _valid_oauth_url()
        line = f'__VRSTUDIO_ANTIGRAVITY_AUTH_URL__"{url}"\n'
        parser.feed(line.encode("utf-8"))
        assert captured == [url]

    def test_auth_manager_transitions_to_waiting(self):
        manager = AntigravityAuthManager(lambda: "agy", lambda: {})
        attempt = LoginAttempt("att_valid", state="starting")
        manager._active_attempt = attempt
        url = _valid_oauth_url()
        manager._on_auth_url_received("att_valid", url)
        assert attempt.state == "waiting"
        assert attempt.validated_auth is not None
        manager.cancel_login()

    def test_acp_client_unattended_generates_auth_required(self):
        """Valid OAuth URL in unattended mode (no on_auth_url) must trigger ACP -32000."""
        from vrsoft_extractor.mary.antigravity_acp import AcpClient
        client = AcpClient(on_auth_url=None)
        client._fail_pending = MagicMock()
        client.close = MagicMock()

        client._auth_url(_valid_oauth_url())
        client._fail_pending.assert_called_once()
        err = client._fail_pending.call_args[0][0]
        assert err.code == -32000

    def test_acp_client_attended_calls_handler(self):
        """Valid OAuth URL with on_auth_url handler must deliver to it."""
        handler = MagicMock()
        from vrsoft_extractor.mary.antigravity_acp import AcpClient
        client = AcpClient(on_auth_url=handler)
        client._auth_url(_valid_oauth_url())
        handler.assert_called_once()


# ===========================================================================
# Scenario 5 — Malicious host rejected
# ===========================================================================

class TestMaliciousHostRejected:
    EVIL = "https://evil.example/o/oauth2/v2/auth?" + urlencode({
        "response_type": "code",
        "state": "opaque",
        "redirect_uri": "http://127.0.0.1:45678/",
        "client_id": "evil",
    })

    def test_validate_rejects(self):
        with pytest.raises(OAuthValidationError):
            validate_authorization_url(self.EVIL)

    def test_is_oauth_returns_false(self):
        assert is_oauth_authorization_url(self.EVIL) is False


# ===========================================================================
# Scenario 6 — Embedded credentials rejected
# ===========================================================================

class TestEmbeddedCredentialsRejected:
    def test_userinfo_in_authority(self):
        url = _valid_oauth_url().replace("https://", "https://user:pass@")
        with pytest.raises(OAuthValidationError):
            validate_authorization_url(url)

    def test_is_oauth_returns_false(self):
        url = _valid_oauth_url().replace("https://", "https://user:pass@")
        assert is_oauth_authorization_url(url) is False


# ===========================================================================
# Scenario 7 — Duplicate critical parameters rejected
# ===========================================================================

class TestDuplicateParamsRejected:
    @pytest.mark.parametrize("param", ["state", "redirect_uri", "response_type"])
    def test_duplicate_parameter_rejected(self, param):
        url = _valid_oauth_url() + f"&{param}=duplicate_value"
        with pytest.raises(OAuthValidationError):
            validate_authorization_url(url)


# ===========================================================================
# Scenario 8 — Helper quote normalization
# ===========================================================================

class TestHelperQuoteNormalization:
    def test_double_quoted_url_normalized(self):
        raw = f'"{_valid_oauth_url()}"'
        clean = normalize_browser_url(raw)
        assert not clean.startswith('"')
        assert not clean.endswith('"')
        assert try_validate_authorization_url(clean) is not None

    def test_single_quoted_url_normalized(self):
        raw = f"'{_valid_oauth_url()}'"
        clean = normalize_browser_url(raw)
        assert not clean.startswith("'")
        assert not clean.endswith("'")
        assert try_validate_authorization_url(clean) is not None

    def test_parser_handles_quoted_valid_url(self):
        """AuthStreamParser must strip quotes before validating."""
        captured = []
        parser = AuthStreamParser(on_auth_url=captured.append)
        url = _valid_oauth_url()
        # PowerShell helper wraps in JSON-encoded quotes
        import json
        line = f'__VRSTUDIO_ANTIGRAVITY_AUTH_URL__{json.dumps(url)}\n'
        parser.feed(line.encode("utf-8"))
        assert captured == [url]

    def test_validator_rejects_raw_quoted_url(self):
        """The strict validator must NOT accept quotes — normalization is separate."""
        raw = f'"{_valid_oauth_url()}"'
        with pytest.raises(OAuthValidationError):
            validate_authorization_url(raw)


# ===========================================================================
# Scenario 9 — Valid account + AccountChooser in unattended mode
# ===========================================================================

class TestUnattendedAccountChooserNoInterruption:
    def test_account_chooser_does_not_fail_pending_or_close(self):
        """Simulate a valid account where the runtime opens AccountChooser.
        The client must remain open with no ACP -32000."""
        from vrsoft_extractor.mary.antigravity_acp import AcpClient
        client = AcpClient(on_auth_url=None)
        client._fail_pending = MagicMock()
        client.close = MagicMock()

        # AccountChooser arrives
        client._auth_url(
            "https://accounts.google.com/AccountChooser?"
            "Email=user@example.com&continue=https%3A%2F%2Fone.google.com%2Fai"
        )
        # Google One arrives
        client._auth_url("https://one.google.com/ai")
        # Generic accounts page
        client._auth_url("https://accounts.google.com/v3/signin/identifier")

        client._fail_pending.assert_not_called()
        client.close.assert_not_called()


# ===========================================================================
# Scenario 10 — Rendering: no QSG_RHI_BACKEND=software
# ===========================================================================

class TestRenderingCorrectness:
    def test_safe_mode_uses_qt_quick_backend(self):
        """Start-VRStudio-SafeMode.bat must use QT_QUICK_BACKEND, not QSG_RHI_BACKEND."""
        from pathlib import Path
        bat_path = Path(__file__).parent.parent / "Start-VRStudio-SafeMode.bat"
        if not bat_path.is_file():
            pytest.skip("Safe mode batch file not found")
        content = bat_path.read_text(encoding="utf-8")
        assert "QT_QUICK_BACKEND=software" in content
        assert "QSG_RHI_BACKEND=software" not in content

    def test_app_py_uses_qt_quick_backend(self):
        """app.py rendering code must use QT_QUICK_BACKEND, not QSG_RHI_BACKEND."""
        from pathlib import Path
        app_path = (
            Path(__file__).parent.parent
            / "vrsoft_extractor" / "mary" / "frontend" / "app.py"
        )
        if not app_path.is_file():
            pytest.skip("app.py not found")
        content = app_path.read_text(encoding="utf-8")
        # Must use QT_QUICK_BACKEND for software rendering
        assert 'os.environ["QT_QUICK_BACKEND"] = "software"' in content
        # Must not set QSG_RHI_BACKEND=software in production startup code
        # (the comment mentioning the variable is expected and OK)
        lines = content.splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "QSG_RHI_BACKEND" in stripped and "=" in stripped and "software" in stripped:
                # This would be setting the variable in production code
                pytest.fail(
                    f"Production code sets QSG_RHI_BACKEND=software: {stripped}"
                )


# ===========================================================================
# Log safety — no sensitive data leakage
# ===========================================================================

class TestLogSafety:
    def test_acp_auth_url_does_not_log_url(self, caplog):
        """When _auth_url ignores a non-OAuth URL, the raw URL must not appear in logs."""
        from vrsoft_extractor.mary.antigravity_acp import AcpClient
        client = AcpClient(on_auth_url=None)
        client._fail_pending = MagicMock()
        client.close = MagicMock()

        sensitive_url = (
            "https://accounts.google.com/AccountChooser?"
            "Email=secret@example.com&state=very_secret_state"
        )
        with caplog.at_level(logging.DEBUG):
            client._auth_url(sensitive_url)
        for record in caplog.records:
            msg = record.getMessage()
            assert "secret@example.com" not in msg
            assert "very_secret_state" not in msg
            assert "Email=" not in msg
            assert sensitive_url not in msg


# ===========================================================================
# Normalize edge cases
# ===========================================================================

class TestNormalizeBrowserUrl:
    def test_none_returns_empty(self):
        assert normalize_browser_url(None) == ""

    def test_empty_returns_empty(self):
        assert normalize_browser_url("") == ""

    def test_strips_whitespace_and_quotes(self):
        assert normalize_browser_url("  'https://example.com'  ") == "https://example.com"
        assert normalize_browser_url('"https://example.com"') == "https://example.com"

    def test_no_quotes_unchanged(self):
        url = "https://accounts.google.com/o/oauth2/v2/auth?x=1"
        assert normalize_browser_url(url) == url

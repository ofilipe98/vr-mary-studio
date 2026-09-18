"""Gaps finais de readiness/restore/runtime (prompt de correção final).

Cobre:
1. silent authenticate OK + session/new -32603 -> authenticated/degraded
2. silent authenticate OK + catalogo vazio -> authenticated/degraded
3. interactive login + catalogo vazio -> failed + authenticated/degraded
4. interactive login completo -> succeeded + authenticated/ready
5. authenticate -32000 no restore -> unauthenticated/failed
6. UI degraded -> warning, nunca success
7. runtime resolvido uma vez no login
8. runtime resolvido uma vez em list_models
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vrsoft_extractor.mary.antigravity_acp import AcpError, AcpRuntimeInfo
from vrsoft_extractor.mary.antigravity_auth import AntigravityAuthManager


def _wait_attempt(attempt, timeout=3.0):
    deadline = time.monotonic() + timeout
    while attempt.state in ("starting", "verifying") and time.monotonic() < deadline:
        time.sleep(0.01)
    return attempt.state


# --- Interactive login -------------------------------------------------------

def test_03_interactive_login_empty_catalog_is_degraded_failed():
    """session/new com sessionId valido mas catalogo vazio nunca e ready."""

    class EmptyCatalogClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()

        def start(self):
            pass

        def request(self, method, params, timeout=None):
            if method == "authenticate":
                return {}
            if method == "session/new":
                return {"sessionId": "s", "models": {"availableModels": []}}
            return {}

        def close(self):
            pass

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", EmptyCatalogClient):
        attempt = manager.start_login()
        _wait_attempt(attempt)
        assert attempt.state == "failed"
        assert manager.account_state == "authenticated"
        assert manager.provider_readiness == "degraded"
        assert "carregar os modelos" in attempt.error_detail


def test_04_interactive_login_full_success_is_ready():
    class OkClient:
        def __init__(self, **kwargs):
            self.process = MagicMock()

        def start(self):
            pass

        def request(self, method, params, timeout=None):
            if method == "authenticate":
                return {}
            if method == "session/new":
                return {"sessionId": "s", "models": {"availableModels": [{"modelId": "m", "name": "M"}]}}
            return {}

        def close(self):
            pass

    manager = AntigravityAuthManager(lambda: "agy_acp", lambda: {})
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.resolve_acp_runtime", return_value=None), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", OkClient):
        attempt = manager.start_login()
        _wait_attempt(attempt)
        assert attempt.state == "succeeded"
        assert manager.account_state == "authenticated"
        assert manager.provider_readiness == "ready"


def test_helpers_semantics():
    m = AntigravityAuthManager(lambda: "x", lambda: {})
    m.mark_credentials_authenticated("checking")
    assert m.account_state == "authenticated"
    assert m.provider_readiness == "validating"
    m.mark_provider_degraded("bad session")
    assert m.account_state == "authenticated"
    assert m.provider_readiness == "degraded"
    m.mark_provider_ready("ok", models=[{"id": "m"}])
    assert m.account_state == "authenticated"
    assert m.provider_readiness == "ready"
    m.mark_credentials_rejected()
    assert m.account_state == "unauthenticated"
    assert m.provider_readiness == "failed"


def test_shared_session_catalog_helper_rejects_empty():
    from vrsoft_extractor.mary.antigravity_auth import validate_session_and_catalog

    client = MagicMock()
    client.request.return_value = {"sessionId": "s", "models": {"availableModels": []}}
    with pytest.raises(AcpError):
        validate_session_and_catalog(client, Path.home())
    client.request.return_value = {"sessionId": "s", "models": {"availableModels": [{"modelId": "m"}]}}
    session, models = validate_session_and_catalog(client, Path.home())
    assert session["sessionId"] == "s"
    assert len(models) == 1


# --- Silent validation (restore) via StudioBridge ----------------------------

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


def _run_validate_and_wait(bridge, app, timeout=5.0):
    result, _ = bridge if isinstance(bridge, tuple) else (bridge, None)
    app_obj = app
    deadline = time.monotonic() + timeout
    while result._agy_check_running and time.monotonic() < deadline:
        app_obj.processEvents()
        time.sleep(0.005)
    return result


def _silent_client(auth_ok=True, session_mode="ok"):
    """Builds a fake ACP client for silent validation.

    session_mode: "ok" | "fail32603" | "empty" | "auth32000"
    """
    class C:
        def __init__(self, **kwargs):
            self.process = MagicMock()

        def start(self, timeout=None):
            pass

        def request(self, method, params, timeout=None):
            if method == "authenticate":
                if session_mode == "auth32000":
                    raise AcpError("authenticate", -32000, "rejected")
                return {}
            if method == "session/new":
                if session_mode == "fail32603":
                    raise AcpError("session/new", -32603, "internal")
                if session_mode == "empty":
                    return {"sessionId": "s", "models": {"availableModels": []}}
                return {"sessionId": "s", "models": {"availableModels": [{"modelId": "m", "name": "M"}]}}
            return {}

        def close(self):
            pass

    return C


def test_01_silent_auth_ok_session_fail32603_preserves_authenticated(bridge):
    result, app = bridge
    runtime = AcpRuntimeInfo(executable_path="srv", harness_path="harness", version="1.0")
    fake = _silent_client(session_mode="fail32603")
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp_runtime", return_value=runtime), \
         patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
         patch("vrsoft_extractor.mary.frontend.studio.spawn_acp_client", return_value=fake()) as spawn, \
         patch("vrsoft_extractor.mary.frontend.studio.prepare_profile"):
        result.validateAntigravityAccount()
        _run_validate_and_wait((result, app), app)
    assert spawn.called
    # on_auth_url must stay None for silent validation (no browser)
    _, kwargs = spawn.call_args
    assert kwargs.get("on_auth_url", None) is None
    assert result._antigravity_auth.account_state == "authenticated"
    assert result._antigravity_auth.provider_readiness == "degraded"
    label = result._antigravity_auth.account_status_label
    assert "Conta Google autenticada" in label
    assert "Login necessário" not in label


def test_02_silent_auth_ok_empty_catalog_is_degraded(bridge):
    result, app = bridge
    runtime = AcpRuntimeInfo(executable_path="srv", harness_path="harness", version="1.0")
    fake = _silent_client(session_mode="empty")
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp_runtime", return_value=runtime), \
         patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
         patch("vrsoft_extractor.mary.frontend.studio.spawn_acp_client", return_value=fake()), \
         patch("vrsoft_extractor.mary.frontend.studio.prepare_profile"):
        result.validateAntigravityAccount()
        _run_validate_and_wait((result, app), app)
    assert result._antigravity_auth.account_state == "authenticated"
    assert result._antigravity_auth.provider_readiness == "degraded"


def test_05_silent_authenticate_32000_is_unauthenticated(bridge):
    result, app = bridge
    runtime = AcpRuntimeInfo(executable_path="srv", harness_path="harness", version="1.0")
    fake = _silent_client(session_mode="auth32000")
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp_runtime", return_value=runtime), \
         patch("vrsoft_extractor.mary.frontend.studio.has_saved_account", return_value=True), \
         patch("vrsoft_extractor.mary.frontend.studio.spawn_acp_client", return_value=fake()), \
         patch("vrsoft_extractor.mary.frontend.studio.prepare_profile"):
        result.validateAntigravityAccount()
        _run_validate_and_wait((result, app), app)
    assert result._antigravity_auth.account_state == "unauthenticated"
    assert result._antigravity_auth.provider_readiness == "failed"


# --- UI degraded -------------------------------------------------------------

def _qml_status(p):
    """Python mirror of VrProviderSettings.qml status() for the Antigravity branch."""
    a = str(p.get("accountStatus") or "")
    if p.get("isVerifying"):
        return {"tone": "muted"}
    if p.get("isValidating") or p.get("checking") or a.startswith("Validando"):
        return {"tone": "muted"}
    if p.get("isWaiting"):
        return {"tone": "warning"}
    if p.get("isStarting"):
        return {"tone": "warning"}
    if p.get("providerReadiness") == "degraded":
        if p.get("accountState") == "authenticated":
            return {"text": "Conta autenticada · falha ao carregar modelos", "tone": "warning"}
        return {"tone": "danger"}
    if p.get("providerReadiness") == "failed":
        if p.get("accountState") == "unauthenticated":
            return {"text": "Login necessário", "tone": "warning"}
        if p.get("accountState") == "authenticated":
            return {"text": "Conta autenticada · falha ao carregar modelos", "tone": "warning"}
        return {"tone": "danger"}
    if p.get("attemptState") == "failed" and p.get("accountState") == "authenticated":
        return {"text": "Conta autenticada · falha ao carregar modelos", "tone": "warning"}
    return {"tone": "success"}


def test_06_ui_degraded_is_warning_not_success(bridge):
    result, app = bridge
    result._antigravity_auth._account_state = "authenticated"
    result._antigravity_auth._provider_readiness = "degraded"
    result._antigravity_auth._account_status_label = (
        "Conta Google autenticada, mas não foi possível inicializar a sessão ou carregar os modelos."
    )
    result.refreshProviders()
    item = next(x for x in result.providerItems if x["id"] == "antigravity")
    assert item["accountState"] == "authenticated"
    assert item["providerReadiness"] == "degraded"
    visual = _qml_status(item)
    assert visual["tone"] == "warning"
    assert visual["text"] == "Conta autenticada · falha ao carregar modelos"
    assert visual["tone"] != "success"

    # QML contract itself must map degraded+authenticated to warning.
    qml = Path(__file__).parent.parent / "vrsoft_extractor" / "mary" / "frontend" / "qml" / "components" / "VrProviderSettings.qml"
    text = qml.read_text(encoding="utf-8")
    assert 'p.providerReadiness === "degraded"' in text
    assert "Conta autenticada · falha ao carregar modelos" in text


# --- Single runtime resolution ------------------------------------------------

def test_07_login_resolves_runtime_once():
    info = AcpRuntimeInfo(executable_path="srv", harness_path="harness", version="9.9.9")
    seen = {}

    class OkClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.process = MagicMock()

        def start(self):
            pass

        def request(self, method, params, timeout=None):
            if method == "session/new":
                return {"sessionId": "s", "models": {"availableModels": [{"modelId": "m"}]}}
            return {}

        def close(self):
            pass

    # Re-run with spawn spy to assert single resolution + passthrough.
    manager = AntigravityAuthManager(
        command_resolver=lambda: "should-not-be-used",
        env_factory=lambda **kwargs: {},
        runtime_resolver=MagicMock(return_value=info),
    )
    with patch("vrsoft_extractor.mary.antigravity_acp.prepare_profile"), \
         patch("vrsoft_extractor.mary.antigravity_acp.preflight_browser_helper"), \
         patch("vrsoft_extractor.mary.antigravity_acp.AcpClient", OkClient):
        import vrsoft_extractor.mary.antigravity_acp as acp_mod
        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return OkClient()

        with patch.object(acp_mod, "spawn_acp_client", side_effect=spy):
            attempt = manager.start_login()
            _wait_attempt(attempt)
        assert manager._runtime_resolver.call_count == 1
        assert len(calls) == 1
        _, kwargs = calls[0]
        assert kwargs.get("runtime_info") is info


def test_08_list_models_resolves_once():
    from vrsoft_extractor.mary.provider_adapters.antigravity import AntigravityProvider

    info = AcpRuntimeInfo(executable_path="srv", harness_path="harness", version="1.0")
    client = MagicMock()
    client.request.side_effect = [
        {},  # authenticate
        {"sessionId": "s", "models": {"availableModels": [{"modelId": "m", "name": "M"}]}},
    ]
    provider = AntigravityProvider()
    with patch("vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account", return_value=True), \
         patch("vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime", return_value=info) as resolve_spy, \
         patch("vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client", return_value=client) as spawn_spy:
        models = provider.list_models()
    assert resolve_spy.call_count == 1
    assert spawn_spy.call_count == 1
    _, kwargs = spawn_spy.call_args
    assert kwargs.get("runtime_info") is info
    assert models and models[0]["id"] == "m"

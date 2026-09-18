"""Resolução única de runtime no send_message (correção residual).

Garante 1 resolução de runtime por spawn no fluxo de envio:
send_message() não usa available() como pré-check e reutiliza
exatamente o mesmo AcpRuntimeInfo no spawn_acp_client().
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vrsoft_extractor.mary.antigravity_acp import AcpRuntimeInfo, IncompleteRuntimeError, RUNTIME_NOT_FOUND_MESSAGE
from vrsoft_extractor.mary.provider_adapters.antigravity import AntigravityProvider
from vrsoft_extractor.mary.providers import ProviderError


def _send(provider, workspace, callback=None):
    return provider.send_message(
        "chat-runtime-once",
        "",
        "default",
        "auto",
        workspace,
        "Hello",
        callback or (lambda event: None),
    )


def test_01_send_message_resolves_runtime_once(tmp_path):
    """Teste 1 — send_message() resolve o runtime uma única vez."""
    provider = AntigravityProvider()
    runtime_info = SimpleNamespace(executable_path="acp", harness_path="harness")
    try:
        with patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account",
            return_value=True,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime",
            return_value=runtime_info,
        ) as resolve_spy, patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client",
            return_value=MagicMock(),
        ) as spawn_spy, patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.threading.Thread",
        ):
            _send(provider, tmp_path)
        assert resolve_spy.call_count == 1
        assert spawn_spy.call_count == 1
        _, kwargs = spawn_spy.call_args
        assert kwargs["runtime_info"] is runtime_info
    finally:
        provider.close()


def test_02_send_message_does_not_call_available(tmp_path):
    """Teste 2 — available() não é chamado por send_message()."""
    provider = AntigravityProvider()
    runtime_info = SimpleNamespace(executable_path="acp", harness_path="harness")
    try:
        with patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account",
            return_value=True,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime",
            return_value=runtime_info,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client",
            return_value=MagicMock(),
        ), patch.object(
            provider,
            "available",
            side_effect=AssertionError("send_message must not call available()"),
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.threading.Thread",
        ):
            _send(provider, tmp_path)
    finally:
        provider.close()


def test_03_missing_runtime_raises_without_spawn_or_thread(tmp_path):
    """Teste 3 — runtime ausente: ProviderError, sem spawn e sem thread."""
    provider = AntigravityProvider()
    try:
        with patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account",
            return_value=True,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime",
            return_value=None,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client",
        ) as spawn_spy, patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.threading.Thread",
        ) as thread_spy:
            with pytest.raises(ProviderError, match=RUNTIME_NOT_FOUND_MESSAGE):
                _send(provider, tmp_path)
        spawn_spy.assert_not_called()
        thread_spy.assert_not_called()
        assert "chat-runtime-once" not in provider._active
    finally:
        provider.close()


def test_04_incomplete_runtime_preserves_diagnostic(tmp_path):
    """Teste 4 — runtime incompleto: ProviderError com diagnóstico preservado."""
    provider = AntigravityProvider()
    diagnostic = "Runtime Antigravity incompleto: helper ausente na mesma instalação."
    try:
        with patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account",
            return_value=True,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime",
            side_effect=IncompleteRuntimeError(diagnostic),
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client",
        ) as spawn_spy, patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.threading.Thread",
        ) as thread_spy:
            with pytest.raises(ProviderError) as excinfo:
                _send(provider, tmp_path)
            assert diagnostic in str(excinfo.value)
        spawn_spy.assert_not_called()
        thread_spy.assert_not_called()
    finally:
        provider.close()


def test_05_valid_runtime_single_spawn_with_same_object(tmp_path):
    """Teste 5 — runtime válido: 1 resolve, 1 spawn, identidade preservada."""
    provider = AntigravityProvider()
    runtime_info = AcpRuntimeInfo(
        executable_path="server-exe",
        harness_path="harness-exe",
        version="9.9.9",
        runtime_dir="runtime-dir",
    )
    try:
        with patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account",
            return_value=True,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime",
            return_value=runtime_info,
        ) as resolve_spy, patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client",
            return_value=MagicMock(),
        ) as spawn_spy, patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.threading.Thread",
        ):
            _send(provider, tmp_path)
        assert resolve_spy.call_count == 1
        assert spawn_spy.call_count == 1
        _, kwargs = spawn_spy.call_args
        assert kwargs["runtime_info"] is runtime_info
    finally:
        provider.close()


def test_06_missing_credential_is_auth_error_not_runtime(tmp_path):
    """Conta sem credencial gera erro de autenticação, sem resolver runtime."""
    provider = AntigravityProvider()
    try:
        with patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.has_saved_account",
            return_value=False,
        ), patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.resolve_acp_runtime",
        ) as resolve_spy, patch(
            "vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client",
        ) as spawn_spy:
            with pytest.raises(ProviderError, match="Entre com Google"):
                _send(provider, tmp_path)
        resolve_spy.assert_not_called()
        spawn_spy.assert_not_called()
    finally:
        provider.close()

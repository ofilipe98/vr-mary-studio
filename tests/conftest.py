"""Shared test setup; provider integration scripts remain explicit manual runs."""

import os

import pytest


# Apply before test-module imports so individual QML files also work headlessly.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")


@pytest.fixture(autouse=True)
def fast_research(request, monkeypatch):
    """Exercise real retries/concurrency without production provider cooldowns."""
    if request.node.get_closest_marker("research_timing"):
        return
    from vrsoft_extractor.mary.execution import runner

    monkeypatch.setattr(runner, "RESEARCH_RETRY_BACKOFF_SECONDS", 0.0)


def _blocked_spawn_acp_client(*_args, **_kwargs):
    raise RuntimeError("spawn_acp_client bloqueado em testes; use patch explícito")


def pytest_configure(config):
    """Never boot the real ACP runtime in the user profile.

    QML/frontend tests building the full window trigger
    ``ProviderSettingsBridge.refreshModels`` -> ``AntigravityProvider.list_models``,
    which would spawn ``agy_acp_server.exe`` against the real saved account.
    Applied once for the whole session (not as a per-test fixture) because the
    refresh workers run on background threads that can outlive a test and call
    between fixture windows. Tests that need a spawn must patch
    ``vrsoft_extractor.mary.provider_adapters.antigravity.spawn_acp_client``
    explicitly (their patch wins over this blocker).
    """
    from vrsoft_extractor.mary.provider_adapters import antigravity

    antigravity.spawn_acp_client = _blocked_spawn_acp_client

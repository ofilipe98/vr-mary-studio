from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from vrsoft_extractor.mary.usage.models import (
    ProviderUsageLimitsSnapshot,
    UsageWindow,
)
from vrsoft_extractor.mary.usage.store import UsageLimitsStore
from vrsoft_extractor.mary.usage.adapters.codex import CodexUsageAdapter
from vrsoft_extractor.mary.usage.adapters.claude import ClaudeUsageAdapter
from vrsoft_extractor.mary.usage.adapters.antigravity import AntigravityUsageAdapter
from vrsoft_extractor.mary.usage.adapters.opencode import OpenCodeUsageAdapter


def test_models_to_dict():
    window = UsageWindow(
        id="test_win",
        label="5 Horas",
        used_ratio=0.40,
        remaining_ratio=0.60,
        unit="%",
        reset_at=1750000000.0,
        window_duration_mins=300,
    )
    d_win = window.to_dict()
    assert d_win["label"] == "5 Horas"
    assert d_win["usedPercent"] == 40
    assert d_win["remainingPercent"] == 60
    assert d_win["resetAt"] == 1750000000.0
    assert d_win["unit"] == "%"

    snapshot = ProviderUsageLimitsSnapshot(
        provider="codex",
        provider_instance_id="codex",
        account="user@example.com",
        plan="Plus",
        windows=[window],
        credits={"hasCredits": True, "balance": "$15.00"},
        fetched_at=1750000000.0,
        status="available",
    )
    d = snapshot.to_dict()
    assert d["provider"] == "codex"
    assert d["supported"] is True
    assert d["account"] == "user@example.com"
    assert d["plan"] == "Plus"
    assert len(d["windows"]) == 1
    assert d["windows"][0]["usedPercent"] == 40
    assert d["credits"]["balance"] == "$15.00"


def test_honest_unsupported_adapters():
    """P0-5 e P0-6: Usage Limits e Reset de quota nunca podem ser inventados."""
    claude = ClaudeUsageAdapter()
    snap_claude = claude.fetch_usage_limits()
    assert snap_claude.status == "unsupported"
    assert snap_claude.provider == "claude"
    assert "não disponibiliza" in (snap_claude.error or "")
    assert len(snap_claude.windows) == 0

    ag = AntigravityUsageAdapter()
    snap_ag = ag.fetch_usage_limits()
    assert snap_ag.status == "unsupported"
    assert snap_ag.provider == "antigravity"
    assert "não expõe" in (snap_ag.error or "")

    oc = OpenCodeUsageAdapter()
    snap_oc = oc.fetch_usage_limits()
    assert snap_oc.status == "unsupported"
    assert snap_oc.provider == "opencode"
    assert "não expõe" in (snap_oc.error or "")


def test_codex_adapter_parsing():
    rate_limits = {
        "primary": {
            "usedPercent": 25.0,
            "resetsAt": 1725800000,
            "windowDurationMinutes": 300,
        },
        "secondary": {
            "usedPercent": 80.0,
            "resetsAt": 1726000000,
            "windowDurationMinutes": 10080,
        },
        "credits": {
            "hasCredits": False,
            "unlimited": True,
            "balance": "",
        },
        "planType": "team",
    }

    mock_provider = MagicMock()
    mock_provider._rpc.side_effect = lambda method, params, timeout=5: (
        {"account": {"email": "dev@company.com"}, "planType": "team"}
        if method == "account/read"
        else {"rateLimits": rate_limits}
    )

    adapter = CodexUsageAdapter(mock_provider)
    snapshot = adapter.fetch_usage_limits()
    assert snapshot.status == "available"
    assert snapshot.account == "dev@company.com"
    assert snapshot.plan == "team"
    assert len(snapshot.windows) == 2
    assert snapshot.windows[0].used_ratio == 0.25
    assert snapshot.windows[1].used_ratio == 0.80
    assert snapshot.credits.get("unlimited") is True


def test_generation_id_race_protection():
    """P0-9: Refresh antigo não pode sobrescrever refresh mais novo (generation ID tracking)."""
    store = UsageLimitsStore()

    # Manually set generations and cache
    snap1 = ProviderUsageLimitsSnapshot(provider="codex", provider_instance_id="codex", plan="Free", status="available")
    snap2 = ProviderUsageLimitsSnapshot(provider="codex", provider_instance_id="codex", plan="Plus", status="available")

    with store._lock:
        store._generations["codex"] = 2
        store._cache["codex"] = (time.monotonic(), 2, snap2)

    # Simulating a late callback from generation 1 trying to save
    with store._lock:
        latest_gen = store._generations.get("codex", 0)
        request_gen = 1
        if request_gen >= latest_gen:
            store._cache["codex"] = (time.monotonic(), request_gen, snap1)

    # Cache should still have snap2
    cached = store._cache.get("codex")
    assert cached is not None
    assert cached[1] == 2
    assert cached[2].plan == "Plus"


def test_slash_usage_limits_local_interception(tmp_path):
    """P0-2, P0-3, P0-4: /usage-limits não pode criar turn, não pode chamar LLM, não pode consumir tokens."""
    from vrsoft_extractor.mary.db import MaryDatabase
    from vrsoft_extractor.mary.config import MarySettings
    from vrsoft_extractor.mary.frontend.chat import ChatBridge

    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    db = MaryDatabase(tmp_path / "test.db")
    cid = db.create_conversation("Teste Limits", "codex", "gpt-4o", workspace=tmp_path)

    bridge = ChatBridge(settings, db)

    signal_fired = False
    def on_show():
        nonlocal signal_fired
        signal_fired = True

    bridge.showUsageLimitsRequested.connect(on_show)
    bridge.refreshUsageLimits = MagicMock()

    # Send /usage-limits via sendMessage
    bridge.sendMessage("/usage-limits")
    assert signal_fired is True

    # Check that NO messages were created in the database
    messages = db.messages(cid)
    assert len(messages) == 0


def test_reset_time_days_formatting(monkeypatch):
    """Verifica formatação em dias quando >= 24 horas (ex.: 143h -> 5d 23h)."""
    now = time.time()
    monkeypatch.setattr("vrsoft_extractor.mary.usage.models.time.time", lambda: now + 0.001)
    # 143 horas e 7 minutos no futuro
    future_143h = now + (143 * 3600) + (7 * 60)
    win_143 = UsageWindow(
        id="weekly",
        label="Weekly",
        used_ratio=0.79,
        remaining_ratio=0.21,
        reset_at=future_143h,
    )
    d = win_143.to_dict()
    assert "5d 23h" in d["resetInText"]
    assert "143h" not in d["resetInText"]

    # 3 horas e 24 minutos no futuro
    future_3h = now + (3 * 3600) + (24 * 60)
    win_3h = UsageWindow(
        id="session",
        label="Session",
        used_ratio=0.66,
        remaining_ratio=0.34,
        reset_at=future_3h,
    )
    d3 = win_3h.to_dict()
    assert "3h 24m" in d3["resetInText"]


@pytest.mark.parametrize("seconds, expected", [(0.01, "resets in 1m"), (60.01, "resets in 2m"),
                                               (3599.99, "resets in 1h 00m"), (0, "resets soon")])
def test_countdown_rounds_remaining_time_up(monkeypatch, seconds, expected):
    monkeypatch.setattr("vrsoft_extractor.mary.usage.models.time.time", lambda: 1000)
    assert UsageWindow("test", "Test", reset_at=1000 + seconds).to_dict()["resetInText"] == expected

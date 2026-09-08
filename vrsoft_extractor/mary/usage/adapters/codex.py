from __future__ import annotations

import logging
import time

from ..models import ProviderUsageLimitsSnapshot, UsageWindow
from .base import ProviderUsageAdapter

LOGGER = logging.getLogger(__name__)


class CodexUsageAdapter(ProviderUsageAdapter):
    provider_name = "codex"

    def __init__(self, codex_provider=None) -> None:
        self._provider = codex_provider

    def set_provider(self, provider) -> None:
        self._provider = provider

    def fetch_usage_limits(self) -> ProviderUsageLimitsSnapshot:
        if self._provider is None:
            return self.make_unsupported_snapshot("Codex provider não instanciado.")

        if hasattr(self._provider, "_ensure_started"):
            try:
                self._provider._ensure_started()
            except Exception as exc:
                LOGGER.warning("Codex _ensure_started falhou: %s", exc)

        account_email = ""
        plan_type = ""

        # 1. Fetch account info
        try:
            acc_resp = self._provider._rpc("account/read", {}, timeout=5)
            acc_data = acc_resp.get("account") or {}
            account_email = str(acc_data.get("email") or "")
            plan_type = str(acc_data.get("planType") or "")
        except Exception as exc:
            LOGGER.warning("Codex account/read falhou: %s", exc)

        # 2. Fetch rate limits
        try:
            rl_resp = self._provider._rpc("account/rateLimits/read", {}, timeout=5)
        except Exception as exc:
            LOGGER.warning("Codex account/rateLimits/read falhou: %s", exc)
            return ProviderUsageLimitsSnapshot(
                provider="codex",
                provider_instance_id="codex",
                account=account_email,
                plan=plan_type,
                windows=[],
                credits=None,
                fetched_at=time.time(),
                source="rpc",
                status="error",
                error=f"Falha ao consultar limites: {exc}",
            )

        rate_limits = rl_resp.get("rateLimits") or {}
        if not plan_type:
            plan_type = str(rate_limits.get("planType") or "")

        windows: list[UsageWindow] = []

        # Primary window (e.g. Session window)
        primary = rate_limits.get("primary")
        if isinstance(primary, dict):
            used_pct = primary.get("usedPercent")
            duration = primary.get("windowDurationMins") or 300
            resets_at = primary.get("resetsAt")

            used_ratio = float(used_pct) / 100.0 if used_pct is not None else None
            remaining_ratio = max(0.0, 1.0 - used_ratio) if used_ratio is not None else None

            windows.append(
                UsageWindow(
                    id="codex_primary",
                    label="Session",
                    used_ratio=used_ratio,
                    remaining_ratio=remaining_ratio,
                    unit="%",
                    reset_at=resets_at,
                    window_duration_mins=duration,
                    metadata=dict(primary),
                )
            )

        # Secondary window (e.g. Weekly window)
        secondary = rate_limits.get("secondary")
        if isinstance(secondary, dict):
            used_pct = secondary.get("usedPercent")
            duration = secondary.get("windowDurationMins") or 10080
            resets_at = secondary.get("resetsAt")

            used_ratio = float(used_pct) / 100.0 if used_pct is not None else None
            remaining_ratio = max(0.0, 1.0 - used_ratio) if used_ratio is not None else None

            windows.append(
                UsageWindow(
                    id="codex_secondary",
                    label="Weekly",
                    used_ratio=used_ratio,
                    remaining_ratio=remaining_ratio,
                    unit="%",
                    reset_at=resets_at,
                    window_duration_mins=duration,
                    metadata=dict(secondary),
                )
            )

        credits_raw = rate_limits.get("credits")
        credits_dict = dict(credits_raw) if isinstance(credits_raw, dict) else None

        return ProviderUsageLimitsSnapshot(
            provider="codex",
            provider_instance_id="codex",
            account=account_email,
            plan=plan_type,
            windows=windows,
            credits=credits_dict,
            fetched_at=time.time(),
            source="rpc",
            status="available",
            error=None,
        )

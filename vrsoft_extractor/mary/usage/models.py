from __future__ import annotations

import datetime
import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UsageWindow:
    id: str
    label: str
    used_ratio: float | None = None  # 0.0 to 1.0
    remaining_ratio: float | None = None  # 0.0 to 1.0
    used_amount: float | None = None
    limit_amount: float | None = None
    unit: str | None = None
    reset_at: float | None = None  # epoch timestamp (seconds)
    window_started_at: float | None = None
    window_duration_mins: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        used_pct = round(self.used_ratio * 100) if self.used_ratio is not None else None
        remaining_pct = round(self.remaining_ratio * 100) if self.remaining_ratio is not None else None

        # Calculate human-readable reset string if reset_at is available
        reset_in_text = ""
        reset_time_text = ""
        if self.reset_at is not None and self.reset_at > 0:
            dt_reset = datetime.datetime.fromtimestamp(self.reset_at)
            reset_time_text = dt_reset.strftime("%H:%M:%S")
            now_ts = time.time()
            diff_secs = self.reset_at - now_ts
            if diff_secs > 0:
                # A positive fraction of a minute is still time remaining.
                hours, mins = divmod(math.ceil(diff_secs / 60), 60)
                if hours >= 24:
                    days = hours // 24
                    rem_hours = hours % 24
                    if rem_hours > 0:
                        reset_in_text = f"resets in {days}d {rem_hours}h"
                    else:
                        reset_in_text = f"resets in {days}d"
                elif hours > 0:
                    reset_in_text = f"resets in {hours}h {mins:02d}m"
                else:
                    reset_in_text = f"resets in {mins}m"
            else:
                reset_in_text = "resets soon"

        return {
            "id": self.id,
            "label": self.label,
            "usedRatio": self.used_ratio,
            "remainingRatio": self.remaining_ratio,
            "usedPercent": used_pct,
            "remainingPercent": remaining_pct,
            "usedAmount": self.used_amount,
            "limitAmount": self.limit_amount,
            "unit": self.unit or "%",
            "resetAt": self.reset_at,
            "resetTimeText": reset_time_text,
            "resetInText": reset_in_text,
            "windowStartedAt": self.window_started_at,
            "windowDurationMins": self.window_duration_mins,
            "metadata": dict(self.metadata),
        }


@dataclass
class ProviderUsageLimitsSnapshot:
    provider: str
    provider_instance_id: str
    account: str = ""
    plan: str = ""
    windows: list[UsageWindow] = field(default_factory=list)
    credits: dict[str, Any] | None = None
    fetched_at: float = 0.0  # epoch timestamp (seconds)
    source: str = "cache"
    status: str = "unsupported"  # available, unsupported, unavailable, error, stale
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        fetched_text = ""
        if self.fetched_at > 0:
            fetched_text = datetime.datetime.fromtimestamp(self.fetched_at).strftime("%d/%m %H:%M:%S")

        return {
            "provider": self.provider,
            "providerInstanceId": self.provider_instance_id,
            "account": self.account,
            "plan": self.plan,
            "windows": [w.to_dict() for w in self.windows],
            "credits": self.credits or {},
            "fetchedAt": self.fetched_at,
            "fetchedText": fetched_text,
            "source": self.source,
            "status": self.status,
            "error": self.error or "",
            "supported": self.status == "available",
        }

from __future__ import annotations

from ..models import ProviderUsageLimitsSnapshot
from .base import ProviderUsageAdapter


class AntigravityUsageAdapter(ProviderUsageAdapter):
    provider_name = "antigravity"

    def fetch_usage_limits(self) -> ProviderUsageLimitsSnapshot:
        return self.make_unsupported_snapshot(
            "O servidor ACP do Google Antigravity não expõe janelas de quotas de rate limit."
        )

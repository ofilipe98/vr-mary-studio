from __future__ import annotations

from ..models import ProviderUsageLimitsSnapshot
from .base import ProviderUsageAdapter


class ClaudeUsageAdapter(ProviderUsageAdapter):
    provider_name = "claude"

    def fetch_usage_limits(self) -> ProviderUsageLimitsSnapshot:
        return self.make_unsupported_snapshot(
            "O runtime local do Claude Code não disponibiliza API estruturada de quotas ou limites de uso."
        )

from __future__ import annotations

from ..models import ProviderUsageLimitsSnapshot
from .base import ProviderUsageAdapter


class OpenCodeUsageAdapter(ProviderUsageAdapter):
    provider_name = "opencode"

    def fetch_usage_limits(self) -> ProviderUsageLimitsSnapshot:
        return self.make_unsupported_snapshot(
            "O runtime OpenCode não expõe limites de uso ou janelas de quota do provedor."
        )

from __future__ import annotations

import abc
import time
from ..models import ProviderUsageLimitsSnapshot


class ProviderUsageAdapter(abc.ABC):
    provider_name: str

    @abc.abstractmethod
    def fetch_usage_limits(self) -> ProviderUsageLimitsSnapshot:
        ...

    def make_unsupported_snapshot(self, reason: str = "Provedor não expõe limites de uso ou quotas.") -> ProviderUsageLimitsSnapshot:
        return ProviderUsageLimitsSnapshot(
            provider=self.provider_name,
            provider_instance_id=self.provider_name,
            account="",
            plan="",
            windows=[],
            credits=None,
            fetched_at=time.time(),
            source="adapter",
            status="unsupported",
            error=reason,
        )

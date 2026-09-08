from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from .adapters.antigravity import AntigravityUsageAdapter
from .adapters.base import ProviderUsageAdapter
from .adapters.claude import ClaudeUsageAdapter
from .adapters.codex import CodexUsageAdapter
from .adapters.opencode import OpenCodeUsageAdapter
from .models import ProviderUsageLimitsSnapshot

LOGGER = logging.getLogger(__name__)


class UsageLimitsStore:
    def __init__(
        self,
        codex_provider=None,
        provider_instances: dict[str, Any] | None = None,
    ) -> None:
        if provider_instances and not codex_provider:
            codex_provider = provider_instances.get("codex")

        self._lock = threading.Lock()
        self._adapters: dict[str, ProviderUsageAdapter] = {
            "codex": CodexUsageAdapter(codex_provider),
            "claude": ClaudeUsageAdapter(),
            "antigravity": AntigravityUsageAdapter(),
            "opencode": OpenCodeUsageAdapter(),
        }
        # provider -> (timestamp, generation_id, snapshot)
        self._cache: dict[str, tuple[float, int, ProviderUsageLimitsSnapshot]] = {}
        # provider -> highest requested generation_id
        self._generations: dict[str, int] = {}
        self._cache_ttl = 45.0  # 45 seconds TTL for usage cache

    def set_codex_provider(self, codex_provider) -> None:
        with self._lock:
            codex_adapter = self._adapters.get("codex")
            if isinstance(codex_adapter, CodexUsageAdapter):
                codex_adapter.set_provider(codex_provider)
            else:
                self._adapters["codex"] = CodexUsageAdapter(codex_provider)

    def get_snapshot(self, provider_name: str, force_reload: bool = False) -> ProviderUsageLimitsSnapshot:
        """Synchronously return current cached snapshot or fetch if expired/missing."""
        provider_key = provider_name.lower().strip()
        now = time.monotonic()

        with self._lock:
            cached = self._cache.get(provider_key)
            if not force_reload and cached:
                ts, gen, snap = cached
                if now - ts < self._cache_ttl:
                    return snap

            # Advance generation counter
            new_gen = self._generations.get(provider_key, 0) + 1
            self._generations[provider_key] = new_gen

        # Fetch outside lock
        adapter = self._adapters.get(provider_key)
        if not adapter:
            snap = ProviderUsageLimitsSnapshot(
                provider=provider_key,
                provider_instance_id=provider_key,
                status="unsupported",
                error=f"Provedor desconhecido: {provider_name}",
            )
        else:
            try:
                snap = adapter.fetch_usage_limits()
            except Exception as exc:
                LOGGER.error("Erro ao buscar limites de uso para %s: %s", provider_name, exc)
                snap = ProviderUsageLimitsSnapshot(
                    provider=provider_key,
                    provider_instance_id=provider_key,
                    status="error",
                    error=str(exc),
                )

        # Store with generation check (P0-9: Stale refresh must not overwrite newer refresh)
        with self._lock:
            latest_gen = self._generations.get(provider_key, 0)
            if new_gen < latest_gen:
                LOGGER.info("Descartando resposta obsoleta de limites para %s (gen %d < %d)", provider_key, new_gen, latest_gen)
                # Return current cached if present
                if cached:
                    return cached[2]
                return snap
            self._cache[provider_key] = (now, new_gen, snap)

        return snap

    def refresh_snapshot_async(
        self,
        provider_name: str,
        on_success: Callable[[ProviderUsageLimitsSnapshot], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> int:
        """Start async refresh and return the allocated generation_id."""
        provider_key = provider_name.lower().strip()
        with self._lock:
            gen = self._generations.get(provider_key, 0) + 1
            self._generations[provider_key] = gen

        def _worker(request_gen: int):
            adapter = self._adapters.get(provider_key)
            if not adapter:
                snap = ProviderUsageLimitsSnapshot(
                    provider=provider_key,
                    provider_instance_id=provider_key,
                    status="unsupported",
                    error=f"Provedor desconhecido: {provider_name}",
                )
            else:
                try:
                    snap = adapter.fetch_usage_limits()
                except Exception as exc:
                    LOGGER.error("Erro assíncrono ao buscar limites de %s: %s", provider_name, exc)
                    snap = ProviderUsageLimitsSnapshot(
                        provider=provider_key,
                        provider_instance_id=provider_key,
                        status="error",
                        error=str(exc),
                    )

            with self._lock:
                latest_gen = self._generations.get(provider_key, 0)
                if request_gen < latest_gen:
                    LOGGER.info("Descartando snapshot assíncrono obsoleto para %s (gen %d < %d)", provider_key, request_gen, latest_gen)
                    return
                self._cache[provider_key] = (time.monotonic(), request_gen, snap)

            if on_success:
                try:
                    on_success(snap)
                except Exception as exc:
                    LOGGER.warning("Callback on_success falhou: %s", exc)

        t = threading.Thread(target=_worker, args=(gen,), daemon=True, name=f"usage-refresh-{provider_key}-{gen}")
        t.start()
        return gen

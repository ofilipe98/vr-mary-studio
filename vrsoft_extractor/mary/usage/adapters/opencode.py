from __future__ import annotations

import datetime
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..models import ProviderUsageLimitsSnapshot, UsageWindow
from .base import ProviderUsageAdapter

LOGGER = logging.getLogger(__name__)

# Canonical destination of the OpenCode Go subscription. The bearer key is only
# ever sent to this exact URL and redirects are refused.
USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
GO_AUTH_PROVIDER_ID = "opencode-go"
GO_PLAN_NAME = "Go"
REQUEST_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 64 * 1024

# (payload key, window id, label, window duration in minutes)
GO_WINDOW_SPECS = (
    ("rolling", "opencode_go_rolling", "5-hour", 300),
    ("weekly", "opencode_go_weekly", "Weekly", 10080),
    ("monthly", "opencode_go_monthly", "Monthly", 43200),
)


class OpenCodeUsageError(Exception):
    """Raised when the OpenCode Go usage endpoint cannot be read."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses redirects so the bearer key never leaves the canonical host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def default_auth_file() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return root / "opencode" / "auth.json"


def read_local_api_key(auth_file: Path) -> str:
    try:
        payload = json.loads(auth_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    entry = payload.get(GO_AUTH_PROVIDER_ID) if isinstance(payload, dict) else None
    key = entry.get("key") if isinstance(entry, dict) else None
    return key.strip() if isinstance(key, str) and key.strip() else ""


def _reset_epoch(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text[-1:] in {"Z", "z"}:
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _used_ratio(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    if percent != percent:
        return None
    return max(0.0, min(1.0, percent / 100.0))


def parse_usage_windows(payload: Any) -> list[UsageWindow]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        raise ValueError("Resposta do endpoint de limites do OpenCode Go sem o objeto 'usage'.")

    windows: list[UsageWindow] = []
    for key, window_id, label, duration in GO_WINDOW_SPECS:
        entry = usage.get(key)
        if not isinstance(entry, dict):
            continue
        used_ratio = _used_ratio(entry.get("percent"))
        windows.append(
            UsageWindow(
                id=window_id,
                label=label,
                used_ratio=used_ratio,
                remaining_ratio=None if used_ratio is None else max(0.0, 1.0 - used_ratio),
                unit="%",
                reset_at=_reset_epoch(entry.get("resetsAt")),
                window_duration_mins=duration,
                metadata=dict(entry),
            )
        )
    if not windows:
        raise ValueError("Resposta do OpenCode Go não informou nenhuma janela de limite.")
    return windows


class OpenCodeUsageAdapter(ProviderUsageAdapter):
    """Reads the rolling/weekly/monthly windows of the OpenCode Go plan."""

    provider_name = "opencode"

    def __init__(self, api_key: str | None = None, auth_file: Path | None = None) -> None:
        # ``None`` resolves the key at fetch time; an explicit value disables
        # that lookup, which keeps tests free of local credentials.
        self._explicit_api_key = api_key
        self._auth_file = auth_file

    def _resolve_api_key(self) -> str:
        if self._explicit_api_key is not None:
            return self._explicit_api_key.strip()
        local_key = read_local_api_key(self._auth_file or default_auth_file())
        if local_key:
            return local_key
        return os.environ.get("OPENCODE_API_KEY", "").strip()

    def _request_usage(self, api_key: str) -> dict[str, Any]:
        request = urllib.request.Request(
            USAGE_URL,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + api_key,
                "User-Agent": "VRStudio-OpenCodeUsage/1",
            },
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                status_code = int(getattr(response, "status", 200) or 200)
                if status_code != 200:
                    raise OpenCodeUsageError(
                        f"O endpoint de limites do OpenCode Go respondeu HTTP {status_code}."
                    )
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            reason = (
                "O serviço do OpenCode Go recusou a chave"
                if exc.code in (401, 403)
                else "O endpoint de limites do OpenCode Go respondeu"
            )
            raise OpenCodeUsageError(f"{reason} (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            detail = getattr(exc, "reason", None) or exc
            raise OpenCodeUsageError(f"Falha ao consultar os limites do OpenCode Go: {detail}") from None

        if len(raw) > MAX_RESPONSE_BYTES:
            raise OpenCodeUsageError("Resposta do endpoint de limites do OpenCode Go excede o limite esperado.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OpenCodeUsageError("O endpoint de limites do OpenCode Go retornou JSON inválido.") from None
        if not isinstance(payload, dict):
            raise OpenCodeUsageError("O endpoint de limites do OpenCode Go retornou um payload inesperado.")
        return payload

    def fetch_usage_limits(self) -> ProviderUsageLimitsSnapshot:
        api_key = self._resolve_api_key()
        if not api_key:
            return self.make_unsupported_snapshot(
                "OpenCode Go não está conectado: nenhuma chave de API local foi encontrada."
            )

        try:
            windows = parse_usage_windows(self._request_usage(api_key))
        except (OpenCodeUsageError, ValueError) as exc:
            LOGGER.warning("Limites de uso do OpenCode Go indisponíveis: %s", exc)
            return ProviderUsageLimitsSnapshot(
                provider=self.provider_name,
                provider_instance_id=self.provider_name,
                plan=GO_PLAN_NAME,
                windows=[],
                credits=None,
                fetched_at=time.time(),
                source="api",
                status="error",
                error=str(exc),
            )

        return ProviderUsageLimitsSnapshot(
            provider=self.provider_name,
            provider_instance_id=self.provider_name,
            plan=GO_PLAN_NAME,
            windows=windows,
            credits=None,
            fetched_at=time.time(),
            source="api",
            status="available",
            error=None,
        )

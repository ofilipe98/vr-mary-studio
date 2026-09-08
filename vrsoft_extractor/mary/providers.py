"""Compatibility facade. Concrete transports live in provider_adapters."""
from __future__ import annotations
import queue as queue
import subprocess as subprocess
from pathlib import Path

from .provider_adapters.base import (
    _seconds_from_env as _seconds_from_env,
    _as_token_count as _as_token_count,
    _token_breakdown as _token_breakdown,
    _claude_token_usage as _claude_token_usage,
    _opencode_token_usage as _opencode_token_usage,
    ProviderError as ProviderError,
    ProviderRateLimited as ProviderRateLimited,
    AgentProvider,
    normalize_effort as normalize_effort,
    _resolve_opencode_command as _resolve_opencode_command,
    _parse_opencode_models as _parse_opencode_models,
    _opencode_environment as _opencode_environment,
    _opencode_error_message as _opencode_error_message,
    _resolve_codex_command as _resolve_codex_command,
    _item_summary as _item_summary,
    EventCallback as EventCallback,
)
from .provider_adapters.codex import CodexProvider
from .provider_adapters.claude import ClaudeProvider
from .provider_adapters.opencode import OpenCodeProvider

def provider_registry(knowledge_root: Path | None = None) -> dict[str, AgentProvider]:
    from .antigravity import AntigravityProvider

    return {
        "codex": CodexProvider(knowledge_root),
        "claude": ClaudeProvider(knowledge_root),
        "opencode": OpenCodeProvider(knowledge_root),
        "antigravity": AntigravityProvider(knowledge_root),
    }

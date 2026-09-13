from __future__ import annotations
import abc
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable
from ..provider_cli import resolve_cli
from ..models import ConversationOptions, RuntimeEvent, approval_preset

EventCallback = Callable[[RuntimeEvent], None]


def _seconds_from_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _as_token_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _token_breakdown(
    *,
    input_tokens: Any = 0,
    output_tokens: Any = 0,
    reasoning_tokens: Any = 0,
    cached_tokens: Any = 0,
    cache_write_tokens: Any = 0,
    total_tokens: Any = 0,
) -> dict[str, int]:
    input_count = _as_token_count(input_tokens)
    output_count = _as_token_count(output_tokens)
    reasoning_count = _as_token_count(reasoning_tokens)
    cached_count = _as_token_count(cached_tokens)
    cache_write_count = _as_token_count(cache_write_tokens)
    total_count = _as_token_count(total_tokens) or (
        input_count + output_count + reasoning_count
    )
    return {
        "inputTokens": input_count,
        "outputTokens": output_count,
        "reasoningOutputTokens": reasoning_count,
        "cachedInputTokens": cached_count,
        "cacheWriteInputTokens": cache_write_count,
        "totalTokens": total_count,
    }


def _claude_token_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize the final Claude Code usage record to the shared event shape."""

    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    model_usage = payload.get("modelUsage") or payload.get("model_usage") or {}
    model_records = (
        [item for item in model_usage.values() if isinstance(item, dict)]
        if isinstance(model_usage, dict)
        else []
    )
    if not usage and model_records:
        usage = {
            "input_tokens": sum(
                _as_token_count(item.get("inputTokens") or item.get("input_tokens"))
                for item in model_records
            ),
            "output_tokens": sum(
                _as_token_count(item.get("outputTokens") or item.get("output_tokens"))
                for item in model_records
            ),
            "cache_read_input_tokens": sum(
                _as_token_count(
                    item.get("cacheReadInputTokens")
                    or item.get("cache_read_input_tokens")
                )
                for item in model_records
            ),
            "cache_creation_input_tokens": sum(
                _as_token_count(
                    item.get("cacheCreationInputTokens")
                    or item.get("cache_creation_input_tokens")
                )
                for item in model_records
            ),
        }
    if not usage:
        return None
    cached = _as_token_count(
        usage.get("cache_read_input_tokens") or usage.get("cacheReadInputTokens")
    )
    cache_write = _as_token_count(
        usage.get("cache_creation_input_tokens")
        or usage.get("cacheCreationInputTokens")
    )
    input_tokens = _as_token_count(
        usage.get("input_tokens") or usage.get("inputTokens")
    ) + cached + cache_write
    breakdown = _token_breakdown(
        input_tokens=input_tokens,
        output_tokens=usage.get("output_tokens") or usage.get("outputTokens"),
        cached_tokens=cached,
        cache_write_tokens=cache_write,
        total_tokens=usage.get("total_tokens") or usage.get("totalTokens"),
    )
    context_window = max(
        (
            _as_token_count(
                item.get("contextWindow") or item.get("context_window")
            )
            for item in model_records
        ),
        default=0,
    )
    return {
        "tokenUsage": {
            "last": breakdown,
            "modelContextWindow": context_window or None,
        }
    }


def _opencode_token_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one OpenCode model step without assuming a model vendor."""

    part = payload.get("part") or {}
    if not isinstance(part, dict):
        part = {}
    usage = part.get("tokens") or payload.get("tokens") or payload.get("usage") or {}
    if not isinstance(usage, dict) or not usage:
        return None
    cache = usage.get("cache") or {}
    if not isinstance(cache, dict):
        cache = {}
    breakdown = _token_breakdown(
        input_tokens=usage.get("input") or usage.get("inputTokens"),
        output_tokens=usage.get("output") or usage.get("outputTokens"),
        reasoning_tokens=usage.get("reasoning") or usage.get("reasoningTokens"),
        cached_tokens=cache.get("read") or usage.get("cachedInputTokens"),
        cache_write_tokens=cache.get("write") or usage.get("cacheWriteInputTokens"),
        total_tokens=usage.get("total") or usage.get("totalTokens"),
    )
    if not breakdown["totalTokens"]:
        return None
    context_window = _as_token_count(
        part.get("contextWindow")
        or part.get("context_window")
        or payload.get("contextWindow")
        or payload.get("context_window")
    )
    return {
        "tokenUsage": {
            "last": breakdown,
            "modelContextWindow": context_window or None,
        }
    }


class ProviderError(RuntimeError):
    pass


class ProviderRateLimited(ProviderError):
    """The configured provider explicitly rejected requests due to its quota."""


UUID4_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class AgentProvider(abc.ABC):
    name: str

    @property
    def capabilities(self):
        from .capabilities import CAPABILITIES, ProviderCapabilities
        return CAPABILITIES.get(self.name, ProviderCapabilities(False, True, False, "unsupported", "unknown"))

    def __init__(self, knowledge_root: Path | None = None):
        self.knowledge_root = knowledge_root.resolve() if knowledge_root else None

    @abc.abstractmethod
    def available(self) -> bool: ...

    @abc.abstractmethod
    def list_models(self) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    def start_conversation(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str: ...

    @abc.abstractmethod
    def resume_conversation(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str: ...

    @abc.abstractmethod
    def send_message(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        message: str,
        callback: EventCallback,
        options: ConversationOptions | None = None,
        skills: list[dict[str, Any]] | None = None,
        image_paths: list[str] | None = None,
    ) -> None: ...

    @abc.abstractmethod
    def interrupt(self, conversation_id: str) -> None: ...

    @abc.abstractmethod
    def approve_action(
        self,
        request_id: str,
        approved: bool,
        session: bool = False,
        request: dict[str, Any] | None = None,
    ) -> None: ...

    def list_collaboration_modes(self) -> list[dict[str, Any]]:
        return [
            {"name": "Build", "mode": "default"},
            {"name": "Plan", "mode": "plan"},
        ]

    def list_mcp_tools(self) -> list[dict[str, Any]]:
        return []

    def list_skills(
        self, workspace: Path, force_reload: bool = False
    ) -> dict[str, list[Any]]:
        return {"skills": [], "errors": []}

    def update_settings(
        self, conversation_id: str, native_id: str, workspace: Path, options: ConversationOptions
    ) -> None:
        return None

    def archive_thread(self, native_id: str) -> None:
        return None

    def unarchive_thread(self, native_id: str) -> None:
        return None

    def delete_thread(self, native_id: str) -> None:
        return None

    def fork_thread(
        self,
        conversation_id: str,
        native_id: str,
        last_turn_id: str,
        workspace: Path,
        options: ConversationOptions,
    ) -> str:
        return ""

    def release_conversation(
        self, conversation_id: str, native_id: str, *, delete_native: bool = False
    ) -> None:
        """Release provider-local state for an internal/ephemeral run."""
        if delete_native and native_id:
            self.delete_thread(native_id)

    @abc.abstractmethod
    def close(self) -> None: ...


def normalize_effort(effort: str, provider: str = "codex") -> str:
    value = str(effort or "medium").strip().lower()
    # Older conversations may have persisted the former UI label. Keep them
    # valid while consolidating the highest reasoning choice under ``max``.
    if value == "ultra":
        value = "max"
    allowed = (
        {"low", "medium", "high", "xhigh", "max"}
        if provider == "claude"
        else {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
    )
    return value if value in allowed else "medium"


def _resolve_opencode_command() -> str | None:
    direct = shutil.which("opencode.exe")
    if direct:
        return direct
    shim = shutil.which("opencode.cmd") or shutil.which("opencode")
    if shim:
        shim_path = Path(shim)
        bundled = shim_path.parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if bundled.is_file():
            return str(bundled)
    return shim


def _parse_opencode_models(output: str) -> list[dict[str, Any]]:
    lines = str(output or "").splitlines()
    models: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        qualified_id = lines[index].strip()
        index += 1
        if not qualified_id or "/" not in qualified_id or qualified_id.startswith(("{", "[")):
            continue
        metadata: dict[str, Any] = {}
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index < len(lines) and lines[index].lstrip().startswith("{"):
            block: list[str] = []
            while index < len(lines):
                block.append(lines[index])
                index += 1
                try:
                    parsed = json.loads("\n".join(block))
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    metadata = parsed
                break
        if str(metadata.get("status") or "active") != "active":
            continue
        capabilities = metadata.get("capabilities") or {}
        capability_names = ["coding"]
        if isinstance(capabilities, dict) and capabilities.get("reasoning"):
            capability_names.append("reasoning")
        variants = metadata.get("variants") or {}
        efforts = [
            value
            for value in ("low", "medium", "high", "xhigh", "max")
            if isinstance(variants, dict) and value in variants
        ]
        limit = metadata.get("limit") or {}
        item: dict[str, Any] = {
            "id": qualified_id,
            "model": qualified_id,
            "displayName": str(metadata.get("name") or qualified_id),
            "description": f"Modelo {qualified_id} disponível no OpenCode.",
            "capabilities": capability_names,
            "supportedReasoningEfforts": efforts or ["medium"],
            "_opencodeVariants": efforts,
        }
        if isinstance(limit, dict) and limit.get("context"):
            item["contextWindow"] = int(limit["context"])
        models.append(item)
    return models


def _opencode_environment(
    approval_profile: str, knowledge_root: Path | None = None, knowledge_context_path: str = ""
) -> dict[str, str]:
    environment = os.environ.copy()
    config: dict[str, Any] = {}
    existing = environment.get("OPENCODE_CONFIG_CONTENT", "").strip()
    if existing:
        try:
            parsed = json.loads(existing)
            if isinstance(parsed, dict):
                config.update(parsed)
        except json.JSONDecodeError:
            pass
    preset = approval_preset(approval_profile)
    if preset.sandbox == "danger-full-access":
        permission: dict[str, str] | str = "allow"
    else:
        permission: dict[str, Any] = {
            "*": "deny",
            "read": "allow",
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
        }
        if preset.sandbox != "read-only":
            permission["edit"] = "allow"
            permission["bash"] = "allow"
        permission["webfetch"] = "allow"
        if knowledge_root:
            resolved_root = str(knowledge_root.resolve()).replace("\\", "/")
            knowledge_pattern = resolved_root.rstrip("/") + "/**"
            permission["external_directory"] = {knowledge_pattern: "allow"}
            if preset.sandbox != "read-only":
                permission["edit"] = {"*": "allow", knowledge_pattern: "deny"}
                search_script = resolved_root.rstrip("/") + "/tools/vr-search.ps1"
                permission["bash"] = {
                    "*": "allow",
                    f"*{resolved_root}*": "deny",
                    f"*{search_script}*": "allow",
                }
            permission["webfetch"] = "allow"
    if knowledge_root:
        from ..knowledge_access import mcp_command
        config.setdefault("mcp", {})["vr-mary-studio"] = {
            "type": "local", "command": mcp_command(knowledge_root, knowledge_context_path),
        }
        if isinstance(permission, dict):
            permission["vr-mary-studio_*"] = "allow"
    config["permission"] = permission
    environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(config, ensure_ascii=False)
    return environment


def _opencode_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error") or {}
    if isinstance(error, dict):
        data = error.get("data") or {}
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
        if error.get("message"):
            return str(error["message"])
    return str(error or payload.get("message") or "Falha no OpenCode.")


def _resolve_codex_command() -> str | None:
    return resolve_cli("codex")


def _item_summary(item: dict[str, Any]) -> str:
    item_type = str(item.get("type", "item"))
    if item_type == "commandExecution":
        command = item.get("command")
        return "Comando: " + (" ".join(command) if isinstance(command, list) else str(command or ""))
    if item_type == "fileChange":
        changes = item.get("changes") or []
        return f"Alterações de arquivo: {len(changes)}"
    if item_type == "mcpToolCall":
        return f"Ferramenta: {item.get('server', '')}/{item.get('tool', '')}"
    return item_type

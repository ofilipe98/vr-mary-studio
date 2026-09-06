from __future__ import annotations

import abc
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

from .. import __version__ as APP_VERSION
from .chat_tools import mcp_thread_config
from .models import ConversationOptions, RuntimeEvent, approval_preset


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


class CodexProvider(AgentProvider):
    name = "codex"

    def __init__(self, knowledge_root: Path | None = None):
        super().__init__(knowledge_root)
        self.command = _resolve_codex_command()
        self.process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._request_id = 0
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._callbacks: dict[str, EventCallback] = {}
        self._native_to_local: dict[str, str] = {}
        self._active_turns: dict[str, str] = {}
        self._completed_turn_ids: dict[str, set[str]] = {}
        self._item_turn_ids: dict[tuple[str, str], str] = {}
        self._assistant_item_keys: dict[str, str] = {}
        self._assistant_item_phases: dict[tuple[str, str], str] = {}
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._start_lock = threading.RLock()
        self._stderr_lines: deque[str] = deque(maxlen=30)
        self._known_mcp_servers: list[str] = []
        self._mcp_server_configs: dict[str, dict[str, Any]] = {}
        self._has_started_once = False
        self.rpc_timeout_seconds = _seconds_from_env(
            "VR_CODEX_RPC_TIMEOUT_SECONDS", 45.0
        )
        self.start_timeout_seconds = _seconds_from_env(
            "VR_CODEX_START_TIMEOUT_SECONDS", 10.0
        )

    def available(self) -> bool:
        return bool(self.command)

    def _ensure_started(self) -> None:
        with self._start_lock:
            with self._state_lock:
                previous = self.process
            if previous and previous.poll() is None:
                return
            if previous is not None:
                with self._state_lock:
                    if self.process is previous:
                        self.process = None
                message = self._process_error(previous)
                self._fail_pending(message)
                self._fail_active_turns(message)
            if not self.command:
                raise ProviderError("Codex não foi encontrado no PATH.")
            self._stderr_lines.clear()
            startup_info: dict[str, Any] = {}
            if os.name == "nt":
                startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                [self.command, "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **startup_info,
            )
            with self._state_lock:
                self.process = process
            self._reader = threading.Thread(
                target=self._read_loop, args=(process,), daemon=True
            )
            self._reader.start()
            self._stderr_reader = threading.Thread(
                target=self._read_stderr, args=(process,), daemon=True
            )
            self._stderr_reader.start()
            try:
                self._rpc(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "vr_norte_studio",
                            "title": "VR Norte Studio",
                            "version": APP_VERSION,
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                    timeout=self.start_timeout_seconds,
                )
                self._notify("initialized", {})
                self._has_started_once = True
            except Exception:
                self._stop_process(process)
                raise

    def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if not process or process.poll() is not None or not process.stdin:
            raise ProviderError("Codex App Server não está ativo.")
        line = json.dumps(message, ensure_ascii=False)
        try:
            with self._write_lock:
                process.stdin.write(line + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ProviderError(self._process_error(process)) from exc

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        effective_timeout = (
            self.rpc_timeout_seconds if timeout is None else timeout
        )
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._state_lock:
            self._request_id += 1
            request_id = self._request_id
            self._pending[request_id] = response_queue
        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        try:
            self._send(message)
        except Exception:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        try:
            response = response_queue.get(timeout=effective_timeout)
        except queue.Empty as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            process = self.process
            if process and process.poll() is not None:
                raise ProviderError(self._process_error(process)) from exc
            detail = "\n".join(self._stderr_lines)
            requester = f" (conversa {conversation_id})" if conversation_id else ""
            self._stop_process(process)
            raise ProviderError(
                f"Timeout do Codex em {method}{requester}."
                + (f"\n{detail}" if detail else "")
            ) from exc
        if "error" in response:
            error = response["error"]
            raise ProviderError(str(error.get("message") if isinstance(error, dict) else error))
        return response.get("result") or {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _read_loop(self, process: subprocess.Popen[str]) -> None:
        stdout = process.stdout
        try:
            if stdout is None:
                raise ProviderError("Codex App Server iniciou sem canal de saída.")
            for line in stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                response_id = message.get("id")
                target = None
                if "result" in message or "error" in message:
                    with self._state_lock:
                        target = self._pending.pop(response_id, None)
                if target:
                    target.put(message)
                    continue
                self._handle_server_message(message)
        finally:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
            # Keep teardown ordered with process replacement.  Without this,
            # an old reader could identify itself as current, be pre-empted by
            # a restart, and then drain requests belonging to the new process.
            with self._start_lock:
                with self._state_lock:
                    is_current = self.process is process
                    if is_current:
                        self.process = None
                if is_current:
                    message = self._process_error(process)
                    self._fail_pending(message)
                    self._fail_active_turns(message)

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        stderr = process.stderr
        if stderr is None:
            return
        for line in stderr:
            self._stderr_lines.append(line.rstrip())

    def _process_error(self, process: subprocess.Popen[str] | None) -> str:
        code = process.poll() if process else None
        detail = "\n".join(self._stderr_lines)
        message = (
            f"Codex App Server encerrou com código {code}."
            if code is not None
            else "Codex App Server foi encerrado."
        )
        return message + (f"\n{detail}" if detail else "")

    def _fail_pending(self, message: str) -> None:
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        response = {"error": {"message": message}}
        for target in pending:
            try:
                target.put_nowait(response)
            except queue.Full:
                pass

    def _fail_active_turns(self, message: str) -> None:
        with self._state_lock:
            active = [
                (conversation_id, self._callbacks.get(conversation_id))
                for conversation_id in tuple(self._active_turns)
            ]
            for conversation_id, _callback in active:
                turn_id = self._active_turns.pop(conversation_id, "")
                if turn_id:
                    for native_id, local_id in self._native_to_local.items():
                        if local_id == conversation_id:
                            self._completed_turn_ids.setdefault(native_id, set()).add(turn_id)
                self._assistant_item_keys.pop(conversation_id, None)
                self._clear_assistant_item_phases(conversation_id)
        for conversation_id, callback in active:
            if callback is None:
                continue
            for event in (
                RuntimeEvent(
                    conversation_id,
                    "error",
                    message,
                    {"provider": "codex", "fatal": True},
                ),
                RuntimeEvent(
                    conversation_id,
                    "turn_completed",
                    payload={"provider": "codex", "fatal": True},
                ),
            ):
                try:
                    callback(event)
                except Exception:
                    continue

    def _stop_process(self, process: subprocess.Popen[str] | None = None) -> None:
        with self._start_lock:
            with self._state_lock:
                target = process or self.process
                owns_current_state = target is self.process
                if owns_current_state:
                    self.process = None
            if target and target.poll() is None:
                target.terminate()
                try:
                    target.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    target.kill()
                    target.wait(timeout=5)
            if owns_current_state:
                message = "Codex App Server foi reiniciado."
                self._fail_pending(message)
                self._fail_active_turns(message)

    def _handle_server_message(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", "event"))
        params = message.get("params") or {}
        native_id = str(params.get("threadId") or "")
        if not native_id and isinstance(params.get("thread"), dict):
            native_id = str(params["thread"].get("id") or "")
        with self._state_lock:
            conversation_id = self._native_to_local.get(native_id, "")
            callback = self._callbacks.get(conversation_id)
            turn = params.get("turn") or {}
            turn_id = str(
                params.get("turnId")
                or (turn.get("id") if isinstance(turn, dict) else "") or ""
            )
            active_turn = self._active_turns.get(conversation_id, "")
            item = params.get("item") or {}
            item_id = str(params.get("itemId") or params.get("item_id")
                          or (item.get("id") if isinstance(item, dict) else "") or "")
            if not turn_id and item_id:
                turn_id = self._item_turn_ids.get((native_id, item_id), "")
            turn_scoped = method.startswith(("item/", "turn/")) or method == "error"
            if (callback and turn_scoped and not turn_id
                    and (active_turn or self._completed_turn_ids.get(native_id))):
                # A current callback is not proof that an anonymous event came
                # from the current turn. Only a previously bound item can help.
                return
            if turn_id and (
                turn_id in self._completed_turn_ids.get(native_id, set())
                or (active_turn and turn_id != active_turn)
            ):
                return
            if callback and turn_id:
                self._active_turns[conversation_id] = turn_id
                if item_id:
                    self._item_turn_ids[(native_id, item_id)] = turn_id
            if callback and method == "turn/completed":
                if turn_id or active_turn:
                    self._completed_turn_ids.setdefault(native_id, set()).add(
                        turn_id or active_turn
                    )
                self._active_turns.pop(conversation_id, None)
                self._callbacks.pop(conversation_id, None)
                self._assistant_item_keys.pop(conversation_id, None)
                self._clear_assistant_item_phases(conversation_id)
        if not callback:
            return
        if method == "thread/tokenUsage/updated":
            callback(
                RuntimeEvent(
                    conversation_id,
                    "token_usage",
                    "Uso de contexto atualizado",
                    params,
                )
            )
        elif method == "thread/settings/updated":
            callback(
                RuntimeEvent(
                    conversation_id,
                    "settings_updated",
                    "Configuração efetiva atualizada",
                    params,
                )
            )
        elif method == "item/agentMessage/delta":
            delta = str(params.get("delta", ""))
            item_id = str(params.get("itemId") or params.get("item_id") or "")
            item_key = f"{method}:{item_id}" if item_id else method
            with self._state_lock:
                previous_item_key = self._assistant_item_keys.get(
                    conversation_id, ""
                )
                phase = self._assistant_item_phases.get(
                    (conversation_id, item_id), ""
                )
                previous_item_id = previous_item_key.partition(":")[2]
                previous_phase = self._assistant_item_phases.get(
                    (conversation_id, previous_item_id), ""
                )
                self._assistant_item_keys[conversation_id] = item_key
            # Codex can emit commentary and the final answer as distinct
            # agent-message items. Keep a readable boundary between them.
            phases_are_distinct = bool(
                phase and previous_phase and phase != previous_phase
            )
            if (
                previous_item_key
                and previous_item_key != item_key
                and delta
                and not phases_are_distinct
            ):
                leading_newlines = len(delta) - len(delta.lstrip("\r\n"))
                delta = "\n" * max(0, 2 - leading_newlines) + delta
            payload = {"method": method, **params}
            if phase:
                payload["phase"] = phase
            callback(
                RuntimeEvent(
                    conversation_id,
                    "assistant_delta",
                    delta,
                    payload,
                )
            )
        elif method == "item/plan/delta":
            callback(
                RuntimeEvent(
                    conversation_id,
                    "reasoning_delta",
                    str(params.get("delta", "")),
                    {"method": method, **params},
                )
            )
        elif method == "item/reasoning/summaryTextDelta":
            callback(
                RuntimeEvent(
                    conversation_id,
                    "reasoning_delta",
                    str(params.get("delta", "")),
                    params,
                )
            )
        elif method == "turn/started":
            turn = params.get("turn") or {}
            with self._state_lock:
                self._assistant_item_keys.pop(conversation_id, None)
                self._clear_assistant_item_phases(conversation_id)
            callback(RuntimeEvent(conversation_id, "turn_started", payload=params))
        elif method == "turn/completed":
            callback(RuntimeEvent(conversation_id, "turn_completed", payload=params))
        elif method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
            "mcpServer/elicitation/request",
        }:
            callback(
                RuntimeEvent(
                    conversation_id,
                    "approval_requested",
                    str(params.get("reason") or params.get("command") or method),
                    {"request_id": str(message.get("id")), "method": method, **params},
                )
            )
        elif method == "item/tool/call":
            callback(
                RuntimeEvent(
                    conversation_id,
                    "dynamic_tool_requested",
                    str(params.get("tool") or "tool"),
                    {"request_id": str(message.get("id")), "method": method, **params},
                )
            )
        elif method == "item/fileChange/patchUpdated":
            item_id = str(params.get("itemId") or params.get("item_id") or "")
            changes = list(params.get("changes") or [])
            callback(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    f"Alterações de arquivo: {len(changes)}",
                    {
                        "lifecycle": method,
                        **params,
                        "item": {
                            "id": item_id,
                            "type": "fileChange",
                            "status": "inProgress",
                            "changes": changes,
                        },
                    },
                )
            )
        elif method == "error":
            error = params.get("error") or {}
            callback(RuntimeEvent(conversation_id, "error", str(error.get("message", error)), params))
        elif method in {"item/started", "item/completed"}:
            item = params.get("item") or {}
            item_id = str(item.get("id") or "")
            if str(item.get("type") or "") == "agentMessage" and item_id:
                phase = str(item.get("phase") or "")
                if phase:
                    with self._state_lock:
                        self._assistant_item_phases[
                            (conversation_id, item_id)
                        ] = phase
            callback(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    _item_summary(item),
                    {"lifecycle": method, **params},
                )
            )
        else:
            callback(RuntimeEvent(conversation_id, "runtime_event", method, params))

    def _clear_assistant_item_phases(self, conversation_id: str) -> None:
        stale = [
            key for key in self._assistant_item_phases if key[0] == conversation_id
        ]
        for key in stale:
            self._assistant_item_phases.pop(key, None)

    def list_models(self) -> list[dict[str, Any]]:
        self._ensure_started()
        return list(
            self._rpc(
                "model/list", {"limit": 100, "includeHidden": False}, timeout=10
            ).get("data", [])
        )

    def list_collaboration_modes(self) -> list[dict[str, Any]]:
        self._ensure_started()
        try:
            data = list(self._rpc("collaborationMode/list", {}).get("data", []))
        except ProviderError:
            return super().list_collaboration_modes()
        result = []
        for item in data:
            mode = str(item.get("mode") or "")
            if mode in {"default", "plan"}:
                result.append({**item, "name": "Build" if mode == "default" else "Plan"})
        return result or super().list_collaboration_modes()

    def _load_mcp_server_configs(self) -> None:
        try:
            config_result = self._rpc("config/read", {"includeLayers": False})
            effective = config_result.get("config") or {}
            raw_configs = effective.get("mcp_servers") or {}
            self._mcp_server_configs = {
                str(name): dict(value)
                for name, value in raw_configs.items()
                if isinstance(value, dict)
            }
            self._known_mcp_servers = list(
                dict.fromkeys([*self._known_mcp_servers, *self._mcp_server_configs])
            )
        except ProviderError:
            self._mcp_server_configs = {}

    def list_mcp_tools(self) -> list[dict[str, Any]]:
        self._ensure_started()
        self._load_mcp_server_configs()
        result = self._rpc(
            "mcpServerStatus/list",
            {"limit": 100, "detail": "toolsAndAuthOnly"},
            timeout=10,
        )
        flattened: list[dict[str, Any]] = []
        self._known_mcp_servers = []
        for server in result.get("data", []):
            server_name = str(server.get("name") or "")
            if not server_name:
                continue
            self._known_mcp_servers.append(server_name)
            raw_tools = server.get("tools") or {}
            iterable = raw_tools.values() if isinstance(raw_tools, dict) else raw_tools
            server_info = server.get("serverInfo") or {}
            server_description = str(server_info.get("description") or "")
            tool_count = 0
            for tool in iterable:
                tool_count += 1
                flattened.append(
                    {
                        "server": server_name,
                        "tool": str(tool.get("name") or ""),
                        "description": str(tool.get("description") or ""),
                        "authStatus": server.get("authStatus"),
                        "serverDescription": server_description,
                        "configurable": server_name in self._mcp_server_configs,
                    }
                )
            if not tool_count:
                flattened.append(
                    {
                        "server": server_name,
                        "tool": "",
                        "description": "Nenhuma tool anunciada pelo servidor.",
                        "authStatus": server.get("authStatus"),
                        "serverDescription": server_description,
                        "configurable": server_name in self._mcp_server_configs,
                    }
                )
        return flattened

    def list_skills(
        self, workspace: Path, force_reload: bool = False
    ) -> dict[str, list[Any]]:
        self._ensure_started()
        resolved = str(workspace.resolve())
        result = self._rpc(
            "skills/list",
            {"cwds": [resolved], "forceReload": bool(force_reload)},
            timeout=10,
        )
        skills: list[dict[str, Any]] = []
        errors: list[str] = []
        for group in result.get("data", []):
            if not isinstance(group, dict):
                continue
            for error in group.get("errors", []):
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("error") or error)
                else:
                    message = str(error)
                if message:
                    errors.append(message)
            for item in group.get("skills", []):
                if not isinstance(item, dict) or item.get("enabled") is False:
                    continue
                name = str(item.get("name") or "").strip()
                path = str(item.get("path") or item.get("skillPath") or "").strip()
                if not name or not path:
                    continue
                interface = item.get("interface") or {}
                skills.append(
                    {
                        "name": name,
                        "path": path,
                        "displayName": str(interface.get("displayName") or name),
                        "description": str(
                            interface.get("shortDescription")
                            or item.get("description")
                            or ""
                        ),
                        "scope": str(item.get("scope") or "codex"),
                    }
                )
        return {"skills": skills, "errors": errors}

    def start_conversation(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        self._ensure_started()
        self._load_mcp_server_configs()
        options = options or ConversationOptions(model=model, effort=effort)
        preset = approval_preset(options.approval_profile)
        params: dict[str, Any] = {
            "model": options.model or model or None,
            "cwd": str(workspace),
            "approvalPolicy": preset.approval_policy,
            "approvalsReviewer": preset.reviewer,
            "sandbox": preset.sandbox,
            "serviceName": "vr_norte_studio",
        }
        if options.service_tier:
            params["serviceTier"] = options.service_tier
        if options.dynamic_tools:
            params["dynamicTools"] = list(options.dynamic_tools)
        config = mcp_thread_config(
            list(options.mcp_tools), self._known_mcp_servers, self._mcp_server_configs
        )
        if config:
            params["config"] = config
        result = self._rpc(
            "thread/start",
            params,
            conversation_id=conversation_id,
        )
        native_id = str((result.get("thread") or {}).get("id", ""))
        if not native_id:
            raise ProviderError("Codex não retornou um ID de thread.")
        with self._state_lock:
            self._native_to_local[native_id] = conversation_id
        return native_id

    def resume_conversation(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        self._ensure_started()
        self._load_mcp_server_configs()
        options = options or ConversationOptions(model=model, effort=effort)
        preset = approval_preset(options.approval_profile)
        params: dict[str, Any] = {
            "threadId": native_id,
            "model": options.model or model or None,
            "cwd": str(workspace),
            "approvalPolicy": preset.approval_policy,
            "approvalsReviewer": preset.reviewer,
            "sandbox": preset.sandbox,
        }
        if options.service_tier:
            params["serviceTier"] = options.service_tier
        config = mcp_thread_config(
            list(options.mcp_tools), self._known_mcp_servers, self._mcp_server_configs
        )
        if config:
            params["config"] = config
        result = self._rpc(
            "thread/resume",
            params,
            conversation_id=conversation_id,
        )
        resumed_id = str((result.get("thread") or {}).get("id", native_id))
        with self._state_lock:
            self._native_to_local[resumed_id] = conversation_id
        return resumed_id

    @staticmethod
    def _is_archived_session_error(error: Exception) -> bool:
        message = str(error).casefold()
        return "archiv" in message and (
            "unarchive" in message
            or "desarquiv" in message
            or "is archived" in message
        )

    def _reactivate_archived_conversation(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions,
    ) -> str:
        try:
            self.unarchive_thread(native_id)
            return self.resume_conversation(
                conversation_id,
                native_id,
                model,
                effort,
                workspace,
                options,
            )
        except ProviderError as exc:
            raise ProviderError(
                "A sessão do Codex foi arquivada e não pôde ser reativada "
                f"automaticamente: {exc}"
            ) from exc

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
    ) -> None:
        process = self.process
        reconnecting = bool(
            self._has_started_once
            and (process is None or process.poll() is not None)
        )
        if reconnecting:
            callback(
                RuntimeEvent(
                    conversation_id,
                    "provider_reconnecting",
                    "Reconectando ao Codex…",
                    {"provider": "codex"},
                )
            )
        self._ensure_started()
        if reconnecting:
            callback(
                RuntimeEvent(
                    conversation_id,
                    "provider_reconnected",
                    "Codex reconectado",
                    {"provider": "codex"},
                )
            )
        options = options or ConversationOptions(model=model, effort=effort)
        with self._state_lock:
            native_known = native_id in self._native_to_local
        if not native_known:
            try:
                native_id = self.resume_conversation(
                    conversation_id, native_id, model, effort, workspace, options
                )
            except ProviderError as exc:
                if not self._is_archived_session_error(exc):
                    raise
                native_id = self._reactivate_archived_conversation(
                    conversation_id,
                    native_id,
                    model,
                    effort,
                    workspace,
                    options,
                )
        with self._state_lock:
            self._callbacks[conversation_id] = callback
            self._native_to_local[native_id] = conversation_id
            self._assistant_item_keys.pop(conversation_id, None)
            self._clear_assistant_item_phases(conversation_id)
            # Keep a pending marker so a server crash between the RPC response
            # and turn/started still terminates this caller instead of timing out.
            self._active_turns[conversation_id] = ""
        preset = approval_preset(options.approval_profile)
        sandbox_policy: dict[str, Any] = {"type": preset.sandbox_policy_type}
        if preset.sandbox_policy_type == "workspaceWrite":
            sandbox_policy.update(
                {"writableRoots": [str(workspace)], "networkAccess": True}
            )
        selected_model = options.model or model
        turn_input: list[dict[str, Any]] = []
        valid_skills = [
            item
            for item in (skills or [])
            if str(item.get("name") or "") and str(item.get("path") or "")
        ]
        skill_prefix = " ".join(f"${item['name']}" for item in valid_skills)
        turn_input.append(
            {
                "type": "text",
                "text": f"{skill_prefix} {message}".strip() if skill_prefix else message,
            }
        )
        turn_input.extend(
            {
                "type": "skill",
                "name": str(item["name"]),
                "path": str(item["path"]),
            }
            for item in valid_skills
        )
        turn_input.extend(
            {
                "type": "localImage",
                "path": str(Path(path).resolve()),
            }
            for path in (image_paths or [])
            if Path(path).is_file()
        )
        params: dict[str, Any] = {
            "threadId": native_id,
            "input": turn_input,
            "cwd": str(workspace),
            "model": selected_model or None,
            "effort": normalize_effort(options.effort or effort),
            "approvalPolicy": preset.approval_policy,
            "approvalsReviewer": preset.reviewer,
            "sandboxPolicy": sandbox_policy,
        }
        if selected_model and options.collaboration_mode == "plan":
            params["collaborationMode"] = {
                "mode": "plan",
                "settings": {
                    "model": selected_model,
                    "reasoning_effort": normalize_effort(options.effort or effort),
                    "developer_instructions": None,
                },
            }
        if options.service_tier:
            params["serviceTier"] = options.service_tier
        try:
            try:
                result = self._rpc("turn/start", params, conversation_id=conversation_id)
            except ProviderError as exc:
                if not self._is_archived_session_error(exc):
                    raise
                native_id = self._reactivate_archived_conversation(
                    conversation_id,
                    native_id,
                    model,
                    effort,
                    workspace,
                    options,
                )
                params["threadId"] = native_id
                with self._state_lock:
                    self._callbacks[conversation_id] = callback
                    self._native_to_local[native_id] = conversation_id
                result = self._rpc("turn/start", params, conversation_id=conversation_id)
            turn_id = str((result.get("turn") or {}).get("id") or "")
            with self._state_lock:
                # A fast turn can complete while the RPC response is in flight.
                if (
                    turn_id and self._callbacks.get(conversation_id) is callback
                    and self._active_turns.get(conversation_id) == ""
                    and turn_id not in self._completed_turn_ids.get(native_id, set())
                ):
                    self._active_turns[conversation_id] = turn_id
        except Exception:
            with self._state_lock:
                self._active_turns.pop(conversation_id, None)
                self._assistant_item_keys.pop(conversation_id, None)
                self._clear_assistant_item_phases(conversation_id)
            raise

    def interrupt(self, conversation_id: str) -> None:
        with self._state_lock:
            native_id = next(
                (
                    native
                    for native, local in self._native_to_local.items()
                    if local == conversation_id
                ),
                "",
            )
            turn_id = self._active_turns.get(conversation_id, "")
        if native_id and turn_id:
            self._rpc("turn/interrupt", {"threadId": native_id, "turnId": turn_id})

    def approve_action(
        self,
        request_id: str,
        approved: bool,
        session: bool = False,
        request: dict[str, Any] | None = None,
    ) -> None:
        request = request or {}
        method = str(request.get("method") or "")
        if method == "item/permissions/requestApproval":
            requested = request.get("permissions") or request.get("requestedPermissions") or []
            result: dict[str, Any] = {
                "permissions": requested if approved else {},
                "scope": "session" if approved and session else "turn",
            }
        elif method == "mcpServer/elicitation/request":
            action = str(request.get("_decision") or ("accept" if approved else "decline"))
            if action not in {"accept", "decline", "cancel"}:
                action = "decline"
            result = {
                "action": action,
                "content": request.get("content") if action == "accept" else None,
            }
        else:
            decision = (
                "acceptForSession" if approved and session else "accept" if approved else "decline"
            )
            result = {"decision": decision}
        self._send({"id": int(request_id), "result": result})

    def respond_dynamic_tool(
        self,
        request_id: str,
        content_items: list[dict[str, Any]],
        success: bool = True,
    ) -> None:
        self._send(
            {
                "id": int(request_id),
                "result": {"contentItems": content_items, "success": success},
            }
        )

    def update_settings(
        self,
        conversation_id: str,
        native_id: str,
        workspace: Path,
        options: ConversationOptions,
    ) -> None:
        if not native_id:
            return
        self._ensure_started()
        preset = approval_preset(options.approval_profile)
        sandbox_policy: dict[str, Any] = {"type": preset.sandbox_policy_type}
        if preset.sandbox_policy_type == "workspaceWrite":
            sandbox_policy.update(
                {"writableRoots": [str(workspace)], "networkAccess": True}
            )
        selected_model = options.model
        params: dict[str, Any] = {
            "threadId": native_id,
            "model": selected_model or None,
            "effort": normalize_effort(options.effort),
            "serviceTier": options.service_tier or None,
            "approvalPolicy": preset.approval_policy,
            "approvalsReviewer": preset.reviewer,
            "sandboxPolicy": sandbox_policy,
        }
        if selected_model and options.collaboration_mode == "plan":
            params["collaborationMode"] = {
                "mode": "plan",
                "settings": {
                    "model": selected_model,
                    "reasoning_effort": normalize_effort(options.effort),
                    "developer_instructions": None,
                },
            }
        try:
            self._rpc("thread/settings/update", params)
        except ProviderError as exc:
            message = str(exc).casefold()
            if "method" not in message and "not found" not in message and "unknown" not in message:
                raise

    def archive_thread(self, native_id: str) -> None:
        if native_id:
            self._ensure_started()
            self._rpc("thread/archive", {"threadId": native_id})

    def unarchive_thread(self, native_id: str) -> None:
        if native_id:
            self._ensure_started()
            self._rpc("thread/unarchive", {"threadId": native_id})

    def delete_thread(self, native_id: str) -> None:
        if native_id:
            self._ensure_started()
            self._rpc("thread/delete", {"threadId": native_id})

    def fork_thread(
        self,
        conversation_id: str,
        native_id: str,
        last_turn_id: str,
        workspace: Path,
        options: ConversationOptions,
    ) -> str:
        if not native_id or not last_turn_id:
            return ""
        self._ensure_started()
        preset = approval_preset(options.approval_profile)
        params: dict[str, Any] = {
            "threadId": native_id,
            "lastTurnId": last_turn_id,
            "cwd": str(workspace),
            "model": options.model or None,
            "approvalPolicy": preset.approval_policy,
            "approvalsReviewer": preset.reviewer,
            "sandbox": preset.sandbox,
            "serviceTier": options.service_tier or None,
        }
        result = self._rpc("thread/fork", params)
        forked_id = str((result.get("thread") or {}).get("id") or "")
        if forked_id:
            with self._state_lock:
                self._native_to_local[forked_id] = conversation_id
        return forked_id

    def close(self) -> None:
        self._stop_process()

    def release_conversation(
        self, conversation_id: str, native_id: str, *, delete_native: bool = False
    ) -> None:
        try:
            if delete_native and native_id:
                self.delete_thread(native_id)
        finally:
            with self._state_lock:
                self._callbacks.pop(conversation_id, None)
                self._active_turns.pop(conversation_id, None)
                self._assistant_item_keys.pop(conversation_id, None)
                self._clear_assistant_item_phases(conversation_id)
                if native_id:
                    self._native_to_local.pop(native_id, None)
                    self._completed_turn_ids.pop(native_id, None)
                    for key in tuple(self._item_turn_ids):
                        if key[0] == native_id:
                            self._item_turn_ids.pop(key, None)


class ClaudeProvider(AgentProvider):
    name = "claude"

    def __init__(self, knowledge_root: Path | None = None):
        super().__init__(knowledge_root)
        self.command = (
            shutil.which("claude.exe")
            or shutil.which("claude.cmd")
            or shutil.which("claude")
        )
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._new_sessions: set[str] = set()
        self._workspaces: dict[str, Path] = {}
        # Each in-flight Popen owns a unique reservation.  A close, release or
        # interrupt can revoke that reservation while Popen is still blocked;
        # the process is only published when the same token remains current.
        self._starting: dict[str, tuple[object, str, bool]] = {}
        self._state_lock = threading.RLock()

    def available(self) -> bool:
        return bool(self.command)

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {"id": "default", "model": "default", "displayName": "Claude padrão", "isDefault": True},
            {"id": "fable", "model": "fable", "displayName": "Claude Fable 5"},
            {"id": "sonnet", "model": "sonnet", "displayName": "Claude Sonnet"},
            {"id": "opus", "model": "opus", "displayName": "Claude Opus"},
            {"id": "haiku", "model": "haiku", "displayName": "Claude Haiku"},
        ]

    def start_conversation(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        session_id = str(uuid.uuid4())
        with self._state_lock:
            self._new_sessions.add(session_id)
        return session_id

    def resume_conversation(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        return native_id

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
    ) -> None:
        if not self.command:
            raise ProviderError("Claude não foi encontrado no PATH.")
        options = options or ConversationOptions(model=model, effort=effort)
        with self._state_lock:
            self._workspaces[conversation_id] = Path(workspace).resolve()
        preset = approval_preset(options.approval_profile)
        readable_roots = [workspace.resolve()]
        image_roots = {
            Path(path).resolve().parent
            for path in (image_paths or [])
            if Path(path).is_file()
        }
        for root in image_roots:
            if root not in readable_roots:
                readable_roots.append(root)
        if (
            options.vr_enabled
            and self.knowledge_root
            and self.knowledge_root not in readable_roots
        ):
            readable_roots.append(self.knowledge_root)
        allowed_tools = [
            f"{tool}({root}/**)"
            for root in readable_roots
            for tool in ("Read", "Glob", "Grep")
        ]
        if preset.sandbox != "read-only":
            allowed_tools.extend(
                [f"Edit({workspace}/**)", f"Write({workspace}/**)"]
            )
        command = [
            self.command,
            "-p",
            message,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if options.vr_enabled:
            command.extend(["--permission-mode", "dontAsk"])
            for root in readable_roots:
                command.extend(["--add-dir", str(root)])
            command.extend(
                [
                    "--allowedTools",
                    ",".join(allowed_tools),
                    "--disallowedTools",
                    "Bash",
                ]
            )
        else:
            for root in image_roots:
                command.extend(["--add-dir", str(root)])
            permission_mode = {
                "workspace-write": "acceptEdits",
                "danger-full-access": "bypassPermissions",
            }.get(preset.sandbox)
            if permission_mode:
                command.extend(["--permission-mode", permission_mode])
        if model and model != "default":
            command.extend(["--model", model])
        command.extend(["--effort", normalize_effort(effort, provider="claude")])
        startup_token = object()
        with self._state_lock:
            if conversation_id in self._active or conversation_id in self._starting:
                raise ProviderError("Já existe um turno Claude em execução.")
            is_new_session = native_id in self._new_sessions
            if is_new_session:
                self._new_sessions.discard(native_id)
            self._starting[conversation_id] = (
                startup_token,
                native_id,
                is_new_session,
            )
        if is_new_session:
            command.extend(["--session-id", native_id])
        elif native_id:
            command.extend(["--resume", native_id])
        startup_info: dict[str, Any] = {}
        if os.name == "nt":
            startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **startup_info,
            )
        except Exception:
            with self._state_lock:
                reservation = self._starting.get(conversation_id)
                owns_reservation = bool(
                    reservation and reservation[0] is startup_token
                )
                if owns_reservation:
                    self._starting.pop(conversation_id, None)
                if owns_reservation and is_new_session:
                    self._new_sessions.add(native_id)
            raise
        with self._state_lock:
            reservation = self._starting.get(conversation_id)
            accepted = bool(reservation and reservation[0] is startup_token)
            if accepted:
                self._starting.pop(conversation_id, None)
                self._active[conversation_id] = process
        if not accepted:
            if process.poll() is None:
                process.terminate()
            raise ProviderError("A inicialização do turno Claude foi cancelada.")
        threading.Thread(
            target=self._consume,
            args=(conversation_id, process, callback),
            daemon=True,
        ).start()

    def _consume(
        self, conversation_id: str, process: subprocess.Popen[str], callback: EventCallback
    ) -> None:
        callback(RuntimeEvent(conversation_id, "turn_started"))
        final_text = ""
        stderr_lines: deque[str] = deque(maxlen=100)

        def read_stderr() -> None:
            if not process.stderr:
                return
            for line in process.stderr:
                cleaned = line.strip()
                if cleaned:
                    stderr_lines.append(cleaned)

        stderr_reader = threading.Thread(target=read_stderr, daemon=True)
        stderr_reader.start()
        stdout = process.stdout
        if stdout is None:
            with self._state_lock:
                self._active.pop(conversation_id, None)
            callback(RuntimeEvent(conversation_id, "error", "Claude iniciou sem canal de saída."))
            callback(RuntimeEvent(conversation_id, "turn_completed"))
            return
        for line in stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = payload.get("type", "")
            if kind == "stream_event":
                event = payload.get("event") or {}
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "thinking_delta":
                        thinking = str(delta.get("thinking") or "")
                        if thinking:
                            callback(RuntimeEvent(conversation_id, "reasoning_delta", thinking, payload))
                        continue
                    text = str(delta.get("text") or "")
                    if text:
                        final_text += text
                        callback(RuntimeEvent(conversation_id, "assistant_delta", text, payload))
            elif kind == "assistant":
                message = payload.get("message") or {}
                for block in message.get("content", []):
                    if block.get("type") == "tool_use":
                        callback(
                            RuntimeEvent(
                                conversation_id,
                                "tool_event",
                                f"{block.get('name', 'ferramenta')}",
                                block,
                            )
                        )
            elif kind == "result":
                result_text = str(payload.get("result") or "")
                if result_text and not final_text:
                    final_text = result_text
                    callback(RuntimeEvent(conversation_id, "assistant_delta", result_text, payload))
                token_usage = _claude_token_usage(payload)
                if token_usage:
                    callback(
                        RuntimeEvent(
                            conversation_id,
                            "token_usage",
                            "Uso de contexto atualizado",
                            token_usage,
                        )
                    )
                if payload.get("is_error"):
                    callback(RuntimeEvent(conversation_id, "error", result_text, payload))
        exit_code = process.wait()
        stderr_reader.join(timeout=1)
        error = "\n".join(stderr_lines).strip()
        if exit_code or not final_text.strip():
            callback(
                RuntimeEvent(
                    conversation_id,
                    "error",
                    error
                    or (
                        f"Claude encerrou com código {exit_code}."
                        if exit_code
                        else "Claude encerrou sem produzir uma resposta."
                    ),
                )
            )
        with self._state_lock:
            if self._active.get(conversation_id) is process:
                self._active.pop(conversation_id, None)
        callback(RuntimeEvent(conversation_id, "turn_completed", payload={"exit_code": exit_code}))

    def interrupt(self, conversation_id: str) -> None:
        with self._state_lock:
            process = self._active.get(conversation_id)
            reservation = self._starting.pop(conversation_id, None)
            if reservation and reservation[2] and reservation[1]:
                self._new_sessions.add(reservation[1])
        if process and process.poll() is None:
            process.terminate()

    def approve_action(
        self,
        request_id: str,
        approved: bool,
        session: bool = False,
        request: dict[str, Any] | None = None,
    ) -> None:
        raise ProviderError("Aprovação interativa não é exposta pelo modo headless do Claude.")

    def close(self) -> None:
        with self._state_lock:
            processes = list(self._active.values())
            self._active.clear()
            self._starting.clear()
            self._new_sessions.clear()
        for process in processes:
            if process.poll() is None:
                process.terminate()

    def release_conversation(
        self, conversation_id: str, native_id: str, *, delete_native: bool = False
    ) -> None:
        with self._state_lock:
            process = self._active.pop(conversation_id, None)
            self._starting.pop(conversation_id, None)
            self._new_sessions.discard(native_id)
            workspace = self._workspaces.pop(conversation_id, None)
        if process and process.poll() is None:
            process.terminate()
        if workspace is not None:
            self._cleanup_session_rollout(native_id, workspace)

    @staticmethod
    def _cleanup_session_rollout(native_id: str, workspace: Path) -> None:
        try:
            native = str(native_id or "")
            if not UUID4_PATTERN.fullmatch(native):
                return
            projects_root = Path.home() / ".claude" / "projects"
            if not projects_root.is_dir():
                return
            expected = f"{native}.jsonl"
            encoded_candidates: list[str] = []
            for candidate in (workspace.resolve(), workspace):
                for text in {str(candidate), str(candidate).lower()}:
                    encoded = re.sub(r"[^A-Za-z0-9]", "-", text)
                    if encoded not in encoded_candidates:
                        encoded_candidates.append(encoded)
            for encoded in encoded_candidates:
                session_dir = projects_root / encoded
                if not session_dir.is_dir():
                    continue
                for entry in session_dir.iterdir():
                    if entry.name == expected and entry.is_file():
                        entry.unlink()
        except Exception:
            pass


class OpenCodeProvider(AgentProvider):
    """Headless OpenCode CLI adapter with provider-qualified model IDs."""

    name = "opencode"

    def __init__(self, knowledge_root: Path | None = None):
        super().__init__(knowledge_root)
        self.command = _resolve_opencode_command()
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._starting: dict[str, object] = {}
        self._sessions: dict[str, str] = {}
        self._model_variants: dict[str, set[str]] = {}
        self._rate_limited_until = 0.0
        self._state_lock = threading.RLock()

    def available(self) -> bool:
        return bool(self.command)

    def list_models(self) -> list[dict[str, Any]]:
        return list(self._load_model_catalog())

    def _load_model_catalog(self) -> list[dict[str, Any]]:
        models = self._fetch_model_catalog()
        self._model_variants = {
            str(item["id"]): set(item.get("_opencodeVariants") or [])
            for item in models
        }
        return models

    def _fetch_model_catalog(self) -> list[dict[str, Any]]:
        if not self.command:
            raise ProviderError("OpenCode não foi encontrado no PATH.")
        startup_info: dict[str, Any] = {}
        if os.name == "nt":
            startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                [self.command, "models", "--verbose"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                **startup_info,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderError(f"Falha ao listar modelos OpenCode: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ProviderError(detail or "Falha ao listar modelos OpenCode.")
        models = _parse_opencode_models(result.stdout)
        if not models:
            raise ProviderError("O OpenCode não retornou nenhum modelo disponível.")
        return models

    def start_conversation(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        token = f"new:{uuid.uuid4()}"
        with self._state_lock:
            self._sessions[token] = ""
        return token

    def resume_conversation(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        return native_id

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
    ) -> None:
        if not self.command:
            raise ProviderError("OpenCode não foi encontrado no PATH.")
        options = options or ConversationOptions(model=model, effort=effort)
        with self._state_lock:
            if time.monotonic() < self._rate_limited_until:
                raise ProviderRateLimited("Limite de requisições do OpenCode atingido. Aguarde antes de tentar novamente.")
            resume_id = self._sessions.get(native_id, native_id)
        command = [
            self.command,
            "run",
            "--format",
            "json",
            "--print-logs",
            "--log-level",
            "ERROR",
            "--dir",
            str(workspace),
            "--agent",
            "plan" if options.collaboration_mode == "plan" else "build",
        ]
        if resume_id and not resume_id.startswith("new:"):
            command.extend(["--session", resume_id])
        if model and model != "default":
            command.extend(["--model", model])
        if not self._model_variants:
            try:
                self._load_model_catalog()
            except Exception:
                pass
        normalized_effort = normalize_effort(effort, provider="opencode")
        if normalized_effort in self._model_variants.get(model, set()):
            command.extend(["--variant", normalized_effort])

        startup_token = object()
        with self._state_lock:
            if conversation_id in self._active or conversation_id in self._starting:
                raise ProviderError("Já existe um turno OpenCode em execução.")
            self._starting[conversation_id] = startup_token

        startup_info: dict[str, Any] = {}
        if os.name == "nt":
            startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=_opencode_environment(
                    options.approval_profile,
                    self.knowledge_root if options.vr_enabled else None,
                ),
                **startup_info,
            )
        except Exception:
            with self._state_lock:
                if self._starting.get(conversation_id) is startup_token:
                    self._starting.pop(conversation_id, None)
            raise

        with self._state_lock:
            accepted = self._starting.get(conversation_id) is startup_token
            if accepted:
                self._starting.pop(conversation_id, None)
                self._active[conversation_id] = process
        if not accepted:
            if process.poll() is None:
                process.terminate()
            raise ProviderError("A inicialização do turno OpenCode foi cancelada.")

        try:
            stdin = process.stdin
            if stdin is None:
                raise ProviderError("OpenCode iniciou sem canal de entrada.")
            stdin.write(message)
            stdin.close()
        except Exception:
            with self._state_lock:
                if self._active.get(conversation_id) is process:
                    self._active.pop(conversation_id, None)
            if process.poll() is None:
                process.terminate()
            raise

        threading.Thread(
            target=self._consume,
            args=(conversation_id, native_id, process, callback),
            daemon=True,
        ).start()

    def _consume(
        self,
        conversation_id: str,
        native_id: str,
        process: subprocess.Popen[str],
        callback: EventCallback,
    ) -> None:
        callback(RuntimeEvent(conversation_id, "turn_started"))
        stderr_lines: deque[str] = deque(maxlen=30)
        reported_error = False

        def report_rate_limit() -> None:
            nonlocal reported_error
            with self._state_lock:
                if self._active.get(conversation_id) is not process:
                    return
                self._rate_limited_until = time.monotonic() + 60
                already_reported = reported_error
                reported_error = True
            if not already_reported:
                callback(RuntimeEvent(
                    conversation_id, "error",
                    "Limite de requisições do OpenCode atingido. Aguarde antes de tentar novamente.",
                    {"code": "rate_limit"},
                ))
            if process.poll() is None:
                process.terminate()

        def read_stderr() -> None:
            if not process.stderr:
                return
            for line in process.stderr:
                cleaned = line.strip()
                if cleaned:
                    stderr_lines.append(cleaned)
                    if "rate limit exceeded" in cleaned.casefold():
                        report_rate_limit()
                        return

        stderr_reader = threading.Thread(target=read_stderr, daemon=True)
        stderr_reader.start()
        session_announced = False
        emitted_text = False
        stdout = process.stdout
        if stdout is None:
            with self._state_lock:
                self._active.pop(conversation_id, None)
            callback(RuntimeEvent(conversation_id, "error", "OpenCode iniciou sem canal de saída."))
            callback(RuntimeEvent(conversation_id, "turn_completed"))
            return
        for line in stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            session_id = str(payload.get("sessionID") or "")
            if session_id and not session_announced:
                session_announced = True
                with self._state_lock:
                    if native_id:
                        self._sessions[native_id] = session_id
                callback(
                    RuntimeEvent(
                        conversation_id,
                        "native_session_started",
                        payload={"native_id": session_id},
                    )
                )
            kind = str(payload.get("type") or "")
            part = payload.get("part") or {}
            if kind == "text":
                text = str(part.get("text") or "")
                if text:
                    emitted_text = True
                    callback(
                        RuntimeEvent(
                            conversation_id, "assistant_delta", text, payload
                        )
                    )
            elif kind == "reasoning":
                text = str(part.get("text") or "")
                if text:
                    callback(RuntimeEvent(conversation_id, "reasoning_delta", text, payload))
            elif kind == "tool_use":
                tool = str(part.get("tool") or part.get("name") or "ferramenta")
                callback(RuntimeEvent(conversation_id, "tool_event", tool, payload))
            elif kind in {"step_finish", "step_completed"}:
                token_usage = _opencode_token_usage(payload)
                if token_usage:
                    callback(
                        RuntimeEvent(
                            conversation_id,
                            "token_usage",
                            "Uso de contexto atualizado",
                            token_usage,
                        )
                    )
            elif kind == "error":
                message = _opencode_error_message(payload)
                if "rate limit exceeded" in message.casefold():
                    report_rate_limit()
                elif not reported_error:
                    reported_error = True
                    callback(RuntimeEvent(conversation_id, "error", message, payload))
        exit_code = process.wait()
        stderr_reader.join(timeout=1)
        if (exit_code or not emitted_text) and not reported_error:
            detail = "\n".join(stderr_lines).strip()
            callback(
                RuntimeEvent(
                    conversation_id,
                    "error",
                    detail
                    or (
                        f"OpenCode encerrou com código {exit_code}."
                        if exit_code
                        else "OpenCode encerrou sem produzir uma resposta."
                    ),
                )
            )
        with self._state_lock:
            if self._active.get(conversation_id) is process:
                self._active.pop(conversation_id, None)
        callback(
            RuntimeEvent(
                conversation_id, "turn_completed", payload={"exit_code": exit_code}
            )
        )

    def interrupt(self, conversation_id: str) -> None:
        with self._state_lock:
            process = self._active.get(conversation_id)
            self._starting.pop(conversation_id, None)
        if process and process.poll() is None:
            process.terminate()

    def approve_action(
        self,
        request_id: str,
        approved: bool,
        session: bool = False,
        request: dict[str, Any] | None = None,
    ) -> None:
        raise ProviderError(
            "Aprovação interativa não é exposta pelo modo headless do OpenCode."
        )

    def delete_thread(self, native_id: str) -> None:
        if not native_id or not self.command:
            return
        with self._state_lock:
            resolved = self._sessions.get(native_id, native_id)
        if not resolved or resolved.startswith("new:"):
            return
        startup_info: dict[str, Any] = {}
        if os.name == "nt":
            startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            [self.command, "session", "delete", resolved],
            capture_output=True,
            text=True,
            timeout=10,
            **startup_info,
        )

    def close(self) -> None:
        with self._state_lock:
            processes = list(self._active.values())
            self._active.clear()
            self._starting.clear()
            self._sessions.clear()
        for process in processes:
            if process.poll() is None:
                process.terminate()

    def release_conversation(
        self, conversation_id: str, native_id: str, *, delete_native: bool = False
    ) -> None:
        with self._state_lock:
            process = self._active.pop(conversation_id, None)
            self._starting.pop(conversation_id, None)
            resolved = self._sessions.pop(native_id, native_id)
        if process and process.poll() is None:
            process.terminate()
        if delete_native and resolved:
            self.delete_thread(resolved)


def provider_registry(knowledge_root: Path | None = None) -> dict[str, AgentProvider]:
    from .antigravity import AntigravityProvider

    return {
        "codex": CodexProvider(knowledge_root),
        "claude": ClaudeProvider(knowledge_root),
        "opencode": OpenCodeProvider(knowledge_root),
        "antigravity": AntigravityProvider(knowledge_root),
    }


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
    approval_profile: str, knowledge_root: Path | None = None
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
    shim = shutil.which("codex.cmd") or shutil.which("codex")
    if shim:
        shim_path = Path(shim)
        package_root = shim_path.parent / "node_modules" / "@openai" / "codex"
        if package_root.exists():
            matches = list(
                package_root.glob(
                    "node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe"
                )
            )
            if matches:
                return str(matches[0])
    direct = shutil.which("codex.exe")
    if direct and "WindowsApps" not in direct:
        return direct
    return shim


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

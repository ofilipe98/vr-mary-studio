from __future__ import annotations

import abc
import json
import os
import queue
import shutil
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

from .chat_tools import mcp_thread_config
from .models import ConversationOptions, RuntimeEvent, approval_preset


EventCallback = Callable[[RuntimeEvent], None]


class ProviderError(RuntimeError):
    pass


class AgentProvider(abc.ABC):
    name: str

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

    @abc.abstractmethod
    def close(self) -> None: ...


class CodexProvider(AgentProvider):
    name = "codex"

    def __init__(self):
        self.command = _resolve_codex_command()
        self.process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._request_id = 0
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._callbacks: dict[str, EventCallback] = {}
        self._native_to_local: dict[str, str] = {}
        self._active_turns: dict[str, str] = {}
        self._lock = threading.Lock()
        self._stderr_lines: deque[str] = deque(maxlen=30)
        self._known_mcp_servers: list[str] = []
        self._mcp_server_configs: dict[str, dict[str, Any]] = {}

    def available(self) -> bool:
        return bool(self.command)

    def _ensure_started(self) -> None:
        if self.process and self.process.poll() is None:
            return
        if not self.command:
            raise ProviderError("Codex não foi encontrado no PATH.")
        startup_info: dict[str, Any] = {}
        if os.name == "nt":
            startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(
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
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()
        self._rpc(
            "initialize",
            {
                "clientInfo": {
                    "name": "vr_mary_studio",
                    "title": "VR Mary Studio",
                    "version": "0.3.6",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self._notify("initialized", {})

    def _send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise ProviderError("Codex App Server não está ativo.")
        line = json.dumps(message, ensure_ascii=False)
        with self._lock:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()

    def _rpc(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 45
    ) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._pending[request_id] = response_queue
        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        self._send(message)
        try:
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            self._pending.pop(request_id, None)
            detail = "\n".join(self._stderr_lines)
            if self.process and self.process.poll() is not None:
                raise ProviderError(
                    f"Codex App Server encerrou com código {self.process.returncode}."
                    + (f"\n{detail}" if detail else "")
                ) from exc
            raise ProviderError(
                f"Timeout do Codex em {method}." + (f"\n{detail}" if detail else "")
            ) from exc
        if "error" in response:
            error = response["error"]
            raise ProviderError(str(error.get("message") if isinstance(error, dict) else error))
        return response.get("result") or {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            response_id = message.get("id")
            if response_id in self._pending and ("result" in message or "error" in message):
                self._pending.pop(response_id).put(message)
                continue
            self._handle_server_message(message)

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self._stderr_lines.append(line.rstrip())

    def _handle_server_message(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", "event"))
        params = message.get("params") or {}
        native_id = str(params.get("threadId") or "")
        if not native_id and isinstance(params.get("thread"), dict):
            native_id = str(params["thread"].get("id") or "")
        conversation_id = self._native_to_local.get(native_id, "")
        callback = self._callbacks.get(conversation_id)
        if not callback:
            return
        if method == "item/agentMessage/delta":
            callback(RuntimeEvent(conversation_id, "assistant_delta", str(params.get("delta", "")), params))
        elif method == "item/plan/delta":
            callback(RuntimeEvent(conversation_id, "assistant_delta", str(params.get("delta", "")), params))
        elif method == "turn/started":
            turn = params.get("turn") or {}
            self._active_turns[conversation_id] = str(turn.get("id", ""))
            callback(RuntimeEvent(conversation_id, "turn_started", payload=params))
        elif method == "turn/completed":
            self._active_turns.pop(conversation_id, None)
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
        elif method == "error":
            error = params.get("error") or {}
            callback(RuntimeEvent(conversation_id, "error", str(error.get("message", error)), params))
        elif method in {"item/started", "item/completed"}:
            item = params.get("item") or {}
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

    def list_models(self) -> list[dict[str, Any]]:
        self._ensure_started()
        return list(self._rpc("model/list", {"limit": 100, "includeHidden": False}).get("data", []))

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
            "serviceName": "vr_mary_studio",
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
        )
        native_id = str((result.get("thread") or {}).get("id", ""))
        if not native_id:
            raise ProviderError("Codex não retornou um ID de thread.")
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
        )
        resumed_id = str((result.get("thread") or {}).get("id", native_id))
        self._native_to_local[resumed_id] = conversation_id
        return resumed_id

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
    ) -> None:
        self._ensure_started()
        options = options or ConversationOptions(model=model, effort=effort)
        if native_id not in self._native_to_local:
            native_id = self.resume_conversation(
                conversation_id, native_id, model, effort, workspace, options
            )
        self._callbacks[conversation_id] = callback
        self._native_to_local[native_id] = conversation_id
        preset = approval_preset(options.approval_profile)
        sandbox_policy: dict[str, Any] = {"type": preset.sandbox_policy_type}
        if preset.sandbox_policy_type == "workspaceWrite":
            sandbox_policy.update(
                {"writableRoots": [str(workspace)], "networkAccess": False}
            )
        selected_model = options.model or model
        params: dict[str, Any] = {
            "threadId": native_id,
            "input": [{"type": "text", "text": message}],
            "cwd": str(workspace),
            "model": selected_model or None,
            "effort": normalize_effort(options.effort or effort),
            "approvalPolicy": preset.approval_policy,
            "approvalsReviewer": preset.reviewer,
            "sandboxPolicy": sandbox_policy,
        }
        if selected_model:
            params["collaborationMode"] = {
                "mode": "plan" if options.collaboration_mode == "plan" else "default",
                "settings": {
                    "model": selected_model,
                    "reasoning_effort": normalize_effort(options.effort or effort),
                    "developer_instructions": None,
                },
            }
        if options.service_tier:
            params["serviceTier"] = options.service_tier
        self._rpc("turn/start", params)

    def interrupt(self, conversation_id: str) -> None:
        native_id = next(
            (native for native, local in self._native_to_local.items() if local == conversation_id),
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
            result = {
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
                {"writableRoots": [str(workspace)], "networkAccess": False}
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
        if selected_model:
            params["collaborationMode"] = {
                    "mode": "plan" if options.collaboration_mode == "plan" else "default",
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
            self._native_to_local[forked_id] = conversation_id
        return forked_id

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None


class ClaudeProvider(AgentProvider):
    name = "claude"

    def __init__(self):
        self.command = (
            shutil.which("claude.exe")
            or shutil.which("claude.cmd")
            or shutil.which("claude")
        )
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._new_sessions: set[str] = set()

    def available(self) -> bool:
        return bool(self.command)

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {"id": "default", "model": "default", "displayName": "Claude padrão", "isDefault": True},
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
    ) -> None:
        if not self.command:
            raise ProviderError("Claude não foi encontrado no PATH.")
        if conversation_id in self._active:
            raise ProviderError("Já existe um turno Claude em execução.")
        command = [
            self.command,
            "-p",
            message,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode",
            "dontAsk",
            "--add-dir",
            str(workspace.parent.parent),
            "--allowedTools",
            ",".join(
                [
                    f"Read({workspace.parent.parent}/**)",
                    f"Glob({workspace.parent.parent}/**)",
                    f"Grep({workspace.parent.parent}/**)",
                    f"Edit({workspace}/**)",
                    f"Write({workspace}/**)",
                ]
            ),
            "--disallowedTools",
            "Bash,WebFetch,WebSearch",
        ]
        if model and model != "default":
            command.extend(["--model", model])
        command.extend(["--effort", normalize_effort(effort, provider="claude")])
        if native_id in self._new_sessions:
            command.extend(["--session-id", native_id])
            self._new_sessions.discard(native_id)
        elif native_id:
            command.extend(["--resume", native_id])
        startup_info: dict[str, Any] = {}
        if os.name == "nt":
            startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
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
        self._active[conversation_id] = process
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
        assert process.stdout
        for line in process.stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = payload.get("type", "")
            if kind == "stream_event":
                event = payload.get("event") or {}
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
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
                    callback(RuntimeEvent(conversation_id, "assistant_delta", result_text, payload))
                if payload.get("is_error"):
                    callback(RuntimeEvent(conversation_id, "error", result_text, payload))
        exit_code = process.wait()
        if exit_code and process.stderr:
            error = process.stderr.read().strip()
            if error:
                callback(RuntimeEvent(conversation_id, "error", error))
        self._active.pop(conversation_id, None)
        callback(RuntimeEvent(conversation_id, "turn_completed", payload={"exit_code": exit_code}))

    def interrupt(self, conversation_id: str) -> None:
        process = self._active.get(conversation_id)
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
        for process in self._active.values():
            if process.poll() is None:
                process.terminate()
        self._active.clear()


def provider_registry() -> dict[str, AgentProvider]:
    return {"codex": CodexProvider(), "claude": ClaudeProvider()}


def normalize_effort(effort: str, provider: str = "codex") -> str:
    allowed = (
        {"low", "medium", "high", "xhigh", "max"}
        if provider == "claude"
        else {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
    )
    value = str(effort or "medium").strip().lower()
    return value if value in allowed else "medium"


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

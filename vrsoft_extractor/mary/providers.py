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
        skills: list[dict[str, Any]] | None = None,
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
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._stderr_lines: deque[str] = deque(maxlen=30)
        self._known_mcp_servers: list[str] = []
        self._mcp_server_configs: dict[str, dict[str, Any]] = {}

    def available(self) -> bool:
        return bool(self.command)

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self.process and self.process.poll() is None:
                return
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
                            "name": "vr_mary_studio",
                            "title": "VR Norte Studio",
                            "version": "0.3.11",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                    timeout=10,
                )
                self._notify("initialized", {})
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
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 45
    ) -> dict[str, Any]:
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
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            process = self.process
            if process and process.poll() is not None:
                raise ProviderError(self._process_error(process)) from exc
            detail = "\n".join(self._stderr_lines)
            self._stop_process(process)
            raise ProviderError(
                f"Timeout do Codex em {method}." + (f"\n{detail}" if detail else "")
            ) from exc
        if "error" in response:
            error = response["error"]
            raise ProviderError(str(error.get("message") if isinstance(error, dict) else error))
        return response.get("result") or {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _read_loop(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout
        try:
            for line in process.stdout:
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
            with self._state_lock:
                is_current = self.process is process
                if is_current:
                    self.process = None
            if is_current:
                self._fail_pending(self._process_error(process))

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        assert process.stderr
        for line in process.stderr:
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

    def _stop_process(self, process: subprocess.Popen[str] | None = None) -> None:
        with self._state_lock:
            target = process or self.process
            if target is self.process:
                self.process = None
        if target and target.poll() is None:
            target.terminate()
            try:
                target.wait(timeout=5)
            except subprocess.TimeoutExpired:
                target.kill()
                target.wait(timeout=5)
        self._fail_pending("Codex App Server foi reiniciado.")

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
        if method == "thread/settings/updated":
            callback(
                RuntimeEvent(
                    conversation_id,
                    "settings_updated",
                    "Configuração efetiva atualizada",
                    params,
                )
            )
        elif method == "item/agentMessage/delta":
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
    ) -> None:
        self._ensure_started()
        options = options or ConversationOptions(model=model, effort=effort)
        if native_id not in self._native_to_local:
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
        self._callbacks[conversation_id] = callback
        self._native_to_local[native_id] = conversation_id
        preset = approval_preset(options.approval_profile)
        sandbox_policy: dict[str, Any] = {"type": preset.sandbox_policy_type}
        if preset.sandbox_policy_type == "workspaceWrite":
            sandbox_policy.update(
                {"writableRoots": [str(workspace)], "networkAccess": False}
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
            self._rpc("turn/start", params)
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
            self._callbacks[conversation_id] = callback
            self._native_to_local[native_id] = conversation_id
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
            self._native_to_local[forked_id] = conversation_id
        return forked_id

    def close(self) -> None:
        self._stop_process()


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
        skills: list[dict[str, Any]] | None = None,
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

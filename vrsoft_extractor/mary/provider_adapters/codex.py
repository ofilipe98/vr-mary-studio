from __future__ import annotations
import json
import os
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any
from ... import __version__ as APP_VERSION
from ..chat_tools import mcp_thread_config
from ..provider_cli import resolve_cli
from ..models import ConversationOptions, RuntimeEvent, approval_preset

from dataclasses import asdict
from .tool_normalizer import normalize_codex_event
from .base import (AgentProvider, EventCallback, ProviderError, _item_summary, _seconds_from_env, normalize_effort)

class CodexProvider(AgentProvider):
    name = "codex"

    def __init__(self, knowledge_root: Path | None = None):
        super().__init__(knowledge_root)
        self.command = resolve_cli("codex")
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
        if not self.command:
            self.command = resolve_cli("codex")
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
            if not self.available():
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
                and (conversation_id, item_id) not in self._assistant_item_phases
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
            payload = {
                "lifecycle": method,
                **params,
                "item": {
                    "id": item_id,
                    "type": "fileChange",
                    "status": "inProgress",
                    "changes": changes,
                },
            }
            norm = normalize_codex_event(params, method, conversation_id)
            if norm:
                payload["canonical_event"] = asdict(norm)
            title = norm.title if norm else f"Alterações de arquivo: {len(changes)}"
            callback(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    title,
                    payload,
                )
            )
        elif method in {"item/commandExecution/outputDelta", "item/outputDelta", "item/updated"}:
            # TC-04: streaming tool updates must reach the same semantic
            # pipeline (reducer) as start/completed via RuntimeEvent tool_event.
            norm = normalize_codex_event(params, method, conversation_id)
            payload = {"lifecycle": method, **params}
            if norm:
                payload["canonical_event"] = asdict(norm)
            if norm is None:
                callback(RuntimeEvent(conversation_id, "runtime_event", method, params))
            else:
                title = norm.title or _item_summary(params.get("item") or {})
                callback(
                    RuntimeEvent(
                        conversation_id,
                        "tool_event",
                        title,
                        payload,
                    )
                )
        elif method == "error":
            error = params.get("error") or {}
            callback(RuntimeEvent(conversation_id, "error", str(error.get("message", error)), params))
        elif method in {"item/started", "item/completed"}:
            item = params.get("item") or {}
            item_id = str(item.get("id") or "")
            item_type = str(item.get("type") or "")
            if item_type == "agentMessage" and item_id:
                phase = str(item.get("phase") or "")
                with self._state_lock:
                    self._assistant_item_phases[(conversation_id, item_id)] = phase
                if method == "item/started":
                    callback(
                        RuntimeEvent(
                            conversation_id,
                            "assistant_started",
                            _item_summary(item),
                            {
                                "lifecycle": method,
                                "itemId": item_id,
                                "phase": phase,
                                **params,
                            },
                        )
                    )
                else:
                    # item/completed — carry the final text snapshot if
                    # the item includes an authoritative content field.
                    final_text = str(item.get("text") or "")
                    for block in item.get("content") or []:
                        if not item.get("text") and isinstance(block, dict) and block.get("type") == "text":
                            final_text += str(block.get("text") or "")
                    callback(
                        RuntimeEvent(
                            conversation_id,
                            "assistant_completed",
                            _item_summary(item),
                            {
                                "lifecycle": method,
                                "itemId": item_id,
                                "phase": phase,
                                "final_text": final_text,
                                **params,
                            },
                        )
                    )
            else:
                norm = normalize_codex_event(params, method, conversation_id)
                payload = {"lifecycle": method, **params}
                if norm:
                    payload["canonical_event"] = asdict(norm)
                title = norm.title if norm else _item_summary(item)
                callback(
                    RuntimeEvent(
                        conversation_id,
                        "tool_event",
                        title,
                        payload,
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

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

from .models import RuntimeEvent


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
        self, conversation_id: str, model: str, effort: str, workspace: Path
    ) -> str: ...

    @abc.abstractmethod
    def resume_conversation(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
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
    ) -> None: ...

    @abc.abstractmethod
    def interrupt(self, conversation_id: str) -> None: ...

    @abc.abstractmethod
    def approve_action(self, request_id: str, approved: bool, session: bool = False) -> None: ...

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
                    "version": "0.3.5",
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
        }:
            callback(
                RuntimeEvent(
                    conversation_id,
                    "approval_requested",
                    str(params.get("reason") or params.get("command") or method),
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

    def start_conversation(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        workspace: Path,
    ) -> str:
        self._ensure_started()
        result = self._rpc(
            "thread/start",
            {
                "model": model or None,
                "cwd": str(workspace),
                "approvalPolicy": "on-request",
                "sandbox": "workspaceWrite",
                "serviceName": "vr_mary_studio",
            },
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
    ) -> str:
        self._ensure_started()
        result = self._rpc(
            "thread/resume",
            {"threadId": native_id, "model": model or None, "cwd": str(workspace)},
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
    ) -> None:
        self._ensure_started()
        if native_id not in self._native_to_local:
            native_id = self.resume_conversation(
                conversation_id, native_id, model, effort, workspace
            )
        self._callbacks[conversation_id] = callback
        self._native_to_local[native_id] = conversation_id
        self._rpc(
            "turn/start",
            {
                "threadId": native_id,
                "input": [{"type": "text", "text": message}],
                "cwd": str(workspace),
                "model": model or None,
                "effort": normalize_effort(effort),
                "approvalPolicy": "on-request",
                "sandboxPolicy": {
                    "type": "workspaceWrite",
                    "writableRoots": [str(workspace)],
                    "networkAccess": False,
                },
            },
        )

    def interrupt(self, conversation_id: str) -> None:
        native_id = next(
            (native for native, local in self._native_to_local.items() if local == conversation_id),
            "",
        )
        turn_id = self._active_turns.get(conversation_id, "")
        if native_id and turn_id:
            self._rpc("turn/interrupt", {"threadId": native_id, "turnId": turn_id})

    def approve_action(self, request_id: str, approved: bool, session: bool = False) -> None:
        decision = "acceptForSession" if approved and session else "accept" if approved else "decline"
        self._send({"id": int(request_id), "result": {"decision": decision}})

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
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

    def approve_action(self, request_id: str, approved: bool, session: bool = False) -> None:
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

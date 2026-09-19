from __future__ import annotations
import json
import os
import re
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any
from ..provider_cli import resolve_cli
from ..models import ConversationOptions, RuntimeEvent, approval_preset

from .base import (AgentProvider, EventCallback, ProviderError, UUID4_PATTERN, _claude_token_usage, normalize_effort, require_standard_provider)

class ClaudeProvider(AgentProvider):
    name = "claude"

    def __init__(self, knowledge_root: Path | None = None):
        super().__init__(knowledge_root)
        self.command = resolve_cli("claude")
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._new_sessions: set[str] = set()
        self._workspaces: dict[str, Path] = {}
        # Each in-flight Popen owns a unique reservation.  A close, release or
        # interrupt can revoke that reservation while Popen is still blocked;
        # the process is only published when the same token remains current.
        self._starting: dict[str, tuple[object, str, bool]] = {}
        self._state_lock = threading.RLock()

    def available(self) -> bool:
        if not self.command:
            self.command = resolve_cli("claude")
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
        options = options or ConversationOptions(model=model, effort=effort)
        require_standard_provider(options, "Claude")
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
        options = options or ConversationOptions(model=model, effort=effort)
        require_standard_provider(options, "Claude")
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
        options = options or ConversationOptions(model=model, effort=effort)
        require_standard_provider(options, "Claude")
        if not self.available():
            raise ProviderError("Claude não foi encontrado no PATH.")
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
            "--input-format",
            "text",
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
        if self.knowledge_root:
            from ..knowledge_access import mcp_command
            mcp_args = mcp_command(self.knowledge_root, options.knowledge_context_path)
            # Inline JSON avoids shared files in the user's project.
            command.extend(["--mcp-config", json.dumps({"mcpServers": {
                "vr-mary-studio": {"command": mcp_args[0], "args": mcp_args[1:]}
            }})])
            mcp_tool = "mcp__vr-mary-studio__*"
            if "--allowedTools" in command:
                position = command.index("--allowedTools") + 1
                command[position] += "," + mcp_tool
            else:
                command.extend(["--allowedTools", mcp_tool])
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
                stdin=subprocess.PIPE,
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
        # Keep prompts out of argv: Windows .cmd launchers have a small command
        # limit and interpret shell metacharacters. Drain output concurrently
        # with input so a large prompt cannot deadlock either pipe.
        def write_prompt() -> None:
            stream = getattr(process, "stdin", None)
            if stream is None:
                return
            try:
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(newline="\n")
                stream.write(message)
                stream.close()
            except (OSError, ValueError):
                # The consumer reports an early exit (auth failure/cancellation).
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        threading.Thread(target=write_prompt, name="claude-prompt-input", daemon=True).start()

    def _consume(
        self, conversation_id: str, process: subprocess.Popen[str], callback: EventCallback
    ) -> None:
        callback(RuntimeEvent(conversation_id, "turn_started"))
        final_text = ""
        message_id = ""
        message_text = ""
        task_calls: dict[str, dict[str, Any]] = {}
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
                if event.get("type") == "message_start":
                    message_id = str((event.get("message") or {}).get("id") or "")
                    message_text = ""
                    if message_id:
                        callback(RuntimeEvent(conversation_id, "assistant_started", payload={"itemId": message_id}))
                elif event.get("type") == "message_stop" and message_id:
                    callback(RuntimeEvent(conversation_id, "assistant_completed", payload={"itemId": message_id, "final_text": message_text}))
                elif event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "thinking_delta":
                        thinking = str(delta.get("thinking") or "")
                        if thinking:
                            callback(RuntimeEvent(conversation_id, "reasoning_delta", thinking, payload))
                        continue
                    text = str(delta.get("text") or "")
                    if text:
                        final_text += text
                        message_text += text
                        callback(RuntimeEvent(conversation_id, "assistant_delta", text, {**payload, **({"itemId": message_id} if message_id else {})}))
            elif kind == "assistant":
                message = payload.get("message") or {}
                snapshot_id = str(message.get("id") or "")
                snapshot_text = "".join(str(block.get("text") or "") for block in message.get("content", []) if block.get("type") == "text")
                if snapshot_id and snapshot_text:
                    callback(RuntimeEvent(conversation_id, "assistant_completed", payload={"itemId": snapshot_id, "final_text": snapshot_text}))
                    if not final_text:
                        final_text = snapshot_text
                for block in message.get("content", []):
                    if block.get("type") == "tool_use":
                        if block.get("name") in {"TaskCreate", "TaskUpdate", "TaskList"}:
                            task_calls[str(block.get("id") or "")] = block
                        callback(
                            RuntimeEvent(
                                conversation_id,
                                "tool_event",
                                f"{block.get('name', 'ferramenta')}",
                                block,
                            )
                        )
            elif kind == "user":
                for block in (payload.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    call = task_calls.pop(str(block.get("tool_use_id") or ""), None)
                    if call is not None and not block.get("is_error"):
                        callback(RuntimeEvent(conversation_id, "task_tool_result", payload={
                            "name": call.get("name"), "input": call.get("input"),
                            "result": payload.get("tool_use_result"),
                        }))
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

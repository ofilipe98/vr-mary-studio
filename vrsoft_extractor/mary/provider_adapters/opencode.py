from __future__ import annotations
import json
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any
from dataclasses import asdict
from .tool_normalizer import normalize_opencode_event
from ..models import ConversationOptions, RuntimeEvent

from .base import (AgentProvider, EventCallback, ProviderError, ProviderRateLimited, _opencode_environment, _opencode_error_message, _opencode_token_usage, _parse_opencode_models, _resolve_opencode_command, normalize_effort)

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
                    self.knowledge_root if self.knowledge_root else None,
                    options.knowledge_context_path,
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
        message_id = ""
        message_parts: dict[str, str] = {}
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
                    native_message = str(part.get("messageID") or "")
                    part_id = str(part.get("id") or "")
                    if native_message and part_id:
                        if native_message != message_id:
                            if message_id:
                                callback(RuntimeEvent(conversation_id, "assistant_completed", payload={"itemId": message_id, "final_text": "".join(message_parts.values())}))
                            message_id = native_message
                            message_parts = {}
                            callback(RuntimeEvent(conversation_id, "assistant_started", payload={"itemId": message_id}))
                        previous = message_parts.get(part_id, "")
                        message_parts[part_id] = text
                        delta = text[len(previous):] if text.startswith(previous) else ""
                        if delta:
                            callback(RuntimeEvent(conversation_id, "assistant_delta", delta, {**payload, "itemId": message_id}))
                    else:
                        callback(RuntimeEvent(conversation_id, "assistant_delta", text, payload))
            elif kind == "reasoning":
                text = str(part.get("text") or "")
                if text:
                    callback(RuntimeEvent(conversation_id, "reasoning_delta", text, payload))
            elif kind == "tool_use":
                norm = normalize_opencode_event(payload, conversation_id)
                tool = norm.title if norm else str(part.get("tool") or part.get("name") or "ferramenta")
                if norm:
                    payload["canonical_event"] = asdict(norm)
                callback(RuntimeEvent(conversation_id, "tool_event", tool, payload))
            elif kind in {"step_finish", "step_completed"}:
                # Check for tool payloads wrapped in step events before treating as usage.
                _norm_step = normalize_opencode_event(payload, conversation_id)
                if _norm_step is not None:
                    tool = _norm_step.title or str(part.get("tool") or part.get("name") or "ferramenta")
                    payload["canonical_event"] = asdict(_norm_step)
                    callback(RuntimeEvent(conversation_id, "tool_event", tool, payload))
                    continue
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
            else:
                # TC-04: route any intermediate tool streaming updates that
                # arrive under other type names to the same tool_event pipeline.
                _norm_other = normalize_opencode_event(payload, conversation_id)
                if _norm_other is not None:
                    tool = _norm_other.title or str(part.get("tool") or part.get("name") or "ferramenta")
                    payload["canonical_event"] = asdict(_norm_other)
                    callback(RuntimeEvent(conversation_id, "tool_event", tool, payload))
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
        if message_id and not reported_error and not exit_code:
            callback(RuntimeEvent(conversation_id, "assistant_completed", payload={"itemId": message_id, "final_text": "".join(message_parts.values())}))
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

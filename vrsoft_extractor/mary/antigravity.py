"""Official agy CLI adapter; Google owns OAuth and the operating-system keyring.

Protocol: https://antigravity.google/docs/cli/headless/
Authentication: https://antigravity.google/docs/cli/install/
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path

from .antigravity_auth import (
    AUTH_MARKER_VRSTUDIO as AUTH_MARKER_VRSTUDIO,
    AUTH_MARKER_T3 as AUTH_MARKER_T3,
    AUTH_PREFIX_ACP as AUTH_PREFIX_ACP,
    AUTH_PREFIX_BROWSER as AUTH_PREFIX_BROWSER,
    INIT_TIMEOUT_SECONDS as INIT_TIMEOUT_SECONDS,
    MAX_AUTH_LINE_BYTES as MAX_AUTH_LINE_BYTES,
    OAUTH_TIMEOUT_SECONDS as OAUTH_TIMEOUT_SECONDS,
    AccountState as AccountState,
    AntigravityAuthManager as AntigravityAuthManager,
    AttemptState as AttemptState,
    AuthStreamParser as AuthStreamParser,
    LoginAttempt as LoginAttempt,
    OAuthCallbackError as OAuthCallbackError,
    OAuthValidationError as OAuthValidationError,
    ProviderReadiness as ProviderReadiness,
    ValidatedAuthUrl as ValidatedAuthUrl,
    forward_callback_to_listener as forward_callback_to_listener,
    validate_authorization_url as validate_authorization_url,
    validate_callback_url as validate_callback_url,
)
from .models import ConversationOptions, RuntimeEvent, approval_preset
from .providers import AgentProvider, ProviderError, _token_breakdown


def resolve_agy() -> str | None:
    direct = shutil.which("agy.exe") or shutil.which("agy")
    if direct:
        return direct
    candidate = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "agy/bin/agy.exe"
    return str(candidate) if candidate.is_file() else None


def google_account_environment() -> dict[str, str]:
    settings = Path.home() / ".gemini/antigravity-cli/settings.json"
    if settings.is_file():
        try:
            config = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProviderError("Não foi possível verificar a autenticação do agy.") from exc
        if config.get("modelProvider"):
            raise ProviderError("O agy usa um modelProvider alternativo. Remova modelProvider das configurações do CLI para usar sua conta Google, conforme a documentação.")
    env = os.environ.copy()
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL"):
        env.pop(name, None)
    return env


class LegacyAntigravityProvider(AgentProvider):
    name = "antigravity"

    def __init__(self, knowledge_root=None):
        super().__init__(knowledge_root)
        self.command = resolve_agy()
        self._active = {}
        self._lock = threading.RLock()
        self._model_variants = {}

    def available(self):
        self.command = resolve_agy()
        return bool(self.command)

    def list_models(self):
        fallback = [{"id": "default", "model": "default", "displayName": "Antigravity padrão", "isDefault": True}]
        if not self.available():
            return fallback
        try:
            result = subprocess.run([self.command, "models"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=25,
                                    env=google_account_environment(),
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode:
                return fallback
            groups = {}
            variants = {}
            for line in result.stdout.splitlines():
                parts = re.split(r"\s{2,}|\t", line.strip(), maxsplit=1)
                if len(parts) == 2 and re.fullmatch(r"[a-z0-9][a-z0-9._-]+", parts[0]):
                    model_id, label = parts
                    match = re.search(r"-(low|medium|high)$", model_id)
                    base = model_id[:match.start()] if match else model_id
                    group = groups.setdefault(base, {
                        "id": model_id, "model": model_id,
                        "displayName": re.sub(r"\s*\((?:Low|Medium|High)\)$", "", label),
                        "aliases": [], "supportedReasoningEfforts": [],
                    })
                    group["aliases"].append(model_id)
                    if match:
                        variants.setdefault(base, {})[match[1]] = model_id
                    else:
                        group["supportedReasoningEfforts"] = [
                            {"reasoningEffort": x} for x in ("low", "medium", "high")]
            for base, group in groups.items():
                choices = variants.get(base, {})
                if choices:
                    group["supportedReasoningEfforts"] = [
                        {"reasoningEffort": x} for x in ("low", "medium", "high") if x in choices]
                    for alias in group["aliases"]:
                        self._model_variants[alias] = choices
                fallback.append(group)
        except (OSError, subprocess.TimeoutExpired, ProviderError):
            pass
        return fallback

    def start_conversation(self, conversation_id, model, effort, workspace, options=None):
        # agy assigns the native ID in init; never invent a resumable ID.
        return ""

    def resume_conversation(self, conversation_id, native_id, model, effort, workspace, options=None):
        return native_id

    def send_message(self, conversation_id, native_id, model, effort, workspace,
                     message, callback, options=None, skills=None, image_paths=None):
        if not self.available():
            raise ProviderError("Antigravity CLI não encontrado. Instale o agy e entre com sua conta Google.")
        if image_paths:
            raise ProviderError("O protocolo de entrada do Antigravity CLI aceita apenas texto; remova os anexos de imagem.")
        options = options or ConversationOptions(model=model, effort=effort)
        if options.vr_enabled:
            message += (
                "\n\nNeste turno headless, priorize os trechos de fontes já fornecidos. "
                "Buscas adicionais são opcionais. Se uma ferramenta exigir permissão "
                "ou falhar, não repita a operação nem tente contornar a restrição: "
                "responda com os fatos sustentados pelos trechos disponíveis e "
                "indique apenas as lacunas específicas. Sempre produza uma resposta textual."
            )
        env = google_account_environment()
        command = [self.command, "--input-format", "stream-json", "--output-format", "stream-json"]
        if native_id:
            command += ["--conversation", native_id]
        if model and model != "default" and not self._model_variants:
            self.list_models()
        choices = self._model_variants.get(model, {})
        selected_effort = effort if effort in {"low", "medium", "high"} else "high" if effort in {"max", "xhigh", "ultra"} else ""
        if choices and selected_effort and selected_effort not in choices:
            raise ProviderError(f"O modelo selecionado não oferece raciocínio {selected_effort}.")
        if model and model != "default":
            command += ["--model", choices.get(selected_effort, model)]
        if selected_effort:
            command += ["--effort", selected_effort]
        preset = approval_preset(options.approval_profile)
        if preset.sandbox == "read-only" or options.collaboration_mode == "plan":
            command += ["--mode", "plan"]
        elif preset.sandbox == "danger-full-access":
            command += ["--dangerously-skip-permissions"]
        else:
            command += ["--mode", "accept-edits"]
        if options.vr_enabled and self.knowledge_root:
            command += ["--add-dir", str(self.knowledge_root)]
        with self._lock:
            if conversation_id in self._active:
                raise ProviderError("Já existe um turno Antigravity em execução.")
            process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding="utf-8", errors="replace", bufsize=1,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self._active[conversation_id] = process
        threading.Thread(target=self._consume, args=(conversation_id, process, message, callback), daemon=True).start()

    def _consume(self, cid, process, message, callback):
        errors = deque(maxlen=40)
        def drain():
            for line in process.stderr:
                errors.append(line.strip())
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        callback(RuntimeEvent(cid, "turn_started"))
        text = ""
        result_seen = False
        empty_retry = False
        try:
            process.stdin.write(json.dumps({"event": "user", "message": {"content": message}}) + "\n")
            process.stdin.flush()
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("event")
                if kind == "init" and event.get("conversation_id"):
                    callback(RuntimeEvent(cid, "native_session_started", payload={"native_id": event["conversation_id"]}))
                elif kind == "step_update":
                    step = event.get("step_update") or {}
                    if step.get("step_type") == "agent_response" and step.get("text_delta"):
                        delta = str(step["text_delta"])
                        text += delta
                        callback(RuntimeEvent(cid, "assistant_delta", delta, step))
                    elif step.get("step_type") == "tool":
                        callback(RuntimeEvent(cid, "tool_event", str(step.get("tool_name", "ferramenta")), step))
                elif kind == "result":
                    result_seen = True
                    result = event.get("result") or {}
                    if not text.strip() and result.get("response"):
                        text = str(result["response"])
                        callback(RuntimeEvent(cid, "assistant_delta", text, result))
                    if result.get("status") != "SUCCESS":
                        callback(RuntimeEvent(cid, "error", str(result.get("error") or result.get("status") or "Falha no Antigravity")))
                    elif not text.strip() and not empty_retry:
                        # A denied tool can end a successful CLI turn without an
                        # answer. Recover once using the existing context only.
                        empty_retry = True
                        result_seen = False
                        process.stdin.write(json.dumps({"event": "user", "message": {"content":
                            "O turno anterior terminou sem resposta textual. Não use ferramentas, "
                            "não repita operações negadas e não solicite permissões. Responda agora "
                            "à solicitação anterior usando somente o contexto já disponível, "
                            "mantendo o formato solicitado. Declare lacunas específicas se necessário."
                        }}) + "\n")
                        process.stdin.flush()
                        continue
                    elif not text.strip():
                        callback(RuntimeEvent(cid, "error", "Antigravity não retornou texto após uma tentativa de recuperação com o contexto disponível."))
                    usage = result.get("usage") or {}
                    if usage:
                        breakdown = _token_breakdown(input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"), reasoning_tokens=usage.get("thinking_tokens"), cached_tokens=usage.get("cache_read_tokens"), total_tokens=usage.get("total_tokens"))
                        callback(RuntimeEvent(cid, "token_usage", payload={"tokenUsage": {"last": breakdown, "modelContextWindow": None}}))
                    process.stdin.close()
            code = process.wait()
            reader.join(timeout=1)
            if code or not result_seen:
                callback(RuntimeEvent(cid, "error", "\n".join(errors) or "Antigravity encerrou sem resultado válido."))
        except Exception as exc:
            callback(RuntimeEvent(cid, "error", str(exc)))
        finally:
            if process.poll() is None:
                process.terminate()
            with self._lock:
                if self._active.get(cid) is process:
                    self._active.pop(cid, None)
            callback(RuntimeEvent(cid, "turn_completed", payload={"exit_code": process.poll()}))

    def interrupt(self, conversation_id):
        with self._lock:
            process = self._active.get(conversation_id)
            if process and process.poll() is None:
                process.terminate()

    def approve_action(self, request_id, approved, session=False, request=None):
        raise ProviderError("O modo headless do agy usa as permissões do CLI e não expõe aprovação interativa.")

    def release_conversation(self, conversation_id, native_id, *, delete_native=False):
        self.interrupt(conversation_id)

    def close(self):
        with self._lock:
            for cid in list(self._active):
                self.interrupt(cid)


# Public provider now uses one ACP profile for browser login and conversations.
# Keep the legacy decoder available for historical fixtures, not provider routing.
from .antigravity_provider import AntigravityProvider as AntigravityProvider

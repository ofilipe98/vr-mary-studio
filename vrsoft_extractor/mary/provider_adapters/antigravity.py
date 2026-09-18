"""Antigravity conversations through Google's ACP server and Studio profile."""
from __future__ import annotations

import base64
import mimetypes
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..antigravity_acp import (
    AcpError,
    IncompleteRuntimeError,
    RUNTIME_NOT_FOUND_MESSAGE,
    extract_acp_models,
    has_saved_account,
    resolve_acp,
    resolve_acp_runtime,
    spawn_acp_client,
)
from ..models import ConversationOptions, RuntimeEvent, approval_preset
from .base import AgentProvider, ProviderError, _token_breakdown

NATIVE_PREFIX = "acp:"

# RuntimeEvent kinds are a stable Studio contract shared with the
# orchestrator, persistence and the frontend. Antigravity session updates are
# normalized onto them; no provider-specific kinds are introduced here.
ASSISTANT_CHUNK_UPDATES = ("agent_message_chunk",)
REASONING_UPDATES = ("agent_thought_chunk", "thought")
TOOL_UPDATES = ("tool_call", "tool_call_update", "tool_result")

# The provider-default alias never sends an identifier: it keeps the agent's
# current model instead of replacing the selection.
DEFAULT_MODEL_ALIASES = {"", "default"}


def _chunk_text(content):
    """Extracts plain text from an ACP message chunk content block."""
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) and text else ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts)
    return ""


def _config_option_by_id(config_options, *ids):
    wanted = {str(i).lower() for i in ids}
    for opt in config_options or []:
        if not isinstance(opt, dict):
            continue
        opt_id = str(opt.get("id") or "").lower()
        category = str(opt.get("category") or "").lower()
        if opt_id in wanted or (not opt_id and category in wanted):
            return opt
    # Fall back to a category match (e.g. category == "model").
    for opt in config_options or []:
        if isinstance(opt, dict) and str(opt.get("category") or "").lower() in wanted:
            return opt
    return None


def _option_values(opt):
    """Allowed values advertised by a select config option (may be empty)."""
    values = []
    options = opt.get("options") if isinstance(opt, dict) else None
    if isinstance(options, list):
        for entry in options:
            if isinstance(entry, dict):
                value = entry.get("value", entry.get("id", entry.get("modelId")))
            else:
                value = entry
            if isinstance(value, str) and value and value not in values:
                values.append(value)
    return values


class AntigravityProvider(AgentProvider):
    name = "antigravity"

    def __init__(self, knowledge_root=None):
        super().__init__(knowledge_root)
        self._lock = threading.RLock()
        self._active = {}
        self._approvals = {}
        self._catalog = []
        self._catalog_time = 0.0
        self._model_variants = {}

    def available(self):
        try:
            return resolve_acp() is not None
        except IncompleteRuntimeError:
            return False
        except Exception:
            return False

    def update_catalog(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            self._catalog = list(items)
            self._catalog_time = time.monotonic()

    def _read_catalog(self, session):
        items = extract_acp_models(session)
        self.update_catalog(items)
        return items

    def list_models(self):
        if not self.available() or not has_saved_account():
            return []
        with self._lock:
            if self._catalog and time.monotonic() - self._catalog_time < 60:
                return list(self._catalog)
        client = spawn_acp_client()
        try:
            client.start()
            client.request("authenticate", {"methodId": "oauth-personal"})
            session = client.request("session/new", {"cwd": str(Path.home()), "mcpServers": []})
            return self._read_catalog(session)
        finally:
            client.close()

    def start_conversation(self, conversation_id, model, effort, workspace, options=None):
        return ""

    def resume_conversation(self, conversation_id, native_id, model, effort, workspace, options=None):
        if native_id and not native_id.startswith(NATIVE_PREFIX):
            raise ProviderError("Esta conversa pertence ao CLI anterior. O histórico foi preservado; inicie uma nova conversa para usar a conta conectada pelo navegador.")
        return native_id

    def send_message(self, conversation_id, native_id, model, effort, workspace,
                     message, callback, options=None, skills=None, image_paths=None):
        if not self.available():
            raise ProviderError(f"{RUNTIME_NOT_FOUND_MESSAGE}. Atualize o Antigravity CLI.")
        if not has_saved_account():
            raise ProviderError("Entre com Google em Configurações → Provedores → Antigravity.")
        try:
            runtime_info = resolve_acp_runtime()
        except IncompleteRuntimeError as exc:
            raise ProviderError(str(exc)) from None
        if runtime_info is None:
            raise ProviderError(f"{RUNTIME_NOT_FOUND_MESSAGE}. Atualize o Antigravity CLI.")
        self.resume_conversation(conversation_id, native_id, model, effort, workspace, options)
        options = options or ConversationOptions(model=model, effort=effort)
        state = {"client": None, "session": "", "cancelled": False, "text": False, "options": options}
        client = spawn_acp_client(
            runtime_info=runtime_info,
            on_notification=lambda method, params: self._update(conversation_id, state, callback, method, params),
            on_request=lambda request_id, method, params: self._permission(conversation_id, state, callback, request_id, method, params),
        )
        state["client"] = client
        with self._lock:
            if conversation_id in self._active:
                raise ProviderError("Já existe um turno Antigravity em execução.")
            self._active[conversation_id] = state
        threading.Thread(target=self._run_turn, args=(conversation_id, native_id, model, effort, Path(workspace),
                                                     message, callback, options, image_paths or [], state), daemon=True).start()

    def _run_turn(self, cid, native_id, model, effort, workspace, message, callback, options, images, state):
        client = state["client"]
        callback(RuntimeEvent(cid, "turn_started"))
        failed = False
        try:
            client.start()
            client.request("authenticate", {"methodId": "oauth-personal"})
            params = {"cwd": str(workspace.resolve()), "mcpServers": []}
            if self.knowledge_root and options.tools_enabled:
                from ..knowledge_access import mcp_command
                command = mcp_command(Path(self.knowledge_root), options.knowledge_context_path)
                params["mcpServers"] = [{
                    "name": "vr-mary-studio", "command": command[0],
                    "args": command[1:], "env": [],
                }]
            if options.vr_enabled and self.knowledge_root:
                message += "\n\nUse as fontes já fornecidas. Se uma ferramenta for recusada, não repita a operação; responda com o contexto disponível e indique lacunas."
            if native_id:
                session_id = native_id[len(NATIVE_PREFIX):]
                state["session"] = session_id
                method = "session/resume" if client.capabilities.get("sessionCapabilities", {}).get("resume") is not None else "session/load"
                state["replaying"] = method == "session/load"
                session = client.request(method, {**params, "sessionId": session_id})
                state["replaying"] = False
            else:
                session = client.request("session/new", params)
                session_id = session.get("sessionId")
                if not isinstance(session_id, str) or not session_id:
                    raise AcpError("session/new")
                state["session"] = session_id
                callback(RuntimeEvent(cid, "native_session_started", payload={"native_id": NATIVE_PREFIX + session_id}))
            self._read_catalog(session)
            if state["cancelled"]:
                return
            self._configure(client, session_id, session, model, effort, options)
            content = [{"type": "text", "text": message}]
            if images and not client.capabilities.get("promptCapabilities", {}).get("image"):
                raise ProviderError("Este runtime Antigravity não aceita imagens.")
            for image_path in images:
                path = Path(image_path)
                content.append({"type": "image", "mimeType": mimetypes.guess_type(path.name)[0] or "image/png",
                                "data": base64.b64encode(path.read_bytes()).decode("ascii")})
            result = client.request("session/prompt", {"sessionId": session_id, "prompt": content}, timeout=600)
            if result.get("stopReason") == "cancelled":
                state["cancelled"] = True
            elif result.get("stopReason") not in ("end_turn", "max_tokens"):
                raise AcpError("session/prompt")
            elif not state["text"]:
                raise ProviderError("Antigravity encerrou o turno sem uma resposta textual.")
        except Exception as exc:
            if not state["cancelled"]:
                failed = True
                text = str(exc) if isinstance(exc, (AcpError, ProviderError)) else "Falha na sessão Antigravity. Tente novamente."
                callback(RuntimeEvent(cid, "error", text))
        finally:
            client.close()
            with self._lock:
                self._active.pop(cid, None)
                self._approvals = {k: v for k, v in self._approvals.items() if v[0] is not client}
            callback(RuntimeEvent(cid, "turn_completed", payload={"exit_code": 1 if failed else 0, "cancelled": state["cancelled"]}))

    def _configure(self, client, session_id, session, model, effort, options):
        session = session if isinstance(session, dict) else {}
        config_options = session.get("configOptions") or []
        if not isinstance(config_options, list):
            config_options = []
        self._apply_model_selection(client, session_id, config_options, model)
        self._apply_effort_selection(client, session_id, config_options, effort)

        mode = "default"
        if options and options.tools_enabled is False:
            mode = "default"
        elif options and options.approval_profile:
            profile_to_mode = {
                "supervised": "default",
                "auto_edits": "auto_edit",
                "full_access": "yolo",
                "research_readonly": "default",
            }
            mode = profile_to_mode.get(options.approval_profile, "default")
        client.request("session/set_mode", {"sessionId": session_id, "modeId": mode})

    def _apply_model_selection(self, client, session_id, config_options, model):
        """Applies the requested model through the negotiated ACP mechanism.

        Never sends the invented ``session/configure`` method. When the
        session negotiates a ``model`` config option, the model is validated
        against the account's catalog and applied with
        ``session/set_config_option``. Otherwise the unstable
        ``session/set_model`` is used when the runtime supports it
        (``-32601`` means unsupported and is tolerated).
        """
        if not model or str(model) in DEFAULT_MODEL_ALIASES:
            return
        model_opt = _config_option_by_id(config_options, "model")
        if model_opt is not None:
            option_id = str(model_opt.get("id") or "model")
            current = model_opt.get("currentValue")
            allowed = _option_values(model_opt)
            if allowed and model not in allowed:
                raise ProviderError(
                    f"Modelo '{model}' indisponível para esta conta Google. "
                    "Selecione um modelo disponível."
                )
            if current is not None and model == current:
                return
            client.request(
                "session/set_config_option",
                {"sessionId": session_id, "configId": option_id, "value": model},
            )
            return
        try:
            client.request("session/set_model", {"sessionId": session_id, "modelId": model})
        except AcpError as exc:
            if exc.code != -32601:
                raise

    def _apply_effort_selection(self, client, session_id, config_options, effort):
        """Applies thinking effort only through a negotiated option."""
        if not effort:
            return
        effort_opt = _config_option_by_id(config_options, "thinking", "reasoningEffort")
        if effort_opt is None:
            return
        option_id = str(effort_opt.get("id") or "thinking")
        current = effort_opt.get("currentValue")
        allowed = _option_values(effort_opt)
        if allowed and effort not in allowed:
            return
        if current is not None and effort == current:
            return
        client.request(
            "session/set_config_option",
            {"sessionId": session_id, "configId": option_id, "value": effort},
        )

    def cancel_conversation(self, conversation_id):
        with self._lock:
            state = self._active.get(conversation_id)
        if state:
            state["cancelled"] = True
            if state["client"]:
                state["client"].close()
            return True
        return False

    def _update(self, cid, state, callback, method, params):
        if method != "session/update" or params.get("sessionId") != state["session"] or state["cancelled"]:
            return
        update = params.get("update", {})
        if not isinstance(update, dict):
            return
        kind = update.get("sessionUpdate")
        if kind in ASSISTANT_CHUNK_UPDATES:
            text = _chunk_text(update.get("content"))
            if text:
                state["text"] = True
                callback(RuntimeEvent(cid, "assistant_delta", text))
        elif kind in REASONING_UPDATES:
            thought = update.get("thought")
            text = thought if isinstance(thought, str) and thought else _chunk_text(update.get("content"))
            if text:
                callback(RuntimeEvent(cid, "reasoning_delta", text))
        elif kind in ("tool_call", "tool_call_update"):
            tool_call = update.get("toolCall") or {}
            if not isinstance(tool_call, dict):
                tool_call = {}
            title = str(tool_call.get("title") or tool_call.get("name") or "Ferramenta externa")
            status = str(update.get("status") or tool_call.get("status") or "")
            callback(RuntimeEvent(cid, "tool_event", title, {
                "sessionUpdate": kind,
                "status": status,
                "title": title,
                "name": str(tool_call.get("name") or tool_call.get("title") or ""),
                "toolCall": tool_call,
                "item": {
                    "id": str(tool_call.get("toolCallId") or ""),
                    "type": "toolCall",
                    "status": status,
                    "title": title,
                },
            }))
        elif kind == "tool_result":
            result = update.get("toolResult") or {}
            if not isinstance(result, dict):
                result = {}
            title = str(result.get("title") or result.get("name") or "Resultado")
            status = str(update.get("status") or result.get("status") or "")
            callback(RuntimeEvent(cid, "tool_event", title, {
                "sessionUpdate": kind,
                "status": status,
                "title": title,
                "name": str(result.get("name") or result.get("title") or ""),
                "toolResult": result,
                "item": {
                    "id": str(result.get("toolCallId") or ""),
                    "type": "toolResult",
                    "status": status,
                    "title": title,
                },
            }))
        elif kind == "usage_update":
            used = update.get("used", 0)
            size = update.get("size", 0)
            payload = {
                "tokenUsage": {
                    "contextOnly": True,
                    "last": {"totalTokens": used},
                    "modelContextWindow": size,
                }
            }
            callback(RuntimeEvent(cid, "token_usage", payload=payload))

    def _permission(self, cid, state, callback, request_id, method, params):
        if method != "session/request_permission":
            return
        client = state.get("client")
        cancelled = state.get("cancelled", False)
        options = state.get("options") or ConversationOptions()
        tool_call = params.get("toolCall") or {}
        available_opts = params.get("options") or []

        if cancelled or not options.tools_enabled or options.collaboration_mode == "plan":
            if client:
                client.respond(request_id, {"outcome": {"outcome": "cancelled"}})
            return

        profile = options.approval_profile
        if profile == "full_access":
            opt = next((o for o in available_opts if o.get("kind") == "allow_always"), None)
            if not opt:
                opt = next((o for o in available_opts if o.get("kind") == "allow_once"), None)
            option_id = opt.get("optionId") if opt else "approve"
            if client:
                client.respond(request_id, {"outcome": {"outcome": "selected", "optionId": option_id}})
            return

        if profile == "research_readonly":
            kind = tool_call.get("kind")
            if kind in ("read", "search"):
                opt = next((o for o in available_opts if o.get("kind") == "allow_once"), None)
                if opt and client:
                    client.respond(request_id, {"outcome": {"outcome": "selected", "optionId": opt.get("optionId")}})
                    return
            if client:
                client.respond(request_id, {"outcome": {"outcome": "cancelled"}})
            return

        title = tool_call.get("title") or params.get("permission", {}).get("description", "Acesso solicitado")
        action_id = uuid.uuid4().hex
        with self._lock:
            self._approvals[action_id] = (client, request_id, available_opts)
        callback(RuntimeEvent(cid, "approval_requested", title,
                              payload={"request_id": action_id, "options": available_opts,
                                       "tool_call": tool_call, "description": title}))

    def resolve_action(self, action_id, approved):
        self.approve_action(action_id, approved)
        return True

    def interrupt(self, conversation_id: str) -> None:
        self.cancel_conversation(conversation_id)

    def approve_action(
        self,
        request_id: str,
        approved: bool,
        session: bool = False,
        request: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            pair = self._approvals.pop(request_id, None)
        if not pair:
            return
        client, r_id, available_opts = pair
        if approved:
            opt = next((o for o in available_opts if o.get("optionId") == "approve"), None)
            if not opt:
                kind_target = "allow_always" if session else "allow_once"
                opt = next((o for o in available_opts if o.get("kind") == kind_target), None)
            if not opt and available_opts:
                opt = available_opts[0]
            opt_id = opt.get("optionId", "approve") if opt else "approve"
            client.respond(r_id, {"outcome": {"outcome": "selected", "optionId": opt_id}})
        else:
            client.respond(r_id, {"outcome": {"outcome": "cancelled"}})

    def close(self) -> None:
        with self._lock:
            for cid in list(self._active.keys()):
                self.cancel_conversation(cid)

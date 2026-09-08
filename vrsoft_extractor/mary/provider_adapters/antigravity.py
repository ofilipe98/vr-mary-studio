"""Antigravity conversations through Google's ACP server and Studio profile."""
from __future__ import annotations

import base64
import mimetypes
import threading
import time
import uuid
from pathlib import Path

from ..antigravity_acp import AcpClient, AcpError, has_saved_account, resolve_acp
from ..models import ConversationOptions, RuntimeEvent, approval_preset
from .base import AgentProvider, ProviderError, _token_breakdown

NATIVE_PREFIX = "acp:"


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
        return resolve_acp() is not None

    def _read_catalog(self, session):
        state = session.get("models") or {}
        default = state.get("currentModelId")
        items = []
        for item in state.get("availableModels", []):
            model_id = item.get("modelId")
            if isinstance(model_id, str) and model_id:
                items.append({"id": model_id, "model": model_id, "displayName": item.get("name") or model_id,
                              "description": item.get("description") or "", "isDefault": model_id == default})
        with self._lock:
            self._catalog = items
            self._catalog_time = time.monotonic()
        return items

    def list_models(self):
        if not self.available() or not has_saved_account():
            return []
        with self._lock:
            if self._catalog and time.monotonic() - self._catalog_time < 60:
                return list(self._catalog)
        client = AcpClient()
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
            raise ProviderError("Servidor Antigravity ACP não encontrado. Atualize o Antigravity CLI.")
        if not has_saved_account():
            raise ProviderError("Entre com Google em Configurações → Provedores → Antigravity.")
        self.resume_conversation(conversation_id, native_id, model, effort, workspace, options)
        options = options or ConversationOptions(model=model, effort=effort)
        state = {"client": None, "session": "", "cancelled": False, "text": False, "options": options}
        client = AcpClient(on_notification=lambda method, params: self._update(conversation_id, state, callback, method, params),
                           on_request=lambda request_id, method, params: self._permission(conversation_id, state, callback, request_id, method, params))
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
            if options.vr_enabled and self.knowledge_root:
                params["additionalDirectories"] = [str(Path(self.knowledge_root).resolve())]
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
        models = {x.get("modelId") for x in (session.get("models") or {}).get("availableModels", [])}
        if model and model != "default":
            if model not in models:
                raise ProviderError("O modelo selecionado não está disponível na conta Antigravity conectada. Atualize o catálogo.")
            client.request("session/set_model", {"sessionId": session_id, "modelId": model})
        preset = approval_preset(options.approval_profile)
        requested_mode = "yolo" if preset.sandbox == "danger-full-access" else "auto_edit" if preset.id == "auto_edits" else "default"
        if options.collaboration_mode == "plan" or preset.sandbox == "read-only":
            requested_mode = "default"
        available_modes = {m.get("id") for m in (session.get("modes") or {}).get("availableModes", [])}
        if requested_mode not in available_modes:
            raise ProviderError("O runtime não oferece o modo de permissões solicitado.")
        client.request("session/set_mode", {"sessionId": session_id, "modeId": requested_mode})
        if effort and effort != "auto":
            for config in session.get("configOptions", []):
                if config.get("category") == "thought_level":
                    values = {x.get("value") for x in config.get("options", []) if isinstance(x, dict)}
                    if effort in values:
                        client.request("session/set_config_option", {"sessionId": session_id, "configId": config["id"], "value": effort})
                    break

    def _update(self, cid, state, callback, method, params):
        if method != "session/update" or state.get("replaying") or state["cancelled"]:
            return
        if state["session"] and params.get("sessionId") != state["session"]:
            return
        update = params.get("update", {})
        kind = update.get("sessionUpdate")
        content = update.get("content") or {}
        if kind in ("agent_message_chunk", "agent_thought_chunk") and isinstance(content, dict) and content.get("type") == "text":
            text = content.get("text") or ""
            if kind == "agent_message_chunk":
                state["text"] = state["text"] or bool(text.strip())
            callback(RuntimeEvent(cid, "assistant_delta" if kind == "agent_message_chunk" else "reasoning_delta", text))
        elif kind in ("tool_call", "tool_call_update"):
            callback(RuntimeEvent(cid, "tool_event", str(update.get("title") or "Ferramenta"), update))
        elif kind == "usage_update":
            # ACP reports context occupancy, not cumulative billed tokens.
            breakdown = _token_breakdown(total_tokens=update.get("used"))
            callback(RuntimeEvent(cid, "token_usage", payload={"tokenUsage": {
                "last": breakdown, "modelContextWindow": update.get("size"), "contextOnly": True}}))

    def _permission(self, cid, state, callback, request_id, method, params):
        client = state["client"]
        if method != "session/request_permission":
            client._send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unsupported client method"}})
            return
        options = state["options"]
        # ACP default mode asks permission. Plan always denies
        # tools here because this runtime does not advertise a native plan mode.
        if state["cancelled"] or options.collaboration_mode == "plan" or options.approval_profile == "research_readonly":
            client.respond(request_id, {"outcome": {"outcome": "cancelled"}})
            return
        choices = params.get("options", [])
        key = uuid.uuid4().hex
        with self._lock:
            self._approvals[key] = (client, request_id, choices)
        tool = params.get("toolCall") or {}
        callback(RuntimeEvent(cid, "approval_requested", str(tool.get("title") or "Permitir ferramenta Antigravity?"),
                              {"request_id": key, "method": method, **params}))

    def approve_action(self, request_id, approved, session=False, request=None):
        with self._lock:
            pending = self._approvals.pop(str(request_id), None)
        if not pending:
            raise ProviderError("Esta solicitação de aprovação já foi encerrada.")
        client, native_id, choices = pending
        preferred = "allow_always" if session else "allow_once"
        selected = next((x for x in choices if x.get("kind") == preferred), None) if approved else None
        if approved and not selected:
            selected = next((x for x in choices if x.get("kind") == "allow_once"), None)
        outcome = {"outcome": "selected", "optionId": selected["optionId"]} if selected else {"outcome": "cancelled"}
        client.respond(native_id, {"outcome": outcome})

    def interrupt(self, conversation_id):
        with self._lock:
            state = self._active.get(conversation_id)
            if not state:
                return
            state["cancelled"] = True
        try:
            if state["session"]:
                state["client"].notify("session/cancel", {"sessionId": state["session"]})
        except AcpError:
            pass
        state["client"].close()

    def release_conversation(self, conversation_id, native_id, *, delete_native=False):
        self.interrupt(conversation_id)

    def close(self):
        with self._lock:
            active = list(self._active)
        for cid in active:
            self.interrupt(cid)

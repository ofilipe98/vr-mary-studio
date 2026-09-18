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
    AcpClient,
    AcpError,
    IncompleteRuntimeError,
    extract_acp_models,
    has_saved_account,
    resolve_acp,
)
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
        config_options = session.get("configOptions", [])
        model_opt = next((opt for opt in config_options if opt.get("id") == "model" or opt.get("category") == "model"), None)
        if model_opt and model:
            client.notify("session/configure", {"sessionId": session_id, "options": {"model": model}})
        if effort:
            effort_opt = next((opt for opt in config_options if opt.get("id") == "thinking" or opt.get("id") == "reasoningEffort"), None)
            if effort_opt:
                client.notify("session/configure", {"sessionId": session_id, "options": {effort_opt["id"]: effort}})

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
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content", {})
            text = content.get("text", "")
            if text:
                state["text"] = True
                callback(RuntimeEvent(cid, "assistant_delta", text))
        elif kind == "thought":
            thought = update.get("thought", "")
            if thought:
                callback(RuntimeEvent(cid, "thought_delta", thought))
        elif kind == "tool_call":
            tc = update.get("toolCall", {})
            title = tc.get("name") or "Ferramenta externa"
            callback(RuntimeEvent(cid, "tool_call_started", title, payload=tc))
        elif kind == "tool_result":
            tr = update.get("toolResult", {})
            title = tr.get("name") or "Resultado"
            callback(RuntimeEvent(cid, "tool_call_completed", title, payload=tr))
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
            callback(RuntimeEvent(cid, "usage_delta", payload=payload))

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

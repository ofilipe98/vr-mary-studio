"""
Contratos e caracterização do baseline para o Plano V2 (Lote L0).

Este módulo valida e fixa as assinaturas e comportamentos fundamentais dos
componentes centrais (ChatOrchestrator, KnowledgeRouter, AgentProvider, ChatBridge)
e a integridade das fixtures sintéticas antes das refatorações dos Itens 4, 5 e 6.
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.fixtures.synthetic_events import (
    antigravity_synthetic_turn_events,
    claude_raw_protocol_lines,
    claude_synthetic_turn_events,
    codex_synthetic_turn_events,
    opencode_raw_protocol_lines,
    opencode_synthetic_turn_events,
    synthetic_evidence_bundle,
)
from vrsoft_extractor.mary.antigravity_provider import AntigravityProvider
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.models import (
    EvidenceBundle,
    KnowledgeDocument,
    QueryProfile,
    RuntimeEvent,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.providers import (
    AgentProvider,
    ClaudeProvider,
    CodexProvider,
    OpenCodeProvider,
)


# ---------------------------------------------------------------------------
# 1. RuntimeEvent Contract
# ---------------------------------------------------------------------------

class TestRuntimeEventContract:
    def test_runtime_event_fields_and_defaults(self) -> None:
        event = RuntimeEvent(
            conversation_id="c-1",
            kind="assistant_delta",
            text="hello",
            payload={"phase": "commentary"},
        )
        assert event.conversation_id == "c-1"
        assert event.kind == "assistant_delta"
        assert event.text == "hello"
        assert event.payload == {"phase": "commentary"}
        assert event.created_at.endswith("Z") or "T" in event.created_at

    def test_runtime_event_empty_payload(self) -> None:
        event = RuntimeEvent("c-2", "turn_started")
        assert event.text == ""
        assert event.payload == {}

        # Verify mutable default isolation: modifying one event's payload does not leak
        event2 = RuntimeEvent("c-3", "turn_completed")
        event.payload["test_key"] = "isolated"
        assert "test_key" not in event2.payload


# ---------------------------------------------------------------------------
# 2. EvidenceBundle Contract
# ---------------------------------------------------------------------------

class TestEvidenceBundleContract:
    def test_bundle_properties_and_serialization(self) -> None:
        bundle = synthetic_evidence_bundle(include_endoo=True)
        assert isinstance(bundle, EvidenceBundle)
        assert isinstance(bundle.profile, QueryProfile)
        assert len(bundle.candidates) == 2

        # Source and origin counting
        assert bundle.source_counts == {"wiki": 2, "kb": 0, "schema": 0}
        assert bundle.source_origin_counts == {"vrwiki": 1, "endoo": 1}
        assert bundle.selected_modules == ("Fiscal",)
        assert bundle.routing_scope == "single_module"

        # Source report retrieval
        rep = bundle.source_report("wiki", "Fiscal")
        assert rep is not None
        assert rep.status == "completed"
        assert len(rep.origin_reports) == 2

        # Round-trip dictionary
        d = bundle.to_dict()
        assert d["profile"]["query"] == bundle.profile.query
        assert len(d["candidates"]) == 2
        assert d["source_origin_counts"] == {"vrwiki": 1, "endoo": 1}

    def test_bundle_origins_remain_independent(self) -> None:
        bundle = synthetic_evidence_bundle(include_endoo=True)
        origins = {c.source_origin for c in bundle.candidates}
        assert "vrwiki" in origins
        assert "endoo" in origins
        assert any(c.evidence_id.startswith("ev-vrwiki") for c in bundle.candidates)
        assert any(c.evidence_id.startswith("ev-endoo") for c in bundle.candidates)


# ---------------------------------------------------------------------------
# 3. KnowledgeRouter Contract & Origin Independence Execution
# ---------------------------------------------------------------------------

class TestKnowledgeRouterContract:
    @pytest.fixture
    def router_env(self, tmp_path: Path):
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        db = MaryDatabase(settings.database_path, root=settings.root)
        # Seed vrwiki document
        db.upsert_document(KnowledgeDocument(
            source="wiki",
            source_id="sped-vrwiki",
            source_origin="vrwiki",
            title="SPED Fiscal VRWiki",
            url="https://wiki.vr.internal/sped",
            markdown="Documentação sobre SPED Fiscal no VRWiki com regras de ICMS.",
            module="Fiscal",
            review_status="approved",
            content_hash="h-vrwiki-1",
        ))
        # Seed endoo document
        db.upsert_document(KnowledgeDocument(
            source="wiki",
            source_id="sped-endoo",
            source_origin="endoo",
            title="SPED Fiscal Endoo",
            url="https://endoo.internal/sped",
            markdown="Documentação sobre SPED Fiscal no Endoo com notas técnicas.",
            module="Fiscal",
            review_status="approved",
            content_hash="h-endoo-1",
        ))
        router = KnowledgeRouter(db, settings.root)
        return router, db

    def test_knowledge_router_signatures(self) -> None:
        # Verify exact signature contracts on KnowledgeRouter
        sig_search = inspect.signature(KnowledgeRouter.search)
        assert "query" in sig_search.parameters
        assert "source" in sig_search.parameters
        assert "module" in sig_search.parameters
        assert "limit" in sig_search.parameters

        sig_route = inspect.signature(KnowledgeRouter.route)
        assert "query" in sig_route.parameters

        sig_refine = inspect.signature(KnowledgeRouter.refine)
        assert "bundle" in sig_refine.parameters
        assert "query" in sig_refine.parameters

    def test_knowledge_router_search_and_route_origin_separation(self, router_env) -> None:
        router, _db = router_env

        # 1. Test search() contract: returns structured dict
        search_res = router.search("SPED Fiscal", limit=5)
        assert isinstance(search_res, dict)
        assert "results" in search_res
        assert "total" in search_res
        assert "query" in search_res
        assert search_res["total"] >= 2

        results = search_res["results"]
        origins = {r.get("source_origin") for r in results}
        assert "vrwiki" in origins
        assert "endoo" in origins

        # 2. Test route() contract: returns EvidenceBundle
        bundle = router.route("SPED Fiscal")
        assert isinstance(bundle, EvidenceBundle)
        assert len(bundle.candidates) >= 2
        # Assert separation of origins in bundle
        assert bundle.source_origin_counts.get("vrwiki", 0) >= 1
        assert bundle.source_origin_counts.get("endoo", 0) >= 1

        # 3. Test refine() contract: returns refined EvidenceBundle
        refined = router.refine(bundle, "SPED Fiscal nota fiscal")
        assert isinstance(refined, EvidenceBundle)


# ---------------------------------------------------------------------------
# 4. Adapter Protocol Normalization (Native Protocol -> RuntimeEvent)
# ---------------------------------------------------------------------------

class TestProviderProtocolNormalization:
    def test_codex_protocol_normalization(self) -> None:
        cdx = CodexProvider.__new__(CodexProvider)
        cdx._state_lock = threading.RLock()
        cdx._assistant_item_phases = {}
        cdx._assistant_item_keys = {}
        cdx._native_to_local = {"thread-100": "c-cdx"}
        cdx._active_turns = {}
        cdx._completed_turn_ids = {}
        cdx._item_turn_ids = {}
        events: list[RuntimeEvent] = []
        cdx._callbacks = {"c-cdx": events.append}

        messages = [
            {"method": "turn/started", "params": {"threadId": "thread-100", "turn": {"id": "turn-1", "status": "in_progress"}}},
            {"method": "thread/tokenUsage/updated", "params": {"threadId": "thread-100", "tokenUsage": {"total": 500, "input": 400, "output": 100}}},
            {"method": "item/started", "params": {"threadId": "thread-100", "turnId": "turn-1", "item": {"id": "i-1", "type": "agentMessage", "phase": "commentary", "text": ""}}},
            {"method": "item/completed", "params": {"threadId": "thread-100", "turnId": "turn-1", "item": {"id": "i-1", "type": "agentMessage", "phase": "commentary", "text": "Comentário."}}},
            {"method": "item/fileChange/patchUpdated", "params": {"threadId": "thread-100", "turnId": "turn-1", "itemId": "p-1", "changes": [{"path": "a.py"}]}},
            {"method": "turn/completed", "params": {"threadId": "thread-100", "turn": {"id": "turn-1", "status": "completed"}}},
        ]
        for m in messages:
            cdx._handle_server_message(m)

        kinds = [e.kind for e in events]
        assert kinds == ["turn_started", "token_usage", "assistant_started", "assistant_completed", "tool_event", "turn_completed"]
        token_ev = next(e for e in events if e.kind == "token_usage")
        assert token_ev.payload.get("tokenUsage", {}).get("total") == 500

    def test_claude_protocol_normalization(self) -> None:
        cld = ClaudeProvider.__new__(ClaudeProvider)
        cld._state_lock = threading.RLock()
        cld._active = {}
        events: list[RuntimeEvent] = []
        proc = MagicMock()
        proc.stdout = claude_raw_protocol_lines()
        proc.stderr = []
        proc.wait.return_value = 0

        cld._consume("c-cld", proc, events.append)
        kinds = [e.kind for e in events]
        assert "turn_started" in kinds
        assert "assistant_started" in kinds
        assert "assistant_delta" in kinds
        assert "assistant_completed" in kinds
        assert "tool_event" in kinds
        assert "token_usage" in kinds
        assert "turn_completed" in kinds

    def test_opencode_protocol_normalization(self) -> None:
        opc = OpenCodeProvider.__new__(OpenCodeProvider)
        opc._state_lock = threading.RLock()
        opc._sessions = {}
        opc._active = {}
        events: list[RuntimeEvent] = []
        proc = MagicMock()
        proc.stdout = opencode_raw_protocol_lines()
        proc.stderr = []
        proc.wait.return_value = 0

        opc._consume("c-opc", "native-1", proc, events.append)
        kinds = [e.kind for e in events]
        assert "turn_started" in kinds
        assert "native_session_started" in kinds
        assert "assistant_started" in kinds
        assert "assistant_delta" in kinds
        assert "tool_event" in kinds
        assert "assistant_completed" in kinds
        assert "turn_completed" in kinds

    def test_antigravity_protocol_normalization(self) -> None:
        agy = AntigravityProvider.__new__(AntigravityProvider)
        agy._lock = threading.RLock()
        events: list[RuntimeEvent] = []
        state = {"client": None, "session": "sess-1", "cancelled": False, "text": False, "replaying": False}

        updates = [
            ("session/update", {"sessionId": "sess-1", "update": {"sessionUpdate": "tool_call", "title": "vr_search"}}),
            ("session/update", {"sessionId": "sess-1", "update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "Pensando..."}}}),
            ("session/update", {"sessionId": "sess-1", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Resposta ACP."}}}),
            ("session/update", {"sessionId": "sess-1", "update": {"sessionUpdate": "usage_update", "inputTokens": 500, "outputTokens": 80, "used": 580}}),
        ]
        for method, params in updates:
            agy._update("c-agy", state, events.append, method, params)

        kinds = [e.kind for e in events]
        assert kinds == ["tool_event", "reasoning_delta", "assistant_delta", "token_usage"]


# ---------------------------------------------------------------------------
# 5. Provider Synthetic Event Streams Validation
# ---------------------------------------------------------------------------

class TestProviderSyntheticLifecycles:
    @pytest.fixture
    def test_db(self, tmp_path: Path):
        settings = MarySettings(
            app_dir=(tmp_path / "app").resolve(),
            root=(tmp_path / "mary").resolve(),
            old_root=(tmp_path / "old").resolve(),
        )
        settings.ensure_dirs()
        db = MaryDatabase(settings.database_path, root=settings.root)
        cid = db.create_conversation("Teste V2", "codex", "gpt-5", Path("."))
        orch = ChatOrchestrator(settings, db)
        return orch, db, cid

    def test_codex_synthetic_events_execution(self, test_db) -> None:
        orch, db, cid = test_db
        events = codex_synthetic_turn_events(cid)
        # Assert fixtures include tool_event and token_usage
        assert any(e.kind == "tool_event" for e in events)
        assert any(e.kind == "token_usage" for e in events)

        # Dispatch events through orchestrator
        for ev in events:
            orch._handle_event(ev)

        orch._turn_finalizer_executor.shutdown(wait=True)

        # Verify assistant message was saved
        messages = [m for m in db.messages(cid) if m["role"] == "assistant"]
        assert len(messages) >= 1
        # Verify tool_event was logged in db
        with db.connect() as conn:
            db_events = [r[0] for r in conn.execute("SELECT kind FROM runtime_events WHERE conversation_id = ?", (cid,)).fetchall()]
        assert "tool_event" in db_events
        assert "token_usage" in db_events
        # Verify token aggregation in conversation
        conv = db.get_conversation(cid)
        assert int(conv["context_used_tokens"] or 0) > 0

    def test_claude_synthetic_events_execution(self, test_db) -> None:
        orch, db, cid = test_db
        events = claude_synthetic_turn_events(cid)
        assert any(e.kind == "tool_event" for e in events)
        assert any(e.kind == "token_usage" for e in events)

        for ev in events:
            orch._handle_event(ev)

        orch._turn_finalizer_executor.shutdown(wait=True)

        messages = [m for m in db.messages(cid) if m["role"] == "assistant"]
        assert len(messages) >= 1

        with db.connect() as conn:
            db_events = [r[0] for r in conn.execute("SELECT kind FROM runtime_events WHERE conversation_id = ?", (cid,)).fetchall()]
        assert "tool_event" in db_events
        assert "token_usage" in db_events
        conv = db.get_conversation(cid)
        assert int(conv["context_used_tokens"] or 0) > 0

    def test_opencode_synthetic_events_execution(self, test_db) -> None:
        orch, db, cid = test_db
        events = opencode_synthetic_turn_events(cid)
        assert any(e.kind == "tool_event" for e in events)
        assert any(e.kind == "token_usage" for e in events)

        for ev in events:
            orch._handle_event(ev)

        orch._turn_finalizer_executor.shutdown(wait=True)

        messages = [m for m in db.messages(cid) if m["role"] == "assistant"]
        assert len(messages) >= 1

        with db.connect() as conn:
            db_events = [r[0] for r in conn.execute("SELECT kind FROM runtime_events WHERE conversation_id = ?", (cid,)).fetchall()]
        assert "tool_event" in db_events
        assert "token_usage" in db_events
        conv = db.get_conversation(cid)
        assert int(conv["context_used_tokens"] or 0) > 0

    def test_antigravity_synthetic_events_implicit_start(self, test_db) -> None:
        orch, db, cid = test_db
        events = antigravity_synthetic_turn_events(cid)
        assert any(e.kind == "tool_event" for e in events)
        assert any(e.kind == "token_usage" for e in events)
        orch._pending_response_modes[cid] = "native"

        for ev in events:
            orch._handle_event(ev)

        orch._turn_finalizer_executor.shutdown(wait=True)

        # Antigravity emits deltas without assistant_started; finalized on turn_completed.
        # Must assert exact message count and content without ambiguous >= 1.
        messages = [m for m in db.messages(cid) if m["role"] == "assistant"]
        assert len(messages) == 1
        expected_text = "Processando dados pelo modelo Gemini...Análise concluída pelo Antigravity."
        assert messages[0]["content"] == expected_text

        with db.connect() as conn:
            db_events = [r[0] for r in conn.execute("SELECT kind FROM runtime_events WHERE conversation_id = ?", (cid,)).fetchall()]
        assert "tool_event" in db_events
        assert "token_usage" in db_events
        conv = db.get_conversation(cid)
        assert int(conv["context_used_tokens"] or 0) > 0


# ---------------------------------------------------------------------------
# 6. AgentProvider Contract Compliance
# ---------------------------------------------------------------------------

class TestAgentProviderContract:
    def test_all_providers_inherit_agent_provider(self) -> None:
        providers = [CodexProvider, ClaudeProvider, OpenCodeProvider, AntigravityProvider]
        for p in providers:
            assert issubclass(p, AgentProvider)

    def test_agent_provider_required_and_optional_methods(self) -> None:
        # Abstract methods that subclasses MUST implement
        abstract_methods = set(getattr(AgentProvider, "__abstractmethods__", set()))
        expected_abstract = {
            "available",
            "list_models",
            "start_conversation",
            "resume_conversation",
            "send_message",
            "interrupt",
            "approve_action",
            "close",
        }
        assert expected_abstract == abstract_methods

        # Concrete default methods on base class
        concrete_methods = {
            "list_collaboration_modes",
            "list_mcp_tools",
            "list_skills",
            "update_settings",
            "archive_thread",
            "unarchive_thread",
            "delete_thread",
            "fork_thread",
            "release_conversation",
        }
        for name in concrete_methods:
            assert hasattr(AgentProvider, name)
            assert name not in abstract_methods

        # Verify exact signatures of abstract methods
        sig_start = inspect.signature(AgentProvider.start_conversation)
        assert list(sig_start.parameters.keys()) == [
            "self", "conversation_id", "model", "effort", "workspace", "options",
        ]
        assert sig_start.parameters["options"].default is None

        sig_resume = inspect.signature(AgentProvider.resume_conversation)
        assert list(sig_resume.parameters.keys()) == [
            "self", "conversation_id", "native_id", "model", "effort", "workspace", "options",
        ]
        assert sig_resume.parameters["options"].default is None

        sig_send = inspect.signature(AgentProvider.send_message)
        expected_send_params = [
            "self", "conversation_id", "native_id", "model", "effort", "workspace",
            "message", "callback", "options", "skills", "image_paths",
        ]
        assert list(sig_send.parameters.keys()) == expected_send_params

        # Verify exact signatures and default returns of concrete methods
        sig_skills = inspect.signature(AgentProvider.list_skills)
        assert list(sig_skills.parameters.keys()) == ["self", "workspace", "force_reload"]
        assert sig_skills.parameters["force_reload"].default is False

        sig_settings = inspect.signature(AgentProvider.update_settings)
        assert list(sig_settings.parameters.keys()) == ["self", "conversation_id", "native_id", "workspace", "options"]

        sig_fork = inspect.signature(AgentProvider.fork_thread)
        assert list(sig_fork.parameters.keys()) == [
            "self", "conversation_id", "native_id", "last_turn_id", "workspace", "options",
        ]

        sig_release = inspect.signature(AgentProvider.release_conversation)
        assert list(sig_release.parameters.keys()) == ["self", "conversation_id", "native_id", "delete_native"]
        assert sig_release.parameters["delete_native"].default is False

        # Test base behavior with a concrete mock subclass
        class ConcreteProvider(AgentProvider):
            name = "concrete_mock"
            def available(self) -> bool: return True
            def list_models(self) -> list[dict[str, Any]]: return []
            def start_conversation(self, conversation_id: str, model: str, effort: str, workspace: Path, options: Any = None) -> str: return "n-1"
            def resume_conversation(self, conversation_id: str, native_id: str, model: str, effort: str, workspace: Path, options: Any = None) -> str: return native_id
            def send_message(self, *args, **kwargs) -> None: pass
            def interrupt(self, conversation_id: str) -> None: pass
            def approve_action(self, *args, **kwargs) -> None: pass
            def close(self) -> None: pass

        mock_prov = ConcreteProvider()
        # list_collaboration_modes returns Build and Plan
        modes = mock_prov.list_collaboration_modes()
        assert len(modes) == 2
        assert modes[0]["mode"] == "default" and modes[0]["name"] == "Build"
        assert modes[1]["mode"] == "plan" and modes[1]["name"] == "Plan"

        # list_skills returns dict with skills and errors lists
        skills_res = mock_prov.list_skills(Path("."))
        assert skills_res == {"skills": [], "errors": []}

        # fork_thread returns empty string on base
        assert mock_prov.fork_thread("c1", "n1", "t1", Path("."), None) == ""

        # release_conversation calls delete_thread when delete_native=True
        mock_prov.delete_thread = MagicMock()
        mock_prov.release_conversation("c1", "n1", delete_native=True)
        mock_prov.delete_thread.assert_called_once_with("n1")


# ---------------------------------------------------------------------------
# 7. Frontend ChatBridge Public QML Contract (QMetaObject Introspection)
# ---------------------------------------------------------------------------

class TestChatBridgeQMLContract:
    def test_bridge_qmetaobject_properties_and_signals(self) -> None:
        from vrsoft_extractor.mary.frontend.chat import ChatBridge

        meta = ChatBridge.staticMetaObject

        # Expected properties with their Qt types and notify signals
        expected_props = {
            "turnRunning": ("bool", b"stateChanged()"),
            "vrMode": ("QString", b"stateChanged()"),
            "statusText": ("QString", b"stateChanged()"),
            "activitySteps": ("QVariantList", b"stateChanged()"),
            "traceItems": ("QVariantList", b"stateChanged()"),
            "conversations": ("QObject*", None),
            "messages": ("QObject*", None),
        }

        for prop_name, (expected_type, expected_signal) in expected_props.items():
            idx = meta.indexOfProperty(prop_name)
            assert idx >= 0, f"QML property {prop_name} not exposed on ChatBridge MetaObject"
            prop = meta.property(idx)
            assert prop.typeName() == expected_type, f"Property {prop_name} type {prop.typeName()} != {expected_type}"
            if expected_signal:
                assert prop.hasNotifySignal(), f"Property {prop_name} missing notify signal"
                assert bytes(prop.notifySignal().methodSignature()) == expected_signal

        # Introspect Q_INVOKABLE methods / slots required by ChatPreview.qml
        method_names = [bytes(meta.method(i).name()).decode() for i in range(meta.methodCount())]
        required_invokables = [
            "sendMessage",
            "stopTurn",
            "setVrMode",
            "cycleVrMode",
            "startNewChat",
        ]
        for name in required_invokables:
            assert name in method_names, f"Missing Q_INVOKABLE method {name} on ChatBridge"

        # Verify exact signature of ChatBridge.sendMessage (takes ONLY text)
        sig_send_message = inspect.signature(ChatBridge.sendMessage)
        assert list(sig_send_message.parameters.keys()) == ["self", "text"]

"""Synthetic representative events for the 4 providers and V2 contracts.

This module provides deterministic fixture streams for:
- Codex provider lifecycle and raw JSON-RPC protocol
- Claude provider lifecycle and raw NDJSON protocol
- OpenCode provider lifecycle and raw NDJSON protocol
- Antigravity provider lifecycle and raw stream-json protocol
- Multi-message intermediate assistant turns
- EvidenceBundle and QueryProfile synthetic contracts
"""
from __future__ import annotations

import json
from typing import Any

from vrsoft_extractor.mary.models import (
    EvidenceBundle,
    EvidenceCandidate,
    ModuleRoutingDecision,
    OriginSearchReport,
    QueryProfile,
    RuntimeEvent,
    SourceSearchReport,
)


def codex_synthetic_turn_events(
    conversation_id: str = "conv-codex-1",
    turn_id: str = "turn-cdx-100",
    item_id_1: str = "item-cdx-1",
    item_id_2: str = "item-cdx-2",
) -> list[RuntimeEvent]:
    """Representative event stream emitted during a Codex provider turn with multi-message."""
    return [
        RuntimeEvent(
            conversation_id,
            "turn_started",
            payload={"turn": {"id": turn_id, "status": "in_progress"}},
        ),
        # Message 1: commentary / intermediate
        RuntimeEvent(
            conversation_id,
            "assistant_started",
            payload={"itemId": item_id_1, "phase": "commentary"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Analisando requisição...",
            payload={"itemId": item_id_1, "phase": "commentary"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_completed",
            payload={"itemId": item_id_1, "phase": "commentary", "final_text": "Analisando requisição..."},
        ),
        # Tool event normalized by Codex adapter
        RuntimeEvent(
            conversation_id,
            "tool_event",
            "vr_search: concluído",
            payload={
                "lifecycle": "item/completed",
                "item": {"id": "tool-1", "type": "toolCall", "tool": "vr_search", "status": "completed"},
            },
        ),
        # Message 2: final answer
        RuntimeEvent(
            conversation_id,
            "assistant_started",
            payload={"itemId": item_id_2, "phase": "final"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Aqui está o resultado detalhado.",
            payload={"itemId": item_id_2, "phase": "final"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_completed",
            payload={"itemId": item_id_2, "phase": "final", "final_text": "Aqui está o resultado detalhado."},
        ),
        RuntimeEvent(
            conversation_id,
            "token_usage",
            payload={
                "tokenUsage": {
                    "last": {
                        "inputTokens": 1500,
                        "outputTokens": 320,
                        "reasoningOutputTokens": 80,
                        "cachedInputTokens": 400,
                        "cacheWriteInputTokens": 0,
                        "totalTokens": 1900,
                    }
                }
            },
        ),
        RuntimeEvent(
            conversation_id,
            "turn_completed",
            payload={"turn": {"id": turn_id, "status": "completed"}},
        ),
    ]


def claude_synthetic_turn_events(
    conversation_id: str = "conv-claude-1",
    message_id_1: str = "msg-cld-1",
    message_id_2: str = "msg-cld-2",
) -> list[RuntimeEvent]:
    """Representative event stream emitted during a Claude provider turn."""
    return [
        RuntimeEvent(conversation_id, "turn_started"),
        # Message 1
        RuntimeEvent(
            conversation_id,
            "assistant_started",
            payload={"itemId": message_id_1, "phase": "commentary"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Consultando documentação...",
            payload={"itemId": message_id_1, "phase": "commentary"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_completed",
            payload={"itemId": message_id_1, "phase": "commentary", "final_text": "Consultando documentação..."},
        ),
        # Tool event normalized by Claude adapter
        RuntimeEvent(
            conversation_id,
            "tool_event",
            "search",
            payload={"type": "tool_use", "name": "search", "input": {"query": "pedido de compra"}},
        ),
        # Message 2
        RuntimeEvent(
            conversation_id,
            "assistant_started",
            payload={"itemId": message_id_2, "phase": "final"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Resposta conclusiva via Claude.",
            payload={"itemId": message_id_2, "phase": "final"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_completed",
            payload={"itemId": message_id_2, "phase": "final", "final_text": "Resposta conclusiva via Claude."},
        ),
        RuntimeEvent(
            conversation_id,
            "token_usage",
            payload={
                "tokenUsage": {
                    "last": {
                        "inputTokens": 2100,
                        "outputTokens": 450,
                        "reasoningOutputTokens": 0,
                        "cachedInputTokens": 800,
                        "cacheWriteInputTokens": 100,
                        "totalTokens": 2650,
                    }
                }
            },
        ),
        RuntimeEvent(conversation_id, "turn_completed"),
    ]


def opencode_synthetic_turn_events(
    conversation_id: str = "conv-opencode-1",
    message_id_1: str = "msg-opc-1",
    message_id_2: str = "msg-opc-2",
) -> list[RuntimeEvent]:
    """Representative event stream emitted during an OpenCode provider turn."""
    return [
        RuntimeEvent(conversation_id, "turn_started"),
        RuntimeEvent(
            conversation_id,
            "assistant_started",
            payload={"itemId": message_id_1, "phase": "commentary"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Iniciando verificação no OpenCode...",
            payload={"itemId": message_id_1, "phase": "commentary"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_completed",
            payload={"itemId": message_id_1, "phase": "commentary", "final_text": "Iniciando verificação no OpenCode..."},
        ),
        # Tool event normalized by OpenCode adapter
        RuntimeEvent(
            conversation_id,
            "tool_event",
            "grep",
            payload={"type": "tool_use", "tool": "grep", "query": "PedidoCompraDAO"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_started",
            payload={"itemId": message_id_2, "phase": "final"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Estrutura localizada com sucesso.",
            payload={"itemId": message_id_2, "phase": "final"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_completed",
            payload={"itemId": message_id_2, "phase": "final", "final_text": "Estrutura localizada com sucesso."},
        ),
        RuntimeEvent(
            conversation_id,
            "token_usage",
            payload={
                "tokenUsage": {
                    "last": {
                        "inputTokens": 1800,
                        "outputTokens": 290,
                        "reasoningOutputTokens": 0,
                        "cachedInputTokens": 200,
                        "cacheWriteInputTokens": 0,
                        "totalTokens": 2090,
                    }
                }
            },
        ),
        RuntimeEvent(conversation_id, "turn_completed"),
    ]


def antigravity_synthetic_turn_events(
    conversation_id: str = "conv-antigravity-1",
) -> list[RuntimeEvent]:
    """Representative event stream emitted during an Antigravity provider turn."""
    return [
        RuntimeEvent(conversation_id, "turn_started"),
        RuntimeEvent(
            conversation_id,
            "native_session_started",
            payload={"native_id": "agy-sess-42"},
        ),
        RuntimeEvent(
            conversation_id,
            "tool_event",
            "vr_search",
            payload={"step_type": "tool", "tool_name": "vr_search"},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Processando dados pelo modelo Gemini...",
            payload={"step_type": "agent_response", "text_delta": "Processando dados pelo modelo Gemini..."},
        ),
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Análise concluída pelo Antigravity.",
            payload={"step_type": "agent_response", "text_delta": "Análise concluída pelo Antigravity."},
        ),
        RuntimeEvent(
            conversation_id,
            "token_usage",
            payload={
                "tokenUsage": {
                    "last": {
                        "inputTokens": 1100,
                        "outputTokens": 180,
                        "reasoningOutputTokens": 40,
                        "cachedInputTokens": 300,
                        "cacheWriteInputTokens": 0,
                        "totalTokens": 1320,
                    }
                }
            },
        ),
        RuntimeEvent(conversation_id, "turn_completed"),
    ]


# ---------------------------------------------------------------------------
# Raw Protocol Fixtures (Native Protocol -> Adapter Conversion Input)
# ---------------------------------------------------------------------------

def codex_raw_protocol_messages(turn_id: str = "turn-100", item_id: str = "item-1") -> list[dict[str, Any]]:
    """Raw JSON-RPC messages received from Codex app-server stdout."""
    return [
        {"method": "turn/started", "params": {"turn": {"id": turn_id, "status": "in_progress"}}},
        {
            "method": "item/started",
            "params": {
                "turnId": turn_id,
                "item": {"id": item_id, "type": "agentMessage", "phase": "commentary", "text": ""},
            },
        },
        {
            "method": "item/completed",
            "params": {
                "turnId": turn_id,
                "item": {
                    "id": item_id,
                    "type": "agentMessage",
                    "phase": "commentary",
                    "text": "Análise inicial em andamento.",
                },
            },
        },
        {
            "method": "item/fileChange/patchUpdated",
            "params": {"turnId": turn_id, "itemId": "tool-patch-1", "changes": [{"path": "src/main.py"}]},
        },
        {"method": "turn/completed", "params": {"turn": {"id": turn_id, "status": "completed"}}},
    ]


def claude_raw_protocol_lines(message_id: str = "msg-cld-100") -> list[str]:
    """Raw NDJSON lines received from Claude CLI stdout."""
    events = [
        {"type": "stream_event", "event": {"type": "message_start", "message": {"id": message_id}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Resposta via Claude."}}},
        {"type": "stream_event", "event": {"type": "message_stop"}},
        {
            "type": "assistant",
            "message": {
                "id": message_id,
                "content": [
                    {"type": "tool_use", "name": "vr_search", "input": {"query": "SPED"}},
                ],
            },
        },
        {
            "type": "result",
            "result": "Resposta via Claude.",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 150,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 0,
            },
        },
    ]
    return [json.dumps(ev) for ev in events]


def opencode_raw_protocol_lines() -> list[str]:
    """Raw NDJSON lines received from OpenCode CLI stdout."""
    events = [
        {"sessionID": "opc-sess-99"},
        {"type": "text", "part": {"messageID": "opc-m1", "id": "p1", "text": "Pesquisando estrutura..."}},
        {"type": "tool_use", "part": {"tool": "grep_code", "pattern": "SpedFiscal"}},
        {
            "type": "step_finish",
            "usage": {"input_tokens": 800, "output_tokens": 120, "cache_read": 100},
        },
    ]
    return [json.dumps(ev) for ev in events]


def antigravity_raw_protocol_lines() -> list[str]:
    """Raw stream-json lines received from Antigravity agy CLI stdout."""
    events = [
        {
            "event": "step_update",
            "step": {"step_type": "tool", "tool_name": "vr_search", "status": "done"},
        },
        {
            "event": "step_update",
            "step": {"step_type": "agent_response", "text_delta": "Dados recuperados com sucesso."},
        },
        {
            "event": "result",
            "result": {
                "status": "SUCCESS",
                "response": "Dados recuperados com sucesso.",
                "usage": {
                    "input_tokens": 950,
                    "output_tokens": 130,
                    "thinking_tokens": 20,
                    "cache_read_tokens": 100,
                    "total_tokens": 1100,
                },
            },
        },
    ]
    return [json.dumps(ev) for ev in events]


# ---------------------------------------------------------------------------
# Synthetic Knowledge / Evidence fixtures
# ---------------------------------------------------------------------------

def synthetic_query_profile(
    query: str = "Como emitir nota fiscal no modulo Fiscal?",
    answer_type: str = "process",
    module: str = "Fiscal",
) -> QueryProfile:
    return QueryProfile(
        query=query,
        intents={"process": 0.88, "functional": 0.15},
        module=module,
        answer_type=answer_type,
        terms=("emitir", "nota", "fiscal"),
    )


def synthetic_evidence_candidate(
    evidence_id: str = "ev-1",
    source: str = "wiki",
    source_origin: str = "vrwiki",
    module: str = "Fiscal",
    confidence: float = 0.92,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=evidence_id,
        source=source,
        source_id=f"doc-{evidence_id}",
        document_id=1,
        chunk_id=1,
        title=f"Manual do {module} ({source_origin})",
        heading="Procedimento",
        content_type="procedure",
        module=module,
        product="",
        excerpt=f"Passo a passo no módulo {module} da origem {source_origin}.",
        url=f"https://wiki.vr.internal/{module}/{evidence_id}",
        local_path=f"conhecimento/{module}/wiki_{evidence_id}.md",
        source_origin=source_origin,
        confidence=confidence,
        score=confidence,
        matched_terms=("emitir", "nota"),
    )


def synthetic_evidence_bundle(
    query: str = "Como emitir nota fiscal no modulo Fiscal?",
    include_endoo: bool = True,
) -> EvidenceBundle:
    profile = synthetic_query_profile(query=query)
    c1 = synthetic_evidence_candidate("ev-vrwiki-1", "wiki", "vrwiki", "Fiscal", 0.95)
    candidates = [c1]
    origin_reports = [
        OriginSearchReport("wiki", "vrwiki", "completed", candidates_examined=1),
    ]

    if include_endoo:
        c2 = synthetic_evidence_candidate("ev-endoo-1", "wiki", "endoo", "Fiscal", 0.88)
        candidates.append(c2)
        origin_reports.append(OriginSearchReport("wiki", "endoo", "completed", candidates_examined=1))

    source_reports = (
        SourceSearchReport(
            source="wiki",
            status="completed",
            module="Fiscal",
            candidates_examined=len(candidates),
            origin_reports=tuple(origin_reports),
        ),
    )

    module_routing = (
        ModuleRoutingDecision(
            module="Fiscal",
            selected=True,
            confidence=0.92,
            reasons=("fiscal", "nota"),
        ),
    )

    return EvidenceBundle(
        profile=profile,
        candidates=tuple(candidates),
        groups=(),
        conflicts=(),
        source_reports=source_reports,
        module_routing=module_routing,
        missing_sources=(),
        warnings=(),
    )

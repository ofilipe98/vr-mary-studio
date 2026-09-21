"""Behavioral regressions from the real OpenCode tool envelopes."""
import json
from dataclasses import asdict

import pytest

from vrsoft_extractor.mary.chat_tools import run_bounded_vr_tool
from vrsoft_extractor.mary.code_context import application_context_warning
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.provider_adapters.tool_normalizer import normalize_opencode_event
from vrsoft_extractor.mary.tool_activity import ToolLifecycleReducer
from vrsoft_extractor.mary.tool_presentation import DEFAULT_PRESENTATION_REGISTRY


def test_terminal_opencode_mcp_and_persisted_history_keep_duration_and_error():
    payload = {"type": "tool_use", "part": {"tool": "vr-mary-studio_vr_read", "callID": "call_1",
        "state": {"status": "error", "input": {"reference": "example.Fiscal"},
                  "error": json.dumps({"state": "no_results", "error": "Fonte fora do contexto"}),
                  "time": {"start": 1000, "end": 38361}}}}
    event = normalize_opencode_event(payload)
    activity = ToolLifecycleReducer().reduce(event)
    view = DEFAULT_PRESENTATION_REGISTRY.format(activity)
    assert view.item_type == "mcpToolCall"
    assert view.duration_label == "37.4s"
    assert view.error_summary == "Fonte fora do contexto"
    assert '"reference": "example.Fiscal"' in view.detail
    assert "Fonte fora do contexto" not in view.detail
    saved = asdict(event)
    saved["type"] = "unknown"  # Old database entries must also render correctly.
    payload["canonical_event"] = saved
    restored = DEFAULT_PRESENTATION_REGISTRY.format_from_event(RuntimeEvent("conv", "tool_event", payload=payload))
    assert restored.item_type == "mcpToolCall"
    assert restored.duration_label == view.duration_label


class Pages:
    def read(self, reference, *, cursor, limit, **scope):
        assert scope["application_contexts"] == [{"app_id": "vratacarejo"}]
        text = "á" * 9000
        content = text[cursor:cursor + limit]
        return {"reference": reference, "content": content, "has_more": cursor + len(content) < len(text),
                "next_cursor": cursor + len(content), "cursor": cursor}

    def search(self, query, *, limit, cursor=0, **scope):
        return {"results": [{"reference": f"kb:{i}", "excerpt": "x" * 500} for i in range(cursor, cursor + limit)],
                "has_more": True, "next_cursor": cursor + limit}


def test_budget_reduces_read_page_without_losing_continuation():
    scope = {"application_contexts": [{"app_id": "vratacarejo"}]}
    first = run_bounded_vr_tool("vr_read", {"reference": "example.Fiscal"}, Pages(), 1800, **scope)
    assert len(first.text) <= 1800
    assert first.parsed["budget"]["page_reduced"]
    assert first.parsed["next_cursor"] == len(first.parsed["content"])
    second = run_bounded_vr_tool("vr_read", {"reference": "example.Fiscal", "cursor": first.parsed["next_cursor"]}, Pages(), 1800, **scope)
    assert second.parsed["cursor"] == len(first.parsed["content"])
    assert second.parsed["reference"] == first.parsed["reference"]


def test_budget_reduces_search_and_reports_exhaustion():
    result = run_bounded_vr_tool("vr_search", {"query": "fiscal", "limit": 6, "cursor": 4}, Pages(), 1700)
    assert len(result.text) <= 1700
    assert result.parsed["next_cursor"] == 4 + len(result.parsed["results"])
    assert result.parsed["results"][0]["reference"] == "kb:4"
    exhausted = run_bounded_vr_tool("vr_search", {"query": "fiscal"}, Pages(), 10)
    assert exhausted.parsed["state"] == "budget_exhausted"
    assert exhausted.parsed["remaining_chars"] == 10


@pytest.mark.parametrize("app,warning", [("vrmaster", True), ("vratacarejo", False)])
def test_product_stack_context_is_explicit(app, warning):
    contexts = [{"app_id": app, "version": "1.0"}]
    assert bool(application_context_warning("vratacarejo.service.Nota.calcular(Nota.java:374)", contexts)) == warning
    assert contexts == [{"app_id": app, "version": "1.0"}]
    assert not application_context_warning("br.com.vrsoftware.vrnfe.Nota.calcular(Nota.java:374)", contexts)


def test_mcp_transport_adapts_to_remaining_turn_budget(tmp_path, monkeypatch):
    from io import StringIO
    from vrsoft_extractor.mary import mcp_server

    class Service(Pages):
        def search(self, query, *, limit, **scope):
            return {"results": [{"reference": f"kb:{i}", "excerpt": "x" * 4500}
                                for i in range(limit)], "has_more": True, "next_cursor": limit}

    monkeypatch.setattr(mcp_server, "MaryDatabase", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "KnowledgeRouter", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "RetrievalService", lambda *a: Service())
    monkeypatch.setattr(mcp_server, "load_scope", lambda path: {"application_contexts": [{"app_id": "vratacarejo"}]})
    requests = [{"id": 1, "method": "tools/call", "params": {
        "name": "vr_search", "arguments": {"query": "fiscal", "limit": 20}}},
        {"id": 2, "method": "tools/call", "params": {
            "name": "vr_read", "arguments": {"reference": "example.Fiscal", "limit": 8000}}}]
    monkeypatch.setattr(mcp_server.sys, "stdin", StringIO("\n".join(json.dumps(r) for r in requests)))
    output = StringIO()
    monkeypatch.setattr(mcp_server.sys, "stdout", output)
    mcp_server.run_mcp_server(tmp_path)
    replies = [json.loads(line)["result"] for line in output.getvalue().splitlines()]
    assert not any(reply["isError"] for reply in replies)
    assert sum(len(reply["content"][0]["text"]) for reply in replies) <= 96000
    read = json.loads(replies[1]["content"][0]["text"])
    assert read["budget"]["page_reduced"] and read["has_more"]
    assert read["next_cursor"] == len(read["content"])

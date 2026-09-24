"""Behavioral regressions from the real OpenCode tool envelopes."""
import json
from dataclasses import asdict

import pytest

from vrsoft_extractor.mary.chat_tools import run_vr_tool
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

    def sources(self, *, limit, cursor=0, **scope):
        return {"state": "available", "results": [{"source_id": str(i)} for i in range(cursor, cursor + limit)],
                "has_more": True, "next_cursor": cursor + limit}


def test_vr_tools_return_requested_pages_and_continuations():
    scope = {"application_contexts": [{"app_id": "vratacarejo"}]}
    first = run_vr_tool(
        "vr_read", {"reference": "example.Fiscal", "limit": 8000}, Pages(), **scope
    )
    assert "budget" not in first.parsed
    assert "remaining_chars" not in first.parsed
    assert len(first.parsed["content"]) == 8000
    assert first.parsed["next_cursor"] == 8000
    assert first.parsed["has_more"]
    second = run_vr_tool(
        "vr_read",
        {"reference": "example.Fiscal", "cursor": first.parsed["next_cursor"], "limit": 8000},
        Pages(),
        **scope,
    )
    assert second.parsed["cursor"] == first.parsed["next_cursor"]
    assert second.parsed["reference"] == first.parsed["reference"]

    search = run_vr_tool(
        "vr_search", {"query": "fiscal", "limit": 20, "cursor": 4}, Pages()
    )
    assert "budget" not in search.parsed
    assert len(search.parsed["results"]) == 20
    assert search.parsed["results"][0]["reference"] == "kb:4"
    assert search.parsed["next_cursor"] == 24
    assert search.parsed["has_more"]


def test_vr_tool_payloads_have_no_turn_budget_state():
    payloads = [
        run_vr_tool("vr_sources", {"limit": 50}, Pages(), application_contexts=[{"app_id": "vratacarejo"}]).parsed,
        run_vr_tool("vr_search", {"query": "fiscal"}, Pages()).parsed,
        run_vr_tool("vr_read", {"reference": "example.Fiscal"}, Pages(), application_contexts=[{"app_id": "vratacarejo"}]).parsed,
    ]
    for payload in payloads:
        assert "budget" not in payload
        assert "remaining_chars" not in payload
        assert payload.get("state") not in {"", "exhausted"}


@pytest.mark.parametrize("app,warning", [("vrmaster", True), ("vratacarejo", False)])
def test_product_stack_context_is_explicit(app, warning):
    contexts = [{"app_id": app, "version": "1.0"}]
    assert bool(application_context_warning("vratacarejo.service.Nota.calcular(Nota.java:374)", contexts)) == warning
    assert contexts == [{"app_id": app, "version": "1.0"}]
    assert not application_context_warning("br.com.vrsoftware.vrnfe.Nota.calcular(Nota.java:374)", contexts)


def test_mcp_transport_allows_vr_responses_over_turn_character_total(tmp_path, monkeypatch):
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
    requests = [
        {
            "id": index,
            "method": "tools/call",
            "params": {
                "name": "vr_read",
                "arguments": {"reference": "example.Fiscal", "limit": 8000},
            },
        }
        for index in range(50)
    ]
    monkeypatch.setattr(mcp_server.sys, "stdin", StringIO("\n".join(json.dumps(r) for r in requests)))
    output = StringIO()
    monkeypatch.setattr(mcp_server.sys, "stdout", output)
    mcp_server.run_mcp_server(tmp_path)
    replies = [json.loads(line)["result"] for line in output.getvalue().splitlines()]
    texts = [reply["content"][0]["text"] for reply in replies]
    assert len(replies) == 50
    assert not any(reply["isError"] for reply in replies)
    assert sum(len(text) for text in texts) > 192_000
    payloads = [json.loads(text) for text in texts]
    assert all("budget" not in payload for payload in payloads)
    assert all("remaining_chars" not in payload for payload in payloads)
    read = payloads[-1]
    assert read["has_more"]
    assert read["next_cursor"] == len(read["content"])


def test_mcp_transport_allows_more_than_forty_vr_calls(tmp_path, monkeypatch):
    from io import StringIO
    from vrsoft_extractor.mary import mcp_server

    monkeypatch.setattr(mcp_server, "MaryDatabase", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "KnowledgeRouter", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "RetrievalService", lambda *a: Pages())
    monkeypatch.setattr(mcp_server, "load_scope", lambda path: {"application_contexts": [{"app_id": "vratacarejo"}]})
    requests = [
        {
            "id": index,
            "method": "tools/call",
            "params": {
                "name": "vr_read",
                "arguments": {"reference": "example.Fiscal", "limit": 8000},
            },
        }
        for index in range(50)
    ]
    monkeypatch.setattr(mcp_server.sys, "stdin", StringIO("\n".join(json.dumps(r) for r in requests)))
    output = StringIO()
    monkeypatch.setattr(mcp_server.sys, "stdout", output)
    mcp_server.run_mcp_server(tmp_path)
    replies = [json.loads(line)["result"] for line in output.getvalue().splitlines()]
    assert len(replies) == 50
    assert not any(reply["isError"] for reply in replies)


def _mcp_replies(tmp_path, monkeypatch, requests, **kwargs):
    from io import StringIO
    from vrsoft_extractor.mary import mcp_server

    monkeypatch.setattr(mcp_server, "MaryDatabase", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "KnowledgeRouter", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "RetrievalService", lambda *a: Pages())
    monkeypatch.setattr(mcp_server, "load_scope", lambda path: {})
    monkeypatch.setattr(
        mcp_server.sys, "stdin", StringIO("\n".join(json.dumps(r) for r in requests))
    )
    output = StringIO()
    monkeypatch.setattr(mcp_server.sys, "stdout", output)
    mcp_server.run_mcp_server(tmp_path, **kwargs)
    return [json.loads(line)["result"] for line in output.getvalue().splitlines()]


def test_mcp_tools_list_follows_vr_mode(tmp_path, monkeypatch):
    listed = _mcp_replies(
        tmp_path,
        monkeypatch,
        [{"id": 1, "method": "tools/list", "params": {}}],
        vr_tools_enabled=True,
    )
    names = {tool["name"] for tool in listed[0]["tools"]}
    assert names == {"vr_sources", "vr_search", "vr_read"}

    hidden = _mcp_replies(
        tmp_path,
        monkeypatch,
        [{"id": 1, "method": "tools/list", "params": {}}],
        vr_tools_enabled=False,
    )
    assert hidden[0]["tools"] == []


def test_mcp_off_does_not_instantiate_database_router_or_retrieval(tmp_path, monkeypatch):
    from io import StringIO
    from vrsoft_extractor.mary import mcp_server

    def forbidden_constructor(*args, **kwargs):
        raise AssertionError("Construtor de retrieval não deve ser chamado em modo OFF")

    monkeypatch.setattr(mcp_server, "MaryDatabase", forbidden_constructor)
    monkeypatch.setattr(mcp_server, "KnowledgeRouter", forbidden_constructor)
    monkeypatch.setattr(mcp_server, "RetrievalService", forbidden_constructor)
    monkeypatch.setattr(mcp_server, "load_scope", lambda path: {})

    requests = [
        {"id": 1, "method": "initialize", "params": {}},
        {"id": 2, "method": "tools/list", "params": {}},
        {
            "id": 3,
            "method": "tools/call",
            "params": {"name": "vr_search", "arguments": {"query": "sped"}},
        },
    ]
    monkeypatch.setattr(
        mcp_server.sys, "stdin", StringIO("\n".join(json.dumps(r) for r in requests))
    )
    output = StringIO()
    monkeypatch.setattr(mcp_server.sys, "stdout", output)
    mcp_server.run_mcp_server(tmp_path, vr_tools_enabled=False)

    replies = [json.loads(line)["result"] for line in output.getvalue().splitlines()]
    assert len(replies) == 3
    assert replies[1]["tools"] == []
    assert replies[2]["isError"] is True
    assert "modo OFF" in replies[2]["content"][0]["text"]


def test_mcp_off_refuses_vr_tool_without_retrieval(tmp_path, monkeypatch):
    from vrsoft_extractor.mary import mcp_server

    calls: list[tuple] = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("retrieval não deveria executar")

    monkeypatch.setattr(mcp_server, "run_vr_tool", forbidden)
    replies = _mcp_replies(
        tmp_path,
        monkeypatch,
        [
            {
                "id": 1,
                "method": "tools/call",
                "params": {"name": "vr_search", "arguments": {"query": "sped"}},
            }
        ],
        vr_tools_enabled=False,
    )
    assert replies[0]["isError"] is True
    assert "modo OFF" in replies[0]["content"][0]["text"]
    assert calls == []


def test_mcp_off_keeps_only_monitor_tools(tmp_path, monkeypatch):
    from vrsoft_extractor.mary import mcp_server
    from vrsoft_extractor.mary.monitor_adapter import MONITOR_TOOL_NAMES, MonitorToolResult

    class Monitor:
        def execute(self, tool_name, arguments, conversation_id):
            return MonitorToolResult(
                text=json.dumps({"ok": tool_name}), parsed={"ok": tool_name}
            )

    monkeypatch.setattr(mcp_server.MonitorAdapter, "from_path", lambda path: Monitor())
    replies = _mcp_replies(
        tmp_path,
        monkeypatch,
        [
            {"id": 1, "method": "tools/list", "params": {}},
            {
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_connections", "arguments": {}},
            },
        ],
        vr_tools_enabled=False,
        monitor_session_id="00000000-0000-0000-0000-000000000001",
    )
    names = {tool["name"] for tool in replies[0]["tools"]}
    assert names == set(MONITOR_TOOL_NAMES)
    assert replies[1]["isError"] is False


def test_mcp_transport_allows_large_monitor_results_and_later_calls(tmp_path, monkeypatch):
    from io import StringIO
    from vrsoft_extractor.mary import mcp_server
    from vrsoft_extractor.mary.monitor_adapter import MonitorToolResult

    class Monitor:
        def execute(self, tool_name, arguments, conversation_id):
            return MonitorToolResult(
                text=json.dumps({"data": "x" * 5000}),
                parsed={"data": "x" * 5000},
            )

    monkeypatch.setattr(mcp_server, "MaryDatabase", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "KnowledgeRouter", lambda *a, **kw: None)
    monkeypatch.setattr(mcp_server, "RetrievalService", lambda *a: Pages())
    monkeypatch.setattr(mcp_server.MonitorAdapter, "from_path", lambda path: Monitor())
    monkeypatch.setattr(mcp_server, "load_scope", lambda path: {})
    requests = [
        {
            "id": index,
            "method": "tools/call",
            "params": {"name": "get_connections", "arguments": {}},
        }
        for index in range(50)
    ]
    monkeypatch.setattr(mcp_server.sys, "stdin", StringIO("\n".join(json.dumps(r) for r in requests)))
    output = StringIO()
    monkeypatch.setattr(mcp_server.sys, "stdout", output)
    mcp_server.run_mcp_server(tmp_path, monitor_session_id="00000000-0000-0000-0000-000000000001")
    replies = [json.loads(line)["result"] for line in output.getvalue().splitlines()]
    assert len(replies) == 50
    assert not any(reply["isError"] for reply in replies)
    assert sum(len(reply["content"][0]["text"]) for reply in replies) > 192_000

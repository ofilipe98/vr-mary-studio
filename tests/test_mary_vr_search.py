from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from vrsoft_extractor.mary.chat_tools import (
    VR_SEARCH_INPUT_SCHEMA,
    VR_SEARCH_TOOL_NAME,
    run_vr_search,
    validate_tool_arguments,
    vr_search_tool_spec,
)
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.models import KnowledgeDocument, RuntimeEvent
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.retrieval.service import RetrievalService


def _settings(tmp_path: Path) -> MarySettings:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "mary").resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.app_dir.mkdir(parents=True)
    settings.old_root.mkdir(parents=True)
    settings.ensure_dirs()
    return settings


def _seed(database: MaryDatabase) -> None:
    for document in (
        KnowledgeDocument(
            source="wiki",
            source_id="sped-wiki",
            title="SPED Fiscal",
            url="https://wiki.example/sped",
            markdown=(
                "# SPED Fiscal\n\n## Geração\n\nInforme período, loja e destino "
                "e clique em Exportar."
            ),
            module="Fiscal",
            review_status="approved",
            content_hash="sped-wiki",
            local_path="conhecimento/Fiscal/Wiki/sped.md",
        ),
        KnowledgeDocument(
            source="kb",
            source_id="sped-kb",
            title="Como gerar o SPED Fiscal",
            url="https://kb.example/sped",
            markdown="Preencha período, versão, loja e destino e clique em Exportar.",
            module="Fiscal",
            review_status="approved",
            content_hash="sped-kb",
            local_path="conhecimento/Fiscal/KB/sped.md",
        ),
        KnowledgeDocument(
            source="schema",
            source_id="sped-schema",
            title="Tabela SPED Fiscal",
            url="",
            markdown="A tabela sped_fiscal possui id e periodo.",
            module="Fiscal",
            review_status="approved",
            content_hash="sped-schema",
            local_path="conhecimento/Fiscal/Schema/sped.md",
        ),
    ):
        database.upsert_document(document)


def test_vr_search_tool_spec_matches_schema() -> None:
    spec = vr_search_tool_spec()
    assert spec["name"] == VR_SEARCH_TOOL_NAME
    assert spec["type"] == "function"
    assert set(VR_SEARCH_INPUT_SCHEMA["required"]) == {"query"}
    validate_tool_arguments({"query": "como gerar sped"}, VR_SEARCH_INPUT_SCHEMA)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"source": "google", "query": "x"},
        {"module": "RH", "query": "x"},
        {"module": "Fiscal", "query": "x"},
        {"limit": "muito", "query": "x"},
        {"query": "ok", "extra": True},
    ],
)
def test_run_vr_search_rejects_invalid_arguments(arguments: dict[str, Any]) -> None:
    class _Router:
        def search(self, *_args, **_kwargs):  # pragma: no cover - must not run
            raise AssertionError("router não deveria ser chamado")

    with pytest.raises(Exception):
        run_vr_search(arguments, _Router())


def test_vr_search_schema_no_longer_exposes_module() -> None:
    assert "module" not in VR_SEARCH_INPUT_SCHEMA["properties"]
    assert "Fiscal" not in json.dumps(VR_SEARCH_INPUT_SCHEMA)
    with pytest.raises(Exception):
        validate_tool_arguments(
            {"query": "x", "module": "Fiscal"}, VR_SEARCH_INPUT_SCHEMA
        )


def _service(tmp_path: Path) -> RetrievalService:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    _seed(database)
    return RetrievalService(KnowledgeRouter(database, settings.root))


def test_search_without_source_consolidates_documentary_lanes(tmp_path: Path) -> None:
    service = _service(tmp_path)

    payload = service.search("Como gerar SPED Fiscal no VR?", limit=10)

    assert set(payload["source_states"]) == {"wiki", "kb", "schema", "code"}
    assert payload["source_states"]["wiki"] == "available"
    assert payload["source_states"]["kb"] == "available"
    assert payload["source_states"]["schema"] == "available"
    assert payload["total"] >= 3
    assert payload["errors"] == {}


def test_search_without_source_runs_four_lanes_concurrently(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    barrier = threading.Barrier(4)
    original = service._search_tool_lane

    def lane(query, lane_name, **kwargs):
        barrier.wait(timeout=10)
        return original(query, lane_name, **kwargs)

    monkeypatch.setattr(service, "_search_tool_lane", lane)

    payload = service.search("Como gerar SPED Fiscal no VR?", limit=10)

    assert set(payload["source_states"]) == {"wiki", "kb", "schema", "code"}
    assert payload["errors"] == {}


def test_search_without_source_keeps_fixed_lane_order(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    delays = {"wiki": 0.08, "kb": 0.06, "schema": 0.04, "code": 0.02}

    def lane(query, lane_name, **kwargs):
        # Deliberately complete in the inverse order.
        time.sleep(delays[lane_name])
        return (
            [{"reference": f"{lane_name}:1", "source": lane_name}],
            "available",
            "",
        )

    monkeypatch.setattr(service, "_search_tool_lane", lane)

    payload = service.search("x", limit=10)

    assert [row["reference"] for row in payload["results"]] == [
        "wiki:1",
        "kb:1",
        "schema:1",
        "code:1",
    ]


def test_search_without_source_isolates_lane_failure(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)

    def lane(query, lane_name, **kwargs):
        if lane_name == "kb":
            return [], "unavailable", "kb fora do ar"
        return (
            [{"reference": f"{lane_name}:1", "source": lane_name}],
            "available",
            "",
        )

    monkeypatch.setattr(service, "_search_tool_lane", lane)

    payload = service.search("x", limit=10)

    assert payload["errors"] == {"kb": "kb fora do ar"}
    assert payload["source_states"]["kb"] == "unavailable"
    assert payload["source_states"]["wiki"] == "available"
    assert [row["reference"] for row in payload["results"]] == [
        "wiki:1",
        "schema:1",
        "code:1",
    ]


def test_search_with_source_runs_only_that_lane(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path)
    called: list[str] = []

    def lane(query, lane_name, **kwargs):
        called.append(lane_name)
        return (
            [{"reference": f"{lane_name}:1", "source": lane_name}],
            "available",
            "",
        )

    monkeypatch.setattr(service, "_search_tool_lane", lane)

    payload = service.search("x", source="schema")

    assert called == ["schema"]
    assert set(payload["source_states"]) == {"schema"}
    assert [row["reference"] for row in payload["results"]] == ["schema:1"]


def test_search_with_source_document_error_is_reported_per_lane(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)

    def broken(*_args, **_kwargs):
        raise RuntimeError("indice indisponivel")

    monkeypatch.setattr(service, "_prepare_search", broken)

    payload = service.search("sped fiscal")

    assert payload["source_states"]["wiki"] == "unavailable"
    assert payload["source_states"]["kb"] == "unavailable"
    assert payload["source_states"]["schema"] == "unavailable"
    assert payload["errors"]["wiki"] == "indice indisponivel"
    assert "code" in payload["source_states"]


def test_knowledge_router_search_returns_compact_results(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    _seed(database)
    router = KnowledgeRouter(database, settings.root)

    payload = router.search("Como gerar SPED Fiscal no VR?", limit=5)

    assert payload["total"] == len(payload["results"]) > 0
    sources = {item["source"] for item in payload["results"]}
    assert sources <= {"wiki", "kb", "schema"}
    first = payload["results"][0]
    assert first["title"]
    assert first["evidence_id"]
    assert len(first["excerpt"]) <= 600


def test_knowledge_router_search_filters_source_and_module(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    _seed(database)
    router = KnowledgeRouter(database, settings.root)

    schema_only = router.search(
        "tabelas do sped fiscal", source="schema", limit=10
    )
    assert schema_only["source"] == "schema"
    assert schema_only["results"]
    assert all(item["source"] == "schema" for item in schema_only["results"])

    kb_only = router.search("gerar sped fiscal", source="kb", module="Fiscal")
    assert kb_only["results"]
    assert all(item["source"] == "kb" for item in kb_only["results"])
    assert all(item["module"] == "Fiscal" for item in kb_only["results"])

    limited = router.search("sped fiscal", limit=1)
    assert limited["total"] == 1


def test_conversation_options_register_vr_search_when_vr_enabled(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )

    options = orchestrator._conversation_options(conversation_id)

    names = [tool["name"] for tool in options.dynamic_tools]
    assert VR_SEARCH_TOOL_NAME in names


class _RecordingCodex:
    def __init__(self) -> None:
        self.responses: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def respond_dynamic_tool(self, request_id, content_items, success=True):
        with self._lock:
            self.responses.append(
                {
                    "request_id": str(request_id),
                    "content_items": content_items,
                    "success": bool(success),
                }
            )


def test_dynamic_tool_event_runs_in_process_search(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    _seed(database)
    orchestrator = ChatOrchestrator(settings, database)
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )

    recording = _RecordingCodex()
    orchestrator.providers["codex"].respond_dynamic_tool = (  # type: ignore[method-assign]
        recording.respond_dynamic_tool
    )

    event = RuntimeEvent(
        conversation_id,
        "dynamic_tool_requested",
        VR_SEARCH_TOOL_NAME,
        {
            "request_id": "req-42",
            "tool": VR_SEARCH_TOOL_NAME,
            "arguments": json.dumps({"query": "Como gerar SPED Fiscal no VR?"}),
        },
    )
    orchestrator._handle_dynamic_tool(event)

    deadline = 10.0
    while deadline > 0 and not recording.responses:
        deadline -= 0.05
        threading.Event().wait(0.05)

    assert len(recording.responses) == 1
    response = recording.responses[0]
    assert response["request_id"] == "req-42"
    assert response["success"] is True
    payload = json.loads(response["content_items"][0]["text"])
    assert payload["total"] > 0

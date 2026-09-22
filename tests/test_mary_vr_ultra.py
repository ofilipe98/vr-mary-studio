from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import (
    KnowledgeDocument,
    ModelRef,
    RuntimeEvent,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator, _code_scope_queries


QUESTION = "como emitir NF no Fiscal E fechar o caixa no PDV"


def _settings(tmp_path: Path) -> MarySettings:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "mary").resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.app_dir.mkdir(parents=True, exist_ok=True)
    settings.old_root.mkdir(parents=True, exist_ok=True)
    settings.ensure_dirs()
    return settings


def _seed_modules(database: MaryDatabase) -> None:
    for doc in (
        KnowledgeDocument(
            source="wiki",
            source_id="nf-fiscal",
            title="Emissão de NF no Fiscal",
            url="https://wiki.example/nf",
            markdown="# Fiscal\n\n## Emitir NF\n\nAcesse Nota Fiscal > Saída e clique em Incluir.",
            module="Fiscal",
            review_status="approved",
            content_hash="nf-fiscal",
            local_path="conhecimento/Fiscal/Wiki/nf.md",
        ),
        KnowledgeDocument(
            source="wiki",
            source_id="caixa-pdv",
            title="Fechamento de caixa no PDV",
            url="https://wiki.example/caixa",
            markdown="# PDV\n\n## Fechamento\n\nRetirada, valor e subtotal encerram o turno.",
            module="PDV",
            review_status="approved",
            content_hash="caixa-pdv",
            local_path="conhecimento/PDV/Wiki/caixa.md",
        ),
    ):
        database.upsert_document(doc)


SYNTHESIS = json.dumps(
    {
        "answer_markdown": "# Resposta Ultra\n\nProcedimento combinado.",
        # Positive fixture: cite the actual seeded Fiscal evidence.
        "used_evidence_ids": ["wiki:nf-fiscal:1"],
    },
    ensure_ascii=False,
)

REPORT = json.dumps(
    {
        "source_status": "found",
        "findings": [
            {"claim": "Passo confirmado", "evidence_ids": ["wiki:nf-fiscal:1"], "kind": "fact", "confidence": 0.9}
        ],
        "steps": [],
        "sources": [],
    }
)


class _UltraFakeProvider:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[str] = []
        self.active: set[str] = set()
        self.parallel_peak = 0

    def available(self) -> bool:
        return True

    def start_conversation(self, conversation_id, model, effort, workspace, options=None):
        with self.lock:
            if ":vr_fanout_" in conversation_id:
                self.active.add(conversation_id)
                self.parallel_peak = max(self.parallel_peak, len(self.active))
        return f"native:{conversation_id}"

    def release_conversation(self, *args, **kwargs):
        local = str(kwargs.get("local_id") or (args[0] if args else ""))
        with self.lock:
            self.active.discard(local)

    def interrupt(self, conversation_id):
        pass

    def send_message(self, conversation_id, native_id, model, effort, workspace,
                     message, callback, options=None, skills=None, image_paths=None):
        with self.lock:
            self.calls.append(conversation_id)
        output = SYNTHESIS
        if ":vr_fanout_" not in conversation_id and not any(
            marker in message for marker in ("sintetizador final", "Reescreva integralmente")
        ):
            output = json.loads(SYNTHESIS)["answer_markdown"] + "\n\n[Nota fiscal](https://wiki.example/nf)"
        if ":vr_fanout_" in conversation_id:
            output = REPORT
            threading.Event().wait(0.05)
        callback(RuntimeEvent(conversation_id, "turn_started", payload={"turn": {"id": "t"}}))
        callback(RuntimeEvent(conversation_id, "assistant_delta", output))
        callback(
            RuntimeEvent(
                conversation_id,
                "token_usage",
                payload={"tokenUsage": {"last": {"totalTokens": 25}}},
            )
        )
        callback(RuntimeEvent(conversation_id, "turn_completed"))


def _orchestrator(tmp_path: Path, mode: str):
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    _seed_modules(database)
    orchestrator = ChatOrchestrator(settings, database)
    provider = _UltraFakeProvider()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_mode=mode
    )
    database.update_conversation(
        conversation_id, native_id="native-x", native_id_vr="native-x"
    )
    events: list[RuntimeEvent] = []
    orchestrator._external_callbacks[conversation_id] = events.append
    return settings, database, orchestrator, provider, conversation_id, events


# ------------------------------------------------------------------ tri-state


def test_vr_mode_backfill_from_vr_enabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    cid = database.create_conversation("c", "codex", "m", settings.work_dir, vr_enabled=True)
    assert database.get_conversation(cid)["vr_mode"] == "vr"
    with database.connect() as connection:
        connection.execute("UPDATE conversations SET vr_mode='' WHERE id=?", (cid,))
    reopened = MaryDatabase(settings.database_path, root=settings.root)
    assert reopened.get_conversation(cid)["vr_mode"] == "vr"


def test_update_vr_mode_tri_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    cid = orchestrator.new_conversation("codex", "sol", defer_provider_start=True)

    orchestrator.update_vr_mode(cid, "ultra")
    row = database.get_conversation(cid)
    assert (row["vr_mode"], row["vr_enabled"]) == ("ultra", 1)

    orchestrator.update_vr_mode(cid, "off")
    row = database.get_conversation(cid)
    assert (row["vr_mode"], row["vr_enabled"]) == ("off", 0)

    orchestrator.update_vr_mode(cid, "turbo")  # inválido → off
    assert database.get_conversation(cid)["vr_mode"] == "off"


# -------------------------------------------------------------------- gatilho


def _run_send(orchestrator, conversation_id, events, *, mode_force=None, **send_kwargs):
    done = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            done.set()

    kwargs = dict(send_kwargs)
    if mode_force:
        kwargs["vr_mode"] = mode_force
    orchestrator.send(
        conversation_id,
        QUESTION,
        callback,
        use_vr=True,
        **kwargs,
    )
    assert done.wait(30), "turno não concluiu"


def test_ultra_mode_triggers_fanout(tmp_path: Path) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")
    _run_send(orchestrator, cid, events)
    kinds = [e.kind for e in events]
    assert "research_started" in kinds
    assert "research_completed" in kinds
    assert not any(
        event.payload.get("worker_id") == "ultra_code" for event in events
    )
    row = [r for r in database.messages(cid) if r["role"] == "assistant"]
    assert row and "Resposta Ultra" in row[-1]["content"]
    persisted = database.orchestration_events_after(cid, 0)
    persisted_kinds = [str(item["kind"]) for item in persisted]
    assert "agent_started" in persisted_kinds
    assert "agent_completed" in persisted_kinds
    assert "agent_usage" in persisted_kinds


def test_code_scope_prefers_original_business_term_over_follow_up_wording() -> None:
    scope = (
        "Quero que monte um fluxo completo de crossdocking no VRMaster.\n"
        "Analise o código e valide essa informação que você me enviou novamente."
    )

    queries = _code_scope_queries(scope)

    assert queries[0].casefold() == "crossdocking"
    assert "informação" not in {item.casefold() for item in queries}


def test_explicit_response_mode_is_applied_before_contract_and_fanout(tmp_path: Path) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "ultra"
    )

    _run_send(orchestrator, cid, events, response_mode="implementation")

    intent_event = [
        event for event in events if event.kind == "intent_analysis_completed"
    ][-1]
    contract_event = [
        event for event in events if event.kind == "response_contract_created"
    ][-1]
    assert intent_event.payload["response_mode"] == "implementation"
    assert intent_event.payload["intent"]["purpose"] == "implementation"
    assert contract_event.payload["contract"]["purpose"] == "implementation"
    assert "mapeamento de dados" in contract_event.payload["contract"]["must_include"]


def test_vr_mode_never_triggers_fanout(tmp_path: Path) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "vr")
    _run_send(orchestrator, cid, events)
    kinds = [e.kind for e in events]
    assert "research_started" not in kinds
    row = [r for r in database.messages(cid) if r["role"] == "assistant"]
    assert row and "Resposta Ultra" in row[-1]["content"]  # resposta direta


def test_ultra_single_module_question_keeps_fixed_sources(tmp_path: Path) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "ultra"
    )
    done = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            done.set()

    orchestrator.send(
        cid,
        "Como emitir NF no Fiscal?",
        callback,
        use_vr=True,
    )
    assert done.wait(30), "turno não concluiu"

    research_started = next(e for e in events if e.kind == "research_started")
    assert research_started.payload["sources"] == ["wiki", "kb", "schema"]
    plan = next(e for e in events if e.kind == "plan_created")
    stages = {stage["id"]: stage for stage in plan.payload["runtime_stages"]}
    assert set(stages) == {
        "ultra_wiki",
        "ultra_kb",
        "ultra_schema",
        "ultra_synthesis",
    }
    assert {stage["source"] for stage in stages.values() if not stage["final"]} == {
        "wiki",
        "kb",
        "schema",
    }
    started = {e.payload["agent_id"] for e in events if e.kind == "agent_started"}
    completed = {
        e.payload["agent_id"] for e in events if e.kind == "agent_completed"
    }
    assert {"ultra_wiki", "ultra_kb", "ultra_schema"} <= started
    assert {"ultra_wiki", "ultra_kb", "ultra_schema"} <= completed
    assert all(
        event.payload.get("parent_id") == "vr_ultra_fanout"
        for event in events
        if event.kind in {"agent_started", "agent_completed", "agent_failed"}
    )


def test_opt_in_code_agent_runs_after_scope_and_preserves_citation(
    tmp_path: Path, monkeypatch
) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "ultra"
    )
    calls: list[tuple[str, str]] = []

    def fake_search(self, query, *, release_id="", limit=10):
        calls.append((query, release_id))
        return [
            {
                "source_key": "a" * 64,
                "release_id": release_id,
                "release_hash": "b" * 64,
                "jar_relative_path": "VRPdv.jar",
                "qualified_name": "br.vr.CaixaService",
                "line_start": 10,
                "line_end": 18,
                "excerpt": "public void fecharCaixa() {}",
                "output_reference": "indice/codigo/decompilation/x",
                "source_relative_path": "br/vr/CaixaService.java",
                "indexed_at": "2026-08-29T00:00:00+00:00",
                "score": 100.0,
                "freshness": "fresh",
                "freshness_warning": "",
            }
        ]

    monkeypatch.setattr(
        "vrsoft_extractor.mary.orchestrator.JavaCodeIndex.search", fake_search
    )
    monkeypatch.setattr(
        "vrsoft_extractor.mary.orchestrator.ErpReleaseCatalog.status",
        lambda self, release_id, **_kwargs: {
            "release_id": release_id,
            "freshness": "fresh",
            "release_manifest_sha256": "b" * 64,
        },
    )
    _run_send(
        orchestrator,
        cid,
        events,
        code_analysis_enabled=True,
        code_analysis_release="2026.08.29",
        code_analysis_manifest_sha256="b" * 64,
    )

    assert calls and all(release == "2026.08.29" for _query, release in calls)
    code_started = [
        event for event in events
        if event.kind == "agent_started"
        and event.payload.get("worker_id") == "ultra_code"
    ]
    assert code_started
    assert all(
        event.payload.get("parent_id") == "vr_ultra_fanout"
        for event in code_started
    )
    research_run_id = [
        event.payload["run_id"]
        for event in events
        if event.kind == "research_started"
    ][-1]
    assert code_started[-1].payload["run_id"] == research_run_id
    assert code_started[-1].payload["release_manifest_sha256"] == "b" * 64
    completed = [event for event in events if event.kind == "research_completed"][-1]
    assert completed.payload["code_agent"] == "found"
    code_completed = [
        event
        for event in events
        if event.kind == "agent_completed"
        and event.payload.get("worker_id") == "ultra_code"
    ][-1]
    assert "VRPdv.jar" in code_completed.payload["citations"][0]


def test_code_agent_rejects_stale_frozen_release_and_fanout_continues(
    tmp_path: Path, monkeypatch
) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "ultra"
    )
    search_called = False

    def fake_search(*_args, **_kwargs):
        nonlocal search_called
        search_called = True
        return []

    monkeypatch.setattr(
        "vrsoft_extractor.mary.orchestrator.JavaCodeIndex.search", fake_search
    )
    monkeypatch.setattr(
        "vrsoft_extractor.mary.orchestrator.ErpReleaseCatalog.status",
        lambda self, release_id, **_kwargs: {
            "release_id": release_id,
            "freshness": "stale",
            "release_manifest_sha256": "b" * 64,
        },
    )

    _run_send(
        orchestrator,
        cid,
        events,
        code_analysis_enabled=True,
        code_analysis_release="2026.08.29",
        code_analysis_manifest_sha256="b" * 64,
    )

    assert not search_called
    failed = [
        event
        for event in events
        if event.kind == "agent_failed"
        and event.payload.get("worker_id") == "ultra_code"
    ][-1]
    assert failed.payload["parent_id"] == "vr_ultra_fanout"
    assert failed.payload["release_id"] == "2026.08.29"
    assert failed.payload["release_manifest_sha256"] == "b" * 64
    assert "mudaram" in failed.payload["error"]
    assert any(event.kind == "turn_completed" for event in events)


def test_code_agent_failure_degrades_without_stopping_synthesis(
    tmp_path: Path, monkeypatch
) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "ultra"
    )

    def fail_search(*_args, **_kwargs):
        raise RuntimeError("índice indisponível")

    monkeypatch.setattr(
        "vrsoft_extractor.mary.orchestrator.JavaCodeIndex.search", fail_search
    )
    _run_send(orchestrator, cid, events, code_analysis_enabled=True)

    assert any(
        event.kind == "agent_failed"
        and event.payload.get("worker_id") == "ultra_code"
        for event in events
    )
    assert any(event.kind == "turn_completed" for event in events)
    completed = [event for event in events if event.kind == "research_completed"][-1]
    assert completed.payload["code_agent"] == "failed"


# ------------------------------------------------------- pool próprio e limite


def test_research_pool_round_robin_and_parallel_cap(tmp_path: Path) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")
    orchestrator.set_research_config(
        pool=[
            ModelRef("codex", "sol", "Sol"),
            ModelRef("codex", "opus", "Opus"),
        ],
        max_parallel=1,
    )
    _run_send(orchestrator, cid, events)
    models = [
        (e.payload.get("model") or {}).get("model")
        for e in events
        if e.kind == "agent_started"
    ]
    assert models[0] == "sol"
    assert provider.parallel_peak == 1, "intensidade 1 deve ser sequencial"


def test_research_pool_models_cycle(tmp_path: Path) -> None:
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")
    orchestrator.set_research_config(
        pool=[
            ModelRef("codex", "sol", "Sol"),
            ModelRef("codex", "opus", "Opus"),
        ]
    )
    _run_send(orchestrator, cid, events)
    models = [
        (e.payload.get("model") or {}).get("model")
        for e in events
        if e.kind == "agent_started"
    ]
    # Researchers start concurrently; compare each assignment with the plan,
    # without depending on thread scheduling order.
    stages = next(e for e in events if e.kind == "plan_created").payload["runtime_stages"]
    expected = {stage["id"]: stage["model"]["model"] for stage in stages if not stage["final"]}
    actual = {e.payload["agent_id"]: e.payload["model"]["model"] for e in events if e.kind == "agent_started"}
    assert actual == expected
    assert sorted(models[:2]) == ["opus", "sol"]


# ---------------------------------------------------- paridade VR <-> VR Ultra


def test_contract_parity_and_deferred_ultra_source_routing(tmp_path: Path) -> None:
    payloads_by_mode: dict[str, dict[str, Any]] = {}
    for mode in ("vr", "ultra"):
        settings, database, orchestrator, provider, cid, events = _orchestrator(
            tmp_path, mode
        )
        _run_send(orchestrator, cid, events)
        payloads_by_mode[mode] = {
            # Routing/contract must match; execution identity and event order
            # intentionally differ for separate requests and must remain present.
            e.kind: {key: value for key, value in e.payload.items()
                     if key not in {"execution_id", "runtime_event_id"}}
            for e in events
            if e.kind in {"response_contract_created", "knowledge_routed"}
        }
    vr = payloads_by_mode["vr"]
    ultra = payloads_by_mode["ultra"]
    assert vr["response_contract_created"] == ultra["response_contract_created"]
    assert "knowledge_routed" in vr
    assert "knowledge_routed" not in ultra

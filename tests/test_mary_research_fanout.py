from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    KnowledgeDocument,
    ModuleRoutingDecision,
    QueryProfile,
    RuntimeEvent,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.research_fanout import (
    MAX_PARALLEL_RESEARCHERS,
    ModuleResearch,
    build_researcher_prompt,
    fanout_payload,
    merge_module_research,
    parse_researcher_output,
)
from vrsoft_extractor.mary.supervision import (
    ResponseContract,
    ResponseIntent,
)


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


def _intent(**overrides: Any) -> ResponseIntent:
    values: dict[str, Any] = {
        "topic": "",
        "user_goal": "answer_question",
        "audience": "operational_user",
        "purpose": "guidance",
        "requested_detail": "normal",
        "technical_level": "low_to_medium",
        "requires_research": True,
        "requires_step_by_step": False,
        "requires_sources": True,
        "conversation_context": "",
    }
    values.update(overrides)
    return ResponseIntent(**values)


def _candidate(index: int, module: str = "", source: str = "wiki") -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=f"{source}:d{index}:-{index}",
        source=source,
        source_id="s",
        document_id=index,
        chunk_id=index,
            title=f"Doc {module} {index}",
        heading="H",
        content_type="section",
        module=module,
        product="",
        excerpt="conteudo",
        url=f"https://wiki.example/{index}",
    )


def _bundle(
    *,
    modules: tuple[str, ...] = (),
    candidates: tuple[EvidenceCandidate, ...] | None = None,
) -> EvidenceBundle:
    profile = QueryProfile(query="q", intents={"functional": 1.0})
    items = candidates or ()
    routing = tuple(
        ModuleRoutingDecision(module=m, selected=True, reasons=()) for m in modules
    )
    return EvidenceBundle(
        profile=profile,
        candidates=items,
        module_routing=routing,
    )


def _contract() -> ResponseContract:
    return ResponseContract(
        purpose="guidance",
        audience="operational_user",
        technical_level="low_to_medium",
        detail_level="normal",
    )


# ------------------------------------------------------------------ Fase 1


class TestResearcherPromptAndParsing:
    def test_prompt_contains_scope_sources_budget_and_json(self):
        prompt = build_researcher_prompt(
            "Fiscal", ("wiki", "kb"), "Como emitir NF?", "<evidence>x</evidence>"
        )
        assert "módulo Fiscal" in prompt
        assert "WIKI" in prompt and "KB" in prompt
        assert "até 6" in prompt
        assert "NÃO investigue" in prompt
        assert '"source_status"' in prompt

    def test_parse_structured_report(self):
        raw = json.dumps(
            {
                "source_status": "found",
                "findings": [
                    {
                        "claim": "Passo X confirmado",
                        "evidence_ids": ["wiki:d0:-0"],
                        "kind": "fact",
                        "confidence": 0.9,
                    }
                ],
                "steps": ["abrir tela"],
                "conflicts": [],
                "missing_information": [],
                "warnings": [],
                "sources": ["wiki:d0:-0"],
            },
            ensure_ascii=False,
        )
        research = parse_researcher_output(
            raw,
            worker_id="fanout_fiscal",
            worker_name="Pesquisador Fiscal",
            module="Fiscal",
        )
        assert research.succeeded
        assert research.report is not None
        assert research.module == "Fiscal"

    def test_parse_invalid_output_becomes_failed_research(self):
        research = parse_researcher_output(
            "não sou json",
            worker_id="w",
            worker_name="W",
            module="PDV",
        )
        assert not research.succeeded
        assert research.raw_error


class TestMergeAndPayload:
    def test_merge_collects_claims_and_marks_failures(self):
        ok_raw = json.dumps(
            {
                "source_status": "found",
                "findings": [
                    {"claim": "A", "evidence_ids": [], "kind": "fact", "confidence": 0.8}
                ],
            }
        )
        good = parse_researcher_output(ok_raw, worker_id="f", worker_name="F", module="Fiscal")
        bad = ModuleResearch(module="PDV", raw_error="timeout")
        merged = merge_module_research([good, bad])
        assert any(item.worker_id == "f" for item in merged.claims)

    def test_payload_counts(self):
        ok_raw = json.dumps({"source_status": "found", "findings": []})
        good = parse_researcher_output(ok_raw, worker_id="f", worker_name="F", module="Fiscal")
        payload = fanout_payload([good, ModuleResearch(module="PDV", raw_error="x")])
        assert payload["ok"] == 1 and payload["failed"] == ["PDV"]


# ------------------------------------------------------- Fase 2: gatilho


class TestFanoutTrigger:
    def _orchestrator(self, tmp_path: Path) -> ChatOrchestrator:
        settings = _settings(tmp_path)
        database = MaryDatabase(settings.database_path, root=settings.root)
        orchestrator = ChatOrchestrator(settings, database)
        orchestrator.new_conversation(
            "codex", "sol", defer_provider_start=True, vr_enabled=True
        )
        return orchestrator

    def test_two_modules_trigger(self, tmp_path: Path):
        orchestrator = self._orchestrator(tmp_path)
        modules = orchestrator._fanout_modules(
            _bundle(modules=("Fiscal", "PDV")), _intent(), has_images=False
        )
        assert modules == ("Fiscal", "PDV")

    def test_single_simple_question_does_not_trigger(self, tmp_path: Path):
        orchestrator = self._orchestrator(tmp_path)
        assert (
            orchestrator._fanout_modules(_bundle(), _intent(), has_images=False)
            is None
        )

    def test_deep_single_module_triggers(self, tmp_path: Path):
        orchestrator = self._orchestrator(tmp_path)
        bundle = _bundle(candidates=(_candidate(0),))
        modules = orchestrator._fanout_modules(
            bundle,
            _intent(purpose="training_manual", requested_detail="very_high"),
            has_images=False,
        )
        assert modules == ("Multimodulo",)

    def test_schema_and_global_labels_respect_parallel_cap(self, tmp_path: Path):
        orchestrator = self._orchestrator(tmp_path)
        bundle = _bundle(
            modules=("Fiscal", "PDV"),
            candidates=(
                _candidate(0, source="schema"),
                _candidate(1, module="Multimodulo"),
            ),
        )
        modules = orchestrator._fanout_modules(bundle, _intent(), has_images=False)
        assert len(modules) <= MAX_PARALLEL_RESEARCHERS
        assert set(modules[:2]) == {"Fiscal", "PDV"}

    def test_images_never_trigger(self, tmp_path: Path):
        orchestrator = self._orchestrator(tmp_path)
        assert (
            orchestrator._fanout_modules(
                _bundle(modules=("Fiscal", "PDV")), _intent(), has_images=True
            )
            is None
        )

    def test_kill_switch_flag_present(self, tmp_path: Path):
        settings = _settings(tmp_path)
        database = MaryDatabase(settings.database_path, root=settings.root)
        orchestrator = ChatOrchestrator(settings, database)
        assert getattr(orchestrator.settings, "vr_research_fanout") is True


# --------------------------------------------------- Fase 3: executor fake


REPORT_BY_MODULE = {
    "Fiscal": {
        "source_status": "found",
        "findings": [
            {"claim": "NF passo confirmado no Fiscal", "evidence_ids": ["wiki:d0:-0"], "kind": "fact", "confidence": 0.9}
        ],
        "steps": ["1. Preencher nota"],
        "sources": ["wiki:d0:-0"],
    },
    "PDV": {
        "source_status": "found",
        "findings": [
            {"claim": "Fechamento de caixa confirmado no PDV", "evidence_ids": [], "kind": "fact", "confidence": 0.85}
        ],
        "steps": [],
        "sources": [],
    },
}


SYNTHESIS_JSON = json.dumps(
    {
        "answer_markdown": "# Resposta\n\nProcedimento combinado dos dois módulos.",
        "used_evidence_ids": ["wiki:d1:-1"],
    },
    ensure_ascii=False,
)


class _FakeFanoutProvider:
    """Returns per-module reports for ephemeral turns, synthesis for main."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[str] = []
        self.parallel_peak = 0
        self._active_ids: set[str] = set()

    def available(self) -> bool:
        return True

    def start_conversation(self, conversation_id, model, effort, workspace, options=None):
        with self.lock:
            self._active_ids.add(conversation_id)
            self.parallel_peak = max(self.parallel_peak, len(self._active_ids))
        return f"native:{conversation_id}"

    def release_conversation(self, *args, **kwargs):
        native_or_local = str(kwargs.get("local_id") or (args[0] if args else ""))
        with self.lock:
            self._active_ids.discard(native_or_local)
            self.parallel_peak = max(self.parallel_peak, 0)

    def interrupt(self, conversation_id):
        pass

    def send_message(self, conversation_id, native_id, model, effort, workspace,
                     message, callback, options=None, skills=None, image_paths=None):
        with self.lock:
            self.calls.append(conversation_id)
        output = SYNTHESIS_JSON
        if ":vr_fanout_" in conversation_id:
            report = REPORT_BY_MODULE.get("Fiscal" if "fiscal" in conversation_id else "PDV")
            output = json.dumps(report, ensure_ascii=False)
            # Hold the session open so genuinely parallel workers overlap.
            threading.Event().wait(0.15)
        callback(RuntimeEvent(conversation_id, "turn_started", payload={"turn": {"id": "t"}}))
        callback(RuntimeEvent(conversation_id, "assistant_delta", output))
        callback(RuntimeEvent(conversation_id, "turn_completed"))


class _FlakyFanoutProvider(_FakeFanoutProvider):
    """Fails the first N calls of a given module, then succeeds."""

    def __init__(self, fail_module: str, failures: int = 1) -> None:
        super().__init__()
        self.fail_module = fail_module
        self.remaining_failures = failures

    def send_message(self, conversation_id, native_id, model, effort, workspace,
                     message, callback, options=None, skills=None, image_paths=None):
        with self.lock:
            self.calls.append(conversation_id)
        callback(RuntimeEvent(conversation_id, "turn_started", payload={"turn": {"id": "t"}}))
        if (
            f":vr_fanout_{self.fail_module}" in conversation_id
            and self.remaining_failures > 0
        ):
            with self.lock:
                self.remaining_failures -= 1
            callback(RuntimeEvent(conversation_id, "error", "upstream indisponível"))
            callback(RuntimeEvent(conversation_id, "turn_completed"))
            return
        output = SYNTHESIS_JSON
        if ":vr_fanout_" in conversation_id:
            report = REPORT_BY_MODULE.get(
                "Fiscal" if "fiscal" in conversation_id else "PDV"
            )
            output = json.dumps(report, ensure_ascii=False)
        callback(RuntimeEvent(conversation_id, "assistant_delta", output))
        callback(RuntimeEvent(conversation_id, "turn_completed"))


def test_run_module_fanout_publishes_merged_answer(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="doc-1",
            title="Doc",
            url="https://wiki.example/1",
            markdown="# Doc\n\nConteudo.",
            module="Fiscal",
            review_status="approved",
            content_hash="doc-1",
            local_path="conhecimento/Fiscal/Wiki/doc-1.md",
        )
    )
    orchestrator = ChatOrchestrator(settings, database)
    provider = _FakeFanoutProvider()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    database.update_conversation(conversation_id, native_id="native-x")
    events: list[RuntimeEvent] = []
    orchestrator._external_callbacks[conversation_id] = events.append

    bundle = _bundle(
        modules=("Fiscal", "PDV"),
        candidates=(_candidate(1),),
    )
    options = ConversationOptions(effort="medium", vr_enabled=True)

    orchestrator._run_module_fanout(
        conversation_id,
        dict(database.get_conversation(conversation_id)),
        "native-x",
        settings.work_dir,
        "Como emitir NF no Fiscal e fechar caixa no PDV?",
        provider,
        options,
        [],
        bundle,
        _intent(),
        _contract(),
        ("Fiscal", "PDV"),
    )

    orchestrator.drain_turn_finalizations()

    assistant_rows = [
        row for row in database.messages(conversation_id) if row["role"] == "assistant"
    ]
    assert assistant_rows, "síntese deveria ser publicada"
    saved = assistant_rows[-1]["content"]
    assert "Resposta" in saved
    kinds = [event.kind for event in events]
    assert "research_started" in kinds and "synthesis_started" in kinds
    assert "plan_created" in kinds, "estágios deveriam ser publicados para o painel"
    plan_event = next(e for e in events if e.kind == "plan_created")
    stages = plan_event.payload.get("runtime_stages") or []
    assert [s["id"] for s in stages] == [
        "fanout_fiscal",
        "fanout_pdv",
        "fanout_synthesis",
    ]
    assert stages[-1]["final"] is True
    started_ids = [
        e.payload.get("agent_id") for e in events if e.kind == "agent_started"
    ]
    completed_ids = [
        e.payload.get("agent_id") for e in events if e.kind == "agent_completed"
    ]
    assert set(started_ids) == {"fanout_fiscal", "fanout_pdv"}
    assert set(completed_ids) == {"fanout_fiscal", "fanout_pdv"}
    assert provider.parallel_peak >= 2, "pesquisadores deveriam rodar em paralelo"
    with database.connect() as connection:
        citations = connection.execute(
            "SELECT document_id FROM source_citations WHERE conversation_id=?",
            (conversation_id,),
        ).fetchall()
    assert citations, "citações da síntese deveriam ser persistidas"
    assert any(row["document_id"] == 1 for row in citations)


def test_researchers_cycle_through_model_pool(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = _FakeFanoutProvider()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    database.update_conversation(conversation_id, native_id="native-x")

    from vrsoft_extractor.mary.models import ModelRef

    orchestrator.set_research_config(
        pool=(
            ModelRef("codex", "sol", "Sol"),
            ModelRef("codex", "opus", "Opus"),
        ),
    )
    options = ConversationOptions(effort="medium", vr_enabled=True)
    events: list[RuntimeEvent] = []
    orchestrator._external_callbacks[conversation_id] = events.append

    orchestrator._run_module_fanout(
        conversation_id,
        dict(database.get_conversation(conversation_id)),
        "native-x",
        settings.work_dir,
        "Pergunta?",
        provider,
        options,
        [],
        _bundle(modules=("Fiscal", "PDV"), candidates=(_candidate(1),)),
        _intent(),
        _contract(),
        ("Fiscal", "PDV"),
    )

    models = [
        (e.payload.get("model") or {}).get("model")
        for e in events
        if e.kind == "agent_started"
    ]
    assert models == ["sol", "opus"], "pesquisadores deveriam alternar o pool"


def test_researcher_retry_recovers_transient_failure(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = _FlakyFanoutProvider("pdv", failures=1)
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    database.update_conversation(conversation_id, native_id="native-x")

    bundle = _bundle(modules=("Fiscal", "PDV"), candidates=(_candidate(1),))
    orchestrator._run_module_fanout(
        conversation_id,
        dict(database.get_conversation(conversation_id)),
        "native-x",
        settings.work_dir,
        "Pergunta?",
        provider,
        ConversationOptions(effort="medium", vr_enabled=True),
        [],
        bundle,
        _intent(),
        _contract(),
        ("Fiscal", "PDV"),
    )

    orchestrator.drain_turn_finalizations()

    assistant_rows = [
        row for row in database.messages(conversation_id) if row["role"] == "assistant"
    ]
    assert assistant_rows and "Resposta" in assistant_rows[-1]["content"]
    pdv_calls = [c for c in provider.calls if "fanout_pdv" in c]
    assert len(pdv_calls) == 2, "PDV deveria ser re-tentado uma vez"


def test_all_researchers_failed_does_not_bypass_budget_and_validation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)

    class _AlwaysFails(_FakeFanoutProvider):
        def send_message(self, conversation_id, native_id, model, effort, workspace,
                         message, callback, options=None, skills=None, image_paths=None):
            with self.lock:
                self.calls.append(conversation_id)
            callback(RuntimeEvent(conversation_id, "turn_started", payload={"turn": {"id": "t"}}))
            if ":vr_fanout_" in conversation_id:
                callback(RuntimeEvent(conversation_id, "error", "upstream down"))
                callback(RuntimeEvent(conversation_id, "turn_completed"))
                return
            callback(RuntimeEvent(conversation_id, "assistant_delta", "RESPOSTA DIRETA"))
            callback(RuntimeEvent(conversation_id, "turn_completed"))

    provider = _AlwaysFails()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    database.update_conversation(conversation_id, native_id="native-x")

    orchestrator._run_module_fanout(
        conversation_id,
        dict(database.get_conversation(conversation_id)),
        "native-x",
        settings.work_dir,
        "Pergunta?",
        provider,
        ConversationOptions(effort="medium", vr_enabled=True),
        [],
        _bundle(modules=("Fiscal", "PDV"), candidates=(_candidate(1),)),
        _intent(),
        _contract(),
        ("Fiscal", "PDV"),
    )

    orchestrator.drain_turn_finalizations()

    deadline = time.monotonic() + 5
    assistant_rows: list[Any] = []
    while time.monotonic() < deadline:
        assistant_rows = [
            row for row in database.messages(conversation_id) if row["role"] == "assistant"
        ]
        if assistant_rows:
            break
        threading.Event().wait(0.05)
    assert assistant_rows and "evid" in assistant_rows[-1]["content"]
    assert "RESPOSTA DIRETA" not in assistant_rows[-1]["content"]


def test_run_module_fanout_is_provider_agnostic(tmp_path: Path) -> None:
    """The fan-out only needs the standard provider surface (opencode works)."""
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = _FakeFanoutProvider()
    orchestrator.providers = {"opencode": provider}
    conversation_id = orchestrator.new_conversation(
        "opencode", "free-model", defer_provider_start=True, vr_enabled=True
    )
    database.update_conversation(conversation_id, native_id="native-oc")

    bundle = _bundle(modules=("Fiscal", "PDV"), candidates=(_candidate(1),))
    events: list[RuntimeEvent] = []
    orchestrator._external_callbacks[conversation_id] = events.append

    orchestrator._run_module_fanout(
        conversation_id,
        dict(database.get_conversation(conversation_id)),
        "native-oc",
        settings.work_dir,
        "Pergunta multi-módulo?",
        provider,
        ConversationOptions(effort="medium", vr_enabled=True),
        [],
        bundle,
        _intent(),
        _contract(),
        ("Fiscal", "PDV"),
    )

    orchestrator.drain_turn_finalizations()

    assistant_rows = [
        row for row in database.messages(conversation_id) if row["role"] == "assistant"
    ]
    assert assistant_rows and "Resposta" in assistant_rows[-1]["content"]
    assert any(event.kind == "research_started" for event in events)

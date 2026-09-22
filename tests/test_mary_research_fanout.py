from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.execution import (
    ExecutionContext,
    ExecutionRunner,
)
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    QueryProfile,
    SourceSearchReport,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.research_fanout import (
    SourceResearch,
    build_source_researcher_prompt,
    merge_source_research,
    parse_source_researcher_output,
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


def _contract() -> ResponseContract:
    return ResponseContract(
        purpose="guidance",
        audience="operational_user",
        technical_level="low_to_medium",
        detail_level="normal",
    )


# ------------------------------------------------------------------ Fase 1


class TestResearcherPromptAndParsing:
    def test_source_prompt_and_parser_enforce_lane_evidence_ids(self):
        prompt = build_source_researcher_prompt(
            "wiki",
            "Como funciona?",
            "evidências",
        )
        assert "exclusivo da fonte WIKI" in prompt
        assert "qualquer módulo" in prompt
        assert "vrwiki e endoo" in prompt
        assert "efetivamente habilitadas" not in prompt
        raw = json.dumps({
            "source_status": "found",
            "findings": [{
                "claim": "Achado",
                "evidence_ids": ["wiki:ok", "kb:fora"],
                "kind": "fact",
                "confidence": 0.9,
            }],
        })
        result = parse_source_researcher_output(
            raw,
            worker_id="ultra_wiki",
            worker_name="Agente Wiki",
            source="wiki",
            allowed_evidence_ids=("wiki:ok",),
        )
        assert result.succeeded and result.report is not None
        assert result.report.findings[0].evidence_ids == ("wiki:ok",)


class TestMergeAndPayload:
    def test_exhausted_source_is_successful_and_mergeable(self):
        exhausted = parse_source_researcher_output(
            json.dumps({
                "source_status": "exhausted",
                "findings": [],
                "missing_information": ["sem resultados"],
            }),
            worker_id="ultra_kb",
            worker_name="Agente KB",
            source="kb",
        )
        assert exhausted.succeeded
        merged = merge_source_research([
            exhausted,
            SourceResearch(source="schema", raw_error="falha técnica"),
        ])
        assert "sem resultados" in merged.gaps
        assert merged.failed_required_workers == ("schema",)


# ------------------------------------------------------- Fase 2: gatilho


class TestFanoutTrigger:
    def test_kill_switch_flag_present(self, tmp_path: Path):
        settings = _settings(tmp_path)
        database = MaryDatabase(settings.database_path, root=settings.root)
        orchestrator = ChatOrchestrator(settings, database)
        assert getattr(orchestrator.settings, "vr_research_fanout") is True


# ------------------------------------------------- Ultra: coordenação real


def test_ultra_source_fanout_starts_dev_with_documental_lanes(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    profile = QueryProfile(query="fluxo fiscal", intents={"functional": 1.0})
    barrier = threading.Barrier(4, timeout=5)
    reached: list[str] = []
    lock = threading.Lock()

    def bundle_for(source: str) -> EvidenceBundle:
        candidate = EvidenceCandidate(
            evidence_id=f"{source}:doc-1:1",
            source=source,
            source_id="doc-1",
            document_id=1,
            chunk_id=1,
            title=f"Doc {source}",
            heading="H",
            content_type="section",
            module="Fiscal",
            product="",
            excerpt="conteudo relevante",
            url="",
        )
        report = SourceSearchReport(
            source=source,
            status="found",
            selected_evidence_ids=(candidate.evidence_id,),
        )
        return EvidenceBundle(
            profile=profile,
            candidates=(candidate,),
            source_reports=(report,),
        )

    retrieval = MagicMock()
    retrieval.classify.return_value = profile
    retrieval.prompt_for_role.return_value = "contexto"

    def route_source(query, source):
        with lock:
            reached.append(source)
        barrier.wait()
        return bundle_for(source)

    retrieval.route_source.side_effect = route_source

    def fake_code(root, query, **kwargs):
        with lock:
            reached.append("code")
        barrier.wait()
        return ([], [], [])

    monkeypatch.setattr(
        "vrsoft_extractor.mary.execution.runner.retrieve_code_candidates",
        fake_code,
    )

    events: list[tuple[str, str, dict]] = []

    def fake_ephemeral(cid, run_id, agent_id, *args, **kwargs):
        source = agent_id.rsplit("_", 1)[-1]
        return json.dumps(
            {
                "source_status": "found",
                "findings": [
                    {
                        "claim": f"achado {source}",
                        "evidence_ids": [f"{source}:doc-1:1"],
                        "kind": "fact",
                        "confidence": 0.9,
                    }
                ],
                "sources": [],
            }
        )

    def fake_buffered(*args, **kwargs):
        return (
            json.dumps(
                {
                    "answer_markdown": "Resposta coordenada.",
                    "used_evidence_ids": ["wiki:doc-1:1"],
                    "answer_status": "partially_answered",
                }
            ),
            {},
            {},
        )

    runner = ExecutionRunner(
        settings=settings,
        providers={},
        retrieval=retrieval,
        event_emitter=(
            lambda cid, kind, text, payload: events.append((kind, text, payload))
        ),
        ephemeral_turn_runner=fake_ephemeral,
        buffered_turn_runner=fake_buffered,
        looks_like_final_envelope=lambda _text: False,
        research_max_parallel=4,
    )
    assert runner.research_max_parallel == 4, (
        "a barreira das quatro frentes depende do limite Ultra explícito"
    )

    result = runner.execute_ultra_source_fanout(
        context=ExecutionContext(
            conversation_id="conv-coord",
            run_id="run-coord",
            workspace=tmp_path,
        ),
        conversation={"provider": "codex", "model": "gpt-5"},
        native_id="native-coord",
        provider=MagicMock(),
        options=ConversationOptions(effort="medium", vr_mode="ultra"),
        skills=[],
        intent=_intent(),
        contract=_contract(),
        code_analysis_enabled=True,
        request="fluxo fiscal",
    )

    assert not barrier.broken, "as quatro frentes precisam coexistir"
    assert set(reached) == {"wiki", "kb", "schema", "code"}
    assert result.draft is not None
    started = {
        payload["agent_id"]: payload
        for kind, _text, payload in events
        if kind == "agent_started"
    }
    assert {"ultra_wiki", "ultra_kb", "ultra_schema", "ultra_code"} <= set(
        started
    )
    assert all(
        payload["parent_id"] == "vr_ultra_fanout"
        for payload in started.values()
    )
    assert all(
        report.report.parent_id == "vr_ultra_fanout"
        for report in result.reports
        if report.report is not None
    )

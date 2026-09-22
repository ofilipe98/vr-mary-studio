from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import (
    EvidenceBundle,
    EvidenceCandidate,
    QueryProfile,
    RuntimeEvent,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.personality import (
    VRMASTER_TOOL_DRIVEN_ACCESS_POLICY,
)
from vrsoft_extractor.mary.supervision import (
    ResponseContract,
    strip_internal_leaks,
    validate_normal_response,
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


def _orchestrator(tmp_path: Path) -> tuple[MarySettings, ChatOrchestrator]:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    return settings, ChatOrchestrator(settings, database)


def _contract(**overrides: Any) -> ResponseContract:
    values: dict[str, Any] = {
        "purpose": "guidance",
        "audience": "operational_user",
        "technical_level": "low_to_medium",
        "detail_level": "normal",
    }
    values.update(overrides)
    return ResponseContract(**values)


def _bundle(*, candidates: int = 1) -> EvidenceBundle:
    profile = QueryProfile(query="q", intents={"functional": 1.0})
    items = tuple(
        EvidenceCandidate(
            evidence_id=f"wiki:doc-{i}:-{i}",
            source="wiki",
            source_id="s",
            document_id=i,
            chunk_id=i,
            title="Doc",
            heading="H",
            content_type="section",
            module="",
            product="",
            excerpt="x",
            url=f"https://wiki.example/doc-{i}",
        )
        for i in range(candidates)
    )
    return EvidenceBundle(
        profile=profile,
        candidates=items,
    )


# ---------------------------------------------------------------- #3 cache


class TestPromptPrefixCache:
    def test_stable_prefix_first_and_question_last(self, tmp_path: Path) -> None:
        _settings, orchestrator = _orchestrator(tmp_path)
        prompt = orchestrator._enrich_prompt("Como exportar SPED?", evidence_bundle=None)

        identity = prompt.index("CONTRATO DE IDENTIDADE")
        question = prompt.index("<user_request>")
        assert identity < question
        assert "Como exportar SPED?" in prompt[question:]

    def test_tool_driven_contract_without_automatic_search(self, tmp_path: Path) -> None:
        _settings, orchestrator = _orchestrator(tmp_path)
        with patch.object(
            orchestrator.database, "search", side_effect=AssertionError("sem retrieval")
        ):
            prompt = orchestrator._enrich_prompt("pergunta", evidence_bundle=None)
        assert VRMASTER_TOOL_DRIVEN_ACCESS_POLICY in prompt
        assert "CONSULTA SOB DEMANDA" in prompt
        assert "CONTEXTO LOCAL VR RECUPERADO" not in prompt
        for name in ("vr_sources", "vr_search", "vr_read"):
            assert name in prompt
        assert "<user_request>" in prompt

    def test_empty_bundle_also_skips_automatic_search(self, tmp_path: Path) -> None:
        _settings, orchestrator = _orchestrator(tmp_path)
        empty = EvidenceBundle(
            profile=QueryProfile(query="pergunta", intents={"functional": 1.0})
        )
        with patch.object(
            orchestrator.database, "search", side_effect=AssertionError("sem retrieval")
        ):
            prompt = orchestrator._enrich_prompt("pergunta", evidence_bundle=empty)
        assert "CONSULTA SOB DEMANDA" in prompt
        assert "CONTEXTO LOCAL VR RECUPERADO" not in prompt

    def test_images_keep_tools_and_skip_evidence_block(self, tmp_path: Path) -> None:
        _settings, orchestrator = _orchestrator(tmp_path)
        with patch.object(
            orchestrator.database, "search", side_effect=AssertionError("sem retrieval")
        ):
            prompt = orchestrator._enrich_prompt(
                "olha o print", evidence_bundle=None, has_images=True
            )
        assert "ANEXO VISUAL" in prompt
        assert "CONTEXTO LOCAL VR RECUPERADO" not in prompt
        assert "CONTEXTO LOCAL VR" not in prompt
        assert VRMASTER_TOOL_DRIVEN_ACCESS_POLICY in prompt
        for name in ("vr_sources", "vr_search", "vr_read"):
            assert name in prompt
        assert "<user_request>" in prompt

    def test_native_tool_hint_only_for_supporting_providers(self, tmp_path: Path) -> None:
        _settings, orchestrator = _orchestrator(tmp_path)
        codex_prompt = orchestrator._enrich_prompt(
            "pergunta", supports_native_tools=True
        )
        opencode_prompt = orchestrator._enrich_prompt(
            "pergunta", supports_native_tools=False
        )
        assert "ferramenta `vr_search`" in codex_prompt
        # Providers without the native dynamic-tool cycle keep the structured
        # local search/read script as a transport fallback, not as retrieval.
        assert "vr-search.ps1" in opencode_prompt
        assert VRMASTER_TOOL_DRIVEN_ACCESS_POLICY in opencode_prompt
        assert "O fallback estruturado" in opencode_prompt
        assert "O fallback estruturado" not in codex_prompt

    def test_prefix_is_byte_identical_across_questions(self, tmp_path: Path) -> None:
        _settings, orchestrator = _orchestrator(tmp_path)
        first = orchestrator._enrich_prompt("Pergunta um", evidence_bundle=None)
        second = orchestrator._enrich_prompt("Pergunta dois totalmente diferente", evidence_bundle=None)

        def stable_head(prompt: str) -> str:
            return prompt.split("<user_request>")[0]

        head_one, head_two = stable_head(first), stable_head(second)
        assert head_one.replace("Pergunta um", "") == head_two.replace(
            "Pergunta dois totalmente diferente", ""
        )

    def test_windows_prefix_warns_about_native_stderr_exit_code(self, tmp_path: Path) -> None:
        _settings, orchestrator = _orchestrator(tmp_path)
        prompt = orchestrator._enrich_prompt("pergunta", evidence_bundle=None)
        if os.name == "nt":
            assert "cmd /c" in prompt
            assert "stderr" in prompt
        else:
            assert "cmd /c" not in prompt


# ---------------------------------------------------------------- #5 validação


class TestValidateNormalResponse:
    def test_clean_answer_passes(self) -> None:
        violations = validate_normal_response(
            "Resposta objetiva e correta.", _contract(requires_sources=False), None
        )
        assert violations == ()

    def test_cited_evidence_id_passes_sources(self) -> None:
        answer = "Conforme wiki:doc-0:-0, o procedimento é X."
        violations = validate_normal_response(
            answer, _contract(requires_sources=True), _bundle()
        )
        assert not any(item.code == "missing_sources" for item in violations)

    def test_internal_leak_detected(self) -> None:
        answer = "Consulte caminho local: conhecimento/x.md para detalhes."
        violations = validate_normal_response(answer, _contract(), None)
        assert any(item.code == "internal_leak" for item in violations)

    def test_missing_sources_detected(self) -> None:
        violations = validate_normal_response(
            "Resposta sem citações.", _contract(requires_sources=True), _bundle()
        )
        assert any(item.code == "missing_sources" for item in violations)

    def test_cited_url_satisfies_sources(self) -> None:
        answer = "Veja [Doc](https://wiki.example/doc-0) para detalhes."
        violations = validate_normal_response(
            answer, _contract(requires_sources=True), _bundle()
        )
        assert not any(item.code == "missing_sources" for item in violations)

    def test_missing_steps_detected(self) -> None:
        violations = validate_normal_response(
            "Faça assim, de qualquer forma.",
            _contract(minimum_steps=3),
            None,
        )
        assert any(item.code == "missing_steps" for item in violations)

    def test_numbered_steps_pass(self) -> None:
        answer = "1) Abra a tela\n2) Clique em exportar\n3) Confirme"
        violations = validate_normal_response(
            answer, _contract(minimum_steps=2), None
        )
        assert not any(item.code == "missing_steps" for item in violations)

    def test_strip_internal_leaks_removes_only_offending_lines(self) -> None:
        content = "Linha boa.\ncaminho local: D:\\Temp\\arquivo.md\nOutra linha boa."
        cleaned = strip_internal_leaks(content)
        assert "Linha boa." in cleaned
        assert "D:\\Temp" not in cleaned
        assert "Outra linha boa." in cleaned


# ------------------------------------------------- dynamic tool evidence


def _dynamic_candidate(evidence_id: str, url: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=evidence_id,
        source="wiki",
        source_id=evidence_id.partition(":")[2],
        document_id=0,
        chunk_id=1,
        title="Doc",
        heading="H",
        content_type="section",
        module="",
        product="",
        excerpt="x",
        url=url,
        confidence=0.9,
    )


def test_dynamic_evidence_merges_before_validation_and_only_cited_persists(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_mode="vr"
    )
    cited = _dynamic_candidate("wiki:doc-cited", "https://wiki.example/cited")
    uncited = _dynamic_candidate("wiki:doc-uncited", "https://wiki.example/uncited")
    orchestrator._pending_evidence_bundles[conversation_id] = EvidenceBundle(
        profile=QueryProfile(query="q", intents={"functional": 1.0}), candidates=()
    )
    orchestrator._turn_dynamic_candidates[conversation_id] = [cited, uncited]

    answer = "Conforme [Doc](https://wiki.example/cited), o procedimento é X."
    validated = orchestrator._validate_direct_response(conversation_id, answer)
    assert validated == answer

    merged = orchestrator._pending_evidence_bundles[conversation_id]
    assert {c.evidence_id for c in merged.candidates} == {
        "wiki:doc-cited",
        "wiki:doc-uncited",
    }
    persisted = orchestrator._candidates_cited_in_content(validated, merged)
    assert [c.evidence_id for c in persisted] == ["wiki:doc-cited"]

    message_id = database.add_message(
        conversation_id, "assistant", validated, turn_id="turn:1"
    )
    database.add_source_citations(
        conversation_id, message_id, [c.to_dict() for c in persisted]
    )
    citations = database.get_source_citations(message_id)
    assert [c["evidence_id"] for c in citations] == ["wiki:doc-cited"]


def test_dynamic_evidence_not_cited_is_not_persisted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_mode="vr"
    )
    uncited = _dynamic_candidate("wiki:doc-uncited", "https://wiki.example/uncited")
    orchestrator._pending_evidence_bundles[conversation_id] = EvidenceBundle(
        profile=QueryProfile(query="q", intents={"functional": 1.0}), candidates=()
    )
    orchestrator._turn_dynamic_candidates[conversation_id] = [uncited]

    answer = "Resposta sem citar documentação."
    validated = orchestrator._validate_direct_response(conversation_id, answer)
    merged = orchestrator._pending_evidence_bundles[conversation_id]
    persisted = orchestrator._candidates_cited_in_content(validated, merged)
    assert persisted == []

    message_id = database.add_message(
        conversation_id, "assistant", validated, turn_id="turn:2"
    )
    database.add_source_citations(
        conversation_id, message_id, [c.to_dict() for c in persisted]
    )
    assert database.get_source_citations(message_id) == []


# ------------------------------------------------- gate integration (turn end)


class _RecordingCodex:
    """Minimal Codex stand-in exposing respond_dynamic_tool-free surface."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started: list[str] = []
        self.sent: list[str] = []

    def available(self) -> bool:
        return True

    def start_conversation(self, conversation_id, model, effort, workspace, options=None):
        with self.lock:
            self.started.append(conversation_id)
        return f"native:{conversation_id}"

    def resume_conversation(self, *args, **kwargs):
        raise AssertionError("não deveria retomar sessão na correção")

    def release_conversation(self, *args, **kwargs):
        pass

    def interrupt(self, conversation_id):
        pass

    def send_message(
        self,
        conversation_id,
        native_id,
        model,
        effort,
        workspace,
        message,
        callback,
        options=None,
        skills=None,
        image_paths=None,
    ):
        with self.lock:
            self.sent.append(message)
        callback(RuntimeEvent(conversation_id, "turn_started", payload={"turn": {"id": "t"}}))
        callback(
            RuntimeEvent(
                conversation_id,
                "assistant_delta",
                "RESPOSTA CORRIGIDA LIMPA",
            )
        )
        callback(RuntimeEvent(conversation_id, "turn_completed"))


def test_turn_end_gate_corrects_leaky_answer(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = _RecordingCodex()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )

    leaky = "Resposta útil.\ncaminho local: conhecimento/Fiscal/x.md\nFim."
    orchestrator._pending_response_modes[conversation_id] = "vr"
    orchestrator._assistant_buffers[conversation_id] = [leaky]
    orchestrator._pending_user_messages[conversation_id] = database.begin_user_turn(
        conversation_id, "pergunta"
    )
    database.update_conversation(conversation_id, native_id="native-x")

    events: list[RuntimeEvent] = []
    orchestrator._external_callbacks[conversation_id] = events.append

    orchestrator._handle_event(
        RuntimeEvent(conversation_id, "turn_completed", payload={"turn": {"id": "t1"}})
    )
    orchestrator.drain_turn_finalizations()

    assistant_rows = [
        row
        for row in database.messages(conversation_id)
        if row["role"] == "assistant"
    ]
    assert assistant_rows, "resposta deveria ser persistida"
    saved = assistant_rows[-1]["content"]
    assert "caminho local:" not in saved
    assert any(event.kind == "response_validation_fixed" for event in events)

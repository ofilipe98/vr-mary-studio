from __future__ import annotations

from pathlib import Path

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    EvidenceConflict,
    QueryProfile,
)
from vrsoft_extractor.mary.supervision import (
    AdaptiveEffortDecision,
    ResponseIntent,
    analyze_response_intent,
    decide_adaptive_effort,
)


def _intent(**overrides: object) -> ResponseIntent:
    values: dict[str, object] = {
        "topic": "VRMaster",
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


def _settings(tmp_path: Path, **overrides: object) -> MarySettings:
    app = tmp_path / "app"
    old_root = tmp_path / "old"
    settings = MarySettings(
        app_dir=app.resolve(),
        root=(tmp_path / "mary").resolve(),
        old_root=old_root.resolve(),
        **overrides,
    )
    app.mkdir(parents=True, exist_ok=True)
    old_root.mkdir(parents=True, exist_ok=True)
    settings.ensure_dirs()
    return settings


def _candidate(index: int) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=f"e{index}",
        source="wiki",
        source_id="s",
        document_id=index,
        chunk_id=index,
        title="t",
        heading="h",
        content_type="section",
        module="",
        product="",
        excerpt="x",
    )


def _bundle(*, conflicts: int = 0, missing: tuple[str, ...] = (), candidates: int = 2):
    profile = QueryProfile(
        query="x",
        intents={"functional": 1.0},
        module="",
        product="",
        entities={},
        answer_type="functional",
        terms=("x",),
    )
    return EvidenceBundle(
        profile=profile,
        candidates=tuple(_candidate(i) for i in range(candidates)),
        groups=(),
        conflicts=tuple(
            EvidenceConflict(
                concept=f"c{i}", evidence_ids=("e0", "e1"), reason="divergência"
            )
            for i in range(conflicts)
        ),
        source_reports=(),
        module_routing=(),
        missing_sources=missing,
        warnings=(),
    )


def test_simple_guidance_keeps_user_effort() -> None:
    decision = decide_adaptive_effort(_intent(), None, "medium")
    assert isinstance(decision, AdaptiveEffortDecision)
    assert decision.effort == "medium"
    assert not decision.changed


def test_training_manual_raises_to_high() -> None:
    decision = decide_adaptive_effort(
        _intent(purpose="training_manual", requires_step_by_step=True), None, "medium"
    )
    assert decision.effort == "high"
    assert decision.changed


def test_troubleshooting_with_conflicts_reaches_xhigh() -> None:
    decision = decide_adaptive_effort(
        _intent(purpose="troubleshooting"),
        _bundle(conflicts=2),
        "medium",
    )
    assert decision.effort == "xhigh"


def test_very_high_detail_and_missing_sources_raise() -> None:
    decision = decide_adaptive_effort(
        _intent(
            purpose="training_manual",
            requested_detail="very_high",
            requires_step_by_step=True,
        ),
        _bundle(missing=("kb",)),
        "high",
    )
    assert decision.effort == "xhigh"


def test_ultra_mode_allows_max() -> None:
    capped = decide_adaptive_effort(
        _intent(purpose="troubleshooting"),
        _bundle(conflicts=1),
        "medium",
    )
    assert capped.effort == "xhigh"

    allowed = decide_adaptive_effort(
        _intent(
            purpose="troubleshooting",
            requested_detail="very_high",
            requires_step_by_step=True,
        ),
        _bundle(conflicts=1),
        "medium",
        allow_max=True,
    )
    assert allowed.effort == "max"


def test_never_lowers_explicit_high() -> None:
    decision = decide_adaptive_effort(_intent(), None, "high")
    assert decision.effort == "high"
    assert not decision.changed


def test_explicit_low_only_rises_with_strong_signals() -> None:
    calm = decide_adaptive_effort(_intent(purpose="technical_explanation"), None, "low")
    assert calm.effort == "low"

    strong = decide_adaptive_effort(
        _intent(purpose="troubleshooting"),
        _bundle(conflicts=1),
        "low",
    )
    assert strong.effort in {"high", "xhigh"}


def test_invalid_base_falls_back_to_medium() -> None:
    decision = decide_adaptive_effort(_intent(), None, "turbo")
    assert decision.base == "medium"
    assert decision.effort == "medium"


def test_auto_base_resolves_concrete_efforts() -> None:
    simple = decide_adaptive_effort(_intent(), None, "auto")
    assert simple.base == "auto"
    assert simple.effort == "medium"
    assert not simple.changed  # baseline: no adjustment event

    hard = decide_adaptive_effort(
        _intent(purpose="troubleshooting"),
        _bundle(conflicts=1),
        "auto",
    )
    assert hard.effort == "xhigh"
    assert hard.changed


def test_apply_adaptive_effort_always_resolves_auto(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    orchestrator = ChatOrchestrator(
        settings, MaryDatabase(settings.database_path, root=settings.root)
    )
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    auto_options = ConversationOptions(effort="auto", vr_enabled=True)

    # Simple question with VR on: still resolves to a concrete provider value.
    resolved = orchestrator._apply_adaptive_effort(
        conversation_id,
        auto_options,
        use_vr=True,
        response_intent=_intent(),
        evidence_bundle=None,
    )
    assert resolved.effort == "medium"

    # Hard question: adaptive raises from the auto baseline.
    raised = orchestrator._apply_adaptive_effort(
        conversation_id,
        auto_options,
        use_vr=True,
        response_intent=_intent(purpose="troubleshooting"),
        evidence_bundle=_bundle(conflicts=1),
    )
    assert raised.effort == "xhigh"

    # VR off: sentinel resolves to the global default without adaptation.
    vr_off = orchestrator._apply_adaptive_effort(
        conversation_id,
        auto_options,
        use_vr=False,
        response_intent=None,
        evidence_bundle=None,
    )
    assert vr_off.effort == str(settings.default_effort)


def test_analyze_intent_feeds_decision_end_to_end() -> None:
    intent = analyze_response_intent(
        "Como fazer o passo a passo para configurar o TEF no PDV?",
        QueryProfile(
            query="x",
            intents={"process": 1.0},
            module="PDV",
            product="",
            entities={},
            answer_type="process",
            terms=("tef",),
        ),
    )
    decision = decide_adaptive_effort(intent, None, "medium")
    assert decision.effort == "high"


def test_apply_adaptive_effort_adjusts_turn_options(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    orchestrator = ChatOrchestrator(
        settings, MaryDatabase(settings.database_path, root=settings.root)
    )
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    options = ConversationOptions(effort="medium", vr_enabled=True)

    adjusted = orchestrator._apply_adaptive_effort(
        conversation_id,
        options,
        use_vr=True,
        response_intent=_intent(
            purpose="troubleshooting",
        ),
        evidence_bundle=_bundle(conflicts=1),
    )
    assert adjusted.effort == "xhigh"
    assert options.effort == "medium"  # original untouched (frozen dataclass)


def test_apply_adaptive_effort_respects_switch_and_vr_flag(tmp_path: Path) -> None:
    settings = _settings(tmp_path, vr_adaptive_effort=False)
    orchestrator = ChatOrchestrator(
        settings, MaryDatabase(settings.database_path, root=settings.root)
    )
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    options = ConversationOptions(effort="medium", vr_enabled=True)

    switched_off = orchestrator._apply_adaptive_effort(
        conversation_id, options, True, _intent(purpose="training_manual"), None
    )
    assert switched_off.effort == "medium"

    vr_off = orchestrator._apply_adaptive_effort(
        conversation_id, options, False, _intent(purpose="training_manual"), None
    )
    assert vr_off.effort == "medium"

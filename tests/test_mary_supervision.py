from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import (
    EvidenceBundle,
    EvidenceCandidate,
    KnowledgeDocument,
    QueryProfile,
    SourceSearchReport,
)
from vrsoft_extractor.mary.supervision import (
    EvidenceClaim,
    FinalDraft,
    FinalResponseValidation,
    MergedEvidence,
    RefinementReason,
    ResponseContract,
    SupervisorAssessment,
    _internal_leaks,
    analyze_response_intent,
    apply_response_mode,
    build_controlled_failure,
    build_response_contract,
    combine_final_validations,
    combine_supervision,
    deterministic_supervision,
    parse_final_draft,
    parse_worker_report,
    render_sources,
    validate_final_response,
)


def _profile(query: str) -> QueryProfile:
    return QueryProfile(
        query=query,
        intents={"functional": 0.1, "process": 0.8, "technical_schema": 0.1},
        module="ADM_FIN_ESTOQUE",
        answer_type="process",
        terms=("entrada", "nota", "fiscal"),
    )


def test_training_intent_separates_presentation_depth_from_task_difficulty() -> None:
    request = (
        "Me dê um passo a passo mais detalhado para fins de treinamento, "
        "com detalhes bem minuciosos."
    )
    intent = analyze_response_intent(request, _profile(request))
    contract = build_response_contract(intent)

    assert intent.purpose == "training_manual"
    assert intent.requested_detail == "very_high"
    assert contract.minimum_steps == 6
    assert contract.minimum_words >= 250
    assert "problemas comuns" in contract.must_include


def test_short_follow_up_inherits_training_purpose_from_conversation() -> None:
    intent = analyze_response_intent(
        "Explique melhor e com mais detalhes.",
        _profile("entrada de nota"),
        conversation_context=(
            "user: Estou preparando um treinamento de entrada de nota fiscal.\n"
            "assistant: Posso organizar o procedimento."
        ),
    )

    assert intent.purpose == "training_manual"
    assert intent.requested_detail == "very_high"


def test_complete_flow_request_creates_a_step_by_step_contract() -> None:
    request = "Crie um fluxo completo do processo de entrada de nota."
    intent = analyze_response_intent(request, _profile(request))
    contract = build_response_contract(intent)

    assert intent.requires_step_by_step is True
    assert intent.requested_detail == "high"
    assert contract.minimum_steps >= 3
    assert "passo a passo" in contract.must_include


def test_implementation_intent_has_mapping_diff_risk_and_validation_contract() -> None:
    request = "Planeje a implantação com migração e mapeamento de dados."
    intent = analyze_response_intent(request, _profile(request))
    contract = build_response_contract(intent)

    assert intent.purpose == "implementation"
    assert intent.audience == "implementation_team"
    assert intent.requires_step_by_step is True
    assert contract.minimum_steps == 5
    assert "mapeamento de dados" in contract.must_include
    assert "diferenças de schema ou configuração" in contract.must_include
    assert "riscos e plano de reversão" in contract.must_include


def test_explicit_senior_response_modes_override_presentation_not_sources() -> None:
    base = analyze_response_intent("Como funciona a venda?", _profile("venda"))

    training = apply_response_mode(base, "training")
    support = apply_response_mode(base, "support")
    implementation = apply_response_mode(base, "implementation")

    assert training.purpose == "training_manual"
    assert training.audience == "beginner"
    assert support.purpose == "troubleshooting"
    assert support.technical_level == "high"
    assert implementation.purpose == "implementation"
    assert implementation.audience == "implementation_team"
    assert all(
        item.requires_sources for item in (training, support, implementation)
    )
    assert apply_response_mode(base, "invalid") == base


def test_deterministic_supervisor_rejects_ungrounded_structured_fact() -> None:
    request = "Como dar entrada de nota?"
    contract = build_response_contract(
        analyze_response_intent(request, _profile(request))
    )
    assessment = deterministic_supervision(
        MergedEvidence(
            claims=(
                EvidenceClaim(
                    "A finalização sempre atualiza o financeiro.",
                    kind="fact",
                    confidence=0.9,
                ),
            )
        ),
        contract,
        has_retrieved_sources=True,
    )

    assert assessment.verdict == "revise"
    assert RefinementReason.UNSUPPORTED_CLAIMS in assessment.reasons
    assert assessment.unsupported_claims


def test_supervisor_does_not_invent_an_unrouted_source_lane() -> None:
    request = "Como funciona a rotina ZX742?"
    contract = build_response_contract(
        analyze_response_intent(request, _profile(request))
    )
    assessment = deterministic_supervision(
        MergedEvidence(
            steps=("Conferir o comportamento documentado.",),
            source_reports=(
                SourceSearchReport("wiki", "found"),
                SourceSearchReport("kb", "exhausted"),
            ),
        ),
        contract,
        has_retrieved_sources=True,
    )

    assert assessment.verdict == "approve"
    assert assessment.reasons == ()
    assert assessment.missing_required_topics == ()


def test_terminal_exhausted_lanes_do_not_trigger_pointless_refinement() -> None:
    contract = ResponseContract(
        purpose="guidance",
        audience="operational_user",
        technical_level="low_to_medium",
        detail_level="normal",
        requires_sources=False,
    )
    assessment = deterministic_supervision(
        MergedEvidence(
            source_reports=tuple(
                SourceSearchReport(source, "exhausted")
                for source in ("wiki", "kb", "schema")
            )
        ),
        contract,
        has_retrieved_sources=False,
    )

    assert assessment.verdict == "approve"
    assert assessment.reasons == ()


def test_supervisor_accepts_terminal_module_sources_without_schema_lane() -> None:
    contract = ResponseContract(
        purpose="guidance",
        audience="operational_user",
        technical_level="low_to_medium",
        detail_level="normal",
        requires_sources=False,
    )
    reports = [
        SourceSearchReport(source, "found", module=module)
        for module in ("Fiscal", "PDV")
        for source in ("wiki", "kb")
    ]

    assessment = deterministic_supervision(
        MergedEvidence(
            steps=("Consolidação modular parcial.",),
            source_reports=tuple(reports),
        ),
        contract,
        has_retrieved_sources=True,
    )

    assert assessment.verdict == "approve"
    assert assessment.reasons == ()
    assert assessment.missing_required_topics == ()


def test_nonblocking_gaps_and_contextual_conflicts_do_not_force_refinement() -> None:
    contract = build_response_contract(
        analyze_response_intent("Como gerar o SPED Fiscal?", _profile("SPED Fiscal"))
    )
    assessment = deterministic_supervision(
        MergedEvidence(
            claims=(
                EvidenceClaim(
                    "O SPED Fiscal pode ser exportado pela rotina documentada.",
                    evidence_ids=("kb:sped:1",),
                    confidence=0.9,
                ),
            ),
            steps=("Informe o período e clique em Exportar.",),
            gaps=("O artigo do plugin não documenta a instalação.",),
            conflicts=("O caminho padrão e o plugin são alternativas de acesso.",),
            source_reports=(
                SourceSearchReport("wiki", "found", module="Fiscal"),
                SourceSearchReport("kb", "found", module="Fiscal"),
            ),
        ),
        contract,
        has_retrieved_sources=True,
    )

    assert assessment.verdict == "approve"
    assert assessment.reasons == ()


def test_material_source_conflict_still_requires_refinement() -> None:
    assessment = deterministic_supervision(
        MergedEvidence(
            steps=("Conferir a rotina documentada.",),
            conflicts=(
                "Fontes semelhantes apresentam polaridade diferente; exige validação.",
            ),
            source_reports=(SourceSearchReport("wiki", "found"),),
        ),
        ResponseContract(
            purpose="guidance",
            audience="operational_user",
            technical_level="low_to_medium",
            detail_level="normal",
            requires_sources=False,
        ),
        has_retrieved_sources=True,
    )

    assert assessment.verdict == "revise"
    assert RefinementReason.CONFLICT_UNRESOLVED in assessment.reasons


def test_semantic_supervisor_cannot_expand_scope_beyond_the_contract() -> None:
    deterministic = SupervisorAssessment(
        verdict="approve",
        summary="Há material sustentado para o procedimento principal.",
        confidence=1.0,
    )
    semantic = SupervisorAssessment(
        verdict="revise",
        reasons=(
            RefinementReason.INCOMPLETE,
            RefinementReason.MISSING_SOURCES,
        ),
        missing_required_topics=(
            "Integrações, XML, DANFE e eventos posteriores não pedidos.",
        ),
        summary="Exigiu variantes adicionais.",
        confidence=0.9,
    )

    combined = combine_supervision(deterministic, semantic)

    assert combined.verdict == "approve"
    assert combined.reasons == ()
    assert combined.missing_required_topics == ()
    assert combined.summary == deterministic.summary


def test_final_validator_cannot_invent_structural_sections() -> None:
    deterministic = FinalResponseValidation(
        verdict="approve",
        summary="O contrato objetivo foi atendido.",
    )
    semantic = FinalResponseValidation(
        verdict="reject",
        reasons=(RefinementReason.INCOMPLETE,),
        missing_sections=("Todas as modalidades de importação.",),
        summary="Escopo ampliado indevidamente.",
    )

    combined = combine_final_validations(deterministic, semantic)

    assert combined.verdict == "approve"
    assert combined.reasons == ()
    assert combined.missing_sections == ()
    assert combined.summary == deterministic.summary


def test_one_global_schema_lane_covers_all_selected_modules() -> None:
    contract = ResponseContract(
        purpose="guidance",
        audience="operational_user",
        technical_level="low_to_medium",
        detail_level="normal",
        requires_sources=False,
    )
    reports = [
        SourceSearchReport(source, "found", module=module)
        for module in ("Fiscal", "PDV")
        for source in ("wiki", "kb")
    ]
    reports.append(SourceSearchReport("schema", "exhausted"))

    assessment = deterministic_supervision(
        MergedEvidence(
            steps=("Consolidação multimódulo concluída.",),
            source_reports=tuple(reports),
        ),
        contract,
        has_retrieved_sources=True,
    )

    assert assessment.verdict == "approve"
    assert assessment.reasons == ()


def test_worker_report_repairs_fenced_json_with_trailing_commas() -> None:
    report = parse_worker_report(
        """```json
        {"findings": [], "steps": ["Validar a rotina",],}
        ```""",
        worker_id="vr_wiki_researcher",
        worker_name="VR Wiki",
    )

    assert report.structured is True
    assert report.steps == ("Validar a rotina",)


def test_exhausted_source_lane_discards_provider_hallucinations() -> None:
    report = parse_worker_report(
        json.dumps(
            {
                "findings": [
                    {
                        "claim": "A fonte confirma uma regra inexistente.",
                        "evidence_ids": [],
                        "kind": "fact",
                    }
                ],
                "steps": ["Aplicar a regra inexistente."],
            }
        ),
        worker_id="vr_schema_researcher",
        worker_name="VR Schema",
        source_report=SourceSearchReport("schema", "exhausted"),
    )

    assert report.findings == ()
    assert report.steps == ()
    assert any("descartad" in warning for warning in report.warnings)


def test_controlled_failure_hides_internal_ids_and_deduplicates_gaps() -> None:
    response = build_controlled_failure(
        SupervisorAssessment(
            verdict="reject",
            missing_required_topics=(
                "Texto completo da página wiki:3558:299 para confirmar o campo observação.",
                "Texto completo da página wiki:3508:258 para confirmar o campo observação.",
                "O worker E2 precisa repetir o retrieval.",
            ),
        )
    )

    assert "wiki:" not in response
    assert "E2" not in response
    assert "worker" not in response.casefold()
    assert response.casefold().count("campo observação") == 1




def test_worker_report_rejects_unprovided_provenance() -> None:
    report = parse_worker_report(
        json.dumps(
            {
                "findings": [
                    {
                        "claim": "A entrada atualiza o estoque.",
                        "evidence_ids": ["wiki:entrada:1", "inventada:999"],
                        "kind": "fact",
                        "confidence": 0.9,
                    }
                ],
                "sources": ["wiki:entrada:1", "inventada:999"],
            }
        ),
        worker_id="vr_grace",
        worker_name="VR Grace",
        allowed_evidence_ids=("wiki:entrada:1",),
    )

    assert report.findings[0].evidence_ids == ("wiki:entrada:1",)
    assert report.sources == ("wiki:entrada:1",)
    assert any("descartad" in warning for warning in report.warnings)


def test_final_validator_rejects_shallow_training_and_internal_metadata() -> None:
    request = "Crie um treinamento bem minucioso sobre entrada de nota."
    contract = build_response_contract(
        analyze_response_intent(request, _profile(request))
    )
    validation = validate_final_response(
        FinalDraft(
            "Segundo E1, o pacote de evidências trouxe um trecho truncado.\n\n"
            "1. Carregue.\n2. Confira.\n3. Finalize.",
            ("wiki:entrada:1",),
        ),
        contract,
        user_message=request,
    )

    assert validation.verdict == "revise"
    assert RefinementReason.INTERNAL_METADATA_LEAK in validation.reasons
    assert RefinementReason.INCOMPLETE in validation.reasons
    assert validation.leaks


def test_sources_are_rendered_deterministically_only_at_the_end() -> None:
    candidate = EvidenceCandidate(
        evidence_id="wiki:entrada:1",
        source="wiki",
        source_id="entrada",
        document_id=1,
        chunk_id=1,
        title="Manual Nota Fiscal Entrada",
        heading="Entrada",
        content_type="process",
        module="ADM_FIN_ESTOQUE",
        product="VRMaster",
        excerpt="Procedimento validado.",
        url="https://wiki.example/entrada",
        local_path="conhecimento/segredo.md",
    )
    bundle = EvidenceBundle(_profile("entrada"), candidates=(candidate,))

    rendered = render_sources(
        "Resposta operacional.",
        ("wiki:entrada:1", "wiki:entrada:1", "fonte:inexistente"),
        bundle,
    )

    assert rendered.startswith("Resposta operacional.")
    assert rendered.endswith(
        "## Fontes\n\n- [Manual Nota Fiscal Entrada](https://wiki.example/entrada)"
    )
    assert rendered.count("Manual Nota Fiscal Entrada") == 1
    assert "segredo.md" not in rendered




def _simple_contract() -> ResponseContract:
    return ResponseContract(
        purpose="guidance",
        audience="operational_user",
        technical_level="low_to_medium",
        detail_level="normal",
    )


def test_parse_final_draft_rescues_envelope_with_unescaped_inner_quotes() -> None:
    raw = (
        '{"answer_markdown": "Abra **Nota Saída > Emissão** e clique em "Incluir" '
        '(ou tecla "F2").\\n\\n## Resultado esperado\\n\\n- **NF:** nota '
        'transmitida.", "used_evidence_ids": ["e1"]}'
    )
    draft = parse_final_draft(raw, allowed_evidence_ids=("e1",))
    assert not draft.answer_markdown.lstrip().startswith('{"')
    assert draft.answer_markdown.startswith("Abra **Nota Saída")
    assert '"Incluir"' in draft.answer_markdown
    assert "\n\n" in draft.answer_markdown
    assert draft.used_evidence_ids == ("e1",)


def test_parse_final_draft_rescues_envelope_without_used_ids_key() -> None:
    raw = '{"answer_markdown": "Resposta com "aspas" internas e \\n quebra."}'
    draft = parse_final_draft(raw, allowed_evidence_ids=())
    assert draft.answer_markdown == 'Resposta com "aspas" internas e \n quebra.'


def test_parse_final_draft_keeps_valid_envelope_and_plain_markdown() -> None:
    valid = '{"answer_markdown": "# Resposta\\n\\nTexto.", "used_evidence_ids": ["e1"]}'
    draft = parse_final_draft(valid, allowed_evidence_ids=("e1", "e2"))
    assert draft.answer_markdown == "# Resposta\n\nTexto."
    assert draft.used_evidence_ids == ("e1",)
    plain = "Resposta em markdown simples com **negrito**."
    draft_plain = parse_final_draft(plain, allowed_evidence_ids=("e1",))
    assert draft_plain.answer_markdown == plain


def test_unrecoverable_envelope_is_flagged_as_internal_leak() -> None:
    raw = '{"answer_markdown": "Inicio de resposta truncada sem fechamento'
    draft = parse_final_draft(raw, allowed_evidence_ids=())
    assert draft.answer_markdown == raw
    leaks = _internal_leaks(draft.answer_markdown, "pergunta do usuário")
    assert any("JSON" in item for item in leaks)
    violations = validate_final_response(
        draft, _simple_contract(), user_message="pergunta do usuário"
    )
    assert violations.verdict != "approve"
    assert RefinementReason.INTERNAL_METADATA_LEAK in violations.reasons


def test_good_answer_is_not_flagged_by_envelope_patterns() -> None:
    answer = (
        "# Título\n\n## Passo a passo\n\n"
        '1. Clique em "Incluir" para iniciar.\n'
        "2. Confirme os dados e transmita.\n\n"
        "https://exemplo.com/wiki/pagina"
    )
    assert _internal_leaks(answer, "pergunta") == []
    validation = validate_final_response(
        FinalDraft(answer, ()), _simple_contract(), user_message="pergunta"
    )
    assert RefinementReason.INTERNAL_METADATA_LEAK not in validation.reasons

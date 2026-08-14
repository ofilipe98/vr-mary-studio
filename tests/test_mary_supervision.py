from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import (
    EvidenceBundle,
    EvidenceCandidate,
    KnowledgeDocument,
    ModelRef,
    OrchestrationOptions,
    QueryProfile,
    RuntimeEvent,
    SourceSearchReport,
)
from vrsoft_extractor.mary.multiagent import (
    AGENT_CATALOG,
    VrAgentAssignment,
    VrPlan,
    bind_response_contract,
    heuristic_difficulty,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.providers import AgentProvider
from vrsoft_extractor.mary.supervision import (
    EvidenceClaim,
    FinalDraft,
    MergedEvidence,
    RefinementReason,
    ResponseContract,
    SupervisorAssessment,
    analyze_response_intent,
    build_controlled_failure,
    build_response_contract,
    deterministic_supervision,
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
    assert heuristic_difficulty(request) >= 2


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


def test_supervisor_waits_for_all_source_lanes_to_reach_terminal_status() -> None:
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

    assert assessment.verdict == "revise"
    assert RefinementReason.MISSING_SOURCES in assessment.reasons
    assert "Concluir a validação da trilha SCHEMA." in assessment.missing_required_topics


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


def test_supervisor_checks_module_sources_and_one_global_schema_lane() -> None:
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

    assert assessment.verdict == "revise"
    assert (
        "Concluir a validação da trilha VR DBA/SCHEMA."
        in assessment.missing_required_topics
    )


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


def test_binding_contract_preserves_worker_identity_and_adds_structured_task() -> None:
    model = ModelRef("codex", "sol", "Sol")
    worker = AGENT_CATALOG["vr_grace"]
    assignment = VrAgentAssignment(
        "wiki_lookup",
        worker,
        model,
        "Levantar o funcionamento documentado.",
        "Adequação à fonte Wiki.",
        required=True,
        priority=80,
    )
    plan = VrPlan(
        2,
        "Moderada",
        "Pesquisa documental.",
        "specialized",
        (assignment,),
    )
    intent = analyze_response_intent("Como fazer?", _profile("Como fazer?"))
    contract = build_response_contract(intent)

    bound = bind_response_contract(plan, intent, contract)
    result = bound.agents[0]

    assert result.id == "wiki_lookup"
    assert result.agent is worker
    assert result.agent.id == "vr_grace"
    assert result.agent.label == "VR Grace"
    assert result.task_spec is not None
    assert result.task_spec.required is True
    assert result.task_spec.objective == assignment.task


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


class GatedSupervisionProvider(AgentProvider):
    name = "codex"

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.evidence_id = ""
        self.main_drafts = 0

    def available(self) -> bool:
        return True

    def list_models(self) -> list[dict[str, Any]]:
        return []

    def start_conversation(self, conversation_id, model, effort, workspace, options=None):
        return f"native:{conversation_id}"

    def resume_conversation(self, conversation_id, native_id, model, effort, workspace, options=None):
        return native_id

    def send_message(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        message: str,
        callback: Callable[[RuntimeEvent], None],
        options=None,
        skills=None,
    ) -> None:
        self.sent.append(
            {"conversation_id": conversation_id, "message": message, "effort": effort}
        )
        callback(
            RuntimeEvent(
                conversation_id,
                "turn_started",
                payload={"turn": {"id": f"turn:{len(self.sent)}"}},
            )
        )
        if ":vr_orchestrator_plan:" in conversation_id:
            output = json.dumps(
                {
                    "difficulty": {"level": 2, "summary": "Treinamento detalhado."},
                    "strategy": "specialized",
                    "agents": [
                        {
                            "id": "kb_training",
                            "agent": "vr_rocky",
                            "model": "codex:sol",
                            "effort": "medium",
                            "task": "Levantar o procedimento completo para treinamento.",
                            "required": True,
                            "priority": 90,
                        },
                        {
                            "id": "final",
                            "agent": "vr_synthesizer",
                            "model": "codex:sol",
                            "effort": "high",
                            "task": "Produzir o treinamento final.",
                        },
                    ],
                },
                ensure_ascii=False,
            )
        elif ":vr_orchestrator_validation:" in conversation_id:
            output = json.dumps(
                {
                    "verdict": "approve",
                    "reasons": [],
                    "refinement_tasks": [],
                    "summary": "Material suficiente.",
                    "confidence": 0.95,
                }
            )
        elif ":vr_orchestrator_final_validation:" in conversation_id:
            output = json.dumps(
                {
                    "verdict": "approve",
                    "reasons": [],
                    "missing_sections": [],
                    "leaks": [],
                    "unsupported_claims": [],
                    "summary": "Apresentação adequada.",
                }
            )
        elif ":vr:" in conversation_id:
            match = re.search(r"\[E\d+ \| ([^\]]+)\]", message)
            if match:
                self.evidence_id = match.group(1)
            output = json.dumps(
                {
                    "findings": [
                        {
                            "claim": "O procedimento exige conferência antes da finalização.",
                            "evidence_ids": [self.evidence_id],
                            "kind": "fact",
                            "confidence": 0.95,
                        }
                    ],
                    "steps": [
                        "Acessar o menu de entrada.",
                        "Conferir fornecedor, itens, tributação e vencimentos.",
                        "Finalizar e validar os efeitos.",
                    ],
                    "conflicts": [],
                    "missing_information": [],
                    "warnings": [],
                    "sources": [self.evidence_id],
                },
                ensure_ascii=False,
            )
        else:
            self.main_drafts += 1
            if self.main_drafts == 1:
                output = json.dumps(
                    {
                        "answer_markdown": (
                            "Segundo E1, o pacote de evidências confirma o procedimento."
                        ),
                        "used_evidence_ids": [self.evidence_id],
                    },
                    ensure_ascii=False,
                )
            else:
                output = json.dumps(
                    {
                        "answer_markdown": _approved_training_answer(),
                        "used_evidence_ids": [self.evidence_id],
                    },
                    ensure_ascii=False,
                )
        callback(RuntimeEvent(conversation_id, "assistant_delta", output))
        callback(
            RuntimeEvent(
                conversation_id,
                "turn_completed",
                payload={"turn": {"id": f"turn:{len(self.sent)}"}},
            )
        )

    def interrupt(self, conversation_id: str) -> None:
        return None

    def approve_action(self, request_id, approved, session=False, request=None) -> None:
        return None

    def release_conversation(self, conversation_id, native_id, *, delete_native=False) -> None:
        return None

    def close(self) -> None:
        return None


def _approved_training_answer() -> str:
    explanation = (
        "Durante o treinamento, explique o motivo de cada conferência e peça ao "
        "participante que compare os dados apresentados com o documento do fornecedor. "
        "Essa prática reduz erros operacionais e ajuda a identificar divergências antes "
        "que a operação produza efeitos no estoque e no financeiro. "
    )
    return f"""## Objetivo do processo

Registrar corretamente uma nota recebida e preparar seus efeitos operacionais.

## Quando utilizar

Use este procedimento quando a empresa receber uma nota fiscal de compra.

## Pré-requisitos

Confirme que fornecedor, produtos, operação e condições de pagamento estão cadastrados.

## Caminho de menu

Acesse o menu de Nota Fiscal e abra a rotina de entrada documentada para a operação.

## Passo a passo detalhado

1. Localize a nota recebida e confirme a identificação do fornecedor.
2. Confira número, série, datas e chave do documento antes de avançar.
3. Compare produtos, unidades, quantidades, valores e descontos com a nota.
4. Verifique tributação, tipo de entrada e eventuais divergências apresentadas.
5. Confira parcelas, vencimentos e totais financeiros antes da confirmação.
6. Finalize somente depois de revisar todos os avisos e dados obrigatórios.

## O que conferir em cada etapa

Fornecedor, itens, valores, tributação, vencimentos e mensagens devem corresponder ao documento.

## Problemas comuns

Cadastros incompletos, operação incorreta e divergência de tributação exigem validação antes de finalizar.

## Resultado esperado

Ao finalizar, a entrada deve ficar registrada com os efeitos previstos pela parametrização confirmada.

## Como validar se deu certo

Consulte o documento registrado e verifique os resultados esperados no estoque e no financeiro.

{explanation * 9}"""


def test_rejected_draft_is_rewritten_privately_before_user_sees_it(
    tmp_path: Path,
) -> None:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "vr").resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.app_dir.mkdir(parents=True)
    settings.old_root.mkdir(parents=True)
    settings.ensure_dirs()
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="entrada-treinamento",
            title="Manual Nota Fiscal Entrada",
            url="https://wiki.example/entrada",
            markdown=(
                "A entrada exige conferência de fornecedor, produtos, tributação, "
                "parcelas e vencimentos antes da finalização."
            ),
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="entrada-treinamento",
            local_path="conhecimento/ADM_FIN_ESTOQUE/Wiki/entrada.md",
        )
    )
    orchestrator = ChatOrchestrator(settings, database)
    provider = GatedSupervisionProvider()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            mode="standard",
            model_pool=(ModelRef("codex", "sol", "Sol"),),
        ),
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(
        conversation_id,
        "Crie um passo a passo bem minucioso para treinamento de entrada de nota fiscal.",
        callback,
        use_vr=True,
    )

    assert completed.wait(10)
    visible = [event.text for event in events if event.kind == "assistant_delta"]
    assert len(visible) == 1
    assert "Segundo E1" not in visible[0]
    assert "pacote de evidências" not in visible[0]
    assert visible[0].rstrip().endswith(
        "- [Manual Nota Fiscal Entrada](https://wiki.example/entrada)"
    )
    assert provider.main_drafts == 2
    plan_event = next(event for event in events if event.kind == "plan_created")
    assert plan_event.payload["routing_scope"] == "single_module"
    assert plan_event.payload["runtime_stages"][0]["label"] == "Supervisor global"
    planned = {
        item["id"]: item for item in plan_event.payload["plan"]["agents"]
    }
    assert planned["vr_atlas"]["module"] == "ADM_FIN_ESTOQUE"
    assert {
        "vr_atlas__wiki",
        "vr_atlas__kb",
        "vr_dba",
        "vr_dba__schema",
    }.issubset(planned)
    assert all(
        planned[identifier]["parent_id"] == "vr_atlas"
        for identifier in (
            "vr_atlas__wiki",
            "vr_atlas__kb",
        )
    )
    assert planned["vr_dba__schema"]["parent_id"] == "vr_dba"
    event_positions = {
        (event.kind, str(event.payload.get("agent_id") or "")): index
        for index, event in enumerate(events)
    }
    assert event_positions[("agent_started", "vr_atlas")] > max(
        event_positions[("agent_completed", identifier)]
        for identifier in (
            "vr_atlas__wiki",
            "vr_atlas__kb",
        )
    )
    assert event_positions[("agent_started", "vr_dba")] > event_positions[
        ("agent_completed", "vr_dba__schema")
    ]
    assert any(event.kind == "response_rewrite_started" for event in events)
    assert any(event.kind == "final_validation_completed" for event in events)
    assert any(event.kind == "response_contract_created" for event in events)
    with database.connect() as connection:
        persisted = connection.execute(
            "SELECT text FROM runtime_events WHERE conversation_id=? AND kind='assistant_delta'",
            (conversation_id,),
        ).fetchall()
        citations = connection.execute(
            "SELECT count(*) FROM source_citations WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()[0]
    assert [row["text"] for row in persisted] == visible
    assert citations == 1

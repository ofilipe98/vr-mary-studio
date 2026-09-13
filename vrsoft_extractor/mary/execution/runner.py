"""
Execution runner for VR Mary Studio.

Extracts the multi-stage research fan-out, worker execution,
budget tracking, cancellation, and draft synthesis coordination
out of ChatOrchestrator. Publication and provider lifecycle remain with the host.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Any, Callable

from ..config import MarySettings
from ..models import (
    ConversationOptions,
    EvidenceBundle,
    EvidenceCandidate,
    ModelRef,
)
from ..providers import AgentProvider, ProviderError, ProviderRateLimited
from ..research_fanout import (
    GLOBAL_MODULE_LABEL,
    MAX_PARALLEL_RESEARCHERS,
    RESEARCH_ATTEMPTS,
    RESEARCH_EFFORT,
    RESEARCH_RETRY_BACKOFF_SECONDS,
    RESEARCH_STAGGER_SECONDS,
    ROLE_BY_FANOUT_MODULE,
    SCHEMA_MODULE_LABEL,
    ModuleResearch,
    available_research_pool,
    build_researcher_prompt,
    build_synthesis_prompt as build_fanout_synthesis_prompt,
    fanout_payload,
    merge_module_research,
    parse_researcher_output,
    resolve_model_ref,
)
from ..supervision import (
    FinalResponseValidation,
    RefinementReason,
    ResponseContract,
    ResponseIntent,
    ResponseViolation,
    WorkerReport,
    build_rewrite_prompt,
    decide_adaptive_effort,
    parse_final_draft,
    validate_fanout_draft,
)
from .budget import CallReservationError, ExecutionBudget
from .cancellation import ExecutionCancelledError
from .repository import ResearchRepository, compute_step_input_hash
from .contracts import (
    ExecutionContext,
    ResearchFanoutPlan,
    ResearchFanoutResult,
    ResearchStagePlan,
)
from ..retrieval.code_retrieval import (
    _code_scope_queries as _code_scope_queries,
    retrieve_code_candidates,
)

LOGGER = logging.getLogger(__name__)


class ExecutionRunner:
    """Coordinates fanout stage planning, budget tracking, parallel execution, and response synthesis."""

    def __init__(
        self,
        settings: MarySettings,
        providers: dict[str, AgentProvider],
        retrieval: Any,
        *,
        event_emitter: Callable[[str, str, str, dict[str, Any]], None],
        ephemeral_turn_runner: Callable[..., str],
        buffered_turn_runner: Callable[..., tuple[str, dict[str, Any], dict[str, Any]]],
        looks_like_final_envelope: Callable[[str], bool],
        operational_reviewer: Callable[..., tuple[ResponseViolation, ...]] | None = None,
        research_pool: tuple[ModelRef, ...] = (),
        research_max_parallel: int = 4,
        repository: ResearchRepository | None = None,
        collect_evidence: Callable[[str], tuple[EvidenceCandidate, ...]] | None = None,
    ):
        self.settings = settings
        self.providers = providers
        self.retrieval = retrieval
        self.emit_event = event_emitter
        self.run_ephemeral_turn = ephemeral_turn_runner
        self.run_buffered_main_turn = buffered_turn_runner
        self.looks_like_final_envelope = looks_like_final_envelope
        self.operational_reviewer = operational_reviewer
        self.research_pool = research_pool
        self.research_max_parallel = research_max_parallel
        self.repository = repository
        self.collect_evidence = collect_evidence

    def plan_fanout(
        self,
        run_id: str,
        modules: tuple[str, ...],
        main_model: ModelRef,
        synthesis_effort: str,
        *,
        code_analysis_enabled: bool = False,
        code_analysis_release: str = "current",
        code_analysis_manifest_sha256: str = "",
        application_contexts: list[dict[str, Any]] | None = None,
    ) -> ResearchFanoutPlan:
        """Construct the stage plans for researcher workers and synthesis."""
        available_providers = {
            name
            for name, candidate in self.providers.items()
            if candidate.available()
        }
        model_pool = available_research_pool(
            self.research_pool,
            available_providers,
        ) or (main_model,)
        max_parallel = max(1, min(MAX_PARALLEL_RESEARCHERS, self.research_max_parallel))

        def model_for_researcher(index: int) -> ModelRef:
            return model_pool[index % len(model_pool)]

        runtime_stages: list[dict[str, Any]] = [
            ResearchStagePlan(
                id=f"fanout_{module.casefold()}",
                agent_id=f"fanout_{module.casefold()}",
                label=f"Pesquisador {module}",
                role="module_research",
                module="" if module in {SCHEMA_MODULE_LABEL, GLOBAL_MODULE_LABEL} else module,
                source="schema" if module == SCHEMA_MODULE_LABEL else "wiki,kb",
                task=(
                    f"Pesquisar e validar evidências do módulo {module} "
                    "para a solicitação, sem sair do escopo."
                ),
                reason="Especialista do módulo executando em paralelo.",
                model=model_for_researcher(index).to_dict(),
                effort=RESEARCH_EFFORT,
                final=False,
                required=True,
                priority=90,
                worker_id=f"fanout_{module.casefold()}",
                worker_name=f"Pesquisador {module}",
            ).to_dict()
            for index, module in enumerate(modules)
        ]
        if code_analysis_enabled:
            runtime_stages.append(
                ResearchStagePlan(
                    id="fanout_codigo",
                    agent_id="fanout_codigo",
                    label="Agente de Código",
                    role="code_research",
                    module="Código",
                    source="code",
                    task=(
                        "Consultar o índice da release selecionada somente depois "
                        "que os pesquisadores delimitarem o escopo."
                    ),
                    reason="Análise de JAR habilitada explicitamente.",
                    model=model_for_researcher(len(modules)).to_dict(),
                    effort=RESEARCH_EFFORT,
                    final=False,
                    required=False,
                    priority=95,
                    worker_id="fanout_codigo",
                    worker_name="Agente de Código",
                    metadata={
                        "run_id": run_id,
                        "release_id": code_analysis_release,
                        "release_manifest_sha256": code_analysis_manifest_sha256,
                        "application_contexts": application_contexts,
                    },
                ).to_dict()
            )
        runtime_stages.append(
            ResearchStagePlan(
                id="fanout_synthesis",
                agent_id="fanout_synthesis",
                label="Síntese final",
                role="final_synthesis",
                module="",
                source="",
                task="Consolidar os achados dos pesquisadores na resposta final com fontes.",
                reason="Consolidação única das frentes paralelas.",
                model=main_model.to_dict(),
                effort=synthesis_effort,
                final=True,
                required=True,
                priority=100,
                worker_id="fanout_synthesis",
                worker_name="Síntese final",
            ).to_dict()
        )
        return ResearchFanoutPlan(
            run_id=run_id,
            modules=modules,
            runtime_stages=runtime_stages,
            max_parallel=max_parallel,
        )

    def execute_fanout(self, context: ExecutionContext, **kwargs: Any) -> ResearchFanoutResult:
        stopped = threading.Event()
        def heartbeat():
            while not stopped.wait(1.0):
                if self.repository and context.metadata.get("_owner_token"):
                    try:
                        self.repository.checkpoint_budget(context.run_id, context.metadata["_owner_token"], context.budget.to_dict())
                    except Exception:
                        LOGGER.exception("Falha no checkpoint periódico de orçamento")
        thread = threading.Thread(target=heartbeat, daemon=True, name="research-checkpoint")
        thread.start()
        try:
            return self._execute_fanout(context=context, **kwargs)
        except Exception as exc:
            if self.repository is not None and context.metadata.get("_repository_claimed"):
                self.repository.update_run_status(
                    context.run_id,
                    "cancelled" if isinstance(exc, ExecutionCancelledError) else "failed",
                    budget_snapshot=context.budget.to_dict(),
                    owner_token=context.metadata.get("_owner_token"),
                )
            raise
        finally:
            stopped.set()
            thread.join(2)

    def _execute_fanout(
        self,
        context: ExecutionContext,
        conversation: dict[str, Any],
        native_id: str,
        provider: AgentProvider,
        options: ConversationOptions,
        skills: list[dict[str, Any]],
        bundle: EvidenceBundle,
        intent: ResponseIntent,
        contract: ResponseContract,
        modules: tuple[str, ...],
        *,
        code_analysis_enabled: bool = False,
        code_analysis_release: str = "current",
        code_analysis_manifest_sha256: str = "",
        application_contexts: list[dict[str, Any]] | None = None,
        search_scope: str = "",
        request: str = "",
    ) -> ResearchFanoutResult:
        """Executes parallel researchers and final synthesis with budget and cancellation."""
        def emit_event(cid, kind, text, payload):
            self.emit_event(cid, kind, text, {**payload, "run_id": context.run_id})

        cid = context.conversation_id
        run_id = context.run_id
        context.check_cancelled()
        resume_run_id = str(context.metadata.get("resume_run_id") or "")
        if resume_run_id:
            if resume_run_id != run_id:
                raise ValueError("A retomada deve preservar o identificador da investigação.")
            previous = self.repository.get_run(resume_run_id) if self.repository else None
            if not previous or previous["conversation_id"] != cid or previous["request_text"] != request:
                raise ValueError("Retomada incompatível com a conversa ou solicitação")
            from .repository import CONTRACT_VERSION
            if previous["contract_version"] != CONTRACT_VERSION or previous["status"] == "running":
                raise ValueError("Execução incompatível ou ainda em andamento")
            context.budget = ExecutionBudget.from_snapshot(json.loads(previous["budget_json"]))
            if context.metadata.get("grant_budget"):
                context.budget.max_calls += 15
                context.budget.max_active_seconds += 300

        main_model = resolve_model_ref(
            str(conversation["provider"]),
            str(conversation.get("model") or ""),
            (),
        )
        allowed_ids = tuple(item.evidence_id for item in bundle.candidates)
        synthesis_effort = decide_adaptive_effort(
            intent,
            bundle,
            options.effort,
            allow_max=options.vr_mode == "ultra",
        ).effort

        plan = self.plan_fanout(
            run_id,
            modules,
            main_model,
            synthesis_effort,
            code_analysis_enabled=code_analysis_enabled,
            code_analysis_release=code_analysis_release,
            code_analysis_manifest_sha256=code_analysis_manifest_sha256,
            application_contexts=application_contexts,
        )

        emit_event(
            cid,
            "research_started",
            f"Pesquisa paralela iniciada em {len(modules)} frentes.",
            {
                "run_id": run_id,
                "modules": list(modules),
                "orchestrator": main_model.to_dict(),
                "budget": context.budget.to_dict(),
            },
        )
        emit_event(
            cid,
            "plan_created",
            f"Plano modular: {len(modules)} pesquisadores + síntese.",
            {
                "run_id": run_id,
                "runtime_stages": plan.runtime_stages,
                "plan": {"agents": []},
            },
        )
        if self.repository is not None:
            if resume_run_id == run_id:
                self.repository.claim_resume(run_id, cid, execution_id=context.owner_message_id or 0)
            else:
                self.repository.create_run(run_id, cid, {"stages": plan.runtime_stages}, request, context.budget.to_dict())
            context.metadata["_repository_claimed"] = True
            context.metadata["_owner_token"] = self.repository.claim_token(run_id)
            self.repository.set_context(run_id, {k: v for k, v in context.metadata.items() if not k.startswith("_")}, context.owner_message_id or 0)

        fanout_start_monotonic = time.monotonic()
        checkpoint_lock = threading.RLock()

        def acquire_call(**kwargs):
            with checkpoint_lock:
                timeout = context.budget.acquire_call(**kwargs)
                if self.repository:
                    try:
                        self.repository.update_run_status(run_id, "running", budget_snapshot=context.budget.to_dict(), owner_token=context.metadata["_owner_token"])
                    except Exception:
                        context.budget.release_call()
                        raise
                return timeout

        def release_call():
            with checkpoint_lock:
                context.budget.release_call()
                if self.repository:
                    self.repository.update_run_status(run_id, "running", budget_snapshot=context.budget.to_dict(), owner_token=context.metadata["_owner_token"])

        def research_one(module: str, index: int) -> ModuleResearch:
            stagger_delay = RESEARCH_STAGGER_SECONDS * index
            if stagger_delay > 0:
                remaining = (
                    fanout_start_monotonic + stagger_delay - time.monotonic()
                )
                if remaining > 0:
                    if context.cancellation.wait(min(remaining, stagger_delay)):
                        return ModuleResearch(module=module, raw_error="Cancelado antes de iniciar")

            if context.cancellation.is_cancelled:
                return ModuleResearch(module=module, raw_error="Cancelado pelo usuário")

            worker_id = f"fanout_{module.casefold()}"
            stage = next(
                item for item in plan.runtime_stages if item["id"] == worker_id
            )
            researcher_model = ModelRef.from_mapping(stage["model"])
            emit_event(
                cid,
                "agent_started",
                f"Pesquisador {module} iniciado.",
                dict(stage),
            )
            sources = ("schema",) if module == SCHEMA_MODULE_LABEL else ("wiki", "kb")
            evidence_context = self.retrieval.prompt_for_role(
                bundle,
                ROLE_BY_FANOUT_MODULE.get(module, ""),
                module="" if module in {SCHEMA_MODULE_LABEL, GLOBAL_MODULE_LABEL} else module,
            )
            prompt = build_researcher_prompt(module, sources, request, evidence_context)
            stage_start_mono = time.monotonic()
            step_input_hash = compute_step_input_hash(module, prompt, {
                **stage["model"], "effort": stage["effort"],
                "evidence": [candidate.to_dict() for candidate in bundle.candidates],
                "workspace": str(context.workspace.resolve()),
                "release": code_analysis_release,
                "manifest": code_analysis_manifest_sha256,
                "application_contexts": application_contexts,
                "scope": search_scope,
                "permissions_and_sources": context.metadata.get("scope_signature", ""),
                "permissions": context.metadata.get("permissions", {}),
            })
            if self.repository is not None:
                try:
                    reusable = self.repository.find_reusable_step(
                        step_input_hash,
                        run_id=str(context.metadata.get("resume_run_id") or run_id),
                        conversation_id=cid,
                    )
                    if reusable is not None and "raw" in reusable.get("output", {}):
                        reused_result = parse_researcher_output(
                            reusable["output"]["raw"],
                            worker_id=worker_id,
                            worker_name=f"Pesquisador {module}",
                            module=module,
                            allowed_evidence_ids=allowed_ids,
                        )
                        if reused_result.succeeded and reused_result.report is not None:
                            claims = [claim.text for claim in reused_result.report.findings]
                            output_preview = f"[Reaproveitado] {len(claims)} achados. " + " ".join(claims)[:500]
                            emit_event(
                                cid,
                                "agent_completed",
                                f"Pesquisador {module} reaproveitado do cache.",
                                {**stage, "output": output_preview, "reused": True},
                            )
                            self.repository.save_step_result(
                                run_id,
                                stage["id"],
                                worker_id,
                                "module_research",
                                module,
                                step_input_hash,
                                "reused",
                                output=reusable["output"],
                                attempts=1,
                                duration_seconds=0.0,
                                owner_token=context.metadata["_owner_token"],
                            )
                            return reused_result
                except Exception as repo_exc:
                    LOGGER.warning("Erro ao verificar reaproveitamento: %s", repo_exc)
            if resume_run_id:
                emit_event(cid, "checkpoint_invalidated", f"{module}: sem etapa concluída compatível; pesquisa será refeita.",
                           {**stage, "reason": "request_model_permissions_or_sources_changed"})
            outcome: ModuleResearch | None = None

            for attempt in range(min(RESEARCH_ATTEMPTS, context.budget.max_retries_per_worker + 1)) :
                if context.cancellation.is_cancelled:
                    outcome = ModuleResearch(module=module, raw_error="Cancelado pelo usuário")
                    break

                # Reserve call from execution budget
                try:
                    timeout_sec = acquire_call(
                        is_synthesis=False,
                        requested_timeout=150.0 if attempt == 0 else 90.0,
                    )
                except CallReservationError as budget_exc:
                    LOGGER.warning("Pesquisador %s não pôde reservar chamada: %s", module, budget_exc)
                    outcome = ModuleResearch(module=module, raw_error=str(budget_exc))
                    break

                try:
                    if self.repository:
                        self.repository.save_step_result(run_id, stage["id"], worker_id, "module_research", module,
                            step_input_hash, "running", attempts=attempt + 1, owner_token=context.metadata["_owner_token"])
                    raw = self.run_ephemeral_turn(
                        cid,
                        run_id,
                        f"vr_fanout_{module.casefold()}",
                        researcher_model,
                        prompt,
                        context.workspace,
                        RESEARCH_EFFORT,
                        timeout_seconds=timeout_sec,
                    )
                except (ExecutionCancelledError, ProviderRateLimited):
                    context.cancellation.cancel("research_aborted")
                    raise
                except Exception as exc:
                    outcome = ModuleResearch(module=module, raw_error=str(exc))
                    LOGGER.warning(
                        "Pesquisador %s falhou (tentativa %s/%s): %s",
                        module,
                        attempt + 1,
                        RESEARCH_ATTEMPTS,
                        exc,
                    )
                else:
                    result = parse_researcher_output(
                        raw,
                        worker_id=worker_id,
                        worker_name=f"Pesquisador {module}",
                        module=module,
                        allowed_evidence_ids=allowed_ids,
                    )
                    if result.succeeded and result.report is not None:
                        claims = [claim.text for claim in result.report.findings]
                        output_preview = (
                            f"{len(claims)} achados. "
                            + " ".join(claims)
                        )[:600]
                        emit_event(
                            cid,
                            "agent_completed",
                            f"Pesquisador {module} concluído.",
                            {**stage, "output": output_preview},
                        )
                        if self.repository is not None:
                            try:
                                dur = time.monotonic() - stage_start_mono
                                out_p = {"raw": raw, "findings": [c.to_dict() for c in result.report.findings]}
                                self.repository.save_step_result(
                                    run_id,
                                    stage["id"],
                                    worker_id,
                                    "module_research",
                                    module,
                                    step_input_hash,
                                    "completed",
                                    output=out_p,
                                    attempts=attempt + 1,
                                    duration_seconds=dur,
                                    record_attempt=True,
                                    owner_token=context.metadata["_owner_token"],
                                )
                            except Exception as db_err:
                                raise ProviderError("O resultado não pôde ser confirmado no checkpoint") from db_err
                        return result
                    outcome = result
                    LOGGER.warning(
                        "Pesquisador %s retornou saída inválida (tentativa %s/%s): %s",
                        module,
                        attempt + 1,
                        RESEARCH_ATTEMPTS,
                        result.raw_error,
                    )
                finally:
                    release_call()

                if self.repository:
                    self.repository.record_step_attempt(f"{run_id}:{stage['id']}", attempt + 1, "failed",
                        error=outcome.raw_error if outcome else "Sem resultado", duration_seconds=time.monotonic() - stage_start_mono)

                if attempt + 1 < RESEARCH_ATTEMPTS:
                    if context.cancellation.wait(RESEARCH_RETRY_BACKOFF_SECONDS * (attempt + 1)):
                        outcome = ModuleResearch(module=module, raw_error="Cancelado durante retry")
                        break

            if outcome is None:
                outcome = ModuleResearch(module=module, raw_error="Pesquisador terminou sem resultado.")
            if self.repository is not None:
                try:
                    self.repository.save_step_result(
                        run_id,
                        stage["id"],
                        worker_id,
                        "module_research",
                        module,
                        step_input_hash,
                        "failed",
                        error=outcome.raw_error,
                        attempts=RESEARCH_ATTEMPTS,
                        duration_seconds=time.monotonic() - stage_start_mono,
                        owner_token=context.metadata["_owner_token"],
                    )
                except Exception:
                    pass
            emit_event(
                cid,
                "agent_failed",
                f"Pesquisador {module} falhou: {outcome.raw_error[:100]}",
                {**stage, "error": outcome.raw_error[:300]},
            )
            return outcome

        reports: list[ModuleResearch] = []
        primary_error: Exception | None = None
        with ThreadPoolExecutor(
            max_workers=max(1, min(plan.max_parallel, context.budget.max_parallel, len(modules)))
        ) as executor:
            futures = {
                executor.submit(research_one, module, index): module
                for index, module in enumerate(modules)
            }
            for future in as_completed(futures):
                try:
                    reports.append(future.result())
                except Exception as exc:
                    if primary_error is None or isinstance(exc, ProviderRateLimited):
                        primary_error = exc
                    context.cancellation.cancel("research_aborted")

        if primary_error is not None:
            raise primary_error

        context.check_cancelled()

        ordered = [next(item for item in reports if item.module == m) for m in modules]
        if not any(item.succeeded for item in ordered):
            raise ProviderError(
                "todos os pesquisadores falharam: "
                + "; ".join(f"{item.module}: {item.raw_error[:120]}" for item in ordered)
            )

        synthesis_bundle = bundle
        code_status = "disabled"
        if code_analysis_enabled and not context.cancellation.is_cancelled:
            code_stage = next(
                item for item in plan.runtime_stages if item["id"] == "fanout_codigo"
            )
            emit_event(
                cid,
                "agent_started",
                "Agente de Código iniciado após delimitação do escopo.",
                dict(code_stage),
            )
            scoped_text = "\n".join(
                [search_scope or request, request]
                + [
                    claim.text
                    for item in ordered
                    if item.report is not None
                    for claim in item.report.findings[:4]
                ]
            )
            try:
                expected_release_hash = str(code_analysis_manifest_sha256 or "").strip()
                if context.metadata.get("code_scope_error"):
                    raise ProviderError(context.metadata["code_scope_error"])
                code_candidates, code_claims, code_results = retrieve_code_candidates(
                    self.settings.root,
                    scoped_text,
                    application_contexts=application_contexts,
                    code_analysis_release=code_analysis_release,
                    code_analysis_manifest_sha256=code_analysis_manifest_sha256,
                    limit_per_scope=8,
                    max_excerpt_chars=3000,
                    limit_per_query=3,
                    max_caller_nodes=3,
                    max_seconds=min(0.3, context.budget.time_remaining()),
                    module=bundle.profile.module,
                    product=bundle.profile.product,
                    budget_remaining=context.budget.time_remaining(),
                )

                fallback_report = WorkerReport(
                    worker_id="fanout_codigo",
                    worker_name="Agente de Código",
                    module="Código",
                    parent_id="vr_fanout",
                    findings=tuple(code_claims),
                    missing_information=(
                        ()
                        if code_claims
                        else ("Nenhum fonte indexado correspondeu ao escopo na release selecionada.",)
                    ),
                    warnings=tuple(
                        dict.fromkeys(
                            str(warning)
                            for item in code_results
                            for warning in (
                                item.get("freshness_warning"),
                                item.get("classpath_warning"),
                            )
                            if warning
                        )
                    ),
                    sources=tuple(item.evidence_id for item in code_candidates),
                )
                code_report = fallback_report
                if code_candidates:
                    code_prompt = f"""Você é o Agente de Código do VR Ultra.

Objetivo: analisar somente os trechos Java já selecionados pelos agentes de
Schema/KB/Wiki e apontar comportamento relevante à solicitação.
Fonte permitida: apenas as evidências de código abaixo, da release
{code_analysis_release}, manifesto {expected_release_hash or "não informado"},
execução {run_id}. Não pesquise arquivos nem amplie o escopo.
Contextos exatos: {json.dumps(application_contexts, ensure_ascii=False) if application_contexts is not None else code_analysis_release}.
Cada evidência pertence ao aplicativo, versão, variante e origem indicados.
Não misture comportamentos entre contextos. Bibliotecas são dependências daquela origem.
Limites: não presuma ordem de classpath; diferencie fato, inferência e hipótese;
sinalize lacunas ou contradições. Cite somente evidence_ids fornecidos.

Solicitação:
{request}

Evidências de código:
{json.dumps([item.to_dict() for item in code_candidates], ensure_ascii=False)}

Retorne somente JSON:
{{"source_status":"found|exhausted|unavailable","findings":[{{"claim":"achado","evidence_ids":["id fornecido"],"kind":"fact|inference|hypothesis","confidence":0.0}}],"steps":[],"conflicts":[],"missing_information":[],"warnings":[],"sources":["id fornecido"]}}"""
                    try:
                        code_call_timeout = acquire_call(
                            is_synthesis=False,
                            requested_timeout=150.0,
                        )
                        try:
                            raw_code = self.run_ephemeral_turn(
                                cid,
                                run_id,
                                "vr_fanout_codigo",
                                ModelRef.from_mapping(code_stage["model"]),
                                code_prompt,
                                context.workspace,
                                RESEARCH_EFFORT,
                                timeout_seconds=code_call_timeout,
                            )
                            parsed_code = parse_researcher_output(
                                raw_code,
                                worker_id="fanout_codigo",
                                worker_name="Agente de Código",
                                module="Código",
                                allowed_evidence_ids=tuple(
                                    item.evidence_id for item in code_candidates
                                ),
                            )
                            if parsed_code.succeeded and parsed_code.report is not None:
                                code_report = parsed_code.report
                            else:
                                code_report = replace(
                                    fallback_report,
                                    warnings=tuple(fallback_report.warnings)
                                    + ("Análise do modelo falhou; usando trechos recuperados.",),
                                )
                        finally:
                            release_call()
                    except CallReservationError as budget_err:
                        LOGGER.warning("Agente de Código dispensado por limite de orçamento: %s", budget_err)
                        code_report = replace(
                            fallback_report,
                            warnings=tuple(fallback_report.warnings)
                            + (f"Orçamento insuficiente para modelo de código: {budget_err}",),
                        )
                    except (ExecutionCancelledError, ProviderRateLimited):
                        raise
                    except Exception as model_exc:
                        LOGGER.warning(
                            "Agente de Código caiu para recuperação determinística: %s",
                            model_exc,
                        )
                        code_report = replace(
                            fallback_report,
                            warnings=tuple(fallback_report.warnings)
                            + ("Análise do modelo indisponível; usando trechos recuperados.",),
                        )

                if application_contexts is not None:
                    from ..code_context import validate_application_contexts
                    validate_application_contexts(self.settings.root, application_contexts)
                ordered.append(ModuleResearch(module="Código", report=code_report))
                synthesis_bundle = replace(
                    bundle,
                    candidates=tuple(bundle.candidates) + tuple(code_candidates),
                )
                allowed_ids = tuple(item.evidence_id for item in synthesis_bundle.candidates)
                code_status = "found" if code_claims else "exhausted"
                emit_event(
                    cid,
                    "agent_completed",
                    f"Agente de Código concluído com {len(code_claims)} achados.",
                    {
                        **code_stage,
                        "status": code_status,
                        "findings": len(code_claims),
                        "citations": [item.title for item in code_candidates],
                    },
                )
            except (ExecutionCancelledError, ProviderRateLimited):
                raise
            except Exception as code_exc:
                code_status = "failed"
                LOGGER.exception("Agente de Código falhou; síntese seguirá sem JAR.")
                emit_event(
                    cid,
                    "agent_failed",
                    "Agente de Código indisponível; seguindo com as outras fontes.",
                    {**code_stage, "error": str(code_exc)[:400]},
                )

        context.check_cancelled()

        if self.collect_evidence is not None:
            captured = self.collect_evidence(run_id)
            synthesis_bundle = replace(synthesis_bundle, candidates=tuple({
                **{c.evidence_id: c for c in synthesis_bundle.candidates},
                **{c.evidence_id: c for c in captured},
            }.values()))
            allowed_ids = tuple(c.evidence_id for c in synthesis_bundle.candidates)

        from ..knowledge_access import bounded_candidates
        synthesis_bundle = replace(synthesis_bundle, candidates=bounded_candidates(synthesis_bundle.candidates))
        allowed_ids = tuple(c.evidence_id for c in synthesis_bundle.candidates)
        merged = merge_module_research(ordered)
        emit_event(
            cid,
            "research_completed",
            "Pesquisa modular concluída; sintetizando resposta.",
            {
                "run_id": run_id,
                **fanout_payload(ordered),
                "errors": {
                    item.module: item.raw_error[:200]
                    for item in ordered
                    if not item.succeeded
                },
                "claims": len(merged.claims),
                "conflicts": len(merged.conflicts),
                "gaps": len(merged.gaps),
                "code_agent": code_status,
            },
        )
        emit_event(
            cid,
            "synthesis_started",
            f"{main_model.display_name or main_model.model or 'Modelo'} sintetizando a resposta.",
            {"run_id": run_id},
        )
        synthesis_prompt = build_fanout_synthesis_prompt(
            request,
            ordered,
            merged,
            intent,
            contract,
            evidence_bundle=synthesis_bundle,
        )

        # Reserve call slot for synthesis (is_synthesis=True)
        synthesis_timeout = acquire_call(is_synthesis=True)
        try:
            raw_draft, started_payload, completed_payload = self.run_buffered_main_turn(
                cid,
                native_id,
                provider,
                str(conversation.get("model") or ""),
                synthesis_effort,
                context.workspace,
                synthesis_prompt,
                options,
                skills,
                timeout_seconds=synthesis_timeout,
            )
        finally:
            release_call()

        draft = parse_final_draft(raw_draft, allowed_evidence_ids=allowed_ids)
        envelope_like = self.looks_like_final_envelope(draft.answer_markdown)
        violations = validate_fanout_draft(
            draft, contract, synthesis_bundle, user_message=request,
        )
        if envelope_like and not any(item.code == "internal_leak" for item in violations):
            violations = violations + (
                ResponseViolation(
                    code="internal_leak",
                    detail="resposta retornou o envelope JSON bruto",
                    fix_instruction=(
                        "Entregue apenas o Markdown da resposta, sem JSON, "
                        "sem cercas de código e sem chaves de metadados."
                    ),
                ),
            )
        needs_operational_review = lambda answer: bool(re.search(
            r"\b(bug|defeito|falha|corrupção|vazamento|divergência|inevitável|nunca|sempre)\b",
            answer,
            re.IGNORECASE,
        ))
        if (
            not violations
            and draft.answer_status != "insufficient_evidence"
            and needs_operational_review(draft.answer_markdown)
            and self.operational_reviewer is not None
            and not context.cancellation.is_cancelled
        ):
            review_timeout = acquire_call(is_synthesis=True, requested_timeout=90)
            try:
                violations = self.operational_reviewer(
                    cid, run_id, main_model, context.workspace, request, draft, synthesis_bundle,
                    timeout_seconds=review_timeout,
                )
            finally:
                release_call()

        for _repair_attempt in range(2):
            if not violations or draft.answer_status == "insufficient_evidence":
                break
            if context.cancellation.is_cancelled:
                break
            # Try to acquire call for repair
            try:
                repair_timeout = acquire_call(is_synthesis=True)
            except CallReservationError:
                LOGGER.warning("Orçamento esgotado durante tentativa de reparo de síntese.")
                break

            try:
                rewrite_prompt = build_rewrite_prompt(
                    request,
                    intent,
                    contract,
                    draft,
                    FinalResponseValidation(
                        verdict="revise",
                        reasons=tuple(RefinementReason.INCOMPLETE for _ in violations),
                        unsupported_claims=tuple(
                            f"[{item.code}] {item.detail}: {item.fix_instruction}"
                            for item in violations
                        ),
                    ),
                    merged,
                    evidence_bundle=synthesis_bundle,
                )
                raw_draft, started_payload, completed_payload = self.run_buffered_main_turn(
                    cid,
                    native_id,
                    provider,
                    str(conversation.get("model") or ""),
                    synthesis_effort,
                    context.workspace,
                    rewrite_prompt,
                    options,
                    skills,
                    timeout_seconds=repair_timeout,
                )
                draft = parse_final_draft(raw_draft, allowed_evidence_ids=allowed_ids)
                violations = validate_fanout_draft(
                    draft, contract, synthesis_bundle, user_message=request,
                )
                if self.looks_like_final_envelope(draft.answer_markdown):
                    violations += (ResponseViolation("internal_leak", "reescrita retornou envelope bruto", "Entregue somente Markdown."),)
            finally:
                release_call()

            if violations or draft.answer_status == "insufficient_evidence":
                break
            if self.operational_reviewer is not None:
                try:
                    review_timeout = acquire_call(is_synthesis=True, requested_timeout=90)
                except CallReservationError:
                    violations = (ResponseViolation("unverified_repair", "Sem orçamento para conferir a reescrita", "Não publique uma reescrita sem conferência."),)
                    break
                try:
                    violations = self.operational_reviewer(
                        cid, run_id, main_model, context.workspace, request, draft, synthesis_bundle,
                        timeout_seconds=review_timeout,
                    )
                finally:
                    release_call()

        context.check_cancelled()
        if self.repository is not None:
            try:
                run_status = "rejected" if violations or draft.answer_status == "insufficient_evidence" else "completed"
                self.repository.update_run_status(
                    run_id,
                    run_status,
                    budget_snapshot=context.budget.to_dict(),
                    result_dict={
                        "claims": len(merged.claims),
                        "code_status": code_status,
                        "answer_status": draft.answer_status if draft else "none",
                    },
                    owner_token=context.metadata["_owner_token"],
                )
            except Exception as repo_err:
                LOGGER.warning("Erro ao atualizar status do run no repositório: %s", repo_err)

        return ResearchFanoutResult(
            run_id=run_id,
            ordered=ordered,
            merged=merged,
            synthesis_bundle=synthesis_bundle,
            code_status=code_status,
            draft=draft,
            violations=violations,
            started_payload=started_payload,
            completed_payload=completed_payload,
        )

from __future__ import annotations
import json
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
from PySide6.QtWidgets import QFileDialog
from ...classpath import ClasspathError, ClasspathPolicyStore
from ...code_coverage import CodeCoverageError, ErpCodeCoverage
from ...code_index import JavaCodeIndex
from ...code_processing_audit import CodeProcessingAudit
from ...code_processing_policy import processing_window_status
from ...erp_releases import ErpReleaseCatalog, ErpReleaseError
from ...jvm_batches import DecompilationBatchError
from ...jvm_toolchain import JvmToolchain

from .presentation import (ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE, ERP_JAR_SCOPE_FULL_RELEASE, ERP_JAR_SCOPE_SINGLE, DEFAULT_ERP_JAR_SOURCE_PATH, EXPECTED_ERP_JAR_COUNT, CODE_PROCESSING_HARDWARE, CODE_PROCESSING_HEAP_OPTIONS, CODE_PROCESSING_TIMEOUT_OPTIONS, CODE_PROCESSING_CPU_CORE_OPTIONS, CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS, CODE_PROCESSING_WINDOW_OPTIONS)

class CodeAdminDomain:
    """Domain operations using the facade as the sole state and transaction owner."""
    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        return getattr(self._owner, name)

    def __setattr__(self, name, value):
        setattr(self._owner, name, value)

    def setCodeAnalysisEnabled(self, enabled: bool) -> None:  # noqa: N802
        self._code_analysis_enabled = bool(
            enabled
            and self._code_analysis_release_items
            and self.codeAnalysisReleaseFresh
        )
        self._preferences.setValue(
            "research/code_analysis_enabled", self._code_analysis_enabled
        )
        self._preferences.sync()
        self.stateChanged.emit()


    def setCodeAnalysisRelease(self, release_id: str) -> None:  # noqa: N802
        selected = str(release_id or "").strip()
        if self._code_processing_running:
            return
        available = {
            str(item.get("releaseId") or "")
            for item in self._code_analysis_release_items
        }
        if (
            not selected
            or selected not in available
            or selected == self._code_analysis_release
        ):
            return
        self._cancel_code_processing_status_refresh()
        self._code_analysis_release = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_release"),
            selected,
        )
        self._preferences.sync()
        self._refresh_code_analysis_jar_sources()
        self.refreshCodeProcessingStatus()
        self.stateChanged.emit()


    def setCodeAnalysisJarSource(self, source: str) -> None:  # noqa: N802
        selected = str(source or "").strip()
        if selected not in {ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE}:
            return
        if selected == self._code_analysis_jar_source:
            return
        self._code_analysis_jar_source = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_jar_source"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()


    def setCodeAnalysisSnapshotScope(self, scope: str) -> None:  # noqa: N802
        selected = str(scope or "").strip()
        if (
            selected not in {ERP_JAR_SCOPE_FULL_RELEASE, ERP_JAR_SCOPE_SINGLE}
            or selected == self._code_analysis_snapshot_scope
            or self._release_snapshot_running
            or self._code_processing_running
        ):
            return
        self._code_analysis_snapshot_scope = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_snapshot_scope"),
            selected,
        )
        self._preferences.sync()
        self._release_snapshot_status = ""
        self.stateChanged.emit()


    def setCodeAnalysisSingleJarPath(self, value: str) -> bool:  # noqa: N802
        candidate = Path(str(value or "").strip()).resolve(strict=False)
        if (
            self._release_snapshot_running
            or self._code_processing_running
            or not candidate.is_file()
            or candidate.suffix.casefold() != ".jar"
        ):
            self._release_snapshot_status = "Selecione um arquivo JAR válido."
            self.stateChanged.emit()
            return False
        self._code_analysis_single_jar_path = str(candidate)
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_single_jar_path"),
            self._code_analysis_single_jar_path,
        )
        self._preferences.sync()
        self._release_snapshot_status = f"JAR selecionado: {candidate.name}"
        self.stateChanged.emit()
        return True


    def selectCodeAnalysisSingleJar(self) -> str:  # noqa: N802
        initial = self.codeAnalysisJarSourcePath or str(self._settings.root)
        selected, _filter = QFileDialog.getOpenFileName(
            None,
            "Selecionar JAR para análise",
            initial,
            "Arquivos JAR (*.jar)",
        )
        if selected and self.setCodeAnalysisSingleJarPath(selected):
            return self._code_analysis_single_jar_path
        return ""


    def setCodeProcessingMaxHeapMb(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_HEAP_OPTIONS
            or selected == self._code_processing_max_heap_mb
        ):
            return
        self._code_processing_max_heap_mb = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_max_heap_mb"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()


    def setCodeProcessingTimeoutSeconds(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_TIMEOUT_OPTIONS
            or selected == self._code_processing_timeout_seconds
        ):
            return
        self._code_processing_timeout_seconds = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_timeout_seconds"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()


    def setCodeProcessingMaxCpuCores(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_CPU_CORE_OPTIONS
            or selected == self._code_processing_max_cpu_cores
        ):
            return
        self._code_processing_max_cpu_cores = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_max_cpu_cores"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()


    def setCodeProcessingDiskMultiplier(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS
            or selected == self._code_processing_disk_multiplier
        ):
            return
        try:
            ErpReleaseCatalog(
                self._settings.root,
                storage_budget_multiplier=selected,
            ).set_storage_budget_multiplier(selected, inspect_storage=False)
        except (ErpReleaseError, OSError, ValueError) as exc:
            self._code_processing_status = f"Limite de disco não alterado: {exc}"
            self.stateChanged.emit()
            return
        self._code_processing_disk_multiplier = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_disk_multiplier"),
            selected,
        )
        self._preferences.sync()
        self.refreshCodeProcessingStatus()
        self.stateChanged.emit()


    def setCodeProcessingWindow(self, value: str) -> None:  # noqa: N802
        selected = str(value or "").strip()
        available = {str(item["value"]) for item in CODE_PROCESSING_WINDOW_OPTIONS}
        if (
            self._code_processing_running
            or selected not in available
            or selected == self._code_processing_window
        ):
            return
        self._code_processing_window = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_window"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()


    def setCodeProcessingRetryBatch(self, batch_id: str) -> None:  # noqa: N802
        selected = str(batch_id or "").strip()
        available = {
            str(item.get("batchId") or "")
            for item in self._code_processing_attention_batches
        }
        if (
            self._code_processing_running
            or selected not in available
            or selected == self._code_processing_retry_batch
        ):
            return
        self._code_processing_retry_batch = selected
        selected_item = next(
            item
            for item in self._code_processing_attention_batches
            if item.get("batchId") == selected
        )
        self._code_processing_current_batch = selected
        self._code_processing_current_jar = str(selected_item.get("jar") or "")
        self.stateChanged.emit()


    def _selected_code_analysis_release_item(self) -> dict[str, Any]:
        return next(
            (
                item
                for item in self._code_analysis_release_items
                if str(item.get("releaseId") or "")
                == self._code_analysis_release
            ),
            {},
        )


    def refreshCodeProcessingStatus(self) -> None:  # noqa: N802
        if self._code_processing_running or self._code_processing_status_loading:
            return
        release_id = self._code_analysis_release
        if not release_id:
            self._reset_code_processing_status("Adicione uma release para processar.")
            self.stateChanged.emit()
            return
        self._code_processing_status_loading = True
        self._code_processing_status_generation += 1
        generation = self._code_processing_status_generation
        workspace = self._settings.root
        results = self._code_processing_status_results
        self._code_processing_status = "Consultando cobertura local..."
        self.stateChanged.emit()

        def load() -> None:
            try:
                try:
                    coverage = ErpCodeCoverage(workspace).status(release_id)
                except Exception as exc:
                    results.put((generation, release_id, None, None, str(exc)))
                    return
                latest_audit = CodeProcessingAudit(workspace).latest(
                    release_id=release_id
                )
                results.put((generation, release_id, coverage, latest_audit, ""))
            finally:
                with self._code_processing_status_threads_lock:
                    self._code_processing_status_threads.discard(
                        threading.current_thread()
                    )

        self._code_processing_status_poll_timer.start()
        thread = threading.Thread(target=load, daemon=True)
        with self._code_processing_status_threads_lock:
            self._code_processing_status_threads.add(thread)
        thread.start()


    def _cancel_code_processing_status_refresh(self) -> None:
        self._code_processing_status_generation += 1
        self._code_processing_status_loading = False
        self._code_processing_status_poll_timer.stop()


    def _poll_code_processing_status(self) -> None:
        latest: tuple[
            int,
            str,
            dict[str, Any] | None,
            dict[str, Any] | None,
            str,
        ] | None = None
        while True:
            try:
                latest = self._code_processing_status_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return
        generation, release_id, coverage, audit_event, error = latest
        if generation != self._code_processing_status_generation:
            return
        self._code_processing_status_loading = False
        self._code_processing_status_poll_timer.stop()
        if release_id != self._code_analysis_release or self._code_processing_running:
            self.stateChanged.emit()
            return
        if error:
            self._reset_code_processing_status(
                f"Não foi possível consultar a cobertura: {error}"
            )
        elif isinstance(coverage, dict):
            self._apply_code_processing_coverage(coverage)
            self._restore_code_processing_audit(audit_event, coverage)
        self.stateChanged.emit()


    def _reset_code_processing_status(self, message: str) -> None:
        self._code_processing_status = message
        self._code_processing_progress = 0
        self._code_processing_covered_jars = 0
        self._code_processing_total_jars = 0
        self._code_processing_can_retry = False
        self._code_processing_current_jar = ""
        self._code_processing_current_batch = ""
        self._code_processing_attention_batches = []
        self._code_processing_retry_batch = ""
        self._code_processing_eta = {}
        self._code_processing_capacity = {}


    def _apply_code_processing_coverage(self, coverage: dict[str, Any]) -> None:
        total = max(0, int(coverage.get("expected_jar_count") or 0))
        covered = max(0, int(coverage.get("covered_jar_count") or 0))
        remaining = max(0, int(coverage.get("remaining_jar_count") or 0))
        blocked = list(coverage.get("blocked_plans") or [])
        active = list(coverage.get("active_plans") or [])
        self._code_processing_eta = dict(coverage.get("eta") or {})
        self._code_processing_capacity = dict(coverage.get("capacity") or {})
        self._code_processing_total_jars = total
        self._code_processing_covered_jars = min(covered, total) if total else covered
        reported_progress = coverage.get("progress_percent")
        if reported_progress is None:
            calculated_progress = covered * 100 / total if total else 0.0
        else:
            calculated_progress = float(reported_progress)
        calculated_progress = round(max(0.0, min(100.0, calculated_progress)), 1)
        self._code_processing_progress = (
            max(float(self._code_processing_progress), calculated_progress)
            if self._code_processing_running
            else calculated_progress
        )
        attention_items: list[dict[str, Any]] = []
        for plan in blocked:
            if not isinstance(plan, dict):
                continue
            selected_jars = [str(item) for item in plan.get("selected_jars") or []]
            for batch in plan.get("attention_batches") or []:
                if not isinstance(batch, dict) or not batch.get("batch_id"):
                    continue
                batch_id = str(batch["batch_id"])
                jar = str(batch.get("jar_relative_path") or "")
                if not jar and len(selected_jars) == 1:
                    jar = selected_jars[0]
                state = str(batch.get("state") or "failed")
                ordinal = int(batch.get("ordinal") or 0) + 1
                attention_items.append(
                    {
                        "batchId": batch_id,
                        "jar": jar,
                        "state": state,
                        "ordinal": ordinal,
                        "label": (
                            f"{jar or 'JAR não identificado'} · lote {ordinal} · {state}"
                        ),
                    }
                )
        self._code_processing_attention_batches = attention_items
        attention_ids = {
            str(item.get("batchId") or "") for item in attention_items
        }
        if self._code_processing_retry_batch not in attention_ids:
            self._code_processing_retry_batch = (
                str(attention_items[0]["batchId"]) if attention_items else ""
            )
        self._code_processing_can_retry = bool(attention_items)
        current_plan = next(
            (
                plan
                for plan in [*active, *blocked]
                if isinstance(plan, dict) and plan.get("current_batch")
            ),
            {},
        )
        current_batch = dict(current_plan.get("current_batch") or {})
        self._code_processing_current_jar = str(
            current_batch.get("jar_relative_path") or ""
        )
        if not self._code_processing_current_jar and remaining:
            pending_jars = list(coverage.get("remaining_jars") or [])
            self._code_processing_current_jar = (
                str(pending_jars[0]) if pending_jars else ""
            )
        self._code_processing_current_batch = str(
            current_batch.get("batch_id") or ""
        )
        if remaining == 0 and total:
            self._code_processing_status = (
                f"Processamento concluído: {covered}/{total} JARs indexados."
            )
        elif self._code_processing_can_retry:
            self._code_processing_status = (
                f"Atenção necessária: {covered}/{total} JARs indexados; "
                "há lote com falha ou saída parcial."
            )
        elif active:
            self._code_processing_status = (
                f"Plano retomável: {covered}/{total} JARs indexados."
            )
        else:
            self._code_processing_status = (
                f"Pronto para processar: {covered}/{total} JARs indexados."
            )


    def _restore_code_processing_audit(
        self,
        audit_event: dict[str, Any] | None,
        coverage: dict[str, Any],
    ) -> None:
        if not isinstance(audit_event, dict):
            return
        manifest_hash = str(coverage.get("release_manifest_sha256") or "")
        audit_hash = str(audit_event.get("release_manifest_sha256") or "")
        if not manifest_hash or audit_hash != manifest_hash:
            return
        self._code_processing_release = str(audit_event.get("release_id") or "")
        self._code_processing_manifest_hash = audit_hash
        self._code_processing_run_id = str(audit_event.get("run_id") or "")
        event = str(audit_event.get("event") or "")
        details = dict(audit_event.get("details") or {})
        restored_telemetry = details.get("telemetry")
        if isinstance(restored_telemetry, dict):
            self._code_processing_telemetry = dict(restored_telemetry)
        if event == "failed":
            error = str(details.get("error") or "erro desconhecido")
            self._code_processing_status = f"Última execução falhou: {error}"
        elif event == "paused":
            self._code_processing_status = (
                "Processamento pausado entre lotes: "
                f"{self._code_processing_covered_jars}/"
                f"{self._code_processing_total_jars} JARs indexados."
            )
        elif event in {"started", "toolchain_validated", "progress", "batch_retried"}:
            self._code_processing_status = (
                "Execução anterior foi interrompida; pronta para retomar: "
                f"{self._code_processing_covered_jars}/"
                f"{self._code_processing_total_jars} JARs indexados."
            )


    def startCodeProcessing(self) -> bool:  # noqa: N802
        return self._start_code_processing(retry_batch_id="")


    def retryCodeProcessing(self) -> bool:  # noqa: N802
        if not self._code_processing_can_retry or not self._code_processing_retry_batch:
            return False
        return self._start_code_processing(
            retry_batch_id=self._code_processing_retry_batch
        )


    def _start_code_processing(self, *, retry_batch_id: str) -> bool:
        if self._code_processing_running or self._release_snapshot_running:
            return False
        if (
            self._code_processing_total_jars > 0
            and self._code_processing_covered_jars
            >= self._code_processing_total_jars
        ):
            return False
        release_id = self._code_analysis_release
        selected = self._selected_code_analysis_release_item()
        if not release_id or not selected:
            self._code_processing_status = "Selecione uma release inventariada."
            self.stateChanged.emit()
            return False
        if selected.get("freshness") != "fresh":
            self._code_processing_status = (
                "A release está desatualizada; gere um novo snapshot antes de processar."
            )
            self.stateChanged.emit()
            return False
        window_status = processing_window_status(self._code_processing_window)
        if not window_status["allowed"]:
            self._code_processing_status = (
                "Fora da janela ociosa configurada: "
                + str(window_status["label"])
                + "."
            )
            self.stateChanged.emit()
            return False
        try:
            manifest = ErpReleaseCatalog(self._settings.root).load_manifest(release_id)
        except (ErpReleaseError, OSError, ValueError) as exc:
            self._code_processing_status = f"Manifesto da release indisponível: {exc}"
            self.stateChanged.emit()
            return False
        manifest_hash = str(manifest.get("release_manifest_sha256") or "").strip()
        if not manifest_hash:
            self._code_processing_status = "O manifesto da release não possui SHA-256."
            self.stateChanged.emit()
            return False

        self._cancel_code_processing_status_refresh()
        self._code_processing_release = release_id
        self._code_processing_manifest_hash = manifest_hash
        self._code_processing_run_id = uuid4().hex
        self._code_processing_telemetry = {}
        max_heap_mb = self._code_processing_max_heap_mb
        timeout_seconds = self._code_processing_timeout_seconds
        max_cpu_cores = self._code_processing_max_cpu_cores
        parallel_workers = CODE_PROCESSING_HARDWARE.parallel_workers_for(
            max_cpu_cores,
            max_heap_mb,
        )
        process_priority = "normal" if parallel_workers > 1 else "low"
        disk_multiplier = self._code_processing_disk_multiplier
        processing_window = self._code_processing_window
        try:
            CodeProcessingAudit(self._settings.root).record(
                "started",
                run_id=self._code_processing_run_id,
                release_id=release_id,
                manifest_sha256=manifest_hash,
                details={
                    "retry_batch_id": retry_batch_id,
                    "max_heap_mb": max_heap_mb,
                    "timeout_seconds": timeout_seconds,
                    "max_cpu_cores": max_cpu_cores,
                    "process_priority": process_priority,
                    "disk_budget_multiplier": disk_multiplier,
                    "processing_window": processing_window,
                    "global_java_concurrency": parallel_workers,
                    "covered_jar_count": self._code_processing_covered_jars,
                    "expected_jar_count": self._code_processing_total_jars,
                },
            )
        except OSError as exc:
            self._code_processing_status = (
                f"Não foi possível criar a trilha de auditoria local: {exc}"
            )
            self.stateChanged.emit()
            return False
        self._code_processing_running = True
        self._code_processing_pause_requested = False
        self._code_processing_pause_event.clear()
        self._code_processing_status = (
            f"Validando Java 17 e decompiladores para {release_id}..."
        )
        self._code_processing_can_retry = False
        self.stateChanged.emit()
        self._code_processing_poll_timer.start()
        self._code_processing_thread = threading.Thread(
            target=self._run_code_processing,
            args=(
                release_id,
                manifest_hash,
                retry_batch_id,
                max_heap_mb,
                timeout_seconds,
                max_cpu_cores,
                parallel_workers,
                process_priority,
                disk_multiplier,
                processing_window,
            ),
            daemon=True,
        )
        self._code_processing_thread.start()
        return True


    def pauseCodeProcessing(self) -> None:  # noqa: N802
        if not self._code_processing_running or self._code_processing_pause_requested:
            return
        self._code_processing_pause_requested = True
        self._code_processing_pause_event.set()
        self._code_processing_status = (
            "Pausa solicitada; os lotes Java atuais serão concluídos com segurança."
        )
        self.stateChanged.emit()


    def _run_code_processing(
        self,
        release_id: str,
        manifest_hash: str,
        retry_batch_id: str,
        max_heap_mb: int,
        timeout_seconds: int,
        max_cpu_cores: int,
        parallel_workers: int,
        process_priority: str,
        disk_multiplier: int,
        processing_window: str,
    ) -> None:
        results = self._code_processing_results

        def publish(event: dict[str, Any]) -> None:
            results.put(event)
            self._codeProcessingReady.emit()

        audit = CodeProcessingAudit(self._settings.root)
        run_id = self._code_processing_run_id
        started_monotonic = time.monotonic()
        job_telemetry: dict[str, Any] = {
            "processed_batches": 0,
            "decompiler_duration_ms": 0,
            "peak_rss_bytes": 0,
            "cpu_user_ms": 0,
            "cpu_kernel_ms": 0,
            "input_bytes": 0,
            "output_bytes": 0,
            "timed_out_batches": 0,
            "metrics_available": False,
            "cpu_limit_applied": False,
            "wall_duration_ms": 0,
        }
        try:
            toolchain = JvmToolchain(
                self._settings.root,
                app_dir=self._settings.app_dir,
            )
            doctor = toolchain.doctor()
            java_ready = bool((doctor.get("java") or {}).get("available"))
            decompiler_ready = any(
                bool((doctor.get(name) or {}).get("available"))
                for name in ("vineflower", "cfr")
            )
            if not java_ready or not decompiler_ready:
                unavailable = []
                for name, label in (
                    ("java", "Java 17 isolado"),
                    ("vineflower", "Vineflower"),
                    ("cfr", "CFR"),
                ):
                    status = doctor.get(name) or {}
                    if not bool(status.get("available")):
                        detail = str(status.get("error") or "indisponível")
                        unavailable.append(f"{label}: {detail}")
                raise CodeCoverageError(
                    "Java 17 isolado e ao menos um decompilador verificado são necessários. "
                    + " | ".join(unavailable)
                )
            audit.record(
                "toolchain_validated",
                run_id=run_id,
                release_id=release_id,
                manifest_sha256=manifest_hash,
                details={
                    "java_ready": java_ready,
                    "decompiler_ready": decompiler_ready,
                },
            )

            catalog = ErpReleaseCatalog(
                self._settings.root,
                storage_budget_multiplier=disk_multiplier,
            )
            catalog.set_storage_budget_multiplier(disk_multiplier)
            manager = ErpCodeCoverage(
                self._settings.root,
                catalog=catalog,
                adapters=(
                    toolchain.adapters()
                    if hasattr(toolchain, "adapters")
                    else None
                ),
            )
            coverage = manager.status(release_id)
            self._require_frozen_code_manifest(coverage, manifest_hash)
            if retry_batch_id:
                attention = [
                    batch
                    for plan in coverage.get("blocked_plans") or []
                    if isinstance(plan, dict)
                    for batch in plan.get("attention_batches") or []
                    if isinstance(batch, dict) and batch.get("batch_id")
                ]
                if not attention:
                    raise CodeCoverageError("Nenhum lote com falha está disponível para retry.")
                attention_by_id = {
                    str(item["batch_id"]): item for item in attention
                }
                if retry_batch_id not in attention_by_id:
                    raise CodeCoverageError(
                        "O lote selecionado para retry não está mais bloqueado: "
                        + retry_batch_id
                    )
                manager.executor.retry(retry_batch_id)
                audit.record(
                    "batch_retried",
                    run_id=run_id,
                    release_id=release_id,
                    manifest_sha256=manifest_hash,
                    details={"batch_id": retry_batch_id},
                )
                coverage = manager.status(release_id)
                self._require_frozen_code_manifest(coverage, manifest_hash)
            publish({"kind": "progress", "coverage": coverage})

            while True:
                window_status = processing_window_status(processing_window)
                if not window_status["allowed"]:
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "paused",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "paused",
                            "coverage": coverage,
                            "telemetry": telemetry,
                            "reason": (
                                "janela ociosa encerrada: "
                                + str(window_status["label"])
                            ),
                        }
                    )
                    return
                if self._code_processing_pause_event.is_set():
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "paused",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {"kind": "paused", "coverage": coverage, "telemetry": telemetry}
                    )
                    return
                if int(coverage.get("remaining_jar_count") or 0) == 0:
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "completed",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "completed",
                            "coverage": coverage,
                            "telemetry": telemetry,
                        }
                    )
                    return
                if coverage.get("blocked_plans"):
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "attention",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "attention",
                            "coverage": coverage,
                            "telemetry": telemetry,
                        }
                    )
                    return

                publish({"kind": "batch_started", "coverage": coverage})
                advanced = manager.advance(
                    release_id,
                    approved=True,
                    jars_per_plan=1,
                    batch_limit=parallel_workers,
                    max_heap_mb=max_heap_mb,
                    timeout_seconds=timeout_seconds,
                    max_cpu_cores=max_cpu_cores,
                    parallel_workers=parallel_workers,
                    process_priority=process_priority,
                    processing_window=processing_window,
                    progress=lambda item: publish(
                        {"kind": "phase_progress", **dict(item)}
                    ),
                )
                coverage = dict(advanced.get("coverage") or {})
                self._require_frozen_code_manifest(coverage, manifest_hash)
                executed = [
                    item
                    for item in advanced.get("executed") or []
                    if isinstance(item, dict)
                ]
                telemetry = self._merge_code_processing_telemetry(
                    job_telemetry, executed, started_monotonic
                )
                self._record_code_processing_coverage(
                    audit,
                    "progress",
                    run_id,
                    release_id,
                    manifest_hash,
                    coverage,
                    telemetry,
                )
                publish(
                    {"kind": "progress", "coverage": coverage, "telemetry": telemetry}
                )
                if any(
                    str(item.get("state") or "") in {"failed", "partial"}
                    for item in executed
                    if isinstance(item, dict)
                ):
                    self._record_code_processing_coverage(
                        audit,
                        "attention",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "attention",
                            "coverage": coverage,
                            "telemetry": telemetry,
                        }
                    )
                    return
                if not executed and int(coverage.get("remaining_jar_count") or 0) > 0:
                    raise CodeCoverageError(
                        "O plano não avançou nenhum lote; revise o estado antes de continuar."
                    )
        except Exception as exc:
            telemetry = self._merge_code_processing_telemetry(
                job_telemetry, [], started_monotonic
            )
            try:
                audit.record(
                    "failed",
                    run_id=run_id,
                    release_id=release_id,
                    manifest_sha256=manifest_hash,
                    details={"error": str(exc), "telemetry": telemetry},
                )
            except OSError:
                pass
            publish(
                {"kind": "error", "error": str(exc), "telemetry": telemetry}
            )


    @staticmethod
    def _record_code_processing_coverage(
        audit: CodeProcessingAudit,
        event: str,
        run_id: str,
        release_id: str,
        manifest_hash: str,
        coverage: dict[str, Any],
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        details = {
            "covered_jar_count": int(coverage.get("covered_jar_count") or 0),
            "expected_jar_count": int(coverage.get("expected_jar_count") or 0),
            "remaining_jar_count": int(coverage.get("remaining_jar_count") or 0),
        }
        if telemetry:
            details["telemetry"] = dict(telemetry)
        audit.record(
            event,
            run_id=run_id,
            release_id=release_id,
            manifest_sha256=manifest_hash,
            details=details,
        )


    @staticmethod
    def _merge_code_processing_telemetry(
        aggregate: dict[str, Any],
        executions: list[dict[str, Any]],
        started_monotonic: float,
    ) -> dict[str, Any]:
        for execution in executions:
            if not isinstance(execution, dict):
                continue
            telemetry = execution.get("telemetry")
            if not isinstance(telemetry, dict):
                continue
            aggregate["processed_batches"] = int(
                aggregate.get("processed_batches") or 0
            ) + 1
            for field in (
                "decompiler_duration_ms",
                "cpu_user_ms",
                "cpu_kernel_ms",
                "input_bytes",
                "output_bytes",
            ):
                source_field = (
                    "duration_ms" if field == "decompiler_duration_ms" else field
                )
                aggregate[field] = int(aggregate.get(field) or 0) + max(
                    0, int(telemetry.get(source_field) or 0)
                )
            aggregate["peak_rss_bytes"] = max(
                int(aggregate.get("peak_rss_bytes") or 0),
                max(0, int(telemetry.get("peak_rss_bytes") or 0)),
            )
            aggregate["metrics_available"] = bool(
                aggregate.get("metrics_available")
                or telemetry.get("metrics_available")
            )
            aggregate["cpu_limit_applied"] = bool(
                aggregate.get("cpu_limit_applied")
                or telemetry.get("cpu_limit_applied")
            )
            aggregate["timed_out_batches"] = int(
                aggregate.get("timed_out_batches") or 0
            ) + int(bool(telemetry.get("timed_out")))
        aggregate["wall_duration_ms"] = int(
            (time.monotonic() - started_monotonic) * 1000
        )
        return dict(aggregate)


    @staticmethod
    def _require_frozen_code_manifest(
        coverage: dict[str, Any], manifest_hash: str
    ) -> None:
        current = str(coverage.get("release_manifest_sha256") or "")
        if not current or current != manifest_hash:
            raise CodeCoverageError(
                "O manifesto da release mudou depois do início; a execução foi interrompida."
            )


    def _poll_code_processing(self) -> None:
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self._code_processing_results.get_nowait())
            except queue.Empty:
                break
        if not events:
            return

        for event in events:
            coverage = event.get("coverage")
            if isinstance(coverage, dict):
                self._apply_code_processing_coverage(coverage)
            telemetry = event.get("telemetry")
            if isinstance(telemetry, dict):
                self._code_processing_telemetry = dict(telemetry)
            kind = str(event.get("kind") or "")
            if kind == "progress":
                self._code_processing_status = (
                    f"Processando {self._code_processing_release}: "
                    f"{self._code_processing_covered_jars}/"
                    f"{self._code_processing_total_jars} JARs indexados."
                )
            elif kind == "phase_progress":
                current = max(0, int(event.get("current") or 0))
                total = max(1, int(event.get("total") or 1))
                ratio = min(1.0, current / total)
                phase = str(event.get("phase") or "")
                if phase == "scanning":
                    candidate = round(3.0 * ratio, 1)
                    action = "Lendo classes do JAR"
                else:
                    candidate = round(3.0 + (2.0 * ratio), 1)
                    action = "Montando lotes de descompilação"
                self._code_processing_progress = max(
                    float(self._code_processing_progress), candidate
                )
                self._code_processing_status = (
                    f"{action}: {min(current, total)}/{total} classes."
                )
            elif kind == "batch_started":
                target = self._code_processing_current_jar or "próximo JAR"
                self._code_processing_status = (
                    f"Processando {self._code_processing_release}: {target} · "
                    f"{self._code_processing_covered_jars}/"
                    f"{self._code_processing_total_jars} JARs concluídos."
                )
            elif kind == "paused":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                reason = str(event.get("reason") or "").strip()
                self._code_processing_status = (
                    f"Processamento pausado entre lotes: "
                    f"{self._code_processing_covered_jars}/"
                    f"{self._code_processing_total_jars} JARs indexados."
                    + (f" Motivo: {reason}." if reason else "")
                )
            elif kind == "attention":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
            elif kind == "completed":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
            elif kind == "error":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                self._code_processing_status = (
                    "Falha no processamento local: "
                    + str(event.get("error") or "erro desconhecido")
                )
        if not self._code_processing_running:
            self._code_processing_poll_timer.stop()
            self._invalidate_release_coverage()
            self._refresh_code_analysis_releases()
        self.stateChanged.emit()


    def snapshotCodeAnalysisRelease(self, release_id: str) -> bool:  # noqa: N802
        """Detect, categorize and inventory local JARs off the UI thread."""

        selected_release = str(release_id or "").strip()
        single_jar = self._code_analysis_snapshot_scope == ERP_JAR_SCOPE_SINGLE
        source = (
            self._code_analysis_single_jar_path
            if single_jar
            else self.codeAnalysisJarSourcePath
        )
        if self._release_snapshot_running or self._code_processing_running:
            return False
        if not source:
            self._release_snapshot_status = (
                "Selecione o JAR que será analisado."
                if single_jar
                else "Selecione um diretório de JARs."
            )
            self.stateChanged.emit()
            return False
        if single_jar:
            candidate = Path(source).resolve(strict=False)
            if not candidate.is_file() or candidate.suffix.casefold() != ".jar":
                self._release_snapshot_status = "Selecione um arquivo JAR válido."
                self.stateChanged.emit()
                return False

        self._release_snapshot_running = True
        self._release_snapshot_status = (
            (
                f"Detectando aplicação e versão de {Path(source).name} localmente..."
                if single_jar
                else "Detectando aplicações e preparando a release localmente..."
            )
        )
        self.stateChanged.emit()
        results = self._release_snapshot_results
        workspace = self._settings.root

        def snapshot() -> None:
            try:
                manifest = ErpReleaseCatalog(
                    workspace,
                    expected_jar_count=(1 if single_jar else EXPECTED_ERP_JAR_COUNT),
                ).snapshot_detected_release(
                    source,
                    release_id=selected_release,
                    analysis_scope=(
                        ERP_JAR_SCOPE_SINGLE
                        if single_jar
                        else ERP_JAR_SCOPE_FULL_RELEASE
                    ),
                )
            except Exception as exc:
                results.put(
                    {
                        "ok": False,
                        "release_id": selected_release,
                        "error": str(exc),
                    }
                )
                self._releaseSnapshotReady.emit()
                return
            results.put(
                {
                    "ok": True,
                    "release_id": str(manifest.get("release_id") or selected_release),
                    "jar_count": int(manifest.get("jar_count") or 0),
                    "package_jar_count": int(manifest.get("package_jar_count") or 0),
                    "base_release_id": str(manifest.get("base_release_id") or ""),
                    "analysis_scope": str(manifest.get("analysis_scope") or ""),
                    "expected_jar_count": int(
                        manifest.get("expected_jar_count") or 0
                    ),
                    "updated_applications": list(
                        manifest.get("updated_applications") or []
                    ),
                }
            )
            self._releaseSnapshotReady.emit()

        self._release_snapshot_poll_timer.start()
        threading.Thread(target=snapshot, daemon=True).start()
        return True


    def removeCodeAnalysisRelease(self, release_id: str) -> bool:  # noqa: N802
        """Remove an inventoried release after confirmation in the UI."""

        selected_release = str(release_id or "").strip()
        if (
            not selected_release
            or self._release_snapshot_running
            or self._code_processing_running
        ):
            return False

        available = {
            str(item.get("releaseId") or "")
            for item in self._code_analysis_release_items
        }
        if selected_release not in available:
            self._release_snapshot_status = (
                f"Não foi possível remover a release {selected_release}: "
                "ela não está mais inventariada."
            )
            self.stateChanged.emit()
            return False

        self._release_snapshot_running = True
        self._release_snapshot_status = (
            f"Removendo o índice da release {selected_release} localmente..."
        )
        self.stateChanged.emit()
        results = self._release_snapshot_results
        workspace = self._settings.root

        def remove() -> None:
            try:
                result = ErpReleaseCatalog(workspace).remove_index(
                    selected_release,
                    approved=True,
                )
            except Exception as exc:
                results.put(
                    {
                        "operation": "remove",
                        "ok": False,
                        "release_id": selected_release,
                        "error": str(exc),
                    }
                )
                self._releaseSnapshotReady.emit()
                return
            results.put(
                {
                    "operation": "remove",
                    "ok": True,
                    **result,
                }
            )
            self._releaseSnapshotReady.emit()

        self._release_snapshot_poll_timer.start()
        threading.Thread(target=remove, daemon=True).start()
        return True


    def cleanCodeProcessingOrphans(self) -> bool:  # noqa: N802
        """Delete only unreferenced generated payload after UI confirmation."""

        if (
            self._release_snapshot_running
            or self._code_processing_running
            or not self.codeProcessingCanCleanOrphans
        ):
            return False
        self._release_snapshot_running = True
        self._release_snapshot_status = "Limpando artefatos órfãos do índice..."
        self.stateChanged.emit()
        results = self._release_snapshot_results
        workspace = self._settings.root

        def clean() -> None:
            try:
                result = ErpReleaseCatalog(workspace).purge_orphaned_index_data(
                    approved=True
                )
            except Exception as exc:
                results.put(
                    {
                        "operation": "clean_orphans",
                        "ok": False,
                        "error": str(exc),
                    }
                )
                self._releaseSnapshotReady.emit()
                return
            results.put({"operation": "clean_orphans", "ok": True, **result})
            self._releaseSnapshotReady.emit()

        self._release_snapshot_poll_timer.start()
        threading.Thread(target=clean, daemon=True).start()
        return True


    def _poll_release_snapshot(self) -> None:
        latest: dict[str, Any] | None = None
        while True:
            try:
                latest = self._release_snapshot_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return

        self._release_snapshot_running = False
        self._release_snapshot_poll_timer.stop()
        release_id = str(latest.get("release_id") or "")
        if str(latest.get("operation") or "") == "clean_orphans":
            if bool(latest.get("ok")):
                reclaimed = int(latest.get("reclaimed_bytes") or 0)
                count = int(latest.get("removed_item_count") or 0)
                self._release_snapshot_status = (
                    f"Limpeza concluída: {count} artefato(s) órfão(s), "
                    f"{reclaimed / (1024 * 1024):.1f} MB liberados. "
                    "Os JARs de origem foram preservados."
                )
                self.refreshCodeProcessingStatus()
            else:
                detail = str(latest.get("error") or "falha desconhecida")
                self._release_snapshot_status = (
                    f"Não foi possível limpar os artefatos órfãos: {detail}"
                )
            self.stateChanged.emit()
            return
        if str(latest.get("operation") or "") == "remove":
            if bool(latest.get("ok")):
                self._invalidate_release_coverage()
                self._refresh_code_analysis_releases()
                self._preferences.setValue(
                    self._workspace_research_preference("code_analysis_release"),
                    self._code_analysis_release,
                )
                self._preferences.setValue(
                    "research/code_analysis_enabled",
                    self._code_analysis_enabled,
                )
                self._preferences.sync()
                self._refresh_code_analysis_jar_sources()
                self.refreshCodeProcessingStatus()
                reclaimed = int(latest.get("reclaimed_bytes") or 0)
                self._release_snapshot_status = (
                    f"Release {release_id} removida do índice. "
                    f"{reclaimed / (1024 * 1024):.1f} MB liberados; "
                    "os JARs de origem foram preservados."
                )
            else:
                detail = str(latest.get("error") or "falha desconhecida")
                self._release_snapshot_status = (
                    f"Não foi possível remover a release {release_id}: {detail}"
                )
            self.stateChanged.emit()
            return
        if bool(latest.get("ok")):
            self._invalidate_release_coverage()
            self._refresh_code_analysis_releases()
            available = {
                str(item.get("releaseId") or "")
                for item in self._code_analysis_release_items
            }
            if release_id in available:
                self._code_analysis_release = release_id
                self._preferences.setValue(
                    self._workspace_research_preference("code_analysis_release"),
                    release_id,
                )
                self._preferences.sync()
            self._refresh_code_analysis_jar_sources()
            self.refreshCodeProcessingStatus()
            jar_count = int(latest.get("jar_count") or 0)
            package_jar_count = int(latest.get("package_jar_count") or jar_count)
            base_release_id = str(latest.get("base_release_id") or "")
            analysis_scope = str(latest.get("analysis_scope") or "")
            expected_jar_count = int(latest.get("expected_jar_count") or 0)
            updated = [str(item) for item in latest.get("updated_applications") or []]
            jar_label = "JAR copiado e verificado" if jar_count == 1 else "JARs copiados e verificados"
            self._release_snapshot_status = (
                f"Release {release_id} detectada e adicionada: {jar_count} {jar_label} "
                f"localmente; pacote recebido com {package_jar_count}."
                + (
                    f" Release parcial: {jar_count} de {expected_jar_count} JARs."
                    if analysis_scope == "partial_release"
                    else ""
                )
                + (f" Base completa: {base_release_id}." if base_release_id else "")
                + (f" Atualizados: {', '.join(updated)}." if updated else "")
            )
        else:
            detail = str(latest.get("error") or "falha desconhecida")
            release_label = release_id or "automática"
            self._release_snapshot_status = (
                f"Não foi possível adicionar a release {release_label}: {detail}"
            )
        self.stateChanged.emit()


    def _refresh_code_analysis_jar_sources(self) -> None:
        workspace_path = self._settings.erp_releases_dir
        options = (
            (
                ERP_JAR_SOURCE_VR_EXEC,
                "Instalação local do ERP",
                DEFAULT_ERP_JAR_SOURCE_PATH,
            ),
            (
                ERP_JAR_SOURCE_WORKSPACE,
                "Workspace atual",
                workspace_path,
            ),
        )
        items: list[dict[str, Any]] = []
        catalog = ErpReleaseCatalog(self._settings.root)
        for value, label, path in options:
            resolved = path.resolve(strict=False)
            exists = resolved.is_dir()
            jar_count = catalog.count_source_jars(resolved) if exists else 0
            status = (
                f"{jar_count} JAR(s) encontrados"
                if exists
                else "Pasta não encontrada"
            )
            items.append(
                {
                    "value": value,
                    "label": f"{label} · {resolved}",
                    "path": str(resolved),
                    "exists": exists,
                    "jarCount": jar_count,
                    "status": status,
                }
            )
        self._code_analysis_jar_source_items = items


    def _load_cached_release_coverage(self) -> dict[str, dict[str, Any]]:
        raw = self._preferences.value(
            self._workspace_research_preference("release_coverage_cache"), ""
        )
        if not raw:
            return {}
        try:
            parsed = json.loads(str(raw)) if isinstance(raw, str) else dict(raw or {})
            if isinstance(parsed, dict):
                return {
                    key: value for key, value in parsed.items()
                    if isinstance(value, dict)
                    and isinstance(value.get("covered_jar_count"), int)
                    and value["covered_jar_count"] >= 0
                }
        except (TypeError, ValueError):
            pass
        return {}


    def _save_cached_release_coverage(self) -> None:
        try:
            self._preferences.setValue(
                self._workspace_research_preference("release_coverage_cache"),
                json.dumps(self._release_coverage_cache, ensure_ascii=False),
            )
            self._preferences.sync()
        except Exception:
            pass


    def _invalidate_release_coverage(self) -> None:
        self._release_coverage_generation += 1
        self._release_coverage_cache.clear()
        self._save_cached_release_coverage()


    def _on_coverage_warmed(self, result: object) -> None:
        self._release_coverage_thread = None
        if self._closed:
            return
        generation, workspace, requests, coverage = result
        stale = (
            generation != self._release_coverage_generation
            or workspace != self._settings.root
        )
        if not stale and coverage:
            self._release_coverage_cache.update(coverage)
            self._save_cached_release_coverage()
        self._refresh_code_analysis_releases(include_coverage=False)
        # Retry changed inputs, but leave a failed query for the next explicit
        # refresh instead of creating an endless background retry loop.
        attempted = {f"{release_id}:{manifest}" for release_id, manifest in requests}
        if stale or any(
            f"{item['releaseId']}:{item['manifestSha256']}" not in attempted
            and not item["coverageLoaded"]
            for item in self._code_analysis_release_items
        ):
            self._warm_release_coverage()
        self.stateChanged.emit()


    def _warm_release_coverage(self) -> None:
        if self._closed or self._release_coverage_thread is not None:
            return
        requests = tuple(
            (item["releaseId"], item["manifestSha256"])
            for item in self._code_analysis_release_items
            if not item["coverageLoaded"]
        )
        if not requests:
            return
        workspace = self._settings.root
        generation = self._release_coverage_generation
        stop = self._release_coverage_stop
        ready = self._codeAnalysisCoverageWarmed

        def load() -> None:
            coverage = {}
            code_index = JavaCodeIndex(workspace)
            for release_id, manifest in requests:
                if stop.is_set():
                    return
                try:
                    value = code_index.coverage(release_id)
                except (DecompilationBatchError, ErpReleaseError, OSError, ValueError, sqlite3.Error):
                    continue
                if value.get("release_manifest_sha256") == manifest:
                    coverage[f"{release_id}:{manifest}"] = value
            if not stop.is_set():
                try:
                    ready.emit((generation, workspace, requests, coverage))
                except RuntimeError:
                    pass  # The QObject may have been destroyed during shutdown.

        self._release_coverage_thread = threading.Thread(target=load, daemon=True)
        self._release_coverage_thread.start()


    def _refresh_code_analysis_releases(self, *, include_coverage: bool = True) -> None:
        if self._closed:
            return
        if self._release_coverage_root != self._settings.root:
            self._release_coverage_root = self._settings.root
            self._release_coverage_generation += 1
            self._release_coverage_cache = self._load_cached_release_coverage()
        try:
            statuses = ErpReleaseCatalog(self._settings.root).list_statuses()
        except (OSError, ValueError):
            statuses = []
        items: list[dict[str, Any]] = []
        for status in statuses[:3]:
            release_id = str(status.get("release_id") or "").strip()
            if not release_id or status.get("state") == "failed":
                continue
            manifest_sha = str(status.get("release_manifest_sha256") or "")
            cache_key = f"{release_id}:{manifest_sha}"
            freshness = str(status.get("freshness") or "unknown")
            jar_count = int(status.get("jar_count") or 0)
            coverage = self._release_coverage_cache.get(cache_key, {})
            try:
                classpath = ClasspathPolicyStore(self._settings.root).status(release_id)
            except (ClasspathError, ErpReleaseError, OSError, ValueError, sqlite3.Error):
                classpath = {}
            covered_jar_count = int(coverage.get("covered_jar_count") or 0)
            has_coverage = cache_key in self._release_coverage_cache
            coverage_label = (
                f"{covered_jar_count}/{jar_count} JARs indexados"
                if has_coverage else f"{jar_count} JARs · cobertura sob consulta"
            )
            analysis_scope = str(status.get("analysis_scope") or "full_release")
            scope_label = (
                "escopo: 1 JAR"
                if analysis_scope == ERP_JAR_SCOPE_SINGLE
                else "release incremental"
                if analysis_scope == "incremental_release"
                else "release parcial"
                if analysis_scope == "partial_release"
                else "release completa"
            )
            classpath_status = str(classpath.get("classpath_status") or "unknown")
            classpath_label = {
                "resolved": "classpath resolvido",
                "partial": "classpath parcial",
                "unknown": "classpath desconhecido",
            }.get(classpath_status, f"classpath {classpath_status}")
            freshness_label = {
                "fresh": "atualizado",
                "stale": "desatualizado",
                "missing": "origem ausente",
            }.get(freshness, "frescor desconhecido")
            items.append(
                {
                    "releaseId": release_id,
                    "manifestSha256": manifest_sha,
                    "label": (
                        f"{release_id} · {coverage_label} · {scope_label} · {freshness_label} · "
                        f"{classpath_label}"
                    ),
                    "freshness": freshness,
                    "state": str(status.get("state") or "incomplete"),
                    "coveredJarCount": covered_jar_count,
                    "coverageLoaded": has_coverage,
                    "jarCount": jar_count,
                    "analysisScope": analysis_scope,
                    "classpathStatus": classpath_status,
                    "warning": " ".join(
                        [
                            *(str(item) for item in status.get("warnings") or []),
                            *(
                                [
                                    "A ordem efetiva do classpath ainda não foi confirmada; "
                                    "resultados conflitantes serão sinalizados."
                                ]
                                if classpath_status != "resolved"
                                else []
                            ),
                        ]
                    ),
                }
            )
        self._code_analysis_release_items = items
        available = {str(item["releaseId"]) for item in items}
        if self._code_analysis_release not in available:
            self._code_analysis_release = str(items[0]["releaseId"]) if items else ""
        selected = self._selected_code_analysis_release_item()
        if (
            self._code_analysis_enabled
            and (not selected or selected.get("freshness") != "fresh")
        ):
            self._code_analysis_enabled = False
        if include_coverage:
            self._warm_release_coverage()


    def refreshCodeAnalysisReleases(self) -> None:  # noqa: N802
        previous = self._code_analysis_release
        was_enabled = self._code_analysis_enabled
        preferences_changed = False
        self._refresh_code_analysis_releases()
        self._refresh_code_analysis_jar_sources()
        if not self._code_analysis_release_items:
            self._code_analysis_enabled = False
        if self._code_analysis_release != previous:
            self._preferences.setValue(
                self._workspace_research_preference("code_analysis_release"),
                self._code_analysis_release,
            )
            preferences_changed = True
        if self._code_analysis_enabled != was_enabled:
            self._preferences.setValue(
                "research/code_analysis_enabled",
                self._code_analysis_enabled,
            )
            preferences_changed = True
        if preferences_changed:
            self._preferences.sync()
        self.refreshCodeProcessingStatus()
        self.stateChanged.emit()

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

from ...decompiled_detection import detect_decompiled_source, import_decompiled_source
from .presentation import (ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE, ERP_JAR_SOURCE_CUSTOM, ERP_JAR_SCOPE_FULL_RELEASE, ERP_JAR_SCOPE_SINGLE, DEFAULT_ERP_JAR_SOURCE_PATH, EXPECTED_ERP_JAR_COUNT, CODE_PROCESSING_HARDWARE, CODE_PROCESSING_HEAP_OPTIONS, CODE_PROCESSING_TIMEOUT_OPTIONS, CODE_PROCESSING_CPU_CORE_OPTIONS, CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS, CODE_PROCESSING_WINDOW_OPTIONS)

class CodeAdminDomain:
    """Domain operations using the facade as the sole state and transaction owner."""
    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        return getattr(self._owner, name)

    def __setattr__(self, name, value):
        setattr(self._owner, name, value)

    def application_context_items(self) -> list[dict[str, Any]]:
        data = self._apps_catalog_data.get("data", {})
        result = []
        for context in self._ultra_application_contexts:
            app = data.get("applications", {}).get(context["app_id"], {})
            variant = app.get("versions", {}).get(context["version"], {}).get("variants", {}).get(context["variant_id"], {})
            origin = next((o for o in variant.get("origin_packages", []) if o["package_id"] == context["package_id"]), {})
            ready = origin.get("index_state") == "ready" and not self._apps_catalog_error
            label = f"{app.get('name', context['app_id'])} {context['version']} · {context['variant_id'][:12]} · {context['package_id']}"
            result.append({**context, "label": label, "ready": ready,
                           "warning": "" if ready else "Origem indisponível ou índice pendente. Verifique em Aplicativos e versões."})
        return result

    def _save_application_contexts(self) -> None:
        self._preferences.setValue(self._workspace_research_preference("application_contexts"),
                                   json.dumps(self._ultra_application_contexts, ensure_ascii=False))
        self._preferences.sync()
        if not self._ultra_application_contexts:
            self._code_analysis_enabled = False
            self._preferences.setValue("research/code_analysis_enabled", False)
            self._preferences.sync()
        self.stateChanged.emit()

    def addSelectedApplicationContext(self) -> bool:  # noqa: N802
        if not (self._selected_app_id and self._selected_app_version and self._selected_app_variant_id
                and self._selected_app_origin_id):
            self._apps_catalog_error = "Selecione aplicativo, versão, variante e origem para usar no Ultra."
            self.stateChanged.emit()
            return False
        selection = {"app_id": self._selected_app_id, "version": self._selected_app_version,
                     "variant_id": self._selected_app_variant_id, "package_id": self._selected_app_origin_id}
        self._ultra_application_contexts = [item for item in self._ultra_application_contexts
                                             if item["app_id"] != selection["app_id"]] + [selection]
        self._save_application_contexts()
        return True

    def removeApplicationContext(self, app_id: str) -> None:  # noqa: N802
        self._ultra_application_contexts = [item for item in self._ultra_application_contexts if item["app_id"] != app_id]
        self._save_application_contexts()

    def setCodeAnalysisEnabled(self, enabled: bool) -> None:  # noqa: N802
        self._code_analysis_enabled = bool(
            enabled
            and self.ultraApplicationContextsReady
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
        self._code_processing_relative_jars = ()
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_release"),
            selected,
        )
        self._preferences.sync()
        self._refresh_code_analysis_jar_sources()
        self.refreshCodeProcessingStatus()
        self.refreshApplicationsCatalog()
        self.stateChanged.emit()


    def setCodeAnalysisJarSource(self, source: str) -> None:  # noqa: N802
        selected = str(source or "").strip()
        if selected not in {ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE, ERP_JAR_SOURCE_CUSTOM}:
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
        self._preferences.setValue("code_processing/max_heap_mb", selected)
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
        self._preferences.setValue("code_processing/timeout_seconds", selected)
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
        self._preferences.setValue("code_processing/max_cpu_cores", selected)
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
        self._preferences.setValue("code_processing/disk_multiplier", selected)
        self._preferences.sync()
        self.refreshCodeProcessingStatus()
        self.refreshApplicationsCatalog()
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
        self._preferences.setValue("code_processing/window", selected)
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
        relative_jars = self._code_processing_relative_jars
        results = self._code_processing_status_results
        self._code_processing_status = "Consultando cobertura local..."
        self.stateChanged.emit()

        def load() -> None:
            try:
                try:
                    coverage = ErpCodeCoverage(workspace).status(release_id)
                    if relative_jars:
                        coverage = CodeAdminDomain._scope_processing_coverage(coverage, relative_jars)
                except Exception as exc:
                    results.put((generation, release_id, None, None, str(exc)))
                    return
                latest_audit = CodeProcessingAudit(workspace).latest(
                    release_id=release_id
                )
                if relative_jars and latest_audit and tuple(latest_audit.get("details", {}).get("relative_jars", ())) != relative_jars:
                    latest_audit = None
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
                candidate = self._code_processing_status_results.get_nowait()
                if candidate[0] == self._code_processing_status_generation:
                    latest = candidate
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
        self._code_processing_can_cancel = False
        self._code_processing_cancel_requested = False
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
        self._code_processing_can_cancel = bool(
            active
            or blocked
            or (
                self._code_processing_progress > 0
                and self._code_processing_covered_jars < self._code_processing_total_jars
            )
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
        if "relative_jars" in details:
            self._code_processing_relative_jars = tuple(str(jar) for jar in details["relative_jars"])
        restored_telemetry = details.get("telemetry")
        if isinstance(restored_telemetry, dict):
            self._code_processing_telemetry = dict(restored_telemetry)
        if event == "failed":
            error = str(details.get("error") or "erro desconhecido")
            self._code_processing_status = f"Última execução falhou: {error}"
        elif event == "cancelled":
            self._code_processing_status = "Descompilação cancelada pelo usuário."
            self._code_processing_can_cancel = False
        elif event == "paused":
            self._code_processing_status = (
                "Processamento pausado entre lotes: "
                f"{self._code_processing_covered_jars}/"
                f"{self._code_processing_total_jars} JARs indexados."
            )
            self._code_processing_can_cancel = True
        elif event in {"started", "toolchain_validated", "progress", "batch_retried"}:
            self._code_processing_status = (
                "Execução anterior foi interrompida; pronta para retomar: "
                f"{self._code_processing_covered_jars}/"
                f"{self._code_processing_total_jars} JARs indexados."
            )


    def startCodeProcessing(self) -> bool:  # noqa: N802
        if self._code_processing_running or self._release_snapshot_running:
            return False
        self._code_processing_relative_jars = ()
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
                    "relative_jars": list(self._code_processing_relative_jars),
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
        self._code_processing_cancel_requested = False
        self._code_processing_cancel_event.clear()
        self._code_processing_can_cancel = True
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

    def cancelCodeProcessing(self) -> None:  # noqa: N802
        if self._code_processing_running:
            if self._code_processing_cancel_requested:
                return
            self._code_processing_cancel_requested = True
            self._code_processing_cancel_event.set()
            self._code_processing_pause_event.set()
            self._code_processing_status = (
                "Cancelamento solicitado; aguardando os lotes atuais terminarem."
            )
            self.stateChanged.emit()
            return

        release_id = (
            self._code_analysis_release
            or self._code_processing_release
            or self._selected_app_origin_id
        )
        if release_id:
            try:
                from ...jvm_batches import DecompilationBatchStore
                DecompilationBatchStore(self._settings.root).cancel_active_plans(
                    release_id, relative_jars=self._code_processing_relative_jars
                )
            except Exception as exc:
                self._code_processing_status = f"Não foi possível cancelar: {exc}"
                self.stateChanged.emit()
                return
            try:
                from ...code_coverage import CodeProcessingAudit
                same_execution = release_id == self._code_processing_release
                CodeProcessingAudit(self._settings.root).record(
                    "cancelled",
                    run_id=(self._code_processing_run_id if same_execution else "") or uuid4().hex,
                    release_id=release_id,
                    manifest_sha256=self._code_processing_manifest_hash if same_execution else "",
                    details={"cancelled_by_user": True,
                             "relative_jars": list(self._code_processing_relative_jars)},
                )
            except Exception:
                pass
        self._reset_code_processing_status("Descompilação cancelada pelo usuário.")
        self._invalidate_release_coverage()
        self._refresh_code_analysis_releases()
        self.refreshApplicationsCatalog()
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
        relative_jars = tuple(self._code_processing_relative_jars)

        def scoped(value):
            return CodeAdminDomain._scope_processing_coverage(value, relative_jars)

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
            coverage = scoped(manager.status(release_id))
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
                coverage = scoped(manager.status(release_id))
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
                if self._code_processing_cancel_event.is_set():
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    manager.cancel(release_id, **({"relative_jars": relative_jars} if relative_jars else {}))
                    coverage = scoped(manager.status(release_id))
                    self._record_code_processing_coverage(
                        audit,
                        "cancelled",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {"kind": "cancelled", "coverage": coverage, "telemetry": telemetry}
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
                    **({"relative_jars": coverage["remaining_jars"]}
                       if relative_jars and not coverage.get("active_plans") else {}),
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
                coverage = scoped(dict(advanced.get("coverage") or {}))
                self._require_frozen_code_manifest(coverage, manifest_hash)
                executed = [
                    item
                    for item in advanced.get("executed") or []
                    if isinstance(item, dict)
                ]
                telemetry = self._merge_code_processing_telemetry(
                    job_telemetry, executed, started_monotonic
                )
                if self._code_processing_cancel_event.is_set():
                    manager.cancel(release_id, **({"relative_jars": relative_jars} if relative_jars else {}))
                    coverage = scoped(manager.status(release_id))
                    self._record_code_processing_coverage(
                        audit,
                        "cancelled",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {"kind": "cancelled", "coverage": coverage, "telemetry": telemetry}
                    )
                    return
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
    def _scope_processing_coverage(coverage: dict[str, Any], relative_jars: tuple[str, ...]) -> dict[str, Any]:
        if not relative_jars:
            return coverage
        selected = set(relative_jars)
        for plan in coverage.get("active_plans", []) + coverage.get("blocked_plans", []):
            if not set(plan.get("selected_jars", [])).issubset(selected):
                raise CodeCoverageError("Existe plano de outro aplicativo neste pacote; conclua-o antes de processar a variante.")
        value = dict(coverage)
        covered = selected.intersection(coverage.get("covered_jars", []))
        remaining = selected - covered
        value.update(expected_jar_count=len(selected), covered_jar_count=len(covered),
                     covered_jars=sorted(covered), remaining_jar_count=len(remaining),
                     remaining_jars=sorted(remaining), coverage_ratio=len(covered) / len(selected),
                     progress_percent=round(100 * len(covered) / len(selected), 1))
        value["relative_jars"] = sorted(selected)
        return value

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
            "relative_jars": list(coverage.get("relative_jars") or []),
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
                self._code_processing_cancel_requested = False
                reason = str(event.get("reason") or "").strip()
                self._code_processing_status = (
                    f"Processamento pausado entre lotes: "
                    f"{self._code_processing_covered_jars}/"
                    f"{self._code_processing_total_jars} JARs indexados."
                    + (f" Motivo: {reason}." if reason else "")
                )
            elif kind == "cancelled":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                self._code_processing_cancel_requested = False
                self._code_processing_can_cancel = False
                self._code_processing_status = "Descompilação cancelada pelo usuário."
            elif kind == "attention":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                self._code_processing_cancel_requested = False
            elif kind == "completed":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                self._code_processing_cancel_requested = False
            elif kind == "error":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                self._code_processing_cancel_requested = False
                self._code_processing_status = (
                    "Falha no processamento local: "
                    + str(event.get("error") or "erro desconhecido")
                )
        if not self._code_processing_running:
            self._code_processing_poll_timer.stop()
            self._invalidate_release_coverage()
            self._refresh_code_analysis_releases()
            self.refreshApplicationsCatalog()
        self.stateChanged.emit()


    def snapshotCodeAnalysisRelease(self, release_id: str, *, source_override: str = "", single_override: bool | None = None, preview_fingerprint: list[dict[str, Any]] | None = None) -> bool:  # noqa: N802
        """Detect, categorize and inventory local JARs off the UI thread."""

        selected_release = str(release_id or "").strip()
        single_jar = self._code_analysis_snapshot_scope == ERP_JAR_SCOPE_SINGLE
        if single_override is not None:
            single_jar = single_override
        source = (
            self._code_analysis_single_jar_path
            if single_jar
            else self.codeAnalysisJarSourcePath
        )
        source = source_override or source
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
                if preview_fingerprint is not None:
                    from ...application_import import preview_application_import
                    current = preview_application_import(workspace, source, single=single_jar)
                    if current["fingerprint"] != preview_fingerprint:
                        raise ErpReleaseError("Os JARs mudaram após a prévia. Confira uma nova prévia antes de importar.")
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
                # Catalog/index readers may be initializing SQLite or reading files
                # being removed. Drain them in this worker, never on the Qt thread.
                for reader in (self._apps_catalog_thread, self._release_coverage_thread):
                    if reader is not None and reader is not threading.current_thread():
                        reader.join(timeout=5)
                        if reader.is_alive():
                            raise ErpReleaseError("A consulta do índice ainda está ativa; tente remover novamente.")
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
        if self._closed:
            return
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
        if latest.get("workspace", self._settings.root) != self._settings.root:
            return
        if latest.get("operation") in {"detect_decompiled", "import_decompiled", "delete_source_jars"}:
            if latest.get("ok"):
                result = latest["result"]
                if latest["operation"] == "detect_decompiled":
                    self._release_snapshot_status = result.get("error", "Confira os fontes detectados.")
                    self.decompiledDirectoryDetected.emit(result)
                elif latest["operation"] == "delete_source_jars":
                    self._release_snapshot_status = f"Exclusão concluída: {result['deleted_count']} JARs originais removidos."
                    self._refresh_code_analysis_jar_sources()
                    self.refreshApplicationsCatalog()
                else:
                    self._release_snapshot_status = f"Importação concluída: {result['total_indexed_sources']} fontes indexados."
                    self._invalidate_release_coverage()
                    self.refreshApplicationsCatalog()
                    self.refreshCodeAnalysisReleases()
            else:
                self._apps_catalog_error = latest["error"]
                self._release_snapshot_status = latest["error"]
            self.stateChanged.emit()
            return
        if latest.get("operation") == "preview":
            self._application_preview_thread = None
            if latest["root"] == self._settings.root and latest["generation"] == self._application_preview_generation:
                self._application_import_preview = latest["preview"]
                self._release_snapshot_status = latest["preview"].get("error", "Confira a prévia e confirme a importação.")
            self.refreshApplicationsCatalog()
            self.stateChanged.emit()
            return
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
                self.refreshApplicationsCatalog()
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
        if str(latest.get("operation") or "") == "unlink_package":
            if bool(latest.get("ok")):
                self.refreshApplicationsCatalog()
                self._invalidate_release_coverage()
                self._refresh_code_analysis_releases()
                self._refresh_code_analysis_jar_sources()
                self.refreshCodeProcessingStatus()
                pkg = str(latest.get("package_id") or "")
                self._release_snapshot_status = (
                    f"Pacote '{pkg}' e seus índices e descompilados foram excluídos com sucesso."
                )
            else:
                detail = str(latest.get("error") or "falha desconhecida")
                self._apps_catalog_error = detail
                self._release_snapshot_status = (
                    f"Não foi possível remover o pacote: {detail}"
                )
            self.stateChanged.emit()
            return
        if bool(latest.get("ok")):
            self.refreshApplicationsCatalog()
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
        custom_dir = str(
            self._preferences.value(
                self._workspace_research_preference("custom_jar_source_dir"), ""
            )
            or ""
        ).strip()
        custom_option = ()
        if custom_dir:
            custom_path = Path(custom_dir)
            custom_option = (
                (
                    ERP_JAR_SOURCE_CUSTOM,
                    f"Diretório personalizado ({custom_path.name or custom_dir})",
                    custom_path,
                ),
            )
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
        ) + custom_option
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
        if self._closed or self._release_snapshot_running or self._release_coverage_thread is not None:
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
        for status in statuses:
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
            and not self._ultra_application_contexts
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
        self.refreshApplicationsCatalog()
        self.stateChanged.emit()

    def refreshApplicationsCatalog(self) -> None:  # noqa: N802
        if self._closed:
            return
        if self._release_snapshot_running:
            self._apps_catalog_dirty = True
            return
        if self._apps_catalog_thread is not None:
            self._apps_catalog_dirty = True
            return
        workspace = self._settings.root
        signal = self._applicationsLoaded
        stop = self._release_coverage_stop
        self._apps_catalog_dirty = False

        def load():
            try:
                catalog = ErpReleaseCatalog(workspace)
                catalog.ensure_apps_catalog_synced()
                data = catalog.apps_store.load_catalog()
                index = JavaCodeIndex(workspace)
                coverage = {}
                for package_id in data["packages"]:
                    if stop.is_set():
                        return
                    if (catalog.paths.manifest_for(package_id).is_file()
                            and catalog.status(package_id).get("freshness") == "fresh"):
                        coverage[package_id] = index.coverage(package_id)
                plans = index.store.status() if coverage else []
                for application in data["applications"].values():
                    for version in application["versions"].values():
                        for variant in version["variants"].values():
                            states = []
                            for origin in variant.get("origin_packages", []):
                                cov = coverage.get(origin["package_id"], {})
                                jar = origin.get("relative_path") or variant["relative_path"]
                                ready = jar in cov.get("covered_jars", [])
                                partial = jar in cov.get("indexed_source_jars", [])
                                failed = any(
                                    p.get("release_id") == origin["package_id"]
                                    and p.get("release_manifest_sha256") == cov.get("release_manifest_sha256")
                                    and any(b.get("jar_relative_path") == jar for b in p.get("attention_batches", []))
                                    for p in plans)
                                origin["index_state"] = "ready" if ready else "failed" if failed else "partial" if partial else "pending"
                                states.append(origin["index_state"])
                            variant["index_state"] = "ready" if "ready" in states else "failed" if "failed" in states else "partial" if "partial" in states else "pending"
                            # Index coverage proves decompilation only for completed artifacts.
                            variant["decompilation_state"] = "ready" if "ready" in states else "failed" if "failed" in states else "partial" if "partial" in states else "pending"
                            count = int(variant.get("class_count") or 0) if "ready" in states else 0
                            variant["indexed_classes"] = count
                            variant["decompiled_classes"] = count
                # Read-only projection: processing truth remains in the existing index.
                catalog.apps_store = catalog.apps_store.read_view(data)
                result = {"root": workspace, "data": data,
                          "applications": catalog.apps_store.list_applications(),
                          "packages": catalog.apps_store.list_packages(),
                          "versions": {key: catalog.apps_store.list_versions(key) for key in data["applications"]}}
            except Exception as exc:
                result = {"root": workspace, "error": str(exc)}
            if not stop.is_set():
                try:
                    signal.emit(result)
                except RuntimeError:
                    pass

        self._apps_catalog_thread = threading.Thread(target=load, daemon=True)
        self._apps_catalog_thread.start()

    def _on_applications_loaded(self, result: object) -> None:
        self._apps_catalog_thread = None
        if self._closed:
            return
        if result["root"] != self._settings.root or self._apps_catalog_dirty:
            self.refreshApplicationsCatalog()
            return
        self._apps_catalog_error = result.get("error", "")
        if not self._apps_catalog_error:
            self._apps_catalog_data = result
            self._applications_catalog = result["applications"]
            self._packages_catalog = result["packages"]
            self.selectApplication(self._selected_app_id)
        self.stateChanged.emit()

    def selectApplication(self, app_id: str) -> None:  # noqa: N802
        selected = str(app_id or "").strip()
        previous = self._selected_app_version if selected == self._selected_app_id else ""
        self._selected_app_id = selected if selected in self._apps_catalog_data.get("versions", {}) else ""
        self._app_versions = self._apps_catalog_data.get("versions", {}).get(self._selected_app_id, [])
        self.selectAppVersion(previous)
        self.stateChanged.emit()

    def selectAppVersion(self, version: str) -> None:  # noqa: N802
        versions = self._apps_catalog_data.get("data", {}).get("applications", {}).get(self._selected_app_id, {}).get("versions", {})
        selected = str(version or "").strip()
        previous = self._selected_app_variant_id if selected == self._selected_app_version else ""
        self._selected_app_version = selected if selected in versions else ""
        self._app_variants = list(versions.get(self._selected_app_version, {}).get("variants", {}).values())
        self._version_comparison_result = {}
        self._app_comparison_generation += 1
        if not previous and len(self._app_variants) == 1:
            previous = self._app_variants[0]["variant_id"]
        self.selectAppVariant(previous)
        self.stateChanged.emit()

    def selectAppVariant(self, variant_id: str) -> None:  # noqa: N802
        self._app_sources = {}
        self._app_comparison_generation += 1
        selected = str(variant_id or "").strip()
        self._selected_version_details = dict(next((v for v in self._app_variants if v["variant_id"] == selected), {}))
        self._selected_app_variant_id = self._selected_version_details.get("variant_id", "")
        origins = self._selected_version_details.get("origin_packages", [])
        if not any(o["package_id"] == self._selected_app_origin_id for o in origins):
            self._selected_app_origin_id = origins[0]["package_id"] if len(origins) == 1 else ""
        self._activate_selected_processing_scope()
        self._version_comparison_result = {}
        self.stateChanged.emit()

    def _activate_selected_processing_scope(self) -> None:
        origin = next((o for o in self._selected_version_details.get("origin_packages", [])
                       if o["package_id"] == self._selected_app_origin_id), {})
        if not origin:
            return
        state = origin.get("index_state", "pending")
        self._selected_version_details.update(index_state=state, decompilation_state=state,
            indexed_classes=self._selected_version_details.get("class_count", 0) if state == "ready" else 0)
        jar = str(origin.get("relative_path") or self._selected_version_details.get("relative_path") or "")
        if (self._code_processing_running or self._release_snapshot_running or not jar
                or not any(item["releaseId"] == self._selected_app_origin_id for item in self._code_analysis_release_items)):
            return
        if self._code_analysis_release == self._selected_app_origin_id and self._code_processing_relative_jars == (jar,):
            return
        self.setCodeAnalysisRelease(self._selected_app_origin_id)
        self._cancel_code_processing_status_refresh()
        self._code_processing_relative_jars = (jar,)
        self._reset_code_processing_status("Consultando a variante selecionada…")
        self.refreshCodeProcessingStatus()

    def previewApplicationImport(self, source: str, single: bool, release_id: str = "") -> bool:  # noqa: N802
        if self._release_snapshot_running or self._code_processing_running or not source or self._closed:
            return False
        self._application_preview_generation += 1
        generation = self._application_preview_generation
        workspace = self._settings.root
        results = self._release_snapshot_results
        signal = self._releaseSnapshotReady
        stop = self._release_coverage_stop
        self._application_import_preview = {"state": "running"}
        self._release_snapshot_running = True
        self._release_snapshot_status = "Lendo aplicativos e verificando os hashes para a prévia…"
        def preview():
            from ...application_import import preview_application_import
            try:
                result = {**preview_application_import(workspace, source, single=single),
                          "state": "ready", "release_id": release_id}
            except Exception as exc:
                result = {"state": "error", "error": str(exc)}
            if not stop.is_set():
                results.put({"operation": "preview", "generation": generation, "root": workspace, "preview": result})
                try:
                    signal.emit()
                except RuntimeError:
                    pass
        self._release_snapshot_poll_timer.start()
        self._application_preview_thread = threading.Thread(target=preview, daemon=True)
        self._application_preview_thread.start()
        self.stateChanged.emit()
        return True

    def confirmApplicationImport(self) -> bool:  # noqa: N802
        preview = self._application_import_preview
        if preview.get("state") != "ready":
            return False
        started = CodeAdminDomain.snapshotCodeAnalysisRelease(self, preview["release_id"],
            source_override=preview["source"], single_override=preview["single"],
            preview_fingerprint=preview["fingerprint"])
        if started:
            self._application_import_preview = {}
            self.stateChanged.emit()
        return started

    def importPackage(self, source_path: str) -> bool:  # noqa: N802
        if not str(source_path or "").strip():
            return False
        candidate = Path(source_path).resolve()
        if not candidate.is_dir():
            return False
        return CodeAdminDomain.snapshotCodeAnalysisRelease(self, "", source_override=str(candidate), single_override=False)

    def importSingleJar(self, jar_path: str) -> bool:  # noqa: N802
        candidate = Path(str(jar_path or "").strip()).resolve()
        if not candidate.is_file() or candidate.suffix.casefold() != ".jar":
            return False
        return CodeAdminDomain.snapshotCodeAnalysisRelease(self, "", source_override=str(candidate), single_override=True)

    def selectAndImportPackage(self) -> str:  # noqa: N802
        initial = self.codeAnalysisJarSourcePath or str(self._settings.root)
        selected = QFileDialog.getExistingDirectory(
            None,
            "Selecionar pasta de pacote VR",
            initial,
        )
        if selected and self.previewApplicationImport(selected, False, ""):
            return selected
        return ""

    def selectAndImportSingleJar(self) -> str:  # noqa: N802
        initial = self.codeAnalysisJarSourcePath or str(self._settings.root)
        selected, _filter = QFileDialog.getOpenFileName(
            None,
            "Selecionar JAR de aplicativo VR",
            initial,
            "Arquivos JAR (*.jar)",
        )
        if selected and self.previewApplicationImport(selected, True, ""):
            return selected
        return ""

    def selectCustomJarDirectory(self) -> str:  # noqa: N802
        initial = self.codeAnalysisJarSourcePath or str(self._settings.root)
        selected = QFileDialog.getExistingDirectory(
            None,
            "Selecionar diretório padrão de JARs do ERP",
            initial,
        )
        if selected:
            resolved = str(Path(selected).resolve())
            self._preferences.setValue(
                self._workspace_research_preference("custom_jar_source_dir"),
                resolved,
            )
            self._preferences.setValue(
                self._workspace_research_preference("code_analysis_jar_source"),
                ERP_JAR_SOURCE_CUSTOM,
            )
            self._code_analysis_jar_source = ERP_JAR_SOURCE_CUSTOM
            self._preferences.sync()
            self._refresh_code_analysis_jar_sources()
            self.stateChanged.emit()
            return resolved
        return ""

    def renamePackage(self, package_id: str, new_name: str) -> bool:  # noqa: N802
        if self._closed or self._release_snapshot_running or self._code_processing_running:
            return False
        try:
            catalog = ErpReleaseCatalog(self._settings.root)
            catalog.rename_package(package_id, new_name)
            self.refreshApplicationsCatalog()
            return True
        except Exception as exc:
            self._apps_catalog_error = str(exc)
            self.stateChanged.emit()
            return False

    def deleteSourceJars(self, package_id: str) -> dict[str, Any]:  # noqa: N802
        if self._closed or self._release_snapshot_running or self._code_processing_running:
            return {"deleted_count": 0, "error": "Aguarde a operação em andamento."}
        workspace = self._settings.root
        self._start_package_task("delete_source_jars", lambda: ErpReleaseCatalog(workspace).delete_source_jars(package_id))
        return {"pending": True}

    def detectDecompiledDirectory(self, directory: str = "") -> dict[str, Any]:  # noqa: N802
        if self._closed or self._release_snapshot_running or self._code_processing_running:
            return {"is_valid": False, "busy": True}
        target_dir = str(directory or "").strip()
        if not target_dir:
            initial = str(self._settings.root)
            target_dir = QFileDialog.getExistingDirectory(
                None,
                "Selecionar pasta de código descompilado",
                initial,
            )
            if not target_dir:
                return {"is_valid": False, "canceled": True}
        self._start_package_task("detect_decompiled", lambda: detect_decompiled_source(target_dir))
        return {"pending": True}

    def importDecompiledDirectory(self, source_dir: str, release_id: str = "", package_name: str = "") -> dict[str, Any]:  # noqa: N802
        if self._closed or self._release_snapshot_running or self._code_processing_running:
            return {"success": False, "busy": True}
        workspace = self._settings.root
        self._start_package_task("import_decompiled", lambda: import_decompiled_source(
            workspace, source_dir, release_id=release_id, package_name=package_name,
        ))
        return {"pending": True}

    def _start_package_task(self, operation: str, task: Any) -> None:
        workspace = self._settings.root
        results = self._release_snapshot_results
        signal = self._releaseSnapshotReady
        self._release_snapshot_running = True
        self._release_snapshot_status = {
            "detect_decompiled": "Detectando fontes...",
            "import_decompiled": "Importando fontes...",
            "delete_source_jars": "Verificando e excluindo JARs originais...",
        }[operation]
        self._apps_catalog_error = ""

        def worker() -> None:
            result = {"operation": operation, "workspace": workspace}
            try:
                result.update(ok=True, result=task())
            except Exception as exc:
                result.update(ok=False, error=str(exc))
            results.put(result)
            if not self._closed:
                signal.emit()

        self._package_operation_thread = threading.Thread(target=worker, daemon=False)
        self._release_snapshot_poll_timer.start()
        self._package_operation_thread.start()
        self.stateChanged.emit()

    def unlinkPackage(self, package_id: str, delete_data: bool = False) -> bool:  # noqa: N802
        selected = str(package_id or "").strip()
        if not selected or self._closed or self._release_snapshot_running or self._code_processing_running:
            return False

        if not delete_data:
            try:
                catalog = ErpReleaseCatalog(self._settings.root)
                catalog.unlink_package(selected, delete_data=False)
                self.refreshApplicationsCatalog()
                self.refreshCodeAnalysisReleases()
                self.stateChanged.emit()
                return True
            except Exception as exc:
                self._apps_catalog_error = str(exc)
                self.stateChanged.emit()
                return False

        if self._release_snapshot_running or self._code_processing_running:
            return False

        self._release_snapshot_running = True
        self._release_snapshot_status = (
            f"Removendo pacote '{selected}' e excluindo índices e descompilados..."
        )
        self.stateChanged.emit()
        results = self._release_snapshot_results
        workspace = self._settings.root

        def worker() -> None:
            try:
                for reader in (self._apps_catalog_thread, self._release_coverage_thread):
                    if reader is not None and reader is not threading.current_thread():
                        reader.join(timeout=5)
                        if reader.is_alive():
                            raise ErpReleaseError(
                                "A consulta do índice ainda está ativa; tente remover novamente."
                            )
                catalog = ErpReleaseCatalog(workspace)
                res = catalog.unlink_package(selected, delete_data=True)
            except Exception as exc:
                results.put({
                    "operation": "unlink_package",
                    "workspace": workspace,
                    "ok": False,
                    "package_id": selected,
                    "error": str(exc),
                })
                if not self._closed:
                    self._releaseSnapshotReady.emit()
                return
            results.put({
                "operation": "unlink_package",
                "workspace": workspace,
                "ok": True,
                "package_id": selected,
                "deleted_data": True,
                **res,
            })
            if not self._closed:
                self._releaseSnapshotReady.emit()

        self._release_snapshot_poll_timer.start()
        self._package_operation_thread = threading.Thread(target=worker, daemon=False)
        self._package_operation_thread.start()
        return True

    def overrideVersion(self, app_id: str, current_version: str, manual_version: str, *, variant_id: str = "") -> bool:  # noqa: N802
        try:
            catalog = ErpReleaseCatalog(self._settings.root)
            catalog.override_version(app_id, current_version, manual_version, variant_id=variant_id)
            self._selected_app_id = app_id
            self._selected_app_version = manual_version
            for context in self._ultra_application_contexts:
                if context["app_id"] == app_id and context["version"] == current_version and (not variant_id or context["variant_id"] == variant_id):
                    context["version"] = manual_version
            self._save_application_contexts()
            self.refreshApplicationsCatalog()
            return True
        except Exception as exc:
            self._apps_catalog_error = str(exc)
            self.stateChanged.emit()
            return False

    def loadApplicationSources(self, query: str, offset: int, source_key: str) -> bool:  # noqa: N802
        if self._closed or self._app_sources_thread is not None:
            return False
        selection = {"app_id": self._selected_app_id, "version": self._selected_app_version,
                     "variant_id": self._selected_app_variant_id, "package_id": self._selected_app_origin_id}
        generation = self._app_comparison_generation
        workspace = self._settings.root
        signal = self._appSourcesLoaded
        stop = self._release_coverage_stop
        def browse():
            from ...code_context import freeze_application_contexts, validate_application_contexts
            try:
                contexts = freeze_application_contexts(workspace, [selection])
                result = JavaCodeIndex(workspace).browse_application_sources(contexts[0], query=query, offset=offset, source_key=source_key)
                validate_application_contexts(workspace, contexts)
            except Exception as exc:
                result = {"state": "error", "error": str(exc)}
            if not stop.is_set():
                try:
                    signal.emit((generation, workspace, result))
                except RuntimeError:
                    pass
        self._app_sources = {**self._app_sources, "state": "running", "body": "", "error": ""}
        self._app_sources_thread = threading.Thread(target=browse, daemon=True)
        self._app_sources_thread.start()
        self.stateChanged.emit()
        return True

    def compareAppVersions(self, app_id: str, base_version: str, target_version: str, base_variant_id: str = "", target_variant_id: str = "") -> dict[str, Any]:  # noqa: N802
        if self._app_comparison_thread is not None or self._closed:
            return {"state": "busy"}
        self._app_comparison_generation += 1
        generation = self._app_comparison_generation
        workspace = self._settings.root
        data = json.loads(json.dumps(self._apps_catalog_data.get("data", {})))
        signal = self._appComparisonLoaded
        stop = self._release_coverage_stop

        def compare():
            try:
                catalog = ErpReleaseCatalog(workspace)
                if data:
                    catalog.apps_store = catalog.apps_store.read_view(data)
                result = catalog.apps_store.compare_versions(app_id, base_version, target_version,
                    base_variant_id=base_variant_id, target_variant_id=target_variant_id)
            except Exception as exc:
                result = {"state": "error", "error": str(exc)}
            if not stop.is_set():
                try:
                    signal.emit((generation, workspace, result))
                except RuntimeError:
                    pass

        self._version_comparison_result = {"state": "running"}
        self._app_comparison_thread = threading.Thread(target=compare, daemon=True)
        self._app_comparison_thread.start()
        self.stateChanged.emit()
        return {"state": "running"}

    def _on_app_comparison_loaded(self, payload: object) -> None:
        self._app_comparison_thread = None
        generation, workspace, result = payload
        if not self._closed and generation == self._app_comparison_generation and workspace == self._settings.root:
            self._version_comparison_result = result
            self.stateChanged.emit()

    def startVariantProcessing(self, app_id: str, version: str, variant_id: str) -> bool:  # noqa: N802
        if self._code_processing_running or self._release_snapshot_running:
            return False
        try:
            catalog = ErpReleaseCatalog(self._settings.root)
            var = catalog.get_variant(app_id, version, variant_id)
            if not var:
                return False
            origins = var.get("origin_packages", [])
            target_release = self._selected_app_origin_id
            origin = next((o for o in origins if o["package_id"] == target_release), None)
            if not origin:
                raise ValueError("Selecione o pacote de origem para definir as dependências da análise.")
            if not target_release:
                return False
            self.setCodeAnalysisRelease(target_release)
            if self._code_analysis_release != target_release:
                raise ValueError("O pacote selecionado não está disponível para processamento.")
            manifest = catalog.load_manifest(target_release)
            jar = str(origin.get("relative_path") or var["relative_path"])
            if not any(a.get("relative_path") == jar and a.get("sha256") == var["sha256"] for a in manifest["artifacts"]):
                raise ValueError("O pacote não contém mais a variante selecionada; atualize o catálogo.")
            self._code_processing_relative_jars = (jar,)
            self._code_processing_covered_jars = 0
            self._code_processing_total_jars = 1
            return self._start_code_processing(retry_batch_id="")
        except Exception as exc:
            self._code_processing_status = str(exc)
            self.stateChanged.emit()
            return False

    def startBatchAppsProcessing(self, app_ids: list[str]) -> bool:  # noqa: N802
        if self._code_processing_running or self._release_snapshot_running:
            return False
        if not app_ids:
            return False
        try:
            catalog = ErpReleaseCatalog(self._settings.root)
            data = catalog.apps_store.load_catalog()
            all_jars: list[str] = []
            target_release = self._selected_app_origin_id or self._code_analysis_release

            for app_id in app_ids:
                app = data.get("applications", {}).get(app_id)
                if not app:
                    continue
                for ver in app.get("versions", {}).values():
                    for var in ver.get("variants", {}).values():
                        origins = var.get("origin_packages", [])
                        if not origins:
                            continue
                        if not target_release:
                            target_release = origins[0].get("package_id")
                        origin = next(
                            (o for o in origins if o.get("package_id") == target_release),
                            origins[0],
                        )
                        jar = str(origin.get("relative_path") or var.get("relative_path") or "")
                        if jar and jar not in all_jars:
                            all_jars.append(jar)

            if not target_release or not all_jars:
                raise ValueError("Nenhum arquivo JAR elegível encontrado para os aplicativos selecionados.")

            self.setCodeAnalysisRelease(target_release)
            if self._code_analysis_release != target_release:
                raise ValueError("O pacote selecionado não está disponível para processamento.")

            manifest = catalog.load_manifest(target_release)
            manifest_jars = {a.get("relative_path") for a in manifest.get("artifacts", [])}
            valid_jars = tuple(j for j in all_jars if j in manifest_jars)
            if not valid_jars:
                raise ValueError("Nenhum dos JARs selecionados foi encontrado no manifesto do pacote.")

            self._code_processing_relative_jars = valid_jars
            self._code_processing_covered_jars = 0
            self._code_processing_total_jars = len(valid_jars)
            return self._start_code_processing(retry_batch_id="")
        except Exception as exc:
            self._code_processing_status = str(exc)
            self.stateChanged.emit()
            return False

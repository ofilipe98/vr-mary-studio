"""Incremental, capacity-aware coverage workflow for ERP code indexes."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .classpath import ClasspathPolicyStore
from .code_index import JavaCodeIndex
from .code_processing_audit import CodeProcessingAudit
from .erp_releases import ErpReleaseCatalog
from .jvm_batches import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_CLASSES,
    PROCESSING_SCHEMA_VERSION,
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
    DecompilationBatchStore,
)


class CodeCoverageError(RuntimeError):
    """Controlled capacity, selection, or execution failure."""


class ErpCodeCoverage:
    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        store: DecompilationBatchStore | None = None,
        planner: DecompilationBatchPlanner | None = None,
        executor: DecompilationBatchExecutor | None = None,
        adapters: Sequence[Any] | None = None,
        code_index: JavaCodeIndex | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.store = store or DecompilationBatchStore(self.root)
        self.planner = planner or DecompilationBatchPlanner(
            self.root, catalog=self.catalog, store=self.store
        )
        self.executor = executor or DecompilationBatchExecutor(
            self.root,
            catalog=self.catalog,
            store=self.store,
            adapters=adapters,
        )
        self.code_index = code_index or JavaCodeIndex(
            self.root, catalog=self.catalog, store=self.store
        )

    def status(self, release_id: str) -> dict[str, Any]:
        release = self.catalog.status(release_id)
        manifest = self.catalog.load_manifest(release_id)
        release_hash = str(manifest.get("release_manifest_sha256") or "")
        artifacts = [
            item
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        ]
        artifact_by_path = {
            str(item["relative_path"]): item for item in artifacts
        }
        all_jars = set(artifact_by_path)
        plans = [
            item
            for item in self.store.status()
            if item.get("release_id") == release_id
            and item.get("release_manifest_sha256") == release_hash
        ]
        code_status = self.code_index.coverage(release_id)
        indexed_origins = set(code_status.get("indexed_source_jars") or [])
        covered = set(code_status.get("covered_jars") or [])
        covered.intersection_update(all_jars)
        remaining = sorted(all_jars - covered, key=str.casefold)
        expected_classes = sum(
            max(0, int(item.get("class_count") or 0)) for item in artifacts
        )
        with self.store.connect() as connection:
            class_progress = connection.execute(
                """SELECT count(*) AS discovered,
                          coalesce(sum(
                              CASE WHEN c.state = 'completed'
                                     AND c.processing_schema_version = ?
                                   THEN 1 ELSE 0 END
                          ), 0) AS processed
                   FROM class_occurrences o
                   JOIN class_contents c
                     ON c.content_sha256 = o.content_sha256
                   WHERE o.release_hash = ?""",
                (PROCESSING_SCHEMA_VERSION, release_hash),
            ).fetchone()
        discovered_classes = min(
            expected_classes, max(0, int(class_progress["discovered"] or 0))
        )
        processed_classes = min(
            expected_classes, max(0, int(class_progress["processed"] or 0))
        )
        active = [
            plan
            for plan in plans
            if int(plan.get("schema_version") or 0) == PROCESSING_SCHEMA_VERSION
            and any(str(jar) in remaining for jar in plan.get("selected_jars") or [])
            and plan.get("state") not in {"completed", "failed"}
            and any(
                int((plan.get("batches_by_state") or {}).get(state) or 0) > 0
                for state in ("pending", "running")
            )
        ]
        blocked = [
            plan
            for plan in plans
            if int(plan.get("schema_version") or 0) == PROCESSING_SCHEMA_VERSION
            and any(str(jar) in remaining for jar in plan.get("selected_jars") or [])
            and plan.get("state") != "completed"
            and plan not in active
            and bool(plan.get("attention_batches"))
        ]
        storage = self.catalog.storage_status()
        expansion_multiplier = max(
            1,
            int(
                storage.get("storage_budget_multiplier")
                or self.catalog.storage_budget_multiplier
            ),
        )
        remaining_source_bytes = sum(
            int(artifact_by_path[jar].get("size_bytes") or 0) for jar in remaining
        )
        conservative_remaining_bytes = remaining_source_bytes * expansion_multiplier
        forecast_bytes = int(storage.get("used_bytes") or 0) + conservative_remaining_bytes
        budget = int(storage.get("budget_bytes") or 0)
        free_disk = int(shutil.disk_usage(self.root).free)
        if (budget and forecast_bytes > budget) or conservative_remaining_bytes > free_disk:
            capacity_state = "insufficient"
        elif budget and forecast_bytes >= int(budget * 0.9):
            capacity_state = "tight"
        else:
            capacity_state = "ready"
        total = len(all_jars)
        if expected_classes:
            # Inventory/planning accounts for a small, visible part of the work;
            # decompilation and source indexing remain the dominant component.
            weighted_done = processed_classes + (discovered_classes * 0.05)
            progress_percent = round(
                min(99.9, weighted_done * 100 / (expected_classes * 1.05)), 1
            )
        else:
            progress_percent = round(len(covered) * 100 / total, 1) if total else 0.0
        if not remaining and total:
            progress_percent = 100.0
        classpath = ClasspathPolicyStore(
            self.root, catalog=self.catalog
        ).status(release_id)
        eta = CodeProcessingAudit(self.root).estimate_remaining(
            release_id=release_id,
            manifest_sha256=release_hash,
            remaining_jar_count=len(remaining),
        )
        return {
            "release": release,
            "release_manifest_sha256": release_hash,
            "expected_jar_count": total,
            "covered_jar_count": len(covered),
            "coverage_ratio": round(len(covered) / total, 6) if total else 0.0,
            "expected_class_count": expected_classes,
            "discovered_class_count": discovered_classes,
            "processed_class_count": processed_classes,
            "progress_percent": progress_percent,
            "covered_jars": sorted(covered, key=str.casefold),
            "remaining_jar_count": len(remaining),
            "remaining_jars": remaining,
            "indexed_source_jar_count": len(indexed_origins),
            "indexed_source_jars": sorted(indexed_origins, key=str.casefold),
            "active_plans": active,
            "blocked_plans": blocked,
            "plans": plans,
            "code_index": code_status,
            "capacity": {
                **storage,
                "free_disk_bytes": free_disk,
                "remaining_source_bytes": remaining_source_bytes,
                "conservative_remaining_bytes": conservative_remaining_bytes,
                "conservative_forecast_bytes": forecast_bytes,
                "state": capacity_state,
            },
            "classpath_order_known": bool(classpath.get("classpath_order_known")),
            "classpath_status": str(classpath.get("classpath_status") or "unknown"),
            "classpath": classpath,
            "eta": eta,
        }

    def advance(
        self,
        release_id: str,
        *,
        approved: bool = False,
        relative_jars: Iterable[str] = (),
        jars_per_plan: int = 1,
        batch_limit: int = 1,
        max_classes: int = DEFAULT_MAX_CLASSES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_heap_mb: int = 2048,
        timeout_seconds: int = 300,
        max_cpu_cores: int = 1,
        parallel_workers: int = 1,
        process_priority: str = "low",
        processing_window: str = "always",
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not approved:
            raise CodeCoverageError(
                "O avanço de cobertura exige aprovação explícita de processamento."
            )
        before = self.status(release_id)
        release = before["release"]
        if release.get("state") != "ready" or release.get("freshness") != "fresh":
            raise CodeCoverageError("A release precisa estar pronta e atualizada.")

        active = before["active_plans"]
        blocked = before["blocked_plans"]
        selected: list[str] = []
        if active:
            if relative_jars:
                raise CodeCoverageError(
                    "Já existe um plano ativo; conclua-o antes de selecionar outros JARs."
                )
            plan = sorted(active, key=lambda item: str(item.get("created_at") or ""))[0]
            plan_id = str(plan["plan_id"])
            selected = [str(item) for item in plan.get("selected_jars") or []]
        elif blocked:
            batch_ids = [
                str(batch.get("batch_id") or "")
                for plan in blocked
                for batch in plan.get("attention_batches") or []
                if batch.get("batch_id")
            ]
            raise CodeCoverageError(
                "Existe plano atual com lote que exige revisão/retry: "
                + ", ".join(batch_ids)
            )
        else:
            remaining = set(before["remaining_jars"])
            requested = list(
                dict.fromkeys(str(item).replace("\\", "/") for item in relative_jars)
            )
            unknown = [item for item in requested if item not in remaining]
            if unknown:
                raise CodeCoverageError(
                    "JARs não pendentes ou inexistentes: " + ", ".join(unknown)
                )
            if requested:
                selected = requested
            else:
                manifest = self.catalog.load_manifest(release_id)
                candidates = [
                    item
                    for item in manifest.get("artifacts", [])
                    if isinstance(item, dict)
                    and str(item.get("relative_path") or "") in remaining
                ]
                candidates.sort(
                    key=lambda item: (
                        int(item.get("size_bytes") or 0),
                        str(item.get("relative_path") or "").casefold(),
                    )
                )
                selected = [
                    str(item["relative_path"])
                    for item in candidates[: max(1, int(jars_per_plan))]
                ]
            if not selected:
                return {
                    "state": "completed",
                    "selected_jars": [],
                    "executed": [],
                    "indexed": {},
                    "coverage": before,
                }
            self._validate_capacity(release_id, selected, before)
            plan = self.planner.plan(
                release_id,
                selected,
                max_classes=max_classes,
                max_bytes=max_bytes,
                progress=progress,
            )
            plan_id = str(plan["plan_id"])

        execution = self.executor.run(
            plan_id,
            limit=max(1, int(batch_limit)),
            max_heap_mb=max_heap_mb,
            timeout_seconds=timeout_seconds,
            max_cpu_cores=max_cpu_cores,
            max_workers=parallel_workers,
            process_priority=process_priority,
            processing_window=processing_window,
        )
        executed = [
            item
            for item in execution.get("executed") or []
            if isinstance(item, dict)
        ]
        completed_batch_ids = [
            str(item.get("batch_id") or "")
            for item in executed
            if item.get("batch_id") and item.get("state") == "completed"
        ]
        indexed = self.code_index.index_plan(
            plan_id,
            batch_ids=completed_batch_ids,
        )
        after = self.status(release_id)
        plan_state = str((execution.get("plan") or {}).get("state") or "unknown")
        return {
            "state": plan_state,
            "plan_id": plan_id,
            "selected_jars": selected,
            "executed": executed,
            "indexed": indexed,
            "coverage": after,
        }

    def _validate_capacity(
        self,
        release_id: str,
        selected: list[str],
        status: dict[str, Any],
    ) -> None:
        manifest = self.catalog.load_manifest(release_id)
        sizes = {
            str(item.get("relative_path") or ""): int(item.get("size_bytes") or 0)
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict)
        }
        capacity = status["capacity"]
        expansion_multiplier = max(
            1,
            int(
                capacity.get("storage_budget_multiplier")
                or self.catalog.storage_budget_multiplier
            ),
        )
        reserve = sum(sizes[item] for item in selected) * expansion_multiplier
        budget = int(capacity.get("budget_bytes") or 0)
        remaining_budget = int(capacity.get("remaining_bytes") or 0)
        free_disk = int(capacity.get("free_disk_bytes") or 0)
        if budget and reserve > remaining_budget:
            raise CodeCoverageError(
                "O orçamento de índice não comporta a estimativa conservadora "
                f"de {reserve} bytes para o próximo plano; disponíveis no limite: "
                f"{remaining_budget} bytes."
            )
        if reserve > free_disk:
            raise CodeCoverageError(
                "O disco não comporta a estimativa conservadora do próximo plano."
            )


__all__ = ["CodeCoverageError", "ErpCodeCoverage"]

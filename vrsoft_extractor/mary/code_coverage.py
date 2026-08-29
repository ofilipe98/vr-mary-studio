"""Incremental, capacity-aware coverage workflow for ERP code indexes."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable

from .code_index import JavaCodeIndex
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
        code_index: JavaCodeIndex | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.store = store or DecompilationBatchStore(self.root)
        self.planner = planner or DecompilationBatchPlanner(
            self.root, catalog=self.catalog, store=self.store
        )
        self.executor = executor or DecompilationBatchExecutor(
            self.root, catalog=self.catalog, store=self.store
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
        covered = {
            str(jar)
            for plan in plans
            if plan.get("state") == "completed"
            for jar in plan.get("selected_jars") or []
        }
        code_status = self.code_index.coverage(release_id)
        indexed_origins = set(code_status.get("indexed_source_jars") or [])
        covered.intersection_update(all_jars)
        remaining = sorted(all_jars - covered, key=str.casefold)
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
        remaining_source_bytes = sum(
            int(artifact_by_path[jar].get("size_bytes") or 0) for jar in remaining
        )
        conservative_remaining_bytes = remaining_source_bytes * 10
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
        return {
            "release": release,
            "release_manifest_sha256": release_hash,
            "expected_jar_count": total,
            "covered_jar_count": len(covered),
            "coverage_ratio": round(len(covered) / total, 6) if total else 0.0,
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
            "classpath_order_known": bool(manifest.get("classpath_order_known")),
            "classpath_status": str(manifest.get("classpath_status") or "unknown"),
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
            )
            plan_id = str(plan["plan_id"])

        execution = self.executor.run(
            plan_id,
            limit=max(1, int(batch_limit)),
            max_heap_mb=max_heap_mb,
            timeout_seconds=timeout_seconds,
        )
        indexed = self.code_index.index_plan(plan_id)
        after = self.status(release_id)
        plan_state = str((execution.get("plan") or {}).get("state") or "unknown")
        return {
            "state": plan_state,
            "plan_id": plan_id,
            "selected_jars": selected,
            "executed": execution.get("executed") or [],
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
        reserve = sum(sizes[item] for item in selected) * 10
        capacity = status["capacity"]
        budget = int(capacity.get("budget_bytes") or 0)
        remaining_budget = int(capacity.get("remaining_bytes") or 0)
        free_disk = int(capacity.get("free_disk_bytes") or 0)
        if budget and reserve > remaining_budget:
            raise CodeCoverageError(
                "O orçamento de índice não comporta a estimativa conservadora "
                f"de {reserve} bytes para o próximo plano."
            )
        if reserve > free_disk:
            raise CodeCoverageError(
                "O disco não comporta a estimativa conservadora do próximo plano."
            )


__all__ = ["CodeCoverageError", "ErpCodeCoverage"]

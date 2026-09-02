from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.code_coverage import CodeCoverageError, ErpCodeCoverage
from vrsoft_extractor.mary.cli import main as cli_main
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import (
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
    DecompilationBatchStore,
)
from vrsoft_extractor.mary.jvm_toolchain import DecompileRequest, DecompileResult


def _jar(path: Path, classes: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
        for name, body in classes.items():
            archive.writestr(name, body)


class _SuccessfulAdapter:
    name = "fake"

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(request.input_path) as archive:
            families = sorted(
                {
                    name.removesuffix(".class").split("$", 1)[0]
                    for name in archive.namelist()
                    if name.endswith(".class")
                }
            )
        for family in families:
            relative = Path(*family.split("/")).with_suffix(".java")
            target = request.output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            package, _, simple_name = family.replace("/", ".").rpartition(".")
            target.write_text(
                f"package {package};\npublic class {simple_name} {{}}\n",
                encoding="utf-8",
            )
        return DecompileResult(
            tool=self.name,
            status="completed",
            duration_ms=1,
            exit_code=0,
            output_dir=str(request.output_dir),
        )


def _manager(
    tmp_path: Path, *, storage_budget_multiplier: int = 100_000
) -> ErpCodeCoverage:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    _jar(source / "A.jar", {"br/vr/A.class": b"class-a"})
    _jar(source / "B.jar", {"br/vr/B.class": b"class-b"})
    catalog = ErpReleaseCatalog(
        tmp_path,
        expected_jar_count=2,
        storage_budget_multiplier=storage_budget_multiplier,
    )
    catalog.import_release("r1")
    store = DecompilationBatchStore(tmp_path)
    return ErpCodeCoverage(
        tmp_path,
        catalog=catalog,
        store=store,
        planner=DecompilationBatchPlanner(tmp_path, catalog=catalog, store=store),
        executor=DecompilationBatchExecutor(
            tmp_path,
            catalog=catalog,
            store=store,
            adapters=(_SuccessfulAdapter(),),
        ),
    )


def test_coverage_advances_one_approved_jar_end_to_end(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    before = manager.status("r1")

    assert before["covered_jar_count"] == 0
    assert before["remaining_jar_count"] == 2
    assert before["expected_class_count"] == 2
    assert before["discovered_class_count"] == 0
    assert before["processed_class_count"] == 0
    assert before["progress_percent"] == 0.0
    with pytest.raises(CodeCoverageError, match="aprovação explícita"):
        manager.advance("r1", relative_jars=("A.jar",))

    result = manager.advance(
        "r1",
        approved=True,
        relative_jars=("A.jar",),
        batch_limit=10,
        max_classes=10,
        max_bytes=1024,
    )

    assert result["state"] == "completed"
    assert result["selected_jars"] == ["A.jar"]
    assert result["indexed"]["errors"] == []
    assert result["coverage"]["covered_jars"] == ["A.jar"]
    assert result["coverage"]["remaining_jars"] == ["B.jar"]
    assert result["coverage"]["indexed_source_jars"] == ["A.jar"]
    assert result["coverage"]["discovered_class_count"] == 1
    assert result["coverage"]["processed_class_count"] == 1
    assert result["coverage"]["progress_percent"] == 50.0


def test_first_plan_uses_selected_quota_without_double_counting_existing_index(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path, storage_budget_multiplier=10)
    orphan = tmp_path / "indice" / "codigo" / "decompilation" / "plan-orphan"
    orphan.mkdir(parents=True)
    (orphan / "old.java").write_bytes(b"legacy-output" * 100)

    before = manager.status("r1")

    assert before["capacity"]["used_bytes"] == 0
    assert before["capacity"]["orphaned_bytes"] > 0
    assert before["capacity"]["physical_used_bytes"] > 0
    assert before["capacity"]["state"] == "tight"

    result = manager.advance(
        "r1",
        approved=True,
        relative_jars=("A.jar",),
        batch_limit=10,
        max_classes=10,
        max_bytes=1024,
    )

    assert result["state"] == "completed"
    assert result["coverage"]["covered_jars"] == ["A.jar"]


def test_old_schema_plan_does_not_block_current_coverage(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with manager.store.connect() as connection:
        now = "2026-08-29T00:00:00+00:00"
        connection.execute(
            """INSERT INTO decompilation_plans
               (plan_id, schema_version, release_id, release_hash, state,
                max_classes, max_bytes, created_at, updated_at)
               VALUES ('old', 1, 'r1', ?, 'pending', 1, 1, ?, ?)""",
            (
                manager.catalog.load_manifest("r1")["release_manifest_sha256"],
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO plan_artifacts
               (plan_id, ordinal, relative_path, artifact_sha256)
               VALUES ('old', 0, 'A.jar', 'old-hash')"""
        )
        connection.commit()

    assert manager.status("r1")["active_plans"] == []


def test_cli_requires_approval_before_loading_workspace(tmp_path: Path) -> None:
    missing_root = tmp_path / "must-not-be-created"

    assert cli_main(
        [
            "--root",
            str(missing_root),
            "advance-erp-code-coverage",
            "r1",
        ]
    ) == 2
    assert not missing_root.exists()


def test_partial_plan_is_blocked_and_never_counted_as_covered(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    result = manager.advance(
        "r1",
        approved=True,
        relative_jars=("A.jar",),
        batch_limit=10,
        max_classes=10,
        max_bytes=1024,
    )
    with manager.store.connect() as connection:
        connection.execute(
            """UPDATE decompilation_plans SET state = 'pending'
               WHERE plan_id = ?""",
            (result["plan_id"],),
        )
        connection.execute(
            """UPDATE decompilation_batches
               SET state = 'partial', last_error = 'fonte ausente'
               WHERE plan_id = ?""",
            (result["plan_id"],),
        )
        connection.commit()

    status = manager.status("r1")

    assert status["covered_jar_count"] == 0
    assert status["indexed_source_jar_count"] == 1
    assert status["blocked_plans"][0]["attention_batches"]
    with pytest.raises(CodeCoverageError, match="exige revisão/retry"):
        manager.advance("r1", approved=True)


def test_completed_plan_without_batches_or_sources_is_rebuilt(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    stale = manager.planner.plan(
        "r1",
        ("A.jar",),
        max_classes=10,
        max_bytes=1024,
    )
    plan_id = stale["plan_id"]
    with manager.store.connect() as connection:
        connection.execute(
            "DELETE FROM batch_members WHERE batch_id IN "
            "(SELECT batch_id FROM decompilation_batches WHERE plan_id = ?)",
            (plan_id,),
        )
        connection.execute(
            "DELETE FROM decompilation_batches WHERE plan_id = ?", (plan_id,)
        )
        connection.execute(
            "UPDATE decompilation_plans SET state = 'completed' WHERE plan_id = ?",
            (plan_id,),
        )
        connection.commit()

    invalid = manager.status("r1")

    assert invalid["covered_jar_count"] == 0
    assert invalid["remaining_jars"] == ["A.jar", "B.jar"]
    assert invalid["indexed_source_jar_count"] == 0

    rebuilt = manager.advance(
        "r1",
        approved=True,
        relative_jars=("A.jar",),
        batch_limit=10,
        max_classes=10,
        max_bytes=1024,
    )

    assert rebuilt["plan_id"] == plan_id
    assert rebuilt["coverage"]["covered_jars"] == ["A.jar"]
    assert rebuilt["coverage"]["indexed_source_jars"] == ["A.jar"]
    assert manager.store.status(plan_id)["batch_count"] > 0


def test_planning_plan_without_batches_resumes_without_rescanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    stale = manager.planner.plan(
        "r1", ("A.jar",), max_classes=10, max_bytes=1024
    )
    plan_id = stale["plan_id"]
    with manager.store.connect() as connection:
        connection.execute(
            "DELETE FROM batch_members WHERE batch_id IN "
            "(SELECT batch_id FROM decompilation_batches WHERE plan_id = ?)",
            (plan_id,),
        )
        connection.execute(
            "DELETE FROM decompilation_batches WHERE plan_id = ?", (plan_id,)
        )
        connection.execute(
            "UPDATE decompilation_plans SET state = 'planning' WHERE plan_id = ?",
            (plan_id,),
        )
        connection.commit()

    def unexpected_scan(*_args, **_kwargs):
        raise AssertionError("classes já inventariadas não devem ser lidas novamente")

    monkeypatch.setattr(manager.planner, "_scan_occurrences", unexpected_scan)
    events: list[dict] = []

    resumed = manager.planner.plan(
        "r1",
        ("A.jar",),
        max_classes=10,
        max_bytes=1024,
        progress=events.append,
    )

    assert resumed["plan_id"] == plan_id
    assert resumed["batch_count"] > 0
    assert events[0] == {
        "phase": "scanning",
        "current": 1,
        "total": 1,
        "resumed": True,
    }
    assert events[-1]["phase"] == "batch_planning"
    assert events[-1]["current"] == events[-1]["total"]


def test_planner_reports_class_scan_and_batch_planning_progress(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    events: list[dict] = []

    manager.planner.plan(
        "r1",
        ("A.jar",),
        max_classes=10,
        max_bytes=1024,
        progress=events.append,
    )

    scan_events = [item for item in events if item["phase"] == "scanning"]
    planning_events = [
        item for item in events if item["phase"] == "batch_planning"
    ]
    assert scan_events[0]["current"] == 0
    assert scan_events[-1]["current"] == scan_events[-1]["total"] == 1
    assert planning_events[0]["current"] == 0
    assert planning_events[-1]["current"] == planning_events[-1]["total"]

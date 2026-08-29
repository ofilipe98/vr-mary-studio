from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import (
    DecompilationBatchError,
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
    DecompilationBatchStore,
)
from vrsoft_extractor.mary.jvm_toolchain import DecompileRequest, DecompileResult


def _jar(path: Path, classes: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
        for name, bytecode in classes.items():
            archive.writestr(name, bytecode)


def _catalog(tmp_path: Path) -> ErpReleaseCatalog:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    _jar(
        source / "A.jar",
        {
            "br/vr/Outer.class": b"outer",
            "br/vr/Outer$Inner.class": b"inner",
            "br/vr/Shared.class": b"same-bytecode",
        },
    )
    _jar(
        source / "B.jar",
        {
            "br/vr/Copy.class": b"same-bytecode",
            "br/vr/Shared.class": b"conflicting-bytecode",
        },
    )
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=2)
    catalog.import_release("r1")
    return catalog


class _FakeAdapter:
    def __init__(self, name: str, status: str = "completed") -> None:
        self.name = name
        self.status = status
        self.requests: list[DecompileRequest] = []

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        self.requests.append(request)
        if self.status == "completed":
            request.output_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(request.input_path) as archive:
                families = {
                    name.removesuffix(".class").split("$", 1)[0]
                    for name in archive.namelist()
                    if name.endswith(".class")
                }
            for index, family in enumerate(sorted(families)):
                output = request.output_dir / f"{family}.java"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(f"class Result{index} {{}}", encoding="utf-8")
        return DecompileResult(
            tool=self.name,
            status=self.status,
            duration_ms=5,
            exit_code=0 if self.status == "completed" else 1,
            output_dir=str(request.output_dir),
            error="" if self.status == "completed" else "controlled failure",
        )


def test_planner_is_deterministic_deduplicates_content_and_keeps_provenance(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    planner = DecompilationBatchPlanner(tmp_path, catalog=catalog)

    first = planner.plan("r1", max_classes=1, max_bytes=1024)
    second = planner.plan("r1", max_classes=1, max_bytes=1024)

    assert first["plan_id"] == second["plan_id"]
    assert first["class_content_count"] == 4
    assert first["batch_count"] == 3
    with DecompilationBatchStore(tmp_path).connect() as connection:
        assert connection.execute("SELECT count(*) FROM class_occurrences").fetchone()[0] == 5
        family_batch = connection.execute(
            """SELECT b.class_count
               FROM decompilation_batches b
               JOIN batch_members m ON m.batch_id = b.batch_id
               JOIN class_occurrences o ON o.occurrence_id = m.occurrence_id
               WHERE o.logical_name = 'br.vr.Outer'"""
        ).fetchone()
        assert family_batch["class_count"] == 2

    reversed_order = planner.plan(
        "r1", ("B.jar", "A.jar"), max_classes=1, max_bytes=1024
    )
    assert reversed_order["plan_id"] == first["plan_id"]


def test_executor_marks_success_and_reuses_completed_content(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", ("A.jar",), max_classes=20
    )
    adapter = _FakeAdapter("vineflower")
    executor = DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(adapter,)
    )

    result = executor.run(plan["plan_id"], limit=1, max_heap_mb=768, timeout_seconds=12)

    assert result["executed"][0]["state"] == "completed"
    assert result["executed"][0]["tool"] == "vineflower"
    assert result["executed"][0]["expected_source_files"] == 2
    assert result["executed"][0]["actual_source_files"] == 2
    assert adapter.requests[0].max_heap_mb == 768
    assert adapter.requests[0].timeout_seconds == 12
    assert adapter.requests[0].input_path.is_file()
    assert (adapter.requests[0].input_path.parent / "attempt.json").is_file()
    with DecompilationBatchStore(tmp_path).connect() as connection:
        states = {
            row[0]
            for row in connection.execute("SELECT state FROM class_contents")
        }
        assert states == {"completed"}


def test_executor_uses_cfr_fallback_after_primary_failure(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", ("A.jar",), max_classes=20
    )
    vineflower = _FakeAdapter("vineflower", "failed")
    cfr = _FakeAdapter("cfr", "completed")

    result = DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(vineflower, cfr)
    ).run(plan["plan_id"])

    execution = result["executed"][0]
    assert execution["state"] == "completed"
    assert execution["tool"] == "cfr"
    assert [item["tool"] for item in execution["attempts"]] == ["vineflower", "cfr"]


def test_executor_refuses_stale_release(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", ("A.jar",), max_classes=20
    )
    _jar(
        tmp_path / "ERP" / "releases" / "r1" / "jars" / "A.jar",
        {"br/vr/Changed.class": b"changed"},
    )

    with pytest.raises(DecompilationBatchError, match="mudaram"):
        DecompilationBatchExecutor(
            tmp_path, catalog=catalog, adapters=(_FakeAdapter("vineflower"),)
        ).run(plan["plan_id"])


def test_retry_requires_failed_or_partial_batch(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", ("A.jar",), max_classes=20
    )
    executor = DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(_FakeAdapter("vineflower"),)
    )
    with DecompilationBatchStore(tmp_path).connect() as connection:
        batch_id = connection.execute(
            "SELECT batch_id FROM decompilation_batches WHERE plan_id = ?",
            (plan["plan_id"],),
        ).fetchone()[0]

    with pytest.raises(DecompilationBatchError, match="falha"):
        executor.retry(batch_id)

    with DecompilationBatchStore(tmp_path).connect() as connection:
        connection.execute(
            "UPDATE decompilation_batches SET state = 'failed' WHERE batch_id = ?",
            (batch_id,),
        )
        connection.commit()
    retried = executor.retry(batch_id)
    assert retried["batches_by_state"] == {"pending": 1}

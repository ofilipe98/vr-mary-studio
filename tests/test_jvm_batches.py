from __future__ import annotations

import os
import threading
import time
import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import (
    DecompilationBatchError,
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
    DecompilationBatchStore,
    _class_family,
    _java_source_candidates,
    _java_source_path_key,
    _missing_java_sources,
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


def _multi_release_catalog(tmp_path: Path) -> ErpReleaseCatalog:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    _jar(
        source / "MR.jar",
        {
            "br/vr/Versioned.class": b"base-outer",
            "br/vr/Versioned$Inner.class": b"base-inner",
            "META-INF/versions/9/br/vr/Versioned.class": b"java9-outer",
            "META-INF/versions/9/br/vr/Versioned$Inner.class": b"java9-inner",
        },
    )
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
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
    assert first["current_batch"]["state"] == "pending"
    assert first["current_batch"]["jar_relative_path"] in {"A.jar", "B.jar"}
    assert first["current_batch"]["batch_id"]
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


def test_class_family_preserves_legal_leading_dollar_names() -> None:
    known = {
        "com.google.gson.internal.$Gson$Preconditions",
        "com.google.gson.internal.$Gson$Types",
        "com.google.gson.internal.$Gson$Types$GenericArrayTypeImpl",
    }

    assert _class_family(
        "com.google.gson.internal.$Gson$Preconditions", known
    ) == "com.google.gson.internal.$Gson$Preconditions"
    assert _class_family(
        "com.google.gson.internal.$Gson$Types$GenericArrayTypeImpl", known
    ) == "com.google.gson.internal.$Gson$Types"
    assert _class_family("br.vr.Outer$Inner", {*known, "br.vr.Outer"}) == "br.vr.Outer"
    assert _class_family("br.vr.Outer$Inner", known) == "br.vr.Outer$Inner"
    assert _class_family(
        "br.vr.Outer$Inner$1", {*known, "br.vr.Outer$Inner"}
    ) == "br.vr.Outer$Inner"
    assert _class_family(
        "br.vr.Outer$Inner$1", {*known, "br.vr.Outer", "br.vr.Outer$Inner"}
    ) == "br.vr.Outer"


def test_class_family_reuses_large_namespace_set_without_iterating_it() -> None:
    class MembershipOnlySet(set[str]):
        def __iter__(self):
            raise AssertionError("o conjunto de nomes não deve ser copiado por classe")

    known = MembershipOnlySet({"br.vr.Outer", "br.vr.Outer$Inner"})

    assert _class_family("br.vr.Outer$Inner", known) == "br.vr.Outer"
    assert "br/vr/Outer.java" in _java_source_candidates(
        "br.vr.Outer$Inner", known
    )


def test_nested_class_accepts_any_decompiler_source_boundary() -> None:
    known = {
        "br.vr.Outer",
        "br.vr.Outer$Inner",
        "br.vr.Outer$Inner$1",
    }
    logical = "br.vr.Outer$Inner$1"

    assert _java_source_candidates(logical, known) == {
        "br/vr/Outer.java",
        "br/vr/Outer.kt",
        "br/vr/Outer$Inner.java",
        "br/vr/Outer$Inner.kt",
        "br/vr/Outer$Inner$1.java",
        "br/vr/Outer$Inner$1.kt",
    }
    assert not _missing_java_sources({logical}, known, {"br/vr/Outer.java"})
    assert not _missing_java_sources({logical}, known, {"br/vr/Outer$Inner.java"})
    assert not _missing_java_sources({logical}, known, {"br/vr/Outer.kt"})
    assert _missing_java_sources({logical}, known, set()) == {"br/vr/Outer.java"}


def test_java_source_path_key_respects_output_filesystem_case_semantics() -> None:
    upper = "COM/ibm/db2/app/Blob.java"
    lower = "com/ibm/db2/app/Blob.java"

    assert _java_source_path_key(upper, case_sensitive=False) == _java_source_path_key(
        lower, case_sensitive=False
    )
    assert _java_source_path_key(upper, case_sensitive=True) != _java_source_path_key(
        lower, case_sensitive=True
    )


@pytest.mark.skipif(os.name != "nt", reason="NTFS output is case-insensitive")
def test_missing_sources_accepts_decompiler_directory_case_on_windows() -> None:
    logical = "COM.ibm.db2.app.Blob"

    assert not _missing_java_sources(
        {logical},
        {logical},
        {"com/ibm/db2/app/Blob.java"},
    )


def test_multi_release_variants_use_isolated_batches_and_normalized_inputs(
    tmp_path: Path,
) -> None:
    catalog = _multi_release_catalog(tmp_path)
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", ("MR.jar",), max_classes=100
    )

    assert plan["schema_version"] == 2
    assert plan["batch_count"] == 2
    with DecompilationBatchStore(tmp_path).connect() as connection:
        batches = connection.execute(
            """SELECT class_version, class_count
               FROM decompilation_batches
               WHERE plan_id = ? ORDER BY ordinal""",
            (plan["plan_id"],),
        ).fetchall()
    assert [(row["class_version"], row["class_count"]) for row in batches] == [
        (0, 2),
        (9, 2),
    ]

    adapter = _FakeAdapter("vineflower")
    result = DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(adapter,)
    ).run(plan["plan_id"], limit=2)

    assert result["plan"]["batches_by_state"] == {"completed": 2}
    assert len(adapter.requests) == 2
    for request in adapter.requests:
        with zipfile.ZipFile(request.input_path) as archive:
            names = set(archive.namelist())
        assert "br/vr/Versioned.class" in names
        assert "br/vr/Versioned$Inner.class" in names
        assert not any(name.startswith("META-INF/versions/") for name in names)
    with DecompilationBatchStore(tmp_path).connect() as connection:
        versions = {
            row[0]
            for row in connection.execute(
                "SELECT processing_schema_version FROM class_contents"
            )
        }
    assert versions == {2}


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
    assert result["executed"][0]["telemetry"]["duration_ms"] == 5
    assert result["executed"][0]["telemetry"]["timed_out"] is False
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


def test_executor_runs_two_batches_in_parallel_with_disjoint_cpu_sets(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", max_classes=1, max_bytes=1024
    )

    class ConcurrentAdapter(_FakeAdapter):
        def __init__(self) -> None:
            super().__init__("vineflower")
            self.lock = threading.Lock()
            self.active = 0
            self.peak = 0

        def decompile(self, request: DecompileRequest) -> DecompileResult:
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                time.sleep(0.1)
                return super().decompile(request)
            finally:
                with self.lock:
                    self.active -= 1

    adapter = ConcurrentAdapter()
    result = DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(adapter,)
    ).run(
        plan["plan_id"],
        limit=2,
        max_cpu_cores=4,
        max_workers=2,
        process_priority="normal",
    )

    assert len(result["executed"]) == 2
    assert {item["state"] for item in result["executed"]} == {"completed"}
    assert result["global_concurrency"] == 2
    assert result["cpu_cores_per_worker"] == 2
    assert adapter.peak == 2
    assert {request.max_cpu_cores for request in adapter.requests} == {2}
    assert {request.cpu_core_offset for request in adapter.requests} == {0, 2}
    assert {request.process_priority for request in adapter.requests} == {"normal"}


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
    blocked = DecompilationBatchStore(tmp_path).status(plan["plan_id"])
    assert blocked["attention_batches"][0]["jar_relative_path"] == "A.jar"
    retried = executor.retry(batch_id)
    assert retried["batches_by_state"] == {"pending": 1}


def test_executor_rejects_plan_from_old_processing_schema(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", ("A.jar",), max_classes=20
    )
    with DecompilationBatchStore(tmp_path).connect() as connection:
        connection.execute(
            "UPDATE decompilation_plans SET schema_version = 1 WHERE plan_id = ?",
            (plan["plan_id"],),
        )
        connection.commit()

    with pytest.raises(DecompilationBatchError, match="schema de processamento antigo"):
        DecompilationBatchExecutor(
            tmp_path, catalog=catalog, adapters=(_FakeAdapter("vineflower"),)
        ).run(plan["plan_id"])

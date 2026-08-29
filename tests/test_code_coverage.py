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


def _manager(tmp_path: Path) -> ErpCodeCoverage:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    _jar(source / "A.jar", {"br/vr/A.class": b"class-a"})
    _jar(source / "B.jar", {"br/vr/B.class": b"class-b"})
    catalog = ErpReleaseCatalog(
        tmp_path,
        expected_jar_count=2,
        storage_budget_multiplier=100_000,
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

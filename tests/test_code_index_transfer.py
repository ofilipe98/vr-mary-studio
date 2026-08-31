from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.code_index import JavaCodeIndex
from vrsoft_extractor.mary.code_index_transfer import (
    PACKAGE_MANIFEST,
    PACKAGE_PAYLOAD,
    CodeIndexTransfer,
    CodeIndexTransferError,
)
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import (
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
)
from vrsoft_extractor.mary.jvm_toolchain import DecompileRequest, DecompileResult


def _jar(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
        archive.writestr("br/vr/Transfer.class", b"transfer-bytecode")


class _Adapter:
    name = "test"

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        source = request.output_dir / "br" / "vr" / "Transfer.java"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "package br.vr; public class Transfer { public void executar() {} }",
            encoding="utf-8",
        )
        return DecompileResult(
            tool=self.name,
            status="completed",
            duration_ms=1,
            exit_code=0,
            output_dir=str(request.output_dir),
        )


def _prepare_index(root: Path, jar_bytes: bytes | None = None) -> tuple[bytes, JavaCodeIndex]:
    jar = root / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
    if jar_bytes is None:
        _jar(jar)
    else:
        jar.parent.mkdir(parents=True, exist_ok=True)
        jar.write_bytes(jar_bytes)
    catalog = ErpReleaseCatalog(root, expected_jar_count=1)
    catalog.import_release("r1")
    return jar.read_bytes(), JavaCodeIndex(root, catalog=catalog)


def test_export_import_round_trip_keeps_release_grounding_without_jars(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    jar_bytes, source_index = _prepare_index(source_root)
    plan = DecompilationBatchPlanner(
        source_root, catalog=source_index.catalog
    ).plan("r1")
    DecompilationBatchExecutor(
        source_root,
        catalog=source_index.catalog,
        adapters=(_Adapter(),),
    ).run(plan["plan_id"])
    source_index.index_plan(plan["plan_id"])
    package = tmp_path / "r1.vridx"

    exported = CodeIndexTransfer(
        source_root, catalog=source_index.catalog, code_index=source_index
    ).export_release("r1", package)

    target_root = tmp_path / "target"
    _prepare_index(target_root, jar_bytes)
    imported = CodeIndexTransfer(target_root).import_package(package)
    target_index = JavaCodeIndex(target_root)
    matches = target_index.search("executar", release_id="r1")

    assert exported["contains_source_jars"] is False
    assert exported["requires_model"] is False
    assert imported["verified"] is True
    assert imported["imported_sources"] == 1
    assert target_index.coverage("r1")["covered_jar_count"] == 1
    assert matches[0]["release_id"] == "r1"
    assert matches[0]["tool"] == "imported"
    assert "ERP release r1" in matches[0]["citation"]

    second = CodeIndexTransfer(target_root).import_package(package)
    assert second["imported_sources"] == 0
    assert second["unchanged_sources"] == 1


def test_import_rejects_tampered_payload_before_database_changes(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    jar_bytes, index = _prepare_index(source_root)
    plan = DecompilationBatchPlanner(source_root, catalog=index.catalog).plan("r1")
    DecompilationBatchExecutor(
        source_root, catalog=index.catalog, adapters=(_Adapter(),)
    ).run(plan["plan_id"])
    index.index_plan(plan["plan_id"])
    package = tmp_path / "valid.vridx"
    CodeIndexTransfer(source_root).export_release("r1", package)

    tampered = tmp_path / "tampered.vridx"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        target.writestr(PACKAGE_MANIFEST, source.read(PACKAGE_MANIFEST))
        target.writestr(PACKAGE_PAYLOAD, source.read(PACKAGE_PAYLOAD) + b"x")
    target_root = tmp_path / "target"
    _prepare_index(target_root, jar_bytes)

    with pytest.raises(CodeIndexTransferError, match="tamanho|SHA-256"):
        CodeIndexTransfer(target_root).import_package(tampered)

    assert JavaCodeIndex(target_root).status("r1")["sources"] == 0

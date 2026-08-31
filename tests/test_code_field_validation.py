from __future__ import annotations

import socket
import zipfile
from pathlib import Path
from unittest.mock import patch

from vrsoft_extractor.mary.code_field_validation import CodeFieldValidator
from vrsoft_extractor.mary.code_index import JavaCodeIndex
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import (
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
)
from vrsoft_extractor.mary.jvm_toolchain import DecompileRequest, DecompileResult


def _jar(path: Path, marker: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
        archive.writestr("br/vr/ReleaseProbe.class", marker)


class _ReleaseAdapter:
    name = "offline-test"

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        with zipfile.ZipFile(request.input_path) as archive:
            marker = archive.read("br/vr/ReleaseProbe.class").decode("ascii")
        source = request.output_dir / "br" / "vr" / "ReleaseProbe.java"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "package br.vr; public class ReleaseProbe { "
            f'public String releaseMarker() {{ return "{marker}"; }} }}',
            encoding="utf-8",
        )
        return DecompileResult(
            tool=self.name,
            status="completed",
            duration_ms=1,
            exit_code=0,
            output_dir=str(request.output_dir),
        )


def _index_release(root: Path, release_id: str, marker: bytes) -> None:
    jar = root / "ERP" / "releases" / release_id / "jars" / "ERP.jar"
    _jar(jar, marker)
    catalog = ErpReleaseCatalog(root, expected_jar_count=1)
    catalog.import_release(release_id)
    plan = DecompilationBatchPlanner(root, catalog=catalog).plan(release_id)
    DecompilationBatchExecutor(
        root, catalog=catalog, adapters=(_ReleaseAdapter(),)
    ).run(plan["plan_id"])
    JavaCodeIndex(root, catalog=catalog).index_plan(plan["plan_id"])


def test_field_validation_proves_two_release_isolation_with_network_blocked(
    tmp_path: Path,
) -> None:
    _index_release(tmp_path, "r1", b"release-one")
    _index_release(tmp_path, "r2", b"release-two")

    with patch.object(
        socket.socket,
        "connect",
        side_effect=AssertionError("network access is forbidden"),
    ):
        result = CodeFieldValidator(tmp_path).validate(
            ["r1", "r2"],
            probe_symbol="releaseMarker",
            require_distinct_hashes=True,
        )

    assert result["ready"] is True
    assert result["release_hashes_distinct"] is True
    assert result["offline_contract"]["requires_network"] is False
    assert result["offline_contract"]["requires_model"] is False
    first, second = result["releases"]
    assert first["probe_source_hashes"] != second["probe_source_hashes"]
    assert all("ERP release r1" in item for item in first["probe_citations"])
    assert all("ERP release r2" in item for item in second["probe_citations"])


def test_two_analyst_workspaces_keep_same_release_id_isolated(tmp_path: Path) -> None:
    analyst_a = tmp_path / "analyst-a"
    analyst_b = tmp_path / "analyst-b"
    _index_release(analyst_a, "current", b"client-a")
    _index_release(analyst_b, "current", b"client-b")

    first = CodeFieldValidator(analyst_a).validate(
        ["current"], probe_symbol="releaseMarker"
    )
    second = CodeFieldValidator(analyst_b).validate(
        ["current"], probe_symbol="releaseMarker"
    )

    assert first["ready"] is True
    assert second["ready"] is True
    assert first["workspace"] != second["workspace"]
    assert (
        first["releases"][0]["release_manifest_sha256"]
        != second["releases"][0]["release_manifest_sha256"]
    )
    assert (
        analyst_a / "indice" / "codigo" / "processing.sqlite"
    ).is_file()
    assert (
        analyst_b / "indice" / "codigo" / "processing.sqlite"
    ).is_file()


def test_field_validation_blocks_partial_coverage(tmp_path: Path) -> None:
    jar = tmp_path / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
    _jar(jar, b"not-indexed")
    ErpReleaseCatalog(tmp_path, expected_jar_count=1).import_release("r1")

    result = CodeFieldValidator(tmp_path).validate(["r1"])

    assert result["ready"] is False
    assert any("cobertura" in item for item in result["blockers"])

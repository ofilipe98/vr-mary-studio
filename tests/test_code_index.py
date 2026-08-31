from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import vrsoft_extractor.mary.code_index as code_index_module
from vrsoft_extractor.mary.classpath import ClasspathAnalyzer
from vrsoft_extractor.mary.code_index import (
    JavaCodeIndex,
    parse_java_source,
    parse_kotlin_source,
)
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import (
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
)
from vrsoft_extractor.mary.jvm_toolchain import DecompileRequest, DecompileResult


def _jar(path: Path, marker: bytes = b"v1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
        archive.writestr("br/vr/Outer.class", marker + b"-outer")
        archive.writestr("br/vr/Outer$Inner.class", marker + b"-inner")
        archive.writestr("br/vr/Shared.class", marker + b"-shared")


class _JavaSourceAdapter:
    name = "vineflower"

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        outer = request.output_dir / "br" / "vr" / "Outer.java"
        shared = request.output_dir / "br" / "vr" / "Shared.java"
        outer.parent.mkdir(parents=True, exist_ok=True)
        outer.write_text(
            """package br.vr;

import java.util.List;

public class Outer extends Base implements Runnable {
    private int total;

    public int calcularTotal(int value) {
        auditoria.registrar(value);
        return new Calculadora().somar(total, value);
    }

    public void run() {}
}
""",
            encoding="utf-8",
        )
        shared.write_text(
            "package br.vr;\npublic record Shared(String value) {}\n",
            encoding="utf-8",
        )
        return DecompileResult(
            tool=self.name,
            status="completed",
            duration_ms=4,
            exit_code=0,
            output_dir=str(request.output_dir),
        )


class _KotlinSourceAdapter:
    name = "vineflower"

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        outer = request.output_dir / "br" / "vr" / "Outer.kt"
        shared = request.output_dir / "br" / "vr" / "Shared.java"
        outer.parent.mkdir(parents=True, exist_ok=True)
        outer.write_text(
            "package br.vr\n\nfun kotlinTotal(): Int = 1\n",
            encoding="utf-8",
        )
        shared.write_text(
            "package br.vr;\npublic record Shared(String value) {}\n",
            encoding="utf-8",
        )
        return DecompileResult(
            tool=self.name,
            status="completed",
            duration_ms=4,
            exit_code=0,
            output_dir=str(request.output_dir),
        )


def _indexed_project(tmp_path: Path) -> tuple[JavaCodeIndex, Path, str]:
    jar = tmp_path / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
    _jar(jar)
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    catalog.import_release("r1")
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", max_classes=20
    )
    DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(_JavaSourceAdapter(),)
    ).run(plan["plan_id"])
    return JavaCodeIndex(tmp_path, catalog=catalog), jar, plan["plan_id"]


def test_parser_extracts_types_methods_fields_and_relations() -> None:
    parsed = parse_java_source(
        """package br.vr;
import java.util.List;
public class Venda extends Base implements Runnable {
  private int total;
  public int calcular(int valor) { return valor; }
}
"""
    )

    assert parsed.qualified_name == "br.vr.Venda"
    assert {item["simple_name"] for item in parsed.symbols} >= {
        "Venda",
        "total",
        "calcular",
    }
    assert not any(
        item["kind"] == "method" and item["simple_name"] == "Venda"
        for item in parse_java_source(
            "class X {\n  void x() {\n    return new Venda();\n  }\n}"
        ).symbols
    )
    assert {(item["kind"], item["target"]) for item in parsed.relations} >= {
        ("import", "java.util.List"),
        ("extends", "Base"),
        ("implements", "Runnable"),
    }


def test_parser_falls_back_when_native_ast_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise code_index_module.JavaAstUnavailable("not installed")

    monkeypatch.setattr(code_index_module, "parse_java_ast", unavailable)
    parsed = code_index_module.parse_java_source(
        "package br.vr;\npublic class Venda { public void salvar() {} }"
    )

    assert parsed.qualified_name == "br.vr.Venda"
    assert parsed.parser_kind == "structural_fallback"


def test_kotlin_parser_preserves_path_identity_and_package() -> None:
    parsed = parse_kotlin_source(
        "package org.springframework.beans.factory\n",
        fallback_qualified=(
            "org.springframework.beans.factory.BeanFactoryExtensionsKt"
        ),
    )

    assert parsed.package_name == "org.springframework.beans.factory"
    assert parsed.primary_type == "BeanFactoryExtensionsKt"
    assert parsed.qualified_name.endswith(".BeanFactoryExtensionsKt")
    assert parsed.parser_kind == "kotlin_structural"


def test_index_accepts_kotlin_output_with_bytecode_provenance(tmp_path: Path) -> None:
    jar = tmp_path / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
    _jar(jar)
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    catalog.import_release("r1")
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", max_classes=20
    )
    execution = DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(_KotlinSourceAdapter(),)
    ).run(plan["plan_id"])
    index = JavaCodeIndex(tmp_path, catalog=catalog)

    result = index.index_plan(plan["plan_id"])
    matches = index.search("kotlinTotal", release_id="r1")

    assert execution["executed"][0]["state"] == "completed"
    assert result["indexed_sources"] == 2
    assert result["errors"] == []
    assert index.status("r1")["parser_kinds"]["kotlin_structural"]["sources"] == 1
    assert matches[0]["qualified_name"] == "br.vr.Outer"
    assert matches[0]["source_relative_path"] == "br/vr/Outer.kt"
    assert matches[0]["logical_names_json"] == '["br.vr.Outer", "br.vr.Outer$Inner"]'


def test_index_is_idempotent_and_search_returns_grounded_citation(
    tmp_path: Path,
) -> None:
    index, _jar_path, plan_id = _indexed_project(tmp_path)

    first = index.index_plan(plan_id)
    second = index.index_plan(plan_id)
    results = index.search("calcularTotal", release_id="r1")
    type_results = index.search("Outer", release_id="r1")

    assert first["indexed_sources"] == 2
    assert first["errors"] == []
    assert second["indexed_sources"] == 0
    assert second["unchanged_sources"] == 2
    assert index.status("r1")["sources"] == 2
    assert index.status("r1")["symbols"] >= 5
    assert index.status("r1")["parser_kinds"]["tree_sitter"]["sources"] == 2
    assert index.status("r1")["relation_kinds"]["calls"] >= 2
    assert index.status("r1")["relation_kinds"]["constructs"] == 1
    assert index.status("r1")["class_versions"] == {"base": 2}
    assert index.status("r1")["jar_count"] == 1
    assert index.status("r1")["jars"] == ["ERP.jar"]
    assert index.coverage("r1")["covered_jar_count"] == 1
    assert index.coverage("r1")["remaining_jars"] == []
    assert results[0]["qualified_name"] == "br.vr.Outer"
    assert results[0]["matched_kind"] == "method"
    assert type_results[0]["matched_kind"] == "class"
    assert results[0]["jar_relative_path"] == "ERP.jar"
    assert results[0]["freshness"] == "fresh"
    assert results[0]["classpath_resolution"] == "unknown"
    assert "ainda não cobre" in results[0]["classpath_warning"]
    assert "calcularTotal" in results[0]["excerpt"]
    assert results[0]["class_version"] == 0
    assert "bytecode base" in results[0]["citation"]
    assert results[0]["line_start"] <= results[0]["matched_line"] <= results[0]["line_end"]
    assert "Código ERP release r1" in results[0]["citation"]
    assert len(results[0]["source_sha256"]) == 64

    ClasspathAnalyzer(index.root, catalog=index.catalog).analyze("r1")
    resolved = index.search("Outer", release_id="r1")[0]
    assert resolved["classpath_resolution"] == "unique"
    assert "classpath unique" in resolved["citation"]

    callers = index.callers("registrar", release_id="r1")
    constructors = index.callers("Calculadora", release_id="r1")
    assert callers[0]["source_symbol"] == "br.vr.Outer.calcularTotal"
    assert callers[0]["resolution"] == "syntactic"
    assert callers[0]["confidence"] == 0.65
    assert "auditoria.registrar" in callers[0]["excerpt"]
    assert constructors[0]["kind"] == "constructs"
    assert constructors[0]["confidence"] == 0.8


def test_identical_jar_reuses_search_index_under_new_release_identity(
    tmp_path: Path,
) -> None:
    index, first_jar, first_plan_id = _indexed_project(tmp_path)
    first = index.index_plan(first_plan_id)
    second_jar = tmp_path / "ERP" / "releases" / "r2" / "jars" / "ERP.jar"
    second_jar.parent.mkdir(parents=True)
    second_jar.write_bytes(first_jar.read_bytes())
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    catalog.import_release("r2")

    second_plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan("r2")
    reused = JavaCodeIndex(tmp_path, catalog=catalog).index_plan(
        second_plan["plan_id"]
    )
    matches = index.search("calcularTotal", release_id="r2")

    assert first["indexed_sources"] == 2
    assert second_plan["state"] == "completed"
    assert second_plan["batch_count"] == 0
    assert reused["reused_sources"] == 2
    assert reused["indexed_sources"] == 0
    assert reused["errors"] == []
    assert index.status("r2")["sources"] == 2
    assert matches[0]["release_id"] == "r2"
    assert matches[0]["tool"] == "reused"
    assert "ERP release r2" in matches[0]["citation"]

    removed = catalog.remove_index("r1", approved=True)
    preserved = index.search("calcularTotal", release_id="r2")
    assert removed["preserved_shared_decompilation_dirs"] == 1
    assert preserved[0]["release_id"] == "r2"


def test_approved_release_removal_purges_scoped_search_and_processing_rows(
    tmp_path: Path,
) -> None:
    index, jar_path, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    removed = index.catalog.remove_index("r1", approved=True)

    assert removed["removed_search_sources"] == 2
    assert removed["removed_processing_plans"] == 1
    assert removed["source_jars_removed"] is False
    assert jar_path.is_file()
    assert index.status("r1")["sources"] == 0
    assert index.store.status() == []


def test_legacy_source_identity_migrates_without_redecompilation(
    tmp_path: Path,
) -> None:
    index, _jar_path, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)
    with index.store.connect() as connection:
        connection.execute(
            """UPDATE code_sources
               SET schema_version = 5, source_key = 'legacy-' || id"""
        )
        connection.commit()

    status = index.status("r1")
    matches = index.search("calcularTotal", release_id="r1")
    with index.store.connect() as connection:
        rows = connection.execute(
            "SELECT schema_version, source_key FROM code_sources ORDER BY id"
        ).fetchall()

    assert status["sources"] == 2
    assert matches[0]["release_id"] == "r1"
    assert {int(row["schema_version"]) for row in rows} == {6}
    assert all(not str(row["source_key"]).startswith("legacy-") for row in rows)


def test_search_warns_when_jar_is_newer_than_index(tmp_path: Path) -> None:
    index, jar_path, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)
    _jar(jar_path, b"v2")

    result = index.search("Outer", release_id="r1")[0]

    assert result["freshness"] == "stale"
    assert "desatualizado" in result["freshness_warning"]

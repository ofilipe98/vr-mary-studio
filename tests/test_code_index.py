from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import vrsoft_extractor.mary.code_index as code_index_module
from vrsoft_extractor.mary.classpath import ClasspathAnalyzer
from vrsoft_extractor.mary.code_index import JavaCodeIndex, parse_java_source
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


def test_search_warns_when_jar_is_newer_than_index(tmp_path: Path) -> None:
    index, jar_path, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)
    _jar(jar_path, b"v2")

    result = index.search("Outer", release_id="r1")[0]

    assert result["freshness"] == "stale"
    assert "desatualizado" in result["freshness_warning"]

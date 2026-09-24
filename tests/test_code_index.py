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
    DecompilationBatchError,
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


def test_structural_parser_ignores_new_expression_as_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise code_index_module.JavaAstUnavailable("not installed")

    monkeypatch.setattr(code_index_module, "parse_java_ast", unavailable)

    parsed = parse_java_source("class X { void x() { return new Venda(); } }")
    multiline_parsed = parse_java_source(
        "class X {\n  void x() {\n    return new Venda();\n  }\n}"
    )

    assert not any(
        symbol["kind"] == "method" and symbol["simple_name"] == "Venda"
        for symbol in parsed.symbols
    )
    assert not any(
        symbol["kind"] == "method" and symbol["simple_name"] == "Venda"
        for symbol in multiline_parsed.symbols
    )


def test_resolve_output_rejects_path_outside_code_index(tmp_path: Path) -> None:
    with pytest.raises(DecompilationBatchError, match="fora do índice permitido"):
        code_index_module._resolve_output(tmp_path, "../outside")


def test_batch_rollback_does_not_double_count_indexed_sources(tmp_path, monkeypatch):
    import sqlite3

    index, _, plan_id = _indexed_project(tmp_path)
    apply = index._apply_indexed_data
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("injected transaction failure")
        return apply(*args, **kwargs)

    monkeypatch.setattr(index, "_apply_indexed_data", fail_second)
    result = index.index_plan(plan_id)
    assert result["errors"] == []
    assert result["indexed_sources"] == 2
    assert result["unchanged_sources"] == 0
    with index.store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM code_sources").fetchone()[0] == 2


def test_reindex_repairs_older_parser_output_without_changing_source_hash(tmp_path):
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)
    with index.store.connect() as connection:
        hashes = [row[0] for row in connection.execute("SELECT source_sha256 FROM code_sources ORDER BY id")]
        connection.execute("UPDATE code_sources SET parser_revision=0")
        connection.execute("DELETE FROM code_symbols")
        connection.commit()
    result = index.index_plan(plan_id)
    assert result["indexed_sources"] == 2
    with index.store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0] > 0
        assert [row[0] for row in connection.execute("SELECT source_sha256 FROM code_sources ORDER BY id")] == hashes
    assert index.index_plan(plan_id)["unchanged_sources"] == 2


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


def test_index_plan_can_index_only_newly_completed_batches(tmp_path: Path) -> None:
    jar = tmp_path / "ERP" / "releases" / "r1" / "jars" / "ERP.jar"
    _jar(jar)
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    catalog.import_release("r1")
    plan = DecompilationBatchPlanner(tmp_path, catalog=catalog).plan(
        "r1", max_classes=1, max_bytes=1024
    )

    class InputAwareAdapter:
        name = "vineflower"

        def decompile(self, request: DecompileRequest) -> DecompileResult:
            request.output_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(request.input_path) as archive:
                families = {
                    name.removesuffix(".class").split("$", 1)[0]
                    for name in archive.namelist()
                    if name.endswith(".class")
                }
            for family in families:
                target = request.output_dir / f"{family}.java"
                target.parent.mkdir(parents=True, exist_ok=True)
                package, _, simple = family.replace("/", ".").rpartition(".")
                target.write_text(
                    f"package {package};\npublic class {simple} {{}}\n",
                    encoding="utf-8",
                )
            return DecompileResult(
                tool=self.name,
                status="completed",
                duration_ms=1,
                exit_code=0,
                output_dir=str(request.output_dir),
            )

    executor = DecompilationBatchExecutor(
        tmp_path, catalog=catalog, adapters=(InputAwareAdapter(),)
    )
    executor.run(plan["plan_id"], limit=1)
    index = JavaCodeIndex(tmp_path, catalog=catalog)
    with index.store.connect() as connection:
        batch_ids = [
            str(row[0])
            for row in connection.execute(
                """SELECT batch_id FROM decompilation_batches
                   WHERE plan_id = ? ORDER BY ordinal""",
                (plan["plan_id"],),
            )
        ]

    first = index.index_plan(plan["plan_id"], batch_ids=(batch_ids[0],))
    with index.store.connect() as connection:
        first_origins = {
            str(row[0]) for row in connection.execute("SELECT DISTINCT batch_id FROM code_sources")
        }
    executor.run(plan["plan_id"], limit=1)
    second = index.index_plan(plan["plan_id"], batch_ids=(batch_ids[1],))
    with index.store.connect() as connection:
        final_origins = {
            str(row[0]) for row in connection.execute("SELECT DISTINCT batch_id FROM code_sources")
        }

    assert first["incremental"] is True
    assert first["completed_batches"] == 1
    assert first_origins == {batch_ids[0]}
    assert second["incremental"] is True
    assert second["completed_batches"] == 1
    assert final_origins == set(batch_ids)


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


def test_resolve_decompiled_reference_exact_method(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    res = index.resolve_decompiled_reference("Outer.calcularTotal", release_id="r1")
    assert res["state"] == "ready"
    assert res["title"] == "Outer"
    assert res["qualified_name"] == "br.vr.Outer"
    assert res["package_name"] == "br.vr"
    assert res["target_symbol"] == "calcularTotal"
    assert res["target_kind"] == "method"
    assert res["raw_target_line"] == 8
    assert res["clean_target_line"] == 8
    assert res["overload_count"] == 1
    assert res["truncated"] is False
    assert "calcularTotal" in res["body"]


def test_resolve_decompiled_reference_fqcn_and_method(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    res = index.resolve_decompiled_reference("br.vr.Outer.calcularTotal", release_id="r1")
    assert res["state"] == "ready"
    assert res["qualified_name"] == "br.vr.Outer"
    assert res["target_symbol"] == "calcularTotal"
    assert res["overload_count"] == 1


def test_resolve_decompiled_reference_fqcn_without_member(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    res = index.resolve_decompiled_reference("br.vr.Outer", release_id="r1")
    assert res["state"] == "ready"
    assert res["qualified_name"] == "br.vr.Outer"
    assert res["target_symbol"] == "Outer"
    assert res["raw_target_line"] == 5
    assert res["overload_count"] == 1


def test_resolve_decompiled_reference_not_found(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    # Unknown member
    res = index.resolve_decompiled_reference("Outer.metodoInexistente", release_id="r1")
    assert res["state"] == "not_found"
    assert "não encontrado" in res["message"]

    # Unknown class
    res2 = index.resolve_decompiled_reference("Inexistente.metodo", release_id="r1")
    assert res2["state"] == "not_found"

    # Invalid ref
    res3 = index.resolve_decompiled_reference("invalido", release_id="r1")
    assert res3["state"] == "not_found"


def test_resolve_decompiled_reference_ambiguous_class(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    # Insert another source with primary_type = 'Outer' but different package/source_key
    with index.store.connect() as connection:
        connection.execute(
            """INSERT INTO code_sources
               (source_key, schema_version, release_id, release_hash,
                jar_relative_path, artifact_sha256, batch_id, class_version,
                tool, output_reference, source_relative_path, source_sha256,
                package_name, primary_type, qualified_name, logical_names_json,
                content_hashes_json, occurrence_count, parser_kind, syntax_error_count,
                symbols_text, body, indexed_at)
               VALUES ('dup-outer', 6, 'r1', 'hash1', 'jars/Other.jar', 'art1', 'b1', 0,
                       'vineflower', 'out', 'other/Outer.java', 'sha1',
                       'other', 'Outer', 'other.Outer', '[]', '[]', 1,
                       'structural_fallback', 0, '', 'class Outer {}', 'now')"""
        )
        connection.commit()

    res = index.resolve_decompiled_reference("Outer.calcularTotal", release_id="r1")
    assert res["state"] == "ambiguous"
    assert len(res["candidates"]) == 2
    assert "ambígua" in res["message"]
    assert res["candidates"][0]["qualified_name"] in ("br.vr.Outer", "other.Outer")


def test_resolve_decompiled_reference_overloaded_method(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    with index.store.connect() as connection:
        source_id = connection.execute(
            "SELECT id FROM code_sources WHERE qualified_name = 'br.vr.Outer'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO code_symbols
               (source_id, kind, simple_name, qualified_name, signature, visibility, line_start)
               VALUES (?, 'method', 'calcularTotal', 'br.vr.Outer.calcularTotal', 'int calcularTotal()', 'public', 20)""",
            (source_id,),
        )
        connection.commit()

    res = index.resolve_decompiled_reference("Outer.calcularTotal", release_id="r1")
    assert res["state"] == "ready"
    assert res["overload_count"] == 2
    assert res["raw_target_line"] == 0
    assert res["clean_target_line"] == 0


def test_resolve_decompiled_reference_clean_banner_line_offset(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    raw_cfr_body = (
        "/*\n"
        " * Decompiled with CFR 0.152.\n"
        " */\n"
        "package br.vr;\n"
        "\n"
        "public class Outer {\n"
        "    public int calcularTotal(int value) {\n"
        "        return value;\n"
        "    }\n"
        "}\n"
    )
    with index.store.connect() as connection:
        source_id = connection.execute(
            "SELECT id FROM code_sources WHERE qualified_name = 'br.vr.Outer'"
        ).fetchone()[0]
        connection.execute(
            "UPDATE code_sources SET body = ?, tool = 'cfr' WHERE id = ?",
            (raw_cfr_body, source_id),
        )
        connection.execute(
            "UPDATE code_symbols SET line_start = 7 WHERE source_id = ? AND simple_name = 'calcularTotal'",
            (source_id,),
        )
        connection.commit()

    res = index.resolve_decompiled_reference("Outer.calcularTotal", release_id="r1")
    assert res["state"] == "ready"
    assert res["clean_status"] == "cleaned"
    assert res["raw_target_line"] == 7
    assert res["clean_target_line"] == 4
    assert res["clean_target_line"] < res["raw_target_line"]
    clean_lines = res["clean_body"].splitlines()
    assert "public int calcularTotal" in clean_lines[res["clean_target_line"] - 1]


def test_resolve_decompiled_reference_clean_line_requires_matching_signature(
    tmp_path: Path,
) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)
    raw_body = (
        "package br.vr;   \n"
        "public class Outer {   \n"
        "    public int calcularTotal(int value) {   \n"
        "        return value;\n"
        "    }\n"
        "}\n"
    )
    with index.store.connect() as connection:
        source_id = connection.execute(
            "SELECT id FROM code_sources WHERE qualified_name = 'br.vr.Outer'"
        ).fetchone()[0]
        connection.execute(
            "UPDATE code_sources SET body = ? WHERE id = ?",
            (raw_body, source_id),
        )
        connection.execute(
            """UPDATE code_symbols SET signature = ?
               WHERE source_id = ? AND simple_name = 'calcularTotal'""",
            ("int calcularTotal(String value)", source_id),
        )
        connection.commit()

    result = index.resolve_decompiled_reference("Outer.calcularTotal", release_id="r1")

    assert result["clean_status"] == "cleaned"
    assert result["clean_target_line"] == 0


def test_resolve_decompiled_reference_max_body_chars_truncation(tmp_path: Path) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)

    res = index.resolve_decompiled_reference(
        "Outer.calcularTotal", release_id="r1", max_body_chars=50
    )
    assert res["state"] == "ready"
    assert res["truncated"] is True
    assert res["raw_target_line"] == 0
    assert res["clean_target_line"] == 0


def test_resolve_decompiled_reference_truncation_without_newline_is_empty(
    tmp_path: Path,
) -> None:
    index, _, plan_id = _indexed_project(tmp_path)
    index.index_plan(plan_id)
    with index.store.connect() as connection:
        connection.execute(
            "UPDATE code_sources SET body = ? WHERE qualified_name = 'br.vr.Outer'",
            ("class Outer { void calcularTotal() {} }",),
        )
        connection.commit()

    result = index.resolve_decompiled_reference(
        "Outer.calcularTotal",
        release_id="r1",
        max_body_chars=12,
    )

    assert result["state"] == "ready"
    assert result["truncated"] is True
    assert result["body"] == ""
    assert result["clean_body"] == ""
    assert result["raw_target_line"] == 0
    assert result["clean_target_line"] == 0

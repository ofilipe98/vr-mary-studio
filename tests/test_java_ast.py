from __future__ import annotations

from vrsoft_extractor.mary.java_ast import parse_java_ast, tree_sitter_available


def test_tree_sitter_extracts_nested_symbols_and_call_edges() -> None:
    assert tree_sitter_available()
    parsed = parse_java_ast(
        """package br.vr;
import java.util.List;
public class Venda extends Base implements Runnable, AutoCloseable {
  private int total, desconto;
  public Venda() {}
  public int calcular(String valor) {
    atualizar();
    servico.salvar(valor);
    return new Calculadora().somar();
  }
}
"""
    )

    assert parsed.qualified_name == "br.vr.Venda"
    assert {(item["kind"], item["simple_name"]) for item in parsed.symbols} >= {
        ("class", "Venda"),
        ("constructor", "Venda"),
        ("method", "calcular"),
        ("field", "total"),
        ("field", "desconto"),
    }
    relations = {
        (item["kind"], item["target"], item["source_symbol"])
        for item in parsed.relations
    }
    assert ("extends", "Base", "br.vr.Venda") in relations
    assert ("implements", "Runnable", "br.vr.Venda") in relations
    assert ("calls", "atualizar", "br.vr.Venda.calcular") in relations
    assert ("calls", "servico.salvar", "br.vr.Venda.calcular") in relations
    assert ("constructs", "Calculadora", "br.vr.Venda.calcular") in relations
    assert parsed.syntax_error_count == 0


def test_tree_sitter_preserves_useful_ast_for_malformed_decompiled_source() -> None:
    parsed = parse_java_ast(
        """package br.vr;
public class Parcial {
  public void executar() {
    int valor = ;
    servico.processar(valor);
  }
}
"""
    )

    assert parsed.qualified_name == "br.vr.Parcial"
    assert any(item["simple_name"] == "executar" for item in parsed.symbols)
    assert parsed.syntax_error_count > 0

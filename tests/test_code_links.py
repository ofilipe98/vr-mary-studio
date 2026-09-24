from __future__ import annotations

from vrsoft_extractor.mary.code_references import (
    parse_java_code_reference,
)
from vrsoft_extractor.mary.frontend.code_links import (
    CODE_REFERENCE_SCHEME,
    encode_code_reference,
    linkify_code_references,
    parse_code_reference,
)


def test_parse_valid_java_code_references():
    ref1 = parse_java_code_reference("NotaSaidaFiscalService.calcularImpostoItem")
    assert ref1 is not None
    assert ref1.raw == "NotaSaidaFiscalService.calcularImpostoItem"
    assert ref1.canonical == "NotaSaidaFiscalService.calcularImpostoItem"
    assert ref1.class_name == "NotaSaidaFiscalService"
    assert ref1.qualified_class_name is None
    assert ref1.member_name == "calcularImpostoItem"

    ref2 = parse_java_code_reference("NotaSaidaFiscalService#calcularImpostoItem")
    assert ref2 is not None
    assert ref2.raw == "NotaSaidaFiscalService#calcularImpostoItem"
    assert ref2.canonical == "NotaSaidaFiscalService.calcularImpostoItem"
    assert ref2.class_name == "NotaSaidaFiscalService"
    assert ref2.qualified_class_name is None
    assert ref2.member_name == "calcularImpostoItem"

    ref3 = parse_java_code_reference("NotaSaidaFiscalService.calcularImpostoItem()")
    assert ref3 is not None
    assert ref3.raw == "NotaSaidaFiscalService.calcularImpostoItem()"
    assert ref3.canonical == "NotaSaidaFiscalService.calcularImpostoItem"
    assert ref3.class_name == "NotaSaidaFiscalService"
    assert ref3.qualified_class_name is None
    assert ref3.member_name == "calcularImpostoItem"

    ref4 = parse_java_code_reference(
        "vratacarejo.service.notasaida.NotaSaidaFiscalService"
    )
    assert ref4 is not None
    assert ref4.raw == "vratacarejo.service.notasaida.NotaSaidaFiscalService"
    assert ref4.canonical == "vratacarejo.service.notasaida.NotaSaidaFiscalService"
    assert ref4.class_name == "NotaSaidaFiscalService"
    assert (
        ref4.qualified_class_name
        == "vratacarejo.service.notasaida.NotaSaidaFiscalService"
    )
    assert ref4.member_name is None

    ref5 = parse_java_code_reference(
        "vratacarejo.service.notasaida.NotaSaidaFiscalService.calcularImpostoItem"
    )
    assert ref5 is not None
    assert (
        ref5.raw
        == "vratacarejo.service.notasaida.NotaSaidaFiscalService.calcularImpostoItem"
    )
    assert (
        ref5.canonical
        == "vratacarejo.service.notasaida.NotaSaidaFiscalService.calcularImpostoItem"
    )
    assert ref5.class_name == "NotaSaidaFiscalService"
    assert (
        ref5.qualified_class_name
        == "vratacarejo.service.notasaida.NotaSaidaFiscalService"
    )
    assert ref5.member_name == "calcularImpostoItem"

    ref6 = parse_java_code_reference(
        "vratacarejo.service.notasaida.NotaSaidaFiscalService#calcularImpostoItem"
    )
    assert ref6 is not None
    assert ref6.class_name == "NotaSaidaFiscalService"
    assert (
        ref6.qualified_class_name
        == "vratacarejo.service.notasaida.NotaSaidaFiscalService"
    )
    assert ref6.member_name == "calcularImpostoItem"
    assert (
        ref6.canonical
        == "vratacarejo.service.notasaida.NotaSaidaFiscalService.calcularImpostoItem"
    )


def test_parse_rejects_invalid_values():
    for raw in (
        "",
        "Erro",
        "null",
        "Exception",
        "Throwable",
        "NotaSaidaFiscalService",
        "oAliquota.getDescricao()",
        "NotaSaidaFiscalService.calcular(x)",
        "NotaSaidaFiscalService.calcular(1, 2)",
        "NotaSaidaFiscalService()",
        "Nota Saida",
        "NotaSaidaFiscalService . calcular",
        "a + b",
        "at com.vr.Service.run(Service.java:10)",
        "com..Service",
        "com.vr.Service..run",
        "https://example.com/Code.java",
    ):
        assert parse_java_code_reference(raw) is None, raw


def test_uri_encoding_round_trip():
    ref = parse_java_code_reference("NotaSaidaFiscalService.calcularImpostoItem")
    assert ref is not None
    encoded = encode_code_reference(ref)
    assert encoded == f"{CODE_REFERENCE_SCHEME}:NotaSaidaFiscalService.calcularImpostoItem"
    parsed = parse_code_reference(encoded)
    assert parsed is not None
    assert parsed.canonical == ref.canonical
    assert parsed.class_name == ref.class_name
    assert parsed.member_name == ref.member_name

    assert parse_code_reference("vr-file:app.py") is None
    assert parse_code_reference("https://example.com") is None
    assert parse_code_reference("") is None


def test_linkify_rewrites_inline_code_and_preserves_fences():
    markdown = (
        "Veja `NotaSaidaFiscalService.calcularImpostoItem` para detalhes.\n\n"
        "```java\n"
        "// `NotaSaidaFiscalService.calcularImpostoItem` inside code block\n"
        "void test() {}\n"
        "```\n\n"
        "Consulte também `NotaSaidaFiscalService#calcularImpostoItem` e `vratacarejo.service.notasaida.NotaSaidaFiscalService`."
    )
    result = linkify_code_references(markdown)
    assert (
        "[NotaSaidaFiscalService.calcularImpostoItem](vr-code:NotaSaidaFiscalService.calcularImpostoItem)"
        in result
    )
    assert (
        "[NotaSaidaFiscalService#calcularImpostoItem](vr-code:NotaSaidaFiscalService.calcularImpostoItem)"
        in result
    )
    assert (
        "[vratacarejo.service.notasaida.NotaSaidaFiscalService](vr-code:vratacarejo.service.notasaida.NotaSaidaFiscalService)"
        in result
    )
    assert (
        "```java\n// `NotaSaidaFiscalService.calcularImpostoItem` inside code block\nvoid test() {}\n```"
        in result
    )


def test_linkify_preserves_existing_markdown_links_and_idempotence():
    markdown = (
        "Já linkado: [`NotaSaidaFiscalService.calcularImpostoItem`](https://example.com) "
        "e texto puro `NotaSaidaFiscalService.calcularImpostoItem`."
    )
    once = linkify_code_references(markdown)
    assert "[`NotaSaidaFiscalService.calcularImpostoItem`](https://example.com)" in once
    assert (
        "[NotaSaidaFiscalService.calcularImpostoItem](vr-code:NotaSaidaFiscalService.calcularImpostoItem)"
        in once
    )
    twice = linkify_code_references(once)
    assert twice == once


def test_markdown_for_display_coexistence_with_file_links():
    from vrsoft_extractor.mary.frontend.bridges.presentation import (
        markdown_for_display,
    )

    markdown = (
        "Veja `mary/frontend/file_links.py:12` e o método `NotaSaidaFiscalService.calcularImpostoItem`.\n\n"
        "Também `vratacarejo.service.notasaida.NotaSaidaFiscalService`.\n\n"
        "```python\n"
        "ref = `NotaSaidaFiscalService.calcularImpostoItem`\n"
        "```\n"
    )
    result = markdown_for_display(markdown)
    assert "[file_links.py · L12](vr-file:mary/frontend/file_links.py#L12)" in result
    assert (
        "[NotaSaidaFiscalService.calcularImpostoItem](vr-code:NotaSaidaFiscalService.calcularImpostoItem)"
        in result
    )
    assert (
        "[vratacarejo.service.notasaida.NotaSaidaFiscalService](vr-code:vratacarejo.service.notasaida.NotaSaidaFiscalService)"
        in result
    )
    assert "ref = `NotaSaidaFiscalService.calcularImpostoItem`" in result

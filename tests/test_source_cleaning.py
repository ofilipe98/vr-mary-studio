"""Clean reading view is deterministic, presentation-only and safe."""

from vrsoft_extractor.mary.source_cleaning import clean_decompiled_source


def _clean(body: str, *, path: str = "br/vr/App.java", tool: str = "vineflower"):
    return clean_decompiled_source(body, source_relative_path=path, tool=tool)


def test_cfr_initial_banner_is_removed():
    body = (
        "/*\n"
        " * Decompiled with CFR 0.152\n"
        " */\n"
        "package br.vr;\n"
        "\n"
        "public class App {}\n"
    )
    result = _clean(body, tool="cfr")
    assert result.available is True
    assert result.status == "cleaned"
    assert "Decompiled with CFR" not in result.body
    assert result.body.startswith("package br.vr;")
    assert "public class App {}" in result.body
    assert (
        result.note
        == "Visualização limpa gerada sem alterar identificadores, literais ou lógica."
    )


def test_vineflower_initial_line_banner_sequence_is_removed():
    body = (
        "// Decompiled by Vineflower\n"
        "// fixture build 42\n"
        "package br.vr;\n"
        "\n"
        "public class App {}\n"
    )
    result = _clean(body, tool="vineflower")
    assert result.status == "cleaned"
    assert "Decompiled" not in result.body
    assert "fixture build 42" not in result.body
    assert result.body.startswith("package br.vr;")


def test_legitimate_initial_comment_without_markers_is_preserved():
    body = "// Licensed under the Apache License.\npackage br.vr;\n\npublic class App {}\n"
    result = _clean(body, tool="cfr")
    assert result.status == "unchanged"
    assert result.body.splitlines()[0] == "// Licensed under the Apache License."


def test_initial_comment_missing_tool_marker_is_preserved():
    body = "// Decompiled output is provided as-is.\npackage br.vr;\n"
    result = _clean(body, tool="cfr")
    assert "// Decompiled output is provided as-is." in result.body


def test_initial_comment_missing_decompiled_marker_is_preserved():
    body = "// CFR 0.152 output\npackage br.vr;\n"
    result = _clean(body, tool="cfr")
    assert "// CFR 0.152 output" in result.body


def test_initial_comment_for_other_tool_is_preserved():
    body = "// Decompiled by Vineflower\npackage br.vr;\n"
    result = _clean(body, tool="cfr")
    assert "// Decompiled by Vineflower" in result.body


def test_later_comment_containing_decompiled_is_preserved():
    body = (
        "package br.vr;\n"
        "\n"
        "// Decompiled with CFR 0.152\n"
        "public class App {}\n"
    )
    result = _clean(body, tool="cfr")
    assert result.status == "unchanged"
    assert "// Decompiled with CFR 0.152" in result.body


def test_trailing_whitespace_outside_strings_and_comments_is_removed():
    body = "package br.vr;   \npublic class App { \t\n}\n"
    result = _clean(body)
    assert result.status == "cleaned"
    assert result.body == "package br.vr;\npublic class App {\n}\n"


def test_consecutive_external_blank_lines_are_reduced():
    body = "\n\npackage br.vr;\n\n\n\npublic class App {}\n\n\n"
    result = _clean(body)
    assert result.status == "cleaned"
    assert result.body == "package br.vr;\n\npublic class App {}\n"


def test_string_literal_content_is_preserved():
    body = 'class App {\n  String s = "a // b /* c */ d  \\" e";   \n}\n'
    result = _clean(body)
    assert result.status == "cleaned"
    assert 'String s = "a // b /* c */ d  \\" e";' in result.body
    assert 'd  \\" e"' in result.body


def test_char_literal_content_is_preserved():
    body = "class App {\n  char q = '\\'';\n  char sp = ' ';\n}\n"
    result = _clean(body)
    assert result.status == "unchanged"
    assert "char q = '\\'';" in result.body
    assert "char sp = ' ';" in result.body


def test_text_block_content_is_preserved():
    body = 'class App {\n  String s = """\n  raw  // text\n\n  end """;\n}\n'
    result = _clean(body)
    assert result.status == "unchanged"
    assert result.body == body


def test_line_comment_content_is_preserved():
    body = "class App {}\n// keep trailing spaces inside comment   \n"
    result = _clean(body)
    assert result.status == "unchanged"
    assert "// keep trailing spaces inside comment   " in result.body


def test_block_comment_content_is_preserved():
    body = "class App {}\n/* block   \n   comment  */\n"
    result = _clean(body)
    assert result.status == "unchanged"
    assert "/* block   " in result.body
    assert "   comment  */" in result.body


def test_unterminated_string_returns_fallback_without_changes():
    body = 'class App {\n  String s = "never closed;\n}\n'
    result = _clean(body)
    assert result.available is True
    assert result.status == "fallback"
    assert result.body == body
    assert (
        result.note
        == "A estrutura léxica não pôde ser validada; exibindo o descompilado original."
    )


def test_unterminated_block_comment_returns_fallback_without_changes():
    body = "class App {}\n/* never closed\n"
    result = _clean(body)
    assert result.status == "fallback"
    assert result.body == body


def test_unterminated_text_block_returns_fallback_without_changes():
    body = 'class App {\n  String s = """never closed\n}\n'
    result = _clean(body)
    assert result.status == "fallback"
    assert result.body == body


def test_non_java_source_is_unsupported_without_changes():
    body = "package br.vr\n\nfun main() {}   \n"
    result = clean_decompiled_source(
        body, source_relative_path="br/vr/App.kt", tool="vineflower"
    )
    assert result.available is False
    assert result.status == "unsupported"
    assert result.body == body
    assert result.note == "Limpeza automática disponível apenas para fontes Java."


def test_already_clean_java_source_is_unchanged():
    body = "package br.vr;\n\npublic class App {}\n"
    result = _clean(body)
    assert result.available is True
    assert result.status == "unchanged"
    assert result.body == body
    assert result.note == "O descompilado já está no formato seguro de leitura."


def test_cleaning_is_idempotent():
    body = (
        "\ufeff// Decompiled by Vineflower\n"
        "package br.vr;   \n"
        "\n"
        "\n"
        "public class App {\n"
        '  String s = "a  b";\n'
        "  \n"
        "}\n\n\n"
    )
    first = _clean(body)
    assert first.status == "cleaned"
    second = _clean(first.body)
    assert second.body == first.body
    assert second.status == "unchanged"

"""Behavior checks for inline-code file references, mirroring t3code."""
from vrsoft_extractor.mary.frontend.file_links import (
    build_parent_suffixes,
    encode_file_reference,
    file_link_label,
    linkify_file_references,
    parse_file_reference,
    resolve_inline_code_file_link,
    resolve_markdown_file_link,
)


def test_accepts_paths_and_line_suffixes():
    cases = {
        "mary/frontend/text_rendering.py": ("mary/frontend/text_rendering.py", None, None),
        "mary/frontend/text_rendering.py:240": ("mary/frontend/text_rendering.py", 240, None),
        "text_rendering.py:240": ("text_rendering.py", 240, None),
        "App.qml:10:5": ("App.qml", 10, 5),
        "Makefile:12": ("Makefile", 12, None),
        "src/main.py#L7": ("src/main.py", 7, None),
        "../tests/test_apps_catalog_bridge.py": ("../tests/test_apps_catalog_bridge.py", None, None),
        r"C:\Codex\VRStudio\mary\frontend\chat.py:12": ("C:/Codex/VRStudio/mary/frontend/chat.py", 12, None),
        "file:///C:/Codex/VRStudio/chat.py": ("C:/Codex/VRStudio/chat.py", None, None),
    }
    for raw, expected in cases.items():
        meta = resolve_inline_code_file_link(raw)
        assert meta is not None, raw
        assert (meta.path, meta.line, meta.column) == expected


def test_rejects_identifiers_commands_and_ambiguous_values():
    for raw in (
        "",
        "calcularImpostoItem",
        "oAliquota.getDescricao()",
        "oTIPO_SAIDA_VENDA",
        "vr_read",
        "AGENTS.md",
        "main.py",
        "README:3",
        "git diff --stat",
        "git status",
        "-o",
        "*.py",
        "**/code_retrieval.py",
        "https://example.com/foo.py",
        "example.com/foo.py",
        "src/components/",
        "HEAD~1",
        "main..feature",
        "localhost:8080",
        "text with spaces/file.py",
    ):
        assert resolve_inline_code_file_link(raw) is None, raw


def test_labels_disambiguate_duplicate_basenames():
    paths = ["apps/web/src/index.ts", "packages/api/src/index.ts", "apps/web/src/app.py"]
    suffixes = build_parent_suffixes(paths)
    assert suffixes["apps/web/src/index.ts"] == "web/src"
    assert suffixes["packages/api/src/index.ts"] == "api/src"
    assert suffixes["apps/web/src/app.py"] == ""
    meta = resolve_inline_code_file_link("apps/web/src/index.ts:4")
    assert file_link_label(meta, suffixes[meta.path]) == "index.ts · web/src · L4"


def test_reference_encoding_round_trips_positions():
    meta = resolve_inline_code_file_link(r"C:\Codex\VRStudio\app.py:10:3")
    assert meta is not None and meta.line == 10 and meta.column == 3
    encoded = encode_file_reference(meta)
    assert encoded == "vr-file:C:/Codex/VRStudio/app.py#L10:C3"
    assert parse_file_reference(encoded) == ("C:/Codex/VRStudio/app.py", 10, 3)
    assert parse_file_reference("https://example.com") is None


def test_linkify_rewrites_only_inline_code_paths():
    markdown = (
        "O método `calcularImpostoItem` fica em `mary/retrieval/code_retrieval.py:412`.\n\n"
        "```python\npath = `not-code`\n```\n\n"
        "Veja `Makefile:12` por último."
    )
    result = linkify_file_references(markdown)
    assert "`calcularImpostoItem`" in result
    assert "`Makefile:12`" not in result
    assert "[code_retrieval.py · L412](vr-file:mary/retrieval/code_retrieval.py#L412)" in result
    assert "[Makefile · L12](vr-file:Makefile#L12)" in result
    assert "```python\npath = `not-code`\n```" in result
    assert "path = `not-code`" in result


def test_linkify_is_idempotent_and_skips_link_labels():
    markdown = "Arquivo `src/app.py` e [`src/app.py`](https://example.com)."
    once = linkify_file_references(markdown)
    assert "[app.py](vr-file:src/app.py)" in once
    assert "[`src/app.py`](https://example.com)" in once
    assert linkify_file_references(once) == once


def test_resolve_markdown_file_link_handles_file_urls():
    meta = resolve_markdown_file_link("file:///C:/Codex/VRStudio/chat.py#L12C3")
    assert meta is not None
    assert (meta.path, meta.line, meta.column) == ("C:/Codex/VRStudio/chat.py", 12, 3)
    assert resolve_markdown_file_link("https://example.com/chat.py") is None
    assert resolve_markdown_file_link("#secao") is None


def test_markdown_for_display_linkifies_and_preserves_fences():
    from vrsoft_extractor.mary.frontend.bridges.presentation import markdown_for_display

    markdown = (
        "Ver `mary/frontend/file_links.py:12` e o método `calcularImpostoItem`.\n\n"
        "```python\npath = `x.py`\n```\n"
    )
    result = markdown_for_display(markdown)
    assert "[file_links.py · L12](vr-file:mary/frontend/file_links.py#L12)" in result
    assert "`calcularImpostoItem`" in result
    assert "path = `x.py`" in result

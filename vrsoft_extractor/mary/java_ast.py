"""Tolerant Java AST extraction for decompiled ERP sources."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Iterator

try:  # The structural parser remains available for source/dev fallback.
    import tree_sitter_java
    from tree_sitter import Language, Node, Parser
except ImportError:  # pragma: no cover - exercised through the public fallback.
    tree_sitter_java = None
    Language = Node = Parser = None  # type: ignore[assignment]


TYPE_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "interface",
}


class JavaAstUnavailable(RuntimeError):
    """Raised when the optional native parser cannot be used."""


@dataclass(frozen=True)
class JavaAstParse:
    package_name: str
    primary_type: str
    qualified_name: str
    symbols: tuple[dict[str, Any], ...]
    relations: tuple[dict[str, Any], ...]
    syntax_error_count: int


def tree_sitter_available() -> bool:
    return tree_sitter_java is not None and Language is not None and Parser is not None


_thread_local = threading.local()


def _parser() -> Any:
    if not tree_sitter_available():
        raise JavaAstUnavailable("Tree-sitter Java não está instalado.")
    parser = getattr(_thread_local, "parser", None)
    if parser is None:
        parser = Parser(Language(tree_sitter_java.language()))
        _thread_local.parser = parser
    return parser


def parse_java_ast(body: str, *, fallback_qualified: str = "") -> JavaAstParse:
    """Parse useful declarations and syntactic call edges, even from imperfect Java."""

    parser = _parser()
    source = body.encode("utf-8")
    root = parser.parse(source).root_node
    package_name = _package_name(root, source)
    symbols: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    primary_type = ""

    def visit(node: Any, owners: tuple[str, ...], callable_symbol: str) -> None:
        nonlocal primary_type
        node_type = str(node.type)
        current_owners = owners
        current_callable = callable_symbol

        if node_type == "import_declaration":
            value = _compact(_text(source, node))
            static = bool(re.match(r"^import\s+static\s+", value))
            target = re.sub(r"^import\s+(?:static\s+)?|;$", "", value).strip()
            if target:
                relations.append(
                    _relation(
                        "static_import" if static else "import",
                        target,
                        "",
                        node.start_point.row + 1,
                        0.95,
                    )
                )

        elif node_type in TYPE_KINDS:
            name_node = node.child_by_field_name("name")
            name = _text(source, name_node)
            if name:
                if not primary_type and not owners:
                    primary_type = name
                qualified = ".".join(filter(None, (package_name, *owners, name)))
                symbols.append(
                    _symbol(
                        TYPE_KINDS[node_type],
                        name,
                        qualified,
                        _declaration_signature(node, source),
                        _visibility(node, source),
                        node.start_point.row + 1,
                    )
                )
                _type_relations(node, source, qualified, relations)
                current_owners = (*owners, name)

        elif node_type in {"method_declaration", "constructor_declaration"}:
            name_node = node.child_by_field_name("name")
            name = _text(source, name_node)
            owner = ".".join(filter(None, (package_name, *owners)))
            qualified = f"{owner}.{name}" if owner else name
            kind = "constructor" if node_type == "constructor_declaration" else "method"
            symbols.append(
                _symbol(
                    kind,
                    name,
                    qualified,
                    _declaration_signature(node, source),
                    _visibility(node, source),
                    node.start_point.row + 1,
                )
            )
            current_callable = qualified

        elif node_type == "field_declaration":
            owner = ".".join(filter(None, (package_name, *owners)))
            for child in node.named_children:
                if child.type != "variable_declarator":
                    continue
                name = _text(source, child.child_by_field_name("name"))
                if name:
                    symbols.append(
                        _symbol(
                            "field",
                            name,
                            f"{owner}.{name}" if owner else name,
                            _compact(_text(source, node)),
                            _visibility(node, source),
                            child.start_point.row + 1,
                        )
                    )

        elif node_type == "method_invocation" and callable_symbol:
            name = _text(source, node.child_by_field_name("name"))
            receiver = _compact(_text(source, node.child_by_field_name("object")))
            target = f"{receiver}.{name}" if receiver and name else name
            if target:
                relations.append(
                    _relation(
                        "calls",
                        _bounded(target),
                        callable_symbol,
                        node.start_point.row + 1,
                        0.65,
                    )
                )

        elif node_type == "object_creation_expression" and callable_symbol:
            target = _compact(_text(source, node.child_by_field_name("type")))
            if target:
                relations.append(
                    _relation(
                        "constructs",
                        _bounded(target),
                        callable_symbol,
                        node.start_point.row + 1,
                        0.8,
                    )
                )

        for child in node.named_children:
            visit(child, current_owners, current_callable)

    visit(root, (), "")
    if not primary_type and fallback_qualified:
        primary_type = fallback_qualified.rsplit(".", 1)[-1]
    qualified_name = (
        f"{package_name}.{primary_type}"
        if package_name and primary_type
        else fallback_qualified or primary_type
    )
    return JavaAstParse(
        package_name=package_name,
        primary_type=primary_type,
        qualified_name=qualified_name,
        symbols=tuple(_unique(symbols)),
        relations=tuple(_unique(relations)),
        syntax_error_count=sum(
            1 for node in _walk(root) if bool(node.is_error) or bool(node.is_missing)
        ),
    )


def _package_name(root: Any, source: bytes) -> str:
    for child in root.named_children:
        if child.type == "package_declaration":
            value = _compact(_text(source, child))
            return re.sub(r"^package\s+|;$", "", value).strip()
    return ""


def _type_relations(
    node: Any,
    source: bytes,
    source_symbol: str,
    relations: list[dict[str, Any]],
) -> None:
    for child in node.named_children:
        if child.type not in {"superclass", "super_interfaces", "extends_interfaces"}:
            continue
        raw = _compact(_text(source, child))
        if child.type == "superclass":
            kind, raw = "extends", re.sub(r"^extends\s+", "", raw)
        elif child.type == "extends_interfaces":
            kind, raw = "extends", re.sub(r"^extends\s+", "", raw)
        else:
            kind, raw = "implements", re.sub(r"^implements\s+", "", raw)
        for target in _split_type_list(raw):
            relations.append(
                _relation(kind, target, source_symbol, child.start_point.row + 1, 0.9)
            )


def _declaration_signature(node: Any, source: bytes) -> str:
    body_node = node.child_by_field_name("body")
    end = body_node.start_byte if body_node is not None else node.end_byte
    return _compact(source[node.start_byte:end].decode("utf-8", errors="replace").rstrip("{;"))


def _visibility(node: Any, source: bytes) -> str:
    modifiers = next((child for child in node.named_children if child.type == "modifiers"), None)
    value = _text(source, modifiers)
    for visibility in ("public", "protected", "private"):
        if re.search(rf"\b{visibility}\b", value):
            return visibility
    return "package"


def _symbol(
    kind: str,
    simple_name: str,
    qualified_name: str,
    signature: str,
    visibility: str,
    line_start: int,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "simple_name": simple_name,
        "qualified_name": qualified_name,
        "signature": signature,
        "visibility": visibility,
        "line_start": line_start,
    }


def _relation(
    kind: str,
    target: str,
    source_symbol: str,
    line_start: int,
    confidence: float,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "target": target,
        "source_symbol": source_symbol,
        "confidence": confidence,
        "line_start": line_start,
    }


def _text(source: bytes, node: Any) -> str:
    if node is None:
        return ""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _bounded(value: str, limit: int = 250) -> str:
    text = _compact(value)
    return text[:limit]


def _split_type_list(raw: str) -> list[str]:
    depth = 0
    start = 0
    result = []
    for index, char in enumerate(raw):
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            result.append(raw[start:index].strip())
            start = index + 1
    result.append(raw[start:].strip())
    return [item for item in result if item]


def _unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, Any], ...]] = set()
    unique_items: list[dict[str, Any]] = []
    for item in items:
        key = tuple(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(item)
    return unique_items


def _walk(node: Any) -> Iterator[Any]:
    yield node
    for child in node.children:
        yield from _walk(child)

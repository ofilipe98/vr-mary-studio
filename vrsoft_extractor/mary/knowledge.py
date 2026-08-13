from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from .search import normalize_search_text


MAX_CHUNK_CHARS = 2200
MIN_CHUNK_CHARS = 120


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_key: str
    heading: str
    content: str
    content_type: str
    entities: dict[str, tuple[str, ...]]
    content_hash: str


PROCESS_MARKERS = (
    "como ",
    "passo ",
    "procedimento",
    "configur",
    "acesse",
    "clique",
    "selecione",
    "cadastre",
    "preencha",
)
FUNCTIONAL_MARKERS = (
    "para que serve",
    "como funciona",
    "funcionalidade",
    "objetivo",
    "permite ",
    "utilizado para",
    "responsavel por",
)
TECHNICAL_MARKERS = (
    "tabela",
    "coluna",
    "campo",
    "schema",
    "foreign key",
    "chave estrangeira",
    "trigger",
    "function",
    "select ",
    "update ",
    "insert ",
    "delete ",
)
TROUBLESHOOTING_MARKERS = (
    "erro",
    "falha",
    "rejeicao",
    "nao foi possivel",
    "solucao",
    "corrigir",
)


def split_knowledge_document(
    title: str,
    markdown: str,
    ocr_text: str = "",
    *,
    source: str = "",
) -> list[KnowledgeChunk]:
    """Split one source document into stable, independently searchable chunks."""
    body = _strip_frontmatter(str(markdown or "")).strip()
    if ocr_text.strip():
        body = (body + "\n\n## Texto extraído das imagens\n\n" + ocr_text.strip()).strip()
    if not body:
        return []
    sections = _markdown_sections(title, body)
    chunks: list[KnowledgeChunk] = []
    ordinal = 0
    for heading, section in sections:
        for part in _split_long_section(section):
            cleaned = part.strip()
            if not cleaned:
                continue
            ordinal += 1
            content_type = classify_content_type(
                f"{heading}\n{cleaned}", source=source
            )
            entities = extract_knowledge_entities(f"{heading}\n{cleaned}")
            digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
            chunks.append(
                KnowledgeChunk(
                    chunk_key=f"{ordinal:05d}-{digest[:12]}",
                    heading=heading.strip() or title.strip() or "Documento",
                    content=cleaned,
                    content_type=content_type,
                    entities=entities,
                    content_hash=digest,
                )
            )
    return chunks


def classify_content_type(text: str, *, source: str = "") -> str:
    normalized = normalize_search_text(text)
    scores = {
        "functional": sum(marker in normalized for marker in FUNCTIONAL_MARKERS),
        "process": sum(marker in normalized for marker in PROCESS_MARKERS),
        "technical_schema": sum(
            marker in normalized for marker in TECHNICAL_MARKERS
        ),
        "troubleshooting": sum(
            marker in normalized for marker in TROUBLESHOOTING_MARKERS
        ),
    }
    if source == "schema":
        scores["technical_schema"] += 5
    elif source == "kb":
        scores["process"] += 1
    elif source == "wiki":
        scores["functional"] += 1
    leader, value = max(scores.items(), key=lambda item: item[1])
    tied = [name for name, score in scores.items() if score == value and score > 0]
    return "mixed" if len(tied) > 1 else leader if value > 0 else "reference"


def extract_knowledge_entities(text: str) -> dict[str, tuple[str, ...]]:
    raw = str(text or "")
    normalized = normalize_search_text(raw)
    tables = set(
        match.group(0).casefold()
        for match in re.finditer(
            r"\b(?:[a-z][a-z0-9_]*\.)?[a-z][a-z0-9_]{2,}\b",
            raw,
            flags=re.I,
        )
        if "_" in match.group(0) or "." in match.group(0)
    )
    fields = set(
        match.group(0).casefold()
        for match in re.finditer(r"\bid_[a-z0-9_]+\b", raw, flags=re.I)
    )
    functions = set(
        match.group(1).casefold()
        for match in re.finditer(
            r"\b(?:funcao|função|function|trigger)\s+[`\"']?([a-z0-9_.]+)",
            raw,
            flags=re.I,
        )
        if match.group(1).casefold() not in {"a", "da", "de", "do", "e", "para"}
    )
    errors = set(
        match.group(0).strip()
        for match in re.finditer(
            r"\b(?:erro|rejeicao|rejeição|falha)\s+[a-z0-9_. -]{2,80}",
            raw,
            flags=re.I,
        )
    )
    routines = set()
    for marker in ("venda", "estoque", "nota fiscal", "tef", "cadastro", "importacao"):
        if marker in normalized:
            routines.add(marker)
    numbers = set(re.findall(r"\b\d{2,}\b", raw))
    return {
        "tables": tuple(sorted(tables)[:40]),
        "fields": tuple(sorted(fields)[:40]),
        "functions": tuple(sorted(functions)[:30]),
        "errors": tuple(sorted(errors)[:12]),
        "routines": tuple(sorted(routines)),
        "numbers": tuple(sorted(numbers)),
    }


def normalized_fact_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in normalize_search_text(value).split()
        if len(token) >= 3
    )


def token_similarity(left: str, right: str) -> float:
    first = normalized_fact_tokens(left)
    second = normalized_fact_tokens(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _strip_frontmatter(value: str) -> str:
    return re.sub(r"\A---\s*.*?\s*---\s*", "", value, flags=re.DOTALL)


def _markdown_sections(title: str, body: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    heading = title.strip() or "Documento"
    buffer: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^#{1,4}\s+(.+?)\s*$", line)
        if match:
            content = "\n".join(buffer).strip()
            if content:
                result.append((heading, content))
            heading = re.sub(r"[`*_]", "", match.group(1)).strip()
            buffer = []
        else:
            buffer.append(line)
    content = "\n".join(buffer).strip()
    if content:
        result.append((heading, content))
    return result or [(heading, body)]


def _split_long_section(value: str) -> Iterable[str]:
    if len(value) <= MAX_CHUNK_CHARS:
        yield value
        return
    paragraphs = re.split(r"\n\s*\n", value)
    buffer: list[str] = []
    size = 0
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > MAX_CHUNK_CHARS:
            if buffer:
                yield "\n\n".join(buffer)
                buffer, size = [], 0
            for start in range(0, len(paragraph), MAX_CHUNK_CHARS):
                yield paragraph[start : start + MAX_CHUNK_CHARS]
            continue
        projected = size + len(paragraph) + (2 if buffer else 0)
        if buffer and projected > MAX_CHUNK_CHARS:
            yield "\n\n".join(buffer)
            buffer, size = [], 0
        buffer.append(paragraph)
        size += len(paragraph) + (2 if size else 0)
    if buffer:
        yield "\n\n".join(buffer)

from __future__ import annotations
import hashlib
import json
import logging
import re
import sqlite3
from typing import Any
from ..search import (
    infer_search_module,
    matched_search_terms,
    minimum_term_matches,
    normalize_search_text,
    search_terms,
    term_coverage,
)

REVIEW_MODULES = {
    "Fiscal",
    "ADM_FIN_ESTOQUE",
    "PDV",
    "Multimodulo",
    "Revisar",
}


REVIEW_ACTIONS = {"approve", "keep", "defer", "reopen"}


LOGGER = logging.getLogger(__name__)


def _default_source_origin(source: str) -> str:
    return {
        "wiki": "vrwiki",
        "kb": "movidesk",
        "schema": "local",
    }.get(str(source or "").strip().casefold(), str(source or "").strip().casefold())


def _escape_like(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _review_reasons(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(reason).strip() for reason in parsed if str(reason).strip()]


def _review_signature(suggested_module: str, reasons: list[str]) -> str:
    payload = json.dumps(
        {
            "module": suggested_module,
            "reasons": sorted({reason.casefold().strip() for reason in reasons}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (\
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_origin TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    module TEXT NOT NULL,
    classification_confidence REAL NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'pending',
    status TEXT NOT NULL DEFAULT 'active',
    category TEXT NOT NULL DEFAULT '',
    product TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL,
    revision TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    markdown TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    assets_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(source, source_id)
);

-- Track writes from every connection, including migrations and direct SQL.
-- Conversation and runtime-event writes do not invalidate retrieval signatures.
CREATE TABLE IF NOT EXISTS knowledge_revision (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    revision INTEGER NOT NULL
);
INSERT OR IGNORE INTO knowledge_revision VALUES(1, 0);
CREATE TRIGGER IF NOT EXISTS knowledge_revision_insert AFTER INSERT ON documents BEGIN
    UPDATE knowledge_revision SET revision=revision+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_revision_update AFTER UPDATE ON documents BEGIN
    UPDATE knowledge_revision SET revision=revision+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_revision_delete AFTER DELETE ON documents BEGIN
    UPDATE knowledge_revision SET revision=revision+1 WHERE singleton=1;
END;

CREATE TABLE IF NOT EXISTS document_versions (\
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    revision TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    markdown TEXT NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_key TEXT NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'reference',
    entities_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id,chunk_key)
);

CREATE TABLE IF NOT EXISTS schema_tables (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    approximate_rows TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    UNIQUE(document_id,schema_name,table_name)
);

CREATE TABLE IF NOT EXISTS schema_columns (
    id INTEGER PRIMARY KEY,
    table_id INTEGER NOT NULL REFERENCES schema_tables(id) ON DELETE CASCADE,
    column_name TEXT NOT NULL,
    data_type TEXT NOT NULL DEFAULT '',
    nullable INTEGER NOT NULL DEFAULT 1,
    primary_key INTEGER NOT NULL DEFAULT 0,
    default_value TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    UNIQUE(table_id,column_name)
);

CREATE TABLE IF NOT EXISTS schema_relations (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    from_schema TEXT NOT NULL,
    from_table TEXT NOT NULL,
    from_column TEXT NOT NULL,
    to_schema TEXT NOT NULL,
    to_table TEXT NOT NULL,
    to_column TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'foreign_key',
    evidence TEXT NOT NULL DEFAULT '',
    UNIQUE(document_id,from_schema,from_table,from_column,to_schema,to_table,to_column)
);

CREATE TABLE IF NOT EXISTS sync_runs (\
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_origin TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS classification_reviews (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    suggested_module TEXT NOT NULL,
    previous_module TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    decided_module TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT '',
    decision_note TEXT NOT NULL DEFAULT '',
    queued_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    document_hash TEXT NOT NULL DEFAULT '',
    suggestion_signature TEXT NOT NULL DEFAULT '',
    validated_change INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    effort TEXT NOT NULL DEFAULT 'medium',
    native_id TEXT NOT NULL DEFAULT '',
    native_id_vr TEXT NOT NULL DEFAULT '',
    workspace TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    archived INTEGER NOT NULL DEFAULT 0,
    service_tier TEXT NOT NULL DEFAULT '',
    approval_profile TEXT NOT NULL DEFAULT 'supervised',
    collaboration_mode TEXT NOT NULL DEFAULT 'default',
    vr_enabled INTEGER NOT NULL DEFAULT 0,
    vr_mode TEXT NOT NULL DEFAULT 'off',
    context_used_tokens INTEGER NOT NULL DEFAULT 0,
    context_window_tokens INTEGER NOT NULL DEFAULT 0,
    total_processed_tokens INTEGER NOT NULL DEFAULT 0,
    trashed_at TEXT NOT NULL DEFAULT '',
    original_workspace TEXT NOT NULL DEFAULT '',
    cloned_from TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    provider_message_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    edited_from_message_id INTEGER,
    response_mode TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_events (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    kind TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    request_json TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tool_definitions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    input_schema_json TEXT NOT NULL DEFAULT '{}',
    executable TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '[]',
    timeout_seconds INTEGER NOT NULL DEFAULT 60,
    safety TEXT NOT NULL DEFAULT 'side_effecting',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_tools (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tool_kind TEXT NOT NULL,
    tool_id TEXT NOT NULL DEFAULT '',
    server_name TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(conversation_id,tool_kind,tool_id,server_name,tool_name)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'file',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_citations (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    document_id INTEGER REFERENCES documents(id),
    message_id INTEGER REFERENCES messages(id),
    excerpt TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'document',
    evidence_id TEXT NOT NULL DEFAULT '',
    provenance TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS message_skills (\
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL,
    name_snapshot TEXT NOT NULL DEFAULT '',
    provider_instance_id TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    path_reference TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title,
    markdown,
    ocr_text,
    module,
    category,
    product,
    content='documents',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
    heading,
    content,
    entities,
    content='knowledge_chunks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
  INSERT INTO knowledge_chunks_fts(rowid,heading,content,entities)
  VALUES(new.id,new.heading,new.content,new.entities_json);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
  INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts,rowid,heading,content,entities)
  VALUES('delete',old.id,old.heading,old.content,old.entities_json);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN
  INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts,rowid,heading,content,entities)
  VALUES('delete',old.id,old.heading,old.content,old.entities_json);
  INSERT INTO knowledge_chunks_fts(rowid,heading,content,entities)
  VALUES(new.id,new.heading,new.content,new.entities_json);
END;

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
  INSERT INTO knowledge_fts(rowid,title,markdown,ocr_text,module,category,product)
  VALUES(new.id,new.title,new.markdown,new.ocr_text,new.module,new.category,new.product);
END;
CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
  INSERT INTO knowledge_fts(knowledge_fts,rowid,title,markdown,ocr_text,module,category,product)
  VALUES('delete',old.id,old.title,old.markdown,old.ocr_text,old.module,old.category,old.product);
END;
CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
  INSERT INTO knowledge_fts(knowledge_fts,rowid,title,markdown,ocr_text,module,category,product)
  VALUES('delete',old.id,old.title,old.markdown,old.ocr_text,old.module,old.category,old.product);
  INSERT INTO knowledge_fts(rowid,title,markdown,ocr_text,module,category,product)
  VALUES(new.id,new.title,new.markdown,new.ocr_text,new.module,new.category,new.product);
END;
"""


def _fts_query(query: str) -> str:
    return " OR ".join(_fts_literal(term) for term in search_terms(query))


def _last_insert_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("O SQLite não retornou o identificador do registro criado.")
    return int(cursor.lastrowid)


def _fts_and_query(terms: list[str]) -> str:
    return " AND ".join(_fts_literal(term) for term in terms)


def _fts_literal(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _score_search_row(
    row: dict[str, Any],
    terms: list[str],
    *,
    minimum_matches: int | None = None,
) -> dict[str, Any] | None:
    title = str(row.get("title") or "")
    markdown = str(row.get("markdown") or "")
    metadata = " ".join(
        str(row.get(field) or "")
        for field in ("module", "source", "category", "product")
    )
    normalized_title = normalize_search_text(title)
    normalized_metadata = normalize_search_text(metadata)
    normalized_content = normalize_search_text(
        markdown + " " + str(row.get("ocr_text") or "")
    )
    title_matches = [term for term in terms if term in normalized_title]
    matched = [
        term
        for term in terms
        if term in normalized_title
        or term in normalized_metadata
        or term in normalized_content
    ]
    required_matches = (
        minimum_term_matches(len(terms))
        if minimum_matches is None
        else max(1, int(minimum_matches))
    )
    if len(matched) < required_matches:
        return None
    coverage = term_coverage(terms, matched)
    title_coverage = term_coverage(terms, title_matches)
    phrase = " ".join(terms)
    inferred_module = infer_search_module(terms)
    score = coverage * 400.0 + title_coverage * 220.0
    if phrase and phrase in normalized_title:
        score += 220.0
    if phrase and phrase in normalized_content:
        score += 120.0
    if inferred_module and str(row.get("module") or "") == inferred_module:
        score += 180.0
    score += min(36, sum(normalized_content.count(term) for term in terms) * 3)
    if len(markdown) > 150_000 and not title_matches:
        score -= 30.0
    result = dict(row)
    result.update(
        {
            "score": round(score, 3),
            "matched_terms": matched,
            "coverage": round(coverage, 4),
            "confidence": round(
                min(0.97, 0.40 + coverage * 0.42 + title_coverage * 0.12),
                3,
            ),
        }
    )
    return result


def _score_search_rows(
    rows: Any, terms: list[str]
) -> list[dict[str, Any]]:
    return [
        scored
        for row in rows
        if (scored := _score_search_row(row, terms)) is not None
    ]


def _expand_reference_results(
    connection: sqlite3.Connection,
    results: list[dict[str, Any]],
    terms: list[str],
    filters: list[str],
    filter_params: list[Any],
) -> None:
    if not results:
        return
    results.sort(key=lambda item: -float(item.get("score") or 0.0))
    by_title = {
        normalize_search_text(item.get("title") or ""): item for item in results
    }
    link_pattern = re.compile(
        r"\[([^]]+)\]\((https?://[^\s)]+)(?:\s+[^)]*)?\)", flags=re.I
    )
    for referring in list(results[:30]):
        markdown = str(referring.get("markdown") or "")
        for label, url in link_pattern.findall(markdown):
            label_matches = matched_search_terms(terms, label)
            if len(label_matches) != len(terms):
                continue
            target_key = normalize_search_text(_reference_target_title(label, url))
            target = by_title.get(target_key)
            if target is None and target_key:
                target_terms = search_terms(target_key)
                if target_terms:
                    sql = f"""
                        SELECT d.*,bm25(knowledge_fts,8.0,1.0,0.8,2.0,1.5,1.5) AS rank
                          FROM knowledge_fts
                          JOIN documents d ON d.id=knowledge_fts.rowid
                         WHERE knowledge_fts MATCH ? AND {' AND '.join(filters)}
                         ORDER BY rank LIMIT 30
                    """
                    params = [_fts_and_query(target_terms), *filter_params]
                    for row in connection.execute(sql, params).fetchall():
                        candidate = dict(row)
                        if normalize_search_text(candidate.get("title") or "") != target_key:
                            continue
                        target = _score_search_row(candidate, terms) or candidate
                        results.append(target)
                        by_title[target_key] = target
                        break
            if target is None or int(target.get("id") or 0) == int(referring.get("id") or -1):
                continue
            target["score"] = round(
                max(
                    float(target.get("score") or 0.0),
                    float(referring.get("score") or 0.0) + 300.0,
                ),
                3,
            )
            target["matched_terms"] = list(terms)
            target["coverage"] = 1.0
            target["confidence"] = max(float(target.get("confidence") or 0.0), 0.98)
            target["resolved_from"] = str(referring.get("title") or "")


def _reference_target_title(label: str, url: str) -> str:
    from urllib.parse import parse_qs, unquote, urlparse

    title = parse_qs(urlparse(url).query).get("title", [""])[0]
    if title:
        return unquote(title).replace("_", " ")
    match = re.match(r"\s*(fun(?:c|ç)[aã]o\s+\d+)", label, flags=re.I)
    return match.group(1) if match else label

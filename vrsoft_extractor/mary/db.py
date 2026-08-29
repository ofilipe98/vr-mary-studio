from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .chat_tools import validate_tool_definition
from .content import target_path, write_document
from .knowledge import split_knowledge_document
from .models import (
    KnowledgeDocument,
    ReviewFilters,
    ReviewPage,
    RuntimeEvent,
    SyncStats,
    utc_now,
)
from .paths import resolve_portable_path, to_portable_path
from .search import (
    infer_search_module,
    matched_search_terms,
    minimum_term_matches,
    normalize_search_text,
    search_excerpt,
    search_terms,
    term_coverage,
)
from .schema_catalog import parse_schema_markdown


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

CREATE TABLE IF NOT EXISTS documents (
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

CREATE TABLE IF NOT EXISTS document_versions (
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

CREATE TABLE IF NOT EXISTS sync_runs (
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
    approval_profile TEXT NOT NULL DEFAULT 'auto',
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
    excerpt TEXT NOT NULL DEFAULT ''
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


class MaryDatabase:
    def __init__(
        self,
        path: Path,
        root: Path | None = None,
        *,
        backup_portable_migration: bool = True,
    ):
        self.path = path
        self.root = root.resolve() if root else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            if self.root and backup_portable_migration:
                self._backup_before_knowledge_router_migration(connection)
                self._backup_before_endoo_wiki_migration(connection)
            connection.executescript(SCHEMA)
            self._ensure_column(
                connection,
                "documents",
                "source_origin",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "sync_runs",
                "source_origin",
                "TEXT NOT NULL DEFAULT ''",
            )
            connection.execute(
                """UPDATE documents
                      SET source_origin=CASE source
                            WHEN 'wiki' THEN 'vrwiki'
                            WHEN 'kb' THEN 'movidesk'
                            WHEN 'schema' THEN 'local'
                            ELSE source
                          END
                    WHERE trim(source_origin)=''"""
            )
            connection.execute(
                """UPDATE sync_runs
                      SET source_origin=CASE source
                            WHEN 'wiki' THEN 'vrwiki'
                            WHEN 'kb' THEN 'movidesk'
                            WHEN 'schema' THEN 'local'
                            ELSE source
                          END
                    WHERE trim(source_origin)=''"""
            )
            self._ensure_column(
                connection,
                "conversations",
                "effort",
                "TEXT NOT NULL DEFAULT 'medium'",
            )
            for column, definition in (
                ("service_tier", "TEXT NOT NULL DEFAULT ''"),
                ("approval_profile", "TEXT NOT NULL DEFAULT 'auto_edits'"),
                ("collaboration_mode", "TEXT NOT NULL DEFAULT 'default'"),
                ("vr_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("vr_mode", "TEXT NOT NULL DEFAULT ''"),
                ("native_id_vr", "TEXT NOT NULL DEFAULT ''"),
                ("context_used_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("context_window_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("total_processed_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("trashed_at", "TEXT NOT NULL DEFAULT ''"),
                ("original_workspace", "TEXT NOT NULL DEFAULT ''"),
            ):
                self._ensure_column(connection, "conversations", column, definition)
            connection.execute(
                """UPDATE conversations
                      SET vr_mode=CASE WHEN vr_enabled=1 THEN 'vr' ELSE 'off' END
                    WHERE trim(vr_mode)=''"""
            )
            for column, definition in (
                ("turn_id", "TEXT NOT NULL DEFAULT ''"),
                ("edited_from_message_id", "INTEGER"),
                ("response_mode", "TEXT NOT NULL DEFAULT ''"),
            ):
                self._ensure_column(connection, "messages", column, definition)
            for column, definition in (
                ("decision_note", "TEXT NOT NULL DEFAULT ''"),
                ("queued_at", "TEXT NOT NULL DEFAULT ''"),
                ("updated_at", "TEXT NOT NULL DEFAULT ''"),
                ("document_hash", "TEXT NOT NULL DEFAULT ''"),
                ("suggestion_signature", "TEXT NOT NULL DEFAULT ''"),
                ("validated_change", "INTEGER NOT NULL DEFAULT 0"),
            ):
                self._ensure_column(
                    connection,
                    "classification_reviews",
                    column,
                    definition,
                )
            if self.root and backup_portable_migration:
                # sqlite3.Connection.backup() cannot make progress while its
                # source connection still owns the migration write transaction.
                connection.commit()
                self._backup_before_portable_migration(connection)
            self._migrate_review_metadata(connection)
            if self.root:
                self._migrate_portable_paths(connection)
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_review_status
                    ON classification_reviews(status);
                CREATE INDEX IF NOT EXISTS idx_review_suggested_confidence
                    ON classification_reviews(suggested_module,confidence);
                CREATE INDEX IF NOT EXISTS idx_review_document_status
                    ON classification_reviews(document_id,status);
                CREATE INDEX IF NOT EXISTS idx_review_updated
                    ON classification_reviews(updated_at);
                CREATE INDEX IF NOT EXISTS idx_documents_review_facets
                    ON documents(source,module,product,updated_at);
                CREATE INDEX IF NOT EXISTS idx_documents_source_origin
                    ON documents(source,source_origin,status,module);
                CREATE INDEX IF NOT EXISTS idx_sync_runs_source_origin
                    ON sync_runs(source,source_origin,id);
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_type
                    ON knowledge_chunks(document_id,content_type);
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_hash
                    ON knowledge_chunks(content_hash);
                CREATE INDEX IF NOT EXISTS idx_schema_tables_name
                    ON schema_tables(schema_name,table_name);
                CREATE INDEX IF NOT EXISTS idx_schema_columns_name
                    ON schema_columns(column_name,table_id);
                CREATE INDEX IF NOT EXISTS idx_schema_relations_from
                    ON schema_relations(from_schema,from_table,from_column);
                CREATE INDEX IF NOT EXISTS idx_schema_relations_to
                    ON schema_relations(to_schema,to_table,to_column);
                CREATE INDEX IF NOT EXISTS idx_runtime_events_conversation_kind
                    ON runtime_events(conversation_id,kind,id);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_source_citations_message
                    ON source_citations(message_id);
                CREATE INDEX IF NOT EXISTS idx_source_citations_conversation
                    ON source_citations(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_document_versions_document
                    ON document_versions(document_id);
                CREATE INDEX IF NOT EXISTS idx_approvals_conversation
                    ON approvals(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_conversation
                    ON artifacts(conversation_id);
                """
            )

    def _backup_before_knowledge_router_migration(
        self, connection: sqlite3.Connection
    ) -> None:
        """Snapshot an existing knowledge database before adding chunk indexes."""
        root = self.root
        if root is None:
            raise RuntimeError("A raiz da base é obrigatória para criar o backup.")
        has_documents = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()
        has_chunks = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_chunks'"
        ).fetchone()
        if not has_documents or has_chunks:
            return
        backup_path = (
            root / ".state" / "backups" / "conhecimento-pre-knowledge-router.sqlite"
        )
        if backup_path.exists():
            return
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup_path) as target:
            connection.backup(target)

    def _backup_before_endoo_wiki_migration(
        self, connection: sqlite3.Connection
    ) -> None:
        """Snapshot an existing knowledge database before adding origin metadata."""

        root = self.root
        if root is None:
            raise RuntimeError("A raiz da base é obrigatória para criar o backup.")
        has_documents = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()
        if not has_documents:
            return
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "source_origin" in columns:
            return
        backup_path = (
            root / ".state" / "backups" / "conhecimento-pre-endoo-wiki.sqlite"
        )
        if backup_path.exists():
            return
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup_path) as target:
            connection.backup(target)

    def _backup_before_portable_migration(
        self, connection: sqlite3.Connection
    ) -> None:
        root = self.root
        if root is None:
            raise RuntimeError("A raiz da base é obrigatória para criar o backup.")
        if not self._has_nonportable_paths(connection):
            return
        backup_path = (
            root / ".state" / "backups" / "conhecimento-pre-portable.sqlite"
        )
        if backup_path.exists():
            return
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup_path) as target:
            connection.backup(target)

    @staticmethod
    def _has_nonportable_paths(connection: sqlite3.Connection) -> bool:
        checks = (
            ("documents", ("local_path", "assets_json")),
            ("conversations", ("workspace", "original_workspace")),
            ("artifacts", ("path",)),
        )
        for table, columns in checks:
            where, parameters = MaryDatabase._nonportable_path_filter(columns)
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", parameters
            ).fetchone():
                return True
        return False

    @staticmethod
    def _nonportable_path_filter(columns: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        patterns = ("%:\\%", "%:/%")
        where = " OR ".join(
            f"({column} LIKE ? OR {column} LIKE ?)" for column in columns
        )
        return where, tuple(pattern for _column in columns for pattern in patterns)

    def _migrate_portable_paths(self, connection: sqlite3.Connection) -> None:
        root = self.root
        if root is None:
            raise RuntimeError("A raiz da base é obrigatória para migrar caminhos.")
        if not self._has_nonportable_paths(connection):
            return
        document_where, document_parameters = self._nonportable_path_filter(
            ("local_path", "assets_json")
        )
        rows = connection.execute(
            f"SELECT id,local_path,assets_json FROM documents WHERE {document_where}",
            document_parameters,
        ).fetchall()
        for row in rows:
            try:
                assets = json.loads(row["assets_json"] or "[]")
            except (TypeError, ValueError):
                assets = []
            local_path = to_portable_path(root, row["local_path"])
            portable_assets = [to_portable_path(root, item) for item in assets]
            assets_json = json.dumps(portable_assets, ensure_ascii=False)
            if local_path != row["local_path"] or assets_json != row["assets_json"]:
                connection.execute(
                    "UPDATE documents SET local_path=?,assets_json=? WHERE id=?",
                    (local_path, assets_json, row["id"]),
                )

        for table in ("conversations", "artifacts"):
            columns = (
                ("workspace", "original_workspace")
                if table == "conversations"
                else ("path",)
            )
            selected = ",".join(("id", *columns))
            where, parameters = self._nonportable_path_filter(columns)
            for row in connection.execute(
                f"SELECT {selected} FROM {table} WHERE {where}", parameters
            ).fetchall():
                values = {column: to_portable_path(root, row[column]) for column in columns}
                if any(values[column] != row[column] for column in columns):
                    assignments = ",".join(f"{column}=?" for column in columns)
                    connection.execute(
                        f"UPDATE {table} SET {assignments} WHERE id=?",
                        (*[values[column] for column in columns], row["id"]),
                    )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        existing = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    @staticmethod
    def _migrate_review_metadata(connection: sqlite3.Connection) -> None:
        now = utc_now()
        connection.execute(
            """UPDATE classification_reviews
               SET queued_at=CASE WHEN queued_at='' THEN ? ELSE queued_at END,
                   updated_at=CASE WHEN updated_at='' THEN ? ELSE updated_at END,
                   document_hash=CASE
                     WHEN document_hash='' THEN COALESCE(
                       (SELECT content_hash FROM documents
                        WHERE documents.id=classification_reviews.document_id),
                       ''
                     )
                     ELSE document_hash
                   END
                WHERE queued_at='' OR updated_at='' OR document_hash=''""",
            (now, now),
        )
        rows = connection.execute(
            """SELECT id,suggested_module,reasons_json
               FROM classification_reviews
               WHERE suggestion_signature=''"""
        ).fetchall()
        for row in rows:
            connection.execute(
                """UPDATE classification_reviews
                   SET suggestion_signature=? WHERE id=?""",
                (
                    _review_signature(
                        str(row["suggested_module"]),
                        _review_reasons(str(row["reasons_json"])),
                    ),
                    row["id"],
                ),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get_document(self, source: str, source_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM documents WHERE source=? AND source_id=?",
                (source, source_id),
            ).fetchone()

    def active_source_origins(self, source: str) -> tuple[str, ...]:
        """Return the active physical origins available for a logical source."""

        with self.connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT source_origin
                     FROM documents
                    WHERE source=? AND status='active'
                      AND trim(source_origin)<>''
                    ORDER BY source_origin""",
                (str(source or "").strip(),),
            ).fetchall()
        return tuple(str(row["source_origin"]) for row in rows)

    def upsert_document(self, document: KnowledgeDocument) -> tuple[int, str]:
        if self.root:
            document.local_path = to_portable_path(self.root, document.local_path)
            document.assets = [
                to_portable_path(self.root, asset) for asset in document.assets
            ]
        current = self.get_document(document.source, document.source_id)
        content_changed = bool(
            current and current["content_hash"] != document.content_hash
        )
        action = "updated" if content_changed else "unchanged" if current else "created"
        with self.connect() as connection:
            if content_changed:
                if current is None:
                    raise RuntimeError("Documento alterado sem versão anterior carregada.")
                connection.execute(
                    """INSERT INTO document_versions
                       (document_id,revision,content_hash,markdown,captured_at)
                       VALUES(?,?,?,?,?)""",
                    (
                        current["id"],
                        current["revision"],
                        current["content_hash"],
                        current["markdown"],
                        utc_now(),
                    ),
                )
            connection.execute(
                """INSERT INTO documents (
                    source,source_origin,source_id,title,url,module,classification_confidence,
                    review_status,status,category,product,created_at,updated_at,
                    synced_at,revision,content_hash,markdown,ocr_text,local_path,assets_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,source_id) DO UPDATE SET
                    source_origin=excluded.source_origin,
                    title=excluded.title,url=excluded.url,
                    module=CASE
                      WHEN documents.review_status='approved'
                           AND documents.module<>excluded.module
                        THEN documents.module
                      ELSE excluded.module END,
                    classification_confidence=excluded.classification_confidence,
                    review_status=CASE
                      WHEN documents.review_status='approved'
                           AND documents.module<>excluded.module THEN 'pending'
                      WHEN documents.review_status='approved'
                           AND documents.content_hash=excluded.content_hash
                        THEN documents.review_status
                      ELSE excluded.review_status END,
                    status=excluded.status,category=excluded.category,product=excluded.product,
                    created_at=CASE
                      WHEN trim(documents.created_at)=''
                      THEN excluded.created_at ELSE documents.created_at END,
                    updated_at=excluded.updated_at,
                    synced_at=excluded.synced_at,revision=excluded.revision,
                    content_hash=excluded.content_hash,markdown=excluded.markdown,
                    ocr_text=excluded.ocr_text,local_path=excluded.local_path,
                    assets_json=excluded.assets_json""",
                (
                    document.source,
                    document.source_origin or _default_source_origin(document.source),
                    document.source_id,
                    document.title,
                    document.url,
                    document.module,
                    document.classification_confidence,
                    document.review_status,
                    document.status,
                    document.category,
                    document.product,
                    document.created_at,
                    document.updated_at,
                    document.synced_at,
                    document.revision,
                    document.content_hash,
                    document.markdown,
                    document.ocr_text,
                    document.local_path,
                    json.dumps(document.assets, ensure_ascii=False),
                ),
            )
            row = connection.execute(
                "SELECT id FROM documents WHERE source=? AND source_id=?",
                (document.source, document.source_id),
            ).fetchone()
            document_id = int(row["id"])
            has_chunks = connection.execute(
                "SELECT 1 FROM knowledge_chunks WHERE document_id=? LIMIT 1",
                (document_id,),
            ).fetchone()
            if action != "unchanged" or not has_chunks:
                self._replace_document_chunks(connection, document_id, document)
            has_schema = connection.execute(
                "SELECT 1 FROM schema_tables WHERE document_id=? LIMIT 1",
                (document_id,),
            ).fetchone()
            if document.source == "schema" and (
                action != "unchanged" or not has_schema
            ):
                self._replace_schema_catalog(connection, document_id, document)
        return document_id, action

    @staticmethod
    def _replace_document_chunks(
        connection: sqlite3.Connection,
        document_id: int,
        document: KnowledgeDocument,
    ) -> None:
        chunks = split_knowledge_document(
            document.title,
            document.markdown,
            document.ocr_text,
            source=document.source,
        )
        connection.execute(
            "DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,)
        )
        now = utc_now()
        connection.executemany(
            """INSERT INTO knowledge_chunks
               (document_id,chunk_key,heading,content,content_type,entities_json,
                content_hash,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                (
                    document_id,
                    chunk.chunk_key,
                    chunk.heading,
                    chunk.content,
                    chunk.content_type,
                    json.dumps(chunk.entities, ensure_ascii=False),
                    chunk.content_hash,
                    now,
                    now,
                )
                for chunk in chunks
            ],
        )

    @staticmethod
    def _replace_schema_catalog(
        connection: sqlite3.Connection,
        document_id: int,
        document: KnowledgeDocument,
    ) -> None:
        connection.execute(
            "DELETE FROM schema_relations WHERE document_id=?", (document_id,)
        )
        connection.execute(
            "DELETE FROM schema_tables WHERE document_id=?", (document_id,)
        )
        for table in parse_schema_markdown(document.markdown):
            cursor = connection.execute(
                """INSERT INTO schema_tables
                   (document_id,schema_name,table_name,description,approximate_rows,version)
                   VALUES(?,?,?,?,?,?)""",
                (
                    document_id,
                    table.schema_name,
                    table.table_name,
                    table.description,
                    table.approximate_rows,
                    document.revision,
                ),
            )
            table_id = _last_insert_id(cursor)
            connection.executemany(
                """INSERT INTO schema_columns
                   (table_id,column_name,data_type,nullable,primary_key,default_value,description)
                   VALUES(?,?,?,?,?,?,?)""",
                [
                    (
                        table_id,
                        column.name,
                        column.data_type,
                        int(column.nullable),
                        int(column.primary_key),
                        column.default_value,
                        column.description,
                    )
                    for column in table.columns
                ],
            )
            connection.executemany(
                """INSERT OR IGNORE INTO schema_relations
                   (document_id,from_schema,from_table,from_column,
                    to_schema,to_table,to_column,relation_type,evidence)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        document_id,
                        relation.from_schema,
                        relation.from_table,
                        relation.from_column,
                        relation.to_schema,
                        relation.to_table,
                        relation.to_column,
                        "foreign_key",
                        relation.evidence,
                    )
                    for relation in table.relations
                ],
            )

    def queue_review(
        self,
        document_id: int,
        suggested_module: str,
        confidence: float,
        reasons: list[str],
        previous_module: str = "",
        validated_change: bool = False,
    ) -> bool:
        now = utc_now()
        reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
        reasons_json = json.dumps(reasons, ensure_ascii=False)
        signature = _review_signature(suggested_module, reasons)
        with self.connect() as connection:
            document = connection.execute(
                "SELECT content_hash FROM documents WHERE id=?",
                (document_id,),
            ).fetchone()
            if not document:
                raise KeyError(f"Documento inexistente: {document_id}")
            document_hash = str(document["content_hash"])
            active = connection.execute(
                """SELECT * FROM classification_reviews
                   WHERE document_id=? AND status IN ('pending','deferred')
                   ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,id DESC
                   LIMIT 1""",
                (document_id,),
            ).fetchone()
            if active:
                unchanged_deferred = (
                    active["status"] == "deferred"
                    and active["document_hash"] == document_hash
                    and active["suggestion_signature"] == signature
                )
                if unchanged_deferred:
                    return False
                connection.execute(
                    """UPDATE classification_reviews
                       SET suggested_module=?,previous_module=?,confidence=?,
                           reasons_json=?,status='pending',decided_module='',
                           decided_at='',decision_note='',updated_at=?,
                           document_hash=?,suggestion_signature=?,
                           validated_change=?
                       WHERE id=?""",
                    (
                        suggested_module,
                        previous_module,
                        confidence,
                        reasons_json,
                        now,
                        document_hash,
                        signature,
                        int(validated_change),
                        active["id"],
                    ),
                )
                connection.execute(
                    "UPDATE documents SET review_status='pending' WHERE id=?",
                    (document_id,),
                )
                return True

            latest = connection.execute(
                """SELECT * FROM classification_reviews
                   WHERE document_id=? ORDER BY id DESC LIMIT 1""",
                (document_id,),
            ).fetchone()
            if (
                latest
                and latest["status"] in {"approved", "kept", "deferred"}
                and latest["document_hash"] == document_hash
                and latest["suggestion_signature"] == signature
            ):
                return False
            connection.execute(
                """INSERT INTO classification_reviews
                   (document_id,suggested_module,previous_module,confidence,
                    reasons_json,status,queued_at,updated_at,document_hash,
                    suggestion_signature,validated_change)
                   VALUES(?,?,?,?,?,'pending',?,?,?,?,?)""",
                (
                    document_id,
                    suggested_module,
                    previous_module,
                    confidence,
                    reasons_json,
                    now,
                    now,
                    document_hash,
                    signature,
                    int(validated_change),
                )
            )
            connection.execute(
                "UPDATE documents SET review_status='pending' WHERE id=?",
                (document_id,),
            )
            return True

    def decide_reviews(
        self,
        review_ids: list[int],
        action: str,
        module: str = "",
        note: str = "",
    ) -> int:
        unique_ids = list(dict.fromkeys(int(review_id) for review_id in review_ids))
        if not unique_ids:
            raise ValueError("Selecione pelo menos uma revisão.")
        if action not in REVIEW_ACTIONS:
            raise ValueError(f"Ação de revisão inválida: {action}")
        destination = module.strip()
        if action == "approve" and destination not in REVIEW_MODULES:
            raise ValueError("Selecione um módulo de destino válido.")

        placeholders = ",".join("?" for _ in unique_ids)
        file_snapshots: dict[Path, bytes | None] = {}
        replaced_files: list[tuple[Path, Path]] = []
        try:
            with self.connect() as connection:
                reviews = connection.execute(
                    f"""SELECT r.*,d.module AS current_module,
                           d.source AS document_source,
                           d.source_origin AS document_source_origin,
                           d.source_id AS document_source_id,
                           d.title AS document_title,d.url AS document_url,
                           d.markdown AS document_markdown,
                           d.classification_confidence,
                           d.review_status AS document_review_status,
                           d.status AS document_status,
                           d.created_at AS document_created_at,
                           d.updated_at AS document_updated_at,
                           d.synced_at AS document_synced_at,
                           d.revision AS document_revision,
                           d.content_hash AS document_content_hash,
                           d.category AS document_category,
                           d.product AS document_product,
                           d.ocr_text AS document_ocr_text,
                           d.local_path AS document_local_path,
                           d.assets_json AS document_assets_json
                    FROM classification_reviews r
                    JOIN documents d ON d.id=r.document_id
                    WHERE r.id IN ({placeholders})""",
                    unique_ids,
                ).fetchall()
                if len(reviews) != len(unique_ids):
                    raise KeyError("Uma ou mais revisões não existem.")
                if action in {"approve", "keep", "defer"} and any(
                    row["status"] != "pending" for row in reviews
                ):
                    raise ValueError(
                        "Somente revisões pendentes podem receber essa decisão."
                    )
                if action == "reopen":
                    if any(row["status"] == "pending" for row in reviews):
                        raise ValueError("A revisão selecionada já está pendente.")
                    for review in reviews:
                        newer = connection.execute(
                            """SELECT 1 FROM classification_reviews
                               WHERE document_id=? AND id>? LIMIT 1""",
                            (review["document_id"], review["id"]),
                        ).fetchone()
                        if newer:
                            raise ValueError(
                                "Somente a decisão mais recente de cada documento "
                                "pode ser reaberta."
                            )

                now = utc_now()
                for review in reviews:
                    final_module = (
                        destination if action == "approve" else review["current_module"]
                    )
                    final_review_status = (
                        "approved" if action in {"approve", "keep"} else "pending"
                    )
                    local_path = str(review["document_local_path"] or "")
                    if self.root:
                        document = self._review_document(
                            review,
                            module=str(final_module),
                            review_status=final_review_status,
                        )
                        target = target_path(self.root, document)
                        if target not in file_snapshots:
                            file_snapshots[target] = (
                                target.read_bytes() if target.is_file() else None
                            )
                        previous = resolve_portable_path(
                            self.root, review["document_local_path"]
                        )
                        write_document(self.root, document)
                        local_path = document.local_path
                        replaced_files.append((previous, target))

                    if action == "approve":
                        connection.execute(
                            """UPDATE classification_reviews
                               SET status='approved',decided_module=?,decided_at=?,
                                   decision_note=?,updated_at=?
                               WHERE id=?""",
                            (destination, now, note.strip(), now, review["id"]),
                        )
                        connection.execute(
                            """UPDATE documents
                               SET module=?,review_status='approved',local_path=?
                               WHERE id=?""",
                            (destination, local_path, review["document_id"]),
                        )
                    elif action == "keep":
                        connection.execute(
                            """UPDATE classification_reviews
                               SET status='kept',decided_module=?,decided_at=?,
                                   decision_note=?,updated_at=?
                               WHERE id=?""",
                            (
                                review["current_module"],
                                now,
                                note.strip(),
                                now,
                                review["id"],
                            ),
                        )
                        connection.execute(
                            """UPDATE documents
                               SET review_status='approved',local_path=? WHERE id=?""",
                            (local_path, review["document_id"]),
                        )
                    elif action == "defer":
                        connection.execute(
                            """UPDATE classification_reviews
                               SET status='deferred',decided_module=?,decided_at=?,
                                   decision_note=?,updated_at=?
                               WHERE id=?""",
                            (
                                review["current_module"],
                                now,
                                note.strip(),
                                now,
                                review["id"],
                            ),
                        )
                        connection.execute(
                            """UPDATE documents
                               SET review_status='pending',local_path=? WHERE id=?""",
                            (local_path, review["document_id"]),
                        )
                    else:
                        connection.execute(
                            """UPDATE classification_reviews
                               SET status='pending',decided_module='',decided_at='',
                                   decision_note='',updated_at=?
                               WHERE id=?""",
                            (now, review["id"]),
                        )
                        connection.execute(
                            """UPDATE documents
                               SET review_status='pending',local_path=? WHERE id=?""",
                            (local_path, review["document_id"]),
                        )
        except Exception:
            self._restore_document_files(file_snapshots)
            raise

        self._remove_replaced_document_files(replaced_files)
        return len(unique_ids)

    @staticmethod
    def _review_document(
        review: sqlite3.Row,
        *,
        module: str,
        review_status: str,
    ) -> KnowledgeDocument:
        try:
            assets = json.loads(review["document_assets_json"] or "[]")
        except (TypeError, ValueError):
            assets = []
        return KnowledgeDocument(
            source=str(review["document_source"]),
            source_origin=str(review["document_source_origin"]),
            source_id=str(review["document_source_id"]),
            title=str(review["document_title"]),
            url=str(review["document_url"]),
            markdown=str(review["document_markdown"] or ""),
            module=module,
            classification_confidence=float(
                review["classification_confidence"] or 0.0
            ),
            review_status=review_status,
            status=str(review["document_status"]),
            created_at=str(review["document_created_at"] or ""),
            updated_at=str(review["document_updated_at"] or ""),
            synced_at=str(review["document_synced_at"] or ""),
            revision=str(review["document_revision"] or ""),
            content_hash=str(review["document_content_hash"] or ""),
            category=str(review["document_category"] or ""),
            product=str(review["document_product"] or ""),
            assets=[str(asset) for asset in assets],
            ocr_text=str(review["document_ocr_text"] or ""),
            local_path=str(review["document_local_path"] or ""),
        )

    @staticmethod
    def _restore_document_files(snapshots: dict[Path, bytes | None]) -> None:
        for path, content in snapshots.items():
            try:
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            except OSError as exc:
                LOGGER.warning(
                    "Falha ao restaurar arquivo %s: %s", path, exc
                )

    def _remove_replaced_document_files(
        self, replaced_files: list[tuple[Path, Path]]
    ) -> None:
        if not self.root:
            return
        knowledge_root = (self.root / "conhecimento").resolve()
        for previous, target in replaced_files:
            try:
                previous = previous.resolve(strict=False)
                if (
                    previous != target.resolve(strict=False)
                    and previous.is_relative_to(knowledge_root)
                    and previous.is_file()
                ):
                    previous.unlink()
            except OSError as exc:
                LOGGER.warning(
                    "Falha ao remover arquivo substituído %s: %s", previous, exc
                )

    def list_reviews(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_size = 500
        maximum = 10_000
        offset = 0
        while len(items) < maximum:
            page = self.query_reviews(
                ReviewFilters(limit=page_size, offset=offset)
            )
            items.extend(page.items)
            if len(page.items) < page_size or len(items) >= page.total:
                break
            offset += page_size
        return items[:maximum]

    def query_reviews(self, filters: ReviewFilters) -> ReviewPage:
        where = ["d.status='active'"]
        params: list[Any] = []
        if filters.status and filters.status != "all":
            where.append("r.status=?")
            params.append(filters.status)
        if filters.source:
            where.append("d.source=?")
            params.append(filters.source)
        if filters.source_origin:
            where.append("d.source_origin=?")
            params.append(filters.source_origin)
        if filters.current_module:
            where.append("d.module=?")
            params.append(filters.current_module)
        if filters.suggested_module:
            where.append("r.suggested_module=?")
            params.append(filters.suggested_module)
        if filters.product:
            where.append("d.product=?")
            params.append(filters.product)
        if filters.category:
            where.append("d.category=?")
            params.append(filters.category)
        if filters.confidence_band == "high":
            where.append("r.confidence>=0.85")
        elif filters.confidence_band == "medium":
            where.append("r.confidence>=0.60 AND r.confidence<0.85")
        elif filters.confidence_band == "low":
            where.append("r.confidence<0.60")
        if filters.period_days > 0:
            where.append(
                "julianday(COALESCE(NULLIF(r.updated_at,''),d.synced_at)) "
                ">= julianday('now',?)"
            )
            params.append(f"-{filters.period_days} days")
        if filters.query.strip():
            needle = f"%{_escape_like(filters.query.strip().casefold())}%"
            where.append(
                """lower(
                     d.title || ' ' || d.source_id || ' ' || d.product || ' ' ||
                     d.category || ' ' || r.reasons_json || ' ' || d.markdown ||
                     ' ' || d.ocr_text
                   ) LIKE ? ESCAPE '\\'"""
            )
            params.append(needle)

        validated_change = "r.validated_change=1"
        if filters.special == "module_change":
            where.append(f"({validated_change})")
        elif filters.special == "no_product":
            where.append("trim(d.product)=''")
        elif filters.special == "low_evidence":
            where.append(
                "(trim(r.reasons_json) IN ('','[]') "
                "OR json_array_length(r.reasons_json)=0)"
            )
        elif filters.special == "simple":
            where.extend(
                [
                    "r.confidence>=0.85",
                    f"NOT ({validated_change})",
                    "trim(d.product)<>''",
                    "trim(r.reasons_json) NOT IN ('','[]')",
                ]
            )

        where_sql = " AND ".join(where)
        risk_score = (
            f"(CASE WHEN {validated_change} THEN 100 ELSE 0 END + "
            "CASE WHEN r.confidence<0.60 THEN 30 "
            "WHEN r.confidence<0.85 THEN 15 ELSE 0 END + "
            "CASE WHEN trim(d.product)='' THEN 10 ELSE 0 END + "
            "CASE WHEN trim(r.reasons_json) IN ('','[]') THEN 5 ELSE 0 END)"
        )
        order_by = {
            "risk": "risk_score DESC,r.confidence ASC,r.updated_at DESC,r.id DESC",
            "confidence_desc": "r.confidence DESC,r.updated_at DESC,r.id DESC",
            "confidence_asc": "r.confidence ASC,r.updated_at DESC,r.id DESC",
            "recent": "r.updated_at DESC,r.id DESC",
            "title": "d.title COLLATE NOCASE ASC,r.id DESC",
        }.get(filters.sort, "risk_score DESC,r.confidence ASC,r.id DESC")
        limit = min(max(int(filters.limit), 1), 500)
        offset = max(int(filters.offset), 0)

        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"""SELECT count(*)
                        FROM classification_reviews r
                        JOIN documents d ON d.id=r.document_id
                        WHERE {where_sql}""",
                    params,
                ).fetchone()[0]
            )
            if total == 0:
                offset = 0
            elif offset >= total:
                offset = ((total - 1) // limit) * limit
            rows = connection.execute(
                f"""SELECT r.*,d.source_id,d.title,d.source,d.source_origin,d.url,
                           d.module AS current_module,d.review_status,
                           d.category,d.product,d.created_at,d.updated_at AS document_updated_at,
                           d.synced_at,d.markdown,d.ocr_text,d.local_path,d.assets_json,
                           CASE WHEN EXISTS(
                             SELECT 1 FROM classification_reviews newer
                             WHERE newer.document_id=r.document_id AND newer.id>r.id
                           ) THEN 0 ELSE 1 END AS is_latest,
                           {risk_score} AS risk_score,
                           CASE
                             WHEN {validated_change} THEN 'Mudança validada'
                             WHEN r.confidence<0.60 THEN 'Baixa confiança'
                             WHEN trim(d.product)='' THEN 'Sem produto'
                             WHEN trim(r.reasons_json) IN ('','[]') THEN 'Pouca evidência'
                             ELSE 'Revisão padrão'
                           END AS risk_label
                    FROM classification_reviews r
                    JOIN documents d ON d.id=r.document_id
                    WHERE {where_sql}
                    ORDER BY {order_by}
                    LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()
        return ReviewPage(
            items=[dict(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def review_filter_values(self) -> dict[str, list[str]]:
        with self.connect() as connection:
            products = [
                str(row[0])
                for row in connection.execute(
                    """SELECT DISTINCT d.product
                       FROM classification_reviews r
                       JOIN documents d ON d.id=r.document_id
                       WHERE trim(d.product)<>'' ORDER BY d.product COLLATE NOCASE"""
                ).fetchall()
            ]
            categories = [
                str(row[0])
                for row in connection.execute(
                    """SELECT DISTINCT d.category
                       FROM classification_reviews r
                       JOIN documents d ON d.id=r.document_id
                       WHERE trim(d.category)<>'' ORDER BY d.category COLLATE NOCASE"""
                ).fetchall()
            ]
        return {"products": products, "categories": categories}

    def backfill_knowledge_chunks(self, limit: int = 0) -> int:
        """Create missing chunks for documents written before the chunk index."""
        sql = """SELECT d.* FROM documents d
                  WHERE NOT EXISTS (
                      SELECT 1 FROM knowledge_chunks c WHERE c.document_id=d.id
                  )
                  ORDER BY d.id"""
        params: tuple[Any, ...] = ()
        if limit > 0:
            sql += " LIMIT ?"
            params = (int(limit),)
        created = 0
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            for row in rows:
                document = KnowledgeDocument(
                    source=str(row["source"]),
                    source_origin=str(row["source_origin"]),
                    source_id=str(row["source_id"]),
                    title=str(row["title"]),
                    url=str(row["url"]),
                    markdown=str(row["markdown"]),
                    ocr_text=str(row["ocr_text"]),
                    module=str(row["module"]),
                    product=str(row["product"]),
                    category=str(row["category"]),
                    review_status=str(row["review_status"]),
                    status=str(row["status"]),
                    revision=str(row["revision"]),
                    content_hash=str(row["content_hash"]),
                    local_path=str(row["local_path"]),
                )
                self._replace_document_chunks(connection, int(row["id"]), document)
                if document.source == "schema":
                    self._replace_schema_catalog(
                        connection, int(row["id"]), document
                    )
                created += 1
        return created

    def search_chunks(
        self,
        query: str,
        limit: int = 8,
        *,
        source: str = "",
        module: str = "",
        source_origin: str = "",
        content_types: tuple[str, ...] = (),
        include_unvalidated: bool = False,
    ) -> list[dict[str, Any]]:
        terms = search_terms(query)
        if not terms:
            return []
        filters = ["d.status='active'"]
        params: list[Any] = []
        if not include_unvalidated:
            filters.extend(
                [
                    "d.module<>'Revisar'",
                    "d.review_status IN ('approved','kept')",
                ]
            )
        if source:
            filters.append("d.source=?")
            params.append(source)
        if source_origin:
            filters.append("d.source_origin=?")
            params.append(source_origin)
        if module:
            filters.append("d.module=?")
            params.append(module)
        if content_types:
            placeholders = ",".join("?" for _ in content_types)
            filters.append(f"c.content_type IN ({placeholders})")
            params.extend(content_types)
        sql = f"""
            SELECT c.id AS chunk_id,c.heading,c.content,c.content_type,
                   c.entities_json,c.content_hash AS chunk_hash,
                   d.id AS document_id,d.source,d.source_origin,d.source_id,d.title,d.url,
                   d.module,d.product,d.category,d.updated_at,d.synced_at,
                   d.local_path,d.review_status,d.classification_confidence,
                   bm25(knowledge_chunks_fts,5.0,1.0,2.0) AS rank
              FROM knowledge_chunks_fts
              JOIN knowledge_chunks c ON c.id=knowledge_chunks_fts.rowid
              JOIN documents d ON d.id=c.document_id
             WHERE knowledge_chunks_fts MATCH ? AND {' AND '.join(filters)}
             ORDER BY rank LIMIT ?
        """
        raw_by_chunk: dict[int, dict[str, Any]] = {}
        with self.connect() as connection:
            exact_params = [
                _fts_and_query(terms),
                *params,
                max(40, int(limit) * 8),
            ]
            for row in connection.execute(sql, exact_params).fetchall():
                raw_by_chunk[int(row["chunk_id"])] = dict(row)
            if len(raw_by_chunk) < max(1, int(limit)):
                broad_params = [
                    _fts_query(query),
                    *params,
                    max(80, int(limit) * 16),
                ]
                for row in connection.execute(sql, broad_params).fetchall():
                    raw_by_chunk.setdefault(int(row["chunk_id"]), dict(row))
        scored: list[dict[str, Any]] = []
        for raw in raw_by_chunk.values():
            candidate_row = {
                **raw,
                "title": " ".join(
                    value
                    for value in (
                        str(raw.get("title") or ""),
                        str(raw.get("heading") or ""),
                    )
                    if value
                ),
                "markdown": str(raw.get("content") or ""),
                "ocr_text": "",
            }
            candidate = _score_search_row(
                candidate_row,
                terms,
                minimum_matches=max(1, min(2, len(terms) // 4)),
            )
            if candidate is None:
                continue
            candidate["title"] = str(raw.get("title") or "")
            candidate["excerpt"] = search_excerpt(
                str(raw.get("content") or ""), terms, limit=700
            )
            scored.append(candidate)
        scored.sort(
            key=lambda item: (
                -float(item.get("score") or 0.0),
                normalize_search_text(item.get("title") or ""),
                int(item.get("chunk_id") or 0),
            )
        )
        return scored[: max(1, int(limit))]

    def document_chunks(self, document_id: int) -> list[dict[str, Any]]:
        """Return every indexed section for one document with source metadata."""

        with self.connect() as connection:
            rows = connection.execute(
                """SELECT c.id AS chunk_id,c.heading,c.content,c.content_type,
                          c.entities_json,c.content_hash AS chunk_hash,
                          d.id AS document_id,d.source,d.source_origin,d.source_id,d.title,d.url,
                          d.module,d.product,d.category,d.updated_at,d.synced_at,
                          d.local_path,d.review_status,d.classification_confidence
                     FROM knowledge_chunks c
                     JOIN documents d ON d.id=c.document_id
                    WHERE d.id=? AND d.status='active'
                    ORDER BY c.id""",
                (max(0, int(document_id)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_schema_catalog(
        self, query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        terms = search_terms(query)
        if not terms:
            return []
        where = " OR ".join(
            "lower(t.schema_name||'.'||t.table_name||' '||c.column_name) "
            "LIKE ? ESCAPE '\\'"
            for _ in terms
        )
        params = [f"%{_escape_like(term.casefold())}%" for term in terms]
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT t.id AS table_id,t.document_id,t.schema_name,t.table_name,
                            t.description,t.approximate_rows,t.version,
                            group_concat(
                                c.column_name||' '||c.data_type||
                                CASE WHEN c.primary_key=1 THEN ' PK' ELSE '' END,
                                '; '
                            ) AS columns
                       FROM schema_tables t
                       LEFT JOIN schema_columns c ON c.table_id=t.id
                      WHERE {where}
                      GROUP BY t.id
                      LIMIT ?""",
                [*params, max(1, int(limit))],
            ).fetchall()
            results = []
            for row in rows:
                relations = connection.execute(
                    """SELECT * FROM schema_relations
                       WHERE document_id=? AND (
                           (from_schema=? AND from_table=?) OR
                           (to_schema=? AND to_table=?)
                       ) LIMIT 30""",
                    (
                        row["document_id"],
                        row["schema_name"],
                        row["table_name"],
                        row["schema_name"],
                        row["table_name"],
                    ),
                ).fetchall()
                result = dict(row)
                result["relations"] = [dict(item) for item in relations]
                results.append(result)
        return results

    def search(
        self,
        query: str,
        limit: int = 12,
        module: str = "",
        source: str = "",
        include_unvalidated: bool = False,
        excluded_sources: tuple[str, ...] = (),
        source_origin: str = "",
    ) -> list[dict[str, Any]]:
        filters = ["d.status='active'"]
        terms = search_terms(query)
        if not terms:
            return []
        if not include_unvalidated:
            filters.extend(
                [
                    "d.module<>'Revisar'",
                    "d.review_status IN ('approved','kept')",
                ]
            )
        filter_params: list[Any] = []
        if module:
            filters.append("d.module=?")
            filter_params.append(module)
        if source:
            filters.append("d.source=?")
            filter_params.append(source)
        if source_origin:
            filters.append("d.source_origin=?")
            filter_params.append(source_origin)
        excluded_sources = tuple(
            str(item).strip() for item in excluded_sources if str(item).strip()
        )
        if excluded_sources:
            placeholders = ",".join("?" for _ in excluded_sources)
            filters.append(f"d.source NOT IN ({placeholders})")
            filter_params.extend(excluded_sources)
        exact_limit = max(60, min(240, int(limit) * 10))
        broad_limit = max(140, min(500, int(limit) * 24))
        sql = f"""
            SELECT d.*,bm25(knowledge_fts,8.0,1.0,0.8,2.0,1.5,1.5) AS rank
              FROM knowledge_fts
              JOIN documents d ON d.id=knowledge_fts.rowid
             WHERE knowledge_fts MATCH ? AND {' AND '.join(filters)}
             ORDER BY rank LIMIT ?
        """
        rows_by_id: dict[int, dict[str, Any]] = {}
        with self.connect() as connection:
            params = [_fts_and_query(terms), *filter_params, exact_limit]
            for row in connection.execute(sql, params).fetchall():
                rows_by_id[int(row["id"])] = dict(row)
            results = _score_search_rows(rows_by_id.values(), terms)
            _expand_reference_results(
                connection,
                results,
                terms,
                filters,
                filter_params,
            )
            if len(results) < max(1, int(limit)):
                params = [_fts_query(query), *filter_params, broad_limit]
                for row in connection.execute(sql, params).fetchall():
                    rows_by_id.setdefault(int(row["id"]), dict(row))
                results = _score_search_rows(rows_by_id.values(), terms)
                _expand_reference_results(
                    connection,
                    results,
                    terms,
                    filters,
                    filter_params,
                )
        results.sort(
            key=lambda item: (
                -float(item.get("score") or 0.0),
                normalize_search_text(item.get("title") or ""),
            )
        )
        selected = results[: max(1, int(limit))]
        for result in selected:
            result["excerpt"] = search_excerpt(
                result.get("markdown") or str(result.get("ocr_text") or ""),
                terms,
            )
        return selected

    def search_page(
        self,
        query: str,
        *,
        limit: int = 100,
        offset: int = 0,
        module: str = "",
        source: str = "",
        include_unvalidated: bool = False,
        excluded_sources: tuple[str, ...] = (),
        source_origin: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a deterministic FTS page and its uncapped result count."""

        terms = search_terms(query)
        if not terms:
            return [], 0
        filters = ["d.status='active'"]
        if not include_unvalidated:
            filters.extend(
                [
                    "d.module<>'Revisar'",
                    "d.review_status IN ('approved','kept')",
                ]
            )
        filter_params: list[Any] = []
        if module:
            filters.append("d.module=?")
            filter_params.append(module)
        if source:
            filters.append("d.source=?")
            filter_params.append(source)
        if source_origin:
            filters.append("d.source_origin=?")
            filter_params.append(source_origin)
        ignored = tuple(
            str(item).strip() for item in excluded_sources if str(item).strip()
        )
        if ignored:
            placeholders = ",".join("?" for _ in ignored)
            filters.append(f"d.source NOT IN ({placeholders})")
            filter_params.extend(ignored)
        where = " AND ".join(filters)
        match_query = _fts_query(query)
        page_limit = max(1, int(limit))
        page_offset = max(0, int(offset))
        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"""SELECT count(*)
                          FROM knowledge_fts
                          JOIN documents d ON d.id=knowledge_fts.rowid
                         WHERE knowledge_fts MATCH ? AND {where}""",
                    [match_query, *filter_params],
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT d.*,bm25(knowledge_fts,8.0,1.0,0.8,2.0,1.5,1.5) AS rank
                      FROM knowledge_fts
                      JOIN documents d ON d.id=knowledge_fts.rowid
                     WHERE knowledge_fts MATCH ? AND {where}
                     ORDER BY rank, d.title COLLATE NOCASE, d.id
                     LIMIT ? OFFSET ?""",
                [match_query, *filter_params, page_limit, page_offset],
            ).fetchall()
        results = [dict(row) for row in rows]
        for result in results:
            result["excerpt"] = search_excerpt(
                result.get("markdown") or str(result.get("ocr_text") or ""),
                terms,
            )
        return results, total

    def start_sync(self, source: str, source_origin: str = "") -> int:
        origin = source_origin or _default_source_origin(source)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO sync_runs(source,source_origin,started_at,status)
                   VALUES(?,?,?,'running')""",
                (source, origin, utc_now()),
            )
            return _last_insert_id(cursor)

    def finish_sync(self, run_id: int, stats: SyncStats, error: str = "") -> None:
        status = "error" if error else "partial" if stats.errors else "completed"
        with self.connect() as connection:
            connection.execute(
                """UPDATE sync_runs SET finished_at=?,status=?,stats_json=?,error=?
                   WHERE id=?""",
                (
                    utc_now(),
                    status,
                    json.dumps(stats.to_dict(), ensure_ascii=False),
                    error,
                    run_id,
                ),
            )

    def mark_missing_inactive(
        self,
        source: str,
        active_ids: set[str],
        source_origin: str = "",
    ) -> int:
        origin = source_origin or _default_source_origin(source)
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id,source_id FROM documents
                   WHERE source=? AND source_origin=? AND status='active'""",
                (source, origin),
            ).fetchall()
            missing = [row["id"] for row in rows if row["source_id"] not in active_ids]
            if missing:
                connection.executemany(
                    "UPDATE documents SET status='inactive',synced_at=? WHERE id=?",
                    [(utc_now(), row_id) for row_id in missing],
                )
            return len(missing)

    def create_conversation(
        self,
        title: str,
        provider: str,
        model: str,
        workspace: Path,
        cloned_from: str = "",
        effort: str = "medium",
        service_tier: str = "",
        approval_profile: str = "auto",
        collaboration_mode: str = "default",
        vr_enabled: bool = False,
        vr_mode: str = "",
    ) -> str:
        conversation_id = uuid.uuid4().hex
        now = utc_now()
        resolved_mode = str(vr_mode or "").strip().casefold()
        if resolved_mode not in {"off", "vr", "ultra"}:
            resolved_mode = "vr" if vr_enabled else "off"
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO conversations
                   (id,title,provider,model,effort,service_tier,approval_profile,
                    collaboration_mode,vr_enabled,vr_mode,workspace,
                    cloned_from,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    title,
                    provider,
                    model,
                    effort,
                    service_tier,
                    approval_profile,
                    collaboration_mode,
                    int(vr_enabled),
                    resolved_mode,
                    to_portable_path(self.root, workspace) if self.root else str(workspace),
                    cloned_from,
                    now,
                    now,
                ),
            )
        return conversation_id

    def list_conversations(
        self, include_archived: bool = False, state: str = "active"
    ) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if state == "trash":
                where = "trashed_at<>''"
                params: tuple[Any, ...] = ()
            elif include_archived:
                where = "trashed_at=''"
                params = ()
            elif state == "archived":
                where = "archived=1 AND trashed_at=''"
                params = ()
            elif state == "all":
                where = "trashed_at=''"
                params = ()
            else:
                where = "archived=0 AND trashed_at=''"
                params = ()
            return connection.execute(
                f"SELECT * FROM conversations WHERE {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()

    def get_conversation(self, conversation_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()

    def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        allowed = {
            "title", "provider", "model", "effort", "native_id", "native_id_vr",
            "status", "archived",
            "service_tier", "approval_profile", "collaboration_mode", "trashed_at",
            "workspace", "original_workspace", "vr_enabled", "vr_mode",
            "context_used_tokens", "context_window_tokens", "total_processed_tokens",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if self.root:
            for key in ("workspace", "original_workspace"):
                if key in values:
                    values[key] = to_portable_path(self.root, values[key])
        if not values:
            return
        values["updated_at"] = utc_now()
        columns = ", ".join(f"{key}=?" for key in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE conversations SET {columns} WHERE id=?",
                [*values.values(), conversation_id],
            )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        turn_id: str = "",
        edited_from_message_id: int | None = None,
        response_mode: str = "",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO messages
                   (conversation_id,role,content,turn_id,edited_from_message_id,response_mode,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    role,
                    content,
                    turn_id,
                    edited_from_message_id,
                    response_mode,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (utc_now(), conversation_id),
            )
            return _last_insert_id(cursor)

    def add_source_citations(
        self,
        conversation_id: str,
        message_id: int,
        citations: list[dict[str, Any]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM source_citations WHERE message_id=?", (message_id,)
            )
            connection.executemany(
                """INSERT INTO source_citations
                   (conversation_id,document_id,message_id,excerpt)
                   VALUES(?,?,?,?)""",
                [
                    (
                        conversation_id,
                        int(item.get("document_id") or 0) or None,
                        message_id,
                        str(item.get("excerpt") or "")[:4000],
                    )
                    for item in citations
                    if int(item.get("document_id") or 0) > 0
                ],
            )

    def begin_user_turn(self, conversation_id: str, content: str) -> int:
        """Atomically claim an idle active conversation and persist its user turn."""

        now = utc_now()
        with self.connect() as connection:
            claimed = connection.execute(
                """UPDATE conversations SET status='running',updated_at=?
                   WHERE id=? AND status<>'running' AND archived=0 AND trashed_at=''""",
                (now, conversation_id),
            )
            if claimed.rowcount != 1:
                row = connection.execute(
                    "SELECT status,archived,trashed_at FROM conversations WHERE id=?",
                    (conversation_id,),
                ).fetchone()
                if not row:
                    raise KeyError(conversation_id)
                if str(row["status"] or "idle") == "running":
                    raise RuntimeError(
                        "Já existe uma resposta em andamento nesta conversa."
                    )
                raise RuntimeError("A conversa não está ativa para receber mensagens.")
            cursor = connection.execute(
                """INSERT INTO messages
                   (conversation_id,role,content,turn_id,edited_from_message_id,created_at)
                   VALUES(?,'user',?,'',NULL,?)""",
                (conversation_id, content, now),
            )
            return _last_insert_id(cursor)

    def abort_user_turn(self, conversation_id: str, message_id: int) -> None:
        """Undo a turn that failed before an asynchronous provider run started."""

        with self.connect() as connection:
            connection.execute(
                """DELETE FROM messages
                   WHERE id=? AND conversation_id=? AND role='user' AND turn_id=''""",
                (message_id, conversation_id),
            )
            connection.execute(
                """UPDATE conversations SET status='idle',updated_at=?
                   WHERE id=? AND status='running'""",
                (utc_now(), conversation_id),
            )

    def recover_interrupted_conversations(self) -> list[str]:
        """Mark turns that have no runtime owner after application startup."""

        now = utc_now()
        with self.connect() as connection:
            conversation_ids = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM conversations WHERE status='running'"
                ).fetchall()
            ]
            if conversation_ids:
                placeholders = ",".join("?" for _ in conversation_ids)
                connection.execute(
                    f"""UPDATE conversations SET status='interrupted',updated_at=?
                        WHERE id IN ({placeholders})""",
                    (now, *conversation_ids),
                )
                connection.executemany(
                    """INSERT INTO runtime_events
                       (conversation_id,kind,text,payload_json,created_at)
                       VALUES(?,'turn_recovered',?,'{}',?)""",
                    [
                        (
                            conversation_id,
                            "Execução anterior interrompida pelo encerramento da aplicação.",
                            now,
                        )
                        for conversation_id in conversation_ids
                    ],
                )
            return conversation_ids

    def messages(self, conversation_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY id",
                (conversation_id,),
            ).fetchall()

    def update_message_turn(self, message_id: int, turn_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE messages SET turn_id=? WHERE id=?", (turn_id, message_id)
            )

    def messages_through(self, conversation_id: str, message_id: int) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM messages
                   WHERE conversation_id=? AND id<=? ORDER BY id""",
                (conversation_id, message_id),
            ).fetchall()

    def save_approval(self, approval_id: str, conversation_id: str, request: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO approvals
                   (id,conversation_id,request_json,decision,created_at,decided_at)
                   VALUES(?,?,?,'',?,'')""",
                (approval_id, conversation_id, json.dumps(request, ensure_ascii=False), utc_now()),
            )

    def decide_approval(self, approval_id: str, decision: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE approvals SET decision=?,decided_at=? WHERE id=?",
                (decision, utc_now(), approval_id),
            )

    def create_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        executable: str,
        arguments: list[str] | None = None,
        timeout_seconds: int = 60,
        safety: str = "side_effecting",
        tool_id: str = "",
    ) -> str:
        validate_tool_definition(
            name, description, input_schema, executable, arguments or []
        )
        identifier = tool_id or uuid.uuid4().hex
        now = utc_now()
        timeout = min(300, max(1, int(timeout_seconds)))
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO tool_definitions
                   (id,name,description,input_schema_json,executable,arguments_json,
                    timeout_seconds,safety,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, name, description,
                    json.dumps(input_schema, ensure_ascii=False), executable,
                    json.dumps(arguments or [], ensure_ascii=False), timeout,
                    safety if safety in {"read_only", "side_effecting"} else "side_effecting",
                    now, now,
                ),
            )
        return identifier

    def update_tool(self, tool_id: str, **fields: Any) -> None:
        current = next(
            (tool for tool in self.list_tools() if str(tool["id"]) == str(tool_id)),
            None,
        )
        if not current:
            raise KeyError(tool_id)
        candidate = {**current, **fields}
        validate_tool_definition(
            str(candidate["name"]),
            str(candidate["description"]),
            candidate["input_schema"],
            str(candidate["executable"]),
            list(candidate["arguments"]),
        )
        mapping = {
            "name": "name", "description": "description", "executable": "executable",
            "timeout_seconds": "timeout_seconds", "safety": "safety", "enabled": "enabled",
            "input_schema": "input_schema_json", "arguments": "arguments_json",
        }
        values: dict[str, Any] = {}
        for key, column in mapping.items():
            if key not in fields:
                continue
            value = fields[key]
            if key in {"input_schema", "arguments"}:
                value = json.dumps(value, ensure_ascii=False)
            elif key == "timeout_seconds":
                value = min(300, max(1, int(value)))
            elif key == "safety" and value not in {"read_only", "side_effecting"}:
                value = "side_effecting"
            values[column] = value
        if not values:
            return
        values["updated_at"] = utc_now()
        columns = ",".join(f"{column}=?" for column in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE tool_definitions SET {columns} WHERE id=?",
                [*values.values(), tool_id],
            )

    def delete_tool(self, tool_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM conversation_tools WHERE tool_kind='dynamic' AND tool_id=?",
                (tool_id,),
            )
            connection.execute("DELETE FROM tool_definitions WHERE id=?", (tool_id,))

    def list_tools(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tool_definitions"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY name COLLATE NOCASE"
        with self.connect() as connection:
            rows = connection.execute(sql).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["input_schema"] = json.loads(item.pop("input_schema_json") or "{}")
            item["arguments"] = json.loads(item.pop("arguments_json") or "[]")
            result.append(item)
        return result

    def set_conversation_tools(
        self,
        conversation_id: str,
        dynamic_ids: list[str],
        mcp_tools: list[dict[str, str]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM conversation_tools WHERE conversation_id=?", (conversation_id,)
            )
            connection.executemany(
                """INSERT INTO conversation_tools
                   (conversation_id,tool_kind,tool_id) VALUES(?,'dynamic',?)""",
                [(conversation_id, tool_id) for tool_id in dict.fromkeys(dynamic_ids)],
            )
            connection.executemany(
                """INSERT INTO conversation_tools
                   (conversation_id,tool_kind,server_name,tool_name)
                   VALUES(?,'mcp',?,?)""",
                [
                    (conversation_id, item.get("server", ""), item.get("tool", ""))
                    for item in mcp_tools
                    if item.get("server") and item.get("tool")
                ],
            )

    def conversation_tools(self, conversation_id: str) -> dict[str, list[Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_tools WHERE conversation_id=?",
                (conversation_id,),
            ).fetchall()
        return {
            "dynamic": [str(row["tool_id"]) for row in rows if row["tool_kind"] == "dynamic"],
            "mcp": [
                {"server": str(row["server_name"]), "tool": str(row["tool_name"])}
                for row in rows if row["tool_kind"] == "mcp"
            ],
        }

    def latest_event(self, conversation_id: str, kind: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM runtime_events
                   WHERE conversation_id=? AND kind=? ORDER BY id DESC LIMIT 1""",
                (conversation_id, kind),
            ).fetchone()

    def orchestration_events_after(
        self, conversation_id: str, event_id: int
    ) -> list[sqlite3.Row]:
        kinds = (
            "intent_analysis_started",
            "intent_analysis_completed",
            "response_contract_created",
            "agent_started",
            "agent_completed",
            "agent_failed",
            "agent_usage",
            "parallel_group_started",
            "parallel_group_completed",
            "evidence_merge_completed",
            "evidence_validation_completed",
            "critic_completed",
            "validation_started",
            "validation_completed",
            "refinement_requested",
            "refinement_started",
            "refinement_completed",
            "revision_started",
            "synthesis_started",
            "synthesis_completed",
            "final_validation_started",
            "final_validation_completed",
            "response_rewrite_started",
            "response_rewrite_completed",
            "orchestration_completed",
            "orchestration_cancelled",
        )
        placeholders = ",".join("?" for _kind in kinds)
        with self.connect() as connection:
            return connection.execute(
                f"""SELECT * FROM runtime_events
                    WHERE conversation_id=? AND id>? AND kind IN ({placeholders})
                    ORDER BY id""",
                (conversation_id, int(event_id), *kinds),
            ).fetchall()

    def latest_turn_events(self, conversation_id: str) -> list[sqlite3.Row]:
        """Return the persisted events that belong to the latest chat turn.

        Response planning can be emitted before the provider's ``turn_started``
        event, so the previous terminal event is the reliable boundary.
        """

        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM runtime_events
                   WHERE conversation_id=? ORDER BY id DESC LIMIT 1000""",
                (conversation_id,),
            ).fetchall()
        ordered = list(reversed(rows))
        if not ordered:
            return []
        terminal_indexes = [
            index
            for index, row in enumerate(ordered)
            if str(row["kind"] or "")
            in {"turn_completed", "orchestration_cancelled", "turn_recovered"}
        ]
        if not terminal_indexes:
            return ordered
        latest_terminal = terminal_indexes[-1]
        has_events_after_latest = latest_terminal < len(ordered) - 1
        boundary_index = (
            latest_terminal
            if has_events_after_latest
            else (terminal_indexes[-2] if len(terminal_indexes) > 1 else -1)
        )
        return ordered[boundary_index + 1 :]

    def purge_conversation(self, conversation_id: str) -> None:
        with self.connect() as connection:
            for table in (
                "source_citations", "artifacts", "approvals", "runtime_events",
                "conversation_tools", "messages",
            ):
                connection.execute(f"DELETE FROM {table} WHERE conversation_id=?", (conversation_id,))
            connection.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    def add_event(self, event: RuntimeEvent) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO runtime_events
                   (conversation_id,kind,text,payload_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    event.conversation_id,
                    event.kind,
                    event.text,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at,
                ),
            )
            return _last_insert_id(cursor)


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
        r"\[([^]]+)]\((https?://[^\s)]+)(?:\s+[^)]*)?\)", flags=re.I
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

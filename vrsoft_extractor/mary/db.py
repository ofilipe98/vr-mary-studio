from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .chat_tools import validate_tool_definition
from .models import (
    KnowledgeDocument,
    ReviewFilters,
    ReviewPage,
    RuntimeEvent,
    SyncStats,
    utc_now,
)
from .paths import to_portable_path
from .search import (
    infer_search_module,
    matched_search_terms,
    minimum_term_matches,
    normalize_search_text,
    search_excerpt,
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

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
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
    workspace TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    archived INTEGER NOT NULL DEFAULT 0,
    service_tier TEXT NOT NULL DEFAULT '',
    approval_profile TEXT NOT NULL DEFAULT 'auto',
    collaboration_mode TEXT NOT NULL DEFAULT 'default',
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
            connection.executescript(SCHEMA)
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
                ("trashed_at", "TEXT NOT NULL DEFAULT ''"),
                ("original_workspace", "TEXT NOT NULL DEFAULT ''"),
            ):
                self._ensure_column(connection, "conversations", column, definition)
            for column, definition in (
                ("turn_id", "TEXT NOT NULL DEFAULT ''"),
                ("edited_from_message_id", "INTEGER"),
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
                """
            )

    def _backup_before_portable_migration(
        self, connection: sqlite3.Connection
    ) -> None:
        assert self.root is not None
        absolute_pattern = "%:\\%"
        checks = (
            ("documents", "local_path LIKE ? OR assets_json LIKE ?"),
            ("conversations", "workspace LIKE ? OR original_workspace LIKE ?"),
            ("artifacts", "path LIKE ? OR path LIKE ?"),
        )
        has_absolute_paths = any(
            connection.execute(
                f"SELECT 1 FROM {table} WHERE {where} LIMIT 1",
                (absolute_pattern, "%:/%"),
            ).fetchone()
            for table, where in checks
        )
        if not has_absolute_paths:
            return
        backup_path = (
            self.root / ".state" / "backups" / "conhecimento-pre-portable.sqlite"
        )
        if backup_path.exists():
            return
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup_path) as target:
            connection.backup(target)

    def _migrate_portable_paths(self, connection: sqlite3.Connection) -> None:
        assert self.root is not None
        rows = connection.execute(
            "SELECT id,local_path,assets_json FROM documents"
        ).fetchall()
        for row in rows:
            try:
                assets = json.loads(row["assets_json"] or "[]")
            except (TypeError, ValueError):
                assets = []
            local_path = to_portable_path(self.root, row["local_path"])
            portable_assets = [to_portable_path(self.root, item) for item in assets]
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
            for row in connection.execute(f"SELECT {selected} FROM {table}").fetchall():
                values = {column: to_portable_path(self.root, row[column]) for column in columns}
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
                   END""",
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

    def upsert_document(self, document: KnowledgeDocument) -> tuple[int, str]:
        if self.root:
            document.local_path = to_portable_path(self.root, document.local_path)
            document.assets = [
                to_portable_path(self.root, asset) for asset in document.assets
            ]
        current = self.get_document(document.source, document.source_id)
        if current and current["content_hash"] == document.content_hash:
            with self.connect() as connection:
                connection.execute(
                    "UPDATE documents SET synced_at=?, status='active' WHERE id=?",
                    (document.synced_at, current["id"]),
                )
            return int(current["id"]), "unchanged"

        action = "updated" if current else "created"
        with self.connect() as connection:
            if current:
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
                    source,source_id,title,url,module,classification_confidence,
                    review_status,status,category,product,created_at,updated_at,
                    synced_at,revision,content_hash,markdown,ocr_text,local_path,assets_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,source_id) DO UPDATE SET
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
                      WHEN documents.review_status='approved' THEN 'approved'
                      ELSE excluded.review_status END,
                    status=excluded.status,category=excluded.category,product=excluded.product,
                    created_at=excluded.created_at,updated_at=excluded.updated_at,
                    synced_at=excluded.synced_at,revision=excluded.revision,
                    content_hash=excluded.content_hash,markdown=excluded.markdown,
                    ocr_text=excluded.ocr_text,local_path=excluded.local_path,
                    assets_json=excluded.assets_json""",
                (
                    document.source,
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
        return int(row["id"]), action

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
            return True

    def decide_review(self, review_id: int, module: str) -> None:
        self.decide_reviews([review_id], "approve", module=module)

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
        with self.connect() as connection:
            reviews = connection.execute(
                f"""SELECT r.*,d.module AS current_module
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
                if action == "approve":
                    connection.execute(
                        """UPDATE classification_reviews
                           SET status='approved',decided_module=?,decided_at=?,
                               decision_note=?,updated_at=?
                           WHERE id=?""",
                        (destination, now, note.strip(), now, review["id"]),
                    )
                    connection.execute(
                        """UPDATE documents SET module=?,review_status='approved'
                           WHERE id=?""",
                        (destination, review["document_id"]),
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
                        """UPDATE documents SET review_status='approved'
                           WHERE id=?""",
                        (review["document_id"],),
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
                        """UPDATE documents SET review_status='pending'
                           WHERE id=?""",
                        (review["document_id"],),
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
                        """UPDATE documents SET review_status='pending'
                           WHERE id=?""",
                        (review["document_id"],),
                    )
        return len(unique_ids)

    def list_reviews(self) -> list[dict[str, Any]]:
        return self.query_reviews(ReviewFilters(limit=10_000)).items

    def query_reviews(self, filters: ReviewFilters) -> ReviewPage:
        where = ["d.status='active'"]
        params: list[Any] = []
        if filters.status and filters.status != "all":
            where.append("r.status=?")
            params.append(filters.status)
        if filters.source:
            where.append("d.source=?")
            params.append(filters.source)
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
            needle = f"%{filters.query.strip().casefold()}%"
            where.append(
                """lower(
                     d.title || ' ' || d.source_id || ' ' || d.product || ' ' ||
                     d.category || ' ' || r.reasons_json || ' ' || d.markdown ||
                     ' ' || d.ocr_text
                   ) LIKE ?"""
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
            "risk": f"risk_score DESC,r.confidence ASC,r.updated_at DESC,r.id DESC",
            "confidence_desc": "r.confidence DESC,r.updated_at DESC,r.id DESC",
            "confidence_asc": "r.confidence ASC,r.updated_at DESC,r.id DESC",
            "recent": "r.updated_at DESC,r.id DESC",
            "title": "d.title COLLATE NOCASE ASC,r.id DESC",
        }.get(filters.sort, f"risk_score DESC,r.confidence ASC,r.id DESC")
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
            rows = connection.execute(
                f"""SELECT r.*,d.source_id,d.title,d.source,d.url,
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

    def search(
        self,
        query: str,
        limit: int = 12,
        module: str = "",
        source: str = "",
        include_unvalidated: bool = False,
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

    def start_sync(self, source: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO sync_runs(source,started_at,status) VALUES(?,?,'running')",
                (source, utc_now()),
            )
            return int(cursor.lastrowid)

    def finish_sync(self, run_id: int, stats: SyncStats, error: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE sync_runs SET finished_at=?,status=?,stats_json=?,error=?
                   WHERE id=?""",
                (
                    utc_now(),
                    "error" if error else "completed",
                    json.dumps(stats.to_dict(), ensure_ascii=False),
                    error,
                    run_id,
                ),
            )

    def mark_missing_inactive(self, source: str, active_ids: set[str]) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,source_id FROM documents WHERE source=? AND status='active'",
                (source,),
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
    ) -> str:
        conversation_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO conversations
                   (id,title,provider,model,effort,service_tier,approval_profile,
                    collaboration_mode,workspace,cloned_from,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    title,
                    provider,
                    model,
                    effort,
                    service_tier,
                    approval_profile,
                    collaboration_mode,
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
            "title", "provider", "model", "effort", "native_id", "status", "archived",
            "service_tier", "approval_profile", "collaboration_mode", "trashed_at",
            "workspace", "original_workspace",
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
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO messages
                   (conversation_id,role,content,turn_id,edited_from_message_id,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (
                    conversation_id,
                    role,
                    content,
                    turn_id,
                    edited_from_message_id,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (utc_now(), conversation_id),
            )
            return int(cursor.lastrowid)

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
            return int(cursor.lastrowid)


def _fts_query(query: str) -> str:
    return " OR ".join(_fts_literal(term) for term in search_terms(query))


def _fts_and_query(terms: list[str]) -> str:
    return " AND ".join(_fts_literal(term) for term in terms)


def _fts_literal(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _score_search_row(
    row: dict[str, Any], terms: list[str]
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
    if len(matched) < minimum_term_matches(len(terms)):
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

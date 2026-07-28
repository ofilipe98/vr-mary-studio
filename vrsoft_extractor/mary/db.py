from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import KnowledgeDocument, RuntimeEvent, SyncStats, utc_now


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
    decided_at TEXT NOT NULL DEFAULT ''
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
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_column(
                connection,
                "conversations",
                "effort",
                "TEXT NOT NULL DEFAULT 'medium'",
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

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
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
                    title=excluded.title,url=excluded.url,module=excluded.module,
                    classification_confidence=excluded.classification_confidence,
                    review_status=CASE
                      WHEN documents.review_status='approved'
                           AND documents.module<>excluded.module THEN 'pending'
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
    ) -> None:
        with self.connect() as connection:
            exists = connection.execute(
                """SELECT 1 FROM classification_reviews
                   WHERE document_id=? AND status='pending'""",
                (document_id,),
            ).fetchone()
            if not exists:
                connection.execute(
                    """INSERT INTO classification_reviews
                       (document_id,suggested_module,previous_module,confidence,reasons_json)
                       VALUES(?,?,?,?,?)""",
                    (
                        document_id,
                        suggested_module,
                        previous_module,
                        confidence,
                        json.dumps(reasons, ensure_ascii=False),
                    ),
                )

    def decide_review(self, review_id: int, module: str) -> None:
        with self.connect() as connection:
            review = connection.execute(
                "SELECT document_id FROM classification_reviews WHERE id=?",
                (review_id,),
            ).fetchone()
            if not review:
                raise KeyError(f"Revisão inexistente: {review_id}")
            now = utc_now()
            connection.execute(
                """UPDATE classification_reviews SET status='approved',
                   decided_module=?,decided_at=? WHERE id=?""",
                (module, now, review_id),
            )
            connection.execute(
                """UPDATE documents SET module=?,review_status='approved'
                   WHERE id=?""",
                (module, review["document_id"]),
            )

    def list_reviews(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """SELECT r.*,d.title,d.source,d.url FROM classification_reviews r
                   JOIN documents d ON d.id=r.document_id
                   WHERE r.status='pending' ORDER BY r.confidence DESC"""
            ).fetchall()

    def search(
        self,
        query: str,
        limit: int = 12,
        module: str = "",
        source: str = "",
    ) -> list[dict[str, Any]]:
        filters = ["d.status='active'"]
        fts_query = _fts_query(query)
        if not fts_query:
            return []
        params: list[Any] = [fts_query]
        if module:
            filters.append("d.module=?")
            params.append(module)
        if source:
            filters.append("d.source=?")
            params.append(source)
        params.append(limit)
        sql = f"""
            SELECT d.*,bm25(knowledge_fts,8.0,1.0,0.8,2.0,1.5,1.5) AS rank,
                   snippet(knowledge_fts,1,'<mark>','</mark>',' … ',28) AS excerpt
            FROM knowledge_fts
            JOIN documents d ON d.id=knowledge_fts.rowid
            WHERE knowledge_fts MATCH ? AND {' AND '.join(filters)}
            ORDER BY rank LIMIT ?
        """
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

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
    ) -> str:
        conversation_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO conversations
                   (id,title,provider,model,effort,workspace,cloned_from,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    title,
                    provider,
                    model,
                    effort,
                    str(workspace),
                    cloned_from,
                    now,
                    now,
                ),
            )
        return conversation_id

    def list_conversations(self, include_archived: bool = False) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM conversations WHERE archived IN (0,?)
                   ORDER BY updated_at DESC""",
                (1 if include_archived else 0,),
            ).fetchall()

    def get_conversation(self, conversation_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()

    def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        allowed = {"title", "model", "effort", "native_id", "status", "archived"}
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return
        values["updated_at"] = utc_now()
        columns = ", ".join(f"{key}=?" for key in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE conversations SET {columns} WHERE id=?",
                [*values.values(), conversation_id],
            )

    def add_message(self, conversation_id: str, role: str, content: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO messages(conversation_id,role,content,created_at)
                   VALUES(?,?,?,?)""",
                (conversation_id, role, content, utc_now()),
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
    stopwords = {
        "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
        "e", "em", "na", "nas", "no", "nos", "o", "os", "para", "por", "que",
        "um", "uma", "mary",
    }
    words = [
        word.lower()
        for word in re.findall(r"[\w-]{2,}", query, flags=re.UNICODE)
        if word.lower() not in stopwords
    ]
    unique = list(dict.fromkeys(words))[:12]
    return " OR ".join('"' + word.replace('"', '""') + '"' for word in unique)

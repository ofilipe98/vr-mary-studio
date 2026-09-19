from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import utc_now
from .paths import to_portable_path
from .repositories.common import (
    SCHEMA,
    _fts_query as _fts_query,
    _review_reasons,
    _review_signature,
)
from .repositories.conversations import ConversationsRepositoryMixin
from .repositories.knowledge import KnowledgeRepositoryMixin


class MaryDatabase(KnowledgeRepositoryMixin, ConversationsRepositoryMixin):
    """Database lifecycle and shared transactions for the repository methods."""

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
                ("approval_profile", "TEXT NOT NULL DEFAULT 'supervised'"),
                ("collaboration_mode", "TEXT NOT NULL DEFAULT 'default'"),
                ("vr_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("vr_mode", "TEXT NOT NULL DEFAULT ''"),
                ("native_id_vr", "TEXT NOT NULL DEFAULT ''"),
                ("native_tools_id", "TEXT NOT NULL DEFAULT ''"),
                ("native_tools_id_vr", "TEXT NOT NULL DEFAULT ''"),
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
                ("execution_ordinal", "INTEGER NOT NULL DEFAULT 0"),
                ("message_status", "TEXT NOT NULL DEFAULT ''"),
                ("execution_id", "INTEGER NOT NULL DEFAULT 0"),
                ("message_phase", "TEXT NOT NULL DEFAULT ''"),
                ("start_event_id", "INTEGER NOT NULL DEFAULT 0"),
            ):
                self._ensure_column(connection, "messages", column, definition)
            connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_assistant_execution_message
                                  ON messages(conversation_id,execution_id,execution_ordinal)
                                  WHERE role='assistant' AND execution_id>0 AND execution_ordinal>0""")
            self._ensure_column(connection, "conversations", "active_execution_id", "INTEGER NOT NULL DEFAULT 0")
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
            for column, definition in (
                ("source", "TEXT NOT NULL DEFAULT 'document'"),
                ("evidence_id", "TEXT NOT NULL DEFAULT ''"),
                ("provenance", "TEXT NOT NULL DEFAULT ''"),
                ("metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("title", "TEXT NOT NULL DEFAULT ''"),
            ):
                self._ensure_column(
                    connection,
                    "source_citations",
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

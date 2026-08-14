from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from .config import MarySettings
from .db import MaryDatabase
from .models import KnowledgeDocument, SyncStats, utc_now


Progress = Callable[[str], None]


class SchemaSync:
    """Index the local SchemaVR markdown without modifying the source file."""

    def __init__(
        self,
        settings: MarySettings,
        database: MaryDatabase,
        progress: Progress | None = None,
        *,
        schema_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.progress = progress or (lambda _message: None)
        self._schema_path = (
            Path(schema_path).expanduser().resolve(strict=False)
            if schema_path is not None
            else None
        )

    @property
    def schema_path(self) -> Path:
        return self._schema_path or (
            self.settings.root / "agentes" / "SchemaVR" / "schema.md"
        )

    def sync(self) -> SyncStats:
        stats = SyncStats("schema")
        run_id = self.database.start_sync("schema")
        try:
            path = self.schema_path
            if not path.is_file():
                raise FileNotFoundError(
                    f"Schema VR não encontrado em {path}."
                )
            self.progress("SCHEMA: lendo tabelas, campos e relacionamentos locais.")
            content = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            modified = path.stat().st_mtime
            document = KnowledgeDocument(
                source="schema",
                source_id="postgresql-vr",
                title="Schema PostgreSQL VR",
                url="",
                markdown=content,
                module="Multimodulo",
                classification_confidence=1.0,
                review_status="approved",
                status="active",
                updated_at=str(modified),
                synced_at=utc_now(),
                revision=digest[:16],
                content_hash=digest,
                category="Banco de dados / Schema PostgreSQL",
                product="VR",
                local_path=self.settings.relative_path(path),
            )
            stats.discovered = 1
            _document_id, action = self.database.upsert_document(document)
            if action == "created":
                stats.created = 1
            elif action == "updated":
                stats.updated = 1
            else:
                stats.unchanged = 1
            self.progress(f"SCHEMA: índice local {action}.")
            self.database.finish_sync(run_id, stats)
            return stats
        except Exception as exc:
            stats.errors = 1
            self.database.finish_sync(run_id, stats, str(exc))
            raise

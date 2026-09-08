from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any
from ..content import target_path, write_document
from ..knowledge import split_knowledge_document
from ..models import (
    KnowledgeDocument,
    ReviewFilters,
    ReviewPage,
    SyncStats,
    utc_now,
)
from ..paths import resolve_portable_path, to_portable_path
from ..search import (
    normalize_search_text,
    search_excerpt,
    search_terms,
)
from ..schema_catalog import parse_schema_markdown

from .common import (
    _default_source_origin,
    _escape_like,
    _review_signature,
    _fts_query,
    _last_insert_id,
    _fts_and_query,
    _score_search_row,
    _score_search_rows,
    _expand_reference_results,
    REVIEW_MODULES,
    REVIEW_ACTIONS,
    LOGGER,
)

class KnowledgeRepositoryMixin:
    """Knowledge operations sharing MaryDatabase's state and transactions."""

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
        revision: str = "",
        product: str = "",
    ) -> list[dict[str, Any]]:
        terms = search_terms(query)
        if not terms:
            return []
        filters = ["d.status='active'"]
        params: list[Any] = []
        for key, value in (("revision", revision), ("product", product)):
            if value:
                filters.append("d.product IN ('',?)" if key == "product" else f"d.{key}=?")
                params.append(value)
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
        revision: str = "",
        product: str = "",
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
        for key, value in (("revision", revision), ("product", product)):
            if value:
                filters.append("d.product IN ('',?)" if key == "product" else f"d.{key}=?")
                filter_params.append(value)
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

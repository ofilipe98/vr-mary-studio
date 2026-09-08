"""
Local semantic vector index for VR Mary Studio.

Provides chunking, incremental embedding storage in SQLite, and cosine
similarity search over text chunks without external vector database dependencies.
"""

from __future__ import annotations

import hashlib
import math
import logging
import re
import sqlite3
import struct
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .embedding_contract import (
    DeterministicHashEmbedding,
    EmbeddingBackend,
    cosine_similarity,
)

LOGGER = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunk_text(text: str, max_chunk_chars: int = 600, overlap_chars: int = 100) -> list[str]:
    """Split text into semantic paragraphs/sections respecting markdown and line boundaries."""
    normalized = str(text or "").strip()
    max_chunk_chars = max(1, int(max_chunk_chars))
    overlap_chars = max(0, min(int(overlap_chars), max_chunk_chars // 4))
    if not normalized:
        return []

    if len(normalized) <= max_chunk_chars:
        return [normalized]

    # Split by double newline (paragraphs) or markdown headers
    raw_blocks = re.split(r"(?:\r?\n){2,}|(?=^#{1,4}\s)", normalized, flags=re.MULTILINE)
    blocks = [b.strip() for b in raw_blocks if b.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        if current_len + len(block) > max_chunk_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(block)
        current_len += len(block)

    if current:
        chunks.append("\n\n".join(current))

    # Fallback if any single chunk is excessively long: split by sentences
    final_chunks: list[str] = []
    for c in chunks:
        if len(c) <= max_chunk_chars:
            final_chunks.append(c)
        else:
            sentences = re.split(r"(?<=[.!?])\s+", c)
            sub = []
            sub_len = 0
            for s in sentences:
                if sub_len + len(s) > max_chunk_chars and sub:
                    final_chunks.append(" ".join(sub))
                    sub = []
                    sub_len = 0
                sub.append(s)
                sub_len += len(s)
            if sub:
                final_chunks.append(" ".join(sub))

    bounded: list[str] = []
    for chunk in final_chunks:
        start = 0
        while start < len(chunk):
            bounded.append(chunk[start:start + max_chunk_chars])
            if start + max_chunk_chars >= len(chunk):
                break
            start += max_chunk_chars - overlap_chars
    return bounded


class SemanticIndex:
    """SQLite-backed dense vector index with incremental chunk updating."""

    def __init__(
        self,
        db_path: Path | str,
        backend: EmbeddingBackend | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backend = backend or DeterministicHashEmbedding()
        self.ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        """Initialize semantic index tables and indices."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS semantic_embeddings (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    chunk_hash TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_semantic_doc
                ON semantic_embeddings(doc_id);

                CREATE INDEX IF NOT EXISTS idx_semantic_hash
                ON semantic_embeddings(chunk_hash);
            """)

    def index_document(
        self,
        doc_id: str,
        text: str,
        *,
        max_chunk_chars: int = 600,
    ) -> int:
        """
        Chunk and index a document incrementally.
        Returns the number of new/updated embeddings computed.
        """
        chunks = chunk_text(text, max_chunk_chars=max_chunk_chars)
        if not chunks:
            with self._connect() as conn:
                conn.execute("DELETE FROM semantic_embeddings WHERE doc_id = ?", (doc_id,))
            return 0

        computed_count = 0
        dim = self.backend.dimension
        model_name = self.backend.model_name
        now = utc_now_iso()

        with self._connect() as conn:
            # Get existing chunk hashes for this doc
            existing_rows = conn.execute(
                "SELECT chunk_id, chunk_hash, model_name, dimension FROM semantic_embeddings WHERE doc_id = ?",
                (doc_id,),
            ).fetchall()
            existing_map = {r["chunk_id"]: (r["chunk_hash"], r["model_name"], r["dimension"]) for r in existing_rows}

            current_chunk_ids: set[str] = set()

            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}:{i}"
                current_chunk_ids.add(chunk_id)
                chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()

                # Incremental check: if chunk text and model are identical, skip computing vector
                if (
                    chunk_id in existing_map
                    and existing_map[chunk_id][0] == chunk_hash
                    and existing_map[chunk_id][1] == model_name
                    and existing_map[chunk_id][2] == dim
                ):
                    continue

                # Compute dense vector
                vector = self.backend.embed_text(chunk)
                if len(vector) != dim or not all(math.isfinite(v) for v in vector):
                    raise ValueError("Embedding inválido: dimensão ou valores não finitos")
                vector_blob = struct.pack(f"{dim}f", *vector)

                conn.execute(
                    """
                    INSERT INTO semantic_embeddings (
                        chunk_id, doc_id, chunk_index, text, chunk_hash,
                        dimension, model_name, vector_blob, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        text = excluded.text,
                        chunk_hash = excluded.chunk_hash,
                        dimension = excluded.dimension,
                        model_name = excluded.model_name,
                        vector_blob = excluded.vector_blob,
                        updated_at = excluded.updated_at
                    """,
                    (
                        chunk_id,
                        doc_id,
                        i,
                        chunk,
                        chunk_hash,
                        dim,
                        model_name,
                        vector_blob,
                        now,
                    ),
                )
                computed_count += 1

            # Remove stale chunks if document shrank
            stale_ids = set(existing_map.keys()) - current_chunk_ids
            if stale_ids:
                placeholders = ",".join("?" * len(stale_ids))
                conn.execute(
                    f"DELETE FROM semantic_embeddings WHERE chunk_id IN ({placeholders})",
                    tuple(stale_ids),
                )

        return computed_count

    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = -1.0,
    ) -> list[tuple[str, float]]:
        """
        Search indexed chunks by vector cosine similarity to the query.
        Returns deduplicated (doc_id, max_similarity) sorted descending by score.
        """
        norm_query = str(query or "").strip()
        if not norm_query or limit <= 0:
            return []

        query_vec = self.backend.embed_text(norm_query)
        dim = self.backend.dimension
        model_name = self.backend.model_name
        if len(query_vec) != dim or not all(math.isfinite(v) for v in query_vec):
            raise ValueError("Embedding de consulta inválido")

        doc_max_scores: dict[str, float] = {}

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT doc_id, vector_blob
                FROM semantic_embeddings
                WHERE model_name = ? AND dimension = ?
                """,
                (model_name, dim),
            ).fetchall()

            for row in rows:
                doc_id = row["doc_id"]
                blob = row["vector_blob"]
                if len(blob) != dim * 4:
                    continue
                vec = struct.unpack(f"{dim}f", blob)
                score = cosine_similarity(query_vec, vec)
                if score >= min_score:
                    if doc_id not in doc_max_scores or score > doc_max_scores[doc_id]:
                        doc_max_scores[doc_id] = score

        ranked = sorted(doc_max_scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:limit]

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM semantic_embeddings")

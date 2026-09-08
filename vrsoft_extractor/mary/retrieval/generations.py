"""Immutable vector generations with an atomic active pointer and scoped readers."""
from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
import struct
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Sequence

from .embedding_contract import EmbeddingBackend, cosine_similarity
from .semantic_index import chunk_text

CHUNKER = "paragraph-600-overlap100-v2"


def document_signature(row: dict) -> str:
    return hashlib.sha256(json.dumps({k: row.get(k, "") for k in (
        "id", "source", "source_id", "source_origin", "module", "product", "revision", "status", "review_status", "title", "markdown", "url", "local_path")},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class GenerationSemanticIndex:
    def __init__(self, path: Path, backend: EmbeddingBackend):
        self.db_path, self.backend = path, backend
        path.parent.mkdir(parents=True, exist_ok=True)
        self._build_lock = threading.Lock()
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS vector_generations(id TEXT PRIMARY KEY,model TEXT,chunker TEXT,status TEXT);
                CREATE TABLE IF NOT EXISTS vector_active(singleton INTEGER PRIMARY KEY CHECK(singleton=1),generation TEXT);
                INSERT OR IGNORE INTO vector_active VALUES(1,'');
                CREATE TABLE IF NOT EXISTS vector_chunks(
                    generation TEXT,doc_id TEXT,chunk INTEGER,source TEXT,origin TEXT,module TEXT,product TEXT,revision TEXT,
                    content_hash TEXT,text TEXT,vector BLOB,PRIMARY KEY(generation,doc_id,chunk));
                CREATE INDEX IF NOT EXISTS vector_scope ON vector_chunks(generation,source,origin,module,product,revision);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def rebuild(self, documents: Sequence[dict], progress: Callable[[int, int], None] | None = None) -> dict:
        with self._build_lock:
            return self._rebuild(documents, progress)

    def _rebuild(self, documents, progress):
        generation = uuid.uuid4().hex
        with self.connect() as conn:
            previous = conn.execute("SELECT generation FROM vector_active WHERE singleton=1").fetchone()[0]
            compatible = conn.execute("SELECT 1 FROM vector_generations WHERE id=? AND model=? AND chunker=?",
                                      (previous, self.backend.model_name, CHUNKER)).fetchone()
            old = {(r["doc_id"], r["chunk"]): dict(r) for r in conn.execute("SELECT * FROM vector_chunks WHERE generation=?", (previous,))} if compatible else {}
            conn.execute("INSERT INTO vector_generations VALUES(?,?,?,'building')", (generation, self.backend.model_name, CHUNKER))
        computed, reused = 0, 0
        try:
            for index, row in enumerate(documents):
                doc_id = f"{row['source']}:{row['source_id']}"
                signature = document_signature(row)
                chunks = chunk_text(str(row.get("title", "")) + "\n" + str(row.get("markdown", "")))
                records = []
                for ordinal, text in enumerate(chunks):
                    saved = old.get((doc_id, ordinal))
                    if saved and saved["text"] == text:
                        blob = saved["vector"]
                        reused += 1
                    else:
                        vector = self.backend.embed_text(text)
                        import math
                        if len(vector) != self.backend.dimension or not all(math.isfinite(v) for v in vector):
                            raise ValueError("Vetor incompatível")
                        blob = struct.pack(f"<{len(vector)}f", *vector)
                        computed += 1
                    records.append((generation, doc_id, ordinal, row["source"], row.get("source_origin", ""), row.get("module", ""),
                                    row.get("product", ""), row.get("revision", ""), signature, text, blob))
                with self.connect() as conn:
                    conn.executemany("INSERT INTO vector_chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)", records)
                if progress:
                    progress(index + 1, len(documents))
            with self.connect() as conn:
                # Another process may have published while this generation was encoding.
                updated = conn.execute("UPDATE vector_active SET generation=? WHERE singleton=1 AND generation=?", (generation, previous))
                if updated.rowcount != 1:
                    raise RuntimeError("Outra geração foi publicada; reindexação deve ser repetida.")
                conn.execute("UPDATE vector_generations SET status='ready' WHERE id=?", (generation,))
                # WAL readers retain their coherent snapshot while obsolete generations disappear.
                conn.execute("DELETE FROM vector_chunks WHERE generation IN (SELECT id FROM vector_generations WHERE id<>? AND status='ready')", (generation,))
                conn.execute("DELETE FROM vector_generations WHERE id<>? AND status='ready'", (generation,))
        except BaseException:
            with self.connect() as conn:
                conn.execute("DELETE FROM vector_chunks WHERE generation=?", (generation,))
                conn.execute("DELETE FROM vector_generations WHERE id=?", (generation,))
            raise
        return {"generation": generation, "computed": computed, "reused": reused, "documents": len(documents)}

    def search(self, query: str, limit: int = 10, *, source: str = "", origins: Sequence[str] = (),
               module: str = "", product: str = "", revision: str = "") -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        with self.connect() as conn:
            conn.execute("BEGIN")
            generation = conn.execute("SELECT generation FROM vector_active WHERE singleton=1").fetchone()[0]
            if not conn.execute("SELECT 1 FROM vector_generations WHERE id=? AND model=? AND chunker=? AND status='ready'",
                                (generation, self.backend.model_name, CHUNKER)).fetchone():
                raise ValueError("Índice semântico ausente ou incompatível; busca textual mantida.")
            where, params = ["generation=?"], [generation]
            for key, value in (("source", source), ("module", module), ("product", product), ("revision", revision)):
                if value:
                    where.append("product IN ('',?)" if key == "product" else f"{key}=?")
                    params.append(value)
            if origins:
                where.append("origin IN (" + ",".join("?" for _ in origins) + ")")
                params.extend(origins)
            vector = getattr(self.backend, "embed_query", self.backend.embed_text)(query)
            unpack = struct.Struct(f"<{self.backend.dimension}f").unpack
            # Keep only the best chunk per document; do not copy and sort every
            # chunk's text/vector just to discard duplicates after ranking.
            best = {}
            for row in conn.execute("SELECT * FROM vector_chunks WHERE " + " AND ".join(where), params):
                score = cosine_similarity(vector, unpack(row["vector"]))
                previous = best.get(row["doc_id"])
                if previous is None or (-score, row["chunk"]) < (-previous[1], previous[0]["chunk"]):
                    best[row["doc_id"]] = (row, score)
        ranked = heapq.nsmallest(limit, best.values(), key=lambda item: (-item[1], item[0]["doc_id"], item[0]["chunk"]))
        return [{**dict(row), "score": score} for row, score in ranked]

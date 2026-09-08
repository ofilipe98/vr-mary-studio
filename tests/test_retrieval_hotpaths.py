"""Cache invalidation and ranking regressions using isolated SQLite databases."""

import sqlite3
import struct

import pytest

from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.mary.retrieval import RetrievalService
from vrsoft_extractor.mary.retrieval.embedding_contract import DeterministicHashEmbedding
from vrsoft_extractor.mary.retrieval.generations import GenerationSemanticIndex


@pytest.fixture
def service(tmp_path):
    db = MaryDatabase(tmp_path / "knowledge.sqlite")
    db.upsert_document(KnowledgeDocument(
        "wiki", "one", "Invoice", "https://example.invalid/one",
        markdown="Original evidence", module="Fiscal", review_status="approved",
    ))
    return RetrievalService(KnowledgeRouter(db, tmp_path))


@pytest.mark.parametrize("column,value", [
    ("markdown", "Original evidence" + "x" * 20_000 + "changed at the end"),
    ("review_status", "pending"),
    ("status", "inactive"),
    ("source_origin", "endoo"),
    ("revision", "r2"),
    ("local_path", "moved/document.md"),
])
def test_signature_invalidates_after_external_document_update(service, column, value):
    before = service.scope_signature()
    # Deliberately bypass the repository: another process may write the same DB.
    with sqlite3.connect(service.router.database.path) as conn:
        conn.execute(f"UPDATE documents SET {column}=?", (value,))
    assert service.scope_signature() != before


def test_signature_tracks_insert_delete_and_origin_permissions(service):
    db = service.router.database
    original = service.scope_signature()
    doc_id, _ = db.upsert_document(KnowledgeDocument(
        "wiki", "two", "Endoo", "", source_origin="endoo", markdown="More evidence",
    ))
    inserted = service.scope_signature()
    assert inserted != original
    service.router.disabled_origins = frozenset({"endoo"})
    assert service.scope_signature() != inserted
    with db.connect() as conn:
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    assert service.scope_signature() == original


def test_signature_reuses_content_hashes_during_chat_and_after_rollback(service, monkeypatch):
    import vrsoft_extractor.mary.retrieval.service as module

    calls = []
    original = module.document_signature

    def record(row):
        calls.append(row["source_id"])
        return original(row)

    monkeypatch.setattr(module, "document_signature", record)
    signature = service.scope_signature()
    assert calls == ["one"]
    db = service.router.database
    cid = db.create_conversation("Chat", "codex", "model", db.path.parent)
    db.begin_user_turn(cid, "question")
    with pytest.raises(RuntimeError, match="rollback"):
        with db.connect() as conn:
            conn.execute("UPDATE documents SET markdown='uncommitted'")
            raise RuntimeError("rollback")
    assert service.scope_signature() == signature
    assert calls == ["one"]


@pytest.mark.parametrize("limit", [0, 1, 3, 10])
def test_semantic_ranking_keeps_best_chunk_and_deterministic_ties(tmp_path, monkeypatch, limit):
    backend = DeterministicHashEmbedding(dimension=16)
    monkeypatch.setattr(backend, "embed_text", lambda _: [1.0] + [0.0] * 15)
    index = GenerationSemanticIndex(tmp_path / "vectors.sqlite", backend)
    generation = index.rebuild([])["generation"]
    chunks = [
        ("z", 0, (0, 1)), ("a", 2, (1, 0)), ("b", 0, (1, 0)),
        ("a", 0, (0, 1)), ("c", 0, (-1, 0)), ("a", 1, (1, 0)),
        ("d", 0, (0, 0)),
    ]
    with index.connect() as conn:
        conn.executemany("INSERT INTO vector_chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
            (generation, doc, chunk, "wiki", "vrwiki", "Fiscal", "", "", "hash", doc,
             struct.pack("<16f", *vector, *([0.0] * 14)))
            for doc, chunk, vector in chunks
        ])
    result = index.search("query", limit)
    expected = [("a", 1, 1.0), ("b", 0, 1.0), ("d", 0, 0.0), ("z", 0, 0.0), ("c", 0, -1.0)]
    assert [(r["doc_id"], r["chunk"], r["score"]) for r in result] == expected[:limit]


def test_generation_connection_rolls_back_and_closes_on_error(tmp_path):
    index = GenerationSemanticIndex(tmp_path / "vectors.sqlite", DeterministicHashEmbedding())
    with pytest.raises(RuntimeError, match="rollback"):
        with index.connect() as conn:
            conn.execute("INSERT INTO vector_generations VALUES('failed','model','chunker','building')")
            raise RuntimeError("rollback")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")
    with index.connect() as reopened:
        assert reopened.execute("SELECT count(*) FROM vector_generations").fetchone()[0] == 0

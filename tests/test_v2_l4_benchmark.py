"""Retrieval quality on the frozen corpus and embedding behavior."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

import pytest

from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.mary.retrieval import (
    DeterministicHashEmbedding,
    EmbeddingBackend,
    FallbackEmbeddingBackend,
    cosine_similarity,
    evaluate_retrieval,
)


class TestEmbeddingContracts:
    def test_deterministic_hash_embedding_properties(self) -> None:
        backend = DeterministicHashEmbedding(dimension=128)
        assert backend.dimension == 128
        assert "128" in backend.model_name

        text_a = "Apuração de ICMS e SPED Fiscal"
        text_b = "Apuração de ICMS e SPED Fiscal"
        text_c = "Procedimento de cancelamento de cupom no PDV"

        vec_a = backend.embed_text(text_a)
        vec_b = backend.embed_text(text_b)
        vec_c = backend.embed_text(text_c)

        # Determinism: identical texts produce identical vectors
        assert vec_a == vec_b

        # Unit norm: ||v|| = 1.0 within floating point precision
        norm_a = math.sqrt(sum(x * x for x in vec_a))
        norm_c = math.sqrt(sum(x * x for x in vec_c))
        assert pytest.approx(norm_a, rel=1e-5) == 1.0
        assert pytest.approx(norm_c, rel=1e-5) == 1.0

        # Cosine similarity of identical texts is 1.0
        assert pytest.approx(cosine_similarity(vec_a, vec_b), rel=1e-5) == 1.0

        # Cosine similarity of different texts is strictly less than 1.0
        sim_ac = cosine_similarity(vec_a, vec_c)
        assert sim_ac < 0.95

        # Empty string handling
        vec_empty = backend.embed_text("")
        assert len(vec_empty) == 128

    def test_fallback_embedding_backend_graceful_degradation(self) -> None:
        class FailingPrimary(EmbeddingBackend):
            @property
            def dimension(self) -> int:
                raise RuntimeError("Primary model broken")

            @property
            def model_name(self) -> str:
                return "broken-model"

            def embed_text(self, text: str) -> list[float]:
                raise ConnectionError("Ollama or remote API unreachable")

        fallback = DeterministicHashEmbedding(dimension=64)
        wrapper = FallbackEmbeddingBackend(primary=FailingPrimary(), fallback=fallback)

        # A configured model failure must not mix vector spaces in a persisted index.
        with pytest.raises(RuntimeError, match="Primary model broken"):
            _ = wrapper.dimension
        with pytest.raises(ConnectionError):
            wrapper.embed_text("teste")
        wrapper = FallbackEmbeddingBackend(primary=None, fallback=fallback)
        assert wrapper.dimension == 64
        vec = wrapper.embed_text("teste de contingência")
        assert len(vec) == 64
        assert pytest.approx(math.sqrt(sum(x * x for x in vec)), rel=1e-5) == 1.0


class TestSearchBenchmarkBaseline:
    @pytest.fixture
    def corpus_data(self) -> dict:
        corpus_path = Path(__file__).parent.parent / "vrsoft_extractor" / "mary" / "retrieval" / "benchmark_corpus.json"
        with open(corpus_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @pytest.fixture
    def indexed_database(self, tmp_path: Path, corpus_data: dict) -> MaryDatabase:
        db_path = tmp_path / "benchmark.db"
        db = MaryDatabase(db_path, root=tmp_path)
        for doc in corpus_data["documents"]:
            db.upsert_document(
                KnowledgeDocument(
                    source=doc["source"],
                    source_id=doc["id"],
                    source_origin="vrwiki" if doc["source"] == "wiki" else doc["source"],
                    title=doc["title"],
                    url=f"https://vr.internal/{doc['id']}",
                    markdown=f"# {doc['title']}\n\n{doc['text']}",
                    module=doc["module"],
                    review_status="approved",
                    content_hash=f"hash-{doc['id']}",
                )
            )
        return db

    def test_lexical_retrieval_meets_frozen_corpus_quality(
        self,
        corpus_data: dict,
        indexed_database: MaryDatabase,
    ) -> None:
        assert len(corpus_data["queries"]) >= 30
        assert len(corpus_data["documents"]) >= 10

        # Baseline search function using database search
        def db_search(query: str, limit: int = 10) -> Sequence[str]:
            results = indexed_database.search(query, limit=limit)
            return [str(r["source_id"]) for r in results]

        metrics = evaluate_retrieval(db_search, corpus_data, k=10)

        assert metrics["query_count"] == 30
        assert metrics["mean_recall"] > 0.30  # Baseline lexical FTS achieves ~0.40 on queries with typos
        assert metrics["mean_mrr"] > 0.40

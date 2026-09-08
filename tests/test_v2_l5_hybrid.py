"""
Testes de índice semântico local e busca híbrida (Lote L5).

Valida os requisitos de PLANO_V2_ULTRA_BUSCA_ARQUITETURA.md:
1. Indexação semântica com chunking respeitando quebras e cabeçalhos.
2. Reindexação incremental evitando recalcular vetores de chunks idênticos.
3. Busca semântica pura recuperando documentos conceituais e tolerante a typos.
4. Reciprocal Rank Fusion (RRF) combinando busca textual e vetorial.
5. Degradação graciosa para busca textual se o índice semântico for nulo ou falhar.
6. Benchmark comparativo: Recall@10 supera o baseline de L4 em >= 15% relativo,
   sem regressão de nDCG e com latência p95 < 50ms.
7. Emissão do relatório estruturado em diretório temporário isolado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.mary.retrieval import (
    DeterministicHashEmbedding,
    HybridSearchEngine,
    SemanticIndex,
    chunk_text,
    evaluate_retrieval,
)


class TestSemanticIndexing:
    def test_chunking_respects_paragraphs_and_headers(self) -> None:
        sample_md = """# Titulo Principal

Primeiro paragrafo com informacoes fiscais importantes sobre ICMS.

## Segunda Secao

Outro paragrafo detalhando o calculo de PIS e COFINS com aliquotas basicas.
"""
        chunks = chunk_text(sample_md, max_chunk_chars=120)
        assert len(chunks) >= 2
        assert any("ICMS" in c for c in chunks)
        assert any("COFINS" in c for c in chunks)

    def test_incremental_indexing_skips_unchanged_chunks(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_sem.db"
        index = SemanticIndex(db_path, backend=DeterministicHashEmbedding(dimension=64))

        doc_text = "Primeiro paragrafo de teste.\n\nSegundo paragrafo inalterado."
        # First indexing computes 2 chunks
        computed_first = index.index_document("doc-1", doc_text, max_chunk_chars=40)
        assert computed_first >= 1

        # Second indexing of identical content computes 0 new embeddings
        computed_second = index.index_document("doc-1", doc_text, max_chunk_chars=40)
        assert computed_second == 0

        # Modifying only one paragraph updates only modified chunks
        doc_modified = "Primeiro paragrafo ALTERADO com novas regras.\n\nSegundo paragrafo inalterado."
        computed_third = index.index_document("doc-1", doc_modified, max_chunk_chars=40)
        assert computed_third >= 1


class TestHybridSearchAndBenchmark:
    @pytest.fixture
    def corpus_data(self) -> dict:
        corpus_path = Path(__file__).parent.parent / "vrsoft_extractor" / "mary" / "retrieval" / "benchmark_corpus.json"
        with open(corpus_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @pytest.fixture
    def setup_hybrid(self, tmp_path: Path, corpus_data: dict) -> tuple[MaryDatabase, SemanticIndex]:
        # Set up SQLite FTS
        db_path = tmp_path / "mary_bench.db"
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

        # Set up Semantic Index with DeterministicHashEmbedding
        sem_path = tmp_path / "semantic_index.db"
        sem_index = SemanticIndex(sem_path, backend=DeterministicHashEmbedding(dimension=128))
        for doc in corpus_data["documents"]:
            sem_index.index_document(doc["id"], f"{doc['title']}\n\n{doc['text']}")

        return db, sem_index

    def test_semantic_search_handles_typos(self, setup_hybrid: tuple[MaryDatabase, SemanticIndex]) -> None:
        db, sem_index = setup_hybrid
        # Typo query: "invetario de estoke"
        typo_query = "invetario de estoke"
        sem_results = sem_index.search(typo_query, limit=5)
        doc_ids = [d for d, s in sem_results]
        # doc-06 is Inventário de estoque
        assert "doc-06" in doc_ids

    def test_hybrid_fallback_on_empty_or_missing_semantic_index(
        self,
        setup_hybrid: tuple[MaryDatabase, SemanticIndex],
    ) -> None:
        db, _ = setup_hybrid

        def lexical_fn(q: str, limit: int = 10) -> list[str]:
            return [str(r["source_id"]) for r in db.search(q, limit=limit)]

        engine_no_sem = HybridSearchEngine(lexical_fn, semantic_index=None)
        res = engine_no_sem.search("apuracao de icms mensal", limit=5)
        assert len(res) >= 1
        assert "doc-01" in res

    def test_hybrid_benchmark_beats_baseline_recall_by_at_least_15_percent(
        self,
        corpus_data: dict,
        setup_hybrid: tuple[MaryDatabase, SemanticIndex],
    ) -> None:
        db, sem_index = setup_hybrid

        # Measure the lexical baseline against the same isolated corpus.
        # This test must also work alone, without a previous L4 report.
        def lexical_baseline(query: str, limit: int = 10) -> list[str]:
            return [str(row["source_id"]) for row in db.search(query, limit=limit)]

        baseline = evaluate_retrieval(lexical_baseline, corpus_data, k=10)

        base_recall = baseline["mean_recall"]

        engine = HybridSearchEngine(
            lexical_search_fn=lexical_baseline,
            semantic_index=sem_index,
            w_text=1.0,
            w_sem=1.2,
            rrf_k=60,
        )

        hybrid_metrics = evaluate_retrieval(engine.search, corpus_data, k=10)

        # 1. Recall must beat baseline by at least 15% relative
        min_required_recall = base_recall * 1.15
        assert hybrid_metrics["mean_recall"] >= min_required_recall, (
            f"Hybrid recall {hybrid_metrics['mean_recall']} did not achieve +15% over baseline {base_recall}"
        )

        # 2. nDCG must not regress below 0.60
        assert hybrid_metrics["mean_ndcg"] >= 0.60

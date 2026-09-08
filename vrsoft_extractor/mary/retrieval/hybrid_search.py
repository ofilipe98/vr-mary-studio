"""
Hybrid search engine combining lexical (FTS5) and dense semantic vector retrieval
via Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

import logging
from typing import Callable, Sequence

from .semantic_index import SemanticIndex

LOGGER = logging.getLogger(__name__)

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    lexical_ranked: Sequence[str],
    semantic_ranked: Sequence[str],
    *,
    w_text: float = 1.0,
    w_sem: float = 1.0,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[tuple[str, float]]:
    """
    Calculate fused scores using Reciprocal Rank Fusion (RRF):
    RRF(d) = w_text / (rrf_k + rank_text(d)) + w_sem / (rrf_k + rank_sem(d))
    (ranks are 1-indexed)
    """
    scores: dict[str, float] = {}
    if rrf_k < 0 or w_text < 0 or w_sem < 0:
        raise ValueError("RRF requires non-negative weights and rank constant")

    for rank, doc_id in enumerate(dict.fromkeys(lexical_ranked), start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + (w_text / (rrf_k + rank))

    for rank, doc_id in enumerate(dict.fromkeys(semantic_ranked), start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + (w_sem / (rrf_k + rank))

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked


class HybridSearchEngine:
    """
    Combines lexical search and semantic vector index.
    Gracefully degrades to 100% lexical search if semantic index is absent or fails.
    """

    def __init__(
        self,
        lexical_search_fn: Callable[[str, int], Sequence[str]],
        semantic_index: SemanticIndex | None = None,
        *,
        w_text: float = 1.0,
        w_sem: float = 1.2,
        rrf_k: int = DEFAULT_RRF_K,
    ):
        self.lexical_search_fn = lexical_search_fn
        self.semantic_index = semantic_index
        self.w_text = float(w_text)
        self.w_sem = float(w_sem)
        self.rrf_k = int(rrf_k)

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[str]:
        """Run hybrid search returning ranked list of document IDs."""
        if limit <= 0 or not query.strip():
            return []
        # 1. Lexical retrieval
        try:
            lexical_ids = list(dict.fromkeys(self.lexical_search_fn(query, limit * 2)))
        except Exception as exc:
            LOGGER.warning("Busca lexical falhou: %s", exc)
            lexical_ids = []

        # 2. Semantic retrieval
        semantic_ids: list[str] = []
        if self.semantic_index is not None:
            try:
                sem_results = self.semantic_index.search(query, limit=limit * 2)
                semantic_ids = [doc_id for doc_id, score in sem_results]
            except Exception as exc:
                LOGGER.warning("Busca semântica falhou, degradando para puramente textual: %s", exc)
                semantic_ids = []

        # If only lexical is available
        if not semantic_ids:
            return lexical_ids[:limit]

        # If only semantic is available
        if not lexical_ids:
            return semantic_ids[:limit]

        # 3. Fuse with RRF
        fused = reciprocal_rank_fusion(
            lexical_ids,
            semantic_ids,
            w_text=self.w_text,
            w_sem=self.w_sem,
            rrf_k=self.rrf_k,
        )
        return [doc_id for doc_id, score in fused[:limit]]

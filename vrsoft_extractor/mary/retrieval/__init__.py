"""
Retrieval subsystem for VR Mary Studio.

Provides facade and contracts for knowledge retrieval, query routing,
dense vector embeddings, local semantic indexing, hybrid search (RRF),
and verifiable relation extraction with bounded context expansion.
"""

from __future__ import annotations

from .benchmark import evaluate_retrieval
from .embedding_contract import (
    DeterministicHashEmbedding,
    EmbeddingBackend,
    FallbackEmbeddingBackend,
    cosine_similarity,
)
from .hybrid_search import (
    HybridSearchEngine,
    reciprocal_rank_fusion,
)
from .relations import (
    ContextExpander,
    DocumentRelation,
    RelationExtractor,
    RelationRepository,
)
from .semantic_index import (
    SemanticIndex,
    chunk_text,
)
from .service import RetrievalService

__all__ = [
    "ContextExpander",
    "DeterministicHashEmbedding",
    "DocumentRelation",
    "EmbeddingBackend",
    "FallbackEmbeddingBackend",
    "HybridSearchEngine",
    "RelationExtractor",
    "RelationRepository",
    "RetrievalService",
    "SemanticIndex",
    "chunk_text",
    "cosine_similarity",
    "evaluate_retrieval",
    "reciprocal_rank_fusion",
]

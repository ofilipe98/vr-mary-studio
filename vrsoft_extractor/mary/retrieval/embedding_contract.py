"""
Embedding backend contracts and deterministic offline implementations for VR Mary Studio.

Provides the EmbeddingBackend protocol, a deterministic n-gram hashing backend
for offline and test execution (zero downloads, unit norm, stable cosine distances),
and fallback wrappers for optional neural model backends.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Sequence


class EmbeddingBackend(ABC):
    """Abstract contract for text embedding providers."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier."""
        ...

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Convert a single text string into a normalized dense vector."""
        ...

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Convert a batch of texts into normalized dense vectors."""
        return [self.embed_text(t) for t in texts]


class DeterministicHashEmbedding(EmbeddingBackend):
    """
    High-performance, zero-dependency, deterministic hash-based embedding backend.

    Generates stable unit-length vectors using character and token n-gram hashing.
    Lexical similarity fixture for tests. This is not a neural semantic model.
    """

    def __init__(self, dimension: int = 128, name: str = "hash-ngram-128"):
        self._dim = max(16, int(dimension))
        self._name = f"hash-ngram-{self._dim}" if name == "hash-ngram-128" else name

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._name

    def embed_text(self, text: str) -> list[float]:
        normalized = str(text or "").strip().lower()
        if not normalized:
            # Return zero vector or neutral point
            return [0.0] * self._dim

        vec = [0.0] * self._dim

        # 1. Word tokens
        words = re.findall(r"\w+", normalized)
        for w in words:
            h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if ((h >> 8) & 1) else -1.0
            vec[idx] += 1.5 * sign

            # Word prefixes
            if len(w) >= 4:
                prefix_h = int(hashlib.md5(w[:4].encode("utf-8")).hexdigest(), 16)
                p_idx = prefix_h % self._dim
                p_sign = 1.0 if ((prefix_h >> 8) & 1) else -1.0
                vec[p_idx] += 0.8 * p_sign

        # 2. Character 3-grams
        for i in range(max(0, len(normalized) - 2)):
            gram = normalized[i : i + 3]
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if ((h >> 8) & 1) else -1.0
            vec[idx] += 0.5 * sign

        # 3. L2 Normalization to guarantee unit norm: ||v|| = 1.0
        norm_sq = sum(x * x for x in vec)
        if norm_sq <= 1e-12:
            vec[0] = 1.0
            return vec

        norm = math.sqrt(norm_sq)
        return [x / norm for x in vec]


class FallbackEmbeddingBackend(EmbeddingBackend):
    """
    Selects one vector space at construction. Runtime failures propagate so
    retrieval can fall back to lexical search without mixing incompatible vectors.
    """

    def __init__(
        self,
        primary: EmbeddingBackend | None = None,
        fallback: EmbeddingBackend | None = None,
    ):
        self._fallback = fallback or DeterministicHashEmbedding()
        self._primary = primary if primary is not None else self._fallback

    @property
    def dimension(self) -> int:
        return self._primary.dimension

    @property
    def model_name(self) -> str:
        return self._primary.model_name

    def embed_text(self, text: str) -> list[float]:
        return self._primary.embed_text(text)


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    if not all(math.isfinite(v) for v in (*v1, *v2)):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in v1) * sum(v * v for v in v2))
    if denominator <= 1e-12:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2)) / denominator
    return max(-1.0, min(1.0, dot))

"""
Retrieval quality benchmark suite for VR Mary Studio.

Calculates Recall@10, MRR@10, nDCG@10 and latency percentiles (p50, p95)
against a standardized evaluation corpus.
"""

from __future__ import annotations

import json
import hashlib
import math
import statistics
import time
from typing import Any, Callable, Sequence


def dcg_at_k(relevance_scores: Sequence[float], k: int = 10) -> float:
    """Calculate Discounted Cumulative Gain at k."""
    dcg = 0.0
    for i, rel in enumerate(relevance_scores[:k]):
        if rel > 0:
            dcg += (2.0**rel - 1.0) / math.log2(i + 2)
    return dcg


def ndcg_at_k(ranked_doc_ids: Sequence[str], ground_truth: dict[str, int], k: int = 10) -> float:
    """Calculate Normalized Discounted Cumulative Gain at k."""
    if not ground_truth:
        return 0.0

    actual_scores = [ground_truth.get(doc_id, 0) for doc_id in list(dict.fromkeys(ranked_doc_ids))[:k]]
    actual_dcg = dcg_at_k(actual_scores, k)

    ideal_scores = sorted(ground_truth.values(), reverse=True)
    ideal_dcg = dcg_at_k(ideal_scores, k)

    if ideal_dcg <= 0.0:
        return 0.0
    return actual_dcg / ideal_dcg


def mrr_at_k(ranked_doc_ids: Sequence[str], ground_truth: dict[str, int], k: int = 10) -> float:
    """Calculate Mean Reciprocal Rank at k (considering relevance >= 1 as hit)."""
    for i, doc_id in enumerate(list(dict.fromkeys(ranked_doc_ids))[:k]):
        if ground_truth.get(doc_id, 0) >= 1:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(ranked_doc_ids: Sequence[str], ground_truth: dict[str, int], k: int = 10) -> float:
    """Calculate Recall at k (relevant retrieved / total relevant)."""
    relevant_ids = {doc_id for doc_id, rel in ground_truth.items() if rel >= 1}
    if not relevant_ids:
        return 0.0
    retrieved_relevant = {doc_id for doc_id in ranked_doc_ids[:k] if doc_id in relevant_ids}
    return len(retrieved_relevant) / len(relevant_ids)


def evaluate_retrieval(
    search_fn: Callable[[str, int], Sequence[str]],
    corpus_data: dict[str, Any],
    k: int = 10,
) -> dict[str, Any]:
    """
    Run full benchmark suite across all queries in corpus_data.

    search_fn: takes (query, limit) and returns sequence of retrieved document IDs.
    """
    queries = corpus_data.get("queries", [])
    if k <= 0:
        raise ValueError("k must be positive")
    if not queries:
        raise ValueError("Corpus has no queries to evaluate")

    recalls: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    latencies_ms: list[float] = []

    per_query_results: list[dict[str, Any]] = []

    for item in queries:
        query_text = item["query"]
        ground_truth: dict[str, int] = item.get("relevant_docs", {})

        t0 = time.perf_counter()
        retrieved_ids = list(dict.fromkeys(search_fn(query_text, k)))[:k]
        latency = (time.perf_counter() - t0) * 1000.0

        latencies_ms.append(latency)
        q_recall = recall_at_k(retrieved_ids, ground_truth, k)
        q_mrr = mrr_at_k(retrieved_ids, ground_truth, k)
        q_ndcg = ndcg_at_k(retrieved_ids, ground_truth, k)

        recalls.append(q_recall)
        mrrs.append(q_mrr)
        ndcgs.append(q_ndcg)

        per_query_results.append({
            "query": query_text,
            "retrieved_ids": retrieved_ids,
            "relevant_docs": ground_truth,
            "retrieved_count": len(retrieved_ids),
            "recall": round(q_recall, 4),
            "mrr": round(q_mrr, 4),
            "ndcg": round(q_ndcg, 4),
            "latency_ms": round(latency, 2),
        })

    latencies_sorted = sorted(latencies_ms)
    p50_idx = int(len(latencies_sorted) * 0.50)
    p95_idx = min(len(latencies_sorted) - 1, int(len(latencies_sorted) * 0.95))

    return {
        "document_count": len(corpus_data.get("documents", [])),
        "corpus_sha256": hashlib.sha256(json.dumps(corpus_data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "split": corpus_data.get("split", "unspecified"),
        "k": k,
        "query_count": len(queries),
        "mean_recall": round(statistics.mean(recalls), 4),
        "mean_mrr": round(statistics.mean(mrrs), 4),
        "mean_ndcg": round(statistics.mean(ndcgs), 4),
        "latency_p50_ms": round(latencies_sorted[p50_idx], 2),
        "latency_p95_ms": round(latencies_sorted[p95_idx], 2),
        "latency_mean_ms": round(statistics.mean(latencies_ms), 2),
        "per_query": per_query_results,
    }

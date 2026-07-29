from __future__ import annotations

from collections import Counter
from typing import Any

from .classifier import classify, load_product_catalog
from .db import MaryDatabase


def audit_classification(
    database: MaryDatabase,
    limit: int | None = None,
    example_limit: int = 25,
    queue_review: bool = False,
) -> dict[str, Any]:
    sql = """SELECT id,source,title,module,review_status,category,product,markdown
             FROM documents WHERE status='active' ORDER BY id"""
    parameters: tuple[int, ...] = ()
    if limit:
        sql += " LIMIT ?"
        parameters = (limit,)
    with database.connect() as connection:
        rows = connection.execute(sql, parameters).fetchall()

    modules: Counter[str] = Counter()
    transitions: Counter[tuple[str, str]] = Counter()
    changed_by_source: Counter[str] = Counter()
    evidence_by_source: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    for row in rows:
        result = classify(
            row["title"],
            row["markdown"],
            row["category"],
            row["product"],
        )
        modules[result.module] += 1
        if any("produto " in reason for reason in result.reasons):
            evidence_by_source[row["source"]] += 1
        if result.module == row["module"]:
            continue
        transitions[(row["module"], result.module)] += 1
        changed_by_source[row["source"]] += 1
        if queue_review:
            database.queue_review(
                row["id"],
                result.module,
                result.confidence,
                result.reasons,
                row["module"],
                bool(
                    row["review_status"] == "approved"
                    and row["module"] != result.module
                ),
            )
        if len(examples) < example_limit:
            examples.append(
                {
                    "title": row["title"],
                    "source": row["source"],
                    "review_status": row["review_status"],
                    "current_module": row["module"],
                    "suggested_module": result.module,
                    "confidence": round(result.confidence, 4),
                    "reasons": result.reasons,
                }
            )

    return {
        "catalog_products": len(load_product_catalog()),
        "documents_analyzed": len(rows),
        "suggested_modules": dict(modules),
        "changes_suggested": sum(transitions.values()),
        "review_queue_updated": (
            sum(transitions.values()) if queue_review else 0
        ),
        "changes_by_source": dict(changed_by_source),
        "product_evidence_by_source": dict(evidence_by_source),
        "transitions": {
            f"{current} -> {suggested}": total
            for (current, suggested), total in transitions.most_common()
        },
        "examples": examples,
    }

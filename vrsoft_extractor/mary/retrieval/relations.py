"""
Deterministic relation extraction, relation storage, and bounded 1-hop context expansion
for VR Mary Studio.
"""

from __future__ import annotations

import re
import json
import sqlite3
import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ..models import EvidenceCandidate, KnowledgeDocument


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DocumentRelation:
    source_id: str
    target_id: str
    relation_type: str  # 'cites', 'schema_table', 'screen_reference', 'related_doc'
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class RelationExtractor:
    """Extracts verifiable relationships deterministically from markdown text."""

    # Markdown links: [label](target)
    LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    # Schema tables: TB_XYZ or tb_xyz
    SCHEMA_TABLE_PATTERN = re.compile(r"\b(TB_[A-Za-z0-9_]{2,})\b", re.IGNORECASE)
    # Screen and routine references: VR0101, VR_IMPORTADOR, etc.
    SCREEN_PATTERN = re.compile(r"\b(VR[0-9]{4}|VR_[A-Za-z0-9_]+)\b", re.IGNORECASE)

    @classmethod
    def extract_relations(
        cls,
        source_id: str,
        markdown: str,
        module: str = "",
    ) -> list[DocumentRelation]:
        text = str(markdown or "")
        relations: list[DocumentRelation] = []
        seen_targets: set[tuple[str, str]] = set()

        # 1. Explicit markdown links
        for match in cls.LINK_PATTERN.finditer(text):
            target = match.group(2).strip()
            # If link points to an internal doc or slug
            if not target.startswith(("http://", "https://")):
                clean_target = target.lstrip("/").replace(".md", "")
                key = (clean_target, "cites")
                if key not in seen_targets and clean_target != source_id:
                    seen_targets.add(key)
                    relations.append(
                        DocumentRelation(
                            source_id=source_id,
                            target_id=clean_target,
                            relation_type="cites",
                            confidence=0.95,
                            metadata={"label": match.group(1).strip()},
                        )
                    )

        # 2. Schema tables
        for match in cls.SCHEMA_TABLE_PATTERN.finditer(text):
            table_name = match.group(1).upper()
            target = f"schema:{table_name}"
            key = (target, "schema_table")
            if key not in seen_targets and target != source_id:
                seen_targets.add(key)
                relations.append(
                    DocumentRelation(
                        source_id=source_id,
                        target_id=target,
                        relation_type="schema_table",
                        confidence=0.90,
                        metadata={"table": table_name},
                    )
                )

        # 3. Screens and routines
        for match in cls.SCREEN_PATTERN.finditer(text):
            screen_name = match.group(1).upper()
            target = f"screen:{screen_name}"
            key = (target, "screen_reference")
            if key not in seen_targets and target != source_id:
                seen_targets.add(key)
                relations.append(
                    DocumentRelation(
                        source_id=source_id,
                        target_id=target,
                        relation_type="screen_reference",
                        confidence=0.85,
                        metadata={"screen": screen_name},
                    )
                )

        return relations


class RelationRepository:
    """SQLite storage for document relations."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS document_relations (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    extracted_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, relation_type)
                );

                CREATE INDEX IF NOT EXISTS idx_relations_source
                ON document_relations(source_id);

                CREATE INDEX IF NOT EXISTS idx_relations_target
                ON document_relations(target_id);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(document_relations)")}
            if "metadata_json" not in columns:
                conn.execute("ALTER TABLE document_relations ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")

    def save_relations(self, relations: Sequence[DocumentRelation]) -> None:
        if not relations:
            return
        now = utc_now_iso()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO document_relations (
                    source_id, target_id, relation_type, confidence, extracted_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                    confidence = excluded.confidence,
                    extracted_at = excluded.extracted_at,
                    metadata_json = excluded.metadata_json
                """,
                [
                    (r.source_id, r.target_id, r.relation_type, r.confidence, now, json.dumps(r.metadata, ensure_ascii=False))
                    for r in relations
                ],
            )

    def replace_all(self, relations: Sequence[DocumentRelation]) -> None:
        """Publish a complete extraction atomically, removing obsolete links too."""
        with self._connect() as conn:
            conn.execute("DELETE FROM document_relations")
            conn.executemany("INSERT INTO document_relations(source_id,target_id,relation_type,confidence,extracted_at,metadata_json) VALUES(?,?,?,?,?,?)",
                [(r.source_id, r.target_id, r.relation_type, r.confidence, utc_now_iso(), json.dumps(r.metadata, ensure_ascii=False)) for r in relations])

    def get_outward_relations(
        self,
        source_id: str,
        min_confidence: float = 0.7,
    ) -> list[DocumentRelation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, target_id, relation_type, confidence, metadata_json
                FROM document_relations
                WHERE source_id = ? AND confidence >= ?
                ORDER BY confidence DESC
                """,
                (source_id, min_confidence),
            ).fetchall()
            return [
                DocumentRelation(
                    source_id=r["source_id"],
                    target_id=r["target_id"],
                    relation_type=r["relation_type"],
                    confidence=r["confidence"],
                    metadata=json.loads(r["metadata_json"]),
                )
                for r in rows
            ]


class ContextExpander:
    """Expands evidence candidates along 1-hop verifiable relations within strict budgets."""

    def __init__(
        self,
        relation_repo: RelationRepository,
        doc_resolver: Callable[[str], KnowledgeDocument | None],
        *,
        max_added: int = 3,
        max_added_tokens: int = 2000,
        min_confidence: float = 0.7,
        require_provenance: bool = False,
        max_seconds: float = 0.1,
    ):
        self.repo = relation_repo
        self.doc_resolver = doc_resolver
        self.max_added = max(0, int(max_added))
        self.max_chars = max(0, int(max_added_tokens * 4))  # ~4 chars per token rule of thumb
        self.min_confidence = float(min_confidence)
        self.require_provenance = require_provenance
        self.max_seconds = max(0.0, max_seconds)

    def expand(
        self,
        primary_candidates: Sequence[EvidenceCandidate],
    ) -> list[EvidenceCandidate]:
        """
        Expand primary candidates with related 1st-degree documents.
        Strictly prevents cycles and respects max_added and max_tokens limits.
        """
        if not primary_candidates or self.max_added <= 0:
            return list(primary_candidates)

        visited_ids: set[str] = {c.evidence_id for c in primary_candidates}
        visited_documents = {(c.source, c.source_id) for c in primary_candidates}
        result: list[EvidenceCandidate] = list(primary_candidates)
        added_count = 0
        added_chars = 0
        deadline = time.monotonic() + self.max_seconds

        for candidate in primary_candidates:
            if added_count >= self.max_added or time.monotonic() >= deadline:
                break

            relations = self.repo.get_outward_relations(
                f"{candidate.source}:{candidate.source_id}" if self.require_provenance else candidate.evidence_id,
                min_confidence=self.min_confidence,
            )

            for rel in relations:
                if added_count >= self.max_added or time.monotonic() >= deadline:
                    break
                if self.require_provenance:
                    parent_doc = self.doc_resolver(rel.source_id)
                    if not parent_doc or not rel.metadata.get("verified") or not rel.metadata.get("excerpt"):
                        continue
                    if rel.metadata.get("source_hash") != hashlib.sha256(parent_doc.markdown.encode()).hexdigest():
                        continue
                target_id = rel.target_id
                if target_id in visited_ids:
                    continue  # Prevents cycle or duplication

                doc = self.doc_resolver(target_id)
                if not doc or (doc.source, doc.source_id) in visited_documents or doc.status != "active":
                    continue
                actual_hash = hashlib.sha256(doc.markdown.encode()).hexdigest() if self.require_provenance else doc.content_hash
                if rel.metadata.get("target_hash") and rel.metadata["target_hash"] != actual_hash:
                    continue
                if candidate.product and doc.product and candidate.product != doc.product:
                    continue

                excerpt = doc.markdown[:800].strip()
                if not excerpt:
                    continue

                if added_chars + len(excerpt) > self.max_chars:
                    continue  # A later, smaller document may still fit.

                visited_ids.add(target_id)
                visited_documents.add((doc.source, doc.source_id))
                added_count += 1
                added_chars += len(excerpt)

                expanded_candidate = EvidenceCandidate(
                    evidence_id=f"{target_id}:related" if self.require_provenance else target_id,
                    source=doc.source,
                    source_id=doc.source_id,
                    document_id=int(rel.metadata.get("target_document_id") or 0),
                    chunk_id=0,
                    title=f"[Relacionado via {candidate.title}] {doc.title}",
                    heading=candidate.heading,
                    content_type=candidate.content_type or "knowledge",
                    module=doc.module or candidate.module,
                    product=candidate.product,
                    excerpt=excerpt,
                    url=doc.url,
                    source_origin=doc.source_origin,
                    score=candidate.score * 0.85,
                    score_breakdown={
                        "relation_confidence": float(rel.confidence),
                        "expanded_from_score": float(candidate.score),
                    },
                    entities={
                        "expanded_from": (candidate.evidence_id,),
                        "relation_type": (rel.relation_type,),
                        "relation_excerpt": (str(rel.metadata.get("excerpt") or ""),),
                        "relation_source_hash": (str(rel.metadata.get("source_hash") or ""),),
                    },
                )
                result.append(expanded_candidate)

        return result

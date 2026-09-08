"""
Retrieval service contract and facade for VR Mary Studio.

Delegates to KnowledgeRouter, HybridSearchEngine, and ContextExpander
while providing an explicit, testable retrieval interface isolated from orchestration details.
"""

from __future__ import annotations

from typing import Any, Sequence
from dataclasses import fields
import hashlib
import json
import logging
import threading
from pathlib import Path
from dataclasses import replace
from .generations import GenerationSemanticIndex, document_signature

from ..knowledge_router import KnowledgeRouter
from ..models import EvidenceBundle, EvidenceCandidate, KnowledgeDocument, QueryProfile
from .hybrid_search import HybridSearchEngine
from .relations import ContextExpander, RelationExtractor, RelationRepository
from .semantic_index import SemanticIndex


class RetrievalService:
    """Retrieval service facade wrapping KnowledgeRouter operations, hybrid search, and context expansion."""

    def __init__(
        self,
        router: KnowledgeRouter,
        semantic_index: SemanticIndex | None = None,
        relation_repository: RelationRepository | None = None,
    ):
        self._router = router
        from types import SimpleNamespace
        root = getattr(router, "root", None)
        self._settings = SimpleNamespace(root=Path(root), state_dir=Path(root) / ".state", index_dir=Path(root) / "indice") if isinstance(root, (str, Path)) else None
        self._neural = None
        self._configuration = {"mode": "textual", "model": "minilm", "relations": False}
        self._diagnostic = "Busca textual"
        self._reindex_lock = threading.Lock()
        self._source_signature = ""
        self._relation_signature = ""
        self._scope_cache = None
        self._scope_lock = threading.Lock()
        self._scheduled = False
        if self._settings:
            self._config_path = self._settings.state_dir / "retrieval.json"
            try:
                self._configuration.update(json.loads(self._config_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        self._router.candidate_enricher = self._enrich_lane
        self._semantic_index = semantic_index
        self._relation_repo = relation_repository

        def lexical_fn(q: str, limit: int = 10):
            res = self._router.database.search(q, limit=limit)
            return [f"{item['source']}:{item['source_id']}" for item in res
                    if self.resolve_document(f"{item['source']}:{item['source_id']}") is not None]

        self._hybrid_engine = HybridSearchEngine(
            lexical_search_fn=lexical_fn,
            semantic_index=self._semantic_index,
        )

        self._expander = (
            ContextExpander(self._relation_repo, doc_resolver=self.resolve_document)
            if self._relation_repo is not None
            else None
        )

    def resolve_document(self, doc_id: str, *, require_review: bool = False) -> KnowledgeDocument | None:
        """Resolve active, enabled knowledge documents, rejecting ambiguous legacy IDs."""
        source, separator, source_id = str(doc_id).partition(":")
        with self._router.database.connect() as conn:
            if separator and source in {"wiki", "kb", "schema"}:
                rows = conn.execute("SELECT * FROM documents WHERE source=? AND source_id=? AND status='active'", (source, source_id)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM documents WHERE source_id=? AND status='active' LIMIT 2", (doc_id,)).fetchall()
        if len(rows) != 1:
            return None
        row = dict(rows[0])
        if require_review and (row.get("review_status") not in {"approved", "kept"} or row.get("module") == "Revisar"):
            return None
        revision = self._router.retrieval_revision.get()
        if revision and row.get("revision") != revision:
            return None
        if row["source_origin"] not in self.enabled_origins(row["source"]):
            return None
        allowed = {f.name for f in fields(KnowledgeDocument)}
        return KnowledgeDocument(**{k: v for k, v in row.items() if k in allowed})

    @property
    def router(self) -> KnowledgeRouter:
        return self._router

    @property
    def semantic_index(self) -> SemanticIndex | None:
        return self._semantic_index

    @property
    def relation_repository(self) -> RelationRepository | None:
        return self._relation_repo

    @property
    def hybrid_engine(self) -> HybridSearchEngine:
        return self._hybrid_engine

    def search(
        self,
        query: str,
        *,
        source: str = "",
        module: str = "",
        limit: int = 6,
        revision: str = "",
    ) -> dict[str, Any]:
        """Run a focused evidence retrieval for tools or direct queries."""
        token = self._router.retrieval_revision.set(revision)
        try:
            self._prepare_search()
            result = self._router.search(query, source=source, module=module, limit=limit)
            if self._configuration["mode"] == "hybrid" and self._diagnostic != "Busca híbrida local":
                result = {**result, "warnings": [*result.get("warnings", []), self._diagnostic]}
            return result
        finally:
            self._router.retrieval_revision.reset(token)

    def hybrid_search(self, query: str, limit: int = 10, *, source: str = "", module: str = "") -> list[str]:
        """Run hybrid search (FTS5 + Semantic RRF)."""
        result = []
        for doc_id in self._hybrid_engine.search(query, limit=max(0, limit) * 3):
            doc = self.resolve_document(doc_id)
            if doc is None or (source and doc.source != source) or (module and doc.module not in {module, "Multimodulo"}):
                continue
            key = f"{doc.source}:{doc.source_id}"
            if key not in result:
                result.append(key)
        return result[:max(0, limit)]

    def expand_candidates(
        self,
        candidates: Sequence[EvidenceCandidate],
    ) -> list[EvidenceCandidate]:
        """Expand evidence candidates with verifiable 1st-degree related documents."""
        if self._expander is not None:
            return self._expander.expand(candidates)
        return list(candidates)

    def route(self, query: str, *, revision: str = "") -> EvidenceBundle:
        token = self._router.retrieval_revision.set(revision)
        try:
            self._prepare_search()
            return self._finalize_bundle(self._router.route(query))
        finally:
            self._router.retrieval_revision.reset(token)

    def _prepare_search(self) -> None:
        if self._configuration["mode"] == "hybrid":
            self._ensure_neural()
            if self._neural and self.scope_signature() != self._source_signature and not self._scheduled:
                self._scheduled = True
                def update():
                    try:
                        self.reindex()
                    except Exception as exc:
                        self._diagnostic = f"Busca textual durante reindexação: {exc}"
                    finally:
                        self._scheduled = False
                threading.Thread(target=update, name="semantic-reindex", daemon=True).start()
    def _finalize_bundle(self, bundle: EvidenceBundle) -> EvidenceBundle:
        # Final permission/version check closes the window between candidate search and context assembly.
        bundle = replace(bundle, candidates=tuple(c for c in bundle.candidates
            if self.resolve_document(f"{c.source}:{c.source_id}", require_review=True) is not None))
        if self._configuration.get("relations"):
            if self.scope_signature() != self._relation_signature:
                self.rebuild_relations()
            bundle = replace(bundle, candidates=tuple(self.expand_candidates(bundle.candidates)))
        if self._configuration["mode"] == "hybrid" and self._diagnostic != "Busca híbrida local":
            bundle = replace(bundle, warnings=(*bundle.warnings, self._diagnostic))
        return bundle

    def scope_signature(self) -> str:
        """Hash current permissions and complete source content, not just search snippets."""
        with self._scope_lock, self._router.database.connect() as conn:
            # Read the revision and content from one snapshot. A writer that commits
            # while hashing will invalidate this entry on the next call.
            conn.execute("BEGIN")
            revision = conn.execute("SELECT revision FROM knowledge_revision WHERE singleton=1").fetchone()[0]
            disabled_origins = frozenset(self._router.disabled_origins)
            key = (revision, disabled_origins)
            if self._scope_cache is not None and self._scope_cache[0] == key:
                return self._scope_cache[1]
            # Permissions and content must describe the same database snapshot.
            permissions = {source: [] for source in ("wiki", "kb", "schema")}
            for source, origin in conn.execute("""SELECT DISTINCT source,source_origin FROM documents
                WHERE status='active' AND trim(source_origin)<>'' ORDER BY source,source_origin"""):
                if source in permissions and origin.casefold() not in disabled_origins:
                    permissions[source].append(origin)
            permission_key = json.dumps(permissions, sort_keys=True)
            digest = hashlib.sha256(permission_key.encode())
            for row in conn.execute("SELECT * FROM documents ORDER BY source,source_id"):
                digest.update(document_signature(dict(row)).encode())
            signature = digest.hexdigest()
            self._scope_cache = (key, signature)
            return signature

    @property
    def configuration(self) -> dict:
        return {**self._configuration, "diagnostic": self._diagnostic}

    def configure(self, *, mode: str, model: str = "minilm", relations: bool = False) -> None:
        from .local_neural import MODELS
        if mode not in {"textual", "hybrid"} or model not in MODELS:
            raise ValueError("Configuração de busca inválida")
        self._configuration = {"mode": mode, "model": model, "relations": bool(relations)}
        self._neural = None
        if self._settings:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._config_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._configuration), encoding="utf-8")
            temporary.replace(self._config_path)
        if relations:
            self.rebuild_relations()

    def _documents(self) -> list[dict]:
        with self._router.database.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM documents WHERE status='active' AND review_status IN ('approved','kept') AND module<>'Revisar'")
                    if r["source_origin"] in self.enabled_origins(r["source"])]

    def rebuild_relations(self) -> dict:
        """Only explicit links to unique, active local documents become traversable edges."""
        from .relations import DocumentRelation
        from urllib.parse import urljoin, unquote
        documents = self._documents()
        aliases = {}
        for row in documents:
            for alias in (f"{row['source']}:{row['source_id']}", row['source_id'], row.get('url'), row.get('local_path')):
                if alias:
                    aliases.setdefault(str(alias).split('#')[0].rstrip('/'), []).append(row)
        relations = {}
        for row in documents:
            for match in RelationExtractor.LINK_PATTERN.finditer(row['markdown']):
                raw = unquote(match.group(2).strip()).split('#')[0].rstrip('/')
                if not raw:
                    continue
                targets = aliases.get(raw) or aliases.get(urljoin(row['url'], raw).rstrip('/')) or []
                targets = {r['id']: r for r in targets}
                if len(targets) != 1:
                    continue
                target = next(iter(targets.values()))
                if target['id'] == row['id'] or (row['product'] and target['product'] and row['product'] != target['product']):
                    continue
                source_id, target_id = f"{row['source']}:{row['source_id']}", f"{target['source']}:{target['source_id']}"
                relation = DocumentRelation(source_id, target_id, 'explicit_link', 1.0, {
                    'verified': True, 'extractor': 'markdown-link-v2', 'excerpt': match.group(0),
                    'source_hash': hashlib.sha256(row['markdown'].encode()).hexdigest(),
                    'target_hash': hashlib.sha256(target['markdown'].encode()).hexdigest(),
                    'source_revision': row['revision'], 'target_revision': target['revision'],
                    'target_document_id': target['id'],
                })
                relations[(source_id, target_id)] = relation
        if self._relation_repo is None:
            self._relation_repo = RelationRepository(self._router.database.path)
        self._relation_repo.replace_all(list(relations.values()))
        self._expander = ContextExpander(self._relation_repo,
            lambda key: self.resolve_document(key, require_review=True), require_provenance=True)
        self._relation_signature = self.scope_signature()
        return {'relations': len(relations), 'documents': len(documents)}

    def _ensure_neural(self) -> None:
        if self._neural is not None or not self._settings:
            return
        try:
            from .local_neural import LocalOnnxEmbedding
            self._neural = GenerationSemanticIndex(self._settings.index_dir / "semantic.sqlite",
                LocalOnnxEmbedding(self._settings.root, self._configuration["model"]))
        except Exception as exc:
            self._diagnostic = f"Busca textual: {exc}"

    def prepare_semantic(self, progress=None) -> dict:
        if not self._settings:
            raise ValueError("Raiz de dados não configurada")
        from .local_neural import prepare_model
        prepare_model(self._settings.root, self._configuration["model"], progress)
        self._ensure_neural()
        if self._neural is None:
            raise RuntimeError(self._diagnostic)
        return self.reindex(progress)

    def reindex(self, progress=None) -> dict:
        self._ensure_neural()
        if self._neural is None:
            raise RuntimeError(self._diagnostic)
        with self._reindex_lock:
            signature = self.scope_signature()
            result = self._neural.rebuild(self._documents(), (lambda n, total: progress("Índice", n, total)) if progress else None)
            self._source_signature = signature
            self._diagnostic = "Busca híbrida local"
            if self._configuration.get("relations"):
                self.rebuild_relations()
            return result

    def _enrich_lane(self, profile, source, module, origin, lexical, limit):
        if self._configuration["mode"] != "hybrid" or self._neural is None:
            return lexical
        # Exact code/number queries retain their established textual ordering.
        if profile.entities.get("identifiers"):
            return lexical
        origins = (origin,) if origin else self.enabled_origins(source)
        if not origins or any(item not in self.enabled_origins(source) for item in origins):
            return lexical
        try:
            hits = self._neural.search(profile.query, limit, source=source, origins=origins, module=module, product=profile.product,
                                       revision=self._router.retrieval_revision.get())
            fresh, rows = {}, {}
            with self._router.database.connect() as conn:
                for hit in hits:
                    row = conn.execute("SELECT * FROM documents WHERE source=? AND source_id=? AND status='active' AND review_status IN ('approved','kept') AND module<>'Revisar'",
                                       (source, hit["doc_id"].partition(":")[2])).fetchone()
                    if not row or row["source_origin"] not in origins or document_signature(dict(row)) != hit["content_hash"]:
                        continue
                    fresh[hit["doc_id"]] = hit
                    converted = self._router._legacy_candidate_row(dict(row))
                    converted.update(excerpt=hit["text"], content=hit["text"], semantic_score=max(0.0, hit["score"]))
                    rows[hit["doc_id"]] = converted
            # RRF preserves textual documents and their chunk metadata; domain reranking follows in the router.
            from .hybrid_search import reciprocal_rank_fusion
            lexical_ids = list(dict.fromkeys(f"{r['source']}:{r['source_id']}" for r in lexical))
            fused = reciprocal_rank_fusion(lexical_ids, list(fresh), rrf_k=60)
            rank = {key: index for index, (key, _) in enumerate(fused)}
            combined = list(lexical) + [row for key, row in rows.items() if key not in lexical_ids]
            combined.sort(key=lambda row: rank.get(f"{row['source']}:{row['source_id']}", len(rank)))
            self._diagnostic = "Busca híbrida local"
            return combined
        except Exception as exc:
            logging.getLogger(__name__).warning("Busca semântica indisponível: %s", exc)
            self._diagnostic = f"Busca textual: {exc}"
            return lexical

    def refine(self, bundle: EvidenceBundle, query: str, *, revision: str = "") -> EvidenceBundle:
        """Refine an existing bundle with new query context."""
        token = self._router.retrieval_revision.set(revision)
        try:
            self._prepare_search()
            return self._finalize_bundle(self._router.refine(bundle, query))
        finally:
            self._router.retrieval_revision.reset(token)

    def classify(self, query: str) -> QueryProfile:
        """Classify query intent, modules, and target sources."""
        return self._router.classify(query)

    def prompt_for_role(
        self,
        bundle: EvidenceBundle,
        role: str,
        *,
        module: str = "",
    ) -> str:
        """Format an evidence prompt excerpt tailored to a specific researcher role."""
        return self._router.prompt_for_role(bundle, role, module=module)

    def enabled_origins(self, source: str) -> tuple[str, ...]:
        """Return currently enabled origins for a given knowledge source."""
        return self._router._enabled_origins(source)

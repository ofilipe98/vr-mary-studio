"""Bounded syntactic caller evidence reusing the existing Java index and provenance."""
from __future__ import annotations
import hashlib
import time
from pathlib import Path
from ..code_index import JavaCodeIndex
from ..models import EvidenceCandidate


def caller_evidence(root: Path, targets: list[str], *, release_id: str, manifest_hash: str,
                    max_nodes: int = 3, max_chars: int = 2400, max_seconds: float = .3) -> tuple[EvidenceCandidate, ...]:
    if not release_id or not manifest_hash or max_nodes <= 0 or max_chars <= 0:
        return ()
    deadline = time.monotonic() + max(0, max_seconds)
    index = JavaCodeIndex(root)
    result, seen, used = [], set(), 0
    for target in dict.fromkeys(targets):
        if time.monotonic() >= deadline or len(result) >= max_nodes:
            break
        for row in index.callers(target, release_id=release_id, limit=max_nodes):
            if time.monotonic() >= deadline or len(result) >= max_nodes:
                break
            if row.get('release_hash') != manifest_hash or row.get('freshness') != 'fresh' or row.get('resolution') != 'syntactic' or not row.get('source_sha256'):
                continue
            key = f"{release_id}:{row['source_sha256']}:{row['qualified_name']}:{row['line_start']}"
            excerpt = str(row.get('excerpt') or '')
            if key in seen or not excerpt or used + len(excerpt) > max_chars:
                continue
            seen.add(key)
            used += len(excerpt)
            result.append(EvidenceCandidate(
                evidence_id='code:relation:' + hashlib.sha256(key.encode()).hexdigest()[:20], source='code', source_id=key,
                document_id=0, chunk_id=0, title=f"Chamada sintática de {target} em {row['qualified_name']}",
                heading=str(row['qualified_name']), content_type='java_syntactic_relation', module='', product='', excerpt=excerpt,
                score=.45, confidence=min(.7, float(row.get('confidence') or .45)),
                entities={'source_sha256':(row['source_sha256'],), 'release_manifest_sha256':(manifest_hash,),
                          'relation_type':('syntactic_call',), 'target':(target,), 'citation':(str(row.get('citation') or ''),)},
            ))
    return tuple(result)

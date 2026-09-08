"""Repeatable CPU/memory probes on synthetic data; no accounts or model downloads.

Run with the project's Python: python scripts/benchmark_hotpaths.py --output report.json
Timing is diagnostic, never a machine-dependent test pass/fail threshold.
"""

from __future__ import annotations

import argparse
import json
import statistics
import struct
import sys
import tempfile
import time
import tracemalloc
import zipfile
from pathlib import Path

from vrsoft_extractor.mary.code_index import CODE_INDEX_SCHEMA_VERSION, JavaCodeIndex
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.retrieval import RetrievalService
from vrsoft_extractor.mary.retrieval.embedding_contract import DeterministicHashEmbedding
from vrsoft_extractor.mary.retrieval.generations import GenerationSemanticIndex


def measure(action, repeats):
    action()  # Warm imports and SQLite page caches on both versions.
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000)
    tracemalloc.start()
    try:
        action()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"median_ms": round(statistics.median(samples), 3), "peak_python_bytes": peak}


def benchmark_code_coverage(root, sources, repeats):
    jars = root / "ERP" / "releases" / "r1" / "jars"
    jars.mkdir(parents=True)
    for number in range(46):
        with zipfile.ZipFile(jars / f"library{number}.jar", "w") as archive:
            archive.writestr("Synthetic.class", b"synthetic benchmark fixture")
    catalog = ErpReleaseCatalog(root, expected_jar_count=46)
    manifest = catalog.import_release("r1")
    index = JavaCodeIndex(root, catalog=catalog)
    index.initialize()
    with index.store.connect() as conn:
        columns = [row for row in conn.execute("PRAGMA table_info(code_sources)") if row["name"] != "id"]
        names = [row["name"] for row in columns]
        defaults = {row["name"]: (0 if row["type"] == "INTEGER" else "") for row in columns}
        defaults.update({
            "schema_version": CODE_INDEX_SCHEMA_VERSION,
            "release_id": "r1", "release_hash": manifest["release_manifest_sha256"],
            "body": "class Synthetic { int value; } " * 130,
        })
        conn.executemany(
            f"INSERT INTO code_sources ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
            (tuple((defaults | {"source_key": str(i), "jar_relative_path": f"library{i % 46}.jar"})[name]
                   for name in names) for i in range(sources)),
        )
        conn.commit()
    return {
        "code_index_module": sys.modules[JavaCodeIndex.__module__].__file__,
        "code_sources": sources,
        "code_initialize": measure(index.initialize, repeats),
        "code_coverage": measure(lambda: index.coverage("r1"), repeats),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=1000)
    parser.add_argument("--chunks", type=int, default=8, help="Vector chunks per document")
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--code-sources", type=int, default=0, help="Also benchmark Java coverage with this many sources")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.documents, args.chunks, args.repeats) < 1:
        parser.error("documents, chunks and repeats must be positive")
    if args.code_sources < 0:
        parser.error("code-sources must be nonnegative")
    with tempfile.TemporaryDirectory(prefix="vr-hotpaths-") as directory:
        root = Path(directory)
        db = MaryDatabase(root / "knowledge.sqlite")
        text = "Synthetic invoice evidence. " * 160
        with db.connect() as conn:
            conn.executemany("""INSERT INTO documents
                (source,source_origin,source_id,title,url,module,review_status,synced_at,content_hash,markdown)
                VALUES('wiki','vrwiki',?,'Invoice','','Fiscal','approved','','fixture',?)""",
                [(str(i), text) for i in range(args.documents)])
        service = RetrievalService(KnowledgeRouter(db, root))
        backend = DeterministicHashEmbedding(dimension=64)
        index = GenerationSemanticIndex(root / "vectors.sqlite", backend)
        generation = index.rebuild([])["generation"]
        vector = struct.pack("<64f", *backend.embed_text("invoice"))
        with index.connect() as conn:
            conn.executemany("INSERT INTO vector_chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                (generation, f"wiki:{i:06}", chunk, "wiki", "vrwiki", "Fiscal", "", "", "hash", text[:500], vector)
                for i in range(args.documents) for chunk in range(args.chunks)
            ))
        report = {
            "database_module": sys.modules[MaryDatabase.__module__].__file__,
            "python": sys.version.split()[0],
            "documents": args.documents, "chunks_per_document": args.chunks, "repeats": args.repeats,
            "scope_signature": measure(service.scope_signature, args.repeats),
            "semantic_search": measure(lambda: index.search("invoice", 10), args.repeats),
        }
        if args.code_sources:
            report.update(benchmark_code_coverage(root / "code", args.code_sources, args.repeats))
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

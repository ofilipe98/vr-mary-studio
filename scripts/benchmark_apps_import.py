"""Benchmark script for Application Import and Snapshot performance."""
from __future__ import annotations

import sys
import tempfile
import time
import tracemalloc
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from test_erp_releases import _vr_jar

from vrsoft_extractor.mary.application_import import (
    preview_application_import,
    validate_preview_fingerprint,
)
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog


def setup_synthetic_package(root: Path, jar_count: int = 46) -> Path:
    source = root / "synthetic_package"
    source.mkdir(parents=True, exist_ok=True)
    for i in range(jar_count):
        jar_path = source / f"vr_app_{i:02d}.jar"
        _vr_jar(jar_path, (1, 0, 0, i))

    # Add pruned directories to simulate realistic development environment
    for ignored_name in [".git", ".venv", "node_modules", "build"]:
        ignored_dir = source / ignored_name
        ignored_dir.mkdir(parents=True, exist_ok=True)
        for j in range(100):
            dummy_file = ignored_dir / f"dummy_{j}.txt"
            dummy_file.write_text("irrelevant data", encoding="utf-8")

    return source


def benchmark_import_flow():
    with tempfile.TemporaryDirectory(prefix="vr-app-import-bench-") as tmp:
        tmp_path = Path(tmp)
        source = setup_synthetic_package(tmp_path, jar_count=46)
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        catalog = ErpReleaseCatalog(workspace, expected_jar_count=46)

        print("=== Benchmarking Application Import Flow (46 JARs + Pruned Dirs) ===")

        # 1. Pruned directory walk benchmark
        t0 = time.perf_counter()
        jars = catalog._source_jars(source)
        t_scan = (time.perf_counter() - t0) * 1000
        print(f"1. Pruned scan: {len(jars)} JARs found in {t_scan:.2f} ms")

        # 2. Preview benchmark
        progress_events = []
        tracemalloc.start()
        t0 = time.perf_counter()
        preview = preview_application_import(
            workspace,
            source,
            single=False,
            progress_callback=progress_events.append,
        )
        t_preview = (time.perf_counter() - t0) * 1000
        _, peak_preview = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"2. Preview: {len(preview['rows'])} rows, {len(progress_events)} progress events in {t_preview:.2f} ms (Peak RAM: {peak_preview / 1024:.1f} KB)")

        # 3. Confirmation validation (stat-based fingerprint check)
        t0 = time.perf_counter()
        validate_preview_fingerprint(source, preview["fingerprint"], single=False)
        t_val = (time.perf_counter() - t0) * 1000
        print(f"3. Fast preview fingerprint validation: {t_val:.2f} ms")

        # 4. Snapshot with known_hashes and streaming copy with digest
        known_hashes = {item["relative_path"]: item["sha256"] for item in preview["fingerprint"]}
        snapshot_progress = []

        tracemalloc.start()
        t0 = time.perf_counter()
        manifest = catalog.snapshot_detected_release(
            source,
            release_id="bench-rel",
            known_hashes=known_hashes,
            progress_callback=snapshot_progress.append,
        )
        t_snapshot = (time.perf_counter() - t0) * 1000
        _, peak_snapshot = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"4. Snapshot execution (streaming copy + digest): {manifest['jar_count']} JARs, {len(snapshot_progress)} events in {t_snapshot:.2f} ms (Peak RAM: {peak_snapshot / 1024:.1f} KB)")
        print("=== Benchmark completed successfully ===")


if __name__ == "__main__":
    benchmark_import_flow()

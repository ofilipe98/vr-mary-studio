"""Benchmark script for Application Import and Snapshot performance."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from test_erp_releases import _vr_jar

from vrsoft_extractor.mary.application_import import (
    preview_application_import,
    validate_preview_fingerprint,
)
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog

PRUNED_DIRS = [".git", ".venv", "venv", "node_modules", "build", "dist"]
VALID_NOISE_DIRS = ["src_valid", "lib_valid"]


def _write_noise_files(base: Path, count: int) -> int:
    base.mkdir(parents=True, exist_ok=True)
    for j in range(count):
        (base / f"irrelevant_{j:05d}.txt").write_text("irrelevant data", encoding="utf-8")
    return count


def setup_discovery_package(root: Path, irrelevant_total: int = 20000) -> tuple[Path, int]:
    """Create ~20k irrelevant files across pruned + valid dirs plus a few valid JARs."""
    source = root / "discovery_package"
    source.mkdir(parents=True, exist_ok=True)
    per_pruned = irrelevant_total * 3 // 4 // len(PRUNED_DIRS)
    per_valid = (irrelevant_total - per_pruned * len(PRUNED_DIRS)) // len(VALID_NOISE_DIRS)
    created = 0
    for name in PRUNED_DIRS:
        created += _write_noise_files(source / name / "nested", per_pruned)
    for name in VALID_NOISE_DIRS:
        created += _write_noise_files(source / name, per_valid)
    # Poucos JARs válidos fora das áreas podadas.
    _vr_jar(source / "vrmaster.jar", (1, 0, 0, 0))
    _vr_jar(source / "vrpdv.jar", (2, 0, 0, 0))
    _vr_jar(source / "sub" / "nested.jar", (3, 0, 0, 0))
    return source, created


def setup_synthetic_package(root: Path, jar_count: int = 46) -> Path:
    source = root / "synthetic_package"
    source.mkdir(parents=True, exist_ok=True)
    for i in range(jar_count):
        jar_path = source / f"vr_app_{i:02d}.jar"
        _vr_jar(jar_path, (1, 0, 0, i))

    # Small pruned noise to prove pruning still applies in the realistic flow.
    for ignored_name in [".git", ".venv", "node_modules", "build"]:
        ignored_dir = source / ignored_name
        ignored_dir.mkdir(parents=True, exist_ok=True)
        for j in range(100):
            (ignored_dir / f"dummy_{j}.txt").write_text("irrelevant data", encoding="utf-8")

    return source


def _timed(fn):
    t0 = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t0) * 1000.0


def benchmark_import_flow(output: str | None = None):
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="vr-app-import-bench-") as tmp:
        tmp_path = Path(tmp)

        # --- Cenário 1: discovery com ~20k arquivos irrelevantes ---
        print("=== Benchmark 1: discovery com ~20k arquivos irrelevantes ===")
        disc_source, irrelevant = setup_discovery_package(tmp_path)
        disc_workspace = tmp_path / "workspace_disc"
        disc_workspace.mkdir(parents=True, exist_ok=True)
        disc_catalog = ErpReleaseCatalog(disc_workspace)

        jars, t_source = _timed(lambda: disc_catalog._source_jars(disc_source))
        count, t_count = _timed(lambda: disc_catalog.count_source_jars(disc_source))
        print(f"_source_jars: {len(jars)} JARs em {t_source:.2f} ms")
        print(f"count_source_jars: {count} JARs em {t_count:.2f} ms")
        print(f"arquivos irrelevantes aproximados: {irrelevant}")
        results["discovery"] = {
            "source_jars_ms": t_source,
            "count_source_jars_ms": t_count,
            "jars_found": len(jars),
            "count_found": count,
            "irrelevant_files_approx": irrelevant,
        }

        # --- Cenário 2: pacote realista com 46 JARs ---
        print("=== Benchmark 2: pacote realista (46 JARs) ===")
        source = setup_synthetic_package(tmp_path, jar_count=46)
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        catalog = ErpReleaseCatalog(workspace, expected_jar_count=46)

        bench_start = time.perf_counter()
        first_progress_at: float | None = None
        preview_events: list[dict] = []

        def preview_cb(ev: dict) -> None:
            nonlocal first_progress_at
            if first_progress_at is None:
                first_progress_at = time.perf_counter()
            preview_events.append(ev)

        tracemalloc.start()
        t0 = time.perf_counter()
        preview = preview_application_import(
            workspace, source, single=False, progress_callback=preview_cb
        )
        preview_duration = (time.perf_counter() - t0) * 1000.0
        _, peak_preview = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        preview_ready_at = time.perf_counter()

        t0 = time.perf_counter()
        validate_preview_fingerprint(source, preview["fingerprint"], single=False)
        fingerprint_validation_duration = (time.perf_counter() - t0) * 1000.0

        known_hashes = {
            item["relative_path"]: item["sha256"] for item in preview["fingerprint"]
        }
        snapshot_events: list[dict] = []
        first_snapshot_progress: float | None = None

        def snapshot_cb(ev: dict) -> None:
            nonlocal first_snapshot_progress
            if first_snapshot_progress is None and ev.get("event") == "progress":
                first_snapshot_progress = time.perf_counter()
            snapshot_events.append(ev)

        tracemalloc.start()
        t0 = time.perf_counter()
        manifest = catalog.snapshot_detected_release(
            source,
            release_id="bench-rel",
            known_hashes=known_hashes,
            progress_callback=snapshot_cb,
        )
        snapshot_duration = (time.perf_counter() - t0) * 1000.0
        _, peak_snapshot = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        snapshot_done_at = time.perf_counter()

        time_to_first_progress = (
            (first_progress_at - bench_start) * 1000.0 if first_progress_at else float("nan")
        )
        time_to_preview_ready = (preview_ready_at - bench_start) * 1000.0
        time_to_snapshot_complete = (snapshot_done_at - bench_start) * 1000.0
        progress_event_count = len(preview_events) + len(snapshot_events)
        total_bytes = sum(int(a.get("size_bytes") or 0) for a in manifest.get("artifacts", []))
        throughput_mbs = (
            (total_bytes / 1024 / 1024) / (snapshot_duration / 1000.0)
            if snapshot_duration > 0
            else 0.0
        )

        print(f"time_to_first_progress: {time_to_first_progress:.2f} ms")
        print(f"time_to_preview_ready: {time_to_preview_ready:.2f} ms")
        print(f"time_to_snapshot_complete: {time_to_snapshot_complete:.2f} ms")
        print(f"preview_duration: {preview_duration:.2f} ms")
        print(f"fingerprint_validation_duration: {fingerprint_validation_duration:.2f} ms")
        print(f"snapshot_duration: {snapshot_duration:.2f} ms")
        print(f"progress_event_count: {progress_event_count}")
        print("time_to_first_row: N/A (rows são entregues em lote ao final da preview)")
        print(f"bytes totais: {total_bytes} ({throughput_mbs:.2f} MB/s no snapshot)")
        print(f"peak memory preview: {peak_preview / 1024:.1f} KB")
        print(f"peak memory snapshot: {peak_snapshot / 1024:.1f} KB")
        print(f"snapshot: {manifest['jar_count']} JARs, scope={manifest.get('analysis_scope')}")
        print("=== Benchmark completed successfully ===")

        results["realistic_46"] = {
            "time_to_first_progress_ms": time_to_first_progress,
            "time_to_preview_ready_ms": time_to_preview_ready,
            "time_to_snapshot_complete_ms": time_to_snapshot_complete,
            "preview_duration_ms": preview_duration,
            "fingerprint_validation_duration_ms": fingerprint_validation_duration,
            "snapshot_duration_ms": snapshot_duration,
            "progress_event_count": progress_event_count,
            "time_to_first_row": "N/A",
            "total_bytes": total_bytes,
            "throughput_mbs": throughput_mbs,
            "peak_preview_bytes": peak_preview,
            "peak_snapshot_bytes": peak_snapshot,
            "jar_count": manifest["jar_count"],
        }

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"results written to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    benchmark_import_flow(output=args.output)

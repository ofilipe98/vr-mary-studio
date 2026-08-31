from __future__ import annotations

from pathlib import Path

from vrsoft_extractor.mary.code_processing_audit import CodeProcessingAudit


def test_latest_filters_release_and_ignores_torn_jsonl_tail(tmp_path: Path) -> None:
    audit = CodeProcessingAudit(tmp_path)
    audit.record(
        "started",
        run_id="run-a",
        release_id="r1",
        manifest_sha256="a" * 64,
    )
    expected = audit.record(
        "paused",
        run_id="run-a",
        release_id="r1",
        manifest_sha256="a" * 64,
        details={"covered_jar_count": 3},
    )
    audit.record(
        "completed",
        run_id="run-b",
        release_id="r2",
        manifest_sha256="b" * 64,
    )
    with audit.path.open("a", encoding="utf-8") as stream:
        stream.write('{"event":"partial"')

    assert audit.latest(release_id="r1") == expected
    assert audit.latest(release_id="missing") is None


def test_eta_uses_local_median_and_requires_recorded_baseline(tmp_path: Path) -> None:
    audit = CodeProcessingAudit(tmp_path)
    manifest_hash = "a" * 64
    for run_id, baseline, covered, duration_ms in (
        ("run-1", 2, 4, 20_000),
        ("run-2", 4, 5, 30_000),
        ("run-3", 5, 7, 40_000),
    ):
        audit.record(
            "started",
            run_id=run_id,
            release_id="r1",
            manifest_sha256=manifest_hash,
            details={"covered_jar_count": baseline},
        )
        audit.record(
            "paused",
            run_id=run_id,
            release_id="r1",
            manifest_sha256=manifest_hash,
            details={
                "covered_jar_count": covered,
                "telemetry": {"wall_duration_ms": duration_ms},
            },
        )

    result = audit.estimate_remaining(
        release_id="r1",
        manifest_sha256=manifest_hash,
        remaining_jar_count=3,
    )

    assert result["available"] is True
    assert result["median_ms_per_jar"] == 20_000
    assert result["estimated_remaining_ms"] == 60_000
    assert result["sample_run_count"] == 3
    assert result["confidence"] == "medium"


def test_eta_does_not_guess_without_compatible_history(tmp_path: Path) -> None:
    result = CodeProcessingAudit(tmp_path).estimate_remaining(
        release_id="r1",
        manifest_sha256="a" * 64,
        remaining_jar_count=46,
    )

    assert result["available"] is False
    assert result["estimated_remaining_ms"] == 0

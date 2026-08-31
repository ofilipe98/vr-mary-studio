"""Append-only local audit trail for ERP code-processing jobs."""

from __future__ import annotations

import json
import os
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CodeProcessingAudit:
    """Persist release/hash-frozen lifecycle events without model involvement."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / "indice" / "codigo" / "processing-runs.jsonl"
        self._lock = threading.Lock()

    def record(
        self,
        event: str,
        *,
        run_id: str,
        release_id: str,
        manifest_sha256: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "event": str(event),
            "run_id": str(run_id),
            "release_id": str(release_id),
            "release_manifest_sha256": str(manifest_sha256),
            "details": dict(details or {}),
        }
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
        return payload

    def latest(self, *, release_id: str = "") -> dict[str, Any] | None:
        """Return the last valid local event, tolerating a torn final line."""

        selected_release = str(release_id or "").strip()
        if not self.path.is_file():
            return None
        latest: dict[str, Any] | None = None
        try:
            with self._lock, self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        payload = json.loads(line)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if selected_release and str(payload.get("release_id") or "") != selected_release:
                        continue
                    if not payload.get("run_id") or not payload.get("event"):
                        continue
                    latest = payload
        except (OSError, UnicodeError):
            return None
        return latest

    def estimate_remaining(
        self,
        *,
        release_id: str,
        manifest_sha256: str,
        remaining_jar_count: int,
    ) -> dict[str, Any]:
        """Estimate remaining wall time from completed local runs only.

        The estimate is deliberately local and deterministic.  It uses the
        median elapsed time per newly covered JAR, which is less sensitive to
        unusually large JARs than a mean.  Runs without a recorded baseline do
        not participate, so old audit data cannot create false precision.
        """

        remaining = max(0, int(remaining_jar_count))
        selected_release = str(release_id or "").strip()
        selected_hash = str(manifest_sha256 or "").strip()
        if not selected_release or not selected_hash:
            return _empty_estimate(remaining)

        runs: dict[str, dict[str, Any]] = {}
        for payload in self._events():
            if (
                str(payload.get("release_id") or "") != selected_release
                or str(payload.get("release_manifest_sha256") or "")
                != selected_hash
            ):
                continue
            run_id = str(payload.get("run_id") or "")
            details = payload.get("details")
            if not run_id or not isinstance(details, dict):
                continue
            run = runs.setdefault(run_id, {})
            event = str(payload.get("event") or "")
            if event == "started" and "covered_jar_count" in details:
                run["baseline"] = max(
                    0, int(details.get("covered_jar_count") or 0)
                )
            telemetry = details.get("telemetry")
            if isinstance(telemetry, dict) and "covered_jar_count" in details:
                run["covered"] = max(
                    int(run.get("covered") or 0),
                    max(0, int(details.get("covered_jar_count") or 0)),
                )
                run["wall_duration_ms"] = max(
                    int(run.get("wall_duration_ms") or 0),
                    max(0, int(telemetry.get("wall_duration_ms") or 0)),
                )

        samples: list[float] = []
        for run in runs.values():
            if "baseline" not in run or "covered" not in run:
                continue
            newly_covered = int(run["covered"]) - int(run["baseline"])
            duration_ms = int(run.get("wall_duration_ms") or 0)
            if newly_covered > 0 and duration_ms > 0:
                samples.append(duration_ms / newly_covered)
        if not samples:
            return _empty_estimate(remaining)

        median_ms = int(statistics.median(samples))
        return {
            "available": True,
            "remaining_jar_count": remaining,
            "estimated_remaining_ms": median_ms * remaining,
            "median_ms_per_jar": median_ms,
            "sample_run_count": len(samples),
            "confidence": "high" if len(samples) >= 5 else "medium" if len(samples) >= 2 else "low",
            "method": "local_median_per_newly_covered_jar",
        }

    def _events(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        events: list[dict[str, Any]] = []
        try:
            with self._lock, self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        payload = json.loads(line)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if isinstance(payload, dict):
                        events.append(payload)
        except (OSError, UnicodeError):
            return []
        return events


def _empty_estimate(remaining_jar_count: int) -> dict[str, Any]:
    return {
        "available": False,
        "remaining_jar_count": max(0, int(remaining_jar_count)),
        "estimated_remaining_ms": 0,
        "median_ms_per_jar": 0,
        "sample_run_count": 0,
        "confidence": "unavailable",
        "method": "local_median_per_newly_covered_jar",
    }


__all__ = ["CodeProcessingAudit"]

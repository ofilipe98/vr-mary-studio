from __future__ import annotations

from datetime import datetime

from vrsoft_extractor.mary.code_processing_policy import processing_window_status


def test_processing_windows_are_deterministic_and_cross_midnight() -> None:
    assert processing_window_status(
        "always", now=datetime(2026, 8, 31, 12, 0)
    )["allowed"] is True
    assert processing_window_status(
        "night", now=datetime(2026, 8, 31, 2, 0)
    )["allowed"] is True
    assert processing_window_status(
        "night", now=datetime(2026, 8, 31, 12, 0)
    )["allowed"] is False
    assert processing_window_status(
        "off_hours", now=datetime(2026, 8, 31, 23, 0)
    )["allowed"] is True
    assert processing_window_status(
        "off_hours", now=datetime(2026, 8, 31, 5, 59)
    )["allowed"] is True
    assert processing_window_status(
        "off_hours", now=datetime(2026, 8, 31, 6, 0)
    )["allowed"] is False

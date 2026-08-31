"""Deterministic local resource policy for ERP code processing."""

from __future__ import annotations

from datetime import datetime
from typing import Any


PROCESSING_WINDOWS: dict[str, tuple[int, int] | None] = {
    "always": None,
    "night": (0, 6 * 60),
    "off_hours": (18 * 60, 6 * 60),
}


def processing_window_status(
    policy: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected = str(policy or "always").strip().casefold()
    if selected not in PROCESSING_WINDOWS:
        selected = "always"
    window = PROCESSING_WINDOWS[selected]
    if window is None:
        return {
            "policy": selected,
            "allowed": True,
            "label": "qualquer horário",
            "start_minute": 0,
            "end_minute": 0,
        }
    current = now or datetime.now().astimezone()
    minute = current.hour * 60 + current.minute
    start, end = window
    allowed = (
        start <= minute < end
        if start < end
        else minute >= start or minute < end
    )
    return {
        "policy": selected,
        "allowed": allowed,
        "label": (
            "00:00-06:00" if selected == "night" else "18:00-06:00"
        ),
        "start_minute": start,
        "end_minute": end,
    }


__all__ = ["PROCESSING_WINDOWS", "processing_window_status"]

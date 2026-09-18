"""Shared test setup; provider integration scripts remain explicit manual runs."""

import os

import pytest


# Apply before test-module imports so individual QML files also work headlessly.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")


@pytest.fixture(autouse=True)
def fast_research(request, monkeypatch):
    """Exercise real retries/concurrency without production provider cooldowns."""
    if request.node.get_closest_marker("research_timing"):
        return
    from vrsoft_extractor.mary.execution import runner

    monkeypatch.setattr(runner, "RESEARCH_STAGGER_SECONDS", 0.0)
    monkeypatch.setattr(runner, "RESEARCH_RETRY_BACKOFF_SECONDS", 0.0)

"""A failed sync task must reach the toast surface as text, never as an object."""
import sqlite3
from unittest.mock import MagicMock, patch


def test_sync_failed_emits_text_for_database_errors():
    from vrsoft_extractor.mary.frontend.studio import StudioBridge

    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())
    toasts = []
    bridge.toastRequested.connect(lambda message, kind: toasts.append((message, kind)))

    with patch.object(bridge, "_append_sync_log"), \
            patch.object(bridge, "_append_log"), \
            patch.object(bridge, "_refresh_review_filter_values"):
        bridge._sync_failed(None, sqlite3.Error("database is locked"))

    assert toasts == [("database is locked", "error")]

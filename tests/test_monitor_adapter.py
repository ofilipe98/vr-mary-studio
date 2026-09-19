from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.monitor_adapter import (
    MONITOR_TOOL_NAMES,
    MonitorAdapter,
    MonitorConfigurationError,
    MonitorToolError,
    load_monitor_config,
)
from vrsoft_extractor.mary.mcp_server import run_mcp_server
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator


CLIENT_ID = "10000000-0000-0000-0000-000000000001"
CONVERSATION_ID = "30000000-0000-0000-0000-000000000001"
TOKEN = base64.urlsafe_b64encode(bytes(32)).decode("ascii").rstrip("=")


def _write_config(path: Path, **changes: Any) -> None:
    value = {
        "version": 1,
        "enabled": True,
        "base_url": "https://monitor.example",
        "client_id": CLIENT_ID,
        "session_token": TOKEN,
        **changes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body: bytes):
        self._body = body

    def read(self, _limit: int) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _WrongMediaResponse(_Response):
    headers = {"Content-Type": "text/html"}


class _Opener:
    def __init__(self, response: _Response):
        self.response = response
        self.requests = []

    def open(self, request, timeout: int):
        self.requests.append((request, timeout))
        return self.response


def test_monitor_adapter_keeps_authority_outside_tool_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "vrmonitor.json"
    _write_config(path)
    result = {
        "correlation_id": "a" * 32,
        "classification": "UNTRUSTED_DATA",
        "data": {
            "live": {
                "operation": "get_long_queries",
                "target": {
                    "host": "db.example",
                    "port": 5432,
                    "database": "vr",
                    "store": 1,
                },
                "observed_at": "2026-09-19T12:00:00Z",
                "rows": {"status": "fresh", "scope": "database", "rows": []},
                "truncated": False,
            }
        },
    }
    opener = _Opener(_Response(json.dumps(result).encode("utf-8")))
    monkeypatch.setattr("urllib.request.build_opener", lambda *_args: opener)
    adapter = MonitorAdapter.from_path(path)
    assert adapter is not None

    output = adapter.execute("get_long_queries", {"long_seconds": 30}, CONVERSATION_ID)

    assert output.parsed["classification"] == "UNTRUSTED_DATA"
    request, timeout = opener.requests[0]
    sent = json.loads(request.data)
    assert sent == {
        "client_id": CLIENT_ID,
        "harness_session_id": CONVERSATION_ID,
        "operation": "get_long_queries",
        "long_seconds": 30,
    }
    assert request.full_url == "https://monitor.example/api/harness/v1/tools"
    assert request.get_header("Authorization") == "Bearer " + TOKEN
    assert timeout == 22
    with pytest.raises(MonitorToolError):
        adapter.execute("get_connections", {"client_id": CLIENT_ID}, CONVERSATION_ID)


def test_monitor_adapter_rejects_non_json_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "vrmonitor.json"
    _write_config(path)
    opener = _Opener(_WrongMediaResponse(b"<html>not json</html>"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *_args: opener)
    adapter = MonitorAdapter.from_path(path)
    assert adapter is not None

    with pytest.raises(MonitorToolError, match="recusou"):
        adapter.execute("get_connections", {}, CONVERSATION_ID)


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "http://monitor.example"},
        {"base_url": "https://user@monitor.example"},
        {"base_url": "https://monitor.example:not-a-port"},
        {"client_id": "not-a-uuid"},
        {"session_token": "secret"},
        {"unknown": True},
    ],
)
def test_monitor_configuration_fails_closed(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    path = tmp_path / "vrmonitor.json"
    _write_config(path, **changes)
    with pytest.raises(MonitorConfigurationError):
        load_monitor_config(path)


def test_orchestrator_registers_monitor_tools_only_when_configured(
    tmp_path: Path,
) -> None:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "VRProject").resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.ensure_dirs()
    database = MaryDatabase(settings.database_path, root=settings.root)
    plain = ChatOrchestrator(settings, database)
    plain_id = plain.new_conversation("codex", "sol", defer_provider_start=True)
    assert not (
        MONITOR_TOOL_NAMES
        & {tool["name"] for tool in plain._conversation_options(plain_id).dynamic_tools}
    )
    plain.close()

    _write_config(settings.state_dir / "vrmonitor.json")
    configured = ChatOrchestrator(settings, database)
    conversation_id = configured.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    names = {
        tool["name"]
        for tool in configured._conversation_options(conversation_id).dynamic_tools
    }
    assert MONITOR_TOOL_NAMES <= names
    configured.close()


def test_mcp_exposes_same_monitor_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = (tmp_path / "VRProject").resolve()
    settings = MarySettings(
        app_dir=tmp_path.resolve(), root=root, old_root=(tmp_path / "old").resolve()
    )
    settings.ensure_dirs()
    MaryDatabase(settings.database_path, root=root)
    _write_config(settings.state_dir / "vrmonitor.json")
    incoming = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    )
    outgoing = io.StringIO()
    monkeypatch.setattr(sys, "stdin", incoming)
    monkeypatch.setattr(sys, "stdout", outgoing)

    run_mcp_server(root, monitor_session_id=CONVERSATION_ID)

    response = json.loads(outgoing.getvalue())
    names = {item["name"] for item in response["result"]["tools"]}
    assert MONITOR_TOOL_NAMES <= names

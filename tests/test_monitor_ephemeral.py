from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import pytest

from vrsoft_extractor.mary.models import ConversationOptions
from vrsoft_extractor.mary.monitor_ephemeral import (
    EPHEMERAL_CONTRACT_VERSION,
    MonitorEphemeralError,
    MonitorEphemeralSession,
    MonitorTurnRequest,
)


def monitor_options() -> ConversationOptions:
    return ConversationOptions(
        approval_profile=ConversationOptions.MONITOR_APPROVAL_PROFILE,
        monitor_mode=True,
    )


def tree_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def assert_canaries_absent(root: Path, *canaries: str) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_bytes()
        for canary in canaries:
            assert canary.encode() not in content, path


class EchoProvider:
    ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
    persists_content = False
    supports_resume = False

    def __init__(self, response: str) -> None:
        self._response = response
        self.retained_request: MonitorTurnRequest | None = None

    def run_turn(
        self,
        request: MonitorTurnRequest,
        cancel_event: threading.Event,
    ) -> bytearray:
        assert request.read_payload()
        assert not cancel_event.is_set()
        self.retained_request = request
        return bytearray(self._response.encode())


def test_success_keeps_content_out_of_disk_events_and_session_state(tmp_path: Path) -> None:
    input_canary = "MONITOR-INPUT-CANARY-9b1d"
    output_canary = "MONITOR-OUTPUT-CANARY-7a42"
    existing = tmp_path / "existing.sqlite"
    existing.write_bytes(b"existing non-monitor state")
    before = tree_snapshot(tmp_path)
    events = []
    provider = EchoProvider(output_canary)
    session = MonitorEphemeralSession(provider, monitor_options(), event_sink=events.append)

    result = session.run_turn(input_canary)

    assert result.read_text() == output_canary
    assert [event.kind for event in events] == ["started", "finished"]
    assert input_canary not in repr(session)
    assert output_canary not in repr(result)
    assert all(input_canary not in repr(event) for event in events)
    assert all(output_canary not in repr(event) for event in events)
    assert tree_snapshot(tmp_path) == before
    assert_canaries_absent(tmp_path, input_canary, output_canary)

    assert provider.retained_request is not None
    with pytest.raises(MonitorEphemeralError, match="monitor_payload_closed"):
        provider.retained_request.read_payload()
    result.close()
    with pytest.raises(MonitorEphemeralError, match="monitor_payload_closed"):
        result.read_text()


def test_provider_error_is_replaced_without_payload_or_provider_details(tmp_path: Path) -> None:
    input_canary = "MONITOR-ERROR-INPUT-180d"
    error_canary = "MONITOR-PROVIDER-ERROR-a553"
    events = []

    class FailingProvider:
        ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
        persists_content = False
        supports_resume = False

        def run_turn(self, request, cancel_event):
            assert request.read_payload() == input_canary
            raise RuntimeError(error_canary)

    session = MonitorEphemeralSession(
        FailingProvider(),
        monitor_options(),
        event_sink=events.append,
    )
    before = tree_snapshot(tmp_path)

    with pytest.raises(MonitorEphemeralError) as raised:
        session.run_turn(input_canary)

    rendered = "".join(traceback.format_exception(raised.value))
    assert str(raised.value) == "monitor_unavailable"
    assert raised.value.__context__ is None
    assert input_canary not in rendered
    assert error_canary not in rendered
    assert [event.kind for event in events] == ["started", "failed"]
    assert events[-1].code == "monitor_unavailable"
    assert tree_snapshot(tmp_path) == before
    assert_canaries_absent(tmp_path, input_canary, error_canary)


def test_cancel_discards_provider_output_and_clears_request(tmp_path: Path) -> None:
    input_canary = "MONITOR-CANCEL-INPUT-5f80"
    output_canary = "MONITOR-CANCEL-OUTPUT-d132"
    entered = threading.Event()
    retained_requests = []
    events = []

    class BlockingProvider:
        ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
        persists_content = False
        supports_resume = False

        def run_turn(self, request, cancel_event):
            assert request.read_payload() == input_canary
            retained_requests.append(request)
            entered.set()
            assert cancel_event.wait(5)
            return bytearray(output_canary.encode())

    session = MonitorEphemeralSession(
        BlockingProvider(),
        monitor_options(),
        event_sink=events.append,
    )
    failures = []

    def run() -> None:
        try:
            session.run_turn(input_canary)
        except Exception as exc:  # captured for the parent test thread
            failures.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(5)
    session.cancel()
    worker.join(5)

    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], MonitorEphemeralError)
    assert str(failures[0]) == "monitor_cancelled"
    assert [event.kind for event in events] == ["started", "cancelled"]
    with pytest.raises(MonitorEphemeralError, match="monitor_payload_closed"):
        retained_requests[0].read_payload()
    assert_canaries_absent(tmp_path, input_canary, output_canary)


def test_restart_has_new_identity_and_no_resume_or_history_surface() -> None:
    first = MonitorEphemeralSession(EchoProvider("first"), monitor_options())
    with first.run_turn("one") as result:
        assert result.read_text() == "first"
    first.close()

    restarted = MonitorEphemeralSession(EchoProvider("second"), monitor_options())
    assert restarted.runtime_id != first.runtime_id
    assert restarted.turns_completed == 0
    assert not hasattr(restarted, "resume")
    assert not hasattr(restarted, "history")
    assert not hasattr(restarted, "export")
    with restarted.run_turn("two") as result:
        assert result.read_text() == "second"


def test_contract_is_rejected_before_an_unapproved_provider_runs() -> None:
    class GenericProvider:
        called = False

        def run_turn(self, request, cancel_event):
            self.called = True
            return bytearray()

    provider = GenericProvider()

    with pytest.raises(MonitorEphemeralError, match="monitor_provider_contract_rejected"):
        MonitorEphemeralSession(provider, monitor_options())

    assert provider.called is False


def test_provider_request_has_no_central_identity_or_target_surface() -> None:
    provider = EchoProvider("response")
    session = MonitorEphemeralSession(provider, monitor_options())

    with session.run_turn("identity-looking data is still only payload"):
        pass

    assert provider.retained_request is not None
    assert set(provider.retained_request.__slots__) == {
        "_payload",
        "correlation_id",
        "runtime_id",
    }
    for authority in (
        "client_id",
        "credential",
        "harness_session_id",
        "target",
        "user_id",
    ):
        with pytest.raises(AttributeError):
            getattr(provider.retained_request, authority)


def test_abrupt_process_exit_leaves_no_content_in_working_tree(tmp_path: Path) -> None:
    canary = "MONITOR-CRASH-CANARY-1f39"
    script = """
import os
import sys
from vrsoft_extractor.mary.models import ConversationOptions
from vrsoft_extractor.mary.monitor_ephemeral import MonitorEphemeralSession

class CrashProvider:
    ephemeral_contract_version = 1
    persists_content = False
    supports_resume = False

    def run_turn(self, request, cancel_event):
        request.read_payload()
        os._exit(23)

options = ConversationOptions(approval_profile="monitor_restricted", monitor_mode=True)
MonitorEphemeralSession(CrashProvider(), options).run_turn(sys.stdin.read())
"""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    before = tree_snapshot(tmp_path)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        input=canary,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 23
    assert tree_snapshot(tmp_path) == before
    assert_canaries_absent(tmp_path, canary)


def test_ephemeral_boundary_has_no_persistence_or_generic_provider_dependencies() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "vrsoft_extractor"
        / "mary"
        / "monitor_ephemeral.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    forbidden = (
        "db",
        "logging",
        "orchestrator",
        "os",
        "pathlib",
        "provider_adapters",
        "repositories",
        "shutil",
        "tempfile",
    )
    assert not any(part in imported for imported in imports for part in forbidden)

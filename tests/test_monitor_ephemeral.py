from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vrsoft_extractor.mary.models import ConversationOptions
from vrsoft_extractor.mary.monitor_ephemeral import (
    EPHEMERAL_CONTRACT_VERSION,
    MAX_MONITOR_INPUT_BYTES,
    MAX_MONITOR_OUTPUT_BYTES,
    MonitorEphemeralError,
    MonitorEphemeralSession,
    MonitorTurnRequest,
)
from vrsoft_extractor.mary.monitor_egress import (
    PILOT_AUTH_METHOD,
    PILOT_ENDPOINT,
    PILOT_PROVIDER_ID,
    MonitorEgressEvidence,
    MonitorEgressManifest,
    attest_monitor_egress,
)
from vrsoft_extractor.mary.monitor_isolation import (
    MonitorIsolationEvidence,
    MonitorProcessManifest,
    attest_monitor_process,
    minimal_monitor_environment,
)


def monitor_options() -> ConversationOptions:
    return ConversationOptions(
        approval_profile=ConversationOptions.MONITOR_APPROVAL_PROFILE,
        monitor_mode=True,
    )


def isolation_attestation(root: Path):
    runtime = root / "monitor-runtime"
    working = runtime / "work"
    profile = runtime / "profile"
    temp = runtime / "temp"
    forbidden = root / "central-secrets"
    for directory in (runtime, working, profile, temp, forbidden):
        directory.mkdir(parents=True, exist_ok=True)
    executable = runtime / "provider-test.bin"
    executable.write_bytes(b"synthetic fixed provider")
    manifest = MonitorProcessManifest(
        executable=executable.resolve(),
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        arguments=("--monitor-restricted",),
        runtime_root=runtime.resolve(),
        working_directory=working.resolve(),
        profile_directory=profile.resolve(),
        temp_directory=temp.resolve(),
        environment=minimal_monitor_environment(profile, temp),
    )
    evidence = MonitorIsolationEvidence(
        brokered_out_of_process=True,
        dedicated_identity=True,
        environment_inherited=False,
        filesystem_acl_enforced=True,
        executable_allowlist_enforced=True,
    )
    return attest_monitor_process(
        manifest,
        evidence,
        forbidden_roots=(forbidden.resolve(),),
    )


def egress_attestation():
    today = datetime.now(timezone.utc).date()
    fields = ("input", "instructions", "model", "store", "stream")
    manifest = MonitorEgressManifest(
        provider_id=PILOT_PROVIDER_ID,
        provider_version="0.155.1",
        model_id="synthetic-model-2026-09-01",
        endpoint=PILOT_ENDPOINT,
        auth_method=PILOT_AUTH_METHOD,
        account_scope_sha256=hashlib.sha256(b"synthetic-project").hexdigest(),
        evidence_sha256=hashlib.sha256(b"synthetic-capture").hexdigest(),
        retention_mode="zero_data_retention",
        retention_days=0,
        telemetry_mode="disabled",
        request_fields=fields,
        store_content=False,
        web_search_enabled=False,
        plugins_enabled=False,
        sync_enabled=False,
        provider_fanout_enabled=False,
    )
    evidence = MonitorEgressEvidence(
        reviewed_on=today,
        expires_on=today + timedelta(days=30),
        observed_destinations=(PILOT_ENDPOINT,),
        observed_request_fields=fields,
        dedicated_provider_account=True,
        retention_control_verified=True,
        telemetry_disabled_verified=True,
        network_allowlist_enforced=True,
        direct_egress_denied=True,
        egress_capture_reviewed=True,
        payload_inventory_reviewed=True,
    )
    return attest_monitor_egress(manifest, evidence)


def isolated_session(provider, isolation, **kwargs):
    egress = egress_attestation()
    provider.isolation_manifest_digest = isolation.manifest_digest
    provider.provider_id = egress.provider_id
    provider.model_id = egress.model_id
    provider.egress_manifest_digest = egress.manifest_digest
    return MonitorEphemeralSession(
        provider,
        monitor_options(),
        isolation,
        egress,
        **kwargs,
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
        output,
        cancel_event: threading.Event,
    ) -> None:
        assert request.read_payload()
        assert not cancel_event.is_set()
        self.retained_request = request
        output.write(bytearray(self._response.encode()))

    def terminate_turn(self, correlation_id: str) -> None:
        pass


def test_success_keeps_content_out_of_disk_events_and_session_state(tmp_path: Path) -> None:
    input_canary = "MONITOR-INPUT-CANARY-9b1d"
    output_canary = "MONITOR-OUTPUT-CANARY-7a42"
    isolation = isolation_attestation(tmp_path)
    existing = tmp_path / "existing.sqlite"
    existing.write_bytes(b"existing non-monitor state")
    before = tree_snapshot(tmp_path)
    events = []
    provider = EchoProvider(output_canary)
    session = isolated_session(
        provider,
        isolation,
        event_sink=events.append,
    )

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

        def run_turn(self, request, output, cancel_event):
            assert request.read_payload() == input_canary
            raise RuntimeError(error_canary)

        def terminate_turn(self, correlation_id):
            pass

    isolation = isolation_attestation(tmp_path)
    session = isolated_session(
        FailingProvider(),
        isolation,
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

        def run_turn(self, request, output, cancel_event):
            assert request.read_payload() == input_canary
            retained_requests.append(request)
            entered.set()
            assert cancel_event.wait(5)
            output.write(bytearray(output_canary.encode()))

        def terminate_turn(self, correlation_id):
            pass

    session = isolated_session(
        BlockingProvider(),
        isolation_attestation(tmp_path),
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


def test_limits_reject_oversized_input_and_configuration(tmp_path: Path) -> None:
    isolation = isolation_attestation(tmp_path)
    provider = EchoProvider("unused")
    session = isolated_session(provider, isolation, max_input_bytes=8)

    with pytest.raises(MonitorEphemeralError, match="monitor_input_rejected"):
        session.run_turn("123456789")
    assert provider.retained_request is None

    with pytest.raises(ValueError, match="input limit"):
        isolated_session(
            EchoProvider("unused"),
            isolation,
            max_input_bytes=MAX_MONITOR_INPUT_BYTES + 1,
        )
    with pytest.raises(ValueError, match="output limit"):
        isolated_session(
            EchoProvider("unused"),
            isolation,
            max_output_bytes=MAX_MONITOR_OUTPUT_BYTES + 1,
        )


def test_continuous_output_is_rejected_before_capture_exceeds_limit(
    tmp_path: Path,
) -> None:
    chunks_written = 0
    events = []

    class StreamingProvider:
        ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
        persists_content = False
        supports_resume = False

        def run_turn(self, request, output, cancel_event):
            nonlocal chunks_written
            while True:
                output.write(b"12345678")
                chunks_written += 1

        def terminate_turn(self, correlation_id):
            pass

    session = isolated_session(
        StreamingProvider(),
        isolation_attestation(tmp_path),
        event_sink=events.append,
        max_output_bytes=32,
        max_output_chunk_bytes=8,
    )

    with pytest.raises(MonitorEphemeralError, match="monitor_output_rejected"):
        session.run_turn("bounded")

    assert chunks_written == 4
    assert events[-1].code == "monitor_output_rejected"
    assert events[-1].output_bytes == 0


def test_timeout_forces_termination_when_provider_ignores_cancellation(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    released = threading.Event()
    terminated = []

    class IgnoringProvider:
        ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
        persists_content = False
        supports_resume = False

        def run_turn(self, request, output, cancel_event):
            entered.set()
            released.wait(5)

        def terminate_turn(self, correlation_id):
            terminated.append(correlation_id)
            released.set()

    session = isolated_session(
        IgnoringProvider(),
        isolation_attestation(tmp_path),
        turn_timeout_seconds=0.03,
        terminate_grace_seconds=0.2,
    )
    started = time.monotonic()

    with pytest.raises(MonitorEphemeralError, match="monitor_timeout"):
        session.run_turn("timeout")

    assert entered.is_set()
    assert len(terminated) == 1
    assert time.monotonic() - started < 1


def test_close_cancels_active_turn_and_forces_termination(tmp_path: Path) -> None:
    entered = threading.Event()
    released = threading.Event()
    terminated = []
    failures = []

    class DisconnectedProvider:
        ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
        persists_content = False
        supports_resume = False

        def run_turn(self, request, output, cancel_event):
            entered.set()
            released.wait(5)

        def terminate_turn(self, correlation_id):
            terminated.append(correlation_id)
            released.set()

    session = isolated_session(
        DisconnectedProvider(),
        isolation_attestation(tmp_path),
        terminate_grace_seconds=0.2,
    )

    def run() -> None:
        try:
            session.run_turn("disconnect")
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(2)
    session.close()
    worker.join(2)

    assert not worker.is_alive()
    assert len(terminated) == 1
    assert len(failures) == 1
    assert str(failures[0]) == "monitor_cancelled"


def test_concurrent_turn_is_rejected_without_queue(tmp_path: Path) -> None:
    entered = threading.Event()
    released = threading.Event()
    failures = []

    class BusyProvider:
        ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
        persists_content = False
        supports_resume = False

        def run_turn(self, request, output, cancel_event):
            entered.set()
            released.wait(5)

        def terminate_turn(self, correlation_id):
            released.set()

    session = isolated_session(BusyProvider(), isolation_attestation(tmp_path))

    def run() -> None:
        try:
            session.run_turn("first")
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(2)
    with pytest.raises(MonitorEphemeralError, match="monitor_busy"):
        session.run_turn("second")
    session.cancel()
    worker.join(2)

    assert not worker.is_alive()
    assert len(failures) == 1
    assert str(failures[0]) == "monitor_cancelled"


def test_restart_has_new_identity_and_no_resume_or_history_surface(tmp_path: Path) -> None:
    isolation = isolation_attestation(tmp_path)
    first = isolated_session(EchoProvider("first"), isolation)
    with first.run_turn("one") as result:
        assert result.read_text() == "first"
    first.close()

    restarted = isolated_session(EchoProvider("second"), isolation)
    assert restarted.runtime_id != first.runtime_id
    assert restarted.turns_completed == 0
    assert not hasattr(restarted, "resume")
    assert not hasattr(restarted, "history")
    assert not hasattr(restarted, "export")
    with restarted.run_turn("two") as result:
        assert result.read_text() == "second"


def test_contract_is_rejected_before_an_unapproved_provider_runs(tmp_path: Path) -> None:
    class GenericProvider:
        called = False

        def run_turn(self, request, cancel_event):
            self.called = True
            return bytearray()

    provider = GenericProvider()

    with pytest.raises(MonitorEphemeralError, match="monitor_provider_contract_rejected"):
        MonitorEphemeralSession(
            provider,
            monitor_options(),
            isolation_attestation(tmp_path),
            object(),
        )

    assert provider.called is False


def test_session_rejects_missing_or_mismatched_egress_attestation(
    tmp_path: Path,
) -> None:
    isolation = isolation_attestation(tmp_path)
    egress = egress_attestation()
    provider = EchoProvider("blocked")
    provider.isolation_manifest_digest = isolation.manifest_digest
    provider.provider_id = egress.provider_id
    provider.model_id = egress.model_id
    provider.egress_manifest_digest = egress.manifest_digest

    with pytest.raises(MonitorEphemeralError, match="monitor_egress_required"):
        MonitorEphemeralSession(provider, monitor_options(), isolation, object())

    provider.model_id = "different-model"
    with pytest.raises(MonitorEphemeralError, match="monitor_egress_required"):
        MonitorEphemeralSession(provider, monitor_options(), isolation, egress)
    assert provider.retained_request is None


def test_provider_request_has_no_central_identity_or_target_surface(tmp_path: Path) -> None:
    provider = EchoProvider("response")
    session = isolated_session(
        provider,
        isolation_attestation(tmp_path),
    )

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
    isolation_attestation(tmp_path)
    script = """
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from vrsoft_extractor.mary.models import ConversationOptions
from vrsoft_extractor.mary.monitor_ephemeral import MonitorEphemeralSession
from vrsoft_extractor.mary.monitor_egress import (
    PILOT_AUTH_METHOD,
    PILOT_ENDPOINT,
    PILOT_PROVIDER_ID,
    MonitorEgressEvidence,
    MonitorEgressManifest,
    attest_monitor_egress,
)
from vrsoft_extractor.mary.monitor_isolation import (
    MonitorIsolationEvidence,
    MonitorProcessManifest,
    attest_monitor_process,
    minimal_monitor_environment,
)

class CrashProvider:
    ephemeral_contract_version = 2
    persists_content = False
    supports_resume = False

    def run_turn(self, request, output, cancel_event):
        request.read_payload()
        os._exit(23)

    def terminate_turn(self, correlation_id):
        pass

options = ConversationOptions(approval_profile="monitor_restricted", monitor_mode=True)
root = Path.cwd()
runtime = root / "monitor-runtime"
executable = runtime / "provider-test.bin"
manifest = MonitorProcessManifest(
    executable=executable.resolve(),
    executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
    arguments=("--monitor-restricted",),
    runtime_root=runtime.resolve(),
    working_directory=(runtime / "work").resolve(),
    profile_directory=(runtime / "profile").resolve(),
    temp_directory=(runtime / "temp").resolve(),
    environment=minimal_monitor_environment(runtime / "profile", runtime / "temp"),
)
evidence = MonitorIsolationEvidence(True, True, False, True, True)
isolation = attest_monitor_process(
    manifest, evidence, forbidden_roots=((root / "central-secrets").resolve(),)
)
today = datetime.now(timezone.utc).date()
fields = ("input", "instructions", "model", "store", "stream")
egress_manifest = MonitorEgressManifest(
    PILOT_PROVIDER_ID,
    "0.155.1",
    "synthetic-model-2026-09-01",
    PILOT_ENDPOINT,
    PILOT_AUTH_METHOD,
    hashlib.sha256(b"synthetic-project").hexdigest(),
    hashlib.sha256(b"synthetic-capture").hexdigest(),
    "zero_data_retention",
    0,
    "disabled",
    fields,
    False,
    False,
    False,
    False,
    False,
)
egress_evidence = MonitorEgressEvidence(
    today,
    today + timedelta(days=30),
    (PILOT_ENDPOINT,),
    fields,
    True,
    True,
    True,
    True,
    True,
    True,
    True,
)
egress = attest_monitor_egress(egress_manifest, egress_evidence)
provider = CrashProvider()
provider.isolation_manifest_digest = isolation.manifest_digest
provider.provider_id = egress.provider_id
provider.model_id = egress.model_id
provider.egress_manifest_digest = egress.manifest_digest
MonitorEphemeralSession(provider, options, isolation, egress).run_turn(sys.stdin.read())
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

from __future__ import annotations

import ast
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from vrsoft_extractor.mary.models import ConversationOptions
from vrsoft_extractor.mary.monitor_ephemeral import (
    EPHEMERAL_CONTRACT_VERSION,
    MonitorEphemeralError,
    MonitorEphemeralSession,
)
from vrsoft_extractor.mary.monitor_isolation import (
    MonitorIsolationAttestation,
    MonitorIsolationError,
    MonitorIsolationEvidence,
    MonitorProcessManifest,
    attest_monitor_process,
    isolation_attested,
    minimal_monitor_environment,
)


def process_policy(tmp_path: Path):
    runtime = tmp_path / "runtime"
    working = runtime / "work"
    profile = runtime / "profile"
    temp = runtime / "temp"
    forbidden = tmp_path / "central-secrets"
    outside = tmp_path / "outside"
    for directory in (runtime, working, profile, temp, forbidden, outside):
        directory.mkdir(parents=True)
    executable = runtime / "provider.bin"
    executable.write_bytes(b"fixed provider binary")
    outside_executable = outside / "provider.bin"
    outside_executable.write_bytes(executable.read_bytes())
    manifest = MonitorProcessManifest(
        executable=executable.resolve(),
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        arguments=("--restricted",),
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
    return manifest, evidence, forbidden.resolve(), outside.resolve(), outside_executable


def test_manifest_attestation_uses_fixed_binary_minimal_environment_and_redaction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "MONITOR-PARENT-SECRET")
    monkeypatch.setenv("PATH", "MONITOR-PARENT-PATH")
    manifest, evidence, forbidden, _, _ = process_policy(tmp_path)

    attestation = attest_monitor_process(
        manifest,
        evidence,
        forbidden_roots=(forbidden,),
    )

    environment = dict(manifest.environment)
    assert isolation_attested(attestation)
    assert "DATABASE_URL" not in environment
    assert "PATH" not in environment
    assert "MONITOR-PARENT" not in repr(manifest)
    assert str(manifest.executable) not in repr(attestation)
    assert repr(evidence) == "MonitorIsolationEvidence(redacted)"


def test_manifest_rejects_executable_arguments_environment_and_filesystem_escape(
    tmp_path: Path,
) -> None:
    manifest, evidence, forbidden, outside, outside_executable = process_policy(tmp_path)
    cases = {
        "hash": replace(manifest, executable_sha256="0" * 64),
        "executable": replace(manifest, executable=outside_executable.resolve()),
        "arguments": replace(manifest, arguments=("--restricted\n--escape",)),
        "environment_key": replace(
            manifest,
            environment=manifest.environment + (("PATH", "MONITOR-PARENT-PATH"),),
        ),
        "environment_path": replace(
            manifest,
            environment=tuple(
                (key, str(outside) if key == "TEMP" else value)
                for key, value in manifest.environment
            ),
        ),
        "working_directory": replace(manifest, working_directory=outside),
    }
    for changed in cases.values():
        with pytest.raises(MonitorIsolationError):
            attest_monitor_process(changed, evidence, forbidden_roots=(forbidden,))

    with pytest.raises(MonitorIsolationError, match="monitor_forbidden_root_overlap"):
        attest_monitor_process(
            manifest,
            evidence,
            forbidden_roots=(manifest.runtime_root,),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"brokered_out_of_process": False},
        {"dedicated_identity": False},
        {"environment_inherited": True},
        {"filesystem_acl_enforced": False},
        {"executable_allowlist_enforced": False},
    ],
)
def test_manifest_rejects_unproven_broker_controls(tmp_path: Path, change) -> None:
    manifest, evidence, forbidden, _, _ = process_policy(tmp_path)

    with pytest.raises(
        MonitorIsolationError,
        match="monitor_isolation_evidence_rejected",
    ):
        attest_monitor_process(
            manifest,
            replace(evidence, **change),
            forbidden_roots=(forbidden,),
        )


def test_ephemeral_session_refuses_missing_forged_or_mismatched_attestation(
    tmp_path: Path,
) -> None:
    class Provider:
        ephemeral_contract_version = EPHEMERAL_CONTRACT_VERSION
        persists_content = False
        supports_resume = False
        called = False

        def run_turn(self, request, cancel_event):
            self.called = True
            return bytearray()

    options = ConversationOptions(
        approval_profile=ConversationOptions.MONITOR_APPROVAL_PROFILE,
        monitor_mode=True,
    )
    provider = Provider()

    with pytest.raises(MonitorEphemeralError, match="monitor_isolation_required"):
        MonitorEphemeralSession(provider, options, object(), object())
    with pytest.raises(MonitorIsolationError, match="monitor_isolation_invalid"):
        MonitorIsolationAttestation("a" * 64, object())
    manifest, evidence, forbidden, _, _ = process_policy(tmp_path)
    attestation = attest_monitor_process(
        manifest,
        evidence,
        forbidden_roots=(forbidden,),
    )
    provider.isolation_manifest_digest = "0" * 64
    with pytest.raises(MonitorEphemeralError, match="monitor_isolation_required"):
        MonitorEphemeralSession(provider, options, attestation, object())
    assert provider.called is False


def test_isolation_policy_cannot_launch_or_reuse_generic_provider_code() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "vrsoft_extractor"
        / "mary"
        / "monitor_isolation.py"
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

    assert "subprocess" not in imports
    assert not any("provider_adapters" in imported for imported in imports)

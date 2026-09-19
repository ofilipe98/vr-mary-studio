from __future__ import annotations

import ast
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
from vrsoft_extractor.mary.monitor_supply_chain import (
    MonitorArtifact,
    MonitorSupplyChainAttestation,
    MonitorSupplyChainError,
    MonitorSupplyChainEvidence,
    MonitorSupplyChainManifest,
    attest_monitor_supply_chain,
    supply_chain_attested,
)


TODAY = datetime.now(timezone.utc).date()


def prerequisite_attestations(tmp_path: Path):
    runtime = tmp_path / "runtime"
    work = runtime / "work"
    profile = runtime / "profile"
    temp = runtime / "temp"
    forbidden = tmp_path / "central-secrets"
    for directory in (runtime, work, profile, temp, forbidden):
        directory.mkdir(parents=True)
    executable = runtime / "codex.exe"
    executable.write_bytes(b"synthetic codex executable")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    process_manifest = MonitorProcessManifest(
        executable=executable.resolve(),
        executable_sha256=executable_sha256,
        arguments=("app-server", "--monitor-restricted"),
        runtime_root=runtime.resolve(),
        working_directory=work.resolve(),
        profile_directory=profile.resolve(),
        temp_directory=temp.resolve(),
        environment=minimal_monitor_environment(profile, temp),
    )
    isolation = attest_monitor_process(
        process_manifest,
        MonitorIsolationEvidence(True, True, False, True, True),
        forbidden_roots=(forbidden.resolve(),),
    )

    fields = ("input", "instructions", "model", "store", "stream")
    egress_manifest = MonitorEgressManifest(
        provider_id=PILOT_PROVIDER_ID,
        provider_version="0.155.1",
        model_id="synthetic-model-2026-09-01",
        endpoint=PILOT_ENDPOINT,
        auth_method=PILOT_AUTH_METHOD,
        account_scope_sha256=hashlib.sha256(b"synthetic-project").hexdigest(),
        evidence_sha256=hashlib.sha256(b"synthetic-egress").hexdigest(),
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
    egress = attest_monitor_egress(
        egress_manifest,
        MonitorEgressEvidence(
            reviewed_on=TODAY,
            expires_on=TODAY + timedelta(days=30),
            observed_destinations=(PILOT_ENDPOINT,),
            observed_request_fields=fields,
            dedicated_provider_account=True,
            retention_control_verified=True,
            telemetry_disabled_verified=True,
            network_allowlist_enforced=True,
            direct_egress_denied=True,
            egress_capture_reviewed=True,
            payload_inventory_reviewed=True,
        ),
    )
    return isolation, egress


def supply_policy(tmp_path: Path):
    isolation, egress = prerequisite_attestations(tmp_path)
    artifact = MonitorArtifact(
        name=PILOT_PROVIDER_ID,
        version=egress.provider_version,
        sha256=isolation.executable_sha256,
        source=(
            "https://github.com/openai/codex/releases/tag/"
            f"rust-v{egress.provider_version}"
        ),
        signer_certificate_sha256=hashlib.sha256(b"synthetic-signer").hexdigest(),
    )
    manifest = MonitorSupplyChainManifest(
        studio_revision="a" * 40,
        artifacts=(artifact,),
        dependency_lock_sha256=hashlib.sha256(b"synthetic-lock").hexdigest(),
        configuration_sha256=hashlib.sha256(b"synthetic-config").hexdigest(),
        isolation_manifest_digest=isolation.manifest_digest,
        egress_manifest_digest=egress.manifest_digest,
        update_policy="offline_reviewed_bundle",
    )
    evidence = MonitorSupplyChainEvidence(
        reviewed_on=TODAY,
        expires_on=TODAY + timedelta(days=30),
        evidence_sha256=hashlib.sha256(b"synthetic-release-report").hexdigest(),
        offline_bundle_built=True,
        artifact_hashes_verified=True,
        signatures_verified=True,
        dependency_distributions_hashed=True,
        source_reviewed=True,
        vulnerability_reviewed=True,
        auto_update_disabled=True,
        installer_network_denied=True,
        update_requires_reapproval=True,
    )
    return manifest, evidence, isolation, egress


def test_attestation_binds_exact_artifact_process_egress_and_revision(
    tmp_path: Path,
) -> None:
    manifest, evidence, isolation, egress = supply_policy(tmp_path)

    attestation = attest_monitor_supply_chain(
        manifest, evidence, isolation, egress
    )

    assert supply_chain_attested(attestation)
    assert attestation.provider_version == egress.provider_version
    assert attestation.isolation_manifest_digest == isolation.manifest_digest
    assert attestation.egress_manifest_digest == egress.manifest_digest
    assert repr(manifest) == "MonitorSupplyChainManifest(redacted)"
    assert repr(evidence) == "MonitorSupplyChainEvidence(redacted)"
    assert repr(manifest.artifacts[0]) == "MonitorArtifact(redacted)"


@pytest.mark.parametrize(
    "change",
    [
        {"studio_revision": "main"},
        {"dependency_lock_sha256": "unlocked"},
        {"configuration_sha256": "mutable"},
        {"isolation_manifest_digest": "0" * 64},
        {"egress_manifest_digest": "0" * 64},
        {"update_policy": "automatic"},
        {"artifacts": ()},
    ],
)
def test_manifest_rejects_unpinned_chain(change, tmp_path: Path) -> None:
    manifest, evidence, isolation, egress = supply_policy(tmp_path)

    with pytest.raises(MonitorSupplyChainError):
        attest_monitor_supply_chain(
            replace(manifest, **change), evidence, isolation, egress
        )


@pytest.mark.parametrize(
    "change",
    [
        {"name": "claude"},
        {"version": "0.154.0"},
        {"sha256": "0" * 64},
        {"source": "https://example.com/codex.exe"},
        {
            "source": (
                "https://github.com/openai/codex/releases/tag/"
                "rust-v0.155.1?latest=true"
            )
        },
        {"signer_certificate_sha256": "unsigned"},
    ],
)
def test_manifest_rejects_artifact_drift(change, tmp_path: Path) -> None:
    manifest, evidence, isolation, egress = supply_policy(tmp_path)
    artifact = replace(manifest.artifacts[0], **change)

    with pytest.raises(MonitorSupplyChainError):
        attest_monitor_supply_chain(
            replace(manifest, artifacts=(artifact,)), evidence, isolation, egress
        )


@pytest.mark.parametrize(
    "field",
    [
        "offline_bundle_built",
        "artifact_hashes_verified",
        "signatures_verified",
        "dependency_distributions_hashed",
        "source_reviewed",
        "vulnerability_reviewed",
        "auto_update_disabled",
        "installer_network_denied",
        "update_requires_reapproval",
    ],
)
def test_attestation_rejects_missing_release_evidence(
    field: str,
    tmp_path: Path,
) -> None:
    manifest, evidence, isolation, egress = supply_policy(tmp_path)

    with pytest.raises(
        MonitorSupplyChainError, match="monitor_supply_chain_evidence_rejected"
    ):
        attest_monitor_supply_chain(
            manifest, replace(evidence, **{field: False}), isolation, egress
        )


def test_attestation_rejects_expired_or_overlong_review(tmp_path: Path) -> None:
    manifest, evidence, isolation, egress = supply_policy(tmp_path)
    cases = (
        replace(evidence, expires_on=TODAY - timedelta(days=1)),
        replace(evidence, expires_on=evidence.reviewed_on + timedelta(days=91)),
    )

    for changed in cases:
        with pytest.raises(MonitorSupplyChainError):
            attest_monitor_supply_chain(manifest, changed, isolation, egress)


def test_attestation_cannot_be_forged() -> None:
    with pytest.raises(
        MonitorSupplyChainError, match="monitor_supply_chain_invalid"
    ):
        MonitorSupplyChainAttestation(
            "a" * 64,
            "b" * 40,
            "0.155.1",
            "c" * 64,
            "d" * 64,
            object(),
        )


def test_supply_chain_module_cannot_download_install_or_launch() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "vrsoft_extractor"
        / "mary"
        / "monitor_supply_chain.py"
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
        "httpx",
        "provider_adapters",
        "provider_cli",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    )
    assert not any(part in imported for imported in imports for part in forbidden)

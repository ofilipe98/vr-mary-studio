from __future__ import annotations

import ast
import hashlib
from dataclasses import fields, replace
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
from vrsoft_extractor.mary.monitor_ephemeral import EPHEMERAL_CONTRACT_VERSION
from vrsoft_extractor.mary.monitor_isolation import (
    MonitorIsolationEvidence,
    MonitorProcessManifest,
    attest_monitor_process,
    minimal_monitor_environment,
)
from vrsoft_extractor.mary.monitor_release_gate import (
    MonitorDynamicValidationEvidence,
    MonitorReleaseApproval,
    MonitorReleaseGateError,
    approve_monitor_release,
    release_approved,
)
from vrsoft_extractor.mary.monitor_supply_chain import (
    MonitorArtifact,
    MonitorSupplyChainEvidence,
    MonitorSupplyChainManifest,
    attest_monitor_supply_chain,
)


TODAY = datetime.now(timezone.utc).date()


def security_attestations(
    tmp_path: Path,
    *,
    model_id: str = "synthetic-model-2026-09-01",
):
    runtime = tmp_path / "runtime"
    work = runtime / "work"
    profile = runtime / "profile"
    temp = runtime / "temp"
    forbidden = tmp_path / "central-secrets"
    for directory in (runtime, work, profile, temp, forbidden):
        directory.mkdir(parents=True)
    executable = runtime / "codex.exe"
    executable.write_bytes(b"synthetic release-gate executable")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    isolation = attest_monitor_process(
        MonitorProcessManifest(
            executable=executable.resolve(),
            executable_sha256=executable_sha256,
            arguments=("app-server", "--monitor-restricted"),
            runtime_root=runtime.resolve(),
            working_directory=work.resolve(),
            profile_directory=profile.resolve(),
            temp_directory=temp.resolve(),
            environment=minimal_monitor_environment(profile, temp),
        ),
        MonitorIsolationEvidence(True, True, False, True, True),
        forbidden_roots=(forbidden.resolve(),),
    )
    request_fields = ("input", "instructions", "model", "store", "stream")
    egress = attest_monitor_egress(
        MonitorEgressManifest(
            provider_id=PILOT_PROVIDER_ID,
            provider_version="0.155.1",
            model_id=model_id,
            endpoint=PILOT_ENDPOINT,
            auth_method=PILOT_AUTH_METHOD,
            account_scope_sha256=hashlib.sha256(b"synthetic-project").hexdigest(),
            evidence_sha256=hashlib.sha256(b"synthetic-egress").hexdigest(),
            retention_mode="zero_data_retention",
            retention_days=0,
            telemetry_mode="disabled",
            request_fields=request_fields,
            store_content=False,
            web_search_enabled=False,
            plugins_enabled=False,
            sync_enabled=False,
            provider_fanout_enabled=False,
        ),
        MonitorEgressEvidence(
            reviewed_on=TODAY,
            expires_on=TODAY + timedelta(days=30),
            observed_destinations=(PILOT_ENDPOINT,),
            observed_request_fields=request_fields,
            dedicated_provider_account=True,
            retention_control_verified=True,
            telemetry_disabled_verified=True,
            network_allowlist_enforced=True,
            direct_egress_denied=True,
            egress_capture_reviewed=True,
            payload_inventory_reviewed=True,
        ),
    )
    artifact = MonitorArtifact(
        name=PILOT_PROVIDER_ID,
        version=egress.provider_version,
        sha256=isolation.executable_sha256,
        source="https://github.com/openai/codex/releases/tag/rust-v0.155.1",
        signer_certificate_sha256=hashlib.sha256(b"synthetic-signer").hexdigest(),
    )
    supply_chain = attest_monitor_supply_chain(
        MonitorSupplyChainManifest(
            studio_revision="a" * 40,
            artifacts=(artifact,),
            dependency_lock_sha256=hashlib.sha256(b"synthetic-lock").hexdigest(),
            configuration_sha256=hashlib.sha256(b"synthetic-config").hexdigest(),
            isolation_manifest_digest=isolation.manifest_digest,
            egress_manifest_digest=egress.manifest_digest,
            update_policy="offline_reviewed_bundle",
        ),
        MonitorSupplyChainEvidence(
            reviewed_on=TODAY,
            expires_on=TODAY + timedelta(days=30),
            evidence_sha256=hashlib.sha256(b"synthetic-supply").hexdigest(),
            offline_bundle_built=True,
            artifact_hashes_verified=True,
            signatures_verified=True,
            dependency_distributions_hashed=True,
            source_reviewed=True,
            vulnerability_reviewed=True,
            auto_update_disabled=True,
            installer_network_denied=True,
            update_requires_reapproval=True,
        ),
        isolation,
        egress,
    )
    return isolation, egress, supply_chain


def complete_evidence() -> MonitorDynamicValidationEvidence:
    digest = hashlib.sha256(b"synthetic operational evidence").hexdigest()
    return MonitorDynamicValidationEvidence(
        tested_on=TODAY,
        expires_on=TODAY + timedelta(days=14),
        studio_revision="a" * 40,
        report_sha256=digest,
        canary_set_sha256=digest,
        network_capture_sha256=digest,
        security_approval_sha256=digest,
        data_owner_approval_sha256=digest,
        operations_approval_sha256=digest,
        ephemeral_contract_version=EPHEMERAL_CONTRACT_VERSION,
        observed_max_input_bytes=64 * 1024,
        observed_max_output_bytes=1024 * 1024,
        observed_max_output_chunk_bytes=64 * 1024,
        observed_turn_timeout_seconds=30.0,
        observed_termination_grace_seconds=1.0,
        actual_broker_used=True,
        actual_provider_used=True,
        dedicated_service_identity_verified=True,
        central_directory_denials_verified=True,
        provider_account_policy_verified=True,
        zero_data_retention_verified=True,
        telemetry_disabled_verified=True,
        egress_destinations_verified=True,
        payload_inventory_verified=True,
        success_canaries_absent=True,
        provider_error_canaries_absent=True,
        cancellation_canaries_absent=True,
        crash_canaries_absent=True,
        restart_canaries_absent=True,
        cross_user_scope_verified=True,
        cross_client_scope_verified=True,
        identity_tampering_denied=True,
        revocation_before_delivery_verified=True,
        oversized_input_denied=True,
        continuous_output_bounded=True,
        ignored_cancel_terminated=True,
        disconnect_terminated=True,
        concurrency_without_queue_verified=True,
        executable_drift_denied=True,
        configuration_drift_denied=True,
        post_run_artifact_scan_clean=True,
        regression_suite_passed=True,
        vulnerability_review_passed=True,
        synthetic_dataset_only=True,
    )


def test_complete_synthetic_matrix_exercises_opaque_approval_logic(
    tmp_path: Path,
) -> None:
    isolation, egress, supply_chain = security_attestations(tmp_path)

    approval = approve_monitor_release(
        complete_evidence(), isolation, egress, supply_chain
    )

    assert release_approved(approval)
    assert approval.studio_revision == supply_chain.studio_revision
    assert repr(complete_evidence()) == "MonitorDynamicValidationEvidence(redacted)"


def test_every_operational_claim_is_mandatory(tmp_path: Path) -> None:
    isolation, egress, supply_chain = security_attestations(tmp_path)
    evidence = complete_evidence()
    boolean_fields = [
        field.name
        for field in fields(evidence)
        if isinstance(getattr(evidence, field.name), bool)
    ]

    assert len(boolean_fields) == 29
    for name in boolean_fields:
        with pytest.raises(
            MonitorReleaseGateError, match="monitor_release_matrix_incomplete"
        ):
            approve_monitor_release(
                replace(evidence, **{name: False}),
                isolation,
                egress,
                supply_chain,
            )


def test_gate_rejects_stale_reports_revision_and_limits(tmp_path: Path) -> None:
    isolation, egress, supply_chain = security_attestations(tmp_path)
    evidence = complete_evidence()
    cases = (
        replace(evidence, expires_on=TODAY - timedelta(days=1)),
        replace(evidence, expires_on=evidence.tested_on + timedelta(days=31)),
        replace(evidence, studio_revision="b" * 40),
        replace(evidence, report_sha256="report.json"),
        replace(evidence, ephemeral_contract_version=1),
        replace(evidence, observed_max_input_bytes=64 * 1024 + 1),
        replace(evidence, observed_max_output_bytes=1024 * 1024 + 1),
        replace(evidence, observed_max_output_chunk_bytes=64 * 1024 + 1),
        replace(evidence, observed_turn_timeout_seconds=301),
        replace(evidence, observed_termination_grace_seconds=6),
    )

    for changed in cases:
        with pytest.raises(MonitorReleaseGateError):
            approve_monitor_release(changed, isolation, egress, supply_chain)


def test_gate_rejects_attestations_from_different_bundle(tmp_path: Path) -> None:
    isolation, egress, supply_chain = security_attestations(tmp_path / "first")
    _, other_egress, _ = security_attestations(
        tmp_path / "second", model_id="synthetic-model-2026-09-02"
    )

    with pytest.raises(MonitorReleaseGateError, match="monitor_release_binding_rejected"):
        approve_monitor_release(
            complete_evidence(), isolation, other_egress, supply_chain
        )


def test_release_approval_cannot_be_forged() -> None:
    with pytest.raises(
        MonitorReleaseGateError, match="monitor_release_approval_invalid"
    ):
        MonitorReleaseApproval(
            "a" * 64,
            "b" * 40,
            TODAY,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            object(),
        )


def test_release_gate_has_no_network_provider_or_process_dependencies() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "vrsoft_extractor"
        / "mary"
        / "monitor_release_gate.py"
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
        "urllib",
    )
    assert not any(part in imported for imported in imports for part in forbidden)

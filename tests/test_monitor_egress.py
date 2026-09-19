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
    MonitorEgressAttestation,
    MonitorEgressError,
    MonitorEgressEvidence,
    MonitorEgressManifest,
    attest_monitor_egress,
    egress_attested,
)


TODAY = datetime.now(timezone.utc).date()
REQUEST_FIELDS = ("input", "instructions", "model", "store", "stream")


def egress_policy():
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
        request_fields=REQUEST_FIELDS,
        store_content=False,
        web_search_enabled=False,
        plugins_enabled=False,
        sync_enabled=False,
        provider_fanout_enabled=False,
    )
    evidence = MonitorEgressEvidence(
        reviewed_on=TODAY,
        expires_on=TODAY + timedelta(days=30),
        observed_destinations=(PILOT_ENDPOINT,),
        observed_request_fields=REQUEST_FIELDS,
        dedicated_provider_account=True,
        retention_control_verified=True,
        telemetry_disabled_verified=True,
        network_allowlist_enforced=True,
        direct_egress_denied=True,
        egress_capture_reviewed=True,
        payload_inventory_reviewed=True,
    )
    return manifest, evidence


def test_attestation_binds_fixed_provider_destination_and_reviewed_policy() -> None:
    manifest, evidence = egress_policy()

    attestation = attest_monitor_egress(manifest, evidence)

    assert egress_attested(attestation)
    assert attestation.provider_id == PILOT_PROVIDER_ID
    assert attestation.model_id == manifest.model_id
    assert repr(manifest) == "MonitorEgressManifest(redacted)"
    assert repr(evidence) == "MonitorEgressEvidence(redacted)"
    assert manifest.account_scope_sha256 not in repr(attestation)


@pytest.mark.parametrize(
    "change",
    [
        {"provider_id": "claude"},
        {"provider_version": "latest"},
        {"model_id": "gpt-latest"},
        {"endpoint": "http://api.openai.com/v1/responses"},
        {"endpoint": "https://api.openai.com/v1/responses?copy=true"},
        {"auth_method": "chatgpt"},
        {"account_scope_sha256": "project-name"},
        {"evidence_sha256": "capture-path"},
        {"retention_mode": "default"},
        {"retention_days": 30},
        {"telemetry_mode": "default"},
        {"request_fields": ("model", "input")},
        {"store_content": True},
        {"web_search_enabled": True},
        {"plugins_enabled": True},
        {"sync_enabled": True},
        {"provider_fanout_enabled": True},
    ],
)
def test_manifest_rejects_unfixed_or_external_capabilities(change) -> None:
    manifest, evidence = egress_policy()

    with pytest.raises(MonitorEgressError):
        attest_monitor_egress(replace(manifest, **change), evidence)


@pytest.mark.parametrize(
    "change",
    [
        {"dedicated_provider_account": False},
        {"retention_control_verified": False},
        {"telemetry_disabled_verified": False},
        {"network_allowlist_enforced": False},
        {"direct_egress_denied": False},
        {"egress_capture_reviewed": False},
        {"payload_inventory_reviewed": False},
    ],
)
def test_attestation_rejects_missing_operational_evidence(change) -> None:
    manifest, evidence = egress_policy()

    with pytest.raises(MonitorEgressError, match="monitor_egress_evidence_rejected"):
        attest_monitor_egress(manifest, replace(evidence, **change))


def test_attestation_rejects_expired_or_mismatched_observation() -> None:
    manifest, evidence = egress_policy()
    cases = (
        replace(evidence, expires_on=TODAY - timedelta(days=1)),
        replace(evidence, expires_on=evidence.reviewed_on + timedelta(days=91)),
        replace(evidence, observed_destinations=("https://example.com/v1",)),
        replace(evidence, observed_request_fields=("input",)),
    )

    for changed in cases:
        with pytest.raises(MonitorEgressError):
            attest_monitor_egress(manifest, changed)


def test_attestation_cannot_be_forged() -> None:
    with pytest.raises(MonitorEgressError, match="monitor_egress_invalid"):
        MonitorEgressAttestation("codex", "model", "a" * 64, object())


def test_policy_module_has_no_network_or_provider_runtime_dependencies() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "vrsoft_extractor"
        / "mary"
        / "monitor_egress.py"
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

    forbidden = ("httpx", "provider_adapters", "requests", "socket", "subprocess")
    assert not any(part in imported for imported in imports for part in forbidden)

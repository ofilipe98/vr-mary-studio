"""Fail-closed external data policy for a future Monitor provider.

The module validates deployment evidence but performs no network requests.  The
generic Studio adapters remain outside this boundary.  A broker must enforce the
destination allowlist and prove the account data controls before it can obtain an
attestation accepted by :mod:`monitor_ephemeral`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit


EGRESS_CONTRACT_VERSION = 1
PILOT_PROVIDER_ID = "codex"
PILOT_AUTH_METHOD = "api_key"
PILOT_ENDPOINT = "https://api.openai.com/v1/responses"
_ATTESTATION_TOKEN = object()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class MonitorEgressError(RuntimeError):
    """Closed policy failure without account or captured payload details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class MonitorEgressManifest:
    """One reviewed provider, model, endpoint and data-handling policy."""

    provider_id: str
    provider_version: str
    model_id: str
    endpoint: str
    auth_method: str
    account_scope_sha256: str
    evidence_sha256: str
    retention_mode: str
    retention_days: int
    telemetry_mode: str
    request_fields: tuple[str, ...]
    store_content: bool
    web_search_enabled: bool
    plugins_enabled: bool
    sync_enabled: bool
    provider_fanout_enabled: bool

    def __repr__(self) -> str:
        return "MonitorEgressManifest(redacted)"


@dataclass(frozen=True, repr=False)
class MonitorEgressEvidence:
    """Claims produced by account review and an isolated egress observation."""

    reviewed_on: date
    expires_on: date
    observed_destinations: tuple[str, ...]
    observed_request_fields: tuple[str, ...]
    dedicated_provider_account: bool
    retention_control_verified: bool
    telemetry_disabled_verified: bool
    network_allowlist_enforced: bool
    direct_egress_denied: bool
    egress_capture_reviewed: bool
    payload_inventory_reviewed: bool

    def __repr__(self) -> str:
        return "MonitorEgressEvidence(redacted)"


class MonitorEgressAttestation:
    """Opaque result bound to one provider, model and manifest digest."""

    __slots__ = (
        "contract_version",
        "manifest_digest",
        "model_id",
        "provider_id",
        "provider_version",
        "_token",
    )

    def __init__(
        self,
        provider_id: str,
        provider_version: str,
        model_id: str,
        manifest_digest: str,
        token: object,
    ) -> None:
        if token is not _ATTESTATION_TOKEN:
            raise MonitorEgressError("monitor_egress_invalid")
        self.contract_version = EGRESS_CONTRACT_VERSION
        self.provider_id = provider_id
        self.provider_version = provider_version
        self.model_id = model_id
        self.manifest_digest = manifest_digest
        self._token = token

    def __repr__(self) -> str:
        return (
            "MonitorEgressAttestation("
            f"contract_version={self.contract_version}, "
            f"provider_id={self.provider_id!r}, model_id={self.model_id!r}, "
            f"manifest_digest={self.manifest_digest!r})"
        )


def egress_attested(value: object) -> bool:
    return (
        isinstance(value, MonitorEgressAttestation)
        and value.contract_version == EGRESS_CONTRACT_VERSION
        and value._token is _ATTESTATION_TOKEN
        and value.provider_id == PILOT_PROVIDER_ID
        and _fixed_identifier(value.provider_version)
        and bool(_IDENTIFIER.fullmatch(value.model_id))
        and bool(_SHA256.fullmatch(value.manifest_digest))
    )


def attest_monitor_egress(
    manifest: MonitorEgressManifest,
    evidence: MonitorEgressEvidence,
) -> MonitorEgressAttestation:
    """Validate one captured pilot route and return its opaque attestation."""

    if manifest.provider_id != PILOT_PROVIDER_ID:
        raise MonitorEgressError("monitor_provider_rejected")
    if not _fixed_identifier(manifest.provider_version) or not _fixed_identifier(
        manifest.model_id
    ):
        raise MonitorEgressError("monitor_provider_revision_rejected")
    if manifest.auth_method != PILOT_AUTH_METHOD:
        raise MonitorEgressError("monitor_provider_auth_rejected")
    if manifest.endpoint != PILOT_ENDPOINT or not _valid_endpoint(manifest.endpoint):
        raise MonitorEgressError("monitor_destination_rejected")
    if not _SHA256.fullmatch(manifest.account_scope_sha256):
        raise MonitorEgressError("monitor_account_scope_rejected")
    if not _SHA256.fullmatch(manifest.evidence_sha256):
        raise MonitorEgressError("monitor_evidence_reference_rejected")
    if manifest.retention_mode != "zero_data_retention" or manifest.retention_days != 0:
        raise MonitorEgressError("monitor_retention_rejected")
    if manifest.telemetry_mode != "disabled":
        raise MonitorEgressError("monitor_telemetry_rejected")
    if not _valid_fields(manifest.request_fields):
        raise MonitorEgressError("monitor_payload_inventory_rejected")
    if any(
        (
            manifest.store_content,
            manifest.web_search_enabled,
            manifest.plugins_enabled,
            manifest.sync_enabled,
            manifest.provider_fanout_enabled,
        )
    ):
        raise MonitorEgressError("monitor_external_capability_rejected")

    if not (
        evidence.dedicated_provider_account
        and evidence.retention_control_verified
        and evidence.telemetry_disabled_verified
        and evidence.network_allowlist_enforced
        and evidence.direct_egress_denied
        and evidence.egress_capture_reviewed
        and evidence.payload_inventory_reviewed
    ):
        raise MonitorEgressError("monitor_egress_evidence_rejected")
    today = datetime.now(timezone.utc).date()
    if evidence.reviewed_on > today or evidence.expires_on < today:
        raise MonitorEgressError("monitor_egress_review_expired")
    if evidence.expires_on < evidence.reviewed_on or (
        evidence.expires_on - evidence.reviewed_on > timedelta(days=90)
    ):
        raise MonitorEgressError("monitor_egress_review_window_rejected")
    if evidence.observed_destinations != (manifest.endpoint,):
        raise MonitorEgressError("monitor_destination_observation_rejected")
    if evidence.observed_request_fields != manifest.request_fields:
        raise MonitorEgressError("monitor_payload_observation_rejected")

    digest = _manifest_digest(manifest)
    return MonitorEgressAttestation(
        manifest.provider_id,
        manifest.provider_version,
        manifest.model_id,
        digest,
        _ATTESTATION_TOKEN,
    )


def _fixed_identifier(value: str) -> bool:
    return (
        bool(_IDENTIFIER.fullmatch(value))
        and "latest" not in value.casefold()
        and "*" not in value
    )


def _valid_endpoint(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.openai.com"
        and parsed.port is None
        and parsed.path == "/v1/responses"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _valid_fields(fields: tuple[str, ...]) -> bool:
    return (
        bool(fields)
        and fields == tuple(sorted(set(fields)))
        and all(_FIELD_NAME.fullmatch(field) for field in fields)
    )


def _manifest_digest(manifest: MonitorEgressManifest) -> str:
    payload = {
        "account_scope_sha256": manifest.account_scope_sha256,
        "auth_method": manifest.auth_method,
        "endpoint": manifest.endpoint,
        "evidence_sha256": manifest.evidence_sha256,
        "model_id": manifest.model_id,
        "plugins_enabled": manifest.plugins_enabled,
        "provider_fanout_enabled": manifest.provider_fanout_enabled,
        "provider_id": manifest.provider_id,
        "provider_version": manifest.provider_version,
        "request_fields": list(manifest.request_fields),
        "retention_days": manifest.retention_days,
        "retention_mode": manifest.retention_mode,
        "store_content": manifest.store_content,
        "sync_enabled": manifest.sync_enabled,
        "telemetry_mode": manifest.telemetry_mode,
        "web_search_enabled": manifest.web_search_enabled,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()

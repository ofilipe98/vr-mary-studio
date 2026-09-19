"""Immutable executable-chain gate for the future Monitor deployment.

This module validates metadata for an offline reviewed bundle.  It never downloads,
installs, updates, imports or launches provider code.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from vrsoft_extractor.mary.monitor_egress import (
    MonitorEgressAttestation,
    egress_attested,
)
from vrsoft_extractor.mary.monitor_isolation import (
    MonitorIsolationAttestation,
    isolation_attested,
)


SUPPLY_CHAIN_CONTRACT_VERSION = 1
_ATTESTATION_TOKEN = object()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_VERSION = re.compile(r"^[0-9][a-zA-Z0-9._-]{0,63}$")


class MonitorSupplyChainError(RuntimeError):
    """Closed bundle-policy failure without paths or captured signer data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class MonitorArtifact:
    """One exact artifact copied into the isolated runtime bundle."""

    name: str
    version: str
    sha256: str
    source: str
    signer_certificate_sha256: str

    def __repr__(self) -> str:
        return "MonitorArtifact(redacted)"


@dataclass(frozen=True, repr=False)
class MonitorSupplyChainManifest:
    """All revisions and configuration needed to reproduce one pilot bundle."""

    studio_revision: str
    artifacts: tuple[MonitorArtifact, ...]
    dependency_lock_sha256: str
    configuration_sha256: str
    isolation_manifest_digest: str
    egress_manifest_digest: str
    update_policy: str

    def __repr__(self) -> str:
        return "MonitorSupplyChainManifest(redacted)"


@dataclass(frozen=True, repr=False)
class MonitorSupplyChainEvidence:
    """Claims produced by the controlled build and release review."""

    reviewed_on: date
    expires_on: date
    evidence_sha256: str
    offline_bundle_built: bool
    artifact_hashes_verified: bool
    signatures_verified: bool
    dependency_distributions_hashed: bool
    source_reviewed: bool
    vulnerability_reviewed: bool
    auto_update_disabled: bool
    installer_network_denied: bool
    update_requires_reapproval: bool

    def __repr__(self) -> str:
        return "MonitorSupplyChainEvidence(redacted)"


class MonitorSupplyChainAttestation:
    """Opaque bundle approval bound to the process and egress manifests."""

    __slots__ = (
        "contract_version",
        "egress_manifest_digest",
        "isolation_manifest_digest",
        "manifest_digest",
        "provider_version",
        "studio_revision",
        "_token",
    )

    def __init__(
        self,
        manifest_digest: str,
        studio_revision: str,
        provider_version: str,
        isolation_manifest_digest: str,
        egress_manifest_digest: str,
        token: object,
    ) -> None:
        if token is not _ATTESTATION_TOKEN:
            raise MonitorSupplyChainError("monitor_supply_chain_invalid")
        self.contract_version = SUPPLY_CHAIN_CONTRACT_VERSION
        self.manifest_digest = manifest_digest
        self.studio_revision = studio_revision
        self.provider_version = provider_version
        self.isolation_manifest_digest = isolation_manifest_digest
        self.egress_manifest_digest = egress_manifest_digest
        self._token = token

    def __repr__(self) -> str:
        return (
            "MonitorSupplyChainAttestation("
            f"contract_version={self.contract_version}, "
            f"manifest_digest={self.manifest_digest!r}, "
            f"studio_revision={self.studio_revision!r})"
        )


def supply_chain_attested(value: object) -> bool:
    return (
        isinstance(value, MonitorSupplyChainAttestation)
        and value.contract_version == SUPPLY_CHAIN_CONTRACT_VERSION
        and value._token is _ATTESTATION_TOKEN
        and bool(_SHA256.fullmatch(value.manifest_digest))
        and bool(_GIT_REVISION.fullmatch(value.studio_revision))
        and bool(_VERSION.fullmatch(value.provider_version))
        and bool(_SHA256.fullmatch(value.isolation_manifest_digest))
        and bool(_SHA256.fullmatch(value.egress_manifest_digest))
    )


def attest_monitor_supply_chain(
    manifest: MonitorSupplyChainManifest,
    evidence: MonitorSupplyChainEvidence,
    isolation: MonitorIsolationAttestation,
    egress: MonitorEgressAttestation,
) -> MonitorSupplyChainAttestation:
    """Validate an offline bundle and bind it to prior security attestations."""

    if not isolation_attested(isolation) or not egress_attested(egress):
        raise MonitorSupplyChainError("monitor_supply_chain_prerequisite_rejected")
    if not _GIT_REVISION.fullmatch(manifest.studio_revision):
        raise MonitorSupplyChainError("monitor_studio_revision_rejected")
    if manifest.update_policy != "offline_reviewed_bundle":
        raise MonitorSupplyChainError("monitor_update_policy_rejected")
    if (
        manifest.isolation_manifest_digest != isolation.manifest_digest
        or manifest.egress_manifest_digest != egress.manifest_digest
    ):
        raise MonitorSupplyChainError("monitor_supply_chain_binding_rejected")
    if not _SHA256.fullmatch(manifest.dependency_lock_sha256):
        raise MonitorSupplyChainError("monitor_dependency_lock_rejected")
    if not _SHA256.fullmatch(manifest.configuration_sha256):
        raise MonitorSupplyChainError("monitor_configuration_revision_rejected")
    if len(manifest.artifacts) != 1:
        raise MonitorSupplyChainError("monitor_artifact_catalog_rejected")

    artifact = manifest.artifacts[0]
    if artifact.name != egress.provider_id or not _NAME.fullmatch(artifact.name):
        raise MonitorSupplyChainError("monitor_artifact_rejected")
    if artifact.version != egress.provider_version or not _VERSION.fullmatch(
        artifact.version
    ):
        raise MonitorSupplyChainError("monitor_artifact_version_rejected")
    if artifact.sha256 != isolation.executable_sha256:
        raise MonitorSupplyChainError("monitor_artifact_hash_rejected")
    if not _SHA256.fullmatch(artifact.sha256) or not _SHA256.fullmatch(
        artifact.signer_certificate_sha256
    ):
        raise MonitorSupplyChainError("monitor_artifact_signature_rejected")
    if not _versioned_official_source(artifact.source, artifact.version):
        raise MonitorSupplyChainError("monitor_artifact_source_rejected")

    if not _SHA256.fullmatch(evidence.evidence_sha256):
        raise MonitorSupplyChainError("monitor_supply_chain_evidence_reference_rejected")
    if not (
        evidence.offline_bundle_built
        and evidence.artifact_hashes_verified
        and evidence.signatures_verified
        and evidence.dependency_distributions_hashed
        and evidence.source_reviewed
        and evidence.vulnerability_reviewed
        and evidence.auto_update_disabled
        and evidence.installer_network_denied
        and evidence.update_requires_reapproval
    ):
        raise MonitorSupplyChainError("monitor_supply_chain_evidence_rejected")
    today = datetime.now(timezone.utc).date()
    if evidence.reviewed_on > today or evidence.expires_on < today:
        raise MonitorSupplyChainError("monitor_supply_chain_review_expired")
    if evidence.expires_on < evidence.reviewed_on or (
        evidence.expires_on - evidence.reviewed_on > timedelta(days=90)
    ):
        raise MonitorSupplyChainError("monitor_supply_chain_review_window_rejected")

    digest = _manifest_digest(manifest)
    return MonitorSupplyChainAttestation(
        digest,
        manifest.studio_revision,
        artifact.version,
        manifest.isolation_manifest_digest,
        manifest.egress_manifest_digest,
        _ATTESTATION_TOKEN,
    )


def _versioned_official_source(source: str, version: str) -> bool:
    parsed = urlsplit(source)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.path.startswith("/openai/codex/releases/tag/")
        and version in parsed.path.rsplit("/", 1)[-1]
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _manifest_digest(manifest: MonitorSupplyChainManifest) -> str:
    payload = {
        "artifacts": [
            {
                "name": item.name,
                "sha256": item.sha256,
                "signer_certificate_sha256": item.signer_certificate_sha256,
                "source": item.source,
                "version": item.version,
            }
            for item in manifest.artifacts
        ],
        "configuration_sha256": manifest.configuration_sha256,
        "dependency_lock_sha256": manifest.dependency_lock_sha256,
        "egress_manifest_digest": manifest.egress_manifest_digest,
        "isolation_manifest_digest": manifest.isolation_manifest_digest,
        "studio_revision": manifest.studio_revision,
        "update_policy": manifest.update_policy,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()

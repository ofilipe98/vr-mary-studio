"""Fail-closed process policy for a future out-of-process Monitor provider.

This module validates a launch manifest but does not launch a process. The
actual broker must enforce the declared OS identity and filesystem ACLs; direct
use of the Studio provider launchers remains forbidden for Monitor sessions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


ISOLATION_CONTRACT_VERSION = 1
_ATTESTATION_TOKEN = object()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENVIRONMENT_KEYS = frozenset(
    {
        "APPDATA",
        "HOME",
        "LOCALAPPDATA",
        "PYTHONIOENCODING",
        "PYTHONUNBUFFERED",
        "PYTHONUTF8",
        "SystemRoot",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)
_PROFILE_KEYS = frozenset({"APPDATA", "HOME", "LOCALAPPDATA", "USERPROFILE"})
_TEMP_KEYS = frozenset({"TEMP", "TMP"})


class MonitorIsolationError(RuntimeError):
    """Closed policy failure without paths, identities, or environment values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class MonitorIsolationEvidence:
    """Claims which a privileged process broker must prove at deployment."""

    brokered_out_of_process: bool
    dedicated_identity: bool
    environment_inherited: bool
    filesystem_acl_enforced: bool
    executable_allowlist_enforced: bool

    def __repr__(self) -> str:
        return "MonitorIsolationEvidence(redacted)"


@dataclass(frozen=True, repr=False)
class MonitorProcessManifest:
    """Immutable launch inputs selected by configuration, never by the model."""

    executable: Path
    executable_sha256: str
    arguments: tuple[str, ...]
    runtime_root: Path
    working_directory: Path
    profile_directory: Path
    temp_directory: Path
    environment: tuple[tuple[str, str], ...]

    def __repr__(self) -> str:
        return "MonitorProcessManifest(redacted)"


class MonitorIsolationAttestation:
    """Opaque result of validating one fixed process manifest."""

    __slots__ = ("contract_version", "manifest_digest", "_token")

    def __init__(self, manifest_digest: str, token: object) -> None:
        if token is not _ATTESTATION_TOKEN:
            raise MonitorIsolationError("monitor_isolation_invalid")
        self.contract_version = ISOLATION_CONTRACT_VERSION
        self.manifest_digest = manifest_digest
        self._token = token

    def __repr__(self) -> str:
        return (
            "MonitorIsolationAttestation("
            f"contract_version={self.contract_version}, manifest_digest={self.manifest_digest!r})"
        )


def isolation_attested(value: object) -> bool:
    return (
        isinstance(value, MonitorIsolationAttestation)
        and value.contract_version == ISOLATION_CONTRACT_VERSION
        and value._token is _ATTESTATION_TOKEN
        and bool(_SHA256.fullmatch(value.manifest_digest))
    )


def minimal_monitor_environment(
    profile_directory: Path,
    temp_directory: Path,
    *,
    system_root: Path | None = None,
) -> tuple[tuple[str, str], ...]:
    """Build an explicit environment without reading or copying the parent."""

    profile = str(Path(profile_directory).resolve())
    temp = str(Path(temp_directory).resolve())
    values = {
        "APPDATA": str(Path(profile) / "AppData/Roaming"),
        "HOME": profile,
        "LOCALAPPDATA": str(Path(profile) / "AppData/Local"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
        "TEMP": temp,
        "TMP": temp,
        "USERPROFILE": profile,
    }
    if system_root is not None:
        resolved_system = str(Path(system_root).resolve())
        values["SystemRoot"] = resolved_system
        values["WINDIR"] = resolved_system
    return tuple(sorted(values.items()))


def attest_monitor_process(
    manifest: MonitorProcessManifest,
    evidence: MonitorIsolationEvidence,
    *,
    forbidden_roots: tuple[Path, ...],
) -> MonitorIsolationAttestation:
    """Validate a brokered launch plan and return an opaque attestation."""

    if not (
        evidence.brokered_out_of_process
        and evidence.dedicated_identity
        and not evidence.environment_inherited
        and evidence.filesystem_acl_enforced
        and evidence.executable_allowlist_enforced
    ):
        raise MonitorIsolationError("monitor_isolation_evidence_rejected")
    if not forbidden_roots:
        raise MonitorIsolationError("monitor_forbidden_roots_required")

    root = _directory(manifest.runtime_root)
    working = _directory(manifest.working_directory)
    profile = _directory(manifest.profile_directory)
    temp = _directory(manifest.temp_directory)
    if not all(_inside(path, root) for path in (working, profile, temp)):
        raise MonitorIsolationError("monitor_filesystem_scope_rejected")

    try:
        forbidden = tuple(Path(path).resolve(strict=True) for path in forbidden_roots)
    except OSError:
        raise MonitorIsolationError("monitor_forbidden_root_rejected") from None
    if any(_overlaps(root, path) for path in forbidden):
        raise MonitorIsolationError("monitor_forbidden_root_overlap")

    executable = Path(manifest.executable)
    if not executable.is_absolute() or executable.is_symlink():
        raise MonitorIsolationError("monitor_executable_rejected")
    try:
        executable = executable.resolve(strict=True)
    except OSError:
        raise MonitorIsolationError("monitor_executable_rejected") from None
    if not executable.is_file() or not _inside(executable, root):
        raise MonitorIsolationError("monitor_executable_rejected")
    expected_hash = manifest.executable_sha256.strip().lower()
    try:
        actual_hash = _file_sha256(executable)
    except OSError:
        raise MonitorIsolationError("monitor_executable_rejected") from None
    if not _SHA256.fullmatch(expected_hash) or actual_hash != expected_hash:
        raise MonitorIsolationError("monitor_executable_hash_rejected")

    if len(manifest.arguments) > 32 or any(
        not isinstance(argument, str)
        or not argument
        or len(argument.encode("utf-8")) > 4096
        or any(character in argument for character in ("\x00", "\r", "\n"))
        for argument in manifest.arguments
    ):
        raise MonitorIsolationError("monitor_arguments_rejected")

    environment = _validate_environment(manifest.environment, profile, temp)
    canonical = {
        "arguments": list(manifest.arguments),
        "environment": sorted(environment.items()),
        "executable_sha256": expected_hash,
        "runtime_root": str(root),
        "working_directory": str(working),
        "profile_directory": str(profile),
        "temp_directory": str(temp),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MonitorIsolationAttestation(digest, _ATTESTATION_TOKEN)


def _directory(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise MonitorIsolationError("monitor_directory_rejected")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise MonitorIsolationError("monitor_directory_rejected") from None
    if not resolved.is_dir():
        raise MonitorIsolationError("monitor_directory_rejected")
    return resolved


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _overlaps(left: Path, right: Path) -> bool:
    return _inside(left, right) or _inside(right, left)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_environment(
    pairs: tuple[tuple[str, str], ...],
    profile: Path,
    temp: Path,
) -> dict[str, str]:
    environment: dict[str, str] = {}
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise MonitorIsolationError("monitor_environment_rejected")
        key, value = pair
        if key not in _ENVIRONMENT_KEYS or key in environment or not isinstance(value, str):
            raise MonitorIsolationError("monitor_environment_rejected")
        if "\x00" in value or "\r" in value or "\n" in value:
            raise MonitorIsolationError("monitor_environment_rejected")
        environment[key] = value
    for key in _PROFILE_KEYS & environment.keys():
        if not _inside(Path(environment[key]).resolve(), profile):
            raise MonitorIsolationError("monitor_environment_rejected")
    for key in _TEMP_KEYS & environment.keys():
        if not _inside(Path(environment[key]).resolve(), temp):
            raise MonitorIsolationError("monitor_environment_rejected")
    system_root = environment.get("SystemRoot")
    windir = environment.get("WINDIR")
    if (system_root is None) != (windir is None) or (
        system_root is not None
        and (
            Path(system_root).resolve() != Path(windir).resolve()
            or not Path(system_root).is_absolute()
            or not Path(system_root).is_dir()
        )
    ):
        raise MonitorIsolationError("monitor_environment_rejected")
    if environment.get("PYTHONIOENCODING", "utf-8") != "utf-8" or environment.get(
        "PYTHONUTF8", "1"
    ) != "1" or environment.get("PYTHONUNBUFFERED", "1") != "1":
        raise MonitorIsolationError("monitor_environment_rejected")
    return environment

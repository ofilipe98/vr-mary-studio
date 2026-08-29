"""Isolated JVM and decompiler discovery for ERP code analysis."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


VINEFLOWER_VERSION = "1.12.0"
CFR_VERSION = "0.152"
VINEFLOWER_SHA256 = "1dfcfe974395734fa467ce620661c7623d05ba83670de0529b1fbd63ff548b9d"
CFR_SHA256 = "f686e8f3ded377d7bc87d216a90e9e9512df4156e75b06c655a16648ae8765b2"
MINIMUM_JAVA_MAJOR = 17


@dataclass(frozen=True)
class ToolStatus:
    name: str
    available: bool
    path: str = ""
    version: str = ""
    error: str = ""
    source: str = ""
    sha256: str = ""
    checksum_verified: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DecompileRequest:
    input_path: Path
    output_dir: Path
    timeout_seconds: int = 900
    max_heap_mb: int = 4096


@dataclass(frozen=True)
class DecompileResult:
    tool: str
    status: str
    duration_ms: int
    exit_code: int | None
    output_dir: str
    stdout: str = ""
    stderr: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class JavaRuntimeResolver:
    """Find Java 17+ without mutating JAVA_HOME or the system installation."""

    def __init__(self, root: str | Path, environ: dict[str, str] | None = None) -> None:
        self.root = Path(root).resolve()
        self.environ = dict(os.environ if environ is None else environ)

    def resolve(self) -> ToolStatus:
        failures: list[str] = []
        for path, source in self._candidates():
            if not path.is_file():
                continue
            status = inspect_java(path, source=source)
            if status.available:
                return status
            failures.append(f"{path}: {status.error}")
        return ToolStatus(
            name="java",
            available=False,
            error=(
                "Java 17+ isolado não encontrado. "
                + ("; ".join(failures) if failures else "Nenhum candidato disponível.")
            ),
        )

    def _candidates(self) -> Iterable[tuple[Path, str]]:
        configured = str(self.environ.get("VR_CODE_JAVA_HOME") or "").strip()
        if configured:
            yield Path(configured).expanduser() / "bin" / _java_executable(), "configured"
        bundled = self.root / "tools" / "code-analysis" / "java17"
        yield bundled / "bin" / _java_executable(), "bundled"
        for candidate in sorted(bundled.glob(f"*/bin/{_java_executable()}")):
            yield candidate, "bundled-archive"
        yield self.root / "tools" / "java17" / "bin" / _java_executable(), "bundled-legacy"
        system = shutil.which("java")
        if system:
            yield Path(system), "system"


class DecompilerAdapter:
    name = "decompiler"
    version = ""
    expected_sha256 = ""

    def __init__(self, java: ToolStatus, jar_path: str | Path) -> None:
        self.java = java
        self.jar_path = Path(jar_path).resolve()

    def status(self) -> ToolStatus:
        if not self.java.available:
            return ToolStatus(
                name=self.name,
                available=False,
                path=str(self.jar_path),
                version=self.version,
                error="Java 17+ indisponível.",
            )
        if not self.jar_path.is_file():
            return ToolStatus(
                name=self.name,
                available=False,
                path=str(self.jar_path),
                version=self.version,
                error="JAR do decompilador não encontrado.",
            )
        actual_hash = _sha256_file(self.jar_path)
        if self.expected_sha256 and actual_hash != self.expected_sha256:
            return ToolStatus(
                name=self.name,
                available=False,
                path=str(self.jar_path),
                version=self.version,
                error="Checksum do decompilador não corresponde à versão aprovada.",
                sha256=actual_hash,
                checksum_verified=False,
            )
        return ToolStatus(
            name=self.name,
            available=True,
            path=str(self.jar_path),
            version=self.version,
            source="bundled-or-configured",
            sha256=actual_hash,
            checksum_verified=bool(
                self.expected_sha256 and actual_hash == self.expected_sha256
            ),
        )

    def command(self, request: DecompileRequest) -> list[str]:
        raise NotImplementedError

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        status = self.status()
        if not status.available:
            return DecompileResult(
                tool=self.name,
                status="unavailable",
                duration_ms=0,
                exit_code=None,
                output_dir=str(request.output_dir),
                error=status.error,
            )
        if not request.input_path.is_file():
            return DecompileResult(
                tool=self.name,
                status="failed",
                duration_ms=0,
                exit_code=None,
                output_dir=str(request.output_dir),
                error=f"Entrada não encontrada: {request.input_path}",
            )
        request.output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                self.command(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, request.timeout_seconds),
                check=False,
                creationflags=_no_window_flag(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return DecompileResult(
                tool=self.name,
                status="failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                exit_code=None,
                output_dir=str(request.output_dir),
                error=f"{type(exc).__name__}: {exc}",
            )
        return DecompileResult(
            tool=self.name,
            status="completed" if completed.returncode == 0 else "failed",
            duration_ms=int((time.monotonic() - started) * 1000),
            exit_code=completed.returncode,
            output_dir=str(request.output_dir),
            stdout=completed.stdout[-4000:],
            stderr=completed.stderr[-4000:],
        )


class VineflowerAdapter(DecompilerAdapter):
    name = "vineflower"
    version = VINEFLOWER_VERSION
    expected_sha256 = VINEFLOWER_SHA256

    def command(self, request: DecompileRequest) -> list[str]:
        return [
            self.java.path,
            f"-Xmx{max(512, request.max_heap_mb)}m",
            "-jar",
            str(self.jar_path),
            str(request.input_path.resolve()),
            str(request.output_dir.resolve()),
        ]


class CfrAdapter(DecompilerAdapter):
    name = "cfr"
    version = CFR_VERSION
    expected_sha256 = CFR_SHA256

    def command(self, request: DecompileRequest) -> list[str]:
        return [
            self.java.path,
            f"-Xmx{max(512, request.max_heap_mb)}m",
            "-jar",
            str(self.jar_path),
            str(request.input_path.resolve()),
            "--outputdir",
            str(request.output_dir.resolve()),
            "--silent",
            "true",
        ]


class JvmToolchain:
    def __init__(self, root: str | Path, environ: dict[str, str] | None = None) -> None:
        self.root = Path(root).resolve()
        self.environ = dict(os.environ if environ is None else environ)

    @property
    def tools_dir(self) -> Path:
        return self.root / "tools" / "code-analysis"

    def doctor(self) -> dict[str, object]:
        java = JavaRuntimeResolver(self.root, self.environ).resolve()
        vineflower = VineflowerAdapter(java, self._vineflower_path()).status()
        cfr = CfrAdapter(java, self._cfr_path()).status()
        return {
            "ready": java.available and vineflower.available and cfr.available,
            "java": java.to_dict(),
            "vineflower": vineflower.to_dict(),
            "cfr": cfr.to_dict(),
            "system_java_unchanged": True,
        }

    def adapters(self) -> tuple[VineflowerAdapter, CfrAdapter]:
        java = JavaRuntimeResolver(self.root, self.environ).resolve()
        return (
            VineflowerAdapter(java, self._vineflower_path()),
            CfrAdapter(java, self._cfr_path()),
        )

    def _vineflower_path(self) -> Path:
        configured = str(self.environ.get("VR_VINEFLOWER_JAR") or "").strip()
        return Path(configured).expanduser() if configured else (
            self.tools_dir / "decompilers" / f"vineflower-{VINEFLOWER_VERSION}.jar"
        )

    def _cfr_path(self) -> Path:
        configured = str(self.environ.get("VR_CFR_JAR") or "").strip()
        return Path(configured).expanduser() if configured else (
            self.tools_dir / "decompilers" / f"cfr-{CFR_VERSION}.jar"
        )


def inspect_java(path: Path, *, source: str = "") -> ToolStatus:
    try:
        completed = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=_no_window_flag(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolStatus(
            name="java",
            available=False,
            path=str(path),
            error=f"{type(exc).__name__}: {exc}",
            source=source,
        )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    version, major = parse_java_version(output)
    if completed.returncode != 0 or major < MINIMUM_JAVA_MAJOR:
        return ToolStatus(
            name="java",
            available=False,
            path=str(path),
            version=version,
            error=(
                f"Java {MINIMUM_JAVA_MAJOR}+ necessário; "
                f"encontrado {version or 'desconhecido'}."
            ),
            source=source,
        )
    return ToolStatus(
        name="java",
        available=True,
        path=str(path),
        version=version,
        source=source,
    )


def parse_java_version(output: str) -> tuple[str, int]:
    match = re.search(r'version\s+"([^"]+)"', str(output or ""), re.IGNORECASE)
    if not match:
        return "", 0
    version = match.group(1)
    first = version.split(".", 2)
    try:
        major = int(first[1] if first[0] == "1" and len(first) > 1 else first[0])
    except ValueError:
        major = 0
    return version, major


def _java_executable() -> str:
    return "java.exe" if os.name == "nt" else "java"


def _no_window_flag() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

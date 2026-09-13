"""Isolated JVM and decompiler discovery for ERP code analysis."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
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
    max_cpu_cores: int = 1
    cpu_core_offset: int = 0
    process_priority: str = "low"


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
    peak_rss_bytes: int = 0
    cpu_user_ms: int = 0
    cpu_kernel_ms: int = 0
    input_bytes: int = 0
    output_bytes: int = 0
    timed_out: bool = False
    metrics_available: bool = False
    cpu_limit_applied: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class JavaRuntimeResolver:
    """Find Java 17+ without mutating JAVA_HOME or the system installation."""

    def __init__(
        self,
        root: str | Path,
        environ: dict[str, str] | None = None,
        *,
        tool_dirs: Iterable[str | Path] = (),
    ) -> None:
        self.root = Path(root).resolve()
        self.environ = dict(os.environ if environ is None else environ)
        self.tool_dirs = tuple(Path(path).resolve() for path in tool_dirs)

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
        seen: set[Path] = set()
        bundled_dirs = self.tool_dirs or (
            self.root / "tools" / "code-analysis",
        )
        for tool_dir in bundled_dirs:
            bundled = tool_dir / "java17"
            direct = bundled / "bin" / _java_executable()
            if direct not in seen:
                seen.add(direct)
                yield direct, "bundled"
            for candidate in sorted(bundled.glob(f"*/bin/{_java_executable()}")):
                if candidate in seen:
                    continue
                seen.add(candidate)
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
        sampler: _ProcessSampler | None = None
        monitor_stop = threading.Event()
        monitor_thread: threading.Thread | None = None
        peak_rss_bytes = 0
        cpu_user_ms = 0
        cpu_kernel_ms = 0
        metrics_available = False
        timed_out = False
        cpu_limit_applied = False
        try:
            process = subprocess.Popen(
                self.command(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_process_creation_flags(request.process_priority),
            )
            cpu_limit_applied = _limit_process_cpu(
                process.pid,
                request.max_cpu_cores,
                offset=request.cpu_core_offset,
            )
            sampler = _ProcessSampler(process.pid)

            def monitor() -> None:
                nonlocal peak_rss_bytes, cpu_user_ms, cpu_kernel_ms, metrics_available
                while not monitor_stop.wait(0.05):
                    sample = sampler.sample()
                    if sample is None:
                        continue
                    metrics_available = True
                    peak_rss_bytes = max(peak_rss_bytes, sample[0])
                    cpu_user_ms = max(cpu_user_ms, sample[1])
                    cpu_kernel_ms = max(cpu_kernel_ms, sample[2])
                sample = sampler.sample()
                if sample is not None:
                    metrics_available = True
                    peak_rss_bytes = max(peak_rss_bytes, sample[0])
                    cpu_user_ms = max(cpu_user_ms, sample[1])
                    cpu_kernel_ms = max(cpu_kernel_ms, sample[2])

            monitor_thread = threading.Thread(target=monitor, daemon=True)
            monitor_thread.start()
            try:
                stdout, stderr = process.communicate(
                    timeout=max(1, request.timeout_seconds)
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
        except (OSError, subprocess.SubprocessError) as exc:
            return DecompileResult(
                tool=self.name,
                status="failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                exit_code=None,
                output_dir=str(request.output_dir),
                error=f"{type(exc).__name__}: {exc}",
                input_bytes=_file_size(request.input_path),
                output_bytes=_directory_size(request.output_dir),
            )
        finally:
            monitor_stop.set()
            if monitor_thread is not None:
                monitor_thread.join(timeout=1)
            if sampler is not None:
                sampler.close()
        return DecompileResult(
            tool=self.name,
            status=(
                "completed"
                if process.returncode == 0 and not timed_out
                else "failed"
            ),
            duration_ms=int((time.monotonic() - started) * 1000),
            exit_code=process.returncode,
            output_dir=str(request.output_dir),
            stdout=str(stdout or "")[-4000:],
            stderr=str(stderr or "")[-4000:],
            error=(
                f"Timeout após {max(1, request.timeout_seconds)} segundo(s)."
                if timed_out
                else ""
            ),
            peak_rss_bytes=peak_rss_bytes,
            cpu_user_ms=cpu_user_ms,
            cpu_kernel_ms=cpu_kernel_ms,
            input_bytes=_file_size(request.input_path),
            output_bytes=_directory_size(request.output_dir),
            timed_out=timed_out,
            metrics_available=metrics_available,
            cpu_limit_applied=cpu_limit_applied,
        )


class VineflowerAdapter(DecompilerAdapter):
    name = "vineflower"
    version = VINEFLOWER_VERSION
    expected_sha256 = VINEFLOWER_SHA256

    def command(self, request: DecompileRequest) -> list[str]:
        cmd = [
            self.java.path,
            f"-Xmx{max(512, request.max_heap_mb)}m",
            "-jar",
            str(self.jar_path),
        ]
        if request.max_cpu_cores > 0:
            cmd.append(f"--thread-count={max(1, request.max_cpu_cores)}")
        cmd.extend(
            [
                str(request.input_path.resolve()),
                str(request.output_dir.resolve()),
            ]
        )
        return cmd


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
    def __init__(
        self,
        root: str | Path,
        environ: dict[str, str] | None = None,
        *,
        app_dir: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.environ = dict(os.environ if environ is None else environ)
        self.app_dir = Path(app_dir).resolve() if app_dir is not None else None

    @property
    def tools_dir(self) -> Path:
        return self._tool_dirs()[0]

    def doctor(self) -> dict[str, object]:
        java = JavaRuntimeResolver(
            self.root,
            self.environ,
            tool_dirs=self._tool_dirs(),
        ).resolve()
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
        java = JavaRuntimeResolver(
            self.root,
            self.environ,
            tool_dirs=self._tool_dirs(),
        ).resolve()
        return (
            VineflowerAdapter(java, self._vineflower_path()),
            CfrAdapter(java, self._cfr_path()),
        )

    def _vineflower_path(self) -> Path:
        configured = str(self.environ.get("VR_VINEFLOWER_JAR") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return self._first_tool(
            Path("decompilers") / f"vineflower-{VINEFLOWER_VERSION}.jar"
        )

    def _cfr_path(self) -> Path:
        configured = str(self.environ.get("VR_CFR_JAR") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return self._first_tool(Path("decompilers") / f"cfr-{CFR_VERSION}.jar")

    def _first_tool(self, relative: Path) -> Path:
        candidates = [tool_dir / relative for tool_dir in self._tool_dirs()]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _tool_dirs(self) -> tuple[Path, ...]:
        """Find project-local and Studio-portable tools without changing Java."""

        candidates: list[Path] = []
        configured = str(self.environ.get("VR_CODE_TOOLS_DIR") or "").strip()
        if configured:
            candidates.append(Path(configured).expanduser())
        candidates.extend(
            (
                self.root / "tools" / "code-analysis",
                self.root / "VRProject" / "tools" / "code-analysis",
            )
        )
        app_dirs: list[Path] = []
        if self.app_dir is not None:
            app_dirs.append(self.app_dir)
        if getattr(sys, "frozen", False):
            app_dirs.append(Path(sys.executable).resolve().parent)
        for app in app_dirs:
            candidates.extend(
                (
                    app / "tools" / "code-analysis",
                    app / "VRProject" / "tools" / "code-analysis",
                    app.parent / "VRProject" / "tools" / "code-analysis",
                )
            )
        unique: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(resolved)
        return tuple(unique)


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


def _process_creation_flags(priority: str) -> int:
    flags = _no_window_flag()
    if os.name == "nt" and str(priority or "").casefold() == "low":
        flags |= int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000))
    return flags


def _limit_process_cpu(pid: int, max_cpu_cores: int, *, offset: int = 0) -> bool:
    requested = max(1, int(max_cpu_cores))
    available = max(1, int(os.cpu_count() or 1))
    selected = min(requested, available)
    if selected >= available:
        return True
    if os.name == "nt":
        try:
            import ctypes

            process_set_information = 0x0200
            process_query_limited_information = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_uint32,
            ]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(
                process_set_information | process_query_limited_information,
                False,
                int(pid),
            )
            if not handle:
                return False
            try:
                kernel32.SetProcessAffinityMask.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                ]
                kernel32.SetProcessAffinityMask.restype = ctypes.c_int
                start = max(0, int(offset)) % available
                selected_cores = {
                    (start + core_index) % available
                    for core_index in range(selected)
                }
                mask = sum(1 << core_index for core_index in selected_cores)
                return bool(kernel32.SetProcessAffinityMask(handle, mask))
            finally:
                kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel32.CloseHandle.restype = ctypes.c_int
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return False
    try:
        if hasattr(os, "sched_setaffinity"):
            start = max(0, int(offset)) % available
            os.sched_setaffinity(
                pid,
                {(start + core_index) % available for core_index in range(selected)},
            )
            return True
    except (OSError, ValueError):
        return False
    return False


class _ProcessSampler:
    """Best-effort per-process telemetry without an external dependency."""

    def __init__(self, pid: int) -> None:
        self._handle = None
        if os.name != "nt":
            return
        try:
            import ctypes

            query_limited_information = 0x1000
            process_vm_read = 0x0010
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_uint32,
            ]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            self._handle = kernel32.OpenProcess(
                query_limited_information | process_vm_read,
                False,
                int(pid),
            )
        except (AttributeError, OSError, ValueError):
            self._handle = None

    def sample(self) -> tuple[int, int, int] | None:
        if not self._handle or os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            memory = ProcessMemoryCounters()
            memory.cb = ctypes.sizeof(memory)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if not psapi.GetProcessMemoryInfo(
                self._handle, ctypes.byref(memory), memory.cb
            ):
                return None
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetProcessTimes.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
            ]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            if not kernel32.GetProcessTimes(
                self._handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            return (
                int(memory.PeakWorkingSetSize),
                _filetime_milliseconds(user),
                _filetime_milliseconds(kernel),
            )
        except (AttributeError, OSError, ValueError):
            return None

    def close(self) -> None:
        if not self._handle or os.name != "nt":
            return
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(self._handle)
        except (AttributeError, OSError, ValueError):
            pass
        self._handle = None


def _filetime_milliseconds(value: object) -> int:
    high = int(getattr(value, "dwHighDateTime", 0))
    low = int(getattr(value, "dwLowDateTime", 0))
    return int(((high << 32) | low) / 10_000)


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _directory_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += int(item.stat().st_size)
    except OSError:
        return total
    return total


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

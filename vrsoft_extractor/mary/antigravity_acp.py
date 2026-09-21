"""Bounded ACP transport and the Studio-owned Google profile.

OAuth, session state and tokens remain owned by Google's installed runtime.
No CLI/IDE token is copied into this profile.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from .. import __version__
from .antigravity_auth import AuthStreamParser, normalize_browser_url, try_validate_authorization_url
from .provider_cli import native_cli_path  # noqa: F401  # patch target em tests/test_provider_cli_install.py

logger = logging.getLogger(__name__)

INIT_TIMEOUT_SECONDS = 45.0
HEALTH_TIMEOUT = 60.0
AUTH_TIMEOUT = 300.0
SESSION_TIMEOUT = 90.0
MAX_PROTOCOL_LINE = 8 * 1024 * 1024

# Every AcpClient owns one exclusive temporary directory. A lock file kept open
# inside it proves live ownership across processes, so a reconciliation pass
# never removes a directory that another active ACP process (possibly from
# another VRStudio instance) is still using.
ACP_TEMP_OWNER_LOCK = ".vrstudio-owner.lock"

# Directories created before the owner lock existed cannot prove liveness;
# they are only reclaimed after this grace period.
LEGACY_ACP_TEMP_GRACE_SECONDS = 24 * 60 * 60

REMOVED_ENVIRONMENT_KEYS = {
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_QUOTA_PROJECT",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GCLOUD_PROJECT",
    "CLOUDSDK_CORE_PROJECT",
    "AGY_ACP_CCPA_PROJECT",
    "AGY_ACP_ENABLE_OAUTH",
    "GEMINI_HOME",
    "AGY_ACP_FORCE_FILE_STORAGE",
    "ANTIGRAVITY_HARNESS_PATH",
    "BROWSER",
    "PYTHONUNBUFFERED",
    "GOOGLE_GEMINI_BASE_URL",
    "AGY_ADC_AUTH",
}


class AcpError(RuntimeError):
    """Only fixed diagnostics are exposed; upstream errors can contain secrets."""

    def __init__(
        self,
        method: str,
        code: int | None = None,
        message: str | None = None,
        data: Any = None,
        timed_out: bool = False,
    ):
        self.method = method
        self.code = code
        self.raw_message = message or ""
        self.data = data
        self.timed_out = timed_out
        msg = f"Antigravity: falha em {method}" + (f" (ACP {code})." if code is not None else ".")
        super().__init__(msg)


class AcpTimeoutError(AcpError):
    """Raised when an ACP request or initialization times out."""

    def __init__(self, method: str, timeout: float | None = None):
        self.timeout = timeout
        super().__init__(method=method, timed_out=True)
        self.raw_message = f"Timeout ({timeout}s) waiting for {method}"


class IncompleteRuntimeError(RuntimeError):
    """Raised when an ACP runtime executable is found but its companion harness is missing."""


class BrowserHelperError(RuntimeError):
    """Raised when the browser helper preflight check fails."""


@dataclass(frozen=True)
class AcpRuntimeInfo:
    executable_path: str
    harness_path: str
    version: str | None = None
    runtime_dir: str | None = None


ACP_SERVER_STEM = "agy_acp_server"
HARNESS_STEM = "localharness_external"

RUNTIME_NOT_FOUND_MESSAGE = "Runtime Antigravity ACP não encontrado"

# Basenames of the main Antigravity CLI: never mistake them for the ACP server.
MAIN_CLI_STEMS = {"antigravity", "agy"}

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _platform_exe(stem: str) -> str:
    return f"{stem}.exe" if os.name == "nt" else stem


def _parse_runtime_version(text: str) -> tuple[int, int, int] | None:
    """Parses a semantic version directory name (e.g. "1.1.1", "v1.2.0")."""
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    try:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _version_from_parts(parts) -> str | None:
    for part in parts:
        if any(c.isdigit() for c in part) and ("." in part or "-" in part):
            if not part.startswith("."):
                return part
    return None


def find_acp_server(base: Path | str | None) -> Path | None:
    """Locates the ACP server anchored at an install location.

    Supports the real Antigravity layout where versioned servers nest next
    to the native CLI (``<root>/bin/acp/<version>/agy_acp_server.exe``) as
    well as flat sibling layouts. The anchor itself is only returned when it
    already is the server binary: the main ``agy``/``antigravity`` CLI is
    never mistaken for the ACP server.
    """
    if not base:
        return None
    server_name = _platform_exe(ACP_SERVER_STEM)
    anchor = Path(base)
    if anchor.is_file() and anchor.name == server_name:
        return anchor
    roots = [anchor if anchor.is_dir() else anchor.parent]
    candidates: list[Path] = []
    for root in roots:
        candidates.extend([
            root / server_name,
            root / "bin" / server_name,
        ])
        versioned = root / "acp"
        try:
            if versioned.is_dir():
                versioned_pairs = []
                for child in versioned.iterdir():
                    try:
                        if not child.is_dir():
                            continue
                    except OSError:
                        continue
                    version = _parse_runtime_version(child.name)
                    if version is None:
                        continue
                    server = child / server_name
                    try:
                        if server.is_file():
                            versioned_pairs.append((version, server))
                    except OSError:
                        continue
                versioned_pairs.sort(key=lambda item: item[0], reverse=True)
                candidates.extend(server for _, server in versioned_pairs)
        except OSError:
            pass
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            pass
    return None


def _pair_harness(server: Path) -> Path | None:
    """Resolves the harness strictly inside the server's own installation.

    A server at ``.../acp/<version>/agy_acp_server.exe`` only pairs with the
    ``localharness_external`` living in that same installation. Harness
    binaries from other versions are never mixed in: the caller raises
    :class:`IncompleteRuntimeError` instead.
    """
    harness_name = _platform_exe(HARNESS_STEM)
    server_dir = server.parent
    candidates = [
        server_dir / harness_name,
        server_dir / "resources" / harness_name,
        server_dir / "bin" / harness_name,
    ]
    if server_dir.name.lower() in ("bin", "resources"):
        candidates.append(server_dir.parent / harness_name)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _complete_runtime(server: Path) -> AcpRuntimeInfo:
    """Pairs ``server`` with its same-installation harness or fails fast."""
    harness_name = _platform_exe(HARNESS_STEM)
    try:
        harness = _pair_harness(server)
    except OSError:
        harness = None
    if harness is None or not harness.is_file():
        raise IncompleteRuntimeError(
            f"Runtime Antigravity incompleto: o executável '{server}' foi encontrado, "
            f"mas o helper complementar '{harness_name}' não está presente na mesma instalação."
        )
    version = _version_from_parts(reversed(server.parts[:-1]))
    return AcpRuntimeInfo(
        executable_path=str(server.resolve()),
        harness_path=str(harness.resolve()),
        version=version,
        runtime_dir=str(server.parent.resolve()),
    )


def _scan_agy_version_layout() -> tuple[AcpRuntimeInfo | None, IncompleteRuntimeError | None]:
    """Scans the explicit ``%LOCALAPPDATA%/agy/bin/acp/<version>/`` layout.

    Prefers the highest complete semantic version. An installation is only
    valid when its ``server + harness`` pair is complete; incomplete version
    directories are reported (never silently mixed across versions) without
    a broad recursive search of ``%LOCALAPPDATA%``.
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None, None
    root = Path(base) / "agy" / "bin" / "acp"
    try:
        if not root.is_dir():
            return None, None
        children = list(root.iterdir())
    except OSError:
        return None, None
    server_name = _platform_exe(ACP_SERVER_STEM)
    harness_name = _platform_exe(HARNESS_STEM)
    complete: list[tuple[tuple[int, int, int], Path, Path]] = []
    incomplete: IncompleteRuntimeError | None = None
    for child in sorted(children, key=lambda p: p.name):
        try:
            if not child.is_dir():
                continue
        except OSError:
            continue
        version = _parse_runtime_version(child.name)
        if version is None:
            continue
        server = child / server_name
        try:
            if not server.is_file():
                continue
            if (child / harness_name).is_file():
                complete.append((version, server, child / harness_name))
            elif incomplete is None:
                incomplete = IncompleteRuntimeError(
                    f"Runtime Antigravity incompleto: o executável '{server}' foi encontrado, "
                    f"mas o helper complementar '{harness_name}' não está presente na mesma instalação."
                )
        except OSError:
            continue
    if complete:
        complete.sort(key=lambda item: item[0], reverse=True)
        version, server, harness = complete[0]
        return (
            AcpRuntimeInfo(
                executable_path=str(server.resolve()),
                harness_path=str(harness.resolve()),
                version=_version_dir_label(version, server),
                runtime_dir=str(server.parent.resolve()),
            ),
            None,
        )
    return None, incomplete


def _version_dir_label(version: tuple[int, int, int], server: Path) -> str:
    """Keeps the on-disk version directory label (e.g. "1.1.1")."""
    label = server.parent.name
    if _parse_runtime_version(label) == version:
        return label
    return ".".join(str(part) for part in version)


def _iter_layout_candidates() -> list[list[Path]]:
    """Other compatible layouts, searched only after the explicit ones.

    Roots keep their historical priority: the first root holding a complete
    ``server + harness`` pair wins. Inside a root, semantic version outranks
    anything else and mtime is only a tiebreaker, never the criterion.
    """
    server_name = _platform_exe(ACP_SERVER_STEM)
    localappdata = os.environ.get("LOCALAPPDATA")
    env_dirs = [
        os.environ.get("ANTIGRAVITY_HOME"),
        localappdata,
        os.environ.get("PROGRAMFILES"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    search_roots = [Path(d) for d in env_dirs if d]
    if os.name != "nt":
        search_roots.extend([
            Path.home() / ".antigravity",
            Path.home() / ".local" / "bin",
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/opt/antigravity"),
        ])
    else:
        search_roots.extend([
            Path.home() / ".antigravity",
            Path.home() / "AppData" / "Local" / "Programs" / "Antigravity",
            Path.home() / "AppData" / "Local" / "Antigravity",
        ])
    patterns = (
        server_name,
        f"*/{server_name}",
        f"bin/{server_name}",
        f"antigravity-acp/{server_name}",
        f"antigravity-acp/*/{server_name}",
        f"antigravity-cli/{server_name}",
        f"antigravity-cli/*/{server_name}",
        f"versions/*/{server_name}",
        f"versions/*/bin/{server_name}",
    )

    def sort_key(candidate: Path):
        version = _version_from_parts(reversed(candidate.parts[:-1]))
        parsed = _parse_runtime_version(version or "")
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            mtime = 0.0
        # Semantic version first; mtime is only a tiebreaker, never the criterion.
        return (parsed or (0, 0, 0), mtime)

    grouped: list[list[Path]] = []
    for root in search_roots:
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        found: list[Path] = []
        for pattern in patterns:
            try:
                found.extend(m for m in root.glob(pattern) if m.is_file())
            except OSError:
                continue
        # The explicit %LOCALAPPDATA%/agy/bin/acp/<version>/ layout is owned
        # by the version scan; skip those copies here so generic results can
        # never shadow or mix with the versioned installations.
        if localappdata and root == Path(localappdata):
            versioned = root / "agy" / "bin" / "acp"
            found = [m for m in found if versioned not in m.parents]
        found.sort(key=sort_key, reverse=True)
        if found:
            grouped.append(found)
    return grouped


def _is_main_cli_name(command: str) -> bool:
    stem = Path(command).stem.lower()
    return stem in MAIN_CLI_STEMS


def resolve_acp_runtime(command: str | None = None) -> AcpRuntimeInfo | None:
    """Discovers and pairs the agy_acp_server executable with its mandatory localharness_external companion.

    Resolution order:
    1. explicit path/command;
    2. ``agy_acp_server`` on ``PATH``;
    3. ``%LOCALAPPDATA%/agy/bin/acp/<version>/`` (highest complete semantic version);
    4. other compatible layouts already supported;
    5. generic fallbacks only afterwards.

    The server and harness are never crossed between versions: an installation
    is only valid when its own pair is complete, otherwise
    :class:`IncompleteRuntimeError` is raised once no complete runtime exists.
    """
    incomplete: IncompleteRuntimeError | None = None

    def pair_or_record(server: Path) -> AcpRuntimeInfo | None:
        nonlocal incomplete
        try:
            return _complete_runtime(server)
        except IncompleteRuntimeError as exc:
            if incomplete is None:
                incomplete = exc
            return None
        except OSError:
            return None

    # 1. Explicit path/command. An explicit installation fails fast so a
    # server from one version is never paired with another version's harness.
    if command and not _is_main_cli_name(command):
        cmd_path = Path(command)
        try:
            if cmd_path.is_file():
                return _complete_runtime(cmd_path)
        except IncompleteRuntimeError:
            raise
        except OSError:
            pass
        found = shutil.which(command)
        if found:
            try:
                return _complete_runtime(Path(found))
            except IncompleteRuntimeError:
                raise
            except OSError:
                pass

    # 2. Executable on PATH.
    server_name = _platform_exe(ACP_SERVER_STEM)
    on_path = shutil.which(server_name)
    if on_path:
        info = pair_or_record(Path(on_path))
        if info is not None:
            return info

    # 3. Explicit %LOCALAPPDATA%/agy/bin/acp/<version>/ layout.
    try:
        layout_info, layout_incomplete = _scan_agy_version_layout()
    except OSError:
        layout_info, layout_incomplete = None, None
    if layout_info is not None:
        return layout_info
    if layout_incomplete is not None and incomplete is None:
        incomplete = layout_incomplete

    # 4-5. Other compatible layouts, then generic fallbacks.
    for group in _iter_layout_candidates():
        for candidate in group:
            info = pair_or_record(candidate)
            if info is not None:
                return info

    if incomplete is not None:
        raise incomplete
    return None


def resolve_acp() -> str | None:
    try:
        info = resolve_acp_runtime()
        return info.executable_path if info else None
    except IncompleteRuntimeError:
        raise
    except Exception:
        return None


def spawn_acp_client(
    command: str | None = None,
    runtime_info: AcpRuntimeInfo | None = None,
    *,
    env_factory=None,
    base_env: dict[str, str] | None = None,
    on_auth_url=None,
    on_notification=None,
    on_request=None,
) -> "AcpClient":
    """Creates one ACP client from a single shared runtime resolution.

    Every spawn (interactive login, saved validation, model listing, chat
    turns, probes) goes through this helper so the executable, the harness,
    the version and the environment always describe the same installation::

        runtime = resolve_acp_runtime()  # or a previously resolved runtime
        client = spawn_acp_client(runtime_info=runtime)

    ``IncompleteRuntimeError`` from the resolution propagates untouched.
    """
    info = runtime_info if runtime_info is not None else resolve_acp_runtime(command)
    env = None
    if env_factory is not None:
        try:
            env = env_factory(runtime_info=info)
        except TypeError:
            env = env_factory()
    if env is None:
        env = acp_environment(runtime_info=info, base_env=base_env)
    return AcpClient(
        command=(info.executable_path if info is not None else command),
        runtime_info=info,
        env=env,
        on_auth_url=on_auth_url,
        on_notification=on_notification,
        on_request=on_request,
    )


def profile_path() -> Path:
    """Returns the Studio-owned isolated profile.

    The profile is fixed at ``~/.gemini/vr-norte-studio``. An external
    ``GEMINI_HOME`` is never honored as the Studio profile: reusing the global
    Antigravity IDE/CLI profile would mix credentials and break isolation.
    Child processes receive this fixed path via ``acp_environment`` instead.
    """
    return Path.home() / ".gemini" / "vr-norte-studio"


def prepare_profile(profile_dir: Path | str | None = None) -> Path:
    """Prepares the Studio-owned Antigravity profile without clearing saved tokens."""
    base = Path(profile_dir) if profile_dir else profile_path()
    acp_dir = base / "antigravity-acp"
    tmp_dir = acp_dir / "tmp"
    acp_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    settings_file = acp_dir / "settings.json"
    settings_data = {
        "auth": {
            "type": "oauth-personal"
        }
    }
    settings_file.write_text(json.dumps(settings_data, indent=2) + "\n", encoding="utf-8")

    # Reclaim only temporary directories owned by dead ACP processes. A live
    # owner lock (this process or another VRStudio instance) is never removed.
    try:
        _cleanup_stale_acp_temp_dirs(profile_dir=base)
    except Exception:
        logger.warning("Falha ao reconciliar diretórios temporários ACP órfãos.", exc_info=True)
    return base


def has_saved_account() -> bool:
    # Presence permits a silent validation; it never proves a valid account.
    return (profile_path() / "antigravity-acp/acp_token.json").is_file()


def acp_environment(runtime_info: AcpRuntimeInfo | None = None, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Builds the child-process environment for exactly one resolved runtime.

    An external ``GEMINI_HOME`` is always stripped and then pinned to the
    Studio-owned profile. The harness always comes from ``runtime_info`` (or
    an explicit ``base_env`` override); this factory never runs an independent
    runtime discovery, so a spawn cannot pair a server with another
    installation's harness. Use :func:`spawn_acp_client` for one shared
    resolution per spawn.
    """
    source = os.environ if base_env is None else base_env
    env = {k: v for k, v in source.items() if k.upper() not in REMOVED_ENVIRONMENT_KEYS}
    env["GEMINI_HOME"] = str(profile_path())
    env["AGY_ACP_FORCE_FILE_STORAGE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    if runtime_info is not None:
        env["ANTIGRAVITY_HARNESS_PATH"] = str(runtime_info.harness_path)
    else:
        harness = source.get("ANTIGRAVITY_HARNESS_PATH")
        if harness:
            env["ANTIGRAVITY_HARNESS_PATH"] = str(harness)

    if os.name == "nt":
        exe = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe").as_posix()
        helper = browser_helper_script().as_posix()
        env["BROWSER"] = f'"{exe}" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{helper}" %s'
    else:
        env["BROWSER"] = 'python3 -c "import sys, json; sys.stderr.write(\'__VRSTUDIO_ANTIGRAVITY_AUTH_URL__\' + json.dumps(sys.argv[1].strip().strip(\'\\\'\"\')) + \'\\n\'); sys.stderr.flush()" %s'

    return env


def browser_helper_script() -> Path:
    return Path(__file__).parent / "data" / "antigravity-browser-noop.ps1"


def preflight_browser_helper(timeout: float = 5.0, helper_cmd: list[str] | None = None) -> None:
    """Executes a fast preflight of the browser relay helper with a synthetic URL.

    Verifies:
    - exit code 0;
    - stdout is strictly empty;
    - stderr contains exactly the expected single-line marker frame and synthetic URL;
    - no additional lines or tokens;
    - no timeout.
    """
    synthetic_url = "https://example.invalid/vrstudio-antigravity-browser-preflight"
    expected_marker = f'__VRSTUDIO_ANTIGRAVITY_AUTH_URL__"{synthetic_url}"\n'

    if helper_cmd is not None:
        cmd = list(helper_cmd) + [synthetic_url]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            raise BrowserHelperError("Verificação do helper de navegador expirou (timeout).") from None
        except Exception as exc:
            raise BrowserHelperError(f"Falha ao executar preflight do helper: {exc}") from exc
    elif os.name == "nt":
        exe = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        helper = str(browser_helper_script())
        if not Path(helper).is_file():
            raise BrowserHelperError(f"Helper de navegador não encontrado: {helper}")
        try:
            res = subprocess.run(
                [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                 "-ExecutionPolicy", "Bypass", "-File", helper, synthetic_url],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise BrowserHelperError("Verificação do helper de navegador expirou (timeout).") from None
        except Exception as exc:
            raise BrowserHelperError(f"Falha ao executar preflight do helper de navegador: {exc}") from exc
    else:
        cmd = ["python3", "-c", "import sys, json; sys.stderr.write('__VRSTUDIO_ANTIGRAVITY_AUTH_URL__' + json.dumps(sys.argv[1]) + '\\n'); sys.stderr.flush()", synthetic_url]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise BrowserHelperError("Verificação do helper de navegador expirou (timeout).") from None
        except Exception as exc:
            raise BrowserHelperError(f"Falha ao executar preflight do helper: {exc}") from exc

    if res.returncode != 0:
        raise BrowserHelperError(f"Preflight do helper falhou com código {res.returncode}.")
    if res.stdout != "":
        raise BrowserHelperError("O helper de navegador contaminou stdout com dados não JSON-RPC.")
    normalized_stderr = res.stderr.replace("\r\n", "\n")
    if normalized_stderr != expected_marker:
        raise BrowserHelperError("O helper de navegador não emitiu o frame exato esperado em stderr.")


def stop_process_tree(process) -> None:
    if not process or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            # PyInstaller's one-file ACP runtime has a bootloader and a child.
            # Killing just the bootloader leaves OAuth's listener running.
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _remove_acp_temp_dir(path: Path, *, attempts: int = 4, initial_delay: float = 0.05) -> bool:
    """Removes an owned ACP temporary directory with bounded retries.

    ``shutil.rmtree(..., ignore_errors=True)`` masks ``PermissionError`` and
    loses the reference even when the directory survives, so transient
    failures are retried with a short backoff instead. ``True`` is returned
    only when the path no longer exists.
    """
    target = Path(path)
    delay = initial_delay
    for attempt in range(attempts):
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            return True
        except OSError:
            if attempt == attempts - 1:
                break
            time.sleep(delay)
            delay *= 2
            continue
        if not target.exists():
            return True
    logger.warning("Could not remove owned ACP temporary directory: %s", target)
    return not target.exists()


def _try_acquire_temp_lock(lock_path: Path) -> BinaryIO | None:
    """Acquires the exclusive owner lock of one ACP temporary directory.

    Lock contention means the directory belongs to an active client and
    returns ``None`` without touching it. Unexpected I/O errors also return
    ``None``: such a directory is preserved as not eligible for removal.
    """
    try:
        handle = open(lock_path, "a+b")
    except OSError:
        return None
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError):
        try:
            handle.close()
        except OSError:
            pass
        return None
    return handle


def _release_temp_lock(handle: BinaryIO | None) -> None:
    """Unlocks and closes an owner lock handle, idempotently and best-effort."""
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError):
        pass
    finally:
        try:
            handle.close()
        except OSError:
            pass


def _create_owned_temp_dir(parent: Path, *, prefix: str) -> tuple[str, BinaryIO]:
    """Creates an exclusive ACP temporary directory and keeps its owner lock.

    The returned handle must stay open (owned by the client) for the whole
    lifetime of the directory; releasing it allows the directory to be
    reclaimed later as an orphan.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent)))
    handle = _try_acquire_temp_lock(temp_dir / ACP_TEMP_OWNER_LOCK)
    if handle is None:
        _remove_acp_temp_dir(temp_dir)
        raise OSError(f"Não foi possível adquirir o lock do diretório temporário ACP: {temp_dir}")
    return str(temp_dir), handle


def _cleanup_stale_acp_temp_dirs(profile_dir: Path | str | None = None, *, now: float | None = None) -> int:
    """Reclaims orphaned ACP temporary directories left by previous processes.

    Only the two owned locations are inspected: ``<profile>/antigravity-acp/tmp/proc-*``
    and ``<tempfile.gettempdir()>/vr-acp-*``. A new-format directory is removed
    only when its owner lock can be acquired; a locked directory belongs to a
    live client (possibly from another VRStudio instance) and is preserved.
    Legacy directories without the lock file are removed only after
    :data:`LEGACY_ACP_TEMP_GRACE_SECONDS`. Failures are logged per entry and
    never stop the remaining reclaims or the caller's profile preparation.
    """
    base = Path(profile_dir) if profile_dir else profile_path()
    roots: list[tuple[Path, list[str]]] = []
    prefixes_by_key: dict[str, list[str]] = {}
    for root, prefix in ((base / "antigravity-acp" / "tmp", "proc-"), (Path(tempfile.gettempdir()), "vr-acp-")):
        try:
            key = os.path.normcase(str(root.resolve()))
        except OSError:
            key = os.path.normcase(str(root))
        if key in prefixes_by_key:
            prefixes_by_key[key].append(prefix)
        else:
            prefixes_by_key[key] = [prefix]
            roots.append((root, prefixes_by_key[key]))
    reference = time.time() if now is None else now
    removed = 0
    for root, prefixes in roots:
        try:
            if not root.is_dir():
                continue
            entries = list(root.iterdir())
        except OSError:
            logger.warning("Falha ao inspecionar temporários ACP em %s", root)
            continue
        for entry in entries:
            try:
                if not any(entry.name.startswith(prefix) for prefix in prefixes):
                    continue
                if entry.is_symlink() or not entry.is_dir():
                    continue
                lock_path = entry / ACP_TEMP_OWNER_LOCK
                if lock_path.is_file():
                    handle = _try_acquire_temp_lock(lock_path)
                    if handle is None:
                        # Contention or I/O error: the directory may still be
                        # in use, so it must not be removed here.
                        continue
                    _release_temp_lock(handle)
                    if _remove_acp_temp_dir(entry):
                        removed += 1
                    continue
                try:
                    modified = entry.stat().st_mtime
                except OSError:
                    logger.warning("Falha ao inspecionar temporário ACP órfão: %s", entry)
                    continue
                if reference - modified < LEGACY_ACP_TEMP_GRACE_SECONDS:
                    continue
                if _remove_acp_temp_dir(entry):
                    removed += 1
            except OSError:
                logger.warning("Falha ao reconciliar temporário ACP órfão: %s", entry)
    return removed


def extract_acp_models(session: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extracts available models and default flag from an ACP session response.

    Looks first for configOptions representing a model select (with currentValue),
    falling back to models.availableModels and models.currentModelId.
    Preserves native IDs.
    """
    if not isinstance(session, dict):
        return []

    # 1. Look for model select in configOptions
    config_options = session.get("configOptions")
    if isinstance(config_options, list):
        for opt in config_options:
            if not isinstance(opt, dict):
                continue
            opt_id = str(opt.get("id") or "").lower()
            opt_category = str(opt.get("category") or "").lower()
            opt_type = str(opt.get("type") or "").lower()
            if (opt_id == "model" or opt_category == "model") and (not opt_type or opt_type == "select"):
                current_value = opt.get("currentValue")
                options = opt.get("options")
                if isinstance(options, list) and options:
                    items: list[dict[str, Any]] = []
                    for item in options:
                        if isinstance(item, dict):
                            model_id = item.get("value") or item.get("id") or item.get("modelId")
                            name = item.get("name") or item.get("label") or item.get("displayName") or model_id
                            desc = item.get("description") or ""
                        elif isinstance(item, str):
                            model_id = item
                            name = item
                            desc = ""
                        else:
                            continue
                        if isinstance(model_id, str) and model_id:
                            items.append({
                                "id": model_id,
                                "modelId": model_id,
                                "model": model_id,
                                "name": str(name),
                                "displayName": str(name),
                                "description": str(desc),
                                "isDefault": model_id == current_value if current_value is not None else False,
                            })
                    if items:
                        return items

    # 2. Fallback to models.availableModels and models.currentModelId
    models_obj = session.get("models")
    if isinstance(models_obj, dict):
        current_id = models_obj.get("currentModelId")
        available = models_obj.get("availableModels")
        if isinstance(available, list):
            items = []
            for item in available:
                if not isinstance(item, dict):
                    continue
                model_id = item.get("modelId") or item.get("id")
                if isinstance(model_id, str) and model_id:
                    name = item.get("name") or item.get("displayName") or model_id
                    desc = item.get("description") or ""
                    items.append({
                        "id": model_id,
                        "modelId": model_id,
                        "model": model_id,
                        "name": str(name),
                        "displayName": str(name),
                        "description": str(desc),
                        "isDefault": model_id == current_id if current_id is not None else False,
                    })
            return items

    return []


class AcpClient:
    def __init__(
        self,
        command=None,
        env=None,
        on_auth_url=None,
        on_notification=None,
        on_request=None,
        runtime_info: AcpRuntimeInfo | None = None,
    ):
        if runtime_info is not None:
            self.runtime_info = runtime_info
            self.command = runtime_info.executable_path
        else:
            # No independent discovery here: every spawn resolves exactly once
            # through resolve_acp_runtime()/spawn_acp_client and passes the
            # shared result in. A missing command fails deterministically in
            # start() instead of pairing whatever happens to be on disk.
            self.command = command
            self.runtime_info = None
        self.env = env if env is not None else acp_environment(runtime_info=self.runtime_info)
        if self.runtime_info is not None:
            self.env["ANTIGRAVITY_HARNESS_PATH"] = str(self.runtime_info.harness_path)
        self.on_auth_url = on_auth_url
        self.on_notification = on_notification
        self.on_request = on_request
        self.process = None
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending = {}
        self._serial = 0
        self._closed = False
        self._readers = []
        self.capabilities = {}
        # The owned temporary directory is created exactly once in start(),
        # never in __init__, so a constructed-but-never-started client owns
        # nothing on disk.
        self._temp_dir = None
        self._temp_lock: BinaryIO | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def start(self, timeout: float = INIT_TIMEOUT_SECONDS):
        with self._lock:
            if self._closed:
                raise AcpError("initialize")
            if not self.command:
                raise RuntimeError(RUNTIME_NOT_FOUND_MESSAGE)

            if self.process is not None:
                raise AcpError("initialize")

            prepare_profile()

            # Isolated per-process temporary directory inside the profile's tmp/ created once on start()
            if self._temp_dir is None:
                prof_tmp = profile_path() / "antigravity-acp" / "tmp"
                try:
                    prof_tmp.mkdir(parents=True, exist_ok=True)
                    self._temp_dir, self._temp_lock = _create_owned_temp_dir(prof_tmp, prefix="proc-")
                except Exception:
                    self._temp_dir, self._temp_lock = _create_owned_temp_dir(
                        Path(tempfile.gettempdir()), prefix="vr-acp-"
                    )

            env = dict(self.env)
            env.update(TEMP=self._temp_dir, TMP=self._temp_dir, TMPDIR=self._temp_dir)
            try:
                self.process = subprocess.Popen(
                    [self.command],
                    cwd=str(Path.home()),
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except OSError:
                self.close()
                raise
            for name in ("stdout", "stderr"):
                reader = threading.Thread(target=self._read, args=(getattr(self.process, name), name), daemon=True)
                self._readers.append(reader)
                reader.start()
        result = self.request("initialize", {"protocolVersion": 1,
                              "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                              "clientInfo": {"name": "vr-norte-studio", "version": __version__}}, timeout=timeout)
        if result.get("protocolVersion") != 1:
            raise AcpError("initialize")
        self.capabilities = result.get("agentCapabilities", {})
        if not any(x.get("id") == "oauth-personal" for x in result.get("authMethods", [])):
            raise AcpError("authenticate")
        return result

    def request(self, method, params, timeout=SESSION_TIMEOUT):
        with self._lock:
            if self._closed:
                raise AcpError(method)
            self._serial += 1
            request_id = self._serial
            future = Future()
            self._pending[request_id] = (future, method)
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            return future.result(timeout=timeout)
        except FutureTimeout:
            raise AcpTimeoutError(method=method, timeout=timeout) from None
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, request_id, result):
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _send(self, payload):
        with self._write_lock:
            if not self.process or self._closed:
                raise AcpError("transport")
            try:
                self.process.stdin.write((json.dumps(payload, ensure_ascii=True) + "\n").encode())
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise AcpError("transport") from None

    def _read(self, stream, name):
        parser = AuthStreamParser(
            self._auth_url,
            self._receive if name == "stdout" else None,
            max_line_bytes=MAX_PROTOCOL_LINE if name == "stdout" else 65536,
        )
        try:
            while not self._closed:
                chunk = stream.read(8192)
                if not chunk:
                    break
                parser.feed(chunk)
            parser.finish()
        except (OSError, ValueError, AcpError):
            pass
        finally:
            if name == "stdout":
                self._fail_pending()

    def _auth_url(self, url):
        clean = normalize_browser_url(url)
        if try_validate_authorization_url(clean) is None:
            # Non-OAuth URL (AccountChooser, Google One, promotional, or
            # incomplete OAuth). Never log the raw URL — it may contain
            # email, state, or other sensitive query parameters.
            logger.debug("URL de navegador não-OAuth ignorada.")
            return
        if self.on_auth_url:
            self.on_auth_url(clean)
        else:
            # Only an explicit login may start OAuth. A model refresh or chat
            # must never leave an invisible browser flow waiting for 5 minutes.
            self._fail_pending(AcpError("authenticate", -32000))
            threading.Thread(target=self.close, daemon=True).start()

    def _receive(self, line):
        try:
            message = json.loads(line)
        except ValueError:
            return
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return
        if "method" in message:
            method, params = message["method"], message.get("params", {})
            if "id" in message:
                if self.on_request:
                    self.on_request(message["id"], method, params)
                elif method == "session/request_permission":
                    self.respond(message["id"], {"outcome": {"outcome": "cancelled"}})
                else:
                    self._send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Unsupported client method"}})
            elif self.on_notification:
                self.on_notification(method, params)
            return
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return
        with self._lock:
            pending = self._pending.get(request_id)
            if pending and not pending[0].done():
                future, method = pending
                if "error" in message:
                    error = message["error"]
                    code = error.get("code") if isinstance(error, dict) else None
                    msg = error.get("message") if isinstance(error, dict) else ""
                    data = error.get("data") if isinstance(error, dict) else None
                    future.set_exception(AcpError(method, code if isinstance(code, int) else None, message=msg, data=data))
                elif isinstance(message.get("result"), dict):
                    future.set_result(message["result"])
                else:
                    future.set_exception(AcpError(method))

    def _fail_pending(self, error=None):
        with self._lock:
            for future, method in self._pending.values():
                if not future.done():
                    future.set_exception(error or AcpError(method))

    def __del__(self):
        # Best-effort only: close() owns the termination check, so the
        # destructor can never delete a temporary directory that a still
        # running ACP process may be using.
        try:
            self.close()
        except Exception:
            pass

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self.process
            temp_dir = self._temp_dir
            temp_lock = self._temp_lock
            self._temp_dir = None
            self._temp_lock = None
        self._fail_pending()
        if process and process.stdin:
            try:
                process.stdin.close()
            except Exception:
                pass
        if process and process.poll() is None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                stop_process_tree(process)
        for reader in self._readers:
            if reader is not threading.current_thread():
                reader.join(timeout=2)
        if process:
            for stream in (process.stdout, process.stderr):
                if stream:
                    try:
                        stream.close()
                    except Exception:
                        pass
        if not temp_dir:
            return
        if process is not None and process.poll() is None:
            # The process survived the shutdown routine: keep the owner lock
            # and the directory so nothing reclaims what it is still using.
            self._temp_lock = temp_lock
            logger.warning("Diretório temporário ACP preservado; processo ainda ativo: %s", temp_dir)
            return
        _release_temp_lock(temp_lock)
        _remove_acp_temp_dir(temp_dir)

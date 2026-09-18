"""Bounded ACP transport and the Studio-owned Google profile.

OAuth, session state and tokens remain owned by Google's installed runtime.
No CLI/IDE token is copied into this profile.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import __version__
from .antigravity_auth import AuthStreamParser
from .provider_cli import native_cli_path

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT = 60.0
AUTH_TIMEOUT = 300.0
SESSION_TIMEOUT = 90.0
MAX_PROTOCOL_LINE = 8 * 1024 * 1024

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
    ):
        self.method = method
        self.code = code
        self.raw_message = message or ""
        self.data = data
        msg = f"Antigravity: falha em {method}" + (f" (ACP {code})." if code is not None else ".")
        super().__init__(msg)


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


def find_acp_server(base: Path | str | None) -> Path | None:
    if not base:
        return None
    p = Path(base)
    server_name = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
    if p.is_file() and p.name.lower() in (server_name.lower(), "agy_acp_server.par"):
        return p

    base_dir = p.parent if p.is_file() or p.suffix else p

    # 1. Direct sibling (for unit-test fixtures or flat portable layouts)
    direct = base_dir / server_name
    if direct.is_file():
        return direct
    if os.name != "nt":
        direct_par = base_dir / "agy_acp_server.par"
        if direct_par.is_file():
            return direct_par

    # 2. Nested under acp/<version>/ (official Antigravity CLI layout)
    for parent_dir in (base_dir, base_dir.parent):
        acp_dir = parent_dir / "acp"
        if acp_dir.is_dir():
            matches = [m for m in acp_dir.rglob(server_name) if m.is_file()]
            if os.name != "nt":
                matches.extend([m for m in acp_dir.rglob("agy_acp_server.par") if m.is_file()])
            if matches:
                def sort_key(item: Path):
                    try:
                        parts = tuple(int(x) for x in item.parent.name.split("."))
                    except Exception:
                        parts = ()
                    return (parts, item.stat().st_mtime)
                matches.sort(key=sort_key, reverse=True)
                return matches[0]

    return None


def resolve_acp_runtime(candidate: Path | str | None = None) -> AcpRuntimeInfo:
    harness_name = "localharness_external.exe" if os.name == "nt" else "localharness_external"
    server_name = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"

    if candidate:
        p = Path(candidate)
        if p.is_file():
            harness = p.parent / harness_name
            if not harness.is_file():
                raise IncompleteRuntimeError(
                    f"Runtime Antigravity incompleto: o executável companion '{harness_name}' não foi encontrado em '{p.parent}'. Atualize ou reinstale o Antigravity."
                )
            version = p.parent.name if any(c.isdigit() for c in p.parent.name) else None
            return AcpRuntimeInfo(
                executable_path=str(p.resolve()),
                harness_path=str(harness.resolve()),
                version=version,
                runtime_dir=str(p.parent.resolve()),
            )
        found = find_acp_server(p)
        if found and found.is_file():
            harness = found.parent / harness_name
            if not harness.is_file():
                raise IncompleteRuntimeError(
                    f"Runtime Antigravity incompleto: o executável companion '{harness_name}' não foi encontrado em '{found.parent}'. Atualize ou reinstale o Antigravity."
                )
            version = found.parent.name if any(c.isdigit() for c in found.parent.name) else None
            return AcpRuntimeInfo(
                executable_path=str(found.resolve()),
                harness_path=str(harness.resolve()),
                version=version,
                runtime_dir=str(found.parent.resolve()),
            )
        # Non-file string fallback (e.g. for unit test mock values like "acp")
        return AcpRuntimeInfo(
            executable_path=str(candidate),
            harness_path=str(Path(candidate).parent / harness_name),
            version=None,
            runtime_dir=str(Path(candidate).parent),
        )

    # Search PATH
    direct = shutil.which(server_name) or (shutil.which("agy_acp_server") if os.name == "nt" else None)
    if direct and Path(direct).is_file():
        harness = Path(direct).parent / harness_name
        if not harness.is_file():
            raise IncompleteRuntimeError(
                f"Runtime Antigravity incompleto: o executável companion '{harness_name}' não foi encontrado em '{Path(direct).parent}'. Atualize ou reinstale o Antigravity."
            )
        version = Path(direct).parent.name if any(c.isdigit() for c in Path(direct).parent.name) else None
        return AcpRuntimeInfo(
            executable_path=str(Path(direct).resolve()),
            harness_path=str(harness.resolve()),
            version=version,
            runtime_dir=str(Path(direct).parent.resolve()),
        )

    cli = shutil.which("agy.exe") or shutil.which("agy")
    candidates = [Path(cli)] if cli else []
    candidates.append(native_cli_path("antigravity"))
    for cand in candidates:
        found = find_acp_server(cand)
        if found and found.is_file():
            harness = found.parent / harness_name
            if not harness.is_file():
                raise IncompleteRuntimeError(
                    f"Runtime Antigravity incompleto: o executável companion '{harness_name}' não foi encontrado em '{found.parent}'. Atualize ou reinstale o Antigravity."
                )
            version = found.parent.name if any(c.isdigit() for c in found.parent.name) else None
            return AcpRuntimeInfo(
                executable_path=str(found.resolve()),
                harness_path=str(harness.resolve()),
                version=version,
                runtime_dir=str(found.parent.resolve()),
            )

    raise FileNotFoundError("Servidor Antigravity ACP não encontrado.")


def resolve_acp() -> str | None:
    try:
        info = resolve_acp_runtime()
        return info.executable_path if info else None
    except IncompleteRuntimeError:
        raise
    except Exception:
        return None


def profile_path() -> Path:
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
    return base


def has_saved_account() -> bool:
    # Presence permits a silent validation; it never proves a valid account.
    return (profile_path() / "antigravity-acp/acp_token.json").is_file()


def acp_environment(runtime_info: AcpRuntimeInfo | None = None, base_env: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base_env is None else base_env
    env = {k: v for k, v in source.items() if k.upper() not in REMOVED_ENVIRONMENT_KEYS}
    env["GEMINI_HOME"] = str(profile_path())
    env["AGY_ACP_FORCE_FILE_STORAGE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    harness = runtime_info.harness_path if runtime_info else source.get("ANTIGRAVITY_HARNESS_PATH")
    if not harness:
        try:
            resolved = resolve_acp_runtime()
            if resolved:
                harness = resolved.harness_path
        except Exception:
            pass
    if harness:
        env["ANTIGRAVITY_HARNESS_PATH"] = str(harness)

    if os.name == "nt":
        exe = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe").as_posix()
        helper = browser_helper_script().as_posix()
        env["BROWSER"] = f'"{exe}" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{helper}" %s'
    else:
        env["BROWSER"] = 'python3 -c "import sys, json; sys.stderr.write(\'__VRSTUDIO_ANTIGRAVITY_AUTH_URL__\' + json.dumps(sys.argv[1]) + \'\\n\'); sys.stderr.flush()" %s'

    return env


def browser_helper_script() -> Path:
    return Path(__file__).parent / "data" / "antigravity-browser-noop.ps1"


def preflight_browser_helper(timeout: float = 5.0) -> None:
    """Executes a fast preflight of the browser relay helper with a synthetic URL.

    Verifies:
    - exit code 0;
    - stdout is completely empty;
    - stderr contains exactly the expected marker and synthetic URL;
    - no timeout.
    """
    synthetic_url = "https://example.invalid/vrstudio-antigravity-browser-preflight"
    if os.name == "nt":
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
    if res.stdout.strip():
        raise BrowserHelperError("O helper de navegador contaminou stdout com dados não JSON-RPC.")
    expected_marker = f'__VRSTUDIO_ANTIGRAVITY_AUTH_URL__"{synthetic_url}"'
    if expected_marker not in res.stderr:
        raise BrowserHelperError("O helper de navegador não emitiu o marker esperado em stderr.")


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
            self.command = command or resolve_acp()
            self.runtime_info = None
        self.env = env if env is not None else acp_environment(runtime_info=self.runtime_info)
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
        prof_tmp = profile_path() / "antigravity-acp" / "tmp"
        try:
            prof_tmp.mkdir(parents=True, exist_ok=True)
            self._temp_dir = tempfile.mkdtemp(prefix="proc-", dir=str(prof_tmp))
            if self.env is not None:
                self.env["TEMP"] = self._temp_dir
                self.env["TMP"] = self._temp_dir
        except Exception:
            self._temp_dir = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def start(self):
        with self._lock:
            if self._closed:
                raise AcpError("initialize")
            if not self.command:
                raise RuntimeError("Servidor Antigravity ACP não encontrado. Atualize o Antigravity CLI.")

            if self.process is not None:
                raise AcpError("initialize")

            prepare_profile()

            # Isolated per-process temporary directory inside the profile's tmp/
            prof_tmp = profile_path() / "antigravity-acp" / "tmp"
            try:
                prof_tmp.mkdir(parents=True, exist_ok=True)
                self._temp_dir = tempfile.mkdtemp(prefix="proc-", dir=str(prof_tmp))
            except Exception:
                self._temp_dir = tempfile.mkdtemp(prefix="vr-acp-")

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
                              "clientInfo": {"name": "vr-norte-studio", "version": __version__}}, HEALTH_TIMEOUT)
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
            raise AcpError(method) from None
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
        if self.on_auth_url:
            self.on_auth_url(url)
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

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self.process
            temp_dir = self._temp_dir
            self._temp_dir = None
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
        if temp_dir and (process is None or process.poll() is not None):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError:
                logger.warning("Could not remove owned ACP temporary directory: %s", temp_dir)

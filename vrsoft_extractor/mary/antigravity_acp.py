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

INIT_TIMEOUT_SECONDS = 45.0
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


def find_acp_server(base: Path | str | None) -> Path | None:
    if not base:
        return None
    p = Path(base)
    candidates = [
        p,
        p / "agy_acp_server.exe",
        p / "agy_acp_server",
        p / "bin" / "agy_acp_server.exe",
        p / "bin" / "agy_acp_server",
    ]
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            pass
    return None


def resolve_acp_runtime(command: str | None = None) -> AcpRuntimeInfo | None:
    """Discovers and pairs the agy_acp_server executable with its mandatory localharness_external companion."""
    server_candidate: Path | None = None
    if command:
        cmd_path = Path(command)
        if cmd_path.is_file():
            server_candidate = cmd_path
        else:
            w = shutil.which(command)
            if w:
                server_candidate = Path(w)

    if not server_candidate:
        ext = ".exe" if os.name == "nt" else ""
        binary_name = f"agy_acp_server{ext}"
        w = shutil.which(binary_name)
        if w:
            server_candidate = Path(w)

    if not server_candidate:
        ext = ".exe" if os.name == "nt" else ""
        binary_name = f"agy_acp_server{ext}"
        env_dirs = [
            os.environ.get("ANTIGRAVITY_HOME"),
            os.environ.get("LOCALAPPDATA"),
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

        for root in search_roots:
            if not root.is_dir():
                continue
            for pattern in (
                binary_name,
                f"*/{binary_name}",
                f"bin/{binary_name}",
                f"antigravity-acp/{binary_name}",
                f"antigravity-acp/*/{binary_name}",
                f"antigravity-cli/{binary_name}",
                f"antigravity-cli/*/{binary_name}",
                f"versions/*/{binary_name}",
                f"versions/*/bin/{binary_name}",
            ):
                matches = list(root.glob(pattern))
                if matches:
                    valid_matches = [m for m in matches if m.is_file()]
                    if valid_matches:
                        valid_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                        server_candidate = valid_matches[0]
                        break
            if server_candidate:
                break

    if not server_candidate or not server_candidate.is_file():
        return None

    harness_ext = ".exe" if os.name == "nt" else ""
    harness_name = f"localharness_external{harness_ext}"

    server_dir = server_candidate.parent
    potential_dirs = [
        server_dir,
        server_dir / "resources",
        server_dir / "bin",
        server_dir.parent,
        server_dir.parent / "resources",
        server_dir.parent / "bin",
    ]

    harness_candidate: Path | None = None
    for d in potential_dirs:
        cand = d / harness_name
        try:
            if cand.is_file():
                harness_candidate = cand
                break
        except OSError:
            pass

    if not harness_candidate:
        parent_runtime_dir = server_dir if (server_dir / "resources").is_dir() else server_dir.parent
        matches = list(parent_runtime_dir.glob(f"**/{harness_name}"))
        if matches:
            valid = [m for m in matches if m.is_file()]
            if valid:
                valid.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                harness_candidate = valid[0]

    if not harness_candidate or not harness_candidate.is_file():
        raise IncompleteRuntimeError(
            f"Runtime Antigravity incompleto: o executável '{server_candidate}' foi encontrado, "
            f"mas o helper complementar '{harness_name}' não está presente na instalação."
        )

    version: str | None = None
    for part in reversed(server_candidate.parts[:-1]):
        if any(c.isdigit() for c in part) and ("." in part or "-" in part):
            if not part.startswith("."):
                version = part
                break

    return AcpRuntimeInfo(
        executable_path=str(server_candidate.resolve()),
        harness_path=str(harness_candidate.resolve()),
        version=version,
        runtime_dir=str(server_dir.resolve()),
    )


def resolve_acp() -> str | None:
    try:
        info = resolve_acp_runtime()
        return info.executable_path if info else None
    except IncompleteRuntimeError:
        raise
    except Exception:
        return None


def profile_path() -> Path:
    base = os.environ.get("GEMINI_HOME")
    if base:
        return Path(base)
    candidates = [
        os.environ.get("APPDATA"),
        os.environ.get("LOCALAPPDATA"),
        str(Path.home() / "AppData/Roaming") if os.name == "nt" else None,
        str(Path.home() / ".config"),
    ]
    for d in candidates:
        if d and Path(d).is_dir():
            return Path(d) / "vr-norte-studio"
    return Path.home() / ".vr-norte-studio"


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

    if runtime_info is not None:
        env["ANTIGRAVITY_HARNESS_PATH"] = str(runtime_info.harness_path)
    else:
        harness = source.get("ANTIGRAVITY_HARNESS_PATH")
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
            self.command = command or resolve_acp()
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
        prof_tmp = profile_path() / "antigravity-acp" / "tmp"
        try:
            prof_tmp.mkdir(parents=True, exist_ok=True)
            self._temp_dir = tempfile.mkdtemp(prefix="proc-", dir=str(prof_tmp))
        except Exception:
            self._temp_dir = tempfile.mkdtemp(prefix="vr-acp-")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def start(self, timeout: float = INIT_TIMEOUT_SECONDS):
        with self._lock:
            if self._closed:
                raise AcpError("initialize")
            if not self.command:
                raise RuntimeError("Servidor Antigravity ACP não encontrado. Atualize o Antigravity CLI.")

            if self.process is not None:
                raise AcpError("initialize")

            prepare_profile()

            # Isolated per-process temporary directory inside the profile's tmp/ created once on start()
            if self._temp_dir is None:
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

    def __del__(self):
        if getattr(self, "_temp_dir", None) and Path(self._temp_dir).is_dir():
            shutil.rmtree(self._temp_dir, ignore_errors=True)

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

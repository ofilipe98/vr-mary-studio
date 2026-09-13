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
from pathlib import Path

from .. import __version__
from .antigravity_auth import AuthStreamParser
from .provider_cli import native_cli_path

HEALTH_TIMEOUT = 45.0
AUTH_TIMEOUT = 300.0
SESSION_TIMEOUT = 90.0
MAX_PROTOCOL_LINE = 8 * 1024 * 1024


class AcpError(RuntimeError):
    """Only fixed diagnostics are exposed; upstream errors can contain secrets."""
    def __init__(self, method: str, code: int | None = None):
        self.method = method
        self.code = code
        super().__init__(f"Antigravity: falha em {method}" + (f" (ACP {code})." if code is not None else "."))


def resolve_acp() -> str | None:
    direct = shutil.which("agy_acp_server.exe") or shutil.which("agy_acp_server")
    if direct:
        return direct
    cli = shutil.which("agy.exe") or shutil.which("agy")
    server_name = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
    candidates = [Path(cli).with_name(server_name)] if cli else []
    candidates.append(native_cli_path("antigravity").with_name(server_name))
    return next((str(p) for p in candidates if p.is_file()), None)


def profile_path() -> Path:
    return Path.home() / ".gemini" / "vr-norte-studio"


def has_saved_account() -> bool:
    # Presence permits a silent validation; it never proves a valid account.
    return (profile_path() / "antigravity-acp/acp_token.json").is_file()


def acp_environment() -> dict[str, str]:
    excluded = {
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GEMINI_BASE_URL",
        "GEMINI_HOME", "BROWSER", "AGY_ADC_AUTH", "AGY_ACP_CCPA_PROJECT",
        "AGY_ACP_FORCE_FILE_STORAGE",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() not in excluded}
    env["GEMINI_HOME"] = str(profile_path())
    env["AGY_ACP_FORCE_FILE_STORAGE"] = "1"
    # The packaged ACP server uses Python webbrowser before printing its URL.
    # Relay its URL through an explicitly flushed pipe. The bundled Python
    # runtime can buffer its own print until OAuth completes, despite
    # PYTHONUNBUFFERED. The Qt bridge validates and opens the relayed URL.
    if os.name == "nt":
        # A Python helper inherits PyInstaller's DLL directory from the ACP
        # bootloader and can hang loading the wrong Python DLL. Use the OS
        # PowerShell host with -File (URL is data, never evaluated as code).
        exe = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe").as_posix()
        helper = (Path(__file__).parent / "data/antigravity-browser-noop.ps1").as_posix()
        env["BROWSER"] = f'"{exe}" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{helper}" %s'
    else:
        env["BROWSER"] = "/usr/bin/true %s"
    env["PYTHONUNBUFFERED"] = "1"
    return env


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
    def __init__(self, command=None, env=None, on_auth_url=None, on_notification=None, on_request=None):
        self.command = command or resolve_acp()
        self.env = env if env is not None else acp_environment()
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
        self._temp_dir: str | None = None

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
            # Only this client owns this directory. Other vr-acp-* directories
            # may belong to active clients, including another Studio process.
            env = dict(self.env)
            self._temp_dir = tempfile.mkdtemp(prefix="vr-acp-")
            env.update(TEMP=self._temp_dir, TMP=self._temp_dir, TMPDIR=self._temp_dir)
            try:
                self.process = subprocess.Popen([self.command], cwd=str(Path.home()), env=env,
                                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
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
        parser = AuthStreamParser(self._auth_url, self._receive if name == "stdout" else None,
                                  max_line_bytes=MAX_PROTOCOL_LINE if name == "stdout" else 65536)
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
                    future.set_exception(AcpError(method, code if isinstance(code, int) else None))
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
                shutil.rmtree(temp_dir)
            except OSError:
                logging.getLogger(__name__).warning("Could not remove owned ACP temporary directory: %s", temp_dir)

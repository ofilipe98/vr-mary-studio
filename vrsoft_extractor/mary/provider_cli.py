"""Official CLI installation and discovery shared by Settings and the harness.

Installers run only on an explicit Settings action, outside the GUI thread.
Sources: learn.chatgpt.com/docs/codex/cli, code.claude.com/docs/en/installation,
antigravity.google/docs/cli/install (verified 2026-09-06).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

INSTALLERS = {
    "codex": "https://chatgpt.com/codex/install",
    "claude": "https://claude.ai/install",
    "antigravity": "https://antigravity.google/cli/install",
}
INSTALL_DOCS = {
    "codex": "https://learn.chatgpt.com/docs/codex/cli",
    "claude": "https://code.claude.com/docs/en/installation",
    "antigravity": "https://antigravity.google/docs/cli/install/",
}


def native_cli_path(provider: str) -> Path:
    name = "agy" if provider == "antigravity" else provider
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        if provider == "codex":
            return Path(os.environ.get("CODEX_INSTALL_DIR") or local / "Programs/OpenAI/Codex/bin") / "codex.exe"
        if provider == "antigravity":
            return local / "agy/bin/agy.exe"
        return Path.home() / ".local/bin/claude.exe"
    return Path.home() / ".local/bin" / name


def resolve_cli(provider: str) -> str | None:
    # Preserve existing PATH/provider selection; native locations cover an
    # installation performed after this process inherited its PATH.
    name = "agy" if provider == "antigravity" else provider
    if provider == "codex":
        shim = shutil.which("codex.cmd") or shutil.which("codex")
        if shim:
            package = Path(shim).parent / "node_modules/@openai/codex"
            matches = list(package.glob("node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe"))
            if matches:
                return str(matches[0])
        direct = shutil.which("codex.exe")
        found = direct if direct and "WindowsApps" not in direct else shim
    else:
        found = shutil.which(name + ".exe") or shutil.which(name + ".cmd") or shutil.which(name)
    if found:
        return found
    if provider in INSTALLERS:
        native = native_cli_path(provider)
        if native.is_file():
            return str(native)
    return None


class InstallCancelled(RuntimeError):
    pass


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise InstallCancelled("Instalação cancelada. Arquivos já instalados são preservados.")


def _stop_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=5,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait(timeout=2)


def _run(command: list[str], cancel: threading.Event, *, timeout: float,
         cwd: Path, env: dict[str, str]) -> str:
    """Bound output, time and cancellation, including installer children."""
    _check_cancel(cancel)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    # File-backed output prevents pipe deadlocks and unbounded Python buffers.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, **flags)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                _check_cancel(cancel)
                if time.monotonic() >= deadline:
                    raise RuntimeError("O tempo limite da instalação/verificação foi excedido. Tente novamente.")
                if os.fstat(output.fileno()).st_size > 8 * 1024 * 1024:
                    raise RuntimeError("O instalador excedeu o limite de saída.")
                cancel.wait(0.1)
            _check_cancel(cancel)
            output.seek(max(0, os.fstat(output.fileno()).st_size - 12_000))
            detail = output.read().decode("utf-8", errors="replace").strip()
            if process.returncode:
                from ..settings import redact_sensitive_text
                raise RuntimeError(f"O comando falhou (código {process.returncode}).\n" + redact_sensitive_text(detail))
            return detail
        finally:
            _stop_tree(process)


def install_cli(provider: str, cancel: threading.Event,
                progress: Callable[[str], None]) -> dict[str, str]:
    if provider not in INSTALLERS:
        raise ValueError("Este provedor não possui instalação integrada.")
    extension = ".ps1" if os.name == "nt" else ".sh"
    url = INSTALLERS[provider] + extension
    env = dict(os.environ)
    env["CODEX_NON_INTERACTIVE"] = "1"
    with tempfile.TemporaryDirectory(prefix="vrstudio-cli-") as temporary:
        work = Path(temporary)
        script = work / ("install" + extension)
        progress("Baixando o instalador oficial…")
        _check_cancel(cancel)
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                if not response.url.startswith("https://"):
                    raise RuntimeError("O instalador deve ser baixado por HTTPS.")
                payload = response.read(2 * 1024 * 1024 + 1)
        except OSError as exc:
            raise RuntimeError("Não foi possível baixar o instalador oficial. Confira a conexão e o proxy e tente novamente.") from exc
        _check_cancel(cancel)
        if not payload or len(payload) > 2 * 1024 * 1024 or payload.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            raise RuntimeError("A fonte oficial não retornou um instalador válido.")
        script.write_bytes(payload)
        if os.name == "nt":
            host = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            command = [str(host), "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                       "-ExecutionPolicy", "Bypass", "-File", str(script)]
        else:
            host = shutil.which("sh" if provider == "codex" else "bash")
            if not host:
                raise RuntimeError("O shell necessário ao instalador não foi encontrado.")
            command = [host, str(script)]
        progress("Instalando o CLI oficial. Isso pode levar alguns minutos…")
        _run(command, cancel, timeout=900, cwd=work, env=env)
        progress("Verificando o executável e a integração com o harness…")
        return verify_cli(provider, cancel, cwd=work, env=env)


def verify_cli(provider: str, cancel: threading.Event, *, cwd: Path | None = None,
               env: dict[str, str] | None = None) -> dict[str, str]:
    work = cwd or Path.home()
    env = dict(os.environ) if env is None else env
    # Verify the native install destination, not a previous npm/PATH copy.
    installed = native_cli_path(provider)
    if not installed.is_file():
        raise RuntimeError("O instalador terminou, mas o CLI não foi encontrado no destino esperado. Consulte a instalação oficial.")
    version = _run([str(installed), "--version"], cancel, timeout=30, cwd=work, env=env)
    if not version:
        raise RuntimeError("O CLI instalado não informou sua versão.")
    harness = installed
    if provider == "antigravity":
        from .antigravity_acp import find_acp_server
        server = find_acp_server(installed)
        if not server or not server.is_file():
            raise RuntimeError("O CLI foi instalado, mas o servidor ACP necessário ao harness não foi encontrado. Consulte a instalação oficial.")
        harness = server
        _verify_acp(str(harness), cancel)
    else:
        args = ["app-server", "--help"] if provider == "codex" else ["--help"]
        help_text = _run([str(harness), *args], cancel, timeout=30, cwd=work, env=env)
        markers = ("app-server",) if provider == "codex" else ("--input-format", "--output-format", "stream-json")
        if not all(marker in help_text for marker in markers):
            raise RuntimeError("O CLI instalado não expõe a interface necessária ao harness.")
    return {"command": str(harness), "version": version.splitlines()[0][:160]}


def _verify_acp(command: str, cancel: threading.Event) -> None:
    # Google's absl-based --help exits with status 1. Validate the exact
    # initialize handshake used by the harness, without authenticate/session/new.
    from .antigravity_acp import AcpClient

    _check_cancel(cancel)
    client = AcpClient(command=command)
    done = threading.Event()

    def watch_cancel():
        while not done.wait(0.1):
            if cancel.is_set():
                client.close()
                return

    watcher = threading.Thread(target=watch_cancel, daemon=True)
    watcher.start()
    try:
        client.start()
        _check_cancel(cancel)
    except Exception as exc:
        _check_cancel(cancel)
        raise RuntimeError("O servidor ACP não respondeu à inicialização do harness. Tente verificar novamente.") from exc
    finally:
        done.set()
        client.close()
        watcher.join(timeout=1)

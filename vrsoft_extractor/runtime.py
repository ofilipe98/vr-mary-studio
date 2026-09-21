from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path


_CHROMIUM_INSTALL_LOCK = threading.Lock()


class PlaywrightRuntimeError(RuntimeError):
    """The compatible Playwright runtime is unavailable."""


def configure_playwright_runtime() -> None:
    if getattr(sys, "frozen", False):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    else:
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")


def _resolve_playwright_chromium_executable() -> Path:
    configure_playwright_runtime()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise PlaywrightRuntimeError(
            "Playwright não está instalado. Repare a instalação do aplicativo/ambiente Python."
        ) from None
    try:
        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path)
    except Exception:
        raise PlaywrightRuntimeError(
            "Não foi possível iniciar o driver Playwright. Repare a instalação do aplicativo/ambiente Python."
        ) from None


def _report_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        try:
            progress(message)
        except Exception:
            # A UI notification must not prevent repair or replace its error.
            pass


def _install_playwright_chromium(*, progress: Callable[[str], None] | None = None) -> None:
    configure_playwright_runtime()
    if getattr(sys, "frozen", False):
        raise PlaywrightRuntimeError(
            "Distribuição incompleta ou corrompida: repare ou reextraia o aplicativo."
        )
    _report_progress(progress, "Preparando o Chromium compatível com o Playwright...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            env=os.environ.copy(),
            shell=False,
            capture_output=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise PlaywrightRuntimeError(
            "Preparação do Chromium excedeu 600 segundos. Verifique a conexão e tente novamente."
        ) from None
    except OSError:
        raise PlaywrightRuntimeError(
            "Não foi possível preparar o Chromium. Verifique o ambiente Python e as permissões."
        ) from None
    if result.returncode != 0:
        raise PlaywrightRuntimeError(
            f"Preparação do Chromium falhou (código {result.returncode}). "
            "Verifique a conexão e as permissões e tente novamente."
        )


def ensure_playwright_chromium(
    *, allow_install: bool = True, progress: Callable[[str], None] | None = None
) -> Path:
    executable = _resolve_playwright_chromium_executable()
    if executable.is_file():
        return executable
    if getattr(sys, "frozen", False):
        raise PlaywrightRuntimeError(
            "Distribuição incompleta ou corrompida: Chromium ausente. "
            "Repare ou reextraia o aplicativo."
        )
    if not allow_install:
        raise PlaywrightRuntimeError(
            "Chromium compatível ausente. Execute a preparação com allow_install=True."
        )
    _report_progress(progress, "Chromium compatível ausente; autorreparo necessário.")
    with _CHROMIUM_INSTALL_LOCK:
        executable = _resolve_playwright_chromium_executable()
        if not executable.is_file():
            _install_playwright_chromium(progress=progress)
            executable = _resolve_playwright_chromium_executable()
            if not executable.is_file():
                raise PlaywrightRuntimeError(
                    "Chromium continua ausente após a preparação. "
                    "Verifique as permissões e repare o ambiente Python."
                )
    _report_progress(progress, "Chromium preparado e disponível.")
    return executable


def find_ffmpeg() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    local_browsers = (
        site_packages
        / "playwright"
        / "driver"
        / "package"
        / ".local-browsers"
    )
    for candidate in local_browsers.glob("ffmpeg-*/ffmpeg-win64.exe"):
        if candidate.exists():
            return str(candidate)
    return None


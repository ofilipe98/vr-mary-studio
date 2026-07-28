from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def configure_playwright_runtime() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")


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


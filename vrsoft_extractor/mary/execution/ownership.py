"""Process identity for durable claims (PID alone is unsafe after a restart)."""
from __future__ import annotations

import os
import sys


def process_identity(pid: int | None = None) -> str:
    pid = os.getpid() if pid is None else int(pid)
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied is not evidence of a dead process.
            return "unknown" if ctypes.get_last_error() == 5 else ""
        try:
            code = wintypes.DWORD()
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return "unknown"
            if code.value != 259:
                return ""
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return "unknown"
            return f"{times[0].dwHighDateTime}:{times[0].dwLowDateTime}"
        finally:
            kernel.CloseHandle(handle)
    try:
        from pathlib import Path
        # Linux stat starttime survives PID reuse; no process signalling is needed.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return ""
    except OSError:
        return "unknown"

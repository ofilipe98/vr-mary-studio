import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from vrsoft_extractor import runtime
from unittest.mock import patch

from vrsoft_extractor.runtime import configure_playwright_runtime


class RuntimeTest(unittest.TestCase):
    def test_configure_playwright_runtime_sets_local_browser_path(self):
        with patch.dict("os.environ", {}, clear=True):
            configure_playwright_runtime()
            import os

            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], "0")


if __name__ == "__main__":
    unittest.main()


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    # Fail closed: even an accidentally unmocked consumer cannot download.
    monkeypatch.setattr(runtime.subprocess, "run", MagicMock(
        side_effect=AssertionError("Real browser installation forbidden in tests")
    ))


def test_external_browser_path_is_preserved(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "external")
    runtime.configure_playwright_runtime()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "external"


def test_frozen_forces_hermetic_path(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "external")
    runtime.configure_playwright_runtime()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "0"


def test_existing_executable_never_installs(tmp_path, monkeypatch):
    executable = tmp_path / "chrome.exe"
    executable.touch()
    monkeypatch.setattr(runtime, "_resolve_playwright_chromium_executable", lambda: executable)
    progress = MagicMock()
    assert runtime.ensure_playwright_chromium(progress=progress) == executable
    runtime.subprocess.run.assert_not_called()
    progress.assert_not_called()


def test_install_re_resolves_compatible_executable(tmp_path, monkeypatch):
    missing = tmp_path / "old" / "chrome.exe"
    installed = tmp_path / "new" / "chrome.exe"
    installed.parent.mkdir()
    installed.touch()
    resolve = MagicMock(side_effect=[missing, missing, installed])
    monkeypatch.setattr(runtime, "_resolve_playwright_chromium_executable", resolve)
    run = MagicMock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    messages = []
    assert runtime.ensure_playwright_chromium(progress=messages.append) == installed
    assert resolve.call_count == 3
    run.assert_called_once_with(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=os.environ.copy(), shell=False, capture_output=True, timeout=600,
    )
    assert run.call_args.kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == "0"
    assert len(messages) == 3


@pytest.mark.parametrize("frozen,allow_install", [(False, False), (True, True), (True, False)])
def test_missing_without_installation(tmp_path, monkeypatch, frozen, allow_install):
    monkeypatch.setattr(sys, "frozen", frozen)
    monkeypatch.setattr(runtime, "_resolve_playwright_chromium_executable", lambda: tmp_path / "missing")
    with pytest.raises(runtime.PlaywrightRuntimeError, match="Distribuição" if frozen else "ausente"):
        runtime.ensure_playwright_chromium(allow_install=allow_install)
    runtime.subprocess.run.assert_not_called()


@pytest.mark.parametrize("failure,match", [
    (subprocess.CompletedProcess([], 7, b"internal", b"traceback"), "código 7"),
    (subprocess.TimeoutExpired("install", 600), "600 segundos"),
    (OSError("internal details"), "permissões"),
    (subprocess.CompletedProcess([], 0), "continua ausente"),
])
def test_install_failures_are_domain_errors(tmp_path, monkeypatch, failure, match):
    monkeypatch.setattr(runtime, "_resolve_playwright_chromium_executable", lambda: tmp_path / "missing")
    run = MagicMock()
    if isinstance(failure, Exception):
        run.side_effect = failure
    else:
        run.return_value = failure
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.PlaywrightRuntimeError, match=match):
        runtime.ensure_playwright_chromium(progress=MagicMock(side_effect=ValueError("UI failed")))
    run.assert_called_once()


def test_concurrent_calls_install_once(tmp_path, monkeypatch):
    executable = tmp_path / "chrome.exe"
    barrier = threading.Barrier(2)
    local = threading.local()
    missing = MagicMock()
    missing.is_file.return_value = False

    def resolve():
        if not getattr(local, "checked", False):
            local.checked = True
            barrier.wait(timeout=5)
            return missing
        return executable

    def install(*args, **kwargs):
        executable.touch()
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(runtime, "_resolve_playwright_chromium_executable", resolve)
    run = MagicMock(side_effect=install)
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(runtime.ensure_playwright_chromium) for _ in range(2)]
        assert [future.result(timeout=5) for future in futures] == [executable, executable]
    run.assert_called_once()


def test_resolver_stops_driver_without_launching(tmp_path):
    context = MagicMock()
    driver = context.__enter__.return_value
    driver.chromium.executable_path = str(tmp_path / "chrome.exe")
    with patch("playwright.sync_api.sync_playwright", return_value=context):
        assert runtime._resolve_playwright_chromium_executable() == tmp_path / "chrome.exe"
    context.__exit__.assert_called_once()
    driver.chromium.launch.assert_not_called()


def test_resolver_missing_package():
    with patch.dict(sys.modules, {"playwright.sync_api": None}):
        with pytest.raises(runtime.PlaywrightRuntimeError, match="não está instalado"):
            runtime._resolve_playwright_chromium_executable()


def test_resolver_driver_failure():
    with patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("internal traceback")):
        with pytest.raises(runtime.PlaywrightRuntimeError, match="driver Playwright") as error:
            runtime._resolve_playwright_chromium_executable()
    assert "internal" not in str(error.value)


def test_frozen_installer_defense(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True)
    with pytest.raises(runtime.PlaywrightRuntimeError, match="Distribuição"):
        runtime._install_playwright_chromium()
    runtime.subprocess.run.assert_not_called()

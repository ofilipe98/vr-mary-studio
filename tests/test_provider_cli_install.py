"""Offline installer lifecycle tests; never modify real CLI installations."""
import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary import provider_cli as cli
from vrsoft_extractor.mary.antigravity_acp import resolve_acp
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.providers import ClaudeProvider, CodexProvider


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bridge(tmp_path, app):
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    instance = StudioBridge(settings, db, prefs)
    yield instance
    instance.close()
    app.processEvents()


@pytest.mark.parametrize("provider", ["codex", "claude", "antigravity"])
def test_install_uses_official_script_and_verifies_native_harness(tmp_path, provider):
    installed = tmp_path / ("agy.exe" if provider == "antigravity" else provider + ".exe")
    installed.touch()
    acp = installed.with_name("agy_acp_server.exe" if os.name == "nt" else "agy_acp_server")
    acp.touch()
    response = io.BytesIO(b"# official fixture installer")
    response.url = cli.INSTALLERS[provider] + ".ps1"
    phases = []
    outputs = ["installed", "1.2.3", "app-server --input-format --output-format stream-json"]
    with patch.object(cli.urllib.request, "urlopen", return_value=response) as download, \
         patch.object(cli, "native_cli_path", return_value=installed), \
         patch.object(cli, "_verify_acp") as verify_acp, \
         patch.object(cli, "_run", side_effect=outputs) as run:
        result = cli.install_cli(provider, threading.Event(), phases.append)
    assert download.call_args.args[0] == cli.INSTALLERS[provider] + (".ps1" if os.name == "nt" else ".sh")
    assert result == {"command": str(acp if provider == "antigravity" else installed), "version": "1.2.3"}
    assert len(phases) == 3
    assert run.call_args_list[1].args[0] == [str(installed), "--version"]
    assert not Path(run.call_args_list[0].args[0][-1]).exists()  # temporary script cleaned
    if provider == "antigravity":
        verify_acp.assert_called_once()


def test_network_failure_never_executes_installer():
    with patch.object(cli.urllib.request, "urlopen", side_effect=OSError("offline")), \
         patch.object(cli, "_run") as run, pytest.raises(RuntimeError, match="conexão"):
        cli.install_cli("codex", threading.Event(), lambda _: None)
    run.assert_not_called()


@pytest.mark.parametrize("body", [b"", b"<!doctype html><html>Access denied", b"x" * (2 * 1024 * 1024 + 1)], ids=["empty", "html", "oversized"])
def test_invalid_download_never_executes(body):
    response = io.BytesIO(body)
    response.url = cli.INSTALLERS["codex"] + ".ps1"
    with patch.object(cli.urllib.request, "urlopen", return_value=response), \
         patch.object(cli, "_run") as run, pytest.raises(RuntimeError, match="válido"):
        cli.install_cli("codex", threading.Event(), lambda _: None)
    run.assert_not_called()


def test_rejects_arbitrary_provider_before_network():
    with patch.object(cli.urllib.request, "urlopen") as download, pytest.raises(ValueError):
        cli.install_cli("codex; injected", threading.Event(), lambda _: None)
    download.assert_not_called()


def test_cancel_before_download_does_not_execute():
    cancel = threading.Event()
    cancel.set()
    with patch.object(cli.urllib.request, "urlopen") as download, pytest.raises(cli.InstallCancelled):
        cli.install_cli("claude", cancel, lambda _: None)
    download.assert_not_called()


def test_success_exit_without_native_binary_is_failure(tmp_path):
    with patch.object(cli, "native_cli_path", return_value=tmp_path / "absent"), \
         pytest.raises(RuntimeError, match="não foi encontrado"):
        cli.verify_cli("codex", threading.Event())


def test_agy_without_acp_is_not_harness_ready(tmp_path):
    binary = tmp_path / "agy.exe"
    binary.touch()
    with patch.object(cli, "native_cli_path", return_value=binary), \
         patch.object(cli, "_run", return_value="1.2.3"), \
         pytest.raises(RuntimeError, match="servidor ACP"):
        cli.verify_cli("antigravity", threading.Event())


def test_incompatible_cli_is_not_harness_ready(tmp_path):
    binary = tmp_path / "claude.exe"
    binary.touch()
    with patch.object(cli, "native_cli_path", return_value=binary), \
         patch.object(cli, "_run", side_effect=["1.0", "unrelated help"]), \
         pytest.raises(RuntimeError, match="interface"):
        cli.verify_cli("claude", threading.Event())


def test_acp_verification_initializes_without_login_or_session():
    with patch("vrsoft_extractor.mary.antigravity_acp.AcpClient") as client:
        cli._verify_acp("server.exe", threading.Event())
    client.return_value.start.assert_called_once()
    client.return_value.close.assert_called_once()
    client.return_value.request.assert_not_called()


def test_acp_verification_failure_and_cancellation_are_distinct():
    with patch("vrsoft_extractor.mary.antigravity_acp.AcpClient") as client:
        client.return_value.start.side_effect = RuntimeError("upstream detail")
        with pytest.raises(RuntimeError, match="não respondeu"):
            cli._verify_acp("server.exe", threading.Event())
        client.return_value.close.assert_called_once()
    cancel = threading.Event()
    with patch("vrsoft_extractor.mary.antigravity_acp.AcpClient") as client:
        def blocked_start():
            assert cancel.wait(2)
            time.sleep(0.2)
        client.return_value.start.side_effect = blocked_start
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        try:
            with pytest.raises(cli.InstallCancelled):
                cli._verify_acp("server.exe", cancel)
        finally:
            timer.cancel()
        assert client.return_value.close.called


def test_existing_native_install_is_found_without_path(tmp_path):
    binary = tmp_path / "codex.exe"
    binary.touch()
    with patch.object(cli, "native_cli_path", return_value=binary), patch.object(cli.shutil, "which", return_value=None):
        assert cli.resolve_cli("codex") == str(binary)


def test_native_fallback_does_not_replace_existing_path_selection(tmp_path):
    native = tmp_path / "claude.exe"
    native.touch()
    with patch.object(cli, "native_cli_path", return_value=native), \
         patch.object(cli.shutil, "which", return_value="existing-custom.exe"):
        assert cli.resolve_cli("claude") == "existing-custom.exe"


def test_new_acp_is_found_without_restarting(tmp_path):
    binary = tmp_path / "agy.exe"
    acp = tmp_path / ("agy_acp_server.exe" if os.name == "nt" else "agy_acp_server")
    with patch("vrsoft_extractor.mary.antigravity_acp.native_cli_path", return_value=binary), \
         patch("vrsoft_extractor.mary.antigravity_acp.shutil.which", return_value=None), \
         patch.dict(os.environ, {"LOCALAPPDATA": str(tmp_path)}):
        assert resolve_acp() is None
        acp.touch()
        assert resolve_acp() == str(acp)


def test_acp_in_nested_version_directory_is_resolved(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / ("agy.exe" if os.name == "nt" else "agy")
    binary.touch()
    server_name = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
    v1 = bin_dir / "acp" / "1.1.0" / server_name
    v2 = bin_dir / "acp" / "1.1.1" / server_name
    v1.parent.mkdir(parents=True)
    v2.parent.mkdir(parents=True)
    v1.touch()
    v2.touch()

    with patch("vrsoft_extractor.mary.antigravity_acp.native_cli_path", return_value=binary), \
         patch("vrsoft_extractor.mary.antigravity_acp.shutil.which", return_value=None):
        assert resolve_acp() == str(v2)


def test_verify_cli_antigravity_finds_nested_acp(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / ("agy.exe" if os.name == "nt" else "agy")
    binary.touch()
    server_name = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server"
    acp = bin_dir / "acp" / "1.1.1" / server_name
    acp.parent.mkdir(parents=True)
    acp.touch()

    with patch.object(cli, "native_cli_path", return_value=binary), \
         patch.object(cli, "_run", return_value="1.1.27"), \
         patch.object(cli, "_verify_acp") as verify_acp:
        result = cli.verify_cli("antigravity", threading.Event())
        assert result == {"command": str(acp), "version": "1.1.27"}
        assert verify_acp.call_count == 1
        assert verify_acp.call_args.args[0] == str(acp)


def test_bridge_clears_error_when_runtime_becomes_available(bridge):
    bridge._provider_install_status["antigravity"] = {
        "runtimeState": "error",
        "installMessage": "O CLI foi instalado, mas o servidor ACP necessário ao harness não foi encontrado.",
    }
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp", return_value="C:/fake/acp/agy_acp_server.exe"):
        bridge.refreshProviders()
    assert "runtimeState" not in bridge._provider_install_status.get("antigravity", {})
    item = next(p for p in bridge.providerItems if p["id"] == "antigravity")
    assert item["available"] is True
    assert item.get("runtimeState") != "error"


@pytest.mark.parametrize("runtime_class", [CodexProvider, ClaudeProvider])
def test_existing_provider_instance_discovers_install(runtime_class):
    with patch(runtime_class.__module__ + ".resolve_cli", return_value=None):
        runtime = runtime_class()
        assert not runtime.available()
    with patch(runtime_class.__module__ + ".resolve_cli", return_value="new-native.exe"):
        assert runtime.available()
        assert runtime.command == "new-native.exe"
    runtime.close()


def test_bridge_deduplicates_and_publishes_verified_harness(bridge):
    runtime = SimpleNamespace(command=None)
    bridge._conversation_orchestrator = SimpleNamespace(providers={"codex": runtime})
    signal = MagicMock()
    bridge.providerRuntimeInstalled.connect(signal)
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_cli", return_value=None), \
         patch.object(bridge._pool, "start") as start:
        bridge.installProviderCli("codex")
        bridge.installProviderCli("codex")
        assert start.call_count == 1
        task = start.call_args.args[0]
        task.signals.progress.emit("Baixando…")
        assert next(p for p in bridge.providerItems if p["id"] == "codex")["installMessage"] == "Baixando…"
        task.signals.finished.emit({"command": "codex.exe", "version": "1.2.3"})
    assert runtime.command == "codex.exe"
    assert bridge._provider_install_status["codex"]["runtimeState"] == "installed"
    assert not bridge._provider_installs
    signal.assert_called_once_with("codex")


def test_install_worker_keeps_qt_responsive_and_updates_on_finish(bridge, app):
    release = threading.Event()
    entered = threading.Event()
    gui_thread = threading.get_ident()

    def install(provider, cancel, progress):
        assert threading.get_ident() != gui_thread
        entered.set()
        progress("Baixando em segundo plano…")
        assert release.wait(3)
        return {"command": "codex.exe", "version": "1"}

    with patch("vrsoft_extractor.mary.frontend.studio.resolve_cli", return_value=None), \
         patch("vrsoft_extractor.mary.frontend.studio.install_cli", side_effect=install):
        bridge.installProviderCli("codex")
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                app.processEvents()
                if bridge._provider_install_status["codex"]["installMessage"] == "Baixando em segundo plano…":
                    break
                time.sleep(0.01)
            assert entered.is_set()
            assert bridge._provider_install_status["codex"]["installMessage"] == "Baixando em segundo plano…"
        finally:
            release.set()
        deadline = time.monotonic() + 2
        while bridge._provider_installs and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert bridge._provider_install_status["codex"]["runtimeState"] == "installed"


def test_bridge_error_retry_ignores_stale_progress(bridge):
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_cli", return_value=None), \
         patch.object(bridge._pool, "start") as start:
        bridge.installProviderCli("claude")
        old = start.call_args.args[0]
        old.signals.failed.emit("Download falhou")
        assert bridge._provider_install_status["claude"]["runtimeState"] == "error"
        bridge.installProviderCli("claude")
        new = start.call_args.args[0]
        old.signals.progress.emit("obsolete")
        old.signals.finished.emit({"command": "wrong.exe", "version": "old"})
        assert bridge._provider_installs["claude"][0] is new
        assert bridge._provider_install_status["claude"]["installMessage"] != "obsolete"
        new.signals.finished.emit({"command": "new.exe", "version": "new"})


def test_cancel_wins_over_late_success_and_close_stops_workers(bridge):
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_cli", return_value=None), \
         patch.object(bridge._pool, "start") as start:
        bridge.installProviderCli("codex")
        task = start.call_args.args[0]
        bridge.cancelProviderInstall("codex")
        task.signals.finished.emit({"command": "new.exe", "version": "new"})
        assert bridge._provider_install_status["codex"]["runtimeState"] == "cancelled"
        bridge.installProviderCli("claude")
        task, cancel = bridge._provider_installs["claude"]
        bridge.close()
        assert cancel.is_set()
        task.signals.finished.emit({"command": "new.exe", "version": "new"})
        assert bridge._provider_install_status["claude"]["runtimeState"] == "installing"


def test_already_installed_does_not_run_installer(bridge):
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_cli", return_value="existing.exe"), \
         patch.object(bridge._pool, "start") as start:
        bridge.installProviderCli("codex")
    start.assert_not_called()


def test_retry_after_partial_install_verifies_without_reinstall(bridge):
    bridge._provider_install_status["codex"] = {"runtimeState": "error"}
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_cli", return_value="existing.exe"), \
         patch("vrsoft_extractor.mary.frontend.studio.verify_cli", return_value={"command": "existing.exe", "version": "1"}) as verify, \
         patch("vrsoft_extractor.mary.frontend.studio.install_cli") as install, \
         patch.object(bridge._pool, "start") as start:
        bridge.installProviderCli("codex")
        start.call_args.args[0].run()
    verify.assert_called_once()
    install.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows login terminal")
def test_login_path_is_data_and_not_shell_source(bridge):
    path = "C:/Users/some ' $name/claude.exe"
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_cli", return_value=path), \
         patch("vrsoft_extractor.mary.frontend.studio.subprocess.Popen") as popen:
        bridge.openProviderLogin("claude")
    assert path not in popen.call_args.args[0][-1]
    assert popen.call_args.kwargs["env"]["VRSTUDIO_LOGIN_CLI"] == path
    assert popen.call_args.kwargs["creationflags"] == subprocess.CREATE_NEW_CONSOLE


def test_runner_reports_exit_failure_and_times_out(tmp_path):
    with pytest.raises(RuntimeError, match="código 7"):
        cli._run([sys.executable, "-c", "print('failure'); raise SystemExit(7)"], threading.Event(),
                 timeout=5, cwd=tmp_path, env=dict(os.environ))
    with pytest.raises(RuntimeError, match="tempo limite"):
        cli._run([sys.executable, "-c", "import time; time.sleep(10)"], threading.Event(),
                 timeout=0.2, cwd=tmp_path, env=dict(os.environ))


def test_runner_cancel_terminates_process(tmp_path):
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(cli.InstallCancelled):
            cli._run([sys.executable, "-c", "import time; time.sleep(10)"], cancel,
                     timeout=20, cwd=tmp_path, env=dict(os.environ))
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5

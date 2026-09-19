from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings

from vrsoft_extractor.mary.config import load_vr_settings
from vrsoft_extractor.mary.frontend.bootstrap import BootstrapBridge
from vrsoft_extractor.mary.settings_service import (
    SETUP_KEY_COMPLETED,
    SETUP_KEY_VERSION,
    SETUP_VERSION,
    get_settings_values,
    is_setup_needed,
    mark_setup_completed,
    save_settings,
)


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root_dir = tmp_path / "vr_root"
    root_dir.mkdir(parents=True, exist_ok=True)
    app_dir = tmp_path / "app_dir"
    app_dir.mkdir(parents=True, exist_ok=True)
    ini_path = tmp_path / "test_settings.ini"

    monkeypatch.setenv("VR_ROOT", str(root_dir))
    settings = load_vr_settings(str(app_dir), str(root_dir))
    prefs = QSettings(str(ini_path), QSettings.Format.IniFormat)
    prefs.clear()
    prefs.sync()

    return {
        "root": root_dir,
        "app_dir": app_dir,
        "settings": settings,
        "prefs": prefs,
        "ini_path": ini_path,
    }


@pytest.fixture
def isolated_runtime_env(monkeypatch: pytest.MonkeyPatch):
    """Snapshot process env keys touched by save_settings (auto-restored)."""
    for key in (
        "VR_ROOT",
        "MOVIDESK_EMAIL",
        "MOVIDESK_PASSWORD",
        "ENDOO_EMAIL",
        "ENDOO_PASSWORD",
        "VR_SYNC_INTERVAL_MINUTES",
        "VR_DEFAULT_EFFORT",
    ):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)


def test_first_run_requires_setup(temp_env):
    """First run without QSettings completed flag requires setup."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]

    assert is_setup_needed(settings, prefs) is True


def test_completed_setup_does_not_require_setup(temp_env):
    """Execution with setup completed flag does not require setup."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]

    mark_setup_completed(prefs)
    assert str(prefs.value(SETUP_KEY_COMPLETED)).lower() == "true"
    assert int(prefs.value(SETUP_KEY_VERSION, 0)) == SETUP_VERSION
    assert is_setup_needed(settings, prefs) is False


def test_invalid_or_missing_root_requires_setup_even_if_marked_complete(temp_env):
    """If root directory does not exist or is invalid, setup is required regardless."""
    prefs = temp_env["prefs"]

    mark_setup_completed(prefs)
    # Point settings to a non-existent path
    bad_settings = load_vr_settings(
        str(temp_env["app_dir"]),
        str(temp_env["root"] / "nonexistent_subfolder_xyz"),
    )
    assert is_setup_needed(bad_settings, prefs) is True


def test_save_settings_with_invalid_root_raises_error(temp_env):
    """Saving with a non-directory path raises an error and does not mark completed."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]

    file_path = temp_env["root"] / "some_file.txt"
    file_path.write_text("hello", encoding="utf-8")

    with pytest.raises(Exception, match="não é um diretório válido"):
        save_settings(
            settings,
            root=str(file_path),
            movidesk_email="test@vr.com.br",
            movidesk_password="pass",
            endoo_email="test@vr.com.br",
            endoo_password="pass",
            interval="120",
        )

    assert prefs.value(SETUP_KEY_COMPLETED) is None


def test_empty_password_preserves_existing_secret(temp_env, monkeypatch: pytest.MonkeyPatch):
    """Leaving password field blank preserves existing credential."""
    settings = temp_env["settings"]
    monkeypatch.setenv("MOVIDESK_PASSWORD", "existing_m_secret")
    monkeypatch.setenv("ENDOO_PASSWORD", "existing_e_secret")

    with patch("vrsoft_extractor.mary.settings_service.save_vr_env") as mock_save_env:
        new_settings, safe_values = save_settings(
            settings,
            root=str(temp_env["root"]),
            movidesk_email="user@vr.com.br",
            movidesk_password="",  # blank
            endoo_email="user@vr.com.br",
            endoo_password="",  # blank
            interval="60",
        )

        mock_save_env.assert_called_once()
        saved_dict = mock_save_env.call_args[0][1]
        assert saved_dict["MOVIDESK_PASSWORD"] == "existing_m_secret"
        assert saved_dict["ENDOO_PASSWORD"] == "existing_e_secret"

        # Check safe values returned
        assert safe_values["movideskPassword"] == ""
        assert safe_values["movideskPasswordConfigured"] is True
        assert safe_values["endooPassword"] == ""
        assert safe_values["endooPasswordConfigured"] is True


def test_passwords_never_exposed_in_settings_values_or_qsettings(temp_env, monkeypatch: pytest.MonkeyPatch):
    """Plain-text passwords must never appear in get_settings_values or QSettings."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]
    monkeypatch.setenv("MOVIDESK_PASSWORD", "super_secret_movidesk")
    monkeypatch.setenv("ENDOO_PASSWORD", "super_secret_endoo")

    vals = get_settings_values(settings)
    assert vals["movideskPassword"] == ""
    assert vals["movideskPasswordConfigured"] is True
    assert vals["endooPassword"] == ""
    assert vals["endooPasswordConfigured"] is True

    mark_setup_completed(prefs)

    # Inspect all keys stored in QSettings
    all_keys = prefs.allKeys()
    for key in all_keys:
        val = str(prefs.value(key))
        assert "super_secret" not in val
        assert "password" not in key.lower()


def test_outdated_setup_version_requires_setup(temp_env):
    """A completed flag with an old schema version must reopen the setup."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]

    mark_setup_completed(prefs)
    prefs.setValue(SETUP_KEY_VERSION, 0)
    prefs.sync()
    assert is_setup_needed(settings, prefs) is True

    prefs.setValue(SETUP_KEY_VERSION, SETUP_VERSION)
    prefs.sync()
    assert is_setup_needed(settings, prefs) is False


def test_save_settings_aligns_runtime_env(temp_env, monkeypatch: pytest.MonkeyPatch, isolated_runtime_env):
    """Persisted emails/interval must take effect in the running process."""
    settings = temp_env["settings"]
    monkeypatch.setenv("MOVIDESK_EMAIL", "old@vr.com.br")
    monkeypatch.setenv("ENDOO_EMAIL", "old@vr.com.br")
    monkeypatch.setenv("VR_SYNC_INTERVAL_MINUTES", "15")
    monkeypatch.setenv("VR_ROOT", str(temp_env["root"]))

    with patch("vrsoft_extractor.mary.settings_service.save_vr_env"):
        new_settings, _safe_values = save_settings(
            settings,
            root=str(temp_env["root"]),
            movidesk_email="new@vr.com.br",
            movidesk_password="",
            endoo_email="endoo@vr.com.br",
            endoo_password="",
            interval="240",
        )

    assert os.environ["MOVIDESK_EMAIL"] == "new@vr.com.br"
    assert os.environ["ENDOO_EMAIL"] == "endoo@vr.com.br"
    assert os.environ["VR_SYNC_INTERVAL_MINUTES"] == "240"
    assert os.environ["VR_ROOT"] == str(temp_env["root"])
    assert new_settings.sync_interval_minutes == 240


def test_bootstrap_save_setup_rejected_when_backend_probe_fails(temp_env, isolated_runtime_env):
    """A refused/failed backend probe must not mark setup as completed."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]

    def _boom(_new_settings):
        raise RuntimeError("db offline")

    for callback in (lambda _new_settings: False, _boom):
        prefs.remove(SETUP_KEY_COMPLETED)
        prefs.remove(SETUP_KEY_VERSION)
        prefs.sync()
        bridge = BootstrapBridge(
            settings,
            prefs,
            initial_state="setup",
            on_setup_completed=callback,
        )
        bridge.saveSetup(
            str(temp_env["root"]),
            "admin@vr.com.br",
            "",
            "admin@vr.com.br",
            "",
            "120",
        )
        assert bridge.state == "setup"
        assert bridge.isSetupActive is True
        assert bridge.errorMessage != ""
        assert str(prefs.value(SETUP_KEY_COMPLETED, "false")).lower() != "true"


def test_bootstrap_save_setup_marks_completed_only_after_probe(temp_env, isolated_runtime_env):
    """Accepted probe -> initializing state and setup/completed persisted."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]

    seen = []

    def accept(new_settings):
        seen.append(new_settings)
        return True

    bridge = BootstrapBridge(
        settings,
        prefs,
        initial_state="setup",
        on_setup_completed=accept,
    )
    bridge.saveSetup(
        str(temp_env["root"]),
        "admin@vr.com.br",
        "",
        "admin@vr.com.br",
        "",
        "120",
    )
    assert len(seen) == 1
    assert bridge.state == "initializing"
    assert bridge.isSetupActive is False
    assert str(prefs.value(SETUP_KEY_COMPLETED)).lower() == "true"
    assert int(prefs.value(SETUP_KEY_VERSION, 0)) == SETUP_VERSION


def test_frontend_bridge_update_settings_after_setup(temp_env):
    """FrontendBridge must stop showing the pre-setup root after setup."""
    from vrsoft_extractor.mary.frontend.bridge import FrontendBridge

    settings = temp_env["settings"]
    prefs = temp_env["prefs"]
    frontend = FrontendBridge(settings, prefs)
    assert frontend.projectPath == str(settings.root)

    new_root = temp_env["root"] / "novo_root"
    new_root.mkdir(parents=True, exist_ok=True)
    new_settings = load_vr_settings(str(temp_env["app_dir"]), str(new_root))

    notified = []
    frontend.projectChanged.connect(lambda: notified.append(True))
    frontend.update_settings(new_settings)

    assert frontend.projectPath == str(new_root)
    assert frontend.projectName == new_root.name
    assert len(notified) == 1


def test_bootstrap_bridge_save_setup_flow(temp_env):
    """Test BootstrapBridge handles saveSetup slot correctly."""
    settings = temp_env["settings"]
    prefs = temp_env["prefs"]

    completed_settings = []
    bridge = BootstrapBridge(
        settings,
        prefs,
        initial_state="setup",
        on_setup_completed=lambda s: completed_settings.append(s),
    )

    assert bridge.state == "setup"
    assert bridge.isSetupActive is True
    assert bridge.isReady is False

    toasts = []
    bridge.toastRequested.connect(lambda msg, kind: toasts.append((msg, kind)))

    # Save with valid root
    bridge.saveSetup(
        str(temp_env["root"]),
        "admin@vr.com.br",
        "new_pass_123",
        "admin@vr.com.br",
        "new_pass_456",
        "120",
    )

    assert len(completed_settings) == 1
    assert str(prefs.value(SETUP_KEY_COMPLETED)).lower() == "true"
    assert any(kind == "success" for _, kind in toasts)
    assert bridge.errorMessage == ""

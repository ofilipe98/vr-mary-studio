from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vrsoft_extractor.mary.config import load_vr_settings
from vrsoft_extractor.mary.frontend.bootstrap import BootstrapBridge


@pytest.fixture
def dummy_settings(tmp_path: Path):
    root_dir = tmp_path / "vr_root"
    root_dir.mkdir(parents=True, exist_ok=True)
    app_dir = tmp_path / "app_dir"
    app_dir.mkdir(parents=True, exist_ok=True)
    return load_vr_settings(str(app_dir), str(root_dir))


def test_bootstrap_lifecycle_transitions(dummy_settings):
    """Test full happy-path transition sequence from loading_apps to ready."""
    bridge = BootstrapBridge(dummy_settings, initial_state="loading_apps")

    states = []
    bridge.stateChanged.connect(lambda: states.append(bridge.state))

    assert bridge.state == "loading_apps"
    assert bridge.isReady is False
    assert bridge.isBusy is True

    # Phase: detecting_apps
    bridge._on_catalog_phase("detecting_apps", 0, 0)
    assert bridge.state == "loading_apps"
    assert "Detectando" in bridge.detailMessage

    # Phase: loading_versions
    bridge._on_catalog_phase("loading_versions", 4, 10)
    assert bridge.state == "loading_versions"
    assert bridge.appsCount == 4
    assert "4 aplicativos encontrados" in bridge.detailMessage

    # Phase: ready
    bridge._on_catalog_phase("ready", 4, 10)
    assert bridge.state == "ready"
    assert bridge.isReady is True
    assert bridge.isBusy is False
    assert "Abrindo VRStudio" in bridge.detailMessage


def test_reviewing_settings_after_error_restarts_bootstrap(tmp_path, monkeypatch):
    """Catalog error -> openSetup -> save -> backend/bootstrap restart -> ready."""
    import os

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

    root_dir = tmp_path / "vr_root"
    root_dir.mkdir(parents=True, exist_ok=True)
    app_dir = tmp_path / "app_dir"
    app_dir.mkdir(parents=True, exist_ok=True)
    settings = load_vr_settings(str(app_dir), str(root_dir))

    mock_chat = MagicMock()
    requested = []

    def on_setup_completed(new_settings):
        assert new_settings.root == settings.root
        requested.append(new_settings)

    mock_bridge = BootstrapBridge(
        settings,
        None,
        initial_state="loading_apps",
        on_setup_completed=on_setup_completed,
    )
    mock_bridge.attach_chat_bridge(mock_chat)

    # Catalog fails during normal startup.
    mock_bridge._on_catalog_phase("error", 0, 0)
    assert mock_bridge.state == "error"

    # "Revisar configurações" must offer a functional way out in every scenario.
    mock_bridge.openSetup()
    assert mock_bridge.state == "setup"
    assert mock_bridge.isSetupActive is True

    mock_bridge.saveSetup(
        str(root_dir),
        "admin@vr.com.br",
        "",
        "admin@vr.com.br",
        "",
        "120",
    )

    # Saving leaves setup and requests the backend; completed waits for it.
    assert mock_bridge.isSetupActive is False
    assert mock_bridge.state == "initializing"
    assert len(requested) == 1

    # The coordinator finishes the backend, marks setup done, restarts catalog.
    mock_bridge.setupInitializationSucceeded(requested[0])
    mock_bridge.start_bootstrap()
    assert mock_chat.refreshApplicationsCatalog.called
    mock_bridge._on_catalog_phase("loading_versions", 2, 7)
    assert mock_bridge.state == "loading_versions"
    assert mock_bridge.versionsCount == 7
    mock_bridge._on_catalog_phase("ready", 2, 7)
    assert mock_bridge.state == "ready"
    assert mock_bridge.isReady is True


def test_bootstrap_error_and_retry(dummy_settings):
    """Test error handling during bootstrap and retry behavior."""
    bridge = BootstrapBridge(dummy_settings, initial_state="loading_apps")
    mock_chat = MagicMock()
    bridge.attach_chat_bridge(mock_chat)

    # Simulate error payload
    bridge._on_catalog_loaded_payload({"error": "Failed to sync releases", "root": dummy_settings.root})

    assert bridge.state == "error"
    assert bridge.errorMessage == "Failed to sync releases"
    assert bridge.isReady is False

    # Trigger retry
    bridge.retryBootstrap()
    assert bridge.state == "loading_apps"
    assert bridge.errorMessage == ""
    assert mock_chat.refreshApplicationsCatalog.called


def test_in_app_refresh_does_not_reopen_startup_screen(dummy_settings):
    """When bootstrap is already ready, in-app catalog refreshes must not reset state to loading_apps."""
    bridge = BootstrapBridge(dummy_settings, initial_state="ready")
    assert bridge.isReady is True
    assert bridge.state == "ready"

    states = []
    bridge.stateChanged.connect(lambda: states.append(bridge.state))

    # In-app refresh emits detecting_apps
    bridge._on_catalog_phase("detecting_apps", 0, 0)
    assert bridge.state == "ready"
    assert bridge.isReady is True
    assert len(states) == 0

    # In-app refresh emits loading_versions
    bridge._on_catalog_phase("loading_versions", 10, 25)
    assert bridge.state == "ready"
    assert bridge.isReady is True

    # In-app refresh emits ready
    bridge._on_catalog_phase("ready", 10, 25)
    assert bridge.state == "ready"
    assert bridge.isReady is True


def test_chat_bridge_catalog_loading_properties(dummy_settings, monkeypatch: pytest.MonkeyPatch):
    """Test that ChatBridge exposes applicationsCatalogLoading and applicationsCatalogLoaded."""
    from vrsoft_extractor.mary.frontend.chat import ChatBridge
    from vrsoft_extractor.mary.db import MaryDatabase

    db = MaryDatabase(dummy_settings.database_path)
    chat = ChatBridge(dummy_settings, db)

    assert chat.applicationsCatalogLoading is False
    assert chat.applicationsCatalogLoaded is False

    # Simulate loaded state
    chat._on_applications_loaded({
        "root": dummy_settings.root,
        "applications": [{"app_id": "VR01"}],
        "packages": [],
        "versions": {},
        "data": {},
    })

    assert chat.applicationsCatalogLoading is False
    assert chat.applicationsCatalogLoaded is True
    assert len(chat.applicationsCatalog) == 1

    chat.close()

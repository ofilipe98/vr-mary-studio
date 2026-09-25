from __future__ import annotations

import pytest
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QObject, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import load_vr_settings
from vrsoft_extractor.mary.frontend.app import (
    create_engine,
    schedule_antigravity_restore,
)
from vrsoft_extractor.mary.frontend.bootstrap import BootstrapBridge
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge

pytestmark = pytest.mark.qml


class StartupQmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_startup_setup_page_elements_and_save_interaction(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            app_dir.mkdir()
            settings = load_vr_settings(str(app_dir), str(root))
            prefs = QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
            frontend_bridge = FrontendBridge(settings, prefs)

            saved_args = []

            def on_save(*args):
                saved_args.append(args)

            bootstrap_bridge = BootstrapBridge(settings, prefs, initial_state="setup")
            bootstrap_bridge.saveSetup = on_save  # type: ignore[method-assign]

            engine = create_engine(
                frontend_bridge,
                chat_bridge=None,
                studio_bridge=None,
                bootstrap_bridge=bootstrap_bridge,
            )
            self.application.processEvents()

            window = engine.rootObjects()[0]
            self.assertIsNotNone(window)
            self.assertTrue(bootstrap_bridge.isSetupActive)
            self.assertFalse(bootstrap_bridge.isReady)

            # Wait for setup loader to instantiate
            for _ in range(30):
                self.application.processEvents()
                if window.findChild(QObject, "setupRootField") is not None:
                    break
                QTest.qWait(10)

            root_field = window.findChild(QObject, "setupRootField")
            self.assertIsNotNone(root_field)
            self.assertEqual(root_field.property("text"), str(settings.root))

            movidesk_email = window.findChild(QObject, "setupMovideskEmail")
            self.assertIsNotNone(movidesk_email)

            save_button = window.findChild(QObject, "setupSaveButton")
            self.assertIsNotNone(save_button)
            self.assertTrue(save_button.property("enabled"))

            # Simulate clicking save
            save_button.clicked.emit()
            self.application.processEvents()

            self.assertEqual(len(saved_args), 1)
            self.assertEqual(saved_args[0][0], str(settings.root))

    def test_first_run_setup_to_loading_without_studio_bridge(self):
        """First-run regression: setup shows with no backend, save leads to loading."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            app_dir.mkdir()
            settings = load_vr_settings(str(app_dir), str(root))
            prefs = QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
            frontend_bridge = FrontendBridge(settings, prefs)

            requested = []

            def on_setup_requested(new_settings):
                # Async handshake like app.main: only request the backend.
                # No initialize_workspace() runs inside saveSetup anymore.
                requested.append(new_settings)

            bootstrap_bridge = BootstrapBridge(
                settings,
                prefs,
                initial_state="setup",
            )
            bootstrap_bridge.setupInitializationRequested.connect(on_setup_requested)

            # studio_bridge does not exist yet: engine creation and the whole
            # setup interaction must never touch it (used to AttributeError).
            engine = create_engine(
                frontend_bridge,
                chat_bridge=None,
                studio_bridge=None,
                bootstrap_bridge=bootstrap_bridge,
            )
            self.application.processEvents()

            window = engine.rootObjects()[0]
            self.assertIsNotNone(window)

            for _ in range(30):
                self.application.processEvents()
                if window.findChild(QObject, "setupRootField") is not None:
                    break
                QTest.qWait(10)
            self.assertIsNotNone(window.findChild(QObject, "setupRootField"))

            new_root = root / "VRProject"
            new_root.mkdir(parents=True, exist_ok=True)
            # Real save path: validate, persist, then initializing; the
            # backend itself is requested async and completes later.
            bootstrap_bridge.saveSetup(
                str(new_root),
                "admin@vr.com.br",
                "",
                "admin@vr.com.br",
                "",
                "120",
            )
            self.assertEqual(len(requested), 1)
            self.assertEqual(bootstrap_bridge.state, "initializing")
            self.assertFalse(bootstrap_bridge.isSetupActive)

            # The global loading page renders once setup is accepted.
            for _ in range(30):
                self.application.processEvents()
                if window.findChild(QObject, "startupLoadingPage") is not None:
                    break
                QTest.qWait(10)
            self.assertIsNotNone(window.findChild(QObject, "startupLoadingPage"))

            # Catalog pipeline still drives the bootstrap to ready.
            bootstrap_bridge._on_catalog_phase("loading_versions", 1, 3)
            self.assertEqual(bootstrap_bridge.state, "loading_versions")
            bootstrap_bridge._on_catalog_phase("ready", 1, 3)
            self.assertTrue(bootstrap_bridge.isReady)

    def test_loading_page_exists_before_backend_bootstrap(self):
        """Normal startup: QML/loading shell exists before backend work runs."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            app_dir.mkdir()
            settings = load_vr_settings(str(app_dir), str(root))
            prefs = QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
            frontend_bridge = FrontendBridge(settings, prefs)

            bootstrap_bridge = BootstrapBridge(
                settings, prefs, initial_state="initializing"
            )
            engine = create_engine(
                frontend_bridge,
                chat_bridge=None,
                studio_bridge=None,
                bootstrap_bridge=bootstrap_bridge,
            )
            self.application.processEvents()

            window = engine.rootObjects()[0]
            self.assertIsNotNone(window)
            for _ in range(30):
                self.application.processEvents()
                if window.findChild(QObject, "startupLoadingPage") is not None:
                    break
                QTest.qWait(10)
            # Loading is visible while chat/studio backends are still absent.
            self.assertIsNotNone(window.findChild(QObject, "startupLoadingPage"))

            # Panel toggles belong to the chat page only: they must not show
            # over the startup screen before the chat page is instantiated.
            sidebar_toggle = window.findChild(QObject, "conversationSidebarToggle")
            surface_toggle = window.findChild(QObject, "surfaceToggleButton")
            self.assertIsNotNone(sidebar_toggle)
            self.assertIsNotNone(surface_toggle)
            self.assertFalse(sidebar_toggle.property("visible"))
            self.assertFalse(surface_toggle.property("visible"))

    def test_schedule_antigravity_restore_without_bridge_is_noop(self):
        # First-run starts with studio_bridge=None: scheduling restore must
        # never raise AttributeError.
        schedule_antigravity_restore(None)

        calls = []

        class _FakeBridge:
            def restoreAntigravityAccount(self):
                calls.append(True)

        schedule_antigravity_restore(_FakeBridge())  # type: ignore[arg-type]
        for _ in range(50):
            self.application.processEvents()
            if calls:
                break
            QTest.qWait(10)
        self.assertEqual(calls, [True])

    def test_startup_loading_page_displays_and_transitions_to_ready(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            app_dir.mkdir()
            settings = load_vr_settings(str(app_dir), str(root))
            prefs = QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
            frontend_bridge = FrontendBridge(settings, prefs)

            bootstrap_bridge = BootstrapBridge(settings, prefs, initial_state="loading_apps")

            engine = create_engine(
                frontend_bridge,
                chat_bridge=None,
                studio_bridge=None,
                bootstrap_bridge=bootstrap_bridge,
            )
            self.application.processEvents()

            window = engine.rootObjects()[0]
            self.assertIsNotNone(window)
            self.assertFalse(bootstrap_bridge.isReady)

            # Wait for loading page to mount
            for _ in range(30):
                self.application.processEvents()
                if window.findChild(QObject, "startupLoadingPage") is not None:
                    break
                QTest.qWait(10)

            loading_page = window.findChild(QObject, "startupLoadingPage")
            self.assertIsNotNone(loading_page)

            # Transition to ready
            bootstrap_bridge.set_ready()
            self.application.processEvents()

            self.assertTrue(bootstrap_bridge.isReady)
            self.assertEqual(bootstrap_bridge.state, "ready")

    def test_startup_catalog_stage_bar_is_determinate_without_fabricated_percent(self):
        """The loading bar tracks the two real catalog stages, never a fake fraction."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            app_dir.mkdir()
            settings = load_vr_settings(str(app_dir), str(root))
            prefs = QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
            frontend_bridge = FrontendBridge(settings, prefs)

            bootstrap_bridge = BootstrapBridge(settings, prefs, initial_state="loading_apps")
            engine = create_engine(
                frontend_bridge,
                chat_bridge=None,
                studio_bridge=None,
                bootstrap_bridge=bootstrap_bridge,
            )
            self.application.processEvents()

            window = engine.rootObjects()[0]
            self.assertIsNotNone(window)
            for _ in range(30):
                self.application.processEvents()
                if window.findChild(QObject, "startupCatalogProgress") is not None:
                    break
                QTest.qWait(10)

            stage_bar = window.findChild(QObject, "startupCatalogProgress")
            self.assertIsNotNone(stage_bar)
            # First stage has no exact denominator yet: still indeterminate.
            self.assertTrue(bool(stage_bar.property("indeterminate")))
            self.assertEqual(int(stage_bar.property("to")), 2)

            bootstrap_bridge._on_catalog_phase("loading_versions", 1, 3)
            self.application.processEvents()
            self.assertFalse(bool(stage_bar.property("indeterminate")))
            self.assertEqual(int(stage_bar.property("value")), 1)

            # Ready destroys the loading page; the bridge state is authoritative.
            bootstrap_bridge._on_catalog_phase("ready", 1, 3)
            self.application.processEvents()
            self.assertTrue(bootstrap_bridge.isReady)
            self.assertEqual(bootstrap_bridge.state, "ready")

    def test_startup_loading_retry_from_error_clears_error_state_and_shows_initializing(self):
        """Simulate error -> retry -> initializing in QML shell: error state is cleared."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            app_dir.mkdir()
            settings = load_vr_settings(str(app_dir), str(root))
            prefs = QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
            frontend_bridge = FrontendBridge(settings, prefs)

            bootstrap_bridge = BootstrapBridge(settings, prefs, initial_state="error")
            bootstrap_bridge.set_error("Falha de conexão com o banco")

            engine = create_engine(
                frontend_bridge,
                chat_bridge=None,
                studio_bridge=None,
                bootstrap_bridge=bootstrap_bridge,
            )
            self.application.processEvents()

            window = engine.rootObjects()[0]
            self.assertIsNotNone(window)

            for _ in range(30):
                self.application.processEvents()
                if window.findChild(QObject, "startupLoadingPage") is not None:
                    break
                QTest.qWait(10)

            loading_page = window.findChild(QObject, "startupLoadingPage")
            self.assertIsNotNone(loading_page)
            self.assertEqual(bootstrap_bridge.state, "error")
            self.assertEqual(bootstrap_bridge.errorMessage, "Falha de conexão com o banco")
            self.assertFalse(bootstrap_bridge.isBusy)

            # Trigger transition to initializing (as done during retry)
            bootstrap_bridge.beginInitialization()
            self.application.processEvents()

            self.assertEqual(bootstrap_bridge.state, "initializing")
            self.assertEqual(bootstrap_bridge.errorMessage, "")
            self.assertTrue(bootstrap_bridge.isBusy)
            self.assertFalse(bootstrap_bridge.isReady)

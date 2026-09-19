"""Production entrypoint for the VR Norte Studio Qt Quick frontend."""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: F401 - registers QML converters
from PySide6.QtWidgets import QApplication

from ...settings import ConfigError
from ..brand import APP_ICON_PATH, APP_TITLE, ORGANIZATION_NAME, SETTINGS_APP_NAME
from ..config import load_vr_settings
from .bridge import FrontendBridge, _stored_bool
from .chat import ChatBridge
from .studio import StudioBridge
from .bootstrap import BootstrapBridge
from .startup import StartupBackendCoordinator
from ..settings_service import is_setup_needed


QML_DIR = Path(__file__).resolve().parent / "qml"
MAIN_QML = QML_DIR / "Main.qml"


def apply_ui_scale_environment(preferences: QSettings) -> None:
    """Keep startup scale handling centralized while QML applies it live.

    QT_SCALE_FACTOR enlarged the complete window geometry and made the Studio
    disproportionate to T3 Code. The saved preference is now consumed by the
    Theme singleton, so changing it updates typography without a restart.
    """
    del preferences


def install_crash_handlers(logs_dir: Path | None = None) -> None:
    """Capture unhandled Python exceptions gracefully and persist tracebacks."""

    def _handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(f"[{timestamp}] UNHANDLED EXCEPTION:\n{error_msg}", file=sys.stderr)

        if logs_dir is not None:
            try:
                logs_dir.mkdir(parents=True, exist_ok=True)
                crash_log = logs_dir / "crash.log"
                with crash_log.open("a", encoding="utf-8") as f:
                    f.write(f"=== Crash at {timestamp} ===\n{error_msg}\n\n")
            except Exception:
                pass

    sys.excepthook = _handle_exception

    def _handle_thread_exception(args: threading.ExceptHookArgs):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        _handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = _handle_thread_exception


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--vr-root", "--mary-root", dest="vr_root", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument(
        "--software-rendering",
        "--gpu-safe-mode",
        dest="software_rendering",
        action="store_true",
        help="Disable hardware GPU acceleration and use software rendering to prevent driver freezes/crashes.",
    )
    parser.add_argument(
        "--hardware-acceleration",
        "--enable-gpu",
        dest="hardware_acceleration",
        action="store_true",
        help="Enable hardware GPU acceleration.",
    )
    parser.add_argument("--screenshot", default="")
    parser.add_argument("--screenshot-page", default="Chat VR")
    parser.add_argument("--screenshot-theme", choices=("light", "dark_orange"), default="")
    parser.add_argument("--screenshot-width", type=int, default=1480)
    parser.add_argument("--screenshot-height", type=int, default=900)
    parser.add_argument("--screenshot-scale", default="")
    parser.add_argument("--screenshot-settings-tab", type=int, default=-1)
    parser.add_argument(
        "--screenshot-popup",
        choices=(
            "",
            "add-project",
            "project-folder",
            "project-selector",
            "project-settings",
            "model",
            "permission",
            "ultra-model",
        ),
        default="",
    )
    parser.add_argument(
        "--screenshot-vr-mode",
        choices=("", "off", "vr", "ultra"),
        default="",
    )
    return parser


def _apply_window_decorations(engine: QQmlApplicationEngine) -> None:
    """Enable native Windows drop shadow and Aero Snap for frameless window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        class MARGINS(ctypes.Structure):
            _fields_ = [
                ("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int),
            ]

        root_objects = engine.rootObjects()
        if root_objects and hasattr(root_objects[0], "winId"):
            hwnd = int(root_objects[0].winId())
            margins = MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
            # Request Windows 11 DWM rounded corners (DWMWCP_ROUND = 2)
            corner_pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref)
            )
    except Exception:
        pass


def create_engine(
    bridge: FrontendBridge,
    chat_bridge: ChatBridge | None = None,
    studio_bridge: StudioBridge | None = None,
    bootstrap_bridge: BootstrapBridge | None = None,
) -> QQmlApplicationEngine:
    # Single rendering policy: global follows the stored fontSmoothing so it
    # matches Theme.textRenderType from the first frame.
    try:
        smoothing = bool(getattr(bridge, "fontSmoothing", True))
    except Exception:
        smoothing = True
    QQuickWindow.setTextRenderType(
        QQuickWindow.TextRenderType.NativeTextRendering
        if smoothing
        else QQuickWindow.TextRenderType.QtTextRendering
    )
    if bootstrap_bridge is None:
        bootstrap_bridge = BootstrapBridge(settings=None, initial_state="ready")
    engine = QQmlApplicationEngine()
    qml_warnings: list[object] = []
    engine.warnings.connect(qml_warnings.extend)
    engine.addImportPath(str(QML_DIR))
    engine.rootContext().setContextProperty("frontend", bridge)
    engine.rootContext().setContextProperty("chat", chat_bridge)
    engine.rootContext().setContextProperty("studio", studio_bridge)
    engine.rootContext().setContextProperty("bootstrap", bootstrap_bridge)
    engine.load(QUrl.fromLocalFile(str(MAIN_QML)))
    engine._qml_warnings = qml_warnings  # type: ignore[attr-defined]
    _apply_window_decorations(engine)
    return engine


def schedule_antigravity_restore(studio_bridge: StudioBridge | None) -> None:
    """Schedule the Antigravity account restore only when the bridge exists.

    Never called with a not-yet-created bridge: first-run starts with
    studio_bridge=None and schedules this after setup_backend() succeeds.
    """
    if studio_bridge is None:
        return
    QTimer.singleShot(0, studio_bridge.restoreAntigravityAccount)


def _apply_application_font(app: QApplication) -> None:
    """Match the current Studio typography and stabilize headless rendering."""

    QQuickWindow.setTextRenderType(QQuickWindow.TextRenderType.NativeTextRendering)

    if sys.platform == "win32":
        for candidate in (
            Path(r"C:\Windows\Fonts\SegUIVar.ttf"),
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\seguisb.ttf"),
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\seguisym.ttf"),
        ):
            if candidate.exists():
                QFontDatabase.addApplicationFont(str(candidate))
        primary_family = "Segoe UI"
        font = QFont(primary_family)
        font.setFamilies([primary_family, "sans-serif"])
        font.setStyleStrategy(
            QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality
        )
        font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
        app.setFont(font)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    args, _unknown = build_parser().parse_known_args(raw_args)
    if args.screenshot_scale:
        os.environ["QT_SCALE_FACTOR"] = args.screenshot_scale
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    preferences = QSettings(ORGANIZATION_NAME, SETTINGS_APP_NAME)
    apply_ui_scale_environment(preferences)

    # Determine if software rendering (CPU) should be used:
    # 1. Explicit CLI / mode flags (--software-rendering, --smoke-test, --screenshot) force software.
    # 2. Environment variables (VR_STUDIO_SOFTWARE_RENDERING=1, VR_STUDIO_GPU_SAFE=1) force software.
    # 3. CLI flag --hardware-acceleration or VR_STUDIO_HARDWARE_ACCELERATION=1 forces hardware GPU.
    # 4. Saved preference appearance/hardware_acceleration (defaults to False: software rendering).
    use_software = False
    if (
        args.screenshot
        or args.smoke_test
        or args.software_rendering
        or os.environ.get("VR_STUDIO_SOFTWARE_RENDERING") == "1"
        or os.environ.get("VR_STUDIO_GPU_SAFE") == "1"
    ):
        use_software = True
    elif (
        getattr(args, "hardware_acceleration", False)
        or os.environ.get("VR_STUDIO_HARDWARE_ACCELERATION") == "1"
    ):
        use_software = False
    else:
        hw_accel = _stored_bool(
            preferences.value("appearance/hardware_acceleration", False), False
        )
        use_software = not hw_accel

    if use_software:
        # Note: Qt 6 does not accept 'software' as a QSG_RHI_BACKEND key.
        # Software rasterization is enabled via QT_QUICK_BACKEND="software".
        os.environ["QT_QUICK_BACKEND"] = "software"
        existing_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        if "--disable-gpu" not in existing_flags:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
                f"{existing_flags} --disable-gpu".strip()
            )

    # The browser surface is loaded lazily, but Qt WebEngine must register its
    # QML types before QApplication exists. Builds without WebEngine keep the
    # rest of the frontend available and show the browser fallback state.
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick

        QtWebEngineQuick.initialize()
    except ImportError:  # pragma: no cover - optional Qt module in minimal builds
        pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setOrganizationName(ORGANIZATION_NAME)
    _apply_application_font(app)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    app_dir = args.project_dir or (
        str(Path(sys.executable).resolve().parent) if getattr(sys, "frozen", False) else "."
    )
    try:
        settings = load_vr_settings(app_dir, args.vr_root)
    except ConfigError as exc:
        print(f"Configura\u00e7\u00e3o inv\u00e1lida: {exc}", file=sys.stderr)
        return 1

    install_crash_handlers(settings.logs_dir)

    # Shell-first startup: the QML engine (Setup or global loading page) must
    # exist before any configuration-dependent work runs.
    #   first run: app -> setup -> initialize -> apps -> versions -> ready -> main
    #   normal:    app -> startup loading -> initialize -> apps -> versions -> ready -> main
    bridge = FrontendBridge(
        settings,
        preferences,
        theme_override=args.screenshot_theme,
        initial_page=args.screenshot_page,
        navigation_override=False if args.screenshot else None,
    )
    needs_setup = not args.screenshot and is_setup_needed(settings, preferences)
    engine: QQmlApplicationEngine | None = None

    # Backend lifecycle (database + ChatBridge + StudioBridge) is owned by a
    # testable coordinator: atomic publishes, explicit readiness, and a real
    # first-frame gate before any heavy initialize_workspace() work runs.
    coordinator_holder: dict[str, StartupBackendCoordinator] = {}

    def schedule_restore(studio_bridge: StudioBridge | None) -> None:
        if not args.screenshot:
            schedule_antigravity_restore(studio_bridge)

    bootstrap_bridge = BootstrapBridge(
        settings,
        preferences,
        initial_state="setup" if needs_setup else "initializing",
        on_bootstrap_retry=lambda: coordinator_holder["coordinator"].bootstrap_or_retry(),
    )
    coordinator = StartupBackendCoordinator(
        settings=settings,
        bootstrap_bridge=bootstrap_bridge,
        frontend_bridge=bridge,
        preferences=preferences,
        on_backend_started=schedule_restore,
    )
    coordinator_holder["coordinator"] = coordinator
    # Single setup contract: the signal arms the deferred backend run.
    # Returning to the event loop lets the loading page paint its first
    # frame before the coordinator prepares the backend; setup/completed
    # is persisted by setupInitializationSucceeded, never here.
    bootstrap_bridge.setupInitializationRequested.connect(
        coordinator.request_setup_backend
    )

    shutdown_complete = False

    def shutdown() -> None:
        nonlocal shutdown_complete
        if shutdown_complete:
            return
        shutdown_complete = True
        coordinator.shutdown()
        if coordinator.studio_bridge is not None:
            coordinator.studio_bridge.close()
        if coordinator.chat_bridge is not None:
            coordinator.chat_bridge.close()

    app.aboutToQuit.connect(shutdown)
    engine = create_engine(bridge, None, None, bootstrap_bridge)
    coordinator.set_engine(engine)

    if not engine.rootObjects():
        for warning in getattr(engine, "_qml_warnings", []):
            print(warning.toString(), file=sys.stderr)
        print(f"Não foi possível carregar o frontend QML: {MAIN_QML}", file=sys.stderr)
        shutdown()
        return 1

    window = engine.rootObjects()[0]
    coordinator.set_window(window)
    # Compact bootstrap envelope: setup/loading/error share one small
    # centered window; the normal geometry is restored on ready. The
    # controller writes nothing to QSettings, so the compact size never
    # becomes the user's saved preference.
    from .bootstrap_geometry import BootstrapGeometryController

    geometry_controller = BootstrapGeometryController(window, bootstrap_bridge)
    engine._bootstrap_geometry = geometry_controller  # type: ignore[attr-defined]
    if args.screenshot:
        # Deterministic capture path: backend synchronously, then ready.
        coordinator.setup_backend(settings)
        if args.screenshot_vr_mode:
            coordinator.chat_bridge._vr_mode = args.screenshot_vr_mode
        bootstrap_bridge.set_ready()
        window.setProperty("width", max(1120, args.screenshot_width))
        window.setProperty("height", max(700, args.screenshot_height))

        popup_targets = {
            "add-project": "addProjectButton",
            "model": "chatModelPicker",
            "permission": "chatPermissionPicker",
            "ultra-model": "vrUltraAgentModelPicker",
        }

        def open_capture_popup() -> None:
            if args.screenshot_settings_tab >= 0:
                settings_page = window.findChild(QObject, "settingsPage")
                if settings_page is not None:
                    settings_page.setProperty("tabIndex", args.screenshot_settings_tab)
            if args.screenshot_popup == "project-folder":
                add_button = window.findChild(QObject, "addProjectButton")
                chat_page = window.findChild(QObject, "chatPage")
                if add_button is not None and hasattr(add_button, "click"):
                    add_button.click()
                if chat_page is not None and hasattr(chat_page, "openLocalFolderBrowser"):
                    chat_page.openLocalFolderBrowser()
                return
            if args.screenshot_popup == "project-selector":
                chat_page = window.findChild(QObject, "chatPage")
                if chat_page is not None and hasattr(
                    chat_page, "openProjectSelectorMenu"
                ):
                    chat_page.openProjectSelectorMenu()
                return
            if args.screenshot_popup == "project-settings":
                chat_page = window.findChild(QObject, "chatPage")
                project_index = next(
                    (
                        index
                        for index, item in enumerate(
                            coordinator.chat_bridge.projectItems
                        )
                        if item.get("path")
                    ),
                    -1,
                )
                if (
                    chat_page is not None
                    and project_index > 0
                    and hasattr(chat_page, "openProjectSettings")
                ):
                    chat_page.openProjectSettings(project_index)
                return
            object_name = popup_targets.get(args.screenshot_popup, "")
            if not object_name:
                return
            target = window.findChild(QObject, object_name)
            if target is not None and hasattr(target, "click"):
                target.click()

        def save_capture() -> None:
            target = Path(args.screenshot).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            # QQuickWindow renders into its own scene graph.  Capturing that
            # buffer avoids Windows returning pixels from an overlapping app.
            content_item = window.property("contentItem")
            quick_window = content_item.window() if content_item is not None else None
            capture = quick_window.grabWindow() if quick_window is not None else None
            if capture is None or capture.isNull() or not capture.save(str(target), "PNG"):
                app.exit(2)
                return
            app.quit()

        QTimer.singleShot(650, open_capture_popup)
        QTimer.singleShot(1300, save_capture)
    elif args.smoke_test:
        QTimer.singleShot(600, app.quit)
    elif not needs_setup:
        # Normal startup: the engine/loading shell is already visible; the
        # heavy backend starts only after the first real frameSwapped frame,
        # so the loading page paints (and keeps animating) first.
        coordinator.request_normal_startup()
    # First run stays on the Setup page until the user saves the configuration.

    # Keep Python-owned QObjects alive for the entire QML engine lifetime.
    engine._frontend_bridge = bridge  # type: ignore[attr-defined]
    engine._coordinator = coordinator  # type: ignore[attr-defined]
    engine._chat_bridge = coordinator.chat_bridge  # type: ignore[attr-defined]
    engine._studio_bridge = coordinator.studio_bridge  # type: ignore[attr-defined]
    try:
        return app.exec()
    finally:
        shutdown()
        del engine
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(main())

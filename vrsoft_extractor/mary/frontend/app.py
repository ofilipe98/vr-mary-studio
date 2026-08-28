"""Production entrypoint for the VR Norte Studio Qt Quick frontend."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: F401 - registers QML converters
from PySide6.QtWidgets import QApplication

from ...settings import ConfigError
from ..brand import APP_ICON_PATH, APP_TITLE, ORGANIZATION_NAME, SETTINGS_APP_NAME
from ..config import load_vr_settings
from ..workspace import initialize_workspace
from .bridge import FrontendBridge, normalized_ui_scale
from .chat import ChatBridge
from .studio import StudioBridge


QML_DIR = Path(__file__).resolve().parent / "qml"
MAIN_QML = QML_DIR / "Main.qml"


def apply_ui_scale_environment(preferences: QSettings) -> None:
    """Apply the saved interface scale before the QGuiApplication exists.

    QHD and 4K monitors often run at 100% system scaling, where the default
    density feels small. The preference multiplies the whole render through
    QT_SCALE_FACTOR and must be set before Qt reads the environment.
    """
    scale = normalized_ui_scale(str(preferences.value("appearance/ui_scale", "") or ""))
    if scale == "100":
        return
    if "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{int(scale) / 100:.2f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--vr-root", "--mary-root", dest="vr_root", default=None)
    parser.add_argument("--smoke-test", action="store_true")
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


def create_engine(
    bridge: FrontendBridge,
    chat_bridge: ChatBridge,
    studio_bridge: StudioBridge | None = None,
) -> QQmlApplicationEngine:
    engine = QQmlApplicationEngine()
    qml_warnings: list[object] = []
    engine.warnings.connect(qml_warnings.extend)
    engine.addImportPath(str(QML_DIR))
    engine.rootContext().setContextProperty("frontend", bridge)
    engine.rootContext().setContextProperty("chat", chat_bridge)
    engine.rootContext().setContextProperty("studio", studio_bridge)
    engine.load(QUrl.fromLocalFile(str(MAIN_QML)))
    engine._qml_warnings = qml_warnings  # type: ignore[attr-defined]
    return engine


def _apply_application_font(app: QApplication) -> None:
    """Match the current Studio typography and stabilize headless rendering."""

    if sys.platform == "win32":
        for candidate in (
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\seguisym.ttf"),
        ):
            if candidate.exists():
                QFontDatabase.addApplicationFont(str(candidate))
        app.setFont(QFont("Segoe UI"))


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    args, _unknown = build_parser().parse_known_args(raw_args)
    if args.screenshot_scale:
        os.environ["QT_SCALE_FACTOR"] = args.screenshot_scale
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    if args.screenshot or args.smoke_test:
        os.environ.setdefault("QSG_RHI_BACKEND", "software")

    # The browser surface is loaded lazily, but Qt WebEngine must register its
    # QML types before QApplication exists. Builds without WebEngine keep the
    # rest of the frontend available and show the browser fallback state.
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick

        QtWebEngineQuick.initialize()
    except ImportError:  # pragma: no cover - optional Qt module in minimal builds
        pass

    preferences = QSettings(ORGANIZATION_NAME, SETTINGS_APP_NAME)
    apply_ui_scale_environment(preferences)

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
        print(f"Configuração inválida: {exc}", file=sys.stderr)
        return 1

    bridge = FrontendBridge(
        settings,
        preferences,
        theme_override=args.screenshot_theme,
        initial_page=args.screenshot_page,
        navigation_override=False if args.screenshot else None,
    )
    database = initialize_workspace(settings)
    chat_bridge = ChatBridge(settings, database, preferences)
    if args.screenshot_vr_mode:
        # Visual-test override only; do not persist or mutate a conversation.
        chat_bridge._vr_mode = args.screenshot_vr_mode
    studio_bridge = StudioBridge(
        settings,
        database,
        preferences,
        chat_orchestrator=chat_bridge._orchestrator,
    )
    studio_bridge.conversationRestored.connect(chat_bridge.refresh)
    chat_bridge.conversationArchived.connect(
        lambda _conversation_id: studio_bridge.refreshArchived("")
    )
    shutdown_complete = False

    def shutdown() -> None:
        nonlocal shutdown_complete
        if shutdown_complete:
            return
        shutdown_complete = True
        studio_bridge.close()
        chat_bridge.close()

    app.aboutToQuit.connect(shutdown)
    engine = create_engine(bridge, chat_bridge, studio_bridge)
    if not engine.rootObjects():
        for warning in getattr(engine, "_qml_warnings", []):
            print(warning.toString(), file=sys.stderr)
        print(f"Não foi possível carregar o frontend QML: {MAIN_QML}", file=sys.stderr)
        shutdown()
        return 1

    window = engine.rootObjects()[0]
    if args.screenshot:
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
                        for index, item in enumerate(chat_bridge.projectItems)
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

    # Keep Python-owned QObjects alive for the entire QML engine lifetime.
    engine._frontend_bridge = bridge  # type: ignore[attr-defined]
    engine._chat_bridge = chat_bridge  # type: ignore[attr-defined]
    engine._studio_bridge = studio_bridge  # type: ignore[attr-defined]
    try:
        return app.exec()
    finally:
        shutdown()


if __name__ == "__main__":
    raise SystemExit(main())

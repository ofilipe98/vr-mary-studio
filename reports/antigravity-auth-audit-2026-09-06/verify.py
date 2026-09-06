"""Safe live validation and offscreen QML evidence for the OAuth audit."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QSG_RHI_BACKEND"] = "software"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
import json
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings, QObject
from PySide6.QtTest import QTest
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.antigravity import AntigravityProvider
from vrsoft_extractor.mary.antigravity_auth import LoginAttempt
from vrsoft_extractor.mary.frontend.app import create_engine, _apply_application_font
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge

out = Path(__file__).resolve().parent
app = QApplication([])
_apply_application_font(app)
with TemporaryDirectory() as tmp:
    root = Path(tmp)
    settings = MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy")
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    prefs = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
    frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Configurações")
    chat = ChatBridge(settings, db, prefs)
    studio = StudioBridge(settings, db, prefs)
    studio.refreshProviders()
    if "--live" in sys.argv:
        studio.validateAntigravityAccount()
        for _ in range(1000):
            QTest.qWait(100)
            if not studio._agy_check_running:
                break
        result = {"account": studio._antigravity_auth.account_state, "validation_finished": not studio._agy_check_running}
        print(json.dumps(result), flush=True)
        provider = AntigravityProvider()
        models = provider.list_models()
        result["model_count_excluding_fallback"] = len(models) - 1
        # Only send a turn after the saved account was verified.
        if result["account"] == "authenticated":
            done = threading.Event()
            events = []
            def receive(event):
                events.append(event)
                if event.kind == "turn_completed":
                    done.set()
            provider.send_message("audit", "", "default", "auto", root,
                                  "Reply only OK. Do not use tools or read files.", receive)
            done.wait(90)
            result["turn_completed"] = done.is_set()
            result["native_session"] = any(e.kind == "native_session_started" for e in events)
            result["nonempty_response"] = any(e.kind == "assistant_delta" and e.text.strip() for e in events)
            result["error_events"] = sum(e.kind == "error" for e in events)
        provider.close()
        (out / "live-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    else:
        engine = create_engine(frontend, chat, studio)
        window = engine.rootObjects()[0]
        window.resize(1200, 900)
        window.show()
        QTest.qWait(300)
        window.findChild(QObject, "settingsPage").setProperty("tabIndex", 1)
        QTest.qWait(200)
        for theme in ("dark_orange", "light"):
            frontend.setTheme(theme)
            studio._antigravity_auth._active_attempt = LoginAttempt("render", state="waiting")
            studio._antigravity_auth._account_state = "unknown"
            studio._antigravity_auth._account_status_label = "Conclua o login no terminal do Antigravity e clique em Validar conta."
            studio.refreshProviders()
            QTest.qWait(200)
            window.grabWindow().save(str(out / (theme + "-waiting.png")))
            studio._antigravity_auth.mark_authenticated_from_validation()
            studio._antigravity_auth.mark_session_or_model_error("test")
            QTest.qWait(200)
            window.grabWindow().save(str(out / (theme + "-session-error.png")))
        window.resize(1000, 750)
        studio.setProviderDisplayName("antigravity", "Antigravity com nome longo para verificar a leitura e as ações")
        QTest.qWait(200)
        window.grabWindow().save(str(out / "narrow-long-name.png"))
        warnings = [x.toString() for x in engine._qml_warnings]
        (out / "qml-warnings.json").write_text(json.dumps(warnings, indent=2), encoding="utf-8")
        print("QML warnings:", len(warnings), flush=True)
        window.close()
    studio.close()
    chat.close()

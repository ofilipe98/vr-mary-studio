"""Render tool cards in an isolated offline UI across themes and scales."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine, _apply_application_font
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.provider_adapters.tool_normalizer import normalize_opencode_event
from vrsoft_extractor.mary.tool_activity import ToolLifecycleReducer
from vrsoft_extractor.mary.tool_presentation import DEFAULT_PRESENTATION_REGISTRY


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else ".test-tmp/tool-cards-review")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)
    if sys.platform == "win32":
        for font in ("consola.ttf", "consolab.ttf"):
            QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / font))
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = MarySettings(app_dir=root, root=root / "data", old_root=root / "old")
        prefs = QSettings(str(root / "prefs.ini"), QSettings.IniFormat)
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
        chat, studio = ChatBridge(settings, db, prefs), StudioBridge(settings, db, prefs)
        engine = create_engine(frontend, chat, studio)
        window = QQuickWindow()
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
            "vrsoft_extractor/mary/frontend/qml/components/VrToolCard.qml")))
        assert not component.isError(), component.errors()
        card = component.create()
        card.setParentItem(window.contentItem())
        card.setX(16)
        card.setY(16)
        event = normalize_opencode_event({"type": "tool_use", "part": {
            "tool": "vr-mary-studio_vr_read", "callID": "visual", "state": {
                "status": "error", "input": {"reference": "vratacarejo.service.notasaida.NotaSaidaFiscalService", "start_line": 340, "end_line": 400},
                "error": "O saldo de respostas deste turno não comporta outra página. Use as evidências já recebidas ou continue em um novo turno.",
                "time": {"start": 1000, "end": 38361}}}})
        card.setProperty("modelData", DEFAULT_PRESENTATION_REGISTRY.format(ToolLifecycleReducer().reduce(event)).to_dict())
        for theme, scale, width in [("dark_orange", "100", 900), ("light", "100", 900),
                                    ("dark_orange", "100", 380), ("light", "150", 560)]:
            frontend.setTheme(theme)
            frontend.setUiScale(scale)
            window.setColor(QColor("#17232c" if theme == "dark_orange" else "#fafafa"))
            window.setWidth(width)
            window.setHeight(600)
            card.setWidth(width - 32)
            window.show()
            for expanded in (False, True):
                card.setProperty("detailExpanded", expanded)
                QTest.qWait(200)
                assert window.grabWindow().save(str(output / f"{theme}-{scale}-{width}-{expanded}.png"))
        window.close()
        card.deleteLater()
        chat.close()
        studio.close()
        app.processEvents()


if __name__ == "__main__":
    main()

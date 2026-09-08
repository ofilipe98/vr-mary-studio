"""Render the actual QML chat with an isolated, offline conversation fixture."""
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QSG_RHI_BACKEND", "software")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.app import create_engine, _apply_application_font
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.models import RuntimeEvent


def find_items(item, name):
    result = [item] if item.objectName() == name else []
    for child in item.childItems():
        result.extend(find_items(child, name))
    return result


def repaint_icons(item):
    # Canvas textures can otherwise stay stale after an offscreen resize.
    if hasattr(item, "requestPaint"):
        item.requestPaint()
    for child in item.childItems():
        repaint_icons(child)


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else ".test-tmp/visual-review")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)
    if sys.platform == "win32":
        from PySide6.QtGui import QFontDatabase
        for font_file in ("consola.ttf", "consolab.ttf"):
            QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / font_file))
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy")
        prefs = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        cid = db.create_conversation("Função 113 · Consulta de documentação", "codex", "gpt-5.6", settings.root)
        db.add_message(cid, "user", "Função 113 no PDV: o que faz?")
        markdown = """## Consulta da função no PDV

Este é um **exemplo visual**, com conteúdo de demonstração para revisar a interface. A consulta relaciona documentação, contexto do projeto e evidências disponíveis.

### Como investigar

1. Localize a função no **mapa de funções** da versão instalada.
2. Confira as permissões e o parâmetro `codigo_funcao`.
3. Compare o resultado com o cenário informado.

> Confirme a versão do ERP antes de aplicar uma orientação operacional.

| Verificação | Origem | Situação |
| --- | --- | --- |
| Mapa de funções | Documentação | Disponível |
| Permissões | Projeto local | Conferir |

```sql
SELECT codigo, descricao
FROM funcoes
WHERE codigo = 113;
```

Consulte também a [documentação do projeto](https://example.com/docs) para complementar a análise.

Fontes consultadas:
- [MAPA DE FUNÇÕES](https://example.com/funcoes)
- [Manual do PDV · permissões de operação](https://example.com/pdv)
- [Configuração do terminal](https://example.com/terminal)
- [Histórico de versões](https://example.com/versoes)
- [Diagnóstico de integração](https://example.com/integracao)
- [Base de conhecimento](https://example.com/base)
"""
        db.add_message(cid, "assistant", markdown)
        for event in [RuntimeEvent(cid, "turn_started", "Execução iniciada"),
                      RuntimeEvent(cid, "turn_completed", "Pronto")]:
            db.add_event(event)
        frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Chat VR")
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            if not engine.rootObjects():
                raise RuntimeError([w.toString() for w in engine._qml_warnings])
            window = engine.rootObjects()[0]
            window.setPosition(0, 0)
            for width, height in [(1366, 768), (1920, 1080), (390, 844), (768, 1024)]:
                # Deterministic captures; interaction tests exercise motion enabled.
                frontend.setReduceMotion(True)
                window.setWidth(width)
                window.setHeight(height)
                QTest.qWait(500)
                assert (window.width(), window.height()) == (width, height)
                timeline = window.findChild(QObject, "messageList")
                timeline.setProperty("followTail", False)
                timeline.setProperty("contentY", 0)
                repaint_icons(window.contentItem())
                QTest.qWait(150)
                window.grabWindow().save(str(output / f"chat-{width}x{height}.png"))
                timeline.positionViewAtEnd()
                QTest.qWait(150)
                window.grabWindow().save(str(output / f"sources-{width}x{height}.png"))
            frontend.setTheme("light")
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(300)
            window.grabWindow().save(str(output / "chat-light.png"))
            frontend.setTheme("dark_orange")
            timeline.setProperty("followTail", False)
            timeline.setProperty("contentY", 0)
            activity = find_items(window.contentItem(), "chatActivity")[0]
            activity.setProperty("elapsedLabel", "13s")
            activity.setProperty("items", [
                {"text": "Analisou a solicitação", "state": "success", "kind": "status", "detail": "Contexto da pergunta identificado."},
                {"text": "Consultou documentação", "state": "success", "kind": "status", "detail": "Documentação de demonstração."},
                {"text": "Validou fontes", "state": "success", "kind": "status"},
                {"text": "Preparou resposta", "state": "success", "kind": "status"},
            ])
            for state, running, expanded in [("Pronto", False, True), ("Consultando documentação…", True, False), ("Erro", False, False), ("Interrompido", False, False)]:
                activity.setProperty("statusText", state)
                activity.setProperty("running", running)
                activity.setProperty("expanded", expanded)
                QTest.qWait(150)
                name = "working" if running else "expanded" if expanded else "error" if state == "Erro" else "cancelled"
                window.grabWindow().save(str(output / f"activity-{name}.png"))
            chat.startNewChat()
            QTest.qWait(150)
            window.grabWindow().save(str(output / "chat-empty.png"))
            errors = [w.toString() for w in engine._qml_warnings]
            (output / "qml-warnings.txt").write_text("\n".join(errors), encoding="utf-8")
            print("QML warnings:", len(errors))
            print("Evidence:", output.resolve())
            window.close()
        studio.close()
        chat.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

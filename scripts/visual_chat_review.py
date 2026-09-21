"""Render the actual QML chat with an isolated, offline conversation fixture."""
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, QSettings, QObject
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


def reveal_in_flickable(flickable, item, top_margin=24):
    """Scroll an already-instantiated delegate into the visible viewport."""
    mapped = item.mapToItem(flickable, QPointF(0, 0))
    current_y = float(flickable.property("contentY") or 0)
    flickable.setProperty("contentY", max(0, current_y + mapped.y() - top_margin))


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

O fluxo fica em `mary/frontend/file_links.py:12` e o método `calcularImpostoItem` permanece inline code.

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
            captures = []
            toolcalling_items = [
                {
                    "id": "tool-call-command",
                    "kind": "tool",
                    "itemType": "commandExecution",
                    "state": "running",
                    "text": "Executando testes do contrato ACP",
                    "command": "python -m pytest tests/test_antigravity_acp.py",
                    "durationLabel": "2.1s",
                },
                {
                    "id": "tool-call-reference",
                    "kind": "tool",
                    "itemType": "fileRead",
                    "state": "completed",
                    "text": "Leu a implementação de referência do ACP",
                    "subtitle": "AcpRuntimeModel.ts",
                },
                {
                    "id": "tool-call-normalizer",
                    "kind": "file_changes",
                    "itemType": "fileChange",
                    "state": "completed",
                    "text": "Atualizou a normalização do toolCallId",
                    "files": [
                        {
                            "path": "vrsoft_extractor/mary/provider_adapters/tool_normalizer.py",
                            "name": "tool_normalizer.py",
                        },
                        {
                            "path": "tests/test_provider_adapters_normalization.py",
                            "name": "test_provider_adapters_normalization.py",
                        },
                    ],
                    "fileCount": 2,
                    "additions": 24,
                    "deletions": 6,
                    "folderSummary": "vrsoft_extractor/mary · tests",
                },
                {
                    "id": "tool-call-lifecycle",
                    "kind": "tool",
                    "itemType": "mcpToolCall",
                    "state": "running",
                    "text": "Validando o lifecycle terminal",
                    "subtitle": "Antigravity ACP",
                },
            ]
            card_names = ("toolCard", "commandCard", "toolGroupCard", "changedFilesCard")

            activity.setProperty("items", toolcalling_items)
            activity.setProperty("statusText", "Executando uma ação…")
            activity.setProperty("running", True)
            activity.setProperty("expanded", False)
            QTest.qWait(200)
            reveal_in_flickable(timeline, activity)
            QTest.qWait(100)
            live_cards = sum(len(find_items(activity, name)) for name in card_names)
            live_titles = [
                str(card.property("titleText") or card.property("commandText") or "")
                for name in card_names
                for card in find_items(activity, name)
            ]
            live_capture = "activity-toolcalling-live.png"
            window.grabWindow().save(str(output / live_capture))
            captures.append(live_capture)

            settled_items = [dict(item, state="completed") for item in toolcalling_items]
            activity.setProperty("items", settled_items)
            activity.setProperty("statusText", "Concluído")
            activity.setProperty("running", False)
            activity.setProperty("expanded", False)
            QTest.qWait(200)
            reveal_in_flickable(timeline, activity)
            QTest.qWait(100)
            settled_cards = sum(len(find_items(activity, name)) for name in card_names)
            settled_header = str(activity.property("headerLabel") or "")
            settled_capture = "activity-toolcalling-settled.png"
            window.grabWindow().save(str(output / settled_capture))
            captures.append(settled_capture)

            activity.setProperty("expanded", True)
            QTest.qWait(200)
            reveal_in_flickable(timeline, activity)
            QTest.qWait(100)
            expanded_cards = sum(len(find_items(activity, name)) for name in card_names)
            expanded_capture = "activity-toolcalling-settled-expanded.png"
            window.grabWindow().save(str(output / expanded_capture))
            captures.append(expanded_capture)

            anonymous_titles = [title for title in live_titles if "anon:exec:noid:" in title]
            settled_disclosure_only = settled_cards == 0 and settled_header == "Concluído em 13s"
            if live_cards != len(toolcalling_items):
                raise RuntimeError(f"Live tool trace rendered {live_cards} of {len(toolcalling_items)} cards")
            if not settled_disclosure_only:
                raise RuntimeError(
                    f"Settled tool trace must contain only its disclosure; "
                    f"header={settled_header!r}, cards={settled_cards}"
                )
            if expanded_cards != len(toolcalling_items):
                raise RuntimeError(
                    f"Expanded settled trace rendered {expanded_cards} of {len(toolcalling_items)} cards"
                )
            if anonymous_titles:
                raise RuntimeError(f"Anonymous tool titles rendered: {anonymous_titles}")

            # Exercise the reference's two central output shapes: comparative
            # tables and a long, copyable plain-text implementation prompt.
            reference_markdown = """Recomendo separar **VR Ultra** e **Aplicativos e versões**, deixando o processamento de código dentro de cada versão.

Este conteúdo é uma demonstração visual; não representa uma análise do catálogo real.

| Área | Responsabilidade |
| --- | --- |
| **VR Ultra** | Agentes, modelos e preferências de análise. |
| **Aplicativos e versões** | Importação de pacotes, histórico por aplicativo e consulta do código. |
| **Processamento** | Acompanhar andamento, consultar erros e reprocessar uma versão. |

O aplicativo é a identidade principal; o pacote registra **de onde ele veio**.

| Pacote importado | Aplicativo | Versão |
| --- | --- | --- |
| Pacote A | VRPdv | 4.5.0 |
| Pacote A | VRGestao | 4.6.0 |
| Pacote B | VRPdv | 4.5.0 |
| Pacote B | VRGestao | 4.6.1 |

Algumas particularidades:

- **Mesma versão, conteúdo diferente:** comparar o hash e preservar variantes.
- **Mesmo conteúdo em pacotes diferentes:** reutilizar o processamento e manter as origens.
- **Versão não identificada:** apresentar o dado como desconhecido.
- **Contexto da análise:** selecionar aplicativo e versão explicitamente.

Segue o prompt de implementação:

````text
Implemente a organização do catálogo por aplicativo e versão.

OBJETIVO
Um pacote pode conter vários aplicativos e repetir versões já importadas.
A importação deve preservar as origens e reutilizar o conteúdo idêntico.

ANTES DE EDITAR
1. Leia AGENTS.md e docs/DEVELOPMENT.md.
2. Inspecione o estado do Git e preserve alterações locais.
3. Rastreie importação, persistência, processamento e consulta de código.

INTERFACE
Aplicativos → Aplicativo → Versões → Versão → Detalhes / Código / Origens.

EXEMPLO DE DOCUMENTAÇÃO A PRESERVAR
```markdown
| Aplicativo | Versão |
| --- | --- |
| VRPdv | 4.5.0 |
```

VERIFICAÇÃO
Confirme importação repetida, versões desconhecidas e conteúdo diferente.
Valide janelas amplas e estreitas, tema claro e escuro e escala de 150%.
Entregue o resultado e as evidências de validação.
````
"""
            activity.setProperty("expanded", False)
            activity.setProperty("statusText", "Pronto")
            chat.messages.update_last(content=reference_markdown, displayContent=reference_markdown)
            # P3 density matrix: standard + narrow widths, both themes and the
            # full 100/125/150 scale range. Filenames sort alphabetically so a
            # reviewer can compare scale steps side by side (or against T3
            # Code captures taken at the same sizes).
            matrix = []
            for theme, width, height, scale in [
                (theme, width, height, scale)
                for theme in ("dark_orange", "light")
                for width, height in ((1366, 900), (390, 844))
                for scale in ("100", "125", "150")
            ]:
                frontend.setTheme(theme)
                frontend.setUiScale(scale)
                window.setWidth(width)
                window.setHeight(height)
                QTest.qWait(250)
                timeline.setProperty("contentY", 0)
                QTest.qWait(100)
                prefix = f"output-{theme}-{width}-{scale}"
                window.grabWindow().save(str(output / f"{prefix}-tables.png"))
                captures.append(f"{prefix}-tables.png")
                table = find_items(window.contentItem(), "tableBlock")[0]
                table.setProperty("expanded", True)
                QTest.qWait(100)
                window.grabWindow().save(str(output / f"{prefix}-expanded.png"))
                captures.append(f"{prefix}-expanded.png")
                table.setProperty("expanded", False)
                timeline.positionViewAtEnd()
                QTest.qWait(150)
                window.grabWindow().save(str(output / f"{prefix}-code.png"))
                captures.append(f"{prefix}-code.png")
                matrix.append({"theme": theme, "width": width, "height": height, "scale": scale})
            frontend.setUiScale("100")
            chat.startNewChat()
            QTest.qWait(150)
            window.grabWindow().save(str(output / "chat-empty.png"))
            errors = [w.toString() for w in engine._qml_warnings]
            (output / "qml-warnings.txt").write_text("\n".join(errors), encoding="utf-8")
            import json
            (output / "results.json").write_text(json.dumps({
                "captures": captures,
                "density_matrix": matrix,
                "activity_toolcalling": {
                    "live_visible_cards": live_cards,
                    "settled_visible_cards": settled_cards,
                    "settled_expanded_visible_cards": expanded_cards,
                    "settled_disclosure_only": settled_disclosure_only,
                    "anonymous_title_count": len(anonymous_titles),
                },
                "qml_warnings": len(errors),
            }, indent=2), encoding="utf-8")
            print("Tool-calling live visible cards:", live_cards)
            print("Tool-calling settled visible cards:", settled_cards)
            print("Tool-calling settled expanded visible cards:", expanded_cards)
            print("Tool-calling settled disclosure only:", settled_disclosure_only)
            print("Tool-calling anon:exec:noid titles:", len(anonymous_titles))
            print("QML warnings:", len(errors))
            print("Evidence:", output.resolve())
            window.close()
        studio.close()
        chat.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

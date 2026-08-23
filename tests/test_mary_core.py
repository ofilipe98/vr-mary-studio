import json
import io
import os
import queue
import sqlite3
import sys
import threading
import unittest
import urllib.parse
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from vrsoft_extractor.mary.classifier import classify, parse_product_catalog
from vrsoft_extractor.mary.chat_tools import (
    MAX_TOOL_OUTPUT_BYTES,
    ToolExecutionError,
    ToolValidationError,
    mcp_thread_config,
    run_local_tool,
    validate_tool_definition,
)
from vrsoft_extractor.mary.chat_widgets import (
    CodeBlockWidget,
    MarkdownMessageWidget,
    ModelPickerCombo,
    ProjectPickerDialog,
    RoundedPopupDialog,
    SpellcheckPlainTextEdit,
    provider_icon,
)
from vrsoft_extractor.mary.classification_audit import audit_classification
from vrsoft_extractor.mary.config import MarySettings, save_vr_env
from vrsoft_extractor.mary.content import (
    canonical_markdown,
    download_asset,
    html_to_markdown,
    preserve_validated_classification,
    sha256_text,
    write_and_persist_document,
    write_document,
)
from vrsoft_extractor.mary.db import MaryDatabase, _fts_query
from vrsoft_extractor.mary.migration import build_manifest, migrate
from vrsoft_extractor.mary.models import (
    APPROVAL_PRESETS,
    ConversationOptions,
    KnowledgeDocument,
    ReviewFilters,
    RuntimeEvent,
    SyncStats,
)
from vrsoft_extractor.mary.movidesk import (
    MovideskInteractiveLoginRequired,
    MovideskSync,
)
from vrsoft_extractor.mary.providers import (
    CodexProvider,
    ProviderError,
    _resolve_codex_command,
    normalize_effort,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.ocr import (
    _download_file,
    latest_github_installer_url,
    latest_windows_installer_url,
)
from vrsoft_extractor.mary.spellcheck import LocalSpellChecker
from vrsoft_extractor.mary.search import search_terms
from vrsoft_extractor.mary.workspace import initialize_workspace
from vrsoft_extractor.mary.wiki import WikiSync

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from vrsoft_extractor.mary.ui import (
    ACCESSIBLE_ORANGE,
    BACKGROUND,
    BRAND_NAVY,
    CONVERSATION_RUNNING_ROLE,
    DISABLED_BACKGROUND,
    DISABLED_TEXT,
    FOCUS_DARK,
    LINK_VISITED,
    MainWindow,
    SCROLLBAR_HANDLE,
    SCROLLBAR_TRACK,
    STATUS_GOOD,
    STATUS_WARN,
    TEXT_MUTED,
    apply_application_theme,
    open_safe_external_url,
)


class MaryCoreTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(".test-tmp") / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.app = self.root / "app"
        self.old = self.root / "old"
        self.app.mkdir(parents=True, exist_ok=True)
        self.old.mkdir(parents=True, exist_ok=True)
        self.settings = MarySettings(
            app_dir=self.app.resolve(),
            root=(self.root / "mary").resolve(),
            old_root=self.old.resolve(),
        )

    def test_save_vr_env_is_validated_atomic_and_preserves_unknown_values(self):
        env_path = self.app / ".env"
        env_path.write_text(
            "# configuração local\nCUSTOM_FLAG=keep\nVR_ROOT=old\n",
            encoding="utf-8",
        )
        save_vr_env(
            self.app,
            {
                "VR_ROOT": str(self.settings.root),
                "MOVIDESK_EMAIL": "user@example.com",
                "MOVIDESK_PASSWORD": "secret",
                "ENDOO_EMAIL": "video@example.com",
                "ENDOO_PASSWORD": "video-secret",
                "VR_SYNC_INTERVAL_MINUTES": "30",
                "VR_DEFAULT_EFFORT": "high",
            },
        )

        content = env_path.read_text(encoding="utf-8")
        self.assertIn("# configuração local", content)
        self.assertIn("CUSTOM_FLAG=keep", content)
        self.assertEqual(content.count("VR_ROOT="), 1)
        self.assertIn("VR_SYNC_INTERVAL_MINUTES=30", content)
        self.assertEqual(list(self.app.glob(".*.tmp")), [])

    def test_save_vr_env_rejects_invalid_values_without_changing_file(self):
        env_path = self.app / ".env"
        env_path.write_text("CUSTOM_FLAG=keep\n", encoding="utf-8")
        invalid = {
            "VR_ROOT": str(self.settings.root),
            "VR_SYNC_INTERVAL_MINUTES": "0",
            "VR_DEFAULT_EFFORT": "medium",
        }

        with self.assertRaisesRegex(RuntimeError, "pelo menos 15"):
            save_vr_env(self.app, invalid)

        self.assertEqual(env_path.read_text(encoding="utf-8"), "CUSTOM_FLAG=keep\n")

    def test_download_asset_rejects_empty_and_oversized_responses(self):
        destination = self.root / "assets"
        with self.assertRaisesRegex(ValueError, "vazio"):
            download_asset(
                "https://example.com/empty.png",
                destination,
                opener=lambda _url: b"",
            )
        with self.assertRaisesRegex(ValueError, "insegura"):
            download_asset("file:///C:/segredo.txt", destination)
        with patch("vrsoft_extractor.mary.content.MAX_ASSET_BYTES", 3):
            with self.assertRaisesRegex(ValueError, "excede o limite"):
                download_asset(
                    "https://example.com/large.png",
                    destination,
                    opener=lambda _url: b"1234",
                )
        self.assertFalse(destination.exists())

    def _queue_review(
        self,
        database: MaryDatabase,
        source_id: str,
        *,
        source: str = "wiki",
        current_module: str = "Revisar",
        suggested_module: str = "PDV",
        confidence: float = 0.5,
        product: str = "",
        category: str = "",
        reasons: list[str] | None = None,
        validated_change: bool = False,
    ) -> int:
        document = KnowledgeDocument(
            source=source,
            source_id=source_id,
            title=f"Documento {source_id}",
            url=f"https://example.com/{source}/{source_id}",
            markdown=f"Conteúdo pesquisável {source_id}",
            module=current_module,
            classification_confidence=confidence,
            review_status="pending",
            revision="1",
            content_hash=f"hash-{source_id}",
            product=product,
            category=category,
            local_path=f"{source_id}.md",
        )
        document_id, _ = database.upsert_document(document)
        database.queue_review(
            document_id,
            suggested_module,
            confidence,
            reasons if reasons is not None else ["evidência"],
            current_module,
            validated_change,
        )
        review = database.query_reviews(
            ReviewFilters(query=source_id, limit=10)
        ).items[0]
        return int(review["id"])

    @staticmethod
    def _contrast_ratio(foreground: str, background: str) -> float:
        def luminance(value: str) -> float:
            channels = [
                int(value[index : index + 2], 16) / 255
                for index in (1, 3, 5)
            ]
            linear = [
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return (
                0.2126 * linear[0]
                + 0.7152 * linear[1]
                + 0.0722 * linear[2]
            )

        first, second = sorted(
            (luminance(foreground), luminance(background)),
            reverse=True,
        )
        return (first + 0.05) / (second + 0.05)

    def test_workspace_and_database_schema(self):
        database = initialize_workspace(self.settings)
        self.assertTrue((self.settings.root / "AGENTS.md").exists())
        self.assertTrue((self.settings.root / "CLAUDE.md").exists())
        with database.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
        self.assertIn("documents", tables)
        self.assertIn("knowledge_fts", tables)
        self.assertIn("conversations", tables)
        self.assertIn("tool_definitions", tables)
        self.assertIn("conversation_tools", tables)

    def test_send_repairs_a_saved_legacy_conversation_workspace(self):
        database = initialize_workspace(self.settings)
        workspace = self.settings.work_dir / "legacy-saved"
        workspace.mkdir(parents=True)
        (workspace / "AGENTS.md").write_text(
            "# Workspace de conversa Mary\n\nInstruções principais: `../../AGENTS.md`.\n",
            encoding="utf-8",
        )
        conversation_id = database.create_conversation(
            "Conversa existente", "codex", "", workspace
        )
        provider = MagicMock()
        provider.start_conversation.return_value = "native-thread"
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers["codex"] = provider

        orchestrator.send(conversation_id, "Teste", lambda _event: None)

        self.assertTrue((workspace / "tools" / "vr-search.ps1").is_file())
        self.assertIn("botão VR está", (workspace / "AGENTS.md").read_text("utf-8"))
        self.assertNotIn("../../AGENTS.md", (workspace / "AGENTS.md").read_text("utf-8"))
        self.assertNotIn("@../../AGENTS.md", (workspace / "CLAUDE.md").read_text("utf-8"))
        provider.start_conversation.assert_called_once()

    def test_conversation_effort_is_persisted_and_legacy_schema_is_migrated(self):
        path = self.settings.database_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                """CREATE TABLE conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    native_id TEXT NOT NULL DEFAULT '',
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'idle',
                    archived INTEGER NOT NULL DEFAULT 0,
                    cloned_from TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
        database = MaryDatabase(path)
        conversation_id = database.create_conversation(
            "Teste",
            "codex",
            "gpt-test",
            self.settings.work_dir,
            effort="high",
        )
        row = database.get_conversation(conversation_id)
        self.assertEqual(row["effort"], "high")
        self.assertEqual(row["approval_profile"], "auto")
        self.assertEqual(row["collaboration_mode"], "default")
        self.assertEqual(row["service_tier"], "")
        self.assertEqual(row["trashed_at"], "")
        database.update_conversation(conversation_id, effort="xhigh")
        self.assertEqual(database.get_conversation(conversation_id)["effort"], "xhigh")

    def test_legacy_ultra_reasoning_effort_is_consolidated_as_maximum(self):
        self.assertEqual(normalize_effort("ultra"), "max")
        self.assertEqual(normalize_effort("ultra", provider="claude"), "max")

    def test_classification_rules_and_confidence(self):
        fiscal = classify(
            "Apuração de ICMS",
            "Configuração fiscal, SPED, PIS e COFINS para emissão de nota fiscal.",
        )
        self.assertEqual(fiscal.module, "Fiscal")
        self.assertGreaterEqual(fiscal.confidence, 0.85)
        pdv = classify(
            "Configuração CliSiTef no checkout",
            "TEF, pinpad e pagamento da venda no PDV.",
        )
        self.assertEqual(pdv.module, "PDV")

    def test_vrmaster_menu_vocabulary_complements_module_classification(self):
        cases = [
            ("Fluxo de Caixa", "", "ADM_FIN_ESTOQUE"),
            ("Controle Bancário", "Custódia Cheque", "ADM_FIN_ESTOQUE"),
            ("Crédito Rotativo", "Emissão Boleto", "ADM_FIN_ESTOQUE"),
            ("Acompanhamento Estoque", "Tabela Estoque", "ADM_FIN_ESTOQUE"),
            ("Análise RFM", "Clientes sem Compra", "ADM_FIN_ESTOQUE"),
            ("Log Transação Pedido", "Log Workflow", "ADM_FIN_ESTOQUE"),
            ("Encerramento Contábil", "Plano Conta Referencial", "Fiscal"),
            ("Carta Correção", "Nota Entrada e Nota Saída", "Fiscal"),
            ("DIME", "Arquivos Magnéticos e Sintegra", "Fiscal"),
            ("Depreciação", "Ativo Imobilizado", "Fiscal"),
        ]
        for title, body, expected in cases:
            with self.subTest(title=title):
                result = classify(title, body, catalog=())
                self.assertEqual(result.module, expected)
                self.assertEqual(result.status, "approved")

        # A evidência nova é complementar: o contexto clássico de TEF no
        # checkout continua sendo classificado como PDV.
        self.assertEqual(
            classify(
                "TEF no checkout",
                "Venda no PDV com pinpad e CliSiTef.",
                catalog=(),
            ).module,
            "PDV",
        )

    def test_vrmaster_manual_title_uses_the_first_menu_in_the_hierarchy(self):
        cases = [
            ("Manual do sistema VR Master CRM Venda Cupom Médio", "ADM_FIN_ESTOQUE"),
            (
                "Manual do Sistema VR Master Ferramentas v4.2 Contabilidade "
                "Encerramento Contábil",
                "Fiscal",
            ),
            (
                "Manual do Sistema VR Master Ferramentas v4.3 Fiscal "
                "Encerramento Diário",
                "Fiscal",
            ),
            ("Manual do sistema VR Master Utilitário Log Transação Pedido", "ADM_FIN_ESTOQUE"),
            ("Manual do sistema VR Master PDV Parâmetro Geral", "PDV"),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                result = classify(title, "", catalog=())
                self.assertEqual(result.module, expected)
                self.assertEqual(result.status, "approved")
                self.assertIn("hierarquia do titulo", result.reasons[0])

    def test_explicit_category_module_overrides_other_evidence(self):
        fiscal = classify(
            "CFOP de entrada no cadastro de Tipo Saida",
            "Cadastro do VRMaster com evidencias administrativas.",
            "Pagina inicial / Voltar para a pesquisa / FISCAL / "
            "VR MASTER / CADASTRO / FISCAL / TIPO SAIDA",
        )
        self.assertEqual(fiscal.module, "Fiscal")
        self.assertEqual(fiscal.status, "approved")
        self.assertGreaterEqual(fiscal.confidence, 0.95)
        self.assertIn("modulo explicito na categoria", fiscal.reasons[0])

        pdv = classify(
            "Nota fiscal emitida no checkout",
            "ICMS e cadastro tributario.",
            "Pagina inicial / Voltar para a pesquisa / PDV / NFC-e",
        )
        self.assertEqual(pdv.module, "PDV")

        administrative = classify(
            "Venda e TEF",
            "Operacao de caixa e pinpad.",
            "Pagina inicial / Voltar para a pesquisa / FINANCEIRO",
        )
        self.assertEqual(administrative.module, "ADM_FIN_ESTOQUE")

        canonical_administrative = classify(
            "Venda e TEF",
            "Operacao de caixa e pinpad.",
            "Pagina inicial / ADM_FIN_ESTOQUE / Cadastro",
        )
        self.assertEqual(canonical_administrative.module, "ADM_FIN_ESTOQUE")

        menu_hierarchy_cases = [
            ("Financeiro / TEF / Transação", "ADM_FIN_ESTOQUE"),
            ("Nota Fiscal / Recebimento", "Fiscal"),
            ("Contabilidade / Arquivos Magnéticos / DIME", "Fiscal"),
            ("Ativo Imobilizado / Depreciação", "Fiscal"),
            ("Estoque / Produção / Consumo", "ADM_FIN_ESTOQUE"),
            ("CRM / Connect / Serviços Web Sefaz", "ADM_FIN_ESTOQUE"),
            ("Sistema / Serviços Web Sefaz", "ADM_FIN_ESTOQUE"),
            ("Utilitário / Estoque Online", "ADM_FIN_ESTOQUE"),
            ("PDV / TEF / Transação", "PDV"),
            ("Fluxo de Caixa", "ADM_FIN_ESTOQUE"),
            ("Serviços Web Sefaz", "ADM_FIN_ESTOQUE"),
            ("DIME", "Fiscal"),
            (
                "FISCAL / VR GERENCIADOR XML / SISTEMA / CONFIGURAÇÃO",
                "Fiscal",
            ),
            ("PDV / SISTEMA / CONFIGURAÇÃO", "PDV"),
        ]
        for category, expected in menu_hierarchy_cases:
            with self.subTest(category=category):
                result = classify(
                    "Função do VRMaster",
                    "Conteúdo compartilhado entre módulos.",
                    category,
                    catalog=(),
                )
                self.assertEqual(result.module, expected)
                self.assertEqual(result.status, "approved")

    def test_non_explicit_category_requires_review_and_conflicts_are_multimodule(self):
        ambiguous = classify(
            "Configuracao CliSiTef no checkout",
            "TEF, pinpad e pagamento da venda no PDV.",
            "Pagina inicial / Voltar para a pesquisa / VR MASTER",
        )
        self.assertEqual(ambiguous.module, "Revisar")
        self.assertEqual(ambiguous.status, "pending")
        self.assertIn("categoria sem modulo explicito", ambiguous.reasons)

        conflicting = classify(
            "Configuracao geral",
            "Conteudo misto.",
            "Pagina inicial / FISCAL / PDV",
        )
        self.assertEqual(conflicting.module, "Multimodulo")
        self.assertEqual(conflicting.status, "approved")
        self.assertIn("categoria com modulos conflitantes", conflicting.reasons[0])

    def test_product_catalog_improves_module_classification(self):
        catalog_path = (
            Path(__file__).parents[1]
            / "vrsoft_extractor"
            / "mary"
            / "data"
            / "produtos_filas.md"
        )
        catalog = parse_product_catalog(catalog_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(catalog), 140)

        cases = [
            (
                "Manual do VRFinanceiro",
                "Configuração financeira e fechamento.",
                "PDV",
            ),
            (
                "Instalação do VRPdvAdmin",
                "Aplicativo administrativo.",
                "ADM_FIN_ESTOQUE",
            ),
            (
                "VRGerenciadorFinanceiroWeb",
                "Parâmetros do gerenciador.",
                "PDV",
            ),
            (
                "VRIntegracaoOnBlox",
                "Configuração da integração.",
                "ADM_FIN_ESTOQUE",
            ),
            (
                "VRGerenciadorXML",
                "Importação e validação de XML.",
                "Fiscal",
            ),
            (
                "VR Carteira Digital API",
                "Configuração da API e do aplicativo mobile.",
                "ADM_FIN_ESTOQUE",
            ),
        ]
        for title, body, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(
                    classify(title, body, catalog=catalog).module,
                    expected,
                )

    def test_hybrid_products_use_context_or_multimodule(self):
        catalog_path = (
            Path(__file__).parents[1]
            / "vrsoft_extractor"
            / "mary"
            / "data"
            / "produtos_filas.md"
        )
        catalog = parse_product_catalog(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(
            classify("VRAdm", "Visão geral do produto.", catalog=catalog).module,
            "Multimodulo",
        )
        self.assertEqual(
            classify(
                "VRAdm - SPED, ICMS e escrituração fiscal",
                "Configuração tributária e nota fiscal.",
                catalog=catalog,
            ).module,
            "Fiscal",
        )
        self.assertEqual(
            classify(
                "VRCaixa - TEF no PDV",
                "Venda, pinpad, SiTef e frente de loja.",
                catalog=catalog,
            ).module,
            "PDV",
        )

    def test_html_to_markdown_preserves_links_and_images(self):
        markdown, images = html_to_markdown(
            '<h1>Ajuda</h1><p>Texto</p><img src="/img/a.png"><a href="/b">B</a>',
            "https://example.com/base/",
        )
        self.assertIn("# Ajuda", markdown)
        self.assertIn("https://example.com/img/a.png", markdown)
        self.assertIn("https://example.com/b", markdown)
        self.assertEqual(images, ["https://example.com/img/a.png"])

    def test_upsert_versioning_and_search(self):
        database = MaryDatabase(self.settings.database_path)
        document = KnowledgeDocument(
            source="wiki",
            source_id="42",
            title="Configuração de PIX",
            url="https://example.com/wiki/42",
            markdown="Configure o PIX no cadastro financeiro.",
            module="ADM_FIN_ESTOQUE",
            classification_confidence=0.9,
            review_status="approved",
            revision="1",
        )
        document.content_hash = sha256_text(document.markdown)
        document.local_path = "doc.md"
        _, action = database.upsert_document(document)
        self.assertEqual(action, "created")
        results = database.search("configuração PIX")
        self.assertEqual(results[0]["source_id"], "42")
        document.markdown = "Configure o PIX e a carteira digital."
        document.revision = "2"
        document.content_hash = sha256_text(document.markdown)
        _, action = database.upsert_document(document)
        self.assertEqual(action, "updated")
        with database.connect() as connection:
            versions = connection.execute(
                "SELECT count(*) FROM document_versions"
            ).fetchone()[0]
        self.assertEqual(versions, 1)

    def test_search_ranks_function_102_and_expands_map_reference(self):
        database = MaryDatabase(self.settings.database_path)
        documents = [
            KnowledgeDocument(
                source="wiki",
                source_id="4495",
                title="MAPA DE FUNCOES",
                url="https://wiki.example/index.php?title=MAPA_DE_FUNCOES",
                markdown=(
                    "- [Funcao 102 - Entrada Operador]"
                    "(https://wiki.example/index.php?title=Funcao_102)"
                ),
                module="PDV",
                review_status="approved",
                content_hash="mapa",
                local_path="conhecimento/PDV/Wiki/mapa-de-funcoes--4495.md",
            ),
            KnowledgeDocument(
                source="wiki",
                source_id="3742",
                title="Funcao 102",
                url="https://wiki.example/index.php?title=Funcao_102",
                markdown=(
                    "Função responsável por identificar um operador para o caixa. "
                    "Status FECHADO PARCIAL. Tecla de atalho O."
                ),
                module="PDV",
                review_status="approved",
                content_hash="funcao-102",
                local_path="conhecimento/PDV/Wiki/funcao-102--3742.md",
            ),
            KnowledgeDocument(
                source="kb",
                source_id="fiscal-1",
                title="Manual de cadastro de entrada fiscal",
                url="https://kb.example/article/fiscal-1",
                markdown="Função de entrada do operador em cadastro de nota fiscal.",
                module="Fiscal",
                review_status="approved",
                content_hash="fiscal",
                local_path="conhecimento/Fiscal/KB/manual-fiscal.md",
            ),
        ]
        documents.extend(
            KnowledgeDocument(
                source="wiki",
                source_id=f"pdv-{index}",
                title=f"Procedimento PDV {index}",
                url=f"https://wiki.example/pdv-{index}",
                markdown="Consulte a função para entrada do operador no PDV.",
                module="PDV",
                review_status="approved",
                content_hash=f"pdv-{index}",
                local_path=f"conhecimento/PDV/Wiki/procedimento-{index}.md",
            )
            for index in range(7)
        )
        for document in documents:
            database.upsert_document(document)

        plain = database.search("Qual a função de entrada do operador?", limit=8)
        prefixed = database.search(
            "Mary: Qual a função de entrada do operador?", limit=8
        )

        self.assertEqual(plain[0]["source_id"], "3742")
        self.assertEqual(plain[0]["resolved_from"], "MAPA DE FUNCOES")
        self.assertEqual(plain[0]["coverage"], 1.0)
        self.assertEqual(plain[0]["matched_terms"], ["funcao", "entrada", "operador"])
        self.assertIn("FECHADO PARCIAL", plain[0]["excerpt"])
        self.assertTrue(plain[0]["url"].startswith("https://"))
        self.assertTrue(plain[0]["local_path"].endswith("funcao-102--3742.md"))
        self.assertNotIn("Fiscal", [item["module"] for item in plain[:8]])
        self.assertEqual(
            [item["source_id"] for item in plain],
            [item["source_id"] for item in prefixed],
        )

    def test_validated_module_is_preserved_until_reclassification_review(self):
        database = MaryDatabase(self.settings.database_path)
        document = KnowledgeDocument(
            source="wiki",
            source_id="validated-1",
            title="Documento validado",
            url="https://example.com/wiki/validated-1",
            markdown="Conteúdo fiscal.",
            module="Fiscal",
            classification_confidence=0.95,
            review_status="approved",
            revision="1",
            content_hash="hash-1",
            local_path="fiscal.md",
        )
        database.upsert_document(document)
        document.module = "PDV"
        document.classification_confidence = 0.96
        document.review_status = "approved"
        document.revision = "2"
        document.content_hash = "hash-2"
        database.upsert_document(document)
        stored = database.get_document("wiki", "validated-1")
        self.assertEqual(stored["module"], "Fiscal")
        self.assertEqual(stored["review_status"], "pending")

    def test_unchanged_content_refreshes_metadata_without_creating_version(self):
        database = MaryDatabase(self.settings.database_path)
        document = KnowledgeDocument(
            source="wiki",
            source_id="metadata-1",
            title="Documento",
            url="https://example.com/old",
            markdown="Mesmo conteúdo",
            module="Fiscal",
            review_status="approved",
            revision="1",
            content_hash="same-hash",
            category="Fiscal",
            local_path="conhecimento/Fiscal/Wiki/documento.md",
        )
        database.upsert_document(document)
        document.url = "https://example.com/new"
        document.revision = "2"
        document.category = "Fiscal / Guias"
        document.synced_at = "2026-08-12T12:00:00+00:00"

        _document_id, action = database.upsert_document(document)
        stored = database.get_document("wiki", "metadata-1")

        self.assertEqual(action, "unchanged")
        self.assertEqual(stored["url"], "https://example.com/new")
        self.assertEqual(stored["revision"], "2")
        self.assertEqual(stored["category"], "Fiscal / Guias")
        with database.connect() as connection:
            versions = connection.execute(
                "SELECT count(*) FROM document_versions"
            ).fetchone()[0]
        self.assertEqual(versions, 0)

    def test_unchanged_content_preserves_human_classification(self):
        database = MaryDatabase(self.settings.database_path)
        approved = KnowledgeDocument(
            source="wiki",
            source_id="human-1",
            title="Documento humano",
            url="https://example.com/human-1",
            markdown="Mesmo conteúdo",
            module="Fiscal",
            review_status="approved",
            content_hash="same-content",
            local_path="conhecimento/Fiscal/Wiki/human.md",
        )
        database.upsert_document(approved)
        current = database.get_document("wiki", "human-1")
        incoming = KnowledgeDocument(
            source="wiki",
            source_id="human-1",
            title="Documento humano atualizado",
            url="https://example.com/human-1",
            markdown="Mesmo conteúdo",
            module="PDV",
            review_status="pending",
            content_hash="same-content",
            local_path="conhecimento/PDV/Wiki/human.md",
        )

        changed = preserve_validated_classification(current, incoming)
        database.upsert_document(incoming)
        stored = database.get_document("wiki", "human-1")

        self.assertFalse(changed)
        self.assertEqual(incoming.module, "Fiscal")
        self.assertEqual(incoming.review_status, "approved")
        self.assertEqual(stored["module"], "Fiscal")
        self.assertEqual(stored["review_status"], "approved")

    def test_queueing_reclassification_hides_previously_approved_document(self):
        database = MaryDatabase(self.settings.database_path)
        document = KnowledgeDocument(
            source="wiki",
            source_id="revalidate-1",
            title="Documento validado",
            url="https://example.com/revalidate-1",
            markdown="pinpad TEF",
            module="Fiscal",
            review_status="approved",
            content_hash="revalidate-hash",
            local_path="conhecimento/Fiscal/Wiki/revalidate.md",
        )
        document_id, _action = database.upsert_document(document)

        database.queue_review(
            document_id,
            "PDV",
            0.92,
            ["pinpad"],
            "Fiscal",
            True,
        )

        stored = database.get_document("wiki", "revalidate-1")
        self.assertEqual(stored["module"], "Fiscal")
        self.assertEqual(stored["review_status"], "pending")
        self.assertEqual(database.search("pinpad"), [])

    def test_unchanged_wiki_repairs_missing_pending_review(self):
        database = MaryDatabase(self.settings.database_path)
        document = KnowledgeDocument(
            source="wiki",
            source_id="42",
            title="Configuração de pinpad",
            url="https://example.com/wiki/42",
            markdown="Configuração TEF no PDV",
            module="Revisar",
            review_status="pending",
            revision="7",
            content_hash="wiki-hash",
            local_path="conhecimento/Revisar/configuracao--42.md",
        )
        database.upsert_document(document)
        sync = WikiSync(self.settings, database)
        sync.iter_pages = lambda: iter(
            [{"pageid": 42, "title": document.title, "revisions": [{"revid": 7}]}]
        )

        stats = sync.sync(limit=1)

        self.assertEqual(stats.unchanged, 1)
        self.assertEqual(stats.review, 1)
        self.assertEqual(database.query_reviews(ReviewFilters()).total, 1)

    def test_wiki_sync_approves_known_menu_without_queueing_review(self):
        database = MaryDatabase(self.settings.database_path)
        classification = classify(
            "Conciliação bancária",
            "Procedimento da função no VRMaster.",
            "Financeiro / Controle Bancário / Conciliação Bancária",
            catalog=(),
        )
        document = KnowledgeDocument(
            source="wiki",
            source_id="financeiro-menu-1",
            title="Conciliação bancária",
            url="https://example.com/wiki/financeiro-menu-1",
            markdown="Procedimento da função no VRMaster.",
            module=classification.module,
            classification_confidence=classification.confidence,
            review_status=classification.status,
            revision="1",
            content_hash="financeiro-menu-hash",
            category="Financeiro / Controle Bancário / Conciliação Bancária",
        )
        sync = WikiSync(self.settings, database)
        sync.iter_pages = lambda: iter(
            [
                {
                    "pageid": document.source_id,
                    "title": document.title,
                    "revisions": [{"revid": 1}],
                }
            ]
        )
        sync.fetch_document = MagicMock(return_value=document)

        stats = sync.sync(limit=1)

        stored = database.get_document("wiki", document.source_id)
        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.review, 0)
        self.assertEqual(stored["module"], "ADM_FIN_ESTOQUE")
        self.assertEqual(stored["review_status"], "approved")
        self.assertEqual(database.query_reviews(ReviewFilters()).total, 0)

    def test_wiki_sync_skips_the_broken_test_placeholder(self):
        database = MaryDatabase(self.settings.database_path)
        progress: list[str] = []
        sync = WikiSync(self.settings, database, progress.append)
        sync.iter_pages = lambda: iter(
            [
                {
                    "pageid": 2030,
                    "title": "Teste",
                    "revisions": [{"revid": 23711}],
                }
            ]
        )
        sync.fetch_document = MagicMock()

        stats = sync.sync(limit=1)

        self.assertEqual(stats.discovered, 1)
        self.assertEqual(stats.skipped, 1)
        self.assertEqual(stats.errors, 0)
        self.assertIn("página de teste", progress[0])
        sync.fetch_document.assert_not_called()

    def test_wiki_api_error_is_reported_with_code_and_message(self):
        database = MaryDatabase(self.settings.database_path)
        sync = WikiSync(self.settings, database)
        response = MagicMock()
        response.read.return_value = (
            b'{"error":{"code":"internal_api_error_Error",'
            b'"info":"Caught exception of type Error"}}'
        )

        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            with self.assertRaisesRegex(
                RuntimeError,
                "internal_api_error_Error.*Caught exception",
            ):
                sync._api({"action": "parse", "pageid": "2030"})

    def test_sync_run_with_item_errors_is_partial(self):
        database = MaryDatabase(self.settings.database_path)
        run_id = database.start_sync("wiki")
        database.finish_sync(run_id, SyncStats("wiki", discovered=3, errors=1))
        with database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM sync_runs WHERE id=?", (run_id,)
            ).fetchone()
        self.assertEqual(row["status"], "partial")

    def test_partial_wiki_sync_does_not_inactivate_unseen_documents(self):
        database = MaryDatabase(self.settings.database_path)
        existing = KnowledgeDocument(
            source="wiki",
            source_id="existing",
            title="Documento existente",
            url="https://example.com/wiki/existing",
            markdown="Conteúdo preservado",
            module="Fiscal",
            review_status="approved",
            status="active",
            revision="1",
            content_hash="existing-hash",
            local_path="conhecimento/Fiscal/Wiki/existing.md",
        )
        database.upsert_document(existing)
        sync = WikiSync(self.settings, database)
        sync.iter_pages = lambda: iter(
            [{"pageid": 99, "title": "Página com falha", "revisions": [{"revid": 1}]}]
        )
        sync.fetch_document = MagicMock(side_effect=RuntimeError("falha de rede"))

        stats = sync.sync()

        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.inactive, 0)
        self.assertEqual(database.get_document("wiki", "existing")["status"], "active")

    def test_write_document_moves_canonical_file_when_module_changes(self):
        document = KnowledgeDocument(
            source="wiki",
            source_id="move-1",
            title="Documento móvel",
            url="https://example.com/move-1",
            markdown="Conteúdo",
            module="Revisar",
            review_status="pending",
            content_hash="move-hash",
        )
        original = write_document(self.settings.root, document)
        document.module = "PDV"
        document.review_status = "approved"

        moved = write_document(
            self.settings.root,
            document,
            previous_path=original,
        )

        self.assertFalse(original.exists())
        self.assertTrue(moved.is_file())
        self.assertIn('module: "PDV"', moved.read_text(encoding="utf-8"))

    def test_document_file_rolls_back_when_database_persistence_fails(self):
        document = KnowledgeDocument(
            source="wiki",
            source_id="rollback-1",
            title="Documento transacional",
            url="https://example.com/rollback-1",
            markdown="Versão anterior",
            module="Fiscal",
            review_status="approved",
            content_hash="old-hash",
        )
        original = write_document(self.settings.root, document)
        original_bytes = original.read_bytes()
        document.markdown = "Versão que não foi persistida"
        document.content_hash = "new-hash"

        with self.assertRaisesRegex(RuntimeError, "banco indisponível"):
            write_and_persist_document(
                self.settings.root,
                document,
                lambda: (_ for _ in ()).throw(RuntimeError("banco indisponível")),
                previous_path=original,
            )

        self.assertEqual(original.read_bytes(), original_bytes)

    def test_document_path_rejects_unknown_module_instead_of_escaping_knowledge(self):
        document = KnowledgeDocument(
            source="wiki",
            source_id="unsafe-1",
            title="Documento inseguro",
            url="https://example.com/unsafe-1",
            markdown="Conteúdo",
            module="../../fora",
        )

        with self.assertRaisesRegex(ValueError, "Módulo de conhecimento inválido"):
            write_document(self.settings.root, document)

        self.assertFalse((self.settings.root / "fora").exists())

    def test_incomplete_ocr_download_does_not_replace_existing_file(self):
        target = self.root / "por.traineddata"
        target.write_bytes(b"previous version")
        with (
            patch(
                "vrsoft_extractor.mary.ocr.urllib.request.urlopen",
                return_value=io.BytesIO(b"curto"),
            ),
            self.assertRaisesRegex(RuntimeError, "Download incompleto"),
        ):
            _download_file("https://example.com/por", target, minimum_bytes=100)

        self.assertEqual(target.read_bytes(), b"previous version")

    def test_oversized_ocr_download_does_not_replace_existing_file(self):
        target = self.root / "eng.traineddata"
        target.write_bytes(b"previous version")
        with (
            patch(
                "vrsoft_extractor.mary.ocr.urllib.request.urlopen",
                return_value=io.BytesIO(b"oversized"),
            ),
            self.assertRaisesRegex(RuntimeError, "excede o limite"),
        ):
            _download_file(
                "https://example.com/eng",
                target,
                minimum_bytes=1,
                maximum_bytes=3,
            )

        self.assertEqual(target.read_bytes(), b"previous version")

    def test_classification_audit_refreshes_review_without_changing_module(self):
        database = MaryDatabase(self.settings.database_path)
        document = KnowledgeDocument(
            source="wiki",
            source_id="audit-1",
            title="Manual do VRFinanceiro",
            url="https://example.com/wiki/audit-1",
            markdown="Configuração do aplicativo.",
            module="Revisar",
            classification_confidence=0.35,
            review_status="pending",
            revision="1",
            content_hash="audit-hash",
            local_path="audit.md",
        )
        document_id, _action = database.upsert_document(document)
        database.queue_review(
            document_id,
            "Fiscal",
            0.61,
            ["regra antiga"],
            "Revisar",
        )
        report = audit_classification(
            database,
            example_limit=0,
            queue_review=True,
        )
        stored = database.get_document("wiki", "audit-1")
        review = database.list_reviews()[0]
        self.assertEqual(stored["module"], "Revisar")
        self.assertEqual(review["suggested_module"], "PDV")
        self.assertEqual(report["review_queue_updated"], 1)

    def test_review_filters_pagination_and_risk_order(self):
        database = MaryDatabase(self.settings.database_path)
        self._queue_review(
            database,
            "safe",
            source="kb",
            current_module="PDV",
            suggested_module="PDV",
            confidence=0.92,
            product="VRPdv",
            category="Venda",
        )
        self._queue_review(
            database,
            "validated-change",
            current_module="Fiscal",
            suggested_module="ADM_FIN_ESTOQUE",
            confidence=0.91,
            product="VRAdm",
            category="Cadastro",
            validated_change=True,
        )
        self._queue_review(
            database,
            "low",
            confidence=0.35,
            reasons=[],
        )

        first = database.query_reviews(
            ReviewFilters(sort="risk", limit=2)
        )
        self.assertEqual(first.total, 3)
        self.assertEqual(len(first.items), 2)
        self.assertEqual(first.items[0]["source_id"], "validated-change")
        second = database.query_reviews(
            ReviewFilters(sort="risk", limit=2, offset=2)
        )
        self.assertEqual(len(second.items), 1)
        kb = database.query_reviews(
            ReviewFilters(source="kb", confidence_band="high")
        )
        self.assertEqual([row["source_id"] for row in kb.items], ["safe"])
        no_product = database.query_reviews(
            ReviewFilters(special="no_product")
        )
        self.assertEqual(
            {row["source_id"] for row in no_product.items},
            {"low"},
        )
        search = database.query_reviews(
            ReviewFilters(query="Cadastro", suggested_module="ADM_FIN_ESTOQUE")
        )
        self.assertEqual(
            [row["source_id"] for row in search.items],
            ["validated-change"],
        )

    def test_review_decisions_history_reopen_and_unchanged_deduplication(self):
        database = MaryDatabase(self.settings.database_path)
        keep_id = self._queue_review(
            database,
            "keep",
            current_module="Fiscal",
            suggested_module="PDV",
        )
        database.decide_reviews([keep_id], "keep", note="Classificação confirmada")
        stored = database.get_document("wiki", "keep")
        self.assertEqual(stored["module"], "Fiscal")
        self.assertEqual(stored["review_status"], "approved")
        kept = database.query_reviews(ReviewFilters(status="kept")).items[0]
        self.assertEqual(kept["decision_note"], "Classificação confirmada")

        database.decide_reviews([keep_id], "reopen")
        reopened = database.query_reviews(ReviewFilters(status="pending")).items
        self.assertEqual([row["id"] for row in reopened], [keep_id])

        defer_id = self._queue_review(database, "defer")
        database.decide_reviews([defer_id], "defer")
        deferred = database.query_reviews(ReviewFilters(status="deferred")).items[0]
        document = database.get_document("wiki", "defer")
        self.assertFalse(
            database.queue_review(
                int(deferred["document_id"]),
                deferred["suggested_module"],
                deferred["confidence"],
                json.loads(deferred["reasons_json"]),
                deferred["current_module"],
            )
        )
        self.assertEqual(
            database.query_reviews(ReviewFilters(status="deferred")).total,
            1,
        )

        with database.connect() as connection:
            connection.execute(
                "UPDATE documents SET content_hash='changed' WHERE id=?",
                (document["id"],),
            )
        self.assertTrue(
            database.queue_review(
                int(deferred["document_id"]),
                deferred["suggested_module"],
                deferred["confidence"],
                json.loads(deferred["reasons_json"]),
                deferred["current_module"],
            )
        )
        self.assertEqual(
            database.query_reviews(
                ReviewFilters(query="defer", status="pending")
            ).total,
            1,
        )

    def test_review_bulk_approval_applies_destination_to_mixed_suggestions(self):
        database = MaryDatabase(self.settings.database_path)
        first = self._queue_review(
            database,
            "bulk-1",
            suggested_module="PDV",
            reasons=["pinpad"],
        )
        second = self._queue_review(
            database,
            "bulk-2",
            suggested_module="Fiscal",
            reasons=["tributação"],
        )
        self.assertEqual(
            database.decide_reviews(
                [first, second],
                "approve",
                module="ADM_FIN_ESTOQUE",
            ),
            2,
        )
        self.assertEqual(
            database.query_reviews(ReviewFilters(status="approved")).total,
            2,
        )
        with database.connect() as connection:
            modules = {
                row["module"]
                for row in connection.execute(
                    "SELECT module FROM documents WHERE source_id IN (?, ?)",
                    ("bulk-1", "bulk-2"),
                ).fetchall()
            }
        self.assertEqual(modules, {"ADM_FIN_ESTOQUE"})

    def test_review_query_clamps_offset_after_results_shrink(self):
        database = MaryDatabase(self.settings.database_path)
        review_id = self._queue_review(database, "last-page")

        page = database.query_reviews(ReviewFilters(limit=1, offset=100))
        self.assertEqual(page.offset, 0)
        self.assertEqual([row["id"] for row in page.items], [review_id])

        database.decide_reviews([review_id], "keep")
        empty = database.query_reviews(ReviewFilters(limit=1, offset=100))
        self.assertEqual(empty.offset, 0)
        self.assertEqual(empty.items, [])

    def test_review_approval_moves_canonical_file_and_updates_front_matter(self):
        database = initialize_workspace(self.settings)
        document = KnowledgeDocument(
            source="wiki",
            source_id="move-after-review",
            title="Documento para revisar",
            url="https://example.com/wiki/move-after-review",
            markdown="Conteúdo validado.",
            module="Revisar",
            classification_confidence=0.55,
            review_status="pending",
            revision="1",
            content_hash="hash-move-after-review",
        )
        original = write_document(self.settings.root, document)
        document_id, _action = database.upsert_document(document)
        database.queue_review(document_id, "PDV", 0.91, ["pinpad"])
        review_id = int(
            database.query_reviews(
                ReviewFilters(query="move-after-review")
            ).items[0]["id"]
        )

        database.decide_reviews([review_id], "approve", module="PDV")

        stored = database.get_document("wiki", "move-after-review")
        moved = self.settings.root / stored["local_path"]
        self.assertEqual(stored["module"], "PDV")
        self.assertEqual(stored["review_status"], "approved")
        self.assertTrue(moved.is_file())
        self.assertIn("conhecimento/PDV/Wiki", moved.as_posix())
        self.assertFalse(original.exists())
        markdown = moved.read_text(encoding="utf-8")
        self.assertIn('module: "PDV"', markdown)
        self.assertIn('review_status: "approved"', markdown)

    def test_review_schema_migrates_existing_rows_without_loss(self):
        database = MaryDatabase(self.settings.database_path)
        review_id = self._queue_review(database, "legacy")
        with database.connect() as connection:
            connection.execute(
                """UPDATE classification_reviews
                   SET queued_at='',updated_at='',document_hash='',
                       suggestion_signature='' WHERE id=?""",
                (review_id,),
            )
        migrated = MaryDatabase(self.settings.database_path)
        row = migrated.query_reviews(ReviewFilters(query="legacy")).items[0]
        self.assertTrue(row["queued_at"])
        self.assertTrue(row["updated_at"])
        self.assertEqual(row["document_hash"], "hash-legacy")
        self.assertEqual(len(row["suggestion_signature"]), 64)

    def test_fts_query_escapes_natural_language(self):
        query = _fts_query("Mary: como corrigir erro do TEF (SiTef)?")
        self.assertNotIn(":", query)
        self.assertIn('"tef"', query)
        self.assertIn(" OR ", query)

    def test_canonical_markdown_removes_signed_query(self):
        document = KnowledgeDocument(
            source="kb",
            source_id="7",
            title="Artigo",
            url="https://s3.example/a.png?X-Amz-Signature=secret&id=7",
            markdown="Conteúdo",
            module="PDV",
            content_hash="abc",
        )
        rendered = canonical_markdown(document)
        self.assertNotIn("Signature", rendered)
        self.assertIn("id=7", rendered)

    def test_migration_is_allowlist_and_rejects_mojibake(self):
        (self.old / "AGENTS.md").write_text("# Mary", encoding="utf-8")
        (self.old / "VRWiki").mkdir()
        (self.old / "VRWiki" / "old.md").write_text("Não copiar", encoding="utf-8")
        (self.old / "Atlas").mkdir()
        (self.old / "Atlas" / "AGENTS.md").write_text("ConfiguraÃ§Ã£o", encoding="utf-8")
        manifest = build_manifest(self.settings)
        names = {Path(item.source).name: item for item in manifest}
        self.assertIn("AGENTS.md", names)
        self.assertFalse(any("VRWiki" in item.source for item in manifest))
        atlas = next(item for item in manifest if "Atlas" in item.source)
        self.assertEqual(atlas.status, "rejected_mojibake")

    def test_migration_copies_source_prompts_and_rewrites_paths(self):
        (self.old / "AGENTS.md").write_text(
            "Use `VRWiki/AGENTS.md`, `KB/AGENTS.md` e `Fisco/AGENTS.md`.",
            encoding="utf-8",
        )
        for folder in ("VRWiki", "KB", "Fisco"):
            (self.old / folder).mkdir()
            (self.old / folder / "AGENTS.md").write_text(
                f"# {folder}", encoding="utf-8"
            )
        result = migrate(self.settings)
        self.assertEqual(result["copied"], 4)
        root_agents = (self.settings.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`agentes/VRWiki/AGENTS.md`", root_agents)
        self.assertTrue(
            (self.settings.root / "agentes" / "KB" / "AGENTS.md").exists()
        )

    def test_codex_resolver_prefers_runnable_binary_or_shim(self):
        command = _resolve_codex_command()
        self.assertTrue(command)
        self.assertIn(Path(command).suffix.lower(), {".exe", ".cmd", ".ps1", ""})

    def test_codex_process_exit_releases_pending_rpc_immediately(self):
        provider = CodexProvider()
        pending = queue.Queue(maxsize=1)
        provider._pending[7] = pending
        process = MagicMock()
        process.stdout = [""]
        process.poll.return_value = 1
        provider.process = process

        provider._read_loop(process)

        response = pending.get_nowait()
        self.assertIn("encerrou com código 1", response["error"]["message"])
        self.assertIsNone(provider.process)
        self.assertFalse(provider._pending)

    def test_codex_rpc_timeout_resets_process_and_catalog_uses_ten_seconds(self):
        provider = CodexProvider()
        process = MagicMock()
        process.poll.return_value = None
        provider.process = process
        response_queue = MagicMock()
        response_queue.get.side_effect = queue.Empty
        with (
            patch("vrsoft_extractor.mary.providers.queue.Queue", return_value=response_queue),
            patch.object(provider, "_send"),
            patch.object(provider, "_stop_process") as stop,
        ):
            with self.assertRaisesRegex(ProviderError, "Timeout do Codex em model/list"):
                provider._rpc("model/list", timeout=0.01)
        stop.assert_called_once_with(process)

        with (
            patch.object(provider, "_ensure_started"),
            patch.object(provider, "_rpc", return_value={"data": []}) as rpc,
        ):
            provider.list_models()
        self.assertEqual(rpc.call_args.kwargs["timeout"], 10)

    def test_selects_latest_tesseract_windows_installer(self):
        listing = (
            '<a href="tesseract-ocr-w64-setup-5.9.0.exe">old</a>'
            '<a href="tesseract-ocr-w64-setup-5.10.0.exe">new</a>'
        )
        url = latest_windows_installer_url(listing, "https://example.com/tesseract/")
        self.assertEqual(
            url,
            "https://example.com/tesseract/tesseract-ocr-w64-setup-5.10.0.exe",
        )

    def test_selects_trusted_tesseract_installer_from_github_fallback(self):
        url = latest_github_installer_url(
            {
                "assets": [
                    {
                        "name": "tesseract-ocr-w64-setup-5.4.0.exe",
                        "browser_download_url": (
                            "https://github.com/UB-Mannheim/tesseract/releases/download/"
                            "v5.4.0/tesseract-ocr-w64-setup-5.4.0.exe"
                        ),
                    }
                ]
            }
        )
        self.assertTrue(url.endswith("tesseract-ocr-w64-setup-5.4.0.exe"))

    def test_codex_send_resumes_thread_after_app_restart(self):
        provider = CodexProvider()
        callback = lambda _event: None
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(
                provider,
                "resume_conversation",
                return_value="native-1",
            ) as resume,
            patch.object(provider, "_rpc", return_value={}),
        ):
            provider.send_message(
                "local-1",
                "native-1",
                "gpt-test",
                "high",
                self.root,
                "Olá",
                callback,
            )
        resume.assert_called_once()

    def test_codex_send_unarchives_when_resume_reports_archived_session(self):
        provider = CodexProvider()
        callback = lambda _event: None
        archived = ProviderError(
            "session native-1 is archived. Run `codex unarchive native-1` first."
        )
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(
                provider,
                "resume_conversation",
                side_effect=[archived, "native-1"],
            ) as resume,
            patch.object(provider, "unarchive_thread") as unarchive,
            patch.object(provider, "_rpc", return_value={}) as rpc,
        ):
            provider.send_message(
                "local-1",
                "native-1",
                "gpt-test",
                "high",
                self.root,
                "Olá",
                callback,
            )

        self.assertEqual(resume.call_count, 2)
        unarchive.assert_called_once_with("native-1")
        self.assertEqual(rpc.call_args.args[0], "turn/start")

    def test_codex_send_unarchives_and_retries_rejected_turn(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        callback = lambda _event: None
        archived = ProviderError(
            "session native-1 is archived. Run `codex unarchive native-1` first."
        )
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(provider, "unarchive_thread") as unarchive,
            patch.object(
                provider,
                "resume_conversation",
                return_value="native-1",
            ) as resume,
            patch.object(provider, "_rpc", side_effect=[archived, {}]) as rpc,
        ):
            provider.send_message(
                "local-1",
                "native-1",
                "gpt-test",
                "high",
                self.root,
                "Olá",
                callback,
            )

        unarchive.assert_called_once_with("native-1")
        resume.assert_called_once()
        self.assertEqual([call.args[0] for call in rpc.call_args_list], ["turn/start"] * 2)
        self.assertEqual(
            rpc.call_args_list[0].args[1]["input"],
            rpc.call_args_list[1].args[1]["input"],
        )

    def test_codex_turn_receives_effort(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        callback = lambda _event: None
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(provider, "_rpc", return_value={}) as rpc,
        ):
            provider.send_message(
                "local-1",
                "native-1",
                "gpt-test",
                "xhigh",
                self.root,
                "Olá",
                callback,
            )
        params = rpc.call_args.args[1]
        self.assertEqual(params["effort"], "xhigh")
        self.assertEqual(params["approvalPolicy"], "on-request")

    def test_codex_turn_includes_native_local_image_input(self):
        image = self.root / "captura.png"
        image.write_bytes(b"image-placeholder")
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(provider, "_rpc", return_value={}) as rpc,
        ):
            provider.send_message(
                "local-1",
                "native-1",
                "gpt-test",
                "high",
                self.root,
                "Analise a imagem",
                lambda _event: None,
                image_paths=[str(image)],
            )

        turn_input = rpc.call_args.args[1]["input"]
        self.assertIn(
            {"type": "localImage", "path": str(image.resolve())},
            turn_input,
        )

    def test_codex_max_is_sent_directly_without_default_collaboration_preset(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        options = ConversationOptions(
            model="gpt-5.6",
            effort="max",
            collaboration_mode="default",
        )
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(provider, "_rpc", return_value={}) as rpc,
        ):
            provider.update_settings(
                "local-1", "native-1", self.root, options
            )
            provider.send_message(
                "local-1",
                "native-1",
                "gpt-5.6",
                "max",
                self.root,
                "Teste max",
                lambda _event: None,
                options,
            )

        settings = rpc.call_args_list[0].args[1]
        turn = rpc.call_args_list[1].args[1]
        self.assertEqual(settings["model"], "gpt-5.6")
        self.assertEqual(settings["effort"], "max")
        self.assertNotIn("collaborationMode", settings)
        self.assertEqual(turn["model"], "gpt-5.6")
        self.assertEqual(turn["effort"], "max")
        self.assertNotIn("collaborationMode", turn)

    def test_codex_reasoning_summary_delta_is_exposed_as_safe_runtime_event(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        events = []
        provider._callbacks["local-1"] = events.append

        provider._handle_server_message(
            {
                "method": "item/reasoning/summaryTextDelta",
                "params": {
                    "threadId": "native-1",
                    "itemId": "reasoning-1",
                    "delta": "Consultando a base local",
                },
            }
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "reasoning_delta")
        self.assertEqual(events[0].text, "Consultando a base local")

    def test_codex_plan_delta_stays_out_of_the_assistant_answer(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        events = []
        provider._callbacks["local-1"] = events.append

        provider._handle_server_message(
            {
                "method": "item/plan/delta",
                "params": {
                    "threadId": "native-1",
                    "itemId": "plan-1",
                    "delta": "Inspecionar a base e preparar a resposta",
                },
            }
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "reasoning_delta")
        self.assertNotEqual(events[0].kind, "assistant_delta")
        self.assertEqual(
            events[0].text, "Inspecionar a base e preparar a resposta"
        )

    def test_codex_separates_distinct_assistant_items_with_a_blank_line(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        events = []
        provider._callbacks["local-1"] = events.append

        for item_id, delta in (
            ("commentary-1", "Vou verificar a versão."),
            ("final-1", "Para colocar imagens, siga estes passos."),
        ):
            provider._handle_server_message(
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "native-1",
                        "itemId": item_id,
                        "delta": delta,
                    },
                }
            )

        self.assertEqual(events[0].text, "Vou verificar a versão.")
        self.assertEqual(
            events[1].text,
            "\n\nPara colocar imagens, siga estes passos.",
        )

    def test_effective_thread_settings_event_is_emitted_and_persisted(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        events = []
        provider._callbacks["local-1"] = events.append
        payload = {
            "threadId": "native-1",
            "threadSettings": {
                "model": "gpt-5.6",
                "effort": "xhigh",
                "serviceTier": "fast",
                "collaborationMode": {"mode": "default", "settings": {}},
            },
        }

        provider._handle_server_message(
            {"method": "thread/settings/updated", "params": payload}
        )

        self.assertEqual(events[0].kind, "settings_updated")
        database = initialize_workspace(self.settings)
        conversation_id = database.create_conversation(
            "Efetivo", "codex", "gpt-5.6", self.settings.work_dir / "efetivo",
            effort="max",
        )
        event = RuntimeEvent(
            conversation_id,
            "settings_updated",
            payload={
                **payload,
                "threadSettings": {
                    **payload["threadSettings"],
                    "model": "gpt-5.7-provider-effective",
                },
            },
        )
        database.add_message(conversation_id, "user", "Conversa já iniciada")
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator._handle_event(event)
        row = database.get_conversation(conversation_id)
        self.assertEqual(row["model"], "gpt-5.6")
        self.assertEqual(row["effort"], "xhigh")
        self.assertEqual(row["service_tier"], "fast")
        with database.connect() as connection:
            stored = connection.execute(
                "SELECT kind,payload_json FROM runtime_events WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
        self.assertEqual(stored["kind"], "settings_updated")
        self.assertIn('"effort": "xhigh"', stored["payload_json"])

    def test_codex_lists_skills_and_sends_structured_skill_input(self):
        provider = CodexProvider()
        skill_path = str((self.root / "skills" / "review" / "SKILL.md").resolve())
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(
                provider,
                "_rpc",
                return_value={
                    "data": [
                        {
                            "cwd": str(self.root),
                            "skills": [
                                {
                                    "name": "review",
                                    "description": "Revisar altera\u00e7\u00f5es",
                                    "path": skill_path,
                                    "enabled": True,
                                    "interface": {"displayName": "Code Review"},
                                }
                            ],
                            "errors": [],
                        }
                    ]
                },
            ) as rpc,
        ):
            catalog = provider.list_skills(self.root, force_reload=True)
        self.assertEqual(catalog["skills"][0]["name"], "review")
        self.assertEqual(catalog["skills"][0]["displayName"], "Code Review")
        self.assertEqual(rpc.call_args.args[0], "skills/list")
        self.assertEqual(rpc.call_args.kwargs["timeout"], 10)

        provider._native_to_local["native-1"] = "local-1"
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(provider, "_rpc", return_value={}) as rpc,
        ):
            provider.send_message(
                "local-1",
                "native-1",
                "gpt-test",
                "medium",
                self.root,
                "Analise este patch",
                lambda _event: None,
                skills=[{"name": "review", "path": skill_path}],
            )
        turn = rpc.call_args.args[1]
        self.assertEqual(turn["input"][0]["text"], "$review Analise este patch")
        self.assertEqual(
            turn["input"][1],
            {"type": "skill", "name": "review", "path": skill_path},
        )

    def test_codex_thread_uses_supported_approval_policy(self):
        provider = CodexProvider()
        with (
            patch.object(provider, "_ensure_started"),
            patch.object(
                provider,
                "_rpc",
                return_value={"thread": {"id": "native-1"}},
            ) as rpc,
        ):
            provider.start_conversation(
                "local-1",
                "gpt-test",
                "medium",
                self.root,
            )
        params = rpc.call_args.args[1]
        self.assertEqual(params["approvalPolicy"], "on-request")
        self.assertEqual(params["sandbox"], "workspace-write")

    def test_all_approval_profiles_serialize_exact_thread_and_turn_contracts(self):
        expected = {
            "supervised": ("read-only", "readOnly", "on-request", "user"),
            "auto_edits": ("workspace-write", "workspaceWrite", "untrusted", "user"),
            "auto": ("workspace-write", "workspaceWrite", "on-request", "auto_review"),
            "full_access": ("danger-full-access", "dangerFullAccess", "never", "user"),
        }
        self.assertEqual(set(APPROVAL_PRESETS), set(expected))
        for profile, contract in expected.items():
            with self.subTest(profile=profile):
                provider = CodexProvider()
                calls: list[tuple[str, dict]] = []

                def rpc(method, params, timeout=45):
                    calls.append((method, params))
                    return {"thread": {"id": f"native-{profile}"}} if method == "thread/start" else {}

                options = ConversationOptions(
                    model="gpt-test",
                    effort="high",
                    approval_profile=profile,
                    collaboration_mode="plan",
                )
                with patch.object(provider, "_ensure_started"), patch.object(provider, "_rpc", side_effect=rpc):
                    native = provider.start_conversation(
                        profile, "gpt-test", "high", self.root, options
                    )
                    provider.send_message(
                        profile,
                        native,
                        "gpt-test",
                        "high",
                        self.root,
                        "teste",
                        lambda _event: None,
                        options,
                    )
                thread = next(params for method, params in calls if method == "thread/start")
                turn = next(params for method, params in calls if method == "turn/start")
                self.assertEqual(thread["sandbox"], contract[0])
                self.assertEqual(turn["sandboxPolicy"]["type"], contract[1])
                self.assertEqual(thread["approvalPolicy"], contract[2])
                self.assertEqual(turn["approvalPolicy"], contract[2])
                self.assertEqual(thread["approvalsReviewer"], contract[3])
                self.assertEqual(turn["approvalsReviewer"], contract[3])
                self.assertEqual(turn["collaborationMode"]["mode"], "plan")

    def test_codex_approval_responses_cover_decision_permissions_and_mcp(self):
        provider = CodexProvider()
        with patch.object(provider, "_send") as send:
            provider.approve_action("1", True, True, {"method": "item/fileChange/requestApproval"})
            provider.approve_action(
                "2",
                True,
                False,
                {
                    "method": "item/permissions/requestApproval",
                    "permissions": {"network": {"enabled": True}},
                },
            )
            provider.approve_action(
                "3",
                False,
                False,
                {"method": "mcpServer/elicitation/request", "_decision": "cancel"},
            )
        self.assertEqual(send.call_args_list[0].args[0]["result"], {"decision": "acceptForSession"})
        self.assertEqual(
            send.call_args_list[1].args[0]["result"],
            {"permissions": {"network": {"enabled": True}}, "scope": "turn"},
        )
        self.assertEqual(send.call_args_list[2].args[0]["result"]["action"], "cancel")

    def test_local_tool_runner_validates_schema_and_stdio_failures(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }
        tool = {
            "name": "echo_json",
            "description": "Ecoa o JSON recebido",
            "input_schema": schema,
            "executable": sys.executable,
            "arguments": ["-c", "import sys; print(sys.stdin.read())"],
            "timeout_seconds": 5,
        }
        result = run_local_tool(tool, {"name": "Mary"}, self.root)
        self.assertEqual(result.parsed, {"name": "Mary"})
        with self.assertRaises(ToolExecutionError):
            run_local_tool(tool, {}, self.root)
        with self.assertRaises(ToolValidationError):
            validate_tool_definition(
                "apply_patch", "reservada", {"type": "object"}, sys.executable, []
            )
        with self.assertRaises(ToolValidationError):
            validate_tool_definition(
                "schema_ruim",
                "inválido",
                {"type": "object", "properties": []},
                sys.executable,
                [],
            )

        failing = {**tool, "arguments": ["-c", "import sys; sys.stderr.write('falhou'); sys.exit(7)"]}
        with self.assertRaises(ToolExecutionError) as failed:
            run_local_tool(failing, {"name": "Mary"}, self.root)
        self.assertIn("7", str(failed.exception))
        stderr_only = {
            **tool,
            "arguments": ["-c", "import sys; sys.stderr.write('aviso')"],
        }
        with self.assertRaisesRegex(ToolExecutionError, "stderr"):
            run_local_tool(stderr_only, {"name": "Mary"}, self.root)
        oversized = {
            **tool,
            "arguments": ["-c", f"print('x'*{MAX_TOOL_OUTPUT_BYTES + 1})"],
        }
        with self.assertRaisesRegex(ToolExecutionError, "64 KiB"):
            run_local_tool(oversized, {"name": "Mary"}, self.root)
        timed = {**tool, "arguments": ["-c", "import time; time.sleep(2)"], "timeout_seconds": 1}
        with self.assertRaisesRegex(ToolExecutionError, "timeout"):
            run_local_tool(timed, {"name": "Mary"}, self.root)

    def test_tool_persistence_selection_and_mcp_thread_config(self):
        database = initialize_workspace(self.settings)
        conversation_id = database.create_conversation(
            "Tools", "codex", "gpt-test", self.settings.work_dir
        )
        tool_id = database.create_tool(
            "consulta_vr",
            "Consulta local",
            {"type": "object"},
            sys.executable,
            ["-V"],
            safety="read_only",
        )
        database.set_conversation_tools(
            conversation_id,
            [tool_id],
            [{"server": "vrwiki", "tool": "buscar"}],
        )
        selected = database.conversation_tools(conversation_id)
        self.assertEqual(selected["dynamic"], [tool_id])
        self.assertEqual(selected["mcp"], [{"server": "vrwiki", "tool": "buscar"}])
        config = mcp_thread_config(
            selected["mcp"],
            ["vrwiki", "outro"],
            {
                "vrwiki": {"command": "vrwiki.exe"},
                "outro": {"url": "https://example.com/mcp"},
            },
        )
        self.assertTrue(config["mcp_servers"]["vrwiki"]["enabled"])
        self.assertEqual(config["mcp_servers"]["vrwiki"]["enabled_tools"], ["buscar"])
        self.assertEqual(config["mcp_servers"]["vrwiki"]["command"], "vrwiki.exe")
        self.assertFalse(config["mcp_servers"]["outro"]["enabled"])

    def test_deferred_conversation_configures_tools_without_empty_branch(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        provider = MagicMock()
        orchestrator.providers["codex"] = provider
        tool_id = database.create_tool(
            "consulta_slash",
            "Consulta selecionada pela paleta",
            {"type": "object"},
            sys.executable,
            ["-V"],
            safety="read_only",
        )
        conversation_id = orchestrator.new_conversation(
            "codex", defer_provider_start=True
        )
        provider.start_conversation.assert_not_called()
        same_id = orchestrator.configure_tools(
            conversation_id,
            [tool_id],
            [{"server": "vrwiki", "tool": "buscar"}],
        )
        self.assertEqual(same_id, conversation_id)
        self.assertEqual(
            database.conversation_tools(conversation_id),
            {
                "dynamic": [tool_id],
                "mcp": [{"server": "vrwiki", "tool": "buscar"}],
            },
        )
        database.add_message(conversation_id, "user", "Conversa iniciada")
        with patch.object(orchestrator, "clone", return_value="branch-id") as clone:
            branch_id = orchestrator.configure_tools(conversation_id, [], [])
        self.assertEqual(branch_id, "branch-id")
        clone.assert_called_once()

    def test_local_portuguese_spellcheck_ignores_technical_text_and_persists_words(self):
        dictionary = self.settings.root / "state" / "spellcheck.json"
        checker = LocalSpellChecker(dictionary, ["VRMaster"])
        issues = [issue.word.casefold() for issue in checker.misspellings(
            "Conversa com errro em https://vr.local e `git status` no VRMaster"
        )]
        self.assertIn("errro", issues)
        self.assertNotIn("vrmaster", issues)
        accent_issue = checker.misspellings("correcao")[0]
        self.assertEqual(accent_issue.suggestions[0], "correção")
        checker.add_word("MaryLocal")
        reloaded = LocalSpellChecker(dictionary)
        self.assertNotIn("marylocal", [issue.word.casefold() for issue in reloaded.misspellings("MaryLocal")])

    def test_live_spellcheck_does_not_calculate_expensive_suggestions(self):
        from PySide6.QtWidgets import QApplication

        calls: list[bool] = []

        class ProbeChecker:
            def misspellings(self, _text, *, include_suggestions=True):
                calls.append(include_suggestions)
                return []

        application = QApplication.instance() or QApplication([])
        editor = SpellcheckPlainTextEdit(ProbeChecker())
        editor.setPlainText("Texto digitado sem bloquear a interface")
        application.processEvents()

        self.assertTrue(calls)
        self.assertFalse(any(calls))
        editor.close()

    def test_model_picker_ranks_favorites_and_ctrl_shortcut_target(self):
        from PySide6.QtWidgets import QApplication, QListWidget

        class FavoriteSettings:
            def value(self, *_args):
                return ["claude:claude-favorite"]

        application = QApplication.instance() or QApplication([])
        picker = ModelPickerCombo()
        picker._settings = FavoriteSettings()
        picker.set_provider_models(
            "codex",
            [{"id": "gpt-default", "displayName": "GPT", "isDefault": True}],
        )
        picker.set_provider_models(
            "claude",
            [{"id": "claude-favorite", "displayName": "Claude", "isDefault": False}],
        )
        selected = []
        picker.providerModelSelected.connect(lambda provider, model: selected.append((provider, model)))
        picker._select_ranked_model(0)
        application.processEvents()
        self.assertEqual(selected, [("claude", "claude-favorite")])
        picker.close()

    def test_model_picker_keeps_active_provider_catalog_order_for_shortcuts(self):
        from PySide6.QtWidgets import QApplication

        class EmptySettings:
            def value(self, *_args):
                return []

        application = QApplication.instance() or QApplication([])
        picker = ModelPickerCombo()
        picker._settings = EmptySettings()
        picker.set_active_provider("codex")
        picker.set_provider_models(
            "codex",
            [
                {"id": "gpt-sol", "displayName": "Sol", "isDefault": True},
                {"id": "gpt-terra", "displayName": "Terra"},
                {"id": "gpt-luna", "displayName": "Luna"},
            ],
        )
        picker.set_provider_models(
            "claude",
            [{"id": "claude-default", "displayName": "Claude", "isDefault": True}],
        )
        application.processEvents()
        self.assertEqual(
            picker._ranked_models()[:3],
            [
                ("codex", "gpt-sol"),
                ("codex", "gpt-terra"),
                ("codex", "gpt-luna"),
            ],
        )
        picker.close()

    def test_model_picker_stays_open_after_mouse_click(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import (
            QApplication,
            QListWidget,
            QTabBar,
            QVBoxLayout,
            QWidget,
        )

        application = QApplication.instance() or QApplication([])
        host = QWidget()
        host.resize(640, 480)
        layout = QVBoxLayout(host)
        picker = ModelPickerCombo()
        picker.set_provider_models(
            "codex",
            [{"id": "gpt-test", "displayName": "GPT Test", "isDefault": True}],
        )
        picker.set_provider_models(
            "claude",
            [
                {"id": "claude-opus", "displayName": "Claude Opus"},
                {
                    "id": "claude-sonnet",
                    "displayName": "Claude Sonnet",
                    "isDefault": True,
                },
            ],
        )
        picker.addItem("GPT Test", "gpt-test")
        layout.addWidget(picker)
        selected: list[tuple[str, str]] = []
        picker.providerModelSelected.connect(
            lambda provider, model: selected.append((provider, model))
        )
        host.show()
        application.processEvents()
        top_levels_before = set(application.topLevelWidgets())

        QTest.mouseClick(picker, Qt.LeftButton)
        QTest.qWait(120)

        self.assertIsNotNone(picker._model_popup)
        self.assertTrue(picker._model_popup.isVisible())
        self.assertFalse(picker._model_popup.isWindow())
        self.assertEqual(set(application.topLevelWidgets()), top_levels_before)

        QTest.mouseClick(picker, Qt.LeftButton)
        QTest.qWait(30)
        self.assertIsNone(picker._model_popup)
        QTest.mouseClick(picker, Qt.LeftButton)
        QTest.qWait(80)
        self.assertIsNotNone(picker._model_popup)
        self.assertTrue(picker._model_popup.isVisible())

        provider_tabs = picker._model_popup.findChild(QTabBar, "modelProviderTabs")
        self.assertEqual(provider_tabs.width(), 56)
        self.assertEqual(provider_tabs.iconSize().width(), 26)
        self.assertTrue(
            all(
                provider_tabs.tabRect(index).width() == provider_tabs.width()
                for index in range(provider_tabs.count())
            )
        )
        self.assertEqual(
            [provider_tabs.tabText(index) for index in range(provider_tabs.count())],
            ["Favoritos", "Codex", "Claude", "OpenCode"],
        )
        self.assertEqual(
            provider_tabs.accessibleName(),
            "Filtrar modelos por provedor",
        )
        QTest.mouseClick(
            provider_tabs,
            Qt.LeftButton,
            pos=provider_tabs.tabRect(2).center(),
        )
        QTest.qWait(30)
        model_list = picker._model_popup.findChild(QListWidget, "modelPickerList")
        claude_item = next(
            model_list.item(index)
            for index in range(model_list.count())
            if model_list.item(index).data(Qt.UserRole)
            == ("claude", "claude-opus")
        )
        QTest.mouseClick(model_list.itemWidget(claude_item), Qt.LeftButton)
        QTest.qWait(30)
        self.assertEqual(selected, [("claude", "claude-opus")])
        self.assertIsNone(picker._model_popup)
        host.close()

    def test_model_picker_does_not_show_transient_native_child_windows(self):
        from PySide6.QtCore import QEvent, QObject, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

        application = QApplication.instance() or QApplication([])
        host = QWidget()
        host.resize(640, 480)
        layout = QVBoxLayout(host)
        picker = ModelPickerCombo()
        picker.set_provider_models(
            "codex",
            [{"id": "gpt-test", "displayName": "GPT Test", "isDefault": True}],
        )
        picker.addItem("GPT Test", "gpt-test")
        layout.addWidget(picker)
        host.show()
        application.processEvents()
        transient_windows: list[tuple[str, str]] = []

        class NativeChildShowRecorder(QObject):
            def eventFilter(self, watched, event):  # noqa: N802 - Qt API
                if (
                    event.type() == QEvent.Show
                    and isinstance(watched, QWidget)
                    and watched.isWindow()
                    and watched.objectName().startswith("model")
                ):
                    transient_windows.append(
                        (watched.metaObject().className(), watched.objectName())
                    )
                return False

        recorder = NativeChildShowRecorder()
        application.installEventFilter(recorder)
        try:
            QTest.mouseClick(picker, Qt.LeftButton)
            QTest.qWait(120)
        finally:
            application.removeEventFilter(recorder)
            host.close()

        self.assertEqual(transient_windows, [])

    def test_main_window_model_picker_is_anchored_without_native_window(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QListWidget

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.model_combo.set_provider_models(
                "codex",
                [{"id": "gpt-test", "displayName": "GPT Test", "isDefault": True}],
            )
            window.model_combo.clear()
            window.model_combo.addItem("GPT Test", "gpt-test")
            application.processEvents()
            top_levels_before = set(application.topLevelWidgets())

            QTest.mouseClick(window.model_combo, Qt.LeftButton)
            QTest.qWait(100)

            panel = window.model_combo._model_popup
            self.assertIsNotNone(panel)
            self.assertEqual(panel.objectName(), "modelPickerPopup")
            self.assertIs(panel.parentWidget(), window)
            self.assertFalse(panel.isWindow())
            self.assertEqual(set(application.topLevelWidgets()), top_levels_before)
            anchor_top = window.model_combo.mapTo(window, QPoint(0, 0)).y()
            self.assertLess(panel.geometry().bottom(), anchor_top)
            self.assertLessEqual(anchor_top - panel.geometry().bottom(), 8)
            self.assertGreaterEqual(panel.width(), 440)

            QTest.mouseClick(window.model_combo, Qt.LeftButton)
            QTest.qWait(100)
            self.assertIsNone(window.model_combo._model_popup)

            QTest.mouseClick(window.model_combo, Qt.LeftButton)
            QTest.qWait(100)
            model_list = window.model_combo._model_popup.findChild(
                QListWidget,
                "modelPickerList",
            )
            selected_item = next(
                model_list.item(index)
                for index in range(model_list.count())
                if model_list.item(index).data(Qt.UserRole) == ("codex", "gpt-test")
            )
            window._ensure_draft_conversation = lambda: None
            QTest.mouseClick(model_list.itemWidget(selected_item), Qt.LeftButton)
            QTest.qWait(100)
            self.assertIsNone(window.model_combo._model_popup)
            self.assertLessEqual(window.composer_card.maximumHeight(), 156)
        finally:
            window.close()

    def test_model_picker_loads_idle_provider_when_its_tab_is_opened(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QTabBar, QVBoxLayout, QWidget

        application = QApplication.instance() or QApplication([])
        host = QWidget()
        layout = QVBoxLayout(host)
        picker = ModelPickerCombo()
        picker.set_provider_models(
            "codex",
            [{"id": "gpt-test", "displayName": "GPT Test", "isDefault": True}],
        )
        picker.addItem("GPT Test", "gpt-test")
        requested: list[str] = []
        picker.retryRequested.connect(requested.append)
        layout.addWidget(picker)
        host.show()
        application.processEvents()

        QTest.mouseClick(picker, Qt.LeftButton)
        QTest.qWait(80)
        provider_tabs = picker._model_popup.findChild(QTabBar, "modelProviderTabs")
        QTest.mouseClick(
            provider_tabs,
            Qt.LeftButton,
            pos=provider_tabs.tabRect(2).center(),
        )
        QTest.qWait(30)

        self.assertEqual(requested, ["claude"])
        self.assertTrue(picker._model_popup.isVisible())
        picker._model_popup.close()
        host.close()

    def test_model_picker_legacy_group_is_keyboard_accessible_and_closes_on_host_resize(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QListWidget, QVBoxLayout, QWidget

        application = QApplication.instance() or QApplication([])
        host = QWidget()
        layout = QVBoxLayout(host)
        picker = ModelPickerCombo()
        picker.set_provider_models(
            "codex",
            [
                {
                    "id": "gpt-5.6-sol",
                    "displayName": "GPT-5.6-Sol",
                    "isDefault": True,
                },
                {"id": "gpt-5.5", "displayName": "GPT-5.5"},
            ],
        )
        picker.addItem("GPT-5.6-Sol", "gpt-5.6-sol")
        layout.addWidget(picker)
        host.show()
        application.processEvents()

        QTest.mouseClick(picker, Qt.LeftButton)
        QTest.qWait(80)
        model_list = picker._model_popup.findChild(QListWidget, "modelPickerList")
        self.assertFalse(
            any(
                model_list.item(index).data(Qt.UserRole) == ("codex", "gpt-5.5")
                for index in range(model_list.count())
            )
        )
        legacy_item = next(
            model_list.item(index)
            for index in range(model_list.count())
            if model_list.item(index).data(Qt.UserRole) == ("legacy", "")
        )
        self.assertEqual(legacy_item.text(), "")
        self.assertEqual(
            legacy_item.data(Qt.AccessibleTextRole),
            "Modelos legados",
        )
        self.assertTrue(legacy_item.flags() & Qt.ItemIsSelectable)
        model_list.setCurrentItem(legacy_item)
        model_list.setFocus()
        QTest.keyClick(model_list, Qt.Key_Return)
        QTest.qWait(30)
        self.assertTrue(
            any(
                model_list.item(index).data(Qt.UserRole) == ("codex", "gpt-5.5")
                for index in range(model_list.count())
            )
        )

        host.resize(700, 520)
        QTest.qWait(20)
        self.assertIsNone(picker._model_popup)
        host.close()

    def test_rounded_popup_mask_clips_all_native_window_corners(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        dialog = RoundedPopupDialog(radius=18)
        dialog.resize(220, 180)
        dialog.show()
        application.processEvents()
        mask = dialog.mask()
        for point in (
            QPoint(0, 0),
            QPoint(dialog.width() - 1, 0),
            QPoint(0, dialog.height() - 1),
            QPoint(dialog.width() - 1, dialog.height() - 1),
        ):
            self.assertFalse(mask.contains(point))
        self.assertTrue(mask.contains(QPoint(dialog.width() // 2, dialog.height() // 2)))
        dialog.close()

    def test_composer_enter_submits_and_shift_enter_inserts_newline(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextCursor
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        checker = LocalSpellChecker(self.settings.state_dir / "composer-spellcheck.json")
        editor = SpellcheckPlainTextEdit(checker)
        submitted = []
        editor.submitRequested.connect(lambda: submitted.append(editor.toPlainText()))
        editor.setPlainText("Mensagem")
        editor.moveCursor(QTextCursor.End)

        QTest.keyClick(editor, Qt.Key_Return)
        application.processEvents()
        self.assertEqual(submitted, ["Mensagem"])
        self.assertEqual(editor.toPlainText(), "Mensagem")

        QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
        application.processEvents()
        self.assertEqual(editor.toPlainText(), "Mensagem\n")
        editor.close()

    def test_composer_right_click_suggestion_replaces_misspelled_word(self):
        from PySide6.QtGui import QTextCharFormat, QTextCursor
        from PySide6.QtWidgets import QApplication, QMenu

        application = QApplication.instance() or QApplication([])
        checker = LocalSpellChecker(self.settings.state_dir / "context-spellcheck.json")
        editor = SpellcheckPlainTextEdit(checker)
        editor.setPlainText("correcao")
        cursor = editor.textCursor()
        cursor.setPosition(3)
        menu = QMenu(editor)

        editor._add_spelling_actions(menu, cursor)
        application.processEvents()

        format_ranges = editor.document().firstBlock().layout().formats()
        self.assertTrue(
            any(
                item.format.underlineStyle()
                == QTextCharFormat.SpellCheckUnderline
                for item in format_ranges
            )
        )
        suggestions = [action for action in menu.actions() if action.text() == "correção"]
        self.assertEqual(len(suggestions), 1)
        suggestions[0].trigger()
        self.assertEqual(editor.toPlainText(), "correção")
        editor.close()

    def test_message_edit_forks_at_previous_codex_turn_and_preserves_original(self):
        class FakeProvider:
            def __init__(self):
                self.forks = []

            def available(self):
                return True

            def fork_thread(self, *args):
                self.forks.append(args)
                return "native-fork"

            def start_conversation(self, *_args):
                return "native-new"

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        fake = FakeProvider()
        orchestrator.providers = {"codex": fake}
        source = database.create_conversation(
            "Original",
            "codex",
            "gpt-test",
            self.settings.work_dir / "source",
        )
        database.update_conversation(source, native_id="native-source")
        first = database.add_message(source, "user", "Primeira", turn_id="turn-1")
        database.add_message(source, "assistant", "Resposta", turn_id="turn-1")
        target = database.add_message(source, "user", "Texto original", turn_id="turn-2")
        branch = orchestrator.branch_from_message(source, target, "Texto corrigido")
        self.assertEqual(fake.forks[0][2], "turn-1")
        self.assertEqual(database.get_conversation(branch)["native_id"], "native-fork")
        self.assertEqual(database.messages(source)[-1]["content"], "Texto original")
        self.assertEqual(database.messages(branch)[0]["id"] > first, True)

    def test_claude_archive_is_local_and_trash_restore_purge_preserve_database_until_delete(self):
        class OfflineClaude:
            def available(self):
                return False

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"claude": OfflineClaude()}
        conversation_id = database.create_conversation(
            "Claude local",
            "claude",
            "claude-test",
            self.settings.work_dir / "pending",
        )
        workspace = self.settings.work_dir / conversation_id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "artefato.txt").write_text("preservar", encoding="utf-8")
        database.update_conversation(conversation_id, workspace=str(workspace))
        orchestrator.archive(conversation_id)
        self.assertEqual(database.get_conversation(conversation_id)["archived"], 1)
        orchestrator.unarchive(conversation_id)
        orchestrator.trash(conversation_id)
        trashed = database.get_conversation(conversation_id)
        self.assertTrue(trashed["trashed_at"])
        self.assertTrue(self.settings.resolve_path(trashed["workspace"]).exists())
        orchestrator.restore(conversation_id)
        self.assertTrue(workspace.exists())
        orchestrator.trash(conversation_id)
        orchestrator.purge(conversation_id)
        self.assertIsNone(database.get_conversation(conversation_id))

    def test_purge_restores_trashed_workspace_when_database_delete_fails(self):
        class OfflineClaude:
            def available(self):
                return False

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"claude": OfflineClaude()}
        conversation_id = database.create_conversation(
            "Falha ao excluir",
            "claude",
            "claude-test",
            self.settings.work_dir / "pending",
        )
        workspace = self.settings.work_dir / conversation_id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "preservar.txt").write_text("conteúdo", encoding="utf-8")
        database.update_conversation(conversation_id, workspace=str(workspace))
        orchestrator.trash(conversation_id)
        trashed_path = self.settings.resolve_path(
            database.get_conversation(conversation_id)["workspace"]
        )

        with (
            patch.object(
                database,
                "purge_conversation",
                side_effect=sqlite3.OperationalError("banco bloqueado"),
            ),
            self.assertRaisesRegex(sqlite3.OperationalError, "banco bloqueado"),
        ):
            orchestrator.purge(conversation_id)

        self.assertIsNotNone(database.get_conversation(conversation_id))
        self.assertTrue((trashed_path / "preservar.txt").is_file())

    def test_archived_conversation_can_be_purged_directly_without_trash_state(self):
        class OfflineClaude:
            def available(self):
                return False

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"claude": OfflineClaude()}
        conversation_id = database.create_conversation(
            "Arquivado direto",
            "claude",
            "claude-test",
            self.settings.work_dir / "pending",
        )
        workspace = self.settings.work_dir / conversation_id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "remover.txt").write_text("conteúdo", encoding="utf-8")
        database.update_conversation(
            conversation_id,
            workspace=str(workspace),
            archived=1,
        )
        image_folder = (
            self.settings.root / ".state" / "chat-images" / conversation_id
        )
        image_folder.mkdir(parents=True)
        (image_folder / "anexo.png").write_bytes(b"imagem")

        orchestrator.purge(conversation_id)

        self.assertIsNone(database.get_conversation(conversation_id))
        self.assertFalse(workspace.exists())
        self.assertFalse(image_folder.exists())

        external_workspace = self.old / "projeto-externo-preservado"
        external_workspace.mkdir(parents=True)
        (external_workspace / "preservar.txt").write_text(
            "conteúdo externo",
            encoding="utf-8",
        )
        external_id = database.create_conversation(
            "Arquivado externo",
            "claude",
            "claude-test",
            external_workspace,
        )
        database.update_conversation(external_id, archived=1)

        orchestrator.purge(external_id)

        self.assertIsNone(database.get_conversation(external_id))
        self.assertTrue((external_workspace / "preservar.txt").is_file())

    def test_missing_codex_rollout_does_not_block_local_trash_or_purge(self):
        class MissingRolloutCodex:
            def available(self):
                return True

            def archive_thread(self, native_id):
                raise ProviderError(f"no rollout found for thread id {native_id}")

            def delete_thread(self, native_id):
                raise ProviderError(f"no rollout found for thread id {native_id}")

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"codex": MissingRolloutCodex()}
        conversation_id = database.create_conversation(
            "Rollout ausente",
            "codex",
            "gpt-test",
            self.settings.work_dir / "pending",
        )
        workspace = self.settings.work_dir / conversation_id
        workspace.mkdir(parents=True, exist_ok=True)
        database.update_conversation(
            conversation_id,
            workspace=str(workspace),
            native_id="native-inexistente",
        )

        orchestrator.trash(conversation_id)
        trashed = database.get_conversation(conversation_id)
        self.assertTrue(trashed["trashed_at"])
        self.assertEqual(trashed["native_id"], "")
        orchestrator.purge(conversation_id)
        self.assertIsNone(database.get_conversation(conversation_id))

    def test_provider_archive_failure_does_not_claim_local_success(self):
        class FailingCodex:
            def available(self):
                return True

            def archive_thread(self, _native_id):
                raise ProviderError("network unavailable")

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"codex": FailingCodex()}
        conversation_id = database.create_conversation(
            "Falha remota",
            "codex",
            "gpt-test",
            self.settings.work_dir / "remote-failure",
        )
        database.update_conversation(conversation_id, native_id="native-1")

        with self.assertRaisesRegex(ProviderError, "network unavailable"):
            orchestrator.archive(conversation_id)

        self.assertEqual(database.get_conversation(conversation_id)["archived"], 0)

    def test_archive_compensates_provider_when_local_persistence_fails(self):
        class TrackingCodex:
            def __init__(self):
                self.operations = []

            def available(self):
                return True

            def archive_thread(self, native_id):
                self.operations.append(("archive", native_id))

            def unarchive_thread(self, native_id):
                self.operations.append(("unarchive", native_id))

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        provider = TrackingCodex()
        orchestrator.providers = {"codex": provider}
        conversation_id = database.create_conversation(
            "Compensação",
            "codex",
            "gpt-test",
            self.settings.work_dir / "compensation",
        )
        database.update_conversation(conversation_id, native_id="native-1")

        with (
            patch.object(
                database,
                "update_conversation",
                side_effect=sqlite3.OperationalError("banco bloqueado"),
            ),
            self.assertRaisesRegex(sqlite3.OperationalError, "banco bloqueado"),
        ):
            orchestrator.archive(conversation_id)

        self.assertEqual(
            provider.operations,
            [("archive", "native-1"), ("unarchive", "native-1")],
        )
        self.assertEqual(database.get_conversation(conversation_id)["archived"], 0)

    def test_trash_rolls_workspace_back_when_database_update_fails(self):
        class OfflineClaude:
            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"claude": OfflineClaude()}
        conversation_id = database.create_conversation(
            "Rollback da lixeira",
            "claude",
            "claude-test",
            self.settings.work_dir / "pending",
        )
        workspace = self.settings.work_dir / conversation_id
        workspace.mkdir(parents=True)
        (workspace / "preservar.txt").write_text("conteúdo", encoding="utf-8")
        database.update_conversation(conversation_id, workspace=str(workspace))

        with (
            patch.object(
                database,
                "update_conversation",
                side_effect=sqlite3.OperationalError("banco bloqueado"),
            ),
            self.assertRaisesRegex(sqlite3.OperationalError, "banco bloqueado"),
        ):
            orchestrator.trash(conversation_id)

        self.assertTrue((workspace / "preservar.txt").is_file())
        self.assertFalse(
            (self.settings.root / ".trash" / "conversations" / conversation_id).exists()
        )

    def test_running_conversation_cannot_be_archived_or_sent_twice(self):
        class IdleProvider:
            def available(self):
                return True

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"claude": IdleProvider()}
        conversation_id = database.create_conversation(
            "Em execução",
            "claude",
            "claude-test",
            self.settings.work_dir / "running",
        )
        database.update_conversation(conversation_id, status="running")

        with self.assertRaisesRegex(RuntimeError, "resposta em andamento"):
            orchestrator.send(conversation_id, "duplicada", lambda _event: None)
        with self.assertRaisesRegex(RuntimeError, "Interrompa"):
            orchestrator.archive(conversation_id)
        self.assertEqual(database.messages(conversation_id), [])

    def test_token_usage_is_persisted_for_context_window_and_total(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        conversation_id = database.create_conversation(
            "Uso de contexto",
            "codex",
            "gpt-test",
            self.settings.work_dir / "context-usage",
        )

        orchestrator._handle_event(
            RuntimeEvent(
                conversation_id,
                "token_usage",
                payload={
                    "tokenUsage": {
                        "last": {"totalTokens": 42_000},
                        "total": {"totalTokens": 125_000},
                        "modelContextWindow": 128_000,
                    }
                },
            )
        )
        row = database.get_conversation(conversation_id)
        self.assertEqual(row["context_used_tokens"], 42_000)
        self.assertEqual(row["context_window_tokens"], 128_000)
        self.assertEqual(row["total_processed_tokens"], 125_000)

        orchestrator._handle_event(
            RuntimeEvent(
                conversation_id,
                "token_usage",
                payload={"tokenUsage": {"last": {"totalTokens": 5_000}}},
            )
        )
        row = database.get_conversation(conversation_id)
        self.assertEqual(row["context_used_tokens"], 5_000)
        self.assertEqual(row["total_processed_tokens"], 130_000)

    def test_concurrent_turn_claim_persists_exactly_one_user_message(self):
        database = initialize_workspace(self.settings)
        conversation_id = database.create_conversation(
            "Concorrente",
            "claude",
            "claude-test",
            self.settings.work_dir / "concurrent",
        )
        barrier = threading.Barrier(3)
        outcomes: list[str] = []

        def claim(text: str) -> None:
            barrier.wait()
            try:
                database.begin_user_turn(conversation_id, text)
            except RuntimeError:
                outcomes.append("rejected")
            else:
                outcomes.append("claimed")

        threads = [
            threading.Thread(target=claim, args=(f"mensagem {index}",))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(sorted(outcomes), ["claimed", "rejected"])
        self.assertEqual(len(database.messages(conversation_id)), 1)

    def test_provider_start_failure_rolls_back_pending_user_turn(self):
        class FailingProvider:
            def available(self):
                return True

            def start_conversation(self, *_args):
                raise ProviderError("provider offline")

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        orchestrator.providers = {"claude": FailingProvider()}
        conversation_id = database.create_conversation(
            "Nova conversa",
            "claude",
            "claude-test",
            self.settings.work_dir / "provider-failure",
        )

        with self.assertRaisesRegex(ProviderError, "provider offline"):
            orchestrator.send(conversation_id, "não persistir", lambda _event: None)

        self.assertEqual(database.messages(conversation_id), [])
        self.assertEqual(database.get_conversation(conversation_id)["status"], "idle")

    def test_orchestrator_startup_recovers_conversation_left_running(self):
        database = initialize_workspace(self.settings)
        conversation_id = database.create_conversation(
            "Interrompida",
            "claude",
            "claude-test",
            self.settings.work_dir / "interrupted",
        )
        database.update_conversation(conversation_id, status="running")

        ChatOrchestrator(self.settings, database)

        self.assertEqual(
            database.get_conversation(conversation_id)["status"], "interrupted"
        )
        recovered = database.latest_event(conversation_id, "turn_recovered")
        self.assertIsNotNone(recovered)

    def test_legacy_workspace_outside_trabalho_mary_is_preserved_when_chat_is_deleted(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        legacy_workspace = self.settings.root / "legacy-chat"
        legacy_workspace.mkdir(parents=True, exist_ok=True)
        artifact = legacy_workspace / "nao-apagar.txt"
        artifact.write_text("preservar", encoding="utf-8")
        conversation_id = database.create_conversation(
            "Chat legado",
            "claude",
            "claude-test",
            legacy_workspace,
        )

        orchestrator.trash(conversation_id)
        trashed = database.get_conversation(conversation_id)
        self.assertTrue(trashed["trashed_at"])
        self.assertTrue(artifact.exists())
        orchestrator.purge(conversation_id)
        self.assertIsNone(database.get_conversation(conversation_id))
        self.assertTrue(artifact.exists())

    def test_movidesk_recognizes_current_localized_article_routes(self):
        self.assertTrue(
            MovideskSync._is_article_url(
                "https://vrsoftware.movidesk.com/kb/article/284297/bem-vindo"
            )
        )
        self.assertTrue(
            MovideskSync._is_article_url(
                "https://vrsoftware.movidesk.com/kb/pt-br/article/284297/bem-vindo"
            )
        )
        database = MaryDatabase(self.settings.database_path)
        sync = MovideskSync(self.settings, database)
        sample_urls = [
            (
                "289782",
                "https://vrsoftware.movidesk.com/kb/pt-br/article/"
                "289782/erro-ao-finalizar-venda-com-tef-12-erro-pinpad"
                "?menuId=29714-80207-289782&ticketId=&q=",
            ),
            (
                "406116",
                "https://vrsoftware.movidesk.com/kb/pt-br/article/"
                "406116/codigos-de-estabelecimento-das-adquirentes"
                "?menuId=29701-80258-406116&ticketId=&q=",
            ),
            (
                "289953",
                "https://vrsoftware.movidesk.com/kb/pt-br/article/"
                "289953/como-realizar-a-importacao-de-nfe-de-saida-pelo-vr-adm"
                "?menuId=29706-131526-289953&ticketId=&q=",
            ),
        ]
        for source_id, url in sample_urls:
            canonical = sync._canonical_kb_url(url)
            self.assertTrue(sync._is_article_url(canonical))
            self.assertEqual(sync._source_id(canonical, ""), source_id)
            self.assertEqual(urllib.parse.urlsplit(canonical).query, "")
        self.assertEqual(
            sync._normalized_host(
                "http://vrsoftware.movidesk.com:80/kb/pt-br/category/pdv"
            ),
            "vrsoftware.movidesk.com",
        )
        self.assertTrue(
            sync._is_category_url(
                "https://vrsoftware.movidesk.com/kb/pt-br/category/pdv"
            )
        )
        self.assertEqual(
            sync._canonical_kb_url(
                "https://vrsoftware.movidesk.com/kb/pt-br/category/zebra TLP"
            ),
            "https://vrsoftware.movidesk.com/kb/pt-br/category/zebra%20TLP",
        )
        self.assertEqual(
            sync._canonical_kb_url(
                "https://vrsoftware.movidesk.com/kb/pt-br/category/emissão"
            ),
            "https://vrsoftware.movidesk.com/kb/pt-br/category/emiss%C3%A3o",
        )

    def test_movidesk_builds_title_from_article_slug_when_heading_is_empty(self):
        self.assertEqual(
            MovideskSync._fallback_title(
                "https://vrsoftware.movidesk.com/kb/pt-br/article/"
                "289953/como-realizar-a-importacao-de-nfe-de-saida-pelo-vr-adm"
            ),
            "Como realizar a importacao de nfe de saida pelo vr adm",
        )
        self.assertEqual(
            MovideskSync._fallback_title(
                "https://vrsoftware.movidesk.com/kb/pt-br/article/289953/"
            ),
            "Article",
        )

    def test_movidesk_walks_javascript_pagination(self):
        pages = [
            ["https://vrsoftware.movidesk.com/kb/pt-br/article/1/a"],
            ["https://vrsoftware.movidesk.com/kb/pt-br/article/2/b"],
            ["https://vrsoftware.movidesk.com/kb/pt-br/article/3/c"],
        ]

        class ResponseWait:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class ResultLocator:
            def __init__(self, page):
                self.page = page

            def evaluate_all(self, _script):
                return pages[self.page.index]

        class NextLocator:
            def __init__(self, page):
                self.page = page

            def count(self):
                return 1

            @property
            def last(self):
                return self

            def get_attribute(self, _name):
                return (
                    "button-pagination button-pagination-disabled"
                    if self.page.index == len(pages) - 1
                    else "button-pagination"
                )

            def is_disabled(self):
                return self.page.index == len(pages) - 1

            def click(self):
                self.page.index += 1

        class FakePage:
            url = "https://vrsoftware.movidesk.com/kb/pt-br/category/pdv"

            def __init__(self):
                self.index = 0

            def locator(self, selector):
                if selector == MovideskSync.RESULT_LINK_SELECTOR:
                    return ResultLocator(self)
                return NextLocator(self)

            def expect_response(self, *_args, **_kwargs):
                return ResponseWait()

            def wait_for_function(self, *_args, **_kwargs):
                return None

        database = MaryDatabase(self.settings.database_path)
        sync = MovideskSync(self.settings, database)
        links, page_count = sync._paginated_result_links(FakePage())
        self.assertEqual(links, [url for page_urls in pages for url in page_urls])
        self.assertEqual(page_count, 3)

    def test_movidesk_scans_all_discovered_categories(self):
        database = MaryDatabase(self.settings.database_path)
        sync = MovideskSync(self.settings, database)
        root = "https://vrsoftware.movidesk.com/kb"
        category_one = f"{root}/pt-br/category/administrativo"
        category_two = f"{root}/pt-br/category/pdv"
        article_one = f"{root}/pt-br/article/1/primeiro"
        article_two = f"{root}/pt-br/article/2/segundo"
        article_three = f"{root}/pt-br/article/3/terceiro"
        category_pages = {
            category_one: [article_two, category_two],
            category_two: [article_three],
        }
        with (
            patch.object(
                sync,
                "_page_links",
                return_value=[article_one, category_one],
            ),
            patch.object(
                sync,
                "_paginated_result_links",
                return_value=([], 0),
            ),
            patch.object(sync, "_storage_cookie_header", return_value="session"),
            patch.object(
                sync,
                "_http_page_links",
                side_effect=lambda url, _cookie: category_pages[url],
            ) as fetch,
        ):
            result = sync._discover_articles(SimpleNamespace(url=root), limit=None)
        self.assertEqual(set(result), {article_one, article_two, article_three})
        self.assertEqual(
            {item.args[0] for item in fetch.call_args_list},
            {category_one, category_two},
        )

    def test_ui_uses_dedicated_login_then_retries_headless_sync(self):
        messages = []
        window = SimpleNamespace(
            settings=self.settings,
            database=MagicMock(),
            _sync_progress=messages.append,
        )
        sync = MagicMock()
        sync.sync.side_effect = [
            MovideskInteractiveLoginRequired("MFA"),
            "authenticated",
        ]
        with patch(
            "vrsoft_extractor.mary.ui.MovideskSync",
            return_value=sync,
        ):
            result = MainWindow._sync_kb_with_auth_fallback(window)
        self.assertEqual(result, "authenticated")
        self.assertEqual(
            sync.sync.call_args_list,
            [call(headed=False), call(headed=False)],
        )
        sync.login.assert_called_once_with()
        self.assertTrue(any("Abrindo uma janela" in message for message in messages))

    def test_ui_visible_kb_action_logs_in_before_headless_sync(self):
        window = SimpleNamespace(
            settings=self.settings,
            database=MagicMock(),
            _sync_progress=MagicMock(),
        )
        sync = MagicMock()
        sync.sync.return_value = "authenticated"
        with patch(
            "vrsoft_extractor.mary.ui.MovideskSync",
            return_value=sync,
        ):
            result = MainWindow._sync_kb_with_auth_fallback(window, headed=True)
        self.assertEqual(result, "authenticated")
        sync.login.assert_called_once_with()
        sync.sync.assert_called_once_with(headed=False)

    def test_ui_requires_confirmation_before_starting_kb_sync(self):
        operation_runner = MagicMock()
        kb_sync = MagicMock(return_value="authenticated")
        window = SimpleNamespace(
            _run_sync=operation_runner,
            _sync_kb_with_auth_fallback=kb_sync,
        )
        window._confirm_kb_session_takeover = lambda: (
            MainWindow._confirm_kb_session_takeover(window)
        )

        with patch(
            "vrsoft_extractor.mary.ui.ConfirmDialog.ask",
            return_value=False,
        ) as question:
            MainWindow.sync_kb(window)

        question.assert_called_once()
        operation_runner.assert_not_called()

        with patch(
            "vrsoft_extractor.mary.ui.ConfirmDialog.ask",
            return_value=True,
        ):
            MainWindow.sync_kb(window, headed=True)

        operation_runner.assert_called_once()
        label, operation = operation_runner.call_args.args
        self.assertEqual(label, "KB")
        self.assertEqual(operation(), "authenticated")
        kb_sync.assert_called_once_with(
            headed=True,
            allow_session_takeover=True,
        )

    def test_movidesk_only_confirms_existing_session_when_authorized(self):
        class Field:
            def __init__(self, count=1):
                self._count = count
                self.filled = ""
                self.clicked = False

            @property
            def first(self):
                return self

            @property
            def last(self):
                return self

            def count(self):
                return self._count

            def fill(self, value):
                self.filled = value

            def click(self):
                self.clicked = True

        class ConflictPage:
            def __init__(self):
                self.url = MovideskSync.LOGIN_PATH
                self.password = Field()
                self.user = Field()
                self.submit = Field()
                self.notice = Field()
                self.confirm = Field()

            def locator(self, selector):
                if selector == "input[type=password]":
                    return self.password
                if "input[type=email]" in selector:
                    return self.user
                if selector == MovideskSync.SESSION_CONFLICT_CONFIRM_SELECTOR:
                    self.confirm.is_visible = lambda: bool(self.confirm._count)
                    return self.confirm
                return self.submit

            def wait_for_load_state(self, *_args, **_kwargs):
                return None

            def wait_for_function(self, *_args, **_kwargs):
                return None

            def is_closed(self):
                return False

            def finish_login_when_confirmed(self):
                original_click = self.confirm.click

                def confirm_and_finish_login():
                    original_click()
                    self.url = "https://vrsoftware.movidesk.com/Home"
                    self.password._count = 0

                self.confirm.click = confirm_and_finish_login

        database = MaryDatabase(self.settings.database_path)
        with patch.dict(
            os.environ,
            {"MOVIDESK_EMAIL": "user@example.com", "MOVIDESK_PASSWORD": "secret"},
        ):
            blocked_page = ConflictPage()
            blocked_sync = MovideskSync(self.settings, database)
            with self.assertRaisesRegex(
                MovideskInteractiveLoginRequired,
                "outra sessão aberta",
            ):
                blocked_sync._ensure_login(blocked_page)
            self.assertFalse(blocked_page.confirm.clicked)

            authorized_page = ConflictPage()
            authorized_page.finish_login_when_confirmed()
            authorized_sync = MovideskSync(
                self.settings,
                database,
                allow_session_takeover=True,
            )
            authorized_sync._ensure_login(authorized_page)
            self.assertTrue(authorized_page.confirm.clicked)
            self.assertEqual(
                authorized_page.url,
                "https://vrsoftware.movidesk.com/Home",
            )

            residual_page = ConflictPage()
            residual_page.confirm._count = 0
            self.assertFalse(
                authorized_sync._session_conflict_pending(residual_page)
            )
            self.assertFalse(
                authorized_sync._confirm_session_takeover(residual_page)
            )

    def test_movidesk_dynamic_wait_avoids_networkidle_delay(self):
        page = MagicMock()
        MovideskSync._wait_for_dynamic_content(page)
        page.wait_for_selector.assert_called_once()
        page.wait_for_timeout.assert_called_once_with(350)
        page.wait_for_load_state.assert_not_called()

    def test_movidesk_retries_transient_category_timeout(self):
        database = MaryDatabase(self.settings.database_path)
        sync = MovideskSync(self.settings, database)
        response = MagicMock()
        response.geturl.return_value = (
            "https://vrsoftware.movidesk.com/kb/pt-br/category/pdv"
        )
        response.read.return_value = (
            b"<html><a href='/kb/pt-br/article/123/teste'>Teste</a></html>"
        )
        context_response = MagicMock()
        context_response.__enter__.return_value = response
        with (
            patch(
                "vrsoft_extractor.mary.movidesk.urllib.request.urlopen",
                side_effect=[TimeoutError("timeout"), context_response],
            ) as urlopen,
            patch("vrsoft_extractor.mary.movidesk.time.sleep") as sleep,
        ):
            links = sync._http_page_links(
                "https://vrsoftware.movidesk.com/kb/pt-br/category/pdv",
                "Bearer=secret",
            )
        self.assertEqual(links, ["/kb/pt-br/article/123/teste"])
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1.5)

    def test_movidesk_reports_when_visible_login_window_is_closed(self):
        page = MagicMock()
        page.wait_for_function.side_effect = RuntimeError("closed")
        page.is_closed.return_value = True
        with self.assertRaisesRegex(
            MovideskInteractiveLoginRequired,
            "fechada antes da conclusão",
        ):
            MovideskSync._wait_for_login_completion(page)

    def test_ui_palette_meets_wcag_contrast_targets(self):
        text_pairs = (
            (ACCESSIBLE_ORANGE, "#FFFFFF"),
            (BRAND_NAVY, BACKGROUND),
            (TEXT_MUTED, "#FFFFFF"),
            (DISABLED_TEXT, DISABLED_BACKGROUND),
            (STATUS_GOOD, "#FFFFFF"),
            (STATUS_WARN, "#FFFFFF"),
            (FOCUS_DARK, "#FFFFFF"),
            (LINK_VISITED, "#FFFFFF"),
        )
        for foreground, background in text_pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(
                    self._contrast_ratio(foreground, background),
                    4.5,
                )
        self.assertGreaterEqual(
            self._contrast_ratio(SCROLLBAR_HANDLE, SCROLLBAR_TRACK),
            3.0,
        )

    def test_message_box_uses_accessible_light_palette(self):
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

        application = QApplication.instance() or QApplication([])
        apply_application_theme(application)
        dialog = QMessageBox(
            QMessageBox.Critical,
            "VR Norte Studio",
            "Falha de validação com texto longo.",
            QMessageBox.Ok,
        )
        try:
            dialog.show()
            application.processEvents()
            label = dialog.findChild(QLabel, "qt_msgbox_label")
            self.assertIsNotNone(label)
            foreground = label.palette().color(QPalette.WindowText).name()
            background = dialog.palette().color(QPalette.Window).name()
            self.assertGreaterEqual(
                self._contrast_ratio(foreground, background),
                4.5,
            )
            self.assertEqual(background.lower(), BACKGROUND.lower())
        finally:
            dialog.close()

    def test_chat_header_is_responsive_and_default_effort_is_hidden(self):
        from PySide6.QtWidgets import QApplication, QLabel

        initialize_workspace(self.settings)
        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            from PySide6.QtCore import QPoint, QSize

            for width, height in ((1120, 700), (1366, 768), (1920, 1080)):
                with self.subTest(size=(width, height)):
                    window.resize(width, height)
                    window.show()
                    window._navigate(window.pages["Chat VR"])
                    application.processEvents()
                    self.assertFalse(hasattr(window, "chat_title"))
                    message_center = (
                        window.message_column.mapTo(window, QPoint(0, 0)).x()
                        + window.message_column.width() / 2
                    )
                    composer_center = (
                        window.composer_card.mapTo(window, QPoint(0, 0)).x()
                        + window.composer_card.width() / 2
                    )
                    self.assertLessEqual(abs(message_center - composer_center), 2)
                    self.assertLessEqual(window.message_column.width(), 920)
                    self.assertLess(
                        window.model_combo.mapTo(window, QPoint(0, 0)).x()
                        + window.model_combo.width(),
                        window.effort_combo.mapTo(window, QPoint(0, 0)).x(),
                    )
                    self.assertLess(
                        window.effort_combo.mapTo(window, QPoint(0, 0)).x()
                        + window.effort_combo.width(),
                        window.approval_combo.mapTo(window, QPoint(0, 0)).x(),
                    )
                    self.assertLess(
                        window.approval_combo.mapTo(window, QPoint(0, 0)).x()
                        + window.approval_combo.width(),
                        window.vr_flow_button.mapTo(window, QPoint(0, 0)).x(),
                    )
                    self.assertLess(
                        window.vr_flow_button.mapTo(window, QPoint(0, 0)).x()
                        + window.vr_flow_button.width(),
                        window.send_button.mapTo(window, QPoint(0, 0)).x(),
                    )
                    self.assertLessEqual(window.composer_card.width(), 920)
                    self.assertLessEqual(window.composer_card.height(), 156)
                    if width == 1120:
                        self.assertTrue(window.nav_collapsed)
                        self.assertGreaterEqual(window.composer_card.width(), 540)
            self.assertTrue(window.chat_empty_state.isVisible())
            self.assertEqual(
                window.chat_empty_state.findChild(QLabel, "chatEmptyTitle").text(),
                "O que vamos construir com a VR?",
            )
            self.assertTrue(window.chat_context_panel.isHidden())
            self.assertTrue(window.provider_combo.isHidden())
            self.assertTrue(window.tier_combo.isHidden())
            self.assertFalse(window.approval_combo.isHidden())
            self.assertFalse(window.vr_flow_button.isHidden())
            self.assertEqual(window.chat_header_title.text(), "Nova conversa")
            self.assertEqual(window.chat_header_project.text(), "Projetos")
            self.assertTrue(window.chat_header_meta.isHidden())
            self.assertNotIn("Todos os projetos", window.chat_header_meta.text())
            self.assertTrue(window.composer_card.isAncestorOf(window.chat_status))
            self.assertTrue(window.conversation_menu_button.isHidden())
            self.assertFalse(window.surface_toggle_button.isHidden())
            window.chat_status.setText("Executando…")
            self.assertEqual(window.chat_status.property("statusKind"), "running")
            window.chat_status.setText("Falha ao executar")
            self.assertEqual(window.chat_status.property("statusKind"), "error")
            window.chat_status.setText("Pronto")
            window.vr_flow_button.setChecked(True)
            self.assertTrue(window.vr_flow_button.isChecked())
            self.assertIn("base local ativa", window.vr_flow_button.toolTip())
            self.assertIn("Modo", window.vr_flow_button.toolTip())
            self.assertEqual(window.composer.placeholderText(), "Digite uma mensagem…")
            self.assertGreater(window.vr_flow_button._glow_animation.duration(), 0)
            self.assertEqual(window.vr_flow_button._glow_animation.loopCount(), 1)
            window.draft_orchestration = window.draft_orchestration.__class__(mode="off")
            window._sync_orchestration_mode_ui(
                window.draft_orchestration, animate=False
            )
            self.assertEqual(window.composer_glow.mode(), "off")
            window.vr_flow_button.setChecked(False)
            self.assertIn("base local inativa", window.vr_flow_button.toolTip())
            self.assertIn("Modo", window.vr_flow_button.toolTip())
            self.assertEqual(window.composer_glow.mode(), "off")
            window.vr_flow_button.setChecked(True)
            self.assertEqual(window.composer_glow.mode(), "off")
            self.assertTrue(window.mode_combo.isHidden())
            self.assertTrue(window.options_button.isHidden())
            self.assertEqual(window.mode_combo.count(), 1)
            self.assertEqual(window.mode_combo.currentData(), "default")
            self.assertFalse(window.send_button.icon().isNull())
            self.assertFalse(window.stop_button.icon().isNull())
            self.assertTrue(
                all(
                    not window.approval_combo.itemIcon(index).isNull()
                    for index in range(window.approval_combo.count())
                )
            )
            self.assertFalse(provider_icon("codex").isNull())
            self.assertFalse(provider_icon("claude").isNull())
            self.assertFalse(provider_icon("opencode").isNull())
            self.assertFalse(window.model_combo.itemIcon(0).isNull())
            self.assertEqual(window.new_chat_button.text(), "")
            self.assertEqual(window.new_chat_button.accessibleName(), "Novo chat")
            self.assertFalse(window.new_chat_button.icon().isNull())
            self.assertFalse(window.scheduled_placeholder_button.icon().isNull())
            self.assertFalse(window.plugins_placeholder_button.icon().isNull())
            self.assertEqual(window.nav_toggle_button.size(), QSize(40, 40))
            self.assertEqual(window.chat_sidebar_toggle_button.size(), QSize(40, 40))
            self.assertEqual(window.nav_toggle_button.objectName(), "navSidebarToggle")
            self.assertEqual(
                window.chat_sidebar_toggle_button.objectName(),
                "chatSidebarToggle",
            )
            self.assertEqual(
                window.orchestration_trace_close_button.objectName(),
                "traceSidebarToggle",
            )
            self.assertEqual(
                window.vr_agents_toggle_button.objectName(),
                "agentSidebarToggle",
            )
            self.assertEqual(
                window.knowledge_expand_button.objectName(),
                "knowledgeExpandToggle",
            )
            self.assertGreaterEqual(
                window.chat_header.height(),
                window.chat_sidebar_toggle_button.height(),
            )
            self.assertEqual(window.conversation_search.placeholderText(), "Buscar")
            self.assertFalse(window.scheduled_placeholder_button.isEnabled())
            self.assertFalse(window.plugins_placeholder_button.isEnabled())
            self.assertFalse(hasattr(window, "conversation_state_tabs"))
            self.assertFalse(hasattr(window, "archived_state_tabs"))
            self.assertEqual(window.settings_tabs.count(), 4)
            self.assertEqual(
                [
                    window.settings_tabs.tabText(index)
                    for index in range(window.settings_tabs.count())
                ],
                [
                    "Geral",
                    "Provedores",
                    "Temas",
                    "Projetos arquivados",
                ],
            )
            self.assertEqual(
                window.nav_button_pages[window.settings_nav_button],
                window.pages["Configurações"],
            )
            window._navigate(window.pages["Configurações"])
            self.assertTrue(window.settings_nav_button.isChecked())
            self.assertFalse(
                any(
                    button.isChecked()
                    for button in window.nav_buttons
                    if button is not window.settings_nav_button
                )
            )
            self.assertTrue(window.stop_button.isHidden())
            self.assertFalse(window.send_button.isHidden())
            self.assertFalse(window.windowIcon().isNull())
            self.assertEqual(window.nav_brand.text(), "VR NORTE")
            self.assertEqual(window.nav_subtitle.text(), "STUDIO")
            self.assertFalse(window.nav_brand_symbol.pixmap().isNull())
            self.assertEqual(
                window.nav_brand_symbol.accessibleName(),
                "Logotipo VRNorte",
            )
            self.assertEqual(
                window.effort_combo.accessibleName(),
                "Nível de esforço",
            )
            window._navigate(window.pages["Chat VR"])
            application.processEvents()
            assistant = window._add_message(
                "assistant",
                "Resposta VR com largura legível para evitar que cada linha "
                "seja quebrada em poucas palavras.",
            )
            application.processEvents()
            self.assertGreaterEqual(assistant.parentWidget().width(), 740)
            self.assertLessEqual(assistant.parentWidget().width(), 780)

            self.assertNotIn("VR_DEFAULT_EFFORT", window.settings_fields)
            self.assertNotIn("MARY_DEFAULT_EFFORT", window.settings_fields)
            self.assertEqual(window.effort_combo.findData("ultra"), -1)
        finally:
            window.close()

    def test_chat_project_selector_binds_new_thread_and_preserves_project_files(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        project = (self.root / "projetos" / "cliente-a").resolve()
        project.mkdir(parents=True)
        existing = project / "codigo.sql"
        existing.write_text("select 1;", encoding="utf-8")
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        try:
            with patch.object(window, "_request_file_catalog"):
                window._select_project(project)
            application.processEvents()
            self.assertEqual(window.draft_project_path, project)
            self.assertEqual(window.project_button.text(), "cliente-a")
            self.assertIn(str(self.settings.root), window.project_button.toolTip())

            result = window._create_conversation_request(
                1,
                "codex",
                "gpt-test",
                "medium",
                "",
                "auto",
                "default",
                [],
                [],
                window.draft_orchestration,
                project,
            )
            row = window.database.get_conversation(result["conversation_id"])
            self.assertIsNotNone(row)
            self.assertEqual(
                self.settings.resolve_path(row["workspace"]), project
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "select 1;")
            self.assertFalse((project / "AGENTS.md").exists())
            self.assertFalse((project / "CLAUDE.md").exists())
        finally:
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.close()

    def test_chat_project_scope_matches_t3_all_projects_and_picker(self):
        from PySide6.QtWidgets import QApplication, QDialog

        application = QApplication.instance() or QApplication([])
        first = (self.root / "projetos" / "alpha").resolve()
        second = (self.root / "projetos" / "beta").resolve()
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        try:
            window._remember_project(first)
            window._remember_project(second)
            window._select_project_scope(None)
            application.processEvents()

            self.assertEqual(window.project_button.text(), "Todos os projetos")
            window._rebuild_project_menu()
            labels = [action.text() for action in window.project_menu.actions()]
            self.assertIn("Todos os projetos", labels)
            self.assertIn("alpha", labels)
            self.assertIn("beta", labels)

            window._select_project_scope(second)
            self.assertEqual(window.chat_header_project.text(), "beta")
            self.assertEqual(window.chat_header_title.text(), "Nova conversa")
            self.assertNotIn("Todos os projetos", window.chat_header_meta.text())
            with (
                patch.object(
                    ProjectPickerDialog, "exec", return_value=QDialog.Accepted
                ) as picker_exec,
                patch.object(
                    ProjectPickerDialog, "selected_project", return_value=first
                ),
            ):
                window.new_chat_button.click()
            picker_exec.assert_called_once()
            self.assertEqual(window.draft_project_path, first)
            self.assertEqual(window.project_scope_path, first)
            self.assertIn("Shift+clique", window.new_chat_button.toolTip())
        finally:
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.close()

    def test_recent_project_actions_open_folder_and_remove_only_the_shortcut(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        project = (self.root / "projetos" / "atalho").resolve()
        project.mkdir(parents=True)
        marker = project / "preservar.txt"
        marker.write_text("conteúdo", encoding="utf-8")
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        try:
            window._select_project_scope(project)
            with patch(
                "vrsoft_extractor.mary.ui.QDesktopServices.openUrl",
                return_value=True,
            ) as open_url:
                window._open_recent_project(project)
            open_url.assert_called_once_with(QUrl.fromLocalFile(str(project)))

            with patch.object(window, "_show_toast") as toast:
                window._remove_recent_project(project)
            self.assertNotIn(project, window._recent_project_paths())
            self.assertIsNone(window.project_scope_path)
            self.assertEqual(window.project_button.text(), "Todos os projetos")
            self.assertTrue(project.is_dir())
            self.assertEqual(marker.read_text(encoding="utf-8"), "conteúdo")
            toast.assert_called_once()
            application.processEvents()
        finally:
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.close()

    def test_project_menu_lists_persisted_projects_from_any_location(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        outside_project = (self.old / "projeto-fora-do-workspace").resolve()
        outside_project.mkdir(parents=True)
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        try:
            window.app_preferences.setValue("chat/current_project", "")
            window.app_preferences.setValue("chat/recent_projects", "[]")
            window.app_preferences.setValue("chat/hidden_projects", "[]")
            window.app_preferences.setValue(
                "chat/projects", json.dumps([str(outside_project)])
            )
            window.project_scope_path = None
            window._rebuild_project_menu()

            labels = [action.text() for action in window.project_menu.actions()]
            self.assertEqual(labels[0], "Todos os projetos")
            self.assertIn("projeto-fora-do-workspace", labels)
            application.processEvents()
        finally:
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.close()

    def test_project_selector_stays_open_and_selects_a_project_after_real_click(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        project = (self.old / "projeto-selecionavel").resolve()
        project.mkdir(parents=True)
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.project_scope_path = None
            window.draft_project_path = None
            with patch.object(window, "_known_project_paths", return_value=[project]):
                QTest.mouseClick(window.project_button, Qt.LeftButton)
                application.processEvents()
                application.processEvents()

            self.assertTrue(window.project_menu.isVisible())
            self.assertFalse(window.project_menu.isWindow())
            self.assertFalse(window.project_menu.testAttribute(Qt.WA_NativeWindow))
            self.assertIs(window.project_menu.parentWidget(), window)
            self.assertEqual(
                [row.name_label.text() for row in window.project_menu._rows],
                ["Todos os projetos", "projeto-selecionavel"],
            )
            QTest.mouseClick(window.project_menu._rows[1], Qt.LeftButton)
            application.processEvents()
            self.assertEqual(window.project_scope_path, project)
            self.assertFalse(window.project_menu.isVisible())
        finally:
            window.project_menu.close()
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.sync()
            window.close()

    def test_dark_chat_composer_uses_neutral_high_contrast_palette(self):
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        apply_application_theme(application, "dark_orange")
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.theme_id = "dark_orange"
            window._refresh_composer_palette()
            palette = window.composer.palette()
            self.assertEqual(palette.color(QPalette.Base).name(), "#141416")
            self.assertEqual(palette.color(QPalette.Text).name(), "#e4e4e7")
            self.assertEqual(
                palette.color(QPalette.PlaceholderText).name(), "#a1a1aa"
            )
            self.assertEqual(palette.color(QPalette.Highlight).name(), "#303036")
            self.assertEqual(application.font().family(), "Segoe UI")
            self.assertEqual(application.font().weight(), 400)
            self.assertEqual(window.composer.font().family(), "Segoe UI")
        finally:
            window.close()

    def test_project_folder_picker_uses_qt_dialog_instead_of_broken_native_window(self):
        from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            with patch.object(
                QFileDialog, "getExistingDirectory", return_value=""
            ) as picker:
                window.choose_project_folder()

            application.processEvents()
            options = picker.call_args.args[3]
            self.assertTrue(options & QFileDialog.DontUseNativeDialog)
        finally:
            window.close()

    def test_new_project_action_opens_the_system_folder_picker(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        existing = (self.root / "existente").resolve()
        existing.mkdir()
        outside_project = (self.old / "selecionado-em-outro-local").resolve()
        outside_project.mkdir()
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        try:
            window._remember_project(existing)
            with (
                patch(
                    "vrsoft_extractor.mary.ui.QFileDialog.getExistingDirectory",
                    return_value=str(outside_project),
                ) as folder_picker,
            ):
                window.add_project_button.click()

            self.assertIn(outside_project, window._created_project_paths())
            self.assertEqual(window.project_scope_path, outside_project)
            folder_picker.assert_called_once()
            self.assertFalse(window.add_project_button.isHidden())
            application.processEvents()
        finally:
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.close()

    def test_project_picker_contains_only_search_and_existing_projects(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        project = (self.root / "projeto-listado").resolve()
        project.mkdir()
        picker = ProjectPickerDialog([project])
        try:
            self.assertEqual(picker.layout().indexOf(picker.search), 0)
            self.assertFalse(hasattr(picker, "new_project_button"))
            self.assertFalse(hasattr(picker, "folder_button"))
            self.assertEqual(picker.project_list.count(), 1)
            application.processEvents()
        finally:
            picker.close()

    def test_provider_reconnection_events_have_visible_chat_feedback(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.current_conversation = "reconnect-ui"
            window._on_runtime_event(
                RuntimeEvent(
                    "reconnect-ui",
                    "provider_reconnecting",
                    payload={"provider": "codex"},
                )
            )
            self.assertEqual(window.chat_status.text(), "Reconectando ao Codex…")
            self.assertEqual(window.chat_status.property("statusKind"), "running")
            window._on_runtime_event(
                RuntimeEvent(
                    "reconnect-ui",
                    "provider_reconnected",
                    payload={"provider": "codex"},
                )
            )
            self.assertEqual(
                window.chat_status.text(), "Codex reconectado · retomando…"
            )
            self.assertEqual(window.chat_status.property("statusKind"), "running")
            application.processEvents()
        finally:
            window.close()

    def test_chat_stop_interrupts_and_turn_state_locks_then_restores_controls(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.current_conversation = "stop-ui-test"
            application.processEvents()

            window._set_turn_running(True)
            application.processEvents()
            self.assertTrue(window.send_button.isHidden())
            self.assertFalse(window.stop_button.isHidden())
            self.assertTrue(window.composer.isReadOnly())
            for control in (
                window.model_combo,
                window.effort_combo,
                window.approval_combo,
                window.vr_flow_button,
                window.send_button,
            ):
                self.assertFalse(control.isEnabled())

            with patch.object(window.orchestrator, "interrupt") as interrupt:
                window.stop_button.click()
                for _attempt in range(50):
                    application.processEvents()
                    if interrupt.called:
                        break
                    from PySide6.QtTest import QTest

                    QTest.qWait(10)
            interrupt.assert_called_once_with("stop-ui-test")
            self.assertEqual(window.chat_status.text(), "Parando…")
            self.assertTrue(window.chat_status.isVisible())

            window._set_turn_running(False)
            application.processEvents()
            self.assertFalse(window.send_button.isHidden())
            self.assertTrue(window.stop_button.isHidden())
            self.assertFalse(window.composer.isReadOnly())
            for control in (
                window.model_combo,
                window.effort_combo,
                window.approval_combo,
                window.vr_flow_button,
                window.send_button,
            ):
                self.assertTrue(control.isEnabled())
        finally:
            window.close()

    def test_main_and_chat_sidebars_expand_and_collapse(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        original_nav = window.nav_collapsed
        original_chat_sidebar = window.chat_sidebar_visible
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window._set_nav_collapsed(False, persist=False)
            window._set_chat_sidebar_visible(True, persist=False)
            application.processEvents()

            window.nav_toggle_button.click()
            application.processEvents()
            self.assertTrue(window.nav_collapsed)
            self.assertEqual(window.nav_frame.width(), 64)
            self.assertTrue(window.nav_brand_symbol.isHidden())
            self.assertTrue(window.nav_brand_text.isHidden())
            self.assertTrue(
                all(button.text() == "" for button in window.nav_buttons)
            )
            self.assertTrue(
                all(
                    button.toolButtonStyle() == Qt.ToolButtonIconOnly
                    and not button.icon().isNull()
                    for button in window.nav_buttons
                )
            )

            window.nav_toggle_button.click()
            application.processEvents()
            self.assertFalse(window.nav_collapsed)
            self.assertEqual(window.nav_frame.width(), 228)
            self.assertTrue(window.nav_brand_symbol.isVisible())
            self.assertEqual(window.nav_buttons[0].text(), "Dashboard")

            window.chat_sidebar_toggle_button.click()
            application.processEvents()
            self.assertFalse(window.chat_sidebar_visible)
            self.assertTrue(window.chat_sidebar.isHidden())
            self.assertIn("Expandir", window.chat_sidebar_toggle_button.toolTip())

            window.chat_sidebar_toggle_button.click()
            application.processEvents()
            self.assertTrue(window.chat_sidebar_visible)
            self.assertTrue(window.chat_sidebar.isVisible())
            self.assertGreaterEqual(window.chat_splitter.sizes()[0], 210)
        finally:
            window._set_nav_collapsed(original_nav, persist=True)
            window._set_chat_sidebar_visible(original_chat_sidebar, persist=True)
            window.close()

    def test_claude_keeps_general_chat_controls_and_disables_codex_only_controls(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_claude_enabled = window.app_preferences.value(
            "providers/claude/enabled", True
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.app_preferences.setValue("providers/claude/enabled", True)
            window._sync_enabled_providers_for_chat()
            window.provider_combo.blockSignals(True)
            window.provider_combo.setCurrentText("claude")
            window.provider_combo.blockSignals(False)
            window._update_codex_controls()
            application.processEvents()

            self.assertEqual(window.approval_combo.currentData(), "auto")
            self.assertTrue(window.options_button.isHidden())
            for control in (
                window.model_combo,
                window.effort_combo,
                window.vr_flow_button,
                window.send_button,
            ):
                self.assertTrue(control.isEnabled())
            for control in (
                window.approval_combo,
                window.tier_combo,
                window.mode_combo,
            ):
                self.assertFalse(control.isEnabled())
        finally:
            window.app_preferences.setValue(
                "providers/claude/enabled", saved_claude_enabled
            )
            window.close()

    def test_dense_review_and_video_controls_reflow_at_minimum_width(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1120, 700)
            window.show()

            window._navigate(window.pages["Revisão"])
            application.processEvents()
            self.assertTrue(window.review_toolbar.isVisible())
            self.assertTrue(window.review_toolbar.search.isVisible())
            self.assertTrue(window.review_toolbar.counter.isVisible())
            self.assertTrue(window.review_filters_panel.isHidden())
            window.review_filters_button.click()
            application.processEvents()
            review_rows = {
                window.review_query.y(),
                window.review_source.y(),
                window.review_product.y(),
                window.review_special.y(),
            }
            self.assertEqual(len(review_rows), 4)
            self.assertGreaterEqual(window.review_source.width(), 180)
            self.assertGreaterEqual(window.review_sort.width(), 360)
            self.assertTrue(window.review_previous_page.isVisible())
            self.assertTrue(window.review_next_page.isVisible())
            self.assertTrue(window.review_pagination.range_label.isVisible())

            window._navigate(window.pages["Vídeos"])
            application.processEvents()
            self.assertTrue(window.video_toolbar.primary_button.isVisible())
            self.assertTrue(window.video_filters_panel.isHidden())
            action_rows = {button.y() for button in window.video_action_buttons}
            self.assertEqual(len(action_rows), 2)

            self.assertEqual(
                window.review_table.verticalHeader().defaultSectionSize(), 38
            )
            self.assertTrue(
                all(
                    not hasattr(toolbar, "density_button")
                    for toolbar in (
                        window.knowledge_toolbar,
                        window.sync_toolbar,
                        window.review_toolbar,
                        window.video_toolbar,
                    )
                )
            )
        finally:
            window.close()

    def test_sync_page_selects_and_indexes_a_new_schema_file(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        selected = self.settings.root / "imports" / "schema-selecionado.md"
        selected.parent.mkdir(parents=True)
        selected.write_text(
            """# Schema PostgreSQL

## `public`.`cliente`

| Coluna | Tipo | Nulo | PK | Default | Descricao |
|---|---|---|---|---|---|
| `id` | `integer` | Nao | PK | | Cliente |
""",
            encoding="utf-8",
        )
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.app_preferences = MagicMock()
            with patch(
                "vrsoft_extractor.mary.ui.QFileDialog.getOpenFileName",
                return_value=(str(selected), "Schema Markdown (*.md *.markdown)"),
            ):
                window.choose_schema_file()

            self.assertEqual(
                Path(window.schema_path_input.text()), selected.resolve()
            )
            window.app_preferences.setValue.assert_called_once_with(
                "sync/schema_path", "imports/schema-selecionado.md"
            )
            with patch.object(window, "_run_sync") as run_sync:
                window.sync_schema()
            label, operation = run_sync.call_args.args
            self.assertIn("schema-selecionado.md", label)
            stats = operation()
            self.assertEqual(stats.created, 1)
            self.assertEqual(
                window.database.search_schema_catalog("cliente")[0]["table_name"],
                "cliente",
            )
        finally:
            window.close()

    def test_data_pages_share_toolbar_and_actionable_empty_states(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()

            self.assertNotIn("schema", window.source_count_labels)
            self.assertNotIn(
                "schema",
                [
                    window.knowledge_source.itemText(index).casefold()
                    for index in range(window.knowledge_source.count())
                ],
            )
            self.assertTrue(
                all(
                    button.variant() == "secondary"
                    for button in window.dashboard_source_action_buttons
                )
            )
            self.assertEqual(
                [button.variant() for button in window.dashboard_quick_action_buttons],
                ["primary", "secondary", "secondary", "secondary"],
            )
            self.assertTrue(
                all(button.variant() == "secondary" for button in window.sync_action_buttons)
            )
            window._set_knowledge_preview_expanded(False, persist=False)
            self.assertFalse(window.knowledge_preview_expanded)
            self.assertFalse(window.knowledge_table.isHidden())
            window._set_knowledge_preview_expanded(True, persist=False)
            self.assertTrue(window.knowledge_preview_expanded)
            self.assertTrue(window.knowledge_table.isHidden())
            self.assertIn(
                "Restaurar",
                window.knowledge_expand_button.accessibleName(),
            )
            window._set_knowledge_preview_expanded(False, persist=False)
            self.assertFalse(window.knowledge_preview_expanded)
            self.assertFalse(window.knowledge_table.isHidden())

            window._navigate(window.pages["Conhecimento"])
            application.processEvents()
            self.assertIs(
                window.knowledge_content.currentWidget(),
                window.knowledge_content.empty_state,
            )
            self.assertEqual(
                window.knowledge_content.empty_state.action_button.text(),
                "Sincronizar fontes",
            )
            window.knowledge_query.setText("inexistente")
            window.search_knowledge()
            self.assertEqual(
                window.knowledge_content.empty_state.action_button.text(),
                "Limpar busca e filtros",
            )

            window._navigate(window.pages["Sincronizações"])
            application.processEvents()
            self.assertIs(
                window.sync_content.currentWidget(), window.sync_content.empty_state
            )
            self.assertTrue(window.sync_toolbar.primary_button.isVisible())

            for toolbar in (
                window.knowledge_toolbar,
                window.sync_toolbar,
                window.review_toolbar,
                window.video_toolbar,
            ):
                self.assertEqual(toolbar.objectName(), "dataToolbar")
                self.assertFalse(hasattr(toolbar, "density_button"))
        finally:
            window.close()

    def test_knowledge_filters_apply_without_a_search_term(self):
        from PySide6.QtWidgets import QApplication

        database = initialize_workspace(self.settings)
        for source_id, module in (("fiscal-doc", "Fiscal"), ("pdv-doc", "PDV")):
            database.upsert_document(
                KnowledgeDocument(
                    source="wiki",
                    source_id=source_id,
                    title=f"Documento {module}",
                    url=f"https://example.test/{source_id}",
                    markdown=f"Conteúdo {module}",
                    module=module,
                    content_hash=source_id,
                )
            )
        database.upsert_document(
            KnowledgeDocument(
                source="schema",
                source_id="schema-doc",
                title="Tabela de venda",
                url="",
                markdown="Tabela PDV venda e seus campos.",
                module="PDV",
                review_status="approved",
                content_hash="schema-doc",
            )
        )

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.knowledge_module.setCurrentText("PDV")
            application.processEvents()

            self.assertEqual(window.knowledge_query.text(), "")
            self.assertEqual(window.knowledge_total, 1)
            self.assertEqual(window.knowledge_table.rowCount(), 1)
            self.assertEqual(window.knowledge_table.item(0, 1).text(), "PDV")
            self.assertEqual(window.knowledge_table.item(0, 2).text(), "WIKI")
            self.assertEqual(window.knowledge_toolbar.filter_button.text(), "Filtros · 1")
        finally:
            window.close()

    def test_chat_context_compact_layout_contains_controls_empty_state_and_stop(self):
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1120, 700)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window._set_chat_sidebar_visible(True, persist=False)
            window._toggle_chat_context(True)
            application.processEvents()

            self.assertTrue(window.chat_context_panel.isVisible())
            self.assertTrue(window._composer_compact)
            self.assertLess(window.composer_host.width(), 600)
            self.assertTrue(all(separator.isHidden() for separator in window.composer_separators))
            self.assertTrue(window.options_button.isHidden())

            empty_origin = window.chat_empty_state.mapTo(
                window.message_column,
                QPoint(0, 0),
            )
            empty_rect = QRect(empty_origin, window.chat_empty_state.size())
            self.assertGreaterEqual(empty_rect.left(), 0)
            self.assertLessEqual(empty_rect.right(), window.message_column.rect().right())

            for running in (False, True):
                with self.subTest(running=running):
                    window._set_turn_running(running)
                    window.chat_status.setText("Pronto")
                    application.processEvents()
                    action = window.stop_button if running else window.send_button
                    controls = (
                        window.model_combo,
                        window.effort_combo,
                        window.approval_combo,
                        window.vr_flow_button,
                        action,
                    )
                    rects = [
                        QRect(
                            control.mapTo(window.composer_card, QPoint(0, 0)),
                            control.size(),
                        )
                        for control in controls
                    ]
                    self.assertTrue(all(control.isVisible() for control in controls))
                    self.assertTrue(
                        all(
                            window.composer_card.rect().contains(rect)
                            for rect in rects
                        )
                    )
                    self.assertTrue(
                        all(
                            left.right() < right.left()
                            for left, right in zip(rects, rects[1:])
                        )
                    )
        finally:
            window.close()

    def test_phase_five_accessibility_contract_is_applied_across_pages(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QToolButton

        application = QApplication.instance() or QApplication([])
        apply_application_theme(application, "light")
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        original_motion = window.reduce_motion
        try:
            window.resize(1480, 900)
            window.show()
            window._navigate(window.pages["Chat VR"])
            application.processEvents()

            self.assertEqual(
                window.knowledge_table.accessibleName(),
                "Resultados do conhecimento",
            )
            self.assertEqual(
                window.review_note.accessibleName(), "Nota de auditoria"
            )
            self.assertEqual(
                window.video_tree.accessibleName(), "Vídeos encontrados"
            )
            self.assertEqual(
                window._tab_sequences["chat"][-2:],
                (window.composer, window.send_button),
            )
            self.assertEqual(
                window._tab_sequences["appearance"],
                (window.theme_combo, window.reduce_motion_check),
            )
            for group_name in ("chat", "knowledge", "sync", "review", "videos"):
                sequence = window._tab_sequences[group_name]
                self.assertEqual(len(sequence), len(set(sequence)))
                for current in sequence:
                    with self.subTest(
                        tab_group=group_name,
                        current=current.accessibleName() or current.objectName(),
                    ):
                        self.assertNotEqual(current.focusPolicy(), Qt.NoFocus)

            for button in window.findChildren(QToolButton):
                if not button.text().strip():
                    with self.subTest(control=button.objectName()):
                        self.assertTrue(button.accessibleName())
                        self.assertTrue(button.toolTip())

            for control in (
                window.nav_toggle_button,
                window.chat_sidebar_toggle_button,
                window.new_chat_button,
                window.vr_flow_button,
                window.send_button,
            ):
                with self.subTest(target=control.objectName()):
                    self.assertGreaterEqual(control.width(), 32)
                    self.assertGreaterEqual(control.height(), 32)

            window.reduce_motion_check.setChecked(True)
            application.processEvents()
            self.assertTrue(application.property("vr_reduce_motion"))
            self.assertTrue(window.vr_flow_button._reduced_motion)
            self.assertTrue(window.composer_glow._reduced_motion)
        finally:
            window._reduce_motion_changed(original_motion)
            window.close()

    def test_vr_toggle_persists_without_changing_the_execution_mode_glow(self):
        from PySide6.QtWidgets import QApplication

        class MemoryPreferences:
            def __init__(self):
                self.values = {}
                self.sync_count = 0

            def value(self, key, default=None):
                return self.values.get(key, default)

            def setValue(self, key, value):
                self.values[key] = value

            def sync(self):
                self.sync_count += 1

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            preferences = MemoryPreferences()
            window.app_preferences = preferences
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.draft_orchestration = window.draft_orchestration.__class__(mode="off")
            window._sync_orchestration_mode_ui(
                window.draft_orchestration, animate=False
            )
            window.vr_flow_button.setChecked(True)
            window.vr_flow_button.setChecked(False)
            application.processEvents()

            self.assertEqual(window.composer_glow.mode(), "off")
            self.assertFalse(preferences.values["chat/vr_flow_enabled"])
            window.vr_flow_button.click()
            application.processEvents()

            self.assertTrue(window.vr_flow_button.isChecked())
            self.assertEqual(window.composer_glow.mode(), "off")
            self.assertTrue(preferences.values["chat/vr_flow_enabled"])

            window.vr_flow_button.click()
            self.assertFalse(window.vr_flow_button.isChecked())
            self.assertEqual(window.composer_glow.mode(), "off")
            self.assertFalse(preferences.values["chat/vr_flow_enabled"])
            self.assertGreaterEqual(preferences.sync_count, 3)
        finally:
            window.close()

    def test_reasoning_and_approval_popups_activate_current_item_with_enter(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QListWidget, QVBoxLayout, QWidget

        from vrsoft_extractor.mary.chat_widgets import (
            ApprovalPickerCombo,
            ReasoningTierCombo,
        )

        application = QApplication.instance() or QApplication([])
        host = QWidget()
        layout = QVBoxLayout(host)
        effort = ReasoningTierCombo()
        effort.addItem("Baixo", "low")
        effort.addItem("Médio", "medium")
        approval = ApprovalPickerCombo()
        approval.addItem("Auto", "auto")
        approval.addItem("Leitura", "read-only")
        layout.addWidget(effort)
        layout.addWidget(approval)
        host.show()
        application.processEvents()
        top_levels_before = set(application.topLevelWidgets())

        def activate_popup_item(combo, payload) -> None:
            combo.showPopup()
            application.processEvents()
            dialog = combo._option_popup
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.isWindow())
            self.assertEqual(set(application.topLevelWidgets()), top_levels_before)
            choices = dialog.findChild(QListWidget, "optionPickerList")
            item = next(
                choices.item(index)
                for index in range(choices.count())
                if choices.item(index).data(Qt.UserRole) == payload
            )
            choices.setCurrentItem(item)
            choices.setFocus()
            QTest.keyClick(choices, Qt.Key_Return)
            application.processEvents()
            self.assertIsNone(combo._option_popup)

        try:
            activate_popup_item(effort, ("reasoning", 1))
            self.assertEqual(effort.currentData(), "medium")

            activate_popup_item(approval, 1)
            self.assertEqual(approval.currentData(), "read-only")

            QTest.mouseClick(approval, Qt.LeftButton)
            application.processEvents()
            self.assertIsNotNone(approval._option_popup)
            QTest.mouseClick(approval, Qt.LeftButton)
            application.processEvents()
            self.assertIsNone(approval._option_popup)
        finally:
            host.close()

    def test_chat_context_menu_targets_clicked_conversation_and_changes_by_state(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.project_scope_path = None
            first = window.database.create_conversation(
                "Primeira", "codex", "gpt-test", self.settings.work_dir / "first"
            )
            second = window.database.create_conversation(
                "Segunda", "codex", "gpt-test", self.settings.work_dir / "second"
            )
            window.refresh_conversations()
            first_item = next(
                window.conversation_list.item(index)
                for index in range(window.conversation_list.count())
                if window.conversation_list.item(index).data(Qt.UserRole) == first
            )
            second_item = next(
                window.conversation_list.item(index)
                for index in range(window.conversation_list.count())
                if window.conversation_list.item(index).data(Qt.UserRole) == second
            )
            self.assertFalse(first_item.icon().isNull())
            self.assertFalse(second_item.icon().isNull())
            window.conversation_list.setCurrentItem(first_item)
            application.processEvents()
            menu = window._build_conversation_menu(second)
            application.processEvents()
            self.assertEqual(window.current_conversation, second)
            self.assertIs(window.conversation_list.currentItem(), second_item)
            self.assertEqual(
                [action.text() for action in menu.actions() if not action.isSeparator()],
                ["Arquivar"],
            )

            window.conversation_state = "archived"
            archived = window._build_conversation_menu(second)
            self.assertEqual(
                [action.text() for action in archived.actions() if not action.isSeparator()],
                ["Restaurar"],
            )
            window.conversation_state = "trash"
            trash = window._build_conversation_menu(second)
            self.assertEqual(
                [action.text() for action in trash.actions() if not action.isSeparator()],
                ["Restaurar"],
            )
        finally:
            window.close()

    def test_settings_theme_providers_and_archived_projects_are_separated_from_chat(self):
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QIcon, QPalette
        from PySide6.QtWidgets import QApplication, QToolButton

        class MemoryPreferences:
            def __init__(self):
                self.values = {}

            def value(self, key, default=None):
                return self.values.get(key, default)

            def setValue(self, key, value):
                self.values[key] = value

            def sync(self):
                pass

        application = QApplication.instance() or QApplication([])
        previous_theme = str(application.property("vr_theme") or "light")

        def icon_colors(button, state):
            image = button.icon().pixmap(
                QSize(18, 18),
                QIcon.Mode.Normal,
                state,
            ).toImage()
            return {
                image.pixelColor(x, y).name().lower()
                for y in range(image.height())
                for x in range(image.width())
                if image.pixelColor(x, y).alpha() > 0
            }

        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.app_preferences = MemoryPreferences()
            window.project_scope_path = None
            active = window.database.create_conversation(
                "Ativo", "codex", "gpt-test", self.settings.work_dir / "active"
            )
            archived = window.database.create_conversation(
                "Arquivado", "codex", "gpt-test", self.settings.work_dir / "archived"
            )
            trashed = window.database.create_conversation(
                "Lixeira", "claude", "claude-test", self.settings.work_dir / "trash"
            )
            window.database.update_conversation(archived, archived=1)
            window.database.update_conversation(
                trashed, archived=1, trashed_at="2026-08-03T12:00:00+00:00"
            )

            window.refresh_conversations()
            active_ids = {
                window.conversation_list.item(index).data(Qt.UserRole)
                for index in range(window.conversation_list.count())
            }
            self.assertIn(active, active_ids)
            self.assertNotIn(archived, active_ids)
            self.assertNotIn(trashed, active_ids)

            window.refresh_archived_projects()
            archived_ids = {
                window.archived_projects_list.item(index).data(Qt.UserRole)
                for index in range(window.archived_projects_list.count())
            }
            self.assertIn(archived, archived_ids)
            self.assertNotIn(trashed, archived_ids)

            delete_button = window.archived_projects_list.itemWidget(
                window.archived_projects_list.item(0)
            ).findChild(QToolButton, "archivedDeleteButton")
            self.assertTrue(delete_button)
            self.assertEqual(delete_button.text(), "")
            self.assertFalse(delete_button.icon().isNull())
            with patch.object(window, "_run_archived_project_operation") as operation:
                delete_button.click()
            self.assertEqual(
                operation.call_args.args,
                (archived, window.orchestrator.purge),
            )
            self.assertEqual(
                set(window.provider_status_labels),
                {"codex", "claude", "opencode"},
            )
            self.assertEqual(window.theme_combo.itemData(0), "light")
            self.assertEqual(window.theme_combo.itemData(1), "dark_orange")

            light_index = window.theme_combo.findData("light")
            window.theme_combo.setCurrentIndex(light_index)
            application.processEvents()
            self.assertIn(
                "#d9d9e2",
                icon_colors(window.nav_buttons[1], QIcon.State.Off),
            )
            self.assertIn(
                "#ffffff",
                icon_colors(window.nav_buttons[1], QIcon.State.On),
            )

            dark_index = window.theme_combo.findData("dark_orange")
            window.theme_combo.setCurrentIndex(dark_index)
            application.processEvents()
            self.assertEqual(application.property("vr_theme"), "dark_orange")
            self.assertEqual(
                application.palette().color(QPalette.Window).name().lower(),
                "#12100f",
            )
            self.assertEqual(
                window.app_preferences.values["appearance/theme"], "dark_orange"
            )
            self.assertIn(
                "#a1a1aa",
                icon_colors(window.nav_buttons[1], QIcon.State.Off),
            )
        finally:
            apply_application_theme(application, previous_theme)
            window.close()

    def test_model_catalog_ignores_stale_results_and_exposes_retry_state(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            models = [{"id": "gpt-new", "displayName": "GPT New", "isDefault": True}]
            window._model_request_ids["codex"] = 2
            with (
                patch.object(window, "load_collaboration_modes"),
                patch.object(window, "_preload_other_models"),
            ):
                window._model_catalog_loaded("codex", 1, [{"id": "gpt-old"}])
                self.assertNotIn("codex", window.model_cache)
                window._model_catalog_loaded("codex", 2, models)
            self.assertEqual(window.model_cache["codex"], models)
            self.assertEqual(window.model_combo.currentData(), "gpt-new")

            window._model_request_ids["codex"] = 3
            window._model_catalog_failed("codex", 3, "Falha simulada")
            self.assertEqual(window.model_combo.catalog_state("codex"), "error")
            self.assertIn("Falha simulada", window.model_combo.toolTip())

            window.show()
            window._navigate(window.pages["Chat VR"])
            application.processEvents()
            window._set_turn_running(True)
            self.assertTrue(window.send_button.isHidden())
            self.assertFalse(window.stop_button.isHidden())
            window._set_turn_running(False)
            self.assertFalse(window.send_button.isHidden())
            self.assertTrue(window.stop_button.isHidden())
        finally:
            window.close()

    def test_main_model_is_locked_after_chat_starts_but_not_for_empty_draft(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            conversation_id = window.database.create_conversation(
                "Troca dinâmica",
                "codex",
                "gpt-test",
                self.settings.work_dir / "dynamic-provider",
            )
            window.current_conversation = conversation_id
            window.draft_conversation = False
            window.provider_combo.setCurrentText("codex")
            window.database.add_message(conversation_id, "user", "Primeira mensagem")
            with (
                patch.object(window, "_provider_enabled", return_value=True),
                patch.object(window.pool, "start") as start,
                patch("vrsoft_extractor.mary.ui.ConfirmDialog.ask") as question,
            ):
                window._model_picker_selected("claude", "claude-test")

            question.assert_not_called()
            start.assert_not_called()
            self.assertFalse(window.provider_switch_in_progress)
            self.assertIn("Modelo principal bloqueado", window.chat_status.text())
            window._update_codex_controls()
            self.assertFalse(window.model_combo.isEnabled())

            empty_id = window.database.create_conversation(
                "Rascunho vazio",
                "codex",
                "gpt-test",
                self.settings.work_dir / "empty-provider",
            )
            window.current_conversation = empty_id
            window._update_codex_controls()
            self.assertTrue(window.model_combo.isEnabled())
        finally:
            window.close()

    def test_service_tier_defaults_to_standard_and_preserves_explicit_fast(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.model_combo.clear()
            window.model_combo.addItem("GPT Tier", "gpt-tier")
            window.model_metadata["gpt-tier"] = {
                "serviceTiers": [
                    {
                        "id": "priority",
                        "name": "Fast",
                        "description": "Maior velocidade e maior consumo.",
                    }
                ],
                "defaultServiceTier": None,
            }

            window.pending_tier = ""
            window.load_service_tiers()
            self.assertEqual(window.tier_combo.itemText(0), "Standard")
            self.assertEqual(window.tier_combo.currentData(), "")
            self.assertEqual(window.tier_combo.itemText(1), "Fast")

            window.pending_tier = "priority"
            window.load_service_tiers()
            self.assertEqual(window.tier_combo.currentData(), "priority")
        finally:
            window.close()

    def test_model_catalog_worker_updates_combo_on_the_ui_thread(self):
        import time

        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            models = [{"id": "gpt-live", "displayName": "GPT Live", "isDefault": True}]
            window.orchestrator.models = MagicMock(return_value=models)
            window.load_collaboration_modes = MagicMock()
            window._preload_other_models = MagicMock()
            window.load_models(force=True)
            deadline = time.monotonic() + 2
            while (
                window.model_combo.catalog_state("codex") == "loading"
                and time.monotonic() < deadline
            ):
                application.processEvents()
                time.sleep(0.01)
            self.assertEqual(window.model_combo.catalog_state("codex"), "ready")
            self.assertEqual(window.model_combo.currentData(), "gpt-live")
            self.assertTrue(
                any(
                    "GPT Live" in window.model_combo.itemText(index)
                    for index in range(window.model_combo.count())
                )
            )
        finally:
            window.close()

    def test_background_stream_does_not_rebuild_conversation_sidebar_per_delta(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.current_conversation = "visible-chat"
            with patch.object(window, "refresh_conversations") as refresh:
                window._on_runtime_event(
                    RuntimeEvent("background-chat", "assistant_delta", "trecho")
                )
                refresh.assert_not_called()

            window._on_runtime_event(
                RuntimeEvent("background-chat", "turn_completed")
            )
            self.assertTrue(window._conversation_refresh_timer.isActive())
        finally:
            window.close()

    def test_running_chat_can_stay_active_while_another_chat_is_opened(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            running_id = window.database.create_conversation(
                "Chat trabalhando",
                "codex",
                "gpt-test",
                self.settings.work_dir / "parallel-running",
            )
            idle_id = window.database.create_conversation(
                "Chat livre",
                "claude",
                "sonnet",
                self.settings.work_dir / "parallel-idle",
            )
            window.database.update_conversation(running_id, status="running")
            window.project_scope_path = None
            window.refresh_conversations()
            running_item = next(
                window.conversation_list.item(index)
                for index in range(window.conversation_list.count())
                if window.conversation_list.item(index).data(Qt.UserRole) == running_id
            )
            idle_item = next(
                window.conversation_list.item(index)
                for index in range(window.conversation_list.count())
                if window.conversation_list.item(index).data(Qt.UserRole) == idle_id
            )

            self.assertTrue(running_item.data(CONVERSATION_RUNNING_ROLE))
            self.assertTrue(window.conversation_activity_delegate._timer.isActive())
            window.conversation_list.setCurrentItem(running_item)
            application.processEvents()
            self.assertTrue(window.turn_running)
            self.assertFalse(window.context_usage_button._timer.isActive())

            with (
                patch.object(window, "_select_project") as select_project,
                patch.object(window, "_show_error") as show_error,
            ):
                window._start_new_conversation_for_project(self.settings.root)
            select_project.assert_called_once_with(self.settings.root)
            show_error.assert_not_called()

            window.conversation_list.setCurrentItem(idle_item)
            application.processEvents()
            self.assertEqual(window.current_conversation, idle_id)
            self.assertFalse(window.turn_running)
            self.assertFalse(window.context_usage_button._timer.isActive())
            self.assertFalse(window.composer.isReadOnly())

            window.database.update_conversation(
                idle_id,
                context_used_tokens=40_000,
                context_window_tokens=100_000,
                total_processed_tokens=250_000,
            )
            window._refresh_context_usage()
            self.assertIn("40%", window.context_usage_value.text())
            self.assertEqual(window.context_usage_bar.value(), 400)
            self.assertIn("250 mil", window.context_total_value.text())
        finally:
            window.close()

    def test_long_assistant_delta_types_smoothly_before_turn_finishes(self):
        from PySide6.QtWidgets import QApplication, QTextBrowser

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            conversation_id = "typing-stream-test"
            answer = "\n\n".join(
                f"## Etapa {index}\n\nResposta VR com efeito de digitação validada."
                for index in range(24)
            )
            window.current_conversation = conversation_id
            window._on_runtime_event(RuntimeEvent(conversation_id, "turn_started"))
            window._on_runtime_event(
                RuntimeEvent(conversation_id, "assistant_delta", answer)
            )

            self.assertIsNotNone(window.assistant_widget)
            self.assertGreater(len(window.assistant_markdown), 0)
            self.assertLess(len(window.assistant_markdown), len(answer))
            stream_browser = window.assistant_widget.findChild(
                QTextBrowser, "messageBody"
            )

            window._on_runtime_event(RuntimeEvent(conversation_id, "turn_completed"))
            self.assertTrue(window.turn_running)
            while window._assistant_pending_text:
                window._render_assistant_typing_step()

            self.assertEqual(window.assistant_markdown, answer)
            self.assertFalse(window.turn_running)
            self.assertIs(
                stream_browser,
                window.assistant_widget.findChild(QTextBrowser, "messageBody"),
            )
            application.processEvents()
            self.assertGreater(stream_browser.height(), 700)
            self.assertGreaterEqual(
                window.assistant_widget.minimumHeight(),
                stream_browser.height(),
            )
            self.assertGreaterEqual(
                window.assistant_widget.height(),
                stream_browser.height(),
            )
        finally:
            window.close()

    def test_response_plan_uses_real_steps_and_segmented_progress(self):
        from PySide6.QtWidgets import QApplication, QFrame, QLabel

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            conversation_id = "response-plan-test"
            window.current_conversation = conversation_id
            steps = [
                "Entender a solicitação sobre bonificação.",
                "Cruzar VRWiki e KB no módulo ADM/Financeiro/Estoque.",
                "Validar a seção Como fazer uma rebaixa.",
                "Explicar funcionamento, regras e efeito operacional.",
                "Redigir a resposta com os links selecionados.",
            ]
            window._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "response_plan_created",
                    "Plano da resposta definido.",
                    {"steps": steps, "completed": 3},
                )
            )

            progress = window.chat_activity_progress
            self.assertIsNotNone(progress)
            self.assertEqual(progress.segment_count, len(steps))
            self.assertEqual(progress.completed_count, 3)
            self.assertEqual(window.chat_activity_count.text(), "3/5")
            self.assertEqual(window.chat_activity_label.text(), steps[3])
            self.assertEqual(window.chat_activity_toggle.text(), "Tasks")
            self.assertEqual(
                len(window.message_container.findChildren(QFrame, "chatActivity")),
                0,
            )
            self.assertEqual(
                len(window.chat_task_host.findChildren(QFrame, "chatActivity")),
                1,
            )
            detail_text = " ".join(
                label.text()
                for label in window.chat_activity_details.findChildren(
                    QLabel, "chatActivityStep"
                )
            )
            self.assertIn("bonificação", detail_text)
            self.assertIn("VRWiki", detail_text)
            self.assertNotIn("Interpretando intenção", detail_text)
            window.chat_activity_toggle.click()
            application.processEvents()
            self.assertFalse(window.chat_activity_details.isHidden())
            self.assertTrue(window.chat_activity_label.isHidden())
            self.assertTrue(progress.isHidden())
            self.assertFalse(window.chat_activity_expanded_count.isHidden())
            window.chat_activity_toggle.click()
            application.processEvents()
            self.assertTrue(window.chat_activity_details.isHidden())
            self.assertFalse(progress.isHidden())

            window._on_runtime_event(
                RuntimeEvent(conversation_id, "assistant_delta", "Resposta final")
            )
            self.assertEqual(progress.completed_count, 4)
            window._on_runtime_event(RuntimeEvent(conversation_id, "turn_completed"))
            application.processEvents()

            completed = window.chat_task_host.findChildren(
                QFrame, "chatActivityCompleted"
            )
            self.assertEqual(len(completed), 1)
            self.assertEqual(progress.completed_count, len(steps))
            self.assertEqual(
                completed[0].findChild(QLabel, "chatActivityCount").text(),
                "5/5",
            )
            self.assertTrue(
                all(
                    marker.text() == "✓"
                    for marker in completed[0].findChildren(
                        QLabel, "chatActivityStepMarker"
                    )
                )
            )
        finally:
            window.close()

    def test_runtime_events_use_one_compact_activity_without_raw_payloads(self):
        from PySide6.QtWidgets import QApplication, QFrame, QLabel, QToolButton

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            conversation_id = "compact-runtime-test"
            window.current_conversation = conversation_id
            window._on_runtime_event(RuntimeEvent(conversation_id, "turn_started"))
            first_activity = window.chat_activity_widget
            self.assertIsNotNone(first_activity)
            self.assertEqual(window.chat_activity_label.text(), "Trabalhando…")

            raw_command = "powershell.exe -Command segredo-interno"
            window._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    f"Comando: {raw_command}",
                    {
                        "lifecycle": "item/started",
                        "item": {"type": "commandExecution", "command": raw_command},
                    },
                )
            )
            self.assertIs(window.chat_activity_widget, first_activity)
            self.assertEqual(window.chat_activity_label.text(), "Executando uma ação…")
            self.assertNotIn("powershell", window.chat_activity_label.text().casefold())
            self.assertEqual(
                len(window.chat_task_host.findChildren(QFrame, "chatActivity")),
                1,
            )
            self.assertEqual(
                len(window.message_container.findChildren(QFrame, "chatActivity")),
                0,
            )

            window._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "reasoning",
                    {
                        "lifecycle": "item/started",
                        "item": {"type": "reasoning", "content": [raw_command]},
                    },
                )
            )
            self.assertIs(window.chat_activity_widget, first_activity)
            self.assertEqual(window.chat_activity_label.text(), "Analisando…")

            window._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "reasoning_delta",
                    "Verificando as evidências relevantes.",
                )
            )
            self.assertIs(window.chat_activity_widget, first_activity)
            self.assertEqual(
                window.chat_activity_label.text(),
                "Pensando… Verificando as evidências relevantes.",
            )

            window._on_runtime_event(
                RuntimeEvent(conversation_id, "assistant_delta", "Resposta final")
            )
            application.processEvents()
            self.assertIs(window.chat_activity_widget, first_activity)
            self.assertEqual(
                len(window.chat_task_host.findChildren(QFrame, "chatActivity")),
                1,
            )
            self.assertIsNotNone(window.assistant_widget)
            self.assertIn("Resposta final", window.assistant_widget.toPlainText())
            self.assertNotIn(raw_command, window.assistant_widget.toPlainText())

            window._on_runtime_event(
                RuntimeEvent(
                    conversation_id,
                    "tool_event",
                    "agentMessage",
                    {"item": {"type": "agentMessage"}},
                )
            )
            self.assertEqual(window.chat_activity_label.text(), "Preparando a resposta…")
            window._on_runtime_event(RuntimeEvent(conversation_id, "turn_completed"))
            application.processEvents()
            self.assertIs(window.chat_activity_widget, first_activity)
            completed = window.chat_task_host.findChildren(
                QFrame, "chatActivityCompleted"
            )
            self.assertEqual(len(completed), 1)
            self.assertEqual(
                completed[0].findChild(QLabel, "chatActivityText").text(),
                "Planejamento e execução concluídos",
            )
            self.assertEqual(
                completed[0].findChild(QLabel, "chatActivityCount").text(),
                "5/5",
            )
            details = completed[0].findChild(QFrame, "chatActivitySteps")
            toggle = completed[0].findChild(QToolButton, "chatActivityToggle")
            self.assertTrue(details.isHidden())
            toggle.click()
            application.processEvents()
            self.assertFalse(details.isHidden())
            completed_steps = " ".join(
                step.text()
                for step in completed[0].findChildren(QLabel, "chatActivityStep")
            )
            self.assertIn("Trabalhando", completed_steps)
            self.assertNotIn(raw_command, completed_steps)
            close = completed[0].findChild(QToolButton, "chatActivityClose")
            close.click()
            application.processEvents()
            self.assertIsNone(window.chat_activity_widget)
            self.assertTrue(window.chat_task_host.isHidden())
            window._show_chat_activity("Não deve reabrir nesta execução")
            self.assertIsNone(window.chat_activity_widget)
            window._begin_chat_activity_turn()
            window._show_chat_activity("Nova execução")
            self.assertIsNotNone(window.chat_activity_widget)
            self.assertFalse(window.chat_task_host.isHidden())
        finally:
            window.close()

    def test_chat_link_handler_opens_only_http_and_https(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            browser = window._add_message(
                "assistant",
                "[Wiki](https://wiki.example/fonte) [KB](http://kb.example/fonte)",
            )
            with patch(
                "vrsoft_extractor.mary.ui.QDesktopServices.openUrl",
                return_value=True,
            ) as opener:
                for value in (
                    "https://wiki.example/fonte",
                    "http://kb.example/fonte",
                    "file:///C:/segredo.txt",
                    "javascript:alert(1)",
                    "powershell:Start-Process",
                    "C:/programa.exe",
                ):
                    browser.anchorClicked.emit(QUrl(value))
                application.processEvents()
                self.assertTrue(open_safe_external_url("https://wiki.example/fonte"))
                self.assertFalse(open_safe_external_url("file:///C:/segredo.txt"))
                self.assertFalse(open_safe_external_url("javascript:alert(1)"))
                self.assertEqual(opener.call_count, 3)
        finally:
            window.close()

    def test_chat_fenced_code_uses_t3_style_card_with_copy_and_highlighting(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            message = window._add_message(
                "assistant",
                "## Mudança estrutural\n\n```python\n"
                "if orchestration.enabled:\n"
                "    run_vr_orchestration()\n"
                "else:\n"
                "    run_native_provider()\n```",
            )
            application.processEvents()

            self.assertIsInstance(message, MarkdownMessageWidget)
            block = message.findChild(CodeBlockWidget, "codeBlockCard")
            self.assertIsNotNone(block)
            self.assertEqual(block.language, "python")
            self.assertEqual(block.editor.font().family(), "Consolas")
            self.assertNotIn("```", message.toPlainText())
            block.copy_code()
            self.assertIn("run_vr_orchestration", QApplication.clipboard().text())
        finally:
            window.close()

    def test_assistant_message_uses_t3_style_without_redundant_role_header(self):
        from PySide6.QtWidgets import QApplication, QLabel

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.provider_combo.setCurrentText("codex")
            native = window._add_message(
                "assistant", "Resposta direta.", response_mode="native"
            )
            vr = window._add_message(
                "assistant", "Resposta com a VR.", response_mode="vr"
            )
            application.processEvents()

            native_label = native.parentWidget().findChild(QLabel, "messageRole")
            vr_label = vr.parentWidget().findChild(QLabel, "messageRole")
            self.assertIsNone(native_label)
            self.assertIsNone(vr_label)
            self.assertEqual(
                native.parentWidget().accessibleName(),
                "Resposta do assistente",
            )
            self.assertEqual(
                vr.parentWidget().accessibleName(),
                "Resposta do assistente",
            )
        finally:
            window.close()

    def test_effective_effort_event_replaces_requested_value_in_chat(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.current_conversation = "effective-ui"
            window.effort_combo.clear()
            window.effort_combo.addItem("Máximo", "max")
            window.effort_combo.setCurrentIndex(0)
            window._on_runtime_event(
                RuntimeEvent(
                    "effective-ui",
                    "settings_updated",
                    payload={
                        "threadId": "native-1",
                        "threadSettings": {
                            "model": "gpt-5.6",
                            "effort": "xhigh",
                        },
                    },
                )
            )
            application.processEvents()

            self.assertEqual(window.effort_combo.currentData(), "xhigh")
            self.assertEqual(window.chat_status.text(), "Esforço efetivo: Muito alto")
        finally:
            window.close()

    def test_conversation_is_created_only_after_sending_typed_text(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        try:
            window.provider_combo.blockSignals(True)
            window.provider_combo.setCurrentText("codex")
            window.provider_combo.blockSignals(False)
            project = (self.root / "projetos" / "digitacao").resolve()
            project.mkdir(parents=True)
            window._select_project_scope(project)
            window.show()
            window._navigate(window.pages["Chat VR"])
            application.processEvents()
            with patch.object(window.pool, "start") as start:
                QTest.mouseClick(window.composer.viewport(), Qt.LeftButton)
                application.processEvents()
                start.assert_not_called()
                QTest.keyClicks(window.composer, "a")
                application.processEvents()
                start.assert_not_called()
                self.assertFalse(window._conversation_creation_in_progress)

                window.send_message()
                start.assert_called_once()
                worker = start.call_args.args[0]
                self.assertEqual(worker.args[1], "codex")
                self.assertEqual(worker.args[2], "")
                self.assertEqual(worker.args[4], "")
                self.assertTrue(window._conversation_creation_in_progress)
        finally:
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.close()

    def test_typing_without_an_available_conversation_remains_local_until_send(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        saved_current = window.app_preferences.value("chat/current_project", "")
        saved_recent = window.app_preferences.value("chat/recent_projects", "[]")
        saved_hidden = window.app_preferences.value("chat/hidden_projects", "[]")
        saved_projects = window.app_preferences.value("chat/projects", "[]")
        try:
            project = (self.root / "projetos" / "rascunho").resolve()
            project.mkdir(parents=True)
            window._select_project_scope(project)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.current_conversation = ""
            window.draft_conversation = False
            application.processEvents()

            with patch.object(window.pool, "start") as start:
                window.composer.setPlainText("teste")
                application.processEvents()
                start.assert_not_called()
                self.assertFalse(window.draft_conversation)
                self.assertFalse(window._conversation_creation_in_progress)
                self.assertEqual(window.composer.toPlainText(), "teste")

                window.send_message()
                start.assert_called_once()
                self.assertTrue(window.draft_conversation)
                self.assertTrue(window._conversation_creation_in_progress)
        finally:
            window.app_preferences.setValue("chat/current_project", saved_current)
            window.app_preferences.setValue("chat/recent_projects", saved_recent)
            window.app_preferences.setValue("chat/hidden_projects", saved_hidden)
            window.app_preferences.setValue("chat/projects", saved_projects)
            window.close()

    def test_chat_header_controls_align_with_sidebar_top(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            application.processEvents()

            tops = [
                widget.mapTo(window, QPoint(0, 0)).y()
                for widget in (
                    window.new_chat_button,
                    window.chat_sidebar_toggle_button,
                    window.surface_toggle_button,
                )
            ]
            self.assertLessEqual(max(tops) - min(tops), 4)
        finally:
            window.close()

    def test_chat_surface_panel_exposes_requested_functions_only(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window._set_surface_panel_visible(True)
            application.processEvents()

            self.assertTrue(window.chat_surface_panel.isVisible())
            self.assertTrue(window.surface_toggle_button.isChecked())
            self.assertEqual(
                set(window.chat_surface_buttons),
                {"browser", "terminal", "files", "agents"},
            )
            labels = " ".join(
                button.text() for button in window.chat_surface_buttons.values()
            )
            self.assertNotIn("Diff", labels)
            self.assertNotIn("Pull request", labels)
            self.assertTrue(
                all(
                    not button.icon().isNull()
                    for button in window.chat_surface_buttons.values()
                )
            )

            window.chat_surface_buttons["files"].click()
            application.processEvents()
            self.assertIs(
                window.chat_surface_stack.currentWidget(),
                window.surface_files_page,
            )
            self.assertIsNotNone(window.surface_file_model)
            self.assertEqual(window.surface_title.text(), "Files")

            window._show_surface_home()
            window.chat_surface_buttons["browser"].click()
            application.processEvents()
            self.assertIs(
                window.chat_surface_stack.currentWidget(),
                window.surface_browser_page,
            )
            self.assertIsNone(window.surface_browser_view)
            self.assertEqual(window.surface_title.text(), "Browser")
        finally:
            window.close()

    @unittest.skipUnless(os.name == "nt", "PowerShell surface requires Windows")
    def test_chat_terminal_and_files_run_inside_surface_panel(self):
        from PySide6.QtCore import QElapsedTimer, QProcess
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])

            window._activate_surface("terminal")
            self.assertNotEqual(
                window.surface_terminal_process.state(), QProcess.NotRunning
            )
            marker = "__VR_EMBEDDED_TERMINAL_OK__"
            window.surface_terminal_input.setText(
                f'Write-Output "{marker}"'
            )
            window._surface_terminal_submit()
            timer = QElapsedTimer()
            timer.start()
            while (
                marker not in window.surface_terminal_output.toPlainText()
                and timer.elapsed() < 5000
            ):
                application.processEvents()
                QTest.qWait(40)
            self.assertIn(
                marker, window.surface_terminal_output.toPlainText()
            )
            self.assertIs(
                window.chat_surface_stack.currentWidget(),
                window.surface_terminal_page,
            )

            window._activate_surface("files")
            target = window._surface_workspace() / "pyproject.toml"
            target.write_text(
                '[project]\nname = "embedded-surface-test"\n',
                encoding="utf-8",
            )
            window._refresh_surface_files()
            source_index = window.surface_file_model.index(str(target))
            timer.restart()
            while not source_index.isValid() and timer.elapsed() < 3000:
                application.processEvents()
                QTest.qWait(40)
                source_index = window.surface_file_model.index(str(target))
            self.assertTrue(source_index.isValid())
            window._surface_file_activated(
                window.surface_file_proxy.mapFromSource(source_index)
            )
            self.assertIn(
                "[project]", window.surface_file_preview.toPlainText()
            )
            self.assertIs(
                window.chat_surface_stack.currentWidget(),
                window.surface_files_page,
            )
        finally:
            window.close()

    def test_chat_browser_loads_local_page_inside_surface_panel(self):
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        import vrsoft_extractor.mary.ui as mary_ui

        if mary_ui.QWebEngineView is None:
            self.skipTest("Qt WebEngine is unavailable")
        preview = self.app / "embedded-browser.html"
        preview.write_text(
            "<html><head><title>VR Browser Test</title></head>"
            "<body>Browser interno ativo</body></html>",
            encoding="utf-8",
        )
        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window._activate_surface("browser")
            window.surface_browser_address.setText(preview.resolve().as_uri())
            window._surface_browser_navigate()

            timer = QElapsedTimer()
            timer.start()
            while (
                window.surface_browser_view.title() != "VR Browser Test"
                and timer.elapsed() < 8000
            ):
                application.processEvents()
                QTest.qWait(50)
            self.assertEqual(
                window.surface_browser_view.title(), "VR Browser Test"
            )
            self.assertIs(
                window.surface_browser_content.currentWidget(),
                window.surface_browser_view,
            )
            self.assertEqual(
                Path(window.surface_browser_view.url().toLocalFile()).resolve(),
                preview.resolve(),
            )
        finally:
            window.close()

    def test_chat_landing_is_centered_and_markdown_has_visual_hierarchy(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1200, 800)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.new_conversation()
            application.processEvents()

            empty_top = window.chat_empty_state.mapTo(window, QPoint(0, 0)).y()
            composer_bottom = (
                window.composer_host.mapTo(window, QPoint(0, 0)).y()
                + window.composer_host.height()
            )
            landing_center = (empty_top + composer_bottom) // 2
            scroll_top = window.message_scroll.mapTo(window, QPoint(0, 0)).y()
            scroll_bottom = scroll_top + window.message_scroll.height()
            self.assertLess(abs(landing_center - ((scroll_top + scroll_bottom) // 2)), 45)
            self.assertTrue(window._composer_in_landing)
            self.assertLessEqual(window.composer_card.maximumWidth(), 770)

            browser = window._add_message(
                "assistant",
                "## Resultado\n\n- **Ponto importante:** use `codigo`.\n\n"
                "> Observação validada.\n\n[Documentação](https://example.com)",
            )
            css = browser.document().defaultStyleSheet()
            self.assertIn("strong", css)
            self.assertIn("code", css)
            self.assertIn("blockquote", css)
            self.assertIn("Resultado", browser.toPlainText())
            self.assertIn("Ponto importante", browser.toPlainText())
        finally:
            window.close()

    def test_markdown_repairs_glued_sentences_but_preserves_inline_code(self):
        from PySide6.QtWidgets import QApplication, QTextBrowser

        application = QApplication.instance() or QApplication([])
        apply_application_theme(application, "dark_orange")
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            widget = window._add_message(
                "assistant",
                "sem presumir a versão.Para continuar, use `arquivo.MD`.",
            )
            self.assertFalse(window._composer_in_landing)
            self.assertIn("versão. Para continuar", widget.toPlainText())
            self.assertIn("arquivo.MD", widget.toPlainText())
            browser = widget.findChild(QTextBrowser, "messageBody")
            code_backgrounds = []
            block = browser.document().firstBlock()
            while block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.charFormat().fontFixedPitch():
                        code_backgrounds.append(
                            fragment.charFormat().background().color().name()
                        )
                    iterator += 1
                block = block.next()
            self.assertIn("#202023", code_backgrounds)
            self.assertEqual(browser.document().indentWidth(), 22)
        finally:
            window.close()
            apply_application_theme(application, "light")

    def test_chat_activity_keeps_short_status_on_one_readable_row(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1200, 800)
            window.show()
            window._navigate(window.pages["Chat VR"])
            window._show_chat_activity("Executando uma ação")
            application.processEvents()
            self.assertGreaterEqual(window.chat_activity_widget.minimumWidth(), 240)
            self.assertLessEqual(window.chat_activity_label.height(), 28)
        finally:
            window.close()

    def test_long_markdown_message_expands_without_clipping(self):
        from PySide6.QtWidgets import QApplication, QTextBrowser

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Chat VR"])
            browser_host = window._add_message(
                "assistant",
                "\n\n".join(f"Parágrafo {index}: conteúdo validado." for index in range(180)),
            )
            application.processEvents()

            browser = browser_host.findChild(QTextBrowser, "messageBody")
            self.assertIsNotNone(browser)
            self.assertGreater(browser.height(), 1200)
            self.assertGreaterEqual(
                browser.height(),
                int(browser.document().size().height()),
            )
        finally:
            window.close()

    def test_slash_palette_exposes_build_as_integrated_default(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QListWidgetItem

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.show()
            window._navigate(window.pages["Chat VR"])
            application.processEvents()
            with (
                patch.object(window, "_request_slash_catalogs"),
                patch.object(window, "_ensure_draft_conversation"),
            ):
                window.composer.setPlainText("/")
                QTest.qWait(50)
                self.assertTrue(window.slash_palette.isVisible())
                commands = [
                    window.slash_palette.list.item(index).text().splitlines()[0]
                    for index in range(window.slash_palette.list.count())
                ]
                self.assertNotIn("/plan", commands)
                self.assertNotIn("/build", commands)
                self.assertIn("/tools", commands)
                self.assertIn("/provider", commands)
                self.assertIn("/tier", commands)
                self.assertIn("/context", commands)
            self.assertEqual(window.mode_combo.currentData(), "default")
            self.assertEqual(window.mode_combo.count(), 1)
            self.assertTrue(window.options_button.isHidden())

            conversation_id = window.database.create_conversation(
                "Legado Plan",
                "codex",
                "gpt-test",
                self.settings.work_dir / "inline",
                collaboration_mode="plan",
            )
            item = QListWidgetItem("Legado Plan")
            item.setData(Qt.UserRole, conversation_id)
            with patch.object(window, "load_models"):
                window.load_conversation(item, None)
            self.assertEqual(
                window.database.get_conversation(conversation_id)["collaboration_mode"],
                "default",
            )
        finally:
            window.close()

    def test_at_file_picker_finds_attaches_and_sends_project_file_reference(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextCursor
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        document = self.settings.root / "documentos" / "manual operacional.md"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text("Conteúdo de referência", encoding="utf-8")
        ignored = self.settings.root / ".git" / "segredo.txt"
        ignored.parent.mkdir(parents=True, exist_ok=True)
        ignored.write_text("ignorar", encoding="utf-8")

        catalog_result = MainWindow._file_catalog_request(7, self.settings.root)
        relative_paths = {item["relative"] for item in catalog_result["files"]}
        self.assertIn("documentos/manual operacional.md", relative_paths)
        self.assertNotIn(".git/segredo.txt", relative_paths)

        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            conversation_id = window.database.create_conversation(
                "Arquivos", "codex", "gpt-test", self.settings.work_dir / "files"
            )
            window.current_conversation = conversation_id
            window.draft_conversation = False
            window.file_catalog = list(catalog_result["files"])
            window._file_catalog_state = "ready"
            window.show()
            window._navigate(window.pages["Chat VR"])
            window.composer.setPlainText("@manual")
            window.composer.moveCursor(QTextCursor.End)
            window._slash_text_changed()
            application.processEvents()

            self.assertTrue(window.slash_palette.isVisible())
            file_item = next(
                window.slash_palette.list.item(index)
                for index in range(window.slash_palette.list.count())
                if (window.slash_palette.list.item(index).data(Qt.UserRole) or {}).get(
                    "kind"
                )
                == "file"
            )
            self.assertIn("manual operacional.md", file_item.text())
            window.slash_palette.list.setCurrentItem(file_item)
            window.slash_palette.activate_current()
            application.processEvents()

            self.assertEqual(window.composer.toPlainText(), "")
            self.assertEqual(len(window.pending_file_mentions), 1)
            self.assertEqual(
                window.pending_file_mentions[0]["relative"],
                "documentos/manual operacional.md",
            )
            self.assertTrue(window.composer_chips.isVisible())

            window.vr_flow_button.setChecked(False)
            with patch.object(window.orchestrator, "send") as send:
                window._send_current_message("Resuma o arquivo")
            provider_text = send.call_args.args[1]
            display_text = send.call_args.args[4]
            self.assertIn("ARQUIVOS REFERENCIADOS PELO USUÁRIO", provider_text)
            self.assertIn(
                json.dumps(str(document.resolve()), ensure_ascii=False),
                provider_text,
            )
            self.assertIn("dados não confiáveis", provider_text)
            self.assertIn("@documentos/manual operacional.md", display_text)
            self.assertFalse(send.call_args.args[6])
            self.assertEqual(window.pending_file_mentions, [])
            window.vr_flow_button.setChecked(True)
        finally:
            window.close()

    def test_new_chat_restores_the_last_selected_model(self):
        from PySide6.QtWidgets import QApplication

        class MemoryPreferences:
            def __init__(self):
                self.values = {}

            def value(self, key, default=None):
                return self.values.get(key, default)

            def setValue(self, key, value):
                self.values[key] = value

            def contains(self, key):
                return key in self.values

            def sync(self):
                pass

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.app_preferences = MemoryPreferences()
            window.provider_combo.blockSignals(True)
            window.provider_combo.setCurrentText("codex")
            window.provider_combo.blockSignals(False)
            models = [
                {"id": "gpt-a", "displayName": "GPT A", "isDefault": True},
                {"id": "gpt-b", "displayName": "GPT B"},
            ]
            window.model_cache["codex"] = models
            window._apply_model_catalog("codex", models)
            window._model_picker_selected("codex", "gpt-b")

            self.assertEqual(
                window.app_preferences.values["chat/last_provider"], "codex"
            )
            self.assertEqual(
                window.app_preferences.values["chat/last_model/codex"], "gpt-b"
            )
            window.model_combo.blockSignals(True)
            window.model_combo.setCurrentIndex(window.model_combo.findData("gpt-a"))
            window.model_combo.blockSignals(False)
            window.new_conversation()
            application.processEvents()
            self.assertEqual(window.model_combo.currentData(), "gpt-b")
        finally:
            window.close()

    def test_chat_image_drop_stages_previews_sends_and_removes_images(self):
        from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
        from PySide6.QtGui import QColor, QDropEvent, QPixmap
        from PySide6.QtWidgets import QApplication, QPushButton

        application = QApplication.instance() or QApplication([])
        image = self.root / "captura de tela.png"
        pixmap = QPixmap(80, 50)
        pixmap.fill(QColor("#FF7200"))
        self.assertTrue(pixmap.save(str(image), "PNG"))
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            conversation_id = window.database.create_conversation(
                "Imagem", "codex", "gpt-test", self.settings.work_dir / "images"
            )
            window.current_conversation = conversation_id
            window.draft_conversation = False
            self.assertFalse(hasattr(window, "attach_image_button"))
            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(str(image))])
            drop = QDropEvent(
                QPointF(10, 10),
                Qt.CopyAction,
                mime_data,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            self.assertTrue(window.eventFilter(window.composer.viewport(), drop))
            self.assertEqual(window.pending_file_mentions[0]["kind"], "image")
            staged = Path(window.pending_file_mentions[0]["path"])
            self.assertTrue(staged.is_file())
            self.assertFalse(window.composer_chips.isHidden())
            chip = window.composer_chips.findChildren(QPushButton)[0]
            self.assertFalse(chip.icon().isNull())

            window._remove_pending_file(window.pending_file_mentions[0])
            self.assertFalse(staged.exists())
            self.assertEqual(window._stage_chat_images([image]), 1)
            window.vr_flow_button.setChecked(False)
            with patch.object(window.orchestrator, "send") as send:
                window._send_current_message("O que aparece nesta imagem?")

            image_paths = send.call_args.kwargs["image_paths"]
            self.assertEqual(len(image_paths), 1)
            self.assertIn(conversation_id, image_paths[0])
            self.assertIn("![captura de tela.png]", send.call_args.args[4])
            self.assertIn("IMAGEM @", send.call_args.args[1])
            self.assertEqual(window.pending_file_mentions, [])
        finally:
            window.close()

    def test_running_conversation_indicator_uses_theme_integrated_palette(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            delegate = window.conversation_activity_delegate
            light = delegate.activity_colors(False, False)
            dark = delegate.activity_colors(True, False)
            selected = delegate.activity_colors(True, True)
            self.assertEqual(light[0].name(), "#eeeff3")
            self.assertEqual(dark[0].name(), "#24201d")
            self.assertNotEqual(dark[0].name(), selected[0].name())
            self.assertNotEqual(dark[2].name(), dark[0].name())
        finally:
            window.close()

    def test_slash_skill_is_one_turn_attachment_and_tool_change_has_no_modal(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            conversation_id = window.database.create_conversation(
                "Slash", "codex", "gpt-test", self.settings.work_dir / "slash"
            )
            window.current_conversation = conversation_id
            window.draft_conversation = False
            skill = {
                "name": "review",
                "displayName": "Code Review",
                "path": str(self.settings.root / "skills" / "review" / "SKILL.md"),
            }
            window.pending_skills = [skill]
            with patch.object(window.orchestrator, "send") as send:
                window._send_current_message("Analise este patch")
            self.assertEqual(send.call_args.args[3], [skill])
            self.assertEqual(
                send.call_args.args[4], "/review Analise este patch"
            )
            self.assertEqual(window.pending_skills, [])

            tool = {
                "id": "tool-id",
                "name": "consulta_vr",
                "description": "Consulta local",
            }
            with (
                patch.object(window.pool, "start") as start,
                patch("vrsoft_extractor.mary.ui.ConfirmDialog.ask") as question,
            ):
                window._toggle_slash_tool(
                    {"kind": "local_tool", "id": "tool-id", "payload": tool}
                )
            question.assert_not_called()
            start.assert_called_once()
            worker = start.call_args.args[0]
            self.assertEqual(worker.function, window.orchestrator.configure_tools)
            self.assertEqual(worker.args[0], conversation_id)
            self.assertEqual(worker.args[1], ["tool-id"])
        finally:
            window.close()

    def test_delete_conversation_confirms_only_permanent_removal(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.current_conversation = "conversation-id"
            with (
                patch.object(window, "_run_conversation_operation") as operation,
                patch(
                    "vrsoft_extractor.mary.ui.ConfirmDialog.ask"
                ) as confirmation,
            ):
                window.conversation_state = "active"
                window.delete_current_conversation()
                self.assertEqual(operation.call_args.args[0], window.orchestrator.trash)
                confirmation.assert_not_called()

                operation.reset_mock()
                window.conversation_state = "trash"
                confirmation.return_value = False
                window.delete_current_conversation()
                operation.assert_not_called()

                confirmation.return_value = True
                window.delete_current_conversation()
                self.assertEqual(operation.call_args.args[0], window.orchestrator.purge)
                self.assertEqual(
                    confirmation.call_args.kwargs["confirmation_phrase"], "EXCLUIR"
                )
        finally:
            window.close()

    def test_archive_conversation_completes_without_navigating_away(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.project_scope_path = None
            conversation_id = window.database.create_conversation(
                "Arquivar agora",
                "claude",
                "claude-test",
                self.settings.work_dir / "pending",
            )
            workspace = self.settings.work_dir / conversation_id
            workspace.mkdir(parents=True, exist_ok=True)
            window.database.update_conversation(
                conversation_id,
                workspace=str(workspace),
            )
            window.refresh_conversations()
            item = next(
                window.conversation_list.item(index)
                for index in range(window.conversation_list.count())
                if window.conversation_list.item(index).data(Qt.UserRole)
                == conversation_id
            )
            window.conversation_list.setCurrentItem(item)
            application.processEvents()

            window.archive_current_conversation()
            for _attempt in range(100):
                application.processEvents()
                if (
                    window.database.get_conversation(conversation_id)["archived"]
                    and not window.current_conversation
                ):
                    break
                QTest.qWait(10)

            self.assertEqual(
                window.database.get_conversation(conversation_id)["archived"], 1
            )
            self.assertEqual(window.current_conversation, "")
            self.assertEqual(window.conversation_list.count(), 0)
            self.assertNotIn(conversation_id, window._conversation_operations)
        finally:
            window.close()

    def test_stale_conversation_operation_does_not_clear_new_selection(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.current_conversation = "conversation-new"
            window._conversation_operations.add("conversation-old")
            window._conversation_operation_done("conversation-old")
            application.processEvents()

            self.assertEqual(window.current_conversation, "conversation-new")
            self.assertNotIn("conversation-old", window._conversation_operations)
        finally:
            window.close()

    def test_review_ui_offscreen_filters_and_previews_document(self):
        from PySide6.QtWidgets import QApplication

        database = initialize_workspace(self.settings)
        self._queue_review(
            database,
            "ui-review",
            source="kb",
            suggested_module="PDV",
            confidence=0.42,
            product="VRPdv",
            category="TEF",
            reasons=["pinpad (título)"],
        )
        self._queue_review(
            database,
            "ui-review-2",
            source="kb",
            suggested_module="Fiscal",
            confidence=0.55,
            product="VRAdm",
            category="Tributação",
            reasons=["tributação (título)"],
        )
        application = QApplication.instance() or QApplication([])
        window = MainWindow(self.settings, smoke_test=True)
        try:
            window.resize(1366, 768)
            window.show()
            window._navigate(window.pages["Revisão"])
            application.processEvents()
            self.assertTrue(window.review_filters_panel.isHidden())
            self.assertEqual(window.review_filters_button.text(), "Filtros")
            window.review_filters_button.click()
            application.processEvents()
            self.assertTrue(window.review_filters_panel.isVisible())
            self.assertEqual(window.review_table.rowCount(), 2)
            self.assertIn("Documento ui-review", window.review_detail_title.text())
            self.assertIn("pinpad", window.review_preview.toPlainText())
            self.assertTrue(window.review_approve.isVisible())
            self.assertLessEqual(
                window.review_reopen.geometry().right(),
                window.review_reopen.parentWidget().width(),
            )
            window.select_all_reviews()
            self.assertEqual(len(window._checked_review_rows()), 2)
            self.assertTrue(window.review_approve.isEnabled())
            self.assertIn("2 itens receberão", window.review_action_hint.text())
            window.clear_review_selection()
            self.assertEqual(len(window._checked_review_rows()), 0)
            window.review_source.setCurrentIndex(
                window.review_source.findData("wiki")
            )
            application.processEvents()
            self.assertEqual(window.review_filters_button.text(), "Filtros · 1")
            self.assertEqual(window.review_table.rowCount(), 0)
            window.review_source.setCurrentIndex(
                window.review_source.findData("kb")
            )
            application.processEvents()
            self.assertEqual(window.review_table.rowCount(), 2)
        finally:
            window.close()

    def test_video_filters_sync_schedule_and_opencode_plan_controls(self):
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        with patch.object(MainWindow, "_refresh_all"):
            window = MainWindow(
                self.settings,
                smoke_test=False,
                auto_close_smoke=False,
            )
        try:
            self.assertFalse(window._auto_sync_enabled)
            self.assertFalse(window.auto_sync_timer.isActive())
            with patch.object(window, "sync_wiki_kb") as sync_wiki_kb:
                window.start_scheduled_sync()
            sync_wiki_kb.assert_called_once_with()
            self.assertTrue(window._auto_sync_enabled)
            window._schedule_next_auto_sync()
            self.assertTrue(window.auto_sync_timer.isActive())
            window.auto_sync_timer.stop()

            window.show()
            window._navigate(window.pages["Vídeos"])
            application.processEvents()
            self.assertTrue(window.video_filters_panel.isHidden())
            window.video_filters_button.click()
            application.processEvents()
            self.assertTrue(window.video_filters_panel.isVisible())
            window.video_status_filter.setCurrentIndex(
                window.video_status_filter.findData("downloaded")
            )
            self.assertEqual(window.video_filters_button.text(), "Filtros · 1")

            window.provider_combo.blockSignals(True)
            window.provider_combo.setCurrentText("opencode")
            window.provider_combo.blockSignals(False)
            window._update_codex_controls()
            self.assertFalse(window.options_button.isEnabled())
            self.assertTrue(window.options_button.isHidden())
            self.assertEqual(window.mode_combo.currentData(), "default")
        finally:
            window.close()

    def test_provider_switch_keeps_conversation_and_transfers_history(self):
        class FakeProvider:
            def __init__(self):
                self.prompts = []

            def available(self):
                return True

            def start_conversation(self, *_args):
                return "native-claude"

            def send_message(self, *args):
                self.prompts.append(args[5])

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        codex = FakeProvider()
        claude = FakeProvider()
        orchestrator.providers = {"codex": codex, "claude": claude}
        conversation_id = orchestrator.new_conversation(
            "codex", "gpt-test", defer_provider_start=True
        )
        database.update_conversation(conversation_id, native_id="native-codex")
        database.add_message(conversation_id, "user", "Criar treinamento de PIX")
        database.add_message(
            conversation_id, "assistant", "Use a rotina financeira."
        )

        switched = orchestrator.switch_provider(
            conversation_id, "claude", "claude-test", "high"
        )
        row = database.get_conversation(conversation_id)
        self.assertEqual(switched, conversation_id)
        self.assertEqual(row["provider"], "claude")
        self.assertEqual(row["model"], "claude-test")
        self.assertEqual(row["effort"], "high")
        self.assertEqual(row["native_id"], "")

        orchestrator.send(
            conversation_id, "Continue o trabalho", lambda _event: None
        )
        for _ in range(100):
            if claude.prompts:
                break
            import time

            time.sleep(0.005)
        self.assertIn("CONTEXTO TRANSFERIDO", claude.prompts[-1])
        self.assertIn("Criar treinamento de PIX", claude.prompts[-1])

    def test_mary_search_is_automatic_for_codex_claude_and_optional_prefix(self):
        class FakeProvider:
            def __init__(self, native_id):
                self.native_id = native_id
                self.prompts = []

            def available(self):
                return True

            def start_conversation(self, *_args):
                return self.native_id

            def send_message(self, *args):
                self.prompts.append(args[5])

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        database.upsert_document(
            KnowledgeDocument(
                source="wiki",
                source_id="3742",
                title="Funcao 102",
                url="https://wiki.example/index.php?title=Funcao_102",
                markdown=(
                    "Função de entrada do operador. Atalho O; estado FECHADO PARCIAL."
                ),
                module="PDV",
                review_status="approved",
                content_hash="automatic-102",
                local_path="conhecimento/PDV/Wiki/funcao-102--3742.md",
            )
        )
        orchestrator = ChatOrchestrator(self.settings, database)
        codex = FakeProvider("native-codex")
        claude = FakeProvider("native-claude")
        orchestrator.providers = {"codex": codex, "claude": claude}

        for provider_name, prefix, provider in (
            ("codex", "", codex),
            ("claude", "Mary: ", claude),
        ):
            conversation_id = orchestrator.new_conversation(
                provider_name, defer_provider_start=True
            )
            typed = prefix + "Qual a função de entrada do operador?"
            provider_text = (
                typed
                + "\n\nINSTRUÇÕES INTERNAS DE ANEXOS E SKILLS: "
                + "planilha fiscal cadastro fornecedor não usar na busca."
            )
            orchestrator.send(
                conversation_id,
                provider_text,
                lambda _event: None,
                search_text=typed,
            )
            for _ in range(100):
                if provider.prompts:
                    break
                import time

                time.sleep(0.005)
            prompt = provider.prompts[-1]
            self.assertEqual(prompt.count("CONTEXTO LOCAL VR"), 1)
            self.assertIn("[Funcao 102](https://wiki.example", prompt)
            self.assertNotIn("funcao-102--3742.md", prompt)
            self.assertIn("Atalho O", prompt)

    def test_disabled_vr_flow_sends_plain_prompt_without_local_search(self):
        class FakeProvider:
            def __init__(self):
                self.prompts = []

            def available(self):
                return True

            def start_conversation(self, *_args):
                return "native-plain"

            def send_message(self, *args):
                self.prompts.append(args[5])

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        provider = FakeProvider()
        orchestrator.providers["codex"] = provider
        conversation_id = orchestrator.new_conversation(
            "codex", defer_provider_start=True
        )
        with patch.object(database, "search") as local_search:
            orchestrator.send(
                conversation_id,
                "Responda apenas com a LLM.",
                lambda _event: None,
                use_vr=False,
            )
            for _ in range(100):
                if provider.prompts:
                    break
                import time

                time.sleep(0.005)

        local_search.assert_not_called()
        self.assertEqual(provider.prompts[-1], "Responda apenas com a LLM.")

    def test_short_continuation_keeps_previous_user_subject(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        conversation_id = database.create_conversation(
            "Continuação", "codex", "", self.settings.work_dir / "continuacao"
        )
        database.add_message(
            conversation_id,
            "user",
            "Qual a função de entrada do operador?",
        )

        query = orchestrator._local_search_query(
            "Mas qual a função?", database.messages(conversation_id)
        )

        self.assertEqual(
            search_terms(query), ["funcao", "entrada", "operador"]
        )

    def test_missing_or_ambiguous_local_sources_forbid_high_confidence(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        with patch.object(database, "search", return_value=[]):
            missing = orchestrator._enrich_prompt("Pergunta sem fonte", "sem fonte")
        self.assertIn("nenhuma fonte validada", missing)
        self.assertIn("não invente referência", missing)
        self.assertIn("não invalida fatos e passos confirmados", missing)

        ambiguous_rows = [
            {
                "title": title,
                "url": f"https://example.com/{index}",
                "source": "wiki",
                "module": "PDV",
                "local_path": f"conhecimento/{index}.md",
                "excerpt": "Trecho",
                "matched_terms": ["teste"],
                "coverage": 1.0,
                "confidence": 0.9,
                "score": score,
            }
            for index, (title, score) in enumerate((("Fonte A", 100), ("Fonte B", 95)))
        ]
        with patch.object(database, "search", return_value=ambiguous_rows):
            ambiguous = orchestrator._enrich_prompt("Teste", "teste")
        self.assertIn("diferem menos de 10%", ambiguous)
        self.assertIn("não apresente a conclusão com confiança alta", ambiguous)

    def test_local_search_error_is_not_reported_as_no_results(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        with patch.object(database, "search", side_effect=RuntimeError("offline")):
            enriched = orchestrator._enrich_prompt("Como configurar o PIX?")

        self.assertIn("ERRO AO CONSULTAR A BASE", enriched)
        self.assertIn("não significa ausência de resultados", enriched)
        self.assertNotIn("nenhuma fonte validada foi encontrada", enriched)

    def test_cloned_context_is_sent_on_first_turn(self):
        class FakeProvider:
            def __init__(self):
                self.prompts = []

            def available(self):
                return True

            def start_conversation(self, *_args):
                return "native"

            def send_message(self, *args):
                self.prompts.append(args[5])

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        fake = FakeProvider()
        orchestrator.providers = {"codex": fake, "claude": fake}
        source = orchestrator.new_conversation("codex")
        database.add_message(source, "user", "Criar treinamento de PIX")
        database.add_message(source, "assistant", "Use a rotina financeira.")
        clone = orchestrator.clone(source, "claude")
        orchestrator.send(clone, "Continue o trabalho", lambda _event: None)
        for _ in range(100):
            if fake.prompts:
                break
            import time

            time.sleep(0.005)
        self.assertIn("CONTEXTO TRANSFERIDO", fake.prompts[-1])
        self.assertIn("Criar treinamento de PIX", fake.prompts[-1])


if __name__ == "__main__":
    unittest.main()

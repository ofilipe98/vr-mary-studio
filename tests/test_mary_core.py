import json
import io
import os
import queue
import shutil
import sqlite3
import sys
import threading
import unittest
import urllib.parse
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from vrsoft_extractor.mary.classifier import classify, parse_product_catalog
from vrsoft_extractor.mary.chat_tools import (
    MAX_TOOL_OUTPUT_BYTES,
    ToolExecutionError,
    ToolValidationError,
    mcp_thread_config,
    run_local_tool,
    validate_tool_definition,
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


class MaryCoreTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(".test-tmp") / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
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

    def test_save_vr_env_round_trips_passwords_with_dotenv_metacharacters(self):
        from dotenv import dotenv_values
        from vrsoft_extractor.settings import load_dotenv_file

        secret = "abc # trecho-final 'com aspas' \\ caminho"
        save_vr_env(
            self.app,
            {
                "VR_ROOT": str(self.settings.root),
                "MOVIDESK_EMAIL": "user@example.com",
                "MOVIDESK_PASSWORD": secret,
                "ENDOO_EMAIL": "video@example.com",
                "ENDOO_PASSWORD": secret,
                "VR_SYNC_INTERVAL_MINUTES": "30",
                "VR_DEFAULT_EFFORT": "medium",
            },
        )

        values = dotenv_values(self.app / ".env")
        if os.name == "nt":
            self.assertEqual(values["MOVIDESK_PASSWORD"], "")
            self.assertEqual(values["ENDOO_PASSWORD"], "")
            protected = self.app / ".state" / "credentials.dpapi.json"
            self.assertTrue(protected.is_file())
            self.assertNotIn(secret, protected.read_text(encoding="utf-8"))
            with patch.dict(
                os.environ,
                {"MOVIDESK_PASSWORD": "", "ENDOO_PASSWORD": ""},
                clear=False,
            ):
                load_dotenv_file(self.app / ".env")
                self.assertEqual(os.environ["MOVIDESK_PASSWORD"], secret)
                self.assertEqual(os.environ["ENDOO_PASSWORD"], secret)
        else:
            self.assertEqual(values["MOVIDESK_PASSWORD"], secret)
            self.assertEqual(values["ENDOO_PASSWORD"], secret)

    @unittest.skipUnless(os.name == "nt", "A migração DPAPI é exclusiva do Windows")
    def test_load_dotenv_migrates_legacy_plaintext_passwords_to_dpapi(self):
        from dotenv import dotenv_values
        from vrsoft_extractor.settings import load_dotenv_file

        secret = "segredo-legado # com metacaractere"
        env_path = self.app / ".env"
        env_path.write_text(
            "MOVIDESK_EMAIL=movidesk@example.com\n"
            f"MOVIDESK_PASSWORD='{secret}'\n"
            "ENDOO_EMAIL=endoo@example.com\n"
            f"ENDOO_PASSWORD='{secret}'\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"MOVIDESK_PASSWORD": "", "ENDOO_PASSWORD": ""},
            clear=False,
        ):
            load_dotenv_file(env_path)
            self.assertEqual(os.environ["MOVIDESK_PASSWORD"], secret)
            self.assertEqual(os.environ["ENDOO_PASSWORD"], secret)

        values = dotenv_values(env_path)
        self.assertEqual(values["MOVIDESK_PASSWORD"], "")
        self.assertEqual(values["ENDOO_PASSWORD"], "")
        protected = self.app / ".state" / "credentials.dpapi.json"
        self.assertTrue(protected.is_file())
        self.assertNotIn(secret, protected.read_text(encoding="utf-8"))

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
        self.assertEqual(row["approval_profile"], "full_access")
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

    def test_search_page_reports_and_reaches_results_beyond_legacy_cap(self):
        database = MaryDatabase(self.settings.database_path)
        for index in range(501):
            database.upsert_document(
                KnowledgeDocument(
                    source="wiki",
                    source_id=f"audit-{index:03d}",
                    title=f"Termoauditoria documento {index:03d}",
                    url=f"https://example.com/audit-{index:03d}",
                    markdown=f"Conteúdo termoauditoria número {index:03d}.",
                    module="Fiscal",
                    review_status="approved",
                    content_hash=f"audit-hash-{index:03d}",
                    local_path=f"audit-{index:03d}.md",
                )
            )

        first, total = database.search_page("termoauditoria", limit=100, offset=0)
        last, last_total = database.search_page(
            "termoauditoria", limit=100, offset=500
        )

        self.assertEqual(total, 501)
        self.assertEqual(last_total, 501)
        self.assertEqual(len(first), 100)
        self.assertEqual(len(last), 1)

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
        self.assertEqual(params["approvalPolicy"], "never")

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

    def test_codex_uses_item_lifecycle_to_classify_commentary_and_final_answer(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        events = []
        provider._callbacks["local-1"] = events.append

        for item_id, phase, delta in (
            ("commentary-1", "commentary", "Vou verificar a versão."),
            ("final-1", "final_answer", "A versão foi confirmada."),
        ):
            provider._handle_server_message(
                {
                    "method": "item/started",
                    "params": {
                        "threadId": "native-1",
                        "item": {
                            "id": item_id,
                            "type": "agentMessage",
                            "phase": phase,
                            "text": "",
                        },
                    },
                }
            )
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

        deltas = [event for event in events if event.kind == "assistant_delta"]
        self.assertEqual([event.payload["phase"] for event in deltas], [
            "commentary",
            "final_answer",
        ])
        self.assertEqual(deltas[0].text, "Vou verificar a versão.")
        self.assertEqual(deltas[1].text, "A versão foi confirmada.")

    def test_codex_exposes_file_patch_updates_as_tool_events(self):
        provider = CodexProvider()
        provider._native_to_local["native-1"] = "local-1"
        events = []
        provider._callbacks["local-1"] = events.append

        provider._handle_server_message(
            {
                "method": "item/fileChange/patchUpdated",
                "params": {
                    "threadId": "native-1",
                    "turnId": "turn-1",
                    "itemId": "files-1",
                    "changes": [
                        {
                            "path": "tests/test_trace.py",
                            "kind": "add",
                            "diff": "@@ -0,0 +1 @@\n+ok = True\n",
                        }
                    ],
                },
            }
        )

        self.assertEqual(events[0].kind, "tool_event")
        self.assertEqual(events[0].payload["item"]["type"], "fileChange")
        self.assertEqual(
            events[0].payload["item"]["changes"][0]["path"],
            "tests/test_trace.py",
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
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(params["sandbox"], "danger-full-access")

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

                def rpc(method, params, timeout=45, **kwargs):
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
        warned = run_local_tool(stderr_only, {"name": "Mary"}, self.root)
        self.assertEqual(warned.text, "aviso")
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

        for used in (6000, 6000, 3000):
            orchestrator._handle_event(RuntimeEvent(conversation_id, "token_usage", payload={
                "tokenUsage": {"last": {"totalTokens": used}, "modelContextWindow": 128_000, "contextOnly": True}}))
        row = database.get_conversation(conversation_id)
        self.assertEqual(row["context_used_tokens"], 3000)
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


    def test_provider_switch_keeps_conversation_and_transfers_history(self):
        class FakeProvider:
            def __init__(self):
                self.prompts = []
                self.message_sent = threading.Event()

            def available(self):
                return True

            def start_conversation(self, *_args):
                return "native-claude"

            def send_message(self, *args):
                self.prompts.append(args[5])
                self.message_sent.set()

            def close(self):
                pass

        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        self.addCleanup(orchestrator.close)
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
        self.assertTrue(
            claude.message_sent.wait(5.0),
            "O provedor alternado não recebeu a mensagem dentro do prazo.",
        )
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

    def test_anaphoric_code_follow_up_keeps_the_original_business_subject(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        conversation_id = database.create_conversation(
            "Crossdocking", "codex", "", self.settings.work_dir / "crossdocking"
        )
        for role, content in (
            (
                "user",
                "Monte um fluxo completo de crossdocking e explique como usar no VRMaster.",
            ),
            ("assistant", "Segue o fluxo recuperado da documentação."),
            (
                "user",
                "Analise o código do VRMaster e valide essa informação que você me enviou.",
            ),
            ("assistant", "Não localizei o código."),
        ):
            database.add_message(conversation_id, role, content)

        query = orchestrator._local_search_query(
            "Tente validar o código fonte novamente.",
            database.messages(conversation_id),
        )

        self.assertIn("crossdocking", query.casefold())
        self.assertIn("valide essa informação", query.casefold())
        self.assertTrue(query.endswith("Tente validar o código fonte novamente."))

    def test_missing_or_ambiguous_local_sources_forbid_high_confidence(self):
        database = initialize_workspace(self.settings)
        orchestrator = ChatOrchestrator(self.settings, database)
        with patch.object(database, "search", return_value=[]):
            missing = orchestrator._enrich_prompt("Pergunta sem fonte", "sem fonte")
        self.assertIn("nenhuma fonte validada", missing)
        self.assertIn("não invente referência", missing)
        self.assertIn("não invalida fatos e passos confirmados", missing)
        self.assertIn('"clique neste botão"', missing)
        self.assertIn("Código Java decompilado e indexado", missing)

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

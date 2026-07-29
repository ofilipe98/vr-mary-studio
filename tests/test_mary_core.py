import json
import os
import sqlite3
import unittest
import urllib.parse
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from vrsoft_extractor.mary.classifier import classify, parse_product_catalog
from vrsoft_extractor.mary.classification_audit import audit_classification
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.content import canonical_markdown, html_to_markdown, sha256_text
from vrsoft_extractor.mary.db import MaryDatabase, _fts_query
from vrsoft_extractor.mary.migration import build_manifest, migrate
from vrsoft_extractor.mary.models import KnowledgeDocument, ReviewFilters
from vrsoft_extractor.mary.movidesk import (
    MovideskInteractiveLoginRequired,
    MovideskSync,
)
from vrsoft_extractor.mary.providers import CodexProvider, _resolve_codex_command
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.ocr import latest_windows_installer_url
from vrsoft_extractor.mary.workspace import initialize_workspace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from vrsoft_extractor.mary.ui import (
    ACCESSIBLE_ORANGE,
    BACKGROUND,
    BRAND_NAVY,
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
        database.update_conversation(conversation_id, effort="xhigh")
        self.assertEqual(database.get_conversation(conversation_id)["effort"], "xhigh")

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

    def test_selects_latest_tesseract_windows_installer(self):
        listing = (
            '<a href="tesseract-ocr-w64-setup-5.3.0.exe">old</a>'
            '<a href="tesseract-ocr-w64-setup-5.5.0.exe">new</a>'
        )
        url = latest_windows_installer_url(listing, "https://example.com/tesseract/")
        self.assertEqual(
            url,
            "https://example.com/tesseract/tesseract-ocr-w64-setup-5.5.0.exe",
        )

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
            "VR Mary Studio",
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

    def test_chat_header_is_responsive_and_settings_effort_is_localized(self):
        from PySide6.QtWidgets import QApplication, QComboBox

        initialize_workspace(self.settings)
        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            self.settings,
            smoke_test=True,
            auto_close_smoke=False,
        )
        try:
            window.resize(1120, 700)
            window.show()
            window._navigate(window.pages["Chat Mary"])
            application.processEvents()

            self.assertLess(
                window.chat_title.geometry().right(),
                window.clone_button.geometry().left(),
            )
            self.assertLess(
                window.provider_combo.geometry().right(),
                window.model_combo.geometry().left(),
            )
            self.assertLess(
                window.model_combo.geometry().right(),
                window.effort_combo.geometry().left(),
            )
            self.assertLess(
                window.effort_combo.geometry().bottom(),
                window.message_scroll.geometry().top(),
            )
            self.assertTrue(window.chat_empty_state.isVisible())
            self.assertEqual(
                window.effort_combo.accessibleName(),
                "Nível de esforço",
            )

            effort_field = window.settings_fields["MARY_DEFAULT_EFFORT"]
            self.assertIsInstance(effort_field, QComboBox)
            self.assertEqual(effort_field.currentText(), "Médio")
            self.assertEqual(effort_field.currentData(), "medium")
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
            self.assertEqual(window.review_table.rowCount(), 0)
            window.review_source.setCurrentIndex(
                window.review_source.findData("kb")
            )
            application.processEvents()
            self.assertEqual(window.review_table.rowCount(), 2)
        finally:
            window.close()

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

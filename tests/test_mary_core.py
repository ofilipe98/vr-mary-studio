import json
import sqlite3
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from vrsoft_extractor.mary.classifier import classify
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.content import canonical_markdown, html_to_markdown, sha256_text
from vrsoft_extractor.mary.db import MaryDatabase, _fts_query
from vrsoft_extractor.mary.migration import build_manifest, migrate
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.mary.movidesk import MovideskSync
from vrsoft_extractor.mary.providers import CodexProvider, _resolve_codex_command
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.ocr import latest_windows_installer_url
from vrsoft_extractor.mary.workspace import initialize_workspace


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
        self.assertEqual(
            sync._normalized_host(
                "http://vrsoftware.movidesk.com:80/kb/pt-br/category/pdv"
            ),
            "vrsoftware.movidesk.com",
        )

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

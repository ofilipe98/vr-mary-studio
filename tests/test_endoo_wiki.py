from __future__ import annotations

from pathlib import Path
from typing import Any

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.endoo_wiki import EndooWikiSync
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.endoo_client import (
    EndooAssetUnavailable,
    EndooFeatureUnavailable,
)


class FakeEndooClient:
    def __init__(self, *, fail_detail: bool = False) -> None:
        self.fail_detail = fail_detail

    def __enter__(self) -> "FakeEndooClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def get_json(self, path: str, *, params=None, attempts: int = 3):
        if path == "/wiki/articles":
            return {
                "data": [
                    {
                        "id": 42,
                        "slug": "funcao-102",
                        "title": "Função 102",
                        "updated_at": "2026-08-20T10:00:00Z",
                        "category": {"full_path": "PDV / Funções"},
                    }
                ],
                "current_page": 1,
                "last_page": 1,
            }
        if self.fail_detail:
            raise RuntimeError("falha transitória no detalhe")
        assert path == "/wiki/articles/funcao-102/read"
        return {
            "article": {
                "id": 42,
                "slug": "funcao-102",
                "title": "Função 102",
                "content": "<h1>Entrada</h1><p>Permite a entrada do operador.</p>",
                "updated_at": "2026-08-20T10:00:00Z",
                "category": {"full_path": "PDV / Funções"},
                "product": "VRCaixa",
            }
        }

    def get_bytes(self, _url: str) -> bytes:
        return b""


class UnavailableAssetClient(FakeEndooClient):
    def __init__(self) -> None:
        super().__init__()
        self.asset_requests = 0

    def get_json(self, path: str, *, params=None, attempts: int = 3):
        payload = super().get_json(path, params=params, attempts=attempts)
        if path.endswith("/read"):
            payload["article"]["content"] = (
                '<p>Conteúdo preservado.</p>'
                '<img src="https://iendo.b-cdn.net/one.png">'
                '<img src="https://iendo.b-cdn.net/two.png">'
            )
        return payload

    def get_bytes(self, _url: str) -> bytes:
        self.asset_requests += 1
        raise EndooAssetUnavailable("iendo.b-cdn.net")


class SummaryContentClient(FakeEndooClient):
    def get_json(self, path: str, *, params=None, attempts: int = 3):
        if path == "/wiki/articles":
            return {
                "data": [
                    {
                        "id": 86,
                        "slug": "Manual/Analise Perda/Quebra/Troca",
                        "title": "Análise Perda/Quebra/Troca",
                        "content": "<p>Conteúdo disponível na listagem.</p>",
                        "updated_at": "2026-09-06T10:00:00Z",
                    }
                ],
                "current_page": 1,
                "last_page": 1,
            }
        raise EndooFeatureUnavailable("detalhe indisponível")


def _settings(tmp_path: Path) -> MarySettings:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "vr").resolve(),
        old_root=(tmp_path / "old").resolve(),
        endoo_wiki_enabled=True,
    )
    settings.app_dir.mkdir(parents=True)
    settings.old_root.mkdir(parents=True)
    settings.ensure_dirs()
    return settings


def _document(origin: str, source_id: str, status: str = "active") -> KnowledgeDocument:
    return KnowledgeDocument(
        source="wiki",
        source_origin=origin,
        source_id=source_id,
        title=source_id,
        url=f"https://example.test/{source_id}",
        markdown="conteúdo antigo",
        module="PDV",
        review_status="approved",
        status=status,
        content_hash=source_id,
        local_path=f"conhecimento/PDV/Wiki/{source_id}.md",
    )


def test_endoo_sync_persists_origin_and_only_inactivates_endoo_scope(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(_document("vrwiki", "publico"))
    database.upsert_document(_document("endoo", "endoo-antigo"))
    sync = EndooWikiSync(settings, database)
    sync._client = lambda **_kwargs: FakeEndooClient()  # type: ignore[method-assign]

    stats = sync.sync()

    created = database.get_document("wiki", "endoo-42")
    public = database.get_document("wiki", "publico")
    stale = database.get_document("wiki", "endoo-antigo")
    assert stats.source_origin == "endoo"
    assert stats.created == 1
    assert stats.inactive == 1
    assert created is not None and created["source_origin"] == "endoo"
    assert "entrada do operador" in created["markdown"].casefold()
    assert public is not None and public["status"] == "active"
    assert stale is not None and stale["status"] == "inactive"


def test_partial_endoo_sync_never_inactivates_missing_documents(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(_document("endoo", "endoo-antigo"))
    sync = EndooWikiSync(settings, database)
    sync._client = lambda **_kwargs: FakeEndooClient(  # type: ignore[method-assign]
        fail_detail=True
    )

    stats = sync.sync()

    stale = database.get_document("wiki", "endoo-antigo")
    assert stats.errors == 1
    assert stats.inactive == 0
    assert stale is not None and stale["status"] == "active"


def test_endoo_sync_skips_timed_out_asset_host_after_first_failure(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    client = UnavailableAssetClient()
    sync = EndooWikiSync(settings, database)
    sync._client = lambda **_kwargs: client  # type: ignore[method-assign]

    stats = sync.sync()

    assert stats.created == 1
    assert stats.errors == 0
    assert client.asset_requests == 1
    document = database.get_document("wiki", "endoo-42")
    assert document is not None
    assert "Conteúdo preservado" in document["markdown"]


def test_endoo_sync_uses_summary_content_when_detail_endpoint_is_missing(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    sync = EndooWikiSync(settings, database)
    sync._client = lambda **_kwargs: SummaryContentClient()  # type: ignore[method-assign]

    stats = sync.sync()

    assert stats.created == 1
    assert stats.errors == 0
    document = database.get_document("wiki", "endoo-86")
    assert document is not None
    assert "Conteúdo disponível na listagem" in document["markdown"]


def test_existing_database_migrates_source_origins_with_backup(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(_document("vrwiki", "legado"))
    with database.connect() as connection:
        connection.execute("DROP INDEX idx_documents_source_origin")
        connection.execute("DROP INDEX idx_sync_runs_source_origin")
        connection.execute("ALTER TABLE documents DROP COLUMN source_origin")
        connection.execute("ALTER TABLE sync_runs DROP COLUMN source_origin")

    migrated = MaryDatabase(settings.database_path, root=settings.root)

    row = migrated.get_document("wiki", "legado")
    assert row is not None and row["source_origin"] == "vrwiki"
    assert (
        settings.root
        / ".state"
        / "backups"
        / "conhecimento-pre-endoo-wiki.sqlite"
    ).is_file()

from __future__ import annotations

import logging
import os
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterator

from ..endoo_client import EndooInvalidResponse, EndooReadClient
from .classifier import classify
from .config import MarySettings
from .content import (
    download_asset,
    html_to_markdown,
    preserve_validated_classification,
    replace_asset_urls,
    sha256_text,
    target_path,
    write_and_persist_document,
)
from .db import MaryDatabase
from .indexer import export_catalog
from .models import KnowledgeDocument, SyncStats, utc_now
from .ocr import OcrManager


LOGGER = logging.getLogger(__name__)


class EndooWikiSync:
    def __init__(
        self,
        settings: MarySettings,
        database: MaryDatabase,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.progress = progress or (lambda _message: None)
        self.ocr = OcrManager(settings.tesseract_dir)

    def login(self) -> Path:
        client = self._client(headless=False)
        return client.login()

    def sync(
        self,
        limit: int | None = None,
        *,
        headless: bool = True,
    ) -> SyncStats:
        if not self.settings.endoo_wiki_enabled:
            raise RuntimeError(
                "A Wiki Endoo esta desativada por VR_ENDOO_WIKI_ENABLED."
            )
        run_id = self.database.start_sync("wiki", "endoo")
        stats = SyncStats("wiki", source_origin="endoo")
        active_ids: set[str] = set()
        try:
            with self._client(headless=headless) as client:
                for index, summary in enumerate(
                    self.iter_article_summaries(client), start=1
                ):
                    if limit and index > limit:
                        break
                    stats.discovered += 1
                    source_id = self._source_id(summary)
                    active_ids.add(source_id)
                    title = str(summary.get("title") or source_id).strip()
                    revision = self._revision(summary)
                    current = self.database.get_document("wiki", source_id)
                    if (
                        current
                        and revision
                        and str(current["revision"] or "") == revision
                        and str(current["status"] or "") == "active"
                    ):
                        if current["review_status"] not in {"approved", "kept"}:
                            result = classify(
                                current["title"],
                                current["markdown"],
                                current["category"],
                                current["product"],
                            )
                            stats.review += int(
                                self.database.queue_review(
                                    int(current["id"]),
                                    result.module,
                                    result.confidence,
                                    result.reasons,
                                    str(current["module"]),
                                )
                            )
                        stats.unchanged += 1
                        self.progress(
                            f"Wiki Endoo {index}: inalterada — {title}"
                        )
                        continue
                    try:
                        document = self.fetch_document(client, summary)
                        validated_module_changed = preserve_validated_classification(
                            current, document
                        )
                        document_id, action = write_and_persist_document(
                            self.settings.root,
                            document,
                            lambda: self.database.upsert_document(document),
                            previous_path=current["local_path"] if current else None,
                        )
                        if document.review_status != "approved" or validated_module_changed:
                            result = classify(
                                document.title,
                                document.markdown,
                                document.category,
                                document.product,
                            )
                            stats.review += int(
                                self.database.queue_review(
                                    document_id,
                                    result.module,
                                    result.confidence,
                                    result.reasons,
                                    current["module"] if current else "",
                                    validated_module_changed,
                                )
                            )
                        setattr(stats, action, getattr(stats, action) + 1)
                        self.progress(
                            f"Wiki Endoo {index}: {action} — {document.title}"
                        )
                    except Exception as exc:
                        LOGGER.exception(
                            "Falha no artigo da Wiki Endoo %s", summary.get("slug")
                        )
                        stats.errors += 1
                        self.progress(
                            f"Wiki Endoo {index}: erro — {title}: {exc}"
                        )
            if not limit and stats.errors == 0:
                stats.inactive = self.database.mark_missing_inactive(
                    "wiki", active_ids, "endoo"
                )
            elif not limit and stats.errors:
                LOGGER.warning(
                    "Wiki Endoo incompleta: documentos ausentes nao serao inativados."
                )
            export_catalog(self.database, self.settings.index_dir)
            self.database.finish_sync(run_id, stats)
            return stats
        except Exception as exc:
            self.database.finish_sync(run_id, stats, str(exc))
            raise

    def iter_article_summaries(
        self, client: EndooReadClient
    ) -> Iterator[dict[str, Any]]:
        page = 1
        seen: set[str] = set()
        while page <= 10_000:
            payload = client.get_json(
                "/wiki/articles", params={"page": page, "per_page": 100}
            )
            if isinstance(payload, list):
                rows = payload
                current_page = page
                last_page = page
            elif isinstance(payload, dict):
                container = payload
                if isinstance(payload.get("data"), dict):
                    container = payload["data"]
                rows = next(
                    (
                        container.get(key)
                        for key in ("data", "articles", "items", "results")
                        if isinstance(container.get(key), list)
                    ),
                    [],
                )
                meta = container.get("meta")
                if not isinstance(meta, dict):
                    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                current_page = self._positive_int(
                    container.get("current_page") or meta.get("current_page"), page
                )
                last_page = self._positive_int(
                    container.get("last_page") or meta.get("last_page"), current_page
                )
            else:
                raise EndooInvalidResponse(
                    "A listagem da Wiki Endoo possui formato invalido."
                )
            if not isinstance(rows, list):
                raise EndooInvalidResponse(
                    "A lista de artigos da Wiki Endoo nao e uma lista."
                )
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = self._source_id(row)
                if key in seen:
                    continue
                seen.add(key)
                yield row
            if not rows or current_page >= last_page:
                break
            page = current_page + 1

    def fetch_document(
        self, client: EndooReadClient, summary: dict[str, Any]
    ) -> KnowledgeDocument:
        slug = str(summary.get("slug") or "").strip()
        if not slug:
            raise EndooInvalidResponse("Artigo da Wiki Endoo sem slug.")
        payload = client.get_json(
            "/wiki/articles/"
            + urllib.parse.quote(slug, safe="")
            + "/read"
        )
        root = payload
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            root = payload["data"]
        article = root.get("article") if isinstance(root, dict) else None
        if not isinstance(article, dict):
            article = root if isinstance(root, dict) else None
        if not isinstance(article, dict):
            raise EndooInvalidResponse(
                f"Detalhe invalido para o artigo Wiki Endoo {slug}."
            )
        title = str(article.get("title") or summary.get("title") or slug).strip()
        html = str(article.get("content") or "").strip()
        if not html:
            raise EndooInvalidResponse(f"Artigo Wiki Endoo vazio: {title}")
        url = urllib.parse.urljoin(
            self.settings.endoo_base_url + "/",
            "wiki/artigo/" + urllib.parse.quote(slug, safe=""),
        )
        markdown, image_urls = html_to_markdown(html, url)
        category = self._category(article.get("category") or summary.get("category"))
        product = str(article.get("product") or summary.get("product") or "").strip()
        classification = classify(title, markdown, category, product)
        document = KnowledgeDocument(
            source="wiki",
            source_origin="endoo",
            source_id=self._source_id({**summary, **article}),
            title=title,
            url=url,
            html=html,
            markdown=markdown,
            module=classification.module,
            classification_confidence=classification.confidence,
            review_status=classification.status,
            created_at=str(
                article.get("created_at")
                or article.get("published_at")
                or summary.get("created_at")
                or summary.get("published_at")
                or ""
            ),
            updated_at=str(
                article.get("updated_at") or summary.get("updated_at") or ""
            ),
            synced_at=utc_now(),
            revision=self._revision(article) or self._revision(summary),
            category=category,
            product=product,
        )
        destination_dir = self.settings.assets_dir / "wiki" / "endoo"
        document_dir = target_path(self.settings.root, document).parent
        assets: list[Path] = []
        replacements: dict[str, str] = {}
        ocr_parts: list[str] = []
        for image_url in image_urls:
            try:
                local = download_asset(
                    image_url,
                    destination_dir,
                    opener=client.get_bytes,
                )
                assets.append(local)
                replacements[image_url] = Path(
                    os.path.relpath(local, document_dir)
                ).as_posix()
                ocr = self.ocr.extract(local)
                if ocr.text:
                    ocr_parts.append(f"### {local.name}\n\n{ocr.text}")
            except Exception:
                LOGGER.warning(
                    "Nao foi possivel baixar imagem da Wiki Endoo: %s", image_url
                )
        document.markdown = replace_asset_urls(markdown, replacements)
        document.assets = [str(path) for path in assets]
        document.ocr_text = "\n\n".join(ocr_parts)
        document.content_hash = sha256_text(
            "\n".join([document.title, document.markdown, document.ocr_text])
        )
        if not document.revision:
            document.revision = document.content_hash[:16]
        return document

    def _client(self, *, headless: bool) -> EndooReadClient:
        return EndooReadClient(
            self.settings.root,
            base_url=self.settings.endoo_base_url,
            api_url=self.settings.endoo_api_url,
            headless=headless,
            entry_path="/wiki",
        )

    @staticmethod
    def _source_id(article: dict[str, Any]) -> str:
        article_id = str(article.get("id") or "").strip()
        if article_id:
            return "endoo-" + article_id
        slug = str(article.get("slug") or "").strip().casefold()
        if not slug:
            raise EndooInvalidResponse("Artigo da Wiki Endoo sem ID e sem slug.")
        normalized = "-".join(part for part in slug.replace("_", "-").split("-") if part)
        return "endoo-slug-" + normalized[:180]

    @staticmethod
    def _revision(article: dict[str, Any]) -> str:
        return str(
            article.get("updated_at")
            or article.get("published_at")
            or article.get("revision")
            or ""
        ).strip()

    @staticmethod
    def _category(value: Any) -> str:
        if isinstance(value, dict):
            return str(
                value.get("full_path") or value.get("name") or value.get("title") or ""
            ).strip()
        return str(value or "").strip()

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return max(1, int(default))

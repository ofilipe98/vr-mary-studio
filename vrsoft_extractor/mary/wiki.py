from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

from .classifier import classify
from .config import MarySettings
from .content import (
    download_asset,
    html_to_markdown,
    replace_asset_urls,
    sha256_text,
    write_document,
)
from .db import MaryDatabase
from .indexer import export_catalog
from .models import KnowledgeDocument, SyncStats, utc_now
from .ocr import OcrManager


LOGGER = logging.getLogger(__name__)


class WikiSync:
    def __init__(
        self,
        settings: MarySettings,
        database: MaryDatabase,
        progress: Callable[[str], None] | None = None,
    ):
        self.settings = settings
        self.database = database
        self.progress = progress or (lambda _message: None)
        self.ocr = OcrManager(settings.tesseract_dir)

    def sync(self, limit: int | None = None) -> SyncStats:
        run_id = self.database.start_sync("wiki")
        stats = SyncStats("wiki")
        active_ids: set[str] = set()
        try:
            for index, page in enumerate(self.iter_pages(), start=1):
                if limit and index > limit:
                    break
                source_id = str(page["pageid"])
                active_ids.add(source_id)
                stats.discovered += 1
                revision = str(
                    ((page.get("revisions") or [{}])[0]).get("revid", "")
                )
                current = self.database.get_document("wiki", source_id)
                if current and current["revision"] == revision and current["status"] == "active":
                    stats.unchanged += 1
                    self.progress(f"Wiki {index}: inalterada — {page['title']}")
                    continue
                try:
                    document = self.fetch_document(page, revision)
                    document_id, action = self.database.upsert_document(document)
                    if document.review_status != "approved":
                        result = classify(
                            document.title,
                            document.markdown,
                            document.category,
                            document.product,
                        )
                        self.database.queue_review(
                            document_id,
                            result.module,
                            result.confidence,
                            result.reasons,
                            current["module"] if current else "",
                        )
                        stats.review += 1
                    setattr(stats, action, getattr(stats, action) + 1)
                    self.progress(f"Wiki {index}: {action} — {page['title']}")
                except Exception as exc:  # keep batch running
                    LOGGER.exception("Falha na página Wiki %s", page.get("title"))
                    stats.errors += 1
                    self.progress(f"Wiki {index}: erro — {page['title']}: {exc}")
            if not limit:
                stats.inactive = self.database.mark_missing_inactive("wiki", active_ids)
            export_catalog(self.database, self.settings.index_dir)
            self.database.finish_sync(run_id, stats)
            return stats
        except Exception as exc:
            self.database.finish_sync(run_id, stats, str(exc))
            raise

    def iter_pages(self) -> Iterator[dict[str, Any]]:
        continuation: dict[str, str] = {}
        while True:
            params = {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "generator": "allpages",
                "gapnamespace": "0",
                "gaplimit": "max",
                "prop": "info|revisions",
                "inprop": "url",
                "rvprop": "ids|timestamp",
                **continuation,
            }
            data = self._api(params)
            for page in data.get("query", {}).get("pages", []):
                if not page.get("missing"):
                    yield page
            next_data = data.get("continue")
            if not next_data:
                break
            continuation = {
                key: str(value) for key, value in next_data.items() if key != "continue"
            }

    def fetch_document(self, page: dict[str, Any], revision: str) -> KnowledgeDocument:
        parsed = self._api(
            {
                "action": "parse",
                "format": "json",
                "formatversion": "2",
                "pageid": str(page["pageid"]),
                "prop": "text|displaytitle|categories",
                "disableeditsection": "1",
            }
        )["parse"]
        url = page.get("fullurl") or (
            self.settings.wiki_base
            + "index.php?"
            + urllib.parse.urlencode({"title": page["title"]})
        )
        markdown, image_urls = html_to_markdown(parsed.get("text", ""), url)
        asset_paths: list[Path] = []
        replacements: dict[str, str] = {}
        ocr_parts: list[str] = []
        for image_url in image_urls:
            try:
                local = download_asset(image_url, self.settings.assets_dir / "wiki")
                asset_paths.append(local)
                relative = Path("..") / ".." / ".." / ".." / "assets" / "wiki" / local.name
                replacements[image_url] = str(relative)
                result = self.ocr.extract(local)
                if result.text:
                    ocr_parts.append(f"### {local.name}\n\n{result.text}")
            except Exception:
                LOGGER.warning("Não foi possível baixar imagem Wiki: %s", image_url)
        markdown = replace_asset_urls(markdown, replacements)
        categories = [
            str(item.get("category") or item.get("*") or "").replace("Categoria:", "")
            for item in parsed.get("categories", [])
        ]
        classification = classify(page["title"], markdown, " / ".join(categories))
        document = KnowledgeDocument(
            source="wiki",
            source_id=str(page["pageid"]),
            title=page["title"],
            url=url,
            html=parsed.get("text", ""),
            markdown=markdown,
            module=classification.module,
            classification_confidence=classification.confidence,
            review_status=classification.status,
            updated_at=str(
                ((page.get("revisions") or [{}])[0]).get("timestamp", "")
            ),
            synced_at=utc_now(),
            revision=revision,
            category=" / ".join(categories),
            assets=[str(path) for path in asset_paths],
            ocr_text="\n\n".join(ocr_parts),
        )
        document.content_hash = sha256_text(
            "\n".join([document.title, markdown, document.ocr_text])
        )
        write_document(self.settings.root, document)
        return document

    def _api(self, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{self.settings.wiki_api}?{query}",
            headers={"User-Agent": "VR-Mary-Studio/0.2 (+knowledge-sync)"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))

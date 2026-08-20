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
    preserve_validated_classification,
    replace_asset_urls,
    sha256_text,
    write_and_persist_document,
)
from .db import MaryDatabase
from .indexer import export_catalog
from .models import KnowledgeDocument, SyncStats, utc_now
from .ocr import OcrManager


LOGGER = logging.getLogger(__name__)
IGNORED_PAGE_IDS = {"2030"}


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
        run_id = self.database.start_sync("wiki", "vrwiki")
        stats = SyncStats("wiki", source_origin="vrwiki")
        active_ids: set[str] = set()
        try:
            for index, page in enumerate(self.iter_pages(), start=1):
                if limit and index > limit:
                    break
                if str(page.get("pageid") or "") in IGNORED_PAGE_IDS:
                    stats.discovered += 1
                    stats.skipped += 1
                    self.progress(f"Wiki {index}: ignorada — {page['title']} (página de teste)")
                    continue
                source_id = str(page["pageid"])
                active_ids.add(source_id)
                stats.discovered += 1
                revision = str(
                    ((page.get("revisions") or [{}])[0]).get("revid", "")
                )
                current = self.database.get_document("wiki", source_id)
                if current and current["revision"] == revision and current["status"] == "active":
                    if current["review_status"] not in {"approved", "kept"}:
                        result = classify(
                            current["title"],
                            current["markdown"],
                            current["category"],
                            current["product"],
                        )
                        queued = self.database.queue_review(
                            int(current["id"]),
                            result.module,
                            result.confidence,
                            result.reasons,
                            str(current["module"]),
                        )
                        stats.review += int(queued)
                    stats.unchanged += 1
                    self.progress(f"Wiki {index}: inalterada — {page['title']}")
                    continue
                try:
                    document = self.fetch_document(page, revision)
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
                        queued = self.database.queue_review(
                            document_id,
                            result.module,
                            result.confidence,
                            result.reasons,
                            current["module"] if current else "",
                            validated_module_changed,
                        )
                        stats.review += int(queued)
                    setattr(stats, action, getattr(stats, action) + 1)
                    self.progress(f"Wiki {index}: {action} — {page['title']}")
                except Exception as exc:  # keep batch running
                    LOGGER.exception("Falha na página Wiki %s", page.get("title"))
                    stats.errors += 1
                    self.progress(f"Wiki {index}: erro — {page['title']}: {exc}")
            if not limit and stats.errors == 0:
                stats.inactive = self.database.mark_missing_inactive("wiki", active_ids)
            elif not limit and stats.errors:
                LOGGER.warning(
                    "Wiki incompleta: documentos ausentes não serão inativados nesta execução."
                )
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
            source_origin="vrwiki",
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
        return document

    def _api(self, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{self.settings.wiki_api}?{query}",
            headers={"User-Agent": "VR-Norte-Studio/0.2 (+knowledge-sync)"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        error = data.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "erro_desconhecido")
            info = str(error.get("info") or "A Wiki não informou detalhes.")
            raise RuntimeError(f"API da Wiki retornou {code}: {info}")
        return data

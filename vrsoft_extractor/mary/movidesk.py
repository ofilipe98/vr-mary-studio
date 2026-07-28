from __future__ import annotations

import logging
import json
import os
import re
import shutil
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup

from ..runtime import configure_playwright_runtime
from .classifier import classify
from .config import MarySettings
from .content import (
    download_asset,
    html_to_markdown,
    replace_asset_urls,
    safe_slug,
    sha256_text,
    write_document,
)
from .db import MaryDatabase
from .indexer import export_catalog
from .models import KnowledgeDocument, SyncStats, utc_now
from .ocr import OcrManager


LOGGER = logging.getLogger(__name__)


class MovideskSync:
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

    def sync(self, headed: bool = False, limit: int | None = None) -> SyncStats:
        configure_playwright_runtime()
        from playwright.sync_api import sync_playwright

        run_id = self.database.start_sync("kb")
        stats = SyncStats("kb")
        active_ids: set[str] = set()
        try:
            with sync_playwright() as playwright:
                launch_options: dict[str, object] = {
                    "headless": not headed,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if self._chrome_installed():
                    launch_options["channel"] = "chrome"
                try:
                    browser = playwright.chromium.launch(**launch_options)
                except Exception:
                    launch_options.pop("channel", None)
                    browser = playwright.chromium.launch(**launch_options)
                context_options = {}
                if self.settings.movidesk_state_path.exists():
                    context_options["storage_state"] = str(
                        self.settings.movidesk_state_path
                    )
                context_options["user_agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36"
                )
                context = browser.new_context(**context_options)
                page = context.new_page()
                response = page.goto(
                    self.settings.kb_url,
                    wait_until="domcontentloaded",
                    timeout=90_000,
                )
                self._raise_for_blocked_page(page, response)
                self._wait_for_dynamic_content(page)
                self._ensure_login(page, interactive=headed)
                context.storage_state(path=str(self.settings.movidesk_state_path))
                article_urls = self._discover_articles(page, limit)
                if not article_urls:
                    diagnostic = self._write_discovery_diagnostic(page)
                    raise RuntimeError(
                        "O Movidesk foi aberto, mas nenhum artigo do KB foi descoberto. "
                        f"Diagnóstico salvo em {diagnostic}. "
                        "Use 'Login/KB visível' se a sessão exigir MFA ou CAPTCHA."
                    )
                for index, url in enumerate(article_urls, start=1):
                    try:
                        response = page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=90_000,
                        )
                        self._raise_for_blocked_page(page, response)
                        self._wait_for_dynamic_content(page)
                        self._ensure_login(page, interactive=headed)
                        document = self._extract_article(page, context)
                        active_ids.add(document.source_id)
                        stats.discovered += 1
                        current = self.database.get_document("kb", document.source_id)
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
                        self.progress(f"KB {index}/{len(article_urls)}: {action} — {document.title}")
                    except Exception as exc:
                        stats.errors += 1
                        LOGGER.exception("Falha no artigo Movidesk %s", url)
                        self.progress(f"KB {index}: erro — {url}: {exc}")
                if not limit:
                    stats.inactive = self.database.mark_missing_inactive("kb", active_ids)
                context.storage_state(path=str(self.settings.movidesk_state_path))
                browser.close()
            export_catalog(self.database, self.settings.index_dir)
            self.database.finish_sync(run_id, stats)
            return stats
        except Exception as exc:
            self.database.finish_sync(run_id, stats, str(exc))
            raise

    @staticmethod
    def _wait_for_dynamic_content(page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        try:
            page.wait_for_selector(
                "a[href*='/kb/'], input[type=password], article, main",
                timeout=15_000,
            )
        except Exception:
            pass

    @staticmethod
    def _chrome_installed() -> bool:
        candidates = [
            shutil.which("chrome.exe"),
            os.path.join(
                os.environ.get("PROGRAMFILES", ""),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            ),
            os.path.join(
                os.environ.get("PROGRAMFILES(X86)", ""),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            ),
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            ),
        ]
        return any(candidate and Path(candidate).exists() for candidate in candidates)

    @staticmethod
    def _raise_for_blocked_page(page, response=None) -> None:
        status = getattr(response, "status", 0) if response else 0
        title = page.title().strip().lower()
        if status in {401, 403} or title in {"401 unauthorized", "403 forbidden"}:
            raise RuntimeError(
                "O Movidesk bloqueou o navegador automatizado "
                f"(HTTP {status or title}). Use 'Login/KB visível' para renovar a sessão."
            )

    def _ensure_login(self, page, interactive: bool = False) -> None:
        password = page.locator("input[type=password]")
        if password.count() == 0:
            return
        email = os.environ.get("MOVIDESK_EMAIL", "")
        secret = os.environ.get("MOVIDESK_PASSWORD", "")
        if not email or not secret:
            raise RuntimeError(
                "Sessão do Movidesk expirada e MOVIDESK_EMAIL/MOVIDESK_PASSWORD ausentes no .env."
            )
        user_field = page.locator(
            "input[type=email], input[name*=email i], input[name*=user i]"
        ).first
        if user_field.count():
            user_field.fill(email)
        password.first.fill(secret)
        submit = page.locator(
            "button[type=submit], input[type=submit], button:has-text('Entrar')"
        ).first
        if submit.count():
            submit.click()
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        if interactive and page.locator("input[type=password]").count():
            self.progress(
                "KB: conclua o login, MFA ou CAPTCHA na janela aberta (até 3 minutos)."
            )
            try:
                page.wait_for_selector("input[type=password]", state="detached", timeout=180_000)
            except Exception:
                pass
        if page.locator("input[type=password]").count():
            raise RuntimeError(
                "Login Movidesk requer interação (MFA/CAPTCHA). Execute sincronização com navegador visível."
            )

    def _discover_articles(self, page, limit: int | None) -> list[str]:
        origin = self._normalized_host(self.settings.kb_url)
        queue = deque([self.settings.kb_url])
        visited: set[str] = set()
        articles: list[str] = []
        while queue:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            self._raise_for_blocked_page(page, response)
            self._wait_for_dynamic_content(page)
            self._ensure_login(page)
            links = page.locator("a[href], [data-href], [data-url]").evaluate_all(
                """(els) => els.map(e =>
                    e.href || e.getAttribute('data-href') || e.getAttribute('data-url')
                ).filter(Boolean)"""
            )
            for link in links:
                absolute = urllib.parse.urljoin(page.url, link)
                parsed = urllib.parse.urlsplit(absolute)
                if (
                    self._normalized_host(absolute) != origin
                    or "/kb" not in parsed.path.lower()
                ):
                    continue
                clean = self._canonical_kb_url(absolute)
                if self._is_article_url(clean):
                    if clean not in articles:
                        articles.append(clean)
                        if limit and len(articles) >= limit:
                            return articles
                elif clean not in visited and len(visited) < 5_000:
                    queue.append(clean)
        return articles

    @staticmethod
    def _normalized_host(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
        if port and port not in {80, 443}:
            return f"{host}:{port}"
        return host

    def _canonical_kb_url(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self.settings.kb_url)
        scheme = base.scheme or "https"
        netloc = base.netloc
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = urllib.parse.urlencode(sorted(query_pairs))
        return urllib.parse.urlunsplit(
            (scheme, netloc, parsed.path.rstrip("/") or "/kb", query, "")
        )

    @staticmethod
    def _is_article_url(url: str) -> bool:
        lowered = url.lower()
        return bool(
            re.search(r"/kb/(?:[a-z]{2}-[a-z]{2}/)?(article|artigo|a)/", lowered)
            or re.search(r"[?&](id|articleid|article)=\d+", lowered)
            or re.search(r"/kb/\d+/", lowered)
        )

    def _write_discovery_diagnostic(self, page) -> Path:
        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().replace(":", "-")
        target = self.settings.logs_dir / f"kb-discovery-{timestamp}.json"
        raw_links = page.locator("a[href]").evaluate_all(
            "(els) => els.slice(0, 100).map(e => e.href).filter(Boolean)"
        )
        links = []
        for link in raw_links:
            parsed = urllib.parse.urlsplit(str(link))
            links.append(
                urllib.parse.urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, "", "")
                )
            )
        payload = {
            "url": page.url,
            "title": page.title(),
            "link_count": page.locator("a[href]").count(),
            "sample_links": links,
            "password_field": bool(page.locator("input[type=password]").count()),
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            page.screenshot(path=str(target.with_suffix(".png")), full_page=True)
        except Exception:
            LOGGER.exception("Não foi possível salvar a captura de diagnóstico do KB.")
        return target

    def _extract_article(self, page, context) -> KnowledgeDocument:
        title = (
            page.locator("h1").first.inner_text().strip()
            if page.locator("h1").count()
            else page.title().strip()
        )
        content_locator = page.locator(
            "article, main, .article-content, .kb-article, [class*=article-content i]"
        ).first
        html = (
            content_locator.inner_html()
            if content_locator.count()
            else page.locator("body").inner_html()
        )
        breadcrumb = " / ".join(
            text.strip()
            for text in page.locator(
                "nav[aria-label*=breadcrumb i] a, .breadcrumb a"
            ).all_inner_texts()
            if text.strip()
        )
        markdown, image_urls = html_to_markdown(html, page.url)
        replacements: dict[str, str] = {}
        assets: list[Path] = []
        ocr_parts: list[str] = []

        def browser_fetch(url: str) -> bytes:
            response = context.request.get(url, timeout=60_000)
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status}")
            return response.body()

        for image_url in image_urls:
            try:
                local = download_asset(
                    image_url,
                    self.settings.assets_dir / "kb",
                    opener=browser_fetch,
                )
                assets.append(local)
                relative = Path("..") / ".." / ".." / ".." / "assets" / "kb" / local.name
                replacements[image_url] = str(relative)
                result = self.ocr.extract(local)
                if result.text:
                    ocr_parts.append(f"### {local.name}\n\n{result.text}")
            except Exception:
                LOGGER.warning("Não foi possível baixar imagem KB: %s", image_url)
        markdown = replace_asset_urls(markdown, replacements)
        source_id = self._source_id(page.url, title)
        created_at, updated_at = self._find_dates(page.locator("body").inner_text())
        classification = classify(title, markdown, breadcrumb)
        document = KnowledgeDocument(
            source="kb",
            source_id=source_id,
            title=title,
            url=page.url,
            html=html,
            markdown=markdown,
            module=classification.module,
            classification_confidence=classification.confidence,
            review_status=classification.status,
            created_at=created_at,
            updated_at=updated_at,
            synced_at=utc_now(),
            revision=updated_at,
            category=breadcrumb,
            assets=[str(path) for path in assets],
            ocr_text="\n\n".join(ocr_parts),
        )
        document.content_hash = sha256_text(
            "\n".join([document.title, markdown, document.ocr_text])
        )
        write_document(self.settings.root, document)
        return document

    @staticmethod
    def _source_id(url: str, title: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        for key in ("id", "articleId", "article", "kbId"):
            if query.get(key):
                return query[key]
        match = re.search(r"/(\d+)(?:/|$)", parsed.path)
        return match.group(1) if match else safe_slug(title)

    @staticmethod
    def _find_dates(text: str) -> tuple[str, str]:
        dates = re.findall(r"\b\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2})?\b", text)
        if not dates:
            return "", ""
        return dates[0], dates[-1]

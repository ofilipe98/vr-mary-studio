from __future__ import annotations

import logging
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
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


class MovideskInteractiveLoginRequired(RuntimeError):
    """Raised when the KB sync must continue in a visible browser."""


class MovideskSync:
    LOGIN_PATH = "/Account/Login"
    ARTICLE_LINK_SELECTOR = "a[href], [data-href], [data-url]"
    RESULT_LINK_SELECTOR = (
        ".search-container-items a[href], "
        ".search-container a.kb-article-hyperlink[href]"
    )
    NEXT_PAGE_SELECTOR = (
        ".container-items-and-pagination .button-right-pagination"
    )

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
                browser = self._launch_browser(playwright, headed=headed)
                context = self._new_context(browser)
                page = context.new_page()
                self.progress("KB: validando a sessão salva.")
                response = page.goto(
                    self.settings.kb_url,
                    wait_until="domcontentloaded",
                    timeout=90_000,
                )
                self._raise_for_blocked_page(page, response)
                self._wait_for_dynamic_content(page)
                login_was_pending = self._login_pending(page)
                if login_was_pending:
                    self._ensure_login(page, interactive=headed)
                    response = page.goto(
                        self.settings.kb_url,
                        wait_until="domcontentloaded",
                        timeout=90_000,
                    )
                    self._raise_for_blocked_page(page, response)
                    self._wait_for_dynamic_content(page)
                    self._ensure_login(page, interactive=headed)
                context.storage_state(path=str(self.settings.movidesk_state_path))
                self.progress(
                    "KB: sessão autenticada; mapeando categorias e artigos."
                )
                article_urls = self._discover_articles(
                    page,
                    limit,
                    interactive=headed,
                )
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
                        validated_module_changed = bool(
                            current
                            and current["review_status"] == "approved"
                            and current["module"] != document.module
                        )
                        if document.review_status != "approved" or validated_module_changed:
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
                                validated_module_changed,
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

    def login(self) -> None:
        """Completes interactive authentication and persists it before syncing."""
        configure_playwright_runtime()
        from playwright.sync_api import sync_playwright

        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright, headed=True)
            try:
                context = self._new_context(browser)
                page = context.new_page()
                self.progress(
                    "KB: conclua o login na janela aberta. Ela será fechada "
                    "automaticamente quando a sessão estiver pronta."
                )
                self._authenticate(page, interactive=True)
                context.storage_state(path=str(self.settings.movidesk_state_path))
                response = page.goto(
                    self.settings.kb_url,
                    wait_until="domcontentloaded",
                    timeout=90_000,
                )
                self._raise_for_blocked_page(page, response)
                self._wait_for_dynamic_content(page)
                self._ensure_login(page, interactive=True)
                context.storage_state(path=str(self.settings.movidesk_state_path))
                self.progress(
                    "KB: autenticação concluída e sessão salva. "
                    "Iniciando a sincronização em segundo plano."
                )
            finally:
                browser.close()

    def _launch_browser(self, playwright, headed: bool):
        launch_options: dict[str, object] = {
            "headless": not headed,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self._chrome_installed():
            launch_options["channel"] = "chrome"
        try:
            return playwright.chromium.launch(**launch_options)
        except Exception:
            launch_options.pop("channel", None)
            return playwright.chromium.launch(**launch_options)

    def _new_context(self, browser):
        context_options: dict[str, object] = {}
        if self.settings.movidesk_state_path.exists():
            context_options["storage_state"] = str(
                self.settings.movidesk_state_path
            )
        context_options["user_agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        )
        return browser.new_context(**context_options)

    @staticmethod
    def _wait_for_dynamic_content(page) -> None:
        try:
            page.wait_for_selector(
                "a[href*='/kb/'], input[type=password], article, main, "
                ".article-content, .kb-article, [class*=article-content i]",
                timeout=15_000,
            )
        except Exception:
            pass
        try:
            page.wait_for_timeout(350)
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
            if not interactive:
                raise MovideskInteractiveLoginRequired(
                    "Sessão do Movidesk expirada e "
                    "as credenciais não permitiram login automático."
                )
            self.progress(
                "KB: entre no Movidesk na janela aberta e conclua MFA/CAPTCHA "
                "(até 3 minutos)."
            )
            self._wait_for_login_completion(page)
        else:
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
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            if interactive and self._login_pending(page):
                self.progress(
                    "KB: conclua o login, MFA ou CAPTCHA na janela aberta "
                    "(até 3 minutos)."
                )
                self._wait_for_login_completion(page)
        if self._login_pending(page):
            raise MovideskInteractiveLoginRequired(
                "Login Movidesk requer interação (MFA/CAPTCHA). Execute sincronização com navegador visível."
            )

    def _authenticate(self, page, interactive: bool) -> None:
        base = urllib.parse.urlsplit(self.settings.kb_url)
        login_url = urllib.parse.urlunsplit(
            (base.scheme or "https", base.netloc, self.LOGIN_PATH, "", "")
        )
        response = page.goto(
            login_url,
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        self._raise_for_blocked_page(page, response)
        self._wait_for_dynamic_content(page)
        if self._login_pending(page):
            self.progress("KB: autenticando no portal Movidesk.")
            self._ensure_login(page, interactive=interactive)
        if self._login_pending(page):
            raise MovideskInteractiveLoginRequired(
                "A autenticação do Movidesk não foi concluída. "
                "Use 'Login/KB visível' para entrar e concluir MFA/CAPTCHA."
            )

    @classmethod
    def _login_pending(cls, page) -> bool:
        if getattr(page, "is_closed", lambda: False)():
            raise MovideskInteractiveLoginRequired(
                "A janela de autenticação foi fechada antes da conclusão. "
                "Abra “Login/KB visível” e aguarde o fechamento automático."
            )
        path = urllib.parse.urlsplit(page.url).path.rstrip("/").lower()
        return (
            path == cls.LOGIN_PATH.lower()
            or bool(page.locator("input[type=password]").count())
        )

    @classmethod
    def _wait_for_login_completion(cls, page) -> None:
        try:
            page.wait_for_function(
                """(loginPath) => {
                    const path = window.location.pathname
                        .replace(/\\/$/, '')
                        .toLowerCase();
                    const hasPassword = Boolean(
                        document.querySelector('input[type=password]')
                    );
                    return path !== loginPath.toLowerCase() && !hasPassword;
                }""",
                arg=cls.LOGIN_PATH,
                timeout=180_000,
            )
        except Exception as exc:
            if getattr(page, "is_closed", lambda: False)():
                raise MovideskInteractiveLoginRequired(
                    "A janela de autenticação foi fechada antes da conclusão. "
                    "Aguarde o aplicativo fechá-la automaticamente."
                ) from exc
            raise MovideskInteractiveLoginRequired(
                "O login Movidesk não foi concluído em três minutos. "
                "Verifique MFA/CAPTCHA e tente novamente."
            ) from exc

    def _discover_articles(
        self,
        page,
        limit: int | None,
        interactive: bool = False,
    ) -> list[str]:
        origin = self._normalized_host(self.settings.kb_url)
        root_url = self._canonical_kb_url(self.settings.kb_url)
        queue: deque[str] = deque()
        scheduled: set[str] = {root_url}
        visited: set[str] = {root_url}
        articles: list[str] = []
        article_ids: set[str] = set()
        pagination_pages = 0
        page_errors = 0

        def collect_links(links: list[str], base_url: str) -> bool:
            for link in links:
                absolute = urllib.parse.urljoin(base_url, link)
                parsed = urllib.parse.urlsplit(absolute)
                if (
                    self._normalized_host(absolute) != origin
                    or "/kb" not in parsed.path.lower()
                ):
                    continue
                clean = self._canonical_kb_url(absolute)
                if self._is_article_url(clean):
                    source_id = self._source_id(clean, "")
                    if source_id not in article_ids:
                        article_ids.add(source_id)
                        articles.append(clean)
                        if limit and len(articles) >= limit:
                            return True
                elif (
                    self._is_category_url(clean)
                    and clean not in scheduled
                    and len(scheduled) < 5_000
                ):
                    scheduled.add(clean)
                    queue.append(clean)
            return False

        root_links = self._page_links(page)
        paginated_links, result_pages = self._paginated_result_links(page)
        root_links.extend(paginated_links)
        pagination_pages += max(0, result_pages - 1)
        if collect_links(root_links, page.url):
            self.progress(
                "KB: limite de descoberta atingido — "
                f"{len(articles)} artigos na página raiz."
            )
            return articles
        self.progress(
            "KB: página raiz analisada — "
            f"{len(articles)} artigos encontrados e "
            f"{len(queue)} categorias pendentes."
        )

        cookie_header = self._storage_cookie_header()
        while queue:
            batch: list[str] = []
            while queue and len(batch) < 8:
                category_url = queue.popleft()
                if category_url not in visited:
                    visited.add(category_url)
                    batch.append(category_url)
            if not batch:
                continue
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = {
                    executor.submit(
                        self._http_page_links,
                        category_url,
                        cookie_header,
                    ): category_url
                    for category_url in batch
                }
                for future in as_completed(futures):
                    category_url = futures[future]
                    try:
                        links = future.result()
                    except MovideskInteractiveLoginRequired:
                        raise
                    except Exception as exc:
                        page_errors += 1
                        LOGGER.warning(
                            "Falha ao mapear categoria KB %s: %s",
                            category_url,
                            exc,
                        )
                        self.progress(
                            f"KB: categoria ignorada após erro ({page_errors}) — "
                            f"{category_url}"
                        )
                        continue
                    if collect_links(links, category_url):
                        self.progress(
                            "KB: limite de descoberta atingido — "
                            f"{len(articles)} artigos em "
                            f"{len(visited) + pagination_pages} páginas."
                        )
                        return articles
            if (
                len(visited) == 1
                or len(visited) % 10 < len(batch)
                or not queue
            ):
                self.progress(
                    "KB: mapeando conteúdo — "
                    f"{len(visited) + pagination_pages} páginas analisadas, "
                    f"{len(articles)} artigos encontrados, "
                    f"{len(queue)} categorias pendentes."
                )
        self.progress(
            "KB: mapeamento concluído — "
            f"{len(visited) + pagination_pages} páginas analisadas e "
            f"{len(articles)} artigos distintos; "
            f"{page_errors} páginas com erro."
        )
        return articles

    def _storage_cookie_header(self) -> str:
        if not self.settings.movidesk_state_path.exists():
            return ""
        try:
            payload = json.loads(
                self.settings.movidesk_state_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return ""
        host = self._normalized_host(self.settings.kb_url).split(":", 1)[0]
        cookies = []
        for cookie in payload.get("cookies", []):
            domain = str(cookie.get("domain", "")).lstrip(".").lower()
            if domain and (host == domain or host.endswith(f".{domain}")):
                cookies.append(f"{cookie.get('name', '')}={cookie.get('value', '')}")
        return "; ".join(cookies)

    def _http_page_links(self, url: str, cookie_header: str) -> list[str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT; Windows NT 10.0; pt-BR) "
                "WindowsPowerShell/5.1"
            ),
            "Accept": "text/html, application/xhtml+xml, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header
        request = urllib.request.Request(url, headers=headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    final_url = response.geturl()
                    html = response.read().decode("utf-8", errors="replace")
                break
            except (TimeoutError, urllib.error.URLError, OSError):
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        soup = BeautifulSoup(html, "html.parser")
        if (
            urllib.parse.urlsplit(final_url).path.lower()
            == self.LOGIN_PATH.lower()
            or soup.select_one("input[type=password]")
        ):
            raise MovideskInteractiveLoginRequired(
                "A sessão Movidesk expirou durante o mapeamento das categorias."
            )
        return [
            str(anchor.get("href"))
            for anchor in soup.select("a[href]")
            if anchor.get("href")
        ]

    def _page_links(self, page) -> list[str]:
        return page.locator(self.ARTICLE_LINK_SELECTOR).evaluate_all(
            """(els) => els.map(e =>
                e.href || e.getAttribute('data-href') || e.getAttribute('data-url')
            ).filter(Boolean)"""
        )

    def _paginated_result_links(self, page) -> tuple[list[str], int]:
        collected: list[str] = []
        seen_pages: set[tuple[str, ...]] = set()
        page_count = 0
        for _ in range(10_000):
            result_links = page.locator(self.RESULT_LINK_SELECTOR).evaluate_all(
                "(els) => els.map(e => e.href).filter(Boolean)"
            )
            signature = tuple(result_links)
            if signature in seen_pages:
                break
            seen_pages.add(signature)
            collected.extend(result_links)
            if result_links:
                page_count += 1

            next_buttons = page.locator(self.NEXT_PAGE_SELECTOR)
            if next_buttons.count() < 1:
                break
            next_button = next_buttons.last
            classes = next_button.get_attribute("class") or ""
            if (
                next_button.is_disabled()
                or "button-pagination-disabled" in classes
            ):
                break

            try:
                with page.expect_response(
                    lambda response: "/KbHome/SearchJSON" in response.url,
                    timeout=30_000,
                ):
                    next_button.click()
                page.wait_for_function(
                    """(previous) => {
                        const links = Array.from(document.querySelectorAll(
                            '.search-container-items a[href], ' +
                            '.search-container a.kb-article-hyperlink[href]'
                        )).map(element => element.href);
                        return JSON.stringify(links) !== JSON.stringify(previous);
                    }""",
                    arg=list(signature),
                    timeout=30_000,
                )
            except Exception as exc:
                LOGGER.warning(
                    "Falha ao avançar a paginação do KB em %s: %s",
                    page.url,
                    exc,
                )
                break
        return collected, page_count

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
        if self._is_article_url(url):
            query_pairs = []
        else:
            query_pairs = [
                (key, value)
                for key, value in query_pairs
                if key.lower() in {"kbcategoryid", "menuid"}
            ]
        query = urllib.parse.urlencode(sorted(query_pairs))
        path = urllib.parse.quote(
            urllib.parse.unquote(parsed.path),
            safe="/-._~",
        )
        return urllib.parse.urlunsplit(
            (scheme, netloc, path.rstrip("/") or "/kb", query, "")
        )

    @staticmethod
    def _is_article_url(url: str) -> bool:
        lowered = url.lower()
        return bool(
            re.search(r"/kb/(?:[a-z]{2}-[a-z]{2}/)?(article|artigo|a)/", lowered)
            or re.search(r"[?&](id|articleid|article)=\d+", lowered)
            or re.search(r"/kb/\d+/", lowered)
        )

    @staticmethod
    def _is_category_url(url: str) -> bool:
        return bool(
            re.search(
                r"/kb/(?:[a-z]{2}-[a-z]{2}/)?category(?:/|$)",
                url.lower(),
            )
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
        if not title:
            title = self._fallback_title(page.url)
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
    def _fallback_title(url: str) -> str:
        """Build a readable title when Movidesk renders an empty heading."""
        segments = [
            urllib.parse.unquote(segment)
            for segment in urllib.parse.urlsplit(url).path.split("/")
            if segment and not segment.isdigit()
        ]
        candidate = segments[-1] if segments else ""
        candidate = re.sub(r"[-_]+", " ", candidate).strip()
        return candidate[:1].upper() + candidate[1:] if candidate else "Artigo Movidesk"

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

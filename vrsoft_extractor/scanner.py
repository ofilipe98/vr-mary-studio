from __future__ import annotations

import html
import logging
import re
from collections import deque
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse

from .auth import ensure_session
from .inventory import load_inventory, merge_inventory, save_inventory
from .models import VideoItem
from .runtime import configure_playwright_runtime
from .settings import ConfigError, Settings, ensure_runtime_dirs, sensitive_values
from .utils import (
    absolutize_url,
    classify_media_url,
    is_media_url,
    is_same_site,
    looks_like_html_page,
    stable_id,
)

LOGGER = logging.getLogger(__name__)

MEDIA_PATTERN = re.compile(
    r"https?://[^'\"\s<>]+?(?:\.m3u8|\.mp4|\.m4v|\.webm)(?:\?[^'\"\s<>]+)?",
    re.IGNORECASE,
)
ATTR_MEDIA_PATTERN = re.compile(
    r"""(?:src|href|data-src|data-url|data-href)=["']([^"']+?(?:\.m3u8|\.mp4|\.m4v|\.webm)(?:\?[^"']*)?)["']""",
    re.IGNORECASE,
)
JWT_PATTERN = re.compile(r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)((?:access[_-]?token|auth[_-]?token|bearer|jwt|signature|sig|key|secret)"
    r"['\"\s:=]+)([^'\"\s<>&]+)"
)

BLOCKED_PATH_PREFIXES = (
    "/admin",
    "/blog",
    "/wiki",
    "/lojinha",
    "/dashboard",
    "/links",
    "/minha-performance",
    "/jornada",
    "/gestao-de-ideias",
    "/login",
    "/logout",
)
BLOCKED_TEXT_TERMS = (
    "sair",
    "logout",
    "login",
    "senha",
    "password",
    "perfil",
    "profile",
    "suporte",
    "support",
)
BLOCKED_ACTION_TERMS = (
    "inscrever",
    "inscricao",
    "inscrição",
    "matricular",
    "comprar",
    "adquirir",
    "assinar",
    "pagamento",
)
ACCESS_TEXTS = (
    "Assistir",
    "Continuar",
    "Iniciar",
    "Acessar",
    "Acessar aula",
    "Ver aula",
    "Abrir",
    "Comecar",
    "Começar",
    "Play",
    "Reproduzir",
)
API_BASE_URL = "https://api.iendo.us/api"
API_HEADER_KEYS = (
    "authorization",
    "site-domain",
    "site-hashid",
    "x-site-id",
    "x-user-id",
    "accept",
    "content-type",
    "referer",
    "user-agent",
)
HABILIZE_HOSTS = (
    "https://storage.fiqueligadonews.com.br",
    "https://iendo.b-cdn.net",
)


@dataclass(frozen=True)
class LinkCandidate:
    url: str
    text: str


@dataclass(frozen=True)
class SectionSpec:
    area: str
    label: str
    root_path: str
    max_depth: int = 10


SECTION_SPECS = (
    SectionSpec(area="biblioteca", label="Biblioteca", root_path="/arquivos"),
    SectionSpec(area="curso", label="Cursos", root_path="/cursos"),
)


class MediaRecorder:
    def __init__(self) -> None:
        self.urls: set[str] = set()
        self.all_urls: set[str] = set()
        self.api_headers: dict[str, str] = {}

    def request_handler(self, request) -> None:
        if not request.url.startswith(API_BASE_URL):
            return
        headers = request.headers
        self.api_headers.update(
            {key: headers[key] for key in API_HEADER_KEYS if key in headers}
        )

    def response_handler(self, response) -> None:
        url = response.url
        self.all_urls.add(url)
        if is_media_url(url):
            self.urls.add(url)

    def clear(self) -> None:
        self.urls.clear()
        self.all_urls.clear()


def scan(
    settings: Settings,
    *,
    headless: bool = True,
    diagnostic: bool = False,
) -> list[VideoItem]:
    ensure_runtime_dirs(settings)
    ensure_session(settings, headless=headless)
    configure_playwright_runtime()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ConfigError(
            "Playwright nao esta instalado. Execute: python -m pip install -e ."
        ) from exc

    LOGGER.info("Iniciando varredura autenticada")
    if diagnostic:
        LOGGER.info("Diagnostico ativado: paginas sem video serao salvas em metadata/debug")
    discovered: list[VideoItem] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(settings.storage_state_path))
        page = context.new_page()
        page.set_default_timeout(15_000)
        recorder = MediaRecorder()
        page.on("request", recorder.request_handler)
        page.on("response", recorder.response_handler)

        for spec in SECTION_SPECS:
            try:
                start_url = f"{settings.base_url}{spec.root_path}"
                LOGGER.info("Varrendo %s a partir de %s", spec.label, start_url)
                api_items = _crawl_api_section(
                    page=page,
                    recorder=recorder,
                    settings=settings,
                    spec=spec,
                    start_url=start_url,
                )
                if api_items:
                    discovered.extend(api_items)
                else:
                    discovered.extend(
                        _crawl_section(
                            page=page,
                            recorder=recorder,
                            settings=settings,
                            spec=spec,
                            start_url=start_url,
                            diagnostic=diagnostic,
                        )
                    )
            except Exception as exc:
                LOGGER.exception("Falha ao varrer %s: %s", spec.label, exc)

        browser.close()

    existing = load_inventory(settings.inventory_json_path)
    merged = merge_inventory(existing, discovered)
    save_inventory(merged, settings.inventory_json_path, settings.inventory_csv_path)
    LOGGER.info("Inventario salvo com %s videos", len(merged))
    return merged


def _open_section(page, base_url: str, label: str) -> str:
    page.goto(f"{base_url}/frontpage", wait_until="domcontentloaded")
    _wait_quiet(page)
    for selector in (
        f'a:has-text("{label}")',
        f'button:has-text("{label}")',
        f'text="{label}"',
        f'text=/{label}/i',
    ):
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                before = page.url
                locator.click()
                _wait_quiet(page)
                if page.url != before or label.lower() in page.content().lower():
                    return page.url
        except Exception:
            continue

    guesses = {
        "Biblioteca": ["/biblioteca", "/library"],
        "Cursos": ["/cursos", "/courses", "/course"],
    }
    for path in guesses.get(label, []):
        url = f"{base_url}{path}"
        try:
            page.goto(url, wait_until="domcontentloaded")
            _wait_quiet(page)
            if "404" not in page.title().lower():
                return page.url
        except Exception:
            continue
    page.goto(f"{base_url}/frontpage", wait_until="domcontentloaded")
    _wait_quiet(page)
    return page.url


def _crawl_api_section(
    *,
    page,
    recorder: MediaRecorder,
    settings: Settings,
    spec: SectionSpec,
    start_url: str,
) -> list[VideoItem]:
    _prime_api_headers(page, recorder, start_url)
    if not recorder.api_headers:
        LOGGER.warning("[%s] Cabecalhos da API nao capturados; usando fallback DOM", spec.label)
        return []
    if spec.area == "biblioteca":
        return _crawl_files_api(page, recorder, settings)
    if spec.area == "curso":
        return _crawl_courses_api(page, recorder, settings)
    return []


def _prime_api_headers(page, recorder: MediaRecorder, start_url: str) -> None:
    recorder.clear()
    page.goto(start_url, wait_until="domcontentloaded")
    _wait_quiet(page)
    page.wait_for_timeout(1_000)


def _crawl_files_api(page, recorder: MediaRecorder, settings: Settings) -> list[VideoItem]:
    queue: deque[tuple[int, list[str]]] = deque([(0, [])])
    seen_folders: set[int] = set()
    found: list[VideoItem] = []

    while queue and len(seen_folders) < settings.max_pages_per_section:
        folder_id, folder_path = queue.popleft()
        if folder_id in seen_folders:
            continue
        seen_folders.add(folder_id)
        data = _api_get_json(page, recorder, f"{API_BASE_URL}/files/files/{folder_id}")
        for item in data.get("files", []) if isinstance(data, dict) else []:
            name = str(item.get("name") or item.get("file_name") or item.get("id") or "item")
            item_path = [*folder_path, name]
            if item.get("type") == "folder":
                try:
                    queue.append((int(item["id"]), item_path))
                except (KeyError, TypeError, ValueError):
                    LOGGER.debug("Pasta sem id valido ignorada: %s", name)
                continue

            for media_url in _media_urls_from_file_item(item):
                found.append(
                    VideoItem(
                        area="biblioteca",
                        course=item_path[0] if len(item_path) > 1 else "",
                        module=" / ".join(item_path[1:-1]),
                        lesson_title=name,
                        page_url=f"{settings.base_url}/arquivos#file-{item.get('id', '')}",
                        media_url=media_url,
                        media_type=classify_media_url(media_url),
                    )
                )

    LOGGER.info("[Biblioteca] Pastas API visitadas: %s", len(seen_folders))
    LOGGER.info("[Biblioteca] Videos API encontrados: %s", len(found))
    return found


def _crawl_courses_api(page, recorder: MediaRecorder, settings: Settings) -> list[VideoItem]:
    found: list[VideoItem] = []
    page_index = 0
    visited_courses = 0

    while page_index < settings.max_pages_per_section:
        courses = _api_get_json(
            page,
            recorder,
            (
                f"{API_BASE_URL}/courses/student/?items=&filter=all&status=all"
                f"&category_id=all&class_status=all&shelf=0&include_training_courses=0"
                f"&order=created_at&position=0&limit=8&page={page_index}&required=0"
            ),
        )
        if not isinstance(courses, list) or not courses:
            break

        for course in courses:
            participant = course.get("participant") or {}
            participant_id = participant.get("id")
            course_id = course.get("id")
            if not participant_id or not course_id:
                LOGGER.info(
                    "[Cursos] Ignorando curso sem inscricao ativa: %s",
                    course.get("name") or course_id,
                )
                continue

            visited_courses += 1
            course_detail = _api_get_json(
                page,
                recorder,
                f"{API_BASE_URL}/courses/{course_id}/{participant_id}",
            )
            found.extend(
                _videos_from_course_detail(
                    page=page,
                    recorder=recorder,
                    settings=settings,
                    course=course_detail if isinstance(course_detail, dict) else course,
                    course_fallback=course,
                    participant_id=participant_id,
                )
            )

        page_index += 1

    LOGGER.info("[Cursos] Paginas API de cursos visitadas: %s", page_index)
    LOGGER.info("[Cursos] Cursos inscritos processados: %s", visited_courses)
    LOGGER.info("[Cursos] Videos API encontrados: %s", len(found))
    return found


def _videos_from_course_detail(
    *,
    page,
    recorder: MediaRecorder,
    settings: Settings,
    course: dict,
    course_fallback: dict,
    participant_id: int,
) -> list[VideoItem]:
    found: list[VideoItem] = []
    course_id = course.get("id") or course_fallback.get("id")
    course_name = str(course.get("name") or course_fallback.get("name") or f"Curso {course_id}")
    if not course_id:
        return found

    for chapter in course.get("chapters", []) or []:
        chapter_name = str(chapter.get("name") or "")
        for task in chapter.get("tasks", []) or []:
            if task.get("enabled") in (False, 0):
                continue
            task_id = task.get("id")
            if not task_id:
                continue
            task_detail = _api_get_json(
                page,
                recorder,
                f"{API_BASE_URL}/courses/task/{task_id}/participant/{participant_id}",
            )
            if not isinstance(task_detail, dict):
                continue
            title = str(task_detail.get("name") or task.get("name") or f"Aula {task_id}")
            route_url = f"{settings.base_url}/cursos/curso/habilize/{course_id}/{task_id}/{participant_id}"
            media_urls = _media_urls_from_any(task_detail, settings.base_url)
            habilize_path = task_detail.get("habilize")
            if isinstance(habilize_path, str) and habilize_path:
                media_urls = _merge_unique(
                    media_urls,
                    _media_urls_from_habilize(page, habilize_path, settings.base_url),
                )
            if not media_urls:
                media_urls = _merge_unique(
                    media_urls,
                    _media_urls_from_habilize_route(page, recorder, route_url),
                )
            for media_url in media_urls:
                found.append(
                    VideoItem(
                        area="curso",
                        course=course_name,
                        module=chapter_name,
                        lesson_title=title,
                        page_url=route_url,
                        media_url=media_url,
                        media_type=classify_media_url(media_url),
                    )
                )
    return found


def _api_get_json(page, recorder: MediaRecorder, url: str):
    response = page.request.get(url, headers=recorder.api_headers)
    if response.status >= 400:
        LOGGER.warning("API retornou %s para %s", response.status, _sanitize_url_for_debug(url))
        return {}
    try:
        return response.json()
    except Exception as exc:
        LOGGER.warning("Resposta API nao JSON em %s: %s", _sanitize_url_for_debug(url), exc)
        return {}


def _media_urls_from_file_item(item: dict) -> list[str]:
    file_data = item.get("file") if isinstance(item.get("file"), dict) else {}
    content_type = str(file_data.get("content_type") or item.get("mime_type") or "").lower()
    raw_urls = [
        str(value)
        for value in (
            item.get("url"),
            item.get("path"),
            item.get("download_url"),
            file_data.get("path"),
            file_data.get("url"),
        )
        if value
    ]
    if not content_type.startswith("video") and not any(classify_media_url(url) in {"mp4", "hls"} for url in raw_urls):
        return []
    return _unique_media_urls(raw_urls, "https://vrsoft.endoo.com.br/arquivos")


def _media_urls_from_any(value, base_url: str) -> list[str]:
    raw_urls: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str):
            raw_urls.append(node)

    walk(value)
    return _unique_media_urls(raw_urls, base_url)


def _media_urls_from_habilize(page, habilize_path: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for url in _candidate_habilize_urls(habilize_path, base_url):
        try:
            response = page.request.get(url)
        except Exception as exc:
            LOGGER.debug("Falha ao buscar habilize %s: %s", _sanitize_url_for_debug(url), exc)
            continue
        if response.status >= 400:
            continue
        try:
            content = response.text()
            urls = _merge_unique(
                urls,
                _extract_media_urls_from_html(content, url),
            )
            for page_url in _habilize_page_urls(content, url):
                try:
                    page_response = page.request.get(page_url)
                except Exception:
                    continue
                if page_response.status >= 400:
                    continue
                urls = _merge_unique(
                    urls,
                    _extract_media_urls_from_html(page_response.text(), page_url),
                )
        except Exception as exc:
            LOGGER.debug("Falha ao extrair habilize %s: %s", _sanitize_url_for_debug(url), exc)
    return urls


def _habilize_page_urls(index_html: str, index_url: str) -> list[str]:
    page_ids = sorted(set(re.findall(r"#(\d+)\.html", index_html)))
    return [urljoin(index_url, f"pages/{page_id}.html") for page_id in page_ids]


def _media_urls_from_habilize_route(page, recorder: MediaRecorder, route_url: str) -> list[str]:
    recorder.clear()
    try:
        page.goto(route_url, wait_until="domcontentloaded")
        _wait_quiet(page)
        page.wait_for_timeout(3_000)
    except Exception as exc:
        LOGGER.debug("Falha ao abrir rota habilize %s: %s", _sanitize_url_for_debug(route_url), exc)
        return []

    try:
        perf_urls = page.evaluate(
            """() => performance.getEntriesByType("resource").map((entry) => entry.name)"""
        )
    except Exception:
        perf_urls = []
    html_content = ""
    try:
        html_content = page.content()
    except Exception:
        pass
    return _extract_media_urls_from_html(
        html_content,
        page.url,
        extra_urls=[*recorder.urls, *perf_urls],
    )


def _candidate_habilize_urls(habilize_path: str, base_url: str) -> list[str]:
    if habilize_path.startswith("http://") or habilize_path.startswith("https://"):
        return [habilize_path]
    if not habilize_path.startswith("/"):
        habilize_path = "/" + habilize_path
    return [*(host + habilize_path for host in HABILIZE_HOSTS), base_url.rstrip("/") + habilize_path]


def _crawl_section(
    *,
    page,
    recorder: MediaRecorder,
    settings: Settings,
    spec: SectionSpec,
    start_url: str,
    diagnostic: bool,
) -> list[VideoItem]:
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    seen_pages: set[str] = set()
    seen_media: set[str] = set()
    found: list[VideoItem] = []
    max_pages = settings.max_pages_per_section

    while queue and len(seen_pages) < max_pages:
        current_url, depth = queue.popleft()
        current_url = _normalize_page_url(current_url)
        if current_url in seen_pages:
            continue
        if not _is_allowed_tree_url(current_url, spec, settings.base_url):
            LOGGER.debug("[%s] Ignorando fora da arvore: %s", spec.label, current_url)
            continue
        seen_pages.add(current_url)
        LOGGER.info("[%s] Visitando %s", spec.label, current_url)

        media_urls, links, page_meta = _inspect_page(
            page,
            recorder,
            current_url,
            settings.base_url,
            spec,
        )
        for index, media_url in enumerate(media_urls, start=1):
            if media_url in seen_media:
                continue
            seen_media.add(media_url)
            title = page_meta["title"]
            if len(media_urls) > 1:
                title = f"{title} - video {index}"
            found.append(
                VideoItem(
                    area=spec.area,
                    course=_course_from_breadcrumb(spec.area, page_meta["breadcrumbs"]),
                    module=_module_from_breadcrumb(spec.area, page_meta["breadcrumbs"]),
                    lesson_title=title,
                    page_url=page_meta["page_url"],
                    media_url=media_url,
                    media_type=classify_media_url(media_url),
                )
            )

        if diagnostic and not media_urls:
            _write_debug_artifacts(
                page=page,
                settings=settings,
                spec=spec,
                page_meta=page_meta,
                urls=page_meta["resource_urls"],
            )

        if depth >= spec.max_depth:
            continue
        for link in links:
            if _should_follow(link, spec, settings.base_url):
                normalized = _normalize_page_url(link.url)
                if normalized not in seen_pages:
                    queue.append((normalized, depth + 1))

    if len(seen_pages) >= max_pages:
        LOGGER.warning("Limite de paginas atingido em %s: %s", spec.label, max_pages)
    LOGGER.info("[%s] Videos encontrados: %s", spec.label, len(found))
    return found


def _inspect_page(
    page,
    recorder: MediaRecorder,
    url: str,
    base_url: str,
    spec: SectionSpec,
):
    recorder.clear()
    page.goto(url, wait_until="domcontentloaded")
    media_urls, links, page_meta = _inspect_current_page(page, recorder, base_url)

    if not media_urls:
        for _ in range(3):
            if not _click_access_control(page):
                break
            more_media, more_links, more_meta = _inspect_current_page(page, recorder, base_url)
            media_urls = _merge_unique(media_urls, more_media)
            links = _merge_links(links, more_links)
            page_meta = _merge_page_meta(page_meta, more_meta)
            if media_urls or not _is_allowed_tree_url(page.url, spec, base_url):
                break

    return media_urls, links, page_meta


def _inspect_current_page(page, recorder: MediaRecorder, base_url: str):
    _wait_quiet(page)
    _scroll_page(page)
    dom_data = page.evaluate(
        """
        () => {
          const attrUrls = [];
          const pushAttrs = (el) => {
            for (const attr of ["src", "href", "data-src", "data-url", "data-href"]) {
              const value = el.getAttribute(attr);
              if (value) attrUrls.push(value);
            }
          };
          document.querySelectorAll("video, source, iframe, embed, a, [data-src], [data-url], [data-href]").forEach(pushAttrs);
          const perfUrls = performance.getEntriesByType("resource").map((entry) => entry.name);
          const titleNode = document.querySelector("h1, [role='heading'], h2");
          const breadcrumbs = Array.from(
            document.querySelectorAll("[aria-label*='breadcrumb' i] a, nav a, .breadcrumb a, .breadcrumbs a")
          ).map((el) => (el.innerText || el.textContent || "").trim()).filter(Boolean);
          return {
            urls: attrUrls.concat(perfUrls),
            title: ((titleNode && (titleNode.innerText || titleNode.textContent)) || document.title || "").trim(),
            breadcrumbs
          };
        }
        """
    )

    html_content = html.unescape(page.content()).replace("\\/", "/")
    raw_urls = [*recorder.urls, *dom_data.get("urls", []), *MEDIA_PATTERN.findall(html_content)]
    media_urls = _extract_media_urls_from_html(
        html_content,
        page.url,
        extra_urls=[str(url) for url in raw_urls],
    )
    links = _collect_links(page, base_url)
    meta = {
        "title": (dom_data.get("title") or "video").strip(),
        "breadcrumbs": dom_data.get("breadcrumbs", []),
        "page_url": page.url,
        "resource_urls": _merge_unique(
            [str(url) for url in recorder.all_urls],
            [str(url) for url in dom_data.get("urls", [])],
        ),
    }
    return media_urls, links, meta


def _extract_media_urls_from_html(
    html_content: str,
    page_url: str,
    *,
    extra_urls: list[str] | tuple[str, ...] = (),
) -> list[str]:
    normalized = html.unescape(html_content).replace("\\/", "/")
    urls = [*extra_urls, *MEDIA_PATTERN.findall(normalized), *ATTR_MEDIA_PATTERN.findall(normalized)]
    return _unique_media_urls([str(url) for url in urls], page_url)


def _unique_media_urls(raw_urls: list[str], page_url: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_urls:
        if not raw:
            continue
        url = absolutize_url(str(raw), page_url)
        url = html.unescape(url).replace("\\/", "/")
        if not is_media_url(url):
            continue
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def _collect_links(page, base_url: str) -> list[LinkCandidate]:
    rows = page.evaluate(
        """
        () => Array.from(document.querySelectorAll("a[href]")).map((a) => ({
          url: a.href,
          text: (a.innerText || a.textContent || "").trim()
        }))
        """
    )
    links: list[LinkCandidate] = []
    for row in rows:
        url = _normalize_page_url(row.get("url", ""))
        if not url or not is_same_site(url, base_url) or not looks_like_html_page(url):
            continue
        links.append(LinkCandidate(url=url, text=row.get("text", "")))
    return links


def _should_follow(link: LinkCandidate, spec: SectionSpec, base_url: str) -> bool:
    if not _is_allowed_tree_url(link.url, spec, base_url):
        return False
    text_lower = link.text.lower()
    url_lower = link.url.lower()
    if any(term in text_lower or term in url_lower for term in BLOCKED_TEXT_TERMS):
        return False
    if any(term in text_lower or term in url_lower for term in BLOCKED_ACTION_TERMS):
        return False
    return True


def _is_allowed_tree_url(url: str, spec: SectionSpec, base_url: str) -> bool:
    if not is_same_site(url, base_url) or not looks_like_html_page(url):
        return False
    path = urlparse(url).path.rstrip("/") or "/"
    path_lower = path.lower()
    if any(path_lower == prefix or path_lower.startswith(prefix + "/") for prefix in BLOCKED_PATH_PREFIXES):
        return False
    root = spec.root_path.rstrip("/").lower()
    return path_lower == root or path_lower.startswith(root + "/")


def _click_access_control(page) -> bool:
    selectors = [
        'button[aria-label*="play" i]',
        'a[aria-label*="play" i]',
        '[role="button"][aria-label*="play" i]',
    ]
    selectors.extend(
        selector
        for text in ACCESS_TEXTS
        for selector in (
            f'button:has-text("{text}")',
            f'a:has-text("{text}")',
            f'[role="button"]:has-text("{text}")',
        )
    )

    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = min(locator.count(), 5)
        except Exception:
            continue
        for index in range(count):
            element = locator.nth(index)
            try:
                if not element.is_visible():
                    continue
                text = (element.inner_text(timeout=1_000) or "").strip().lower()
                href = (element.get_attribute("href", timeout=1_000) or "").lower()
                if any(term in text or term in href for term in BLOCKED_ACTION_TERMS):
                    continue
                element.click(timeout=3_000)
                _wait_quiet(page)
                _scroll_page(page)
                return True
            except Exception:
                continue
    return False


def _write_debug_artifacts(
    *,
    page,
    settings: Settings,
    spec: SectionSpec,
    page_meta: dict,
    urls: list[str],
) -> None:
    debug_dir = settings.metadata_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    artifact_id = stable_id(spec.area, page.url, page_meta.get("title", ""))
    prefix = debug_dir / f"{spec.area}_{artifact_id}"

    try:
        (prefix.with_suffix(".html")).write_text(
            _sanitize_debug_text(page.content()),
            encoding="utf-8",
        )
    except Exception as exc:
        LOGGER.debug("Falha ao salvar HTML diagnostico de %s: %s", page.url, exc)

    try:
        page.screenshot(path=str(prefix.with_suffix(".png")), full_page=True)
    except Exception as exc:
        LOGGER.debug("Falha ao salvar screenshot diagnostico de %s: %s", page.url, exc)

    safe_urls = sorted({_sanitize_url_for_debug(str(url)) for url in urls if url})
    try:
        (prefix.with_suffix(".urls.txt")).write_text(
            "\n".join([_sanitize_url_for_debug(page.url), *safe_urls]) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        LOGGER.debug("Falha ao salvar URLs diagnostico de %s: %s", page.url, exc)


def _sanitize_debug_text(value: str) -> str:
    sanitized = value
    for secret in sensitive_values():
        sanitized = sanitized.replace(secret, "***")
    sanitized = JWT_PATTERN.sub("***JWT***", sanitized)
    sanitized = SECRET_ASSIGNMENT_PATTERN.sub(r"\1***", sanitized)
    return sanitized


def _sanitize_url_for_debug(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return urlunparse(parsed._replace(fragment=""))
    safe_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_sensitive_query_key(key):
            safe_query.append((key, "***"))
        else:
            safe_query.append((key, value[:80]))
    return urlunparse(parsed._replace(query=urlencode(safe_query), fragment=""))


def _is_sensitive_query_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        term in lowered
        for term in (
            "token",
            "signature",
            "sig",
            "key",
            "secret",
            "auth",
            "jwt",
            "credential",
        )
    )


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in [*first, *second]:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _merge_links(first: list[LinkCandidate], second: list[LinkCandidate]) -> list[LinkCandidate]:
    result: list[LinkCandidate] = []
    seen: set[str] = set()
    for item in [*first, *second]:
        if item.url not in seen:
            seen.add(item.url)
            result.append(item)
    return result


def _merge_page_meta(first: dict, second: dict) -> dict:
    merged = dict(first)
    if second.get("title") and second.get("title") != "video":
        merged["title"] = second["title"]
    if second.get("breadcrumbs"):
        merged["breadcrumbs"] = second["breadcrumbs"]
    if second.get("page_url"):
        merged["page_url"] = second["page_url"]
    merged["resource_urls"] = _merge_unique(
        [str(url) for url in first.get("resource_urls", [])],
        [str(url) for url in second.get("resource_urls", [])],
    )
    return merged


def _normalize_page_url(url: str) -> str:
    clean, _fragment = urldefrag(url)
    return clean.rstrip("/")


def _course_from_breadcrumb(area: str, breadcrumbs: list[str]) -> str:
    if area != "curso":
        return ""
    cleaned = [item for item in breadcrumbs if item.lower() not in {"home", "inicio", "início", "cursos"}]
    return cleaned[0] if cleaned else ""


def _module_from_breadcrumb(area: str, breadcrumbs: list[str]) -> str:
    if area != "curso":
        return ""
    cleaned = [item for item in breadcrumbs if item.lower() not in {"home", "inicio", "início", "cursos"}]
    return cleaned[1] if len(cleaned) > 1 else ""


def _scroll_page(page) -> None:
    try:
        for _ in range(4):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(500)
    except Exception:
        pass


def _wait_quiet(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

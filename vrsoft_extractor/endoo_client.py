from __future__ import annotations

import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any

from .auth import ensure_session, login
from .runtime import configure_playwright_runtime
from .scanner import API_HEADER_KEYS
from .settings import ConfigError, Settings, load_settings


LOGGER = logging.getLogger(__name__)


class EndooError(RuntimeError):
    """Base error for read-only Endoo API operations."""


class EndooAuthenticationRequired(EndooError):
    pass


class EndooPermissionDenied(EndooError):
    pass


class EndooFeatureUnavailable(EndooError):
    pass


class EndooRateLimited(EndooError):
    pass


class EndooInvalidResponse(EndooError):
    pass


class EndooAssetUnavailable(EndooError):
    """Raised when an optional asset origin does not answer in time."""

    def __init__(self, host: str) -> None:
        self.host = str(host or "").casefold()
        super().__init__(f"Host de recurso Endoo sem resposta: {self.host}")


class EndooReadClient:
    """Authenticated, read-only Endoo client backed by the saved browser session."""

    def __init__(
        self,
        project_dir: Path,
        *,
        base_url: str,
        api_url: str,
        headless: bool = True,
        entry_path: str = "/wiki",
    ) -> None:
        self.settings: Settings = load_settings(project_dir, base_url=base_url)
        self.api_url = str(api_url).rstrip("/")
        self.headless = bool(headless)
        self.entry_path = "/" + str(entry_path or "/wiki").lstrip("/")
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None
        self.headers: dict[str, str] = {}

    def login(self) -> Path:
        return login(self.settings, headless=False, force=True)

    def __enter__(self) -> "EndooReadClient":
        ensure_session(self.settings, headless=self.headless)
        configure_playwright_runtime()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ConfigError("Playwright nao esta instalado") from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            storage_state=str(self.settings.storage_state_path)
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(20_000)

        def capture(request) -> None:
            request_url = urllib.parse.urlsplit(str(request.url))
            api_url = urllib.parse.urlsplit(self.api_url)
            if (
                self._origin(request_url) != self._origin(api_url)
                or not (
                    request_url.path == api_url.path
                    or request_url.path.startswith(api_url.path + "/")
                )
            ):
                return
            request_headers = request.headers
            self.headers.update(
                {
                    key: request_headers[key]
                    for key in API_HEADER_KEYS
                    if key in request_headers
                }
            )

        self.page.on("request", capture)
        self.page.goto(
            urllib.parse.urljoin(self.settings.base_url + "/", self.entry_path.lstrip("/")),
            wait_until="domcontentloaded",
        )
        try:
            self.page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        self.page.wait_for_timeout(500)
        if "/login" in str(self.page.url).casefold():
            self.close()
            raise EndooAuthenticationRequired(
                "Sessao Endoo expirada. Execute o login visivel e tente novamente."
            )
        if not self.headers:
            self.close()
            raise EndooPermissionDenied(
                "A Wiki Endoo nao carregou a API autenticada. Verifique a permissao wiki_visualizar."
            )
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        for value in (self._context, self._browser, self._playwright):
            if value is None:
                continue
            try:
                value.close() if hasattr(value, "close") else value.stop()
            except Exception:
                pass
        self.page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        attempts: int = 3,
    ) -> Any:
        normalized = "/" + str(path or "").lstrip("/")
        if not normalized.startswith("/wiki/") and normalized != "/wiki":
            raise EndooPermissionDenied(
                "O cliente de leitura Endoo aceita somente endpoints /wiki."
            )
        if normalized.startswith("/wiki/manage"):
            raise EndooPermissionDenied(
                "Endpoints administrativos da Wiki Endoo sao bloqueados."
            )
        url = self.api_url + normalized
        if params:
            url += "?" + urllib.parse.urlencode(
                {key: value for key, value in params.items() if value is not None}
            )
        if self.page is None:
            raise EndooError("Cliente Endoo nao inicializado.")
        last_status = 0
        for attempt in range(1, max(1, int(attempts)) + 1):
            # An API redirect must not forward session headers to another origin.
            response = self.page.request.get(
                url, headers=self.headers, timeout=60_000, max_redirects=0
            )
            last_status = int(response.status)
            if 200 <= last_status < 300:
                try:
                    return response.json()
                except Exception as exc:
                    raise EndooInvalidResponse(
                        f"A API da Wiki Endoo retornou JSON invalido em {normalized}."
                    ) from exc
            if last_status == 401:
                raise EndooAuthenticationRequired("Sessao Endoo expirada.")
            if last_status == 403:
                raise EndooPermissionDenied(
                    "A conta Endoo nao possui permissao para visualizar a Wiki."
                )
            if last_status == 404:
                raise EndooFeatureUnavailable(
                    f"Recurso da Wiki Endoo indisponivel: {normalized}"
                )
            if last_status == 429 and attempt >= max(1, int(attempts)):
                raise EndooRateLimited("A API da Wiki Endoo limitou as requisicoes.")
            if last_status not in {429, 500, 502, 503, 504}:
                raise EndooError(
                    f"A API da Wiki Endoo retornou HTTP {last_status} em {normalized}."
                )
            time.sleep(min(2.0, 0.25 * (2 ** (attempt - 1))))
        raise EndooError(
            f"A API da Wiki Endoo permaneceu indisponivel (HTTP {last_status})."
        )

    def get_bytes(self, url: str) -> bytes:
        if self.page is None:
            raise EndooError("Cliente Endoo nao inicializado.")
        api_origin = self._origin(urllib.parse.urlsplit(self.api_url))
        for _hop in range(6):
            parsed = self._validate_asset_url(url)
            authenticated = self._origin(parsed) == api_origin
            headers = dict(self.headers) if authenticated else {}
            # A browser request shares its cookie jar, even across ports and
            # cookie-compatible subdomains. Each public hop gets an empty jar.
            public_context = None
            if authenticated:
                request = self.page.request
            else:
                public_context = self._playwright.request.new_context()
                request = public_context
            response = None
            try:
                try:
                    response = request.get(
                        url,
                        headers=headers,
                        timeout=60_000 if authenticated else 10_000,
                        max_redirects=0,
                    )
                except Exception as exc:
                    if not authenticated and exc.__class__.__name__ == "TimeoutError":
                        raise EndooAssetUnavailable(parsed.hostname or "") from exc
                    raise
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "")
                    if not location:
                        raise EndooError("Redirecionamento de recurso Endoo sem destino.")
                    url = urllib.parse.urljoin(url, location)
                    continue
                if response.status < 200 or response.status >= 300:
                    raise EndooError(f"Recurso Endoo retornou HTTP {response.status}.")
                return response.body()
            finally:
                if response is not None:
                    response.dispose()
                if public_context is not None:
                    public_context.dispose()
        raise EndooError("Recurso Endoo excedeu o limite de redirecionamentos.")

    @staticmethod
    def _origin(parsed: urllib.parse.SplitResult) -> tuple[str, str, int | None]:
        return (
            parsed.scheme.casefold(),
            (parsed.hostname or "").casefold(),
            parsed.port if parsed.port is not None else (
                443 if parsed.scheme.casefold() == "https" else 80
            ),
        )

    @staticmethod
    def _validate_asset_url(url: str) -> urllib.parse.SplitResult:
        parsed = urllib.parse.urlsplit(str(url or ""))
        if (
            parsed.scheme.casefold() != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
        ):
            raise EndooPermissionDenied("Recurso Endoo com URL insegura.")
        host = parsed.hostname.casefold()
        allowed_suffixes = (
            "endoo.com.br",
            "iendo.us",
            "b-cdn.net",
            "fiqueligadonews.com.br",
            "vrsoft.com.br",
        )
        if not any(host == suffix or host.endswith("." + suffix) for suffix in allowed_suffixes):
            raise EndooPermissionDenied(
                f"Host de recurso nao permitido para a Wiki Endoo: {host}"
            )
        return parsed

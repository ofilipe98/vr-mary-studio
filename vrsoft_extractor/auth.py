from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from .runtime import configure_playwright_runtime
from .settings import ConfigError, Settings, ensure_runtime_dirs, get_credentials

LOGGER = logging.getLogger(__name__)

EMAIL_SELECTORS = [
    "#username",
    'input[name="username"]',
    'input[type="email"]',
    'input[name="email"]',
    'input[name*="email" i]',
    'input[name*="login" i]',
    'input[autocomplete="username"]',
]
PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    'input[name*="password" i]',
    'input[name*="senha" i]',
    'input[autocomplete="current-password"]',
]
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Entrar")',
    'button:has-text("Login")',
    'button:has-text("Acessar")',
    'text=/entrar/i',
]


class AuthError(RuntimeError):
    """Raised when authentication cannot be completed."""


def login(settings: Settings, *, headless: bool = False, force: bool = False) -> Path:
    ensure_runtime_dirs(settings)
    configure_playwright_runtime()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ConfigError(
            "Playwright nao esta instalado. Execute: python -m pip install -e ."
        ) from exc

    LOGGER.info("Iniciando autenticacao em %s", settings.base_url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context_args: dict[str, Any] = {}
        if settings.storage_state_path.exists() and not force:
            context_args["storage_state"] = str(settings.storage_state_path)
        context = browser.new_context(**context_args)
        page = context.new_page()
        page.set_default_timeout(15_000)
        page.goto(f"{settings.base_url}/frontpage", wait_until="domcontentloaded")
        _quiet_network_idle(page)

        if not force and not _is_login_page(page):
            context.storage_state(path=str(settings.storage_state_path))
            browser.close()
            LOGGER.info("Sessao existente ainda esta valida")
            return settings.storage_state_path

        credentials = get_credentials(required=False)
        if credentials:
            LOGGER.info("Preenchendo formulario de login com credenciais do .env")
            username_filled = _fill_first(page, EMAIL_SELECTORS, credentials.email)
            if not username_filled:
                LOGGER.warning("Campo de usuario nao encontrado automaticamente")

            # The current Endoo login is a two-step form: only #username is
            # visible initially and submitting it reveals #password. Keep
            # compatibility with older single-step forms as well.
            if username_filled and not _has_visible(page, PASSWORD_SELECTORS):
                if _click_first(page, SUBMIT_SELECTORS):
                    _wait_for_any_visible(page, PASSWORD_SELECTORS, timeout_ms=15_000)
                else:
                    LOGGER.warning("Botao para avancar no login nao encontrado")

            password_filled = _fill_first(
                page, PASSWORD_SELECTORS, credentials.password
            )
            if not password_filled:
                LOGGER.warning("Campo de senha nao encontrado automaticamente")
            if password_filled and not _click_first(page, SUBMIT_SELECTORS):
                LOGGER.warning("Botao de login nao encontrado automaticamente")
            _wait_for_login_success(page, timeout_seconds=45)

        if _is_login_page(page):
            if headless:
                browser.close()
                raise AuthError(
                    "Login nao concluido em modo headless. Rode sem --headless para finalizar manualmente."
                )
            if _should_wait_without_prompt():
                LOGGER.info(
                    "Finalize o login no navegador aberto. Aguardando conclusao automaticamente."
                )
                _wait_for_login_success(page, timeout_seconds=600)
            else:
                LOGGER.info(
                    "Finalize o login no navegador aberto. Depois pressione Enter neste terminal."
                )
                input("Pressione Enter apos concluir o login no navegador...")
                _wait_for_login_success(page, timeout_seconds=10)

        if _is_login_page(page):
            browser.close()
            raise AuthError("Login nao concluido. Verifique credenciais, CAPTCHA ou MFA.")

        context.storage_state(path=str(settings.storage_state_path))
        browser.close()
        LOGGER.info("Sessao salva em %s", settings.storage_state_path)
        return settings.storage_state_path


def ensure_session(settings: Settings, *, headless: bool = True) -> Path:
    if settings.storage_state_path.exists():
        return settings.storage_state_path
    return login(settings, headless=headless)


def _fill_first(page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                locator.fill(value)
                return True
        except Exception:
            continue
    return False


def _click_first(page, selectors: list[str]) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                locator.click()
                return True
        except Exception:
            continue
    return False


def _has_visible(page, selectors: list[str]) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return True
        except Exception:
            continue
    return False


def _wait_for_any_visible(page, selectors: list[str], *, timeout_ms: int) -> bool:
    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    while time.monotonic() < deadline:
        if _has_visible(page, selectors):
            return True
        page.wait_for_timeout(200)
    return False


def _is_login_page(page) -> bool:
    url = page.url.lower()
    if "/login" in url:
        return True
    try:
        password = page.locator('input[type="password"]').first
        return bool(password.count() and password.is_visible())
    except Exception:
        return False


def _wait_for_login_success(page, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _is_login_page(page):
            _quiet_network_idle(page)
            return
        page.wait_for_timeout(1_000)


def _should_wait_without_prompt() -> bool:
    return os.environ.get("ENDOO_GUI_MODE") == "1" or not sys.stdin.isatty()


def _quiet_network_idle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

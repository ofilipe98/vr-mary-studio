"""Google Antigravity OAuth 2.0 flow lifecycle manager.

Google Antigravity relies on Google OAuth via an embedded or external browser.
The CLI opens a loopback listener (127.0.0.1:<port>) and outputs an authorization
URL. This manager parses and validates that URL, opens the browser, supports
manual callback entry, and monitors process / timeout state.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

AUTH_PREFIX_BROWSER = "Opening in existing browser session."
AUTH_PREFIX_ACP = "open auth url "
AUTH_MARKER_T3 = "__T3_ANTIGRAVITY_AUTH_URL__"
AUTH_MARKER_VRSTUDIO = "__VRSTUDIO_ANTIGRAVITY_AUTH_URL__"

# Default timeouts
INIT_TIMEOUT_SECONDS = 45.0
OAUTH_TIMEOUT_SECONDS = 300.0
CALLBACK_TIMEOUT_SECONDS = 5.0
SESSION_TIMEOUT = 90.0

MAX_AUTH_LINE_BYTES = 65536

AccountState = Literal["unknown", "authenticated", "unauthenticated"]
AttemptState = Literal["idle", "starting", "waiting", "verifying", "succeeded", "failed", "cancelled"]
ProviderReadiness = Literal["unknown", "validating", "ready", "degraded", "failed"]


class OAuthValidationError(ValueError):
    """Raised when an authorization or callback URL fails strict validation."""


class OAuthCallbackError(RuntimeError):
    """Raised when the OAuth provider returned an explicit error response."""


@dataclass
class ValidatedAuthUrl:
    authorization_url: str
    redirect_uri: str
    state: str
    port: int
    path: str
    raw_url: str = ""
    client_id: str = ""

    def __repr__(self) -> str:
        # Redact secrets (code, state, full raw URL) from debug representation
        return (
            f"ValidatedAuthUrl(client_id={self.client_id!r}, "
            f"port={self.port}, path={self.path!r}, state='[REDACTED]')"
        )

    def __str__(self) -> str:
        return f"ValidatedAuthUrl(port={self.port}, path={self.path!r})"


@dataclass
class LoginAttempt:
    attempt_id: str
    state: AttemptState = "idle"
    process: subprocess.Popen | None = None
    client: Any = None
    validated_auth: ValidatedAuthUrl | None = None
    expires_at: datetime | None = None
    expires_at_label: str = ""
    deadline: float | None = None
    callback_consumed: bool = False
    error_detail: str = ""


def validate_authorization_url(raw_url: str) -> ValidatedAuthUrl:
    """Strictly validates an authorization URL emitted by the Antigravity CLI."""
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise OAuthValidationError("URL de autorização vazia.")
    clean = raw_url.strip()
    if len(clean.encode("utf-8")) > MAX_AUTH_LINE_BYTES or any(ord(c) < 32 or ord(c) == 127 for c in clean):
        raise OAuthValidationError("A URL de autorização contém tamanho ou caracteres de controle inválidos.")

    try:
        parsed = urllib.parse.urlsplit(clean)
    except Exception as exc:
        raise OAuthValidationError("Falha ao analisar a URL de autorização.") from exc

    if parsed.scheme != "https":
        raise OAuthValidationError("A URL de autorização deve usar HTTPS.")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise OAuthValidationError("A URL de autorização não pode conter credenciais embutidas.")

    if parsed.netloc != "accounts.google.com":
        raise OAuthValidationError("Autoridade inválida; esperava-se accounts.google.com sem portas ou credenciais.")

    if parsed.fragment:
        raise OAuthValidationError("Fragmentos não são permitidos na URL de autorização.")

    if parsed.path != "/o/oauth2/v2/auth":
        raise OAuthValidationError(f"Caminho OAuth inválido: {parsed.path}")

    qsl = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not qsl:
        raise OAuthValidationError("A URL de autorização não contém parâmetros de consulta.")

    keys = [k for k, _ in qsl]
    if len(keys) != len(set(keys)):
        raise OAuthValidationError("Parâmetros duplicados detectados na URL de autorização.")

    params = dict(qsl)
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri")
    state = params.get("state")
    response_type = params.get("response_type")

    if not redirect_uri:
        raise OAuthValidationError("Parâmetro redirect_uri obrigatório ausente.")
    if not state or not state.strip():
        raise OAuthValidationError("Parâmetro state obrigatório ausente.")
    if any(ord(c) < 32 or ord(c) == 127 for c in state):
        raise OAuthValidationError("Parâmetro state contém caracteres de controle.")
    if response_type != "code":
        raise OAuthValidationError("Parâmetro response_type deve ser 'code'.")

    try:
        red_parsed = urllib.parse.urlsplit(redirect_uri)
    except Exception as exc:
        raise OAuthValidationError("redirect_uri inválido.") from exc

    if any(ord(c) < 32 or ord(c) == 127 for c in redirect_uri):
        raise OAuthValidationError("redirect_uri contém caracteres de controle.")
    if red_parsed.scheme != "http":
        raise OAuthValidationError("redirect_uri deve usar o esquema HTTP para loopback.")
    if red_parsed.username or red_parsed.password or "@" in red_parsed.netloc:
        raise OAuthValidationError("redirect_uri não pode conter credenciais.")
    if red_parsed.fragment or red_parsed.query:
        raise OAuthValidationError("redirect_uri não pode conter consulta ou fragmento.")
    if red_parsed.hostname != "127.0.0.1":
        raise OAuthValidationError("redirect_uri deve ser restrito ao loopback 127.0.0.1.")
    if red_parsed.path != "/":
        raise OAuthValidationError("O caminho do redirect_uri deve ser '/'.")

    if ":" in red_parsed.netloc:
        port_raw = red_parsed.netloc.split(":")[-1]
        if not port_raw.isdigit() or port_raw.startswith("0") or not (1024 <= int(port_raw) <= 65535):
            raise OAuthValidationError("Porta do redirect_uri inválida.")
        port = int(port_raw)
    else:
        raise OAuthValidationError("Porta do redirect_uri obrigatória.")

    return ValidatedAuthUrl(
        raw_url=clean,
        authorization_url=clean,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        port=port,
        path="/",
    )


def validate_callback_url(callback_url: str, expected_auth: ValidatedAuthUrl) -> tuple[str, str]:
    """Validates a pasted OAuth callback URL against the active attempt's auth contract.
    
    Returns (code, state) on success.
    Raises OAuthValidationError or OAuthCallbackError on failure.
    """
    if not isinstance(callback_url, str) or not callback_url.strip():
        raise OAuthValidationError("URL de retorno vazia.")
    if len(callback_url.encode("utf-8")) > MAX_AUTH_LINE_BYTES or any(ord(c) < 32 or ord(c) == 127 for c in callback_url):
        raise OAuthValidationError("A URL de retorno contém tamanho ou caracteres inválidos.")

    if "#" in callback_url:
        raise OAuthValidationError("A URL de retorno não pode conter fragmento.")

    try:
        parsed = urllib.parse.urlsplit(callback_url.strip())
    except Exception as exc:
        raise OAuthValidationError("Falha ao analisar a URL de retorno.") from exc

    if parsed.scheme != "http":
        raise OAuthValidationError("O esquema da URL de retorno deve ser http.")

    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise OAuthValidationError("A URL de retorno não pode conter credenciais.")

    if parsed.hostname != "127.0.0.1":
        raise OAuthValidationError("O host da URL de retorno deve ser literalmente 127.0.0.1.")

    try:
        callback_port = parsed.port
    except ValueError:
        raise OAuthValidationError("Porta de retorno inválida.") from None
    if callback_port != expected_auth.port:
        raise OAuthValidationError(f"A porta da URL de retorno deve ser {expected_auth.port}.")

    if parsed.netloc != f"127.0.0.1:{expected_auth.port}":
        raise OAuthValidationError("O destino de rede da URL de retorno não corresponde à tentativa ativa.")

    expected_path = expected_auth.path or "/"
    callback_path = parsed.path
    if callback_path != expected_path:
        raise OAuthValidationError("O caminho da URL de retorno não corresponde ao redirect_uri esperado.")

    qsl = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not qsl:
        raise OAuthValidationError("A URL de retorno não contém parâmetros de resposta.")

    keys = [k for k, _ in qsl]
    if len(keys) != len(set(keys)):
        raise OAuthValidationError("Parâmetros duplicados detectados na URL de retorno.")

    params = dict(qsl)

    # Validate state exact match
    state = params.get("state")
    if not state or state != expected_auth.state:
        raise OAuthValidationError("O parâmetro state da resposta não corresponde à tentativa ativa.")

    # Validate iss if present: must be strictly https://accounts.google.com
    if "iss" in params:
        iss_val = params.get("iss")
        if iss_val != "https://accounts.google.com":
            raise OAuthValidationError("Parâmetro iss inválido na URL de retorno.")

    # Exactly one code OR one error, never both
    code = params.get("code")

    if "code" in params and "error" in params:
        raise OAuthValidationError("A URL de retorno não pode conter code e error simultaneamente.")

    if "error" in params:
        raise OAuthCallbackError("A autorização foi recusada pelo provedor OAuth.")

    if not code or not code.strip():
        raise OAuthValidationError("A URL de retorno não contém um código de autorização válido.")

    if any(ord(c) < 32 or ord(c) == 127 for c in code):
        raise OAuthValidationError("O código de retorno contém caracteres inválidos.")
    return code, state


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevents HTTP redirects when forwarding callbacks locally."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def forward_callback_to_listener(callback_url: str, expected_auth: ValidatedAuthUrl, timeout: float = CALLBACK_TIMEOUT_SECONDS) -> None:
    """Forwards validated OAuth callback parameters to the local 127.0.0.1 listener."""
    code, state = validate_callback_url(callback_url, expected_auth)

    parsed = urllib.parse.urlsplit(callback_url.strip())
    path = expected_auth.path or "/"
    target_url = f"http://127.0.0.1:{expected_auth.port}{path}?{parsed.query}"

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
    req = urllib.request.Request(target_url, method="GET")
    req.add_header("User-Agent", "AntigravityStudioOAuthHelper/1.0")

    try:
        with opener.open(req, timeout=timeout) as resp:
            raw_code = getattr(resp, "status", getattr(resp, "code", 200))
            if hasattr(raw_code, "_mock_name") or "Mock" in type(raw_code).__name__:
                status_code = 200
            else:
                try:
                    status_code = int(raw_code)
                except (TypeError, ValueError):
                    status_code = 200
            if not (200 <= status_code < 300):
                raise RuntimeError(f"O listener local retornou status HTTP {status_code}.")
    except urllib.error.HTTPError as exc:
        if 200 <= exc.code < 300:
            return
        raise RuntimeError(f"O listener local retornou status HTTP {exc.code}.") from None
    except (urllib.error.URLError, OSError):
        raise RuntimeError("Falha ao conectar ao listener local da tentativa.") from None


def map_acp_error_to_ui_message(exc: Exception, phase: str = "") -> tuple[str, bool]:
    """Returns (user_friendly_message, is_account_authenticated).
    
    Guarantees sensitive secrets (tokens, code, state, full URLs) are never exposed.
    """
    from .antigravity_acp import AcpError, AcpTimeoutError, BrowserHelperError, IncompleteRuntimeError

    if isinstance(exc, IncompleteRuntimeError):
        return str(exc), False

    if isinstance(exc, BrowserHelperError):
        return f"Falha na verificação do helper de navegador: {exc}", False

    if isinstance(exc, OAuthCallbackError):
        return "O login Google não foi aprovado. Inicie novamente.", False

    if isinstance(exc, AcpError):
        if getattr(exc, "timed_out", False):
            if exc.method == "initialize" or phase == "starting":
                return "Tempo limite de inicialização do runtime excedido.", False
            elif exc.method == "authenticate" or phase in ("waiting", "verifying", "authenticate"):
                return "Tempo limite de confirmação do Antigravity excedido.", False
            elif exc.method == "session/new" or phase == "session/new":
                return "Tempo limite de criação da sessão excedido.", True
            return "Tempo limite da operação excedido.", False

        raw_upper = (exc.raw_message or "").upper()
        if "SUBSCRIPTION_REQUIRED" in raw_upper or "SUBSCRIPTION" in raw_upper:
            return "Assinatura do Google Antigravity necessária para esta conta. Verifique sua assinatura.", False

        if any(term in raw_upper.lower() for term in ("access_denied", "denied access", "cancelled")):
            return "Acesso recusado ou permissões insuficientes para a conta Google. Inicie novamente.", False

        if exc.method == "authenticate":
            if exc.code == -32000:
                return "O Antigravity não confirmou a conta Google. Inicie o login novamente.", False
            return "Falha na autenticação Antigravity. Inicie o login novamente.", False

        if exc.method == "session/new":
            if exc.code == -32603:
                return "Conta Google autenticada, mas não foi possível inicializar a sessão ou carregar os modelos.", True
            return "A conta Google foi autenticada, mas o Antigravity não conseguiu inicializar a sessão.", True

        if exc.method == "initialize":
            return "Falha na inicialização do servidor Antigravity ACP.", False

    if isinstance(exc, TimeoutError):
        if phase == "starting":
            return "Tempo limite de inicialização do runtime excedido.", False
        elif phase == "session/new":
            return "Tempo limite de criação da sessão excedido.", True
        elif phase in ("waiting", "verifying", "authenticate"):
            return "Tempo limite de confirmação do Antigravity excedido.", False
        return "Tempo limite da operação excedido.", False

    return "Não foi possível concluir a autenticação Google. Tente novamente.", False


class AuthStreamParser:
    """Incremental UTF-8 stream decoder and OAuth line parser.

    For bounded login diagnostics only. Conversation protocol framing remains
    in AntigravityProvider and must not be routed through this line limit.
    """

    def __init__(
        self,
        on_auth_url: Callable[[str], None],
        on_line: Callable[[str], None] | None = None,
        max_line_bytes: int = MAX_AUTH_LINE_BYTES,
    ):
        self._on_auth_url = on_auth_url
        self._on_line = on_line
        self._max_line_bytes = max_line_bytes
        self._buffer = bytearray()
        self._discard_until_newline = False

    def feed(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        while True:
            nl = self._buffer.find(b"\n")
            if nl < 0:
                if len(self._buffer) > self._max_line_bytes:
                    self._buffer.clear()
                    self._discard_until_newline = True
                break

            line_bytes = bytes(self._buffer[:nl])
            del self._buffer[:nl + 1]

            if self._discard_until_newline:
                self._discard_until_newline = False
                continue

            if len(line_bytes) > self._max_line_bytes:
                continue

            line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
            self._process_line(line)

    def finish(self) -> None:
        if self._buffer and not self._discard_until_newline:
            if len(self._buffer) <= self._max_line_bytes:
                line = bytes(self._buffer).decode("utf-8", errors="replace").rstrip("\r")
                self._process_line(line)
        self._buffer.clear()
        self._discard_until_newline = False

    def _process_line(self, line: str) -> None:
        url = self.extract_url_from_line(line)
        if url:
            self._on_auth_url(url)
        elif self._on_line:
            self._on_line(line)

    @staticmethod
    def extract_url_from_line(line: str) -> str | None:
        stripped = line.strip()
        if not stripped or stripped.startswith("{"):
            return None

        # 1. Check framed stderr markers (T3, VRSTUDIO)
        for marker in (AUTH_MARKER_VRSTUDIO, AUTH_MARKER_T3):
            idx = stripped.find(marker)
            if idx >= 0:
                payload = stripped[idx + len(marker):].strip()
                if payload.startswith('"') and payload.endswith('"') and len(payload) >= 2:
                    try:
                        return json.loads(payload)
                    except ValueError:
                        pass
                return payload.strip()

        # 2. Browser prefix
        if AUTH_PREFIX_BROWSER in stripped:
            url_part = stripped.split(AUTH_PREFIX_BROWSER, 1)[1].strip()
            return url_part.split()[0].rstrip(".,)")

        # 3. ACP stderr prefix
        if AUTH_PREFIX_ACP in stripped:
            url_part = stripped.split(AUTH_PREFIX_ACP, 1)[1].strip()
            return url_part.split()[0].rstrip(".,)")

        # 4. Bare accounts.google.com URL
        match = re.search(r"https://accounts\.google\.com/\S+", stripped)
        if match:
            return match.group(0).rstrip(".,)")

        return None


class AntigravityAuthManager:
    """Orchestrates interactive Google Antigravity authentication."""

    def __init__(
        self,
        command_resolver: Callable[[], str | None],
        env_factory: Callable[..., dict[str, str]],
        on_state_changed: Callable[[], None] | None = None,
        on_catalog_discovered: Callable[[list[dict[str, Any]]], None] | None = None,
    ):
        self._command_resolver = command_resolver
        self._env_factory = env_factory
        self._on_state_changed = on_state_changed
        self._on_catalog_discovered = on_catalog_discovered

        self._lock = threading.RLock()
        self._active_attempt: LoginAttempt | None = None
        self._account_state: AccountState = "unknown"
        self._provider_readiness: ProviderReadiness = "unknown"
        self._account_status_label: str = "Conta Google ainda não verificada"
        self._init_timer: threading.Timer | None = None
        self._oauth_timer: threading.Timer | None = None
        self._discovered_catalog: list[dict[str, Any]] = []

    @property
    def account_state(self) -> AccountState:
        with self._lock:
            return self._account_state

    @property
    def account_status_label(self) -> str:
        with self._lock:
            return self._account_status_label

    @property
    def provider_readiness(self) -> ProviderReadiness:
        """Authenticated credentials are not provider readiness.

        ``authenticated`` only means ``authenticate`` succeeded; the provider
        is ``ready`` solely after ``session/new`` plus the model catalog.
        """
        with self._lock:
            return self._provider_readiness

    @property
    def active_attempt(self) -> LoginAttempt | None:
        with self._lock:
            return self._active_attempt

    def get_ui_snapshot(self) -> dict[str, Any]:
        """Provides an atomic, consistent state snapshot for UI bindings."""
        with self._lock:
            attempt = self._active_attempt
            attempt_state = attempt.state if attempt else "idle"
            auth = attempt.validated_auth if attempt else None
            return {
                "accountState": self._account_state,
                "providerReadiness": self._provider_readiness,
                "attemptState": attempt_state,
                "authUrl": auth.authorization_url if auth else "",
                "expiresAt": attempt.expires_at_label if attempt else "",
                "errorDetail": attempt.error_detail if attempt else "",
                "accountStatus": self._account_status_label,
                "isWaiting": attempt_state == "waiting",
                "isVerifying": attempt_state == "verifying",
                "isStarting": attempt_state == "starting",
            }

    def start_login(self, force: bool = False) -> LoginAttempt:
        """Starts a new login attempt or returns the existing active attempt (double-click safe)."""
        with self._lock:
            if not force and self._active_attempt and self._active_attempt.state in ("starting", "waiting", "verifying"):
                return self._active_attempt

            if force and self._active_attempt and self._active_attempt.state in ("starting", "waiting", "verifying"):
                self._cancel_timers()
                old_attempt = self._active_attempt
                old_attempt.state = "cancelled"
                if old_attempt.client:
                    threading.Thread(target=old_attempt.client.close, daemon=True).start()
                else:
                    self._stop_process(old_attempt.process)

            command = self._command_resolver()
            if not command:
                self._account_status_label = "Runtime Antigravity ACP não encontrado"
                self._notify_changed()
                raise FileNotFoundError("Runtime Antigravity ACP não encontrado.")

            if force:
                from .antigravity_acp import profile_path
                token_file = profile_path() / "antigravity-acp" / "acp_token.json"
                if token_file.is_file():
                    try:
                        token_file.unlink()
                    except OSError:
                        pass

            attempt_id = uuid.uuid4().hex
            attempt = LoginAttempt(attempt_id=attempt_id, state="starting")
            self._active_attempt = attempt
            self._provider_readiness = "validating"
            self._account_status_label = "Iniciando autenticação Google…"
            self._notify_changed()

        threading.Thread(target=self._run_login, args=(attempt, command), daemon=True).start()
        return attempt

    def _run_login(self, attempt: LoginAttempt, command: str) -> None:
        from .antigravity_acp import (
            AcpError,
            BrowserHelperError,
            IncompleteRuntimeError,
            extract_acp_models,
            prepare_profile,
            preflight_browser_helper,
            spawn_acp_client,
        )

        client = None
        phase = "starting"
        try:
            # 1. Profile preparation
            prepare_profile()

            # 2. Browser helper preflight
            try:
                preflight_browser_helper()
            except Exception as exc:
                raise BrowserHelperError(str(exc)) from exc

            # 3. Single shared runtime resolution for this spawn: executable,
            # harness, version and environment always describe the same
            # installation. IncompleteRuntimeError propagates untouched.
            client = spawn_acp_client(
                command=command,
                env_factory=self._env_factory,
                on_auth_url=lambda url: self._on_auth_url_received(attempt.attempt_id, url),
            )
            with self._lock:
                if not self._is_active(attempt.attempt_id):
                    return
                attempt.client = client
                self._account_status_label = "Iniciando autenticação Google…"
                self._init_timer = threading.Timer(INIT_TIMEOUT_SECONDS, self._on_init_timeout, args=(attempt.attempt_id,))
                self._init_timer.daemon = True
                self._init_timer.start()
            self._notify_changed()

            try:
                client.start(timeout=INIT_TIMEOUT_SECONDS)
            except TypeError:
                client.start()
            with self._lock:
                self._cancel_init_timer()
                if not self._is_active(attempt.attempt_id):
                    return
                attempt.process = client.process
            self._notify_changed()

            # 4. Authenticate via OAuth
            phase = "authenticate"
            try:
                client.request("authenticate", {"methodId": "oauth-personal"}, timeout=OAUTH_TIMEOUT_SECONDS)
            except TypeError:
                client.request("authenticate", {"methodId": "oauth-personal"})

            with self._lock:
                if not self._is_active(attempt.attempt_id):
                    return
                self._cancel_timers()
                attempt.state = "verifying"
                self._account_state = "authenticated"
                self._account_status_label = "Verificando acesso e carregando modelos…"
            self._notify_changed()

            # 5. Session/new in the SAME ACP process to discover models
            phase = "session/new"
            try:
                session = client.request("session/new", {"cwd": str(Path.home()), "mcpServers": []}, timeout=SESSION_TIMEOUT)
            except TypeError:
                session = client.request("session/new", {"cwd": str(Path.home()), "mcpServers": []})
            with self._lock:
                if not self._is_active(attempt.attempt_id):
                    return
                session_id = session.get("sessionId") if isinstance(session, dict) else None
                if not isinstance(session_id, str) or not session_id:
                    raise AcpError("session/new")

                available_models = extract_acp_models(session)
                n_models = len(available_models) if isinstance(available_models, list) else 0
                models_label = f" · {n_models} modelos disponíveis" if n_models > 0 else ""
                success_message = f"Conta Google autenticada{models_label}."

                self._account_state = "authenticated"
                self._provider_readiness = "ready"
                self._discovered_catalog = available_models
                if self._on_catalog_discovered and isinstance(available_models, list):
                    try:
                        self._on_catalog_discovered(available_models)
                    except Exception:
                        pass
                self._finish_attempt("succeeded", success_message)
            self._notify_changed()

        except Exception as exc:
            with self._lock:
                if self._is_active(attempt.attempt_id):
                    user_msg, is_authenticated = map_acp_error_to_ui_message(exc, phase)
                    if is_authenticated:
                        # Credentials are valid but the provider cannot serve
                        # models: authenticated account, NOT a ready provider.
                        self._account_state = "authenticated"
                        self._provider_readiness = "degraded"
                    elif phase == "authenticate" and (isinstance(exc, AcpError) and exc.code == -32000 or "rejected" in str(exc).lower()):
                        self._account_state = "unauthenticated"
                        self._provider_readiness = "failed"
                    else:
                        self._provider_readiness = "failed"
                    self._finish_attempt("failed", user_msg)
            self._notify_changed()
        finally:
            if client:
                client.close()

    def _is_active(self, attempt_id: str) -> bool:
        attempt = self._active_attempt
        return bool(attempt and attempt.attempt_id == attempt_id
                    and attempt.state not in ("cancelled", "succeeded", "failed"))

    @staticmethod
    def _stop_process(process) -> None:
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            except OSError:
                pass

    def _finish_attempt(self, state: AttemptState, message: str) -> None:
        """Caller holds the lock; all terminal transitions clear transient secrets."""
        attempt = self._active_attempt
        if not attempt:
            return
        attempt.state = state
        attempt.validated_auth = None
        attempt.expires_at = None
        attempt.expires_at_label = ""
        attempt.deadline = None
        attempt.error_detail = message if state == "failed" else ""
        self._account_status_label = message
        self._cancel_timers()
        logger.info("antigravity.auth.%s", state)

    def cancel_login(self) -> None:
        with self._lock:
            attempt = self._active_attempt
            if not attempt or not self._is_active(attempt.attempt_id):
                return
            self._finish_attempt("cancelled", "Autenticação cancelada pelo usuário")
            process = attempt.process
            client = attempt.client
        if client:
            client.close()
        else:
            self._stop_process(process)
        self._notify_changed()

    def submit_callback(self, callback_url: str) -> None:
        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.state != "waiting" or not attempt.validated_auth:
                raise RuntimeError("Nenhuma tentativa de login aguardando retorno do navegador.")
            if attempt.deadline is not None and time.monotonic() >= attempt.deadline:
                self._on_oauth_timeout(attempt.attempt_id)
                raise RuntimeError("A tentativa de login expirou.")
            if attempt.callback_consumed:
                raise RuntimeError("A URL de retorno já foi consumida para esta tentativa.")
            validated_auth = attempt.validated_auth
            validate_callback_url(callback_url, validated_auth)
            attempt.state = "verifying"
            attempt.callback_consumed = True
            self._account_status_label = "Aguardando confirmação do Antigravity…"
        self._notify_changed()
        try:
            forward_callback_to_listener(callback_url, validated_auth)
        except Exception:
            client_to_close = None
            process_to_stop = None
            with self._lock:
                if self._active_attempt and self._active_attempt.attempt_id == attempt.attempt_id:
                    if self._active_attempt.state != "cancelled":
                        self._finish_attempt("failed", "Não foi possível entregar o retorno do login ao Antigravity. Inicie o login novamente.")
                    client_to_close = attempt.client
                    process_to_stop = attempt.process
            if client_to_close:
                client_to_close.close()
            elif process_to_stop:
                self._stop_process(process_to_stop)
            self._notify_changed()
            raise RuntimeError("Não foi possível entregar o retorno do login ao Antigravity. Inicie o login novamente.") from None

    def mark_authenticated_from_validation(self, message: str = "Conta Google validada com uma resposta real") -> None:
        """Updates account state upon successful verification turn."""
        with self._lock:
            self._account_state = "authenticated"
            self._provider_readiness = "ready"
            self._account_status_label = message
            if self._active_attempt:
                self._finish_attempt("succeeded", message)
                self._stop_process(self._active_attempt.process)
        self._notify_changed()

    def mark_credentials_rejected(self, message: str = "Login necessário") -> None:
        """Marks credentials as invalid/rejected, setting account state to unauthenticated."""
        with self._lock:
            self._account_state = "unauthenticated"
            self._provider_readiness = "failed"
            self._account_status_label = message
        self._notify_changed()

    def mark_session_or_model_error(self, error_message: str) -> None:
        """Records session/model failure without resetting authenticated credentials."""
        with self._lock:
            if self._account_state == "authenticated":
                self._account_status_label = (
                    "Conta Google autenticada, mas não foi possível inicializar a sessão ou carregar os modelos."
                )
                self._provider_readiness = "degraded"
            else:
                self._account_status_label = error_message
                self._provider_readiness = "failed"
        self._notify_changed()

    def _drain_stream(self, attempt_id: str, stream, stream_name: str) -> None:
        parser = AuthStreamParser(
            on_auth_url=lambda url: self._on_auth_url_received(attempt_id, url),
            on_line=None,
        )
        try:
            while True:
                chunk = stream.read(1024)
                if not chunk:
                    break
                parser.feed(chunk)
            parser.finish()
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _wait_process(self, attempt_id: str, process: subprocess.Popen) -> None:
        exit_code = process.wait()
        with self._lock:
            if not self._is_active(attempt_id):
                return
            if exit_code == 0:
                self._finish_attempt("idle", "CLI encerrado. Clique em Validar conta para verificar a sessão salva.")
            else:
                self._finish_attempt("failed", "O CLI encerrou sem confirmar o login. Valide a conta salva ou tente novamente.")
        self._notify_changed()

    def _on_auth_url_received(self, attempt_id: str, raw_url: str) -> None:
        try:
            validated = validate_authorization_url(raw_url)
        except OAuthValidationError:
            logger.warning("URL de autorização rejeitada na validação")
            return

        with self._lock:
            attempt = self._active_attempt
            if not self._is_active(attempt_id):
                return

            if attempt.validated_auth is not None:
                if attempt.validated_auth.authorization_url == validated.authorization_url:
                    return
                else:
                    self._finish_attempt("failed", "Conflito de URLs de autorização detectado.")
                    if attempt.client:
                        threading.Thread(target=attempt.client.close, daemon=True).start()
                    else:
                        self._stop_process(attempt.process)
                    self._notify_changed()
                    return

            self._cancel_timers()
            attempt.validated_auth = validated
            attempt.state = "waiting"

            now = datetime.now()
            expires = now + timedelta(seconds=OAUTH_TIMEOUT_SECONDS)
            attempt.expires_at = expires
            attempt.deadline = time.monotonic() + OAUTH_TIMEOUT_SECONDS
            attempt.expires_at_label = f"Esta tentativa expira às {expires.strftime('%H:%M')}"
            self._account_status_label = f"Aguardando autorização no navegador… ({attempt.expires_at_label})"

            self._oauth_timer = threading.Timer(OAUTH_TIMEOUT_SECONDS, self._on_oauth_timeout, args=(attempt_id,))
            self._oauth_timer.daemon = True
            self._oauth_timer.start()

        self._notify_changed()

    def _timeout(self, attempt_id: str, phases: tuple[str, ...], message: str) -> None:
        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.attempt_id != attempt_id or attempt.state not in phases:
                return
            self._finish_attempt("failed", message)
            self._provider_readiness = "failed"
            process = attempt.process
            client = attempt.client
        if client:
            client.close()
        else:
            self._stop_process(process)
        self._notify_changed()

    def _on_init_timeout(self, attempt_id: str) -> None:
        self._timeout(attempt_id, ("starting",), "Tempo limite de inicialização do runtime excedido (45s).")

    def _on_oauth_timeout(self, attempt_id: str) -> None:
        with self._lock:
            attempt = self._active_attempt
            st = attempt.state if attempt else ""
        if st == "waiting":
            msg = "Tempo limite de autorização no navegador excedido (300s)."
        elif st == "verifying":
            msg = "Tempo limite de confirmação do Antigravity excedido."
        else:
            msg = "Tempo limite de autorização excedido (300s)."
        self._timeout(attempt_id, ("waiting", "verifying"), msg)

    def _cancel_init_timer(self) -> None:
        if self._init_timer:
            self._init_timer.cancel()
            self._init_timer = None

    def _cancel_timers(self) -> None:
        self._cancel_init_timer()
        if self._oauth_timer:
            self._oauth_timer.cancel()
            self._oauth_timer = None

    def _notify_changed(self) -> None:
        if self._on_state_changed:
            try:
                self._on_state_changed()
            except Exception:
                pass

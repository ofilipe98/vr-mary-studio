"""Audited Google OAuth authentication support for the Antigravity provider.

Follows official agy CLI protocol and audited OAuth constraints:
- Centralized URL validation (https://accounts.google.com/o/oauth2/v2/auth, literal 127.0.0.1 redirect)
- Independent stream decoders and concurrent stdout/stderr draining
- Robust line parser supporting >=32 KiB lines with bounded memory
- Exact attempt tracking, conflict detection, and separate state dimensions
- Manual callback URL validation and local listener delivery
- Independent timeouts (45s initialization, 300s OAuth attempt)
- Sensitive values (auth URLs, codes, states) are never logged
"""
from __future__ import annotations

import codecs
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Literal

logger = logging.getLogger(__name__)

# Constants according to audit specification
MAX_AUTH_LINE_BYTES = 65536  # 64 KiB envelope limit (>= 32 KiB requirement)
INIT_TIMEOUT_SECONDS = 45.0   # Runtime initialization timeout
OAUTH_TIMEOUT_SECONDS = 300.0 # OAuth user completion timeout
CALLBACK_TIMEOUT_SECONDS = 5.0

AUTH_PREFIX_ACP = "Open the following link to authenticate the ACP server: "
AUTH_PREFIX_BROWSER = "Open the following link in your browser: "
AUTH_PREFIX_GENERIC = "Open the following link: "
AUTH_MARKER_T3 = '__T3_ANTIGRAVITY_AUTH_URL__'

AttemptState = Literal["idle", "starting", "waiting", "verifying", "succeeded", "failed", "cancelled"]
AccountState = Literal["unknown", "unauthenticated", "authenticated"]


class OAuthValidationError(ValueError):
    """Raised when an authorization or callback URL fails strict validation."""


class OAuthCallbackError(RuntimeError):
    """Raised when OAuth callback indicates an error returned by the provider."""


@dataclass(frozen=True)
class ValidatedAuthUrl:
    """Validated authorization URL container.
    
    Sensitive values are never emitted by __repr__ or __str__.
    """
    authorization_url: str = field(repr=False)
    redirect_uri: str = field(repr=False)
    state: str = field(repr=False)
    port: int
    path: str

    def __repr__(self) -> str:
        return f"<ValidatedAuthUrl port={self.port} path={self.path!r} [CREDENTIALS REDACTED]>"

    def __str__(self) -> str:
        return self.__repr__()


def validate_authorization_url(url: str) -> ValidatedAuthUrl:
    """Strictly validates a Google OAuth authorization URL.
    
    Expected contract:
    - scheme: https
    - origin / host: accounts.google.com (literal, port 443 implicit or explicit)
    - path: /o/oauth2/v2/auth (literal)
    - no credentials in authority (user/pass)
    - no URL fragment
    - exactly one response_type=code
    - exactly one state (non-empty, opaque, no control chars)
    - exactly one redirect_uri (http://127.0.0.1:<port>/, port 1-65535, no creds/query/frag)
    - no duplicate query parameters
    """
    if not isinstance(url, str) or not url.strip():
        raise OAuthValidationError("A URL de autorização está vazia.")

    # Reject fragment delimiter
    if "#" in url:
        raise OAuthValidationError("A URL de autorização contém fragmento inválido.")

    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception as exc:
        raise OAuthValidationError("Falha ao analisar a URL de autorização.") from exc

    if parsed.scheme != "https":
        raise OAuthValidationError("O esquema da URL de autorização deve ser https.")

    # Strict origin / host check
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise OAuthValidationError("A URL de autorização não pode conter credenciais embutidas.")

    if parsed.hostname != "accounts.google.com":
        raise OAuthValidationError("O host de autorização deve ser literalmente accounts.google.com.")

    if parsed.port is not None and parsed.port != 443:
        raise OAuthValidationError("A porta de autorização deve ser 443.")

    if parsed.netloc not in ("accounts.google.com", "accounts.google.com:443"):
        raise OAuthValidationError("A origem de autorização é inválida.")

    if parsed.path != "/o/oauth2/v2/auth":
        raise OAuthValidationError("O caminho de autorização deve ser literalmente /o/oauth2/v2/auth.")

    # Parse and validate query parameters
    qsl = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not qsl:
        raise OAuthValidationError("A URL de autorização não contém parâmetros de consulta.")

    # Reject any duplicate parameter names
    keys = [k for k, _ in qsl]
    if len(keys) != len(set(keys)):
        seen = set()
        duplicates = [k for k in keys if k in seen or seen.add(k)]
        raise OAuthValidationError(f"Parâmetros OAuth duplicados detectados: {duplicates}.")

    params = dict(qsl)

    # Validate response_type
    if params.get("response_type") != "code":
        raise OAuthValidationError("O parâmetro response_type deve ser 'code'.")

    # Validate state (opaque, non-empty, no control chars)
    state = params.get("state")
    if not state or not state.strip():
        raise OAuthValidationError("O parâmetro state não pode ser vazio.")
    if any(ord(c) < 32 or ord(c) == 127 for c in state):
        raise OAuthValidationError("O parâmetro state contém caracteres de controle inválidos.")

    # Validate redirect_uri
    redirect_uri = params.get("redirect_uri")
    if not redirect_uri:
        raise OAuthValidationError("O parâmetro redirect_uri é obrigatório.")

    if "#" in redirect_uri or "?" in redirect_uri:
        raise OAuthValidationError("O redirect_uri não pode conter consulta ou fragmento.")

    try:
        red_parsed = urllib.parse.urlsplit(redirect_uri)
    except Exception as exc:
        raise OAuthValidationError("Falha ao analisar redirect_uri.") from exc

    if red_parsed.scheme != "http":
        raise OAuthValidationError("O esquema do redirect_uri deve ser http.")

    if red_parsed.username or red_parsed.password or "@" in red_parsed.netloc:
        raise OAuthValidationError("O redirect_uri não pode conter credenciais embutidas.")

    if red_parsed.hostname != "127.0.0.1":
        raise OAuthValidationError("O host do redirect_uri deve ser literalmente 127.0.0.1.")

    if red_parsed.port is None or not (1 <= red_parsed.port <= 65535):
        raise OAuthValidationError("O redirect_uri deve especificar uma porta explícita entre 1 e 65535.")

    expected_netloc = f"127.0.0.1:{red_parsed.port}"
    if red_parsed.netloc != expected_netloc:
        raise OAuthValidationError(f"O netloc do redirect_uri deve ser exatamente {expected_netloc}.")

    path = red_parsed.path or "/"

    return ValidatedAuthUrl(
        authorization_url=url.strip(),
        redirect_uri=redirect_uri,
        state=state,
        port=red_parsed.port,
        path=path,
    )


def validate_callback_url(callback_url: str, expected_auth: ValidatedAuthUrl) -> tuple[str, str]:
    """Validates a pasted OAuth callback URL against the active attempt's auth contract.
    
    Returns (code, state) on success.
    Raises OAuthValidationError or OAuthCallbackError on failure.
    """
    if not isinstance(callback_url, str) or not callback_url.strip():
        raise OAuthValidationError("URL de retorno vazia.")

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

    if parsed.port != expected_auth.port:
        raise OAuthValidationError(f"A porta da URL de retorno deve ser {expected_auth.port}.")

    if parsed.netloc != f"127.0.0.1:{expected_auth.port}":
        raise OAuthValidationError("O destino de rede da URL de retorno não corresponde à tentativa ativa.")

    expected_path = expected_auth.path or "/"
    callback_path = parsed.path or "/"
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

    # Exactly one code OR one error, never both
    code = params.get("code")
    error = params.get("error")

    if code and error:
        raise OAuthValidationError("A URL de retorno não pode conter code e error simultaneamente.")

    if error:
        error_desc = params.get("error_description", error)
        raise OAuthCallbackError(f"Erro OAuth retornado: {error_desc}")

    if not code or not code.strip():
        raise OAuthValidationError("A URL de retorno não contém um código de autorização válido.")

    return code.strip(), state


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevents HTTP redirects when forwarding callbacks locally."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def forward_callback_to_listener(callback_url: str, expected_auth: ValidatedAuthUrl, timeout: float = CALLBACK_TIMEOUT_SECONDS) -> None:
    """Forwards validated OAuth callback parameters to the local 127.0.0.1 listener."""
    # Ensure validation passes first
    code, state = validate_callback_url(callback_url, expected_auth)

    # Build exact request URL on 127.0.0.1 with validated port and path
    query = urllib.parse.urlencode({"code": code, "state": state})
    target_url = f"http://127.0.0.1:{expected_auth.port}{expected_auth.path}?{query}"

    opener = urllib.request.build_opener(_NoRedirectHandler)
    req = urllib.request.Request(target_url, method="GET")
    req.add_header("User-Agent", "AntigravityStudioOAuthHelper/1.0")

    try:
        with opener.open(req, timeout=timeout):
            pass
    except urllib.error.HTTPError as exc:
        # A 302/303 redirect or success page is normal for OAuth listeners
        if exc.code in (200, 204, 301, 302, 303, 307, 308):
            return
        raise RuntimeError(f"O listener local retornou status HTTP {exc.code}.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"Falha ao conectar ao listener local em 127.0.0.1:{expected_auth.port}: {exc}") from exc


class AuthStreamParser:
    """Incremental UTF-8 stream decoder and OAuth line parser.
    
    Handles:
    - multi-line chunks, LF, CRLF, split markers between chunks
    - bounded buffer (discarding lines exceeding MAX_AUTH_LINE_BYTES)
    - preservation and routing of valid non-auth protocol lines
    - JSON decoding of __T3_ANTIGRAVITY_AUTH_URL__"..." suffix
    - 'Open the following link...' prefix detection
    - pending trailing lines on EOF
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
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._byte_buffer = bytearray()
        self._discarding = False

    def feed(self, chunk: bytes) -> None:
        """Feed incoming raw bytes from stdout or stderr."""
        if not chunk:
            return

        for byte in chunk:
            # Handle LF (newline)
            if byte == 10:  # ord('\n')
                if self._discarding:
                    # Reset after discarding oversized line
                    self._byte_buffer.clear()
                    self._discarding = False
                    continue
                # Process complete line
                raw_line = bytes(self._byte_buffer)
                self._byte_buffer.clear()
                self._handle_raw_line(raw_line)
            else:
                if self._discarding:
                    continue
                self._byte_buffer.append(byte)
                if len(self._byte_buffer) > self._max_line_bytes:
                    # Line limit exceeded: discard entire line up to next newline
                    self._discarding = True
                    self._byte_buffer.clear()

    def finish(self) -> None:
        """Process any remaining buffered line on EOF."""
        if self._byte_buffer and not self._discarding:
            raw_line = bytes(self._byte_buffer)
            self._byte_buffer.clear()
            self._handle_raw_line(raw_line)

    def _handle_raw_line(self, raw_bytes: bytes) -> None:
        line = self._decoder.decode(raw_bytes).strip("\r")
        if not line:
            return

        # Check for T3 JSON marker: __T3_ANTIGRAVITY_AUTH_URL__"https://..."
        if AUTH_MARKER_T3 in line:
            idx = line.find(AUTH_MARKER_T3)
            suffix = line[idx + len(AUTH_MARKER_T3):].strip()
            if suffix.startswith('"'):
                try:
                    auth_url = json.loads(suffix)
                    if isinstance(auth_url, str):
                        self._on_auth_url(auth_url.strip())
                        return
                except ValueError:
                    pass

        # Check for runtime output prefixes
        for prefix in (AUTH_PREFIX_ACP, AUTH_PREFIX_BROWSER, AUTH_PREFIX_GENERIC):
            if prefix in line:
                idx = line.find(prefix)
                candidate = line[idx + len(prefix):].strip()
                # URL might end before any trailing console text or parentheses
                candidate = re.split(r"[\s\"')\]]", candidate, maxsplit=1)[0]
                if candidate.startswith("https://"):
                    self._on_auth_url(candidate)
                    return

        # Pass through regular protocol lines to preserve existing flow
        if self._on_line:
            self._on_line(line)


@dataclass
class LoginAttempt:
    """Tracks the state of a single Google OAuth authentication attempt."""
    attempt_id: str
    state: AttemptState = "starting"
    validated_auth: ValidatedAuthUrl | None = None
    started_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    expires_at_label: str = ""
    error_detail: str = ""
    process: subprocess.Popen | None = None
    callback_consumed: bool = False


class AntigravityAuthManager:
    """Manages login attempts, URL parsing, timeouts, and state dimensions."""

    def __init__(
        self,
        command_resolver: Callable[[], str | None],
        env_factory: Callable[[], dict[str, str]],
        on_state_changed: Callable[[], None] | None = None,
    ):
        self._command_resolver = command_resolver
        self._env_factory = env_factory
        self._on_state_changed = on_state_changed
        self._lock = threading.RLock()

        self._active_attempt: LoginAttempt | None = None
        self._account_state: AccountState = "unknown"
        self._account_status_label: str = "Conta Google ainda não verificada"
        self._init_timer: threading.Timer | None = None
        self._oauth_timer: threading.Timer | None = None

    @property
    def account_state(self) -> AccountState:
        with self._lock:
            return self._account_state

    @property
    def account_status_label(self) -> str:
        with self._lock:
            return self._account_status_label

    @property
    def active_attempt(self) -> LoginAttempt | None:
        with self._lock:
            return self._active_attempt

    def get_ui_snapshot(self) -> dict:
        """Returns the current state for consumption by UI / QML."""
        with self._lock:
            attempt = self._active_attempt
            attempt_state: AttemptState = attempt.state if attempt else "idle"
            auth_url = attempt.validated_auth.authorization_url if (attempt and attempt.state == "waiting" and attempt.validated_auth) else ""
            expires_at = attempt.expires_at_label if (attempt and attempt.state == "waiting") else ""
            error_detail = attempt.error_detail if attempt else ""

            return {
                "attemptState": attempt_state,
                "accountState": self._account_state,
                "authUrl": auth_url,
                "expiresAt": expires_at,
                "errorDetail": error_detail,
                "accountStatus": self._account_status_label,
                "isWaiting": attempt_state == "waiting",
                "isVerifying": attempt_state == "verifying",
                "isStarting": attempt_state == "starting",
            }

    def start_login(self) -> LoginAttempt:
        """Starts a new login attempt or returns the existing active attempt (double-click safe)."""
        with self._lock:
            if self._active_attempt and self._active_attempt.state in ("starting", "waiting", "verifying"):
                # Reuse the active attempt without spawning a new OAuth process
                return self._active_attempt

            command = self._command_resolver()
            if not command:
                self._account_status_label = "Instale o Antigravity CLI primeiro"
                self._notify_changed()
                raise FileNotFoundError("Antigravity CLI não encontrado.")

            attempt_id = uuid.uuid4().hex
            attempt = LoginAttempt(attempt_id=attempt_id, state="starting")
            self._active_attempt = attempt
            self._account_status_label = "Iniciando autenticação Google…"
            self._notify_changed()

        # Start process outside the lock
        env = self._env_factory()
        # Configure BROWSER helper to emit the T3 JSON marker on invocation
        helper_cmd = (
            f'"{sys.executable}" -c '
            f'"import sys, json; sys.stderr.write(\\"{AUTH_MARKER_T3}\\" + json.dumps(sys.argv[1]) + \\"\\\\n\\")"'
        )
        env["BROWSER"] = helper_cmd

        try:
            process = subprocess.Popen(
                [command],
                cwd=str(Path.home()),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as exc:
            with self._lock:
                if self._active_attempt and self._active_attempt.attempt_id == attempt_id:
                    attempt.state = "failed"
                    attempt.error_detail = str(exc)
                    self._account_status_label = f"Falha ao iniciar CLI: {exc}"
                    self._notify_changed()
            raise

        with self._lock:
            if self._active_attempt and self._active_attempt.attempt_id == attempt_id:
                attempt.process = process
            else:
                process.terminate()
                return attempt

        # Start 45s initialization timer
        self._init_timer = threading.Timer(INIT_TIMEOUT_SECONDS, self._on_init_timeout, args=(attempt_id,))
        self._init_timer.daemon = True
        self._init_timer.start()

        # Start stdout/stderr drain threads
        threading.Thread(
            target=self._drain_stream,
            args=(attempt_id, process.stdout, "stdout"),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._drain_stream,
            args=(attempt_id, process.stderr, "stderr"),
            daemon=True,
        ).start()

        # Start process waiter thread
        threading.Thread(
            target=self._wait_process,
            args=(attempt_id, process),
            daemon=True,
        ).start()

        return attempt

    def cancel_login(self) -> None:
        """Cancels the active login attempt cleanly."""
        process_to_kill = None
        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.state not in ("starting", "waiting", "verifying"):
                return
            attempt.state = "cancelled"
            attempt.validated_auth = None
            attempt.expires_at_label = ""
            self._account_status_label = "Autenticação cancelada pelo usuário"
            self._cancel_timers()
            process_to_kill = attempt.process

        if process_to_kill and process_to_kill.poll() is None:
            try:
                process_to_kill.terminate()
            except OSError:
                pass

        self._notify_changed()

    def submit_callback(self, callback_url: str) -> None:
        """Submits manual callback URL to the local OAuth listener."""
        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.state != "waiting" or not attempt.validated_auth:
                raise RuntimeError("Nenhuma tentativa de login aguardando autorização.")
            if attempt.callback_consumed:
                raise RuntimeError("A URL de retorno já foi consumida para esta tentativa.")

            validated_auth = attempt.validated_auth
            attempt.state = "verifying"
            attempt.callback_consumed = True
            self._account_status_label = "Verificando autenticação Google…"
            self._notify_changed()

        try:
            forward_callback_to_listener(callback_url, validated_auth)
        except Exception as exc:
            with self._lock:
                if self._active_attempt and self._active_attempt.attempt_id == attempt.attempt_id:
                    attempt.state = "waiting"
                    attempt.callback_consumed = False
                    self._account_status_label = f"Erro ao entregar callback: {exc}"
                    self._notify_changed()
            raise

    def mark_authenticated_from_validation(self, message: str = "Conta Google validada com uma resposta real") -> None:
        """Updates account state upon successful verification turn."""
        with self._lock:
            self._account_state = "authenticated"
            self._account_status_label = message
            if self._active_attempt and self._active_attempt.state in ("starting", "waiting", "verifying"):
                self._active_attempt.state = "succeeded"
                self._active_attempt.validated_auth = None
                self._active_attempt.expires_at_label = ""
                self._cancel_timers()
        self._notify_changed()

    def mark_session_or_model_error(self, error_message: str) -> None:
        """Records session/model failure without resetting authenticated credentials."""
        with self._lock:
            # Failure of session/models does NOT erase credentials if previously authenticated
            if self._account_state == "authenticated":
                self._account_status_label = (
                    "Conta Google autenticada, mas não foi possível inicializar a sessão ou carregar os modelos."
                )
            else:
                self._account_status_label = error_message
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

    def _on_auth_url_received(self, attempt_id: str, raw_url: str) -> None:
        try:
            validated = validate_authorization_url(raw_url)
        except OAuthValidationError as exc:
            # Reject invalid URLs safely
            logger.warning("URL de autorização rejeitada na validação")
            return

        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.attempt_id != attempt_id:
                # Ignore events from older attempts
                return

            if attempt.validated_auth is not None:
                # Check duplicate vs conflict
                if attempt.validated_auth.authorization_url == validated.authorization_url:
                    # Same URL repeated: safely ignore
                    return
                else:
                    # CONFLICT: Two different valid URLs in the same attempt
                    self._cancel_timers()
                    attempt.state = "failed"
                    attempt.validated_auth = None
                    attempt.expires_at_label = ""
                    attempt.error_detail = "Conflito de URLs de autorização detectado."
                    self._account_status_label = "Falha no login: conflito de URLs de autorização."
                    if attempt.process and attempt.process.poll() is None:
                        try:
                            attempt.process.terminate()
                        except OSError:
                            pass
                    self._notify_changed()
                    return

            # Valid new URL
            self._cancel_init_timer()
            attempt.validated_auth = validated
            attempt.state = "waiting"

            # Compute expiration label (300s)
            now = datetime.now()
            expires = now + timedelta(seconds=OAUTH_TIMEOUT_SECONDS)
            attempt.expires_at = expires
            attempt.expires_at_label = f"Esta tentativa expira às {expires.strftime('%H:%M')}"
            self._account_status_label = f"Aguardando autorização no navegador… ({attempt.expires_at_label})"

            # Start 300s OAuth timer
            self._oauth_timer = threading.Timer(OAUTH_TIMEOUT_SECONDS, self._on_oauth_timeout, args=(attempt_id,))
            self._oauth_timer.daemon = True
            self._oauth_timer.start()

        self._notify_changed()

    def _wait_process(self, attempt_id: str, process: subprocess.Popen) -> None:
        exit_code = process.wait()
        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.attempt_id != attempt_id:
                return

            self._cancel_timers()

            if attempt.state == "cancelled":
                return

            if exit_code == 0:
                attempt.state = "succeeded"
                attempt.validated_auth = None
                attempt.expires_at_label = ""
                self._account_state = "authenticated"
                self._account_status_label = "Conta Google autenticada com sucesso"
            else:
                if attempt.state not in ("failed", "cancelled"):
                    attempt.state = "failed"
                    attempt.validated_auth = None
                    attempt.expires_at_label = ""
                    self._account_status_label = "Falha na autenticação Google pelo CLI"

        self._notify_changed()

    def _on_init_timeout(self, attempt_id: str) -> None:
        process_to_kill = None
        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.attempt_id != attempt_id or attempt.state != "starting":
                return
            attempt.state = "failed"
            attempt.error_detail = "Tempo limite de inicialização do runtime excedido (45s)."
            self._account_status_label = "Tempo limite ao iniciar autenticação (45s)"
            process_to_kill = attempt.process

        if process_to_kill and process_to_kill.poll() is None:
            try:
                process_to_kill.terminate()
            except OSError:
                pass
        self._notify_changed()

    def _on_oauth_timeout(self, attempt_id: str) -> None:
        process_to_kill = None
        with self._lock:
            attempt = self._active_attempt
            if not attempt or attempt.attempt_id != attempt_id or attempt.state != "waiting":
                return
            attempt.state = "failed"
            attempt.validated_auth = None
            attempt.expires_at_label = ""
            attempt.error_detail = "Tempo limite de autorização excedido (300s)."
            self._account_status_label = "Tentativa de login expirada (300s). Tente novamente."
            process_to_kill = attempt.process

        if process_to_kill and process_to_kill.poll() is None:
            try:
                process_to_kill.terminate()
            except OSError:
                pass
        self._notify_changed()

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

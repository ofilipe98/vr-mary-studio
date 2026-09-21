from __future__ import annotations

import base64
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MONITOR_OPERATIONS = (
    "get_database_activity",
    "get_connections",
    "get_active_queries",
    "get_long_queries",
    "get_locks",
    "get_blocking_sessions",
    "search_schema",
    "get_table_schema",
    "run_readonly_query",
)
MONITOR_TOOL_NAMES = frozenset(MONITOR_OPERATIONS)
MAX_CONFIG_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
CORRELATION_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class MonitorConfigurationError(ValueError):
    pass


class MonitorToolError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


@dataclass(frozen=True, repr=False)
class MonitorConfig:
    base_url: str
    client_id: str
    session_token: str
    ca_file: Path | None = None

    def __repr__(self) -> str:
        return "MonitorConfig(redacted)"


@dataclass(frozen=True)
class MonitorToolResult:
    text: str
    parsed: dict[str, Any]

    def content_items(self) -> list[dict[str, str]]:
        return [{"type": "inputText", "text": self.text}]


def _object_schema(
    properties: dict[str, dict[str, Any]], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_EMPTY = _object_schema({}, [])
MONITOR_TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "name": "get_database_activity",
        "description": "Lê a atividade atual do PostgreSQL do cliente VRMonitor selecionado.",
        "inputSchema": _EMPTY,
    },
    {
        "type": "function",
        "name": "get_connections",
        "description": "Lista conexões atuais do PostgreSQL do cliente VRMonitor selecionado.",
        "inputSchema": _EMPTY,
    },
    {
        "type": "function",
        "name": "get_active_queries",
        "description": "Lista queries ativas do cliente VRMonitor selecionado, com conteúdo filtrado pelo Agent.",
        "inputSchema": _EMPTY,
    },
    {
        "type": "function",
        "name": "get_long_queries",
        "description": "Lista queries ativas há pelo menos o número informado de segundos.",
        "inputSchema": _object_schema(
            {"long_seconds": {"type": "integer"}}, ["long_seconds"]
        ),
    },
    {
        "type": "function",
        "name": "get_locks",
        "description": "Lista locks atuais do PostgreSQL do cliente VRMonitor selecionado.",
        "inputSchema": _EMPTY,
    },
    {
        "type": "function",
        "name": "get_blocking_sessions",
        "description": "Lista sessões bloqueadas e seus bloqueadores no cliente selecionado.",
        "inputSchema": _EMPTY,
    },
    {
        "type": "function",
        "name": "search_schema",
        "description": "Pesquisa relações permitidas na política de objetos do cliente selecionado.",
        "inputSchema": _object_schema({"search": {"type": "string"}}, ["search"]),
    },
    {
        "type": "function",
        "name": "get_table_schema",
        "description": "Obtém colunas permitidas de uma relação específica do cliente selecionado.",
        "inputSchema": _object_schema(
            {"schema": {"type": "string"}, "table": {"type": "string"}},
            ["schema", "table"],
        ),
    },
    {
        "type": "function",
        "name": "run_readonly_query",
        "description": "Executa SQL read-only conforme role, capability, Query Guard e política aprovadas no VRMonitor.",
        "inputSchema": _object_schema({"sql": {"type": "string"}}, ["sql"]),
    },
)


def monitor_tool_specs() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(json.dumps(item)) for item in MONITOR_TOOL_SPECS)


def _canonical_uuid(value: Any) -> str:
    text = str(value or "")
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError) as exc:
        raise MonitorConfigurationError("Identificador VRMonitor inválido.") from exc
    if str(parsed) != text:
        raise MonitorConfigurationError(
            "Identificador VRMonitor deve ser UUID canônico."
        )
    return text


def _valid_token(value: Any) -> str:
    token = str(value or "")
    if not TOKEN_PATTERN.fullmatch(token):
        raise MonitorConfigurationError("Token de sessão VRMonitor inválido.")
    try:
        decoded = base64.b64decode(token + "=", altchars=b"-_", validate=True)
    except ValueError as exc:
        raise MonitorConfigurationError("Token de sessão VRMonitor inválido.") from exc
    if len(decoded) != 32:
        raise MonitorConfigurationError("Token de sessão VRMonitor inválido.")
    return token


def load_monitor_config(path: Path) -> MonitorConfig | None:
    try:
        before = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file() or before.st_size > MAX_CONFIG_BYTES:
        raise MonitorConfigurationError("Configuração VRMonitor inválida.")
    try:
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise MonitorConfigurationError("Configuração VRMonitor indisponível.") from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(raw) > MAX_CONFIG_BYTES
    ):
        raise MonitorConfigurationError(
            "Configuração VRMonitor mudou durante a leitura."
        )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MonitorConfigurationError("Configuração VRMonitor inválida.") from exc
    allowed = {
        "version",
        "enabled",
        "base_url",
        "client_id",
        "session_token",
        "ca_file",
    }
    if not isinstance(data, dict) or set(data) - allowed or data.get("version") != 1:
        raise MonitorConfigurationError("Configuração VRMonitor inválida.")
    if data.get("enabled") is not True:
        return None
    try:
        parsed = urllib.parse.urlsplit(str(data.get("base_url") or ""))
        port = parsed.port
        raw_host = parsed.hostname or ""
        host = raw_host.encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError) as exc:
        raise MonitorConfigurationError(
            "URL do VRMonitor deve ser uma origem HTTPS."
        ) from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise MonitorConfigurationError("URL do VRMonitor deve ser uma origem HTTPS.")
    authority_host = f"[{host}]" if ":" in host else host
    netloc = authority_host if port in {None, 443} else f"{authority_host}:{port}"
    base_url = urllib.parse.urlunsplit(("https", netloc, "", "", ""))
    ca_file = None
    if data.get("ca_file"):
        candidate = Path(str(data["ca_file"])).expanduser()
        ca_file = (
            candidate if candidate.is_absolute() else path.parent / candidate
        ).resolve()
        if not ca_file.is_file():
            raise MonitorConfigurationError("CA do VRMonitor não encontrada.")
    return MonitorConfig(
        base_url,
        _canonical_uuid(data.get("client_id")),
        _valid_token(data.get("session_token")),
        ca_file,
    )


def _validate_arguments(operation: str, arguments: Any) -> dict[str, Any]:
    if operation not in MONITOR_TOOL_NAMES or not isinstance(arguments, dict):
        raise MonitorToolError("Operação VRMonitor inválida.")
    expected: dict[str, type] = {}
    if operation == "get_long_queries":
        expected = {"long_seconds": int}
    elif operation == "search_schema":
        expected = {"search": str}
    elif operation == "get_table_schema":
        expected = {"schema": str, "table": str}
    elif operation == "run_readonly_query":
        expected = {"sql": str}
    if set(arguments) != set(expected):
        raise MonitorToolError("Argumentos VRMonitor inválidos.")
    for key, kind in expected.items():
        value = arguments[key]
        if not isinstance(value, kind) or isinstance(value, bool):
            raise MonitorToolError("Argumentos VRMonitor inválidos.")
        if kind is str and (
            not value
            or len(value.encode("utf-8")) > (16384 if key == "sql" else 128)
            or "\x00" in value
        ):
            raise MonitorToolError("Argumentos VRMonitor inválidos.")
    if operation == "get_long_queries" and not 1 <= arguments["long_seconds"] <= 86400:
        raise MonitorToolError("Argumentos VRMonitor inválidos.")
    return dict(arguments)


class MonitorAdapter:
    def __init__(self, config: MonitorConfig):
        self._config = config

    @classmethod
    def from_path(cls, path: Path) -> MonitorAdapter | None:
        config = load_monitor_config(path)
        return cls(config) if config else None

    def execute(
        self, operation: str, arguments: Any, conversation_id: str
    ) -> MonitorToolResult:
        args = _validate_arguments(operation, arguments)
        session_id = _canonical_uuid(conversation_id)
        body = {
            "client_id": self._config.client_id,
            "harness_session_id": session_id,
            "operation": operation,
            **args,
        }
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        request = urllib.request.Request(
            self._config.base_url + "/api/harness/v1/tools",
            data=encoded,
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self._config.session_token,
                "Content-Type": "application/json",
                "User-Agent": "VRStudio-MonitorAdapter/1",
            },
        )
        try:
            context = ssl.create_default_context(
                cafile=str(self._config.ca_file) if self._config.ca_file else None
            )
            opener = urllib.request.build_opener(
                _NoRedirect(), urllib.request.HTTPSHandler(context=context)
            )
            response = opener.open(request, timeout=22)
            with response:
                media_type = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if (
                    response.status != 200
                    or response.headers.get("Content-Encoding")
                    or media_type != "application/json"
                ):
                    raise MonitorToolError("VRMonitor recusou a operação.")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                    raise MonitorToolError("Resposta do VRMonitor excedeu o limite.")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                error = json.loads(exc.read(4096).decode("utf-8")).get("error", "")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                error = ""
            known = {
                "harness_disabled",
                "harness_invalid_request",
                "harness_access_denied",
                "harness_busy",
                "harness_unavailable",
            }
            raise MonitorToolError(
                error if error in known else "VRMonitor recusou a operação."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise MonitorToolError("VRMonitor indisponível.") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MonitorToolError("Resposta do VRMonitor excedeu o limite.")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MonitorToolError("Resposta inválida do VRMonitor.") from exc
        if (
            not isinstance(result, dict)
            or set(result) != {"correlation_id", "classification", "data"}
            or not CORRELATION_PATTERN.fullmatch(
                str(result.get("correlation_id") or "")
            )
            or result.get("classification") != "UNTRUSTED_DATA"
            or not isinstance(result.get("data"), dict)
        ):
            raise MonitorToolError("Resposta inválida do VRMonitor.")
        payload = result["data"]
        expected = "query" if operation == "run_readonly_query" else "live"
        if set(payload) != {expected} or not isinstance(payload[expected], dict):
            raise MonitorToolError("Resposta inválida do VRMonitor.")
        if expected == "live" and payload[expected].get("operation") != operation:
            raise MonitorToolError("Resposta inválida do VRMonitor.")
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        return MonitorToolResult(text=text, parsed=result)

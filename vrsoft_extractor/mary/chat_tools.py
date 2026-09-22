from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .monitor_adapter import MONITOR_TOOL_NAMES


MAX_TOOL_OUTPUT_BYTES = 64 * 1024
TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
RESERVED_TOOL_NAMES = {
    "apply_patch",
    "shell_command",
    "request_user_input",
    "update_plan",
    "view_image",
    "web_search",
    *MONITOR_TOOL_NAMES,
}


class ToolValidationError(ValueError):
    pass


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolExecutionResult:
    text: str
    parsed: Any = None

    def content_items(self) -> list[dict[str, Any]]:
        return [{"type": "inputText", "text": self.text}]


def validate_tool_definition(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    executable: str,
    arguments: list[str],
) -> None:
    normalized = name.strip()
    if not TOOL_NAME_PATTERN.fullmatch(normalized):
        raise ToolValidationError(
            "O nome deve começar com letra ou _ e conter apenas letras, números, _ ou -."
        )
    if normalized.casefold() in {item.casefold() for item in RESERVED_TOOL_NAMES}:
        raise ToolValidationError("Esse nome é reservado pelo Codex.")
    if not description.strip():
        raise ToolValidationError("Informe uma descrição para a tool.")
    if not isinstance(input_schema, dict) or input_schema.get("type", "object") != "object":
        raise ToolValidationError("O JSON Schema deve descrever um objeto.")
    _validate_schema_shape(input_schema)
    if not executable.strip():
        raise ToolValidationError("Informe o executável da tool.")
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        raise ToolValidationError("Os argumentos fixos devem ser uma lista de textos.")


def _validate_schema_shape(schema: dict[str, Any], path: str = "schema") -> None:
    allowed_types = {"object", "array", "string", "number", "integer", "boolean", "null"}
    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in allowed_types:
        raise ToolValidationError(f"Tipo JSON Schema inválido em {path}: {schema_type}")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ToolValidationError(f"properties deve ser um objeto em {path}.")
    for name, child in properties.items():
        if not isinstance(child, dict):
            raise ToolValidationError(f"A propriedade {name} deve conter um schema.")
        _validate_schema_shape(child, f"{path}.properties.{name}")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ToolValidationError(f"required deve ser uma lista de nomes em {path}.")
    if any(name not in properties for name in required):
        raise ToolValidationError(f"required referencia propriedade inexistente em {path}.")
    items = schema.get("items")
    if items is not None:
        if not isinstance(items, dict):
            raise ToolValidationError(f"items deve conter um schema em {path}.")
        _validate_schema_shape(items, f"{path}.items")


def validate_tool_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Os argumentos da tool devem formar um objeto JSON.")
    properties = schema.get("properties", {})
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise ToolExecutionError("Argumentos obrigatórios ausentes: " + ", ".join(missing))
    if schema.get("additionalProperties") is False:
        extra = [name for name in arguments if name not in properties]
        if extra:
            raise ToolExecutionError("Argumentos não permitidos: " + ", ".join(extra))
    for name, value in arguments.items():
        child = properties.get(name)
        if child:
            _validate_value(value, child, name)


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected and not type_checks[expected](value):
        raise ToolExecutionError(f"O argumento {path} deve ser do tipo {expected}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolExecutionError(f"O argumento {path} não pertence aos valores permitidos.")
    if expected == "object":
        validate_tool_arguments(value, schema)
    elif expected == "array" and isinstance(value, list) and schema.get("items"):
        for index, item in enumerate(value):
            _validate_value(item, schema["items"], f"{path}[{index}]")


def dynamic_tool_spec(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": str(tool["name"]),
        "description": str(tool["description"]),
        "inputSchema": tool.get("input_schema") or {"type": "object"},
    }


def run_local_tool(
    tool: dict[str, Any],
    arguments: dict[str, Any],
    workspace: Path,
) -> ToolExecutionResult:
    executable = str(tool.get("executable") or "").strip()
    fixed_arguments = list(tool.get("arguments") or [])
    validate_tool_definition(
        str(tool.get("name") or ""),
        str(tool.get("description") or ""),
        tool.get("input_schema") or {"type": "object"},
        executable,
        fixed_arguments,
    )
    validate_tool_arguments(arguments, tool.get("input_schema") or {"type": "object"})
    resolved = Path(executable).expanduser()
    command = [str(resolved) if resolved.is_absolute() else executable, *fixed_arguments]
    timeout = min(300, max(1, int(tool.get("timeout_seconds") or 60)))
    startup_info: dict[str, Any] = {}
    if os.name == "nt":
        startup_info["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(arguments, ensure_ascii=False),
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            **startup_info,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError(f"A tool excedeu o timeout de {timeout} segundos.") from exc
    except OSError as exc:
        raise ToolExecutionError(f"Não foi possível executar a tool: {exc}") from exc

    stdout = completed.stdout or ""
    stderr = (completed.stderr or "").strip()
    if len(stdout.encode("utf-8")) + len(stderr.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
        raise ToolExecutionError("A saída da tool excedeu o limite de 64 KiB.")
    if completed.returncode:
        detail = stderr or stdout.strip() or "sem detalhes"
        raise ToolExecutionError(
            f"A tool terminou com código {completed.returncode}: {detail[:4000]}"
        )
    text = stdout.strip()
    if not text and stderr:
        text = stderr[:4000]
    if not text:
        text = "Tool executada sem saída."
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    return ToolExecutionResult(text=text, parsed=parsed)


def mcp_thread_config(
    selected: list[dict[str, str]],
    known_servers: list[str],
    server_configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    grouped: dict[str, list[str]] = {}
    for item in selected:
        server = str(item.get("server") or "")
        tool = str(item.get("tool") or "")
        if server and tool:
            grouped.setdefault(server, []).append(tool)
    configs = server_configs or {}
    servers: dict[str, Any] = {}
    for server in dict.fromkeys([*known_servers, *grouped.keys()]):
        if server not in configs:
            continue
        tools = list(dict.fromkeys(grouped.get(server, [])))
        # App Server replaces nested tables in a thread config layer, so copy
        # the effective transport/auth fields and change only selection leaves.
        config = {key: value for key, value in configs[server].items() if value is not None}
        config["enabled"] = bool(tools)
        config["enabled_tools"] = tools
        servers[server] = config
    return {"mcp_servers": servers} if servers else {}


VR_SOURCES_TOOL_NAME = "vr_sources"
VR_SOURCES_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "enum": ["wiki", "kb", "schema", "code", "project"],
            "description": "Fonte opcional para listar inventário ou módulos.",
        },
        "context": {
            "type": "string",
            "description": "Contexto opcional de aplicação (ex.: vr-master-server, vr-pdv) para listar classes/pacotes de código.",
        },
        "cursor": {
            "type": "integer",
            "description": "Deslocamento de paginação (padrão 0).",
        },
        "limit": {
            "type": "integer",
            "description": "Quantidade de itens retornados (1-50, padrão 20).",
        },
    },
    "additionalProperties": False,
}


def vr_sources_tool_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "name": VR_SOURCES_TOOL_NAME,
        "description": (
            "Descobre e lista fontes, módulos, contextos de aplicação e inventário de código Java "
            "disponíveis na base local do VR. Use para identificar contextos, pacotes e módulos antes da busca detalhada."
        ),
        "inputSchema": VR_SOURCES_INPUT_SCHEMA,
    }


VR_SEARCH_TOOL_NAME = "vr_search"
VR_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Consulta em português com os termos técnicos do VR "
                "(rotina, procedimento, tabela, campo ou classe Java)."
            ),
        },
        "source": {
            "type": "string",
            "enum": ["wiki", "kb", "schema", "code", "project"],
            "description": (
                "Fonte opcional: wiki (funcionamento), kb (processos e casos), "
                "schema (tabelas e relacionamentos) ou code (código Java descompilado). "
                "Omita para buscar Wiki, KB, Schema e Código em paralelo."
            ),
        },
        "context": {
            "type": "string",
            "description": "Contexto opcional de aplicação para restringir busca em código.",
        },
        "cursor": {
            "type": "integer",
            "description": "Deslocamento para paginação de resultados (padrão 0).",
        },
        "limit": {
            "type": "integer",
            "description": "Quantidade máxima de resultados (1-20, padrão 6).",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


def vr_search_tool_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "name": VR_SEARCH_TOOL_NAME,
        "description": (
            "Busca evidências validadas na base de conhecimento local do VR. "
            "Sem `source`, consulta Wiki (funcionamento), KB (processos), Schema "
            "(banco) e Código Java descompilado em paralelo e devolve um "
            "resultado consolidado. Com `source`, consulta somente a fonte "
            "escolhida. Use sempre que faltar detalhe confiável sobre regras, "
            "procedimentos, funcionamento, rotinas ou implementações antes de responder."
        ),
        "inputSchema": VR_SEARCH_INPUT_SCHEMA,
    }


VR_READ_TOOL_NAME = "vr_read"
VR_READ_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reference": {
            "type": "string",
            "description": (
                "Identificador ou caminho da evidência a ler. Pode ser 'source:source_id' "
                "(ex.: 'wiki:123', 'schema:TB_CLIENTE') ou FQCN / caminho de classe Java "
                "(ex.: 'br.com.vrsoft.fiscal.venda.VendaFiscal')."
            ),
        },
        "start_line": {
            "type": "integer",
            "description": "Linha inicial para leitura em código Java (1-indexed).",
        },
        "end_line": {
            "type": "integer",
            "description": "Linha final para leitura em código Java (1-indexed).",
        },
        "cursor": {
            "type": "integer",
            "description": "Offset em caracteres para leitura paginada de documento ou código.",
        },
        "limit": {
            "type": "integer",
            "description": "Quantidade máxima de caracteres a retornar (máximo 8000, padrão 4000).",
        },
    },
    "required": ["reference"],
    "additionalProperties": False,
}


def vr_read_tool_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "name": VR_READ_TOOL_NAME,
        "description": (
            "Lê o conteúdo integral ou trecho paginado de um documento da base VR "
            "ou de uma classe Java descompilada usando sua referência ou FQCN."
        ),
        "inputSchema": VR_READ_INPUT_SCHEMA,
    }


def all_vr_tools_specs() -> list[dict[str, Any]]:
    return [
        vr_sources_tool_spec(),
        vr_search_tool_spec(),
        vr_read_tool_spec(),
    ]


def _access_service(router: Any) -> Any:
    from .knowledge_router import KnowledgeRouter
    from .retrieval.service import RetrievalService
    return RetrievalService(router) if isinstance(router, KnowledgeRouter) else router


def run_vr_sources(arguments: dict[str, Any], router: Any, **kwargs: Any) -> ToolExecutionResult:
    validate_tool_arguments(arguments, VR_SOURCES_INPUT_SCHEMA)
    service = _access_service(router)
    payload = service.sources(source=str(arguments.get("source") or ""), context=str(arguments.get("context") or ""),
        cursor=max(0, int(arguments.get("cursor") or 0)), limit=max(1, min(50, int(arguments.get("limit") or 20))), **kwargs)
    return ToolExecutionResult(text=json.dumps(payload, ensure_ascii=False), parsed=payload)


def run_vr_search(arguments: dict[str, Any], router: Any, **kwargs: Any) -> ToolExecutionResult:
    validate_tool_arguments(arguments, VR_SEARCH_INPUT_SCHEMA)
    service = _access_service(router)
    options = {"source": str(arguments.get("source") or ""),
               "limit": max(1, min(20, int(arguments.get("limit") or 6)))}
    if arguments.get("context"):
        options["context"] = str(arguments["context"])
    if "cursor" in arguments:
        options["cursor"] = max(0, int(arguments["cursor"]))
    payload = service.search(str(arguments.get("query") or "").strip(), **options, **kwargs)
    return ToolExecutionResult(text=json.dumps(payload, ensure_ascii=False), parsed=payload)


def run_vr_read(arguments: dict[str, Any], router: Any, **kwargs: Any) -> ToolExecutionResult:
    validate_tool_arguments(arguments, VR_READ_INPUT_SCHEMA)
    service = _access_service(router)
    payload = service.read(str(arguments.get("reference") or "").strip(),
        cursor=max(0, int(arguments.get("cursor") or 0)), limit=max(1, min(8000, int(arguments.get("limit") or 4000))),
        start_line=arguments.get("start_line"), end_line=arguments.get("end_line"), **kwargs)
    return ToolExecutionResult(text=json.dumps(payload, ensure_ascii=False), parsed=payload)


def run_bounded_vr_tool(name: str, arguments: dict[str, Any], router: Any,
                        remaining_chars: int, **scope: Any) -> ToolExecutionResult:
    """Fit a real page, never truncate JSON or lose continuation references."""
    runners = {VR_SEARCH_TOOL_NAME: (run_vr_search, 6),
               VR_READ_TOOL_NAME: (run_vr_read, 4000),
               VR_SOURCES_TOOL_NAME: (run_vr_sources, 20)}
    runner, default_limit = runners[name]
    options = dict(arguments)
    size = max(1, int(options.get("limit") or default_limit))
    while remaining_chars > 256:
        options["limit"] = size
        result = runner(options, router, **scope)
        payload = dict(result.parsed)
        payload["budget"] = {"remaining_chars": 0, "page_reduced": size < int(arguments.get("limit") or default_limit)}
        # Reserve enough digits for the remaining budget before measuring.
        payload["budget"]["remaining_chars"] = remaining_chars
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) <= remaining_chars:
            payload["budget"]["remaining_chars"] = remaining_chars - len(text)
            return ToolExecutionResult(text=json.dumps(payload, ensure_ascii=False), parsed=payload)
        if size == 1 or payload.get("error"):
            break
        size = max(1, size // 2)
    payload = {"state": "budget_exhausted", "remaining_chars": remaining_chars,
               "error": "O saldo de respostas deste turno não comporta outra página. "
                        "Use as evidências já recebidas ou continue em um novo turno; não repita a consulta."}
    return ToolExecutionResult(text=json.dumps(payload, ensure_ascii=False), parsed=payload)

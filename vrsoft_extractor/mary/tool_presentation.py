"""Presentation Layer for Tool Activities (Etapa 4).

Provides:
- ToolPresentation: Formatted visual view model for UI components.
- ToolGroupPresentation: Intelligent aggregation of sequential/parallel tool calls.
- Specialized Formatters for each ToolType:
  - CommandExecutionFormatter
  - FileChangeFormatter
  - FileReadFormatter
  - WebSearchFormatter
  - McpToolCallFormatter
  - BrowserFormatter
  - SubagentFormatter
  - GenericFormatter
- ToolPresentationRegistry: Central dispatcher and registry for tool formatters.
- Error and title sanitization ensuring no 'null', 'None', or raw stack traces leak to titles.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
import json
from typing import Any
from urllib.parse import urlparse

from .tool_activity import (
    ToolActivity,
    ToolEventKind,
    ToolStatus,
    ToolType,
    sanitize_error_summary,
    sanitize_title,
)


def format_duration(ms: int) -> str:
    """Format duration in milliseconds into a human-readable string."""
    if ms < 0:
        return "0s"
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem_seconds = int(seconds % 60)
    return f"{minutes}m {rem_seconds}s"


@dataclass
class ToolPresentation:
    """Visual view model representing a tool execution for QML and UI."""

    tool_id: str
    tool_type: ToolType
    status: ToolStatus
    kind: str = "tool"
    item_type: str = "tool"
    state: str = "running"  # "running" | "completed" | "error" | "cancelled" | "interrupted" | "waiting_approval"
    text: str = ""
    subtitle: str = ""
    detail: str = ""
    command: str = ""
    cwd: str = ""
    files: list[str] = field(default_factory=list)
    file_count: int = 0
    additions: int = 0
    deletions: int = 0
    folder_summary: str = ""
    has_diff: bool = False
    diff_content: str = ""
    output: str = ""
    error_summary: str = ""
    error_details: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    duration_label: str = "0s"
    icon: str = "hammer"
    badge_text: str = ""
    badge_variant: str = "neutral"
    can_expand: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.text

    def to_dict(self) -> dict[str, Any]:
        """Serialize into a dict compatible with both legacy and new QML items."""
        return {
            "id": self.tool_id,
            "kind": self.kind,
            "itemType": self.item_type,
            "state": self.state,
            "text": self.text,
            "title": self.text,
            "subtitle": self.subtitle,
            "detail": self.detail,
            "command": self.command,
            "cwd": self.cwd,
            "files": list(self.files),
            "fileCount": self.file_count,
            "additions": self.additions,
            "deletions": self.deletions,
            "folderSummary": self.folder_summary,
            "hasDiff": self.has_diff,
            "diffContent": self.diff_content,
            "output": self.output,
            "errorSummary": self.error_summary,
            "errorDetails": self.error_details,
            "exitCode": self.exit_code,
            "durationMs": self.duration_ms,
            "durationLabel": self.duration_label,
            "icon": self.icon,
            "badgeText": self.badge_text,
            "badgeVariant": self.badge_variant,
            "canExpand": self.can_expand,
            "toolType": self.tool_type.value,
            "status": self.status.value,
            "metadata": dict(self.metadata),
        }


@dataclass
class ToolGroupPresentation:
    """Grouped presentation model for multiple sequential/parallel tool executions."""

    group_id: str
    title: str
    status: ToolStatus
    state: str
    badge_text: str
    badge_variant: str
    duration_ms: int
    duration_label: str
    total_tools: int
    running_count: int
    failed_count: int
    items: list[ToolPresentation] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "action_group"

    @property
    def tool_id(self) -> str:
        return self.group_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.group_id,
            "kind": "tool_group",
            "itemType": "tool_group",
            "title": self.title,
            "text": self.title,
            "status": self.status.value,
            "state": self.state,
            "badgeText": self.badge_text,
            "badgeVariant": self.badge_variant,
            "durationMs": self.duration_ms,
            "durationLabel": self.duration_label,
            "totalTools": self.total_tools,
            "runningCount": self.running_count,
            "failedCount": self.failed_count,
            "items": [item.to_dict() for item in self.items],
        }


class ToolFormatter(ABC):
    """Abstract base class for typed tool formatters."""

    @abstractmethod
    def format(self, activity: ToolActivity) -> ToolPresentation:
        """Transform a canonical ToolActivity into a ToolPresentation."""
        pass


def _map_state(status: ToolStatus) -> str:
    if status in (ToolStatus.FAILURE, ToolStatus.TIMED_OUT):
        return "error"
    if status == ToolStatus.SUCCESS:
        return "completed"
    if status == ToolStatus.INTERRUPTED:
        return "interrupted"
    if status == ToolStatus.CANCELLED:
        return "cancelled"
    if status == ToolStatus.WAITING_APPROVAL:
        return "waiting_approval"
    return "running"


def _extract_errors(activity: ToolActivity) -> tuple[str, str]:
    """Return (error_summary, error_details)."""
    raw = activity.error_details or activity.error
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"], json.dumps(
            {k: v for k, v in payload.items() if k != "error"}, ensure_ascii=False, indent=2
        )
    if activity.error_details:
        return activity.error or "Erro", activity.error_details
    raw_error = activity.error or ""
    if not raw_error and activity.status == ToolStatus.FAILURE:
        raw_error = str(activity.output) if activity.output else "Erro desconhecido"

    clean_summary, details = sanitize_error_summary(raw_error)
    return clean_summary, details


class CommandExecutionFormatter(ToolFormatter):
    """Specialized formatter for command executions (terminal/shell)."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        cmd = (activity.command or activity.input or "").strip()
        if isinstance(cmd, dict):
            cmd = str(cmd.get("CommandLine") or cmd.get("command") or "")

        error_summary, error_details = _extract_errors(activity)

        title = sanitize_title(activity.title, activity.name, ToolType.COMMAND_EXECUTION, activity.status, error=activity.error)
        if title in {"Executar comando", "Comando falhou"} and cmd:
            if activity.status == ToolStatus.SUCCESS:
                title = f"Executado: {cmd[:40]}"
            elif activity.status == ToolStatus.RUNNING:
                title = f"Executando: {cmd[:40]}"
            elif activity.status == ToolStatus.WAITING_APPROVAL:
                title = f"Aprovação pendente: {cmd[:40]}"

        if state == "waiting_approval":
            title = f"Aprovação pendente: {cmd[:40]}" if cmd else "Aprovação pendente: comando"
        elif activity.metadata.get("denied"):
            title = f"Comando negado: {cmd[:40]}" if cmd else "Comando negado"

        # Subtitle is full command, cwd, or error summary if failed
        subtitle = cmd if len(cmd) > 40 else (activity.cwd or "")
        if state == "error" and error_summary:
            subtitle = error_summary
        elif activity.exit_code is not None and activity.exit_code != 0:
            if not error_summary or error_summary == "Erro":
                error_summary = f"Código de saída: {activity.exit_code}"
            if state == "error":
                subtitle = error_summary

        # Combine output and error for detail pane (preserve full content)
        detail_lines: list[str] = []
        if cmd:
            detail_lines.append(f"$ {cmd}")
        if activity.cwd:
            detail_lines.append(f"Cwd: {activity.cwd}")
        if activity.output:
            detail_lines.append(str(activity.output))
        if error_details:
            detail_lines.append("\n--- Erro / Stack trace ---\n" + error_details)
        elif error_summary and error_summary not in detail_lines:
            detail_lines.append(error_summary)

        detail = "\n".join(detail_lines)

        icon = "terminalPrompt"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = f"exit {activity.exit_code}" if activity.exit_code is not None else "falhou"
        elif state == "completed":
            icon = "check"
            badge_variant = "success"
            badge_text = "sucesso"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "executando"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=ToolType.COMMAND_EXECUTION,
            status=activity.status,
            kind="tool",
            item_type="commandExecution",
            state=state,
            text=title,
            subtitle=subtitle,
            detail=detail,
            command=cmd,
            cwd=activity.cwd,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            exit_code=activity.exit_code,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class FileChangeFormatter(ToolFormatter):
    """Specialized formatter for file edits, patches, and diffs."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        files = list(activity.files)
        file_count = len(files)

        # Calculate folder summary
        folders = set()
        for f in files:
            parts = f.replace("\\", "/").split("/")
            if len(parts) > 1:
                folders.add(parts[0])
        folder_summary = ", ".join(sorted(folders)[:3])

        # Diff and stats
        additions = 0
        deletions = 0
        diff_text = ""
        changes = activity.metadata.get("changes") or activity.locations or []
        for c in changes:
            if isinstance(c, dict):
                additions += int(c.get("additions") or 0)
                deletions += int(c.get("deletions") or 0)
                if c.get("diff"):
                    diff_text += str(c["diff"]) + "\n"

        if not diff_text and activity.output:
            diff_text = str(activity.output)

        title = sanitize_title(activity.title, activity.name, ToolType.FILE_CHANGE, activity.status, error=activity.error)
        if title in {"Alterar arquivo", "Erro ao alterar arquivo"} or not activity.title:
            if state == "waiting_approval":
                title = f"Aprovação pendente: {file_count} arquivos" if file_count > 1 else (f"Aprovar alteração: {files[0]}" if file_count == 1 else "Aprovação pendente: alterar arquivo")
            elif state == "completed":
                title = f"Alterou {files[0]}" if file_count == 1 else (f"Alterou {file_count} arquivos" if file_count > 1 else "Alterou arquivo")
            elif state == "error":
                title = f"Erro ao alterar {files[0]}" if file_count == 1 else (f"Erro ao alterar {file_count} arquivos" if file_count > 1 else "Erro ao alterar arquivo")
            else:
                title = f"Alterando {files[0]}" if file_count == 1 else (f"Alterando {file_count} arquivos" if file_count > 1 else "Alterando arquivo")

        error_summary, error_details = _extract_errors(activity)

        detail_lines: list[str] = []
        if files:
            detail_lines.append("Arquivos:\n" + "\n".join(f"- {f}" for f in files))
        if diff_text:
            detail_lines.append("\n" + diff_text)
        if error_details:
            detail_lines.append("\n" + error_details)

        detail = "\n".join(detail_lines)

        icon = "fileDiff"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = "falhou"
        elif state == "completed":
            badge_variant = "success"
            badge_text = f"+{additions} -{deletions}" if (additions or deletions) else "modificado"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "alterando"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=ToolType.FILE_CHANGE,
            status=activity.status,
            kind="file_changes",
            item_type="fileChange",
            state=state,
            text=title,
            subtitle=error_summary if (state == "error" and error_summary) else folder_summary,
            detail=detail,
            files=files,
            file_count=file_count,
            additions=additions,
            deletions=deletions,
            folder_summary=folder_summary,
            has_diff=bool(diff_text),
            diff_content=diff_text,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class FileReadFormatter(ToolFormatter):
    """Specialized formatter for reading file contents."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        files = list(activity.files)
        path = files[0] if files else (activity.name or "")
        file_count = len(files)

        if state == "waiting_approval":
            title = f"Aprovação pendente: ler {path}" if path else "Aprovação pendente: ler arquivo"
        elif state == "error":
            title = f"Erro ao ler {path}" if path else "Erro ao ler arquivo"
        elif file_count > 1:
            title = f"Leu {file_count} arquivos"
        elif path:
            title = f"Ler {path}"
        else:
            title = "Ler arquivo"

        title = sanitize_title(title, activity.name, ToolType.FILE_READ, activity.status, error=activity.error)

        error_summary, error_details = _extract_errors(activity)
        detail = str(activity.output or activity.error or "")

        icon = "document"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = "falhou"
        elif state == "completed":
            badge_variant = "success"
            badge_text = "lido"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "lendo"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=ToolType.FILE_READ,
            status=activity.status,
            kind="tool",
            item_type="fileRead",
            state=state,
            text=title,
            subtitle=error_summary if (state == "error" and error_summary) else path,
            detail=detail,
            files=files,
            file_count=file_count,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class WebSearchFormatter(ToolFormatter):
    """Specialized formatter for web and documentation search."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        query = ""
        if isinstance(activity.input, dict):
            query = str(activity.input.get("query") or activity.input.get("q") or "")
        elif isinstance(activity.input, str):
            query = activity.input

        if state == "waiting_approval":
            title = f'Aprovação pendente: "{query[:40]}"' if query else "Aprovação pendente: pesquisa web"
        elif state == "completed":
            title = f'Pesquisou "{query[:40]}"' if query else "Pesquisou na web"
        elif state == "error":
            title = f'Erro ao pesquisar "{query[:40]}"' if query else "Pesquisa na web falhou"
        else:
            title = f'Pesquisando "{query[:40]}"' if query else "Pesquisando na web"

        title = sanitize_title(title, activity.name, ToolType.WEB_SEARCH, activity.status, error=activity.error)
        error_summary, error_details = _extract_errors(activity)
        detail = str(activity.output or activity.error or "")

        icon = "search"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = "falhou"
        elif state == "completed":
            badge_variant = "success"
            badge_text = "encontrado"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "pesquisando"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=ToolType.WEB_SEARCH,
            status=activity.status,
            kind="tool",
            item_type="webSearch",
            state=state,
            text=title,
            subtitle=error_summary if (state == "error" and error_summary) else query,
            detail=detail,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class McpToolCallFormatter(ToolFormatter):
    """Specialized formatter for MCP protocol tool calls."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        server = str(activity.metadata.get("server") or "")
        tool_name = str(activity.name or activity.metadata.get("tool") or "")
        if tool_name.startswith("vr-mary-studio_"):
            server, tool_name = "vr-mary-studio", tool_name.removeprefix("vr-mary-studio_")
        elif tool_name.startswith("mcp__"):
            parts = tool_name.split("__", 2)
            if len(parts) == 3:
                _, server, tool_name = parts
        server_tool = f"{server}/{tool_name}" if server else tool_name

        if state == "waiting_approval":
            title = f"Aprovação pendente: {server_tool}" if server_tool else "Aprovação pendente: ferramenta MCP"
        elif state == "completed":
            title = f"Executou {server_tool}" if server_tool else "Executou ferramenta MCP"
        elif state == "error":
            title = f"Erro em {server_tool}" if server_tool else "Chamada MCP falhou"
        else:
            title = f"Executando {server_tool}" if server_tool else "Chamando ferramenta MCP"

        if server == "vr-mary-studio" and state != "waiting_approval":
            args = activity.input if isinstance(activity.input, dict) else {}
            if tool_name == "vr_read":
                title = "Ler " + str(args.get("reference") or "fonte VR")
            elif tool_name == "vr_search":
                title = "Buscar " + str(args.get("query") or "na base VR")
            elif tool_name == "vr_sources":
                title = "Listar fontes " + str(args.get("source") or "VR")

        title = sanitize_title(title, activity.name, ToolType.MCP_TOOL_CALL, activity.status, error=activity.error)
        error_summary, error_details = _extract_errors(activity)

        detail_lines: list[str] = []
        if server:
            detail_lines.append(f"Servidor: {server}")
        if tool_name:
            detail_lines.append(f"Ferramenta: {tool_name}")
        if activity.input:
            try:
                args_str = (
                    json.dumps(activity.input, indent=2, ensure_ascii=False)
                    if isinstance(activity.input, (dict, list))
                    else str(activity.input)
                )
                detail_lines.append(f"Parâmetros:\n{args_str}")
            except Exception:
                detail_lines.append(f"Parâmetros: {activity.input}")
        if activity.output:
            detail_lines.append(f"\nResposta:\n{activity.output}")

        detail = "\n".join(detail_lines)

        icon = "plug"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = "falhou"
        elif state == "completed":
            badge_variant = "success"
            badge_text = "concluído"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "chamando"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=ToolType.MCP_TOOL_CALL,
            status=activity.status,
            kind="tool",
            item_type="mcpToolCall",
            state=state,
            text=title,
            subtitle=server_tool,
            detail=detail,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class BrowserFormatter(ToolFormatter):
    """Specialized formatter for browser actions and device automation."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        raw_action = str(activity.name or "browser")

        # Sanitize long URL in title by extracting host/domain
        clean_action = raw_action
        url = str(activity.metadata.get("url") or (activity.input if isinstance(activity.input, str) else ""))
        if not url and raw_action.startswith(("http://", "https://")):
            url = raw_action
        if url:
            try:
                parsed = urlparse(url)
                host = parsed.netloc or parsed.path
                if host:
                    clean_action = host
            except Exception:
                clean_action = url[:40]

        if state == "waiting_approval":
            title = f"Aprovação pendente: {clean_action}"
        elif state == "completed":
            title = f"Navegou para {clean_action}" if clean_action != "browser" else "Navegação concluída"
        elif state == "error":
            title = f"Erro ao navegar: {clean_action}"
        else:
            title = f"Navegando: {clean_action}"

        title = sanitize_title(title, activity.name, ToolType.BROWSER, activity.status, error=activity.error)
        error_summary, error_details = _extract_errors(activity)
        detail = str(activity.output or activity.input or "")

        icon = "globe"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = "falhou"
        elif state == "completed":
            badge_variant = "success"
            badge_text = "pronto"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "navegando"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=ToolType.BROWSER,
            status=activity.status,
            kind="tool",
            item_type="browser",
            state=state,
            text=title,
            subtitle=error_summary if (state == "error" and error_summary) else clean_action,
            detail=detail,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class SubagentFormatter(ToolFormatter):
    """Specialized formatter for delegated subagents."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        agent_name = str(activity.name or "subagente")

        if state == "waiting_approval":
            title = f"Aprovação pendente: subagente {agent_name}"
        elif state == "completed":
            title = f"Subagente finalizado: {agent_name}"
        elif state == "error":
            title = f"Subagente falhou: {agent_name}"
        else:
            title = f"Subagente: {agent_name}"

        title = sanitize_title(title, activity.name, ToolType.SUBAGENT, activity.status, error=activity.error)
        error_summary, error_details = _extract_errors(activity)
        detail = str(activity.output or activity.input or "")

        icon = "robot"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = "falhou"
        elif state == "completed":
            badge_variant = "success"
            badge_text = "concluído"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "executando"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=ToolType.SUBAGENT,
            status=activity.status,
            kind="tool",
            item_type="subagent",
            state=state,
            text=title,
            subtitle=error_summary if (state == "error" and error_summary) else agent_name,
            detail=detail,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class GenericFormatter(ToolFormatter):
    """Fallback formatter for unknown or generic tool activities."""

    def format(self, activity: ToolActivity) -> ToolPresentation:
        state = _map_state(activity.status)
        name = activity.name or "ferramenta"
        title = sanitize_title(activity.title, name, activity.type, activity.status, error=activity.error)
        error_summary, error_details = _extract_errors(activity)
        detail = str(
            activity.command
            or activity.output
            or activity.input
            or activity.error
            or ""
        )

        icon = "hammer"
        if state == "error":
            icon = "close"
            badge_variant = "error"
            badge_text = "falhou"
        elif state == "completed":
            badge_variant = "success"
            badge_text = "sucesso"
        elif state == "interrupted":
            icon = "close"
            badge_variant = "warning"
            badge_text = "interrompido"
        elif state == "cancelled":
            icon = "close"
            badge_variant = "warning"
            badge_text = "negado" if activity.metadata.get("denied") else "cancelado"
        elif state == "waiting_approval":
            icon = "alert"
            badge_variant = "warning"
            badge_text = "aguardando aprovação"
        else:
            badge_variant = "info"
            badge_text = "executando"

        dur_ms = activity.duration_ms() or 0
        return ToolPresentation(
            tool_id=activity.id,
            tool_type=activity.type,
            status=activity.status,
            kind="tool",
            item_type=activity.type.value,
            state=state,
            text=title,
            subtitle=error_summary if (state == "error" and error_summary) else name,
            detail=detail,
            output=str(activity.output) if activity.output is not None else "",
            error_summary=error_summary,
            error_details=error_details,
            exit_code=activity.exit_code,
            duration_ms=dur_ms,
            duration_label=format_duration(dur_ms) if activity.duration_ms() is not None else "",
            icon=icon,
            badge_text=badge_text,
            badge_variant=badge_variant,
            can_expand=bool(detail),
            metadata=dict(activity.metadata),
        )


class ToolPresentationRegistry:
    """Registry and dispatcher of typed tool formatters."""

    def __init__(self) -> None:
        self._formatters: dict[ToolType, ToolFormatter] = {}
        self._default_formatter = GenericFormatter()
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(ToolType.COMMAND_EXECUTION, CommandExecutionFormatter())
        self.register(ToolType.FILE_CHANGE, FileChangeFormatter())
        self.register(ToolType.FILE_READ, FileReadFormatter())
        self.register(ToolType.WEB_SEARCH, WebSearchFormatter())
        self.register(ToolType.MCP_TOOL_CALL, McpToolCallFormatter())
        self.register(ToolType.BROWSER, BrowserFormatter())
        self.register(ToolType.SUBAGENT, SubagentFormatter())
        self.register(ToolType.UNKNOWN, GenericFormatter())

    def register(self, tool_type: ToolType, formatter: ToolFormatter) -> None:
        self._formatters[tool_type] = formatter

    def get_formatter(self, tool_type: ToolType) -> ToolFormatter:
        return self._formatters.get(tool_type, self._default_formatter)

    def format(self, activity: ToolActivity) -> ToolPresentation:
        if activity.type == ToolType.UNKNOWN:
            activity = replace(activity, type=ToolType.from_string(activity.name))
        formatter = self.get_formatter(activity.type)
        return formatter.format(activity)

    def format_many(self, activities: list[ToolActivity]) -> list[ToolPresentation]:
        return [self.format(a) for a in activities]

    def format_from_event(self, event: Any) -> ToolPresentation:
        from .provider_adapters.tool_normalizer import normalize_generic_event
        """Helper to convert a RuntimeEvent into ToolPresentation via normalization."""
        norm = normalize_generic_event(event)
        if norm:
            clean_summary, clean_details = sanitize_error_summary(norm.error or "")
            activity = ToolActivity(
                id=norm.tool_id,
                conversation_id=event.conversation_id,
                provider=norm.provider,
                type=norm.type,
                name=norm.name,
                title=norm.title,
                command=norm.command,
                cwd=norm.cwd,
                files=list(norm.files),
                input=norm.input,
                output=norm.output,
                error=clean_summary,
                error_details=clean_details,
                exit_code=norm.exit_code,
                status=norm.status or (
                    ToolStatus.FAILURE if norm.kind == ToolEventKind.FAILED
                    else (ToolStatus.SUCCESS if norm.kind == ToolEventKind.COMPLETED
                    else ToolStatus.RUNNING)
                ),
                started_at=event.created_at,
                metadata=dict(event.payload),
            )
            return self.format(activity)

        # Basic fallback for non-normalized event (never reuse shared "tool" id).
        text = event.text or "Atividade"
        payload = event.payload if isinstance(event.payload, dict) else {}
        fallback_id = str(
            payload.get("id")
            or payload.get("runtime_event_id")
            or payload.get("request_id")
            or payload.get("execution_id")
            or ""
        ).strip()
        if fallback_id.lower() in {"", "tool", "unknown", "item"}:
            import time as _time

            fallback_id = f"anon:{str(payload.get('execution_id') or 'exec')}:{int(_time.time() * 1000) % 1000000}"
        return ToolPresentation(
            tool_id=fallback_id,
            tool_type=ToolType.UNKNOWN,
            status=ToolStatus.RUNNING,
            kind="tool",
            item_type="tool",
            state="running",
            text=text,
            detail=str(event.payload.get("detail") or ""),
        )

    def group_activities(
        self, activities: list[ToolActivity], group_id: str = "group_1"
    ) -> ToolGroupPresentation:
        """Aggregate multiple tool activities into an intelligent group summary."""
        items = self.format_many(activities)
        total = len(items)
        if total == 0:
            return ToolGroupPresentation(
                group_id=group_id,
                title="Nenhuma ferramenta",
                status=ToolStatus.SUCCESS,
                state="completed",
                badge_text="0",
                badge_variant="neutral",
                duration_ms=0,
                duration_label="0s",
                total_tools=0,
                running_count=0,
                failed_count=0,
                items=[],
            )

        running_count = sum(1 for item in items if item.state == "running")
        failed_count = sum(1 for item in items if item.state == "error")
        cancelled_count = sum(1 for item in items if item.state in {"cancelled", "interrupted"})
        waiting_count = sum(1 for item in items if item.state == "waiting_approval")

        # Group status resolution
        if failed_count > 0:
            group_status = ToolStatus.FAILURE
            group_state = "error"
            badge_text = f"{failed_count} falha" if failed_count == 1 else f"{failed_count} falhas"
            badge_variant = "error"
        elif running_count > 0:
            group_status = ToolStatus.RUNNING
            group_state = "running"
            badge_text = f"{running_count} rodando"
            badge_variant = "info"
        elif waiting_count > 0:
            group_status = ToolStatus.WAITING_APPROVAL
            group_state = "waiting_approval"
            badge_text = f"{waiting_count} aprovações" if waiting_count > 1 else "aguardando aprovação"
            badge_variant = "warning"
        elif cancelled_count > 0:
            group_status = ToolStatus.CANCELLED
            group_state = "cancelled"
            badge_text = "cancelado"
            badge_variant = "warning"
        else:
            group_status = ToolStatus.SUCCESS
            group_state = "completed"
            badge_text = f"{total} concluídos"
            badge_variant = "success"

        # Specialized group titles
        types = {item.tool_type for item in items}
        if len(types) == 1:
            only_type = next(iter(types))
            if only_type == ToolType.COMMAND_EXECUTION:
                title = f"{total} comandos executados" if total > 1 else items[0].text
            elif only_type == ToolType.FILE_READ:
                title = f"{total} arquivos lidos" if total > 1 else items[0].text
            elif only_type == ToolType.FILE_CHANGE:
                title = f"{total} alterações de arquivo" if total > 1 else items[0].text
            elif only_type == ToolType.WEB_SEARCH:
                title = f"{total} pesquisas realizadas" if total > 1 else items[0].text
            else:
                title = f"{total} ferramentas executadas"
        else:
            title = f"{total} ferramentas executadas"

        total_dur_ms = sum(item.duration_ms for item in items)
        return ToolGroupPresentation(
            group_id=group_id,
            title=title,
            status=group_status,
            state=group_state,
            badge_text=badge_text,
            badge_variant=badge_variant,
            duration_ms=total_dur_ms,
            duration_label=format_duration(total_dur_ms),
            total_tools=total,
            running_count=running_count,
            failed_count=failed_count,
            items=items,
        )

    def group_consecutive_tools(
        self,
        activities: list[ToolActivity],
        threshold: int = 3,
    ) -> list[ToolPresentation | ToolGroupPresentation]:
        """Intelligently group consecutive completed repetitive actions.
        
        Guarantees:
        - NEVER hides running, failure, or waiting_approval inside a group.
        - Long-running tools (duration >= 10s) are never collapsed into a group.
        - Preserves temporal order of distinct tool sequences.
        """
        if not activities:
            return []

        results: list[ToolPresentation | ToolGroupPresentation] = []
        cluster: list[ToolActivity] = []
        cluster_type: ToolType | None = None

        def flush_cluster():
            nonlocal cluster, cluster_type
            if not cluster:
                return
            if len(cluster) >= threshold:
                gid = f"grp_{cluster[0].id}"
                results.append(self.group_activities(cluster, group_id=gid))
            else:
                for a in cluster:
                    results.append(self.format(a))
            cluster = []
            cluster_type = None

        for act in activities:
            is_groupable = (
                act.status == ToolStatus.SUCCESS
                and (act.duration_ms() or 0) < 10000
                and act.type in {ToolType.FILE_READ, ToolType.COMMAND_EXECUTION, ToolType.WEB_SEARCH}
            )

            if is_groupable:
                if cluster_type is None or cluster_type == act.type:
                    cluster.append(act)
                    cluster_type = act.type
                else:
                    flush_cluster()
                    cluster.append(act)
                    cluster_type = act.type
            else:
                flush_cluster()
                results.append(self.format(act))

        flush_cluster()
        return results


DEFAULT_PRESENTATION_REGISTRY = ToolPresentationRegistry()


def group_consecutive_tools(
    activities: list[ToolActivity],
    threshold: int = 3,
) -> list[ToolPresentation | ToolGroupPresentation]:
    return DEFAULT_PRESENTATION_REGISTRY.group_consecutive_tools(activities, threshold=threshold)

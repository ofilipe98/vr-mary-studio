"""Canonical Tool Activity model, events and lifecycle reducer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import logging
from typing import Any

logger = logging.getLogger("mary.tool_activity")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolStatus(str, Enum):
    PENDING = "pending"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ToolStatus.SUCCESS,
            ToolStatus.FAILURE,
            ToolStatus.CANCELLED,
            ToolStatus.INTERRUPTED,
            ToolStatus.TIMED_OUT,
        }


class ToolType(str, Enum):
    COMMAND_EXECUTION = "commandExecution"
    FILE_READ = "fileRead"
    FILE_CHANGE = "fileChange"
    WEB_SEARCH = "webSearch"
    MCP_TOOL_CALL = "mcpToolCall"
    BROWSER = "browser"
    SUBAGENT = "subagent"
    REASONING = "reasoning"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, val: str | None) -> ToolType:
        if not val:
            return cls.UNKNOWN
        v = str(val).strip().lower()
        if v in {"command", "commandexecution", "bash", "terminal", "exec", "shell", "run_command"}:
            return cls.COMMAND_EXECUTION
        if v in {"fileread", "file_read", "read", "readfile", "view_file", "view", "cat"}:
            return cls.FILE_READ
        if v in {"filechange", "file_change", "edit", "write", "create_file", "edit_file", "patch", "apply_diff"}:
            return cls.FILE_CHANGE
        if v in {"websearch", "web_search", "search", "search_web", "google"}:
            return cls.WEB_SEARCH
        if v in {"mcptoolcall", "mcp_tool_call", "mcp", "call_mcp_tool"}:
            return cls.MCP_TOOL_CALL
        if v in {"browser", "browseractivity", "browse", "navigate", "preview"}:
            return cls.BROWSER
        if v in {"subagent", "agent", "invoke_subagent", "delegation"}:
            return cls.SUBAGENT
        if v in {"reasoning", "thinking", "thought"}:
            return cls.REASONING
        # Direct enum name match
        for member in cls:
            if member.value.lower() == v:
                return member
        return cls.UNKNOWN


class ToolEventKind(str, Enum):
    STARTED = "tool.started"
    UPDATED = "tool.updated"
    COMPLETED = "tool.completed"
    FAILED = "tool.failed"
    CANCELLED = "tool.cancelled"
    APPROVAL_REQUESTED = "tool.approval_requested"
    APPROVAL_RESOLVED = "tool.approval_resolved"

    @classmethod
    def from_string(cls, val: str | None) -> ToolEventKind:
        if not val:
            return cls.UPDATED
        v = str(val).strip().lower()
        mapping = {
            "tool.started": cls.STARTED,
            "tool_started": cls.STARTED,
            "started": cls.STARTED,
            "start": cls.STARTED,
            "tool.updated": cls.UPDATED,
            "tool_updated": cls.UPDATED,
            "updated": cls.UPDATED,
            "update": cls.UPDATED,
            "tool.completed": cls.COMPLETED,
            "tool_completed": cls.COMPLETED,
            "completed": cls.COMPLETED,
            "complete": cls.COMPLETED,
            "success": cls.COMPLETED,
            "tool.failed": cls.FAILED,
            "tool_failed": cls.FAILED,
            "failed": cls.FAILED,
            "fail": cls.FAILED,
            "error": cls.FAILED,
            "tool.cancelled": cls.CANCELLED,
            "tool_cancelled": cls.CANCELLED,
            "cancelled": cls.CANCELLED,
            "canceled": cls.CANCELLED,
            "tool.approval_requested": cls.APPROVAL_REQUESTED,
            "tool_approval_requested": cls.APPROVAL_REQUESTED,
            "approval_requested": cls.APPROVAL_REQUESTED,
            "waiting_approval": cls.APPROVAL_REQUESTED,
            "tool.approval_resolved": cls.APPROVAL_RESOLVED,
            "tool_approval_resolved": cls.APPROVAL_RESOLVED,
            "approval_resolved": cls.APPROVAL_RESOLVED,
        }
        return mapping.get(v, cls.UPDATED)


INVALID_TEXT_VALUES = {
    "null", "none", "undefined", "{}", "[]", '""', "''", "",
    "commandexecution", "filechange", "fileread", "websearch",
    "mcptoolcall", "browser", "subagent", "reasoning", "unknown",
    "tool", "item",
}


def sanitize_title(
    title: str | None,
    name: str | None,
    tool_type: ToolType,
    status: ToolStatus,
    error: str = "",
) -> str:
    """Sanitize invalid titles like 'null', None, '{}', returning semantic fallback."""
    raw_title = (title or "").strip()
    if raw_title and raw_title.lower() not in INVALID_TEXT_VALUES:
        return raw_title

    raw_name = (name or "").strip()
    if raw_name and raw_name.lower() not in INVALID_TEXT_VALUES:
        return raw_name

    # Semantic fallback based on tool type & status
    if status == ToolStatus.FAILURE or bool(error):
        fallback_errors = {
            ToolType.COMMAND_EXECUTION: "Comando falhou",
            ToolType.FILE_READ: "Erro ao ler arquivo",
            ToolType.FILE_CHANGE: "Erro ao alterar arquivo",
            ToolType.WEB_SEARCH: "Pesquisa na web falhou",
            ToolType.MCP_TOOL_CALL: "Chamada MCP falhou",
            ToolType.BROWSER: "Erro ao navegar",
            ToolType.SUBAGENT: "Subagente falhou",
        }
        return fallback_errors.get(tool_type, "Ferramenta falhou")

    if status == ToolStatus.WAITING_APPROVAL:
        fallback_approvals = {
            ToolType.COMMAND_EXECUTION: "Aprovação pendente: comando",
            ToolType.FILE_READ: "Aprovação pendente: ler arquivo",
            ToolType.FILE_CHANGE: "Aprovação pendente: alterar arquivo",
            ToolType.WEB_SEARCH: "Aprovação pendente: pesquisa web",
            ToolType.MCP_TOOL_CALL: "Aprovação pendente: ferramenta MCP",
            ToolType.BROWSER: "Aprovação pendente: navegação",
            ToolType.SUBAGENT: "Aprovação pendente: subagente",
        }
        return fallback_approvals.get(tool_type, "Aprovação pendente")

    fallback_names = {
        ToolType.COMMAND_EXECUTION: "Executar comando",
        ToolType.FILE_READ: "Ler arquivo",
        ToolType.FILE_CHANGE: "Alterar arquivo",
        ToolType.WEB_SEARCH: "Pesquisa na web",
        ToolType.MCP_TOOL_CALL: "Ferramenta MCP",
        ToolType.BROWSER: "Navegação",
        ToolType.SUBAGENT: "Subagente",
    }
    return fallback_names.get(tool_type, "Executar ferramenta")


def sanitize_error_summary(raw_error: str | None) -> tuple[str, str]:
    """Split and sanitize error text into (summary, details/stack).
    
    Handles patterns like:
    - Traceback (most recent call last): ... FileNotFoundError: ...
    - null\\nvratacarejo.service.notasaida.NotaSaidaFiscalService... -> ("NullPointerException", full stack)
    - java.lang.NullPointerException: Cannot invoke ... -> ("NullPointerException", full stack)
    """
    if not raw_error:
        return "", ""
    text = str(raw_error).strip()
    if not text:
        return "", ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", ""

    first_line = lines[0]

    # Check for Python traceback: the actual exception is on the final lines
    if first_line.startswith("Traceback (most recent call last)"):
        for line in reversed(lines):
            if any(term in line for term in ("Error", "Exception", "Warning")):
                summary = line.split(":")[0].strip()
                return summary[:120], text
        return lines[-1][:120], text

    # Check if first line is literal "null" followed by Java/Python stack trace
    if first_line.lower() in INVALID_TEXT_VALUES:
        # Check remaining lines for exception name or stack
        for line in lines[1:]:
            if "Exception" in line or "Error" in line:
                parts = line.split(":")
                candidate = parts[0].split(".")[-1].strip()
                if candidate:
                    return candidate, text
        if len(lines) > 1:
            return "NullPointerException", text
        return "Erro desconhecido", text

    # Check for Java fully qualified exception e.g. java.lang.NullPointerException: ...
    if ":" in first_line and ("Exception" in first_line or "Error" in first_line):
        candidate = first_line.split(":")[0].split(".")[-1].strip()
        if candidate:
            return candidate[:120], text

    return first_line[:120], text


MAX_TOOL_OUTPUT_CHARS = 200_000


def _truncate_tool_output(value: Any) -> Any:
    """Bound in-memory/UI retention for very large tool outputs."""
    if not isinstance(value, str):
        return value
    if len(value) <= MAX_TOOL_OUTPUT_CHARS:
        return value
    return "[...truncado...]\n" + value[-MAX_TOOL_OUTPUT_CHARS:]


def coalesce_output(
    curr_output: Any,
    new_output: Any = None,
    delta: Any = None,
    *,
    output_mode: str = "",
    sequence: int = 0,
    current_sequence: int = 0,
) -> Any:
    """Coalesce incoming output chunk or snapshot with current output.

    Explicit ``output_mode`` avoids inferring provider semantics from text:
    - ``"delta"``: incremental chunk, always appended literally
      (``"A"`` + ``"A"`` -> ``"AA"``).
    - ``"snapshot"``: cumulative buffer, newest authoritative value replaces
      progressive or divergent buffers; duplicate maintains value; out-of-order
      stale sequence ignored when sequence information is available.
    - ``""`` (legacy): heuristic parity with T3Code streaming & coalescing:
      delta stream ("A", "B", "C") -> "ABC";
      snapshot stream ("A", "AB", "ABC") -> "ABC";
      duplicate snapshots ("A", "A", "AB") -> "AB";
      cumulative snapshot in delta field does not repeat ("ABC", never "AABABC").
    Handles string, dict/list (MCP/JSON payloads), and None seamlessly.
    """
    mode = str(output_mode or "").strip().lower()
    if mode == "delta":
        candidate = delta if delta is not None else new_output
        if candidate is not None and candidate != "":
            delta_str = str(candidate)
            if curr_output is None or curr_output == "":
                return delta_str
            return str(curr_output) + delta_str
        return curr_output

    if mode == "snapshot":
        if sequence > 0 and current_sequence > 0 and sequence < current_sequence:
            return curr_output
        candidate = new_output if new_output is not None else delta
        if candidate is not None:
            if curr_output is None or curr_output == "":
                return candidate
            if curr_output == candidate:
                return curr_output
            # In explicit snapshot mode, newest buffer is authoritative:
            # progressive replaces ("A" -> "AB" -> "ABC"),
            # divergent replaces ("phase 1" -> "final result"),
            # never concatenate or use text heuristics.
            return candidate
        return curr_output

    if delta is not None and delta != "":
        delta_str = str(delta)
        if curr_output is None or curr_output == "":
            return delta_str
        curr_str = str(curr_output)
        if delta_str == curr_str:
            return curr_str
        if delta_str.startswith(curr_str):
            # Cumulative buffer sent via delta field
            return delta_str
        if curr_str.startswith(delta_str) and len(curr_str) >= len(delta_str):
            # Stale or duplicate delta chunk
            return curr_str
        return curr_str + delta_str

    if new_output is not None:
        if curr_output is None or curr_output == "":
            return new_output
        if curr_output == new_output:
            return curr_output
        if isinstance(curr_output, str) and isinstance(new_output, str):
            if new_output.startswith(curr_output):
                # Progressive cumulative snapshot
                return new_output
            if curr_output.startswith(new_output):
                # Out-of-order older snapshot
                return curr_output
            # Disjoint chunk sent via output field instead of delta
            return curr_output + new_output
        return new_output

    return curr_output


@dataclass
class ToolActivity:
    id: str
    provider: str = ""
    conversation_id: str = ""
    turn_id: str = ""
    execution_id: str | int = ""
    type: ToolType = ToolType.UNKNOWN
    name: str = ""
    title: str = ""
    status: ToolStatus = ToolStatus.PENDING
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    input: Any = None
    input_preview: str = ""
    output: Any = None
    output_preview: str = ""
    error: str = ""
    error_details: str = ""
    command: str = ""
    cwd: str = ""
    exit_code: int | None = None
    files: list[str] = field(default_factory=list)
    locations: list[dict[str, Any]] = field(default_factory=list)
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    _explicit_duration_ms: int | None = None

    @property
    def tool_id(self) -> str:
        return self.id

    def is_terminal(self) -> bool:
        return self.status.is_terminal

    def duration_ms(self) -> int | None:
        if self._explicit_duration_ms is not None:
            return self._explicit_duration_ms
        if not self.started_at:
            return None
        end_str = self.finished_at or self.updated_at
        if not end_str:
            return None
        try:
            t0 = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            diff = int((t1 - t0).total_seconds() * 1000)
            return max(0, diff)
        except Exception:
            return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["type"] = self.type.value
        data["duration_ms"] = self.duration_ms()
        data["is_terminal"] = self.is_terminal()
        return data

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ToolActivity:
        data = dict(d)
        data.pop("duration_ms", None)
        data.pop("is_terminal", None)
        if "status" in data and isinstance(data["status"], str):
            try:
                data["status"] = ToolStatus(data["status"])
            except ValueError:
                data["status"] = ToolStatus.PENDING
        if "type" in data and isinstance(data["type"], str):
            data["type"] = ToolType.from_string(data["type"])
        return cls(**data)


@dataclass
class NormalizedToolEvent:
    tool_id: str
    kind: ToolEventKind
    event_id: str = ""
    provider: str = ""
    conversation_id: str = ""
    turn_id: str = ""
    execution_id: str | int = ""
    type: ToolType = ToolType.UNKNOWN
    name: str = ""
    title: str = ""
    status: ToolStatus | None = None
    timestamp: str = field(default_factory=utc_now)
    sequence: int = 0
    input: Any = None
    input_preview: str = ""
    output: Any = None
    output_preview: str = ""
    delta: Any = None
    output_mode: str = ""  # "delta" | "snapshot" | "" (legacy heuristic)
    error: str = ""
    error_details: str = ""
    command: str = ""
    cwd: str = ""
    exit_code: int | None = None
    files: list[str] = field(default_factory=list)
    locations: list[dict[str, Any]] = field(default_factory=list)
    approved: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def payload_digest(self) -> str:
        """Deterministic fingerprint for deduplicating identical events missing event_id."""
        raw = (
            f"{self.kind.value}:{self.tool_id}:{self.status}:{self.sequence}:"
            f"{self.output}:{self.delta}:{self.output_mode}:{self.error}:{self.exit_code}"
        )
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


GENERIC_TOOL_IDS = {"", "tool", "unknown", "item", "none", "null", "undefined"}


def is_generic_tool_id(tool_id: str | None) -> bool:
    return str(tool_id or "").strip().lower() in GENERIC_TOOL_IDS


class ToolLifecycleReducer:
    """Central lifecycle reducer and coalescer for tool calls.
    
    Transforms stream of NormalizedToolEvents into stable, monotonic ToolActivity states.
    Ensures:
    - Stable identity per tool call
    - Monotonic terminal state transitions (success, failure, cancelled, interrupted cannot revert to running)
    - Rejection of out-of-order and stale updates
    - Independent tracking of concurrent/parallel tools
    - Seamless handling of snapshot vs delta outputs without duplication
    - Strict idempotency (event_id > sequence > digest)
    - Title and error sanitization
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolActivity] = {}
        self._tool_order: list[str] = []
        self._processed_event_ids: set[str] = set()
        self._processed_digests: set[str] = set()
        self._processed_sequences: set[tuple[str, int]] = set()
        self._processed_provider_sequences: set[tuple[str, str, int]] = set()
        self._event_to_tool: dict[str, str] = {}
        self._digest_to_tool: dict[str, str] = {}
        self._sequence_to_tool: dict[tuple[str, str, int], str] = {}
        self._anon_counter: int = 0

    def _mint_anonymous_id(self, event: NormalizedToolEvent) -> str:
        """Mint an ephemeral unique identity for tools without stable provider ID.

        Never reuses a shared fixed identity like "tool"/"unknown"/"item".
        Prefers stable event info (execution_id, runtime_event_id, event_id,
        request_id, sequence) so retries with the same event_id stay idempotent,
        while distinct anonymous tools never coalesce.
        """
        self._anon_counter += 1
        exec_part = str(event.execution_id or "").strip() or "exec"
        meta = event.metadata if isinstance(event.metadata, dict) else {}
        runtime_hint = str(
            meta.get("runtime_event_id")
            or meta.get("runtimeEventId")
            or meta.get("request_id")
            or meta.get("requestId")
            or ""
        ).strip()
        event_hint = str(event.event_id or "").strip()
        # Deterministic when a stable per-event hint exists (retry dedupe);
        # otherwise suffix a monotonic counter to guarantee distinctness.
        if event_hint:
            return f"anon:{exec_part}:{event_hint}"
        if runtime_hint:
            return f"anon:{exec_part}:{runtime_hint}:{self._anon_counter}"
        if event.sequence:
            return f"anon:{exec_part}:seq{event.sequence}:{self._anon_counter}"
        return f"anon:{exec_part}:noid:{self._anon_counter}"

    @property
    def activities(self) -> dict[str, ToolActivity]:
        return self._tools

    @property
    def tools(self) -> dict[str, ToolActivity]:
        return self._tools

    def reduce(self, event: NormalizedToolEvent) -> ToolActivity:
        # TC-05: never coalesce tools without a stable provider identity.
        if is_generic_tool_id(event.tool_id):
            event.tool_id = self._mint_anonymous_id(event)

        has_event_id = bool(event.event_id and str(event.event_id).strip())
        has_sequence = bool(event.sequence and event.sequence > 0)

        # 1. Idempotency by event_id (highest priority, exclusive).
        # When an explicit event_id exists, sequence must not participate
        # in the dedup decision: a new event_id with a repeated sequence
        # is a legitimate new event, while a repeated event_id with a
        # different sequence is still a retry.
        if has_event_id:
            if event.event_id in self._processed_event_ids:
                logger.debug("Duplicate event_id ignored: %s (tool_id=%s)", event.event_id, event.tool_id)
                mapped = self._event_to_tool.get(event.event_id)
                if mapped is not None and mapped in self._tools:
                    return self._tools[mapped]
                if event.tool_id in self._tools:
                    return self._tools[event.tool_id]
            # Explicit identity present: skip sequence/digest dedup entirely.
        elif has_sequence:
            # 2. Idempotency by sequence only without event_id.
            # Keyed by the full (provider, tool_id, sequence) triple via
            # _processed_provider_sequences only. The legacy (tool_id,
            # sequence) key without provider must never block an event.
            provider = str(event.provider or "").strip().lower()
            provider_seq_key = (provider, event.tool_id, event.sequence)
            if provider_seq_key in self._processed_provider_sequences:
                logger.debug(
                    "Duplicate sequence ignored: provider=%s tool_id=%s seq=%d",
                    provider,
                    event.tool_id,
                    event.sequence,
                )
                mapped = self._sequence_to_tool.get(provider_seq_key)
                if mapped is not None and mapped in self._tools:
                    return self._tools[mapped]
                if event.tool_id in self._tools:
                    return self._tools[event.tool_id]
        else:
            digest = event.payload_digest()
            # 3. Digest fallback only without event_id and without usable
            # sequence. Explicit delta chunks must append literally even
            # when textually equal ("A"+"A" -> "AA"); only
            # snapshot/legacy payloads use digest heuristics.
            is_explicit_delta = str(getattr(event, "output_mode", "") or "").lower() == "delta"
            if not is_explicit_delta and digest in self._processed_digests:
                logger.debug("Duplicate event digest ignored: %s (tool_id=%s)", digest, event.tool_id)
                mapped = self._digest_to_tool.get(digest)
                if mapped is not None and mapped in self._tools:
                    return self._tools[mapped]
                if event.tool_id in self._tools:
                    return self._tools[event.tool_id]

        provider = str(event.provider or "").strip().lower()
        provider_seq_key = (provider, event.tool_id, event.sequence)
        digest = event.payload_digest()

        # 2. Retrieve or initialize tool activity
        tool = self._tools.get(event.tool_id)
        if tool is None:
            tool = ToolActivity(
                id=event.tool_id,
                provider=event.provider,
                conversation_id=event.conversation_id,
                turn_id=str(event.turn_id or ""),
                execution_id=event.execution_id or "",
                type=event.type or ToolType.UNKNOWN,
                name=event.name or "",
                title=event.title or "",
                status=ToolStatus.PENDING,
                started_at="",
                updated_at=event.timestamp or utc_now(),
                sequence=event.sequence,
                metadata=dict(event.metadata or {}),
            )
            self._tools[event.tool_id] = tool
            self._tool_order.append(event.tool_id)
        else:
            # 3. Out-of-order / Stale Sequence Protection
            if event.sequence > 0 and tool.sequence > 0 and event.sequence < tool.sequence:
                logger.warning(
                    "Stale sequence ignored for tool %s: incoming sequence %d < current %d",
                    tool.id,
                    event.sequence,
                    tool.sequence,
                )
                return tool

            # 4. Monotonic Terminal State Invariant + terminal enrichment
            # Once in a terminal status, tool cannot regress or have its terminal status mutated,
            # but diagnostic data may still be enriched monotonically (TC-03).
            if tool.is_terminal():
                if event.error_details:
                    if not tool.error_details:
                        tool.error_details = event.error_details
                    elif event.error_details != tool.error_details and len(str(event.error_details)) > len(str(tool.error_details)):
                        tool.error_details = event.error_details
                if event.error:
                    summary, details = sanitize_error_summary(event.error)
                    if summary and summary != tool.error:
                        # Prefer a more informative summary when available.
                        if not tool.error or len(summary) > len(str(tool.error)):
                            tool.error = summary
                    if details and details != tool.error_details:
                        if not tool.error_details or len(str(details)) > len(str(tool.error_details)):
                            tool.error_details = details
                # Terminal output enrichment: allow authoritative snapshots /
                # terminal diagnostics to complete the record, but ignore stale
                # incremental deltas after terminal (late provider chunks must
                # not append to a completed/cancelled card).
                if event.output is not None:
                    merged = coalesce_output(
                        tool.output,
                        new_output=event.output,
                        delta=None,
                        output_mode=getattr(event, "output_mode", "") or "snapshot",
                        sequence=event.sequence,
                        current_sequence=tool.sequence,
                    )
                    if merged != tool.output:
                        tool.output = _truncate_tool_output(merged)
                if event.exit_code is not None:
                    tool.exit_code = event.exit_code
                if event.metadata:
                    tool.metadata.update(event.metadata)
                if event.files:
                    for f in event.files:
                        if f and f not in tool.files:
                            tool.files.append(f)
                if event.locations:
                    tool.locations.extend(event.locations)
                if event.event_id:
                    self._processed_event_ids.add(event.event_id)
                    self._event_to_tool[event.event_id] = tool.id
                if event.sequence > 0:
                    # Legacy _processed_sequences is intentionally not updated:
                    # sequence identity is keyed only by (provider, tool, seq).
                    self._processed_provider_sequences.add(provider_seq_key)
                    self._sequence_to_tool[provider_seq_key] = tool.id
                self._processed_digests.add(digest)
                self._digest_to_tool[digest] = tool.id
                logger.info(
                    "Ignored event %s for tool %s already in terminal status %s",
                    event.kind,
                    tool.id,
                    tool.status,
                )
                return tool

        # 5. Metadata and identity enrichment
        if event.provider and not tool.provider:
            tool.provider = event.provider
        if event.conversation_id and not tool.conversation_id:
            tool.conversation_id = event.conversation_id
        if event.turn_id and not tool.turn_id:
            tool.turn_id = str(event.turn_id)
        if event.execution_id and not tool.execution_id:
            tool.execution_id = event.execution_id
        if event.type and event.type != ToolType.UNKNOWN:
            tool.type = event.type
        if event.name and not tool.name:
            tool.name = event.name
        if event.command and not tool.command:
            tool.command = event.command
        if event.cwd and not tool.cwd:
            tool.cwd = event.cwd
        if event.exit_code is not None:
            tool.exit_code = event.exit_code
        prev_sequence = tool.sequence
        if event.sequence > tool.sequence:
            tool.sequence = event.sequence
        if event.metadata:
            tool.metadata.update(event.metadata)

        # 6. Input merging
        if event.input is not None and tool.input is None:
            tool.input = event.input
        if event.input_preview and not tool.input_preview:
            tool.input_preview = event.input_preview

        # 7. Output merging: explicit delta vs snapshot semantics (no textual inference)
        tool.output = _truncate_tool_output(
            coalesce_output(
                tool.output,
                new_output=event.output,
                delta=event.delta,
                output_mode=getattr(event, "output_mode", "") or "",
                sequence=event.sequence,
                current_sequence=prev_sequence,
            )
        )

        if event.output_preview:
            tool.output_preview = event.output_preview

        # 8. Files and locations merging (deduplicated)
        if event.files:
            for f in event.files:
                if f and f not in tool.files:
                    tool.files.append(f)
        if event.locations:
            tool.locations.extend(event.locations)

        # 9. Status transition resolution
        new_status = tool.status
        if event.kind == ToolEventKind.STARTED:
            if not tool.is_terminal():
                new_status = ToolStatus.RUNNING
                if not tool.started_at:
                    tool.started_at = event.timestamp or utc_now()
        elif event.kind == ToolEventKind.APPROVAL_REQUESTED:
            if not tool.is_terminal():
                new_status = ToolStatus.WAITING_APPROVAL
        elif event.kind == ToolEventKind.APPROVAL_RESOLVED:
            if not tool.is_terminal():
                is_approved = event.approved if event.approved is not None else event.metadata.get("approved")
                if is_approved is True:
                    new_status = ToolStatus.RUNNING
                    if not tool.started_at:
                        tool.started_at = event.timestamp or utc_now()
                elif is_approved is False:
                    new_status = ToolStatus.CANCELLED
                    tool.metadata["denied"] = True
                    tool.finished_at = event.timestamp or utc_now()
        elif event.kind == ToolEventKind.COMPLETED:
            if not tool.is_terminal():
                new_status = ToolStatus.SUCCESS
                tool.finished_at = event.timestamp or utc_now()
        elif event.kind == ToolEventKind.FAILED:
            if not tool.is_terminal():
                new_status = ToolStatus.FAILURE
                tool.finished_at = event.timestamp or utc_now()
        elif event.kind == ToolEventKind.CANCELLED:
            if not tool.is_terminal():
                new_status = ToolStatus.CANCELLED
                tool.finished_at = event.timestamp or utc_now()
        elif event.kind == ToolEventKind.UPDATED:
            if event.status is not None and not tool.is_terminal():
                new_status = event.status
                if new_status.is_terminal:
                    tool.finished_at = event.timestamp or utc_now()
                elif new_status == ToolStatus.RUNNING and not tool.started_at:
                    tool.started_at = event.timestamp or utc_now()

        # Update status
        tool.status = new_status
        tool.updated_at = event.timestamp or utc_now()

        # 10. Error handling and sanitization (Section 14 & 15)
        raw_error = event.error or tool.error
        raw_error_details = event.error_details or tool.error_details
        if raw_error:
            summary, details = sanitize_error_summary(raw_error)
            tool.error = summary
            if details and not raw_error_details:
                tool.error_details = details
        if raw_error_details and not tool.error_details:
            tool.error_details = raw_error_details

        # TC-03: UPDATED + exit_code != 0 must NOT terminalize on its own.
        # Lifecycle follows only canonical terminal events (FAILED/COMPLETED/
        # CANCELLED/APPROVAL_RESOLVED denied). exit_code is stored for
        # diagnostics (section 5 above) without forcing a terminal status.

        # Sanitize title
        tool.title = sanitize_title(
            title=event.title or tool.title,
            name=tool.name,
            tool_type=tool.type,
            status=tool.status,
            error=tool.error,
        )

        # 11. Mark event as processed
        if event.event_id:
            self._processed_event_ids.add(event.event_id)
            self._event_to_tool[event.event_id] = tool.id
        if event.sequence > 0:
            # Legacy _processed_sequences is intentionally not updated.
            self._processed_provider_sequences.add(provider_seq_key)
            self._sequence_to_tool[provider_seq_key] = tool.id
        self._processed_digests.add(digest)
        self._digest_to_tool[digest] = tool.id

        return tool

    def get_tool(self, tool_id: str) -> ToolActivity | None:
        return self._tools.get(tool_id)

    def get_all_tools(self) -> list[ToolActivity]:
        return [self._tools[tid] for tid in self._tool_order if tid in self._tools]

    def get_active_tools(self) -> list[ToolActivity]:
        return [
            tool for tool in self.get_all_tools()
            if tool.status in {ToolStatus.RUNNING, ToolStatus.WAITING_APPROVAL, ToolStatus.PENDING}
        ]

    def cancel_all_running(self, finished_at: str | None = None) -> list[ToolActivity]:
        """Cancel all running or pending tools (e.g. on user turn cancellation)."""
        cancelled: list[ToolActivity] = []
        end_time = finished_at or utc_now()
        for tool in self.get_all_tools():
            if not tool.is_terminal():
                tool.status = ToolStatus.CANCELLED
                tool.finished_at = end_time
                tool.updated_at = end_time
                cancelled.append(tool)
                logger.info("Cancelled running tool on turn cancellation: %s", tool.id)
        return cancelled

    def finalize_turn(
        self,
        turn_terminal_status: ToolStatus = ToolStatus.INTERRUPTED,
        finished_at: str | None = None,
    ) -> list[ToolActivity]:
        """Ensure no tool remains in 'running' or 'pending' when a turn finishes without explicit tool event.
        
        Prevents blindly marking running tools as success (Section 5 & 29).
        """
        finalized: list[ToolActivity] = []
        end_time = finished_at or utc_now()
        for tool in self.get_all_tools():
            if not tool.is_terminal():
                tool.status = turn_terminal_status
                tool.finished_at = end_time
                tool.updated_at = end_time
                if turn_terminal_status == ToolStatus.INTERRUPTED and not tool.error:
                    tool.error = "Interrompido antes da conclusão"
                elif turn_terminal_status == ToolStatus.CANCELLED and not tool.error:
                    tool.error = "Cancelado pelo usuário"
                tool.title = sanitize_title(
                    tool.title, tool.name, tool.type, tool.status, error=tool.error
                )
                finalized.append(tool)
                logger.warning(
                    "Tool %s was still active at turn completion; marked as %s",
                    tool.id,
                    turn_terminal_status.value,
                )
        return finalized

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": [self._tools[tid].to_dict() for tid in self._tool_order if tid in self._tools],
            "processed_event_ids": list(self._processed_event_ids),
            "processed_digests": list(self._processed_digests),
            "processed_sequences": [list(item) for item in self._processed_sequences],
            "processed_provider_sequences": [list(item) for item in self._processed_provider_sequences],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolLifecycleReducer:
        reducer = cls()
        for tool_dict in data.get("tools", []):
            tool = ToolActivity.from_dict(tool_dict)
            reducer._tools[tool.id] = tool
            reducer._tool_order.append(tool.id)
        reducer._processed_event_ids = set(data.get("processed_event_ids", []))
        reducer._processed_digests = set(data.get("processed_digests", []))
        # Legacy compat: accept old payloads with processed_sequences but
        # never consult _processed_sequences in reduce() again.
        reducer._processed_sequences = {tuple(x) for x in data.get("processed_sequences", [])}
        reducer._processed_provider_sequences = {tuple(x) for x in data.get("processed_provider_sequences", [])}
        return reducer

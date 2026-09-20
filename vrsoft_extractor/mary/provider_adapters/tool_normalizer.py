"""Provider adapter normalizers for tool events.

Transforms heterogeneous event structures from:
- Codex
- Antigravity
- OpenCode
- Claude (legacy fallback)
into canonical NormalizedToolEvent instances.
"""
from __future__ import annotations

import logging
from typing import Any

from ..models import RuntimeEvent
from ..tool_activity import (
    NormalizedToolEvent,
    ToolEventKind,
    ToolStatus,
    ToolType,
    sanitize_title,
)

logger = logging.getLogger("mary.tool_normalizer")


def _extract_event_id(*containers: Any) -> str:
    """Extract explicit event identity from heterogeneous provider payloads."""
    for c in containers:
        if not isinstance(c, dict):
            continue
        for key in ("event_id", "eventId", "update_id", "updateId"):
            val = c.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ""


def _extract_sequence(*containers: Any, provider: str = "") -> int:
    """Extract monotonic provider sequence from heterogeneous payloads.

    Only explicit ``sequence``/``seq`` keys represent a monotonic provider
    sequence. ``index``/``output_index`` are positional hints that stay in
    the original metadata but must never drive idempotency or stale checks.
    """
    allowed_keys = ("sequence", "seq")

    for c in containers:
        if not isinstance(c, dict):
            continue
        for key in allowed_keys:
            val = c.get(key)
            if val is None or val == "":
                continue
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    return 0


def normalize_codex_event(
    params: dict[str, Any],
    method: str,
    conversation_id: str = "",
) -> NormalizedToolEvent | None:
    """Normalize Codex RPC notifications into a NormalizedToolEvent."""
    item = params.get("item") if isinstance(params.get("item"), dict) else {}
    event_id = _extract_event_id(params, item)
    sequence = _extract_sequence(params, item, provider="codex")

    if method == "item/started":
        item_id = str(item.get("id") or "")
        item_type = str(item.get("type") or "")
        if item_type in {"agentMessage", "userMessage", "reasoning", "thinking"}:
            return None

        tool_type = ToolType.from_string(item_type)
        command = item.get("command")
        command_str = (
            " ".join(command) if isinstance(command, list) else str(command or "")
        )
        cwd = str(item.get("cwd") or "")
        files: list[str] = []
        if item_type == "fileChange":
            for c in item.get("changes") or []:
                if isinstance(c, dict) and c.get("path"):
                    files.append(str(c["path"]))
        elif item_type == "fileRead":
            path = item.get("path") or item.get("file")
            if path:
                files.append(str(path))

        name = str(item.get("name") or command_str or item_type)
        raw_title = item.get("title")
        title = sanitize_title(raw_title, name, tool_type, ToolStatus.RUNNING)

        return NormalizedToolEvent(
            tool_id=item_id,
            kind=ToolEventKind.STARTED,
            event_id=event_id,
            sequence=sequence,
            provider="codex",
            conversation_id=conversation_id,
            type=tool_type,
            name=name,
            title=title,
            command=command_str,
            cwd=cwd,
            files=files,
            input=item.get("input") or item.get("arguments"),
            metadata=dict(params),
        )

    if method == "item/completed":
        item = params.get("item") or {}
        item_id = str(item.get("id") or "")
        item_type = str(item.get("type") or "")
        if item_type in {"agentMessage", "userMessage", "reasoning", "thinking"}:
            return None

        tool_type = ToolType.from_string(item_type)
        status_raw = str(item.get("status") or "").lower()
        exit_code = item.get("exitCode")
        if exit_code is None:
            exit_code = item.get("exit_code")
        error = str(item.get("error") or "")

        output = item.get("output")
        if output is None:
            stdout = str(item.get("stdout") or "")
            stderr = str(item.get("stderr") or "")
            if stdout or stderr:
                output = stdout + (("\n" + stderr) if stderr else "")

        is_failure = (
            status_raw in {"error", "failed"}
            or (exit_code is not None and exit_code != 0)
            or bool(error)
        )
        kind = ToolEventKind.FAILED if is_failure else ToolEventKind.COMPLETED
        tool_status = ToolStatus.FAILURE if is_failure else ToolStatus.SUCCESS

        raw_title = item.get("title")
        name = str(item.get("name") or item_type)
        title = sanitize_title(raw_title, name, tool_type, tool_status, error=error)

        return NormalizedToolEvent(
            tool_id=item_id,
            kind=kind,
            event_id=event_id,
            sequence=sequence,
            provider="codex",
            conversation_id=conversation_id,
            type=tool_type,
            name=name,
            title=title,
            output=output,
            output_mode="snapshot" if output is not None else "",
            error=error,
            exit_code=exit_code,
            metadata=dict(params),
        )

    if method == "item/fileChange/patchUpdated":
        item_id = str(params.get("itemId") or params.get("item_id") or "")
        changes = list(params.get("changes") or [])
        files = [
            str(c.get("path"))
            for c in changes
            if isinstance(c, dict) and c.get("path")
        ]
        return NormalizedToolEvent(
            tool_id=item_id,
            kind=ToolEventKind.UPDATED,
            event_id=event_id,
            sequence=sequence,
            provider="codex",
            conversation_id=conversation_id,
            type=ToolType.FILE_CHANGE,
            files=files,
            delta=changes,
            metadata=dict(params),
        )

    if method in {"item/commandExecution/outputDelta", "item/outputDelta"}:
        item_id = str(params.get("itemId") or params.get("item_id") or "")
        delta = params.get("delta") or params.get("outputDelta") or params.get("output")
        return NormalizedToolEvent(
            tool_id=item_id,
            kind=ToolEventKind.UPDATED,
            event_id=event_id,
            sequence=sequence,
            provider="codex",
            conversation_id=conversation_id,
            type=ToolType.COMMAND_EXECUTION if "commandExecution" in method else ToolType.UNKNOWN,
            delta=delta,
            output_mode="delta" if delta is not None else "",
            metadata=dict(params),
        )

    if method == "item/updated":
        item = params.get("item") or {}
        item_id = str(item.get("id") or params.get("itemId") or params.get("item_id") or "")
        item_type = str(item.get("type") or "")
        tool_type = ToolType.from_string(item_type) if item_type else ToolType.UNKNOWN
        output = item.get("output")
        delta = params.get("delta") or item.get("delta")
        exit_code = item.get("exitCode") or item.get("exit_code")
        error = str(item.get("error") or "")
        if delta is not None and output is None:
            output_mode = "delta"
        elif output is not None:
            output_mode = "snapshot"
        else:
            output_mode = ""
        return NormalizedToolEvent(
            tool_id=item_id,
            kind=ToolEventKind.UPDATED,
            event_id=event_id,
            sequence=sequence,
            provider="codex",
            conversation_id=conversation_id,
            type=tool_type,
            output=output,
            delta=delta,
            output_mode=output_mode,
            exit_code=exit_code,
            error=error,
            metadata=dict(params),
        )

    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "mcpServer/elicitation/request",
    }:
        req_id = str(params.get("request_id") or params.get("id") or "")
        command = str(params.get("command") or "")
        reason = str(params.get("reason") or command or method)
        tool_type = (
            ToolType.COMMAND_EXECUTION
            if "commandExecution" in method
            else (ToolType.FILE_CHANGE if "fileChange" in method else ToolType.UNKNOWN)
        )
        return NormalizedToolEvent(
            tool_id=req_id,
            kind=ToolEventKind.APPROVAL_REQUESTED,
            event_id=event_id,
            sequence=sequence,
            provider="codex",
            conversation_id=conversation_id,
            type=tool_type,
            command=command,
            title=reason,
            metadata=dict(params),
        )

    return None


def normalize_antigravity_event(
    params: dict[str, Any],
    method: str,
    conversation_id: str = "",
) -> NormalizedToolEvent | None:
    """Normalize Antigravity ACP/SSE session updates into a NormalizedToolEvent."""
    update = params.get("update") or {}
    if not isinstance(update, dict):
        return None
    session_update = update.get("sessionUpdate")

    if session_update in ("tool_call", "tool_call_update"):
        tool_call = update.get("toolCall") or {}
        if not isinstance(tool_call, dict):
            tool_call = {}

        def field(name: str) -> Any:
            value = update.get(name)
            return value if value is not None else tool_call.get(name)

        def first_legacy(*names: str) -> Any:
            for name in names:
                value = tool_call.get(name)
                if value is not None:
                    return value
            return None

        event_id = _extract_event_id(params, update, tool_call)
        sequence = _extract_sequence(params, update, tool_call, provider="antigravity")
        call_id = str(
            update.get("toolCallId")
            or tool_call.get("toolCallId")
            or tool_call.get("id")
            or ""
        )

        title_value = field("title")
        kind_value = field("kind")
        has_top_level_kind = update.get("kind") is not None
        name_value = field("name")
        raw_name = str(name_value or title_value or kind_value or "")

        acp_kind = str(kind_value or "").strip().lower()
        acp_types = {
            "execute": ToolType.COMMAND_EXECUTION,
            "edit": ToolType.FILE_CHANGE,
            "delete": ToolType.FILE_CHANGE,
            "move": ToolType.FILE_CHANGE,
            "search": ToolType.WEB_SEARCH,
            "fetch": ToolType.WEB_SEARCH,
        }
        tool_type = acp_types.get(acp_kind, ToolType.UNKNOWN)
        if tool_type == ToolType.UNKNOWN and not has_top_level_kind:
            for legacy_type in (
                tool_call.get("kind"),
                tool_call.get("name"),
                tool_call.get("title"),
            ):
                candidate = ToolType.from_string(str(legacy_type or ""))
                if candidate != ToolType.UNKNOWN:
                    tool_type = candidate
                    break

        raw_input = field("rawInput")
        args = raw_input if raw_input is not None else first_legacy(
            "arguments", "args", "input"
        )
        command_str = ""
        if isinstance(args, dict):
            command = (
                args.get("CommandLine")
                or args.get("command")
                or args.get("command_line")
                or args.get("commandLine")
            )
            if command is not None:
                command_str = (
                    " ".join(str(part) for part in command)
                    if isinstance(command, list)
                    else str(command)
                )
            elif args.get("executable"):
                command_parts = [str(args["executable"])]
                command_args = args.get("args")
                if isinstance(command_args, (list, tuple)):
                    command_parts.extend(str(part) for part in command_args)
                elif command_args is not None:
                    command_parts.append(str(command_args))
                command_str = " ".join(command_parts)
        elif isinstance(args, str):
            command_str = args

        raw_output = field("rawOutput")
        output = None
        if isinstance(raw_output, dict):
            for output_key in ("combinedOutput", "combined_output"):
                if raw_output.get(output_key) is not None:
                    output = raw_output[output_key]
                    break
            if output is None:
                stdout = raw_output.get("stdout")
                stderr = raw_output.get("stderr")
                if stdout is not None or stderr is not None:
                    chunks = [str(chunk) for chunk in (stdout, stderr) if chunk not in (None, "")]
                    output = "\n".join(chunks)
            if output is None:
                for output_key in ("output", "content"):
                    if raw_output.get(output_key) is not None:
                        output = raw_output[output_key]
                        break
        elif raw_output is not None:
            output = raw_output

        content = field("content")
        if output is None and content is not None:
            output = content
        if output is None:
            output = first_legacy("output", "result")

        # TC-04: tool_call_update must carry real content updates (output /
        # content / result / delta / rawOutput / status), with correct
        # delta vs snapshot semantics. Never emit an empty update with only
        # id/name/input.
        delta = field("delta")
        status_raw = str(field("status") or "").strip()
        error_value = field("error")
        if error_value is None and isinstance(raw_output, dict):
            error_value = raw_output.get("error")
        error_text = str(error_value or "")

        exit_code = None
        if isinstance(raw_output, dict):
            exit_code = raw_output.get("exitCode")
            if exit_code is None:
                exit_code = raw_output.get("exit_code")
        if exit_code is None:
            exit_code = field("exitCode")
        if exit_code is None:
            exit_code = field("exit_code")

        locations_value = field("locations")
        locations = (
            [location for location in locations_value if isinstance(location, dict)]
            if isinstance(locations_value, list)
            else []
        )
        explicit_error = bool(error_text) or bool(field("isError"))
        normalized_status = status_raw.replace("_", "").replace("-", "").lower()
        if explicit_error or normalized_status in {"failed", "error"}:
            event_kind = ToolEventKind.FAILED
            tool_status = ToolStatus.FAILURE
        elif normalized_status in {"completed", "success", "done"}:
            event_kind = ToolEventKind.COMPLETED
            tool_status = ToolStatus.SUCCESS
        elif session_update == "tool_call":
            event_kind = ToolEventKind.STARTED
            tool_status = ToolStatus.RUNNING
        else:
            event_kind = ToolEventKind.UPDATED
            tool_status = ToolStatus.RUNNING

        if session_update == "tool_call_update" and (
            output is None
            and delta is None
            and not status_raw
            and not error_text
            and exit_code is None
            and not locations
        ):
            return None
        if delta is not None and output is None:
            output_mode = "delta"
        elif output is not None:
            output_mode = "snapshot"
        else:
            output_mode = ""
        has_presentation = any(value not in (None, "") for value in (
            title_value, name_value, kind_value
        ))
        title = (
            sanitize_title(
                str(title_value or ""),
                raw_name or ("ferramenta" if session_update == "tool_call" else ""),
                tool_type,
                tool_status,
                error=error_text,
            )
            if session_update == "tool_call" or has_presentation
            else ""
        )
        return NormalizedToolEvent(
            tool_id=call_id,
            kind=event_kind,
            event_id=event_id,
            sequence=sequence,
            provider="antigravity",
            conversation_id=conversation_id,
            type=tool_type,
            name=raw_name,
            title=title,
            status=tool_status,
            command=command_str,
            input=args,
            output=output,
            delta=delta,
            output_mode=output_mode,
            error=error_text,
            exit_code=exit_code,
            locations=locations,
            metadata=dict(params),
        )

    if session_update == "tool_result":
        tool_result = update.get("toolResult") or {}
        if not isinstance(tool_result, dict):
            tool_result = {}
        event_id = _extract_event_id(params, update, tool_result)
        sequence = _extract_sequence(params, update, tool_result, provider="antigravity")
        call_id = str(
            tool_result.get("toolCallId")
            or tool_result.get("id")
            or update.get("toolCallId")
            or ""
        )
        raw_name = str(tool_result.get("name") or tool_result.get("title") or "")
        tool_type = ToolType.from_string(raw_name)
        status_raw = str(
            update.get("status") or tool_result.get("status") or ""
        ).lower()
        is_error = (
            status_raw in ("error", "failed")
            or bool(tool_result.get("isError"))
            or bool(tool_result.get("error"))
        )
        kind = ToolEventKind.FAILED if is_error else ToolEventKind.COMPLETED
        tool_status = ToolStatus.FAILURE if is_error else ToolStatus.SUCCESS

        output = (
            tool_result.get("output")
            or tool_result.get("result")
            or tool_result.get("content")
        )
        error = str(tool_result.get("error") or (output if is_error else ""))
        title = sanitize_title(
            tool_result.get("title"), raw_name, tool_type, tool_status, error=error
        )

        return NormalizedToolEvent(
            tool_id=call_id,
            kind=kind,
            event_id=event_id,
            sequence=sequence,
            provider="antigravity",
            conversation_id=conversation_id,
            type=tool_type,
            name=raw_name,
            title=title,
            output=output,
            output_mode="snapshot" if output is not None else "",
            error=error,
            status=tool_status,
            metadata=dict(params),
        )

    return None


def normalize_opencode_event(
    payload: dict[str, Any],
    conversation_id: str = "",
) -> NormalizedToolEvent | None:
    """Normalize OpenCode CLI/streaming payload into a NormalizedToolEvent.

    Intermediate streaming updates (same callID, partial output) are routed
    to the same tool_event pipeline as started/completed — never dropped.
    """
    kind = str(payload.get("type") or "")
    part = payload.get("part") or {}
    if not isinstance(part, dict):
        part = {}
    kind_lc = kind.lower()
    is_tool_payload = (
        kind == "tool_use"
        or "tool" in part
        or part.get("type") == "tool"
        or ("tool" in kind_lc and isinstance(part, dict) and part)
    )

    if is_tool_payload:
        event_id = _extract_event_id(payload, part)
        sequence = _extract_sequence(payload, part, provider="opencode")
        call_id = str(
            part.get("callID")
            or part.get("id")
            or payload.get("callID")
            or payload.get("id")
            or ""
        )
        tool_name = str(
            part.get("tool")
            or part.get("name")
            or payload.get("tool")
            or "ferramenta"
        )
        tool_type = ToolType.from_string(tool_name)
        state = str(
            part.get("state")
            or part.get("status")
            or payload.get("state")
            or ""
        ).lower()
        input_data = (
            part.get("args")
            if part.get("args") is not None
            else part.get("input")
            if part.get("input") is not None
            else payload.get("args")
        )
        output_data = (
            part.get("output")
            if part.get("output") is not None
            else part.get("result")
            if part.get("result") is not None
            else part.get("content")
            if part.get("content") is not None and isinstance(part.get("content"), str)
            else payload.get("output")
            if payload.get("output") is not None
            else payload.get("result")
            if payload.get("result") is not None
            else None
        )
        delta_data = (
            part.get("delta")
            if part.get("delta") is not None
            else payload.get("delta")
            if payload.get("delta") is not None
            else None
        )
        error_data = str(part.get("error") or payload.get("error") or "")

        command_str = ""
        if tool_type == ToolType.COMMAND_EXECUTION:
            if isinstance(input_data, dict):
                command_str = str(input_data.get("command") or input_data.get("cmd") or "")
            elif isinstance(input_data, str):
                command_str = input_data

        if state in ("completed", "success", "done"):
            event_kind = ToolEventKind.COMPLETED
            status = ToolStatus.SUCCESS
        elif state in ("error", "failed") or bool(error_data):
            event_kind = ToolEventKind.FAILED
            status = ToolStatus.FAILURE
        else:
            event_kind = ToolEventKind.STARTED
            status = ToolStatus.RUNNING

        title = sanitize_title(
            part.get("title") or payload.get("title"),
            tool_name,
            tool_type,
            status,
            error=error_data,
        )

        if delta_data is not None and output_data is None:
            output_mode = "delta"
        elif output_data is not None:
            output_mode = "snapshot"
        else:
            output_mode = ""
        return NormalizedToolEvent(
            tool_id=call_id,
            kind=event_kind,
            event_id=event_id,
            sequence=sequence,
            provider="opencode",
            conversation_id=conversation_id,
            type=tool_type,
            name=tool_name,
            title=title,
            command=command_str,
            input=input_data,
            output=output_data,
            delta=delta_data,
            output_mode=output_mode,
            error=error_data,
            metadata=dict(payload),
        )

    return None


def normalize_claude_event(
    block_or_payload: dict[str, Any],
    conversation_id: str = "",
) -> NormalizedToolEvent | None:
    """Normalize Claude Code CLI tool_use / tool_result blocks."""
    event_id = _extract_event_id(block_or_payload)
    sequence = _extract_sequence(block_or_payload, provider="claude")
    block_type = str(block_or_payload.get("type") or "")
    if block_type == "tool_use":
        tool_id = str(block_or_payload.get("id") or "")
        tool_name = str(block_or_payload.get("name") or "ferramenta")
        tool_type = ToolType.from_string(tool_name)
        input_data = block_or_payload.get("input")
        command_str = ""
        if tool_type == ToolType.COMMAND_EXECUTION and isinstance(input_data, dict):
            command_str = str(input_data.get("command") or "")
        title = sanitize_title(None, tool_name, tool_type, ToolStatus.RUNNING)
        return NormalizedToolEvent(
            tool_id=tool_id,
            kind=ToolEventKind.STARTED,
            event_id=event_id,
            sequence=sequence,
            provider="claude",
            conversation_id=conversation_id,
            type=tool_type,
            name=tool_name,
            title=title,
            command=command_str,
            input=input_data,
            metadata=dict(block_or_payload),
        )

    if block_type == "tool_result":
        tool_id = str(block_or_payload.get("tool_use_id") or "")
        is_error = bool(block_or_payload.get("is_error"))
        content = block_or_payload.get("content")
        kind = ToolEventKind.FAILED if is_error else ToolEventKind.COMPLETED
        tool_status = ToolStatus.FAILURE if is_error else ToolStatus.SUCCESS
        error = str(content) if is_error else ""
        output = content if not is_error else ""
        title = sanitize_title(
            None, "ferramenta", ToolType.UNKNOWN, tool_status, error=error
        )
        return NormalizedToolEvent(
            tool_id=tool_id,
            kind=kind,
            event_id=event_id,
            sequence=sequence,
            provider="claude",
            conversation_id=conversation_id,
            output=output,
            output_mode="snapshot" if output else "",
            error=error,
            title=title,
            status=tool_status,
            metadata=dict(block_or_payload),
        )

    return None


def normalize_generic_event(event: RuntimeEvent) -> NormalizedToolEvent | None:
    """Fallback normalizer for any RuntimeEvent."""
    payload = dict(event.payload or {})
    provider_name = str(payload.get("provider") or "").strip().lower()
    if "canonical_event" in payload and isinstance(payload["canonical_event"], dict):
        d = dict(payload["canonical_event"])
        item = (
            payload.get("item")
            or payload.get("part")
            or payload.get("toolCall")
            or payload.get("toolResult")
            or {}
        )
        if not d.get("event_id"):
            ext_ev_id = _extract_event_id(payload, item)
            if ext_ev_id:
                d["event_id"] = ext_ev_id
        if not d.get("sequence"):
            ext_seq = _extract_sequence(payload, item, provider=provider_name)
            if ext_seq:
                d["sequence"] = ext_seq
        if not d.get("conversation_id") and event.conversation_id:
            d["conversation_id"] = event.conversation_id
        if not d.get("execution_id") and payload.get("execution_id") is not None:
            d["execution_id"] = payload["execution_id"]
        kind = ToolEventKind.from_string(d.pop("kind", None))
        type_ = ToolType.from_string(d.pop("type", None))
        status = ToolStatus(d["status"]) if "status" in d and d["status"] else None
        d.pop("status", None)
        return NormalizedToolEvent(
            kind=kind,
            type=type_,
            status=status,
            **d,
        )

    # Inspect provider or nested item
    if "toolCall" in payload or "toolResult" in payload:
        norm = normalize_antigravity_event(payload, "session/update", event.conversation_id)
        if norm:
            return norm

    item = payload.get("item") or payload.get("part") or payload
    if not isinstance(item, dict):
        return None

    item_type = str(item.get("type") or payload.get("step_type") or "tool")
    if item_type in {"agentMessage", "userMessage", "reasoning", "thinking"}:
        return None

    raw_identity = str(
        item.get("id")
        or payload.get("itemId")
        or payload.get("item_id")
        or payload.get("toolCallId")
        or payload.get("tool_call_id")
        or payload.get("callId")
        or payload.get("callID")
        or ""
    ).strip()
    # TC-05: never reuse a shared fixed identity ("tool"/"unknown"/"item").
    # Prefer stable per-event info (runtime_event_id/request_id) only when no
    # stable tool id exists; the reducer mints a distinct anon id otherwise.
    # Here we keep runtime_event_id/request_id as identity only if they look
    # like a stable tool correlation; otherwise leave empty for the reducer
    # to mint anon:{execution}:{hint} (never "tool").
    if raw_identity and raw_identity.lower() not in {"tool", "unknown", "item", "none", "null", "undefined"}:
        identity = raw_identity
    else:
        stable_hint = str(
            payload.get("runtime_event_id")
            or payload.get("request_id")
            or payload.get("requestId")
            or ""
        ).strip()
        if stable_hint and stable_hint.lower() not in {"tool", "unknown", "item"}:
            # Use execution-scoped ephemeral hint; reducer guarantees
            # distinctness across anonymous tools via counter/digest.
            exec_hint = str(payload.get("execution_id") or "").strip() or "exec"
            identity = f"anon:{exec_hint}:{stable_hint}"
        else:
            identity = ""
    tool_type = ToolType.from_string(item_type or item.get("name"))
    lifecycle = str(payload.get("lifecycle") or "")
    status_raw = str(item.get("status") or payload.get("status") or "").lower()

    is_complete = (
        lifecycle.endswith("completed")
        or status_raw in {"completed", "success"}
    )
    is_failed = (
        lifecycle.endswith("failed")
        or status_raw in {"error", "failed"}
        or payload.get("success") is False
        or bool(item.get("error"))
    )

    delta = item.get("delta") or payload.get("delta")
    has_delta = bool(delta)

    if is_failed:
        kind = ToolEventKind.FAILED
        status = ToolStatus.FAILURE
    elif is_complete:
        kind = ToolEventKind.COMPLETED
        status = ToolStatus.SUCCESS
    elif has_delta or lifecycle.endswith("updated") or status_raw == "updated":
        kind = ToolEventKind.UPDATED
        status = ToolStatus.RUNNING
    else:
        kind = ToolEventKind.STARTED
        status = ToolStatus.RUNNING

    error = str(item.get("error") or payload.get("error") or "")
    raw_name = str(item.get("name") or item.get("tool") or item_type)
    title = sanitize_title(event.text or item.get("title"), raw_name, tool_type, status, error=error)

    output = item.get("output") or payload.get("output")
    input_data = item.get("input") or item.get("arguments") or payload.get("arguments")
    command = str(item.get("command") or payload.get("command") or "")
    cwd = str(item.get("cwd") or payload.get("cwd") or "")
    exit_code_raw = item.get("exit_code") or payload.get("exit_code")
    exit_code = int(exit_code_raw) if exit_code_raw is not None else None
    # Explicit provider event identity prioritized over content heuristics.
    event_id = _extract_event_id(payload, item)
    sequence = _extract_sequence(payload, item, provider=provider_name)
    # Explicit output semantics: incremental delta vs cumulative snapshot.
    # Only providers that declare cumulative snapshots use snapshot coalescing;
    # true deltas always append literally (even when textually equal).
    explicit_mode = str(payload.get("output_mode") or item.get("output_mode") or "")
    if explicit_mode.lower() in {"delta", "snapshot"}:
        output_mode = explicit_mode.lower()
    elif delta is not None and output is None:
        output_mode = "delta"
    elif output is not None:
        output_mode = "snapshot"
    else:
        output_mode = ""

    return NormalizedToolEvent(
        tool_id=identity,
        kind=kind,
        event_id=event_id,
        provider=str(payload.get("provider") or ""),
        conversation_id=event.conversation_id,
        execution_id=payload.get("execution_id", ""),
        type=tool_type,
        name=raw_name,
        title=title,
        command=command,
        cwd=cwd,
        exit_code=exit_code,
        sequence=sequence,
        input=input_data,
        output=output,
        delta=delta,
        output_mode=output_mode,
        error=error,
        metadata=payload,
    )

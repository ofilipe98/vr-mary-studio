"""Unit tests for Provider Adapters tool event normalization (Etapa 3).

Verifies that Codex, Antigravity, OpenCode, and Claude events are cleanly
transformed into canonical NormalizedToolEvents at the adapter boundary,
and feed correctly into ToolLifecycleReducer.
"""

from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.provider_adapters.tool_normalizer import (
    normalize_antigravity_event,
    normalize_claude_event,
    normalize_codex_event,
    normalize_generic_event,
    normalize_opencode_event,
)
from vrsoft_extractor.mary.tool_activity import (
    ToolEventKind,
    ToolLifecycleReducer,
    ToolStatus,
    ToolType,
)


def test_codex_command_execution_started_and_completed():
    started_params = {
        "item": {
            "id": "item_cmd_1",
            "type": "commandExecution",
            "command": ["rg", "calcularImpostoItem", "src/"],
            "cwd": "C:/repo",
        }
    }
    event_start = normalize_codex_event(started_params, "item/started", "conv_123")
    assert event_start is not None
    assert event_start.tool_id == "item_cmd_1"
    assert event_start.kind == ToolEventKind.STARTED
    assert event_start.type == ToolType.COMMAND_EXECUTION
    assert event_start.command == "rg calcularImpostoItem src/"
    assert event_start.cwd == "C:/repo"
    assert event_start.title != "null"
    assert event_start.title != ""

    completed_params = {
        "item": {
            "id": "item_cmd_1",
            "type": "commandExecution",
            "status": "completed",
            "exitCode": 0,
            "output": "Found 3 occurrences",
        }
    }
    event_done = normalize_codex_event(completed_params, "item/completed", "conv_123")
    assert event_done is not None
    assert event_done.tool_id == "item_cmd_1"
    assert event_done.kind == ToolEventKind.COMPLETED
    assert event_done.output == "Found 3 occurrences"
    assert event_done.exit_code == 0

    # Feed into reducer
    reducer = ToolLifecycleReducer()
    tool = reducer.reduce(event_start)
    assert tool.status == ToolStatus.RUNNING
    tool = reducer.reduce(event_done)
    assert tool.status == ToolStatus.SUCCESS
    assert tool.output == "Found 3 occurrences"


def test_codex_command_execution_failure():
    failed_params = {
        "item": {
            "id": "item_cmd_fail",
            "type": "commandExecution",
            "status": "error",
            "exitCode": 1,
            "error": "command not found: nonexistent",
        }
    }
    event_fail = normalize_codex_event(failed_params, "item/completed", "conv_123")
    assert event_fail is not None
    assert event_fail.kind == ToolEventKind.FAILED
    assert event_fail.exit_code == 1
    assert event_fail.error == "command not found: nonexistent"
    assert event_fail.title == "Comando falhou"

    reducer = ToolLifecycleReducer()
    tool = reducer.reduce(event_fail)
    assert tool.status == ToolStatus.FAILURE
    assert tool.error == "command not found: nonexistent"


def test_codex_file_change_and_patch_updated():
    patch_params = {
        "itemId": "item_patch_1",
        "changes": [
            {"path": "src/service.py", "kind": "modify"},
            {"path": "tests/test_service.py", "kind": "create"},
        ],
    }
    event_patch = normalize_codex_event(patch_params, "item/fileChange/patchUpdated", "conv_1")
    assert event_patch is not None
    assert event_patch.tool_id == "item_patch_1"
    assert event_patch.kind == ToolEventKind.UPDATED
    assert event_patch.type == ToolType.FILE_CHANGE
    assert event_patch.files == ["src/service.py", "tests/test_service.py"]


def test_codex_agent_message_is_ignored_by_tool_normalizer():
    params = {
        "item": {
            "id": "msg_1",
            "type": "agentMessage",
            "text": "Hello user",
        }
    }
    assert normalize_codex_event(params, "item/started", "conv_1") is None
    assert normalize_codex_event(params, "item/completed", "conv_1") is None


def test_antigravity_tool_call_and_result():
    call_params = {
        "sessionId": "ses_ag_1",
        "update": {
            "sessionUpdate": "tool_call",
            "toolCall": {
                "toolCallId": "ag_call_1",
                "name": "run_command",
                "arguments": {"CommandLine": "dir", "Cwd": "C:/test"},
            },
        },
    }
    event_start = normalize_antigravity_event(call_params, "session/update", "conv_ag")
    assert event_start is not None
    assert event_start.tool_id == "ag_call_1"
    assert event_start.kind == ToolEventKind.STARTED
    assert event_start.type == ToolType.COMMAND_EXECUTION
    assert event_start.command == "dir"
    assert event_start.title != "null"

    result_params = {
        "sessionId": "ses_ag_1",
        "update": {
            "sessionUpdate": "tool_result",
            "status": "completed",
            "toolResult": {
                "toolCallId": "ag_call_1",
                "output": "Directory contents...",
            },
        },
    }
    event_done = normalize_antigravity_event(result_params, "session/update", "conv_ag")
    assert event_done is not None
    assert event_done.tool_id == "ag_call_1"
    assert event_done.kind == ToolEventKind.COMPLETED
    assert event_done.output == "Directory contents..."

    # Feed into reducer
    reducer = ToolLifecycleReducer()
    reducer.reduce(event_start)
    tool = reducer.reduce(event_done)
    assert tool.status == ToolStatus.SUCCESS
    assert tool.output == "Directory contents..."


def test_antigravity_tool_result_error():
    err_params = {
        "sessionId": "ses_ag_1",
        "update": {
            "sessionUpdate": "tool_result",
            "status": "failed",
            "toolResult": {
                "toolCallId": "ag_err_1",
                "isError": True,
                "error": "Access denied",
            },
        },
    }
    event_err = normalize_antigravity_event(err_params, "session/update", "conv_ag")
    assert event_err is not None
    assert event_err.kind == ToolEventKind.FAILED
    assert event_err.error == "Access denied"


def test_opencode_tool_use_lifecycle():
    # Started
    payload_start = {
        "type": "tool_use",
        "part": {
            "callID": "oc_1",
            "tool": "bash",
            "state": "running",
            "args": {"command": "git status"},
        },
    }
    event_start = normalize_opencode_event(payload_start, "conv_oc")
    assert event_start is not None
    assert event_start.tool_id == "oc_1"
    assert event_start.kind == ToolEventKind.STARTED
    assert event_start.type == ToolType.COMMAND_EXECUTION
    assert event_start.command == "git status"

    # Completed
    payload_done = {
        "type": "tool_use",
        "part": {
            "callID": "oc_1",
            "tool": "bash",
            "state": "completed",
            "output": "On branch dev\nnothing to commit",
        },
    }
    event_done = normalize_opencode_event(payload_done, "conv_oc")
    assert event_done is not None
    assert event_done.tool_id == "oc_1"
    assert event_done.kind == ToolEventKind.COMPLETED
    assert event_done.output == "On branch dev\nnothing to commit"


def test_claude_tool_use_and_result_lifecycle():
    block_use = {
        "type": "tool_use",
        "id": "claude_call_1",
        "name": "Bash",
        "input": {"command": "pytest"},
    }
    event_use = normalize_claude_event(block_use, "conv_cl")
    assert event_use is not None
    assert event_use.tool_id == "claude_call_1"
    assert event_use.kind == ToolEventKind.STARTED
    assert event_use.type == ToolType.COMMAND_EXECUTION

    block_result = {
        "type": "tool_result",
        "tool_use_id": "claude_call_1",
        "content": "10 passed",
        "is_error": False,
    }
    event_res = normalize_claude_event(block_result, "conv_cl")
    assert event_res is not None
    assert event_res.tool_id == "claude_call_1"
    assert event_res.kind == ToolEventKind.COMPLETED
    assert event_res.output == "10 passed"


def test_generic_event_fallback_with_canonical_event():
    canonical = {
        "tool_id": "canon_1",
        "kind": "tool.completed",
        "type": "commandExecution",
        "title": "Executar comando",
        "status": "success",
        "output": "All done",
    }
    runtime_event = RuntimeEvent(
        conversation_id="conv_1",
        kind="tool_event",
        text="Executar comando",
        payload={"canonical_event": canonical},
    )
    norm = normalize_generic_event(runtime_event)
    assert norm is not None
    assert norm.tool_id == "canon_1"
    assert norm.kind == ToolEventKind.COMPLETED
    assert norm.output == "All done"

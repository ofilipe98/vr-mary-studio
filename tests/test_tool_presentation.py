"""Unit tests for Tool Presentation Layer (Etapa 4).

Covers:
- ToolPresentation view model and backward-compatible dict serialization.
- Typed formatters: CommandExecution, FileChange, FileRead, WebSearch, MCP, Browser, Subagent.
- ToolGroupPresentation aggregation and status roll-up logic.
- Sanitization of titles and clean separation of concise error summaries vs full stack traces.
- ToolPresentationRegistry dispatching and format_from_event.
"""

from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.tool_activity import (
    ToolActivity,
    ToolStatus,
    ToolType,
)
from vrsoft_extractor.mary.tool_presentation import (
    DEFAULT_PRESENTATION_REGISTRY,
    CommandExecutionFormatter,
    FileChangeFormatter,
    FileReadFormatter,
    McpToolCallFormatter,
    ToolPresentationRegistry,
    WebSearchFormatter,
    format_duration,
)


def test_format_duration_helper():
    assert format_duration(50) == "50ms"
    assert format_duration(850) == "850ms"
    assert format_duration(1400) == "1.4s"
    assert format_duration(65000) == "1m 5s"


def test_command_execution_formatter_success():
    activity = ToolActivity(
        id="cmd_1",
        conversation_id="conv_1",
        provider="codex",
        type=ToolType.COMMAND_EXECUTION,
        name="rg",
        command="rg calcularImpostoItem src/",
        cwd="C:/repo",
        output="Match on line 42\nMatch on line 88",
        status=ToolStatus.SUCCESS,
        exit_code=0,
        started_at="2026-09-19T10:00:00Z",
        finished_at="2026-09-19T10:00:02Z",
    )
    formatter = CommandExecutionFormatter()
    pres = formatter.format(activity)

    assert pres.tool_id == "cmd_1"
    assert pres.item_type == "commandExecution"
    assert pres.state == "completed"
    assert pres.badge_variant == "success"
    assert pres.icon == "check"
    assert "$ rg calcularImpostoItem src/" in pres.detail
    assert "Cwd: C:/repo" in pres.detail
    assert "Match on line 42" in pres.detail
    assert pres.exit_code == 0
    assert pres.duration_ms == 2000
    assert pres.duration_label == "2.0s"

    # Backward-compatible dict export
    d = pres.to_dict()
    assert d["id"] == "cmd_1"
    assert d["state"] == "completed"
    assert d["itemType"] == "commandExecution"
    assert "rg" in d["text"] or "Executado" in d["text"]


def test_command_execution_formatter_failure_and_error_separation():
    raw_stack_trace = """Traceback (most recent call last):
  File "runner.py", line 12, in <module>
    run_job()
  File "job.py", line 45, in run_job
    raise FileNotFoundError("Arquivo config.json não encontrado")
FileNotFoundError: Arquivo config.json não encontrado"""

    activity = ToolActivity(
        id="cmd_fail",
        conversation_id="conv_1",
        provider="codex",
        type=ToolType.COMMAND_EXECUTION,
        name="python",
        command="python runner.py",
        cwd="C:/repo",
        output="",
        error=raw_stack_trace,
        status=ToolStatus.FAILURE,
        exit_code=1,
    )
    pres = CommandExecutionFormatter().format(activity)

    assert pres.state == "error"
    assert pres.badge_variant == "error"
    assert pres.icon == "close"
    assert pres.exit_code == 1
    # Error summary must be concise, NOT the full stack trace!
    assert "FileNotFoundError" in pres.error_summary
    assert "Traceback" not in pres.error_summary
    # Full stack trace is in error_details and detail pane
    assert "Traceback (most recent call last)" in pres.error_details
    assert "Traceback" in pres.detail
    assert pres.can_expand is True


def test_file_change_formatter():
    activity = ToolActivity(
        id="fc_1",
        conversation_id="conv_1",
        provider="codex",
        type=ToolType.FILE_CHANGE,
        name="patch",
        files=["src/service.py", "tests/test_service.py"],
        metadata={
            "changes": [
                {"path": "src/service.py", "additions": 15, "deletions": 3, "diff": "@@ -1,3 +1,15 @@"},
                {"path": "tests/test_service.py", "additions": 30, "deletions": 0, "diff": "@@ -0,0 +1,30 @@"},
            ]
        },
        status=ToolStatus.SUCCESS,
    )
    pres = FileChangeFormatter().format(activity)

    assert pres.kind == "file_changes"
    assert pres.item_type == "fileChange"
    assert pres.state == "completed"
    assert pres.file_count == 2
    assert pres.additions == 45
    assert pres.deletions == 3
    assert pres.badge_text == "+45 -3"
    assert "src/service.py" in pres.files
    assert "tests/test_service.py" in pres.files
    assert "src, tests" in pres.folder_summary or "src" in pres.folder_summary
    assert pres.has_diff is True
    assert "@@ -1,3 +1,15 @@" in pres.diff_content


def test_file_read_formatter():
    activity = ToolActivity(
        id="read_1",
        conversation_id="conv_1",
        provider="codex",
        type=ToolType.FILE_READ,
        name="readme.md",
        files=["docs/readme.md"],
        output="# VRStudio Documentation\n\nFull guide...",
        status=ToolStatus.SUCCESS,
    )
    pres = FileReadFormatter().format(activity)
    assert pres.item_type == "fileRead"
    assert pres.state == "completed"
    assert pres.text == "Ler docs/readme.md"
    assert pres.subtitle == "docs/readme.md"
    assert "Full guide" in pres.detail
    assert pres.icon == "document"


def test_web_search_formatter():
    activity = ToolActivity(
        id="ws_1",
        conversation_id="conv_1",
        provider="codex",
        type=ToolType.WEB_SEARCH,
        input={"query": "Qt6 QML Repeater Loader binding"},
        output="Found 5 results:\n1. Qt Documentation...",
        status=ToolStatus.SUCCESS,
    )
    pres = WebSearchFormatter().format(activity)
    assert pres.item_type == "webSearch"
    assert "Qt6 QML Repeater" in pres.text
    assert pres.subtitle == "Qt6 QML Repeater Loader binding"
    assert "Found 5 results" in pres.detail
    assert pres.icon == "search"


def test_mcp_tool_call_formatter():
    activity = ToolActivity(
        id="mcp_1",
        conversation_id="conv_1",
        provider="codex",
        type=ToolType.MCP_TOOL_CALL,
        name="execute_sql",
        metadata={"server": "postgres", "tool": "execute_sql"},
        input={"query": "SELECT * FROM users LIMIT 1"},
        output='[{"id": 1, "name": "admin"}]',
        status=ToolStatus.SUCCESS,
    )
    pres = McpToolCallFormatter().format(activity)
    assert pres.item_type == "mcpToolCall"
    assert pres.subtitle == "postgres/execute_sql"
    assert "SELECT * FROM users" in pres.detail
    assert "admin" in pres.detail
    assert pres.icon == "plug"


def test_group_activities_all_success_commands():
    act1 = ToolActivity(id="t1", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS)
    act2 = ToolActivity(id="t2", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS)
    act3 = ToolActivity(id="t3", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS)

    registry = ToolPresentationRegistry()
    group = registry.group_activities([act1, act2, act3])

    assert group.total_tools == 3
    assert group.status == ToolStatus.SUCCESS
    assert group.state == "completed"
    assert group.title == "3 comandos executados"
    assert group.badge_text == "3 concluídos"
    assert group.badge_variant == "success"
    assert len(group.items) == 3


def test_group_activities_one_failure_poisons_group():
    act1 = ToolActivity(id="t1", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS)
    act2 = ToolActivity(id="t2", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.FAILURE, error="Exit code 1")
    act3 = ToolActivity(id="t3", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS)

    registry = ToolPresentationRegistry()
    group = registry.group_activities([act1, act2, act3])

    assert group.status == ToolStatus.FAILURE
    assert group.state == "error"
    assert group.failed_count == 1
    assert group.badge_text == "1 falha"
    assert group.badge_variant == "error"


def test_group_activities_running_takes_precedence_over_success():
    act1 = ToolActivity(id="t1", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS)
    act2 = ToolActivity(id="t2", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.RUNNING)

    registry = ToolPresentationRegistry()
    group = registry.group_activities([act1, act2])

    assert group.status == ToolStatus.RUNNING
    assert group.state == "running"
    assert group.running_count == 1
    assert group.badge_text == "1 rodando"
    assert group.badge_variant == "info"


def test_mandatory_null_and_stack_trace_sanitization_in_presentation():
    # Mandatory requirement from Section 11 and Section 41:
    # Title is "null", error is a Java NullPointerException stack trace
    java_stack_trace = """java.lang.NullPointerException: Cannot invoke "String.length()" because "s" is null
\tat com.example.MyClass.process(MyClass.java:42)
\tat com.example.Main.main(Main.java:15)"""

    activity = ToolActivity(
        id="null_case",
        conversation_id="conv_1",
        provider="codex",
        type=ToolType.COMMAND_EXECUTION,
        name="null",
        title="null",
        error=java_stack_trace,
        status=ToolStatus.FAILURE,
    )
    pres = DEFAULT_PRESENTATION_REGISTRY.format(activity)

    # Title must NEVER be "null" or None or empty
    assert pres.text != "null"
    assert pres.text != ""
    assert pres.text == "Comando falhou"
    # Error summary must cleanly extract the semantic exception name
    assert "NullPointerException" in pres.error_summary
    assert "at com.example" not in pres.error_summary
    # Full stack trace is in error_details and detail
    assert "at com.example.MyClass.process" in pres.error_details


def test_format_from_event_roundtrip():
    # RuntimeEvent with canonical event dict
    event = RuntimeEvent(
        conversation_id="conv_roundtrip",
        kind="tool_event",
        text="rg search",
        payload={
            "canonical_event": {
                "tool_id": "call_rt_1",
                "kind": "tool.completed",
                "type": "commandExecution",
                "title": "Buscar no código",
                "command": "rg search",
                "status": "success",
                "output": "Found result",
            }
        },
    )
    pres = DEFAULT_PRESENTATION_REGISTRY.format_from_event(event)
    assert pres.tool_id == "call_rt_1"
    assert pres.item_type == "commandExecution"
    assert pres.state == "completed"
    assert pres.text == "Buscar no código"
    assert "rg search" in pres.detail
    assert "Found result" in pres.detail

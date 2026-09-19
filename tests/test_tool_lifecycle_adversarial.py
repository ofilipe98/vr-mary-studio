"""Adversarial and parity test suite for Tool Calling lifecycle and UI presentation."""
import pytest
from vrsoft_extractor.mary.tool_activity import (
    ToolActivity,
    ToolLifecycleReducer,
    ToolStatus,
    ToolType,
    ToolEventKind,
    NormalizedToolEvent,
    coalesce_output,
    sanitize_title,
    sanitize_error_summary,
)
from vrsoft_extractor.mary.tool_presentation import (
    DEFAULT_PRESENTATION_REGISTRY,
    group_consecutive_tools,
)


class TestToolLifecycleAdversarial:
    """Test out-of-order, concurrent, and adversarial edge cases."""

    def test_parallel_running_tools_independent_lifecycle(self):
        reducer = ToolLifecycleReducer()
        # Tool A starts
        ev_a_start = NormalizedToolEvent(
            tool_id="call-a",
            kind=ToolEventKind.STARTED,
            provider="antigravity",
            type=ToolType.COMMAND_EXECUTION,
            command="git status",
            name="command",
        )
        reducer.reduce(ev_a_start)

        # Tool B starts concurrently
        ev_b_start = NormalizedToolEvent(
            tool_id="call-b",
            kind=ToolEventKind.STARTED,
            provider="codex",
            type=ToolType.FILE_READ,
            name="fileRead",
            files=["src/main.py"],
        )
        reducer.reduce(ev_b_start)

        assert len(reducer.activities) == 2
        assert reducer.activities["call-a"].status == ToolStatus.RUNNING
        assert reducer.activities["call-b"].status == ToolStatus.RUNNING

        # Stream output to Tool A only
        reducer.reduce(NormalizedToolEvent(
            tool_id="call-a",
            kind=ToolEventKind.UPDATED,
            delta="On branch main\n",
        ))
        assert reducer.activities["call-a"].output == "On branch main\n"
        assert reducer.activities["call-b"].output is None

        # Complete Tool B with success
        reducer.reduce(NormalizedToolEvent(
            tool_id="call-b",
            kind=ToolEventKind.COMPLETED,
            output="file content",
        ))
        assert reducer.activities["call-b"].status == ToolStatus.SUCCESS
        assert reducer.activities["call-a"].status == ToolStatus.RUNNING  # unaffected

        # Complete Tool A with failure
        reducer.reduce(NormalizedToolEvent(
            tool_id="call-a",
            kind=ToolEventKind.FAILED,
            exit_code=1,
            error="fatal: not a git repository",
        ))
        assert reducer.activities["call-a"].status == ToolStatus.FAILURE
        assert reducer.activities["call-b"].status == ToolStatus.SUCCESS

    def test_completed_before_started_out_of_order(self):
        """If a completed event arrives before started, tool must reach terminal state and not regress."""
        reducer = ToolLifecycleReducer()
        ev_completed = NormalizedToolEvent(
            tool_id="ooo-1",
            kind=ToolEventKind.COMPLETED,
            provider="codex",
            type=ToolType.COMMAND_EXECUTION,
            command="echo hi",
            output="hi\n",
            exit_code=0,
        )
        act = reducer.reduce(ev_completed)
        assert act.status == ToolStatus.SUCCESS
        assert act.output == "hi\n"

        # Late started event arrives afterwards
        ev_late_start = NormalizedToolEvent(
            tool_id="ooo-1",
            kind=ToolEventKind.STARTED,
            provider="codex",
            type=ToolType.COMMAND_EXECUTION,
            command="echo hi",
        )
        act_after = reducer.reduce(ev_late_start)
        # MUST NOT regress to RUNNING
        assert act_after.status == ToolStatus.SUCCESS

    def test_late_updates_after_cancellation_do_not_regress_or_turn_success(self):
        """Running tool + turn cancelado + late provider update -> tool remains cancelled/interrupted."""
        reducer = ToolLifecycleReducer()
        reducer.reduce(NormalizedToolEvent(
            tool_id="cancel-1",
            kind=ToolEventKind.STARTED,
            provider="antigravity",
            type=ToolType.COMMAND_EXECUTION,
            command="mvn clean install",
        ))
        assert reducer.activities["cancel-1"].status == ToolStatus.RUNNING

        # Turn cancelled
        reducer.reduce(NormalizedToolEvent(
            tool_id="cancel-1",
            kind=ToolEventKind.CANCELLED,
            provider="antigravity",
        ))
        assert reducer.activities["cancel-1"].status == ToolStatus.CANCELLED

        # Late provider delta arrives
        reducer.reduce(NormalizedToolEvent(
            tool_id="cancel-1",
            kind=ToolEventKind.UPDATED,
            delta="BUILD SUCCESS\n",
        ))
        # Status MUST stay CANCELLED, not RUNNING
        assert reducer.activities["cancel-1"].status == ToolStatus.CANCELLED

        # Late provider completed event arrives
        reducer.reduce(NormalizedToolEvent(
            tool_id="cancel-1",
            kind=ToolEventKind.COMPLETED,
            output="Full build done",
            exit_code=0,
        ))
        # Status MUST stay CANCELLED, NEVER turn to SUCCESS!
        assert reducer.activities["cancel-1"].status == ToolStatus.CANCELLED

    def test_turn_completion_non_masking(self):
        """Unfinished running tools finalize to interrupted, never masked as completed/success."""
        reducer = ToolLifecycleReducer()
        reducer.reduce(NormalizedToolEvent(
            tool_id="run-1",
            kind=ToolEventKind.STARTED,
            type=ToolType.COMMAND_EXECUTION,
            command="long-running-job",
        ))
        reducer.reduce(NormalizedToolEvent(
            tool_id="run-2",
            kind=ToolEventKind.STARTED,
            type=ToolType.FILE_READ,
            files=["config.json"],
        ))
        # Complete run-2 normally
        reducer.reduce(NormalizedToolEvent(
            tool_id="run-2",
            kind=ToolEventKind.COMPLETED,
            output="{}",
        ))

        # Turn abruptly finishes
        reducer.finalize_turn(turn_terminal_status=ToolStatus.INTERRUPTED)

        assert reducer.activities["run-2"].status == ToolStatus.SUCCESS  # already completed
        assert reducer.activities["run-1"].status == ToolStatus.INTERRUPTED  # NOT SUCCESS

    def test_approval_lifecycle_and_denial(self):
        """Test waiting_approval -> denied -> CANCELLED with denied metadata."""
        reducer = ToolLifecycleReducer()
        # Approval requested
        act = reducer.reduce(NormalizedToolEvent(
            tool_id="appr-1",
            kind=ToolEventKind.APPROVAL_REQUESTED,
            type=ToolType.COMMAND_EXECUTION,
            command="rm -rf /tmp/build",
            title="Excluir diretório de build?",
        ))
        assert act.status == ToolStatus.WAITING_APPROVAL

        # Approval denied
        act_denied = reducer.reduce(NormalizedToolEvent(
            tool_id="appr-1",
            kind=ToolEventKind.APPROVAL_RESOLVED,
            metadata={"approved": False},
        ))
        assert act_denied.status == ToolStatus.CANCELLED
        assert act_denied.metadata.get("denied") is True

        # Presentation check
        pres = DEFAULT_PRESENTATION_REGISTRY.format(act_denied)
        assert pres.badge_text == "negado"
        assert pres.badge_variant == "warning"
        assert "negado" in pres.title.lower() or "cancelado" in pres.title.lower()


class TestOutputCoalescingAdversarial:
    """Test snapshot vs delta coalescing, avoiding duplicate repetition like AABABC."""

    def test_delta_stream(self):
        curr = None
        for chunk in ["A", "B", "C"]:
            curr = coalesce_output(curr, delta=chunk)
        assert curr == "ABC"

    def test_snapshot_stream(self):
        curr = None
        for snap in ["A", "AB", "ABC"]:
            curr = coalesce_output(curr, new_output=snap)
        assert curr == "ABC"

    def test_cumulative_snapshot_sent_in_delta_field(self):
        """Some buggy adapters send the whole cumulative buffer in the delta parameter."""
        curr = None
        for fake_delta in ["A", "AB", "ABC"]:
            curr = coalesce_output(curr, delta=fake_delta)
        # MUST NOT be AABABC
        assert curr == "ABC"

    def test_delta_with_whitespace_and_newlines(self):
        curr = "Line 1\n"
        curr = coalesce_output(curr, delta="Line 2\n")
        assert curr == "Line 1\nLine 2\n"

    def test_none_and_empty_deltas(self):
        curr = "Hello"
        assert coalesce_output(curr, delta="") == "Hello"
        assert coalesce_output(curr, delta=None) == "Hello"


class TestSanitizationAndStackTraces:
    """Never show 'null', 'None', 'undefined' as title, and sanitize stack traces."""

    def test_null_and_empty_title_fallbacks(self):
        assert sanitize_title(None, "", ToolType.FILE_READ, ToolStatus.RUNNING) == "Ler arquivo"
        assert sanitize_title("null", "", ToolType.COMMAND_EXECUTION, ToolStatus.RUNNING) == "Executar comando"
        assert sanitize_title("None", "web_search", ToolType.WEB_SEARCH, ToolStatus.RUNNING) == "web_search"
        assert sanitize_title("None", "", ToolType.WEB_SEARCH, ToolStatus.RUNNING) == "Pesquisa na web"
        assert sanitize_title("undefined", "browser", ToolType.BROWSER, ToolStatus.RUNNING) == "Navegação"
        assert sanitize_title("{}", "", ToolType.MCP_TOOL_CALL, ToolStatus.RUNNING) == "Ferramenta MCP"

    def test_null_title_with_java_stack_trace(self):
        """Mandatory requirement test case:
        null + vratacarejo.service.notasaida.NotaSaidaFiscalService... must collapse to
        × Ferramenta falhou / NullPointerException, with full trace only in expanded detail.
        """
        stack_trace = (
            "java.lang.NullPointerException: Cannot invoke method getNumero() on null object\n"
            "\tat vratacarejo.service.notasaida.NotaSaidaFiscalService.gerarNota(NotaSaidaFiscalService.java:142)\n"
            "\tat vratacarejo.service.notasaida.NotaSaidaFiscalService.processar(NotaSaidaFiscalService.java:88)\n"
            "\tat vratacarejo.web.controller.NotaSaidaController.salvar(NotaSaidaController.java:45)"
        )
        summary, details = sanitize_error_summary(stack_trace)
        assert summary == "NullPointerException"
        assert "vratacarejo.service.notasaida" in details

        # Check full presentation
        act = ToolActivity(
            id="err-java",
            type=ToolType.UNKNOWN,
            name="null",
            title=None,
            status=ToolStatus.FAILURE,
            error=summary,
            error_details=details,
        )
        pres = DEFAULT_PRESENTATION_REGISTRY.format(act)
        assert pres.state == "error"
        assert pres.title == "Ferramenta falhou"
        assert pres.subtitle == "NullPointerException"
        assert "vratacarejo.service.notasaida" in pres.error_details


class TestGroupingInvariants:
    """Test grouping of consecutive tools and strict non-hiding rules."""

    def test_consecutive_file_reads_grouped(self):
        activities = [
            ToolActivity(
                id=f"read-{i}",
                type=ToolType.FILE_READ,
                name="read_file",
                status=ToolStatus.SUCCESS,
                files=[f"file_{i}.txt"],
                _explicit_duration_ms=200,
            )
            for i in range(5)
        ]
        grouped = group_consecutive_tools(activities, threshold=3)
        assert len(grouped) == 1
        group = grouped[0]
        assert group.kind == "action_group"
        assert group.total_tools == 5
        assert len(group.items) == 5
        assert "5 arquivos" in group.title

    def test_running_tool_never_hidden_inside_group(self):
        activities = [
            ToolActivity(id="r-1", type=ToolType.FILE_READ, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            ToolActivity(id="r-2", type=ToolType.FILE_READ, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            ToolActivity(id="r-3", type=ToolType.FILE_READ, status=ToolStatus.RUNNING, _explicit_duration_ms=100),
            ToolActivity(id="r-4", type=ToolType.FILE_READ, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
        ]
        grouped = group_consecutive_tools(activities, threshold=2)
        # r-3 MUST NOT be inside any group!
        group_items = []
        for g in grouped:
            if hasattr(g, "items") and getattr(g, "kind", None) == "action_group":
                group_items.extend(g.items)
            else:
                assert g.tool_id == "r-3" or g.state != "running"

        assert not any(getattr(item, "tool_id", None) == "r-3" for item in group_items)

    def test_failed_tool_never_hidden_inside_group(self):
        activities = [
            ToolActivity(id="r-1", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            ToolActivity(id="r-2", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            ToolActivity(id="r-3", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.FAILURE, error="Boom", _explicit_duration_ms=100),
        ]
        grouped = group_consecutive_tools(activities, threshold=2)
        # r-3 must be isolated and standalone
        standalone_ids = [g.tool_id for g in grouped if getattr(g, "kind", None) != "action_group"]
        assert "r-3" in standalone_ids

    def test_waiting_approval_never_hidden_inside_group(self):
        activities = [
            ToolActivity(id="r-1", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            ToolActivity(id="r-2", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            ToolActivity(id="r-3", type=ToolType.COMMAND_EXECUTION, status=ToolStatus.WAITING_APPROVAL, _explicit_duration_ms=100),
        ]
        grouped = group_consecutive_tools(activities, threshold=2)
        standalone_ids = [g.tool_id for g in grouped if getattr(g, "kind", None) != "action_group"]
        assert "r-3" in standalone_ids

    def test_long_running_tool_never_hidden_inside_group(self):
        activities = [
            ToolActivity(id="r-1", type=ToolType.FILE_READ, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            ToolActivity(id="r-2", type=ToolType.FILE_READ, status=ToolStatus.SUCCESS, _explicit_duration_ms=100),
            # 15 seconds duration >= 10,000ms threshold
            ToolActivity(id="r-3", type=ToolType.FILE_READ, status=ToolStatus.SUCCESS, _explicit_duration_ms=15000),
        ]
        grouped = group_consecutive_tools(activities, threshold=2)
        standalone_ids = [g.tool_id for g in grouped if getattr(g, "kind", None) != "action_group"]
        assert "r-3" in standalone_ids

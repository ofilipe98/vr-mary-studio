"""Unit tests for the canonical ToolActivity model and ToolLifecycleReducer.

Covers:
- Lifecycle state transitions (started -> running, completed, failed, cancelled, approval)
- Monotonic terminal state invariants (terminal cannot revert to running)
- Out-of-order and stale sequence handling
- Deduplication and idempotency (repeated event_ids and repeated payloads)
- Snapshot vs delta output merge (incremental vs cumulative vs repeated)
- Concurrent parallel tool calls
- Turn finalization (no running tools converted to success)
- Replay and serialization roundtrips
- Error and title sanitization, including the mandatory 'null' stack trace case
"""
import pytest

from vrsoft_extractor.mary.tool_activity import (
    NormalizedToolEvent,
    ToolActivity,
    ToolEventKind,
    ToolLifecycleReducer,
    ToolStatus,
    ToolType,
    sanitize_error_summary,
    sanitize_title,
)


def test_lifecycle_started_to_running():
    reducer = ToolLifecycleReducer()
    event = NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
        type=ToolType.COMMAND_EXECUTION,
        name="rg",
        command='rg "calcularImpostoItem" src/',
    )
    tool = reducer.reduce(event)
    assert tool.id == "call_1"
    assert tool.status == ToolStatus.RUNNING
    assert tool.type == ToolType.COMMAND_EXECUTION
    assert tool.started_at != ""
    assert tool.finished_at == ""
    assert not tool.is_terminal()


def test_lifecycle_running_to_completed():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
        type=ToolType.FILE_READ,
        name="readFile",
    ))
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.COMPLETED,
        output="file content",
    ))
    assert tool.status == ToolStatus.SUCCESS
    assert tool.is_terminal()
    assert tool.finished_at != ""
    assert tool.output == "file content"


def test_lifecycle_running_to_failed():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
        type=ToolType.COMMAND_EXECUTION,
    ))
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.FAILED,
        exit_code=1,
        error="Process exited with code 1",
    ))
    assert tool.status == ToolStatus.FAILURE
    assert tool.is_terminal()
    assert tool.exit_code == 1
    assert tool.error == "Process exited with code 1"


def test_lifecycle_running_to_cancelled():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
    ))
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.CANCELLED,
    ))
    assert tool.status == ToolStatus.CANCELLED
    assert tool.is_terminal()


def test_lifecycle_waiting_approval_resolved_true():
    reducer = ToolLifecycleReducer()
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.APPROVAL_REQUESTED,
        type=ToolType.COMMAND_EXECUTION,
        command="rm -rf /tmp/test",
    ))
    assert tool.status == ToolStatus.WAITING_APPROVAL

    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.APPROVAL_RESOLVED,
        approved=True,
    ))
    assert tool.status == ToolStatus.RUNNING


def test_lifecycle_waiting_approval_resolved_false():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.APPROVAL_REQUESTED,
    ))
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.APPROVAL_RESOLVED,
        approved=False,
    ))
    assert tool.status == ToolStatus.CANCELLED
    assert tool.is_terminal()


def test_terminal_state_protection_completed_cannot_revert():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.COMPLETED,
        output="done",
    ))

    # Late event trying to set status back to running
    late_event = NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
    )
    tool = reducer.reduce(late_event)
    assert tool.status == ToolStatus.SUCCESS
    assert tool.is_terminal()

    # Late update event with running status
    late_update = NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        status=ToolStatus.RUNNING,
    )
    tool = reducer.reduce(late_update)
    assert tool.status == ToolStatus.SUCCESS


def test_terminal_state_protection_failed_cannot_revert():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.FAILED,
        error="Crash",
    ))
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        status=ToolStatus.RUNNING,
    ))
    assert tool.status == ToolStatus.FAILURE


def test_out_of_order_sequence_protection():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
        sequence=5,
    ))
    # Stale sequence 3 arrives late
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        sequence=3,
        name="should_not_overwrite",
    ))
    assert tool.sequence == 5
    assert tool.name != "should_not_overwrite"


def test_idempotency_same_event_id_twice():
    reducer = ToolLifecycleReducer()
    e1 = NormalizedToolEvent(
        tool_id="call_1",
        event_id="evt_100",
        kind=ToolEventKind.STARTED,
        output="first output",
    )
    reducer.reduce(e1)
    tool = reducer.reduce(e1)
    assert tool.output == "first output"


def test_idempotency_same_payload_without_event_id():
    reducer = ToolLifecycleReducer()
    e = NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        delta="hello ",
    )
    reducer.reduce(e)
    tool = reducer.reduce(e)
    # Identical repeated payload digest should not double append
    assert tool.output == "hello "


def test_snapshot_vs_delta_cumulative_snapshot():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
    ))
    # Cumulative snapshots: chunk 1, chunk 1 + chunk 2, chunk 1 + chunk 2 + chunk 3
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        output="Line 1\n",
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        output="Line 1\nLine 2\n",
    ))
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        output="Line 1\nLine 2\nLine 3\n",
    ))
    # Must NOT duplicate Line 1 and Line 2
    assert tool.output == "Line 1\nLine 2\nLine 3\n"


def test_snapshot_vs_delta_incremental_deltas():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        delta="chunk A, ",
    ))
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.UPDATED,
        delta="chunk B",
    ))
    assert tool.output == "chunk A, chunk B"


def test_concurrent_parallel_tool_calls():
    """Scenario required by prompt:
    A started
    B started
    A completed
    C started
    B failed
    C completed
    """
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="tool_A",
        kind=ToolEventKind.STARTED,
        name="tool_A",
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="tool_B",
        kind=ToolEventKind.STARTED,
        name="tool_B",
    ))

    active = reducer.get_active_tools()
    assert len(active) == 2
    assert {t.id for t in active} == {"tool_A", "tool_B"}

    reducer.reduce(NormalizedToolEvent(
        tool_id="tool_A",
        kind=ToolEventKind.COMPLETED,
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="tool_C",
        kind=ToolEventKind.STARTED,
        name="tool_C",
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="tool_B",
        kind=ToolEventKind.FAILED,
        error="Network error",
    ))

    all_tools = {t.id: t for t in reducer.get_all_tools()}
    assert all_tools["tool_A"].status == ToolStatus.SUCCESS
    assert all_tools["tool_B"].status == ToolStatus.FAILURE
    assert all_tools["tool_C"].status == ToolStatus.RUNNING

    reducer.reduce(NormalizedToolEvent(
        tool_id="tool_C",
        kind=ToolEventKind.COMPLETED,
    ))
    assert all_tools["tool_C"].status == ToolStatus.SUCCESS
    assert len(reducer.get_active_tools()) == 0


def test_turn_finalization_interrupted_does_not_mask_running_as_success():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="tool_1",
        kind=ToolEventKind.STARTED,
    ))
    # Turn finishes prematurely without explicit tool.completed
    finalized = reducer.finalize_turn(turn_terminal_status=ToolStatus.INTERRUPTED)
    assert len(finalized) == 1
    assert finalized[0].status == ToolStatus.INTERRUPTED
    assert finalized[0].is_terminal()
    assert finalized[0].status != ToolStatus.SUCCESS


def test_cancel_all_running_on_user_cancellation():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="t1",
        kind=ToolEventKind.STARTED,
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="t2",
        kind=ToolEventKind.COMPLETED,
    ))
    cancelled = reducer.cancel_all_running()
    assert len(cancelled) == 1
    assert cancelled[0].id == "t1"
    assert cancelled[0].status == ToolStatus.CANCELLED
    # t2 should remain SUCCESS
    assert reducer.get_tool("t2").status == ToolStatus.SUCCESS


def test_replay_serialization_roundtrip():
    reducer = ToolLifecycleReducer()
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.STARTED,
        type=ToolType.WEB_SEARCH,
        title='Pesquisou "T3Code tool calling"',
        sequence=1,
    ))
    reducer.reduce(NormalizedToolEvent(
        tool_id="call_1",
        kind=ToolEventKind.COMPLETED,
        output="Result docs",
        sequence=2,
    ))
    data = reducer.to_dict()

    restored = ToolLifecycleReducer.from_dict(data)
    restored_tool = restored.get_tool("call_1")
    assert restored_tool is not None
    assert restored_tool.id == "call_1"
    assert restored_tool.status == ToolStatus.SUCCESS
    assert restored_tool.type == ToolType.WEB_SEARCH
    assert restored_tool.title == 'Pesquisou "T3Code tool calling"'
    assert restored_tool.output == "Result docs"
    assert restored_tool.sequence == 2


def test_mandatory_null_error_case_section_41():
    """Section 41 mandatory test:
    null
    vratacarejo.service.notasaida.
    NotaSaidaFiscalService.calcularImpostoItem(...)
    
    Must result in:
    Title: "Ferramenta falhou" (never "null")
    Error summary: "NullPointerException"
    Error details: full stack trace
    """
    raw_error = (
        "null\n"
        "vratacarejo.service.notasaida.\n"
        "NotaSaidaFiscalService.calcularImpostoItem(NotaSaidaFiscalService.java:120)\n"
        "vratacarejo.service.notasaida.NotaSaidaFiscalService.processar(NotaSaidaFiscalService.java:45)"
    )
    summary, details = sanitize_error_summary(raw_error)
    assert summary == "NullPointerException"
    assert "NotaSaidaFiscalService.calcularImpostoItem" in details

    reducer = ToolLifecycleReducer()
    tool = reducer.reduce(NormalizedToolEvent(
        tool_id="call_err",
        kind=ToolEventKind.FAILED,
        title="null",
        error=raw_error,
    ))
    assert tool.title != "null"
    assert tool.title == "Ferramenta falhou"
    assert tool.error == "NullPointerException"
    assert "NotaSaidaFiscalService.calcularImpostoItem" in tool.error_details


def test_sanitize_title_fallbacks():
    assert sanitize_title("null", "", ToolType.COMMAND_EXECUTION, ToolStatus.RUNNING) == "Executar comando"
    assert sanitize_title("None", "", ToolType.FILE_READ, ToolStatus.RUNNING) == "Ler arquivo"
    assert sanitize_title("undefined", "", ToolType.FILE_CHANGE, ToolStatus.RUNNING) == "Alterar arquivo"
    assert sanitize_title("{}", "", ToolType.WEB_SEARCH, ToolStatus.RUNNING) == "Pesquisa na web"
    assert sanitize_title("[]", "", ToolType.COMMAND_EXECUTION, ToolStatus.FAILURE) == "Comando falhou"
    assert sanitize_title("", "", ToolType.UNKNOWN, ToolStatus.FAILURE) == "Ferramenta falhou"
    assert sanitize_title("Valid Title", "", ToolType.COMMAND_EXECUTION, ToolStatus.RUNNING) == "Valid Title"

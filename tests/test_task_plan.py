import pytest

from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.task_plan import TaskPlan, claude_task_result, provider_plan


@pytest.mark.parametrize(
    "event",
    [
        RuntimeEvent(
            "c",
            "runtime_event",
            "turn/plan/updated",
            {
                "plan": [
                    {"step": "Read", "status": "inProgress"},
                    {"step": "Check", "status": "pending"},
                ]
            },
        ),
        RuntimeEvent(
            "c",
            "tool_event",
            payload={
                "name": "TodoWrite",
                "input": {
                    "todos": [
                        {"content": "Read", "status": "in_progress"},
                        {"content": "Check", "status": "pending"},
                    ]
                },
            },
        ),
        RuntimeEvent(
            "c",
            "tool_event",
            payload={
                "part": {
                    "tool": "todowrite",
                    "state": {
                        "input": {
                            "todos": [
                                {"content": "Read", "status": "in_progress"},
                                {"content": "Check", "status": "pending"},
                            ]
                        }
                    },
                }
            },
        ),
        RuntimeEvent(
            "c",
            "task_plan_updated",
            payload={
                "plan": [
                    {"content": "Read", "status": "in_progress"},
                    {"content": "Check", "status": "pending"},
                ]
            },
        ),
    ],
)
def test_provider_snapshots(event):
    assert provider_plan(event) == [
        {"text": "Read", "state": "running"},
        {"text": "Check", "state": "pending"},
    ]


def test_duplicate_steps_have_independent_timing_and_explicit_clear():
    plan = TaskPlan()
    plan.update(
        [{"text": "Check", "state": "running"}, {"text": "Check", "state": "pending"}],
        "2026-09-13T12:00:00Z",
    )
    plan.update(
        [
            {"text": "Check", "state": "completed"},
            {"text": "Check", "state": "running"},
        ],
        "2026-09-13T12:00:05Z",
    )
    plan.update(
        [
            {"text": "Check", "state": "completed"},
            {"text": "Check", "state": "completed"},
        ],
        "2026-09-13T12:00:12Z",
    )
    assert [step["durationMs"] for step in plan.steps] == [5000, 7000]
    plan.update([], "2026-09-13T12:00:13Z")
    plan.update([{"text": "Check", "state": "completed"}], "2026-09-13T12:00:15Z")
    assert "durationMs" not in plan.steps[0]


def test_malformed_plan_does_not_clear_but_empty_plan_does():
    assert (
        provider_plan(
            RuntimeEvent(
                "c", "runtime_event", "turn/plan/updated", {"plan": [None, {}]}
            )
        )
        is None
    )
    assert (
        provider_plan(
            RuntimeEvent("c", "runtime_event", "turn/plan/updated", {"plan": []})
        )
        == []
    )


def test_claude_task_create_update_list_and_delete_use_successful_results():
    created = claude_task_result(
        {
            "name": "TaskCreate",
            "input": {"subject": "Read"},
            "result": {"task": {"id": "1", "subject": "Read"}},
        },
        {},
    )
    assert created["plan"] == [{"step": "Read", "status": "pending"}]
    updated = claude_task_result(
        {
            "name": "TaskUpdate",
            "input": {"taskId": "1", "status": "in_progress", "addBlockedBy": ["2"]},
            "result": {"success": True},
        },
        created["task_records"],
    )
    assert updated["plan"] == [
        {"step": "Read (bloqueada por #2)", "status": "in_progress"}
    ]
    assert (
        claude_task_result(
            {
                "name": "TaskUpdate",
                "input": {"taskId": "1", "status": "completed"},
                "result": {"success": False},
            },
            updated["task_records"],
        )
        is None
    )
    deleted = claude_task_result(
        {"name": "TaskUpdate", "input": {"taskId": "1", "status": "deleted"}},
        updated["task_records"],
    )
    assert deleted["plan"] == []
    assert (
        claude_task_result(
            {"name": "TaskList", "result": {"tasks": []}}, updated["task_records"]
        )["plan"]
        == []
    )


def test_claude_stream_task_results_are_correlated_and_errors_ignored():
    import io
    import json
    from types import SimpleNamespace
    from vrsoft_extractor.mary.provider_adapters.claude import ClaudeProvider

    messages = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "one",
                        "name": "TaskCreate",
                        "input": {"subject": "Read"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "one"}]},
            "tool_use_result": {"task": {"id": "1", "subject": "Read"}},
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "two",
                        "name": "TaskUpdate",
                        "input": {"taskId": "1", "status": "completed"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "two", "is_error": True}
                ]
            },
        },
        {"type": "result", "result": "Done"},
    ]
    process = SimpleNamespace(
        stdout=io.StringIO("\n".join(json.dumps(x) for x in messages)),
        stderr=io.StringIO(""),
        wait=lambda: 0,
    )
    events = []
    provider = ClaudeProvider()
    provider._consume("c", process, events.append)
    results = [event for event in events if event.kind == "task_tool_result"]
    assert len(results) == 1
    assert results[0].payload["result"]["task"]["id"] == "1"

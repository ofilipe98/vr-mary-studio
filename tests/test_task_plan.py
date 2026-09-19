import pytest

from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.task_plan import (
    TaskPlan,
    claude_task_result,
    derive_task_progress,
    provider_plan,
)


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


def test_codex_status_mapping_is_canonical():
    event = RuntimeEvent(
        "c",
        "runtime_event",
        "turn/plan/updated",
        {
            "plan": [
                {"step": "A", "status": "pending"},
                {"step": "B", "status": "inProgress"},
                {"step": "C", "status": "completed"},
                {"step": "D", "status": "weird_future_state"},
            ]
        },
    )
    assert provider_plan(event) == [
        {"text": "A", "state": "pending"},
        {"text": "B", "state": "running"},
        {"text": "C", "state": "completed"},
        {"text": "D", "state": "pending"},
    ]


def test_todowrite_fallback_shapes_normalize_to_same_contract():
    variants = [
        {"name": "TodoWrite", "input": {"todos": [{"content": "X", "status": "in_progress"}]}},
        {"tool": "todo_write", "input": {"todos": [{"content": "X", "status": "in_progress"}]}},
        {
            "part": {
                "tool": "TodoWrite",
                "state": {"input": {"todos": [{"title": "X", "status": "in_progress"}]}},
            }
        },
    ]
    for payload in variants:
        assert provider_plan(RuntimeEvent("c", "tool_event", payload=payload)) == [
            {"text": "X", "state": "running"}
        ]


def test_opencode_tool_use_shape_normalizes():
    payload = {
        "type": "tool_use",
        "part": {
            "tool": "TodoWrite",
            "state": {"input": {"todos": [{"content": "Y", "status": "pending"}]}},
        },
    }
    assert provider_plan(RuntimeEvent("c", "tool_event", payload=payload)) == [
        {"text": "Y", "state": "pending"}
    ]


def test_derive_task_progress_single_source():
    assert derive_task_progress([]) is None
    assert derive_task_progress(None) is None
    assert (
        derive_task_progress([{"text": "A", "state": "completed"}]) is None
    )
    assert derive_task_progress(
        [
            {"text": "A", "state": "completed"},
            {"text": "B", "state": "running"},
            {"text": "C", "state": "pending"},
        ]
    ) == {"step": "B", "completed": 1, "total": 3}
    # No running: first pending wins.
    assert derive_task_progress(
        [
            {"text": "A", "state": "completed"},
            {"text": "B", "state": "pending"},
        ]
    ) == {"step": "B", "completed": 1, "total": 2}
    # Duplicate labels do not collide: occurrence order decides.
    assert derive_task_progress(
        [
            {"text": "Same", "state": "completed"},
            {"text": "Same", "state": "pending"},
        ]
    ) == {"step": "Same", "completed": 1, "total": 2}


def test_claude_blocked_by_preserved_and_list_replaces_registry():
    created = claude_task_result(
        {
            "name": "TaskCreate",
            "input": {"subject": "A", "blockedBy": ["9"]},
            "result": {"task": {"id": "1", "subject": "A", "blockedBy": ["9"]}},
        },
        {},
    )
    assert created["plan"][0]["step"] == "A (bloqueada por #9)"
    replaced = claude_task_result(
        {
            "name": "TaskList",
            "input": {},
            "result": {"tasks": [{"id": "2", "subject": "B", "status": "pending"}]},
        },
        created["task_records"],
    )
    assert replaced["plan"] == [{"step": "B", "status": "pending"}]
    assert set(replaced["task_records"]) == {"2"}
    # Unknown id and failed result never corrupt state.
    assert (
        claude_task_result(
            {
                "name": "TaskUpdate",
                "input": {"taskId": "missing", "status": "completed"},
                "result": {"success": True},
            },
            replaced["task_records"],
        )
        is None
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

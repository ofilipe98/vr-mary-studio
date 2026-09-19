"""Provider task snapshots, independent from the orchestration activity timeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import RuntimeEvent


def claude_task_result(
    payload: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any] | None:
    """Apply successful Claude Task tool results to a persisted task registry."""
    name = payload.get("name")
    inputs = payload.get("input") or {}
    result = payload.get("result") or {}
    if not isinstance(inputs, dict) or not isinstance(result, dict):
        return None
    records = {
        key: dict(value) for key, value in previous.items() if isinstance(value, dict)
    }
    if name == "TaskList":
        if not isinstance(result.get("tasks"), list):
            return None
        records = {
            str(task["id"]): dict(task)
            for task in result["tasks"]
            if isinstance(task, dict) and task.get("id") and task.get("subject")
        }
    elif name == "TaskCreate":
        task = result.get("task")
        if not isinstance(task, dict) or not task.get("id"):
            return None
        records[str(task["id"])] = {**inputs, **task}
    elif name == "TaskUpdate":
        identifier = str(inputs.get("taskId") or result.get("taskId") or "")
        if identifier not in records or result.get("success") is False:
            return None
        if inputs.get("status") == "deleted":
            records.pop(identifier)
        else:
            task = records[identifier]
            for key in ("subject", "status"):
                if isinstance(inputs.get(key), str):
                    task[key] = inputs[key]
            blocked = list(task.get("blockedBy") or [])
            for identifier in inputs.get("addBlockedBy") or []:
                if identifier not in blocked:
                    blocked.append(identifier)
            removed = inputs.get("removeBlockedBy") or []
            task["blockedBy"] = [
                identifier for identifier in blocked if identifier not in removed
            ]
    else:
        return None
    plan = []
    for task in records.values():
        subject = task.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            continue
        blocked = task.get("blockedBy") or []
        suffix = (
            " (bloqueada por " + ", ".join("#" + str(key) for key in blocked) + ")"
            if blocked
            else ""
        )
        plan.append(
            {"step": subject.strip() + suffix, "status": task.get("status", "pending")}
        )
    return {"plan": plan, "task_records": records}


def _normalize_task_state(status: object) -> str:
    """Map provider plan statuses to the Studio canonical states."""
    text = str(status or "").strip()
    if text == "completed":
        return "completed"
    if text in {"inProgress", "in_progress", "in-progress", "in_progress_running"}:
        return "running"
    return "pending"


def _extract_todo_list(inputs: object) -> list | None:
    if not isinstance(inputs, dict):
        return None
    for key in ("todos", "tasks", "plan", "items"):
        value = inputs.get(key)
        if isinstance(value, list):
            return value
    return None


def provider_plan(event: RuntimeEvent) -> list[dict[str, str]] | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    raw = None
    if event.kind == "runtime_event" and event.text == "turn/plan/updated":
        candidate = payload.get("plan")
        if isinstance(candidate, list):
            raw = candidate
        else:
            raw = _extract_todo_list(payload)
    elif event.kind == "task_plan_updated":
        raw = payload.get("plan")
    elif event.kind == "tool_event":
        item = payload.get("item") or payload.get("part") or payload
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or item.get("tool") or "").casefold()
        if name not in {"todowrite", "todo_write"}:
            # OpenCode may surface the tool under part.type or payload type.
            fallback = str(
                payload.get("tool") or payload.get("name") or ""
            ).casefold()
            if fallback not in {"todowrite", "todo_write"}:
                return None
        state = item.get("state") or {}
        if not isinstance(state, dict):
            state = {}
        inputs = item.get("input") or state.get("input") or {}
        if not isinstance(inputs, dict):
            inputs = {}
        raw = _extract_todo_list(inputs)
        if raw is None and isinstance(item.get("todos"), list):
            raw = item.get("todos")
    if not isinstance(raw, list):
        return None
    steps = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = (
            item.get("step")
            if isinstance(item.get("step"), str)
            else item.get("content")
            if isinstance(item.get("content"), str)
            else item.get("title")
            if isinstance(item.get("title"), str)
            else item.get("text")
            if isinstance(item.get("text"), str)
            else item.get("label")
            if isinstance(item.get("label"), str)
            else None
        )
        if not isinstance(label, str) or not label.strip():
            continue
        steps.append(
            {
                "text": label.strip(),
                "state": _normalize_task_state(item.get("status")),
            }
        )
    # Empty arrays clear the plan; malformed nonempty snapshots do not.
    return steps if steps or not raw else None


def derive_task_progress(
    steps: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> dict[str, Any] | None:
    """Derive the compact active progress from a normalized plan snapshot.

    Single derivation shared by composer badge, activity status and sidebar.
    Returns ``{"step": str, "completed": int, "total": int}`` or ``None``
    when there is no active work (empty plan or everything completed).
    """
    if not isinstance(steps, (list, tuple)) or not steps:
        return None
    total = len(steps)
    completed = sum(
        1
        for step in steps
        if isinstance(step, dict) and step.get("state") == "completed"
    )
    if completed >= total:
        return None
    current = ""
    for step in steps:
        if isinstance(step, dict) and step.get("state") == "running":
            text = step.get("text")
            if isinstance(text, str) and text.strip():
                current = text.strip()
                break
    if not current:
        for step in steps:
            if isinstance(step, dict) and step.get("state") == "pending":
                text = step.get("text")
                if isinstance(text, str) and text.strip():
                    current = text.strip()
                    break
    if not current:
        return None
    return {"step": current, "completed": completed, "total": total}


class TaskPlan:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self._timings: dict[tuple[str, int], dict[str, float]] = {}
        self._turn_id: str = ""
        self._previous_completed_at: float | None = None

    def update(
        self, steps: list[dict[str, str]], created_at: str, turn_id: str = ""
    ) -> None:
        if any(
            not isinstance(step, dict)
            or not isinstance(step.get("text"), str)
            or step.get("state") not in {"pending", "running", "completed"}
            for step in steps
        ):
            return
        if turn_id and turn_id != self._turn_id:
            self._timings.clear()
            self._turn_id = turn_id
            self._previous_completed_at = None
        if not steps:
            self.steps = []
            self._timings.clear()
            self._previous_completed_at = None
            return
        try:
            timestamp = datetime.fromisoformat(created_at).timestamp()
        except (ValueError, TypeError):
            timestamp = None
        if self._previous_completed_at is None:
            self._previous_completed_at = timestamp
        occurrences: dict[str, int] = {}
        result = []
        for step in steps:
            text = step["text"]
            occurrence = occurrences.get(text, 0)
            occurrences[text] = occurrence + 1
            timing = self._timings.setdefault((text, occurrence), {})
            item: dict[str, Any] = dict(step)
            if timestamp is not None:
                if step["state"] == "running":
                    if "end" in timing:
                        timing.clear()
                    timing.setdefault("start", timestamp)
                elif step["state"] == "pending":
                    timing.clear()
                elif step["state"] == "completed":
                    if "end" not in timing:
                        timing.setdefault("start", self._previous_completed_at)
                        timing["end"] = timestamp
                        self._previous_completed_at = timestamp
                    elapsed = timing["end"] - timing["start"]
                    if elapsed > 0:
                        item["durationMs"] = int(elapsed * 1000)
            result.append(item)
        self.steps = result

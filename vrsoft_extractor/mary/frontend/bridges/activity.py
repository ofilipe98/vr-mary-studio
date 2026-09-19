from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from ...models import RuntimeEvent
from ...task_plan import TaskPlan

from .presentation import (markdown_for_display, short_event_text, segments_for_display)

class ActivityDomain:
    """Domain operations using the facade as the sole state and transaction owner."""
    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        return getattr(self._owner, name)

    def __setattr__(self, name, value):
        setattr(self._owner, name, value)

    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        if not isinstance(event, RuntimeEvent):
            return
        execution_id = int(event.payload.get("execution_id") or 0)
        if execution_id:
            previous = self._ui_execution_ids.get(event.conversation_id, 0)
            if execution_id < previous or (event.conversation_id, execution_id) in self._ui_terminal_executions:
                return
            self._ui_execution_ids[event.conversation_id] = execution_id
            if event.kind in {"turn_completed", "orchestration_completed", "orchestration_cancelled", "error"}:
                self._ui_terminal_executions.add((event.conversation_id, execution_id))
        if event.kind == "turn_started":
            self._finalize_pending_terminal_before_new_turn(event.conversation_id)
            self._active_turns.add(event.conversation_id)
        selected_id = self._selected_conversation_id()
        if event.conversation_id != selected_id:
            self._on_background_runtime_event(event)
            return
        self._sync_selected_turn_state()
        if execution_id and event.kind in {"assistant_started", "tool_event"} and any(
            row.get("role") == "activity" and not row.get("messageKey") for row in self._messages._items
        ):
            self._messages.replace([row for row in self._messages._items if row.get("role") != "activity" or row.get("messageKey")])
        self._record_execution_event(event)
        if event.kind == "tool_event" and execution_id:
            tool_entry = self._extract_tool_entry(event)
            if tool_entry is not None:
                assistant_count = sum(
                    1 for r in self._messages._items
                    if r.get("role") == "assistant"
                    and str(r.get("messageKey") or "").startswith(f"{execution_id}:")
                )
                activity_key = f"activity:{execution_id}:{assistant_count}"
                existing_activity = next(
                    (r for r in self._messages._items
                     if str(r.get("messageKey") or "").startswith(f"activity:{execution_id}:")
                     and any(t.get("id") == tool_entry["id"] for t in r.get("activityData", []))),
                    None,
                )
                if existing_activity is not None:
                    activity_key = existing_activity["messageKey"]
                else:
                    existing_activity = next((r for r in self._messages._items if r.get("messageKey") == activity_key), None)
                if existing_activity is not None:
                    activity_data = list(existing_activity.get("activityData") or [])
                    found = False
                    for idx, entry in enumerate(activity_data):
                        if entry.get("id") == tool_entry["id"]:
                            updated = dict(entry)
                            updated.update(tool_entry)
                            if not tool_entry.get("detail") and entry.get("detail"):
                                updated["detail"] = entry["detail"]
                            activity_data[idx] = updated
                            found = True
                            break
                    if not found:
                        activity_data.append(tool_entry)
                    is_running = any(entry.get("state") == "running" for entry in activity_data)
                    self._messages.update_by_key(
                        "messageKey",
                        activity_key,
                        activityData=activity_data,
                        isStreaming=is_running,
                    )
                else:
                    new_activity = {
                        "messageId": -2,
                        "role": "activity",
                        "content": "",
                        "displayContent": "",
                        "segments": [],
                        "createdAt": event.created_at,
                        "responseMode": "activity",
                        "messageKey": activity_key,
                        "isStreaming": tool_entry["state"] == "running",
                        "activityData": [tool_entry],
                    }
                    self._messages.append(new_activity)
        if event.kind == "assistant_started":
            for row in self._messages._items:
                if row.get("role") == "activity" and str(row.get("messageKey") or "").startswith(f"activity:{execution_id}:"):
                    self._messages.update_by_key("messageKey", row["messageKey"], isStreaming=False)
            key = str(event.payload.get("message_key") or "")
            if key:
                if any(row.get("messageKey") == key for row in self._messages._items):
                    return
                self._current_message_key = key
                self._streaming_text = ""
                self._displayed_streaming_text = ""
                self._stream_pending_text = ""
                self._turn_text = ""
                self._turn_segments = []
                self._segment_cursor = 0
                self._message_streaming_texts[key] = ""
                self._message_displayed_texts[key] = ""
                self._message_pending_texts[key] = ""
                self._messages.append({
                    "messageId": -1,
                    "role": "assistant",
                    "content": "",
                    "displayContent": "",
                    "segments": [],
                    "createdAt": "",
                    "responseMode": "vr" if self._vr_mode != "off" else "native",
                    "messageKey": key,
                    "isStreaming": True,
                })
                self._schedule_state_update()
            return
        if event.kind == "assistant_completed":
            key = str(event.payload.get("message_key") or "")
            if key:
                final_text = str(event.payload.get("final_text") or "")
                display_text = final_text or self._message_streaming_texts.get(key, "")
                self._messages.update_by_key(
                    "messageKey", key,
                    content=display_text,
                    displayContent=markdown_for_display(display_text),
                    segments=segments_for_display(display_text),
                    isStreaming=False,
                    messageId=int(event.payload.get("message_id") or -1),
                )
                self._message_streaming_texts.pop(key, None)
                self._message_displayed_texts.pop(key, None)
                self._message_pending_texts.pop(key, None)
                if self._current_message_key == key:
                    self._current_message_key = ""
                    if not any(self._message_pending_texts.values()):
                        self._stream_timer.stop()
                    self._stream_pending_text = ""
                    self._streaming_text = ""
                    self._displayed_streaming_text = ""
                self._schedule_state_update()
            return
        if event.kind == "assistant_delta":
            incoming_key = str(event.payload.get("message_key") or "")
            if incoming_key and any(row.get("messageKey") == incoming_key and not row.get("isStreaming") for row in self._messages._items):
                return
            delta = str(event.text or "")
            if not delta:
                return
            if str(event.payload.get("phase") or "") == "commentary" and not event.payload.get("message_key"):
                self._record_trace_text_delta(event, item_type="commentary")
                self._status_text = "Trabalhando…"
                self._schedule_state_update()
                return
            self._streaming_text += delta
            self._turn_text += delta
            self._stream_pending_text += delta
            key = str(event.payload.get("message_key") or self._current_message_key)
            if key:
                self._message_streaming_texts[key] = self._message_streaming_texts.get(key, "") + delta
                self._message_pending_texts[key] = self._message_pending_texts.get(key, "") + delta
            if not self._assistant_stream_started:
                self._assistant_stream_started = True
                if not event.payload.get("message_key"):
                    self._advance_default_activity()
                self._schedule_state_update()
            self._ensure_streaming_message()
            if not self._stream_timer.isActive():
                self._stream_timer.start()
        elif event.kind in {"approval_requested", "dynamic_tool_approval_requested"}:
            self._enqueue_approval(event)
        elif event.kind == "reasoning_delta":
            self._reasoning_text += str(event.text or "")
            self._record_trace_text_delta(event, item_type="reasoning")
            self._status_text = "Pensando…"
            self._schedule_state_update()
        elif event.kind in {"tool_event", "provider_reconnecting", "provider_reconnected"}:
            if event.kind == "tool_event":
                browser_address = self._browser_address_from_event(event)
                if browser_address:
                    self.browserNavigationRequested.emit(browser_address)
            self._status_text = (
                "Executando uma ação…"
                if event.kind == "tool_event"
                else event.text or "Trabalhando…"
            )
            self.stateChanged.emit()
        elif event.kind == "response_empty":
            self._status_text = "O provedor concluiu sem conteúdo."
            self.stateChanged.emit()

        elif event.kind == "research_failed":
            self._status_text = f"Pesquisa falhou: {short_event_text(event.text)}"
            self.stateChanged.emit()
        elif event.kind == "context_transferred":
            self._status_text = "Contexto transferido para nova sessão."
            self.stateChanged.emit()
        elif event.kind in {"turn_completed", "orchestration_completed", "error", "orchestration_cancelled"}:
            self._discard_conversation_approvals(event.conversation_id)
            for row in self._messages._items:
                if row.get("role") == "activity":
                    activities = [dict(act) for act in row.get("activityData", [])]
                    for act in activities:
                        if act.get("state") == "running":
                            act["state"] = ("error" if event.kind == "error" else
                                            "cancelled" if event.kind == "orchestration_cancelled" else "completed")
                    self._messages.update_by_key("messageKey", row.get("messageKey"),
                                                 isStreaming=False, activityData=activities)
            self._queue_terminal_state(event.kind, conversation_id=event.conversation_id, execution_id=execution_id)


    def _on_background_runtime_event(self, event: RuntimeEvent) -> None:
        if event.kind in {"approval_requested", "dynamic_tool_approval_requested"}:
            self._enqueue_approval(event)
            return
        if event.kind == "turn_started":
            self._finalize_pending_terminal_before_new_turn(event.conversation_id)
            self._active_turns.add(event.conversation_id)
            self._begin_task_turn(event.conversation_id)
            self.stateChanged.emit()
            return
        if event.kind == "task_plan_updated":
            steps = event.payload.get("steps")
            if isinstance(steps, list):
                if self._apply_task_snapshot(
                    event.conversation_id,
                    steps,
                    event.created_at,
                    str(
                        event.payload.get("turnId")
                        or event.payload.get("execution_id")
                        or ""
                    ),
                ):
                    self.stateChanged.emit()
            return
        if event.kind in {
            "turn_completed",
            "orchestration_completed",
            "error",
            "orchestration_cancelled",
        }:
            execution_id = int(event.payload.get("execution_id") or 0)
            self._discard_conversation_approvals(event.conversation_id)
            self._finish_background_turn(
                event.conversation_id, kind=event.kind, execution_id=execution_id
            )


    def _enqueue_approval(self, event: RuntimeEvent) -> None:
        request = {**event.payload, "conversation_id": event.conversation_id,
                   "_dynamic": event.kind.startswith("dynamic")}
        key = (request.get("conversation_id"), request.get("request_id"), request["_dynamic"])
        if not any((r.get("conversation_id"), r.get("request_id"), r.get("_dynamic")) == key
                   for r in self._pending_approvals):
            self._pending_approvals.append(request)
        if not self._approval_request:
            self._show_next_approval()

    def _show_next_approval(self) -> None:
        self._approval_request = self._pending_approvals[0] if self._pending_approvals else {}
        if self._approval_request.get("conversation_id") == self._selected_conversation_id():
            self._status_text = "Aguardando aprovação…"
        self.approvalRequested.emit(dict(self._approval_request))
        self.stateChanged.emit()

    def _discard_conversation_approvals(self, conversation_id: str) -> None:
        self._pending_approvals = [r for r in self._pending_approvals
                                   if r.get("conversation_id") != conversation_id]
        if self._approval_request.get("conversation_id") == conversation_id:
            self._show_next_approval()

    def _ensure_streaming_message(self) -> None:
        if self._current_message_key and any(row.get("messageKey") == self._current_message_key for row in self._messages._items):
            return
        if self._messages._items and self._messages._items[-1].get("role") == "assistant":
            return
        self._messages.append(
            {
                "messageId": -1,
                "role": "assistant",
                "content": self._streaming_text,
                "displayContent": "",
                "segments": [],
                "createdAt": "",
                "responseMode": "vr" if self._vr_mode != "off" else "native",
                "messageKey": self._current_message_key,
                "isStreaming": True,
            }
        )


    def _reset_stream_state(self) -> None:
        if hasattr(self, "_stream_timer"):
            self._stream_timer.stop()
        if hasattr(self, "_activity_clock"):
            self._activity_clock.stop()
        pending = getattr(self, "_pending_terminal", None)
        if pending:
            self._finalize_pending_terminal_before_new_turn()
        self._current_message_key = ""
        self._message_streaming_texts.clear()
        self._message_displayed_texts.clear()
        self._message_pending_texts.clear()
        self._streaming_text = ""
        self._displayed_streaming_text = ""
        self._stream_pending_text = ""
        self._stream_terminal_kind = ""
        self._turn_segments = []
        self._turn_text = ""
        self._segment_cursor = 0
        self._assistant_stream_started = False
        self._activity_started_at = 0.0
        self._activity_elapsed_seconds = 0


    def _reset_trace_state(self) -> None:
        self._trace_items = []
        self._trace_sequence = 0


    def _tick_activity_clock(self) -> None:
        if not self._activity_started_at:
            self._activity_clock.stop()
            return
        elapsed = max(0, int(time.monotonic() - self._activity_started_at))
        if elapsed != self._activity_elapsed_seconds:
            self._activity_elapsed_seconds = elapsed
            self._schedule_state_update()


    def _flush_stream_step(self) -> None:
        pending_messages = [(key, text) for key, text in self._message_pending_texts.items() if text]
        if pending_messages:
            for key, text in pending_messages:
                batch_size = max(32, (len(text) + 3) // 4)
                self._message_pending_texts[key] = text[batch_size:]
                visible = self._message_displayed_texts.get(key, "") + text[:batch_size]
                self._message_displayed_texts[key] = visible
                self._messages.update_by_key(
                    "messageKey", key, content=self._message_streaming_texts.get(key, ""),
                    displayContent=markdown_for_display(visible), segments=segments_for_display(visible),
                )
            self._stream_pending_text = ""
            return
        if self._stream_pending_text:
            backlog = len(self._stream_pending_text)
            batch_size = max(32, (backlog + 3) // 4)
            visible = self._stream_pending_text[:batch_size]
            self._stream_pending_text = self._stream_pending_text[batch_size:]
            self._displayed_streaming_text += visible
            self._ensure_streaming_message()
            update_kwargs = dict(
                content=self._streaming_text,
                displayContent=markdown_for_display(self._displayed_streaming_text),
                segments=self._turn_display_segments(
                    reveal_limit=len(self._displayed_streaming_text)
                ),
            )
            if self._current_message_key:
                self._messages.update_by_key(
                    "messageKey", self._current_message_key, **update_kwargs
                )
            else:
                self._messages.update_last(**update_kwargs)
            return
        self._stream_timer.stop()
        pending = getattr(self, "_pending_terminal", None)
        terminal_kind = self._stream_terminal_kind
        if pending:
            self._finalize_pending_terminal_before_new_turn()
        elif terminal_kind:
            self._stream_terminal_kind = ""
            self._finalize_terminal_state(terminal_kind)


    @staticmethod
    def _default_activity_steps() -> list[dict[str, str]]:
        return [
            {
                "kind": "request_analysis",
                "text": "Analisar a solicitação e o contexto disponível",
                "state": "running",
            },
            {
                "kind": "response_preparation",
                "text": "Preparar e revisar a resposta",
                "state": "pending",
            },
        ]


    def _advance_default_activity(self) -> None:
        if not self._activity_steps:
            self._activity_steps = self._default_activity_steps()
        for step in self._activity_steps:
            if step.get("state") == "running":
                step["state"] = "completed"
                break
        for step in self._activity_steps:
            if step.get("state") == "pending":
                step["state"] = "running"
                break


    def _restore_activity_from_history(self, conversation_id: str) -> None:
        key = str(conversation_id or "")
        restored = TaskPlan()
        for row in self._database.task_plan_events(conversation_id):
            try:
                payload = json.loads(row["payload_json"])
                steps = payload.get("steps")
                if isinstance(steps, list):
                    restored.update(steps, row["created_at"], str(payload.get("turnId") or payload.get("execution_id") or ""))
            except (TypeError, ValueError, KeyError, AttributeError):
                continue
        self._task_plans[key] = restored
        self._task_plan_current_by_id[key] = False
        self._task_progress_by_id.pop(key, None)
        # Keep legacy behavior: the selected view mirrors the restored
        # conversation (production restores the selection; tests restore
        # explicitly to inspect persistence).
        self._task_plan = restored
        self._task_plan_current = False
        self._activity_steps = []
        self._activity_items = []
        self._reset_trace_state()
        self._turn_segments = []
        self._turn_text = ""
        self._segment_cursor = 0
        self._restoring_turn_history = True
        self._reasoning_text = ""
        self._activity_elapsed_seconds = 0
        rows = self._database.latest_turn_events(conversation_id)
        if not rows:
            self._restoring_turn_history = False
            return
        try:
            started_at = datetime.fromisoformat(str(rows[0]["created_at"] or ""))
            finished_at = datetime.fromisoformat(str(rows[-1]["created_at"] or ""))
            self._activity_elapsed_seconds = max(
                0, int((finished_at - started_at).total_seconds())
            )
        except (TypeError, ValueError):
            pass
        terminal = False
        try:
            for row in rows:
                kind = str(row["kind"] or "")
                text = str(row["text"] or "")
                try:
                    payload = json.loads(str(row["payload_json"] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                if kind == "reasoning_delta":
                    self._reasoning_text += text
                    self._record_trace_text_delta(
                        RuntimeEvent(conversation_id, kind, text, payload),
                        item_type="reasoning",
                    )
                elif kind == "assistant_delta":
                    if str(payload.get("phase") or "") == "commentary":
                        self._record_trace_text_delta(
                            RuntimeEvent(conversation_id, kind, text, payload),
                            item_type="commentary",
                        )
                    else:
                        self._turn_text += text
                        self._streaming_text += text
                        self._displayed_streaming_text += text
                        self._advance_default_activity()
                else:
                    if kind == "task_plan_updated":
                        continue  # Already restored across turns, with original timestamps.
                    self._record_execution_event(
                        RuntimeEvent(conversation_id, kind, text, payload),
                        emit_state=False,
                    )
                if kind in {
                    "turn_completed",
                    "orchestration_completed",
                    "orchestration_cancelled",
                    "turn_recovered",
                }:
                    terminal = True
        finally:
            self._restoring_turn_history = False
        current_in_latest = (
            any(str(row["kind"]) == "task_plan_updated" for row in rows)
            and not terminal
            and key in self._active_turns
        )
        self._task_plan_current_by_id[key] = current_in_latest
        self._task_plan_current = current_in_latest
        # Recompute cached active progress (only visible while running).
        from ...task_plan import derive_task_progress as _derive_progress

        plan = self._task_plans.get(key)
        progress = _derive_progress(plan.steps if plan is not None else [])
        if progress is None or not current_in_latest:
            self._task_progress_by_id.pop(key, None)
        else:
            self._task_progress_by_id[key] = dict(progress)
        self._update_conversation_task_item(key)
        if not self._activity_steps and any(
            str(row["kind"] or "") in {"turn_started", "assistant_delta"}
            for row in rows
        ):
            self._activity_steps = self._default_activity_steps()
        if terminal:
            for step in self._activity_steps:
                if step.get("state") not in {"error", "cancelled"}:
                    step["state"] = "completed"
            for item in self._activity_items:
                if item.get("state") == "running":
                    item["state"] = "completed"
            for item in self._trace_items:
                if item.get("state") == "running":
                    item["state"] = "completed"


    def _next_trace_id(self, prefix: str) -> str:
        self._trace_sequence += 1
        return f"{prefix}-{self._trace_sequence}"


    @staticmethod
    def _trace_payload_item(payload: dict[str, Any]) -> dict[str, Any]:
        item = payload.get("item") or payload.get("part") or {}
        return item if isinstance(item, dict) else {}


    def _record_trace_text_delta(
        self, event: RuntimeEvent, *, item_type: str
    ) -> None:
        text = str(event.text or "")
        if not text:
            return
        payload = dict(event.payload or {})
        raw_item = self._trace_payload_item(payload)
        method = str(payload.get("method") or "")
        effective_type = "plan" if method == "item/plan/delta" else item_type
        identifier = str(
            payload.get("itemId")
            or payload.get("item_id")
            or raw_item.get("id")
            or ""
        )
        summary_index = payload.get("summaryIndex")
        identity = identifier
        if effective_type == "reasoning" and summary_index is not None:
            identity = f"{identifier}:{summary_index}"
        candidate = next(
            (
                item
                for item in reversed(self._trace_items)
                if identity
                and item.get("sourceId") == identity
                and item.get("kind") == "commentary"
            ),
            None,
        )
        if candidate is None and not identity:
            last = self._trace_items[-1] if self._trace_items else None
            if (
                last is not None
                and last.get("kind") == "commentary"
                and last.get("itemType") == effective_type
                and last.get("state") == "running"
            ):
                candidate = last
        if candidate is None:
            candidate = {
                "id": self._next_trace_id(effective_type),
                "sourceId": identity,
                "kind": "commentary",
                "itemType": effective_type,
                "text": "",
                "detail": "",
                "state": "running",
            }
            self._trace_items.append(candidate)
        candidate["text"] = str(candidate.get("text") or "") + text
        candidate["state"] = "running"
        self._trace_items = self._trace_items[-80:]


    def _trace_display_path(self, raw_path: str) -> str:
        value = str(raw_path or "").strip()
        if not value:
            return ""
        path = Path(value)
        workspace = Path(str(self._selected.get("workspace") or ""))
        if path.is_absolute() and str(workspace):
            try:
                return str(
                    path.resolve(strict=False).relative_to(
                        workspace.resolve(strict=False)
                    )
                ).replace("\\", "/")
            except ValueError:
                pass
        return value.replace("\\", "/")


    @staticmethod
    def _trace_folder_summary(files: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = {}
        for item in files:
            path = str(item.get("path") or "")
            parts = [part for part in path.split("/") if part]
            folder = parts[0] if len(parts) > 1 else "raiz"
            counts[folder] = counts.get(folder, 0) + 1
        return " · ".join(f"{name} {count}" for name, count in counts.items())


    def _record_trace_file_changes(
        self,
        item: dict[str, Any],
        identifier: str,
        state: str,
    ) -> None:
        changes = item.get("changes") or []
        if not isinstance(changes, list):
            changes = []
        card = next(
            (entry for entry in self._trace_items if entry.get("kind") == "file_changes"),
            None,
        )
        if card is None:
            card = {
                "id": self._next_trace_id("files"),
                "sourceId": identifier,
                "kind": "file_changes",
                "itemType": "fileChange",
                "text": "Arquivos alterados",
                "detail": "",
                "state": state,
                "files": [],
                "fileCount": 0,
                "additions": 0,
                "deletions": 0,
                "folderSummary": "",
                "hasDiff": False,
            }
            self._trace_items.append(card)
        known = {
            str(entry.get("path") or ""): dict(entry)
            for entry in card.get("files") or []
            if isinstance(entry, dict)
        }
        for raw_change in changes:
            if not isinstance(raw_change, dict):
                continue
            path = self._trace_display_path(str(raw_change.get("path") or ""))
            if not path:
                continue
            diff = str(raw_change.get("diff") or "")
            additions, deletions = self._diff_line_counts(diff)
            known[path] = {
                "path": path,
                "name": Path(path).name or path,
                "kind": str(raw_change.get("kind") or "update"),
                "diff": diff[:20000],
                "additions": additions,
                "deletions": deletions,
            }
        files = list(known.values())
        card["files"] = files
        card["fileCount"] = len(files)
        card["additions"] = sum(int(entry.get("additions") or 0) for entry in files)
        card["deletions"] = sum(int(entry.get("deletions") or 0) for entry in files)
        card["folderSummary"] = self._trace_folder_summary(files)
        card["hasDiff"] = any(str(entry.get("diff") or "") for entry in files)
        card["detail"] = "\n\n".join(
            f"{entry['path']}\n{entry['diff']}" for entry in files if entry.get("diff")
        )[:40000]
        card["text"] = (
            f"{len(files)} arquivo" + ("s alterados" if len(files) != 1 else " alterado")
            if files
            else "Arquivos alterados"
        )
        card["state"] = state


    @staticmethod
    def _trace_action_label(item_type: str, count: int) -> str:
        plural = count != 1
        if item_type == "commandExecution":
            return f"Executou {count} comando" + ("s" if plural else "")
        if item_type in {"webSearch", "web_search"}:
            return "Pesquisou na web" if count == 1 else f"Fez {count} pesquisas na web"
        if item_type == "mcpToolCall":
            return f"Usou {count} ferramenta MCP" + ("s" if plural else "")
        return f"Usou {count} ferramenta" + ("s" if plural else "")


    def _record_trace_tool_item(
        self,
        item: dict[str, Any],
        identifier: str,
        lifecycle: str,
        state: str,
        detail: str,
    ) -> None:
        item_type = str(item.get("type") or "")
        if item_type == "agentMessage":
            phase = str(item.get("phase") or "")
            authoritative = str(item.get("text") or "")
            if phase == "commentary" and authoritative:
                source = str(item.get("id") or identifier)
                existing = next(
                    (
                        entry
                        for entry in reversed(self._trace_items)
                        if entry.get("kind") == "commentary"
                        and entry.get("sourceId") == source
                    ),
                    None,
                )
                if existing is None:
                    existing = {
                        "id": self._next_trace_id("commentary"),
                        "sourceId": source,
                        "kind": "commentary",
                        "itemType": "commentary",
                        "text": authoritative,
                        "detail": "",
                        "state": state,
                    }
                    self._trace_items.append(existing)
                elif lifecycle.endswith("completed"):
                    existing["text"] = authoritative
                    existing["state"] = state
            return
        if item_type == "reasoning":
            if lifecycle.endswith("completed"):
                for entry in reversed(self._trace_items):
                    if entry.get("kind") != "commentary" or entry.get("itemType") not in {
                        "reasoning",
                        "plan",
                    }:
                        continue
                    if identifier and not str(entry.get("sourceId") or "").startswith(
                        identifier
                    ):
                        continue
                    entry["state"] = state
                    if identifier:
                        break
            return
        if item_type == "fileChange":
            self._record_trace_file_changes(item, identifier, state)
            return
        category = item_type or "tool"
        target = next(
            (
                entry
                for entry in reversed(self._trace_items)
                if identifier
                and identifier in list(entry.get("memberIds") or [])
            ),
            None,
        )
        if target is None:
            last = self._trace_items[-1] if self._trace_items else None
            if (
                last is not None
                and last.get("kind") == "action_group"
                and last.get("itemType") == category
                and (identifier or not lifecycle.endswith("completed"))
            ):
                target = last
        if target is None:
            target = {
                "id": self._next_trace_id("actions"),
                "sourceId": identifier,
                "kind": "action_group",
                "itemType": category,
                "text": "",
                "detail": "",
                "state": state,
                "memberIds": [],
            }
            self._trace_items.append(target)
        members = list(target.get("memberIds") or [])
        if identifier and identifier not in members:
            members.append(identifier)
        target["memberIds"] = members
        count = len(members) or 1
        target["text"] = self._trace_action_label(category, count)
        if detail:
            details = [part for part in str(target.get("detail") or "").split("\n\n") if part]
            if detail not in details:
                details.append(detail)
            target["detail"] = "\n\n".join(details)[:12000]
        target["state"] = state
        self._trace_items = self._trace_items[-80:]


    def _record_trace_status_event(self, event: RuntimeEvent, message: str) -> None:
        if not message:
            return
        base_kind = str(event.kind or "")
        for suffix in ("_started", "_completed", "_failed"):
            if base_kind.endswith(suffix):
                base_kind = base_kind[: -len(suffix)]
                break
        source = str(
            event.payload.get("agent_id")
            or event.payload.get("id")
            or event.payload.get("run_id")
            or base_kind
        )
        existing = next(
            (
                item
                for item in reversed(self._trace_items)
                if item.get("kind") == "status" and item.get("sourceId") == source
            ),
            None,
        )
        if existing is None:
            existing = {
                "id": self._next_trace_id("status"),
                "sourceId": source,
                "kind": "status",
                "itemType": base_kind,
                "text": message,
                "detail": "",
                "state": self._event_state(event.kind),
            }
            self._trace_items.append(existing)
        else:
            existing["text"] = message
            existing["state"] = self._event_state(event.kind)
        self._trace_items = self._trace_items[-80:]


    def _upsert_agent(
        self,
        payload: dict[str, Any],
        status: str,
        *,
        output: str = "",
        delta: str = "",
    ) -> None:
        identifier = str(
            payload.get("agent_id")
            or payload.get("id")
            or payload.get("assignment_id")
            or ""
        )
        if not identifier:
            return
        item = next(
            (candidate for candidate in self._agent_items if candidate["agentId"] == identifier),
            None,
        )
        model = payload.get("model") or {}
        if not isinstance(model, dict):
            model = {}
        if item is None:
            label = str(
                payload.get("label")
                or payload.get("worker_name")
                or payload.get("agent")
                or "Agente VR"
            )
            if label.startswith("Mary "):
                label = "VR " + label.removeprefix("Mary ")
            item = {
                "agentId": identifier,
                "label": label,
                "model": str(
                    model.get("display_name")
                    or model.get("model")
                    or model.get("provider")
                    or "Automático"
                ),
                "effort": str(payload.get("effort") or "medium"),
                "status": status,
                "statusLabel": status.title(),
                "task": str(payload.get("task") or ""),
                "reason": str(payload.get("reason") or ""),
                "module": str(payload.get("module") or ""),
                "source": str(payload.get("source") or "").upper(),
                "parentId": str(payload.get("parent_id") or ""),
                "final": bool(payload.get("final")),
                "output": "",
            }
            self._agent_items.append(item)
        else:
            item["status"] = status
            item["statusLabel"] = status.title()
            for source_key, target_key in (
                ("task", "task"),
                ("reason", "reason"),
                ("module", "module"),
                ("parent_id", "parentId"),
            ):
                value = str(payload.get(source_key) or "")
                if value:
                    item[target_key] = value
            if payload.get("source"):
                item["source"] = str(payload["source"]).upper()
        if output:
            item["output"] = output
        elif delta:
            item["output"] = str(item.get("output") or "") + str(delta)


    @staticmethod
    def _extract_tool_entry(event: RuntimeEvent) -> dict[str, Any] | None:
        payload = dict(event.payload or {})
        raw_item = payload.get("item") or payload.get("part") or {}
        if not raw_item and any(key in payload for key in ("name", "tool", "input", "command", "step_type")):
            raw_item = payload
        item = raw_item if isinstance(raw_item, dict) else {}
        item_type = str(item.get("type") or item.get("step_type") or payload.get("step_type") or "tool")
        if item_type in {"agentMessage", "userMessage", "reasoning", "thinking"}:
            return None
        identity = str(
            item.get("id")
            or payload.get("itemId")
            or payload.get("toolCallId")
            or payload.get("callId")
            or payload.get("runtime_event_id")
            or payload.get("request_id")
            or "tool"
        )
        lifecycle = str(payload.get("lifecycle") or "")
        complete = (
            lifecycle.endswith("completed")
            or item.get("status") in {"completed", "error", "failed"}
            or payload.get("success") is not None
        )
        state = (
            "error"
            if payload.get("success") is False or item.get("status") in {"error", "failed"}
            else "completed"
            if complete
            else "running"
        )
        detail = str(
            item.get("command")
            or item.get("arguments")
            or item.get("input")
            or payload.get("arguments")
            or item.get("output")
            or payload.get("output")
            or ""
        )[:8000]
        label = short_event_text(event.text or item.get("name") or item.get("tool") or item_type)
        return {
            "id": identity,
            "kind": "tool",
            "itemType": item_type,
            "text": label,
            "detail": detail,
            "state": state,
        }

    @staticmethod
    def _execution_activity(event: RuntimeEvent) -> dict[str, Any] | None:
        entry = ActivityDomain._extract_tool_entry(event)
        if entry is None:
            return None
        eid = event.payload.get("execution_id") or 0
        key = f"activity:{eid}:0"
        return {
            "messageId": -2,
            "role": "activity",
            "content": "",
            "displayContent": "",
            "segments": [],
            "createdAt": event.created_at,
            "responseMode": "activity",
            "messageKey": key,
            "isStreaming": entry["state"] == "running",
            "activityData": [entry],
        }


    @staticmethod
    def _activity_timeline_item() -> dict[str, Any]:
        return {
            "messageId": -2,
            "role": "activity",
            "content": "",
            "displayContent": "",
            "segments": [],
            "createdAt": "",
            "responseMode": "activity",
            "messageKey": "",
            "isStreaming": False,
        }

from __future__ import annotations
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from PySide6.QtCore import (
    QUrl,
)
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog
from ...workspace import is_managed_conversation_workspace

from .presentation import (markdown_for_display, segments_for_display, STATUS_LABELS)

class ConversationsDomain:
    """Domain operations using the facade as the sole state and transaction owner."""
    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        return getattr(self._owner, name)

    def __setattr__(self, name, value):
        setattr(self._owner, name, value)

    def _selected_conversation_id(self) -> str:
        return str(self._selected.get("conversationId") or "")


    def setProject(self, index: int) -> None:  # noqa: N802
        if index < 0 or index >= len(self._projects):
            return
        if index == self._current_project_index:
            return
        selected_id = str(self._selected.get("conversationId") or "")
        self._current_project_index = index
        raw_path = self._projects[index]["path"]
        self._project_scope = Path(raw_path).resolve(strict=False) if raw_path else None
        self._invalidate_file_suggestions()
        self._preferences.setValue("chat/current_project", raw_path)
        self._preferences.sync()
        self.projectsChanged.emit()
        if self._draft:
            self.selectionChanged.emit()
        self._apply_filter(selected_id)


    def renameProject(self, index: int, name: str) -> bool:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return False
        label = " ".join(str(name or "").split())
        if not label:
            return False
        target_path = str(Path(self._projects[index]["path"]).resolve(strict=False))
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == Path(
                target_path
            ):
                item["label"] = label
                break
        else:
            values.append({"path": target_path, "label": label})
        self._store_project_entries(values)
        self._refresh_projects()
        self.refresh()
        return True


    def openProjectFolder(self, index: int) -> bool:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return False
        path = Path(self._projects[index]["path"]).resolve(strict=False)
        if not path.is_dir():
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))


    def copyProjectPath(self, index: int) -> None:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return
        path = str(self._projects[index]["path"])
        QGuiApplication.clipboard().setText(path)
        self.messageCopied.emit(path)


    #: Nomes de ícone aceitos no seletor (devem existir em VrLineIcon.qml).
    PROJECT_ICON_KINDS = frozenset(
        {
            "folder",
            "folderPlus",
            "files",
            "file",
            "browser",
            "globe",
            "terminal",
            "code",
            "database",
            "layers",
            "cube",
            "models",
            "image",
            "context",
            "agents",
            "task",
            "listTodo",
            "branch",
            "star",
            "eye",
            "lock",
            "archive",
            "gauge",
            "trendUp",
            "auto",
            "paintbrush",
            "react",
            "attachment",
            "search",
            "settings",
            "pin",
            "plus",
            "check",
            "edit",
            "copy",
            "external",
            "newChat",
        }
    )

    def chooseProjectIcon(self, index: int) -> str:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return ""
        project_path = Path(self._projects[index]["path"]).resolve(strict=False)
        selected, _filter = QFileDialog.getOpenFileName(
            None,
            "Escolher ícone do projeto",
            str(project_path),
            "Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.ico)",
        )
        if not selected:
            return ""
        icon_path = str(Path(selected).expanduser().resolve(strict=False))
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == project_path:
                item["icon"] = icon_path
                item["iconKind"] = ""
                item["iconEmoji"] = ""
                item["iconText"] = ""
                break
        else:
            values.append(
                {
                    "path": str(project_path),
                    "label": self._projects[index]["label"],
                    "icon": icon_path,
                    "iconKind": "",
                    "iconEmoji": "",
                    "iconText": "",
                }
            )
        self._store_project_entries(values)
        self._refresh_projects()
        return icon_path


    def setProjectIconEmoji(self, index: int, emoji: str) -> bool:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return False
        value = str(emoji or "").strip()
        # Aceita um único grapheme (emoji pode ter 2+ codepoints: família, bandeira, ZWJ).
        if len(value) > 12:
            return False
        project_path = Path(self._projects[index]["path"]).resolve(strict=False)
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == project_path:
                item["iconEmoji"] = value
                if value:
                    item["icon"] = ""
                    item["iconKind"] = ""
                    item["iconText"] = ""
                break
        else:
            values.append(
                {
                    "path": str(project_path),
                    "label": self._projects[index]["label"],
                    "icon": "",
                    "iconKind": "",
                    "iconEmoji": value,
                    "iconText": "",
                }
            )
        self._store_project_entries(values)
        self._refresh_projects()
        return True


    def setProjectIconColor(self, index: int, color: str) -> bool:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return False
        raw = str(color or "").strip()
        if raw and not self._is_valid_icon_color(raw):
            return False
        project_path = Path(self._projects[index]["path"]).resolve(strict=False)
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == project_path:
                item["iconColor"] = raw
                break
        else:
            values.append(
                {
                    "path": str(project_path),
                    "label": self._projects[index]["label"],
                    "iconColor": raw,
                }
            )
        self._store_project_entries(values)
        self._refresh_projects()
        return True


    def clearProjectIcon(self, index: int) -> bool:  # noqa: N802
        """Volta ao ícone automático estilo T3 Code (monograma derivado do nome)."""
        if index <= 0 or index >= len(self._projects):
            return False
        project_path = Path(self._projects[index]["path"]).resolve(strict=False)
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == project_path:
                item["icon"] = ""
                item["iconKind"] = ""
                item["iconEmoji"] = ""
                item["iconColor"] = ""
                item["iconText"] = ""
                break
        else:
            return True
        self._store_project_entries(values)
        self._refresh_projects()
        return True


    def setProjectIconKind(self, index: int, kind: str) -> bool:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return False
        value = str(kind or "").strip()
        if value and value not in self.PROJECT_ICON_KINDS:
            return False
        project_path = Path(self._projects[index]["path"]).resolve(strict=False)
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == project_path:
                item["iconKind"] = value
                if value:
                    item["icon"] = ""
                    item["iconEmoji"] = ""
                    item["iconText"] = ""
                break
        else:
            values.append(
                {
                    "path": str(project_path),
                    "label": self._projects[index]["label"],
                    "iconKind": value,
                }
            )
        self._store_project_entries(values)
        self._refresh_projects()
        return True


    def setProjectIconText(self, index: int, text: str) -> bool:  # noqa: N802
        """Monograma personalizado (1-2 caracteres); vazio volta a derivar do nome."""
        if index <= 0 or index >= len(self._projects):
            return False
        value = " ".join(str(text or "").split())
        if len(value) > 2:
            return False
        project_path = Path(self._projects[index]["path"]).resolve(strict=False)
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == project_path:
                item["iconText"] = value
                if value:
                    item["icon"] = ""
                    item["iconKind"] = ""
                    item["iconEmoji"] = ""
                break
        else:
            values.append(
                {
                    "path": str(project_path),
                    "label": self._projects[index]["label"],
                    "iconText": value,
                }
            )
        self._store_project_entries(values)
        self._refresh_projects()
        return True


    def applyProjectIcon(  # noqa: N802
        self, index: int, kind: str = "", color: str = "", emoji: str = "", text: str = ""
    ) -> bool:
        """Aplica o resultado do seletor de ícones de uma vez (vazio limpa o campo)."""
        if index <= 0 or index >= len(self._projects):
            return False
        clean_kind = str(kind or "").strip()
        clean_color = str(color or "").strip()
        clean_emoji = str(emoji or "").strip()
        clean_text = " ".join(str(text or "").split())
        if clean_kind and clean_kind not in self.PROJECT_ICON_KINDS:
            return False
        if clean_color and not self._is_valid_icon_color(clean_color):
            return False
        if len(clean_emoji) > 12 or len(clean_text) > 2:
            return False
        project_path = Path(self._projects[index]["path"]).resolve(strict=False)
        values = self._stored_project_entries()
        for item in values:
            raw_path = str(item.get("path") or "").strip()
            if raw_path and Path(raw_path).expanduser().resolve(strict=False) == project_path:
                item["icon"] = ""
                item["iconKind"] = clean_kind
                item["iconColor"] = clean_color
                item["iconEmoji"] = clean_emoji
                item["iconText"] = clean_text
                break
        else:
            values.append(
                {
                    "path": str(project_path),
                    "label": self._projects[index]["label"],
                    "icon": "",
                    "iconKind": clean_kind,
                    "iconColor": clean_color,
                    "iconEmoji": clean_emoji,
                    "iconText": clean_text,
                }
            )
        self._store_project_entries(values)
        self._refresh_projects()
        return True


    @staticmethod
    def _is_valid_icon_color(value: str) -> bool:
        raw = value.strip()
        if len(raw) == 4 and raw.startswith("#"):
            return all(c in "0123456789abcdefABCDEF" for c in raw[1:])
        if len(raw) == 7 and raw.startswith("#"):
            return all(c in "0123456789abcdefABCDEF" for c in raw[1:])
        return False


    def removeProject(self, index: int) -> bool:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return False
        target = Path(self._projects[index]["path"]).resolve(strict=False)
        hidden = self._stored_project_paths("chat/hidden_projects")
        if target not in hidden:
            hidden.append(target)
            self._preferences.setValue(
                "chat/hidden_projects",
                json.dumps([str(path) for path in hidden], ensure_ascii=False),
            )
        values = [
            item
            for item in self._stored_project_entries()
            if Path(item["path"]).expanduser().resolve(strict=False) != target
        ]
        self._store_project_entries(values)
        self._preferences.setValue("chat/current_project", "")
        self._preferences.sync()
        self._refresh_projects()
        self.refresh()
        return True


    def _load_draft_records(self) -> dict[str, dict[str, Any]]:
        raw = self._preferences.value("chat/drafts", "{}")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return {
            str(key): dict(value)
            for key, value in values.items()
            if str(key).strip() and isinstance(value, dict)
        }


    def _persist_draft_records(self) -> None:
        self._preferences.setValue(
            "chat/drafts",
            json.dumps(self._draft_records, ensure_ascii=False, sort_keys=True),
        )
        self._preferences.sync()


    def _load_pinned_conversation_ids(self) -> set[str]:
        raw = self._preferences.value("chat/pinned_conversations", "[]")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else list(raw or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            return set()
        return {str(value) for value in values if str(value).strip()}


    def _persist_pinned_conversation_ids(self) -> None:
        self._preferences.setValue(
            "chat/pinned_conversations",
            json.dumps(sorted(self._pinned_conversation_ids), ensure_ascii=False),
        )
        self._preferences.sync()


    def saveCurrentDraft(self, text: str) -> bool:  # noqa: N802
        content = str(text or "")
        conversation_id = self._selected_conversation_id()
        if not content.strip() and not self._attachments:
            if conversation_id and conversation_id in self._draft_records:
                self._draft_records.pop(conversation_id, None)
                self._persist_draft_records()
                self.refresh()
            return False
        if not conversation_id:
            workspace = self._project_scope or self._settings.root
            try:
                conversation_id = self._orchestrator.new_conversation(
                    self._provider,
                    self._model,
                    self._effort,
                    service_tier=self._service_tier,
                    approval_profile=self._approval_profile,
                    defer_provider_start=True,
                    workspace=workspace,
                    vr_mode=self._vr_mode,
                )
            except Exception as exc:
                self._status_text = f"Falha ao salvar rascunho: {exc}"
                self.stateChanged.emit()
                return False
        attachments = [dict(item) for item in self._attachments]
        self._draft_records[conversation_id] = {
            "text": content,
            "attachments": attachments,
            "savedAt": datetime.now().astimezone().isoformat(),
            "vr_mode": self._vr_mode,
        }
        row = self._database.get_conversation(conversation_id)
        has_messages = bool(self._database.messages(conversation_id))
        if row is not None and not has_messages:
            first_line = next(
                (line.strip() for line in content.splitlines() if line.strip()), ""
            )
            title = first_line or (attachments[0]["name"] if attachments else "Nova conversa")
            self._database.update_conversation(
                conversation_id, title=title[:72].rstrip()
            )
        self._persist_draft_records()
        self.refresh()
        return True


    def discardDraft(self, conversation_id: str = "") -> bool:  # noqa: N802
        cid = str(conversation_id or "").strip() or self._selected_conversation_id()
        if not cid:
            return False
        had_draft = cid in self._draft_records
        self._draft_records.pop(cid, None)
        self._persist_draft_records()

        is_current = cid == self._selected_conversation_id()
        row = self._database.get_conversation(cid)
        has_messages = bool(self._database.messages(cid))

        if is_current:
            self._attachments = []
            self.draftRestored.emit("")

        if row is None or not has_messages:
            self._pinned_conversation_ids.discard(cid)
            self._persist_pinned_conversation_ids()
            self._active_turn_started_epochs.pop(cid, None)
            if is_current:
                self.startNewChat()
            if row is not None:
                try:
                    self._orchestrator.trash(cid)
                except Exception:
                    pass
        elif is_current:
            self._vr_mode = self._normalize_vr_mode(row["vr_mode"]) or (
                "vr" if bool(row["vr_enabled"]) else "off"
            )
            self._sync_selected_turn_state()
            self._reload_selected_messages()

        self.refresh()
        self.stateChanged.emit()
        self.selectionChanged.emit()
        return had_draft


    def copyMessage(self, index: int) -> None:  # noqa: N802
        message = self._messages.item(index)
        application = QGuiApplication.instance()
        if message is None or application is None:
            return
        content = str(message.get("content") or "")
        application.clipboard().setText(content)
        self.messageCopied.emit(content)


    def copyConversation(self) -> None:  # noqa: N802
        """Copy every message, including rows outside the virtualized viewport."""
        application = QGuiApplication.instance()
        if application is None:
            return
        parts = []
        for index in range(self._messages.rowCount()):
            message = self._messages.item(index) or {}
            role = str(message.get("role") or "")
            content = str(message.get("content") or "")
            if role == "activity" or not content:
                continue
            label = {"user": "Você", "assistant": "VR"}.get(role, role)
            parts.append(f"{label}:\n{content}")
        content = "\n\n".join(parts)
        application.clipboard().setText(content)
        self.messageCopied.emit(content)


    def selectConversation(self, index: int) -> None:  # noqa: N802
        selected = self._conversations.item(index)
        if selected is None:
            self._clear_selection()
            return
        if index == self._selected_index and selected == self._selected:
            return
        previous_id = str(self._selected.get("conversationId") or "")
        changing_conversation = previous_id != str(selected.get("conversationId") or "")
        self._draft = False
        if changing_conversation:
            self._finalize_pending_terminal_before_new_turn()
            self._reset_stream_state()
            self._activity_steps = []
            # Detach the selected view; per-conversation plans in
            # _task_plans survive so background turns keep their state.
            # The following restore repopulates the new selection from DB.
            from ...task_plan import TaskPlan as _TaskPlan

            self._task_plan = _TaskPlan()
            self._task_plan_current = False
            self._activity_items = []
            self._reset_trace_state()
            self._turn_segments = []
            self._turn_text = ""
            self._segment_cursor = 0
            self._reasoning_text = ""
            self._activity_elapsed_seconds = 0
            self._agent_items = []
            self._invalidate_file_suggestions()
        self._selected_index = index
        self._selected = dict(selected)
        draft_record = self._draft_records.get(str(selected["conversationId"]))
        if changing_conversation:
            if draft_record is not None:
                self._attachments = [
                    {
                        "name": str(item.get("name") or Path(str(item.get("path") or "")).name),
                        "path": str(item.get("path") or ""),
                    }
                    for item in list(draft_record.get("attachments") or [])
                    if isinstance(item, dict) and str(item.get("path") or "")
                ]
                self.draftRestored.emit(str(draft_record.get("text") or ""))
            else:
                self._attachments = []
                self.draftRestored.emit("")
        row = self._database.get_conversation(str(selected["conversationId"]))
        if row is not None:
            self._provider = str(row["provider"] or "codex")
            self._model = str(row["model"] or "")
            self._effort = str(row["effort"] or "medium")
            self._service_tier = str(row["service_tier"] or "")
            self._approval_profile = str(row["approval_profile"] or "full_access")
            self._vr_mode = self._normalize_vr_mode(row["vr_mode"]) or (
                "vr" if bool(row["vr_enabled"]) else "off"
            )
            if draft_record is not None and draft_record.get("vr_mode"):
                self._vr_mode = (
                    self._normalize_vr_mode(draft_record.get("vr_mode"))
                    or self._vr_mode
                )
            self._remember_current_chat_options()
        if changing_conversation:
            self._restore_activity_from_history(str(selected["conversationId"]))
        self._sync_selected_turn_state()
        if changing_conversation and self.turnRunning:
            self._status_text = "Executando…"
            self._activity_started_at = (
                time.monotonic() - self._activity_elapsed_seconds
            )
            self._activity_clock.start()
        elif changing_conversation:
            status = str(selected.get("status") or "idle")
            self._status_text = STATUS_LABELS.get(status, status.title())
        self._reload_selected_messages()
        if changing_conversation and self.turnRunning and self._streaming_text:
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
        self.stateChanged.emit()


    def selectConversationId(self, conversation_id: str) -> None:  # noqa: N802
        target = str(conversation_id or "")
        index = next(
            (
                item_index
                for item_index, item in enumerate(self._conversations._items)
                if str(item.get("conversationId") or "") == target
            ),
            -1,
        )
        if index >= 0:
            self.selectConversation(index)


    def addProject(self) -> str:  # noqa: N802
        selected = QFileDialog.getExistingDirectory(
            None,
            "Adicionar projeto ao Chat VR",
            str(self._settings.root),
        )
        if not selected:
            return ""
        return self._add_project_path(Path(selected))


    def beginProjectFolderBrowse(self) -> None:  # noqa: N802
        self._set_project_folder(Path.home())


    def browseProjectFolder(self, value: str) -> None:  # noqa: N802
        raw = str(value or "").strip()
        if not raw:
            return
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self._project_folder / candidate
        self._set_project_folder(candidate)


    def browseParentProjectFolder(self) -> None:  # noqa: N802
        self._set_project_folder(self._project_folder.parent)


    def addCurrentProjectFolder(self) -> str:  # noqa: N802
        return self._add_project_path(self._project_folder)


    def openCurrentProjectFolder(self) -> None:  # noqa: N802
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._project_folder)))


    def _set_project_folder(self, value: Path) -> None:
        path = value.expanduser().resolve(strict=False)
        if not path.is_dir():
            return
        items: list[dict[str, str]] = []
        try:
            children = sorted(
                (child for child in path.iterdir() if child.is_dir()),
                key=lambda child: child.name.casefold(),
            )
        except OSError:
            children = []
        for child in children:
            items.append({"label": child.name, "path": str(child)})
        self._project_folder = path
        self._project_folder_items = items
        self.projectFolderChanged.emit()


    def _add_project_path(self, selected: Path) -> str:
        path = selected.expanduser().resolve(strict=False)
        if not path.is_dir():
            return ""
        values = self._stored_project_entries()
        stored = [item.get("path", "") if isinstance(item, dict) else item for item in values]
        if str(path) not in stored:
            values.append({"path": str(path)})
            self._store_project_entries(values)
        hidden = self._stored_project_paths("chat/hidden_projects")
        if path in hidden:
            self._preferences.setValue(
                "chat/hidden_projects",
                json.dumps(
                    [str(item) for item in hidden if item != path], ensure_ascii=False
                ),
            )
            self._preferences.sync()
        self._refresh_projects()
        target = next(
            (index for index, item in enumerate(self._projects) if item["path"] == str(path)),
            0,
        )
        self.setProject(target)
        return str(path)


    def _stored_project_entries(self) -> list[dict[str, str]]:
        raw = self._preferences.value("chat/projects", "[]")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else list(raw or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        entries: list[dict[str, str]] = []
        for value in values:
            if isinstance(value, dict):
                path = str(value.get("path") or "").strip()
                label = str(value.get("label") or "").strip()
                icon = str(value.get("icon") or "").strip()
                icon_kind = str(value.get("iconKind") or value.get("icon_kind") or "").strip()
                icon_emoji = str(value.get("iconEmoji") or value.get("icon_emoji") or "").strip()
                icon_color = str(value.get("iconColor") or value.get("icon_color") or "").strip()
                icon_text = str(value.get("iconText") or value.get("icon_text") or "").strip()
            else:
                path = str(value or "").strip()
                label = ""
                icon = ""
                icon_kind = ""
                icon_emoji = ""
                icon_color = ""
                icon_text = ""
            if path:
                entries.append(
                    {
                        "path": path,
                        "label": label,
                        "icon": icon,
                        "iconKind": icon_kind,
                        "iconEmoji": icon_emoji,
                        "iconColor": icon_color,
                        "iconText": icon_text,
                    }
                )
        return entries


    def _stored_project_paths(self, key: str) -> list[Path]:
        raw = self._preferences.value(key, "[]")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else list(raw or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        paths: list[Path] = []
        for value in values:
            candidate = Path(str(value or "")).expanduser().resolve(strict=False)
            if str(value or "").strip() and candidate not in paths:
                paths.append(candidate)
        return paths


    def _store_project_entries(self, values: list[dict[str, str]]) -> None:
        self._preferences.setValue(
            "chat/projects", json.dumps(values, ensure_ascii=False)
        )
        self._preferences.sync()


    def togglePinnedConversation(self, conversation_id: str) -> None:  # noqa: N802
        """Toggle pin for the explicitly targeted conversation (no reselection)."""
        cid = str(conversation_id or "").strip()
        if not cid:
            return
        if self._database.get_conversation(cid) is None:
            return
        if cid in self._pinned_conversation_ids:
            self._pinned_conversation_ids.remove(cid)
        else:
            self._pinned_conversation_ids.add(cid)
        self._persist_pinned_conversation_ids()
        self.refresh()
        self.selectionChanged.emit()

    def archiveConversation(self, conversation_id: str) -> None:  # noqa: N802
        """Archive the explicitly targeted conversation (no reselection).

        Running state is evaluated per target: a persisted ``running``
        status blocks only that same conversation.
        """
        cid = str(conversation_id or "").strip()
        if not cid:
            return
        if cid in self._active_turns:
            row = self._database.get_conversation(cid)
            if row is not None and str(row["status"] or "idle") == "running":
                return
            # Residual frontend state; reconcile instead of blocking.
            self._active_turns.discard(cid)
            self._active_turn_started_epochs.pop(cid, None)
        else:
            row = self._database.get_conversation(cid)
            if row is not None and str(row["status"] or "idle") == "running":
                return
        try:
            self._orchestrator.archive(cid)
        except Exception as exc:
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()
            return
        self._draft_records.pop(cid, None)
        self._pinned_conversation_ids.discard(cid)
        self._persist_draft_records()
        self._persist_pinned_conversation_ids()
        was_selected = cid == self._selected_conversation_id()
        self.refresh()
        self.conversationArchived.emit(cid)
        if was_selected:
            self.startNewChat()

    def archiveCurrentConversation(self) -> None:  # noqa: N802
        return self.archiveConversation(self._selected_conversation_id())


    def trashConversation(self, conversation_id: str) -> None:  # noqa: N802
        """Delete the explicitly targeted conversation.

        Execution state is evaluated per ``conversation_id``: a running turn
        blocks only the deletion of that same conversation. Stale frontend
        entries (``_active_turns`` holding an id whose persisted status is no
        longer ``running``) are reconciled instead of blocking the delete.
        """
        cid = str(conversation_id or "").strip()
        if not cid:
            return
        if cid in self._deleting_conversation_ids:
            return
        row = self._database.get_conversation(cid)
        if row is None:
            self.refresh()
            return
        persisted_status = str(row["status"] or "idle")
        if persisted_status == "running":
            self._status_text = "Esta conversa ainda está em execução."
            self.stateChanged.emit()
            return
        if cid in self._active_turns:
            # Residual frontend state: the turn already reached a terminal
            # status in the database but the id was never removed locally.
            # Reconcile instead of blocking an unrelated-or-finished delete.
            self._active_turns.discard(cid)
            self._active_turn_started_epochs.pop(cid, None)
        self._begin_conversation_trash(cid)

    def trashCurrentConversation(self) -> None:  # noqa: N802
        return self.trashConversation(self._selected_conversation_id())

    def _begin_conversation_trash(self, conversation_id: str) -> None:
        cid = str(conversation_id or "").strip()
        if not cid or cid in self._deleting_conversation_ids:
            return
        is_selected = cid == self._selected_conversation_id()
        self._conversation_delete_running = True
        self._conversation_delete_id = cid
        self._deleting_conversation_ids.add(cid)
        if is_selected:
            self.startNewChat()
        self.refresh()
        self._status_text = "Movendo conversa para a lixeira…"
        self.stateChanged.emit()

        def trash() -> None:
            result: dict[str, Any] = {
                "conversation_id": cid,
                "error": "",
            }
            try:
                self._orchestrator.trash(cid)
            except Exception as exc:
                result["error"] = str(exc)
            self._conversationTrashFinished.emit(result)

        threading.Thread(target=trash, daemon=True).start()


    def _finish_conversation_trash(self, value: object) -> None:
        result = dict(value) if isinstance(value, dict) else {}
        conversation_id = str(result.get("conversation_id") or "")
        error = str(result.get("error") or "")
        self._deleting_conversation_ids.discard(conversation_id)
        if conversation_id == self._conversation_delete_id:
            remaining = sorted(self._deleting_conversation_ids)
            self._conversation_delete_id = remaining[0] if remaining else ""
        if not self._deleting_conversation_ids:
            self._conversation_delete_running = False
            self._conversation_delete_id = ""
        if self._closed:
            return
        if error:
            self._status_text = f"Falha ao excluir conversa: {error}"
            self.refresh()
            self.stateChanged.emit()
            return
        self._draft_records.pop(conversation_id, None)
        self._pinned_conversation_ids.discard(conversation_id)
        self._persist_draft_records()
        self._persist_pinned_conversation_ids()
        self.refresh()
        self._status_text = "Conversa movida para a lixeira."
        self.stateChanged.emit()


    def _reload_selected_messages(self) -> None:
        conversation_id = str(self._selected.get("conversationId") or "")
        if not conversation_id:
            return
        rows = self._database.messages(conversation_id)
        if self._reload_execution_timeline(conversation_id, rows):
            self.selectionChanged.emit()
            return
        skills_by_msg = {}
        try:
            skills_by_msg = self._database.get_conversation_message_skills(conversation_id)
        except Exception:
            skills_by_msg = {}
        items = [
                {
                    "messageId": int(row["id"]),
                    "role": str(row["role"] or "assistant"),
                    "content": str(row["content"] or ""),
                    "displayContent": markdown_for_display(str(row["content"] or "")),
                    "skills": skills_by_msg.get(int(row["id"]), []),
                    "segments": segments_for_display(str(row["content"] or ""))
                    if str(row["role"] or "") == "assistant"
                    else [],
                    "createdAt": str(row["created_at"] or ""),
                    "responseMode": str(row["response_mode"] or ""),
                    "messageKey": (f"{row['execution_id']}:{row['execution_ordinal']}" if row['execution_id'] else f"db:{row['id']}"),
                    "isStreaming": False,
                }
                for row in rows
                if str(row["role"] or "") != "system"
            ]
        if (
            self._activity_steps
            or self._activity_items
            or self._trace_items
            or self._reasoning_text
        ):
            assistant_index = next(
                (
                    index
                    for index in range(len(items) - 1, -1, -1)
                    if items[index]["role"] == "assistant"
                ),
                len(items),
            )
            items.insert(assistant_index, self._activity_timeline_item())
        if self._turn_segments and items and items[-1].get("role") == "assistant":
            merged_segments = self._turn_display_segments()
            if merged_segments:
                items[-1]["segments"] = merged_segments
        self._messages.replace(items)
        self.selectionChanged.emit()


    def _refresh_projects(self) -> None:
        saved_scope = str(
            self._preferences.value("chat/current_project", "") or ""
        ).strip()
        candidates: list[Path] = []
        custom_labels: dict[Path, str] = {}
        custom_icons: dict[Path, str] = {}
        custom_kinds: dict[Path, str] = {}
        custom_emoji: dict[Path, str] = {}
        custom_colors: dict[Path, str] = {}
        custom_texts: dict[Path, str] = {}
        hidden_paths = set(self._stored_project_paths("chat/hidden_projects"))

        def include(
            value: object,
            label: object = "",
            icon: object = "",
            icon_kind: object = "",
            icon_emoji: object = "",
            icon_color: object = "",
            icon_text: object = "",
        ) -> None:
            raw = str(value or "").strip()
            if not raw:
                return
            candidate = Path(raw).expanduser().resolve(strict=False)
            if candidate in hidden_paths:
                return
            if candidate.is_dir() and candidate not in candidates:
                candidates.append(candidate)
            custom_label = " ".join(str(label or "").split())
            if candidate.is_dir() and custom_label:
                custom_labels[candidate] = custom_label
            custom_icon = str(icon or "").strip()
            if candidate.is_dir() and custom_icon:
                custom_icons[candidate] = custom_icon
            kind = str(icon_kind or "").strip()
            if candidate.is_dir() and kind:
                custom_kinds[candidate] = kind
            emoji = str(icon_emoji or "").strip()
            if candidate.is_dir() and emoji:
                custom_emoji[candidate] = emoji
            color = str(icon_color or "").strip()
            if candidate.is_dir() and color:
                custom_colors[candidate] = color
            text = " ".join(str(icon_text or "").split())
            if candidate.is_dir() and text:
                custom_texts[candidate] = text

        include(self._settings.root)

        for key in ("chat/projects", "chat/recent_projects"):
            raw_value = self._preferences.value(key, "[]")
            try:
                values = (
                    json.loads(str(raw_value))
                    if isinstance(raw_value, str)
                    else list(raw_value or [])
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                values = []
            for value in values:
                if isinstance(value, dict):
                    customized = key == "chat/projects"
                    include(
                        value.get("path", ""),
                        value.get("label", "") if customized else "",
                        value.get("icon", "") if customized else "",
                        (value.get("iconKind", value.get("icon_kind", ""))) if customized else "",
                        (value.get("iconEmoji", value.get("icon_emoji", ""))) if customized else "",
                        (value.get("iconColor", value.get("icon_color", ""))) if customized else "",
                        (value.get("iconText", value.get("icon_text", ""))) if customized else "",
                    )
                else:
                    include(value)

        for row in self._database.list_conversations(state="all"):
            workspace = self._settings.resolve_path(row["workspace"])
            if not is_managed_conversation_workspace(self._settings, workspace):
                include(workspace)

        self._projects = [
            {
                "label": "Todos os projetos",
                "path": "",
                "icon": "",
                "iconKind": "",
                "iconEmoji": "",
                "iconColor": "",
                "iconText": "",
            }
        ]
        self._projects.extend(
            {
                "label": custom_labels.get(path) or path.name or str(path),
                "path": str(path),
                "icon": custom_icons.get(path, ""),
                "iconKind": custom_kinds.get(path, ""),
                "iconEmoji": custom_emoji.get(path, ""),
                "iconColor": custom_colors.get(path, ""),
                "iconText": custom_texts.get(path, ""),
            }
            for path in candidates[:32]
        )
        self._current_project_index = next(
            (
                index
                for index, item in enumerate(self._projects)
                if saved_scope
                and item["path"]
                and Path(item["path"]).resolve(strict=False)
                == Path(saved_scope).expanduser().resolve(strict=False)
            ),
            0,
        )
        selected_path = self._projects[self._current_project_index]["path"]
        self._project_scope = (
            Path(selected_path).resolve(strict=False) if selected_path else None
        )
        self.projectsChanged.emit()

from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
)
from ..text_rendering import fenced_blocks, code_language_badge
from ...code_processing_hardware import detect_code_processing_hardware

"""Read-only presentation models for the first QML Chat VR migration slice."""


PROVIDER_LABELS = {
    "codex": "Codex",
    "claude": "Claude",
    "opencode": "OpenCode",
    "antigravity": "Antigravity",
}


STATUS_LABELS = {
    "idle": "Pronto",
    "running": "Executando",
    "error": "Falha",
    "cancelled": "Cancelado",
    "interrupted": "Interrompido",
}


EFFORT_LABELS = {
    "auto": "Auto",
    "none": "None",
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra High",
    "max": "Max",
}


_CODE_OR_URL_RE = re.compile(r"(`+.*?`+|https?://\S+)", re.DOTALL)


_GLUED_SENTENCE_RE = re.compile(
    r"(?<=[a-záàâãéêíóôõúüç][.!?])"
    r"(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][a-záàâãéêíóôõúüç])"
)


ERP_JAR_SOURCE_VR_EXEC = "vr_exec"


ERP_JAR_SOURCE_WORKSPACE = "workspace"


ERP_JAR_SOURCE_CUSTOM = "custom"


MAX_FILE_SUGGESTION_ENTRIES = 50_000


ERP_JAR_SCOPE_FULL_RELEASE = "full_release"


ERP_JAR_SCOPE_SINGLE = "single_jar"


DEFAULT_ERP_JAR_SOURCE_PATH = Path(r"C:\vr\exec")


EXPECTED_ERP_JAR_COUNT = 46


CODE_PROCESSING_HARDWARE = detect_code_processing_hardware()


CODE_PROCESSING_HEAP_OPTIONS = (1024, 2048, 4096)


CODE_PROCESSING_TIMEOUT_OPTIONS = (300, 600, 1200)


CODE_PROCESSING_CPU_CORE_OPTIONS = CODE_PROCESSING_HARDWARE.cpu_options


CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS = (5, 8, 10)


CODE_PROCESSING_WINDOW_OPTIONS = (
    {"label": "Sempre", "value": "always"},
    {"label": "Madrugada · 00h-06h", "value": "night"},
    {"label": "Fora do expediente · 18h-06h", "value": "off_hours"},
)


DEFAULT_CODE_PROCESSING_HEAP_MB = CODE_PROCESSING_HARDWARE.recommended_heap_mb


DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS = 300


DEFAULT_CODE_PROCESSING_CPU_CORES = CODE_PROCESSING_HARDWARE.recommended_cpu_cores


DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER = 10


DEFAULT_CODE_PROCESSING_WINDOW = "always"


CODE_PROCESSING_HARDWARE_PROFILE_VERSION = 2


def markdown_for_display(markdown: str) -> str:
    """Repair provider spacing without changing inline code or URLs."""

    result = []
    for block in fenced_blocks(str(markdown or "")):
        if block["kind"] == "code":
            result.append(block["raw"])
        else:
            parts = _CODE_OR_URL_RE.split(block["content"])
            result.append("".join(
                part if index % 2 else _GLUED_SENTENCE_RE.sub(" ", part)
                for index, part in enumerate(parts)
            ))
    return "".join(result)


def short_event_text(value: object, limit: int = 140) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class _MappingListModel(QAbstractListModel):
    """Small reusable model whose public surface is a fixed set of QML roles."""

    ROLE_NAMES: tuple[str, ...] = ()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._roles = {
            Qt.UserRole + index + 1: name.encode("utf-8")
            for index, name in enumerate(self.ROLE_NAMES)
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._items):
            return None
        role_name = self._roles.get(role)
        if role_name is None:
            return None
        name = role_name.decode("utf-8")
        return self._items[index.row()].get(name, [] if name == "activityData" else False if name in ("isStreaming", "vrEnabled") else "" if name in ("messageKey", "vrMode") else None)

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return self._roles

    def replace(self, items: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def item(self, index: int) -> dict[str, Any] | None:
        if index < 0 or index >= len(self._items):
            return None
        return self._items[index]

    def append(self, item: dict[str, Any]) -> None:
        index = len(self._items)
        self.beginInsertRows(QModelIndex(), index, index)
        self._items.append(dict(item))
        self.endInsertRows()

    def update_last(self, **values: Any) -> None:
        if not self._items:
            return
        index = len(self._items) - 1
        self._items[index].update(values)
        model_index = self.index(index, 0)
        self.dataChanged.emit(model_index, model_index, list(self._roles))

    def update_by_key(self, key_field: str, key_value: Any, **values: Any) -> bool:
        """Update the item where item[key_field] == key_value."""
        for index in range(len(self._items) - 1, -1, -1):
            if self._items[index].get(key_field) == key_value:
                self._items[index].update(values)
                model_index = self.index(index, 0)
                self.dataChanged.emit(model_index, model_index, list(self._roles))
                return True
        return False


class ConversationListModel(_MappingListModel):
    ROLE_NAMES = (
        "conversationId",
        "title",
        "subtitle",
        "provider",
        "modelName",
        "status",
        "statusLabel",
        "running",
        "workspace",
        "projectLabel",
        "updatedAt",
        "editing",
        "pinned",
        "section",
        "startedAtEpoch",
        "vrMode",
        "vrEnabled",
    )


class MessageListModel(_MappingListModel):
    ROLE_NAMES = (
        "messageId",
        "role",
        "content",
        "displayContent",
        "segments",
        "createdAt",
        "responseMode",
        "messageKey",
        "isStreaming",
        "activityData",
    )


def segments_for_display(markdown: str) -> list[dict[str, str]]:
    """Split a markdown answer into text and fenced-code card segments."""
    text = str(markdown or "")
    blocks = fenced_blocks(text)
    if not any(block["kind"] == "code" for block in blocks):
        return []
    segments: list[dict[str, str]] = []

    def append_text(part: str) -> None:
        if str(part).strip():
            segments.append(
                {"kind": "text", "content": markdown_for_display(part)}
            )

    for block in blocks:
        if block["kind"] == "text":
            append_text(block["content"])
            continue
        language = block["language"]
        segments.append(
            {
                "kind": "code",
                "content": block["content"],
                "language": language,
                "badge": code_language_badge(language),
            }
        )
    return segments

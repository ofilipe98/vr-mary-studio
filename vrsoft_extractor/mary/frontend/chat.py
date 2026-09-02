"""Read-only presentation models for the first QML Chat VR migration slice."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    QSettings,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog

from ..brand import ORGANIZATION_NAME, SETTINGS_APP_NAME
from .text_rendering import FENCE_RE, code_language_badge
from ..classpath import ClasspathError, ClasspathPolicyStore
from ..code_coverage import CodeCoverageError, ErpCodeCoverage
from ..code_index import JavaCodeIndex
from ..code_processing_audit import CodeProcessingAudit
from ..code_processing_policy import processing_window_status
from ..config import MarySettings
from ..db import MaryDatabase
from ..erp_releases import ErpReleaseCatalog, ErpReleaseError
from ..jvm_batches import DecompilationBatchError
from ..jvm_toolchain import JvmToolchain
from ..models import ModelRef, RuntimeEvent
from ..orchestrator import ChatOrchestrator
from ..workspace import is_managed_conversation_workspace


PROVIDER_LABELS = {
    "codex": "Codex",
    "claude": "Claude",
    "opencode": "OpenCode",
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
MAX_FILE_SUGGESTION_ENTRIES = 50_000
ERP_JAR_SCOPE_FULL_RELEASE = "full_release"
ERP_JAR_SCOPE_SINGLE = "single_jar"
DEFAULT_ERP_JAR_SOURCE_PATH = Path(r"C:\vr\exec")
EXPECTED_ERP_JAR_COUNT = 46
CODE_PROCESSING_HEAP_OPTIONS = (1024, 2048, 4096)
CODE_PROCESSING_TIMEOUT_OPTIONS = (300, 600, 1200)
CODE_PROCESSING_CPU_CORE_OPTIONS = (1, 2, 4)
CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS = (5, 8, 10)
CODE_PROCESSING_WINDOW_OPTIONS = (
    {"label": "Sempre", "value": "always"},
    {"label": "Madrugada · 00h-06h", "value": "night"},
    {"label": "Fora do expediente · 18h-06h", "value": "off_hours"},
)
DEFAULT_CODE_PROCESSING_HEAP_MB = 2048
DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS = 300
DEFAULT_CODE_PROCESSING_CPU_CORES = 1
DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER = 10
DEFAULT_CODE_PROCESSING_WINDOW = "always"


def markdown_for_display(markdown: str) -> str:
    """Repair provider spacing without changing inline code or URLs."""

    parts = _CODE_OR_URL_RE.split(str(markdown or ""))
    return "".join(
        part if index % 2 else _GLUED_SENTENCE_RE.sub(" ", part)
        for index, part in enumerate(parts)
    )


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
        return self._items[index.row()].get(role_name.decode("utf-8"))

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
    )


def segments_for_display(markdown: str) -> list[dict[str, str]]:
    """Split a markdown answer into text and fenced-code card segments."""
    text = str(markdown or "")
    matches = list(FENCE_RE.finditer(text))
    if not matches:
        return []
    segments: list[dict[str, str]] = []

    def append_text(part: str) -> None:
        if str(part).strip():
            segments.append(
                {"kind": "text", "content": markdown_for_display(part)}
            )

    cursor = 0
    for match in matches:
        if match.start() > cursor:
            append_text(text[cursor:match.start()])
        language = str(match.group(1) or "").strip().casefold() or "text"
        segments.append(
            {
                "kind": "code",
                "content": str(match.group(2) or ""),
                "language": language,
                "badge": code_language_badge(language),
            }
        )
        cursor = match.end()
    if cursor < len(text):
        append_text(text[cursor:])
    return segments


class ChatBridge(QObject):
    """Expose existing conversation reads without changing domain behavior."""

    conversationsChanged = Signal()
    selectionChanged = Signal()
    searchChanged = Signal()
    projectsChanged = Signal()
    projectFolderChanged = Signal()
    messageCopied = Signal(str)
    stateChanged = Signal()
    approvalRequested = Signal("QVariantMap")
    fileSuggestionsChanged = Signal()
    conversationArchived = Signal(str)
    draftRestored = Signal(str)
    browserNavigationRequested = Signal(str)

    def __init__(
        self,
        settings: MarySettings,
        database: MaryDatabase,
        preferences: QSettings | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._database = database
        self._orchestrator = ChatOrchestrator(settings, database)
        self._preferences = preferences or QSettings(
            ORGANIZATION_NAME, SETTINGS_APP_NAME
        )
        self._conversations = ConversationListModel(self)
        self._messages = MessageListModel(self)
        self._all_conversations: list[dict[str, Any]] = []
        self._projects: list[dict[str, str]] = []
        self._project_scope: Path | None = None
        self._current_project_index = 0
        self._project_folder = Path.home().resolve(strict=False)
        self._project_folder_items: list[dict[str, str]] = []
        self._search = ""
        self._selected_index = -1
        self._selected: dict[str, Any] = {}
        self._draft = False
        self._active_turns: set[str] = set()
        self._active_turn_started_epochs: dict[str, float] = {}
        self._turn_running = False
        self._running_conversation_id = ""
        self._closed = False
        self._status_text = "Pronto"
        self._streaming_text = ""
        self._displayed_streaming_text = ""
        self._stream_pending_text = ""
        self._stream_terminal_kind = ""
        self._assistant_stream_started = False
        self._approval_request: dict[str, Any] = {}
        self._activity_steps: list[dict[str, str]] = []
        self._activity_items: list[dict[str, str]] = []
        self._turn_segments: list[dict[str, Any]] = []
        self._turn_text = ""
        self._segment_cursor = 0
        self._restoring_turn_history = False
        self._reasoning_text = ""
        self._activity_started_at = 0.0
        self._activity_elapsed_seconds = 0
        self._agent_items: list[dict[str, Any]] = []
        enabled_providers = self._enabled_provider_names()
        saved_provider = str(self._preferences.value("chat/last_provider", "") or "")
        self._provider = (
            saved_provider if saved_provider in enabled_providers else enabled_providers[0]
        )
        self._model = str(
            self._preferences.value(f"chat/last_model/{self._provider}", "") or ""
        )
        if self._provider == "codex" and self._model == "gpt-5.6":
            self._model = "gpt-5.6-sol"
            self._preferences.setValue("chat/last_model/codex", self._model)
            self._preferences.sync()
        self._model_items: list[dict[str, Any]] = []
        self._favorite_model_keys = self._load_favorite_model_keys()
        self._model_catalog_loading = False
        self._model_catalog_results: queue.SimpleQueue[list[dict[str, Any]]] = (
            queue.SimpleQueue()
        )
        self._effort = str(
            self._preferences.value("chat/last_effort", settings.default_effort)
            or settings.default_effort
        )
        self._service_tier = str(
            self._preferences.value("chat/last_service_tier", "") or ""
        )
        self._approval_profile = str(
            self._preferences.value("chat/last_approval_profile", "auto") or "auto"
        )
        self._vr_mode = "vr"
        self._research_model_keys: list[str] = []
        self._research_max_parallel = 3
        self._code_analysis_enabled = False
        self._code_analysis_release = "current"
        self._code_analysis_release_items: list[dict[str, Any]] = []
        self._code_analysis_jar_source = ERP_JAR_SOURCE_VR_EXEC
        self._code_analysis_jar_source_items: list[dict[str, Any]] = []
        self._code_analysis_snapshot_scope = ERP_JAR_SCOPE_FULL_RELEASE
        self._code_analysis_single_jar_path = ""
        self._release_snapshot_running = False
        self._release_snapshot_started_at = 0.0
        self._release_snapshot_status = ""
        self._release_snapshot_results: queue.SimpleQueue[dict[str, Any]] = (
            queue.SimpleQueue()
        )
        self._code_processing_running = False
        self._code_processing_started_at = 0.0
        self._code_processing_pause_requested = False
        self._code_processing_status_loading = False
        self._code_processing_status_generation = 0
        self._code_processing_status = ""
        self._code_processing_progress = 0
        self._code_processing_covered_jars = 0
        self._code_processing_total_jars = 0
        self._code_processing_can_retry = False
        self._code_processing_release = ""
        self._code_processing_manifest_hash = ""
        self._code_processing_run_id = ""
        self._code_processing_current_jar = ""
        self._code_processing_current_batch = ""
        self._code_processing_attention_batches: list[dict[str, Any]] = []
        self._code_processing_retry_batch = ""
        self._code_processing_max_heap_mb = DEFAULT_CODE_PROCESSING_HEAP_MB
        self._code_processing_timeout_seconds = (
            DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS
        )
        self._code_processing_max_cpu_cores = DEFAULT_CODE_PROCESSING_CPU_CORES
        self._code_processing_disk_multiplier = (
            DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER
        )
        self._code_processing_window = DEFAULT_CODE_PROCESSING_WINDOW
        self._code_processing_telemetry: dict[str, Any] = {}
        self._code_processing_eta: dict[str, Any] = {}
        self._code_processing_pause_event = threading.Event()
        self._code_processing_results: queue.SimpleQueue[dict[str, Any]] = (
            queue.SimpleQueue()
        )
        self._code_processing_thread: threading.Thread | None = None
        self._code_processing_status_results: queue.SimpleQueue[
            tuple[
                int,
                str,
                dict[str, Any] | None,
                dict[str, Any] | None,
                str,
            ]
        ] = queue.SimpleQueue()
        self._code_processing_status_threads: set[threading.Thread] = set()
        self._code_processing_status_threads_lock = threading.Lock()
        self._senior_profile_enabled = False
        self._vr_response_mode = "auto"
        self._load_research_config()
        self._apply_research_config()
        self._attachments: list[dict[str, str]] = []
        self._draft_records = self._load_draft_records()
        self._pinned_conversation_ids = self._load_pinned_conversation_ids()
        self._extension_items: list[dict[str, Any]] = []
        self._selected_extension_keys: set[str] = set()
        self._extensions_loading = False
        self._extensions_generation = 0
        self._extension_catalog_results: queue.SimpleQueue[dict[str, Any]] = (
            queue.SimpleQueue()
        )
        self._file_suggestions_cache: list[dict[str, Any]] = []
        self._file_suggestions_root: Path | None = None
        self._file_suggestions_generation = 0
        self._file_suggestions_built_at = 0.0
        self._file_suggestions_loading = False
        self._file_suggestions_query = ""
        self._file_suggestions_results: queue.SimpleQueue[
            tuple[int, Path, list[dict[str, str]]]
        ] = queue.SimpleQueue()
        self._runtimeEvent.connect(self._on_runtime_event)
        self._model_catalog_poll_timer = QTimer(self)
        self._model_catalog_poll_timer.setInterval(25)
        self._model_catalog_poll_timer.timeout.connect(self._poll_model_catalog)
        self._extension_catalog_poll_timer = QTimer(self)
        self._extension_catalog_poll_timer.setInterval(25)
        self._extension_catalog_poll_timer.timeout.connect(
            self._poll_extension_catalog
        )
        self._file_suggestions_timer = QTimer(self)
        self._file_suggestions_timer.setSingleShot(True)
        self._file_suggestions_timer.setInterval(500)
        self._file_suggestions_timer.timeout.connect(self._rebuild_file_suggestions)
        self._file_suggestions_poll_timer = QTimer(self)
        self._file_suggestions_poll_timer.setInterval(25)
        self._file_suggestions_poll_timer.timeout.connect(
            self._poll_file_suggestions
        )
        self._release_snapshot_poll_timer = QTimer(self)
        self._release_snapshot_poll_timer.setInterval(50)
        self._release_snapshot_poll_timer.timeout.connect(
            self._poll_release_snapshot
        )
        self._releaseSnapshotReady.connect(self._poll_release_snapshot)
        self._code_processing_poll_timer = QTimer(self)
        self._code_processing_poll_timer.setInterval(100)
        self._code_processing_poll_timer.timeout.connect(
            self._poll_code_processing
        )
        self._codeProcessingReady.connect(self._poll_code_processing)
        self._code_processing_status_poll_timer = QTimer(self)
        self._code_processing_status_poll_timer.setInterval(50)
        self._code_processing_status_poll_timer.timeout.connect(
            self._poll_code_processing_status
        )
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(28)
        self._stream_timer.timeout.connect(self._flush_stream_step)
        self._activity_clock = QTimer(self)
        self._activity_clock.setInterval(1000)
        self._activity_clock.timeout.connect(self._tick_activity_clock)
        self._state_update_timer = QTimer(self)
        self._state_update_timer.setSingleShot(True)
        self._state_update_timer.setInterval(32)
        self._state_update_timer.timeout.connect(self.stateChanged.emit)
        self._reset_model_items()
        self._refresh_projects()
        self.refresh()
        if not self._all_conversations:
            self.startNewChat()

    _runtimeEvent = Signal(object)
    _releaseSnapshotReady = Signal()
    _codeProcessingReady = Signal()

    @Property(QObject, constant=True)
    def conversations(self) -> ConversationListModel:
        return self._conversations

    @Property(QObject, constant=True)
    def messages(self) -> MessageListModel:
        return self._messages

    @Property("QVariantList", notify=projectsChanged)
    def projectItems(self) -> list[dict[str, str]]:  # noqa: N802
        return list(self._projects)

    @Property(int, notify=projectsChanged)
    def currentProjectIndex(self) -> int:  # noqa: N802
        return self._current_project_index

    @Property(str, notify=projectFolderChanged)
    def projectFolderPath(self) -> str:  # noqa: N802
        return str(self._project_folder)

    @Property(str, notify=projectFolderChanged)
    def projectFolderDisplayPath(self) -> str:  # noqa: N802
        home = Path.home().resolve(strict=False)
        try:
            relative = self._project_folder.relative_to(home)
        except ValueError:
            return str(self._project_folder)
        if not relative.parts:
            return "~/"
        return "~/" + relative.as_posix()

    @Property("QVariantList", notify=projectFolderChanged)
    def projectFolderItems(self) -> list[dict[str, str]]:  # noqa: N802
        return list(self._project_folder_items)

    @Property(bool, notify=projectFolderChanged)
    def projectFolderCanGoBack(self) -> bool:  # noqa: N802
        return self._project_folder.parent != self._project_folder

    @Property(int, notify=conversationsChanged)
    def conversationCount(self) -> int:  # noqa: N802
        return self._conversations.rowCount()

    @Property(bool, notify=conversationsChanged)
    def hasConversations(self) -> bool:  # noqa: N802
        return self.conversationCount > 0

    @Property(str, notify=searchChanged)
    def search(self) -> str:
        return self._search

    @Property(int, notify=selectionChanged)
    def selectedIndex(self) -> int:  # noqa: N802
        return self._selected_index

    @Property(bool, notify=selectionChanged)
    def hasSelection(self) -> bool:  # noqa: N802
        return bool(self._selected)

    @Property(bool, notify=selectionChanged)
    def isDraft(self) -> bool:  # noqa: N802
        return self._draft

    @Property(bool, notify=selectionChanged)
    def selectedPinned(self) -> bool:  # noqa: N802
        return self._selected_conversation_id() in self._pinned_conversation_ids

    @Property(str, notify=selectionChanged)
    def selectedTitle(self) -> str:  # noqa: N802
        if self._draft:
            return "Nova conversa"
        return str(self._selected.get("title") or "Selecione uma conversa")

    @Property(str, notify=selectionChanged)
    def selectedMeta(self) -> str:  # noqa: N802
        if self._draft:
            return "Configure a conversa antes de enviar a primeira mensagem"
        if not self._selected:
            return "Histórico em modo somente leitura"
        return str(self._selected.get("subtitle") or "")

    @Property(str, notify=selectionChanged)
    def selectedProject(self) -> str:  # noqa: N802
        if self._draft:
            if not self._projects:
                return "Espaço gerenciado VR"
            project = self._projects[self._current_project_index]
            return project["label"] if project["path"] else "Espaço gerenciado VR"
        return str(self._selected.get("projectLabel") or "Todos os projetos")

    @Property(bool, notify=stateChanged)
    def turnRunning(self) -> bool:  # noqa: N802
        conversation_id = self._selected_conversation_id()
        return bool(conversation_id and conversation_id in self._active_turns)

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:  # noqa: N802
        return self._status_text

    @Property(bool, notify=stateChanged)
    def vrEnabled(self) -> bool:  # noqa: N802
        return self._vr_mode != "off"

    @Property(str, notify=stateChanged)
    def vrMode(self) -> str:  # noqa: N802
        return self._vr_mode

    @Property("QVariantList", notify=stateChanged)
    def researchModelItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {
                "label": str(item.get("label") or item.get("value") or ""),
                "value": str(item.get("value") or ""),
                "key": str(item.get("key") or ""),
                "provider": str(item.get("provider") or ""),
                "description": str(item.get("description") or ""),
            }
            for item in self._model_items
            if item.get("provider")
        ]

    @Property("QVariantList", notify=stateChanged)
    def researchModelKeys(self) -> list[str]:  # noqa: N802
        return list(self._research_model_keys)

    @Property(int, notify=stateChanged)
    def researchMaxParallel(self) -> int:  # noqa: N802
        return self._research_max_parallel

    @Property(bool, notify=stateChanged)
    def codeAnalysisEnabled(self) -> bool:  # noqa: N802
        return self._code_analysis_enabled

    @Property(str, notify=stateChanged)
    def codeAnalysisRelease(self) -> str:  # noqa: N802
        return self._code_analysis_release

    @Property("QVariantList", notify=stateChanged)
    def codeAnalysisReleaseItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._code_analysis_release_items]

    @Property(str, notify=stateChanged)
    def codeAnalysisJarSource(self) -> str:  # noqa: N802
        return self._code_analysis_jar_source

    @Property(str, notify=stateChanged)
    def codeAnalysisJarSourcePath(self) -> str:  # noqa: N802
        selected = next(
            (
                item
                for item in self._code_analysis_jar_source_items
                if item.get("value") == self._code_analysis_jar_source
            ),
            {},
        )
        return str(selected.get("path") or "")

    @Property("QVariantList", notify=stateChanged)
    def codeAnalysisJarSourceItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._code_analysis_jar_source_items]

    @Property(int, notify=stateChanged)
    def codeAnalysisExpectedJarCount(self) -> int:  # noqa: N802
        return EXPECTED_ERP_JAR_COUNT

    @Property(str, notify=stateChanged)
    def codeAnalysisSnapshotScope(self) -> str:  # noqa: N802
        return self._code_analysis_snapshot_scope

    @Property(int, notify=stateChanged)
    def codeAnalysisSnapshotExpectedJarCount(self) -> int:  # noqa: N802
        return (
            1
            if self._code_analysis_snapshot_scope == ERP_JAR_SCOPE_SINGLE
            else EXPECTED_ERP_JAR_COUNT
        )

    @Property(str, notify=stateChanged)
    def codeAnalysisSingleJarPath(self) -> str:  # noqa: N802
        return self._code_analysis_single_jar_path

    @Property(str, notify=stateChanged)
    def codeAnalysisSingleJarName(self) -> str:  # noqa: N802
        return (
            Path(self._code_analysis_single_jar_path).name
            if self._code_analysis_single_jar_path
            else ""
        )

    @Property(bool, notify=stateChanged)
    def releaseSnapshotRunning(self) -> bool:  # noqa: N802
        if self._release_snapshot_running:
            time.sleep(0.001)
        if (
            self._release_snapshot_running
            and self._release_snapshot_started_at > 0
            and time.monotonic() - self._release_snapshot_started_at >= 0.05
            and not self._release_snapshot_results.empty()
        ):
            self._poll_release_snapshot()
        return self._release_snapshot_running

    @Property(str, notify=stateChanged)
    def releaseSnapshotStatus(self) -> str:  # noqa: N802
        return self._release_snapshot_status

    @Property(bool, notify=stateChanged)
    def codeAnalysisReleaseFresh(self) -> bool:  # noqa: N802
        selected = self._selected_code_analysis_release_item()
        return bool(selected and selected.get("freshness") == "fresh")

    @Property(bool, notify=stateChanged)
    def codeProcessingRunning(self) -> bool:  # noqa: N802
        if self._code_processing_running:
            time.sleep(0.001)
        if (
            self._code_processing_running
            and self._code_processing_started_at > 0
            and time.monotonic() - self._code_processing_started_at >= 0.05
            and not self._code_processing_results.empty()
        ):
            self._poll_code_processing()
        return self._code_processing_running

    @Property(bool, notify=stateChanged)
    def codeProcessingPauseRequested(self) -> bool:  # noqa: N802
        return self._code_processing_pause_requested

    @Property(bool, notify=stateChanged)
    def codeProcessingStatusLoading(self) -> bool:  # noqa: N802
        return self._code_processing_status_loading

    @Property(str, notify=stateChanged)
    def codeProcessingStatus(self) -> str:  # noqa: N802
        return self._code_processing_status

    @Property(int, notify=stateChanged)
    def codeProcessingProgress(self) -> int:  # noqa: N802
        return self._code_processing_progress

    @Property(int, notify=stateChanged)
    def codeProcessingCoveredJars(self) -> int:  # noqa: N802
        return self._code_processing_covered_jars

    @Property(int, notify=stateChanged)
    def codeProcessingTotalJars(self) -> int:  # noqa: N802
        return self._code_processing_total_jars

    @Property(bool, notify=stateChanged)
    def codeProcessingCanRetry(self) -> bool:  # noqa: N802
        return self._code_processing_can_retry

    @Property(str, notify=stateChanged)
    def codeProcessingFrozenRelease(self) -> str:  # noqa: N802
        return self._code_processing_release

    @Property(str, notify=stateChanged)
    def codeProcessingFrozenManifestHash(self) -> str:  # noqa: N802
        return self._code_processing_manifest_hash

    @Property(str, notify=stateChanged)
    def codeProcessingCurrentJar(self) -> str:  # noqa: N802
        return self._code_processing_current_jar

    @Property(str, notify=stateChanged)
    def codeProcessingCurrentBatch(self) -> str:  # noqa: N802
        return self._code_processing_current_batch

    @Property("QVariantList", notify=stateChanged)
    def codeProcessingAttentionBatches(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._code_processing_attention_batches]

    @Property(str, notify=stateChanged)
    def codeProcessingRetryBatch(self) -> str:  # noqa: N802
        return self._code_processing_retry_batch

    @Property("QVariantList", notify=stateChanged)
    def codeProcessingHeapOptions(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {"label": f"{value // 1024} GB", "value": value}
            for value in CODE_PROCESSING_HEAP_OPTIONS
        ]

    @Property("QVariantList", notify=stateChanged)
    def codeProcessingTimeoutOptions(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {"label": f"{value // 60} minutos", "value": value}
            for value in CODE_PROCESSING_TIMEOUT_OPTIONS
        ]

    @Property(int, notify=stateChanged)
    def codeProcessingMaxHeapMb(self) -> int:  # noqa: N802
        return self._code_processing_max_heap_mb

    @Property(int, notify=stateChanged)
    def codeProcessingTimeoutSeconds(self) -> int:  # noqa: N802
        return self._code_processing_timeout_seconds

    @Property("QVariantList", notify=stateChanged)
    def codeProcessingCpuCoreOptions(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {"label": f"{value} núcleo(s)", "value": value}
            for value in CODE_PROCESSING_CPU_CORE_OPTIONS
        ]

    @Property(int, notify=stateChanged)
    def codeProcessingMaxCpuCores(self) -> int:  # noqa: N802
        return self._code_processing_max_cpu_cores

    @Property("QVariantList", notify=stateChanged)
    def codeProcessingDiskMultiplierOptions(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {"label": f"Até {value}x", "value": value}
            for value in CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS
        ]

    @Property(int, notify=stateChanged)
    def codeProcessingDiskMultiplier(self) -> int:  # noqa: N802
        return self._code_processing_disk_multiplier

    @Property("QVariantList", notify=stateChanged)
    def codeProcessingWindowOptions(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in CODE_PROCESSING_WINDOW_OPTIONS]

    @Property(str, notify=stateChanged)
    def codeProcessingWindow(self) -> str:  # noqa: N802
        return self._code_processing_window

    @Property("QVariantMap", notify=stateChanged)
    def codeProcessingTelemetry(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._code_processing_telemetry)

    @Property(str, notify=stateChanged)
    def codeProcessingTelemetrySummary(self) -> str:  # noqa: N802
        telemetry = self._code_processing_telemetry
        batches = int(telemetry.get("processed_batches") or 0)
        if not batches:
            return ""
        duration_ms = int(telemetry.get("wall_duration_ms") or 0)
        peak_rss = int(telemetry.get("peak_rss_bytes") or 0)
        cpu_ms = int(telemetry.get("cpu_user_ms") or 0) + int(
            telemetry.get("cpu_kernel_ms") or 0
        )
        output_bytes = int(telemetry.get("output_bytes") or 0)
        metrics_note = (
            f"pico Java {self._format_megabytes(peak_rss)} · CPU {cpu_ms / 1000:.1f}s"
            if telemetry.get("metrics_available")
            else "RAM/CPU indisponíveis"
        )
        return (
            f"Telemetria: {batches} lote(s) · "
            f"{self._format_duration_ms(duration_ms)} · {metrics_note} · "
            f"saída {self._format_megabytes(output_bytes)}"
        )

    @Property(str, notify=stateChanged)
    def codeProcessingEtaSummary(self) -> str:  # noqa: N802
        eta = self._code_processing_eta
        if not eta.get("available"):
            return "ETA: aguardando histórico local suficiente."
        duration = self._format_duration_ms(
            int(eta.get("estimated_remaining_ms") or 0)
        )
        samples = int(eta.get("sample_run_count") or 0)
        confidence = {
            "high": "alta",
            "medium": "média",
            "low": "baixa",
        }.get(str(eta.get("confidence") or ""), "indisponível")
        return f"ETA local: {duration} · confiança {confidence} · {samples} execução(ões)"

    @Property(bool, notify=stateChanged)
    def seniorProfileEnabled(self) -> bool:  # noqa: N802
        return self._senior_profile_enabled

    @Property(str, notify=stateChanged)
    def vrResponseMode(self) -> str:  # noqa: N802
        return self._vr_response_mode

    @Property("QVariantList", notify=stateChanged)
    def modelItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {
                **item,
                "favorite": str(item.get("key") or "") in self._favorite_model_keys,
            }
            for item in self._model_items
        ]

    @Property(int, notify=stateChanged)
    def modelIndex(self) -> int:  # noqa: N802
        return next(
            (
                index
                for index, item in enumerate(self._model_items)
                if item.get("provider") == self._provider
                and str(item.get("value") or "") == self._model
            ),
            0,
        )

    @Property(bool, notify=stateChanged)
    def modelCatalogLoading(self) -> bool:  # noqa: N802
        return self._model_catalog_loading

    @Property("QVariantList", notify=stateChanged)
    def effortItems(self) -> list[dict[str, Any]]:  # noqa: N802
        supported = self._supported_efforts_for_current_model()
        default_effort = str(self._settings.default_effort or "medium").casefold()
        return [
            {
                "label": EFFORT_LABELS.get(value, value.replace("_", " ").title()),
                "value": value,
                "default": value == default_effort,
            }
            for value in supported
        ]

    @Property("QVariantList", notify=stateChanged)
    def serviceTierItems(self) -> list[dict[str, Any]]:  # noqa: N802
        if self._provider != "codex":
            return []
        values: list[dict[str, Any]] = [
            {
                "label": "Standard",
                "value": "",
                "description": "Camada padrão do provedor.",
                "default": True,
            }
        ]
        metadata = self._current_model_item()
        raw_tiers = metadata.get("serviceTiers") or []
        if not raw_tiers:
            raw_tiers = [
                {
                    "id": "fast",
                    "name": "Fast",
                    "description": "1,5× mais rápido, com maior consumo.",
                }
            ]
        for raw in raw_tiers:
            if not isinstance(raw, dict):
                continue
            value = str(raw.get("id") or raw.get("value") or "").strip()
            if not value or any(item["value"] == value for item in values):
                continue
            values.append(
                {
                    "label": str(raw.get("name") or raw.get("label") or value.title()),
                    "value": value,
                    "description": str(raw.get("description") or ""),
                    "default": False,
                }
            )
        return values

    @Property("QVariantList", constant=True)
    def approvalItems(self) -> list[dict[str, str]]:  # noqa: N802
        return [
            {
                "label": "Supervisionado",
                "value": "supervised",
                "description": "Perguntar antes de comandos e alterações em arquivos.",
            },
            {
                "label": "Autoaceitar edições",
                "value": "auto_edits",
                "description": "Aprovar edições; perguntar antes de outras ações.",
            },
            {
                "label": "Auto",
                "value": "auto",
                "description": "Provedores compatíveis aprovam ações rotineiras; outros ainda perguntam.",
            },
            {
                "label": "Acesso total",
                "value": "full_access",
                "description": "Permitir comandos e edições sem confirmações.",
            },
        ]

    @Property(int, notify=stateChanged)
    def effortIndex(self) -> int:  # noqa: N802
        values = [item["value"] for item in self.effortItems]
        if self._effort in values:
            return values.index(self._effort)
        if "medium" in values:
            return values.index("medium")
        return 0 if values else -1

    @Property(int, notify=stateChanged)
    def serviceTierIndex(self) -> int:  # noqa: N802
        values = [item["value"] for item in self.serviceTierItems]
        if not values:
            return -1
        return values.index(self._service_tier) if self._service_tier in values else 0

    @Property(int, notify=stateChanged)
    def approvalIndex(self) -> int:  # noqa: N802
        values = [item["value"] for item in self.approvalItems]
        return values.index(self._approval_profile) if self._approval_profile in values else 2

    @Property("QVariantList", notify=stateChanged)
    def attachments(self) -> list[dict[str, str]]:
        return list(self._attachments)

    @Property("QVariantList", notify=stateChanged)
    def extensionItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {**item, "selected": str(item.get("key") or "") in self._selected_extension_keys}
            for item in self._extension_items
        ]

    @Property(bool, notify=stateChanged)
    def extensionsLoading(self) -> bool:  # noqa: N802
        return self._extensions_loading

    @Property(float, notify=stateChanged)
    def contextUsageFraction(self) -> float:  # noqa: N802
        row = self._selected_database_row()
        window = self._provider_context_window()
        if row is None or not window:
            return 0.0
        used = int(row["context_used_tokens"] or 0)
        return min(1.0, used / window)

    @Property(bool, notify=stateChanged)
    def hasContextWindow(self) -> bool:  # noqa: N802
        row = self._selected_database_row()
        return bool(
            row is not None
            and int(row["context_used_tokens"] or 0) > 0
            and self._provider_context_window() > 0
        )

    @Property(str, notify=stateChanged)
    def contextUsageLabel(self) -> str:  # noqa: N802
        row = self._selected_database_row()
        window = self._provider_context_window()
        if row is None or not window:
            return "Aguardando dados"
        used = int(row["context_used_tokens"] or 0)
        return f"{used:,} / {window:,} tokens".replace(",", ".")

    @Property(str, notify=stateChanged)
    def contextUsageCompactLabel(self) -> str:  # noqa: N802
        row = self._selected_database_row()
        window = self._provider_context_window()
        if row is None or not window:
            return "Aguardando dados"
        used = int(row["context_used_tokens"] or 0)
        percentage = min(100, round(used * 100 / window))
        return f"{percentage}% · {self._compact_tokens(used)}/{self._compact_tokens(window)}"

    @Property(str, notify=stateChanged)
    def contextUsageNote(self) -> str:  # noqa: N802
        item = self._current_model_item()
        model_name = str(item.get("displayName") or self._model or "modelo")
        return f"Limite informado pelo provedor para {model_name}. Compactação ocorre quando necessário."

    def _provider_context_window(self) -> int:
        item = self._current_model_item()
        candidates = (
            item.get("contextWindow"),
            item.get("context_window"),
            item.get("contextWindowTokens"),
            item.get("inputTokenLimit"),
        )
        for value in candidates:
            try:
                parsed = int(value or 0)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return 0

    @Property(str, notify=stateChanged)
    def totalProcessedLabel(self) -> str:  # noqa: N802
        row = self._selected_database_row()
        total = int(row["total_processed_tokens"] or 0) if row is not None else 0
        return f"{total:,} tokens".replace(",", ".")

    @staticmethod
    def _compact_tokens(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}m".replace(".0m", "m")
        if value >= 1_000:
            return f"{value / 1_000:.0f}k"
        return str(value)

    @Property("QVariantList", notify=stateChanged)
    def activitySteps(self) -> list[dict[str, str]]:  # noqa: N802
        return [dict(item) for item in self._activity_steps]

    @Property("QVariantList", notify=stateChanged)
    def activityItems(self) -> list[dict[str, str]]:  # noqa: N802
        return [dict(item) for item in self._activity_items]

    @Property(str, notify=stateChanged)
    def reasoningText(self) -> str:  # noqa: N802
        return self._reasoning_text

    @Property(str, notify=stateChanged)
    def activityElapsedLabel(self) -> str:  # noqa: N802
        seconds = max(0, int(self._activity_elapsed_seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    @Property("QVariantList", notify=stateChanged)
    def agentItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._agent_items]

    def _selected_database_row(self) -> Any:
        conversation_id = self._selected_conversation_id()
        return self._database.get_conversation(conversation_id) if conversation_id else None

    @Slot()
    def close(self) -> None:
        """Release providers and timers exactly once during application shutdown."""

        if self._closed:
            return
        self._closed = True
        for timer in (
            self._file_suggestions_timer,
            self._file_suggestions_poll_timer,
            self._model_catalog_poll_timer,
            self._extension_catalog_poll_timer,
            self._release_snapshot_poll_timer,
            self._code_processing_poll_timer,
            self._code_processing_status_poll_timer,
            self._stream_timer,
            self._activity_clock,
            self._state_update_timer,
        ):
            timer.stop()
        self._code_processing_pause_event.set()
        processing_thread = self._code_processing_thread
        if processing_thread is not None and processing_thread.is_alive():
            processing_thread.join(timeout=2.0)
        self._cancel_code_processing_status_refresh()
        with self._code_processing_status_threads_lock:
            status_threads = list(self._code_processing_status_threads)
        for thread in status_threads:
            thread.join(timeout=1.0)
        self._orchestrator.close()
        self._active_turns.clear()
        self._sync_selected_turn_state()

    def _selected_conversation_id(self) -> str:
        return str(self._selected.get("conversationId") or "")

    def _sync_selected_turn_state(self) -> None:
        """Keep private compatibility fields scoped to the selected conversation."""

        conversation_id = self._selected_conversation_id()
        running = bool(conversation_id and conversation_id in self._active_turns)
        self._turn_running = running
        self._running_conversation_id = conversation_id if running else ""

    def _enabled_provider_names(self) -> list[str]:
        enabled: list[str] = []
        for provider in ("codex", "claude", "opencode"):
            raw = self._preferences.value(f"providers/{provider}/enabled", True)
            if isinstance(raw, bool):
                active = raw
            else:
                active = str(raw).strip().casefold() not in {"", "0", "false", "no", "off"}
            if active:
                enabled.append(provider)
        return enabled or ["codex"]

    def _remember_current_chat_options(self) -> None:
        self._preferences.setValue("chat/last_provider", self._provider)
        if self._model:
            self._preferences.setValue(
                f"chat/last_model/{self._provider}", self._model
            )
        self._preferences.setValue("chat/last_effort", self._effort)
        self._remember_model_effort(self._effort)
        self._preferences.setValue("chat/last_service_tier", self._service_tier)
        self._preferences.setValue(
            "chat/last_approval_profile", self._approval_profile
        )
        self._preferences.sync()

    def _current_model_item(self) -> dict[str, Any]:
        return next(
            (
                item
                for item in self._model_items
                if item.get("provider") == self._provider
                and str(item.get("value") or "") == self._model
            ),
            {},
        )

    def _supported_efforts_for_current_model(self) -> list[str]:
        metadata = self._current_model_item()
        raw_efforts = metadata.get("efforts") or []
        efforts: list[str] = []
        for item in raw_efforts:
            if isinstance(item, str):
                value = item
            elif isinstance(item, dict):
                value = (
                    item.get("reasoningEffort")
                    or item.get("effort")
                    or item.get("value")
                    or item.get("id")
                    or ""
                )
            else:
                value = ""
            normalized = str(value).strip().casefold()
            if normalized == "ultra":
                normalized = "max"
            if normalized in EFFORT_LABELS and normalized not in efforts:
                efforts.append(normalized)
        if efforts:
            return ["auto", *efforts]
        return (
            ["auto", "low", "medium", "high", "xhigh", "max"]
            if self._provider == "claude"
            else ["auto", "minimal", "low", "medium", "high", "xhigh", "max"]
        )

    def _model_effort_preferences(self) -> dict[str, str]:
        raw = self._preferences.value("chat/model_efforts", "{}")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return {
            str(key): str(value).strip().casefold()
            for key, value in values.items()
            if str(key).strip() and str(value).strip()
        }

    def _model_effort_key(self) -> str:
        return f"{self._provider}:{self._model}"

    def _remember_model_effort(self, effort: str) -> None:
        value = str(effort or "").strip().casefold()
        if not value or not self._model:
            return
        if value == "ultra":
            value = "max"
        preferences = self._model_effort_preferences()
        preferences[self._model_effort_key()] = value
        self._preferences.setValue(
            "chat/model_efforts",
            json.dumps(preferences, ensure_ascii=False, sort_keys=True),
        )

    def _restore_effort_for_current_model(self) -> None:
        supported = [item["value"] for item in self.effortItems]
        if not supported:
            self._effort = "medium"
            return
        saved = self._model_effort_preferences().get(self._model_effort_key(), "")
        preferred = saved or self._effort or self._settings.default_effort
        if preferred == "ultra":
            preferred = "max"
        if preferred not in supported:
            concrete = [value for value in supported if value != "auto"]
            preferred = (
                "medium" if "medium" in concrete else (concrete or supported)[0]
            )
        self._effort = preferred

    def _reset_model_items(self) -> None:
        enabled = self._enabled_provider_names()
        provider = self._provider if self._provider in enabled else enabled[0]
        self._provider = provider
        label = self._model or PROVIDER_LABELS.get(provider, provider.title())
        provider_label = PROVIDER_LABELS.get(provider, provider.title())
        self._model_items = [{
            "label": label,
            "displayName": label,
            "value": self._model,
            "provider": provider,
            "providerLabel": provider_label,
            "description": "Última seleção disponível",
            "key": f"{provider}:{self._model or '__default__'}",
        }]

    @Slot()
    def refreshModels(self) -> None:  # noqa: N802
        if self._model_catalog_loading:
            return
        self._model_catalog_loading = True
        self.stateChanged.emit()
        enabled_providers = tuple(self._enabled_provider_names())
        providers = dict(self._orchestrator.providers)
        results = self._model_catalog_results

        def load() -> None:
            items: list[dict[str, Any]] = []
            for provider_name in enabled_providers:
                provider = providers.get(provider_name)
                if provider is None:
                    continue
                provider_label = PROVIDER_LABELS.get(provider_name, provider_name.title())
                try:
                    models = provider.list_models() if provider.available() else []
                except Exception:
                    models = []
                for raw in models:
                    model_id = str(raw.get("id") or raw.get("model") or "").strip()
                    if not model_id:
                        continue
                    display_name = str(raw.get("displayName") or raw.get("display_name") or model_id)
                    raw_limit = raw.get("limit") or raw.get("limits") or {}
                    if not isinstance(raw_limit, dict):
                        raw_limit = {}
                    context_window = next(
                        (
                            value
                            for value in (
                                raw.get("contextWindow"),
                                raw.get("context_window"),
                                raw.get("contextWindowTokens"),
                                raw.get("inputTokenLimit"),
                                raw_limit.get("context"),
                                raw_limit.get("contextWindow"),
                            )
                            if value not in (None, "")
                        ),
                        0,
                    )
                    items.append({
                        "label": f"{display_name} · {provider_label}",
                        "displayName": display_name,
                        "value": model_id,
                        "provider": provider_name,
                        "providerLabel": provider_label,
                        "description": str(raw.get("description") or model_id),
                        "key": f"{provider_name}:{model_id}",
                        "efforts": raw.get("supportedReasoningEfforts") or raw.get("supported_reasoning_efforts") or [],
                        "serviceTiers": raw.get("serviceTiers") or raw.get("service_tiers") or [],
                        "contextWindow": context_window,
                    })
            results.put(items)

        self._model_catalog_poll_timer.start()
        threading.Thread(target=load, daemon=True).start()

    @Slot()
    def _poll_model_catalog(self) -> None:
        latest: list[dict[str, Any]] | None = None
        while True:
            try:
                latest = self._model_catalog_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            if not self._model_catalog_loading:
                self._model_catalog_poll_timer.stop()
            return
        self._apply_model_catalog(latest)
        if not self._model_catalog_loading:
            self._model_catalog_poll_timer.stop()

    @Slot(object)
    def _apply_model_catalog(self, values: object) -> None:
        items = [dict(item) for item in list(values or []) if isinstance(item, dict)]
        enabled_providers = set(self._enabled_provider_names())
        if self._draft and not self._model:
            preferred = next(
                (
                    item
                    for item in items
                    if item.get("provider") == self._provider
                    and str(item.get("value") or "")
                ),
                None,
            )
            if preferred is not None:
                self._model = str(preferred.get("value") or "")
                self._remember_current_chat_options()
        current_key = f"{self._provider}:{self._model or '__default__'}"
        if not any(str(item.get("key") or "") == current_key for item in items):
            current = self._model_items[self.modelIndex] if self._model_items else None
            if current:
                historical = dict(current)
                historical["inactive"] = self._provider not in enabled_providers
                items.insert(0, historical)
        if self._draft and self._provider not in enabled_providers and items:
            preferred = next(
                (item for item in items if not item.get("inactive")), items[0]
            )
            self._provider = str(
                preferred.get("provider") or next(iter(enabled_providers), "codex")
            )
            self._model = str(preferred.get("value") or "")
            self._remember_current_chat_options()
            items = [item for item in items if not item.get("inactive")]
        self._model_items = items or self._model_items
        self._restore_effort_for_current_model()
        if not self.serviceTierItems:
            self._service_tier = ""
        self._model_catalog_loading = False
        self.stateChanged.emit()

    @Slot(int)
    def setModel(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._model_items) or self.turnRunning:
            return
        item = self._model_items[index]
        provider = str(item.get("provider") or "codex")
        model = str(item.get("value") or "")
        if (provider, model) == (self._provider, self._model):
            return
        conversation_id = str(self._selected.get("conversationId") or "")
        if conversation_id and any(
            str(row["role"] or "") == "user"
            for row in self._database.messages(conversation_id)
        ):
            self._status_text = "Modelo principal bloqueado após a primeira mensagem"
            self.stateChanged.emit()
            return
        try:
            if conversation_id:
                self._orchestrator.switch_provider(
                    conversation_id, provider, model, self._effort
                )
        except Exception as exc:
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()
            return
        self._provider = provider
        self._model = model
        self._restore_effort_for_current_model()
        if not self.serviceTierItems:
            self._service_tier = ""
        self._remember_current_chat_options()
        self._status_text = "Pronto"
        self.refresh()
        self.stateChanged.emit()

    @Slot(int)
    def toggleModelFavorite(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._model_items):
            return
        key = str(self._model_items[index].get("key") or "")
        if not key:
            return
        if key in self._favorite_model_keys:
            self._favorite_model_keys.remove(key)
        else:
            self._favorite_model_keys.add(key)
        self._preferences.setValue(
            "chat/favorite_models",
            json.dumps(sorted(self._favorite_model_keys), ensure_ascii=False),
        )
        self._preferences.sync()
        self.stateChanged.emit()

    def _load_favorite_model_keys(self) -> set[str]:
        raw = self._preferences.value("chat/favorite_models", "[]")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else list(raw or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        return {str(value) for value in values if str(value).strip()}

    @Slot(result="QVariantList")
    def chooseAttachments(self) -> list[dict[str, str]]:  # noqa: N802
        selected, _ = QFileDialog.getOpenFileNames(
            None,
            "Adicionar arquivos à conversa",
            str(self._project_scope or self._settings.root),
            "Arquivos suportados (*.png *.jpg *.jpeg *.webp *.gif *.md *.txt *.json *.csv *.pdf);;Todos os arquivos (*.*)",
        )
        self._stage_attachment_paths(selected)
        return self.attachments

    def _stage_attachment_paths(self, values: list[object]) -> int:
        """Stage existing local files supplied by a picker or QML drop event."""

        known = {item["path"] for item in self._attachments}
        added = 0
        for raw in values:
            if isinstance(raw, QUrl):
                local_value = raw.toLocalFile() if raw.isLocalFile() else ""
            else:
                text = str(raw or "").strip()
                url = QUrl(text)
                local_value = url.toLocalFile() if url.isLocalFile() else text
            if not local_value:
                continue
            path = Path(local_value).expanduser().resolve(strict=False)
            normalized = str(path)
            if not path.is_file() or normalized in known:
                continue
            self._attachments.append({"name": path.name, "path": normalized})
            known.add(normalized)
            added += 1
        if added:
            self.stateChanged.emit()
        return added

    @Slot("QVariantList", result=int)
    def addDroppedAttachments(self, values: list) -> int:  # noqa: N802
        """Receive local file URLs dropped directly on the QML composer."""

        return self._stage_attachment_paths(list(values or []))

    @Slot(int)
    def removeAttachment(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self._attachments):
            self._attachments.pop(index)
            self.stateChanged.emit()

    @Slot(str, result="QVariantList")
    def fileSuggestions(self, query: str) -> list[dict[str, Any]]:  # noqa: N802
        needle = str(query or "").strip().casefold()
        self._file_suggestions_query = needle
        if self._file_suggestions_stale() and not self._file_suggestions_timer.isActive():
            # The first opening of the Files surface has nothing to debounce.
            # Start it on the next event-loop tick so the initial listing does
            # not inherit the refresh delay used after project mutations.
            initial_load = self._file_suggestions_root is None
            self._file_suggestions_timer.start(0 if initial_load else 500)
        visible = []
        for item in self._file_suggestions_cache:
            is_directory = bool(item.get("isDirectory"))
            if needle and (is_directory or needle not in item["relative"].casefold()):
                continue
            visible.append({
                "label": item["relative"],
                "name": item.get("name") or Path(item["relative"]).name,
                "path": item["path"],
                "parent": item.get("parent") or "",
                "depth": int(item.get("depth") or 0),
                "isDirectory": is_directory,
            })
        return visible[:80 if needle else 600]

    def _file_suggestions_stale(self) -> bool:
        if self._file_suggestions_loading:
            return False
        root = (self._project_scope or self._settings.root).resolve(strict=False)
        if self._file_suggestions_root != root:
            return True
        # A completed scan of an empty project is still a valid cache.  Without
        # this marker every QML binding read starts another background thread.
        if self._file_suggestions_built_at <= 0:
            return True
        return time.monotonic() - self._file_suggestions_built_at > 60

    def _invalidate_file_suggestions(self) -> None:
        self._file_suggestions_generation += 1
        self._file_suggestions_cache = []
        self._file_suggestions_root = None
        self._file_suggestions_built_at = 0.0
        self._file_suggestions_timer.start()

    @Slot()
    def _rebuild_file_suggestions(self) -> None:  # noqa: N802
        if self._file_suggestions_loading:
            return
        root = (self._project_scope or self._settings.root).resolve(strict=False)
        if not root.is_dir():
            self._file_suggestions_root = root
            self._file_suggestions_cache = []
            self._file_suggestions_built_at = time.monotonic()
            self._apply_pending_file_suggestions()
            return
        self._file_suggestions_loading = True
        generation = self._file_suggestions_generation
        results = self._file_suggestions_results

        def scan() -> None:
            ignored = {".git", ".venv", "__pycache__", "node_modules", ".state"}
            entries: list[dict[str, Any]] = []
            try:
                stop_scan = False
                for current, directory_names, file_names in os.walk(
                    root, topdown=True, followlinks=False
                ):
                    directory_names[:] = sorted(
                        (
                            name
                            for name in directory_names
                            if name.casefold() not in ignored
                        ),
                        key=str.casefold,
                    )
                    current_path = Path(current)
                    for name, is_directory in (
                        *((name, True) for name in directory_names),
                        *((name, False) for name in sorted(file_names, key=str.casefold)),
                    ):
                        path = current_path / name
                        relative_path = path.relative_to(root)
                        relative = relative_path.as_posix()
                        parent = relative_path.parent.as_posix()
                        entries.append({
                            "relative": relative,
                            "name": name,
                            "path": str(path),
                            "parent": "" if parent == "." else parent,
                            "depth": max(0, len(relative_path.parts) - 1),
                            "isDirectory": is_directory,
                        })
                        if len(entries) >= MAX_FILE_SUGGESTION_ENTRIES:
                            stop_scan = True
                            break
                    if stop_scan:
                        break
                entries.sort(key=lambda item: (
                    tuple(part.casefold() for part in Path(item["relative"]).parts),
                    not bool(item.get("isDirectory")),
                ))
            except OSError:
                entries = []
            # A Python worker must not emit through a QObject that may already
            # have been destroyed by Qt.  The UI thread drains this queue.
            results.put((generation, root, entries))

        self._file_suggestions_poll_timer.start()
        threading.Thread(target=scan, daemon=True).start()

    @Slot()
    def _poll_file_suggestions(self) -> None:
        latest: tuple[int, Path, list[dict[str, str]]] | None = None
        while True:
            try:
                latest = self._file_suggestions_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            if not self._file_suggestions_loading:
                self._file_suggestions_poll_timer.stop()
            return
        self._apply_file_suggestions(*latest)
        if not self._file_suggestions_loading:
            self._file_suggestions_poll_timer.stop()

    def _apply_file_suggestions(
        self, generation: int, root: Path, entries: list[dict[str, str]]
    ) -> None:  # noqa: N802
        self._file_suggestions_loading = False
        if generation != self._file_suggestions_generation:
            self._file_suggestions_timer.start(0)
            return
        self._file_suggestions_cache = [
            {
                "relative": str(item.get("relative") or ""),
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "parent": str(item.get("parent") or ""),
                "depth": int(item.get("depth") or 0),
                "isDirectory": bool(item.get("isDirectory")),
            }
            for item in list(entries or [])
            if isinstance(item, dict) and item.get("relative")
        ]
        self._file_suggestions_root = root
        self._file_suggestions_built_at = time.monotonic()
        self._apply_pending_file_suggestions()

    def _apply_pending_file_suggestions(self) -> None:
        # Files can be opened with an empty search.  The asynchronous scan must
        # still notify QML or the initial project listing remains blank.
        self.fileSuggestionsChanged.emit()

    @Slot(str, result=str)
    def readFilePreview(self, value: str) -> str:  # noqa: N802
        """Read a small text file from the selected project for the Files surface."""
        raw = str(value or "").strip()
        if not raw:
            return ""
        candidate = Path(raw).expanduser().resolve(strict=False)
        roots = [
            (self._project_scope or self._settings.root).resolve(strict=False),
            self._settings.root.resolve(strict=False),
        ]
        if not any(self._is_relative_to(candidate, root) for root in roots):
            return "O arquivo está fora do projeto selecionado."
        if not candidate.is_file():
            return "O arquivo não foi encontrado."
        if candidate.stat().st_size > 512_000:
            return "Arquivo maior que 500 KB. Abra-o no editor para visualizar."
        try:
            return candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return candidate.read_text(encoding="cp1252")
            except (OSError, UnicodeError):
                return "Este arquivo não possui uma visualização textual compatível."
        except OSError as exc:
            return f"Não foi possível ler o arquivo: {exc}"

    @Slot(str, result="QVariantList")
    def contextSuggestions(self, query: str) -> list[dict[str, str]]:  # noqa: N802
        value = str(query or "").strip()
        if not value:
            return []
        try:
            rows = self._database.search(value, limit=20, excluded_sources=("schema",))
        except Exception:
            return []
        return [
            {
                "title": str(row.get("title") or "Documento"),
                "source": str(row.get("source") or "").upper(),
                "excerpt": str(row.get("excerpt") or row.get("markdown") or "")[:240],
                "reference": f"@vr:{row.get('source_id') or row.get('title') or ''}",
            }
            for row in rows
        ]

    @Slot()
    def refreshExtensions(self) -> None:  # noqa: N802
        self._extensions_generation += 1
        generation = self._extensions_generation
        self._extensions_loading = True
        self.stateChanged.emit()
        provider_name = self._provider
        workspace = (self._project_scope or self._settings.root).resolve(strict=False)
        orchestrator = self._orchestrator
        results = self._extension_catalog_results

        def load() -> None:
            values: list[dict[str, Any]] = []
            try:
                skill_result = orchestrator.skills(provider_name, workspace)
            except Exception:
                skill_result = {"skills": []}
            for item in skill_result.get("skills", []):
                name = str(item.get("name") or "")
                if not name:
                    continue
                values.append({
                    "key": f"skill:{name}:{item.get('path') or ''}",
                    "kind": "skill",
                    "name": str(item.get("displayName") or name),
                    "description": str(item.get("description") or item.get("scope") or "Skill"),
                    "payload": dict(item),
                })
            try:
                tools = orchestrator.mcp_tools(provider_name)
            except Exception:
                tools = []
            for item in tools:
                server = str(item.get("server") or "")
                tool = str(item.get("tool") or "")
                if not server:
                    continue
                values.append({
                    "key": f"mcp:{server}:{tool}",
                    "kind": "mcp",
                    "name": f"{server} · {tool or 'servidor'}",
                    "description": str(item.get("description") or item.get("serverDescription") or "MCP"),
                    "payload": {"server": server, "tool": tool},
                })
            results.put(
                {
                    "generation": generation,
                    "provider": provider_name,
                    "workspace": str(workspace),
                    "items": values,
                }
            )

        self._extension_catalog_poll_timer.start()
        threading.Thread(target=load, daemon=True).start()

    @Slot()
    def _poll_extension_catalog(self) -> None:
        latest: dict[str, Any] | None = None
        while True:
            try:
                latest = self._extension_catalog_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            if not self._extensions_loading:
                self._extension_catalog_poll_timer.stop()
            return
        self._apply_extension_catalog(latest)
        if not self._extensions_loading:
            self._extension_catalog_poll_timer.stop()

    @Slot(object)
    def _apply_extension_catalog(self, values: object) -> None:
        payload = dict(values) if isinstance(values, dict) else {"items": values}
        generation = int(payload.get("generation") or self._extensions_generation)
        current_workspace = str(
            (self._project_scope or self._settings.root).resolve(strict=False)
        )
        if (
            generation != self._extensions_generation
            or str(payload.get("provider") or self._provider) != self._provider
            or str(payload.get("workspace") or current_workspace) != current_workspace
        ):
            return
        self._extension_items = [
            dict(item)
            for item in list(payload.get("items") or [])
            if isinstance(item, dict)
        ]
        available = {str(item.get("key") or "") for item in self._extension_items}
        self._selected_extension_keys.intersection_update(available)
        self._extensions_loading = False
        self.stateChanged.emit()

    @Slot(int, bool)
    def toggleExtension(self, index: int, selected: bool) -> None:  # noqa: N802
        if not 0 <= index < len(self._extension_items):
            return
        key = str(self._extension_items[index].get("key") or "")
        if selected:
            self._selected_extension_keys.add(key)
        else:
            self._selected_extension_keys.discard(key)
        self.stateChanged.emit()

    @Slot()
    def refresh(self) -> None:
        selected_id = self._selected_conversation_id()
        rows = list(self._database.list_conversations(state="active"))
        self._active_turns = {
            str(row["id"])
            for row in rows
            if str(row["status"] or "idle") == "running"
        }
        for conversation_id in tuple(self._active_turn_started_epochs):
            if conversation_id not in self._active_turns:
                self._active_turn_started_epochs.pop(conversation_id, None)
        conversations: list[dict[str, Any]] = []
        for row in rows:
            workspace = self._settings.resolve_path(row["workspace"])
            if is_managed_conversation_workspace(self._settings, workspace):
                project_label = "Projeto temporário"
            else:
                project_label = next(
                    (
                        item["label"]
                        for item in self._projects
                        if item["path"]
                        and Path(item["path"]).resolve(strict=False) == workspace
                    ),
                    workspace.name or str(workspace),
                )
            provider = str(row["provider"] or "codex")
            status = str(row["status"] or "idle")
            provider_label = PROVIDER_LABELS.get(provider, provider.title())
            model_name = str(row["model"] or provider_label)
            conversation_id = str(row["id"])
            if status == "running" and conversation_id not in self._active_turn_started_epochs:
                try:
                    started_epoch = datetime.fromisoformat(
                        str(row["updated_at"] or "")
                    ).timestamp()
                except (TypeError, ValueError):
                    started_epoch = time.time()
                self._active_turn_started_epochs[conversation_id] = started_epoch
            editing = conversation_id in self._draft_records
            pinned = conversation_id in self._pinned_conversation_ids
            conversations.append(
                {
                    "conversationId": conversation_id,
                    "title": str(row["title"] or "Nova conversa"),
                    "subtitle": f"{project_label} · {provider_label} · {STATUS_LABELS.get(status, status.title())}",
                    "provider": provider_label,
                    "modelName": model_name,
                    "status": status,
                    "statusLabel": STATUS_LABELS.get(status, status.title()),
                    "running": status == "running",
                    "workspace": str(workspace),
                    "projectLabel": project_label,
                    "updatedAt": str(row["updated_at"] or ""),
                    "editing": editing,
                    "pinned": pinned,
                    "section": "Rascunhos" if editing else "Conversas",
                    "startedAtEpoch": self._active_turn_started_epochs.get(
                        conversation_id, 0.0
                    ),
                }
            )
        conversations.sort(
            key=lambda item: (
                0 if item["editing"] else 1,
                0 if item["pinned"] else 1,
            )
        )
        self._all_conversations = conversations
        self._apply_filter(selected_id)

    @Slot(str)
    def setSearch(self, value: str) -> None:  # noqa: N802
        normalized = str(value or "").strip()
        if normalized == self._search:
            return
        selected_id = str(self._selected.get("conversationId") or "")
        self._search = normalized
        self.searchChanged.emit()
        self._apply_filter(selected_id)

    @Slot(int)
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

    @Slot(int, str, result=bool)
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

    @Slot(int, result=bool)
    def openProjectFolder(self, index: int) -> bool:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return False
        path = Path(self._projects[index]["path"]).resolve(strict=False)
        if not path.is_dir():
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))

    @Slot(int)
    def copyProjectPath(self, index: int) -> None:  # noqa: N802
        if index <= 0 or index >= len(self._projects):
            return
        path = str(self._projects[index]["path"])
        QGuiApplication.clipboard().setText(path)
        self.messageCopied.emit(path)

    @Slot(int, result=str)
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
                break
        else:
            values.append(
                {
                    "path": str(project_path),
                    "label": self._projects[index]["label"],
                    "icon": icon_path,
                }
            )
        self._store_project_entries(values)
        self._refresh_projects()
        return icon_path

    @Slot(int, result=bool)
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

    @Slot(str, result=bool)
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

    @Slot()
    def togglePinnedCurrent(self) -> None:  # noqa: N802
        conversation_id = self._selected_conversation_id()
        if not conversation_id:
            return
        if conversation_id in self._pinned_conversation_ids:
            self._pinned_conversation_ids.remove(conversation_id)
        else:
            self._pinned_conversation_ids.add(conversation_id)
        self._persist_pinned_conversation_ids()
        self.refresh()
        self.selectionChanged.emit()

    @Slot()
    def startNewChat(self) -> None:  # noqa: N802
        self._remember_current_chat_options()
        enabled = self._enabled_provider_names()
        saved_provider = str(self._preferences.value("chat/last_provider", "") or "")
        self._provider = saved_provider if saved_provider in enabled else enabled[0]
        self._model = str(
            self._preferences.value(f"chat/last_model/{self._provider}", "") or ""
        )
        if not self._model:
            preferred = next(
                (
                    item
                    for item in self._model_items
                    if item.get("provider") == self._provider
                    and str(item.get("value") or "")
                ),
                None,
            )
            if preferred is not None:
                self._model = str(preferred.get("value") or "")
        self._effort = str(
            self._preferences.value(
                "chat/last_effort",
                self._preferences.value(
                    "chat/default_effort", self._settings.default_effort
                ),
            )
            or self._settings.default_effort
        )
        self._service_tier = str(
            self._preferences.value("chat/last_service_tier", "") or ""
        )
        self._approval_profile = str(
            self._preferences.value("chat/last_approval_profile", "auto") or "auto"
        )
        self._vr_mode = self._normalize_vr_mode(
            self._preferences.value("chat/vr_mode", "")
        ) or (
            "vr"
            if self._stored_bool(
                self._preferences.value("chat/vr_flow_enabled", True), True
            )
            else "off"
        )
        self._research_model_keys: list[str] = []
        self._research_max_parallel = 3
        self._code_analysis_enabled = False
        self._code_analysis_release = "current"
        self._code_analysis_release_items = []
        self._senior_profile_enabled = False
        self._vr_response_mode = "auto"
        self._load_research_config()
        self._apply_research_config()
        self._attachments = []
        self.draftRestored.emit("")
        self._activity_steps = []
        self._activity_items = []
        self._reasoning_text = ""
        self._reset_stream_state()
        self._agent_items = []
        if not any(
            item.get("provider") == self._provider
            and str(item.get("value") or "") == self._model
            for item in self._model_items
        ):
            self._reset_model_items()
        self._restore_effort_for_current_model()
        if not self.serviceTierItems:
            self._service_tier = ""
        self._selected_index = -1
        self._selected = {}
        self._draft = True
        self._sync_selected_turn_state()
        self._messages.replace([])
        self.selectionChanged.emit()
        self._status_text = "Pronto"
        self.stateChanged.emit()

    @Slot(int)
    def copyMessage(self, index: int) -> None:  # noqa: N802
        message = self._messages.item(index)
        application = QGuiApplication.instance()
        if message is None or application is None:
            return
        content = str(message.get("content") or "")
        application.clipboard().setText(content)
        self.messageCopied.emit(content)

    @Slot(int)
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
            self._reset_stream_state()
            self._activity_steps = []
            self._activity_items = []
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
            self._approval_profile = str(row["approval_profile"] or "auto")
            self._vr_mode = self._normalize_vr_mode(row["vr_mode"]) or (
                "vr" if bool(row["vr_enabled"]) else "off"
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
            self._messages.update_last(
                content=self._streaming_text,
                displayContent=markdown_for_display(self._displayed_streaming_text),
                segments=self._turn_display_segments(
                    reveal_limit=len(self._displayed_streaming_text)
                ),
            )
        self.stateChanged.emit()

    @Slot(str)
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

    @Slot(int)
    def setEffort(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.effortItems):
            return
        self._effort = self.effortItems[index]["value"]
        self._preferences.setValue("chat/last_effort", self._effort)
        self._preferences.setValue("chat/default_effort", self._effort)
        self._remember_model_effort(self._effort)
        self._preferences.sync()
        if self._selected:
            self._database.update_conversation(
                str(self._selected["conversationId"]), effort=self._effort
            )
        self.stateChanged.emit()

    @Slot(int)
    def setServiceTier(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.serviceTierItems):
            return
        self._service_tier = self.serviceTierItems[index]["value"]
        self._preferences.setValue("chat/last_service_tier", self._service_tier)
        self._preferences.sync()
        if self._selected:
            self._database.update_conversation(
                str(self._selected["conversationId"]),
                service_tier=self._service_tier,
            )
        self.stateChanged.emit()

    @Slot(int)
    def setApproval(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.approvalItems):
            return
        self._approval_profile = self.approvalItems[index]["value"]
        self._preferences.setValue(
            "chat/last_approval_profile", self._approval_profile
        )
        self._preferences.sync()
        if self._selected:
            self._database.update_conversation(
                str(self._selected["conversationId"]),
                approval_profile=self._approval_profile,
            )
        self.stateChanged.emit()

    @staticmethod
    def _normalize_vr_mode(value: object) -> str:
        mode = str(value or "").strip().casefold()
        return mode if mode in {"off", "vr", "ultra"} else ""

    @Slot()
    def cycleVrMode(self) -> None:  # noqa: N802
        order = ["off", "vr", "ultra"]
        nxt = order[(order.index(self._vr_mode) + 1) % len(order)]
        self.setVrMode(nxt)

    @Slot(str)
    def setVrMode(self, mode: str) -> None:  # noqa: N802
        resolved = self._normalize_vr_mode(mode)
        if not resolved or resolved == self._vr_mode:
            return
        self._vr_mode = resolved
        self._preferences.setValue("chat/vr_mode", resolved)
        self._preferences.setValue(
            "chat/vr_flow_enabled", resolved != "off"
        )
        self._preferences.sync()
        conversation_id = str(self._selected.get("conversationId") or "")
        if conversation_id:
            try:
                self._orchestrator.update_vr_mode(conversation_id, resolved)
            except Exception as exc:
                self._status_text = f"Falha: {exc}"
        self.stateChanged.emit()

    def _load_research_config(self) -> None:
        raw_keys = self._preferences.value("research/model_pool", "[]")
        try:
            values = json.loads(str(raw_keys or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        self._research_model_keys = [
            str(item) for item in values if str(item or "").strip()
        ][:1]
        try:
            parallel = int(self._preferences.value("research/max_parallel", 3))
        except (TypeError, ValueError):
            parallel = 3
        self._research_max_parallel = max(1, min(3, parallel))
        self._code_analysis_enabled = self._stored_bool(
            self._preferences.value("research/code_analysis_enabled", False),
            False,
        )
        release_preference = self._workspace_research_preference(
            "code_analysis_release"
        )
        requested_release = str(
            self._preferences.value(
                release_preference,
                self._preferences.value("research/code_analysis_release", "current"),
            )
            or "current"
        ).strip() or "current"
        self._code_analysis_release = requested_release
        source_preference = self._workspace_research_preference(
            "code_analysis_jar_source"
        )
        requested_source = str(
            self._preferences.value(
                source_preference,
                ERP_JAR_SOURCE_VR_EXEC,
            )
            or ERP_JAR_SOURCE_VR_EXEC
        ).strip()
        self._code_analysis_jar_source = (
            requested_source
            if requested_source
            in {ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE}
            else ERP_JAR_SOURCE_VR_EXEC
        )
        scope_preference = self._workspace_research_preference(
            "code_analysis_snapshot_scope"
        )
        requested_scope = str(
            self._preferences.value(
                scope_preference,
                ERP_JAR_SCOPE_FULL_RELEASE,
            )
            or ERP_JAR_SCOPE_FULL_RELEASE
        ).strip()
        self._code_analysis_snapshot_scope = (
            requested_scope
            if requested_scope in {ERP_JAR_SCOPE_FULL_RELEASE, ERP_JAR_SCOPE_SINGLE}
            else ERP_JAR_SCOPE_FULL_RELEASE
        )
        single_jar_preference = self._workspace_research_preference(
            "code_analysis_single_jar_path"
        )
        requested_single_jar = str(
            self._preferences.value(single_jar_preference, "") or ""
        ).strip()
        self._code_analysis_single_jar_path = (
            requested_single_jar
            if requested_single_jar.casefold().endswith(".jar")
            else ""
        )
        heap_preference = self._workspace_research_preference(
            "code_processing_max_heap_mb"
        )
        timeout_preference = self._workspace_research_preference(
            "code_processing_timeout_seconds"
        )
        cpu_preference = self._workspace_research_preference(
            "code_processing_max_cpu_cores"
        )
        disk_preference = self._workspace_research_preference(
            "code_processing_disk_multiplier"
        )
        window_preference = self._workspace_research_preference(
            "code_processing_window"
        )
        try:
            requested_heap = int(
                self._preferences.value(
                    heap_preference, DEFAULT_CODE_PROCESSING_HEAP_MB
                )
            )
        except (TypeError, ValueError):
            requested_heap = DEFAULT_CODE_PROCESSING_HEAP_MB
        try:
            requested_timeout = int(
                self._preferences.value(
                    timeout_preference, DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS
                )
            )
        except (TypeError, ValueError):
            requested_timeout = DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS
        try:
            requested_cpu = int(
                self._preferences.value(
                    cpu_preference, DEFAULT_CODE_PROCESSING_CPU_CORES
                )
            )
        except (TypeError, ValueError):
            requested_cpu = DEFAULT_CODE_PROCESSING_CPU_CORES
        try:
            requested_disk = int(
                self._preferences.value(
                    disk_preference, DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER
                )
            )
        except (TypeError, ValueError):
            requested_disk = DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER
        requested_window = str(
            self._preferences.value(
                window_preference, DEFAULT_CODE_PROCESSING_WINDOW
            )
            or DEFAULT_CODE_PROCESSING_WINDOW
        )
        self._code_processing_max_heap_mb = (
            requested_heap
            if requested_heap in CODE_PROCESSING_HEAP_OPTIONS
            else DEFAULT_CODE_PROCESSING_HEAP_MB
        )
        self._code_processing_timeout_seconds = (
            requested_timeout
            if requested_timeout in CODE_PROCESSING_TIMEOUT_OPTIONS
            else DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS
        )
        self._code_processing_max_cpu_cores = (
            requested_cpu
            if requested_cpu in CODE_PROCESSING_CPU_CORE_OPTIONS
            else DEFAULT_CODE_PROCESSING_CPU_CORES
        )
        self._code_processing_disk_multiplier = (
            requested_disk
            if requested_disk in CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS
            else DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER
        )
        available_windows = {
            str(item["value"]) for item in CODE_PROCESSING_WINDOW_OPTIONS
        }
        self._code_processing_window = (
            requested_window
            if requested_window in available_windows
            else DEFAULT_CODE_PROCESSING_WINDOW
        )
        self._refresh_code_analysis_releases()
        self._refresh_code_analysis_jar_sources()
        self._preferences.setValue(
            release_preference,
            self._code_analysis_release,
        )
        self._preferences.setValue(
            source_preference,
            self._code_analysis_jar_source,
        )
        self._preferences.setValue(
            scope_preference,
            self._code_analysis_snapshot_scope,
        )
        self._preferences.setValue(
            single_jar_preference,
            self._code_analysis_single_jar_path,
        )
        self._preferences.setValue(
            heap_preference,
            self._code_processing_max_heap_mb,
        )
        self._preferences.setValue(
            timeout_preference,
            self._code_processing_timeout_seconds,
        )
        self._preferences.setValue(
            cpu_preference,
            self._code_processing_max_cpu_cores,
        )
        self._preferences.setValue(
            disk_preference,
            self._code_processing_disk_multiplier,
        )
        self._preferences.setValue(window_preference, self._code_processing_window)
        try:
            ErpReleaseCatalog(
                self._settings.root,
                storage_budget_multiplier=self._code_processing_disk_multiplier,
            ).set_storage_budget_multiplier(self._code_processing_disk_multiplier)
        except (ErpReleaseError, OSError, ValueError):
            pass
        if not self._code_analysis_release_items and self._code_analysis_enabled:
            self._code_analysis_enabled = False
            self._preferences.setValue("research/code_analysis_enabled", False)
        self._preferences.sync()
        self._senior_profile_enabled = self._stored_bool(
            self._preferences.value("research/senior_profile_enabled", False),
            False,
        )
        saved_mode = self._normalize_response_mode(
            self._preferences.value("research/response_mode", "auto")
        )
        self._vr_response_mode = saved_mode if self._senior_profile_enabled else "auto"

    def _apply_research_config(self) -> None:
        wanted = set(self._research_model_keys)
        pool = [
            ModelRef(
                provider=str(item.get("provider") or ""),
                model=str(item.get("value") or ""),
                display_name=str(item.get("label") or ""),
            )
            for item in self._model_items
            if str(item.get("key") or "") in wanted and item.get("provider")
        ]
        try:
            self._orchestrator.set_research_config(
                pool=pool,
                max_parallel=self._research_max_parallel,
            )
        except Exception:
            pass

    @Slot("QVariantList")
    def setResearchModels(self, keys: list) -> None:  # noqa: N802
        selected: list[str] = []
        for item in keys:
            key = str(item or "").strip()
            if key:
                selected.append(key)
            if selected:
                break
        self._research_model_keys = selected
        self._preferences.setValue(
            "research/model_pool",
            json.dumps(self._research_model_keys),
        )
        self._preferences.sync()
        self._apply_research_config()
        self.stateChanged.emit()

    @Slot(int)
    def setResearchMaxParallel(self, value: int) -> None:  # noqa: N802
        try:
            parallel = int(value)
        except (TypeError, ValueError):
            return
        self._research_max_parallel = max(1, min(3, parallel))
        self._preferences.setValue("research/max_parallel", self._research_max_parallel)
        self._preferences.sync()
        self._apply_research_config()
        self.stateChanged.emit()

    @Slot(bool)
    def setCodeAnalysisEnabled(self, enabled: bool) -> None:  # noqa: N802
        self._code_analysis_enabled = bool(
            enabled
            and self._code_analysis_release_items
            and self.codeAnalysisReleaseFresh
        )
        self._preferences.setValue(
            "research/code_analysis_enabled", self._code_analysis_enabled
        )
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(str)
    def setCodeAnalysisRelease(self, release_id: str) -> None:  # noqa: N802
        selected = str(release_id or "").strip()
        if self._code_processing_running:
            return
        available = {
            str(item.get("releaseId") or "")
            for item in self._code_analysis_release_items
        }
        if (
            not selected
            or selected not in available
            or selected == self._code_analysis_release
        ):
            return
        self._cancel_code_processing_status_refresh()
        self._code_analysis_release = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_release"),
            selected,
        )
        self._preferences.sync()
        self._refresh_code_analysis_jar_sources()
        self.refreshCodeProcessingStatus()
        self.stateChanged.emit()

    @Slot(str)
    def setCodeAnalysisJarSource(self, source: str) -> None:  # noqa: N802
        selected = str(source or "").strip()
        if selected not in {ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE}:
            return
        if selected == self._code_analysis_jar_source:
            return
        self._code_analysis_jar_source = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_jar_source"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(str)
    def setCodeAnalysisSnapshotScope(self, scope: str) -> None:  # noqa: N802
        selected = str(scope or "").strip()
        if (
            selected not in {ERP_JAR_SCOPE_FULL_RELEASE, ERP_JAR_SCOPE_SINGLE}
            or selected == self._code_analysis_snapshot_scope
            or self._release_snapshot_running
            or self._code_processing_running
        ):
            return
        self._code_analysis_snapshot_scope = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_snapshot_scope"),
            selected,
        )
        self._preferences.sync()
        self._release_snapshot_status = ""
        self.stateChanged.emit()

    @Slot(str, result=bool)
    def setCodeAnalysisSingleJarPath(self, value: str) -> bool:  # noqa: N802
        candidate = Path(str(value or "").strip()).resolve(strict=False)
        if (
            self._release_snapshot_running
            or self._code_processing_running
            or not candidate.is_file()
            or candidate.suffix.casefold() != ".jar"
        ):
            self._release_snapshot_status = "Selecione um arquivo JAR válido."
            self.stateChanged.emit()
            return False
        self._code_analysis_single_jar_path = str(candidate)
        self._preferences.setValue(
            self._workspace_research_preference("code_analysis_single_jar_path"),
            self._code_analysis_single_jar_path,
        )
        self._preferences.sync()
        self._release_snapshot_status = f"JAR selecionado: {candidate.name}"
        self.stateChanged.emit()
        return True

    @Slot(result=str)
    def selectCodeAnalysisSingleJar(self) -> str:  # noqa: N802
        initial = self.codeAnalysisJarSourcePath or str(self._settings.root)
        selected, _filter = QFileDialog.getOpenFileName(
            None,
            "Selecionar JAR para análise",
            initial,
            "Arquivos JAR (*.jar)",
        )
        if selected and self.setCodeAnalysisSingleJarPath(selected):
            return self._code_analysis_single_jar_path
        return ""

    @Slot(int)
    def setCodeProcessingMaxHeapMb(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_HEAP_OPTIONS
            or selected == self._code_processing_max_heap_mb
        ):
            return
        self._code_processing_max_heap_mb = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_max_heap_mb"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(int)
    def setCodeProcessingTimeoutSeconds(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_TIMEOUT_OPTIONS
            or selected == self._code_processing_timeout_seconds
        ):
            return
        self._code_processing_timeout_seconds = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_timeout_seconds"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(int)
    def setCodeProcessingMaxCpuCores(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_CPU_CORE_OPTIONS
            or selected == self._code_processing_max_cpu_cores
        ):
            return
        self._code_processing_max_cpu_cores = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_max_cpu_cores"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(int)
    def setCodeProcessingDiskMultiplier(self, value: int) -> None:  # noqa: N802
        selected = int(value)
        if (
            self._code_processing_running
            or selected not in CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS
            or selected == self._code_processing_disk_multiplier
        ):
            return
        try:
            ErpReleaseCatalog(
                self._settings.root,
                storage_budget_multiplier=selected,
            ).set_storage_budget_multiplier(selected)
        except (ErpReleaseError, OSError, ValueError) as exc:
            self._code_processing_status = f"Limite de disco não alterado: {exc}"
            self.stateChanged.emit()
            return
        self._code_processing_disk_multiplier = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_disk_multiplier"),
            selected,
        )
        self._preferences.sync()
        self.refreshCodeProcessingStatus()
        self.stateChanged.emit()

    @Slot(str)
    def setCodeProcessingWindow(self, value: str) -> None:  # noqa: N802
        selected = str(value or "").strip()
        available = {str(item["value"]) for item in CODE_PROCESSING_WINDOW_OPTIONS}
        if (
            self._code_processing_running
            or selected not in available
            or selected == self._code_processing_window
        ):
            return
        self._code_processing_window = selected
        self._preferences.setValue(
            self._workspace_research_preference("code_processing_window"),
            selected,
        )
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(str)
    def setCodeProcessingRetryBatch(self, batch_id: str) -> None:  # noqa: N802
        selected = str(batch_id or "").strip()
        available = {
            str(item.get("batchId") or "")
            for item in self._code_processing_attention_batches
        }
        if (
            self._code_processing_running
            or selected not in available
            or selected == self._code_processing_retry_batch
        ):
            return
        self._code_processing_retry_batch = selected
        selected_item = next(
            item
            for item in self._code_processing_attention_batches
            if item.get("batchId") == selected
        )
        self._code_processing_current_batch = selected
        self._code_processing_current_jar = str(selected_item.get("jar") or "")
        self.stateChanged.emit()

    def _selected_code_analysis_release_item(self) -> dict[str, Any]:
        return next(
            (
                item
                for item in self._code_analysis_release_items
                if str(item.get("releaseId") or "")
                == self._code_analysis_release
            ),
            {},
        )

    @Slot()
    def refreshCodeProcessingStatus(self) -> None:  # noqa: N802
        if self._code_processing_running or self._code_processing_status_loading:
            return
        release_id = self._code_analysis_release
        if not release_id:
            self._reset_code_processing_status("Adicione uma release para processar.")
            self.stateChanged.emit()
            return
        self._code_processing_status_loading = True
        self._code_processing_status_generation += 1
        generation = self._code_processing_status_generation
        workspace = self._settings.root
        results = self._code_processing_status_results
        self._code_processing_status = "Consultando cobertura local..."
        self.stateChanged.emit()

        def load() -> None:
            try:
                try:
                    coverage = ErpCodeCoverage(workspace).status(release_id)
                except Exception as exc:
                    results.put((generation, release_id, None, None, str(exc)))
                    return
                latest_audit = CodeProcessingAudit(workspace).latest(
                    release_id=release_id
                )
                results.put((generation, release_id, coverage, latest_audit, ""))
            finally:
                with self._code_processing_status_threads_lock:
                    self._code_processing_status_threads.discard(
                        threading.current_thread()
                    )

        self._code_processing_status_poll_timer.start()
        thread = threading.Thread(target=load, daemon=True)
        with self._code_processing_status_threads_lock:
            self._code_processing_status_threads.add(thread)
        thread.start()

    def _cancel_code_processing_status_refresh(self) -> None:
        self._code_processing_status_generation += 1
        self._code_processing_status_loading = False
        self._code_processing_status_poll_timer.stop()

    @Slot()
    def _poll_code_processing_status(self) -> None:
        latest: tuple[
            int,
            str,
            dict[str, Any] | None,
            dict[str, Any] | None,
            str,
        ] | None = None
        while True:
            try:
                latest = self._code_processing_status_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return
        generation, release_id, coverage, audit_event, error = latest
        if generation != self._code_processing_status_generation:
            return
        self._code_processing_status_loading = False
        self._code_processing_status_poll_timer.stop()
        if release_id != self._code_analysis_release or self._code_processing_running:
            self.stateChanged.emit()
            return
        if error:
            self._reset_code_processing_status(
                f"Não foi possível consultar a cobertura: {error}"
            )
        elif isinstance(coverage, dict):
            self._apply_code_processing_coverage(coverage)
            self._restore_code_processing_audit(audit_event, coverage)
        self.stateChanged.emit()

    def _reset_code_processing_status(self, message: str) -> None:
        self._code_processing_status = message
        self._code_processing_progress = 0
        self._code_processing_covered_jars = 0
        self._code_processing_total_jars = 0
        self._code_processing_can_retry = False
        self._code_processing_current_jar = ""
        self._code_processing_current_batch = ""
        self._code_processing_attention_batches = []
        self._code_processing_retry_batch = ""
        self._code_processing_eta = {}

    @staticmethod
    def _format_megabytes(value: int) -> str:
        return f"{max(0, int(value)) / (1024 * 1024):.1f} MB"

    @staticmethod
    def _format_duration_ms(value: int) -> str:
        total_seconds = max(0, int(value)) // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"

    def _apply_code_processing_coverage(self, coverage: dict[str, Any]) -> None:
        total = max(0, int(coverage.get("expected_jar_count") or 0))
        covered = max(0, int(coverage.get("covered_jar_count") or 0))
        remaining = max(0, int(coverage.get("remaining_jar_count") or 0))
        blocked = list(coverage.get("blocked_plans") or [])
        active = list(coverage.get("active_plans") or [])
        self._code_processing_eta = dict(coverage.get("eta") or {})
        self._code_processing_total_jars = total
        self._code_processing_covered_jars = min(covered, total) if total else covered
        self._code_processing_progress = (
            min(100, int(round(covered * 100 / total))) if total else 0
        )
        attention_items: list[dict[str, Any]] = []
        for plan in blocked:
            if not isinstance(plan, dict):
                continue
            selected_jars = [str(item) for item in plan.get("selected_jars") or []]
            for batch in plan.get("attention_batches") or []:
                if not isinstance(batch, dict) or not batch.get("batch_id"):
                    continue
                batch_id = str(batch["batch_id"])
                jar = str(batch.get("jar_relative_path") or "")
                if not jar and len(selected_jars) == 1:
                    jar = selected_jars[0]
                state = str(batch.get("state") or "failed")
                ordinal = int(batch.get("ordinal") or 0) + 1
                attention_items.append(
                    {
                        "batchId": batch_id,
                        "jar": jar,
                        "state": state,
                        "ordinal": ordinal,
                        "label": (
                            f"{jar or 'JAR não identificado'} · lote {ordinal} · {state}"
                        ),
                    }
                )
        self._code_processing_attention_batches = attention_items
        attention_ids = {
            str(item.get("batchId") or "") for item in attention_items
        }
        if self._code_processing_retry_batch not in attention_ids:
            self._code_processing_retry_batch = (
                str(attention_items[0]["batchId"]) if attention_items else ""
            )
        self._code_processing_can_retry = bool(attention_items)
        current_plan = next(
            (
                plan
                for plan in [*active, *blocked]
                if isinstance(plan, dict) and plan.get("current_batch")
            ),
            {},
        )
        current_batch = dict(current_plan.get("current_batch") or {})
        self._code_processing_current_jar = str(
            current_batch.get("jar_relative_path") or ""
        )
        if not self._code_processing_current_jar and remaining:
            pending_jars = list(coverage.get("remaining_jars") or [])
            self._code_processing_current_jar = (
                str(pending_jars[0]) if pending_jars else ""
            )
        self._code_processing_current_batch = str(
            current_batch.get("batch_id") or ""
        )
        if remaining == 0 and total:
            self._code_processing_status = (
                f"Processamento concluído: {covered}/{total} JARs indexados."
            )
        elif self._code_processing_can_retry:
            self._code_processing_status = (
                f"Atenção necessária: {covered}/{total} JARs indexados; "
                "há lote com falha ou saída parcial."
            )
        elif active:
            self._code_processing_status = (
                f"Plano retomável: {covered}/{total} JARs indexados."
            )
        else:
            self._code_processing_status = (
                f"Pronto para processar: {covered}/{total} JARs indexados."
            )

    def _restore_code_processing_audit(
        self,
        audit_event: dict[str, Any] | None,
        coverage: dict[str, Any],
    ) -> None:
        if not isinstance(audit_event, dict):
            return
        manifest_hash = str(coverage.get("release_manifest_sha256") or "")
        audit_hash = str(audit_event.get("release_manifest_sha256") or "")
        if not manifest_hash or audit_hash != manifest_hash:
            return
        self._code_processing_release = str(audit_event.get("release_id") or "")
        self._code_processing_manifest_hash = audit_hash
        self._code_processing_run_id = str(audit_event.get("run_id") or "")
        event = str(audit_event.get("event") or "")
        details = dict(audit_event.get("details") or {})
        restored_telemetry = details.get("telemetry")
        if isinstance(restored_telemetry, dict):
            self._code_processing_telemetry = dict(restored_telemetry)
        if event == "failed":
            error = str(details.get("error") or "erro desconhecido")
            self._code_processing_status = f"Última execução falhou: {error}"
        elif event == "paused":
            self._code_processing_status = (
                "Processamento pausado entre lotes: "
                f"{self._code_processing_covered_jars}/"
                f"{self._code_processing_total_jars} JARs indexados."
            )
        elif event in {"started", "toolchain_validated", "progress", "batch_retried"}:
            self._code_processing_status = (
                "Execução anterior foi interrompida; pronta para retomar: "
                f"{self._code_processing_covered_jars}/"
                f"{self._code_processing_total_jars} JARs indexados."
            )

    @Slot(result=bool)
    def startCodeProcessing(self) -> bool:  # noqa: N802
        return self._start_code_processing(retry_batch_id="")

    @Slot(result=bool)
    def retryCodeProcessing(self) -> bool:  # noqa: N802
        if not self._code_processing_can_retry or not self._code_processing_retry_batch:
            return False
        return self._start_code_processing(
            retry_batch_id=self._code_processing_retry_batch
        )

    def _start_code_processing(self, *, retry_batch_id: str) -> bool:
        if self._code_processing_running or self._release_snapshot_running:
            return False
        if (
            self._code_processing_total_jars > 0
            and self._code_processing_covered_jars
            >= self._code_processing_total_jars
        ):
            return False
        release_id = self._code_analysis_release
        selected = self._selected_code_analysis_release_item()
        if not release_id or not selected:
            self._code_processing_status = "Selecione uma release inventariada."
            self.stateChanged.emit()
            return False
        if selected.get("freshness") != "fresh":
            self._code_processing_status = (
                "A release está desatualizada; gere um novo snapshot antes de processar."
            )
            self.stateChanged.emit()
            return False
        window_status = processing_window_status(self._code_processing_window)
        if not window_status["allowed"]:
            self._code_processing_status = (
                "Fora da janela ociosa configurada: "
                + str(window_status["label"])
                + "."
            )
            self.stateChanged.emit()
            return False
        try:
            manifest = ErpReleaseCatalog(self._settings.root).load_manifest(release_id)
        except (ErpReleaseError, OSError, ValueError) as exc:
            self._code_processing_status = f"Manifesto da release indisponível: {exc}"
            self.stateChanged.emit()
            return False
        manifest_hash = str(manifest.get("release_manifest_sha256") or "").strip()
        if not manifest_hash:
            self._code_processing_status = "O manifesto da release não possui SHA-256."
            self.stateChanged.emit()
            return False

        self._cancel_code_processing_status_refresh()
        self._code_processing_release = release_id
        self._code_processing_manifest_hash = manifest_hash
        self._code_processing_run_id = uuid4().hex
        self._code_processing_telemetry = {}
        max_heap_mb = self._code_processing_max_heap_mb
        timeout_seconds = self._code_processing_timeout_seconds
        max_cpu_cores = self._code_processing_max_cpu_cores
        disk_multiplier = self._code_processing_disk_multiplier
        processing_window = self._code_processing_window
        try:
            CodeProcessingAudit(self._settings.root).record(
                "started",
                run_id=self._code_processing_run_id,
                release_id=release_id,
                manifest_sha256=manifest_hash,
                details={
                    "retry_batch_id": retry_batch_id,
                    "max_heap_mb": max_heap_mb,
                    "timeout_seconds": timeout_seconds,
                    "max_cpu_cores": max_cpu_cores,
                    "process_priority": "low",
                    "disk_budget_multiplier": disk_multiplier,
                    "processing_window": processing_window,
                    "global_java_concurrency": 1,
                    "covered_jar_count": self._code_processing_covered_jars,
                    "expected_jar_count": self._code_processing_total_jars,
                },
            )
        except OSError as exc:
            self._code_processing_status = (
                f"Não foi possível criar a trilha de auditoria local: {exc}"
            )
            self.stateChanged.emit()
            return False
        self._code_processing_running = True
        self._code_processing_started_at = time.monotonic()
        self._code_processing_pause_requested = False
        self._code_processing_pause_event.clear()
        self._code_processing_status = (
            f"Validando Java 17 e decompiladores para {release_id}..."
        )
        self._code_processing_can_retry = False
        self.stateChanged.emit()
        self._code_processing_poll_timer.start()
        self._code_processing_thread = threading.Thread(
            target=self._run_code_processing,
            args=(
                release_id,
                manifest_hash,
                retry_batch_id,
                max_heap_mb,
                timeout_seconds,
                max_cpu_cores,
                disk_multiplier,
                processing_window,
            ),
            daemon=True,
        )
        self._code_processing_thread.start()
        return True

    @Slot()
    def pauseCodeProcessing(self) -> None:  # noqa: N802
        if not self._code_processing_running or self._code_processing_pause_requested:
            return
        self._code_processing_pause_requested = True
        self._code_processing_pause_event.set()
        self._code_processing_status = (
            "Pausa solicitada; o lote Java atual será concluído com segurança."
        )
        self.stateChanged.emit()

    def _run_code_processing(
        self,
        release_id: str,
        manifest_hash: str,
        retry_batch_id: str,
        max_heap_mb: int,
        timeout_seconds: int,
        max_cpu_cores: int,
        disk_multiplier: int,
        processing_window: str,
    ) -> None:
        results = self._code_processing_results

        def publish(event: dict[str, Any]) -> None:
            results.put(event)
            self._codeProcessingReady.emit()

        audit = CodeProcessingAudit(self._settings.root)
        run_id = self._code_processing_run_id
        started_monotonic = time.monotonic()
        job_telemetry: dict[str, Any] = {
            "processed_batches": 0,
            "decompiler_duration_ms": 0,
            "peak_rss_bytes": 0,
            "cpu_user_ms": 0,
            "cpu_kernel_ms": 0,
            "input_bytes": 0,
            "output_bytes": 0,
            "timed_out_batches": 0,
            "metrics_available": False,
            "cpu_limit_applied": False,
            "wall_duration_ms": 0,
        }
        try:
            toolchain = JvmToolchain(
                self._settings.root,
                app_dir=self._settings.app_dir,
            )
            doctor = toolchain.doctor()
            java_ready = bool((doctor.get("java") or {}).get("available"))
            decompiler_ready = any(
                bool((doctor.get(name) or {}).get("available"))
                for name in ("vineflower", "cfr")
            )
            if not java_ready or not decompiler_ready:
                unavailable = []
                for name, label in (
                    ("java", "Java 17 isolado"),
                    ("vineflower", "Vineflower"),
                    ("cfr", "CFR"),
                ):
                    status = doctor.get(name) or {}
                    if not bool(status.get("available")):
                        detail = str(status.get("error") or "indisponível")
                        unavailable.append(f"{label}: {detail}")
                raise CodeCoverageError(
                    "Java 17 isolado e ao menos um decompilador verificado são necessários. "
                    + " | ".join(unavailable)
                )
            audit.record(
                "toolchain_validated",
                run_id=run_id,
                release_id=release_id,
                manifest_sha256=manifest_hash,
                details={
                    "java_ready": java_ready,
                    "decompiler_ready": decompiler_ready,
                },
            )

            catalog = ErpReleaseCatalog(
                self._settings.root,
                storage_budget_multiplier=disk_multiplier,
            )
            catalog.set_storage_budget_multiplier(disk_multiplier)
            manager = ErpCodeCoverage(
                self._settings.root,
                catalog=catalog,
                adapters=(
                    toolchain.adapters()
                    if hasattr(toolchain, "adapters")
                    else None
                ),
            )
            coverage = manager.status(release_id)
            self._require_frozen_code_manifest(coverage, manifest_hash)
            if retry_batch_id:
                attention = [
                    batch
                    for plan in coverage.get("blocked_plans") or []
                    if isinstance(plan, dict)
                    for batch in plan.get("attention_batches") or []
                    if isinstance(batch, dict) and batch.get("batch_id")
                ]
                if not attention:
                    raise CodeCoverageError("Nenhum lote com falha está disponível para retry.")
                attention_by_id = {
                    str(item["batch_id"]): item for item in attention
                }
                if retry_batch_id not in attention_by_id:
                    raise CodeCoverageError(
                        "O lote selecionado para retry não está mais bloqueado: "
                        + retry_batch_id
                    )
                manager.executor.retry(retry_batch_id)
                audit.record(
                    "batch_retried",
                    run_id=run_id,
                    release_id=release_id,
                    manifest_sha256=manifest_hash,
                    details={"batch_id": retry_batch_id},
                )
                coverage = manager.status(release_id)
                self._require_frozen_code_manifest(coverage, manifest_hash)
            publish({"kind": "progress", "coverage": coverage})

            while True:
                window_status = processing_window_status(processing_window)
                if not window_status["allowed"]:
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "paused",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "paused",
                            "coverage": coverage,
                            "telemetry": telemetry,
                            "reason": (
                                "janela ociosa encerrada: "
                                + str(window_status["label"])
                            ),
                        }
                    )
                    return
                if self._code_processing_pause_event.is_set():
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "paused",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {"kind": "paused", "coverage": coverage, "telemetry": telemetry}
                    )
                    return
                if int(coverage.get("remaining_jar_count") or 0) == 0:
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "completed",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "completed",
                            "coverage": coverage,
                            "telemetry": telemetry,
                        }
                    )
                    return
                if coverage.get("blocked_plans"):
                    telemetry = self._merge_code_processing_telemetry(
                        job_telemetry, [], started_monotonic
                    )
                    self._record_code_processing_coverage(
                        audit,
                        "attention",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "attention",
                            "coverage": coverage,
                            "telemetry": telemetry,
                        }
                    )
                    return

                advanced = manager.advance(
                    release_id,
                    approved=True,
                    jars_per_plan=1,
                    batch_limit=1,
                    max_heap_mb=max_heap_mb,
                    timeout_seconds=timeout_seconds,
                    max_cpu_cores=max_cpu_cores,
                    process_priority="low",
                    processing_window=processing_window,
                )
                coverage = dict(advanced.get("coverage") or {})
                self._require_frozen_code_manifest(coverage, manifest_hash)
                executed = [
                    item
                    for item in advanced.get("executed") or []
                    if isinstance(item, dict)
                ]
                telemetry = self._merge_code_processing_telemetry(
                    job_telemetry, executed, started_monotonic
                )
                self._record_code_processing_coverage(
                    audit,
                    "progress",
                    run_id,
                    release_id,
                    manifest_hash,
                    coverage,
                    telemetry,
                )
                publish(
                    {"kind": "progress", "coverage": coverage, "telemetry": telemetry}
                )
                if any(
                    str(item.get("state") or "") in {"failed", "partial"}
                    for item in executed
                    if isinstance(item, dict)
                ):
                    self._record_code_processing_coverage(
                        audit,
                        "attention",
                        run_id,
                        release_id,
                        manifest_hash,
                        coverage,
                        telemetry,
                    )
                    publish(
                        {
                            "kind": "attention",
                            "coverage": coverage,
                            "telemetry": telemetry,
                        }
                    )
                    return
                if not executed and int(coverage.get("remaining_jar_count") or 0) > 0:
                    raise CodeCoverageError(
                        "O plano não avançou nenhum lote; revise o estado antes de continuar."
                    )
        except Exception as exc:
            telemetry = self._merge_code_processing_telemetry(
                job_telemetry, [], started_monotonic
            )
            try:
                audit.record(
                    "failed",
                    run_id=run_id,
                    release_id=release_id,
                    manifest_sha256=manifest_hash,
                    details={"error": str(exc), "telemetry": telemetry},
                )
            except OSError:
                pass
            publish(
                {"kind": "error", "error": str(exc), "telemetry": telemetry}
            )

    @staticmethod
    def _record_code_processing_coverage(
        audit: CodeProcessingAudit,
        event: str,
        run_id: str,
        release_id: str,
        manifest_hash: str,
        coverage: dict[str, Any],
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        details = {
            "covered_jar_count": int(coverage.get("covered_jar_count") or 0),
            "expected_jar_count": int(coverage.get("expected_jar_count") or 0),
            "remaining_jar_count": int(coverage.get("remaining_jar_count") or 0),
        }
        if telemetry:
            details["telemetry"] = dict(telemetry)
        audit.record(
            event,
            run_id=run_id,
            release_id=release_id,
            manifest_sha256=manifest_hash,
            details=details,
        )

    @staticmethod
    def _merge_code_processing_telemetry(
        aggregate: dict[str, Any],
        executions: list[dict[str, Any]],
        started_monotonic: float,
    ) -> dict[str, Any]:
        for execution in executions:
            if not isinstance(execution, dict):
                continue
            telemetry = execution.get("telemetry")
            if not isinstance(telemetry, dict):
                continue
            aggregate["processed_batches"] = int(
                aggregate.get("processed_batches") or 0
            ) + 1
            for field in (
                "decompiler_duration_ms",
                "cpu_user_ms",
                "cpu_kernel_ms",
                "input_bytes",
                "output_bytes",
            ):
                source_field = (
                    "duration_ms" if field == "decompiler_duration_ms" else field
                )
                aggregate[field] = int(aggregate.get(field) or 0) + max(
                    0, int(telemetry.get(source_field) or 0)
                )
            aggregate["peak_rss_bytes"] = max(
                int(aggregate.get("peak_rss_bytes") or 0),
                max(0, int(telemetry.get("peak_rss_bytes") or 0)),
            )
            aggregate["metrics_available"] = bool(
                aggregate.get("metrics_available")
                or telemetry.get("metrics_available")
            )
            aggregate["cpu_limit_applied"] = bool(
                aggregate.get("cpu_limit_applied")
                or telemetry.get("cpu_limit_applied")
            )
            aggregate["timed_out_batches"] = int(
                aggregate.get("timed_out_batches") or 0
            ) + int(bool(telemetry.get("timed_out")))
        aggregate["wall_duration_ms"] = int(
            (time.monotonic() - started_monotonic) * 1000
        )
        return dict(aggregate)

    @staticmethod
    def _require_frozen_code_manifest(
        coverage: dict[str, Any], manifest_hash: str
    ) -> None:
        current = str(coverage.get("release_manifest_sha256") or "")
        if not current or current != manifest_hash:
            raise CodeCoverageError(
                "O manifesto da release mudou depois do início; a execução foi interrompida."
            )

    @Slot()
    def _poll_code_processing(self) -> None:
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self._code_processing_results.get_nowait())
            except queue.Empty:
                break
        if not events:
            return

        for event in events:
            coverage = event.get("coverage")
            if isinstance(coverage, dict):
                self._apply_code_processing_coverage(coverage)
            telemetry = event.get("telemetry")
            if isinstance(telemetry, dict):
                self._code_processing_telemetry = dict(telemetry)
            kind = str(event.get("kind") or "")
            if kind == "progress":
                self._code_processing_status = (
                    f"Processando {self._code_processing_release}: "
                    f"{self._code_processing_covered_jars}/"
                    f"{self._code_processing_total_jars} JARs indexados."
                )
            elif kind == "paused":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                reason = str(event.get("reason") or "").strip()
                self._code_processing_status = (
                    f"Processamento pausado entre lotes: "
                    f"{self._code_processing_covered_jars}/"
                    f"{self._code_processing_total_jars} JARs indexados."
                    + (f" Motivo: {reason}." if reason else "")
                )
            elif kind == "attention":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
            elif kind == "completed":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
            elif kind == "error":
                self._code_processing_running = False
                self._code_processing_pause_requested = False
                self._code_processing_status = (
                    "Falha no processamento local: "
                    + str(event.get("error") or "erro desconhecido")
                )
        if not self._code_processing_running:
            self._code_processing_started_at = 0.0
            self._code_processing_poll_timer.stop()
            self._refresh_code_analysis_releases()
        self.stateChanged.emit()

    @Slot(str, result=bool)
    def snapshotCodeAnalysisRelease(self, release_id: str) -> bool:  # noqa: N802
        """Detect, categorize and inventory local JARs off the UI thread."""

        selected_release = str(release_id or "").strip()
        single_jar = self._code_analysis_snapshot_scope == ERP_JAR_SCOPE_SINGLE
        source = (
            self._code_analysis_single_jar_path
            if single_jar
            else self.codeAnalysisJarSourcePath
        )
        if self._release_snapshot_running or self._code_processing_running:
            return False
        if not source:
            self._release_snapshot_status = (
                "Selecione o JAR que será analisado."
                if single_jar
                else "Selecione um diretório de JARs."
            )
            self.stateChanged.emit()
            return False
        if single_jar:
            candidate = Path(source).resolve(strict=False)
            if not candidate.is_file() or candidate.suffix.casefold() != ".jar":
                self._release_snapshot_status = "Selecione um arquivo JAR válido."
                self.stateChanged.emit()
                return False

        self._release_snapshot_running = True
        self._release_snapshot_started_at = time.monotonic()
        self._release_snapshot_status = (
            (
                f"Detectando aplicação e versão de {Path(source).name} localmente..."
                if single_jar
                else "Detectando aplicações e compondo a release localmente..."
            )
        )
        self.stateChanged.emit()
        results = self._release_snapshot_results
        workspace = self._settings.root

        def snapshot() -> None:
            try:
                manifest = ErpReleaseCatalog(
                    workspace,
                    expected_jar_count=(1 if single_jar else EXPECTED_ERP_JAR_COUNT),
                ).snapshot_detected_release(
                    source,
                    release_id=selected_release,
                    analysis_scope=(
                        ERP_JAR_SCOPE_SINGLE
                        if single_jar
                        else ERP_JAR_SCOPE_FULL_RELEASE
                    ),
                )
            except Exception as exc:
                results.put(
                    {
                        "ok": False,
                        "release_id": selected_release,
                        "error": str(exc),
                    }
                )
                self._releaseSnapshotReady.emit()
                return
            results.put(
                {
                    "ok": True,
                    "release_id": str(manifest.get("release_id") or selected_release),
                    "jar_count": int(manifest.get("jar_count") or 0),
                    "package_jar_count": int(manifest.get("package_jar_count") or 0),
                    "base_release_id": str(manifest.get("base_release_id") or ""),
                    "updated_applications": list(
                        manifest.get("updated_applications") or []
                    ),
                }
            )
            self._releaseSnapshotReady.emit()

        self._release_snapshot_poll_timer.start()
        threading.Thread(target=snapshot, daemon=True).start()
        return True

    @Slot(str, result=bool)
    def removeCodeAnalysisRelease(self, release_id: str) -> bool:  # noqa: N802
        """Remove an inventoried release after confirmation in the UI."""

        selected_release = str(release_id or "").strip()
        if (
            not selected_release
            or self._release_snapshot_running
            or self._code_processing_running
        ):
            return False

        available = {
            str(item.get("releaseId") or "")
            for item in self._code_analysis_release_items
        }
        if selected_release not in available:
            self._release_snapshot_status = (
                f"Não foi possível remover a release {selected_release}: "
                "ela não está mais inventariada."
            )
            self.stateChanged.emit()
            return False

        self._release_snapshot_running = True
        self._release_snapshot_started_at = time.monotonic()
        self._release_snapshot_status = (
            f"Removendo o índice da release {selected_release} localmente..."
        )
        self.stateChanged.emit()
        results = self._release_snapshot_results
        workspace = self._settings.root

        def remove() -> None:
            try:
                result = ErpReleaseCatalog(workspace).remove_index(
                    selected_release,
                    approved=True,
                )
            except Exception as exc:
                results.put(
                    {
                        "operation": "remove",
                        "ok": False,
                        "release_id": selected_release,
                        "error": str(exc),
                    }
                )
                self._releaseSnapshotReady.emit()
                return
            results.put(
                {
                    "operation": "remove",
                    "ok": True,
                    **result,
                }
            )
            self._releaseSnapshotReady.emit()

        self._release_snapshot_poll_timer.start()
        threading.Thread(target=remove, daemon=True).start()
        return True

    @Slot()
    def _poll_release_snapshot(self) -> None:
        latest: dict[str, Any] | None = None
        while True:
            try:
                latest = self._release_snapshot_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return

        self._release_snapshot_running = False
        self._release_snapshot_started_at = 0.0
        self._release_snapshot_poll_timer.stop()
        release_id = str(latest.get("release_id") or "")
        if str(latest.get("operation") or "") == "remove":
            if bool(latest.get("ok")):
                self._refresh_code_analysis_releases()
                self._preferences.setValue(
                    self._workspace_research_preference("code_analysis_release"),
                    self._code_analysis_release,
                )
                self._preferences.setValue(
                    "research/code_analysis_enabled",
                    self._code_analysis_enabled,
                )
                self._preferences.sync()
                self._refresh_code_analysis_jar_sources()
                self.refreshCodeProcessingStatus()
                reclaimed = int(latest.get("reclaimed_bytes") or 0)
                self._release_snapshot_status = (
                    f"Release {release_id} removida do índice. "
                    f"{reclaimed / (1024 * 1024):.1f} MB liberados; "
                    "os JARs de origem foram preservados."
                )
            else:
                detail = str(latest.get("error") or "falha desconhecida")
                self._release_snapshot_status = (
                    f"Não foi possível remover a release {release_id}: {detail}"
                )
            self.stateChanged.emit()
            return
        if bool(latest.get("ok")):
            self._refresh_code_analysis_releases()
            available = {
                str(item.get("releaseId") or "")
                for item in self._code_analysis_release_items
            }
            if release_id in available:
                self._code_analysis_release = release_id
                self._preferences.setValue(
                    self._workspace_research_preference("code_analysis_release"),
                    release_id,
                )
                self._preferences.sync()
            self._refresh_code_analysis_jar_sources()
            self.refreshCodeProcessingStatus()
            jar_count = int(latest.get("jar_count") or 0)
            package_jar_count = int(latest.get("package_jar_count") or jar_count)
            base_release_id = str(latest.get("base_release_id") or "")
            updated = [str(item) for item in latest.get("updated_applications") or []]
            jar_label = "JAR copiado e verificado" if jar_count == 1 else "JARs copiados e verificados"
            self._release_snapshot_status = (
                f"Release {release_id} detectada e adicionada: {jar_count} {jar_label} "
                f"localmente; pacote recebido com {package_jar_count}."
                + (f" Base completa: {base_release_id}." if base_release_id else "")
                + (f" Atualizados: {', '.join(updated)}." if updated else "")
            )
        else:
            detail = str(latest.get("error") or "falha desconhecida")
            release_label = release_id or "automática"
            self._release_snapshot_status = (
                f"Não foi possível adicionar a release {release_label}: {detail}"
            )
        self.stateChanged.emit()

    def _workspace_research_preference(self, name: str) -> str:
        identity = str(self._settings.root.resolve()).replace("\\", "/").casefold()
        workspace_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"research/workspaces/{workspace_id}/{name}"

    def _refresh_code_analysis_jar_sources(self) -> None:
        workspace_path = self._settings.erp_releases_dir
        options = (
            (
                ERP_JAR_SOURCE_VR_EXEC,
                "Instalação local do ERP",
                DEFAULT_ERP_JAR_SOURCE_PATH,
            ),
            (
                ERP_JAR_SOURCE_WORKSPACE,
                "Workspace atual",
                workspace_path,
            ),
        )
        items: list[dict[str, Any]] = []
        catalog = ErpReleaseCatalog(self._settings.root)
        for value, label, path in options:
            resolved = path.resolve(strict=False)
            exists = resolved.is_dir()
            jar_count = catalog.count_source_jars(resolved) if exists else 0
            status = (
                f"{jar_count} JAR(s) encontrados"
                if exists
                else "Pasta não encontrada"
            )
            items.append(
                {
                    "value": value,
                    "label": f"{label} · {resolved}",
                    "path": str(resolved),
                    "exists": exists,
                    "jarCount": jar_count,
                    "status": status,
                }
            )
        self._code_analysis_jar_source_items = items

    def _refresh_code_analysis_releases(self) -> None:
        try:
            statuses = ErpReleaseCatalog(self._settings.root).list_statuses()
        except (OSError, ValueError):
            statuses = []
        items: list[dict[str, Any]] = []
        code_index = JavaCodeIndex(self._settings.root)
        for status in statuses[:3]:
            release_id = str(status.get("release_id") or "").strip()
            if not release_id or status.get("state") == "failed":
                continue
            freshness = str(status.get("freshness") or "unknown")
            jar_count = int(status.get("jar_count") or 0)
            try:
                coverage = code_index.coverage(release_id)
            except (
                DecompilationBatchError,
                ErpReleaseError,
                OSError,
                ValueError,
                sqlite3.Error,
            ):
                coverage = {}
            try:
                classpath = ClasspathPolicyStore(self._settings.root).status(release_id)
            except (ClasspathError, ErpReleaseError, OSError, ValueError, sqlite3.Error):
                classpath = {}
            covered_jar_count = int(coverage.get("covered_jar_count") or 0)
            analysis_scope = str(status.get("analysis_scope") or "full_release")
            scope_label = (
                "escopo: 1 JAR"
                if analysis_scope == ERP_JAR_SCOPE_SINGLE
                else "release incremental"
                if analysis_scope == "incremental_release"
                else "release completa"
            )
            classpath_status = str(classpath.get("classpath_status") or "unknown")
            classpath_label = {
                "resolved": "classpath resolvido",
                "partial": "classpath parcial",
                "unknown": "classpath desconhecido",
            }.get(classpath_status, f"classpath {classpath_status}")
            freshness_label = {
                "fresh": "atualizado",
                "stale": "desatualizado",
                "missing": "origem ausente",
            }.get(freshness, "frescor desconhecido")
            items.append(
                {
                    "releaseId": release_id,
                    "manifestSha256": str(
                        status.get("release_manifest_sha256") or ""
                    ),
                    "label": (
                        f"{release_id} · {covered_jar_count}/{jar_count} JARs "
                        f"indexados · {scope_label} · {freshness_label} · "
                        f"{classpath_label}"
                    ),
                    "freshness": freshness,
                    "state": str(status.get("state") or "incomplete"),
                    "coveredJarCount": covered_jar_count,
                    "jarCount": jar_count,
                    "analysisScope": analysis_scope,
                    "classpathStatus": classpath_status,
                    "warning": " ".join(
                        [
                            *(str(item) for item in status.get("warnings") or []),
                            *(
                                [
                                    "A ordem efetiva do classpath ainda não foi confirmada; "
                                    "resultados conflitantes serão sinalizados."
                                ]
                                if classpath_status != "resolved"
                                else []
                            ),
                        ]
                    ),
                }
            )
        self._code_analysis_release_items = items
        available = {str(item["releaseId"]) for item in items}
        if self._code_analysis_release not in available:
            self._code_analysis_release = str(items[0]["releaseId"]) if items else ""
        selected = self._selected_code_analysis_release_item()
        if (
            self._code_analysis_enabled
            and (not selected or selected.get("freshness") != "fresh")
        ):
            self._code_analysis_enabled = False

    @Slot()
    def refreshCodeAnalysisReleases(self) -> None:  # noqa: N802
        previous = self._code_analysis_release
        was_enabled = self._code_analysis_enabled
        preferences_changed = False
        self._refresh_code_analysis_releases()
        self._refresh_code_analysis_jar_sources()
        if not self._code_analysis_release_items:
            self._code_analysis_enabled = False
        if self._code_analysis_release != previous:
            self._preferences.setValue(
                self._workspace_research_preference("code_analysis_release"),
                self._code_analysis_release,
            )
            preferences_changed = True
        if self._code_analysis_enabled != was_enabled:
            self._preferences.setValue(
                "research/code_analysis_enabled",
                self._code_analysis_enabled,
            )
            preferences_changed = True
        if preferences_changed:
            self._preferences.sync()
        self.refreshCodeProcessingStatus()
        self.stateChanged.emit()

    @staticmethod
    def _normalize_response_mode(value: object) -> str:
        selected = str(value or "auto").strip().casefold()
        return (
            selected
            if selected in {"auto", "training", "support", "implementation"}
            else "auto"
        )

    @Slot(bool)
    def setSeniorProfileEnabled(self, enabled: bool) -> None:  # noqa: N802
        self._senior_profile_enabled = bool(enabled)
        if not self._senior_profile_enabled:
            self._vr_response_mode = "auto"
            self._preferences.setValue("research/response_mode", "auto")
        self._preferences.setValue(
            "research/senior_profile_enabled",
            self._senior_profile_enabled,
        )
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(str)
    def setVrResponseMode(self, mode: str) -> None:  # noqa: N802
        selected = self._normalize_response_mode(mode)
        if not self._senior_profile_enabled:
            selected = "auto"
        if selected == self._vr_response_mode:
            return
        self._vr_response_mode = selected
        self._preferences.setValue("research/response_mode", selected)
        self._preferences.sync()
        self.stateChanged.emit()

    @Slot(result=str)
    def addProject(self) -> str:  # noqa: N802
        selected = QFileDialog.getExistingDirectory(
            None,
            "Adicionar projeto ao Chat VR",
            str(self._settings.root),
        )
        if not selected:
            return ""
        return self._add_project_path(Path(selected))

    @Slot()
    def beginProjectFolderBrowse(self) -> None:  # noqa: N802
        self._set_project_folder(Path.home())

    @Slot(str)
    def browseProjectFolder(self, value: str) -> None:  # noqa: N802
        raw = str(value or "").strip()
        if not raw:
            return
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self._project_folder / candidate
        self._set_project_folder(candidate)

    @Slot()
    def browseParentProjectFolder(self) -> None:  # noqa: N802
        self._set_project_folder(self._project_folder.parent)

    @Slot(result=str)
    def addCurrentProjectFolder(self) -> str:  # noqa: N802
        return self._add_project_path(self._project_folder)

    @Slot()
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
            else:
                path = str(value or "").strip()
                label = ""
                icon = ""
            if path:
                entries.append({"path": path, "label": label, "icon": icon})
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

    @Slot(str)
    def sendMessage(self, text: str) -> None:  # noqa: N802
        content = str(text or "").strip()
        if not content or self.turnRunning:
            return
        force_research = False
        if content.lower().startswith("/pesquisa"):
            argument = content[len("/pesquisa"):].strip()
            if self._vr_mode == "off":
                self._status_text = "Ative o VR para pesquisar na base local."
                self.stateChanged.emit()
                return
            if not argument:
                self._status_text = "Use: /pesquisa <pergunta>"
                self.stateChanged.emit()
                return
            content = argument
            force_research = True
        selected_extensions = [
            item
            for item in self._extension_items
            if str(item.get("key") or "") in self._selected_extension_keys
        ]
        skills = [
            dict(item.get("payload") or {})
            for item in selected_extensions
            if item.get("kind") == "skill"
        ]
        mcp_tools = [
            dict(item.get("payload") or {})
            for item in selected_extensions
            if item.get("kind") == "mcp"
        ]
        conversation_id = str(self._selected.get("conversationId") or "")
        if not conversation_id:
            workspace = self._project_scope or self._settings.root
            try:
                conversation_id = self._orchestrator.new_conversation(
                    self._provider,
                    self._model,
                    self._effort,
                    service_tier=self._service_tier,
                    approval_profile=self._approval_profile,
                    mcp_tools=mcp_tools,
                    workspace=workspace,
                    vr_mode=self._vr_mode,
                )
            except Exception as exc:
                self._status_text = f"Falha: {exc}"
                self.stateChanged.emit()
                return
            self._draft = False
            self.refresh()
            selected_index = next(
                (
                    index
                    for index, item in enumerate(self._conversations._items)
                    if item["conversationId"] == conversation_id
                ),
                -1,
            )
            if selected_index >= 0:
                self.selectConversation(selected_index)
        elif mcp_tools:
            try:
                configured_id = self._orchestrator.configure_tools(
                    conversation_id, [], mcp_tools
                )
            except Exception as exc:
                self._status_text = f"Falha: {exc}"
                self.stateChanged.emit()
                return
            if configured_id != conversation_id:
                conversation_id = configured_id
                self.refresh()
                selected_index = next(
                    (
                        index
                        for index, item in enumerate(self._conversations._items)
                        if item["conversationId"] == conversation_id
                    ),
                    -1,
                )
                if selected_index >= 0:
                    self.selectConversation(selected_index)
        image_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        image_paths = [
            item["path"]
            for item in self._attachments
            if Path(item["path"]).suffix.casefold() in image_extensions
        ]
        reference_paths = [
            item["path"]
            for item in self._attachments
            if item["path"] not in image_paths or self._provider != "codex"
        ]
        file_references = " ".join(
            f'@"{item["path"]}"'
            for item in self._attachments
            if item["path"] in reference_paths
        )
        provider_text = " ".join(value for value in (file_references, content) if value)
        self._active_turns.add(conversation_id)
        self._active_turn_started_epochs[conversation_id] = time.time()
        self._sync_selected_turn_state()
        self._status_text = "Executando…"
        self._activity_steps = self._default_activity_steps()
        self._activity_items = []
        self._reasoning_text = ""
        self._reset_stream_state()
        self._activity_started_at = time.monotonic()
        self._activity_elapsed_seconds = 0
        self._activity_clock.start()
        self._agent_items = []
        self._messages.append(
            {
                "messageId": -1,
                "role": "user",
                "content": content,
                "displayContent": content,
                "segments": [],
                "createdAt": "",
                "responseMode": "vr" if self._vr_mode != "off" else "native",
            }
        )
        self._messages.append(self._activity_timeline_item())
        self.stateChanged.emit()
        self.selectionChanged.emit()
        try:
            selected_code_release = self._selected_code_analysis_release_item()
            self._orchestrator.send(
                conversation_id,
                provider_text,
                self._runtimeEvent.emit,
                skills,
                content,
                content,
                self._vr_mode != "off",
                image_paths=image_paths,
                vr_mode=self._vr_mode,
                force_research=force_research,
                code_analysis_enabled=(
                    self._code_analysis_enabled
                    and bool(self._code_analysis_release)
                ),
                code_analysis_release=self._code_analysis_release,
                code_analysis_manifest_sha256=(
                    str(selected_code_release.get("manifestSha256") or "")
                    if self._code_analysis_enabled
                    else ""
                ),
                response_mode=(
                    self._vr_response_mode
                    if self._senior_profile_enabled
                    else "auto"
                ),
            )
            if conversation_id in self._draft_records:
                self._draft_records.pop(conversation_id, None)
                self._persist_draft_records()
            self._attachments = []
            self._selected_extension_keys = set()
            self.refresh()
            self.stateChanged.emit()
        except Exception as exc:
            self._active_turns.discard(conversation_id)
            self._active_turn_started_epochs.pop(conversation_id, None)
            self._sync_selected_turn_state()
            self._status_text = f"Falha: {exc}"
            self.refresh()
            self.stateChanged.emit()

    @Slot()
    def stopTurn(self) -> None:  # noqa: N802
        target = self._selected_conversation_id()
        if not target or target not in self._active_turns:
            return
        self._status_text = "Parando…"
        self.stateChanged.emit()

        def interrupt() -> None:
            try:
                self._orchestrator.interrupt(target)
            except Exception as exc:
                self._runtimeEvent.emit(RuntimeEvent(target, "error", str(exc)))

        threading.Thread(target=interrupt, daemon=True).start()

    @Slot()
    def archiveCurrentConversation(self) -> None:  # noqa: N802
        conversation_id = self._selected_conversation_id()
        if not conversation_id or conversation_id in self._active_turns:
            return
        try:
            self._orchestrator.archive(conversation_id)
        except Exception as exc:
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()
            return
        self._draft_records.pop(conversation_id, None)
        self._pinned_conversation_ids.discard(conversation_id)
        self._persist_draft_records()
        self._persist_pinned_conversation_ids()
        self.refresh()
        self.conversationArchived.emit(conversation_id)
        self.startNewChat()

    @Slot()
    def trashCurrentConversation(self) -> None:  # noqa: N802
        conversation_id = self._selected_conversation_id()
        if not conversation_id or conversation_id in self._active_turns:
            return
        try:
            self._orchestrator.trash(conversation_id)
        except Exception as exc:
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()
            return
        self._draft_records.pop(conversation_id, None)
        self._pinned_conversation_ids.discard(conversation_id)
        self._persist_draft_records()
        self._persist_pinned_conversation_ids()
        self.refresh()
        self.startNewChat()

    @Slot(bool, bool)
    def decideApproval(self, approved: bool, session: bool) -> None:  # noqa: N802
        request = dict(self._approval_request)
        if not request:
            return
        request_id = str(request.get("request_id") or "")
        conversation_id = str(request.get("conversation_id") or self._selected.get("conversationId") or "")
        try:
            if request.get("_dynamic"):
                self._orchestrator.approve_dynamic_tool(request_id, approved)
            else:
                self._orchestrator.approve(
                    conversation_id,
                    request_id,
                    approved,
                    session,
                    request,
                )
        except Exception as exc:
            self._status_text = f"Falha: {exc}"
        self._approval_request = {}
        self.stateChanged.emit()

    @Slot(object)
    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        if not isinstance(event, RuntimeEvent):
            return
        if event.kind == "turn_started":
            self._active_turns.add(event.conversation_id)
        selected_id = self._selected_conversation_id()
        if event.conversation_id != selected_id:
            self._on_background_runtime_event(event)
            return
        self._sync_selected_turn_state()
        self._record_execution_event(event)
        if event.kind == "assistant_delta":
            delta = str(event.text or "")
            if not delta:
                return
            self._streaming_text += delta
            self._turn_text += delta
            self._stream_pending_text += delta
            if not self._assistant_stream_started:
                self._assistant_stream_started = True
                self._advance_default_activity()
                self._schedule_state_update()
            self._ensure_streaming_message()
            if not self._stream_timer.isActive():
                self._stream_timer.start()
        elif event.kind in {"approval_requested", "dynamic_tool_approval_requested"}:
            self._approval_request = dict(event.payload)
            self._approval_request["conversation_id"] = event.conversation_id
            self._approval_request["_dynamic"] = event.kind.startswith("dynamic")
            self._status_text = "Aguardando aprovação…"
            self.approvalRequested.emit(dict(self._approval_request))
            self.stateChanged.emit()
        elif event.kind == "reasoning_delta":
            self._reasoning_text += str(event.text or "")
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
        elif event.kind in {"turn_completed", "orchestration_completed"}:
            self._queue_terminal_state(event.kind)
        elif event.kind in {"error", "orchestration_cancelled"}:
            self._queue_terminal_state(event.kind)

    @staticmethod
    def _browser_address_from_event(event: RuntimeEvent) -> str:
        payload = event.payload if isinstance(event.payload, dict) else {}
        item = payload.get("item") or {}
        if not isinstance(item, dict):
            item = {}
        item_type = str(
            item.get("type") or payload.get("type") or payload.get("tool") or ""
        ).casefold()
        if not any(
            marker in item_type
            for marker in ("browser", "webfetch", "web_fetch")
        ):
            return ""
        for mapping in (item, payload):
            for key in ("url", "address", "uri"):
                value = str(mapping.get(key) or "").strip()
                if value.startswith(("http://", "https://", "localhost")):
                    return value
        return ""

    def _on_background_runtime_event(self, event: RuntimeEvent) -> None:
        if event.kind in {"approval_requested", "dynamic_tool_approval_requested"}:
            self._approval_request = dict(event.payload)
            self._approval_request["conversation_id"] = event.conversation_id
            self._approval_request["_dynamic"] = event.kind.startswith("dynamic")
            self.approvalRequested.emit(dict(self._approval_request))
            return
        if event.kind in {
            "turn_completed",
            "orchestration_completed",
            "error",
            "orchestration_cancelled",
        }:
            self._finish_background_turn(event.conversation_id)

    def _finish_background_turn(self, conversation_id: str) -> None:
        self._active_turns.discard(str(conversation_id or ""))
        self._active_turn_started_epochs.pop(str(conversation_id or ""), None)
        self._sync_selected_turn_state()
        self.stateChanged.emit()
        self.refresh()

    def _ensure_streaming_message(self) -> None:
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
            }
        )

    def _reset_stream_state(self) -> None:
        if hasattr(self, "_stream_timer"):
            self._stream_timer.stop()
        if hasattr(self, "_activity_clock"):
            self._activity_clock.stop()
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

    def _schedule_state_update(self) -> None:
        if not self._state_update_timer.isActive():
            self._state_update_timer.start()

    def _tick_activity_clock(self) -> None:
        if not self._activity_started_at:
            self._activity_clock.stop()
            return
        elapsed = max(0, int(time.monotonic() - self._activity_started_at))
        if elapsed != self._activity_elapsed_seconds:
            self._activity_elapsed_seconds = elapsed
            self._schedule_state_update()

    @Slot()
    def _flush_stream_step(self) -> None:
        if self._stream_pending_text:
            backlog = len(self._stream_pending_text)
            batch_size = max(2, min(96, (backlog + 55) // 56))
            visible = self._stream_pending_text[:batch_size]
            self._stream_pending_text = self._stream_pending_text[batch_size:]
            self._displayed_streaming_text += visible
            self._ensure_streaming_message()
            self._messages.update_last(
                content=self._streaming_text,
                displayContent=markdown_for_display(self._displayed_streaming_text),
                segments=self._turn_display_segments(
                    reveal_limit=len(self._displayed_streaming_text)
                ),
            )
            return
        self._stream_timer.stop()
        if self._stream_terminal_kind:
            terminal_kind = self._stream_terminal_kind
            self._stream_terminal_kind = ""
            self._finalize_terminal_state(terminal_kind)

    def _queue_terminal_state(self, kind: str) -> None:
        if (
            not self.turnRunning
            and kind in {"turn_completed", "orchestration_completed"}
            and self._status_text in {"Erro", "Interrompido"}
        ):
            return
        self._stream_terminal_kind = kind
        if self._activity_started_at:
            self._activity_elapsed_seconds = max(
                self._activity_elapsed_seconds,
                int(time.monotonic() - self._activity_started_at),
            )
        self._activity_clock.stop()
        for step in self._activity_steps:
            if step.get("state") not in {"error", "cancelled"}:
                step["state"] = "completed"
        terminal_state = (
            "error"
            if kind == "error"
            else "cancelled" if kind == "orchestration_cancelled" else "completed"
        )
        for item in self._activity_items:
            if item.get("state") == "running":
                item["state"] = terminal_state
        if self._stream_pending_text:
            self._status_text = "Finalizando resposta…"
            if not self._stream_timer.isActive():
                self._stream_timer.start()
            self.stateChanged.emit()
            return
        terminal_kind = self._stream_terminal_kind
        self._stream_terminal_kind = ""
        self._finalize_terminal_state(terminal_kind)

    def _finalize_terminal_state(self, kind: str) -> None:
        conversation_id = self._selected_conversation_id()
        self._active_turns.discard(conversation_id)
        self._active_turn_started_epochs.pop(conversation_id, None)
        self._sync_selected_turn_state()
        self._status_text = (
            "Erro"
            if kind == "error"
            else "Interrompido" if kind == "orchestration_cancelled" else "Pronto"
        )
        self._reload_selected_messages()
        self.refresh()
        self.stateChanged.emit()

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
        self._activity_steps = []
        self._activity_items = []
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
                elif kind == "assistant_delta":
                    self._turn_text += text
                    self._streaming_text += text
                    self._displayed_streaming_text += text
                    self._advance_default_activity()
                else:
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

    def _record_execution_event(
        self, event: RuntimeEvent, *, emit_state: bool = True
    ) -> None:
        """Adapt orchestration events into compact, QML-safe presentation state."""
        execution_kinds = {
            "turn_started",
            "response_plan_created",
            "tool_event",
            "intent_analysis_started",
            "intent_analysis_completed",
            "response_contract_created",
            "orchestration_started",
            "plan_created",
            "parallel_group_started",
            "parallel_group_completed",
            "agent_started",
            "agent_delta",
            "agent_completed",
            "agent_failed",
            "research_started",
            "research_completed",
            "evidence_merge_completed",
            "evidence_validation_completed",
            "critic_completed",
            "refinement_requested",
            "refinement_started",
            "refinement_completed",
            "validation_started",
            "validation_completed",
            "revision_started",
            "synthesis_started",
            "synthesis_completed",
            "final_validation_started",
            "final_validation_completed",
            "response_rewrite_started",
            "response_rewrite_completed",
            "orchestration_completed",
            "orchestration_cancelled",
            "response_empty",
            "research_failed",
            "context_transferred",
        }
        if event.kind not in execution_kinds:
            return

        if event.kind == "turn_started" and not self._activity_steps:
            self._activity_steps = self._default_activity_steps()

        if event.kind == "response_plan_created":
            raw_steps = [
                " ".join(str(item or "").split())
                for item in event.payload.get("steps") or []
                if str(item or "").strip()
            ]
            completed = max(0, int(event.payload.get("completed") or 0))
            self._activity_steps = [
                {
                    "kind": "plan_step",
                    "text": text,
                    "state": (
                        "completed"
                        if index < completed
                        else "running" if index == completed else "pending"
                    ),
                }
                for index, text in enumerate(dict.fromkeys(raw_steps))
            ]

        if event.kind == "tool_event":
            self._record_tool_event(event)

        if event.kind == "plan_created":
            raw_plan = event.payload.get("plan") or {}
            planned = list(raw_plan.get("agents") or []) if isinstance(raw_plan, dict) else []
            planned.extend(event.payload.get("runtime_stages") or [])
            for raw_item in planned:
                if isinstance(raw_item, dict):
                    self._upsert_agent(raw_item, "aguardando")

        identifier = str(event.payload.get("agent_id") or event.payload.get("id") or "")
        if event.kind in {"agent_started", "agent_completed", "agent_failed"} and identifier:
            status = {
                "agent_started": "executando",
                "agent_completed": "concluído",
                "agent_failed": "falhou",
            }[event.kind]
            output = str(
                event.payload.get("output")
                or event.payload.get("output_preview")
                or event.payload.get("error")
                or ""
            ).strip()
            self._upsert_agent(event.payload, status, output=output)
        elif event.kind == "agent_delta" and identifier:
            self._upsert_agent(event.payload, "executando", delta=event.text)
        elif event.kind in {"synthesis_started", "orchestration_completed"}:
            target_status = "executando" if event.kind == "synthesis_started" else "concluído"
            for item in self._agent_items:
                if item.get("final"):
                    item["status"] = target_status
                    item["statusLabel"] = target_status.title()
        elif event.kind == "orchestration_cancelled":
            for item in self._agent_items:
                if item.get("status") == "executando":
                    item["status"] = "interrompido"
                    item["statusLabel"] = "Interrompido"

        message = str(event.text or "").strip()
        if not message:
            message = {
                "context_transferred": "Contexto transferido",
                "response_empty": "Resposta vazia",
                "research_failed": "Pesquisa falhou",
            }.get(event.kind, "")
        if event.kind not in {
            "response_plan_created",
            "tool_event",
            "turn_started",
        } and message and (
            not self._activity_items
            or self._activity_items[-1].get("text") != message
            or self._activity_items[-1].get("kind") != event.kind
        ):
            self._activity_items.append(
                {
                    "kind": event.kind,
                    "text": message,
                    "detail": "",
                    "state": self._event_state(event.kind),
                }
            )
            self._activity_items = self._activity_items[-60:]
        if event.kind.endswith("_completed") and any(
            step.get("state") == "pending" for step in self._activity_steps
        ):
            self._advance_default_activity()
        if emit_state:
            self.stateChanged.emit()

    def _record_tool_event(self, event: RuntimeEvent) -> None:
        payload = dict(event.payload or {})
        raw_item = payload.get("item") or payload.get("part") or {}
        if not raw_item and any(
            key in payload for key in ("name", "tool", "input", "command")
        ):
            raw_item = payload
        item = raw_item if isinstance(raw_item, dict) else {}
        item_type = str(item.get("type") or "")
        identifier = str(
            item.get("id")
            or payload.get("itemId")
            or payload.get("item_id")
            or payload.get("request_id")
            or ""
        )
        fallback_labels = {
            "reasoning": "Raciocínio",
            "commandExecution": "Comando",
            "fileChange": "Alteração de arquivo",
            "mcpToolCall": "Ferramenta MCP",
            "webSearch": "Pesquisa na web",
            "web_search": "Pesquisa na web",
            "userMessage": "Preparação do contexto",
            "agentMessage": "Preparação da resposta",
        }
        label = str(
            item.get("name")
            or item.get("tool")
            or fallback_labels.get(item_type)
            or item_type
            or event.text
            or "Ferramenta"
        ).strip()
        lifecycle = str(payload.get("lifecycle") or "")
        state = (
            "error"
            if payload.get("success") is False
            else "completed" if lifecycle.endswith("completed") or payload.get("success") is True
            else "running"
        )
        detail_values: list[str] = []
        for value in (
            item.get("command"),
            item.get("arguments"),
            item.get("input"),
            item.get("changes"),
            item.get("aggregatedOutput"),
            item.get("output"),
            payload.get("arguments"),
            payload.get("output"),
        ):
            if value in (None, "", [], {}):
                continue
            if isinstance(value, str):
                rendered = value
            else:
                rendered = json.dumps(value, ensure_ascii=False, indent=2)
            rendered = rendered.strip()
            if rendered and rendered not in detail_values:
                detail_values.append(rendered)
        detail = "\n\n".join(detail_values)[:4000]
        existing = next(
            (
                candidate
                for candidate in reversed(self._activity_items)
                if identifier and candidate.get("id") == identifier
            ),
            None,
        )
        if existing is None:
            self._record_turn_tool_segment(item_type)
            self._activity_items.append(
                {
                    "id": identifier,
                    "kind": (
                        "reasoning"
                        if item_type == "reasoning"
                        else "activity"
                        if item_type in {"userMessage", "agentMessage"}
                        else "tool"
                    ),
                    "itemType": item_type,
                    "text": label,
                    "detail": detail,
                    "state": state,
                }
            )
            self._activity_items = self._activity_items[-60:]
            return
        existing["text"] = label or existing.get("text", "Ferramenta")
        existing["itemType"] = item_type
        existing["state"] = state
        if detail:
            existing["detail"] = detail

    def _record_turn_tool_segment(self, item_type: str) -> None:
        """Track per-turn tool usage so summaries can interleave with text."""
        if item_type in {"reasoning", "userMessage", "agentMessage"}:
            return
        if not (self.turnRunning or self._restoring_turn_history):
            return
        cursor = len(self._turn_text)
        if cursor > self._segment_cursor:
            self._turn_segments.append(
                {"kind": "text", "start": self._segment_cursor, "end": cursor}
            )
            self._segment_cursor = cursor
        category = (
            "commands"
            if item_type == "commandExecution"
            else "files"
            if item_type == "fileChange"
            else "tools"
        )
        last = self._turn_segments[-1] if self._turn_segments else None
        if last is not None and last.get("kind") == "tools":
            last[category] = int(last.get(category) or 0) + 1
            return
        segment: dict[str, Any] = {
            "kind": "tools",
            "offset": cursor,
            "commands": 0,
            "files": 0,
            "tools": 0,
        }
        segment[category] = 1
        self._turn_segments.append(segment)

    @staticmethod
    def _tool_summary_label(segment: dict[str, Any]) -> str:
        parts: list[str] = []
        files = int(segment.get("files") or 0)
        commands = int(segment.get("commands") or 0)
        tools = int(segment.get("tools") or 0)
        if files:
            parts.append(f"Alterou {files} arquivo" + ("s" if files > 1 else ""))
        if commands:
            parts.append(f"executou {commands} comando" + ("s" if commands > 1 else ""))
        if tools:
            parts.append(f"usou {tools} ferramenta" + ("s" if tools > 1 else ""))
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " e " + parts[-1]

    @staticmethod
    def _segments_for_text_chunk(chunk: str) -> list[dict[str, Any]]:
        chunk = str(chunk or "")
        if not chunk.strip():
            return []
        segments = segments_for_display(chunk)
        if segments:
            return segments
        return [{"kind": "text", "content": markdown_for_display(chunk)}]

    def _turn_display_segments(
        self, reveal_limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Build QML segments for the live turn, interleaving tool summaries."""
        if not any(segment.get("kind") == "tools" for segment in self._turn_segments):
            return []
        text = self._turn_text
        limit = (
            len(text)
            if reveal_limit is None
            else max(0, min(int(reveal_limit), len(text)))
        )
        units: list[dict[str, Any]] = []
        for segment in self._turn_segments:
            if segment.get("kind") == "text":
                units.append(
                    {
                        "kind": "text",
                        "start": int(segment.get("start") or 0),
                        "end": int(segment.get("end") or 0),
                    }
                )
            else:
                units.append(
                    {
                        "kind": "tools",
                        "offset": int(segment.get("offset") or 0),
                        "segment": segment,
                    }
                )
        units.append({"kind": "text", "start": self._segment_cursor, "end": len(text)})
        display: list[dict[str, Any]] = []
        for unit in units:
            if unit["kind"] == "tools":
                if unit["offset"] > limit:
                    break
                segment = unit["segment"]
                display.append(
                    {
                        "kind": "tools",
                        "label": self._tool_summary_label(segment),
                        "commands": int(segment.get("commands") or 0),
                        "files": int(segment.get("files") or 0),
                        "tools": int(segment.get("tools") or 0),
                    }
                )
                continue
            start, end = int(unit["start"]), int(unit["end"])
            if start >= limit:
                break
            visible_end = min(end, limit)
            if visible_end > start:
                display.extend(
                    self._segments_for_text_chunk(text[start:visible_end])
                )
            if limit < end:
                break
        return display

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
    def _event_state(kind: str) -> str:
        if kind in {"response_empty", "context_transferred"}:
            return "completed"
        if kind.endswith("failed"):
            return "error"
        if kind.endswith("completed"):
            return "completed"
        if kind.endswith("cancelled"):
            return "cancelled"
        return "running"

    def _reload_selected_messages(self) -> None:
        conversation_id = str(self._selected.get("conversationId") or "")
        if not conversation_id:
            return
        rows = self._database.messages(conversation_id)
        items = [
                {
                    "messageId": int(row["id"]),
                    "role": str(row["role"] or "assistant"),
                    "content": str(row["content"] or ""),
                    "displayContent": markdown_for_display(str(row["content"] or "")),
                    "segments": segments_for_display(str(row["content"] or ""))
                    if str(row["role"] or "") == "assistant"
                    else [],
                    "createdAt": str(row["created_at"] or ""),
                    "responseMode": str(row["response_mode"] or ""),
                }
                for row in rows
                if str(row["role"] or "") != "system"
            ]
        if self._activity_steps or self._activity_items or self._reasoning_text:
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
        }

    def _apply_filter(self, selected_id: str = "") -> None:
        term = self._search.casefold()
        filtered = [
            item
            for item in self._all_conversations
            if (
                self._project_scope is None
                or Path(str(item["workspace"])).resolve(strict=False)
                == self._project_scope
            )
            and (
                not term
                or term
                in " ".join(
                    (
                        str(item["title"]),
                        str(item["subtitle"]),
                        str(item["workspace"]),
                    )
                ).casefold()
            )
        ]
        self._conversations.replace(filtered)
        self.conversationsChanged.emit()
        if self._draft:
            self._selected_index = -1
            self._selected = {}
            self._messages.replace([])
            self.selectionChanged.emit()
            return
        target_index = next(
            (
                index
                for index, item in enumerate(filtered)
                if item["conversationId"] == selected_id
            ),
            0 if filtered else -1,
        )
        if target_index >= 0:
            self.selectConversation(target_index)
        else:
            self._clear_selection()

    def _clear_selection(self) -> None:
        changed = self._selected_index != -1 or bool(self._selected)
        self._reset_stream_state()
        self._selected_index = -1
        self._selected = {}
        self._sync_selected_turn_state()
        self._status_text = "Pronto"
        self._messages.replace([])
        if changed:
            self.selectionChanged.emit()

    def _refresh_projects(self) -> None:
        saved_scope = str(
            self._preferences.value("chat/current_project", "") or ""
        ).strip()
        candidates: list[Path] = []
        custom_labels: dict[Path, str] = {}
        custom_icons: dict[Path, str] = {}
        hidden_paths = set(self._stored_project_paths("chat/hidden_projects"))

        def include(value: object, label: object = "", icon: object = "") -> None:
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
                    include(
                        value.get("path", ""),
                        value.get("label", "") if key == "chat/projects" else "",
                        value.get("icon", "") if key == "chat/projects" else "",
                    )
                else:
                    include(value)

        for row in self._database.list_conversations(state="all"):
            workspace = self._settings.resolve_path(row["workspace"])
            if not is_managed_conversation_workspace(self._settings, workspace):
                include(workspace)

        self._projects = [{"label": "Todos os projetos", "path": "", "icon": ""}]
        self._projects.extend(
            {
                "label": custom_labels.get(path) or path.name or str(path),
                "path": str(path),
                "icon": custom_icons.get(path, ""),
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

    @staticmethod
    def _stored_bool(value: object, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() not in {
            "", "0", "false", "no", "off"
        }

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True


from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import (
    QObject,
    Property,
    QSettings,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from ..brand import ORGANIZATION_NAME, SETTINGS_APP_NAME
from ..code_processing_audit import CodeProcessingAudit
from ..config import MarySettings
from ..db import MaryDatabase
from ..models import RuntimeEvent
from ..task_plan import TaskPlan
from ..orchestrator import ChatOrchestrator
from ..workspace import is_managed_conversation_workspace

LOGGER = logging.getLogger(__name__)




















from .bridges.presentation import (
    markdown_for_display,
    ConversationListModel,
    MessageListModel,
    segments_for_display,
    PROVIDER_LABELS,
    STATUS_LABELS,
    EFFORT_LABELS,
    ERP_JAR_SOURCE_VR_EXEC,
    MAX_FILE_SUGGESTION_ENTRIES,
    ERP_JAR_SCOPE_FULL_RELEASE,
    ERP_JAR_SCOPE_SINGLE,
    DEFAULT_ERP_JAR_SOURCE_PATH as DEFAULT_ERP_JAR_SOURCE_PATH,
    EXPECTED_ERP_JAR_COUNT,
    CODE_PROCESSING_HARDWARE,
    CODE_PROCESSING_HEAP_OPTIONS,
    CODE_PROCESSING_TIMEOUT_OPTIONS,
    CODE_PROCESSING_CPU_CORE_OPTIONS,
    CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS,
    CODE_PROCESSING_WINDOW_OPTIONS,
    DEFAULT_CODE_PROCESSING_HEAP_MB,
    DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS,
    DEFAULT_CODE_PROCESSING_CPU_CORES,
    DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER,
    DEFAULT_CODE_PROCESSING_WINDOW,
)
from .bridges.codeadmin import CodeAdminDomain
from .bridges.providersettings import ProviderSettingsDomain
from .bridges.activity import ActivityDomain
from .bridges.conversations import ConversationsDomain

class ChatBridge(QObject):
    @property
    def _CodeAdmin_domain(self):
        return CodeAdminDomain(self)

    @property
    def _ProviderSettings_domain(self):
        return ProviderSettingsDomain(self)

    @property
    def _Activity_domain(self):
        return ActivityDomain(self)

    @property
    def _Conversations_domain(self):
        return ConversationsDomain(self)

    """Expose existing conversation reads without changing domain behavior."""

    conversationsChanged = Signal()
    selectionChanged = Signal()
    searchChanged = Signal()
    projectsChanged = Signal()
    projectFolderChanged = Signal()
    messageCopied = Signal(str)
    stateChanged = Signal()
    decompiledDirectoryDetected = Signal("QVariantMap")
    approvalRequested = Signal("QVariantMap")
    fileSuggestionsChanged = Signal()
    conversationArchived = Signal(str)
    draftRestored = Signal(str)
    browserNavigationRequested = Signal(str)
    _conversationTrashFinished = Signal(object)
    _codeAnalysisCoverageWarmed = Signal(object)
    _applicationsLoaded = Signal(object)
    _appComparisonLoaded = Signal(object)
    _appSourcesLoaded = Signal(object)
    activeSkillsChanged = Signal()
    showSkillsInSlashMenuChanged = Signal()
    showUsageLimitsRequested = Signal()
    usageLimitsChanged = Signal()

    def __init__(
        self,
        settings: MarySettings,
        database: MaryDatabase,
        preferences: QSettings | None = None,
        *,
        open_new_chat: bool = False,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._database = database
        self._orchestrator = ChatOrchestrator(settings, database)
        from .bridges.retrieval import RetrievalBridge
        self._retrieval_settings = RetrievalBridge(self._orchestrator.retrieval_service, self)
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
        self._active_skills: list[dict[str, Any]] = []
        self._usage_snapshot: dict[str, Any] = {}
        self._selected_index = -1
        self._selected: dict[str, Any] = {}
        self._draft = False
        self._active_turns: set[str] = set()
        self._active_turn_started_epochs: dict[str, float] = {}
        self._conversation_delete_running = False
        self._conversation_delete_id = ""
        self._deleting_conversation_ids: set[str] = set()
        self._turn_running = False
        self._running_conversation_id = ""
        self._closed = False
        self._status_text = "Pronto"
        self._streaming_text = ""
        self._current_message_key: str = ""
        self._ui_execution_ids: dict[str, int] = {}
        self._ui_terminal_executions: set[tuple[str, int]] = set()
        self._message_streaming_texts: dict[str, str] = {}
        self._message_displayed_texts: dict[str, str] = {}
        self._message_pending_texts: dict[str, str] = {}
        self._displayed_streaming_text = ""
        self._stream_pending_text = ""
        self._stream_terminal_kind = ""
        self._assistant_stream_started = False
        self._approval_request: dict[str, Any] = {}
        self._pending_approvals: list[dict[str, Any]] = []
        self._activity_steps: list[dict[str, str]] = []
        self._task_plan = TaskPlan()
        self._task_plan_current = False
        self._activity_items: list[dict[str, str]] = []
        self._trace_items: list[dict[str, Any]] = []
        self._trace_sequence = 0
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
            self._preferences.value("chat/last_approval_profile", "full_access") or "full_access"
        )
        if self._approval_profile in ("auto", "auto_edits", ""):
            self._approval_profile = "full_access"
        self._vr_mode = "vr"
        self._research_model_keys: list[str] = []
        self._research_max_parallel = 3
        self._code_analysis_enabled = False
        self._code_analysis_release = "current"
        self._code_analysis_release_items: list[dict[str, Any]] = []
        self._release_coverage_root = settings.root
        self._release_coverage_generation = 0
        self._release_coverage_thread: threading.Thread | None = None
        self._release_coverage_stop = threading.Event()
        self._release_coverage_cache = self._CodeAdmin_domain._load_cached_release_coverage()
        self._codeAnalysisCoverageWarmed.connect(
            self._on_coverage_warmed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._code_analysis_jar_source = ERP_JAR_SOURCE_VR_EXEC
        self._code_analysis_jar_source_items: list[dict[str, Any]] = []
        self._code_analysis_snapshot_scope = ERP_JAR_SCOPE_FULL_RELEASE
        self._code_analysis_single_jar_path = ""
        self._application_import_preview = {}
        self._application_preview_generation = 0
        self._application_preview_thread = None
        self._package_operation_thread = None
        self._release_snapshot_running = False
        self._release_snapshot_status = ""
        self._release_snapshot_results: queue.SimpleQueue[dict[str, Any]] = (
            queue.SimpleQueue()
        )
        self._code_processing_running = False
        self._code_processing_pause_requested = False
        self._code_processing_status_loading = False
        self._code_processing_status_generation = 0
        self._code_processing_status = ""
        self._code_processing_progress = 0
        self._code_processing_covered_jars = 0
        self._code_processing_total_jars = 0
        self._code_processing_can_retry = False
        self._ultra_application_contexts: list[dict[str, Any]] = []
        self._applications_catalog: list[dict[str, Any]] = []
        self._selected_app_id: str = ""
        self._app_versions: list[dict[str, Any]] = []
        self._selected_app_version: str = ""
        self._selected_app_variant_id: str = ""
        self._selected_version_details: dict[str, Any] = {}
        self._version_comparison_result: dict[str, Any] = {}
        self._packages_catalog: list[dict[str, Any]] = []
        self._apps_catalog_data: dict[str, Any] = {}
        self._apps_catalog_error = ""
        self._apps_catalog_thread: threading.Thread | None = None
        self._apps_catalog_dirty = False
        self._app_variants: list[dict[str, Any]] = []
        self._selected_app_origin_id = ""
        self._code_processing_relative_jars: tuple[str, ...] = ()
        self._applicationsLoaded.connect(self._on_applications_loaded, Qt.ConnectionType.QueuedConnection)
        self._app_comparison_thread: threading.Thread | None = None
        self._app_sources = {}
        self._app_sources_thread = None
        self._appSourcesLoaded.connect(self._on_app_sources_loaded, Qt.ConnectionType.QueuedConnection)
        self._app_comparison_generation = 0
        self._appComparisonLoaded.connect(self._on_app_comparison_loaded, Qt.ConnectionType.QueuedConnection)
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
        self._code_processing_capacity: dict[str, Any] = {}
        self._code_processing_pause_event = threading.Event()
        self._code_processing_cancel_event = threading.Event()
        self._code_processing_cancel_requested = False
        self._code_processing_can_cancel = False
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
        self._conversationTrashFinished.connect(
            self._finish_conversation_trash,
            Qt.ConnectionType.QueuedConnection,
        )
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
        self._releaseSnapshotReady.connect(
            self._poll_release_snapshot, Qt.ConnectionType.QueuedConnection
        )
        self._code_processing_poll_timer = QTimer(self)
        self._code_processing_poll_timer.setInterval(100)
        self._code_processing_poll_timer.timeout.connect(
            self._poll_code_processing
        )
        self._codeProcessingReady.connect(
            self._poll_code_processing, Qt.ConnectionType.QueuedConnection
        )
        self._code_processing_status_poll_timer = QTimer(self)
        self._code_processing_status_poll_timer.setInterval(50)
        self._code_processing_status_poll_timer.timeout.connect(
            self._poll_code_processing_status
        )
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(80)
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
        if open_new_chat or not self._all_conversations:
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
    def selectedConversationId(self) -> str:  # noqa: N802
        return self._selected_conversation_id()

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

    @Property(bool, notify=stateChanged)
    def conversationDeleteRunning(self) -> bool:  # noqa: N802
        return self._conversation_delete_running

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


    @Property("QVariantList", notify=stateChanged)
    def applicationsCatalog(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._applications_catalog]

    @Property(str, notify=stateChanged)
    def applicationsCatalogError(self) -> str:  # noqa: N802
        return self._apps_catalog_error

    @Property("QVariantList", notify=stateChanged)
    def appVariants(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._app_variants]

    @Property(str, notify=stateChanged)
    def selectedAppOriginId(self) -> str:  # noqa: N802
        return self._selected_app_origin_id

    @Slot(str)
    def selectAppOrigin(self, package_id: str) -> None:  # noqa: N802
        self._app_comparison_generation += 1
        self._app_sources = {}
        origins = self._selected_version_details.get("origin_packages", [])
        self._selected_app_origin_id = package_id if any(o["package_id"] == package_id for o in origins) else ""
        self._CodeAdmin_domain._activate_selected_processing_scope()
        self.stateChanged.emit()

    @Slot(object)
    def _on_applications_loaded(self, result: object) -> None:
        self._CodeAdmin_domain._on_applications_loaded(result)

    @Slot(object)
    def _on_app_comparison_loaded(self, result: object) -> None:
        self._CodeAdmin_domain._on_app_comparison_loaded(result)

    @Slot(str, result="QVariantList")
    def variantsForVersion(self, version: str) -> list[dict[str, Any]]:  # noqa: N802
        return list(self._apps_catalog_data.get("data", {}).get("applications", {}).get(
            self._selected_app_id, {}).get("versions", {}).get(version, {}).get("variants", {}).values())

    @Property(str, notify=stateChanged)
    def selectedAppId(self) -> str:  # noqa: N802
        return self._selected_app_id

    @Property("QVariantList", notify=stateChanged)
    def appVersions(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._app_versions]

    @Property(str, notify=stateChanged)
    def selectedAppVersion(self) -> str:  # noqa: N802
        return self._selected_app_version

    @Property(str, notify=stateChanged)
    def selectedAppVariantId(self) -> str:  # noqa: N802
        return self._selected_app_variant_id

    @Property("QVariantMap", notify=stateChanged)
    def applicationSources(self) -> dict[str, Any]:  # noqa: N802
        return self._app_sources

    @Slot(str, int, str, result=bool)
    def loadApplicationSources(self, query: str, offset: int, source_key: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.loadApplicationSources(query, offset, source_key)

    @Slot(object)
    def _on_app_sources_loaded(self, payload: object) -> None:
        self._app_sources_thread = None
        generation, workspace, result = payload
        if not self._closed and workspace == self._settings.root and generation == self._app_comparison_generation:
            if "body" in result:
                self._app_sources.update(result)
            else:
                self._app_sources = result
            self.stateChanged.emit()

    @Property("QVariantMap", notify=stateChanged)
    def applicationImportPreview(self) -> dict[str, Any]:  # noqa: N802
        return self._application_import_preview

    @Slot(str, bool, str, result=bool)
    def previewApplicationImport(self, source: str, single: bool, release_id: str = "") -> bool:  # noqa: N802
        return self._CodeAdmin_domain.previewApplicationImport(source, single, release_id)

    @Slot(str, result=bool)
    def previewConfiguredImport(self, release_id: str) -> bool:  # noqa: N802
        single = self._code_analysis_snapshot_scope == ERP_JAR_SCOPE_SINGLE
        source = self._code_analysis_single_jar_path if single else self.codeAnalysisJarSourcePath
        return self.previewApplicationImport(source, single, release_id)

    @Slot(result=bool)
    def confirmApplicationImport(self) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.confirmApplicationImport()

    @Slot()
    def cancelApplicationImport(self) -> None:  # noqa: N802
        self._application_preview_generation += 1
        self._application_import_preview = {}
        self.stateChanged.emit()

    @Slot(str, str, str, str, result=bool)
    def overrideVariantVersion(self, app_id: str, version: str, variant_id: str, manual_version: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.overrideVersion(app_id, version, manual_version, variant_id=variant_id)

    @Property("QVariantList", notify=stateChanged)
    def ultraApplicationContexts(self) -> list[dict[str, Any]]:  # noqa: N802
        return self._CodeAdmin_domain.application_context_items()

    @Property(bool, notify=stateChanged)
    def ultraApplicationContextsReady(self) -> bool:  # noqa: N802
        items = self.ultraApplicationContexts
        return bool(items) and all(item["ready"] for item in items)

    @Slot(result=bool)
    def addSelectedApplicationContext(self) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.addSelectedApplicationContext()

    @Slot(str)
    def removeApplicationContext(self, app_id: str) -> None:  # noqa: N802
        self._CodeAdmin_domain.removeApplicationContext(app_id)

    @Property("QVariantMap", notify=stateChanged)
    def selectedVersionDetails(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._selected_version_details)

    @Property("QVariantMap", notify=stateChanged)
    def versionComparisonResult(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._version_comparison_result)

    @Property("QVariantList", notify=stateChanged)
    def packagesCatalog(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._packages_catalog]

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
        return self._code_processing_running

    @Property(bool, notify=stateChanged)
    def codeProcessingPauseRequested(self) -> bool:  # noqa: N802
        return self._code_processing_pause_requested

    @Property(bool, notify=stateChanged)
    def codeProcessingCancelRequested(self) -> bool:  # noqa: N802
        return self._code_processing_cancel_requested

    @Property(bool, notify=stateChanged)
    def codeProcessingCanCancel(self) -> bool:  # noqa: N802
        return self._code_processing_can_cancel

    @Property(bool, notify=stateChanged)
    def codeProcessingStatusLoading(self) -> bool:  # noqa: N802
        return self._code_processing_status_loading

    @Property(str, notify=stateChanged)
    def codeProcessingStatus(self) -> str:  # noqa: N802
        return self._code_processing_status

    @Property(float, notify=stateChanged)
    def codeProcessingProgress(self) -> float:  # noqa: N802
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
            {
                "label": (
                    f"{value} núcleo(s) · Turbo"
                    if value >= 4
                    else f"{value} núcleo(s)"
                ),
                "value": value,
            }
            for value in CODE_PROCESSING_CPU_CORE_OPTIONS
        ]

    @Property(int, notify=stateChanged)
    def codeProcessingMaxCpuCores(self) -> int:  # noqa: N802
        return self._code_processing_max_cpu_cores

    @Property(str, notify=stateChanged)
    def codeProcessingHardwareSummary(self) -> str:  # noqa: N802
        workers = self.codeProcessingParallelWorkers
        return (
            CODE_PROCESSING_HARDWARE.summary
            + f" Configuração atual: {workers} processos paralelos."
        )

    @Property(int, notify=stateChanged)
    def codeProcessingParallelWorkers(self) -> int:  # noqa: N802
        return CODE_PROCESSING_HARDWARE.parallel_workers_for(
            self._code_processing_max_cpu_cores,
            self._code_processing_max_heap_mb,
        )

    @Property(int, notify=stateChanged)
    def codeProcessingCpuCoresPerWorker(self) -> int:  # noqa: N802
        return max(
            1,
            self._code_processing_max_cpu_cores
            // self.codeProcessingParallelWorkers,
        )

    @Property("QVariantList", notify=stateChanged)
    def codeProcessingDiskMultiplierOptions(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {"label": f"Até {value}x", "value": value}
            for value in CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS
        ]

    @Property(int, notify=stateChanged)
    def codeProcessingDiskMultiplier(self) -> int:  # noqa: N802
        return self._code_processing_disk_multiplier

    @Property("QVariantMap", notify=stateChanged)
    def codeProcessingCapacity(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._code_processing_capacity)

    @Property(str, notify=stateChanged)
    def codeProcessingCapacitySummary(self) -> str:  # noqa: N802
        capacity = self._code_processing_capacity
        if not capacity:
            return ""
        used = self._format_megabytes(int(capacity.get("used_bytes") or 0))
        budget = self._format_megabytes(int(capacity.get("budget_bytes") or 0))
        physical = self._format_megabytes(
            int(capacity.get("physical_used_bytes") or 0)
        )
        orphaned = self._format_megabytes(
            int(capacity.get("orphaned_bytes") or 0)
        )
        free = self._format_megabytes(int(capacity.get("free_disk_bytes") or 0))
        return (
            f"Dados ativos: {used} de {budget} · ocupação física: {physical} · "
            f"órfãos removíveis: {orphaned} · disco livre: {free}"
        )

    @Property(bool, notify=stateChanged)
    def codeProcessingCanCleanOrphans(self) -> bool:  # noqa: N802
        return bool(
            int(self._code_processing_capacity.get("orphaned_item_count") or 0) > 0
            and not self._code_processing_capacity.get("orphan_scan_errors")
        )

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

    @Property(str, notify=stateChanged)
    def provider(self) -> str:
        return self._provider

    @Property(bool, notify=stateChanged)
    def supportsReasoning(self) -> bool:  # noqa: N802
        return self._provider != "antigravity" and bool(
            self.effortItems or self.serviceTierItems
        )

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
        default_index = values.index("full_access") if "full_access" in values else 3
        return values.index(self._approval_profile) if self._approval_profile in values else default_index

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
        return self._ProviderSettings_domain._provider_context_window()

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
    def taskSteps(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._task_plan.steps]

    @Property(bool, notify=stateChanged)
    def taskPlanVisible(self) -> bool:  # noqa: N802
        return self.turnRunning and self._task_plan_current and any(
            step["state"] != "completed" for step in self._task_plan.steps
        )

    @Property("QVariantList", notify=stateChanged)
    def activityItems(self) -> list[dict[str, str]]:  # noqa: N802
        return [dict(item) for item in self._activity_items]

    @Property("QVariantList", notify=stateChanged)
    def traceItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._trace_items]

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
        self._release_coverage_stop.set()
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
        self._code_processing_cancel_event.set()
        processing_thread = self._code_processing_thread
        if processing_thread is not None and processing_thread.is_alive():
            processing_thread.join(timeout=2.0)
        self._cancel_code_processing_status_refresh()
        with self._code_processing_status_threads_lock:
            status_threads = list(self._code_processing_status_threads)
        for thread in status_threads:
            thread.join(timeout=1.0)
        if self._release_coverage_thread is not None:
            self._release_coverage_thread.join(timeout=1.0)
        if self._apps_catalog_thread is not None:
            self._apps_catalog_thread.join(timeout=1.0)
        if self._app_comparison_thread is not None:
            self._app_comparison_thread.join(timeout=1.0)
        if self._app_sources_thread is not None:
            self._app_sources_thread.join(timeout=1.0)
        if self._application_preview_thread is not None:
            self._application_preview_thread.join(timeout=1.0)
        if self._package_operation_thread is not None:
            self._package_operation_thread.join(timeout=2.0)
        self._orchestrator.close()
        self._active_turns.clear()
        self._sync_selected_turn_state()

    def _selected_conversation_id(self) -> str:
        return self._Conversations_domain._selected_conversation_id()

    def _sync_selected_turn_state(self) -> None:
        """Keep private compatibility fields scoped to the selected conversation."""

        conversation_id = self._selected_conversation_id()
        running = bool(conversation_id and conversation_id in self._active_turns)
        self._turn_running = running
        self._running_conversation_id = conversation_id if running else ""

    def _enabled_provider_names(self) -> list[str]:
        return self._ProviderSettings_domain._enabled_provider_names()

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
        return self._ProviderSettings_domain._current_model_item()

    def _supported_efforts_for_current_model(self) -> list[str]:
        return self._ProviderSettings_domain._supported_efforts_for_current_model()

    def _model_effort_preferences(self) -> dict[str, str]:
        return self._ProviderSettings_domain._model_effort_preferences()

    def _model_effort_key(self) -> str:
        return self._ProviderSettings_domain._model_effort_key()

    def _remember_model_effort(self, effort: str) -> None:
        return self._ProviderSettings_domain._remember_model_effort(effort)

    def _restore_effort_for_current_model(self) -> None:
        return self._ProviderSettings_domain._restore_effort_for_current_model()

    def _load_cached_model_catalog(self) -> list[dict[str, Any]]:
        return self._ProviderSettings_domain._load_cached_model_catalog()

    def _save_cached_model_catalog(self, items: list[dict[str, Any]]) -> None:
        return self._ProviderSettings_domain._save_cached_model_catalog(items)

    def _reset_model_items(self) -> None:
        return self._ProviderSettings_domain._reset_model_items()

    @Slot()
    def refreshModels(self) -> None:  # noqa: N802
        return self._ProviderSettings_domain.refreshModels()

    @Slot()
    def _poll_model_catalog(self) -> None:
        return self._ProviderSettings_domain._poll_model_catalog()

    @Slot(object)
    def _apply_model_catalog(self, values: object, is_final: bool = True) -> None:
        return self._ProviderSettings_domain._apply_model_catalog(values, is_final)

    @Slot(int)
    def setModel(self, index: int) -> None:  # noqa: N802
        return self._ProviderSettings_domain.setModel(index)

    @Slot(int)
    def toggleModelFavorite(self, index: int) -> None:  # noqa: N802
        return self._ProviderSettings_domain.toggleModelFavorite(index)

    def _load_favorite_model_keys(self) -> set[str]:
        return self._ProviderSettings_domain._load_favorite_model_keys()

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

    @Slot(result=bool)
    def pasteClipboardAttachment(self) -> bool:  # noqa: N802
        """Stage clipboard images/files; leave ordinary text to the editor."""
        if self.turnRunning:
            return False
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is None:
            return False
        if mime.hasImage():
            image = clipboard.image()
            if image.isNull():
                return False
            folder = self._settings.state_dir / "clipboard-attachments"
            try:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"imagem-{uuid4().hex}.png"
                if not image.save(str(path), "PNG"):
                    raise OSError("Não foi possível salvar a imagem colada.")
                return bool(self._stage_attachment_paths([str(path)]))
            except OSError as exc:
                self._status_text = str(exc)
                self.stateChanged.emit()
                return False
        if mime.hasUrls():
            return bool(self._stage_attachment_paths(mime.urls()))
        return False

    @Slot(str, result=str)
    def attachmentSizeLabel(self, path: str) -> str:  # noqa: N802
        try:
            p = Path(path).expanduser().resolve(strict=False)
            if p.is_file():
                size_bytes = p.stat().st_size
                if size_bytes < 1024:
                    return f"{size_bytes} B"
                if size_bytes < 1024 * 1024:
                    return f"{max(1, round(size_bytes / 1024))} KB"
                return f"{size_bytes / (1024 * 1024):.1f} MB"
        except Exception:
            pass
        return ""

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
        return self._ProviderSettings_domain.refreshExtensions()

    @Slot()
    def _poll_extension_catalog(self) -> None:
        return self._ProviderSettings_domain._poll_extension_catalog()

    @Slot(object)
    def _apply_extension_catalog(self, values: object) -> None:
        return self._ProviderSettings_domain._apply_extension_catalog(values)

    @Slot(int, bool)
    def toggleExtension(self, index: int, selected: bool) -> None:  # noqa: N802
        return self._ProviderSettings_domain.toggleExtension(index, selected)

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
            conversation_id = str(row["id"])
            if conversation_id in self._deleting_conversation_ids:
                continue
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
            vr_mode = self._normalize_vr_mode(row["vr_mode"]) or (
                "vr" if bool(row["vr_enabled"]) else "off"
            )
            if editing and conversation_id == selected_id:
                vr_mode = self._vr_mode
            vr_enabled = vr_mode != "off"
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
                    "vrMode": vr_mode,
                    "vrEnabled": vr_enabled,
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
        return self._Conversations_domain.setProject(index)

    @Slot(int, str, result=bool)
    def renameProject(self, index: int, name: str) -> bool:  # noqa: N802
        return self._Conversations_domain.renameProject(index, name)

    @Slot(int, result=bool)
    def openProjectFolder(self, index: int) -> bool:  # noqa: N802
        return self._Conversations_domain.openProjectFolder(index)

    @Slot(int)
    def copyProjectPath(self, index: int) -> None:  # noqa: N802
        return self._Conversations_domain.copyProjectPath(index)

    @Slot(int, result=str)
    def chooseProjectIcon(self, index: int) -> str:  # noqa: N802
        return self._Conversations_domain.chooseProjectIcon(index)

    @Slot(int, result=bool)
    def removeProject(self, index: int) -> bool:  # noqa: N802
        return self._Conversations_domain.removeProject(index)

    def _load_draft_records(self) -> dict[str, dict[str, Any]]:
        return self._Conversations_domain._load_draft_records()

    def _persist_draft_records(self) -> None:
        return self._Conversations_domain._persist_draft_records()

    def _load_pinned_conversation_ids(self) -> set[str]:
        return self._Conversations_domain._load_pinned_conversation_ids()

    def _persist_pinned_conversation_ids(self) -> None:
        return self._Conversations_domain._persist_pinned_conversation_ids()

    @Slot(str, result=bool)
    def saveCurrentDraft(self, text: str) -> bool:  # noqa: N802
        return self._Conversations_domain.saveCurrentDraft(text)

    @Slot(result=bool)
    @Slot(str, result=bool)
    def discardDraft(self, conversation_id: str = "") -> bool:  # noqa: N802
        return self._Conversations_domain.discardDraft(conversation_id)

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
            self._preferences.value("chat/last_approval_profile", "full_access") or "full_access"
        )
        if self._approval_profile in ("auto", "auto_edits", ""):
            self._approval_profile = "full_access"
        self._vr_mode = self._normalize_vr_mode(
            self._preferences.value("chat/vr_mode", "")
        ) or (
            "vr"
            if self._stored_bool(
                self._preferences.value("chat/vr_flow_enabled", True), True
            )
            else "off"
        )
        self._application_preview_generation += 1
        self._application_import_preview = {}
        self._apps_catalog_data = {}
        self._applications_catalog = []
        self._packages_catalog = []
        self._app_sources = {}
        self._app_comparison_generation += 1
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
        self._task_plan = TaskPlan()
        self._task_plan_current = False
        self._activity_items = []
        self._reset_trace_state()
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
        return self._Conversations_domain.copyMessage(index)

    @Slot()
    def copyConversation(self) -> None:  # noqa: N802
        return self._Conversations_domain.copyConversation()

    @Slot(int)
    def selectConversation(self, index: int) -> None:  # noqa: N802
        return self._Conversations_domain.selectConversation(index)

    @Slot(str)
    def selectConversationId(self, conversation_id: str) -> None:  # noqa: N802
        return self._Conversations_domain.selectConversationId(conversation_id)

    @Slot(int)
    def setEffort(self, index: int) -> None:  # noqa: N802
        return self._ProviderSettings_domain.setEffort(index)

    @Slot(int)
    def setServiceTier(self, index: int) -> None:  # noqa: N802
        return self._ProviderSettings_domain.setServiceTier(index)

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
            self.refresh()
        self.stateChanged.emit()

    def _load_research_config(self) -> None:
        return self._ProviderSettings_domain._load_research_config()

    def _apply_research_config(self) -> None:
        return self._ProviderSettings_domain._apply_research_config()

    @Slot("QVariantList")
    def setResearchModels(self, keys: list) -> None:  # noqa: N802
        return self._ProviderSettings_domain.setResearchModels(keys)

    @Slot(int)
    def setResearchMaxParallel(self, value: int) -> None:  # noqa: N802
        return self._ProviderSettings_domain.setResearchMaxParallel(value)

    @Slot(bool)
    def setCodeAnalysisEnabled(self, enabled: bool) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeAnalysisEnabled(enabled)

    @Slot(str)
    def setCodeAnalysisRelease(self, release_id: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeAnalysisRelease(release_id)

    @Slot(str)
    def setCodeAnalysisJarSource(self, source: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeAnalysisJarSource(source)

    @Slot(str)
    def setCodeAnalysisSnapshotScope(self, scope: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeAnalysisSnapshotScope(scope)

    @Slot(str, result=bool)
    def setCodeAnalysisSingleJarPath(self, value: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.setCodeAnalysisSingleJarPath(value)

    @Slot(result=str)
    def selectCodeAnalysisSingleJar(self) -> str:  # noqa: N802
        return self._CodeAdmin_domain.selectCodeAnalysisSingleJar()

    @Slot(int)
    def setCodeProcessingMaxHeapMb(self, value: int) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeProcessingMaxHeapMb(value)

    @Slot(int)
    def setCodeProcessingTimeoutSeconds(self, value: int) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeProcessingTimeoutSeconds(value)

    @Slot(int)
    def setCodeProcessingMaxCpuCores(self, value: int) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeProcessingMaxCpuCores(value)

    @Slot(int)
    def setCodeProcessingDiskMultiplier(self, value: int) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeProcessingDiskMultiplier(value)

    @Slot(str)
    def setCodeProcessingWindow(self, value: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeProcessingWindow(value)

    @Slot(str)
    def setCodeProcessingRetryBatch(self, batch_id: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.setCodeProcessingRetryBatch(batch_id)

    def _selected_code_analysis_release_item(self) -> dict[str, Any]:
        return self._CodeAdmin_domain._selected_code_analysis_release_item()

    @Slot()
    def refreshCodeProcessingStatus(self) -> None:  # noqa: N802
        return self._CodeAdmin_domain.refreshCodeProcessingStatus()

    def _cancel_code_processing_status_refresh(self) -> None:
        return self._CodeAdmin_domain._cancel_code_processing_status_refresh()

    @Slot()
    def _poll_code_processing_status(self) -> None:
        return self._CodeAdmin_domain._poll_code_processing_status()

    def _reset_code_processing_status(self, message: str) -> None:
        return self._CodeAdmin_domain._reset_code_processing_status(message)

    @staticmethod
    def _format_megabytes(value: int) -> str:
        return f"{max(0, int(value)) / (1024 * 1024):.1f} MB"

    @staticmethod
    def _format_duration_ms(value: int) -> str:
        total_seconds = max(0, int(value)) // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"

    def _apply_code_processing_coverage(self, coverage: dict[str, Any]) -> None:
        return self._CodeAdmin_domain._apply_code_processing_coverage(coverage)

    def _restore_code_processing_audit(
        self,
        audit_event: dict[str, Any] | None,
        coverage: dict[str, Any],
    ) -> None:
        return self._CodeAdmin_domain._restore_code_processing_audit(audit_event, coverage)

    @Slot(result=bool)
    def startCodeProcessing(self) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.startCodeProcessing()

    @Slot(result=bool)
    def retryCodeProcessing(self) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.retryCodeProcessing()

    def _start_code_processing(self, *, retry_batch_id: str) -> bool:
        return self._CodeAdmin_domain._start_code_processing(retry_batch_id=retry_batch_id)

    @Slot()
    def pauseCodeProcessing(self) -> None:  # noqa: N802
        return self._CodeAdmin_domain.pauseCodeProcessing()

    @Slot()
    def cancelCodeProcessing(self) -> None:  # noqa: N802
        return self._CodeAdmin_domain.cancelCodeProcessing()

    def _run_code_processing(
        self,
        release_id: str,
        manifest_hash: str,
        retry_batch_id: str,
        max_heap_mb: int,
        timeout_seconds: int,
        max_cpu_cores: int,
        parallel_workers: int,
        process_priority: str,
        disk_multiplier: int,
        processing_window: str,
    ) -> None:
        return self._CodeAdmin_domain._run_code_processing(release_id, manifest_hash, retry_batch_id, max_heap_mb, timeout_seconds, max_cpu_cores, parallel_workers, process_priority, disk_multiplier, processing_window)

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
        return CodeAdminDomain._record_code_processing_coverage(audit, event, run_id, release_id, manifest_hash, coverage, telemetry)

    @staticmethod
    def _merge_code_processing_telemetry(
        aggregate: dict[str, Any],
        executions: list[dict[str, Any]],
        started_monotonic: float,
    ) -> dict[str, Any]:
        return CodeAdminDomain._merge_code_processing_telemetry(aggregate, executions, started_monotonic)

    @staticmethod
    def _require_frozen_code_manifest(
        coverage: dict[str, Any], manifest_hash: str
    ) -> None:
        return CodeAdminDomain._require_frozen_code_manifest(coverage, manifest_hash)

    @Slot()
    def _poll_code_processing(self) -> None:
        return self._CodeAdmin_domain._poll_code_processing()

    @Slot(str, result=bool)
    def snapshotCodeAnalysisRelease(self, release_id: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.snapshotCodeAnalysisRelease(release_id)

    @Slot(str, result=bool)
    def removeCodeAnalysisRelease(self, release_id: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.removeCodeAnalysisRelease(release_id)

    @Slot(result=bool)
    def cleanCodeProcessingOrphans(self) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.cleanCodeProcessingOrphans()

    @Slot()
    def _poll_release_snapshot(self) -> None:
        return self._CodeAdmin_domain._poll_release_snapshot()

    def _workspace_research_preference(self, name: str) -> str:
        return self._ProviderSettings_domain._workspace_research_preference(name)

    def _refresh_code_analysis_jar_sources(self) -> None:
        return self._CodeAdmin_domain._refresh_code_analysis_jar_sources()

    @Slot(object)
    def _on_coverage_warmed(self, result: object) -> None:
        return self._CodeAdmin_domain._on_coverage_warmed(result)

    def _refresh_code_analysis_releases(self, *, include_coverage: bool = True) -> None:
        return self._CodeAdmin_domain._refresh_code_analysis_releases(include_coverage=include_coverage)

    @Slot()
    def refreshCodeAnalysisReleases(self) -> None:  # noqa: N802
        return self._CodeAdmin_domain.refreshCodeAnalysisReleases()

    @Slot(str)
    def selectApplication(self, app_id: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.selectApplication(app_id)

    @Slot(str)
    def selectAppVersion(self, version: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.selectAppVersion(version)

    @Slot(str)
    def selectAppVariant(self, variant_id: str) -> None:  # noqa: N802
        return self._CodeAdmin_domain.selectAppVariant(variant_id)

    @Slot(str, result=bool)
    def importPackage(self, source_path: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.importPackage(source_path)

    @Slot(str, result=bool)
    def importSingleJar(self, jar_path: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.importSingleJar(jar_path)

    @Slot(result=str)
    def selectAndImportPackage(self) -> str:  # noqa: N802
        return self._CodeAdmin_domain.selectAndImportPackage()

    @Slot(result=str)
    def selectAndImportSingleJar(self) -> str:  # noqa: N802
        return self._CodeAdmin_domain.selectAndImportSingleJar()

    @Slot(result=str)
    def selectCustomJarDirectory(self) -> str:  # noqa: N802
        return self._CodeAdmin_domain.selectCustomJarDirectory()

    @Slot(str, str, result=bool)
    def renamePackage(self, package_id: str, new_name: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.renamePackage(package_id, new_name)

    @Slot(str, result="QVariantMap")
    def deleteSourceJars(self, package_id: str) -> dict[str, Any]:  # noqa: N802
        return self._CodeAdmin_domain.deleteSourceJars(package_id)

    @Slot(result="QVariantMap")
    @Slot(str, result="QVariantMap")
    def detectDecompiledDirectory(self, directory: str = "") -> dict[str, Any]:  # noqa: N802
        return self._CodeAdmin_domain.detectDecompiledDirectory(directory)

    @Slot(str, str, str, result="QVariantMap")
    @Slot(str, result="QVariantMap")
    def importDecompiledDirectory(self, source_dir: str, release_id: str = "", package_name: str = "") -> dict[str, Any]:  # noqa: N802
        return self._CodeAdmin_domain.importDecompiledDirectory(source_dir, release_id, package_name)

    @Slot(str, result=bool)
    @Slot(str, bool, result=bool)
    def unlinkPackage(self, package_id: str, delete_data: bool = False) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.unlinkPackage(package_id, delete_data)

    @Slot(str, str, str, result=bool)
    def overrideVersion(self, app_id: str, current_version: str, manual_version: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.overrideVersion(app_id, current_version, manual_version)

    @Slot(str, str, str, result="QVariantMap")
    @Slot(str, str, str, str, str, result="QVariantMap")
    def compareAppVersions(self, app_id: str, base_version: str, target_version: str, base_variant_id: str = "", target_variant_id: str = "") -> dict[str, Any]:  # noqa: N802
        return self._CodeAdmin_domain.compareAppVersions(app_id, base_version, target_version, base_variant_id, target_variant_id)

    @Slot()
    def refreshApplicationsCatalog(self) -> None:  # noqa: N802
        return self._CodeAdmin_domain.refreshApplicationsCatalog()

    @Slot(str, str, str, result=bool)
    def startVariantProcessing(self, app_id: str, version: str, variant_id: str) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.startVariantProcessing(app_id, version, variant_id)

    @Slot(list, result=bool)
    def startBatchAppsProcessing(self, app_ids: list[str]) -> bool:  # noqa: N802
        return self._CodeAdmin_domain.startBatchAppsProcessing(app_ids)


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
        return self._Conversations_domain.addProject()

    @Slot()
    def beginProjectFolderBrowse(self) -> None:  # noqa: N802
        return self._Conversations_domain.beginProjectFolderBrowse()

    @Slot(str)
    def browseProjectFolder(self, value: str) -> None:  # noqa: N802
        return self._Conversations_domain.browseProjectFolder(value)

    @Slot()
    def browseParentProjectFolder(self) -> None:  # noqa: N802
        return self._Conversations_domain.browseParentProjectFolder()

    @Slot(result=str)
    def addCurrentProjectFolder(self) -> str:  # noqa: N802
        return self._Conversations_domain.addCurrentProjectFolder()

    @Slot()
    def openCurrentProjectFolder(self) -> None:  # noqa: N802
        return self._Conversations_domain.openCurrentProjectFolder()

    def _set_project_folder(self, value: Path) -> None:
        return self._Conversations_domain._set_project_folder(value)

    def _add_project_path(self, selected: Path) -> str:
        return self._Conversations_domain._add_project_path(selected)

    def _stored_project_entries(self) -> list[dict[str, str]]:
        return self._Conversations_domain._stored_project_entries()

    def _stored_project_paths(self, key: str) -> list[Path]:
        return self._Conversations_domain._stored_project_paths(key)

    def _store_project_entries(self, values: list[dict[str, str]]) -> None:
        return self._Conversations_domain._store_project_entries(values)

    @Property("QVariantList", notify=activeSkillsChanged)
    def activeSkills(self) -> list[dict[str, Any]]:  # noqa: N802
        return list(self._active_skills)

    @Slot(dict)
    def addActiveSkill(self, skill: dict) -> None:  # noqa: N802
        if not skill:
            return
        skill_id = str(skill.get("id") or skill.get("name") or "")
        if any(str(s.get("id") or s.get("name") or "") == skill_id for s in self._active_skills):
            return
        self._active_skills.append(dict(skill))
        self.activeSkillsChanged.emit()

    @Slot(int)
    def removeActiveSkill(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self._active_skills):
            self._active_skills.pop(index)
            self.activeSkillsChanged.emit()

    @Slot()
    def clearActiveSkills(self) -> None:  # noqa: N802
        if self._active_skills:
            self._active_skills.clear()
            self.activeSkillsChanged.emit()

    @Property(bool, notify=showSkillsInSlashMenuChanged)
    def showSkillsInSlashMenu(self) -> bool:  # noqa: N802
        val = self._preferences.value("chat/show_skills_in_slash_menu", True)
        if isinstance(val, bool):
            return val
        return str(val).strip().casefold() in ("true", "1", "yes")

    @Slot(bool)
    def setShowSkillsInSlashMenu(self, value: bool) -> None:  # noqa: N802
        self._preferences.setValue("chat/show_skills_in_slash_menu", bool(value))
        self.showSkillsInSlashMenuChanged.emit()

    @Slot(str, result="QVariantList")
    def skillSuggestions(self, query: str) -> list[dict[str, Any]]:  # noqa: N802
        workspace = (self._project_scope or self._settings.root).resolve(strict=False)
        try:
            return self._orchestrator.search_skills(
                query, provider=self._provider, workspace=workspace
            )
        except Exception as exc:
            LOGGER.warning("Erro em skillSuggestions: %s", exc)
            return []

    @Slot(result="QVariantList")
    def allSkills(self) -> list[dict[str, Any]]:  # noqa: N802
        workspace = (self._project_scope or self._settings.root).resolve(strict=False)
        try:
            res = self._orchestrator.skills(self._provider, workspace)
            return res.get("skills", [])
        except Exception as exc:
            LOGGER.warning("Erro em allSkills: %s", exc)
            return []

    @Slot(str, str, str, str, str, result="QVariantMap")
    def createSkill(
        self,
        provider: str,
        name: str,
        description: str,
        instructions: str,
        scope: str = "project",
    ) -> dict[str, Any]:  # noqa: N802
        workspace = (self._project_scope or self._settings.root).resolve(strict=False)
        try:
            skill = self._orchestrator.create_skill(
                provider=provider or self._provider,
                name=name,
                description=description,
                instructions=instructions,
                workspace=workspace,
                scope=scope,
            )
            return {"success": True, "skill": skill}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @Slot(str, str, str, result="QVariantMap")
    def updateSkill(
        self,
        skill_id: str,
        instructions: str = "",
        description: str = "",
    ) -> dict[str, Any]:  # noqa: N802
        try:
            skill = self._orchestrator.update_skill(
                skill_id=skill_id,
                instructions=instructions if instructions else None,
                description=description if description else None,
            )
            return {"success": True, "skill": skill}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @Property("QVariantMap", notify=usageLimitsChanged)
    def usageSnapshot(self) -> dict[str, Any]:  # noqa: N802
        if not self._usage_snapshot:
            self.refreshUsageLimits(force=False)
        return dict(self._usage_snapshot)

    @Slot()
    @Slot(bool)
    def refreshUsageLimits(self, force: bool = True) -> None:  # noqa: N802
        provider_name = self._provider
        def worker():
            try:
                snap = self._orchestrator.usage_limits(provider_name, force_refresh=force)
                self._usage_snapshot = snap
                self.usageLimitsChanged.emit()
            except Exception as exc:
                LOGGER.warning("Erro em refreshUsageLimits: %s", exc)
        threading.Thread(target=worker, daemon=True, name=f"usage-refresh-{provider_name}").start()

    @Slot()
    def openUsageLimits(self) -> None:  # noqa: N802
        self.refreshUsageLimits(force=True)
        self.showUsageLimitsRequested.emit()

    @Slot(str)
    def sendMessage(self, text: str) -> None:  # noqa: N802
        self._send_message(text)

    @Property("QVariantMap", notify=stateChanged)
    def resumableResearch(self) -> dict:  # noqa: N802
        return {}

    @Property(QObject, constant=True)
    def retrievalSettings(self):  # noqa: N802
        return self._retrieval_settings

    @Slot(bool)
    def resumeResearch(self, grant_budget: bool = False) -> None:  # noqa: N802
        return None

    def _send_message(self, text: str, *, resume_run_id: str = "", grant_budget: bool = False) -> None:
        content = str(text or "").strip()
        if content.lower() == "/usage-limits" or content.lower().startswith("/usage-limits "):
            self.openUsageLimits()
            return
        if self.turnRunning or (not content and not self._attachments):
            return
        if not content:
            content = "Analise os anexos enviados."
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
        active_chips = list(self._active_skills)
        known_skill_keys = {
            str(s.get("id") or s.get("name") or "") for s in skills
        }
        for chip in active_chips:
            k = str(chip.get("id") or chip.get("name") or "")
            if k and k not in known_skill_keys:
                skills.append(dict(chip))
                known_skill_keys.add(k)
        if self._active_skills:
            self._active_skills.clear()
            self.activeSkillsChanged.emit()
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
        elif mcp_tools and not resume_run_id:
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
        self._task_plan_current = False
        self._activity_items = []
        self._reset_trace_state()
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
                "skills": [dict(s) for s in skills],
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
                image_paths=[] if resume_run_id else image_paths,
                vr_mode=self._vr_mode,
                force_research=force_research,
                code_analysis_enabled=(
                    self._code_analysis_enabled
                    and bool(self._ultra_application_contexts)
                ),
                application_contexts=json.loads(json.dumps(self._ultra_application_contexts)),
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
                **({"resume_run_id": resume_run_id, "grant_budget": grant_budget} if resume_run_id else {}),
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
        return self._Conversations_domain.archiveCurrentConversation()

    @Slot()
    def trashCurrentConversation(self) -> None:  # noqa: N802
        return self._Conversations_domain.trashCurrentConversation()

    @Slot(object)
    def _finish_conversation_trash(self, value: object) -> None:
        return self._Conversations_domain._finish_conversation_trash(value)

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
        self._pending_approvals = [r for r in self._pending_approvals if not (
            str(r.get("request_id") or "") == request_id
            and r.get("conversation_id") == conversation_id
            and r.get("_dynamic") == request.get("_dynamic")
        )]
        if conversation_id == self._selected_conversation_id():
            self._status_text = "Aprovado" if approved else "Negado"
        self._Activity_domain._show_next_approval()
        self.stateChanged.emit()

    @Slot(object)
    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        return self._Activity_domain._on_runtime_event(event)

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
        return self._Activity_domain._on_background_runtime_event(event)

    def _finish_background_turn(self, conversation_id: str) -> None:
        self._active_turns.discard(str(conversation_id or ""))
        self._active_turn_started_epochs.pop(str(conversation_id or ""), None)
        self._sync_selected_turn_state()
        self.stateChanged.emit()
        self.refresh()

    def _ensure_streaming_message(self) -> None:
        return self._Activity_domain._ensure_streaming_message()

    def _reset_stream_state(self) -> None:
        return self._Activity_domain._reset_stream_state()

    def _reset_trace_state(self) -> None:
        return self._Activity_domain._reset_trace_state()

    def _schedule_state_update(self) -> None:
        if not self._state_update_timer.isActive():
            self._state_update_timer.start()

    def _tick_activity_clock(self) -> None:
        return self._Activity_domain._tick_activity_clock()

    @Slot()
    def _flush_stream_step(self) -> None:
        return self._Activity_domain._flush_stream_step()

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
                if kind in {"error", "orchestration_cancelled"}:
                    if step.get("state") == "running":
                        step["state"] = "error" if kind == "error" else "cancelled"
                else:
                    step["state"] = "completed"
        terminal_state = (
            "error"
            if kind == "error"
            else "cancelled" if kind == "orchestration_cancelled" else "completed"
        )
        for item in self._activity_items:
            if item.get("state") == "running":
                item["state"] = terminal_state
        for item in self._trace_items:
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
        return ActivityDomain._default_activity_steps()

    def _advance_default_activity(self) -> None:
        return self._Activity_domain._advance_default_activity()

    def _restore_activity_from_history(self, conversation_id: str) -> None:
        return self._Activity_domain._restore_activity_from_history(conversation_id)

    def _next_trace_id(self, prefix: str) -> str:
        return self._Activity_domain._next_trace_id(prefix)

    @staticmethod
    def _trace_payload_item(payload: dict[str, Any]) -> dict[str, Any]:
        return ActivityDomain._trace_payload_item(payload)

    def _record_trace_text_delta(
        self, event: RuntimeEvent, *, item_type: str
    ) -> None:
        return self._Activity_domain._record_trace_text_delta(event, item_type=item_type)

    @staticmethod
    def _diff_line_counts(diff: str) -> tuple[int, int]:
        additions = 0
        deletions = 0
        for line in str(diff or "").splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1
        return additions, deletions

    def _trace_display_path(self, raw_path: str) -> str:
        return self._Activity_domain._trace_display_path(raw_path)

    @staticmethod
    def _trace_folder_summary(files: list[dict[str, Any]]) -> str:
        return ActivityDomain._trace_folder_summary(files)

    def _record_trace_file_changes(
        self,
        item: dict[str, Any],
        identifier: str,
        state: str,
    ) -> None:
        return self._Activity_domain._record_trace_file_changes(item, identifier, state)

    @staticmethod
    def _trace_action_label(item_type: str, count: int) -> str:
        return ActivityDomain._trace_action_label(item_type, count)

    def _record_trace_tool_item(
        self,
        item: dict[str, Any],
        identifier: str,
        lifecycle: str,
        state: str,
        detail: str,
    ) -> None:
        return self._Activity_domain._record_trace_tool_item(item, identifier, lifecycle, state, detail)

    def _record_trace_status_event(self, event: RuntimeEvent, message: str) -> None:
        return self._Activity_domain._record_trace_status_event(event, message)

    def _record_execution_event(
        self, event: RuntimeEvent, *, emit_state: bool = True
    ) -> None:
        """Adapt orchestration events into compact, QML-safe presentation state."""
        if event.kind == "turn_started":
            self._task_plan_current = False
        if event.kind == "task_plan_updated":
            steps = event.payload.get("steps")
            if isinstance(steps, list):
                self._task_plan.update(steps, event.created_at, str(event.payload.get("turnId") or event.payload.get("execution_id") or ""))
                self._task_plan_current = True
                if emit_state:
                    self.stateChanged.emit()
            return
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
            self._record_trace_status_event(event, message)
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
        self._record_trace_tool_item(
            item,
            identifier,
            lifecycle,
            state,
            detail,
        )
        existing = next(
            (
                candidate
                for candidate in reversed(self._activity_items)
                if identifier and candidate.get("id") == identifier
            ),
            None,
        )
        if existing is None:
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
        return self._Activity_domain._upsert_agent(payload, status, output=output, delta=delta)

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

    @staticmethod
    def _execution_activity(event: RuntimeEvent) -> dict[str, Any] | None:
        return ActivityDomain._execution_activity(event)

    @staticmethod
    def _extract_tool_entry(event: RuntimeEvent) -> dict[str, Any] | None:
        return ActivityDomain._extract_tool_entry(event)

    def _reload_execution_timeline(self, cid: str, rows: list[Any]) -> bool:
        """Replay semantic public events, retaining DB text and message identity.

        Runtime event PK supplies the shared order for messages and work. Old
        rows with no execution metadata retain the existing history path.
        """
        with self._database.connect() as connection:
            events = connection.execute("SELECT * FROM runtime_events WHERE conversation_id=? ORDER BY id", (cid,)).fetchall()
        groups: dict[int, dict[str, dict[str, Any]]] = {}
        persisted: dict[str, Any] = {}
        for row in rows:
            if row["execution_id"] and row["role"] == "assistant":
                persisted[f"{row['execution_id']}:{row['execution_ordinal']}"] = row
        terminal_ids: set[int] = set()
        assistant_counts: dict[int, int] = {}
        for record in events:
            payload = json.loads(record["payload_json"] or "{}")
            eid = int(payload.get("execution_id") or 0)
            if not eid:
                continue
            group = groups.setdefault(eid, {})
            self._ui_execution_ids[cid] = max(eid, self._ui_execution_ids.get(cid, 0))
            kind = record["kind"]
            key = str(payload.get("message_key") or "")
            if kind in {"turn_completed", "orchestration_cancelled", "error", "turn_recovered"}:
                terminal_ids.add(eid)
            if kind == "tool_event":
                payload["runtime_event_id"] = record["id"]
                tool_entry = ActivityDomain._extract_tool_entry(RuntimeEvent(cid, kind, record["text"], payload, record["created_at"]))
                if tool_entry:
                    count = assistant_counts.get(eid, 0)
                    act_key = f"activity:{eid}:{count}"
                    activity = next((r for r in group.values() if r.get("role") == "activity"
                                     and any(t.get("id") == tool_entry["id"] for t in r["activityData"])), None)
                    if activity is None:
                        activity = group.get(act_key)
                    if activity is None:
                        activity = {
                            "messageId": -2,
                            "role": "activity",
                            "content": "",
                            "displayContent": "",
                            "segments": [],
                            "createdAt": record["created_at"],
                            "responseMode": "activity",
                            "messageKey": act_key,
                            "isStreaming": False,
                            "activityData": [],
                        }
                        group[act_key] = activity
                    existing_tool = next((t for t in activity["activityData"] if t.get("id") == tool_entry["id"]), None)
                    if existing_tool is not None:
                        detail = existing_tool.get("detail", "")
                        existing_tool.update(tool_entry)
                        if not tool_entry.get("detail"):
                            existing_tool["detail"] = detail
                    else:
                        activity["activityData"].append(tool_entry)
            elif kind in {"assistant_started", "assistant_delta", "assistant_completed"} and key:
                if ":" in key:
                    try:
                        ordinal = int(key.split(":")[-1])
                        assistant_counts[eid] = max(assistant_counts.get(eid, 0), ordinal)
                    except ValueError:
                        pass
                item = group.setdefault(key, {"messageId": -1, "role": "assistant", "content": "", "displayContent": "", "segments": [], "createdAt": record["created_at"], "responseMode": "native", "messageKey": key, "isStreaming": True})
                if kind == "assistant_delta":
                    item["content"] += record["text"]
                elif kind == "assistant_completed":
                    item["content"] = str(payload.get("final_text") or item["content"])
                    item["isStreaming"] = False
                if key in persisted:
                    row = persisted[key]
                    item.update(content=row["content"], messageId=int(row["id"]), responseMode=row["response_mode"], isStreaming=False)
        if not groups and not persisted:
            return False
        for key, row in persisted.items():
            group = groups.setdefault(int(row["execution_id"]), {})
            group.setdefault(key, {"messageId": int(row["id"]), "role": "assistant", "content": row["content"], "displayContent": "", "segments": [], "createdAt": row["created_at"], "responseMode": row["response_mode"], "messageKey": key, "isStreaming": False})
        result = []
        conversation = self._database.get_conversation(cid)
        running = conversation is not None and conversation["status"] == "running"
        if not running:
            self._ui_terminal_executions.update((cid, eid) for eid in terminal_ids)
        for group_id, group in groups.items():
            for item in group.values():
                if group_id in terminal_ids or not running:
                    item["isStreaming"] = False
                    for activity in item.get("activityData", []):
                        if activity["state"] == "running":
                            activity["state"] = "interrupted" if conversation and conversation["status"] != "idle" else "completed"
                item["displayContent"] = markdown_for_display(item["content"])
                if item["role"] == "assistant":
                    item["segments"] = segments_for_display(item["content"])
        for row in rows:
            if row["role"] == "system" or row["execution_id"]:
                continue
            result.append({"messageId": int(row["id"]), "role": row["role"], "content": row["content"], "displayContent": markdown_for_display(row["content"]), "segments": segments_for_display(row["content"]) if row["role"] == "assistant" else [], "createdAt": row["created_at"], "responseMode": row["response_mode"], "messageKey": f"db:{row['id']}", "isStreaming": False})
            if row["role"] == "user":
                result.extend(groups.pop(int(row["id"]), {}).values())
        for group in groups.values():
            result.extend(group.values())
        self._streaming_text = self._displayed_streaming_text = self._stream_pending_text = ""
        self._current_message_key = ""
        self._message_streaming_texts.clear()
        self._message_displayed_texts.clear()
        self._message_pending_texts.clear()
        for item in result:
            if item["role"] == "assistant" and item["isStreaming"]:
                key = item["messageKey"]
                self._current_message_key = key
                self._message_streaming_texts[key] = item["content"]
                self._message_displayed_texts[key] = item["content"]
                self._streaming_text = self._displayed_streaming_text = item["content"]
        self._messages.replace(result)
        return True

    def _reload_selected_messages(self) -> None:
        return self._Conversations_domain._reload_selected_messages()

    @staticmethod
    def _activity_timeline_item() -> dict[str, Any]:
        return ActivityDomain._activity_timeline_item()

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
        self._task_plan = TaskPlan()
        self._task_plan_current = False
        self._selected_index = -1
        self._selected = {}
        self._sync_selected_turn_state()
        self._status_text = "Pronto"
        self._messages.replace([])
        if changed:
            self.selectionChanged.emit()
            self.stateChanged.emit()

    def _refresh_projects(self) -> None:
        return self._Conversations_domain._refresh_projects()

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

"""QML-facing view models for the non-chat Studio surfaces.

The module adapts existing database and service APIs.  Business rules remain in
the established Python backend; QML only renders state and requests actions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QProcess,
    QProcessEnvironment,
    QRunnable,
    QSettings,
    QThreadPool,
    QTimer,
    Qt,
    QUrl,
    Signal,
    Slot,
    Property,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from ..brand import ORGANIZATION_NAME, SETTINGS_APP_NAME
from ..config import MarySettings, save_vr_env
from ..db import MaryDatabase
from ..endoo_wiki import EndooWikiSync
from ..models import ReviewFilters
from ..provider_cli import INSTALLERS, INSTALL_DOCS, InstallCancelled, install_cli, resolve_cli, verify_cli
from ..antigravity import AntigravityAuthManager
from ..antigravity_acp import AcpClient, acp_environment, resolve_acp, has_saved_account
from ..movidesk import MovideskInteractiveLoginRequired, MovideskSync
from ..schema_sync import SchemaSync
from ..wiki import WikiSync
from ...settings import redact_sensitive_text


MODULES = ("Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar")
MAX_PROCESS_OUTPUT_CHARS = 200_000
MAX_LOG_LINES = 800
MAX_LOG_ENTRY_CHARS = 8_000
MAX_SYNC_LOG_LINES = 800
STATUS_LABELS = {
    "pending": "Pendente",
    "approved": "Aprovado",
    "deferred": "Adiado",
    "kept": "Mantido",
    "active": "Ativo",
    "inactive": "Inativo",
    "waiting": "Aguardando",
    "running": "Executando",
    "completed": "Concluído",
    "error": "Erro",
}


def _bounded_text(current: str, addition: str, limit: int = MAX_PROCESS_OUTPUT_CHARS) -> str:
    combined = str(current or "") + str(addition or "")
    if len(combined) <= limit:
        return combined
    marker = "[...saída anterior truncada...]\n"
    return marker + combined[-max(0, limit - len(marker)):]


class MappingListModel(QAbstractListModel):
    """Simple role-based list model shared by the QML data pages."""

    def __init__(self, roles: tuple[str, ...], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._roles = {
            Qt.UserRole + index + 1: role.encode("utf-8")
            for index, role in enumerate(roles)
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        role_name = self._roles.get(role)
        return (
            self._items[index.row()].get(role_name.decode("utf-8"))
            if role_name is not None
            else None
        )

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return self._roles

    def replace(self, items: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def item(self, index: int) -> dict[str, Any] | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    @property
    def items(self) -> list[dict[str, Any]]:
        return list(self._items)


class BoundedTextListModel(QAbstractListModel):
    """Append-only, virtualizable text rows for high-volume live output."""

    TextRole = Qt.UserRole + 1

    def __init__(self, maximum: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._maximum = max(1, int(maximum))
        self._items: list[str] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        if role in {Qt.DisplayRole, self.TextRole}:
            return self._items[index.row()]
        return None

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {self.TextRole: b"lineText"}

    def clear(self) -> None:
        if not self._items:
            return
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def append(self, value: str) -> None:
        if len(self._items) >= self._maximum:
            remove_count = len(self._items) - self._maximum + 1
            self.beginRemoveRows(QModelIndex(), 0, remove_count - 1)
            del self._items[:remove_count]
            self.endRemoveRows()
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(str(value))
        self.endInsertRows()


class _TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class _Task(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:  # pragma: no cover - service integration
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(result)


class StudioBridge(QObject):
    """Live state and actions for Dashboard, data, settings and log pages."""

    dashboardChanged = Signal()
    knowledgeChanged = Signal()
    reviewChanged = Signal()
    videosChanged = Signal()
    syncChanged = Signal()
    settingsChanged = Signal()
    providersChanged = Signal()
    providerRuntimeInstalled = Signal(str)
    _antigravityAuthChanged = Signal()
    archivedChanged = Signal()
    logsChanged = Signal()
    terminalChanged = Signal()
    toastRequested = Signal(str, str)
    navigationRequested = Signal(int)
    reviewFilterValuesChanged = Signal()
    reviewSelectionChanged = Signal()
    conversationRestored = Signal(str)
    _syncProgressReceived = Signal(str)

    def __init__(
        self,
        settings: MarySettings,
        database: MaryDatabase,
        preferences: QSettings | None = None,
        chat_orchestrator: Any = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._database = database
        self._preferences = preferences or QSettings(
            ORGANIZATION_NAME, SETTINGS_APP_NAME
        )
        self._pool = QThreadPool.globalInstance()
        self._tasks: set[_Task] = set()
        self._loaded_pages: set[int] = set()
        self._dashboard_sources: list[dict[str, Any]] = []
        self._dashboard_metrics: dict[str, str] = {}
        self._knowledge = MappingListModel(
            ("title", "module", "source", "status", "markdown", "localPath"), self
        )
        self._knowledge_total = 0
        self._knowledge_offset = 0
        self._knowledge_page_size = 100
        self._knowledge_query = ""
        self._knowledge_module = "Todos"
        self._knowledge_source = "Todas"
        self._knowledge_origin = ""
        self._knowledge_selected = -1
        self._review = MappingListModel(
            (
                "reviewId",
                "title",
                "source",
                "currentModule",
                "suggestedModule",
                "confidence",
                "product",
                "category",
                "risk",
                "updatedAt",
                "markdown",
                "localPath",
                "url",
                "sourceId",
            ),
            self,
        )
        self._review_total = 0
        self._review_offset = 0
        self._review_query = ""
        self._review_filters: dict[str, Any] = {}
        review_values = database.review_filter_values()
        self._product_items = ["Todos os produtos", *review_values.get("products", [])]
        self._category_items = ["Todas as categorias", *review_values.get("categories", [])]
        self._review_selected = -1
        self._videos = MappingListModel(
            (
                "depth",
                "title",
                "source",
                "module",
                "status",
                "download",
                "size",
                "confidence",
                "itemId",
                "selectable",
                "nodeId",
                "ancestorIds",
                "expandable",
            ),
            self,
        )
        self._all_video_items: list[dict[str, Any]] = []
        self._video_filters = ("", "", "", "")
        self._video_summary = ""
        self._sync_running = False
        self._sync_status = "Pronto"
        self._sync_log: list[str] = []
        self._sync_log_model = BoundedTextListModel(MAX_SYNC_LOG_LINES, self)
        self._schema_path = self._default_schema_path()
        self._settings_values: dict[str, Any] = {}
        self._providers: list[dict[str, Any]] = []
        self._provider_installs: dict[str, tuple[_Task, threading.Event]] = {}
        self._provider_install_status: dict[str, dict[str, str]] = {}
        self._archived = MappingListModel(
            ("conversationId", "title", "project", "provider", "updatedAt"), self
        )
        self._log_lines: list[str] = []
        self._log_model = BoundedTextListModel(MAX_LOG_LINES, self)
        self._video_process: QProcess | None = None
        self._video_loading = False
        self._video_refresh_task: _Task | None = None
        self._terminal_process: QProcess | None = None
        self._terminal_output = ""
        self._closed = False
        self._conversation_orchestrator = chat_orchestrator
        self._review_selection: set[int] = set()
        self._video_buffer = ""
        self._video_pending_output = ""
        self._video_output_timer = QTimer(self)
        self._video_output_timer.setSingleShot(True)
        self._video_output_timer.setInterval(80)
        self._video_output_timer.timeout.connect(self._flush_video_output)
        self._syncProgressReceived.connect(self._apply_sync_progress)
        self._antigravityAuthChanged.connect(self._refresh_antigravity_auth, Qt.QueuedConnection)
        self._antigravity_auth = AntigravityAuthManager(
            command_resolver=resolve_acp,
            env_factory=acp_environment,
            on_state_changed=self._on_antigravity_auth_state_changed,
        )
        self._agy_check_cancel = threading.Event()
        self._agy_check_process = None
        self._agy_check_client = None
        self._agy_opened_attempt = None

    def _on_antigravity_auth_state_changed(self) -> None:
        if not getattr(self, "_closed", False):
            self._antigravityAuthChanged.emit()

    @Slot()
    def _refresh_antigravity_auth(self) -> None:
        if not self._closed:
            self.refreshProviders()
            attempt = self._antigravity_auth.active_attempt
            if (attempt and attempt.state == "waiting" and attempt.validated_auth
                    and self._agy_opened_attempt != attempt.attempt_id):
                self._agy_opened_attempt = attempt.attempt_id
                if not QDesktopServices.openUrl(QUrl(attempt.validated_auth.authorization_url)):
                    self.toastRequested.emit("Não foi possível abrir o navegador. Use Abrir no navegador ou Copiar link.", "warning")

    @Slot()
    def restoreAntigravityAccount(self) -> None:
        if has_saved_account():
            self.validateAntigravityAccount()

    @Property("QVariantList", notify=dashboardChanged)
    def dashboardSources(self) -> list[dict[str, Any]]:  # noqa: N802
        return list(self._dashboard_sources)

    @Property("QVariantMap", notify=dashboardChanged)
    def dashboardMetrics(self) -> dict[str, str]:  # noqa: N802
        return dict(self._dashboard_metrics)

    @Property(QObject, constant=True)
    def knowledgeModel(self) -> MappingListModel:  # noqa: N802
        return self._knowledge

    @Property(int, notify=knowledgeChanged)
    def knowledgeTotal(self) -> int:  # noqa: N802
        return self._knowledge_total

    @Property(str, notify=knowledgeChanged)
    def knowledgePageLabel(self) -> str:  # noqa: N802
        page = self._knowledge_offset // self._knowledge_page_size + 1
        pages = max(1, (self._knowledge_total + self._knowledge_page_size - 1) // self._knowledge_page_size)
        return f"Página {page} de {pages}"

    @Property(bool, notify=knowledgeChanged)
    def knowledgeCanPrevious(self) -> bool:  # noqa: N802
        return self._knowledge_offset > 0

    @Property(bool, notify=knowledgeChanged)
    def knowledgeCanNext(self) -> bool:  # noqa: N802
        return self._knowledge_offset + self._knowledge_page_size < self._knowledge_total

    @Property(str, notify=knowledgeChanged)
    def knowledgePreview(self) -> str:  # noqa: N802
        row = self._knowledge.item(self._knowledge_selected)
        return str(row.get("markdown") or "") if row else ""

    @Property(str, notify=knowledgeChanged)
    def knowledgeTitle(self) -> str:  # noqa: N802
        row = self._knowledge.item(self._knowledge_selected)
        return str(row.get("title") or "Documento") if row else "Documento"

    @Property(str, notify=knowledgeChanged)
    def knowledgeLocalPath(self) -> str:  # noqa: N802
        row = self._knowledge.item(self._knowledge_selected)
        return str(row.get("localPath") or "") if row else ""

    @Property(QObject, constant=True)
    def reviewModel(self) -> MappingListModel:  # noqa: N802
        return self._review

    @Property(int, notify=reviewChanged)
    def reviewTotal(self) -> int:  # noqa: N802
        return self._review_total

    @Property(str, notify=reviewChanged)
    def reviewPreview(self) -> str:  # noqa: N802
        row = self._review.item(self._review_selected)
        return str(row.get("markdown") or "") if row else ""

    @Property(str, notify=reviewChanged)
    def reviewTitle(self) -> str:  # noqa: N802
        row = self._review.item(self._review_selected)
        return str(row.get("title") or "Nenhuma revisão encontrada") if row else "Nenhuma revisão encontrada"

    @Property(int, notify=reviewChanged)
    def currentReviewId(self) -> int:  # noqa: N802
        row = self._review.item(self._review_selected)
        return int(row.get("reviewId") or 0) if row else 0

    @Property(str, notify=reviewChanged)
    def reviewLocalPath(self) -> str:  # noqa: N802
        row = self._review.item(self._review_selected)
        return str(row.get("localPath") or "") if row else ""

    @Property(str, notify=reviewChanged)
    def reviewUrl(self) -> str:  # noqa: N802
        row = self._review.item(self._review_selected)
        return str(row.get("url") or "") if row else ""

    @Property(str, notify=reviewChanged)
    def reviewCitation(self) -> str:  # noqa: N802
        row = self._review.item(self._review_selected)
        if not row:
            return ""
        source = str(row.get("source") or "").upper()
        source_id = str(row.get("sourceId") or "")
        title = str(row.get("title") or "")
        url = str(row.get("url") or "")
        target = f"[{title}]({url})" if url else title
        current_module = str(row.get("currentModule") or "")
        return f"{target} — {current_module} · {source} · ID {source_id}".strip()

    @Property(str, notify=reviewChanged)
    def reviewPageLabel(self) -> str:  # noqa: N802
        page = self._review_offset // 100 + 1
        pages = max(1, (self._review_total + 99) // 100)
        return f"Página {page} de {pages}"

    @Property(bool, notify=reviewChanged)
    def reviewCanPrevious(self) -> bool:  # noqa: N802
        return self._review_offset > 0

    @Property(bool, notify=reviewChanged)
    def reviewCanNext(self) -> bool:  # noqa: N802
        return self._review_offset + 100 < self._review_total

    @Property(QObject, constant=True)
    def videoModel(self) -> MappingListModel:  # noqa: N802
        return self._videos

    @Property(str, notify=videosChanged)
    def videoSummary(self) -> str:  # noqa: N802
        return self._video_summary

    @Property(str, notify=videosChanged)
    def videoLog(self) -> str:  # noqa: N802
        return self._video_buffer

    @Property(bool, notify=videosChanged)
    def videoLoading(self) -> bool:  # noqa: N802
        return self._video_loading

    @Property("QVariantList", notify=videosChanged)
    def videoExpandableNodeIds(self) -> list[str]:  # noqa: N802
        return [
            str(item.get("nodeId") or "")
            for item in self._all_video_items
            if item.get("expandable") and str(item.get("nodeId") or "")
        ]

    @Property(bool, notify=videosChanged)
    def videoRunning(self) -> bool:  # noqa: N802
        return bool(
            self._video_process
            and self._video_process.state() != QProcess.NotRunning
        )

    @Property(bool, notify=syncChanged)
    def syncRunning(self) -> bool:  # noqa: N802
        return self._sync_running

    @Property(str, notify=syncChanged)
    def syncStatus(self) -> str:  # noqa: N802
        return self._sync_status

    @Property(str, notify=syncChanged)
    def syncLog(self) -> str:  # noqa: N802
        return "\n".join(self._sync_log)

    @Property(QObject, constant=True)
    def syncLogModel(self) -> QObject:  # noqa: N802
        return self._sync_log_model

    @Property(str, notify=syncChanged)
    def schemaPath(self) -> str:  # noqa: N802
        return str(self._schema_path)

    @Property("QVariantMap", notify=settingsChanged)
    def settingsValues(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._settings_values)

    @Property("QVariantList", notify=providersChanged)
    def providerItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return list(self._providers)

    @Property(QObject, constant=True)
    def archivedModel(self) -> MappingListModel:  # noqa: N802
        return self._archived

    @Property(str, notify=logsChanged)
    def logText(self) -> str:  # noqa: N802
        return "\n".join(self._log_lines)

    @Property(QObject, constant=True)
    def logModel(self) -> QObject:  # noqa: N802
        return self._log_model

    @Property(str, notify=terminalChanged)
    def terminalOutput(self) -> str:  # noqa: N802
        return self._terminal_output

    @Property(bool, notify=terminalChanged)
    def terminalRunning(self) -> bool:  # noqa: N802
        return bool(
            self._terminal_process
            and self._terminal_process.state() != QProcess.NotRunning
        )

    @Property("QVariantList", constant=True)
    def moduleItems(self) -> list[str]:  # noqa: N802
        return ["Todos", *MODULES]

    @Property("QVariantList", constant=True)
    def sourceItems(self) -> list[str]:  # noqa: N802
        return ["Todas", "wiki", "kb"]

    @Property("QVariantList", notify=reviewFilterValuesChanged)
    def productItems(self) -> list[str]:  # noqa: N802
        return list(self._product_items)

    @Property("QVariantList", notify=reviewFilterValuesChanged)
    def categoryItems(self) -> list[str]:  # noqa: N802
        return list(self._category_items)

    @Property(int, notify=reviewSelectionChanged)
    def reviewSelectionCount(self) -> int:  # noqa: N802
        return len(self._review_selection)

    @Property("QVariantList", notify=reviewSelectionChanged)
    def selectedReviewIds(self) -> list[int]:  # noqa: N802
        return sorted(self._review_selection)

    @Slot(int)
    def activatePage(self, index: int) -> None:  # noqa: N802
        """Load only the data needed by the page the user actually opened."""

        page = int(index)
        if page in self._loaded_pages or page == 1:
            return
        self._loaded_pages.add(page)
        try:
            if page == 0:
                self._refresh_dashboard()
            elif page == 2:
                self.searchKnowledge("", "Todos", "Todas", "")
            elif page == 4:
                self.searchReviews("")
            elif page == 5:
                self.refreshVideos()
            elif page == 7:
                self._refresh_settings()
                self.refreshProviders()
                self.refreshArchived("")
        except Exception as exc:
            self._loaded_pages.discard(page)
            self.toastRequested.emit(str(exc), "error")

    @Slot()
    def refreshAll(self) -> None:  # noqa: N802
        self._loaded_pages.update({0, 2, 4, 5, 7})
        self._refresh_dashboard()
        self.searchKnowledge("", "Todos", "Todas", "")
        self.searchReviews("")
        self.refreshVideos()
        self._refresh_settings()
        self.refreshProviders()
        self.refreshArchived("")

    def _refresh_dashboard(self) -> None:
        source_specs = {
            "vrwiki": ("wiki", "vrwiki"),
            "endoo": ("wiki", "endoo"),
            "kb": ("kb", "movidesk"),
        }
        with self._database.connect() as connection:
            documents = int(connection.execute(
                "SELECT count(*) FROM documents WHERE status='active' AND source<>'schema'"
            ).fetchone()[0])
            reviews = int(connection.execute(
                """SELECT count(*) FROM classification_reviews r
                   JOIN documents d ON d.id=r.document_id
                   WHERE r.status='pending' AND d.status='active'"""
            ).fetchone()[0])
            ocr = int(connection.execute(
                "SELECT count(*) FROM documents WHERE status='active' AND length(ocr_text)>0"
            ).fetchone()[0])
            conversations = int(connection.execute(
                "SELECT count(*) FROM conversations WHERE archived=0 AND trashed_at=''"
            ).fetchone()[0])
            counts = {
                key: int(connection.execute(
                    "SELECT count(*) FROM documents WHERE source=? AND source_origin=? AND status='active'",
                    values,
                ).fetchone()[0])
                for key, values in source_specs.items()
            }
            runs = {
                key: connection.execute(
                    """SELECT finished_at,status,stats_json,error FROM sync_runs
                       WHERE source=? AND source_origin=? ORDER BY id DESC LIMIT 1""",
                    values,
                ).fetchone()
                for key, values in source_specs.items()
            }
        labels = {
            "vrwiki": ("VRWiki", "Base pública MediaWiki", "Sincronizar Wiki"),
            "endoo": ("Wiki Endoo", "Base autenticada do portal Endoo", "Sincronizar Wiki Endoo"),
            "kb": ("Movidesk KB", "Base autenticada de suporte", "Sincronizar KB"),
        }
        sources: list[dict[str, Any]] = []
        for key in ("vrwiki", "endoo", "kb"):
            run = runs[key]
            status = "Nunca sincronizado"
            detail = ""
            good = False
            if key == "endoo" and not self._settings.endoo_wiki_enabled:
                status = "Integração desativada"
                detail = "Ative VR_ENDOO_WIKI_ENABLED=true no arquivo .env."
            elif run:
                try:
                    stats = json.loads(run["stats_json"] or "{}")
                except json.JSONDecodeError:
                    stats = {}
                errors = int(stats.get("errors", 0) or 0)
                good = run["status"] == "completed" and not run["error"] and errors == 0
                status = "Sincronização concluída" if good else "Concluída com falhas"
                detail = self._format_sync_detail(run, stats)
            name, description, action = labels[key]
            sources.append({
                "key": key,
                "name": name,
                "description": description,
                "count": f"{counts[key]} documentos",
                "status": ("OK — " if good else "ATENÇÃO — ") + status,
                "detail": detail,
                "good": good,
                "action": action,
            })
        video_count, video_detail, video_good = self._video_dashboard_state()
        sources.append({
            "key": "video",
            "name": "Vídeos",
            "description": "Inventário do extrator VRSoft",
            "count": f"{video_count} vídeos",
            "status": ("OK — " if video_good else "ATENÇÃO — ") + ("Inventário disponível" if video_good else "Inventário não encontrado"),
            "detail": video_detail,
            "good": video_good,
            "action": "Abrir Vídeos",
        })
        self._dashboard_sources = sources
        self._dashboard_metrics = {
            "documents": str(documents),
            "reviews": str(reviews),
            "ocr": str(ocr),
            "conversations": str(conversations),
        }
        self.dashboardChanged.emit()

    @staticmethod
    def _format_sync_detail(run: Any, stats: dict[str, Any]) -> str:
        raw = str(run["finished_at"] or "")
        try:
            finished = datetime.fromisoformat(raw).astimezone().strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            finished = raw or "em execução"
        detail = (
            f"{finished}\nDescobertos {int(stats.get('discovered', 0) or 0)} · "
            f"Novos {int(stats.get('created', 0) or 0)} · "
            f"Atualizados {int(stats.get('updated', 0) or 0)} · "
            f"Erros {int(stats.get('errors', 0) or 0)}"
        )
        if run["error"]:
            detail += "\n" + str(run["error"]).splitlines()[0][:140]
        return detail

    def _video_dashboard_state(self) -> tuple[int, str, bool]:
        try:
            from ...inventory import load_inventory
            from ...settings import load_settings
            from ...video_storage import inspect_video_storage

            rows = load_inventory(self._settings.root / "metadata" / "videos.json")
            storage = inspect_video_storage(rows, load_settings(project_dir=self._settings.root))
            downloaded = sum(item.downloaded for item in storage.values())
            failures = sum(item.status in {"error", "failed"} for item in rows)
            return len(rows), f"Baixados {downloaded} · Pendentes {max(0, len(rows) - downloaded - failures)} · Falhas {failures}", bool(rows)
        except Exception:
            return 0, "Execute Inventariar na tela de Vídeos.", False

    @Slot(str, str, str, str)
    def searchKnowledge(self, query: str, module: str, source: str, origin: str) -> None:  # noqa: N802
        self._knowledge_query = str(query or "").strip()
        self._knowledge_module = str(module or "Todos")
        self._knowledge_source = str(source or "Todas")
        self._knowledge_origin = str(origin or "")
        self._knowledge_offset = 0
        self._load_knowledge()

    def _load_knowledge(self) -> None:
        query = self._knowledge_query or "*"
        module = self._knowledge_module
        source = self._knowledge_source
        try:
            if query == "*":
                clauses = ["status='active'", "source<>'schema'"]
                parameters: list[Any] = []
                if module != "Todos":
                    clauses.append("module=?")
                    parameters.append(module)
                if source != "Todas":
                    clauses.append("source=?")
                    parameters.append(source)
                if self._knowledge_origin:
                    clauses.append("source_origin=?")
                    parameters.append(self._knowledge_origin)
                where = " AND ".join(clauses)
                with self._database.connect() as connection:
                    total = int(connection.execute(
                        f"SELECT count(*) FROM documents WHERE {where}", parameters
                    ).fetchone()[0])
                    rows = connection.execute(
                        f"SELECT * FROM documents WHERE {where} ORDER BY synced_at DESC LIMIT ? OFFSET ?",
                        [*parameters, self._knowledge_page_size, self._knowledge_offset],
                    ).fetchall()
                    results = [dict(row) for row in rows]
            else:
                results, total = self._database.search_page(
                    query,
                    limit=self._knowledge_page_size,
                    offset=self._knowledge_offset,
                    module="" if module == "Todos" else module,
                    source="" if source == "Todas" else source,
                    source_origin=self._knowledge_origin,
                    excluded_sources=("schema",),
                )
        except Exception as exc:
            self._append_log(f"Falha ao consultar conhecimento: {exc}")
            self.toastRequested.emit(str(exc), "error")
            results, total = [], 0
        items = []
        for result in results:
            local_path = self._settings.resolve_path(result.get("local_path", ""))
            markdown = str(result.get("markdown") or result.get("excerpt") or "")
            if local_path.is_file():
                try:
                    markdown = local_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            items.append({
                "title": str(result.get("title") or ""),
                "module": str(result.get("module") or ""),
                "source": str(result.get("source") or "").upper(),
                "status": STATUS_LABELS.get(str(result.get("review_status") or "").casefold(), str(result.get("review_status") or "").title()),
                "markdown": markdown,
                "localPath": str(local_path),
            })
        self._knowledge_total = total
        self._knowledge.replace(items)
        self._knowledge_selected = 0 if items else -1
        self.knowledgeChanged.emit()

    @Slot(int)
    def selectKnowledge(self, index: int) -> None:  # noqa: N802
        if self._knowledge.item(index) is None:
            return
        self._knowledge_selected = index
        self.knowledgeChanged.emit()

    @Slot()
    def previousKnowledgePage(self) -> None:  # noqa: N802
        self._knowledge_offset = max(0, self._knowledge_offset - self._knowledge_page_size)
        self._load_knowledge()

    @Slot()
    def nextKnowledgePage(self) -> None:  # noqa: N802
        if self.knowledgeCanNext:
            self._knowledge_offset += self._knowledge_page_size
            self._load_knowledge()

    @Slot(str)
    def searchReviews(self, query: str) -> None:  # noqa: N802
        self._clear_review_selection()
        self._review_query = str(query or "").strip()
        self._review_filters = {}
        self._review_offset = 0
        self._load_reviews()

    @Slot(str, "QVariantMap")
    def searchReviewsAdvanced(self, query: str, filters: dict[str, Any]) -> None:  # noqa: N802
        self._clear_review_selection()
        self._review_query = str(query or "").strip()
        self._review_filters = dict(filters or {})
        self._review_offset = 0
        self._load_reviews()

    def _review_query_filters(self, limit: int, offset: int) -> ReviewFilters:
        values = self._review_filters
        return ReviewFilters(
            query=self._review_query,
            source=str(values.get("source") or ""),
            source_origin=str(values.get("sourceOrigin") or ""),
            current_module=str(values.get("currentModule") or ""),
            suggested_module=str(values.get("suggestedModule") or ""),
            confidence_band=str(values.get("confidence") or ""),
            product=str(values.get("product") or ""),
            category=str(values.get("category") or ""),
            status=str(values.get("status") or "pending"),
            period_days=int(values.get("periodDays") or 0),
            special=str(values.get("special") or ""),
            sort=str(values.get("sort") or "risk"),
            limit=limit,
            offset=offset,
        )

    def _load_reviews(self) -> None:
        try:
            page = self._database.query_reviews(
                self._review_query_filters(100, self._review_offset)
            )
            rows = page.items
            self._review_total = page.total
            self._review_offset = page.offset
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            rows = []
            self._review_total = 0
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                reasons = json.loads(row.get("reasons_json") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                reasons = []
            local_path = self._settings.resolve_path(row.get("local_path", ""))
            markdown = str(row.get("markdown") or "")
            if local_path.is_file():
                try:
                    markdown = local_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            evidence = "\n".join(f"- {reason}" for reason in reasons) or "- Sem evidência"
            try:
                assets = json.loads(row.get("assets_json") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                assets = []
            asset_lines = "\n".join(
                f"- {self._settings.resolve_path(value).name}" for value in assets
            ) or "- Nenhuma imagem associada"
            status = STATUS_LABELS.get(
                str(row.get("status") or "").casefold(),
                str(row.get("status") or "").title(),
            )
            detailed_markdown = f"""\
- **Estado:** {status}
- **Risco:** {row.get('risk_label') or ''}
- **Fonte / ID:** {str(row.get('source') or '').upper()} · {row.get('source_id') or ''}
- **Módulo atual → sugerido:** {row.get('current_module') or ''} → {row.get('suggested_module') or ''}
- **Confiança:** {float(row.get('confidence') or 0):.0%}
- **Produto:** {row.get('product') or 'Não identificado'}
- **Categoria:** {row.get('category') or 'Sem categoria'}
- **Atualização:** {row.get('document_updated_at') or row.get('synced_at') or ''}
- **Nota registrada:** {row.get('decision_note') or 'Sem nota'}

## Evidências

{evidence}

## Imagens

{asset_lines}

## Conteúdo

{markdown or '_Documento sem Markdown._'}

## OCR

{row.get('ocr_text') or '_Sem OCR associado._'}
"""
            items.append({
                "reviewId": int(row["id"]),
                "title": str(row.get("title") or ""),
                "source": str(row.get("source") or "").upper(),
                "currentModule": str(row.get("current_module") or ""),
                "suggestedModule": str(row.get("suggested_module") or ""),
                "confidence": f"{float(row.get('confidence') or 0):.0%}",
                "product": str(row.get("product") or "Não identificado"),
                "category": str(row.get("category") or "Sem categoria"),
                "risk": f"{row.get('risk_label') or ''} · {reasons[0] if reasons else 'Sem evidência registrada'}",
                "updatedAt": str(row.get("updated_at") or row.get("document_updated_at") or row.get("synced_at") or ""),
                "markdown": detailed_markdown,
                "localPath": str(local_path),
                "url": str(row.get("url") or ""),
                "sourceId": str(row.get("source_id") or ""),
            })
        self._review.replace(items)
        self._review_selected = 0 if items else -1
        self.reviewChanged.emit()

    @Slot(int)
    def selectReview(self, index: int) -> None:  # noqa: N802
        if self._review.item(index) is None:
            return
        self._review_selected = index
        self.reviewChanged.emit()

    @Slot(int, result=bool)
    def isReviewSelected(self, review_id: int) -> bool:  # noqa: N802
        return int(review_id) in self._review_selection

    @Slot(int, bool)
    def setReviewSelected(self, review_id: int, selected: bool) -> None:  # noqa: N802
        identifier = int(review_id)
        if selected:
            if identifier in self._review_selection:
                return
            self._review_selection.add(identifier)
        else:
            if identifier not in self._review_selection:
                return
            self._review_selection.discard(identifier)
        self.reviewSelectionChanged.emit()

    @Slot(bool)
    def setAllReviewsSelected(self, selected: bool) -> None:  # noqa: N802
        if not selected:
            if not self._review_selection:
                return
            self._review_selection = set()
            self.reviewSelectionChanged.emit()
            return
        selection: set[int] = set()
        try:
            offset = 0
            while offset < 10_000:
                page = self._database.query_reviews(
                    self._review_query_filters(500, offset)
                )
                selection.update(int(row["id"]) for row in page.items)
                if len(page.items) < 500:
                    break
                offset += len(page.items)
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        self._review_selection = selection
        self.reviewSelectionChanged.emit()

    def _clear_review_selection(self) -> None:
        if not self._review_selection:
            return
        self._review_selection = set()
        self.reviewSelectionChanged.emit()

    @Slot()
    def previousReviewPage(self) -> None:  # noqa: N802
        if not self.reviewCanPrevious:
            return
        self._review_offset = max(0, self._review_offset - 100)
        self._load_reviews()

    @Slot()
    def nextReviewPage(self) -> None:  # noqa: N802
        if not self.reviewCanNext:
            return
        self._review_offset += 100
        self._load_reviews()

    @Slot(str, "QVariantList", str, str)
    def decideReviews(self, action: str, ids: list[Any], module: str, note: str) -> None:  # noqa: N802
        review_ids = [int(value) for value in ids if str(value).isdigit()]
        if not review_ids and self._review_selected >= 0:
            row = self._review.item(self._review_selected)
            review_ids = [int(row["reviewId"])] if row else []
        if not review_ids:
            self.toastRequested.emit("Selecione pelo menos uma revisão.", "warning")
            return
        try:
            count = self._database.decide_reviews(review_ids, action, module=module, note=note.strip())
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        self.toastRequested.emit(f"{count} revisão(ões) atualizada(s).", "success")
        self._clear_review_selection()
        self._load_reviews()
        self._refresh_dashboard()
        self._refresh_review_filter_values()

    @Slot()
    def refreshVideos(self) -> None:  # noqa: N802
        if self._video_loading:
            return
        self._video_loading = True
        self._video_summary = "Carregando inventário…"
        self.videosChanged.emit()
        task = _Task(self._build_video_snapshot)
        self._video_refresh_task = task
        self._tasks.add(task)
        task.signals.finished.connect(
            lambda result, task=task: self._video_snapshot_ready(task, result)
        )
        task.signals.failed.connect(
            lambda error, task=task: self._video_snapshot_failed(task, error)
        )
        self._pool.start(task)

    def _build_video_snapshot(self) -> tuple[list[dict[str, Any]], str]:
        try:
            from ...courses import load_course_catalog
            from ...inventory import load_inventory
            from ...settings import load_settings
            from ...video_storage import format_byte_size, inspect_video_storage

            rows = load_inventory(self._settings.root / "metadata" / "videos.json")
            courses = load_course_catalog(self._settings.root / "metadata" / "courses.json")
            storage = inspect_video_storage(rows, load_settings(project_dir=self._settings.root))
            nodes: dict[str, dict[str, Any]] = {}

            def ensure_node(
                node_id: str,
                title: str,
                *,
                parent_id: str = "",
                source: str = "",
                module: str = "",
                status: str = "",
                download: str = "",
                size: str = "",
                confidence: str = "",
                item_id: str = "",
                selectable: bool = False,
                sort_key: object = "",
            ) -> dict[str, Any]:
                existing = nodes.get(node_id)
                if existing is not None:
                    return existing
                ancestors = []
                if parent_id:
                    parent = nodes[parent_id]
                    ancestors = [*parent["ancestorIds"], parent_id]
                value: dict[str, Any] = {
                    "depth": len(ancestors),
                    "title": title,
                    "source": source,
                    "module": module,
                    "status": status,
                    "download": download,
                    "size": size,
                    "confidence": confidence,
                    "itemId": item_id,
                    "selectable": selectable,
                    "nodeId": node_id,
                    "ancestorIds": ancestors,
                    "expandable": False,
                    "_children": [],
                    "_sortKey": sort_key,
                    "_downloaded": 0,
                    "_total": 0,
                    "_files": {},
                }
                nodes[node_id] = value
                if parent_id:
                    nodes[parent_id]["_children"].append(node_id)
                    nodes[parent_id]["expandable"] = True
                return value

            ensure_node(
                "root:courses", "Cursos", source="Cursos", sort_key=(0, 0, "cursos")
            )
            ensure_node(
                "root:library",
                "Biblioteca / Arquivos",
                source="Biblioteca",
                sort_key=(1, 0, "biblioteca"),
            )

            represented_courses: set[str] = set()
            sorted_rows = sorted(
                rows,
                key=lambda value: (
                    value.area,
                    value.business_module,
                    value.course.casefold(),
                    value.source_order,
                    value.lesson_title.casefold(),
                ),
            )
            for row in sorted_rows:
                is_course = row.area == "curso"
                root_id = "root:courses" if is_course else "root:library"
                source_label = "Cursos" if is_course else "Biblioteca"
                module_name = row.business_module or "Revisar"
                module_id = f"{root_id}:module:{module_name}"
                ensure_node(
                    module_id,
                    module_name,
                    parent_id=root_id,
                    module=module_name,
                    sort_key=(0, 0, module_name.casefold()),
                )
                parent_id = module_id
                if is_course:
                    represented_courses.add(row.course.casefold())
                    if row.source_course_id:
                        represented_courses.add(str(row.source_course_id))
                    course_key = row.source_course_id or row.course.casefold()
                    course_id = f"{module_id}:course:{course_key}"
                    ensure_node(
                        course_id,
                        row.course or "Curso",
                        parent_id=module_id,
                        source="Cursos",
                        module=module_name,
                        status="Inscrito",
                        sort_key=(0, 0, (row.course or "Curso").casefold()),
                    )
                    parent_id = course_id
                    hierarchy = (
                        list(row.folder_path[1:])
                        if len(row.folder_path) > 1
                        else ([row.module] if row.module else [])
                    )
                else:
                    hierarchy = list(row.folder_path)

                for folder_index, part in enumerate(
                    value for value in hierarchy if str(value).strip()
                ):
                    folder_id = f"{parent_id}:folder:{part}"
                    ensure_node(
                        folder_id,
                        str(part),
                        parent_id=parent_id,
                        module=module_name,
                        status="Pasta",
                        sort_key=(0, folder_index, str(part).casefold()),
                    )
                    parent_id = folder_id

                info = storage.get(row.id)
                downloaded = bool(info and info.downloaded)
                size_bytes = int(info.size_bytes or 0) if info else 0
                state = str(getattr(info, "state", "") or "") if info else ""
                leaf = ensure_node(
                    f"video:{row.id}",
                    row.lesson_title or row.title or row.id,
                    parent_id=parent_id,
                    source=source_label,
                    module=module_name,
                    status=row.status,
                    download=state or ("Baixado" if downloaded else "Pendente"),
                    size=format_byte_size(size_bytes) if size_bytes else "",
                    confidence=(
                        f"{row.classification_confidence:.0%}"
                        if row.classification_confidence
                        else ""
                    ),
                    item_id=row.id,
                    selectable=True,
                    sort_key=(1, row.source_order, row.lesson_title.casefold()),
                )
                for ancestor_id in leaf["ancestorIds"]:
                    aggregate = nodes[ancestor_id]
                    aggregate["_total"] += 1
                    if downloaded:
                        aggregate["_downloaded"] += 1
                    if info and info.path:
                        aggregate["_files"][str(info.path).casefold()] = size_bytes

            for course in sorted(courses, key=lambda value: value.name.casefold()):
                represented_key = course.course_id or course.name.casefold()
                if course.status == "enrolled" and (
                    represented_key in represented_courses
                    or course.name.casefold() in represented_courses
                ):
                    continue
                module_name = course.business_module or "Revisar"
                module_id = f"root:courses:module:{module_name}"
                ensure_node(
                    module_id,
                    module_name,
                    parent_id="root:courses",
                    module=module_name,
                    sort_key=(0, 0, module_name.casefold()),
                )
                ensure_node(
                    f"{module_id}:catalog:{course.course_id or course.name}",
                    course.name,
                    parent_id=module_id,
                    source="Cursos",
                    module=module_name,
                    status=course.reason or course.status,
                    download="Inscrever" if course.selectable else "",
                    confidence=(
                        f"{course.classification_confidence:.0%}"
                        if course.classification_confidence
                        else ""
                    ),
                    item_id=f"course:{course.course_id}:{course.selected_class_id}",
                    selectable=course.selectable,
                    sort_key=(1, 0, course.name.casefold()),
                )

            for node in nodes.values():
                if node["_total"]:
                    node["download"] = (
                        f"{node['_downloaded']}/{node['_total']} baixados"
                    )
                    if node["_files"]:
                        node["size"] = format_byte_size(
                            sum(node["_files"].values())
                        )

            items: list[dict[str, Any]] = []

            def flatten(node_id: str) -> None:
                node = nodes[node_id]
                items.append(
                    {
                        key: value
                        for key, value in node.items()
                        if not key.startswith("_")
                    }
                )
                children = sorted(
                    node["_children"], key=lambda child_id: nodes[child_id]["_sortKey"]
                )
                for child_id in children:
                    flatten(child_id)

            flatten("root:courses")
            flatten("root:library")
            downloaded = sum(info.downloaded for info in storage.values())
            total_size = sum(info.size_bytes for info in storage.values() if info.downloaded)
            summary = f"{len(rows)} vídeos · {len(courses)} cursos no catálogo · {downloaded}/{len(rows)} baixados · {format_byte_size(total_size)}"
        except Exception as exc:
            items = []
            summary = f"Inventário indisponível · {exc}"
        return items, summary

    def _video_snapshot_ready(self, task: _Task, result: object) -> None:
        self._tasks.discard(task)
        if task is not self._video_refresh_task:
            return
        self._video_refresh_task = None
        self._video_loading = False
        items, summary = result if isinstance(result, tuple) and len(result) == 2 else ([], "Inventário indisponível")
        self._all_video_items = items
        self._video_summary = str(summary)
        self._apply_video_filters()
        self.videosChanged.emit()

    def _video_snapshot_failed(self, task: _Task, error: str) -> None:
        self._tasks.discard(task)
        if task is not self._video_refresh_task:
            return
        self._video_refresh_task = None
        self._video_loading = False
        self._all_video_items = []
        self._video_summary = f"Inventário indisponível · {error}"
        self._apply_video_filters()
        self.videosChanged.emit()

    @Slot(str, str, str, str)
    def filterVideos(self, query: str, source: str, module: str, status: str) -> None:  # noqa: N802
        self._video_filters = (
            str(query or "").strip().casefold(),
            str(source or "").strip().casefold(),
            str(module or "").strip().casefold(),
            str(status or "").strip().casefold(),
        )
        self._apply_video_filters()
        self.videosChanged.emit()

    def _apply_video_filters(self) -> None:
        query, source, module, status = self._video_filters
        if not any(self._video_filters):
            self._videos.replace(self._all_video_items)
            return
        matching: set[int] = set()
        for index, item in enumerate(self._all_video_items):
            if item.get("expandable"):
                continue
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("title", "source", "module", "status", "download")
            ).casefold()
            item_source = str(item.get("source") or "").casefold()
            item_module = str(item.get("module") or "").casefold()
            item_status = " ".join(
                (str(item.get("status") or ""), str(item.get("download") or ""))
            ).casefold()
            if query and query not in haystack:
                continue
            if source and source not in item_source:
                continue
            if module and module != item_module:
                continue
            if status:
                if status == "downloaded":
                    if not any(value in item_status for value in ("downloaded", "baixado")):
                        continue
                elif status == "review":
                    if item_module != "revisar" and "review" not in item_status:
                        continue
                elif status not in item_status:
                    continue
            matching.add(index)
            wanted_depth = int(item.get("depth") or 0)
            cursor = index - 1
            while cursor >= 0 and wanted_depth > 0:
                parent_depth = int(self._all_video_items[cursor].get("depth") or 0)
                if parent_depth < wanted_depth:
                    matching.add(cursor)
                    wanted_depth = parent_depth
                cursor -= 1
        self._videos.replace(
            [item for index, item in enumerate(self._all_video_items) if index in matching]
        )

    @Slot(str, result="QVariantList")
    def videoDescendantNodeIds(self, node_id: str) -> list[str]:  # noqa: N802
        target = str(node_id or "")
        if not target:
            return []
        return [
            str(item.get("nodeId") or "")
            for item in self._all_video_items
            if item.get("expandable")
            and target in list(item.get("ancestorIds") or [])
            and str(item.get("nodeId") or "")
        ]

    @Slot(str)
    def runVideoAction(self, action: str) -> None:  # noqa: N802
        self._start_video_process(action, [])

    def _start_video_process(self, action: str, extra_args: list[str]) -> None:
        if self._video_process and self._video_process.state() != QProcess.NotRunning:
            self.toastRequested.emit("Já existe uma ação de vídeo em execução.", "warning")
            return
        self._video_process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("ENDOO_GUI_MODE", "1")
        self._video_process.setProcessEnvironment(environment)
        self._video_process.setWorkingDirectory(str(self._settings.app_dir))
        self._video_process.setProcessChannelMode(QProcess.MergedChannels)
        self._video_process.readyReadStandardOutput.connect(self._read_video_output)
        self._video_process.finished.connect(self._video_finished)
        self._video_process.finished.connect(self._video_process.deleteLater)
        args = ["-m", "vrsoft_extractor", "--project-dir", str(self._settings.root), action, *extra_args]
        if action == "scan" and not self._settings.endoo_state_path.is_file():
            args.append("--headed")
        self._video_output_timer.stop()
        self._video_buffer = ""
        self._video_pending_output = ""
        self._video_summary = f"Executando {action}…"
        self._append_log("$ " + Path(sys.executable).name + " " + " ".join(args))
        self._video_process.start(sys.executable, args)
        self.videosChanged.emit()

    @Slot(str, "QVariantList")
    def runVideoSelection(self, action: str, ids: list[Any]) -> None:  # noqa: N802
        item_ids = [str(value) for value in ids if str(value) and not str(value).startswith("course:")]
        if not item_ids:
            self.toastRequested.emit("Selecione pelo menos um vídeo.", "warning")
            return
        extra: list[str] = []
        for item_id in item_ids:
            extra.extend(("--item-id", item_id))
        self._start_video_process(action, extra)

    @Slot("QVariantList")
    def enrollSelectedCourses(self, ids: list[Any]) -> None:  # noqa: N802
        selections = []
        for value in ids:
            raw = str(value)
            if raw.startswith("course:"):
                _prefix, course_id, class_id = (raw.split(":", 2) + [""])[:3]
                if course_id and class_id:
                    selections.append(f"{course_id}:{class_id}")
        if not selections:
            self.toastRequested.emit("Selecione pelo menos um curso disponível.", "warning")
            return
        self._start_video_process("enroll", [*selections, "--confirm", "--scan-after"])

    @Slot("QVariantList", str)
    def applyVideoModule(self, ids: list[Any], module: str) -> None:  # noqa: N802
        targets = []
        for value in ids:
            raw = str(value)
            if raw.startswith("course:"):
                parts = raw.split(":", 2)
                targets.append(("groups", f"course:{parts[1]}", module))
            elif raw:
                targets.append(("items", raw, module))
        if not targets:
            self.toastRequested.emit("Selecione um curso ou vídeo.", "warning")
            return
        try:
            from ...inventory import load_inventory, save_inventory
            from ...settings import load_settings
            from ...video_classification import classify_inventory, save_module_overrides

            extractor_settings = load_settings(project_dir=self._settings.root)
            save_module_overrides(extractor_settings.video_overrides_path, targets)
            items = load_inventory(extractor_settings.inventory_json_path)
            classify_inventory(items, extractor_settings.video_overrides_path)
            save_inventory(items, extractor_settings.inventory_json_path, extractor_settings.inventory_csv_path)
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        self.refreshVideos()
        self.toastRequested.emit("Classificação aplicada.", "success")

    @Slot()
    def organizeVideoDownloads(self) -> None:  # noqa: N802
        try:
            from ...downloader import organize_downloads
            from ...settings import load_settings

            result = organize_downloads(load_settings(project_dir=self._settings.root))
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        self.refreshVideos()
        self.toastRequested.emit(
            f"Organização concluída: {result['moved']} movidos, {result['collisions']} colisões, {result['missing']} ausentes.",
            "success",
        )

    @Slot()
    def stopVideoAction(self) -> None:  # noqa: N802
        process = self._video_process
        if not process or process.state() == QProcess.NotRunning:
            return
        process.terminate()
        QTimer.singleShot(3000, lambda: self._kill_process_if_running(process))

    @staticmethod
    def _kill_process_if_running(process: QProcess) -> None:
        try:
            if process.state() != QProcess.NotRunning:
                process.kill()
        except RuntimeError:
            pass

    def _read_video_output(self) -> None:
        if not self._video_process:
            return
        text = bytes(self._video_process.readAllStandardOutput()).decode("utf-8", "replace")
        if text:
            self._video_pending_output = _bounded_text(
                self._video_pending_output, redact_sensitive_text(text)
            )
            self._append_log(text.rstrip())
            if not self._video_output_timer.isActive():
                self._video_output_timer.start()

    def _flush_video_output(self) -> None:
        if not self._video_pending_output:
            return
        self._video_buffer = _bounded_text(
            self._video_buffer, self._video_pending_output
        )
        self._video_pending_output = ""
        self.videosChanged.emit()

    def _video_finished(self, code: int, _status: Any) -> None:
        self._video_process = None
        self._video_output_timer.stop()
        self._flush_video_output()
        self._video_summary = "Concluído" if code == 0 else f"Falha · código {code}"
        self.refreshVideos()
        self._refresh_dashboard()

    @Slot(str)
    def runSync(self, action: str) -> None:  # noqa: N802
        if self._sync_running:
            self.toastRequested.emit("Já existe uma sincronização em andamento.", "warning")
            return
        actions: dict[str, tuple[str, Callable[[], Any]]] = {
            "vrwiki": ("Wiki", lambda: WikiSync(self._settings, self._database, self._sync_progress).sync()),
            "endoo": ("Wiki Endoo", self._sync_endoo),
            "kb": ("KB", self._sync_kb),
            "kb_visible": ("Login/KB visível", self._sync_kb_visible),
            "schema": ("Schema", lambda: SchemaSync(self._settings, self._database, self._sync_progress, schema_path=self._schema_path).sync()),
            "all": ("Wikis + KB + Schema", self._sync_all),
            "wiki_kb": ("Wikis + KB", self._sync_wiki_kb),
            "ocr": ("OCR portátil", self._install_ocr),
        }
        selected = actions.get(action)
        if selected is None:
            return
        label, operation = selected
        self._sync_running = True
        self._sync_status = f"Sincronizando {label}…"
        self._sync_log = []
        self._sync_log_model.clear()
        self.syncChanged.emit()
        self.navigationRequested.emit(3)
        task = _Task(operation)
        self._tasks.add(task)
        task.signals.finished.connect(lambda result, task=task, label=label: self._sync_finished(task, label, result))
        task.signals.failed.connect(lambda error, task=task: self._sync_failed(task, error))
        self._pool.start(task)

    def _append_sync_log(self, message: object) -> None:
        value = redact_sensitive_text(message)
        if len(value) > MAX_LOG_ENTRY_CHARS:
            value = "[...entrada truncada...]\n" + value[-MAX_LOG_ENTRY_CHARS:]
        self._sync_log.append(value)
        self._sync_log = self._sync_log[-MAX_SYNC_LOG_LINES:]
        self._sync_log_model.append(value)

    def _sync_progress(self, message: str) -> None:
        self._syncProgressReceived.emit(str(message))

    @Slot(str)
    def _apply_sync_progress(self, message: str) -> None:
        self._append_sync_log(message)
        self._append_log(str(message))
        self.syncChanged.emit()

    def _sync_endoo(self) -> Any:
        sync = EndooWikiSync(self._settings, self._database, self._sync_progress)
        try:
            return sync.sync(headless=True)
        except Exception:
            sync.login()
            return sync.sync(headless=True)

    def _sync_kb(self) -> Any:
        sync = MovideskSync(self._settings, self._database, self._sync_progress, allow_session_takeover=True)
        try:
            return sync.sync(headed=False)
        except MovideskInteractiveLoginRequired:
            sync.login()
            return sync.sync(headed=False)

    def _sync_kb_visible(self) -> Any:
        sync = MovideskSync(
            self._settings,
            self._database,
            self._sync_progress,
            allow_session_takeover=True,
        )
        sync.login()
        return sync.sync(headed=False)

    def _sync_selected(self, sources: tuple[str, ...]) -> dict[str, Any]:
        operations = {
            "vrwiki": lambda: WikiSync(self._settings, self._database, self._sync_progress).sync(),
            "endoo": self._sync_endoo,
            "kb": self._sync_kb,
            "schema": lambda: SchemaSync(self._settings, self._database, self._sync_progress, schema_path=self._schema_path).sync(),
        }
        results: dict[str, Any] = {}
        for source in sources:
            try:
                result = operations[source]()
                results[source] = result.to_dict() if hasattr(result, "to_dict") else result
            except Exception as exc:
                results[source] = {"status": "error", "errors": 1, "error": str(exc)}
        return results

    def _sync_all(self) -> dict[str, Any]:
        sources = ["vrwiki", "kb", "schema"]
        if self._settings.endoo_wiki_enabled:
            sources.insert(1, "endoo")
        return self._sync_selected(tuple(sources))

    def _sync_wiki_kb(self) -> dict[str, Any]:
        sources = ["vrwiki", "kb"]
        if self._settings.endoo_wiki_enabled:
            sources.insert(1, "endoo")
        return self._sync_selected(tuple(sources))

    def _install_ocr(self) -> str:
        from ..ocr import OcrManager

        path = OcrManager(self._settings.tesseract_dir).install_portable(self._sync_progress)
        return str(path)

    def _refresh_review_filter_values(self) -> None:
        try:
            values = self._database.review_filter_values()
        except Exception:
            return
        self._product_items = ["Todos os produtos", *values.get("products", [])]
        self._category_items = [
            "Todas as categorias",
            *values.get("categories", []),
        ]
        self.reviewFilterValuesChanged.emit()

    def _sync_finished(self, task: _Task, label: str, result: Any) -> None:
        self._tasks.discard(task)
        self._sync_running = False
        value = result.to_dict() if hasattr(result, "to_dict") else result
        self._sync_status = f"{label}: concluído"
        self._append_sync_log(json.dumps(value, ensure_ascii=False, indent=2))
        self.syncChanged.emit()
        self._refresh_dashboard()
        self._load_knowledge()
        self._load_reviews()
        self._clear_review_selection()
        self._refresh_review_filter_values()
        self.toastRequested.emit(f"{label}: sincronização concluída.", "success")

    def _sync_failed(self, task: _Task, error: str) -> None:
        self._tasks.discard(task)
        self._sync_running = False
        self._sync_status = "Falha na sincronização"
        self._append_sync_log(error)
        self._append_log(error)
        self.syncChanged.emit()
        self._refresh_review_filter_values()
        self.toastRequested.emit(error, "error")

    @Slot(result=str)
    def chooseSchemaFile(self) -> str:  # noqa: N802
        selected, _ = QFileDialog.getOpenFileName(
            None,
            "Selecionar arquivo do Schema",
            str(self._schema_path.parent),
            "Schema Markdown (*.md *.markdown);;Arquivos de texto (*.txt);;Todos os arquivos (*.*)",
        )
        if selected:
            self._schema_path = Path(selected).resolve(strict=False)
            self._preferences.setValue("sync/schema_path", self._settings.relative_path(self._schema_path))
            self._preferences.sync()
            self.syncChanged.emit()
        return str(self._schema_path)

    def _default_schema_path(self) -> Path:
        stored = str(self._preferences.value("sync/schema_path", "") or "").strip()
        if stored:
            return self._settings.resolve_path(stored)
        return self._settings.root / "schema" / "schema.md"

    def _refresh_settings(self) -> None:
        movidesk_password = os.environ.get("MOVIDESK_PASSWORD", "")
        endoo_password = os.environ.get("ENDOO_PASSWORD", "")
        self._settings_values = {
            "root": str(self._settings.root),
            "movideskEmail": os.environ.get("MOVIDESK_EMAIL", ""),
            "movideskPassword": "",
            "movideskPasswordConfigured": bool(movidesk_password),
            "endooEmail": os.environ.get("ENDOO_EMAIL", ""),
            "endooPassword": "",
            "endooPasswordConfigured": bool(endoo_password),
            "interval": str(self._settings.sync_interval_minutes),
            "diagnostic": self._diagnostic_text(),
        }
        self.settingsChanged.emit()

    def _diagnostic_text(self) -> str:
        try:
            from ..ocr import OcrManager

            ocr_ready = OcrManager(self._settings.tesseract_dir).is_ready()
        except Exception:
            ocr_ready = False
        codex_ready = (self._settings.root / ".codex" / "config.toml").is_file()
        return f"Projeto Codex: {'OK' if codex_ready else 'não preparado'}\nTesseract por+eng: {'OK' if ocr_ready else 'não instalado'}"

    @Slot(result=str)
    def chooseKnowledgeRoot(self) -> str:  # noqa: N802
        selected = QFileDialog.getExistingDirectory(None, "Selecionar fonte de conhecimento VR", str(self._settings.root))
        return str(Path(selected).resolve()) if selected else ""

    @Slot(str, str, str, str, str, str)
    def saveSettings(self, root: str, movidesk_email: str, movidesk_password: str, endoo_email: str, endoo_password: str, interval: str) -> None:  # noqa: N802
        movidesk_secret = (
            movidesk_password
            if movidesk_password
            else os.environ.get("MOVIDESK_PASSWORD", "")
        )
        endoo_secret = (
            endoo_password if endoo_password else os.environ.get("ENDOO_PASSWORD", "")
        )
        values = {
            "VR_ROOT": root,
            "MOVIDESK_EMAIL": movidesk_email,
            "MOVIDESK_PASSWORD": movidesk_secret,
            "ENDOO_EMAIL": endoo_email,
            "ENDOO_PASSWORD": endoo_secret,
            "VR_SYNC_INTERVAL_MINUTES": interval,
            "VR_DEFAULT_EFFORT": self._settings.default_effort,
        }
        try:
            save_vr_env(self._settings.app_dir, values)
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        for key, value in values.items():
            os.environ[key] = str(value)
        self._settings_values.update({
            "root": root,
            "movideskEmail": movidesk_email,
            "movideskPassword": "",
            "movideskPasswordConfigured": bool(movidesk_secret),
            "endooEmail": endoo_email,
            "endooPassword": "",
            "endooPasswordConfigured": bool(endoo_secret),
            "interval": interval,
        })
        self.settingsChanged.emit()
        self.toastRequested.emit(
            "Configurações salvas. Credenciais e intervalo já estão ativos; reinicie apenas para aplicar mudanças de caminho.",
            "success",
        )

    @Slot()
    def refreshProviders(self) -> None:  # noqa: N802
        descriptions = {
            "codex": "Codex App Server local · modelos, tools e Build integrado",
            "claude": "Claude Code local · conversas e modelos Claude",
            "opencode": "OpenCode local · modelos e sessões via CLI",
            "antigravity": "Antigravity CLI · conta Google",
        }
        labels = {"codex": "Codex", "claude": "Claude", "opencode": "OpenCode", "antigravity": "Antigravity"}
        self._providers = []
        for provider in labels:
            enabled = self._stored_bool(self._preferences.value(f"providers/{provider}/enabled", True), True)
            command = resolve_acp() if provider == "antigravity" else resolve_cli(provider)
            available = command is not None
            auth_info = self._antigravity_auth.get_ui_snapshot() if (provider == "antigravity" and hasattr(self, "_antigravity_auth")) else {}
            account_status = auth_info.get("accountStatus", getattr(self, "_agy_account_status", "Conta Google ainda não verificada")) if provider == "antigravity" else "Autenticação gerenciada pelo CLI"
            checking = provider == "antigravity" and getattr(self, "_agy_check_running", False)
            if checking:
                account_status = "Validando conta Google…"
            self._providers.append({
                "id": provider,
                "name": str(self._preferences.value(f"providers/{provider}/displayName", labels[provider])),
                "command": command or "",
                "accountStatus": account_status,
                "attemptState": auth_info.get("attemptState", "idle"),
                "accountState": auth_info.get("accountState", "unknown"),
                "authUrl": auth_info.get("authUrl", ""),
                "expiresAt": auth_info.get("expiresAt", ""),
                "errorDetail": auth_info.get("errorDetail", ""),
                "isWaiting": auth_info.get("isWaiting", False),
                "isVerifying": checking or auth_info.get("isVerifying", False),
                "isStarting": auth_info.get("isStarting", False),
                "description": descriptions[provider],
                "enabled": enabled,
                "available": available,
                "installSupported": provider in INSTALLERS,
                "installDocs": INSTALL_DOCS.get(provider, ""),
                **self._provider_install_status.get(provider, {}),
                "status": "● Desativado para novas conversas" if not enabled else "● Disponível localmente" if available else "● Não encontrado no PATH",
            })
        self.providersChanged.emit()

    @Slot(str)
    def installProviderCli(self, provider: str) -> None:  # noqa: N802
        if self._closed or provider in self._provider_installs:
            return
        if provider not in INSTALLERS:
            self.toastRequested.emit("Este provedor não possui instalação integrada.", "warning")
            return
        # Fresh installs only; do not replace a binary serving live conversations.
        command = resolve_acp() if provider == "antigravity" else resolve_cli(provider)
        verify_only = bool(command)
        if command and self._provider_install_status.get(provider, {}).get("runtimeState") not in {"error", "cancelled"}:
            self.refreshProviders()
            self.toastRequested.emit("O CLI já está instalado nesta máquina.", "info")
            return
        cancel = threading.Event()
        self._provider_install_status[provider] = {"runtimeState": "installing", "installMessage": "Preparando instalação…"}

        def operation():
            try:
                if verify_only:
                    task.signals.progress.emit("Verificando o CLI já instalado…")
                    return verify_cli(provider, cancel)
                return install_cli(provider, cancel, task.signals.progress.emit)
            except InstallCancelled:
                return {"cancelled": True}

        task = _Task(operation)
        self._provider_installs[provider] = (task, cancel)
        self._tasks.add(task)

        def progress(message):
            if self._closed or self._provider_installs.get(provider, (None,))[0] is not task or cancel.is_set():
                return
            self._provider_install_status[provider]["installMessage"] = str(message)
            self.refreshProviders()

        def finish(result=None, error=""):
            self._tasks.discard(task)
            if self._provider_installs.get(provider, (None,))[0] is not task:
                return
            self._provider_installs.pop(provider)
            if self._closed:
                return
            if cancel.is_set() or (result or {}).get("cancelled"):
                status = {"runtimeState": "cancelled", "installMessage": "Instalação cancelada. Arquivos já instalados foram preservados."}
            elif error:
                status = {"runtimeState": "error", "installMessage": redact_sensitive_text(str(error))[:12000]}
            else:
                status = {"runtimeState": "installed", "installVersion": result["version"],
                          "installMessage": "CLI instalado e verificado. Entre na sua conta para usar nas conversas."}
                orchestrator = self._conversation_orchestrator
                runtime = orchestrator.providers.get(provider) if orchestrator else None
                if runtime is not None and hasattr(runtime, "command"):
                    runtime.command = result["command"]
            self._provider_install_status[provider] = status
            self.refreshProviders()
            if status["runtimeState"] == "installed":
                self.providerRuntimeInstalled.emit(provider)
            self.toastRequested.emit(status["installMessage"].splitlines()[0], "error" if error else "info")

        task.signals.progress.connect(progress)
        task.signals.finished.connect(finish)
        task.signals.failed.connect(lambda error: finish(error=error))
        self.refreshProviders()
        self._pool.start(task)

    @Slot(str)
    def cancelProviderInstall(self, provider: str) -> None:  # noqa: N802
        active = self._provider_installs.get(provider)
        if active:
            active[1].set()
            self._provider_install_status[provider]["installMessage"] = "Cancelando instalação…"
            self.refreshProviders()

    @Slot(str)
    def openProviderLogin(self, provider: str) -> None:  # noqa: N802
        if self._closed or provider in self._provider_installs or provider not in {"codex", "claude"}:
            return
        command = resolve_cli(provider)
        if not command:
            self.toastRequested.emit("Instale o CLI primeiro.", "warning")
            return
        if os.name != "nt":
            self.copyText("codex login" if provider == "codex" else "claude auth login")
            self.toastRequested.emit("Comando de login copiado. Execute-o no seu terminal.", "info")
            return
        # Interactive login needs a visible terminal; the executable path remains
        # data in an environment variable, never interpolated into shell code.
        env = dict(os.environ)
        env["VRSTUDIO_LOGIN_CLI"] = command
        args = "login" if provider == "codex" else "auth login"
        host = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        try:
            subprocess.Popen([str(host), "-NoLogo", "-NoProfile", "-NoExit", "-Command",
                              "& $env:VRSTUDIO_LOGIN_CLI " + args],
                             env=env, cwd=Path.home(), creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError:
            self.toastRequested.emit("Não foi possível abrir o terminal de login.", "error")

    @Slot(str, str)
    def setProviderDisplayName(self, provider: str, name: str) -> None:
        if provider not in {item["id"] for item in self._providers} or not name.strip():
            return
        self._preferences.setValue(f"providers/{provider}/displayName", name.strip()[:80])
        self._preferences.sync()
        self.refreshProviders()

    @Slot()
    def openAntigravityLogin(self) -> None:
        if getattr(self, "_agy_check_running", False) or self._closed:
            return
        try:
            command = resolve_acp()
            if not command:
                QDesktopServices.openUrl(QUrl("https://antigravity.google/docs/cli/install/"))
                return
            attempt = self._antigravity_auth.start_login()
            if attempt.state == "waiting" and attempt.validated_auth:
                self._agy_opened_attempt = attempt.attempt_id
                QDesktopServices.openUrl(QUrl(attempt.validated_auth.authorization_url))
            self.refreshProviders()
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")

    @Slot()
    def cancelAntigravityLogin(self) -> None:
        try:
            self._cancel_antigravity_check()
            if hasattr(self, "_antigravity_auth"):
                self._antigravity_auth.cancel_login()
            self.refreshProviders()
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")

    @Slot(str)
    def submitAntigravityCallback(self, callback_url: str) -> None:
        def do_submit():
            if hasattr(self, "_antigravity_auth"):
                self._antigravity_auth.submit_callback(callback_url)

        task = _Task(do_submit)
        self._tasks.add(task)
        def finish_error(exc):
            self._tasks.discard(task)
            if self._closed:
                return
            self.toastRequested.emit(f"Falha ao validar retorno OAuth: {exc}", "error")
            self.refreshProviders()
        def finish_success(_):
            self._tasks.discard(task)
            if self._closed:
                return
            self.refreshProviders()
        task.signals.failed.connect(finish_error)
        task.signals.finished.connect(finish_success)
        self._pool.start(task)

    def _cancel_antigravity_check(self) -> None:
        self._agy_check_cancel.set()
        if self._agy_check_client:
            self._agy_check_client.close()

    def _run_antigravity_check(self, command: str):
        if not has_saved_account():
            raise RuntimeError("Entre com Google primeiro.")
        if self._agy_check_cancel.is_set():
            raise RuntimeError("Validação cancelada.")
        client = AcpClient(command=command)
        self._agy_check_client = client
        try:
            if self._agy_check_cancel.is_set():
                raise RuntimeError("Validação cancelada.")
            client.start()
            client.request("authenticate", {"methodId": "oauth-personal"})
            if self._agy_check_cancel.is_set():
                raise RuntimeError("Validação cancelada.")
            # Authentication is already confirmed even if session/new fails.
            self._antigravity_auth.mark_authenticated_from_validation("Conta Google autenticada pelo Antigravity.")
            return client.request("session/new", {"cwd": str(Path.home()), "mcpServers": []})
        finally:
            client.close()
            self._agy_check_client = None

    @Slot()
    def validateAntigravityAccount(self) -> None:
        if getattr(self, "_agy_check_running", False) or self._closed:
            return
        attempt = self._antigravity_auth.active_attempt
        if attempt and attempt.state in ("starting", "waiting", "verifying"):
            return
        command = resolve_acp()
        if not command:
            self.toastRequested.emit("Instale o Antigravity CLI primeiro.", "warning")
            return
        self._agy_check_running = True
        self._agy_check_cancel.clear()
        checked_attempt = self._antigravity_auth.active_attempt
        checked_phase = checked_attempt.state if checked_attempt else "idle"
        self._agy_account_status = "Validando conta Google…"
        self.refreshProviders()
        def check():
            result = self._run_antigravity_check(command)
            models = (result.get("models") or {}).get("availableModels", [])
            if not result.get("sessionId") or not models:
                raise RuntimeError("Não foi possível carregar os modelos da conta.")
            return f"Conta Google autenticada. Conexão validada e {len(models)} modelos disponíveis."
        task = _Task(check)
        self._tasks.add(task)
        def finish_success(message):
            self._tasks.discard(task)
            self._agy_check_running = False
            if self._closed or self._agy_check_cancel.is_set() or self._antigravity_auth.active_attempt is not checked_attempt:
                if not self._closed:
                    self.refreshProviders()
                return
            if checked_attempt and checked_attempt.state in ("cancelled", "failed") and checked_attempt.state != checked_phase:
                self.refreshProviders()
                return
            self._agy_account_status = str(message)
            if hasattr(self, "_antigravity_auth"):
                self._antigravity_auth.mark_authenticated_from_validation(str(message))
            self.refreshProviders()
        def finish_error(exc):
            self._tasks.discard(task)
            self._agy_check_running = False
            if self._closed or self._agy_check_cancel.is_set() or self._antigravity_auth.active_attempt is not checked_attempt:
                if not self._closed:
                    self.refreshProviders()
                return
            if checked_attempt and checked_attempt.state in ("cancelled", "failed") and checked_attempt.state != checked_phase:
                self.refreshProviders()
                return
            # Exceptions may contain captured CLI output/URLs. Publish only a
            # fixed diagnostic, preserving any previously confirmed account.
            self._antigravity_auth.mark_session_or_model_error(
                "Não foi possível verificar a conta. Entre com Google ou tente validar novamente."
            )
            self.refreshProviders()
        task.signals.finished.connect(finish_success)
        task.signals.failed.connect(finish_error)
        self._pool.start(task)

    @Slot(str, bool)
    def setProviderEnabled(self, provider: str, enabled: bool) -> None:  # noqa: N802
        active = [item for item in self._providers if item["id"] != provider and item["enabled"]]
        if not enabled and not active:
            self.toastRequested.emit("Mantenha pelo menos um provedor ativo.", "warning")
            # Re-emit the authoritative model so the checkbox returns to the
            # enabled state after the rejected toggle.
            self.refreshProviders()
            return
        self._preferences.setValue(f"providers/{provider}/enabled", enabled)
        self._preferences.sync()
        self.refreshProviders()

    @Slot(str)
    def refreshArchived(self, search: str) -> None:  # noqa: N802
        term = str(search or "").strip().casefold()
        rows = []
        for row in self._database.list_conversations(state="archived"):
            workspace = self._settings.resolve_path(row["workspace"])
            title = str(row["title"] or "Nova conversa")
            project = workspace.name or str(workspace)
            if term and term not in f"{title} {project}".casefold():
                continue
            rows.append({
                "conversationId": str(row["id"]),
                "title": title,
                "project": project,
                "provider": str(row["provider"] or "").title(),
                "updatedAt": str(row["updated_at"] or ""),
            })
        self._archived.replace(rows)
        self.archivedChanged.emit()

    @Slot(str)
    def restoreArchived(self, conversation_id: str) -> None:  # noqa: N802
        try:
            self._chat_orchestrator().unarchive(conversation_id)
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        self.refreshArchived("")
        self.conversationRestored.emit(conversation_id)
        self.toastRequested.emit("Conversa restaurada.", "success")

    @Slot(str)
    def purgeArchived(self, conversation_id: str) -> None:  # noqa: N802
        try:
            self._chat_orchestrator().purge(conversation_id)
        except Exception as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        self.refreshArchived("")
        self.toastRequested.emit("Conversa excluída definitivamente.", "success")

    def _chat_orchestrator(self) -> Any:
        if self._conversation_orchestrator is None:
            from ..orchestrator import ChatOrchestrator

            self._conversation_orchestrator = ChatOrchestrator(
                self._settings, self._database
            )
        return self._conversation_orchestrator

    @Slot(str)
    def openLocalPath(self, value: str) -> None:  # noqa: N802
        path = Path(str(value or "")).expanduser().resolve(strict=False)
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.toastRequested.emit("O arquivo local não foi encontrado.", "warning")

    @Slot(str)
    def openExternalUrl(self, value: str) -> None:  # noqa: N802
        url = QUrl.fromUserInput(str(value or "").strip())
        if not url.isValid() or url.scheme().casefold() not in {"http", "https"}:
            self.toastRequested.emit("Digite um endereço http ou https válido.", "warning")
            return
        QDesktopServices.openUrl(url)

    @Slot()
    def openVrInCodex(self) -> None:  # noqa: N802
        try:
            from ..indexer import export_catalog
            from ..portable_project import ensure_portable_project

            result = ensure_portable_project(self._settings.root)
            export_catalog(self._database, self._settings.index_dir)
        except Exception as exc:
            self.toastRequested.emit(
                f"Não foi possível preparar o projeto Codex: {exc}", "error"
            )
            return
        executable = shutil.which("codex")
        if not executable:
            self.toastRequested.emit(
                "Codex não foi encontrado no PATH. Instale e autentique o Codex nesta máquina.",
                "error",
            )
            return
        started = QProcess.startDetached(
            executable,
            ["app", str(result.root)],
            str(result.root),
        )
        success = started[0] if isinstance(started, tuple) else bool(started)
        if not success:
            self.toastRequested.emit(
                "O Codex foi encontrado, mas não foi possível abri-lo.", "error"
            )

    @Slot(str)
    def runTerminalCommand(self, command: str) -> None:  # noqa: N802
        value = str(command or "").strip()
        if not value:
            return
        if self._terminal_process and self._terminal_process.state() != QProcess.NotRunning:
            self.toastRequested.emit("Já existe um comando em execução.", "warning")
            return
        self._terminal_process = QProcess(self)
        self._terminal_output = f"> {redact_sensitive_text(value)}\n"
        self._terminal_process.setWorkingDirectory(str(self._settings.root))
        self._terminal_process.setProcessChannelMode(QProcess.MergedChannels)
        self._terminal_process.readyReadStandardOutput.connect(self._read_terminal_output)
        self._terminal_process.finished.connect(self._terminal_finished)
        self._terminal_process.finished.connect(self._terminal_process.deleteLater)
        self._append_log(f"> {value}")
        if sys.platform == "win32":
            self._terminal_process.start("powershell.exe", ["-NoProfile", "-Command", value])
        else:
            self._terminal_process.start("sh", ["-lc", value])
        self.terminalChanged.emit()

    @Slot()
    def stopTerminalCommand(self) -> None:  # noqa: N802
        process = self._terminal_process
        if not process or process.state() == QProcess.NotRunning:
            return
        process.terminate()
        QTimer.singleShot(2000, lambda: self._kill_process_if_running(process))

    def _read_terminal_output(self) -> None:
        if not self._terminal_process:
            return
        value = bytes(self._terminal_process.readAllStandardOutput()).decode(
            "utf-8", "replace"
        )
        if not value:
            return
        self._terminal_output = _bounded_text(
            self._terminal_output, redact_sensitive_text(value)
        )
        self._append_log(value.rstrip())
        self.terminalChanged.emit()

    def _terminal_finished(self, code: int, _status: Any) -> None:
        self._terminal_process = None
        self._terminal_output = _bounded_text(
            self._terminal_output, f"\n[processo finalizado · código {code}]"
        )
        self.terminalChanged.emit()
        self.toastRequested.emit(
            f"Comando concluído · código {code}",
            "success" if code == 0 else "error",
        )

    @Slot()
    def close(self) -> None:
        """Stop owned processes before the QML engine and event loop disappear."""

        if self._closed:
            return
        self._closed = True
        for _task, cancel in self._provider_installs.values():
            cancel.set()
        self._cancel_antigravity_check()
        if hasattr(self, "_antigravity_auth"):
            self._antigravity_auth.cancel_login()
        self._video_output_timer.stop()
        for process in (self._terminal_process, self._video_process):
            if not process or process.state() == QProcess.NotRunning:
                continue
            process.terminate()
            if not process.waitForFinished(1200):
                process.kill()
                process.waitForFinished(800)
        self._terminal_process = None
        self._video_process = None

    @Slot(str)
    def copyText(self, value: str) -> None:  # noqa: N802
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app:
            app.clipboard().setText(value)
            self.toastRequested.emit("Copiado para a área de transferência.", "success")

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        value = redact_sensitive_text(message)
        if len(value) > MAX_LOG_ENTRY_CHARS:
            value = "[...entrada truncada...]\n" + value[-MAX_LOG_ENTRY_CHARS:]
        self._log_lines.append(f"[{timestamp}] {value}")
        self._log_lines = self._log_lines[-MAX_LOG_LINES:]
        self._log_model.append(self._log_lines[-1])
        self.logsChanged.emit()

    @staticmethod
    def _stored_bool(value: object, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() not in {"", "0", "false", "no", "off"}

"""Read-only presentation models for the first QML Chat VR migration slice."""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    QSettings,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from ..brand import ORGANIZATION_NAME, SETTINGS_APP_NAME
from ..config import MarySettings
from ..db import MaryDatabase
from ..models import ModelRef, OrchestrationOptions, RuntimeEvent
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


def markdown_for_display(markdown: str) -> str:
    """Repair provider spacing without changing inline code or URLs."""

    parts = _CODE_OR_URL_RE.split(str(markdown or ""))
    return "".join(
        part if index % 2 else _GLUED_SENTENCE_RE.sub(" ", part)
        for index, part in enumerate(parts)
    )


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
    )


class MessageListModel(_MappingListModel):
    ROLE_NAMES = (
        "messageId",
        "role",
        "content",
        "displayContent",
        "createdAt",
        "responseMode",
    )


class ChatBridge(QObject):
    """Expose existing conversation reads without changing domain behavior."""

    conversationsChanged = Signal()
    selectionChanged = Signal()
    searchChanged = Signal()
    projectsChanged = Signal()
    messageCopied = Signal(str)
    stateChanged = Signal()
    approvalRequested = Signal("QVariantMap")
    _modelsLoaded = Signal(object)
    _extensionsLoaded = Signal(object)

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
        self._search = ""
        self._selected_index = -1
        self._selected: dict[str, Any] = {}
        self._draft = False
        self._turn_running = False
        self._status_text = "Pronto"
        self._streaming_text = ""
        self._displayed_streaming_text = ""
        self._stream_pending_text = ""
        self._stream_terminal_kind = ""
        self._assistant_stream_started = False
        self._approval_request: dict[str, Any] = {}
        self._activity_steps: list[dict[str, str]] = []
        self._activity_items: list[dict[str, str]] = []
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
        self._model_items: list[dict[str, Any]] = []
        self._favorite_model_keys = self._load_favorite_model_keys()
        self._model_catalog_loading = False
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
        self._vr_enabled = True
        self._orchestration = self._load_default_orchestration()
        self._attachments: list[dict[str, str]] = []
        self._extension_items: list[dict[str, Any]] = []
        self._selected_extension_keys: set[str] = set()
        self._extensions_loading = False
        self._modelsLoaded.connect(self._apply_model_catalog)
        self._extensionsLoaded.connect(self._apply_extension_catalog)
        self._runtimeEvent.connect(self._on_runtime_event)
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
        return self._turn_running

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:  # noqa: N802
        return self._status_text

    @Property(bool, notify=stateChanged)
    def vrEnabled(self) -> bool:  # noqa: N802
        return self._vr_enabled

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

    @Property("QVariantList", constant=True)
    def orchestrationModes(self) -> list[dict[str, str]]:  # noqa: N802
        return [
            {"label": "Desligado", "value": "off"},
            {"label": "Automático", "value": "automatic"},
            {"label": "Ligado", "value": "standard"},
            {"label": "Ultra", "value": "ultra"},
        ]

    @Property("QVariantList", constant=True)
    def orchestrationStrategies(self) -> list[dict[str, str]]:  # noqa: N802
        return [
            {"label": "Automática", "value": "automatic"},
            {"label": "Adaptativa", "value": "adaptive"},
            {"label": "Paralela", "value": "parallel"},
            {"label": "Especializada", "value": "specialized"},
            {"label": "Sequencial", "value": "sequential"},
            {"label": "Debate", "value": "debate"},
            {"label": "Consenso", "value": "consensus"},
        ]

    @Property(str, notify=stateChanged)
    def orchestrationMode(self) -> str:  # noqa: N802
        return self._orchestration.mode

    @Property(str, notify=stateChanged)
    def orchestrationModeLabel(self) -> str:  # noqa: N802
        labels = {item["value"]: item["label"] for item in self.orchestrationModes}
        return labels.get(self._orchestration.mode, "Automático")

    @Property(str, notify=stateChanged)
    def orchestrationStrategy(self) -> str:  # noqa: N802
        return self._orchestration.strategy

    @Property(bool, notify=stateChanged)
    def orchestrationShowExecution(self) -> bool:  # noqa: N802
        return self._orchestration.show_execution

    @Property(bool, notify=stateChanged)
    def orchestrationExplainRouting(self) -> bool:  # noqa: N802
        return self._orchestration.explain_routing

    @Property(bool, notify=stateChanged)
    def orchestrationDynamicModels(self) -> bool:  # noqa: N802
        return self._orchestration.dynamic_model_routing

    @Property(bool, notify=stateChanged)
    def orchestrationDynamicAgents(self) -> bool:  # noqa: N802
        return self._orchestration.dynamic_agent_count

    @Property(bool, notify=stateChanged)
    def orchestrationDifficultyRouting(self) -> bool:  # noqa: N802
        return self._orchestration.difficulty_routing

    @Property("QVariantList", notify=stateChanged)
    def orchestrationPoolKeys(self) -> list[str]:  # noqa: N802
        return [model.key for model in self._orchestration.model_pool]

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
        if row is None:
            return 0.0
        used = int(row["context_used_tokens"] or 0)
        window = int(row["context_window_tokens"] or 0)
        return min(1.0, used / window) if window else 0.0

    @Property(str, notify=stateChanged)
    def contextUsageLabel(self) -> str:  # noqa: N802
        row = self._selected_database_row()
        if row is None:
            return "Aguardando dados"
        used = int(row["context_used_tokens"] or 0)
        window = int(row["context_window_tokens"] or 0)
        if not window:
            return "Aguardando dados"
        return f"{used:,} / {window:,} tokens".replace(",", ".")

    @Property(str, notify=stateChanged)
    def contextUsageCompactLabel(self) -> str:  # noqa: N802
        row = self._selected_database_row()
        if row is None:
            return "Aguardando dados"
        used = int(row["context_used_tokens"] or 0)
        window = int(row["context_window_tokens"] or 0)
        if not window:
            return "Aguardando dados"
        percentage = min(100, round(used * 100 / window))
        return f"{percentage}% · {self._compact_tokens(used)}/{self._compact_tokens(window)}"

    @Property(str, notify=stateChanged)
    def contextUsageNote(self) -> str:  # noqa: N802
        item = self._current_model_item()
        model_name = str(item.get("displayName") or self._model or "modelo")
        return f"O contexto de {model_name} é compactado automaticamente quando necessário."

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
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    @Property("QVariantList", notify=stateChanged)
    def agentItems(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._agent_items]

    def _selected_database_row(self) -> Any:
        conversation_id = str(self._selected.get("conversationId") or "")
        return self._database.get_conversation(conversation_id) if conversation_id else None

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
            return efforts
        return (
            ["low", "medium", "high", "xhigh", "max"]
            if self._provider == "claude"
            else ["minimal", "low", "medium", "high", "xhigh", "max"]
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
            preferred = "medium" if "medium" in supported else supported[0]
        self._effort = preferred

    def _reset_model_items(self) -> None:
        enabled = self._enabled_provider_names()
        provider = self._provider if self._provider in enabled else enabled[0]
        self._provider = provider
        label = self._model or PROVIDER_LABELS.get(provider, provider.title())
        self._model_items = [{
            "label": label,
            "displayName": label,
            "value": self._model,
            "provider": provider,
            "providerLabel": PROVIDER_LABELS.get(provider, provider.title()),
            "description": "Última seleção disponível",
            "key": f"{provider}:{self._model or '__default__'}",
        }]

    @Slot()
    def refreshModels(self) -> None:  # noqa: N802
        if self._model_catalog_loading:
            return
        self._model_catalog_loading = True
        self.stateChanged.emit()

        def load() -> None:
            items: list[dict[str, Any]] = []
            for provider_name in self._enabled_provider_names():
                provider = self._orchestrator.providers.get(provider_name)
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
                    })
            self._modelsLoaded.emit(items)

        threading.Thread(target=load, daemon=True).start()

    @Slot(object)
    def _apply_model_catalog(self, values: object) -> None:
        items = [dict(item) for item in list(values or []) if isinstance(item, dict)]
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
                items.insert(0, dict(current))
        self._model_items = items or self._model_items
        self._restore_effort_for_current_model()
        if not self.serviceTierItems:
            self._service_tier = ""
        self._model_catalog_loading = False
        self.stateChanged.emit()

    @Slot(int)
    def setModel(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._model_items) or self._turn_running:
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

    def _load_default_orchestration(self) -> OrchestrationOptions:
        def boolean(key: str, default: bool) -> bool:
            raw = self._preferences.value(key, default)
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().casefold() not in {"", "0", "false", "no", "off"}

        raw_models = self._preferences.value("orchestration/available_models", "[]")
        try:
            values = json.loads(str(raw_models or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        return OrchestrationOptions(
            mode=str(self._preferences.value("orchestration/mode", "automatic") or "automatic"),
            strategy=str(self._preferences.value("orchestration/strategy", "automatic") or "automatic"),
            model_pool=tuple(ModelRef.from_mapping(item) for item in values if isinstance(item, dict)),
            show_execution=boolean("orchestration/show_execution", True),
            explain_routing=boolean("orchestration/explain_routing", False),
            dynamic_model_routing=boolean("orchestration/dynamic_model_routing", True),
            dynamic_agent_count=boolean("orchestration/dynamic_agent_count", True),
            difficulty_routing=boolean("orchestration/difficulty_routing", True),
        )

    def _save_default_orchestration(self) -> None:
        options = self._orchestration
        self._preferences.setValue("orchestration/mode", options.mode)
        self._preferences.setValue("orchestration/strategy", options.strategy)
        self._preferences.setValue("orchestration/show_execution", options.show_execution)
        self._preferences.setValue("orchestration/explain_routing", options.explain_routing)
        self._preferences.setValue("orchestration/dynamic_model_routing", options.dynamic_model_routing)
        self._preferences.setValue("orchestration/dynamic_agent_count", options.dynamic_agent_count)
        self._preferences.setValue("orchestration/difficulty_routing", options.difficulty_routing)
        self._preferences.setValue(
            "orchestration/available_models",
            json.dumps([model.to_dict() for model in options.model_pool], ensure_ascii=False),
        )
        self._preferences.sync()

    def _apply_orchestration(self) -> None:
        conversation_id = str(self._selected.get("conversationId") or "")
        if conversation_id:
            self._orchestrator.update_orchestration(conversation_id, self._orchestration)
        else:
            self._save_default_orchestration()
        self.stateChanged.emit()

    @Slot(str)
    def setOrchestrationMode(self, mode: str) -> None:  # noqa: N802
        current = self._orchestration
        self._orchestration = OrchestrationOptions(
            mode=str(mode or "automatic"),
            strategy=current.strategy,
            model_pool=current.model_pool,
            show_execution=current.show_execution,
            explain_routing=current.explain_routing,
            dynamic_model_routing=current.dynamic_model_routing,
            dynamic_agent_count=current.dynamic_agent_count,
            difficulty_routing=current.difficulty_routing,
        )
        self._apply_orchestration()

    @Slot(str, bool, bool, bool, bool, bool, "QVariantList")
    def saveOrchestrationSettings(  # noqa: N802
        self,
        strategy: str,
        show_execution: bool,
        explain_routing: bool,
        dynamic_models: bool,
        dynamic_agents: bool,
        difficulty_routing: bool,
        pool_keys: list[Any],
    ) -> None:
        wanted = {str(value) for value in pool_keys}
        pool = tuple(
            ModelRef(
                provider=str(item.get("provider") or ""),
                model=str(item.get("value") or ""),
                display_name=str(item.get("label") or ""),
                description=str(item.get("description") or ""),
            )
            for item in self._model_items
            if str(item.get("key") or "") in wanted and item.get("provider")
        )
        current = self._orchestration
        self._orchestration = OrchestrationOptions(
            mode=current.mode,
            strategy=str(strategy or "automatic"),
            model_pool=pool,
            show_execution=show_execution,
            explain_routing=explain_routing,
            dynamic_model_routing=dynamic_models,
            dynamic_agent_count=dynamic_agents,
            difficulty_routing=difficulty_routing,
        )
        self._apply_orchestration()

    @Slot(result="QVariantList")
    def chooseAttachments(self) -> list[dict[str, str]]:  # noqa: N802
        selected, _ = QFileDialog.getOpenFileNames(
            None,
            "Adicionar arquivos à conversa",
            str(self._project_scope or self._settings.root),
            "Arquivos suportados (*.png *.jpg *.jpeg *.webp *.gif *.md *.txt *.json *.csv *.pdf);;Todos os arquivos (*.*)",
        )
        known = {item["path"] for item in self._attachments}
        for raw in selected:
            path = Path(raw).resolve(strict=False)
            if str(path) in known:
                continue
            self._attachments.append({"name": path.name, "path": str(path)})
            known.add(str(path))
        if selected:
            self.stateChanged.emit()
        return self.attachments

    @Slot(int)
    def removeAttachment(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self._attachments):
            self._attachments.pop(index)
            self.stateChanged.emit()

    @Slot(str, result="QVariantList")
    def fileSuggestions(self, query: str) -> list[dict[str, str]]:  # noqa: N802
        root = self._project_scope or self._settings.root
        if not root.is_dir():
            return []
        needle = str(query or "").strip().casefold()
        ignored = {".git", ".venv", "__pycache__", "node_modules", ".state"}
        results: list[dict[str, str]] = []
        try:
            for path in root.rglob("*"):
                if any(part in ignored for part in path.parts) or not path.is_file():
                    continue
                relative = str(path.relative_to(root)).replace("\\", "/")
                if needle and needle not in relative.casefold():
                    continue
                results.append({"label": relative, "path": str(path)})
                if len(results) >= 40:
                    break
        except OSError:
            return []
        return results

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
        if self._extensions_loading:
            return
        self._extensions_loading = True
        self.stateChanged.emit()
        provider_name = self._provider
        workspace = self._project_scope or self._settings.root

        def load() -> None:
            values: list[dict[str, Any]] = []
            try:
                skill_result = self._orchestrator.skills(provider_name, workspace)
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
                tools = self._orchestrator.mcp_tools(provider_name)
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
            self._extensionsLoaded.emit(values)

        threading.Thread(target=load, daemon=True).start()

    @Slot(object)
    def _apply_extension_catalog(self, values: object) -> None:
        self._extension_items = [
            dict(item) for item in list(values or []) if isinstance(item, dict)
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
        selected_id = str(self._selected.get("conversationId") or "")
        conversations: list[dict[str, Any]] = []
        for row in self._database.list_conversations(state="active"):
            workspace = self._settings.resolve_path(row["workspace"])
            project_label = (
                "Projeto temporário"
                if is_managed_conversation_workspace(self._settings, workspace)
                else (workspace.name or str(workspace))
            )
            provider = str(row["provider"] or "codex")
            status = str(row["status"] or "idle")
            provider_label = PROVIDER_LABELS.get(provider, provider.title())
            model_name = str(row["model"] or provider_label)
            conversations.append(
                {
                    "conversationId": str(row["id"]),
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
                }
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
        self._preferences.setValue("chat/current_project", raw_path)
        self._preferences.sync()
        self.projectsChanged.emit()
        if self._draft:
            self.selectionChanged.emit()
        self._apply_filter(selected_id)

    @Slot()
    def startNewChat(self) -> None:  # noqa: N802
        if self._turn_running:
            return
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
        self._vr_enabled = self._stored_bool(
            self._preferences.value("chat/vr_flow_enabled", True), True
        )
        self._orchestration = self._load_default_orchestration()
        self._attachments = []
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
            self._activity_steps = []
            self._activity_items = []
            self._reasoning_text = ""
            self._activity_elapsed_seconds = 0
            self._agent_items = []
        self._selected_index = index
        self._selected = dict(selected)
        row = self._database.get_conversation(str(selected["conversationId"]))
        if row is not None:
            self._provider = str(row["provider"] or "codex")
            self._model = str(row["model"] or "")
            self._effort = str(row["effort"] or "medium")
            self._service_tier = str(row["service_tier"] or "")
            self._approval_profile = str(row["approval_profile"] or "auto")
            self._vr_enabled = bool(row["vr_enabled"])
            self._orchestration = OrchestrationOptions.from_mapping(
                row,
                tuple(
                    self._database.conversation_model_pool(
                        str(selected["conversationId"])
                    )
                ),
            )
            self._remember_current_chat_options()
        if changing_conversation:
            self._restore_activity_from_history(str(selected["conversationId"]))
        self._reload_selected_messages()
        self.stateChanged.emit()

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

    @Slot()
    def toggleVr(self) -> None:  # noqa: N802
        self._vr_enabled = not self._vr_enabled
        self._preferences.setValue("chat/vr_flow_enabled", self._vr_enabled)
        self._preferences.sync()
        if self._selected:
            self._database.update_conversation(
                str(self._selected["conversationId"]), vr_enabled=int(self._vr_enabled)
            )
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
        path = Path(selected).resolve(strict=False)
        raw = self._preferences.value("chat/projects", "[]")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else list(raw or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        stored = [item.get("path", "") if isinstance(item, dict) else item for item in values]
        if str(path) not in stored:
            values.append({"path": str(path)})
            self._preferences.setValue("chat/projects", json.dumps(values, ensure_ascii=False))
            self._preferences.sync()
        self._refresh_projects()
        target = next(
            (index for index, item in enumerate(self._projects) if item["path"] == str(path)),
            0,
        )
        self.setProject(target)
        return str(path)

    @Slot(str)
    def sendMessage(self, text: str) -> None:  # noqa: N802
        content = str(text or "").strip()
        if not content or self._turn_running:
            return
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
                    orchestration=self._orchestration,
                    vr_enabled=self._vr_enabled,
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
        file_references = " ".join(
            f'@"{item["path"]}"'
            for item in self._attachments
            if item["path"] not in image_paths
        )
        provider_text = " ".join(value for value in (file_references, content) if value)
        self._turn_running = True
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
                "createdAt": "",
                "responseMode": "vr" if self._vr_enabled else "native",
            }
        )
        self._messages.append(self._activity_timeline_item())
        self.stateChanged.emit()
        self.selectionChanged.emit()
        try:
            self._orchestrator.send(
                conversation_id,
                provider_text,
                self._runtimeEvent.emit,
                skills,
                content,
                content,
                self._vr_enabled,
                image_paths=image_paths,
            )
            self._attachments = []
            self._selected_extension_keys = set()
            self.stateChanged.emit()
        except Exception as exc:
            self._turn_running = False
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()

    @Slot()
    def stopTurn(self) -> None:  # noqa: N802
        conversation_id = str(self._selected.get("conversationId") or "")
        if not conversation_id or not self._turn_running:
            return
        self._status_text = "Parando…"
        self.stateChanged.emit()

        def interrupt() -> None:
            try:
                self._orchestrator.interrupt(conversation_id)
            except Exception as exc:
                self._runtimeEvent.emit(
                    RuntimeEvent(conversation_id, "error", str(exc))
                )

        threading.Thread(target=interrupt, daemon=True).start()

    @Slot()
    def archiveCurrentConversation(self) -> None:  # noqa: N802
        conversation_id = str(self._selected.get("conversationId") or "")
        if not conversation_id or self._turn_running:
            return
        try:
            self._orchestrator.archive(conversation_id)
        except Exception as exc:
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()
            return
        self.refresh()
        self.startNewChat()

    @Slot()
    def trashCurrentConversation(self) -> None:  # noqa: N802
        conversation_id = str(self._selected.get("conversationId") or "")
        if not conversation_id or self._turn_running:
            return
        try:
            self._orchestrator.trash(conversation_id)
        except Exception as exc:
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()
            return
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
        selected_id = str(self._selected.get("conversationId") or "")
        if event.conversation_id != selected_id:
            if event.kind in {"turn_completed", "error"}:
                self.refresh()
            return
        self._record_execution_event(event)
        if event.kind == "assistant_delta":
            delta = str(event.text or "")
            if not delta:
                return
            self._streaming_text += delta
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
            self._status_text = (
                "Executando uma ação…"
                if event.kind == "tool_event"
                else event.text or "Trabalhando…"
            )
            self.stateChanged.emit()
        elif event.kind in {"turn_completed", "orchestration_completed"}:
            self._queue_terminal_state(event.kind)
        elif event.kind in {"error", "orchestration_cancelled"}:
            self._queue_terminal_state(event.kind)

    def _ensure_streaming_message(self) -> None:
        if self._messages._items and self._messages._items[-1].get("role") == "assistant":
            return
        self._messages.append(
            {
                "messageId": -1,
                "role": "assistant",
                "content": self._streaming_text,
                "displayContent": "",
                "createdAt": "",
                "responseMode": "vr" if self._vr_enabled else "native",
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
            )
            return
        self._stream_timer.stop()
        if self._stream_terminal_kind:
            terminal_kind = self._stream_terminal_kind
            self._stream_terminal_kind = ""
            self._finalize_terminal_state(terminal_kind)

    def _queue_terminal_state(self, kind: str) -> None:
        if (
            not self._turn_running
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
        self._turn_running = False
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
        self._reasoning_text = ""
        self._activity_elapsed_seconds = 0
        rows = self._database.latest_turn_events(conversation_id)
        if not rows:
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
                    "text": label,
                    "detail": detail,
                    "state": state,
                }
            )
            self._activity_items = self._activity_items[-60:]
            return
        existing["text"] = label or existing.get("text", "Ferramenta")
        existing["state"] = state
        if detail:
            existing["detail"] = detail

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
        self._messages.replace(items)
        self.selectionChanged.emit()

    @staticmethod
    def _activity_timeline_item() -> dict[str, Any]:
        return {
            "messageId": -2,
            "role": "activity",
            "content": "",
            "displayContent": "",
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
        self._selected_index = -1
        self._selected = {}
        self._messages.replace([])
        if changed:
            self.selectionChanged.emit()

    def _refresh_projects(self) -> None:
        saved_scope = str(
            self._preferences.value("chat/current_project", "") or ""
        ).strip()
        candidates: list[Path] = []

        def include(value: object) -> None:
            raw = str(value or "").strip()
            if not raw:
                return
            candidate = Path(raw).expanduser().resolve(strict=False)
            if candidate.is_dir() and candidate not in candidates:
                candidates.append(candidate)

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
                include(value.get("path", "") if isinstance(value, dict) else value)

        for row in self._database.list_conversations(state="all"):
            workspace = self._settings.resolve_path(row["workspace"])
            if not is_managed_conversation_workspace(self._settings, workspace):
                include(workspace)

        self._projects = [{"label": "Todos os projetos", "path": ""}]
        self._projects.extend(
            {"label": path.name or str(path), "path": str(path)}
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

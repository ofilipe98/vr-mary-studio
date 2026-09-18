from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QSettings
from PySide6.QtWidgets import QFileDialog

from ..config import MarySettings
from ..settings_service import (
    get_settings_values,
    save_settings,
    mark_setup_completed,
)


class BootstrapBridge(QObject):
    """Coordinates application startup, initial setup gating, and catalog loading."""

    stateChanged = Signal()
    phaseChanged = Signal()
    statusMessageChanged = Signal()
    detailMessageChanged = Signal()
    errorMessageChanged = Signal()
    progressChanged = Signal()
    toastRequested = Signal(str, str)
    setupCompleted = Signal(object)

    def __init__(
        self,
        settings: MarySettings | None,
        preferences: QSettings | None = None,
        *,
        initial_state: str = "ready",
        on_setup_completed: Callable[[MarySettings], None] | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._preferences = preferences
        self._on_setup_completed = on_setup_completed
        self._state = initial_state  # boot, check_setup, setup, initializing, loading_apps, loading_versions, ready, error
        self._phase = "idle"
        self._status_message = "Preparando seu ambiente" if initial_state != "setup" else "Configuração Inicial"
        self._detail_message = "Inicializando..." if initial_state != "setup" else "Preencha as configurações essenciais para prosseguir."
        self._error_message = ""
        self._apps_count = 0
        self._versions_count = 0
        self._is_ready = initial_state == "ready"
        self._chat_bridge: Any = None
        self._settings_values: dict[str, Any] = (
            get_settings_values(settings) if settings is not None else {}
        )

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    @Property(str, notify=phaseChanged)
    def phase(self) -> str:
        return self._phase

    @Property(str, notify=statusMessageChanged)
    def statusMessage(self) -> str:  # noqa: N802
        return self._status_message

    @Property(str, notify=detailMessageChanged)
    def detailMessage(self) -> str:  # noqa: N802
        return self._detail_message

    @Property(str, notify=errorMessageChanged)
    def errorMessage(self) -> str:  # noqa: N802
        return self._error_message

    @Property(int, notify=progressChanged)
    def appsCount(self) -> int:  # noqa: N802
        return self._apps_count

    @Property(int, notify=progressChanged)
    def versionsCount(self) -> int:  # noqa: N802
        return self._versions_count

    @Property(bool, notify=stateChanged)
    def isReady(self) -> bool:  # noqa: N802
        return self._is_ready

    @Property(bool, notify=stateChanged)
    def isSetupActive(self) -> bool:  # noqa: N802
        return self._state == "setup"

    @Property(bool, notify=stateChanged)
    def isBusy(self) -> bool:  # noqa: N802
        return self._state in ("initializing", "loading_apps", "loading_versions")

    @Property("QVariantMap", notify=stateChanged)
    def settingsValues(self) -> dict[str, Any]:  # noqa: N802
        return self._settings_values

    # -------------------------------------------------------------------------
    # Setup Gating & Configuration Slots
    # -------------------------------------------------------------------------

    @Slot(result=str)
    def chooseKnowledgeRoot(self) -> str:  # noqa: N802
        initial_dir = str(self._settings.root) if self._settings and self._settings.root else ""
        selected = QFileDialog.getExistingDirectory(
            None,
            "Selecionar diretório local do VRStudio",
            initial_dir,
        )
        return str(Path(selected).resolve()) if selected else ""

    @Slot(str, str, str, str, str, str)
    def saveSetup(  # noqa: N802
        self,
        root: str,
        movidesk_email: str,
        movidesk_password: str,
        endoo_email: str,
        endoo_password: str,
        interval: str,
    ) -> None:
        if self._settings is None:
            self._error_message = "Configuração do aplicativo não disponível."
            self.errorMessageChanged.emit()
            return

        try:
            new_settings, safe_values = save_settings(
                self._settings,
                root,
                movidesk_email,
                movidesk_password,
                endoo_email,
                endoo_password,
                interval,
            )
        except Exception as exc:
            self._error_message = str(exc)
            self.errorMessageChanged.emit()
            self.toastRequested.emit(f"Configuração inválida: {exc}", "error")
            return

        self._settings = new_settings
        self._settings_values = safe_values
        self._error_message = ""
        self.errorMessageChanged.emit()

        mark_setup_completed(self._preferences)
        self.toastRequested.emit("Configuração inicial salva com sucesso.", "success")
        self.setupCompleted.emit(new_settings)

        if self._on_setup_completed is not None:
            self._on_setup_completed(new_settings)

    @Slot()
    def openSetup(self) -> None:  # noqa: N802
        self._state = "setup"
        self._is_ready = False
        self._status_message = "Configuração Inicial"
        self._detail_message = "Ajuste os parâmetros necessários para continuar."
        if self._settings is not None:
            self._settings_values = get_settings_values(self._settings)
        self.stateChanged.emit()
        self.statusMessageChanged.emit()
        self.detailMessageChanged.emit()

    # -------------------------------------------------------------------------
    # Catalog Bootstrap Lifecycle
    # -------------------------------------------------------------------------

    def attach_chat_bridge(self, chat_bridge: Any) -> None:
        self._chat_bridge = chat_bridge
        if hasattr(chat_bridge, "applicationsCatalogPhase"):
            chat_bridge.applicationsCatalogPhase.connect(
                self._on_catalog_phase,
                Qt.ConnectionType.QueuedConnection,
            )
        if hasattr(chat_bridge, "_applicationsLoaded"):
            chat_bridge._applicationsLoaded.connect(
                self._on_catalog_loaded_payload,
                Qt.ConnectionType.QueuedConnection,
            )

    def start_bootstrap(self) -> None:
        self._state = "loading_apps"
        self._is_ready = False
        self._error_message = ""
        self._status_message = "Preparando seu ambiente"
        self._detail_message = "Detectando aplicativos…"
        self.stateChanged.emit()
        self.statusMessageChanged.emit()
        self.detailMessageChanged.emit()
        self.errorMessageChanged.emit()

        if self._chat_bridge is not None:
            self._chat_bridge.refreshApplicationsCatalog()
        else:
            self.set_ready()

    def set_ready(self) -> None:
        self._state = "ready"
        self._phase = "ready"
        self._is_ready = True
        self._status_message = "Pronto"
        self._detail_message = "Abrindo VRStudio…"
        self.stateChanged.emit()
        self.phaseChanged.emit()
        self.statusMessageChanged.emit()
        self.detailMessageChanged.emit()

    @Slot()
    def retryBootstrap(self) -> None:  # noqa: N802
        self._error_message = ""
        self.errorMessageChanged.emit()
        self.start_bootstrap()

    def _on_catalog_phase(self, phase: str, apps_count: int, versions_count: int) -> None:
        # Ignore updates if we are already in ready state (e.g. in-app refreshes from Main UI)
        if self._is_ready and self._state == "ready":
            return

        self._phase = phase
        self.phaseChanged.emit()

        if phase == "detecting_apps":
            self._state = "loading_apps"
            self._status_message = "Preparando seu ambiente"
            self._detail_message = "Detectando aplicativos…"
            self.stateChanged.emit()
            self.statusMessageChanged.emit()
            self.detailMessageChanged.emit()

        elif phase == "loading_versions":
            self._state = "loading_versions"
            self._apps_count = apps_count
            self._status_message = "Preparando seu ambiente"
            self._detail_message = (
                f"{apps_count} aplicativos encontrados. Carregando versões e metadados…"
                if apps_count > 0
                else "Carregando versões e metadados do catálogo…"
            )
            self.stateChanged.emit()
            self.statusMessageChanged.emit()
            self.detailMessageChanged.emit()
            self.progressChanged.emit()

        elif phase == "ready":
            self._apps_count = apps_count
            self._versions_count = versions_count
            self.progressChanged.emit()
            self.set_ready()

        elif phase == "error":
            self._state = "error"
            if not self._error_message:
                self._error_message = "Falha ao carregar o catálogo de aplicativos."
            self._status_message = "Erro de inicialização"
            self._detail_message = "Não foi possível preparar o ambiente."
            self.stateChanged.emit()
            self.statusMessageChanged.emit()
            self.detailMessageChanged.emit()
            self.errorMessageChanged.emit()

    def _on_catalog_loaded_payload(self, result: object) -> None:
        if self._is_ready and self._state == "ready":
            return
        if isinstance(result, dict) and result.get("error"):
            self._error_message = str(result["error"])
            self._state = "error"
            self._status_message = "Erro de inicialização"
            self._detail_message = "Não foi possível preparar o ambiente."
            self.stateChanged.emit()
            self.statusMessageChanged.emit()
            self.detailMessageChanged.emit()
            self.errorMessageChanged.emit()

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
    # Async setup handshake: saveSetup persists fields, shows loading and only
    # *requests* backend creation. The app answers with
    # setupInitializationSucceeded (persist setup/completed, emit
    # setupCompleted, start catalog) or setupInitializationFailed (back to the
    # setup form, completed stays false).
    setupInitializationRequested = Signal(object)

    def __init__(
        self,
        settings: MarySettings | None,
        preferences: QSettings | None = None,
        *,
        initial_state: str = "ready",
        on_setup_completed: Callable[[MarySettings], Any] | None = None,
        on_bootstrap_retry: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._preferences = preferences
        self._on_setup_completed = on_setup_completed
        self._on_bootstrap_retry = on_bootstrap_retry
        self._state = initial_state  # boot, check_setup, setup, initializing, loading_apps, loading_versions, ready, error
        self._phase = "idle"
        self._status_message = "Preparando seu ambiente" if initial_state != "setup" else "Configuração Inicial"
        self._detail_message = "Inicializando..." if initial_state != "setup" else "Preencha as configurações essenciais para prosseguir."
        self._error_message = ""
        self._apps_count = 0
        self._versions_count = 0
        self._is_ready = initial_state == "ready"
        self._chat_bridge: Any = None
        self._pending_setup_settings: MarySettings | None = None
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
        """Real total of catalog versions across applications (never a placeholder)."""
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
        self._pending_setup_settings = new_settings
        self._error_message = ""
        self.errorMessageChanged.emit()

        # Move to the loading state synchronously so StartupLoadingPage
        # renders its first frame before any deferred backend work runs.
        # Field validation/persistence above is light (mkdir + .env + reload);
        # the heavy initialize_workspace() runs exactly once, later, owned by
        # the startup coordinator after the loading frame has been presented.
        self._state = "initializing"
        self._is_ready = False
        self._status_message = "Preparando seu ambiente"
        self._detail_message = "Inicializando…"
        self.stateChanged.emit()
        self.statusMessageChanged.emit()
        self.detailMessageChanged.emit()
        self.setupInitializationRequested.emit(new_settings)

        # Fire-and-forget backend request: the callback must only schedule
        # the real initialization (after the first loading frame) and return
        # to the event loop. Completion arrives via
        # setupInitializationSucceeded / setupInitializationFailed, which is
        # the only path that persists setup/completed. The synchronous return
        # value is intentionally ignored so no heavy probe can run here.
        if self._on_setup_completed is not None:
            try:
                self._on_setup_completed(new_settings)
            except Exception as exc:
                self.setupInitializationFailed(
                    f"Não foi possível inicializar o ambiente: {exc}"
                )
                return

    @Slot(object)
    def setupInitializationSucceeded(self, new_settings: object = None) -> None:  # noqa: N802
        """Persist setup/completed after the minimal backend proved valid.

        Called by the startup coordinator once database + ChatBridge +
        StudioBridge are built and attached. Only here is setup/completed
        persisted and setupCompleted emitted; the catalog start that follows
        drives the loading_apps/loading_versions phases.
        """
        resolved = new_settings if isinstance(new_settings, MarySettings) else None
        self._pending_setup_settings = None
        if resolved is not None:
            self._settings = resolved
            self._settings_values = get_settings_values(resolved)
        if self._preferences is not None:
            mark_setup_completed(self._preferences)
        self.setupCompleted.emit(self._settings)
        self.toastRequested.emit("Configuração inicial salva com sucesso.", "success")

    @Slot(str)
    def setupInitializationFailed(self, message: str = "") -> None:  # noqa: N802
        """Return to the setup form; setup/completed stays false for retry."""
        self._pending_setup_settings = None
        self._enter_setup_error(
            message or "Não foi possível inicializar o ambiente com essa configuração."
        )

    @Slot()
    def openSetup(self) -> None:  # noqa: N802
        self._pending_setup_settings = None
        self._state = "setup"
        self._is_ready = False
        self._status_message = "Configuração Inicial"
        self._detail_message = "Ajuste os parâmetros necessários para continuar."
        if self._settings is not None:
            self._settings_values = get_settings_values(self._settings)
        self.stateChanged.emit()
        self.statusMessageChanged.emit()
        self.detailMessageChanged.emit()

    def _enter_setup_error(self, message: str) -> None:
        """Return to the setup form with an error instead of marking it done."""
        self._state = "setup"
        self._is_ready = False
        self._status_message = "Configuração Inicial"
        self._detail_message = "Ajuste os parâmetros necessários para continuar."
        self._error_message = message
        self.stateChanged.emit()
        self.statusMessageChanged.emit()
        self.detailMessageChanged.emit()
        self.errorMessageChanged.emit()
        self.toastRequested.emit(message, "error")

    def set_error(self, message: str) -> None:
        """Expose a bootstrap failure (e.g. backend creation) as error state."""
        self._state = "error"
        self._is_ready = False
        self._error_message = message or "Falha ao preparar o ambiente."
        self._status_message = "Erro de inicialização"
        self._detail_message = "Não foi possível preparar o ambiente."
        self.stateChanged.emit()
        self.statusMessageChanged.emit()
        self.detailMessageChanged.emit()
        self.errorMessageChanged.emit()

    # -------------------------------------------------------------------------
    # Catalog Bootstrap Lifecycle
    # -------------------------------------------------------------------------

    def detach_chat_bridge(self) -> None:
        """Drop a previous backend so rebuilds never duplicate signal paths."""
        previous = self._chat_bridge
        self._chat_bridge = None
        if previous is None:
            return
        for signal_name, handler in (
            ("applicationsCatalogPhase", self._on_catalog_phase),
            ("_applicationsLoaded", self._on_catalog_loaded_payload),
        ):
            try:
                signal = getattr(previous, signal_name, None)
                if signal is not None:
                    signal.disconnect(handler)
            except (RuntimeError, TypeError):
                pass

    def attach_chat_bridge(self, chat_bridge: Any) -> None:
        if chat_bridge is None or self._chat_bridge is chat_bridge:
            return
        self.detach_chat_bridge()
        self._chat_bridge = chat_bridge
        if hasattr(chat_bridge, "applicationsCatalogPhase"):
            try:
                # Duplicates are impossible here: same-bridge re-entry returns
                # early and a different bridge is detached first.
                chat_bridge.applicationsCatalogPhase.connect(
                    self._on_catalog_phase,
                    Qt.ConnectionType.QueuedConnection,
                )
            except RuntimeError:
                pass
        if hasattr(chat_bridge, "_applicationsLoaded"):
            try:
                chat_bridge._applicationsLoaded.connect(
                    self._on_catalog_loaded_payload,
                    Qt.ConnectionType.QueuedConnection,
                )
            except RuntimeError:
                pass

    def isAttachedTo(self, chat_bridge: Any) -> bool:  # noqa: N802
        """True only when the bootstrap listens to this exact ChatBridge."""
        return self._chat_bridge is not None and self._chat_bridge is chat_bridge

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

        # Fail closed: READY must mean (valid backend + finished catalog).
        # Without an attached ChatBridge there is no catalog to wait for, so
        # this is an error, never a shortcut to ready. Explicit set_ready()
        # remains available for screenshots/tests that skip the bootstrap.
        if self._chat_bridge is None:
            self.set_error(
                "Backend indisponível: nenhum ChatBridge anexado ao bootstrap."
            )
            return
        self._chat_bridge.refreshApplicationsCatalog()

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
        # When the app wires a retry handler it rebuilds the backend when
        # needed (missing/failed backend); otherwise just refresh the catalog.
        if self._on_bootstrap_retry is not None:
            self._on_bootstrap_retry()
        else:
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
            self._versions_count = versions_count
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

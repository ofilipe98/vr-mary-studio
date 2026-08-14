"""Reusable visual primitives for the VR Norte Studio interface.

These components deliberately avoid native popup geometry and platform icons so
the application keeps the same hierarchy, spacing and interaction on every
supported Windows scale factor.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .chat_widgets import RoundedPopupDialog

ASSET_DIR = Path(__file__).resolve().parent / "assets"


def _dark_theme() -> bool:
    application = QApplication.instance()
    return bool(application and application.property("vr_theme") == "dark_orange")


def _theme_icon(name: str) -> QIcon:
    suffix = "-dark" if _dark_theme() else ""
    path = ASSET_DIR / f"{name}{suffix}.svg"
    return QIcon(str(path))


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class _ElidedLabel(QLabel):
    """QLabel that keeps its full value while painting a middle ellipsis."""

    def __init__(self, text: str = "", parent: QWidget | None = None, **kwargs):
        super().__init__("", parent, **kwargs)
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._refresh_elision()

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._refresh_elision()

    def _refresh_elision(self) -> None:
        available = max(0, self.width())
        QLabel.setText(
            self,
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.ElideMiddle,
                available,
            ),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elision()


class SurfaceMenu(QMenu):
    """Application menu with stable sizing and the shared surface treatment."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("surfaceMenu")
        self.setSeparatorsCollapsible(True)
        self.setToolTipsVisible(True)
        self.setMinimumWidth(196)


class ContextActionMenu(SurfaceMenu):
    """Canonical menu for secondary actions tied to one UI entity."""

    def add_action(
        self,
        text: str,
        callback,
        *,
        destructive: bool = False,
        tooltip: str = "",
    ) -> QAction:
        action = self.addAction(text)
        action.setProperty("destructive", bool(destructive))
        if tooltip:
            action.setToolTip(tooltip)
        action.triggered.connect(callback)
        return action


class SimpleFilterGroup(QObject):
    """One API for counting and resetting search + combo filters."""

    activeCountChanged = Signal(int)

    def __init__(
        self,
        *,
        search: QLineEdit | None = None,
        selectors: tuple[QComboBox, ...] = (),
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.search = search
        self.selectors = tuple(selectors)
        if self.search is not None:
            self.search.textChanged.connect(self.refresh)
        for selector in self.selectors:
            selector.currentIndexChanged.connect(self.refresh)
            if selector.isEditable():
                selector.currentTextChanged.connect(self.refresh)

    def active_count(self) -> int:
        count = int(bool(self.search and self.search.text().strip()))
        return count + sum(
            int(selector.currentIndex() != 0) for selector in self.selectors
        )

    def refresh(self, *_args) -> int:
        count = self.active_count()
        self.activeCountChanged.emit(count)
        return count

    def reset(self) -> None:
        blockers = []
        if self.search is not None:
            blockers.append(QSignalBlocker(self.search))
            self.search.clear()
        for selector in self.selectors:
            blockers.append(QSignalBlocker(selector))
            selector.setCurrentIndex(0)
        self.refresh()


class ActionButton(QPushButton):
    """Canonical action with primary, secondary, ghost and danger variants."""

    VARIANTS = frozenset({"primary", "secondary", "ghost", "danger"})

    def __init__(
        self,
        text: str = "",
        *,
        variant: str = "secondary",
        parent: QWidget | None = None,
    ):
        super().__init__(text, parent)
        self.setObjectName("actionButton")
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        selected = variant if variant in self.VARIANTS else "secondary"
        self.setProperty("actionVariant", selected)
        _repolish(self)

    def variant(self) -> str:
        return str(self.property("actionVariant") or "secondary")


class FormField(QFrame):
    """Label, control, help and validation message as one accessible field."""

    def __init__(
        self,
        label: str,
        control: QWidget,
        *,
        help_text: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("formField")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.label = QLabel(label, objectName="formFieldLabel")
        layout.addWidget(self.label)
        self.control = control
        if not control.accessibleName():
            control.setAccessibleName(label)
        layout.addWidget(control)
        self.help_label = QLabel(help_text, objectName="formFieldHelp")
        self.help_label.setWordWrap(True)
        self.help_label.setVisible(bool(help_text))
        layout.addWidget(self.help_label)
        self.error_label = QLabel("", objectName="formFieldError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

    def set_error(self, message: str) -> None:
        value = str(message or "").strip()
        self.error_label.setText(value)
        self.error_label.setVisible(bool(value))
        self.control.setProperty("validationState", "error" if value else "")
        self.control.setAccessibleDescription(value or self.help_label.text())
        _repolish(self.control)


class StatusBadge(QLabel):
    """Compact semantic status shared by chat and operational pages."""

    KINDS = frozenset(
        {"idle", "running", "success", "warning", "error", "info"}
    )

    def __init__(
        self,
        text: str = "",
        *,
        kind: str = "idle",
        parent: QWidget | None = None,
    ):
        super().__init__(text, parent)
        self.setObjectName("statusBadge")
        self.set_status(text, kind)

    def set_status(self, text: str, kind: str = "info") -> None:
        value = str(text or "")
        selected = kind if kind in self.KINDS else "info"
        QLabel.setText(self, value)
        self.setToolTip(value)
        self.setProperty("statusKind", selected)
        self.setAccessibleName(f"Status: {value}")
        _repolish(self)

    def setText(self, text: str) -> None:
        value = str(text or "")
        normalized = value.casefold()
        if any(marker in normalized for marker in ("erro", "falha")):
            kind = "error"
        elif any(marker in normalized for marker in ("executando", "andamento")):
            kind = "running"
        elif any(marker in normalized for marker in ("atenção", "aguardando")):
            kind = "warning"
        elif any(marker in normalized for marker in ("concluído", "sucesso")):
            kind = "success"
        else:
            kind = "info"
        self.set_status(value, kind)


class _StudioDialog(RoundedPopupDialog):
    """Shared modal surface with deterministic centering and keyboard safety."""

    def __init__(self, parent: QWidget | None = None, *, radius: float = 16.0):
        super().__init__(parent, radius=radius)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModal)

    def showEvent(self, event) -> None:
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            host = parent.window()
            geometry = self.frameGeometry()
            geometry.moveCenter(host.frameGeometry().center())
            self.move(geometry.topLeft())
        super().showEvent(event)


class ConfirmDialog(_StudioDialog):
    """Application confirmation dialog, including typed destructive consent."""

    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget | None = None,
        *,
        confirm_text: str = "Continuar",
        cancel_text: str = "Cancelar",
        destructive: bool = False,
        confirmation_phrase: str = "",
        kind: str = "question",
    ):
        super().__init__(parent)
        self.setObjectName("confirmDialog")
        visual_kind = "error" if destructive else kind
        self.setProperty("dialogKind", visual_kind)
        self.setAccessibleName(title)
        self.setMinimumWidth(440)
        self.setMaximumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        eyebrow_text = {
            "error": "ALGO DEU ERRADO",
            "warning": "ATENÇÃO",
            "success": "CONCLUÍDO",
        }.get(visual_kind, "CONFIRMAÇÃO")
        if destructive and confirmation_phrase:
            eyebrow_text = "AÇÃO PERMANENTE"
        eyebrow = QLabel(eyebrow_text, objectName="dialogEyebrow")
        eyebrow.setProperty("dialogKind", visual_kind)
        layout.addWidget(eyebrow)
        heading = QLabel(title, objectName="dialogTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        body = QLabel(message, objectName="dialogMessage")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        self.phrase_input: QLineEdit | None = None
        self._confirmation_phrase = confirmation_phrase.strip()
        if self._confirmation_phrase:
            phrase_hint = QLabel(
                f"Digite “{self._confirmation_phrase}” para confirmar.",
                objectName="dialogPhraseHint",
            )
            phrase_hint.setWordWrap(True)
            layout.addWidget(phrase_hint)
            self.phrase_input = QLineEdit(objectName="dialogPhrase")
            self.phrase_input.setPlaceholderText("Digite a frase de confirmação")
            self.phrase_input.setAccessibleName(
                f"Digite {self._confirmation_phrase} para confirmar"
            )
            self.phrase_input.setClearButtonEnabled(True)
            self.phrase_input.returnPressed.connect(self._accept_if_confirmed)
            layout.addWidget(self.phrase_input)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        self.cancel_button: QPushButton | None = None
        if cancel_text:
            self.cancel_button = QPushButton(cancel_text, objectName="dialogCancel")
            self.cancel_button.setAccessibleName(cancel_text)
            self.cancel_button.clicked.connect(self.reject)
            self.cancel_button.setDefault(True)
            actions.addWidget(self.cancel_button)
        button_name = "dialogDanger" if destructive else "dialogPrimary"
        self.confirm_button = QPushButton(confirm_text, objectName=button_name)
        self.confirm_button.setAccessibleName(confirm_text)
        self.confirm_button.clicked.connect(self.accept)
        self.confirm_button.setAutoDefault(False)
        actions.addWidget(self.confirm_button)
        layout.addLayout(actions)

        if self.phrase_input is not None:
            self.phrase_input.textChanged.connect(self._sync_confirmation_state)
            self._sync_confirmation_state()
            self.setFocusProxy(self.phrase_input)

    def _sync_confirmation_state(self, *_args) -> None:
        entered = self.phrase_input.text().strip() if self.phrase_input else ""
        self.confirm_button.setEnabled(
            entered.casefold() == self._confirmation_phrase.casefold()
        )

    def _accept_if_confirmed(self) -> None:
        if self.confirm_button.isEnabled():
            self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.phrase_input is not None:
            self.phrase_input.setFocus()

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        confirm_text: str = "Continuar",
        cancel_text: str = "Cancelar",
        destructive: bool = False,
        confirmation_phrase: str = "",
    ) -> bool:
        dialog = cls(
            title,
            message,
            parent,
            confirm_text=confirm_text,
            cancel_text=cancel_text,
            destructive=destructive,
            confirmation_phrase=confirmation_phrase,
        )
        return dialog.exec() == QDialog.Accepted

    @classmethod
    def notice(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        kind: str = "error",
        confirm_text: str = "Entendi",
    ) -> None:
        cls(
            title,
            message,
            parent,
            confirm_text=confirm_text,
            cancel_text="",
            destructive=kind == "error",
            kind=kind,
        ).exec()


class TextPromptDialog(_StudioDialog):
    """Multiline correction dialog that prevents empty/no-op branches."""

    def __init__(
        self,
        title: str,
        prompt: str,
        original: str,
        parent: QWidget | None = None,
        *,
        confirm_text: str = "Criar ramificação",
    ):
        super().__init__(parent)
        self.setObjectName("textPromptDialog")
        self.setAccessibleName(title)
        self.setMinimumWidth(520)
        self.setMinimumHeight(330)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        eyebrow = QLabel("EDITAR MENSAGEM", objectName="dialogEyebrow")
        layout.addWidget(eyebrow)
        heading = QLabel(title, objectName="dialogTitle")
        layout.addWidget(heading)
        instruction = QLabel(prompt, objectName="dialogMessage")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.editor = QPlainTextEdit(objectName="dialogEditor")
        self.editor.setPlainText(original)
        self.editor.setAccessibleName("Mensagem corrigida")
        self.editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.editor, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel = QPushButton("Cancelar", objectName="dialogCancel")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.confirm_button = QPushButton(confirm_text, objectName="dialogPrimary")
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self.accept)
        actions.addWidget(self.confirm_button)
        layout.addLayout(actions)

        self._original = original.strip()
        self.editor.textChanged.connect(self._sync_confirmation_state)
        self._sync_confirmation_state()
        self.setFocusProxy(self.editor)

    def _focus_editor(self) -> None:
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.editor.setTextCursor(cursor)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._focus_editor()

    def _sync_confirmation_state(self) -> None:
        value = self.value()
        self.confirm_button.setEnabled(bool(value) and value != self._original)

    def value(self) -> str:
        return self.editor.toPlainText().strip()

    @classmethod
    def get_multiline(
        cls,
        parent: QWidget | None,
        title: str,
        prompt: str,
        original: str,
        *,
        confirm_text: str = "Criar ramificação",
    ) -> tuple[str, bool]:
        dialog = cls(
            title,
            prompt,
            original,
            parent,
            confirm_text=confirm_text,
        )
        accepted = dialog.exec() == QDialog.Accepted
        return dialog.value(), accepted


class ToastBanner(QFrame):
    """Non-blocking feedback banner anchored over a parent window."""

    closed = Signal()

    def __init__(
        self,
        message: str,
        parent: QWidget,
        *,
        kind: str = "info",
    ):
        super().__init__(parent)
        self.setObjectName("toastBanner")
        self.setProperty("toastKind", kind)
        self.setAccessibleName(f"Aviso: {message}")
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumWidth(320)
        self.setMaximumWidth(440)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 8, 11)
        layout.setSpacing(10)
        message_label = QLabel(message, objectName="toastMessage")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(message_label, 1)
        close_button = QPushButton("×", objectName="toastClose")
        close_button.setAccessibleName("Fechar aviso")
        close_button.setFocusPolicy(Qt.NoFocus)
        close_button.clicked.connect(self.dismiss)
        layout.addWidget(close_button, 0, Qt.AlignTop)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._dismissed = False

    def show_anchored(
        self,
        *,
        top: int = 20,
        right: int = 20,
        duration_ms: int = 4500,
    ) -> None:
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(12, parent.width() - self.width() - right), top)
        self.show()
        self.raise_()
        if duration_ms > 0:
            self._timer.start(duration_ms)

    def dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self._timer.stop()
        self.hide()
        self.closed.emit()
        self.deleteLater()


class DataToolbar(QFrame):
    """Shared data-page header with search, filters and a primary action."""

    searchSubmitted = Signal()
    filtersToggled = Signal(bool)
    primaryRequested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        search_placeholder: str = "",
        filter_text: str = "Filtros",
        primary_text: str = "",
        show_search: bool = True,
        show_filters: bool = True,
    ):
        super().__init__(parent)
        self.setObjectName("dataToolbar")
        self.setAccessibleName("Ferramentas de dados")
        self._filter_text = filter_text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(8)
        self.search = QLineEdit(objectName="dataToolbarSearch")
        self.search.setPlaceholderText(search_placeholder)
        self.search.setAccessibleName("Pesquisar dados")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.searchSubmitted)
        self.search.setVisible(show_search)
        layout.addWidget(self.search, 1 if show_search else 0)

        self.filter_button = QToolButton(objectName="dataToolbarFilter")
        self.filter_button.setText(filter_text)
        self.filter_button.setCheckable(True)
        self.filter_button.setArrowType(Qt.RightArrow)
        self.filter_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.filter_button.setAccessibleName(f"Mostrar {filter_text.casefold()}")
        self.filter_button.setToolTip(f"Mostrar ou ocultar {filter_text.casefold()}")
        self.filter_button.toggled.connect(self._filters_toggled)
        self.filter_button.setVisible(show_filters)
        layout.addWidget(self.filter_button)

        self.counter = QLabel("0 resultados", objectName="dataToolbarCount")
        self.counter.setAccessibleName("Quantidade de resultados")
        layout.addWidget(self.counter)
        if not show_search:
            layout.addStretch(1)

        self.primary_button = ActionButton(primary_text, variant="primary")
        self.primary_button.setObjectName("dataToolbarPrimary")
        self.primary_button.setVisible(bool(primary_text))
        self.primary_button.clicked.connect(self.primaryRequested)
        layout.addWidget(self.primary_button)

    def set_count(self, text: str) -> None:
        self.counter.setText(text)
        self.counter.setToolTip(text)

    def set_filter_count(self, count: int) -> None:
        self.filter_button.setText(
            self._filter_text if count <= 0 else f"{self._filter_text} · {count}"
        )
        self.filter_button.setProperty("active", count > 0)
        _repolish(self.filter_button)

    def set_filters_expanded(self, expanded: bool) -> None:
        self.filter_button.blockSignals(True)
        self.filter_button.setChecked(expanded)
        self.filter_button.blockSignals(False)
        self.filter_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _filters_toggled(self, visible: bool) -> None:
        self.filter_button.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        self.filtersToggled.emit(visible)


class EmptyState(QFrame):
    """Actionable empty result state shared by data pages."""

    actionRequested = Signal()

    def __init__(
        self,
        title: str,
        message: str,
        action_text: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("dataEmptyState")
        self.setAccessibleName(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(9)
        layout.addStretch(1)
        marker = QLabel("—", objectName="dataEmptyMarker")
        marker.setAlignment(Qt.AlignCenter)
        layout.addWidget(marker, 0, Qt.AlignHCenter)
        self.title_label = QLabel(title, objectName="dataEmptyTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.message_label = QLabel(message, objectName="dataEmptyMessage")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(520)
        layout.addWidget(self.message_label, 0, Qt.AlignHCenter)
        self.action_button = ActionButton(action_text, variant="primary")
        self.action_button.setObjectName("dataEmptyAction")
        self.action_button.setVisible(bool(action_text))
        self.action_button.clicked.connect(self.actionRequested)
        layout.addWidget(self.action_button, 0, Qt.AlignHCenter)
        layout.addStretch(1)

    def set_content(self, title: str, message: str, action_text: str = "") -> None:
        self.title_label.setText(title)
        self.message_label.setText(message)
        self.action_button.setText(action_text)
        self.action_button.setVisible(bool(action_text))


class LoadingSkeleton(QFrame):
    """Static loading placeholder without continuous repaint or animation."""

    def __init__(
        self,
        message: str = "Carregando dados…",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("loadingSkeleton")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        label = QLabel(message, objectName="loadingSkeletonLabel")
        layout.addWidget(label)
        for index in range(6):
            bar = QFrame(objectName="loadingSkeletonBar")
            bar.setProperty("short", index in {2, 5})
            bar.setFixedHeight(14)
            bar.setMaximumWidth(520 if index in {2, 5} else 760)
            layout.addWidget(bar)
        layout.addStretch(1)


class DataContentStack(QStackedWidget):
    """Canonical content, empty and loading state container."""

    def __init__(
        self,
        content: QWidget,
        *,
        empty_title: str,
        empty_message: str,
        empty_action: str = "",
        loading_message: str = "Carregando dados…",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("dataContentStack")
        self.content = content
        self.empty_state = EmptyState(
            empty_title,
            empty_message,
            empty_action,
            self,
        )
        self.loading_state = LoadingSkeleton(loading_message, self)
        self.addWidget(content)
        self.addWidget(self.empty_state)
        self.addWidget(self.loading_state)
        self.set_state("content")

    def set_state(self, state: str) -> None:
        target = {
            "content": self.content,
            "empty": self.empty_state,
            "loading": self.loading_state,
        }.get(state, self.content)
        self.setCurrentWidget(target)
        self.setAccessibleName(
            {
                "content": "Conteúdo disponível",
                "empty": "Nenhum resultado",
                "loading": "Carregando conteúdo",
            }.get(state, "Conteúdo disponível")
        )


class PaginationBar(QFrame):
    """Shared pagination controls with a stable result-range summary."""

    previousRequested = Signal()
    nextRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("paginationBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.previous_button = QPushButton("← Anterior", objectName="paginationButton")
        self.previous_button.clicked.connect(self.previousRequested)
        layout.addWidget(self.previous_button)
        self.page_label = QLabel("Página 1 de 1", objectName="paginationPage")
        layout.addWidget(self.page_label)
        self.next_button = QPushButton("Próxima →", objectName="paginationButton")
        self.next_button.clicked.connect(self.nextRequested)
        layout.addWidget(self.next_button)
        layout.addStretch(1)
        self.range_label = QLabel("0 itens", objectName="paginationRange")
        layout.addWidget(self.range_label)

    def set_page(
        self,
        *,
        offset: int,
        page_size: int,
        visible_count: int,
        total: int,
    ) -> None:
        first = offset + 1 if total else 0
        last = min(offset + visible_count, total)
        current = offset // max(1, page_size) + 1
        pages = max(1, (total + max(1, page_size) - 1) // max(1, page_size))
        self.page_label.setText(f"Página {current} de {pages}")
        self.range_label.setText(
            f"Exibindo {first}–{last} de {total}" if total else "Nenhum item"
        )
        self.previous_button.setEnabled(offset > 0)
        self.next_button.setEnabled(offset + page_size < total)


class ProjectScopeButton(QFrame):
    """Compact project trigger whose layout does not depend on native menus."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("projectSelector")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Selecionar projeto")
        self.setMinimumHeight(34)
        self.setMaximumHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 8, 0)
        layout.setSpacing(7)
        self._folder = QLabel(objectName="projectSelectorIcon")
        self._folder.setFixedSize(16, 16)
        self._folder.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._folder)
        self._label = _ElidedLabel(
            "Todos os projetos", objectName="projectSelectorLabel"
        )
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._label.setToolTip("Todos os projetos")
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._label, 1)
        self._chevron = QLabel(objectName="projectSelectorChevron")
        self._chevron.setFixedSize(12, 8)
        self._chevron.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._chevron)
        self.refresh_theme()

    def text(self) -> str:
        return self._label.full_text()

    def setText(self, text: str) -> None:
        display = str(text)
        self._label.set_full_text(display)
        self.setToolTip(display)
        self.setAccessibleDescription(display)

    def set_expanded(self, expanded: bool) -> None:
        self.setProperty("expanded", expanded)
        _repolish(self)

    def refresh_theme(self) -> None:
        self._folder.setPixmap(_theme_icon("project-folder").pixmap(QSize(16, 16)))
        self._chevron.setPixmap(_theme_icon("project-chevron").pixmap(QSize(12, 8)))

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.rect().contains(event.position().toPoint())
            and self.isEnabled()
        ):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space}:
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _ProjectScopeRow(QFrame):
    activated = Signal(object)
    openRequested = Signal(object)
    removeRequested = Signal(object)

    def __init__(
        self,
        project: Path | None,
        *,
        selected: bool,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.project = project.resolve() if project is not None else None
        self.setObjectName("projectMenuRow")
        self.setProperty("selected", selected)
        self.setProperty("keyboardFocus", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumHeight(36)
        self.setMaximumHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 9, 0)
        layout.setSpacing(8)
        self.icon_label = QLabel(objectName="projectMenuIcon")
        self.icon_label.setFixedSize(16, 16)
        layout.addWidget(self.icon_label)
        label = (
            "Todos os projetos"
            if self.project is None
            else (self.project.name or str(self.project))
        )
        self.name_label = QLabel(label, objectName="projectMenuName")
        self.name_label.setMinimumWidth(0)
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.name_label.setToolTip(
            "Exibir conversas de todos os projetos"
            if self.project is None
            else str(self.project)
        )
        layout.addWidget(self.name_label, 1)
        self.check_label = QLabel(objectName="projectMenuCheck")
        self.check_label.setAlignment(Qt.AlignCenter)
        self.check_label.setFixedWidth(18)
        layout.addWidget(self.check_label)
        self.action_button = QToolButton(objectName="projectMenuActions")
        self.action_button.setText("⋯")
        self.action_button.setAccessibleName(f"Ações do projeto {label}")
        self.action_button.setToolTip(f"Ações do projeto {label}")
        self.action_button.setVisible(self.project is not None)
        if self.project is not None:
            self.action_menu = ContextActionMenu(self.action_button)
            self.action_menu.add_action(
                "Abrir pasta",
                lambda: self.openRequested.emit(self.project),
            )
            self.action_menu.add_action(
                "Remover da lista",
                lambda: self.removeRequested.emit(self.project),
            )
            self.action_button.setMenu(self.action_menu)
            self.action_button.setPopupMode(QToolButton.InstantPopup)
        layout.addWidget(self.action_button)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        name = "project-all" if self.project is None else "project-folder"
        self.icon_label.setPixmap(_theme_icon(name).pixmap(QSize(16, 16)))
        if bool(self.property("selected")):
            self.check_label.setPixmap(
                _theme_icon("project-check").pixmap(QSize(16, 16))
            )

    def set_keyboard_focus(self, focused: bool) -> None:
        self.setProperty("keyboardFocus", focused)
        _repolish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.activated.emit(self.project)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _ProjectSearchLineEdit(QLineEdit):
    navigationRequested = Signal(int)

    def keyPressEvent(self, event) -> None:
        if event.key() in {
            Qt.Key_Down,
            Qt.Key_Up,
            Qt.Key_Return,
            Qt.Key_Enter,
            Qt.Key_Escape,
        }:
            self.navigationRequested.emit(event.key())
            event.accept()
            return
        super().keyPressEvent(event)


class ProjectScopePopup(RoundedPopupDialog):
    """Anchored, searchable project scope selector inspired by T3 Code."""

    projectSelected = Signal(object)
    openProjectRequested = Signal(object)
    removeProjectRequested = Signal(object)

    def __init__(self, anchor: ProjectScopeButton, parent: QWidget | None = None):
        super().__init__(parent, radius=12.0)
        self.anchor = anchor
        self.setObjectName("projectScopePopup")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setProperty("closeOnDeactivate", True)
        self.setAccessibleName("Lista de projetos")
        self._projects: list[Path] = []
        self._current: Path | None = None
        self._rows: list[_ProjectScopeRow] = []
        self._focused_row = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.search = _ProjectSearchLineEdit(objectName="projectScopeSearch")
        self.search.setPlaceholderText("Buscar projeto…")
        self.search.setAccessibleName("Buscar projeto")
        self.search.textChanged.connect(self._rebuild_rows)
        self.search.navigationRequested.connect(self._handle_navigation_key)
        layout.addWidget(self.search)

        self.scroll = QScrollArea(objectName="projectScopeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.rows_host = QWidget(objectName="projectScopeRows")
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        self.scroll.setWidget(self.rows_host)
        layout.addWidget(self.scroll)

    def set_projects(self, projects: list[Path], current: Path | None) -> None:
        unique: list[Path] = []
        for project in projects:
            resolved = project.resolve()
            if resolved not in unique:
                unique.append(resolved)
        resolved_current = current.resolve() if current is not None else None
        if resolved_current is not None and resolved_current not in unique:
            unique.insert(0, resolved_current)
        self._projects = unique
        self._current = resolved_current
        self.search.setVisible(len(unique) > 5)
        if self.search.isHidden():
            self.search.clear()
        self._rebuild_rows()

    def actions(self) -> list[QAction]:
        """Expose semantic entries for compatibility with existing UI tests."""
        actions: list[QAction] = []
        for label in ["Todos os projetos", *[p.name or str(p) for p in self._projects]]:
            actions.append(QAction(label, self))
        return actions

    def show_anchored(self) -> None:
        if self.search.text():
            self.search.clear()
        self._rebuild_rows()
        width = max(260, self.anchor.width())
        row_count = max(1, len(self._rows))
        search_height = 40 if not self.search.isHidden() else 0
        height = min(430, 16 + search_height + row_count * 38)
        self.setFixedSize(width, height)
        position = self.anchor.mapToGlobal(QPoint(0, self.anchor.height() + 5))
        screen = self.anchor.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = min(max(position.x(), available.left()), available.right() - width + 1)
            y = position.y()
            if y + height > available.bottom():
                y = self.anchor.mapToGlobal(QPoint(0, -height - 5)).y()
            position = QPoint(x, max(available.top(), y))
        self.move(position)
        self.anchor.set_expanded(True)
        self.show()
        self.raise_()
        if not self.search.isHidden():
            self.search.setFocus()
        else:
            self.setFocus()

    def refresh_theme(self) -> None:
        self.add_button.setIcon(_theme_icon("project-add"))
        for row in self._rows:
            row.refresh_theme()
        self.update()

    def done(self, result: int) -> None:
        self.anchor.set_expanded(False)
        super().done(result)

    def hideEvent(self, event) -> None:
        self.anchor.set_expanded(False)
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._handle_navigation_key(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_navigation_key(self, key: int) -> bool:
        if not self._rows:
            if key == Qt.Key_Escape:
                self.reject()
                return True
            return False
        if key in {Qt.Key_Down, Qt.Key_Up}:
            offset = 1 if key == Qt.Key_Down else -1
            self._set_focused_row((self._focused_row + offset) % len(self._rows))
            return True
        if key in {Qt.Key_Return, Qt.Key_Enter}:
            self._activate_project(self._rows[self._focused_row].project)
            return True
        if key == Qt.Key_Escape:
            self.reject()
            return True
        return False

    def _rebuild_rows(self, *_args) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []
        term = self.search.text().strip().casefold()
        candidates: list[Path | None] = [None, *self._projects]
        for project in candidates:
            label = (
                "Todos os projetos" if project is None else f"{project.name} {project}"
            )
            if term and term not in label.casefold():
                continue
            row = _ProjectScopeRow(
                project,
                selected=(project is None and self._current is None)
                or (project is not None and project == self._current),
                parent=self.rows_host,
            )
            row.activated.connect(self._activate_project)
            row.openRequested.connect(self._request_open_project)
            row.removeRequested.connect(self._request_remove_project)
            self.rows_layout.addWidget(row)
            self._rows.append(row)
        self.rows_layout.addStretch(1)
        self._focused_row = 0
        for index, row in enumerate(self._rows):
            if bool(row.property("selected")):
                self._focused_row = index
                break
        self._set_focused_row(self._focused_row)

    def _set_focused_row(self, index: int) -> None:
        if not self._rows:
            return
        self._focused_row = max(0, min(index, len(self._rows) - 1))
        for row_index, row in enumerate(self._rows):
            row.set_keyboard_focus(row_index == self._focused_row)
        self.scroll.ensureWidgetVisible(self._rows[self._focused_row])

    def _activate_project(self, project: Path | None) -> None:
        self.projectSelected.emit(project)
        self.accept()

    def _request_open_project(self, project: Path) -> None:
        self.accept()
        self.openProjectRequested.emit(project)

    def _request_remove_project(self, project: Path) -> None:
        self.accept()
        self.removeProjectRequested.emit(project)


class _VrOptionRow(QFrame):
    activated = Signal(str)

    def __init__(
        self,
        value: str,
        title: str,
        description: str,
        *,
        selected: bool,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.value = value
        self.setObjectName("vrOptionRow")
        self.setProperty("selected", selected)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        self.setMinimumHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 9, 6)
        layout.setSpacing(9)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title_label = QLabel(title, objectName="vrOptionTitle")
        self.description_label = QLabel(description, objectName="vrOptionDescription")
        self.description_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.description_label)
        layout.addLayout(text_layout, 1)
        self.check_label = QLabel(objectName="vrOptionCheck")
        self.check_label.setFixedSize(18, 18)
        self.check_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.check_label)
        self.refresh_theme()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.refresh_theme()
        _repolish(self)

    def refresh_theme(self) -> None:
        if bool(self.property("selected")):
            self.check_label.setPixmap(
                _theme_icon("project-check").pixmap(QSize(16, 16))
            )
        else:
            self.check_label.clear()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.activated.emit(self.value)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space}:
            self.activated.emit(self.value)
            event.accept()
            return
        super().keyPressEvent(event)


class VrModePopup(RoundedPopupDialog):
    """Descriptive control panel for local context and orchestration modes."""

    vrEnabledChanged = Signal(bool)
    modeSelected = Signal(str)
    settingsRequested = Signal()

    MODE_OPTIONS = (
        (
            "off",
            "Desligado",
            "Sem agentes extras; usa somente o modelo principal.",
        ),
        (
            "automatic",
            "Automático",
            "Escolhe resposta direta, padrão ou Ultra pela dificuldade.",
        ),
        (
            "standard",
            "Ligado",
            "Executa especialistas em paralelo e gera uma síntese final.",
        ),
        (
            "ultra",
            "Ultra",
            "Amplia análises, crítica cruzada e validação.",
        ),
    )

    def __init__(self, anchor: QWidget, parent: QWidget | None = None):
        super().__init__(parent, radius=14.0)
        self.anchor = anchor
        self.setObjectName("vrModePopup")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setProperty("closeOnDeactivate", True)
        self.setAccessibleName("Configuração do fluxo VR")
        self._vr_enabled = True
        self._mode = "automatic"
        self._mode_rows: dict[str, _VrOptionRow] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        title = QLabel("Fluxo VR", objectName="vrPanelTitle")
        layout.addWidget(title)
        self.base_row = _VrOptionRow(
            "base",
            "Consultar base local",
            "Pesquisa Wiki, KB e schema antes de responder.",
            selected=True,
            parent=self,
        )
        self.base_row.activated.connect(self._toggle_base)
        layout.addWidget(self.base_row)
        section = QLabel("Modo de orquestração", objectName="vrPanelSection")
        layout.addWidget(section)
        for value, label, description in self.MODE_OPTIONS:
            row = _VrOptionRow(
                value,
                label,
                description,
                selected=value == self._mode,
                parent=self,
            )
            row.activated.connect(self._select_mode)
            self._mode_rows[value] = row
            layout.addWidget(row)
        self.summary = QLabel("", objectName="vrPanelSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.settings_button = QPushButton(
            "Configuração avançada…", objectName="vrPanelSettings"
        )
        self.settings_button.clicked.connect(self._request_settings)
        layout.addWidget(self.settings_button)

    def set_state(
        self,
        *,
        vr_enabled: bool,
        mode: str,
        strategy: str,
        model_count: int,
    ) -> None:
        self._vr_enabled = bool(vr_enabled)
        self._mode = mode if mode in self._mode_rows else "automatic"
        self.base_row.set_selected(self._vr_enabled)
        for value, row in self._mode_rows.items():
            row.set_selected(value == self._mode)
        strategy_labels = {
            "automatic": "automática",
            "parallel": "paralela",
            "specialized": "especializada",
            "sequential": "sequencial",
            "debate": "debate",
            "consensus": "consenso",
            "adaptive": "adaptativa",
        }
        strategy_label = strategy_labels.get(strategy, strategy)
        state = "Base local ativa" if self._vr_enabled else "Base local desativada"
        self.summary.setText(
            f"{state} · estratégia {strategy_label} · "
            f"{max(1, model_count)} modelo(s) no pool"
        )

    def show_anchored(self) -> None:
        width = 382
        height = 385
        self.setFixedSize(width, height)
        position = self.anchor.mapToGlobal(
            QPoint(self.anchor.width() - width, -height - 6)
        )
        screen = self.anchor.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = min(max(position.x(), available.left()), available.right() - width + 1)
            y = position.y()
            if y < available.top():
                y = self.anchor.mapToGlobal(QPoint(0, self.anchor.height() + 6)).y()
            position = QPoint(x, min(y, available.bottom() - height + 1))
        self.move(position)
        self.show()
        self.raise_()
        self.base_row.setFocus()

    def refresh_theme(self) -> None:
        self.base_row.refresh_theme()
        for row in self._mode_rows.values():
            row.refresh_theme()
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def _toggle_base(self, _value: str) -> None:
        self._vr_enabled = not self._vr_enabled
        self.base_row.set_selected(self._vr_enabled)
        self.vrEnabledChanged.emit(self._vr_enabled)

    def _select_mode(self, mode: str) -> None:
        self._mode = mode
        for value, row in self._mode_rows.items():
            row.set_selected(value == mode)
        self.modeSelected.emit(mode)
        self.accept()

    def _request_settings(self) -> None:
        self.accept()
        self.settingsRequested.emit()

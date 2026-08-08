from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    Property,
    QPropertyAnimation,
    QRectF,
    QSettings,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .chat_tools import ToolValidationError, validate_tool_definition
from .db import MaryDatabase
from .spellcheck import LocalSpellChecker


ASSET_DIR = Path(__file__).resolve().parent / "assets"
PROVIDER_ICON_PATHS = {
    "codex": ASSET_DIR / "provider-gpt.png",
    "claude": ASSET_DIR / "provider-claude.webp",
}
_PROVIDER_ICON_CACHE: dict[str, QIcon] = {}


def provider_icon(provider: str) -> QIcon:
    provider_name = str(provider).casefold()
    cached = _PROVIDER_ICON_CACHE.get(provider_name)
    if cached is not None:
        return cached
    path = PROVIDER_ICON_PATHS.get(provider_name)
    if not path or not path.is_file():
        return QIcon()
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QIcon()
    mask = pixmap.mask()
    if not mask.isNull():
        visible_bounds = QRegion(mask).boundingRect()
        if visible_bounds.isValid() and not visible_bounds.isEmpty():
            pixmap = pixmap.copy(visible_bounds)
    if provider_name == "codex":
        canvas = QPixmap(128, 128)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#D1D5DB"), 3))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(3, 3, 122, 122)
        symbol = pixmap.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(
            (canvas.width() - symbol.width()) // 2,
            (canvas.height() - symbol.height()) // 2,
            symbol,
        )
        painter.end()
        pixmap = canvas
    icon = QIcon(pixmap)
    _PROVIDER_ICON_CACHE[provider_name] = icon
    return icon


class AnimatedVrFlowButton(QToolButton):
    """Compact animated switch for the optional local VR knowledge flow."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._glow = 0.0
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(62, 30)
        self.setAccessibleName("Fluxo VR")

        self._glow_animation = QPropertyAnimation(self, b"glow", self)
        self._glow_animation.setDuration(1500)
        self._glow_animation.setLoopCount(-1)
        self._glow_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._glow_animation.setKeyValueAt(0.0, 0.0)
        self._glow_animation.setKeyValueAt(0.5, 1.0)
        self._glow_animation.setKeyValueAt(1.0, 0.0)
        self.toggled.connect(self._sync_state)
        self._sync_state(self.isChecked())

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = float(value)
        self.update()

    glow = Property(float, _get_glow, _set_glow)

    def _sync_state(self, enabled: bool) -> None:
        if enabled:
            if self._glow_animation.state() != QPropertyAnimation.Running:
                self._glow_animation.start()
            description = "Fluxo VR ativo: consulta a base local antes de responder"
        else:
            self._glow_animation.stop()
            self._set_glow(0.0)
            description = "Fluxo VR inativo: conversa diretamente com a LLM"
        self.setToolTip(description)
        self.setAccessibleDescription(description)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        body = QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -2.0)
        radius = body.height() / 2.0

        if self.isChecked():
            pulse = max(0.0, min(1.0, self._glow))
            painter.setPen(QPen(QColor(255, 189, 15, 95 + int(130 * pulse)), 2.2))
            gradient = QLinearGradient(body.topLeft(), body.bottomRight())
            gradient.setColorAt(0.0, QColor("#FF8A00"))
            gradient.setColorAt(0.55, QColor("#E85B00"))
            gradient.setColorAt(1.0, QColor("#B83D00"))
            painter.setBrush(gradient)
            text_color = QColor("#FFFFFF")
            star_color = QColor("#FFF1B8")
        else:
            painter.setPen(QPen(QColor("#B9B9C5"), 1.2))
            painter.setBrush(QColor("#F1F1F5"))
            text_color = QColor("#5F5F70")
            star_color = QColor("#777789")
        painter.drawRoundedRect(body, radius, radius)

        star_center = QPointF(body.left() + 13.0, body.center().y())
        outer = 5.0 if self.isChecked() else 4.2
        inner = 1.35
        star = QPainterPath()
        star.moveTo(star_center.x(), star_center.y() - outer)
        star.lineTo(star_center.x() + inner, star_center.y() - inner)
        star.lineTo(star_center.x() + outer, star_center.y())
        star.lineTo(star_center.x() + inner, star_center.y() + inner)
        star.lineTo(star_center.x(), star_center.y() + outer)
        star.lineTo(star_center.x() - inner, star_center.y() + inner)
        star.lineTo(star_center.x() - outer, star_center.y())
        star.lineTo(star_center.x() - inner, star_center.y() - inner)
        star.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(star_color)
        painter.drawPath(star)

        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(max(8.5, font.pointSizeF()))
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(
            QRectF(body.left() + 21.0, body.top(), body.width() - 25.0, body.height()),
            Qt.AlignCenter,
            "VR",
        )
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#FCBD0F"), 1.5, Qt.DotLine))
            painter.drawRoundedRect(body.adjusted(1, 1, -1, -1), radius, radius)
        painter.end()


class SpellHighlighter(QSyntaxHighlighter):
    def __init__(self, document, checker: LocalSpellChecker):
        super().__init__(document)
        self.checker = checker
        self.format = QTextCharFormat()
        self.format.setUnderlineColor(QColor("#C62828"))
        self.format.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        for issue in self.checker.misspellings(text):
            self.setFormat(issue.start, issue.length, self.format)


class SpellcheckPlainTextEdit(QPlainTextEdit):
    submitRequested = Signal()
    interactionStarted = Signal()

    def __init__(self, checker: LocalSpellChecker, parent: QWidget | None = None):
        super().__init__(parent)
        self.checker = checker
        self.highlighter = SpellHighlighter(self.document(), checker)
        self.slash_palette: SlashCommandPalette | None = None

    def set_slash_palette(self, palette: "SlashCommandPalette") -> None:
        self.slash_palette = palette

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.interactionStarted.emit()
        if self.slash_palette and self.slash_palette.isVisible():
            if event.key() == Qt.Key_Escape:
                self.slash_palette.dismiss()
                event.accept()
                return
            if event.key() in (Qt.Key_Up, Qt.Key_Down):
                self.slash_palette.move_selection(-1 if event.key() == Qt.Key_Up else 1)
                event.accept()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab) and not (
                event.modifiers() & Qt.ShiftModifier
            ):
                self.slash_palette.activate_current()
                event.accept()
                return
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.modifiers() & Qt.ShiftModifier
        ):
            event.accept()
            self.submitRequested.emit()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.interactionStarted.emit()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt API
        menu = self.createStandardContextMenu()
        cursor = self.cursorForPosition(event.pos())
        self._add_spelling_actions(menu, cursor)
        menu.exec(event.globalPos())

    def _add_spelling_actions(self, menu, cursor: QTextCursor) -> None:
        cursor.select(QTextCursor.WordUnderCursor)
        word = cursor.selectedText()
        issue = next(
            (item for item in self.checker.misspellings(word) if item.word == word), None
        )
        if not issue:
            return

        first_standard_action = menu.actions()[0] if menu.actions() else None
        for suggestion in issue.suggestions[:5]:
            replacement = _match_word_case(word, suggestion)
            action = QAction(replacement, menu)
            action.setToolTip(f"Substituir “{word}” por “{replacement}”")
            action.triggered.connect(
                lambda _checked=False, value=replacement, target=QTextCursor(cursor): (
                    target.insertText(value)
                )
            )
            menu.insertAction(first_standard_action, action)
        add_action = QAction(f"Adicionar “{word}” ao dicionário", menu)
        add_action.triggered.connect(lambda: self._add_word(word))
        menu.insertAction(first_standard_action, add_action)
        menu.insertSeparator(first_standard_action)

    def _add_word(self, word: str) -> None:
        self.checker.add_word(word)
        self.highlighter.rehighlight()


def _match_word_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class SlashCommandPalette(QFrame):
    """Keyboard-first overlay used by the Mary composer slash menu."""

    itemChosen = Signal(object)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("slashPalette")
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumWidth(360)
        self.setMaximumWidth(760)
        self.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(5)
        self.title = QLabel("Comandos e ferramentas")
        self.title.setObjectName("slashPaletteTitle")
        layout.addWidget(self.title)
        self.list = QListWidget()
        self.list.setObjectName("slashPaletteList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._activate_item)
        layout.addWidget(self.list)

    def set_entries(
        self, entries: list[dict[str, Any]], title: str = "Comandos e ferramentas"
    ) -> None:
        self.title.setText(title)
        self.list.clear()
        for entry in entries:
            kind = str(entry.get("kind") or "")
            if kind == "section":
                item = QListWidgetItem(str(entry.get("name") or ""))
                item.setData(Qt.UserRole, entry)
                item.setFlags(Qt.NoItemFlags)
            else:
                name = str(entry.get("name") or "")
                description = str(entry.get("description") or "").strip()
                source = str(entry.get("source") or "").strip()
                detail = " \u00b7 ".join(value for value in (description, source) if value)
                item = QListWidgetItem(name + (f"\n{detail}" if detail else ""))
                icon = entry.get("icon")
                if isinstance(icon, QIcon) and not icon.isNull():
                    item.setIcon(icon)
                item.setData(Qt.UserRole, entry)
                if not entry.get("enabled", True):
                    item.setFlags(Qt.NoItemFlags)
                    item.setToolTip(str(entry.get("disabledReason") or description))
            self.list.addItem(item)
        self._select_first()
        rows = max(1, min(9, self.list.count()))
        self.setFixedHeight(min(430, 46 + rows * 48))

    def show_above(self, editor: QWidget, host: QWidget) -> None:
        width = max(360, min(760, editor.width()))
        self.setFixedWidth(width)
        origin = editor.mapTo(host, QPoint(0, 0))
        x = max(8, min(origin.x(), max(8, host.width() - width - 8)))
        y = max(8, origin.y() - self.height() - 8)
        self.move(x, y)
        self.raise_()
        self.show()

    def dismiss(self) -> None:
        self.hide()

    def move_selection(self, step: int) -> None:
        if not self.list.count():
            return
        start = self.list.currentRow()
        for offset in range(1, self.list.count() + 1):
            row = (start + step * offset) % self.list.count()
            item = self.list.item(row)
            if item.flags() != Qt.NoItemFlags:
                self.list.setCurrentRow(row)
                self.list.scrollToItem(item)
                return

    def activate_current(self) -> None:
        self._activate_item(self.list.currentItem())

    def _activate_item(self, item: QListWidgetItem | None) -> None:
        if not item or item.flags() == Qt.NoItemFlags:
            return
        payload = item.data(Qt.UserRole)
        if isinstance(payload, dict):
            self.itemChosen.emit(payload)

    def _select_first(self) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.flags() != Qt.NoItemFlags:
                self.list.setCurrentRow(row)
                return


class DescriptiveComboBox(QComboBox):
    """Compact combo with a readable, Codex-like popup."""

    popup_title = "Opções"

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        dialog = QDialog(self)
        dialog.setObjectName("optionPickerPopup")
        dialog.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(4)
        title = QLabel(self.popup_title)
        title.setObjectName("optionPickerTitle")
        layout.addWidget(title)
        choices = QListWidget()
        choices.setObjectName("optionPickerList")
        choices.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for index in range(self.count()):
            label = self.itemText(index)
            description = str(self.itemData(index, Qt.ToolTipRole) or "").strip()
            prefix = "✓ " if index == self.currentIndex() else ""
            item = QListWidgetItem(prefix + label + (f"\n{description}" if description else ""))
            icon = self.itemIcon(index)
            if not icon.isNull():
                item.setIcon(icon)
            item.setData(Qt.UserRole, index)
            choices.addItem(item)
        choices.itemClicked.connect(
            lambda item: (self.setCurrentIndex(int(item.data(Qt.UserRole))), dialog.accept())
        )
        layout.addWidget(choices)
        rows = max(1, self.count())
        width = max(270, min(390, self.width() + 170))
        dialog.resize(width, min(420, 48 + rows * 58))
        origin = self.mapToGlobal(QPoint(0, self.height() + 5))
        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            x = max(available.left() + 6, min(origin.x(), available.right() - width - 6))
            y = origin.y()
            if y + dialog.height() > available.bottom() - 6:
                y = max(available.top() + 6, self.mapToGlobal(QPoint(0, -dialog.height() - 5)).y())
            dialog.move(x, y)
        dialog.exec()


class ApprovalPickerCombo(DescriptiveComboBox):
    popup_title = "Permissões"


class ReasoningTierCombo(QComboBox):
    """Reasoning selector that also exposes service tier in one compact popup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tier_combo: QComboBox | None = None

    def set_tier_combo(self, combo: QComboBox) -> None:
        self._tier_combo = combo

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        dialog = QDialog(self)
        dialog.setObjectName("optionPickerPopup")
        dialog.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(4)
        choices = QListWidget()
        choices.setObjectName("optionPickerList")
        choices.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        def add_section(label: str) -> None:
            item = QListWidgetItem(label)
            item.setFlags(Qt.NoItemFlags)
            item.setData(Qt.UserRole, ("section", -1))
            choices.addItem(item)

        add_section("RACIOCÍNIO")
        for index in range(self.count()):
            prefix = "✓ " if index == self.currentIndex() else ""
            item = QListWidgetItem(prefix + self.itemText(index))
            item.setData(Qt.UserRole, ("reasoning", index))
            choices.addItem(item)
        if self._tier_combo is not None:
            add_section("CAMADA DE SERVIÇO")
            for index in range(self._tier_combo.count()):
                suffix = "  Padrão" if not self._tier_combo.itemData(index) else ""
                prefix = "✓ " if index == self._tier_combo.currentIndex() else ""
                item = QListWidgetItem(prefix + self._tier_combo.itemText(index) + suffix)
                item.setData(Qt.UserRole, ("tier", index))
                choices.addItem(item)

        def choose(item: QListWidgetItem) -> None:
            kind, index = item.data(Qt.UserRole)
            if kind == "reasoning":
                self.setCurrentIndex(index)
            elif kind == "tier" and self._tier_combo is not None:
                self._tier_combo.setCurrentIndex(index)
            dialog.accept()

        choices.itemClicked.connect(choose)
        layout.addWidget(choices)
        rows = choices.count()
        width = max(190, self.width() + 100)
        dialog.resize(width, min(470, 20 + rows * 36))
        origin = self.mapToGlobal(QPoint(0, self.height() + 5))
        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            x = max(available.left() + 6, min(origin.x(), available.right() - width - 6))
            y = origin.y()
            if y + dialog.height() > available.bottom() - 6:
                y = max(available.top() + 6, self.mapToGlobal(QPoint(0, -dialog.height() - 5)).y())
            dialog.move(x, y)
        dialog.exec()


class ModelPickerCombo(QComboBox):
    providerModelSelected = Signal(str, str)
    retryRequested = Signal(str)
    catalogChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalogs: dict[str, list[dict[str, Any]]] = {}
        self._catalog_states: dict[str, str] = {}
        self._catalog_errors: dict[str, str] = {}
        self._active_provider = "codex"
        self._settings = QSettings()
        self._favorite_shortcuts: list[QShortcut] = []
        for number in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(
                lambda position=number - 1: self._select_ranked_model(position)
            )
            self._favorite_shortcuts.append(shortcut)

    def set_provider_models(self, provider: str, models: list[dict[str, Any]]) -> None:
        self._catalogs[provider] = list(models)
        self._catalog_states[provider] = "ready"
        self._catalog_errors.pop(provider, None)
        self.catalogChanged.emit()

    def set_active_provider(self, provider: str) -> None:
        self._active_provider = provider

    def set_catalog_state(self, provider: str, state: str, error: str = "") -> None:
        self._catalog_states[provider] = state
        if error:
            self._catalog_errors[provider] = error
        elif state != "error":
            self._catalog_errors.pop(provider, None)
        self.catalogChanged.emit()

    def catalog_state(self, provider: str) -> str:
        return self._catalog_states.get(provider, "idle")

    def _ranked_models(self) -> list[tuple[str, str]]:
        favorites = set(self._settings.value("chat/model_favorites", [], list) or [])
        rows: list[tuple[bool, bool, str, str, str]] = []
        for provider_name, models in self._catalogs.items():
            for model in models:
                model_id = str(model.get("id") or model.get("model") or "")
                if not model_id:
                    continue
                key = f"{provider_name}:{model_id}"
                label = str(model.get("displayName") or model_id)
                rows.append(
                    (key in favorites, bool(model.get("isDefault")), label, provider_name, model_id)
                )
        rows.sort(key=lambda row: (not row[0], not row[1], row[2].casefold()))
        return [(row[3], row[4]) for row in rows]

    def _select_ranked_model(self, position: int) -> None:
        ranked = self._ranked_models()
        if 0 <= position < len(ranked):
            self.providerModelSelected.emit(*ranked[position])

    def _place_popup(self, dialog: QDialog) -> None:
        screen = self.screen()
        if not screen:
            return
        available = screen.availableGeometry()
        width = min(520, max(320, available.width() - 24))
        height = min(560, max(300, available.height() - 24))
        dialog.resize(width, height)
        below = self.mapToGlobal(QPoint(0, self.height() + 6))
        x = max(available.left() + 8, min(below.x(), available.right() - width - 8))
        if below.y() + height <= available.bottom() - 8:
            y = below.y()
        else:
            above = self.mapToGlobal(QPoint(0, -height - 6)).y()
            y = max(available.top() + 8, above)
        dialog.move(x, y)

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        dialog = QDialog(self)
        dialog.setObjectName("modelPickerPopup")
        dialog.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        dialog.setAccessibleName("Selecionar modelo")
        dialog.resize(520, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        provider = QTabBar()
        provider.setObjectName("modelProviderTabs")
        provider.setDocumentMode(True)
        provider.setDrawBase(False)
        provider.setShape(QTabBar.RoundedWest)
        provider.setExpanding(False)
        provider.setFixedWidth(48)
        all_index = provider.addTab(QIcon(str(ASSET_DIR / "model-all.svg")), "")
        provider.setTabToolTip(all_index, "Todos os modelos")
        provider.setTabData(all_index, "")
        for name in ("codex", "claude"):
            index = provider.addTab(provider_icon(name), "")
            provider.setTabToolTip(index, name.title())
            provider.setTabData(index, name)
        body.addWidget(provider, 0, Qt.AlignTop)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(8)
        search = QLineEdit()
        search.setObjectName("modelPickerSearch")
        search.setPlaceholderText("Pesquisar modelos…")
        content_layout.addWidget(search)
        model_list = QListWidget()
        content_layout.addWidget(model_list, 1)
        status = QLabel()
        status.setWordWrap(True)
        status.setObjectName("muted")
        content_layout.addWidget(status)
        retry = QPushButton("Tentar novamente")
        retry.setObjectName("modelPickerAction")
        favorite = QPushButton("☆ Favoritar")
        favorite.setObjectName("modelPickerAction")
        actions = QHBoxLayout()
        actions.addWidget(favorite)
        actions.addStretch()
        actions.addWidget(retry)
        content_layout.addLayout(actions)
        body.addWidget(content, 1)
        layout.addLayout(body)
        favorites = set(self._settings.value("chat/model_favorites", [], list) or [])

        def refresh() -> None:
            selected_provider = str(provider.tabData(provider.currentIndex()) or "")
            term = search.text().strip().casefold()
            rows: list[tuple[bool, str, dict[str, Any]]] = []
            for provider_name, models in self._catalogs.items():
                if selected_provider and provider_name != selected_provider:
                    continue
                for model in models:
                    model_id = str(model.get("id") or model.get("model") or "")
                    haystack = " ".join(
                        [
                            model_id,
                            str(model.get("displayName") or ""),
                            str(model.get("description") or ""),
                            provider_name,
                        ]
                    ).casefold()
                    if term and term not in haystack:
                        continue
                    key = f"{provider_name}:{model_id}"
                    rows.append((key in favorites, provider_name, model))
            rows.sort(
                key=lambda item: (
                    not item[0],
                    not bool(item[2].get("isDefault")),
                    str(item[2].get("displayName") or item[2].get("id") or "").casefold(),
                )
            )
            model_list.clear()
            default_provider = selected_provider or self._active_provider
            default_haystack = f"modelo padrão default {default_provider}".casefold()
            if not term or term in default_haystack:
                default_item = QListWidgetItem(
                    "Modelo padrão\n"
                    f"{default_provider.title()} · escolha recomendada pelo provedor"
                )
                default_item.setIcon(provider_icon(default_provider))
                default_item.setData(Qt.UserRole, (default_provider, ""))
                model_list.addItem(default_item)
            for index, (is_favorite, provider_name, model) in enumerate(rows, start=1):
                model_id = str(model.get("id") or model.get("model") or "")
                label = str(model.get("displayName") or model_id)
                suffix = " · padrão" if model.get("isDefault") else ""
                shortcut = f"  Ctrl+{index}" if index <= 9 else ""
                capabilities = (
                    model.get("capabilities")
                    or model.get("inputModalities")
                    or model.get("supportedInputModalities")
                    or []
                )
                if isinstance(capabilities, dict):
                    capabilities = [name for name, enabled in capabilities.items() if enabled]
                capability_text = (
                    " · " + ", ".join(map(str, capabilities))
                    if isinstance(capabilities, (list, tuple)) and capabilities
                    else ""
                )
                item = QListWidgetItem(
                    f"{'★' if is_favorite else '☆'} {label}{suffix}{shortcut}\n"
                    f"{provider_name.title()} · {model.get('description') or model_id}{capability_text}"
                )
                item.setIcon(provider_icon(provider_name))
                item.setData(Qt.UserRole, (provider_name, model_id))
                model_list.addItem(item)
            if model_list.count():
                model_list.setCurrentRow(0)
            state_providers = (
                [selected_provider]
                if selected_provider
                else [name for name in ("codex", "claude") if name in self._catalog_states]
            )
            loading = [
                name for name in state_providers if self._catalog_states.get(name) == "loading"
            ]
            errors = [
                self._catalog_errors.get(name, "")
                for name in state_providers
                if self._catalog_states.get(name) == "error"
            ]
            if rows:
                status.clear()
            elif loading:
                status.setText("Carregando modelos…")
            elif errors:
                status.setText(errors[0])
            else:
                status.setText("Nenhum modelo disponível neste provedor.")
            retry.setVisible(bool(errors) or (not rows and not loading))
            favorite.setEnabled(
                bool(model_list.currentItem())
                and bool(model_list.currentItem().data(Qt.UserRole)[1])
            )

        def choose() -> None:
            item = model_list.currentItem()
            if not item:
                return
            provider_name, model_id = item.data(Qt.UserRole)
            self.providerModelSelected.emit(provider_name, model_id)
            dialog.accept()

        def toggle_favorite() -> None:
            item = model_list.currentItem()
            if not item:
                return
            provider_name, model_id = item.data(Qt.UserRole)
            key = f"{provider_name}:{model_id}"
            if key in favorites:
                favorites.remove(key)
            else:
                favorites.add(key)
            self._settings.setValue("chat/model_favorites", sorted(favorites))
            refresh()

        def refresh_favorite() -> None:
            item = model_list.currentItem()
            if not item:
                favorite.setEnabled(False)
                favorite.setText("☆ Favoritar")
                return
            provider_name, model_id = item.data(Qt.UserRole)
            favorite.setEnabled(bool(model_id))
            favorite.setText(
                "★ Remover favorito"
                if f"{provider_name}:{model_id}" in favorites
                else "☆ Favoritar"
            )

        def retry_models() -> None:
            selected_provider = str(provider.tabData(provider.currentIndex()) or "")
            self.retryRequested.emit(selected_provider or self._active_provider)

        search.textChanged.connect(refresh)
        search.returnPressed.connect(choose)
        provider.currentChanged.connect(refresh)
        model_list.itemActivated.connect(lambda _item: choose())
        model_list.currentItemChanged.connect(lambda _current, _previous: refresh_favorite())
        favorite.clicked.connect(toggle_favorite)
        retry.clicked.connect(retry_models)
        self.catalogChanged.connect(refresh)
        refresh()
        self._place_popup(dialog)
        search.setFocus()
        try:
            dialog.exec()
        finally:
            self.catalogChanged.disconnect(refresh)


class ApprovalDialog(QDialog):
    def __init__(self, payload: dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aprovação solicitada")
        self.resize(680, 460)
        self.approved = False
        self.session = False
        self.action = (
            "cancel"
            if payload.get("method") == "mcpServer/elicitation/request"
            else "decline"
        )
        layout = QVBoxLayout(self)
        reason = payload.get("reason") or "O agente solicitou autorização para continuar."
        layout.addWidget(QLabel(str(reason)))
        summary_fields = (
            ("Comando", payload.get("command")),
            ("Diretório", payload.get("cwd")),
            ("Arquivos", payload.get("files") or payload.get("fileChanges")),
            ("Rede", payload.get("network") or payload.get("additionalPermissions")),
            ("Justificativa", payload.get("justification") or payload.get("reason")),
            ("Permissões", payload.get("permissions") or payload.get("requestedPermissions")),
            ("Servidor MCP", payload.get("serverName")),
        )
        summary = "\n".join(
            f"{label}: {json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}"
            for label, value in summary_fields
            if value not in (None, "", [], {})
        )
        if summary:
            summary_box = QPlainTextEdit(summary)
            summary_box.setReadOnly(True)
            summary_box.setMaximumHeight(145)
            layout.addWidget(summary_box)
        details = QPlainTextEdit(json.dumps(payload, ensure_ascii=False, indent=2))
        details.setReadOnly(True)
        layout.addWidget(details, 1)
        self.form_content: QPlainTextEdit | None = None
        if payload.get("method") == "mcpServer/elicitation/request" and payload.get("mode") in {
            "form",
            "openai/form",
        }:
            layout.addWidget(QLabel("Dados do formulário (JSON)"))
            self.form_content = QPlainTextEdit(
                json.dumps(payload.get("content") or {}, ensure_ascii=False, indent=2)
            )
            self.form_content.setMaximumHeight(130)
            layout.addWidget(self.form_content)
        buttons = QHBoxLayout()
        deny = QPushButton("Negar")
        once = QPushButton("Permitir uma vez")
        session = QPushButton("Permitir nesta sessão")
        available = set(payload.get("availableDecisions") or [])
        if available and "decline" not in available:
            deny.setVisible(False)
        if available and "accept" not in available:
            once.setVisible(False)
        if available and "acceptForSession" not in available:
            session.setVisible(False)
        deny.clicked.connect(lambda: self._finish(False, False, "decline"))
        once.clicked.connect(lambda: self._finish(True, False, "accept"))
        session.clicked.connect(lambda: self._finish(True, True, "accept"))
        buttons.addStretch()
        buttons.addWidget(deny)
        buttons.addWidget(once)
        buttons.addWidget(session)
        if payload.get("method") == "mcpServer/elicitation/request":
            cancel = QPushButton("Cancelar")
            cancel.clicked.connect(lambda: self._finish(False, False, "cancel"))
            buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _finish(self, approved: bool, session: bool, action: str) -> None:
        if approved and self.form_content is not None:
            try:
                content = json.loads(self.form_content.toPlainText() or "{}")
            except json.JSONDecodeError as exc:
                QMessageBox.warning(self, "Formulário MCP", f"JSON inválido: {exc}")
                return
            if not isinstance(content, dict):
                QMessageBox.warning(self, "Formulário MCP", "O conteúdo deve ser um objeto JSON.")
                return
        self.approved = approved
        self.session = session
        self.action = action
        self.accept()

    def response_content(self) -> dict[str, Any] | None:
        if not self.approved or self.form_content is None:
            return None
        value = json.loads(self.form_content.toPlainText() or "{}")
        return value if isinstance(value, dict) else None


class ToolEditorDialog(QDialog):
    def __init__(self, tool: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.tool = tool or {}
        self.setWindowTitle("Tool local")
        self.resize(680, 600)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(str(self.tool.get("name") or ""))
        self.description = QLineEdit(str(self.tool.get("description") or ""))
        self.schema = QPlainTextEdit(
            json.dumps(
                self.tool.get("input_schema") or {"type": "object", "properties": {}},
                ensure_ascii=False,
                indent=2,
            )
        )
        self.executable = QLineEdit(str(self.tool.get("executable") or ""))
        self.arguments = QLineEdit(
            json.dumps(self.tool.get("arguments") or [], ensure_ascii=False)
        )
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 300)
        self.timeout.setValue(int(self.tool.get("timeout_seconds") or 60))
        self.safety = QComboBox()
        self.safety.addItem("Com efeitos — pedir aprovação", "side_effecting")
        self.safety.addItem("Somente leitura", "read_only")
        index = self.safety.findData(self.tool.get("safety"))
        if index >= 0:
            self.safety.setCurrentIndex(index)
        form.addRow("Nome", self.name)
        form.addRow("Descrição", self.description)
        form.addRow("JSON Schema", self.schema)
        form.addRow("Executável", self.executable)
        form.addRow("Argumentos fixos (JSON)", self.arguments)
        form.addRow("Timeout (s)", self.timeout)
        form.addRow("Segurança", self.safety)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> dict[str, Any]:
        return {
            "name": self.name.text().strip(),
            "description": self.description.text().strip(),
            "input_schema": json.loads(self.schema.toPlainText()),
            "executable": self.executable.text().strip(),
            "arguments": json.loads(self.arguments.text() or "[]"),
            "timeout_seconds": self.timeout.value(),
            "safety": self.safety.currentData(),
        }

    def _validate(self) -> None:
        try:
            value = self.value()
            validate_tool_definition(
                value["name"], value["description"], value["input_schema"],
                value["executable"], value["arguments"],
            )
        except (ValueError, json.JSONDecodeError, ToolValidationError) as exc:
            QMessageBox.warning(self, "Tool local", str(exc))
            return
        self.accept()


class ToolSelectionDialog(QDialog):
    def __init__(
        self,
        database: MaryDatabase,
        mcp_tools: list[dict[str, Any]],
        selected: dict[str, list[Any]],
        parent=None,
    ):
        super().__init__(parent)
        self.database = database
        self.mcp_tools = mcp_tools
        self.selected = selected
        self.setWindowTitle("Tools da conversa")
        self.resize(760, 580)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        local_page = QWidget()
        local_layout = QVBoxLayout(local_page)
        self.local_list = QListWidget()
        local_layout.addWidget(self.local_list)
        local_actions = QHBoxLayout()
        add = QPushButton("+ Criar")
        edit = QPushButton("Editar")
        remove = QPushButton("Excluir")
        add.clicked.connect(self._add_tool)
        edit.clicked.connect(self._edit_tool)
        remove.clicked.connect(self._delete_tool)
        local_actions.addWidget(add)
        local_actions.addWidget(edit)
        local_actions.addWidget(remove)
        local_actions.addStretch()
        local_layout.addLayout(local_actions)
        tabs.addTab(local_page, "Tools locais")
        mcp_page = QWidget()
        mcp_layout = QVBoxLayout(mcp_page)
        self.mcp_list = QListWidget()
        mcp_layout.addWidget(self.mcp_list)
        tabs.addTab(mcp_page, "MCP do Codex")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_local()
        current_server = ""
        for tool in sorted(
            self.mcp_tools,
            key=lambda value: (str(value.get("server") or "").casefold(), str(value.get("tool") or "").casefold()),
        ):
            server_name = str(tool.get("server") or "")
            if server_name != current_server:
                current_server = server_name
                auth = str(tool.get("authStatus") or "desconhecida")
                header = QListWidgetItem(
                    f"{server_name} · autenticação: {auth}\n{tool.get('serverDescription') or ''}"
                )
                header.setFlags(Qt.NoItemFlags)
                self.mcp_list.addItem(header)
            if not tool.get("tool"):
                unavailable = QListWidgetItem(str(tool.get("description") or "Indisponível"))
                unavailable.setFlags(Qt.NoItemFlags)
                self.mcp_list.addItem(unavailable)
                continue
            if not tool.get("configurable", True):
                managed = QListWidgetItem(
                    f"{tool.get('tool')}\nGerenciada dinamicamente pelo Codex; seleção por thread indisponível."
                )
                managed.setFlags(Qt.NoItemFlags)
                self.mcp_list.addItem(managed)
                continue
            item = QListWidgetItem(
                f"{tool.get('tool')}\n{tool.get('description') or ''}"
            )
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            key = {"server": tool.get("server"), "tool": tool.get("tool")}
            item.setData(Qt.UserRole, key)
            item.setCheckState(Qt.Checked if key in selected.get("mcp", []) else Qt.Unchecked)
            self.mcp_list.addItem(item)

    def selection(self) -> tuple[list[str], list[dict[str, str]]]:
        dynamic = [
            str(self.local_list.item(index).data(Qt.UserRole))
            for index in range(self.local_list.count())
            if self.local_list.item(index).checkState() == Qt.Checked
        ]
        mcp = [
            self.mcp_list.item(index).data(Qt.UserRole)
            for index in range(self.mcp_list.count())
            if self.mcp_list.item(index).checkState() == Qt.Checked
        ]
        return dynamic, mcp

    def _refresh_local(self) -> None:
        checked = set(self.selected.get("dynamic", []))
        checked.update(
            str(self.local_list.item(index).data(Qt.UserRole))
            for index in range(self.local_list.count())
            if self.local_list.item(index).checkState() == Qt.Checked
        )
        self.local_list.clear()
        for tool in self.database.list_tools():
            item = QListWidgetItem(
                f"{tool['name']} · {'somente leitura' if tool['safety'] == 'read_only' else 'com efeitos'}\n"
                f"{tool['description']}"
            )
            item.setData(Qt.UserRole, tool["id"])
            item.setData(Qt.UserRole + 1, tool)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if tool["id"] in checked else Qt.Unchecked)
            self.local_list.addItem(item)

    def _add_tool(self) -> None:
        dialog = ToolEditorDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.database.create_tool(**dialog.value())
            except Exception as exc:
                QMessageBox.warning(self, "Tool local", f"Não foi possível criar a tool: {exc}")
                return
            self._refresh_local()

    def _edit_tool(self) -> None:
        item = self.local_list.currentItem()
        if not item:
            return
        tool = item.data(Qt.UserRole + 1)
        dialog = ToolEditorDialog(tool, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.database.update_tool(str(tool["id"]), **dialog.value())
            except Exception as exc:
                QMessageBox.warning(self, "Tool local", f"Não foi possível atualizar a tool: {exc}")
                return
            self._refresh_local()

    def _delete_tool(self) -> None:
        item = self.local_list.currentItem()
        if not item:
            return
        if QMessageBox.question(self, "Excluir tool", "Excluir esta definição de tool?") == QMessageBox.Yes:
            self.database.delete_tool(str(item.data(Qt.UserRole)))
            self._refresh_local()

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    Property,
    QPropertyAnimation,
    QRectF,
    QSize,
    QSettings,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QConicalGradient,
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
    QAbstractItemView,
    QApplication,
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
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionTab,
    QStylePainter,
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
        self._glow_animation.setDuration(950)
        self._glow_animation.setLoopCount(1)
        self._glow_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._glow_animation.setKeyValueAt(0.0, 0.0)
        self._glow_animation.setKeyValueAt(0.5, 1.0)
        self._glow_animation.setKeyValueAt(1.0, 0.0)
        self.toggled.connect(self._sync_state)
        self._sync_state(self.isChecked(), animate=False)

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = float(value)
        self.update()

    glow = Property(float, _get_glow, _set_glow)

    def _sync_state(self, enabled: bool, animate: bool = True) -> None:
        if enabled:
            self._glow_animation.stop()
            self._set_glow(0.0)
            if animate:
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
        if not self.isEnabled():
            painter.setOpacity(0.55)
        body = QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -2.0)
        radius = body.height() / 2.0

        if self.isChecked():
            pulse = max(0.0, min(1.0, self._glow))
            painter.setPen(QPen(QColor(255, 189, 15, 95 + int(130 * pulse)), 2.2))
            gradient = QLinearGradient(body.topLeft(), body.bottomRight())
            gradient.setColorAt(0.0, QColor("#B34700"))
            gradient.setColorAt(0.55, QColor("#973200"))
            gradient.setColorAt(1.0, QColor("#762600"))
            painter.setBrush(gradient)
            text_color = QColor("#FFFFFF")
            star_color = QColor("#FFF1B8")
        else:
            application = QApplication.instance()
            dark = bool(
                application
                and application.property("mary_theme") == "dark_orange"
            )
            painter.setPen(QPen(QColor("#756A63" if dark else "#B9B9C5"), 1.2))
            painter.setBrush(QColor("#24201D" if dark else "#F1F1F5"))
            text_color = QColor("#B8AEA7" if dark else "#5F5F70")
            star_color = QColor("#9D9189" if dark else "#777789")
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


class VrComposerGlowFrame(QFrame):
    """Orange-spectrum aurora around the composer while the VR flow is active."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chatComposerGlow")
        self._vr_active = False
        self._phase = 0.0
        self._phase_animation = QPropertyAnimation(self, b"phase", self)
        self._phase_animation.setDuration(1100)
        self._phase_animation.setLoopCount(1)
        self._phase_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._phase_animation.setStartValue(0.0)
        self._phase_animation.setEndValue(1.0)

    def _get_phase(self) -> float:
        return self._phase

    def _set_phase(self, value: float) -> None:
        self._phase = float(value)
        self.update()

    phase = Property(float, _get_phase, _set_phase)

    def set_vr_active(self, enabled: bool, *, animate: bool = True) -> None:
        enabled = bool(enabled)
        changed = enabled != self._vr_active
        self._vr_active = enabled
        if not enabled:
            self._phase_animation.stop()
            self._set_phase(0.0)
            return
        if animate and changed:
            self._phase_animation.stop()
            self._set_phase(0.0)
            self._phase_animation.start()
        else:
            self.update()

    def vr_active(self) -> bool:
        return self._vr_active

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if not self._vr_active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bounds = QRectF(self.rect()).adjusted(3.0, 3.0, -3.0, -3.0)
        gradient = QConicalGradient(
            bounds.center(),
            -90.0 + (360.0 * self._phase),
        )
        gradient.setColorAt(0.00, QColor("#7A3500"))
        gradient.setColorAt(0.18, QColor("#FF7200"))
        gradient.setColorAt(0.36, QColor("#FCBD0F"))
        gradient.setColorAt(0.55, QColor("#E85B00"))
        gradient.setColorAt(0.74, QColor("#C45100"))
        gradient.setColorAt(0.90, QColor("#FF9A3D"))
        gradient.setColorAt(1.00, QColor("#7A3500"))
        if self._phase_animation.state() == QPropertyAnimation.Running:
            pulse = 1.0 - abs((2.0 * self._phase) - 1.0)
            painter.setOpacity(0.16 + (0.18 * pulse))
            painter.setPen(QPen(QBrush(gradient), 6.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(bounds, 27.0, 27.0)
        painter.setOpacity(1.0)
        painter.setPen(QPen(QBrush(gradient), 2.4))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(bounds, 27.0, 27.0)


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


def _apply_rounded_mask(widget: QWidget, radius: float) -> None:
    """Clip a top-level Qt popup; border-radius alone does not clip its window."""
    if widget.width() <= 0 or widget.height() <= 0:
        return
    path = QPainterPath()
    path.addRoundedRect(QRectF(widget.rect()), radius, radius)
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


class RoundedPopupDialog(QDialog):
    """Frameless popup whose native window is clipped to the painted radius."""

    def __init__(self, parent: QWidget | None = None, radius: float = 18.0):
        super().__init__(parent)
        self._popup_radius = float(radius)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        _apply_rounded_mask(self, self._popup_radius)
        super().showEvent(event)

    def event(self, event) -> bool:
        handled = super().event(event)
        if (
            event.type() == QEvent.WindowDeactivate
            and self.property("closeOnDeactivate")
            and self.isVisible()
        ):
            self.reject()
        return handled

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        _apply_rounded_mask(self, self._popup_radius)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Paint an opaque rounded surface even on translucent native windows."""
        super().paintEvent(event)
        application = QApplication.instance()
        dark = bool(
            application and application.property("mary_theme") == "dark_orange"
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#756A63" if dark else "#CBCBD7"), 1))
        painter.setBrush(QColor("#1B1816" if dark else "#FFFFFF"))
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(
            bounds,
            self._popup_radius,
            self._popup_radius,
        )


class RoundedOverlayFrame(QFrame):
    """In-window dropdown layer that avoids a separate native popup window."""

    closed = Signal()

    def __init__(
        self,
        parent: QWidget,
        anchor: QWidget,
        radius: float = 18.0,
    ):
        super().__init__(parent)
        self._anchor = anchor
        self._popup_radius = float(radius)
        self._close_notified = False
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._close_notified = False
        _apply_rounded_mask(self, self._popup_radius)
        super().showEvent(event)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        super().hideEvent(event)
        if not self._close_notified:
            self._close_notified = True
            self.closed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        _apply_rounded_mask(self, self._popup_radius)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget):
            if not self._contains_widget(watched):
                if self._contains_anchor(watched):
                    self.close()
                    return True
                self.close()
        elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.close()
            return True
        elif (
            event.type() in {QEvent.Resize, QEvent.Hide}
            and watched is self.parentWidget()
        ):
            self.close()
        return False

    def _contains_widget(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            if current is self:
                return True
            current = current.parentWidget()
        return False

    def _contains_anchor(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            if current is self._anchor:
                return True
            current = current.parentWidget()
        return False


class EmbeddedPickerPanel(QFrame):
    """Rounded picker content embedded in the chat layout, never a popup window."""

    closed = Signal()

    def __init__(self, parent: QWidget, radius: float = 18.0):
        super().__init__(parent)
        self._panel_radius = float(radius)
        self._close_notified = False
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._close_notified = False
        _apply_rounded_mask(self, self._panel_radius)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().hideEvent(event)
        if not self._close_notified:
            self._close_notified = True
            self.closed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        _apply_rounded_mask(self, self._panel_radius)


class RoundedComboBox(QComboBox):
    """Standard combo with a genuinely rounded, clipped popup container."""

    popup_radius = 12.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rounded_popup_container: QWidget | None = None

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        self._prepare_popup_container()
        super().showPopup()
        QTimer.singleShot(0, self._refresh_popup_mask)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self._rounded_popup_container and event.type() in {
            QEvent.Show,
            QEvent.Resize,
        }:
            QTimer.singleShot(0, self._refresh_popup_mask)
        return super().eventFilter(watched, event)

    def _prepare_popup_container(self) -> None:
        container = self.view().window()
        if container is self._rounded_popup_container:
            return
        if self._rounded_popup_container is not None:
            self._rounded_popup_container.removeEventFilter(self)
        self._rounded_popup_container = container
        container.setObjectName("roundedComboPopup")
        container.setAttribute(Qt.WA_TranslucentBackground, True)
        container.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        container.installEventFilter(self)

    def _refresh_popup_mask(self) -> None:
        if self._rounded_popup_container is not None:
            _apply_rounded_mask(
                self._rounded_popup_container,
                self.popup_radius,
            )


class ModelOptionRow(QFrame):
    """Compact model card inspired by the Codex picker reference."""

    activated = Signal()
    favoriteToggled = Signal()

    def __init__(
        self,
        *,
        icon: QIcon,
        title: str,
        provider: str,
        shortcut: str = "",
        favorite: bool = False,
        can_favorite: bool = True,
        tooltip: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("modelOptionRow")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(60)
        self.setToolTip(tooltip)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(9)

        icon_label = QLabel(objectName="modelOptionIcon")
        icon_label.setFixedSize(22, 22)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(icon.pixmap(QSize(19, 19)))
        icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(icon_label)

        labels = QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(1)
        title_label = QLabel(title, objectName="modelOptionTitle")
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        meta_label = QLabel(provider.title(), objectName="modelOptionMeta")
        meta_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        meta_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        labels.addWidget(title_label)
        labels.addWidget(meta_label)
        layout.addLayout(labels, 1)

        shortcut_label = QLabel(shortcut, objectName="modelShortcutBadge")
        shortcut_label.setVisible(bool(shortcut))
        shortcut_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(shortcut_label)

        self.favorite_button = QToolButton(objectName="modelFavoriteButton")
        favorite_asset = "model-favorite-active.svg" if favorite else "model-favorite.svg"
        self.favorite_button.setIcon(QIcon(str(ASSET_DIR / favorite_asset)))
        self.favorite_button.setIconSize(QSize(15, 15))
        self.favorite_button.setAccessibleName(
            "Remover modelo dos favoritos" if favorite else "Adicionar modelo aos favoritos"
        )
        self.favorite_button.setVisible(can_favorite)
        self.favorite_button.clicked.connect(self.favoriteToggled)
        layout.addWidget(self.favorite_button)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ModelLegacyRow(QFrame):
    """Collapsible summary for older models."""

    toggled = Signal()

    def __init__(self, count: int, expanded: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("modelLegacyRow")
        self.setAccessibleName("Modelos legados")
        self.setAccessibleDescription(f"Grupo com {count} modelos")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(58)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        labels = QVBoxLayout()
        labels.setSpacing(1)
        title = QLabel("Modelos legados", objectName="modelLegacyTitle")
        count_label = QLabel(f"{count} modelos", objectName="modelLegacyMeta")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        count_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        labels.addWidget(title)
        labels.addWidget(count_label)
        layout.addLayout(labels, 1)
        chevron = QLabel("⌄" if expanded else "›", objectName="modelLegacyChevron")
        chevron.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(chevron)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self.toggled.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AccessibleIconTabBar(QTabBar):
    """Paint icon-only tabs while preserving their text for assistive tools."""

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802 - Qt API
        del index
        return QSize(50, 48)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QStylePainter(self)
        selected = self.currentIndex()
        order = [index for index in range(self.count()) if index != selected]
        if selected >= 0:
            order.append(selected)
        for index in order:
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            option.text = ""
            painter.drawControl(QStyle.CE_TabBarTab, option)


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


class DescriptiveComboBox(RoundedComboBox):
    """Compact combo with a readable, Codex-like popup."""

    popup_title = "Opções"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._option_popup: RoundedOverlayFrame | None = None

    def _place_option_popup(
        self,
        popup: QWidget,
        width: int,
        height: int,
    ) -> None:
        host = popup.parentWidget() or self.window()
        available = host.rect().adjusted(8, 8, -8, -8)
        width = max(1, min(width, available.width()))
        height = max(1, min(height, available.height()))
        popup.resize(width, height)
        below = self.mapTo(host, QPoint(0, self.height() + 5))
        x = max(available.left(), min(below.x(), available.right() - width + 1))
        if below.y() + height <= available.bottom():
            y = below.y()
        else:
            y = max(
                available.top(),
                self.mapTo(host, QPoint(0, -height - 5)).y(),
            )
        popup.move(x, y)

    def hidePopup(self) -> None:  # noqa: N802 - Qt API
        if self._option_popup is not None:
            self._option_popup.close()

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        if self._option_popup is not None and self._option_popup.isVisible():
            self._option_popup.raise_()
            return
        dialog = RoundedOverlayFrame(self.window(), self)
        dialog.setObjectName("optionPickerPopup")
        dialog.setAccessibleName(self.popup_title)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        title = QLabel(self.popup_title)
        title.setObjectName("optionPickerTitle")
        layout.addWidget(title)
        choices = QListWidget()
        choices.setObjectName("optionPickerList")
        choices.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        choices.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        choices.setWordWrap(True)
        choices.setTextElideMode(Qt.ElideNone)
        for index in range(self.count()):
            label = self.itemText(index)
            description = str(self.itemData(index, Qt.ToolTipRole) or "").strip()
            prefix = "✓ " if index == self.currentIndex() else ""
            item = QListWidgetItem(prefix + label + (f"\n{description}" if description else ""))
            icon = self.itemIcon(index)
            if not icon.isNull():
                item.setIcon(icon)
            item.setData(Qt.UserRole, index)
            item.setSizeHint(QSize(0, 76 if description else 44))
            choices.addItem(item)

        def choose(item: QListWidgetItem) -> None:
            self.setCurrentIndex(int(item.data(Qt.UserRole)))
            dialog.close()

        choices.itemClicked.connect(choose)
        choices.itemActivated.connect(choose)
        layout.addWidget(choices)
        content_height = 58 + sum(
            choices.item(index).sizeHint().height()
            for index in range(choices.count())
        )
        width = max(320, min(370, self.width() + 230))
        self._place_option_popup(dialog, width, min(390, content_height))
        self._option_popup = dialog

        def cleanup_popup() -> None:
            if self._option_popup is dialog:
                self._option_popup = None
            dialog.deleteLater()

        dialog.closed.connect(cleanup_popup)
        dialog.show()
        dialog.raise_()
        if choices.count():
            choices.setCurrentRow(max(0, self.currentIndex()))
        choices.setFocus()


class ApprovalPickerCombo(DescriptiveComboBox):
    popup_title = "Permissões"


class ReasoningTierCombo(RoundedComboBox):
    """Reasoning selector that also exposes service tier in one compact popup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tier_combo: QComboBox | None = None
        self._option_popup: RoundedOverlayFrame | None = None

    def set_tier_combo(self, combo: QComboBox) -> None:
        self._tier_combo = combo

    def hidePopup(self) -> None:  # noqa: N802 - Qt API
        if self._option_popup is not None:
            self._option_popup.close()

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        if self._option_popup is not None and self._option_popup.isVisible():
            self._option_popup.raise_()
            return
        dialog = RoundedOverlayFrame(self.window(), self)
        dialog.setObjectName("optionPickerPopup")
        dialog.setAccessibleName("Raciocínio e camada de serviço")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(0)
        choices = QListWidget()
        choices.setObjectName("optionPickerList")
        choices.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        choices.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        choices.setTextElideMode(Qt.ElideNone)

        def add_section(label: str) -> None:
            item = QListWidgetItem(label)
            item.setFlags(Qt.NoItemFlags)
            item.setData(Qt.UserRole, ("section", -1))
            item.setSizeHint(QSize(0, 30))
            choices.addItem(item)

        add_section("RACIOCÍNIO")
        for index in range(self.count()):
            prefix = "✓ " if index == self.currentIndex() else ""
            item = QListWidgetItem(prefix + self.itemText(index))
            item.setData(Qt.UserRole, ("reasoning", index))
            item.setSizeHint(QSize(0, 36))
            choices.addItem(item)
        if self._tier_combo is not None:
            add_section("CAMADA DE SERVIÇO")
            for index in range(self._tier_combo.count()):
                suffix = "  Padrão" if not self._tier_combo.itemData(index) else ""
                prefix = "✓ " if index == self._tier_combo.currentIndex() else ""
                item = QListWidgetItem(prefix + self._tier_combo.itemText(index) + suffix)
                item.setData(Qt.UserRole, ("tier", index))
                item.setSizeHint(QSize(0, 36))
                choices.addItem(item)

        def choose(item: QListWidgetItem) -> None:
            kind, index = item.data(Qt.UserRole)
            if kind == "reasoning":
                self.setCurrentIndex(index)
            elif kind == "tier" and self._tier_combo is not None:
                self._tier_combo.setCurrentIndex(index)
            else:
                return
            dialog.close()

        choices.itemClicked.connect(choose)
        choices.itemActivated.connect(choose)
        layout.addWidget(choices)
        content_height = 14 + sum(
            choices.item(index).sizeHint().height()
            for index in range(choices.count())
        )
        width = max(205, min(228, self.width() + 115))
        helper = DescriptiveComboBox._place_option_popup
        helper(self, dialog, width, min(312, content_height))
        self._option_popup = dialog

        def cleanup_popup() -> None:
            if self._option_popup is dialog:
                self._option_popup = None
            dialog.deleteLater()

        dialog.closed.connect(cleanup_popup)
        dialog.show()
        dialog.raise_()
        selected_row = 1 + max(0, self.currentIndex())
        if selected_row < choices.count():
            choices.setCurrentRow(selected_row)
        choices.setFocus()


class ModelPickerCombo(RoundedComboBox):
    providerModelSelected = Signal(str, str)
    retryRequested = Signal(str)
    catalogChanged = Signal()
    panelVisibilityChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalogs: dict[str, list[dict[str, Any]]] = {}
        self._catalog_states: dict[str, str] = {}
        self._catalog_errors: dict[str, str] = {}
        self._active_provider = "codex"
        self._settings = QSettings()
        self._popup_press_armed = False
        self._suppress_popup_release = False
        self._model_popup: RoundedOverlayFrame | EmbeddedPickerPanel | None = None
        self._inline_host: QWidget | None = None
        self._favorite_shortcuts: list[QShortcut] = []
        for number in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(
                lambda position=number - 1: self._select_ranked_model(position)
            )
            self._favorite_shortcuts.append(shortcut)

    def set_inline_host(self, host: QWidget) -> None:
        """Render the selector inside ``host`` instead of as a floating layer."""
        self._inline_host = host

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            if self._suppress_popup_release:
                self._suppress_popup_release = False
                self._popup_press_armed = False
                event.accept()
                return
            self._popup_press_armed = self.rect().contains(
                event.position().toPoint()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            should_open = self._popup_press_armed and self.rect().contains(
                event.position().toPoint()
            )
            self._popup_press_armed = False
            event.accept()
            if should_open:
                # QComboBox normally opens on mouse press. This heavier custom
                # popup must wait for release or Qt treats that same click as
                # an outside click and immediately rejects the dialog.
                QTimer.singleShot(50, self.showPopup)
            return
        super().mouseReleaseEvent(event)

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
        latest_codex_version = (0, 0)
        for model in self._catalogs.get("codex", []):
            model_id = str(model.get("id") or model.get("model") or "")
            match = re.search(r"\bgpt-(\d+)\.(\d+)", model_id.casefold())
            if match:
                latest_codex_version = max(
                    latest_codex_version,
                    (int(match.group(1)), int(match.group(2))),
                )
        rows: list[tuple[bool, bool, bool, bool, int, int, str, str, str]] = []
        for provider_order, (provider_name, models) in enumerate(self._catalogs.items()):
            for model_order, model in enumerate(models):
                model_id = str(model.get("id") or model.get("model") or "")
                if not model_id:
                    continue
                key = f"{provider_name}:{model_id}"
                label = str(model.get("displayName") or model_id)
                match = re.search(r"\bgpt-(\d+)\.(\d+)", model_id.casefold())
                legacy = bool(
                    model.get("isLegacy")
                    or model.get("deprecated")
                    or str(model.get("status") or "").casefold()
                    in {"legacy", "deprecated"}
                    or (
                        provider_name == "codex"
                        and match
                        and (int(match.group(1)), int(match.group(2)))
                        < latest_codex_version
                    )
                )
                rows.append(
                    (
                        key in favorites,
                        provider_name == self._active_provider,
                        bool(model.get("isDefault")),
                        legacy,
                        provider_order,
                        model_order,
                        label,
                        provider_name,
                        model_id,
                    )
                )
        rows.sort(
            key=lambda row: (
                not row[0],
                0 if row[0] else not row[1],
                row[3],
                not row[2],
                row[4],
                row[5],
                row[6].casefold(),
            )
        )
        return [(row[7], row[8]) for row in rows]

    def _select_ranked_model(self, position: int) -> None:
        ranked = self._ranked_models()
        if 0 <= position < len(ranked):
            self.providerModelSelected.emit(*ranked[position])

    def _place_popup(self, dialog: QWidget) -> None:
        host = dialog.parentWidget() or self.window()
        available = host.rect().adjusted(8, 8, -8, -8)
        width = min(400, max(340, available.width() - 24))
        height = min(470, max(360, available.height() - 24))
        dialog.resize(width, height)
        below = self.mapTo(host, QPoint(0, self.height() + 6))
        x = max(available.left() + 8, min(below.x(), available.right() - width - 8))
        if below.y() + height <= available.bottom() - 8:
            y = below.y()
        else:
            above = self.mapTo(host, QPoint(0, -height - 6)).y()
            y = max(available.top() + 8, above)
        dialog.move(x, y)

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        if self._model_popup is not None and self._model_popup.isVisible():
            if self._inline_host is not None:
                self._model_popup.close()
                return
            self._model_popup.raise_()
            return
        inline = self._inline_host is not None
        if inline:
            dialog = EmbeddedPickerPanel(self._inline_host, radius=0.0)
            dialog.setObjectName("modelPickerPanel")
        else:
            dialog = RoundedOverlayFrame(self.window(), self)
            dialog.setObjectName("modelPickerPopup")
        dialog.setAccessibleName("Selecionar modelo")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        provider = AccessibleIconTabBar()
        provider.setObjectName("modelProviderTabs")
        provider.setDocumentMode(True)
        provider.setDrawBase(False)
        provider.setShape(QTabBar.RoundedWest)
        provider.setExpanding(False)
        provider.setFixedWidth(50)
        provider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        provider.setAccessibleName("Filtrar modelos por provedor")
        recommended_index = provider.addTab(
            QIcon(str(ASSET_DIR / "model-all.svg")), "Recomendados"
        )
        provider.setTabToolTip(recommended_index, "Modelos recomendados")
        provider.setTabData(recommended_index, "recommended")
        for name in ("codex", "claude"):
            index = provider.addTab(provider_icon(name), name.title())
            provider.setTabToolTip(index, name.title())
            provider.setTabData(index, name)
        body.addWidget(provider)

        content = QWidget(objectName="modelPickerContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(9, 9, 9, 9)
        content_layout.setSpacing(7)
        search = QLineEdit()
        search.setObjectName("modelPickerSearch")
        search.setPlaceholderText("Pesquisar modelos…")
        search.addAction(
            QIcon(str(ASSET_DIR / "model-search.svg")),
            QLineEdit.LeadingPosition,
        )
        content_layout.addWidget(search)
        model_list = QListWidget()
        model_list.setObjectName("modelPickerList")
        model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        model_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        model_list.setSpacing(2)
        content_layout.addWidget(model_list, 1)
        status = QLabel()
        status.setWordWrap(True)
        status.setObjectName("muted")
        content_layout.addWidget(status)
        retry = QPushButton("Tentar novamente")
        retry.setObjectName("modelPickerAction")
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(retry)
        content_layout.addLayout(actions)
        body.addWidget(content, 1)
        layout.addLayout(body)
        favorites = set(self._settings.value("chat/model_favorites", [], list) or [])
        shortcut_positions = {
            key: index
            for index, key in enumerate(self._ranked_models()[:9], start=1)
        }
        legacy_expanded = False

        latest_codex_version = (0, 0)
        for model in self._catalogs.get("codex", []):
            model_id = str(model.get("id") or model.get("model") or "")
            match = re.search(r"\bgpt-(\d+)\.(\d+)", model_id.casefold())
            if match:
                latest_codex_version = max(
                    latest_codex_version,
                    (int(match.group(1)), int(match.group(2))),
                )

        def is_legacy(provider_name: str, model: dict[str, Any]) -> bool:
            if bool(model.get("isLegacy") or model.get("deprecated")):
                return True
            if str(model.get("status") or "").casefold() in {"legacy", "deprecated"}:
                return True
            if provider_name != "codex" or latest_codex_version == (0, 0):
                return False
            model_id = str(model.get("id") or model.get("model") or "")
            match = re.search(r"\bgpt-(\d+)\.(\d+)", model_id.casefold())
            return bool(
                match
                and (int(match.group(1)), int(match.group(2))) < latest_codex_version
            )

        def select_item(item: QListWidgetItem) -> None:
            model_list.setCurrentItem(item)
            choose(item)

        def toggle_favorite_key(provider_name: str, model_id: str) -> None:
            key = f"{provider_name}:{model_id}"
            if key in favorites:
                favorites.remove(key)
            else:
                favorites.add(key)
            self._settings.setValue("chat/model_favorites", sorted(favorites))
            refresh()

        def add_model_row(
            provider_name: str,
            model_id: str,
            title: str,
            description: str,
            is_favorite: bool,
        ) -> QListWidgetItem:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, (provider_name, model_id))
            item.setSizeHint(QSize(0, 62))
            model_list.addItem(item)
            shortcut_number = shortcut_positions.get((provider_name, model_id))
            row = ModelOptionRow(
                icon=provider_icon(provider_name),
                title=title,
                provider=provider_name,
                shortcut=f"Ctrl+{shortcut_number}" if shortcut_number else "",
                favorite=is_favorite,
                can_favorite=bool(model_id),
                tooltip=description,
            )
            row.activated.connect(lambda target=item: select_item(target))
            if model_id:
                row.favoriteToggled.connect(
                    lambda name=provider_name, value=model_id: toggle_favorite_key(
                        name, value
                    )
                )
            model_list.setItemWidget(item, row)
            return item

        def refresh() -> None:
            nonlocal legacy_expanded
            selected_tab = str(provider.tabData(provider.currentIndex()) or "")
            selected_provider = (
                self._active_provider if selected_tab == "recommended" else selected_tab
            )
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
                )
            )
            model_list.clear()
            default_provider = selected_provider or self._active_provider
            default_haystack = f"modelo padrão default {default_provider}".casefold()
            target_provider = self._active_provider
            target_model = str(self.currentData() or "")
            selected_item: QListWidgetItem | None = None
            if not rows and (not term or term in default_haystack):
                default_item = add_model_row(
                    default_provider,
                    "",
                    "Modelo padrão",
                    f"{default_provider.title()} · escolha recomendada pelo provedor",
                    False,
                )
                if target_provider == default_provider and not target_model:
                    selected_item = default_item

            current_rows: list[tuple[bool, str, dict[str, Any]]] = []
            legacy_rows: list[tuple[bool, str, dict[str, Any]]] = []
            for row_data in rows:
                bucket = legacy_rows if is_legacy(row_data[1], row_data[2]) else current_rows
                bucket.append(row_data)

            def render_models(items: list[tuple[bool, str, dict[str, Any]]]) -> None:
                nonlocal selected_item
                for is_favorite, provider_name, model in items:
                    model_id = str(model.get("id") or model.get("model") or "")
                    label = str(model.get("displayName") or model_id)
                    item = add_model_row(
                        provider_name,
                        model_id,
                        label,
                        str(model.get("description") or model_id),
                        is_favorite,
                    )
                    if (provider_name, model_id) == (target_provider, target_model):
                        selected_item = item

            render_models(current_rows)
            selected_is_legacy = any(
                (provider_name, str(model.get("id") or model.get("model") or ""))
                == (target_provider, target_model)
                for _favorite, provider_name, model in legacy_rows
            )
            show_legacy_models = legacy_expanded or selected_is_legacy or bool(term)
            if legacy_rows:
                legacy_item = QListWidgetItem()
                legacy_item.setData(Qt.UserRole, ("legacy", ""))
                legacy_item.setData(Qt.AccessibleTextRole, "Modelos legados")
                legacy_item.setData(
                    Qt.AccessibleDescriptionRole,
                    f"Grupo com {len(legacy_rows)} modelos",
                )
                legacy_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                legacy_item.setSizeHint(QSize(0, 60))
                model_list.addItem(legacy_item)
                legacy_row = ModelLegacyRow(len(legacy_rows), show_legacy_models)

                def toggle_legacy() -> None:
                    nonlocal legacy_expanded
                    legacy_expanded = not show_legacy_models
                    refresh()

                legacy_row.toggled.connect(toggle_legacy)
                model_list.setItemWidget(legacy_item, legacy_row)
                if show_legacy_models:
                    render_models(legacy_rows)

            if selected_item is None and model_list.count():
                selected_item = next(
                    (
                        model_list.item(index)
                        for index in range(model_list.count())
                        if isinstance(model_list.item(index).data(Qt.UserRole), tuple)
                        and model_list.item(index).data(Qt.UserRole)[0] != "legacy"
                    ),
                    None,
                )
            if selected_item is not None:
                model_list.setCurrentItem(selected_item)
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

        def choose(item: QListWidgetItem | None = None) -> None:
            nonlocal legacy_expanded
            selected = item or model_list.currentItem()
            if not selected:
                return
            payload = selected.data(Qt.UserRole)
            if not isinstance(payload, tuple) or len(payload) != 2:
                return
            provider_name, model_id = payload
            if provider_name == "legacy":
                legacy_expanded = not legacy_expanded
                refresh()
                return
            self.providerModelSelected.emit(provider_name, model_id)
            dialog.close()

        def sync_selected_row(
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
        ) -> None:
            for item, selected in ((previous, False), (current, True)):
                if item is None:
                    continue
                row = model_list.itemWidget(item)
                if isinstance(row, ModelOptionRow):
                    row.set_selected(selected)

        def retry_models() -> None:
            selected_tab = str(provider.tabData(provider.currentIndex()) or "")
            selected_provider = (
                self._active_provider if selected_tab == "recommended" else selected_tab
            )
            self.retryRequested.emit(selected_provider or self._active_provider)

        def provider_changed() -> None:
            selected_tab = str(provider.tabData(provider.currentIndex()) or "")
            selected_provider = (
                self._active_provider if selected_tab == "recommended" else selected_tab
            )
            if self._catalog_states.get(selected_provider, "idle") == "idle":
                self.retryRequested.emit(selected_provider)
            refresh()

        search.textChanged.connect(refresh)
        search.returnPressed.connect(lambda: choose())
        provider.currentChanged.connect(provider_changed)
        model_list.itemActivated.connect(choose)
        model_list.currentItemChanged.connect(sync_selected_row)
        retry.clicked.connect(retry_models)
        catalog_connection = self.catalogChanged.connect(refresh)
        refresh()
        if inline:
            host_layout = self._inline_host.layout()
            if host_layout is None:
                host_layout = QVBoxLayout(self._inline_host)
                host_layout.setContentsMargins(0, 0, 0, 0)
                host_layout.setSpacing(0)
            host_layout.addWidget(dialog)
            dialog.setMinimumHeight(320)
            dialog.setMaximumHeight(390)
            dialog.setFixedHeight(360)
            self._inline_host.show()
            self.panelVisibilityChanged.emit(True)
        else:
            self._place_popup(dialog)
        self._model_popup = dialog

        def cleanup_popup() -> None:
            try:
                QObject.disconnect(catalog_connection)
            except (RuntimeError, TypeError):
                pass
            if self._model_popup is dialog:
                self._model_popup = None
            if inline and self._inline_host is not None:
                self._inline_host.hide()
                self.panelVisibilityChanged.emit(False)
            dialog.deleteLater()

        dialog.closed.connect(cleanup_popup)
        dialog.show()
        if not inline:
            dialog.raise_()
        search.setFocus()


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
        self.safety = RoundedComboBox()
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

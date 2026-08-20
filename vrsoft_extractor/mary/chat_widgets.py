from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QImageReader,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QShortcut,
    QSyntaxHighlighter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
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
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .chat_tools import ToolValidationError, validate_tool_definition
from .db import MaryDatabase
from .models import ModelRef, OrchestrationOptions
from .spellcheck import LocalSpellChecker

ASSET_DIR = Path(__file__).resolve().parent / "assets"
CODE_WRAP_ICON_PATH = ASSET_DIR / "code-wrap.svg"
CODE_COPY_ICON_PATH = ASSET_DIR / "code-copy.svg"
PROVIDER_ICON_PATHS = {
    "codex": ASSET_DIR / "provider-gpt.png",
    "claude": ASSET_DIR / "provider-claude.webp",
    "opencode": ASSET_DIR / "provider-opencode.svg",
}
_PROVIDER_ICON_CACHE: dict[str, QIcon] = {}


def application_reduced_motion() -> bool:
    """Return the application-wide motion preference used by custom widgets."""
    application = QApplication.instance()
    if application is not None:
        value = application.property("vr_reduce_motion")
        if value is not None:
            return bool(value)
    return os.environ.get("VR_REDUCE_MOTION", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def provider_display_name(provider: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude",
        "opencode": "OpenCode",
    }.get(str(provider).casefold(), str(provider).title())


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
    """Compact toggle for the local base and VR execution mode."""

    optionsRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._glow = 0.0
        self._compact = False
        self._reduced_motion = application_reduced_motion()
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(56, 32)
        self.setAccessibleName("VR: base local e modos de orquestração")

        self._glow_animation = QPropertyAnimation(self, b"glow", self)
        self._glow_animation.setDuration(160)
        self._glow_animation.setLoopCount(1)
        self._glow_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._glow_animation.setKeyValueAt(0.0, 0.0)
        self._glow_animation.setKeyValueAt(0.5, 1.0)
        self._glow_animation.setKeyValueAt(1.0, 0.0)
        self.toggled.connect(self._sync_state)
        self._sync_state(self.isChecked(), animate=False)

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self.setFixedSize(36 if self._compact else 56, 32)
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        if self._reduced_motion:
            self._glow_animation.stop()
            self._set_glow(0.0)

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = float(value)
        self.update()

    glow = Property(float, _get_glow, _set_glow)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key_Down and event.modifiers() & Qt.AltModifier:
            self.optionsRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _sync_state(self, enabled: bool, animate: bool = True) -> None:
        if enabled:
            self._glow_animation.stop()
            self._set_glow(0.0)
            if animate and not self._reduced_motion:
                self._glow_animation.start()
            description = "Fluxo VR ativo: consulta a base local antes de responder"
        else:
            self._glow_animation.stop()
            self._set_glow(0.0)
            description = (
                "Fluxo VR inativo: não consulta a base local; o modo de "
                "orquestração não é alterado"
            )
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
                and application.property("vr_theme") == "dark_orange"
            )
            painter.setPen(QPen(QColor("#756A63" if dark else "#B9B9C5"), 1.2))
            painter.setBrush(QColor("#24201D" if dark else "#F1F1F5"))
            text_color = QColor("#B8AEA7" if dark else "#5F5F70")
            star_color = QColor("#9D9189" if dark else "#777789")
        painter.drawRoundedRect(body, radius, radius)

        star_center = QPointF(
            body.left() + 12.0 if self._compact else body.left() + 13.0,
            body.center().y(),
        )
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
        if not self._compact:
            painter.drawText(
                QRectF(
                    body.left() + 21.0,
                    body.top(),
                    body.width() - 27.0,
                    body.height(),
                ),
                Qt.AlignCenter,
                "VR",
            )
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#FCBD0F"), 1.5, Qt.DotLine))
            painter.drawRoundedRect(body.adjusted(1, 1, -1, -1), radius, radius)
        painter.end()


class VrComposerGlowFrame(QFrame):
    """Single composer outline for the selected VR execution mode."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chatComposerGlow")
        self._mode = "off"
        self._phase = 0.0
        self._reduced_motion = application_reduced_motion()
        self._phase_animation = QPropertyAnimation(self, b"phase", self)
        self._phase_animation.setDuration(160)
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

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        if self._reduced_motion:
            self._phase_animation.stop()
            self._set_phase(0.14 if self._mode != "off" else 0.0)

    def set_mode(self, mode: str, *, animate: bool = True) -> None:
        mode = str(mode or "off").strip().casefold()
        if mode not in {"standard", "ultra"}:
            mode = "off"
        changed = mode != self._mode
        self._mode = mode
        if mode == "off":
            self._phase_animation.stop()
            self._set_phase(0.0)
            return
        self._phase_animation.stop()
        self._phase_animation.setDuration(160)
        self._phase_animation.setLoopCount(1)
        self._phase_animation.setEasingCurve(QEasingCurve.OutCubic)
        if animate and changed and not self._reduced_motion:
            self._set_phase(0.0)
            self._phase_animation.start()
        else:
            self._set_phase(0.14)
            self.update()

    def mode(self) -> str:
        return self._mode

    # Compatibility for older callers; the outline now belongs to Modos.
    def set_vr_active(self, enabled: bool, *, animate: bool = True) -> None:
        self.set_mode("standard" if enabled else "off", animate=animate)

    def vr_active(self) -> bool:
        return self._mode != "off"

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._phase_animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if self._mode == "off":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bounds = QRectF(self.rect()).adjusted(3.0, 3.0, -3.0, -3.0)
        outline = QColor("#FF9A3D" if self._mode == "ultra" else "#D96B20")
        if self._phase_animation.state() == QPropertyAnimation.Running:
            pulse = 1.0 - abs((2.0 * self._phase) - 1.0)
            painter.setOpacity(0.10 + (0.10 * pulse))
            painter.setPen(QPen(outline, 4.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(bounds, 27.0, 27.0)
        painter.setOpacity(1.0)
        painter.setPen(QPen(outline, 1.6 if self._mode == "standard" else 2.0))
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
        # Suggestions can require an expensive edit-distance search. Live
        # highlighting only needs membership; suggestions are computed lazily
        # when the user opens the context menu for a specific word.
        for issue in self.checker.misspellings(text, include_suggestions=False):
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
            application and application.property("vr_theme") == "dark_orange"
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


class CodeSyntaxHighlighter(QSyntaxHighlighter):
    """Small, dependency-free highlighter for chat code blocks."""

    _GENERAL_KEYWORDS = {
        "and", "as", "assert", "async", "await", "break", "case", "catch",
        "class", "const", "continue", "def", "default", "del", "do", "elif",
        "else", "enum", "except", "export", "extends", "false", "finally",
        "for", "from", "function", "if", "import", "in", "interface", "is",
        "lambda", "let", "match", "new", "none", "not", "null", "or", "pass",
        "raise", "return", "static", "switch", "throw", "true", "try", "var",
        "while", "with", "yield",
    }
    _SQL_KEYWORDS = {
        "all", "and", "as", "asc", "by", "case", "count", "create", "delete",
        "desc", "distinct", "else", "end", "false", "from", "full", "group",
        "having", "in", "inner", "insert", "into", "is", "join", "left", "like",
        "limit", "not", "null", "on", "or", "order", "outer", "right", "select",
        "set", "table", "then", "true", "union", "update", "values", "when",
        "where", "with",
    }

    def __init__(self, document: QTextDocument, language: str = ""):
        super().__init__(document)
        self.language = str(language or "").strip().casefold()
        self.keyword_format = QTextCharFormat()
        self.keyword_format.setForeground(QColor("#FF7AB2"))
        self.keyword_format.setFontWeight(QFont.Bold)
        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor("#43D17B"))
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#7F8C98"))
        self.number_format = QTextCharFormat()
        self.number_format.setForeground(QColor("#67B7FF"))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        sql = self.language in {"sql", "postgres", "postgresql", "plsql"}
        keywords = self._SQL_KEYWORDS if sql else self._GENERAL_KEYWORDS
        keyword_re = re.compile(
            r"\b(?:" + "|".join(sorted(keywords, key=len, reverse=True)) + r")\b",
            re.IGNORECASE if sql else 0,
        )
        for match in keyword_re.finditer(text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.keyword_format
            )
        for match in re.finditer(r"\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b", text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.number_format
            )
        for match in re.finditer(r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")", text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.string_format
            )
        comment_pattern = r"--.*$" if sql else r"#.*$|//.*$"
        for match in re.finditer(comment_pattern, text):
            self.setFormat(
                match.start(), match.end() - match.start(), self.comment_format
            )


class CodeBlockWidget(QFrame):
    """T3-style code card with language badge, wrapping and copy actions."""

    def __init__(self, code: str, language: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("codeBlockCard")
        self.code = str(code).rstrip("\n")
        self.language = str(language or "text").strip().casefold() or "text"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame(objectName="codeBlockHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 7, 8, 5)
        header_layout.setSpacing(5)

        badge = QLabel(self._language_badge(), objectName="codeLanguageBadge")
        badge.setAccessibleName(f"Linguagem: {self.language}")
        header_layout.addWidget(badge)
        header_layout.addStretch()

        self.wrap_button = QToolButton(objectName="codeBlockAction")
        self.wrap_button.setIcon(QIcon(str(CODE_WRAP_ICON_PATH)))
        self.wrap_button.setIconSize(QSize(15, 15))
        self.wrap_button.setCheckable(True)
        self.wrap_button.setAccessibleName("Alternar quebra de linha do código")
        self.wrap_button.setToolTip("Quebrar linhas")
        self.wrap_button.toggled.connect(self._set_line_wrap)
        header_layout.addWidget(self.wrap_button)

        self.copy_button = QToolButton(objectName="codeBlockAction")
        self.copy_button.setIcon(QIcon(str(CODE_COPY_ICON_PATH)))
        self.copy_button.setIconSize(QSize(15, 15))
        self.copy_button.setAccessibleName("Copiar código")
        self.copy_button.setToolTip("Copiar código")
        self.copy_button.clicked.connect(self.copy_code)
        header_layout.addWidget(self.copy_button)
        layout.addWidget(header)

        self.editor = QPlainTextEdit(objectName="codeBlockEditor")
        self.editor.setReadOnly(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setTabStopDistance(32)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        code_font = QFont("Consolas")
        code_font.setStyleHint(QFont.Monospace)
        code_font.setPointSizeF(10.0)
        self.editor.setFont(code_font)
        self.editor.setPlainText(self.code)
        self.highlighter = CodeSyntaxHighlighter(self.editor.document(), self.language)
        line_count = max(1, self.editor.document().blockCount())
        editor_height = min(520, max(48, 18 * line_count + 20))
        self.editor.setFixedHeight(editor_height)
        layout.addWidget(self.editor)
        self.setFixedHeight(editor_height + 40)

    def _language_badge(self) -> str:
        return {
            "python": "Py",
            "py": "Py",
            "sql": "DB",
            "postgres": "DB",
            "postgresql": "DB",
            "json": "{}",
            "javascript": "JS",
            "js": "JS",
            "typescript": "TS",
            "ts": "TS",
            "powershell": ">_",
            "shell": ">_",
            "bash": ">_",
        }.get(
            self.language,
            "<>" if self.language == "text" else self.language[:3].upper(),
        )

    def _set_line_wrap(self, enabled: bool) -> None:
        self.editor.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if enabled else QPlainTextEdit.NoWrap
        )
        self.wrap_button.setToolTip(
            "Não quebrar linhas" if enabled else "Quebrar linhas"
        )

    def copy_code(self) -> None:
        QApplication.clipboard().setText(self.code)
        self.copy_button.setIcon(QIcon())
        self.copy_button.setText("✓")
        self.copy_button.setToolTip("Copiado")
        QTimer.singleShot(1200, self._restore_copy_button)

    def _restore_copy_button(self) -> None:
        self.copy_button.setText("")
        self.copy_button.setIcon(QIcon(str(CODE_COPY_ICON_PATH)))
        self.copy_button.setToolTip("Copiar código")


class MarkdownMessageWidget(QWidget):
    """Markdown message split into native text and polished code cards."""

    anchorClicked = Signal(QUrl)
    _FENCE_RE = re.compile(
        r"^```([^\n`]*)\n(.*?)(?:\n```[ \t]*(?=\n|$)|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    _CODE_OR_URL_RE = re.compile(r"(`+.*?`+|https?://\S+)", re.DOTALL)
    _GLUED_SENTENCE_RE = re.compile(
        r"(?<=[a-záàâãéêíóôõúüç][.!?])"
        r"(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][a-záàâãéêíóôõúüç])"
    )

    def __init__(
        self,
        markdown: str,
        configure_browser: Callable[[QTextBrowser], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("messageBodyHost")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._markdown = ""
        self._stream_browser: QTextBrowser | None = None
        self._configure_browser = configure_browser
        self._content_layout = QVBoxLayout(self)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        self._style_probe = QTextBrowser(self)
        self._style_probe.hide()
        self._configure_browser(self._style_probe)
        self.setMarkdown(markdown)

    def setMarkdown(self, markdown: str) -> None:  # noqa: N802 - Qt compatibility
        self._markdown = str(markdown or "")
        self._stream_browser = None
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        matches = list(self._FENCE_RE.finditer(self._markdown))
        if not matches:
            self._stream_browser = self._create_markdown_browser(self._markdown)
            self._content_layout.addWidget(self._stream_browser)
            self.updateGeometry()
            return

        cursor = 0
        rendered = False
        for match in matches:
            if match.start() > cursor:
                rendered |= self._add_markdown_segment(
                    self._markdown[cursor:match.start()]
                )
            block = CodeBlockWidget(match.group(2), match.group(1), self)
            self._content_layout.addWidget(block)
            rendered = True
            cursor = match.end()
        if cursor < len(self._markdown):
            rendered |= self._add_markdown_segment(self._markdown[cursor:])
        if not rendered:
            self._add_markdown_segment("")
        self.updateGeometry()

    def setStreamingMarkdown(self, markdown: str) -> None:  # noqa: N802
        """Update a live response without rebuilding its widget tree."""
        self._markdown = str(markdown or "")
        if self._stream_browser is None:
            while self._content_layout.count():
                item = self._content_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self._stream_browser = self._create_markdown_browser(self._markdown)
            self._content_layout.addWidget(self._stream_browser)
        else:
            self._stream_browser.setMarkdown(
                self._markdown_for_display(self._markdown)
            )
            self._apply_native_markdown_style(self._stream_browser)
            self._resize_markdown_browser(self._stream_browser)
        self.updateGeometry()

    def finishStreaming(self) -> None:  # noqa: N802
        """Promote completed fenced code to code cards after streaming ends."""
        if self._FENCE_RE.search(self._markdown):
            self.setMarkdown(self._markdown)
        else:
            self.updateGeometry()

    def _create_markdown_browser(self, markdown: str) -> QTextBrowser:
        browser = QTextBrowser(self)
        browser.setObjectName("messageBody")
        browser.setOpenExternalLinks(False)
        browser.anchorClicked.connect(self.anchorClicked.emit)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._configure_browser(browser)
        browser.setMarkdown(self._markdown_for_display(markdown))
        self._apply_native_markdown_style(browser)
        browser.document().documentLayout().documentSizeChanged.connect(
            lambda _size=None, widget=browser: self._resize_markdown_browser(widget)
        )
        self._resize_markdown_browser(browser)
        QTimer.singleShot(0, lambda widget=browser: self._resize_markdown_browser(widget))
        return browser

    def _resize_markdown_browser(self, browser: QTextBrowser) -> None:
        # The browser has no internal vertical scrollbar, so its viewport must
        # grow with the full document. Capping this value clipped long answers.
        target = max(30, min(16_000_000, int(browser.document().size().height()) + 8))
        if browser.height() != target:
            browser.setFixedHeight(target)
            self.updateGeometry()

    def _add_markdown_segment(self, markdown: str) -> bool:
        if not markdown.strip() and self._markdown:
            return False
        browser = self._create_markdown_browser(markdown)
        self._content_layout.addWidget(browser)
        return True

    def toPlainText(self) -> str:  # noqa: N802 - Qt compatibility
        document = QTextDocument()
        document.setMarkdown(self._markdown_for_display(self._markdown))
        return document.toPlainText()

    @classmethod
    def _markdown_for_display(cls, markdown: str) -> str:
        """Repair missing sentence spacing without touching code or URLs."""
        parts = cls._CODE_OR_URL_RE.split(str(markdown or ""))
        return "".join(
            part
            if index % 2
            else cls._GLUED_SENTENCE_RE.sub(" ", part)
            for index, part in enumerate(parts)
        )

    @staticmethod
    def _apply_native_markdown_style(browser: QTextBrowser) -> None:
        """Apply the T3-like rhythm that Qt's Markdown importer omits."""
        application = QApplication.instance()
        dark = bool(
            application
            and application.property("vr_theme") == "dark_orange"
        )
        text_color = QColor("#D4D4D8" if dark else "#27272A")
        link_color = QColor("#58A6FF" if dark else "#075EAD")
        code_text = QColor("#E4E4E7" if dark else "#27272A")
        code_background = QColor("#202023" if dark else "#EEEEF2")
        document = browser.document()
        document.setIndentWidth(22)

        block = document.firstBlock()
        while block.isValid():
            block_format = block.blockFormat()
            block_format.setLineHeight(
                155.0,
                QTextBlockFormat.ProportionalHeight.value,
            )
            heading_level = block_format.headingLevel()
            text_list = block.textList()
            next_block = block.next()
            if heading_level:
                block_format.setTopMargin(0 if block == document.firstBlock() else 16)
                block_format.setBottomMargin(8)
            elif text_list is not None:
                same_list_continues = (
                    next_block.isValid() and next_block.textList() is text_list
                )
                block_format.setTopMargin(0)
                block_format.setBottomMargin(6 if same_list_continues else 14)
            else:
                block_format.setTopMargin(0)
                block_format.setBottomMargin(0 if not next_block.isValid() else 14)
            block_cursor = QTextCursor(block)
            block_cursor.setBlockFormat(block_format)

            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                fragment_format = fragment.charFormat()
                if fragment_format.isImageFormat():
                    image_format = fragment_format.toImageFormat()
                    image_url = QUrl(image_format.name())
                    image_path = (
                        image_url.toLocalFile()
                        if image_url.isLocalFile()
                        else image_format.name()
                    )
                    image_size = QImageReader(image_path).size()
                    if image_size.isValid() and image_size.width() > 0:
                        scale = min(
                            1.0,
                            480.0 / image_size.width(),
                            320.0 / image_size.height(),
                        )
                        image_format.setWidth(image_size.width() * scale)
                        image_format.setHeight(image_size.height() * scale)
                    fragment_cursor = QTextCursor(document)
                    fragment_cursor.setPosition(fragment.position())
                    fragment_cursor.setPosition(
                        fragment.position() + fragment.length(),
                        QTextCursor.KeepAnchor,
                    )
                    fragment_cursor.mergeCharFormat(image_format)
                    iterator += 1
                    continue
                fragment_format.setForeground(
                    link_color if fragment_format.isAnchor() else text_color
                )
                if fragment_format.fontFixedPitch():
                    fragment_format.setFontFamilies(["Consolas"])
                    fragment_format.setFontPointSize(9.0)
                    fragment_format.setForeground(code_text)
                    fragment_format.setBackground(code_background)
                elif heading_level:
                    fragment_format.setFontPointSize(
                        {1: 15.0, 2: 12.75, 3: 11.25}.get(
                            heading_level,
                            10.5,
                        )
                    )
                    fragment_format.setFontWeight(700)
                fragment_cursor = QTextCursor(document)
                fragment_cursor.setPosition(fragment.position())
                fragment_cursor.setPosition(
                    fragment.position() + fragment.length(),
                    QTextCursor.KeepAnchor,
                )
                fragment_cursor.mergeCharFormat(fragment_format)
                iterator += 1
            block = next_block

    def document(self) -> QTextDocument:
        return self._style_probe.document()

    def refresh_theme(self) -> None:
        self._configure_browser(self._style_probe)
        self.setMarkdown(self._markdown)


class ProjectPickerDialog(RoundedPopupDialog):
    """Keyboard-friendly project chooser modeled after T3 Code's palette."""

    def __init__(self, projects: list[Path], parent: QWidget | None = None):
        super().__init__(parent, radius=18.0)
        self.setObjectName("projectPickerDialog")
        self.setWindowTitle("Selecionar projeto")
        self.setModal(True)
        self.setMinimumSize(560, 260)
        self.resize(620, min(480, 132 + 58 * max(1, len(projects))))
        self._projects = list(dict.fromkeys(path.resolve() for path in projects))
        self._selected_project: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self.search = QLineEdit(objectName="projectPickerSearch")
        self.search.setPlaceholderText("Buscar projeto")
        self.search.setAccessibleName("Buscar projeto")
        self.search.textChanged.connect(self._rebuild)
        self.search.returnPressed.connect(self._accept_current)
        layout.addWidget(self.search)

        title = QLabel("Projetos", objectName="projectPickerLabel")
        layout.addWidget(title)
        self.project_list = QListWidget(objectName="projectPickerList")
        self.project_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.project_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.project_list.itemActivated.connect(lambda _item: self._accept_current())
        self.project_list.itemDoubleClicked.connect(
            lambda _item: self._accept_current()
        )
        layout.addWidget(self.project_list, 1)

        hint = QLabel(
            "↑  ↓  Navegar     Enter  Selecionar     Esc  Fechar",
            objectName="projectPickerHint",
        )
        layout.addWidget(hint)
        self._rebuild()
        QTimer.singleShot(0, self.search.setFocus)

    def _rebuild(self, *_args: Any) -> None:
        term = self.search.text().strip().casefold()
        self.project_list.clear()
        for project in self._projects:
            haystack = f"{project.name} {project}".casefold()
            if term and term not in haystack:
                continue
            item = QListWidgetItem(f"{project.name}\n{project}")
            item.setData(Qt.UserRole, str(project))
            item.setToolTip(str(project))
            folder_icon = (
                "project-folder-dark.svg"
                if QApplication.instance()
                and QApplication.instance().property("vr_theme") == "dark_orange"
                else "project-folder.svg"
            )
            item.setIcon(QIcon(str(ASSET_DIR / folder_icon)))
            item.setSizeHint(QSize(0, 54))
            self.project_list.addItem(item)
        if self.project_list.count():
            self.project_list.setCurrentRow(0)

    def _accept_current(self) -> None:
        item = self.project_list.currentItem()
        if item is None:
            return
        self._selected_project = Path(str(item.data(Qt.UserRole))).resolve()
        self.accept()

    def selected_project(self) -> Path | None:
        return self._selected_project


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
        self.setWindowFlags(Qt.Widget)
        self.setAttribute(Qt.WA_NativeWindow, False)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
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
        # A translucent native combo window is rendered with an opaque black
        # fringe by the Windows Fusion style in the light theme. The mask is
        # sufficient to clip the corners, so keep the popup surface opaque.
        container.setAttribute(Qt.WA_TranslucentBackground, False)
        container.setAttribute(Qt.WA_StyledBackground, True)
        container.setAutoFillBackground(True)
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

        icon_label = QLabel(self, objectName="modelOptionIcon")
        icon_label.setFixedSize(30, 30)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(icon.pixmap(QSize(26, 26)))
        icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(icon_label)

        labels = QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(1)
        title_label = QLabel(title, self, objectName="modelOptionTitle")
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        meta_label = QLabel(
            provider_display_name(provider),
            self,
            objectName="modelOptionMeta",
        )
        meta_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        meta_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        labels.addWidget(title_label)
        labels.addWidget(meta_label)
        layout.addLayout(labels, 1)

        shortcut_label = QLabel(shortcut, self, objectName="modelShortcutBadge")
        shortcut_label.setVisible(bool(shortcut))
        shortcut_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(shortcut_label)

        self.favorite_button = QToolButton(self, objectName="modelFavoriteButton")
        favorite_asset = "model-favorite-active.svg" if favorite else "model-favorite.svg"
        self.favorite_button.setIcon(QIcon(str(ASSET_DIR / favorite_asset)))
        self.favorite_button.setIconSize(QSize(15, 15))
        self.favorite_button.setAccessibleName(
            "Remover modelo dos favoritos" if favorite else "Adicionar modelo aos favoritos"
        )
        self.favorite_button.setToolTip(self.favorite_button.accessibleName())
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
        title = QLabel("Modelos legados", self, objectName="modelLegacyTitle")
        count_label = QLabel(
            f"{count} modelos",
            self,
            objectName="modelLegacyMeta",
        )
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        count_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        labels.addWidget(title)
        labels.addWidget(count_label)
        layout.addLayout(labels, 1)
        chevron = QLabel(
            "⌄" if expanded else "›",
            self,
            objectName="modelLegacyChevron",
        )
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
        return QSize(56, 54)

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
            option.icon = QIcon()
            painter.drawControl(QStyle.CE_TabBarTab, option)
            icon = self.tabIcon(index)
            if not icon.isNull():
                icon_size = self.iconSize()
                pixmap = icon.pixmap(icon_size)
                target = self.tabRect(index)
                painter.drawPixmap(
                    target.center().x() - pixmap.width() // 2,
                    target.center().y() - pixmap.height() // 2,
                    pixmap,
                )


class SlashCommandPalette(QFrame):
    """Keyboard-first overlay used by the VR composer slash menu."""

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalogs: dict[str, list[dict[str, Any]]] = {}
        self._catalog_states: dict[str, str] = {}
        self._catalog_errors: dict[str, str] = {}
        self._active_provider = "codex"
        self._enabled_providers = {"codex", "claude", "opencode"}
        self._settings = QSettings()
        self._popup_press_armed = False
        self._suppress_popup_release = False
        self._model_popup: RoundedOverlayFrame | None = None
        self._favorite_shortcuts: list[QShortcut] = []
        for number in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(
                lambda position=number - 1: self._select_ranked_model(position)
            )
            self._favorite_shortcuts.append(shortcut)

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
                QTimer.singleShot(0, self.showPopup)
            return
        super().mouseReleaseEvent(event)

    def set_provider_models(self, provider: str, models: list[dict[str, Any]]) -> None:
        self._catalogs[provider] = list(models)
        self._catalog_states[provider] = "ready"
        self._catalog_errors.pop(provider, None)
        self.catalogChanged.emit()

    def set_active_provider(self, provider: str) -> None:
        self._active_provider = provider

    def set_enabled_providers(self, providers: list[str] | tuple[str, ...]) -> None:
        """Limit provider choices without discarding already loaded catalogs."""
        self._enabled_providers = {
            str(provider).strip().casefold()
            for provider in providers
            if str(provider).strip()
        }
        self.catalogChanged.emit()

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
            if provider_name not in self._enabled_providers:
                continue
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
        width = min(450, max(380, available.width() - 24))
        height = min(430, max(360, available.height() - 24))
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
        # The model picker owns an in-window overlay. Ensure a native QComboBox
        # container can never remain visible if Qt tried to prepare one.
        QComboBox.hidePopup(self)
        if self._model_popup is not None and self._model_popup.isVisible():
            self._model_popup.raise_()
            return
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
        provider.setFixedWidth(56)
        provider.setIconSize(QSize(26, 26))
        provider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        provider.setAccessibleName("Filtrar modelos por provedor")
        favorites_index = provider.addTab(
            QIcon(str(ASSET_DIR / "model-favorite-active.svg")), "Favoritos"
        )
        provider.setTabToolTip(favorites_index, "Somente modelos favoritos")
        provider.setTabData(favorites_index, "favorites")
        for name in ("codex", "claude", "opencode"):
            if name not in self._enabled_providers:
                continue
            index = provider.addTab(provider_icon(name), provider_display_name(name))
            provider.setTabToolTip(index, provider_display_name(name))
            provider.setTabData(index, name)
            if name == self._active_provider:
                provider.setCurrentIndex(index)
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
            favorites_only = selected_tab == "favorites"
            selected_provider = "" if favorites_only else selected_tab
            term = search.text().strip().casefold()
            rows: list[tuple[bool, str, dict[str, Any]]] = []
            for provider_name, models in self._catalogs.items():
                if provider_name not in self._enabled_providers:
                    continue
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
                    if favorites_only and key not in favorites:
                        continue
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
            if not favorites_only and not rows and (not term or term in default_haystack):
                default_item = add_model_row(
                    default_provider,
                    "",
                    "Modelo padrão",
                    f"{provider_display_name(default_provider)} · escolha recomendada pelo provedor",
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
                else [
                    name
                    for name in ("codex", "claude", "opencode")
                    if name in self._enabled_providers and name in self._catalog_states
                ]
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
                status.setText(
                    "Nenhum modelo favorito. Marque a estrela em um provedor."
                    if favorites_only
                    else "Nenhum modelo disponível neste provedor."
                )
            retry.setVisible(
                not favorites_only and (bool(errors) or (not rows and not loading))
            )

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
            selected_provider = "" if selected_tab == "favorites" else selected_tab
            self.retryRequested.emit(selected_provider or self._active_provider)

        def provider_changed() -> None:
            selected_tab = str(provider.tabData(provider.currentIndex()) or "")
            selected_provider = "" if selected_tab == "favorites" else selected_tab
            if selected_provider and self._catalog_states.get(selected_provider, "idle") == "idle":
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
        self._place_popup(dialog)
        self._model_popup = dialog

        def cleanup_popup() -> None:
            try:
                QObject.disconnect(catalog_connection)
            except (RuntimeError, TypeError):
                pass
            if self._model_popup is dialog:
                self._model_popup = None
            dialog.deleteLater()

        dialog.closed.connect(cleanup_popup)
        dialog.show()
        dialog.raise_()
        search.setFocus()


class OrchestrationSettingsDialog(QDialog):
    """Edit VR orchestration without coupling an agent role to a model."""

    STRATEGIES = (
        (
            "automatic",
            "Automática",
            "O orquestrador escolhe o fluxo, os agentes e a estratégia efetiva.",
        ),
        (
            "adaptive",
            "Adaptativa",
            "Combina estratégias conforme a dificuldade e os resultados parciais.",
        ),
        (
            "parallel",
            "Paralela",
            "Executa análises independentes em paralelo e compara os resultados.",
        ),
        (
            "specialized",
            "Especializada",
            "Distribui subtarefas diferentes aos agentes mais adequados.",
        ),
        (
            "sequential",
            "Sequencial",
            "Usa a saída de uma etapa como entrada da etapa seguinte.",
        ),
        (
            "debate",
            "Debate",
            "Solicita propostas e críticas entre agentes antes da síntese.",
        ),
        (
            "consensus",
            "Consenso",
            "Compara concordâncias e divergências antes de decidir.",
        ),
    )

    def __init__(
        self,
        available_models: list[ModelRef] | tuple[ModelRef, ...],
        current: OrchestrationOptions,
        orchestrator: ModelRef,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._current = current
        self._orchestrator = (
            orchestrator
            if isinstance(orchestrator, ModelRef)
            else ModelRef.from_mapping(orchestrator)
        )
        self._available_keys: set[str] = set()
        self._models_by_key: dict[str, ModelRef] = {}
        for raw_model in available_models:
            model = (
                raw_model
                if isinstance(raw_model, ModelRef)
                else ModelRef.from_mapping(raw_model)
            )
            if not model.provider or model.key in self._models_by_key:
                continue
            self._available_keys.add(model.key)
            self._models_by_key[model.key] = model
        # Keep stale saved choices visible so opening and accepting the dialog
        # never drops configuration silently. They can be explicitly unchecked.
        for raw_model in current.model_pool:
            model = (
                raw_model
                if isinstance(raw_model, ModelRef)
                else ModelRef.from_mapping(raw_model)
            )
            if model.provider and model.key not in self._models_by_key:
                self._models_by_key[model.key] = model

        self.setWindowTitle("Orquestração VR")
        self.setAccessibleName("Configurações de orquestração VR")
        self.resize(640, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        title = QLabel("Orquestração VR", objectName="sectionTitle")
        layout.addWidget(title)
        description = QLabel(
            "O fluxo define quais agentes trabalham; o orquestrador escolhe um "
            "modelo deste pool para cada agente.",
            objectName="muted",
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        mode_labels = {
            "off": "Desligado",
            "automatic": "Automático",
            "standard": "Ligado",
            "ultra": "Ultra",
        }
        self.mode_status = QLabel(
            f"Modo atual: {mode_labels.get(current.mode, 'Automático')}. "
            "Use o menu VR no chat para alterá-lo.",
            objectName="muted",
        )
        self.mode_status.setWordWrap(True)
        layout.addWidget(self.mode_status)

        orchestrator_card = QFrame(objectName="panel")
        orchestrator_layout = QHBoxLayout(orchestrator_card)
        orchestrator_layout.setContentsMargins(14, 11, 14, 11)
        orchestrator_layout.setSpacing(10)
        orchestrator_icon = QLabel()
        orchestrator_icon.setFixedSize(24, 24)
        orchestrator_icon.setPixmap(
            provider_icon(self._orchestrator.provider).pixmap(QSize(22, 22))
        )
        orchestrator_icon.setAccessibleName(
            f"Provedor {provider_display_name(self._orchestrator.provider)}"
        )
        orchestrator_layout.addWidget(orchestrator_icon)
        orchestrator_text = QVBoxLayout()
        orchestrator_text.setContentsMargins(0, 0, 0, 0)
        orchestrator_text.setSpacing(1)
        orchestrator_text.addWidget(QLabel("Orquestrador", objectName="muted"))
        orchestrator_name = self._model_label(self._orchestrator)
        self.orchestrator_label = QLabel(orchestrator_name, objectName="sectionTitle")
        self.orchestrator_label.setAccessibleName(
            f"Orquestrador atual: {orchestrator_name}"
        )
        orchestrator_text.addWidget(self.orchestrator_label)
        orchestrator_layout.addLayout(orchestrator_text, 1)
        layout.addWidget(orchestrator_card)

        strategy_row = QHBoxLayout()
        strategy_label = QLabel("Estratégia")
        strategy_row.addWidget(strategy_label)
        self.strategy_combo = DescriptiveComboBox()
        self.strategy_combo.popup_title = "Estratégia de orquestração"
        self.strategy_combo.setAccessibleName("Estratégia de orquestração")
        self.strategy_combo.setMinimumWidth(220)
        for value, label, detail in self.STRATEGIES:
            self.strategy_combo.addItem(label, value)
            self.strategy_combo.setItemData(
                self.strategy_combo.count() - 1,
                detail,
                Qt.ToolTipRole,
            )
        strategy_index = self.strategy_combo.findData(current.strategy)
        self.strategy_combo.setCurrentIndex(strategy_index if strategy_index >= 0 else 0)
        strategy_label.setBuddy(self.strategy_combo)
        strategy_row.addWidget(self.strategy_combo, 1)
        layout.addLayout(strategy_row)

        pool_heading = QHBoxLayout()
        pool_heading.addWidget(QLabel("Modelos disponíveis para os agentes"))
        pool_heading.addStretch()
        self.select_all_button = QPushButton("Todos")
        self.select_all_button.setAccessibleName("Selecionar todos os modelos")
        self.clear_pool_button = QPushButton("Limpar")
        self.clear_pool_button.setAccessibleName("Limpar seleção de modelos")
        pool_heading.addWidget(self.select_all_button)
        pool_heading.addWidget(self.clear_pool_button)
        layout.addLayout(pool_heading)

        self.pool_list = QListWidget()
        self.pool_list.setAccessibleName(
            "Pool de modelos disponíveis para orquestração"
        )
        self.pool_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.pool_list.setAlternatingRowColors(True)
        self.pool_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        selected_keys = {model.key for model in current.model_pool}
        for key, model in self._models_by_key.items():
            available = key in self._available_keys
            availability = "" if available else " · indisponível agora"
            model_id = model.model or "modelo padrão"
            item = QListWidgetItem(
                f"{self._model_label(model)}\n"
                f"{provider_display_name(model.provider)} · {model_id}{availability}"
            )
            item.setIcon(provider_icon(model.provider))
            item.setData(Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if key in selected_keys else Qt.Unchecked)
            item.setToolTip(
                model.description
                or f"{provider_display_name(model.provider)} · {model_id}{availability}"
            )
            item.setSizeHint(QSize(0, 54))
            self.pool_list.addItem(item)
        if not self._models_by_key:
            empty = QListWidgetItem("Nenhum modelo disponível no momento.")
            empty.setFlags(Qt.NoItemFlags)
            self.pool_list.addItem(empty)
        layout.addWidget(self.pool_list, 1)

        self.pool_status = QLabel("", objectName="muted")
        self.pool_status.setWordWrap(True)
        layout.addWidget(self.pool_status)

        self.show_execution_check = QCheckBox(
            "Mostrar o andamento da execução VR"
        )
        self.show_execution_check.setAccessibleName(
            "Mostrar andamento da execução VR"
        )
        self.show_execution_check.setChecked(bool(current.show_execution))
        layout.addWidget(self.show_execution_check)

        self.explain_routing_check = QCheckBox(
            "Mostrar resumos dos motivos de escolha dos modelos"
        )
        self.explain_routing_check.setAccessibleName(
            "Mostrar motivos operacionais da escolha dos modelos"
        )
        self.explain_routing_check.setToolTip(
            "Exibe somente um resumo operacional; raciocínio interno privado não é mostrado."
        )
        self.explain_routing_check.setChecked(bool(current.explain_routing))
        layout.addWidget(self.explain_routing_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        apply_button = buttons.button(QDialogButtonBox.Ok)
        if apply_button is not None:
            apply_button.setText("Aplicar")
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Cancelar")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.pool_list.itemChanged.connect(lambda _item: self._update_pool_status())
        self.select_all_button.clicked.connect(lambda: self._set_all_models(True))
        self.clear_pool_button.clicked.connect(lambda: self._set_all_models(False))
        self._sync_enabled_state(True)
        self._update_pool_status()

    @staticmethod
    def _model_label(model: ModelRef) -> str:
        return model.display_name or model.model or "Modelo padrão"

    def _selected_models(self) -> tuple[ModelRef, ...]:
        selected: list[ModelRef] = []
        for index in range(self.pool_list.count()):
            item = self.pool_list.item(index)
            if item.checkState() != Qt.Checked:
                continue
            model = self._models_by_key.get(str(item.data(Qt.UserRole) or ""))
            if model is not None:
                selected.append(model)
        return tuple(selected)

    def _set_all_models(self, checked: bool) -> None:
        self.pool_list.blockSignals(True)
        try:
            for index in range(self.pool_list.count()):
                item = self.pool_list.item(index)
                key = str(item.data(Qt.UserRole) or "")
                if key:
                    item.setCheckState(
                        Qt.Checked
                        if checked and key in self._available_keys
                        else Qt.Unchecked
                    )
        finally:
            self.pool_list.blockSignals(False)
        self._update_pool_status()

    def _sync_enabled_state(self, enabled: bool) -> None:
        enabled = bool(enabled)
        has_models = bool(self._models_by_key)
        for widget in (
            self.strategy_combo,
            self.show_execution_check,
            self.explain_routing_check,
        ):
            widget.setEnabled(enabled)
        for widget in (
            self.pool_list,
            self.select_all_button,
            self.clear_pool_button,
        ):
            widget.setEnabled(enabled and has_models)
        self._update_pool_status()

    def _update_pool_status(self) -> None:
        count = len(self._selected_models())
        unavailable = sum(
            model.key not in self._available_keys
            for model in self._selected_models()
        )
        suffix = "modelo selecionado" if count == 1 else "modelos selecionados"
        if self._current.mode != "off" and count == 0:
            self.pool_status.setText(
                "Selecione pelo menos um modelo antes de ativar a orquestração."
            )
        elif self._current.mode != "off" and unavailable:
            self.pool_status.setText(
                f"{count} {suffix}; {unavailable} indisponível no momento."
            )
        else:
            self.pool_status.setText(f"{count} {suffix} para os agentes VR.")

    def value(self) -> OrchestrationOptions:
        """Return the edited options while preserving non-visual routing flags."""
        return OrchestrationOptions(
            mode=self._current.mode,
            strategy=str(self.strategy_combo.currentData() or "automatic"),
            model_pool=self._selected_models(),
            show_execution=self.show_execution_check.isChecked(),
            explain_routing=self.explain_routing_check.isChecked(),
            dynamic_model_routing=self._current.dynamic_model_routing,
            dynamic_agent_count=self._current.dynamic_agent_count,
            difficulty_routing=self._current.difficulty_routing,
        )

    def options(self) -> OrchestrationOptions:
        return self.value()

    def orchestrator_model(self) -> ModelRef:
        return self._orchestrator

    def _validate(self) -> None:
        selected = self._selected_models()
        if self._current.mode != "off" and not selected:
            QMessageBox.warning(
                self,
                "Orquestração VR",
                "Selecione pelo menos um modelo disponível para os agentes.",
            )
            self.pool_list.setFocus()
            return
        unavailable = [
            model for model in selected if model.key not in self._available_keys
        ]
        if self._current.mode != "off" and unavailable:
            QMessageBox.warning(
                self,
                "Orquestração VR",
                "Remova do pool os modelos marcados como indisponíveis.",
            )
            self.pool_list.setFocus()
            return
        self.accept()

    @classmethod
    def get_options(
        cls,
        available_models: list[ModelRef] | tuple[ModelRef, ...],
        current: OrchestrationOptions,
        orchestrator: ModelRef,
        parent: QWidget | None = None,
    ) -> tuple[OrchestrationOptions, bool]:
        dialog = cls(available_models, current, orchestrator, parent)
        accepted = dialog.exec() == QDialog.Accepted
        return (dialog.value() if accepted else current), accepted


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

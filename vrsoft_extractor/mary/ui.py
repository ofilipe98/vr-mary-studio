from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import MarySettings, load_mary_settings
from .chat_widgets import (
    ApprovalDialog,
    ModelPickerCombo,
    SpellReviewDialog,
    SpellcheckPlainTextEdit,
    ToolSelectionDialog,
)
from .migration import migrate
from .models import APPROVAL_PRESETS, ConversationOptions, ReviewFilters, RuntimeEvent
from .movidesk import MovideskInteractiveLoginRequired, MovideskSync
from .ocr import OcrManager
from .orchestrator import ChatOrchestrator
from .spellcheck import LocalSpellChecker
from .wiki import WikiSync
from .workspace import initialize_workspace


APP_TITLE = "VR Mary Studio"
ORGANIZATION_NAME = "VRNorte"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
APP_ICON_PATH = ASSET_DIR / "vrnorte-app.ico"
BRAND_SYMBOL_PATH = ASSET_DIR / "vrnorte-symbol.png"
BRAND_ORANGE = "#FF7200"
ACCESSIBLE_ORANGE = "#C45100"
BRAND_YELLOW = "#FCBD0F"
BRAND_NAVY = "#02021E"
TEXT_MUTED = "#4E4E62"
BACKGROUND = "#F3F3F3"
FOCUS_DARK = "#7A3500"
LINK_VISITED = "#5A2600"
DISABLED_TEXT = "#5F5F70"
DISABLED_BACKGROUND = "#ECECF1"
STATUS_GOOD = "#176B3A"
STATUS_WARN = "#8A5500"
SCROLLBAR_HANDLE = "#848493"
SCROLLBAR_TRACK = "#F0F0F4"
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


def video_process_environment() -> QProcessEnvironment:
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("PYTHONUTF8", "1")
    environment.insert("PYTHONIOENCODING", "utf-8")
    return environment


def new_video_output_decoder():
    return codecs.getincrementaldecoder("utf-8")("replace")


STYLESHEET = f"""
* {{
    font-family: "__APP_FONT__";
    font-size: 13px;
    color: {BRAND_NAVY};
}}
QMainWindow, QWidget#appRoot, QStackedWidget, QWidget#chatCenter {{
    background: {BACKGROUND};
}}
QFrame#navRail {{ background: {BRAND_NAVY}; border: 0; }}
QLabel#brandTitle {{ color: white; font-size: 18px; font-weight: 700; }}
QLabel#brandSub {{ color: #B9B9C8; font-size: 11px; }}
QToolButton#navButton {{
    color: #E9E9F0; background: transparent; border: 0; border-radius: 8px;
    min-height: 42px; text-align: left; padding: 0 12px;
}}
QToolButton#navButton:hover {{ background: #191937; }}
QToolButton#navButton:checked {{ background: {ACCESSIBLE_ORANGE}; color: white; font-weight: 600; }}
QFrame#card, QFrame#panel {{
    background: white; border: 1px solid #E2E2E9; border-radius: 10px;
}}
QPushButton {{
    min-height: 38px; border-radius: 8px; border: 1px solid #D6D6DF;
    background: white; padding: 0 14px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {BRAND_ORANGE}; background: #FFF6EF; }}
QPushButton:focus {{ border: 2px solid {FOCUS_DARK}; }}
QPushButton#primary {{ background: {ACCESSIBLE_ORANGE}; color: white; border: 0; }}
QPushButton#primary:hover {{ background: #A84300; }}
QPushButton#primary:focus {{ border: 2px solid {BRAND_YELLOW}; }}
QPushButton#danger {{ color: #A1261D; border-color: #E3B8B4; }}
QPushButton:disabled {{
    color: {DISABLED_TEXT}; background: {DISABLED_BACKGROUND}; border-color: #DADAE2;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: white; border: 1px solid #D6D6DF; border-radius: 8px;
    padding: 7px; color: {BRAND_NAVY};
    selection-background-color: {ACCESSIBLE_ORANGE}; selection-color: white;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 2px solid {BRAND_ORANGE};
}}
QListWidget, QTableWidget {{
    background: white; color: {BRAND_NAVY}; border: 0;
    alternate-background-color: #FAFAFC;
}}
QListWidget::item {{ padding: 9px; border-radius: 7px; }}
QListWidget::item:selected {{ background: #FFF0E4; color: {BRAND_NAVY}; }}
QTableWidget::item:selected {{ background: #FFF0E4; color: {BRAND_NAVY}; }}
QListWidget::item:focus, QTableWidget::item:focus {{
    border: 2px solid {ACCESSIBLE_ORANGE};
}}
QComboBox QAbstractItemView {{
    background: white; color: {BRAND_NAVY}; border: 1px solid #C9C9D4;
    selection-background-color: #FFF0E4; selection-color: {BRAND_NAVY};
    outline: 0; padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px; padding: 4px 8px; color: {BRAND_NAVY};
}}
QComboBox QAbstractItemView::item:selected {{
    background: #FFF0E4; color: {BRAND_NAVY};
}}
QMenu {{
    background: white; color: {BRAND_NAVY}; border: 1px solid #C9C9D4;
}}
QMenu::item:selected {{ background: #FFF0E4; color: {BRAND_NAVY}; }}
QHeaderView::section {{
    background: #F6F6F9; border: 0; border-bottom: 1px solid #DFDFE6;
    padding: 9px; font-weight: 700;
}}
QTableCornerButton::section {{
    background: #F6F6F9; border: 0; border-bottom: 1px solid #DFDFE6;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {SCROLLBAR_TRACK}; border: 0; margin: 0;
}}
QScrollBar:vertical {{ width: 12px; }}
QScrollBar:horizontal {{ height: 12px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {SCROLLBAR_HANDLE}; border-radius: 5px; min-height: 28px; min-width: 28px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: #666677;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0; background: transparent;
}}
QLabel#pageTitle {{ font-size: 24px; font-weight: 700; }}
QLabel#sectionTitle {{ font-size: 16px; font-weight: 700; }}
QLabel#muted {{ color: {TEXT_MUTED}; }}
QLabel#statusGood {{ color: {STATUS_GOOD}; font-weight: 700; }}
QLabel#statusWarn {{ color: {STATUS_WARN}; font-weight: 700; }}
QTextBrowser {{ background: white; border: 0; padding: 12px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{
    border: 0; background: white; color: {BRAND_NAVY};
}}
QScrollArea#messageScroll, QWidget#messageContainer {{
    background: white; color: {BRAND_NAVY};
}}
QSplitter::handle {{ background: #E2E2E9; }}
QToolTip {{
    background: {BRAND_NAVY}; color: white; border: 1px solid #303052;
    padding: 5px;
}}
QDialog, QMessageBox {{
    background: {BACKGROUND}; color: {BRAND_NAVY};
}}
QMessageBox QLabel {{
    background: transparent; color: {BRAND_NAVY};
}}
QMessageBox QLabel#qt_msgbox_label {{
    min-width: 420px; max-width: 560px;
    qproperty-wordWrap: true;
}}
QMessageBox QPushButton {{
    min-width: 64px; background: white; color: {BRAND_NAVY};
}}
QToolButton#navButton:focus {{ border: 2px solid {BRAND_YELLOW}; }}
"""


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str)


class Worker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        if "progress" in kwargs and kwargs["progress"] is None:
            self.kwargs["progress"] = self.signals.progress.emit

    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as exc:
            self.signals.error.emit(str(exc))
        else:
            self.signals.finished.emit(result)


class MainWindow(QMainWindow):
    runtime_event_signal = Signal(object)
    sync_progress_signal = Signal(str)

    def __init__(
        self,
        settings: MarySettings,
        smoke_test: bool = False,
        auto_close_smoke: bool = True,
    ):
        super().__init__()
        self.smoke_test = smoke_test
        self.settings = settings
        self.database = initialize_workspace(settings)
        self.orchestrator = ChatOrchestrator(settings, self.database)
        self.spell_checker = LocalSpellChecker(
            settings.state_dir / "spellcheck_pt_br.json",
            [
                "VRNorte", "VRSoft", "Mary", "Movidesk", "VRWiki", "VRMaster",
                "VRCaixa", "VRPdv", "Sitef", "Pix", "NFCe", "PostgreSQL",
            ],
        )
        self.pool = QThreadPool.globalInstance()
        self.current_conversation = ""
        self.conversation_state = "active"
        self.draft_conversation = True
        self.draft_dynamic_tools: list[str] = []
        self.draft_mcp_tools: list[dict[str, str]] = []
        self.mcp_tool_catalog: list[dict[str, Any]] = []
        self._pending_first_message = ""
        self.assistant_widget: QTextBrowser | None = None
        self.assistant_markdown = ""
        self.video_process: QProcess | None = None
        self._video_decoder = new_video_output_decoder()
        self.sync_running = False
        self.model_metadata: dict[str, dict[str, Any]] = {}
        self.pending_model = ""
        self.pending_effort = ""
        self.pending_tier = ""
        self.nav_buttons: list[QToolButton] = []
        self.pages: dict[str, int] = {}
        self.setWindowTitle(APP_TITLE)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1480, 900)
        self.setMinimumSize(1120, 700)
        self.runtime_event_signal.connect(self._on_runtime_event)
        self.sync_progress_signal.connect(self.sync_log_append)
        self._build_ui()
        self._refresh_all()
        self._setup_auto_sync()
        if smoke_test and auto_close_smoke:
            QTimer.singleShot(800, QApplication.instance().quit)

    def _build_ui(self) -> None:
        root = QWidget(objectName="appRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_nav())
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        builders = [
            ("Dashboard", self._build_dashboard),
            ("Chat Mary", self._build_chat),
            ("Conhecimento", self._build_knowledge),
            ("Sincronizações", self._build_sync),
            ("Revisão", self._build_review),
            ("Vídeos", self._build_videos),
            ("Configurações", self._build_settings),
            ("Logs", self._build_logs),
        ]
        for name, builder in builders:
            self.pages[name] = self.stack.count()
            self.stack.addWidget(builder())

    def _build_nav(self) -> QWidget:
        frame = QFrame(objectName="navRail")
        self.nav_frame = frame
        frame.setFixedWidth(188)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 18, 12, 14)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        self.nav_brand_symbol = QLabel()
        self.nav_brand_symbol.setFixedSize(42, 42)
        self.nav_brand_symbol.setAccessibleName("Logotipo VRNorte")
        if BRAND_SYMBOL_PATH.exists():
            symbol = QPixmap(str(BRAND_SYMBOL_PATH))
            self.nav_brand_symbol.setPixmap(
                symbol.scaled(
                    self.nav_brand_symbol.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        self.nav_brand = QLabel("VR NORTE", objectName="brandTitle")
        self.nav_subtitle = QLabel("MARY STUDIO", objectName="brandSub")
        brand_text.addWidget(self.nav_brand)
        brand_text.addWidget(self.nav_subtitle)
        brand_row.addWidget(self.nav_brand_symbol)
        brand_row.addLayout(brand_text, 1)
        layout.addLayout(brand_row)
        layout.addSpacing(22)
        for index, label in enumerate(
            [
                "Dashboard",
                "Chat Mary",
                "Conhecimento",
                "Sincronizações",
                "Revisão",
                "Vídeos",
                "Configurações",
                "Logs",
            ]
        ):
            button = QToolButton(objectName="navButton")
            button.setText(label)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.clicked.connect(lambda _checked=False, i=index: self._navigate(i))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch()
        self.nav_provider_status = QLabel("Agentes: verificando…", objectName="brandSub")
        self.nav_provider_status.setWordWrap(True)
        layout.addWidget(self.nav_provider_status)
        return frame

    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        if index == self.pages["Dashboard"]:
            self.refresh_dashboard()
        elif index == self.pages["Conhecimento"]:
            self.search_knowledge()
        elif index == self.pages["Revisão"]:
            self.refresh_reviews()

    def _page(self, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        heading = QLabel(title, objectName="pageTitle")
        layout.addWidget(heading)
        if subtitle:
            label = QLabel(subtitle, objectName="muted")
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addSpacing(8)
        return page, layout

    def _build_dashboard(self) -> QWidget:
        page, layout = self._page(
            "Visão geral",
            "Wiki, KB e Vídeos possuem saúde, inventário e ações independentes.",
        )
        sources = QGridLayout()
        sources.setHorizontalSpacing(12)
        layout.addLayout(sources)
        self.source_count_labels: dict[str, QLabel] = {}
        self.source_status_labels: dict[str, QLabel] = {}
        self.source_detail_labels: dict[str, QLabel] = {}

        source_specs = [
            (
                "wiki",
                "VRWiki",
                "Base pública MediaWiki",
                "Sincronizar Wiki",
                self.sync_wiki,
            ),
            (
                "kb",
                "Movidesk KB",
                "Base autenticada de suporte",
                "Sincronizar KB",
                self.sync_kb,
            ),
            (
                "video",
                "Vídeos",
                "Inventário do extrator VRSoft",
                "Abrir Vídeos",
                lambda: self._navigate(self.pages["Vídeos"]),
            ),
        ]
        for column, (key, title, subtitle, action_text, action) in enumerate(source_specs):
            card = QFrame(objectName="card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            name = QLabel(title, objectName="sectionTitle")
            description = QLabel(subtitle, objectName="muted")
            count = QLabel("—")
            count.setStyleSheet("font-size: 30px; font-weight: 700;")
            status = QLabel("Aguardando dados", objectName="statusWarn")
            detail = QLabel("", objectName="muted")
            detail.setWordWrap(True)
            button = QPushButton(
                action_text,
                objectName="primary" if key == "wiki" else "",
            )
            button.clicked.connect(action)
            card_layout.addWidget(name)
            card_layout.addWidget(description)
            card_layout.addWidget(count)
            card_layout.addWidget(status)
            card_layout.addWidget(detail)
            card_layout.addStretch()
            card_layout.addWidget(button)
            self.source_count_labels[key] = count
            self.source_status_labels[key] = status
            self.source_detail_labels[key] = detail
            sources.addWidget(card, 0, column)

        layout.addWidget(QLabel("Resumo da Mary", objectName="sectionTitle"))
        self.dashboard_grid = QGridLayout()
        layout.addLayout(self.dashboard_grid)
        self.metric_labels: dict[str, QLabel] = {}
        metrics = [
            ("Documentos", "documents"),
            ("Pendentes", "reviews"),
            ("OCR", "ocr"),
            ("Conversas", "conversations"),
        ]
        for index, (label, key) in enumerate(metrics):
            card = QFrame(objectName="card")
            card_layout = QVBoxLayout(card)
            title = QLabel(label, objectName="muted")
            value = QLabel("—")
            value.setStyleSheet("font-size: 26px; font-weight: 700;")
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            self.metric_labels[key] = value
            self.dashboard_grid.addWidget(card, 0, index)

        quick = QFrame(objectName="card")
        quick_layout = QHBoxLayout(quick)
        sync_button = QPushButton("Sincronizar Wiki + KB", objectName="primary")
        sync_button.clicked.connect(self.sync_all)
        chat_button = QPushButton("Nova conversa Mary")
        chat_button.clicked.connect(lambda: self._navigate(self.pages["Chat Mary"]))
        review_button = QPushButton("Revisar classificações")
        review_button.clicked.connect(lambda: self._navigate(self.pages["Revisão"]))
        quick_layout.addWidget(sync_button)
        quick_layout.addWidget(chat_button)
        quick_layout.addWidget(review_button)
        quick_layout.addStretch()
        layout.addWidget(quick)
        layout.addStretch()
        return page

    def _build_chat(self) -> QWidget:
        page = QWidget()
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        page_layout.addWidget(splitter)

        conversations = QFrame(objectName="panel")
        conversations.setMinimumWidth(235)
        conversations.setMaximumWidth(330)
        left = QVBoxLayout(conversations)
        left.setContentsMargins(12, 14, 12, 12)
        row = QHBoxLayout()
        title = QLabel("Conversas", objectName="sectionTitle")
        new_button = QPushButton("+ Nova")
        new_button.clicked.connect(self.new_conversation)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(new_button)
        left.addLayout(row)
        self.conversation_search = QLineEdit()
        self.conversation_search.setPlaceholderText("Buscar conversas")
        self.conversation_search.textChanged.connect(self.refresh_conversations)
        left.addWidget(self.conversation_search)
        self.conversation_state_combo = QComboBox()
        self.conversation_state_combo.addItem("Ativas", "active")
        self.conversation_state_combo.addItem("Arquivadas", "archived")
        self.conversation_state_combo.addItem("Lixeira", "trash")
        self.conversation_state_combo.currentIndexChanged.connect(
            self._conversation_state_changed
        )
        left.addWidget(self.conversation_state_combo)
        self.conversation_list = QListWidget()
        self.conversation_list.currentItemChanged.connect(self.load_conversation)
        left.addWidget(self.conversation_list, 1)
        self.conversation_empty = QLabel(
            "Nenhuma conversa ainda.\nUse “+ Nova” para começar.",
            objectName="muted",
        )
        self.conversation_empty.setAlignment(Qt.AlignCenter)
        self.conversation_empty.setWordWrap(True)
        self.conversation_empty.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Expanding,
        )
        left.addWidget(self.conversation_empty)
        splitter.addWidget(conversations)

        center = QWidget(objectName="chatCenter")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 14, 16, 14)
        header = QGridLayout()
        self.chat_title = QLabel("Nova conversa", objectName="sectionTitle")
        self.chat_title.setWordWrap(True)
        self.provider_combo = QComboBox()
        self.provider_combo.setAccessibleName("Provedor da conversa")
        self.provider_combo.setToolTip("Provedor local usado nesta conversa.")
        self.provider_combo.addItems(["codex", "claude"])
        self.provider_combo.currentTextChanged.connect(self.load_models)
        self.model_combo = ModelPickerCombo()
        self.model_combo.setAccessibleName("Modelo da conversa")
        self.model_combo.setToolTip("Modelo disponibilizado pelo provedor selecionado.")
        self.model_combo.setMinimumWidth(150)
        self.model_combo.currentIndexChanged.connect(self.load_efforts)
        self.model_combo.providerModelSelected.connect(self._model_picker_selected)
        self.effort_combo = QComboBox()
        self.effort_combo.setAccessibleName("Nível de esforço")
        self.effort_combo.setMinimumWidth(96)
        self.effort_combo.setToolTip(
            "Controla quanto raciocínio o agente usa nesta conversa."
        )
        self.effort_combo.currentTextChanged.connect(self._chat_option_changed)
        self.tier_combo = QComboBox()
        self.tier_combo.setAccessibleName("Camada de serviço")
        self.tier_combo.setToolTip("Camada de serviço anunciada pelo modelo.")
        self.tier_combo.currentTextChanged.connect(self._chat_option_changed)
        self.approval_combo = QComboBox()
        self.approval_combo.setAccessibleName("Perfil de aprovação")
        for preset in APPROVAL_PRESETS.values():
            self.approval_combo.addItem(preset.label, preset.id)
            self.approval_combo.setItemData(
                self.approval_combo.count() - 1,
                preset.description,
                Qt.ToolTipRole,
            )
        self.approval_combo.setCurrentIndex(self.approval_combo.findData("auto"))
        self.approval_combo.currentIndexChanged.connect(self._chat_option_changed)
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName("Modo de colaboração")
        self.mode_combo.addItem("Build", "default")
        self.mode_combo.addItem("Plan", "plan")
        self.mode_combo.currentIndexChanged.connect(self._chat_option_changed)
        self.tools_button = QPushButton("Tools (0)")
        self.tools_button.clicked.connect(self.open_tools)
        self.clone_button = QPushButton("Clonar para outro provedor")
        self.clone_button.clicked.connect(self.clone_conversation)
        self.archive_button = QPushButton("Arquivar")
        self.archive_button.clicked.connect(self.archive_current_conversation)
        self.delete_conversation_button = QPushButton("Excluir")
        self.delete_conversation_button.setObjectName("danger")
        self.delete_conversation_button.clicked.connect(self.delete_current_conversation)
        header.addWidget(self.chat_title, 0, 0)
        conversation_actions = QHBoxLayout()
        conversation_actions.addWidget(self.clone_button)
        conversation_actions.addWidget(self.archive_button)
        conversation_actions.addWidget(self.delete_conversation_button)
        header.addLayout(conversation_actions, 0, 2)
        header.setColumnStretch(1, 1)
        center_layout.addLayout(header)
        self.message_scroll = QScrollArea(objectName="messageScroll")
        self.message_scroll.setWidgetResizable(True)
        self.message_container = QWidget(objectName="messageContainer")
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setAlignment(Qt.AlignTop)
        self._add_chat_empty_state()
        self.message_layout.addStretch()
        self.message_scroll.setWidget(self.message_container)
        center_layout.addWidget(self.message_scroll, 1)
        composer_card = QFrame(objectName="card")
        composer_layout = QVBoxLayout(composer_card)
        self.composer = SpellcheckPlainTextEdit(self.spell_checker)
        self.composer.setPlaceholderText(
            "Digite Mary: para ativar o fluxo e pesquisar a base local…"
        )
        self.composer.setMaximumHeight(130)
        composer_layout.addWidget(self.composer)
        selector_primary = QHBoxLayout()
        selector_primary.setSpacing(6)
        selector_primary.addWidget(self.provider_combo)
        selector_primary.addWidget(self.model_combo, 1)
        selector_primary.addWidget(self.tools_button)
        composer_layout.addLayout(selector_primary)
        selector_secondary = QHBoxLayout()
        selector_secondary.setSpacing(6)
        selector_secondary.addWidget(self.effort_combo)
        selector_secondary.addWidget(self.tier_combo)
        selector_secondary.addWidget(self.approval_combo, 1)
        selector_secondary.addWidget(self.mode_combo)
        composer_layout.addLayout(selector_secondary)
        actions = QHBoxLayout()
        self.chat_status = QLabel("Pronto", objectName="muted")
        correct_button = QPushButton("Corrigir texto")
        correct_button.setToolTip("Correção ortográfica local em português.")
        correct_button.clicked.connect(self.correct_composer_text)
        stop_button = QPushButton("Parar", objectName="danger")
        stop_button.clicked.connect(self.stop_turn)
        send_button = QPushButton("Enviar", objectName="primary")
        send_button.clicked.connect(self.send_message)
        actions.addWidget(self.chat_status)
        actions.addStretch()
        actions.addWidget(correct_button)
        actions.addWidget(stop_button)
        actions.addWidget(send_button)
        composer_layout.addLayout(actions)
        center_layout.addWidget(composer_card)
        splitter.addWidget(center)

        context = QFrame(objectName="panel")
        context.setMinimumWidth(250)
        context.setMaximumWidth(360)
        context_layout = QVBoxLayout(context)
        context_layout.setContentsMargins(12, 14, 12, 12)
        context_layout.addWidget(QLabel("Contexto local", objectName="sectionTitle"))
        self.context_search = QLineEdit()
        self.context_search.setPlaceholderText("Pesquisar Wiki e KB")
        self.context_search.returnPressed.connect(self.search_context)
        context_layout.addWidget(self.context_search)
        self.context_results = QListWidget()
        self.context_results.itemDoubleClicked.connect(self.insert_context_reference)
        context_layout.addWidget(self.context_results, 1)
        self.context_files = QLabel(
            "Os resultados usados em mensagens Mary serão incluídos automaticamente.",
            objectName="muted",
        )
        self.context_files.setWordWrap(True)
        context_layout.addWidget(self.context_files)
        splitter.addWidget(context)
        splitter.setSizes([260, 820, 300])
        return page

    def _build_knowledge(self) -> QWidget:
        page, layout = self._page(
            "Conhecimento",
            "Pesquisa local FTS5 em textos, metadados e OCR.",
        )
        filters = QHBoxLayout()
        self.knowledge_query = QLineEdit()
        self.knowledge_query.setAccessibleName("Pesquisar conhecimento")
        self.knowledge_query.setPlaceholderText("Ex.: configuração PIX, erro TEF, cadastro de produto")
        self.knowledge_query.returnPressed.connect(self.search_knowledge)
        self.knowledge_module = QComboBox()
        self.knowledge_module.addItems(
            ["Todos", "Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar"]
        )
        self.knowledge_source = QComboBox()
        self.knowledge_source.addItems(["Todas", "wiki", "kb"])
        search_button = QPushButton("Pesquisar", objectName="primary")
        search_button.clicked.connect(self.search_knowledge)
        filters.addWidget(self.knowledge_query, 1)
        filters.addWidget(self.knowledge_module)
        filters.addWidget(self.knowledge_source)
        filters.addWidget(search_button)
        layout.addLayout(filters)
        self.knowledge_count = QLabel(
            "Carregando documentos…",
            objectName="muted",
        )
        layout.addWidget(self.knowledge_count)
        splitter = QSplitter(Qt.Horizontal)
        self.knowledge_table = QTableWidget(0, 4)
        self.knowledge_table.setHorizontalHeaderLabels(["Título", "Módulo", "Fonte", "Status"])
        self.knowledge_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.knowledge_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.knowledge_table.itemSelectionChanged.connect(self.preview_knowledge)
        self.knowledge_preview = QTextBrowser()
        self.knowledge_preview.setOpenExternalLinks(True)
        self.knowledge_preview.setMarkdown(
            "### Visualização do documento\n\n"
            "Selecione um resultado para consultar o texto, as imagens e o OCR."
        )
        splitter.addWidget(self.knowledge_table)
        splitter.addWidget(self.knowledge_preview)
        splitter.setSizes([620, 560])
        layout.addWidget(splitter, 1)
        self.knowledge_results: list[dict[str, Any]] = []
        return page

    def _build_sync(self) -> QWidget:
        page, layout = self._page(
            "Sincronizações",
            "A primeira sincronização pode demorar; as próximas usam revisão/hash.",
        )
        actions = QHBoxLayout()
        wiki_button = QPushButton("Sincronizar Wiki", objectName="primary")
        wiki_button.clicked.connect(self.sync_wiki)
        kb_button = QPushButton("Sincronizar KB")
        kb_button.clicked.connect(self.sync_kb)
        kb_visible = QPushButton("Login/KB visível")
        kb_visible.clicked.connect(lambda: self.sync_kb(True))
        all_button = QPushButton("Sincronizar tudo")
        all_button.clicked.connect(self.sync_all)
        actions.addWidget(wiki_button)
        actions.addWidget(kb_button)
        actions.addWidget(kb_visible)
        actions.addWidget(all_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.sync_status = QLabel("Pronto", objectName="muted")
        layout.addWidget(self.sync_status)
        self.sync_log = QPlainTextEdit()
        self.sync_log.setReadOnly(True)
        self.sync_log.setPlaceholderText(
            "O progresso aparecerá aqui. Escolha uma fonte acima para iniciar."
        )
        layout.addWidget(self.sync_log, 1)
        return page

    def _build_review(self) -> QWidget:
        page, layout = self._page(
            "Revisão",
            "Triagem auditável por risco, evidência, produto e módulo.",
        )

        self.review_query_timer = QTimer(self)
        self.review_query_timer.setSingleShot(True)
        self.review_query_timer.setInterval(300)
        self.review_query_timer.timeout.connect(self.reset_review_page)

        filters = QGridLayout()
        filters.setHorizontalSpacing(8)
        filters.setVerticalSpacing(8)
        self.review_query = QLineEdit()
        self.review_query.setAccessibleName("Pesquisar revisões")
        self.review_query.setPlaceholderText(
            "Buscar título, ID, produto, categoria, motivo ou conteúdo"
        )
        self.review_query.textChanged.connect(
            lambda _text: self.review_query_timer.start()
        )
        self.review_query.returnPressed.connect(self.reset_review_page)

        self.review_source = QComboBox()
        for label, value in (("Todas as fontes", ""), ("Wiki", "wiki"), ("KB", "kb")):
            self.review_source.addItem(label, value)
        self.review_current_module = self._module_filter_combo("Módulo atual")
        self.review_suggested_module = self._module_filter_combo("Módulo sugerido")

        self.review_confidence = QComboBox()
        for label, value in (
            ("Toda confiança", ""),
            ("Alta · 85% ou mais", "high"),
            ("Intermediária · 60–84%", "medium"),
            ("Baixa · menos de 60%", "low"),
        ):
            self.review_confidence.addItem(label, value)

        self.review_status_filter = QComboBox()
        for label, value in (
            ("Pendentes", "pending"),
            ("Adiados", "deferred"),
            ("Aprovados", "approved"),
            ("Mantidos", "kept"),
            ("Todos os estados", "all"),
        ):
            self.review_status_filter.addItem(label, value)

        self.review_product = QComboBox()
        self.review_product.setEditable(True)
        self.review_product.setInsertPolicy(QComboBox.NoInsert)
        self.review_category = QComboBox()
        self.review_category.setEditable(True)
        self.review_category.setInsertPolicy(QComboBox.NoInsert)
        for combo in (self.review_product, self.review_category):
            combo.currentIndexChanged.connect(
                lambda _index, current=combo: current.lineEdit().setCursorPosition(0)
            )

        self.review_period = QComboBox()
        for label, days in (
            ("Qualquer período", 0),
            ("Últimos 7 dias", 7),
            ("Últimos 30 dias", 30),
            ("Últimos 90 dias", 90),
        ):
            self.review_period.addItem(label, days)

        self.review_special = QComboBox()
        for label, value in (
            ("Todos os riscos", ""),
            ("Mudança de módulo validado", "module_change"),
            ("Sem produto identificado", "no_product"),
            ("Pouca evidência", "low_evidence"),
            ("Aprovação simples", "simple"),
        ):
            self.review_special.addItem(label, value)

        self.review_sort = QComboBox()
        for label, value in (
            ("Maior risco primeiro", "risk"),
            ("Maior confiança", "confidence_desc"),
            ("Menor confiança", "confidence_asc"),
            ("Mais recentes", "recent"),
            ("Título A–Z", "title"),
        ):
            self.review_sort.addItem(label, value)

        filter_combos = [
            self.review_source,
            self.review_current_module,
            self.review_suggested_module,
            self.review_confidence,
            self.review_status_filter,
            self.review_product,
            self.review_category,
            self.review_period,
            self.review_special,
            self.review_sort,
        ]
        for combo in filter_combos:
            combo.currentIndexChanged.connect(self.reset_review_page)

        filters.addWidget(self.review_query, 0, 0, 1, 4)
        filters.addWidget(self.review_source, 0, 4)
        filters.addWidget(self.review_status_filter, 0, 5)
        filters.addWidget(self.review_confidence, 0, 6)
        filters.addWidget(self.review_current_module, 1, 0)
        filters.addWidget(self.review_suggested_module, 1, 1)
        filters.addWidget(self.review_product, 1, 2)
        filters.addWidget(self.review_category, 1, 3)
        filters.addWidget(self.review_period, 1, 4)
        filters.addWidget(self.review_special, 1, 5)
        filters.addWidget(self.review_sort, 1, 6)
        filters.setColumnStretch(0, 1)
        filters.setColumnStretch(1, 1)
        filters.setColumnStretch(2, 1)
        filters.setColumnStretch(3, 1)
        layout.addLayout(filters)

        presets = QHBoxLayout()
        for label, preset in (
            ("Maior risco", "risk"),
            ("Aprovação simples", "simple"),
            ("Sem produto", "no_product"),
            ("Adiados", "deferred"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=preset: self.apply_review_preset(value)
            )
            presets.addWidget(button)
        clear_filters = QPushButton("Limpar filtros")
        clear_filters.clicked.connect(self.clear_review_filters)
        presets.addWidget(clear_filters)
        presets.addStretch()
        layout.addLayout(presets)

        selection_bar = QHBoxLayout()
        self.review_select_all = QPushButton("Selecionar todos")
        self.review_select_all.setToolTip(
            "Seleciona os até 100 itens exibidos na página atual."
        )
        self.review_select_all.clicked.connect(self.select_all_reviews)
        selection_bar.addWidget(self.review_select_all)
        self.review_clear_selection = QPushButton("Limpar seleção")
        self.review_clear_selection.clicked.connect(self.clear_review_selection)
        selection_bar.addWidget(self.review_clear_selection)
        selection_bar.addStretch()
        self.review_summary = QLabel("Carregando revisões…", objectName="muted")
        selection_bar.addWidget(self.review_summary)
        layout.addLayout(selection_bar)

        splitter = QSplitter(Qt.Horizontal)
        self.review_table = QTableWidget(0, 10)
        self.review_table.setHorizontalHeaderLabels(
            [
                "✓",
                "Título",
                "Fonte",
                "Atual",
                "Sugestão",
                "Confiança",
                "Produto",
                "Categoria",
                "Risco / motivo",
                "Atualização",
            ]
        )
        review_header = self.review_table.horizontalHeader()
        review_header.setSectionResizeMode(QHeaderView.Interactive)
        review_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column, width in {
            1: 240,
            2: 70,
            3: 120,
            4: 120,
            5: 90,
            6: 140,
            7: 150,
            8: 280,
            9: 150,
        }.items():
            self.review_table.setColumnWidth(column, width)
        self.review_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollPerPixel
        )
        self.review_table.setAlternatingRowColors(True)
        self.review_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.review_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.review_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.review_table.itemSelectionChanged.connect(self.preview_review)
        self.review_table.itemChanged.connect(self.review_selection_changed)
        splitter.addWidget(self.review_table)

        detail = QFrame(objectName="panel")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(12, 12, 12, 12)
        self.review_detail_title = QLabel("Selecione uma revisão", objectName="sectionTitle")
        self.review_detail_title.setWordWrap(True)
        detail_layout.addWidget(self.review_detail_title)
        self.review_preview = QTextBrowser()
        self.review_preview.setOpenExternalLinks(True)
        detail_layout.addWidget(self.review_preview, 1)

        source_actions = QHBoxLayout()
        self.review_open_source = QPushButton("Abrir fonte")
        self.review_open_source.clicked.connect(self.open_review_source)
        self.review_open_local = QPushButton("Abrir arquivo local")
        self.review_open_local.clicked.connect(self.open_review_local)
        self.review_copy_citation = QPushButton("Copiar citação")
        self.review_copy_citation.clicked.connect(self.copy_review_citation)
        source_actions.addWidget(self.review_open_source)
        source_actions.addWidget(self.review_open_local)
        source_actions.addWidget(self.review_copy_citation)
        detail_layout.addLayout(source_actions)

        self.review_note = QTextEdit()
        self.review_note.setPlaceholderText("Nota de auditoria opcional")
        self.review_note.setMaximumHeight(72)
        detail_layout.addWidget(self.review_note)

        actions = QGridLayout()
        self.review_module = QComboBox()
        self.review_module.addItems(
            ["Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar"]
        )
        self.review_module.currentTextChanged.connect(self._update_review_actions)
        self.review_approve = QPushButton("Aprovar", objectName="primary")
        self.review_approve.clicked.connect(self.approve_review)
        self.review_keep = QPushButton("Manter atual")
        self.review_keep.clicked.connect(self.keep_review)
        self.review_defer = QPushButton("Adiar")
        self.review_defer.clicked.connect(self.defer_review)
        self.review_reopen = QPushButton("Reabrir")
        self.review_reopen.clicked.connect(self.reopen_review)
        actions.addWidget(QLabel("Destino:"), 0, 0)
        actions.addWidget(self.review_module, 0, 1, 1, 3)
        actions.addWidget(self.review_approve, 1, 0)
        actions.addWidget(self.review_keep, 1, 1)
        actions.addWidget(self.review_defer, 1, 2)
        actions.addWidget(self.review_reopen, 1, 3)
        detail_layout.addLayout(actions)
        self.review_action_hint = QLabel("", objectName="muted")
        self.review_action_hint.setWordWrap(True)
        detail_layout.addWidget(self.review_action_hint)
        splitter.addWidget(detail)
        splitter.setSizes([930, 410])
        layout.addWidget(splitter, 1)

        pagination = QHBoxLayout()
        self.review_previous_page = QPushButton("← Anterior")
        self.review_previous_page.clicked.connect(self.previous_review_page)
        self.review_next_page = QPushButton("Próxima →")
        self.review_next_page.clicked.connect(self.next_review_page)
        self.review_page_label = QLabel("Página 1")
        pagination.addWidget(self.review_previous_page)
        pagination.addWidget(self.review_page_label)
        pagination.addWidget(self.review_next_page)
        pagination.addStretch()
        pagination.addWidget(QLabel("100 itens por página", objectName="muted"))
        layout.addLayout(pagination)

        self.review_rows: list[dict[str, Any]] = []
        self.review_total = 0
        self.review_offset = 0
        self.review_loading = False
        self._load_review_filter_values()
        for sequence, callback in (
            ("Alt+A", self.approve_review),
            ("Alt+M", self.keep_review),
            ("Alt+D", self.defer_review),
            ("PageUp", self.previous_review_page),
            ("PageDown", self.next_review_page),
        ):
            shortcut = QShortcut(QKeySequence(sequence), page)
            shortcut.activated.connect(callback)
        self._update_review_actions()
        return page

    def _build_videos(self) -> QWidget:
        page, layout = self._page(
            "Vídeos",
            "Cursos e Biblioteca classificados por módulo; não há transcrição nesta versão.",
        )
        actions = QHBoxLayout()
        for label, action in [
            ("Login", "login"),
            ("Atualizar cursos", "courses"),
            ("Inventariar", "scan"),
            ("Classificar", "classify-videos"),
            ("Baixar", "download"),
            ("Executar tudo", "run"),
        ]:
            button = QPushButton(label, objectName="primary" if action == "run" else "")
            button.clicked.connect(lambda _checked=False, value=action: self.run_video_action(value))
            actions.addWidget(button)
        enroll = QPushButton("Inscrever selecionados")
        enroll.clicked.connect(self.enroll_selected_courses)
        actions.addWidget(enroll)
        organize = QPushButton("Organizar downloads")
        organize.clicked.connect(self.organize_video_downloads)
        actions.addWidget(organize)
        stop = QPushButton("Parar", objectName="danger")
        stop.clicked.connect(self.stop_video_action)
        actions.addWidget(stop)
        actions.addStretch()
        layout.addLayout(actions)

        filters = QHBoxLayout()
        self.video_source_filter = QComboBox()
        self.video_source_filter.addItem("Todas as fontes", "")
        self.video_source_filter.addItem("Cursos", "curso")
        self.video_source_filter.addItem("Biblioteca/Arquivos", "biblioteca")
        self.video_module_filter = QComboBox()
        self.video_module_filter.addItem("Todos os módulos", "")
        for module in ("Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar"):
            self.video_module_filter.addItem(module, module)
        self.video_status_filter = QComboBox()
        self.video_status_filter.addItem("Todas as situações", "")
        for label, value in (
            ("Disponível", "available"),
            ("Inscrito", "enrolled"),
            ("Baixado", "downloaded"),
            ("Pendente", "found"),
            ("Revisar", "review"),
            ("Indisponível", "unavailable"),
        ):
            self.video_status_filter.addItem(label, value)
        self.video_search = QLineEdit()
        self.video_search.setPlaceholderText("Filtrar por curso, pasta, capítulo ou vídeo")
        filters.addWidget(self.video_source_filter)
        filters.addWidget(self.video_module_filter)
        filters.addWidget(self.video_status_filter)
        filters.addWidget(self.video_search, 1)
        layout.addLayout(filters)

        classification = QHBoxLayout()
        classification.addWidget(QLabel("Classificar seleção como:"))
        self.video_manual_module = QComboBox()
        for module in ("Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar"):
            self.video_manual_module.addItem(module, module)
        classification.addWidget(self.video_manual_module)
        apply_module = QPushButton("Aplicar módulo")
        apply_module.clicked.connect(self.apply_video_module_override)
        classification.addWidget(apply_module)
        self.video_selection_detail = QLabel("", objectName="muted")
        classification.addWidget(self.video_selection_detail, 1)
        layout.addLayout(classification)

        splitter = QSplitter(Qt.Vertical)
        self.video_tree = QTreeWidget()
        self.video_tree.setColumnCount(5)
        self.video_tree.setHeaderLabels(
            ["Curso, pasta ou vídeo", "Fonte", "Módulo", "Situação", "Confiança"]
        )
        self.video_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.video_tree.setAlternatingRowColors(True)
        self.video_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 5):
            self.video_tree.header().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.video_tree.itemSelectionChanged.connect(self._video_selection_changed)
        splitter.addWidget(self.video_tree)
        self.video_status = QLabel("Pronto", objectName="muted")
        layout.addWidget(self.video_status)
        self.video_log = QPlainTextEdit()
        self.video_log.setReadOnly(True)
        self.video_log.setPlaceholderText(
            "O inventário, as inscrições, os downloads e eventuais falhas aparecerão aqui."
        )
        splitter.addWidget(self.video_log)
        splitter.setSizes([520, 180])
        layout.addWidget(splitter, 1)
        for widget in (
            self.video_source_filter,
            self.video_module_filter,
            self.video_status_filter,
        ):
            widget.currentIndexChanged.connect(self.refresh_video_tree)
        self.video_search.textChanged.connect(self.refresh_video_tree)
        return page

    def _build_settings(self) -> QWidget:
        page, layout = self._page(
            "Configurações",
            "Credenciais permanecem apenas no .env local e são mascaradas nos logs.",
        )
        form = QFrame(objectName="card")
        grid = QGridLayout(form)
        self.settings_fields: dict[str, QLineEdit | QComboBox] = {}
        fields = [
            ("Raiz Mary", "MARY_ROOT", str(self.settings.root), False),
            ("Email Movidesk", "MOVIDESK_EMAIL", os.environ.get("MOVIDESK_EMAIL", ""), False),
            ("Senha Movidesk", "MOVIDESK_PASSWORD", os.environ.get("MOVIDESK_PASSWORD", ""), True),
            ("Email Endoo", "ENDOO_EMAIL", os.environ.get("ENDOO_EMAIL", ""), False),
            ("Senha Endoo", "ENDOO_PASSWORD", os.environ.get("ENDOO_PASSWORD", ""), True),
            (
                "Intervalo (min)",
                "MARY_SYNC_INTERVAL_MINUTES",
                str(self.settings.sync_interval_minutes),
                False,
            ),
            (
                "Esforço padrão",
                "MARY_DEFAULT_EFFORT",
                self.settings.default_effort,
                False,
            ),
        ]
        for row, (label, key, value, secret) in enumerate(fields):
            grid.addWidget(QLabel(label), row, 0)
            if key == "MARY_DEFAULT_EFFORT":
                edit = QComboBox()
                edit.setAccessibleName(label)
                for effort_label, effort_value in (
                    ("Baixo", "low"),
                    ("Médio", "medium"),
                    ("Alto", "high"),
                    ("Muito alto", "xhigh"),
                    ("Máximo", "max"),
                    ("Ultra", "ultra"),
                ):
                    edit.addItem(effort_label, effort_value)
                selected = edit.findData(value)
                edit.setCurrentIndex(selected if selected >= 0 else 1)
            else:
                edit = QLineEdit(value)
                edit.setAccessibleName(label)
                if secret:
                    edit.setEchoMode(QLineEdit.Password)
            self.settings_fields[key] = edit
            grid.addWidget(edit, row, 1)
        self.provider_diagnostic = QLabel("", objectName="muted")
        self.provider_diagnostic.setWordWrap(True)
        grid.addWidget(QLabel("Diagnóstico"), len(fields), 0)
        grid.addWidget(self.provider_diagnostic, len(fields), 1)
        save = QPushButton("Salvar .env", objectName="primary")
        save.clicked.connect(self.save_settings)
        ocr_install = QPushButton("Instalar OCR portátil por+eng")
        ocr_install.clicked.connect(self.install_ocr)
        buttons = QHBoxLayout()
        buttons.addWidget(ocr_install)
        buttons.addStretch()
        buttons.addWidget(save)
        grid.addLayout(buttons, len(fields) + 1, 1)
        layout.addWidget(form)
        layout.addStretch()
        return page

    def _build_logs(self) -> QWidget:
        page, layout = self._page("Logs", "Eventos operacionais sem credenciais.")
        self.app_log = QPlainTextEdit()
        self.app_log.setReadOnly(True)
        self.app_log.setPlaceholderText(
            "Nenhum evento nesta sessão. Senhas e cookies nunca são exibidos."
        )
        layout.addWidget(self.app_log, 1)
        return page

    def _refresh_all(self) -> None:
        self.refresh_dashboard()
        self.refresh_video_tree()
        self.refresh_conversations()
        self.refresh_reviews()
        if not self.smoke_test:
            self.load_models()
        else:
            self.model_combo.clear()
            self.model_combo.addItem("Smoke test", "")
            self.load_efforts()
        status = self.orchestrator.provider_status()
        summary = " · ".join(
            f"{name.title()}: {'OK' if available else 'ausente'}"
            for name, available in status.items()
        )
        self.nav_provider_status.setText(summary)
        ocr = OcrManager(self.settings.tesseract_dir)
        self.provider_diagnostic.setText(
            summary + f"\nTesseract por+eng: {'OK' if ocr.is_ready() else 'não instalado'}"
        )

    def refresh_dashboard(self) -> None:
        with self.database.connect() as connection:
            total = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
            reviews = connection.execute(
                "SELECT count(*) FROM classification_reviews WHERE status='pending'"
            ).fetchone()[0]
            source_counts = {
                source: connection.execute(
                    "SELECT count(*) FROM documents WHERE source=? AND status='active'",
                    (source,),
                ).fetchone()[0]
                for source in ("wiki", "kb")
            }
            conversations = connection.execute(
                "SELECT count(*) FROM conversations"
            ).fetchone()[0]
            ocr_count = connection.execute(
                "SELECT count(*) FROM documents WHERE length(ocr_text)>0"
            ).fetchone()[0]
            latest_runs = {}
            for source in ("wiki", "kb"):
                latest_runs[source] = connection.execute(
                    """SELECT source,finished_at,status,stats_json,error
                       FROM sync_runs WHERE source=? ORDER BY id DESC LIMIT 1""",
                    (source,),
                ).fetchone()

        values = {
            "documents": total,
            "reviews": reviews,
            "ocr": ocr_count,
            "conversations": conversations,
        }
        for key, value in values.items():
            self.metric_labels[key].setText(str(value))

        for source in ("wiki", "kb"):
            self.source_count_labels[source].setText(
                f"{source_counts[source]} documentos"
            )
            run = latest_runs[source]
            if not run:
                self._set_source_status(source, "Nunca sincronizado", "", False)
                continue
            try:
                stats = json.loads(run["stats_json"] or "{}")
            except json.JSONDecodeError:
                stats = {}
            discovered = int(stats.get("discovered", 0) or 0)
            created = int(stats.get("created", 0) or 0)
            updated = int(stats.get("updated", 0) or 0)
            errors = int(stats.get("errors", 0) or 0)
            success = run["status"] == "completed" and not run["error"]
            if source == "kb" and discovered == 0:
                success = False
                status_text = "Nenhum artigo descoberto"
            elif success:
                status_text = "Sincronização concluída"
            else:
                status_text = "Falha na sincronização"
            finished_at = run["finished_at"] or ""
            try:
                finished_label = (
                    datetime.fromisoformat(finished_at)
                    .astimezone()
                    .strftime("%d/%m/%Y %H:%M")
                )
            except (TypeError, ValueError):
                finished_label = finished_at or "em execução"
            detail = (
                f"{finished_label}\n"
                f"Descobertos {discovered} · Novos {created} · "
                f"Atualizados {updated} · Erros {errors}"
            )
            if run["error"]:
                detail += f"\n{self._friendly_sync_error(str(run['error']))}"
            self._set_source_status(source, status_text, detail, success)

        inventory_path = self.settings.root / "metadata" / "videos.json"
        items: list[dict[str, Any]] = []
        if inventory_path.exists():
            try:
                parsed = json.loads(inventory_path.read_text(encoding="utf-8"))
                if isinstance(parsed, list):
                    items = [item for item in parsed if isinstance(item, dict)]
            except (OSError, json.JSONDecodeError):
                items = []
        downloaded = sum(item.get("status") == "downloaded" for item in items)
        failures = sum(item.get("status") in {"error", "failed"} for item in items)
        self.source_count_labels["video"].setText(f"{len(items)} vídeos")
        self._set_source_status(
            "video",
            "Inventário disponível" if items else "Inventário não encontrado",
            (
                f"Baixados {downloaded} · Pendentes {max(0, len(items) - downloaded - failures)} "
                f"· Falhas {failures}"
                if items
                else "Execute Inventariar na tela de Vídeos."
            ),
            bool(items),
        )

    def _set_source_status(
        self,
        source: str,
        status: str,
        detail: str,
        success: bool,
    ) -> None:
        label = self.source_status_labels[source]
        label.setObjectName("statusGood" if success else "statusWarn")
        label.setText(("OK — " if success else "ATENÇÃO — ") + status)
        label.style().unpolish(label)
        label.style().polish(label)
        self.source_detail_labels[source].setText(detail)

    @staticmethod
    def _friendly_sync_error(error: str) -> str:
        normalized = error.lower()
        if "target page, context or browser has been closed" in normalized:
            return "Sessão do navegador encerrada. Use “Login/KB visível”."
        if "mfa" in normalized or "captcha" in normalized or "intera" in normalized:
            return "Autenticação necessária. Use “Login/KB visível”."
        return error.strip().splitlines()[0][:140]

    def refresh_conversations(self, *_args: Any) -> None:
        selected = self.current_conversation
        term = self.conversation_search.text().lower() if hasattr(self, "conversation_search") else ""
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        for row in self.database.list_conversations(state=self.conversation_state):
            if term and term not in row["title"].lower():
                continue
            item = QListWidgetItem(
                f"{row['title']}\n{row['provider'].title()} · "
                f"{row['model'] or 'padrão'} · esforço {row['effort']} · "
                f"{self._status_label(row['status'])}"
            )
            item.setData(Qt.UserRole, row["id"])
            self.conversation_list.addItem(item)
            if row["id"] == selected:
                self.conversation_list.setCurrentItem(item)
        self.conversation_list.blockSignals(False)
        is_empty = self.conversation_list.count() == 0
        self.conversation_list.setVisible(not is_empty)
        self.conversation_empty.setVisible(is_empty)

    def new_conversation(self) -> None:
        if self.conversation_state != "active":
            self.conversation_state_combo.setCurrentIndex(
                self.conversation_state_combo.findData("active")
            )
        self.current_conversation = ""
        self.draft_conversation = True
        self._pending_first_message = ""
        self.draft_dynamic_tools = []
        self.draft_mcp_tools = []
        self.provider_combo.setEnabled(True)
        self.composer.setReadOnly(False)
        self.chat_title.setText("Nova conversa")
        self._clear_messages()
        self.conversation_list.clearSelection()
        self.chat_status.setText("Configure a conversa e envie a primeira mensagem")
        self.archive_button.setEnabled(False)
        self.delete_conversation_button.setEnabled(False)
        self.clone_button.setEnabled(False)
        self._update_tools_label()
        self._update_codex_controls()

    def _create_draft_conversation(self) -> None:
        provider = self.provider_combo.currentText() or "codex"
        model = self.model_combo.currentData() or self.model_combo.currentText()
        effort = self.effort_combo.currentData() or self.effort_combo.currentText()
        self.chat_status.setText("Criando conversa…")

        worker = Worker(
            self.orchestrator.new_conversation,
            provider,
            model,
            effort or self.settings.default_effort,
            self.tier_combo.currentData() or "",
            self.approval_combo.currentData() or "auto",
            self.mode_combo.currentData() or "default",
            self.draft_dynamic_tools,
            self.draft_mcp_tools,
        )
        worker.signals.finished.connect(self._conversation_created)
        worker.signals.error.connect(self._show_error)
        self.pool.start(worker)

    def _conversation_created(self, conversation_id: str) -> None:
        self.current_conversation = conversation_id
        self.draft_conversation = False
        self.refresh_conversations()
        for index in range(self.conversation_list.count()):
            item = self.conversation_list.item(index)
            if item.data(Qt.UserRole) == conversation_id:
                self.conversation_list.setCurrentItem(item)
                break
        self.chat_status.setText("Pronto")
        self.archive_button.setEnabled(True)
        self.delete_conversation_button.setEnabled(True)
        self.clone_button.setEnabled(True)
        self._update_codex_controls()
        is_active = self.conversation_state == "active"
        self.composer.setReadOnly(not is_active)
        self.archive_button.setText(
            "Restaurar da lixeira"
            if self.conversation_state == "trash"
            else "Restaurar"
            if self.conversation_state == "archived"
            else "Arquivar"
        )
        self.delete_conversation_button.setText(
            "Excluir definitivamente" if self.conversation_state == "trash" else "Excluir"
        )
        if self._pending_first_message:
            text = self._pending_first_message
            self._pending_first_message = ""
            self._send_current_message(text)

    def load_conversation(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if not current:
            return
        conversation_id = current.data(Qt.UserRole)
        row = self.database.get_conversation(conversation_id)
        if not row:
            return
        self.current_conversation = conversation_id
        self.draft_conversation = False
        self.chat_title.setText(row["title"])
        self.pending_model = str(row["model"])
        self.pending_effort = str(row["effort"] or self.settings.default_effort)
        self.pending_tier = str(row["service_tier"] or "")
        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentText(row["provider"])
        self.provider_combo.setEnabled(False)
        self.provider_combo.blockSignals(False)
        for combo, value in (
            (self.approval_combo, row["approval_profile"]),
            (self.mode_combo, row["collaboration_mode"]),
        ):
            combo.blockSignals(True)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.load_models()
        self._clear_messages()
        for message in self.database.messages(conversation_id):
            if message["role"] != "system":
                self._add_message(
                    message["role"], message["content"], int(message["id"])
                )
        self.chat_status.setText(self._status_label(row["status"]))
        self._update_tools_label()
        is_active = self.conversation_state == "active"
        self.composer.setReadOnly(not is_active)
        self.archive_button.setText(
            "Restaurar da lixeira"
            if self.conversation_state == "trash"
            else "Restaurar"
            if self.conversation_state == "archived"
            else "Arquivar"
        )
        self.delete_conversation_button.setText(
            "Excluir definitivamente" if self.conversation_state == "trash" else "Excluir"
        )
        self.archive_button.setEnabled(True)
        self.delete_conversation_button.setEnabled(True)
        self.clone_button.setEnabled(True)
        self._update_codex_controls()

    def _clear_messages(self) -> None:
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._add_chat_empty_state()
        self.assistant_widget = None
        self.assistant_markdown = ""

    def _add_chat_empty_state(self) -> None:
        empty = QFrame(objectName="card")
        empty.setMinimumWidth(360)
        empty.setMinimumHeight(140)
        empty.setMaximumWidth(620)
        empty.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("Pronto para criar um fluxo Mary", objectName="sectionTitle")
        title.setWordWrap(True)
        description = QLabel(
            "Crie uma conversa, escolha o provedor e descreva o treinamento "
            "ou problema. A base local relevante será pesquisada automaticamente.",
            objectName="muted",
        )
        description.setWordWrap(True)
        empty_layout.addWidget(title)
        empty_layout.addWidget(description)
        self.chat_empty_state = empty
        self.message_layout.insertWidget(0, empty, 0, Qt.AlignHCenter)

    def _add_message(
        self, role: str, content: str, message_id: int | None = None
    ) -> QTextBrowser:
        if hasattr(self, "chat_empty_state"):
            self.chat_empty_state.hide()
        card = QFrame(objectName="card")
        card.setMaximumWidth(860)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)
        role_label = QLabel("Você" if role == "user" else "Mary")
        role_label.setStyleSheet(
            f"font-weight: 700; color: {ACCESSIBLE_ORANGE if role == 'user' else BRAND_NAVY};"
        )
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setMarkdown(content)
        browser.document().documentLayout().documentSizeChanged.connect(
            lambda _size, widget=browser: widget.setMinimumHeight(
                min(520, max(58, int(widget.document().size().height()) + 22))
            )
        )
        message_header = QHBoxLayout()
        message_header.addWidget(role_label)
        message_header.addStretch()
        if role == "user" and message_id is not None:
            edit_button = QPushButton("Editar")
            edit_button.setToolTip("Corrigir esta mensagem em uma nova ramificação.")
            edit_button.clicked.connect(
                lambda _checked=False, mid=message_id, original=content: self.edit_message(
                    mid, original
                )
            )
            message_header.addWidget(edit_button)
        layout.addLayout(message_header)
        layout.addWidget(browser)
        self.message_layout.insertWidget(self.message_layout.count() - 1, card)
        QTimer.singleShot(
            0,
            lambda: self.message_scroll.verticalScrollBar().setValue(
                self.message_scroll.verticalScrollBar().maximum()
            ),
        )
        return browser

    def send_message(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text:
            return
        if not self.current_conversation:
            if self.draft_conversation:
                self._pending_first_message = text
                self._create_draft_conversation()
            else:
                QMessageBox.information(self, APP_TITLE, "Crie uma conversa antes de enviar.")
            return
        self._send_current_message(text)

    def _send_current_message(self, text: str) -> None:
        self.composer.clear()
        self._add_message("user", text)
        self.assistant_markdown = ""
        self.assistant_widget = self._add_message("assistant", "")
        self.chat_status.setText("Executando…")
        try:
            self.orchestrator.send(
                self.current_conversation,
                text,
                self.runtime_event_signal.emit,
            )
        except Exception as exc:
            self._show_error(str(exc))

    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        if event.conversation_id != self.current_conversation:
            self.refresh_conversations()
            return
        if event.kind == "assistant_delta":
            self.assistant_markdown += event.text
            if self.assistant_widget:
                self.assistant_widget.setMarkdown(self.assistant_markdown)
        elif event.kind == "turn_started":
            self.chat_status.setText("Executando…")
        elif event.kind == "turn_completed":
            self.chat_status.setText("Pronto")
            self.refresh_conversations()
        elif event.kind == "tool_event":
            self._add_runtime_card(event.text, event.payload)
        elif event.kind == "approval_requested":
            self._request_approval(event)
        elif event.kind == "dynamic_tool_approval_requested":
            self._request_dynamic_tool_approval(event)
        elif event.kind == "error":
            self.chat_status.setText("Erro")
            self._add_runtime_card("Erro", {"message": event.text})
        self._append_log(f"{event.kind}: {event.text}")

    def _add_runtime_card(self, title: str, payload: dict[str, Any]) -> None:
        details = QTextBrowser()
        details.setMarkdown(
            f"**{title}**\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)[:6000]}\n```"
        )
        details.setMaximumHeight(180)
        self.message_layout.insertWidget(self.message_layout.count() - 1, details)

    def _request_approval(self, event: RuntimeEvent) -> None:
        dialog = ApprovalDialog(event.payload, self)
        accepted = dialog.exec() == QDialog.Accepted
        request_id = str(event.payload.get("request_id", ""))
        request = dict(event.payload)
        request["_decision"] = dialog.action
        if dialog.approved:
            request["content"] = dialog.response_content()
        try:
            self.orchestrator.approve(
                event.conversation_id,
                request_id,
                accepted and dialog.approved,
                dialog.session,
                request,
            )
        except Exception as exc:
            self._show_error(str(exc))

    def _request_dynamic_tool_approval(self, event: RuntimeEvent) -> None:
        dialog = ApprovalDialog(event.payload, self)
        accepted = dialog.exec() == QDialog.Accepted and dialog.approved
        try:
            self.orchestrator.approve_dynamic_tool(
                str(event.payload.get("request_id") or ""), accepted
            )
        except Exception as exc:
            self._show_error(str(exc))

    def stop_turn(self) -> None:
        if self.current_conversation:
            self.orchestrator.interrupt(self.current_conversation)

    def clone_conversation(self) -> None:
        if not self.current_conversation:
            return
        destination = "claude" if self.provider_combo.currentText() == "codex" else "codex"
        effort = self.effort_combo.currentData() or self.effort_combo.currentText()
        try:
            new_id = self.orchestrator.clone(
                self.current_conversation,
                destination,
                effort=effort or self.settings.default_effort,
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._conversation_created(new_id)

    def _conversation_state_changed(self) -> None:
        self.conversation_state = str(self.conversation_state_combo.currentData() or "active")
        self.current_conversation = ""
        self.draft_conversation = False
        self.refresh_conversations()
        self._clear_messages()
        self.chat_title.setText(
            {"active": "Conversas ativas", "archived": "Conversas arquivadas", "trash": "Lixeira"}[
                self.conversation_state
            ]
        )
        self.composer.setReadOnly(True)
        self.archive_button.setEnabled(False)
        self.delete_conversation_button.setEnabled(False)
        self.clone_button.setEnabled(False)
        self._update_codex_controls()

    def archive_current_conversation(self) -> None:
        if not self.current_conversation:
            return
        operation = (
            self.orchestrator.restore
            if self.conversation_state == "trash"
            else self.orchestrator.unarchive
            if self.conversation_state == "archived"
            else self.orchestrator.archive
        )
        self._run_conversation_operation(operation)

    def delete_current_conversation(self) -> None:
        if not self.current_conversation:
            return
        if self.conversation_state == "trash":
            confirmation, accepted = QInputDialog.getText(
                self,
                "Excluir definitivamente",
                "Digite EXCLUIR para apagar definitivamente a conversa e seus arquivos:",
            )
            if not accepted or confirmation.strip() != "EXCLUIR":
                return
            self._run_conversation_operation(self.orchestrator.purge)
            return
        answer = QMessageBox.question(
            self,
            "Mover para a lixeira",
            "A conversa e sua pasta serão movidas para a lixeira recuperável. Continuar?",
        )
        if answer == QMessageBox.Yes:
            self._run_conversation_operation(self.orchestrator.trash)

    def _run_conversation_operation(self, operation: Callable[[str], None]) -> None:
        conversation_id = self.current_conversation
        self.chat_status.setText("Processando conversa…")
        worker = Worker(operation, conversation_id)
        worker.signals.finished.connect(lambda _result: self._conversation_operation_done())
        worker.signals.error.connect(self._show_error)
        self.pool.start(worker)

    def _conversation_operation_done(self) -> None:
        self.current_conversation = ""
        self._clear_messages()
        self.refresh_conversations()
        self.chat_status.setText("Pronto")
        self.composer.setReadOnly(True)
        self.archive_button.setEnabled(False)
        self.delete_conversation_button.setEnabled(False)
        self.clone_button.setEnabled(False)
        self._update_codex_controls()

    def open_tools(self) -> None:
        if self.provider_combo.currentText() != "codex":
            QMessageBox.information(
                self, APP_TITLE, "Tools dinâmicas e MCP estão disponíveis nas conversas Codex."
            )
            return
        if self.mcp_tool_catalog:
            self._show_tool_dialog()
            return
        self.chat_status.setText("Carregando tools MCP…")
        worker = Worker(self.orchestrator.mcp_tools, "codex")
        worker.signals.finished.connect(self._mcp_tools_loaded)
        worker.signals.error.connect(lambda error: self._mcp_tools_loaded([], error))
        self.pool.start(worker)

    def _mcp_tools_loaded(self, tools: list[dict[str, Any]], error: str = "") -> None:
        self.mcp_tool_catalog = tools
        if error:
            self._append_log(error)
        self.chat_status.setText("Pronto")
        self._show_tool_dialog()

    def _show_tool_dialog(self) -> None:
        selected = (
            self.database.conversation_tools(self.current_conversation)
            if self.current_conversation
            else {"dynamic": self.draft_dynamic_tools, "mcp": self.draft_mcp_tools}
        )
        dialog = ToolSelectionDialog(
            self.database, self.mcp_tool_catalog, selected, self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        dynamic_ids, mcp_tools = dialog.selection()
        if self.current_conversation:
            if dynamic_ids == selected["dynamic"] and mcp_tools == selected["mcp"]:
                return
            answer = QMessageBox.question(
                self,
                "Alterar tools",
                "Alterar tools cria uma ramificação e preserva a conversa atual. Continuar?",
            )
            if answer != QMessageBox.Yes:
                return
            worker = Worker(
                self.orchestrator.clone,
                self.current_conversation,
                "codex",
                "",
                str(self.effort_combo.currentData() or self.settings.default_effort),
                dynamic_ids,
                mcp_tools,
            )
            worker.signals.finished.connect(self._conversation_created)
            worker.signals.error.connect(self._show_error)
            self.pool.start(worker)
        else:
            self.draft_dynamic_tools = dynamic_ids
            self.draft_mcp_tools = mcp_tools
            self._update_tools_label()

    def _update_tools_label(self) -> None:
        if self.current_conversation:
            selected = self.database.conversation_tools(self.current_conversation)
            count = len(selected["dynamic"]) + len(selected["mcp"])
        else:
            count = len(self.draft_dynamic_tools) + len(self.draft_mcp_tools)
        self.tools_button.setText(f"Tools ({count})")

    def correct_composer_text(self) -> None:
        text = self.composer.toPlainText()
        if not text.strip():
            return
        if not self.spell_checker.available:
            QMessageBox.warning(
                self,
                APP_TITLE,
                "O corretor local não está instalado neste pacote.",
            )
            return
        dialog = SpellReviewDialog(self.spell_checker, text, self)
        if dialog.exec() == QDialog.Accepted:
            self.composer.setPlainText(dialog.corrected_text())

    def edit_message(self, message_id: int, original: str) -> None:
        replacement, accepted = QInputDialog.getMultiLineText(
            self,
            "Editar mensagem",
            "A correção será enviada em uma nova ramificação:",
            original,
        )
        replacement = replacement.strip()
        if not accepted or not replacement or replacement == original.strip():
            return
        source_id = self.current_conversation
        worker = Worker(
            self.orchestrator.branch_from_message,
            source_id,
            message_id,
            replacement,
        )
        worker.signals.finished.connect(
            lambda new_id, text=replacement: self._branch_created_and_send(new_id, text)
        )
        worker.signals.error.connect(self._show_error)
        self.pool.start(worker)

    def _branch_created_and_send(self, conversation_id: str, text: str) -> None:
        self._conversation_created(conversation_id)
        self._send_current_message(text)

    def load_models(self, *_args: Any) -> None:
        provider = self.provider_combo.currentText() or "codex"
        current_model = self.pending_model or self.model_combo.currentData() or ""
        self.model_combo.clear()
        self.model_combo.addItem("Carregando…", "")

        def loaded(models: list[dict[str, Any]]) -> None:
            self.model_combo.set_provider_models(provider, models)
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_metadata = {}
            for model in models:
                model_id = model.get("id") or model.get("model") or ""
                self.model_metadata[str(model_id)] = model
                self.model_combo.addItem(
                    model.get("displayName") or model_id,
                    model_id,
                )
                if model.get("isDefault"):
                    self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
            selected_model = self.pending_model or current_model
            if selected_model:
                index = self.model_combo.findData(selected_model)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
            self.model_combo.blockSignals(False)
            self.pending_model = ""
            self.load_efforts()
            self.load_service_tiers()
            if provider == "codex":
                self.load_collaboration_modes()
            self._preload_other_models(provider)

        worker = Worker(self.orchestrator.models, provider)
        worker.signals.finished.connect(loaded)
        worker.signals.error.connect(
            lambda error: (
                self.model_combo.clear(),
                self.model_combo.addItem("Indisponível", ""),
                self._append_log(error),
            )
        )
        self.pool.start(worker)

    def load_collaboration_modes(self) -> None:
        selected = str(self.mode_combo.currentData() or "default")

        def loaded(modes: list[dict[str, Any]]) -> None:
            self.mode_combo.blockSignals(True)
            self.mode_combo.clear()
            for mode in modes:
                value = str(mode.get("mode") or "")
                if value in {"default", "plan"}:
                    self.mode_combo.addItem(
                        str(mode.get("name") or ("Build" if value == "default" else "Plan")),
                        value,
                    )
            if not self.mode_combo.count():
                self.mode_combo.addItem("Build", "default")
                self.mode_combo.addItem("Plan", "plan")
            index = self.mode_combo.findData(selected)
            self.mode_combo.setCurrentIndex(max(0, index))
            self.mode_combo.blockSignals(False)

        worker = Worker(self.orchestrator.collaboration_modes, "codex")
        worker.signals.finished.connect(loaded)
        worker.signals.error.connect(
            lambda error: (self._append_log(error), loaded([]))
        )
        self.pool.start(worker)

    def _preload_other_models(self, current_provider: str) -> None:
        other = "claude" if current_provider == "codex" else "codex"
        if other in self.model_combo._catalogs:
            return
        worker = Worker(self.orchestrator.models, other)
        worker.signals.finished.connect(
            lambda models, name=other: self.model_combo.set_provider_models(name, models)
        )
        worker.signals.error.connect(lambda error: self._append_log(error))
        self.pool.start(worker)

    def _model_picker_selected(self, provider: str, model_id: str) -> None:
        if provider != self.provider_combo.currentText():
            if self.current_conversation:
                answer = QMessageBox.question(
                    self,
                    "Trocar provedor",
                    "Trocar o provedor cria uma ramificação e preserva a conversa atual. Continuar?",
                )
                if answer != QMessageBox.Yes:
                    return
                try:
                    new_id = self.orchestrator.clone(
                        self.current_conversation,
                        provider,
                        model=model_id,
                        effort=self.effort_combo.currentData() or self.settings.default_effort,
                    )
                except Exception as exc:
                    self._show_error(str(exc))
                    return
                self._conversation_created(new_id)
                return
            self.provider_combo.setCurrentText(provider)
        index = self.model_combo.findData(model_id)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

    def load_service_tiers(self) -> None:
        model_id = str(self.model_combo.currentData() or "")
        metadata = self.model_metadata.get(model_id, {})
        tiers = metadata.get("serviceTiers") or []
        selected = self.pending_tier or self.tier_combo.currentData() or ""
        self.tier_combo.blockSignals(True)
        self.tier_combo.clear()
        if not tiers:
            self.tier_combo.addItem("Padrão", "")
        else:
            default_tier = str(metadata.get("defaultServiceTier") or "")
            for tier in tiers:
                tier_id = str(tier.get("id") or "")
                self.tier_combo.addItem(str(tier.get("name") or tier_id), tier_id)
                self.tier_combo.setItemData(
                    self.tier_combo.count() - 1,
                    str(tier.get("description") or ""),
                    Qt.ToolTipRole,
                )
                if tier_id == default_tier:
                    self.tier_combo.setCurrentIndex(self.tier_combo.count() - 1)
        index = self.tier_combo.findData(str(selected))
        if index >= 0:
            self.tier_combo.setCurrentIndex(index)
        self.tier_combo.blockSignals(False)
        self.pending_tier = ""

    def load_efforts(self, *_args: Any) -> None:
        provider = self.provider_combo.currentText() or "codex"
        model_id = str(self.model_combo.currentData() or "")
        metadata = self.model_metadata.get(model_id, {})
        raw_efforts = (
            metadata.get("supportedReasoningEfforts")
            or metadata.get("supported_reasoning_efforts")
            or []
        )
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
            value = str(value).strip().lower()
            if value and value not in efforts:
                efforts.append(value)
        if not efforts:
            efforts = (
                ["low", "medium", "high", "xhigh", "max"]
                if provider == "claude"
                else ["minimal", "low", "medium", "high", "xhigh"]
            )

        selected_effort = (
            self.pending_effort
            or self.effort_combo.currentData()
            or self.settings.default_effort
        )
        self.effort_combo.blockSignals(True)
        self.effort_combo.clear()
        effort_labels = {
            "none": "Nenhum",
            "minimal": "Mínimo",
            "low": "Baixo",
            "medium": "Médio",
            "high": "Alto",
            "xhigh": "Muito alto",
            "max": "Máximo",
            "ultra": "Ultra",
        }
        for effort in efforts:
            self.effort_combo.addItem(effort_labels.get(effort, effort.title()), effort)
        index = self.effort_combo.findData(str(selected_effort))
        if index < 0:
            index = self.effort_combo.findData("medium")
        if index >= 0:
            self.effort_combo.setCurrentIndex(index)
        self.effort_combo.blockSignals(False)
        self.pending_effort = ""
        self.load_service_tiers()
        self._update_codex_controls()
        self._chat_option_changed()

    def _chat_option_changed(self, *_args: Any) -> None:
        if not self.current_conversation or self.conversation_state != "active":
            return
        model = self.model_combo.currentData() or self.model_combo.currentText()
        effort = self.effort_combo.currentData() or self.effort_combo.currentText()
        if effort:
            options = ConversationOptions(
                model=str(model or ""),
                effort=str(effort),
                service_tier=str(self.tier_combo.currentData() or ""),
                approval_profile=str(self.approval_combo.currentData() or "auto"),
                collaboration_mode=str(self.mode_combo.currentData() or "default"),
            )
            worker = Worker(
                self.orchestrator.update_options,
                self.current_conversation,
                options,
            )
            worker.signals.finished.connect(lambda _result: self.refresh_conversations())
            worker.signals.error.connect(self._show_error)
            self.pool.start(worker)

    def _update_codex_controls(self) -> None:
        is_active = self.conversation_state == "active"
        self.model_combo.setEnabled(is_active)
        self.effort_combo.setEnabled(is_active)
        is_codex = (
            self.provider_combo.currentText() == "codex"
            and is_active
        )
        for widget in (
            self.tier_combo,
            self.approval_combo,
            self.mode_combo,
            self.tools_button,
        ):
            widget.setEnabled(is_codex)
        if not is_codex:
            self.tools_button.setToolTip("Tools compartilhadas são exclusivas do Codex.")

    def search_context(self) -> None:
        query = self.context_search.text().strip()
        self.context_results.clear()
        if not query:
            return
        try:
            results = self.database.search(query, limit=12)
        except Exception as exc:
            self._show_error(str(exc))
            return
        for result in results:
            item = QListWidgetItem(
                f"{result['title']}\n{result['module']} · {result['source'].upper()}"
            )
            item.setData(Qt.UserRole, result)
            self.context_results.addItem(item)

    def insert_context_reference(self, item: QListWidgetItem) -> None:
        result = item.data(Qt.UserRole)
        self.composer.insertPlainText(f"\nConsidere a fonte local: {result['local_path']}\n")

    def search_knowledge(self) -> None:
        query = self.knowledge_query.text().strip()
        module = self.knowledge_module.currentText()
        source = self.knowledge_source.currentText()
        if not query:
            query = "*"
        try:
            if query == "*":
                with self.database.connect() as connection:
                    rows = connection.execute(
                        """SELECT *,'' AS excerpt FROM documents
                           WHERE status='active' ORDER BY synced_at DESC LIMIT 200"""
                    ).fetchall()
                    results = [dict(row) for row in rows]
            else:
                results = self.database.search(
                    query,
                    limit=200,
                    module="" if module == "Todos" else module,
                    source="" if source == "Todas" else source,
                )
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.knowledge_results = results
        self.knowledge_table.setRowCount(len(results))
        for row_index, result in enumerate(results):
            values = [
                result["title"],
                result["module"],
                result["source"].upper(),
                self._status_label(result["review_status"]),
            ]
            for column, value in enumerate(values):
                self.knowledge_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        plural = len(results) != 1
        self.knowledge_count.setText(
            f"{len(results)} documento{'s' if plural else ''} "
            f"encontrado{'s' if plural else ''}"
        )
        if results:
            self.knowledge_table.setCurrentCell(0, 0)
            self.preview_knowledge()
        else:
            self.knowledge_preview.setMarkdown(
                "### Nenhum documento encontrado\n\n"
                "Tente remover filtros ou pesquisar por outro termo."
            )

    def preview_knowledge(self) -> None:
        row = self.knowledge_table.currentRow()
        if row < 0 or row >= len(self.knowledge_results):
            return
        result = self.knowledge_results[row]
        path = Path(result["local_path"])
        if path.exists():
            self.knowledge_preview.setMarkdown(path.read_text(encoding="utf-8"))
        else:
            self.knowledge_preview.setMarkdown(result.get("markdown", ""))

    @staticmethod
    def _module_filter_combo(placeholder: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem(placeholder, "")
        for module in (
            "Fiscal",
            "ADM_FIN_ESTOQUE",
            "PDV",
            "Multimodulo",
            "Revisar",
        ):
            combo.addItem(module, module)
        return combo

    @staticmethod
    def _status_label(status: str) -> str:
        value = str(status or "").strip()
        return STATUS_LABELS.get(value.lower(), value.replace("_", " ").title())

    def _load_review_filter_values(self) -> None:
        values = self.database.review_filter_values()
        for combo, label, entries in (
            (self.review_product, "Todos os produtos", values["products"]),
            (self.review_category, "Todas as categorias", values["categories"]),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(label, "")
            for entry in entries:
                combo.addItem(entry, entry)
            combo.setCurrentIndex(0)
            if combo.lineEdit():
                combo.lineEdit().setCursorPosition(0)
            combo.blockSignals(False)
            if combo.lineEdit():
                combo.lineEdit().editingFinished.connect(self.reset_review_page)

    @staticmethod
    def _review_combo_value(combo: QComboBox) -> str:
        data = combo.currentData()
        if data is not None:
            return str(data)
        text = combo.currentText().strip()
        return "" if text.lower().startswith(("todos", "todas")) else text

    @staticmethod
    def _review_json_list(raw: str) -> list[str]:
        try:
            values = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return [str(value) for value in values] if isinstance(values, list) else []

    def _review_filters(self) -> ReviewFilters:
        return ReviewFilters(
            query=self.review_query.text().strip(),
            source=self._review_combo_value(self.review_source),
            current_module=self._review_combo_value(self.review_current_module),
            suggested_module=self._review_combo_value(
                self.review_suggested_module
            ),
            confidence_band=self._review_combo_value(self.review_confidence),
            product=self._review_combo_value(self.review_product),
            category=self._review_combo_value(self.review_category),
            status=self._review_combo_value(self.review_status_filter) or "pending",
            period_days=int(self.review_period.currentData() or 0),
            special=self._review_combo_value(self.review_special),
            sort=self._review_combo_value(self.review_sort) or "risk",
            limit=100,
            offset=self.review_offset,
        )

    def reset_review_page(self, *_args: Any) -> None:
        if not hasattr(self, "review_table"):
            return
        self.review_offset = 0
        self.refresh_reviews()

    def refresh_reviews(self) -> None:
        if not hasattr(self, "review_table"):
            return
        try:
            page = self.database.query_reviews(self._review_filters())
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.review_loading = True
        self.review_rows = page.items
        self.review_total = page.total
        self.review_offset = page.offset
        self.review_table.clearContents()
        self.review_table.setRowCount(len(self.review_rows))
        for row_index, row in enumerate(self.review_rows):
            reasons = self._review_json_list(row["reasons_json"])
            main_reason = reasons[0] if reasons else "Sem evidência registrada"
            risk = f"{row['risk_label']} · {main_reason}"
            values = [
                "",
                row["title"],
                row["source"].upper(),
                row["current_module"],
                row["suggested_module"],
                f"{row['confidence']:.0%}",
                row["product"] or "Não identificado",
                row["category"] or "Sem categoria",
                risk,
                row["updated_at"] or row["document_updated_at"] or row["synced_at"],
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, int(row["id"]))
                if column == 0:
                    item.setFlags(
                        Qt.ItemIsEnabled
                        | Qt.ItemIsSelectable
                        | Qt.ItemIsUserCheckable
                    )
                    item.setCheckState(Qt.Unchecked)
                    item.setTextAlignment(Qt.AlignCenter)
                self.review_table.setItem(row_index, column, item)
        self.review_loading = False

        first = self.review_offset + 1 if self.review_total else 0
        last = min(self.review_offset + len(self.review_rows), self.review_total)
        self.review_summary.setText(
            f"{self.review_total} resultados · exibindo {first}–{last} · "
            "0 selecionados"
        )
        current_page = self.review_offset // page.limit + 1
        total_pages = max(1, (self.review_total + page.limit - 1) // page.limit)
        self.review_page_label.setText(f"Página {current_page} de {total_pages}")
        self.review_previous_page.setEnabled(self.review_offset > 0)
        self.review_next_page.setEnabled(
            self.review_offset + page.limit < self.review_total
        )
        self.review_note.clear()
        if self.review_rows:
            self.review_table.setCurrentCell(0, 1)
        else:
            self.review_detail_title.setText("Nenhuma revisão encontrada")
            self.review_preview.setMarkdown(
                "Ajuste os filtros ou escolha outro estado da revisão."
            )
        self._update_review_actions()

    def review_selection_changed(self, _item: QTableWidgetItem) -> None:
        if self.review_loading:
            return
        self._refresh_review_selection_state()

    def _refresh_review_selection_state(self) -> None:
        selected = len(self._checked_review_rows())
        first = self.review_offset + 1 if self.review_total else 0
        last = min(self.review_offset + len(self.review_rows), self.review_total)
        self.review_summary.setText(
            f"{self.review_total} resultados · exibindo {first}–{last} · "
            f"{selected} selecionados"
        )
        self._update_review_actions()

    def select_all_reviews(self) -> None:
        self.review_loading = True
        try:
            for row_index in range(len(self.review_rows)):
                item = self.review_table.item(row_index, 0)
                if item:
                    item.setCheckState(Qt.Checked)
        finally:
            self.review_loading = False
        self._refresh_review_selection_state()

    def clear_review_selection(self) -> None:
        self.review_loading = True
        try:
            for row_index in range(len(self.review_rows)):
                item = self.review_table.item(row_index, 0)
                if item:
                    item.setCheckState(Qt.Unchecked)
        finally:
            self.review_loading = False
        self._refresh_review_selection_state()

    def _checked_review_rows(self) -> list[dict[str, Any]]:
        checked: list[dict[str, Any]] = []
        for row_index, row in enumerate(self.review_rows):
            item = self.review_table.item(row_index, 0)
            if item and item.checkState() == Qt.Checked:
                checked.append(row)
        return checked

    def _selected_review_rows(self) -> list[dict[str, Any]]:
        checked = self._checked_review_rows()
        if checked:
            return checked
        row_index = self.review_table.currentRow()
        if 0 <= row_index < len(self.review_rows):
            return [self.review_rows[row_index]]
        return []

    def preview_review(self) -> None:
        row_index = self.review_table.currentRow()
        if row_index < 0 or row_index >= len(self.review_rows):
            self._update_review_actions()
            return
        review = self.review_rows[row_index]
        self.review_detail_title.setText(review["title"])
        if review["suggested_module"] in [
            self.review_module.itemText(index)
            for index in range(self.review_module.count())
        ]:
            self.review_module.setCurrentText(review["suggested_module"])

        reasons = self._review_json_list(review["reasons_json"])
        evidence = "\n".join(f"- {reason}" for reason in reasons) or "- Sem evidência"
        assets = self._review_json_list(review["assets_json"])
        asset_lines = []
        for raw_path in assets:
            asset_path = Path(raw_path)
            if not asset_path.is_absolute():
                asset_path = self.settings.root / asset_path
            asset_url = QUrl.fromLocalFile(str(asset_path)).toString()
            asset_lines.append(f"- [{asset_path.name}]({asset_url})")
        asset_markdown = "\n".join(asset_lines) or "- Nenhuma imagem associada"
        note = review["decision_note"] or "Sem nota"
        content = review["markdown"] or "_Documento sem Markdown._"
        ocr = review["ocr_text"] or "_Sem OCR associado._"
        metadata = f"""\
- **Estado:** {self._status_label(review['status'])}
- **Risco:** {review['risk_label']}
- **Fonte / ID:** {review['source'].upper()} · {review['source_id']}
- **Módulo atual → sugerido:** {review['current_module']} → {review['suggested_module']}
- **Confiança:** {review['confidence']:.0%}
- **Produto:** {review['product'] or 'Não identificado'}
- **Categoria:** {review['category'] or 'Sem categoria'}
- **Atualização:** {review['document_updated_at'] or review['synced_at']}
- **Nota registrada:** {note}

## Evidências

{evidence}

## Imagens

{asset_markdown}

## Conteúdo

{content}

## OCR

{ocr}
"""
        local_path = Path(review["local_path"]) if review["local_path"] else None
        if local_path:
            self.review_preview.document().setBaseUrl(
                QUrl.fromLocalFile(str(local_path.parent) + os.sep)
            )
        self.review_preview.setMarkdown(metadata)
        self.review_note.setPlainText(review["decision_note"] or "")
        self._update_review_actions()

    def _update_review_actions(self) -> None:
        if not hasattr(self, "review_approve"):
            return
        rows = self._selected_review_rows()
        pending = bool(rows) and all(row["status"] == "pending" for row in rows)
        reopenable = bool(rows) and all(
            row["status"] != "pending" and row["is_latest"] for row in rows
        )
        hint = ""
        if len(rows) > 1:
            hint = (
                f"Lote: {len(rows)} itens receberão o destino "
                f"{self.review_module.currentText()}."
            )
        elif rows:
            hint = "Atalhos: Alt+A aprovar · Alt+M manter · Alt+D adiar."
        self.review_approve.setEnabled(pending)
        self.review_keep.setEnabled(pending)
        self.review_defer.setEnabled(pending)
        self.review_reopen.setEnabled(reopenable)
        self.review_module.setEnabled(pending)
        self.review_select_all.setEnabled(bool(self.review_rows))
        self.review_clear_selection.setEnabled(bool(self._checked_review_rows()))
        self.review_open_source.setEnabled(bool(rows))
        self.review_open_local.setEnabled(
            bool(rows and rows[0]["local_path"] and Path(rows[0]["local_path"]).exists())
        )
        self.review_copy_citation.setEnabled(bool(rows))
        self.review_action_hint.setText(hint)

    def previous_review_page(self) -> None:
        if self.review_offset <= 0:
            return
        self.review_offset = max(0, self.review_offset - 100)
        self.refresh_reviews()

    def next_review_page(self) -> None:
        if self.review_offset + 100 >= self.review_total:
            return
        self.review_offset += 100
        self.refresh_reviews()

    def clear_review_filters(self) -> None:
        self.review_query.blockSignals(True)
        self.review_query.clear()
        self.review_query.blockSignals(False)
        for combo in (
            self.review_source,
            self.review_current_module,
            self.review_suggested_module,
            self.review_confidence,
            self.review_product,
            self.review_category,
            self.review_period,
            self.review_special,
            self.review_sort,
        ):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.review_status_filter.blockSignals(True)
        self.review_status_filter.setCurrentIndex(
            self.review_status_filter.findData("pending")
        )
        self.review_status_filter.blockSignals(False)
        self.reset_review_page()

    def apply_review_preset(self, preset: str) -> None:
        self.clear_review_filters()
        for combo in (
            self.review_status_filter,
            self.review_special,
            self.review_sort,
        ):
            combo.blockSignals(True)
        if preset == "deferred":
            self.review_status_filter.setCurrentIndex(
                self.review_status_filter.findData("deferred")
            )
        elif preset == "simple":
            self.review_special.setCurrentIndex(
                self.review_special.findData("simple")
            )
            self.review_sort.setCurrentIndex(
                self.review_sort.findData("confidence_desc")
            )
        elif preset == "no_product":
            self.review_special.setCurrentIndex(
                self.review_special.findData("no_product")
            )
        else:
            self.review_sort.setCurrentIndex(self.review_sort.findData("risk"))
        for combo in (
            self.review_status_filter,
            self.review_special,
            self.review_sort,
        ):
            combo.blockSignals(False)
        self.reset_review_page()

    def open_review_source(self) -> None:
        rows = self._selected_review_rows()
        if rows and rows[0]["url"]:
            QDesktopServices.openUrl(QUrl(rows[0]["url"]))

    def open_review_local(self) -> None:
        rows = self._selected_review_rows()
        if not rows or not rows[0]["local_path"]:
            return
        path = Path(rows[0]["local_path"])
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def copy_review_citation(self) -> None:
        rows = self._selected_review_rows()
        if not rows:
            return
        row = rows[0]
        citation = (
            f"[{row['title']}]({row['url']}) — "
            f"{row['current_module']} · {row['source'].upper()} · ID {row['source_id']}"
        )
        QApplication.clipboard().setText(citation)
        self.review_action_hint.setText("Citação copiada.")

    def _confirm_bulk_review(self, action: str, rows: list[dict[str, Any]]) -> bool:
        if len(rows) <= 1:
            return True
        labels = {
            "approve": "aprovar",
            "keep": "manter o módulo atual de",
            "defer": "adiar",
            "reopen": "reabrir",
        }
        destination = (
            f"\nDestino: {self.review_module.currentText()}"
            if action == "approve"
            else ""
        )
        answer = QMessageBox.question(
            self,
            "Confirmar ação em lote",
            f"Deseja {labels[action]} {len(rows)} revisões selecionadas?"
            f"{destination}\n\n"
            + (
                "O destino escolhido será aplicado a todos os itens, "
                "independentemente das sugestões individuais.\n\n"
                if action == "approve"
                else ""
            )
            + "A ação ficará registrada no histórico.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _run_review_action(self, action: str) -> None:
        rows = self._selected_review_rows()
        if not rows or not self._confirm_bulk_review(action, rows):
            return
        try:
            count = self.database.decide_reviews(
                [int(row["id"]) for row in rows],
                action,
                module=self.review_module.currentText(),
                note=self.review_note.toPlainText().strip(),
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        verbs = {
            "approve": "aprovadas",
            "keep": "mantidas",
            "defer": "adiadas",
            "reopen": "reabertas",
        }
        self.refresh_reviews()
        self.review_action_hint.setText(f"{count} revisões {verbs[action]}.")
        self.refresh_dashboard()

    def approve_review(self) -> None:
        self._run_review_action("approve")

    def keep_review(self) -> None:
        self._run_review_action("keep")

    def defer_review(self) -> None:
        self._run_review_action("defer")

    def reopen_review(self) -> None:
        self._run_review_action("reopen")

    def sync_wiki(self) -> None:
        self._run_sync(
            "Wiki",
            lambda: WikiSync(self.settings, self.database, self._sync_progress).sync(),
        )

    def sync_kb(self, headed: bool = False) -> None:
        self._run_sync(
            "KB",
            lambda: self._sync_kb_with_auth_fallback(headed=headed),
        )

    def _sync_kb_with_auth_fallback(self, headed: bool = False):
        sync = MovideskSync(
            self.settings,
            self.database,
            self._sync_progress,
        )
        if headed:
            sync.login()
            return sync.sync(headed=False)
        try:
            return sync.sync(headed=False)
        except MovideskInteractiveLoginRequired:
            self._sync_progress(
                "KB: o Movidesk exige confirmação. Abrindo uma janela "
                "exclusiva para login, MFA ou CAPTCHA."
            )
            sync.login()
            return sync.sync(headed=False)

    def sync_all(self) -> None:
        def operation():
            wiki = WikiSync(self.settings, self.database, self._sync_progress).sync()
            kb = self._sync_kb_with_auth_fallback()
            return {"wiki": wiki.to_dict(), "kb": kb.to_dict()}

        self._run_sync("Wiki + KB", operation)

    def _run_sync(self, label: str, operation: Callable[[], Any]) -> None:
        if self.sync_running:
            QMessageBox.information(
                self,
                APP_TITLE,
                "Já existe uma sincronização em andamento. "
                "Acompanhe o progresso nesta tela.",
            )
            self._navigate(self.pages["Sincronizações"])
            return
        self.sync_running = True
        self.sync_status.setText(f"Sincronizando {label}…")
        self._navigate(self.pages["Sincronizações"])
        worker = Worker(operation)
        worker.signals.finished.connect(
            lambda result: self._sync_finished(label, result)
        )
        worker.signals.error.connect(self._sync_error)
        self.pool.start(worker)

    def _sync_progress(self, message: str) -> None:
        self.sync_progress_signal.emit(message)

    def sync_log_append(self, message: str) -> None:
        self.sync_log.appendPlainText(message)

    def _sync_finished(self, label: str, result: Any) -> None:
        self.sync_running = False
        self.sync_status.setText(f"{label}: concluído")
        value = result.to_dict() if hasattr(result, "to_dict") else result
        self.sync_log.appendPlainText(json.dumps(value, ensure_ascii=False, indent=2))
        self.refresh_dashboard()
        self.refresh_reviews()

    def _sync_error(self, error: str) -> None:
        self.sync_running = False
        self.sync_status.setText("Falha na sincronização")
        self.sync_log.appendPlainText(error)
        self._show_error(error)

    def refresh_video_tree(self, *_args) -> None:
        if not hasattr(self, "video_tree"):
            return
        from ..courses import load_course_catalog
        from ..models import VideoItem
        from ..video_classification import load_module_overrides

        inventory_path = self.settings.root / "metadata" / "videos.json"
        course_path = self.settings.root / "metadata" / "courses.json"
        override_path = self.settings.root / "metadata" / "video_module_overrides.json"
        rows: list[VideoItem] = []
        if inventory_path.exists():
            try:
                raw = json.loads(inventory_path.read_text(encoding="utf-8"))
                rows = [VideoItem.from_dict(value) for value in raw if isinstance(value, dict)]
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                rows = []
        courses = load_course_catalog(course_path)
        overrides = load_module_overrides(override_path)
        source_filter = str(self.video_source_filter.currentData() or "")
        module_filter = str(self.video_module_filter.currentData() or "")
        status_filter = str(self.video_status_filter.currentData() or "")
        query = self.video_search.text().strip().casefold()

        def matches(
            *, source: str, module: str, status: str, text: str
        ) -> bool:
            if source_filter and source != source_filter:
                return False
            if module_filter and module != module_filter:
                return False
            effective_status = "review" if module == "Revisar" else status
            if status_filter and status_filter != effective_status:
                return False
            return not query or query in text.casefold()

        self.video_tree.clear()
        roots: dict[str, QTreeWidgetItem] = {}
        modules: dict[tuple[str, str], QTreeWidgetItem] = {}

        def source_node(source: str) -> QTreeWidgetItem:
            if source not in roots:
                label = "Cursos" if source == "curso" else "Biblioteca/Arquivos"
                roots[source] = QTreeWidgetItem(self.video_tree, [label, label, "", "", ""])
                roots[source].setExpanded(True)
            return roots[source]

        def module_node(source: str, module: str) -> QTreeWidgetItem:
            key = (source, module)
            if key not in modules:
                modules[key] = QTreeWidgetItem(
                    source_node(source), [module, "", module, "", ""]
                )
                modules[key].setExpanded(True)
            return modules[key]

        course_nodes: dict[tuple[str, str], QTreeWidgetItem] = {}
        hierarchy_nodes: dict[tuple[int, str], QTreeWidgetItem] = {}
        represented_courses: set[str] = set()
        for item in sorted(
            rows,
            key=lambda value: (
                value.area,
                value.business_module,
                value.course.casefold(),
                value.source_order,
                value.lesson_title.casefold(),
            ),
        ):
            text = " ".join(
                [item.course, item.module, *item.folder_path, item.lesson_title]
            )
            if not matches(
                source=item.area,
                module=item.business_module,
                status=item.status,
                text=text,
            ):
                continue
            parent = module_node(item.area, item.business_module)
            if item.area == "curso":
                represented_courses.add(item.source_course_id or item.course.casefold())
                course_key = (item.business_module, item.source_course_id or item.course.casefold())
                if course_key not in course_nodes:
                    course_node = QTreeWidgetItem(
                        parent,
                        [item.course or "Curso", "Cursos", item.business_module, "Inscrito", ""],
                    )
                    course_node.setData(
                        0,
                        Qt.UserRole,
                        {"kind": "group", "scope": "groups", "key": item.group_key()},
                    )
                    course_nodes[course_key] = course_node
                parent = course_nodes[course_key]
                hierarchy = item.folder_path[1:] if len(item.folder_path) > 1 else (
                    [item.module] if item.module else []
                )
            else:
                hierarchy = item.folder_path

            for part in hierarchy:
                node_key = (id(parent), part)
                if node_key not in hierarchy_nodes:
                    child = QTreeWidgetItem(
                        parent,
                        [part, "", item.business_module, "Pasta", ""],
                    )
                    if item.area == "biblioteca" and part == hierarchy[-1]:
                        child.setData(
                            0,
                            Qt.UserRole,
                            {"kind": "group", "scope": "groups", "key": item.group_key()},
                        )
                    hierarchy_nodes[node_key] = child
                parent = hierarchy_nodes[node_key]
            confidence = (
                f"{item.classification_confidence:.0%}"
                if item.classification_confidence
                else ""
            )
            video_node = QTreeWidgetItem(
                parent,
                [
                    item.lesson_title,
                    "Cursos" if item.area == "curso" else "Biblioteca",
                    item.business_module,
                    item.status,
                    confidence,
                ],
            )
            video_node.setToolTip(0, "\n".join(item.classification_reasons))
            video_node.setData(
                0,
                Qt.UserRole,
                {
                    "kind": "video",
                    "scope": "items",
                    "key": item.dedupe_key(),
                    "reasons": item.classification_reasons,
                },
            )

        for course in courses:
            represented_key = course.course_id or course.name.casefold()
            if course.status == "enrolled" and represented_key in represented_courses:
                continue
            group_key = f"course:{represented_key}"
            module = overrides["groups"].get(group_key, course.business_module)
            text = f"{course.name} {course.reason}"
            if not matches(
                source="curso",
                module=module,
                status=course.status,
                text=text,
            ):
                continue
            node = QTreeWidgetItem(
                module_node("curso", module),
                [
                    course.name,
                    "Cursos",
                    module,
                    course.reason or course.status,
                    f"{course.classification_confidence:.0%}"
                    if course.classification_confidence
                    else "",
                ],
            )
            data = {
                "kind": "catalog",
                "scope": "groups",
                "key": group_key,
                "course_id": course.course_id,
                "class_id": course.selected_class_id,
                "name": course.name,
                "selectable": course.selectable,
            }
            node.setData(0, Qt.UserRole, data)
            if course.selectable:
                node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
                node.setCheckState(0, Qt.Unchecked)

        self.video_tree.sortItems(0, Qt.AscendingOrder)
        self.video_status.setText(
            f"{len(rows)} vídeos · {len(courses)} cursos no catálogo"
        )

    def _video_selection_changed(self) -> None:
        selected = self.video_tree.selectedItems()
        if not selected:
            self.video_selection_detail.setText("")
            return
        data = selected[0].data(0, Qt.UserRole) or {}
        reasons = data.get("reasons") or []
        self.video_selection_detail.setText(
            f"{len(selected)} item(ns) selecionado(s)"
            + (f" · {'; '.join(reasons[:2])}" if reasons else "")
        )

    def apply_video_module_override(self) -> None:
        targets: set[tuple[str, str]] = set()
        for node in self.video_tree.selectedItems():
            data = node.data(0, Qt.UserRole) or {}
            if data.get("scope") in {"groups", "items"} and data.get("key"):
                targets.add((str(data["scope"]), str(data["key"])))
        if not targets:
            QMessageBox.information(
                self, APP_TITLE, "Selecione um curso, uma pasta final ou um vídeo."
            )
            return
        module = str(self.video_manual_module.currentData())
        answer = QMessageBox.question(
            self,
            "Classificação manual",
            f"Aplicar o módulo {module} a {len(targets)} seleção(ões)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        from ..inventory import load_inventory, save_inventory
        from ..settings import load_settings
        from ..video_classification import classify_inventory, save_module_override

        extractor_settings = load_settings(project_dir=self.settings.root)
        for scope, key in targets:
            save_module_override(
                extractor_settings.video_overrides_path,
                key=key,
                module=module,
                scope=scope,
            )
        items = load_inventory(extractor_settings.inventory_json_path)
        classify_inventory(items, extractor_settings.video_overrides_path)
        save_inventory(
            items,
            extractor_settings.inventory_json_path,
            extractor_settings.inventory_csv_path,
        )
        self.refresh_video_tree()
        self.refresh_dashboard()

    def enroll_selected_courses(self) -> None:
        selected: list[dict[str, Any]] = []

        def visit(node: QTreeWidgetItem) -> None:
            data = node.data(0, Qt.UserRole) or {}
            if (
                data.get("kind") == "catalog"
                and data.get("selectable")
                and node.checkState(0) == Qt.Checked
            ):
                selected.append(data)
            for index in range(node.childCount()):
                visit(node.child(index))

        for index in range(self.video_tree.topLevelItemCount()):
            visit(self.video_tree.topLevelItem(index))
        if not selected:
            QMessageBox.information(
                self, APP_TITLE, "Marque pelo menos um curso disponível."
            )
            return
        names = "\n".join(f"• {value['name']}" for value in selected[:12])
        if len(selected) > 12:
            names += f"\n• e mais {len(selected) - 12} curso(s)"
        answer = QMessageBox.question(
            self,
            "Confirmar inscrições",
            "Inscrever a conta Endoo nos cursos abaixo?\n\n" + names,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        selections = [
            f"{value['course_id']}:{value['class_id']}" for value in selected
        ]
        self.run_video_action(
            "enroll",
            [*selections, "--confirm", "--scan-after"],
        )

    def organize_video_downloads(self) -> None:
        answer = QMessageBox.question(
            self,
            "Organizar downloads",
            "Mover os vídeos já baixados para as pastas classificadas?\n"
            "Arquivos existentes no destino não serão sobrescritos.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        from ..downloader import organize_downloads
        from ..settings import load_settings

        result = organize_downloads(load_settings(project_dir=self.settings.root))
        QMessageBox.information(
            self,
            APP_TITLE,
            "Organização concluída: "
            f"{result['moved']} movidos, {result['collisions']} colisões, "
            f"{result['missing']} ausentes.",
        )
        self.refresh_video_tree()

    def run_video_action(self, action: str, extra_args: list[str] | None = None) -> None:
        if self.video_process and self.video_process.state() != QProcess.NotRunning:
            QMessageBox.information(self, APP_TITLE, "Já existe uma ação de vídeo em execução.")
            return
        self.video_process = QProcess(self)
        self.video_process.setProcessEnvironment(video_process_environment())
        self.video_process.setWorkingDirectory(str(self.settings.app_dir))
        self.video_process.setProcessChannelMode(QProcess.MergedChannels)
        self.video_process.readyReadStandardOutput.connect(self._read_video_output)
        self.video_process.finished.connect(self._video_process_finished)
        self._video_decoder = new_video_output_decoder()
        args = [
            "-m",
            "vrsoft_extractor",
            "--project-dir",
            str(self.settings.root),
            action,
            *(extra_args or []),
        ]
        self.video_status.setText(f"Executando {action}…")
        self.video_log.appendPlainText("$ python " + " ".join(args))
        self.video_process.start(sys.executable, args)

    def _read_video_output(self) -> None:
        if self.video_process:
            text = self._video_decoder.decode(
                bytes(self.video_process.readAllStandardOutput()), final=False
            )
            if text:
                self.video_log.appendPlainText(text.rstrip())

    def _video_process_finished(self, code: int, _status) -> None:
        tail = self._video_decoder.decode(b"", final=True)
        if tail:
            self.video_log.appendPlainText(tail.rstrip())
        self.video_status.setText(f"Concluído · código {code}")
        self.refresh_video_tree()
        self.refresh_dashboard()

    def stop_video_action(self) -> None:
        if self.video_process and self.video_process.state() != QProcess.NotRunning:
            self.video_process.terminate()

    def save_settings(self) -> None:
        env_path = self.settings.app_dir / ".env"
        values: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value
        for key, field in self.settings_fields.items():
            if isinstance(field, QComboBox):
                values[key] = str(field.currentData() or field.currentText())
            else:
                values[key] = field.text()
        env_path.write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
            encoding="utf-8",
        )
        QMessageBox.information(
            self,
            APP_TITLE,
            "Configurações salvas. Reinicie o aplicativo para aplicar mudanças de caminho.",
        )

    def install_ocr(self) -> None:
        answer = QMessageBox.question(
            self,
            "Instalar OCR local",
            "Baixar e instalar o Tesseract por+eng dentro da base VR_Mary_V2?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._navigate(self.pages["Sincronizações"])
        self.sync_status.setText("Instalando OCR portátil…")
        manager = OcrManager(self.settings.tesseract_dir)
        worker = Worker(manager.install_portable, self.sync_progress_signal.emit)
        worker.signals.finished.connect(
            lambda path: (
                self.sync_status.setText("OCR portátil pronto"),
                self.sync_log.appendPlainText(str(path)),
                self._refresh_all(),
            )
        )
        worker.signals.error.connect(self._sync_error)
        self.pool.start(worker)

    def _setup_auto_sync(self) -> None:
        if self.smoke_test:
            return
        self.auto_sync_timer = QTimer(self)
        self.auto_sync_timer.setInterval(self.settings.sync_interval_minutes * 60 * 1000)
        self.auto_sync_timer.timeout.connect(self.sync_all)
        self.auto_sync_timer.start()
        with self.database.connect() as connection:
            last = connection.execute(
                """SELECT finished_at FROM sync_runs WHERE status='completed'
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        should_run = not last
        if last and last["finished_at"]:
            try:
                timestamp = datetime.fromisoformat(last["finished_at"])
                should_run = datetime.now(timezone.utc) - timestamp >= timedelta(
                    minutes=self.settings.sync_interval_minutes
                )
            except ValueError:
                should_run = True
        if should_run and os.environ.get("MARY_DISABLE_STARTUP_SYNC") != "1":
            QTimer.singleShot(2500, self.sync_all)

    def _append_log(self, message: str) -> None:
        redacted = message
        for key in ("MOVIDESK_PASSWORD", "ENDOO_PASSWORD"):
            secret = os.environ.get(key, "")
            if secret:
                redacted = redacted.replace(secret, "***")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.app_log.appendPlainText(f"[{timestamp}] {redacted}")

    def _show_error(self, error: str) -> None:
        self._append_log("ERRO: " + error)
        QMessageBox.critical(self, APP_TITLE, error)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.orchestrator.close()
        if self.video_process and self.video_process.state() != QProcess.NotRunning:
            self.video_process.terminate()
        event.accept()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--mary-root", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot", default="")
    parser.add_argument("--screenshot-page", default="Dashboard")
    parser.add_argument("--screenshot-width", type=int, default=1480)
    parser.add_argument("--screenshot-height", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args, _unknown = build_parser().parse_known_args(argv or sys.argv[1:])
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName(ORGANIZATION_NAME)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    apply_application_theme(app)
    app_dir = args.project_dir or (
        str(Path(sys.executable).resolve().parent) if getattr(sys, "frozen", False) else "."
    )
    settings = load_mary_settings(app_dir, args.mary_root)
    window = MainWindow(
        settings,
        smoke_test=args.smoke_test or bool(args.screenshot),
        auto_close_smoke=not bool(args.screenshot),
    )
    if args.screenshot:
        window.resize(
            max(window.minimumWidth(), args.screenshot_width),
            max(window.minimumHeight(), args.screenshot_height),
        )
    window.show()
    if args.screenshot:
        app.processEvents()
    if args.screenshot_page in window.pages:
        window._navigate(window.pages[args.screenshot_page])
    if args.screenshot:
        def save_capture() -> None:
            target = Path(args.screenshot).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            window.repaint()
            app.processEvents()
            window.grab().save(str(target), "PNG")
            app.quit()

        def capture() -> None:
            window.stack.setFocus()
            window.nav_frame.hide()
            app.processEvents()
            window.nav_frame.show()
            window.repaint()
            app.processEvents()
            QTimer.singleShot(150, save_capture)

        QTimer.singleShot(600, capture)
    return app.exec()


def apply_application_theme(app: QApplication) -> None:
    """Apply a deterministic light palette, including modal system dialogs."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BACKGROUND))
    palette.setColor(QPalette.WindowText, QColor(BRAND_NAVY))
    palette.setColor(QPalette.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.AlternateBase, QColor("#FAFAFC"))
    palette.setColor(QPalette.ToolTipBase, QColor(BRAND_NAVY))
    palette.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Text, QColor(BRAND_NAVY))
    palette.setColor(QPalette.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ButtonText, QColor(BRAND_NAVY))
    palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Highlight, QColor(ACCESSIBLE_ORANGE))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.Link, QColor(FOCUS_DARK))
    palette.setColor(QPalette.LinkVisited, QColor(LINK_VISITED))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(DISABLED_TEXT),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(DISABLED_TEXT),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(DISABLED_TEXT),
    )
    app.setPalette(palette)
    font_family = _load_application_font()
    app.setStyleSheet(STYLESHEET.replace("__APP_FONT__", font_family))


def _load_application_font() -> str:
    candidates = [
        Path(__file__).resolve().parent / "assets" / "Montserrat-Regular.ttf",
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(candidate))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                return families[0]
    return "Sans Serif"


if __name__ == "__main__":
    raise SystemExit(main())

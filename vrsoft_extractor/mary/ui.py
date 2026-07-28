from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QProcess, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
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
    QVBoxLayout,
    QWidget,
)

from .config import MarySettings, load_mary_settings
from .migration import migrate
from .models import RuntimeEvent
from .movidesk import MovideskSync
from .ocr import OcrManager
from .orchestrator import ChatOrchestrator
from .wiki import WikiSync
from .workspace import initialize_workspace


APP_TITLE = "VR Mary Studio"
BRAND_ORANGE = "#FF7200"
ACCESSIBLE_ORANGE = "#C45100"
BRAND_YELLOW = "#FCBD0F"
BRAND_NAVY = "#02021E"
TEXT_MUTED = "#4E4E62"
BACKGROUND = "#F3F3F3"


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
QPushButton#primary {{ background: {ACCESSIBLE_ORANGE}; color: white; border: 0; }}
QPushButton#primary:hover {{ background: #A84300; }}
QPushButton#danger {{ color: #A1261D; border-color: #E3B8B4; }}
QPushButton:disabled {{
    color: #777787; background: #ECECF1; border-color: #DADAE2;
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
QLabel#pageTitle {{ font-size: 24px; font-weight: 700; }}
QLabel#sectionTitle {{ font-size: 16px; font-weight: 700; }}
QLabel#muted {{ color: {TEXT_MUTED}; }}
QLabel#statusGood {{ color: #176B3A; font-weight: 700; }}
QLabel#statusWarn {{ color: #8A5500; font-weight: 700; }}
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

    def __init__(self, settings: MarySettings, smoke_test: bool = False):
        super().__init__()
        self.smoke_test = smoke_test
        self.settings = settings
        self.database = initialize_workspace(settings)
        self.orchestrator = ChatOrchestrator(settings, self.database)
        self.pool = QThreadPool.globalInstance()
        self.current_conversation = ""
        self.assistant_widget: QTextBrowser | None = None
        self.assistant_markdown = ""
        self.video_process: QProcess | None = None
        self.model_metadata: dict[str, dict[str, Any]] = {}
        self.pending_model = ""
        self.pending_effort = ""
        self.nav_buttons: list[QToolButton] = []
        self.pages: dict[str, int] = {}
        self.setWindowTitle(APP_TITLE)
        self.resize(1480, 900)
        self.setMinimumSize(1120, 700)
        self.runtime_event_signal.connect(self._on_runtime_event)
        self.sync_progress_signal.connect(self.sync_log_append)
        self._build_ui()
        self._refresh_all()
        self._setup_auto_sync()
        if smoke_test:
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
        frame.setFixedWidth(178)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 18, 12, 14)
        brand = QLabel("VR Mary", objectName="brandTitle")
        subtitle = QLabel("STUDIO", objectName="brandSub")
        layout.addWidget(brand)
        layout.addWidget(subtitle)
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
        self.conversation_list = QListWidget()
        self.conversation_list.currentItemChanged.connect(self.load_conversation)
        left.addWidget(self.conversation_list, 1)
        splitter.addWidget(conversations)

        center = QWidget(objectName="chatCenter")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 14, 16, 14)
        header = QHBoxLayout()
        self.chat_title = QLabel("Nova conversa", objectName="sectionTitle")
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["codex", "claude"])
        self.provider_combo.currentTextChanged.connect(self.load_models)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(150)
        self.model_combo.currentIndexChanged.connect(self.load_efforts)
        self.effort_combo = QComboBox()
        self.effort_combo.setMinimumWidth(96)
        self.effort_combo.setToolTip(
            "Controla quanto raciocínio o agente usa nesta conversa."
        )
        self.effort_combo.currentTextChanged.connect(self._chat_option_changed)
        clone_button = QPushButton("Clonar para outro provedor")
        clone_button.clicked.connect(self.clone_conversation)
        header.addWidget(self.chat_title)
        header.addStretch()
        header.addWidget(self.provider_combo)
        header.addWidget(self.model_combo)
        header.addWidget(QLabel("Esforço:"))
        header.addWidget(self.effort_combo)
        header.addWidget(clone_button)
        center_layout.addLayout(header)
        self.message_scroll = QScrollArea(objectName="messageScroll")
        self.message_scroll.setWidgetResizable(True)
        self.message_container = QWidget(objectName="messageContainer")
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setAlignment(Qt.AlignTop)
        self.message_layout.addStretch()
        self.message_scroll.setWidget(self.message_container)
        center_layout.addWidget(self.message_scroll, 1)
        composer_card = QFrame(objectName="card")
        composer_layout = QVBoxLayout(composer_card)
        self.composer = QPlainTextEdit()
        self.composer.setPlaceholderText(
            "Digite Mary: para ativar o fluxo e pesquisar a base local…"
        )
        self.composer.setMaximumHeight(130)
        composer_layout.addWidget(self.composer)
        actions = QHBoxLayout()
        self.chat_status = QLabel("Pronto", objectName="muted")
        stop_button = QPushButton("Parar", objectName="danger")
        stop_button.clicked.connect(self.stop_turn)
        send_button = QPushButton("Enviar", objectName="primary")
        send_button.clicked.connect(self.send_message)
        actions.addWidget(self.chat_status)
        actions.addStretch()
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
        splitter = QSplitter(Qt.Horizontal)
        self.knowledge_table = QTableWidget(0, 4)
        self.knowledge_table.setHorizontalHeaderLabels(["Título", "Módulo", "Fonte", "Status"])
        self.knowledge_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.knowledge_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.knowledge_table.itemSelectionChanged.connect(self.preview_knowledge)
        self.knowledge_preview = QTextBrowser()
        self.knowledge_preview.setOpenExternalLinks(True)
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
        layout.addWidget(self.sync_log, 1)
        return page

    def _build_review(self) -> QWidget:
        page, layout = self._page(
            "Revisão",
            "Conteúdo de confiança intermediária/baixa e mudanças de módulo.",
        )
        self.review_table = QTableWidget(0, 5)
        self.review_table.setHorizontalHeaderLabels(
            ["Título", "Fonte", "Sugestão", "Confiança", "Motivos"]
        )
        self.review_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.review_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.review_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.review_table, 1)
        actions = QHBoxLayout()
        self.review_module = QComboBox()
        self.review_module.addItems(
            ["Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar"]
        )
        approve = QPushButton("Aprovar classificação", objectName="primary")
        approve.clicked.connect(self.approve_review)
        actions.addWidget(QLabel("Destino:"))
        actions.addWidget(self.review_module)
        actions.addWidget(approve)
        actions.addStretch()
        layout.addLayout(actions)
        self.review_rows: list[Any] = []
        return page

    def _build_videos(self) -> QWidget:
        page, layout = self._page(
            "Vídeos",
            "O extrator existente foi incorporado; não há transcrição nesta versão.",
        )
        actions = QHBoxLayout()
        for label, action in [
            ("Login", "login"),
            ("Inventariar", "scan"),
            ("Baixar", "download"),
            ("Executar tudo", "run"),
        ]:
            button = QPushButton(label, objectName="primary" if action == "run" else "")
            button.clicked.connect(lambda _checked=False, value=action: self.run_video_action(value))
            actions.addWidget(button)
        stop = QPushButton("Parar", objectName="danger")
        stop.clicked.connect(self.stop_video_action)
        actions.addWidget(stop)
        actions.addStretch()
        layout.addLayout(actions)
        self.video_status = QLabel("Pronto", objectName="muted")
        layout.addWidget(self.video_status)
        self.video_log = QPlainTextEdit()
        self.video_log.setReadOnly(True)
        layout.addWidget(self.video_log, 1)
        return page

    def _build_settings(self) -> QWidget:
        page, layout = self._page(
            "Configurações",
            "Credenciais permanecem apenas no .env local e são mascaradas nos logs.",
        )
        form = QFrame(objectName="card")
        grid = QGridLayout(form)
        self.settings_fields: dict[str, QLineEdit] = {}
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
            edit = QLineEdit(value)
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
        layout.addWidget(self.app_log, 1)
        return page

    def _refresh_all(self) -> None:
        self.refresh_dashboard()
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
                detail += f"\n{str(run['error'])[:180]}"
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

    def refresh_conversations(self, *_args: Any) -> None:
        selected = self.current_conversation
        term = self.conversation_search.text().lower() if hasattr(self, "conversation_search") else ""
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        for row in self.database.list_conversations():
            if term and term not in row["title"].lower():
                continue
            item = QListWidgetItem(
                f"{row['title']}\n{row['provider'].title()} · "
                f"{row['model'] or 'padrão'} · esforço {row['effort']} · {row['status']}"
            )
            item.setData(Qt.UserRole, row["id"])
            self.conversation_list.addItem(item)
            if row["id"] == selected:
                self.conversation_list.setCurrentItem(item)
        self.conversation_list.blockSignals(False)

    def new_conversation(self) -> None:
        provider = self.provider_combo.currentText() or "codex"
        model = self.model_combo.currentData() or self.model_combo.currentText()
        effort = self.effort_combo.currentData() or self.effort_combo.currentText()
        self.chat_status.setText("Criando conversa…")

        worker = Worker(
            self.orchestrator.new_conversation,
            provider,
            model,
            effort or self.settings.default_effort,
        )
        worker.signals.finished.connect(self._conversation_created)
        worker.signals.error.connect(self._show_error)
        self.pool.start(worker)

    def _conversation_created(self, conversation_id: str) -> None:
        self.current_conversation = conversation_id
        self.refresh_conversations()
        for index in range(self.conversation_list.count()):
            item = self.conversation_list.item(index)
            if item.data(Qt.UserRole) == conversation_id:
                self.conversation_list.setCurrentItem(item)
                break
        self.chat_status.setText("Pronto")

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
        self.chat_title.setText(row["title"])
        self.pending_model = str(row["model"])
        self.pending_effort = str(row["effort"] or self.settings.default_effort)
        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentText(row["provider"])
        self.provider_combo.setEnabled(False)
        self.provider_combo.blockSignals(False)
        self.load_models()
        self._clear_messages()
        for message in self.database.messages(conversation_id):
            if message["role"] != "system":
                self._add_message(message["role"], message["content"])
        self.chat_status.setText(row["status"])

    def _clear_messages(self) -> None:
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.assistant_widget = None
        self.assistant_markdown = ""

    def _add_message(self, role: str, content: str) -> QTextBrowser:
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
        layout.addWidget(role_label)
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
            QMessageBox.information(self, APP_TITLE, "Crie uma conversa antes de enviar.")
            return
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
        answer = QMessageBox.question(
            self,
            "Aprovação solicitada",
            event.text or "O agente solicitou uma ação.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        request_id = str(event.payload.get("request_id", ""))
        try:
            self.orchestrator.approve(
                event.conversation_id, request_id, answer == QMessageBox.Yes
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

    def load_models(self, *_args: Any) -> None:
        provider = self.provider_combo.currentText() or "codex"
        current_model = self.pending_model or self.model_combo.currentData() or ""
        self.model_combo.clear()
        self.model_combo.addItem("Carregando…", "")

        def loaded(models: list[dict[str, Any]]) -> None:
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
        self._chat_option_changed()

    def _chat_option_changed(self, *_args: Any) -> None:
        if not self.current_conversation:
            return
        model = self.model_combo.currentData() or self.model_combo.currentText()
        effort = self.effort_combo.currentData() or self.effort_combo.currentText()
        if effort:
            self.database.update_conversation(
                self.current_conversation,
                model=str(model or ""),
                effort=str(effort),
            )
            self.refresh_conversations()

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
                result["review_status"],
            ]
            for column, value in enumerate(values):
                self.knowledge_table.setItem(row_index, column, QTableWidgetItem(str(value)))

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

    def refresh_reviews(self) -> None:
        self.review_rows = self.database.list_reviews()
        self.review_table.setRowCount(len(self.review_rows))
        for row_index, row in enumerate(self.review_rows):
            reasons = ", ".join(json.loads(row["reasons_json"] or "[]"))
            values = [
                row["title"],
                row["source"].upper(),
                row["suggested_module"],
                f"{row['confidence']:.0%}",
                reasons,
            ]
            for column, value in enumerate(values):
                self.review_table.setItem(row_index, column, QTableWidgetItem(str(value)))

    def approve_review(self) -> None:
        row_index = self.review_table.currentRow()
        if row_index < 0:
            return
        review = self.review_rows[row_index]
        self.database.decide_review(review["id"], self.review_module.currentText())
        self.refresh_reviews()
        self.refresh_dashboard()

    def sync_wiki(self) -> None:
        self._run_sync(
            "Wiki",
            lambda: WikiSync(self.settings, self.database, self._sync_progress).sync(),
        )

    def sync_kb(self, headed: bool = False) -> None:
        self._run_sync(
            "KB",
            lambda: MovideskSync(self.settings, self.database, self._sync_progress).sync(
                headed=headed
            ),
        )

    def sync_all(self) -> None:
        def operation():
            wiki = WikiSync(self.settings, self.database, self._sync_progress).sync()
            kb = MovideskSync(self.settings, self.database, self._sync_progress).sync()
            return {"wiki": wiki.to_dict(), "kb": kb.to_dict()}

        self._run_sync("Wiki + KB", operation)

    def _run_sync(self, label: str, operation: Callable[[], Any]) -> None:
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
        self.sync_status.setText(f"{label}: concluído")
        value = result.to_dict() if hasattr(result, "to_dict") else result
        self.sync_log.appendPlainText(json.dumps(value, ensure_ascii=False, indent=2))
        self.refresh_dashboard()
        self.refresh_reviews()

    def _sync_error(self, error: str) -> None:
        self.sync_status.setText("Falha na sincronização")
        self.sync_log.appendPlainText(error)
        self._show_error(error)

    def run_video_action(self, action: str) -> None:
        if self.video_process and self.video_process.state() != QProcess.NotRunning:
            QMessageBox.information(self, APP_TITLE, "Já existe uma ação de vídeo em execução.")
            return
        self.video_process = QProcess(self)
        self.video_process.setWorkingDirectory(str(self.settings.app_dir))
        self.video_process.setProcessChannelMode(QProcess.MergedChannels)
        self.video_process.readyReadStandardOutput.connect(self._read_video_output)
        self.video_process.finished.connect(
            lambda code, _status: self.video_status.setText(f"Concluído · código {code}")
        )
        args = [
            "-m",
            "vrsoft_extractor",
            "--project-dir",
            str(self.settings.root),
            action,
        ]
        self.video_status.setText(f"Executando {action}…")
        self.video_log.appendPlainText("$ python " + " ".join(args))
        self.video_process.start(sys.executable, args)

    def _read_video_output(self) -> None:
        if self.video_process:
            text = bytes(self.video_process.readAllStandardOutput()).decode("utf-8", "replace")
            self.video_log.appendPlainText(text.rstrip())

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args, _unknown = build_parser().parse_known_args(argv or sys.argv[1:])
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("VR Soft")
    app.setStyle("Fusion")
    font_family = _load_application_font()
    app.setStyleSheet(STYLESHEET.replace("__APP_FONT__", font_family))
    app_dir = args.project_dir or (
        str(Path(sys.executable).resolve().parent) if getattr(sys, "frozen", False) else "."
    )
    settings = load_mary_settings(app_dir, args.mary_root)
    window = MainWindow(settings, smoke_test=args.smoke_test or bool(args.screenshot))
    if args.screenshot_page in window.pages:
        window._navigate(window.pages[args.screenshot_page])
    window.show()
    if args.screenshot:
        def capture() -> None:
            target = Path(args.screenshot).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(target), "PNG")
            app.quit()
        QTimer.singleShot(600, capture)
    return app.exec()


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

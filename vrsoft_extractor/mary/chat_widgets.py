from __future__ import annotations

import json
import re
from typing import Any

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeySequence,
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
    QVBoxLayout,
    QWidget,
)

from .chat_tools import ToolValidationError, validate_tool_definition
from .db import MaryDatabase
from .spellcheck import LocalSpellChecker


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
    def __init__(self, checker: LocalSpellChecker, parent: QWidget | None = None):
        super().__init__(parent)
        self.checker = checker
        self.highlighter = SpellHighlighter(self.document(), checker)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt API
        menu = self.createStandardContextMenu()
        cursor = self.cursorForPosition(event.pos())
        cursor.select(QTextCursor.WordUnderCursor)
        word = cursor.selectedText()
        issue = next(
            (item for item in self.checker.misspellings(word) if item.word == word), None
        )
        if issue:
            menu.insertSeparator(menu.actions()[0] if menu.actions() else None)
            for suggestion in issue.suggestions[:5]:
                action = menu.addAction(f"Substituir por “{suggestion}”")
                action.triggered.connect(
                    lambda _checked=False, value=suggestion, target=QTextCursor(cursor): (
                        target.insertText(value)
                    )
                )
            add_action = menu.addAction(f"Adicionar “{word}” ao dicionário Mary")
            add_action.triggered.connect(lambda: self._add_word(word))
        menu.exec(event.globalPos())

    def _add_word(self, word: str) -> None:
        self.checker.add_word(word)
        self.highlighter.rehighlight()


class SpellReviewDialog(QDialog):
    def __init__(self, checker: LocalSpellChecker, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correção ortográfica local")
        self.resize(760, 520)
        corrected, replacements = checker.correct_text(text)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Revise as sugestões. Código, URLs, caminhos e identificadores técnicos são ignorados."
            )
        )
        columns = QHBoxLayout()
        original_box = QPlainTextEdit(text)
        original_box.setReadOnly(True)
        self.corrected_box = QPlainTextEdit(corrected)
        left = QVBoxLayout()
        left.addWidget(QLabel("Original"))
        left.addWidget(original_box)
        right = QVBoxLayout()
        right.addWidget(QLabel("Corrigido"))
        right.addWidget(self.corrected_box)
        columns.addLayout(left)
        columns.addLayout(right)
        layout.addLayout(columns)
        layout.addWidget(QLabel(f"{len(replacements)} sugestão(ões) encontrada(s)."))
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).setText("Aplicar correções")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def corrected_text(self) -> str:
        return self.corrected_box.toPlainText()


class ModelPickerCombo(QComboBox):
    providerModelSelected = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalogs: dict[str, list[dict[str, Any]]] = {}
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

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        dialog = QDialog(self)
        dialog.setWindowTitle("Selecionar modelo")
        dialog.resize(520, 560)
        layout = QVBoxLayout(dialog)
        filters = QHBoxLayout()
        provider = QTabBar()
        provider.setDocumentMode(True)
        all_index = provider.addTab("★ Todos")
        provider.setTabData(all_index, "")
        for name in ("codex", "claude"):
            if name in self._catalogs:
                index = provider.addTab("◉ Codex" if name == "codex" else "◆ Claude")
                provider.setTabData(index, name)
        search = QLineEdit()
        search.setPlaceholderText("Pesquisar modelos…")
        filters.addWidget(provider)
        filters.addWidget(search, 1)
        layout.addLayout(filters)
        model_list = QListWidget()
        layout.addWidget(model_list, 1)
        favorite = QPushButton("☆ Favoritar")
        layout.addWidget(favorite)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
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
                item.setData(Qt.UserRole, (provider_name, model_id))
                model_list.addItem(item)

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

        search.textChanged.connect(refresh)
        provider.currentChanged.connect(refresh)
        model_list.itemDoubleClicked.connect(lambda _item: choose())
        favorite.clicked.connect(toggle_favorite)
        refresh()
        dialog.exec()


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

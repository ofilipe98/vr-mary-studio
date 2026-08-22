from __future__ import annotations

import json
import io
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.knowledge import extract_knowledge_entities
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.schema_catalog import parse_schema_markdown
from vrsoft_extractor.mary.schema_sync import SchemaSync
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    KnowledgeDocument,
    ModelRef,
    OrchestrationOptions,
    RuntimeEvent,
)
from vrsoft_extractor.mary.multiagent import (
    AGENT_CATALOG,
    VrAgentAssignment,
    VrPlan,
    build_agent_prompt,
    build_consistency_prompt,
    build_planner_prompt,
    build_synthesis_prompt,
    effective_orchestration_mode,
    ensure_source_research_plan,
    execution_batches,
    parse_plan,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.providers import (
    AgentProvider,
    ClaudeProvider,
    CodexProvider,
    OpenCodeProvider,
    ProviderError,
    _claude_token_usage,
    _opencode_environment,
    _opencode_token_usage,
    _parse_opencode_models,
)


def test_provider_usage_payloads_share_one_context_shape() -> None:
    claude = _claude_token_usage(
        {
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 40,
                "cache_creation_input_tokens": 10,
                "output_tokens": 25,
            },
            "modelUsage": {"sonnet": {"contextWindow": 200_000}},
        }
    )
    opencode = _opencode_token_usage(
        {
            "type": "step_finish",
            "part": {
                "tokens": {
                    "input": 80,
                    "output": 20,
                    "reasoning": 5,
                    "cache": {"read": 30, "write": 4},
                },
                "contextWindow": 128_000,
            },
        }
    )

    assert claude is not None
    assert claude["tokenUsage"]["last"]["totalTokens"] == 175
    assert claude["tokenUsage"]["modelContextWindow"] == 200_000
    assert opencode is not None
    assert opencode["tokenUsage"]["last"]["totalTokens"] == 105
    assert opencode["tokenUsage"]["modelContextWindow"] == 128_000


def _settings(
    tmp_path: Path, *, legacy_vr_orchestration: bool = True
) -> MarySettings:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "mary").resolve(),
        old_root=(tmp_path / "old").resolve(),
        legacy_vr_orchestration=legacy_vr_orchestration,
    )
    settings.app_dir.mkdir(parents=True)
    settings.old_root.mkdir(parents=True)
    settings.ensure_dirs()
    return settings


class FakeProvider(AgentProvider):
    def __init__(
        self,
        name: str,
        *,
        final_text: str = "RESPOSTA FINAL",
        divergent: bool = False,
        difficulty_level: int = 3,
    ):
        self.name = name
        self.final_text = final_text
        self.divergent = divergent
        self.difficulty_level = difficulty_level
        self.starts: list[str] = []
        self.start_options: list[ConversationOptions | None] = []
        self.sent: list[dict[str, Any]] = []
        self.interrupted: list[str] = []
        self.released: list[tuple[str, str, bool]] = []
        self._lock = threading.Lock()

    def available(self) -> bool:
        return True

    def list_models(self) -> list[dict[str, Any]]:
        return []

    def start_conversation(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        with self._lock:
            self.starts.append(conversation_id)
            self.start_options.append(options)
        return f"native:{conversation_id}"

    def resume_conversation(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        options: ConversationOptions | None = None,
    ) -> str:
        return native_id

    def send_message(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        message: str,
        callback: Callable[[RuntimeEvent], None],
        options: ConversationOptions | None = None,
        skills: list[dict[str, Any]] | None = None,
        image_paths: list[str] | None = None,
    ) -> None:
        with self._lock:
            self.sent.append(
                {
                    "conversation_id": conversation_id,
                    "native_id": native_id,
                    "model": model,
                    "effort": effort,
                    "message": message,
                    "options": options,
                }
            )
        callback(
            RuntimeEvent(
                conversation_id,
                "turn_started",
                payload={"turn": {"id": f"turn:{conversation_id}"}},
            )
        )
        if ":vr_orchestrator_plan:" in conversation_id:
            output = json.dumps(
                {
                    "difficulty": {
                        "level": self.difficulty_level,
                        "summary": "Análise em etapas.",
                    },
                    "strategy": "adaptive",
                    "agents": [
                        {
                            "id": "planner",
                            "agent": "vr_planner",
                            "model": "codex:sol",
                            "effort": "medium",
                            "task": "Planejar.",
                        },
                        {
                            "id": "reasoner_a",
                            "agent": "vr_reasoner_a",
                            "model": "codex:sol",
                            "effort": "high",
                            "task": "Analisar A.",
                            "depends_on": ["planner"],
                        },
                        {
                            "id": "reasoner_b",
                            "agent": "vr_reasoner_b",
                            "model": "claude:opus",
                            "effort": "xhigh",
                            "task": "Analisar B.",
                            "depends_on": ["planner"],
                        },
                        {
                            "id": "critic",
                            "agent": "vr_critic",
                            "model": "codex:sol",
                            "effort": "high",
                            "task": "Criticar.",
                            "depends_on": ["reasoner_a", "reasoner_b"],
                        },
                        {
                            "id": "final",
                            "agent": "vr_synthesizer",
                            "model": "codex:sol",
                            "effort": "max",
                            "task": "Sintetizar.",
                            "depends_on": ["critic"],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        elif ":vr_orchestrator_validation:" in conversation_id and self.divergent:
            output = json.dumps(
                {
                    "divergence": True,
                    "confidence": 0.75,
                    "summary": "As respostas divergem.",
                    "revision_task": "Resolver a divergência principal.",
                },
                ensure_ascii=False,
            )
        elif ":vr:" in conversation_id:
            output = f"resultado intermediário de {conversation_id}"
        else:
            output = self.final_text
        callback(RuntimeEvent(conversation_id, "assistant_delta", output))
        callback(
            RuntimeEvent(
                conversation_id,
                "turn_completed",
                payload={"turn": {"id": f"turn:{conversation_id}"}},
            )
        )

    def interrupt(self, conversation_id: str) -> None:
        with self._lock:
            self.interrupted.append(conversation_id)

    def approve_action(
        self,
        request_id: str,
        approved: bool,
        session: bool = False,
        request: dict[str, Any] | None = None,
    ) -> None:
        return None

    def release_conversation(
        self, conversation_id: str, native_id: str, *, delete_native: bool = False
    ) -> None:
        with self._lock:
            self.released.append((conversation_id, native_id, delete_native))

    def close(self) -> None:
        return None


class BlockingPlannerProvider(FakeProvider):
    def __init__(self):
        super().__init__("codex")
        self.planner_started = threading.Event()
        self._pending_callbacks: dict[str, Callable[[RuntimeEvent], None]] = {}

    def send_message(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        message: str,
        callback: Callable[[RuntimeEvent], None],
        options: ConversationOptions | None = None,
        skills: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            self.sent.append(
                {
                    "conversation_id": conversation_id,
                    "native_id": native_id,
                    "model": model,
                    "message": message,
                }
            )
            self._pending_callbacks[conversation_id] = callback
        if ":vr_orchestrator_plan:" in conversation_id:
            self.planner_started.set()
            return
        super().send_message(
            conversation_id,
            native_id,
            model,
            effort,
            workspace,
            message,
            callback,
            options,
            skills,
        )

    def interrupt(self, conversation_id: str) -> None:
        super().interrupt(conversation_id)
        with self._lock:
            callback = self._pending_callbacks.pop(conversation_id, None)
        if callback:
            callback(RuntimeEvent(conversation_id, "turn_completed"))


class FinalErrorProvider(FakeProvider):
    def send_message(
        self,
        conversation_id: str,
        native_id: str,
        model: str,
        effort: str,
        workspace: Path,
        message: str,
        callback: Callable[[RuntimeEvent], None],
        options: ConversationOptions | None = None,
        skills: list[dict[str, Any]] | None = None,
    ) -> None:
        if ":vr:" not in conversation_id:
            callback(RuntimeEvent(conversation_id, "error", "falha final"))
            callback(RuntimeEvent(conversation_id, "turn_completed"))
            return
        super().send_message(
            conversation_id,
            native_id,
            model,
            effort,
            workspace,
            message,
            callback,
            options,
            skills,
        )


def test_model_ref_uses_provider_qualified_key_and_round_trips() -> None:
    model = ModelRef.from_mapping(
        {
            "provider": " Claude ",
            "model_id": " opus ",
            "displayName": "Opus",
            "capabilities": "reasoning",
        }
    )

    assert model == ModelRef("claude", "opus", "Opus", "", ("reasoning",))
    assert model.key == "claude:opus"
    assert ModelRef("codex", "").key == "codex:__default__"
    assert ModelRef.from_mapping(model.to_dict()) == model


def test_orchestration_modes_normalize_legacy_flags_and_route_automatic_levels() -> None:
    assert OrchestrationOptions(enabled=False).mode == "off"
    assert OrchestrationOptions(enabled=True).mode == "automatic"
    assert OrchestrationOptions(ultra=True).mode == "ultra"
    standard = OrchestrationOptions(mode="standard")
    assert standard.enabled is True
    assert standard.ultra is False

    automatic = OrchestrationOptions(mode="automatic")
    assert [
        effective_orchestration_mode(automatic, level) for level in range(1, 6)
    ] == ["off", "standard", "standard", "ultra", "ultra"]
    assert effective_orchestration_mode(standard, 5) == "standard"
    assert effective_orchestration_mode(OrchestrationOptions(mode="ultra"), 1) == "ultra"


def test_orchestration_dialog_keeps_agent_pool_separate_from_orchestrator() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from vrsoft_extractor.mary.chat_widgets import OrchestrationSettingsDialog

    application = QApplication.instance() or QApplication([])
    sol = ModelRef("codex", "sol", "Sol")
    opus = ModelRef("claude", "opus", "Opus")
    current = OrchestrationOptions(
        mode="ultra",
        strategy="adaptive",
        model_pool=(opus,),
        explain_routing=True,
        dynamic_model_routing=False,
        dynamic_agent_count=False,
        difficulty_routing=False,
    )
    dialog = OrchestrationSettingsDialog((sol, opus), current, sol)
    try:
        application.processEvents()
        checked_keys = {
            str(dialog.pool_list.item(index).data(Qt.UserRole))
            for index in range(dialog.pool_list.count())
            if dialog.pool_list.item(index).checkState() == Qt.Checked
        }
        assert checked_keys == {"claude:opus"}
        assert dialog.orchestrator_model() == sol
        edited = dialog.options()
        assert edited.model_pool == (opus,)
        assert edited.mode == "ultra"
        assert edited.ultra is True
        assert edited.dynamic_model_routing is False
        assert edited.dynamic_agent_count is False
        assert edited.difficulty_routing is False
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        assert buttons.button(QDialogButtonBox.Ok).text() == "Aplicar"
        assert buttons.button(QDialogButtonBox.Cancel).text() == "Cancelar"
    finally:
        dialog.close()


def test_standard_and_ultra_share_the_compact_composer_outline() -> None:
    from PySide6.QtCore import QAbstractAnimation
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from vrsoft_extractor.mary.chat_widgets import VrComposerGlowFrame

    application = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    frame = VrComposerGlowFrame(host)
    frame_layout = QVBoxLayout(frame)
    frame_layout.addWidget(QLabel("Chat"))
    layout.addWidget(frame)
    host.show()
    try:
        frame.set_mode("standard")
        application.processEvents()
        assert frame.mode() == "standard"
        assert frame._phase_animation.loopCount() == 1
        assert frame._phase_animation.state() == QAbstractAnimation.Running

        frame.set_mode("ultra")
        application.processEvents()
        assert frame.mode() == "ultra"
        # Accessibility contract: Ultra may animate its state change once,
        # but it must never keep repainting indefinitely.
        assert frame._phase_animation.loopCount() == 1
        assert frame._phase_animation.state() == QAbstractAnimation.Running

        frame.set_reduced_motion(True)
        frame.set_mode("standard")
        application.processEvents()
        assert frame._phase_animation.state() == QAbstractAnimation.Stopped
        assert frame.phase == pytest.approx(0.14)

        frame.set_mode("off")
        application.processEvents()
        assert frame._phase_animation.state() == QAbstractAnimation.Stopped
        assert frame.mode() == "off"
    finally:
        host.close()


def test_codex_provider_emits_reconnection_lifecycle_before_resuming_turn(
    tmp_path: Path,
) -> None:
    provider = CodexProvider(tmp_path)
    provider._has_started_once = True
    provider.process = None
    provider._native_to_local["native-thread"] = "conversation"
    events: list[RuntimeEvent] = []

    with (
        patch.object(provider, "_ensure_started"),
        patch.object(provider, "_rpc", return_value={}),
    ):
        provider.send_message(
            "conversation",
            "native-thread",
            "gpt-test",
            "medium",
            tmp_path,
            "Continue",
            events.append,
            ConversationOptions(model="gpt-test", effort="medium"),
        )

    assert [event.kind for event in events] == [
        "provider_reconnecting",
        "provider_reconnected",
    ]
    assert all(event.payload["provider"] == "codex" for event in events)


def test_vr_panel_explains_four_modes_and_local_base_keeps_its_own_state(
    tmp_path: Path,
) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from vrsoft_extractor.mary.ui import MainWindow

    application = QApplication.instance() or QApplication([])
    window = MainWindow(_settings(tmp_path), smoke_test=True, auto_close_smoke=False)
    try:
        window.show()
        application.processEvents()
        assert set(window.orchestration_mode_actions) == {
            "off",
            "automatic",
            "standard",
            "ultra",
        }
        assert window.vr_flow_button.menu() is window.vr_menu
        assert set(window.vr_mode_panel._mode_rows) == {
            "off",
            "automatic",
            "standard",
            "ultra",
        }
        assert all(
            row.description_label.text().strip()
            for row in window.vr_mode_panel._mode_rows.values()
        )
        assert (
            window.vr_local_base_action.isChecked()
            == window.vr_flow_button.isChecked()
        )
        assert not hasattr(window, "orchestration_button")
        menu_labels = [action.text() for action in window.vr_menu.actions()]
        assert "Consultar base local" in menu_labels
        assert "Desligado" in menu_labels
        assert "Automático" in menu_labels
        assert "Ligado" in menu_labels
        assert "Ultra" in menu_labels
        assert all("Orange" not in label for label in menu_labels)
        assert all("Rainbow" not in label for label in menu_labels)

        arrow_requests = []
        window.vr_flow_button.optionsRequested.connect(
            lambda: arrow_requests.append(True)
        )
        checked_before_arrow = window.vr_flow_button.isChecked()
        QTest.mouseClick(
            window.vr_flow_button,
            Qt.LeftButton,
            pos=QPoint(
                window.vr_flow_button.width() - 5,
                window.vr_flow_button.height() // 2,
            ),
        )
        assert arrow_requests == []
        assert window.vr_flow_button.isChecked() != checked_before_arrow

        window.vr_flow_button.setChecked(True)
        for mode, visual in (
            ("off", "off"),
            ("automatic", "off"),
            ("standard", "standard"),
            ("ultra", "ultra"),
        ):
            options = OrchestrationOptions(mode=mode)
            window._sync_orchestration_mode_ui(options, animate=False)
            assert window.orchestration_mode_actions[mode].isChecked()
            assert window.vr_mode_panel._mode_rows[mode].property("selected")
            assert window.composer_glow.mode() == visual

        window.draft_orchestration = OrchestrationOptions(mode="standard")
        window._sync_orchestration_mode_ui(
            window.draft_orchestration, animate=False
        )
        window.vr_local_base_action.setChecked(False)
        assert not window.vr_flow_button.isChecked()
        assert window.composer_glow.mode() == "off"

        window.current_conversation = "draft"
        window.draft_orchestration = OrchestrationOptions(
            mode="automatic", show_execution=False
        )
        window._sync_orchestration_mode_ui(
            window.draft_orchestration, animate=False
        )
        window._on_runtime_event(
            RuntimeEvent(
                "draft",
                "plan_created",
                "Plano automático",
                {
                    "mode": "automatic",
                    "effective_mode": "ultra",
                    "plan": {"difficulty": {"level": 4}, "agents": []},
                },
            )
        )
        assert window.composer_glow.mode() == "ultra"
        window._on_runtime_event(RuntimeEvent("draft", "turn_completed"))
        assert window.composer_glow.mode() == "off"
    finally:
        window.close()


def test_execution_transparency_can_be_hidden_and_replayed_safely(
    tmp_path: Path,
) -> None:
    from PySide6.QtWidgets import QApplication

    from vrsoft_extractor.mary.ui import MainWindow

    application = QApplication.instance() or QApplication([])
    settings = _settings(tmp_path)
    window = MainWindow(settings, smoke_test=True, auto_close_smoke=False)
    hidden = OrchestrationOptions(
        enabled=True,
        model_pool=(ModelRef("codex", "sol", "Sol"),),
        show_execution=False,
    )
    hidden_id = window.database.create_conversation(
        "Oculta", "codex", "sol", settings.work_dir / "hidden", orchestration=hidden
    )
    try:
        window.current_conversation = hidden_id
        window._on_runtime_event(
            RuntimeEvent(
                hidden_id,
                "agent_started",
                "VR Critic executando no modelo privado.",
                {"agent_id": "critic"},
            )
        )
        assert window.orchestration_trace.isHidden()
        assert window.chat_status.text() == "Trabalhando…"

        visible = OrchestrationOptions(
            enabled=True,
            model_pool=(ModelRef("codex", "sol", "Sol"),),
            show_execution=True,
        )
        visible_id = window.database.create_conversation(
            "Visível",
            "codex",
            "sol",
            settings.work_dir / "visible",
            orchestration=visible,
        )
        run_id = "run-visible"
        full_agent_output = "Ponto crítico validado.\n\n" + ("detalhe " * 900)
        plan_payload = {
            "run_id": run_id,
            "plan": {
                "difficulty": {"level": 3, "label": "Complexa"},
                "agents": [
                    {
                        "id": "critic",
                        "agent": "vr_critic",
                        "label": "VR Critic",
                        "model": {"display_name": "Sol"},
                        "task": "Criticar a solução.",
                        "reason": "<b>texto literal</b>",
                        "final": False,
                    },
                    {
                        "id": "final",
                        "agent": "vr_synthesizer",
                        "label": "VR Synthesizer",
                        "model": {"display_name": "Sol"},
                        "final": True,
                    },
                ],
            },
        }
        window.database.add_event(
            RuntimeEvent(visible_id, "plan_created", "Plano", plan_payload)
        )
        for kind, text, payload in (
            ("agent_started", "Critic iniciou", {"run_id": run_id, "agent_id": "critic"}),
            (
                "agent_completed",
                "Critic concluiu",
                {
                    "run_id": run_id,
                    "agent_id": "critic",
                    "output": full_agent_output,
                },
            ),
            ("synthesis_started", "Síntese", {"run_id": run_id}),
            ("orchestration_completed", "Concluído", {"run_id": run_id}),
        ):
            window.database.add_event(RuntimeEvent(visible_id, kind, text, payload))

        window.current_conversation = visible_id
        window.vr_agents_sidebar_preferred = True
        window._on_runtime_event(
            RuntimeEvent(
                visible_id,
                "intent_analysis_started",
                "Analisando intenção e requisitos.",
                {"run_id": run_id},
            )
        )
        assert window.chat_status.text() == "Analisando intenção e requisitos."
        assert (
            window.orchestration_trace_status.text()
            == "Analisando intenção e requisitos."
        )
        with patch.object(
            window,
            "_render_orchestration_trace",
            wraps=window._render_orchestration_trace,
        ) as render_trace:
            window._restore_orchestration_trace(visible_id, visible)
        assert render_trace.call_count == 1
        application.processEvents()
        assert window.orchestration_agent_list.count() == 2
        window.orchestration_agent_list.setCurrentRow(0)
        application.processEvents()
        rendered = window.orchestration_trace_details.toPlainText()
        assert "<b>texto literal</b>" in window.orchestration_agent_task.text()
        assert "Criticar a solução." in window.orchestration_agent_task.text()
        assert "Ponto crítico validado." in rendered
        assert rendered.count("detalhe") == 900
        assert "VR Critic" in window.orchestration_agent_chat_title.text()
        assert "concluído" in window.orchestration_agent_chat_title.text()
        assert "Última execução · Concluído" == window.orchestration_trace_status.text()
        assert window.chat_splitter.indexOf(window.orchestration_trace) == 2
        assert not window.orchestration_trace.isHidden()
        window._set_vr_agent_sidebar_visible(False)
        assert window.orchestration_trace.isHidden()
        assert not window.vr_agents_toggle_button.isHidden()
    finally:
        window.close()


def test_multiagent_migration_creates_one_backup_and_idempotent_pool(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    path = settings.database_path
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                native_id TEXT NOT NULL DEFAULT '',
                workspace TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                archived INTEGER NOT NULL DEFAULT 0,
                cloned_from TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO conversations
               (id,title,provider,model,workspace,created_at,updated_at)
               VALUES('legacy','Legada','codex','sol','TrabalhoMary/legacy','now','now')"""
        )

    database = MaryDatabase(path, root=settings.root)
    backup = (
        settings.root
        / ".state"
        / "backups"
        / "conhecimento-pre-multiagent.sqlite"
    )
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        legacy_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(conversations)")
        }
        assert "orchestration_enabled" not in legacy_columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='conversation_model_pool'"
        ).fetchone() is None

    assert [(item.provider, item.model) for item in database.conversation_model_pool("legacy")] == [
        ("codex", "sol")
    ]
    assert database.get_conversation("legacy")["orchestration_mode"] == "off"
    models = [
        ModelRef("codex", "sol", "Sol antigo"),
        ModelRef("claude", "opus", "Opus", capabilities=("reasoning",)),
        ModelRef("codex", "sol", "Sol"),
    ]
    database.set_conversation_model_pool("legacy", models)
    database.set_conversation_model_pool("legacy", models)
    pool = database.conversation_model_pool("legacy")
    assert [(item.key, item.display_name) for item in pool] == [
        ("claude:opus", "Opus"),
        ("codex:sol", "Sol"),
    ]

    database.set_conversation_model_pool(
        "legacy", [ModelRef("claude", "opus", "Opus")]
    )
    backup_bytes = backup.read_bytes()
    reopened = MaryDatabase(path, root=settings.root)
    assert backup.read_bytes() == backup_bytes
    assert [item.key for item in reopened.conversation_model_pool("legacy")] == [
        "claude:opus",
    ]


def test_partial_pool_migration_recovers_only_conversations_without_rows(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                native_id TEXT NOT NULL DEFAULT '',
                workspace TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                archived INTEGER NOT NULL DEFAULT 0,
                cloned_from TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE conversation_model_pool (
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                provider TEXT NOT NULL,
                model_id TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY(conversation_id,provider,model_id)
            )"""
        )
        connection.execute(
            """INSERT INTO conversations
               (id,title,provider,model,workspace,created_at,updated_at)
               VALUES('partial','Parcial','codex','sol','work','now','now')"""
        )

    database = MaryDatabase(settings.database_path, root=settings.root)
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT provider,model_id FROM conversation_model_pool "
            "WHERE conversation_id='partial'"
        ).fetchall()
    assert [tuple(row) for row in rows] == [("codex", "sol")]


def test_mode_migration_preserves_off_automatic_and_ultra_legacy_states(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-modes.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                native_id TEXT NOT NULL DEFAULT '',
                workspace TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                archived INTEGER NOT NULL DEFAULT 0,
                orchestration_enabled INTEGER NOT NULL DEFAULT 0,
                ultra_enabled INTEGER NOT NULL DEFAULT 0,
                cloned_from TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.executemany(
            """INSERT INTO conversations
               (id,title,provider,model,workspace,orchestration_enabled,
                ultra_enabled,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                ("off", "Off", "codex", "sol", "off", 0, 0, "now", "now"),
                ("auto", "Auto", "codex", "sol", "auto", 1, 0, "now", "now"),
                ("ultra", "Ultra", "codex", "sol", "ultra", 0, 1, "now", "now"),
            ),
        )

    database = MaryDatabase(path)
    assert {
        identifier: database.get_conversation(identifier)["orchestration_mode"]
        for identifier in ("off", "auto", "ultra")
    } == {"off": "off", "auto": "automatic", "ultra": "ultra"}


def test_dynamic_flags_round_trip_and_control_the_validated_plan(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    sol = ModelRef("codex", "sol", "Sol")
    opus = ModelRef("claude", "opus", "Opus")
    options = OrchestrationOptions(
        mode="standard",
        model_pool=(sol, opus),
        dynamic_model_routing=False,
        dynamic_agent_count=False,
        difficulty_routing=False,
    )
    conversation_id = database.create_conversation(
        "Flags", "codex", "sol", settings.work_dir / "flags", orchestration=options
    )
    restored = ConversationOptions.from_mapping(
        database.get_conversation(conversation_id),
        tuple(database.conversation_model_pool(conversation_id)),
    ).orchestration
    assert restored.mode == "standard"
    assert restored.dynamic_model_routing is False
    assert restored.dynamic_agent_count is False
    assert restored.difficulty_routing is False

    raw = json.dumps(
        {
            "difficulty": {"level": 1},
            "agents": [
                {"agent": "vr_critic", "model": "claude:opus"},
                {"agent": "vr_validator", "model": "claude:opus"},
            ],
        }
    )
    plan = parse_plan(raw, "Pedido", restored, sol, (sol, opus))
    assert plan.difficulty_level == 3
    assert len(plan.agents) == 3
    assert {item.model.key for item in plan.agents[:-1]} == {"codex:sol"}


def test_parse_plan_accepts_valid_models_and_falls_back_inside_pool() -> None:
    sol = ModelRef("codex", "sol", "Sol")
    opus = ModelRef("claude", "opus", "Opus")
    pool = (sol, opus)
    options = OrchestrationOptions(
        mode="standard", strategy="adaptive", model_pool=pool
    )
    valid = json.dumps(
        {
            "difficulty": {"level": 3, "summary": "Exige comparação."},
            "strategy": "parallel",
            "agents": [
                {
                    "id": "critic",
                    "agent": "vr_critic",
                    "model": "claude:opus",
                    "effort": "low",
                    "task": "Comparar alternativas.",
                },
                {
                    "id": "final",
                    "agent": "vr_synthesizer",
                    "model": "codex:sol",
                    "effort": "max",
                    "depends_on": ["critic"],
                },
            ],
        }
    )
    plan = parse_plan(valid, "Compare alternativas", options, sol, pool)

    assert not plan.fallback
    assert plan.difficulty_level == 3
    assert plan.agents[0].model is opus
    assert plan.agents[0].effort == "low"
    assert plan.agents[-1].model is sol
    assert plan.agents[-1].effort == "max"
    assert not plan.warnings

    outside_pool = json.dumps(
        {
            "difficulty": {"level": 4},
            "agents": [
                {
                    "id": "critic",
                    "agent": "vr_critic",
                    "model": "other:fable-5",
                    "effort": "impossível",
                }
            ],
        }
    )
    repaired = parse_plan(outside_pool, "Investigue profundamente", options, sol, pool)
    assert repaired.agents[0].model.key in {item.key for item in pool}
    assert all(item.model.key in {candidate.key for candidate in pool} for item in repaired.agents)
    assert any("fallback de modelo" in warning for warning in repaired.warnings)
    assert any("fallback de effort" in warning for warning in repaired.warnings)
    assert repaired.agents[0].effort == "xhigh"
    assert parse_plan("not json", "Traduza: hello", options, sol, pool).fallback


def test_agent_definition_is_independent_from_selected_model() -> None:
    definition = AGENT_CATALOG["vr_critic"]
    first = VrAgentAssignment("critic", definition, ModelRef("codex", "sol"), "Criticar", "")
    second = VrAgentAssignment(
        "critic", definition, ModelRef("claude", "opus"), "Criticar", ""
    )

    assert not hasattr(definition, "model")
    assert first.agent is second.agent
    assert first.agent.role == second.agent.role == "criticism"
    assert first.model.key != second.model.key


def test_vrmaster_personality_is_applied_to_each_orchestration_stage() -> None:
    model = ModelRef("codex", "sol", "Sol")
    options = OrchestrationOptions(mode="standard", model_pool=(model,))
    assignment = VrAgentAssignment(
        "research",
        AGENT_CATALOG["vr_researcher"],
        model,
        "Verificar a evidência disponível.",
        "",
    )
    plan = VrPlan(
        2,
        "Moderada",
        "Exige validação documental.",
        "specialized",
        (
            assignment,
            VrAgentAssignment(
                "final",
                AGENT_CATALOG["vr_synthesizer"],
                model,
                "Consolidar.",
                "",
                ("research",),
            ),
        ),
    )

    planner = build_planner_prompt("Analise o erro", options, model, (model,))
    worker = build_agent_prompt(assignment, "Analise o erro", [])
    validation = build_consistency_prompt(
        "Analise o erro", [], "[E1] WIKI/FUNCIONAMENTO"
    )
    synthesis = build_synthesis_prompt("Analise o erro", plan, [], None)

    assert "[E1] WIKI/FUNCIONAMENTO" in validation

    assert "Sintoma -> Contexto -> Evidência" in planner
    assert "Não complete lacunas com conhecimento próprio" in worker
    assert "A presença de uma evidência no pacote não" in worker
    assert "ações destrutivas ou de alto impacto" in validation
    assert "Especialista Técnico em ERP VRMaster" in synthesis
    assert "Precisão > Evidência" in synthesis
    assert "Nunca esconda incerteza" in synthesis
    assert "Não recomende alteração direta de banco" in synthesis
    assert "evidência disponível não amplia o escopo" in synthesis


def test_execution_batches_run_every_non_final_agent_in_parallel() -> None:
    model = ModelRef("codex", "sol")
    planner = VrAgentAssignment(
        "planner", AGENT_CATALOG["vr_planner"], model, "Planejar", ""
    )
    reasoner_a = VrAgentAssignment(
        "reasoner_a",
        AGENT_CATALOG["vr_reasoner"],
        model,
        "Analisar A",
        "",
        ("planner",),
    )
    reasoner_b = VrAgentAssignment(
        "reasoner_b",
        AGENT_CATALOG["vr_reasoner"],
        model,
        "Analisar B",
        "",
        ("planner",),
    )
    critic = VrAgentAssignment(
        "critic",
        AGENT_CATALOG["vr_critic"],
        model,
        "Criticar",
        "",
        ("reasoner_a", "reasoner_b"),
    )
    final = VrAgentAssignment(
        "final",
        AGENT_CATALOG["vr_synthesizer"],
        model,
        "Sintetizar",
        "",
        ("critic",),
    )
    plan = VrPlan(3, "Complexa", "", "adaptive", (planner, reasoner_a, reasoner_b, critic, final))

    assert [[item.id for item in batch] for batch in execution_batches(plan)] == [[
        "planner",
        "reasoner_a",
        "reasoner_b",
        "critic",
    ]]

    cyclic = VrPlan(
        3,
        "Complexa",
        "",
        "adaptive",
        (
            VrAgentAssignment(
                "a", AGENT_CATALOG["vr_reasoner"], model, "A", "", ("b",)
            ),
            VrAgentAssignment(
                "b", AGENT_CATALOG["vr_critic"], model, "B", "", ("a",)
            ),
            final,
        ),
    )
    assert [[item.id for item in batch] for batch in execution_batches(cyclic)] == [
        ["a", "b"]
    ]


def test_runtime_starts_every_non_final_agent_concurrently(tmp_path: Path) -> None:
    class ParallelProbeProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__("codex", difficulty_level=3)
            self.worker_barrier = threading.Barrier(4)
            self.active_workers = 0
            self.maximum_active_workers = 0

        def send_message(self, *args, **kwargs) -> None:
            conversation_id = str(args[0])
            is_worker = (
                ":vr:" in conversation_id
                and "vr_orchestrator_" not in conversation_id
            )
            if not is_worker:
                return super().send_message(*args, **kwargs)
            with self._lock:
                self.active_workers += 1
                self.maximum_active_workers = max(
                    self.maximum_active_workers,
                    self.active_workers,
                )
            try:
                self.worker_barrier.wait(timeout=3)
                super().send_message(*args, **kwargs)
            finally:
                with self._lock:
                    self.active_workers -= 1

    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = ParallelProbeProvider()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            mode="standard",
            model_pool=(ModelRef("codex", "sol", "Sol"),),
        ),
    )
    completed = threading.Event()
    orchestrator.send(
        conversation_id,
        "Analise em paralelo",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=True,
    )

    assert completed.wait(5)
    assert provider.maximum_active_workers == 4


def test_orchestrated_turn_exposes_and_persists_only_final_synthesis(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    codex = FakeProvider("codex")
    claude = FakeProvider("claude")
    orchestrator.providers = {"codex": codex, "claude": claude}
    pool = (ModelRef("codex", "sol", "Sol"), ModelRef("claude", "opus", "Opus"))
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            enabled=True,
            strategy="adaptive",
            model_pool=pool,
            show_execution=True,
        ),
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(conversation_id, "Resolva o problema", callback, use_vr=True)
    assert completed.wait(5), "o fluxo orquestrado não concluiu"

    assert [event.text for event in events if event.kind == "assistant_delta"] == [
        "RESPOSTA FINAL"
    ]
    assert [tuple(row)[:3] for row in database.messages(conversation_id)]
    messages = database.messages(conversation_id)
    assert [(row["role"], row["content"]) for row in messages] == [
        ("user", "Resolva o problema"),
        ("assistant", "RESPOSTA FINAL"),
    ]
    with database.connect() as connection:
        persisted_deltas = connection.execute(
            "SELECT text FROM runtime_events WHERE conversation_id=? AND kind='assistant_delta'",
            (conversation_id,),
        ).fetchall()
        persisted_agent_deltas = connection.execute(
            "SELECT text FROM runtime_events WHERE conversation_id=? AND kind='agent_delta'",
            (conversation_id,),
        ).fetchall()
        completed_agents = connection.execute(
            "SELECT payload_json FROM runtime_events "
            "WHERE conversation_id=? AND kind='agent_completed'",
            (conversation_id,),
        ).fetchall()
    assert [row["text"] for row in persisted_deltas] == ["RESPOSTA FINAL"]
    assert persisted_agent_deltas == []
    assert any(event.kind == "agent_delta" for event in events)
    assert completed_agents
    assert all(
        json.loads(row["payload_json"])["output"].startswith(
            "resultado intermediário"
        )
        for row in completed_agents
    )
    assert any(event.kind == "parallel_group_started" for event in events)
    all_sent = codex.sent + claude.sent
    internal_calls = [
        item for item in all_sent if ":vr:" in item["conversation_id"]
    ]
    assert len(internal_calls) == 7
    assert any(
        "vr_orchestrator_validation" in item["conversation_id"]
        for item in internal_calls
    )
    main_calls = [item for item in all_sent if item["conversation_id"] == conversation_id]
    assert len(main_calls) == 1
    assert main_calls[0]["effort"] == "max"
    assert "RESULTADOS DOS AGENTES" in main_calls[0]["message"]
    worker_efforts = {
        item["conversation_id"].split(":")[-2]: item["effort"]
        for item in all_sent
        if ":vr:" in item["conversation_id"]
        and "vr_orchestrator_" not in item["conversation_id"]
    }
    assert {
        "vr_wiki_researcher",
        "vr_kb_researcher",
        "vr_dba__schema",
        "vr_dba",
    }.issubset(worker_efforts)
    assert all(
        worker_efforts[agent_id] == "medium"
        for agent_id in (
            "vr_wiki_researcher",
            "vr_kb_researcher",
            "vr_dba__schema",
        )
    )


def test_vr_off_bypasses_personality_base_and_orchestration(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            mode="standard",
            model_pool=(ModelRef("codex", "sol", "Sol"),),
        ),
    )
    completed = threading.Event()

    orchestrator.send(
        conversation_id,
        "Responda como o Codex nativo.",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=False,
    )

    assert completed.wait(5)
    assert len(provider.sent) == 1
    assert provider.sent[0]["message"] == "Responda como o Codex nativo."
    assert provider.sent[0]["options"].vr_enabled is False
    assert provider.start_options[0].vr_enabled is False
    assert not any(":vr:" in item["conversation_id"] for item in provider.sent)
    assert database.messages(conversation_id)[-1]["response_mode"] == "native"


@pytest.mark.parametrize("provider_name", ("codex", "opencode"))
def test_vr_on_direct_adds_identity_and_local_base_without_multiagent(
    tmp_path: Path,
    provider_name: str,
) -> None:
    settings = _settings(tmp_path, legacy_vr_orchestration=False)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider(provider_name)
    orchestrator.providers = {provider_name: provider}
    conversation_id = orchestrator.new_conversation(
        provider_name,
        "sol",
        defer_provider_start=True,
        # Stored legacy choices must no longer reactivate the proprietary graph.
        orchestration=OrchestrationOptions(
            mode="standard",
            model_pool=(ModelRef(provider_name, "sol", "Sol"),),
        ),
        vr_enabled=True,
    )
    completed = threading.Event()

    orchestrator.send(
        conversation_id,
        "Consulte o conhecimento local.",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=True,
    )

    assert completed.wait(5)
    assert len(provider.sent) == 1
    prompt = provider.sent[0]["message"]
    assert "MODO VR ATIVO" in prompt
    assert "Seu nome de atendimento é VR" in prompt
    assert "PESQUISA LOCAL VR" in prompt
    assert str(settings.root) in prompt
    assert provider.sent[0]["options"].vr_enabled is True
    assert provider.start_options[0].vr_enabled is True
    assert not any(":vr:" in item["conversation_id"] for item in provider.sent)
    assert database.messages(conversation_id)[-1]["response_mode"] == "vr"


def test_changing_vr_mode_releases_session_and_starts_an_isolated_one(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    database.update_conversation(conversation_id, native_id="native-vr")

    orchestrator.update_vr_mode(conversation_id, False)

    row = database.get_conversation(conversation_id)
    assert row["vr_enabled"] == 0
    assert row["native_id"] == ""
    assert provider.released == [(conversation_id, "native-vr", False)]


def test_query_profile_supports_functional_process_schema_and_hybrid_intents(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    router = KnowledgeRouter(database, settings.root)

    functional = router.classify("Para que serve e como funciona a função 102?")
    process = router.classify("Como fazer o passo a passo para configurar o TEF?")
    sped_process = router.classify("Como gerar SPED Fiscal no VR?")
    technical = router.classify(
        "Qual tabela e chave estrangeira relacionam venda e estoque?"
    )
    hybrid = router.classify(
        "Como funciona a baixa de estoque, qual o processo e quais tabelas participam?"
    )

    assert functional.answer_type == "functional"
    assert functional.entities["functions"] == ("102",)
    assert functional.entities["numbers"] == ("102",)
    assert process.answer_type == "process"
    assert sped_process.answer_type == "process"
    assert technical.answer_type == "technical_schema"
    assert hybrid.answer_type == "hybrid"
    assert all(abs(sum(item.intents.values()) - 1.0) < 0.001 for item in (
        functional, process, sped_process, technical, hybrid
    ))


def test_process_route_expands_wiki_index_and_does_not_inject_schema(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    documents = (
        KnowledgeDocument(
            source="wiki",
            source_id="sped-wiki",
            title="SPED Fiscal",
            url="https://wiki.example/sped",
            markdown="""# Índice

1. Recursos
2. Configurar
3. Geração SPED Fiscal

## Recursos

A rotina exporta a escrituração fiscal.

## Configurar

Selecione o perfil e a versão do leiaute.

## Geração SPED Fiscal

Informe período, data de apuração, loja e destino; depois clique em Exportar.
""",
            module="Fiscal",
            review_status="approved",
            content_hash="sped-wiki",
            local_path="conhecimento/Fiscal/Wiki/sped.md",
        ),
        KnowledgeDocument(
            source="kb",
            source_id="sped-kb",
            title="Como gerar o SPED Fiscal",
            url="https://kb.example/sped",
            markdown="Preencha período, versão, loja e destino e clique em Exportar.",
            module="Fiscal",
            review_status="approved",
            content_hash="sped-kb",
            local_path="conhecimento/Fiscal/KB/sped.md",
        ),
        KnowledgeDocument(
            source="schema",
            source_id="sped-schema",
            title="Tabela SPED Fiscal",
            url="",
            markdown="A tabela sped_fiscal possui id e periodo.",
            module="Fiscal",
            review_status="approved",
            content_hash="sped-schema",
            local_path="conhecimento/Fiscal/Schema/sped.md",
        ),
    )
    for document in documents:
        database.upsert_document(document)

    bundle = KnowledgeRouter(database, settings.root).route(
        "Como gerar SPED Fiscal no VR?"
    )

    headings = {item.heading for item in bundle.candidates if item.source == "wiki"}
    assert bundle.profile.answer_type == "process"
    assert bundle.source_counts["schema"] == 0
    assert "Geração SPED Fiscal" in headings
    assert "Configurar" in headings


def test_router_ignores_presentation_modifiers_and_keeps_primary_procedure(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="entrada-principal",
            title="Manual Nota Fiscal Entrada",
            url="https://wiki.example/entrada",
            markdown="""# Processo de entrada de nota

## Lançamento manual de nota fiscal entrada

Acesse Nota Fiscal, inclua a nota, preencha o cabeçalho, informe os itens,
salve e finalize a entrada.
""",
            module="Fiscal",
            review_status="approved",
            content_hash="entrada-principal",
            local_path="conhecimento/Fiscal/Wiki/entrada.md",
        )
    )
    for index in range(6):
        database.upsert_document(
            KnowledgeDocument(
                source="wiki",
                source_id=f"entrada-incidental-{index}",
                title=f"Erro {index} ao finalizar nota entrada",
                url=f"https://wiki.example/erro-{index}",
                markdown="Mensagem específica de erro durante um caso excepcional.",
                module="Fiscal",
                review_status="approved",
                content_hash=f"entrada-incidental-{index}",
                local_path=f"conhecimento/Fiscal/Wiki/erro-{index}.md",
            )
        )

    bundle = KnowledgeRouter(database, settings.root).route(
        "Crie um fluxo completo do processo de entrada de nota"
    )

    assert bundle.profile.terms == ("fluxo", "processo", "entrada", "nota")
    assert any(item.source_id == "entrada-principal" for item in bundle.candidates)


def test_generic_alphanumeric_entities_are_recognized_without_topic_rules() -> None:
    entities = extract_knowledge_entities(
        "Como funciona o bloco ZX742 e o retorno E116 na rotina pedido_item?"
    )

    assert {"zx742", "e116"}.issubset(entities["identifiers"])
    assert "pedido_item" in entities["tables"]


def test_source_research_plan_is_mandatory_even_for_a_simple_plan() -> None:
    model = ModelRef("codex", "sol", "Sol")
    final = VrAgentAssignment(
        "final",
        AGENT_CATALOG["vr_synthesizer"],
        model,
        "Responder.",
        "",
    )
    plan = VrPlan(1, "Simples", "Resposta direta.", "direct", (final,))

    expanded = ensure_source_research_plan(
        plan,
        OrchestrationOptions(mode="standard", model_pool=(model,)),
        model,
        (model,),
    )

    source_workers = [item for item in expanded.agents if item.agent.source]
    assert [item.agent.source for item in source_workers] == ["wiki", "kb", "schema"]
    assert all(item.required for item in source_workers)
    assert set(expanded.agents[-1].depends_on) == {
        "vr_wiki_researcher",
        "vr_kb_researcher",
        "vr_dba",
    }
    dba = next(item for item in expanded.agents if item.id == "vr_dba")
    schema = next(item for item in expanded.agents if item.id == "vr_dba__schema")
    assert dba.depends_on == ("vr_dba__schema",)
    assert schema.parent_id == "vr_dba"


def test_source_research_plan_respects_the_routed_source_contract() -> None:
    model = ModelRef("codex", "sol", "Sol")
    final = VrAgentAssignment(
        "final",
        AGENT_CATALOG["vr_synthesizer"],
        model,
        "Responder.",
        "",
    )
    plan = VrPlan(2, "Moderada", "Pesquisa dirigida.", "specialized", (final,))
    options = OrchestrationOptions(mode="standard", model_pool=(model,))

    process = ensure_source_research_plan(
        plan,
        options,
        model,
        (model,),
        modules=("Fiscal",),
        sources=("kb", "wiki"),
        required_sources=("kb",),
    )
    technical = ensure_source_research_plan(
        plan,
        options,
        model,
        (model,),
        modules=("Fiscal",),
        sources=("schema",),
        required_sources=("schema",),
    )

    assert {item.id for item in process.agents} == {
        "vr_fisco",
        "vr_fisco__wiki",
        "vr_fisco__kb",
        "final",
    }
    assert next(item for item in process.agents if item.id == "vr_fisco__kb").required
    assert not next(
        item for item in process.agents if item.id == "vr_fisco__wiki"
    ).required
    assert {item.id for item in technical.agents} == {
        "vr_dba",
        "vr_dba__schema",
        "final",
    }


def test_module_specialists_use_wiki_kb_and_dba_owns_global_schema() -> None:
    model = ModelRef("codex", "sol", "Sol")
    final = VrAgentAssignment(
        "final",
        AGENT_CATALOG["vr_synthesizer"],
        model,
        "Responder.",
        "",
    )
    plan = VrPlan(3, "Complexa", "Multimódulo.", "parallel", (final,))

    expanded = ensure_source_research_plan(
        plan,
        OrchestrationOptions(mode="standard", model_pool=(model,)),
        model,
        (model,),
        modules=("Fiscal", "PDV"),
    )

    fisco = next(item for item in expanded.agents if item.id == "vr_fisco")
    caixa = next(item for item in expanded.agents if item.id == "vr_caixa")
    dba = next(item for item in expanded.agents if item.id == "vr_dba")
    assert fisco.module == "Fiscal"
    assert caixa.module == "PDV"
    assert set(fisco.depends_on) == {
        "vr_fisco__wiki",
        "vr_fisco__kb",
    }
    assert all(
        item.parent_id == "vr_fisco" and item.module == "Fiscal"
        for item in expanded.agents
        if item.id.startswith("vr_fisco__")
    )
    assert dba.depends_on == ("vr_dba__schema",)
    assert next(
        item for item in expanded.agents if item.id == "vr_dba__schema"
    ).parent_id == "vr_dba"
    assert [[item.id for item in batch] for batch in execution_batches(expanded)] == [
        [
            "vr_fisco__wiki",
            "vr_fisco__kb",
            "vr_caixa__wiki",
            "vr_caixa__kb",
            "vr_dba__schema",
        ],
        ["vr_fisco", "vr_caixa", "vr_dba"],
    ]
    assert set(expanded.agents[-1].depends_on) == {
        "vr_fisco",
        "vr_caixa",
        "vr_dba",
    }
    assert any("multimódulo" in warning for warning in expanded.warnings)


def test_router_retrieves_wiki_kb_and_schema_as_complementary_lanes(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    documents = (
        KnowledgeDocument(
            source="wiki",
            source_id="wiki-venda",
            title="Funcionamento da baixa de estoque na venda",
            url="https://wiki.example/venda",
            markdown=(
                "A finalização da venda aciona a baixa de estoque e atualiza o saldo."
            ),
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="wiki-venda",
            local_path="conhecimento/ADM_FIN_ESTOQUE/Wiki/venda.md",
        ),
        KnowledgeDocument(
            source="kb",
            source_id="kb-venda",
            title="Processo para conferir a baixa de estoque da venda",
            url="https://kb.example/venda",
            markdown=(
                "Passo a passo: finalize a venda, consulte o estoque e confira a loja."
            ),
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="kb-venda",
            local_path="conhecimento/ADM_FIN_ESTOQUE/KB/venda.md",
        ),
        KnowledgeDocument(
            source="schema",
            source_id="schema-venda",
            title="Schema venda e movimento de estoque",
            url="",
            markdown=(
                "## `public`.`venda`\n\n| Coluna | Tipo | Nulo | PK | Default | Descricao |\n"
                "|---|---|---|---|---|---|\n| `id` | `integer` | Nao | PK | | |\n"
                "| `id_estoque` | `integer` | Nao | | | |\n\n"
                "**Chaves Estrangeiras:**\n- `venda.id_estoque` -> `public.estoque.id`"
            ),
            module="Multimodulo",
            review_status="approved",
            content_hash="schema-venda",
            local_path="agentes/SchemaVR/test-schema.md",
        ),
    )
    for document in documents:
        database.upsert_document(document)
    router = KnowledgeRouter(database, settings.root, per_source_limit=3)

    bundle = router.route(
        "Como funciona a baixa de estoque da venda, qual processo conferir e quais tabelas se relacionam?"
    )

    assert {item.source for item in bundle.candidates} == {"wiki", "kb", "schema"}
    assert bundle.source_counts == {"wiki": 1, "kb": 1, "schema": 1}
    assert bundle.selected_modules == ("ADM_FIN_ESTOQUE", "PDV")
    assert bundle.routing_scope == "multimodule"
    reports = {
        (report.module, report.source): report.status
        for report in bundle.source_reports
    }
    assert reports == {
        ("ADM_FIN_ESTOQUE", "wiki"): "found",
        ("ADM_FIN_ESTOQUE", "kb"): "found",
        ("PDV", "wiki"): "exhausted",
        ("PDV", "kb"): "exhausted",
        ("", "schema"): "found",
    }
    assert all(report.queries for report in bundle.source_reports)
    assert bundle.profile.answer_type == "hybrid"
    prompt = router.prompt(bundle)
    assert "WIKI/FUNCIONAMENTO" in prompt
    assert "KB/PROCESSO" in prompt
    assert "SCHEMA/ESTRUTURA" in prompt
    assert "[Funcionamento da baixa" in prompt


def test_router_prefers_exact_function_number_over_generic_function_hits(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    for source_id, title, markdown in (
        ("102", "Funcao 102", "Funcao responsavel por identificar o operador."),
        ("198", "Funcao 198", "Funcao usada para outro procedimento do PDV."),
    ):
        database.upsert_document(
            KnowledgeDocument(
                source="wiki",
                source_id=source_id,
                title=title,
                url="",
                markdown=markdown,
                module="PDV",
                review_status="approved",
                content_hash=source_id,
                local_path=f"conhecimento/PDV/Wiki/funcao-{source_id}.md",
            )
        )

    bundle = KnowledgeRouter(database, settings.root).route(
        "Para que serve a funcao 102?"
    )

    assert bundle.candidates[0].title == "Funcao 102"
    assert bundle.candidates[0].score_breakdown["entities"] == 1.0


def test_router_uses_generic_identifier_across_all_three_sources(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    for source, suffix, body in (
        ("wiki", "conceito", "O bloco ZX742 registra a configuração funcional."),
        ("kb", "procedimento", "Para validar ZX742, confira o cadastro e o resultado."),
        ("schema", "estrutura", "A tabela regra_zx742 contém id_regra e situacao."),
    ):
        database.upsert_document(
            KnowledgeDocument(
                source=source,
                source_id=f"{source}-{suffix}",
                title=f"ZX742 - {suffix}",
                url=f"https://example.test/{source}/zx742" if source != "schema" else "",
                markdown=body,
                module="Fiscal",
                review_status="approved",
                content_hash=f"{source}-{suffix}",
                local_path=f"conhecimento/Fiscal/{source}/{suffix}.md",
            )
        )

    bundle = KnowledgeRouter(database, settings.root).route(
        "Como funciona ZX742 e onde seus dados são gravados?"
    )

    assert bundle.profile.entities["identifiers"] == ("zx742",)
    assert {item.source for item in bundle.candidates} == {"wiki", "kb", "schema"}
    assert {item.status for item in bundle.source_reports} == {"found"}


def test_document_metadata_resolves_a_code_or_lexical_module_mismatch(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="entrada-operacional",
            title="Entrada de nota fiscal",
            url="https://example.test/entrada",
            markdown="A rotina cadastra fornecedor, itens e parcelas da entrada.",
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="entrada-operacional",
            local_path="conhecimento/ADM_FIN_ESTOQUE/Wiki/entrada.md",
        )
    )

    bundle = KnowledgeRouter(database, settings.root).route(
        "Como realizar a entrada de nota fiscal?"
    )

    assert bundle.profile.module == "Fiscal"
    assert bundle.selected_modules == ("ADM_FIN_ESTOQUE",)
    assert bundle.routing_scope == "single_module"
    assert all(
        report.module == "ADM_FIN_ESTOQUE"
        for report in bundle.source_reports
        if report.source in {"wiki", "kb"}
    )
    assert bundle.source_report("schema").module == ""


def test_schema_parser_and_sync_create_structured_catalog(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    schema_dir = settings.root / "agentes" / "SchemaVR"
    schema_dir.mkdir(parents=True)
    markdown = """# Schema PostgreSQL

## `public`.`venda`
*Registros aproximados: 20*

| Coluna | Tipo | Nulo | PK | Default | Descricao |
|---|---|---|---|---|---|
| `id` | `integer` | Nao | PK | | Venda |
| `id_loja` | `integer` | Nao | | | Loja |

**Chaves Estrangeiras:**
- `venda.id_loja` -> `public.loja.id`
"""
    (schema_dir / "schema.md").write_text(markdown, encoding="utf-8")
    parsed = parse_schema_markdown(markdown)
    assert len(parsed) == 1
    assert parsed[0].schema_name == "public"
    assert parsed[0].table_name == "venda"
    assert [item.name for item in parsed[0].columns] == ["id", "id_loja"]
    assert parsed[0].relations[0].to_table == "loja"

    database = MaryDatabase(settings.database_path, root=settings.root)
    stats = SchemaSync(settings, database).sync()
    assert stats.created == 1
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM schema_tables").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM schema_columns").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM schema_relations").fetchone()[0] == 1
    catalog = database.search_schema_catalog("venda id_loja")
    assert catalog[0]["table_name"] == "venda"
    assert catalog[0]["relations"][0]["to_table"] == "loja"


def test_schema_sync_accepts_a_user_selected_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    selected = settings.root / "imports" / "novo-schema.md"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        """# Schema PostgreSQL

## `public`.`produto`

| Coluna | Tipo | Nulo | PK | Default | Descricao |
|---|---|---|---|---|---|
| `id` | `integer` | Nao | PK | | Produto |
""",
        encoding="utf-8",
    )
    database = MaryDatabase(settings.database_path, root=settings.root)

    stats = SchemaSync(settings, database, schema_path=selected).sync()

    assert stats.created == 1
    document = database.get_document("schema", "postgresql-vr")
    assert document is not None
    assert document["local_path"] == "imports/novo-schema.md"
    assert database.search_schema_catalog("produto")[0]["table_name"] == "produto"


def test_router_groups_cross_source_duplicates_and_flags_conflicts(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    for source, source_id, text in (
        (
            "wiki",
            "cancelamento-wiki",
            "O cancelamento da venda atualiza o estoque automaticamente após finalizar a rotina.",
        ),
        (
            "kb",
            "cancelamento-kb",
            "O cancelamento da venda não atualiza o estoque automaticamente após finalizar a rotina.",
        ),
    ):
        database.upsert_document(
            KnowledgeDocument(
                source=source,
                source_id=source_id,
                title="Cancelamento da venda e atualização do estoque",
                url=f"https://{source}.example/cancelamento",
                markdown=text,
                module="ADM_FIN_ESTOQUE",
                review_status="approved",
                content_hash=source_id,
                local_path=f"conhecimento/ADM_FIN_ESTOQUE/{source}/{source_id}.md",
            )
        )
    router = KnowledgeRouter(database, settings.root)

    bundle = router.route(
        "O cancelamento da venda atualiza o estoque automaticamente?"
    )

    assert len(bundle.groups) == 1
    assert bundle.groups[0].relationship == "complementary"
    assert len(bundle.groups[0].evidence_ids) == 2
    assert len(bundle.conflicts) == 1
    assert "polaridade diferente" in bundle.conflicts[0].reason


def test_vr_turn_persists_routed_evidence_as_message_citations(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, legacy_vr_orchestration=False)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="funcao-102",
            title="Função 102",
            url="https://wiki.example/102",
            markdown="A função 102 permite a entrada do operador no PDV.",
            module="PDV",
            review_status="approved",
            content_hash="funcao-102",
            local_path="conhecimento/PDV/Wiki/funcao-102.md",
        )
    )
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider(
        "codex", final_text="Fonte: https://wiki.example/102"
    )
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(
        conversation_id,
        "Para que serve a função 102 no PDV?",
        callback,
        use_vr=True,
    )

    assert completed.wait(5)
    assert any(event.kind == "knowledge_routed" for event in events)
    response_plans = [
        event for event in events if event.kind == "response_plan_created"
    ]
    assert len(response_plans) == 1
    assert response_plans[0].payload["completed"] == 3
    assert len(response_plans[0].payload["steps"]) == 5
    assert "função 102" in response_plans[0].payload["steps"][0].casefold()
    assert any("PDV" in step for step in response_plans[0].payload["steps"])
    assert not any(
        "interpretando intenção" in step.casefold()
        for step in response_plans[0].payload["steps"]
    )
    assistant = database.messages(conversation_id)[-1]
    with database.connect() as connection:
        citations = connection.execute(
            "SELECT * FROM source_citations WHERE message_id=?",
            (assistant["id"],),
        ).fetchall()
    assert len(citations) == 1
    assert "entrada do operador" in citations[0]["excerpt"]


def test_direct_vr_does_not_persist_candidates_not_cited_by_the_answer(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, legacy_vr_orchestration=False)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_origin="endoo",
            source_id="endoo-102",
            title="Função 102",
            url="https://vrsoft.endoo.com.br/wiki/artigo/funcao-102",
            markdown="A função 102 permite a entrada do operador no PDV.",
            module="PDV",
            review_status="approved",
            content_hash="endoo-102",
            local_path="conhecimento/PDV/Wiki/funcao-102-endoo.md",
        )
    )
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex", final_text="Resposta sem citar documentação.")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    completed = threading.Event()

    orchestrator.send(
        conversation_id,
        "Para que serve a função 102 no PDV?",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=True,
    )

    assert completed.wait(5)
    assistant = database.messages(conversation_id)[-1]
    with database.connect() as connection:
        total = connection.execute(
            "SELECT count(*) FROM source_citations WHERE message_id=?",
            (assistant["id"],),
        ).fetchone()[0]
    assert total == 0


def test_wiki_route_preserves_relevant_vrwiki_and_endoo_origins(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, legacy_vr_orchestration=False)
    database = MaryDatabase(settings.database_path, root=settings.root)
    for origin, source_id, url in (
        ("vrwiki", "publica-102", "https://wiki.example/102"),
        (
            "endoo",
            "endoo-102",
            "https://vrsoft.endoo.com.br/wiki/artigo/funcao-102",
        ),
    ):
        database.upsert_document(
            KnowledgeDocument(
                source="wiki",
                source_origin=origin,
                source_id=source_id,
                title="Função 102 no PDV",
                url=url,
                markdown="A função 102 permite a entrada do operador no PDV.",
                module="PDV",
                review_status="approved",
                content_hash=source_id,
                local_path=f"conhecimento/PDV/Wiki/{source_id}.md",
            )
        )

    bundle = KnowledgeRouter(database, settings.root).route(
        "Para que serve a função 102 no PDV?"
    )

    assert {item.source_origin for item in bundle.candidates} >= {"vrwiki", "endoo"}
    report = next(item for item in bundle.source_reports if item.source == "wiki")
    assert {item.source_origin for item in report.origin_reports} >= {
        "vrwiki",
        "endoo",
    }
    prompt = KnowledgeRouter(database, settings.root).prompt(bundle)
    assert "Wiki pública VR" in prompt
    assert "Wiki autenticada Endoo" in prompt


@pytest.mark.parametrize(
    ("mode", "difficulty", "expected_effective", "expected_workers"),
    (
        ("off", 5, None, 0),
        ("automatic", 1, "off", 0),
        ("automatic", 3, "standard", 5),
        ("automatic", 4, "ultra", 8),
        ("standard", 4, "standard", 5),
        ("ultra", 1, "ultra", 8),
    ),
)
def test_execution_modes_select_the_expected_effective_flow(
    tmp_path: Path,
    mode: str,
    difficulty: int,
    expected_effective: str | None,
    expected_workers: int,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex", difficulty_level=difficulty)
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            mode=mode,
            model_pool=(ModelRef("codex", "sol", "Sol"),),
        ),
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(conversation_id, "Pedido", callback, use_vr=True)
    assert completed.wait(5)
    worker_calls = [
        item
        for item in provider.sent
        if ":vr:" in item["conversation_id"]
        and "vr_orchestrator_" not in item["conversation_id"]
    ]
    assert len(worker_calls) == expected_workers
    plans = [event for event in events if event.kind == "plan_created"]
    if expected_effective is None:
        assert plans == []
    else:
        assert plans[-1].payload["mode"] == mode
        assert plans[-1].payload["effective_mode"] == expected_effective


def test_orchestrator_is_not_injected_into_an_explicit_worker_pool(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    codex = FakeProvider("codex")
    claude = FakeProvider("claude")
    orchestrator.providers = {"codex": codex, "claude": claude}
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            enabled=True,
            model_pool=(ModelRef("claude", "opus", "Opus"),),
        ),
    )
    completed = threading.Event()
    orchestrator.send(
        conversation_id,
        "Analise",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=True,
    )
    assert completed.wait(5)
    codex_workers = [
        item
        for item in codex.sent
        if ":vr:" in item["conversation_id"]
        and "vr_orchestrator_" not in item["conversation_id"]
    ]
    assert codex_workers == []
    assert any(
        ":vr:" in item["conversation_id"]
        and "vr_orchestrator_" not in item["conversation_id"]
        for item in claude.sent
    )


def test_final_error_is_not_reported_as_orchestration_success(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FinalErrorProvider("codex")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            enabled=True,
            model_pool=(ModelRef("codex", "sol", "Sol"),),
        ),
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(conversation_id, "Falhe", callback, use_vr=True)
    assert completed.wait(5)
    assert any(event.kind == "error" for event in events)
    assert not any(event.kind == "orchestration_completed" for event in events)
    assert database.get_conversation(conversation_id)["status"] == "error"
    delivered = len(events)
    orchestrator._handle_event(RuntimeEvent(conversation_id, "error", "tardia"))
    orchestrator._handle_event(RuntimeEvent(conversation_id, "turn_completed"))
    assert len(events) == delivered
    assert database.get_conversation(conversation_id)["status"] == "error"


def test_ultra_revision_respects_dynamic_count_and_model_flags(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex", divergent=True)
    orchestrator.providers = {"codex": provider}
    pool = (
        ModelRef("codex", "luna", "Luna"),
        ModelRef("codex", "opus", "Opus"),
    )

    def run(dynamic_agent_count: bool) -> list[dict[str, Any]]:
        conversation_id = orchestrator.new_conversation(
            "codex",
            "sol",
            defer_provider_start=True,
            orchestration=OrchestrationOptions(
                enabled=True,
                model_pool=pool,
                ultra=True,
                dynamic_model_routing=False,
                dynamic_agent_count=dynamic_agent_count,
            ),
        )
        completed = threading.Event()
        orchestrator.send(
            conversation_id,
            "Compare profundamente",
            lambda event: completed.set()
            if event.kind == "turn_completed"
            else None,
            use_vr=True,
        )
        assert completed.wait(5)
        return [
            item
            for item in provider.sent
            if item["conversation_id"].startswith(f"{conversation_id}:vr:")
        ]

    static_calls = run(False)
    assert not any("vr_revision" in item["conversation_id"] for item in static_calls)

    dynamic_calls = run(True)
    revision = next(
        item for item in dynamic_calls if "vr_revision" in item["conversation_id"]
    )
    assert revision["model"] == "luna"


def test_codex_process_exit_terminates_registered_async_turn() -> None:
    class DeadProcess:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("fatal\n")

        def wait(self, timeout: float | None = None) -> int:
            return 1

        def poll(self) -> int:
            return 1

    provider = CodexProvider()
    process = DeadProcess()
    events: list[RuntimeEvent] = []
    provider.process = process  # type: ignore[assignment]
    with provider._state_lock:
        provider._callbacks["conversation"] = events.append
        provider._active_turns["conversation"] = "turn"

    provider._read_loop(process)  # type: ignore[arg-type]

    assert [event.kind for event in events] == ["error", "turn_completed"]
    assert provider._active_turns == {}


def test_codex_replacement_drains_state_owned_by_dead_process() -> None:
    class DeadProcess:
        stderr = io.StringIO("fatal\n")

        def poll(self) -> int:
            return 1

    provider = CodexProvider()
    provider.command = "codex"
    process = DeadProcess()
    events: list[RuntimeEvent] = []
    provider.process = process  # type: ignore[assignment]
    with provider._state_lock:
        provider._callbacks["conversation"] = events.append
        provider._active_turns["conversation"] = "turn"

    with patch(
        "vrsoft_extractor.mary.providers.subprocess.Popen",
        side_effect=OSError("spawn failed"),
    ):
        with pytest.raises(OSError, match="spawn failed"):
            provider._ensure_started()

    assert [event.kind for event in events] == ["error", "turn_completed"]
    assert provider._active_turns == {}


def test_claude_rejects_two_concurrent_turns_for_the_same_conversation(
    tmp_path: Path,
) -> None:
    class CompletedProcess:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")

        def wait(self) -> int:
            return 0

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            return None

    provider = ClaudeProvider()
    provider.command = "claude"
    workspace = tmp_path / "work"
    workspace.mkdir()
    native_id = provider.start_conversation(
        "same", "opus", "medium", workspace
    )
    spawn_started = threading.Event()
    allow_spawn = threading.Event()
    first_errors: list[Exception] = []

    def popen(*_args: Any, **_kwargs: Any) -> CompletedProcess:
        spawn_started.set()
        assert allow_spawn.wait(5)
        return CompletedProcess()

    def first_send() -> None:
        try:
            provider.send_message(
                "same",
                native_id,
                "opus",
                "medium",
                workspace,
                "primeira",
                lambda _event: None,
            )
        except Exception as exc:  # pragma: no cover - asserted below
            first_errors.append(exc)

    with patch(
        "vrsoft_extractor.mary.providers.subprocess.Popen", side_effect=popen
    ) as mocked_popen:
        thread = threading.Thread(target=first_send)
        thread.start()
        assert spawn_started.wait(5)
        with pytest.raises(ProviderError, match="Já existe"):
            provider.send_message(
                "same",
                native_id,
                "opus",
                "medium",
                workspace,
                "segunda",
                lambda _event: None,
            )
        allow_spawn.set()
        thread.join(5)
        assert not thread.is_alive()
        assert mocked_popen.call_count == 1
        command = mocked_popen.call_args.args[0]
        assert "--session-id" in command
        assert "--resume" not in command
    assert first_errors == []


@pytest.mark.parametrize("cancel_action", ["close", "release"])
def test_claude_cancellation_revokes_a_blocked_startup(
    tmp_path: Path, cancel_action: str
) -> None:
    class SpawnedProcess:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.terminated = False

        def poll(self) -> int | None:
            return -15 if self.terminated else None

        def terminate(self) -> None:
            self.terminated = True

    provider = ClaudeProvider()
    provider.command = "claude"
    workspace = tmp_path / cancel_action
    workspace.mkdir()
    native_id = provider.start_conversation(
        "same", "opus", "medium", workspace
    )
    spawn_started = threading.Event()
    allow_spawn = threading.Event()
    process = SpawnedProcess()
    errors: list[Exception] = []

    def popen(*_args: Any, **_kwargs: Any) -> SpawnedProcess:
        spawn_started.set()
        assert allow_spawn.wait(5)
        return process

    def send() -> None:
        try:
            provider.send_message(
                "same",
                native_id,
                "opus",
                "medium",
                workspace,
                "mensagem",
                lambda _event: None,
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    with patch(
        "vrsoft_extractor.mary.providers.subprocess.Popen", side_effect=popen
    ):
        thread = threading.Thread(target=send)
        thread.start()
        assert spawn_started.wait(5)
        if cancel_action == "close":
            provider.close()
        else:
            provider.release_conversation("same", native_id)
        allow_spawn.set()
        thread.join(5)

    assert not thread.is_alive()
    assert process.terminated
    assert len(errors) == 1
    assert isinstance(errors[0], ProviderError)
    assert "cancelada" in str(errors[0])
    assert provider._active == {}
    assert provider._starting == {}


def test_interrupt_cancels_blocked_planner_without_timing_sleep(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = BlockingPlannerProvider()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        orchestration=OrchestrationOptions(
            enabled=True,
            model_pool=(ModelRef("codex", "sol", "Sol"),),
        ),
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(conversation_id, "Cancele esta análise", callback, use_vr=True)
    assert provider.planner_started.wait(5), "o planner não iniciou"
    orchestrator.interrupt(conversation_id)
    assert completed.wait(5), "o cancelamento não concluiu"

    assert any(event.kind == "orchestration_cancelled" for event in events)
    assert any(":vr:" in item for item in provider.interrupted)
    assert conversation_id in provider.interrupted
    assert not any(event.kind == "orchestration_completed" for event in events)
    assert database.get_conversation(conversation_id)["status"] == "cancelled"
    assert [(row["role"], row["content"]) for row in database.messages(conversation_id)] == [
        ("user", "Cancele esta análise")
    ]


def test_opencode_verbose_catalog_preserves_qualified_ids_and_variants() -> None:
    output = """opencode/fast-code
{
  "id": "fast-code",
  "providerID": "opencode",
  "name": "Fast Code",
  "status": "active",
  "limit": {"context": 200000},
  "capabilities": {"reasoning": true},
  "variants": {"low": {}, "high": {}}
}
other/retired
{
  "id": "retired",
  "providerID": "other",
  "name": "Retired",
  "status": "deprecated",
  "capabilities": {},
  "variants": {}
}
"""

    assert _parse_opencode_models(output) == [
        {
            "id": "opencode/fast-code",
            "model": "opencode/fast-code",
            "displayName": "Fast Code",
            "description": "Modelo opencode/fast-code disponível no OpenCode.",
            "capabilities": ["coding", "reasoning"],
            "supportedReasoningEfforts": ["low", "high"],
            "_opencodeVariants": ["low", "high"],
            "contextWindow": 200000,
        }
    ]


def test_opencode_permissions_follow_the_selected_approval_profile() -> None:
    supervised = json.loads(
        _opencode_environment("supervised")["OPENCODE_CONFIG_CONTENT"]
    )["permission"]
    automatic = json.loads(
        _opencode_environment("auto")["OPENCODE_CONFIG_CONTENT"]
    )["permission"]
    full_access = json.loads(
        _opencode_environment("full_access")["OPENCODE_CONFIG_CONTENT"]
    )["permission"]

    assert supervised["read"] == "allow"
    assert supervised["*"] == "deny"
    assert "edit" not in supervised
    assert automatic["edit"] == "allow"
    assert automatic["*"] == "deny"
    assert full_access == "allow"


def test_opencode_allows_read_only_external_knowledge_and_keeps_project_tools(
    tmp_path: Path,
) -> None:
    knowledge = (tmp_path / "VR_Mary_V2").resolve()
    knowledge.mkdir()
    permission = json.loads(
        _opencode_environment("auto", knowledge)["OPENCODE_CONFIG_CONTENT"]
    )["permission"]
    normalized_knowledge = str(knowledge).replace("\\", "/")
    pattern = normalized_knowledge + "/**"

    assert permission["external_directory"][pattern] == "allow"
    assert permission["edit"]["*"] == "allow"
    assert permission["edit"][pattern] == "deny"
    assert permission["bash"]["*"] == "allow"
    assert permission["bash"][f"*{normalized_knowledge}*"] == "deny"
    assert any(
        key.endswith("/tools/vr-search.ps1*") and value == "allow"
        for key, value in permission["bash"].items()
    )


def test_conversation_can_bind_to_external_project_without_writing_managed_files(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    assert all(
        provider.knowledge_root == settings.root
        for provider in orchestrator.providers.values()
    )
    orchestrator.providers = {"codex": FakeProvider("codex")}
    project = (tmp_path / "cliente" / "projeto-fiscal").resolve()
    project.mkdir(parents=True)

    conversation_id = orchestrator.new_conversation(
        "codex",
        "sol",
        defer_provider_start=True,
        workspace=project,
    )
    row = database.get_conversation(conversation_id)

    assert row is not None
    assert settings.resolve_path(row["workspace"]) == project
    assert not (project / "AGENTS.md").exists()
    assert not (project / "CLAUDE.md").exists()
    assert str(settings.root) in orchestrator._enrich_prompt("consultar cadastro")

    clone_id = orchestrator.clone(conversation_id, "codex", "sol")
    clone = database.get_conversation(clone_id)
    assert clone is not None
    assert settings.resolve_path(clone["workspace"]) == project


def test_claude_receives_project_and_knowledge_as_distinct_readable_roots(
    tmp_path: Path,
) -> None:
    knowledge = (tmp_path / "VR_Mary_V2").resolve()
    project = (tmp_path / "projeto").resolve()
    knowledge.mkdir()
    project.mkdir()
    provider = ClaudeProvider(knowledge)
    provider.command = "claude"

    with (
        patch(
            "vrsoft_extractor.mary.providers.subprocess.Popen",
            side_effect=OSError("stop after command capture"),
        ) as popen,
        pytest.raises(OSError, match="command capture"),
    ):
            provider.send_message(
                "local",
                "native",
                "sonnet",
                "medium",
                project,
                "pesquise a base",
                lambda _event: None,
                ConversationOptions(vr_enabled=True),
            )

    command = popen.call_args.args[0]
    add_dirs = [command[index + 1] for index, value in enumerate(command) if value == "--add-dir"]
    allowed = command[command.index("--allowedTools") + 1]
    assert str(project) in add_dirs
    assert str(knowledge) in add_dirs
    assert f"Read({knowledge}/**)" in allowed
    assert f"Grep({knowledge}/**)" in allowed
    assert f"Edit({knowledge}/**)" not in allowed
    assert popen.call_args.kwargs["cwd"] == project


def test_claude_native_mode_does_not_inject_vr_permissions_or_knowledge(
    tmp_path: Path,
) -> None:
    knowledge = (tmp_path / "VR_Mary_V2").resolve()
    project = (tmp_path / "projeto").resolve()
    knowledge.mkdir()
    project.mkdir()
    provider = ClaudeProvider(knowledge)
    provider.command = "claude"

    with (
        patch(
            "vrsoft_extractor.mary.providers.subprocess.Popen",
            side_effect=OSError("stop after command capture"),
        ) as popen,
        pytest.raises(OSError, match="command capture"),
    ):
        provider.send_message(
            "local",
            "native",
            "sonnet",
            "medium",
            project,
            "mensagem nativa",
            lambda _event: None,
            ConversationOptions(vr_enabled=False),
        )

    command = popen.call_args.args[0]
    assert command[command.index("-p") + 1] == "mensagem nativa"
    assert "--permission-mode" not in command
    assert "--add-dir" not in command
    assert "--allowedTools" not in command
    assert "--disallowedTools" not in command
    assert str(knowledge) not in command


def test_opencode_native_environment_does_not_expose_knowledge_root(
    tmp_path: Path,
) -> None:
    knowledge = (tmp_path / "VR_Mary_V2").resolve()
    knowledge.mkdir()

    vr_permission = json.loads(
        _opencode_environment("auto", knowledge)["OPENCODE_CONFIG_CONTENT"]
    )["permission"]
    native_permission = json.loads(
        _opencode_environment("auto", None)["OPENCODE_CONFIG_CONTENT"]
    )["permission"]

    normalized = str(knowledge).replace("\\", "/")
    assert f"{normalized}/**" in vr_permission["external_directory"]
    assert "external_directory" not in native_permission
    assert all(normalized not in key for key in native_permission["bash"])


def test_opencode_streams_json_and_announces_native_session(
    tmp_path: Path,
) -> None:
    class InputSink:
        def __init__(self) -> None:
            self.value = ""

        def write(self, value: str) -> int:
            self.value += value
            return len(value)

        def close(self) -> None:
            return None

    class Process:
        def __init__(self) -> None:
            self.stdin = InputSink()
            self.stdout = io.StringIO(
                '\n'.join(
                    (
                        '{"type":"step_start","sessionID":"ses-real","part":{}}',
                        '{"type":"text","sessionID":"ses-real","part":{"text":"OK"}}',
                        '{"type":"step_finish","sessionID":"ses-real","part":{}}',
                    )
                )
                + '\n'
            )
            self.stderr = io.StringIO("")
            self.returncode: int | None = None
            self.terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 1

    provider = OpenCodeProvider()
    provider.command = "opencode"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    native_id = provider.start_conversation(
        "conversation", "opencode/fast-code", "high", workspace
    )
    provider._model_variants = {"opencode/fast-code": {"high"}}
    process = Process()
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    with patch(
        "vrsoft_extractor.mary.providers.subprocess.Popen", return_value=process
    ) as popen:
        provider.send_message(
            "conversation",
            native_id,
            "opencode/fast-code",
            "high",
            workspace,
            "Responda apenas OK",
            callback,
            ConversationOptions(
                model="opencode/fast-code",
                effort="high",
                approval_profile="supervised",
                collaboration_mode="plan",
            ),
        )
        assert completed.wait(5)

    command = popen.call_args.args[0]
    assert command[:3] == ["opencode", "run", "--format"]
    assert command[command.index("--model") + 1] == "opencode/fast-code"
    assert command[command.index("--variant") + 1] == "high"
    assert command[command.index("--agent") + 1] == "plan"
    assert "--session" not in command
    assert process.stdin.value == "Responda apenas OK"
    assert [event.kind for event in events] == [
        "turn_started",
        "native_session_started",
        "assistant_delta",
        "turn_completed",
    ]
    assert events[1].payload["native_id"] == "ses-real"
    assert events[2].text == "OK"


def test_opencode_native_session_event_is_persisted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    conversation_id = orchestrator.new_conversation(
        "opencode", defer_provider_start=True
    )

    orchestrator._handle_event(
        RuntimeEvent(
            conversation_id,
            "native_session_started",
            payload={"native_id": "ses-persisted"},
        )
    )

    assert database.get_conversation(conversation_id)["native_id"] == "ses-persisted"

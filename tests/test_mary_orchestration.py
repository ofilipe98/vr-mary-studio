from __future__ import annotations

import subprocess

import json
import io
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings

from vrsoft_extractor.mary.chat_tools import VR_READ_TOOL_NAME
from vrsoft_extractor.mary.config import MarySettings, load_vr_settings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.knowledge import extract_knowledge_entities
from vrsoft_extractor.mary.knowledge_router import (
    KnowledgeRouter,
    _query_variants,
    should_suggest_vr_flow,
)
from vrsoft_extractor.mary.schema_catalog import parse_schema_markdown
from vrsoft_extractor.mary.schema_sync import SchemaSync
from vrsoft_extractor.mary.models import (
    ConversationOptions,
    KnowledgeDocument,
    ModelRef,
    RuntimeEvent,
)
from vrsoft_extractor.mary.orchestrator import (
    ChatOrchestrator,
    OrchestrationCancelled,
    vr_sessions_note,
)
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


def _settings(tmp_path: Path, **overrides: Any) -> MarySettings:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "mary").resolve(),
        old_root=(tmp_path / "old").resolve(),
        **overrides,
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


def test_expert_profile_preference_migrates_legacy_key_without_rewriting_it(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    preferences = QSettings(
        str(tmp_path / "preferences.ini"),
        QSettings.IniFormat,
    )
    preferences.setValue("research/senior_profile_enabled", True)
    preferences.sync()
    tracked_preferences = MagicMock(wraps=preferences)
    bridge = ChatBridge(settings, database, tracked_preferences)

    try:
        assert bridge.expertProfileEnabled is True
        assert preferences.value("research/expert_profile_enabled", False) is True
        migrated_writes = [
            call.args[0] for call in tracked_preferences.setValue.call_args_list
        ]
        assert "research/expert_profile_enabled" in migrated_writes
        assert "research/senior_profile_enabled" not in migrated_writes

        tracked_preferences.setValue.reset_mock()
        bridge.setExpertProfileEnabled(False)
        bridge.setExpertProfileEnabled(True)
        bridge.setVrResponseMode("support")
        new_writes = [
            call.args[0] for call in tracked_preferences.setValue.call_args_list
        ]
        assert "research/expert_profile_enabled" in new_writes
        assert "research/response_mode" in new_writes
        assert "research/senior_profile_enabled" not in new_writes
        assert preferences.value("research/senior_profile_enabled", False) is True
    finally:
        bridge.close()


def test_chat_bridge_sends_effective_expert_profile_mode(tmp_path: Path) -> None:
    cases = (
        (False, "support", "vr", "auto"),
        (True, "auto", "vr", "adaptive"),
        (True, "training", "vr", "training"),
        (True, "support", "ultra", "support"),
        (True, "implementation", "ultra", "implementation"),
        (True, "support", "off", "auto"),
    )

    for index, (enabled, response_mode, vr_mode, expected) in enumerate(cases):
        case_root = tmp_path / f"profile-{index}"
        settings = _settings(case_root)
        database = MaryDatabase(settings.database_path, root=settings.root)
        conversation_id = database.create_conversation(
            f"Perfil {index}",
            "codex",
            "sol",
            settings.root,
            vr_enabled=vr_mode != "off",
            vr_mode=vr_mode,
        )
        preferences = QSettings(
            str(case_root / "preferences.ini"),
            QSettings.IniFormat,
        )
        preferences.setValue("chat/vr_mode", vr_mode)
        preferences.setValue("research/expert_profile_enabled", enabled)
        preferences.setValue("research/response_mode", response_mode)
        preferences.sync()
        bridge = ChatBridge(settings, database, preferences)
        bridge.selectConversationId(conversation_id)

        try:
            with patch.object(bridge._orchestrator, "send") as send_mock:
                assert bridge.sendMessage(f"Pergunta do perfil {index}") is True
            assert send_mock.call_args.kwargs["response_mode"] == expected
            assert send_mock.call_args.args[6] is (vr_mode != "off")
            if enabled and response_mode == "auto" and vr_mode != "off":
                assert preferences.value("research/response_mode") == "auto"
        finally:
            bridge.close()


@pytest.mark.parametrize("provider_name", ("codex", "opencode"))
def test_vr_on_direct_adds_identity_and_local_base(
    tmp_path: Path,
    provider_name: str,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider(provider_name)
    orchestrator.providers = {provider_name: provider}
    conversation_id = orchestrator.new_conversation(
        provider_name,
        "sol",
        defer_provider_start=True,
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
    assert "Contrato de acesso tool-driven do modo VR" in prompt
    assert "CONSULTA SOB DEMANDA" in prompt
    assert "CONTEXTO LOCAL VR RECUPERADO" not in prompt
    assert "vr_sources" in prompt
    assert "vr_search" in prompt
    assert "vr_read" in prompt
    if provider_name == "codex":
        # Native dynamic tools keep the folder path and the script out of the
        # prompt; providers without that cycle keep the folder/script fallback.
        assert str(settings.root) not in prompt
        assert "vr-search.ps1" not in prompt
    else:
        assert str(settings.root) in prompt
    assert provider.sent[0]["options"].vr_enabled is True
    assert provider.start_options[0].vr_enabled is True
    assert not any(":vr:" in item["conversation_id"] for item in provider.sent)
    assert database.messages(conversation_id)[-1]["response_mode"] == "vr"


def test_changing_vr_mode_preserves_a_native_session_per_mode(
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
    database.update_conversation(conversation_id, native_id_vr="native-vr", native_tools_id_vr="native-vr")

    orchestrator.update_vr_mode(conversation_id, False)

    row = database.get_conversation(conversation_id)
    assert row["vr_enabled"] == 0
    assert row["native_id_vr"] == "native-vr"
    assert provider.released == []

    completed = threading.Event()
    orchestrator.send(
        conversation_id,
        "Primeira pergunta nativa",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=False,
    )
    assert completed.wait(5)

    row = database.get_conversation(conversation_id)
    assert row["native_id"].startswith("native:")
    assert row["native_id_vr"] == "native-vr"

    orchestrator.update_vr_mode(conversation_id, True)
    completed.clear()
    orchestrator.send(
        conversation_id,
        "De volta ao VR",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=True,
    )
    assert completed.wait(5)

    row = database.get_conversation(conversation_id)
    assert row["native_id_vr"] == "native-vr"
    assert provider.sent[0]["native_id"].startswith("native:")
    assert provider.sent[-1]["native_id"] == "native-vr"


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


def test_product_name_does_not_run_before_the_business_topic(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    profile = KnowledgeRouter(database, settings.root).classify(
        "Quero um fluxo completo de crossdocking no VRMaster"
    )

    variants = _query_variants(profile)

    assert profile.terms == ("fluxo", "crossdocking")
    assert variants[0].casefold() != "vrmaster"
    assert variants[:2] == ("cross docking", "crossdocking")


def test_joined_business_term_matches_the_spaced_manual_spelling(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="cross-docking-manual",
            title="Manual Administrativo Compra Pedido",
            url="https://wiki.example/cross-docking",
            markdown=(
                "# Cross Docking\n\nA mercadoria recebida é transferida diretamente "
                "para o ponto de entrega. O pedido de compra define as lojas destino."
            ),
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="cross-docking-manual",
            local_path="conhecimento/ADM_FIN_ESTOQUE/Wiki/cross-docking.md",
        )
    )
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="wms-cross-docking",
            title="Manual VR WMS Cross-Docking",
            url="https://wiki.example/wms-cross-docking",
            markdown="O Cross-Docking no WMS controla a lacração do estoque.",
            module="ADM_FIN_ESTOQUE",
            review_status="approved",
            content_hash="wms-cross-docking",
            local_path="conhecimento/ADM_FIN_ESTOQUE/Wiki/wms-cross-docking.md",
        )
    )
    for index in range(5):
        database.upsert_document(
            KnowledgeDocument(
                source="wiki",
                source_id=f"fluxo-generico-{index}",
                title=f"Fluxo genérico {index}",
                url=f"https://wiki.example/fluxo-{index}",
                markdown="Este documento descreve outro fluxo do sistema.",
                module="PDV",
                review_status="approved",
                content_hash=f"fluxo-generico-{index}",
                local_path=f"conhecimento/PDV/Wiki/fluxo-{index}.md",
            )
        )

    bundle = KnowledgeRouter(database, settings.root).route(
        "Quero um fluxo completo de crossdocking no VRMaster"
    )

    assert bundle.candidates[0].source_id == "cross-docking-manual"
    assert bundle.selected_modules == ("ADM_FIN_ESTOQUE",)


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


def _forbid_automatic_retrieval(orchestrator: ChatOrchestrator) -> None:
    service = orchestrator.retrieval_service

    def blocked(*_args, **_kwargs):
        raise AssertionError("retrieval automático não deveria rodar")

    service.route = blocked
    service.route_source = blocked
    service.route_code_source = blocked
    service.route_vr_sources = blocked


class ToolCallingVrProvider(FakeProvider):
    """VR provider that calls vr_search before answering the turn."""

    def __init__(self, final_text: str, query: str) -> None:
        super().__init__("codex", final_text=final_text)
        self.query = query
        self.tool_finished = threading.Event()

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
        callback(
            RuntimeEvent(
                conversation_id,
                "dynamic_tool_requested",
                "vr_search",
                {
                    "tool": "vr_search",
                    "request_id": "req-search-1",
                    "arguments": {"query": self.query},
                },
            )
        )
        assert self.tool_finished.wait(10), "vr_search não respondeu"
        callback(RuntimeEvent(conversation_id, "assistant_delta", self.final_text))
        callback(
            RuntimeEvent(
                conversation_id,
                "turn_completed",
                payload={"turn": {"id": f"turn:{conversation_id}"}},
            )
        )


def test_vr_tool_evidence_feeds_validation_and_citations(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
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
    provider = ToolCallingVrProvider(
        final_text="Fonte: https://wiki.example/102", query="função 102 PDV"
    )
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    _forbid_automatic_retrieval(orchestrator)
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "tool_event":
            provider.tool_finished.set()
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(
        conversation_id,
        "Para que serve a função 102 no PDV?",
        callback,
        use_vr=True,
    )

    assert completed.wait(10)
    kinds = [event.kind for event in events]
    assert "knowledge_routed" not in kinds
    assert "research_started" not in kinds
    assert "agent_started" not in kinds
    tool_events = [event for event in events if event.kind == "tool_event"]
    assert tool_events and tool_events[0].payload["success"] is True
    payload = json.loads(str(tool_events[0].payload["output"]))
    assert payload["source_states"]["wiki"] == "available"
    response_plans = [
        event for event in events if event.kind == "response_plan_created"
    ]
    assert len(response_plans) == 1
    assert len(response_plans[0].payload["steps"]) == 5
    assistant = database.messages(conversation_id)[-1]
    assert assistant["response_mode"] == "vr"
    with database.connect() as connection:
        citations = connection.execute(
            "SELECT * FROM source_citations WHERE message_id=?",
            (assistant["id"],),
        ).fetchall()
    assert len(citations) == 1
    assert "entrada do operador" in citations[0]["excerpt"]


def test_vr_turn_without_tool_does_not_retrieve(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
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
    provider = FakeProvider("codex", final_text="Resposta direta sem consultar a base.")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=True
    )
    _forbid_automatic_retrieval(orchestrator)
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    with patch.object(
        database, "search", side_effect=AssertionError("sem retrieval automático")
    ):
        orchestrator.send(
            conversation_id,
            "Qual a capital da França?",
            callback,
            use_vr=True,
        )
        assert completed.wait(5)

    assert not any(event.kind == "knowledge_routed" for event in events)
    assert not any(event.kind == "tool_event" for event in events)
    assistant = database.messages(conversation_id)[-1]
    assert assistant["response_mode"] == "vr"
    assert assistant["content"] == "Resposta direta sem consultar a base."
    with database.connect() as connection:
        total = connection.execute(
            "SELECT count(*) FROM source_citations WHERE message_id=?",
            (assistant["id"],),
        ).fetchone()[0]
    assert total == 0


def test_direct_vr_does_not_persist_candidates_not_cited_by_the_answer(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
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
    settings = _settings(tmp_path)
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


def test_disabled_endoo_keeps_legacy_route_off_and_ultra_wiki_on(
    tmp_path: Path,
) -> None:
    from vrsoft_extractor.mary.retrieval import RetrievalService

    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    for origin, source_id in (
        ("vrwiki", "publica-102"),
        ("endoo", "endoo-102"),
    ):
        database.upsert_document(
            KnowledgeDocument(
                source="wiki",
                source_origin=origin,
                source_id=source_id,
                title="Função 102 no PDV",
                url=f"https://wiki.example/{source_id}",
                markdown="A função 102 permite a entrada do operador no PDV.",
                module="PDV",
                review_status="approved",
                content_hash=source_id,
                local_path=f"conhecimento/PDV/Wiki/{source_id}.md",
            )
        )
    service = RetrievalService(
        KnowledgeRouter(
            database,
            settings.root,
            disabled_origins=("endoo",),
        )
    )

    legacy = service.route("Para que serve a função 102 no PDV?")
    assert not any(item.source_origin == "endoo" for item in legacy.candidates)
    assert "endoo" not in service.enabled_origins("wiki")

    ultra = service.route_source("Para que serve a função 102 no PDV?", "wiki")
    assert {item.source_origin for item in ultra.candidates} == {
        "vrwiki",
        "endoo",
    }
    report = ultra.source_report("wiki")
    assert report is not None
    assert {item.source_origin for item in report.origin_reports} == {
        "vrwiki",
        "endoo",
    }
    assert all(item.status == "found" for item in report.origin_reports)


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


def test_claude_native_mode_exposes_knowledge_through_mcp_only(
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
            ConversationOptions(vr_enabled=False, approval_profile="supervised"),
        )

    command = popen.call_args.args[0]
    assert "mensagem nativa" not in command
    assert popen.call_args.kwargs["stdin"] == subprocess.PIPE
    assert "--permission-mode" not in command
    assert "--add-dir" not in command
    assert command[command.index("--allowedTools") + 1] == "mcp__vr-mary-studio__*"
    assert "--disallowedTools" not in command
    mcp = json.loads(command[command.index("--mcp-config") + 1])["mcpServers"]
    assert "vr-mary-studio" in mcp
    assert str(knowledge) in mcp["vr-mary-studio"]["args"]


@pytest.mark.parametrize(
    ("profile", "expected_mode"),
    [
        ("supervised", None),
        ("auto_edits", "acceptEdits"),
        ("auto", "acceptEdits"),
        ("full_access", "bypassPermissions"),
    ],
)
def test_claude_native_turn_honours_approval_profile(
    tmp_path: Path,
    profile: str,
    expected_mode: str | None,
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
            ConversationOptions(vr_enabled=False, approval_profile=profile),
        )

    command = popen.call_args.args[0]
    if expected_mode is None:
        assert "--permission-mode" not in command
    else:
        assert command[command.index("--permission-mode") + 1] == expected_mode
    assert command[command.index("--allowedTools") + 1] == "mcp__vr-mary-studio__*"
    assert "--disallowedTools" not in command
    mcp = json.loads(command[command.index("--mcp-config") + 1])["mcpServers"]
    assert str(knowledge) in mcp["vr-mary-studio"]["args"]
    assert popen.call_args.kwargs["cwd"] == project


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
                        '{"type":"reasoning","sessionID":"ses-real","part":{"text":"Checking evidence"}}',
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
        "reasoning_delta",
        "assistant_delta",
        "turn_completed",
    ]
    assert events[1].payload["native_id"] == "ses-real"
    assert events[2].text == "Checking evidence"
    assert events[3].text == "OK"


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


def test_commentary_is_persisted_but_excluded_from_final_answer_buffer(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )

    orchestrator._handle_event(
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "Vou inspecionar os arquivos.",
            {"itemId": "commentary-1", "phase": "commentary"},
        )
    )
    orchestrator._handle_event(
        RuntimeEvent(
            conversation_id,
            "assistant_delta",
            "A correção foi concluída.",
            {"itemId": "final-1", "phase": "final_answer"},
        )
    )

    assert orchestrator._assistant_buffers[conversation_id] == [
        "A correção foi concluída."
    ]
    rows = database.latest_turn_events(conversation_id)
    assert [str(row["text"]) for row in rows] == [
        "Vou inspecionar os arquivos.",
        "A correção foi concluída.",
    ]


@pytest.mark.parametrize(
    ("use_vr", "expected_text"),
    [
        (False, "Execução interrompida."),
        (True, "Execução VR interrompida."),
    ],
)
def test_cancellation_message_reflects_response_mode(
    tmp_path: Path, use_vr: bool, expected_text: str
) -> None:
    class CancellingProvider(FakeProvider):
        def send_message(self, *args, **kwargs) -> None:
            raise OrchestrationCancelled(str(args[0] if args else ""))

    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    orchestrator.providers = {"codex": CancellingProvider("codex")}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(conversation_id, "Olá", callback, use_vr=use_vr)

    assert completed.wait(5)
    cancelled = [
        event for event in events if event.kind == "orchestration_cancelled"
    ]
    assert [event.text for event in cancelled] == [expected_text]


def test_empty_provider_answer_warns_instead_of_disappearing(tmp_path: Path) -> None:
    class EmptyProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__("codex", final_text="")

    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    orchestrator.providers = {"codex": EmptyProvider()}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(
        conversation_id, "Pergunta sem resposta", callback, use_vr=False
    )

    assert completed.wait(5)
    warnings = [event for event in events if event.kind == "response_empty"]
    assert len(warnings) == 1
    assert "sem retornar conteúdo" in warnings[0].text
    assert [
        (row["role"], row["content"]) for row in database.messages(conversation_id)
    ] == [("user", "Pergunta sem resposta")]
    with database.connect() as connection:
        persisted = connection.execute(
            "SELECT text FROM runtime_events "
            "WHERE conversation_id=? AND kind='response_empty'",
            (conversation_id,),
        ).fetchall()
    assert ["sem retornar conteúdo" in row["text"] for row in persisted] == [True]


def test_context_transfer_is_announced_when_session_starts_with_history(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    codex = FakeProvider("codex")
    orchestrator.providers = {"codex": codex}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    database.add_message(conversation_id, "user", "Primeira dúvida")
    database.add_message(conversation_id, "assistant", "Primeira resposta")

    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(
        conversation_id, "Continue de onde paramos", callback, use_vr=False
    )

    assert completed.wait(5)
    transfers = [event for event in events if event.kind == "context_transferred"]
    assert len(transfers) == 1
    assert "2 mensagens" in transfers[0].text
    assert transfers[0].payload["provider"] == "codex"
    sent_message = codex.sent[-1]["message"]
    assert "CONTEXTO TRANSFERIDO DE OUTRO PROVEDOR" in sent_message
    assert sent_message.rstrip().endswith("Continue de onde paramos")


def _tool_names(options: ConversationOptions | None) -> set[str]:
    return {
        str(tool.get("name") or "")
        for tool in (options.dynamic_tools if options else ())
    }


def test_off_turn_registers_all_local_tools(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    completed = threading.Event()

    orchestrator.send(
        conversation_id,
        "Pergunta nativa com acesso local sob demanda",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=False,
    )
    assert completed.wait(5)

    assert {"vr_sources", "vr_search", "vr_read"} <= _tool_names(
        provider.start_options[0]
    )
    assert {"vr_sources", "vr_search", "vr_read"} <= _tool_names(
        provider.sent[0]["options"]
    )
    assert len(provider.sent) == 1


def test_legacy_vr_native_search_env_does_not_remove_off_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VR_NATIVE_SEARCH_ENABLED", "0")
    app_dir = (tmp_path / "app").resolve()
    app_dir.mkdir(parents=True)
    settings = load_vr_settings(
        app_dir=app_dir,
        root=(tmp_path / "mary").resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.old_root.mkdir(parents=True)
    settings.ensure_dirs()
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    completed = threading.Event()

    orchestrator.send(
        conversation_id,
        "Pergunta nativa com a variável legada desligada",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=False,
    )
    assert completed.wait(5)

    assert {"vr_sources", "vr_search", "vr_read"} <= _tool_names(
        provider.start_options[0]
    )
    assert {"vr_sources", "vr_search", "vr_read"} <= _tool_names(
        provider.sent[0]["options"]
    )


def test_off_turn_registers_local_tools_for_provider_decided_calls(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex")
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    completed = threading.Event()

    orchestrator.send(
        conversation_id,
        "Pergunta nativa com busca sob demanda",
        lambda event: completed.set() if event.kind == "turn_completed" else None,
        use_vr=False,
    )
    assert completed.wait(5)

    assert "vr_search" in _tool_names(provider.start_options[0])
    assert "vr_search" in _tool_names(provider.sent[0]["options"])
    assert database.messages(conversation_id)[-1]["response_mode"] == "native"


class ToolCallingProvider(FakeProvider):
    """Native provider that decides to call vr_search mid-turn."""

    def __init__(self) -> None:
        super().__init__("codex", final_text="Resposta com evidência local.")

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
        callback(
            RuntimeEvent(
                conversation_id,
                "dynamic_tool_requested",
                "vr_search",
                {
                    "tool": "vr_search",
                    "request_id": "req-vr-search-1",
                    "arguments": {"query": "sped fiscal"},
                },
            )
        )
        callback(RuntimeEvent(conversation_id, "assistant_delta", self.final_text))
        callback(
            RuntimeEvent(
                conversation_id,
                "turn_completed",
                payload={"turn": {"id": f"turn:{conversation_id}"}},
            )
        )


def test_off_turn_answers_vr_search_without_vr_pipeline(tmp_path: Path) -> None:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "mary").resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.app_dir.mkdir(parents=True)
    settings.old_root.mkdir(parents=True)
    settings.ensure_dirs()
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    orchestrator.providers = {"codex": ToolCallingProvider()}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if event.kind == "turn_completed":
            completed.set()

    orchestrator.send(
        conversation_id,
        "Onde o SPED grava as notas?",
        callback,
        use_vr=False,
    )

    assert completed.wait(5)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(
        event.kind == "tool_event" for event in events
    ):
        time.sleep(0.05)
    tool_events = [event for event in events if event.kind == "tool_event"]
    assert len(tool_events) == 1
    assert tool_events[0].payload["success"] is True
    payload = json.loads(str(tool_events[0].payload["output"]))
    assert payload["query"] == "sped fiscal"
    assert payload["total"] == 0
    # The upfront VR pipeline must stay out of native turns.
    assert not any(event.kind == "knowledge_routed" for event in events)
    assert not any(event.kind == "intent_analysis_started" for event in events)
    orchestrator.drain_turn_finalizations()
    assert database.messages(conversation_id)[-1]["response_mode"] == "native"
    assert conversation_id not in orchestrator._external_callbacks
    assert conversation_id not in orchestrator._callback_generations
    assert not orchestrator._dynamic_tool_callbacks
    assert not hasattr(orchestrator, "_turn_tool_calls")
    assert not hasattr(orchestrator, "_turn_monitor_output_chars")
    orchestrator.close()


def test_resume_research_reuses_run_without_budget_concept(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    bridge = ChatBridge(
        settings,
        database,
        QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat),
    )
    conversation_id = bridge._orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_mode="ultra"
    )
    run_id = "resume-run"
    bridge._orchestrator.research_repository.create_run(
        run_id,
        conversation_id,
        {},
        "pergunta original",
        {},
    )
    bridge._orchestrator.research_repository.update_run_status(run_id, "cancelled")
    bridge._selected = {"conversationId": conversation_id}
    with patch.object(bridge, "_send_message") as send:
        bridge.resumeResearch()
    send.assert_called_once_with(
        "pergunta original", resume_run_id=run_id
    )
    assert bridge.resumableResearch["run_id"] == run_id
    assert "grant_budget" not in send.call_args.kwargs
    bridge.close()


def test_monitor_and_vr_tools_share_no_turn_output_counter(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)

    class Provider:
        def available(self):
            return True

        def close(self):
            return None

    class Service:
        def read(self, reference, *, cursor, limit, **scope):
            return {
                "state": "available",
                "reference": reference,
                "content": "v" * limit,
                "cursor": cursor,
                "limit": limit,
                "has_more": True,
                "next_cursor": cursor + limit,
            }

    class Monitor:
        def execute(self, tool_name, arguments, conversation_id):
            class Result:
                text = "m" * 5000
                parsed = {"data": "m" * 5000}

                def content_items(self):
                    return [{"type": "inputText", "text": self.text}]

            return Result()

    orchestrator.providers = {"codex": Provider()}
    orchestrator.retrieval_service = Service()
    orchestrator._monitor_adapter = Monitor()
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=False
    )
    orchestrator._pending_user_messages[conversation_id] = 1
    orchestrator._turn_access_paths[conversation_id] = ""
    events: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event: RuntimeEvent) -> None:
        events.append(event)
        if len(events) == 50:
            completed.set()

    orchestrator._external_callbacks[conversation_id] = callback
    for index in range(50):
        event = RuntimeEvent(
            conversation_id,
            "dynamic_tool_requested",
            "tool",
            {
                "request_id": f"request-{index}",
                "arguments": {"reference": "example.Fiscal"} if index % 2 else {},
            },
        )
        if index % 2:
            orchestrator._execute_vr_native_tool(event, VR_READ_TOOL_NAME)
        else:
            orchestrator._execute_monitor_tool(event, "get_connections")
    assert completed.wait(5)
    assert all(event.payload["success"] is True for event in events)
    assert sum(len(str(event.payload["output"])) for event in events) > 192_000
    assert not hasattr(orchestrator, "_turn_tool_calls")
    assert not hasattr(orchestrator, "_turn_monitor_output_chars")
    orchestrator.close()


def test_vr_sessions_note_covers_slot_combinations() -> None:
    assert vr_sessions_note("", "") == ""
    assert vr_sessions_note("native:x", "") == (
        "Somente o thread nativo foi criado nesta conversa."
    )
    assert vr_sessions_note("", "native:v") == (
        "Somente o thread VR foi criado nesta conversa."
    )
    assert vr_sessions_note("native:x", "native:v") == (
        "Threads nativo e VR ativos nesta conversa."
    )


def test_should_suggest_vr_flow_targets_erp_questions(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    router = KnowledgeRouter(database, settings.root)

    process_question = router.classify(
        "Como fazer o passo a passo para gerar o SPED fiscal?"
    )
    schema_question = router.classify(
        "Em qual tabela e coluna os dados sao gravados da nfce?"
    )
    product_mention = router.classify("Explique como funciona o VRMaster")
    two_term_hint = router.classify("Preciso ajustar o cadastro de produto")
    single_weak_hint = router.classify("Me ajuda com estoque?")
    generic = router.classify("Qual a capital da França?")

    assert should_suggest_vr_flow(process_question) is True
    assert should_suggest_vr_flow(schema_question) is True
    assert should_suggest_vr_flow(product_mention) is True
    assert should_suggest_vr_flow(two_term_hint) is True
    # Errs toward omission on weak or generic signals.
    assert should_suggest_vr_flow(single_weak_hint) is False
    assert should_suggest_vr_flow(generic) is False


def test_finalizer_waits_for_running_dynamic_tool_past_old_short_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    import vrsoft_extractor.mary.orchestrator as orchestrator_module
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True
    )
    owner = database.begin_user_turn(conversation_id, "pergunta")
    orchestrator._pending_user_messages[conversation_id] = owner
    orchestrator._callback_generations[conversation_id] = 1
    orchestrator._dynamic_tool_callbacks[(conversation_id, "tool-1")] = (
        1,
        lambda event: None,
    )
    clock_calls = 0
    real_monotonic = time.monotonic

    def logical_clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 6.0 if clock_calls > 1 else 0.0

    monkeypatch.setattr(orchestrator_module.time, "monotonic", logical_clock)
    finished = threading.Event()
    event = RuntimeEvent(
        conversation_id,
        "turn_completed",
        payload={"_owner_generation": 1, "_owner_message": owner},
    )

    def finalize() -> None:
        orchestrator._finalize_turn_completed(event, "", False, "", "", None)
        finished.set()

    thread = threading.Thread(target=finalize)
    thread.start()
    assert not finished.wait(0.02)
    with orchestrator._agent_run_lock:
        orchestrator._dynamic_tool_callbacks.pop((conversation_id, "tool-1"), None)
    assert finished.wait(2)
    thread.join(2)
    assert not thread.is_alive()
    monkeypatch.setattr(orchestrator_module.time, "monotonic", real_monotonic)
    orchestrator.close()

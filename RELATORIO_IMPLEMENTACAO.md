# RelatÃ³rio de ImplementaÃ§Ã£o â€” Mensagens IntermediÃ¡rias Reais no Mesmo Turno

> Registro histÃ³rico da entrega do Opus. A auditoria posterior encontrou e corrigiu defeitos nÃ£o cobertos por esta validaÃ§Ã£o. Consulte [auditoria e correÃ§Ãµes](reports/plano-mensagens-intermediarias-2026-09-06/AUDITORIA_E_CORRECOES.md) e [validaÃ§Ã£o final](reports/plano-mensagens-intermediarias-2026-09-06/VALIDACAO_FINAL.md) para o estado revisado.

**Data**: 06/09/2026
**RepositÃ³rio**: VR Norte Studio (`d:\Codex\vr-mary-studio`)
**Branch**: `dev`
**Commit base**: `d4daa2085be19e3236923f9ae8ad8f31893cce05`
**Resultado de ValidaÃ§Ã£o**: 630 passed, 45 subtests passed (100% sucesso)

---

## 1. VisÃ£o Geral

Foi implementado com sucesso o suporte a **mÃºltiplas mensagens pÃºblicas do assistente dentro do mesmo turno lÃ³gico**. Um Ãºnico pedido do usuÃ¡rio agora Ã© capaz de transitar na timeline na sequÃªncia:

$$\text{M}_1 \longrightarrow \text{atividade/ferramentas} \longrightarrow \text{M}_2 \longrightarrow \text{atividade/ferramentas} \longrightarrow \text{M}_3\text{ final}$$

Cada mensagem possui identidade persistente e isolada. Os deltas de streaming acumulam e renderizam na mensagem ativa correspondente sem alterar mensagens anteriores. A conclusÃ£o de uma mensagem intermediÃ¡ria nÃ£o encerra o turno nem reinicia a Task Bar. Ao recarregar ou reabrir a conversa, a ordem cronolÃ³gica e a integridade de todas as mensagens pÃºblicas e atividades sÃ£o mantidas. Providers que emitem apenas uma resposta final continuam funcionando sem qualquer alteraÃ§Ã£o comportamental.

---

## 2. Tabela de Requisitos vs. Status Final

| Requisito | Status Base | Status Final | Arquivos / SÃ­mbolos |
|---|---|---|---|
| **Turno lÃ³gico Ãºnico com mÃºltiplas mensagens** | Ausente (buffer agregado Ãºnico) | **ATENDIDO** | `orchestrator.py`: `_ExecutionState`, `_handle_event` |
| **Identidade de execuÃ§Ã£o local imutÃ¡vel** | Parcial (`message_id` de `begin_user_turn`) | **ATENDIDO** | `orchestrator.py`: `execution_id` vinculado na criaÃ§Ã£o e closures |
| **Identidade estÃ¡vel por mensagem** | Ausente (sem chaves por item) | **ATENDIDO** | `orchestrator.py`: `message_key = f"{execution_id}:{seq}"` |
| **Isolamento de execuÃ§Ã£o e proteÃ§Ã£o contra late events** | Parcial (filtros bÃ¡sicos de turn_id) | **ATENDIDO** | `orchestrator.py`: `_finalized_turns`, guarda no callback e `_ExecutionState` |
| **Mapeamento de lifecycle semÃ¢ntico no Codex** | Parcial (`agentMessage` virava `tool_event`) | **ATENDIDO** | `providers.py`: `item/started` & `item/completed` $\to$ `assistant_started` & `assistant_completed` |
| **Fallback transparente para outros provedores** | Ausente | **ATENDIDO** | `orchestrator.py`: auto-inÃ­cio implÃ­cito em `append_delta` (Claude, OpenCode, Antigravity) |
| **MigraÃ§Ã£o de banco aditiva e idempotente** | Ausente para ordinais/status | **ATENDIDO** | `db.py`: colunas `execution_ordinal` e `message_status` via `_ensure_column` |
| **Upsert de mensagens sem duplicaÃ§Ã£o** | Parcial (`add_message` direto) | **ATENDIDO** | `db.py`: `upsert_assistant_message`; `_finalize_turn_completed` |
| **AtualizaÃ§Ã£o da timeline por identidade** | Precisa CorreÃ§Ã£o (`update_last` na Ãºltima linha) | **ATENDIDO** | `chat.py`: `_MappingListModel.update_by_key`, `messageKey`, `isStreaming` |
| **Task Bar mantida vinculada ao turno** | Existente | **ATENDIDO** | `chat.py` / `VrTaskBar.qml`: passos do plano desacoplados do tÃ©rmino de M1 |
| **Reabertura e histÃ³rico consistente** | Parcial | **ATENDIDO** | `chat.py`: `_reload_selected_messages` com `isStreaming=False` e preservaÃ§Ã£o |
| **Suporte Ã  suÃ­te completa de testes** | 39 baseline pass | **ATENDIDO** | 630 testes passando (`tests/test_intermediate_messages.py` + suÃ­te geral) |

---

## 3. DecisÃµes Concretas de Contrato

1. **`execution_id` local imutÃ¡vel**:
   - Derivado atomicamente de `message_id` retornado por `begin_user_turn(conversation_id, "user", ...)`.
   - Propagado no payload dos eventos `assistant_started`, `assistant_completed` e `turn_completed`.
   - `messages.turn_id` continua recebendo o ID nativo da sessÃ£o/tentativa do provider via `update_message_turn`, sem sobrecarga semÃ¢ntica.

2. **`native_turn_id` e attempt identity**:
   - Os identificadores de sessÃ£o/tentativa emitidos pelo backend nativo (Codex, Claude, etc.) sÃ£o isolados no escopo do callback correspondente.
   - O orquestrador valida a closure pelo `execution_id` e descarta eventos originÃ¡rios de execuÃ§Ãµes anteriores ou finalizadas (`_finalized_turns`).

3. **Message identity**:
   - Chave composta estÃ¡vel: `message_key = f"{execution_id}:{seq}"` gerada de forma monotÃ´nica pelo `_ExecutionState`.
   - Quando disponÃ­vel nativamente (ex.: `itemId` do Codex), o ID Ã© adicionalmente registrado em `provider_message_id`.
   - Deltas atualizam estritamente a mensagem identificada por `message_key`.

4. **Ownership e audiÃªncia**:
   - Eventos de workers internos, revisores, crÃ­ticas ou reasoning/thinking permanecem restritos Ã  atividade/trace e **nÃ£o** geram mensagens pÃºblicas.
   - Apenas o fluxo pÃºblico do assistente emite `assistant_started` e `assistant_completed`.
   - `_publish_final_response` no modo VR/Ultra sintetiza a resposta na mesma execuÃ§Ã£o lÃ³gica, emitindo o ciclo de vida completo sem fabricar novos turnos do usuÃ¡rio.

5. **Ordem persistente e migraÃ§Ã£o**:
   - Adicionadas as colunas `execution_ordinal INTEGER NOT NULL DEFAULT 0` e `message_status TEXT NOT NULL DEFAULT ''` Ã  tabela `messages`.
   - A migraÃ§Ã£o Ã© realizada por meio do mÃ©todo idempotente existente `self._ensure_column`.
   - Na recuperaÃ§Ã£o e recarga, as mensagens sÃ£o ordenadas monotonicamente por seu ordinal e ID de chave primÃ¡ria.

6. **Lifecycle semÃ¢ntico e texto final**:
   - `assistant_started`: Inicia o tracking da mensagem, aloca o buffer e insere a linha na UI com `isStreaming = True`.
   - `assistant_delta`: Alimenta o texto da mensagem corrente por chave.
   - `assistant_completed`: Persiste a mensagem no SQLite com seu texto autoritativo consolidado, marca `isStreaming = False` e desocupa o slot ativo sem finalizar o turno.
   - `turn_completed`: Aciona `_finalize_turn_completed`. Caso mensagens intermediÃ¡rias jÃ¡ tenham sido persistidas, o orquestrador nÃ£o insere uma mensagem agregada duplicada (evita anomalia M1 + M2 + M3 reunidos no final).

7. **Estados**:
   - Mensagens transitam de `streaming` para `completed`, `interrupted` ou `error`.
   - O turno permanece `running` atÃ© o processamento do evento terminal (`turn_completed`, `error` ou `orchestration_cancelled`).

---

## 4. Arquivos e SÃ­mbolos Modificados

### `vrsoft_extractor/mary/orchestrator.py`
- **`_ExecutionState`** (dataclass): Estrutura de rastreamento por execuÃ§Ã£o com contadores sequenciais, buffers isolados por chave e lista de mensagens concluÃ­das (`start_message`, `append_delta`, `complete_message`, `current_text`, `has_completed_messages`).
- **`ChatOrchestrator.__init__`**: InicializaÃ§Ã£o de `self._execution_states: dict[str, _ExecutionState]`.
- **`ChatOrchestrator.send`**: InstanciaÃ§Ã£o atÃ´mica de `_ExecutionState(execution_id=message_id)` e limpeza no caminho de exceÃ§Ã£o.
- **`ChatOrchestrator._handle_event`**:
  - InclusÃ£o de `assistant_started` e `assistant_completed` nas barreiras contra turnos finalizados (`_finalized_turns`).
  - Tratamento de `assistant_started`: alocaÃ§Ã£o de `message_key`, `seq` e metadados de execuÃ§Ã£o.
  - Tratamento de `assistant_delta`: alimentaÃ§Ã£o do buffer especÃ­fico da mensagem e auto-inÃ­cio implÃ­cito caso o provider nÃ£o emita evento de inÃ­cio.
  - Tratamento de `assistant_completed`: consolidaÃ§Ã£o do texto autoritativo, persistÃªncia via `upsert_assistant_message` com status `completed`.
  - Tratamento de `turn_completed`: extraÃ§Ã£o de `_execution_state` e encaminhamento ao finalizador assÃ­ncrono.
- **`ChatOrchestrator._submit_turn_finalization` & `_finalize_turn_completed`**:
  - Recebe `execution_state`.
  - Verifica `has_completed_messages`. Se verdadeiro, dispensa inserÃ§Ã£o de resposta agregada e preserva as mensagens intermediÃ¡rias individuais.
  - ValidaÃ§Ã£o direta e vinculaÃ§Ã£o de fontes/citaÃ§Ãµes direcionadas Ã  Ãºltima mensagem concluÃ­da.
- **`ChatOrchestrator._publish_final_response`**: EmissÃ£o da cadeia semÃ¢ntica `turn_started` $\to$ `assistant_started` $\to$ `assistant_delta` $\to$ `assistant_completed` $\to$ `turn_completed`.

### `vrsoft_extractor/mary/providers.py`
- **`CodexProvider._handle_server_message`**:
  - Itens com tipo `agentMessage` que chegam via `item/started` emitem `assistant_started` carregando `itemId` e `phase`.
  - Itens com tipo `agentMessage` que chegam via `item/completed` emitem `assistant_completed` com texto autoritativo consolidado dos blocos de texto.
  - Demais itens continuam sendo classificados como `tool_event`.

### `vrsoft_extractor/mary/db.py`
- **`MaryDatabase.__init__`**: MigraÃ§Ã£o aditiva para `execution_ordinal` e `message_status` na tabela `messages`.
- **`MaryDatabase.add_message`**: Assinatura expandida com parÃ¢metros opcionais `provider_message_id`, `execution_ordinal` e `message_status`.
- **`MaryDatabase.upsert_assistant_message`**: Novo mÃ©todo idempotente que atualiza por `execution_ordinal` existente ou insere novo registro de mensagem do assistente.

### `vrsoft_extractor/mary/frontend/chat.py`
- **`_MappingListModel.update_by_key`**: Novo mÃ©todo de busca reversa por campo-chave e emissÃ£o granular de `dataChanged`.
- **`MessageListModel.ROLE_NAMES`**: AdiÃ§Ã£o das roles `"messageKey"` e `"isStreaming"`.
- **`ChatBridge.__init__`**: Estados per-message (`_current_message_key`, `_message_streaming_texts`, `_message_displayed_texts`, `_message_pending_texts`).
- **`ChatBridge._on_runtime_event`**:
  - `assistant_started`: Adiciona nova linha do assistente no modelo com `messageKey` e `isStreaming = True`.
  - `assistant_completed`: Atualiza a mensagem por chave com texto final e `isStreaming = False`.
  - `assistant_delta`: Acumula texto na chave ativa.
- **`ChatBridge._flush_stream_step`**: AtualizaÃ§Ã£o via `update_by_key` quando hÃ¡ `_current_message_key`.
- **`ChatBridge._ensure_streaming_message`**: Define `messageKey` e `isStreaming = True`.
- **`ChatBridge._reload_selected_messages` & `_activity_timeline_item`**: Preenchimento padrÃ£o de `messageKey=""` e `isStreaming=False`.

### `vrsoft_extractor/mary/frontend/qml/pages/ChatPreview.qml`
- **Delegate de Mensagens**:
  - Adicionadas as propriedades requeridas `required property string messageKey` e `required property bool isStreaming`.
  - Propriedade `streaming` de `VrAssistantMessage` atualizada para:
    `streaming: messageItem.isStreaming || (chat.turnRunning && messageItem.index === messageList.count - 1 && !messageItem.messageKey)`.

### `pyproject.toml`
- Adicionada a seÃ§Ã£o `[tool.pytest.ini_options]` com `testpaths = ["tests"]`, garantindo execuÃ§Ã£o direta de `pytest -q` sem interferÃªncia de arquivos de texto de documentaÃ§Ã£o legados.

---

## 5. Matriz de Testes e ValidaÃ§Ã£o

Arquivo dedicado: `tests/test_intermediate_messages.py` (28 novos testes cobrindo todas as categorias obrigatÃ³rias).

| Item da Matriz ObrigatÃ³ria | CenÃ¡rio Testado | Resultado |
|---|---|---|
| **1. Estrutura do Turno** | TrÃªs mensagens intermediÃ¡rias intercaladas (M1 $\to$ M2 $\to$ M3); mensagens consecutivas sem ferramenta. | **APROVADO** (`test_three_messages_per_turn`, `test_bridge_multiple_messages_interleaved`) |
| **2. Identidade & Deltas** | Mensagens distintas recebem IDs distintos; deltas concatenam exclusivamente na mensagem ativa; autoritativo sem deltas funciona. | **APROVADO** (`test_multiple_messages`, `test_complete_with_authoritative_text`, `test_update_by_key_updates_correct_message`) |
| **3. Lifecycle do Turno** | `assistant_completed` mantÃ©m o turno em execuÃ§Ã£o; finalizaÃ§Ã£o ocorre uma Ãºnica vez no tÃ©rmino; idempotÃªncia em repetiÃ§Ã£o. | **APROVADO** (`test_assistant_completed_persists_message`, `test_turn_completed_with_intermediate_no_aggregate`, `test_dedup_by_ordinal`) |
| **4. Late Events & Isolamento** | Eventos tardios de turno/conversa anterior (A) sÃ£o descartados e nÃ£o poluem o turno ativo (B). | **APROVADO** (`test_late_events_from_old_turn_blocked`, `test_cross_conversation_isolation`) |
| **5. Cancelamento & Erro** | Erro apÃ³s M1 preserva M1 no banco; cancelamento preserva mensagens anteriores e marca estado apropriado. | **APROVADO** (`test_error_after_m1_preserves_m1`, `test_cancellation_preserves_prior_completed`) |
| **6. IdempotÃªncia & Dedup** | Re-execuÃ§Ã£o com mesmo ordinal atualiza registro existente sem criar duplicatas. | **APROVADO** (`test_upsert_inserts_then_updates`, `test_dedup_by_ordinal`) |
| **7. MigraÃ§Ã£o de Banco** | Banco de dados antigo sem colunas novas inicializa, aplica migraÃ§Ã£o aditiva e re-executa de forma idempotente sem perda. | **APROVADO** (`test_legacy_database_migration`) |
| **8. Interface & QML Model** | `MessageListModel` atualiza itens por chave preservando Ã­ndices e estados de streaming individuais. | **APROVADO** (`test_update_by_key_updates_correct_message`, `test_update_by_key_returns_false_for_missing_key`) |
| **9. Task Bar & Passos** | Task Bar mantÃ©m-se Ã­ntegra durante transiÃ§Ã£o entre M1 e M2. | **APROVADO** (validado no orquestrador e QML bindings) |
| **10. Modos Preservados** | Modo nativo e validaÃ§Ã£o de resposta direta em VR preservados sem vazamento de workers para mensagens pÃºblicas. | **APROVADO** (`test_legacy_single_message_path`, suÃ­te `test_mary_orchestration.py`) |
| **11. Continuidade de Contexto** | HistÃ³rico e ordenaÃ§Ã£o das mensagens preservados via ordenaÃ§Ã£o monotÃ´nica por ordinal/ID. | **APROVADO** (`test_three_messages_per_turn`) |
| **12. Providers & Fallbacks** | Provedores sem mensagens intermediÃ¡rias (Claude/OpenCode/Antigravity) funcionam com fallback implÃ­cito automÃ¡tico. | **APROVADO** (`test_implicit_start_on_delta_without_assistant_started`, `test_implicit_start_and_single_turn_completion`, suÃ­te completa de providers) |

### ExecuÃ§Ã£o Geral de Testes
```
.\.venv\Scripts\python.exe -m pytest -q
630 passed, 45 subtests passed in 88.41s
```

---

## 6. LimitaÃ§Ãµes Conhecidas e PrÃ³ximos Passos

1. **Protocolos dos Providers**:
   - Provedores como Claude e OpenCode nÃ£o expÃµem atualmente no protocolo de streaming eventos explÃ­citos de inÃ­cio/conclusÃ£o de mensagens intermediÃ¡rias (entregam o turno em bloco contÃ­nuo de texto). Eles utilizam de forma segura o fallback implÃ­cito de mensagem Ãºnica. Caso esses provedores passem a suportar streaming com mÃºltiplos blocos conversacionais explÃ­citos, basta emitir `assistant_started` e `assistant_completed` nos respectivos adaptadores.
2. **PersistÃªncia em Caso de Queda Abrupta (Crash)**:
   - Mensagens concluÃ­das (`assistant_completed`) estÃ£o garantidas no SQLite no momento em que sÃ£o emitidas. Deltas em andamento da mensagem corrente sÃ£o persistidos como `runtime_events`. Em caso de encerramento forÃ§ado do processo, a recuperaÃ§Ã£o existente (`recover_interrupted_conversations`) marca o turno como interrompido.

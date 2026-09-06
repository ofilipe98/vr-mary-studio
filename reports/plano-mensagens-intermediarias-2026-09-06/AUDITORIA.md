# Auditoria do plano de mensagens intermediárias

Data: 06/09/2026. Projeto: VR Norte Studio, `D:\Codex\vr-mary-studio`.
Parecer: **faz sentido, com ajustes obrigatórios antes da implementação**.
Escopo desta entrega: auditar e preparar a implementação pelo Opus 4.6; nenhuma implementação da funcionalidade foi feita nesta etapa.

## Base examinada e limites

Foi examinado o código da árvore de trabalho, incluindo alterações locais e arquivos ainda não versionados. HEAD: `d4daa2085be19e3236923f9ae8ad8f31893cce05`. HEAD sozinho não representa a base auditada. Consulte `baseline-manifest.json`, `baseline-source.zip` e `baseline-git-status.txt` para a futura comparação. Linhas podem mudar; os símbolos abaixo são as referências principais.

Entrada: `plano-original.md`, cópia do anexo. Consultei também a [referência T3 Code](https://github.com/pingdotgg/t3code), sem tratá-la como especificação dos protocolos dos providers. O parecer decorre do código local; não constitui auditoria da implementação interna do T3 nem certificação das versões instaladas dos CLIs.

Validação executada:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_audit_regressions.py tests/test_review_recovery.py tests/test_chat_presentation.py
```

Resultado: **39 passed in 8.72s**. Não executei toda a suíte, provider real ou inspeção visual interativa nesta auditoria. Esses testes confirmam regressões existentes, não comprovam a funcionalidade proposta.

## Mapa do existente

| Requisito | Estado | Evidência e consequência |
|---|---|---|
| Python, SQLite, Qt/QML e bridge | EXISTENTE | `models.py`, `db.py`, `frontend/chat.py`, `ChatPreview.qml`; preservar. |
| Task Bar | EXISTENTE | `frontend/qml/components/VrTaskBar.qml`, instância em `ChatPreview.qml`; `steps=chat.activitySteps`. Contagem e etapa atual em `completedCount`/`currentStepText`. |
| Estado do plano | EXISTENTE / PARCIAL | `ChatBridge._activity_steps`, `_record_execution_event`, `_default_activity_steps`, `_advance_default_activity`; `response_plan_created` alimenta passos e `plan_created` registra agentes. Há plano padrão de duas etapas; não afirmar que toda a barra já representa um plano nativo do modelo. |
| RuntimeEvent | PARCIAL | `models.py:RuntimeEvent`: conversation_id, kind, text, payload, created_at. Identidades específicas ficam no payload; falta contrato uniforme para execução e mensagem. |
| Identidade e admissão do turno | EXISTENTE / PARCIAL | `MaryDatabase.begin_user_turn` faz claim e inserção do usuário atomicamente. `_guarded_turn_callback` captura ID imutável da mensagem do usuário. `messages.turn_id` recebe ID nativo posteriormente. Falta identidade local explícita propagada em todos os caminhos. |
| Proteção contra eventos atrasados | EXISTENTE / PARCIAL | Codex mantém `_active_turns`, `_completed_turn_ids`, `_item_turn_ids`; há callback guard e geração de callback no finalizador. `test_audit_regressions.py` testa atrasos, start pendente e reconnect. Não refazer como se ausente; estender aos novos eventos e demais caminhos. |
| Streaming | EXISTENTE / PRECISA CORREÇÃO | `_assistant_buffers[conversation_id]` agrega texto; bridge usa `_streaming_text` e atualização da última linha. Não representa mensagens independentes. |
| Commentary | PARCIAL | Codex preserva phase e itemId; `_handle_event` exclui commentary do buffer final; bridge envia commentary ao trace. Precisa publicação conversacional sem duplicar trace/bolha. |
| Ciclo de vida por mensagem | AUSENTE como contrato comum | `item/started` e `item/completed` de agentMessage ainda viram `tool_event`; separação por quebras de linha não equivale a message identity. |
| Work/Activity | EXISTENTE / PARCIAL | `_record_tool_event`, `_record_turn_tool_segment`, `_turn_display_segments` e `VrChatActivity.qml`. Já há intercalação por offsets dentro da resposta; reutilizar apresentação, substituir inferência quando houver identidade real. |
| Ordenação | PARCIAL | `messages()` ordena por id; runtime_events também tem PK. Falta ligação persistente de ordem entre mensagens e atividades, especialmente ao recarregar mais de um turno. |
| SQLite com várias mensagens | EXISTENTE no schema / PARCIAL no fluxo | `messages` não limita assistant por turn e já tem `provider_message_id`, `turn_id`, `response_mode`. `add_message` não expõe provider_message_id; `_finalize_turn_completed` grava uma resposta agregada. Não justificar migração como remoção de restrição inexistente. |
| Reload e recuperação | EXISTENTE / PARCIAL | `_reload_selected_messages`, `_restore_activity_from_history`, `latest_turn_events`, `recover_interrupted_conversations`. Recuperação marca conversas interrupted; falta replay fiel das mensagens novas e seus estados. |
| Cancelamento e falhas | EXISTENTE / PARCIAL | `interrupt`, estados terminais, limpeza condicional de processo/callback. Falta fechamento e persistência por mensagem; finalização atual não salva texto assistant quando há estado terminal de erro/cancelamento. |
| Finalização assíncrona | EXISTENTE / PRECISA EXTENSÃO | `_submit_turn_finalization`, `_finalize_turn_completed`; preservar executor, guardas e validação. Identidade deve cobrir toda mutação, não só remoção do callback. |
| VR direto / Ultra | EXISTENTE | `_validate_direct_response`, `_run_module_fanout`, `_run_buffered_main_turn`, `_run_ephemeral_turn`, `_publish_final_response`. Não publicar drafts, envelopes JSON, review/rewrite ou workers como conversa. |
| General Harness separado | NÃO LOCALIZADO | Não encontrei perfil `GENERAL_ORCHESTRATED` na árvore examinada. Não criar esse produto para cumprir exemplos conceituais do anexo. Revalidar se a árvore mudar. |
| Deduplicação genérica | AUSENTE como contrato | Guardas e reconciliação específicos não equivalem a dedup global. Implementar somente por identidade confiável; nunca por texto. |
| Testes | EXISTENTE / PARCIAL | Core, orchestration, VR Ultra, QML, presentation, antigravity e audit regressions; faltam casos end-to-end de várias mensagens persistentes. |

## Providers: o que o código permite afirmar

| Provider | Normalização atual | Trabalho necessário |
|---|---|---|
| Codex | Eventos agentMessage delta com itemId/phase; lifecycle chega como tool_event; turn IDs e filtros já existem. | Publicar lifecycle semântico de mensagem, manter isolamento e reconciliar texto autoritativo de completed sem duplicar deltas. |
| Claude | `_consume` lê stream_event/content_block_delta; assistant blocks viram ferramentas; result serve de fallback quando não houve texto. turn_started/completed locais não fornecem ID nativo uniforme. | Capturar fronteiras/IDs presentes nos eventos suportados, distinguir mensagem de content block, reconciliar result; não usar cada token/bloco como nova mensagem. |
| OpenCode | `_consume` mapeia text, reasoning, tool_use e step_finish; step_finish contabiliza tokens; término ocorre ao encerrar processo. | Verificar se text é delta ou snapshot nas fixtures reais, aproveitar IDs de part/message quando presentes; step_finish não encerra automaticamente turno. |
| Antigravity | `antigravity.py:_consume`: step.agent_response/text_delta, ferramentas e result; recuperação com nova tentativa quando falta texto. | Identidade por execução/tentativa e mensagem quando demonstrável; fallback sem inventar fronteiras. Preservar recuperação e contabilidade. |

Ter caminhos de parsing não prova que o provider/modelo emitirá intermediárias em toda tarefa. A certificação requer fixtures sanitizadas e teste real quando disponível.

## Ajustes essenciais ao anexo

1. **Reutilizar proteções já presentes.** A prioridade zero é demonstrar isolamento completo, não substituir obrigatoriamente os dicionários por tuplas. Um callback associado à execução e validado corretamente é aceitável.
2. **Separar turno local e tentativa nativa.** Um pedido do usuário pode gerar síntese, retry e rewrite. O ID nativo não pode redefinir o turno lógico nem permitir que uma tentativa antiga finalize outra.
3. **Persistir intermediárias públicas.** Remover a opção ambígua de serem efêmeras. Salvar completed e texto parcial no cancelamento/erro controlado; documentar perda máxima em crash. Não gravar uma nova transação por token como parte desta mudança. Hoje `add_event` já é chamado para deltas: auditar custo, sem alegar que o projeto não grava tokens.
4. **Preservar o contrato final do VR.** A última mensagem não é necessariamente resposta final aprovada. Respeitar phase, validação, síntese, citações e publicação existente. Intermediárias não podem contaminar o conteúdo enviado ao validador.
5. **QTimer não é proibido em geral.** O timer de 80 ms revela texto recebido e outro mede tempo de atividade. Preservá-los ou adaptá-los por mensagem. A proibição é fabricar progresso conversacional usando timers.
6. **Definir fronteiras, dedup e ordem.** Duas mensagens sem tool entre elas também precisam de IDs diferentes. Deltas repetidos legitimamente devem continuar aparecendo. Snapshot final substitui/reconcilia a mesma mensagem; não concatena novamente.
7. **Separar vida do plano da vida da mensagem.** Nem encerrar nem avançar a Task Bar só porque M1 terminou ou M2 começou. A primeira emissão de texto já aciona `_advance_default_activity`; revisar essa dependência específica. Falha/cancelamento não equivale a marcar todas as tarefas concluídas.
8. **Testar a cada etapa.** Não deixar cancelamento, erro e concorrência para depois da UI. Incluir eventos enfileirados na thread Qt, finalizador atrasado, troca de conversa, retry, clonagem e ramificação.
9. **Compatibilidade dos construtores.** RuntimeEvent é criado posicionalmente em muitos lugares; novos campos devem ser opcionais e preservar a ordem atual, ou exigir migração explícita de todos os chamadores.
10. **Escopo controlado.** Não adicionar provider, modelo, General Harness, novo transporte, novo composer ou redesign. Opus 4.6 é o destinatário deste trabalho, não uma configuração que deva ser adicionada ao aplicativo.

## Entrega para implementação e revisão

Use `PROMPT_OPUS_4_6.md` como instrução principal. O anexo é contexto de intenção; as decisões concretas do prompt preparado resolvem suas ambiguidades. Solicite ao implementador relatório por etapa, diff relativo à baseline local, comandos/resultados de testes, migração e limitações. A revisão futura deve verificar o código entregue e reproduzir os cenários; este parecer não antecipa sua aprovação.

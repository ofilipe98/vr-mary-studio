# Implementação para Opus 4.6 — mensagens intermediárias reais

Implemente nesta árvore de trabalho do VR Norte Studio o suporte a múltiplas mensagens públicas do assistant no mesmo turno. Leia primeiro `AUDITORIA.md` nesta pasta e revalide seus símbolos no código atual. A auditoria foi feita em 06/09/2026; há mudanças locais anteriores. Não reverta, descarte ou sobrescreva trabalho existente. Não faça deploy, release, instalação de providers ou alterações de autenticação como parte desta tarefa.

## Resultado esperado

Um pedido cria um único turno lógico. Esse turno pode exibir M1 → atividade → M2 → atividade → M3 final, com identidade persistente para cada mensagem. Deltas atualizam a mensagem correta; concluir M1 não encerra o turno. A Task Bar existente permanece vinculada ao turno. Ao reabrir a conversa, mensagens públicas e atividades mantêm identidade e ordem. Providers que só entregam resposta final continuam funcionando.

Reutilize Python, SQLite, RuntimeEvent, ChatOrchestrator, ChatBridge, MessageListModel, QML, VrTaskBar, VrAssistantMessage, VrChatActivity, renderização Markdown e mecanismos atuais de signals/slots. Não crie React, frontend web, HTTP/RPC/WebSocket interno novo, outro plano, outra barra ou outro composer. Preserve os transportes que os providers já utilizam.

## Contrato obrigatório antes de codificar

Documente sua decisão concreta para os pontos abaixo; faça a implementação em seguida, sem pedir confirmação para escolhas técnicas rotineiras dentro deste escopo.

- **execution_id local imutável**: criado na admissão atômica do pedido, pode derivar do ID da mensagem user já produzido por begin_user_turn. É a identidade do turno lógico. Preserve `messages.turn_id` e sua compatibilidade com operações nativas; não o reaproveite silenciosamente com outro significado.
- **native_turn_id e attempt identity**: IDs nativos pertencem a tentativas/sessões do provider. Retry, revisão e síntese podem ter outros IDs sem criar novo pedido. Identidade de tentativa deve ser congelada no callback, nunca inferida consultando apenas a conversa atualmente ativa.
- **message identity**: ID local estável, associado à execução; use provider item/message ID quando houver. Fallback por contador da execução somente em fronteiras observáveis. Não criar uma mensagem por delta, por tool ou por cronômetro. Distinguir message ID de content-block/part ID.
- **ownership/audience**: eventos de worker, review, rewrite e resultado interno não são mensagens públicas. Autorizar publicação apenas no fluxo público do agente principal. Eventos reasoning/thinking não viram mensagens públicas.
- **ordem persistente**: defina um ordinal monotônico por execução para inserção de mensagens e atividades, ou use identidade de runtime_event persistida de modo equivalente. Atualizações da mesma entidade não a reordenam. Não ordenar apenas por timestamp, nem usar índices independentes que não permitam intercalar as duas tabelas.
- **lifecycle semântico**: estenda RuntimeEvent minimamente para distinguir assistant_started, assistant_delta, assistant_completed e término de turno. Preserve chamadas posicionais existentes. Mantenha tool_event e eventos de plano quando suficientes; QML recebe dados semânticos, nunca interpreta protocolo nativo.
- **texto final**: `assistant_completed` fecha apenas a mensagem; `turn_completed` aciona a finalização existente. Error/cancelled permanecem terminais próprios. Texto autoritativo de item completed deve reconciliar o mesmo item, sem duplicar deltas. Um item completed sem deltas também deve aparecer.
- **estados**: mensagens completed, interrupted/failed conforme convenção escolhida; turno running até terminar a finalização aplicável. Não transformar cancelamento/erro em sucesso só porque o processo emitiu completed depois.

Não introduza event sourcing completo, tabela de turnos ou mecanismo genérico de conexão sem demonstrar necessidade. Use os campos existentes e migração aditiva apenas para metadados realmente ausentes. `messages` já aceita várias linhas assistant por turn.

## Etapas de implementação

### 0. Registrar a base

Leia o status Git e instruções AGENTS aplicáveis. Registre arquivos preexistentes modificados/não versionados. Esta pasta contém uma baseline parcial de código e testes, não um backup de todo o projeto. Se algum arquivo mudou após a auditoria, registre a diferença e adapte o plano.

Faça uma tabela EXISTENTE / PARCIAL / AUSENTE / PRECISA CORREÇÃO para os requisitos, com símbolos reais. Catalogue os kinds de RuntimeEvent produzidos e consumidos pelos caminhos afetados. Não invente `GENERAL_ORCHESTRATED` se não existir; mapeie os modos reais, hoje nativo, VR e VR Ultra.

### 1. Isolar execução em todas as fronteiras

Estenda `_guarded_turn_callback`, normalizadores e contextos de execução. Preserve filtros Codex `_active_turns`, `_completed_turn_ids`, `_item_turn_ids` e limpeza condicionada ao callback/processo proprietário. Dictionary por conversa é aceitável se a execução capturada e a validação forem suficientes.

Valide ownership antes de alterar buffer, banco, plano, status, aprovações ou callback. Cubra `_run_buffered_main_turn`, `_run_ephemeral_turn`, `_emit_orchestration_event`, callbacks de ferramentas dinâmicas e finalizador assíncrono. Finalizador A não pode escrever status/limpar estado de B nem emitir erro contra B. Não se limite à remoção do callback no finally.

Proteja também eventos já enfileirados no signal Qt: a validação no provider não basta se A chegou ao bridge depois que B começou. Eventos globais de sessão/settings sem identidade de turno continuam tendo seu tratamento compatível; não atribua arbitrariamente eventos de execução anônimos ao turno ativo.

Adicione e execute regressões de A → término → B → delta/completed/error de A antes de avançar.

### 2. Normalizar mensagens e conteúdo nos providers

Codex: mapear agentMessage started/completed para mensagens, conservar itemId/phase e texto autoritativo; remover a necessidade de concatenar itens por quebras de linha. Não classificar agentMessage como ferramenta na timeline nova.

Claude: preservar fronteiras de mensagem nos stream events suportados, índices de blocos, IDs e fallback result. Não confundir content_block_stop com término de turno. Evitar replay duplicado entre delta, assistant snapshot e result.

OpenCode: determinar por fixtures sanitizadas se part.text é delta ou snapshot. Preservar part/message identity quando presente e manter step_finish como etapa, não término global.

Antigravity: preservar step/text_delta/result e tentativa de recuperação. Não inventar IDs nativos ou suporte a mensagens intermediárias. Um fallback de mensagem única por execução é válido se o protocolo observado não fornecer fronteiras confiáveis.

Para todos: dedup somente com event ID/offset/sequência nativa confiável e no escopo correto. Uma sequência local gerada a cada recebimento ordena, mas não identifica uma retransmissão. Texto igual não é duplicata por definição. Não exigir event_id de provider que não o fornece. Registre limitações de protocolo, sem alegar validação real a partir de mocks.

### 3. Orquestrador e SQLite

Substitua buffer agregado por estado de mensagens pertencentes à execução, mantendo compatibilidade com fluxos antigos. Persistir mensagem pública ao completar; salvar parcial em cancelamento/erro controlado, com estado explícito. Em crash, garantir sobrevivência das mensagens concluídas e recuperação do turno como interrupted; parcial desde o último checkpoint pode ser perdido, desde que documentado. Não exigir nova gravação por token. Inspecione `add_event`, que já persiste deltas, antes de escolher checkpoint.

Reutilize messages.id, provider_message_id, turn_id e response_mode. Acrescente somente o necessário para execução, ordenação e status/fase. Migração aditiva, idempotente e transacional; seguir o mecanismo de migração existente e registrar versão/marcador compatível. Testar banco antigo sem os novos campos. Não mudar nem abrir banco pessoal para testes.

Garanta upsert/idempotência por identidade; não persistir a mesma intermediária em `assistant_completed` e novamente no finalizador. Não criar uma resposta agregada duplicando M1+M2+M3. Persistir atividades com vínculo e ordem suficientes para reconstruir todos os turnos, não apenas `latest_turn_events`.

Preserve `_validate_direct_response`, evidências e citações associadas à mensagem correta. Em VR, publique comentários públicos comprovadamente destinados ao usuário, mas mantenha draft final, envelope estruturado, revisão e rewrite internos até o fluxo existente aprovar a resposta. `_run_buffered_main_turn` não pode concatenar commentary à resposta a validar. `_publish_final_response` deve publicar a resposta aprovada na mesma execução lógica, sem fabricar um novo turno público.

Mantenha isolamento dos pesquisadores e fanout: agent_delta e resultados de workers continuam atividade interna. Não adicione instruções de comportamento ao modelo nesta primeira implementação; a infraestrutura e os fixtures devem provar suporte antes.

### 4. Bridge, timeline e Task Bar

MessageListModel deve inserir e atualizar por identidade; retire a hipótese de que a última linha é sempre a mensagem que recebe o delta. Atualizar uma mensagem não pode alterar outra nem mover sua posição. Preserve scroll, cópia, seleção, Markdown, fontes, virtualização e troca de conversa durante execução.

Reutilize componentes visuais e lógica de atividade. Renderizar M1/atividade/M2, inclusive M1 e M2 consecutivas sem ferramenta. Evitar duas representações visíveis da mesma commentary. Replay do histórico deve produzir a mesma ordem e IDs, inclusive depois de trocar de conversa e retornar durante streaming. Rever `_reload_selected_messages`, `_restore_activity_from_history`, `_ensure_streaming_message` e atualização da última linha.

Preserve timers legítimos de flush/animação/tempo decorrido, adaptando estado por mensagem. É proibido fabricar texto de assistant por timer. Flushing pendente de M1 não pode vazar para M2 ou outra conversa.

Reutilize VrTaskBar, `activitySteps` e o estado de plano existente. Não resetar/avançar o plano por assistant_started/completed. Examine a dependência atual de `_advance_default_activity` no primeiro delta e preserve apenas transições justificadas pelo lifecycle real do turno. Atualizações reais de plano seguem sua semântica. Ao falhar/cancelar, a barra sai de running sem marcar etapas não executadas como concluídas.

### 5. Regressões e validação final

Execute testes apropriados a cada etapa e a suíte completa ao final. Não modifique expectativas antigas apenas para encobrir regressões; explique mudanças de contrato intencionais, como persistência de intermediárias antes ausentes.

Matriz obrigatória, com asserts de estado, banco e UI quando pertinente:

1. User → final → turn completed; tools → final; três mensagens intercaladas; duas mensagens sem tool entre elas.
2. IDs diferentes para mensagens distintas; deltas da mesma mensagem concatenam nela; completed com snapshot não duplica; completed sem delta é exibido.
3. assistant_completed mantém turno/plano running; terminal do turno finaliza uma vez. Repetição de completed é idempotente.
4. Late delta/completed/error/tool/plan de A não afeta B, inclusive antes da confirmação nativa de B, após reconnect e na fila Qt. Callback/processo de B sobrevive.
5. Cancelar durante streaming, erro após M1 e no meio de M2, retry, finalizador A atrasado; estados e parciais corretos, limpeza só do proprietário.
6. Evento duplicado identificado não duplica texto; dois deltas legítimos iguais permanecem. Ordem determinística com timestamps iguais.
7. Banco antigo migra duas vezes sem perda; reabrir conversa com vários turnos mantém ordem de mensagens/atividades. Recuperação após encerramento abrupto preserva mensagens completas e marca execução interrompida.
8. Trocar conversa durante streaming e retornar, iniciar outro turno após término, rolar manualmente, copiar, renderizar blocos/citações; QML sem erros.
9. Task Bar única, sem reset entre mensagens; cancelamento/erro não marca plano inteiro como concluído.
10. Nativo, VR direto e VR Ultra preservados; validação e citações corretas; worker/reasoning/draft/rewrite não aparecem como mensagens públicas.
11. Clone, branch_from_message, messages_through e contexto de continuação permanecem coerentes; intermediárias não devem expulsar silenciosamente o contexto útil por limites baseados em quantidade de linhas. Documente e teste a política de contexto escolhida.
12. Fixtures de todos os quatro providers, incluindo fallback sem intermediárias; testes de provider existentes continuam válidos.

Comando final esperado:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Use QML offscreen nos testes que o suportam. Faça também smoke visual com a UI e um provider real já configurado quando o ambiente permitir, em diretório temporário e com tarefa inofensiva. Não instale/autentique/reconfigure provider para cumprir o smoke. Registre indisponibilidade como NÃO VALIDADO, nunca como passou. Não force intermediárias falsas se o modelo não as emitir. Logs devem conter apenas metadados necessários e conteúdo sanitizado; nunca secrets, tokens, prompts completos ou raciocínio privado.

## Entrega para revisão posterior pelo Codex

Crie `RELATORIO_IMPLEMENTACAO.md` nesta pasta contendo:

- Requisitos e status final com arquivos/símbolos; o que reutilizou, alterou e deixou limitado.
- Contrato de execução/mensagem/tentativa/ordenação, eventos e tabela de capacidades verificadas por provider.
- Fluxo concreto provider → RuntimeEvent → orquestrador → DB → bridge → QML, incluindo intermediárias e final aprovado.
- Migração e comportamento de cancelamento, erro, crash e recuperação; política de contexto/branch.
- Comandos, totais de testes, falhas preexistentes separadas das introduzidas, logs e evidências visuais sanitizadas.
- Lista exata dos arquivos alterados nesta implementação e diff relativo à base local, distinguindo mudanças anteriores. Não faça commit de alterações alheias para produzir esse diff.
- Declaração verificável: “Task Bar existente foi reutilizada e não duplicada”.
- Limitações e validações não realizadas. Não declare pronto se critérios essenciais falharem; descreva o impedimento concreto.

A revisão posterior examinará identidade ponta a ponta, ownership de callbacks/finalizadores, publicação VR, idempotência, migração/reload e regressões de QML, além de comparar os arquivos com a baseline. Esta implementação precisa ser revisável por evidências, não apenas por screenshots ou contagem de testes.

# Auditoria e correções da implementação do Opus

Data: 06/09/2026. Escopo: revisar a implementação entregue e corrigir os erros e pendências, conforme autorização posterior do usuário.

## Parecer

A implementação original não estava pronta, apesar de sua suíte passar. Foram reproduzidos defeitos de persistência, identidade e apresentação. As correções estão aplicadas ao código local e as regressões foram incorporadas à suíte normal em `tests/test_intermediate_review.py`.

O `RELATORIO_IMPLEMENTACAO.md` na raiz registra a entrega anterior do Opus. Suas afirmações sobre conclusão integral, cancelamento, ordenação e capacidades dos providers não devem ser usadas como comprovação da versão corrigida. Este relatório e as evidências anexas registram a revisão.

## Achados e correções

| Gravidade | Problema confirmado | Correção |
|---|---|---|
| Alta | `execution_ordinal` reiniciava em 1 a cada turno, mas o upsert buscava somente conversa + ordinal. O segundo turno sobrescrevia a resposta do primeiro. | Chave persistente inclui `execution_id` imutável; índice único parcial para mensagens novas e upsert serializado. |
| Alta | A UI acumulava `FirstSecond` na segunda mensagem usando o buffer agregado. | Flush usa buffers por `messageKey`; completed limpa apenas a mensagem correspondente; ferramenta entre deltas não cria outra linha. |
| Alta | IDs nativos eram recebidos, mas não utilizados para localizar a mensagem; completed antigo podia fechar M2. | Mapeamento de item por tentativa e execução, estado de fechamento e rejeição de deltas/completions repetidos de item encerrado. |
| Alta | `commentary` continuava excluído do texto público; o snapshot Codex lia `content`, ignorando `item.text`, formato que o próprio código anterior já consumia. | Commentary recebe lifecycle e persistência próprios; normalizador aceita `item.text` e o fallback de blocos de texto. |
| Alta | Lifecycle da síntese em buffer podia atravessar o caminho público antes da revisão VR. | Síntese mantém draft internamente; final direto aguarda validação; somente comentários públicos e resposta aprovada atravessam a publicação. |
| Alta | Cancelamento/erro preservava M1, mas perdia o parcial de M2. | Persistência do parcial público com estado interrupted/error; drafts VR não aprovados continuam internos. |
| Alta | Identidade não protegia eventos já enfileirados na UI nem todos os efeitos de um finalizador atrasado. | Bridge acompanha execução por conversa; finalizador captura dono antes de entrar no executor; admissão/finalização usam dono também no banco. Callbacks preservam geração e tentativa. |
| Média | `complete_message()` não liberava a mensagem ativa. | Fechamento efetivamente libera o slot; completions não encerram o turno. |
| Média | Reload apagava `messageKey`, restaurava só o último conjunto de atividades e podia juntar conteúdo na última linha. | Replay de eventos públicos por PK persistente, agrupado por execução, com mensagens, ferramentas e parciais da execução ativa. |
| Média | Cancelamento marcava etapas não executadas como concluídas. | Tarefas pendentes permanecem pendentes; a etapa corrente recebe erro/cancelamento. Task Bar existente reutilizada. |
| Média | O relatório alegava cobertura de todos os providers com teste somente do buffer genérico. | Fixtures agora atravessam consumidores de Claude, OpenCode e Antigravity, além do mapeamento Codex. Fronteiras/IDs observáveis são aproveitados; fallback continua disponível. |
| Média | Intermediárias poderiam consumir o limite de contexto baseado em linhas. | Commentary e mensagens interrompidas/erro são filtradas do contexto de continuação e do transcript de clone, sem apagar o histórico público. |

## Contrato resultante

- `execution_id`: ID da mensagem user retornado pela admissão atômica. Distingue os pedidos da conversa.
- `attempt_id`: identidade local capturada no callback. IDs de itens nativos são mapeados no escopo da tentativa.
- `messageKey`: execução + ordinal da mensagem; permanece estável no streaming e na recarga. Históricos anteriores usam a identidade da linha do banco.
- `turn_id`: preserva a identidade nativa, sem ser substituído pela execução local.
- Ordem: a PK de `runtime_events` determina a inserção relativa de mensagens e atividades; atualizações não movem o item.
- `assistant_completed`: fecha/persiste uma mensagem pública, sem encerrar a Task Bar ou o turno. Publicação final VR ocorre após validação.
- `turn_completed`: mantém o finalizador existente e conclui somente sua execução. Uma nova admissão não pode ser liberada pelo finalizador antigo.
- Deduplicação: IDs confiáveis de evento e estado/identidade do item. Nunca pelo texto de deltas. Dois deltas legítimos iguais continuam válidos.

## Banco e compatibilidade

Reutilizados `messages`, `runtime_events`, `provider_message_id`, `turn_id`, `response_mode` e o mecanismo existente `_ensure_column`.

Acrescentados metadados aditivos: `messages.execution_id`, `message_phase`, `start_event_id` e `conversations.active_execution_id`. As colunas `execution_ordinal` e `message_status` da entrega do Opus foram preservadas. O índice `idx_assistant_execution_message` restringe somente registros novos com execução e ordinal positivos; não impõe unicidade retroativa aos históricos antigos.

Migração segue a introspecção idempotente de schema já usada pelo projeto; o conjunto de colunas e o índice identificam a nova estrutura. Não foi introduzido um segundo framework de migração. Bancos temporários antigos são cobertos pelos testes. Não houve abertura ou alteração do banco pessoal durante esta validação.

Mensagens públicas completas sobrevivem ao reinício. Parciais públicos persistem em erro/cancelamento controlado e os eventos públicos já registrados permitem reconstruir o texto disponível. Recuperação existente marca execuções órfãs como interrompidas. Texto que ainda não chegou a um checkpoint/evento persistido pode ser perdido num crash. Não foi acrescentada uma gravação de mensagem por token; o log de eventos existente continua sendo usado.

A correção impede novas sobrescritas; não presume recuperar automaticamente conteúdo que a versão anterior já tenha sobrescrito em algum banco.

## Providers e limites verificados

| Provider | Validação realizada | Limite |
|---|---|---|
| Codex | Mapeamento nativo, regressões e teste real de dois turnos no mesmo chat. | O smoke solicitou respostas curtas; não comprova emissão espontânea de intermediárias numa tarefa longa. |
| Claude | Consumidor testado com message_start/message_stop, deltas e snapshots identificados. | Não foi executado modelo real neste provider. Sem identidade observável, permanece fallback. |
| OpenCode | Consumidor testado com messageID, part IDs, snapshots repetidos e mudança de mensagem. | Sem IDs, mantém streaming legado; não deduplica por coincidência textual. Não foi executado modelo real. |
| Antigravity | Consumidor testado com step_update e result; suíte existente preservada. | Fallback de mensagem única quando não há fronteira confiável; não foi executado modelo real. |

General Harness separado não foi localizado na base auditada; não foi criado artificialmente. A infraestrutura comum atende os modos existentes nativo, VR direto e VR Ultra. Não foram adicionados prompts de progresso artificial, outro composer, outra Task Bar ou transporte interno.

## Evidências e validação

- Antes das correções: **630 passed, 45 subtests passed**, reproduzidos nesta sessão. Isso não cobria os cenários acima.
- Regressões adicionais: `tests/test_intermediate_review.py`, com reprodução de sobrescrita, mistura de buffers, commentary, item antigo, erro/cancelamento, isolamento VR, finalizador antigo, replay e consumidores de providers.
- Um teste antigo de paridade VR/Ultra comparava também o payload completo. Foi ajustado para comparar o conteúdo de roteamento/contrato, excluindo apenas os novos metadados de execução e ordenação, que necessariamente diferem entre pedidos distintos.
- Teste real: `smoke-provider-result.json`, produzido por `smoke_provider.py --live`. Projeto e SQLite temporários, dois pedidos curtos, perfil supervisionado, nenhuma instalação ou alteração de autenticação. O resultado verifica que a resposta A continua presente após B e os IDs são distintos.
- QML: `smoke-visual-result.json`, `qml-timeline.png` e `qml-timeline-active.png`. Fixture determinística de três mensagens e duas atividades; captura ativa mostra a única Task Bar existente em 2/3. Inspeção visual realizada e sem avisos QML no smoke. Fontes locais foram carregadas explicitamente apenas no script offscreen.
- Resultado da última suíte completa e comandos: `VALIDACAO_FINAL.md` nesta pasta.

Os screenshots representam uma fixture de interface, não uma conversa real com provider. As fixtures de protocolo não equivalem a certificar todas as versões instaladas dos CLIs.

## Arquivos da correção

Produção: `vrsoft_extractor/mary/db.py`, `orchestrator.py`, `providers.py`, `frontend/chat.py`, `frontend/qml/pages/ChatPreview.qml`. Testes: `tests/test_intermediate_review.py`, ajuste semântico em `tests/test_mary_vr_ultra.py`. Também foi removida uma linha vazia excedente no fim de `pyproject.toml`; a configuração pytest acrescentada pelo Opus foi mantida.

Esta revisão manteve as alterações preexistentes. Não foi feito commit, release ou instalação do aplicativo. Ao iniciar o código atualizado, o mecanismo existente aplicará a migração aditiva ao banco utilizado pelo aplicativo.

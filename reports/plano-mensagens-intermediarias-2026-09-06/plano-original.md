# Prompt — Mensagens intermediárias do Assistant + Harness + Integração com Task Bar Existente

Quero evoluir o sistema de execução/chat deste projeto para suportar
mensagens intermediárias reais do assistant durante uma tarefa,
seguindo os PRINCÍPIOS arquiteturais do T3 Code, porém adaptando-os
à arquitetura JÁ EXISTENTE deste projeto.

Referência:

https://github.com/pingdotgg/t3code


IMPORTANTE:

NÃO faça rewrite do harness.

NÃO substitua a arquitetura Python/QML existente por React,
WebSocket, RPC ou qualquer arquitetura do T3 Code.

NÃO recrie funcionalidades que já existem.

NÃO recrie a barra de Tasks.

NÃO recrie o composer.

NÃO recrie a persistência de conversa.

NÃO recrie o sistema de providers se a abstração atual já resolver
corretamente determinado problema.

Antes de implementar qualquer alteração, AUDITE o código atual e
classifique cada requisito deste prompt como:

EXISTENTE
PARCIAL
AUSENTE
PRECISA CORREÇÃO

Depois implemente SOMENTE:

PARCIAL
AUSENTE
PRECISA CORREÇÃO


==================================================
BASELINE JÁ CONHECIDO DO PROJETO
==================================================

A arquitetura atual já possui aproximadamente:

ChatPreview.qml
        ↓
ChatBridge.sendMessage
        ↓
ChatOrchestrator.send
        ↓
MaryDatabase.begin_user_turn
        ↓
provider
        ↓
RuntimeEvent
        ↓
ChatOrchestrator._handle_event
        ↓
finalização
        ↓
messages / conversations
        ↓
ChatBridge
        ↓
QML


O projeto é desktop:

Python
+
Qt Quick / QML

A comunicação interna utiliza:

properties
slots
signals

Portanto:

NÃO introduza HTTP interno,
NÃO introduza WebSocket interno,
NÃO introduza RPC apenas para copiar o T3 Code.

Utilize os mecanismos atuais.


==================================================
FUNCIONALIDADES QUE DEVEM SER PRESERVADAS
==================================================

Preserve integralmente o funcionamento atual de:

- Task Bar existente;
- composer existente;
- streaming atual;
- histórico de conversas;
- SQLite;
- ChatBridge;
- ChatOrchestrator;
- providers existentes;
- cancelamento;
- VR direto;
- VR Ultra;
- General Harness, caso já implementado;
- modos de execução existentes;
- contexto de continuação;
- fontes/citações;
- pesquisas de código;
- autenticação dos providers;
- instalações dos providers;
- configurações por conversa.

Não substitua sistemas funcionais apenas para deixar o código mais
parecido com T3 Code.


==================================================
OBJETIVO PRINCIPAL
==================================================

Hoje quero que uma única execução possa produzir:

USER

"Refatore a tela de providers."


ASSISTANT

"Vou primeiro localizar a implementação da tela e entender o fluxo
atual antes de alterar qualquer coisa."


WORK / ACTIVITY

✓ Leu ProviderSettings
✓ Localizou estilos
● Analisando integração com providers


ASSISTANT

"Encontrei a estrutura. A lógica dos providers já está separada,
então vou preservar o backend e alterar somente a apresentação."


WORK / ACTIVITY

✓ Alterou ProviderSettings
● Executando testes


TASK BAR EXISTENTE

Tasks   Executar testes   2/4


ASSISTANT

"Os testes passaram. Agora vou validar os estados de autenticação."


WORK / ACTIVITY

✓ Validou provider autenticado
✓ Validou provider sem autenticação


ASSISTANT

"Concluído. A tela foi refinada..."


TUDO ISSO pertence ao MESMO TURN.

Não criar novos turns para cada mensagem intermediária.


==================================================
CONCEITOS QUE DEVEM PERMANECER SEPARADOS
==================================================

Existem três conceitos independentes:


1. ASSISTANT MESSAGE

Texto deliberadamente enviado pelo modelo para o usuário.

Exemplo:

"Vou analisar primeiro a arquitetura."

"Encontrei o componente responsável."

"Os testes passaram. Vou validar o resultado."


2. TASK / PLAN

Planejamento de alto nível.

A Task Bar atual já representa isso.

Exemplo:

✓ Analisar arquitetura
● Implementar streaming
○ Executar testes
○ Validar


3. WORK / AGENT ACTIVITY

Operações executadas.

Exemplo:

Read file
Search
Edit
Run command
Tool call
MCP
Subagent
Web search


REGRA:

AssistantMessage != Task != WorkActivity


Não transformar automaticamente:

tool call

em:

assistant message


Não transformar automaticamente:

mudança da Task Bar

em:

assistant message


Não transformar:

assistant message

em:

Task.


==================================================
TASK BAR — JÁ EXISTE
==================================================

A função equivalente a:

Tasks   Implementar streaming   2/5   ▬ ▬ ▬ ▬ ▬

JÁ EXISTE.

NÃO recriar.

NÃO redesenhar sem necessidade.

NÃO criar outro sistema de Tasks.

NÃO criar outro estado de plano paralelo.


Primeiro localize a implementação existente.

Identifique:

- onde o plano é armazenado;
- como steps são atualizados;
- como completed/total é calculado;
- como current task é determinada;
- quais eventos alimentam a barra;
- como ela é ligada ao turn atual.


Depois apenas integre o novo lifecycle de mensagens/turnos ao sistema
existente.


A Task Bar deve continuar funcionando normalmente enquanto mensagens
intermediárias aparecem.


Exemplo:

Assistant:
"Vou localizar o fluxo."

Task Bar:
Tasks   Analisar arquitetura   0/4

Work:
Read files


Assistant:
"Encontrei o fluxo."

Task Bar:
Tasks   Implementar alteração   1/4

Work:
Edit files


Nenhum desses sistemas deve depender artificialmente do outro.


==================================================
AUDITORIA OBRIGATÓRIA ANTES DA ALTERAÇÃO
==================================================

Antes de escrever código, localize e documente:

1. RuntimeEvent atual.

2. Todos os tipos/kinds de RuntimeEvent existentes.

3. Como cada provider produz eventos.

4. Como Codex streaming funciona.

5. Como Claude streaming funciona.

6. Como OpenCode streaming funciona.

7. Como Antigravity streaming funciona.

8. Como ChatOrchestrator._handle_event trata cada evento.

9. Onde o texto parcial do assistant é acumulado.

10. Como a resposta final é persistida.

11. Como turn_id é criado.

12. Como turn_id é propagado.

13. Como callbacks são associados ao provider.

14. Como um callback é removido.

15. Como cancelamento funciona.

16. Como retry funciona.

17. Como eventos atrasados são tratados.

18. Como messages são armazenadas no SQLite.

19. Se existe identidade separada entre:
    conversation
    turn
    assistant item/message

20. Como a Task Bar atual recebe updates.

21. Como Work/Activity é representado atualmente.

22. Como QML recebe atualizações incrementais.

23. Como histórico é reconstruído ao abrir uma conversa.

24. Como uma conversa ativa é restaurada.

25. Quais testes já cobrem esses fluxos.


Crie inicialmente uma tabela interna:

FEATURE                       STATUS

Task Bar                      EXISTENTE
Turn identity                 ?
Assistant streaming           ?
Multiple assistant messages   ?
Work activity                 ?
Provider normalization        ?
Reconnect/reload              ?
Persistence                   ?
Late event protection         ?
Cancellation                  ?
Ordering                      ?


Só depois implemente.


==================================================
PRIORIDADE ZERO — CORRIGIR IDENTIDADE DE TURN
==================================================

Existe histórico de problema no projeto onde eventos antigos de um
turn podem atingir um novo turn.

Portanto esta mudança NÃO pode ser implementada em cima de associação
frágil baseada apenas em:

conversation_id

ou:

thread_id


Todo RuntimeEvent relacionado a execução deve possuir identidade
suficiente para determinar exatamente a qual execução pertence.

Preferência:

conversation_id
turn_id

e quando aplicável:

item_id
message_id
event_id


Exemplo conceitual:

RuntimeEvent(
    conversation_id=...,
    turn_id=...,
    item_id=...,
    event_id=...,
    kind=...
)


O formato concreto deve respeitar o código atual.


==================================================
REGRA DE ISOLAMENTO
==================================================

Se:

Turn A encerrou

e:

Turn B está ativo


e chegar atrasado:

delta de A

ou:

completed de A


o sistema deve:

ignorar com segurança
OU
encaminhar ao estado histórico correto de A


NUNCA:

append no conteúdo de B

NUNCA:

finalizar B

NUNCA:

remover callback de B

NUNCA:

alterar status da conversa como se B tivesse terminado.


==================================================
CALLBACKS
==================================================

Audite os callbacks atuais dos providers.

Se atualmente forem associados apenas por:

threadId

ou:

conversationId


corrija para identidade de execução.


Conceitualmente:

callbacks[
    (thread_id, turn_id)
]


ou abstração equivalente.


Não exigir exatamente tuple se a arquitetura possuir um objeto de sessão
melhor.


==================================================
BUFFERS
==================================================

O texto em streaming também precisa pertencer a uma mensagem específica.

EVITAR:

assistant_buffer[conversation_id]


Preferir conceitualmente:

assistant_buffer[
    turn_id,
    message_id
]


Isso é obrigatório para suportar:

assistant message #1
tool
assistant message #2
tool
assistant message #3

dentro do mesmo turn.


==================================================
MULTIPLE ASSISTANT MESSAGES PER TURN
==================================================

A arquitetura não pode assumir:

1 turn = 1 assistant response.


Preciso suportar:

Turn T1

AssistantMessage M1
"Vou analisar primeiro."

Tool activity

AssistantMessage M2
"Encontrei o componente."

Tool activity

AssistantMessage M3
"Alteração feita. Vou testar."

Tool activity

AssistantMessage M4
"Concluído."


Todos:

turn_id = T1


Mas:

message_id M1 != M2 != M3 != M4


==================================================
ASSISTANT ITEM IDENTITY
==================================================

Cada segmento/mensagem de assistant deve possuir identidade estável.

Preferência de origem:

provider item/message ID

Quando provider não fornecer:

gerar identidade local estável vinculada ao turn.


Exemplo:

assistant:<provider_item_id>


Fallback aceitável:

assistant:<turn_id>:<sequence>


Não utilizar somente:

assistant:<turn_id>


pois isso impossibilita várias mensagens dentro do mesmo turn.


==================================================
RUNTIME EVENT MODEL
==================================================

Não copie cegamente os nomes do T3.

Primeiro analise RuntimeEvent existente.

Se o modelo atual conseguir representar corretamente esses estados,
estenda-o.

Se não conseguir, introduza o mínimo necessário.


Conceitualmente precisamos distinguir:

TURN_STARTED

ASSISTANT_STARTED
ASSISTANT_DELTA
ASSISTANT_COMPLETED

TOOL_STARTED
TOOL_UPDATED
TOOL_COMPLETED

TASK/PLAN_UPDATED

TURN_COMPLETED

TURN_FAILED
TURN_CANCELLED


Os nomes reais devem seguir as convenções Python atuais.


==================================================
ASSISTANT STREAMING
==================================================

Lifecycle desejado:

assistant.started
    message_id=M1

assistant.delta
    message_id=M1
    delta="Vou"

assistant.delta
    message_id=M1
    delta=" analisar"

assistant.delta
    message_id=M1
    delta=" primeiro."

assistant.completed
    message_id=M1


A UI deve atualizar M1.

NÃO criar:

M1 = "Vou"
M2 = " analisar"
M3 = " primeiro."


==================================================
ASSISTANT COMPLETED != TURN COMPLETED
==================================================

Esta distinção é obrigatória.

Pode acontecer:

assistant M1 completed

↓

tool

↓

assistant M2 completed

↓

tool

↓

assistant M3 completed

↓

turn completed


Não finalize a conversa quando uma AssistantMessage termina.


Somente evento real de:

TURN_COMPLETED

deve encerrar lifecycle do turn.


==================================================
PROVIDERS
==================================================

A arquitetura atual possui providers.

Não reescreva todos.

Faça uma camada de normalização mínima no limite de cada provider.


Objetivo:

Codex native events
        ↓
Codex mapping
        ↓
RuntimeEvent


Claude native events
        ↓
Claude mapping
        ↓
RuntimeEvent


OpenCode native events
        ↓
OpenCode mapping
        ↓
RuntimeEvent


Antigravity native events
        ↓
Antigravity mapping
        ↓
RuntimeEvent


ChatOrchestrator deve consumir o contrato comum.


==================================================
NÃO ESPALHAR IF DE PROVIDER
==================================================

Evitar no ChatOrchestrator:

if provider == "codex":
    ...

elif provider == "claude":
    ...

elif provider == "antigravity":
    ...


para interpretar o significado semântico de eventos.


Diferenças de protocolo devem ser normalizadas perto do provider.


==================================================
PROVIDERS SEM INTERMEDIATE MESSAGES
==================================================

Nem todo provider necessariamente produz várias AssistantMessages
durante uma execução.

Isso é válido.


Provider A:

assistant
tool
assistant
tool
assistant


Provider B:

tool
tool
assistant


Provider C:

assistant


Todos devem funcionar.


NÃO inventar mensagens em providers que não enviem isso.


==================================================
NÃO SIMULAR PROGRESSO
==================================================

PROIBIDO implementar:

QTimer
sleep
setTimeout equivalente
mensagens hardcoded


como:

"Analisando..."
"Lendo arquivos..."
"Preparando resposta..."


Não gerar conversa falsa a partir de activity.


O texto precisa vir do provider/modelo.


==================================================
PREAMBLES / INTERMEDIATE ASSISTANT OUTPUT
==================================================

Quando o provider realmente produzir texto destinado ao usuário antes
de uma tool call, preserve-o como AssistantMessage.


Exemplo nativo:

assistant text
→ tool call
→ assistant text
→ tool call
→ assistant text


Não concatenar tudo somente no final.


Isso é o comportamento principal que quero obter.


==================================================
WORK / ACTIVITY
==================================================

Audite o que já existe.

Se houver sistema atual de activity:

REUTILIZE.


Tool events continuam sendo activity.


Exemplo:

Read file
Search
Apply patch
Run command
MCP
Subagent


Não salvar isso como mensagem conversacional do assistant.


==================================================
WORK LOG VISUAL
==================================================

Se a UI já possui visualização de trabalho:

preserve-a.


Se existe apenas texto/debug bruto:

refine somente o necessário para representar eventos reais.


Não exponha chain-of-thought interno.


Mostrar:

atividade observável

não:

raciocínio privado do modelo.


==================================================
TASK BAR EXISTENTE + NOVO FLOW
==================================================

A Task Bar continua sendo a visão do plano.


AssistantMessage:

o agente conversa.


Task Bar:

o agente mostra onde está no plano.


Activity:

o sistema mostra operações realizadas.


Exemplo final esperado:


Assistant

"Vou primeiro verificar como o provider entrega os eventos."


Tasks
● Analisar provider events                   0/4


Work

✓ Read providers.py
✓ Read orchestrator.py


Assistant

"O provider já entrega IDs suficientes. Vou usá-los para isolar
cada message segment."


Tasks
✓ Analisar provider events
● Implementar turn identity                  1/4


Work

✓ Edit providers.py
✓ Edit orchestrator.py


Assistant

"A identidade já está isolada. Agora vou testar eventos atrasados."


Tasks
✓ Analisar provider events
✓ Implementar turn identity
● Testar late events                         2/4


Work

● Running tests


Assistant

"Os testes passaram."


Essa composição é o objetivo.


==================================================
TIMELINE
==================================================

Analise como ChatPreview.qml representa atualmente a conversa.

A timeline deve conseguir intercalar cronologicamente:

UserMessage
AssistantMessage
Activity
AssistantMessage
Activity
AssistantMessage


Não renderizar necessariamente tudo em um único ListModel se a
arquitetura atual possuir solução melhor.


Mas a ordem visual precisa refletir a ordem real dos eventos.


==================================================
EVENT ORDERING
==================================================

Não confiar exclusivamente em horário de parede se eventos podem
chegar no mesmo milissegundo.


Utilizar preferencialmente:

sequence

ou:

event order gerado pelo runtime


com identidade estável.


Se RuntimeEvent atual já possui ordering:

reutilize.


==================================================
QML MODEL
==================================================

Não obrigue QML a entender protocolos de provider.

QML deve receber tipos semânticos como:

user_message

assistant_message

activity

ou o modelo equivalente existente.


Não enviar para QML:

codex/event/item/completed
claude/content_block_delta

e exigir interpretação no frontend.


==================================================
PERSISTÊNCIA
==================================================

Antes de mudar schema:

audite a tabela messages.


Determine se hoje existe:

uma única assistant row por turn

ou:

suporte para múltiplas rows.


Se múltiplas mensagens já forem suportadas:

REUTILIZE.


Se não forem:

implemente a menor migration compatível possível.


Preservar leitura de históricos antigos.


==================================================
MODELO DE MENSAGEM
==================================================

Conceitualmente uma AssistantMessage deve conseguir representar:

id
conversation_id
turn_id
provider_item_id?
sequence
content
streaming/completed
created_at


Não adicione campos redundantes se o banco atual já possuir equivalentes.


==================================================
STREAMING + DATABASE
==================================================

Evite gravar uma transação SQLite a cada token se o sistema atual não
faz isso.


Pode manter conteúdo parcial em memória e persistir em:

checkpoint razoável

ou:

assistant.completed


desde que:

- crash/restart behavior seja conscientemente tratado;
- final state seja correto;
- UI continue streaming.


Preserve a estratégia atual quando ela for segura.


==================================================
RELOAD
==================================================

Ao fechar e reabrir uma conversa concluída:

AssistantMessages intermediárias devem continuar aparecendo na ordem
correta, se forem consideradas parte persistente da conversa.


Exemplo:

User

Assistant preamble

Assistant intermediate

Assistant final


não deve virar apenas:

User

Assistant final


a menos que a arquitetura/produto deliberadamente decida que
intermediates são efêmeras.


Decida explicitamente e documente.


Preferência:

persistir mensagens realmente destinadas ao usuário.


==================================================
RECONNECT / PROVIDER SESSION
==================================================

Analise o comportamento existente de retomada/reconexão.

Não invente um novo sistema.


Mas garanta que eventos antigos após uma retomada não sejam aceitos
como pertencentes ao turn atual.


==================================================
LATE EVENTS
==================================================

Adicionar testes específicos:

Turn 1:
delta
completed

Turn 2:
started

então receber novamente:

Turn 1 delta

Turn 1 completed


Resultado obrigatório:

Turn 2 permanece intacto.

callback Turn 2 permanece ativo.

buffer Turn 2 permanece correto.

conversa permanece running enquanto Turn 2 estiver executando.


==================================================
DUPLICATE EVENTS
==================================================

Se provider reenviar o mesmo evento:

não duplicar conteúdo.


Audite se existe event ID ou mecanismo equivalente.


Se existir:

usar dedup existente.


Se não:

implementar dedup somente onde houver identidade confiável.


Não fazer dedup baseado apenas no texto.


==================================================
CANCELLATION
==================================================

Cancelar um turn deve:

interromper provider

marcar aquele turn como cancelled/interrupted

fechar somente mensagens daquele turn

não interferir em histórico anterior

não deixar Task Bar presa

não deixar callback órfão

não aceitar completed tardio daquele turn como conclusão válida de
um turn futuro.


==================================================
ERROR
==================================================

Provider error deve possuir turn identity.

Erro de Turn A não pode aparecer como erro de Turn B.


Se AssistantMessage estava streaming:

fechar/cancelar seu lifecycle corretamente.


==================================================
FINAL MESSAGE
==================================================

Não criar obrigatoriamente uma entidade especial:

FinalAnswer


se não houver necessidade.


A última AssistantMessage antes de TURN_COMPLETED pode ser simplesmente
a resposta final.


O final do turn é definido pelo lifecycle, não pelo texto.


==================================================
HARNESS GERAL / VR
==================================================

Não acoplar este recurso ao domínio VR.


A camada de mensagens e events deve funcionar tanto em:

NATIVE_DIRECT

VR_DIRECT

GENERAL_ORCHESTRATED

VR_ORCHESTRATED


se esses perfis estiverem presentes na árvore atual.


A infraestrutura comum de execução não deve importar lógica VR
apenas para suportar intermediate messages.


==================================================
VR ULTRA
==================================================

Preserve:

pesquisadores
merge
validação
rewrite
síntese
fontes


Não transformar output interno de workers em mensagens do usuário.


Workers continuam produzindo material interno.


Somente o agente/supervisor responsável pela conversa pode emitir
AssistantMessage para o usuário.


==================================================
SUBAGENTS
==================================================

Subagent output NÃO é automaticamente AssistantMessage.


Exemplo:

Subagent:
"Found 14 files..."

deve continuar Activity/internal result.


Somente conteúdo explicitamente publicado pelo main agent vira
AssistantMessage.


==================================================
CHAIN OF THOUGHT
==================================================

Não exponha reasoning privado.


Não converter:

reasoning tokens
thinking
scratchpad


em mensagens intermediárias.


Intermediate AssistantMessage deve ser texto deliberadamente público.


==================================================
TASK BAR — INTEGRAÇÃO APENAS
==================================================

Como a Task Bar já existe:

não altere sua arquitetura sem necessidade.


Garanta somente:

1. ela continua vinculada ao turn correto;

2. um completed de AssistantMessage não a encerra;

3. somente completion real do turn encerra seu estado ativo;

4. late events não alteram a Task Bar do turn atual;

5. cancelamento limpa o plano atual corretamente;

6. intermediate messages não resetam o progresso;

7. troca de AssistantMessage dentro do mesmo turn não cria um novo
   plano;

8. reload/reopen preserva o comportamento atual.


==================================================
PERFORMANCE
==================================================

Streaming textual pode emitir muitos deltas.


Não fazer:

reload completo do histórico

a cada delta.


Não reconstruir toda ListModel se for desnecessário.


Atualize somente a mensagem atual.


Se necessário:

buffer pequeno
batch de UI
coalescing curto


Mas NÃO atrasar semantic events.


Nunca coalescer:

assistant started
assistant completed
turn completed
error
approval


Tool/progress visual pode ser coalescido se já houver excesso de eventos.


==================================================
QML PERFORMANCE
==================================================

Evitar:

recriar delegates inteiros

resetar ListModel inteiro

recalcular Markdown completo de todas mensagens


a cada token.


Preferir atualizar:

content da row correspondente a message_id.


==================================================
SCROLL
==================================================

Preserve o comportamento atual do chat.


Durante intermediate messages:

se usuário estiver no final:
seguir streaming.


Se usuário estiver lendo histórico:
não puxar scroll forçadamente.


Não gerar layout jump ao alternar:

AssistantMessage
Activity
Task update.


==================================================
PROVIDER-SPECIFIC AUDIT
==================================================

Para cada provider atualmente suportado, documente:

Provider
Native event
Assistant start
Assistant delta
Assistant complete
Tool start/update/complete
Turn complete
Item ID disponível?
Turn ID disponível?
Multiple assistant items?


Faça isso para todos os providers existentes na árvore.


Não assumir comportamento com base apenas no T3 Code.


Valide no SDK/protocolo realmente usado por este projeto.


==================================================
CODEX
==================================================

Inspecione especialmente:

CodexProvider._handle_server_message


Mapeie:

threadId
turnId
itemId
event id
assistant text
tool calls
turn completion


Corrija associação de callbacks/buffers para que eventos antigos não
atinjam o turn novo.


==================================================
CHAT ORCHESTRATOR
==================================================

Inspecione especialmente:

ChatOrchestrator.send
ChatOrchestrator._handle_event
ChatOrchestrator._finalize_turn_completed


Não permita mais agregação de assistant output baseada apenas em
conversation.


O estado deve conhecer explicitamente:

turn atual

mensagem assistant atual

items daquele turn.


==================================================
MARY DATABASE
==================================================

Preserve a atomicidade de:

begin_user_turn


Não enfraquecer o bloqueio de dois envios simultâneos.


A nova identidade de mensagem deve complementar o lifecycle existente,
não substituí-lo por estado menos seguro.


==================================================
COMPATIBILIDADE DE HISTÓRICO
==================================================

Banco antigo deve continuar abrindo.


Conversas antigas devem continuar renderizando.


Não faça migration destrutiva.


Se schema migration for necessária:

versionar
migrar automaticamente
testar base antiga


==================================================
OBSERVABILIDADE DEV
==================================================

Em debug/dev mode quero conseguir rastrear:

provider-native event
        ↓
RuntimeEvent
        ↓
turn_id
message_id/item_id
        ↓
ChatOrchestrator
        ↓
DB/UI


Sem exibir isso ao usuário normal.


Logs úteis:

provider
conversation_id
turn_id
item_id
event kind
sequence


Nunca logar secrets/tokens.


==================================================
TESTES OBRIGATÓRIOS
==================================================

Preserve toda suíte existente.


Adicionar testes para:


A)

User
Assistant final
Turn completed


B)

User
Assistant #1
Tool
Assistant #2
Turn completed


C)

Assistant #1
Tool
Assistant #2
Tool
Assistant #3
Turn completed


D)

Tool
Tool
Assistant final


E)

Dois AssistantMessages no mesmo turn possuem IDs diferentes.


F)

Deltas da mesma AssistantMessage são concatenados na mesma mensagem.


G)

assistant.completed não encerra turn.


H)

turn.completed encerra turn.


I)

late delta de turn anterior é rejeitado.


J)

late completed de turn anterior não encerra turn atual.


K)

duplicate event não duplica conteúdo quando event identity permitir.


L)

cancelamento durante streaming.


M)

provider error durante streaming.


N)

Task Bar continua ativa entre AssistantMessages do mesmo turn.


O)

Task Bar encerra somente quando turn termina/cancela.


P)

Task Bar não é resetada quando M1 termina e M2 começa.


Q)

histórico antigo continua carregando.


R)

nova conversa com intermediate messages recarrega corretamente.


S)

VR_DIRECT continua funcionando.


T)

VR_ORCHESTRATED continua funcionando.


U)

NATIVE_DIRECT continua funcionando.


V)

GENERAL_ORCHESTRATED continua funcionando, se existir.


==================================================
VALIDAÇÃO REAL
==================================================

Além de unit tests:

execute pelo menos um provider real quando o ambiente permitir.


Observe uma sessão completa.


Capture em log dev:

turn started

assistant message 1

tool

assistant message 2

tool

assistant final

turn completed


Se o provider testado não produzir intermediate assistant messages:

isso NÃO é falha da implementação.


Valide então:

tool
tool
assistant final


e documente que aquele provider não emitiu intermediates no cenário.


==================================================
NÃO FORÇAR O MODELO
==================================================

Primeiro determine se provider/model já envia preambles/intermediate
assistant items.


Se for necessário adicionar instrução de comportamento ao prompt do
coding agent, faça isso somente depois da infraestrutura suportar
corretamente várias AssistantMessages.


A infraestrutura vem primeiro.


Não tente resolver limitação arquitetural apenas com system prompt.


==================================================
PROMPT BEHAVIOR — SE NECESSÁRIO
==================================================

Somente se a arquitetura já suportar multiple assistant messages e
o provider permitir esse comportamento, adicione instrução semelhante:

"Durante tarefas longas, mantenha o usuário informado com mensagens
curtas e úteis antes de grupos significativos de ações.

Exemplos:

'Vou localizar primeiro onde esse fluxo é implementado.'

'Encontrei o componente. Vou preservar o backend e alterar somente
a camada visual.'

'Os testes passaram. Agora vou validar o caso de erro.'

Não envie updates para cada tool call.

Envie apenas atualizações quando houver mudança significativa de fase."


Não transformar isso em spam.


==================================================
CADÊNCIA DAS MENSAGENS
==================================================

Não quero:

"Vou ler arquivo."
"Li arquivo."
"Vou abrir outro."
"Abri."
"Vou pesquisar."
"Pesquisei."


Quero:

"Vou analisar primeiro a implementação atual."

[5–20 operações]

"Encontrei a causa. Vou corrigir a associação do evento ao turn."

[operações]

"A correção passou nos testes. Vou verificar regressões."


Updates baseados em MUDANÇA DE FASE, não em tool count.


==================================================
CRITÉRIO DE SUCESSO VISUAL
==================================================

Uma execução longa deve ficar aproximadamente:


USER
Corrija o streaming.


ASSISTANT
Vou analisar primeiro como os eventos do provider chegam ao
orquestrador.


TASKS
● Analisar eventos                         0/4


WORK
✓ Read providers.py
✓ Read orchestrator.py
✓ Search RuntimeEvent


ASSISTANT
Encontrei o problema de identidade do turn. Vou corrigir o vínculo
dos callbacks e buffers antes de mexer no frontend.


TASKS
✓ Analisar eventos
● Corrigir identidade                      1/4


WORK
✓ Edit providers.py
✓ Edit orchestrator.py


ASSISTANT
A associação agora está isolada por turn. Vou executar os testes de
eventos atrasados.


TASKS
✓ Analisar eventos
✓ Corrigir identidade
● Testar eventos atrasados                 2/4


WORK
● pytest ...


ASSISTANT
Os testes de concorrência passaram. Agora vou validar o QML e a
persistência.


TASKS
✓ Analisar eventos
✓ Corrigir identidade
✓ Testar eventos atrasados
● Validar interface                        3/4


WORK
✓ QML tests
✓ persistence tests


ASSISTANT
Concluído...


TASKS
4/4

Turn completed


==================================================
IMPLEMENTAÇÃO INCREMENTAL
==================================================

Faça nesta ordem:


FASE 1 — AUDIT

Mapear implementação existente.


FASE 2 — TURN IDENTITY

Corrigir isolamento de eventos/callbacks/buffers.


FASE 3 — ASSISTANT ITEM IDENTITY

Permitir múltiplas mensagens por turn.


FASE 4 — PROVIDER NORMALIZATION

Normalizar eventos necessários.


FASE 5 — ORCHESTRATOR

Processar assistant lifecycle independentemente de turn lifecycle.


FASE 6 — PERSISTENCE

Persistir múltiplas mensagens se necessário.


FASE 7 — QML

Intercalar mensagens/activity sem quebrar UI atual.


FASE 8 — TASK BAR INTEGRATION

Apenas garantir vínculo correto com o mesmo turn.
NÃO recriar a barra.


FASE 9 — CANCELLATION / ERROR / LATE EVENTS

Cobrir lifecycle adverso.


FASE 10 — TESTS

Adicionar regressões e executar suíte completa.


FASE 11 — REAL PROVIDER VALIDATION

Validar fluxo real quando disponível.


==================================================
PROIBIÇÕES
==================================================

NÃO:

- rewrite geral;
- remover SQLite;
- trocar QML;
- criar React;
- criar frontend web;
- criar protocolo HTTP interno;
- criar WebSocket desnecessário;
- duplicar Task Bar;
- duplicar sistema de plano;
- inventar progress messages;
- expor chain-of-thought;
- persistir tool output como assistant message;
- tratar worker output como resposta;
- usar conversation_id como única identidade;
- usar thread_id como única identidade;
- considerar assistant.complete equivalente a turn.complete;
- apagar compatibilidade com histórico antigo.


==================================================
ENTREGA FINAL
==================================================

No final me entregue um relatório objetivo:


1. AUDITORIA DO EXISTENTE

Para cada requisito:

EXISTENTE
PARCIAL
IMPLEMENTADO
NÃO APLICÁVEL


2. O QUE JÁ EXISTIA

Liste explicitamente tudo que foi reutilizado.


3. O QUE FOI ALTERADO


4. ARQUITETURA ANTES


5. ARQUITETURA DEPOIS


6. EVENT FLOW

Exemplo real:

Provider event
→ RuntimeEvent
→ ChatOrchestrator
→ DB
→ ChatBridge
→ QML


7. IDENTIDADE

Explique como:

conversation_id
turn_id
message_id
item_id
event_id

se relacionam.


8. PROVIDERS

Tabela:

provider
multiple assistant messages
item id
turn id
tools
limitações


9. TASK BAR

Confirme explicitamente:

"Task Bar existente foi reutilizada e não duplicada."


10. TESTES

Informe:

testes existentes
testes novos
total executado
falhas


11. MIGRATIONS

Se houver.


12. LIMITAÇÕES RESTANTES


==================================================
CONDIÇÃO DE CONCLUSÃO
==================================================

Não considere a tarefa concluída até provar que:


- a Task Bar existente continua funcionando;

- um turn suporta múltiplas AssistantMessages;

- intermediate AssistantMessages podem aparecer antes/depois de tools;

- AssistantMessage completion não encerra o turn;

- turn completion encerra corretamente;

- eventos atrasados não contaminam outro turn;

- callbacks não são removidos pelo turn errado;

- buffers não misturam respostas;

- cancelamento funciona;

- histórico antigo continua funcionando;

- QML continua estável;

- providers sem intermediate messages continuam funcionando;

- VR e harness geral não foram acoplados indevidamente;

- toda a suíte anterior continua passando.


Faça a auditoria primeiro.

Reutilize o máximo possível.

Implemente somente o que estiver faltando.

Plano auditado de acesso unificado — OFF, VR e ULTRA
===================================================

**Estado atual (VRTOOL-001, 22/09/2026).** O modo `vr` passou a ser tool-driven. O modelo principal recebe um contrato VR estável (identidade, fontes disponíveis e política de grounding) e decide consultar Wiki, KB, Schema e Código por `vr_sources`/`vr_search`/`vr_read`; não há retrieval automático antes da resposta nem bundle inicial preenchido por busca. `vr_search` sem `source` executa as quatro lanes determinísticas em paralelo (ordem fixa wiki, kb, schema, code) e devolve um resultado consolidado; com `source`, consulta somente a fonte escolhida. O chat VR não oferece filtro por módulo: a unidade de consulta é a fonte. Validação e citações usam somente as evidências realmente retornadas pelas tools durante o turno. O modo `ultra` mantém fan-out, síntese validada e agente DEV Java. Prefetch/cache de consulta não pertencem a este contrato. Os perfis Adaptativa, implantação, suporte e treinamento formam uma camada comportamental sobre o mesmo mecanismo de retrieval, sem alterar fontes, tools ou fan-out. As seções e tabelas abaixo são o registro histórico da auditoria original de 09/09/2026.

Entrega para implementação pelo Gemini 3.8. Auditoria em 09/09/2026, sobre o checkout `D:\Codex\VRStudio`, HEAD `afc7d98`, incluindo as alterações locais existentes. Este documento especifica a implementação; o código de produção não foi alterado nesta auditoria. As linhas citadas correspondem a esse estado e devem ser conferidas novamente antes da edição.

**Estado atual (OFF-002).** O OFF é um fluxo de modelo direto: não registra nem executa `vr_sources`, `vr_search` ou `vr_read` e não executa retrieval automático, `RetrievalService`, `KnowledgeRouter`, fan-out ou agentes VR. O turno OFF recebe o workspace/projeto e a raiz de fontes configurada (`MarySettings.root`) como contexto opcional somente leitura e usa as capacidades nativas do provider para listar, buscar e ler arquivos; o modelo pode responder sem consultar a raiz. VR e Ultra mantêm as três tools VR, o contrato tool-driven, o fan-out, a síntese e o fallback atuais. As menções a `native_vr_search_enabled`, `VR_NATIVE_SEARCH_ENABLED` e à disponibilidade das tools em todos os modos descrevem apenas o estado auditado em 09/09/2026 e não representam o contrato atual.

**Problema.** O plano original aponta a direção correta, mas suas quatro fases ainda não garantem que os três modos consultem Wiki, KB, Schema e Java. Faltam transporte efetivo nos provedores, descoberta e leitura além do primeiro resultado da busca, limites compartilhados de evidências, tratamento de conversas existentes e persistência das fontes de código.

O requisito de aceite é: **o modo controla a estratégia de resposta; todos os modos oferecem acesso às mesmas fontes locais configuradas e disponíveis**. Isso inclui todos os arquivos de conhecimento dessas fontes e o código descompilado dos aplicativos e dependências dos contextos consultados. A busca inicial pode selecionar poucos trechos, mas nenhum arquivo elegível pode ficar inacessível por causa de OFF, VR ou ULTRA.

| Modo | Acesso exigido | Trabalho automático | Profundidade |
| --- | --- | --- | --- |
| OFF | Projetos e fontes como no ChatGPT Web; descobrir, buscar e ler Wiki, KB, Schema e Java sob demanda | Aplicar instruções do projeto e disponibilizar fontes, anexos e ferramentas | O provedor decide quando consultar conteúdo; sem RAG antecipado nem fan-out |
| VR | As mesmas ferramentas e fontes | Nenhum retrieval antes da chamada ao modelo: contrato VR estável e tools disponíveis; `vr_search` sem fonte consulta Wiki, KB, Schema e Código em paralelo | Uma resposta principal, com consulta sob demanda por `vr_sources`/`vr_search`/`vr_read` |
| ULTRA | As mesmas ferramentas e fontes | Recuperação comum e investigação especializada | Fan-out, agente de código quando pertinente, síntese e validação |

“Todas as fontes disponíveis” permite consultar todo o acervo elegível; não exige inserir todos os arquivos no prompt nem usar as quatro fontes em toda resposta. Fontes desativadas, documentos em revisão e índices pendentes precisam de estados explícitos e das regras existentes de curadoria, iguais nos três modos. A configuração de aplicativo/versão delimita a interpretação do Java, sem tornar o restante do catálogo invisível.

**Requisito adicional do usuário — OFF com projetos e fontes como no ChatGPT Web.** O botão OFF deve manter comportamento funcional equivalente ao ChatGPT Web no uso de projetos e fontes: a conversa recebe o contexto do projeto selecionado e pode consultar seus materiais naturalmente. OFF desativa a orquestração especializada VR; projetos, instruções, arquivos e fontes continuam funcionando.

A referência confirmada na documentação oficial da OpenAI é que um projeto reúne conversas, instruções, arquivos enviados e fontes conectadas; novas conversas do projeto têm acesso a esses materiais compartilhados. Anexos específicos podem ser enviados diretamente à conversa. A documentação distingue esse contexto de uma pasta local acessível ao runtime. [Projects and chats — ChatGPT Learn](https://learn.chatgpt.com/docs/projects).

Aplicar essa referência ao VRStudio com os seguintes critérios de produto; são requisitos da implementação local, sem pressupor uma API interna ou a mesma estratégia de recuperação do ChatGPT Web:

- **Projeto como contexto persistente:** ao iniciar ou retomar uma conversa em OFF dentro de um projeto, aplicar suas instruções e disponibilizar suas fontes automaticamente. O usuário não precisa reenviar os arquivos, digitar um comando especial ou mudar de modo para o modelo poder consultá-los. Cada conversa mantém seu próprio histórico; compartilhar fontes não significa concatenar todas as conversas no prompt.
- **Fontes do projeto e anexos da conversa:** materiais vinculados ao projeto ficam disponíveis às suas conversas; um anexo exclusivo de uma conversa mantém esse escopo, salvo associação explícita ao projeto. Permitir inspecionar quais fontes estão vinculadas, sua disponibilidade e a origem dos trechos usados.
- **Uso natural sob demanda:** perguntas como “compare os arquivos do projeto” ou “o que essa classe faz?” devem levar o provedor a consultar as fontes adequadas em OFF. As instruções do projeto entram no contexto inicial; os conteúdos grandes são buscados/lidos conforme a necessidade, com os limites já definidos neste plano. O usuário não precisa conhecer `vr_search` ou `vr_read`.
- **Seleção e continuidade:** projeto e fontes permanecem associados à conversa ao alternar OFF/VR/ULTRA e ao reiniciar o Studio. Mudar o projeto selecionado para uma nova conversa não pode reatribuir silenciosamente conversas existentes. Novas vinculações e remoções de fontes devem valer para as próximas consultas; remover uma fonte não apaga retroativamente trechos já existentes no histórico.
- **Escopos visíveis:** distinguir fontes privadas do projeto, anexos da conversa e a base VR compartilhada. OFF continua com acesso sob demanda a Wiki, KB, Schema e Java configurados, conforme o requisito geral. Consultas no projeto A não podem trazer materiais exclusivos do projeto B sem vínculo explícito; a base VR comum continua acessível aos projetos autorizados.
- **Conversa sem projeto:** permitir chat nativo com seus próprios anexos e acesso sob demanda às fontes comuns configuradas. Não assumir que `VRProject` é o projeto selecionado nem herdar instruções/fontes privadas de outro projeto.
- **Integração existente:** reutilizar o cadastro e o seletor de projetos atuais (`projectItems`, `currentProjectIndex` e operações de pasta) e os vínculos de conversa existentes. Acrescentar ou completar a associação persistida de instruções/fontes onde faltar; não manter um segundo cadastro de projetos só para OFF. Uma pasta de trabalho, por si só, não substitui o contrato de fontes do projeto.

**Causa raiz.** O acesso está acoplado a controles de modo em pontos diferentes. OFF pula a recuperação automática, seus adaptadores também restringem a exposição da base e sua ferramenta local é opt-in. O Java está encapsulado na execução de pesquisa do ULTRA. Além disso, busca dinâmica, RAG e script portátil utilizam caminhos de recuperação distintos. Alterar apenas o `if` do orquestrador não harmoniza esses contratos.

**Localização.** Achados confirmados no código atual:

**Nota de estado histórico.** A tabela abaixo registra achados da auditoria em 09/09/2026 (HEAD `afc7d98`). Referências a `native_vr_search_enabled` e `VR_NATIVE_SEARCH_ENABLED` são históricas e não representam o contrato atual: o opt-in exclusivo do OFF foi removido e as tools locais são registradas independentemente do modo.

| Prioridade | Local | Achado e consequência para o plano |
| --- | --- | --- |
| P0 | `mary/orchestrator.py:564`, `:701`, `:718` | RAG depende de `use_vr`; `explicit_code_analysis` exige `vr_mode == "ultra"` e só é consumido no fan-out. VR direto e ULTRA sem fan-out não recebem Java por esse caminho. |
| P0 | `mary/frontend/chat.py:2565` | O frontend **já envia** `application_contexts` e a flag sem comparar o modo com ULTRA. A fase 3 original descreve uma trava que não está mais nesse trecho. A flag ainda depende da seleção e do controle de análise. |
| P0 | `mary/chat_tools.py:224`, `:272`; `mary/config.py:51`, `:226` | `vr_search` aceita apenas `wiki`, `kb`, `schema`; chama o router diretamente. OFF depende de `native_vr_search_enabled=False` e do default `VR_NATIVE_SEARCH_ENABLED=0`. |
| P0 | `mary/provider_adapters/codex.py:679`; `mary/orchestrator.py:3140` | Registro e resposta de ferramentas dinâmicas são implementados pelo transporte Codex. Uma especificação presente em `ConversationOptions` não prova execução nos demais provedores. |
| P0 | `mary/provider_adapters/claude.py:99`; `antigravity.py:96`; `opencode.py:162` | Exposição da base depende de `vr_enabled`. Claude não encaminha `dynamic_tools`; Antigravity envia `mcpServers=[]`; OpenCode não encaminha essas ferramentas dinâmicas. |
| P0 | `mary/code_context.py:13`, `:57`, `:63` | Já existem congelamento de aplicativo/versão/variante/origem e filtro por artefato/hash antes do `LIMIT`. Devem ser reutilizados nos três modos. |
| P1 | `mary/execution/runner.py:608`, `:638`, `:685` | Pesquisadores rodam em paralelo; o agente de código começa **depois**, usando seus achados para delimitar a busca. “Código em paralelo” modifica uma dependência existente. |
| P1 | `mary/retrieval/service.py:153`, `:174` | A finalização resolve candidatos em `documents`. Acrescentar `source="code"` antes dessa validação, sem adaptar o resolver, pode eliminar os candidatos Java. |
| P1 | `mary/knowledge_router.py:1519`; `mary/code_index.py:794` | O prompt tem orçamento de 18.000 caracteres e interrompe a inclusão no primeiro bloco que não cabe. A expansão Java permite 24.000 caracteres por resultado. Acrescentar Java ao final pode resultar em zero código no prompt. |
| P1 | `mary/execution/runner.py:698`, `:706`; `mary/supervision.py:1466` | Até oito resultados Java por contexto podem ser expandidos; a síntese serializa todas as evidências recebidas. A quantidade de aplicativos pode multiplicar o contexto sem um teto comum nessa montagem. |
| P1 | `mary/data/vr-search.ps1:11`; `mary/portable_project.py:236`; `mary/cli.py:1116` | O script portátil aceita explicitamente apenas Wiki/KB; o CLI Java existe, mas seu comando de busca não recebe o contexto completo de aplicativo. O fallback não equivale ao acesso unificado. |
| P1 | `mary/orchestrator.py:2361`; `mary/repositories/conversations.py:240` | Citações diretas são reconhecidas por URL ou ID; persistência em `source_citations` descarta `document_id <= 0`. Candidatos Java são criados com `document_id=0`. |
| P1 | `tests/test_mary_orchestration.py:1970` | O teste OFF usa provedor simulado, termina com texto fixo e confere busca com zero resultados. Não demonstra que um provedor recebe o retorno e responde com precisão. |
| P2 | `tests/` | O arquivo pertinente é `test_mary_orchestration.py`; `test_orchestrator.py`, citado no plano original, não existe neste checkout. |

Os caminhos acima são relativos a `vrsoft_extractor/`, exceto `tests/`. Consulte também [DEVELOPMENT.md](DEVELOPMENT.md) e preserve as modificações locais em catálogo, Java, bridges e QML.

**Fluxo afetado.** Atualmente o composer envia modo, seleção e flag ao `ChatOrchestrator.send`. OFF entrega o texto ao provedor e só oferece `vr_search` quando configurado; essa ferramenta procura três fontes. VR/ULTRA passam pelo `RetrievalService.route`, que também recupera conhecimento documental. Se o modo, as imagens e a configuração permitirem fan-out, o runner executa pesquisadores e, posteriormente, a busca/análise Java. Ao responder, há ainda diferenças no registro das evidências usadas.

O fluxo pretendido começa por um contexto de consulta imutável por turno, comum aos três modos. Ferramentas e recuperação automática chamam o mesmo serviço em Python; esse serviço consulta os índices existentes e produz evidências com identidade e orçamento. A estratégia OFF/VR/ULTRA decide quando usar o serviço e quantas etapas de investigação executar.

**Correção proposta.** Implementar na ordem abaixo. Primeiro estabelecer acesso comum e demonstrá-lo em um ciclo completo de ferramenta; depois conectá-lo às estratégias. Não copiar o bloco Java inteiro do runner para o orquestrador.

**1. Fixar os contratos de acesso, escopo e disponibilidade.**

- Separar a disponibilidade da base, a disponibilidade do índice Java e a habilitação da análise profunda. O toggle atual `code_analysis_enabled` deve controlar trabalho adicional do agente de código, sem retirar do OFF/VR o direito de consultar Java pronto.
- Registrar ferramentas comuns por padrão nos três modos. Retirar o opt-in OFF como requisito operacional. Definir migração explícita da configuração legada `VR_NATIVE_SEARCH_ENABLED`: a ausência da variável e o antigo default falso devem migrar para o novo comportamento; qualquer preferência explícita de desligamento da base deve ser tratada como opção global visível, independente do modo, sem manter uma trava oculta só no OFF.
- Capturar, por turno, workspace resolvido, projeto associado à conversa, instruções e vínculos de fontes do projeto, anexos da conversa, identidade da execução/mensagem, revisão das fontes/permissões e seleção de aplicativos. Reutilizar `freeze_application_contexts` e `validate_application_contexts` no worker. Evitar estado global de “release atual” compartilhado por conversas.
- Preservar `None` versus `[]` nos caminhos legados: lista explícita vazia não autoriza fallback para `current`, último pacote ou todas as releases. Uma seleção inválida/desatualizada deve produzir diagnóstico de escopo, sem pesquisar outra origem silenciosamente.
- Disponibilizar descoberta paginada de todos os aplicativos/versões/origens. Se não houver seleção, permitir listar os contextos disponíveis; uma consulta explícita a aplicativo/versão inequívocos pode resolver o contexto exato. Quando faltar informação para distinguir variantes, devolver as alternativas identificadas e solicitar a escolha somente quando necessária à resposta. Não alterar a seleção persistida por decisão do modelo.
- Quando houver seleção explícita, a busca de conteúdo Java respeita aplicativo, versão, variante, distribuição, manifesto e artefatos, incluindo suas dependências. O catálogo continua navegável. Mudanças de contexto precisam ser explícitas; comparar versões não pode misturar evidências sob a mesma identidade.

**2. Centralizar descoberta, busca, leitura e montagem das evidências.**

- Estender o `RetrievalService` existente para coordenar conhecimento e código. Extrair a recuperação determinística e a construção de candidatos Java de `execution/runner.py` para um módulo pequeno em `retrieval/`, reutilizado por `route`, ferramentas e fan-out. Manter busca documental e `JavaCodeIndex` nos respectivos armazenamentos.
- Usar `JavaCodeIndex.search`, `expanded_excerpt` com limite explícito e as relações já indexadas. O parser/AST pertence à preparação do índice; o chat consulta símbolos/relações prontos. Não descompilar, reindexar o corpus inteiro ou analisar toda a AST a cada pergunta.
- Manter os filtros de artefato/hash antes do limite e distinguir identidade de conteúdo de identidade de origem. Classes homônimas, JARs reutilizados, dependências e aplicativos distintos precisam continuar distinguíveis.
- Adaptar a finalização de evidências por fonte: Wiki/KB/Schema passam pela validação documental; Java é resolvido e validado pelo índice e contexto exatos. Não adicionar `code` indiscriminadamente a todas as constantes e consultas documentais.
- Usar estados explícitos como `available`, `not_indexed`, `stale`, `disabled`, `scope_required`, `unavailable` e `no_results`. São novos contratos propostos; mapear os estados existentes para eles. Fonte não consultada e consulta interrompida por orçamento não podem ser declaradas esgotadas.
- Conservar os trechos primários e sua procedência mesmo quando houver resumos. Resultados sem correspondência devem devolver diagnóstico e opções de refinamento; não apresentar ausência no top-k como inexistência do arquivo.

Contrato sugerido de ferramentas, implementado uma única vez e exposto pelos transportes:

| Ferramenta | Entrada essencial | Saída/garantia |
| --- | --- | --- |
| `vr_sources` | Fonte opcional, contexto opcional, cursor | Catálogo e arquivos paginados, disponibilidade, referências estáveis, versões/origens e continuação; sem despejar conteúdo |
| `vr_search` | Consulta, `source` opcional incluindo `code`, módulo/contexto opcionais, limite e cursor | Trechos ranqueados das fontes consultáveis, referências, estado por fonte, truncamento e continuação |
| `vr_read` | Referência emitida pelo serviço, seção/faixa de linhas e cursor | Leitura paginada de um documento/classe, com limites e revalidação de origem/hash |

Reusar os argumentos atuais de `vr_search` e acrescentar campos de forma compatível. Omitir `source` deve permitir pesquisar as quatro fontes; a falta de contexto Java deve aparecer no estado dessa fonte, sem impedir as demais. Prioridades do RAG não restringem uma busca explícita por fonte.

`vr_sources` e `vr_read` são necessários para o requisito “todos os arquivos”: o usuário/modelo precisa conseguir localizar e continuar lendo um item fora do primeiro top-k. Reutilizar o navegador de fontes Java onde couber, ampliando o contrato para dependências e leitura por páginas; seu retorno atual de até 200.000 caracteres foi feito para o navegador da UI e não deve ser usado diretamente como resposta de tool. Índices de Wiki também precisam permitir alcançar as páginas referenciadas.

Referências e cursores devem ser resolvidos pelo serviço dentro do contexto autorizado. Caminhos enviados pela LLM não definem o escopo. Arquivos ainda não indexados precisam ser identificáveis no inventário e ter sua pendência explícita; concluir a preparação é pré-condição para prometer busca completa. Se oferecer leitura do arquivo original enquanto o índice estiver pendente, usar referência catalogada, paginação e estado de validação explícito, sem promovê-lo a evidência validada automaticamente.

**3. Implementar transporte real nos provedores e compatibilidade de sessões.**

- Codex: reutilizar `dynamicTools` e a resposta nativa já existente. Registrar as ferramentas antes de iniciar a sessão. Revisar `_respond_dynamic_tool`, aprovação e callbacks para testar entrega ao transporte, além do evento mostrado na UI.
- Claude, Antigravity e OpenCode: expor a mesma implementação por **MCP local sobre stdio**, com configuração por execução/sessão. Não criar outra implementação de busca nem um serviço HTTP local. O processo MCP deve carregar o contexto congelado do turno e retornar os mesmos IDs, estados e limites do caminho Codex.
- Claude: integrar configuração MCP no comando que já executa `-p`; conciliar as ferramentas de consulta com o perfil de aprovação existente. O caminho atual proíbe Bash no VR; instruir o modelo a executar um script não resolve esse transporte.
- Antigravity: preencher `mcpServers` ao criar/carregar/retomar a sessão e verificar as capacidades/versionamento negociados. Não assumir que apenas mudar `additionalDirectories` disponibiliza ferramentas ou índices.
- OpenCode: integrar um servidor MCP local à configuração de processo já usada pelo adaptador. Preservar as demais configurações e ferramentas do usuário.
- Os detalhes de stdio são suportados pelas documentações oficiais: [MCP do Claude Code](https://code.claude.com/docs/en/mcp), [configuração pela CLI do Claude](https://code.claude.com/docs/en/cli-reference), [sessões ACP](https://agentclientprotocol.com/protocol/v1/session-setup) e [MCP do OpenCode](https://opencode.ai/docs/mcp-servers/). Essa escolha é uma proposta de integração; o suporte das versões instaladas deve ser confirmado durante a implementação, inclusive no binário distribuído do Studio.
- O transporte adicional deve ser fino e iniciar sem varrer o corpus ou calcular hashes de todos os JARs. Definir inicialização, timeout, encerramento e descarte de chamadas de turno antigo; o processo não pode sobreviver a cancelamento/fechamento indevidamente. Usar um SDK compatível se o projeto precisar acrescentar essa dependência e incluí-la no empacotamento.
- Identificar a versão do conjunto de ferramentas registrada na sessão. Para uma sessão antiga incompatível, usar reconfiguração suportada; se o transporte exigir uma nova sessão, preservar a conversa local e transferir o histórico pelo fluxo já existente, sem duplicar a pergunta ou reenviar ferramentas com efeitos colaterais. Atualizar o identificador somente depois de sucesso, com recuperação de falha.
- OFF mantém personalidade/resposta nativas, aplicando as instruções do projeto e os anexos da conversa. Disponibilizar informação leve sobre projeto, fontes e ferramentas; consultar conteúdos grandes sob demanda. Retirar o vínculo entre `vr_enabled` e capacidade de consultar a base. Não ativar o pipeline VR para obter permissões de leitura.
- O script `vr-search.ps1` deixa de ser a garantia de equivalência dos provedores. Se continuar sendo anunciado pelo prompt ou usado como fallback, atualizar o contrato para Schema/Java e escopo exato; editar o gerador versionado em `mary/data/`, seus consumidores e testes, não apenas a cópia em `VRProject`. Preservar o funcionamento da exportação portátil sem depender silenciosamente da venv deste checkout.

Os perfis de aprovação existentes permanecem aplicáveis. A política de fonte e procedência precisa ser aplicada pelo serviço; não depender apenas de instrução no prompt sobre uma pasta. Evitar prometer a mesma política por leituras nativas irrestritas que contornem o contexto de consulta.

**4. Integrar as estratégias OFF, VR e ULTRA.**

- OFF: cumprir o contrato de projetos/fontes como no ChatGPT Web descrito acima e oferecer as três operações. Instruções do projeto e contexto leve são aplicados automaticamente; buscar/ler conteúdo das fontes quando o provedor pedir. Uma pergunta geral sem consulta à base não deve disparar recuperação, classificação VR ou agente auxiliar.
- VR (contrato atual desde VRTOOL-001): o modelo principal inicia o turno sem retrieval automático, com o contrato VR estável e as tools `vr_sources`/`vr_search`/`vr_read`; decide quando e qual fonte consultar. `vr_search` sem `source` roda Wiki, KB, Schema e Código em paralelo e consolida; a falta de contexto Java aparece no estado daquela fonte sem impedir as demais. A trilha Java usa pergunta, identificadores, aplicativo selecionado e relevância, sem depender de ULTRA ou do toggle do agente profundo; uma pergunta sustentada apenas por código funciona com Wiki/KB/Schema vazios ou com falha documental. (Histórico VRNORMAL-001-v2, substituído: obter o bundle comum antes de `_enrich_prompt` e registrar as evidências pendentes.)
- Selecionar e intercalar trechos por relevância e fonte antes de renderizar, reservando espaço para Java quando ele sustentar a pergunta. Considerar as quatro fontes no planejamento; não anexar um trecho de cada fonte artificialmente. Perguntas sobre regra/tela podem exigir Java sem mencionar “classe” ou “código”; cobrir isso nos casos de recall.
- ULTRA: utilizar o mesmo bundle e as mesmas ferramentas. O acesso Java continua disponível se o fan-out estiver desativado, se faltar orçamento para o agente de código ou se houver anexos visuais. A recuperação básica não depende do agente especializado.
- Preservar inicialmente a sequência atual do agente de código, pois seus termos de busca aproveitam os achados dos pesquisadores. A exigência de acesso aos arquivos não depende de mudar essa ordem. Se quiser paralelizar, fazê-lo em etapa posterior: antecipar recuperação com escopo congelado, depois permitir refinamento limitado por achados novos, usando o mesmo orçamento global. Não chamar código de “paralelo” mantendo o bloqueio atual depois de `as_completed`.
- Com imagens, preservar a imagem enviada ao provedor e o acesso a todas as ferramentas. O caminho atual omite o bundle em `_enrich_prompt` quando há imagens; tratar esse ramo explicitamente, mantendo a política de carga leve e permitindo consulta Java/documental sob demanda.
- No frontend, concentrar a mudança nos conceitos e consumidores reais: `CodeAdminDomain`, propriedades Qt, preferências e textos dos seletores. Apresentar “Contexto de aplicativos” disponível nos três modos e diferenciar “Análise profunda de código”. Manter aliases/migração para propriedades e preferências `ultra...` enquanto houver consumidores. Não é necessário redesenhar o composer.

**5. Aplicar limites compartilhados e preservar fontes utilizadas.**

- Estabelecer orçamento de evidências por prompt e por turno, com limites de bytes/caracteres serializados, resultados, páginas, chamadas e tempo. Contar metadados, relatórios e leituras adicionais; limitar só o número de resultados não basta.
- Ponto de partida proposto para calibração: manter o teto atual de 18.000 caracteres da montagem documental como teto comum inicial do VR; usar trechos curtos e, inicialmente, até três resultados Java, dentro desse teto. Ferramentas: até seis resultados por busca e 8.000 caracteres por página de leitura, sempre subordinados ao orçamento cumulativo e à capacidade restante. Esses valores são parâmetros iniciais de engenharia, não desempenho medido nem limites dos modelos.
- A cada chamada LLM, contabilizar o que o Studio controla: instruções, histórico reenviado, evidências, relatórios e reserva para resposta. Usar informação de contexto do provedor quando disponível; estimativas devem ser identificadas e limites desconhecidos não podem ser inventados. Tetos em caracteres não equivalem a garantias de tokens; preservar a compactação nativa e medir o conteúdo efetivamente transmitido.
- ULTRA deve manter `ExecutionBudget`, reserva de síntese/validação, cancelamento e retomada. Acrescentar busca/leitura e seleção final a esse controle. Evitar multiplicar o teto de evidências por aplicativo ou por agente na síntese.
- Se um bloco exceder o espaço restante, reduzir/paginar e continuar a seleção com critério explícito; não encerrar a montagem antes de incluir evidência indispensável. Registrar o conjunto exato de IDs cujos trechos chegaram ao modelo.
- Cache, se necessário, deve incluir workspace, revisão documental/permissões, contexto/manifesto/artefatos, consulta e versão do índice. Não reutilizar resultados entre aplicativos/conversas de escopos diferentes. Toda validação pesada roda fora da thread Qt; cancelar e rejeitar resultados obsoletos antes de publicar.
- Reutilizar o registro de evidências existente e estendê-lo para todos os turnos: IDs recuperados, entregues, lidos e citados são conjuntos diferentes. Resultados de ferramentas também entram no registro da execução correta.
- Fazer migração aditiva da persistência de citações para acomodar fontes sem `document_id`, preservando as referências documentais antigas. Armazenar `source`, referência/ID da evidência, procedência e trecho/faixa usados; para Java, aplicativo, versão, origem/JAR, classe, linhas e hashes. Não criar documentos fictícios apenas para satisfazer a chave documental.
- Definir uma referência pública legível que possa ser mapeada deterministicamente à evidência de código, pois o fluxo direto atual reconhece apenas URL/ID. Validar/rejeitar citações desconhecidas sem uma chamada extra obrigatória à LLM e sem expor o envelope interno no chat. Recarregar a conversa deve preservar as fontes utilizadas.

**Risco de regressão.** Os principais riscos são mistura de versões Java, mudança das permissões do modo nativo, conversas antigas sem ferramentas, contexto excedido, travamento da UI por hashes/SQLite, resultados de consultas canceladas publicados no turno seguinte e perda de citações. Há também risco de duplicar recuperação no ULTRA ou retirar filtros de revisão/origem ao uniformizar as fontes.

Preservar as regras de variantes e escopo dos testes existentes; a distinção entre sessões nativas OFF e sessões VR; anexos; streaming e mensagens intermediárias; seleção de projeto; fontes desativadas; cancelamento; retomada; histórico; exportação portátil e perfis de aprovação. Existem alterações locais extensas, especialmente em aplicativos e versões: comparar o diff da implementação com o baseline e não resetar, reformatar ou reescrever trabalho fora do escopo.

**Verificação.** A auditoria executou o comando abaixo, com **88 testes aprovados em 12,85 s**:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_application_contexts.py tests/test_code_index.py tests/test_mary_orchestration.py tests/test_mary_research_fanout.py -q --durations=10
```

Esse resultado valida o baseline dessas quatro suítes. A auditoria não executou chamadas a provedores autenticados nem mediu latência com a base de produção. Não é certificação da arquitetura proposta.

Matriz obrigatória para a implementação:

| Caso | Prova exigida |
| --- | --- |
| 3 modos × 4 fontes | Fixture com um fato exclusivo em Wiki, KB, Schema e Java; busca/leitura alcança cada um, com a mesma origem/contexto independentemente do modo |
| Todos os transportes | Codex, Claude, Antigravity e OpenCode recebem chamada, executam o serviço e devolvem resultado ao modelo; mocks na fronteira do transporte verificam mensagens/configuração reais, não só `options.dynamic_tools` |
| OFF sem necessidade local | Zero chamadas à recuperação e ao fan-out; modo de resposta continua nativo |
| OFF com consulta | Provedor simulado só produz a resposta depois de receber um marcador exclusivo vindo do retorno da ferramenta; teste falha se o retorno não for entregue |
| OFF com projeto e fontes | Nova conversa e conversa retomada recebem instruções e acesso às fontes do projeto; um fato exclusivo do arquivo é recuperado sem reenvio, comando especial ou ativação de VR/ULTRA |
| OFF: projeto, conversa e base comum | Arquivo do projeto está disponível a duas conversas desse projeto; anexo exclusivo fica na conversa correspondente; materiais privados de outro projeto não entram na consulta; base VR comum autorizada continua acessível |
| OFF: persistência e alteração de fontes | Reinício e alternância de modos preservam vínculos; adicionar/remover fonte afeta consultas seguintes e invalida o cache pertinente; alterar o seletor para nova conversa não muda o projeto de conversas existentes |
| OFF sem projeto | Conversa funciona com anexos próprios e fontes comuns configuradas, sem herdar instruções de outro projeto nem assumir `VRProject` como seleção |
| VR com evidência só Java | Trecho Java entra no prompt efetivamente enviado e sustenta resposta/citação, inclusive sem documentos ou com falha da trilha documental |
| VR com regra funcional | Pergunta não contém “Java”/“classe”, mas o comportamento está na implementação; recuperação encontra o método relevante sem exigir ULTRA |
| ULTRA com e sem agente/fan-out | Acesso às quatro fontes se mantém com fan-out ativo, desativado, código profundo desligado e orçamento insuficiente para o agente; não duplicar recuperação inicial |
| Imagens | Anexo chega ao provedor e ferramentas das quatro fontes continuam utilizáveis |
| Arquivo fora do top-k | Paginação/listagem e `vr_read` alcançam o arquivo correto, inclusive página de Wiki ligada ao índice e classe/dependência fora dos primeiros resultados |
| Isolamento | Duas aplicações com classe homônima, releases/variantes diferentes e dependências compartilhadas; resultado respeita escopo antes do limite |
| Contexto ausente, vazio ou inválido | Descoberta identifica alternativas; lista explicitamente vazia/seleção inválida não vira busca ampla nem `current` silencioso |
| Alteração durante o turno | Manifesto, JAR, documento, permissão ou seleção mudam; evidência velha é invalidada/rejeitada, com estado correto |
| Conversas e concorrência | Sessão criada antes da mudança recebe ferramentas; alternância OFF→VR→ULTRA→OFF, troca de provedor e duas conversas simultâneas preservam histórico e escopo |
| Cancelar/fechar/retomar | Ferramenta bloqueada, cancelamento, turno novo e fechamento não publicam resultado antigo nem deixam processos/threads sem encerramento; retomada respeita identidade e orçamento |
| Orçamento | Código com método enorme, vários aplicativos e várias páginas: prompt/retorno serializado respeita os tetos, informa truncamento e mantém evidência essencial |
| Citações | Java com `document_id=0` pode ser persistido por identidade própria; fontes inventadas e candidatos não usados não aparecem como citações; fontes sobrevivem ao recarregamento |
| Preparação/curadoria | Índice pendente, fonte desativada, documento em revisão e falha de consulta produzem estados distintos; nenhum modo ignora as regras de origem |
| Distribuição | MCP/CLI funciona no pacote distribuído e com caminhos Windows contendo espaços, sem depender do checkout antigo ou de uma venv externa |

Expandir prioritariamente `tests/test_application_contexts.py`, `tests/test_code_index.py`, `tests/test_mary_orchestration.py` e `tests/test_mary_research_fanout.py`. Acrescentar testes comportamentais do serviço e transportes nos arquivos existentes apropriados, incluindo `test_antigravity_acp.py`, `test_portable_project.py` e os testes Qt afetados. Atualizar os testes que hoje exigem a ausência da base no OFF para o novo contrato, mantendo a proteção contra RAG/fan-out antecipados.

Durante a implementação, executar testes focados e Ruff. Após falha, `pytest --lf -q -x`. Antes de entregar:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q --durations=10
git diff --check
```

Medir antes/depois o atraso local até o envio ao provedor, latência de busca/leitura, tamanho de prompts/retornos e responsividade Qt, separando cache frio/quente, pergunta geral e pergunta sobre código. Usar a mesma fixture/corpus e registrar p50/p95; acordar o limiar de regressão com os dados do baseline, sem inventar SLA. O benchmark existente ajuda nos índices, mas não substitui medir o fluxo completo. Para UI, conferir contexto/toggle nos três modos em janela ampla e estreita; para responsividade, usar interação/sinais com worker bloqueado, não apenas screenshots.

Concluir com smoke controlado de provedores reais disponíveis, cobrindo os três modos e as quatro fontes com dados de teste. Registrar quais combinações foram realmente exercitadas. Se faltar autenticação/runtime, entregar a limitação explicitamente e não declarar aquele transporte certificado com base em um fake.

Mensagem de encaminhamento sugerida ao Gemini 3.8:

> Implemente este plano a partir do checkout atual, preservando as alterações locais. O aceite principal é permitir que OFF, VR e ULTRA descubram, busquem e leiam Wiki, KB, Schema e Java com o mesmo escopo e procedência. O botão OFF deve ter comportamento funcional equivalente ao ChatGPT Web quanto a projetos e fontes: herdar instruções e disponibilizar os materiais do projeto, distinguir anexos da conversa e consultar conteúdos relevantes sem exigir ativação de VR/ULTRA. Reutilize RetrievalService, JavaCodeIndex, code_context, o cadastro de projetos e o runner existente. Entregue acesso efetivo nos transportes, compatibilidade de sessões, limites de contexto e citações persistidas. Preserve OFF sob demanda, VR com recuperação direta e ULTRA com investigação profunda. Demonstre o ciclo completo de ferramenta e a matriz de testes; não considere suficiente habilitar uma flag ou adicionar texto ao prompt.

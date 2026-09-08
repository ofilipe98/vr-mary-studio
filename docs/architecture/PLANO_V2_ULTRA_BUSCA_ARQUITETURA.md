# Plano V2 — Ultra, busca e arquitetura

Data: 06/09/2026. Projeto: VR Norte Studio, `D:\Codex\vr-mary-studio`.

Status em 08/09/2026: implementação L0–L8 e auditoria final concluídas no checkout `D:\Codex\VRStudio`, com as evidências e ressalvas em [V2_IMPLEMENTACAO.md](V2_IMPLEMENTACAO.md). Busca híbrida permanece opcional; Claude sem validação de resposta real por ausência de assinatura. O histórico abaixo preserva o plano original.

Responsáveis: Gemini 3.8 Flash implementa todos os lotes; Codex revisa integralmente as alterações entregues, verifica as evidências e corrige os problemas encontrados na auditoria final. O nome do modelo identifica o executor escolhido pelo usuário, sem alterar os modelos configurados no produto.

## 1. Resultado esperado e limites

Este plano cobre os itens 4, 5 e 6 da proposta de versão 2:

1. Ultra com orçamento global, cancelamento efetivo e retomada de etapas concluídas.
2. Busca textual e semântica combinadas, com relações verificáveis entre fontes.
3. Separação incremental do núcleo, dos adaptadores e dos bridges QML.

Manter Python, Qt Quick/QML, SQLite, operação local e distribuição portátil. Preservar sincronização, revisão, vídeos, releases, permissões, anexos, histórico, ramificações e todos os provedores existentes. Não estão no escopo novos provedores, migração web, microserviços, comparação funcional completa de releases ou lançamento/publicação da versão 2.

## 2. Estado encontrado e referência de comparação

- HEAD observado: `a31acc3e81f7cf0b7ef1c8b83ab5b783840830a4`, branch `dev`, versão declarada `0.5.6`.
- O checkout possui alterações locais em `pyproject.toml`, `db.py`, `frontend/chat.py`, `ChatPreview.qml`, `orchestrator.py` e `providers.py`.
- Há testes locais `test_intermediate_messages.py` e `test_intermediate_review.py`, além de `RELATORIO_IMPLEMENTACAO.md` e outros artefatos não rastreados.
- O relatório de mensagens intermediárias informa um commit base diferente do HEAD observado. Sua contagem de testes é histórica, não uma validação deste plano.
- O fluxo atual já possui tentativas, limites de paralelismo, validação de respostas, eventos persistidos, FTS5/BM25, reordenação por entidades e mecanismos de recuperação.
- `frontend/chat.py` reúne apresentação e administração de processamento Java. `orchestrator.py` reúne execução, eventos, síntese, validação e ciclo de vida de conversas.

A referência da implementação será HEAD **mais as alterações locais identificadas e os arquivos não rastreados pertinentes**. Uma worktree criada apenas a partir do HEAD não contém essa referência completa. Não executar reset, limpeza, stash automático ou sobrescrever trabalho anterior.

## 3. Forma de trabalho e auditoria

Gemini executa os lotes sequencialmente, de L0 a L8, mantendo registros separados de escopo, diff, testes, evidências, limitações e desativação. Corrige os problemas encontrados em sua própria validação e avança sem aguardar parecer intermediário do Codex. Dependências técnicas e critérios de qualidade continuam obrigatórios.

Esta instrução posterior do usuário substitui as exigências anteriores de parar ao final de cada lote, inclusive as contidas nos pareceres L0/R1/R2, que permanecem como histórico e lista de correções. As seções “Auditoria” dos lotes passam a compor a auditoria final. O Codex revisará todos os arquivos e alterações entregues, incluindo exclusões, testes, configuração, migrações, dependências e empacotamento, corrigirá os achados e repetirá as validações afetadas. Revisão integral do escopo não é garantia de ausência de qualquer defeito; limites de validação serão documentados. Este documento não inicia sessões do Gemini nem chamadas a provedores reais.

Diretório sugerido de entregas: `reports/v2/<lote>/`. Para cada lote:

- `entrega.md`: problema, comportamento final, arquivos/símbolos, comandos executados, códigos de saída e limitações.
- `baseline.json`: commit, identificação do diff anterior, hashes dos arquivos pertinentes, versões de Python/Qt e, quando aplicável, índice, corpus e modelo.
- Evidências de testes e cenários; capturas apenas quando houver impacto visual.
- `auditoria.md`: preenchido pelo Codex, com achados por severidade, arquivo/linha, reprodução, impacto e correção esperada.

Pareceres: **aprovado**, **correções necessárias** ou **validação incompleta**. O parecer não afirma funcionamento com provedor real com base em mocks. Defeitos críticos/altos e cenários obrigatórios não verificados impedem a aprovação. Desvios menores ficam identificados com impacto e tratamento; não somem do relatório.

## 4. Sequência de execução

| Lote | Item | Entrega | Depende de |
| --- | --- | --- | --- |
| L0 | 4/5/6 | Referência reproduzível e contratos existentes | — |
| L1 | 6 | Separação inicial da execução e da recuperação | L0 |
| L2 | 4 | Orçamento, cancelamento e controle de tentativas | L1 |
| L3 | 4 | Persistência e retomada segura | L2 |
| L4 | 5 | Avaliação congelada da busca e contrato semântico | L1; executar após L3 para manter integração sequencial |
| L5 | 5 | Índice semântico local e busca híbrida | L4 |
| L6 | 5 | Relações verificáveis e expansão limitada | L5 |
| L7 | 6 | Separação restante de provedores, bridges e acesso a dados | L3 e L6 |
| L8 | 4/5/6 | Validação integrada e portabilidade | L7 |

Cada lote pode ser dividido em mudanças menores revisáveis. Não juntar extração mecânica, mudança de ranking e alteração de política de execução no mesmo diff. Esta ordem inicia o item 6 apenas onde ele prepara os itens 4 e 5 e conclui a arquitetura após estabilizar os comportamentos.

## 5. Contratos que todas as etapas preservam

- Modos persistidos `off`, `vr` e `ultra`, incluindo o encaminhamento atual de `/pesquisa`.
- `off` não consulta nem expande a base local.
- Separação entre execução local, run de pesquisa, tentativa do provedor e mensagem. Mapear os IDs existentes antes de acrescentar campos.
- Mensagens intermediárias públicas permanecem ordenadas e identificadas; seu término não encerra o turno.
- Eventos internos de pesquisadores/revisores não viram mensagens públicas. Eventos atrasados não alteram outra tentativa ou execução.
- Resposta final continua sujeita às validações existentes; um orçamento esgotado não autoriza publicar alegações reprovadas.
- Origens `vrwiki` e `endoo` permanecem independentes após combinação e deduplicação. Falta de resultado e fonte indisponível permanecem distintas.
- Escopo de projeto, fontes permitidas, produto e release é aplicado antes de recuperar, expandir ou reutilizar evidências.
- Preservar hashes, JARs originais, índices históricos e dados de usuário. Migrações aditivas, idempotentes e compatíveis com o mecanismo atual.
- Conteúdo recuperado é dado não confiável. Metadados de ranking ou similaridade não equivalem a probabilidade de verdade.

## 6. L0 — Referência reproduzível

**Gemini:** registrar status/diff/hashes sem alterar o trabalho existente; executar a suíte atual em ambiente de teste e separar falhas preexistentes. Mapear envio, mensagens intermediárias, ferramentas, finalização, cancelamento e recuperação nos quatro provedores.

Criar fixtures sintéticas com eventos representativos e documentar os contratos públicos de `ChatOrchestrator`, `KnowledgeRouter`, `AgentProvider`, `RuntimeEvent`, `EvidenceBundle`, sinais e propriedades QML usados pelos fluxos afetados. Reutilizar testes existentes; acrescentar caracterização somente para comportamentos importantes sem cobertura.

**Aceite:** qualquer regressão futura pode ser comparada com um estado identificado; a referência contém as mensagens intermediárias locais. Registrar as lacunas de integração real. Falhas relevantes preexistentes recebem um lote de correção separado antes das mudanças dependentes.

**Auditoria Codex:** verificar se a referência inclui os arquivos locais, se os testes exercitam o caminho real de código e se nenhuma expectativa foi relaxada para esconder falhas.

## 7. L1 — Separação inicial do núcleo

Criar módulos pequenos por responsabilidade, com nomes orientativos:

- `execution/contracts.py`: contexto de execução e resultados de etapa, sem dependência de Qt.
- `execution/runner.py`: extração da coordenação hoje concentrada em `_run_module_fanout` e dos pontos de chamada necessários.
- `retrieval/service.py`: contrato para recuperação e refinamento, inicialmente delegando ao `KnowledgeRouter` atual.

Manter as entradas atuais como fachadas durante a transição. Injetar repositório, relógio, mecanismo de cancelamento e acesso aos provedores nos limites que precisam de isolamento. Não criar um contêiner genérico de serviços.

**Aceite:** mesmos resultados de busca, política de esforço, tentativas e eventos públicos da referência. Imports existentes continuam válidos; nenhum ciclo de imports. Núcleo de execução não importa QML/Qt. Não copiar o estado mutável para dois donos.

**Auditoria:** comparar rastros normalizados por contrato, descartando somente campos variáveis como timestamps/IDs gerados. Verificar quem possui locks, callbacks e finalizadores após a extração.

## 8. L2 — Orçamento e cancelamento do Ultra

### Comportamento

Uma investigação recebe `ExecutionBudget`: limite de tempo ativo, chamadas, concorrência e tentativas. Registrar uso de tokens quando o provedor o informar, distinguindo valores reais, estimados e desconhecidos.

- O orçamento é compartilhado por pesquisadores, agente de código, síntese, revisão e correção. Retries e recuperação de resposta vazia consomem esse mesmo orçamento.
- A reserva de chamadas é atômica entre workers. O timeout de cada operação é o menor entre seu limite e o tempo restante.
- Reservar capacidade para síntese e validação antes de abrir pesquisas opcionais. Sem capacidade de concluir com validação, encerrar com estado explícito e achados preservados.
- Defaults iniciais devem reproduzir a política medida em L0. Perfis mais rápidos são habilitados depois da comparação; não reduzir limites arbitrariamente na extração.
- Retry limitado para falhas transitórias. Negação de ferramenta, permissão insuficiente e entrada inválida não geram retry cego nem troca de provedor para contornar a restrição.
- Respeitar a concorrência global existente e acrescentar limite por provedor quando necessário. Não substituir o modelo escolhido silenciosamente.
- Cancelamento sinaliza os workers, interrompe chamadas pelos adaptadores e impede novas etapas. Limpeza de subprocessos se limita à operação pertencente à execução.
- Eventos de progresso descrevem etapas reais. O estado da timeline acompanha a execução, preservando a semântica das mensagens intermediárias.

Limite de tokens é estrito somente quando o provedor permite impor o teto. Contabilização recebida apenas no final permite interromper novas chamadas, não garantir o consumo máximo da chamada já iniciada. Não apresentar custo monetário sem dados suficientes.

### Testes e aceite

Relógio controlado para prazo e backoff; workers concorrentes disputando a última chamada; timeout durante síntese; orçamento esgotado durante revisão; cancelamento durante espera/retry; callback tardio; falha de um pesquisador e resultado dos demais.

Nenhuma chamada nova começa sem reserva e prazo válidos. Um término lógico não é publicado duas vezes. A interface libera a execução cancelada sem esperar uma tarefa remota ilimitadamente e informa eventual interrupção remota não confirmada.

**Auditoria:** procurar esperas que ultrapassem o orçamento, contagem dupla de tokens, corrida na reserva e executores cujo shutdown bloqueie a finalização. `Future.cancel()` não interrompe tarefas em execução; a interrupção precisa alcançar o adaptador [Python](https://docs.python.org/3/library/concurrent.futures.html).

## 9. L3 — Persistência e retomada

### Persistência proposta

Adicionar repositório de investigações usando o SQLite existente. Reutilizar identidade/eventos já presentes, sem duplicar tabelas com a mesma função. Nomes orientativos: `research_runs`, `research_steps`, `research_step_attempts`.

Persistir vínculo com conversa/execução, versão do contrato, plano, estados, hashes de entrada e saída, orçamento consumido, tentativas e resultado estruturado validado. Resultado e estado concluído são gravados na mesma transação.

Estados do run: `pending`, `running`, `completed`, `partial`, `interrupted`, `cancelled`, `failed`. Estados de etapa: `pending`, `running`, `completed`, `failed`, `skipped`. Documentar transições válidas e impedir concorrência por claim atômico e identidade do dono/tentativa.

Ao reiniciar, jobs que perderam o dono ficam interrompidos. Não disparar novas chamadas automaticamente. A ação **Retomar investigação** cria uma nova execução local vinculada ao mesmo run, preservando mensagens anteriores. Um usuário cancelado só retoma mediante ação explícita.

### Reutilização e consistência

- Reutilizar somente resultados completos, validados e compatíveis com pergunta/contexto, escopo, fontes autorizadas, hashes dos documentos, manifesto ERP, versão do prompt/política e modelo relevante.
- Resolver a release `current` para um manifesto concreto no início. Se o contexto ou as evidências mudarem, invalidar a etapa e seus dependentes com motivo visível.
- Manter orçamento consumido; retomada não o zera. Persistir tempo ativo acumulado e reconstruir o relógio monotônico ao retomar; tempo com o app fechado não consome tempo ativo. Orçamento esgotado exige uma nova concessão explícita na ação de continuar.
- Garantir idempotência local da publicação final e dos estados. Uma queda depois da resposta remota, antes do commit local, pode exigir repetir a chamada; registrar essa janela de incerteza, sem prometer execução remota exatamente uma vez.
- Não repetir automaticamente ferramentas com efeitos externos. A primeira versão de retomada cobre etapas de pesquisa de leitura e síntese; efeito desconhecido fica pendente de decisão explícita.
- Dados de pesquisa são privados como conversas: integrar arquivamento/lixeira/purge e excluir checkpoints/resultados privados da exportação de conhecimento.

**Aceite:** testes de queda antes/depois de cada fronteira de commit, duas retomadas simultâneas, alteração de manifesto/documento, permissão revogada, evento atrasado, banco antigo e migração repetida. Etapa completa compatível não chama o provedor novamente. Nenhuma duplicação de resposta final.

**Auditoria:** reproduzir interrupção em processo separado e retomar usando o mesmo banco temporário. Verificar o caso de sucesso remoto sem checkpoint local e o destino dos dados na exportação portátil.

## 10. L4 — Avaliação da busca e escolha semântica

Congelar um corpus sintético/anonimizado e pelo menos 40 consultas, com evidências relevantes rotuladas. Incluir identificadores exatos, sinônimos, perguntas ambíguas, diferentes origens, fontes indisponíveis, ausência de resposta e release divergente. Separar consultas de ajuste e avaliação final; não ajustar pesos usando o conjunto final.

Registrar Recall@10, MRR@10, preservação de resultados exatos, cobertura por origem, p50/p95 de consulta, memória e tamanho do índice. Medir consultas frias e aquecidas separadamente. O benchmark atual de análise Java é referência de comparação/revisão, mas seu contrato de 5–10 casos não deve ser alterado para acomodar esta suíte de recuperação.

Criar contrato `EmbeddingBackend` para documentos e consultas, incluindo identificação imutável do modelo, revisão, dimensão e normalização. Avaliar um pequeno conjunto de modelos locais adequados ao português; a entrega deve escolher um e fixar revisão, licença, checksum, dependências e limites de hardware com evidência. Essa escolha é trabalho do lote, não uma suposição deste plano.

O recurso semântico será opcional. Não instalar/download de pesos durante import, inicialização ou consulta. Preparação explícita, com progresso, tamanho e diretório gerenciado. CPU deve continuar viável; GPU pode acelerar quando disponível. Nenhum conteúdo autenticado será enviado a um serviço externo de embeddings nesta etapa.

**Aceite:** relatório de seleção reproduzível e conjunto de avaliação congelado antes de L5. Se os candidatos não forem viáveis, entregar o diagnóstico e ajustar a estratégia sem simular ganho.

## 11. L5 — Índice e recuperação híbrida

Implementar índice semântico regenerável sob `VRProject/indice/`, isolado do conteúdo canônico. Identificar cada vetor por documento/chunk, origem, escopo, hash do conteúdo, revisão do segmentador e modelo.

Indexação incremental deve atualizar conteúdo alterado, excluir/inativar documentos removidos e recuperar interrupções. Construir uma geração completa antes de publicá-la atomicamente; consultas enxergam uma geração coerente enquanto há reconstrução. Modelos/dimensões diferentes nunca compartilham o mesmo espaço de comparação.

Fluxo: busca textual atual + busca semântica filtrada → fusão de posições → reordenação de domínio → deduplicação e recomposição de cobertura → `EvidenceBundle` compatível.

- Começar com fusão por posições (RRF, constante inicial 60), sem somar diretamente BM25 e cosseno. Ajustes são feitos só no conjunto de desenvolvimento.
- Manter prioridade de identificadores exatos e proteção da cobertura das origens. Similaridade alta não transforma evidência fraca em fato.
- Aplicar fontes e escopo permitidos na recuperação e verificar novamente o candidato antes de montar o contexto.
- Modelo ausente, índice incompatível ou falha semântica preserva busca textual e informa degradação no diagnóstico.
- Manter `textual` e `hybrid` selecionáveis; começar com comparação em modo de avaliação. Preservar FTS5 e seu ranking textual [SQLite](https://www.sqlite.org/fts5.html).

**Critérios propostos de promoção:** ganho mínimo de 5 pontos percentuais em Recall@10 no grupo de paráfrases; MRR@10 geral sem queda superior a 0,02; nenhum caso obrigatório de identificador exato ou isolamento de origem/release regredindo. Relatar resultados por consulta, tamanho de cada grupo e variância; a amostra inicial não prova generalização.

Fixar em L4 um limite de p95 de consulta e memória a partir da máquina/corpus alvo, antes de medir o candidato final. Não habilitar por padrão enquanto qualidade, portabilidade e limites de recursos não passarem. Se falhar, manter o modo textual e relatar o resultado.

**Auditoria:** recomputar métricas a partir dos resultados brutos; verificar consultas omitidas, vazamento entre ajuste/avaliação, documento removido ainda recuperável, filtros tardios e falso fallback que oculta falhas.

## 12. L6 — Relações entre evidências

Criar relações locais com tipo, origem da extração, versão, hash e referência do trecho: artigo → identificador/tela, procedimento → artigo, código → símbolo/chamada/tabela e schema → relação física existente.

Priorizar relações extraídas de links, identificadores e sintaxe verificável. A expansão inicial é de um salto, com limite total configurado e deduplicação de nós. Não introduzir servidor de grafo ou expansão recursiva livre.

O índice Java já possui `callers()` sintático. Reutilizar esse contrato, sem promover coincidência de nome ou chamada sintática a resolução completa de classpath. Relações inferidas ficam identificadas como candidatas e não constituem prova sozinhas.

**Aceite:** cada relação navegável possui origem verificável; ciclos, excesso de vizinhos, homônimos, relações obsoletas e releases diferentes têm testes. Expansão melhora os casos rotulados sem ultrapassar orçamento de contexto/consulta nem remover evidências diretas melhores.

**Auditoria:** partir de uma conclusão e percorrer suas relações até o trecho original; verificar se o contexto permite a afirmação e se a versão foi mantida durante o percurso.

## 13. L7 — Concluir a divisão da arquitetura

Extrair uma responsabilidade por alteração:

1. Adaptadores para `provider_adapters/base.py`, `codex.py`, `claude.py`, `opencode.py` e `antigravity.py`; manter `providers.py` como fachada compatível enquanto existirem consumidores.
2. Descrever capacidades efetivamente suportadas: anexos, ferramentas, interrupção, retomada, mensagens intermediárias e consumo informado. Não presumir paridade entre protocolos.
3. Separar modelos de mensagens/atividade, gestão de conversas, configuração de provedores e administração Java do bridge atual. Manter sinais/propriedades Qt consumidos pelo QML por delegação durante a migração.
4. Extrair consultas/persistência por domínio conforme usadas nos lotes, mantendo `MaryDatabase` como fachada e a coordenação de transações. Não criar repositórios independentes que quebrem operações atômicas entre tabelas.
5. Dividir `ChatPreview.qml` por componentes com responsabilidades claras, preservando tema, foco, seleção, scroll, anexos e composer. Reutilizar os componentes existentes.

Não definir sucesso por número de arquivos ou meta arbitrária de linhas. Aceite estrutural: execução/recuperação sem imports de frontend, adaptadores sem dependência do orquestrador, um dono de cada estado mutável e de cada transação, fachadas sem lógica duplicada e ausência de dependências circulares.

**Auditoria:** contrato de cada provedor com fixtures representativas, exercício das fachadas antigas, ciclo de vida de threads/Qt, imports em processo limpo e conteúdo incluído no pacote. Validar desempenho e delegates com medição, seguindo as orientações de [Qt Quick](https://doc.qt.io/qt-6/qtquick-performance.html).

## 14. L8 — Validação integrada

### Automatizada

Executar testes direcionados por lote. Ao final, executar a suíte completa e os checks de Python/QML pertinentes. Exemplos a adaptar aos arquivos novos:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_intermediate_messages.py tests/test_intermediate_review.py tests/test_mary_orchestration.py tests/test_mary_research_fanout.py tests/test_mary_vr_ultra.py tests/test_mary_response_quality.py -q
.venv\Scripts\python.exe -m pytest tests/test_mary_vr_search.py tests/test_code_index.py tests/test_portable_project.py -q
.venv\Scripts\python.exe -m pytest tests/test_chat_presentation.py tests/test_qml_frontend.py -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q vrsoft_extractor
git diff --check
```

Usar `.venv\Lib\site-packages\PySide6\qmllint.exe` com `-I vrsoft_extractor\mary\frontend\qml` nos arquivos afetados; distinguir exit code de avisos. Não mudar expectativas existentes apenas para satisfazer a implementação.

### Cenários obrigatórios

| Cenário | Evidência esperada |
| --- | --- |
| Conversa nativa com várias mensagens | Ordem e identidade preservadas, uma finalização de turno |
| VR simples, híbrido desligado | Compatibilidade com a referência e fontes corretas |
| Ultra com vários pesquisadores | Orçamento compartilhado e revisão final válida |
| Provedor lento ou rate limit | Tentativas limitadas e interrupção sem contaminar outra execução |
| Queda após uma etapa | Retomada reaproveita resultado válido e preserva consumo |
| Mudança de release/permissão | Resultado incompatível não é reutilizado |
| Sem modelo semântico/offline | Busca textual funcional e estado de degradação correto |
| Corpus reindexado durante consulta | Uma geração consistente, sem evidência removida publicada |
| Relação entre artigo, código e schema | Proveniência verificável e release compatível |
| Exportação portátil | Conteúdo permitido, sem resultados privados de investigação |

Validar UI em claro/escuro, 1366×768 e 1920×1080, resposta longa, mensagens intermediárias, erro, cancelamento e retomada. Capturas precisam vir da aplicação executada com a mudança; imagens antigas não validam o lote.

Para testes com provedor real, registrar modelo/versão, corpus, manifesto, parâmetros e consumo disponível; comparar VR/Ultra com a mesma pergunta e contexto. Cada adaptador alterado recebe teste real quando houver sessão disponível. Ausência de acesso fica como validação incompleta desse adaptador, sem ocultar o limite. Respeitar os controles de execução/custo do benchmark existente; não alterar esses controles para realizar o teste.

Construir e extrair um pacote de validação em destino isolado. Conferir novos módulos, dependências opcionais e ausência de downloads implícitos. Executar smoke e auditoria portátil pelos mecanismos do projeto, sem publicar, sobrescrever o pacote em uso ou mudar versões de lançamento.

### Métricas finais

Comparar p50/p95 de busca e de investigação, taxa de conclusão, chamadas por etapa, resultados reaproveitados, fidelidade das citações e qualidade humana. Distinguir falha de recuperação, erro do provedor e reprovação da resposta. Não prometer percentuais de aceleração antes da medição.

## 15. Desativação e correção de regressões

Busca híbrida e expansão de relações têm flags independentes; desligá-las recupera o caminho textual validado. O novo executor entra por flag durante a transição, com somente um executor ativo por run. Não trocar de executor no meio de uma investigação.

Uma flag não desfaz migrações nem garante compatibilidade com binário antigo. Testar leitura do banco migrado pela versão de referência quando esse retorno for pretendido; usar cópias de teste e preservar backup antes da migração real. Checkpoints de contrato incompatível são identificados, não interpretados silenciosamente.

Corrigir regressões em lote próprio, reapresentar o cenário que falhou e repetir os testes afetados. Não remover índices/JARs/dados reais para obter um teste verde.

## 16. Instrução atual para o Gemini — execução completa

> Execute integralmente L0–L8 conforme este plano e `design/PROMPT_GEMINI_V2_EXECUCAO_COMPLETA.md`. Corrija primeiro as pendências reais do L0/R2, preserve o trabalho existente, implemente e valide cada lote, registre as evidências e continue sem aguardar auditoria intermediária. Ao final, entregue o diff completo e um relatório consolidado para o Codex revisar todas as alterações e corrigir os problemas encontrados. Não faça commit, push, publicação ou alteração de versão sem instrução específica.

O status de implementação por lote deve ser registrado nas entregas. As caixas abaixo representam aprovação de auditoria; somente o Codex as marca após a revisão final.

## 17. Controle de andamento

- [x] L0 — referência atual e contratos auditados; relatórios históricos de L0/R2 não acompanharam a mudança de pasta.
- [x] L1 — separação inicial auditada.
- [x] L2 — orçamento e cancelamento auditados.
- [x] L3 — persistência e retomada auditadas.
- [x] L4 — avaliação e seleção semântica auditadas.
- [x] L5 — busca híbrida auditada como opção; promoção a padrão reprovada pelo caso negativo adicional.
- [x] L6 — relações e expansão auditadas.
- [x] L7 — arquitetura restante auditada; dívida de avisos estáticos QML discriminada no relatório.
- [x] L8 — integração e pacote de validação auditados; resposta real do Claude não homologada por ausência de assinatura.

As marcações foram feitas pelo auditor após implementação, testes e inspeção das evidências; não significam ausência de limitações ou garantia de toda resposta do modelo.

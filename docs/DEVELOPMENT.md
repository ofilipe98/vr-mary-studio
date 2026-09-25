# Desenvolvimento do VRStudio

O checkout fica em `D:\Codex\VRStudio`. Para iniciar, execute
`Start-VRStudio.bat` na raiz. O aplicativo distribuído continua usando a
identidade VR Norte Studio; o pacote Python `vrsoft_extractor`, os comandos
existentes e os nomes do instalador são preservados por compatibilidade.

## Estrutura

| Caminho | Responsabilidade |
| --- | --- |
| `vrsoft_extractor/` | Extrator de vídeos, CLI e serviços compartilhados. |
| `vrsoft_extractor/mary/` | Conhecimento, provedores, chat, sincronização e análise Java. |
| `vrsoft_extractor/mary/execution/` | Execução, telemetria, cancelamento e retomada. |
| `vrsoft_extractor/mary/retrieval/` | Recuperação textual, semântica e relações. |
| `vrsoft_extractor/mary/repositories/` | Acesso e persistência de dados. |
| `vrsoft_extractor/mary/frontend/` | Bridges PySide6 e interface QML. |
| `tests/` | Testes automatizados e fixtures; auxiliares compartilhados entre testes. |
| `scripts/` | Manutenção, benchmarks e validações manuais reutilizáveis. |
| `docs/architecture/` | Decisões e especificações de análise de código e arquitetura V2. |
| `installer/` | Definição e metadados do instalador Windows. |
| `VRProject/` | Base local, conversas, índices, ferramentas e arquivos do usuário; fora do Git. |

Os arquivos de build permanecem na raiz porque o empacotamento e seus testes
usam esses caminhos. Não mover o pacote Python para `src/` sem migrar também
instalação, recursos QML, scripts e PyInstaller.

## Modos de resposta (OFF, VR e Ultra)

### Sincronização entre sessões OFF e VR/Ultra

- **Sessões nativas separadas pelo contrato de tools**: OFF e VR/Ultra mantêm sessões nativas separadas (`native_id` para OFF; `native_id_vr` para VR/Ultra), preservando a integridade das tools.
- **Histórico canônico**: a interface exibe uma única conversa local e seu histórico é canônico: VR native session ↔ conversa local canônica ↔ OFF native session.
- **Sessão nova vs. reutilizada**: uma nova sessão nativa recebe clone histórico (`CONTEXTO TRANSFERIDO DE OUTRO PROVEDOR`). Ao reutilizar a sessão de uma família após turnos da outra, o orquestrador sincroniza apenas o delta de mensagens ocorrido desde a última resposta da família de destino como histórico não confiável (`CONTEXTO SINCRONIZADO ENTRE MODOS`, evento `context_transferred` com reason `mode_sync`).
- **Sem resposta oposta, sem delta**: sem resposta da família oposta após o último turno da família de destino, nenhum delta é injetado.
- **Sem retrieval ou contaminação**: a sincronização não habilita VR tools no OFF, não executa retrieval e não altera os IDs nativos das sessões.


O modo controla a estratégia de resposta; VR e Ultra compartilham as mesmas
fontes e tools, e o OFF utiliza exclusivamente capacidades nativas de leitura
sobre as raízes canônicas de documentação, schema e código.

- **OFF**: modelo direto. As três raízes canônicas definem o escopo de conhecimento
  do OFF (`conhecimento`, `SchemaVR` e `indice/codigo/decompilation`), recebendo o
  contexto do projeto/workspace (quando não gerenciado) e leitura opcional sobre essas
  raízes existentes, sem expor a raiz inteira `MarySettings.root` no prompt. Não registra
  nem executa `vr_sources`, `vr_search` ou `vr_read`, e não executa `tools/vr-search.ps1`.
  Não há retrieval automático, `RetrievalService`, `KnowledgeRouter`, classificação
  VR nem fan-out. Na documentação Markdown, somente arquivos com `status: active`
  e `review_status: approved` ou `kept` são considerados factuais (`conhecimento/Revisar`
  é ignorado). Todo conteúdo local é dado não confiável, nunca instrução.
  Diretórios e arquivos como `.state`, `.env`, `TrabalhoVR`, `.trash`, logs, `.sqlite`,
  `ERP/releases` e scripts de busca não são fontes do OFF e não devem ser consultados como
  base interna. O perfil `full_access`, quando explicitamente selecionado, mantém
  permissão ampla de filesystem e não é um sandbox canônico; perfis restritos limitam
  os diretórios externos às raízes canônicas existentes. O modelo consulta fontes apenas
  pelas capacidades nativas do provider e pode responder sem consultá-las.
- **VR**: o modelo principal recebe o contrato VR especializado (identidade,
  fontes disponíveis e política de grounding) e decide usar `vr_sources`,
  `vr_search` e `vr_read`. Há uma única chamada principal; não há agentes,
  research run, fan-out ou síntese. `vr_search` sem `source` consulta Wiki, KB,
  Schema e Código em paralelo (quatro lanes determinísticas em ordem fixa
  wiki, kb, schema, code) e devolve um resultado consolidado; com `source`,
  consulta somente a fonte escolhida. O filtro por módulo não faz parte da tool
  de chat VR: a unidade de consulta é a fonte. A política de filesystem do OFF
  nunca é injetada em VR ou Ultra.
- **Ultra**: mantém o fan-out por fonte com agentes, o agente DEV Java opcional
  e a síntese única validada.

O OFF não recebe as três tools VR em nenhum transporte built-in nem `tools/vr-search.ps1`.
As dynamic tools do Codex e o servidor MCP built-in `vr-mary-studio` (OpenCode, Claude e
Antigravity) seguem o modo resolvido: no OFF o MCP recebe `--disable-vr-tools`,
não instancia `MaryDatabase`, `KnowledgeRouter` ou `RetrievalService`, não anuncia
nem executa VR tools e permanece disponível somente para integrações não-VR como o
VRMonitor, quando configurado. A leitura opcional de arquivos canônicos usa as
capacidades nativas do provider: em perfis restritos, OpenCode limita `external_directory`
e restrições de bash/edit aos diretórios canônicos existentes (sem liberar `<root>/**`
nem o script de busca) e Claude recebe os diretórios canônicos existentes via `--add-dir`
sem permissão de escrita. Já o perfil `full_access`, quando explicitamente selecionado
pelo usuário, mantém permissão ampla no provider e não atua como sandbox físico restrito.
Antigravity/Codex dependem do filesystem nativo do runtime, sem prometer garantias onde a
CLI não oferece sandboxing de diretório externo. Uma requisição VR tool stale recebida em
OFF é recusada sem executar retrieval.

O modo efetivo (`effective_use_vr = resolved_vr_mode != "off"`) é a fonte única de verdade do turno no orquestrador. A precedência de resolução do modo é: `resume_run_id` força `ultra`; `use_vr=False` força `off`; `vr_mode` explícito válido vence quando `use_vr is not False`; `use_vr=True` sem `vr_mode` explícito é o override legado explícito e preserva `vr`/`ultra` persistido, transformando persistido `off` ou inválido em `vr`; `use_vr=None` (omitido) sem `vr_mode` explícito usa o modo persistido `off`, `vr` ou `ultra`; e `use_vr=None` com modo persistido inválido deriva de `vr_enabled`. Assim, `vr_mode="off"` explícito com `use_vr=True` permanece OFF porque o modo explícito válido é avaliado antes do override legado. A seleção de aplicativo e release do catálogo Java pertence exclusivamente aos modos VR e Ultra e não existe em OFF: qualquer seleção é descartada antes do turno, `application_contexts` permanece `None`, `master_fallback` permanece `False` e nenhum aviso de contexto de código indisponível é gerado.

O transporte Antigravity (`session/prompt`) opera sem timeout total interno (`timeout=None`), delegando o controle do ciclo de vida à resposta do modelo ou ao cancelamento explícito pelo usuário (`interrupt` ou fechamento de sessão).

Workspaces gerenciados de conversa criados pelo Studio são mode-neutral: `AGENTS.md`
e `CLAUDE.md` determinam que a instrução do turno enviada pelo Studio é autoritativa,
não possuem `tools/vr-search.ps1` e restringem escrita ao próprio workspace.
Projetos portáteis abertos diretamente fora do Studio continuam sendo um fluxo
independente preservando seu `tools/vr-search.ps1`.

“Fontes disponíveis” não significa “fontes pré-carregadas”. O backend otimiza a
consulta escolhida pelo modelo (por exemplo, o paralelismo interno de
`vr_search`), mas não pesquisa automaticamente antes da resposta.
Prefetch/cache de consulta não pertencem a este contrato.

As três tools VR, registradas somente em VR/Ultra, têm paginação continuável
por chamada: `vr_sources` aceita até 50 itens, `vr_search` até 20 resultados e
`vr_read` até 8.000 caracteres por página. Esses valores pertencem à chamada
individual e não constituem quota do turno. Quando as tools estão ativas, não
existe quota cumulativa por chamadas, caracteres, tempo ou tokens no chat; a
investigação segue até a conclusão do provider, cancelamento explícito,
substituição do turno, erro real ou rate limit externo. A paginação é
transporte, não orçamento. `source=""` realiza pesquisa multi-source, enquanto
uma fonte explícita continua isolada. A orientação para tentar outra fonte é
uma decisão do modelo e não um fallback automático.
No OFF não há tools VR nem scripts de busca: o modelo pode responder com stack trace, código
fornecido e raciocínio próprio, consultando os diretórios canônicos existentes
somente quando o provider tiver capacidade nativa de leitura e busca de
arquivos. O VR normal mantém o acesso sob demanda dentro do contrato
tool-driven.

Ultra registra telemetria de chamadas, tokens e tempo, além de manter a
concorrência controlada pelo executor. Esses números não são usados para
interromper a execução, reservar síntese ou descartar evidências. A
persistência de checkpoints permanece para retomada, sem representar uma
concessão finita de recursos.

A lane Wiki explícita/source-wide usada por VR e Ultra consulta sempre VRWiki +
Endoo, mesmo quando o toggle legado de Endoo está desligado. Cada origem é
consultada em bloco de erro independente: uma falha parcial mantém os hits da
outra origem e a lane só fica indisponível quando todas as origens falham.

## Perfis especialistas

Perfis especialistas são uma camada comportamental sobre o mesmo mecanismo de
acesso dos modos VR e Ultra. A composição de um turno é:

1. política base do modo e identidade do produto;
2. política tool-driven do VR;
3. no máximo uma skill built-in de perfil especialista;
4. skills opcionais escolhidas pelo usuário;
5. solicitação e evidências disponíveis no turno.

Eles existem somente quando o modo resolvido é `vr` ou `ultra`. No modo OFF, o
seletor fica oculto e inativo, `response_mode="auto"` é enviado ao orquestrador e
nenhuma política de perfil é injetada. A preferência persistida não é apagada ao
alternar temporariamente para OFF e pode voltar a valer em VR/Ultra.

Um perfil não habilita, desabilita, prioriza ou remove fontes; não altera o
contrato de `vr_sources`, `vr_search` ou `vr_read`; não cria agentes; e não muda
fontes, workers, paralelismo, ranqueamento, retries, telemetria ou fan-out do
Ultra. VR normal continua decidindo no modelo quando e se consultará uma tool.

**Adaptativa** é o primeiro perfil built-in e usa o identificador interno
`adaptive`. Sua skill não força template, propósito, público ou nível técnico:
ela preserva a `ResponseIntent` detectada automaticamente e orienta como
investigar, aplicar evidências, tratar conflitos e estruturar a resposta.

Treinamento, Suporte e Implantação continuam usando os contratos atuais nesta
entrega. Skills normais escolhidas pelo usuário coexistem com o perfil e não são
convertidas em política de perfil.

Os perfis built-in são empacotados em `vrsoft_extractor/mary/data/` e
materializados como `SkillDefinition` com `scope="vr"`,
`invocation_mode="injected"` e `source="app_managed"`. Eles não são arquivos
editáveis em `VRProject` ou no workspace e não aparecem no gerenciador comum de
skills. Adaptativa não é um agente independente.

## Pacotes de conhecimento (Wiki, Endoo e KB)

A aba "Wiki e KB" em Configurações exporta e importa documentos ativos das
origens VRWiki, Wiki Endoo e KB Movidesk em um único `.zip` portátil
(`vrstudio-knowledge-package`, manifesto `vrstudio-knowledge-export.json`,
`documents.jsonl` e os `.md` canônicos em `files/`). Os anexos referenciados
são sempre empacotados; anexos ausentes no disco são omitidos e contados no
manifesto. A Wiki Endoo é conteúdo autenticado e só entra com seleção
explícita (mesmo contrato do `--include-endoo` no export portátil).

O banco é a fonte de verdade: o `.md` do pacote é regerado de
`canonical_markdown`, e a importação valida manifesto, hashes de registros e
de anexos antes da primeira escrita. O modo "Mesclar" preserva módulo e
revisão aprovados localmente (`preserve_validated_classification`) e
reenfileira revisão quando o conteúdo muda; "Restaurar" grava módulo e
`review_status` do pacote (`upsert_document(preserve_local_review=False)`).
Ao final o catálogo é regenerado (`export_catalog`) e as superfícies de
conhecimento recarregam (`StudioBridge.refreshKnowledgeData`).

O fluxo reutiliza a infraestrutura de tarefas do `ChatBridge`
(`_start_knowledge_transfer_task`, fila, poll de 50 ms e
`_release_snapshot_running`), com os slots `exportKnowledgePackage`,
`detectKnowledgePackageArchive` e `importKnowledgePackageArchive`, os sinais
`knowledgePackageDetected`, `knowledgePackageImported`,
`knowledgePackageExported` e `knowledgeTransferFailed`, e os testes focados:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_transfer.py tests/test_knowledge_transfer_bridge.py -q
```

## Instalação e testes

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints-windows-x64.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```

Use `python -m` nos comandos de desenvolvimento para evitar executáveis de
virtualenv que ainda apontem a um checkout antigo. Ao mover novamente o projeto,
recrie a virtualenv e reinstale o pacote. Preserve `.env`, `.state` e `VRProject`.

### Ciclo de verificação

No checkout Python, o primeiro fluxo Playwright prepara automaticamente o Chromium
compatível. O padrão é hermético (`PLAYWRIGHT_BROWSERS_PATH=0`); valores externos
explícitos são preservados em Python. A distribuição PyInstaller força `0`, usa
somente o Chromium empacotado e nunca baixa browsers em runtime. Caso o binário
esteja ausente, repare ou reextraia a distribuição. O build portátil prepara o
Chromium antes do PyInstaller e valida Chromium/FFmpeg novamente no artefato.

Testes unitários devem mockar a resolução e o instalador do runtime (ou a garantia
no módulo consumidor). Nunca podem disparar download real de browser.

Execute os comandos na raiz, usando o Python da virtualenv:

| Objetivo | Comando após `.\.venv\Scripts\python.exe` |
| --- | --- |
| Imports não usados, nomes indefinidos e erros sintáticos | `-m ruff check .` |
| Teste afetado durante a edição | `-m pytest tests/test_arquivo.py -q -x` |
| Repetir as últimas falhas | `-m pytest --lf -q -x` |
| Backend sem os testes de renderização | `-m pytest -q -m "not qml"` |
| Renderização, interação e lint QML | `-m pytest -q -m qml` |
| Regressão completa e testes mais lentos | `-m pytest -q --durations=10` |

O pytest configura Qt offscreen antes de importar os testes, valida os nomes dos
markers e imprime as stacks se um teste ficar preso por 60 segundos. Isso ajuda
a investigar travamentos; não é um timeout que interrompe o processo.

`tests/conftest.py` elimina somente o escalonamento e o cooldown de retries dos
pesquisadores simulados. As threads, contagem de chamadas, cancelamento e
validação continuam reais. Testes do próprio tempo de espera devem usar
`@pytest.mark.research_timing`; os limites de produção permanecem em
`mary/research_fanout.py`. Faça patches no módulo que usa o símbolo: por exemplo,
`mary.execution.runner`, onde o fan-out é executado.

Evite testes que apenas conferem `hasattr`, defaults de dataclasses ou texto do
código quando um teste comportamental já cobre o contrato. Para Qt, verifique
QMetaObject, sinais, estado e interação; ao mudar layout, confira também as
capturas dos scripts visuais. As fachadas de compatibilidade usam reexports
explícitos (`Nome as Nome`); não remova esses imports automaticamente.

### Onde editar

`mary/db.py` mantém inicialização, migrações e transações. Os métodos de
conhecimento e conversas vêm dos mixins em `mary/repositories/`, compartilhando
esse mesmo estado. Implemente cada operação uma vez no repository. Os slots e
properties do `frontend/chat.py` continuam sendo a interface Qt; alterar sua
exposição exige conferir o QMetaObject e os consumidores QML.

Os transportes concretos ficam em `mary/provider_adapters/`; `mary/providers.py`
preserva imports existentes. O fan-out e seus checkpoints ficam em
`mary/execution/`; busca e ranking ficam em `mary/retrieval/`.

No frontend, os ícones de linha usam a geometria oficial do Lucide em
`frontend/qml/theme/LucidePaths.js`, compartilhada por todas as instâncias de
`VrLineIcon`; somente os kinds sem equivalente Lucide continuam desenhados no
componente. Os tamanhos seguem os tokens `Theme.iconMicro`/`iconCompact`/
`iconSmall`/`iconMedium`/`iconSize` (escala 12/14/16/18/20 do T3 Code) e as
caixas seguem `Theme.iconButtonCompact` (24, `icon-xs`)/`iconButtonNormal` (28,
`icon-sm`)/`iconButtonLarge` (32, `icon`), com `compactControlHeight` em 28
(`h-7`). As laterais usam `Theme.navigationWidth` (256, mínimo
`navigationWidthMinimum` 208) com `sidebarContentInset` 8 e `sidebarRowHeight`
32, e a coluna do chat usa `Theme.contentWidth` (768, `max-w-3xl`). A
rasterização de texto vem da preferência `appearance/text_rendering` (`qt` ou
`native`), aplicada em `create_engine` e exposta em Tipografia.

O markdown do chat segue `.chat-markdown` do T3 Code: corpo em
`Theme.markdownBodySize` (14, `text-sm`) com ritmo 1.625 (`leading-relaxed`),
títulos em 1.25/1.125/1/0.875 rem, código inline e células de tabela em
`markdownCodeSize`/`markdownTableSize` (12, `.75rem`), entrelinha de título
1.3 e margens `.65rem`/`1.25rem 0 .5rem`. `frontend/text_rendering.py` aplica
essas razões ao `QTextDocument`, então a hierarquia acompanha a escala da
interface.

Em VR e Ultra, o código do VRMaster (app central) é fallback do escopo
selecionado: `code_context.master_fallback_context` resolve o contexto do mesmo
pacote e a busca o consulta quando o escopo não retorna trechos, quando o texto
menciona `vrmaster.` ou quando `vr_read` não encontra a referência. Os trechos
do fallback são marcados com `· fallback VRMaster`; a seleção do usuário e o
modo OFF não mudam.

O output do chat usa `frontend/text_rendering.py` para reconhecer cercas de
código, tabelas e fontes; a normalização em `bridges/presentation.py` compartilha
as mesmas cercas para preservar o conteúdo do código durante streaming.
`frontend/file_links.py` reconhece caminhos de arquivo em inline code e os
converte em links `vr-file:`; o clique chama `ChatBridge.openFileReference`, que
abre o arquivo na superfície Arquivos pelo sinal `filePreviewRequested`.

`frontend/code_links.py` e `code_references.py` reconhecem referências a classes e
métodos Java em inline code do chat e as convertem em links `vr-code:`. O link é
criado sintaticamente no display; o clique chama `ChatBridge.openDecompiledReference`,
e `CodePreviewDomain` (`bridges/codepreview.py`) executa
`JavaCodeIndex.resolve_decompiled_reference` em um worker, com a referência canônica
como entrada. O resultado volta à thread Qt por um signal queued e respostas obsoletas
são descartadas por geração incremental. A resolução no `JavaCodeIndex` é exata,
sem busca textual ou fallback. A superfície Código é a page 6, reutilizada para
cada resultado, com visualização Java realçada, alternância Limpo/Descompilado e
posicionamento por scroll no símbolo. O fluxo `vr-file:` permanece independente.
`VrAssistantMessage.qml` atualiza os blocos existentes, preservando os controles
de quebra de linha e ampliação. `VrTableBlock.qml` mantém seleção nativa, rolagem
horizontal e cópia em Markdown, CSV ou TSV; as divisórias seguem as posições
reais das linhas no documento Qt. Os testes `test_chat_output_rendering.py`,
`test_file_links.py` e `test_chat_presentation.py` cobrem conteúdo, clipboard,
tema, posição de leitura e os chips de arquivo.
O script `visual_chat_review.py` também captura tabelas, chips de arquivo e
prompts longos nos temas claro/escuro, janela estreita e escala de 150%.

Todas as barras de progresso usam `VrProgressBar.qml`: posição real (nunca um
percentual inventado), legenda opcional `showPercentage`, marcador de ritmo
(`markerPosition`), limiares `warningThreshold`/`dangerThreshold` e um feixe
indeterminado único, com fallback estático sob `reduceMotion`. O percentual do
import de aplicativos vem de `releaseSnapshotProgress`; a inicialização usa uma
barra de duas etapas reais do catálogo. `scripts/visual_progress_review.py`
renderiza a matriz de estados em `.test-tmp/progress-review`.

A cobertura das releases é consultada por um worker em `bridges/codeadmin.py`.
O worker devolve dados pelo sinal Qt; somente a thread da interface altera o
cache e as preferências. Ao invalidar resultados após processamento ou snapshots,
incremente também a geração para rejeitar consultas anteriores. A suíte
`tests/test_release_coverage_refresh.py` verifica responsividade, invalidação e
encerramento com consultas bloqueadas, sem limites de tempo de desempenho.

### Medições locais

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_hotpaths.py --output .test-tmp/hotpaths.json
.\.venv\Scripts\python.exe scripts/benchmark_hotpaths.py --code-sources 20000 --output .test-tmp/coverage-hotpaths.json
```

Esse benchmark cria e remove sua própria base sintética, mede a assinatura de
conhecimento e a busca vetorial e registra o módulo carregado, a versão do Python,
a mediana e o pico de memória Python. Não acessa contas, `VRProject` ou modelos
remotos. Compare antes/depois com o mesmo corpus e ambiente. Os testes de qualidade
mantêm as exigências de recall/nDCG sem limites de tempo dependentes da máquina.
A opção `--code-sources` também cria um índice Java sintético e mede inicialização
e cobertura de JARs. Os índices SQLite são construídos no primeiro uso; essa
migração inicial não faz parte das medições após aquecimento.
A assinatura usa uma revisão mantida por triggers SQLite; mudanças em documentos e permissões
invalidam o cache, enquanto mensagens de chat não exigem recalcular todos os hashes.

As suítes de regressão antigas que ainda cobrem funções ativas são mantidas.
O benchmark híbrido calcula seu baseline no próprio teste e pode ser executado
sozinho, sem relatórios de execuções anteriores:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_l5_hybrid.py -q
.\.venv\Scripts\python.exe scripts/visual_chat_review.py .test-tmp/visual-review
.\.venv\Scripts\python.exe scripts/visual_settings_all_tabs_review.py .test-tmp/settings-review
.\.venv\Scripts\python.exe scripts/visual_progress_review.py .test-tmp/progress-review
.\.venv\Scripts\python.exe scripts/curate_knowledge_modules.py --help
```

`smoke_codex_chat.py` usa um provedor real autenticado e cria conversas de teste.
Os scripts visuais usam dados isolados. `benchmark_v2_retrieval.py` mantém o corpus
congelado em `tests/fixtures/` e exige os modelos e dependências semânticas indicados
no script. Essas verificações manuais complementam a suíte automatizada.

## VRMonitor

O adapter opcional do VRMonitor reutiliza os providers e o orquestrador existentes. A
configuração local, a allowlist e os limites estão em
[VRMONITOR_INTEGRATION.md](VRMONITOR_INTEGRATION.md). Os testes focados são:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_adapter.py tests/test_antigravity_acp.py -q
```

## Arquivos gerados

`build/`, `dist/`, `releases/`, `reports/`, `.test-tmp/`, caches Python/pytest/ruff
e `*.egg-info/` são saídas locais ignoradas pelo Git. Relatórios e capturas novos
devem ficar em `reports/` ou `.test-tmp/`, sem cópias de fontes ou pacotes binários
versionadas. Documentação que deve ser mantida fica em `docs/`.

Não confundir essas saídas com `VRProject/`, `.env` e `.state`: esses caminhos
guardam dados, credenciais e sessões necessários ao uso local.

A interface Tkinter `vrsoft_extractor/gui.py`, seu inicializador
`VRSoftExtractorGUI.pyw` e sua suíte exclusiva foram retirados. A interface
atual é Qt Quick/QML; o extrator continua disponível nela e pela CLI.

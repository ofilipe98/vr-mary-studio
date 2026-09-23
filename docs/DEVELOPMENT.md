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
| `vrsoft_extractor/mary/execution/` | Execução, orçamento, cancelamento e retomada. |
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

O modo controla a estratégia de resposta; as fontes locais são as mesmas nos
três modos.

- **OFF**: o provedor decide quando pesquisar e as fontes internas ficam
  disponíveis sob demanda. Não há retrieval automático, classificação VR nem
  fan-out.
- **VR**: o modelo principal recebe o contrato VR especializado (identidade,
  fontes disponíveis e política de grounding) e decide usar `vr_sources`,
  `vr_search` e `vr_read`. Há uma única chamada principal; não há agentes,
  research run, fan-out ou síntese. `vr_search` sem `source` consulta Wiki, KB,
  Schema e Código em paralelo (quatro lanes determinísticas em ordem fixa
  wiki, kb, schema, code) e devolve um resultado consolidado; com `source`,
  consulta somente a fonte escolhida. O filtro por módulo não faz parte da tool
  de chat VR: a unidade de consulta é a fonte.
- **Ultra**: mantém o fan-out por fonte com agentes, o agente DEV Java opcional
  e a síntese única validada.

“Fontes disponíveis” não significa “fontes pré-carregadas”. O backend otimiza a
consulta escolhida pelo modelo (por exemplo, o paralelismo interno de
`vr_search`), mas não pesquisa automaticamente antes da resposta.
Prefetch/cache de consulta não pertencem a este contrato.

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
fontes, workers, paralelismo, ranqueamento, retries, orçamento ou fan-out do
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
`iconSmall`/`iconMedium`/`iconSize` (escala 12/14/16/18/20 do T3 Code). A
rasterização de texto vem da preferência `appearance/text_rendering` (`qt` ou
`native`), aplicada em `create_engine` e exposta em Tipografia.

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
`VrAssistantMessage.qml` atualiza os blocos existentes, preservando os controles
de quebra de linha e ampliação. `VrTableBlock.qml` mantém seleção nativa, rolagem
horizontal e cópia em Markdown, CSV ou TSV; as divisórias seguem as posições
reais das linhas no documento Qt. Os testes `test_chat_output_rendering.py`,
`test_file_links.py` e `test_chat_presentation.py` cobrem conteúdo, clipboard,
tema, posição de leitura e os chips de arquivo.
O script `visual_chat_review.py` também captura tabelas, chips de arquivo e
prompts longos nos temas claro/escuro, janela estreita e escala de 150%.

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

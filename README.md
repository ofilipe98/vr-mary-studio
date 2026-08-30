# VR Norte Studio

Aplicativo desktop Windows para manter a base de conhecimento VR, conversar
com Codex, Claude e OpenCode instalados localmente e operar o extrator de vídeos VRSoft.

## Recursos

- Sincronização completa/incremental da VRWiki via API MediaWiki.
- Sincronização somente leitura da Wiki autenticada do Endoo, com sessão
  Playwright, paginação, imagens, OCR, hash e retomada segura.
- Sincronização autenticada do Movidesk KB com Chrome/Playwright e diagnóstico de bloqueios.
- Markdown canônico, imagens locais, OCR por+eng, hash e versionamento.
- Classificação em Fiscal, ADM_FIN_ESTOQUE, PDV, Multimodulo e Revisar.
- Catálogo determinístico de 169 produtos/equipes baseado em `produtos_filas.md`.
- SQLite FTS5, `catalogo.jsonl` e `INDEX.md`.
- Chat em streaming com Codex App Server, Claude Code e OpenCode, com seletor pesquisável,
  favoritos, esforço, service tier e modos Build/Plan por conversa.
- Orquestração VR dinâmica entre modelos Codex/Claude/OpenCode, com dificuldade de 1 a
  5, execução paralela, crítica/validação, transparência opcional e modo Ultra.
- Quatro perfis de aprovação, tools locais/MCP, correção ortográfica portuguesa,
  ramificações por edição e conversas com arquivo e lixeira recuperável.
- Extrator de vídeos Endoo integrado, sem transcrição.
- Dashboard separado para VRWiki, Wiki Endoo, KB e Vídeos.
- Central de Revisão com filtros combináveis, risco, paginação, histórico,
  contexto completo e ações individuais ou em lote confirmado.
- Interface PySide6 baseada na identidade VR Soft, contraste WCAG, foco visível
  e layout validado em 1366×768, 1920×1080 e escalas de 125%/150%.

## VR como projeto Codex portátil

A VR não depende do aplicativo Python para responder perguntas. A própria
pasta da base é preparada como projeto Codex com `AGENTS.md`, especialistas em
`.codex/agents/` e pesquisa local PowerShell em `tools/vr-search.ps1`.

Em uma máquina nova:

1. Copie a pasta `VRProject`.
2. Instale e autentique o Codex normalmente, sem cadastrar outra API key.
3. Execute `VRProject\Abrir-VR-no-Codex.cmd` ou abra essa pasta no Codex.
4. Faça a pergunta diretamente; o prefixo `VR:` é opcional.

O Codex pesquisa o catálogo e os documentos localmente, encaminha a análise aos
especialistas VR e cita os arquivos usados. O VR Norte Studio continua sendo o
gerenciador opcional para sincronizar Wiki/KB, revisar classificações, executar
OCR e administrar vídeos. Credenciais, cookies, logs e vídeos completos não são
incluídos no projeto portátil.

No chat do VR Norte Studio, o botão animado **VR** concentra a pesquisa local e
os modos de orquestração VR em um único menu. A opção **Consultar base local**
pesquisa a base e preserva o assunto em perguntas curtas de continuação; quando
desmarcada, não consulta a base local. O prefixo `VR:` continua opcional quando
o fluxo local está ligado. As respostas citam a URL original da Wiki/KB como
link web ao final e não expõem caminhos locais ou metadados internos.

### Orquestração VR no chat

O fluxo padrão do botão **VR** é direto. A mensagem é normalizada, perguntas
curtas podem herdar o assunto anterior e o roteador classifica intenção e
módulo. Em seguida ele consulta SQLite FTS/chunks nas fontes lógicas `wiki`,
`kb` e `schema`, reranqueia, deduplica e monta um pacote de evidências para o
modelo principal selecionado no composer.

A fonte lógica `wiki` possui duas origens físicas independentes: `vrwiki`
(pública) e `endoo` (autenticada). Elas são pesquisadas separadamente e o
roteador recompõe a cobertura por origem depois da deduplicação, para que uma
origem com mais documentos não esconda a outra. O prompt identifica fonte e
origem; a interface mostra as contagens separadas. A resposta deve citar o URL
original, e o banco registra apenas as evidências cujo URL ou ID foi realmente
usado no texto final.

Assim, **VR ativado** significa identidade VR + pesquisa local + resposta do
provedor principal; **VR desativado** envia a solicitação sem consulta à base
local. O **VR Ultra** acrescenta pesquisadores modulares em paralelo quando a
pergunta envolve vários módulos ou exige investigação aprofundada.

Documentos recuperados são tratados como dados não confiáveis, nunca como
instruções. Schema é priorizado para estrutura física, Wiki para funcionamento
e KB para procedimento. Lacunas, indisponibilidade e conflitos devem aparecer
explicitamente em vez de serem preenchidos por suposição.

## Instalação para desenvolvimento

```powershell
cd D:\Codex\Projetos\vrsoft-video-extractor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints-windows-x64.txt
$env:PLAYWRIGHT_BROWSERS_PATH='0'
.\.venv\Scripts\python.exe -m playwright install chromium
```

Copie `.env.example` para `.env` e preencha apenas as credenciais necessárias:

```dotenv
ENDOO_EMAIL=
ENDOO_PASSWORD=
ENDOO_BASE_URL=https://vrsoft.endoo.com.br
ENDOO_API_URL=https://api.iendo.us/api
VR_ENDOO_WIKI_ENABLED=true
MOVIDESK_EMAIL=
MOVIDESK_PASSWORD=
VR_ROOT=VRProject
VR_OLD_ROOT=
VR_SYNC_INTERVAL_MINUTES=120
VR_DEFAULT_EFFORT=medium
VR_PRODUCTS_FILE=
```

O `.env` e as sessões em `.state` nunca entram no pacote ou nos logs.

### Acesso à Wiki Endoo

O sincronizador abre `/wiki` com a sessão Endoo salva, captura apenas os
cabeçalhos necessários da API e aceita exclusivamente endpoints de leitura sob
`/wiki`. Endpoints `/wiki/manage` são bloqueados pelo cliente. A conta precisa
da permissão `wiki_visualizar`; sessão expirada abre o login visível na
interface. Artigos, imagens e OCR são persistidos como origem `endoo`, enquanto
a VRWiki pública permanece como `vrwiki`.

### Acesso completo ao Movidesk KB

O sincronizador entra primeiro em `/Account/Login`, reutiliza a sessão salva e
só então enumera o KB. Isso é necessário porque artigos internos podem retornar
HTTP 403 e não aparecem na árvore pública. A enumeração lê a página raiz e
percorre, com a mesma sessão autenticada, todas as categorias e paginações
descobertas. As categorias são consultadas concorrentemente, com deduplicação
por ID, timeout e repetição automática para falhas transitórias. O progresso
mostra páginas analisadas, artigos distintos e categorias pendentes.

Se houver MFA ou CAPTCHA, a sincronização normal abre automaticamente uma
janela visível. Conclua o acesso e aguarde a sincronização continuar. O botão
**Sincronizações > Login/KB visível** também permite iniciar diretamente nesse
modo. A sessão autenticada é salva em
`VRProject\.state\movidesk.json`.

## Uso

Abra `Start-VRStudio.bat` ou execute:

```powershell
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.frontend.app --project-dir .
```

A interface Qt Quick/QML é o único frontend desktop.

### Releases do ERP para análise de código

Cada versão do ERP deve ficar isolada em `VRProject/ERP/releases/<release>/jars`.
O inventário registra os 46 JARs, hashes SHA-256, tamanho, classes, informações
do `MANIFEST.MF`, duplicidades de classe e sinais heurísticos de ofuscação. Os
JARs fornecidos manualmente nunca são removidos pelo Studio.

```powershell
# Importar e validar uma release completa
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject import-erp-release 2026.08.28

# Verificação rápida por tamanho e data, ou verificação integral por hash
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-release 2026.08.28 --full-hash

# Remover somente o índice regenerável, com aprovação explícita
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject remove-erp-release-index 2026.08.28 --approve
```

Para importar temporariamente uma pasta fora do layout padrão, use `--path`.
Uma release com quantidade diferente de 46 JARs ou algum arquivo inválido é
registrada como `incomplete` e não deve ser selecionada pelo Agente de Código.
O catálogo mantém no máximo três releases e usa como orçamento inicial do
índice dez vezes o tamanho da primeira release importada; ele nunca remove uma
versão automaticamente para abrir espaço.

O diagnóstico da toolchain de código procura primeiro um Java 17 isolado em
`VRProject/tools/code-analysis/java17`, sem alterar o Java global do ERP. As
versões iniciais aprovadas são Vineflower 1.12.0 e CFR 0.152, com checksum
validado antes do uso:

```powershell
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject doctor-code-analysis
```

Antes de decompilar uma release, o Gate 1 mede conteúdos únicos e conflitos de
bytecode em um conjunto representativo de JARs:

```powershell
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject inspect-erp-classes current `
  --jar VRMaster.jar --jar VRAtacarejo.jar --jar VRPdv.jar `
  --jar lib/VRLib.jar --jar lib/VRCore.jar
```

O processamento definitivo usa lotes retomáveis de famílias de classes,
deduplicados pelo SHA-256 do bytecode. O estado fica separado em
`indice/codigo/processing.sqlite`; um lock global permite somente um
decompilador por vez. Cada tentativa preserva entrada, saída e `attempt.json`
com release, hashes, ferramenta e cobertura. Um lote só fica `completed` se o
processo terminar normalmente e gerar todas as famílias Java esperadas.

```powershell
# Planejar: repita --jar para restringir o escopo; sem ele, usa os 46 JARs
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject plan-erp-decompilation current `
  --jar VRPdv.jar --max-classes 500 --max-bytes 8388608

# Consultar o progresso pelo identificador retornado no planejamento
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-decompilation plan-<id>

# Executar um lote por vez; Vineflower é primário e CFR é fallback
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject run-erp-decompilation plan-<id> `
  --limit 1 --heap-mb 2048 --timeout 300

# Uma falha nunca é ocultada; o reenvio exige uma ação explícita
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject retry-erp-decompilation batch-<id>
```

Se o Studio for interrompido, o lock exclusivo garante que um lote deixado em
`running` só volte a `pending` quando não houver outro executor ativo. Saídas
parciais ficam preservadas e não entram como conteúdo pronto.

Os fontes aprovados podem ser promovidos para o índice pesquisável. Esta etapa
é incremental: mudanças na versão do extrator reprocessam os símbolos, enquanto
fontes e versão de parser inalterados são ignorados. Toda resposta inclui
release, JAR, classe, linhas, hashes e o frescor atual da release.

```powershell
# Indexar somente lotes já concluídos e com cobertura aprovada
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject index-erp-code plan-<id>

# Conferir cobertura e pesquisar por classe, pacote, método, campo ou conteúdo
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-code current
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject search-erp-code VendaVO --release current --limit 5
```

Para ampliar a cobertura sem criar um plano monolítico para cerca de 1,3 milhão
de ocorrências de classe, use o fluxo incremental. O status diferencia os JARs
apenas inventariados dos efetivamente processados, projeta o consumo com a
reserva conservadora de 10× e mostra planos antigos sem tratá-los como ativos.

```powershell
# Conferir cobertura, capacidade, frescor e planos antes de gravar dados
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-code-coverage current

# Avançar o menor JAR pendente; repita para retomar o mesmo plano até concluí-lo
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject advance-erp-code-coverage current `
  --limit 10 --approve-processing

# Seleção manual continua disponível para um módulo prioritário
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject advance-erp-code-coverage current `
  --jar VRMaster.jar --limit 1 --approve-processing
```

Sem `--jar`, um novo plano começa pelos menores JARs pendentes para produzir
resultados verificáveis cedo; um plano atual já iniciado sempre é retomado antes
de selecionar outro. A execução continua serial, indexa somente lotes concluídos
e para diante de falha/saída parcial. O comando não remove planos antigos nem
fontes fornecidas pelo usuário.

O índice atual combina correspondência exata de símbolos, FTS5 sobre nomes e
corpo e relações estruturais (`import`, `extends`, `implements`). A evolução
para AST completo e embeddings deve complementar essa base sem retirar sua
proveniência determinística.

Na aba `Configurações > VR Ultra`, o toggle **Agente de Código / JAR** permanece
desligado por padrão e permite escolher a release. Quando ligado, os agentes
base delimitam primeiro o assunto; só então o worker de código consulta até
oito fontes candidatas do índice, analisa os trechos em contexto isolado e os
entrega à síntese. Se o índice ou o worker falhar, o VR Ultra continua com
Schema/Wiki/KB e registra a degradação na trilha da execução.
O seletor mostra cobertura efetiva, por exemplo `3/46 JARs indexados`, separada
do inventário completo da release.

O checkpoint controlado do Gate 11 chegou a 10/46 JARs, incluindo `VRPdv`,
`VRGerenciadorNFCe`, `VRConcentrador`, `VRAutorizador` e `VRAtacado`. A medição,
os critérios de parada e a divergência de entradas duplicadas encontrada no
`VRAtacado.jar` estão documentados em
`design/GATE11_EXPANSAO_CONTROLADA_PRIORITARIOS_2026-08-30.md`. `VRAtacarejo` e
`VRMaster` permanecem pendentes até a política de classpath/duplicatas ser
formalizada; consultas não devem escolher silenciosamente uma variante
conflitante.

O Gate 12 formaliza essa política em
`design/GATE12_CLASSPATH_DUPLICATAS_2026-08-30.md`. A análise incremental grava
a variante que `java.util.jar.JarFile` realmente seleciona dentro de cada JAR e
cruza conflitos entre artefatos. Sem um perfil completo, a busca devolve
`classpath_resolution: ambiguous` e o Agente de Código reduz a confiança.

```powershell
# Analisar os 46 JARs; artefatos já conhecidos são reutilizados por SHA-256
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject inspect-erp-classpath current

# Conferir perfis candidatos e política efetiva
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-classpath current
```

Use `set-erp-classpath ... --complete --approve` apenas quando a ordem tiver
sido confirmada no launcher ou trace real. Declarações `Class-Path` do manifesto
são sugestões parciais e não são promovidas automaticamente.

O Gate 13 concluiu `VRAtacarejo.jar` e `VRMaster.jar`, elevando a cobertura para
12/46 e completando os sete módulos principais. A execução real também levou o
pipeline a aceitar fontes Java e Kotlin do Vineflower e a respeitar a semântica
de capitalização do filesystem ao validar caminhos. Métricas, retries e
critérios estão em
`design/GATE13_COBERTURA_ATACAREJO_MASTER_2026-08-30.md`.

### Benchmark pareado do Agente de Código

O ganho do toggle deve ser medido com chamados já resolvidos cuja causa em
código seja conhecida. O benchmark aceita somente casos classificados como
`anonymized` ou `synthetic`, executa cada pergunta duas vezes no VR Ultra
(Agente de Código desligado e ligado) e alterna a ordem entre casos para reduzir
viés de aquecimento. Cada relatório preserva respostas, citações, workers,
tokens, latência e a cobertura real do índice utilizado; a preferência final
continua sendo uma revisão humana.

```powershell
# Gerar o modelo, anonimizar e preencher os casos antes da execução
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject benchmark-code-analysis-template `
  --output casos-codigo.json

# Duas execuções VR Ultra por caso: exige confirmação explícita de custo/dados
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject benchmark-code-analysis casos-codigo.json `
  --provider codex --model gpt-5.4 --approve-model-usage
```

O comando recusa releases ausentes/desatualizadas e índices sem fontes. O
relatório completo é gravado em
`VRProject/indice/evaluations/code-analysis/`. Revise e anonimize o arquivo de
casos antes de usar `--approve-model-usage`: a flag confirma tanto as duas
chamadas por caso quanto o envio do conteúdo ao provedor configurado.

CLI da base:

```powershell
.\.venv\Scripts\vr-norte.exe init
.\.venv\Scripts\vr-norte.exe migrate --dry-run
.\.venv\Scripts\vr-norte.exe migrate
.\.venv\Scripts\vr-norte.exe sync-wiki
.\.venv\Scripts\vr-norte.exe sync-endoo-wiki --headed
.\.venv\Scripts\vr-norte.exe sync-wikis
.\.venv\Scripts\vr-norte.exe sync-kb --headed
.\.venv\Scripts\vr-norte.exe search "configuração PIX" --origin endoo
.\.venv\Scripts\vr-norte.exe audit-classification --examples 10
.\.venv\Scripts\vr-norte.exe audit-classification --queue-review --examples 0
.\.venv\Scripts\vr-norte.exe status
.\.venv\Scripts\vr-norte.exe prepare-codex
.\.venv\Scripts\vr-norte.exe export-portable D:\Destino\VRProject
.\.venv\Scripts\vr-norte.exe export-portable --include-endoo D:\DestinoPrivado\VRProject
```

Por padrão, `export-portable` exclui a origem autenticada `endoo`. Use
`--include-endoo` somente para um destino privado autorizado.

Quando a categoria informa explicitamente `FISCAL`, `PDV` ou a família
`ADM`/`FINANCEIRO`/`ESTOQUE`, esse módulo prevalece sobre título, produto e
conteúdo. Se uma categoria preenchida não informa um módulo de forma explícita
e inequívoca, o item permanece em `Revisar`; quando ela identifica dois ou mais
módulos, o item segue aprovado para `Multimodulo`. Sem categoria, o classificador
prioriza o produto mais específico encontrado no título ou campo de produto.
Produtos híbridos, como `VRAdm` e `VRCaixa`, usam o contexto do artigo para
desempate e permanecem aprovados em `Multimodulo` quando há evidência para mais
de um módulo. A
auditoria é somente leitura.
Use `--queue-review` para atualizar apenas as sugestões da tela Revisão,
mantendo o módulo atual até a aprovação humana.

## Central de Revisão

- A fila abre com itens pendentes e maior risco primeiro.
- A busca cobre título, ID, produto, categoria, evidências, Markdown e OCR.
- Os filtros incluem fonte, módulos, confiança, produto, categoria, estado,
  período e riscos especiais.
- Cada decisão pode aprovar, manter o módulo atual, adiar ou reabrir e aceitar
  uma nota opcional.
- `Selecionar todos` marca os até 100 itens da página atual; após confirmação,
  o destino escolhido é aplicado ao lote mesmo com sugestões diferentes.
- Atalhos: `Alt+A` aprovar, `Alt+M` manter, `Alt+D` adiar e
  `PageUp`/`PageDown` para navegar.

Os comandos antigos permanecem disponíveis:

```powershell
.\.venv\Scripts\vrsoft-extractor.exe login
.\.venv\Scripts\vrsoft-extractor.exe scan
.\.venv\Scripts\vrsoft-extractor.exe download
.\.venv\Scripts\vrsoft-extractor.exe run
```

### Cursos, inscrição e classificação dos vídeos

A aba **Vídeos** mostra o catálogo Endoo e o inventário em árvore. Cursos com
turma aberta podem ser marcados e inscritos somente depois de confirmação
explícita. Cursos fechados e de fila de espera permanecem visíveis, mas não
são selecionáveis. Depois de uma inscrição confirmada, o inventário é
atualizado; o download continua manual.

Os vídeos são classificados por metadados em `Fiscal`, `ADM_FIN_ESTOQUE`,
`PDV`, `Multimodulo` ou `Revisar`. A classificação não analisa o áudio. As
correções manuais feitas na árvore são persistidas em
`metadata/video_module_overrides.json`.

As colunas **Download** e **Tamanho** consultam os arquivos reais no disco.
Cada vídeo mostra se está baixado, pendente ou com arquivo ausente; cursos,
módulos e pastas exibem a quantidade baixada e o tamanho total agregado.

```text
downloads/Cursos/<Módulo>/<Curso>/<Capítulo>/<Vídeo>.<ext>
downloads/Biblioteca/<Módulo>/<Pastas originais>/<Vídeo>.<ext>
```

Comandos adicionais:

```powershell
.\.venv\Scripts\vrsoft-extractor.exe courses
.\.venv\Scripts\vrsoft-extractor.exe classify-videos
.\.venv\Scripts\vrsoft-extractor.exe enroll 10009:491503 --confirm --scan-after
```

`enroll` exige o par `CURSO:TURMA` e `--confirm`; sem confirmação nenhuma
inscrição é enviada ao Endoo.

## Codex, Claude e OpenCode

- Codex usa `codex app-server` e JSON-RPC em stdio. A criação da thread envia
  os valores kebab-case `read-only`, `workspace-write` ou
  `danger-full-access`; cada turno envia o `sandboxPolicy.type` correspondente
  em camelCase (`readOnly`, `workspaceWrite` ou `dangerFullAccess`).
- Claude usa `stream-json`, retoma por `session_id` e recebe permissões de escrita
  apenas para a pasta da conversa.
- OpenCode usa `run --format json`, mantém a identidade completa
  `provider/model`, retoma por `sessionID` e respeita o perfil de aprovação do chat.
- Cada conversa grava arquivos em `VRProject\TrabalhoVR\<id>`.
- Modelo, esforço, tier, perfil de aprovação, modo e seleção de tools ficam
  persistidos em cada conversa. `Auto` é o perfil padrão.
- Tools locais executam sem shell, recebem JSON por `stdin` e devolvem
  texto/JSON por `stdout`, com timeout e limite de 64 KiB. A seleção MCP é
  aplicada somente à configuração da thread, sem alterar o `config.toml`.
- O corretor é ortográfico, local e em português; ele não promete revisão
  gramatical avançada. Palavras pessoais ficam na pasta de estado da VR.
- Alterar provedor/tools ou editar uma mensagem cria uma ramificação e mantém a
  conversa original. Arquivar/restaurar sincroniza com o Codex; Claude e
  OpenCode mantêm esse estado local, e a exclusão definitiva remove a sessão
  OpenCode correspondente.
- Use **Clonar para outro provedor** para transferir o contexto entre agentes.

## OCR

Na tela Configurações, use **Instalar OCR portátil por+eng**. O mecanismo e os
idiomas são instalados em `VRProject\tools\tesseract`; nada é enviado a um
serviço online.

## Empacotamento

```powershell
.\build_portable.ps1
```

O canal é determinado pela branch atual e o repositório deve estar limpo. Na
branch `main`, é gerado `VRNortePortable-main-<versão>.zip`. Na branch `dev`, é
gerado `VRNortePortable-dev-<versão>-<revisão>.zip`. Todo pacote inclui um
`build-info.json` com canal, branch e commit exatos, evitando que uma build de
teste seja confundida com a estável.

O ZIP reúne `App` e a estrutura do `VRProject`, incluindo agentes e Schema, mas
não incorpora por padrão o acervo sincronizado de KB e Wiki. Essas fontes podem
ser sincronizadas no ambiente de destino com as credenciais do usuário. Use
`Abrir-VR-Studio.cmd` para o gerenciador ou
`VRProject\Abrir-VR-no-Codex.cmd` para trabalhar diretamente no Codex. Se
Inno Setup estiver instalado, compile `installer\VRNorteStudio.iss` para produzir
o instalador Windows.

Para uma exportação excepcional que inclua o acervo completo, execute
`build_portable.ps1 -IncludeKnowledgeBase`.

A distribuição portátil oficial é destinada ao Windows 10/11 x64, incorpora
Python, Chromium e FFmpeg e deve ser totalmente extraída antes da execução. O
arquivo `LEIA-ME-PORTATIL.txt` acompanha a raiz do ZIP. O build também atualiza
`releases\SHA256SUMS.txt`; use esse hash para conferir o arquivo antes de
distribuí-lo. Credenciais e CLIs de provedores de chat não são incorporados.

## Fluxo de versões

- `main` contém apenas a versão estável aprovada.
- O ciclo `0.4` usa uma versão-base estável sem sufixo e revisões incrementais
  com hífen: `0.4`, `0.4-1`, `0.4-2` e assim sucessivamente.
- Logo após cada promoção, `dev` avança para a próxima revisão desse ciclo. Por
  exemplo: após promover `0.4-1`, abra `0.4-2` em `dev`.
- Toda melhoria, correção ou alteração nova entra primeiro em `dev`.
- A build `dev` é entregue para homologação e permanece identificada pelo commit.
- Depois da aprovação explícita, integre a versão validada de `dev` em `main`,
  execute a suíte completa e gere a nova build `main`.
- Não desenvolva diretamente em `main` nem promova uma árvore com alterações
  locais pendentes.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Smoke test visual:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.frontend.app --smoke-test
```

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
No escopo **Release completa**, o inventário registra os 46 JARs, hashes SHA-256, tamanho, classes, informações
do `MANIFEST.MF`, duplicidades de classe e sinais heurísticos de ofuscação. Os
JARs fornecidos manualmente nunca são removidos pelo Studio.

Para uma investigação focada, a interface também oferece o escopo **Somente um
JAR**. O analista escolhe explicitamente o arquivo, que recebe um manifesto
`single_jar` e cobertura `1/1`. Esse índice pode ser usado pelo Agente de Código,
mas permanece identificado como parcial e não representa a cobertura completa
do ERP.

```powershell
# Importar e validar uma release completa
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject import-erp-release 2026.08.28

# Origem padrão do analista: copia e valida sem modificar C:\vr\exec
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject snapshot-erp-release 2026.08.28 `
  --source "C:\vr\exec"

# Escopo parcial: copia e valida somente o JAR explicitamente selecionado
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject snapshot-erp-release 2026.08.28-vrpdv `
  --source "C:\vr\exec\VRPdv.jar" --expected-jars 1

# Verificação rápida por tamanho e data, ou verificação integral por hash
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-release 2026.08.28 --full-hash

# Remover somente o índice regenerável, com aprovação explícita
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject remove-erp-release-index 2026.08.28 --approve
```

Para importar temporariamente uma pasta fora do layout padrão, use `--path`.
Uma release completa com quantidade diferente de 46 JARs ou algum arquivo
inválido é registrada como `incomplete`. O escopo de JAR único só é considerado
pronto quando o arquivo foi escolhido explicitamente e validado como JAR.
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

Antes de iniciar uma cobertura real, o preflight offline valida identidade,
escopo declarado (46 JARs ou um JAR explicitamente selecionado), hashes,
frescor, toolchain, capacidade e classpath. Ele não chama modelo, não acessa
rede, não decompila e não modifica a origem:

```powershell
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject preflight-erp-code-offline <release_id>
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

O Gate 14 acrescenta preflight obrigatório e revisão humana realmente cega.
Cada caso declara módulo, JARs-alvo, causa-raiz conhecida, termos, símbolos,
fontes esperadas e hipóteses proibidas. Execute o preflight antes de aprovar
custo; ele bloqueia placeholders, cobertura insuficiente e símbolos ausentes:

```powershell
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject preflight-code-analysis casos-codigo.json

# Depois do benchmark, separar respostas A/B da chave off/on
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject prepare-code-analysis-review relatorio.json `
  --output review.json --key-output review-key.json

# Preencher review.json sem consultar a chave e então consolidar
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject finalize-code-analysis-review `
  relatorio.json review.json review-key.json --output reviewed.json
```

O desenho, a validação contra o índice real e as regras de integridade estão em
`design/GATE14_PREFLIGHT_REVISAO_CEGA_2026-08-30.md`.

O Gate 15 acrescenta uma barreira de entrada para chamados reais. Suítes
`anonymized` precisam conter 5–10 casos resolvidos, método de seleção, tamanho
do conjunto candidato, revisão humana de anonimização e evidência da causa. Um
scanner local bloqueia padrões sensíveis óbvios sem reproduzir o valor no
relatório; ele complementa, mas não substitui, a revisão humana.

```powershell
# Auditar e congelar a seleção antes de olhar qualquer resposta
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  audit-code-analysis-cases casos-codigo.json

.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  freeze-code-analysis-cases casos-codigo.json `
  --output casos-codigo.intake.json

# O SHA-256 do manifesto precisa continuar correspondendo à suíte
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject preflight-code-analysis casos-codigo.json `
  --intake-manifest casos-codigo.intake.json
```

O benchmark de uma suíte real também exige
`--intake-manifest casos-codigo.intake.json`. Qualquer alteração posterior nos
casos ou critérios invalida o manifesto e bloqueia o envio. Contrato, limites do
scanner e critérios estão em
`design/GATE15_INTAKE_CASOS_REAIS_2026-08-30.md`.

O Gate 16 aceita páginas de tickets Movidesk salvas como ZIP. O inventário não
expõe assunto nem mensagens; a preparação gera um pacote pseudonimizado e uma
chave sensível de origem em arquivos separados. Nenhum candidato é marcado como
elegível apenas porque o ticket está resolvido ou contém termos de código.

```powershell
# Inventário local e seguro
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  audit-movidesk-ticket-archives "C:\Caminho\Auditoria"

# Revisar somente o pacote; não compartilhar a chave de origem
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  prepare-movidesk-ticket-review "C:\Caminho\Auditoria" `
  --output tickets-review.json --key-output tickets-source-key.json
```

O pacote continua com `safe_for_model: false` até revisão humana, mesmo quando
todos os detectores automáticos ficam zerados. Resultados e limites estão em
`design/GATE16_INTAKE_ARQUIVOS_MOVIDESK_2026-08-30.md`.

O Gate 17 fecha essa revisão sem enviar o histórico bruto ao modelo. No bloco
`review` de cada candidato, o revisor preenche título e pergunta anonimizados,
data da resolução, módulo, JARs, causa-raiz, evidência e critérios esperados.
Somente 5–10 casos com `anonymization_approved: true` e
`eligible_for_code_benchmark: true` podem virar suíte. A release é sempre
informada explicitamente; ela nunca é inferida da pasta ou dos tickets.

```powershell
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  finalize-movidesk-ticket-review tickets-review.json tickets-source-key.json `
  --release RELEASE_ESCOLHIDA `
  --anonymization-review-id anon-review-local-001 `
  --output casos-codigo.json `
  --manifest-output casos-codigo.intake.json
```

A operação comprova que pacote e chave pertencem ao mesmo conjunto, detecta
alterações no conteúdo pseudonimizado, reexecuta a auditoria de dados sensíveis
nos campos manuais e produz o manifesto SHA-256 junto com a suíte. O pacote de
revisão e a chave continuam locais e não devem ser compartilhados. Detalhes em
`design/GATE17_FINALIZACAO_REVISAO_TICKETS_2026-08-30.md`.

Para uso por vários analistas, a indexação de releases é local e independente
de LLM. Cada workspace mantém seu próprio catálogo de até três releases e a
release ativa fica vinculada ao workspace. O congelamento de release e hash em
cada execução já cobre o job local e o Agente de Código do fan-out. O
pipeline obrigatório usa apenas SHA-256, leitura de ZIP/JAR, Java 17,
Vineflower/CFR, AST/grafo e SQLite/FTS. Modelos entram somente depois, na
consulta e síntese; indisponibilidade de provedor não pode impedir uma release
de chegar a `ready`. O plano de produto e migração do portátil genérico está em
`design/GATE18_INDEXACAO_LOCAL_POR_ANALISTA_2026-08-30.md`.

Na máquina do analista, a origem padrão dos JARs é `C:\vr\exec`. A tela de
configuração permite alternar entre esse diretório e a estrutura atual
do workspace. A importação lê a origem sem modificá-la e cria um snapshot local
por `release_id` e hash antes de iniciar o índice.

Em **Escopo da análise**, escolha **Release completa · 46 JARs** para cobertura
integral ou **Somente um JAR** para selecionar um arquivo no diálogo. No segundo
caso, informe um `release_id` próprio, escolha o JAR e use **Adicionar release**.
O seletor identifica a base como `escopo: 1 JAR`, evitando apresentá-la como uma
release ERP completa.

Essa primeira fatia já está disponível na configuração do VR Ultra. A escolha é
persistida por workspace, mostra existência e contagem de JARs e não muda
silenciosamente quando `C:\vr\exec` está ausente. O comando de snapshot exige a
contagem configurada, valida os ZIP/JARs, copia para a área gerenciada e compara
SHA-256 antes de inventariar a release. A mesma operação está disponível pelo
campo de release e pelo botão **Adicionar release**; ela roda em background,
bloqueia importações simultâneas e atualiza o seletor quando termina. Nenhuma
etapa chama modelo.

A aba VR Ultra também executa agora essa fila local em background. **Iniciar** ou
**Retomar** avança planos persistidos um lote por vez; **Pausar** espera o Java
atual terminar e para antes do lote seguinte; o seletor de falhas permite
escolher qual estado `failed/partial` será reenfileirado. A tela também configura
heap de 1/2/4 GB, timeout de 5/10/20 minutos, afinidade de 1/2/4 núcleos,
orçamento de disco de 5/8/10× e janela de execução (`sempre`, `00h–06h` ou
`18h–06h`). Tudo é persistido por workspace e congelado no início do job. A
concorrência Java permanece fixa em 1 processo e o subprocesso usa prioridade
baixa por padrão.
Antes de começar, o Studio exige Java 17 e ao
menos um decompilador verificado, congela `release_id` e SHA-256 do manifesto e
grava os eventos em
`VRProject\indice\codigo\processing-runs.jsonl`. A consulta de cobertura também
roda fora da thread da interface. Ao reabrir o Studio, a aba restaura a última
release/hash, o estado retomável e o JAR/lote atual ou próximo, sem reiniciar o
processamento. Em cada análise VR Ultra, o Agente de Código recebe a release, o
hash congelado e o `run_id` do fan-out; se a origem estiver desatualizada ou o
hash divergir, apenas esse worker falha e a síntese continua com as demais
fontes. Cada tentativa de decompilação também registra duração, pico de memória
do subprocesso, tempo de CPU, bytes de entrada/saída e timeout. A aba agrega os
valores por job e restaura o último resumo a partir da auditoria local.
Com histórico suficiente, a mesma auditoria calcula um ETA pela mediana local
de tempo por novo JAR coberto, exibindo quantidade de amostras e confiança sem
inventar estimativa na primeira execução.

JARs idênticos entre releases reutilizam a decompilação e o índice pesquisável
por SHA-256, mas recebem novas linhas vinculadas ao `release_id` de destino para
preservar filtros e citações. O schema do índice inclui `release_id` na chave;
duas releases com os mesmos bytes não colidem. A remoção aprovada limpa planos e
fontes pesquisáveis da release, preserva os JARs de origem e mantém artefatos
compartilhados ainda referenciados.

O índice também pode ser transportado opcionalmente em pacote `.vridx`. O
pacote não contém JARs, é verificado por SHA-256 em streaming e só é importado
quando `release_id`, manifesto e hashes de cada artefato coincidem com a release
local fresca. Esse atalho não substitui a indexação local.

```powershell
# Ajustar o orçamento gerado (máximo contratual: 10×)
.\.venv\Scripts\vr-norte.exe --root VRProject set-erp-code-storage-budget --multiplier 8

# Exportar/importar o índice offline sem transportar os JARs
.\.venv\Scripts\vr-norte.exe --root VRProject export-erp-code-index 4.1.0 D:\Transfer\4.1.0.vridx
.\.venv\Scripts\vr-norte.exe --root VRProject import-erp-code-index D:\Transfer\4.1.0.vridx --release 4.1.0

# Relatório offline de aceite e isolamento entre releases
.\.venv\Scripts\vr-norte.exe --root VRProject validate-erp-code-field `
  --release 4.1.0 --release 4.2.0 --probe-symbol VendaController `
  --require-distinct-hashes
```

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
- Candidatas beta aprovadas explicitamente usam o formato PEP 440
  `major.minor.patchbN`, por exemplo `0.4.21b1`, e podem ser promovidas para
  `main` para homologação controlada.
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

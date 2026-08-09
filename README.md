# VR Norte Studio

Aplicativo desktop Windows para manter a base de conhecimento Mary, conversar
com Codex/Claude instalados localmente e operar o extrator de vídeos VRSoft.

## Recursos

- Sincronização completa/incremental da VRWiki via API MediaWiki.
- Sincronização autenticada do Movidesk KB com Chrome/Playwright e diagnóstico de bloqueios.
- Markdown canônico, imagens locais, OCR por+eng, hash e versionamento.
- Classificação em Fiscal, ADM_FIN_ESTOQUE, PDV, Multimodulo e Revisar.
- Catálogo determinístico de 169 produtos/equipes baseado em `produtos_filas.md`.
- SQLite FTS5, `catalogo.jsonl` e `INDEX.md`.
- Chat em streaming com Codex App Server e Claude Code, com seletor pesquisável,
  favoritos, esforço, service tier e modos Build/Plan por conversa.
- Quatro perfis de aprovação, tools locais/MCP, correção ortográfica portuguesa,
  ramificações por edição e conversas com arquivo e lixeira recuperável.
- Extrator de vídeos Endoo integrado, sem transcrição.
- Dashboard separado para Wiki, KB e Vídeos.
- Central de Revisão com filtros combináveis, risco, paginação, histórico,
  contexto completo e ações individuais ou em lote confirmado.
- Interface PySide6 baseada na identidade VR Soft, contraste WCAG, foco visível
  e layout validado em 1366×768, 1920×1080 e escalas de 125%/150%.

## Mary como projeto Codex portátil

A Mary não depende do aplicativo Python para responder perguntas. A própria
pasta da base é preparada como projeto Codex com `AGENTS.md`, especialistas em
`.codex/agents/` e pesquisa local PowerShell em `tools/mary-search.ps1`.

Em uma máquina nova:

1. Copie a pasta `MaryProject`.
2. Instale e autentique o Codex normalmente, sem cadastrar outra API key.
3. Execute `MaryProject\Abrir-Mary-no-Codex.cmd` ou abra essa pasta no Codex.
4. Faça a pergunta diretamente; o prefixo `Mary:` é opcional.

O Codex pesquisa o catálogo e os documentos localmente, encaminha a análise aos
especialistas Mary e cita os arquivos usados. O VR Norte Studio continua sendo o
gerenciador opcional para sincronizar Wiki/KB, revisar classificações, executar
OCR e administrar vídeos. Credenciais, cookies, logs e vídeos completos não são
incluídos no projeto portátil.

No chat do VR Norte Studio, o botão animado **VR** controla a pesquisa local no
Codex e no Claude. Ligado, ele pesquisa a base e preserva o assunto em perguntas
curtas de continuação; desligado, a mensagem segue diretamente para a LLM. O
prefixo `Mary:` continua opcional quando o fluxo VR está ligado. As respostas
citam a URL original da Wiki/KB como link web e mantêm o caminho local em texto
copiável.

## Instalação para desenvolvimento

```powershell
cd D:\Codex\Projetos\vrsoft-video-extractor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PLAYWRIGHT_BROWSERS_PATH='0'
.\.venv\Scripts\python.exe -m playwright install chromium
```

Copie `.env.example` para `.env` e preencha apenas as credenciais necessárias:

```dotenv
ENDOO_EMAIL=
ENDOO_PASSWORD=
MOVIDESK_EMAIL=
MOVIDESK_PASSWORD=
MARY_ROOT=MaryProject
MARY_OLD_ROOT=
MARY_SYNC_INTERVAL_MINUTES=120
MARY_DEFAULT_EFFORT=medium
MARY_PRODUCTS_FILE=
```

O `.env` e as sessões em `.state` nunca entram no pacote ou nos logs.

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
`VR_Mary_V2\.state\movidesk.json`.

## Uso

Abra `Start-VRMaryStudio.bat` ou execute:

```powershell
.\.venv\Scripts\vr-mary-studio.exe --project-dir .
```

CLI da base:

```powershell
.\.venv\Scripts\vr-mary.exe init
.\.venv\Scripts\vr-mary.exe migrate --dry-run
.\.venv\Scripts\vr-mary.exe migrate
.\.venv\Scripts\vr-mary.exe sync-wiki
.\.venv\Scripts\vr-mary.exe sync-kb --headed
.\.venv\Scripts\vr-mary.exe search "configuração PIX"
.\.venv\Scripts\vr-mary.exe audit-classification --examples 10
.\.venv\Scripts\vr-mary.exe audit-classification --queue-review --examples 0
.\.venv\Scripts\vr-mary.exe status
.\.venv\Scripts\vr-mary.exe prepare-codex
.\.venv\Scripts\vr-mary.exe export-portable D:\Destino\MaryProject
```

Quando a categoria informa explicitamente `FISCAL`, `PDV` ou a família
`ADM`/`FINANCEIRO`/`ESTOQUE`, esse módulo prevalece sobre título, produto e
conteúdo. Se uma categoria preenchida não informa um módulo de forma explícita
e inequívoca, o item permanece em `Revisar`. Sem categoria, o classificador
prioriza o produto mais específico encontrado no título ou campo de produto.
Produtos híbridos, como `VRAdm` e `VRCaixa`, usam o contexto do artigo para
desempate e permanecem em `Multimodulo` quando não há evidência suficiente. A
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

## Codex e Claude

- Codex usa `codex app-server` e JSON-RPC em stdio. A criação da thread envia
  os valores kebab-case `read-only`, `workspace-write` ou
  `danger-full-access`; cada turno envia o `sandboxPolicy.type` correspondente
  em camelCase (`readOnly`, `workspaceWrite` ou `dangerFullAccess`).
- Claude usa `stream-json`, retoma por `session_id` e recebe permissões de escrita
  apenas para a pasta da conversa.
- Cada conversa grava arquivos em `VR_Mary_V2\TrabalhoMary\<id>`.
- Modelo, esforço, tier, perfil de aprovação, modo e seleção de tools ficam
  persistidos em cada conversa. `Auto` é o perfil padrão.
- Tools locais executam sem shell, recebem JSON por `stdin` e devolvem
  texto/JSON por `stdout`, com timeout e limite de 64 KiB. A seleção MCP é
  aplicada somente à configuração da thread, sem alterar o `config.toml`.
- O corretor é ortográfico, local e em português; ele não promete revisão
  gramatical avançada. Palavras pessoais ficam na pasta de estado do Mary.
- Alterar provedor/tools ou editar uma mensagem cria uma ramificação e mantém a
  conversa original. Arquivar/restaurar sincroniza com o Codex; Claude usa
  somente o estado local.
- Use **Clonar para outro provedor** para transferir o contexto entre agentes.

## OCR

Na tela Configurações, use **Instalar OCR portátil por+eng**. O mecanismo e os
idiomas são instalados em `VR_Mary_V2\tools\tesseract`; nada é enviado a um
serviço online.

## Empacotamento

```powershell
.\build_portable.ps1
```

O canal é determinado pela branch atual e o repositório deve estar limpo. Na
branch `main`, é gerado `VRMaryPortable-main-<versão>.zip`. Na branch `dev`, é
gerado `VRMaryPortable-dev-<versão>-<revisão>.zip`. Todo pacote inclui um
`build-info.json` com canal, branch e commit exatos, evitando que uma build de
teste seja confundida com a estável.

O ZIP reúne `App` e `MaryProject`; o pacote completo já inclui o aplicativo. Nele, use
`Abrir-VR-Mary-Studio.cmd` para o gerenciador ou
`MaryProject\Abrir-Mary-no-Codex.cmd` para trabalhar diretamente no Codex. Se
Inno Setup estiver instalado, compile `installer\VRMaryStudio.iss` para produzir
o instalador Windows.

## Fluxo de versões

- `main` contém apenas a versão estável aprovada.
- Toda melhoria, correção ou alteração nova entra primeiro em `dev`.
- A build `dev` é entregue para homologação e permanece identificada pelo commit.
- Depois da aprovação, atualize a versão, integre `dev` em `main`, execute a
  suíte completa e gere a nova build `main`.
- Não desenvolva diretamente em `main` nem promova uma árvore com alterações
  locais pendentes.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Smoke test visual:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:MARY_DISABLE_STARTUP_SYNC='1'
.\.venv\Scripts\vr-mary-studio.exe --smoke-test
```

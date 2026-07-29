# VR Mary Studio

Aplicativo desktop Windows para manter a base de conhecimento Mary, conversar
com Codex/Claude instalados localmente e operar o extrator de vídeos VRSoft.

## Recursos

- Sincronização completa/incremental da VRWiki via API MediaWiki.
- Sincronização autenticada do Movidesk KB com Chrome/Playwright e diagnóstico de bloqueios.
- Markdown canônico, imagens locais, OCR por+eng, hash e versionamento.
- Classificação em Fiscal, ADM_FIN_ESTOQUE, PDV, Multimodulo e Revisar.
- Catálogo determinístico de 169 produtos/equipes baseado em `produtos_filas.md`.
- SQLite FTS5, `catalogo.jsonl` e `INDEX.md`.
- Chat em streaming com Codex App Server e Claude Code, com esforço por conversa.
- Conversas persistentes, clonagem de provedor, eventos de ferramentas e aprovações.
- Extrator de vídeos Endoo integrado, sem transcrição.
- Dashboard separado para Wiki, KB e Vídeos.
- Central de Revisão com filtros combináveis, risco, paginação, histórico,
  contexto completo e ações individuais ou em lote confirmado.
- Interface PySide6 baseada na identidade VR Soft, contraste WCAG, foco visível
  e layout validado em 1366×768, 1920×1080 e escalas de 125%/150%.

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
MARY_ROOT=D:\Codex\Projetos\VR_Mary_V2
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
```

O classificador prioriza o produto mais específico encontrado no título,
categoria ou campo de produto. Produtos híbridos, como `VRAdm` e `VRCaixa`,
usam o contexto do artigo para desempate e permanecem em `Multimodulo` quando
não há evidência suficiente. A auditoria é somente leitura.
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

## Codex e Claude

- Codex usa `codex app-server`, JSON-RPC em stdio e o sandbox `workspaceWrite`.
- Claude usa `stream-json`, retoma por `session_id` e recebe permissões de escrita
  apenas para a pasta da conversa.
- Cada conversa grava arquivos em `VR_Mary_V2\TrabalhoMary\<id>`.
- O modelo e o nível de esforço ficam persistidos em cada conversa.
- Use **Clonar para outro provedor** para transferir o contexto entre agentes.

## OCR

Na tela Configurações, use **Instalar OCR portátil por+eng**. O mecanismo e os
idiomas são instalados em `VR_Mary_V2\tools\tesseract`; nada é enviado a um
serviço online.

## Empacotamento

```powershell
.\build_portable.ps1
```

O ZIP portátil é gerado em `releases`. Se Inno Setup estiver instalado, compile
`installer\VRMaryStudio.iss` para produzir o instalador Windows.

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

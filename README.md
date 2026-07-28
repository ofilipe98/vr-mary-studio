# VR Mary Studio

Aplicativo desktop Windows para manter a base de conhecimento Mary, conversar
com Codex/Claude instalados localmente e operar o extrator de vídeos VRSoft.

## Recursos

- Sincronização completa/incremental da VRWiki via API MediaWiki.
- Sincronização autenticada do Movidesk KB com Chrome/Playwright e diagnóstico de bloqueios.
- Markdown canônico, imagens locais, OCR por+eng, hash e versionamento.
- Classificação em Fiscal, ADM_FIN_ESTOQUE, PDV, Multimodulo e Revisar.
- SQLite FTS5, `catalogo.jsonl` e `INDEX.md`.
- Chat em streaming com Codex App Server e Claude Code, com esforço por conversa.
- Conversas persistentes, clonagem de provedor, eventos de ferramentas e aprovações.
- Extrator de vídeos Endoo integrado, sem transcrição.
- Dashboard separado para Wiki, KB e Vídeos.
- Interface PySide6 baseada na identidade VR Soft e contraste acessível.

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
```

O `.env` e as sessões em `.state` nunca entram no pacote ou nos logs.

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
.\.venv\Scripts\vr-mary.exe status
```

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

# Validação final — 06/09/2026

Código corrigido, sem commit/release nesta sessão.

## Suíte completa

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Resultado final: **647 passed, 45 subtests passed in 90.80s**. Código de saída 0. Inclui os 630 testes anteriores e 17 regressões adicionais da revisão.

`git diff --check`: código de saída 0, sem erros de whitespace. Git informa apenas a conversão habitual LF/CRLF em arquivos do Windows.

## Provider real

```powershell
.\.venv\Scripts\python.exe reports/plano-mensagens-intermediarias-2026-09-06/smoke_provider.py --live
```

Resultado final: **passed**. Dois turnos reais no Codex, mesma conversa temporária, respostas A e B preservadas, IDs de execução distintos, nenhum evento de erro. Cada turno produziu um assistant_started, um assistant_completed e um turn_completed. Não houve duplicação do evento de conclusão no finalizador.

Arquivo: [smoke-provider-result.json](smoke-provider-result.json).

Este cenário real verifica a resposta única e a preservação entre turnos. Intermediárias, ferramentas intercaladas, snapshots e condições adversas são cobertos pelas regressões/fixtures. Não foram executados modelos reais de Claude, OpenCode ou Antigravity.

## Interface

```powershell
.\.venv\Scripts\python.exe reports/plano-mensagens-intermediarias-2026-09-06/smoke_visual.py
```

Resultado: **passed**, zero avisos QML. Capturas inspecionadas:

- [Timeline concluída](qml-timeline.png): user, M1, atividade, M2, atividade, M3.
- [Timeline com Task Bar ativa](qml-timeline-active.png): barra existente em 2/3, sem segunda barra.

Dados determinísticos de teste, fontes locais carregadas pelo script offscreen. Nenhuma dessas imagens foi apresentada como conversa de provider real.

## Escopo da conclusão

Os defeitos encontrados foram corrigidos e os testes acima passaram. Limites de protocolo, fallback sem fronteiras observáveis e comportamento de recuperação estão descritos em [AUDITORIA_E_CORRECOES.md](AUDITORIA_E_CORRECOES.md). Nenhum banco pessoal foi usado nos testes. A baseline original permanece preservada para comparação.

# Auditoria de autenticação Antigravity — 06/09/2026

Commit auditado: `a2dc5a88cd5ff11bd8ddb365e95ad67469aca880`.
Checkout: `D:\Codex\vr-mary-studio`. Correções aplicadas no working tree, sem commit ou push. Arquivos não rastreados preexistentes foram preservados.

## Resultado

O commit original não estava pronto para aceite: seus 49 testes passavam, mas um deles exigia um falso positivo de autenticação e faltava exercitar eventos tardios e a atualização real da UI entre threads.

As correções preservam o transporte `agy --input-format stream-json --output-format stream-json`. O login volta a usar o terminal interativo nativo do CLI no Windows, com tentativa controlada e cancelamento. A conta só é confirmada mediante resposta real; encerrar o CLI não prova login.

O teste real utilizou a conta já salva no cofre do sistema: validação concluída, 7 grupos de modelos além do fallback, nova sessão nativa e resposta não vazia, sem eventos de erro. Consulte `live-results.json`. Nenhuma credencial foi lida, impressa ou removida pela auditoria.

## Defeitos encontrados e corrigidos

1. **Inicialização incompatível com o contrato comprovado do CLI.** O commit executava a interface interativa de `agy` oculta, com stdin/stdout/stderr redirecionados, e injetava um comando Python em `BROWSER` sem demonstrar suporte do runtime. `agy --help` não oferece comando de login isolado. Uma execução local com pipes e stdin encerrado não terminou em 10 segundos. Removida a interceptação presumida; o terminal fica disponível para a interação exigida pelo CLI.
2. **Autenticação falsa.** `_wait_process` marcava `authenticated` por exit code zero, inclusive após falha anterior. Agora o encerramento mantém a conta anterior e solicita validação da sessão salva. Teste original corrigido para verificar essa distinção.
3. **Tentativas ressuscitadas.** URLs tardias podiam tirar tentativas canceladas/falhas do estado terminal. Erro tardio no encaminhamento do callback também restaurava `waiting`. Ambos foram corrigidos, incluindo cancelamento durante criação do processo.
4. **Timeout incompleto.** O prazo OAuth só se aplicava a `waiting`, deixando `verifying` sem limite. Agora ambas as fases expiram, com deadline monotônico para rejeitar retorno expirado antes do timer executar.
5. **Notificação Qt perdida.** `QTimer.singleShot` era chamado a partir de threads sem event loop. Substituído por sinal Qt com conexão enfileirada para o slot da UI; o teste processa o event loop e verifica o modelo efetivamente atualizado.
6. **Status escondido ou incorreto.** O snapshot do manager sobrescrevia a mensagem de validação; falhas genéricas podiam afirmar que uma conta desconhecida estava autenticada. Corrigida a publicação do estado de validação, preservando uma conta previamente confirmada sem inventar login. A UI apresenta a mensagem de falha da conexão mesmo quando a conta permanece autenticada.
7. **Validação sem cancelamento do processo.** O subprocesso de validação agora é rastreado, encerrado no cancelamento/fechamento e tem seus pipes fechados. Cancelamento durante seu lançamento e sucesso tardio têm testes próprios.
8. **Validação de URL incompleta.** Portas malformadas escapavam como `ValueError`; caminhos de redirect arbitrários eram aceitos; `code` com `error` vazio era aceito; controles podiam ser normalizados silenciosamente. Agora os erros são controlados e essas entradas são rejeitadas.
9. **Risco de exposição no retorno manual.** Desativado o proxy herdado para envio ao listener local; redirects continuam desativados. Mensagens OAuth e erros de rede não reproduzem conteúdo sensível fornecido pelo callback.
10. **Parser podia interpretar conteúdo do protocolo como instrução OAuth.** Frames JSON são encaminhados como conteúdo, não interpretados como marcadores de login. Marcadores devem iniciar a linha. UTF-8 incompleto não contamina a linha seguinte e pontuação de parâmetros opacos não é truncada. O parser de diagnóstico não foi conectado ao transporte de conversas, que mantém seu tratamento de mensagens.
11. **Suíte Qt abortava quando executada em conjunto.** Os testes novos do commit criavam `QCoreApplication`, impedindo a criação posterior de `QApplication` exigida pelos testes visuais. Corrigido o tipo de aplicação de teste.

## Compatibilidade e limites

Referências consultadas nesta auditoria:

- [Google: instalação e autenticação do CLI](https://antigravity.google/docs/cli/install/) — login local gerenciado pelo CLI e credenciais do sistema.
- [Google: modo headless](https://antigravity.google/docs/cli/headless/) — execução e transporte integrados.
- Ajuda do executável local, obtida com `agy --help`.

O executável `agy_acp_server.exe` existe na instalação local, mas o adaptador deste projeto usa `agy`, não ACP. Esta auditoria não migrou o transporte nem presumiu que os marcadores do T3 fossem emitidos pelo CLI nativo.

Os utilitários de URL/callback permanecem testados, mas o campo de callback manual e as ações de copiar/abrir URL só aparecem quando houver uma URL validada proveniente de um adaptador compatível. O fluxo nativo atual não fornece essa URL ao harness. Portanto, **não se declara implementado um OAuth embutido com callback manual para o CLI nativo**. Sua integração exige comprovação do contrato upstream ou uma migração de escopo explícita.

Uma nova instância começa com conta `unknown`, preserva o cofre existente e permite verificar a sessão salva. A verificação explícita envia mensagem e consome cota; não foi introduzido login automático, sondagem paga no startup nem um mecanismo de status não documentado.

## Validação

Comando da suíte relevante:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_antigravity_auth.py tests/test_antigravity_auth_regressions.py tests/test_antigravity.py tests/test_qml_frontend.py -q
```

A suíte original de 49 testes foi ampliada com regressões de parser, validação, processos, cancelamento, entrega Qt e retry. Resultado final, incluindo a suíte QML: **167 passed in 16.86s**.

`qmllint` do componente terminou com exit code 0, com avisos de acesso não qualificado aos contextos QML. A renderização do aplicativo teve zero avisos QML em runtime (`qml-warnings.json`). Foram inspecionadas capturas claras/escuras e com nome longo/largura reduzida.

Reprodução das evidências, a partir do checkout:

```powershell
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe reports\antigravity-auth-audit-2026-09-06\verify.py
.venv\Scripts\python.exe reports\antigravity-auth-audit-2026-09-06\verify.py --live
```

O segundo comando verifica a conta salva e envia uma mensagem curta de teste; utiliza a cota da conta. Só registra indicadores, sem URLs OAuth, código ou tokens.

## Aceite manual ainda necessário

Não foi forçado logout nem novo consentimento Google. Para validar esse cenário quando o runtime solicitar autenticação: Configurações → Provedores → Antigravity → Entrar com Google; concluir a interação no terminal/navegador; selecionar Validar conta. Cancelar deve encerrar a tentativa sem apagar credenciais. Depois, verificar catálogo e resposta em conversa.

O fluxo com credenciais já salvas foi verificado. O fluxo de **novo consentimento Google** e um eventual **callback manual embutido** não estão cobertos por esse resultado real. Uma falha simulada de sessão/conexão foi coberta por testes e pela renderização mantendo a conta autenticada.

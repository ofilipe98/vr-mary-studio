# Auditoria de backend, frontend e integração — 2026-08-26

## Escopo e baseline

- Repositório: `vr-mary-studio`
- Branch auditada: `dev`
- Baseline remoto/local antes das correções: `12ffaad800dc1bd0f9648f74d464ae04328cecc6`
- Tag exata do baseline: `v0.3.18b1`
- Estado remoto verificado: `HEAD == origin/dev`
- Camadas cobertas: banco SQLite, busca, orquestração, providers, bridges Qt, frontend QML, configurações, processos, logs, testes e empacotamento Windows.
- Não houve commit, push, tag ou publicação nesta execução.

## Resumo executivo

A auditoria encontrou falhas reais de isolamento entre conversas, lifecycle de callbacks, persistência de credenciais, seleção de revisões, paginação, encerramento de processos e sincronização de estado entre as bridges. Todas as correções priorizadas neste ciclo foram implementadas e validadas localmente.

O resultado final é uma árvore de trabalho pronta para revisão: a suíte integral terminou com **464 testes e 154 subtestes aprovados**, o frontend QML foi renderizado e inspecionado, e um pacote PyInstaller isolado iniciou e encerrou com código `0`.

## Achados e correções implementadas

| ID | Severidade | Achado | Correção | Estado |
|---|---:|---|---|---|
| CHAT-01 | Alta | Um turno em execução bloqueava globalmente todas as conversas e o stream visual podia contaminar outra seleção. | Estado de execução passou a ser indexado por `conversation_id`; troca de conversa restaura eventos do banco e mantém o compositor das demais conversas disponível. | Corrigido |
| CHAT-02 | Alta | A finalização dos turnos era serial e callbacks podiam permanecer registrados ou ser removidos antes de uma ferramenta dinâmica tardia responder. | Finalizadores paralelos limitados a 4; callback versionado por turno e preservado por requisição de ferramenta; limpeza só remove a geração correta. | Corrigido |
| SEC-01 | Alta | Senhas ficavam em texto no `.env`, eram devolvidas para o QML e podiam aparecer em logs/saídas. | No Windows, senhas são migradas atomicamente para DPAPI por usuário; `.env` fica sem o valor; QML recebe apenas o indicador “configurada”; logs e saídas redigem credenciais configuradas. | Corrigido e migrado localmente |
| SEC-02 | Média | Valores de `.env` com `#`, aspas ou barra invertida podiam sofrer truncamento/interpretação incorreta. | Serialização compatível com `python-dotenv` e testes de round-trip com metacaracteres. | Corrigido |
| REVIEW-01 | Alta | A ação de revisão podia atingir a seleção antiga em vez do item exibido no preview. | O frontend envia uma lista explícita e congelada de IDs; sem seleção, usa apenas `currentReviewId`; filtros limpam seleção obsoleta. | Corrigido |
| LIFE-01 | Alta | Parar vídeo bloqueava a UI por até 3 segundos e processos podiam sobreviver ao encerramento. | `terminate` assíncrono com `kill` temporizado, botão para parar terminal e fechamento idempotente de Studio/Chat no `aboutToQuit`. | Corrigido |
| INT-01 | Média | Arquivar/restaurar conversa em uma bridge não atualizava necessariamente a outra. | Sinais explícitos conectam Chat e Studio para atualizar listas ativas e arquivadas. | Corrigido |
| DATA-01 | Média | A busca da tela Conhecimento era limitada a 500 itens, tornando páginas posteriores inalcançáveis. | `search_page` no banco retorna página determinística e total não truncado, com filtros parametrizados. | Corrigido |
| FRONT-01 | Média | Anexos não tinham feedback/remover no compositor; imagem em provider não-Codex podia não chegar como referência legível. | Chips horizontais removíveis, botão de anexo e referência `@"caminho"` para providers sem anexo nativo. | Corrigido |
| FRONT-02 | Média | Resultado assíncrono de arquivos/extensões podia ficar stale após troca de projeto/provider ou não atualizar ao passar de vazio para pronto. | Gerações de catálogo e validação de provider/workspace; refresh QML incondicional ao concluir sugestões. | Corrigido |
| OBS-01 | Média | Logs e buffers de terminal/vídeo cresciam sem limite. | Limites por entrada, por quantidade de linhas e por buffer; preservação da cauda com marcador de truncamento. | Corrigido |
| BUILD-01 | Média | Instalador ainda declarava `0.3.18.dev2`, a venv reportava `0.3.12` e o `.exe` não possuía recurso de versão. | Instalador, pacote Python e recurso Windows sincronizados em `0.3.18b2`; instalação editável local atualizada. | Corrigido |

## Plano de correção executado

1. Revalidar o baseline `dev`, contratos e testes existentes.
2. Isolar estado e eventos por conversa, mantendo múltiplos turnos simultâneos.
3. Corrigir lifecycle de callbacks, finalizadores e ferramentas dinâmicas tardias.
4. Corrigir alvo de revisão e sincronização entre listas ativas/arquivadas.
5. Encerrar processos/timers com segurança e limitar buffers de observabilidade.
6. Completar anexos, sugestões assíncronas e paginação de conhecimento.
7. Proteger persistência e apresentação de credenciais.
8. Sincronizar metadados de versão e validar o executável congelado.
9. Executar regressão direcionada, suíte integral, smoke visual e smoke empacotado.

Todos os itens foram concluídos.

## Evidências de validação

| Verificação | Resultado final |
|---|---|
| Testes QML/GUI/auth/versão direcionados | PASS — 57 testes |
| Persistência DPAPI e paginação >500 | PASS — 5 testes |
| Corrida de ferramenta dinâmica repetida | PASS — 5 execuções consecutivas |
| Suíte integral | PASS — 464 testes + 154 subtestes em 593,08 s |
| `py_compile` / `compileall` | PASS |
| `pip check` | PASS — nenhuma dependência quebrada |
| `git diff --check` | PASS — somente avisos esperados LF→CRLF no checkout Windows |
| Smoke do frontend fonte | PASS — código 0 |
| Capturas 1480×900 de Chat, Revisão e Configurações | PASS — inspecionadas visualmente |
| PyInstaller isolado | PASS |
| Versão do `.exe` pelo Windows | `FileVersion=0.3.18b2`, `ProductVersion=0.3.18b2` |
| Smoke do `.exe` com `Start-Process -Wait` | PASS — código 0 |
| Migração do `.env` local | PASS — senhas ausentes do texto e round-trip DPAPI válido |

O projeto já possui `constraints-windows-x64.txt`; portanto, não se confirmou o achado antigo de ausência total de constraints. Os avisos PyInstaller restantes são imports condicionais de plataforma ou extras opcionais de Pillow/yt-dlp. Nenhum impediu o smoke do executável.

## Limites e riscos residuais

- Não foram executados logins, sincronizações ou downloads reais em Wiki, Movidesk e Endoo, pois usam estado externo, credenciais e podem gerar efeitos/custos. Esses fluxos foram cobertos por contratos e fakes locais.
- Não foi consumido um turno real pago de Codex/Claude/OpenCode nesta validação.
- O cofre DPAPI é propositalmente vinculado à conta Windows atual; copiar apenas `credentials.dpapi.json` para outro usuário/máquina não transfere as senhas.
- A redação cobre os valores de credenciais configurados. Saídas arbitrárias de comandos ainda devem evitar imprimir tokens não cadastrados ou arquivos de sessão.
- O lock de sincronização continua sendo por processo/janela; duas instâncias apontadas para a mesma raiz exigem um lease SQLite cross-process em uma evolução separada.
- O pacote oficial/ZIP não foi gerado porque o script oficial exige worktree limpo. O build de validação foi isolado em `.test-tmp/package-smoke` e não substituiu artefatos oficiais.
- As alterações permanecem não commitadas para revisão do usuário; nenhum arquivo original versionado foi descartado.

## Estado de entrega

As correções locais estão implementadas e validadas. O próximo gate recomendado é revisão do diff, seguida de commit na `dev` e um E2E controlado com contas de teste antes de publicar qualquer instalador.

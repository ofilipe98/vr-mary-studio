# Auditoria técnica de produção — VR Norte Studio

Data: 2026-08-12
Branch auditada: `dev` (`ae09571`, antes das alterações locais não commitadas)
Política aplicada: nenhuma publicação, push ou promoção para `main`.

## Resumo executivo

A auditoria cobriu os 45 arquivos Python de produção e os 12 arquivos de teste. Foram analisados estaticamente 24.091 LOC de produção, 890 funções/métodos e 78 classes, além de 7.652 LOC de testes. A regressão automatizada final, o build e os smokes empacotados estão registrados em **Validação final**.

O defeito relatado ao arquivar conversa foi reproduzido: o banco recebia `archived=1`, mas o `QRunnable` podia perder a referência Python antes de entregar o callback. A lista e a conversa atual só pareciam corretas quando outra navegação forçava a recarga. A correção mantém o worker vivo, atualiza a tela imediatamente e impede que um callback atrasado limpe outra conversa.

Também foi encontrado um problema crítico de privacidade: o exportador portátil copiava `TrabalhoMary` e um SQLite completo, incluindo conversas, mensagens, eventos e documentos inativos. A exportação agora inclui somente conhecimento ativo e um scaffold vazio de trabalho, e sanitiza todo estado de chat.

Não restou nenhum defeito conhecido de severidade `CRITICAL` sem mitigação. Ainda existem riscos arquiteturais e de integração externa descritos abaixo; portanto, “build passou” não deve ser interpretado como validação online de Wiki, Movidesk, Endoo ou provedores LLM reais.

## Mapa da aplicação

| Camada | Responsabilidade | Fonte de verdade |
|---|---|---|
| Entradas | `VRMaryStudio.pyw`, CLI Mary e CLI de vídeos | argumentos e `.env` |
| UI principal | `mary/ui.py`, `mary/chat_widgets.py` | estado transitório Qt; nunca deve substituir persistência |
| Chat/orquestração | `orchestrator.py`, `multiagent.py`, `providers.py`, `chat_tools.py` | SQLite para conversa/mensagem/evento; IDs nativos apenas como vínculo |
| Conhecimento | Wiki, Movidesk, classificador, revisão, indexador e busca | SQLite para estado lógico; Markdown canônico para conteúdo portátil |
| Vídeos | auth, cursos, scanner, classificação, downloader e inventário | `metadata/*.json` + arquivos válidos em disco |
| OCR | `mary/ocr.py` | executável e `por+eng.traineddata` validados por existência/tamanho |
| Portabilidade | paths, workspace, portable project/export | caminhos relativos à raiz Mary |
| Configuração | `.env`, `MarySettings`, `Settings`, `QSettings` | `.env` para runtime; `QSettings` para preferências visuais |
| Logs/observabilidade | logging, logs da UI, `sync_runs`, `runtime_events` | arquivo/eventos persistidos conforme o fluxo |

Entidades principais: documento, versão, revisão, fonte, sincronização, conversa, mensagem, evento, artefato, ferramenta, modelo, curso, turma, vídeo, classificação, override manual, asset, configuração e workspace.

## Fluxos e dependências funcionais validados

1. Dashboard → consultas ativas → contadores → status da última sincronização → atalhos.
2. Wiki/KB → inventário → extração → classificação preservando decisão humana → arquivo canônico → banco → fila de revisão → catálogo/busca.
3. Revisão → validar transição → escrever/mover Markdown → transação SQLite → remover/atualizar pendência → reconciliar paginação e Dashboard.
4. Chat → claim atômico da conversa → mensagem do usuário → contexto VR opcional → provedor → deltas/eventos → mensagem final → estado ocioso.
5. Arquivamento → validar conversa ociosa → sincronizar provedor → persistir SQLite → atualizar lista/UI; falhas posteriores compensam a etapa anterior.
6. Lixeira → quarentena/movimento seguro → persistência → rollback de filesystem/provedor em falha.
7. Vídeos → autenticar → inventariar → classificar → baixar → validar arquivo → persistir JSON+CSV → organizar com rollback.
8. Exportação portátil → selecionar documentos ativos → copiar conteúdo permitido → sanitizar banco → auditar caminhos/segredos.

### Máquinas de estado verificadas

- Conversa: `idle/interrupted → running → idle|interrupted`; arquivada ou na lixeira não recebe mensagem; `running` não pode ser movida.
- Revisão: `pending|deferred → approved|kept|deferred`; `reopen → pending`; documento e fila mudam na mesma transação.
- Sincronização: `running → completed|partial|error`; erro por item nunca é comunicado como sucesso integral.
- Vídeo: `pending|failed|protected → downloaded` somente depois de arquivo de vídeo existente e não vazio; arquivo ausente reabre o download.

## Problemas encontrados e correções

### CRITICAL

#### CRIT-001 — Exportação portátil vazava dados privados

- **Arquivos / funções / módulo:** `mary/portable_export.py`, `mary/portable_project.py`; exportação portátil.
- **Categoria / severidade:** segurança, persistência e privacidade / `CRITICAL` / corrigido.
- **Problema e incoerência:** um pacote de conhecimento também copiava workspaces privados e o banco completo de chat, contrariando o significado de “base portátil”.
- **Reprodução / atual:** criar conversa, mensagem e arquivo privado em `TrabalhoMary`; exportar; os dados apareciam no destino.
- **Esperado / causa raiz:** apenas conhecimento ativo e arquivos explicitamente permitidos; cópia recursiva e backup integral do SQLite não tinham etapa de sanitização.
- **Risco / correção:** exposição de prompt, histórico e arquivos; `TrabalhoMary` foi excluído da cópia, o banco de destino apaga estado de usuário/chat e documentos inativos, e assets são derivados somente de documentos ativos.
- **Teste:** `test_export_portable_excludes_secrets_and_full_videos` confirma destino sanitizado e origem intacta.

### HIGH

#### CHAT-001 — Arquivar só atualizava visualmente apó mudar de aba

- **Arquivos / funções / módulo:** `mary/ui.py`; `Worker`, `_start_worker`, `_run_conversation_operation`; Chat VR.
- **Categoria / severidade:** estado assíncrono / `HIGH` / corrigido.
- **Problema e incoerência:** o banco arquivava, mas o objeto `QRunnable` podia ser coletado antes do callback; a UI ficava stale ou podia encerrar de forma instável.
- **Reprodução / atual:** arquivar e permanecer na aba; conversa permanecia visível até outra navegação.
- **Esperado / causa raiz:** remoção imediata e segura; faltava retenção Python do worker e um sinal de conclusão incondicional.
- **Risco / correção:** crash/stale state; workers ativos ficam retidos, liberados em `done`, operações repetidas são bloqueadas e callbacks verificam o ID atual.
- **Testes:** `test_archive_conversation_completes_without_navigating_away` e `test_stale_conversation_operation_does_not_clear_new_selection`.

#### CHAT-002 — Provedor, banco e pasta podiam divergir ao mover conversa

- **Arquivos / funções / módulo:** `mary/orchestrator.py`; `archive`, `unarchive`, `trash`, `restore`, `purge`; Chat VR.
- **Categoria / severidade:** atomicidade cross-system / `HIGH` / corrigido quando compensável.
- **Problema e incoerência:** falha do SQLite depois de arquivar remotamente ou mover pasta deixava estados incompatíveis; colisão de destino podia ser tratada como sucesso.
- **Reprodução / atual:** simular banco bloqueado depois de `archive_thread` ou do movimento para `.trash`.
- **Esperado / causa raiz:** rollback; sequência composta não possuía compensação.
- **Risco / correção:** conversa inacessível ou pasta associada ao registro errado; operações reversas e rollback de pasta foram adicionados e colisões agora falham explicitamente.
- **Testes:** `test_archive_compensates_provider_when_local_persistence_fails`, `test_trash_rolls_workspace_back_when_database_update_fails`, teste de rollback do purge.

#### CHAT-003 — Double click/envio concorrente criava turno fantasma ou duplicado

- **Arquivos / funções / módulo:** `mary/db.py`, `mary/orchestrator.py`, `mary/ui.py`; `begin_user_turn`, `abort_user_turn`, `send`; Chat VR.
- **Categoria / severidade:** concorrência e persistência / `HIGH` / corrigido.
- **Problema e incoerência:** a validação e a inserção da mensagem eram separadas; duas threads podiam aceitar a mesma conversa, e falha ao iniciar provedor deixava mensagem/status.
- **Reprodução / atual:** dois `send` simultâneos ou falha síncrona em `start_conversation`.
- **Esperado / causa raiz:** exatamente um claim; check-then-act não atômico.
- **Risco / correção:** mensagens duplicadas/turno travado; `UPDATE` condicional e inserção agora ocorrem numa transação, com abort pré-start e recuperação de `running` apó restart.
- **Testes:** concorrência, rollback do start e recuperação de conversa interrompida.

#### DATA-001 — Arquivo Markdown e SQLite divergiam em sincronização/revisão

- **Arquivos / funções / módulo:** `mary/content.py`, `mary/db.py`, Wiki e Movidesk; conhecimento/revisão.
- **Categoria / severidade:** atomicidade e single source of truth / `HIGH` / corrigido.
- **Problema e incoerência:** uma aprovação podia alterar somente o banco; escrita de arquivo antes do upsert podia deixar conteúdo novo com estado antigo.
- **Reprodução / atual:** aprovar `Revisar → PDV` ou provocar erro de banco apó escrita.
- **Esperado / causa raiz:** frontmatter, path, documento e revisão coerentes; faltava coordenador com snapshots/rollback.
- **Risco / correção:** busca, agentes e UI viam módulos diferentes; escrita canônica atômica, rollback do target, transação de revisão e remoção do predecessor somente depois do commit.
- **Testes:** aprovação move arquivo/frontmatter, falha de persistência restaura arquivo, path traversal rejeitado.

#### SYNC-001 — Falha parcial podia inativar documentos e afirmar sucesso

- **Arquivos / funções / módulo:** `mary/wiki.py`, `mary/movidesk.py`, `mary/db.py`, `mary/ui.py`; sincronizações.
- **Categoria / severidade:** regra de negócio e estado / `HIGH` / corrigido.
- **Problema e incoerência:** erro em item era confundido com item removido; execução com falhas terminava como `completed`.
- **Reprodução / atual:** falhar a leitura de uma página durante inventário completo.
- **Esperado / causa raiz:** `partial`, preservar ausentes quando inventário não é confiável; inativação não considerava `stats.errors`.
- **Risco / correção:** conhecimento válido desaparecia do Chat; inativação só ocorre com inventário integral e status possui `partial`.
- **Testes:** `test_sync_run_with_item_errors_is_partial` e `test_partial_wiki_sync_does_not_inactivate_unseen_documents`.

#### VIDEO-001 — `downloaded=true` não significava arquivo válido

- **Arquivos / funções / módulo:** `downloader.py`, `video_storage.py`, `mary/ui.py`; vídeos/Dashboard.
- **Categoria / severidade:** pós-condição e estado impossível / `HIGH` / corrigido.
- **Problema e incoerência:** thumbnail/arquivo vazio podia ser aceito; `--redownload` não incluía todos os estados; Dashboard confiava apenas no status.
- **Reprodução / atual:** inventário marcado como baixado com path ausente, ou `.jpg` com mesmo basename.
- **Esperado / causa raiz:** vídeo existente e não vazio; busca por glob sem validar extensão/tamanho e filtros contraditórios.
- **Risco / correção:** falso sucesso e impossibilidade de recuperar; validação comum, redownload real, estados `Arquivo ausente/Arquivo inválido/Baixado` reconciliados.
- **Testes:** recupera missing file, respeita redownload e ignora thumbnail/vídeo vazio.

#### VIDEO-002 — Scan parcial podia substituir um inventário confiável

- **Arquivos / funções / módulo:** `scanner.py`; vídeos.
- **Categoria / severidade:** erro enganoso e persistência / `HIGH` / corrigido.
- **Problema e incoerência:** exceções por seção eram logadas, mas a operação seguia para salvar.
- **Reprodução / atual:** Cursos falha e Biblioteca termina.
- **Esperado / causa raiz:** preservar inventário e reportar falha composta; erro era convertido em resultado parcial sem contrato.
- **Risco / correção:** perda/ocultação funcional; falhas são agregadas e impedem commit.
- **Teste:** `test_scan_failure_preserves_previous_inventory`.

### MEDIUM, LOW e inconsistências funcionais

| ID | Arquivo/função | Categoria / status | Problema, cenário e resultado atual | Esperado, causa, risco e correção | Teste |
|---|---|---|---|---|---|
| ERR-001 | `courses.py`, `_request_json`, `_iter_course_summaries` | erro enganoso / `MEDIUM` / corrigido | HTTP/JSON inválido virava `{}` e podia sobrescrever catálogo como vazio | separar erro de zero resultados; agora levanta `ConfigError` e preserva estado anterior | dois testes de HTTP/JSON/inventário malformado |
| CHAT-004 | `providers.py`, consumidores Codex/Claude/OpenCode | async/processo / `MEDIUM` / corrigido | stderr não drenado podia bloquear processo; exit não zero ou resposta vazia podia parecer conclusão | drenar em paralelo, emitir erro, limpar callbacks/handles e validar pipes explicitamente | 41 testes focados de provedores/chat |
| SEARCH-001 | `orchestrator.py`, `_enrich_prompt` | inconsistência funcional / `MEDIUM` / corrigido | falha do SQLite era igual a “nenhum resultado” | contexto inclui aviso de indisponibilidade e log; não inventa ausência | regressão de busca indisponível |
| STATE-001 | `db.py`, Dashboard/UI | stale state / `MEDIUM` / corrigido | contadores incluíam inativos ou não reconciliavam revisão/chat | queries ativas e refresh dependente da persistência, sem `contador -= 1` | testes de Dashboard/revisão |
| CONFIG-001 | `settings.py`, `mary/config.py`, `ui.save_settings`, GUI Tk | configuração / `MEDIUM` / corrigido | `.env` era sobrescrito não atomicamente, sem validar intervalo/root/URL; logs expunham e-mail | atualiza somente chaves conhecidas, preserva comentários, replace atômico, valida HTTP(S) e mascara credenciais | testes de preservação e rejeição sem mutação |
| FS-001 | `inventory.py`, `courses.py`, `downloader.organize_downloads` | filesystem / `MEDIUM` / corrigido | `.tmp` compartilhado e commit JSON/CSV/movimentos sem rollback | temporários únicos, backups e rollback de movimentos | testes de persistência/organização |
| SEC-001 | `mary/content.py` | segurança/recursos / `MEDIUM` / corrigido | asset malicioso podia usar esquema local e downloads eram ilimitados/não atômicos | somente HTTP(S) sem userinfo, 25 MiB, conteúdo não vazio e replace atômico | `test_download_asset_rejects_empty_and_oversized_responses` |
| OCR-001 | `mary/ocr.py` | downloads/versionamento / `MEDIUM` / corrigido | arquivo parcial podia substituir alvo; `5.9` podia ser escolhido acima de `5.10`; download ilimitado | temporário, tamanho mínimo/máximo, ordenação numérica e origem HTTPS | testes de parcial, oversized e versão 5.10 |
| REVIEW-001 | `db.query_reviews`, UI | paginação/seleção / `MEDIUM` / corrigido | aprovar/filtrar na última página podia deixar página vazia inválida | clamp do offset conforme total filtrado e refresh apó decisão | regressão de paginação |
| CLASS-001 | `content.preserve_validated_classification`, Wiki/KB | regra de negócio / `FUNCTIONAL INCONSISTENCY` / corrigido | Wiki e KB reclassificavam decisão humana de formas diferentes | regra central: mesmo hash preserva aprovação; conteúdo alterado com sugestão diferente abre revisão sem sobrescrever humano | testes de classificação validada e metadata |
| FUNC-001 | Dashboard/Sincronizações/Vídeos | semântica de UI / `FUNCTIONAL INCONSISTENCY` / corrigido | “Sincronizar tudo” não incluía vídeos; “Executar tudo” não inscrevia/organizava | labels agora dizem `Wiki + KB` e `Inventariar e baixar`; handlers compartilhados mantêm a mesma semântica | testes de UI + inspeção visual |
| LOW-001 | imports/f-strings/timer do model picker | código morto/flake / `LOW` / corrigido | seis imports/expressões mortas e popup dependente de atraso arbitrário | removidos; abertura agendada no próximo ciclo de eventos | Ruff `F/E9` e teste do seletor |

## Problemas de arquitetura e riscos ainda abertos

### ARCH-001 — `MainWindow` é um god object

- **Arquivos / funções / módulo:** `mary/ui.py`, classe `MainWindow`; UI inteira.
- **Categoria / severidade:** `ARCHITECTURE` / risco `MEDIUM` / aberto.
- **Problema e incoerência:** cerca de 7,4 mil linhas e mais de 200 métodos coordenam chat, sync, vídeos, revisão, settings e logs; consumidores dependem de estado mutável do widget.
- **Reprodução / atual:** qualquer alteração cross-module exige tocar a mesma classe e amplia combinações de estado.
- **Esperado / causa raiz / risco:** controllers por domínio e eventos tipados; crescimento incremental concentrou responsabilidades; risco de regressão e testes caros.
- **Correção proposta / teste:** extrair primeiro `ConversationController` e `SyncController`, mantendo contratos existentes; testes de integração por controller. Não executado para evitar reescrita de alto risco nesta estabilização.

### CONC-001 — lock de sincronização existe apenas por janela/processo

- **Arquivos / funções / módulo:** `mary/ui.py::_run_sync`, `db.start_sync`; sincronização.
- **Categoria / severidade:** concorrência / `HIGH` potencial / aberto.
- **Problema e incoerência:** duas instâncias apontadas para a mesma raiz podem executar Wiki/KB simultaneamente.
- **Reprodução / atual:** abrir dois Studios e sincronizar a mesma fonte; cada processo aceita a operação.
- **Esperado / causa raiz / risco:** lease cross-process com heartbeat e recuperação de crash; `sync_running` é apenas memória da janela; risco de lost update e arquivos concorrentes.
- **Correção proposta / teste:** lease SQLite com owner/heartbeat/TTL e teste multiprocesso. Não foi improvisado um lock permanente que pudesse bloquear o usuário apó crash.

### SEC-002 — instalador e modelos OCR não possuem verificação criptográfica

- **Arquivos / funções / módulo:** `mary/ocr.py::install_portable`; OCR.
- **Categoria / severidade:** supply chain / `HIGH` potencial / aberto.
- **Problema e incoerência:** HTTPS, origem, extensão e tamanho são validados, mas o `.exe` baixado é executado sem hash/Authenticode; `traineddata` também não tem hash pinado.
- **Reprodução / atual:** comprometimento da origem/CDN ainda produziria um arquivo aceito.
- **Esperado / causa raiz / risco:** manifesto de versão+SHA-256 e/ou assinatura confiável; URL “mais recente” é dinâmica; execução de binário comprometido.
- **Correção proposta / teste:** publicar manifesto próprio assinado, pinar versão/hashes e validar Authenticode antes de executar; testar hash errado e assinatura ausente.

### DEP-001 — dependências de produção não são reproduzíveis

- **Arquivos / funções / módulo:** `pyproject.toml`, `requirements.txt`; build.
- **Categoria / severidade:** dependências / `MEDIUM` / aberto.
- **Problema e incoerência:** limites apenas inferiores permitem que instalações futuras resolvam combinações diferentes.
- **Reprodução / atual:** instalar em datas/máquinas diferentes.
- **Esperado / causa raiz / risco:** lock/constraints testado por Python/Windows; projeto não mantém lock; build não determinístico.
- **Correção proposta / teste:** gerar constraints a partir de ambiente limpo, validar licenças/CVEs e reconstruir; não atualizar versões cegamente.

### PERSIST-001 — documento inativo permanece no filesystem da base original

- **Arquivos / funções / módulo:** `db.mark_missing_inactive`; conhecimento.
- **Categoria / severidade:** persistência / `MEDIUM` / aberto.
- **Problema e incoerência:** busca, contadores e exportação ignoram inativos, mas o Markdown antigo continua na pasta.
- **Reprodução / atual:** remover documento na origem, sincronizar integralmente e inspecionar a pasta manualmente.
- **Esperado / causa raiz / risco:** política explícita de quarentena/retenção; reativação hoje depende de manter histórico; agentes externos que varrem arquivos diretamente podem enxergar dado stale.
- **Correção proposta / teste:** mover para quarentena versionada e restaurar em reativação; E2E remove→sync→search→restore.

### EXT-001 — exclusão remota e SQLite não podem compartilhar transação

- **Arquivos / funções / módulo:** `orchestrator.purge`; Chat VR.
- **Categoria / severidade:** atomicidade externa / `MEDIUM` / parcialmente mitigado.
- **Problema e incoerência:** depois de `delete_thread`, uma falha local não consegue recriar a thread remota.
- **Reprodução / atual:** provedor exclui e SQLite falha.
- **Esperado / causa raiz / risco:** saga durável/outbox; API externa não oferece transação distribuída; vínculo nativo perdido, mas dados locais permanecem recuperáveis na lixeira.
- **Correção proposta / teste:** persistir intenção de purge antes da chamada e reconciliar no startup.

### DUP-001 — runners Claude/OpenCode duplicam lifecycle de subprocesso

- **Arquivos / funções / módulo:** `mary/providers.py`; provedores.
- **Categoria / severidade:** duplicação / `ARCHITECTURE` / aberto.
- **Problema e incoerência:** reserva, stdin/stdout/stderr, cancelamento e cleanup são muito semelhantes, com pequenas diferenças.
- **Risco / correção proposta:** correções podem atingir apenas um provedor; extrair runner interno somente apó testes contratuais equivalentes. Não abstraído nesta passagem para evitar mudança ampla.

### LEGACY-001 — GUI Tk antiga permanece sem entrada principal documentada

- **Arquivos / funções / módulo:** `gui.py`, `VRSoftExtractorGUI.pyw`; legado de vídeos.
- **Categoria / severidade:** código legado / `LOW` / `UNCERTAIN`.
- **Problema:** não é o entry point publicado no `pyproject`, mas ainda possui launcher e testes.
- **Correção proposta:** decidir deprecação formal apó confirmar uso em campo; não removido.

### TYPE-001 — camada Qt não fecha no mypy atual

- **Arquivos / funções / módulo:** `mary/ui.py`, `mary/chat_widgets.py`; UI.
- **Categoria / severidade:** tipos / `LOW` / aberto.
- **Problema:** stubs do PySide6 reportam enums/kwargs válidos em runtime como erro e o mypy 2.3 chegou a erro interno na análise integral.
- **Estado:** 28 arquivos de núcleo passam com `--check-untyped-defs`; UI foi validada por testes e smoke gráfico, não por type-check limpo.
- **Correção proposta:** configuração de stubs/plugin Qt ou fronteira tipada entre controllers e widgets.

## Código morto, duplicações e warnings

- `vulture --min-confidence 80`: nenhum símbolo inequivocamente morto.
- `ruff --select F,E9`: limpo depois da remoção de seis ocorrências.
- Trechos `except Exception` foram revisados. Vários são fronteiras deliberadas de batch/UI/provedor e mantêm log/estado; catches silenciosos restantes estão em probes de DOM, cleanup ou fallback opcional.
- Bandit: nenhum achado `HIGH` restante. Alertas `B608` foram auditados: nomes de tabela/coluna/order/where são allowlists/fragmentos internos; valores externos continuam parametrizados. Subprocessos usam listas, sem `shell=True`; executáveis são resolvidos pela aplicação/configuração.
- Warnings PyInstaller de POSIX e backends opcionais do `yt-dlp`: `EXPECTED/THIRD PARTY`; o executável e o despacho de CLI iniciaram com exit `0`.

## Testes de regressão adicionados/fortalecidos

- Arquivamento imediato sem troca de aba e callback stale.
- Compensação provedor↔SQLite e rollback da pasta da lixeira.
- Claim concorrente de turno, rollback de falha de start e recuperação apó crash.
- Aprovação move Markdown e atualiza frontmatter; falha restaura arquivo.
- Preserva classificação humana, reabre revisão quando necessário e atualiza metadata sem versão falsa.
- Sync parcial não inativa documentos; status `partial`.
- Export portátil sem chat, mensagens, workspace privado ou documento inativo.
- Download de vídeo valida arquivo, recupera missing e respeita redownload.
- Scan/organização/inventário preservam estado em falha.
- Curso distingue vazio real de HTTP/JSON inválido.
- `.env` atômico preserva configuração externa e rejeita valores inválidos.
- Assets/OCR rejeitam vazio, oversized, esquema inseguro e versão ordenada incorretamente.

## Validação final

| Verificação | Resultado |
|---|---|
| `pytest tests -q -p no:cacheprovider` | PASS — 218 testes + 29 subtestes em 49,65 s |
| `compileall` | PASS |
| `pip check` | PASS — nenhuma dependência quebrada |
| Ruff `F,E9` (produção) | PASS |
| Mypy núcleo, 28 arquivos, `--check-untyped-defs` | PASS |
| Mypy UI Qt | NOT CLEAN — stubs PySide6/erro interno; ver `TYPE-001` |
| Bandit severidade alta | PASS — zero achado alto |
| Vulture confiança ≥80% | PASS — zero candidato |
| `git diff --check` | PASS; apenas avisos esperados LF→CRLF do checkout Windows |
| Smoke gráfico fonte, raiz limpa, 1480×900 | PASS; captura inspecionada sem colisão/corte |
| PyInstaller isolado | PASS |
| Smoke `.exe` com `Start-Process -Wait -PassThru` | PASS, exit `0` |
| Despacho empacotado `--video-cli --help` | PASS, exit `0` |

## Não analisado/testado ao vivo

- `NOT TESTED` — login/sincronização Wiki e Movidesk reais: requer credenciais, MFA/CAPTCHA e estado externo.
- `NOT TESTED` — inventário, inscrição e download Endoo reais: pode causar inscrição/download e consumir banda/disco.
- `NOT TESTED` — turno completo cobrado nos provedores Codex/Claude/OpenCode: testes usam contratos/fakes e smoke de processo, sem consumir serviço externo.
- `NOT TESTED` — instalação real do Tesseract: executa binário externo; ver `SEC-002`.
- `NOT TESTED` — recuperação real de disco cheio, queda de energia e permissão negada em cada volume; rollback foi exercitado por falhas simuladas.
- `NOT TESTED` — duas instâncias sincronizando a mesma raiz; ver `CONC-001`.
- `NOT TESTED` — clone limpo/instalação do zero, pois o worktree recebido já continha alterações locais extensas. O build foi isolado em `.test-tmp`.
- `NOT TESTED` — pacote ZIP/publicação; deliberadamente não gerado/publicado sem autorização.

## Checklist de conclusão

```text
Arquitetura ............... DONE (ARCH-001 documentado)
Código morto .............. DONE
Duplicações ............... DONE (DUP-001 documentado)
Tipos ..................... DONE no núcleo; UI NOT CLEAN — TYPE-001
Estados ................... DONE
Persistência .............. DONE (PERSIST-001 e EXT-001 documentados)
Cache ..................... DONE
Concorrência .............. DONE em processo; multi-instância NOT TESTED — CONC-001
Async ..................... DONE
Erros ..................... DONE
Retries ................... DONE
Timeouts .................. DONE
Configurações ............. DONE
Filesystem ................ DONE; falhas físicas NOT TESTED
Dashboard ................. DONE
Chat VR ................... DONE; provedor real NOT TESTED
Conhecimento .............. DONE; fontes reais NOT TESTED
Sincronizações ............ DONE; fontes reais/multi-instância NOT TESTED
Revisão ................... DONE
Vídeos .................... DONE; portal/download real NOT TESTED
Logs ...................... DONE
Configurações UI .......... DONE
Integração entre módulos .. DONE por testes locais; serviços externos NOT TESTED
Testes unitários .......... DONE
Testes integração ......... DONE localmente
Regression ................ DONE apó execução final registrada na entrega
```

## Critério de liberação recomendado

Manter em `dev` até um operador validar, com credenciais de teste, pelo menos: Wiki real, KB real, uma conversa real por provedor usado e um download de vídeo pequeno. Antes de distribuição ampla, tratar `SEC-002` e criar constraints reproduzíveis (`DEP-001`). Para uso simultâneo por mais de um processo sobre a mesma raiz, `CONC-001` é bloqueador.

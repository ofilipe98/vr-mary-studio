# Perfil de segurança do VRMonitor

O VRMonitor usa um fluxo separado das conversas comuns do Studio. O perfil interno
`monitor_restricted` não aparece no seletor da interface, não pode ser carregado do
SQLite e exige `ConversationOptions(monitor_mode=True)`. Perfis vazios ou desconhecidos
são normalizados para `supervised`; a resolução direta de um preset desconhecido falha.

## Estado atual

Codex, Claude, OpenCode e Antigravity recusam `monitor_mode` antes de iniciar ou
retomar uma sessão. O módulo `monitor_ephemeral` acrescenta o limite local da H02:
ele executa um turno por vez, somente em memória, sem importar banco, orchestrator,
logging, adapters genéricos ou qualquer API de filesystem. Não existem superfícies de
histórico, resume ou exportação.

O conteúdo de entrada fica em buffer mutável e é sobrescrito ao terminar, inclusive
em erro ou cancelamento. O resultado transitório pertence ao transporte e precisa ser
fechado depois da entrega. Eventos contêm somente `runtime_id` e `correlation_id`
aleatórios, contagens de bytes, estado e código fechado de erro. Uma nova instância
sempre recebe outro runtime e não recupera o turno anterior.

`runtime_id` é metadado local e não representa usuário ou sessão autenticada. O
request entregue ao provider não possui credencial, user_id, client_id, sessão Harness
ou target. No VRMonitor, o contrato central iniciado no commit `bd27e88` vincula token,
cliente e sessão em uma credencial privada, recusa divergência antes de AuthZ/Agent e
continua derivando usuário/target do cadastro. O futuro transporte deve criar esse
vínculo fora do prompt; ele ainda não existe neste checkout.

Esse limite ainda não habilita o Monitor. O contrato declarado por um provider
(`persists_content=False` e `supports_resume=False`) é uma barreira local, não uma
prova de retenção. O adapter concreto, processo isolado, destino e retenção do
provider continuam bloqueados pelos gates seguintes. Adicionar o perfil a um provider
genérico ou ao seletor da interface viola este contrato.

## Processo Monitor

`monitor_isolation` define o gate local da H04 sem reutilizar os launchers genéricos e
sem importar `subprocess`. Um manifesto aceito exige executável absoluto dentro da raiz
dedicada, SHA-256 exato, argumentos fixos, diretórios de trabalho/perfil/temporário
confinados, raízes do servidor explicitamente proibidas e environment construído por
allowlist sem copiar `PATH`, tokens, senhas ou outras variáveis do processo pai.

O broker precisa declarar processo externo, identidade de sistema dedicada, ACL de
filesystem e allowlist de executável efetivamente aplicadas. A atestação resultante é
opaca e seu digest deve coincidir com o provider antes de criar a sessão efêmera.
Manifesto aprovado para um executável não pode ser reutilizado com outro provider.

Essa validação prepara e bloqueia o contrato; não implementa o broker privilegiado nem
prova uma ACL/conta do Windows. Os providers atuais continuam recusados. H04 somente
poderá ser encerrada após validar a conta de serviço, ACLs e isolamento reais no ambiente
de implantação.

## Provider e egress do piloto

`monitor_egress` reserva o piloto ao provider `codex`, mas não aprova o adapter Codex
genérico. O manifesto exige autenticação por chave de API, versão e modelo exatos (sem
`latest`), conta/projeto representado apenas por SHA-256, um único destino
`https://api.openai.com/v1/responses`, `store=false`, Zero Data Retention e telemetria
desativada. Busca Web, plugins, sync e fan-out entre providers precisam permanecer
desligados.

A atestação só é emitida quando a revisão da conta e uma captura isolada de egress
declaram o mesmo destino e o mesmo inventário de campos, com allowlist de rede aplicada,
egress direto negado e validade máxima de 90 dias. A sessão efêmera compara provider,
modelo e digest do manifesto antes de entregar o payload. Evidência ausente, expirada ou
divergente fecha o caminho.

Em 2026-09-19, o inventário desta máquina encontrou apenas Codex CLI 0.155.1; os outros
três CLIs não estavam instalados. Isso não é evidência de aprovação. O adapter existente
usa `app-server`, herda o environment e suporta retomada, portanto continua proibido no
Monitor. Nenhum manifesto operacional, identificador de projeto, captura de tráfego ou
declaração ZDR real foi incluído no repositório.

Pela documentação oficial, uso com chave de API segue os controles da organização da
API; o padrão pode manter logs de abuso por até 30 dias e ZDR depende de aprovação da
OpenAI. A H05 só poderá ser encerrada após confirmar a política na conta/projeto dedicado,
desativar a telemetria, executar a captura no broker isolado e revisar o inventário real.
Referências consultadas em 2026-09-19:
[controles de dados](https://developers.openai.com/api/docs/guides/your-data) e
[autenticação do Codex](https://developers.openai.com/es-419/docs/auth).

## Limites do turno

O contrato efêmero v2 não aceita mais uma resposta monolítica retornada pelo provider.
O provider precisa escrever em `MonitorOutputSink`, que limita cada chunk a 64 KiB e a
captura total a 1 MiB antes de copiar bytes. Entrada permanece limitada a 64 KiB. Esses
valores são tetos: uma integração pode reduzi-los, mas não aumentá-los por configuração.

Cada turno tem deadline de até 300 s e graça de término de até 5 s. Os padrões do piloto
são 30 s e 1 s. Timeout, cancelamento explícito ou fechamento da sessão marcam o token de
cancelamento e chamam `terminate_turn(correlation_id)`. Conteúdo capturado é sobrescrito;
erros do provider e stderr não atravessam a fronteira. A sessão permite um turno ativo e
recusa concorrência imediatamente com `monitor_busy`, sem fila.

Essa barreira evita captura ilimitada dentro do processo Studio, mas Python não consegue
matar com segurança uma thread que ignora o contrato. O provider concreto precisa ser o
processo externo da H04 e o broker deve provar término da árvore, limite de memória e
fechamento dos pipes. H06 permanece aberta até esses casos passarem no broker real.

## Cadeia executada e atualização

`monitor_supply_chain` aceita somente um bundle offline revisado. O manifesto fixa a
revisão Git do Studio, o artefato Codex, versão, SHA-256, origem versionada no repositório
oficial `openai/codex`, hash do certificado assinante, lock de dependências, configuração
e os digests dos manifestos H04/H05. A sessão exige o digest dessa cadeia, portanto trocar
binário, versão, processo, destino ou configuração invalida a aprovação anterior.

A evidência exige hashes verificados antes do launch, assinaturas válidas, distribuições
de dependências com hash, revisão de fonte/vulnerabilidades, atualização automática
desativada, rede de instalador negada e nova aprovação após qualquer mudança. O módulo
não importa launcher, installer, adapter, subprocesso nem cliente de rede.

Inventário local em 2026-09-19: Codex CLI 0.155.1, executável com SHA-256
`eba0f32c976667cb9298efafd98513e823eeda7b576a03ec658bb8be8d336316` e assinatura
Authenticode válida de `OpenAI OpCo, LLC`. Isso não forma um bundle aprovado: o binário
está fora da raiz isolada e `constraints-windows-x64.txt` fixa versões, mas não hashes das
distribuições. Nenhum manifesto operacional foi incluído. A documentação oficial aponta
`openai/codex` como repositório do CLI e App Server; atualização integrada não é permitida
em uma sessão Monitor.

O padrão de conversas novas também passa a ser `supervised`. Conversas existentes que
tenham um perfil válido preservam a escolha; trocar de provider volta para
`supervised`. `full_access` continua disponível como escolha explícita para fluxos
gerais do Studio e não é permitido como substituto do perfil Monitor.

## Próximos gates

Antes de habilitar uma sessão Monitor ainda são necessários:

1. conectar o transporte ao limite efêmero sem introduzir persistência;
2. conectar a credencial vinculada a usuário/sessão/cliente fora do prompt e validar
   adulteração/revogação de ponta a ponta;
3. implementar o broker externo e validar conta de serviço/ACLs reais contra o
   manifesto de processo aprovado;
4. materializar e validar em ambiente a conta, ZDR, telemetria e captura exigidos pelo
   manifesto de egress;
5. aplicar e validar no broker real os limites de processo, memória e pipes;
6. produzir o bundle offline com hashes de distribuições e validar a cadeia no broker;
7. executar a matriz dinâmica completa com canários antes de qualquer aprovação.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_restricted_profile.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_ephemeral.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_isolation.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_egress.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_supply_chain.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_antigravity_acp.py -q -x
```

Os testes efêmeros usam canários em sucesso, erro, cancelamento, reinício e encerramento
abrupto do processo e verificam que a superfície do provider não carrega autoridade
central. Eles provam o limite local isolado; não aprovam o adapter, um provider, o
tratamento de dados de clientes ou a integração do VRMonitor.

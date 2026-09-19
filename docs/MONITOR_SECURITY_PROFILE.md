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

O padrão de conversas novas também passa a ser `supervised`. Conversas existentes que
tenham um perfil válido preservam a escolha; trocar de provider volta para
`supervised`. `full_access` continua disponível como escolha explícita para fluxos
gerais do Studio e não é permitido como substituto do perfil Monitor.

## Próximos gates

Antes de habilitar uma sessão Monitor ainda são necessários:

1. conectar o transporte ao limite efêmero sem introduzir persistência;
2. conectar a credencial vinculada a usuário/sessão/cliente fora do prompt e validar
   adulteração/revogação de ponta a ponta;
3. processo isolado, ambiente mínimo, filesystem e executáveis permitidos;
4. provider único, destinos de egress fixos e retenção/telemetria aprovadas;
5. limites de streaming, subprocesso, tempo, cancelamento e concorrência;
6. versões, hashes e atualização controlada da cadeia executada;
7. matriz dinâmica completa com canários antes de qualquer aprovação.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_restricted_profile.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_ephemeral.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_antigravity_acp.py -q -x
```

Os testes efêmeros usam canários em sucesso, erro, cancelamento, reinício e encerramento
abrupto do processo e verificam que a superfície do provider não carrega autoridade
central. Eles provam o limite local isolado; não aprovam o adapter, um provider, o
tratamento de dados de clientes ou a integração do VRMonitor.

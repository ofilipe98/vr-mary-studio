# Perfil de segurança do VRMonitor

O VRMonitor usa um fluxo separado das conversas comuns do Studio. O perfil interno
`monitor_restricted` não aparece no seletor da interface, não pode ser carregado do
SQLite e exige `ConversationOptions(monitor_mode=True)`. Perfis vazios ou desconhecidos
são normalizados para `supervised`; a resolução direta de um preset desconhecido falha.

## Estado atual

Esta revisão prepara a primeira barreira do gate de integração. Codex, Claude,
OpenCode e Antigravity recusam `monitor_mode` antes de iniciar ou retomar uma sessão.
O perfil só poderá executar quando existir um adapter Monitor dedicado com ferramentas,
destino e identidade central fixados. Adicionar o perfil a um provider genérico ou ao
seletor da interface viola este contrato.

O padrão de conversas novas também passa a ser `supervised`. Conversas existentes que
tenham um perfil válido preservam a escolha; trocar de provider volta para
`supervised`. `full_access` continua disponível como escolha explícita para fluxos
gerais do Studio e não é permitido como substituto do perfil Monitor.

## Próximos gates

Antes de habilitar uma sessão Monitor ainda são necessários:

1. caminho efêmero sem mensagens, eventos, journal, resume ou exportação;
2. identidade de usuário, sessão e cliente obtida fora do prompt e revalidada no central;
3. processo isolado, ambiente mínimo, filesystem e executáveis permitidos;
4. provider único, destinos de egress fixos e retenção/telemetria aprovadas;
5. limites de entrada, saída, subprocesso, cancelamento e concorrência;
6. versões, hashes e atualização controlada da cadeia executada;
7. testes dinâmicos com canários antes de qualquer aprovação.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_restricted_profile.py -q -x
.\.venv\Scripts\python.exe -m pytest tests/test_antigravity_acp.py -q -x
```

Esses testes provam somente a barreira de perfil. Eles não aprovam o adapter, um
provider, o tratamento de dados de clientes ou a integração do VRMonitor.

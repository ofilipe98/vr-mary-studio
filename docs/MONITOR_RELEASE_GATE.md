# Gate dinâmico do VRMonitor

## Decisão atual

**NEGADO.** Não existe aprovação para habilitar provider, transporte ou dados de
clientes. O broker Windows e sua contenção possuem evidência operacional, mas isso não
substitui conta API, ZDR, captura de rede, execução efêmera e aprovadores reais.

`monitor_release_gate` só emite uma aprovação opaca, vinculada e com validade máxima de
30 dias quando recebe as atestações H04, H05 e H07 do mesmo bundle e uma matriz completa.
A futura Etapa 17 deverá exigir essa aprovação no startup. Neste checkout não existe
adapter ou startup Monitor que possa consumi-la.

## Matriz obrigatória

| Grupo | Casos obrigatórios | Estado operacional |
| --- | --- | --- |
| Processo | broker real, identidade dedicada, negação aos diretórios centrais | Validado no host Windows em 2026-09-19 |
| Provider | conta dedicada, ZDR, telemetria desativada, provider real | Ausente |
| Egress | destinos e campos capturados, proxy/allowlist aplicados | Ausente |
| Efemeridade | canários após sucesso, erro, cancelamento, crash e restart | Apenas sintético |
| Escopo | dois usuários e dois CNPJs, adulteração e revogação antes da entrega | Apenas serviços centrais/sintético |
| Limites | entrada grande, saída contínua, cancelamento ignorado, desconexão e concorrência | Job/memória/processo reais; streaming/provider sintéticos |
| Cadeia | bundle offline, hashes de distribuições, assinatura, drift de binário/configuração | Broker/Codex fixados; aprovação do bundle ausente |
| Pós-execução | varredura de disco/profile/temp/logs e regressão/vulnerabilidades | Ausente |
| Aprovação | registros assinados de Segurança, Data Owner e Operações | Ausente |

O gate também fixa revisão Git, digests dos relatórios/canários/captura e os tetos
efetivamente observados. Qualquer `false`, hash inválido, revisão divergente, evidência
vencida ou atestação de outro bundle resulta em erro fechado. A aprovação não contém
payload, conta, caminho, captura ou dado de cliente.

## Evidência local

Os testes usam executável, provider, conta, captura, relatórios e aprovações sintéticos.
Eles verificam a decisão positiva somente para provar que todos os campos participam do
contrato; em seguida negam individualmente cada uma das 29 declarações operacionais,
revisão, validade, hashes, limites, versão do contrato e mistura de bundles. O módulo não
importa rede, subprocesso, installer ou adapters genéricos.

Os commits VRMonitor `6192d7a` e `95f88fe` instalaram o serviço `VRMonitorBroker` sob
SID próprio e protegeram a cópia das evidências contra escrita pelo serviço. O
self-test real comprovou DACL, environment mínimo, término do Job Object, memória e um
processo ativo sem iniciar o provider. O relatório tem SHA-256
`d3cb6631877807aaa2f49c652ff5b65ad1b77f1100f6c245689a2d5bfa6b14a2`; o manifesto
local do bundle tem SHA-256
`a2bda51a735f0be3dc0009afac7d2d1b077960316d4839e227cbd2c2785ab5cc`; o índice
imutável tem SHA-256
`19a96ef9e7b2be17e8420f111d40d621005e36f956d0dd3ae496435c1df45078` e decisão de
egress `blocked_pending_zdr`.

Esses arquivos ainda não formam uma aprovação do gate: não há atestação H05 real,
captura, canários de uma execução de provider, varredura pós-execução nem assinaturas dos
três responsáveis. A revisão final deverá ser fixada depois da integração e da execução
da matriz completa.

## Verificação local

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_release_gate.py -q -x
```

# Gate dinâmico do VRMonitor

## Decisão atual

**NEGADO.** Não existe aprovação para habilitar provider, transporte ou dados de
clientes. Os testes locais exercitam a lógica do gate com evidência sintética; eles não
substituem broker, conta, rede, provider e aprovadores reais.

`monitor_release_gate` só emite uma aprovação opaca, vinculada e com validade máxima de
30 dias quando recebe as atestações H04, H05 e H07 do mesmo bundle e uma matriz completa.
A futura Etapa 17 deverá exigir essa aprovação no startup. Neste checkout não existe
adapter ou startup Monitor que possa consumi-la.

## Matriz obrigatória

| Grupo | Casos obrigatórios | Estado operacional |
| --- | --- | --- |
| Processo | broker real, identidade dedicada, negação aos diretórios centrais | Ausente |
| Provider | conta dedicada, ZDR, telemetria desativada, provider real | Ausente |
| Egress | destinos e campos capturados, proxy/allowlist aplicados | Ausente |
| Efemeridade | canários após sucesso, erro, cancelamento, crash e restart | Apenas sintético |
| Escopo | dois usuários e dois CNPJs, adulteração e revogação antes da entrega | Apenas serviços centrais/sintético |
| Limites | entrada grande, saída contínua, cancelamento ignorado, desconexão e concorrência | Apenas provider sintético |
| Cadeia | bundle offline, hashes de distribuições, assinatura, drift de binário/configuração | Manifesto sintético; bundle ausente |
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

Nenhuma evidência operacional foi criada ou simulada como real. A revisão H01–H07
publicada antes deste gate termina em `45e1abd`; a revisão final a testar deverá ser
fixada somente depois da integração da branch e da construção do bundle offline.

## Verificação local

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest tests/test_monitor_release_gate.py -q -x
```

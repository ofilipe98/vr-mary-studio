# Gate 9 — Benchmark pareado e auditoria do VR Ultra

## Objetivo

Medir, com chamados resolvidos, quando o Agente de Código opt-in melhora a
resposta do VR Ultra e qual é o custo adicional. A comparação precisa usar a
mesma release, modelo e esforço, conservar a trilha de workers e separar métrica
automática de julgamento humano.

## Gap encontrado e corrigido

Os eventos de início, conclusão e falha dos pesquisadores modulares eram
entregues à interface, mas estavam marcados como transitórios. Assim, uma
execução podia mostrar agentes durante o streaming e não deixar prova deles no
banco. Os eventos agora são persistidos. O consumo informado pelos turnos
efêmeros também era ignorado; agora cada worker gera um evento `agent_usage`
com modelo e contagem de tokens.

Continuam transitórios apenas deltas de streaming e eventos técnicos que não
compõem a auditoria. A consulta de eventos da orquestração passou a incluir
`agent_usage`.

## Desenho do benchmark

- Cada suíte fixa `release_id`, classificação dos dados e casos conhecidos.
- Somente `anonymized` e `synthetic` são aceitos; dados brutos de clientes são
  recusados.
- Cada caso roda em duas conversas VR Ultra independentes: toggle desligado e
  ligado.
- A ordem alterna entre os pares (`off/on`, depois `on/off`) para reduzir viés
  de cache, aquecimento e ordem.
- A execução exige `--approve-model-usage`, pois consome duas rodadas por caso e
  envia o texto ao provedor escolhido.
- A release precisa estar pronta e fresca, e seu índice precisa conter fontes.
- O relatório registra a cobertura real (`jar_count` e lista de JARs), evitando
  apresentar uma indexação parcial como cobertura dos 46 JARs.
- O placar automático mede termos esperados, símbolos conhecidos, evidência de
  código, tokens e latência. Ele não substitui revisão humana de correção,
  utilidade e preferência.

## Saída auditável

Cada variante conserva:

- conversa e resposta completas;
- tempo decorrido e tokens do agente principal e dos workers;
- contagem de eventos e ciclo de vida dos workers;
- indicação de disparo/status do Agente de Código;
- citações de código;
- score objetivo e campos vazios para revisão humana.

O relatório JSON é escrito atomicamente em
`indice/evaluations/code-analysis/`. A síntese agregada mostra ganho objetivo
médio, casos em que surgiu evidência de código e decisões preliminares. Uma
decisão `supports_opt_in` significa ganho nos critérios previamente declarados,
não autorização para tornar o worker obrigatório.

## Critérios de aceitação

1. Uma execução Ultra deixa `agent_started`, `agent_completed` ou
   `agent_failed` persistidos por worker.
2. Workers que informam uso deixam `agent_usage` persistido e entram no custo
   total sem duplicar o consumo do agente principal.
3. Nenhum benchmark roda sem aprovação explícita de custo e envio.
4. Casos brutos são recusados antes de abrir conversas com o provedor.
5. Release ausente/desatualizada ou índice vazio bloqueia a execução.
6. O relatório permite reconstruir ordem, agentes, evidências, custo e resultado
   de cada lado do par.
7. A conclusão de produto depende da revisão humana e de uma amostra real
   representativa.

## Estado deste gate

A infraestrutura e os critérios automáticos foram validados com casos
sintéticos. Nenhum chamado real foi executado neste gate porque ainda não há
uma suíte anonimizada fornecida para o projeto. O índice real atualmente medido
cobre integralmente apenas `VRPdv.jar`; os demais 45 JARs continuam fora dessa
cobertura e aparecerão explicitamente como ausentes no relatório.

## Próximo experimento

Montar uma suíte pequena de chamados encerrados em que a causa confirmada foi
código, declarar antes da execução os termos/símbolos esperados e as hipóteses
descartadas, executar o par e revisar às cegas as respostas. A recomendação do
default deve considerar ganho de acurácia e diagnóstico, custo, latência, taxa
de falha e diferenças entre suporte, implantação e treinamento.

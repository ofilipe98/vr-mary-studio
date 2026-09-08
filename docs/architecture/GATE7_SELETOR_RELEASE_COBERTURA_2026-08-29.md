# Gate 7 — Seletor de release e ampliação da cobertura real

Data: 2026-08-29

## Decisão

A análise de código do VR Ultra só pode ser ativada quando existe uma release
ERP inventariada. A release é escolhida em um seletor alimentado pelo catálogo
local, nunca por texto livre. Isso mantém a execução presa a um manifesto
verificável e impede que um nome digitado seja tratado como uma base existente.

O catálogo continua limitado a até três releases simultâneas. Releases com
manifesto vazio ou falho não são oferecidas. O seletor mostra quantidade de
JARs e frescor; uma base alterada depois da importação aparece como
`desatualizado` antes da execução.

## Fluxo implementado

1. A tela VR Ultra solicita ao backend as releases inventariadas.
2. O backend carrega os estados pelo `ErpReleaseCatalog` e fornece somente IDs
   válidos ao seletor.
3. A seleção é persistida por usuário. Uma seleção removida é substituída pela
   primeira release disponível; sem catálogo, ela é limpa.
4. O toggle do Agente de Código fica indisponível sem release e não pode ser
   habilitado por chamada direta ao backend.
5. O orquestrador recebe a análise de código como ativa somente quando há toggle
   ligado e release válida.
6. A atualização manual do inventário recalcula opções, frescor e preferência
   sem reiniciar o Studio.

## Correção encontrada com dados reais

A ampliação dos lotes revelou classes Java legais cujo nome começa com `$`,
como `com.google.gson.internal.$Gson$Types`. O agrupamento anterior interpretava
o primeiro `$` como separador de classe interna e esperava um caminho `.java`
inválido.

O agrupamento agora preserva nomes iniciados por `$` e escolhe como classe
externa o maior prefixo que realmente existe no lote. Na retomada, todos os
membros do lote participam dessa decisão, inclusive fontes já reaproveitadas.
O lote afetado foi reexecutado e passou de parcial para concluído na segunda
tentativa, com 354 fontes esperadas e 354 encontradas.

## Validação na release real

Escopo atual: release `current`, apenas `VRPdv.jar`. A seleção completa dos 46
JARs continua sendo uma etapa separada, pois o usuário escolhe manualmente qual
release e quais artefatos entram em cada plano.

| Métrica | Resultado |
|---|---:|
| Plano | `plan-e9d10176f4514cfe8f30e153` |
| Lotes concluídos | 16 de 95 |
| Lotes pendentes | 79 |
| Conteúdos de classe concluídos | 46.994 |
| Fontes Java indexadas | 4.895 |
| Símbolos AST | 88.399 |
| Relações sintáticas | 225.410 |
| Chamadas | 169.839 |
| Construções | 17.907 |
| Extensões | 3.566 |
| Implementações | 2.282 |
| Imports | 31.816 |

Uma fonte IBM JPOS possui 55 nós de erro sintático, mas o parser tolerante ainda
extraiu a interface e seis símbolos úteis. Ela permanece sinalizada para
auditoria em vez de ser descartada ou apresentada como parse perfeito.

## Critérios automatizados

- a lista contém apenas releases inventariadas e respeita a ordem do catálogo;
- uma release desconhecida não pode ser persistida pelo seletor;
- mudança posterior no JAR aparece como release desatualizada;
- sem inventário, a análise de código não pode ser habilitada;
- nomes Java iniciados por `$` preservam a fonte correta;
- classes internas convencionais continuam agrupadas pela classe externa;
- a preferência válida sobrevive à reabertura da interface.

## Próximos passos

- o plano v1 desta página foi substituído pelo plano multi-release v2; a
  cobertura completa de `VRPdv.jar` está documentada no Gate 8;
- selecionar explicitamente e planejar os demais JARs da release quando a
  cobertura dos 46 artefatos for autorizada para a rodada;
- validar chamados reais com o Agente de Código ligado e desligado;
- medir custo, latência, precisão e ganho por modo sênior;
- adicionar busca semântica aos sinais AST e ao grafo sintático.

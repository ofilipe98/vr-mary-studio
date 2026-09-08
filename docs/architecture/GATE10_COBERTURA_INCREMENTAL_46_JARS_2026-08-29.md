# Gate 10 — Cobertura incremental dos 46 JARs

## Diagnóstico

A release `current` está pronta e fresca com 46 JARs, mas o índice do Gate 9
cobria somente `VRPdv.jar`. Os 45 JARs restantes somavam 1.315.222 ocorrências
de classe no manifesto. O banco de processamento já ocupava aproximadamente
843 MB e todos os artefatos gerados, 1,55 GB.

Planejar e executar os 45 de uma vez ocultaria progresso, ampliaria o domínio de
falha e dificultaria interromper com segurança. A projeção conservadora era de
33.099.983.569 bytes para um orçamento de 33.572.848.010 bytes: cabe, mas acima
de 98% do limite. Por isso, o estado correto é `tight`, não `ready`.

Também havia um plano antigo de schema 1 ainda marcado como pendente. Ele não
pode ser retomado pelo executor atual e agora permanece visível apenas para
auditoria, sem bloquear planos do schema 2.

## Implementação

O `ErpCodeCoverage` adiciona um ciclo retomável e consciente de capacidade:

1. valida release pronta e fresca;
2. separa JAR inventariado, origem de fonte e JAR coberto por plano concluído;
3. ignora planos incompatíveis ao escolher um plano ativo;
4. retoma um plano atual antes de abrir outro;
5. por padrão escolhe o menor JAR pendente, ou aceita seleção manual;
6. reserva conservadoramente 10× o tamanho comprimido antes de planejar;
7. executa lotes serialmente sob o lock global existente;
8. indexa apenas lotes concluídos e preserva falhas/parciais para decisão;
9. recalcula cobertura, disco e orçamento ao final.

O avanço exige `--approve-processing` antes de carregar `.env`, inicializar o
workspace ou executar Java. O status é somente leitura. Nenhuma rotina remove
JARs, planos antigos ou saídas regeneráveis automaticamente.

## Correção transversal de SQLite

Durante a validação da interface, os bancos temporários permaneceram bloqueados
no Windows. A causa era o uso do contexto nativo de `sqlite3.Connection`, que
faz commit/rollback, mas não fecha o handle. O `DecompilationBatchStore` agora
expõe um context manager real: rollback em exceção e fechamento garantido no
`finally`. Isso é necessário para centenas de ciclos de planejamento/indexação.

A suíte QML também revelou carregadores de modelos e extensões emitindo sinais
Qt diretamente de threads daemon. Quando uma bridge anterior já havia sido
destruída, isso podia causar uma violação de acesso nativa. Esses workers agora
publicam resultados em filas e timers da thread da interface fazem a aplicação,
seguindo o mesmo isolamento usado pela varredura assíncrona de arquivos.

## Interface

O seletor da aba VR Ultra deixou de mostrar apenas `46 JARs`, número que descreve
o inventário e podia sugerir cobertura inexistente. O rótulo agora informa a
razão efetiva, como `3/46 JARs indexados`, junto ao frescor da release.

## Validação real incremental

- Estado inicial: `1/46`, somente `VRPdv.jar`.
- `VRChat.jar`: 1 lote, 22 conteúdos, 10/10 fontes, Vineflower, sem erro.
- `VRMicroTerminal.jar`: 1 lote, 26 conteúdos, 7/7 fontes, Vineflower, sem erro.
- Estado após os incrementos: `3/46`, 43 pendentes.
- O classpath continua `partial`; nenhuma duplicata é resolvida por confiança.

Esses dois JARs validam criação, execução, indexação e retomada entre planos,
mas não validam ainda a capacidade final dos JARs grandes.

## Critérios para continuar

- avançar um JAR por plano enquanto a capacidade continuar diferente de
  `insufficient`;
- interromper em qualquer lote `failed` ou `partial` e revisar antes de retry;
- conferir a razão de crescimento real depois dos primeiros JARs médios;
- não afirmar cobertura integral antes de `46/46`;
- manter a ordem do classpath como desconhecida até obter informação oficial ou
  traces de execução.

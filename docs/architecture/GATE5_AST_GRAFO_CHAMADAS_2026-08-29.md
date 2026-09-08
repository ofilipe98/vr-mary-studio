# Gate 5 — AST tolerante e grafo de chamadas

Data: 2026-08-29

## Resultado

O índice de código usa Tree-sitter Java como parser primário e preserva o
extrator estrutural anterior como fallback. O parser trabalha sobre as fontes
já decompiladas: não abre nem decompila novamente os 46 JARs durante uma busca.

A dependência foi fixada em `tree-sitter 0.25.2` e
`tree-sitter-java 0.23.5`. Os módulos nativos também foram incluídos
explicitamente na coleta do PyInstaller.

## Dados extraídos

- pacote, tipos, classes aninhadas, métodos, construtores e todos os declaradores
  de um campo;
- imports, herança e implementação de interfaces;
- chamadas de método (`calls`) e instanciações (`constructs`);
- símbolo de origem, linha e confiança de cada relação;
- parser efetivamente usado e quantidade de erros sintáticos por fonte.

As arestas de chamada são **sintáticas**. Por exemplo, `servico.salvar()` informa
o receptor textual e o método, mas não afirma qual classe concreta está em
`servico`. Resolver isso semanticamente depende do classpath real, cuja ordem
ainda não foi fornecida.

## Consulta e grounding

O comando abaixo lista chamadores e devolve release, JAR, classe, linhas,
SHA-256, trecho, frescor e confiança:

```powershell
vr-norte callers-erp-code gravarLogPdv --release current
```

`resolution: syntactic` é sempre incluído, evitando apresentar inferência como
resolução exata. A mudança do hash dos JARs continua gerando aviso de índice
desatualizado.

## Migração incremental

O schema 4 acrescenta metadados do parser e das relações por `ALTER TABLE`, sem
apagar o banco. A versão do parser invalida somente fontes antigas; uma segunda
execução não regrava fontes cujo conteúdo e schema já coincidem.

## Validação na release real

Escopo disponível nesta etapa: três lotes concluídos de `VRPdv.jar`.

- fontes: 1.277;
- símbolos: 18.747;
- relações totais: 56.942;
- chamadas: 44.003;
- construções: 3.397;
- imports: 8.903;
- fontes processadas por Tree-sitter: 1.277 (100%);
- fontes com erro sintático: 0;
- erros de indexação: 0;
- primeira migração: 18,741 segundos;
- segunda execução: 0 alteradas, 1.277 preservadas, 2,947 segundos.

Uma consulta real a `LogPdv.gravarLogPdv` retornou chamadores em classes como
`CopiarDLL`, `CupomVerdeRequest` e `TrocoController`, com linhas, hash, release e
frescor `fresh`.

## Limites e próximo incremento

- o corpus ainda cobre somente os três lotes concluídos; os 92 restantes devem
  continuar de forma retomável antes de medir cobertura dos 46 JARs completos;
- chamadas dinâmicas, reflexão, lambdas indiretas e polimorfismo não são
  resolvidos pelo grafo sintático;
- a próxima camada de busca híbrida deve adicionar embeddings por símbolo/trecho
  sem substituir FTS5 e filtros exatos;
- a resolução semântica do grafo deve esperar uma fonte confiável para a ordem
  do classpath por release.

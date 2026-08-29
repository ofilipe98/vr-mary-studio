# Gate 3 — Índice de código pesquisável

Data: 2026-08-29

## Objetivo

Transformar somente saídas de decompilação aprovadas em uma ferramenta de
consulta pequena, incremental e citável, sem injetar o conteúdo dos JARs no
prompt do orquestrador.

## Implementação

- Índice FTS5 separado da base de conhecimento, no mesmo SQLite operacional de
  código.
- Busca exata priorizada para tipos, construtores, métodos e campos.
- Busca lexical no nome qualificado, símbolos, relações e corpo Java.
- Extração estrutural inicial de pacote, tipos, métodos, campos, imports,
  herança e interfaces.
- Chave estável por release, artefato, classe e hashes de bytecode.
- Reindexação incremental por hash do fonte e versão do parser.
- Citação pronta com release, JAR, classe, intervalo de linhas e SHA-256 do
  fonte decompilado.
- Consulta de frescor em tempo de busca; uma mudança posterior nos JARs produz
  aviso explícito em vez de apresentar o índice como atual.

## Validação real

Base: três lotes aprovados do `VRPdv.jar`, release `current`.

| Métrica | Valor |
|---|---:|
| Fontes Java | 1.277 |
| Símbolos | 18.351 |
| Relações | 9.548 |
| Lotes cobertos | 3 |
| Erros de indexação | 0 |
| Segunda indexação | 0 alterados / 1.277 inalterados |

Consultas reais validadas:

- `VendaVO`: priorizou a declaração de tipo e distinguiu classes homônimas por
  pacote, com citação de linhas.
- `VRPdvAdminAutenticacaoRequest`: encontrou a classe e também o serviço que a
  importa.
- `PromocaoService`: retornou tipos, campos e referências relacionadas sem
  perder release e JAR de origem.

Durante a validação, o parser confundiu inicialmente `return new VendaVO()` com
uma assinatura. A regra foi corrigida, o índice ganhou versionamento próprio e
os 1.277 fontes foram reprocessados. Também foi corrigida a seleção do excerto
para que a faixa citada sempre contenha o símbolo encontrado.

## Limite deste gate

A extração atual é estrutural e deliberadamente conservadora; não é ainda uma
AST Java completa. Também não há embeddings. Portanto, este gate aprova a base
lexical citável, mas não conclui sozinho a arquitetura híbrida desejada.

Próximos passos:

1. adicionar parser AST tolerante aos fontes decompilados e grafo de chamadas;
2. criar chunks de classe/método e busca semântica incremental;
3. definir a ferramenta enxuta que o Agente de Código poderá consultar;
4. adicionar o toggle opt-in e o worker ao fan-out do VR Ultra;
5. validar chamados cuja causa conhecida estava no código.

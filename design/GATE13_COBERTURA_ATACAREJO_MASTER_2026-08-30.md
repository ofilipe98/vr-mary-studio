# Gate 13 — cobertura de VRAtacarejo e VRMaster

Data da validação: 2026-08-30

Release selecionada: `current`

SHA-256 do manifesto: `93217be54b3f1e9f7323547ef2f22add4c6b2b7224733135a54465b842106f33`

## Resultado

Os sete módulos classificados como principais estão cobertos no índice de
código: `VRMaster`, `VRAutorizador`, `VRConcentrador`, `VRAtacarejo`,
`VRAtacado`, `VRGerenciadorNFCe` e `VRPdv`.

A cobertura integral da release passou de 10/46 para 12/46 JARs. Os dois novos
planos foram executados serialmente, em checkpoints de até dez lotes, sem
decompilação durante consultas e sem remover planos ou saídas anteriores.

| JAR | Lotes | Conteúdos de classe | Bytecode | Fontes geradas | Estado |
| --- | ---: | ---: | ---: | ---: | --- |
| `VRAtacarejo.jar` | 75 | 37.340 | 127.935.271 bytes | 25.125 | completo |
| `VRMaster.jar` | 103 | 48.519 | 188.443.354 bytes | 21.821 | completo |

Ambos terminaram com todos os lotes em `completed`, nenhuma atenção pendente e
zero erro de indexação. O contador de origens pesquisáveis e o contador de JARs
cobertos convergiram em 12.

## Correções descobertas na release real

### Capitalização de caminhos no Windows

Dois lotes do `VRAtacarejo.jar` continham pacotes IBM declarados como
`COM.ibm...`. Os fontes preservavam esse package, mas o NTFS reutilizava o
diretório físico `com`, criado anteriormente. A validação comparava os caminhos
como strings sensíveis a maiúsculas e classificava 31 fontes existentes como
ausentes.

A chave de comparação agora segue a semântica do filesystem: insensível a
capitalização no Windows e sensível nas plataformas que distinguem os nomes.
Os nomes lógicos Java, hashes e citações continuam preservando a capitalização
original. Os dois lotes reais foram reenfileirados e concluíram com Vineflower.

### Fontes Kotlin produzidas pelo Vineflower

Um lote do `VRMaster.jar` continha `BeanFactoryExtensionsKt` e
`ListableBeanFactoryExtensionsKt`. O Vineflower reconheceu o bytecode Kotlin e
gerou arquivos `.kt`; o contrato anterior aceitava apenas `.java`, acionando um
fallback CFR que perdia outras classes do lote.

O executor e o índice agora aceitam `.java` e `.kt`. Cada fonte Kotlin recebe
identidade e package baseados no caminho e no conteúdo, parser marcado como
`kotlin_structural`, corpo pesquisável e a mesma proveniência de release, JAR,
classe e hash. Arquivos de outras extensões continuam sem contar como cobertura.
O retry real passou com 225 famílias esperadas e 279 fontes geradas.

## Capacidade

| Métrica | Antes | Depois |
| --- | ---: | ---: |
| Uso do índice | 3.067.050.360 bytes | 5.223.303.113 bytes |
| Projeção conservadora | 30.003.638.360 bytes | 27.077.907.183 bytes |
| Limite configurado | 33.572.848.010 bytes | 33.572.848.010 bytes |
| Estado | `ready` | `ready` |

O crescimento real foi de 2.156.252.753 bytes. A projeção caiu porque os dois
JARs deixaram de usar a reserva genérica de 10× e passaram a contribuir com o
consumo observado. Restam 34/46 JARs, com até três releases simultâneas
configuradas.

## Critérios de aceite

- release explícita e fresca durante todo o processamento;
- 178/178 lotes novos em `completed`;
- zero lote `partial` ou `failed` ao encerrar os planos;
- zero erro de indexação;
- Java e Kotlin pesquisáveis com proveniência do bytecode;
- sete módulos principais cobertos;
- classpath conflitante continua sinalizado, sem perfil completo inferido;
- consumo real e projeção abaixo do teto configurado;
- testes de regressão para os dois problemas encontrados nos dados reais.

## Próxima etapa

Com os módulos principais cobertos, o próximo gate deve executar o benchmark
pareado com chamados resolvidos cuja causa conhecida esteja em código:

1. anonimizar e classificar os casos por módulo e causa conhecida;
2. executar cada caso no VR Ultra com o Agente de Código desligado e ligado;
3. medir correção da causa-raiz, citações válidas, divergências, latência e
   tokens;
4. revisar humanamente os pares sem revelar ao avaliador qual configuração foi
   usada;
5. manter o toggle opt-in até os resultados demonstrarem ganho consistente.

Em paralelo, devem ser coletados os comandos ou traces reais dos launchers para
confirmar os perfis de classpath. A cobertura dos 34 JARs restantes pode avançar
depois do benchmark, priorizada por demanda real e ganho observado.

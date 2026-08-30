# Gate 11 — expansão controlada dos JARs prioritários

Data da validação: 2026-08-30  
Release selecionada: `current`  
SHA-256 do manifesto: `93217be54b3f1e9f7323547ef2f22add4c6b2b7224733135a54465b842106f33`

## Resultado

O índice passou de 3/46 para 10/46 JARs integralmente cobertos. Nenhum JAR foi
considerado coberto a partir de um plano parcial e nenhum dado fornecido pelo
usuário foi removido.

JARs cobertos no checkpoint:

- `VRAtacado.jar`
- `VRAutorizador.jar`
- `VRChat.jar`
- `VRConcentrador.jar`
- `VRGerenciadorNFCe.jar`
- `VRGerenciadorVAN.jar`
- `VRMicroTerminal.jar`
- `VRPdv.jar`
- `VRRecebimento.jar`
- `VRSoftware.jar`

Dos sete módulos definidos como prioritários, cinco ficaram completos:

| JAR | Lotes | Conteúdos de classe | Fontes geradas | Estado |
| --- | ---: | ---: | ---: | --- |
| `VRPdv.jar` | 97 | 46.994 | 30.115 | completo |
| `VRGerenciadorNFCe.jar` | 29 | 13.806 | 7.869 | completo |
| `VRConcentrador.jar` | 16 | 6.979 | 4.239 | completo |
| `VRAutorizador.jar` | 29 | 14.044 | 9.612 | completo |
| `VRAtacado.jar` | 8 | 3.719 novos | 2.042 | completo |
| `VRAtacarejo.jar` | — | — | — | pendente |
| `VRMaster.jar` | — | — | — | pendente |

`VRAtacado.jar` possui muito conteúdo já coberto por outros módulos; por isso o
plano precisou de apenas oito lotes novos apesar do tamanho do arquivo.

## Capacidade medida

| Métrica | Antes do Gate 11 | Checkpoint 10/46 |
| --- | ---: | ---: |
| Uso do índice | 1.546.407.401 bytes | 2.490.550.929 bytes |
| Projeção conservadora | 33.099.565.761 bytes | 29.427.138.929 bytes |
| Limite configurado | 33.572.848.010 bytes | 33.572.848.010 bytes |
| Estado | `tight` | `ready` |

O crescimento observado foi de 944.143.528 bytes. A projeção caiu porque cinco
JARs relevantes deixaram de usar a estimativa genérica de 10× e passaram a ter
consumo real conhecido. Permanecem 36 JARs pendentes e até três releases
simultâneas configuradas.

## Correção descoberta em produção

O `VRGerenciadorNFCe.jar` revelou classes internas anônimas que Vineflower e CFR
incorporam no fonte da classe externa. O validador anterior tratava
`Outer$Inner$1.class` como ausente quando o decompilador produzia apenas
`Outer.java` ou `Outer$Inner.java`, principalmente quando `Outer.class` já havia
sido deduplicado em outro JAR.

O executor agora:

1. resolve famílias contra o namespace completo do artefato e da variante Java;
2. aceita como cobertura o fonte externo, o fonte da interna nomeada ou o fonte
   específico produzido pelo decompilador;
3. continua exigindo que cada classe compilada tenha ao menos uma dessas
   representações, sem transformar saída realmente ausente em sucesso.

O lote real foi reexecutado e passou com 357 famílias esperadas, 360 fontes
geradas e zero erro de indexação. Há teste de regressão para os três limites de
fonte possíveis.

## Divergência estrutural encontrada no VRAtacado

O `VRAtacado.jar` contém 46.428 nomes lógicos de classe e 22.170 nomes repetidos
no diretório central do ZIP:

- 19.300 nomes são aliases do mesmo cabeçalho físico;
- 2.870 nomes apontam para mais de um cabeçalho físico;
- 2.629 nomes possuem CRC/tamanho divergente entre as ocorrências.

O índice preservou os conteúdos distintos e concluiu apenas os conteúdos ainda
pendentes, mas não existe informação confirmada sobre qual ocorrência o
classpath real seleciona. Essa divergência não pode ser ocultada por uma escolha
silenciosa da variante “mais confiante”. O aviso deve permanecer disponível na
auditoria, sem gerar milhares de linhas repetidas no console.

## Critérios de aceite aplicados

- release explícita, fresca e com os 46 JARs inventariados;
- execução serial e retomável, em janelas de até dez lotes;
- zero lote `partial` ou `failed` para declarar um JAR coberto;
- zero erro na indexação Java;
- crescimento real abaixo do teto configurado de 10×;
- interrupção antes de fan-out, embeddings ou benchmark enquanto a ordem do
  classpath permanecer desconhecida;
- preservação dos planos antigos para auditoria.

## Próxima decisão

O Gate 12 deve formalizar a resolução de classpath e de entradas duplicadas:

1. registrar no manifesto aliases físicos, duplicatas reais e conflitos de
   bytecode por JAR;
2. reproduzir a seleção efetiva de `java.util.zip.ZipFile`/classloader para uma
   classe duplicada e compará-la com o ambiente real do ERP;
3. permitir ordem de classpath declarada por release, sem inferi-la pelo nome da
   pasta;
4. sinalizar resultados ambíguos quando a ordem não estiver disponível;
5. somente depois retomar `VRAtacarejo.jar` e `VRMaster.jar` e iniciar o
   benchmark de chamados.


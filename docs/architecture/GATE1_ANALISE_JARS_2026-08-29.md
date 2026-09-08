# Gate 1 — Análise dos JARs do ERP

Data: 2026-08-29

## Objetivo

Validar runtime, ferramentas, volume de bytecode, deduplicação e viabilidade de
decompilar JARs completos antes de construir o índice definitivo.

## Toolchain isolada

- Java: Temurin JRE 17.0.20.1, dentro de `VRProject/tools/code-analysis`.
- Vineflower: 1.12.0.
- CFR: 0.152.
- O Java global permaneceu no Temurin 8.0.492.

Checksums SHA-256:

```text
Vineflower 1.12.0
1dfcfe974395734fa467ce620661c7623d05ba83670de0529b1fbd63ff548b9d

CFR 0.152
f686e8f3ded377d7bc87d216a90e9e9512df4156e75b06c655a16648ae8765b2

Temurin JRE 17 para Windows x64
bc21a93923103cdaac93ee337b0ae4365e739fde36df823dd456bc67c8a9d352
```

## Métricas dos cinco JARs representativos

JARs analisados:

- `VRMaster.jar`
- `VRAtacarejo.jar`
- `VRPdv.jar`
- `lib/VRLib.jar`
- `lib/VRCore.jar`

Resultado:

| Métrica | Valor |
|---|---:|
| Entradas de classe | 352.055 |
| Classes lógicas únicas | 131.875 |
| Nomes lógicos duplicados | 104.248 |
| Nomes iguais com bytecode diferente | 23.990 |
| Conteúdos de classe únicos | 162.411 |
| Entradas deduplicáveis por conteúdo | 189.644 |
| Entradas multi-release | 1.792 |
| Bytecode descompactado | 1.225.132.144 bytes |
| Duração da medição | 14,8 segundos |

Não houve erro de leitura dos cinco artefatos.

## Benchmark de decompilação do VRPdv.jar

### Vineflower

- Heap: 4 GB.
- Limite: 15 minutos.
- Resultado: timeout.
- Saída parcial: 8.659 arquivos e 160.053.361 bytes.
- Memória observada: aproximadamente 4,65 GB.

### CFR

- Heap: 4 GB.
- Duração: aproximadamente 7,2 minutos.
- Resultado: falha por `OutOfMemoryError: Java heap space`.
- Saída parcial: 26.192 arquivos e 138.931.821 bytes.
- Memória observada: aproximadamente 4,7 GB.

Saída parcial nunca deve marcar um artefato como pronto.

## Decisão

O Gate 1 rejeita decompilação integral por JAR como unidade operacional. O
processador definitivo deve:

1. criar lotes determinísticos de famílias de classes;
2. deduplicar pelo hash do bytecode antes da decompilação;
3. executar apenas um processo de decompilação por vez;
4. usar heap e timeout configuráveis por lote;
5. persistir `pending`, `running`, `completed`, `partial` e `failed`;
6. retomar somente lotes incompletos;
7. usar CFR apenas nos lotes ou classes que falharem no Vineflower;
8. preservar JAR, release e hash em todas as ocorrências de uma classe.

Os outros quatro JARs não foram decompilados integralmente porque o menor
artefato representativo já invalidou a estratégia. Repetir o mesmo desenho
consumiria recursos sem responder uma questão técnica nova.

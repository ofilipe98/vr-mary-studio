# Gate 2 — Lotes retomáveis de decompilação

Data: 2026-08-29

## Objetivo

Validar em um JAR real a arquitetura escolhida depois que o Gate 1 rejeitou a
decompilação monolítica: planejamento determinístico, deduplicação por bytecode,
execução serial, cobertura verificável e retomada persistente.

## Implementação

- Estado operacional separado em `indice/codigo/processing.sqlite`.
- Identificadores determinísticos de plano e lote.
- Todas as ocorrências preservam release, hash da release, JAR, hash do JAR,
  entrada ZIP, classe lógica, versão multi-release e hash do bytecode.
- Conteúdo idêntico é decompilado uma vez, sem perder as ocorrências.
- Classe externa e classes internas (`$`) permanecem na mesma unidade.
- Um lock de arquivo global limita a execução a um decompilador.
- Vineflower é primário; CFR roda somente quando o primário falha ou não cobre
  todas as famílias esperadas.
- Cada tentativa grava `attempt.json`; saída parcial permanece auditável, mas
  não recebe estado `completed`.

## Validação real — VRPdv.jar

Configuração do plano:

| Item | Valor |
|---|---:|
| Release | `current` |
| Hash da release | `93217be54b3f1e9f7323547ef2f22add4c6b2b7224733135a54465b842106f33` |
| Limite de classes por lote | 500 |
| Limite de bytecode por lote | 8.388.608 bytes |
| Conteúdos únicos planejados | 46.994 |
| Lotes gerados | 95 |
| Bytecode planejado | 154.648.448 bytes |
| Tempo de planejamento | aproximadamente 4 segundos |

Três lotes reais foram executados com Java 17 isolado, Vineflower 1.12.0,
heap de 2 GB e timeout de cinco minutos:

| Lote | Bytecodes | Famílias esperadas | Fontes geradas | Duração | Resultado |
|---|---:|---:|---:|---:|---|
| 1 | 500 | 431 | 431 | 5,6 s | concluído |
| 2 | 500 | 415 | 415 | 4,6 s | concluído |
| 3 | 500 | 431 | 431 | 3,5 s | concluído |

O terceiro lote foi executado com a regra definitiva, que confere os caminhos
esperados em vez de aceitar apenas a contagem total, e gravou a trilha
`attempt.json`. O primeiro foi executado imediatamente antes da migração que
adicionou os contadores ao SQLite; sua cobertura 431/431 foi aferida sobre os
arquivos preservados e registrada neste documento.

## Decisão

O Gate 2 aprova o processador em lotes como base para a próxima fase. Ele reduz
o teste do menor JAR representativo de mais de quinze minutos sem conclusão
para lotes de poucos segundos com cobertura objetiva e retomada.

Isso ainda não torna o índice pesquisável nem habilita o Agente de Código no
VR Ultra. As próximas fases são:

1. concluir uma amostra mais larga de módulos e medir falhas/fallback;
2. extrair símbolos e relações AST dos fontes aprovados;
3. criar busca híbrida por classe, pacote, símbolo e semântica;
4. ligar a consulta ao worker de código opt-in e à síntese com citações;
5. validar chamados reais com o toggle ligado e desligado.

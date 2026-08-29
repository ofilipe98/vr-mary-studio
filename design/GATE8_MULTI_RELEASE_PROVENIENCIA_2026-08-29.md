# Gate 8 — JAR multi-release e proveniência por versão

Data: 2026-08-29

## Diagnóstico real

Ao ampliar a decompilação do `VRPdv.jar`, o plano de processamento v1 encontrou
um lote parcial na família `org.bouncycastle.asn1.sec.SECNamedCurves`. O lote
esperava `SECNamedCurves.java`, mas continha uma combinação de classes base e
entradas em `META-INF/versions/9` sem a classe externa completa.

Isso revelou um problema maior que a fonte ausente: um lote podia misturar
variantes da mesma classe para runtimes Java diferentes. O decompilador poderia
ignorar a entrada multi-release ou produzir uma única fonte associada a mais de
um bytecode. Portanto, o plano v1 foi considerado inadequado para promoção,
mesmo com 70 de 95 lotes concluídos.

## Correção estrutural

- O schema de processamento passou para v2 e entra na identidade do plano.
- Cada lote contém exatamente uma `class_version`.
- Entradas base, Java 9, Java 11 e Java 15 nunca compartilham lote.
- Entradas `META-INF/versions/<n>/...` são normalizadas para o caminho lógico da
  classe dentro do JAR temporário entregue ao decompilador.
- Famílias de classes externas e internas permanecem atômicas dentro de cada
  versão.
- O executor usa todos os membros da família ao retomar trabalho parcialmente
  reaproveitado.
- Conteúdo concluído registra a versão do schema que o produziu. Uma mudança de
  schema força reprocessamento em vez de reutilização silenciosa.
- Execução, retry e indexação recusam planos de schema antigo.
- O status lista lotes `partial`/`failed`, contagens esperada/real e o erro para
  auditoria sem consulta manual ao SQLite.

## Índice e grounding

O schema do índice passou para v5. A chave da fonte e a citação incluem a versão
do bytecode (`base`, `Java 9`, `Java 11` ou `Java 15`). Entradas derivadas de
schema anterior são removidas por release durante a promoção do novo plano.

Quando duas variantes existem, a busca pode devolver ambas, com versão e hash
explícitos. O sistema não presume silenciosamente qual runtime o cliente usa;
essa escolha continua sendo uma informação necessária para interpretar a
variante efetiva.

## Validação real

Release: `current`

Artefato: `VRPdv.jar`
Manifesto: `93217be54b3f1e9f7323547ef2f22add4c6b2b7224733135a54465b842106f33`

Plano v2: `plan-5fd318e11c9bc2469f65a13b`

| Versão de classe | Lotes | Conteúdos planejados |
|---|---:|---:|
| base | 93 | 46.121 |
| Java 9 | 2 | 819 |
| Java 11 | 1 | 34 |
| Java 15 | 1 | 20 |

Resultado: 97 de 97 lotes concluídos, sendo 92 com Vineflower e 5 pelo fallback
CFR, sem falha ou saída parcial. Foram validadas 29.343 fontes esperadas e
30.115 arquivos Java produzidos.

O índice promovido contém:

| Métrica | Total |
|---|---:|
| Fontes únicas | 30.113 |
| Símbolos | 584.288 |
| Relações | 1.526.243 |
| Chamadas | 1.139.632 |
| Construções | 141.029 |
| Extensões | 21.295 |
| Implementações | 14.529 |
| Imports | 209.758 |
| Fontes base | 29.537 |
| Fontes Java 9 | 564 |
| Fontes Java 11 | 7 |
| Fontes Java 15 | 5 |

A consulta de prova por `SECNamedCurves` retornou separadamente a fonte base e
a fonte Java 9, com SHA-256 e citação distintos.

## Limites e próximos passos

- Esta cobertura completa é somente do `VRPdv.jar`; os outros 45 JARs ainda
  exigem seleção e plano explícitos.
- A ordem efetiva do classpath continua desconhecida. Duplicatas entre JARs não
  devem ser resolvidas automaticamente.
- Para decidir qual variante multi-release representa o comportamento de um
  cliente, ainda é necessário registrar a versão Java do runtime desse cliente.
- Os 586 fontes com erros sintáticos continuam pesquisáveis pelo parser
  tolerante, mas devem carregar confiança menor em análises profundas.
- O próximo Gate deve testar chamados reais com análise de código ligada e
  desligada e medir ganho, custo e latência.

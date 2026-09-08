# Gate 14 — preflight e revisão cega do benchmark de código

Data da validação: 2026-08-30

Release selecionada: `current`

## Objetivo

Impedir que o benchmark pareado consuma duas execuções VR Ultra por caso quando
o caso ainda não é mensurável e separar a avaliação humana da informação sobre
qual resposta usou o Agente de Código.

Nenhuma chamada de modelo foi executada neste gate. Ainda não existe no
workspace uma suíte de chamados reais, resolvidos e anonimizados.

## Gaps encontrados

1. A execução validava release e índice, mas não comprovava que os JARs-alvo
   estavam integralmente cobertos.
2. Símbolos esperados podiam estar ausentes do índice, tornando o par incapaz de
   medir o ganho pretendido.
3. O arquivo-modelo podia ser executado sem substituir todos os placeholders.
4. O relatório expunha variantes `off` e `on` ao lado dos campos de revisão
   humana; portanto a revisão não era cega.
5. O score automático não exigia que uma fonte esperada aparecesse nas citações
   do Agente de Código.

## Preflight obrigatório

Cada caso passa a declarar:

- `module`;
- `target_jars`;
- `known_root_cause`, mantida local e não incluída na pergunta enviada;
- `expected_terms`;
- `expected_code_symbols`;
- `expected_citation_sources`;
- `forbidden_terms`.

Antes de abrir conversas, o preflight exige release fresca, índice não vazio,
JARs-alvo completamente cobertos, critérios objetivos e ausência de marcadores
do template. Cada símbolo esperado é pesquisado na release e precisa aparecer
em um dos JARs-alvo. Frescor, citação e estado de classpath do candidato ficam
registrados.

O score inclui separadamente termos, símbolos e fontes de citação esperadas.
Classpath `ambiguous`, `shadowed` ou `unknown` não é ocultado: o caso pode seguir
quando existe evidência, mas recebe aviso explícito.

## Validação contra o índice real

Um caso sintético local, sem chamada de modelo, foi usado apenas para validar o
preflight:

| Métrica | Resultado |
| --- | ---: |
| JARs cobertos | 12/46 |
| Fontes indexadas | 101.139 |
| Símbolos indexados | 1.959.797 |
| Símbolo procurado | `BeanFactoryExtensionsKt` |
| JAR confirmado | `VRMaster.jar` |
| Frescor | `fresh` |
| Classpath | `shadowed` |
| Preflight | aprovado com aviso |

O próprio template foi validado como reprovado enquanto contém placeholders.

## Revisão cega A/B

Após uma execução real, o Studio produz dois arquivos separados:

1. pacote do revisor, contendo pergunta e respostas rotuladas apenas como A/B;
2. chave de auditoria, contendo o mapeamento A/B para `off/on`.

O revisor atribui notas de 0 a 4 para correção e grounding, escolhe A, B ou
empate e adiciona observações. A finalização só aceita todos os casos avaliados,
confere benchmark/review IDs, correspondência exata dos casos e mapeamentos, e
valida um SHA-256 do conteúdo imutável. Alterar pergunta, resposta ou citação
depois do cegamento invalida o pacote.

A consolidação traduz as notas para `off/on` somente com a chave, calcula deltas
médios e preferências e preserva o `review_id` na trilha de auditoria.

## Fluxo operacional

```powershell
# Deve ficar verde antes de aprovar custo de modelo
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject preflight-code-analysis casos-codigo.json

# Executa duas variantes por caso somente após aprovação explícita
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject benchmark-code-analysis casos-codigo.json `
  --provider codex --model <modelo> --approve-model-usage

# Entregar somente review.json ao avaliador
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject prepare-code-analysis-review relatorio.json `
  --output review.json --key-output review-key.json

# Depois de preencher review.json
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject finalize-code-analysis-review `
  relatorio.json review.json review-key.json --output reviewed.json
```

Os comandos não sobrescrevem arquivos existentes. A chave deve permanecer com
quem coordena o experimento, fora do alcance do revisor até a entrega das notas.

## Critérios de aceite

- zero chamada de modelo durante preflight e preparação da revisão;
- casos não mensuráveis bloqueados antes de abrir conversas;
- cobertura integral comprovada por JAR-alvo;
- símbolo esperado comprovado no índice e ligado a uma citação;
- placeholders do template recusados;
- pacote do revisor sem mapeamento `off/on`;
- chave separada e integridade protegida por SHA-256;
- notas fora de 0–4, casos ausentes/duplicados e conteúdo alterado recusados;
- relatório final conserva métricas automáticas e julgamento humano separados.

## Próximo insumo necessário

Selecionar de cinco a dez chamados encerrados cuja causa confirmada estava em
um dos sete módulos principais, anonimizar dados de cliente e preencher os
critérios antes de olhar as respostas do benchmark. Só depois da revisão cega
os resultados podem embasar mudança de default do toggle ou expansão orientada
dos 34 JARs restantes.

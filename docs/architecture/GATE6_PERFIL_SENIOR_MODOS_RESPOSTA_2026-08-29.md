# Gate 6 — Perfis especialistas e modos de resposta

Data: 2026-08-29

## Resultado

O Studio possui uma camada de perfis especialistas para os modos VR e Ultra. A
seleção é uma preferência local, começa desligada e oferece quatro opções:

- Adaptativa: injeta a skill built-in `adaptive` sem impor template nem
  substituir a intenção detectada automaticamente;
- Treinamento: resposta pedagógica, passo a passo e reutilizável em onboarding;
- Suporte: diagnóstico técnico, causa confirmada ou hipóteses qualificadas e
  validação da correção;
- Implantação: mapeamento de dados, diferenças de schema/configuração, sequência,
  riscos, reversão e checklist.

Adaptativa é materializada como `SkillDefinition` com `scope="vr"`,
`invocation_mode="injected"` e `source="app_managed"`. Seu arquivo é empacotado
em `vrsoft_extractor/mary/data/` e não é uma skill editável pelo usuário. A
seleção persistida usa `research/expert_profile_enabled`; internamente,
Adaptativa continua representada por esse estado ligado e
`research/response_mode="auto"`, sem persistir `adaptive` como template.

## Integração com o harness

1. O `ChatBridge` lê perfil e modo no começo da execução.
2. A análise automática de intenção sempre ocorre nos modos VR e Ultra.
3. `response_mode="adaptive"` preserva todos os campos da `ResponseIntent`.
4. A skill Adaptativa é injetada no VR tool-driven e no contexto de
   análise/síntese do Ultra.
5. Treinamento, Suporte e Implantação continuam aplicando seus contratos
   explícitos antes da criação do contrato de resposta.
6. A trilha de eventos grava o modo efetivo junto da intenção resultante.

O perfil Adaptativa não habilita nem desabilita fontes, não modifica o contrato
das três tools VR, não cria agentes e não altera plano, workers, paralelismo,
retry, orçamento, DEV Java ou síntese do Ultra.

## Isolamento do modo OFF

Quando o modo resolvido é `off`, o seletor fica oculto e inativo. O bridge envia
`response_mode="auto"`, o `_enrich_off_prompt` não recebe política de perfil e
nenhuma skill de perfil é injetada. A preferência persistida não é apagada; ao
voltar para VR ou Ultra, a última seleção pode voltar a ser aplicada.

## Classificação automática

Mesmo sem perfil explícito, termos como implantação, migração, mapeamento de
dados, diff de schema e virada de sistema criam o contrato de Implantação. O
seletor explícito existe para remover ambiguidade. Adaptativa não substitui essa
classificação: ela apenas orienta a profundidade, a investigação e a forma da
resposta depois que a intenção automática já foi determinada.

## Validação

- Adaptativa é uma skill built-in VR, app-managed e injected;
- a chave canônica de preferência substitui a nomenclatura anterior;
- preferências de instalações antigas são lidas uma vez e migradas;
- perfil desativado mantém `auto` e impede seleção manual;
- `adaptive` preserva a identidade e todos os campos da intenção;
- VR mantém zero retrieval antecipado e continua tool-driven;
- Ultra mantém as mesmas fontes e o mesmo grafo de workers;
- o texto Adaptativa não entra em `search_scope`;
- OFF envia `auto` e não injeta política;
- skills normais do usuário permanecem independentes.

## Próximos passos

- avaliar novas políticas built-in sem permitir que alterem retrieval ou
  fan-out;
- executar benchmarks com chamados reais para Adaptativa, Treinamento, Suporte e
  Implantação;
- adicionar avaliação de qualidade por intenção preservada, sem template fixo.

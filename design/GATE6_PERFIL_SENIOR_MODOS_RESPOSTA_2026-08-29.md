# Gate 6 — Perfil sênior e modos de resposta

Data: 2026-08-29

## Resultado

O Studio agora possui um perfil especialista sênior, desligado por padrão e
salvo nas preferências do usuário. Quando ativo, ele libera uma seleção manual
de quatro comportamentos:

- Automático: mantém a classificação da intenção;
- Treinamento: resposta pedagógica, passo a passo e reutilizável em onboarding;
- Suporte: diagnóstico técnico, causa confirmada ou hipóteses qualificadas e
  validação da correção;
- Implantação: mapeamento de dados, diferenças de schema/configuração, sequência,
  riscos, reversão e checklist.

O perfil é uma preferência de trabalho local, não um mecanismo de segurança ou
autorização. Desligá-lo força o modo Automático e impede que uma seleção manual
antiga continue atuando silenciosamente.

## Integração com o harness

1. O `ChatBridge` lê perfil e modo no começo da execução.
2. A análise automática de intenção sempre ocorre.
3. Quando o perfil sênior está ativo, o modo explícito transforma a intenção
   antes da criação do contrato de resposta.
4. O contrato transformado orienta workers, síntese, supervisão e profundidade.
5. A trilha de eventos grava o modo selecionado junto da intenção efetiva.

O modo Implantação é considerado investigação crítica no VR Ultra e pode abrir
o fan-out mesmo quando a consulta inicial aponta somente um módulo. Isso permite
cruzar schema e documentação sem tornar todo atendimento comum multiagente.

## Classificação automática

Mesmo sem o perfil sênior, termos como implantação, migração, mapeamento de
dados, diff de schema e virada de sistema criam o contrato de Implantação. O
seletor existe para remover ambiguidade, não para substituir a classificação.

## Validação

- perfil desativado mantém `auto` e rejeita seleção manual;
- perfil e modo persistem ao reabrir a interface;
- desligar o perfil limpa o modo manual;
- os três modos geram propósitos, públicos e níveis técnicos distintos;
- Implantação exige mapeamento, diff, risco/reversão e checklist;
- o override ocorre antes do contrato e do fan-out;
- tela VR Ultra validada renderizada em 1480 × 900, com o seletor desabilitado no
  estado padrão.

## Próximos passos

- validar com usuários reais se o nome “perfil sênior” é o mais claro;
- avaliar política administrada por equipe caso a opção deixe de ser apenas uma
  preferência local;
- executar o benchmark com chamados resolvidos e materiais reais dos três modos;
- adicionar busca vetorial por provedor configurável, sem remover FTS5/grafo.

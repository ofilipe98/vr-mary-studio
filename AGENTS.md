# Diretrizes de Engenharia e Manutenção do Projeto (VRStudio)

Este arquivo define as diretrizes de engenharia, qualidade e investigação para o desenvolvimento e manutenção do projeto `VRStudio`. As instruções complementam o ambiente Antigravity e o T3 Code focando na qualidade de código e prevenção de regressões.

## Ambiente e comandos

- Leia `docs/DEVELOPMENT.md` para o mapa dos módulos e dos testes.
- Inspecione `git status --short` antes de editar e preserve o trabalho local existente.
- Use `.\.venv\Scripts\python.exe -m ...`; executáveis de uma virtualenv movida podem apontar ao checkout antigo.
- Durante a edição: `-m ruff check .` e `-m pytest tests/test_arquivo.py -q -x`.
- Após uma falha: `-m pytest --lf -q -x`. Para concluir: `-m pytest -q --durations=10` e revisão do diff.
- `-m pytest -q -m qml` seleciona os testes de renderização e interação; `-m pytest -q -m "not qml"` seleciona os demais.
- Testes de fan-out omitem cooldowns de produção por padrão; use o marker `research_timing` para testar essas esperas.
- Medições reproduzíveis: `.\.venv\Scripts\python.exe scripts/benchmark_hotpaths.py --output .test-tmp/hotpaths.json`.
- `VRProject/`, `.env` e `.state/` contêm dados do usuário. Use diretórios temporários para testes e `.test-tmp/` para resultados de verificação.

---

## Lane Wiki (VRWiki + Endoo)

A lane Wiki explícita/source-wide usada por VR e Ultra consulta sempre `vrwiki` + `endoo`; o toggle legado de Endoo não restringe esse caminho. Falha de uma origem não elimina os resultados da outra: cada origem é consultada em bloco de erro independente e a lane só fica `unavailable` quando todas as origens falham.

---

## Tools VR, OFF e paginação

`vr_sources`, `vr_search` e `vr_read` pertencem somente aos modos VR e Ultra. O modo OFF não registra nem executa essas tools built-in por nenhum transporte: as dynamic tools do Codex e o servidor MCP built-in `vr-mary-studio` (OpenCode, Claude e Antigravity) seguem o modo resolvido e, no OFF, o MCP permanece apenas para integrações não-VR como o VRMonitor, sem anunciar nem executar tools VR. Uma requisição VR tool stale recebida em OFF é recusada sem executar retrieval. O OFF é um fluxo de modelo direto, recebe `MarySettings.root` como raiz de fontes opcional somente leitura e depende das capacidades nativas do provider para listar, buscar e ler arquivos: OpenCode expõe a raiz por acesso a diretório externo somente leitura, Claude recebe a raiz como diretório adicional somente leitura e o Antigravity depende do filesystem do runtime, sem campo ACP novo. O OFF não executa retrieval automático, `RetrievalService`, `KnowledgeRouter`, fan-out ou agentes VR; tools customizadas e MCPs explicitamente escolhidos pelo usuário permanecem disponíveis.

Quando as tools estão ativas em VR/Ultra, elas não possuem quota cumulativa por chamadas, caracteres, tempo ou tokens no chat. Cada chamada respeita o limite da própria ferramenta e a paginação por cursor/next_cursor continua sendo a forma de aprofundar resultados longos. Paginação é transporte, não orçamento. Cancelamento explícito, substituição do turno e limites externos inevitáveis do provider e do contexto permanecem válidos. Ausência ou falha em uma fonte específica não implica ausência nas demais fontes; quando o modelo escolhe uma fonte, nenhuma alternativa é acionada automaticamente.

---

## Perfis especialistas

Perfis especialistas são skills built-in injetadas exclusivamente nos modos VR e Ultra. Eles orientam apenas o comportamento e nunca alteram fontes, retrieval, tools ou fan-out. O modo OFF não exibe perfil ativo, não envia modo de perfil e não injeta política de perfil.

---

## Investigate Before Asking

Investigue antes de perguntar.

Procure respostas em:
* código
* configurações
* testes
* SQL
* documentação
* logs
* histórico Git

Pergunte ao usuário apenas quando a decisão não puder ser inferida do ambiente e alterar materialmente o resultado.

---

## Root Cause First

Em análises de bug:
1. identifique o comportamento incorreto
2. rastreie o fluxo completo
3. descubra onde o problema começa
4. encontre a causa raiz
5. diferencie causa de sintoma
6. proponha a menor correção segura

---

## Regression Analysis

Sempre considere:
* módulos afetados
* callers e consumers
* integrações
* regras de negócio relacionadas
* banco de dados
* possíveis diferenças entre versões
* histórico Git quando relevante
* fluxos que devem permanecer inalterados

---

## Existing Architecture First

Antes de criar uma nova abordagem, procure como o próprio projeto resolve situações equivalentes.

Respeite:
* padrões arquiteturais
* convenções de nomenclatura
* logging
* tratamento de erros
* acesso a banco
* serviços
* repositories/DAOs
* validações
* testes

---

## Verification

Não considere uma tarefa concluída sem validação.

Para correções:
1. confirme o problema
2. identifique a causa raiz
3. aplique a mudança mínima
4. execute testes relevantes
5. verifique regressões
6. revise o diff
7. confirme ausência de mudanças fora do escopo

---

## Bug Analysis Output

Quando o usuário pedir análise sem implementação, apresente o diagnóstico seguindo estritamente a estrutura abaixo:

### Problema
O que está acontecendo.

### Causa raiz
Por que acontece.

### Localização
Arquivos, classes, métodos ou SQL relevantes.

### Fluxo afetado
Como o sistema chega ao problema.

### Correção proposta
Menor alteração segura.

### Risco de regressão
Outros fluxos potencialmente afetados.

### Verificação
Como validar a correção.

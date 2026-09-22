# Relatório de Implementação e Verificação: Plano de Acesso Unificado (OFF, VR e ULTRA)

## 1. Visão Geral e Aceite
Implementação do **Plano Auditado de Acesso Unificado — OFF, VR e ULTRA** no repositório `D:\Codex\VRStudio` (HEAD `afc7d98`).
O objetivo central foi atingido: **o modo controla a estratégia de resposta; todos os modos oferecem acesso uniforme às mesmas fontes locais configuradas e disponíveis** (Wiki, KB, Schema e Código Java descompilado), mantendo em modo OFF o comportamento de produto equivalente ao ChatGPT Web para projetos, instruções e fontes: os materiais ficam disponíveis à conversa, sem retrieval automático obrigatório. A equivalência pretendida é de comportamento de produto, não de implementação interna.

---

## 2. Entregas por Componente e Arquitetura

### 2.1. Desacoplamento da Recuperação de Código e Runner
- **Módulo Extraído**: [code_retrieval.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/retrieval/code_retrieval.py)
  - Funções de alto nível: `retrieve_code_candidates`, `list_code_sources`, `read_code_source`, `check_code_availability`.
  - Separação entre busca semântica/símbolos pré-indexados e runner de orquestração.
- **Refatoração no Runner**: [runner.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/execution/runner.py)
  - `_execute_code_analysis` e `_retrieve_code_evidence` agora delegam para `retrieve_code_candidates`.

### 2.2. Migração Aditiva no Banco de Dados SQLite
- **Tabela**: `source_citations` em [common.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/repositories/common.py), [conversations.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/repositories/conversations.py) e [db.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/db.py)
  - `document_id` tornado `NULLABLE` para suportar fontes sem ID de documento tradicional (ex.: classes Java descompiladas).
  - Adicionadas colunas persistidas: `evidence_id`, `provenance`, `title`.
  - Mapeamento determinístico de classes Java citadas no texto da resposta via `_candidates_cited_in_content`.

### 2.3. Ferramentas Unificadas de Chat
- **Módulo**: [chat_tools.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/chat_tools.py)
  - `vr_sources`: Descoberta paginada de inventário e disponibilidade de Wiki, KB, Schema e Code.
  - `vr_search`: Busca compacta de trechos suportando `source in ("wiki", "kb", "schema", "code")` com filtros por módulo e contexto.
  - `vr_read`: Leitura paginada com limites controlados (`limit` padrão de 4000, max 8000 caracteres, suporte a `start_line` / `end_line`).

### 2.4. Servidor MCP Local Stdio
- **Módulo**: [mcp_server.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/mcp_server.py)
  - Implementação nativa e leve de MCP 2024-11-05 sobre `stdio` com JSON-RPC 2.0.
  - Carrega contexto do turno e expõe `vr_sources`, `vr_search` e `vr_read`.

### 2.5. Adaptadores de Provedor
- **Claude** ([claude.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/provider_adapters/claude.py)):
  - Gera `--mcp-config` apontando para o servidor MCP local em todos os modos.
  - Removido `--add-dir` arbitrário do modo OFF para evitar permissões excessivas.
- **Antigravity** ([antigravity.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/provider_adapters/antigravity.py)):
  - Registra o servidor MCP `mary_local_kb` em `mcpServers`.
- **OpenCode** ([opencode.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/provider_adapters/opencode.py)):
  - Configura o MCP `mary_local_kb` em `_opencode_environment`.
- **Codex** ([base.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/provider_adapters/base.py) & [orchestrator.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/orchestrator.py)):
  - Dynamic tools (`vr_sources`, `vr_search`, `vr_read`) registradas para Codex independentemente do modo.

### 2.6. Orquestrador e Modo OFF com comportamento de produto equivalente ao ChatGPT Web
- **Orquestrador**: [orchestrator.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/orchestrator.py)
  - `_enrich_off_prompt`: Injeta instruções do projeto (`INSTRUCTIONS.md`/`instructions.md`), lista de arquivos do workspace do projeto e aviso de ferramentas locais sob demanda.
  - As tools locais são registradas em todos os modos; OFF não executa retrieval automático nem fan-out e não injeta todo o corpus no prompt — o conteúdo é buscado/lido sob demanda, dentro dos limites das tools.
  - Isolamento estrito: workspaces de conversas gerenciadas (`is_managed_conversation_workspace`) não herdam instruções indevidas.

### 2.7. Script Portátil vr-search.ps1
- **Arquivos**: [vr-search.ps1](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/data/vr-search.ps1) e [workspace.py](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/workspace.py)
  - Atualizado `ValidateSet` para aceitar `('wiki', 'kb', 'schema', 'code')` e adicionado o parâmetro `-Context`.

---

## 3. Matriz de Testes e Resultados

### 3.1. Suíte Unificada ([test_unified_access_modes.py](file:///D:/Codex/VRStudio/tests/test_unified_access_modes.py))
1. `test_unified_tools_specs_contain_all_three_tools`: **PASSED**
2. `test_all_four_sources_searchable_and_readable`: **PASSED** (Wiki, KB, Schema e Java buscados e lidos via `vr_search` e `vr_read`)
3. `test_vr_sources_inventory_discovery`: **PASSED** (Descoberta paginada de catálogo e classes)
4. `test_off_mode_orchestrator_options_include_tools`: **PASSED** (Modo OFF registra ferramentas)
5. `test_off_mode_project_instructions_and_file_listing`: **PASSED** (Enriquecimento ChatGPT Web de instruções e materiais)
6. `test_off_mode_scratchpad_workspace_no_inheritance`: **PASSED** (Isolamento de conversas sem projeto)
7. `test_citations_persistence_additive_with_code_sources`: **PASSED** (Persistência aditiva de citações de código com `document_id=0`)
8. `test_candidates_cited_in_content_matches_java_class`: **PASSED** (Reconhecimento determinístico de citações FQCN)
9. `test_mcp_server_subprocess_transport`: **PASSED** (Handshake JSON-RPC e execução de tools sobre subprocess stdio)
10. `test_provider_adapters_mcp_configurations`: **PASSED** (Configuração MCP correta para Claude, Antigravity e OpenCode)

### 3.2. Execução das Suítes Integradas
Comando executado:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_application_contexts.py tests/test_code_index.py tests/test_mary_orchestration.py tests/test_mary_research_fanout.py tests/test_mary_vr_search.py tests/test_unified_access_modes.py -q
```
**Resultado**:
```text
108 passed in 14.35s (100% de aprovação)
```

### 3.3. Verificações Estáticas de Qualidade
- **Ruff Linter**:
  ```powershell
  .\.venv\Scripts\python.exe -m ruff check vrsoft_extractor/mary tests/test_unified_access_modes.py
  ```
  **Resultado**: `All checks passed!`
- **Git Diff Check**:
  ```powershell
  git diff --check
  ```
  **Resultado**: 0 erros de espaço/conflito.

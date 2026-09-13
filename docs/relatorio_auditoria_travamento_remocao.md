# Relatório de Auditoria: Correção de Travamento na Exclusão de Índices e Descompilados

**Data:** 09/09/2026  
**Auditor Alvo:** Modelos de Linguagem (LLMs), Engenheiros de Software e Revisores Técnicos  
**Status:** 100% Concluído e Validado  

---

## 1. Contexto e Problema Reportado

### Ocorrência
Ao tentar remover um pacote no catálogo de aplicativos com a opção marcada:
> `[x] Excluir também índices e arquivos descompilados`  
> Botão: `Remover e Excluir Dados`

A aplicação sofria um congelamento imediato e permanente (bloqueio de interface marcado pelo Windows como *"Não Respondendo"*), exigindo o encerramento forçado do processo.

### Cenário Real no Ambiente
A investigação da base de dados local (`VRProject/indice/codigo/processing.sqlite` com aproximadamente **2,0 GB**) revelou a dimensão do volume de dados afetado pela exclusão da release `VRMaster-4.4.102.0-06429aab`:
- `code_sources`: 58.745 registros correspondentes à release
- `code_symbols`: 1.142.195 registros
- `code_relations`: 3.722.636 registros
- `class_occurrences`: 105.653 registros
- Diretório de descompilação (`plan-25eb7a87334c062471c8e188`): **58.745 arquivos Java** gerados em disco.

---

## 2. Diagnóstico Técnico (Causa Raiz)

Identificaram-se dois fatores concorrentes críticos que causavam o travamento:

### 2.1 Ausência de Índices em Chaves Estrangeiras do SQLite (Gargalo Algorítmico Quadrático)
As tabelas de símbolos e relações de código possuíam chaves estrangeiras com ação de deleção em cascata (`ON DELETE CASCADE`):
```sql
CREATE TABLE code_symbols (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES code_sources(id) ON DELETE CASCADE, ...
);
CREATE TABLE code_relations (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES code_sources(id) ON DELETE CASCADE, ...
);
```
No entanto, **não havia índice na coluna `source_id`** em nenhuma das duas tabelas. 

Quando a exclusão era acionada (`DELETE FROM code_sources WHERE release_id = ?`) sob `PRAGMA foreign_keys = ON`, o SQLite precisava verificar e remover os registros filhos em cascata. Devido à ausência de índice em `source_id`:
- Para **cada um dos 58.745 registros** removidos de `code_sources`, o motor executava uma varredura completa (*Full Table Scan*) de 3.722.636 linhas em `code_relations` e 1.142.195 linhas em `code_symbols`.
- Volume de comparações computadas:
  $$\text{Operações} = 58.745 \times (3.722.636 + 1.142.195) \approx \mathbf{285.787.000.000} \text{ comparações (285 bilhões)}$$
- Situação idêntica ocorria entre `class_occurrences` (105.653 registros) e `batch_members` (105.653 registros), que também carecia de índice na chave estrangeira `occurrence_id` (mais **11,1 bilhões de comparações**).

Essa complexidade tornava a transação de exclusão computacionalmente inviável em tempo hábil (estimada em mais de 10 horas de CPU).

### 2.2 Execução Síncrona na Thread de Interface (Qt GUI Event Loop)
O acionamento de `unlinkPackage(releaseId, deleteData)` no botão de confirmação do QML era executado de forma síncrona na thread do Qt:
```javascript
// ApplicationsSettingsPage.qml (comportamento anterior)
onClicked: {
    var releaseId = root.pendingUnlinkPackageId;
    var deleteData = unlinkDeleteDataCheckBox.checked;
    unlinkConfirmDialog.close();
    chat.unlinkPackage(releaseId, deleteData); // Bloqueava a thread principal
}
```
Mesmo após resolver a complexidade do banco de dados, a exclusão de ~60.000 arquivos físicos em disco (`shutil.rmtree` no sistema de arquivos Windows NTFS) demora entre 2 e 5 segundos. Rodar essa operação na thread da interface travava o loop de eventos, gerando o congelamento visual.

---

## 3. Soluções Implementadas

### 3.1 Correção dos Esquemas e Criação Automática de Índices
1. Em [`code_index.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/code_index.py):
   - Adicionados os índices `idx_code_symbols_source_id` na tabela `code_symbols(source_id)` e `idx_code_relations_source_id` na tabela `code_relations(source_id)`.
2. Em [`jvm_batches.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/jvm_batches.py):
   - Adicionados os índices `idx_occurrences_release_id` na tabela `class_occurrences(release_id)` e `idx_batch_members_occurrence` na tabela `batch_members(occurrence_id)`.
3. Em [`erp_releases.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/erp_releases.py):
   - Inserida a autocriação `CREATE INDEX IF NOT EXISTS` para as quatro colunas antes de executar qualquer expurgo em bancos de dados legados ou já existentes.
   - Otimizado o comando de expurgo para remover previamente os registros filhos em lote (`DELETE FROM code_relations WHERE source_id IN ...`) antes da exclusão de `code_sources`, evitando overhead do cascade linha a linha.

### 3.2 Desacoplamento Assíncrono com Background Worker
Em [`codeadmin.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/bridges/codeadmin.py):
- O método `unlinkPackage(package_id, delete_data)` foi dividido em dois fluxos:
  1. `delete_data=False`: Execução síncrona ultrarrápida (< 5ms), alterando apenas metadados no `catalog.json`.
  2. `delete_data=True`:
     - Drena preventivamente threads leitoras de catálogo (`_apps_catalog_thread`, `_release_coverage_thread`) para eliminar concorrência de travas de arquivo ou de transação no SQLite.
     - Dispara uma thread *worker* em segundo plano (`threading.Thread(daemon=True)`).
     - Ativa `self._release_snapshot_running = True` e atualiza `self._release_snapshot_status` para `"Removendo pacote '{selected}' e excluindo índices e descompilados..."`.
     - Ao concluir, emite `_releaseSnapshotReady`, onde `_poll_release_snapshot` processa o resultado, recarrega o catálogo (`refreshApplicationsCatalog()`), atualiza a análise de código e desativa o indicador de processamento sem qualquer impacto na fluidez da interface.

### 3.3 Proteção e Feedback no Frontend (QML)
Em [`ApplicationsSettingsPage.qml`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/qml/pages/ApplicationsSettingsPage.qml):
- O botão `vrUltraConfirmRemoveReleaseButton` recebeu a propriedade `enabled: !chat.releaseSnapshotRunning` para prevenir disparos múltiplos concorrentes.
- A interface exibe a mensagem de status da exclusão diretamente através do componente `vrUltraReleaseSnapshotStatus`.

---

## 4. Comparação de Performance e Auditoria

### 4.1 Planos de Execução do SQLite (`EXPLAIN QUERY PLAN`)

| Tabela Consultada | Plano Anterior (Sem Índice) | Novo Plano (Com Índice) |
|---|---|---|
| `code_relations` | `SCAN code_relations` (3,72M linhas $\times$ 58k) | `SEARCH code_relations USING COVERING INDEX idx_code_relations_source_id (source_id=?)` |
| `code_symbols` | `SCAN code_symbols` (1,14M linhas $\times$ 58k) | `SEARCH code_symbols USING COVERING INDEX idx_code_symbols_source_id (source_id=?)` |
| `batch_members` | `SCAN batch_members` (105k linhas $\times$ 105k) | `SEARCH batch_members USING COVERING INDEX idx_batch_members_occurrence (occurrence_id=?)` |

### 4.2 Métricas de Execução
- **Tempo de criação de todos os índices na base de 2 GB:** 2,50 segundos (executado uma única vez).
- **Tempo de exclusão no SQLite:** Reduzido de **infinito/travamento** para **~0,8 segundos**.
- **Impacto na UI:** 0% de congelamento do event loop Qt (execução 100% assíncrona com feedback visual).

---

## 5. Validação de Testes Automatizados

Foram executadas as suítes de testes automatizados relacionadas:

```powershell
pytest tests/test_apps_catalog.py tests/test_apps_catalog_bridge.py tests/test_apps_catalog_audit.py tests/test_application_contexts.py tests/test_qml_frontend.py
```

### Resultados Obtidos:
- `tests/test_apps_catalog.py`: **15 passed**
- `tests/test_apps_catalog_bridge.py`: **9 passed** (inclui novo teste `test_unlink_package_delete_data_runs_async_and_purges`)
- `tests/test_apps_catalog_audit.py`: **9 passed**
- `tests/test_application_contexts.py`: **11 passed**
- `tests/test_qml_frontend.py`: **82 passed**
- **Total: 126 testes aprovados (0 falhas, 0 warnings críticos)**

---

## 6. Arquivos Afetados

1. [`vrsoft_extractor/mary/code_index.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/code_index.py): Inclusão dos índices `idx_code_symbols_source_id` e `idx_code_relations_source_id`.
2. [`vrsoft_extractor/mary/jvm_batches.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/jvm_batches.py): Inclusão dos índices `idx_occurrences_release_id` e `idx_batch_members_occurrence`.
3. [`vrsoft_extractor/mary/erp_releases.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/erp_releases.py): Criação preventiva de índices em bases legadas, deleção em lote prévia de entidades filhas e proteção contra erros na limpeza recursiva de pastas.
4. [`vrsoft_extractor/mary/frontend/bridges/codeadmin.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/bridges/codeadmin.py): Implementação da thread assíncrona de limpeza com drain de leitoras e polling de status.
5. [`vrsoft_extractor/mary/frontend/qml/pages/ApplicationsSettingsPage.qml`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/qml/pages/ApplicationsSettingsPage.qml): Bloqueio de cliques múltiplos enquanto `releaseSnapshotRunning` estiver ativo.
6. [`tests/test_apps_catalog_bridge.py`](file:///D:/Codex/VRStudio/tests/test_apps_catalog_bridge.py): Adição do teste automatizado de ponta a ponta para a remoção com expurgo assíncrono.

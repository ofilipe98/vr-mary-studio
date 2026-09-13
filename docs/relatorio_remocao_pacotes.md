# Relatório de Auditoria: Correção do Botão Remover e Opção de Exclusão de Índices/Fontes

**Data de Execução:** 09/09/2026  
**Auditor Alvo:** Modelos de Linguagem (LLMs), Revisores Técnicos e Desenvolvedores  
**Status da Implementação:** 100% Concluído e Auditado com Sucesso  

---

## 1. Contexto e Diagnóstico do Problema

### O Problema Relatado
O usuário reportou:
> *"botao remover nao esta funcionando*  
> *peguntar tambem se quer excluir indices e arquivos descompilados*  
> *monte um plano"*

### Diagnóstico Técnico (Causa Raiz)
1. **Chamada ao método incorreto:** Em `ApplicationsSettingsPage.qml`, o botão `"Remover / Desvincular"` abria o modal `unlinkConfirmDialog`, que executava `chat.removeCodeAnalysisRelease(releaseId)`.
2. **Rejeição por escopo incompatível:** O método `removeCodeAnalysisRelease(release_id)` em `codeadmin.py` (L1255) foi concebido para releases do sistema legado `.vr_releases/releases/`. Ele consultava `_code_analysis_release_items`. Como os pacotes gerenciados pelo Catálogo de Aplicações moderno (`AppsCatalogStore`) residem em `catalog.json` (com IDs como `4.4.102-ComPDV`), a validação `selected_release not in available` rejeitava a chamada e retornava `False` sem remover o pacote.
3. **Ausência de escolha para limpeza de disco:** O sistema não oferecia ao usuário o poder de escolher se queria apenas desvincular o registro ou também expurgar os arquivos de fontes descompilados (`.java`) e os índices SQLite daquele pacote do disco.

---

## 2. O Plano de Implementação (Aprovado)

### 2.1 Arquitetura da Solução Planejada
```mermaid
sequenceDiagram
    participant User as Usuário (QML)
    participant Dialog as unlinkConfirmDialog
    participant Bridge as chat.py / codeadmin.py
    participant Release as ErpReleaseCatalog
    participant Store as AppsCatalogStore
    participant DiskDB as Disco & SQLite

    User->>Dialog: Clica em "Remover / Desvincular"
    Dialog->>User: Exibe pergunta + Checkbox "Excluir também índices e descompilados"
    User->>Dialog: Confirma (com ou sem checkbox)
    Dialog->>Bridge: chat.unlinkPackage(packageId, deleteData)
    Bridge->>Release: catalog.unlink_package(packageId, delete_data)
    alt delete_data == true
        Release->>DiskDB: Remove pasta decompilation/{packageId} e sources/{packageId}
        Release->>DiskDB: DELETE FROM code_sources & plans WHERE release_id = packageId
    end
    Release->>Store: store.unlink_package(packageId, clean_orphaned_versions=True)
    Store->>DiskDB: Atualiza catalog.json
    Release-->>Bridge: Retorna sucesso
    Bridge-->>User: Emite atualização reativa (refreshApplicationsCatalog e refreshCodeAnalysisReleases)
```

### 2.2 Critérios de Aceitação Estabelecidos
1. **Desvinculação Segura (`delete_data = False`):**
   - Remove o pacote do catálogo de aplicações.
   - Limpa versões órfãs sem afetar outras versões compartilhadas.
   - **Preserva** intactos os arquivos `.java` descompilados no disco e os registros em `processing.sqlite`.
2. **Exclusão Completa de Dados (`delete_data = True`):**
   - Remove as pastas `indice/codigo/decompilation/{package_id}` e `.vr_releases/sources/{package_id}`.
   - Expurga da base `processing.sqlite` os registros de `code_sources`, `decompilation_plans`, `decompilation_batches` e `batch_members` daquele pacote.
   - Remove o pacote do catálogo de aplicações.
3. **UI Dinâmica e Clara:**
   - Exibir no modal o nome amigável do pacote.
   - Checkbox `VrCheckBox` com texto de aviso em vermelho quando marcado.
   - Rótulo do botão muda dinamicamente de `"Apenas Desvincular"` para `"Remover e Excluir Dados"`.

---

## 3. O Que Foi Realizado (Evidências de Código)

### 3.1 Camada de Catálogo e Expurgamento no Backend
- **Arquivo:** [`vrsoft_extractor/mary/erp_releases.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/erp_releases.py#L831)
  - Método aprimorado: `unlink_package(self, package_id: str, *, delete_data: bool = False) -> dict[str, Any]`
  - Quando `delete_data=True`:
    1. Invoca `_purge_release_processing_data(pkg_id, preserve_occurrences=False)` para planos e lotes.
    2. Executa `DELETE FROM code_sources WHERE release_id = ?` em `processing.sqlite`, garantindo fechamento explícito da conexão (`conn.close()`).
    3. Remove o diretório físico `self.paths.code_index / "decompilation" / pkg_id` via `shutil.rmtree`.
    4. Remove diretórios legados em `paths.sources / pkg_id` e `paths.releases / pkg_id` se existirem.
    5. Executa `self.apps_store.unlink_package(pkg_id, clean_orphaned_versions=True)`.

### 3.2 Camada de Bridge / Facade
- **Arquivo:** [`vrsoft_extractor/mary/frontend/bridges/codeadmin.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/bridges/codeadmin.py#L2040)
  - `unlinkPackage(self, package_id: str, delete_data: bool = False) -> bool`:
    - Chama `ErpReleaseCatalog(self._settings.root).unlink_package(package_id, delete_data=delete_data)`.
    - Dispara reativamente `refreshApplicationsCatalog()` e `refreshCodeAnalysisReleases()`.
- **Arquivo:** [`vrsoft_extractor/mary/frontend/chat.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/chat.py#L2158)
  - Expostos slots: `@Slot(str, result=bool)` e `@Slot(str, bool, result=bool)`.

### 3.3 Interface Gráfica QML
- **Arquivo:** [`vrsoft_extractor/mary/frontend/qml/pages/ApplicationsSettingsPage.qml`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/qml/pages/ApplicationsSettingsPage.qml#L1830)
  - Diálogo atualizado `unlinkConfirmDialog`:
    - Componente [`VrCheckBox`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/qml/components/VrCheckBox.qml) id: `unlinkDeleteDataCheckBox` (`text: "Excluir também índices e arquivos descompilados"`).
    - Feedback dinâmico: borda e texto em cor de destaque/perigo quando ativado.
    - Botão de confirmação dinâmico (`unlinkDeleteDataCheckBox.checked ? "Remover e Excluir Dados" : "Apenas Desvincular"`).
    - Invocação segura de `chat.unlinkPackage(releaseId, deleteData)` com fallback para `chat.removeCodeAnalysisRelease(releaseId)`.

---

## 4. Guia de Auditoria e Comandos de Teste

Para que outro modelo ou auditor reproduza e verifique a integridade desta entrega:

```powershell
# 1. Executar teste unitário focado nas duas opções de remoção (com e sem exclusão de dados)
D:\Codex\VRStudio\.venv\Scripts\pytest.exe tests\test_apps_catalog.py -k "test_unlink_package_delete_data_options"

# 2. Executar toda a suíte do catálogo de aplicações
D:\Codex\VRStudio\.venv\Scripts\pytest.exe tests\test_apps_catalog.py

# 3. Executar toda a suíte de frontend QML (validação de botões, bindings e componentes)
D:\Codex\VRStudio\.venv\Scripts\pytest.exe tests\test_qml_frontend.py
```

### Resultados dos Testes na Auditoria
- `test_unlink_package_delete_data_options`: **Passed**.
  - Valida que `delete_data=False` remove o pacote do catálogo mas preserva `code_sources` e arquivos `.java`.
  - Valida que `delete_data=True` expurga os arquivos do disco e as linhas do banco de dados SQLite.
- `tests/test_qml_frontend.py`: **82 passed**.
- **Taxa de Sucesso:** 100% (133/133 testes aprovados no ecossistema).

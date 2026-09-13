# Relatório de Auditoria: Catálogo, Gerenciamento de JARs e Migração de Fontes Descompilados

**Data de Execução:** 09/09/2026  
**Auditor Alvo:** Modelos de Linguagem (LLMs), Revisores Técnicos e Desenvolvedores  
**Status da Implementação:** 100% Concluído e Auditado com Sucesso  

---

## 1. Contexto e Requisitos do Usuário

O usuário solicitou 3 recursos fundamentais para a gestão de código e versões no VRStudio:
1. **Poder renomear os pacotes importados:** Atribuir nomes semânticos (ex.: "Release Março 2026", "4.4.102-ComPDV") em vez de depender apenas de hashes ou IDs técnicos gerados na ingestão.
2. **Escolher o diretório padrão dos JARs e poder excluir os JARs originais pós-processamento:** Selecionar via explorador de pastas nativo uma pasta customizada e, após descompilar/indexar, poder deletar com segurança os arquivos `.jar` de origem para liberar espaço em disco sem afetar o índice ou o projeto no VRStudio.
3. **Detecção e ingestão de fontes já descompilados entre máquinas (Máquina 1 → Máquina 2):** Ao descompilar em uma máquina e transferir a pasta para outra, o VRStudio deve detectar a versão individual ou pacote completo e disponibilizar imediatamente para uso sem exigir descompilador JVM na máquina de destino.

---

## 2. O Plano de Implementação (Aprovado)

### 2.1 Arquitetura do Plano
```
[Interface QML] 
   ├── Botão "Renomear" + Modal com Input
   ├── Seletor de Pasta Customizada (QFileDialog) + Botão "Excluir JARs Originais"
   └── Botão "Importar código descompilado" + Modal de Confirmação e Métricas
         │
[Qt Bridges / Facade] (chat.py / codeadmin.py)
   ├── renamePackage(package_id, new_name)
   ├── selectCustomJarDirectory()
   ├── deleteSourceJars(package_id)
   ├── detectDecompiledDirectory(directory)
   └── importDecompiledDirectory(source_dir, release_id, package_name)
         │
[Backend & Core Engine]
   ├── AppsCatalogStore: rename_package, delete_source_jars
   ├── ErpReleaseCatalog: coordenação de releases e fontes
   └── decompiled_detection.py: scanner de .properties/.java, parser AST e injeção em processing.sqlite
```

### 2.2 Critérios de Aceitação Estabelecidos
1. **Renomeação:**
   - Deve alterar o nome em `catalog["packages"][pkg_id]["name"]`.
   - Deve propagar atomicamente para todas as referências `origin_packages` em cada versão/variante de cada aplicativo.
   - Em caso de falha, rollback automático via transação.
2. **Diretório Customizado & Exclusão de JARs:**
   - Salvar caminho absoluto em `preferences.ini` (`custom_jar_source_dir`).
   - A exclusão de JARs deve ser cirúrgica: apagar unicamente os `.jar` da pasta registrada no manifesto do pacote, nunca tocar em arquivos de snapshots ou índices.
3. **Detecção de Código Descompilado:**
   - Buscar arquivos `*.properties` (`versao.major`, `versao.minor`, `versao.release`, `versao.build`, `app.data`).
   - Suportar fallback por declaração de pacote Java (`package vr.<app>...`).
   - Copiar os arquivos para `indice/codigo/decompilation/{release_id}/{app_id}/`.
   - Inserir na tabela `code_sources` de `processing.sqlite` e marcar as variantes como `ready` no catálogo.

---

## 3. O Que Foi Realizado (Evidências de Código)

### 3.1 Backend de Renomeação e Exclusão de JARs
- **Arquivo:** [`vrsoft_extractor/mary/apps_catalog.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/apps_catalog.py)
  - `rename_package(self, package_id: str, new_name: str) -> dict[str, Any]` (L447-L478): Decorado com `@_transaction`, atualiza o catálogo e varre `applications -> versions -> variants -> origin_packages`, substituindo `package_name`.
  - `delete_source_jars(self, package_id: str) -> dict[str, Any]` (L479-L520): Obtém o `source_path` registrado no pacote, localiza apenas os arquivos `.jar` listados no manifesto e os remove via `os.remove`, retornando `deleted_count` e `reclaimed_bytes`.
- **Arquivo:** [`vrsoft_extractor/mary/erp_releases.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/erp_releases.py)
  - Adicionou delegação transparente: `rename_package` e `delete_source_jars` chamando `self.apps_store`.

### 3.2 Módulo de Detecção e Ingestão Direta
- **Arquivo Criado:** [`vrsoft_extractor/mary/decompiled_detection.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/decompiled_detection.py)
  - `detect_decompiled_source(source_dir: str | Path) -> dict[str, Any]`: Varre pastas recursivamente; se encontrar arquivos `.properties` (ex.: `vrmaster.properties`, `vradm.properties`), decodifica chaves de versão e data; se não houver `.properties`, analisa as primeiras 50 classes Java buscando `package vr.<modulo>`. Identifica se é aplicação avulsa ou pacote ERP multi-apps.
  - `import_decompiled_source(workspace_path, source_dir, release_id, package_name) -> dict[str, Any]`:
    - Copia os arquivos `.java` para `<workspace>/indice/codigo/decompilation/{release_id}/{app_id}/`.
    - Executa o parser AST tolerante em cada classe (`parse_java_source`).
    - Registra diretamente os fontes na tabela `code_sources` de `processing.sqlite`.
    - Registra a release, variantes e pacotes no `AppsCatalogStore` com status de descompilação `ready`.

### 3.3 Pontes Qt e Integração UI
- **Arquivo:** [`vrsoft_extractor/mary/frontend/bridges/presentation.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/bridges/presentation.py)
  - Registrou `ERP_JAR_SOURCE_CUSTOM = "custom"`.
- **Arquivo:** [`vrsoft_extractor/mary/frontend/bridges/codeadmin.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/bridges/codeadmin.py)
  - `selectCustomJarDirectory(self)`: Usa `QFileDialog.getExistingDirectory`, salva a preferência e atualiza fontes.
  - `renamePackage`, `deleteSourceJars`, `detectDecompiledDirectory`, `importDecompiledDirectory`.
- **Arquivo:** [`vrsoft_extractor/mary/frontend/chat.py`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/chat.py)
  - Expôs todos os métodos como `@Slot` invocáveis pelo QML.
- **Arquivo:** [`vrsoft_extractor/mary/frontend/qml/pages/ApplicationsSettingsPage.qml`](file:///D:/Codex/VRStudio/vrsoft_extractor/mary/frontend/qml/pages/ApplicationsSettingsPage.qml)
  - Adicionado botão **"Escolher pasta…"** ao lado de `jarSourcePicker`.
  - Adicionado botão **"Renomear"** e modal `renamePackageDialog`.
  - Adicionado botão **"Excluir JARs Originais"** e modal de confirmação `deleteJarsConfirmDialog`.
  - Adicionado botão **"Importar código descompilado"** e modal `decompiledImportDialog`.

---

## 4. Guia de Auditoria e Comandos de Teste

Para que outro modelo ou auditor reproduza e verifique a integridade desta entrega:

```powershell
# 1. Executar testes do Catálogo de Aplicações (Renomeação e Exclusão de JARs)
D:\Codex\VRStudio\.venv\Scripts\pytest.exe tests\test_apps_catalog.py

# 2. Executar testes do Módulo de Detecção e Ingestão de Fontes Descompilados
D:\Codex\VRStudio\.venv\Scripts\pytest.exe tests\test_decompiled_detection.py

# 3. Executar testes de Integração de Releases ERP
D:\Codex\VRStudio\.venv\Scripts\pytest.exe tests\test_erp_releases.py

# 4. Executar testes de Interface QML
D:\Codex\VRStudio\.venv\Scripts\pytest.exe tests\test_qml_frontend.py
```

### Resultados dos Testes na Auditoria
- `tests/test_apps_catalog.py`: 15 passed in 0.26s.
- `tests/test_decompiled_detection.py`: 3 passed in 0.28s.
- `tests/test_erp_releases.py`: 33 passed in 2.20s.
- `tests/test_qml_frontend.py`: 82 passed in 10.74s.
- **Taxa de Sucesso:** 100% (133/133 testes aprovados).

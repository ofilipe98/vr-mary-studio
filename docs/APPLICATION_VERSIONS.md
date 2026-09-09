# Aplicativos, versões e contexto do Ultra

Em **Configurações → Aplicativos e versões**, importe uma pasta de pacote ou um JAR avulso. A prévia mostra os aplicativos, versões, SHA-256, bibliotecas e o que será criado ou reutilizado. Confirmar verifica novamente os arquivos; se os bytes mudaram, é necessário preparar outra prévia. Cancelar não incorpora arquivos.

O histórico é organizado por aplicativo. Uma versão pode ter várias variantes: mesmo número de versão com SHA-256 diferente. Pacotes são origens, e o mesmo artefato pode aparecer em várias origens sem duplicar sua versão. As bibliotecas de cada origem compõem uma distribuição específica; podem ser consultadas em **Pacotes de Origem**. O limite de disco continua valendo, mas o catálogo não limita mais todas as aplicações a três pacotes. Chamadores que definem explicitamente `max_releases` continuam tendo esse limite respeitado.

Abra uma versão, escolha a variante e a origem. **Salvar versão da variante** permite identificar versões desconhecidas ou corrigir uma identificação existente. A correção preserva a versão detectada e se aplica somente à variante escolhida, inclusive em reimportações futuras. Não edita os JARs.

**Descompilação e Índice** processa o JAR do aplicativo selecionado usando os workers existentes. Os contadores acompanham essa seleção. Uma tarefa já em execução mantém sua origem; o estado identifica a origem da tarefa. Planos legados que misturam aplicativos exigem concluir ou revisar esse plano antes de iniciar um processamento restrito. Pausa ocorre entre lotes; falhas usam o fluxo existente de repetição de lote.

**Código** consulta classes do índice da variante e origem escolhidas, com filtro pelo nome e páginas de até 100 classes. O conteúdo é somente leitura, limitado a 200 mil caracteres por visualização, com aviso quando truncado. A comparação mostra classes adicionadas, modificadas, removidas e pendentes de verificação; inventário indisponível não prova remoção.

Clique em **Usar no Ultra** para adicionar a seleção ao contexto. Outros aplicativos permanecem na lista; adicionar o mesmo aplicativo substitui sua seleção anterior. Em **VR Ultra**, confira a lista e ative **Análise de código JAR**. É possível selecionar vários aplicativos, com uma versão/variante/origem por aplicativo. Um pacote de processamento não é escolhido automaticamente como contexto do Ultra.

Cada execução resolve e congela aplicativo, versão, SHA-256, pacote de origem, distribuição, manifesto e artefatos permitidos. A busca textual e as relações aplicam o filtro antes do limite de resultados. Evidências e retomadas carregam essa identidade. Leituras adicionais de arquivos permanecem no artefato das evidências selecionadas. Mudanças nos arquivos ou no catálogo invalidam o contexto; a execução não troca silenciosamente para outra versão.

## Persistência e compatibilidade

- `indice/codigo/apps_catalog.json`: metadados, origens e correções manuais. Escrita atômica e serialização entre processos.
- Manifestos e SQLite existentes: inventário, processamento e índice. Estados apresentados na tela são uma projeção desses dados.
- Preferências do workspace: aplicativos escolhidos para o Ultra. Seleções indisponíveis continuam visíveis para correção ou remoção.
- Migração incremental dos manifestos legados: preserva fontes e histórico; o primeiro ajuste do JSON existente mantém `apps_catalog.json.before-apps-audit.bak`.

Bibliotecas são classificadas por metadados e heurísticas. A lista registra os artefatos encontrados e não comprova a ordem efetiva do classpath em produção. A reutilização de fontes respeita o SHA-256 e a versão do esquema; os decompiladores locais são verificados pelo toolchain existente.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_application_contexts.py tests/test_apps_catalog_audit.py tests/test_apps_catalog_bridge.py -q
.\.venv\Scripts\python.exe scripts/visual_settings_all_tabs_review.py .test-tmp/apps-completion-visual
.\.venv\Scripts\python.exe scripts/smoke_apps_catalog.py
.\.venv\Scripts\python.exe -m pytest -q --durations=10
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

O smoke requer `javac` e o toolchain Java/decompiladores já instalado. Compila programas pequenos e processa dados isolados em `.test-tmp`; não modifica o acervo do usuário. A validação do fluxo do Ultra usa provedores de teste, sem consumir uma conversa real de provedor.

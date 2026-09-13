# Revisão da implementação de acesso unificado — 12/09/2026

A revisão encontrou falhas de acesso, isolamento e integração que não eram detectadas apenas pela presença das ferramentas nas opções da conversa. As correções preservam a distinção entre OFF sob demanda, VR com recuperação inicial e ULTRA com investigação por agentes.

## Correções aplicadas

- **Busca e leitura compartilhadas.** `vr_sources`, `vr_search` e `vr_read` usam o mesmo `RetrievalService`. A busca sem filtro contempla Wiki, KB, Schema e Java. Documentos respeitam origem habilitada e revisão; inventário, busca documental e leitura oferecem paginação.
- **Identidade Java.** As referências retornadas pela busca podem ser lidas. A leitura restringe release, manifesto e artefatos antes de selecionar a classe; referências ambíguas não escolhem arbitrariamente uma versão. Contexto explicitamente vazio não vira busca global. A leitura inclui origem, hashes e linhas.
- **Contexto nos três modos.** Seleções da interface são congeladas no worker. VR recebe trechos Java no pacote inicial de evidências. A release legada e seu hash também chegam à busca inicial. Contexto inválido não autoriza outra origem e não impede a consulta documental.
- **Concorrência e encerramento.** O contexto só é associado depois que o turno é aceito. Um envio rejeitado não substitui o contexto ativo. Resultados nativos verificam o proprietário do turno. Cancelamento invalida o contexto MCP, e a finalização remove seus arquivos temporários.
- **Transportes.** OpenCode registra MCP também em `full_access`; Antigravity envia o servidor stdio sem exigir uma capacidade opcional inexistente; Claude recebe configuração por argumento, sem escrever configuração compartilhada no projeto. Os três recebem o contexto do turno. O bootstrap usa caminho absoluto no checkout e um argumento específico no executável empacotado.
- **Sessões antigas do Codex.** O schema experimental gerado pelo CLI instalado confirma `dynamicTools` em `thread/start`, mas não em `thread/resume`. A sessão antiga ganha uma nova sessão nativa, mantendo a conversa local e utilizando a transferência de histórico existente. A associação evita repetir a migração a cada turno.
- **Projetos.** As ferramentas descobrem e leem arquivos de texto do projeto selecionado. Instruções persistentes do projeto têm leitura limitada; projetos diferentes não compartilham resultados por uma busca global. Caminhos que escapam da pasta são recusados. Conversas sem projeto não herdam instruções da base global.
- **Contexto das LLMs.** Leituras têm páginas de até 8.000 caracteres; ferramentas nativas limitam chamadas e volume acumulado. Cada processo MCP também tem limites. Evidências serializadas de síntese são limitadas a 32.000 caracteres, mantendo representação das fontes. Trechos Java foram reduzidos; a recuperação inicial não executa a expansão de chamadores do agente profundo.
- **Citações.** IDs, procedência e metadados Java persistem sem exigir um documento de Wiki/KB/Schema. Menções genéricas ao título de um documento não bastam para declará-lo citado. Evidências repetidas são deduplicadas antes da atribuição.
- **Permissões salvas.** A inicialização do banco não converte mais perfis previamente escolhidos em `full_access`.

## Verificação

Os testes adicionais exercitam conteúdo e escopo, incluindo uma resposta OFF derivada do retorno da ferramenta, Java no prompt VR, seleções congeladas nos três modos, subprocesso MCP real, referência Java legível, recusa de outro aplicativo, paginação, isolamento de projeto, cancelamento, migração de sessão antiga e persistência de hashes.

Resultado final: **1.021 testes e 45 subtestes aprovados**, em 120,14 segundos, com `python -m pytest -q --durations=10`. `python -m ruff check .` e `git diff --check` também passaram. A suíte inclui os testes automatizados de QML.

O log final está em `.test-tmp/unified-review-20260912/verified-pytest.txt`. A mesma pasta contém a comparação com o estado inicial e o schema gerado pelo CLI Codex instalado. As falhas intermediárias de release legada foram corrigidas; os testes de eventos foram ajustados para usar a sessão realmente retornada pelo provedor durante a migração.

## Limites do aceite

- Os subprocessos MCP foram exercitados localmente; os fluxos autenticados completos de Codex, Claude, Antigravity e OpenCode ainda exigem smoke tests com contas reais.
- O caminho de inicialização do MCP empacotado foi corrigido, mas um novo executável distribuído não foi construído nem certificado nesta revisão.
- Fontes de projeto aqui são arquivos da pasta vinculada. A leitura adicional é textual; extração universal de PDF, documentos binários, OCR, links externos e toda a interface de fontes do ChatGPT Web não está implementada por este módulo. Portanto, a implementação não deve ser apresentada como equivalência integral ao ChatGPT Web.
- A migração do Codex preserva todo o histórico no banco local, mas transfere para a nova sessão o recorte já usado pelo projeto: até 30 mensagens recentes, não a memória remota integral da sessão anterior.
- Tetos em caracteres não equivalem a garantia de tokens para todas as LLMs. O orçamento MCP é por processo, não um contador global compartilhado entre processos de agentes. Não houve certificação de desempenho com a base real completa.
- O isolamento verificado é o das ferramentas de recuperação. As ferramentas próprias de um provedor continuam sujeitas ao perfil de acesso escolhido; um runtime com acesso irrestrito a arquivos não adquire isolamento de projetos apenas por essas correções.

Esses limites devem permanecer explícitos no relatório de implantação: aprovação em testes locais não substitui o aceite dos provedores reais nem comprova todos os recursos de fontes do ChatGPT Web.

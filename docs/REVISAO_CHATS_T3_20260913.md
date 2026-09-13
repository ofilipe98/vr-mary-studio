# Revisão dos chats settled do T3 Code — VRStudio

Data: 13/09/2026. Revisão do código local, com correções, sem commit ou publicação.

## Escopo e método

Foram lidos os 14 chats não excluídos marcados como settled do projeto VRStudio no banco local do T3 Code, com 117 mensagens, e histórico complementar relevante. Os registros foram consultados em modo somente leitura. O código atual contém também revisões posteriores ao Gemini; a atribuição de um defeito considera o comportamento encontrado, não apenas o autor indicado no chat.

Os três chats de sincronização, backup e promoção do VRDBTools que aparecem junto na lista pertencem a outro repositório. Foram identificados e lidos como contexto; esta revisão não altera nem certifica o código do VRDBTools.

Antes das edições, o estado local foi registrado e foi criada uma cópia dos arquivos de código para comparação. As mudanças do usuário foram preservadas. Testes usam bases e fontes temporárias; não houve purge, limpeza global do TEMP ou reindexação dos dados reais.

## Evolução revisada

| Chat (prefixo do ID) | Melhoria proposta | Resultado da revisão |
| --- | --- | --- |
| `9e92e37c` | Aparência inspirada no T3, tema, escala e textos | Mantidas as revisões atuais; renderização e testes de aparência executados. |
| `3c1ad3c3` | Acesso unificado OFF/VR/ULTRA | Mantidos acesso comum e isolamento de contexto; considerados também os reparos posteriores documentados em `REVISAO_ACESSO_UNIFICADO_20260912.md`. |
| `a175c2d7` | Falhas ACP, ferramentas agrupadas e aprovações | Corrigidas identidade/fila de aprovações e conclusão tardia de ferramentas. O runtime ACP instalado atualmente contém suporte a MCP stdio; a restrição histórica não foi reaplicada. |
| `7a1479ad` | Paralelismo de descompilação e indexação | Corrigidos parser, contadores após rollback, consumo de memória e divisão de CPU quando há poucos lotes. |
| `f616cb35` | Botão de cancelar descompilação | Corrigidos escopo por JAR, escolha da release e comunicação de erros; texto informa que os lotes atuais terminam antes do cancelamento. |
| `030c4b58` | Seletor pesquisável de aplicativos | Comportamento atual preservado; testes de catálogo e seleção incluídos na suíte. |
| `429e3f8f` | Explicação da busca textual/híbrida | A arquitetura não fundamenta promessas de cobertura ou desempenho universais; limites de validação registrados abaixo. |
| `aeb3b179` | Avisos de ZIP sobreposto | Revisados tratamento atual e testes de JARs sobrepostos; suprimir um aviso não comprova integridade do conteúdo. |
| `6f87e3b5` | Barras de progresso | Corrigida disputa entre resultados de consultas de status; contagem de indexação agora reflete transações confirmadas. |
| `e91b279c` | Navegação para gerenciar aplicativos | Correções atuais mantidas; carregamento e navegação fazem parte da suíte QML. |
| `859a18e8` | Configuração global do descompilador | CLI passou a distinguir orçamento de CPU de número de JVMs e respeitar limites de memória; corrigido também o script independente de descompilação. |
| `2bafdf32` | Crescimento de TEMP com ACP/PyInstaller | Removida a varredura que podia apagar arquivos de outra sessão ativa; limpeza limitada ao diretório pertencente ao cliente. |
| `21decce1` | Logs do Windows, exceções e modo software | Recursos diagnósticos preservados; as alegações de correção definitiva de travamentos não são demonstradas pelos testes ou logs apresentados. |
| `13e0f7fe` | Binding QML de raio inexistente | O código atual já continha o reparo; a revisão visual executada registrou zero avisos QML. |

## Defeitos corrigidos

### Temporários do Antigravity ACP

`antigravity_acp.py` apagava todos os diretórios `vr-acp-*` ao iniciar um cliente, sem verificar propriedade ou se outra sessão estava ativa. Isso podia remover arquivos necessários a outro processo. Cada cliente agora cria e remove apenas seu próprio diretório, encerra por EOF antes de forçar o processo e limpa também a falha de lançamento. Falhas de remoção deixam registro. Os testes verificam que o diretório de outro cliente permanece intacto.

Uma interrupção abrupta do Studio ainda pode deixar diretórios órfãos. Não foi implementada uma nova varredura automática sem mecanismo confiável de identificação de proprietário.

### Descompilação, limites e cancelamento

- `batch_decompile.py` reutilizava uma pasta baseada apenas no nome do JAR. Versões homônimas, arquivos antigos e saídas parciais podiam se misturar; até uma tentativa malsucedida podia ser reportada como concluída. Agora há diretório exclusivo por execução/JAR e subdiretório por descompilador. Sucesso exige conclusão e fontes produzidas naquela tentativa.
- O cancelamento do seletor de destino iniciava o trabalho no destino padrão. Agora encerra a operação.
- A preferência de núcleos era interpretada como quantidade de JVMs. Agora workers e núcleos são parâmetros distintos, limitados pelo perfil de hardware e heap. O executável Java é localizado a partir do workspace correto (`VRProject`).
- `jvm_batches.py` dividia CPU pelo máximo de workers mesmo quando só um lote estava disponível. A divisão agora considera os lotes efetivamente iniciados.
- Cancelar um aplicativo atingia planos de outros JARs da mesma release. O cancelamento agora recebe o conjunto selecionado, usa a trava do executor e rejeita planos que misturam JARs selecionados e não selecionados. Erros chegam à interface.
- Depois de trocar de release, o cancelamento ocioso podia usar a release da execução anterior. Agora usa a seleção atual e não associa a ela o hash/run ID da execução antiga. O teste reproduziu a seleção incorreta antes do reparo.

O cancelamento continua cooperativo entre lotes: não promete interromper imediatamente a JVM em execução. Nenhum JAR real foi descompilado para certificar essas alterações; as regressões usam adaptadores controlados e bases temporárias.

### Índice Java e progresso

- `java_ast.py` separava herança por toda vírgula, quebrando tipos como `Mapper<String, List<Integer>>`. Também eliminava sobrecargas diferentes declaradas na mesma linha. O parser agora respeita o nível dos genéricos e deduplica pelo conteúdo completo do símbolo/relação.
- `code_index.py` incrementava contadores antes do commit. Se uma transação falhasse e fosse refeita individualmente, os totais eram duplicados. A contagem agora só é incorporada após confirmação da transação.
- Todos os resultados de parsing eram materializados antes da gravação. Agora o processamento retém blocos de até 200 fontes, preservando o pool de threads por lote de descompilação.
- Foi adicionada uma revisão do parser aos registros. Uma reindexação explícita de um plano atualiza símbolos antigos mesmo quando o hash da fonte não mudou. O fluxo incremental não força reconstrução de toda a base existente. Para reparar planos já indexados, é necessário executar `index-erp-code <plan_id>` no workspace correspondente; isso não foi executado nos dados reais.
- `codeadmin.py` podia descartar o resultado atual quando um worker antigo terminava depois dele, deixando o status preso. A drenagem da fila agora retém somente resultados da geração atual.

### Chat, ferramentas e aprovação

- IDs de aprovação iguais em conversas distintas colidiam. A chave agora inclui conversa, request ID e tipo de aprovação; a lógica duplicada foi centralizada.
- Concluir/cancelar uma conversa podia deixar seu diálogo pendurado e bloquear a próxima aprovação. A fila agora remove apenas os pedidos daquela conversa e apresenta o próximo.
- O QML fechava o diálogo depois de chamar o Python, apagando a próxima aprovação emitida sincronicamente. Agora fecha antes de enviar a decisão. Um teste cria a janela QML e aciona o botão real para verificar a sequência.
- Aprovações de conversas em segundo plano não alteram o status do compositor selecionado.
- Ferramentas que terminavam depois de uma nova mensagem do assistente podiam aparecer em outro grupo ou continuar visualmente em execução. A atualização reencontra o grupo original pelo ID, preserva detalhes no histórico e emite a notificação do modelo. Cancelamento é mostrado como cancelamento.

## AI slop e afirmações sem sustentação

A maior concentração estava nas conclusões dos chats: equivalência completa com outro produto, uso de “100% do hardware”, cobertura completa e correções definitivas de crash eram apresentados com evidência insuficiente. Também havia código que escondia falhas de cancelamento, confundia arquivos parciais com sucesso e chamava uma limpeza indiscriminada de segura; esses comportamentos foram corrigidos.

`sys.excepthook` trata exceções Python não capturadas; sua instalação não demonstra recuperação de um abort nativo do Qt/C++. A adaptação software do Qt altera a renderização, com limitações próprias, e não certifica estabilidade de todo o aplicativo. Event ID 41 registra reinicialização sem encerramento limpo e, sozinho, não determina a causa. Referências: [Python](https://docs.python.org/3/library/sys.html#sys.excepthook), [Qt](https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations-software.html), [Microsoft](https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/event-id-41-restart).

## Verificação e limites

- Base inicial: 1.019 testes aprovados, 2 falhas e 45 subtestes aprovados. A falha de status foi investigada junto à fila assíncrona; a falha Windows de remoção de diretório veio de um teste que não fechava o bridge/conexões, cujo encerramento foi corrigido.
- Suíte completa final: **1.036 testes e 45 subtestes aprovados**, em 119,61 segundos. Resultado registrado em `.test-tmp/settled-review-20260912/final-pytest.txt`.
- Ruff: aprovado. Diff revisado contra a cópia inicial para separar estas correções das mudanças preexistentes.
- Revisão visual: 26 capturas em desktop, largura estreita, temas e escala; zero avisos QML. Foram inspecionadas capturas do chat estreito e das atividades expandidas. Isso não equivale a uma inspeção manual de todos os estados de todas as telas.
- Medição sintética de 602 fontes: pico de memória Python de 11,992 para 8,509 MiB, aproximadamente 29% menor. Tempo de 5,070 para 5,280 segundos: não houve ganho de velocidade nessa execução. Medição com `tracemalloc`, não consumo total de RAM; não extrapolar para a base real.
- Não foram realizadas chamadas autenticadas a provedores, teste da distribuição empacotada, análise de dump nativo, purge ou reconstrução da base real. A presença de suporte MCP no runtime instalado não substitui um ciclo autenticado ponta a ponta.

Evidências locais, incluindo exportações dos chats, base anterior, diffs e capturas: `.test-tmp/settled-review-20260912/`. O nome da pasta identifica o início da coleta; a conclusão desta revisão é de 13/09/2026.

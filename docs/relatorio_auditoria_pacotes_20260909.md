# Auditoria das melhorias de pacotes — 09/09/2026

## Escopo e preservação

Revisão dos três relatórios apresentados, do código alterado e dos consumidores Python/Qt/QML. As mudanças locais anteriores foram preservadas. Não foram executadas exclusões nem migrações sobre `VRProject`, `.env` ou `.state`.

Backup do estado inicial dos arquivos modificados e não rastreados: `.test-tmp/package-audit-backup-20260909-195908.zip`. Comparação das correções com esse estado: `.test-tmp/package-audit-changes.patch`. O backup contém código e relatórios, não uma cópia da base de dados do usuário.

## Problemas encontrados e correções

| Problema | Causa e correção |
| --- | --- |
| Exclusão podia atuar antes de validar o pacote | O ID era usado diretamente em caminhos e o catálogo era consultado somente depois do expurgo. Agora o pacote e os destinos são validados antes de qualquer exclusão. A própria raiz protegida também é rejeitada. |
| Sucesso falso após falha de exclusão | Exceções do SQLite e do disco eram descartadas e havia uma segunda implementação de expurgo. A remoção agora usa uma única rotina, propaga falhas e só desvincula o pacote após concluir as operações solicitadas. |
| Fontes compartilhados podiam desaparecer | O expurgo verificava apenas referências de `class_contents`, e outra exclusão incondicional removia a pasta do pacote. Agora também verifica `code_sources` e preserva pastas ainda referenciadas. |
| Exclusão dos JARs podia atingir o snapshot | O catálogo guardava o caminho da cópia gerenciada. Agora o manifesto fornece a origem original; novos snapshots registram o caminho anterior à categorização. Manifestos antigos usam correspondência não ambígua por nome e conferência de hash. Artefatos herdados da base não entram na seleção. |
| Um JAR substituído podia ser apagado | A seleção verificava apenas extensão e caminho. Agora todos os candidatos são verificados por SHA-256 antes da primeira exclusão, com proteção do índice e do snapshot. Dependências registradas também são consideradas. |
| Detecção, ingestão e exclusão de JARs bloqueavam o Qt | Varredura, parsing, hashing e acesso ao disco rodavam na thread da interface. Agora essas operações usam worker acompanhado, fila/sinal Qt, estado de execução e feedback de sucesso/falha. |
| Operações concorrentes e encerramento inseguro | O novo worker de remoção era daemon e não era acompanhado no fechamento. Os workers de pacotes são acompanhados no encerramento, deixam de emitir após fechar e rejeitam resultados de outro workspace. Alterações conflitantes são bloqueadas enquanto a operação está ativa. |
| Versões prontas com fontes inacessíveis por variante | `artifact_sha256` recebia o hash de cada fonte, diferente do hash da aplicação registrado no catálogo. Agora o hash da aplicação é determinístico e é compartilhado pelos registros dessa variante. |
| Índice estrutural incompleto | O parser era executado, mas seus símbolos e relações não eram persistidos. Agora `code_symbols` e `code_relations` são preenchidos, e arquivos Kotlin usam o parser correspondente. |
| Importação parcial após falha | Cada aplicação era confirmada separadamente. A ingestão agora usa uma transação SQL para o conjunto e a transação existente do catálogo; falhas durante parsing/cópia retiram os arquivos criados nessa tentativa. IDs ou destinos já usados são rejeitados para evitar sobrescrita e fontes obsoletos. |
| Detecção incorreta de identidade e versão | O fallback inventava `1.0.0.0` e podia identificar `vr.vrmaster` como `VRVrmaster`. Agora mantém versão não identificada, agrupa aplicações inferidas e evita duplicar fontes entre raízes sobrepostas. A pasta `resources` na raiz é tratada corretamente. Ambiguidades de metadados/versões são informadas em vez de misturadas. |

Os índices de chaves estrangeiras adicionados na implementação original foram mantidos. A eliminação em lote permanece na rotina única de expurgo.

## Verificação

Regressões novas em `tests/test_package_improvements_audit.py` cobrem caminhos inválidos, pacote inexistente, rollback, falha de banco, fontes compartilhados, seleção por hash da variante, símbolos/relações, versão desconhecida, metadados em `resources`, proteção de JARs modificados/internos e preservação do snapshot categorizado.

Os testes em `tests/test_apps_catalog_bridge.py` bloqueiam deliberadamente os workers e verificam que o event loop Qt continua processando eventos durante detecção, importação e exclusão de JARs, além de verificar rejeição de operações concorrentes e apresentação dos erros.

Uma rodada revelou `WinError 32` no encerramento de um teste antigo de snapshot: a pasta temporária era descartada antes de fechar a bridge. O teste passou a encerrá-la explicitamente; a repetição com `pytest --lf -q -x` passou.

Resultado final: `python -m pytest -q --durations=10` concluiu com **963 testes e 45 subtestes aprovados em 97,78 segundos**. A verificação focada dos fluxos corrigidos passou com 26 testes. `python -m ruff check .` e `git diff --check` concluíram sem erros.

## Limites da evidência

As verificações usam bases e arquivos temporários, incluindo testes Qt/QML. Não houve exclusão experimental na base real de aproximadamente 2 GB, benchmark de remoção nessa base, nem certificação de tempo de execução em produção. Os números de desempenho dos relatórios anteriores não foram reproduzidos nesta auditoria.

SQLite, JSON e sistema de arquivos não formam uma única transação durável contra encerramento abrupto do processo ou falha de energia. Uma falha de disco durante expurgo pode deixar exclusão parcial; ela agora é reportada, sem informar sucesso ou remover silenciosamente o registro do pacote.

Dados importados com a implementação anterior não foram reindexados automaticamente. As correções de hash, símbolos e relações se aplicam às novas importações; dados antigos incompletos precisam ser reimportados a partir dos fontes preservados. A interface continua oferecendo os fluxos existentes de renomeação e diretório personalizado.

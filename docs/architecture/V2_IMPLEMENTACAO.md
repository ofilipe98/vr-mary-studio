# V2 — entrega e auditoria final

Escopo: execução Ultra recuperável, busca híbrida local e separação de responsabilidades, conforme [plano](PLANO_V2_ULTRA_BUSCA_ARQUITETURA.md).

O checkout foi movido para `D:\Codex\VRStudio` durante a implementação. Os relatórios antigos não acompanharam esta pasta. As novas evidências são geradas em `reports/v2/conclusao/`, ignorado pelo Git. Não foi criada release nem enviado commit.

## Implementado

- Runner utilizado pelo chat com orçamento compartilhado, reserva para síntese e revisão, cancelamento e checkpoint periódico.
- Propriedade persistida por processo, recuperação de execução órfã sem chamadas automáticas e retomada explícita pela interface. O run é preservado; cada retomada recebe uma nova execução local. A ampliação de orçamento exige a ação separada `+15 chamadas / +300 s`.
- Validação de versão, permissões, modelo e conteúdo antes de reutilizar uma etapa; resultado e tentativa gravados juntos. Publicação local liga mensagem, citações e registro da investigação na mesma transação.
- Modelos ONNX multilíngues em CPU, revisão e SHA-256 fixados. Download somente pela ação explícita de preparo. Índice em gerações com publicação atômica, atualização incremental, remoção de documentos antigos e fallback textual.
- Candidatos semânticos entram nas trilhas do roteador, com filtros, RRF e o reranqueamento do domínio. Relações explícitas locais possuem trecho e hashes verificáveis; chamadas Java continuam identificadas como relações sintáticas.
- Adaptadores concretos separados, domínios de persistência e apresentação extraídos e compositor QML separado. As fachadas existentes preservam o contrato dos consumidores.

## Resultado em 08/09/2026

Implementação L0–L8 concluída no checkout `D:\Codex\VRStudio`, referência Git `2f563b7b0ea876707971e419283faa24194725e5`. A versão de lançamento continua `0.5.7`; V2 designa este conjunto de funcionalidades. As alterações existentes de interface, Skills, limites de uso, otimizações de busca e reorganização de arquivos foram preservadas e incluídas na regressão. O Claude não teve resposta real homologada por ausência de assinatura, informada pelo usuário.

| Verificação | Resultado e evidência |
| --- | --- |
| Suíte completa final | **872 testes e 45 subtestes aprovados**, sem falhas, em 97,85 s. [Log](../../reports/v2/conclusao/pytest-final-r2.log), [JUnit](../../reports/v2/conclusao/pytest-final-r2.xml). |
| Python e diff | `compileall`, Ruff `F821/F811` e `git diff --check` aprovados. [Resultado](../../reports/v2/conclusao/static-final.json). |
| QML estático | 62 arquivos, **0 erros e 806 avisos**: 773 de acesso não qualificado, 26 de propriedade não inferida e 7 de posicionamento em layout. `ChatPreview`: 25, abaixo do limite de 50; compositor: 3; controles novos de busca e retomada: 0. [Saída integral](../../reports/v2/conclusao/qmllint-final.json). |
| Chat renderizado | 14 capturas, claro/escuro, 1366×768, 1920×1080, 390×844 e 768×1024; texto longo, fontes, atividade, erro, cancelamento e conversa vazia. Zero avisos de execução QML. [Capturas](../../reports/v2/conclusao/visual/). |
| Componentes V2 | 20 capturas, claro/escuro, larguras 700 e 390, modelo ausente, preparo, orçamento esgotado e publicação pronta. Zero avisos de execução QML. [Capturas](../../reports/v2/conclusao/visual-v2-final/). |
| Pacote final | PyInstaller concluído; ZIP extraído e executável aberto em chat escuro e configurações claras. Exit 0, sem download implícito de pesos. [Resultado](../../reports/v2/conclusao/portable-result-final.json). |

Os 806 avisos estáticos são uma dívida remanescente, não foram suprimidos nem apresentados como corrigidos. As renderizações e testes de interação cobrem os estados citados, não todos os estados possíveis. A contagem preliminar feita por PowerShell subestimava o primeiro aviso de alguns arquivos; o relatório final usa a saída bruta do processo.

O corpus sintético congelado contém 96 documentos e 62 consultas, com subconjuntos de desenvolvimento e avaliação. Não representa instruções verificadas do ERP real. A busca textual permanece padrão; a híbrida é opcional.

## Rastreabilidade dos lotes

| Lote | Entrega auditada |
| --- | --- |
| L0 | Contratos de protocolo, fixtures brutas, testes de mutação e inventário final com SHA-256. |
| L1 | Runner e serviço de busca utilizados pelo chat; teste em processo novo bloqueia importações transitivas de Qt pelo backend. |
| L2 | Orçamento compartilhado entre pesquisadores, código, síntese, revisão e correção; reserva atômica, concorrência limitada e cancelamento pelo adaptador. |
| L3 | Checkpoints SQLite, propriedade por processo e instante de criação, recuperação de órfãos sem chamadas automáticas, retomada explícita e publicação local transacional. |
| L4 | Dois modelos ONNX reais em CPU, revisões e hashes fixados, corpus dividido antes da avaliação e escolha pelo desenvolvimento. |
| L5 | Busca híbrida nas trilhas do roteador real; filtros antes do ranking, RRF, gerações atômicas, atualização incremental e fallback textual. |
| L6 | Referências explícitas verificáveis, hashes de origem/destino, limites de expansão e chamadores Java identificados como relações sintáticas. |
| L7 | Adaptadores concretos, domínios de persistência e apresentação extraídos, fachadas compatíveis e compositor QML separado. |
| L8 | Testes integrados, provedores disponíveis, renderizações e pacote extraído. Restrição externa do Claude registrada. |

Os relatórios originais de L0/R2 não acompanharam a mudança de pasta. O inventário final registra o estado atual; não substitui retroativamente aqueles arquivos nem comprova uma comparação de desempenho com o baseline perdido.

## Correções relevantes

- Corrigida a divergência entre a fachada do banco e o domínio de conversas, que rejeitava os argumentos de publicação V2. Mensagem, citações e registro de publicação agora são gravados juntos, com idempotência.
- Restaurada a exclusão dos checkpoints e tentativas ao remover definitivamente uma conversa. A exportação portátil sanitiza pesquisas privadas e relações; o índice semântico derivado não faz parte da lista de índices exportáveis.
- Retomada preserva consumo, contexto e run; modelo, permissões, fontes ou release incompatíveis invalidam reaproveitamento. A ampliação separada de `+15 chamadas / +300 s` não zera o consumo.
- Corrigida a normalização da release com análise de código desativada. A retomada explícita inicia uma nova sessão principal nativa, evitando depender de uma sessão Codex vazia que nunca persistiu um turno.
- Uma segunda instância preserva conversas com pesquisa pertencente a processo vivo. Atualizações atrasadas usam o token imutável do proprietário.
- Filtros de revisão, origem, produto e release são conferidos na busca e na montagem do contexto; o contexto de release acompanha as threads. Busca por ferramenta e refinamento também preparam o serviço híbrido.
- Cache de assinatura invalidado por triggers SQLite, inclusive em escrita externa; mensagens de chat não invalidam os documentos. Ranking mantém o melhor trecho por documento, com desempate determinístico e fechamento de conexões em erro.
- Corrigidos contador de minutos, referências de logging e transbordamento dos controles em telas estreitas. Publicação já pronta pode ser retomada sem pedir orçamento adicional.
- Claude recebe prompts por stdin, preservando Unicode e quebras de linha, sem exceder o limite do `.cmd` nem colocar metacaracteres do prompt na linha de comando. Teste com subprocesso real cobre entrada maior que o pipe. A tentativa externa alcançou o protocolo e informou falta de login; não houve novas chamadas após a informação de ausência de assinatura.

## Busca medida no roteador de produção

São 12 consultas de desenvolvimento e 50 de avaliação: 36 paráfrases, 8 identificadores exatos e 6 sem resposta. Os rótulos foram fixados antes da avaliação; a seleção do MiniLM usa o conjunto de desenvolvimento.

| Métrica final | Textual | Híbrida MiniLM |
| --- | ---: | ---: |
| Recall@10, avaliação com resposta | 25,00% | 75,00% |
| MRR, avaliação com resposta | 0,2500 | 0,4856 |
| Recall@10, paráfrases | 8,33% | 69,44% |
| MRR, paráfrases | 0,0833 | 0,3713 |
| Latência p50 | 28,82 ms | 82,40 ms |
| Latência p95 | 52,60 ms | 105,70 ms |
| Identificadores exatos preservados | Sim | Sim |
| Isolamento de release | Sim | Sim |
| Consultas sem resposta que receberam candidatos | 1/6 | 2/6 |

[Resultados por consulta](../../reports/v2/conclusao/production-benchmark.json). As métricas isoladas dos modelos não substituem as do roteador. O ganho nas paráfrases não comprova qualidade em qualquer corpus; a regressão nas consultas sem resposta impede promover a busca híbrida a padrão nesta entrega.

## Provedores e retomada reais

- **Antigravity / `gemini-3.7-flash-high`**: mesma pergunta e fonte sintética em VR (39,81 s) e Ultra (42,62 s), uma citação em cada resposta. Cancelamento após checkpoint e retomada por clique QML aprovados: mesmo run, nova execução, etapa reutilizada e uma publicação. [Registro](../../reports/v2/conclusao/runtime-r2/result.json).
- **Codex / `gpt-6-astra`**: resposta nativa `V2_OK` em 6,52 s. [Registro](../../reports/v2/conclusao/adapters/codex/result.json). Na validação integrada final, VR respondeu em 43,03 s com uma citação. A primeira resposta Ultra foi **rejeitada pelo contrato** após síntese/correção (83,95 s), por faltar a seção de validação; foi publicada a mensagem de falha controlada, sem fontes inventadas. O cenário separado de cancelamento e retomada pela UI terminou aprovado, com mesmo run, nova execução, checkpoint reutilizado e publicação única. [Registro completo](../../reports/v2/conclusao/runtime-final/result.json). Não se trata de 100% de respostas válidas do modelo.
- **OpenCode / `opencode/big-pickle`**: resposta nativa `V2_OK` em 7,80 s. [Registro](../../reports/v2/conclusao/adapters/opencode/result.json).
- **Claude**: transporte corrigido e testes locais aprovados; sem resposta de modelo homologada por falta de assinatura. [Tentativa](../../reports/v2/conclusao/adapters/claude/result.json).

Tempos de uma execução não são p50/p95 de investigação nem evidência de aceleração geral. O cenário de cancelamento inclui o trabalho anterior ao pedido de interrupção. Uso real, estimado e desconhecido permanece separado nos snapshots; não há estimativa monetária inventada.

A captura imediatamente após a publicação mostrou a UI ainda processando eventos enfileirados. A reabertura do resultado persistido foi conferida separadamente: conversa e interface ociosas, zero avisos QML. [Registro](../../reports/v2/conclusao/runtime-final/reopened-ui.json), [captura](../../reports/v2/conclusao/runtime-final/resume-after-reopened.png). O script de validação passou a aguardar também o estado ocioso da UI antes de capturar futuras execuções.

## Operação e limites

Configurações → VR Ultra → Busca local permite preparar os pesos e ativar a busca híbrida. Somente a ação explícita de preparo baixa modelos. As flags de busca híbrida e relações são independentes. O caminho nativo de anexos foi preservado; não é apresentado como pesquisa fan-out recuperável.

Não há retomada automática de efeitos externos. Pesquisas automáticas são somente leitura; uma chamada remota sem confirmação pode ter ocorrido antes de uma queda. A publicação única é uma garantia local transacional, não execução remota exatamente uma vez. O checkpoint periódico tem resolução aproximada de um segundo; uma queda pode perder esse último intervalo de contabilização.

O pacote foi construído com as dependências opcionais instaladas e abriu após extração, sem preparo implícito. Os embeddings reais foram exercitados no Python local; não se afirma execução ONNX dentro do binário congelado. Retorno a binário antigo sobre o banco migrado não foi homologado.

Os 118 módulos Python do projeto presentes no arquivo PYZ do build final foram comparados estruturalmente com o bytecode compilado das fontes atuais, sem executar o conteúdo. Os dois pacotes de namespace foram identificados separadamente. NumPy, ONNX Runtime e tokenizers estão presentes no arquivo do build. [Conferência](../../reports/v2/conclusao/frozen-source-check.json).

## Artefatos e reprodução

- [Manifesto final](../../reports/v2/conclusao/source-final-manifest.json) e [fontes auditadas](../../reports/v2/conclusao/source-final.zip), incluindo arquivos novos não rastreados.
- [Diff rastreado](../../reports/v2/conclusao/tracked-diff-final.patch) e [estado Git](../../reports/v2/conclusao/git-status-final.txt).
- [Pacote de validação](../../reports/v2/conclusao/VRStudio-v2-final.zip), SHA-256 `be6a0915d809d57d183e3c5b8af6b6233a7c12a2fa17fbf6eb55f381f8892885`. Artefato local, não uma release publicada.

Os scripts em `scripts/` são `benchmark_v2_retrieval.py`, `benchmark_v2_router.py`, `validate_v2_runtime.py`, `validate_v2_adapters.py`, `visual_chat_review.py`, `visual_v2_review.py`, `audit_v2_checkout.py` e `verify_v2_package.py`. Usar `.venv/Scripts/python.exe -m ...` para ferramentas no checkout movido. Os scripts de provedor real fazem chamadas externas; os demais usam dados isolados.

## Referências dos modelos

- [Multilingual E5 Small](https://huggingface.co/intfloat/multilingual-e5-small): MIT; revisão `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
- [Multilingual MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2): Apache-2.0; revisão `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.

Manifestos de arquivos, dimensões, pooling e checksums estão em `retrieval/local_neural.py`. Instalação de desenvolvimento opcional: `python -m pip install -e ".[semantic]"`. O aplicativo permite preparar os pesos em Configurações → VR Ultra → Busca local.

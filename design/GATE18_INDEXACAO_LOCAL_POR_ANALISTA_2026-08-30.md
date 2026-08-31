# Gate 18 — indexação local por analista, sem dependência de LLM

Data: 2026-08-30

## Decisão arquitetural

O VRStudio será instalado nas máquinas dos analistas. Cada instalação pode
trabalhar com uma release ERP diferente e manter até três releases locais.
Portanto, o processamento necessário para transformar os 46 JARs em uma base
pesquisável precisa funcionar integralmente sem LLM, sem provedor de embeddings
remoto e sem serviço central.

Além da release integral, o Studio admite uma investigação parcial explícita de
um único JAR. Esse fluxo exige seleção do arquivo, cria manifesto
`analysis_scope=single_jar`, usa cobertura `1/1` e nunca deve ser apresentado
como cobertura completa do ERP. O contrato de 46 JARs permanece obrigatório
quando o escopo escolhido for **Release completa**.

O limite entre as camadas fica fixo:

| Camada | Responsabilidade | LLM permitida |
|---|---|---|
| Preparação da release | inventário, hashes, decompilação, AST, grafo e FTS | Não |
| Recuperação | busca por classe, pacote, símbolo, chamada e texto | Não |
| Análise da pergunta | escolha de fontes, interpretação e síntese | Opcional |

Uma release só pode aparecer como `ready` quando as duas primeiras camadas
estiverem utilizáveis. Embeddings podem ser acrescentados como índice auxiliar,
preferencialmente local, mas sua ausência ou falha nunca rebaixa o índice-base
nem impede o uso da busca determinística.

## Estado atual validado

O backend já possui os componentes corretos para o núcleo offline:

- catálogo local por `release_id`, com limite de três releases;
- inventário dos 46 JARs, SHA-256 agregado e verificação de frescor;
- Java 17 isolado, Vineflower e CFR, sem uso de modelo;
- lotes determinísticos, serializados, retomáveis e protegidos por lock;
- deduplicação por hash de bytecode e proveniência por release/JAR;
- parser AST tolerante, grafo sintático e índice SQLite/FTS;
- seleção local de release na aba VR Ultra;
- remoção de índice somente com aprovação.

Nenhum desses passos chama o orquestrador ou um provedor de modelo. O modelo é
usado somente no worker de Código depois que a recuperação local encontra os
trechos candidatos.

## Fatias implementadas

- seletor **Diretório padrão dos JARs** na configuração VR Ultra;
- opções `C:\vr\exec` e workspace atual, com caminho resolvido, existência e
  contagem de JARs;
- preferência e release ativa persistidas por workspace;
- página VR Ultra rolável para manter todos os controles acessíveis;
- comando `snapshot-erp-release`, com origem padrão `C:\vr\exec`;
- exigência de quantidade exata, legibilidade do ZIP/JAR e estabilidade durante
  o preflight;
- cópia para staging, comparação de tamanho e SHA-256 e promoção sem
  sobrescrever snapshot existente;
- proveniência da origem e do snapshot persistida no manifesto local;
- campo de `release_id` e botão **Adicionar release** na própria aba VR Ultra;
- snapshot executado em thread local, sem bloquear a interface, com estado de
  execução, resultado e atualização automática do seletor;
- bloqueio de uma segunda importação simultânea e recusa de sobrescrita de uma
  release já inventariada;
- fila contínua de decompilação/indexação acionada pela aba VR Ultra, avançando
  um lote local por vez e reutilizando planos persistidos;
- pausa cooperativa entre lotes, retomada do plano atual e retry seletivo de
  qualquer lote `failed/partial` exibido na tela;
- preflight local de Java 17 e de ao menos um decompilador verificado antes de
  criar ou avançar trabalho;
- `release_id` e SHA-256 do manifesto congelados no início do job, verificados
  durante toda a rodada e registrados em trilha JSONL append-only;
- consulta de cobertura em background para não bloquear a interface em bases
  grandes;
- restauração visual do último job, release/hash e JAR/lote atual ou próximo;
- heap por lote configurável em 1/2/4 GB e timeout em 5/10/20 minutos, ambos
  persistidos por workspace, congelados no início do job e auditados;
- concorrência Java global fixada em 1 processo para proteger a máquina do
  analista;
- telemetria local por tentativa/lote e agregada por job: duração de parede,
  duração do decompilador, pico de memória do processo, tempo de CPU, bytes de
  entrada/saída e ocorrência de timeout; o último resumo é restaurado pela
  trilha JSONL;
- preflight offline determinístico para release, 46 artefatos/hash, frescor,
  Java 17, decompilador aprovado, capacidade e classpath, sem iniciar Java de
  decompilação, rede ou modelo;
- contrato do Agente de Código com `release_id`, hash do manifesto e `run_id`
  do fan-out, com degradação isolada quando a origem divergir;
- bloqueio do Agente de Código quando a release selecionada está `stale`;
- nenhuma dependência de LLM ou rede nesse fluxo.

Ainda falta ETA preditivo por lote. A telemetria observada cobre o subprocesso
do decompilador, mas não representa o consumo total do Studio nem constitui uma
cota percentual de CPU do sistema operacional. O limite de CPU continua
estrutural pela concorrência Java igual a 1. O snapshot pode ser acionado pela
interface ou pelo CLI; ambos chamam a mesma operação determinística.

## Gaps de produto

1. Cadastro, snapshot, avanço contínuo, JAR/lote atual, erros selecionáveis e
   telemetria observada já estão na interface. Falta estimativa de tempo baseada
   no histórico real da mesma máquina/release.
2. Jobs de índice e análises do Agente de Código já congelam suas identidades e
   são correlacionáveis por release/hash, mantendo `run_id` próprio por ciclo de
   vida. Falta uma visualização consolidada dessa correlação na interface.
3. A distribuição portátil de homologação atual inclui um `VRProject` grande e
   específico da máquina de build. Isso não deve ser o pacote padrão entregue a
   todos os analistas.
4. Falta um teste explícito com rede e provedores de modelo indisponíveis que
   leve uma release do inventário até o índice pesquisável.

### Resultado do preflight real em 2026-08-31

- `C:\vr\exec` não estava presente na máquina;
- a única release inventariada, `current`, tinha 46 JARs no manifesto, mas
  estava `stale` porque a lista da origem mudou;
- cobertura existente: 12/46 JARs, com 34 restantes;
- Java 17, Vineflower e CFR estavam disponíveis; os dois decompiladores tinham
  checksum aprovado;
- capacidade: cerca de 5,22 GB usados, previsão conservadora de 27,08 GB e
  aproximadamente 574,49 GB livres em D:;
- decisão: não iniciar o E2E completo até existir uma origem estável e uma
  `release_id` explícita. O bloqueio é de identidade/frescor, não de capacidade.

## Estrutura por instalação

O aplicativo e os dados variáveis devem ficar separados:

```text
VRStudio/App/                         executável e toolchain imutável
WorkspaceDoAnalista/ERP/releases/
  <release_id>/jars/                  os 46 JARs escolhidos pelo analista
WorkspaceDoAnalista/indice/codigo/
  releases/<release_id>/              manifesto e estado local
  artifacts/                          cache por conteúdo
  decompilation/                      saídas retomáveis
```

O analista informa um identificador e seleciona a pasta da release. O Studio
não infere versão pelo nome da pasta ou pelo conteúdo do JAR. O manifesto local
registra os 46 caminhos, tamanho, mtime, SHA-256, hash agregado, toolchain e data
de indexação.

## Diretório padrão dos JARs

Nas máquinas dos analistas, os JARs do ERP estarão normalmente em:

```text
C:\vr\exec
```

A tela de configurações deve incluir o campo **Diretório padrão dos JARs** com
duas opções explícitas:

1. **Instalação local do ERP — `C:\vr\exec`**: opção padrão da instalação;
2. **Workspace atual**: estrutura já suportada em
   `WorkspaceDoAnalista\ERP\releases\<release_id>\jars`.

A preferência é local e vinculada ao workspace. A interface mostra o caminho
resolvido, existência da pasta, quantidade de JARs encontrada e data da última
verificação. Se `C:\vr\exec` não existir, o Studio não troca silenciosamente de
origem: mantém a escolha, sinaliza o problema e permite selecionar o caminho do
workspace.

`C:\vr\exec` é uma origem de importação, não o local definitivo do índice. O
Studio nunca altera, remove ou decompila arquivos dentro dessa pasta. Ao
cadastrar uma release, ele:

1. exige `release_id` informado pelo analista;
2. verifica que existem exatamente 46 JARs legíveis;
3. calcula SHA-256 diretamente na origem;
4. cria um snapshot imutável em
   `WorkspaceDoAnalista\ERP\releases\<release_id>\jars`;
5. confirma que os hashes do snapshot são iguais aos da origem;
6. inventaria imediatamente; decompilação e indexação posteriores usam somente
   o snapshot, nunca a pasta de origem.

Esse snapshot é necessário porque uma atualização do ERP pode substituir os
arquivos em `C:\vr\exec`. Indexar diretamente ali poderia misturar duas releases
ou invalidar uma análise em andamento. O custo é uma cópia adicional dos JARs,
compensada pela preservação de até três releases e pela deduplicação posterior
por hash de bytecode.

JARs prioritários como VRMaster, VRAutorizador, VRConcentrador, VRAtarejo,
VRAtacado, VRGerenciadorNFCe e VRPdv podem definir a ordem inicial de
processamento, mas `ready_full` exige os 46 JARs. Cobertura parcial precisa ficar
visível como razão, nunca como release completa.

## Fluxo local proposto

1. **Adicionar release:** o analista escolhe uma pasta e informa `release_id`.
2. **Preflight:** o Studio confere Java 17/toolchain, espaço, quantidade de JARs
   e legibilidade, sem iniciar modelo.
3. **Inventário:** calcula hashes e registra o manifesto local.
4. **Planejamento:** deduplica bytecode e cria lotes determinísticos.
5. **Processamento em background:** executa um decompilador por vez, com pausa,
   retomada, limite de CPU/heap e estado por lote.
6. **Indexação:** promove somente saídas completas para AST, grafo e FTS.
7. **Validação:** executa consultas locais conhecidas e marca cobertura/frescor.
8. **Ativação:** associa a release pronta ao workspace. Cada chat captura
   `release_id` e hash antes de iniciar os workers.
9. **Consulta opcional com IA:** somente após a recuperação local, e apenas se o
   toggle de Código e a política de envio permitirem.

Se a pasta mudar, o Studio marca a release como `stale`, interrompe novas
análises fundamentadas nela e oferece reindexação incremental. JARs com hash já
processado podem reutilizar artefatos locais; arquivos alterados são
reprocessados. Não há decompilação durante uma pergunta.

## Entrega faseada

### Fase A — contrato offline e isolamento

- declarar em código uma política `indexacao_local_sem_llm` sempre ativa;
- separar pacote genérico do aplicativo e dados ERP do workspace;
- persistir release ativa por workspace, não apenas por usuário;
- persistir por workspace a origem `C:\vr\exec` ou `Workspace atual`;
- criar snapshot verificado dos 46 JARs sem modificar a pasta de origem;
- congelar release/hash no início de cada execução;
- registrar eventos locais de inventário, processamento e promoção. O job de
  processamento grava `processing-runs.jsonl`; o Agente de Código recebe no
  fan-out o `release_id`, o mesmo hash de manifesto e o `run_id` da análise.
  Jobs de índice e análises mantêm IDs distintos, correlacionados por
  release/hash, para não misturar dois ciclos de vida na auditoria.

### Fase B — assistente de release na interface

- botão **Adicionar release** com escolha da pasta e ID explícito;
- seletor **Diretório padrão dos JARs** com `C:\vr\exec` e o caminho atual;
- indicador de pasta existente, total de JARs e última verificação;
- preflight dos 46 JARs, espaço de até 10× e toolchain;
- fila local com progresso por JAR/lote, pausar, continuar e retry;
- estados `incomplete`, `indexing`, `partial`, `ready`, `stale` e `failed`;
- bloqueio do Agente de Código quando a release selecionada não estiver fresca.

Implementado: progresso por cobertura de JAR, JAR/lote atual ou
próximo, pausa entre lotes, continuação do plano persistido, restauração visual
do último job após reabrir o Studio, retry seletivo, limites de heap/timeout,
telemetria observada, ETA baseado na mediana do histórico local e bloqueio por
frescor. O único gate desta fase que depende de dados externos é o E2E offline
com uma release real fresca de 46 JARs.

### Fase C — eficiência multi-release

- reaproveitar conteúdo idêntico entre releases pelo SHA-256 do bytecode;
- reindexar somente JARs alterados;
- aplicar limites configuráveis de CPU, heap, disco e horário ocioso;
- manter no máximo três releases e pedir aprovação antes de remover uma antiga;
- oferecer exportação/importação opcional de índice assinado por hash, sem
  transformar esse atalho em dependência.

Implementado: o cache global de bytecode evita decompilar conteúdo concluído;
um JAR integralmente idêntico clona seu índice pesquisável sob a identidade da
nova release, sem colisão de `release_id`. Apenas artefatos alterados geram novos
lotes. A aba expõe CPU, heap, disco e janela ociosa; o Java continua serial e em
prioridade baixa. O catálogo bloqueia a quarta release, a remoção exige aprovação
e agora também purga as linhas pesquisáveis e planos exclusivos, preservando
fontes JAR e cache compartilhado. Exportação/importação `.vridx` usa verificação
SHA-256 em streaming e exige coincidência do manifesto e de cada JAR local.

### Fase D — validação em campo

- testar máquinas de analistas com releases diferentes ao mesmo tempo;
- executar instalação e indexação com rede bloqueada e providers desativados;
- comparar o mesmo chamado em duas releases e provar citações/hashes distintos;
- medir duração, pico de RAM, CPU, disco e taxa de retomada após interrupção;
- validar atualização de release sem contaminar ou apagar a anterior.

Automatizado no repositório: execução com acesso de rede bloqueado, duas releases
com bytecodes diferentes e citações/hashes isolados, dois workspaces de analistas
com o mesmo `release_id` e bases distintas, rejeição de pacote adulterado,
retomada e limpeza aprovada sem apagar os JARs. O comando
`validate-erp-code-field` consolida cobertura, frescor, símbolo de prova,
citações, hashes e telemetria sem rede ou modelo.

Gates externos restantes: executar o instalador em máquinas reais diferentes,
processar uma release fresca completa com os 46 JARs, medir o ciclo integral e
rodar os chamados reais já resolvidos com Código ligado/desligado. Esses gates
não podem ser simulados como concluídos no checkout de desenvolvimento.

## Critérios objetivos de aceite

- uma máquina limpa indexa os 46 JARs e responde busca por símbolo com todos os
  providers de modelo desabilitados;
- `C:\vr\exec` é a seleção inicial e o usuário pode alternar para o caminho do
  workspace sem editar arquivo de configuração;
- a importação não altera nenhum byte, data ou nome dentro de `C:\vr\exec`;
- trocar os JARs da origem depois do snapshot não muda uma execução ou release
  já indexada;
- zero chamada de rede ocorre entre adicionar a release e promover o índice;
- duas instalações podem selecionar releases diferentes sem compartilhar
  preferência, banco ou cache mutável;
- duas releases na mesma instalação mantêm documentos, símbolos e citações
  separados por `release_id` e hash;
- fechar/reabrir o Studio retoma o primeiro lote incompleto, sem reiniciar tudo;
- mudança em um JAR marca a release como `stale` antes de qualquer resposta;
- troca do seletor durante uma execução não altera a release já congelada nela;
- pacote genérico não contém JAR, fonte decompilada ou índice específico de
  cliente/release;
- exclusão de release exige aprovação e não remove os 46 JARs de origem.

## Riscos e trade-offs

- **Tempo inicial:** os 46 JARs podem exigir horas; por isso o processo deve ser
  retomável e utilizável parcialmente com cobertura explícita.
- **Disco:** o orçamento conservador de 10× é por workspace; três releases podem
  exigir deduplicação agressiva ou política de retenção.
- **CPU/RAM:** processamento em background não pode degradar o atendimento do
  analista; limites e pausa são requisitos, não otimizações futuras.
- **Classpath desconhecido:** indexar todos os JARs não resolve automaticamente
  classes duplicadas. A resposta deve continuar sinalizando ambiguidade.
- **Índice parcial:** consultas podem funcionar antes de 46/46, mas a interface e
  as citações precisam declarar exatamente a cobertura disponível.
- **Embeddings:** melhoram recall semântico, porém não podem ser o único caminho
  para localizar código nem requisito para operar offline.

## Impacto na sequência restante

Antes da revisão dos tickets e do benchmark final, entra uma validação adicional:
provar que a release escolhida pelo analista pode ser preparada localmente, do
inventário à busca, com providers desligados. Depois disso permanecem a revisão
de 5–10 chamados, o benchmark ligado/desligado e a revisão cega dos resultados.

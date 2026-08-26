# Plano de migração do frontend para Qt Quick/QML

## Objetivo

Modernizar somente a camada visual do VR Norte Studio, preservando a identidade
VR Norte, o comportamento funcional e todo o backend Python existente. A
migração deve ser incremental, comparável e reversível até atingir paridade.

## Status de implementação — 23/08/2026

A migração visual e funcional das oito telas foi concluída no frontend QML. O
backend Python existente continua sendo a fonte das regras de negócio e dos
dados. A interface Qt Widgets permanece disponível como rollback até a
ativação definitiva do QML.

| Tela | Dados e estados migrados | Ações e opções migradas |
|---|---|---|
| Dashboard | métricas, fontes, situação das sincronizações, OCR, vídeos e conversas | sincronizar Wiki + KB, nova conversa, revisão e abrir VR no Codex |
| Chat VR | conversas, mensagens Markdown, streaming, atividade, contexto e subagentes | buscar, novo chat, projeto, arquivar, lixeira, anexos, modelo/provedor, effort, permissões, VR, orquestração, skills, MCP, tools, comandos `/`, menções `@`, envio, interrupção e aprovações |
| Conhecimento | busca FTS5, tabela, documento completo, vazio, paginação e contador | pesquisar, filtros de módulo/fonte/origem, limpar, selecionar, expandir e abrir arquivo local |
| Sincronizações | estado concorrente, progresso e log da sessão | Wiki, Endoo, KB, login visível, Schema, OCR, seleção de arquivo e sincronizar tudo |
| Revisão | tabela completa, detalhe auditável, evidências, OCR, filtros, presets, seleção e paginação | aprovar, manter, adiar, reabrir, aplicar em lote, abrir fonte/local e copiar citação |
| Vídeos | hierarquia, resumo, seleção, filtros, progresso e saída do processo | login, atualizar cursos, inventariar, classificar, baixar, inscrever, organizar, módulo manual e parar |
| Configurações | Geral, Provedores, Temas e Projetos arquivados | procurar pasta, salvar `.env`, instalar OCR, abrir Codex, ativar provedores, reduzir movimento, restaurar e excluir com confirmação |
| Logs | eventos operacionais selecionáveis e estado vazio | copiar por seleção e rolagem nativa |

As superfícies do Chat VR também foram migradas: Browser embutido, Terminal,
Files com pré-visualização, Contexto local e Agents/Subagentes. Agendamentos e
Plugins continuam desabilitados porque também são placeholders “em breve” na
interface anterior.

### Validação já executada

- shell e todas as páginas carregando sem erro QML;
- identidade Dark & Orange comparada visualmente com as capturas da interface
  anterior, incluindo barra lateral preta e centro preto do Chat VR;
- testes de design system, bridges, navegação, conversas e eventos de
  orquestração;
- suíte completa do projeto executada antes do fechamento visual;
- QML promovido a frontend padrão na `dev`, com rollback por `--legacy-frontend`.

### Pendências fora da migração da interface

- validar o executável PyInstaller em uma build limpa;
- validar a distribuição portátil offline;
- tornar o QML a entrada padrão somente após aceite manual explícito;
- remover o frontend Widgets somente em uma etapa futura autorizada.

## Restrições obrigatórias

1. Não alterar regras de negócio em `orchestrator.py`, `db.py`, `providers.py`,
   sincronizadores, busca, classificação ou processamento de vídeos.
2. Não alterar marca, logotipo, símbolo, nomes das telas ou terminologia do
   produto.
3. Preservar a paleta VR Norte e os temas claro e Dark & Orange.
4. Manter o frontend Qt Widgets como padrão até o aceite da nova interface.
5. Não colocar regras de negócio em QML ou JavaScript.
6. Fazer cada etapa na branch `dev`, em lotes pequenos, testáveis e reversíveis.
7. Não remover a interface antiga antes da paridade funcional e visual.

## Identidade visual preservada

Os valores institucionais passam a ter uma fonte canônica compartilhada em
`mary/brand.py`:

| Elemento | Valor preservado |
|---|---|
| Laranja VR | `#FF7200` |
| Laranja acessível | `#C45100` |
| Amarelo VR | `#FCBD0F` |
| Azul-marinho VR | `#02021E` |
| Barra lateral | preto `#000000` |
| Fundo claro | `#F3F3F3` |
| Fundo Dark & Orange | `#12100F` |
| Superfície escura | `#1B1816` |
| Tipografia atual | Segoe UI no Windows |
| Símbolo | `assets/vrnorte-symbol.png` |
| Ícones | SVGs oficiais existentes em `mary/assets` |

Modernizar significa melhorar ritmo, hierarquia, consistência, responsividade,
foco e feedback. Não significa rebranding.

## Arquitetura alvo

```text
QML / Qt Quick
  páginas, componentes, layout e estados visuais
                     │
                     │ signals, slots, properties e models
                     ▼
Bridges/ViewModels Python da camada frontend
  adaptação dos contratos existentes; nenhuma regra de negócio
                     │
                     ▼
Backend Python atual
  orquestrador, SQLite, provedores, sync, busca e vídeos
```

Fluxo de estado:

```text
ação do usuário → QML → bridge → API existente
evento/resultado → bridge → propriedade/model → render QML
```

## Estrutura alvo

```text
vrsoft_extractor/mary/
├── brand.py
├── frontend/
│   ├── app.py
│   ├── bridge.py
│   ├── bridges/
│   │   ├── chat.py
│   │   ├── dashboard.py
│   │   ├── knowledge.py
│   │   ├── review.py
│   │   ├── sync.py
│   │   ├── videos.py
│   │   └── settings.py
│   └── qml/
│       ├── Main.qml
│       ├── theme/
│       ├── components/
│       ├── pages/
│       └── dialogs/
├── ui.py                  # frontend atual durante a transição
└── chat_widgets.py        # frontend atual durante a transição
```

## Fase 0 — baseline e proteção

### Passos

- [x] Confirmar que o frontend atual usa PySide6/Qt Widgets.
- [x] Catalogar as oito superfícies principais.
- [x] Registrar o risco arquitetural da `MainWindow` concentrar estado visual.
- [x] Centralizar a identidade em módulo independente de Widgets/QML.
- [x] Gerar a matriz completa ação → método Python → estado visual.
- [ ] Capturar todas as telas atuais em claro/escuro, 1366×768 e 1920×1080.
- [ ] Capturar DPI 100%, 125% e 150%.
- [ ] Registrar estados de conteúdo, vazio, carregamento, erro e operação ativa.

### Aceite

Nenhum fluxo será migrado sem possuir referência funcional e visual da versão
Qt Widgets.

## Fase 1 — fundação QML e execução paralela

### Passos

- [x] Criar o pacote `mary/frontend`.
- [x] Criar entrada de preview por `--qml-preview`.
- [x] Promover a entrada QML como padrão após o aceite visual.
- [x] Manter a entrada Qt Widgets por `--legacy-frontend` durante a estabilização.
- [x] Criar `FrontendBridge` sem importar backend de domínio.
- [x] Expor nome, versão, projeto, tema, navegação e assets ao QML.
- [x] Criar shell com dimensões mínimas equivalentes às atuais.
- [x] Criar navegação expandida/recolhida.
- [x] Criar troca entre tema claro e Dark & Orange.
- [x] Incluir QML no `pyproject.toml` e no build PyInstaller.
- [x] Adicionar smoke test de carregamento QML.
- [x] Adicionar captura automatizada do preview.
- [ ] Validar a entrada QML no executável empacotado.

### Aceite

`python -m vrsoft_extractor.mary.ui --smoke-test` termina com código zero e
carrega o frontend QML. A flag `--qml-preview` permanece como alias compatível,
enquanto `--legacy-frontend` permite o rollback temporário para Qt Widgets.

## Fase 2 — design system QML

### Passos

- [x] Criar tokens de espaçamento, raios, controles, navegação e tipografia.
- [x] Criar `VrButton`, `VrCard`, `VrStatusBadge` e `VrNavItem` iniciais.
- [x] Criar `VrIconButton`.
- [x] Criar `VrTextField` e busca.
- [x] Criar `VrTextArea`.
- [x] Criar `VrComboBox` básico.
- [ ] Criar seletor rico com busca e metadados.
- [x] Criar tooltip e menu contextual.
- [x] Criar diálogo, confirmação destrutiva e prompt multiline.
- [x] Criar toast de sucesso, informação, aviso e erro.
- [x] Criar estados vazios, de carregamento e de erro.
- [x] Criar toolbar de dados, filtros e paginação.
- [x] Criar tabela/lista virtualizada.
- [ ] Criar catálogo visual de todos os componentes e estados.

### Aceite

Nenhuma página cria variações locais de botão, campo, card, popup, toast,
filtro ou estado vazio. Todo componente deve cobrir hover, foco, pressionado,
desabilitado e carregamento quando aplicável.

## Fase 3 — Dashboard

### Passos

- [x] Criar uma primeira superfície visual de Dashboard sem dados fictícios.
- [ ] Criar `DashboardBridge` usando somente consultas existentes.
- [ ] Expor métricas como propriedades somente leitura.
- [ ] Implementar carregamento, erro e indisponibilidade.
- [ ] Implementar cards e atalhos reais.
- [ ] Comparar cada valor com o frontend atual.
- [ ] Validar atualização sem recriar a página.

### Aceite

Os números, rótulos, ações e estados precisam coincidir com o Dashboard atual.

## Fase 4 — Chat VR em fatias verticais

### 4.1 Conversas

- [x] Criar `ConversationListModel` com `QAbstractListModel`.
- [x] Migrar busca e seleção em modo somente leitura.
- [x] Migrar seletor de projeto e filtro das conversas.
- [x] Criar rascunho visual de novo chat sem persistência antecipada.
- [x] Criar a conversa real somente no primeiro envio.
- [x] Migrar menu contextual, arquivar, restaurar e excluir.
- [ ] Preservar seleção e scroll durante atualizações.

### 4.2 Cabeçalho e configuração

- [x] Exibir título, projeto, provedor e estado da conversa selecionada.
- [x] Exibir provedor, modelo, esforço, permissão e modo VR.
- [x] Migrar seletores e painel do modo VR.
- [ ] Representar indisponibilidade, troca e reconexão de provedor.

### 4.3 Mensagens

- [x] Criar `MessageListModel` virtualizado.
- [x] Renderizar o histórico básico de usuário e assistente em Markdown.
- [x] Implementar cópia do conteúdo integral da mensagem.
- [ ] Refinar código, citações e ações por mensagem.
- [ ] Implementar copiar, wrap de código e ações da mensagem.
- [ ] Representar reasoning, ferramentas, aprovações e erros.

### 4.4 Composer

- [x] Migrar entrada multiline, enviar e interromper.
- [x] Migrar chips de arquivo, skill, MCP tool e contexto.
- [x] Migrar menções `@` e comandos `/`.
- [x] Preservar atalhos e prevenção de envio duplicado.

### 4.5 Streaming e multiagentes

- [x] Atualizar texto incrementalmente sem travar a UI.
- [ ] Preservar scroll quando o usuário estiver lendo conteúdo anterior.
- [x] Migrar barra de atividade e plano.
- [x] Migrar painel de agentes e saídas individuais.
- [x] Migrar aprovação, cancelamento, falha e conclusão.

### Aceite

O mesmo turno executado em Widgets e QML deve persistir as mesmas mensagens,
eventos, opções e estados no backend.

## Fase 5 — telas de dados

Executar na ordem: Conhecimento → Revisão → Vídeos.

Para cada superfície:

1. Criar bridge específica.
2. Expor coleções por `QAbstractListModel`.
3. Migrar busca, filtros, contador e ação principal.
4. Migrar conteúdo e painel de detalhes.
5. Migrar paginação e densidade.
6. Implementar loading, empty e error.
7. Preservar seleção durante refresh.
8. Comparar filtros, ordenação, totais e ações com Widgets.
9. Testar dados longos e coleções grandes.

### Aceite

Nenhuma consulta ou regra de filtro é reimplementada em QML, e os resultados
coincidem com a interface atual.

## Fase 6 — telas operacionais

### Sincronizações

- [x] Migrar fontes, ações, progresso e log.
- [x] Representar operação concorrente, falha parcial e recuperação.
- [x] Impedir ações visualmente impossíveis durante execução.

### Vídeos

- [x] Migrar árvore/lista, filtros e seleção.
- [x] Migrar classificação manual, progresso e saída do processo.
- [x] Preservar o lifecycle de `QProcess` no Python existente.

### Aceite

QML apenas inicia ações e apresenta estado; threads e processos permanecem no
Python.

## Fase 7 — Configurações e Logs

- [x] Migrar Geral, Aparência e Provedores; manter Orquestração no Chat VR como na interface ativa.
- [x] Migrar projetos arquivados.
- [x] Implementar validação inline e alterações antes de salvar.
- [x] Migrar conteúdo selecionável e rolagem dos logs.
- [x] Manter erros importantes selecionáveis e recuperáveis.

## Fase 8 — validação visual e acessibilidade

Cada lote deve validar:

1. Tema claro e Dark & Orange.
2. 1366×768 e 1920×1080.
3. DPI 100%, 125% e 150%.
4. Conteúdo, vazio, loading, erro e execução.
5. Textos longos, clipping, colisões e scroll.
6. Tab, Shift+Tab, Enter, Espaço, setas e Esc.
7. Nome acessível e tooltip em ações apenas com ícone.
8. Contraste WCAG AA e foco visível.
9. Redução de movimento.
10. Comparação visual com a identidade atual.

Nenhuma captura é considerada validada apenas porque o processo terminou: a
imagem deve ser aberta e inspecionada.

## Fase 9 — empacotamento e ativação

- [x] Declarar arquivos QML como package data.
- [x] Incluir a árvore QML no `VRNorteStudio.spec`.
- [ ] Validar plugins Qt Quick no build limpo.
- [ ] Validar o executável e a distribuição portátil offline.
- [x] Disponibilizar QML como preview interno.
- [x] Fechar a matriz de paridade por tela.
- [x] Tornar QML padrão somente na branch `dev`.
- [x] Manter rollback para Widgets durante um ciclo de estabilização.
- [ ] Remover Widgets somente mediante autorização e aceite manual.

## Critérios finais de conclusão

- 100% das ações da matriz possuem paridade funcional.
- Nenhuma regra de negócio foi movida para QML.
- Nenhum token institucional diverge de `brand.py`.
- Nenhuma ação crítica fica inacessível em 1366×768 a 125%.
- Todos os componentes interativos funcionam por teclado.
- Claro e Dark & Orange mantêm a mesma hierarquia e legibilidade.
- O build instalado e portátil contém QML, fontes, ícones e assets.
- O usuário reconhece imediatamente a interface como VR Norte Studio.
- A troca do frontend padrão só ocorre após validação manual explícita.

## Rollback

Durante a estabilização na branch `dev`, `--legacy-frontend` retorna ao frontend
Qt Widgets sem migração de banco, configuração ou dados. O QML permanece como
entrada padrão e `--qml-preview` é aceito apenas como alias de compatibilidade.

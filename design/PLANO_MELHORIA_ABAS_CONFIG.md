# Plano de melhoria das abas de Configuração

## Objetivo

Alinhar as abas da tela Configurações à identidade visual do VR Norte Studio,
nos frontends QML (padrão) e Qt Widgets (rollback), sem criar uma quarta
linguagem de seleção.

## Diagnóstico validado

1. A aba ativa usava `VrButton variant:"primary"` — o mesmo botão laranja
   sólido da ação principal da tela ("Salvar .env"), competindo com ela e
   violando o princípio de não pintar navegação de laranja.
2. Abas inativas usavam a variante ghost sem borda, sem affordance de controle.
3. As cores de seleção (`#FFE8D6` claro, `#462813` escuro) e de hover
   (`#EAEAF0`) estavam hardcoded no QSS de `ui.py`, fora de `brand.py`.
4. `SettingsPage.qml` usava tamanhos e margens fora dos tokens (`Theme.*`).
5. O diálogo de exclusão de arquivados usava `variant:"primary"` e não exigia
   a frase de confirmação `EXCLUIR`, diferente do `ConfirmDialog` do Widgets.
6. Não havia captura de Configurações no tema Dark & Orange em `build/`.

## Fases

### Fase 1 — token `accentSoft`

- [x] Adicionar `ACCENT_SOFT` (#FFE8D6), `ACCENT_SOFT_HOVER` (#EAEAF0) e
  `DARK_ACCENT_SOFT` (#462813) em `brand.py`.
- [x] Expor `accentSoft` em `brand_palette()` para o QML.
- [x] Substituir os hex hardcoded no QSS de `conversationTabs`,
  `settingsTabs`, `QTabBar` genérico, menus/combos escuros e no chip de
  conversa selecionada.

### Fase 2 — componente `VrTabBar`

- [x] Criar `components/VrTabBar.qml`: pill com raio `radiusControl`, altura
  `compactControlHeight`, seleção com chip `accentSoft`, texto DemiBold.
- [x] Estados hover, foco visível e desabilitado; `Accessible.PageTab` por
  aba e `Accessible.TabBar` no contêiner.
- [x] Teclado: ←/→ trocam de aba; Enter/Espaço ativam; Tab entra no grupo.
- [x] Nunca usar `variant:"primary"` para navegação.

### Fase 3 — cards e tokens

- [x] Adotar o `VrCard` existente no painel Geral.
- [x] Adicionar `Theme.subtitleSize` (16) e trocar tamanhos/margens hardcoded
  por tokens nas quatro abas.

### Fase 4 — ação destrutiva

- [x] Adicionar `variant:"danger"` ao `VrButton` (paridade com `ActionButton`
  do Widgets).
- [x] Diálogo de exclusão exige digitar `EXCLUIR`; botão fica desabilitado
  até a confirmação e usa a variante danger.

### Fase 5 — validação

- [x] Testes: paleta (`accentSoft` nos dois temas), fonte do QML (sem padrão
  antigo de abas, presença de `settingsTabBar`, danger e `EXCLUIR`) e carga
  real da página no engine com troca de abas.
- [x] Capturas de Configurações nos temas claro e Dark & Orange, com
  inspeção visual (`build/abas-config-clara.png`, `build/abas-config-escura.png`).
- [x] Smoke por teclado automatizado (QTest): ←/→ trocam de aba, Enter
  reativa a aba atual, Tab percorre os controles.

### Fase 6 — monitores QHD e 4K

- [x] Preferência "Escala da interface" (100/110/125/150%) no painel Temas,
  persistida em `appearance/ui_scale` e validada por `normalized_ui_scale`.
- [x] A escala é aplicada no arranque via `QT_SCALE_FACTOR`, antes da criação
  do `QApplication` (`apply_ui_scale_environment`); a variável definida
  manualmente pela linha de comando tem precedência.
- [x] Janela principal usa tamanho relativo à tela (88%/86% com teto de
  1760×1120), respeitando os mínimos de 1120×700.
- [x] Configurações centraliza o conteúdo com largura máxima de 1120 px,
  evitando campos esticados em telas largas.
- [x] Capturas de validação em 2560×1440 e 3840×2160.
- [x] Estender a largura máxima centrada às demais páginas: novo componente
  `VrPageColumn` (teto 1120 px) aplicado a Dashboard, Conhecimento,
  Sincronizações, Revisão, Vídeos, Logs e Configurações.
- [x] Paridade da preferência de escala no frontend Widgets: `main` aplica
  `apply_ui_scale_environment(_app_preferences())` antes de criar o
  `QApplication`.

### Fase 7 — ajustes pós-feedback (Dashboard dark)

Diagnóstico por amostragem de pixels do relato do usuário: o canvas estava no
canônico `#12100F`, mas lê como cinza ao lado do rail preto `#000000` e do
Chat VR preto; o cap de 1120 px nas páginas de dados deixava campos vazios
grandes ("as informações não preenchem a tela").

- [x] Páginas de dados voltam a preencher a tela: Dashboard, Conhecimento,
  Sincronizações, Revisão, Vídeos e Logs usam coluna de largura integral;
  `VrPageColumn` (teto 1120 px) permanece apenas em Configurações, onde
  formulários esticados prejudicam a leitura.
- [x] Canvas dark unificado: `DARK_BACKGROUND` #12100F → #000000, eliminando
  o tom cinza e pareando rail, Chat VR e páginas de dados; superfícies
  (#1B1816/#24201D) e bordas permanecem para dar profundidade.
- [x] Testes e capturas atualizados, com verificação de pixel do fundo
  (`build/dashboard-dark-fase7.png`: canvas #000000, cards #1B1816).

### Fase 8 — acabamento pós-feedback (chat e Vídeos)

- [x] Botão de recolher a barra lateral do Chat VR move-se para dentro do
  cabeçalho (primeiro item da linha "Projetos"), com posição estável nos
  estados recolhido e expandido, 34×34 px e alinhado ao breadcrumb.
- [x] Árvore de Vídeos inicia recolhida: gatilho único de inicialização
  (`ensureInitialCollapse`) disparado por mudança de dados, contagem da
  lista e conclusão da página, eliminando a corrida do sinal assíncrono.
- [x] Superfícies dark integradas ao preto: `DARK_SURFACE` #1B1816 →
  #131110, `DARK_SURFACE_RAISED` #24201D → #1B1816 e `DARK_BORDER`
  #3A3A40 → #2C2823 (quente e discreto); botões, linhas e painéis deixam
  de ler como cinza sobre o canvas preto.

### Fase 9 — desempenho na troca de abas

Diagnóstico medido por benchmark no engine (offscreen): a recriação do
ChatPreview custava 40-110 ms por troca e as demais páginas 8-22 ms, porque
cada `Loader` destruída e recriava a página visitada.

- [x] Páginas permanecem vivas após a primeira visita: `Main.qml` mantém Chat
  VR e o hub em Loaders próprios (`chatVisited`/`hubVisited`); `SettingsHub`
  mantém as sete páginas em Loaders explícitos com `visitedPages`.
- [x] Delegados de `Repeater` não recebem QObject parent — os Loaders são
  explícitos para `window.findChild` continuar encontrando as páginas.
- [x] `FrontendBridge.palette` passa a cache o dicionário de cores (era
  reconstruído a cada leitura de binding) e o invalida em `setTheme`.
- [x] Resultado medido: revisitas de 8-44 ms para 0,3-0,8 ms por troca.

## Critério de aceite

- As abas usam o mesmo chip de seleção do restante do app; o laranja sólido
  aparece apenas na ação principal de cada aba.
- Zero hex de aba fora de `brand.py`/`Theme.qml`.
- Navegação por teclado completa e nomes acessíveis nas abas.
- Nenhuma regressão visual nas abas de conversa do Chat VR (mesmo token).
- Em 2560×1440 e 3840×2160 a janela abre proporcional à tela, o conteúdo de
  Configurações permanece legível e centrado, e a escala 125%/150% amplia
  toda a interface sem cortes ou sobreposições.
- Nas páginas de dados o conteúdo preenche a largura da janela em qualquer
  resolução; no tema Dark & Orange o canvas é preto, sem tom cinza, em todas
  as telas (rail, chat e páginas).

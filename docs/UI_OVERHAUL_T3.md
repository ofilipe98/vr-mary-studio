# Refinamento visual e escala da interface

Referência inspecionada: `pingdotgg/t3code`, commit
`2efb8178d83f4f7c4ccc3ae1165f2a2ded0b2742`.

O VRStudio mantém Qt Quick, seus temas e o destaque laranja dos modos VR/Ultra.
O trabalho adapta a hierarquia visual e o comportamento de escala da referência
às telas próprias do produto, incluindo catálogo de aplicativos, conhecimento,
sincronizações, revisão e vídeos. Não representa equivalência de renderização
pixel a pixel entre Chromium e Qt.

## Referência e decisões

| Referência T3 Code | Aplicação no VRStudio |
| --- | --- |
| [appearanceFonts.ts](https://github.com/pingdotgg/t3code/blob/2efb8178d83f4f7c4ccc3ae1165f2a2ded0b2742/apps/web/src/appearanceFonts.ts): fonte do sistema, interface de 16 px como raiz e dimensões em rem | Segoe UI no Windows; `Theme.interfaceScale` aplica a proporção da fonte também aos espaçamentos, controles e dimensões compartilhadas. Preferências de fonte existentes são preservadas. |
| Prompt e código têm tamanhos próprios em pixels | No modo avançado, mudar a fonte da interface não multiplica novamente prompt, código ou terminal. O modo simples continua seguindo as preferências vinculadas já existentes. |
| [DesktopWindow.ts](https://github.com/pingdotgg/t3code/blob/2efb8178d83f4f7c4ccc3ae1165f2a2ded0b2742/apps/desktop/src/window/DesktopWindow.ts): zoom da janela separado do zoom do navegador incorporado | Escala visível em Aparência; Ctrl +, Ctrl − e Ctrl 0. Texto, controles e espaçamento acompanham a escala. A preferência de zoom do Browser e a escala de DPI do Windows permanecem independentes. |
| [index.css](https://github.com/pingdotgg/t3code/blob/2efb8178d83f4f7c4ccc3ae1165f2a2ded0b2742/apps/web/src/index.css) e [button.tsx](https://github.com/pingdotgg/t3code/blob/2efb8178d83f4f7c4ccc3ae1165f2a2ded0b2742/apps/web/src/components/ui/button.tsx): raios de controles de 0,5 rem, controles compactos e hierarquia discreta | Raios de 8 px na base, altura compacta de 32 px, subtítulos de página menores com quebra de linha, abas sublinhadas e dimensões proporcionais. |
| Botões do `button.tsx` em largura desktop (`sm:`): `default` 32, `compact`/`sm` 28, `xs`/`icon-xs` 24, `micro` 20; caixas de ícone `icon-sm` 28 e `icon` 32 com glifo 16 | `Theme.controlHeightCompact` 32, `compactControlHeight` 28, `iconButtonCompact` 24, `iconButtonNormal` 28 (padrão de `VrIconButton`, glifo 16) e `iconButtonLarge` 32. O cabeçalho do painel lateral usa 24 + glifo 14, como `Add project`/`Add action`. |
| `--sidebar-width` 256 (mínimo 208), `--sidebar-content-inset` 8, `--sidebar-row-content-inset` 10, `--sidebar-control-gap` 8, linha de busca `h-8` | `Theme.navigationWidth` 256 e `navigationWidthMinimum` 208 na barra de conversas e na navegação de Configurações; `sidebarContentInset` 8, `sidebarRowInset` 10, `sidebarRowHeight` 32 e `VrNavItem` com raio 8 e espaçamento 8. |
| Coluna do chat `max-w-3xl` (768) | `Theme.contentWidth` 768 para mensagens, landing e composer. |
| `.chat-markdown`: corpo `text-sm` (14) com `leading-relaxed` (1.625), títulos 1.25/1.125/1/0.875 rem com `line-height:1.3` e `margin:1.25rem 0 .5rem`, código inline e tabela `.75rem`, citação com borda de 2 px | `VrMarkdownContent`/`VrUserMessage` em `Theme.markdownBodySize` (14) e `frontend/text_rendering.py` aplicando as mesmas razões de margem, entrelinha e tamanho por fragmento (tabelas em `Theme.markdownTableSize` 12, `VrCodeBlock` com cabeçalho de 30 px e padding `.8rem .9rem`). |
| `.chat-markdown :not(pre)>code`: fundo `--muted`, borda `1px solid var(--contrast-border)`, raio `.375rem` e padding `.1rem .35rem` | O tema mapeia `inlineCodeSurface` para `muted` e `VrInlineChipLayer` repinta o chip arredondado atrás do texto (`Theme.inlineChip*`); o padding horizontal é aproximado porque o layout de texto do Qt não reserva esse espaço. |

O Electron usa incrementos de 0,5 no nível de zoom. A adaptação Qt usa os passos
90, 100, 110, 125 e 150%, mantendo também a leitura das preferências granulares
101–105% anteriormente salvas. `auto` equivale à base de 100% em pixels lógicos
Qt; redimensionar a janela não muda o tamanho da fonte automaticamente. A moldura
e os controles nativos da janela continuam com dimensões próprias.

## Superfícies revisadas

- Dashboard: cartões com ritmo consistente, rolagem e ações adaptáveis.
- Conhecimento e Revisão: filtros e ações se reorganizam; a lista e os detalhes
  se empilham em janelas estreitas, mantendo busca, paginação e decisões.
- Sincronizações, Vídeos e Logs: dimensões compartilhadas proporcionais;
  confirmação de sincronização com layout e botões do próprio tema.
- Configurações: oito subabas, Aparência e seus diálogos, Provedores, Skills,
  catálogo e versões. Cabeçalhos e controles se reorganizam quando falta espaço.
- Chat: composer, código, tabelas, pickers e chamadas de ferramentas usam a
  mesma base de escala. O cabeçalho de atividades tem indicação explícita de
  expansão; o conteúdo e a correlação dos eventos de ferramentas não mudam.
- Navegação compacta mantém todas as páginas acessíveis. Perfis do chat podem
  rolar horizontalmente e ser acionados pelo teclado. Abas mantêm a seleção
  visível ao redimensionar ou mudar a escala.
- Painel lateral: um contêiner dedicado participa do SplitView; navegador e
  terminal passam para overlay sem herdar coordenadas antigas do desktop.

## Validação reproduzível

Os scripts usam dados e preferências temporários. Capturas e relatórios ficam em
`.test-tmp/overhaul-final/` e não são incluídos no repositório.

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q --durations=10
.\.venv\Scripts\python.exe scripts/visual_core_pages_review.py .test-tmp/overhaul-final/core-complete
.\.venv\Scripts\python.exe scripts/visual_settings_all_tabs_review.py .test-tmp/overhaul-final/settings-refined
.\.venv\Scripts\python.exe scripts/visual_chat_review.py .test-tmp/overhaul-final/chat
git diff --check
```

A matriz cobre temas claro/escuro, larguras de 390 a 1920 px e escalas de 100,
125 e 150%, conforme os cenários de cada script. A revisão de páginas principais
agora falha também se detectar problemas de geometria. Os testes de Aparência
cobrem escala, tipografia independente, navegação compacta e a transição do
painel entre desktop e janela estreita.

As capturas de tool calling usam eventos simulados. Elas verificam apresentação
e expansão; não são certificação de execução com provedores reais.

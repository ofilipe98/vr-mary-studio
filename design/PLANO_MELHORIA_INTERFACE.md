# Plano de melhoria da interface do VR Norte Studio

## Objetivo

Construir uma interface coesa, rápida e acessível para Chat VR e para os demais
módulos do Studio. A referência de qualidade é a clareza do T3 Code, preservando
a identidade Dark & Orange e os fluxos específicos do VR Norte Studio.

O trabalho deve evoluir por componentes compartilhados. Nenhuma tela deve criar
uma quarta variação de botão, seletor, popup ou mensagem de estado.

## Diagnóstico

A interface atual combina três linguagens visuais:

1. componentes próprios, como o composer e os seletores de modelo;
2. controles Qt estilizados globalmente;
3. menus e diálogos nativos com geometria e indicadores dependentes do Windows.

Essa mistura provoca diferenças de raio, altura, alinhamento, ícones, foco,
seleção e densidade. O antigo seletor de projetos era o exemplo mais visível:
usava ícone do sistema, QMenu, check lateral e popup sem relação geométrica
forte com o botão.

## Princípios

- A ação principal deve ser evidente, sem pintar todas as ações de laranja.
- Seleção usa a linha completa; check e cor são confirmações complementares.
- Todo controle interativo precisa de hover, foco, pressionado, desabilitado e
  carregando quando aplicável.
- Ícones são SVGs de 16 px, monocromáticos e independentes do sistema.
- Popups são alinhados ao controle de origem e respeitam os limites da tela.
- Informações secundárias aparecem por hierarquia tipográfica ou tooltip.
- Operações destrutivas nunca compartilham a aparência de ações comuns.
- Tema claro e Dark & Orange oferecem os mesmos estados e contraste.

## Tokens

| Categoria | Valores |
|---|---|
| Espaçamento | 4, 8, 12, 16, 24 e 32 px |
| Altura compacta | 32–34 px |
| Altura padrão | 38–40 px |
| Linha de lista | 36 px; 52 px quando há descrição |
| Raios | 8 px linha; 10 px controle; 12–14 px popup; 18 px card |
| Ícones | 16 px; 20 px apenas em navegação principal |
| Animação | 120–160 ms; respeitar redução de movimento |
| Foco claro | laranja acessível com borda contínua |
| Foco escuro | laranja claro com contraste mínimo de 3:1 |

## Componentes canônicos

### Fundação implementada

- SurfaceMenu: menu contextual com dimensões, separadores e seções comuns.
- ProjectScopeButton: gatilho composto com pasta, rótulo e chevron.
- ProjectScopePopup: popup ancorado, filtrável e operável por teclado.
- RoundedComboBox: seletor simples.
- ModelPickerCombo: seletor rico com busca e metadados.
- RoundedPopupDialog: base dos popups e diálogos personalizados.
- ConfirmDialog: confirmação comum, aviso modal e consentimento destrutivo
  digitado.
- TextPromptDialog: edição multiline com prevenção de envio vazio ou inalterado.
- ToastBanner: sucesso, informação, aviso e erro sem interromper o trabalho.
- DataToolbar: busca persistente, filtros ativos, contador, densidade e ação
  principal responsivos.
- DataContentStack: alternância canônica entre conteúdo, estado vazio e skeleton.
- EmptyState: ausência de dados com explicação e ação de recuperação.
- LoadingSkeleton: carregamento estático, sem animação contínua ou repaint.
- PaginationBar: página, intervalo, total e navegação no mesmo componente.

### Componentes complementares implementados

- [x] ActionButton: primary, secondary, ghost e danger.
- [x] FormField: rótulo, controle, ajuda, validação e erro.
- [x] StatusBadge: idle, running, success, warning e error.
- [x] ContextActionMenu: ações secundárias de projeto e demais entidades.
- [x] SimpleFilterGroup: contagem e limpeza compartilhadas entre telas.

## Fases

### Fase 1 — navegação e seletores

- [x] Substituir o seletor nativo de projetos.
- [x] Alinhar popup, seleção, ícones, busca e teclado.
- [x] Criar superfície comum para menus contextuais.
- [x] Consolidar a ação de adicionar no rodapé do seletor.
- [x] Adicionar ações de projeto: abrir pasta e remover dos recentes.
- [x] Unificar os filtros simples em uma única API de seletor.

Critério de aceite: nenhum seletor principal usa emoji, ícone de plataforma ou
popup desalinhado; Tab, setas, Enter e Esc funcionam.

### Fase 2 — Chat VR

- [x] Consolidar cabeçalho, estado da conversa e ações em uma barra responsiva.
- [x] Transformar o menu VR em painel de opções com descrição dos modos.
- [x] Exibir claramente provedor, modelo, raciocínio, permissão e modo ativo.
- [x] Confirmar o padrão compartilhado dos chips de arquivos, skills, tools e
  contexto.
- [x] Melhorar estados de execução, cancelamento, erro e aprovação.
- [x] Exibir reconexão quando o provider Codex reiniciar sua conexão local.
- [x] Manter saída completa de cada agente no painel individual e somente a síntese
  final na conversa principal.

Critério de aceite: o usuário identifica configuração e estado do turno sem
abrir menus; nenhum estado impossível permite envio ou troca insegura.

### Fase 3 — diálogos e feedback

- [x] Inventariar usos de QMessageBox, QInputDialog e QFileDialog.
- [x] Migrar confirmações para ConfirmDialog e a edição multiline para
  TextPromptDialog.
- [x] Manter QFileDialog onde a integração nativa de arquivos é vantajosa.
- [x] Substituir mensagens de sucesso e orientação bloqueantes por ToastBanner.
- [x] Exigir a frase `EXCLUIR` apenas para exclusão definitiva.
- [x] Manter erros modais, selecionáveis e com ação explícita para fechamento.
- [x] Validar diálogos e toasts nos temas claro e Dark & Orange.

Critério de aceite: erros explicam causa e recuperação; sucesso não interrompe o
fluxo; foco retorna ao controle que abriu o diálogo.

### Fase 4 — dados e conteúdo

- [x] Aplicar DataToolbar em Conhecimento, Revisão, Vídeos e Sincronizações.
- [x] Manter busca, quantidade, filtros ativos, densidade e ação principal no
  cabeçalho de dados.
- [x] Unificar filtros recolhíveis e contagem de filtros ativos.
- [x] Aplicar PaginationBar em Conhecimento e Revisão, com 100 itens por página.
- [x] Criar LoadingSkeleton estático e estados vazios acionáveis.
- [x] Tornar tabelas legíveis em 1366×768 sem esconder ações críticas.
- [x] Padronizar e persistir densidade confortável e compacta entre telas.
- [x] Validar conteúdo, vazio e carregamento nos temas claro e Dark & Orange.
- [x] Validar 1366×768 e 1920×1080 por capturas inspecionadas.

Critério de aceite: busca, filtro ativo, quantidade de resultados e ação
principal permanecem visíveis e semanticamente consistentes.

### Fase 5 — acessibilidade e acabamento

- [x] Definir ordem de Tab explícita para Chat VR, Conhecimento,
  Sincronizações, Revisão, Vídeos e Aparência.
- [x] Adicionar nome acessível e tooltip aos botões somente com ícone,
  inclusive limpeza de campos.
- [x] Validar contraste WCAG AA para texto e estados de foco nos dois temas.
- [x] Garantir alvos de clique mínimos de 32×32 px, inclusive na densidade
  compacta.
- [x] Validar zoom/DPI de 100%, 125% e 150% por capturas reais.
- [x] Adicionar preferência persistente de redução de movimento e remover a
  animação contínua do modo Ultra.
- [x] Revisar truncamento, textos longos, tooltips integrais e português.

Critério de aceite: a navegação principal funciona por teclado, controles
gráficos têm descrição equivalente, nenhum efeito decorativo repinta
continuamente e a interface permanece legível nas três escalas suportadas.

## Matriz de validação

Cada lote deve passar por:

1. testes unitários de estado, sinais e persistência;
2. testes de teclado e fechamento de popup;
3. smoke gráfico em tema claro e Dark & Orange;
4. capturas em 1366×768 e 1920×1080;
5. inspeção da imagem, não apenas código de saída;
6. comparação de geometria, contraste, clipping e colisões;
7. regressão dos fluxos de conversa, projeto e execução;
8. execução em build portátil antes da promoção.

## Métricas

- zero emojis usados como ícones funcionais;
- zero seletores principais dependentes de QMenu;
- 100% dos botões de ícone com nome acessível e tooltip;
- 100% dos popups fechando com Esc e clique externo;
- nenhuma ação crítica inacessível em 1366×768 a 125% de escala;
- nenhum tema com texto, foco ou seleção ilegíveis;
- nenhuma promoção para main antes do teste manual do usuário.

## Estratégia de entrega

As alterações permanecem na branch dev. Cada fase deve gerar um lote pequeno,
testável e reversível. Arquivos locais preexistentes são preservados, e commits,
pushes, builds publicadas ou promoção para main exigem autorização explícita.

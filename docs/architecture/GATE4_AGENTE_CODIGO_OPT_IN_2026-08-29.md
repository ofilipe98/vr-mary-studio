# Gate 4 — Agente de Código opt-in no VR Ultra

Data: 2026-08-29

## Decisão

O Agente de Código é opcional e fica desligado por padrão. A configuração é
salva por usuário, junto da release explicitamente escolhida. Isso evita custo
em perguntas puramente documentais e permite defaults diferentes para Suporte,
Implantação e Treinamento.

## Fluxo implementado

1. O orquestrador lê `codeAnalysisEnabled` e `codeAnalysisRelease` no início do
   turno.
2. Os três pesquisadores base rodam em paralelo e delimitam o assunto.
3. Se o toggle estiver ligado, termos de código são extraídos da solicitação e
   dos achados já condensados.
4. O worker consulta a ferramenta `JavaCodeIndex`; não recebe o JAR nem o índice
   inteiro.
5. Até oito fontes candidatas, com release/JAR/classe/linhas/hash, formam o
   contexto isolado do Agente de Código.
6. O agente deve retornar JSON no contrato fixo de achados, conflitos, lacunas,
   avisos e IDs de evidência permitidos.
7. A síntese recebe número variável de relatórios e reconcilia código com as
   outras fontes.

## Controles

- O plano da execução registra o worker opcional e a release selecionada.
- Eventos `agent_started`, `agent_completed` e `agent_failed` identificam o
  Agente de Código.
- Uma falha de busca ou de modelo não bloqueia a síntese.
- Se o modelo do worker falhar após a recuperação, os trechos citáveis ainda
  podem ser usados como fallback determinístico, com aviso.
- Resultados de uma release desatualizada carregam confiança reduzida e aviso de
  frescor; não são apresentados silenciosamente como atuais.
- Toggle desligado mantém exatamente o fan-out anterior, sem consulta ao índice
  nem chamada adicional de modelo.

## Validação automatizada

- opt-out não cria o worker de código;
- opt-in usa a release configurada e roda depois do escopo;
- a citação conserva o JAR;
- a preferência sobrevive à reabertura da interface;
- falha do índice emite `agent_failed` e a síntese ainda conclui.

## Pendências antes de generalizar

- validar chamados reais cuja causa conhecida estava no código, ligado versus
  desligado;
- adicionar embeddings ao AST tolerante e ao grafo sintático entregues no Gate 5;
- seletor de releases inventariadas entregue no Gate 7;
- medir tokens e latência do quarto agente por perfil de usuário;
- validar em uso real o perfil sênior e os modos formalizados no Gate 6.

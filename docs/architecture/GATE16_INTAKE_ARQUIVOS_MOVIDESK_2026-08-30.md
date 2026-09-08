# Gate 16 — intake de arquivos Movidesk

Data da validação: 2026-08-30

Origem local analisada: `C:\Users\ofili\Downloads\Auditoria`

## Objetivo

Transformar páginas de tickets salvas como ZIP em candidatos auditáveis, sem
copiar o conteúdo bruto para o repositório e sem enviar mensagens ou anexos a
um modelo.

## Material recebido

Foram encontrados 17 arquivos válidos:

| Canal | Quantidade |
| --- | ---: |
| N1 → cliente | 8 |
| N2 → N1 | 9 |
| Total com status resolvido | 17 |

Os arquivos possuem 21 ações estruturadas. Em diversos casos, uma única ação
contém um histórico maior incorporado; portanto a contagem de ações não pode
ser tratada como contagem de interações.

A classificação local sugeriu cinco candidatos N2 com termos relacionados a
código ou desenvolvimento. Isso é suficiente para triagem, mas não confirma
cinco causas-raiz em código. Nenhum candidato foi promovido automaticamente ao
benchmark.

## Controles implementados

O leitor:

- abre os ZIPs em modo somente leitura e nunca extrai caminhos do arquivo;
- limita número de entradas e tamanho do `index.html`;
- rejeita arquivo criptografado, inválido ou sem exatamente um `index.html`;
- registra SHA-256 do ZIP como identidade estável;
- separa os canais `n1_client` e `n2_n1`;
- extrai somente assunto, status e ações necessários à revisão;
- produz inventário seguro sem assunto, mensagem, nome ou número do ticket;
- classifica módulo apenas como sugestão, nunca como JAR confirmado;
- mantém `eligible_for_code_benchmark: false` até revisão humana.

## Pacote de revisão e chave

O preparo gera dois arquivos:

1. `tickets-review.json`: conteúdo pseudonimizado, candidatos e campos vazios
   para decisão humana;
2. `tickets-source-key.json`: caminho original, número do ticket e hash,
   marcado como sensível e proibido para compartilhamento com o revisor.

O redator remove padrões suportados de e-mail, telefone, CPF, CNPJ, URL, IP,
credencial, caminho de usuário e IDs de tickets presentes no conjunto. Também
substitui identidades encontradas nos campos estruturados, saudações, UUIDs e
nomes de anexos.

Após a geração real:

- zero padrão sensível suportado permaneceu no pacote;
- zero número bruto de ticket permaneceu no pacote;
- zero caminho de origem permaneceu no pacote;
- zero caractere de substituição de encoding foi encontrado;
- zero saudação com identidade residual foi encontrada.

Mesmo assim, `safe_for_model` permanece `false`: nomes citados fora dos campos
estruturados e contexto capaz de identificar clientes ainda exigem inspeção
humana. Automação sem achados não equivale a anonimização comprovada.

## Comandos

```powershell
# Inventário sem conteúdo do ticket
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  audit-movidesk-ticket-archives `
  "C:\Users\ofili\Downloads\Auditoria"

# Pacote local para revisão + chave de origem separada
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  prepare-movidesk-ticket-review `
  "C:\Users\ofili\Downloads\Auditoria" `
  --output "C:\Users\ofili\Downloads\Auditoria\_processado\tickets-review.json" `
  --key-output "C:\Users\ofili\Downloads\Auditoria\_processado\tickets-source-key.json"
```

Os comandos executam antes da inicialização do workspace, não carregam
credenciais e recusam sobrescrever arquivos existentes.

## Saídas reais

- pacote: `Auditoria\_processado\tickets-review.json`;
- chave: `Auditoria\_processado\tickets-source-key.json`;
- primeira geração preservada em `Auditoria\_processado\superseded\` após o
  redator ser endurecido para referências cruzadas e saudações.

O pacote atual possui SHA-256
`5ADB14685690A9BFD4F8D816EDF3D04ABAE599A645837A1AE35F17AC55B3DF48`.

## Decisão sobre quantidade

Não é necessário coletar mais tickets aleatórios neste momento. Primeiro devem
ser revisados os cinco candidatos N2 indicados pelo inventário. Se menos de
cinco contiverem causa-raiz confirmada, o próximo pedido deve ser específico:
tickets N2 com retorno de desenvolvimento, correção/versão confirmada, classe ou
módulo identificado, ou vínculo com fechamento de Jira/Redmine. Mais tickets N1
sem desfecho técnico não aumentam a qualidade do benchmark de código.

## Próximo gate

Adicionar finalização do pacote revisado: validar a aprovação humana, selecionar
5–10 casos elegíveis, converter apenas esses casos para o schema do benchmark e
exigir novamente o scanner e o manifesto SHA-256 do Gate 15.

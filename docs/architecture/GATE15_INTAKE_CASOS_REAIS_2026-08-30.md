# Gate 15 — intake auditável dos casos reais

Data da validação: 2026-08-30

## Objetivo

Impedir que uma suíte declarada como `anonymized` chegue ao provedor apenas por
autodeclaração. Os casos precisam ter sido resolvidos, selecionados antes da
execução, revisados localmente e congelados por conteúdo.

Este gate não executa modelos e não cria casos fictícios para representar
chamados reais.

## Gap corrigido

O Gate 14 comprovava release, cobertura, símbolos e integridade da revisão
cega, mas `data_classification: anonymized` ainda era somente um campo JSON. Não
existiam controles para:

- limitar a amostra real aos 5–10 casos planejados;
- registrar o universo candidato e o método de seleção;
- comprovar que cada causa-raiz vinha de um chamado encerrado;
- detectar dados sensíveis óbvios antes de aprovar o envio;
- provar que perguntas e critérios não mudaram depois da seleção.

## Contrato da suíte real

Uma suíte `anonymized` precisa declarar:

- `candidate_pool_size`, maior ou igual ao número selecionado;
- `selection_method`, descrevendo a seleção anterior às respostas;
- `anonymization_review_id`, identificador técnico sem nome pessoal;
- entre 5 e 10 casos;
- `module`, `root_cause_evidence` e `resolved_at` em cada caso;
- os campos objetivos já exigidos pelo Gate 14.

Mais de 60% dos casos em um único módulo ou cobertura de apenas um módulo gera
aviso de viés. O aviso não é escondido e limita a possibilidade de generalizar
o resultado para todo o ERP.

## Auditoria local de dados sensíveis

Antes do congelamento, um scanner determinístico procura indícios de:

- e-mail;
- telefone formatado;
- CPF e CNPJ com dígitos verificadores válidos;
- endereço IPv4;
- URL;
- caminho de usuário Windows, macOS ou Linux;
- credencial atribuída a campos como senha, token ou chave de API.

O relatório nunca repete o valor encontrado. Ele registra somente caso, campo,
tipo e um fingerprint curto, suficiente para localizar e corrigir o campo sem
espalhar o dado.

Esse scanner reduz vazamentos óbvios, mas não reconhece com segurança nomes,
endereços em linguagem natural, apelidos internos ou contexto capaz de
identificar um cliente. Por isso `anonymization_review_id` representa uma
revisão humana obrigatória; resultado sem achados não significa garantia de
anonimização completa.

## Congelamento e execução

Após a auditoria ficar verde, o comando de congelamento grava um manifesto com:

- SHA-256 do conteúdo semântico completo da suíte;
- release e classificação;
- data UTC do congelamento;
- tamanho da amostra e do conjunto candidato;
- distribuição por módulo e modo de resposta;
- avisos de viés.

O preflight e o benchmark exigem esse manifesto para casos reais. Qualquer
alteração posterior em pergunta, causa, critério, JAR, módulo ou metadado muda o
SHA-256 e bloqueia a execução. `--max-cases` também não pode reduzir uma amostra
real congelada. Suítes `synthetic` continuam dispensadas do manifesto e podem
ser reduzidas para ensaios, mas passam pelo scanner local.

```powershell
# 1. Auditar sem abrir workspace nem chamar modelo
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  audit-code-analysis-cases casos-codigo.json

# 2. Congelar somente depois da revisão humana
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  freeze-code-analysis-cases casos-codigo.json `
  --output casos-codigo.intake.json

# 3. Verificar release, índice, símbolos e manifesto sem chamar modelo
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject preflight-code-analysis casos-codigo.json `
  --intake-manifest casos-codigo.intake.json

# 4. Aprovar custo e envio apenas quando todas as barreiras estiverem verdes
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject benchmark-code-analysis casos-codigo.json `
  --intake-manifest casos-codigo.intake.json `
  --provider codex --model <modelo> --approve-model-usage
```

Os comandos de auditoria e congelamento rodam antes da inicialização do
workspace e não carregam credenciais de Wiki, Endoo ou Movidesk. Arquivos
existentes não são sobrescritos.

## Critérios de aceite

- suíte real fora da faixa de 5–10 casos é bloqueada;
- causa sem evidência de resolução ou data válida é bloqueada;
- CPF, CNPJ, e-mail e demais padrões suportados são bloqueados localmente;
- relatório de achados não reproduz o conteúdo sensível;
- manifesto só é criado para uma auditoria aprovada;
- qualquer mudança posterior invalida o fingerprint;
- preflight e benchmark reais recusam manifesto ausente ou divergente;
- nenhuma chamada de modelo ocorre em auditoria, congelamento ou preflight;
- viés de distribuição permanece explícito no manifesto e no preflight.

## Estado e próxima entrada

A infraestrutura está pronta, mas ainda não há uma suíte real no workspace.
Para iniciar a medição, o responsável precisa selecionar 5–10 chamados
encerrados entre os sete módulos principais atualmente cobertos, remover dados
de cliente, registrar a evidência da causa e executar a auditoria local. Somente
o pacote A/B, nunca a chave `off/on` ou a causa conhecida, deve ser entregue ao
revisor cego.

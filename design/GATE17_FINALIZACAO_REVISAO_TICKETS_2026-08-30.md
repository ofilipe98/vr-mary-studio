# Gate 17 — finalização da revisão de tickets

## Objetivo

Transformar a revisão humana local do Gate 16 em uma suíte anonimizada e já
congelada para o benchmark pareado do Agente de Código, sem enviar ao modelo o
assunto ou as ações originais do ticket.

## Contrato de entrada

A finalização recebe dois arquivos gerados juntos pelo comando
`prepare-movidesk-ticket-review`:

- pacote pseudonimizado, ainda marcado `safe_for_model: false`;
- chave sensível de origem, mantida localmente e fora da revisão compartilhada.

O revisor pode alterar somente o bloco `review`. Para cada caso selecionado,
precisa registrar:

- `anonymization_approved: true`;
- `eligible_for_code_benchmark: true`;
- `benchmark_title` e `benchmark_question`, ambos anonimizados;
- `resolved_at`, `module` e ao menos um `target_jars` terminado em `.jar`;
- `known_root_cause` e `root_cause_evidence` confirmadas após a resolução;
- ao menos um item em `expected_terms`, `expected_code_symbols` e
  `expected_citation_sources`;
- `forbidden_terms`, quando houver hipótese já descartada.

Status Resolvido, presença da palavra “bug” ou encaminhamento ao N2 não bastam
para aprovação. O revisor deve encontrar evidência de que a causa estava no
código e de que a correção produziu o resultado esperado.

## Barreiras de integridade

`finalize-movidesk-ticket-review` bloqueia a operação quando:

1. pacote e chave não têm o mesmo `packet_id`, fingerprints ou conjunto de
   candidatos;
2. qualquer parte imutável do pacote foi alterada depois da preparação;
3. foram escolhidos menos de 5 ou mais de 10 casos;
4. um caso escolhido não tem aprovação humana de anonimização;
5. faltam causa-raiz, evidência, data, módulo, JAR ou critérios objetivos;
6. os detectores encontram e-mail, telefone, CPF/CNPJ, URL, IP, caminho de
   usuário ou credencial nos campos preenchidos manualmente;
7. a release não foi escolhida explicitamente.

O scanner reduz risco, mas não reconhece todo nome próprio ou contexto de
cliente. Por isso, aprovação humana continua obrigatória.

## Saídas e auditabilidade

A operação gera, sem sobrescrever arquivos:

- suíte `anonymized` no schema do benchmark existente;
- manifesto com SHA-256 da suíte e identificação do pacote, do conjunto-fonte
  e dos candidatos selecionados.

O manifesto nasce na mesma execução que valida a revisão. Qualquer edição
posterior da suíte invalida seu fingerprint no preflight. O comando não chama
modelo, não consulta os JARs e não executa o benchmark.

## Critérios objetivos de aceite

- uma amostra de 5–10 casos aprovados produz suíte aceita por
  `audit-code-analysis-cases`;
- `verify_benchmark_intake_manifest` confirma o fingerprint;
- adulteração de assunto, ações ou metadados pseudonimizados é bloqueada;
- inclusão manual de padrão sensível é bloqueada sem reproduzir o valor;
- arquivos de saída existentes nunca são sobrescritos;
- release e identificador da revisão ficam explícitos na trilha de auditoria.

## Estado da amostra de Auditoria

Os 17 tickets disponíveis são suficientes para triagem, mas ainda não para o
benchmark: nenhum pode ser promovido automaticamente. A próxima ação humana é
revisar primeiro os candidatos N2 priorizados e aprovar de 5 a 10 casos com
causa em código comprovada. Se menos de 5 atenderem ao contrato, será necessário
fornecer mais tickets já resolvidos com evidência técnica de desenvolvimento.

# Gate 19 — releases incrementais por `vr*.properties`

## Objetivo

Detectar aplicação e versão diretamente em cada JAR, sem modelo, e suportar os
pacotes de atualização do ERP que contêm somente as aplicações alteradas.

## Contrato local

1. Para `VRMaster.jar`, procurar `vrmaster.properties`; a mesma regra vale para
   as demais aplicações, sem diferenciar maiúsculas de minúsculas.
2. Ler exclusivamente `versao.major`, `versao.minor`, `versao.release`,
   `versao.build`, `versao.beta` e `app.data`.
3. Não persistir outras propriedades. Isso evita levar chaves de telemetria ou
   configurações internas para logs, prompts e manifestos.
4. Quando o arquivo correspondente não existir, usar o nome do JAR como
   aplicação, marcar a versão como `unknown` e diferenciar conteúdo pelo
   SHA-256.
5. Materializar snapshots em
   `<release>/jars/<aplicação>/<versão>/<jar>`, sempre por cópia verificada. Não
   usar hard links, pois uma atualização in-place da origem alteraria o snapshot.

## Pacotes parciais

- Pacote com 46 aplicações: forma uma nova base completa.
- Pacote com menos aplicações: seleciona a release completa mais recente, copia
  os JARs não presentes no pacote e substitui somente as aplicações recebidas.
- Sem base completa: falha de forma explícita e não cria snapshot parcial.
- Aplicações duplicadas no mesmo pacote: falha antes de copiar.
- Aplicação nova ou ausente que faça a composição divergir de 46: falha antes
  de publicar o manifesto.

## Proveniência obrigatória

O manifesto registra:

- `base_release_id`;
- `package_jar_count`;
- `updated_applications`;
- `carried_forward_jar_count`;
- versão e arquivo `.properties` de cada componente;
- origem `package` ou `base` para cada JAR;
- hash da composição final.

## Validação

- detector unitário sem vazamento de propriedades não permitidas;
- pacote completo categorizado;
- pacote parcial composto sobre base completa;
- pacote parcial rejeitado sem base;
- fallback para JAR sem arquivo de versão;
- fluxo CLI e fluxo QML sem chamada a modelo;
- varredura real do pacote de 46 JARs antes de habilitar a importação em campo.

# Gate 12 — classpath, duplicatas e seleção efetiva do runtime

Data da validação: 2026-08-30

Release selecionada: `current`
SHA-256 do manifesto: `93217be54b3f1e9f7323547ef2f22add4c6b2b7224733135a54465b842106f33`

## Resultado

O classpath deixou de ser apenas um booleano no manifesto. O Studio agora
possui:

1. índice incremental de classes efetivas por hash de artefato;
2. distinção entre alias físico, múltiplos cabeçalhos e bytecodes conflitantes;
3. regra reproduzível para duplicatas dentro do mesmo JAR;
4. perfis de classpath por aplicação/release;
5. sinalização de resolução em cada resultado de busca e chamada sintática;
6. redução automática de confiança no Agente de Código quando a variante é
   ambígua ou o índice não cobre a classe.

Não foi configurado um perfil completo para a release real, pois a ordem do
launcher ainda não foi fornecida. Os 19 `Class-Path` encontrados nos manifestos
são publicados como candidatos parciais, nunca como prova do runtime.

## Seleção interna confirmada com Java

O utilitário `scripts/JarEntryProbe.java` consulta o mesmo
`java.util.jar.JarFile` utilizado pelo runtime. A prova foi executada com o Java
17 isolado sobre `VRAtacado.jar` e a classe
`com/google/common/annotations/GwtCompatible.class`.

O JAR contém duas variantes físicas:

| Ordem central | Tamanho | SHA-256 |
| ---: | ---: | --- |
| primeira | 640 bytes | `7d603fb82e9db41ce6efd2c1149a4e2c2bac10ed5aa47e96aeb84c97567cddfe` |
| última | 600 bytes | `5a7fd8f567fea7883e8c94fdb8989c6c2f3fa53ae4c9839eec9d244a81ef4498` |

`JarFile.getJarEntry` devolveu a segunda variante. Portanto, a regra persistida
é `last_central_directory_entry`. As variantes anteriores continuam registradas
como divergência; não são apagadas nem apresentadas como efetivas.

## Medição dos 46 JARs

| Métrica | Resultado |
| --- | ---: |
| JARs analisados | 46/46 |
| Duplicatas internas | 22.170 |
| Conflitos internos de bytecode | 2.629 |
| Classes presentes em múltiplos JARs | 109.421 |
| Conflitos efetivos entre JARs | 29.090 |
| Perfis candidatos de manifesto | 19 |
| Erros | 0 |

A primeira execução analisou 46 artefatos. A segunda reutilizou 46/46 pelo
SHA-256, sem reler o bytecode.

O banco `classpath.sqlite` ocupa 575.897.600 bytes. O uso total do índice passou
para 3.066.509.688 bytes e a projeção conservadora para os 36 JARs pendentes
ficou em 30.003.097.688 bytes, abaixo do limite de 33.572.848.010 bytes.

## Estados expostos por resultado

- `unique`: uma única variante efetiva conhecida entre os artefatos analisados;
- `resolved`: regra interna ou perfil explícito selecionou a variante retornada;
- `shadowed`: o fonte existe no índice, mas outra variante seria carregada;
- `ambiguous`: existem bytecodes divergentes e nenhum perfil completo foi
  selecionado;
- `unknown`: a análise ainda não cobre a classe ou a release.

As citações incluem o estado (`classpath ambiguous`, por exemplo). O VR Ultra
encaminha o aviso ao sintetizador e usa confiança reduzida para `ambiguous`,
`shadowed` e `unknown`.

Uma busca real por `GwtCompatible` retornou variantes de `VRPdv`,
`VRAutorizador` e `VRAtacado` como `ambiguous`, com 23 candidatos efetivos e sem
escolher silenciosamente uma delas.

## Perfis por aplicação

Não existe uma única ordem correta para todos os 46 JARs. Cada aplicação pode
ser iniciada com dependências próprias. A política é separada por `profile_id` e
contém uma lista ordenada de JARs.

Uma política manual:

- exige release fresca;
- aceita apenas JARs presentes no manifesto;
- exige aprovação explícita;
- pode ser parcial ou marcada como completa;
- é invalidada automaticamente quando o hash agregado da release muda;
- não altera nem remove os JARs originais.

Exemplo, somente após confirmar o comando real do launcher:

```powershell
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject set-erp-classpath current vr-atacado `
  --jar VRAtacado.jar --jar lib/VRFramework.jar `
  --complete --approve
```

## Comandos de auditoria

```powershell
# Análise completa; execuções seguintes reutilizam o cache por hash
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject inspect-erp-classpath current

# Estado geral ou de um perfil explicitamente selecionado
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-classpath current
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject status-erp-classpath current --profile vr-atacado

# Busca ordenada pelo perfil, preservando variantes shadowed na auditoria
.\.venv\Scripts\python.exe -m vrsoft_extractor.mary.cli `
  --root VRProject search-erp-code GwtCompatible `
  --release current --profile vr-atacado
```

## Critérios de aceite

- seleção interna comprovada contra Java 17 real;
- análise integral dos 46 JARs sem erro;
- cache incremental por SHA-256 do artefato;
- nenhuma política real inferida pelo nome de pasta;
- configuração manual protegida por aprovação e frescor;
- divergência propagada até busca, citação, confiança e síntese;
- interface mostra `classpath parcial/desconhecido` na release selecionada;
- capacidade permanece dentro do teto configurado.

## Próxima etapa

Com a política formalizada, `VRAtacarejo.jar` e `VRMaster.jar` podem ser
processados sem esconder ambiguidades. Em paralelo, deve-se coletar o comando ou
trace real de inicialização de cada aplicação principal para promover os perfis
correspondentes de parciais para completos. Depois disso, o benchmark pareado de
chamados poderá distinguir ganho do índice de ganho da resolução de runtime.

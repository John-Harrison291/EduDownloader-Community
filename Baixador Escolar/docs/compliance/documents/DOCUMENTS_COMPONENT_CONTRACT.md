# Contrato técnico do Componente de Documentos

> **Registro histórico:** este contrato documenta o componente canônico usado
> na PoC e na aceitação técnica interna da 1.4.0. O modelo de pacote separado
> reempacotado pelo EduDownloader foi encerrado e não é contrato de
> distribuição vigente. A autoridade atual é
> `DOCUMENTS_DISTRIBUTION_MODEL.md`: o usuário obtém o LibreOffice Portable na
> fonte oficial e configura sua instalação local. O inventário, os hashes e os
> achados abaixo são preservados como evidência histórica, não como conteúdo a
> ser publicado pelo EduDownloader.

**Fase:** 1.4-B1 / 1.4-G1

**Decisão anterior:** `GO_LIBREOFFICE_SEPARATE_COMPONENT`

**Integração no produto:** implementada sem motor empacotado

**Redistribuição:** não autorizada por este documento

**Revisão jurídica:** `LEGAL_REVIEW_REQUIRED = YES`

Este documento define o contrato técnico e o fechamento de evidência do
componente documental offline do EduDownloader. Ele registra identidade,
layout, validação, provenance, segurança e limites operacionais. Não é parecer
jurídico, não cria um pacote distribuível e não autoriza publicação,
redistribuição ou download automático.

## 1. Identidade independente

- Nome: **EduDownloader Documents Component**.
- `component_id`: `edudownloader.documents.libreoffice`.
- `component_version`: `documents-component-26.2.4.2`.
- Motor: LibreOffice Portable MultilingualStandard 26.2.4.2, Windows x86-64.
- A versão do componente é independente da versão do EduDownloader. Atualizar
  o aplicativo não implica atualizar o motor, e o inverso também é verdadeiro.

## 2. Layout offline proposto

```text
EduDownloader-Portable/
  EduDownloader.exe
  components/
    documents/
      component-manifest.json
      DOCUMENTS_COMPONENT_PROVENANCE.json
      DOCUMENTS_COMPONENT_INVENTORY.json
      licenses/
      engine/
        LibreOfficePortable/
          LibreOfficePortable.exe
          App/
          Data/
          Other/
```

O layout preferencial coloca o componente ao lado do aplicativo. Todos os
paths operacionais do manifesto usam `/`, são relativos à raiz do componente e
proíbem drive letter, path UNC, path absoluto, `..` e barra invertida. Isso
preserva paths com espaços/Unicode, pendrive, mudança de letra de unidade e
outro perfil Windows.

Prioridade futura de descoberta:

1. `components/documents` ao lado do executável;
2. uma raiz explicitamente configurada pelo usuário ou administrador.

Não haverá varredura do disco nem fallback silencioso para LibreOffice global,
registro do Windows ou `PATH`.

## 3. Manifesto canônico

O schema obrigatório é
`DOCUMENTS_COMPONENT_MANIFEST_SCHEMA.json` (JSON Schema 2020-12). O futuro
`component-manifest.json` deverá conter:

- identidade, versão, plataforma e arquitetura;
- autoridade binária e de source;
- hash e tamanho do instalador;
- estado de source correspondence;
- contagem, bytes, hash lógico e hash físico do inventário;
- paths relativos de `soffice.com`, `soffice.bin`, launcher e Python embutido;
- licenças/notices esperados e respectivos hashes;
- compatibilidade e política de runtime.

Arquivos de autoridade são UTF-8 sem BOM, LF, JSON com chaves ordenadas,
indentação de dois espaços e newline final. O hash lógico do inventário é o
SHA-256 do array `entries` em JSON compacto UTF-8 com chaves ordenadas, depois
de ordenar entries por path POSIX em `casefold`, com o path exato como desempate.

O schema não torna um pacote distribuível. Uma instância final do manifesto só
deverá ser criada durante uma futura etapa de empacotamento controlado.

## 4. Inventário canônico

`DOCUMENTS_COMPONENT_INVENTORY.json` registra a árvore limpa aprovada pela PoC:

- 15.354 arquivos;
- 928.815.136 bytes;
- SHA-256 lógico do inventário:
  `8D212879137C57DDF77EFC6785AB4019EDB6C3D78E5974C8A4F845F3F6C69A4F`;
- SHA-256 do arquivo de inventário:
  `FE3CF5E39FCA3EA4B25ECFF5E602075320CE00F25C14CB91D34F2C08FD1340A2`.

O escopo exclui profiles, temporários, outputs, evidências da PoC e bytecode
`.pyc`. Encontrar `.pyc` na árvore canônica é falha, não diferença tolerada.

A revalidação G1 confirmou que todos os 15.354 arquivos canônicos continuam
presentes e byte-idênticos: zero missing, zero modificados e zero `.pyc`. A
cópia ignorada da PoC contém oito dumps de crash posteriores ao capture, com
1.098.448 bytes. Eles não integram a autoridade do pacote, não podem ser
empacotados e fazem o `FULL_VERIFY` daquela cópia falhar por arquivos extras.
O pacote futuro deverá ser materializado de uma extração limpa que corresponda
exatamente ao inventário rastreado; nenhum dump foi removido nesta fase.

## 5. Mutabilidade e runtime

`ENGINE_TREE = READ_ONLY_EXPECTED`. A árvore distribuída do motor deve permanecer
imutável. Somente estas raízes externas podem ser graváveis por operação:

- profile isolado;
- temporários;
- output escolhido.

O wrapper futuro deve definir `PYTHONDONTWRITEBYTECODE=1` e `PYTHONHOME` para
`App/libreoffice/program/python-core-3.12.13`. Estado crítico, cache e profile
nunca pertencem à árvore do motor. Sucesso, erro e cancelamento terminam com a
remoção integral do profile temporário.

## 6. Executáveis autorizados

| Papel | Path relativo | SHA-256 |
| --- | --- | --- |
| Entrypoint operacional futuro | `App/libreoffice/program/soffice.com` | `5D8954C7FBE457B5AAB7FA601059E57D9DD3ECCB25694C276BD12D1FAEE25335` |
| Processo do motor | `App/libreoffice/program/soffice.bin` | `651F5BC9C0A771B65F1E5124079BAADE982C2B5578FA05D93FE48A665F4593E7` |
| Launcher portátil presente | `LibreOfficePortable.exe` | `8308DE6D16E74E15318FEB04E80BF1612E8FF318706A16983CFC24114B808C6C` |
| Launcher Python embutido | `App/libreoffice/program/python.exe` | `36D659510D39C047D716A0EE9D9342A76C539A49AEAB52F55FC68BB776122F0A` |
| DLL Python embutida | `App/libreoffice/program/python3.dll` | `173D9766B38822D5EDEB43F5BEBEFA2E570A567BBA744D73DD9763D395BD9BF4` |
| Runtime Python embutido | `App/libreoffice/program/python-core-3.12.13/bin/python.exe` | `574FF275980D94D6A4EB14081A562F1577FF0C413BD207E05AC6360421536F00` |

O wrapper deverá iniciar diretamente o entrypoint validado dentro do
componente. O launcher portátil integra a árvore canônica, mas não substitui o
controle explícito necessário para a árvore de processos.

## 7. Detecção e validação futuras

Estados conceituais:

- `NOT_CONFIGURED`: nenhuma raiz válida foi informada ou encontrada;
- `AVAILABLE`: schema, identidade, compatibilidade e checks exigidos passaram;
- `INVALID`: manifesto ausente, malformado, inseguro ou fora da root permitida;
- `VERSION_MISMATCH`: versão/plataforma/arquitetura incompatível;
- `CORRUPTED`: arquivo ausente ou hash/inventário divergente.

### FAST_CHECK

Usado na primeira operação que precisa do motor, após configurar/trocar a raiz
e em diagnóstico leve. Valida schema, paths confinados, id/versão/arquitetura,
hashes dos executáveis críticos e presença/hash de licenças/notices. Não deve
ler 929 MB a cada startup.

### FULL_VERIFY

Usado na instalação, troca, atualização, diagnóstico explícito, após falha do
fast check ou suspeita de corrupção. Recalcula todos os 15.354 paths, tamanhos e
hashes. Arquivo ausente, extra, alterado ou `.pyc` inesperado falha fechado.

## 8. Modelo de entrega offline

| Modelo | Vantagem | Limite |
| --- | --- | --- |
| ZIP oficial já canônico | melhor UX, layout e hashes determinísticos | exige packaging e compliance completos do projeto |
| Extrator oficial separado | origem binária forte | extração e normalização são complexas para o destinatário |
| Pasta pronta | configuração simples | transporte e integridade são mais frágeis sem package authority |

Preferência futura: um **pacote oficial separado do Componente de Documentos**,
offline, já canônico e reconhecido automaticamente. Não haverá download
dinâmico nesta fase. O componente integral acrescentaria aproximadamente 929 MB
à baseline do aplicativo; mantê-lo separado reduz custo para quem não usa
conversão de documentos e simplifica atualização independente.

## 9. Provenance e source correspondence

Autoridade binária observada:

- PortableApps.com, LibreOffice Portable 26.2.4 MultilingualStandard;
- runtime LibreOffice 26.2.4.2;
- instalador de 223.657.592 bytes;
- SHA-256
  `4BDE93374AEF4409243505B20D16561A4628AC7591457DD01FC6E1CCF571BA65`;
- assinatura Authenticode válida de RARE IDEAS, LLC.

Authority upstream de source: The Document Foundation, diretório oficial
`libreoffice/src/26.2.4/`. A versão 26.2.4.2 possui archives exatos de core,
dictionaries, help e translations, cada qual com hash SHA-256 oficial,
assinatura upstream adjacente e tag exata `libreoffice-26.2.4.2`:

| Escopo | Archive | Bytes | SHA-256 | Commit da tag |
| --- | --- | ---: | --- | --- |
| Core | `libreoffice-26.2.4.2.tar.xz` | 292.105.604 | `B9F9655442432998AF2CD1034AEEE802641ABA4D0BE6B6CE4FC10BEC78CE4B9B` | `995ae2723a5200b4bab3e5fe39c18f24b544aaf3` |
| Dictionaries | `libreoffice-dictionaries-26.2.4.2.tar.xz` | 62.188.908 | `7E64776D79240943CB2C20D467723A488638178337B6810DE4526D1CBABE40FB` | `36bdd8e1575813c6bbbfecb235623de8f8aeac6a` |
| Help | `libreoffice-help-26.2.4.2.tar.xz` | 58.404.004 | `491DBC6333A24A1856FE1690E4DB981F83D451C6C850D84F7D0F2475317825F5` | `99be0bfdcc9115986e5677b1a27a9357afc5cfee` |
| Translations | `libreoffice-translations-26.2.4.2.tar.xz` | 234.920.384 | `B9FD1C2F21333F5B444C91ABFEC201BC7CF23854ACEF345133DF78CA6CE094E0` | `4d2386b239bbe244410c2059c49e2527f799b84a` |

Os archives grandes não foram baixados nem adicionados ao Git. A autoridade
técnica é formada pelo diretório oficial, hashes, assinaturas disponíveis e
commits exatos. Isso permite obter/verificar o source correspondente sem
confundir referência técnica com a decisão jurídica sobre como entregá-lo.

O `download.lst` da tag exata possui blob Git
`e217b679efbcbbb0d70aa307f97ce491401b33d1`, 33.313 bytes e SHA-256
`DDEAE7C86FDD87BC1A1AAF2256A4766DB735C53C69754244A3E7645E586AEDDD`.
Ele fixa nomes/hashes dos tarballs third-party, inclusive Python 3.12.13 e
OpenSymbol, e fornece um crosswalk proporcional sem reconstruir cada DLL.

Consequentemente:

- `TECHNICAL_REDISTRIBUTION_EVIDENCE = COMPLETE`;
- `LEGAL_REVIEW_REQUIRED = YES`;
- `DISTRIBUTION_ALLOWED = NOT_DECLARED`.

GO técnico para implementar o wrapper em fase posterior não equivale a GO para
redistribuição.

## 10. Licenças, notices e third-party

O componente contém `App/libreoffice/LICENSE.html`, `license.txt`, `NOTICE`,
fontes do launcher em `Other/Source` e textos/declarations específicos dos
dicionários. A evidência oficial descreve LibreOffice sob MPL 2.0, herança do
Apache OpenOffice e numerosos componentes sob outras licenças. Portanto, a
classificação não é simplificada para “LibreOffice = MPL”.

Classificação G1:

- `COVERED_BY_UPSTREAM_NOTICE`: third-party agregado pelos textos oficiais e
  pelo `download.lst` da tag exata;
- `EXPLICIT_SOURCE_REQUIRED`: core, dictionaries, help, translations,
  PortableApps launcher e OpenSymbol possuem autoridade exata registrada;
- `LEGAL_REVIEW_ONLY`: suficiência jurídica do modelo de entrega, apresentação
  final dos notices de alguns dicionários e do OpenSymbol.

O inventário resumido de dicionários contém 601 arquivos e 208.316.350 bytes:
`ar`, `de`, `en`, `es`, `fr`, `it`, `ko`, `pt-BR`, `pt-PT` e `ru`. Recursos de
locale contêm 449 arquivos e 43.129.170 bytes para `ar`, `de`, `en_GB`,
`en_ZA`, `es`, `fr`, `it`, `ja`, `ko`, `pt`, `pt_BR`, `ru`, `zh_CN` e `zh_TW`,
além de `common`. Nenhum idioma/dicionário é removido em B1; qualquer recorte
futuro exige nova análise funcional e de licença.

O OpenSymbol (`opens___.ttf`, versão 102.12) aparece em duas localizações com o
mesmo SHA-256
`F543E6E2D7275557A839A164941C0A86E5F2C3F2A0042BFC434C88C6DDE9E140`.
Esse hash coincide exatamente com `OPENSYMBOL_SHA256SUM` no `download.lst`; a
fonte canônica é `extras/source/truetype/symbol/OpenSymbol.sfd` na tag exata.
Não há outras fontes embarcadas na árvore, e fontes do Windows estão fora do
escopo. A apresentação jurídica do notice do OpenSymbol continua separada.

O launcher principal é PortableApps.com Launcher 2.2.9.0. O pacote contém GPL,
README e source/configuração NSIS específicos em `Other/Source`; a autoridade
complementar é o pacote oficial de source 2.2.9, com SHA-256
`7BC93E47B885D5E953FA2082A2E65169AE98128026AC4D747F774A23BD01345B`,
e o repositório upstream. Não há tag Git 2.2.9 publicada; o pacote oficial é a
autoridade exata de versão, fato registrado sem ocultar a limitação do repo.

## 11. Segurança obrigatória do wrapper futuro

Requisitos demonstrados pela PoC e não negociáveis:

- profile novo e isolado por operação;
- `DisableMacrosExecution=true`;
- `DisableActiveContent=true`;
- macro security level 3;
- `BlockUntrustedRefererLinks=true`;
- nenhuma trusted location, certificado, extensão, macro ou template herdado;
- `PYTHONHOME` explícito e `PYTHONDONTWRITEBYTECODE=1`;
- engine read-only; profile, temp e output externos;
- recursos externos não confiáveis bloqueados.

Cada operação deve iniciar `soffice.com` suspenso, associá-lo a um Windows Job
Object exclusivo e somente então resumir a thread principal. Cancelamento usa
`TerminateJobObject`/kill-on-job-close e alcança apenas descendentes daquela
operação. É proibido matar `soffice` por nome ou interferir no LibreOffice do
usuário.

## 12. Validação DOCX preliminar

Antes de chamar o motor, o wrapper futuro deverá rejeitar entradas que não
satisfaçam todos os limites:

- arquivo até 100 MiB;
- cada entry até 100 MiB;
- no máximo 10.000 entries;
- total descompactado até 500 MiB;
- ratio de compressão até 100:1;
- ZIP estruturalmente válido e não criptografado;
- `[Content_Types].xml` e `word/document.xml` obrigatórios;
- nomes internos normalizados, sem absoluto, drive, UNC, `..` ou traversal.

Esses valores são **provisórios** até testes específicos da fase 1.4-B2. A
extensão `.docx` sozinha nunca será autoridade de tipo.

## 13. UX e degradação controlada

Mensagem principal futura: **“Componente de documentos não configurado.”**

Ação: **“Configurar componente”**.

Status válido: **“Disponível”**.

Versão LibreOffice e detalhes de hashes ficam em Informações/diagnóstico. A
ausência do componente não pode impedir startup, poluir toda inicialização ou
quebrar Arquivos, PDF, Downloads ou Mídia. Somente a operação dependente do
motor informa indisponibilidade.

## 14. Atualização, troca e remoção

O manifesto suporta versionamento independente para integração futura ao
sistema controlado de motores planejado para 1.6. Nada é implementado em B1.
Troca ou remoção consiste em substituir/remover a pasta do componente somente
quando nenhuma operação está ativa. Profiles e estado crítico permanecem fora
da pasta, tornando a remoção simples e evitando migração de estado oculto.

## 15. Critérios para a próxima fase

O produto já implementa descoberta, validação e wrapper sem empacotar o motor.
Antes de criar um RC que transporte o componente separado, deverão ser
validados ao menos:

- parser/schema do manifesto e confinamento real de paths;
- fast check e full verify, inclusive adulteração, missing, extra e `.pyc`;
- versão/arquitetura incorretas e componente fora da root permitida;
- limites DOCX com fixtures válidas, corrompidas e adversariais controladas;
- wrapper com Job Object e limpeza em sucesso/erro/cancelamento;
- segurança de macros/active content e bloqueio externo;
- materialização a partir de extração limpa, sem os dumps da PoC;
- cópia acessível dos notices por índice no pacote;
- modelo de source delivery escolhido após revisão jurídica;
- inventário final e hash do ZIP congelados.

## 16. Estado ao fechar G1

- página Documentos e integrações previstas: implementadas sem motor embutido;
- conversões: dependem do componente separado validado;
- LibreOffice no build principal/PyInstaller: ausente;
- APP_VERSION: 1.3.0;
- package/release/download automático: não criados;
- decisão técnica vigente: `GO_LIBREOFFICE_SEPARATE_COMPONENT`;
- `TECHNICAL_REDISTRIBUTION_EVIDENCE = COMPLETE`;
- `LEGAL_REVIEW_REQUIRED = YES`;
- `DISTRIBUTION_ALLOWED = NOT_DECLARED`.

## 17. Matriz de compliance

| Componente | Binário | Licença | Source authority | Hash/versão | Notice futuro | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| LibreOffice core | sim | sim | archive + tag TDF | 26.2.4.2 | LICENSE/NOTICE agregados | `COMPLETE` |
| Dictionaries | sim | sim/declarations | archive + tag TDF | 26.2.4.2 | textos específicos + índice | `TECHNICALLY_COMPLETE` |
| Help | sim | sim | archive + tag TDF | 26.2.4.2 | agregado | `COMPLETE` |
| Translations/locales | sim | sim | archive + tag TDF | 26.2.4.2 | agregado | `COMPLETE` |
| Portable launcher | sim | sim | pacote source 2.2.9 + repo | 2.2.9.0 | GPL/README/NSIS | `COMPLETE` |
| OpenSymbol | sim | agregado | SFD + `download.lst` exatos | 102.12/hash fixo | agregado + referência | `TECHNICALLY_COMPLETE` |
| Third-party aggregate | sim | sim | `download.lst` exato | blob/hash fixos | LICENSE/NOTICE | `TECHNICALLY_COMPLETE` |
| Fontes | sim | agregado | somente OpenSymbol | duas cópias idênticas | agregado + referência | `TECHNICALLY_COMPLETE` |
| Python embutido | sim | sim | `Python-3.12.13.tar.xz` fixado | 3.12.13/hash fixo | licença Python agregada | `COMPLETE` |
| Extensões | sim | sim/declarations | core + dictionaries | inventário canônico | textos locais + agregado | `TECHNICALLY_COMPLETE` |

## 18. Notice delivery e source model

O pacote futuro deverá expor, sem exigir busca manual em 15 mil arquivos:

- índice em `licenses/README.md` ou equivalente;
- LICENSE/NOTICE agregados do LibreOffice;
- GPL/README/source NSIS do launcher;
- LICENSE/COPYING/README de dicionários;
- manifesto, provenance e inventário canônico;
- referências exatas de source, versão, commit e hash.

Três modelos técnicos permanecem disponíveis, sem escolha jurídica nesta fase:

1. incluir os quatro archives correspondentes e o source do launcher;
2. entregar referências oficiais imutáveis e hashes, caso juridicamente
   suficientes;
3. congelar pacote separado de source correspondence mapeado ao binário.

## 19. Modelo do pacote futuro

Nome conceitual: `EduDownloader-Documents-Component-26.2.4.2.zip`.

Conteúdo mínimo: `component-manifest.json`, `provenance/`, `inventory/`,
`licenses/` e `engine/LibreOfficePortable/`. Antes de qualquer distribuição,
o pacote deverá congelar contagem, bytes, hash lógico do inventário e SHA-256
do ZIP. O pacote não foi criado em G1 e download dinâmico continua ausente.

## 20. Lacunas restantes

| Item | Classificação | Consequência |
| --- | --- | --- |
| Escolha/suficiência do modelo de source delivery | `LEGAL_REVIEW_ONLY` | bloqueia autorização oficial de distribuição |
| Apresentação final de notices de alguns dicionários | `LEGAL_REVIEW_ONLY` | confirmar texto/posição antes do pacote final |
| Apresentação final do notice do OpenSymbol | `LEGAL_REVIEW_ONLY` | confirmar texto/posição antes do pacote final |
| Oito dumps na cópia ignorada da PoC | `NON_BLOCKING_DOCUMENTATION` | nunca usar essa cópia como raiz do pacote; extração limpa obrigatória |

Não há lacuna `BLOCKING_TECHNICAL` conhecida de provenance, source, licença ou
notice. Isso permite seguir para hardening/RC interno, mas não autoriza a
publicação do Componente de Documentos.

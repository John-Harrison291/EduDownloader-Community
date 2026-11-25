# D11H — Deno 2.9.5: política canônica SPDX para revisão P3

## Resultado técnico

Registro de 2026-09-10. A política
`ADOPT_CANONICAL_REFERENCE_POLICY_FOR_P3_REVIEW` passa a distinguir
explicitamente source correspondence, identidade da licença, disponibilidade
do texto upstream, referência canônica SPDX, attribution, notice e revisão
jurídica.

O snapshot oficial é a SPDX License List 3.28.0, tag anotada `v3.28.0`, objeto
`779ef2e5dff6d4af389c53de5e97116ab0bb52e8` e commit de conteúdo
`c4a7237ec8f4654e867546f9f409749300f1bf4c`. Foram preservados somente os textos
`MIT`, `Apache-2.0`, `CC0-1.0` e `Zlib`, no namespace separado
`docs/compliance/licenses/spdx-reference/`, com provenance, tamanho e SHA-256.
Esses textos são `SPDX_CANONICAL_REFERENCE_TEXT`, nunca
`UPSTREAM_LICENSE_TEXT`.

Para os 15 componentes remanescentes:

- `LICENSE_IDENTITY = RESOLVED_FROM_EXACT_UPSTREAM_METADATA`;
- `UPSTREAM_LICENSE_TEXT = ABSENT` em 13 casos;
- `UPSTREAM_LICENSE_TEXT = PARTIAL` em `zune-core` e `zune-jpeg`;
- `CANONICAL_REFERENCE_COVERAGE = COMPLETE_FOR_D11H_SCOPE`;
- `ATTRIBUTION_METADATA = PARTIAL`, sem titular ou ano inferido;
- `NOTICE_IDENTITY = RESOLVED`;
- `NOTICE_DELIVERY = PENDING_FIX`;
- `LEGAL_REVIEW = P3_REQUIRED`.

As expressões `MIT OR Apache-2.0` e `MIT OR Apache-2.0 OR Zlib` permanecem
literais e exigem referência para todas as alternativas. A evidência Zlib e a
informação Apache parciais dos dois componentes Zune continuam preservadas como
upstream; SPDX é complementar.

Como `SOURCE_PENDING`, `SOURCE_BLOCKED` e `OPEN_SOURCE_UNKNOWN` são zero,
`SOURCE_CORRESPONDENCE = TECHNICALLY_COMPLETE`. A contagem legada permanece 916
`TEXT_RESOLVED` e 15 `TEXT_PENDING`, pois mede conjuntos integrais upstream e
não deve incorporar referências canônicas. Nenhum staging ou bundle COMPLETE
foi montado.

Manifestos canônicos após a D11H:

- provenance Deno: SHA-256
  `9819DB881B0D819B0F00FF6A00D2160BDFE37393651357971B60D26A15D06382`;
- inventário: SHA-256
  `155D6C10D7021108ED27BCEE928C436742E9EC91F9910382C3FE76D743F210CF`;
- notice consolidado futuro: SHA-256
  `5DCE768CB069D3CF0A73F4F2DC3308FE6B0786FD2A4DFF602ACA6E36E5532347`.

O candidato congelado histórico permanece com 1.068 arquivos, 382.736.507
bytes e inventário SHA-256
`26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857`.
Não recebeu os textos SPDX. P2, P3, versão, edição e gates permanecem abertos ou
fechados exatamente como antes.

## Histórico D11D — resolução final direcionada de textos de licença

## Resultado e fronteira

Registro técnico de 2026-09-09 para o `deno.exe` do candidato congelado
`INTERNAL_ANALYSIS_CANDIDATE`, produzido do source commit do EduDownloader
`621a72b8c3329dc68abc0c581ec152d6c3bd9e08`. O binário é a release oficial
Deno 2.9.5 para `x86_64-pc-windows-msvc`, tem 97.408.288 bytes e SHA-256
`98F8C2A2D470E4CCB04C935C86FF8050817D877762AEC5EAEEB9E409CCB3B9FD`.

**V8 NATIVE SOURCE CLOSURE: RESOLVED.**

**DENO OPEN-SOURCE SOURCE CORRESPONDENCE: PARTIAL. NÃO PUBLICAR.**

A D11D continua a reconciliação textual da D11C para o inventário material já
fechado pelas D10/D11A. As closures Cargo, SWC e V8/GN e os sources
Deno/Rust/V8 não foram reabertos nem baixados novamente.

Após o trace:

- `SOURCE_PENDING = 0`;
- `SOURCE_BLOCKED = 0`;
- `OPEN_SOURCE_UNKNOWN = 0`.

Dos 88 componentes inicialmente `TEXT_PENDING`, 73 foram resolvidos e 15
continuam pendentes. A única metadata sem expressão, `libuv-sys-lite@1.48.3`,
foi resolvida como `RESOLVED_FROM_LICENSE_FILE` pelo `license-file` e pelo texto
`LICENSE` do `.crate` exato, sem inventar expressão SPDX. O inventário agora
inclui também 62 identidades materiais nativas/Rust já provadas na D11A: são
931 componentes ao todo, 916 `TEXT_RESOLVED`, 15 `TEXT_PENDING`, zero
`LICENSE_EXPRESSION_PENDING` e zero `UNKNOWN`.

Como ainda existem 15 textos sem conjunto autoritativo completo, a
correspondência Deno permanece `PARTIAL`; nenhum staging nem bundle `COMPLETE`
foi criado. A entrega de notices ao candidato congelado permanece
`PENDING_FIX`, separada da identidade aqui preservada, e a revisão jurídica
continua pendente.

O candidato congelado permaneceu intacto. Nenhum PyInstaller, compiler, Ninja,
Cargo, Rust ou build V8 foi executado. Nenhum source proprietário, chave,
licença operacional ou material privado participa da evidência.

Autoridade rastreada:

- `DENO_RUNTIME_SOURCE_PROVENANCE.json`: identidade, closure GN, arestas,
  classificações, source coverage e notices nativos;
- `DENO_THIRD_PARTY_INVENTORY.json`: inventário gerado D11D de 931 componentes,
  mappings, hashes, status e tentativas de autoridade;
- `DENO_THIRD_PARTY_NOTICES.txt`: consolidação determinística para candidato
  futuro, não entregue ao candidato histórico;
- `deno_runtime_source_bundle.py`: geração e verificação offline fail-closed;
- `tests/test_deno_runtime_source_bundle.py`: regressões de target, args,
  identidade, classificação, coverage e adulteração.

O manifesto de provenance é JSON canônico e tem SHA-256
`6F8FBE8F8D0D7EF84C9E9AB53CB8726EB5072F965D16A42F8983C0C4D700F0D5`.
O inventário gerado tem SHA-256
`EBBD612BCF648898F7AC948EB033438C2C074787A5C1D34EE0FA5EE21D5C5932`.
O notice consolidado tem 2.598.468 bytes e SHA-256
`F586887C3DEB172AF2FB3BB435EFD12C50710A32E96127D54E9074B41F56761A`.

## Resolução final direcionada D11D

Os 16 itens pendentes da D11C foram agrupados por repositório, workspace e
revisão antes da inspeção individual. Foram reutilizados os 89 arquivos de
evidência existentes, todos os `.crate` exatos e as árvores/source archives já
preservadas. A inspeção oficial das revisões exatas confirmou ausência de paths
adicionais `LICENSE`, `COPYING`, `NOTICE`, `COPYRIGHT`, `AUTHORS`, SPDX/REUSE ou
equivalentes capazes de fechar os componentes ainda pendentes.

`dlopen2@0.6.1` foi resolvido no commit oficial exato
`8580a7c1eafad6507b6c5fd37cb2e404af7e214d`. O manifesto
`dlopen2/Cargo.toml` declara nome, versão 0.6.1 e MIT e é igual ao
`Cargo.toml.orig` do `.crate` após normalização exclusiva de fim de linha. O
`Cargo.toml` raiz inclui `dlopen2` no workspace; o `LICENSE` MIT integral no
mesmo commit possui SHA-256
`39FA265207450E77C62E90C5594A06C085B655D8374C7CED4BF7894B6BD95DD2`
e é byte-identical ao texto já conhecido no commit irmão de
`dlopen2_derive@0.4.0`. A evidência mantém mapping separado e notice deduplicado
por hash.

Foram baixados somente três arquivos pequenos desse commit: `LICENSE`,
`Cargo.toml` raiz e `dlopen2/Cargo.toml`. O índice passa a 60 textos
autoritativos e 44 mappings, com SHA-256 canônico
`44794C785B42C2CE8C8D32640673A28E60A2D2802752D5ECB5A494CABEFF95FD`.
Nenhum crate, source archive, source tree, Deno, V8, Rust, GN/Ninja ou evidência
SWC foi baixado novamente.

Os demais 15 continuam `TEXT_PENDING`:

- `aead-gcm-stream@0.4.0`;
- `convert_case@0.4.0`;
- `deno_native_certs@0.3.0`;
- `deno_tunnel@0.8.1`;
- `derive-io@0.4.1` e `derive-io-macros@0.4.1`;
- `fqdn@0.5.2`;
- `hexf-parse@0.2.1`;
- `rustls-tokio-stream@0.8.0`;
- `sacabase@2.0.0`;
- `sptr@0.3.2`;
- `sys_traits@0.1.28` e `sys_traits_macros@0.1.0`;
- `zune-core@0.4.12` e `zune-jpeg@0.4.13`.

`derive-io` e `derive-io-macros` compartilham commit e herança de workspace,
mas a raiz não contém os textos MIT/Apache. `sys_traits` e
`sys_traits_macros` pertencem ao mesmo repositório em commits distintos, ambos
sem texto. Os repositórios oficiais exatos de `deno_native_certs`,
`deno_tunnel` e `rustls-tokio-stream` contêm declaração MIT e cabeçalhos curtos,
mas nenhum arquivo integral; isso não autoriza cobertura pelo parent Deno.
`zune-core` e `zune-jpeg` continuam com Zlib integral e aviso Apache curto, sem
os textos integrais MIT/Apache. Os demais componentes apresentam apenas
metadata SPDX ou badges/referências que não fornecem texto autoritativo no
commit exato. Nenhum fallback genérico ou revisão aproximada foi usado.

A inspeção das estruturas exatas não encontrou `NOTICE`, `COPYRIGHT`, `AUTHORS`
ou exceção separada exigida para esses 16 componentes. Por isso eles são
classificados como `NOTICE_NOT_REQUIRED_BY_UPSTREAM_STRUCTURE`, em vez de
`NOTICE_IDENTITY_PENDING`. O inventário global mantém 29 notices resolvidos,
27 componentes `NOTICE_NOT_REQUIRED_BY_UPSTREAM_STRUCTURE` (16 deste lote e 11
anteriores) e zero `NOTICE_PENDING`. Isso não altera o estado separado de
entrega do notice consolidado ao produto, que continua `PENDING_FIX`.

## Resolução direcionada D11C

Os 44 itens pendentes da D11B foram mapeados individualmente. Vinte e três
crates com prefixo `swc_` e quatro crates auxiliares do mesmo repositório foram
tratados como uma família comprovada: a tag oficial exata
`swc_core@v48.0.4`, commit
`b0ab736714f7574cd8e5f12eee224d666f01fccc`, contém os 27 manifests com as
versões exatas e `license.workspace = true`; o `Cargo.toml` raiz declara
Apache-2.0 e o `LICENSE` integral tem SHA-256
`D96EBA1F1881334D50FFC144276DFA98E147A415E7C591ECDFCB81680361DC91`.
Cada componente conserva também seu checksum de `.crate`, commit VCS de
publicação e path no workspace. Um único texto raiz foi deduplicado, sem 27
downloads idênticos.

`dlopen2_derive@0.4.0` foi resolvido pelo commit VCS exato
`122b5b7d9f15718de9525b5968ea8888ddc3a89d` do workspace oficial
`OpenByteDev/dlopen2`: o manifesto do membro prova nome, versão e MIT, o
manifesto raiz prova a participação no workspace e o `LICENSE` integral tem
SHA-256
`39FA265207450E77C62E90C5594A06C085B655D8374C7CED4BF7894B6BD95DD2`.

Nos dois componentes Zune, `LICENSE-ZLIB` foi encontrado e preservado nos
commits exatos, com SHA-256
`7FA429541E55B1509909E058F2D21A37467E4958EC713B357F6E0CF9DC4EE352`.
Isso não fecha `MIT OR Apache-2.0 OR Zlib`: o `LICENSE.md` upstream é somente
um aviso Apache curto e não contém os textos integrais MIT e Apache. Ambos
continuam `TEXT_PENDING`, sem fallback genérico.

Foram preservados 34 arquivos pequenos novos: quatro textos de licença e 30
manifests de prova. O índice passa a 59 textos autoritativos e 44 mappings, com
SHA-256 canônico
`ABDA7DF00E9FDD7868E48FF61FCB5101F7F5C69A7D4E809E51C8D7DC5BC2283C`.
Não foram baixados crates, source archives ou árvores grandes.

Permanecem pendentes exatamente:

- `aead-gcm-stream@0.4.0`;
- `convert_case@0.4.0`;
- `deno_native_certs@0.3.0`;
- `deno_tunnel@0.8.1`;
- `derive-io@0.4.1` e `derive-io-macros@0.4.1`;
- `dlopen2@0.6.1`;
- `fqdn@0.5.2`;
- `hexf-parse@0.2.1`;
- `rustls-tokio-stream@0.8.0`;
- `sacabase@2.0.0`;
- `sptr@0.3.2`;
- `sys_traits@0.1.28` e `sys_traits_macros@0.1.0`;
- `zune-core@0.4.12` e `zune-jpeg@0.4.13`.

Tags exatas encontradas para `convert_case`, `deno_native_certs`,
`hexf-parse`, `sptr` e `sys_traits` apontam aos mesmos commits já examinados e
não contêm texto de licença. Os pares `derive-io`/`derive-io-macros` compartilham
commit e workspace, mas sem texto raiz; `sys_traits` e `sys_traits_macros`
pertencem ao mesmo repositório em revisões distintas. `dlopen2@0.6.1` segue sem
revisão VCS ou tag exata comprovada. Nenhum desses fatos foi promovido a texto.

## Reconciliação D11B

A baseline histórica dos 88 itens foi preservada. A classificação inicial é:

| Causa inicial | Componentes |
|---|---:|
| `LICENSE_FILE_NOT_PACKAGED` | 61 |
| `MULTIPLE_LICENSE_EXPRESSION` | 12 |
| `WORKSPACE_INHERITED` | 8 |
| `LICENSE_METADATA_ONLY` | 4 |
| `OTHER` | 2 |
| `UPSTREAM_LICENSE_REFERENCE` | 1 |

Foram resolvidos 31 componentes por textos pequenos do repositório upstream no
commit VCS exato, 11 por um `.crate` irmão do mesmo commit e mesma expressão, e
dois pelos arquivos `LICENCE` britânicos já presentes nos próprios `.crate`.
O índice local ignorado pelo Git registra 55 arquivos textuais oficiais, origem,
commit, tamanho e hash; seu SHA-256 canônico é
`D1ABABAF890829ABFEFDD3750E0A013D904E70409F8B85C8C7FF3E44F50A8AC8`.
Não houve fallback para texto SPDX canônico, pois a política atual não o
autoriza.

Ao final da D11B, os 44 pendentes estavam enumerados no inventário, cada um com versão, source,
expressão, causa e tentativas. Entre as evidências restantes necessárias estão
um texto oficial no exato commit/tag quando o repositório não o contém, o
restabelecimento de commits SWC que hoje não são resolvidos pelo upstream e o
texto Zlib necessário para completar as expressões de `zune-core` e
`zune-jpeg`. `dlopen2@0.6.1` não possui revisão VCS exata comprovada. Nenhuma
revisão aproximada foi usada como substituta.

## Evidência D10 reutilizada e aquisição D11A

A D11A reutiliza, sem redownload:

| Parent preservado | Bytes | SHA-256 | Identidade |
|---|---:|---|---|
| Deno 2.9.5 | 32.639.976 | `9890BA7947C8DB2F31A91A374471FAF86D19C1682F623C170AEB2F86F58A2112` | tag `v2.9.5`; commit `17fadf33a8df3af9488b9f42efd1f2290d6dc7a3`; tree `e6af10b0db821bc8b0c110d66726270d2a50995a` |
| crate `v8` 150.4.0 | 36.296.166 | `42A978FF11F15B24E5C05A7123CF2B68F41E763546699781A924EF4E2CF43A49` | rusty_v8 commit `5c15a6995c9bb4bacd3e341b59fff32c909c80bf` |
| Rust source 1.95.0 | 3.827.368 | `67B09138C8DB96AFC4BBFC69EA771AC9A091FD777698ACB43F6DFD9FB7DEA363` | commit `59807616e1fa2540724bfbac14d7976d7e4a3860`; tree `e09ec02e7b522ab6b45c97b9742429e84940892e` |
| denoland/V8 | 32.860.562 | `208FC32BB41A5758BDB0E130A0019C908E68599FF5D9A40EF029A8E793B9039E` | V8 `15.0.245.2-rusty`; revision `ac1e23989121713ca642f6650b34deff7b686896`; tree `ff06e1a909291763a6f8526b44079551f037246a` |

O trace provou um único parent source adicional necessário, sem abrir Chromium,
`depot_tools` ou toda a árvore DEPS:

| Parent novo | Bytes | Arquivos | SHA-256 | Identidade |
|---|---:|---:|---|---|
| `chromium/src/third_party/rust` | 33.689.546 | 11.275 | `E10326E9AFF0AE922879071E71BA39C503390472EC643221D0349A9D00E2CE19` | commit `26e8ff47f18a8d28d6187a04b6a16cb7332356f8`; tree `b11eaf710e48d9c3d757090338131ac8d006d65d` |

Todos os 793 paths GN requeridos desse parent existem no archive. Os 45 crates
vendorizados alcançados possuem expressão/arquivo de licença e hash registrados
individualmente no manifesto.

## Autoridade do build e argumentos GN

O workflow oficial rusty_v8 no commit exato tem Git blob
`8fd61799619ced98022ac6bf1ddb168730b20a94` e SHA-256
`B7EB1E8F8E424B8C0838FCF1E1CCAF9EF9994EDA85767E55EFFFE9A459E7A6EF`.
O job identificado é `release x86_64-pc-windows-msvc simdutf`, com
`V8_FROM_SOURCE=true` e `RUSTFLAGS=-D warnings`; ele comprime
`target/x86_64-pc-windows-msvc/release/gn_out/obj/rusty_v8.lib` no artefato
esperado.

Os seis argumentos materiais emitidos por `build.rs` para essa variante são:

| Arg | Valor |
|---|---|
| `is_debug` | `false` |
| `use_custom_libcxx` | `true` |
| `v8_enable_sandbox` | `false` |
| `v8_enable_pointer_compression` | `false` |
| `v8_enable_v8_checks` | `false` |
| `rusty_v8_enable_simdutf` | `true` |

Os defaults/derivações materiais confirmados na configuração são:

- build não componentizado, `symbol_level=1` e `v8_monolithic=false`;
- ICU/i18n habilitado, com dados embutidos:
  `icu_use_data_file=false` e `v8_depend_on_icu_data_file=false`;
- snapshot interno: `v8_use_external_startup_data=false` e
  `v8_enable_snapshot_compression=false`;
- zlib V8 e partition allocator desabilitados;
- Rust/CXX e Temporal habilitados;
- WebAssembly habilitado e revectorização SIMD256 efetiva em x64;
- custom libc++ habilitado, custom libunwind desabilitado.

`target_cpu`/`target_os` não foram inventados como argumentos explícitos: a
autoridade é o target do workflow e o toolchain efetivo
`//build/toolchain/win:win_clang_x64`. O source empacotado no crate rusty_v8 é
a autoridade do V8 adaptado; o trace não aplica camada adicional de patch Deno.

Para gerar somente metadata, foram usados GN no commit
`3357c4f51b1a9e676378c695dd9c7e9911c35ee6` (SHA-256
`154197D2DA4217A7B1F607B5EC81981DC7E7A2B2257A7D6EBA75FE1FB8075B07`)
e Ninja 1.12.1, CIPD `3@1.12.1.chromium.4` (SHA-256
`48F6F1B2653E37A846DB3FADDD1C713C697B74C79318510E573D8EF53DB751AC`).
Quatro overrides do harness apontaram caminhos de toolchain para stubs inertes;
eles não alteram seleção de source e os caminhos absolutos foram normalizados.

## Root e trace exato

`ROOT_GN_TARGET = //:rusty_v8`, tipo `static_library`, não componentizado. O
output é `$BUILD_DIR/obj/rusty_v8.lib`; a aresta direta para
`//third_party/simdutf:simdutf` confirma a variante simdutf.

O trace percorre transitivamente os `deps` do `project.json` GN e registra
sources/public, outputs gerados, toolchain, tipo e arestas. O universo gerado
possui 731 targets. A closure do root possui:

| Papel | Targets |
|---|---:|
| Source/link | 273 |
| Actions/copies gerados | 39 |
| Executáveis/grupos build-only | 44 |
| **Total alcançado** | **356** |

Há 1.710 arestas alcançadas. Nenhum target `testonly` integra a closure. Os
hashes canônicos são:

- targets: `7BFFBE7AE60289E33B3CF7B5AD2A8FB8665830016809825FD846726BB084FE61`;
- arestas: `F15754AC62802C35EDEE43C5D1D3EC97D5AAE7EC0D58FBA1AD95E79265368DBA`;
- grafo normalizado: `3F99871488C47B78D18A70F2B20DC635686E45B169F3F2A57FD0A429C9526F68`;
- paths de source: `00D31ED670FACF0481ACC9CEC4D73214E0961928DC7904D0E15BF4E195FC6EFE`.

Dos 6.647 registros de source/public, há 6.576 paths únicos: 4.456 cobertos
pelo parent rusty_v8/V8 preservado, 793 pelo parent Chromium Rust separado e
1.327 outputs gerados por actions cujos inputs/geradores estão cobertos. Não há
path material sem parent.

## Classificação dos 14 candidatos V8 DEPS

Cada linha possui targets alcançados e sources selecionados. Arestas
consumidoras, revisão exata e hashes de licença ficam no manifesto.

| Candidato | Classificação | Targets | Sources | Cobertura / notice |
|---|---|---:|---:|---|
| ICU 77.1 | `VENDORED_WITH_V8` | 8 | 959 | parent rusty_v8/V8; Unicode-3.0 verificada |
| simdutf | `VENDORED_WITH_V8` | 2 | 2 | parent rusty_v8/V8; MIT verificada |
| Abseil | `VENDORED_WITH_V8` | 178 | 455 | parent rusty_v8/V8; Apache-2.0 verificada |
| partition_alloc | `FEATURE_DISABLED` | 0 | 0 | `v8_enable_partition_alloc=false` |
| libc++ | `VENDORED_WITH_V8` | 3 | 51 | parent rusty_v8/V8; Apache-2.0 WITH LLVM-exception verificada |
| libc++abi | `TARGET_NOT_APPLICABLE` | 0 | 0 | dependência somente em `!is_win` |
| libunwind | `TARGET_NOT_APPLICABLE` | 0 | 0 | `use_custom_libunwind=false` |
| llvm-libc | `VENDORED_WITH_V8` | 2 | 1 | headers por public config; Apache-2.0 WITH LLVM-exception verificada |
| Chromium Rust | `MATERIAL_SOURCE_PARENT` | 80 | 793 | parent separado exato; 45 notices verificados |
| Highway | `VENDORED_WITH_V8` | 1 | 7 | parent rusty_v8/V8; Apache-2.0 verificada |
| fast_float | `VENDORED_WITH_V8` | 1 | 1 | parent rusty_v8/V8; MIT/Apache-2.0/BSL-1.0 verificadas |
| FP16 | `VENDORED_WITH_V8` | 1 | 1 | parent rusty_v8/V8; MIT verificada |
| Dragonbox | `VENDORED_WITH_V8` | 1 | 1 | parent rusty_v8/V8; Apache-2.0 WITH LLVM-exception/BSL-1.0 verificadas |
| googletest | `TEST_ONLY` | 0 | 0 | quatro targets no universo, todos `testonly`, nenhum alcançado |

ICU é bundled/static na closure. Como `icu_use_data_file=false`, o target gera
e incorpora o payload de dados em C++; não há arquivo ICU externo a entregar.
O pin é `ee5f27adc28bd3f15b2c293f726d14d2e336cbd5` e o `LICENSE` Unicode v3
preservado tem SHA-256
`451167C55C0FA447CC2D5632714F5E3C567FE4F1E1BADEFAB2C1333852198ACA`.

simdutf é consumido diretamente pelo root; seus dois sources estão cobertos no
crate e o `LICENSE` preservado tem SHA-256
`FC8DBC04E03AD4EFC08A647FFE7F995B811A95BC04C0E85A56D5277C6593FA5F`.

O zlib V8, pin `3246f1b60849cc505e231c5d19d0cbf358093555`, permanece
`TARGET_NOT_APPLICABLE`: `v8_use_zlib=false` e
`v8_enable_snapshot_compression=false`; nenhum target foi alcançado.

Embora o target seja Windows MSVC, `use_custom_libcxx=true` torna libc++
material. libc++abi é excluído pela condição Windows; libunwind custom não é
selecionado. O runtime/toolchain Microsoft e os objetos CRT continuam P3, não
foram convertidos em parent open-source.

## Generated material, Torque e third_party adicional

Torque, `mksnapshot`, snapshot interno, bytecode builtins, regexp special-case e
embedded assembly são alcançados. Os executáveis geradores são classificados
como build/codegen; os outputs incorporados são
`GENERATED_FROM_COVERED_SOURCE`, sem criar parent para output.

Além dos 14 candidatos, o trace alcança sete raízes third-party vendorizadas no
V8: glibc, inspector_protocol, rapidhash-v8, siphash, utf8-decoder, os helpers
builtins/codegen V8 e valgrind. Todos os sources estão cobertos pelo parent V8;
suas identidades de licença e hashes dos arquivos estão registrados no
manifesto. Isso não promove diretórios third-party não alcançados.

## Notices, estado parcial e próximos passos

As identidades de licença nativas verificadas na D11A foram incorporadas ao
inventário final: nove candidatos materiais (excluído o aggregate Rust), 45
crates Chromium Rust, sete raízes third-party adicionais e o parent Rust std
1.95.0. O inventário continua `PARTIAL_GENERATED_INVENTORY`; não é um notice
oficial do Deno nem parecer jurídico.

O próximo passo proporcional é obter evidência autoritativa exata para os 15
textos remanescentes ou aprovar formalmente uma política separada de fallback
canônico. Somente com texto, expressão, notice exigido e source todos sem
pending/unknown, validações fail-closed aprovadas e classe A será permitido
montar staging e bundle COMPLETE. `verify-staging`, `assemble` e
`verify-bundle` continuam recusando a closure antes de escrever.

Permanecem separados:

- `BUILD_REPRODUCIBILITY = P2_SEPARATE_PENDING`: Rust/Cargo, GN, Ninja, Clang,
  MSVC, Windows SDK, prebuilt rusty_v8 e ambiente exato do workflow;
- `MICROSOFT CRT = P3_PENDING_REVIEW`;
- `LEGAL REVIEW = PENDING`.

As closures FFmpeg/BtbN, yt-dlp, CPython/Tcl-Tk, PyInstaller/hooks,
CFFI/cryptography e Wheel Integrity não foram reabertas. Pillow/PDFium continua
resolvido; CustomTkinter continua parcial pelo producing parent Roboto. FFmpeg
Gyan permanece ativo e BtbN segue `CANDIDATE_NOT_PROMOTED`.

## Estado do produto preservado

- `APP_VERSION = 0.9.5`;
- `product_edition = community`;
- `activation_required_for_current_edition = false`;
- `default_trust_store_key_count = 1`;
- `operational_public_key_configured = true`;
- `production_crypto_configured = true`;
- `operational_private_key_configured = false`;
- `activation_operational = true`;
- `production_ready = false`;
- `public_release_allowed = false`.

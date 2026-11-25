# Deno 2.9.5 — source review bundle

Este bundle reúne o source e as evidências técnicas correspondentes ao runtime
Deno 2.9.5 `x86_64-pc-windows-msvc` distribuído no candidato congelado
histórico do EduDownloader 0.9.5. Sua classificação é
`COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW`.

Nesse nome, `COMPLETE` significa somente que o conjunto técnico de source e
evidências está completo para revisão jurídica. Não significa aprovação
jurídica, comercial, de produção ou de publicação.

## Estrutura

- `sources/deno/`: source archive exato do Deno 2.9.5;
- `sources/cargo/`: 810 archives dos crates materiais resolvidos pela D10;
- `sources/rust/`: source archive exato do Rust 1.95.0;
- `sources/v8/`: sources exatos do V8 e do parent Rust temporal alcançado;
- `evidence/`: metadata oficial e registros crates.io fixados;
- `licenses/upstream/`: 60 textos de licença publicados pelos upstreams e
  preservados pelas D11A–D11D;
- `licenses/attribution/`: 33 manifests e registros de provenance/attribution,
  mantidos separados dos textos de licença upstream;
- `licenses/spdx-reference/`: quatro referências da SPDX License List 3.28.0;
- `review/`: provenance, inventário, notice e documentação de revisão;
- `BUNDLE_MANIFEST.json`: composição esperada e hashes por arquivo;
- `SOURCE-BUNDLE-INVENTORY.json`: inventário interno do ZIP.

## Fronteiras de licença

`UPSTREAM_LICENSE_TEXT` e `SPDX_CANONICAL_REFERENCE_TEXT` são categorias
distintas. As referências SPDX complementam expressões já comprovadas por
metadata upstream; elas não são apresentadas como arquivos originais dos
componentes.

Dos 15 casos da D11F, 13 continuam com `UPSTREAM_LICENSE_TEXT = ABSENT` e dois
continuam `PARTIAL`: `zune-core@0.4.12` e `zune-jpeg@0.4.13`. Para os dois Zune,
o `LICENSE-ZLIB` integral, a evidência Apache parcial e a metadata upstream são
preservados ao lado das referências canônicas complementares. Expressões com
`OR` permanecem integrais; nenhuma alternativa foi escolhida unilateralmente.

## Estado que o bundle não altera

- `SOURCE_CORRESPONDENCE = TECHNICALLY_COMPLETE`;
- `LICENSE_IDENTITY = RESOLVED`;
- `CANONICAL_REFERENCE_COVERAGE = COMPLETE`;
- `NOTICE_IDENTITY = RESOLVED`;
- `NOTICE_DELIVERY = PENDING_FIX` no candidato congelado histórico;
- `LEGAL_REVIEW = P3_REQUIRED`;
- `BUILD_REPRODUCIBILITY = P2_SEPARATE_PENDING`;
- `MICROSOFT = P3_PENDING_REVIEW`.

GN, Ninja, toolchain MSVC, Windows SDK e prebuilt de `rusty_v8` pertencem ao
trabalho P2 separado e não são requisitos de source deste bundle. O bundle não
contém `deno.exe`, o aplicativo proprietário EduDownloader, material de
ativação, chaves, credenciais, registros privados ou o candidato congelado.
Os dois checksums textuais dos artefatos binários Deno que continham paths
absolutos do ambiente upstream também foram excluídos; suas identidades e o
motivo estão registrados no manifesto, sem copiar os paths para o bundle.

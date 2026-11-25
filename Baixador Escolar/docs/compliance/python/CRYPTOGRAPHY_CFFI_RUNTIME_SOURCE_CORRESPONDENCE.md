# CFFI/cryptography — corresponding source open-source (D6)

Data: 2026-09-03. Baseline Git: `bfec4d2d71ff489f30dd03a15a83b4eb8617fe65`,
`codex/v0.9.5`. Escopo: somente material open-source incorporado ao candidato
Windows x64 já analisado na D5. Não é aprovação jurídica, produção ou release.

## Resultado e limites

**OPEN-SOURCE SOURCE CORRESPONDENCE: A — TECNICAMENTE COMPLETA PARA REVISÃO
JURÍDICA.** São 26 parents lógicos, 23 aquisições novas e três reusos exatos;
zero source pending, blocked ou open-source P0 UNKNOWN. Os números resultam
da inspeção física, não de uma meta de contagem.

- `NOTICE IDENTITY = RESOLVED`: textos exatos inventariados no staging/bundle.
- `NOTICE DELIVERY = PENDING_FIX`: o candidate conserva seus notices anteriores.
- `LEGAL REVIEW = PENDING`: nenhuma escolha de alternativa jurídica foi feita.
- `MICROSOFT/CRT = P3_PENDING_REVIEW`: composição dos objetos CRT estáticos
  continua **UNKNOWN**, separada dos sources open-source; não foi apagada.
- Reprodutibilidade: `P2_SEPARATE_PENDING`, não há alegação de replay bit a bit.

FFmpeg/BtbN, yt-dlp, CPython/Tcl-Tk, PyInstaller/hooks e Wheel Integrity
permanecem A; Pillow e PDFium permanecem RESOLVED nos respectivos escopos.
Gyan continua ativo e BtbN `CANDIDATE_NOT_PROMOTED`.

## Autoridades preservadas

Manifesto canônico pinado:
`CRYPTOGRAPHY_CFFI_RUNTIME_SOURCE_PROVENANCE.json`.
Validador offline: `cryptography_cffi_source_bundle.py`.

O candidate `INTERNAL_ANALYSIS_CANDIDATE`, originado de
`621a72b8c3329dc68abc0c581ec152d6c3bd9e08`, não foi reconstruído nem executado
nesta D6. Continua com 1.068 arquivos, 382.736.507 bytes e inventário
`26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857`.
Seu manifesto histórico D1 permanece byte a byte intacto.

| Material | SHA-256 |
|---|---|
| Wheel CFFI 2.1.1 cp314 win_amd64 | `3222BA5D678F80A030E6AFBCC33DC1AE5CB45FACABB61CEE2C7016B8432FDE48` |
| `_cffi_backend.cp314-win_amd64.pyd` | `9E99B2184C60F21A88CAFC374386DED3559E8694ED7CF111F2869E066D303334` |
| Wheel cryptography 49.0.0 cp311 abi3 win_amd64 | `E5DFC1E64DE5677CEC922FFA8DA89C546D0415BF6EFDF081842E5D44C84E1F0E` |
| `_rust.pyd` | `813B101F70EFB79C388239CE82AC891E195A1E19EEAEB43C32D9BF425E7B51B8` |

Os dois nativos foram novamente confrontados byte a byte com suas wheels;
candidate, inventário e manifesto de integridade das wheels foram revalidados.
A análise de materialidade D5 é reutilizada, não repetida: zero módulos Python
CFFI no PYZ; 34 módulos cryptography; consumidores `licensing.ed25519` e
`pypdf._crypt_providers._cryptography`. A cadeia nativa é cryptography →
`_rust.pyd` → glue CFFI/OpenSSL e `_cffi_backend`. Isso não aciona emissão,
assinatura, restauração ou acesso à chave operacional.

## Aquisição em duas ondas

A Onda A preservou somente CFFI 2.1.1, cryptography 49.0.0, OpenSSL 4.0.1 e
rust-src 1.96.0. Foram inspecionados nomes, tipos, tamanhos e conteúdo dos
archives, licenses, metadata e relações Git, antes da Onda B.

O rust-src 1.96.0 **não contém a pasta de crates `library/vendor`** nem sources
integrais de cfg-if/hashbrown/rustc-demangle. Os arquivos internos de
portable-simd em `src/vendor` não são essa coleção de crates. Cryptography
também não traz vendor. Portanto não houve redução dos parents da projeção D5.
A Onda B adquiriu somente 18 crates materiais cryptography ainda ausentes e
hashbrown da std. Nenhum resolver foi executado e nenhuma versão foi escolhida
por atualização de dependências.

| Parent principal | Bytes | SHA-256 | Commit / tree |
|---|---:|---|---|
| CFFI 2.1.1, tag v2.1.1 | 530807 | `DD31F52EA1086513BB9DF30F8FCEE9B8918323AE067A3D5B78BC826A000712BE` | `fd33e7700f0ebafe6f30bd5053f13327221b77a2` / `dc954328517d7d06ee8ecf663ee61c8f7511b4d5` |
| CFFI 2.0.0, tag v2.0.0, reuso | 523588 | `44D1B5909021139FE36001AE048DBDDE8214AFA20200EDA0F64C068CAC5D5529` | `6366c01d84e9a78e7e85f12ebe9760ba5d19b6d3` / `fbe91454a8a00a37b51823c1a407ca1e1c06bea1` |
| cryptography 49.0.0 | 854345 | `F89660A348F4F78A92366240A61404E337586EF7F5909A2FEF59CA88EF505493` | `e300bbe2f1bec75e5ee7e0ab7b196958831b3db6` / `614f0103a01cd84f935dab98861871d23acad409` |
| OpenSSL 4.0.1 | 55079428 | `2DB3F3A0D6EA4B59E1F094ACE2C8CD536DFFB87CDC39084C5AFA1E6F7F37DD09` | `1e963a8680ec78ad2072792c7a1a71f3c530bd2e` / `6b7ac39dd2fb86943398c625a90dd13662f46196` |
| rust-src 1.96.0 | 3868128 | `7875F9F4B91455AC25E2EA0E0F1CB3D7D16C309EF0720778538D20ED0E9B818B` | `ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96` / `6df25bba13e4c9e2caeea3b8abeafe40de6a3112` |

PyPI identifica os sdists; refs/tags/commits/trees oficiais vinculam os sources.
OpenSSL usa o asset e checksum oficiais. Rust usa o manifest oficial de
2026-05-28 e seu `xz_hash`. URLs e respostas oficiais, com hashes/provenance,
ficam na coleção P1. Nenhum script upstream foi executado.

## Cobertura material

### CFFI, libffi e código gerado

CFFI 2.1.1 cobre o backend distribuído: C, headers, glue, setup e manifest.
A libffi é o subtree histórico `src/c/libffi_x86_x64`, derivado da linhagem
CPython 2.7/Mercurial `e04e1f253ed8`, adaptado para MSVC. **Não é libffi
moderna 3.4.4**; não foi adquirido parent libffi separado.

`ffi.c`, headers, `prep_cif.c`, `types.c`, `win32.c` e `win64.asm` estão
preservados. O `win64.obj` oficial permanece no archive intacto fora do bundle;
sua fonte assembly está no bundle e a reprodução/tooling fica em P2. O binário
ARM64 `ffi.lib` também é excluído da projeção, não é material deste target x64.

O sdist não inclui LICENSE/README próprios da libffi. Foram preservados como
P1, diretamente do mesmo commit CFFI, e confrontados com blobs da tree.
LICENSE MIT-like: 1.060 bytes, SHA-256
`40A537C7D74BAEED3831304E92D1664ABABD7AD8A3CF29F11A257C9E47145248`.
O LICENSE principal CFFI é MIT-0. Libffi: `PRESERVED_WITH_CFFI_PARENT`.

CFFI 2.0.0 foi reutilizado, não baixado novamente:
`REUSED_EXISTING_SOURCE / GENERATED_CODE_SOURCE_INPUT`. Seus templates e
`recompiler.py`, cryptography `_cffi_src`/`build.rs` e os headers OpenSSL cobrem
`_openssl.c`, `_openssl.a`, constantes e bindings gerados incorporados a
`_rust.pyd`. Esses outputs não criam parents adicionais. Os requirements e
workflows upstream registram o gerador CFFI 2.0.0 e a construção das wheels.

### Cryptography e OpenSSL

Parent cryptography preservado: Python, `_cffi_src`, Cargo/workspace, build
scripts, LICENSE/Apache/BSD e os oito crates locais 0.49.0:
cryptography-rust, cffi, crypto, keepalive, key-parsing, openssl, x509 e
x509-verification (todos com prefixo `cryptography-`). Eles herdam versão e
licença do workspace; não são oito aquisições adicionais.

Cargo.lock da raiz: SHA-256
`104F567EE229A7D3D27189D404E276BE705BF2CA384753DB6669FCF706591B1D`.
O SBOM tem 40 nós: 39 components mais o componente raiz. Sua correspondência
com o lock é conferida offline; aparecer no lock não significa runtime.

OpenSSL **4.0.1**, e não 3.5.7 da closure CPython, cobre a ligação estática
de `_rust.pyd`. Evidências: `OPENSSL_STATIC=1`, `VC-WIN64A`, `no-shared`,
`no-module`, `no-zlib`, flags de build e SBOM da própria wheel. Não há parent
zlib novo. LICENSE.txt Apache-2.0 e demais notices do parent são preservados.
SBOM OpenSSL SHA-256:
`3C84A13E98A66E600308A4691DE245E4F1C6CC1B818901A9D22FC5C1B69E006F`;
SBOM Rust/Cargo:
`1EFDA14501A10FA09A8634355D52A54C8DFEFE2E1EB2869558645D18EA11E46D`.
Os SBOMs são evidências, não parents. Seus paths de CI upstream não são paths
pessoais do operador; foram preservados sem reescrever o documento oficial.

### Rust/std e reusos

Rust 1.96.0 cobre core, alloc, std, Windows PAL/glue, panic_unwind/SEH,
std_detect, stdarch e `compiler_builtins 0.1.160`. Backtrace corresponde à
revision `28ec93b503bf0410745bc3d571bf3dc1caac3019` (79 blobs conferidos).
COPYRIGHT, LICENSE-MIT, LICENSE-APACHE, licenças de backtrace, compiler-builtins,
libm/libunwind e exceção LLVM aplicável estão inventariados arquivo por arquivo.

- cfg-if 1.0.4: **REUSED**, 13/13 arquivos de checksum conferidos.
- rustc-demangle 0.1.27: **REUSED**, 15/15 arquivos conferidos.
- hashbrown 0.16.1: **PRESERVED_NEW**, checksum exato do lock std.

Os dois reusos vêm do carrier rust-src 1.97.1 já preservado. Somente os
subtrees exatos, incluindo `.cargo-checksum.json`, foram copiados; o carrier
1.97.1 não entrou no bundle e não substitui o runtime source 1.96.0.

## Crates e licenças

Todos os archives novos têm filename canônico, tamanho, SHA-256, name/version,
Cargo.toml, inventário e license files conferidos. A autoridade é crates.io
name/version/checksum, sem exigir um commit VCS artificial.

| Classe | Sources preservados |
|---|---|
| Runtime, 15/15 | asn1 0.24.1; base64 0.22.1; bitflags 2.13.0; cfg-if 1.0.4 (reuso); foreign-types 0.3.2; foreign-types-shared 0.1.1; itoa 1.0.18; libc 0.2.186; once_cell 1.21.4; openssl 0.10.81; openssl-sys 0.9.117; pem 3.0.6; pyo3/pyo3-ffi 0.29.0; self_cell 1.2.2 |
| Codegen material, 4/4 | asn1_derive 0.24.1; openssl-macros 0.1.1; pyo3-macros/pyo3-macros-backend 0.29.0 |
| BUILD_ONLY/P2, 12 excluídos | cc 1.2.64; find-msvc-tools 0.1.9; pkg-config 0.3.33; pyo3-build-config 0.29.0; shlex 2.0.1; target-lexicon 0.13.5; vcpkg 0.2.15; heck 0.5.0; proc-macro2 1.0.106; quote 1.0.45; syn 2.0.117; unicode-ident 1.0.24 |
| TARGET_NOT_APPLICABLE, 1 excluído | portable-atomic 1.13.1: condição `not(target_has_atomic = "64")`, não aplicável ao Windows x64 auditado |

Licenças identificadas: asn1/asn1_derive BSD-3-Clause; openssl Apache-2.0;
openssl-sys e pem MIT; self_cell Apache-2.0 OR GPL-2.0-only, **ambos os textos
preservados**, sem escolher juridicamente uma alternativa. Os demais registram
MIT OR Apache-2.0 ou a grafia upstream `MIT/Apache-2.0`, sem normalizar
silenciosamente a metadata. Expressões e hashes de cada arquivo constam no
manifesto. Crates build-only e portable-atomic não foram adquiridos.

## Projeção e auditoria do bundle

Archives de entrada permanecem intactos, ignorados pelo Git, fora do bundle.
A projeção exclui prebuilt objects e arquivos de fixtures upstream PEM/DER,
PKCS#12 e similares, com path/hash/motivo explícitos. Nenhum executable, wheel,
PYD, Microsoft DLL, código proprietário, material administrativo ou chave do
operador entrou no staging/bundle.

**Não se afirma ausência de toda string PEM.** Sete arquivos materiais
upstream são aceitos exclusivamente por path **e SHA-256 fixos**:
cryptography `serialization/ssh.py`, openssl `dsa.rs`, `ec.rs`, `pkey.rs`,
`pkey_ctx.rs`, `rsa.rs` e pem `lib.rs`. Contêm delimitadores/documentação;
os dois últimos casos relevantes (`pkey_ctx.rs` e pem `lib.rs`) também têm
vetores públicos upstream embutidos em testes/documentação. Não são segredo
nem chave operacional do emissor. Esses arquivos não foram alterados; qualquer
byte divergente perde a exceção. Arquivos avulsos de chave continuam proibidos.

Comparação com upstream: CFFI 205 blobs e gerador 191; cryptography 475;
OpenSSL 6.008; Rust library 2.170 mais backtrace 79. Oito exemplos CFFI são
links Git materializados no sdist, não diferenças no backend. `CLAUDE.md`
difere no sdist cryptography, é documentação sem materialidade runtime.
PKG-INFO/egg-info são outputs de sdist. Ausências Git incluem CI, vectors e
ferramentas/testes stdarch, não o runtime requerido. Essas diferenças são
inventariadas; não há alegação de que sdist e checkout completo são idênticos.

## Inventário e reprodução offline

Staging final ignorado: `build-compliance-cryptography-cffi/staging-source-only`.
São **9.533 arquivos / 206.113.032 bytes**, inventário
`EE62CD918E8158AD40B48E5EB91971CE25D61DEAB24BB9A5EBCBB9F01603AD7C`.

Bundle em `build-compliance-cryptography-cffi/bundles/`:
`EduDownloader-ThirdParty-Source-Cryptography-CFFI-COMPLETE.zip`.
São **9.535 entradas / 73.092.438 bytes**, 212.762.094 bytes descomprimidos;
SHA-256 `B423677E623182AD580438134EDC2D25DF1EBD2AEA57817D9EBCBCE83461E6FE`;
inventário do bundle
`7B034EF17CAB27183F0C4A0C973EC35338E3FE30F63144E46C5F0E754E2147F8`.
O manifesto e o inventário interno explicam as duas entradas adicionais.
Duas montagens independentes produziram o mesmo SHA-256, entradas e inventário.

Com o Python do ambiente fechado, sem rede nem resolver:

```text
python cryptography_cffi_source_bundle.py verify-staging
python cryptography_cffi_source_bundle.py verify-inputs
python cryptography_cffi_source_bundle.py verify-frozen
python cryptography_cffi_source_bundle.py assemble
python cryptography_cffi_source_bundle.py verify-bundle
python cryptography_cffi_source_bundle.py assemble --bundle <novo-zip-de-verificacao>
```

Saídas existentes nunca são sobrescritas. O manifesto esperado é externo ao
ZIP e fixado no validador; adulterar o ZIP e seu inventário não redefine a
autoridade. O primeiro staging exploratório, anterior à revisão dos sete
arquivos materiais, não é o staging aprovado nem evidência de closure A.

## Validação final

- 19 testes focados offline, com subcasos de parents, cobertura, geração,
  exclusões, hashes, reuso, leakage, paths e ZIP adulterado: OK.
- Suíte completa: **1.047 testes, 4 skips, OK** (Python 3.14.6).
- Ruff check e format --check: OK, 109 arquivos; compileall no escopo
  rastreado mais os dois novos arquivos Python: OK, 109 arquivos.
- Fonte/licenciamento: OK, 76 arquivos. Distribuição e licenciamento
  congelado: OK, 1.068 arquivos; consistência do manifesto candidate: OK.
- Ambiente exato/requirements lock, pip check e Wheel Integrity classe A
  para as 17 wheels: OK. Locks e wheel provenance não foram alterados.
- Manifesto canônico idêntico ao gerado dos inputs, pin SHA-256, inventário
  completo, 65 textos de license/copyright/notice e 1.071 exclusões: OK.
- verify-staging, verify-inputs, verify-frozen, assemble, verify-bundle e
  segunda montagem independente: OK; ZIPs também comparados byte a byte.
- Diff de código/documentação e todos os registros gerados revisados;
  git diff --check: OK. Nenhum archive, staging ou bundle foi adicionado ao Git.

## Pendências separadas e gates

Maturin 1.14.0, Cargo/rustc binários, setuptools, cibuildwheel, MSVC, Windows
SDK, reprodução de win64.obj e CI/replay exato continuam P2. Microsoft/CRT
continua P3, uma incerteza de composição estática, sem aquisição Microsoft ou
parecer de redistribuição. Entrega futura de notices, Deno transitivo,
CustomTkinter, revisões jurídicas e demais tarefas pré-1.0 continuam abertas.

APP_VERSION `0.9.5`; ProductEdition `community`;
`activation_required_for_current_edition = false`.

| Campo | Valor preservado |
|---|---|
| default_trust_store_key_count | 1 |
| operational_public_key_configured | true |
| production_crypto_configured | true |
| operational_private_key_configured | false |
| activation_operational | true |
| production_ready | false |
| public_release_allowed | false |

Sem rebuild, PyInstaller, emissão, comando key-*, acesso à chave privada,
promoção BtbN, push, merge ou tag. **TESTE INTERNO — NÃO PUBLICAR.**

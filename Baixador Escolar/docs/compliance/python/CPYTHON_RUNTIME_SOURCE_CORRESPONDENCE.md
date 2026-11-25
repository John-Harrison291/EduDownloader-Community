# Source correspondence do runtime CPython 3.14.6 / Tcl-Tk 8.6

## Resultado técnico

**Classe: A — TECNICAMENTE COMPLETA PARA REVISÃO JURÍDICA**

Esta conclusão cobre somente o corresponding source material da composição
CPython/Tcl-Tk observada no candidato congelado interno 0.9.5. Não constitui
aprovação jurídica, não comprova reprodutibilidade bit a bit e não autoriza
produção ou publicação.

O manifesto fail-closed canônico é
`CPYTHON_RUNTIME_SOURCE_PROVENANCE.json`. Ele fixa versões, revisions Git,
trees, archives, hashes, consumers, licenças, metadados do release, relações de
reuso e as separações que continuam pendentes.

## Autoridade do candidato

- classificação: `INTERNAL_ANALYSIS_CANDIDATE`;
- source commit: `621a72b8c3329dc68abc0c581ec152d6c3bd9e08`;
- inventário pristine: 1.068 arquivos, 382.736.507 bytes;
- SHA-256 canônico do inventário:
  `26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857`;
- CPython: 3.14.6 x64;
- Tcl/Tk: 8.6.15;
- DLLs Microsoft mantidas fora desta closure: 45 arquivos, 2.522.376 bytes.

O candidato não foi reconstruído ou modificado durante esta etapa.

## Dez source parents lógicos

| Parent | Versão | Preservação | Commit | Tree | SHA-256 do source |
|---|---:|---|---|---|---|
| CPython | 3.14.6 | `PRESERVED_NEW` | `c63aec69bd59c55314c06c23f4c22c03de76fe45` | `ad415ee943062293d0032daad921a37a3b760410` | `143B1DDDEFAEC3BD2E21E3B839B34A2B7FB9842272883C576420D605E9F30C63` |
| bzip2 | 1.0.8 | `REUSED_EXISTING_SOURCE` | `05301997b2f9590f49c672cf3dfd3d3dfa7ad521` | `933e65e88f0a28f9bcbc8abe5a4c12e3f618c043` | `12C17D15F99E27235529574A722FB484A4E8FDF2427CEF53B1B68BDF07E404A9` |
| libffi | 3.4.4 | `PRESERVED_NEW` | `73b247f34ef3ae1859b8c2c34d321d34ebc5db15` | `dba0e3bd6143ae50d7017850345f7053775c6677` | `9D802681ADFEA27D84CAE0487A785FB9CAA925BDAD44C401B364C59AB2B8EDDA` |
| mpdecimal | 4.0.0 | `PRESERVED_NEW` | `48316ec025c1ebe500854c332be0a12c640c7301` | `1ecd3b3fb74d2b6c93f384b553a6023a88e0de34` | `338FAC3FB8CDD60F406B6326431338756F58A8AF94229FFD9BF1E7C2B1AD71CA` |
| OpenSSL | 3.5.7 | `PRESERVED_NEW` | `6a6901fa60c604816acb50b4e167791e5339c8f8` | `4f5b47534bc1016b89e70bd6dc27382670adcee5` | `CA94E7C6C223D9CAF77BB51AAC5949186379608EA2A0CAD3AA8BDF31856912E9` |
| Tcl | 8.6.15.0 | `PRESERVED_NEW` | `275286594fd3e162af29e8c0ba4e365d3d1f7775` | `85bd8c2c9b2f8db34f56d08efdb3f65dd909b7c3` | `4C23F0DD3EFCBE6F3A22C503A68D147617BB30C4F5290F1EB3EAACF0B460440B` |
| Tk | 8.6.15.0 | `PRESERVED_NEW` | `a526badcf885e4986e13e68695398a0bb64d5ea1` | `642dd68515c70ff138bc867919304f0936cf3fe9` | `0AE56D39BCA92865F338529557A1E56D110594184B6DC5A91339C5675751E264` |
| XZ | 5.2.5 | `REUSED_EXISTING_SOURCE` | `c6bc0c612605622aaef101a33a751f9de2ecc193` | `2b8fb6a3c0b111c2175bec896b2a22448fd0ac4b` | `6A4389CC05143BEB2679B1299CECEE71B02BAA55E70F68A88B44DC01AD495424` |
| zlib-ng | 2.2.4 | `PRESERVED_NEW` | `a502e047655c31db29601def76ad6539acacf43d` | `897870eecd4dd0e8cc94db018ddb09bc01348671` | `00BBD88709BC416CB96160AB61D3E1C8F76E106799AF7328D0FE434DC7DD5004` |
| Zstandard | 1.5.7 | `PRESERVED_NEW` | `eef946ae8cf1591c0e5cc5f43486210768647c2e` | `65df13bfb803791fd5d2073f3ce86a8743dd05ff` | `F24B52470D12F466E9FA4FCC94E6C530625ADA51D7B36DE7FDC6ED7E6F499C8E` |

Foram adquiridos oito parents novos. bzip2 e XZ foram copiados dos artifacts
já preservados pela closure yt-dlp e confrontados com os mesmos commit, tree e
SHA-256; nenhum dos dois foi baixado novamente.

## CPython e metadados oficiais

O arquivo `Python-3.14.6.tar.xz` corresponde à tag anotada `v3.14.6`, tag
object `8594736f5057fdc979d42d2135895d56274589a8`, commit e tree acima. O
archive oficial possui 5.100 arquivos. Em relação à tree Git, 4.935 blobs
coincidem diretamente, 164 coincidem após normalização CRLF/LF, 185 blobs são
omissões explicadas do export de release e o único arquivo exclusivo do
archive é `Misc/NEWS`; não restou divergência de conteúdo sem explicação.

Foram preservados o índice e a página oficiais do release, o bundle Sigstore e
o SBOM SPDX do source, além do manifesto Windows 3.14.6 e seu bundle Sigstore.
Os digests ligam o source e o manifesto Windows aos artifacts oficiais. Não foi
inventada ou exigida assinatura PGP para este release.

Também foram preservados `LICENSE`, `Doc/license.rst`, as licenças históricas e
os avisos de documentação aplicáveis, sem tratar a closure como revisão
jurídica concluída.

## Cobertura pelo parent

O source CPython cobre o código de `python314.dll`, `python3.dll`, stdlib,
inputs de `base_library.zip`, os wrappers das 16 extensões observadas e:

- Expat 2.8.1 em `Modules/expat` — `PRESERVED_WITH_PARENT`;
- HACL na revisão `8ba599b2f6c9701b3dc961db895b0856a2210f76` —
  `PRESERVED_WITH_PARENT`;
- tabelas Unicode 16.0.0 e seu gerador — `PRESERVED_WITH_PARENT`;
- wrappers `_tkinter`, `_decimal`, `_ssl`, `_hashlib`, `_bz2`, `_lzma`,
  `_ctypes` e `_zstd`.

Tcl cobre sua biblioteca de scripts, encodings, mensagens, tzdata, módulos
`.tm`, o diretório `compat/zlib` 1.3.1 completo com 266 arquivos e o snapshot
`libtommath` completo com 76 arquivos. Esses dois últimos materiais ficam
`PRESERVED_WITH_PARENT`, sem criar parents lógicos adicionais.

SQLite 3.50.4.0 aparece nos pins PCbuild, mas `_sqlite3.pyd` e `sqlite3.dll`
não existem no candidato observado. Por isso está `NOT_REQUIRED` nesta closure,
e não foi baixado.

## Evidência bin-deps

Metadados oficiais pequenos de `python/cpython-bin-deps` ligam os sources aos
inputs Windows:

- `libffi-3.4.4`: commit
  `94cb9a1c7feb608adf2b9f8fe2dbd6925ffbf90d`, tree
  `bf8087b61bea675a2d4ab393e25e017a9eea9734`;
- `openssl-bin-3.5.7`: commit
  `3217be5a2a7e20dbc5f5b5160ef21a9c84de7138`, tree
  `489fe20520999c58ed7f39d43bea3c482ec46cee`;
- `tcltk-8.6.15.0`: commit
  `5a51bb7b87efa119332c52b04a84c49d3042279c`, tree
  `d30680904f4152fa2fd06bda1f332b7041c8728c`.

Esses três registros são evidência de provenance, não source parents novos.

## Licenças e notices

Vinte arquivos de licença/notice foram extraídos byte a byte dos dez parents e
fixados por tamanho e SHA-256. O inventário cobre PSF e licenças históricas do
CPython, bzip2, libffi, mpdecimal, Apache-2.0 do OpenSSL, Tcl, Tk, zlib,
libtommath, XZ, zlib-ng e Zstandard. Nenhuma conclusão jurídica é inferida.

O `license.terms` do Tk presente no candidato corresponde ao source após a
normalização documentada de CRLF/LF. O source e a licença Tcl estão preservados
no bundle, mas o candidato não expõe `license.terms` sob `_tcl_data`; isso é
`NOTICE_GAP_TO_FIX_LATER`, e não source gap.

## Staging e bundle

- staging: 104 arquivos, 112.285.992 bytes;
- SHA-256 do inventário canônico do staging:
  `BAB3AB1AEE9191B564CA87A7F5BE2F417E7AB2315C99F84A373D79BF55F5FFA8`;
- bundle:
  `EduDownloader-ThirdParty-Source-CPython-3.14.6-COMPLETE.zip`;
- bundle: 106 entradas, 104.692.758 bytes;
- SHA-256 do bundle:
  `B17AFD66AD30715B6E6B642FA77FAEE53CA7DD2F220840871490FEE0812705DA`;
- SHA-256 do inventário interno:
  `D46524F07ABEA780ADF91DAA1609A35043A5FC816A154E9C3D9BD36265C8BDDE`.

Duas montagens independentes produziram bytes e SHA-256 idênticos. O staging e
o bundle ficam em `build-compliance-python-runtime/`, ignorado pelo Git. Não
foi adicionado executável separado, candidate binário, wheelhouse, código
proprietário, material privado de ativação, chave ou segredo. Archives oficiais
de source foram mantidos integrais, inclusive eventual payload auxiliar que o
próprio upstream versiona dentro deles.

## Validação fail-closed

`python_runtime_source_bundle.py` valida offline:

- hash canônico e estrutura do manifesto;
- os dez parents, oito aquisições e dois reusos exatos;
- versões, hashes, commits, trees e conteúdo dos archives;
- metadados Git source-deps/bin-deps, SPDX e Sigstore;
- licenças extraídas e inventários de metadata;
- cobertura interna de Expat, HACL, Unicode, zlib Tcl e libtommath;
- separação de SQLite não material, Microsoft e reprodutibilidade;
- ausência de executáveis adicionados separadamente, candidate e material
  privado no staging;
- correspondência do candidate e notice Tk;
- composição, inventário e bytes do bundle determinístico.

O validador rejeita ausência ou adulteração de source, hash/revision/tree
incorretos, licença ausente, parent inesperado, classe A com material pendente e
leakage proibido.

## Pendências separadas

- revisão jurídica: `PENDING`;
- notice Tcl na distribuição: `NOTICE_GAP_TO_FIX_LATER`;
- runtime Microsoft: `P3_PENDING_LEGAL_REVIEW`;
- reprodutibilidade integral do build: `SEPARATE_PENDING_REVIEW`;
- PyInstaller 6.21.0 e runtime hooks;
- cffi 2.1.1;
- cryptography 49.0.0;
- notices transitivos do Deno;
- reconciliação de notice/licença do CustomTkinter.

Pillow/PDFium e as closures de source yt-dlp e BtbN já resolvidas não foram
reabertas. Gyan continua sendo o FFmpeg ativo, e BtbN continua apenas
`CANDIDATE_NOT_PROMOTED`.

## Gates preservados

- `APP_VERSION: 0.9.5`;
- `product_edition: community`;
- `activation_required_for_current_edition: false`;
- `activation_operational: true`;
- `production_ready: false`;
- `public_release_allowed: false`.

O resultado permanece **TESTE INTERNO — NÃO PUBLICAR**.

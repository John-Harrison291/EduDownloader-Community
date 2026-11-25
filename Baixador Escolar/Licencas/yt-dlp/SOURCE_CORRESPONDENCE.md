# Source correspondence técnico do yt-dlp 2026.08.19

## Estado e limites

Classificação atual: **A — TECNICAMENTE COMPLETA PARA REVISÃO JURÍDICA**.

O source principal, os inputs textuais do build Windows x64 e todos os source
parents materiais observados no executável foram preservados em staging local
ignorado pelo Git. Não há source gap material conhecido. Esta classificação é
técnica: não constitui conclusão jurídica, não cria candidate 1.0 e **não
autoriza publicação**.

O staging e o bundle separado não pertencem ao cliente, ao R2 ou ao R3. O R3
permanece evidência histórica imutável da baseline 2026.07.04.

## Baseline vinculada

- release/tag: `2026.08.19` stable;
- commit da tag: `3a08beaf031ab68f966401ead017ac81fe8486cf`;
- source funcional (`RELEASE_GIT_HEAD`):
  `594bd50c2c78ac432f81600d309fdc4e0a92d82c`;
- executável oficial: 17.840.399 bytes;
- SHA-256 do executável:
  `66674953FE251B89F4D08C5F0E35E0728679BD67AB3D7D05C0562AF101DD3E7A`;
- source oficial: 6.020.567 bytes;
- SHA-256 do source:
  `072AAD4F2A7604E92155F61A275A4752DC64046C8F6D90DF3710525D94CD37C1`.

O executable e o source coincidem com `SHA2-256SUMS`, com os digests da API
oficial da release e com a attestation GitHub preservada. A tag lightweight
aponta ao commit de release; `RELEASE_GIT_HEAD` identifica separadamente o
source funcional incorporado.

## Cadeia de build

O workflow oficial da tag usa Python 3.10 x64, requirements com hashes,
PyInstaller 6.22.0 e o source do yt-dlp para produzir o `win_exe`. A auditoria
material confirmou CPython 3.10.11 AMD64. O source do PyInstaller/bootloader
está preservado no asset oficial `pyinstaller-6.22.0.tar.gz`, juntamente com o
workflow, locks e metadata da release Pyinstaller-Builds
`2026.08.19.215425`.

A reprodução bit a bit da toolchain não foi alegada: o status de
reprodutibilidade continua parcial.

## Delta de source parents

Contagem considerando o source principal:

- `REUSED_PARENT`: 22;
- `UPDATED_PARENT`: 14;
- `NEW_PARENT`: 1;
- `REMOVED_PARENT`: 2;
- total corrente: 37 parents (source principal + 36 archives externos).

Os 22 reutilizados, por identidade e bytes, são: mutagen, yt-dlp-ejs, package
e source Astring, package e source Meriyah, nghttp2, nghttp3, ngtcp2, Brotli
Python, idna, pycparser, PyCryptodome, requests, urllib3, CPython e seus seis
externals materiais (OpenSSL, SQLite, bzip2, zlib runtime, libffi e XZ).

Os 14 atualizados são o source principal do yt-dlp, certifi, Mozilla certdata,
curl, curl-impersonate, curl_cffi, PyInstaller, BoringSSL, Brotli nativo, zlib
nativo, zstd, cffi, charset-normalizer e websockets. `typing-extensions` é o
parent novo. `packaging` e `setuptools` foram removidos porque o novo PYZ não
contém esses pacotes; continuam registrados apenas como ferramentas de build.

## Certifi

Certifi 2026.7.22 possui sdist PyPI exato. O `cacert.pem` tem SHA-256
`9CC2A774B5198DCFF14D9BE1E66091F538975D867CE029A96BCE15A55DFD730F`.
A revisão Mozilla certdata
`4e9426ae522c67de47ff3e060774328b42df0134` foi preservada e corresponde
deterministicamente aos mesmos **121 certificados** confiáveis.

## Curl nativo

O sdist curl_cffi 0.16.0 fixa curl-impersonate `v2.0.0`. A receita CMake
oficial e seus hashes fixam:

| Parent | Revisão/versão | Estado |
|---|---|---|
| curl | 8.21.0 (`curl-8_21_0`) | verificado |
| BoringSSL | `156c7b75ae9b8c3b3f847acf264f17594c3859fb` | verificado |
| Brotli nativo | 1.2.0 | verificado |
| nghttp2 | 1.63.0 | reutilizado/verificado |
| nghttp3 | 1.15.0 | reutilizado/verificado |
| ngtcp2 | 1.20.0 | reutilizado/verificado |
| zlib | 1.3.1 | verificado |
| zstd | 1.5.7 | verificado |

No Windows, a receita mantém `USE_LIBIDN2` desligado. Os seis patches oficiais
foram preservados e verificados por hash e estrutura. A aplicação/reprodução
mecânica integral continua parcial; isso não é tratado como source gap.

## Python P2

Python P2 geral: **RESOLVIDO TECNICAMENTE**.

Os dez parents materiais são Brotli Python 1.2.0, cffi 2.1.1,
charset-normalizer 3.5.0, idna 3.18, pycparser 3.0, PyCryptodome 3.23.0,
requests 2.34.2, typing-extensions 4.16.0, urllib3 2.7.0 e websockets 16.1.1.
Os sdists, hashes PyPI, locks, membros materiais e licenças foram verificados
offline. `setuptools` e `packaging` não têm material no PYZ corrente.

## EJS e runtime CPython

yt-dlp-ejs 0.8.0 continua byte-identical, com Astring 1.9.0 e Meriyah 6.1.4
cobertos pelos parents preservados. A política do cliente continua usando Deno
local com `--no-remote-components`.

O runtime permanece CPython 3.10.11. O source parent cobre Expat e mpdecimal;
os externals materiais preservados são OpenSSL, SQLite, bzip2, zlib runtime,
libffi e XZ. As divergências de versão do notice upstream são reconciliadas em
`RUNTIME_SOURCE_NOTICES.md` sem adulterar o texto oficial.

## Notice e entrega

O `THIRD_PARTY_LICENSES.txt` da tag 2026.08.19 corresponde ao material
incorporado no executável e acrescenta, entre outras, as seções de
curl-impersonate, curl, BoringSSL, nghttp2, ngtcp2, nghttp3 e OpenSSL 1.x.
Menções não materiais, como componentes não presentes no PYZ, não foram
promovidas a source parents.

O bundle separado validado fica em
`compliance_artifacts/yt-dlp/2026.08.19/` e contém inventário determinístico.
Ele exclui o código proprietário do EduDownloader. A forma jurídica definitiva
de oferta/entrega e a revisão jurídica continuam pendentes.

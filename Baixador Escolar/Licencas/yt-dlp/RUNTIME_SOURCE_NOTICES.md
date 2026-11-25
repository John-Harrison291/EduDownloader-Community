# Suplemento técnico do runtime CPython no yt-dlp.exe

## Escopo

Este suplemento reconcilia os componentes materiais do runtime CPython 3.10.11
AMD64 incorporado ao `yt-dlp.exe` oficial 2026.08.19. Ele não altera o arquivo
upstream `THIRD_PARTY_LICENSES.txt`, não substitui os textos integrais dentro dos
archives preservados e não constitui conclusão jurídica.

| Componente | Versão material | Incorporação | Textos preservados no source |
|---|---:|---|---|
| OpenSSL | 1.1.1t | `libcrypto-1_1.dll`, `libssl-1_1.dll`, `_ssl.pyd` e `_hashlib.pyd` | `LICENSE` (OpenSSL License e Original SSLeay License) e `external/perl/Text-Template-1.46/COPYING` |
| SQLite | 3.40.1 | amalgamation usada por `sqlite3.dll` e `_sqlite3.pyd` | declaração de domínio público em `sqlite3.c` e `sqlite3.h` |
| bzip2 | 1.0.8 | link estático em `_bz2.pyd` | `LICENSE` |
| zlib | 1.2.13 | compilada no runtime CPython | `LICENSE` |
| libffi | pin CPython 3.3.0 | `libffi-7.dll` e `_ctypes.pyd` | `LICENSE` e `LICENSE-BUILDTOOLS` |
| XZ/liblzma | 5.2.5 | link em `_lzma.pyd` | `COPYING`, `COPYING.GPLv2`, `COPYING.GPLv3` e `COPYING.LGPLv2.1` |

Um futuro pacote de source/licenciamento deverá conservar os seis archives com
todos esses textos integrais e acompanhar este suplemento e o notice oficial
do yt-dlp. A forma jurídica de oferta/entrega ainda precisa ser revisada.

Os seis ZIPs são snapshots oficiais das tags exatas de
`python/cpython-source-deps` baixadas pela estratégia de
`PCbuild/get_external.py`. Como não foi localizado checksum oficial publicado
para esses ZIPs gerados por tag, cada SHA-256 local está classificado como
`local_calculated_verified_revision`. Cada archive foi comparado blob a blob
com a tree Git oficial do commit fixado; commit/tree Git não foi tratado como
SHA-256 do archive.

## Discrepâncias reconciliadas

- O notice upstream preservado menciona OpenSSL `3.0+`, mas o executável
  auditado contém OpenSSL 1.1.1t. Este suplemento registra o material real sem
  adulterar o documento upstream.
- O notice upstream ainda menciona bzip2 1.0.6; o pin PCbuild, o source
  preservado e o material auditado correspondem a bzip2 1.0.8.
- O tag/source-deps e o pin binário do libffi são `3.3.0`; o `configure.ac` da
  tree exata preservada conserva o marcador upstream `3.3-rc0`. A
  correspondência desta baseline se apoia nas revisions completas e nos pins
  Windows do CPython, sem rebatizar o conteúdo upstream.
- A zlib 1.2.13 deste suplemento pertence ao runtime CPython. Ela permanece
  distinta da zlib 1.3 da closure nativa de curl, preservada sob outra revision
  e outro papel material.
- O libffi deste suplemento pertence ao runtime CPython. Ele permanece distinto
  do source libffi incorporado ao sdist do cffi 2.1.1.

Expat 2.5.0 e mpdecimal 2.5.1 são cobertos pelo source parent CPython. Tcl,
Tk, Tix e `_tkinter` não estão presentes no `yt-dlp.exe`; NASM é apenas input
de build. Nenhum source separado desses componentes foi acrescentado.

## Limites

VCRUNTIME140, UCRT, `api-ms-win-*` e DLLs de sistema permanecem sujeitos aos
termos de redistribuição Microsoft, separados desta correspondência de source
open source. O snapshot integral da toolchain Windows, a reprodução bit a bit,
a proveniência exata do patch do toolcache e a revisão jurídica do método de
entrega continuam fora do fechamento técnico registrado aqui.

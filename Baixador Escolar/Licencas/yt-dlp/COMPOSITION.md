# Composição auditada do yt-dlp.exe 2026.08.19

## Escopo

Este registro descreve o executável oficial `win_exe` da release estável
2026.08.19 que o EduDownloader redistribui sem modificação. O SHA-256 auditado
é `66674953FE251B89F4D08C5F0E35E0728679BD67AB3D7D05C0562AF101DD3E7A`.
O EduDownloader não compilou esse executável e permanece uma aplicação
proprietária separada.

O código-base do yt-dlp está sob The Unlicense. O upstream registra que os
executáveis empacotados com PyInstaller incluem código GPLv3+ e, por isso, a
obra combinada é GPLv3+. Essa classificação do executável externo não altera a
licença do código próprio do EduDownloader.

## Estrutura observada

- formato: PyInstaller one-file, com CArchive e PYZ;
- CArchive: 150 entradas;
- PYZ: 1.584 módulos;
- total auditado: 1.734 entradas;
- runtime incorporado: CPython 3.10.11 AMD64;
- source funcional (`RELEASE_GIT_HEAD`):
  `594bd50c2c78ac432f81600d309fdc4e0a92d82c`;
- commit da tag de release:
  `3a08beaf031ab68f966401ead017ac81fe8486cf`.

Entre os componentes materiais observados estão `yt_dlp`, Cryptodome, brotli,
certifi, cffi, pycparser, charset_normalizer, curl_cffi, idna, mutagen,
requests, typing_extensions, urllib3 e websockets, além do runtime Python. Os
pacotes `setuptools` e `packaging` usados na construção não aparecem no PYZ da
baseline 2026.08.19 e são classificados como build-only.

O CArchive mantém o runtime CPython 3.10.11 e suas DLLs OpenSSL 1.1.1t. A nova
composição separa o wrapper `curl_cffi` do DLL nativo
`libcurl-impersonate-8.21.0...dll`, correspondente ao curl-impersonate 2.0.0 e
aos parents nativos fixados pela receita CMake oficial.

## EJS local

A composição contém `yt_dlp_ejs` 0.8.0 e os arquivos JavaScript
`yt_dlp_ejs/yt/solver/core.min.js` e `yt_dlp_ejs/yt/solver/lib.min.js`. O Deno
distribuído pelo EduDownloader continua sendo invocado localmente. A política
`--no-remote-components` permanece inalterada e nenhum download remoto de EJS
foi autorizado.

## Licenças preservadas

- `YT-DLP-UNLICENSE.txt`: licença do código-base na tag;
- `THIRD_PARTY_LICENSES.txt`: conjunto oficial integral da tag 2026.08.19;
- `GPL-3.0.txt`: GPLv3 integral preservada da seção correspondente;
- `SHA2-256SUMS`: checksums oficiais da release;
- `PROVENANCE.json`: vínculo entre binário, release, commits e documentos;
- `SOURCE_PROVENANCE.json`: inventário determinístico do source separado.

O `THIRD_PARTY_LICENSES.txt` corrente corresponde byte a byte, após apenas a
normalização LF/CRLF de leitura, ao documento incorporado no executável. Ele
inclui as famílias materiais do novo runtime, entre elas curl-impersonate,
curl, BoringSSL, nghttp2, ngtcp2, nghttp3 e OpenSSL 1.x.

## Source correspondence

Estado: **staging validado, sources externos dos lotes 1, 1B, 1C, 1D, 1E e
1F preservados, source chain material tecnicamente completa (classe A) para
revisão jurídica**.

O delta 2026.07.04 → 2026.08.19 reutilizou 22 source parents idênticos,
atualizou 14 identidades contando o source principal, acrescentou
`typing-extensions` e removeu `packaging`/`setuptools` da closure material.
O staging contém 36 archives externos mais o source principal. O bundle
separado foi montado e reaberto com inventário determinístico.

PyInstaller 6.22.0, certifi 2026.7.22, curl_cffi 0.16.0,
curl-impersonate 2.0.0, curl 8.21.0, cffi 2.1.1,
charset-normalizer 3.5.0 e websockets 16.1.1 possuem source exato preservado.
A closure nativa também preserva BoringSSL na revisão exata, Brotli 1.2.0,
zlib 1.3.1 e zstd 1.5.7; nghttp2 1.63.0, nghttp3 1.15.0 e ngtcp2 1.20.0 foram
reutilizados sem alteração. A reprodução mecânica integral da toolchain e dos
patches permanece parcial e não é apresentada como reprodução bit a bit.

O contrato completo está em `SOURCE_PROVENANCE.json` e
`SOURCE_CORRESPONDENCE.md`. Não há source gap material conhecido, mas a revisão
jurídica e o método definitivo de entrega continuam pendentes. Nenhum gate ou
autorização de publicação foi aberto.

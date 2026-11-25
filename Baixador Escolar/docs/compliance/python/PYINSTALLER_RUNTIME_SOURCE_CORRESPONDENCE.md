# PyInstaller/hooks — source correspondence do runtime congelado (D4)

**A — TECNICAMENTE COMPLETA PARA REVISÃO JURÍDICA.**
Bundle: `COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW`.
Notice delivery do candidate: **PENDING_FIX**. Revisão jurídica: **PENDING**.
Este documento não autoriza publicação nem substitui parecer jurídico.

## Autoridade e recorte

Baseline inicial: `codex/v0.9.5`, HEAD
`00a0f15e587339117b3e11ca055b94da4ab86ecf`, upstream alinhado, árvore limpa.
APP_VERSION 0.9.5, edição Community. A D4 reutiliza a materialidade identificada
na D3, sem repetir a auditoria inteira nem reabrir blocos fechados.

Candidate: `INTERNAL_ANALYSIS_CANDIDATE`, source commit
`621a72b8c3329dc68abc0c581ec152d6c3bd9e08`. Sua autoridade imutável é
`docs/compliance/build/FROZEN_CANDIDATE_COMPOSITION.json`, SHA-256
`4D3FE5AF64B892B4D23028744922D811886184F611E4955E8D894984725B5DC3`.
Permanece com 1.068 arquivos, 382.736.507 bytes e inventário
`26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857`.
O EXE mantém 4.677.978 bytes e SHA-256
`2A6B49C2B67D596FFC6445D7D7725B219E80E34D5EC2C112ECA814FCE5FE367B`.
Não foi executado PyInstaller, rebuild, emissão ou operação de chave.

## Dois parents exatos

| Parent | Preservação | Tag / commit / tree |
|---|---|---|
| PyInstaller 6.21.0 | `REUSED_EXISTING_SOURCE` | `v6.21.0` / `1cda34561015a90b6e1ae31dc89703799adaf13e` / `b1e4e629352ba8710e0ffb8449e1b959877005c5` |
| pyinstaller-hooks-contrib 2026.6 | `PRESERVED_NEW` | `v2026.6` / `791432e2a150b2282f8048df71c9ec3665aabb48` / `518f9bd4216346a782984b741a91081a4a3cc2fa` |

Wheels já preservadas, não baixadas nem instaladas na D4:

- `pyinstaller-6.21.0-py3-none-win_amd64.whl`, 1.397.487 bytes, SHA-256
  `7FAE06C494CE0EBFE6BD3055C0E409DEF884F63AF2E3705D06BD431AD9237FC7`;
- `pyinstaller_hooks_contrib-2026.6-py3-none-any.whl`, 457.159 bytes, SHA-256
  `FD13B8AC126B35361175EDACD41A0D97080B75DD5F4B594ECEFEFFF969509DD3`.

O archive PyInstaller já existente em
`compliance_artifacts/yt-dlp/2026.07.04/sources/lot-1/pyinstaller-6.21.0.tar.gz`
foi reutilizado sem alteração/redownload: 3.518.947 bytes, SHA-256
`190A36D44D2F024168F94DE11C0CDD37DFC37997F7F2D07CD16E2649551D2529`.
Sua origem é a preservação oficial yt-dlp/Pyinstaller-Builds,
release `2026.06.20.202648`. A evidência da closure original foi vinculada em
`metadata/reused-authority.json` com o hash da autoridade original.

Esse archive **não é byte-identical ao sdist PyPI** de mesmo nome, cuja
identidade oficial é 4.061.519 bytes e SHA-256
`BB9FAB705983E393A2D1CAC77D6972513057AD800215FD861DC15FF5272E98FD`.
O sdist PyPI PyInstaller não foi adquirido. A correspondência é estabelecida
pelo archive preservado, commit/tree e comparação de conteúdo upstream.

Única nova aquisição de source: sdist oficial
`pyinstaller_hooks_contrib-2026.6.tar.gz`, 173.354 bytes, SHA-256
`BEF5002C32F4F50BD55B005DA12CFF64ECA8783E7EAF86A06A62410164BAB725`.
Origem exata em `pypi_sdist_identities` no manifesto; arquivo preservado em
`build-compliance-pyinstaller-runtime/inputs/`, ignorado pelo Git.
Somente metadados textuais oficiais adicionais foram adquiridos.

Tag/commit/tree/PyPI JSON foram preservados. O manifesto registra comparação
de 1.417 arquivos PyInstaller e 722 hooks-contrib com Git blobs das árvores
oficiais (LF para texto, bytes para recursos). O `setup.cfg` do sdist contrib
é uma reserialização ConfigParser com `[egg_info]` gerado: foi comparado
semanticamente com o original upstream, preservado e explicitamente
identificado como metadado gerado, não como diferença de source runtime.

## Materialidade e licenças

| Material distribuído | Evidência / cobertura | Estado |
|---|---|---|
| `runw.exe` Windows GUI / releasew / x64 | Fontes `bootloader/src`, headers, wscript e zlib do parent | `RESOLVED` |
| `pyimod01_archive`, `pyimod02_importers`, `pyimod03_ctypes`, `pyimod04_pywin32`, `pyiboot01_bootstrap` | Cinco sources `PyInstaller/loader` comparados com CArchive | `RESOLVED` |
| `pyi_rth_inspect`, `pyi_rth__tkinter` | `PyInstaller/hooks/rthooks`, headers e relação Apache-2.0 preservados | `RESOLVED` |
| `pyi_rth_cryptography_openssl` | `_pyinstaller_hooks_contrib/rthooks`, Apache-2.0 | `RESOLVED` |
| zlib 1.3.2 | `bootloader/zlib`, LICENSE, tabelas `crc32.h`/`inffixed.h` e fontes geradoras | `COVERED_BY_PARENT` |
| `icon-windowed.ico` | `PyInstaller/bootloader/images`, recurso exato do parent | `COVERED_BY_PARENT` |

O bootloader original da wheel tem 280.576 bytes e SHA-256
`184E0D1ADE1E772B35531867C4B02215D81CA3DF62CAF202EE27AE3BE94AEE60`.
Sua reprodução exata bit a bit permanece `SEPARATE_PENDING_REVIEW`.
Toolchain/CRT/SDK não foram adquiridos. CRT estático e Microsoft runtime ficam
em `SEPARATE_P3_REVIEW`, sem convertê-los em novo source gap open-source.

O source do hook cryptography tem SHA-256
`8E7CC4924D4C673164F4C7F77C62AF6AB822D76EC94DA13641D4AB1026E20F1E`
e header `Copyright (c) 2024, PyInstaller Development Team`. O consumer é
o CArchive de EduDownloader.exe. Compilação apenas em memória, com flags
isolados do validador, confirmou igualdade dos oito code objects materiais
com o CArchive. Nenhum desses módulos foi executado.

Analysis hooks/stdhooks contrib são `BUILD_ONLY_NOT_DISTRIBUTED`; stdhooks
têm GPL-2.0-or-later, enquanto o runtime hook distribuído tem Apache-2.0.
O `LICENSE` integral mantém essa distinção, sem expressão global simplificada.
Altgraph, pefile e pywin32-ctypes continuam somente build. O hook
`pyi_rth_edudownloader_tk` é código próprio e não entra no source bundle.

O ícone tem 60.690 bytes e SHA-256
`168DB1B8A7C62FA2AB92C1210185D145923F31C1BE23FDED42D9420F48B98392`.
Sua associação ao parent não é interpretação conclusiva da exceção jurídica.
Não foi identificado miniz/uthash material neste recorte D3/D4.

Textos upstream completos, sem alteração de bytes:

| Texto preservado no repositório | SHA-256 |
|---|---|
| `Licencas/PyInstaller/COPYING.txt` | `DCF75FDB959DB1E3B41C0F8505069D2ECE781B5EC6B3D0A4D30975CFC6580245` |
| `Licencas/PyInstaller/ZLIB_LICENSE.txt` | `E32FF4E00D9D94930537635291DA39E7E612703334BF6FDE8C7F1686FE8A45A2` |
| `Licencas/pyinstaller-hooks-contrib/LICENSE` | `91D0BAAFF00773038E72C0A1FC9D5D2D38706B7A2B9C04F34296608F931B9CD0` |

O COPYING separa project/general terms GPL-2.0-or-later, Bootloader Exception
e Run-time Hooks Apache-2.0. A evidência da exceção em PyInstaller 6.21.0 usa
COPYING normalizado LF, de `Bootloader Exception` (inclusivo, offset 466)
até `Run-time Hooks` (exclusivo, offset 1214): 748 bytes, SHA-256
`711C0CD077A0985A5C35A1464D604FBAC42EAACB8B4E42C17C4896C521514D56`.
Essas identidades não constituem parecer jurídico.

## Projeção source-only e bundle

Os archives originais permanecem intactos. O bundle contém uma projeção
source-only, não os archives brutos: o archive reutilizado contém oito
bootloaders pré-compilados e treze fixtures upstream binárias/de chave/archive
sem materialidade runtime. Esses 21 itens são excluídos com path/hash/motivo
inventariados; nenhum source material distribuído é removido. Três symlinks
internos são materializados como bytes dos respectivos alvos dentro do parent,
sem criar links no filesystem. Fontes, recursos e metadados restantes são
verificados contra os dois archives e o inventário externo pinado.

Não contém EXEs, DLLs, wheels, wheelhouse, candidate, código proprietário ou
material operacional de ativação. Fixtures textuais upstream são fontes de
terceiros, não executadas, e não representam dados pessoais do operador.
O `.gitattributes` conserva bytes/whitespace dos textos jurídicos upstream;
não se reformata uma licença para satisfazer checks de estilo.

Manifesto rastreado: `PYINSTALLER_RUNTIME_SOURCE_PROVENANCE.json`, SHA-256
`2AA4AE06C1E13014DC610533C9AD459A385811EE07282E7AB3DABC0A9660B1AF`.
Staging: `build-compliance-pyinstaller-runtime/staging/`:

- 2.165 arquivos, 9.513.701 bytes;
- inventário SHA-256
  `93D6E8484A20E9C48851E0E602464CE6CF402CEE461438D6D5134D264F8D8D71`.

Bundle em `build-compliance-pyinstaller-runtime/bundles/`:
`EduDownloader-ThirdParty-Source-PyInstaller-6.21.0-COMPLETE.zip`:

- 2.167 entradas; 10.934.301 bytes descomprimidos;
- 4.751.866 bytes de ZIP;
- SHA-256 `AEAA60336F821F1A6DC710D2DBBA8FC122AD05BDA33FE016B3B020FCBD3CD05D`;
- inventário integral do ZIP
  `7455EA5ABAA5421F084F740BFDD8B631789ECF7CC7561BCF9ADAE36AF9846E01`.

As duas entradas adicionais são provenance e inventário. O inventário interno
não se inclui a si próprio; o hash acima considera todas as entradas finais.
Duas montagens tiveram os mesmos bytes, count, size, SHA-256 e inventory SHA.
O ZIP não é release, artefato executável ou pacote Community.

Validador: `pyinstaller_runtime_source_bundle.py`. Rejeita ausência/adulteração
de archives, manifesto, sources, licenças, recursos, commit/tree e inventários;
classificação build-only indevida; source gap com status completo; executáveis,
paths inseguros e qualquer arquivo extra, inclusive código próprio. A autoridade
esperada é externa ao ZIP: reescrever seu inventário não o torna aceitável.

Comandos offline (com o Python 3.14.6 do ambiente já validado):

```text
python -B pyinstaller_runtime_source_bundle.py verify-staging
python -B pyinstaller_runtime_source_bundle.py verify-frozen
python -B pyinstaller_runtime_source_bundle.py assemble
python -B pyinstaller_runtime_source_bundle.py verify-bundle
python -B pyinstaller_runtime_source_bundle.py assemble --bundle build-compliance-pyinstaller-runtime/bundles/EduDownloader-ThirdParty-Source-PyInstaller-6.21.0-REPEAT.zip
```

`assemble` recusa sobrescrever outputs existentes. `verify-bundle` valida o
ZIP sem depender do staging, usando o manifesto rastreado como autoridade.
O diretório local ignorado de compliance é excluído somente da varredura de
código próprio; não há relaxamento da auditoria do cliente ou do source bundle.

## Validações D4

- 18 regressões novas do validador/bundle e uma regressão da exclusão do
  staging upstream da varredura de código próprio;
- lote direcionado source/bundle/provenance/frozen/distribution/package/
  licensing/wheels: 164 testes, 1 skip, OK;
- suíte completa: 1.028 testes, 4 skips, OK;
- licenciamento da fonte: 75 arquivos, PASS;
- ambiente corresponde exatamente ao lock; `pip check` sem dependências
  quebradas; lock hash-pinned e Wheel Integrity classe A, PASS;
- Ruff check e format check: PASS, 107 arquivos formatados;
- compileall somente do escopo rastreado e dos dois novos arquivos Python:
  107 arquivos, PASS;
- JSON canônico/pinado, hashes de licenças, URLs dos avisos, staging,
  CArchive/source, bundle standalone e segunda montagem determinística: PASS;
- integridade do candidate e `git diff --check`: PASS.

Nenhuma instalação, build, execução das fontes upstream preservadas ou aquisição
de toolchain foi necessária. As fontes preservadas não foram usadas como suíte
executável; os testes D4 são fixtures offline sintéticas.

## Fechamento e pendências separadas

Dois logical parents cobertos; um reuso; uma nova aquisição; zero transitive
parents; zero source pending, blocked ou unknown no recorte PyInstaller/hooks.
Isso permite **A**, não aprovação jurídica. Os novos textos e a correção de
`THIRD_PARTY_NOTICES.txt` preparam build futuro; o candidate antigo continua
com **PENDING_FIX** em notice delivery. Não se cria NOTICE inexistente upstream.

Permanecem cffi/cryptography (`NEXT_SEPARATE_GAP`), Microsoft P3, Deno,
CustomTkinter, notice delivery (inclusive Tcl), revisão jurídica, política de
entrega e reprodução bit a bit. CPython/Tcl-Tk, yt-dlp, FFmpeg/BtbN e Wheel
Integrity continuam A; Pillow e pypdfium2/PDFium continuam RESOLVED.
Gyan 8.1.2 permanece ativo; BtbN não foi promovido.

APP_VERSION 0.9.5; `product_edition=community`;
`activation_required_for_current_edition=false`;
`default_trust_store_key_count=1`; `operational_public_key_configured=true`;
`production_crypto_configured=true`; `operational_private_key_configured=false`;
`activation_operational=true`; `production_ready=false`;
`public_release_allowed=false`. Nenhum gate foi aberto.

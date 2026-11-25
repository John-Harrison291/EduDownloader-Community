# Consolidação de notices do próximo candidato — D14A

Atualização da composição corrente 1.4.0: esta tabela D14A registra o estado
histórico de sua preparação. O inventário canônico atual substitui Gyan pelo
par BtbN LGPLv3+ e inclui `FFMPEG_BTBN_LICENSE.txt`,
`FFMPEG_BTBN_NOTICE.txt` e `THIRD_PARTY_SOURCE_INFORMATION.txt`. O bundle de
fonte está preservado, mas ainda não foi entregue publicamente. Nenhum estado
do R2/RC1 histórico foi reescrito.

Registro técnico de 2026-09-10. Esta fase prepara no source tree a árvore de
licenças/notices que um futuro candidato R3 poderá entregar. Ela não modifica o
candidato histórico nem o R2, não executa PyInstaller e não autoriza produção,
publicação ou redistribuição.

## Separação de escopos

O inventário canônico `NOTICE_DELIVERY_INVENTORY.json` é a allowlist de
delivery. Somente os caminhos em `delivery_artifacts` pertencem ao conjunto de
notices destinado ao usuário. Arquivos enumerados em
`source_only_license_artifacts` permanecem no source tree por compatibilidade e
evidência, mas não devem ser copiados pelo futuro R3. Bundles de source,
provenance interna, wheelhouse, staging, P2 e P3 permanecem fora da entrega.

O R2 continua fisicamente com seus estados históricos: PyInstaller
`DELIVERED`; Deno e CustomTkinter `PARTIAL`; Microsoft, CPython/Tcl-Tk e
cffi/cryptography `PENDING_FIX`; outros `PARTIAL`. A preparação no source tree
não retroage esses estados.

## Resultado por família

| Família | Identidade do notice | Conjunto do próximo candidato |
|---|---|---|
| Microsoft VC Runtime 14.51.36247.0 | resolvida tecnicamente | `PREPARED_NOT_DELIVERED`; P3 pendente |
| CPython 3.14.6 | resolvida | `PREPARED_NOT_DELIVERED` |
| Tcl 8.6.15.0 | resolvida | `PREPARED_NOT_DELIVERED` |
| Tk 8.6.15.0 | resolvida | `PREPARED_NOT_DELIVERED` |
| PyInstaller 6.21.0/hooks 2026.6 | resolvida | entregue no R2 e retida |
| cffi 2.1.1/cryptography 49.0.0/OpenSSL 4.0.1/Rust 1.96.0 | resolvida | `PREPARED_NOT_DELIVERED` |
| Deno 2.9.5 | resolvida com 15 gaps de texto upstream | `PARTIAL_PREPARED_NOT_DELIVERED` |
| CustomTkinter 5.2.2 | parcial | `PARTIAL_PREPARED_NOT_DELIVERED` |
| Pillow 12.3.0 | resolvida | preparada e presente no R2 |
| pypdfium2/PDFium 5.12.1 | resolvida | preparada e presente no R2 |
| yt-dlp 2026.07.04 | resolvida | preparada e presente no R2 |
| FFmpeg/FFprobe Gyan 8.1.2 | resolvida para a baseline ativa | `PREPARED_NOT_DELIVERED` |
| darkdetect 0.8.0/packaging 26.3/pypdf 6.15.0 | resolvida | `PREPARED_NOT_DELIVERED` |

O conjunto global é `PARTIAL`: no Deno, 13 textos upstream permanecem
`ABSENT` e dois `PARTIAL`; as referências canônicas SPDX são complementares e
não são apresentadas como texto upstream. No CustomTkinter,
`ROBOTO_PRODUCER_PENDING` permanece explícito. BtbN continua
`CANDIDATE_NOT_PROMOTED`; Gyan é a única baseline FFmpeg ativa.

## Determinismo e validação

`notice_delivery.py` gera os consolidados a partir da evidence local preservada
e valida offline a composição R2 contra o inventário. O validador rejeita falta
ou hash divergente, versão/runtime incompatível, componente material sem
cobertura, Gyan/BtbN confundidos, perda da distinção Deno upstream/SPDX,
pendência Roboto apagada, artefato não classificado e marcadores de material
privado. JSON gerado usa chaves ordenadas, UTF-8 e LF; textos gerados não incluem
timestamp corrente, usuário, host ou path local absoluto.

O futuro D14B/R3 deverá copiar a allowlist do inventário, e não recursivamente
todo o diretório `Licencas`. A integração física e a nova validação do candidato
pertencem àquela fase, não à D14A.

Reprodutibilidade integral continua `P2_SEPARATE_PENDING`. Revisão jurídica
continua `P3_REQUIRED`, inclusive `P3_PENDING_REVIEW` para Microsoft. O status
parcial não abre nenhum gate.

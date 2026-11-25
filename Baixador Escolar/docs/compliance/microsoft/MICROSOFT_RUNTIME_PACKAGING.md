# Microsoft runtime packaging — D13A

## Escopo

A D13A prepara o próximo candidato controlado sem reconstruir ou modificar o
`INTERNAL_ANALYSIS_CANDIDATE` histórico. A baseline técnica provisória passa a
ser `WINDOWS_10_OR_NEWER_X64`. Não há suporte declarado a versões anteriores do
Windows nesta política.

O candidato histórico permanece com 1068 arquivos, 382736507 bytes e inventory
SHA-256
`26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857`.

## Causa corrigida

O pipeline executava o PyInstaller herdando todo o `PATH` do operador. Nesse
ambiente, um diretório auxiliar `libheif/bin`, fora do projeto e do ambiente de
build isolado, aparecia antes dos diretórios do Windows. A resolução de
dependências do PyInstaller usou esse caminho e coletou 42 API Sets e
`ucrtbase.dll` 10.0.26100.4654. A coleta não era declarada no spec e variava
conforme software externo instalado.

O wrapper passa a substituir, e não complementar, o `PATH` herdado. As roots
permitidas são: runtime Microsoft pinado, projeto/área isolada de build,
instalação CPython explicitamente identificada e diretórios de sistema do
Windows. DLL externa a essas roots falha; runtime Microsoft vindo do CPython ou
de qualquer origem diferente da autoridade pinada também falha.

## Política futura de UCRT e API Sets

Para Windows 10/11 x64:

- 29 API Set Core: `SYSTEM_RUNTIME_NOT_TO_BE_BUNDLED`;
- 13 API Set CRT: `SYSTEM_RUNTIME_NOT_TO_BE_BUNDLED`;
- `ucrtbase.dll`: `SYSTEM_RUNTIME_NOT_TO_BE_BUNDLED`.

Os 43 arquivos não foram removidos do candidato histórico. A política só vale
para o próximo candidato. As tabelas de importação já auditadas na D12 não
mostram exceção que exija o UCRT application-local nessa baseline.

## Autoridade VC Runtime

Foi adquirido do permalink oficial Microsoft somente o pacote x64 v14:

- produto: Microsoft Visual C++ v14 Redistributable (x64) 14.51.36247;
- pacote: `vc_redist.x64.exe`;
- tamanho: 18731856 bytes;
- SHA-256:
  `843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C`;
- publisher: Microsoft Corporation;
- Authenticode: `VALID`.

O layout Burn identificou os pacotes x64 Minimum e Additional 14.51.36247 já
presentes no cache oficial do instalador. A inspeção dos CABs mostrou 26 DLLs.
As import tables do produto requerem somente:

| Arquivo | Versão | Bytes | SHA-256 |
|---|---|---:|---|
| `VCRUNTIME140.dll` | 14.51.36247.0 | 178616 | `D1F4225DF2CD877DBF130D5668A021DCE3F94118455FF5EC952061C30AFC9CE7` |
| `VCRUNTIME140_1.dll` | 14.51.36247.0 | 50112 | `A7146C08F89FE5B04541AB507CDB59FF7B44534D4BA3C668A426C6450A03434E` |

`msvcp*`, `concrt*`, `vcomp*`, `MFC`, `vcamp` e `vccorlib` não são selecionados.
As duas DLLs escolhidas são x64, assinadas pelo Microsoft Windows Software
Compatibility Publisher e estão pinadas por tamanho e hash.

## Guards do próximo build

O pipeline futuro falha se:

- o manifest ou a raiz local da autoridade estiver ausente;
- versão inferior a 14.51 for selecionada;
- arquitetura, tamanho, hash, versão, assinatura ou publisher divergirem;
- API Set ou UCRT application-local reaparecer;
- `libheif/bin` ou outra root alheia fornecer DLL;
- VCRuntime vier incidentalmente da instalação CPython;
- surgir outra família Microsoft (`msvcp`, `concrt`, MFC etc.);
- houver duplicata ou ausência de um VCRuntime requerido;
- o TOC do PyInstaller ou o candidato produzido divergir do pin.

O próximo build usará explicitamente os dois arquivos descritos pelo manifest.
A D13A não executa PyInstaller; a prova no candidato fica reservada à D13B.

## Limites

- `BUILD_REPRODUCIBILITY = P2_SEPARATE_PENDING`;
- `P3 = P3_PENDING_REVIEW`;
- `PYINSTALLER_STATIC_MICROSOFT_RUNTIME = CONFIRMED_POLICY`;
- `DENO_STATIC_MICROSOFT_RUNTIME = PARTIAL`;
- PDFium/static permanece `PARTIAL_OR_UNKNOWN`.

As referências oficiais e a identidade técnica não representam aprovação
jurídica ou autorização de release comercial/pública. A entrega do notice
preparado depende de P3.

# D8 — CustomTkinter 5.2.2: preservação e reconciliação

## Resultado e fronteira

Registro de 2026-09-08, iniciado em `b230fdb3d80f6008b8ccfe499ee87b40af91ec51`,
branch `codex/v0.9.5`, upstream alinhado 0/0 e árvore limpa.
**SOURCE CORRESPONDENCE: PARTIAL. NÃO PUBLICAR.**

O parent CustomTkinter e o parent Digsby estão preservados e verificados.
O produtor exato dos dois Roboto continua `PROVENANCE_PENDING`. Não há
staging nem bundle COMPLETE: não se infere corresponding source apenas pela
versão da fonte ou por arquivos semelhantes. Nenhum archive Roboto foi adquirido.

Esta D8 não executa PyInstaller, não reconstrói nem modifica o candidato e não
altera notices dentro dele. A mudança de empacotamento afeta somente builds futuros.
Não há conclusão jurídica nem abertura de gates.

Autoridade reproduzível:
`CUSTOMTKINTER_RUNTIME_SOURCE_PROVENANCE.json`, com hashes, inventários,
43 registros de módulos, nove dados, aquisições oficiais e revisões públicas.
O verificador `customtkinter_runtime_source.py` trabalha offline e não executa
código preservado. Compilar para comparação de code objects não executa módulos.
O manifesto canônico tem bytes preservados por `.gitattributes`, como os
manifestos D4/D6, evitando conversão CRLF que invalidaria seu SHA-256.

## Autoridade congelada e wheel

Preservado o `INTERNAL_ANALYSIS_CANDIDATE` do source commit
`621a72b8c3329dc68abc0c581ec152d6c3bd9e08`:

- 1.068 arquivos, 382.736.507 bytes;
- inventory SHA-256 `26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857`;
- wheel `customtkinter-5.2.2-py3-none-any.whl`, 296.062 bytes;
- wheel SHA-256 `14AD3E7CD3CB3B9EB642B9D4E8711AE80D3F79FB82545AD11258EEFFB2E6B37C`.

A wheel aprovada foi reutilizada; não houve nova aquisição de wheel.
43/43 módulos PYZ correspondem aos code objects das fontes da wheel, usando
o filename do code object e optimize=0; 9/9 package data são byte-idênticos.

## CustomTkinter: sdist, tag e cobertura

| Identidade | Evidência |
|---|---|
| Sdist | `customtkinter-5.2.2.tar.gz`, 261.999 bytes |
| SHA-256 | `FD8DB3BAFA961C982EE6030DBA80B4C2E25858630756B513986DB19113D8D207` |
| Tag | `v5.2.2` |
| Tag object | `e2c410af89401cedb5f6a49616794668e5a9ca2c` |
| Commit | `a2f0ecd144c6fee931fc06c823a14d9ae0d01bdb` |
| Tree | `acaba786f081b183465f61772b18cef182233643` |
| Inventário sdist | 62 arquivos, 890.737 bytes |
| Inventory SHA-256 | `9DBF086270A2C4DE68181608F1D063AEDADA1EEB9BA2537C2BABF5DAA29BE693` |

O hash confere com PyPI. Os arquivos comuns ao sdist e tree, exceto o
setup.cfg reformatado descrito abaixo, conferem por Git blob SHA-1;
todos os 52 membros do pacote na wheel conferem com o sdist.
Os 43 Python sources, três themes, duas Roboto, shapes font e ícone estão
cobertos fisicamente pelo parent CustomTkinter. Isso não resolve o produtor
anterior das fontes Roboto, que é uma questão separada.
LICENSE e MANIFEST.in também são byte-idênticos ao tree. O setup.cfg do tag
foi preservado separadamente: o sdist reformatou whitespace/indentação e
acrescentou `[egg_info]` com tag_build vazio e tag_date=0. A equivalência de
todos os campos originais, incluindo CC0 e classifier MIT, é validada
semanticamente; qualquer outra diferença falha. Essa transformação é
GENERATED_PACKAGING_METADATA, não SOURCE_MATCH byte a byte.
Todos os 62 membros do sdist e 57 da wheel têm classificação explícita;
metadados de empacotamento gerados são inventariados separadamente.

### Correção factual de D7: `.DS_Store`

A aquisição física revelou os dois arquivos também no sdist:
`customtkinter/assets/.DS_Store` e `customtkinter/assets/icons/.DS_Store`.
Continuam ausentes do tag. Portanto, a expectativa D7
`WHEEL_ONLY_NON_RUNTIME` não descreve exatamente o escopo observado.
A classificação corrente é `NON_RUNTIME_PACKAGING_RESIDUE`, presente em
sdist + wheel, sem função runtime e **sem constituir source gap**.

`EduDownloader.spec` exclui esse componente de path sem diferenciar caixa,
inclusive paths Windows. Os validadores de distribuição e de candidato
rejeitam sua presença nos próximos builds. Os dois arquivos históricos
permanecem intactos no candidato atual; uma reprovação deles pela política
nova é esperada e não autoriza reescrever a evidência pristine.

## LICENSE MIT e metadata CC0

As evidências permanecem separadas, sem normalização dos termos upstream:

- LICENSE MIT oficial, LF: `C973B8600E620159CB0473EB9B08783143E0D9ED5333F350FC933368D94D9E0D`;
- LICENSE entregue no candidato, CRLF: `4C58162E0686C537AFBB0A40577B5F96467EEBE518F03FC2152707DA2FBE4F7A`;
- igualdade integral após normalização exclusiva de line endings;
- setup.cfg e wheel metadata: `Creative Commons Zero v1.0 Universal`;
- classifier e README badge: MIT; metadata PyPI preservada;
- commit `4d52febd993110119cb50cbd2d4b61188798ca61`: alteração do LICENSE
  para MIT, sem atualizar o campo CC0 de setup.cfg.

Classificação técnica: `METADATA_DISCREPANCY_EXPLAINED`.
A precedência jurídica dos sinais continua P3, não decidida nesta tarefa.

## Shapes font e ícone

| Material | SHA-256 | Classificação |
|---|---|---|
| CustomTkinter_shapes_font.otf | `FAD67E2B060C318B6C8646D087FBD3ADD938B6676243F14B0C52623179641274` | COVERED_BY_CUSTOMTKINTER_PARENT |
| CustomTkinter_icon_Windows.ico | `1234C017C871EB2E20D36F668F93E066CDCB93DB464D5CEF9D7A5BF83506D28C` | COVERED_BY_CUSTOMTKINTER_PARENT |

Byte identity sdist/tag/wheel/candidato conferida. A história preservada aponta
para `15558b4d0f093b346aeaf207939da71e2dd6db69` (fonte) e
`f3710de173c6ba73afc651923e536e103054ae2d` (ícone), no upstream CustomTkinter.
A name table da shapes font está inventariada: não fornece termos específicos
suficientes para encerrar a revisão. Ambos permanecem `SPECIFIC_TERMS: P3_PENDING`.
Nenhum parent separado foi inventado.

## Roboto: identidade resolvida, produtor não resolvido

| Arquivo | Bytes | SHA-256 |
|---|---:|---|
| Roboto-Regular.ttf | 168.260 | `319CFF6E7A31F0F2A41C475DCA42890AA5D19FE16017E2290F8C1D4E14F76481` |
| Roboto-Medium.ttf | 168.644 | `4AC8E03606FFA4C37F61A6510A2080F1F37A7054F4726C214887D3B23F72E369` |

As name tables preservadas identificam Version 2.137/2017, copyright Google,
Google/Christian Robertson e Apache-2.0. Foi preservado o LICENSE Apache-2.0
da linha histórica Google Fonts, commit
`724bf98e9f5cb98a1d3d5044f45a2e286b817401`, 11.358 bytes,
SHA-256 `CFC7749B96F63BD31C3C42B5C471BF756814053E847C10F3EB003417BC523D30`.
Essa evidência é compatível com as strings embutidas, mas não prova o archive
produtor das duas fontes. Não se usou a licença de uma linha recente diferente.

Busca proporcional em metadados oficiais, somada às conclusões D7:

- google/fonts 2.137: Regular 171.676 e Medium 172.064 bytes; Git blobs diferentes;
- googlefonts/roboto-2 2.138 e comparação histórica D7 2.136: variantes hinted
  diferentes, não aceitas como equivalentes;
- googlefonts/robototester, commit `7c4152a2fea8fe850b513cfd1a4fee3052d578e4`:
  mesmos blobs Google Fonts de 171.676/172.064 bytes, também diferentes.

Não se baixou archive Roboto aleatório, não se substituiu TTF e não se tratou
versão igual como byte provenance. Regular e Medium: bytes `RESOLVED`,
producing parent `PARTIAL / PROVENANCE_PENDING`. Próximo passo específico:
localizar uma identidade oficial que explique precisamente esses dois blobs.

## Digsby e Stack Overflow

Digsby foi preservado como archive integral, não executado nem instalado:

- repository `ifwe/digsby`;
- commit `f5fe00244744aa131e07f09348d10563f3d8fa99`;
- tree `fd48fba90bb227017ac2da9786d59f9b9130aaf0`;
- archive: 57.366.382 bytes, SHA-256 `5CE4C8E45D0BE1000C076C8A66B654175DC0EEC8D933BAB63C933C8AF6FD87D4`;
- inventário: 4.949 arquivos/blobs, 92.982.787 bytes;
- inventory SHA-256 `ABE72F1E7421C874470E5B9B878299BF7E4FC3100C14837C6A23E5A0D53A53F3`;
- todos os membros conferidos com os blobs do tree; links são texto, nunca seguidos;
- `digsby/src/gui/native/win/winfonts.py`, 3.450 bytes,
  SHA-256 `3F20A0E42E8DD2F779AA1DD800925909DEF1E7A04B8FF525040AE2E65674CA90`;
- Digsby License v1, integral, 2.420 bytes,
  SHA-256 `40DDC25914FCC63289871553C5D478CCC7CCC196987F69F5BDE4A8EC399FC374`.

O archive integral é preservação local upstream, não staging source-only nem
pacote do cliente; membros binários do projeto upstream não serão automaticamente
incluídos em um futuro bundle.

A resposta [30631309, de Felipe](https://stackoverflow.com/questions/11993290/truly-custom-font-in-tkinter/30631309)
foi criada em timestamp UTC `1433367854`. Foram preservados metadados/revisões
da API, não uma cópia da página inteira. Todas as quatro revisões referenciam
Digsby. Seus GUIDs, autores, timestamps e hashes do trecho de código estão no manifesto.

As revisões 1, 2 e 3 têm o mesmo trecho; a 4 remove whitespace. A revisão 3
estava disponível quando FontManager foi criado em 2022-05-17, commit
`afe44f4ff772030211d0659972aaea559776e53d`. A história posterior contém dois
renames de path preservados. Isso não determina qual revisão foi copiada:
`REVISION_IDENTITY_PARTIAL`, sem atribuição inventada.

| Adaptação técnica | Categoria |
|---|---|
| ctypes buffers, AddFontResourceExA/W e flags private/enumerable | UNCHANGED |
| nomes camelCase → snake_case | RENAMED |
| str/unicode → bytes/str | PYTHON3_ADAPTATION |
| função de módulo → classmethod de FontManager | STRUCTURAL_CHANGE |
| bool(count) → bool(min(count, 1)) na versão final; docstrings/diagnóstico | OTHER |

O vínculo Digsby → resposta → CustomTkinter está `RESOLVED` tecnicamente;
Stack Overflow é intermediário de provenance/notice, não um quarto parent.
A API rotula revisões 1/2 CC BY-SA 3.0 e 3/4 CC BY-SA 4.0. A
[política oficial](https://stackoverflow.com/help/licensing) distingue as datas
das contribuições. Aplicabilidade da licença e obrigações Digsby permanecem P3.
Não se conclui originalidade, compatibilidade ou suficiência jurídica.

## Notice identities e entrega futura

| Identidade preparada | Evidência preservada / pendência |
|---|---|
| CustomTkinter | MIT integral + nota técnica CC0; sem sobrescrever metadata |
| Roboto | Google/Christian Robertson, Apache-2.0 histórico e strings TTF; producer pendente |
| Digsby | copyright/licença integral, identidade do source e resumo das adaptações |
| Stack Overflow | Felipe, URL/answer/revisions, evidência CC BY-SA; revisão copiada não provada |
| Shapes/icon | parent CustomTkinter, termos específicos P3 |

NOTICE IDENTITY: PARTIAL. NOTICE DELIVERY: PENDING_FIX.
A entrega física será feita somente num novo candidato controlado após revisão
das identidades/termos. Nenhum notice do candidato atual foi modificado.

## Contabilidade, validação e próximos limites

Três parents lógicos; dois preservados; duas novas aquisições de source archives.
Arquivos textuais/metadados oficiais adicionais constam individualmente no manifesto.
Uma pendência de source, bloqueando o fechamento: produtor Roboto; dois arquivos
materiais com produtor desconhecido. `source_pending=1` e `source_blocked=1`
descrevem o mesmo parent, não duas lacunas diferentes. A revisão SO indeterminada
é registrada separadamente; não é um terceiro TTF desconhecido.

Staging: não criado (contagem/tamanho/hash não aplicáveis).
Bundle: não criado (entries/tamanho/SHA/inventory/determinismo não aplicáveis).
`verify-staging`, `assemble` e `verify-bundle` devem recusar a closure parcial,
antes de escrever. Não se anuncia teste de determinismo de um bundle inexistente;
testa-se determinismo do inventário e bloqueio explícito da montagem.

Validação offline: testes D8 e distribuição/pipeline; hashes de evidências;
sdist/tree/wheel; code objects/dados/pristine; source licensing; ambiente/lock;
pip check; wheel integrity; suíte completa; Ruff; compileall em arquivos
rastreados; JSON canônico; git diff --check. Nenhum build ou assinatura é executado.

Preservação ignorada pelo Git em `build-compliance-customtkinter/`: dois archives,
evidências oficiais pequenas, ledger de aquisição e inventários derivados.
Não contém source próprio em staging, wheelhouse copiada ou material operacional.
O validador de licenciamento de fonte exclui explicitamente essa área upstream,
como já faz com as áreas D2/D4/D6; o helper rastreado e o código do aplicativo
continuam inspecionados. Um teste rejeita a exclusão de diretórios apenas parecidos
e confirma que violações no source próprio continuam detectadas.

APP_VERSION 0.9.5; ProductEdition community; ativação exigida nesta edição false.
Trust store 1; public key true; production crypto true; private key false;
activation_operational true; production_ready false; public_release_allowed false.
Gyan continua ativo; BtbN CANDIDATE_NOT_PROMOTED.
FFmpeg/BtbN, yt-dlp, CPython/Tcl-Tk, PyInstaller/hooks, cffi/cryptography e Wheel
Integrity não foram reabertos; Pillow/PDFium continuam RESOLVED.
Deno: NEXT_SEPARATE_GAP; Microsoft: P3_PENDING_REVIEW.

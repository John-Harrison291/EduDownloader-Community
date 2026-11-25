# Composição auditada do Pillow

## Wheel do build ativo

- Pillow 13.0.0, CPython 3.14.6 x64, tag cp314-cp314-win_amd64.
- Wheel oficial pillow-13.0.0-cp314-cp314-win_amd64.whl, SHA-256
  F7CBB7A64E7EC664775195E4F81923BC8A93D9451B963F844E59118F63147A7A.
- Publicação autenticada pelo PyPI para python-pillow/Pillow, workflow wheels.yml
  e tag 13.0.0. A licença declarada é MIT-CMU. [Wheel e procedência](https://pypi.org/project/pillow/13.0.0/#pillow-13.0.0-cp314-cp314-win_amd64.whl)
- PILLOW_LICENSE.txt preserva o LICENSE fornecido pela wheel, SHA-256
  988FFE8AB3480B0F4E9A0AB2702BFFD73D9FB6B47198043FB3BA101A62FAC236.
- PILLOW_SBOM.cdx.json preserva o SBOM CycloneDX da mesma wheel, SHA-256
  FE1CA6E3A4F73E7018A3805A75A19377453F342D203712F37387AD6EE853FD44.

WHEEL, METADATA e RECORD identificam o arquivo distribuído e a instalação
auditada. O LICENSE e o SBOM são copiados byte a byte para os avisos.

## Extensões e composição

A wheel contém oito extensões Windows x64 em PIL (_avif, _imaging, _imagingcms,
_imagingft, _imagingmath, _imagingmorph, _imagingtk e _webp). Todas indicam
linker MSVC 14.51 nas informações PE. O requisito de runtime Microsoft
continua no modelo de pré-requisito externo do build.

FreeType está ativo no ambiente com a wheel verificada. Este software
utiliza FreeType por meio do Pillow e do PDFium. A presença material de cada
extensão nos portáteis pode ser conferida pelos bytes nativos empacotados
e pelo inventário do build de cada edição.

Um componente listado no SBOM não equivale automaticamente a uma biblioteca
materialmente distribuída. A wheel auditada não possui suporte libimagequant
habilitado. A API de features do Pillow confirmou a ausência de libimagequant,
Raqm e XCB. O validador do ambiente
continua rejeitando uma feature esperada como ausente quando ativada,
desconhecida ou não verificável.

Este registro se aplica ao build atual. Inventários de candidatos históricos
continuam documentando as versões e os bytes efetivamente entregues à época.

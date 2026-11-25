# Compilação no Windows x64

Use CPython 3.14.6 x64 com Tcl/Tk. Execute os comandos de Python a partir de `Baixador Escolar`. O [guia do pip](https://pip.pypa.io/en/stable/topics/secure-installs/) explica a validação de hashes das dependências. O PyInstaller deve ser executado no Windows para gerar o pacote Windows.

## Insumos separados

A partir de `Baixador Escolar`, escolha uma pasta de trabalho fora do repositório. O exemplo usa uma pasta nova ao lado dele.

```powershell
$insumos = New-Item -ItemType Directory -Path '..\..\edudownloader-insumos'
$wheels = Join-Path $insumos.FullName 'build-compliance-wheels\wheelhouse'
New-Item -ItemType Directory -Path $wheels
py -3.14 -m pip download --require-hashes --only-binary=:all: -r requirements-build-hashes.lock -d $wheels
```

Coloque os quatro executáveis abaixo diretamente em `$insumos`. Preserve as versões exatas dos pares compatíveis. O par histórico FFmpeg/FFprobe exige uma cópia arquivada até haver uma fonte pública verificável ou a homologação de outro par. As receitas e revisões registradas no manifesto permitem investigar a reconstrução. A equivalência byte a byte de uma reconstrução ainda não foi demonstrada.

A reprodução integral da compilação por terceiros permanece temporariamente pendente porque o ZIP original não está mais disponível no canal do fornecedor. O instalador e a versão portátil da Community 3.0.0 já incluem o par homologado e funcionam sem esse download. As fontes correspondentes dos executáveis redistribuídos seguem as licenças e os avisos dos respectivos componentes.

| Arquivo | Origem |
| --- | --- |
| `yt-dlp.exe` | [yt-dlp 2026.08.19](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19) |
| `deno.exe` | [Deno 2.9.5](https://github.com/denoland/deno/releases/tag/v2.9.5), arquivo `deno-x86_64-pc-windows-msvc.zip` |
| `ffmpeg.exe` e `ffprobe.exe` | BtbN `autobuild-2026-08-25-13-06`, variante `win64-lgpl-8.1` indicada em `docs/compliance/ffmpeg/BTBN_CANDIDATE_PROVENANCE.json`. O fornecedor retirou o download diário. Use uma cópia de procedência verificável que corresponda aos hashes fixados. |

```powershell
py -3.14 validate_frozen_candidate.py validate-externals --root $insumos.FullName
py -3.14 validate_python_wheels.py --lock requirements-build.lock --hashed-lock requirements-build-hashes.lock `
  --manifest docs/compliance/python/PYTHON_WHEEL_PROVENANCE.json --wheelhouse $wheels
```

Prepare o OCR em uma pasta nova. O script baixa somente os insumos discriminados no manifesto `ocr_community_sources.json`, confere tamanho e SHA-256 e compara a compilação com o hash do motor homologado. O empacotamento confirma também a presença e os hashes dos modelos e avisos de licença.

```powershell
py -3.14 prepare_ocr_component.py --download `
  --cache (Join-Path $insumos.FullName 'ocr-downloads') `
  --workspace (Join-Path $insumos.FullName 'ocr-build') `
  --destination (Join-Path $insumos.FullName 'Componentes\OCR-Community')
```

Para executar o aplicativo a partir do código com esses componentes, coloque as cópias verificadas dos quatro executáveis em `Baixador Escolar` e o OCR em `Baixador Escolar/Componentes/OCR-Community`. A instalação do LibreOffice é separada e usa o catálogo e os perfis verificados na pasta `installer`.

## Validar e compilar

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python run_test_suite.py
& $python -m ruff check .
& $python -m ruff format --check .
& $python -m compileall -q -x '[/\\](\.venv|build-[^/\\]+|Componentes)[/\\]' .
& $python -m pip check
& $python notice_delivery.py validate
& $python build_editions.py community --expected-version 3.0.0 --inputs $insumos.FullName
```

O último comando imprime o caminho do portátil verificado, de onde também são geradas a evidência de composição e a cópia ZIP local. Mantenha o caminho para a etapa do instalador. Use o `ISCC.exe` do [Inno Setup](https://jrsoftware.org/isinfo.php) 7.1.1, obtido no canal do fornecedor:

```powershell
& $python build_community_installer.py --iscc $iscc --portable $portatil --output $saida
```

Defina `$iscc` com o caminho do compilador, `$portatil` com o diretório impresso pelo build e `$saida` com um diretório dedicado para a saída. A compilação gera um candidato local. A distribuição de binários requer verificação dos avisos e fontes correspondentes, além da homologação do pacote resultante.

### Evidência de código-fonte de terceiros

A compilação do aplicativo usa os insumos acima. A verificação aprofundada das fontes de Deno, do conjunto BtbN e do runtime embutido no yt-dlp é uma etapa adicional. Para esses testes, prepare uma pasta externa com os caminhos e hashes descritos nos manifestos de procedência em `docs/compliance` e `Licencas/yt-dlp`. Sem esses insumos, os casos diretamente dependentes dos dados de procedência ficam registrados como skips. As origens verificáveis estão listadas nos manifestos.

```powershell
$env:EDUDOWNLOADER_COMPLIANCE_INPUTS = $fontesTerceiros
& $python run_test_suite.py
Remove-Item Env:EDUDOWNLOADER_COMPLIANCE_INPUTS
```

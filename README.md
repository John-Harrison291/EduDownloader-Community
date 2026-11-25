# EduDownloader Community 3.0.0

O EduDownloader Community é gratuito e reúne downloads, organização de arquivos e ferramentas locais para PDF, documentos e mídia. Foi pensado para professores, estudantes e pessoas que preparam materiais educacionais. Esta árvore contém o código-fonte da Community.

## Funcionalidades

- **Downloads.** Vídeo MP4 e áudio MP3, fila, seleção de qualidade e destino, progresso e cancelamento.
- **Arquivos.** Pesquisa, filtros, favoritos e prévias, com encaminhamento para a ferramenta compatível.
- **PDF.** Junção, extração de páginas, conversão entre imagens e PDF, pôsteres e conversão básica para DOCX. O OCR local ajuda a extrair texto quando há páginas digitalizadas.
- **Documentos e mídia.** TXT para PDF, DOCX e ODT para PDF com LibreOffice compatível e ferramentas de vídeo e áudio locais.
- **Configurações.** Temas claro e escuro, tamanho de texto, diagnóstico e gerenciamento de componentes.

Use conteúdos próprios ou autorizados e respeite os direitos dos autores e os termos das plataformas. A conversão de arquivos locais ocorre no computador. A rede é usada para downloads e para consultas ou aquisição de componentes solicitadas na interface.

## Windows e dependências

O candidato homologado foi compilado para **Windows x64**. A validação de referência usou Windows 11. O ambiente de compilação usa CPython 3.14.6 x64 com Tcl/Tk, Microsoft Visual C++ Redistributable x64 e, para o instalador, Inno Setup 7.1.1. O usuário do portátil precisa manter os arquivos do pacote juntos e pode executá-lo sem instalar Python. O LibreOffice é um componente separado para as conversões de DOCX e ODT.

A interface usa CustomTkinter. Os serviços em Python usam pypdf, PDFium via pypdfium2 e Pillow para documentos PDF, imagens e prévias. yt-dlp, Deno e FFmpeg/FFprobe atendem aos fluxos de download e mídia. A detecção, a validação e a atualização autorizada de componentes estão separadas da interface. O PyInstaller gera o portátil e o Inno Setup compila o instalador Windows.

## Executar pelo código-fonte

No PowerShell, a partir da raiz do repositório:

```powershell
Set-Location 'Baixador Escolar'
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-build-hashes.lock
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe main.py
```

Para usar downloads, mídia e o OCR portátil também na execução pelo código, siga as instruções de aquisição e validação na [documentação de compilação](Baixador%20Escolar/docs/COMPILACAO.md).

## Compilar e contribuir

A [documentação de compilação](Baixador%20Escolar/docs/COMPILACAO.md) descreve os insumos verificados, a validação, a geração do portátil e do instalador. Use a versão e a arquitetura exatas do ambiente ao reproduzir os pacotes.

Contribuições podem incluir reproduções de erros, correções, testes ou documentação. Use documentos e URLs de teste sintéticos ou expressamente autorizados e mantenha credenciais, dados pessoais, logs e binários fora da árvore. Antes de propor uma mudança, execute os testes da área afetada e as verificações de estilo. Para mudanças na interface, descreva os cenários verificados no Windows.

## Limitações conhecidas

- A inicialização apresentou falhas nas escalas nativas de 125% e 150% do Windows no ambiente homologado. A validação em outros ambientes Windows está pendente.
- O aplicativo e o instalador aguardam assinatura digital confiável. Mantenha as proteções do Windows habilitadas.
- A conversão PDF para Word é aproximada. Layouts complexos, tabelas, fontes e páginas digitalizadas podem exigir correções no DOCX.
- Caminhos temporários extensos no Windows podem afetar a conversão pelo LibreOffice. A instalação para todos os usuários, a reutilização de instalações independentes do LibreOffice e o cenário sem Visual C++ prévio ainda precisam de homologação externa.
- O gerenciamento usa o catálogo local distribuído com o aplicativo. A autoridade de assinatura e o catálogo remoto de produção aguardam provisionamento.

## Licenciamento

O código e os documentos próprios seguem a [licença MIT](LICENSE) com o aviso de direitos autorais nela indicado. Os materiais de terceiros seguem suas próprias licenças. Consulte os [avisos e as fontes correspondentes](Baixador%20Escolar/Licencas/). A disponibilização do código-fonte da Community e a redistribuição de executáveis de terceiros são etapas distintas. Quem redistribuir um pacote binário deve cumprir a documentação de procedência e as condições dos respectivos componentes.

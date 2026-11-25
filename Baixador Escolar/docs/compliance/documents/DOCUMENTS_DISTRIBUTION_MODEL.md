# Modelo de distribuição da integração de documentos

Modelo de distribuição da Community 2.5.0 (1.4 e 1.6 são marcos históricos).

```text
DOCUMENTS_COMPONENT_DISTRIBUTION_MODEL = USER_PROVIDED_OR_USER_INITIATED_GUIDED_OFFICIAL_ACQUISITION
INTEGRATION_WITH_LIBREOFFICE = SUPPORTED
LIBREOFFICE_REDISTRIBUTED_BY_EDUDOWNLOADER = NO
LIBREOFFICE_USER_PROVIDED = YES
LIBREOFFICE_SILENT_INSTALL = NO
LIBREOFFICE_OFFICIAL_INSTALLER_INTERACTION_REQUIRED = YES
LIBREOFFICE_ACQUISITION_MODEL = USER_INITIATED_GUIDED_OFFICIAL_INSTALLER
LIBREOFFICE_BUNDLED_IN_MAIN_PACKAGE = NO
LIBREOFFICE_HOSTED_BY_EDUDOWNLOADER = NO
```

## Contrato operacional

### Fluxo ativo na 2.5.0

A descoberta é local/offline e limitada: preferência válida já configurada,
App Paths oficial do Windows (views 64/32-bit), pastas padrão de Program Files,
metadata gerenciada atual/legada e o destino orientado na 1.6 sob USERPROFILE.
Não há varredura de disco, busca em PATH nem execução de candidatos para
identificá-los. Instalações nativas e imagens administrativas são aceitas com
layout mínimo, cabeçalhos PE x64, fornecedor oficial e recurso VERSIONINFO
**26.8.3.1** nos três executáveis do motor. A versão Portable 26.2.4 foi retirada
da configuração ativa após o CVE-2026-18566. A verificação estrutural da
instalação existente não autentica a árvore inteira.
[Avisos do LibreOffice](https://www.libreoffice.org/security/)

Quando ausente, **Instalar LibreOffice** exige confirmação. O serviço prepara
`%LOCALAPPDATA%/EduDocuments/`, separado da pasta portátil: metadata em
`Componentes/active.json`, staging de operação em `Componentes/.staging/`
e destino curto em `Componentes/L/`. Um destino parcial anterior é preservado;
uma nova tentativa usa pasta distinta. Unicode/espaços não são rejeitados por
política, mas caminhos excessivamente longos continuam recusados com mensagem.
Sem data root válido/permissão/espaço, falha sem fallback para a pasta do app.

A aquisição depende do consentimento do usuário e baixa o MSI oficial do
espelho HTTPS aprovado em `LIBREOFFICE_MANAGED_BASELINE.json`. O download
recebe a extensão `.msi` após a conferência do tamanho e do SHA-256. O
staging próprio é limpo após a operação e a recuperação só alcança áreas
inequivocamente órfãs.

O assistente do Windows Installer abre com `/a`, `TARGETDIR=<destino>` e
`/norestart`. O modo administrativo grava uma imagem local na pasta dedicada,
sem registrar o produto como instalação global. O usuário confirma a pasta e
conclui a janela oficial. Após o fechamento, o serviço verifica a raiz
selecionada e só então grava o ponteiro e habilita DOCX/ODT.
[Modo de imagem administrativa do Windows Installer](https://learn.microsoft.com/en-us/windows/win32/msi/administrative-installation)
O worker aguarda no máximo 15 minutos. Se a janela oficial continuar aberta,
o worker termina, mantém payload/locks da operação e oferece recheck explícito
não bloqueante após o usuário concluí-la. Não mata o instalador nem remove seu
payload enquanto ativo; o fechamento normal do app aguarda essa operação.
Se o destino for alterado na janela oficial, **Verificar instalação** repete
a descoberta limitada; **Localizar LibreOffice** é fallback manual validado.
Instalação removida é reavaliada ao abrir Documentos ou verificar componentes.
TXT → PDF permanece interno e independente. As duas edições usam o mesmo fluxo,
sem consulta à ativação, chave operacional ou backup.

Referência da descoberta nativa: [registro App Paths no código upstream](https://github.com/LibreOffice/core/blob/master/scp2/source/ooo/registryitem_ooo.scp).
O motor continua externo; profile isolado, Job Object, timeout/cancelamento de
conversão e publicação atômica permanecem sem alterações.

### OLD_FLOW — registro do contrato 1.6, substituído acima somente na UX/setup

O EduDownloader não hospeda, extrai, reempacota nem inclui LibreOffice,
LibreOffice Portable ou launchers PortableApps em sua distribuição. Para usar
DOCX → PDF e ODT → PDF, o usuário pode selecionar uma instalação local obtida
na [página oficial do PortableApps.com](https://portableapps.com/apps/office/libreoffice_portable)
ou iniciar, voluntariamente, a aquisição guiada do instalador oficial. Nesse
segundo fluxo, o aplicativo baixa o pacote da fonte oficial, confere tamanho e
SHA-256 pinados, mostra um destino curto e estável para cópia, abre o instalador
oficial sem parâmetros de instalação silenciosa e valida somente esse destino
antes de ativá-lo. O usuário cola/confirma o caminho na janela oficial. Não há
instalação silenciosa nem download ao iniciar o app.

A seleção manual é explícita e persistida apenas como path local. Na aquisição
guiada, a origem `MANAGED` é persistida com caminho relativo quando o destino é
`Componentes/L`; caso o usuário escolha explicitamente outra
pasta compatível, essa localização é registrada como tal, sem fallback oculto.
Um destino externo é `MANAGED_EXTERNAL_ROOT`: fica absoluto e não acompanha
uma eventual mudança da pasta do aplicativo. Destinos internos `L` e
`L-repair-<id>` ficam relativos a `Componentes/` e são relocáveis com ela.
O path manual anterior permanece preservado. O cliente valida a
identidade PortableApps/LibreOffice, a versão suportada e os arquivos mínimos
necessários antes de iniciar `soffice.com` por path absoluto. Não existe busca
global, dependência do `PATH`, instalação automática ou
fallback silencioso. A aquisição guiada é iniciada somente pelo usuário,
com confirmação, progresso, cancelamento e interação no instalador oficial.
Uma configuração ausente, incompatível ou incompleta
falha de modo controlado e pode ser corrigida posteriormente.
Na 1.6-G, o reparo de managed com problema é uma nova aquisição guiada da
mesma baseline, em pasta nova e vazia. O componente anterior e a escolha manual
não são removidos; o novo ponteiro só é gravado após verificação. A limpeza
automática limita-se a staging cuja posse e inatividade sejam comprovadas.

O runtime permanece externo, local, opcional e executado em processo separado.
Cada conversão usa profile e temporários isolados, ambiente restrito, controle
da árvore de processos, cancelamento e publicação atômica já aceitos
tecnicamente. TXT → PDF continua interno e não consulta LibreOffice.

LibreOffice é software de terceiros, não desenvolvido, certificado, hospedado ou
distribuído pelo EduDownloader, e permanece sujeito aos termos do respectivo
fornecedor. A identificação textual tem finalidade exclusivamente funcional.

## Packaging e compliance

A distribuição do EduDownloader rejeita árvores, executáveis, launchers,
fontes e evidências de runtime do LibreOffice/PortableApps. Os manifestos,
inventários e relatórios existentes neste diretório permanecem como evidência
histórica da PoC, da aceitação interna e da decisão que encerrou o modelo de
ZIP reempacotado; eles não são copiados para o artefato público.

Com o runtime efetivamente ausente da distribuição, os achados anteriores
relativos ao reempacotamento, às DLLs incluídas pelo pacote upstream, ao source
bundle do pacote redistribuído, ao OpenSymbol e aos dicionários passam a ser
`NOT_APPLICABLE_TO_EDUDOWNLOADER_DISTRIBUTION`. Isso não é parecer jurídico e
não autoriza redistribuir esses arquivos por outro canal.

```text
LEGAL_REVIEW_REQUIRED = NO_FOR_USER_PROVIDED_LIBREOFFICE_INTEGRATION
LEGAL_COMPLIANCE_STATUS = PASS_FOR_INTEGRATION_WITHOUT_REDISTRIBUTION
DISTRIBUTION_ALLOWED = ALLOWED_WITHOUT_BUNDLED_LIBREOFFICE
PUBLIC_RELEASE_WITH_DOCUMENTS_COMPONENT = NOT_APPLICABLE_SUPERSEDED_TERM
PUBLIC_RELEASE_WITH_DOCUMENTS_INTEGRATION = ALLOWED
PUBLIC_RELEASE_WITH_BUNDLED_LIBREOFFICE = NO
COMMERCIAL_USE_COMPATIBLE = CONDITIONAL_ON_GENERAL_PROJECT_REVIEW
```

Esses estados removem somente o bloqueio técnico/documental causado pela
redistribuição própria do LibreOffice. Os gates gerais do projeto continuam
separados e não são abertos por esta decisão.

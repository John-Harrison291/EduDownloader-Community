# Microsoft VC runtime externo — composição Community 1.4 posterior ao RC1

O modelo do **próximo** pacote é `EXTERNAL_PREREQUISITE`. O arquivo canônico
`MICROSOFT_EXTERNAL_RUNTIME_POLICY.json` exige zero cópias app-local de
`VCRUNTIME140.dll` e `VCRUNTIME140_1.dll`. O spec não injeta binários Microsoft,
o wrapper PyInstaller isola o PATH sem a autoridade de staging antiga, e os
validadores de Analysis, candidato e distribuição rejeitam arquivos diretos.
Nomes importados de DLL em executáveis, materiais embutidos por upstream e
referências textuais não são classificados como arquivo direto do cliente.

Microsoft Visual C++ Runtime x64 compatível passa a ser pré-requisito instalado
no Windows. O host de teste possui 14.51.36247.0; o número é evidência local,
**não** mínimo técnico afirmado para todos os binários. O EduDownloader não
baixa, hospeda nem redistribui `vc_redist`; a instalação, quando necessária,
deve vir da [página oficial Microsoft](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170).
Se faltar o runtime, o executável pode falhar antes do código Python/UI.

`MICROSOFT_RUNTIME_PACKAGING.json`, `MICROSOFT_RUNTIME_PACKAGING.md` e o
inventário P3-01 preservam a autoridade, o pin e os bytes do RC1 **histórico**,
que continha as duas DLLs. Não devem ser usados como instrução para o próximo
build. A cadeia Microsoft de componentes upstream continua risco registrado
separadamente; a mudança não é parecer jurídico sobre esses componentes.
Como a distribuição muda, `RC2_REQUIRED = YES` antes da publicação. Gates
`production_ready` e `public_release_allowed` permanecem `false`.

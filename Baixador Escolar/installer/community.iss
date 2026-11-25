; Compilado por build_community_installer.py com entradas verificadas.
#define ProductName "EduDownloader"
#define ReleaseKey "6F734F86-BF85-43D6-91DA-250B0F7D6F47"
#define VariantDir "Programa\" + PayloadID
#define OfficeDir "Componentes\LibreOffice\" + OfficeEngine

[Setup]
AppId={{{#ReleaseKey}}
AppName={#ProductName}
AppVersion={#AppVersion}
AppVerName={#ProductName} {#AppVersion}
AppPublisher=EduDownloader
VersionInfoVersion={#AppVersion}.0
VersionInfoProductVersion={#AppVersion}.0
VersionInfoDescription=Instalador do EduDownloader
SetupArchitecture=x64
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\EduDownloader
DefaultGroupName=EduDownloader
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableDirPage=no
UsePreviousAppDir=yes
UsePreviousGroup=no
UsePreviousSetupType=yes
SetupIconFile=..\branding\edudownloader-symbol.ico
WizardSmallImageFile={#LogoFile}
WizardImageFile={#WizardPanel}
WizardStyle=modern light
UninstallDisplayIcon={app}\{#VariantDir}\EduDownloader.exe
UninstallDisplayName={#ProductName}
OutputBaseFilename=EduDownloader-{#AppVersion}-Setup-Windows-x64
Compression=lzma2/normal
SolidCompression=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
AllowNetworkDrive=no
AllowUNCPath=no
AllowRootDirectory=no
AllowNoIcons=no
ShowComponentSizes=no
AppendDefaultDirName=no
UsePreviousPrivileges=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[CustomMessages]
ptbr.InstallCore=EduDownloader e ferramentas locais
ptbr.InstallOffice=Preparar LibreOffice para converter DOCX e ODT em PDF
ptbr.CoreOnly=Somente EduDownloader
ptbr.WithOffice=EduDownloader com LibreOffice
ptbr.Choose=Personalizada
ptbr.Launch=Executar o EduDownloader
ptbr.VcTitle=Preparando o Visual C++ x64
ptbr.OfficeTitle=Preparando o LibreOffice para Documentos
ptbr.DownloadHint=O pacote será obtido do fornecedor e verificado antes de executar.
ptbr.ExpandOffice=Preparando o motor de conversão de documentos.
ptbr.VerifyOffice=Verificando o motor com uma conversão de teste.
ptbr.ReduceOffice=Organizando os recursos de interface do LibreOffice.
ptbr.VerifyRequirements=Verificando os requisitos do computador.
ptbr.CheckComponents=Verificando os componentes disponíveis.
ptbr.CoreFiles=Instalando os arquivos e as ferramentas do EduDownloader.
ptbr.OfficeFiles=Copiando os componentes do LibreOffice.
ptbr.CheckInstalled=Verificando os componentes instalados.
ptbr.CheckUpdates=Consultando versões homologadas dos componentes.
ptbr.Finalizing=Finalizando a instalação.
ptbr.Finished=Instalação concluída.
ptbr.ProgressSteps=Etapas concluídas: %1 de %2.
ptbr.TargetSpace=Arquivos da instalação em %1: até %2.
ptbr.TemporarySpace=Área temporária em %1: até %2.
ptbr.ReserveSpace=Margem adicional de 256 MiB por unidade utilizada.
ptbr.ReuseSpace=O LibreOffice disponível será reutilizado.
ptbr.CoreSpace=Não há espaço suficiente na unidade de destino para instalar o EduDownloader.
ptbr.VcSpace=Não há espaço suficiente para obter o Visual C++ x64 necessário.
ptbr.UninstallOptions=Dados do EduDownloader
ptbr.UninstallDetails=Os componentes gerenciados serão removidos. Documentos, downloads e arquivos gerados serão preservados.
ptbr.UninstallSettings=Remover também preferências e logs deste perfil do Windows
ptbr.UninstallContinue=Continuar
ptbr.UninstallDataFailure=Alguns dados internos não puderam ser removidos. Consulte o log da desinstalação.
ptbr.VcFailed=Não foi possível preparar o Visual C++ x64 necessário. Verifique a conexão e confirme a permissão de administrador, ou instale o redistribuível oficial da Microsoft e tente novamente.
ptbr.VcRecords=O registro do Visual C++ x64 contém informações inconsistentes. Verifique a instalação do runtime oficial antes de continuar.
ptbr.VcRestart=O Visual C++ foi preparado. Reinicie o computador e execute este assistente novamente.
ptbr.OfficeReused=Um LibreOffice compatível foi localizado e será reutilizado.
ptbr.OfficeMissing=O LibreOffice não foi preparado. Você poderá prepará-lo depois em Configurações.
ptbr.OfficeSpace=Espaço insuficiente para preparar o LibreOffice. Prepare-o depois em Configurações ou use uma unidade com mais espaço.
ptbr.OfficePath=O caminho temporário é longo demais para o LibreOffice. Você poderá prepará-lo depois em Configurações.
ptbr.OfficeCancelled=A preparação do LibreOffice foi cancelada. Você poderá retomá-la em Configurações.
ptbr.VcOffline=Não foi encontrado um Visual C++ x64 compatível. Conecte-se à internet ou instale o redistribuível oficial e execute o assistente novamente.
ptbr.FolderOwned=Escolha uma pasta vazia ou o diretório da instalação já registrada.
ptbr.ScopeConflict=Já há uma instalação do EduDownloader em outro modo. Execute o assistente no mesmo modo da instalação anterior.
ptbr.UnsafeFolder=Escolha uma pasta local em disco fixo, sem atalhos de diretório, com caminho mais curto.

[Types]
Name: "complete"; Description: "{cm:WithOffice}"
Name: "core"; Description: "{cm:CoreOnly}"
Name: "custom"; Description: "{cm:Choose}"; Flags: iscustom

[Components]
Name: "core"; Description: "{cm:InstallCore}"; Types: complete core custom; Flags: fixed
Name: "libreoffice"; Description: "{cm:InstallOffice}"; Types: complete

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "libreoffice-ui-resources.txt"; Flags: dontcopy noencryption
Source: "{#Payload}\*"; DestDir: "{app}\{#VariantDir}"; Excludes: "\Downloads\*,\Logs\*"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: core
Source: "EduDownloader.Community.installed"; DestDir: "{app}\{#VariantDir}"; Flags: ignoreversion; Components: core; AfterInstall: CoreFilesDone
Source: "{tmp}\lo-image\*"; DestDir: "{app}\{#OfficeDir}"; Excludes: "\LibreOffice*.msi,__pycache__\*"; Flags: external skipifsourcedoesntexist recursesubdirs createallsubdirs ignoreversion; ExternalSize: {#OfficeInstallSize}; Components: libreoffice; Check: CopyPreparedOffice; BeforeInstall: BeginOfficeCopy; AfterInstall: OfficeCopyDone

[Icons]
Name: "{autoprograms}\EduDownloader\EduDownloader"; Filename: "{app}\{#VariantDir}\EduDownloader.exe"; WorkingDir: "{app}\{#VariantDir}"; Flags: uninsneveruninstall; Check: AllowShortcut('{autoprograms}\EduDownloader\EduDownloader.lnk')
Name: "{autodesktop}\EduDownloader"; Filename: "{app}\{#VariantDir}\EduDownloader.exe"; WorkingDir: "{app}\{#VariantDir}"; Tasks: desktopicon; Flags: uninsneveruninstall; Check: AllowShortcut('{autodesktop}\EduDownloader.lnk')

[Run]
Filename: "{app}\{#VariantDir}\EduDownloader.exe"; Description: "{cm:Launch}"; WorkingDir: "{app}\{#VariantDir}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#ReleaseKey}' + '}_is1';
  RuntimeKey = 'Software\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  SpaceReserve = 268435456;

var
  DownloadPage: TDownloadWizardPage;
  ActivityPage: TOutputMarqueeProgressWizardPage;
  InstallProgress: TNewProgressBar;
  InstallActivity: TNewProgressBar;
  InstallStageLabel, InstallStepsLabel, SpaceLabel: TNewStaticText;
  OriginalComponentClick, OriginalTypeChange: TNotifyEvent;
  OfficeStatus: String;
  FinishedOfficeLabel: TNewStaticText;
  OfficeImageOwned, OfficeProbeOwned: Boolean;
  OfficePrepared: Boolean;
  RestartAfterSetup: Boolean;
  DownloadName: String;
  DownloadStartedAt: UInt64;
  SpaceOfficeReused, SpaceNeedsVC: Boolean;
  SpaceCheckedAt: String;
  InstallStageCount, InstallCompleted: Integer;
  RemoveUserSettings: Boolean;

function GetFileAttributesW(Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function GetDriveTypeW(Drive: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function GetTickCount64: UInt64;
  external 'GetTickCount64@kernel32.dll stdcall';

function SetEnvironmentVariableW(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function OfflineInstall: Boolean;
var
  Index: Integer;
begin
  Result := True;
  for Index := 1 to ParamCount do
    if CompareText(ParamStr(Index), '/OFFLINE') = 0 then
      Exit;
  Result := False;
end;

function SafeLocalDirectory(PathName: String): Boolean;
var
  Root, Current: String;
  Attr: Cardinal;
begin
  Result := False;
  if Length(PathName) > 180 then
    Exit;
  Root := ExtractFileDrive(PathName);
  if (Length(Root) <> 2) or (Copy(PathName, 3, 1) <> '\') then
    Exit;
  if GetDriveTypeW(Root + '\') <> 3 then
    Exit;
  Current := RemoveBackslashUnlessRoot(PathName);
  while Length(Current) > 3 do
  begin
    Attr := GetFileAttributesW(Current);
    if (Attr <> $FFFFFFFF) and (((Attr and $10) = 0) or ((Attr and $400) <> 0)) then
      Exit;
    Current := ExtractFileDir(Current);
  end;
  Result := True;
end;

function OwnedShortcut(Link: String): Boolean;
var
  Shell, Shortcut: Variant;
  Target, Revision, ProgramDir, Marker, Identity: String;
  I: Integer;
begin
  Result := False;
  if not SafeLocalDirectory(ExtractFileDir(Link)) or
    not FileExists(Link) or ((GetFileAttributesW(Link) and $400) <> 0) then
    Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Shortcut := Shell.CreateShortcut(Link);
    Target := Shortcut.TargetPath;
    Revision := ExtractFileDir(Target);
    ProgramDir := ExtractFileDir(Revision);
    Identity := LowerCase(ExtractFileName(Revision));
    if (Length(Identity) <> 24) or (CompareText(ExtractFileName(Target), 'EduDownloader.exe') <> 0) or
      (CompareText(ProgramDir, ExpandConstant('{app}\Programa')) <> 0) or
      not SafeLocalDirectory(Revision) then
      Exit;
    for I := 1 to Length(Identity) do
      if Pos(Identity[I], '0123456789abcdef') = 0 then
        Exit;
    Marker := AddBackslash(Revision) + 'EduDownloader.Community.installed';
    Result := FileExists(Marker) and ((GetFileAttributesW(Marker) and $400) = 0) and
      (CompareText(GetSHA256OfFile(Marker), '{#InstallMarkerSHA}') = 0);
  except
    Log('Não foi possível confirmar a propriedade do atalho: ' + Link);
  end;
end;

function AllowShortcut(Name: String): Boolean;
var
  Link: String;
begin
  Link := ExpandConstant(Name);
  Result := SafeLocalDirectory(ExtractFileDir(Link)) and
    ((GetFileAttributesW(Link) = $FFFFFFFF) or OwnedShortcut(Link));
  if not Result then
    Log('Atalho de outra origem preservado: ' + Link);
end;

function RemoveLegacyShortcut(Link, Replacement: String): Boolean;
begin
  Result := OwnedShortcut(Replacement) and OwnedShortcut(Link) and DeleteFile(Link);
  if Result then
    Log('Atalho da versão anterior removido: ' + Link);
end;

function PreviousFolder(RootKey: Integer; var Folder: String): Boolean;
begin
  Result := RegQueryStringValue(RootKey, UninstallKey, 'Inno Setup: App Path', Folder) and (Folder <> '');
end;

function InitializeSetup: Boolean;
var
  OtherFolder: String;
  OtherKey: Integer;
begin
  OtherKey := HKLM64;
  if IsAdminInstallMode then
    OtherKey := HKCU64;
  Result := not PreviousFolder(OtherKey, OtherFolder);
  if not Result then
    SuppressibleMsgBox(CustomMessage('ScopeConflict'), mbError, MB_OK, IDOK);
end;

function SizeText(Bytes: Int64): String;
begin
  if Bytes >= 1073741824 then
    Result := Format('%.2f GiB', [Bytes / 1073741824.0])
  else
    Result := Format('%.1f MiB', [Bytes / 1048576.0]);
  StringChangeEx(Result, '.', ',', True);
end;

function ShowDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
var
  Seconds: Int64;
  Details: String;
  Rate: Int64;
begin
  Result := not DownloadPage.AbortedByUser;
  Details := SizeText(Progress);
  if ProgressMax > 0 then
    Details := Format('%d%%  ·  %s de %s', [(Progress * 100) div ProgressMax, Details, SizeText(ProgressMax)]);
  Seconds := (GetTickCount64 - DownloadStartedAt) div 1000;
  if (Seconds >= 2) and (Progress > 0) then
  begin
    Rate := Progress div Seconds;
    if Rate > 0 then
    begin
      Details := Details + '  ·  ' + SizeText(Rate) + '/s';
      if (Seconds >= 5) and (ProgressMax > Progress) then
        Details := Details + Format('  ·  ~%d s restantes', [(ProgressMax - Progress) div Rate]);
    end;
  end;
  DownloadPage.Msg1Label.Caption := DownloadName;
  DownloadPage.Msg2Label.Caption := Details;
  if ProgressMax <= 0 then
    DownloadPage.ProgressBar.Style := npbstMarquee
  else
    DownloadPage.ProgressBar.Style := npbstNormal;
end;

function DestinationError: String;
var
  Directory, Previous: String;
  Entry: TFindRec;
  ThisKey: Integer;
begin
  Result := '';
  Directory := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  if not SafeLocalDirectory(Directory) then
  begin
    Result := CustomMessage('UnsafeFolder');
    Exit;
  end;
  ThisKey := HKCU64;
  if IsAdminInstallMode then
    ThisKey := HKLM64;
  if PreviousFolder(ThisKey, Previous) then
  begin
    if CompareText(Directory, RemoveBackslashUnlessRoot(Previous)) <> 0 then
      Result := CustomMessage('FolderOwned');
    Exit;
  end;
  if FindFirst(AddBackslash(Directory) + '*', Entry) then
  begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then
        begin
          Result := CustomMessage('FolderOwned');
          Exit;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

function PSLiteral(Value: String): String;
begin
  StringChangeEx(Value, '''', '''''', True);
  Result := '''' + Value + '''';
end;

function VerifyAuthenticode(Filename, Thumbprint: String): Boolean;
var
  Command: String;
  Code: Integer;
begin
  Command :=
    '$ErrorActionPreference=''Stop''; ' +
    'Import-Module (Join-Path $PSHOME ''Modules\Microsoft.PowerShell.Security''); ' +
    '$s=Get-AuthenticodeSignature -LiteralPath ' + PSLiteral(Filename) + '; ' +
    'if ($s.Status -eq ''Valid'' -and $s.SignerCertificate.Thumbprint -eq ' +
    PSLiteral(Thumbprint) + ') { exit 0 }; exit 1';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoLogo -NoProfile -NonInteractive -Command ' + AddQuotes(Command),
    ExpandConstant('{sys}'), SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function FetchPackage(Title, DisplayName, URL, Name, Hash, Signer: String; var Cancelled: Boolean): Boolean;
var
  Filename: String;
begin
  Result := False;
  Cancelled := False;
  Filename := ExpandConstant('{tmp}\') + Name;
  DownloadPage.Caption := Title;
  DownloadName := DisplayName;
  DownloadStartedAt := GetTickCount64;
  DownloadPage.Clear;
  DownloadPage.Add(URL, Name, Hash);
  DownloadPage.SetText(DisplayName, '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      Result := FileExists(Filename) and (CompareText(GetSHA256OfFile(Filename), Hash) = 0) and
        VerifyAuthenticode(Filename, Signer);
      if not Result then
        Log('Pré-requisito recusado na verificação de integridade ou assinatura.');
    except
      Cancelled := DownloadPage.AbortedByUser;
      Log('Aquisição de pré-requisito interrompida: ' + GetExceptionMessage);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

function VCRecord(Root: Integer; var HasRecord: Boolean; var Valid: Boolean): String;
var
  Installed, Major, Minor, Bld, Rbld: Cardinal;
  Version: String;
  Reported, Numeric: Int64;
begin
  Result := '';
  HasRecord := RegKeyExists(Root, RuntimeKey);
  Valid := not HasRecord;
  if not HasRecord then
    Exit;
  if not RegQueryDWordValue(Root, RuntimeKey, 'Installed', Installed) then
    Exit;
  Valid := Installed = 0;
  if Installed <> 1 then
    Exit;
  if not (RegQueryStringValue(Root, RuntimeKey, 'Version', Version) and
          RegQueryDWordValue(Root, RuntimeKey, 'Major', Major) and
          RegQueryDWordValue(Root, RuntimeKey, 'Minor', Minor) and
          RegQueryDWordValue(Root, RuntimeKey, 'Bld', Bld) and
          RegQueryDWordValue(Root, RuntimeKey, 'Rbld', Rbld)) then
    Exit;
  if Copy(Version, 1, 1) = 'v' then
    Delete(Version, 1, 1);
  if (Major <> 14) or (Minor > 65535) or (Bld > 65535) or (Rbld > 65535) or
     not StrToVersion(Version, Reported) then
    Exit;
  Numeric := PackVersionComponents(Major, Minor, Bld, Rbld);
  Valid := SamePackedVersion(Numeric, Reported);
  if Valid then
    Result := VersionToStr(Numeric);
end;

function CompatibleVC(var Consistent: Boolean): Boolean;
var
  Registry32, Registry64, Seen32, Seen64, Valid32, Valid64: Boolean;
  Version32, Version64, Version: String;
  Observed, Minimum: Int64;
begin
  Version64 := VCRecord(HKLM64, Seen64, Valid64);
  Version32 := VCRecord(HKLM32, Seen32, Valid32);
  Result := False;
  Registry32 := Version32 <> '';
  Registry64 := Version64 <> '';
  Consistent := Valid32 and Valid64 and not (Seen32 and Seen64 and (Version32 <> Version64));
  if not Consistent then
    Exit;
  Version := Version64;
  if not Registry64 and Registry32 then
    Version := Version32;
  if Version = '' then
    Exit;
  if not (StrToVersion(Version, Observed) and StrToVersion('{#VCMinimum}', Minimum)) then
    Exit;
  Result := ComparePackedVersion(Observed, Minimum) >= 0;
end;

function PrepareVC(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  FileName, Mode: String;
  Cancelled, Ran, Consistent: Boolean;
begin
  Result := '';
  if CompatibleVC(Consistent) then
  begin
    Log('Visual C++ x64 compatível detectado. Instalação ignorada.');
    Exit;
  end;
  if OfflineInstall then
  begin
    Result := CustomMessage('VcOffline');
    Exit;
  end;
  if not Consistent then
  begin
    Result := CustomMessage('VcRecords');
    Exit;
  end;
  Result := CustomMessage('VcFailed');
  if not FetchPackage(CustomMessage('VcTitle'), 'Microsoft Visual C++ x64', '{#VCURL}', 'vc-redist-x64.exe',
      '{#VCSHA}', '{#VCSigner}', Cancelled) then
    Exit;
  FileName := ExpandConstant('{tmp}\vc-redist-x64.exe');
  Mode := '/install /passive /norestart';
  if WizardSilent then
    Mode := '/install /quiet /norestart';
  if IsAdminInstallMode then
    Ran := Exec(FileName, Mode, ExpandConstant('{sys}'), SW_SHOWNORMAL, ewWaitUntilTerminated, Code)
  else
    Ran := ShellExec('runas', FileName, Mode, ExpandConstant('{sys}'), SW_SHOWNORMAL, ewWaitUntilTerminated, Code);
  if not Ran then
  begin
    Log('Visual C++ não iniciou. Código ' + IntToStr(Code));
    Exit;
  end;
  Log('Redistribuível Microsoft terminou com código ' + IntToStr(Code));
  if (Code = 0) or (Code = 1638) or (Code = 3010) or (Code = 1641) then
  begin
    if CompatibleVC(Consistent) then
    begin
      RestartAfterSetup := (Code = 3010) or (Code = 1641);
      Result := '';
    end
    else if (Code = 3010) or (Code = 1641) then
    begin
      NeedsRestart := True;
      Result := CustomMessage('VcRestart');
    end;
  end;
end;

function VerifyOfficeBinary(Root, Filename, ExpectedSHA: String): Boolean;
var
  PathName: String;
begin
  PathName := AddBackslash(Root) + 'program\' + Filename;
  Result := FileExists(PathName) and
    ((GetFileAttributesW(PathName) and $400) = 0) and
    (CompareText(GetSHA256OfFile(PathName), ExpectedSHA) = 0) and
    VerifyAuthenticode(PathName, '{#OfficeSigner}');
end;

function VerifiedOffice(Root: String): Boolean;
begin
  Result := SafeLocalDirectory(Root) and SafeLocalDirectory(AddBackslash(Root) + 'program') and
    FileExists(AddBackslash(Root) + 'license.txt') and
    FileExists(AddBackslash(Root) + 'program\bootstrap.ini') and
    VerifyOfficeBinary(Root, 'soffice.com', '{#OfficeSOFFICECOM}') and
    VerifyOfficeBinary(Root, 'soffice.exe', '{#OfficeSOFFICEEXE}') and
    VerifyOfficeBinary(Root, 'soffice.bin', '{#OfficeSOFFICEBIN}');
end;

function HasCompatibleOffice: Boolean;
var
  Native: String;
begin
  Result := VerifiedOffice(ExpandConstant('{app}\{#OfficeDir}')) or
    VerifiedOffice(ExpandConstant('{commonpf}\LibreOffice'));
  if Result then
    Exit;
  if RegQueryStringValue(HKLM64,
      'Software\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe', '', Native) then
    Result := VerifiedOffice(ExtractFileDir(ExtractFileDir(RemoveQuotes(Native))));
end;

procedure SpaceBudget(AddOffice, AddVC: Boolean; var TargetBytes, TempBytes: Int64);
begin
  TargetBytes := {#PayloadSize};
  TempBytes := 0;
  if AddVC then
    TempBytes := {#VCSize};
  if AddOffice then
  begin
    TargetBytes := TargetBytes + {#OfficeInstallSize};
    TempBytes := TempBytes + {#OfficeMSISize} + {#OfficeImageSize};
  end;
end;

function SpaceAvailable(AddOffice, AddVC: Boolean): Boolean;
var
  TempFree, TempTotal, TargetFree, TargetTotal, TempNeed, TargetNeed: Int64;
  TempDir, Target: String;
begin
  TempDir := ExpandConstant('{tmp}');
  Target := ExpandConstant('{app}');
  Result := GetSpaceOnDisk64(TempDir, TempFree, TempTotal) and
    GetSpaceOnDisk64(ExtractFileDrive(Target) + '\', TargetFree, TargetTotal);
  if not Result then
    Exit;
  SpaceBudget(AddOffice, AddVC, TargetNeed, TempNeed);
  TargetNeed := TargetNeed + SpaceReserve;
  if CompareText(ExtractFileDrive(TempDir), ExtractFileDrive(Target)) = 0 then
    Result := TempFree >= (TempNeed + TargetNeed)
  else
    Result := (TargetFree >= TargetNeed) and
      ((TempNeed = 0) or (TempFree >= TempNeed + SpaceReserve));
end;

procedure RefreshSpace(Sender: TObject);
var
  TargetNeed, TempNeed: Int64;
  Selected: Boolean;
begin
  Selected := WizardIsComponentSelected('libreoffice');
  SpaceBudget(Selected and not SpaceOfficeReused and not OfflineInstall,
    SpaceNeedsVC and not OfflineInstall, TargetNeed, TempNeed);
  SpaceLabel.Caption := FmtMessage(CustomMessage('TargetSpace'), [
    ExtractFileDrive(WizardDirValue), SizeText(TargetNeed)]) + #13#10 +
    FmtMessage(CustomMessage('TemporarySpace'), [
      ExtractFileDrive(ExpandConstant('{tmp}')), SizeText(TempNeed)]) + #13#10 +
    CustomMessage('ReserveSpace');
  if Selected and SpaceOfficeReused then
    SpaceLabel.Caption := SpaceLabel.Caption + #13#10 + CustomMessage('ReuseSpace');
end;

procedure ComponentClick(Sender: TObject);
begin
  if OriginalComponentClick <> nil then
    OriginalComponentClick(Sender);
  RefreshSpace(Sender);
end;

procedure SetupTypeChange(Sender: TObject);
begin
  if OriginalTypeChange <> nil then
    OriginalTypeChange(Sender);
  RefreshSpace(Sender);
end;

procedure InitializeWizard;
var
  Gauge: TNewProgressBar;
begin
  DownloadPage := CreateDownloadPage(CustomMessage('OfficeTitle'), CustomMessage('DownloadHint'), @ShowDownloadProgress);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
  ActivityPage := CreateOutputMarqueeProgressPage('Preparação da instalação', 'A instalação continuará ao terminar esta etapa.');
  FinishedOfficeLabel := TNewStaticText.Create(WizardForm);
  FinishedOfficeLabel.Parent := WizardForm.FinishedPage;
  FinishedOfficeLabel.AutoSize := False;
  FinishedOfficeLabel.WordWrap := True;
  FinishedOfficeLabel.SetBounds(WizardForm.FinishedLabel.Left,
    WizardForm.FinishedLabel.Top + ScaleY(105), WizardForm.FinishedLabel.Width, ScaleY(90));
  SpaceLabel := TNewStaticText.Create(WizardForm);
  SpaceLabel.Parent := WizardForm.SelectComponentsPage;
  SpaceLabel.AutoSize := False;
  SpaceLabel.WordWrap := True;
  SpaceLabel.SetBounds(WizardForm.ComponentsList.Left, WizardForm.ComponentsList.Top +
    WizardForm.ComponentsList.Height - ScaleY(90), WizardForm.ComponentsList.Width, ScaleY(105));
  WizardForm.ComponentsList.Height := WizardForm.ComponentsList.Height - ScaleY(96);
  WizardForm.ComponentsDiskSpaceLabel.Visible := False;
  OriginalComponentClick := WizardForm.ComponentsList.OnClickCheck;
  WizardForm.ComponentsList.OnClickCheck := @ComponentClick;
  OriginalTypeChange := WizardForm.TypesCombo.OnChange;
  WizardForm.TypesCombo.OnChange := @SetupTypeChange;

  WizardForm.StatusLabel.Visible := False;
  WizardForm.FilenameLabel.Visible := False;
  Gauge := WizardForm.ProgressGauge;
  Gauge.Visible := False;
  InstallStageLabel := TNewStaticText.Create(WizardForm);
  InstallStageLabel.Parent := WizardForm.InstallingPage;
  InstallStageLabel.AutoSize := False;
  InstallStageLabel.WordWrap := True;
  InstallStageLabel.SetBounds(Gauge.Left, WizardForm.StatusLabel.Top, Gauge.Width, ScaleY(36));
  InstallProgress := TNewProgressBar.Create(WizardForm);
  InstallProgress.Parent := WizardForm.InstallingPage;
  InstallProgress.SetBounds(Gauge.Left, Gauge.Top, Gauge.Width, Gauge.Height);
  InstallStepsLabel := TNewStaticText.Create(WizardForm);
  InstallStepsLabel.Parent := WizardForm.InstallingPage;
  InstallStepsLabel.SetBounds(Gauge.Left, Gauge.Top + Gauge.Height + ScaleY(8), Gauge.Width, ScaleY(20));
  InstallActivity := TNewProgressBar.Create(WizardForm);
  InstallActivity.Parent := WizardForm.InstallingPage;
  InstallActivity.SetBounds(Gauge.Left, Gauge.Top + Gauge.Height + ScaleY(35), Gauge.Width, ScaleY(7));
  InstallActivity.Style := npbstMarquee;
end;

procedure ShowActivity(Text: String);
begin
  ActivityPage.SetText(Text, '');
  ActivityPage.Show;
  ActivityPage.Animate;
end;

function SmokeOffice(Root: String): Boolean;
var
  Profile, Scratch, Sample, Output, Uri, RunParams, PreviousBytecode: String;
  Code: Integer;
  PDF: AnsiString;
begin
  Result := False;
  Scratch := ExpandConstant('{tmp}\lo-test');
  Profile := AddBackslash(Scratch) + 'profile';
  Sample := AddBackslash(Scratch) + 'amostra.txt';
  Output := AddBackslash(Scratch) + 'amostra.pdf';
  if not SafeLocalDirectory(Scratch) or DirExists(Scratch) or not CreateDir(Scratch) then
    Exit;
  OfficeProbeOwned := True;
  if not SaveStringToFile(Sample, 'EduDownloader {#AppVersion}', False) then
    Exit;
  Uri := Profile;
  StringChangeEx(Uri, '\', '/', True);
  StringChangeEx(Uri, '%', '%25', True);
  StringChangeEx(Uri, ' ', '%20', True);
  StringChangeEx(Uri, '#', '%23', True);
  RunParams := AddQuotes('-env:UserInstallation=file:///' + Uri) +
    ' --headless --nologo --nodefault --norestore --convert-to pdf:writer_pdf_Export --outdir ' +
    AddQuotes(Scratch) + ' ' + AddQuotes(Sample);
  PreviousBytecode := GetEnv('PYTHONDONTWRITEBYTECODE');
  if not SetEnvironmentVariableW('PYTHONDONTWRITEBYTECODE', '1') then
    Exit;
  try
    if Exec(AddBackslash(Root) + 'program\soffice.com', RunParams,
        ExpandConstant('{sys}'), SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0) and
        LoadStringFromFile(Output, PDF) then
      Result := (Length(PDF) > 64) and (Copy(PDF, 1, 5) = '%PDF-');
  finally
    SetEnvironmentVariableW('PYTHONDONTWRITEBYTECODE', PreviousBytecode);
  end;
end;

function PruneOfficeUi(Root: String): Boolean;
var
  Rows: TArrayOfString;
  Row, Relative, PathName, Directory, LastDir: String;
  Index, Delimiter, Size: Integer;
  Found: TFindRec;
begin
  Result := False;
  if not SafeLocalDirectory(Root) then
    Exit;
  ExtractTemporaryFile('libreoffice-ui-resources.txt');
  if not LoadStringsFromFile(ExpandConstant('{tmp}\libreoffice-ui-resources.txt'), Rows) or
    (GetArrayLength(Rows) <> {#OfficeRemoveCount}) then
    Exit;
  LastDir := '';
  for Index := 0 to GetArrayLength(Rows) - 1 do
  begin
    Row := Rows[Index];
    Delimiter := Pos('|', Row);
    Relative := Copy(Row, 1, Delimiter - 1);
    Size := StrToIntDef(Copy(Row, Delimiter + 1, Length(Row)), 0);
    if (Size <= 0) or (Pos('program/resource/', Relative) <> 1) or
      (Pos('/LC_MESSAGES/', Relative) = 0) or (ExtractFileExt(Relative) <> '.mo') or
      (Pos('..', Relative) <> 0) or (Pos(':', Relative) <> 0) or (Pos('\', Relative) <> 0) then
      Exit;
    StringChangeEx(Relative, '/', '\', True);
    PathName := AddBackslash(Root) + Relative;
    Directory := ExtractFileDir(PathName);
    if Directory <> LastDir then
    begin
      if not SafeLocalDirectory(Directory) then
        Exit;
      LastDir := Directory;
    end;
    if not FindFirst(PathName, Found) then
      Exit;
    try
      if ((Found.Attributes and ($400 or $10)) <> 0) or
        (Found.SizeHigh <> 0) or (Found.SizeLow <> Size) then
        Exit;
    finally
      FindClose(Found);
    end;
    if not DeleteFile(PathName) then
      Exit;
  end;
  Result := True;
end;

procedure PrepareOffice;
var
  ImageRoot, Package, Params: String;
  Code: Integer;
  Cancelled: Boolean;
  StartedAt: UInt64;
begin
  OfficeStatus := CustomMessage('OfficeMissing');
  if HasCompatibleOffice then
  begin
    Log(CustomMessage('OfficeReused'));
    OfficeStatus := '';
    Exit;
  end;
  if OfflineInstall then
    Exit;
  if Length(ExpandConstant('{tmp}')) > 120 then
  begin
    OfficeStatus := CustomMessage('OfficePath');
    Exit;
  end;
  if not SpaceAvailable(True, False) then
  begin
    OfficeStatus := CustomMessage('OfficeSpace');
    Exit;
  end;
  if not FetchPackage(CustomMessage('OfficeTitle'), 'LibreOffice {#OfficeEngine}', '{#OfficeURL}', '{#OfficeMSI}',
      '{#OfficeSHA}', '{#OfficeSigner}', Cancelled) then
  begin
    if Cancelled then
      OfficeStatus := CustomMessage('OfficeCancelled');
    Exit;
  end;
  ImageRoot := ExpandConstant('{tmp}\lo-image');
  if not SafeLocalDirectory(ImageRoot) or DirExists(ImageRoot) then
    Exit;
  if not CreateDir(ImageRoot) then
    Exit;
  OfficeImageOwned := True;
  Package := ExpandConstant('{tmp}\{#OfficeMSI}');
  Params := '/a ' + AddQuotes(Package) + ' /qn /norestart TARGETDIR=' + AddQuotes(ImageRoot)
    + ' /L* ' + AddQuotes(ExpandConstant('{tmp}\LibreOffice-Admin.log'));
  ShowActivity(CustomMessage('ExpandOffice'));
  StartedAt := GetTickCount64;
  try
    if Exec(ExpandConstant('{sys}\msiexec.exe'), Params, ExpandConstant('{sys}'),
      SW_HIDE, ewWaitUntilTerminated, Code) then
    begin
      Log(Format('Imagem administrativa LibreOffice: código %d em %d ms.', [Code, GetTickCount64 - StartedAt]));
      if (Code = 0) and VerifiedOffice(ImageRoot) then
      begin
        ActivityPage.SetText(CustomMessage('ReduceOffice'), '');
        if PruneOfficeUi(ImageRoot) then
        begin
          ActivityPage.SetText(CustomMessage('VerifyOffice'), '');
          OfficePrepared := SmokeOffice(ImageRoot);
        end
        else
          Log('O conteúdo extraído não corresponde ao catálogo de traduções do MSI.');
      end;
      if OfficePrepared then
        OfficeStatus := ''
      else if Code = 1602 then
        OfficeStatus := CustomMessage('OfficeCancelled');
    end;
  finally
    ActivityPage.Hide;
  end;
end;

procedure CleanOfficeScratch(PathName: String);
begin
  if not SafeLocalDirectory(PathName) or not DirExists(PathName) then
    Exit;
  if not DelTree('\\?\' + PathName, True, True, True) then
    Log('A limpeza de uma pasta temporária do LibreOffice ficou incompleta.');
end;

procedure DeinitializeSetup;
begin
  if OfficeProbeOwned then
    CleanOfficeScratch(ExpandConstant('{tmp}\lo-test'));
  if OfficeImageOwned then
    CleanOfficeScratch(ExpandConstant('{tmp}\lo-image'));
end;

function CopyPreparedOffice: Boolean;
begin
  Result := OfficePrepared;
end;

procedure ShowInstallStage(Text: String);
begin
  InstallProgress.Position := InstallCompleted;
  InstallStageLabel.Caption := Text;
  InstallStepsLabel.Caption := FmtMessage(CustomMessage('ProgressSteps'), [
    IntToStr(InstallCompleted), IntToStr(InstallStageCount)]);
  Log(Text);
end;

procedure CoreFilesDone;
begin
  InstallCompleted := 1;
  if not OfficePrepared then
    ShowInstallStage(CustomMessage('Finalizing'));
end;

procedure BeginOfficeCopy;
begin
  ShowInstallStage(CustomMessage('OfficeFiles'));
end;

procedure OfficeCopyDone;
begin
  InstallCompleted := 2;
  ShowInstallStage(CustomMessage('Finalizing'));
end;

procedure CheckForComponentUpdates;
var
  ApplicationPath: String;
  Code: Integer;
begin
  if OfflineInstall then
  begin
    Log('Consulta online desativada pela opção /OFFLINE.');
    Exit;
  end;
  ApplicationPath := ExpandConstant('{app}\{#VariantDir}\EduDownloader.exe');
  if not FileExists(ApplicationPath) or ((GetFileAttributesW(ApplicationPath) and $400) <> 0) or
    (CompareText(GetSHA256OfFile(ApplicationPath), '{#AppExecutableSHA}') <> 0) then
    Exit;
  ShowInstallStage(CustomMessage('CheckUpdates'));
  if ExecAsOriginalUser(ApplicationPath, '--setup-component-updates', ExpandConstant('{sys}'),
     SW_HIDE, ewWaitUntilTerminated, Code) then
    Log('Consulta de componentes terminou com código ' + IntToStr(Code))
  else
    Log('Consulta de componentes indisponível, serão usadas as cópias verificadas.');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Consistent, NeedsVC: Boolean;
begin
  OfficePrepared := False;
  OfficeStatus := '';
  Result := DestinationError;
  if Result <> '' then
    Exit;
  ShowActivity(CustomMessage('VerifyRequirements'));
  try
    NeedsVC := not CompatibleVC(Consistent) and Consistent;
    if not SpaceAvailable(False, False) then
      Result := CustomMessage('CoreSpace')
    else if NeedsVC and not SpaceAvailable(False, True) then
      Result := CustomMessage('VcSpace');
  finally
    ActivityPage.Hide;
  end;
  if Result <> '' then
    Exit;
  Result := PrepareVC(NeedsRestart);
  if Result <> '' then
    Exit;
  if WizardIsComponentSelected('libreoffice') then
  begin
    try
      PrepareOffice;
    except
      OfficePrepared := False;
      OfficeStatus := CustomMessage('OfficeMissing');
      Log('Preparação opcional interrompida: ' + GetExceptionMessage);
    end;
    Log(OfficeStatus);
  end;
end;

function NeedRestart: Boolean;
begin
  Result := RestartAfterSetup;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  LegacyGroup, NewGroup: String;
begin
  if CurStep = ssInstall then
  begin
    InstallStageCount := 2;
    if OfficePrepared then
      InstallStageCount := 3;
    InstallCompleted := 0;
    InstallProgress.Max := InstallStageCount;
    ShowInstallStage(CustomMessage('CoreFiles'));
  end
  else if CurStep = ssPostInstall then
  begin
    ShowInstallStage(CustomMessage('CheckInstalled'));
    if OfficePrepared and not VerifiedOffice(ExpandConstant('{app}\{#OfficeDir}')) then
    begin
      OfficeStatus := CustomMessage('OfficeMissing');
      Log('A verificação do LibreOffice copiado falhou.');
    end;
    CheckForComponentUpdates;
    ShowInstallStage(CustomMessage('Finalizing'));
    RemoveLegacyShortcut(
      ExpandConstant('{autodesktop}\EduDownloader Community.lnk'),
      ExpandConstant('{autodesktop}\EduDownloader.lnk'));
    LegacyGroup := ExpandConstant('{autoprograms}\EduDownloader Community');
    NewGroup := ExpandConstant('{autoprograms}\EduDownloader');
    if RemoveLegacyShortcut(AddBackslash(LegacyGroup) + 'EduDownloader Community.lnk',
      AddBackslash(NewGroup) + 'EduDownloader.lnk') then
      RemoveDir(LegacyGroup);
    InstallCompleted := InstallStageCount;
    ShowInstallStage(CustomMessage('Finished'));
    InstallActivity.Visible := False;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Consistent: Boolean;
begin
  if (CurPageID = wpSelectComponents) and (SpaceCheckedAt <> WizardDirValue) then
  begin
    SpaceCheckedAt := WizardDirValue;
    ShowActivity(CustomMessage('CheckComponents'));
    try
      SpaceOfficeReused := HasCompatibleOffice;
      SpaceNeedsVC := not CompatibleVC(Consistent) and Consistent;
      RefreshSpace(WizardForm);
    finally
      ActivityPage.Hide;
    end;
  end;
  if CurPageID = wpFinished then
  begin
    FinishedOfficeLabel.Caption := OfficeStatus;
    FinishedOfficeLabel.Visible := OfficeStatus <> '';
  end;
end;

procedure InitializeUninstallProgressForm;
var
  Dialog: TSetupForm;
  Details: TNewStaticText;
  Settings: TNewCheckBox;
  ContinueButton: TNewButton;
begin
  if UninstallSilent or IsAdminInstallMode then
    Exit;
  Dialog := CreateCustomForm(ScaleX(416), ScaleY(162), True, True);
  try
    Dialog.Caption := CustomMessage('UninstallOptions');
    Dialog.Position := poScreenCenter;
    Details := TNewStaticText.Create(Dialog);
    Details.Parent := Dialog;
    Details.AutoSize := False;
    Details.WordWrap := True;
    Details.SetBounds(ScaleX(16), ScaleY(16), Dialog.ClientWidth - ScaleX(32), ScaleY(50));
    Details.Caption := CustomMessage('UninstallDetails');
    Settings := TNewCheckBox.Create(Dialog);
    Settings.Parent := Dialog;
    Settings.SetBounds(ScaleX(16), ScaleY(76), Dialog.ClientWidth - ScaleX(32), ScaleY(24));
    Settings.Caption := CustomMessage('UninstallSettings');
    Settings.Checked := False;
    ContinueButton := TNewButton.Create(Dialog);
    ContinueButton.Parent := Dialog;
    ContinueButton.SetBounds(Dialog.ClientWidth - ScaleX(115), ScaleY(116), ScaleX(99), ScaleY(29));
    ContinueButton.Caption := CustomMessage('UninstallContinue');
    ContinueButton.Default := True;
    ContinueButton.ModalResult := mrOk;
    RemoveUserSettings := (Dialog.ShowModal = mrOk) and Settings.Checked;
  finally
    Dialog.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Menu, Link, ApplicationPath, Args: String;
  Code: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Menu := ExpandConstant('{autoprograms}\EduDownloader');
  Link := AddBackslash(Menu) + 'EduDownloader.lnk';
  if OwnedShortcut(Link) and DeleteFile(Link) then
    RemoveDir(Menu);
  Link := ExpandConstant('{autodesktop}\EduDownloader.lnk');
  if OwnedShortcut(Link) then
    DeleteFile(Link);
  if IsAdminInstallMode then
  begin
    Log('Instalação para todos: dados de perfis do Windows preservados.');
    Exit;
  end;
  ApplicationPath := ExpandConstant('{app}\{#VariantDir}\EduDownloader.exe');
  Args := '--uninstall-user-components';
  if RemoveUserSettings then
    Args := '--uninstall-user-data';
  if not SafeLocalDirectory(ExtractFileDir(ApplicationPath)) or
    not FileExists(ApplicationPath) or ((GetFileAttributesW(ApplicationPath) and $400) <> 0) or
    (CompareText(GetSHA256OfFile(ApplicationPath), '{#AppExecutableSHA}') <> 0) or
    not Exec(ApplicationPath, Args, ExpandConstant('{sys}'), SW_HIDE, ewWaitUntilTerminated, Code) or
    (Code <> 0) then
  begin
    Log('A limpeza restrita aos dados gerenciados deste perfil não pôde ser concluída.');
    if not UninstallSilent then
      SuppressibleMsgBox(CustomMessage('UninstallDataFailure'), mbInformation, MB_OK, IDOK);
  end;
end;

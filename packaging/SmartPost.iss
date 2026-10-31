#define MyAppName "SmartPost"
#ifndef MyAppVersion
  #define MyAppVersion "3.0.1"
#endif
#define MyAppPublisher "SmartPost"
#define MyAppExeName "SmartPost.exe"

[Setup]
AppId={{A18AF7C6-0CA7-4A48-9A5E-CB5178EEA458}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SmartPost
DefaultGroupName=SmartPost
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist-installer
OutputBaseFilename=SmartPost_Instalador
SetupIconFile=..\assets\smartpost.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
MinVersion=10.0

[Files]
Source: "..\dist\SmartPost\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\INSTRUCTIVO_USUARIO.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SmartPost"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; AppUserModelID: "SmartPost.Desktop"
Name: "{autodesktop}\SmartPost"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; AppUserModelID: "SmartPost.Desktop"
Name: "{autoprograms}\SmartPost - Guía rápida"; Filename: "{app}\docs\INSTRUCTIVO_USUARIO.pdf"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir SmartPost"; Flags: nowait postinstall skipifsilent

[Code]
function ExcelRegistered(): Boolean;
var
  Value: String;
begin
  Result := RegQueryStringValue(HKCR, 'Excel.Application\CLSID', '', Value);
  if not Result then
    Result := RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\App Paths\excel.exe', '', Value);
  if not Result then
    Result := RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\App Paths\excel.exe', '', Value);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not ExcelRegistered() and not WizardSilent() then
  begin
    MsgBox(
      'SmartPost se puede instalar, pero no se detectó Microsoft Excel de escritorio.' + #13#10 + #13#10 +
      'Excel es necesario para generar los reportes oficiales. Podés continuar la instalación y luego instalar/activar Excel.',
      mbInformation, MB_OK
    );
  end;
end;

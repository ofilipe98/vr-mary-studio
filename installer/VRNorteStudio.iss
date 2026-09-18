#define MyAppName "VR Norte Studio"
#define MyAppVersion "0.6.5"
#define MyAppPublisher "VRNorte"
#define MyAppExeName "VRNorteStudio.exe"

[Setup]
AppId={{88340B2C-B18C-4A09-9F01-82D0DC28E1BD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VR Norte Studio
DefaultGroupName=VR Norte Studio
OutputDir=..\releases
OutputBaseFilename=VRNorteStudio-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\vrsoft_extractor\mary\assets\vrnorte-app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Files]
Source: "..\dist\VRNorteStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\VR Norte Studio"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\VR Norte Studio"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir VR Norte Studio"; Flags: nowait postinstall skipifsilent

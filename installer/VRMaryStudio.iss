#define MyAppName "VR Mary Studio"
#define MyAppVersion "0.3.5"
#define MyAppPublisher "VR Soft"
#define MyAppExeName "VRMaryStudio.exe"

[Setup]
AppId={{88340B2C-B18C-4A09-9F01-82D0DC28E1BD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VR Mary Studio
DefaultGroupName=VR Mary Studio
OutputDir=..\releases
OutputBaseFilename=VRMaryStudio-0.3.5-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Files]
Source: "..\dist\VRMaryStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\VR Mary Studio"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\VR Mary Studio"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir VR Mary Studio"; Flags: nowait postinstall skipifsilent

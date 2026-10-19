#ifndef AppVersion
#define AppVersion "1.0.0"
#endif

#define AppName "WinWhisperPlus Portable"
#define AppExeName "WinWhisperPlus.exe"

[Setup]
AppId={{AAAD844E-F559-4B43-AF17-1CB4A139637C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=orgAnice Lizenz-Verwaltung UG (haftungsbeschränkt)
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=WinWhisperPlus-Portable-Setup-{#AppVersion}
SetupIconFile=..\assets\Microphone.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UsePreviousPrivileges=no
CloseApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\WinWhisperPlus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{userprograms}\{#AppName} Benutzerhandbuch"; Filename: "{app}\_internal\docs\WinWhisperPlus Benutzerhandbuch.pdf"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

; No profile cleanup: ZIP, classic setup and Portable share settings/models.

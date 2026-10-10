#ifndef AppVersion
#define AppVersion "1.0.0"
#endif

#define AppName "WinWhisperPlus"
#define AppPublisher "orgAnice Lizenz-Verwaltung UG (haftungsbeschränkt)"
#define AppExeName "WinWhisperPlus.exe"

[Setup]
AppId={{9FA1E1EE-0815-4F4C-93AC-8A07DCD54C58}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=WinWhisperPlus-Setup
SetupIconFile=..\assets\Microphone.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\WinWhisperPlus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autoprograms}\{#AppName} Benutzerhandbuch"; Filename: "{app}\_internal\docs\WinWhisperPlus Benutzerhandbuch.pdf"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure RemoveDirectoryIfExists(Path: string);
begin
  if DirExists(Path) then
    DelTree(Path, True, True, True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then begin
    if MsgBox('Sollen WinWhisperPlus-Einstellungen, Statistiken und heruntergeladene Whisper-Modelle ebenfalls geloescht werden?', mbConfirmation, MB_YESNO) = IDYES then begin
      RemoveDirectoryIfExists(ExpandConstant('{userappdata}') + '\WinWhisperPlus');
      RemoveDirectoryIfExists(ExpandConstant('{userappdata}') + '\MyWhisper');
      RemoveDirectoryIfExists(ExpandConstant('{localappdata}') + '\WinWhisperPlus');
      RemoveDirectoryIfExists(ExpandConstant('{userprofile}') + '\.cache\whisper');
    end;
  end;
end;

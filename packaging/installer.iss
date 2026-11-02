; Установщик для Windows (Inno Setup 6).
; Сборка: ISCC.exe /DAppVersion=1.0.0 packaging\installer.iss
; Ожидает PyInstaller-сборку в build\pyinstaller\dist\lsb-stego.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{5C7E2A4B-9D1F-4E3A-B8C6-2F1D7A9E4B60}
AppName=LSB-стеганография
AppVersion={#AppVersion}
AppVerName=LSB-стеганография {#AppVersion}
AppPublisher=ScheglyakStas
AppPublisherURL=https://github.com/ScheglyakStas/lsb-stego
DefaultDirName={autopf}\LSB-Stego
DefaultGroupName=LSB-стеганография
UninstallDisplayIcon={app}\lsb-stego.exe
OutputDir=..\dist
OutputBaseFilename=LSB-Stego-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\build\pyinstaller\dist\lsb-stego\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LSB-стеганография"; Filename: "{app}\lsb-stego.exe"
Name: "{group}\{cm:UninstallProgram,LSB-стеганография}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LSB-стеганография"; Filename: "{app}\lsb-stego.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\lsb-stego.exe"; Description: "{cm:LaunchProgram,LSB-стеганография}"; Flags: nowait postinstall skipifsilent

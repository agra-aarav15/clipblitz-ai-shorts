; ClipBlitz Studio - Windows installer (Inno Setup 6)
;
; Compiled in GitHub Actions after the PyInstaller onedir bundle is assembled:
;   ISCC /DVersion=5.4.4 /DSourceDir=<repo>\studio\dist\ClipBlitzStudio /O<repo> ClipBlitzStudio.iss
;
; The installer is per-user on purpose: no admin prompt, no Program Files write,
; and the app's data/ folder stays writable next to the EXE. Everything the app
; needs (CPython, ffmpeg, yt-dlp, web UI, plugin) is already inside SourceDir.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\ClipBlitzStudio"
#endif

[Setup]
AppId={{8E7F1C2A-5B4D-4F3A-9C61-2D8B7A6E4F10}
AppName=ClipBlitz Studio
AppVersion={#Version}
AppVerName=ClipBlitz Studio {#Version}
AppPublisher=ClipBlitz
AppPublisherURL=https://github.com/agra-aarav15/clipblitz-ai-shorts
AppSupportURL=https://github.com/agra-aarav15/clipblitz-ai-shorts/issues
AppUpdatesURL=https://github.com/agra-aarav15/clipblitz-ai-shorts/releases
DefaultDirName={autopf}\ClipBlitz Studio
DefaultGroupName=ClipBlitz Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=ClipBlitzStudio-{#Version}-setup
SetupIconFile={#SourceDir}\assets\ClipBlitzStudio.ico
UninstallDisplayIcon={app}\ClipBlitzStudio.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
MinVersion=10.0.17763
VersionInfoVersion={#Version}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Everything PyInstaller produced, plus web/, bin/, assets/, plugin/ and the docs.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ClipBlitz Studio"; Filename: "{app}\ClipBlitzStudio.exe"; Parameters: "--open"
Name: "{group}\Uninstall ClipBlitz Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ClipBlitz Studio"; Filename: "{app}\ClipBlitzStudio.exe"; Parameters: "--open"; Tasks: desktopicon

[Run]
Filename: "{app}\ClipBlitzStudio.exe"; Parameters: "--open"; Description: "{cm:LaunchProgram,ClipBlitz Studio}"; Flags: nowait postinstall skipifsilent

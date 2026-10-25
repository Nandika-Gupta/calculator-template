; Inno Setup script for the ViralCut Windows installer.
; Build after PyInstaller:  ISCC.exe viralcut\packaging\installer.iss  (VIRALCUT_VERSION env var sets the version)
#define AppVersion GetEnv("VIRALCUT_VERSION")
#if AppVersion == ""
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6E0B7C4E-5B7A-4D2E-9C1B-7A1F2D3C4B5A}
AppName=ViralCut
AppVersion={#AppVersion}
AppVerName=ViralCut {#AppVersion}
AppPublisher=ViralCut
DefaultDirName={localappdata}\Programs\ViralCut
DefaultGroupName=ViralCut
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist_installer
OutputBaseFilename=ViralCut-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\ViralCut.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\ViralCut\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ViralCut"; Filename: "{app}\ViralCut.exe"
Name: "{group}\Uninstall ViralCut"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ViralCut"; Filename: "{app}\ViralCut.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ViralCut.exe"; Description: "Start ViralCut now"; Flags: nowait postinstall skipifsilent

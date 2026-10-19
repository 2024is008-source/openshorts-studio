[Setup]
AppId={{6F62CCED-8032-4DEB-8C31-5951C52C1629}
AppName=OpenShorts
AppVersion=1.1.0
AppPublisher=OpenShorts
DefaultDirName={localappdata}\Programs\OpenShorts
DefaultGroupName=OpenShorts
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=..\..\dist\wpf-installer
OutputBaseFilename=OpenShorts-Setup
SetupIconFile=..\..\assets\desktop.ico
UninstallDisplayIcon={app}\OpenShorts.Desktop.exe
Compression=lzma2/fast
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=2000000000
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\..\LICENSE
VersionInfoVersion=1.1.0
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "..\..\dist\wpf\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\OpenShorts"; Filename: "{app}\OpenShorts.Desktop.exe"
Name: "{autodesktop}\OpenShorts"; Filename: "{app}\OpenShorts.Desktop.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\OpenShorts.Desktop.exe"; Description: "Launch OpenShorts"; Flags: nowait postinstall skipifsilent
; AppData and user projects are preserved. No cleanup of the previous shell
; until feature parity and upgrade testing approve migration completion.

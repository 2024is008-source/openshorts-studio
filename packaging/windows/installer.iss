#define AppVersion "1.0.0"
[Setup]
AppId={{6F62CCED-8032-4DEB-8C31-5951C52C1629}
AppName=OpenShorts
AppVersion={#AppVersion}
AppPublisher=OpenShorts
DefaultDirName={localappdata}\Programs\OpenShorts
DefaultGroupName=OpenShorts
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\..\dist\installer
OutputBaseFilename=OpenShorts-Setup
SetupIconFile=..\..\build\desktop-resources\openshorts.ico
UninstallDisplayIcon={app}\OpenShorts.exe
Compression=lzma2/fast
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=2000000000
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\..\LICENSE
VersionInfoVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\OpenShorts\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OpenShorts"; Filename: "{app}\OpenShorts.exe"
Name: "{autodesktop}\OpenShorts"; Filename: "{app}\OpenShorts.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OpenShorts.exe"; Description: "Launch OpenShorts"; Flags: nowait postinstall skipifsilent

; No AppData deletion: projects and credentials survive upgrades/uninstall.

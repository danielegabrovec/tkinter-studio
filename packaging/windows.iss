#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#ifndef PayloadDir
  #define PayloadDir SourcePath + "..\dist\TkinterStudio"
#endif
#ifndef ReleaseDir
  #define ReleaseDir SourcePath + "..\dist"
#endif
[Setup]
AppId={{9B701867-7768-433A-995B-6E5F5149EB80}
AppName=Tkinter Studio
AppVersion={#AppVersion}
AppPublisher=Daniele Gabrovec
AppPublisherURL=https://github.com/danielegabrovec/tkinter-studio
DefaultDirName={localappdata}\Programs\TkinterStudio
DefaultGroupName=Tkinter Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#ReleaseDir}
OutputBaseFilename=TkinterStudio-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\python\pythonw.exe
DisableProgramGroupPage=yes
CloseApplications=yes
[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul desktop"; Flags: unchecked
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Tkinter Studio"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"
Name: "{autodesktop}\Tkinter Studio"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Tasks: desktopicon
[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "Avvia Tkinter Studio"; Flags: nowait postinstall skipifsilent unchecked

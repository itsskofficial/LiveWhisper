; LiveWhisper installer (Inno Setup 6).
;
;   packaging\build.py builds the app folder with PyInstaller, then runs:
;   ISCC.exe /DAppVersion=1.0.0 packaging\installer.iss
;
; Per-user install: no administrator prompt, installs to
; %LOCALAPPDATA%\Programs\LiveWhisper. Models and settings are not in here -
; the app downloads models on first launch (%LOCALAPPDATA%\LiveWhisper) and
; keeps settings in %APPDATA%\LiveWhisper. Uninstall offers to remove both.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "LiveWhisper"
#define AppExe "LiveWhisper.exe"
#define Dist "..\build\dist\LiveWhisper"

[Setup]
AppId={{6F2C9D4E-4B1A-4C7B-9E1F-6A2B7C3D4E5F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=LiveWhisper
AppPublisherURL=https://github.com/itsskofficial/LiveWhisper
AppSupportURL=https://github.com/itsskofficial/LiveWhisper/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\build\installer
OutputBaseFilename=LiveWhisper-Setup-{#AppVersion}
SetupIconFile=..\assets\livewhisper.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
WizardSizePercent=110
AppMutex=LiveWhisper.Running
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start LiveWhisper when I sign in (recommended)"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#Dist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; The same entry the app's own "Start with Windows" switch writes.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "LiveWhisper"; ValueData: """{app}\{#AppExe}"" --background"; \
  Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open LiveWhisper"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM llama-server.exe"; Flags: runhidden; RunOnceId: "KillRunner"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
const
  WebView2Key = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2UserKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Url = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';

function WebView2Installed: Boolean;
var
  Version: String;
begin
  Result := (RegQueryStringValue(HKLM, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'))
    or (RegQueryStringValue(HKCU, WebView2UserKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

{ The app window is drawn by Microsoft's WebView2, part of every Windows 11 and
  of Windows 10 since 2021. On the rare machine without it, fetch Microsoft's
  own small bootstrapper and let it install the runtime. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if (CurStep = ssPostInstall) and not WebView2Installed then
  begin
    try
      WizardForm.StatusLabel.Caption := 'Installing Microsoft Edge WebView2...';
      DownloadTemporaryFile(WebView2Url, 'MicrosoftEdgeWebview2Setup.exe', '', nil);
      Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
           SW_HIDE, ewWaitUntilTerminated, Code);
    except
      MsgBox('LiveWhisper needs Microsoft Edge WebView2, which could not be installed ' +
             'automatically. Install it from https://developer.microsoft.com/microsoft-edge/webview2/ ' +
             'and LiveWhisper will open normally.', mbInformation, MB_OK);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    if MsgBox('Also delete your LiveWhisper settings, history and downloaded models?' + #13#10 + #13#10 +
              'The models can take several gigabytes. Choose No to keep them for a reinstall.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{userappdata}\LiveWhisper'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\LiveWhisper'), True, True, True);
    end;
  end;
end;

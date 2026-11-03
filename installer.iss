; Canonical installer for NeDotify. The PyInstaller GUI-installer pipeline
; (build_installer.py / installer_gui.py / uninstaller_gui.py) is gone: it
; emitted three byte-identical setup exes plus a second, competing uninstaller.
; Build order: pyinstaller setup_pyinstaller.spec  ->  dist\NeDotify.exe
;               iscc installer.iss                   ->  dist\NeDotify_Setup.exe
[Setup]
AppId={{8F56F2A1-90E1-4A0A-AB89-24A326E6D371}
AppName=NeDotify
AppVersion=2.5.1
AppPublisher=The pAura Team
AppCopyright=Copyright (C) 2024 The pAura Team
DefaultDirName={localappdata}\Programs\NeDotify
DefaultGroupName=NeDotify
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=NeDotify_Setup
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=no
WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
DisableReadyPage=no
UninstallDisplayName=NeDotify 2.5.1
UninstallDisplayIcon={app}\NeDotify.exe
CreateUninstallRegKey=yes
CloseApplications=yes
; Shares this static session-scoped mutex with the app. The app also owns a
; separate profile-derived mutex for single-instance-per-user behavior.
AppMutex=Local\NeDotify_Installer_Guard
RestartIfNeededByRun=no
#ifdef NEDOTIFY_RELEASE_SIGNING
; Release signing is opt-in: sign_release.ps1 provides this tool only when a
; user's valid code-signing certificate and timestamp service are configured.
SignTool=NeDotifyRelease
SignedUninstaller=yes
#endif

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

; ─── Optional Zapret bundle (BUG-001, installer half) ──────────────────────
; When a verified zapret bundle is staged next to the build as
; dist\zapret\winws.exe (+ its WinDivert DLLs/driver), it is installed into
; {app}\zapret — the directory services/zapret_service.py::find_binary scans
; in a frozen build (base_dir = the folder holding NeDotify.exe) and the only
; location the elevation gate (_protected_elevation_path → Inno
; InstallLocation) accepts outside Program Files. This closes the installer
; half of BUG-001 WITHOUT breaking builds that do not ship the bundle: the
; #if guard skips the entry entirely, and the app falls back to downloading
; the SHA-256-pinned archive into ~/.nedotify/zapret at runtime (that
; location stays forbidden for elevation by design — user-writable storage).
; SHIPPED-BINARY POLICY (deliberate decision, not an oversight): upstream
; bol-van/zapret is MIT-licensed, but redistributing third-party binaries
; inside the installer (hash pinning of the *bundle*, review, update path)
; is a release decision that must be made consciously. Until that decision
; is taken, dist\zapret\ does not exist and this block compiles to nothing.
#define ZapretBundleWinws SourcePath + "\dist\zapret\winws.exe"
#if FileExists(ZapretBundleWinws)
#define ZapretBundleReady 1
#endif

[Tasks]
; No "Flags: checked" here: Inno Setup 6 rejects it as an unknown flag and
; aborts the compile ("Parameter Flags includes an unknown flag", [Tasks]
; supports only checkablealone/checkedonce/dontinheritcheck/exclusive/restart/
; unchecked). Tasks are checked by default; only "unchecked" opts out.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenuicon"; Description: "{cm:StartMenuIconTask}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutostartTask}"; GroupDescription: "{cm:AutostartGroup}"; Flags: unchecked

[Files]
Source: "dist\NeDotify.exe"; DestDir: "{app}"; DestName: "NeDotify.exe"; Flags: ignoreversion
Source: "dist\ffprobe.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
#ifdef ZapretBundleReady
; Staged zapret bundle (see the policy note above the #define): installed
; into {app}\zapret where find_binary() and the elevation gate accept it.
Source: "dist\zapret\*"; DestDir: "{app}\zapret"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{group}\NeDotify"; Filename: "{app}\NeDotify.exe"; Comment: "NeDotify — Музыкальный плеер"
Name: "{group}\Удалить NeDotify"; Filename: "{uninstallexe}"
Name: "{autodesktop}\NeDotify"; Filename: "{app}\NeDotify.exe"; Comment: "NeDotify — Музыкальный плеер"; Tasks: desktopicon
Name: "{userstartmenu}\NeDotify"; Filename: "{app}\NeDotify.exe"; Comment: "NeDotify — Музыкальный плеер"; Tasks: startmenuicon

[Registry]
; Autostart value name: "NeDotify" is the single source of truth
; core/api.py::AUTOSTART_RUN_VALUE (core/api.py::update_autostart writes the
; exact same hive/key/name). Inno Setup cannot read a Python constant, so the
; literal is duplicated here and kept honest by
; tests/test_build_and_brand.py::test_installer_and_api_share_run_value_name.
; Both sides must stay on HKCU, or Windows keeps two independent Run entries.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "NeDotify"; ValueData: """{app}\NeDotify.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\NeDotify.exe"; Description: "{cm:LaunchProgram,NeDotify}"; Flags: nowait postinstall skipifsilent

[CustomMessages]
russian.StartMenuIconTask=Добавить ярлык в меню «Пуск»
english.StartMenuIconTask=Add a Start Menu shortcut
russian.AutostartTask=Запускать NeDotify при запуске Windows
english.AutostartTask=Start NeDotify when Windows starts
russian.AutostartGroup=Автозапуск:
english.AutostartGroup=Startup:
russian.WelcomeBody=Добро пожаловать в установщик NeDotify 2.5.1.%n%nNeDotify — современный музыкальный плеер с поддержкой онлайн-сервисов, тем и горячих клавиш.%n%nНажмите «Далее», чтобы продолжить, или «Отмена», чтобы выйти.
english.WelcomeBody=Welcome to the NeDotify 2.5.1 setup.%n%nNeDotify is a modern music player with online services, themes, and keyboard shortcuts.%n%nClick Next to continue, or Cancel to exit.

[Code]
const
  WV2_CLIENT_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WV2_BOOTSTRAP_URL = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';

function IsWebView2Installed(): Boolean;
var
  Version: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WV2_CLIENT_GUID, 'pv', Version) then
  begin
    if (Version <> '') and (Version <> '0.0.0.0') then
    begin
      Result := True;
      Exit;
    end;
  end;
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WV2_CLIENT_GUID, 'pv', Version) then
  begin
    if (Version <> '') and (Version <> '0.0.0.0') then
    begin
      Result := True;
      Exit;
    end;
  end;
  if RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WV2_CLIENT_GUID, 'pv', Version) then
  begin
    if (Version <> '') and (Version <> '0.0.0.0') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function InstallWebView2(): Boolean;
var
  InstallerPath: String;
  DownloadCmd: String;
  ResultCode: Integer;
begin
  Result := True;
  if IsWebView2Installed() then
    Exit;

  InstallerPath := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
  DownloadCmd := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ' +
    '"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ' +
    '(New-Object System.Net.WebClient).DownloadFile('''' + WV2_BOOTSTRAP_URL + '''', '''' + InstallerPath + '''')"';

  Log('WebView2 runtime not detected. Downloading Evergreen bootstrapper...');
  if not Exec('powershell.exe', DownloadCmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) or not FileExists(InstallerPath) then
  begin
    Log('Failed to download WebView2 bootstrapper via PowerShell.');
    Result := False;
    Exit;
  end;

  Log('Installing WebView2 runtime via MicrosoftEdgeWebview2Setup.exe /silent /install...');
  if not Exec(InstallerPath, '/silent /install', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    Log('WebView2 bootstrapper execution failed with code ' + IntToStr(ResultCode));
    Result := False;
    Exit;
  end;

  Result := IsWebView2Installed();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not IsWebView2Installed() then
  begin
    if not InstallWebView2() then
    begin
      Log('WebView2 runtime installation could not be completed.');
    end;
  end;
end;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption := ExpandConstant('{cm:WelcomeBody}');
end;

// Drop the Run value written by pre-NeDotify builds ("AURA Music").
// core/api.py::update_autostart also clears it, but only when the user
// touches the autostart toggle; without this the stale entry survives the
// upgrade and Windows tries to launch a path that no longer exists at logon.
procedure RemoveLegacyAutostart();
begin
  RegDeleteValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Run',
    'AURA Music');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RemoveLegacyAutostart();
end;

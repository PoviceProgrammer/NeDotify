; Canonical installer for NeDotify. The PyInstaller GUI-installer pipeline
; (build_installer.py / installer_gui.py / uninstaller_gui.py) is gone: it
; emitted three byte-identical setup exes plus a second, competing uninstaller.
; Build order: pyinstaller setup_pyinstaller.spec  ->  dist\NeDotify.exe
;               iscc installer.iss                   ->  dist\NeDotify_Setup.exe
[Setup]
AppName=NeDotify
AppVersion=5.0 Beta
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
UninstallDisplayName=NeDotify Beta 5
UninstallDisplayIcon={app}\NeDotify.exe
CreateUninstallRegKey=yes
CloseApplications=yes
RestartIfNeededByRun=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checked
Name: "startmenuicon"; Description: "Добавить ярлык в меню «Пуск»"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checked
Name: "autostart"; Description: "Запускать NeDotify при запуске Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Files]
Source: "dist\NeDotify.exe"; DestDir: "{app}"; DestName: "NeDotify.exe"; Flags: ignoreversion

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

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'Добро пожаловать в установщик NeDotify Beta 5.' + #13#10 + #13#10 +
    'NeDotify — современный музыкальный плеер с поддержкой' + #13#10 +
    'онлайн-сервисов, тем и горячих клавиш.' + #13#10 + #13#10 +
    'Нажмите «Далее», чтобы продолжить, или «Отмена», чтобы выйти.';
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

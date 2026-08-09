[Setup]
AppName=NeDotify
AppVersion=5.0 Beta
AppPublisher=The pAura Team
AppCopyright=Copyright (C) 2024 The pAura Team
DefaultDirName={localappdata}\Programs\NeDotify
DefaultGroupName=NeDotify
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=Beta5_Setup
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
Source: "dist\Beta_NeDotify.exe"; DestDir: "{app}"; DestName: "NeDotify.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\NeDotify"; Filename: "{app}\NeDotify.exe"; Comment: "NeDotify — Музыкальный плеер"
Name: "{group}\Удалить NeDotify"; Filename: "{uninstallexe}"
Name: "{autodesktop}\NeDotify"; Filename: "{app}\NeDotify.exe"; Comment: "NeDotify — Музыкальный плеер"; Tasks: desktopicon
Name: "{userstartmenu}\NeDotify"; Filename: "{app}\NeDotify.exe"; Comment: "NeDotify — Музыкальный плеер"; Tasks: startmenuicon

[Registry]
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

#define MyAppName "AIPacs"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\output\stage"
#endif
#ifndef InstallerOutputDir
  #define InstallerOutputDir "..\output\installer"
#endif

[Setup]
AppId={{2D6A29F1-11CF-4A1B-9C3A-0D6B14661E65}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename=AIPacs_{#MyAppVersion}_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
DisableReadyMemo=no
SetupIconFile=..\..\Qss\images\favicon.ico
LicenseFile=..\..\LICENSE
UninstallDisplayIcon={app}\AIPacs.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "core"; Description: "Core workstation platform"

[Components]
Name: "core"; Description: "Core platform"; Types: core; Flags: fixed

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
Name: "{localappdata}\AIPacs\user_data"; Permissions: users-modify
Name: "{userappdata}\AIPacs\config"; Permissions: users-modify

[Files]
Source: "{#StageDir}\core\*"; DestDir: "{app}"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\AIPacs.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\AIPacs.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AIPacs.exe"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  GpuPage: TWizardPage;
  GpuCheckBox: TNewCheckBox;
  GpuHintLabel: TNewStaticText;

function BoolToJson(Value: Boolean): String;
begin
  if Value then
    Result := 'true'
  else
    Result := 'false';
end;

function GraphicsModeValue(): String;
begin
  if GpuCheckBox.Checked then
    Result := 'prefer_gpu'
  else
    Result := 'cpu_safe';
end;

function InternalConfigDir(): String;
begin
  if DirExists(ExpandConstant('{app}\_internal\config')) then
    Result := ExpandConstant('{app}\_internal\config')
  else
    Result := ExpandConstant('{app}\config');
end;

procedure InitializeWizard();
begin
  GpuPage := CreateCustomPage(
    wpSelectComponents,
    'Graphics Acceleration',
    'Choose whether this workstation should prefer GPU acceleration.'
  );

  GpuCheckBox := TNewCheckBox.Create(GpuPage.Surface);
  GpuCheckBox.Parent := GpuPage.Surface;
  GpuCheckBox.Left := ScaleX(0);
  GpuCheckBox.Top := ScaleY(8);
  GpuCheckBox.Width := GpuPage.SurfaceWidth;
  GpuCheckBox.Caption := 'This workstation has a compatible GPU and should prefer GPU acceleration';
  GpuCheckBox.Checked := False;

  GpuHintLabel := TNewStaticText.Create(GpuPage.Surface);
  GpuHintLabel.Parent := GpuPage.Surface;
  GpuHintLabel.Left := ScaleX(0);
  GpuHintLabel.Top := ScaleY(36);
  GpuHintLabel.Width := GpuPage.SurfaceWidth;
  GpuHintLabel.Height := ScaleY(64);
  GpuHintLabel.AutoSize := False;
  GpuHintLabel.WordWrap := True;
  GpuHintLabel.Caption :=
    'When enabled, AIPacs will probe the machine on first launch. ' +
    'If a usable GPU is detected, the viewer will prefer GPU mode; ' +
    'otherwise it will automatically fall back to the current CPU-safe mode. ' +
    'Optional modules are installed later from Settings -> Installation Module.';
end;

procedure WriteInstallationProfile();
var
  ConfigDir: String;
  ProfilePath: String;
  JsonText: String;
begin
  ConfigDir := InternalConfigDir();
  ForceDirectories(ConfigDir);
  ProfilePath := AddBackslash(ConfigDir) + 'installation_profile.json';

  JsonText :=
    '{' + #13#10 +
    '  "app_name": "AIPacs",' + #13#10 +
    '  "generated_at_utc": "",' + #13#10 +
    '  "modules": {' + #13#10 +
    '    "viewer": true,' + #13#10 +
    '    "download_manager": true,' + #13#10 +
    '    "zeta_boost": true,' + #13#10 +
    '    "advanced_mpr": false,' + #13#10 +
    '    "printing": false,' + #13#10 +
    '    "run_cd": false,' + #13#10 +
    '    "web_browser": false,' + #13#10 +
    '    "echomind": false' + #13#10 +
    '  },' + #13#10 +
    '  "module_packages": {' + #13#10 +
    '    "viewer": {"module_id":"viewer","title":"Viewer","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "download_manager": {"module_id":"download_manager","title":"Download Manager","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "zeta_boost": {"module_id":"zeta_boost","title":"ZetaBoost","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "advanced_mpr": {"module_id":"advanced_mpr","title":"Advanced MPR","tier":"optional","package_kind":"runtime_payload","status":"not_installed","installed_from":"","requires_restart":true},' + #13#10 +
    '    "printing": {"module_id":"printing","title":"Printing Module","tier":"optional","package_kind":"bundled_unlock","status":"not_installed","installed_from":"","requires_restart":true},' + #13#10 +
    '    "run_cd": {"module_id":"run_cd","title":"Run CD Module","tier":"optional","package_kind":"bundled_unlock","status":"not_installed","installed_from":"","requires_restart":true},' + #13#10 +
    '    "web_browser": {"module_id":"web_browser","title":"Web Browser Module","tier":"optional","package_kind":"bundled_unlock","status":"not_installed","installed_from":"","requires_restart":true},' + #13#10 +
    '    "echomind": {"module_id":"echomind","title":"EchoMind Module","tier":"optional","package_kind":"bundled_unlock","status":"not_installed","installed_from":"","requires_restart":true}' + #13#10 +
    '  },' + #13#10 +
    '  "graphics": {' + #13#10 +
    '    "user_declared_gpu": ' + BoolToJson(GpuCheckBox.Checked) + ',' + #13#10 +
    '    "preferred_mode": "' + GraphicsModeValue() + '",' + #13#10 +
    '    "last_detected_gpu": false,' + #13#10 +
    '    "last_probe_backend": "",' + #13#10 +
    '    "last_probe_device": "",' + #13#10 +
    '    "last_probe_utc": ""' + #13#10 +
    '  }' + #13#10 +
    '}';

  SaveStringToFile(ProfilePath, JsonText, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteInstallationProfile();
end;

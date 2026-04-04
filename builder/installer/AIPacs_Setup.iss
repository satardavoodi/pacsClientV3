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
#ifndef InstallerBaseName
  #define InstallerBaseName "ai-pacs installer"
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
OutputBaseFilename={#InstallerBaseName}
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
Name: "core"; Description: "Core workstation only (viewer, download manager, education, stitching)"
Name: "custom"; Description: "Choose optional modules for this PC before installation"; Flags: iscustom

[Components]
Name: "core"; Description: "Core platform"; Types: core custom; Flags: fixed
Name: "optional"; Description: "Optional modules copied into the installer bundle for first-launch activation"; Types: custom
Name: "optional\advanced_mpr"; Description: "Advanced MPR (3D reconstruction and bundled Slicer runtime)"; Types: custom
Name: "optional\printing"; Description: "Printing Module (medical print and filming workflows)"; Types: custom
Name: "optional\run_cd"; Description: "Run CD Module (media export and portable delivery workflows)"; Types: custom
Name: "optional\web_browser"; Description: "Web Browser Module (embedded web access inside the workstation)"; Types: custom
Name: "optional\echomind"; Description: "EchoMind Module (assistant and guided workflow features)"; Types: custom

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
Name: "{localappdata}\AIPacs\user_data"; Permissions: users-modify
Name: "{userappdata}\AIPacs\config"; Permissions: users-modify

[Files]
Source: "{#StageDir}\core\*"; DestDir: "{app}"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\plugin_packages\module_package_feed.json"; DestDir: "{app}\module_packages"; Components: core; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\advanced_mpr\*"; DestDir: "{app}\module_packages\advanced_mpr"; Components: optional\advanced_mpr; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\printing\*"; DestDir: "{app}\module_packages\printing"; Components: optional\printing; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\run_cd\*"; DestDir: "{app}\module_packages\run_cd"; Components: optional\run_cd; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\web_browser\*"; DestDir: "{app}\module_packages\web_browser"; Components: optional\web_browser; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\echomind\*"; DestDir: "{app}\module_packages\echomind"; Components: optional\echomind; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

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
  GpuAutoDetected: Boolean;
  GpuDetectionError: String;

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

function OptionalModuleSelected(const ModuleId: String): Boolean;
begin
  Result := WizardIsComponentSelected('optional\' + ModuleId);
end;

function OptionalModuleStatusValue(const ModuleId: String): String;
begin
  if OptionalModuleSelected(ModuleId) then
    Result := 'selected_for_install'
  else
    Result := 'not_installed';
end;

function OptionalModuleSourceValue(const ModuleId: String): String;
begin
  if OptionalModuleSelected(ModuleId) then
    Result := 'bundled_setup_selection'
  else
    Result := '';
end;

function InternalConfigDir(): String;
begin
  if DirExists(ExpandConstant('{app}\_internal\config')) then
    Result := ExpandConstant('{app}\_internal\config')
  else
    Result := ExpandConstant('{app}\config');
end;

function AutoDetectGpuSupport(var ErrorMessage: String): Boolean;
var
  ProbePath: String;
  ProbeCommand: String;
  ResultCode: Integer;
  ProbeOutput: AnsiString;
begin
  Result := False;
  ErrorMessage := '';
  ProbePath := ExpandConstant('{tmp}\aipacs_gpu_probe.txt');

  DeleteFile(ProbePath);

  ProbeCommand :=
    '$ErrorActionPreference=''Stop''; ' +
    '$controllers=Get-CimInstance Win32_VideoController; ' +
    '$hasGpu=$false; ' +
    'foreach($g in $controllers){ ' +
    '  $sig=("$($g.Name) $($g.AdapterCompatibility) $($g.VideoProcessor)").ToLower(); ' +
    '  if($sig -match ''microsoft basic display|basic render|remote display|rdp|citrix|vmware|virtualbox|hyper-v''){ continue }; ' +
    '  if($sig -match ''nvidia|amd|radeon|intel|iris|uhd|arc|geforce|quadro|tesla|rtx''){ $hasGpu=$true; break } ' +
    '}; ' +
    'if($hasGpu){''true''} else {''false''} | Out-File -Encoding ascii -Force ''' + ProbePath + '''';

  if not Exec(
    ExpandConstant('{cmd}'),
    '/C powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "' + ProbeCommand + '"',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
  begin
    ErrorMessage := 'GPU probe failed to start.';
    Exit;
  end;

  if ResultCode <> 0 then
  begin
    ErrorMessage := 'GPU probe command returned a non-zero status.';
    Exit;
  end;

  if not LoadStringFromFile(ProbePath, ProbeOutput) then
  begin
    ErrorMessage := 'GPU probe output is unavailable.';
    Exit;
  end;

  ProbeOutput := Trim(Lowercase(ProbeOutput));
  Result := Pos('true', ProbeOutput) > 0;
end;

function SelectedModulesSummary(): String;
var
  Items: String;
begin
  Items :=
    '  - Core platform (always installed)' + #13#10 +
    '  - Viewer' + #13#10 +
    '  - Download Manager' + #13#10 +
    '  - ZetaBoost' + #13#10 +
    '  - Education Module' + #13#10 +
    '  - Stitching Module' + #13#10;

  if OptionalModuleSelected('advanced_mpr') then Items := Items + '  - Advanced MPR (selected)' + #13#10;
  if OptionalModuleSelected('printing') then Items := Items + '  - Printing Module (selected)' + #13#10;
  if OptionalModuleSelected('run_cd') then Items := Items + '  - Run CD Module (selected)' + #13#10;
  if OptionalModuleSelected('web_browser') then Items := Items + '  - Web Browser Module (selected)' + #13#10;
  if OptionalModuleSelected('echomind') then Items := Items + '  - EchoMind Module (selected)' + #13#10;

  if not OptionalModuleSelected('advanced_mpr') and
     not OptionalModuleSelected('printing') and
     not OptionalModuleSelected('run_cd') and
     not OptionalModuleSelected('web_browser') and
     not OptionalModuleSelected('echomind') then
    Result := Items + '  - No optional modules selected for this PC' + #13#10
  else
    Result := Items;
end;

function UpdateReadyMemo(
  Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String
): String;
var
  GraphicsSummary: String;
begin
  if GpuCheckBox.Checked then
    GraphicsSummary := 'Prefer GPU acceleration'
  else
    GraphicsSummary := 'CPU-safe / software OpenGL fallback';

  Result :=
    MemoDirInfo + NewLine + NewLine +
    MemoTypeInfo + NewLine + NewLine +
    MemoComponentsInfo + NewLine + NewLine +
    MemoTasksInfo + NewLine + NewLine +
    'Graphics Preference:' + NewLine +
    Space + GraphicsSummary + NewLine + NewLine +
    'Optional Modules:' + NewLine +
    SelectedModulesSummary() + NewLine +
    'Install behavior:' + NewLine +
    Space + 'Selected optional modules are copied now and activated on first launch.' + NewLine +
    Space + 'A runtime graphics probe will confirm GPU use and fall back safely if needed.';
end;

procedure InitializeWizard();
begin
  GpuAutoDetected := AutoDetectGpuSupport(GpuDetectionError);

  GpuPage := CreateCustomPage(
    wpSelectComponents,
    'Graphics Acceleration',
    'Choose whether this workstation should prefer GPU acceleration on this PC.'
  );

  GpuCheckBox := TNewCheckBox.Create(GpuPage.Surface);
  GpuCheckBox.Parent := GpuPage.Surface;
  GpuCheckBox.Left := ScaleX(0);
  GpuCheckBox.Top := ScaleY(8);
  GpuCheckBox.Width := GpuPage.SurfaceWidth;
  GpuCheckBox.Caption := 'This workstation has a compatible GPU and should prefer GPU acceleration';
  GpuCheckBox.Checked := GpuAutoDetected;

  GpuHintLabel := TNewStaticText.Create(GpuPage.Surface);
  GpuHintLabel.Parent := GpuPage.Surface;
  GpuHintLabel.Left := ScaleX(0);
  GpuHintLabel.Top := ScaleY(36);
  GpuHintLabel.Width := GpuPage.SurfaceWidth;
  GpuHintLabel.Height := ScaleY(64);
  GpuHintLabel.AutoSize := False;
  GpuHintLabel.WordWrap := True;
  if GpuAutoDetected then
    GpuHintLabel.Caption :=
      'Detected a likely compatible GPU on this workstation. ' +
      'GPU preference has been enabled by default. You can change it now if needed. ' +
      'AIPacs will still probe graphics support at runtime and safely fall back when required.'
  else
    GpuHintLabel.Caption :=
      'No compatible GPU was detected automatically, or detection could not be completed. ' +
      'CPU-safe mode is selected by default. You can enable GPU preference manually if this system has a supported GPU.';

  if GpuDetectionError <> '' then
    GpuHintLabel.Caption :=
      GpuHintLabel.Caption + #13#10 + #13#10 +
      'Detection note: ' + GpuDetectionError;

  GpuHintLabel.Caption :=
    GpuHintLabel.Caption + #13#10 + #13#10 +
    'This setup stores the module choices for this workstation, copies the selected optional packages, ' +
    'and lets AIPacs validate graphics support again on first launch. ' +
    'Other packages can still be installed later from Settings -> Installation Module.';
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
    '    "education": true,' + #13#10 +
    '    "stitching": true,' + #13#10 +
    '    "advanced_mpr": ' + BoolToJson(OptionalModuleSelected('advanced_mpr')) + ',' + #13#10 +
    '    "printing": ' + BoolToJson(OptionalModuleSelected('printing')) + ',' + #13#10 +
    '    "run_cd": ' + BoolToJson(OptionalModuleSelected('run_cd')) + ',' + #13#10 +
    '    "web_browser": ' + BoolToJson(OptionalModuleSelected('web_browser')) + ',' + #13#10 +
    '    "echomind": ' + BoolToJson(OptionalModuleSelected('echomind')) + #13#10 +
    '  },' + #13#10 +
    '  "module_packages": {' + #13#10 +
    '    "viewer": {"module_id":"viewer","title":"Viewer","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "download_manager": {"module_id":"download_manager","title":"Download Manager","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "zeta_boost": {"module_id":"zeta_boost","title":"ZetaBoost","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "education": {"module_id":"education","title":"Education Module","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "stitching": {"module_id":"stitching","title":"Stitching Module","tier":"basic","package_kind":"core","status":"core","installed_from":"core_bundle","requires_restart":false},' + #13#10 +
    '    "advanced_mpr": {"module_id":"advanced_mpr","title":"Advanced MPR","tier":"optional","package_kind":"runtime_payload","status":"' + OptionalModuleStatusValue('advanced_mpr') + '","installed_from":"' + OptionalModuleSourceValue('advanced_mpr') + '","requires_restart":true},' + #13#10 +
    '    "printing": {"module_id":"printing","title":"Printing Module","tier":"optional","package_kind":"bundled_unlock","status":"' + OptionalModuleStatusValue('printing') + '","installed_from":"' + OptionalModuleSourceValue('printing') + '","requires_restart":true},' + #13#10 +
    '    "run_cd": {"module_id":"run_cd","title":"Run CD Module","tier":"optional","package_kind":"bundled_unlock","status":"' + OptionalModuleStatusValue('run_cd') + '","installed_from":"' + OptionalModuleSourceValue('run_cd') + '","requires_restart":true},' + #13#10 +
    '    "web_browser": {"module_id":"web_browser","title":"Web Browser Module","tier":"optional","package_kind":"bundled_unlock","status":"' + OptionalModuleStatusValue('web_browser') + '","installed_from":"' + OptionalModuleSourceValue('web_browser') + '","requires_restart":true},' + #13#10 +
    '    "echomind": {"module_id":"echomind","title":"EchoMind Module","tier":"optional","package_kind":"bundled_unlock","status":"' + OptionalModuleStatusValue('echomind') + '","installed_from":"' + OptionalModuleSourceValue('echomind') + '","requires_restart":true}' + #13#10 +
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

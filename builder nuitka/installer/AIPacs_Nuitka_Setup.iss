#define MyAppName "AIPacs (Nuitka)"
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
  #define InstallerBaseName "ai-pacs-nuitka-installer"
#endif
#define AdvancedMprPayloadExe StageDir + "\plugin_packages\advanced_mpr\payload\AIPacsAdvancedViewer.exe"
#define AdvancedMprAvailable FileExists(AdvancedMprPayloadExe)

[Setup]
; DIFFERENT GUID from PyInstaller version to allow coexistence
AppId={{3E7B29F2-22DF-4B2C-8D3A-1E7C25772F76}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
; Install to a different directory to avoid conflicts
DefaultDirName={autopf}\AIPacs_Nuitka
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename={#InstallerBaseName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
DisableReadyMemo=no
SetupIconFile=..\..\Qss\images\favicon.ico
LicenseFile=..\..\LICENSE
UninstallDisplayIcon={app}\AIPacs.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "core"; Description: "Core workstation (viewer, download manager, education, stitching)"
Name: "custom"; Description: "Custom — choose optional modules for this workstation"; Flags: iscustom

[Components]
Name: "core"; Description: "Core platform (always required)"; Types: core custom; Flags: fixed
Name: "optional"; Description: "Optional modules — copied now, activated on first launch"; Types: custom
#if AdvancedMprAvailable
Name: "optional\advanced_mpr"; Description: "Advanced MPR — 3D reconstruction with bundled Slicer runtime (large download)"; Types: custom
#endif
Name: "optional\printing"; Description: "Printing — medical film printing and DICOM export workflows"; Types: custom
Name: "optional\run_cd"; Description: "Run CD — portable DICOM media export and delivery"; Types: custom
Name: "optional\web_browser"; Description: "Web Browser — embedded browser access inside the workstation"; Types: custom
Name: "optional\echomind"; Description: "EchoMind — AI assistant and guided reporting features"; Types: custom

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
; User Data next to executable for visibility
Name: "{app}\User Data"; Permissions: users-modify
; Legacy path for upgrade compatibility
Name: "{localappdata}\AIPacs\user_data"; Permissions: users-modify
Name: "{userappdata}\AIPacs\config"; Permissions: users-modify
; ProgramData for system-wide config and optional modules
Name: "{commonappdata}\AIPacs\config"; Permissions: users-modify
Name: "{commonappdata}\AIPacs\module_packages"; Permissions: users-modify

[Files]
; Core bundle from Nuitka build
Source: "{#StageDir}\core\*"; DestDir: "{app}"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs

; Module package feed (registry of available optional modules)
Source: "{#StageDir}\plugin_packages\module_package_feed.json"; DestDir: "{commonappdata}\AIPacs\module_packages"; Components: core; Flags: ignoreversion skipifsourcedoesntexist

; Default-enabled external package used to keep analytics dependencies out of Engine
Source: "{#StageDir}\plugin_packages\data_analysis\*"; DestDir: "{commonappdata}\AIPacs\module_packages\data_analysis"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; Optional module packages (same as PyInstaller build - plugin system is build-agnostic)
#if AdvancedMprAvailable
Source: "{#StageDir}\plugin_packages\advanced_mpr\*"; DestDir: "{commonappdata}\AIPacs\module_packages\advanced_mpr"; Components: optional\advanced_mpr; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
#endif
Source: "{#StageDir}\plugin_packages\printing\*"; DestDir: "{commonappdata}\AIPacs\module_packages\printing"; Components: optional\printing; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\run_cd\*"; DestDir: "{commonappdata}\AIPacs\module_packages\run_cd"; Components: optional\run_cd; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\web_browser\*"; DestDir: "{commonappdata}\AIPacs\module_packages\web_browser"; Components: optional\web_browser; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#StageDir}\plugin_packages\echomind\*"; DestDir: "{commonappdata}\AIPacs\module_packages\echomind"; Components: optional\echomind; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\AIPacs.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\AIPacs.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AIPacs.exe"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ExistingInstallPage: TWizardPage;
  ExistingInstallSummaryLabel: TNewStaticText;
  ExistingInstallWarningLabel: TNewStaticText;
  GpuPage: TWizardPage;
  GpuCheckBox: TNewCheckBox;
  GpuHintLabel: TNewStaticText;
  GpuAutoDetected: Boolean;
  GpuDetectionError: String;
  ExistingInstallDetected: Boolean;
  ExistingInstalledVersion: String;
  ExistingInstallAction: String;
  ExistingInstallShouldUpdate: Boolean;
  ExistingInstallWarning: String;

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
#if !AdvancedMprAvailable
  if ModuleId = 'advanced_mpr' then
  begin
    Result := False;
    Exit;
  end;
#endif
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

function InstalledVersionValue(): String;
begin
  if ExistingInstallDetected then
    Result := ExistingInstalledVersion
  else
    Result := '';
end;

function InstalledVersionDisplayValue(): String;
begin
  if ExistingInstallDetected and (ExistingInstalledVersion <> '') then
    Result := ExistingInstalledVersion
  else
    Result := 'none detected';
end;

function InstallActionDisplayValue(): String;
begin
  if ExistingInstallAction = 'update' then
    Result := 'Update existing installation'
  else if ExistingInstallAction = 'reinstall' then
    Result := 'Reinstall / repair current version'
  else if ExistingInstallAction = 'downgrade' then
    Result := 'Downgrade existing installation'
  else
    Result := 'Fresh install';
end;

function ShouldUpdateValue(): String;
begin
  Result := BoolToJson(ExistingInstallShouldUpdate);
end;

function ExtractNextVersionPart(var Value: String): Integer;
var
  DotPos: Integer;
  Token: String;
begin
  DotPos := Pos('.', Value);
  if DotPos = 0 then
  begin
    Token := Trim(Value);
    Value := '';
  end
  else
  begin
    Token := Trim(Copy(Value, 1, DotPos - 1));
    Delete(Value, 1, DotPos);
  end;

  if Token = '' then
    Result := 0
  else
    Result := StrToIntDef(Token, 0);
end;

function CompareVersionText(const LeftVersion: String; const RightVersion: String): Integer;
var
  LeftWork: String;
  RightWork: String;
  SegmentIndex: Integer;
  LeftPart: Integer;
  RightPart: Integer;
begin
  LeftWork := LeftVersion;
  RightWork := RightVersion;

  for SegmentIndex := 0 to 3 do
  begin
    LeftPart := ExtractNextVersionPart(LeftWork);
    RightPart := ExtractNextVersionPart(RightWork);

    if LeftPart < RightPart then
    begin
      Result := -1;
      Exit;
    end;

    if LeftPart > RightPart then
    begin
      Result := 1;
      Exit;
    end;

    if (LeftWork = '') and (RightWork = '') then
      Break;
  end;

  Result := 0;
end;

function ExistingAppExePath(): String;
begin
  if FileExists(AddBackslash(WizardDirValue()) + 'Engine\AIPacs.exe') then
    Result := AddBackslash(WizardDirValue()) + 'Engine\AIPacs.exe'
  else
    Result := AddBackslash(WizardDirValue()) + 'AIPacs.exe';
end;

procedure RefreshExistingInstallState();
var
  ExistingExe: String;
  DetectedVersion: String;
  VersionCompare: Integer;
begin
  ExistingInstallDetected := False;
  ExistingInstalledVersion := '';
  ExistingInstallAction := 'fresh_install';
  ExistingInstallShouldUpdate := False;
  ExistingInstallWarning := '';

  ExistingExe := ExistingAppExePath();
  if FileExists(ExistingExe) and GetVersionNumbersString(ExistingExe, DetectedVersion) then
  begin
    ExistingInstallDetected := True;
    ExistingInstalledVersion := Trim(DetectedVersion);
    VersionCompare := CompareVersionText(ExistingInstalledVersion, '{#MyAppVersion}');

    if VersionCompare < 0 then
    begin
      ExistingInstallAction := 'update';
      ExistingInstallShouldUpdate := True;
      ExistingInstallWarning :=
        'An older AIPacs version was detected in the selected folder. ' +
        'Setup will update it to the current installer version.';
    end
    else if VersionCompare = 0 then
    begin
      ExistingInstallAction := 'reinstall';
      ExistingInstallWarning :=
        'The same AIPacs version is already installed in the selected folder. ' +
        'Setup will reinstall or repair that version.';
    end
    else
    begin
      ExistingInstallAction := 'downgrade';
      ExistingInstallWarning :=
        'A newer AIPacs version is already installed in the selected folder. ' +
        'Continuing will downgrade that installation to the current installer version.';
    end;
  end;
end;

procedure RefreshExistingInstallPage();
begin
  RefreshExistingInstallState();

  ExistingInstallSummaryLabel.Caption :=
    'Install folder:' + #13#10 +
    '  ' + WizardDirValue() + #13#10 + #13#10 +
    'Version found in this folder:' + #13#10 +
    '  ' + InstalledVersionDisplayValue() + #13#10 + #13#10 +
    'This installer version:' + #13#10 +
    '  {#MyAppVersion}' + #13#10 + #13#10 +
    'Action:' + #13#10 +
    '  ' + InstallActionDisplayValue();

  if ExistingInstallWarning <> '' then
    ExistingInstallWarningLabel.Caption := ExistingInstallWarning
  else
    ExistingInstallWarningLabel.Caption :=
      'No previous installation was found in the selected folder. Setup will perform a fresh install.';
end;

function InternalConfigDir(): String;
begin
  // Primary: ProgramData (writable by installer and runtime without elevation)
  if DirExists(ExpandConstant('{commonappdata}\AIPacs\config')) then
  begin
    Result := ExpandConstant('{commonappdata}\AIPacs\config');
    Exit;
  end;
  // Fallback: engine\config (current PyInstaller layout)
  if DirExists(ExpandConstant('{app}\Engine\config')) then
  begin
    Result := ExpandConstant('{app}\Engine\config');
    Exit;
  end;
  if DirExists(ExpandConstant('{app}\engine\config')) then
  begin
    Result := ExpandConstant('{app}\engine\config');
    Exit;
  end;
  // Legacy fallback: _internal\config (pre-2.3.8 installs)
  if DirExists(ExpandConstant('{app}\_internal\config')) then
  begin
    Result := ExpandConstant('{app}\_internal\config');
    Exit;
  end;
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
    '  Core platform (always installed)' + #13#10 +
    '  Viewer' + #13#10 +
    '  Download Manager' + #13#10 +
    '  ZetaBoost cache engine' + #13#10 +
    '  Education' + #13#10 +
    '  Stitching' + #13#10;

  if OptionalModuleSelected('advanced_mpr') then Items := Items + '  Advanced MPR  [selected]' + #13#10;
  if OptionalModuleSelected('printing')     then Items := Items + '  Printing  [selected]' + #13#10;
  if OptionalModuleSelected('run_cd')       then Items := Items + '  Run CD  [selected]' + #13#10;
  if OptionalModuleSelected('web_browser')  then Items := Items + '  Web Browser  [selected]' + #13#10;
  if OptionalModuleSelected('echomind')     then Items := Items + '  EchoMind  [selected]' + #13#10;

  if not OptionalModuleSelected('advanced_mpr') and
     not OptionalModuleSelected('printing') and
     not OptionalModuleSelected('run_cd') and
     not OptionalModuleSelected('web_browser') and
     not OptionalModuleSelected('echomind') then
    Result := Items + '  No optional modules selected'
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
  RefreshExistingInstallState();

  if GpuCheckBox.Checked then
    GraphicsSummary := 'GPU acceleration enabled'
  else
    GraphicsSummary := 'Software rendering (CPU-safe fallback)';

  Result :=
    MemoDirInfo + NewLine + NewLine +
    MemoTypeInfo + NewLine + NewLine +
    MemoComponentsInfo + NewLine + NewLine +
    MemoTasksInfo + NewLine + NewLine +
    'Version:' + NewLine +
    Space + 'Installed in selected folder: ' + InstalledVersionDisplayValue() + NewLine +
    Space + 'This installer: {#MyAppVersion}' + NewLine +
    Space + 'Action: ' + InstallActionDisplayValue() + NewLine + NewLine +
    'Rendering mode:' + NewLine +
    Space + GraphicsSummary + NewLine + NewLine +
    'Modules:' + NewLine +
    SelectedModulesSummary() + NewLine +
    'Notes:' + NewLine +
    Space + 'Optional modules are copied now and activated automatically on first launch.' + NewLine +
    Space + 'AIPacs validates graphics support at startup and falls back to software rendering if needed.' + NewLine +
    Space + 'Additional modules can be installed later from Settings > Installation.';
end;

procedure InitializeWizard();
begin
  ExistingInstallDetected := False;
  ExistingInstalledVersion := '';
  ExistingInstallAction := 'fresh_install';
  ExistingInstallShouldUpdate := False;
  ExistingInstallWarning := '';
  GpuAutoDetected := AutoDetectGpuSupport(GpuDetectionError);

  ExistingInstallPage := CreateCustomPage(
    wpSelectDir,
    'Existing Installation',
    'Setup detected an existing installation in the selected folder. Review the details below before continuing.'
  );

  ExistingInstallSummaryLabel := TNewStaticText.Create(ExistingInstallPage.Surface);
  ExistingInstallSummaryLabel.Parent := ExistingInstallPage.Surface;
  ExistingInstallSummaryLabel.Left := ScaleX(0);
  ExistingInstallSummaryLabel.Top := ScaleY(8);
  ExistingInstallSummaryLabel.Width := ExistingInstallPage.SurfaceWidth;
  ExistingInstallSummaryLabel.Height := ScaleY(140);
  ExistingInstallSummaryLabel.AutoSize := False;
  ExistingInstallSummaryLabel.WordWrap := True;

  ExistingInstallWarningLabel := TNewStaticText.Create(ExistingInstallPage.Surface);
  ExistingInstallWarningLabel.Parent := ExistingInstallPage.Surface;
  ExistingInstallWarningLabel.Left := ScaleX(0);
  ExistingInstallWarningLabel.Top := ScaleY(156);
  ExistingInstallWarningLabel.Width := ExistingInstallPage.SurfaceWidth;
  ExistingInstallWarningLabel.Height := ScaleY(88);
  ExistingInstallWarningLabel.AutoSize := False;
  ExistingInstallWarningLabel.WordWrap := True;

  GpuPage := CreateCustomPage(
    wpSelectComponents,
    'Graphics Mode',
    'Choose the rendering mode for this workstation. This setting is saved locally and can be changed later in Settings.'
  );

  GpuCheckBox := TNewCheckBox.Create(GpuPage.Surface);
  GpuCheckBox.Parent := GpuPage.Surface;
  GpuCheckBox.Left := ScaleX(0);
  GpuCheckBox.Top := ScaleY(8);
  GpuCheckBox.Width := GpuPage.SurfaceWidth;
  GpuCheckBox.Caption := 'Enable GPU acceleration on this workstation';
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
      'A compatible GPU was detected on this workstation. ' +
      'GPU acceleration is enabled by default — you can change this if needed. ' +
      'AIPacs probes graphics support at startup and falls back automatically if the GPU is unavailable.'
  else
    GpuHintLabel.Caption :=
      'No compatible GPU was detected, or detection could not be completed. ' +
      'Software rendering is selected by default. You can enable GPU acceleration manually if this machine has a supported graphics card.';

  if GpuDetectionError <> '' then
    GpuHintLabel.Caption :=
      GpuHintLabel.Caption + #13#10 + #13#10 +
      'Detection note: ' + GpuDetectionError;

  GpuHintLabel.Caption :=
    GpuHintLabel.Caption + #13#10 + #13#10 +
    'Optional modules selected on the previous page are copied to the installation folder now and activated automatically on first launch. ' +
    'You can install additional modules later from Settings > Installation.';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = ExistingInstallPage.ID then
    RefreshExistingInstallPage();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = ExistingInstallPage.ID then
  begin
    RefreshExistingInstallPage();
    if ExistingInstallAction = 'downgrade' then
      Result :=
        MsgBox(
          'A newer version (' + InstalledVersionDisplayValue() + ') is already installed in this folder.' + #13#10 + #13#10 +
          'This installer contains version {#MyAppVersion}.' + #13#10 +
          'Proceeding will downgrade the existing installation. Continue?',
          mbConfirmation,
          MB_YESNO
        ) = IDYES;
  end;
end;

procedure WriteInstallationProfile();
var
  ConfigDir: String;
  ProfilePath: String;
  JsonText: String;
begin
  ConfigDir := ExpandConstant('{commonappdata}\AIPacs\config');
  ForceDirectories(ConfigDir);
  ProfilePath := AddBackslash(ConfigDir) + 'installation_profile.json';

  JsonText :=
    '{' + #13#10 +
    '  "app_name": "AIPacs",' + #13#10 +
    '  "app_version": "{#MyAppVersion}",' + #13#10 +
    '  "generated_at_utc": "",' + #13#10 +
    '  "installer": {' + #13#10 +
    '    "current_version": "{#MyAppVersion}",' + #13#10 +
    '    "detected_existing_version": "' + InstalledVersionValue() + '",' + #13#10 +
    '    "install_action": "' + ExistingInstallAction + '",' + #13#10 +
    '    "should_update": ' + ShouldUpdateValue() + #13#10 +
    '  },' + #13#10 +
    '  "modules": {' + #13#10 +
    '    "viewer": true,' + #13#10 +
    '    "download_manager": true,' + #13#10 +
    '    "zeta_boost": true,' + #13#10 +
    '    "education": true,' + #13#10 +
    '    "stitching": true,' + #13#10 +
    '    "data_analysis": true,' + #13#10 +
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
    '    "data_analysis": {"module_id":"data_analysis","title":"Data Analysis","tier":"optional","package_kind":"bundled_unlock","status":"selected_for_install","installed_from":"bundled_setup_selection","requires_restart":true},' + #13#10 +
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
  begin
    WriteInstallationProfile();

    if OptionalModuleSelected('advanced_mpr') then
      MsgBox(
        'Advanced MPR was included in this installation.' + #13#10 + #13#10 +
        'Advanced MPR uses a bundled 3D Slicer runtime. ' +
        'The runtime package has been copied to the module_packages folder in ProgramData and will be activated automatically the first time you open Advanced MPR inside AIPacs.' + #13#10 + #13#10 +
        'Requirements for Advanced MPR:' + #13#10 +
        '  - Windows 10 or later (64-bit)' + #13#10 +
        '  - At least 8 GB RAM (16 GB recommended for large CT volumes)' + #13#10 +
        '  - Sufficient disk space for the Slicer runtime (~1.5 GB)' + #13#10 +
        '  - A dedicated GPU is strongly recommended for 3D rendering' + #13#10 + #13#10 +
        'If activation fails on first launch, restart AIPacs and try again from Settings > Installation.',
        mbInformation,
        MB_OK
      );
  end;
end;


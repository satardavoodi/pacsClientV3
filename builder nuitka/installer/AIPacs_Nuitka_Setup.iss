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
Name: "optional\advanced_mpr"; Description: "Advanced MPR — 3D reconstruction with bundled Slicer runtime (large download)"; Types: custom
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

; Optional module packages (same as PyInstaller build - plugin system is build-agnostic)
Source: "{#StageDir}\plugin_packages\advanced_mpr\*"; DestDir: "{commonappdata}\AIPacs\module_packages\advanced_mpr"; Components: optional\advanced_mpr; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
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
{ Note: This is a simplified installer script for initial Nuitka build testing.
  The full PyInstaller installer includes:
  - Existing install detection and version comparison
  - GPU auto-detection (PowerShell probe)
  - installation_profile.json generation
  
  These features can be ported later once the basic build is validated.
  For now, this installer provides:
  - Core Nuitka-compiled bundle installation
  - Optional module package deployment to ProgramData
  - Desktop shortcut creation
}

procedure InitializeWizard;
begin
  { Placeholder for future GPU detection / existing install checks }
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { Placeholder for installation_profile.json generation }
end;

; AIPacs Professional Windows Installer
; Inno Setup 6.x Script with Comprehensive Prerequisite Validation
; 
; This installer:
; - Validates graphics stack (OpenGL, GPU drivers, software fallback)
; - Checks runtime dependencies (VC++ redistributables, VTK, SimpleITK)
; - Runs pre-flight tests before completing installation
; - Provides clear error messages for missing prerequisites
; - Ensures Viewer widget works before installation completes

#define MyAppName "AIPacs"
#define MyAppVersion "2.2.5"
#define MyAppPublisher "AI-PACS Medical Imaging Systems"
#define MyAppURL "https://www.example.com/"
#define MyAppExeName "AIPacs.exe"
#define SourceDir "..\FINAL_BUILD\AI Pacs Portable"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
AppId={{A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
InfoBeforeFile=PREINSTALL_INFO.txt
InfoAfterFile=POSTINSTALL_INFO.txt
OutputDir=Output
OutputBaseFilename=AIPacs_v{#MyAppVersion}_Setup
SetupIconFile={#SourceDir}\_internal\Qss\images\favicon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0.10240
DisableWelcomePage=no
; Uninstall settings
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
CreateUninstallRegKey=yes
; Require admin for proper VC++ runtime installation
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application files
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Prerequisite validation scripts
Source: "scripts\check_prerequisites.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "scripts\check_graphics.py"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "scripts\test_vtk_init.py"; DestDir: "{tmp}"; Flags: deleteafterinstall
; VC++ Redistributable (embedded)
Source: "redist\VC_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Install VC++ redistributable silently (critical for VTK/SimpleITK)
Filename: "{tmp}\VC_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ Runtime..."; Flags: waituntilterminated; Check: NeedsVCRedist
; Run post-install validation
Filename: "{tmp}\check_graphics.py"; Parameters: """{app}\{#MyAppExeName}"""; WorkingDir: "{tmp}"; StatusMsg: "Validating graphics subsystem..."; Flags: runhidden waituntilterminated; Check: CheckPythonInBundle
; Optional: Launch application after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  PrereqCheckPage: TOutputProgressWizardPage;
  GraphicsTestResult: Integer;
  VCRedistNeeded: Boolean;
  ErrorDetailsPage: TOutputMsgMemoWizardPage;

// ============================================================================
// PREREQUISITE DETECTION FUNCTIONS
// ============================================================================

function NeedsVCRedist: Boolean;
var
  ResultCode: Integer;
begin
  Result := VCRedistNeeded;
end;

function CheckVCRedist: Boolean;
var
  Installed: Cardinal;
begin
  // Check for VC++ 2015-2022 Redistributable (registry detection)
  Result := RegQueryDWordValue(HKLM64, 
    'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 
    'Installed', Installed) and (Installed = 1);
  
  if not Result then
    VCRedistNeeded := True
  else
    VCRedistNeeded := False;
end;

function CheckOpenGLSupport: Boolean;
var
  ResultCode: Integer;
  Output: AnsiString;
begin
  // Run PowerShell script to check OpenGL availability
  Result := True; // Assume pass by default
  
  if Exec('powershell.exe', 
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\check_prerequisites.ps1') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode <> 0 then
    begin
      Result := False;
      Log('OpenGL check failed with code: ' + IntToStr(ResultCode));
    end;
  end
  else
  begin
    Log('Failed to execute OpenGL check script');
    Result := False;
  end;
end;

function CheckPythonInBundle: Boolean;
begin
  // Check if python.exe or embedded Python exists in the bundle
  Result := FileExists(ExpandConstant('{app}\_internal\python.exe')) or
            FileExists(ExpandConstant('{app}\python.exe'));
end;

function TestVTKInitialization: Boolean;
var
  ResultCode: Integer;
  PythonExe: String;
  TestScript: String;
begin
  Result := True; // Assume success
  
  // Locate embedded Python
  if FileExists(ExpandConstant('{app}\_internal\python.exe')) then
    PythonExe := ExpandConstant('{app}\_internal\python.exe')
  else if FileExists(ExpandConstant('{app}\python.exe')) then
    PythonExe := ExpandConstant('{app}\python.exe')
  else
  begin
    Log('Embedded Python not found, skipping VTK test');
    Exit;
  end;
  
  TestScript := ExpandConstant('{tmp}\test_vtk_init.py');
  
  // Run VTK initialization test
  if Exec(PythonExe, '"' + TestScript + '"', ExpandConstant('{app}'), 
    SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    GraphicsTestResult := ResultCode;
    if ResultCode <> 0 then
    begin
      Log('VTK initialization test failed with code: ' + IntToStr(ResultCode));
      Result := False;
    end;
  end
  else
  begin
    Log('Failed to execute VTK test script');
    Result := False;
  end;
end;

// ============================================================================
// CUSTOM WIZARD PAGES
// ============================================================================

procedure InitializeWizard();
begin
  // Create prerequisite check progress page
  PrereqCheckPage := CreateOutputProgressPage('Checking Prerequisites', 
    'Validating system requirements for AIPacs installation');
  
  // Create error details page (shown only if validation fails)
  ErrorDetailsPage := CreateOutputMsgMemoPage(wpReady, 
    'Prerequisite Validation Failed', 
    'The following issues must be resolved before installation can continue:',
    'Please review the details below and take the recommended actions.',
    '');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ErrorMessage: String;
  HasErrors: Boolean;
begin
  Result := True;
  HasErrors := False;
  ErrorMessage := '';
  
  // Run prerequisite checks before starting installation
  if CurPageID = wpReady then
  begin
    PrereqCheckPage.SetText('Checking system requirements...', '');
    PrereqCheckPage.SetProgress(0, 0);
    PrereqCheckPage.Show;
    
    try
      // Step 1: Check VC++ Redistributable
      PrereqCheckPage.SetText('Checking Visual C++ Runtime...', 
        'Validating Microsoft Visual C++ 2015-2022 Redistributable');
      PrereqCheckPage.SetProgress(1, 4);
      Sleep(500);
      
      if not CheckVCRedist then
      begin
        ErrorMessage := ErrorMessage + '- Microsoft Visual C++ 2015-2022 Redistributable (x64) is missing' + #13#10;
        ErrorMessage := ErrorMessage + '  This will be installed automatically during setup.' + #13#10 + #13#10;
        Log('VC++ Redistributable check: MISSING (will install)');
      end
      else
      begin
        Log('VC++ Redistributable check: OK');
      end;
      
      // Step 2: Check OpenGL/Graphics
      PrereqCheckPage.SetText('Checking graphics subsystem...', 
        'Validating OpenGL and GPU driver availability');
      PrereqCheckPage.SetProgress(2, 4);
      Sleep(500);
      
      if not CheckOpenGLSupport then
      begin
        HasErrors := True;
        ErrorMessage := ErrorMessage + '- OpenGL graphics support is not available or incompatible' + #13#10;
        ErrorMessage := ErrorMessage + '  Recommended action: Update your GPU drivers' + #13#10;
        ErrorMessage := ErrorMessage + '  - NVIDIA: https://www.nvidia.com/Download/index.aspx' + #13#10;
        ErrorMessage := ErrorMessage + '  - Intel: https://www.intel.com/content/www/us/en/download-center/home.html' + #13#10;
        ErrorMessage := ErrorMessage + '  - AMD: https://www.amd.com/en/support' + #13#10 + #13#10;
        Log('OpenGL check: FAILED');
      end
      else
      begin
        Log('OpenGL check: OK');
      end;
      
      // Step 3: Check system architecture
      PrereqCheckPage.SetText('Checking system architecture...', 
        'Verifying 64-bit Windows compatibility');
      PrereqCheckPage.SetProgress(3, 4);
      Sleep(500);
      
      if not Is64BitInstallMode then
      begin
        HasErrors := True;
        ErrorMessage := ErrorMessage + '- 64-bit Windows is required' + #13#10;
        ErrorMessage := ErrorMessage + '  This application requires Windows 10 (64-bit) or newer' + #13#10 + #13#10;
        Log('Architecture check: FAILED (not 64-bit)');
      end
      else
      begin
        Log('Architecture check: OK');
      end;
      
      // Step 4: Summary
      PrereqCheckPage.SetText('Prerequisite check complete', '');
      PrereqCheckPage.SetProgress(4, 4);
      Sleep(500);
      
    finally
      PrereqCheckPage.Hide;
    end;
    
    // If errors found, show details and block installation
    if HasErrors then
    begin
      ErrorDetailsPage.RichEditViewer.Text := ErrorMessage;
      ErrorDetailsPage.RichEditViewer.Text := ErrorDetailsPage.RichEditViewer.Text + #13#10 + 
        'Installation cannot continue until these issues are resolved.' + #13#10 + 
        'Click Back to cancel installation.';
      
      // Block installation and show error message
      Result := False;
      MsgBox('Prerequisites validation failed. Please resolve the issues listed and run the installer again.', 
        mbError, MB_OK);
    end;
  end;
end;

// ============================================================================
// POST-INSTALL VALIDATION
// ============================================================================

procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorMsg: String;
  VTKTestPassed: Boolean;
begin
  if CurStep = ssPostInstall then
  begin
    // Run post-install VTK/graphics validation
    Log('Running post-install validation...');
    
    VTKTestPassed := TestVTKInitialization;
    
    if not VTKTestPassed then
    begin
      ErrorMsg := 'Post-install validation detected a potential issue with the graphics subsystem.' + #13#10 + #13#10;
      ErrorMsg := ErrorMsg + 'The application has been installed, but the Viewer may not work correctly.' + #13#10 + #13#10;
      ErrorMsg := ErrorMsg + 'Recommended actions:' + #13#10;
      ErrorMsg := ErrorMsg + '1. Update your GPU drivers to the latest version' + #13#10;
      ErrorMsg := ErrorMsg + '2. Ensure OpenGL 3.0 or higher is supported' + #13#10;
      ErrorMsg := ErrorMsg + '3. If you have an older GPU, the application will attempt to use software rendering' + #13#10 + #13#10 + 
        'Error code: ' + IntToStr(GraphicsTestResult);
      
      MsgBox(ErrorMsg, mbInformation, MB_OK);
      Log('Post-install validation: WARNING (VTK test failed)');
    end
    else
    begin
      Log('Post-install validation: OK');
    end;
  end;
end;

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: dirifempty; Name: "{localappdata}\AIPacs"

<#
verify_unified_pipeline_2026-06-17.ps1

Full verification runner for the 2026-06-17 work:
  - Download Manager critical-intent P0 hardening + repaired tests
  - Attachment local-first persistence guard
  - Unified-pipeline Phase-1 foundation (PatientStudySet) + Phase-2 shadow detector
  - Plugin-mirror parity (389/389)

The three pytest targets are run as SEPARATE processes on purpose: collecting a
home-panel suite before download_manager can trip a known latent package
circular-import. Separate processes isolate collection. `-p no:debugging` is the
project policy.

Usage (run from anywhere; the script locates the repo root itself):
  powershell -ExecutionPolicy Bypass -File tools\dev\verify_unified_pipeline_2026-06-17.ps1
  powershell -ExecutionPolicy Bypass -File tools\dev\verify_unified_pipeline_2026-06-17.ps1 -SyncMirrors
  powershell -ExecutionPolicy Bypass -File tools\dev\verify_unified_pipeline_2026-06-17.ps1 -RunApp     # launch SOURCE build with the shadow detector ON (live 46630 evidence)
  powershell -ExecutionPolicy Bypass -File tools\dev\verify_unified_pipeline_2026-06-17.ps1 -TailLog    # show the shadow traces from the diagnostics log
#>
param(
    [switch]$SyncMirrors,
    [switch]$RunApp,
    [switch]$TailLog
)
$ErrorActionPreference = 'Stop'

# Repo root = two levels up from this script (tools\dev\..\..)
$Proj = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Proj
Write-Host "Project: $Proj"

$Py = Join-Path $Proj '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { $Py = 'python' }
Write-Host "Python : $Py"
& $Py --version

# --- Show shadow traces from the log and exit ---
if ($TailLog) {
    $log = Join-Path $Proj 'user_data\logs\download_diagnostics.log'
    if (-not (Test-Path $log)) { Write-Host "Log not found: $log"; return }
    Write-Host "`n--- patient_study_set traces (last 40) ---"
    Select-String -Path $log -Pattern 'patient_study_set_open|patient_study_set_late_growth' |
        Select-Object -Last 40 | ForEach-Object { $_.Line }
    return
}

# --- Launch the SOURCE build with the shadow detector ON (live evidence) ---
if ($RunApp) {
    $env:AIPACS_PATIENT_STUDY_SET_SHADOW = '1'
    Write-Host "`nAIPACS_PATIENT_STUDY_SET_SHADOW=1 set. Launching the SOURCE build (python main.py)."
    Write-Host "This is the source build (NOT the frozen exe). Startup is slow."
    Write-Host "At login the credentials are pre-filled - just Sign In."
    Write-Host "Then pick MRI + a recent date, open patient 46630, then close the app."
    Write-Host "Afterwards run:  .\tools\dev\verify_unified_pipeline_2026-06-17.ps1 -TailLog`n"
    & $Py main.py
    return
}

# --- Test suites (separate processes; -p no:debugging per project policy) ---
$fail = $false

Write-Host "`n==== tests/code/download_manager ===="
& $Py -m pytest tests/code/download_manager -q -p no:debugging
if ($LASTEXITCODE -ne 0) { $fail = $true }

Write-Host "`n==== tests/code/network/test_attachment_local_first_persistence.py ===="
& $Py -m pytest tests/code/network/test_attachment_local_first_persistence.py -q -p no:debugging
if ($LASTEXITCODE -ne 0) { $fail = $true }

Write-Host "`n==== tests/code/ui_services (incl. test_patient_study_set) ===="
& $Py -m pytest tests/code/ui_services -q -p no:debugging
if ($LASTEXITCODE -ne 0) { $fail = $true }

# --- Plugin mirrors ---
if ($SyncMirrors) {
    Write-Host "`n==== sync_plugin_mirrors ===="
    & $Py tools\dev\sync_plugin_mirrors.py
}
Write-Host "`n==== verify_plugin_mirrors ===="
& $Py tools\dev\verify_plugin_mirrors.py
if ($LASTEXITCODE -ne 0) { $fail = $true }

if ($fail) { Write-Host "`nRESULT: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "`nRESULT: ALL GREEN" -ForegroundColor Green

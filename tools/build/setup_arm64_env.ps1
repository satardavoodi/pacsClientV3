<#
.SYNOPSIS
  Bootstrap the Windows ARM64 build environment for AI-PACS (ARM64 plan §7).

.DESCRIPTION
  Run ON the ARM64 builder machine (Snapdragon dev kit / WoA laptop / arm64 VM).
  PyInstaller cannot cross-compile, so the arm64 build MUST be produced here.

  Steps: verify host is ARM64 -> verify an ARM64 CPython 3.11+ is available ->
  create .venv-arm64 -> install requirements-arm64.txt core set -> best-effort
  install the #OPTIONAL lines one-by-one (report failures, don't abort) ->
  install PyInstaller -> print the build command.

.USAGE
  powershell -ExecutionPolicy Bypass -File tools\build\setup_arm64_env.ps1
  Optional: -Python "C:\Path\To\arm64\python.exe"
#>
param(
    [string]$Python = ""
)

$ErrorActionPreference = 'Stop'
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$req = Join-Path $repo 'requirements-arm64.txt'
$venv = Join-Path $repo '.venv-arm64'

# 1 ── host must be ARM64 ------------------------------------------------------
$hostArch = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment').PROCESSOR_ARCHITECTURE
if ($hostArch -ne 'ARM64') {
    throw "This machine's host architecture is '$hostArch', not ARM64. PyInstaller cannot cross-build — run this on the ARM64 builder."
}
Write-Host "[OK] Host architecture: ARM64" -ForegroundColor Green

# 2 ── locate an ARM64 CPython -------------------------------------------------
if (-not $Python) {
    $candidates = @('python.exe') + (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*-arm64\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName)
    foreach ($c in $candidates) {
        try {
            $arch = & $c -c "import platform;print(platform.machine())" 2>$null
            if ($arch -eq 'ARM64') { $Python = $c; break }
        } catch {}
    }
}
if (-not $Python) {
    throw "No ARM64 CPython found. Install the python.org 'Windows installer (ARM64)' for Python 3.13, then re-run (or pass -Python)."
}
$pyver = & $Python -c "import sys,platform;print(platform.machine(), sys.version.split()[0])"
Write-Host "[OK] ARM64 Python: $Python ($pyver)" -ForegroundColor Green

# 3 ── venv --------------------------------------------------------------------
if (-not (Test-Path $venv)) {
    & $Python -m venv $venv
    Write-Host "[OK] Created $venv"
}
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --upgrade pip wheel | Out-Null

# 4 ── core requirements --------------------------------------------------------
Write-Host "`n[STEP] Installing core arm64 requirements..." -ForegroundColor Cyan
& $vpy -m pip install -r $req
if ($LASTEXITCODE -ne 0) { throw "Core requirements failed — fix before continuing (these are the verified set)." }

# 5 ── optional best-effort -----------------------------------------------------
Write-Host "`n[STEP] Best-effort optional packages (#OPTIONAL lines)..." -ForegroundColor Cyan
$failed = @()
Get-Content $req | Where-Object { $_ -match '^#OPTIONAL\s+(.+)$' } | ForEach-Object {
    $pkg = $Matches[1].Trim()
    Write-Host "  -> $pkg"
    & $vpy -m pip install $pkg
    if ($LASTEXITCODE -ne 0) { $failed += $pkg }
}
if ($failed) {
    Write-Host "`n[WARN] No win_arm64 wheel for:" -ForegroundColor Yellow
    $failed | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow }
    Write-Host "  Decode plugins (pylibjpeg-*) matter for compressed DICOM — build from source or use cgohlke/win_arm64-wheels." -ForegroundColor Yellow
} else {
    Write-Host "[OK] All optional packages installed." -ForegroundColor Green
}

# 6 ── PyInstaller --------------------------------------------------------------
& $vpy -m pip install pyinstaller
Write-Host "`n[DONE] ARM64 env ready." -ForegroundColor Green
Write-Host "Next:  & '$vpy' builder\build_release.py --arch arm64" -ForegroundColor Cyan
Write-Host "Note:  Phase 1 is the arm64-lite (FAST-only) profile; vtk/SimpleITK wheels are Phase 2/3 (see requirements-arm64.txt footer)."

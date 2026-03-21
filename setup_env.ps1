<#
.SYNOPSIS
    Creates and populates the .venv virtual environment for AIPacs.

.DESCRIPTION
    - Requires Python 3.13.5 or later (no older versions accepted).
    - Detects Python 3.13+ automatically (no hardcoded paths).
    - Creates .venv at the repo root if it does not already exist.
    - Installs requirements-core.txt by default.
    - Optionally installs requirements-dev.txt with -IncludeDev.
    - Falls back to requirements.txt only if the split requirement files are missing.
    - Safe to run repeatedly: reuses .venv unless -Force is specified.
    - Works on any PC after a git clone without any manual path changes.

.EXAMPLE
    .\setup_env.ps1
    .\setup_env.ps1 -IncludeDev
    .\setup_env.ps1 -Force    # Remove and recreate .venv even if it exists
#>
param(
    [switch]$Force,
    [switch]$IncludeDev
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$root               = $PSScriptRoot
$venvDir            = Join-Path $root ".venv"
$venvPython         = Join-Path $venvDir "Scripts\python.exe"
$coreRequirements   = Join-Path $root "requirements-core.txt"
$devRequirements    = Join-Path $root "requirements-dev.txt"
$legacyRequirements = Join-Path $root "requirements.txt"

if ($Force -and (Test-Path $venvDir)) {
    Write-Host "[setup_env] -Force: removing existing .venv ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDir
}

Write-Host "[setup_env] Setting up Python environment ..." -ForegroundColor Cyan

function Find-Python3135Plus {
    # Try Windows Python Launcher first (py), then plain python/python3 on PATH
    $candidates = @(
        @{ exe = "py";         args = @("-3.13") },
        @{ exe = "py";         args = @("-3") },
        @{ exe = "python3.13"; args = @() },
        @{ exe = "python3";    args = @() },
        @{ exe = "python";     args = @() }
    )

    foreach ($c in $candidates) {
        try {
            $verStr = & $c.exe @($c.args) -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')" 2>$null
            if (-not $verStr) { continue }
            $parts = $verStr.Trim() -split "\."
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            $patch = [int]$parts[2]
            if ($major -eq 3 -and $minor -eq 13 -and $patch -ge 5) {
                $label = "$($c.exe) $($c.args -join ' ')".Trim()
                Write-Host "[setup_env] Found Python $($verStr.Trim()) via: $label" -ForegroundColor Cyan
                return $c
            } elseif ($major -eq 3 -and $minor -eq 13 -and $patch -lt 5) {
                Write-Warning "[setup_env] Found Python $($verStr.Trim()) but 3.13.5+ is required. Skipping."
            }
        } catch { }
    }
    return $null
}

$pyCandidate = Find-Python3135Plus
if ($null -eq $pyCandidate) {
    Write-Error @"
[setup_env] Python 3.13.5+ not found on this machine.

This project requires Python 3.13.5 or later.
Please install it from https://python.org/downloads/
and make sure to check "Add Python to PATH" during installation,
or install the Windows Python Launcher (py.exe).
"@
    exit 1
}

if (-not (Test-Path $venvPython)) {
    Write-Host "[setup_env] Creating .venv ..." -ForegroundColor Cyan
    & $pyCandidate.exe @($pyCandidate.args) -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[setup_env] Failed to create virtual environment (exit $LASTEXITCODE)."
        exit 1
    }
} else {
    Write-Host "[setup_env] Reusing existing .venv ..." -ForegroundColor Green
}

if (-not (Test-Path $venvPython)) {
    Write-Error "[setup_env] .venv was created but python.exe not found at expected path: $venvPython"
    exit 1
}

Write-Host "[setup_env] Upgrading pip ..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[setup_env] pip upgrade returned exit $LASTEXITCODE (non-fatal, continuing)."
}

$selectedRequirements = $null
$selectedLabel = $null

if ($IncludeDev -and (Test-Path $devRequirements)) {
    $selectedRequirements = $devRequirements
    $selectedLabel = "requirements-dev.txt"
} elseif (Test-Path $coreRequirements) {
    $selectedRequirements = $coreRequirements
    $selectedLabel = "requirements-core.txt"
} elseif (Test-Path $legacyRequirements) {
    $selectedRequirements = $legacyRequirements
    $selectedLabel = "requirements.txt"
}

if ($null -ne $selectedRequirements) {
    Write-Host "[setup_env] Installing $selectedLabel ..." -ForegroundColor Cyan
    & $venvPython -m pip install -r $selectedRequirements
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[setup_env] 'pip install -r $selectedLabel' failed (exit $LASTEXITCODE)."
        exit 1
    }
} else {
    Write-Warning "[setup_env] No requirements file found. Looked for requirements-core.txt, requirements-dev.txt, and requirements.txt."
}

if ($IncludeDev -and -not (Test-Path $devRequirements)) {
    Write-Warning "[setup_env] -IncludeDev was requested but requirements-dev.txt was not found. Installed runtime dependencies only."
}

Write-Host ""
Write-Host "[setup_env] Environment ready at: $venvDir" -ForegroundColor Green
Write-Host "[setup_env] Python: $venvPython" -ForegroundColor Green
exit 0

<#
.SYNOPSIS
    Creates and populates the .venv_build virtual environment required for AIPacs release builds.

.DESCRIPTION
    This script sets up the isolated build environment used by build.py / build.bat.
    It is safe to run on any Windows PC after a fresh git clone.

    Steps performed:
    1. Locate Python 3.13.5+ (same requirement as the runtime).
    2. Create .venv_build at the repository root (if it does not exist).
    3. Install pinned build toolchain from builder/requirements/build_requirements.txt.
    4. Install project runtime dependencies from requirements-core.txt
       (PyInstaller needs them on the import path to resolve hidden imports and datas).

    After this script completes, run:
        python build.py           # uses .venv_build automatically via build.bat
        .\build.bat               # same, via the .bat wrapper

.PARAMETER Force
    Remove and recreate .venv_build from scratch even if it already exists.

.EXAMPLE
    .\setup_build_env.ps1
    .\setup_build_env.ps1 -Force
#>
param(
    [switch]$Force
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$root              = $PSScriptRoot
$venvDir           = Join-Path $root ".venv_build"
$venvPython        = Join-Path $venvDir "Scripts\python.exe"
$venvPip           = Join-Path $venvDir "Scripts\pip.exe"
$buildRequirements = Join-Path $root "builder\requirements\build_requirements.txt"
$coreRequirements  = Join-Path $root "requirements-core.txt"

if ($Force -and (Test-Path $venvDir)) {
    Write-Host "[setup_build_env] -Force: removing existing .venv_build ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDir
}

Write-Host "[setup_build_env] Setting up AIPacs build environment ..." -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Locate Python 3.13.5+
# ---------------------------------------------------------------------------
function Find-Python3135Plus {
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
            $major = [int]$parts[0]; $minor = [int]$parts[1]; $patch = [int]$parts[2]
            if ($major -eq 3 -and $minor -eq 13 -and $patch -ge 5) {
                Write-Host "[setup_build_env] Found Python $($verStr.Trim()) via: $($c.exe) $($c.args -join ' ')".Trim() -ForegroundColor Cyan
                return $c
            } elseif ($major -eq 3 -and $minor -eq 13 -and $patch -lt 5) {
                Write-Warning "[setup_build_env] Found Python $($verStr.Trim()) but 3.13.5+ is required. Skipping."
            }
        } catch { }
    }
    return $null
}

$pyCandidate = Find-Python3135Plus
if ($null -eq $pyCandidate) {
    Write-Error @"
[setup_build_env] Python 3.13.5+ not found on this machine.

This project requires Python 3.13.5 or later.
Please install it from https://python.org/downloads/
and make sure to check "Add Python to PATH" during installation,
or install the Windows Python Launcher (py.exe).
"@
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Create .venv_build if it does not exist
# ---------------------------------------------------------------------------
if (-not (Test-Path $venvPython)) {
    Write-Host "[setup_build_env] Creating .venv_build ..." -ForegroundColor Cyan
    & $pyCandidate.exe @($pyCandidate.args) -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[setup_build_env] Failed to create .venv_build."
        exit 1
    }
    Write-Host "[setup_build_env] .venv_build created." -ForegroundColor Green
} else {
    Write-Host "[setup_build_env] .venv_build already exists." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 3. Upgrade pip inside the build venv
# ---------------------------------------------------------------------------
Write-Host "[setup_build_env] Upgrading pip ..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[setup_build_env] pip upgrade returned non-zero (usually harmless, continuing)."
}

# ---------------------------------------------------------------------------
# 4. Install pinned build toolchain
# ---------------------------------------------------------------------------
if (Test-Path $buildRequirements) {
    Write-Host "[setup_build_env] Installing build toolchain from builder\requirements\build_requirements.txt ..." -ForegroundColor Cyan
    & $venvPython -m pip install -r $buildRequirements --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[setup_build_env] Failed to install build requirements."
        exit 1
    }
    Write-Host "[setup_build_env] Build toolchain installed." -ForegroundColor Green
} else {
    Write-Error "[setup_build_env] builder\requirements\build_requirements.txt not found."
    exit 1
}

# ---------------------------------------------------------------------------
# 5. Install project runtime dependencies
#    (PyInstaller needs these on its import path to trace hidden imports/datas)
# ---------------------------------------------------------------------------
if (Test-Path $coreRequirements) {
    Write-Host "[setup_build_env] Installing runtime dependencies from requirements-core.txt ..." -ForegroundColor Cyan
    & $venvPython -m pip install -r $coreRequirements --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[setup_build_env] Failed to install core runtime requirements."
        exit 1
    }
    Write-Host "[setup_build_env] Runtime dependencies installed." -ForegroundColor Green
} else {
    Write-Error "[setup_build_env] requirements-core.txt not found."
    exit 1
}

# ---------------------------------------------------------------------------
# 6. Verify key packages
# ---------------------------------------------------------------------------
Write-Host "[setup_build_env] Verifying key packages ..." -ForegroundColor Cyan
$checks = @("PyInstaller", "PySide6", "vtk", "pydicom")
$allOk = $true
foreach ($pkg in $checks) {
    $result = & $venvPython -c "import $pkg; print('ok')" 2>&1
    if ($result -eq "ok") {
        Write-Host "  [OK] $pkg" -ForegroundColor Green
    } else {
        Write-Warning "  [WARN] $pkg import check failed: $result"
        $allOk = $false
    }
}

# ---------------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "===============================================================================" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "  Build environment is ready." -ForegroundColor Green
} else {
    Write-Host "  Build environment created but some package checks failed (see warnings above)." -ForegroundColor Yellow
}
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Build venv : $venvDir"
Write-Host "  Python     : $venvPython"
Write-Host ""
Write-Host "  To build the release:" -ForegroundColor Cyan
Write-Host "      python build.py"
Write-Host "  or:"
Write-Host "      .\build.bat"
Write-Host ""
Write-Host "  The build scripts automatically use .venv_build\Scripts\python.exe." -ForegroundColor Cyan
Write-Host "  Run this script again with -Force to recreate the build venv from scratch." -ForegroundColor Cyan
Write-Host ""

<#
    run_mg_cursor_tests.ps1
    Runs the pure guard tests for the Two-Stage 3D Cursor + EagleEye MG viewport
    fixes on the Windows source build (the sandbox mount truncated files, so these
    could not be run there).

    These tests are PURE (no Qt/VTK/app launch) — they run under plain pytest in a
    few seconds. `-p no:debugging` is the project's required flag (debugpy/VS Code
    conflict; tests/conftest.py backfills the --trace/--pdb options it removes).

    Usage (from anywhere):
        powershell -ExecutionPolicy Bypass -File ".\run_mg_cursor_tests.ps1"

    Options:
        -All        also run the whole tests/code/ai_imaging suite (regression sweep)
        -Verbose2   verbose per-test output (-vv) instead of the quiet summary
#>

param(
    [switch]$All,
    [switch]$Verbose2
)

$ErrorActionPreference = "Stop"

# Repo root = the folder this script lives in.
$Repo = $PSScriptRoot
Set-Location -Path $Repo

# Prefer the runtime venv; fall back to whatever `python` is on PATH.
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "[i] .venv not found at $Py - falling back to 'python' on PATH" -ForegroundColor Yellow
    $Py = "python"
}

Write-Host "=== AI-PACS: MG 3D-Cursor / viewport guard tests ===" -ForegroundColor Cyan
Write-Host "    repo:   $Repo"
Write-Host "    python: $Py"
& $Py --version

# Make sure pytest is available in this interpreter.
& $Py -c "import pytest" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[i] pytest not installed in this interpreter - installing..." -ForegroundColor Yellow
    & $Py -m pip install pytest --quiet
}

# The two new pure test files.
$Targets = @(
    "tests/code/ai_imaging/test_cursor3d_two_stage.py",
    "tests/code/ai_imaging/test_eagleeye_viewport_fixes.py"
)

if ($All) {
    Write-Host "[i] -All set: running the whole tests/code/ai_imaging suite" -ForegroundColor Yellow
    $Targets = @("tests/code/ai_imaging")
}

# Warn about any missing target rather than failing opaquely.
foreach ($t in $Targets) {
    if (-not (Test-Path (Join-Path $Repo $t))) {
        Write-Host "[!] target not found: $t" -ForegroundColor Red
    }
}

$PytestArgs = @("-m", "pytest") + $Targets + @("-p", "no:debugging", "--no-header")
if ($Verbose2) { $PytestArgs += "-vv" } else { $PytestArgs += @("-q") }

Write-Host ""
Write-Host ">> $Py $($PytestArgs -join ' ')" -ForegroundColor DarkGray
Write-Host ""

& $Py @PytestArgs
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
    Write-Host "=== PASS (exit 0) ===" -ForegroundColor Green
} else {
    Write-Host "=== FAIL (exit $code) ===" -ForegroundColor Red
    Write-Host "Tip: re-run with -Verbose2 for per-test detail." -ForegroundColor DarkGray
}
exit $code

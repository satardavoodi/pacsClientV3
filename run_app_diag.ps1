<#
    run_app_diag.ps1  —  Launch the AI-PACS source build for LIVE VERIFICATION.

    Thin wrapper around the project's own launcher (run_app.ps1): it sets the
    diagnostic feature flags in the environment, then delegates to run_app.ps1 so
    you keep all of its behaviour (venv auto-setup, UTF-8, tee'd terminal log under
    .\log\). It does NOT replace or modify run_app.ps1.

    Why: this turns on the traces that answer the two open questions, all written to
    user_data\logs\app.log:
        [MG][VTK-DIAG]   — is a single-image MG series arriving with >1 image? (bug #1)
        [3D-Cursor][2-STAGE] / [2ND-PASS] — the threshold escalation ladder
        [MG][AUTO-PAIR]  — CC/MLO auto-pairing (bug #2)

    Usage:
        powershell -ExecutionPolicy Bypass -File ".\run_app_diag.ps1"

    Options:
        -EnforceSingleImage   Also turn ON the MG single-image corrective
                              (AIPACS_MG_ENFORCE_SINGLE_IMAGE=1). Leave OFF for the
                              FIRST run — read the [MG][VTK-DIAG] lines first, then
                              enable this to confirm the fix on a second run.
#>

param(
    [switch]$EnforceSingleImage,
    [ValidateSet("ss", "ab", "gm")]
    [string]$Locus = "gm"
)

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
Set-Location -Path $Repo

$Launcher = Join-Path $Repo "run_app.ps1"
if (-not (Test-Path $Launcher)) {
    Write-Host "[X] run_app.ps1 not found — cannot delegate to the project launcher." -ForegroundColor Red
    exit 1
}

# --- Feature flags for this verification run (inherited by the child process) ---
$env:AIPACS_MG_VOLUME_DIAG       = "1"   # [MG][VTK-DIAG]
$env:AIPACS_CURSOR3D_TWO_STAGE   = "1"   # two-stage matching (default on; explicit)
$env:AIPACS_CURSOR3D_SECOND_PASS = "1"   # background rerun + escalation ladder
$env:AIPACS_CURSOR3D_LOCUS       = $Locus  # ss (default) | ab | gm (geometric model)

if ($EnforceSingleImage) {
    $env:AIPACS_MG_ENFORCE_SINGLE_IMAGE = "1"
} else {
    $env:AIPACS_MG_ENFORCE_SINGLE_IMAGE = "0"
}
# AIPACS_TEST_SERVER is deliberately NOT set — never enable it during a real read.

Write-Host "=== AI-PACS verification launch (diagnostics ON) ===" -ForegroundColor Cyan
Write-Host "    MG_VOLUME_DIAG=1  TWO_STAGE=1  SECOND_PASS=1  LOCUS=$Locus  ENFORCE_SINGLE_IMAGE=$($env:AIPACS_MG_ENFORCE_SINGLE_IMAGE)" -ForegroundColor DarkGray
if ($Locus -eq "gm") {
    Write-Host "    LOCUS=gm -> Geometric Model locus (fixes the 50258 pectoral-tilt error; validated on that case, calibrating broadly)" -ForegroundColor Cyan
}
Write-Host "    delegating to: $Launcher" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  After it opens: Sign In -> Eagle Eye -> open study 50016 (MG)," -ForegroundColor DarkGray
Write-Host "  reproduce the two-image viewport, then run the 3D Cursor." -ForegroundColor DarkGray
Write-Host "  Watch diagnostics live in a SECOND PowerShell window with:" -ForegroundColor DarkGray
Write-Host "      Get-Content .\user_data\logs\app.log -Wait -Tail 0 | Select-String 'MG\]\[VTK-DIAG|3D-Cursor|MG\]\[AUTO-PAIR'" -ForegroundColor DarkGray
Write-Host ""

# Delegate to the project launcher (keeps its venv-setup + tee'd terminal log).
& $Launcher
exit $LASTEXITCODE

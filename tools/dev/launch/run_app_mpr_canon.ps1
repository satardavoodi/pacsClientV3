# run_app_mpr_canon.ps1
# Launch the AI-PACS SOURCE build with the Zeta MPR orientation fix ENABLED.
#
# This sets two environment variables, then calls the blessed launcher run_app.ps1
# (which uses .venv\Scripts\python.exe + tees terminal output to log\). The fix is
# OFF unless AIPACS_ZETA_MPR_CANONICALIZE is set, so this script is the only thing
# that turns it on.
#
# IMPORTANT: fully CLOSE any already-running source build first. The single-instance
# guard will otherwise just raise the existing window, and the new env/code won't load.
#
# Usage (PowerShell, from the repo root):
#   .\run_app_mpr_canon.ps1
# To run WITHOUT the fix (legacy), just use .\run_app.ps1 instead.

Set-Location -Path $PSScriptRoot

$env:AIPACS_ZETA_MPR_CANONICALIZE = "1"   # enable matrix-driven canonical MPR
$env:ZETA_MPR_DIAG = "1"                  # orientation corner labels + invariant checks (optional; remove for a clean view)

Write-Host "[run_app_mpr_canon] AIPACS_ZETA_MPR_CANONICALIZE=$($env:AIPACS_ZETA_MPR_CANONICALIZE)  ZETA_MPR_DIAG=$($env:ZETA_MPR_DIAG)" -ForegroundColor Green

& (Join-Path $PSScriptRoot "run_app.ps1")
exit $LASTEXITCODE

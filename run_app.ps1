Set-Location -Path $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# Auto-setup: create .venv and install requirements if not present
if (-not (Test-Path $venvPython)) {
    Write-Host "[run_app] .venv not found - running setup_env.ps1 ..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup_env.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[run_app] Environment setup failed. Cannot start app."
        exit $LASTEXITCODE
    }
}

& $venvPython main.py
exit $LASTEXITCODE

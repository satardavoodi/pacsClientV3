param(
    [switch]$TestServer,
    [switch]$EagleEyeServer,
    [switch]$Standard,
    [string]$EagleEyeConfig
)

if ($EagleEyeServer -and $Standard) { throw 'Choose one workstation role.' }
$roleArgs = @()
if ($EagleEyeServer -or $Standard) {
    if (-not $EagleEyeConfig) {
        $EagleEyeConfig = Join-Path $PSScriptRoot ('generated-files\eagle-eye\deployment\' + $(if ($EagleEyeServer) { 'server.json' } else { 'client.json' }))
    }
    $roleArgs = @('--eagle-eye-mode', $(if ($EagleEyeServer) { 'server' } else { 'standard' }), '--eagle-eye-config', $EagleEyeConfig)
}

# Normal launches use all default features without the automation test endpoint.
$env:AIPACS_TEST_SERVER = if ($TestServer) { '1' } else { '0' }

Set-Location -Path $PSScriptRoot
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$teeRunner = Join-Path $PSScriptRoot "tools\diagnostics\tee_process_output.py"
$terminalLogDir = Join-Path $PSScriptRoot "log"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$sessionLog = Join-Path $terminalLogDir ("terminal_{0}.log" -f $timestamp)
$latestPointer = Join-Path $terminalLogDir "latest_terminal_log.txt"

New-Item -ItemType Directory -Force -Path $terminalLogDir | Out-Null
New-Item -ItemType File -Force -Path $sessionLog | Out-Null
Set-Content -Path $latestPointer -Value $sessionLog -Encoding UTF8

Write-Host "[run_app] Terminal session log: $sessionLog" -ForegroundColor Cyan

# Auto-setup: create .venv and install requirements if not present
if (-not (Test-Path $venvPython)) {
    Write-Host "[run_app] .venv not found - running setup_env.ps1 ..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup_env.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[run_app] Environment setup failed. Cannot start app."
        exit $LASTEXITCODE
    }
}

& $venvPython $teeRunner --cwd $PSScriptRoot --log-file $sessionLog -- $venvPython main.py @roleArgs
$appExitCode = $LASTEXITCODE

Add-Content -Path $sessionLog -Value ("[run_app] ExitCode={0}" -f $appExitCode) -Encoding UTF8
exit $appExitCode

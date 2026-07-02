#Requires -Version 5.1
<#
    run_app_lifecycle_shadow.ps1
    ---------------------------------------------------------------------------
    Launch the AI-PACS SOURCE build with the Stage-1 lifecycle SHADOW observer
    enabled (AIPACS_LIFECYCLE_THUMBS=shadow).

    The shadow observer is TELEMETRY ONLY: it runs the canonical PatientLoadModel
    alongside the legacy thumbnail path and writes [LIFECYCLE] / [LIFECYCLE-SHADOW]
    log lines. It never changes what renders, so behaviour is otherwise identical
    to a normal run.

    Rules honoured (per the project runbook):
      * SOURCE build only  -> repo .venv python on main.py (never the frozen exe).
      * ONE instance       -> detects a running source build and asks first.
      * Watch it load      -> runs in the foreground and streams the app output.

    Usage:
      powershell -ExecutionPolicy Bypass -File .\tools\dev\run_app_lifecycle_shadow.ps1
      # optional switches:
      #   -TailLog   also open a 2nd window that live-tails the [LIFECYCLE] log
      #   -Force     skip the "already running" prompt (the app takeover will
      #              close the old instance)
#>
[CmdletBinding()]
param(
    [switch]$TailLog,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# --- Paths -----------------------------------------------------------------
$Repo   = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
$Py     = Join-Path $Repo '.venv\Scripts\python.exe'
$Main   = Join-Path $Repo 'main.py'
$LogDir = Join-Path $Repo 'user_data\logs'
$AppLog = Join-Path $LogDir 'app.log'

# --- Preconditions ---------------------------------------------------------
if (-not (Test-Path -LiteralPath $Py))   { throw "venv python not found: $Py" }
if (-not (Test-Path -LiteralPath $Main)) { throw "main.py not found: $Main" }

# --- UTF-8 console so unicode prints (emoji / Persian) never crash stdout --
try {
    $OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch { }
$env:PYTHONUTF8       = '1'
$env:PYTHONIOENCODING = 'utf-8'

# --- The ONE flag we are enabling (telemetry only; everything else default) -
$env:AIPACS_LIFECYCLE_THUMBS = 'shadow'

# --- One-instance guard: do not spawn a duplicate source build -------------
$running = @()
try {
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'main\.py' }
} catch { }
if ($running -and -not $Force) {
    Write-Warning ("A source-build instance already looks to be running (PID {0})." -f (($running.ProcessId) -join ', '))
    $ans = Read-Host 'Launch anyway? The app takeover will close the old one. [y/N]'
    if ($ans -notmatch '^(y|yes)$') { Write-Host 'Aborted.'; return }
}

# --- Banner ----------------------------------------------------------------
Write-Host ''
Write-Host '======================================================================'
Write-Host ' AI-PACS  -  SOURCE build  -  lifecycle SHADOW observer ON'
Write-Host '======================================================================'
Write-Host (' Repo   : {0}' -f $Repo)
Write-Host (' Python : {0}' -f $Py)
Write-Host (' Flag   : AIPACS_LIFECYCLE_THUMBS = {0}' -f $env:AIPACS_LIFECYCLE_THUMBS)
Write-Host (' Log    : {0}' -f $AppLog)
Write-Host '----------------------------------------------------------------------'
Write-Host ' After it loads: sign in, click patients (include the ones that'
Write-Host ' sometimes fail; try a fast  A -> B -> A ). Then look in app.log for:'
Write-Host '   [LIFECYCLE] ... ->thumbs_ready'
Write-Host '   [LIFECYCLE-SHADOW] legacy_discard reason=stale_token parked_series=N'
Write-Host '======================================================================'
Write-Host ''

# --- Optional: 2nd window live-tailing the shadow log ----------------------
if ($TailLog) {
    if (Test-Path -LiteralPath $AppLog) {
        Start-Process powershell -ArgumentList @(
            '-NoExit', '-Command',
            "Get-Content -LiteralPath `"$AppLog`" -Tail 5 -Wait | Select-String -Pattern 'LIFECYCLE'"
        )
    } else {
        Write-Warning "Log not present yet; re-run with -TailLog after the app has started once."
    }
}

# --- Launch (foreground; CWD = repo so config/ and user_data/ resolve) ------
Set-Location -LiteralPath $Repo
& $Py $Main
$code = $LASTEXITCODE

Write-Host ''
Write-Host ("AI-PACS exited with code {0}." -f $code)
exit $code

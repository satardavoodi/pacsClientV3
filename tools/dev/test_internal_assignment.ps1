<#
.SYNOPSIS
    Enable + test the Internal-Center (INO) Assignment feature on the SOURCE build.

.DESCRIPTION
    One-shot helper to validate the internal-assignment work:
      1. Turns the feature ON for this session (AIPACS_INO_ASSIGNMENT=1).
      2. Syncs the education plugin mirror (assign_dialog.py was edited).
      3. Runs the targeted offscreen tests (network / assignment / notifications).
      4. Launches the SOURCE build (main.py via the repo venv) for GUI testing.
      5. Tails the logs, filtered to the [ino-assignment] / [ino-approval] tags.

    Runs the SOURCE build ONLY (never the frozen exe / black AI-PACS icon), per
    the project rules. Human-assisted: log in + position the window yourself.

.PARAMETER BaseUrl
    Optional override for the INO assignment API base URL. Leave empty to use the
    configured Reception API base (recommended — /api/personnel + /api/AdminUser/
    getCenterUsers live there).

.PARAMETER SkipSync     Skip the plugin-mirror sync/verify.
.PARAMETER SkipTests    Skip pytest.
.PARAMETER NoLaunch     Run tests only; do not launch the app.
.PARAMETER TailLogs     After launch, follow the logs (Ctrl+C to stop).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\dev\test_internal_assignment.ps1
.EXAMPLE
    .\tools\dev\test_internal_assignment.ps1 -SkipSync -TailLogs
.EXAMPLE
    .\tools\dev\test_internal_assignment.ps1 -BaseUrl "http://81.16.117.196:8080"
#>

[CmdletBinding()]
param(
    [string]$BaseUrl = "",
    [switch]$SkipSync,
    [switch]$SkipTests,
    [switch]$NoLaunch,
    [switch]$TailLogs
)

$ErrorActionPreference = "Stop"

# --- Resolve repo root (this script lives in <root>\tools\dev) ---------------
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
Write-Host "Repo root: $RepoRoot" -ForegroundColor Cyan

# --- Pick the venv python (source build), else fall back to system python ----
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = Join-Path $RepoRoot "venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python) { throw "No Python found (.venv\Scripts\python.exe or python on PATH)." }
Write-Host "Python: $Python" -ForegroundColor Cyan

# --- 1) Enable the feature for THIS session ---------------------------------
$env:AIPACS_INO_ASSIGNMENT = "1"
if ($BaseUrl) { $env:AIPACS_INO_ASSIGNMENT_BASE_URL = $BaseUrl }
# Approval-flag status sync is already default-on; make it explicit here.
$env:AIPACS_INO_APPROVAL_SYNC = "1"
Write-Host "Feature flags: AIPACS_INO_ASSIGNMENT=1  AIPACS_INO_APPROVAL_SYNC=1" -ForegroundColor Green
if ($BaseUrl) { Write-Host "  AIPACS_INO_ASSIGNMENT_BASE_URL=$BaseUrl" -ForegroundColor Green }

# --- 2) Sync the education plugin mirror (assign_dialog.py was edited) --------
if (-not $SkipSync) {
    $sync   = Join-Path $RepoRoot "tools\dev\sync_plugin_mirrors.py"
    $verify = Join-Path $RepoRoot "tools\dev\verify_plugin_mirrors.py"
    if (Test-Path $sync) {
        Write-Host "`n[1/3] Syncing plugin mirrors..." -ForegroundColor Yellow
        & $Python $sync
        if (Test-Path $verify) { & $Python $verify }
    } else {
        Write-Warning "sync_plugin_mirrors.py not found - skipping mirror sync."
    }
}

# --- 3) Run the targeted tests (offscreen) -----------------------------------
if (-not $SkipTests) {
    Write-Host "`n[2/3] Running internal-assignment tests..." -ForegroundColor Yellow
    $tests = @(
        "tests/code/network/test_ino_assignment.py",
        "tests/code/network/test_ino_notifications.py",
        "tests/code/network/test_report_status_approval_flags.py",
        "tests/code/network/test_ino_report_workflow.py"
    ) | Where-Object { Test-Path (Join-Path $RepoRoot $_) }

    & $Python -m pytest @tests -q -p no:debugging
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Some tests failed (exit $LASTEXITCODE). Review above before GUI testing."
    } else {
        Write-Host "All targeted tests passed." -ForegroundColor Green
    }
}

# --- 4) Launch the SOURCE build ----------------------------------------------
if (-not $NoLaunch) {
    Write-Host "`n[3/3] Launching the SOURCE build (main.py)..." -ForegroundColor Yellow
    Write-Host @"
    Manual test checklist once the app is up (log in as the reading physician):
      Internal assignment (Assign column -> popup -> Internal tab):
        * Internal tab lists INO CENTER users in TWO LABELED GROUPS:
            - 'پزشکان (پرسنل مرکز) — Physicians'  (from /api/personnel)
            - 'کاربران مرکز (منشی/سایر) — Users / Secretaries' (from
              /api/AdminUser/getCenterUsers)
          NOT the two gmail consultation physicians.
        * External tab lists the AI-PACS WEBSITE registered users (from the
          /consultants registry) - it must NOT be empty.
        * Select an internal user -> Assign to selected -> succeeds (no Drive /
          no upload / no payment).
      Report status popup (Report column):
        * 'ارجاع داخلی مرکز' field shows current assignment + eligible users.
      Patient list:
        * Assigned-but-not-completed reporter name shows in RED; completed = GREEN.
      Permissions: if a restricted user assigns, a clear 'not permitted' message.
      Status sync: change a report status -> confirm it reflects on the INO web page.
"@ -ForegroundColor Cyan

    $main = Join-Path $RepoRoot "main.py"
    if ($TailLogs) {
        # Launch app in a background process, then follow the logs here.
        $proc = Start-Process -FilePath $Python -ArgumentList $main -PassThru -WorkingDirectory $RepoRoot
        Write-Host "App PID: $($proc.Id). Following logs (Ctrl+C to stop tailing; app keeps running)." -ForegroundColor Green
        $log = Join-Path $RepoRoot "user_data\logs\app.log"
        # Wait for the log to appear, then tail + filter for the assignment tags.
        for ($i = 0; $i -lt 30 -and -not (Test-Path $log); $i++) { Start-Sleep -Milliseconds 500 }
        if (Test-Path $log) {
            Get-Content $log -Tail 5 -Wait |
                Select-String -Pattern "ino-assignment|ino-approval|INOAssignment|RECEPTION_SERVER|REPORT_SAVE"
        } else {
            Write-Warning "Log not found yet at $log - open it manually once the app is running."
        }
    } else {
        # Foreground: blocks until the app closes (like pressing Play).
        & $Python $main
    }
}

Write-Host "`nDone." -ForegroundColor Cyan

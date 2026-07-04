# =============================================================================
#  AI-PACS — clean, traced launch of the SOURCE build
#  Captures MAIN_THREAD_STALL + stack traces to verify OPT-01 startup fixes.
#  Force-closes any lingering AI-PACS instances first (stale/untraced instances
#  are why app.log/viewer_diagnostics stopped advancing between runs), then
#  launches ONE traced source-build instance.
#  Rules: source build only (never the frozen exe / black icon), ONE instance.
#  Usage:  & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\run_app_stall_trace.ps1'
# =============================================================================

$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
Set-Location $repo

# 1) Stop any lingering AI-PACS instances (source python running main.py, or the
#    frozen aipacs.exe). Matches on the command line so unrelated python is left alone.
Write-Host "Closing any existing AI-PACS instances..." -ForegroundColor Yellow
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" |
    Where-Object { $_.CommandLine -match 'ai-pacs' -or $_.CommandLine -match 'main\.py' -or $_.Name -eq 'aipacs.exe' } |
    ForEach-Object {
        Write-Host ("  stopping PID {0}" -f $_.ProcessId) -ForegroundColor DarkYellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

# 1b) Back up the two KPI logs so THIS run starts with a clean, small log (fresh-log
#     discipline). Old logs are renamed, not deleted. Only runs when the app is closed.
$logsDir = Join-Path $repo 'user_data\logs'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
foreach ($name in 'app.log','viewer_diagnostics.log') {
    $p = Join-Path $logsDir $name
    if (Test-Path $p) {
        try { Rename-Item $p ($p + ".pretrace-$stamp") -ErrorAction Stop; Write-Host "  archived $name" -ForegroundColor DarkGray }
        catch { Write-Host "  (could not archive $name - still in use?)" -ForegroundColor DarkYellow }
    }
}

# 2) Enable the stall probe + stack-trace capture (this session only; nothing permanent)
$env:AIPACS_MAIN_THREAD_PROBE        = '1'    # emit MAIN_THREAD_STALL events
$env:AIPACS_MAIN_THREAD_TRACE        = '1'    # capture the freeze stack trace
$env:AIPACS_STALL_TRACE_THRESHOLD_MS = '200'  # trace stalls > 200 ms (default 400)
# Multi-study display-remap diagnostic (48912/48952 current-series-shows-previous).
# Log-only, no behaviour change; captures whether the series switch is entered with the
# requested key or an already-remapped offset key. Remove after the bug is pinned.
$env:AIPACS_SERIES_SWITCH_DIAG       = '1'
$env:AIPACS_VIEWPORT_LOAD_TRACE      = '1'    # deep per-drop resolved-study cross-check

# 3) Source-build Python (.venv); fall back to PATH python if absent
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "WARN: .venv python not found - using 'python' from PATH." -ForegroundColor Yellow
    $py = 'python'
}

# 4) Show app.log's time BEFORE launch — after startup it MUST be newer (proves the
#    traced instance is the one writing the KPI logs).
$log = Join-Path $repo 'user_data\logs\app.log'
if (Test-Path $log) { Write-Host ("app.log before launch: {0}" -f (Get-Item $log).LastWriteTime) -ForegroundColor DarkGray }

# 5) Launch ONE traced instance (streams startup log here; GUI opens; close it to stop)
Write-Host ("Python: {0}" -f $py) -ForegroundColor Cyan
Write-Host "Launching AI-PACS source build with tracing... (close the app window to stop)" -ForegroundColor Green
& $py main.py

# 6) After you close the app:
Write-Host ("app.log after run:   {0}" -f (Get-Item $log).LastWriteTime) -ForegroundColor Cyan
Write-Host "Stall traces: user_data\logs\viewer_diagnostics.log" -ForegroundColor Cyan

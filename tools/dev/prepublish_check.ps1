# =============================================================================
#  AI-PACS - PRE-PUBLISH validation gate  (ASCII only; PowerShell 5.1 safe)
#  1) Runs the guard-test suites for this release's changes.
#  2) Cleanly launches the traced SOURCE build (DEFAULT flags = published state:
#     the 4 collapsed optimizations ON; fast-sweep / expensive-TTL OFF).
#  3) After you close the app, scans user_data/logs for the health signals that
#     decide "OK to publish": crashes, during-use main-thread stalls, the
#     wrong-study identity gate, error spikes, and KPI health.
#  Source build only (never the frozen exe). Run ONE instance.
#  Usage:  & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\prepublish_check.ps1'
# =============================================================================

$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$logsDir = Join-Path $repo 'user_data\logs'

function Section($t) { Write-Host "`n==================== $t ====================" -ForegroundColor Cyan }

# ---------------------------------------------------------------------------
# STEP 1 - guard tests for this release
# ---------------------------------------------------------------------------
Section "STEP 1/3  Guard tests"
$tests = @(
  'tests\code\ui_services\test_startup_freeze_defer.py',
  'tests\code\ui_services\test_theme_apply_dedup.py',
  'tests\code\ui_services\test_status_refresh_dicom_only.py',
  'tests\code\ui_services\test_study_downloaded_cache.py',
  'tests\code\logging\test_telemetry_level_downgrade.py',
  'tests\code\system\test_fast_instance_sweep.py',
  'tests\code\system\test_instance_sweep_cheap_name.py',
  'tests\code\viewer\test_viewport_study_identity_gate.py',
  'tests\code\viewer\test_primary_series_poison_guard.py'
)
& $py -m pytest @tests -p no:debugging -q
$testsOk = ($LASTEXITCODE -eq 0)
if ($testsOk) { Write-Host "TESTS: PASS" -ForegroundColor Green }
else { Write-Host "TESTS: FAIL - do NOT publish until green" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# STEP 2 - clean, traced launch of the SOURCE build (publish-state flags)
# ---------------------------------------------------------------------------
Section "STEP 2/3  Launch traced source build"

Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" |
  Where-Object { $_.CommandLine -match 'ai-pacs' -or $_.CommandLine -match 'main\.py' -or $_.Name -eq 'aipacs.exe' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
foreach ($n in 'app.log','viewer_diagnostics.log') {
  $p = Join-Path $logsDir $n
  if (Test-Path $p) { Rename-Item $p ($p + ".prepublish-$stamp") -ErrorAction SilentlyContinue }
}
$dlLog = Join-Path $logsDir 'download_diagnostics.log'
$dlErrBefore = 0
if (Test-Path $dlLog) { $dlErrBefore = (Select-String -Path $dlLog -Pattern '\| ERROR ' -AllMatches).Count }

$env:AIPACS_MAIN_THREAD_PROBE        = '1'
$env:AIPACS_MAIN_THREAD_TRACE        = '1'
$env:AIPACS_STALL_TRACE_THRESHOLD_MS = '200'

Write-Host "Launching... exercise the REAL workflow, then CLOSE the app:" -ForegroundColor Green
Write-Host "  open several PATIENTS, switch SERIES, load a PREVIOUS EXAM, DOWNLOAD one study." -ForegroundColor Green
& $py main.py

# ---------------------------------------------------------------------------
# STEP 3 - log health check
# ---------------------------------------------------------------------------
Section "STEP 3/3  Log health check"
$vd  = Join-Path $logsDir 'viewer_diagnostics.log'
$app = Join-Path $logsDir 'app.log'
$issues = New-Object System.Collections.Generic.List[string]

function Grep($path, $pat) {
  if (Test-Path $path) { return (Select-String -Path $path -Pattern $pat -AllMatches).Count } else { return 0 }
}

# (a) fresh logs actually written by this run
$freshApp = (Test-Path $app) -and ((Get-Item $app).LastWriteTime.Date -eq (Get-Date).Date)
Write-Host ("Fresh app.log written this run: {0}" -f $freshApp)
if (-not $freshApp) { [void]$issues.Add("app.log was not written this run - the traced source build may not have launched") }

# (b) CRASHES - any is a hard blocker
$crash = (Grep $app 'access violation|0xc0000005|faulthandler|Windows fatal|exited unexpectedly') +
         (Grep $vd  'access violation|0xc0000005|faulthandler|Windows fatal|exited unexpectedly')
$crashColor = 'Green'; if ($crash -gt 0) { $crashColor = 'Red' }
Write-Host ("Crash / fatal markers: {0}" -f $crash) -ForegroundColor $crashColor
if ($crash -gt 0) { [void]$issues.Add("$crash crash/fatal marker(s) in the logs - BLOCK") }

# (c) WRONG-STUDY identity gate
$gateSkip = Grep $vd 'IDENTITY-GATE\] .*SKIP render'
$gateEval = Grep $vd 'IDENTITY-GATE\] eval'
Write-Host ("Viewport identity-gate: evals={0}  skips(blocked stomps)={1}" -f $gateEval, $gateSkip)

# (d) during-use main-thread stalls (startup stalls are expected + one-time)
$duringUse = @()
if (Test-Path $vd) {
  $duringUse = Select-String -Path $vd -Pattern 'MAIN_THREAD_STALL .*interaction_active=True' |
    ForEach-Object { if ($_.Line -match 'stall_duration_ms=([0-9.]+)') { [double]$Matches[1] } }
}
$duMax = 0
if ($duringUse.Count -gt 0) { $duMax = [math]::Round(($duringUse | Measure-Object -Maximum).Maximum) }
Write-Host ("During-use main-thread stalls: count={0}  max={1} ms" -f $duringUse.Count, $duMax)
if ($duMax -gt 800) { [void]$issues.Add("during-use stall max $duMax ms is high (over 800) - investigate before publish") }

# (e) new download errors this run (delta on the accumulating log)
$dlErrAfter = Grep $dlLog '\| ERROR '
$dlErrNew = $dlErrAfter - $dlErrBefore
Write-Host ("New download ERROR records this run: {0}" -f $dlErrNew)
if ($dlErrNew -gt 0) {
  [void]$issues.Add("$dlErrNew new download ERROR record(s) this run - review the sample below")
  Write-Host "  (last ERROR lines:)" -ForegroundColor DarkYellow
  Select-String -Path $dlLog -Pattern '\| ERROR ' | Select-Object -Last 5 |
    ForEach-Object { "   " + ($_.Line.Substring(0,[math]::Min(180,$_.Line.Length))) }
}

# (f) OPT-09 log hygiene - after a download, telemetry should be INFO not WARNING
$dlWarn = Grep $dlLog '\| WARNING '
Write-Host ("download_diagnostics WARNING total (want ~real warnings, not tens-of-thousands of telemetry): {0}" -f $dlWarn)

# (g) KPI sanity - TTFI present + healthy
$ttfi = $null
if (Test-Path $vd) { $ttfi = Select-String -Path $vd -Pattern 'TTFI .*total_ms=([0-9.]+)' | Select-Object -Last 1 }
if ($ttfi) {
  $idx = [math]::Max(0, $ttfi.Line.IndexOf('TTFI'))
  Write-Host ("KPI TTFI (last): {0}" -f $ttfi.Line.Substring($idx))
} else {
  Write-Host "KPI TTFI: none captured (did you open a series?)" -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
Section "VERDICT"
if (-not $testsOk) { [void]$issues.Insert(0, "guard tests FAILED") }
if ($issues.Count -eq 0) {
  Write-Host "PRE-PUBLISH CHECKS: PASS (no automated blockers found)." -ForegroundColor Green
  Write-Host "Still required before publish: your manual confirmation of CLINICAL behaviour" -ForegroundColor Yellow
  Write-Host "(patient/series nav, overlays, measurements, thumbnails, correct patient/series shown)," -ForegroundColor Yellow
  Write-Host "a current BACKUP, a ROLLBACK path, and your explicit go-ahead." -ForegroundColor Yellow
} else {
  Write-Host "PRE-PUBLISH CHECKS: ATTENTION - do not publish yet:" -ForegroundColor Red
  foreach ($it in $issues) { Write-Host ("  - " + $it) -ForegroundColor Red }
}
Write-Host ""

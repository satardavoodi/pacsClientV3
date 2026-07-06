# =============================================================================
#  AI-PACS - RELEASE VERIFICATION (N-1)  (ASCII only; PowerShell 5.1 safe)
#  Drives the "code-complete, needs-verification" OPT items to CLOSED in ONE run.
#   STEP 1  full release guard-test suite (offscreen).
#   STEP 2  traced source launch with the TWO default-off flags ENABLED, so they
#           get validated for promotion:
#             AIPACS_FAST_INSTANCE_SWEEP=1   (OPT-12 startup ppid snapshot)
#             AIPACS_STATUS_EXPENSIVE_TTL=1  (OPT-01 status-chip TTL reuse)
#   STEP 3  per-OPT log-signal checks (OPT-02/03/09/12/17/18 + crashes/stalls/KPIs).
#  Exercise a REAL session before closing the app: several patients, series switches,
#  a PREVIOUS EXAM on a multi-study patient, at least one DOWNLOAD, rapid A->B->A drags.
#  Usage:  & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\verify_release.ps1'
# =============================================================================

$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$logsDir = Join-Path $repo 'user_data\logs'
function Section($t) { Write-Host "`n==================== $t ====================" -ForegroundColor Cyan }
function Grep($path, $pat) { if (Test-Path $path) { return (Select-String -Path $path -Pattern $pat -AllMatches).Count } else { return 0 } }

# ---------------------------------------------------------------------------
Section "STEP 1/3  Full release guard-test suite"
$tests = @(
  'tests\code\ui_services\test_startup_freeze_defer.py',
  'tests\code\ui_services\test_theme_apply_dedup.py',
  'tests\code\ui_services\test_status_refresh_dicom_only.py',
  'tests\code\ui_services\test_study_downloaded_cache.py',
  'tests\code\logging\test_telemetry_level_downgrade.py',
  'tests\code\system\test_fast_instance_sweep.py',
  'tests\code\system\test_instance_sweep_cheap_name.py',
  'tests\code\viewer\test_viewport_study_identity_gate.py',
  'tests\code\viewer\test_primary_series_poison_guard.py',
  'tests\code\viewer\test_cache_study_identity.py',
  'tests\code\viewer\test_grow_lane_study_number_bind.py',
  'tests\code\download_manager\test_multistudy_identity_guards.py'
)
& $py -m pytest @tests -p no:debugging -q
$testsOk = ($LASTEXITCODE -eq 0)
if ($testsOk) { Write-Host "TESTS: PASS" -ForegroundColor Green } else { Write-Host "TESTS: FAIL - fix before closing" -ForegroundColor Red }

# ---------------------------------------------------------------------------
Section "STEP 2/3  Traced launch (both default-off flags ENABLED for validation)"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" |
  Where-Object { $_.CommandLine -match 'ai-pacs' -or $_.CommandLine -match 'main\.py' -or $_.Name -eq 'aipacs.exe' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
foreach ($n in 'app.log','viewer_diagnostics.log') { $p = Join-Path $logsDir $n; if (Test-Path $p) { Rename-Item $p ($p + ".verify-$stamp") -ErrorAction SilentlyContinue } }
$dlLog = Join-Path $logsDir 'download_diagnostics.log'
$dlErrBefore = Grep $dlLog '\| ERROR '
$dlWarnBefore = Grep $dlLog '\| WARNING '
$dlInfoBefore = Grep $dlLog '\| INFO '

$env:AIPACS_MAIN_THREAD_PROBE        = '1'
$env:AIPACS_MAIN_THREAD_TRACE        = '1'
$env:AIPACS_STALL_TRACE_THRESHOLD_MS = '200'
$env:AIPACS_FAST_INSTANCE_SWEEP        = '1'   # OPT-12 - validate the ppid snapshot
$env:AIPACS_STATUS_EXPENSIVE_TTL       = '1'   # OPT-01 - validate the status-chip TTL reuse
$env:AIPACS_GROW_LANE_STUDY_NUMBER_BIND = '1'  # OPT-06 - validate the study-scoped prev-exam grow bind
$env:AIPACS_LIFECYCLE_VERBOSE          = '1'   # surface [LIFECYCLE*] markers if gated

Write-Host "Launch OK. Do a REAL session, then CLOSE the app:" -ForegroundColor Green
Write-Host "  - open several patients; switch series; load a PREVIOUS EXAM on a multi-study patient" -ForegroundColor Green
Write-Host "  - DOWNLOAD at least one study; do a few rapid A->B->A series drags" -ForegroundColor Green
Write-Host "  - watch that nothing unexpected closes (VS Code / terminal) - that validates the fast sweep" -ForegroundColor Green
& $py main.py

# ---------------------------------------------------------------------------
Section "STEP 3/3  Per-OPT verification signals"
$vd = Join-Path $logsDir 'viewer_diagnostics.log'; $app = Join-Path $logsDir 'app.log'
$fail = New-Object System.Collections.Generic.List[string]

# global safety
$crash = (Grep $app 'access violation|0xc0000005|faulthandler|exited unexpectedly') + (Grep $vd 'access violation|0xc0000005|faulthandler|exited unexpectedly')
$c1='Green'; if ($crash -gt 0){$c1='Red'; [void]$fail.Add("crashes=$crash")}
Write-Host ("[safety]  crashes/fatal: {0}" -f $crash) -ForegroundColor $c1
$du = @(); if (Test-Path $vd) { $du = Select-String -Path $vd -Pattern 'MAIN_THREAD_STALL .*interaction_active=True' | ForEach-Object { if ($_.Line -match 'stall_duration_ms=([0-9.]+)') { [double]$Matches[1] } } }
$duMax=0; if ($du.Count){$duMax=[math]::Round(($du|Measure-Object -Maximum).Maximum)}
Write-Host ("[safety]  during-use stalls: count={0} max={1} ms" -f $du.Count,$duMax)
if ($duMax -gt 800){[void]$fail.Add("during-use stall max ${duMax}ms")}

# OPT-17 / OPT-20 viewer display integrity.
#   CORRECTED 2026-07-05: 'ViewportLoadingStateCleared series=None' is NOT a display miss.
#   It is _hide_spinner_for_widget logging _awaiting_series_number, which is None AFTER a
#   successful load (awaiting already reset). Verified: every series=None clear followed a
#   successful open_series + first_image_visible. The TRUE failure signals are:
#     - ViewportLoadFailed (the load path gave up), and
#     - ViewportLoadingStateCleared with a NON-None series (spinner cleared while STILL awaiting).
$ge = Grep $vd 'IDENTITY-GATE\] eval'; $gs = Grep $vd 'IDENTITY-GATE\] .*SKIP render'
$loadFailed = Grep $vd 'ViewportLoadFailed'
$clrAwaiting = 0
if (Test-Path $vd) { $clrAwaiting = (Select-String -Path $vd -Pattern 'ViewportLoadingStateCleared' | Where-Object { $_.Line -notmatch 'series=None' }).Count }
$firstImg = Grep $vd 'first_image_visible series='
$benignClear = Grep $vd 'ViewportLoadingStateCleared .*series=None'
Write-Host ("[OPT-17]  identity-gate evals={0} skips={1}" -f $ge,$gs)
Write-Host ("[OPT-20]  REAL display failures: ViewportLoadFailed={0} cleared-while-awaiting={1} (both want 0) ; successful first-images={2} ; benign series=None clears={3}" -f $loadFailed,$clrAwaiting,$firstImg,$benignClear)
if (($loadFailed + $clrAwaiting) -gt 0) { [void]$fail.Add("viewport display failures=$($loadFailed + $clrAwaiting)"); Write-Host "          -> a REAL display miss occurred; grep ViewportLoadFailed / non-None ViewportLoadingStateCleared for the series + study" -ForegroundColor Red }
else { Write-Host "          -> no real display failures (series=None clears are benign post-success spinner hides)" -ForegroundColor Green }

# OPT-02 Seam A - token-stale thumbnail render (kills "only first thumbnail").
#   TRIGGER: click patient A, immediately B, immediately back to A (rapid A->B->A), on a
#   patient with several series so the thumbnail fetch is still in flight on the way back.
$seamA = Grep $vd 'LIFECYCLE-CUTOVER\] rendered token-stale ACTIVE'
$shadow = Grep $vd 'thumbs_ready'
Write-Host ("[OPT-02]  Seam A token-stale renders: {0} (shadow thumbs_ready={1})" -f $seamA,$shadow)
if ($seamA -gt 0) { Write-Host "          -> CUTOVER fired: stale-but-correct thumbnails rendered (fix active)" -ForegroundColor Green }
else { Write-Host "          -> not triggered this run; force it with a rapid A->B->A patient switch" -ForegroundColor DarkYellow }
# OPT-03 Seam B - previous-exam grow keep-alive (kills "second drag needed").
#   TRIGGER: open a multi-study / previous-exam patient on a SLOW/dropping link and drag a
#   previous-exam series; the series must FINISH + display without a second drag.
$seamB = Grep $vd 'LIFECYCLE-CUTOVER\] seam_b watchdog kept alive'
$grow = Grep $vd 'watchdog_grow|GROW-DISPLAYED'
Write-Host ("[OPT-03]  Seam B watchdog-kept-alive: {0} (grow activity={1})" -f $seamB,$grow)
if ($seamB -gt 0) { Write-Host "          -> CUTOVER fired: dropped-notification grow kept alive (fix active)" -ForegroundColor Green }
else { Write-Host "          -> not triggered this run; needs a dropped progress event (slow link). If prev-exam series still finished on the FIRST drag, the symptom is absent = also OK" -ForegroundColor DarkYellow }

# OPT-06 study-scoped grow-lane bind (flag ENABLED this run) - the PROPER fix for the
#   "series N shows in current AND previous exam / needs a 2nd drag" report.
#   TRIGGER: open a multi-study / previous-exam patient and drag a PREVIOUS-EXAM series;
#   it must grow on the FIRST drag. bound>0 = the study-scoped fallback rescued a series
#   the series_uid match could not; unmatched should be low (fewer than the pre-fix run).
$studyNumBind = Grep $vd 'GROW-LANE-STUDYNUM-BIND\] bound'
$laneUnmatched = Grep $vd 'GROW-LANE-TRACE\]'
Write-Host ("[OPT-06]  study-scoped grow binds: {0} ; grow-lane UNMATCHED traces: {1}" -f $studyNumBind,$laneUnmatched)
if ($studyNumBind -gt 0) { Write-Host "          -> FIX ACTIVE: previous-exam series bound by (study_uid,series_number) after series_uid miss" -ForegroundColor Green }
else { Write-Host "          -> no study-scoped bind fired; if you dragged a prev-exam series and it grew on the FIRST drag, series_uid matched (also OK). If it needed a 2nd drag, paste the [GROW-LANE-TRACE] lines (they now carry full uids + ev_num)" -ForegroundColor DarkYellow }

# OPT-18  DB owner enforcement (should be absent/rare on conformant data)
$reassign = (Grep $app 'CrossStudyReassignment|CrossPatientReassignment') + (Grep $vd 'CrossStudyReassignment|CrossPatientReassignment') + (Grep (Join-Path $logsDir 'db_diagnostics.log') 'CrossStudyReassignment|CrossPatientReassignment')
Write-Host ("[OPT-18]  owner-reassignment events (0 = clean; >0 = guard blocked a duplicate-UID repoint): {0}" -f $reassign)

# OPT-12 fast sweep  (startup :387 psutil stall should be gone; nothing wrongly killed)
$s387 = Grep $vd 'single_instance_lock.py\", line 387'
Write-Host ("[OPT-12]  startup single_instance_lock:387 stall traces: {0} (want 0)" -f $s387)

# OPT-01 expensive-TTL  (flag on this run) - status still correct = your visual check
Write-Host "[OPT-01]  status-chip TTL reuse ENABLED this run - confirm DCM/DOC/VOC/AI chips still update promptly (visual)."

# OPT-09  download telemetry hygiene  (new telemetry should be INFO, not WARNING)
$dlErrNew = (Grep $dlLog '\| ERROR ') - $dlErrBefore
$dlWarnNew = (Grep $dlLog '\| WARNING ') - $dlWarnBefore
$dlInfoNew = (Grep $dlLog '\| INFO ') - $dlInfoBefore
Write-Host ("[OPT-09]  download_diagnostics this run: +{0} INFO, +{1} WARNING, +{2} ERROR" -f $dlInfoNew,$dlWarnNew,$dlErrNew)
if ($dlInfoNew -eq 0 -and $dlWarnNew -gt 50){ Write-Host "          -> telemetry still WARNING (downgrade NOT active) - OPT-09 needs a fix" -ForegroundColor DarkYellow }
elseif ($dlInfoNew -gt 0){ Write-Host "          -> telemetry now INFO (OPT-09 working)" -ForegroundColor Green }

# KPI
$ttfi = $null; if (Test-Path $vd){ $ttfi = Select-String -Path $vd -Pattern 'TTFI .*total_ms=([0-9.]+)' | Select-Object -Last 1 }
if ($ttfi){ $i=[math]::Max(0,$ttfi.Line.IndexOf('TTFI')); Write-Host ("[KPI]     "+$ttfi.Line.Substring($i)) }

Section "VERDICT"
if (-not $testsOk){ [void]$fail.Insert(0,"guard tests FAILED") }
if ($fail.Count -eq 0){
  Write-Host "VERIFICATION: PASS (no automated blockers). Paste STEP 3 to close the items." -ForegroundColor Green
} else {
  Write-Host "VERIFICATION: review needed:" -ForegroundColor Yellow
  foreach ($f in $fail){ Write-Host ("  - "+$f) -ForegroundColor Yellow }
}
Write-Host ""

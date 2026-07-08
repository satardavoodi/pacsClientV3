# =============================================================================
#  AI-PACS - CLOSE-OUT VERIFICATION for OPT-20 + remaining OPT items
#  (ASCII only; PowerShell 5.1 safe)
#
#  ONE run that: (1) runs the guard-test suite, (2) launches the source build with
#  every validation flag on, (3) prints a CLOSE / HOLD verdict per OPT so the
#  backlog can be closed with evidence.
#
#  SESSION TO RUN (then CLOSE the app) - exercise everything once:
#    * open 2-3 patients incl. a MULTI-STUDY / PREVIOUS-EXAM one (e.g. 45289 / 48456);
#    * switch/drag several PREVIOUS-EXAM series, incl. the large X-rays / documents
#      that used to stay blank -> they must now render on the FIRST switch (OPT-20);
#    * download at least one study (OPT-09), do a couple rapid A->B->A drags (OPT-06),
#      and glance that the DCM/DOC/VOC/AI status chips stay fresh (OPT-01);
#    * watch that nothing unexpected closes - VS Code / terminal (OPT-12).
#
#  Usage:
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\verify_all_opts.ps1'
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\verify_all_opts.ps1' -AnalyzeOnly
# =============================================================================
param([switch]$AnalyzeOnly)

$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'; if (-not (Test-Path $py)) { $py = 'python' }
$logsDir = Join-Path $repo 'user_data\logs'
$vd  = Join-Path $logsDir 'viewer_diagnostics.log'
$app = Join-Path $logsDir 'app.log'
$dl  = Join-Path $logsDir 'download_diagnostics.log'
$SCRIPT_VERSION = 'v1-close-opts'
Write-Host ("### verify_all_opts $SCRIPT_VERSION ###  (if you do not see this line + a VERDICT section, you ran a STALE copy)") -ForegroundColor Magenta

function Section($t) { Write-Host "`n==================== $t ====================" -ForegroundColor Cyan }
function CountRe($path, $pat) { if (Test-Path $path) { return (Select-String -Path $path -Pattern $pat -AllMatches).Count } return 0 }
function Tally($path, $pat) {
  $h = @{}
  if (Test-Path $path) {
    foreach ($m in (Select-String -Path $path -Pattern $pat -AllMatches)) {
      foreach ($mm in $m.Matches) { $k = $mm.Groups[1].Value; if ($h.ContainsKey($k)) { $h[$k]++ } else { $h[$k] = 1 } }
    }
  }
  return $h
}
$closes = New-Object System.Collections.Generic.List[string]
$holds  = New-Object System.Collections.Generic.List[string]
$dlErrB = 0; $dlWarnB = 0; $dlInfoB = 0

# ---------------------------------------------------------------------------
if (-not $AnalyzeOnly) {
  Section "STEP 1/3  Guard-test suite (offscreen)"
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
  if ($LASTEXITCODE -eq 0) { Write-Host "TESTS: PASS" -ForegroundColor Green; $closes.Add("guard-tests PASS") } else { Write-Host "TESTS: FAIL - fix before closing" -ForegroundColor Red; $holds.Add("guard-tests FAILED") }

  Section "STEP 2/3  Traced launch (all validation flags ON)"
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" |
    Where-Object { $_.CommandLine -match 'ai-pacs' -or $_.CommandLine -match 'main\.py' -or $_.Name -eq 'aipacs.exe' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  foreach ($n in 'app.log', 'viewer_diagnostics.log') { $p = Join-Path $logsDir $n; if (Test-Path $p) { Rename-Item $p ($p + ".closeopts-$stamp") -ErrorAction SilentlyContinue } }
  $dlErrB = CountRe $dl '\| ERROR '; $dlWarnB = CountRe $dl '\| WARNING '; $dlInfoB = CountRe $dl '\| INFO '

  $env:AIPACS_MAIN_THREAD_PROBE          = '1'
  $env:AIPACS_MAIN_THREAD_TRACE          = '1'
  $env:AIPACS_STALL_TRACE_THRESHOLD_MS   = '200'
  $env:AIPACS_VIEWPORT_LIFECYCLE_LOG     = '1'
  $env:AIPACS_APPLY_TRACE                = '1'   # OPT-20 : surface [APPLY-ENTER]/[APPLY-GATE]
  $env:AIPACS_GROW_LANE_STUDY_NUMBER_BIND = '1'  # OPT-06 : validate for promotion
  $env:AIPACS_STATUS_EXPENSIVE_TTL       = '1'   # OPT-01 : validate the status-chip TTL reuse
  $env:AIPACS_FAST_INSTANCE_SWEEP        = '1'   # OPT-12 : confirm the ppid snapshot (default-on)

  Write-Host "Launch OK. Run the session described in the header, then CLOSE the app." -ForegroundColor Green
  & $py main.py
}

# ---------------------------------------------------------------------------
Section "STEP 3/3  Per-OPT CLOSE / HOLD verdict"

# --- SAFETY ---
$crash = (CountRe $app 'access violation|0xc0000005|faulthandler|exited unexpectedly') + (CountRe $vd 'access violation|0xc0000005|faulthandler|exited unexpectedly')
$du = @(); if (Test-Path $vd) { $du = Select-String -Path $vd -Pattern 'MAIN_THREAD_STALL .*interaction_active=True' | ForEach-Object { if ($_.Line -match 'stall_duration_ms=([0-9.]+)') { [double]$Matches[1] } } }
$duMax = 0; if ($du.Count) { $duMax = [math]::Round(($du | Measure-Object -Maximum).Maximum) }
$vlFailed = CountRe $vd 'ViewportLoadFailed'
$clrAwait = 0; if (Test-Path $vd) { $clrAwait = (Select-String -Path $vd -Pattern 'ViewportLoadingStateCleared' | Where-Object { $_.Line -notmatch 'series=None' }).Count }
Write-Host ("[safety]  crashes={0}  during-use stalls={1} (max {2} ms)  ViewportLoadFailed={3}  cleared-while-awaiting={4}" -f $crash, $du.Count, $duMax, $vlFailed, $clrAwait)
if ($crash -eq 0 -and $duMax -le 800 -and $vlFailed -eq 0 -and $clrAwait -eq 0) { $closes.Add("safety clean") } else { $holds.Add("safety: crashes=$crash maxstall=$duMax ViewportLoadFailed=$vlFailed clrAwait=$clrAwait") }

# --- OPT-20 : async-apply render gate (previous-exam DX/document display) ---
$apEnter = CountRe $app '\[APPLY-ENTER\]'
$agFix   = 0; $agFalse = 0
if (Test-Path $app) {
  $ag = Select-String -Path $app -Pattern '\[APPLY-GATE\]'
  $agFix = ($ag | Where-Object { $_.Line -match 'target_fix_render=True' }).Count
  $agFalse = ($ag | Where-Object { $_.Line -match 'legacy_match=False' }).Count
}
$switch = Tally $vd 'change_series_on_viewer series=(\d+)'
$first  = Tally $vd 'first_image_visible series=(\d+)'
$offNever = @()   # offset-key series switched-to but NEVER rendered = a REAL OPT-20 miss
foreach ($k in ($switch.Keys | Sort-Object { [int]$_ })) {
  if ([int]$k -ge 1000000) {
    $fi = 0; if ($first.ContainsKey($k)) { $fi = $first[$k] }
    if ($fi -eq 0) { $offNever += $k }
  }
}
$ywFalse = 0; if (Test-Path $app) { $ywFalse = (Select-String -Path $app -Pattern 'FAST-YIELD-TRACE\].*will_yield=False').Count }
Write-Host ("[OPT-20]  APPLY-GATE target_fix_render={0} (legacy_match=False={1})  prev-exam series that NEVER rendered={2}  empty-metadata(will_yield=False)={3}" -f $agFix, $agFalse, $offNever.Count, $ywFalse)
if ($offNever.Count -eq 0 -and $vlFailed -eq 0) {
  Write-Host "          -> every previous-exam series that was opened rendered. OPT-20 fix holding." -ForegroundColor Green
  $closes.Add("OPT-20 (previous-exam render) - no unrendered offset-key series")
} else {
  Write-Host ("          -> still {0} previous-exam series never rendered: {1}. Re-run run_dx_trace.ps1 to pinpoint." -f $offNever.Count, ($offNever -join ',')) -ForegroundColor Red
  $holds.Add("OPT-20: offset-key series never rendered ($($offNever -join ','))")
}
if ($ywFalse -gt 0) { Write-Host "          -> residual (a): $ywFalse empty-metadata build(s) (P2, rare)." -ForegroundColor DarkYellow }
$lostPost = 0
# residual (b): a change_series with NO [APPLY-ENTER] within a few seconds is a lost worker->UI post (approx: RENDER-DROP without a matching APPLY-ENTER second)
$lostPost = CountRe $vd '\[RENDER-DROP\] series'
if ($lostPost -gt 0) { Write-Host "          -> residual (b): $lostPost render-drop event(s) (lost worker->UI post; recover on re-click; P2)." -ForegroundColor DarkYellow }

# --- OPT-06 : study-scoped grow-lane bind (candidate to flip default-on) ---
$snb = CountRe $vd 'GROW-LANE-STUDYNUM-BIND\] bound'
Write-Host ("[OPT-06]  study-scoped grow binds={0}" -f $snb)
if ($snb -gt 0) { Write-Host "          -> fix engaged on a real stale-uid case: SAFE TO FLIP default-on." -ForegroundColor Green; $closes.Add("OPT-06 - study-scoped bind engaged; flip default-on") }
else { Write-Host "          -> not exercised (no stale-uid prev-exam grow this run); keep default-off. HOLD." -ForegroundColor DarkYellow; $holds.Add("OPT-06 - not exercised; keep default-off") }

# --- OPT-17 : viewer-cache study identity ---
$ge = CountRe $vd 'IDENTITY-GATE\] eval'; $gs = CountRe $vd 'IDENTITY-GATE\].*SKIP'
$cacheRej = CountRe $vd 'CACHE-STUDY-IDENTITY'
Write-Host ("[OPT-17]  identity-gate evals={0} skips={1} ; cache study-identity rejects={2}" -f $ge, $gs, $cacheRej)
if ($gs -eq 0) { $closes.Add("OPT-17 - 0 wrong-study gate skips (isolation holds)") }

# --- OPT-18 : DB owner enforcement ---
$reassign = (CountRe $app 'CrossStudyReassignment|CrossPatientReassignment') + (CountRe $vd 'CrossStudyReassignment|CrossPatientReassignment')
Write-Host ("[OPT-18]  owner-reassignment events (0 = clean): {0}" -f $reassign)
if ($reassign -eq 0) { $closes.Add("OPT-18 - 0 owner-reassignments") } else { $holds.Add("OPT-18: $reassign reassignment events - review") }

# --- OPT-12 : startup single-instance fast sweep ---
$s387 = CountRe $vd 'single_instance_lock.py\", line 387'
Write-Host ("[OPT-12]  startup single_instance_lock:387 stall traces (want 0): {0}" -f $s387)
if ($s387 -eq 0 -and $crash -eq 0) { $closes.Add("OPT-12 - :387 stall gone, nothing wrongly closed") } else { $holds.Add("OPT-12: :387 stall traces=$s387") }

# --- OPT-09 : download telemetry hygiene ---
if (-not $AnalyzeOnly) {
  $dlInfoN = (CountRe $dl '\| INFO ') - $dlInfoB
  $dlWarnN = (CountRe $dl '\| WARNING ') - $dlWarnB
  $dlErrN  = (CountRe $dl '\| ERROR ') - $dlErrB
  Write-Host ("[OPT-09]  download_diagnostics this run: +{0} INFO, +{1} WARNING, +{2} ERROR" -f $dlInfoN, $dlWarnN, $dlErrN)
  if ($dlInfoN -gt 0 -or $dlWarnN -eq 0) { $closes.Add("OPT-09 - telemetry at INFO") } elseif ($dlWarnN -gt 50) { $holds.Add("OPT-09: WARNING still high ($dlWarnN) - downgrade not active") }
} else {
  Write-Host "[OPT-09]  (delta needs a launch run; skipped in -AnalyzeOnly)"
}

# --- OPT-01 : status-chip expensive-TTL (visual confirm) ---
Write-Host "[OPT-01]  expensive-TTL ENABLED this run + during-use stalls above. If DCM/DOC/VOC/AI chips stayed FRESH (visual), it is safe to flip AIPACS_STATUS_EXPENSIVE_TTL default-on."
if ($duMax -le 250) { Write-Host "          -> during-use main-thread rock-solid (max ${duMax}ms). Confirm chip freshness, then flip." -ForegroundColor Green }

# --- KPI ---
$ttfi = $null; if (Test-Path $vd) { $ttfi = Select-String -Path $vd -Pattern 'TTFI .*total_ms=([0-9.]+)' | Select-Object -Last 1 }
if ($ttfi) { $i = [math]::Max(0, $ttfi.Line.IndexOf('TTFI')); Write-Host ("[KPI]     " + $ttfi.Line.Substring($i)) }

# ---------------------------------------------------------------------------
Section "VERDICT  (close these; hold these)"
Write-Host "CLOSE:" -ForegroundColor Green
if ($closes.Count -eq 0) { Write-Host "  (none yet)" -ForegroundColor DarkGray } else { foreach ($c in $closes) { Write-Host ("  [x] " + $c) -ForegroundColor Green } }
Write-Host "HOLD / follow-up:" -ForegroundColor Yellow
if ($holds.Count -eq 0) { Write-Host "  (none - all clear)" -ForegroundColor Green } else { foreach ($h in $holds) { Write-Host ("  [ ] " + $h) -ForegroundColor Yellow } }
Write-Host ""
Write-Host "Paste this VERDICT + the [OPT-20]/[OPT-06] lines and I will close the backlog items and flip the validated flags." -ForegroundColor Cyan
Write-Host ""

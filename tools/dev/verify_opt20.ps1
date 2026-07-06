# =============================================================================
#  AI-PACS - OPT-20 RE-DROP TEST + focused re-verify   (ASCII only; PS 5.1 safe)
#
#  WHY: the old "display-miss(series=None)" count was a FALSE metric. The spinner
#  clear logs _awaiting_series_number, which is None AFTER a successful load. The
#  REAL display miss = a series you switched to that NEVER produced first_image_visible.
#  This script computes that directly (per-series switch vs first-image tally),
#  ignores the benign series=None clears, and for any real miss auto-detects the
#  stale-mid-download-cache signature (itk files=N vs fresh disk_file_count=M) and
#  prints the resolution proof from BOTH log channels.
#
#  MODES:
#    (default)        kill + rotate logs + launch the source build, you run the
#                     session and CLOSE the app, then it analyzes THIS run only.
#    -AnalyzeOnly     do not launch; analyze the current logs (use if you already
#                     ran the app from VS Code).
#
#  OPT-20 SESSION (the point of this run):
#    * Open the multi-study / previous-exam patient.
#    * Drag the SLOT-1 previous-exam series that failed before (the ~13.5 MB X-ray).
#      It is fully downloaded now, so it MUST show its image on the FIRST drag.
#    * For coverage also: switch several current + previous series, download one
#      study, and do one rapid A->B->A drag.
#
#  Usage:
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\verify_opt20.ps1'
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\verify_opt20.ps1' -AnalyzeOnly
# =============================================================================
param([switch]$AnalyzeOnly)

$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'; if (-not (Test-Path $py)) { $py = 'python' }
$logsDir = Join-Path $repo 'user_data\logs'
$vd  = Join-Path $logsDir 'viewer_diagnostics.log'
$app = Join-Path $logsDir 'app.log'
$dl  = Join-Path $logsDir 'download_diagnostics.log'

function Section($t) { Write-Host "`n==================== $t ====================" -ForegroundColor Cyan }
function CountRe($path, $pat) { if (Test-Path $path) { return (Select-String -Path $path -Pattern $pat -AllMatches).Count } return 0 }
function LastLines($path, $pat, $n) { if (Test-Path $path) { return (Select-String -Path $path -Pattern $pat | Select-Object -Last $n | ForEach-Object { $_.Line }) } return @() }
function Tally($path, $pat) {
  $h = @{}
  if (Test-Path $path) {
    foreach ($m in (Select-String -Path $path -Pattern $pat -AllMatches)) {
      foreach ($mm in $m.Matches) { $k = $mm.Groups[1].Value; if ($h.ContainsKey($k)) { $h[$k]++ } else { $h[$k] = 1 } }
    }
  }
  return $h
}

$dlErrB = 0; $dlWarnB = 0; $dlInfoB = 0

if (-not $AnalyzeOnly) {
  Section "LAUNCH  (rotate logs so analysis is THIS run only)"
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" |
    Where-Object { $_.CommandLine -match 'ai-pacs' -or $_.CommandLine -match 'main\.py' -or $_.Name -eq 'aipacs.exe' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  foreach ($n in 'app.log', 'viewer_diagnostics.log') { $p = Join-Path $logsDir $n; if (Test-Path $p) { Rename-Item $p ($p + ".opt20-$stamp") -ErrorAction SilentlyContinue } }
  $dlErrB = CountRe $dl '\| ERROR '; $dlWarnB = CountRe $dl '\| WARNING '; $dlInfoB = CountRe $dl '\| INFO '

  $env:AIPACS_MAIN_THREAD_PROBE = '1'
  $env:AIPACS_MAIN_THREAD_TRACE = '1'
  $env:AIPACS_STALL_TRACE_THRESHOLD_MS = '200'
  $env:AIPACS_GROW_LANE_STUDY_NUMBER_BIND = '1'   # OPT-06 study-scoped bind
  $env:AIPACS_FAST_INSTANCE_SWEEP = '1'           # OPT-12 fast sweep
  $env:AIPACS_VIEWPORT_LIFECYCLE_LOG = '1'        # ensure Viewport* lifecycle events log

  Write-Host "Run the OPT-20 session, then CLOSE the app:" -ForegroundColor Green
  Write-Host "  1) open the multi-study / previous-exam patient" -ForegroundColor Green
  Write-Host "  2) DRAG the slot-1 previous-exam X-ray that failed before (now fully downloaded)" -ForegroundColor Green
  Write-Host "     -> it must show on the FIRST drag" -ForegroundColor Green
  Write-Host "  3) also: switch a few current + previous series, download one study, one A->B->A" -ForegroundColor Green
  & $py main.py
}

# ---------------------------------------------------------------------------
Section "SAFETY"
$crash = (CountRe $app 'access violation|0xc0000005|faulthandler|exited unexpectedly') + (CountRe $vd 'access violation|0xc0000005|faulthandler|exited unexpectedly')
$c1 = 'Green'; if ($crash -gt 0) { $c1 = 'Red' }
Write-Host ("crashes/fatal: {0}" -f $crash) -ForegroundColor $c1
$du = @(); if (Test-Path $vd) { $du = Select-String -Path $vd -Pattern 'MAIN_THREAD_STALL .*interaction_active=True' | ForEach-Object { if ($_.Line -match 'stall_duration_ms=([0-9.]+)') { [double]$Matches[1] } } }
$duMax = 0; if ($du.Count) { $duMax = [math]::Round(($du | Measure-Object -Maximum).Maximum) }
Write-Host ("during-use stalls: count={0} max={1} ms" -f $du.Count, $duMax)

# ---------------------------------------------------------------------------
Section "OPT-20  Per-series render integrity (the REAL display-miss test)"
$switch = Tally $vd 'change_series_on_viewer series=(\d+)'
$first  = Tally $vd 'first_image_visible series=(\d+)'
$loadFailed = CountRe $vd 'ViewportLoadFailed'
$clrAwait = 0; if (Test-Path $vd) { $clrAwait = (Select-String -Path $vd -Pattern 'ViewportLoadingStateCleared' | Where-Object { $_.Line -notmatch 'series=None' }).Count }
$benign = CountRe $vd 'ViewportLoadingStateCleared .*series=None'
Write-Host ("Real failure signals: ViewportLoadFailed={0}  cleared-while-awaiting={1}  (both want 0)" -f $loadFailed, $clrAwait)
$renderDrop = CountRe $vd 'RENDER-DROP\]'
$renderDropPrev = 0; if (Test-Path $vd) { $renderDropPrev = (Select-String -Path $vd -Pattern 'RENDER-DROP\]' | Where-Object { $_.Line -match 'previous_exam=True' }).Count }
$rdColor = 'DarkGray'; if ($renderDrop -gt 0) { $rdColor = 'Red' }
Write-Host ("Render-drop detector: [RENDER-DROP] events={0} (of which previous-exam={1}) -- load completed but repaint dropped" -f $renderDrop, $renderDropPrev) -ForegroundColor $rdColor
if ($renderDrop -gt 0) { Write-Host "          -> CONFIRMS the render-drop defect at the exact event; each names series/viewer/waited_ms. Fix = render-convergence (OPT-04)." -ForegroundColor Red }
Write-Host ("Benign series=None spinner clears (post-success, NOT misses): {0}" -f $benign) -ForegroundColor DarkGray
Write-Host ""

$suspects = @()       # never rendered (first_images == 0)
$intermittent = @()   # rendered on SOME switches but not all (0 < first < switches) on an offset key
foreach ($k in ($switch.Keys | Sort-Object { [int]$_ })) {
  $sw = $switch[$k]
  $fi = 0; if ($first.ContainsKey($k)) { $fi = $first[$k] }
  $isOffset = ([int]$k -ge 1000000)   # offset display key = a previous-exam / secondary-study series
  $tag = ''; if ($isOffset) { $tag = '  [previous-exam]' }
  $line = ("  series={0,-9} switches={1,-3} first_images={2}{3}" -f $k, $sw, $fi, $tag)
  if ($fi -eq 0) { Write-Host $line -ForegroundColor Red; $suspects += $k }
  elseif ($fi -lt $sw) {
    # rendered sometimes, missed other switches. On an OFFSET key that is the real
    # previous-exam intermittent-render defect; on a PRIMARY key it may be a benign
    # re-selection of an already-shown series (no new first_image needed).
    if ($isOffset) { Write-Host ($line + '  <- INTERMITTENT (real miss)') -ForegroundColor Red; $intermittent += $k }
    else { Write-Host ($line + '  <- partial (maybe benign re-selection)') -ForegroundColor DarkYellow }
  }
  else { Write-Host $line -ForegroundColor Green }
}
Write-Host ""
$realMiss = @($suspects) + @($intermittent)
if ($realMiss.Count -eq 0) {
  Write-Host "OPT-20 VERDICT: every series rendered on every switch -> NO display miss. PASS." -ForegroundColor Green
}
else {
  Write-Host ("OPT-20 VERDICT: {0} series with a REAL display miss (never / intermittently rendered): {1}" -f $realMiss.Count, ($realMiss -join ',')) -ForegroundColor Red
  Write-Host "  ROOT (2026-07-06): DX / single-frame previous-exam series from certain studies do not render. NOT contention (check stalls below) - a data/state-specific FAST metadata-build-or-render failure. See [FAST-YIELD-TRACE] per suspect." -ForegroundColor Red
  $st = @(); if (Test-Path $vd) { $st = Select-String -Path $vd -Pattern 'MAIN_THREAD_STALL .*stall_duration_ms=([0-9.]+)' | ForEach-Object { [double]$_.Matches[0].Groups[1].Value } }
  $stMax = 0; if ($st.Count) { $stMax = [math]::Round(($st | Measure-Object -Maximum).Maximum) }
  Write-Host ("  main-thread stalls this run: {0} (max {1} ms) -- if 0, contention is ruled OUT (the DX metadata/render bug)." -f $st.Count, $stMax) -ForegroundColor Red
  $suspects = $realMiss
  foreach ($s in $suspects) {
    Section "SUSPECT series=$s : why it did not render"
    LastLines $app ("\[MULTI-STUDY LOAD\] key=$s ") 2 | ForEach-Object { Write-Host ("  [app] " + $_) }
    $h7 = LastLines $app ("\[H7-P4\] series=$s ") 1
    $h7 | ForEach-Object { Write-Host ("  [app] " + $_) }
    $gate = CountRe $vd ("IDENTITY-GATE\] eval.*series=$s\b")
    Write-Host ("  identity-gate evals for this series: {0}  (0 = the render never reached the gate)" -f $gate)
    # raw window around the LAST switch to this series
    $ev = Select-String -Path $vd -Pattern ("change_series_on_viewer series=$s\b") | Select-Object -Last 1
    if ($ev) {
      $ts = $ev.Line.Substring(0, 19)
      Write-Host ("  --- raw viewer_diagnostics @ $ts ---")
      $ctx = Select-String -Path $vd -Pattern ([regex]::Escape($ts)) | ForEach-Object { $_.Line } |
             Where-Object { $_ -match 'itk_pipeline_total|path_scan|open_series|first_image_visible|LoadingStateCleared|load_request|UX_SERIES_LOAD' }
      foreach ($c in $ctx) { Write-Host ("     " + $c) }
      # [FAST-YIELD-TRACE] (app.log, correlated by second) = the exact FAST decision point.
      #   will_yield=False -> the metadata build produced NO instances (empty).
      #   will_yield=True + no first_image -> a downstream apply/decode/render failure.
      $yt = Select-String -Path $app -Pattern ([regex]::Escape($ts)) | ForEach-Object { $_.Line } | Where-Object { $_ -match 'FAST-YIELD-TRACE|DB_METADATA_GATE|FAST_LOAD_BREAKDOWN' }
      foreach ($y in $yt) { $i = $y.IndexOf('['); if ($i -lt 0) { $i = 0 }; Write-Host ("     [app] " + $y.Substring($i)) }
      # auto-detect the stale-mid-download-cache signature: itk files vs fresh disk count
      $itk = ($ctx | Where-Object { $_ -match 'itk_pipeline_total' } | Select-Object -First 1)
      $itkFiles = -1; if ($itk -and $itk -match 'files=(\d+)') { $itkFiles = [int]$Matches[1] }
      $h7disk = -1; if ($h7 -and $h7[0] -match 'disk_file_count=(\d+)') { $h7disk = [int]$Matches[1] }
      if ($itkFiles -ge 0 -and $h7disk -ge 0 -and $itkFiles -ne $h7disk) {
        Write-Host ("  >> STALE-CACHE SIGNATURE CONFIRMED: itk files={0} but fresh disk_file_count={1} (mismatch)." -f $itkFiles, $h7disk) -ForegroundColor Magenta
        Write-Host "     Root = stale mid-download FAST metadata cache not cleared by force_reload." -ForegroundColor Magenta
        Write-Host "     If this series was dragged DURING its download, the fix target is _get_cached_metadata / reconcile honoring force_reload." -ForegroundColor Magenta
      }
      elseif ($gate -eq 0) {
        Write-Host "  >> aborted BEFORE the render gate. Read the [FAST-YIELD-TRACE] above: will_yield=False = empty metadata build; will_yield=True = downstream render failure (likely DX/single-frame). modality/rows/cols identify the series type." -ForegroundColor Magenta
      }
    }
    Write-Host "  NOTE: DX / single-frame previous-exam misses are a data/state-specific metadata-or-render bug (same code renders primary DX). The FAST-YIELD-TRACE pinpoints which half." -ForegroundColor DarkYellow
  }
}

# ---------------------------------------------------------------------------
Section "OTHER OPTs (quick re-verify)"
# OPT-06 study-scoped grow bind
$snb = CountRe $vd 'GROW-LANE-STUDYNUM-BIND\] bound'
$laneUn = CountRe $vd 'GROW-LANE-TRACE\]'
Write-Host ("[OPT-06]  study-scoped grow binds={0} ; grow-lane UNMATCHED traces={1}" -f $snb, $laneUn)
if ($snb -gt 0) { Write-Host "          -> fix active (prev-exam series bound by study+number after series_uid miss)" -ForegroundColor Green }
# OPT-18 DB owner enforcement
$reassign = (CountRe $app 'CrossStudyReassignment|CrossPatientReassignment') + (CountRe $vd 'CrossStudyReassignment|CrossPatientReassignment')
Write-Host ("[OPT-18]  owner-reassignment events (0 = clean): {0}" -f $reassign)
# OPT-12 startup sweep stall
$s387 = CountRe $vd 'single_instance_lock.py\", line 387'
Write-Host ("[OPT-12]  startup single_instance_lock:387 stall traces (want 0): {0}" -f $s387)
# OPT-09 telemetry hygiene (delta only meaningful in launch mode)
if (-not $AnalyzeOnly) {
  $dlErrN = (CountRe $dl '\| ERROR ') - $dlErrB
  $dlWarnN = (CountRe $dl '\| WARNING ') - $dlWarnB
  $dlInfoN = (CountRe $dl '\| INFO ') - $dlInfoB
  Write-Host ("[OPT-09]  download_diagnostics this run: +{0} INFO, +{1} WARNING, +{2} ERROR" -f $dlInfoN, $dlWarnN, $dlErrN)
  if ($dlInfoN -gt 0) { Write-Host "          -> telemetry at INFO (OPT-09 working)" -ForegroundColor Green }
}
# KPI
$ttfi = $null; if (Test-Path $vd) { $ttfi = Select-String -Path $vd -Pattern 'TTFI .*total_ms=([0-9.]+)' | Select-Object -Last 1 }
if ($ttfi) { $i = [math]::Max(0, $ttfi.Line.IndexOf('TTFI')); Write-Host ("[KPI]     " + $ttfi.Line.Substring($i)) }

# ---------------------------------------------------------------------------
Section "VERDICT"
$fail = @()
if ($crash -gt 0) { $fail += "crashes=$crash" }
if ($duMax -gt 800) { $fail += "during-use stall max ${duMax}ms" }
if ($loadFailed + $clrAwait -gt 0) { $fail += "viewport load failures=$($loadFailed + $clrAwait)" }
if ($suspects.Count -gt 0) { $fail += "$($suspects.Count) series switched-to but never rendered ($($suspects -join ','))" }
if ($fail.Count -eq 0) {
  Write-Host "OPT-20 + re-verify: PASS (no real display miss, no blockers). Paste this output to close OPT-20." -ForegroundColor Green
}
else {
  Write-Host "REVIEW NEEDED:" -ForegroundColor Yellow
  foreach ($f in $fail) { Write-Host ("  - " + $f) -ForegroundColor Yellow }
  Write-Host "Paste the SUSPECT section(s) above and I will pinpoint / fix the cause." -ForegroundColor Yellow
}
Write-Host ""

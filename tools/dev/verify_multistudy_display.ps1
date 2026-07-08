# =============================================================================
#  AI-PACS - MULTI-STUDY DISPLAY VERIFY   (ASCII only; PowerShell 5.1 safe)
#
#  Verifies the user's OPT-20 requirement:
#    "different series for one patient AND different studies of one patient can
#     be imported and shown in the viewport -- NO missed import, and NO importing
#     with each other (no cross-study mixing)."
#
#  Confirms the 2026-07-07 study-blind append-skip fix
#  (AIPACS_SERIES_APPEND_STUDY_DISTINCT) + the 2026-07-06 index-gate fix
#  (AIPACS_APPLY_RENDER_TARGET_VIEWER): every series of every study reaches the
#  render (first_image_visible), the distinct-append log fires for colliding
#  names, and the viewport identity gate never has to SKIP a cross-exam paint.
#
#  SESSION TO RUN (then CLOSE the app):
#    * Open the multi-study / previous-exam patient (e.g. 49317).
#    * Drag / switch EVERY series of the CURRENT study, one by one.
#    * Open the Previous Exam(s) and drag EVERY series of each prior study.
#    * Re-drag a couple you already viewed (re-selection must still show them).
#    * Watch that each series actually paints (no blank / stuck viewport) and
#      that a previous-exam series never shows the current study's image.
#
#  Usage:
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\verify_multistudy_display.ps1'
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\verify_multistudy_display.ps1' -AnalyzeOnly
# =============================================================================
param([switch]$AnalyzeOnly)

$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'; if (-not (Test-Path $py)) { $py = 'python' }
$logsDir = Join-Path $repo 'user_data\logs'
$vd  = Join-Path $logsDir 'viewer_diagnostics.log'
$app = Join-Path $logsDir 'app.log'
$SCRIPT_VERSION = 'v1-multistudy-display'
Write-Host ("### verify_multistudy_display $SCRIPT_VERSION ###  (if you do not see this banner + a VERDICT, you ran a STALE copy)") -ForegroundColor Magenta

function Section($t) { Write-Host "`n==================== $t ====================" -ForegroundColor Cyan }
function Tally($path, $pat) {
  $h = @{}
  if (Test-Path $path) {
    foreach ($m in (Select-String -Path $path -Pattern $pat -AllMatches)) {
      foreach ($mm in $m.Matches) { $k = $mm.Groups[1].Value; if ($h.ContainsKey($k)) { $h[$k]++ } else { $h[$k] = 1 } }
    }
  }
  return $h
}
function CountPat($path, $pat) { if (Test-Path $path) { return (Select-String -Path $path -Pattern $pat).Count } return 0 }

if (-not $AnalyzeOnly) {
  Section "LAUNCH  (clean logs for THIS run; multi-study display trace on)"
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" |
    Where-Object { $_.CommandLine -match 'ai-pacs' -or $_.CommandLine -match 'main\.py' -or $_.Name -eq 'aipacs.exe' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  foreach ($n in 'app.log', 'viewer_diagnostics.log') { $p = Join-Path $logsDir $n; if (Test-Path $p) { Rename-Item $p ($p + ".msdisp-$stamp") -ErrorAction SilentlyContinue } }

  # THE FIXES (both default-on in code; set explicit so an env kill switch can't hide them).
  $env:AIPACS_SERIES_APPEND_STUDY_DISTINCT = '1'   # 2026-07-07 append-skip fix (slot-3 residual)
  $env:AIPACS_APPLY_RENDER_TARGET_VIEWER   = '1'   # 2026-07-06 index-gate fix
  # Diagnostics (log-only; none change rendering behaviour).
  $env:AIPACS_APPLY_TRACE               = '1'   # [APPLY-ENTER]/[APPLY-GATE]/[APPLY-LOOP]/[APPLY-STALE-VIEWER]
  $env:AIPACS_FAST_YIELD_TRACE          = '1'
  $env:AIPACS_RENDER_DROP_DETECT        = '1'
  $env:AIPACS_RENDER_DROP_MS            = '2500'
  $env:AIPACS_VIEWPORT_LIFECYCLE_LOG    = '1'
  $env:AIPACS_VIEWER_LOAD_TRACE         = '1'   # per-drop resolved-study cross-check (isolation)
  $env:AIPACS_MAIN_THREAD_PROBE         = '1'
  $env:AIPACS_MAIN_THREAD_TRACE         = '1'
  $env:AIPACS_STALL_TRACE_THRESHOLD_MS  = '200'

  Write-Host "Run the multi-study session, then CLOSE the app:" -ForegroundColor Green
  Write-Host "  1) open the multi-study / previous-exam patient (e.g. 49317)" -ForegroundColor Green
  Write-Host "  2) drag EVERY series of the CURRENT study (one by one)" -ForegroundColor Green
  Write-Host "  3) open the Previous Exam(s) and drag EVERY series of each prior study" -ForegroundColor Green
  Write-Host "  4) re-drag a couple you already viewed (must still show)" -ForegroundColor Green
  Write-Host "  5) confirm a previous-exam series never shows the CURRENT study's image" -ForegroundColor Green
  & $py main.py
}

# ---------------------------------------------------------------------------
Section "1/4  Per-series render tally (NO MISSED IMPORT)"
# A miss = a series switched-to but never painted (first_image_visible < switches).
# Offset keys (>= 1000000) are previous-exam / secondary-study series.
$switch = Tally $vd 'change_series_on_viewer series=(\d+)'
$first  = Tally $vd 'first_image_visible series=(\d+)'
$misses = @()
$offCount = 0; $offOk = 0
foreach ($k in ($switch.Keys | Sort-Object { [int]$_ })) {
  $sw = $switch[$k]; $fi = 0; if ($first.ContainsKey($k)) { $fi = $first[$k] }
  $off = ([int64]$k -ge 1000000); $tag = ''; if ($off) { $tag = '  [previous-exam/secondary]'; $offCount++ }
  $line = ("  series={0,-9} switches={1,-3} first_images={2}{3}" -f $k, $sw, $fi, $tag)
  if ($fi -lt $sw) { Write-Host ($line + '  <- MISS (never painted)') -ForegroundColor Red; $misses += $k }
  else { Write-Host $line -ForegroundColor Green; if ($off) { $offOk++ } }
}
Write-Host ("`n  offset-key (secondary-study) series that rendered OK: {0}/{1}" -f $offOk, $offCount)

# ---------------------------------------------------------------------------
Section "2/4  The append-skip fix (distinct cross-study series were PLACED)"
$appendDistinct = CountPat $app '\[SERIES-APPEND-DISTINCT\]'
Write-Host ("[SERIES-APPEND-DISTINCT] appends (distinct series that share a name+count): {0}" -f $appendDistinct)
if ($appendDistinct -gt 0 -and (Test-Path $app)) {
  foreach ($l in (Select-String -Path $app -Pattern '\[SERIES-APPEND-DISTINCT\]' | Select-Object -Last 8 | ForEach-Object { $_.Line })) {
    $i = $l.IndexOf('[SERIES-APPEND'); if ($i -lt 0) { $i = 0 }; Write-Host ("  " + $l.Substring($i)) -ForegroundColor DarkGray
  }
}
# The OLD gate-off signal: [APPLY-LOOP] with series_idx=-1 means replace_series_data
# returned -1 (the append was skipped). After the fix this should be 0.
$loopNeg = 0
if (Test-Path $app) { $loopNeg = (Select-String -Path $app -Pattern '\[APPLY-LOOP\].*series_idx=-1').Count }
Write-Host ("[APPLY-LOOP] series_idx=-1 (append-skip gate-off; MUST be 0 after fix): {0}" -f $loopNeg) -ForegroundColor $(if ($loopNeg -gt 0) { 'Red' } else { 'Green' })
# Apply-path breakdown (index-gate fix engagement).
$apEnter = CountPat $app '\[APPLY-ENTER\]'
$apStale = CountPat $app '\[APPLY-STALE-EARLY\]'
$agFix = 0; if (Test-Path $app) { $agFix = (Select-String -Path $app -Pattern '\[APPLY-GATE\]' | Where-Object { $_.Line -match 'target_fix_render=True' }).Count }
Write-Host ("[apply-path]  APPLY-ENTER={0}  APPLY-STALE-EARLY={1}  target_fix_render={2}" -f $apEnter, $apStale, $agFix)

# ---------------------------------------------------------------------------
Section "3/4  Isolation (NO IMPORTING WITH EACH OTHER / no cross-study mix)"
$idSkip = 0
if (Test-Path $vd) { $idSkip = (Select-String -Path $vd -Pattern '\[IDENTITY-GATE\].*SKIP render').Count }
if (-not (Test-Path $vd)) { }
if ((CountPat $app '\[IDENTITY-GATE\].*SKIP render') -gt 0) { $idSkip += (CountPat $app '\[IDENTITY-GATE\].*SKIP render') }
Write-Host ("[IDENTITY-GATE] SKIP (cross-exam paint blocked; 0 = no stale/wrong-study render attempt): {0}" -f $idSkip) -ForegroundColor $(if ($idSkip -gt 0) { 'Yellow' } else { 'Green' })
# Deep per-drop cross-check: study_path must equal the resolved study for every drop.
$loadTraceMismatch = 0
if (Test-Path $vd) {
  foreach ($m in (Select-String -Path $vd -Pattern '\[VIEWPORT-LOAD-TRACE\]')) {
    if ($m.Line -match 'study_path=(\S+).*resolved_study=(\S+)') {
      if ($Matches[1] -ne $Matches[2]) { $loadTraceMismatch++ }
    }
  }
}
Write-Host ("[VIEWPORT-LOAD-TRACE] study_path != resolved_study (MUST be 0): {0}" -f $loadTraceMismatch) -ForegroundColor $(if ($loadTraceMismatch -gt 0) { 'Red' } else { 'Green' })
$mlLoads = CountPat $app '\[MULTI-STUDY LOAD\]'
Write-Host ("[MULTI-STUDY LOAD] resolutions (each secondary series loaded from its OWN study path): {0}" -f $mlLoads) -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
Section "4/4  Safety (no crash / stall / failed load)"
$vlFailed = CountPat $vd 'ViewportLoadFailed'
$clearedNonNull = 0
if (Test-Path $vd) { $clearedNonNull = (Select-String -Path $vd -Pattern 'ViewportLoadingStateCleared' | Where-Object { $_.Line -notmatch 'series=None' }).Count }
$stalls = @(); if (Test-Path $vd) { $stalls = Select-String -Path $vd -Pattern 'MAIN_THREAD_STALL .*interaction_active=True' }
$stMax = 0
if ($stalls.Count) { $stMax = [math]::Round((($stalls | ForEach-Object { if ($_.Line -match 'stall_duration_ms=([0-9.]+)') { [double]$Matches[1] } }) | Measure-Object -Maximum).Maximum) }
Write-Host ("ViewportLoadFailed: {0}   ViewportLoadingStateCleared(non-None, real failure): {1}" -f $vlFailed, $clearedNonNull) -ForegroundColor $(if (($vlFailed + $clearedNonNull) -gt 0) { 'Red' } else { 'Green' })
Write-Host ("during-use main-thread stalls: {0} (max {1} ms)" -f $stalls.Count, $stMax)

# ---------------------------------------------------------------------------
Section "VERDICT"
$offMisses = @($misses | Where-Object { [int64]$_ -ge 1000000 })
$primMisses = @($misses | Where-Object { [int64]$_ -lt 1000000 })
$displayOk = ($misses.Count -eq 0 -and $loopNeg -eq 0)
$isolationOk = ($idSkip -eq 0 -and $loadTraceMismatch -eq 0)
$safetyOk = (($vlFailed + $clearedNonNull) -eq 0)

if ($displayOk -and $isolationOk -and $safetyOk) {
  Write-Host "  CLOSE OPT-20 multi-study display:" -ForegroundColor Green
  Write-Host "    - every series of every study rendered (no miss, no series_idx=-1 gate-off)" -ForegroundColor Green
  Write-Host "    - no cross-study mixing (identity gate never had to skip; study_path==resolved)" -ForegroundColor Green
  Write-Host "    - no failed loads / crashes" -ForegroundColor Green
  Write-Host "  -> Safe to collapse AIPACS_SERIES_APPEND_STUDY_DISTINCT to unconditional." -ForegroundColor Green
} else {
  Write-Host "  HOLD -- one or more checks did not pass:" -ForegroundColor Yellow
  if (-not $displayOk) {
    Write-Host ("    - DISPLAY: offset-key misses={0} primary misses={1} series_idx=-1={2}" -f $offMisses.Count, $primMisses.Count, $loopNeg) -ForegroundColor Yellow
    if ($misses.Count) { Write-Host ("      missed series: " + ($misses -join ', ')) -ForegroundColor Yellow }
    Write-Host "      For each missed series grep app.log for its [APPLY-ENTER]/[APPLY-LOOP]/[APPLY-GATE]:" -ForegroundColor DarkGray
    Write-Host "        no [APPLY-ENTER]        -> worker->UI post lost (or 1100000-style document = OPT-07)" -ForegroundColor DarkGray
    Write-Host "        [APPLY-LOOP] series_idx=-1 -> still gated off (append fix not engaged / different placement bug)" -ForegroundColor DarkGray
    Write-Host "        [APPLY-GATE] target_fix_render=True but no first_image -> render path (identity gate?)" -ForegroundColor DarkGray
  }
  if (-not $isolationOk) { Write-Host ("    - ISOLATION: identity-gate skips={0} load-trace mismatches={1} (investigate cross-study)" -f $idSkip, $loadTraceMismatch) -ForegroundColor Red }
  if (-not $safetyOk) { Write-Host ("    - SAFETY: ViewportLoadFailed + non-None cleared = {0}" -f ($vlFailed + $clearedNonNull)) -ForegroundColor Red }
}
Write-Host ""
Write-Host "Paste sections 1/4..4/4 + VERDICT. If a series still misses, paste its [APPLY-*] lines." -ForegroundColor Green
Write-Host ""

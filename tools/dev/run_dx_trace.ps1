# =============================================================================
#  AI-PACS - RUN + DX RENDER TRACE   (ASCII only; PowerShell 5.1 safe)
#
#  Purpose: launch the SOURCE build with the FAST-YIELD-TRACE + render-drop
#  instrumentation on, capture a CLEAN log for THIS run only, then pinpoint WHY
#  a DX / single-frame previous-exam series fails to render (OPT-20). It answers
#  the one open question:
#     will_yield=False  -> the FAST metadata build produced NO instances
#                          (fix = _build_metadata_headers_only / header read)
#     will_yield=True   -> metadata built + applied but never painted
#                          (fix = the apply / FAST-container render path)
#
#  SESSION TO RUN (then CLOSE the app):
#    * Open patient 48456 (the one with the slot-2 X-rays that would not show).
#    * Drag / switch to the previous-exam X-ray series that failed (2000001 /
#      2000002 and any other slot-2 previous-exam series). Try each once or twice.
#    * Also switch a couple of series that DO work, for contrast.
#
#  Usage:
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\run_dx_trace.ps1'
#    & 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version\tools\dev\run_dx_trace.ps1' -AnalyzeOnly
# =============================================================================
param([switch]$AnalyzeOnly)

$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'; if (-not (Test-Path $py)) { $py = 'python' }
$logsDir = Join-Path $repo 'user_data\logs'
$vd  = Join-Path $logsDir 'viewer_diagnostics.log'
$app = Join-Path $logsDir 'app.log'
$SCRIPT_VERSION = 'v4-apply-path-droppoint-locator'
Write-Host ("### run_dx_trace $SCRIPT_VERSION ###  (if you do not see this line + an [apply-path] section below, you ran a STALE copy)") -ForegroundColor Magenta

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
function LastLines($path, $pat, $n) { if (Test-Path $path) { return (Select-String -Path $path -Pattern $pat | Select-Object -Last $n | ForEach-Object { $_.Line }) } return @() }

if (-not $AnalyzeOnly) {
  Section "LAUNCH  (clean logs for THIS run; FAST-YIELD-TRACE on)"
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" |
    Where-Object { $_.CommandLine -match 'ai-pacs' -or $_.CommandLine -match 'main\.py' -or $_.Name -eq 'aipacs.exe' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  foreach ($n in 'app.log', 'viewer_diagnostics.log') { $p = Join-Path $logsDir $n; if (Test-Path $p) { Rename-Item $p ($p + ".dxtrace-$stamp") -ErrorAction SilentlyContinue } }

  # Diagnostics ON. FAST-YIELD-TRACE + render-drop are default-on; set explicitly so a
  # kill switch in the environment can't hide the capture. Main-thread trace confirms
  # (again) whether contention is present. Nothing here changes rendering behaviour.
  $env:AIPACS_FAST_YIELD_TRACE          = '1'
  $env:AIPACS_RENDER_DROP_DETECT        = '1'
  $env:AIPACS_RENDER_DROP_MS            = '2500'
  $env:AIPACS_RENDER_DROP_RECONVERGE    = '0'   # OFF: that was the wrong fix (deterministic, not a race)
  $env:AIPACS_APPLY_RENDER_TARGET_VIEWER = '1'  # THE REAL FIX (now default-on in code; explicit here too)
  $env:AIPACS_APPLY_TRACE               = '1'   # surface the [APPLY-ENTER]/[APPLY-GATE] markers (default-off in code)
  $env:AIPACS_MAIN_THREAD_PROBE         = '1'
  $env:AIPACS_MAIN_THREAD_TRACE         = '1'
  $env:AIPACS_STALL_TRACE_THRESHOLD_MS  = '200'
  $env:AIPACS_VIEWPORT_LIFECYCLE_LOG    = '1'
  $env:AIPACS_VIEWER_LOAD_TRACE         = '1'   # deep per-drop resolved-study cross-check

  Write-Host "Run the DX session, then CLOSE the app:" -ForegroundColor Green
  Write-Host "  1) open patient 48456" -ForegroundColor Green
  Write-Host "  2) switch/drag the slot-2 previous-exam X-ray series that would NOT show (2000001 / 2000002)" -ForegroundColor Green
  Write-Host "  3) also switch a couple of series that DO work, for contrast" -ForegroundColor Green
  & $py main.py
}

# ---------------------------------------------------------------------------
Section "1/3  Contention check (rule in/out) + per-series render tally"
$stalls = @(); if (Test-Path $vd) { $stalls = Select-String -Path $vd -Pattern 'MAIN_THREAD_STALL .*interaction_active=True' }
$stMax = 0
if ($stalls.Count) { $stMax = [math]::Round((($stalls | ForEach-Object { if ($_.Line -match 'stall_duration_ms=([0-9.]+)') { [double]$Matches[1] } }) | Measure-Object -Maximum).Maximum) }
Write-Host ("during-use main-thread stalls: {0} (max {1} ms)  [0 = contention ruled OUT]" -f $stalls.Count, $stMax)
$renderDrop = 0; $reconv = 0
if (Test-Path $vd) {
  $renderDrop = (Select-String -Path $vd -Pattern 'RENDER-DROP\] series').Count
  $reconv = (Select-String -Path $vd -Pattern 'RENDER-DROP-RECONVERGE\]').Count
}
Write-Host ("[RENDER-DROP] events: {0}" -f $renderDrop) -ForegroundColor $(if ($renderDrop -gt 0) { 'Yellow' } else { 'DarkGray' })
# --- Apply-path drop-point breakdown (the DEFINITIVE OPT-20 locator) ---
# Each miss shows exactly ONE drop point (all markers are default-on, log-only):
#   no [APPLY-ENTER] for the series -> the worker->UI apply post was LOST (never ran)
#   [APPLY-ENTER] + [APPLY-STALE-EARLY] -> the top-level stale guard dropped it (token race)
#   [APPLY-ENTER] + [APPLY-GATE] legacy_match=False -> the index-compare gate
#   [APPLY-GATE] target_fix_render=True -> the index-gate FIX rendered it
$apEnter = 0; $apStale = 0; $agFalse = 0; $agFix = 0
if (Test-Path $app) {
  $apEnter = (Select-String -Path $app -Pattern '\[APPLY-ENTER\]').Count
  $apStale = (Select-String -Path $app -Pattern '\[APPLY-STALE-EARLY\]').Count
  $ag = Select-String -Path $app -Pattern '\[APPLY-GATE\]'
  $agFalse = ($ag | Where-Object { $_.Line -match 'legacy_match=False' }).Count
  $agFix = ($ag | Where-Object { $_.Line -match 'target_fix_render=True' }).Count
}
Write-Host ("[apply-path]  APPLY-ENTER={0}  APPLY-STALE-EARLY={1}  APPLY-GATE(legacy_match=False)={2}  target_fix_render={3}" -f $apEnter, $apStale, $agFalse, $agFix)
if ($apEnter -eq 0) { Write-Host "  -> apply NEVER entered: the worker->UI post is lost (OR the app is running STALE code -- check the banner at the top matches THIS file)." -ForegroundColor Red }
elseif ($apStale -gt 0) { Write-Host "  -> STALE-EARLY guard dropped the apply (token race) - the real fix belongs THERE, not the index gate." -ForegroundColor Yellow }
elseif ($agFix -gt 0) { Write-Host "  -> the index-gate fix rendered the targeted viewer (good)." -ForegroundColor Green }
elseif ($agFalse -gt 0) { Write-Host "  -> reached the index gate, legacy_match=False, but fix NOT engaged (flag off?)." -ForegroundColor Yellow }

$switch = Tally $vd 'change_series_on_viewer series=(\d+)'
$first  = Tally $vd 'first_image_visible series=(\d+)'
$misses = @()
Write-Host ""
foreach ($k in ($switch.Keys | Sort-Object { [int]$_ })) {
  $sw = $switch[$k]; $fi = 0; if ($first.ContainsKey($k)) { $fi = $first[$k] }
  $off = ([int]$k -ge 1000000); $tag = ''; if ($off) { $tag = '  [previous-exam]' }
  $line = ("  series={0,-9} switches={1,-3} first_images={2}{3}" -f $k, $sw, $fi, $tag)
  if ($fi -lt $sw -and $off) { Write-Host ($line + '  <- MISS') -ForegroundColor Red; $misses += $k }
  elseif ($fi -lt $sw) { Write-Host ($line + '  <- partial (maybe re-selection)') -ForegroundColor DarkYellow }
  else { Write-Host $line -ForegroundColor Green }
}

# ---------------------------------------------------------------------------
Section "2/3  ALL [FAST-YIELD-TRACE] this run (the exact FAST decision point)"
$yt = @(); if (Test-Path $app) { $yt = Select-String -Path $app -Pattern '\[FAST-YIELD-TRACE\]' | ForEach-Object { $_.Line } }
if ($yt.Count -eq 0) {
  Write-Host "NONE found. If misses exist, FAST-YIELD-TRACE may be off (AIPACS_FAST_YIELD_TRACE) or the build is stale." -ForegroundColor Yellow
} else {
  $noYield = $yt | Where-Object { $_ -match 'will_yield=False' }
  Write-Host ("total={0}  will_yield=False (empty metadata build)={1}" -f $yt.Count, @($noYield).Count)
  Write-Host "-- will_yield=False (these are the empty-metadata misses) --" -ForegroundColor Magenta
  foreach ($l in ($noYield | Select-Object -Last 12)) { $i = $l.IndexOf('[FAST-YIELD'); if ($i -lt 0) { $i = 0 }; Write-Host ("  " + $l.Substring($i)) -ForegroundColor Magenta }
  Write-Host "-- last 8 traces overall (context) --" -ForegroundColor DarkGray
  foreach ($l in ($yt | Select-Object -Last 8)) { $i = $l.IndexOf('[FAST-YIELD'); if ($i -lt 0) { $i = 0 }; Write-Host ("  " + $l.Substring($i)) -ForegroundColor DarkGray }
}

# ---------------------------------------------------------------------------
Section "3/3  Per-miss verdict (display key -> disk series -> FAST-YIELD-TRACE)"
if ($misses.Count -eq 0) {
  Write-Host "No previous-exam misses this run. If the X-rays rendered, the issue did not reproduce." -ForegroundColor Green
}
foreach ($s in $misses) {
  Write-Host ("`n  MISS series=$s") -ForegroundColor Red
  # display key -> disk series via MULTI-STUDY LOAD
  $ml = LastLines $app ("\[MULTI-STUDY LOAD\] key=$s -> ") 1
  $disk = ''
  if ($ml) { Write-Host ("    " + ($ml[0] -replace '.*(\[MULTI-STUDY LOAD\].*)', '$1')); if ($ml[0] -match 'disk_series=(\S+)') { $disk = $Matches[1] } }
  # the miss switch timestamp (minute granularity for correlation)
  $ev = Select-String -Path $vd -Pattern ("change_series_on_viewer series=$s\b") | Select-Object -Last 1
  $tmin = ''; if ($ev) { $tmin = $ev.Line.Substring(0, 16) }
  # FAST-YIELD-TRACE for that disk series near the miss minute
  $line = $null
  if ($disk -ne '' -and $tmin -ne '' -and (Test-Path $app)) {
    $line = Select-String -Path $app -Pattern ("\[FAST-YIELD-TRACE\] series=$disk ") | Where-Object { $_.Line -like "$tmin*" } | Select-Object -Last 1
  }
  if ($line) {
    $i = $line.Line.IndexOf('[FAST-YIELD'); if ($i -lt 0) { $i = 0 }
    Write-Host ("    " + $line.Line.Substring($i)) -ForegroundColor White
    if ($line.Line -match 'will_yield=False') {
      Write-Host "    >> VERDICT: metadata build produced NO instances -> fix = _build_metadata_headers_only / header read for this file." -ForegroundColor Magenta
    } elseif ($line.Line -match 'will_yield=True') {
      Write-Host "    >> VERDICT: metadata built + yielded, but never painted -> fix = the apply / FAST-container render path." -ForegroundColor Magenta
    }
    if ($line.Line -match 'modality=(\S+)') { Write-Host ("    modality=" + $Matches[1]) -ForegroundColor DarkGray }
  } else {
    Write-Host "    (no FAST-YIELD-TRACE matched for disk series $disk at $tmin -- paste this MISS block and I will widen the correlation)" -ForegroundColor DarkYellow
  }
}

Section "DONE"
Write-Host "Paste sections 2/3 and 3/3. The will_yield value on each MISS tells me exactly which half to fix." -ForegroundColor Green
Write-Host ""

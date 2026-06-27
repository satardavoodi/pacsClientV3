<#
  check_validation.ps1 — post-run validation check for the AI-PACS viewer-unification work.

  Run this AFTER a workflow that exercises the stages — ideally launched with
  run_with_validation.cmd (so the shadow / identity / authority flags are ON), then:
    - open a MULTI-STUDY patient (or use Previous Exams) and drop a SECONDARY-study series,
    - switch between patients and change the layout a couple of times.

  Usage (from the project root, in a SECOND terminal so the app keeps running):
    .\check_validation.ps1                  # scans the last 30 minutes
    .\check_validation.ps1 -SinceMinutes 10
#>
param([int]$SinceMinutes = 30)

$ErrorActionPreference = 'SilentlyContinue'
$root = if ($PSScriptRoot) { $PSScriptRoot } else { "E:\ai-pacs\ai-pacs codes\ai-pacs beta version" }
$logs = Join-Path $root "user_data\logs"
$cut  = (Get-Date).AddMinutes(-$SinceMinutes)

function Read-Recent([string]$file, [int]$tail = 8000) {
    $p = Join-Path $logs $file
    if (-not (Test-Path $p)) { return @() }
    Get-Content $p -Tail $tail | Where-Object {
        if ($_ -match '(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)') {
            try { return ([datetime]::ParseExact($matches[1], 'yyyy-MM-dd HH:mm:ss', $null) -ge $cut) }
            catch { return $true }
        }
        return $true
    }
}

function Show([string]$label, [string]$status, [string]$detail) {
    $tag = @{ PASS = '[PASS]'; WARN = '[WARN]'; FAIL = '[FAIL]'; INFO = '[INFO]' }[$status]
    $col = @{ PASS = 'Green'; WARN = 'Yellow'; FAIL = 'Red'; INFO = 'Cyan' }[$status]
    Write-Host ("{0,-7} {1,-32} {2}" -f $tag, $label, $detail) -ForegroundColor $col
}

function Count($lines, [string]$pattern) {
    if (-not $lines) { return 0 }
    return ($lines | Select-String $pattern).Count
}

$viewer = Read-Recent "viewer_diagnostics.log"
$app    = Read-Recent "app.log"
$dl     = Read-Recent "download_diagnostics.log"
$all    = @($viewer) + @($app)

Write-Host ""
Write-Host "=== AI-PACS unification validation  (last $SinceMinutes min) ===" -ForegroundColor White
Write-Host ""

# --- STAGE markers --------------------------------------------------------
$gs = Count $all "\[GROW-SIBLING\]"
if ($gs -gt 0) { Show "Grow-sibling (multi-study fix)" 'PASS' "$gs live grow events on secondary studies" }
else           { Show "Grow-sibling (multi-study fix)" 'INFO' "0 - drop a SECONDARY-study series to exercise it" }

$idS = Count $all "VIEWER-IDENTITY-SHADOW"
$idR = Count $all "VIEWER-STABLE-IDENTITY"
if (($idS + $idR) -gt 0) { Show "S1 stable identity" 'PASS' "$idS shadow / $idR stale-request rejections" }
else                     { Show "S1 stable identity" 'INFO' "0 - flags off? use run_with_validation.cmd + switch patients/layouts" }

$auth = Count $all "STATE-AUTHORITY-SHADOW"
if ($auth -eq 0) { Show "S2 state authority" 'PASS' "0 divergences (authority agrees with the live check)" }
else             { Show "S2 state authority" 'WARN' "$auth divergence(s) - review the log lines" }

# S3b ensure_series_displayed chokepoint (shadow): 0 divergences = the unified chokepoint agrees
# with the live settled decision on this run (safe to advance the cutover); >0 = review before flip.
$ens = Count $all "ENSURE-DISPLAYED-SHADOW"
if ($ens -eq 0) { Show "S3 chokepoint shadow" 'PASS' "0 divergences (chokepoint agrees with the live path)" }
else            { Show "S3 chokepoint shadow" 'WARN' "$ens divergence(s) - review before any S3 cutover" }

# Non-terminal grow STARVATION guard (45743 / 2000008): a series the user keeps scrolling
# must still grow. Many hot-defers WITH forced grows = the guard is working; many hot-defers
# with ZERO forced grows = starvation (flag off or regressed).
$forceProg = Count $all "\[PROGRESSIVE_GROW_FORCE_PROGRESS\]"
$hotDefer  = Count $all "PROGRESSIVE_GROW_DEFERRED_INTERACTION.*nonterminal_hot"
if ($hotDefer -ge 8 -and $forceProg -eq 0) {
    Show "Grow anti-starvation (hot-force)" 'FAIL' "$hotDefer hot-defers, 0 forced - series may STARVE (flag off / regressed)"
} elseif ($forceProg -gt 0) {
    Show "Grow anti-starvation (hot-force)" 'PASS' "$forceProg forced grow(s) broke through $hotDefer hot-defer(s)"
} else {
    Show "Grow anti-starvation (hot-force)" 'INFO' "0 - scroll a slow SECONDARY series continuously to exercise it"
}

# Slow-link progressive grow (Mehr "viewport doesn't grow until complete", 2026-06-27):
# on a slow link images trickle in 1-at-a-time, so the fixed-batch grow gate (delta >= 10)
# never trips for a small series. The time-based escape grows with whatever has arrived.
# On a FAST link (Razi) the batch path fires first → 0 is EXPECTED; on Mehr >0 = fix engaged.
$slowGrow = Count $all "progressive: slow-link grow"
if ($slowGrow -gt 0) { Show "Slow-link grow (Mehr fix)" 'PASS' "$slowGrow live grows from trickled images (viewport grew mid-download)" }
else                 { Show "Slow-link grow (Mehr fix)" 'INFO' "0 - expected on a FAST link; on Mehr, view a downloading series to exercise it" }

Write-Host ""

# --- HEALTH ---------------------------------------------------------------
$attempts = ($all | Select-String "attempt=(\d+)" -AllMatches | ForEach-Object { $_.Matches } |
             ForEach-Object { [int]$_.Groups[1].Value } | Measure-Object -Maximum).Maximum
if (-not $attempts) { $attempts = 0 }
$forceReload = Count $viewer "grow-fallback metadata-sync \+ force-reload"
if (($attempts -ge 20) -or ($forceReload -ge 30)) {
    Show "Resume-watchdog livelock" 'FAIL' "max attempt=$attempts, force-reload=$forceReload - LIVELOCK suspected"
} else {
    Show "Resume-watchdog livelock" 'PASS' "healthy (max attempt=$attempts, force-reload=$forceReload)"
}

$complete = Count $viewer "COMPLETE \(\d+ slices\)"
Show "Series fully loaded" 'INFO' "$complete series reached COMPLETE"

$ttfi = $viewer | Select-String "\[KPI\] kind=TTFI scope=viewer.*?total_ms=([\d\.]+)" -AllMatches |
        ForEach-Object { $_.Matches } | ForEach-Object { [double]$_.Groups[1].Value }
if ($ttfi) {
    $avg = [int]($ttfi | Measure-Object -Average).Average
    $mx  = [int]($ttfi | Measure-Object -Maximum).Maximum
    $st  = if ($mx -le 300) { 'PASS' } else { 'WARN' }
    Show "KPI first-image (TTFI)" $st "avg=${avg}ms  max=${mx}ms  (n=$($ttfi.Count))"
} else {
    Show "KPI first-image (TTFI)" 'INFO' "no samples (no series viewed yet)"
}

$stalls = $viewer | Select-String "stall_duration_ms=([\d\.]+)" -AllMatches |
          ForEach-Object { $_.Matches } | ForEach-Object { [double]$_.Groups[1].Value }
if ($stalls) {
    $over1 = ($stalls | Where-Object { $_ -gt 1000 }).Count
    $mx    = [int]($stalls | Measure-Object -Maximum).Maximum
    $st    = if ($over1 -eq 0) { 'PASS' } else { 'WARN' }
    Show "Main-thread stalls" $st "max=${mx}ms  over-1s=$over1  (n=$($stalls.Count))"
} else {
    Show "Main-thread stalls" 'PASS' "none recorded"
}

# --- reception breaker (only shown if relevant) ---------------------------
$restErr = Count $dl "reporter-hydration.*rest_error"
$brkOpen = Count $dl "reception-breaker\] OPEN"
if (($restErr + $brkOpen) -gt 0) {
    $st = if ($brkOpen -gt 0) { 'PASS' } else { 'INFO' }
    Show "Reception breaker (report API)" $st "rest_errors=$restErr  breaker-open=$brkOpen"
}

Write-Host ""
Write-Host "Tip: if S1/S2 show [INFO] 0, the app was launched without the flags - use run_with_validation.cmd." -ForegroundColor DarkGray
Write-Host ""

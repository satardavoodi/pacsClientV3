<#
  check_s4b.ps1 - S4b VTK-cache shadow / cache evidence check.

  Run in a SECOND PowerShell terminal AFTER you have exercised MPR + the Advanced
  viewer (see run_s4b_shadow.cmd / run_s4b_cache.cmd). It scans the logs for the
  [VTK-VOLUME-SHADOW] evidence and reports the cross-builder geometry GATE.

  Usage (from the project root):
    .\check_s4b.ps1                 # scans the last 60 minutes
    .\check_s4b.ps1 -SinceMinutes 15
#>
param([int]$SinceMinutes = 60)

$ErrorActionPreference = 'SilentlyContinue'
$root = if ($PSScriptRoot) { $PSScriptRoot } else { "E:\ai-pacs\ai-pacs codes\ai-pacs beta version" }
$logs = Join-Path $root "user_data\logs"
$cut  = (Get-Date).AddMinutes(-$SinceMinutes)

function Read-Recent([string]$file, [int]$tail = 15000) {
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

$all = @(Read-Recent "viewer_diagnostics.log") + @(Read-Recent "app.log")

Write-Host ""
Write-Host "=== AI-PACS S4b VTK-cache validation  (last $SinceMinutes min) ===" -ForegroundColor White
Write-Host ""

$shadow  = Count $all "\[VTK-VOLUME-SHADOW\]"
$diverge = Count $all "GEOMETRY DIVERGES"
$rebuild = Count $all "\[VTK-VOLUME-SHADOW\].*REBUILD"
$mpr     = Count $all "mpr_full_rebuild"
$adv     = Count $all "advanced_itk2vtk"

# Did the shadow run at all?
if ($shadow -eq 0) {
    Show "VTK-VOLUME-SHADOW seen" 'INFO' "0 - launch with run_s4b_shadow.cmd, then open MPR + Advanced on a series"
} else {
    Show "VTK-VOLUME-SHADOW seen" 'PASS' "$shadow shadow event(s)"
}

# THE GATE: MPR and Advanced must build the SAME geometry for a series before reuse is allowed.
if ($diverge -gt 0) {
    Show "Cross-builder geometry GATE" 'FAIL' "$diverge GEOMETRY DIVERGES - do NOT enable cache reuse (MPR vs Advanced differ)"
} elseif ($shadow -gt 0) {
    Show "Cross-builder geometry GATE" 'PASS' "0 divergences - MPR and Advanced agree (cross-builder reuse is safe)"
} else {
    Show "Cross-builder geometry GATE" 'INFO' "no shadow data yet"
}

# Were BOTH builders observed for the same series? (needed for the comparison to mean anything)
if ($mpr -gt 0 -and $adv -gt 0) {
    Show "Both builders observed" 'PASS' "MPR + Advanced both built (mpr=$mpr adv=$adv) - comparison valid"
} elseif ($shadow -gt 0) {
    Show "Both builders observed" 'WARN' "only one seen (mpr=$mpr adv=$adv) - open the SAME series in BOTH MPR and Advanced"
} else {
    Show "Both builders observed" 'INFO' "mpr=$mpr adv=$adv"
}

# Evidence of the savings (each = a rebuild / re-read the shared cache removes).
Show "Avoidable rebuilds measured" 'INFO' "$rebuild (each is a full VTK rebuild the cache would skip)"

# Health: the wiring must not introduce errors.
$app = Read-Recent "app.log"
$tb  = Count $app "Traceback \(most recent call last\)"
$err = Count $app "vtk_volume_service.*(error|Exception)"
if ($tb -gt 0 -or $err -gt 0) {
    Show "Errors / tracebacks" 'WARN' "tracebacks=$tb  vtk_volume_service errors=$err - inspect app.log"
} else {
    Show "Errors / tracebacks" 'PASS' "none in the new code path"
}

Write-Host ""
if ($diverge -gt 0) {
    Write-Host "Result: cross-builder geometry DIVERGES - keep cache reuse OFF; the Advanced and MPR" -ForegroundColor Yellow
    Write-Host "        builders need to converge first. Stay on shadow mode." -ForegroundColor Yellow
} elseif ($shadow -gt 0 -and $mpr -gt 0 -and $adv -gt 0) {
    Write-Host "Result: GATE PASSED - the cache ACT mode (run_s4b_cache.cmd) is safe to try." -ForegroundColor Green
    Write-Host "        Then re-run this to confirm rebuilds drop on the 2nd open of a series." -ForegroundColor Green
} else {
    Write-Host "Result: not enough evidence yet - open the SAME CT/MR series in BOTH MPR and the" -ForegroundColor DarkGray
    Write-Host "        Advanced viewer (and reopen MPR once), then re-run .\check_s4b.ps1" -ForegroundColor DarkGray
}
Write-Host ""

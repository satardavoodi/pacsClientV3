param(
    [string]$LogDirectory = 'user_data/logs',
    [string]$Start = '2026-09-14 21:04:04',
    [string]$End = '2026-09-14 21:17:55',
    [int]$AppProcessId = 925068
)
# Read-only, PHI-safe aggregate output. Read live logs with writer/delete sharing.
# F8 gaps describe threshold-selected stalls, not all event-loop or request latencies.
$ErrorActionPreference = 'Stop'
$auditEvents = @{}
$auditTraces = @{}
$auditMarkers = @{}
$auditFiles = Get-ChildItem -LiteralPath $LogDirectory -File | Where-Object {
    $_.Name -match '^(app|viewer_diagnostics|download_diagnostics)\.log(\.\d+)?$'
}
foreach ($auditFile in $auditFiles) {
    $auditStream = [System.IO.File]::Open(
        $auditFile.FullName, 'Open', 'Read',
        ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
    $auditReader = [System.IO.StreamReader]::new($auditStream)
    try {
        while ($null -ne ($auditLine = $auditReader.ReadLine())) {
            if ($auditLine.Length -lt 19) { continue }
            $auditStamp = $auditLine.Substring(0, 19)
            if ($auditStamp -lt $Start -or $auditStamp -gt $End -or
                $auditLine -notmatch "pid=$AppProcessId\b") { continue }
            if ($auditLine -match '\[MAIN_THREAD_STALL\].*?gap_ms=([\d.]+)') {
                $auditEvents[$auditLine] = [double]$Matches[1]
            }
            if ($auditLine -match '\[MAIN_THREAD_STALL_TRACE\].*?gap_ms=([\d.]+)') {
                $auditTraces[$auditLine] = [pscustomobject]@{
                    time = $auditStamp
                    gap_ms = [double]$Matches[1]
                    functions = (([regex]::Matches(
                        $auditLine, 'line \d+, in ([A-Za-z0-9_]+)') |
                        ForEach-Object { $_.Groups[1].Value }) -join ' > ')
                }
            }
            foreach ($auditMarker in @('SLOT_TIMING', 'first_series_visible',
                'MAIN_THREAD_STALL_PROBE armed', 'MAIN_THREAD_STALL_TRACE armed')) {
                if ($auditLine.Contains($auditMarker)) {
                    if (-not $auditMarkers.ContainsKey($auditMarker)) {
                        $auditMarkers[$auditMarker] = 0
                    }
                    $auditMarkers[$auditMarker]++
                }
            }
        }
    } finally { $auditReader.Dispose() }
}
$auditValues = @($auditEvents.Values | Sort-Object)
$auditMedian = $null
$auditP95 = $null
$auditMaximum = $null
if ($auditValues.Count) {
    $auditMiddle = [int][math]::Floor($auditValues.Count / 2)
    $auditMedian = $auditValues[$auditMiddle]
    if (($auditValues.Count % 2) -eq 0) {
        $auditMedian = ($auditValues[$auditMiddle - 1] + $auditValues[$auditMiddle]) / 2
    }
    $auditP95 = $auditValues[[math]::Ceiling(.95 * $auditValues.Count) - 1]
    $auditMaximum = $auditValues[-1]
}
[pscustomobject]@{
    start = $Start; end = $End; pid = $AppProcessId; files_read = $auditFiles.Count
    unique_stall_count = $auditValues.Count; median_stall_ms = $auditMedian
    p95_stall_nearest_rank_ms = $auditP95; max_stall_ms = $auditMaximum
    stalls_over_1000ms = @($auditValues | Where-Object { $_ -gt 1000 }).Count
    unique_traces = $auditTraces.Count; markers = $auditMarkers
    traces = @($auditTraces.Values | Sort-Object time)
} | ConvertTo-Json -Depth 5

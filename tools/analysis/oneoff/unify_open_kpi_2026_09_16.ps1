param(
    [string]$LogDirectory = 'user_data/logs',
    [string]$Start = '2026-09-16 20:51:54',
    [string]$End = '2026-09-16 20:58:29',
    [int]$AppProcessId = 1207756
)
# Read-only local analysis. Never emit raw identities, paths, messages or images.
# Extract identity AFTER the trace marker, not the generic logger's study=- field.
$ErrorActionPreference = 'Stop'
$traceRows = @{}
$errorRows = @{}
$allProcessErrorRows = @{}
$fileChecks = @{}
$phaseCounts = @{}
$files = @(Get-ChildItem -LiteralPath $LogDirectory -File | Where-Object {
    $_.Name -match '^(app|viewer_diagnostics|download_diagnostics)\.log(\.\d+)?$'
})
foreach ($file in $files) {
    $stream = [IO.File]::Open($file.FullName, 'Open', 'Read',
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    $reader = [IO.StreamReader]::new($stream)
    try {
        while ($null -ne ($line = $reader.ReadLine())) {
            if ($line.Length -lt 23 -or $line.Substring(0,19) -lt $Start -or
                $line.Substring(0,19) -gt $End) { continue }
            if ($line -match '\|\s*(ERROR|CRITICAL)\s*\|') { $allProcessErrorRows[$line] = $true }
            if ($line -match '\[SERIES_FILE_COUNT_CHECK\] expected=(\d+) present=(\d+) passed=(True|False) cancelled=(True|False) check_ms=([\d.]+)') {
                $fileChecks[$line.Substring(0,23)+' '+$Matches[0]] = @{
                    expected=[int]$Matches[1]; present=[int]$Matches[2]
                    passed=($Matches[3] -eq 'True'); cancelled=($Matches[4] -eq 'True')
                    check_ms=[double]$Matches[5]
                }
            }
            if ($line -notmatch "pid=$AppProcessId\b") { continue }
            if ($line -match '\|\s*(ERROR|CRITICAL)\s*\|') { $errorRows[$line] = $true }
            $marker = '[FAST-OPEN-TRACE] '
            $offset = $line.IndexOf($marker)
            if ($offset -lt 0) { continue }
            $body = $line.Substring($offset + $marker.Length)
            $traceRows[$line.Substring(0,23)+' '+$body] = @{
                stamp = $line.Substring(0,23); body = $body
            }
        }
    } finally { $reader.Dispose() }
}
$identities = @{}
$events = @()
$applyValues = @()
foreach ($row in ($traceRows.Values | Sort-Object stamp)) {
    $body = $row.body
    $identity = [regex]::Match($body, '^study=(\S+)').Groups[1].Value
    if (-not $identities.ContainsKey($identity)) { $identities[$identity] = 'case-{0:D2}' -f ($identities.Count+1) }
    $phase = [regex]::Match($body, '\bphase=(\S+)').Groups[1].Value
    if (-not $phaseCounts.ContainsKey($phase)) { $phaseCounts[$phase] = 0 }
    $phaseCounts[$phase]++
    if ($phase -eq 'local_thumb_stream_card') {
        $applyValues += [double]([regex]::Match($body, '\bapply_ms=([\d.]+)').Groups[1].Value)
        continue
    }
    if ($phase -notmatch 'open_request|first_series_visible|thumb|series_info|backfill|patient_study_set') { continue }
    $fields = [ordered]@{time=$row.stamp; case=$identities[$identity]; phase=$phase}
    foreach ($match in [regex]::Matches($body,
        '\b(t_ms|all_studies|thumbnail_count|series_count|studies|series|new_studies|queue_ms|prepare_wait_ms|scan_ms|delivery_ms|elapsed_ms|delivered|total_ms|duration_ms)=([\d.]+)')) {
        $fields[$match.Groups[1].Value] = [double]$match.Groups[2].Value
    }
    foreach ($name in @('source','outcome')) {
        $value = [regex]::Match($body, "\b$name=(db|server|local|import|done|failed|cancelled)\b")
        if ($value.Success) { $fields[$name] = $value.Groups[1].Value }
    }
    $events += [pscustomobject]$fields
}
$orderedApply = @($applyValues | Sort-Object)
$applySummary = $null
if ($orderedApply.Count) {
    $middle = [int][math]::Floor($orderedApply.Count/2)
    $median = $orderedApply[$middle]
    if (($orderedApply.Count % 2) -eq 0) {
        $median = ($orderedApply[$middle-1]+$orderedApply[$middle])/2
    }
    $applySummary = @{
        count=$orderedApply.Count; sum_ms=($applyValues | Measure-Object -Sum).Sum
        median_ms=$median
        p95_nearest_rank_ms=$orderedApply[[math]::Ceiling(.95*$orderedApply.Count)-1]
        max_ms=$orderedApply[-1]
    }
}
[pscustomobject]@{
    start=$Start; end=$End; pid=$AppProcessId; files_read=$files.Count
    error_or_critical_lines=$errorRows.Count; phase_counts=$phaseCounts
    window_error_or_critical_all_pids=$allProcessErrorRows.Count
    download_file_count_checks=@{
        count=$fileChecks.Count
        passed=@($fileChecks.Values | Where-Object {$_.passed}).Count
        exact_count_match=@($fileChecks.Values | Where-Object {$_.expected -eq $_.present}).Count
        cancelled=@($fileChecks.Values | Where-Object {$_.cancelled}).Count
        max_check_ms=($fileChecks.Values.check_ms | Measure-Object -Maximum).Maximum
    }
    local_card_apply=$applySummary; events=$events
} | ConvertTo-Json -Depth 6

# Quick Test Runner for Mode B Performance Investigation
# Combines app launch with performance monitoring

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("baseline", "download_only", "mode_b", "actions")]
    [string]$Scenario,
    
    [Parameter(Mandatory=$false)]
    [string]$Duration = "00:05:00"  # 5 minutes default
)

$ErrorActionPreference = "Stop"

# Paths
$toolsDir = Split-Path -Parent $PSScriptRoot
$rootDir = Split-Path -Parent $toolsDir
$perfLogDir = Join-Path $rootDir "perf_logs"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# Ensure directories exist
if (-not (Test-Path $perfLogDir)) {
    New-Item -ItemType Directory -Path $perfLogDir -Force | Out-Null
}

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Mode B Performance Test Runner" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Scenario: $Scenario" -ForegroundColor Green
Write-Host "Duration: $Duration" -ForegroundColor Green
Write-Host "Timestamp: $timestamp" -ForegroundColor Green
Write-Host ""

# Scenario descriptions
$scenarioDescriptions = @{
    "baseline" = @"
SCENARIO A: Viewer Only (Baseline)
----------------------------------
1. Launch application
2. Open a downloaded study (Study A)
3. Scroll through series for 60+ seconds
4. Drag-drop 5 series into viewers
5. Apply window/level changes
6. Close study

Expected: Smooth operation, no lag
"@
    "download_only" = @"
SCENARIO B: Download Only (Isolation)
--------------------------------------
1. Launch application
2. Queue 2 large studies for download
3. Start downloads
4. DO NOT open any viewer tabs
5. Wait for completion

Expected: Main UI responsive, no CPU spikes
"@
    "mode_b" = @"
SCENARIO C: Viewer + Download (Mode B)
---------------------------------------
1. Open Study A (already downloaded) in viewer
2. Load initial series, verify smooth scrolling
3. START download of Study B
4. IMMEDIATELY begin continuous scrolling in Study A
5. Continue scrolling for 120 seconds
6. Note when download completes
7. Continue scrolling 30s post-download

Expected: Choppy during download, smooth after
"@
    "actions" = @"
SCENARIO D: Viewer Actions During Download
-------------------------------------------
Perform each action during download:
- Wheel scroll (50 events)
- Slider drag (continuous)
- Series drag-drop (3 series)
- Window/Level adjust (10 times)
- Viewer switch (5 times)
- Zoom/Pan (10 operations)

Expected: All actions laggy during download
"@
}

Write-Host $scenarioDescriptions[$Scenario] -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to start test (or Ctrl+C to cancel)..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
Write-Host ""

# Start performance monitoring in background
Write-Host "[1/3] Starting performance monitoring..." -ForegroundColor Cyan

$perfScriptPath = Join-Path $PSScriptRoot "start_performance_monitoring.ps1"

# Start perfmon collector
$perfJob = Start-Job -ScriptBlock {
    param($scriptPath, $scenario, $duration, $outputDir)
    & $scriptPath -TestName $scenario -Duration $duration -OutputDir $outputDir
} -ArgumentList $perfScriptPath, $Scenario, $Duration, $perfLogDir

Start-Sleep -Seconds 3
Write-Host "[✓] Performance monitoring started (Job ID: $($perfJob.Id))" -ForegroundColor Green
Write-Host ""

# Set environment for detailed logging
Write-Host "[2/3] Configuring application logging..." -ForegroundColor Cyan
$env:AIPACS_LOG_LEVEL = "DEBUG"
$env:AIPACS_PERF_LOG = "1"

$appLogFile = Join-Path $perfLogDir "app_$($Scenario)_$timestamp.log"
Write-Host "[✓] App log: $appLogFile" -ForegroundColor Green
Write-Host ""

# Launch application
Write-Host "[3/3] Launching application..." -ForegroundColor Cyan
Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  APPLICATION STARTING" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $rootDir

try {
    # Start app with log redirection
    Write-Host "[*] App is starting... Follow scenario steps above." -ForegroundColor Yellow
    Write-Host "[*] Performance data is being collected in background" -ForegroundColor Yellow
    Write-Host ""
    
    # Launch app and capture output
    $appProcess = Start-Process -FilePath "python" `
                                 -ArgumentList "main.py" `
                                 -RedirectStandardOutput $appLogFile `
                                 -RedirectStandardError "$appLogFile.err" `
                                 -PassThru `
                                 -NoNewWindow
    
    Write-Host "[✓] Application launched (PID: $($appProcess.Id))" -ForegroundColor Green
    Write-Host ""
    Write-Host "--------------------------------------" -ForegroundColor Yellow
    Write-Host "  PERFORM TEST SCENARIO NOW" -ForegroundColor White
    Write-Host "--------------------------------------" -ForegroundColor Yellow
    Write-Host ""
    
    # Monitor app and perfmon
    Write-Host "[*] Monitoring... (press Ctrl+C when test complete)" -ForegroundColor Gray
    Write-Host ""
    
    # Tail application log in real-time
    Write-Host "=== APPLICATION LOG (PERF events only) ===" -ForegroundColor Cyan
    
    # Wait for app to exit or user interrupt
    $checkInterval = 5
    $elapsed = 0
    
    while (-not $appProcess.HasExited) {
        Start-Sleep -Seconds $checkInterval
        $elapsed += $checkInterval
        
        # Show PERF log entries
        if (Test-Path $appLogFile) {
            $perfLines = Get-Content $appLogFile -Tail 10 | Where-Object { $_ -match '\[PERF\]' }
            if ($perfLines) {
                foreach ($line in $perfLines) {
                    Write-Host $line -ForegroundColor DarkGray
                }
            }
        }
        
        # Show progress
        if ($elapsed % 30 -eq 0) {
            Write-Host "[*] Test running... ($elapsed seconds elapsed)" -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    Write-Host "[✓] Application exited" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "[!] ERROR: $_" -ForegroundColor Red
    
    # Try to kill app if running
    if ($appProcess -and -not $appProcess.HasExited) {
        Write-Host "[*] Terminating application..." -ForegroundColor Yellow
        $appProcess.Kill()
    }
}
finally {
    Pop-Location
    
    # Stop performance monitoring
    Write-Host ""
    Write-Host "[*] Stopping performance monitoring..." -ForegroundColor Cyan
    
    Stop-Job -Job $perfJob -ErrorAction SilentlyContinue
    Remove-Job -Job $perfJob -Force -ErrorAction SilentlyContinue
    
    # Manually stop logman collector
    $collectorName = "mode_b_perf_*"
    logman stop $collectorName 2>$null | Out-Null
    logman delete $collectorName 2>$null | Out-Null
    
    Write-Host "[✓] Performance monitoring stopped" -ForegroundColor Green
    Write-Host ""
    
    # Summary
    Write-Host "======================================" -ForegroundColor Cyan
    Write-Host "  TEST COMPLETE" -ForegroundColor Green
    Write-Host "======================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Collected data:" -ForegroundColor Yellow
    Write-Host "  Application log:  $appLogFile" -ForegroundColor White
    Write-Host "  Performance data: Check $perfLogDir for .blg files" -ForegroundColor White
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Analyze application log:" -ForegroundColor White
    Write-Host "     python tools\performance\performance_log_analyzer.py `"$appLogFile`"" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  2. View performance data:" -ForegroundColor White
    Write-Host "     perfmon.exe  (then open .blg file)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  3. Extract PERF events only:" -ForegroundColor White
    Write-Host "     Select-String -Path `"$appLogFile`" -Pattern '\[PERF\]' | Out-File perf_only.log" -ForegroundColor Cyan
    Write-Host ""
}

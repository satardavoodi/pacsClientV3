# Performance Monitor Setup and Data Collection Script
# For Mode B Testing - Windows Performance Counters

param(
    [Parameter(Mandatory=$false)]
    [string]$TestName = "mode_b_test",
    
    [Parameter(Mandatory=$false)]
    [string]$Duration = "00:10:00",  # 10 minutes default
    
    [Parameter(Mandatory=$false)]
    [string]$OutputDir = "E:\ai-pacs\perf_logs"
)

$ErrorActionPreference = "Stop"

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Mode B Performance Monitor Setup" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Ensure output directory exists
if (-not (Test-Path $OutputDir)) {
    Write-Host "[*] Creating output directory: $OutputDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

# Generate timestamp for this test run
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$collectorName = "mode_b_perf_$timestamp"
$outputFile = Join-Path $OutputDir "$TestName`_$timestamp.blg"

Write-Host "[*] Test name: $TestName" -ForegroundColor Green
Write-Host "[*] Output file: $outputFile" -ForegroundColor Green
Write-Host "[*] Duration: $Duration" -ForegroundColor Green
Write-Host ""

# Define counters to collect
$counters = @(
    # Process-level CPU
    "\Process(AIPacs)\% Processor Time",
    "\Process(AIPacs)\% User Time",
    "\Process(AIPacs)\% Privileged Time",
    "\Process(python*)\% Processor Time",
    "\Process(python*)\% User Time",
    
    # Process-level Memory
    "\Process(AIPacs)\Working Set",
    "\Process(AIPacs)\Private Bytes",
    "\Process(AIPacs)\Virtual Bytes",
    "\Process(AIPacs)\Page Faults/sec",
    "\Process(python*)\Working Set",
    "\Process(python*)\Private Bytes",
    
    # Process-level I/O
    "\Process(AIPacs)\IO Data Bytes/sec",
    "\Process(AIPacs)\IO Data Operations/sec",
    "\Process(AIPacs)\IO Read Bytes/sec",
    "\Process(AIPacs)\IO Write Bytes/sec",
    "\Process(python*)\IO Data Bytes/sec",
    "\Process(python*)\IO Read Bytes/sec",
    "\Process(python*)\IO Write Bytes/sec",
    
    # Process-level threads
    "\Process(AIPacs)\Thread Count",
    "\Process(python*)\Thread Count",
    
    # System-level CPU
    "\Processor(_Total)\% Processor Time",
    "\Processor(_Total)\% User Time",
    "\Processor(_Total)\% Privileged Time",
    "\Processor(*)\% Processor Time",  # Per-core
    
    # System-level Memory
    "\Memory\Available MBytes",
    "\Memory\Pages/sec",
    "\Memory\Page Faults/sec",
    "\Memory\% Committed Bytes In Use",
    
    # Disk I/O
    "\PhysicalDisk(*)\Disk Read Bytes/sec",
    "\PhysicalDisk(*)\Disk Write Bytes/sec",
    "\PhysicalDisk(*)\Avg. Disk Queue Length",
    "\PhysicalDisk(*)\Avg. Disk sec/Read",
    "\PhysicalDisk(*)\Avg. Disk sec/Write",
    "\PhysicalDisk(*)\% Disk Time",
    
    # System
    "\System\Context Switches/sec",
    "\System\Processor Queue Length"
)

Write-Host "[*] Configuring performance counters..." -ForegroundColor Yellow

# Create the data collector set
$counterList = $counters -join " "

try {
    # Delete existing collector if present
    $existing = logman query $collectorName 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[*] Removing existing collector..." -ForegroundColor Yellow
        logman delete $collectorName | Out-Null
    }
    
    # Create new collector
    Write-Host "[*] Creating data collector set..." -ForegroundColor Yellow
    
    # Build logman command
    $logmanArgs = @(
        "create", "counter", $collectorName,
        "-f", "bincirc",           # Binary circular format
        "-v", "mmddhhmm",           # Version in filename
        "-max", "500",              # Max 500 MB
        "-c", ($counters -join " "),
        "-si", "00:00:01",          # Sample interval: 1 second
        "-o", $outputFile
    )
    
    $process = Start-Process -FilePath "logman" -ArgumentList $logmanArgs -NoNewWindow -Wait -PassThru
    
    if ($process.ExitCode -ne 0) {
        throw "Failed to create data collector set (exit code: $($process.ExitCode))"
    }
    
    Write-Host "[✓] Data collector set created successfully" -ForegroundColor Green
    Write-Host ""
    
    # Start the collector
    Write-Host "[*] Starting data collection..." -ForegroundColor Yellow
    logman start $collectorName | Out-Null
    
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start data collector"
    }
    
    Write-Host "[✓] Data collection started" -ForegroundColor Green
    Write-Host ""
    Write-Host "======================================" -ForegroundColor Cyan
    Write-Host "  MONITORING ACTIVE" -ForegroundColor Green
    Write-Host "======================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Performance data is being collected to:" -ForegroundColor White
    Write-Host "  $outputFile" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "TO STOP COLLECTION, press Ctrl+C or run:" -ForegroundColor Yellow
    Write-Host "  logman stop $collectorName" -ForegroundColor White
    Write-Host "  logman delete $collectorName" -ForegroundColor White
    Write-Host ""
    Write-Host "TO VIEW DATA:" -ForegroundColor Yellow
    Write-Host "  1. Open Performance Monitor (perfmon.exe)" -ForegroundColor White
    Write-Host "  2. Click 'Performance Monitor' in left pane" -ForegroundColor White
    Write-Host "  3. Click toolbar icon 'View Log Data' (folder icon)" -ForegroundColor White
    Write-Host "  4. Browse to: $outputFile" -ForegroundColor Cyan
    Write-Host ""
    
    # Optional: Wait for test duration then auto-stop
    if ($Duration -ne "manual") {
        Write-Host "[*] Auto-stop configured for: $Duration" -ForegroundColor Yellow
        Write-Host "[*] Waiting..." -ForegroundColor Yellow
        
        # Parse duration
        $ts = [TimeSpan]::Parse($Duration)
        $seconds = $ts.TotalSeconds
        
        # Wait with progress updates
        $interval = 30  # Update every 30 seconds
        $elapsed = 0
        
        while ($elapsed -lt $seconds) {
            Start-Sleep -Seconds $interval
            $elapsed += $interval
            $remaining = $seconds - $elapsed
            Write-Host "[*] Collection running... ($elapsed s elapsed, $remaining s remaining)" -ForegroundColor Gray
        }
        
        Write-Host ""
        Write-Host "[*] Duration complete, stopping collection..." -ForegroundColor Yellow
        logman stop $collectorName | Out-Null
        logman delete $collectorName | Out-Null
        
        Write-Host "[✓] Collection stopped and saved" -ForegroundColor Green
        Write-Host "[✓] Data file: $outputFile" -ForegroundColor Green
    }
    else {
        # Manual mode - wait for Ctrl+C
        Write-Host "[*] Press Ctrl+C to stop collection" -ForegroundColor Yellow
        
        try {
            while ($true) {
                Start-Sleep -Seconds 60
                Write-Host "[*] Collection running... (press Ctrl+C to stop)" -ForegroundColor Gray
            }
        }
        finally {
            Write-Host ""
            Write-Host "[*] Stopping collection..." -ForegroundColor Yellow
            logman stop $collectorName | Out-Null
            logman delete $collectorName | Out-Null
            Write-Host "[✓] Collection stopped" -ForegroundColor Green
        }
    }
    
}
catch {
    Write-Host ""
    Write-Host "[!] ERROR: $_" -ForegroundColor Red
    Write-Host ""
    
    # Cleanup on error
    try {
        logman stop $collectorName 2>$null | Out-Null
        logman delete $collectorName 2>$null | Out-Null
    }
    catch {
        # Ignore cleanup errors
    }
    
    exit 1
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  COLLECTION COMPLETE" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Open Performance Monitor to view collected data" -ForegroundColor White
Write-Host "  2. Analyze application logs for performance events" -ForegroundColor White
Write-Host "  3. Correlate system metrics with application logs" -ForegroundColor White
Write-Host ""

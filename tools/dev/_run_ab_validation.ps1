# A/B Validation Runner for FAST Render-Clock Experiment
param([string]$Mode = 'both', [int]$DragSeconds = 45)

$workspace = "e:\ai-pacs\ai-pacs codes\ai-pacs beta version"
$logsDir = "$workspace\user_data\logs"
$outDir = "$logsDir\ab_runs"
$viewerLog = "$logsDir\viewer_diagnostics.log"
$dlLog = "$logsDir\download_diagnostics.log"

New-Item -ItemType Directory -Path $outDir -Force | Out-Null

Write-Host "`n=== FAST Render-Clock A/B Validation ===" -ForegroundColor Cyan

function Stop-App {
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "main.py" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

function Rotate-Logs([string]$Name) {
    Write-Host "`nRotating logs ($Name)..." -ForegroundColor Yellow
    if (Test-Path $viewerLog) {
        Copy-Item -Path $viewerLog -Destination "$outDir\${Name}_viewer.log" -Force
        Clear-Content -Path $viewerLog -Force
        Write-Host "  [OK] viewer log" -ForegroundColor Green
    }
    if (Test-Path $dlLog) {
        Copy-Item -Path $dlLog -Destination "$outDir\${Name}_download.log" -Force
        Clear-Content -Path $dlLog -Force
        Write-Host "  [OK] download log" -ForegroundColor Green
    }
}

function RunScenario([string]$Mode, [string]$EnvVal) {
    Write-Host "`nLaunching AIPacs ($Mode)..." -ForegroundColor Yellow
    Write-Host "  Env: AIPACS_FAST_RENDER_CLOCK_EXPERIMENT=$EnvVal" -ForegroundColor Cyan
    Write-Host "`nManual steps:" -ForegroundColor Yellow
    Write-Host "  1. Open series 203 or patient 41256 / series 202" -ForegroundColor Yellow
    Write-Host "  2. Drag/scroll for $DragSeconds seconds" -ForegroundColor Yellow
    Write-Host "  3. Close app normally" -ForegroundColor Yellow
    Write-Host "  4. Press ENTER when done" -ForegroundColor Yellow
    
    if ($EnvVal -eq "1") {
        $env:AIPACS_FAST_RENDER_CLOCK_EXPERIMENT = "1"
    }
    else {
        $env:AIPACS_FAST_RENDER_CLOCK_EXPERIMENT = ""
    }
    
    & "$workspace\.venv\Scripts\python.exe" "$workspace\main.py"
    Start-Sleep -Seconds 2
}

Stop-App

if ($Mode -eq "baseline" -or $Mode -eq "both") {
    Write-Host "`n*** BASELINE RUN (EXPERIMENT OFF) ***" -ForegroundColor Green
    Rotate-Logs "baseline"
    RunScenario "Baseline" "0"
    Write-Host "`n[OK] Baseline complete" -ForegroundColor Green
}

if ($Mode -eq "experiment" -or $Mode -eq "both") {
    Write-Host "`n*** EXPERIMENT RUN (EXPERIMENT ON) ***" -ForegroundColor Magenta
    Stop-App
    Rotate-Logs "experiment"
    RunScenario "Experiment" "1"
    Write-Host "`n[OK] Experiment complete" -ForegroundColor Green
}

Write-Host "`nDone. Logs: $outDir" -ForegroundColor Cyan

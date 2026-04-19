param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath,

    [string]$Scenario = "common_local_viewing",

    [string]$PythonExe = ".venv\\Scripts\\python.exe",

    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\\..")
$harness = Join-Path $repoRoot "tools\\performance\\clearcanvas_aipacs_kpi_harness.py"

if (-not (Test-Path $ExecutablePath)) {
    throw "ClearCanvas executable not found: $ExecutablePath"
}

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputDir = Join-Path $repoRoot "generated-files\\benchmarks\\clearcanvas_manual_$stamp"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

& $PythonExe $harness emit-execution-pack --scenario $Scenario --viewer clearcanvas --output-dir $OutputDir | Out-Null

$instructions = Join-Path $OutputDir "instructions.md"
$metricsJson = Join-Path $OutputDir "clearcanvas_process_metrics.json"

Write-Host ""
Write-Host "Execution pack prepared:"
Write-Host "  Instructions : $instructions"
Write-Host "  Output JSON   : $metricsJson"
Write-Host ""
Write-Host "ClearCanvas will launch now. Perform the scenario steps while monitoring runs."
Write-Host ""

$proc = Start-Process -FilePath $ExecutablePath -PassThru

& $PythonExe $harness monitor-process --scenario $Scenario --pid $proc.Id --label "ClearCanvas" --output $metricsJson

Write-Host ""
Write-Host "Monitoring finished."
Write-Host "Review and fill manual observations in:"
Write-Host "  $(Join-Path $OutputDir 'manual_step_results.csv')"
Write-Host ""

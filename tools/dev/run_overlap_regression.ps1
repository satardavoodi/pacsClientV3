# F1 overlap pixel-quality regression bundle (F1.3 wiring).
#
# Runs the gate that protects against image-quality regressions in
# Lightweight2DPipeline (settled + drag rendering) plus the harness/parser
# tests that produce overlap KPIs.
#
# Usage:
#   .\tools\dev\run_overlap_regression.ps1          # validate against goldens
#   .\tools\dev\run_overlap_regression.ps1 -Capture # re-capture goldens (review the diff!)
#
# Required green BEFORE merging any change to:
#   modules/viewer/fast/lightweight_2d_pipeline.py
#   modules/viewer/fast/qt_viewer_bridge.py
#   modules/viewer/fast/qt_slice_viewer.py
#   builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/*
#
# See: plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md (F1.3)
param(
    [switch]$Capture
)

$ErrorActionPreference = "Stop"
Set-Location -Path (Join-Path $PSScriptRoot "..\..")

$venvPython = ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Runtime venv not found at $venvPython. Run setup_env.ps1 first."
    exit 2
}

$tests = @(
    "tests/viewer/test_overlap_pixel_quality.py",
    "tests/viewer/test_overlap_pixel_quality_drag.py",
    "tests/performance/test_overlap_kpi_parser.py",
    "tests/performance/test_clearcanvas_aipacs_kpi_harness.py"
)

$pytestArgs = @("-m", "pytest") + $tests + @("-v")
if ($Capture) {
    Write-Host "[F1.3] Re-capturing F1.1 goldens..." -ForegroundColor Yellow
    $pytestArgs += "--capture-golden"
}

Write-Host "[F1.3] Running overlap pixel-quality regression bundle..." -ForegroundColor Cyan
& $venvPython @pytestArgs
$rc = $LASTEXITCODE

if ($rc -eq 0) {
    Write-Host "[F1.3] OK - overlap regression bundle GREEN." -ForegroundColor Green
} else {
    Write-Host "[F1.3] FAIL - overlap regression bundle RED (exit=$rc)." -ForegroundColor Red
    Write-Host "       Inspect diffs against tests/viewer/golden/*.json." -ForegroundColor Red
}
exit $rc

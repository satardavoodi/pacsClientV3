Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [switch]$SkipInstall,
    [switch]$SkipAudit,
    [switch]$SkipDiagnose
)

. "$PSScriptRoot\_common.ps1"

$repo = Get-RepoRoot
$py = Ensure-BuildVenv
$logFile = Get-LogFile -Prefix "build_appB"
$specPath = Join-Path $repo "builder\spec\appB_slicer.spec"

Write-Host "[builder] Build App B log: $logFile"

if (-not $SkipInstall) {
    Install-BuildDependencies -PythonExe $py -LogFile $logFile
}

if (-not $SkipAudit) {
    Invoke-Logged -LogFile $logFile -Description "Run scan_imports.ps1 (audit + docs)" -ScriptBlock {
        & (Join-Path $PSScriptRoot "scan_imports.ps1")
    }
}

if (-not $SkipDiagnose) {
    Invoke-Logged -LogFile $logFile -Description "Run diagnose_imports.ps1" -ScriptBlock {
        & (Join-Path $PSScriptRoot "diagnose_imports.ps1")
    }
}

Invoke-PyInstallerBuild -PythonExe $py -AppKey "appB" -SpecPath $specPath -LogFile $logFile

$exePath = Get-AppExePath -AppKey "appB"
Write-Host "[builder] App B EXE: $exePath"
if (-not (Test-Path $exePath)) {
    throw "App B executable not found after build: $exePath"
}


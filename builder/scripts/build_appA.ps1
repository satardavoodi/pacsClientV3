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
$logFile = Get-LogFile -Prefix "build_appA"
$specPath = Join-Path $repo "builder\spec\appA_workstation.spec"

Write-Host "[builder] Build App A log: $logFile"

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

Invoke-PyInstallerBuild -PythonExe $py -AppKey "appA" -SpecPath $specPath -LogFile $logFile

$exePath = Get-AppExePath -AppKey "appA"
Write-Host "[builder] App A EXE: $exePath"
if (-not (Test-Path $exePath)) {
    throw "App A executable not found after build: $exePath"
}


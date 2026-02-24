Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [switch]$SkipInstall,
    [switch]$SkipAudit,
    [switch]$SkipDiagnose
)

. "$PSScriptRoot\_common.ps1"

$logFile = Get-LogFile -Prefix "build_all"
Write-Host "[builder] Build-all log: $logFile"

Invoke-Logged -LogFile $logFile -Description "Build App A" -ScriptBlock {
    & (Join-Path $PSScriptRoot "build_appA.ps1") @PSBoundParameters
}

Invoke-Logged -LogFile $logFile -Description "Build App B" -ScriptBlock {
    & (Join-Path $PSScriptRoot "build_appB.ps1") @PSBoundParameters
}

Write-Host "[builder] All builds completed"


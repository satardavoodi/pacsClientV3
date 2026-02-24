Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_common.ps1"

$exe = Get-AppExePath -AppKey "appA"
if (-not (Test-Path $exe)) {
    throw "App A executable not found: $exe"
}

Write-Host "[builder] Launching App A: $exe"
& $exe @args


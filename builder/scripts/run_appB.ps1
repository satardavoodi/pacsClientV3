Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_common.ps1"

$exe = Get-AppExePath -AppKey "appB"
if (-not (Test-Path $exe)) {
    throw "App B executable not found: $exe"
}

Write-Host "[builder] Launching App B: $exe"
& $exe @args


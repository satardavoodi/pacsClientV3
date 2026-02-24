Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_common.ps1"

$builder = Get-BuilderRoot
$targets = @(
    (Join-Path $builder "output\build"),
    (Join-Path $builder "output\dist")
)

foreach ($t in $targets) {
    if (Test-Path $t) {
        Write-Host "[builder] Cleaning $t"
        Get-ChildItem -Force $t | Remove-Item -Recurse -Force
    }
}

Write-Host "[builder] Clean complete (builder/output only)"


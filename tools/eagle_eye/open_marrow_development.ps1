# Human-run source launcher; sign-in and study selection remain human-owned.
param([switch]$WithoutTestControl)
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$clientConfig = Join-Path $repositoryRoot 'generated-files\marrow-stage-20261008\client-development.json'
if (-not (Test-Path -LiteralPath $clientConfig)) {
    throw 'The prepared Development client configuration is unavailable.'
}
$launchArgs = @{Standard=$true;EagleEyeConfig=$clientConfig}
if (-not $WithoutTestControl) { $launchArgs.TestServer=$true }
& (Join-Path $repositoryRoot 'run_app.ps1') @launchArgs

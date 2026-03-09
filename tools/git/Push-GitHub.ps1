[CmdletBinding()]
param(
    [ValidateSet("Auto", "Direct", "Proxy")]
    [string]$Mode = "Auto",
    [string]$Remote = "origin",
    [string]$Branch,
    [switch]$CheckOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Invoke-Git {
    param(
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    & git @Arguments
    $exitCode = $LASTEXITCODE

    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $exitCode."
    }

    return $exitCode
}

function Get-ProxyUrl {
    param(
        [string]$ConfigPath
    )

    if (Test-Path $ConfigPath) {
        $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($config.proxyUrl) {
            return [string]$config.proxyUrl
        }
    }

    foreach ($name in @("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) {
            return $value
        }
    }

    return $null
}

function New-GitArgs {
    param(
        [ValidateSet("Direct", "Proxy")]
        [string]$ConnectionMode,
        [string]$ProxyUrl,
        [string[]]$CommandArgs
    )

    $args = @()

    if ($ConnectionMode -eq "Direct") {
        $args += "-c", "http.proxy="
        $args += "-c", "https.proxy="
    } elseif ($ConnectionMode -eq "Proxy") {
        if (-not $ProxyUrl) {
            throw "Proxy mode requires a proxy URL."
        }

        $args += "-c", "http.proxy=$ProxyUrl"
        $args += "-c", "https.proxy=$ProxyUrl"
    }

    $args += $CommandArgs
    return $args
}

function Test-ConnectionMode {
    param(
        [ValidateSet("Direct", "Proxy")]
        [string]$ConnectionMode,
        [string]$Remote,
        [string]$Branch,
        [string]$ProxyUrl
    )

    Write-Host "Testing $ConnectionMode access to $Remote/$Branch ..."
    $args = New-GitArgs -ConnectionMode $ConnectionMode -ProxyUrl $ProxyUrl -CommandArgs @(
        "ls-remote",
        "--exit-code",
        "--heads",
        $Remote,
        $Branch
    )

    & git @args *> $null
    return ($LASTEXITCODE -eq 0)
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$proxyConfigPath = Join-Path $scriptRoot "github-network.local.json"
$proxyExamplePath = Join-Path $scriptRoot "github-network.example.json"
$proxyUrl = Get-ProxyUrl -ConfigPath $proxyConfigPath

if (-not $Branch) {
    $Branch = (& git branch --show-current).Trim()
}

if (-not $Branch) {
    throw "Could not detect the current branch."
}

$remoteUrl = (& git remote get-url --push $Remote).Trim()
if (-not $remoteUrl) {
    throw "Could not resolve the push URL for remote '$Remote'."
}

Write-Host "Remote : $Remote"
Write-Host "URL    : $remoteUrl"
Write-Host "Branch : $Branch"

if ($proxyUrl) {
    Write-Host "Proxy  : configured"
} else {
    Write-Host "Proxy  : not configured"
}

$candidates = switch ($Mode) {
    "Auto" {
        if ($proxyUrl) {
            @("Direct", "Proxy")
        } else {
            @("Direct")
        }
    }
    "Direct" { @("Direct") }
    "Proxy" { @("Proxy") }
}

$selectedMode = $null

foreach ($candidate in $candidates) {
    if (Test-ConnectionMode -ConnectionMode $candidate -Remote $Remote -Branch $Branch -ProxyUrl $proxyUrl) {
        $selectedMode = $candidate
        break
    }
}

if (-not $selectedMode) {
    $message = "GitHub is unreachable in $Mode mode."

    if (-not $proxyUrl) {
        $message += " If your connection only works through a proxy, copy '$proxyExamplePath' to '$proxyConfigPath' and set the proxy URL once."
    }

    throw $message
}

Write-Host "Using $selectedMode mode."

if ($CheckOnly) {
    exit 0
}

$pushArgs = @("push")
if ($DryRun) {
    $pushArgs += "--dry-run"
}
$pushArgs += "--progress", $Remote, "HEAD:refs/heads/$Branch"

$resolvedArgs = New-GitArgs -ConnectionMode $selectedMode -ProxyUrl $proxyUrl -CommandArgs $pushArgs
$null = Invoke-Git -Arguments $resolvedArgs

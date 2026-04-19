param(
    [switch]$Show,
    [switch]$Tail,
    [int]$Last = 80
)

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$terminalLogDir = Join-Path $repoRoot "log"
$latestPointer = Join-Path $terminalLogDir "latest_terminal_log.txt"

if (-not (Test-Path $latestPointer)) {
    Write-Error "[terminal-log] No latest terminal log pointer found at $latestPointer"
    exit 1
}

$latestLog = (Get-Content -Path $latestPointer -ErrorAction Stop | Select-Object -Last 1).Trim()
if (-not $latestLog) {
    Write-Error "[terminal-log] Latest terminal log pointer is empty"
    exit 1
}

if (-not (Test-Path $latestLog)) {
    Write-Error "[terminal-log] Latest terminal log does not exist: $latestLog"
    exit 1
}

Write-Output $latestLog

if ($Show) {
    Get-Content -Path $latestLog
}
elseif ($Tail) {
    Get-Content -Path $latestLog -Tail $Last
}
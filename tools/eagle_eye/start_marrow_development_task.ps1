# Manual-only Development task. Preserve existing services, tasks and firewall rules.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$deploymentRoot = 'D:\Eagle Eye Server'
$candidateSource = Join-Path $deploymentRoot 'revisions\20261008-lumbar-marrow-r3\source'
$candidateConfig = Join-Path $deploymentRoot 'config\server-marrow-development-20261008.json'
$config = Get-Content -LiteralPath $candidateConfig -Raw | ConvertFrom-Json
if ($config.host -ne '127.0.0.1' -or $config.port -ne 8042 -or
    $config.job_root -ne (Join-Path $deploymentRoot 'jobs-marrow-development-20261008')) {
    throw 'The Development configuration does not match the isolated candidate.'
}
if (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Development port is already owned; no task start performed.'
}
$taskName = 'AI-PACS Lumbar Marrow Development 20261008'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Development task already exists; inspect before reuse.'
}
$runner = Join-Path $deploymentRoot 'staging\marrow-20261008\run_marrow_development.py'
$arguments = '"' + $runner + '" --source "' + $candidateSource + '" --config "' + $candidateConfig + '"'
$action = New-ScheduledTaskAction -Execute (Join-Path $candidateSource '.venv\Scripts\python.exe') `
    -Argument $arguments -WorkingDirectory $candidateSource
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings `
    -Description 'Manually started isolated Eagle Eye lumbar marrow Development listener on loopback only.' | Out-Null
Start-ScheduledTask -TaskName $taskName
@{task_name=$taskName;source=$candidateSource;config=$candidateConfig;endpoint='https://127.0.0.1:8042';
  scm_changed=$false;firewall_changed=$false;automatic_trigger=$false} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $deploymentRoot 'revisions\20261008-lumbar-marrow-r3\marrow-development-task.json') -Encoding UTF8
Write-Output 'Manual Development task started. Existing services and firewall unchanged.'

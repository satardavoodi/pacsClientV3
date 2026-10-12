param([switch]$TestServer)

# Start a single source session through Windows Task Scheduler, outside the
# calling terminal's process/job tree. No credentials or elevation are stored.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runner = Join-Path $root 'run_app.ps1'
$taskName = 'AIPacs-Source-Detached'
$description = 'Manual AI-PACS source launch independent of the initiating console.'
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
try { $existing = $folder.GetTask($taskName) } catch { $existing = $null }
if ($existing -and $existing.Definition.RegistrationInfo.Description -ne $description) {
    throw 'An unrelated task already uses the reserved launcher name; it was not changed.'
}
if ($existing -and $existing.GetInstances(0).Count -gt 0) {
    throw 'The detached source session is already running. Close it normally first.'
}
# Only a human-selected fresh launch is allowed; do not trigger takeover of an
# existing workstation launched by another route.
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"
if ($running | Where-Object { $_.CommandLine -match '(?i)(?:^|[\s"\\])main\.py(?:[\s"]|$)' }) {
    throw 'A source workstation is already running. Close it normally first.'
}
$definition = $service.NewTask(0)
$definition.RegistrationInfo.Description = $description
$definition.Principal.LogonType = 3 # TASK_LOGON_INTERACTIVE_TOKEN
$definition.Principal.RunLevel = 0 # TASK_RUNLEVEL_LUA
$definition.Settings.ExecutionTimeLimit = 'PT0S'
$definition.Settings.DisallowStartIfOnBatteries = $false
$definition.Settings.StopIfGoingOnBatteries = $false
$definition.Settings.AllowHardTerminate = $false
$definition.Settings.MultipleInstances = 2 # Ignore duplicate Run requests.
$action = $definition.Actions.Create(0)
$action.Path = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$action.WorkingDirectory = $root
$action.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '"'
if ($TestServer) { $action.Arguments += ' -TestServer' }
$task = $folder.RegisterTaskDefinition($taskName, $definition, 6, $null, $null, 3)
$instance = $task.Run($null)
Write-Output ('Detached source session requested. Task instance: ' + $instance.InstanceGuid)
# There are no triggers, retries or automatic restarts. The task remains for
# exit-result inspection and is reused only on the next explicit invocation.

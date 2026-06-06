# Agent-driven full-environment launch for the AI-PACS SOURCE build (Zeta MPR canon validation).
# The agent's shell is stripped (no COMPUTERNAME / WINDIR), which makes the license hardware-ID
# mismatch (license dialog) and crashes qtawesome. This repopulates the real user environment first.
$ErrorActionPreference = 'SilentlyContinue'
$repo = 'E:\ai-pacs\ai-pacs codes\ai-pacs beta version'

# 1) Repopulate the full environment (Machine + User scope) into this process.
foreach ($scope in @([System.EnvironmentVariableTarget]::Machine, [System.EnvironmentVariableTarget]::User)) {
    $vars = [System.Environment]::GetEnvironmentVariables($scope)
    foreach ($k in $vars.Keys) { try { Set-Item -Path ("Env:" + $k) -Value $vars[$k] } catch {} }
}
# Critical identity vars (license hardware-ID = SHA256(MAC + "-" + COMPUTERNAME)).
$env:COMPUTERNAME = [System.Environment]::MachineName
if (-not $env:WINDIR)     { $env:WINDIR = 'C:\Windows' }
if (-not $env:SystemRoot) { $env:SystemRoot = 'C:\Windows' }

# 2) Kill any running instances so the single-instance guard can't hand off to stale code.
taskkill /F /IM python.exe  /T 2>$null | Out-Null
taskkill /F /IM pythonw.exe /T 2>$null | Out-Null
taskkill /F /IM aipacs.exe  /T 2>$null | Out-Null
Start-Sleep -Seconds 3
taskkill /F /IM python.exe  /T 2>$null | Out-Null

# 3) Clear stale MPR bytecode so edited .py modules recompile; isolate the pyc cache for this run.
Get-ChildItem -Path (Join-Path $repo 'modules\mpr') -Recurse -Directory -Filter '__pycache__' |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'aipacs_pyc_agent_run'
Remove-Item -Recurse -Force $env:PYTHONPYCACHEPREFIX 2>$null

# 4) Zeta MPR canonical fix ON; yellow diagnostic overlay OFF.
$env:AIPACS_ZETA_MPR_CANONICALIZE = '1'
$env:ZETA_MPR_DIAG = '0'

# 5) Launch the SOURCE build with the explicit .venv interpreter, detached, capturing logs.
$py  = Join-Path $repo '.venv\Scripts\python.exe'
$out = Join-Path $repo '_agent_run_stdout.log'
$err = Join-Path $repo '_agent_run_stderr.log'
Remove-Item $out, $err 2>$null
if (-not (Test-Path $py)) { Write-Host "ERROR: .venv python not found at $py"; exit 1 }
$p = Start-Process -FilePath $py -ArgumentList 'main.py' -WorkingDirectory $repo `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
Write-Host ("LAUNCHED pid=" + $p.Id + " COMPUTERNAME=" + $env:COMPUTERNAME + " WINDIR=" + $env:WINDIR)
Write-Host ("CANON=" + $env:AIPACS_ZETA_MPR_CANONICALIZE + " DIAG=" + $env:ZETA_MPR_DIAG)

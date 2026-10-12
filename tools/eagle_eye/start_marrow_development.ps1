# Start only the tested, isolated loopback Development candidate on Razi.
# Does not alter Windows services, firewall rules, or shared server configuration.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$deploymentRoot = 'D:\Eagle Eye Server'
$candidateSource = Join-Path $deploymentRoot 'revisions\20261008-lumbar-marrow-r3\source'
$candidateConfig = Join-Path $deploymentRoot 'config\server-marrow-development-20261008.json'
if (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Development port is already owned; no launch performed.'
}
if (Test-Path -LiteralPath $candidateConfig) {
    throw 'Development config already exists; inspect before reuse.'
}
$config = Get-Content -LiteralPath (Join-Path $deploymentRoot 'config\server-20260930-echomind.json') -Raw | ConvertFrom-Json
$config.host = '127.0.0.1'
$config.port = 8042
$config.job_root = Join-Path $deploymentRoot 'jobs-marrow-development-20261008'
$config.worker_threads = 1
$config.max_jobs_per_client = 1
$config.PSObject.Properties.Remove('echomind')
$config.PSObject.Properties.Remove('secretary')
New-Item -ItemType Directory -Path $config.job_root -Force | Out-Null
$config | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $candidateConfig -Encoding UTF8
$privateLogs = Join-Path $deploymentRoot 'logs\marrow-development-20261008'
New-Item -ItemType Directory -Path $privateLogs -Force | Out-Null
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:PYTHONNOUSERSITE = '1'
$entryPoint = Join-Path $candidateSource 'tools\eagle_eye\serve.py'
$process = Start-Process -FilePath (Join-Path $candidateSource '.venv\Scripts\python.exe') `
    -ArgumentList @('-u', ('"' + $entryPoint + '"'), '--config', ('"' + $candidateConfig + '"')) `
    -WorkingDirectory $candidateSource -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $privateLogs 'stdout.log') `
    -RedirectStandardError (Join-Path $privateLogs 'stderr.log') -PassThru
@{
    process_id = $process.Id
    source = $candidateSource
    config = $candidateConfig
    port = 8042
    endpoint = 'https://127.0.0.1:8042'
    firewall_changed = $false
    scm_changed = $false
    started_utc = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $deploymentRoot 'revisions\20261008-lumbar-marrow-r3\marrow-development-launch.json') -Encoding UTF8
Write-Output 'Isolated loopback TLS Development candidate launched; no SCM/firewall changes.'

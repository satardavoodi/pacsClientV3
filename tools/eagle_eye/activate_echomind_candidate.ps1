# Razi-only Developer source transition; not an installer or release approval.
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
if($env:COMPUTERNAME -ne 'WIN-CTBQPS2GSM3') { throw 'Unexpected deployment host.' }
$root='D:\Eagle Eye Server'
$baseline=$root+'\revisions\20260930-developer\source'
$candidate=$root+'\revisions\20260930-echomind\source'
$oldConfig=$root+'\config\server-developer-20260930.json'
$newConfig=$root+'\config\server-20260930-echomind.json'
$oldCommand='"'+$baseline+'\.venv\Scripts\python.exe" "'+$baseline+'\tools\eagle_eye\windows_service.py" "'+$oldConfig+'"'
$newCommand='"'+$candidate+'\.venv\Scripts\python.exe" "'+$candidate+'\tools\eagle_eye\windows_service.py" "'+$newConfig+'"'
$service=Get-CimInstance Win32_Service -Filter "Name='AIPacsEagleEye'"
if($service.PathName -cne $oldCommand -or $service.StartName -ine 'NT AUTHORITY\LocalService' -or $service.State -ne 'Running') { throw 'Unexpected service ownership or state.' }
$stage=Get-Content -Raw -LiteralPath ($root+'\validation\echomind-20260930-echomind-stage.json') | ConvertFrom-Json
$probe=Get-Content -Raw -LiteralPath ($root+'\validation\echomind-candidate-workflows-final-20260930.json') | ConvertFrom-Json
if(!$stage.automated_tests_passed -or !$probe.passed -or @($probe.results).Count -ne 15) { throw 'Candidate checks are incomplete.' }
$manifest=Get-Content -Raw -LiteralPath ($root+'\incoming\overlay-manifest.json') | ConvertFrom-Json
if($manifest.archive_sha256 -ne $stage.overlay_sha256) { throw 'Staging receipt differs.' }
foreach($file in $manifest.files) {
    if((Get-FileHash -LiteralPath (Join-Path $candidate $file.path)).Hash.ToLower() -ne $file.sha256) { throw 'Candidate source drifted.' }
}
$config=Get-Content -Raw -LiteralPath $newConfig | ConvertFrom-Json
$active=0
foreach($directory in Get-ChildItem -LiteralPath $config.job_root -Directory) {
    $path=Join-Path $directory.FullName 'state.json'
    if(Test-Path -LiteralPath $path) {
        $state=Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
        if($state.status -notin @('succeeded','failed','cancelled','interrupted')) { $active++ }
    }
}
if($active -ne 0) { throw 'Active model jobs prevent this transition.' }
$listeners=@(Get-NetTCPConnection -State Listen -LocalPort 8002)
if($listeners.Count -ne 1) { throw 'Unexpected listener count.' }
$process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$listeners[0].OwningProcess)
if($process.CommandLine -notlike '*modules.ai_imaging.eagle_eye_remote.service_host*server-developer-20260930.json*') { throw 'Unexpected listener ownership.' }
$backup=$root+'\backups\echomind-cutover-20260930'
if(Test-Path -LiteralPath $backup) { throw 'Transition backup already exists.' }
New-Item -ItemType Directory -Path $backup | Out-Null
@{old_command=$oldCommand;new_command=$newCommand;baseline=$baseline;candidate=$candidate;config=$newConfig} | ConvertTo-Json | Set-Content -LiteralPath ($backup+'\scm-transition.json') -Encoding UTF8
$changed=$false
try {
    Stop-Service AIPacsEagleEye
    (Get-Service AIPacsEagleEye).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(45))
    $result=Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{PathName=$newCommand}
    if($result.ReturnValue -ne 0) { throw 'SCM command update failed.' }
    $changed=$true
    Start-Service AIPacsEagleEye
    (Get-Service AIPacsEagleEye).WaitForStatus('Running',[TimeSpan]::FromSeconds(60))
    & ($candidate+'\.venv\Scripts\python.exe') ($candidate+'\tools\eagle_eye\check_echomind_listener.py') --server-config $newConfig
    if($LASTEXITCODE -ne 0) { throw 'Authenticated listener acceptance failed.' }
    @{activated=$true;source=$candidate;config=$newConfig;port=8002;active_jobs_before=0;overlay_sha256=$stage.overlay_sha256;rollback_exercised=$false} | ConvertTo-Json | Set-Content -LiteralPath ($root+'\validation\echomind-cutover-20260930.json') -Encoding UTF8
    'Developer EchoMind service activated; whole-server GUI/model acceptance remains separate.'
} catch {
    if($changed) {
        if((Get-Service AIPacsEagleEye).Status -ne 'Stopped') { Stop-Service AIPacsEagleEye; (Get-Service AIPacsEagleEye).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(45)) }
        $result=Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{PathName=$oldCommand}
        if($result.ReturnValue -ne 0) { throw 'Rollback command restoration failed.' }
    }
    if((Get-Service AIPacsEagleEye).Status -eq 'Stopped') { Start-Service AIPacsEagleEye }
    throw
}

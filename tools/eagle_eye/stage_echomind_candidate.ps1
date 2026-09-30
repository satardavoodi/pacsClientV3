param(
    [Parameter(Mandatory=$true)][string]$OverlayArchive,
    [Parameter(Mandatory=$true)][string]$OverlayManifest,
    [string]$Root='D:\Eagle Eye Server',
    [string]$Candidate='20260930-echomind',
    [string]$Baseline='20260930-developer',
    [string]$BaselineConfig='server-developer-20260930.json',
    [switch]$Resume
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
if ($env:COMPUTERNAME -ne 'WIN-CTBQPS2GSM3') { throw 'Unexpected deployment host.' }
if ($Candidate -notmatch '^\d{8}-[a-z0-9-]+$' -or $Baseline -notmatch '^\d{8}-[a-z0-9-]+$') { throw 'Invalid revision name.' }
$rootPath=[IO.Path]::GetFullPath($Root)
if($rootPath -ne 'D:\Eagle Eye Server') { throw 'Unexpected deployment root.' }
$source=Join-Path $rootPath ('revisions\'+$Baseline+'\source')
$target=Join-Path $rootPath ('revisions\'+$Candidate+'\source')
if(!(Test-Path -LiteralPath ($source+'\main.py')) -or ((Test-Path -LiteralPath $target) -and !$Resume)) { throw 'Baseline missing or candidate already exists.' }
if($BaselineConfig -notmatch '^server-[a-z0-9-]+\.json$') { throw 'Invalid baseline configuration name.' }
$previousConfig=Join-Path $rootPath ('config\'+$BaselineConfig)
if(!(Test-Path -LiteralPath $previousConfig)) { throw 'Baseline configuration is missing.' }
$manifest=Get-Content -Raw -LiteralPath $OverlayManifest | ConvertFrom-Json
$archiveHash=(Get-FileHash -LiteralPath $OverlayArchive -Algorithm SHA256).Hash.ToLower()
if($archiveHash -ne $manifest.archive_sha256) { throw 'Overlay archive hash mismatch.' }
$archivePaths=& tar.exe -tf $OverlayArchive
if($LASTEXITCODE -ne 0) { throw 'Cannot inspect overlay archive.' }
foreach($entry in $archivePaths) {
    if($entry.Contains('..') -or $entry.StartsWith('/') -or $entry.Contains(':')) { throw 'Unsafe archive path.' }
    if(!$entry.EndsWith('/') -and $entry -notin @($manifest.files.path)) { throw 'Unexpected overlay file.' }
}
if(!$Resume) {
    New-Item -ItemType Directory -Path $target | Out-Null
    & robocopy.exe $source $target /E /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD ($source+'\.venv') ($source+'\generated-files') ($source+'\user_data') __pycache__ .pytest_cache
    if($LASTEXITCODE -gt 7) { throw 'Baseline copy failed.' }
    foreach($name in @('.venv','generated-files','user_data')) {
        New-Item -ItemType Junction -Path (Join-Path $target $name) -Target (Join-Path $source $name) | Out-Null
    }
} else {
    if((Get-FileHash -LiteralPath ($target+'\main.py')).Hash -ne (Get-FileHash -LiteralPath ($source+'\main.py')).Hash) { throw 'Partial candidate differs from the baseline.' }
    foreach($name in @('.venv','generated-files','user_data')) {
        $junction=Get-Item -LiteralPath (Join-Path $target $name)
        if($junction.LinkType -ne 'Junction' -or (Join-Path $source $name) -notin @($junction.Target)) { throw 'Unexpected partial-candidate runtime link.' }
    }
}
& tar.exe -xf $OverlayArchive -C $target
if($LASTEXITCODE -ne 0) { throw 'Overlay extraction failed.' }
foreach($item in $manifest.files) {
    $file=Join-Path $target $item.path
    if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower() -ne $item.sha256) { throw 'Candidate overlay hash mismatch.' }
}
$private=Join-Path $rootPath ('config\echomind-'+$Candidate)
New-Item -ItemType Directory -Path $private -Force | Out-Null
& icacls.exe $private /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-19:(OI)(CI)R' | Out-Null
if($LASTEXITCODE -ne 0) { throw 'Private configuration ACL failed.' }
$providerSource='D:\Program Files\AI_PACS_SERVER\data\echomind'
foreach($name in @('settings.json','centers.json')) {
    $providerFile=Join-Path $providerSource $name
    if(!(Test-Path -LiteralPath $providerFile)) { throw 'Existing private EchoMind configuration is missing.' }
    Copy-Item -LiteralPath $providerFile -Destination (Join-Path $private $name)
}
$config=Get-Content -Raw -LiteralPath $previousConfig | ConvertFrom-Json
$config | Add-Member -NotePropertyName echomind -NotePropertyValue @{config_dir=$private;max_requests=4;max_requests_per_client=1} -Force
$newConfig=Join-Path $rootPath ('config\server-'+$Candidate+'.json')
[IO.File]::WriteAllText($newConfig,($config | ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH=$target
Push-Location $target
try {
    & ($target+'\.venv\Scripts\python.exe') -m pytest -p no:debugging tests/code/echomind/test_eagle_eye_echomind.py tests/code/echomind/test_eagle_eye_echomind_core.py tests/code/echomind/test_remote_backend.py tests/code/ai_imaging/test_eagle_eye_remote.py tests/code/ai_imaging/test_eagle_eye_service_host.py -q --reruns 0 --tb=short
    if($LASTEXITCODE -ne 0) { throw 'Candidate regression checks failed.' }
    & ($target+'\.venv\Scripts\python.exe') -m pip check
    if($LASTEXITCODE -ne 0) { throw 'Candidate dependency check failed.' }
} finally { Pop-Location }
$receipt=@{candidate=$Candidate;baseline=$Baseline;source=$target;config=$newConfig;overlay_sha256=$archiveHash;overlay_files=@($manifest.files).Count;automated_tests_passed=$true;activated=$false}
$receiptPath=Join-Path $rootPath ('validation\echomind-'+$Candidate+'-stage.json')
[IO.File]::WriteAllText($receiptPath,($receipt | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
'Candidate staged and verified; service activation has not occurred.'

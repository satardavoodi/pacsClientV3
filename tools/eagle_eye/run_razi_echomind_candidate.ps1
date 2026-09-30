param([switch]$TestServer)
$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'WIN-CTBQPS2GSM3') { throw 'This launcher belongs to Razi.' }
$source='D:\Eagle Eye Server\revisions\20260930-echomind\source'
$config='D:\Eagle Eye Server\config\server-20260930-echomind.json'
$native='D:\Eagle Eye Server\revisions\20260930-echomind\slicer-software-probe\AIPacsAdvancedViewer.exe'
$existing=@(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match '(?i)\bmain\.py\b' -and $_.CommandLine -like '*Eagle Eye Server*'
})
if($existing.Count -ne 0) { throw 'Close the existing Razi source workstation before this launch. No process was stopped.' }
if(!(Test-Path -LiteralPath $native)) { throw 'Validated app-local graphics candidate is missing.' }
$env:AIPACS_ADVANCED_VIEWER_EXE=$native
$env:AIPACS_BRAIN_BUNDLE=Join-Path $source 'generated-files\eagle-eye\brain-tf212-py310\model'
$env:PYTHONNOUSERSITE='1'
$env:AIPACS_NO_TAKEOVER='1'
$env:QT_OPENGL='software'
$env:QT_OPENGL_DLL='opengl32sw'
$env:QT_QUICK_BACKEND='software'
$env:PATH=(Join-Path $source 'graphics_runtime')+';'+$env:PATH
Set-Location -LiteralPath $source
& (Join-Path $source 'run_app.ps1') -EagleEyeServer -EagleEyeConfig $config -TestServer:$TestServer
exit $LASTEXITCODE

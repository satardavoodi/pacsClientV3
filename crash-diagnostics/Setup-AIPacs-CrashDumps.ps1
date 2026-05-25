# ============================================================================
#  Setup-AIPacs-CrashDumps.ps1
#  ---------------------------------------------------------------------------
#  Tells Windows to automatically write a crash dump every time AIPacs.exe
#  terminates abnormally. The dump names the exact faulting code, so the next
#  crash can be diagnosed precisely instead of guessed at.
#
#  RUN THIS ONCE, AS ADMINISTRATOR:
#    Right-click this file  ->  "Run with PowerShell"   (approve the UAC prompt)
#    or, in an elevated PowerShell window:
#      powershell -ExecutionPolicy Bypass -File "Setup-AIPacs-CrashDumps.ps1"
#
#  It is safe and fully reversible (see the last line of output).
# ============================================================================

$ErrorActionPreference = 'Stop'

# 1. Require Administrator (HKLM registry write needs elevation) -------------
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "This script must be run as Administrator."
    Write-Host   "Right-click the file and choose 'Run as administrator', then try again."
    Read-Host "Press Enter to close"
    exit 1
}

# 2. Crash-dump folder on the Desktop (easy to find and send) ----------------
$dumpFolder = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AIPacs-CrashDumps'
New-Item -ItemType Directory -Force -Path $dumpFolder | Out-Null

# 3. Register WER LocalDumps for AIPacs.exe ----------------------------------
#    DumpType 1 = mini dump: small (~30-60 MB) but contains the crashing
#    thread's stack, the exception code, and the loaded-module list -- enough
#    to pinpoint the fault. DumpCount 10 = keep the 10 most recent.
$key = 'HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\AIPacs.exe'
New-Item -Path $key -Force | Out-Null
New-ItemProperty -Path $key -Name 'DumpFolder' -Value $dumpFolder -PropertyType ExpandString -Force | Out-Null
New-ItemProperty -Path $key -Name 'DumpType'   -Value 1  -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $key -Name 'DumpCount'  -Value 10 -PropertyType DWord -Force | Out-Null

Write-Host ""
Write-Host "SUCCESS - crash-dump capture is now enabled for AIPacs.exe." -ForegroundColor Green
Write-Host ""
Write-Host "When the app next closes by itself, a .dmp file will appear in:"
Write-Host "  $dumpFolder" -ForegroundColor Cyan
Write-Host "Send that .dmp file (plus the three logs from user_data\logs) for analysis."
Write-Host ""
Write-Host "To undo this later, run as Administrator:"
Write-Host "  Remove-Item -Path '$key' -Recurse" -ForegroundColor DarkGray
Write-Host ""
Read-Host "Press Enter to close"

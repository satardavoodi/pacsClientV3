<#
.SYNOPSIS
  Collect native-crash + graphics-environment evidence for AI-PACS on an
  end-user PC (OPT-21 / Windows-on-ARM MPR crash investigation, 2026-07-07).

.DESCRIPTION
  Read-only by default. Gathers into a folder on the Desktop (then zips it):
    1. OS / CPU / architecture (incl. Windows-on-ARM host detection)
    2. GPU + driver version (Win32_VideoController)
    3. Microsoft "OpenCL/OpenGL Compatibility Pack" (D3DMappingLayers /
       OpenGLOn12 = Mesa GLon12) package version + architecture
    4. Architecture of the installed AIPacs.exe (PE header: x64 vs ARM64)
    5. Windows Event Log: Application Error / WER / .NET entries for AIPacs
       (faulting module name + exception code = the crash's smoking gun)
    6. WER ReportArchive entries for AIPacs (Report.wer copies)
  -EnableDumps additionally registers WER LocalDumps for AIPacs.exe so the
  NEXT crash writes a full .dmp (requires an elevated PowerShell).

.USAGE
  Copy this file to the end-user PC, open PowerShell, then:
    powershell -ExecutionPolicy Bypass -File .\collect_pc_crash_evidence.ps1
  Optional:
    ... -ExePath "D:\AIPacs\aipacs.exe" -EnableDumps
  Send the produced zip back for analysis.
#>
param(
    [string]$ExePath = "D:\AIPacs\aipacs.exe",
    [switch]$EnableDumps
)

$ErrorActionPreference = 'Continue'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) "aipacs_crash_evidence_$stamp"
New-Item -ItemType Directory -Path $out -Force | Out-Null
$summary = @()

function Save($name, $content) {
    $content | Out-File -FilePath (Join-Path $out $name) -Encoding UTF8
}

# 1 ── OS / CPU / architecture ------------------------------------------------
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor
    $osArch = $env:PROCESSOR_ARCHITECTURE
    $native = 'unknown'
    try {
        # Registry PROCESSOR_ARCHITECTURE reflects the HOST even from emulated shells
        $native = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment').PROCESSOR_ARCHITECTURE
    } catch {}
    $txt = @(
        "Caption        : $($os.Caption)"
        "Version/Build  : $($os.Version) / $($os.BuildNumber)"
        "OSArchitecture : $($os.OSArchitecture)"
        "HostArch(reg)  : $native"
        "ShellArch(env) : $osArch"
        "CPU            : $(($cpu | Select-Object -First 1).Name)"
        "Resolution note: host ARM64 + x64 app => Prism emulation + OpenGLOn12 graphics path"
    ) -join "`r`n"
    Save 'system_info.txt' $txt
    $summary += "HOST ARCH: $native | OS: $($os.Caption) $($os.BuildNumber)"
} catch { Save 'system_info.txt' "FAILED: $_" }

# 2 ── GPU + driver -----------------------------------------------------------
try {
    $gpu = Get-CimInstance Win32_VideoController |
        Select-Object Name, DriverVersion, DriverDate, AdapterCompatibility, VideoProcessor
    $gpu | Format-List | Out-String | Out-File (Join-Path $out 'gpu_driver.txt') -Encoding UTF8
    $summary += "GPU: " + (($gpu | ForEach-Object { "$($_.Name) drv $($_.DriverVersion)" }) -join '; ')
} catch { Save 'gpu_driver.txt' "FAILED: $_" }

# 3 ── D3DMappingLayers / OpenGLOn12 compatibility pack ------------------------
try {
    $pkgs = @()
    try { $pkgs += Get-AppxPackage -Name 'Microsoft.D3DMappingLayers' -ErrorAction SilentlyContinue } catch {}
    try { $pkgs += Get-AppxPackage -Name 'Microsoft.D3DMappingLayers' -AllUsers -ErrorAction SilentlyContinue } catch {}
    if ($pkgs) {
        $pkgs | Select-Object Name, Version, Architecture, InstallLocation |
            Format-List | Out-String | Out-File (Join-Path $out 'd3d_mapping_layers.txt') -Encoding UTF8
        $summary += "D3DMappingLayers (OpenGLOn12): " + (($pkgs | Select-Object -First 1).Version)
    } else {
        Save 'd3d_mapping_layers.txt' 'Microsoft.D3DMappingLayers package NOT found'
        $summary += "D3DMappingLayers: NOT INSTALLED"
    }
    # The actual DLLs an app would load:
    Get-ChildItem "$env:ProgramFiles\WindowsApps\Microsoft.D3DMappingLayers*" -Recurse -Filter 'OpenGLOn12.dll' -ErrorAction SilentlyContinue |
        Select-Object FullName, Length, LastWriteTime |
        Format-List | Out-String | Out-File (Join-Path $out 'd3d_mapping_layers.txt') -Append -Encoding UTF8
} catch { Save 'd3d_mapping_layers.txt' "FAILED: $_" }

# 4 ── AIPacs.exe PE architecture ---------------------------------------------
try {
    if (Test-Path $ExePath) {
        $fs = [System.IO.File]::OpenRead($ExePath)
        try {
            $br = New-Object System.IO.BinaryReader($fs)
            $fs.Seek(0x3C, 'Begin') | Out-Null
            $peOff = $br.ReadInt32()
            $fs.Seek($peOff + 4, 'Begin') | Out-Null
            $machine = $br.ReadUInt16()
        } finally { $fs.Close() }
        $arch = switch ($machine) {
            0x8664 { 'x64 (AMD64) — runs under Prism emulation on an ARM64 host' }
            0xAA64 { 'ARM64 native' }
            0x014C { 'x86 (32-bit)' }
            default { "unknown machine 0x{0:X}" -f $machine }
        }
        Save 'aipacs_exe_arch.txt' "Path: $ExePath`r`nPE machine: 0x$('{0:X4}' -f $machine) => $arch"
        $summary += "AIPacs.exe: $arch"
    } else {
        Save 'aipacs_exe_arch.txt' "Exe not found at $ExePath (pass -ExePath)"
    }
} catch { Save 'aipacs_exe_arch.txt' "FAILED: $_" }

# 5 ── Event Log: crashes for AIPacs -------------------------------------------
try {
    $since = (Get-Date).AddDays(-30)
    $events = Get-WinEvent -FilterHashtable @{
        LogName = 'Application'
        ProviderName = @('Application Error', 'Windows Error Reporting', '.NET Runtime')
        StartTime = $since
    } -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -match 'aipacs|AIPacs' } |
        Select-Object -First 60
    if ($events) {
        $events | Format-List TimeCreated, Id, ProviderName, Message |
            Out-String -Width 300 | Out-File (Join-Path $out 'event_log_aipacs.txt') -Encoding UTF8
        # Extract the smoking gun lines
        $faults = $events | ForEach-Object {
            if ($_.Message -match 'Faulting module name:\s*(\S+).*?Exception code:\s*(\S+)') {
                "$($_.TimeCreated)  module=$($Matches[1])  code=$($Matches[2])"
            }
        } | Where-Object { $_ }
        if ($faults) {
            Save 'FAULTING_MODULES.txt' ($faults -join "`r`n")
            $summary += "FAULTING MODULES:"; $summary += $faults | Select-Object -First 5
        } else {
            $summary += "Event log: AIPacs entries found, no 'Faulting module' pattern (see event_log_aipacs.txt)"
        }
    } else {
        Save 'event_log_aipacs.txt' 'No Application Error/WER/.NET events mentioning AIPacs in the last 30 days'
        $summary += "Event log: NO AIPacs crash records in last 30 days"
    }
} catch { Save 'event_log_aipacs.txt' "FAILED: $_" }

# 6 ── WER ReportArchive --------------------------------------------------------
try {
    $wer = Get-ChildItem "$env:ProgramData\Microsoft\Windows\WER\ReportArchive", "$env:ProgramData\Microsoft\Windows\WER\ReportQueue" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'aipacs' } | Select-Object -First 10
    if ($wer) {
        $wer | Select-Object FullName, LastWriteTime | Format-List |
            Out-String | Out-File (Join-Path $out 'wer_reports.txt') -Encoding UTF8
        foreach ($d in $wer) {
            $rep = Join-Path $d.FullName 'Report.wer'
            if (Test-Path $rep) { Copy-Item $rep (Join-Path $out ("$($d.Name).Report.wer")) -ErrorAction SilentlyContinue }
        }
    } else { Save 'wer_reports.txt' 'No WER ReportArchive/ReportQueue entries matching aipacs' }
} catch { Save 'wer_reports.txt' "FAILED: $_" }

# 7 ── Optional: register full crash dumps for the NEXT crash -------------------
if ($EnableDumps) {
    try {
        $dumpDir = Join-Path $out 'dumps'
        New-Item -ItemType Directory -Path $dumpDir -Force | Out-Null
        $key = 'HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\AIPacs.exe'
        New-Item -Path $key -Force | Out-Null
        Set-ItemProperty -Path $key -Name DumpFolder -Value $dumpDir
        Set-ItemProperty -Path $key -Name DumpType -Value 2      # full dump
        Set-ItemProperty -Path $key -Name DumpCount -Value 3
        $summary += "LocalDumps ENABLED -> $dumpDir (reproduce the crash once, then re-zip this folder)"
    } catch { $summary += "LocalDumps enable FAILED (run elevated): $_" }
}

# 8 ── Summary + zip ------------------------------------------------------------
Save '_SUMMARY.txt' ($summary -join "`r`n")
Write-Host "`r`n===== SUMMARY =====" -ForegroundColor Cyan
$summary | ForEach-Object { Write-Host $_ }
try {
    $zip = "$out.zip"
    Compress-Archive -Path "$out\*" -DestinationPath $zip -Force
    Write-Host "`r`nEvidence written to:`r`n  $out`r`n  $zip" -ForegroundColor Green
} catch { Write-Host "Zip failed: $_" }

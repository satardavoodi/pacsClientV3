# Build an ISO from a folder via IMAPI2FS — repro tool for the CD-viewer
# "Failed to start embedded python interpreter" report (2026-06-06).
# -Mode 1 = ISO9660 only (what CD burns used) · 3 = ISO9660+Joliet (fix candidate)
param(
    [int]$Mode = 1,
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Out,
    [string]$Label = 'DICOM_IMAGES'
)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices.ComTypes;
public static class IsoWriter {
    public static void Write(object comStream, string path, long totalBytes) {
        IStream stream = (IStream)comStream;
        using (FileStream fs = new FileStream(path, FileMode.Create, FileAccess.Write)) {
            byte[] buffer = new byte[1024 * 1024];
            IntPtr pRead = System.Runtime.InteropServices.Marshal.AllocHGlobal(8);
            try {
                long remaining = totalBytes;
                while (remaining > 0) {
                    int chunk = (int)Math.Min(buffer.Length, remaining);
                    stream.Read(buffer, chunk, pRead);
                    int read = System.Runtime.InteropServices.Marshal.ReadInt32(pRead);
                    if (read <= 0) { break; }
                    fs.Write(buffer, 0, read);
                    remaining -= read;
                }
            } finally {
                System.Runtime.InteropServices.Marshal.FreeHGlobal(pRead);
            }
        }
    }
}
'@

$image = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
$image.ChooseImageDefaultsForMediaType(2) | Out-Null   # CD-R geometry
try {
    $image.FileSystemsToCreate = $Mode
} catch {
    Write-Host "FileSystemsToCreate=$Mode REJECTED: $($_.Exception.Message)"
    exit 2
}
$image.VolumeName = $Label

Write-Host "[image] AddTree('$Source') FileSystemsToCreate=$Mode"
try {
    $image.Root.AddTree((Resolve-Path $Source).Path, $false)
} catch {
    Write-Host "ADDTREE FAILED: $($_.Exception.Message)"
    exit 3
}

$result = $image.CreateResultImage()
$bytes = [long]$result.TotalBlocks * [long]$result.BlockSize
[IsoWriter]::Write($result.ImageStream, (Join-Path (Get-Location) $Out), $bytes)
Write-Host ("[iso] wrote {0} ({1:N1} MB)" -f $Out, ($bytes / 1MB))
exit 0

# Troubleshooting — AI-PACS Advanced Viewer

> Detailed diagnostic procedures for common issues with the custom 3D Slicer module.
>
> **Quick reference:** See also the troubleshooting table in [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#9-troubleshooting).

---

## Issue 1: Slicer Opens But Shows No Image

**Symptoms:**
- Slicer window appears with empty views
- No volume in the Data module tree
- Log shows `loadVolume() returned None` or `DICOMUtils.loadPatientByUID() failed`

**Root Cause:** C++ loadable modules did not load — usually the **intDir** issue.

**Diagnosis:**
```powershell
$exe = "...\NewMPR2Slicer\build\AIPacsAdvancedViewer.exe"
& $exe --no-splash --no-main-window --python-code "
import slicer
fm = slicer.app.moduleManager().factoryManager()
print(f'intDir=[{slicer.app.intDir}]')
print(f'REGISTERED={len(fm.registeredModuleNames())}')
print(f'LOADED={len(fm.loadedModuleNames())}')
slicer.app.quit()
"
```

**Expected:** `REGISTERED=49`, `LOADED=49`, `intDir=[]` (empty string)

**If LOADED < 49:**
1. Check that DLLs exist in BOTH locations:
   - `lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules/*.dll` (for intDir="")
   - `lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules/Release/*.dll` (for intDir="Release")
2. If DLLs only exist in `Release/`, run the assembly script again or manually copy:
   ```powershell
   $libDir = "...\build\lib\AIPacsAdvancedViewer-5.11"
   Copy-Item "$libDir\qt-loadable-modules\Release\*" "$libDir\qt-loadable-modules\" -Force
   Copy-Item "$libDir\cli-modules\Release\*" "$libDir\cli-modules\" -Force
   Copy-Item "$libDir\ITKFactories\Release\*" "$libDir\ITKFactories\" -Force
   ```

---

## Issue 2: "Specified Python Script Doesn't Exist"

**Symptoms:**
- Error message in log or console: `specified python script doesn't exist`
- Slicer opens but doesn't load any DICOM data

**Root Cause:** CTK launcher cannot handle spaces in `--python-script` path.

**Diagnosis:**
```powershell
# Check workspace path for spaces
Write-Output $PWD
# If path contains spaces (e.g., "C:\AI-Pacs codes\..."), this is the issue
```

**Fix (already applied in launch_slicer.py):**
The launcher copies `startup_script.py` to `%TEMP%\aipacs_slicer\startup_script.py` when the path contains spaces. If this is not working:

1. Verify the copy happens — check `%TEMP%\aipacs_slicer\` for the script
2. Manually test:
   ```powershell
   Copy-Item "...\startup_script.py" "$env:TEMP\aipacs_slicer\startup_script.py"
   $exe = "...\AIPacsAdvancedViewer.exe"
   & $exe --no-splash --python-script "$env:TEMP\aipacs_slicer\startup_script.py"
   ```
3. Alternative: Move the project to a path without spaces (e.g., `C:\AIPacs\`)

---

## Issue 3: No Console Output / Silent Failure

**Symptoms:**
- Slicer starts but you can't see any output from `startup_script.py`
- Log file is empty or missing

**Root Cause:** stdout was captured by `subprocess.PIPE` in the old code.

**Fix (already applied):**
`launch_slicer.py` now redirects stdout to a log file. Check:
```powershell
Get-Content "...\slicer_custom_app\logs\slicer_startup.log" -Tail 50
```

If the log directory doesn't exist:
```powershell
New-Item -ItemType Directory -Path "...\slicer_custom_app\logs" -Force
```

---

## Issue 4: Slicer Crashes Immediately

**Symptoms:**
- Process exits within 1-2 seconds
- No window appears at all
- Exit code is non-zero (often -1073741515 = 0xC0000135 = DLL not found)

**Diagnosis:**
```powershell
# Run from console to see error messages
$exe = "...\NewMPR2Slicer\build\AIPacsAdvancedViewer.exe"
& $exe --version 2>&1
echo "Exit code: $LASTEXITCODE"
```

**Common causes:**

| Exit Code | Meaning | Fix |
|---|---|---|
| 0xC0000135 | DLL not found | Check `deps/qt/`, `deps/vtk/` exist with all DLLs |
| 0xC000007B | Architecture mismatch | Ensure all DLLs are x64 (not x86) |
| Access denied | Permissions | Run as admin or check folder permissions |

**Verify critical DLLs exist:**
```powershell
$build = "...\NewMPR2Slicer\build"
@(
    "$build\AIPacsAdvancedViewer.exe",
    "$build\bin\Release\AIPacsAdvancedViewer.exe",
    "$build\deps\qt\Qt5Core.dll",
    "$build\deps\qt-plugins\platforms\qwindows.dll",
    "$build\python-install\bin\python312.dll"
) | ForEach-Object {
    if (Test-Path $_) { "OK: $_" } else { "MISSING: $_" }
}
```

---

## Issue 5: Black Window / No Rendering

**Symptoms:**
- Slicer window appears but all views are black
- May see OpenGL errors in console

**Root Cause:** GPU/OpenGL driver incompatibility.

**Fix options:**
1. **Update GPU drivers** — most reliable fix
2. **Force software rendering:**
   ```powershell
   $env:LIBGL_ALWAYS_SOFTWARE = "1"
   $env:QT_OPENGL = "software"
   $env:MESA_GL_VERSION_OVERRIDE = "3.3"
   & $exe --testing --no-splash --python-script "...\startup_script.py"
   ```
3. **Use ANGLE (DirectX backend):**
   ```powershell
   $env:QT_OPENGL = "angle"
   ```

---

## Issue 6: Module Loads But DICOM Import Fails

**Symptoms:**
- Modules loaded successfully (49/49)
- But `slicer.util.loadVolume()` or `DICOMUtils.loadPatientByUID()` returns None

**Diagnosis:**
1. Check the DICOM directory has `.dcm` files:
   ```powershell
   (Get-ChildItem "$env:NEWMPR2_DICOM_DIR" -Filter "*.dcm").Count
   ```
2. Check log for specific errors:
   ```powershell
   Get-Content "...\slicer_custom_app\logs\slicer_startup.log" | Select-String "ERROR|FAIL|Exception"
   ```
3. Test loading manually:
   ```powershell
   $env:NEWMPR2_DICOM_DIR = "C:\path\to\series"
   & $exe --no-splash --no-main-window --python-code "
   import slicer, os, glob
   dcm_dir = os.environ['NEWMPR2_DICOM_DIR']
   dcms = glob.glob(os.path.join(dcm_dir, '*.dcm'))
   print(f'Found {len(dcms)} DICOM files')
   if dcms:
       vol = slicer.util.loadVolume(dcms[0])
       if vol:
           print(f'Success: dims={vol.GetImageData().GetDimensions()}')
       else:
           print('FAILED: loadVolume returned None')
   slicer.app.quit()
   "
   ```

**Common causes:**
- DICOM directory doesn't exist or is empty
- Files don't have `.dcm` extension (some DICOM files lack extensions)
- Corrupted DICOM data
- DICOMScalarVolumePlugin not loaded (check module count)

---

## Issue 7: Wrong Executable Used

**Symptoms:**
- Process starts but no window appears (or crashes)
- Running the exe doesn't set up paths correctly

**Root Cause:** Running `bin/Release/AIPacsAdvancedViewer.exe` directly instead of the root launcher.

**Fix:** Always use the **root** `AIPacsAdvancedViewer.exe` (the CTK launcher), NOT `bin/Release/AIPacsAdvancedViewer.exe`.

```
✅ build/AIPacsAdvancedViewer.exe                    ← CTK launcher (correct)
❌ build/bin/Release/AIPacsAdvancedViewer.exe         ← Real app (no path setup)
```

The root exe reads `AIPacsAdvancedViewerLauncherSettings.ini` to set all DLL paths, Python paths, and environment variables before launching the real exe.

---

## Issue 8: BOM in Python Scripts

**Symptoms:**
- `SyntaxError: invalid non-printable character U+FEFF` when Slicer runs startup_script.py

**Root Cause:** File was saved with UTF-8 BOM (e.g., by PowerShell's `Set-Content -Encoding utf8`).

**Fix:**
```powershell
# Check for BOM
$bytes = [System.IO.File]::ReadAllBytes("...\startup_script.py")
if ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    Write-Output "BOM detected — removing"
    $content = [System.IO.File]::ReadAllText("...\startup_script.py")
    [System.IO.File]::WriteAllText("...\startup_script.py", $content, [System.Text.UTF8Encoding]::new($false))
}
```

**Prevention:** Always write Python files using Python's `open()` with `encoding='utf-8'`, NOT PowerShell's `Set-Content`.

---

## Issue 9: TCP Remote Command Not Working

**Symptoms:**
- A new Slicer process spawns every time instead of reusing the existing one
- Load command is not received by the running instance

**Diagnosis:**
```powershell
# Check if port is in use
netstat -ano | findstr "47891"

# Test connection manually
$tcpClient = New-Object System.Net.Sockets.TcpClient
try {
    $tcpClient.Connect("127.0.0.1", 47891)
    Write-Output "Connection OK"
    $tcpClient.Close()
} catch {
    Write-Output "Connection FAILED: $_"
}
```

**Common causes:**
- `startup_script.py` didn't reach the TCP listener setup (crashed earlier)
- Firewall blocking localhost connections
- Port already in use by another application

---

## Diagnostic Quick-Reference

```powershell
$build = "...\NewMPR2Slicer\build"
$exe   = "$build\AIPacsAdvancedViewer.exe"

# 1. Version
& $exe --version

# 2. Module count
& $exe --no-splash --no-main-window --python-code "import slicer; print(len(slicer.app.moduleManager().factoryManager().loadedModuleNames())); slicer.app.quit()"

# 3. intDir value
& $exe --no-splash --no-main-window --python-code "import slicer; print(repr(slicer.app.intDir)); slicer.app.quit()"

# 4. Critical file check
@("$build\AIPacsAdvancedViewer.exe","$build\bin\Release\AIPacsAdvancedViewer.exe","$build\deps\qt\Qt5Core.dll","$build\deps\qt-plugins\platforms\qwindows.dll","$build\python-install\bin\python312.dll") | ForEach-Object { if (Test-Path $_) {"OK: $_"} else {"MISSING: $_"} }

# 5. DLL count
(Get-ChildItem "$build\lib\AIPacsAdvancedViewer-5.11\qt-loadable-modules" -Filter "*.dll" -ErrorAction SilentlyContinue).Count

# 6. Startup log
if (Test-Path "...\slicer_custom_app\logs\slicer_startup.log") { Get-Content "...\slicer_custom_app\logs\slicer_startup.log" -Tail 30 }
```

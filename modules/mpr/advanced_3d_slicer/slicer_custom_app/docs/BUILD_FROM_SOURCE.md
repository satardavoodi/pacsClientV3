# Build From Source — AI-PACS Advanced Viewer (Custom 3D Slicer)

The definitive 2026-09-23 native runtime is **already built**. Both Client and
Eagle Eye Server reuse it for ordinary future AI-PACS builds. Read the
[baseline record](../../../../../docs/release-and-build/SLICER_NATIVE_BASELINE_2026-09-23.md)
and the canonical [`BUILD.md`](../../../../../BUILD.md) first. Do not run this
multi-hour source build just because the AI-PACS version changes. Use this guide
only when native C++/CMake/Qt resources change, the provenance gate fails, or
the verified native runtime cannot be restored.

> Build the custom 3D Slicer SuperBuild from scratch.
> Required whenever the C++ application, Qt resources, or other native UI inputs change.
> The stock 3D Slicer installation is not a substitute for this custom application.
>
> **Time:** 4–8 hours first build (8-core machine) | **Disk:** ~60 GB

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| **CMake** | ≥ 3.16.3 | Download from [cmake.org](https://cmake.org/download/) |
| **Visual Studio** | 2019 or 2022 | Need "Desktop development with C++" workload. MSVC v142 or v143 toolset. |
| **Qt** | 5.15.2 (msvc2019_64) | Include Qt WebEngine. Path: `C:\Qt\5.15.2\msvc2019_64` |
| **Git** | Any recent | Needed for FetchContent during CMake configure |
| **Python** | 3.12+ | System Python for running the assembly script |
| **Disk space** | ~60 GB | Full SuperBuild generates many intermediate artifacts |
| **RAM** | ≥ 16 GB recommended | Large parallel compilation |
| **VC143 app-local CRT** | VS 2022 BuildTools 14.44.35112 x64 | Required for the portable runtime; `assemble_slicer_runtime.py` checks official DLL hashes before replacing the Developer Run runtime. |

---

## Step 1: Configure and build the custom SuperBuild

Slicer rejects source and build paths containing spaces or excessively long
paths. Keep `C:\S\NB` as compiler scratch space, not an installer destination.
Copy the *current* repository custom-app source to a short path, excluding its
generated `build` runtime. Recopy it whenever native/UI sources change. Check
that `robocopy` exits with code 0-7 (8 or higher means failure).
The assembly guard later compares this exact CMake compiler-source copy with
the repository; it will reject a stale copy even if compilation succeeds.

```powershell
$repo = (Resolve-Path .).Path
$appSource = Join-Path $repo 'modules\mpr\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer'
New-Item -ItemType Directory -Path 'C:\S\app' -Force | Out-Null
robocopy $appSource 'C:\S\app' /E /XD build /R:1 /W:1
if ($LASTEXITCODE -ge 8) { throw 'Custom Slicer source copy failed' }
if ((git -C 'C:\S\src' rev-parse HEAD).Trim() -ne 'ae061acd0f40570dcc1332920a2f6e370f1bd69d') {
    throw 'Pinned Slicer source checkout is missing or wrong'
}

$cmake = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
& $cmake -S 'C:\S\app' -B 'C:\S\NB' -G 'Visual Studio 17 2022' -A x64 `
  '-Dslicersources_SOURCE_DIR:PATH=C:/S/src' `
  '-DQt5_DIR:PATH=C:/Qt/5.15.2/msvc2019_64/lib/cmake/Qt5' `
  '-DCMAKE_CONFIGURATION_TYPES:STRING=Release' `
  '-DBUILD_TESTING:BOOL=OFF' `
  '-DSlicer_BUILD_WIN32_CONSOLE:BOOL=ON' `
  '-DSlicer_BUILD_WIN32_CONSOLE_LAUNCHER:BOOL=OFF' `
  '-DSlicer_BUILD_APPLICATIONUPDATE_SUPPORT:BOOL=OFF' `
  '-DSlicer_BUILD_EXTENSIONMANAGER_SUPPORT:BOOL=OFF' `
  '-DSlicer_BUILD_DOCUMENTATION:BOOL=OFF' `
  '-DSlicer_BUILD_DIFFUSION_SUPPORT:BOOL=OFF' `
  '-DSlicer_BUILD_MULTIVOLUME_SUPPORT:BOOL=OFF' `
  '-DSlicer_BUILD_BRAINSTOOLS:BOOL=OFF' `
  '-DSlicer_BUILD_CompareVolumes:BOOL=OFF' `
  '-DSlicer_BUILD_LandmarkRegistration:BOOL=OFF' `
  '-DSlicer_BUILD_SurfaceToolbox:BOOL=OFF' `
  '-DSlicer_USE_SimpleITK:BOOL=OFF' `
  '-DSlicer_USE_QtTesting:BOOL=OFF'
if ($LASTEXITCODE -ne 0) { throw 'Custom Slicer configuration failed' }

& $cmake --build 'C:\S\NB' --config Release -- /m:6 /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw 'Custom Slicer build failed' }
```

**Notes:**
- The verified 2026-09-23 build uses the existing pinned Slicer Git checkout
  `C:\S\src` at commit `ae061acd0f40` and builds ~30 external projects
  (VTK, ITK, CTK, DCMTK, TBB, etc.) before Slicer itself.
- Subsequent builds are much faster (only changed targets rebuild).
- The source archive or Git checkout must resolve to the exact Slicer commit and
  SlicerCustomAppUtilities commit pinned in `NewMPR2Slicer/CMakeLists.txt`.
  A pinned source archive may avoid a slow full-history Git clone; it is still
  only compiler input, not an AI-PACS output artifact. If using an archive,
  pass its short, space-free extracted path as `-Dslicersources_SOURCE_DIR:PATH=...`
  and populate the pinned utilities source as required by CMake.
- Do not reuse an existing `CMakeCache.txt` with a different source path. Preserve
  the old compiler tree as evidence and configure a fresh `C:\S\NB` instead.
- The pinned Slicer source must remain a real Git checkout. A source archive can
  bootstrap inspection, but Slicer's final configure/package targets require
  repository date and revision metadata. Shallow-fetch and check out the exact
  pinned commit before building; verify `git rev-parse HEAD` equals the pin.

### Build Output Structure

After a successful build, `C:\S\NB` contains:

```
C:\S\NB\
├── Slicer-build/           ← Main Slicer application (bin/, lib/, share/)
├── python-install/          ← Embedded Python 3.12
├── VTK-build/               ← VTK libraries + Python bindings
├── ITK-build/               ← ITK libraries
├── CTK-build/               ← CTK + PythonQt libraries
├── DCMTK-build/             ← DICOM toolkit
├── tbb-install/             ← Intel TBB threading
├── teem-build/              ← Teem image I/O
├── OpenSSL-install/         ← SSL libraries
├── LibArchive-install/      ← Archive support
├── SlicerExecutionModel-build/ ← SEM + ModuleDescriptionParser
├── JsonCpp-build/           ← JSON library
└── ... (many more intermediate dirs)
```

---

## Step 2: Install Python Packages in Embedded Python

The embedded Python needs specific packages for our startup script. First verify
what the SuperBuild already installed; only add missing packages to this
embedded Python, never the workstation's `.venv` or `.venv_build`:

```powershell
$pip = "C:\S\NB\python-install\Scripts\pip.exe"
& $pip list
# Only if missing, match the last verified 3.6.7 assembled runtime:
& $pip install 'pydicom==3.0.1' 'numpy==2.3.4' 'scipy==1.16.3' `
  'Pillow==12.0.0' 'requests==2.32.5' 'dicomweb-client==0.60.1'
& $pip check
```

---

## Step 3: Assemble the Portable Runtime

Once the SuperBuild completes, verify the new inner executable exists and is
newer than the repository native UI source. Close all source-app Advanced Viewer
processes before replacing the Developer Run runtime: the assembly script
currently replaces that whole `build/` directory. Do not terminate clinical
sessions just to satisfy a build. Then run from the repository root:

```powershell
Test-Path 'C:\S\NB\Slicer-build\bin\Release\AIPacsAdvancedViewer.exe'
& .\.venv\Scripts\python.exe tools\slicer\assemble_slicer_runtime.py
```

If the source Viewer is still open, assemble first into a **fresh**, explicit
scratch directory with `--output C:\b\<new-slicer-staging-name>`. This leaves
the active Developer Run runtime untouched. Verify that staged runtime, then
promote it to the canonical `build/` location only after the human has closed
the Viewer; the canonical installer coordinator will not accept a staged-only
runtime because it enforces Developer Run parity. The scratch path is not an
installer destination.

This creates the portable runtime (roughly 0.8 GB; verify actual size) at:
```
modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build/
```

The script:
1. Copies bin/, lib/, share/ from `Slicer-build/`
2. Copies the embedded Python from `python-install/`
3. Copies external DLLs from each dependency's build dir
4. Copies Qt DLLs and plugins from Qt installation
5. Flattens `Release/` subdirectories (fixes intDir issue)
6. Generates `AIPacsAdvancedViewerLauncherSettings.ini`
7. Writes `aipacs-native-build.json`, binding the compiled executable to the
   current native source; later packaging fails closed if either changes.
8. Copies the ten compiler-matched VC143 CRT DLLs from the official BuildTools
   redistribution folder into `bin/Release` and verifies their pinned hashes.
   The default source is
   `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Redist\MSVC\14.44.35112\x64\Microsoft.VC143.CRT`.
   On a different authorized build machine, pass `--vc-redist-dir <folder>`;
   the hashes must still match `builder/slicer_runtime_payload.py`. Never
   substitute DLLs from System32 or silently use an older runtime.

Build input must then be snapshotted into a **fresh** immutable distribution
asset cache. Follow `BUILD.md` for the selected Client or Server role and the
single canonical installer coordinator. Never copy a stock Slicer executable
or an older `build/` runtime into the installer folders.

For the existing 3.6.7 source/binary baseline, this SuperBuild is already
complete. Ordinary later Client **and** Server builds use the corrected
`generated-files/distribution-assets-native-3.6.7-vc143-20260923/` cache and
do not rerun CMake or this assembler. Rebuild native Slicer only after a native
source/resource change or an unrecoverable provenance failure; a product
version bump or Python-side UI/startup change alone is not such a change.

---

## Step 4: Verify the Build

```powershell
$exe = "modules\mpr\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer\build\AIPacsAdvancedViewer.exe"

# Version check
& $exe --version

# Module count (should be 49)
& $exe --no-splash --no-main-window --python-code "import slicer; fm=slicer.app.moduleManager().factoryManager(); print(f'REGISTERED={len(fm.registeredModuleNames())}'); print(f'LOADED={len(fm.loadedModuleNames())}'); slicer.app.quit()"

# Volume loading test
$env:NEWMPR2_DICOM_DIR = "C:\path\to\test\dicom\series"
& $exe --no-splash --python-script "modules\mpr\advanced_3d_slicer\slicer_custom_app\startup_script.py"
```

---

## Customization Points

### Application Name & Branding

| What | Where |
|---|---|
| App name (`AIPacsAdvancedViewer`) | `NewMPR2Slicer/Applications/NewMPR2SlicerApp/qNewMPR2SlicerAppMainWindow.cxx` |
| Icon | `slicer_custom_app/branding/icons/AIPacsAdvancedViewer.ico` |
| Splash screen | `NewMPR2Slicer/Applications/NewMPR2SlicerApp/Resources/Images/SplashScreen.png` |
| QSS stylesheet | `slicer_custom_app/branding/NewMPR2Slicer.qss` |
| Color scheme | `slicer_custom_app/branding/colors.json` |

### Slicer Version

Pinned in `NewMPR2Slicer/CMakeLists.txt`:
```cmake
FetchContent_Populate(slicersources
    GIT_TAG ae061acd0f40570dcc1332920a2f6e370f1bd69d   ← change this
)
```

### Disabled Modules

Also in `CMakeLists.txt`:
```cmake
set(Slicer_QTLOADABLEMODULES_DISABLED  SceneViews SlicerWelcome ViewControllers)
set(Slicer_QTSCRIPTEDMODULES_DISABLED  DataProbe DMRIInstall Endoscopy ...)
```

### Custom Modules

Our two custom scripted modules:
```cmake
set(Slicer_EXTENSION_SOURCE_DIRS
    ${NewMPR2Slicer_SOURCE_DIR}/Modules/Scripted/Home
    ${NewMPR2Slicer_SOURCE_DIR}/Modules/Scripted/NewMPR2MPR
)
```

---

## Troubleshooting Build Issues

| Issue | Solution |
|---|---|
| CMake can't find Qt5 | Set `-DQt5_DIR=C:/Qt/5.15.2/msvc2019_64/lib/cmake/Qt5` |
| Link errors during build | Ensure you're using the matching VS toolset (v142 for VS2019) |
| FetchContent download fails | Check internet connection; Git must be on PATH |
| Full-history VTK clone stalls | Stop the build, shallow-fetch the exact commit pinned by `C:\S\src\SuperBuild\External_VTK.cmake` into a local Git checkout, verify `git rev-parse HEAD`, then reconfigure with `-DSlicer_VTK_GIT_REPOSITORY:STRING=<local-checkout>` and resume the same `C:\S\NB` build. For the pinned 3.6.7 source the VTK commit is `e21c90bd874fb15f1dc34986c238462b8aab4af8`; do not substitute a different VTK release. |
| ITK or CTK clone stalls | Use the same pinned-commit, verified local-checkout procedure and reconfigure the existing build with `-DSlicer_ITK_GIT_REPOSITORY:STRING=<local-ITK-checkout>` or `-DSlicer_CTK_GIT_REPOSITORY:STRING=<local-CTK-checkout>`. For this source the pins are ITK `ac65b49c34fcfa3c3422a66026c7fe2bbaa88902` and CTK `3811bcaf0d84e9b43777e6422b2330b84baf2e0b`. Verify the generated `*-gitclone.cmake` points to the local checkout before resuming. |
| Out of disk space | SuperBuild needs ~60 GB; use a short path like `C:\S\NB` |
| Build takes >12 hours | Use `/maxcpucount:N` matching your core count; ensure SSD |
| Python packages missing after assembly | Run pip install in the *embedded* Python, not system Python |

---

## Incremental Rebuilds

After modifying C++ source or CMake files:

```powershell
cd C:\S\NB
cmake --build . --config Release --target NewMPR2SlicerApp
```

After modifying only Python scripts (Home, NewMPR2MPR, startup_script):
- Native C++ recompilation is unnecessary, but packaging must still stage the
  current Python/UI sources and verify their hashes against Developer Run.
- Do not manually patch an existing installer or immutable asset cache.

After updating the Slicer tag:
- Full rebuild required (change GIT_TAG in CMakeLists.txt → reconfigure)

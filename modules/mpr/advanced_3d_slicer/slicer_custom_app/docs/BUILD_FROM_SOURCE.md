# Build From Source — AI-PACS Advanced Viewer (Custom 3D Slicer)

> Build the custom 3D Slicer SuperBuild from scratch.
> Only needed if you need to modify the C++ application or update the Slicer version.
>
> **Time:** 4–8 hours first build (8-core machine) | **Disk:** ~60 GB

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| **CMake** | ≥ 3.16.3 | Download from [cmake.org](https://cmake.org/download/) |
| **Visual Studio** | 2019 or 2022 | Need "Desktop development with C++" workload. MSVC v142 or v143 toolset. |
| **Qt** | 5.15.2 (msvc2019_64) | Install via Qt Online Installer. Path: `C:\Qt\5.15.2\msvc2019_64` |
| **Git** | Any recent | Needed for FetchContent during CMake configure |
| **Python** | 3.12+ | System Python for running the assembly script |
| **Disk space** | ~60 GB | Full SuperBuild generates many intermediate artifacts |
| **RAM** | ≥ 16 GB recommended | Large parallel compilation |

---

## Step 1: Configure and Build the SuperBuild

```powershell
# Create build directory (short path recommended)
mkdir C:\S\NB
cd C:\S\NB

# Configure with CMake
cmake ^
  -G "Visual Studio 16 2019" ^
  -A x64 ^
  -DQt5_DIR=C:/Qt/5.15.2/msvc2019_64/lib/cmake/Qt5 ^
  -DSlicer_BUILD_WIN32_CONSOLE=ON ^
  -DSlicer_BUILD_WIN32_CONSOLE_LAUNCHER=OFF ^
  -DSlicer_BUILD_APPLICATIONUPDATE_SUPPORT=OFF ^
  -DSlicer_BUILD_EXTENSIONMANAGER_SUPPORT=OFF ^
  -DSlicer_BUILD_DOCUMENTATION=OFF ^
  -DSlicer_BUILD_DIFFUSION_SUPPORT=OFF ^
  -DSlicer_BUILD_MULTIVOLUME_SUPPORT=OFF ^
  -DSlicer_BUILD_BRAINSTOOLS=OFF ^
  -DSlicer_BUILD_DataStore=OFF ^
  -DSlicer_BUILD_CompareVolumes=OFF ^
  -DSlicer_BUILD_LandmarkRegistration=OFF ^
  -DSlicer_BUILD_SurfaceToolbox=OFF ^
  -DSlicer_USE_SimpleITK=OFF ^
  -DSlicer_USE_QtTesting=OFF ^
  "path\to\modules\mpr\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer"

# Build (Release config)
cmake --build . --config Release -- /maxcpucount:8
```

**Notes:**
- The first build downloads Slicer source (commit `ae061acd0f40`) via FetchContent, 
  then builds ~30 external projects (VTK, ITK, CTK, DCMTK, TBB, etc.) before building Slicer itself.
- Subsequent builds are much faster (only changed targets rebuild).
- The generator can be `"Visual Studio 17 2022"` if using VS 2022.

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

The embedded Python needs specific packages for our startup script:

```powershell
$pip = "C:\S\NB\python-install\Scripts\pip.exe"
& $pip install pydicom numpy scipy Pillow requests dicomweb-client
```

---

## Step 3: Assemble the Portable Runtime

Once the SuperBuild completes, run the assembly script to extract only runtime files:

```powershell
cd "c:\AI-Pacs codes\aipacs-pydicom2d"
python tools/slicer/assemble_slicer_runtime.py
```

This creates the portable 842 MB runtime at:
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
- No rebuild needed — just copy the updated .py files
- For our startup script, it's read from the workspace directly

After updating the Slicer tag:
- Full rebuild required (change GIT_TAG in CMakeLists.txt → reconfigure)

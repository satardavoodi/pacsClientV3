# Dependency Manifest — AI-PACS Advanced Viewer Runtime

> Complete inventory of the assembled runtime at `NewMPR2Slicer/build/`.
>
> Generated: 2026-03-11 | Runtime size: ~842 MB | File count: ~11,259

---

## Build Directory Structure

```
build/                                          ~842 MB total
├── AIPacsAdvancedViewer.exe                    7.8 MB  (CTK launcher)
├── AIPacsAdvancedViewerLauncherSettings.ini    3 KB    (all paths <APPLAUNCHER_DIR> relative)
├── Logo.png, LogoFull.png, SplashScreen.png    Branding images
│
├── bin/                                        61.6 MB
│   ├── Release/                                28 DLLs + 57 EXEs (core Slicer)
│   ├── Python/                                 Slicer Python bindings
│   ├── iconengines/                            Qt icon engine plugins
│   └── styles/                                 Qt style plugins
│
├── lib/AIPacsAdvancedViewer-5.11/              47.4 MB
│   ├── qt-loadable-modules/                    83 DLLs (C++ loadable modules)
│   │   └── Release/                            Same 83 DLLs (redundant, for intDir compat)
│   │   └── Python/                             Python bindings for loadable modules
│   ├── qt-scripted-modules/                    20 Python modules
│   ├── cli-modules/                            8 files (CLI module executables)
│   │   └── Release/                            Same files (redundant)
│   ├── ITKFactories/                           1 DLL (MRMLIDIOPlugin.dll)
│   │   └── Release/                            Same DLL (redundant)
│   └── orientation_logger.py                   Logging helper
│
├── deps/                                       407.9 MB
│   ├── qt/                                     155.1 MB (20 Qt5 DLLs + extras)
│   ├── vtk/                                    106.8 MB (VTK DLLs)
│   ├── vtk-site-packages/                      42.4 MB (VTK Python bindings)
│   ├── dcmtk/                                  28.8 MB (DICOM toolkit)
│   ├── qt-plugins/                             25.8 MB (platforms, imageformats, etc.)
│   ├── itk/                                    22.3 MB (ITK DLLs)
│   ├── pythonqt/                               10.8 MB (PythonQt bridge)
│   ├── ctk/                                    5.6 MB (CTK + designer plugins)
│   ├── openssl/                                3.7 MB (SSL DLLs)
│   ├── teem/                                   3.0 MB (Teem image I/O)
│   ├── tbb/                                    2.1 MB (Intel TBB threading)
│   ├── libarchive/                             0.9 MB
│   ├── sem/                                    0.3 MB (Slicer Execution Model)
│   ├── jsoncpp/                                0.2 MB
│   └── ctk-python/                             <0.1 MB (CTK Python bindings)
│
├── python-install/                             313.5 MB
│   ├── Lib/site-packages/                      See Python packages below
│   ├── Lib/                                    Standard library
│   ├── bin/                                    python312.dll, python.exe
│   ├── include/                                Python headers
│   ├── libs/                                   Import libraries
│   ├── Scripts/                                pip, etc.
│   └── share/                                  Python share data
│
└── share/AIPacsAdvancedViewer-5.11/            3.6 MB
    ├── Slicer.crt                              SSL certificate bundle
    ├── ColorFiles/                             Color lookup tables
    └── ...                                     Other Slicer shared data
```

---

## Qt5 DLLs (deps/qt/)

```
Qt5Concurrent.dll       Qt5PrintSupport.dll     Qt5WebEngineWidgets.dll
Qt5Core.dll             Qt5Qml.dll              Qt5Widgets.dll
Qt5Gui.dll              Qt5QmlModels.dll        Qt5Xml.dll
Qt5Multimedia.dll       Qt5Quick.dll            d3dcompiler_47.dll
Qt5MultimediaWidgets.dll Qt5QuickWidgets.dll    libEGL.dll
Qt5Network.dll          Qt5Sql.dll              libGLESv2.dll
Qt5OpenGL.dll           Qt5Svg.dll              opengl32sw.dll
Qt5Positioning.dll      Qt5WebChannel.dll       QtWebEngineProcess.exe
                        Qt5WebEngine.dll
                        Qt5WebEngineCore.dll
```

## Qt5 Plugins (deps/qt-plugins/)

```
platforms/qwindows.dll          ← ESSENTIAL: without this, no window appears
imageformats/                   JPEG, PNG, SVG, etc.
iconengines/                    SVG icon engine
styles/                         Windows Vista style
sqldrivers/                     SQLite driver (for settings)
```

---

## Slicer C++ Loadable Modules (49 total)

These are in `lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules/`:

### Core Infrastructure
- SubjectHierarchy, Data, Colors, Units, Tables, Texts, Plots
- Terminologies, EventBroker, Cameras

### DICOM
- DICOM, DICOMScalarVolumePlugin, DICOMPatcher
- DICOMEnhancedUSVolumePlugin, DICOMGeAbusPlugin
- DICOMImageSequencePlugin, DICOMSlicerDataBundlePlugin, DICOMVolumeSequencePlugin

### Visualization
- Volumes, VolumeRendering, Models, Annotations, Markups
- Segmentations, SegmentEditor, SegmentStatistics

### MPR / Reformat
- Reformat, GeneralizedReformat, CropVolume, CropVolumeSequence

### Our Custom Modules
- **NewMPR2MPR** — Primary MPR viewer module
- **Home** — App orchestration module

### Other
- Transforms, Sequences, ScreenCapture, WebServer
- SelfTests, LineProfile, ImportItkSnapLabel
- (Test modules: CLI4Test, PyCLI4Test, AddManyMarkupsFiducialTest, etc.)

---

## Python Packages in Embedded Python

| Package | Version | Purpose |
|---|---|---|
| numpy | 2.3.4 | Array operations |
| scipy | 1.16.3 | Scientific computing |
| pydicom | 3.0.1 | DICOM file reading |
| Pillow (PIL) | 12.0.0 | Image processing |
| requests | 2.32.5 | HTTP client |
| dicomweb-client | 0.60.1 | DICOMweb protocol support |
| vtk | 9.5.2 | VTK Python bindings (in deps/vtk-site-packages/) |
| certifi | 2025.11.12 | SSL certificates |
| urllib3 | 2.5.0 | HTTP library |
| idna | 3.11 | Internationalized domain names |
| charset-normalizer | 3.4.4 | Character encoding detection |
| pyparsing | 3.2.5 | Parsing library |
| packaging | 25.0 | Version parsing |
| setuptools | 80.9.0 | Package management |
| pip | 25.3 | Package installer |
| wheel | 0.45.1 | Wheel format |
| retrying | 1.4.2 | Retry decorator |
| six | 1.17.0 | Python 2/3 compat |

---

## Environment Variables Set by Launcher INI

| Variable | Value |
|---|---|
| `SLICER_HOME` | `<APPLAUNCHER_DIR>` (= build/ root) |
| `ITK_AUTOLOAD_PATH` | `<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/ITKFactories/Release` |
| `PYTHONHOME` | `<APPLAUNCHER_DIR>/python-install` |
| `PYTHONNOUSERSITE` | `1` |
| `PIP_REQUIRE_VIRTUALENV` | `0` |
| `PIP_DISABLE_PIP_VERSION_CHECK` | `1` |
| `SSL_CERT_FILE` | `<APPLAUNCHER_DIR>/share/AIPacsAdvancedViewer-5.11/Slicer.crt` |

---

## Critical Path Dependencies

These files are absolutely essential — if any are missing, the app will not function:

1. **`AIPacsAdvancedViewer.exe`** (root) — CTK launcher
2. **`AIPacsAdvancedViewerLauncherSettings.ini`** — paths config
3. **`bin/Release/AIPacsAdvancedViewer.exe`** — real application binary
4. **`deps/qt/Qt5Core.dll`** — Qt core (and all other Qt5*.dll)
5. **`deps/qt-plugins/platforms/qwindows.dll`** — Qt platform plugin
6. **`lib/.../qt-loadable-modules/*.dll`** — flattened module DLLs (NOT just in Release/)
7. **`python-install/bin/python312.dll`** — Python runtime
8. **`deps/vtk/*.dll`** — VTK rendering
9. **`deps/ctk/*.dll`** — CTK framework

---

## Source Build Dependencies (for building from source only)

| Tool | Version | Download |
|---|---|---|
| CMake | ≥ 3.16.3 | cmake.org |
| Visual Studio | 2019 or 2022 (MSVC v142+) | visualstudio.microsoft.com |
| Qt | 5.15.2 (msvc2019_64) | qt.io/download |
| Git | any recent | git-scm.com |
| Python | 3.12+ | python.org |
| ~60 GB disk space | — | For full SuperBuild |
| ~4–8 hours build time | — | First build on 8-core machine |

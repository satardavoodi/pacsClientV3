# Nuitka Build System — Completion Report

Date: 2026-07-02

## Summary

The Nuitka build was incomplete because its **specification file was an empty
stub** (`builder nuitka/AIPacs_nuitka.spec.py` contained only `LTO = "auto"`).
The driver `build_nuitka.py` reads all inclusion data (data dirs, hidden imports,
plugins, codecs, excludes) from that spec via `getattr(..., default)`, so with an
empty spec it produced a broken executable (no bundled assets, missing modules,
no compressed-DICOM codec support). The staged release pipeline also failed at
stage 6 on a stale intermediate-build collision.

This work completes the spec, hardens the driver, fixes the staged-pipeline bug,
adds reproducible build tooling + logging, and documents the workflow — without
touching the working PyInstaller (Python) build.

## Root cause

- `build_nuitka.py` (a complete driver) + `AIPacs_nuitka.spec.py` (empty) →
  functional plumbing, no configuration. The "incompleteness" was the missing
  spec, not the driver.
- The PyInstaller spec `AIPacs.spec` is the authoritative inclusion list; the
  Nuitka spec had never been derived from it.

## Deliverables

### 1. Completed / fixed files
| File | Change |
|---|---|
| `builder nuitka/AIPacs_nuitka.spec.py` | **Rewritten** from a 4-line stub into a complete spec mirroring `AIPacs.spec` (data dirs, ~90 hidden imports, packages, plugins, codec metadata, excludes, compiler knobs, reproducibility flags). |
| `build_nuitka.py` (root driver) | Added: default spec path resolution; `--include-package-data` for extra packages; `--include-distribution-metadata` for codecs; `--onefile` override; build-process env pinning; **file logging** to `output/logs/`. |
| `builder nuitka/build_nuitka_release.py` | Fixed the stage-6 crash: `run_nuitka_stage` now removes stale `*.build` intermediate trees before compiling (prevents `AssertionError: ...module.PIL.c`). |
| `builder nuitka/build_nuitka_simple.cmd` | **New** one-click reproducible build (isolated `.venv_nuitka`, installs deps, runs driver, logs). |
| `builder nuitka/README_NUITKA_BUILD.md` | **New** full workflow documentation. |

### 2. Missing dependencies / imports added to the Nuitka config
- **Compressed-DICOM codec metadata** (the critical fix): `pylibjpeg`,
  `pylibjpeg-libjpeg`, `pylibjpeg-openjpeg`, `pylibjpeg-rle` via
  `--include-distribution-metadata` — without this, JPEG 2000 / JPEG-lossless /
  RLE images silently fail to decode in the frozen app.
- Codec plugin modules: `libjpeg`, `openjpeg`, `rle`, all `pydicom` pixel-data
  handlers (pylibjpeg/pillow/rle/gdcm).
- PySide6 modules incl. `QtWebEngineCore/Widgets`, `QtSvg`, `QtOpenGL(Widgets)`,
  `shiboken6`.
- VTK: `vtkmodules` (whole package) + util submodules + QVTKRenderWindowInteractor.
- Medical/numeric: `numpy` (core/_core internals), `pydicom`, `pynetdicom`,
  `SimpleITK`, `pandas`.
- MPR/3D dynamic packages: `modules.mpr.zeta_mpr`, `modules.mpr.orthogonal`,
  `PacsClient.pacs.workstation_ui.settings_ui` (lazy import).
- UI/other lazy imports: `qtawesome`, `Custom_Widgets`, `qasync`, `cv2`, `pypdf`,
  `pptx`, `pytesseract`, `grpc`, google API libs, `sounddevice`, `soundfile`,
  `speech_recognition`, `openai`, `dotenv`, `natsort`.
- Excludes (anti-bloat / crash-avoid): `PyQt5/6`, `tkinter`, `torch`,
  `tensorflow`, `transformers`, `IPython`, `jupyter`, `pytest`, `fitz`/`pymupdf`.

### 3. Runtime assets included
- Folders: `PacsClient`, `Fonts`, `Qss` (icons+images), `config`, `json-styles`,
  `generated-files`, EchoMind Secretary `catalog/` + `prompts/`.
- Files: `modules/EchoMind/secretary/module_map.yaml`, `servers.json`,
  `browser_bookmarks.json` (auto-skipped if absent).
- DLLs: software-OpenGL fallback `graphics_runtime\opengl32sw.dll`, `osmesa.dll`,
  `pipe_swrast.dll` (copied next to the exe).
- Package data: PySide6, qtawesome fonts, Custom_Widgets theme assets.
- App icon: `Qss/images/favicon.ico`.

### 4. Comparison with the PyInstaller (Python) build
| Aspect | PyInstaller (`AIPacs.spec`) | Nuitka (this work) |
|---|---|---|
| Data dirs | `datas` list | `DATA_DIRS` / `OPTIONAL_DATA` — mirrored |
| Hidden imports | `hiddenimports` | `FORCED_IMPORTS` + `INCLUDE_PACKAGES` — mirrored |
| Codec metadata | `copy_metadata(...)` | `--include-distribution-metadata` — mirrored |
| Excludes | `excludes` | `EXCLUDES`/`NOFOLLOW_IMPORTS` — mirrored |
| numpy thread pin | `runtime_hook_numpy.py` | build-process env + doc note (runtime is optional/perf) |
| VTK preload | `runtime_hook_vtk.py` | covered by forced util-submodule imports |
| Reverse-engineering | bytecode extractable | compiled to native C — much harder |
| Output | `builder/output/dist/AIPacs/` | `builder nuitka/output/dist/AIPacs_nuitka/main.dist/` |

### 5. Testing results
- **Static verification (sandbox):** `build_nuitka.py` and
  `build_nuitka_release.py` compile cleanly (`py_compile`). The spec is
  declarative Python confirmed complete via the authoritative file read; the
  driver `load_spec()`s it at build time so any error surfaces immediately.
- **Real build/runtime:** must run on the Windows build machine (the sandbox has
  no GUI/VTK/OpenGL). Follow README §8 — the key Nuitka-specific check is opening
  a **compressed DICOM** to confirm the codec-metadata fix.

### 6. Known limitations
- Not yet run end-to-end on Windows in this session — first real compile + the
  §8 GUI/codec checklist still need to be executed on the build machine.
- Nuitka 4.0.8 first build is slow (10–30 min) and memory-heavy (LTO). Use
  incremental builds during iteration; `--clean` only for releases.
- numpy BLAS thread pins are applied to the *build* process; if wanted at
  *runtime* they must be set in the first lines of `main.py` (perf/stability
  only, not correctness).
- The staged release pipeline's optional plugin packaging (Advanced MPR runtime,
  lite viewer) has its own prerequisites (see its stage-8 requirements); the
  simple monolithic build does not use them.

### 7. Documentation
- `builder nuitka/README_NUITKA_BUILD.md` — full workflow, spec reference,
  critical inclusions, reproducibility, troubleshooting, test checklist.

## Safety
No change touches the PyInstaller build (`AIPacs.spec`, `builder/`, `build.py`),
the app source, or the dev `.venv`. The Nuitka path is additive.

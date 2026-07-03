# AIPacs — Nuitka Build Workflow

This document describes the **Nuitka** build pipeline for AIPacs. Nuitka compiles
the Python source into C/C++ and then into a native binary, which is
significantly harder to reverse-engineer than the PyInstaller build (whose `.pyc`
bytecode can be extracted and decompiled). It is provided as an **additional,
production build option** and does **not** replace or modify the existing
PyInstaller (Python) build in `builder/`.

> **Golden rule:** the PyInstaller spec `AIPacs.spec` (project root) is the
> *source of truth* for what must ship (data dirs, hidden imports, codecs,
> excludes). The Nuitka spec mirrors it. When you change one, change the other.

---

## 1. Two Nuitka entry points (don't confuse them)

| Entry point | Purpose | Config it reads |
|---|---|---|
| `build_nuitka.py` (root) + `builder nuitka/AIPacs_nuitka.spec.py` | **Simple / monolithic** standalone build — everything in one `dist` tree. Fast, reproducible, hard to reverse-engineer. **Start here.** | The full spec |
| `builder nuitka/build_nuitka_release.py` | **Staged / checkpointed release** pipeline — Engine + external plugin packages + Inno Setup installer, resumable stage-by-stage. | Only `LTO`, `ICON`, `ENTRY_POINT`, `OPTIONAL_DATA`, `NOFOLLOW_IMPORTS` from the spec; the rest of its inclusion logic is internal. |

Both are independent of the PyInstaller build.

---

## 2. Quick start (simple build)

### Option A — one-click, reproducible (recommended)

```bat
REM From the project root:
"builder nuitka\build_nuitka_simple.cmd" --clean
```

This script:
1. Creates an isolated build venv `.venv_nuitka` (first run only).
2. Installs `requirements-nuitka.txt` into it.
3. Runs `build_nuitka.py` with any args you pass through.
4. Writes a timestamped log to `builder nuitka\output\logs\`.

### Option B — manual

```bat
python -m pip install -r requirements-nuitka.txt
python build_nuitka.py --clean
```

### Useful flags

```bat
python build_nuitka.py               REM incremental build
python build_nuitka.py --clean       REM remove old dist/build first
python build_nuitka.py --onefile     REM single .exe (slower startup)
python build_nuitka.py --dry-run     REM print the Nuitka command, build nothing
python build_nuitka.py --spec <path> REM use a custom spec
```

**Output:** `builder nuitka\output\dist\AIPacs_nuitka\main.dist\AIPacs.exe`
(plus the bundled `PacsClient\`, `Qss\`, `Fonts\`, `config\`, DLLs, etc.).

---

## 3. What the spec controls (`AIPacs_nuitka.spec.py`)

| Key | Meaning |
|---|---|
| `ENTRY_POINT`, `APP_NAME`, `OUTPUT_DIR`, `ICON` | Build identity |
| `STANDALONE` / `ONEFILE` / `WINDOWS_CONSOLE` | Output mode |
| `PLUGINS` | Nuitka plugins (`pyside6` is mandatory) |
| `INCLUDE_PACKAGES` | Whole packages + submodules (`--include-package`) |
| `FORCED_IMPORTS` | Individual hidden imports (`--include-module`) |
| `PACKAGE_DATA` | Non-python package data (qtawesome fonts, Custom_Widgets) |
| `DIST_METADATA` | **Codec metadata** — pylibjpeg decoder discovery (see §4) |
| `EXCLUDES` / `NOFOLLOW_IMPORTS` | Packages to drop (`--nofollow-import-to`) |
| `DATA_DIRS` / `OPTIONAL_DATA` | Bundled data folders/files (auto-skipped if absent) |
| `RUNTIME_ENV` | BLAS thread pins applied to the build process |
| `LTO`, `C_COMPILER`, `JOBS`, `EXTRA_FLAGS` | Compiler / performance knobs |

---

## 4. Critical inclusions (learned from the PyInstaller build)

These are the items that "work in dev but break in the frozen app" if omitted:

- **Compressed DICOM codecs.** `pylibjpeg` finds its `libjpeg` / `openjpeg` /
  `rle` decoder plugins through each distribution's `.dist-info` metadata. The
  spec ships `DIST_METADATA` → `--include-distribution-metadata=...`. Without it,
  JPEG 2000 / JPEG-lossless / RLE images decode fine in dev but silently fail in
  the build. (Equivalent to `copy_metadata()` in `AIPacs.spec`.)
- **EchoMind Secretary data.** `catalog/`, `prompts/`, `module_map.yaml` are read
  from disk; missing them makes every LLM-fallback command fail with
  "could not map this command".
- **qtawesome fonts** → blank toolbar icons if missing.
- **Software-OpenGL DLLs** (`graphics_runtime\*.dll`) → VTK/Qt fail to render on
  machines without a GPU OpenGL driver.
- **VTK util submodules** — bundled via `FORCED_IMPORTS` (replaces the
  PyInstaller `runtime_hook_vtk.py` pre-import).

---

## 5. Reproducibility

- Uses an **isolated `.venv_nuitka`** (Option A) so the build doesn't depend on
  your dev environment.
- `EXTRA_FLAGS` sets `--python-flag=static_hashes` (deterministic hashing),
  `--python-flag=safe_path` (no CWD imports in the frozen app),
  `--assume-yes-for-downloads` (never blocks on a prompt), and
  `--remove-output` (drops the intermediate `.build` tree on success).
- Version comes from `pyproject.toml` (same source as the PyInstaller build).

---

## 6. Logging & troubleshooting

- Every build tees full output to
  `builder nuitka\output\logs\nuitka_build_<timestamp>.log`.
- A Nuitka XML compilation report is written to
  `builder nuitka\output\reports\nuitka_build_report.xml`.
- **"AssertionError: ...main.build\\module.XXX.c"** — a stale intermediate build
  tree. Run with `--clean`. (The staged pipeline now auto-removes stale `.build`
  dirs before each stage.)
- **Missing module at runtime** — add it to `FORCED_IMPORTS` (single module) or
  `INCLUDE_PACKAGES` (whole package) in the spec, mirroring `AIPacs.spec`.
- **Blank icons / missing theme** — check `PACKAGE_DATA` and `DATA_DIRS`.

---

## 7. Staged release pipeline (advanced)

```bat
python "builder nuitka\build_nuitka_release.py"            REM full run
python "builder nuitka\build_nuitka_release.py" --resume   REM resume after a failure
python "builder nuitka\build_nuitka_release.py" --stage 6  REM rerun one stage
python "builder nuitka\build_nuitka_release.py" --smoke-test
python "builder nuitka\build_nuitka_release.py" --clean-all
```

Stages: 0 preflight → 1 minimal core → 2 Qt shell → 3 core packages →
4 DICOM → 5 heavy native (VTK/SimpleITK) → 6 full core → 7 runtime resources →
8 plugin staging → 9 installer manifests → 10 Inno Setup installer. State is
checkpointed in `builder nuitka\output\build_state.json`.

---

## 8. Testing the produced executable (must run on Windows)

The sandbox verify-lane cannot exercise a real GUI/VTK build. On the Windows
build machine:

1. Launch `...\AIPacs_nuitka\main.dist\AIPacs.exe` → login screen appears (no
   console window, no missing-DLL popups).
2. Select **MRI**, pick a recent date, click several patients → thumbnails load.
3. Open a study; scroll a stack; confirm images render (proves VTK + OpenGL).
4. Open a **compressed** DICOM (JPEG 2000 / lossless) → renders (proves codec
   metadata). This is the single most important Nuitka-specific check.
5. Open **MPR** and **Dental Curve MPR** → render (proves the dynamic module
   packages compiled in).
6. Confirm toolbar icons are present (proves qtawesome fonts).
7. Confirm the theme/QSS applied (proves `generated-files` + `Qss`).

Compare the `dist` tree against the PyInstaller output
(`builder\output\dist\AIPacs\`) — the `Qss`, `Fonts`, `config`, `PacsClient`
folders should be present in both.

---

## 9. Do NOT

- Modify or rely on the PyInstaller build being changed — it stays the primary,
  regularly-used pipeline.
- Let a Nuitka data/import change drift from `AIPacs.spec`. Keep them in sync.

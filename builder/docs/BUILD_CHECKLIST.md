# Build Checklist

## Pre-Build Checks

- Activate or create `.venv_build`
- Install `builder/requirements/build_requirements.txt`
- Install project runtime dependencies from `requirements-core.txt`

### Dependency Audit (run before each release)

**cv2 / OpenCV check**
```powershell
.venv_build\Scripts\python.exe -c "import cv2; print('cv2 OK:', cv2.__version__)"
```
`opencv-python-headless` must be installed in `.venv_build` and listed in
`builder/inventory/imports_summary.json` under `suggested_hiddenimports`.
Without it the FAST viewer falls back to VTK and shows the wrong "Advanced" badge.

**printing.data check — main codebase**
```powershell
.venv_build\Scripts\python.exe -c "from modules.printing.data import get_series_for_study; print('main codebase data: OK')"
```

**printing.data check — plugin package (CRITICAL — must pass separately)**
```powershell
.venv_build\Scripts\python.exe -c "
import sys
sys.path.insert(0, 'builder/plugin package/packages/printing/payload/python')
from modules.printing.data import get_series_for_study
from modules.printing.data.filming_manager import FilmingDataManager
from modules.printing.data.dicom_enrichment import get_series_with_enrichment
print('Plugin data package: OK')
"
```
See **Dual-Location Rule** below — the plugin package is the production runtime
override and must have an identical `data/` package.

---

## Dual-Location Rule for Python Subpackages

> **Any Python subpackage added to `modules/<name>/` MUST also be added to
> `builder/plugin package/packages/<name>/payload/python/modules/<name>/`.**

### Why this matters

When a module is enabled on an installed machine, the installer registers its
`payload/python/` path in `sys.path` BEFORE the PyInstaller `engine/` bundle.
This means the **plugin package's** `modules.<name>` overrides the bundled one.
If `data/` exists only in the bundle but not in the plugin package,
`from modules.printing.data import ...` raises `ModuleNotFoundError` at runtime
even though the build log shows no errors.

### Affected locations (Printing module example)
| Location | Purpose |
|----------|---------|
| `modules/printing/data/` | Dev mode + PyInstaller bundle (fallback when plugin NOT enabled) |
| `builder/plugin package/packages/printing/payload/python/modules/printing/data/` | **Production runtime** when Printing plugin IS enabled |

### Checklist for new subpackages
- [ ] Create `modules/<name>/<subpackage>/` with `__init__.py` + source files
- [ ] Create identical copy at `builder/plugin package/packages/<name>/payload/python/modules/<name>/<subpackage>/`
- [ ] Check `.gitignore` — ensure `!modules/*/data/` (or similar) is present so
      Python packages inside data directories are NOT ignored by git
- [ ] Add any new top-level imports to `suggested_hiddenimports` in
      `builder/inventory/imports_summary.json`
- [ ] Run both pre-build checks above

---

## Build

- Assemble the optional Advanced MPR runtime if that payload should ship:
  `python tools/slicer/assemble_slicer_runtime.py`
- Run `python build.py`

## Post-Build Verification

- Verify `builder/output/stage/core/AIPacs.exe` exists
- Verify `builder/output/stage/manifest/release_manifest.json` marks optional payloads correctly
- If `ISCC.exe` is available, verify installers:
  - `builder/output/installer/ai-pacs installer.exe`
  - `builder/output/installer/ai-pacs installer v<version>.exe`
- Verify installer metadata files:
  - `builder/output/installer/INSTALL_NOTES.txt`
  - `builder/output/installer/SHA256.txt`
- Run installer validation using `builder/docs/INSTALLER_QA_CHECKLIST.md`

### Build log scan (no real errors expected)
```powershell
Select-String -Path "builder\output\build_v*.log" -Pattern "ModuleNotFoundError|No module named|Failed to collect" | ForEach-Object { $_.Line.Trim() } | Sort-Object -Unique
```
Expected: only harmless `charset_normalizer.md__mypyc` warning (known PyInstaller
quirk). Any `modules.printing.*` or `cv2` lines are real errors.

### Inno Setup exit code 1 — known false alarm
Inno Setup emits a `PrivilegesRequired` warning when the script uses per-user
paths (`localappdata`, `userappdata`) while `PrivilegesRequired=admin`. This is
expected — the installer is intentionally admin-required. The resulting EXE is
valid; the exit code 1 does not indicate a broken installer.

### PyInstaller warnings file
The full warnings file is at `builder/output/build/appA_workstation/warn-appA_workstation.txt`.
All `missing module named numpy._core.*`, `pandas.*`, `comtypes.*`, `anyio.*` etc. are
**known false positives** from third-party optional deps. Actionable lines are those
referencing `modules.*` or `PacsClient.*` without `optional` or `conditional` labels.

### Production test file exclusion
`PacsClient.pacs.patient_tab.utils.test` is excluded from the bundle via the
`excludes` list in `builder/spec/appA_workstation.spec`. Without this exclusion
it triggers spurious `missing module named image_filters` / `utils` warnings since
it imports dev-only helpers as top-level imports.

Note: PyInstaller may still report `excluded module named PacsClient.pacs.patient_tab.utils.test
- imported by main.py (top-level)` in the warnings file. This is a false positive from
`collect_submodules` static tracing, not a real `main.py` import. "excluded" status means
the spec rule worked correctly.

---

## Database Module (`database/`)

### Python package vs. runtime data directory

Two things named "database" exist in this project — do NOT confuse them:

| Path | What it is | Build treatment |
|------|-----------|----------------|
| `database/` (project root) | Python package — connection pool, schema, CRUD | **Must be bundled** as Python code |
| Runtime `database/` or `dicom.db` | SQLite data files created at runtime | **Must NOT be bundled** (section D of BUILD_DOCUMENT.md) |

### Coverage audit (verified v2.4.7)

The `database/` Python package is covered by **two mechanisms** in the spec:

1. **Explicit hiddenimports** (`extra=` list in spec):
   - `database`
   - `database.core`
   - `database.manager`

2. **`collect_submodules("database", filter=lambda name: True)`** — no filter applied,
   so ALL submodules are auto-discovered:
   - `database._pool`
   - `database.ai_reception_db`
   - `database.ai_sessions_db`
   - `database.dicom_db`
   - `database.download_progress_db`
   - `database.token_usage_db`
   - `database.migrations.migrate_report_status`

### Dependencies (all stdlib — no hiddenimports needed)
All `database/` modules import only Python standard library: `sqlite3`, `logging`,
`json`, `threading`, `hashlib`, `contextlib`, `ast`, `random`, `time`, `datetime`.
No third-party packages. Zero warnings in PyInstaller analysis.

### Adding new database submodules
New files added to `database/` are automatically picked up by `collect_submodules`.
No changes to `imports_summary.json` or the spec `extra=` list are needed unless
the new module imports a **new third-party package** not already in
`suggested_hiddenimports`.

### Pre-build check
```powershell
.venv_build\Scripts\python.exe -c "
from database import get_db_connection, init_database
from database._pool import cleanup_connection_pools
from database.dicom_db import insert_patient
from database.download_progress_db import get_incomplete_downloads
from database.ai_reception_db import ai_save_reception_report
print('database package: OK')
"
```

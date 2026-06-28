# Import opens the FAST Patient Tab (not the legacy VTK viewer) — 2026-06-28

## Symptom (reported)
After importing an external image/study, the Patient Tab that opens automatically
"looks older / inconsistent with the current Patient Tab" and "sometimes feels
slower". Re-opening the **same** study later from the patient list looked correct
(modern). So only the *auto-open right after import* was wrong.

## Root cause (single, precise)
The tab component is the **same** current `PatientWidget` for every path. The
divergence was the **viewer backend** it was forced into.

`_HPImportMixin._open_imported_primary_study`
(`PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_import.py`) opened the
imported study with a hard pin:

```python
self.add_new_tab_widget(..., viewer_backend_override=BACKEND_PYDICOM)   # "pydicom_2d"
```

- `BACKEND_PYDICOM = "pydicom_2d"` is the **legacy VTK-rendering** 2D backend.
- `BACKEND_PYDICOM_QT = "pydicom_qt"` is the modern **VTK-free FAST** viewer and,
  since **v2.3.3**, the default for every other open path
  (`modules/viewer/viewer_backend_config.py` — `DEFAULT_BACKEND = BACKEND_PYDICOM_QT`;
  `pydicom_2d` is deprecated and `resolve_viewer_backend()` remaps it → `pydicom_qt`).

Why the pin won (it shouldn't have): `_vc_backend._get_requested_viewer_backend()`
returns a per-widget override **verbatim** when the configured backend is FAST,
**bypassing** the `resolve_viewer_backend()` remap:

```python
override_backend = getattr(self.parent_widget, "viewer_backend_override", "")
if override_backend and configured_backend in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT):
    return override_backend          # returns "pydicom_2d" — no remap
```

The viewer factory then keys strictly on FAST:

```python
# _vc_layout.creator_vtk_widget / _pw_viewers.creator_vtk_widget
if requested_backend == BACKEND_PYDICOM_QT:
    return QtFastContainer(...)      # modern FAST, VTK-free
return VTKWidget(...)               # everything else -> legacy VTK  ← import landed here
```

So import opened **`VTKWidget`** (old viewer, VTK render windows) while normal
patient-open opened **`QtFastContainer`** (FAST). That fully explains "older UI",
"slower", and "not the updated viewer/pipeline".

### Why it was a stale leftover, not a real requirement
- The pin was added in **v2.3.1** (commit `b46b236f`), *before* v2.3.3 made
  `pydicom_qt` the default and deprecated `pydicom_2d`.
- `IMPORT_PIPELINE_COMPRESSED_DICOM_2026-06-06.md` §3 made **decompress-on-import
  default ON** — imported studies are stored as plain **uncompressed** Explicit VR
  Little Endian (“viewer, thumbnails, pixel cache … all read plain uncompressed
  files”). §4: “SimpleITK/VTK: used for rendering paths, not for import decode.”
  → the VTK pin gave **no decode benefit**.
- The shared sink `save_complete_study_info` (used by server-download, reconcile,
  AND import) produces identical FAST-ready metadata; the FAST viewer reads the
  `.dcm` files straight from `SOURCE_PATH/<study_uid>/<series>/`. Server-downloaded
  compressed studies already open in FAST every day — proof FAST needs no pin.

## Fix (minimal, flag-gated, reversible)
`_open_imported_primary_study` no longer pins the backend by default; it resolves
the **same** backend as normal patient-open (FAST by default, or Advanced if the
user configured it). A kill switch restores the legacy pin without a code change:

```python
force_legacy_import_viewer = os.getenv("AIPACS_IMPORT_FORCE_LEGACY_VIEWER", "0").strip() == "1"
viewer_backend_override = BACKEND_PYDICOM if force_legacy_import_viewer else None
self.add_new_tab_widget(..., viewer_backend_override=viewer_backend_override)
```

- Default (env unset / `0`) → `None` → identical to the normal Patient Tab.
- `AIPACS_IMPORT_FORCE_LEGACY_VIEWER=1` → byte-identical legacy behavior.
- Both the interactive import and `auto_import_folder_from_startup` (CD media) go
  through this one method, so both are fixed at a single point.
- `_hp_import.py` is **not** plugin-mirrored. Eagle Eye's separate VTK override is
  untouched. `report_status` (not passed by import) is unrelated and left as-is.

## Scope / non-goals
Download/registration/thumbnail building and the FAST pipeline are unchanged. No
DB/schema/network/geometry change. The pre-existing import-time thumbnail build
(`_prepare_imported_studies_for_fast_open`) decodes each series once to make
PNGs before the viewer decodes for display — this duplicate decode is inherent to
import (no server thumbnails) and is **not** the reported "old tab" bug; left as a
separate future optimization.

## Verification
- Offscreen (sandbox): `py_compile` clean; pure decision-logic
  (unset/`0`→None, `1`→`pydicom_2d`); source guards
  (`tests/code/ui_services/test_import_viewer_backend.py`) pass. The full
  behavioral pytest needs PySide6 (couldn't install in this sandbox session).
- **NEEDS live source-build verify** (clinical lane): import an external study →
  the auto-opened tab is the FAST `QtFastContainer` (identical look to opening a
  local study from the list), correct patient/study/series + thumbnails, no VTK
  render window, performance ≈ normal local open.

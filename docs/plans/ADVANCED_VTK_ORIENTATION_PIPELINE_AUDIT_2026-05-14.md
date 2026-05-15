# Advanced VTK Orientation Pipeline Audit (Forensic)

## Scope
End-to-end audit for DICOM -> SITK -> VTK -> viewport orientation in Advanced viewer, without behavior changes.

## Instrumentation Added

1. Stage-level source/convert logs in `image_io.py`
- Emits `[ADVANCED_VTK_ORIENTATION_AUDIT]` for:
  - `stage=sitk_read_db`
  - `stage=vtk_convert_db`
  - corresponding filesystem stages
- Captures DICOM header (IOP/IPP/spacing), SITK origin/spacing/direction, VTK origin/spacing/direction field-data presence.
- Stamps metadata fields:
  - `_orientation_audit_sitk_origin`
  - `_orientation_audit_sitk_spacing`
  - `_orientation_audit_sitk_direction`
  - `_orientation_audit_vtk_origin`
  - `_orientation_audit_vtk_spacing`
  - `_orientation_audit_vtk_direction`

2. Per-viewport render-state logs in `modules/viewer/advanced/viewer_2d.py`
- Emits on each `_set_slice_impl`:
  - `[ADVANCED_VTK_ORIENTATION_AUDIT] viewport_id=... series_uid=... series_number=... slice_index=... plane=...`
- Captures:
  - DICOM row/col/normal from IOP
  - actor matrix, reslice axes, camera vectors
  - expected vs actual screen-right/up in LPS
  - mismatch angles (row/col/normal)
  - `orientation_valid` and `failure_class` (A-F)

3. Plugin parity mirror
- Same audit hooks mirrored to:
  - `builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py`

4. Offline proof-table parser
- Added script:
  - `tools/diagnostics/_advanced_vtk_orientation_audit_report.py`
- Reads `viewer_diagnostics.log` and prints required viewport proof table.

## Mismatch Math

Let:
- DICOM row unit vector = $r$
- DICOM col unit vector = $c$
- DICOM normal = $n = \hat{r \times c}$
- expected screen-right = $r$
- expected screen-up = $-c$ (DICOM column points down)

From camera:
- camera up = $u$
- camera direction of projection = $d$
- camera right = $q = \hat{d \times u}$

Project to DICOM plane:
- actual screen-right = $\hat{q - (q\cdot n)n}$
- actual screen-up = $\hat{u - (u\cdot n)n}$
- screen plane normal = $\hat{\text{actual-right} \times \text{actual-up}}$

Angles:
- row mismatch = $\angle(\text{expected-right},\text{actual-right})$
- col mismatch = $\angle(\text{expected-up},\text{actual-up})$
- normal mismatch = $\angle(n, \text{screen-plane-normal})$

`orientation_valid=True` iff all three mismatch angles are <= 10 degrees.

## A-F Failure Classification (Current Heuristic)

- A: source direction exists but active direction and active field direction both absent.
- B: source direction exists but active direction absent (partial direction loss).
- C: non-identity actor transform or large normal mismatch.
- D: missing metadata instance for current slice.
- E: row+col axis mismatch high and source->active direction-loss pattern present.
- F: residual mismatch category.

## Static Risk Findings (Code Evidence)

1. Converter applies Y flip before VTK conversion
- `PacsClient/pacs/patient_tab/utils/utils.py`:
  - `arr = arr[:, ::-1, :]  # Flip Y axis for VTK`
- This makes orientation dependent on a compensating transform contract downstream.

2. Direction stored in field data and optionally copied to active image
- `DirectionMatrix` is written to field data in converter.
- Viewer calls `_apply_direction_matrix_from_field_data`, but active input is reslice output.

3. Multiple paths still assume world = origin + ijk*spacing (direction ignored)
- In `viewer_2d.py` sync/pick logic, comments and equations explicitly use direction-agnostic mapping.
- This is a likely source of mismatch between DICOM patient-space orientation and displayed orientation-dependent computations.

## How to Collect Proof (Knee Session)

1. Run a real Advanced VTK knee side-by-side layout (axial + coronal/sagittal).
2. Scroll each viewport at least one slice so `_set_slice_impl` emits logs.
3. Run:

```powershell
.venv\Scripts\python.exe tools\diagnostics\_advanced_vtk_orientation_audit_report.py
```

4. Copy generated table and map each viewport to A-F class.

## Required Proof Table (Generated)

| viewport | plane | DICOM row/col/normal | SITK direction | VTK direction | actor/camera axes | mismatch_deg | failure_class |
|---|---|---|---|---|---|---|---|
| (from script output) | | | | | | | |

## Minimal Correction Plan (No Behavior Change Yet)

1. Keep instrumentation live and gather knee-session evidence first.
2. Confirm whether direction is lost between source image and active reslice output (A/B) or distorted by actor/camera transforms (C/E/F).
3. Isolate direction-agnostic world<->ijk paths and quantify impact with current logs before editing behavior.
4. Prepare a single minimal patch at the confirmed failure point only, then re-run same proof table and compare mismatch angles.

# Eagle Eye / Mammography Crash — Root Cause & Defensive Fixes (2026-06-05)

Follow-up to `OTHER_PC_LOG_EVALUATION_2026-06-05.md` items **U2** (VTK native
crashes) and **U1** (Response-too-large series failures). All fixes are in the
current source tree, compiled, plugin-mirrored (287/287), and guard-tested.

## 1. The crash, as production saw it

Workflow on the affected clinic PC (frozen build): open MG study in Eagle Eye →
CSV/AI result loads → drag-drop an image into the Eagle Eye viewport → app dies.

`native_fault.log` contains **6 access violations**; 4 are byte-identical chains:

```
viewer_2d.py:276  Viewer2D.__init__   ← SetInputData(self.image_reslice.GetOutput())
_vw_series.py:1117 switch_series      ← ImageViewer2D recreation (slow path)
vtk_widget.py:900  AIVTKWidget.switch_series   ← Eagle Eye override
_vc_switch.py:1047/1059 _perform_series_switch_optimized
_vc_switch.py:733  _finish_on_ui
```

The remaining 2: one in `loading_overlay.py:441 _start_fade` (fade animation on
a deleted overlay), one in `thumbnail_manager.py:53 __init__` (single hit).
Notably **zero 0x8001010d** on that PC — this is not the drag/COM family.

## 2. Root cause

**Where:** the ADVANCED (VTK) viewer construction, not the CSV parser, not the
drag-drop routing, not the GPU.

**Routing is by design:** Eagle Eye forces the VTK/Advanced pipeline
(`AIVTKWidget._bind_backend_from_metadata(..., force_vtk=True)`) because the
CSV bbox/segmentation draw path needs it. So every series drop in Eagle Eye
rebuilds a `Viewer2D` — the FAST viewer is never involved (and stays VTK-free).

**The defect:** `ImageReslice.__init__` (subclass of `vtkImageReslice`, cubic
interpolation) calls `Update()` in its constructor. For large-frame MG images
this materializes a second full-resolution copy (~160 MB per typical FFDM
frame). When that allocation fails on a memory-pressured machine, **VTK does
not raise** — it logs and leaves the filter output as an *empty* `vtkImageData`
(dims 0, no scalar array). The very next line fed that empty image to the
native call:

```python
self.SetInputData(self.image_reslice.GetOutput())   # viewer_2d.py:276
```

`vtkResliceImageViewer.SetInputData` dereferences the scalar pointer natively →
access violation → whole-process death. That is why it is machine-specific:
it is a **RAM/allocation** issue (CPU-side), not GPU, driver, or DPI scaling —
and why it clusters on MG (largest single frames) behind a CSV load (extra
memory already held by the AI overlay).

## 3. Fixes applied

### FIX 1 — validate before the native call (`modules/viewer/advanced/viewer_2d.py`)
New helper `_vtk_image_scalars_valid(img)`: True only for a `vtkImageData`
with positive dims and an allocated scalar array with >0 tuples. The
construction branch now:

1. validates the reslice output → use it (original behavior);
2. else, if the **raw input** image is valid → log `[VTK-GUARD] … allocation
   failure …` and wire the raw input directly (degraded interpolation, but the
   image displays and the app lives);
3. else raise a plain Python `RuntimeError` — which `_vw_series.switch_series`'s
   existing `except Exception` (L1182) catches, logs, and degrades cleanly.
   A failed series switch instead of a dead process.

### FIX 2 — overlay fade liveness (`PacsClient/components/loading_overlay.py`)
`hide_overlay`'s `_start_fade` now checks `shiboken6.isValid(overlay)` before
constructing the `QPropertyAnimation`, and catches `RuntimeError` from a
mid-flight C++ deletion → `_cleanup(overlay)`. Kills the
`loading_overlay.py:441` AV (fade scheduled on an overlay whose widget was
torn down by a fast series switch).

### FIX 3 — U1 "Response too large" recovery (`modules/download_manager/network/socket_client.py`)
Investigation showed the existing batch-halving branch was **dead code**: the
`NetworkError("Response too large…")` raised at the 500 MB length check was
swallowed by `send_request`'s generic handler → `None` → the series failed
with an opaque `'No response'` (16 production failures, "series 8" ×12).
Now:

- `send_request` returns a structured `{'status':'error', 'error': …}` for
  this error on the **GetSeriesImages endpoint only** (all other endpoints
  keep their None-on-error contract);
- `download_series` halving fires again, and at minimum batch size performs
  **2 bounded same-size retries on a fresh socket** — correct recovery, since
  an implausible declared length almost always means stream desync (the four
  "length" bytes were payload garbage), not real size. The socket is already
  dropped at the raise site, so the retry reconnects clean;
- the retry budget resets per successful batch; on exhaustion the failure
  reason surfaced to the DM is now the real `Response too large: N bytes`.

Note: MG/large-frame series already force single-instance batches
(`_should_force_single_instance_batches`), so for the production failures the
desync-retry path is the one that matters.

## 4. Verification

| Check | Result |
|---|---|
| `tests/code/viewer/test_vtk_input_guard.py` (5 vtkImageData unit tests incl. empty-image failed-Update analogue + 2 source contracts) | **7/7 passed** |
| `tests/code/download_manager/test_response_too_large_u1.py` (4 source contracts) | **4/4 passed** |
| Full `tests/code/download_manager` regression | **119 passed** |
| `py_compile` viewer_2d / loading_overlay / socket_client | OK |
| `tools/dev/verify_plugin_mirrors.py` | **287/287** (viewer + DM payloads synced) |

## 5. Answers to the investigation questions

- **VTK initialization?** Yes — exactly there (reslice output → native
  SetInputData), now guarded.
- **GPU / rendering backend / scaling?** No — the fault is CPU-side memory
  allocation before any rendering; no GPU code in the chain; no DPI factor.
- **Image size?** Yes — large MG frames are the trigger (cubic-interpolated
  full copy), which is why MG + Eagle Eye dominates.
- **CSV overlay / segmentation / bbox?** Not the fault site; it contributes
  memory pressure and forces the VTK path, both by design.
- **Drag-drop routing FAST vs ADVANCED?** Correct as-is: Eagle Eye must force
  Advanced/VTK for the overlay draw; FAST stays VTK-free. No routing change.
- **Where should the fix be?** Viewer rendering init + overlay teardown +
  download error propagation — applied. The crash is now a logged, recoverable
  failure on any machine, regardless of its RAM situation.

## 6. Remaining / noted

- `thumbnail_manager.py:53` AV (×1): `QPropertyAnimation(self, b"progress")`
  during widget construction — left unguarded (single occurrence,
  construction-time, different family). Watch in future logs.
- These fixes are in source only. The affected PC runs a frozen build —
  **shipping the next build remains the highest-value action** (see
  `OTHER_PC_LOG_EVALUATION_2026-06-05.md` §1).
- Still open from that report: U3 close-path stalls, U4 deferred styling,
  U5 misc GUI-thread blockers, U6 frozen extraction stalls.

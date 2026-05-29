# Golden pixel-hash baselines (F1.1)

This directory holds JSON files capturing per-slice `sha256(qimage.constBits())`
hashes for parametrised cases of the FAST viewer rendering pipeline. They form
the **image-quality safety net** that protects every behaviour-changing step
in phases F3–F9 of the FAST viewer overlap performance plan.

## Cases

| File | filter_enabled | photometric |
|------|---------------|-------------|
| `overlap_pixel_filter_off_mono2.json` | False | MONOCHROME2 |
| `overlap_pixel_filter_on_mono2.json`  | True  | MONOCHROME2 |
| `overlap_pixel_filter_off_mono1.json` | False | MONOCHROME1 |
| `overlap_pixel_filter_on_mono1.json`  | True  | MONOCHROME1 |

## How to (re)capture

```powershell
.venv\Scripts\python.exe -m pytest tests/viewer/test_overlap_pixel_quality.py --capture-golden -v
```

Capture is allowed ONLY when the production pipeline is in a known-good state
(typically: at the start of a phase, after a change has been hash-validated).
Re-capture is a deliberate act — review the diff in code review.

## How to validate

```powershell
.venv\Scripts\python.exe -m pytest tests/viewer/test_overlap_pixel_quality.py -v
```

100% match required for settled (`fast_interaction=False`) frames in all four
parametrised cases. Any mismatch fails the test and BLOCKS the change.

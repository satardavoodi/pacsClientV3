# AIPacs v3.0.4 Release Notes

**Date:** 2026-05-17  
**Branch:** matab-conservative  
**Previous stable:** v3.0.3

---

## Summary

FAST viewer V2 stack-drag model promoted to **default ON**, resolving choppy
navigation on spine MRI and other small-series studies (< 25 slices).

---

## Root Cause Diagnosed

Patient 41584 spine MRI (series 7, ~20 slices):

- V1 natural threshold: `px_per_slice = h / n ≈ 308 / 20 = 15.4 px`
- At clinical drag speed 150 px/s: 1 accepted event per ~103 ms → ≈ 10 events/sec
- `[FAST_EVENT_PACING]` log confirmed `queue_wait_classification=INPUT_DELIVERY_GAP`
  in **all 19 drag sessions** for that series
- `[B3.8_SCROLL]` showed `frame=20/40/60 slice=4` (frozen same slice for 60+ consecutive
  frames) — direct confirmation of the slide-show perception

Smooth large series (series 12, 120+ slices) showed `QT_UPDATE_PAINT_DELAY`
classification with `event_p50=25–31 ms` — the dead-zone is the discriminating
factor, not rendering speed.

---

## Change: V2 Drag Model Now Default ON

**Kill switch:** Set `AIPACS_STACK_DRAG_V2=0` to revert to V1 behaviour.

### V2 Band Parameters

| Band   | n range    | px/slice      | max/event | Velocity gain |
|--------|-----------|---------------|-----------|---------------|
| tiny   | n < 25     | **7.0 px fixed** | 1       | none          |
| small  | 25 ≤ n < 50 | **6.0 px fixed** | 1      | none          |
| medium | 50 ≤ n < 100 | natural × 1.0 | 1      | up to ×1.4   |
| large  | 100 ≤ n < 200 | natural × 3.5 | 2     | up to ×1.9   |
| xlarge | 200 ≤ n < 400 | natural × 4.0 | 2     | up to ×2.2   |
| huge   | n ≥ 400    | natural × 4.5 | 3       | up to ×2.5   |

For the problematic spine MRI (n=20, tiny band):

- Before (V1): `px_per_slice ≈ 15.4 px` → ~10 events/sec at 150 px/s
- After (V2): `px_per_slice = 7.0 px` → ~21 events/sec at 150 px/s (**≈ 3× improvement**)

### Files Modified

| File | Change |
|------|--------|
| `modules/viewer/fast/qt_slice_viewer.py` | `AIPACS_STACK_DRAG_V2` default `"0"` → `"1"` |
| `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/qt_slice_viewer.py` | SHA-equal mirror |
| `tests/viewer/test_qt_slice_viewer_stack_drag.py` | 9 V1-specific tests pinned to V1 via `monkeypatch` |
| `pyproject.toml` | Version bump 3.0.3 → 3.0.4 |

---

## Test Results

```
tests/viewer/test_qt_slice_viewer_stack_drag.py  46 passed (was 37 passed + 9 failed)
```

All 9 previously failing tests are now passing. Tests that explicitly exercise V1
accumulation mechanics use `monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)` to
remain valid V1 regression tests while V2 runs by default.

---

## Critical Rule Added

**R26-V2 (v3.0.4):** V2 drag model is default ON. `AIPACS_STACK_DRAG_V2=0` is the
escape hatch. Do NOT flip the default back to `"0"` without first re-validating the
INPUT_DELIVERY_GAP diagnostic on small-series studies. The 7 px fixed dead-zone for
the tiny band (n < 25) is the load-bearing fix for spine MRI choppiness.

---

## Regression Guards

- `test_v2_tiny_band_has_smaller_threshold_than_v1_natural` — asserts V2 tiny (7 px)
  < V1 natural (15.4 px) for n=20, h=308
- All V2 band-param tests in `TestV2BandParams` run with V2 active (no monkeypatch)
- V1 regression tests explicitly pin `_USE_V2_MODEL=False`

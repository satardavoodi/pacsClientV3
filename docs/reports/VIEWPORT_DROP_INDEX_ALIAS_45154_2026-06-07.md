# Viewport drop silently ignored — thumbnail-index aliasing (45154 s102)

**Date:** 2026-06-07 · **Commit:** `8091f72` · **Severity:** workflow (no data risk)

## Symptom
Patient 45154 (multi-study). Dragging Series 102 into one viewport loads fine;
dragging the same series into the other viewport does nothing — the old image
stays. Which pane "works" depends on drop order, not on the pane itself.

## Evidence (live-app logs, 2026-06-07 11:32)
`viewer_diagnostics.log` / `app.log`, pid 83740:

| time | event | viewer |
|---|---|---|
| 11:32:38.826 | `[VIEWER_SWITCH] phase=switch_start switch-1000102` | **0** |
| — | *nothing further: no `_start_qt_viewer`, no completion* | |
| 11:32:40.796 | `[VIEWER_SWITCH] phase=switch_start switch-1000102` | **1** |
| 11:32:40.817–.833 | `widget_created` → `first_image_visible` → `switch_series: complete slices=175` | 1 |

Both drops entered `_perform_series_switch_optimized` (so routing, drop-target
detection, no-op metadata guard, and the inflight dedupe were all healthy).
Drop A died silently inside the pane widget.

## Root cause
`QtFastContainer.switch_series` (FAST pane) and its VTK twin
(`_vw_series.py::switch_series`) decided their same-series no-op with:

```python
if self.last_series_show == series_index: ...skip
```

`last_series_show` stores a **thumbnail-list index** by contract
(`_vc_layout.py:710`), and `series_index` is the index resolved for the
incoming series. On a multi-study patient the sidebar/index space is rebuilt
(`_rebuild_multistudy_series_index`, offset keys `slot*1_000_000+n`), so two
*different* series can carry the *same* list index at different times.
Pane 0's stale index for series 1000005 equalled the resolved index for
1000102 → the guard concluded "already showing" and returned `False` with a
**debug-level** log only. A list index is not a series identity.

Not the cause (checked and cleared): drag-event routing (both pane types
forward to the same handlers), pane identification (`id_vtk_widget` unique per
pane), active/primary-pane special-casing (none exists), the controller's
metadata no-op guard (read the correct per-pane bridge metadata), the
`_viewer_switch_inflight` dedupe (per-pane key, discarded in `finally`), and
spinner/refresh (skip path hides the spinner; nothing leaked).

## Fix (both active switch paths; `_legacy_widget.py` is env-gated A/B backup, untouched)
Decide the no-op by **displayed series identity**: `series_number` plus a
`series_path` tie-breaker when both sides carry one — the same contract the
FAST in-place-refresh check already used (synthetic numbers like `100000`
repeat across studies, so number alone is not identity). `last_series_show`
keeps its index semantics for all existing consumers (toolbar resets,
metadata fallbacks). Skip log upgraded debug → info.

## Verification
- `tests/code/viewer/test_viewport_drop_replacement.py` — 7 green, including
  the exact aliased-index repro, synthetic-number/path tie-break, fresh-pane,
  fail-open, and a source-level anti-pattern guard for both files.
- Related suites: `test_document_series_drop_fit.py`,
  `test_dragdrop_progressive.py`, `test_mainwindow_drag_gate.py` → 31 passed,
  1 skipped (stale spec), 2 failed — **pre-existing** (verified by stashing
  the fix and re-running; stale `_awaiting_apply_retries` specs, see Follow-ups).
- Live retest recipe (15 s, after next app start): open 45154 → drop s102 into
  pane 2 → then drop s102 into pane 1 → pane 1 must replace. Expect
  `[VIEWER_SWITCH] phase=switch_start viewer=0` followed by
  `switch_series: complete`, or an INFO `already showing` line if genuinely
  the same series.

## Follow-ups (out of scope, noted)
- `_pw_pipeline.py:764` compares `last_series_show == series_num` (index vs
  NUMBER — always false) in the auto-assign dedupe; harmless today but the
  same semantic confusion.
- 2 stale `test_dragdrop_progressive` specs vs the committed
  `_awaiting_apply_retries` retry behavior need a spec refresh.

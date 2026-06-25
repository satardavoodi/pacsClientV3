# Unified Series-Display Authority — Implementation Plan (2026-06-24)

Turns §7 of `docs/reports/SERIES_DISPLAY_PIPELINE_UNIFIED_METHOD_EVALUATION_2026-06-24.md`
into staged, flag-gated, GUI-validated work. Goal: make the FAST viewer's
load/switch/grow/resume orchestration **structurally** unified — one read model, one
decide-once function — instead of 13+ entry points each re-deriving the decision from 4
disagreeing count sources.

**Clinical guardrail (unchanged from the unified-pipeline doc §7):** this is a
data-path / decision-authority change. It stays **above `set_server_series_info`** and must
NOT touch VTK/MPR geometry, slice order, orientation, or verified rendering. Every step is
flag-gated default-on with the legacy path preserved as a kill switch, and is independently
GUI-validatable.

---

## Phase 1 — DONE (2026-06-24, this session)

### 1A. The pure decision authority ✅
`PacsClient/utils/series_display_state.py` — pure stdlib (+ `series_completeness`), no
Qt/VTK/pydicom/numpy, unit-testable in isolation (like `patient_study_set.py`).
- `SeriesDisplayState` — the read model over the 4 counts (server / disk / canonical-metadata
  / viewer-visible) + resolved-expected, with `target = max(disk, expected)`.
- `DisplayAction` — the closed action set: `NOOP`, `GROW_IN_PLACE`, `REFRESH_AND_REBUILD`,
  `REBUILD`, `SKIP_DOWNGRADE`, `AWAIT_DOWNLOAD`.
- `decide_display_action(state)` — the ONE decide-once truth table.
- Tests: `tests/code/ui_services/test_series_display_state.py` (13, incl. the 203 and 47804
  scenarios + the never-downgrade rule). Green.

### 1B. First live wiring — the never-downgrade guard ✅
`_vc_switch.py::change_series_on_viewer` same-series block now builds the state from the
counts it already gathers **plus the viewer's real `get_count_of_slices()`** and consults
`decide_display_action`. On `SKIP_DOWNGRADE` it keeps the fuller volume and returns; **every
other action falls through to the existing (tested) branching unchanged** — purely additive.
Flag `AIPACS_UNIFIED_SERIES_DISPLAY` default-on (`=0` = legacy). This supplies the one action
the legacy block lacked (it reasoned from canonical-metadata count, never from actual visible
slices), closing the resume-watchdog "99 → 8" reset structurally. The resume watchdog
(`_maybe_resume_awaiting_from_disk`) calls `change_series_on_viewer(force_reload=False)`, so it
is covered by this guard with no separate edit.
- Tests: `tests/code/viewer/test_unified_series_display_wiring.py` (4). Green.

**Live-verify before Phase 2:** reopen 47842/47793 on Razi, view series 203 → all slices; and
confirm a normal multi-series patient still switches/grows with no `skip-downgrade` false
positives in `viewer_diagnostics.log`.

---

## Phase 2 — 2A DONE; rest STAGED (each flag-gated, GUI-validated, then flipped on)

### 2A. Route the same-series decision through the authority ✅ (2026-06-24)
`_vc_switch.py::change_series_on_viewer` now computes the authority's verdict ONCE
(`decide_display_action`, fed `get_count_of_slices()` + `has_lazy_loader`) and **maps it onto
the operation flags**: `GROW_IN_PLACE`/`REFRESH_AND_REBUILD` → `series_grew=True`,
`AWAIT_DOWNLOAD` → `series_incomplete=True`, `NOOP` → both False, `SKIP_DOWNGRADE` → keep-and-return.
The proven operation blocks (in-place grow, grow-fallback metadata-sync, incomplete reassert)
run **unchanged** on that verdict. This removes the dual decision (the canonical-metadata-only
`completeness` flags vs the viewer-aware authority) and, critically, makes the decision **viewer-
aware** — it now catches a viewport that is behind disk even when canonical metadata already
caught up (the case the legacy flags could not see). Same flag `AIPACS_UNIFIED_SERIES_DISPLAY`
(default-on, `=0` = legacy `completeness` flags). Tests:
`tests/code/viewer/test_unified_series_display_wiring.py` (6). Also shipped the resume-watchdog
**settled-state stop** (`AIPACS_RESUME_STOP_WHEN_SETTLED`) which cut the live 145× resume loop
(`tests/code/viewer/test_resume_stop_when_settled.py`).

**Note (resume cap):** `_DISK_READY_RESUME_MAX_ATTEMPTS=6` is defeated when the awaited-key
churns (per-episode reset zeroes the counter), which is how 145 attempts happened. The settled-
stop addresses the symptom (clear the stale awaited flag → watchdog stops being called). 2B
should make the awaited-flag clear at the load-success source so the cap is meaningful again.

### 2B. One `ensure_series_displayed(viewer, series, intent)` controller chokepoint
A single method (on the ViewerController) that builds the state and runs the dispatch, so the
**other entry points funnel through it** instead of re-implementing the decision:
`load_series_on_demand`, `_display_series_after_load`, `on_series_download_fully_complete`,
`_completion_verify_series`, `_completion_sweep_tick`, `_grow_progressive_fast`,
`_start_progressive_display`, and the disk-ready resume. Migrate one caller at a time, each
behind its own sub-flag + guard test + a GUI pass. The canonical metadata sync becomes
**structurally guaranteed** (called inside the chokepoint), not hand-placed at ~10 sites.

### 2C. One disk-count read authority
Keep the 1 s TTL `_count_series_files_on_disk` cache but make the download-complete boundary the
**only** place that may serve a "complete" verdict on a freshly-busted count (the post-complete
gate already does this — generalize it). No consumer should be able to read a stale-low count and
conclude completeness. Fold the four count getters behind the `SeriesDisplayState` builder so the
57 ad-hoc reads collapse to one accessor over time.

### 2D. Collapse the duplicate `change_series_on_viewer`
There are two: `_vc_switch.py:122` (live) and `thumbnail_panel.py:267` (legacy). Confirm the
legacy `ThumbnailBatchRunner` is never instantiated (memory says so) and remove/redirect the
parallel method so there is one switch authority.

### 2E. Converge with the upstream `DownloadPlan` / catalog
Per `docs/pipelines/unified-patient-study-pipeline.md` §7.2/§7.4 + §8: the viewer chokepoint
(2B) and the study-set authority (`PatientStudySetService`) should meet at one typed
`DownloadPlan` + `PatientStudyCatalog` read model, so open / back-fill / drag-drop / progressive
all share ONE resolver + ONE plan + ONE single-flight slot + ONE display decision.

---

## Sequencing & safety

1. Live-verify Phase 1 (203 fixed; no false `skip-downgrade`).
2. 2A (same file, decision already validated by 1B) → GUI pass.
3. 2B one caller at a time, highest-risk-of-desync first (progressive grow, resume, completion).
4. 2C alongside 2B (the chokepoint is the natural home for the single count read).
5. 2D (cleanup) and 2E (converge with the upstream unified pipeline) last.

Each step: pure-logic change in `series_display_state.py` (unit-tested) + a thin, flag-gated,
source-pinned wiring edit + an offscreen guard + a live source-build GUI pass. No VTK/MPR/render
change at any step.

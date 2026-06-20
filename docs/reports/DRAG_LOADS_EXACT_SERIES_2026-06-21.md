# Drag loads EXACTLY that series — multi-study / previous-exam resolution (as-built, 2026-06-21)

**Status:** implemented, live-verified on patient 44030 (current ANKLE + previous exams
43373 BRAIN MR and 47214 DOC merged into one tab), stabilized with regression guards.
**Scope:** viewer series-load resolution only. No change to slice ordering, IPP/IOP
geometry, orientation, VTK/MPR, downloads, or clinical isolation. Single-study patients
are byte-identical.

## Symptom

On a multi-study tab — a current patient plus one or more **Previous Exams** merged in
(prior studies of the same real person under DIFFERENT Patient IDs / Study UIDs) — after
viewing a previous exam, dragging a **current** series into a viewport showed the
**previous** study's series instead. It worsened after several drags and a re-open
"fixed" it temporarily.

## Root cause

The viewer resolved the right series **identity** but loaded **pixels from the wrong
study folder**. Each series load computes a `study_path` (the study's disk folder) and a
disk series number. The tab-level `study_path` (derived from the widget's
`import_folder_path`) gets "poisoned" to the previously-viewed exam's folder. The
plain-key resolver then kept that poisoned path with a folder-existence short-circuit:

> if `study_path/<series>/` exists on disk → keep `study_path`.

Because a previous exam very often **also has a same-numbered series** (both 44030 and
43373 have a "series 2"), the check passed and the current series loaded from the
previous study's folder.

This was proven from `user_data/logs/app.log` once the resolution trace was routed to a
readable channel (see "How it was found"):

```
[VIEWPORT-LOAD-TRACE] dropped_key=2 resolved_study=...0530112945.0.173(44030) is_previous=False ... study_path=...20260530112945.0.173   ✅ correct (early)
[VIEWPORT-LOAD-TRACE] dropped_key=2 resolved_study=...0530112945.0.173(44030) is_previous=False ... study_path=...30000026052404...089(43373)  ❌ WRONG (after a previous-exam drop)
```

Same current key `2`, two different `study_path` values — the second pointing at the
previous study 43373.

## The fix (`PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`)

Make **each series' own `_server_series_info` entry the single source of truth** for
which study + disk folder it loads from — for **every** key, not just non-primary ones.

The multi-study index builder (`_rebuild_multistudy_series_index`, `_pw_thumbnails.py`)
stamps every rebuilt entry — **primary slot 0 included** — with
`series_path = SOURCE_PATH/<study_uid>/<orig_no>`, `_orig_series_number`, `_study_slot`
and `study_uid`. So the entry already encodes the exact disk location of the dragged
thumbnail.

Three resolution layers now guarantee exactness:

1. **Entry authority (primary path).** A new pure helper
   `resolve_entry_study_location(entry, tab_study_path)` returns
   `(study_dir, disk_series_number)` from the entry's `series_path` whenever the entry has
   **both** `series_path` and `_orig_series_number`. The multi-study gate in
   `_load_single_series_on_demand` calls it for **every** key. Previously this gate was
   restricted to `_study_slot > 0`, so current/primary keys skipped it and fell back to
   the poison-prone tab path — that restriction is removed.
2. **Fallbacks.** If the entry is missing (an offset key whose entry was rebuilt away),
   the offset-key fallback recomputes `(study_uid, orig)` from the **stable** slot
   registry `_multistudy_slot_order`. The plain-key fallback
   (`_resolve_plain_series_study_path`) now trusts the entry's `series_path` first and
   redirects even when the poisoned path coincidentally contains that series number.
3. **Cache guard.** `_vc_cache._cache_entry_study_matches` drops any cached pixels whose
   `study_uid` does not match the study the key currently resolves to
   (`[CACHE-STUDY-MISMATCH]`), so a stale cache entry can never surface another study's
   image.

### Why single-study is unaffected

The entry-authority gate requires **both** `series_path` **and** `_orig_series_number`.
Single-study entries carry `series_path` but **not** `_orig_series_number` (only the
multi-study rebuild sets it), so the gate returns `(None, None)` and the original
tab-path behaviour runs unchanged — byte-identical.

## Invariants (do not regress)

- **A dragged series always loads from its own study folder.** Resolve disk location
  from the series' own `_server_series_info` entry (`series_path` /
  `_orig_series_number`), never from the tab's `import_folder_path` / `study_path`, which
  can point at a different study on a multi-study tab.
- The entry-authority gate must call `resolve_entry_study_location` for **every** key.
  Do **not** re-gate it on `_study_slot > 0` (that regresses current/primary keys — the
  original bug).
- `resolve_entry_study_location` stays **pure stdlib** (unit-testable in isolation).
- The gate requires `series_path` **and** `_orig_series_number` so single-study stays
  byte-identical.
- Keep all three layers (entry authority → stable-slot / plain-key fallback → cache
  study-match guard). Each defends a different failure mode.
- Clinical isolation is unchanged: previous exams are admitted only via the
  `sanctioned_uids` allow-list in `merge_study_uids`; each exam keeps its own
  `study_uid` + `patient_id`; disk stays keyed by `study_uid`.

## Diagnostics

- **Always-on (INFO, `app.log`):** `[MULTI-STUDY LOAD] key=<k> -> study_path=<dir>
  disk_series=<n> (entry-authority slot=<N>)` — the production diagnostic; `study_path`
  must match the key's study.
- **Opt-in (`AIPACS_VIEWPORT_LOAD_TRACE=1`):** `[VIEWPORT-LOAD-TRACE]` adds the canonical
  `resolved_study` + `series_uid` + `is_previous` cross-check (routed to `app.log` via
  `component="ui"`). Default **off** after stabilization to keep production logs clean.
- **Verification rule:** for every drop, the `[VIEWPORT-LOAD-TRACE]` `study_path` must
  equal `resolved_study`, and `is_previous` must match the dragged origin (current vs
  previous).

## How it was found (lesson)

The blocker was **looking in the wrong log**, not the code. Viewer-component logs route
to `viewer_diagnostics.log`, which had stalled mid-session, so the trace looked absent
and the live app looked "unrelated to the repo." Routing the trace to `app.log`
(`component="ui"`) made the resolution readable and the defect was immediately obvious
(`resolved_study=44030` but `study_path=43373`). When a fix "isn't working," verify the
diagnostic channel before doubting the code path.

## Verification

- Pure resolver extracted from source and exercised: **7/7** scenarios (current primary
  with poisoned tab path → own study; previous → previous; poisoned-same-number →
  correct; single-study / `None` / no-path / non-dict → `(None, None)`).
- Source-pin wiring confirmed: gate calls `resolve_entry_study_location`; the old
  `_study_slot ... > 0` gate is gone; plain-key entry-authority present; cache guard
  present.
- Live log (pid 719420): every drop shows `study_path == resolved_study` — current keys
  1/2 → 44030 `(entry-authority slot=0)`; previous keys → 43373 `(slot=1)` and 47214 DOC
  `(slot=2)`. No errors, no `[CACHE-STUDY-MISMATCH]`.
- Regression test: `tests/code/viewer/test_drag_loads_exact_series.py` (pure behavior +
  source-pin). Run on Windows with PySide6 present:
  `python -m pytest tests/code/viewer/test_drag_loads_exact_series.py -q -p no:debugging`.

## Files changed

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py` — new pure
  `resolve_entry_study_location`; gate delegates to it for all keys; `_resolve_plain_series_study_path`
  entry-authority-first; `[VIEWPORT-LOAD-TRACE]` made opt-in.
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py` — `_cache_entry_study_matches`
  study-scoped cache guard (pre-existing in this work; an invariant here).
- `tests/code/viewer/test_drag_loads_exact_series.py` — new regression guard.

None of these files are plugin-mirrored. Flags: `AIPACS_VIEWPORT_LOAD_TRACE` (default off).
Related: `docs/pipelines/previous-exams.md`, `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`,
`docs/reports/CROSS_PATIENT_STUDY_MIXING_44504_2026-06-02.md`.

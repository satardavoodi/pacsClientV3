# Wrong-study load — primary series after a previous-exam series (48912 / 29694) — 2026-07-04

**Severity:** HIGH — clinical correctness (one study's images shown under another).
**Type:** minimal, flag-gated, offscreen-verified. **Live-verify pending.**
**Kill switch:** `AIPACS_PRIMARY_SERIES_POISON_GUARD=0` → byte-identical legacy.

## Symptom (user report + log-confirmed)

Patient 48912, current exam + 1 previous exam (study 29694). Load previous-exam series 4
(offset key `1000004`) into a cell, then try to load **current-exam** series 4 (plain key `4`) —
it won't appear; the previous exam's series 4 just re-renders. User clicked current series 4
five times (12:28:05 → 12:35:07) with no effect.

## Root cause (proven from `viewer_diagnostics.log`, session pid 310688)

The current-series-4 drop resolved its disk path to the **previous** study:

```
[QtFastContainer DROP] apply — series=4                       (dropped CURRENT series 4)
[SERIES UNLOAD] … rebind_to_series=1000004                    (rebinds to PREVIOUS series)
lw2d open_series path=…\<PREVIOUS_STUDY>\4                     (loads previous study's /4)
[VIEWER_SWITCH] … series=1000004 … first_image_visible series=1000004
```

Mechanism: viewing the previous exam left the tab-level `study_path` / `import_folder_path`
**poisoned** to the previous study. `_resolve_plain_series_study_path`
(`_vc_load.py`) re-resolves a poisoned path back to the correct study **only via the series'
`_server_series_info` entry `series_path`** — but on this tab only the **secondary**
(previous-exam) entries carry a `series_path`; the **primary** series 4 entry has none (no
`[MULTI-STUDY LOAD]` entry-authority line fired for key 4). So resolution fell through to the
final check *"does `study_path/4` exist?"* — and because the poisoned previous-study folder
**also** has a `/4` (series-number collision), it answered yes and kept the wrong study.

This is the "drag loads exact series" multi-study class (2026-06-21), but that fix relied on the
entry `series_path`, which the **primary** entry lacked here — the uncovered case:
**a primary/plain-key series loaded *after* a secondary series poisoned the path.**

## Fix

A plain (`< 1_000_000`) key always belongs to the tab's **primary** `study_uid`. In
`_resolve_plain_series_study_path`, after the entry-authority check, add a poison guard: on a
**multi-study** tab, if the passed `study_path`'s folder name ≠ the primary `study_uid`,
re-resolve to `SOURCE_PATH/<primary_study_uid>` — but only when that primary folder actually has
the series on disk.

```python
if multistudy and primary_uid and study_path and Path(study_path).name != primary_uid:
    pp = SOURCE_PATH / primary_uid
    if (pp / series_key).exists():
        return str(pp)          # re-resolve the plain key to its OWN (primary) study
```

## Why it is safe

- **Enforces the multi-study isolation invariant** (plain key ⇒ primary study) — it strengthens
  cross-study isolation, it does not weaken it.
- Fires **only** on a multi-study tab, **only** when the path is actually poisoned
  (`name != primary_uid`), and **only** when the primary study has the series on disk (never
  invents a path / never mis-resolves a not-yet-downloaded series).
- Single-study tabs and correctly-resolved primary loads never enter the branch → **byte-identical**.
- Runs **after** the existing entry-authority resolution (so the 2026-06-21 secondary-series fix
  is untouched); it is a backstop for the case that fix doesn't cover.
- Flag-gated default-on; `=0` = exact legacy.

## Files changed

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py` — poison guard in
  `_resolve_plain_series_study_path`.
- `tests/code/viewer/test_primary_series_poison_guard.py` — new guard (source-pins + a
  filesystem-backed mirror of the decision).

## Verification

- `py_compile` clean.
- Offscreen: `test_primary_series_poison_guard.py` **7 passed** (poison re-resolves to primary;
  kill-switch keeps legacy; single-study byte-identical; correct-primary unchanged; absent-on-disk
  does not mis-resolve). `test_plain_series_study_path.py` / `test_drag_loads_exact_series.py`
  error/skip on `No module named PySide6` (pre-existing base-sandbox limitation, unrelated).

## Acceptance / rollback

- **Acceptance (live):** on 48912, load previous-exam 29694 series 4, then load current-exam
  series 4 — it must display the **current** study's series 4 (overlay study/series matches the
  current exam), on the first try; log shows
  `[MULTI-STUDY LOAD] key=4 -> study_path=<CURRENT> (primary poison-guard; passed=<PREVIOUS> …)`.
- **Rollback:** `AIPACS_PRIMARY_SERIES_POISON_GUARD=0` (or git revert the two files).

## Deeper follow-up (not done)

The real origin is that the **primary** study's `_server_series_info` entries lack `series_path`
on a multi-study tab (only the merged secondary entries get one in
`_rebuild_multistudy_series_index`). Populating `series_path` for the primary slot too would let
the existing entry-authority path resolve every key uniformly — a larger change with wider blast
radius; the poison guard is the contained fix. Track as a multi-study identity unification item.

# The active viewport must not carry a reference line

**Date:** 2026-08-16
**Reported as:** *"Check this imported study — it shows 2 reference lines in the active layout and in the active one."*
**Study:** SENAC--FRICHETEAU, ID I10027433471 (imported cervical-spine MR)
**Status:** fixed, guarded, reversible
**File touched:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py` (one function's default)
**Guard tests:** `tests/code/viewer/test_reference_line_active_viewport.py` (17), plus two re-pointed in `test_reference_lines_all_pairs.py`
**Kill switch:** `AIPACS_REFERENCE_LINES_ALL_PAIRS=1` restores bidirectional lines

---

## 1. What was on screen

A 2-up layout: **SAG T1 TSE** (series 9, image 8/15) on the left, **AX T2 TSE
CHARNIERE** (series 14, image 13/15) on the right. Series 14 was the active
series — blue border and the red active bar on its thumbnail.

Both viewports carried a yellow line: a near-horizontal one across the sagittal,
and a vertical one down the axial. Two lines in a two-viewport layout, one of
them on the viewport the reader was actively scrolling.

## 2. This was not a defect — it was the shipped default

`_manage_reference_line_all_pairs` does exactly what its docstring says:

> Draw, on EVERY viewport, one reference line per OTHER viewport.

and it explicitly refuses to self-reference:

```python
for srec in records:
    if srec is trec:
        continue  # a viewport never draws its own plane on itself
```

So with two viewports the correct all-pairs output is **exactly one line each,
two in the layout** — precisely what the screenshot showed. Nothing was
duplicated, nothing was stale, and the imported-study angle turned out to be a
red herring: the geometry was fine.

The all-pairs mode was added for a real reason, recorded in the code: the older
single-source path meant "axial→sagittal/coronal worked, sagittal→axial and
coronal→anything never appeared". Bidirectional fixed that.

## 3. Why it is still wrong for reading

The reader's mental model is the localizer convention: **the active series is
the SOURCE.** It is the one being scrolled, and it should stay clean; the line
belongs on the series being cross-referenced, showing where the active slice
cuts it. A line drawn *on* the image you are actively scrolling is visual noise
over the anatomy you are looking at — here, straight across the C-spine cord on
a T2 axial.

This is a product judgement, not a geometry bug, so it was **taken to the owner
before changing anything**. Confirmed: no line on the active viewport.

## 4. The fix

One default, in `_rl_all_pairs_enabled()`:

```python
# was: default "1", off-vocabulary  ("0"/"false"/"no"/"off")
return str(_os.environ.get(self._RL_ALL_PAIRS_ENV, "0")).strip().lower() \
    in ("1", "true", "yes", "on")
```

That routes `manage_reference_line()` to the legacy single-source path, which
already implements exactly the requested behaviour — including the part that
matters most:

```python
# Skip drawing on the source viewer itself
if vtk_widget is self.selected_widget:
    if getattr(iv, 'IS_QT_BRIDGE', False):
        iv.qt_viewer.clear_overlay_lines()
    else:
        reference_line.rl_hide_actor_if_any(iv)
    ...
    continue
```

It **clears** the source overlay rather than merely skipping it. That is the
difference between a fix and a fix that looks broken: a viewport drawn on while
it was inactive must lose its line the moment the user clicks it.

### Why flip the default rather than write new code

The behaviour asked for already existed, fully implemented, on a path that:

- handles the Qt bridge (`IS_QT_BRIDGE` → `set_overlay_lines` /
  `clear_overlay_lines`) everywhere, so the FAST viewer is covered — checked,
  not assumed, because a legacy path that predated the Qt bridge would have
  silently killed reference lines in FAST mode;
- clears the target when geometry is missing or the planes do not intersect,
  so no stale lines;
- was kept deliberately as the documented kill switch.

Writing a third mode would have added a code path to maintain for no gain.

**Nothing was deleted.** `_manage_reference_line_all_pairs` is untouched and
keeps all of its own tests; `AIPACS_REFERENCE_LINES_ALL_PAIRS=1` restores it.

### One deliberate detail

The flag's vocabulary was inverted rather than just changing the fallback
string: it now enables on `1/true/yes/on` instead of disabling on
`0/false/no/off`. A site that had explicitly set `0` is therefore unaffected,
and an unset/garbled value falls to the safe side — the new default.

## 5. What changes in practice

| Layout | Before | After |
|---|---|---|
| 2-up, axial active | line on both | line on the sagittal only |
| 3-up, axial active | line on all three (2 each) | lines on sagittal + coronal, axial clean |
| Click a different viewport | lines stay everywhere | the clean viewport follows the selection |
| Single viewport | none | none |

Slice-change propagation is unchanged: scrolling the active viewport still
updates every other viewport's line, and scrolling a target still moves its own
line, because the target's slice rectangle is what moved.

## 6. Guard tests

`tests/code/viewer/test_reference_line_active_viewport.py` — 17 tests, driven
through the public `manage_reference_line()` entry point, not the internals:

| Test | What it pins |
|---|---|
| `test_two_up_layout_draws_exactly_one_line` | the reported case, exactly |
| `test_three_up_still_leaves_the_active_one_clean` | scales past 2-up |
| **`test_the_active_overlay_is_actively_cleared`** | **load-bearing** — a line drawn while inactive must vanish when the viewport becomes active, and the overlay must be *cleared*, not skipped |
| `test_switching_the_active_viewport_moves_the_line` | the clean viewport follows selection |
| `test_env_flag_restores_the_line_on_the_active_viewport` | the way back, end-to-end |
| `test_anything_but_an_explicit_yes_keeps_the_active_one_clean` | 7 params |
| `test_single_viewport_layout_draws_nothing`, `test_no_selection_is_survivable`, `test_repaint_true_updates_the_target_widgets`, `test_a_target_without_geometry_is_cleared_not_crashed` | things that must not have broken |

Two existing tests in `test_reference_lines_all_pairs.py` pinned the *old*
default and were **re-pointed, not deleted** — `test_all_pairs_is_OFF_by_default`
now pins the new default, and `test_round_robin_targets_include_every_viewport`
sets the env explicitly so it still covers all-pairs. A new
`test_all_pairs_can_be_switched_back_on` (6 params) covers the enable
vocabulary.

**Verified to fail on the pre-fix codebase**: with the old default restored,
**8 fail**, including every load-bearing one.

## 7. Regression run

`pytest tests/code/viewer tests/code/fast` → **2396 passed, 28 skipped,
54 xfailed, 2 xpassed, 0 failed**. The xfail/xpass set is the pre-existing
quarantine, unchanged.

## 8. To see it

The running app predates this change and must be restarted. Then open the same
study 2-up: the active series should be clean, and the line should appear only
on the other one — and should jump to the other viewport when you click across.

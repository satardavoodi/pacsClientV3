# Eagle Eye — MLO / CC image mixing (MG-PAIR-1)

**Date:** 2026-08-04
**Traced patient:** PID 52795 (poorjahani zahra, 62y)
**Study:** `2.16.840.1.113669.632.20.20260802.113626638.6.18` (study_pk 2253)
**Status:** Root cause proven, fix applied, tests green.

---

## 1. Reported symptoms

1. The MLO layout showed a slice counter of **`1 / 2`** even though the view is a
   single mammography image.
2. **Scrolling inside the MLO layout displayed the CC image.**
3. (Separate issue, see §7) The `Advanced` / `Show / Hide Box` controls at the top
   of each layout appeared duplicated and overlapping.

---

## 2. The data is clean — the defect is in the viewer

Disk + DB probe of study_pk 2253:

```
SERIES num=2      mod='MG'  imgs=1  desc='R-CC'      series_name=None   ON DISK: 1 .dcm
SERIES num=4      mod='MG'  imgs=1  desc='L-CC'      series_name=None   ON DISK: 1 .dcm
SERIES num=6      mod='MG'  imgs=1  desc='R-MLO'     series_name=None   ON DISK: 1 .dcm
SERIES num=8      mod='MG'  imgs=1  desc='L-MLO'     series_name=None   ON DISK: 1 .dcm
SERIES num=100000 mod='DOC' imgs=1  desc='Documents' series_name=None
```

Four MG series, **one image each**, distinct Series UIDs, distinct SOP Instance
UIDs, distinct descriptions. Nothing in the DICOM data groups MLO with CC.
Series grouping, view-position metadata and SOP/Series-UID grouping are all
correct — so the fault is downstream, in the viewer's *paired-series* logic.

---

## 3. Root cause — `str(None)` is the truthy literal `'None'`

The `series` table stores `series_name` as **NULL** for these rows.
`image_io.load_series_preview()` loads series metadata DB-first via
`get_series_by_series_pk()` (image_io.py:3573), so `metadata['series']['series_name']`
is `None` at runtime — the key is *present* with a `None` value.

Every paired-series call site read it as:

```python
series_name = str(series_info.get('series_name', ''))
```

`str(None)` is the **string** `'None'`, which is **truthy**. Consequences:

**a) The index builder created one shared bucket.**
`ViewerController._rebuild_series_index()` (`_vc_backend.py:651`) guarded with
`if series_name:` — which `'None'` passes — so:

```python
_paired_series_map == {'None': ['2', '4', '6', '8']}
```

All four MG series landed in a single pairing bucket.

**b) The switch path then paired arbitrary views.**
`_vc_switch.py:1446` looked up `series_name in self._paired_series_map`
(`'None'` → hit), took **the first other number in the bucket**, and attached it
as `vtk_image_data_2`. The MG-modality gate did not help — all four *are* MG.

Confirmed in the user's own `viewer_diagnostics.log` (2026-08-04 18:09:57):

```
ViewerController._get_series_by_number_fast  cache_result=main_hit   ... series_number=2   <- R-CC fetched as the partner
[ADVANCED_SERIES_BIND] bind_source=switch_series_combined ... series_number=4              <- into the L-CC viewport
[SERIES SWITCH] START - Series #4 [MG] 'L-CC'
[SERIES SWITCH]   Index: 1, Combined: True
```

**c) The combined viewer turned the pair into a 2-slice stack.**
`_vw_series.py:1199` builds `CustomCombineImageViewers` whenever
`vtk_image_data_2 is not None`. In `modules/viewer/advanced/viewer_2d.py`:

- `get_count_of_slices()` returns `Z1 + Z2` = `1 + 1` = **2** → the `1 / 2` counter.
- `set_slice(1)` falls into the `else` branch → `change_local_series('series_2')`
  → rebinds reslice + metadata to the partner series → **scrolling shows the CC image**.

Three ungated equality sites had the same defect via a different route
(`None == None` / `'None' == 'None'` both evaluate True):

| File | Line | Expression |
|---|---|---|
| `_vc_layout.py` | 757 | `if series_name_2 == series_name:` |
| `_pw_viewers.py` | 397 | `if series_name_2 == series_name:` |
| `_pw_series.py` | 150, 692 | `... ['series_name'] == series_name` |

---

## 4. The fix (MG-PAIR-1)

New shared helper `PacsClient/utils/series_pairing.py`:

- `normalize_series_name(value)` — collapses `None`, `'None'`, `''`, whitespace,
  `'null'`, `'nan'`, `'unknown'`, `'n/a'`, `'-'` to `''` ("no pairing key").
- `can_pair_series_names(a, b)` — True **only** when both carry the *same
  non-empty, real* series name. Replaces the bare `==` checks.
- `pairing_guard_enabled()` — kill switch, guard ON by default.

Applied at six sites:

| File | Change |
|---|---|
| `_vc_backend.py` | pairing key normalised; the flat metadata cache keeps the raw value |
| `_vc_switch.py` | `series_pair_key` used for the map lookup; raw name kept for logging |
| `_vc_warmup.py` | same as `_vc_switch` (first-display path) |
| `_vc_layout.py` | `==` → `can_pair_series_names(...)` |
| `_pw_viewers.py` | `==` → `can_pair_series_names(...)` (legacy path) |
| `_pw_series.py` | `==` → `can_pair_series_names(...)` ×2 (legacy paths) |

**Behaviour preserved:** studies whose series rows *do* carry a real shared
`series_name` still pair and still open the combined viewer exactly as before.
The MG-modality gate, `allow_paired`, the flat metadata cache and the
`_series_number_to_index` fast lookup are all untouched.

### Kill switch

```
AIPACS_DISABLE_SERIES_NAME_PAIRING_GUARD=1
```

Restores the exact pre-fix behaviour (including `str(None) -> 'None'`) without a
code change. Default is OFF (guard active).

---

## 5. Verification

**End-to-end, against the live database** (`_recovery/probe_pair_map_52795.py`):

```
[GUARD ON  (fixed)]  _paired_series_map = {}
[GUARD ON  (fixed)]  _series_number_to_index = {'2': 0, '4': 1, '6': 2, '8': 3}

[GUARD OFF (legacy)] _paired_series_map = {'None': ['2', '4', '6', '8']}
[GUARD OFF (legacy)] _series_number_to_index = {'2': 0, '4': 1, '6': 2, '8': 3}

RESULT: PASS - no MG series can pair on a NULL name
```

The legacy run reproduces the defect exactly, which proves both the diagnosis
and that the kill switch is a genuine revert path.

**Tests:** `tests/code/viewer/test_mg_series_pairing_guard.py` — 33 tests, all pass.
Covers the placeholder set, the `str(None)` regression, genuine names still
pairing, the untouched flat cache and fast index, and the kill switch
reproducing the original bad bucket.

**Regression:** `tests/code/viewer` — **2099 passed**, 28 skipped, 51 xfailed.
`tests/code/ui_services` — 707 passed, 2 failed; both failures are the
**pre-existing** stale positional-guard tests
(`test_login_carries_the_user_identity_ids`,
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute`), unrelated to
this change and previously proven pre-existing against `git show HEAD`.

---

## 6. Live check to run in the app

1. Open PID 52795 in Eagle Eye.
2. The MLO layout must show **`1 / 1`**, not `1 / 2`.
3. Scrolling / mouse-wheel in the MLO layout must **never** show the CC image.
4. The CC layout must likewise stay on its own image.
5. Confirm `viewer_diagnostics.log` shows `Combined: False` and
   `bind_source=switch_series` (not `switch_series_combined`) for series 4 and 6.
6. Regression check on a study that legitimately uses paired MG series — the
   combined viewer must still open there.

---

## 7. Issue 1 — duplicate `Advanced` / `Show / Hide Box` controls: NOT yet root-caused

This is being tracked as a **separate** defect. What has been **ruled out**:

- **Duplicate widget creation.** `_create_boxes_toggle_button()`
  (`modules/ai_imaging/.../overrides/vtk_widget.py:1685`) is the only creation
  site in the whole codebase, and is called exactly once per `AIVTKWidget`
  (`__init__`, line 204, gated on `type_viewer != fixed_viewer`).
- **Repeated signal connections.** The badge (`_backend_badge`) and the toggle
  (`_boxes_toggle_btn`) are single instances; `_update_backend_badge` and
  `_position_boxes_toggle_button` only `setText` / `move` / `raise_` them.
- **Lesion count triggering another toolbar.** There is no per-lesion toolbar
  code; `"Hide Boxes"` / `"Show Boxes"` appears at exactly one creation site.
- **The combined-viewer path adding a second overlay set.**
  `CustomCombineImageViewers` *subclasses* `ImageViewer2D` (one renderer, one
  overlay set); `change_local_series()` swaps the reslice and metadata and does
  not add actors.
- **Stacked `AIVTKWidget`s in the captured session.** Log analysis of
  2026-08-04 18:09–18:11 found only **two** viewer ids (0 and 1), with viewer 1
  legitimately rebinding series 4 then 6 — i.e. reuse, not duplication.

**Remaining hypothesis:** layout reinitialisation leaving an orphaned previous
widget parented at the same geometry — the one item from the original checklist
not yet excluded. The captured log window does not cover a layout rebuild, so
reproducing it needs either a fresh log taken at the moment the duplicate
appears, or a screenshot-time widget-tree dump.

**Note:** because the combined viewer is what made this study render abnormally,
re-check Issue 1 after the MG-PAIR-1 fix is live — the duplicate may not
reproduce once the MLO/CC viewports stop being combined.

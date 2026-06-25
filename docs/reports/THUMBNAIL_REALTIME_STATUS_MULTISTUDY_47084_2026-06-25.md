# Real-time thumbnail download status broken for multi-study patients (47084) — 2026-06-25

## Symptom (reported)
On patient **47084** the side-panel thumbnail border did not turn "ready" in real time
as series finished downloading. Completed series appeared only after switching tabs /
navigating away and back. Reported as a regression "after the unified-pipeline changes."

## Investigation (the 7 requested areas)

1. **Download progress event** — `DownloadManagerWidget` emits `seriesDownloadStarted` /
   `seriesProgressUpdated` / `seriesDownloadCompleted` `(study_uid, series_uid, …)`. Fine.
2. **Series-level completion event** — `seriesDownloadCompleted` fires per series. Fine.
3. **Thumbnail model/status update** — `thumbnail_manager.start_series_download` /
   `complete_series_download` set the projection state + `ready_series` and repaint via
   `apply_border_states_new`. Verified firing **in real time** on the live app
   (`[FAST-THUMB-STATE] state=downloading … state=completed` ~1 s apart, 76/76 balanced)
   **for single-study patients**.
4. **UI binding / signal** — the DM→widget bridge is
   `HomeDownloadService.connect_dm_to_widget(dm, widget, study_uid)`
   (`PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`).
5. **Border refresh** — `apply_border_states_new` repaints; not the root cause here.
6. **Tab visibility** — the apparent "only after tab switch" is the *secondary effect*:
   a tab-switch rebuild replays state from disk, which is why it eventually appeared.
7. **Unified-pipeline change** — this is the regression vector (offset-key multi-study).

## Root cause (confirmed)

**47084 is a multi-study patient** (live: `is_multistudy: true`; thumbnails keyed by
multi-study **offset/display keys** — `orig_series_number` 203/202 with a duplicate 203 =
two studies).

`connect_dm_to_widget` is called **once per opened (primary) `study_uid`**
(`_hp_download.py:413`). Every bridge handler hard-returns on `uid != study_uid`:

```python
def on_series_started(uid, series_uid, series_desc):
    if uid != study_uid:
        return          # <-- secondary study dropped
def on_series_completed(uid, series_uid):
    if uid != study_uid or not widget_ref():
        return          # <-- secondary study dropped
```

So for a multi-study patient the **secondary study's** series-download events are dropped
entirely → those thumbnails never get a real-time `start_series_download` /
`complete_series_download`. They only correct themselves when a tab-switch rebuild replays
state from disk. **Single-study patients are unaffected** (`uid` always == `study_uid`),
which is why the live single-study run showed perfect real-time updates.

The resolution machinery was already correct: `_resolve_sn(series_uid)` maps a
globally-unique `series_uid` → the thumbnail's **offset/display key** via
`_series_uid_to_number` (`_pw_thumbnails.py:197/211`). The events were simply never
admitted. This is the same class as the 46970 progressive-bind / 46713 disk-ready bugs:
the DM keys by bare/resolved number + per-study `study_uid`, the multi-study UI keys by
offset/display key.

## Fix (minimal, flag-gated, no duplicate download logic)

`home_download_service.py` (NOT plugin-mirrored). Flag
`AIPACS_THUMB_SIBLING_STUDY_STATUS` (default **on**; `=0` = byte-identical legacy filter).

When a series event's `uid != study_uid`, **admit it into the THUMBNAIL lane only** if its
`series_uid` resolves to a thumbnail already shown for **this** multi-study patient:

- `_belongs_to_open_thumbnails(series_uid)` — admission gate. True only when the patient is
  multi-study **and** `series_uid` is in **this patient's** `_series_uid_to_number` map
  (built solely from this patient's `server_series_info`). A foreign patient's UID can never
  resolve here → **cross-patient isolation preserved** (the highest-severity invariant).
- `_project_sibling_thumbnail(uid, series_uid, completed)` — resolves the offset/display key
  via `_resolve_sn` and calls **only** `start_series_download` / `complete_series_download`.
  It performs **no** `series_downloaded` emit, **no** viewport progress, **no** load trigger
  — so it cannot start an unwanted viewer load for a series the user did not open.
- `on_series_started` / `on_series_completed` call the projection just before their existing
  `return`. The **primary** path is byte-unchanged. The viewport/progress/`series_downloaded`
  lanes stay primary-study-only (the deferred "bridge secondary progress" enhancement).

Result: a multi-study secondary series turns **downloading** on start and **ready** on
complete **in real time**, at its own offset-key thumbnail, with no tab switch.

## Two viewers
The thumbnail panel + `thumbnail_manager` are **backend-agnostic** (shared by FAST/pydicom
and Advanced/VTK), so this single fix covers both backends.

## Tests
`tests/code/ui_services/test_thumb_sibling_study_status.py` — 7 green (functional, real Qt
fake-DM emitting the actual signals):
- sibling completion/start route to the **offset/display key**;
- the sibling path emits **no** signals (no viewer-load trigger);
- an unknown/foreign UID is **rejected** (cross-patient safe);
- the **primary** path still completes;
- the **kill switch** restores the legacy filter.
Full `tests/code/ui_services` suite: 185 passed (2 pre-existing, unrelated `test_pin_overlay`
source-pin failures — `patient_table_widget.py`, untouched here).

## Known limitations / honest staging
- **Progress ring/count** for a secondary study (the intermediate "n/N") is still
  primary-study-only — only the **border state** (downloading→ready) is now real-time for
  siblings. Full secondary-study progress bridging is the separate deferred enhancement
  noted in the 46970/46713 records.
- **Failed → red border**: there is still no DM→thumbnail *failure* signal wired (the
  architecture review's "true download-FAILURE error needs a real DM failure signal
  (future)"). The fix does not fabricate one.
- **NEEDS live source-build verify** with a **fresh** (not-yet-downloaded) multi-study
  patient: open it, watch each secondary-study thumbnail turn ready in real time. (47084 is
  already fully cached, so re-opening cannot re-exercise the real-time transition.)

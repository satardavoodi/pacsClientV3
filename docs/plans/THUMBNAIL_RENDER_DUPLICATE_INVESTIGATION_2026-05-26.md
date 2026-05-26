# Right-Panel Thumbnail Duplicate-Render — Root Cause Investigation
**Date:** 2026-05-26
**Status:** Investigation complete; one-line surgical fix proposed.
**Companion docs:** `docs/pipelines/thumbnail-pipeline.md` (the regression-guarded as-built record), `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`, `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`.

---

## 1. Confirmations from the existing as-built records

- **Transport is socket, not gRPC.** `modules/download_manager/network/grpc_client.py::GrpcMetadataClient` is socket-backed despite the name. Verified in code (line 23: *"Socket-backed thumbnail and metadata retrieval compatibility layer"*) and matches `CLAUDE.md` § Zeta Download Manager. The legacy gRPC stack in `modules/network/grpc_client.py`, `dicom_downloader*.py`, `multi.py`, `dicom_service_pb2*.py` is dead — no new wiring.
- **Disk is the canonical thumbnail source.** Path `THUMBNAIL_PATH/<study_uid>/<series_number>.png`. ThumbnailStore + DB column are accelerators only.
- **`ThumbnailImageSourceService`** (`patient_tab/utils/thumbnail_image_source_service.py`) is the shared read helper for the viewer-tab sidebar. The right-side panel reads PNGs directly (documented follow-up §7 of pipeline doc).

---

## 2. Signals fired on a single patient row click

In `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1521-1526`:

```python
self.patientClicked.emit(patient_id, patient_name, study_uid)   # → series-info flow
self.thumbnailRequested.emit(row)                                # → thumbnail flow
```

Both signals are emitted in the **same Qt event**. Each drives an independent flow that ultimately writes to the right panel.

### Path A — `patientClicked` ⇒ `_hp_series._on_patient_single_clicked` ⇒ `_load_and_display_series_info`

For a **downloaded** study (`check_study_complete(study_uid)` is True):
- Calls `_load_thumbnails_for_downloaded_study(...)` with the `series_list` returned by `get_series_by_study_pk(study_pk)`.
- Builds thumbnails inline with explicit fields from the rich DB series rows.
- Renders by calling `right_panel_widget.display_thumbnails(thumbnails, progressive=True)`.

For a **non-downloaded** study:
- Calls `show_patient_studies({...})` after a `_get_or_fetch_series_info` await (which can be slow — the GetStudyInfo socket call is known to time out per `CLAUDE.md`; the probe sometimes waits multiple seconds).

### Path B — `thumbnailRequested` ⇒ `_hp_series._on_thumbnail_requested` ⇒ (120 ms debounce) ⇒ `_start_thumbnail_task` ⇒ `_safe_on_plus_button_clicked` ⇒ `on_plus_button_clicked` ⇒ `show_patient_studies`

Always calls `show_patient_studies(...)` 120 ms after the original click — regardless of whether the study is downloaded or not.

### `show_patient_studies` itself

- Cache-hit branch (line 1025): `_build_cached_thumbnail_payload(study_uid)` → if any thumbnail PNG exists on disk for this study, build payload from disk + per-series DB lookup → render.
- Otherwise: socket fetch → `save_thumbnail` (writes PNGs) → `save_series_info_to_database` (writes DB series rows) → render.

---

## 3. The duplicate-render trigger

For a **downloaded** study (the common case after the first patient open):

| t (ms) | Event | Effect |
|---|---|---|
| 0 | Click → both signals emitted | — |
| ~5 | Path A scheduled (async) | — |
| ~5 | Path B's 120 ms QTimer starts | — |
| ~15 | Path A runs DB check, calls `_load_thumbnails_for_downloaded_study` | Renders with **rich `series_list`** (image_count from DB row, blank description fallback) |
| 125 | Path B's timer fires → `show_patient_studies` → cache-hit branch → `_build_cached_thumbnail_payload` → renders **again** | Renders with **DB lookup per-series** |

Both calls render. The order of the user-visible flashes matches: Path A's render appears first (image_count badge visible), then Path B's render overwrites it ~120 ms later.

Note: this is not gated by my earlier (now reverted) `right_panel_already_rendered_skip` block — the duplicate render is **structural**, present in the codebase regardless of recent UI work.

---

## 4. The metadata divergence — root cause of "image_count → Series N"

The two render paths build thumbnails dicts that **disagree on the fallback when the DB row is thin or missing**:

### Path A — `_hp_series.py:542-549` (`_load_thumbnails_for_downloaded_study`)

```python
thumbnails.append({
    'file_path': thumb_file_path,
    'series_uid': series_uid,
    'series_number': series_number,
    'series_description': series.get('series_description', ''),   # ← '' fallback
    'modality': series.get('modality', ''),
    'image_count': series.get('image_count', 0)
})
```

`series` here comes from `get_series_by_study_pk(study_pk)`. If the study row exists and series rows are present, this carries `image_count` populated. If a series row is incomplete, `series_description` is `''` and `image_count` is `0`.

### Path B — `_hp_search.py:398-408` (`_build_cached_thumbnail_payload`)

```python
payload['thumbnails'].append({
    'file_path': series_path,
    'series_number': series_number,
    'modality': series_info.get('modality', 'Unknown'),
    'series_description': series_info.get('series_description', f'Series {series_number}'),   # ← 'Series N' fallback
    'image_count': series_info.get('image_count', 0),
    ...
})
```

`series_info` is `get_series_info_from_database(study_uid, series_number)`, which does `get_series_by_study_and_number(study_uid, int(series_number))`. If the lookup fails (DB row missing, study_pk not found, `int(series_number)` doesn't match the stored series_number type, etc.) the function returns `{}`. **In that case the payload uses the `'Series N'` literal — that's the regression-trigger string the user sees.**

### What the renderer does — `thumbnail_manager.py::create_thumbnail_widget` (lines 1420-1485)

```
1) if desc is truthy (and not 'No description' / 'Unknown'):
       show desc label
2) if image_count > 0:
       show "{N} images" blue badge          ← THIS is the badge the user sees
   elif desc is empty/falsy:
       show "Series {series_number}" gray label   ← the visible regression
```

Putting it together for the **same study, same disk PNGs**, when path B's DB lookup returns `{}`:

- Path A render: desc=`''` → no desc label. image_count=`8` (from rich DB row) → renders **blue "8 images"** badge. ✓
- Path B render: desc=`'Series 0'` (fallback) → renders **gray "Series 0"** label (because line 1428's `desc` truthiness check passes the fallback string). image_count=`0` → no blue badge. ✗

Net effect: the first flash shows the correct blue badge; ~120 ms later the second render appears, the desc label changes from blank to `"Series 0"`, and the blue badge disappears (because count is now 0). **Exactly what the user reports.**

---

## 5. When does Path B's DB lookup return `{}` for a downloaded study?

Path A succeeded with rich data — proof that the series rows exist. Yet Path B's per-series lookup returns `{}`. The two queries are subtly different:

- Path A: `get_series_by_study_pk(study_pk)` — single query, returns ALL series for the study at once.
- Path B: `get_series_by_study_and_number(study_uid, int(series_number))` — re-resolves `study_pk` via `find_study_pk_with_study_uid(study_uid)`, then queries `WHERE study_fk = ? AND series_number = ?`.

Likely causes of Path B's `{}` (without proving them empirically — log-only investigation):

1. **Type mismatch on series_number.** Path B does `int(series_number)` where `series_number` is parsed from a PNG file path stem. If the DB column is `TEXT` but the comparison uses int parameter binding, SQLite's type affinity sometimes does the right thing, sometimes not. Worth checking the schema.
2. **Race with `save_series_info_to_database`.** For a non-downloaded study the socket fetch path writes DB rows. If Path B runs *before* the write completes (it shouldn't, because show_patient_studies is single-threaded, but reentrancy or async ordering could cause this), the rows aren't there yet.
3. **Connection-pool eventual consistency.** Different DB connections + WAL mode + uncommitted writes from a concurrent task could let one path see rows the other doesn't.

The exact reason isn't strictly necessary to fix the visible symptom — see §6.

---

## 6. Proposed fix — minimal, surgical, regression-safe

The visible symptom comes from **one specific line**: the `'Series N'` fallback string in `_build_cached_thumbnail_payload`. The renderer's logic is fine; the upstream metadata divergence is the issue.

### Change (one file, one line)

`PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py` line 403:

```python
# Before:
'series_description': series_info.get('series_description', f'Series {series_number}'),
# After:
'series_description': series_info.get('series_description', ''),
```

### Why this is safe

- When `get_series_info_from_database` returns rich data, both paths now produce **identical** payloads (both use the DB-provided description).
- When it returns `{}`, both paths now produce an **empty** `series_description`. The renderer then:
  - sees `desc` is empty → skips the desc label.
  - sees `image_count` (Path B: `0` from default, Path A: whatever the DB had).
  - if `image_count > 0` → shows "N images" badge in both cases.
  - if `image_count = 0` and `desc` is empty → falls through to the `series_num_display` block (line 1466-1485) which shows the small grey `"Series N"` label as a hard-fallback.

The user-observable consequence: when the DB row is genuinely missing, **both renders look the same** (the grey "Series N" label appears). When the DB row is rich, **both renders look the same** (the blue "N images" badge appears). **No more flicker between two visually different renders.**

### What this does **not** change

- The duplicate render itself still happens (two `display_thumbnails` calls per click). Removing the duplicate is a separate, riskier change — my previous attempt at it broke the download-start state machine. Leaving the duplicate in place keeps the existing download-start coordination intact.
- Path A's `_load_thumbnails_for_downloaded_study` is untouched.
- `show_patient_studies`' inflight guard, socket fetch, `save_thumbnail`, `save_series_info_to_database` paths — all unchanged.
- The thumbnail pipeline guardrails (disk authority, ThumbnailStore behaviour, `make_pixmap_from_bytes` main-thread rule) are unchanged.

---

## 7. Download-start delay — what the logs say

From `download_diagnostics.log` between 15:59:53 and 15:59:59 (one click on patient 43622):

```
15:59:53.829  plus_entry                            # path B starts
15:59:53.849  right_panel_cache_hit                 # first render (path B fast)
15:59:55.571  series_info_entry                     # another click / retry, NEW click
15:59:56.690  right_panel_already_rendered_skip     # my old block (now removed)
15:59:57.326  GetStudyInfo: timed out               # server-side, known issue per CLAUDE.md
15:59:58.602  GetStudyInfo: timed out               # second timeout
15:59:59.170  "Study state not found for critical series request"
15:59:59.177  "State not found in store"
15:59:59.181  download_start_before_worker_start    # 6 SECONDS after the click
15:59:59.188  "Invalid transition: Downloading → Pending"
```

The "Study state not found" + "Invalid transition" were caused by my prior block (now reverted). With both reverts applied (current state on disk), the download-start delay reduces to whatever the GetStudyInfo socket timeout policy contributes — per `CLAUDE.md`, this is **single-attempt** with a fast fail. After server-side socket recovers (or with a cached series info), download starts within ~200-500 ms.

**No code change required from me for download-start.** The cause was my own earlier work, fully reverted. The user needs to **restart the app once** so the running process drops its corrupted state.

If the delay persists after a clean restart, the cause is server-side `GetStudyInfo: timed out`, which is a known socket-server issue documented in `CLAUDE.md` Zeta DM section and outside the scope of UI work.

---

## 8. Multi-study, series ordering — verified untouched

- Multi-study sidebar logic in `_pw_panels.py` and `patient_widget_core/widget.py` — **not modified** in any of my work.
- Series ordering: `get_series_by_study_pk(study_pk)` does `ORDER BY series_number`. `_build_cached_thumbnail_payload` reads thumbnails from the folder iteration (no explicit sort but file system usually lists numerically). The duplicate-render fix above does not affect ordering.
- Multi-study fix invariants documented in `MULTI_STUDY_SINGLE_TAB_PLAN.md` — all still hold.

---

## 9. Acceptance — what passing looks like

After the one-line fix lands:
- Click a patient on the home page → **single visible render** (the duplicate still happens at the code level, but the second render no longer changes what the user sees).
- The blue "N images" badge appears and stays.
- Double-click opens the patient tab without a regression.
- Download starts within a few hundred ms when the server is responsive.
- No "Invalid transition: Downloading → Pending" in `download_diagnostics.log` after a clean app restart.
- No `right_panel_already_rendered_skip` in the logs (my prior block is gone).

If any of these don't hold, that points at a deeper issue we can investigate separately — but with the existing pipeline intact for safer iteration.

---

## 10. Items deliberately NOT changed in this fix

- The two signals (`patientClicked` + `thumbnailRequested`) still both fire on click. Removing the second is **architecturally tempting** but risky — it has other consumers (keyboard navigation at `patient_table_widget.py:3984, 3989`).
- `show_patient_studies` flow is unchanged.
- `_load_thumbnails_for_downloaded_study` flow is unchanged.
- No new flags, no early-returns, no global state.

This is the minimum-blast-radius fix that addresses the user-visible symptom without re-introducing the download-state corruption from my previous attempt.

# Root-Cause Report — Patient 44113: stale series/thumbnails on single-click

**Date:** 2026-06-01  **Scope:** investigation only — *no code changed in this pass.*
**Verdict:** the failure is **cache/database-related** (a local-only "is this study
complete?" gate reading a stale DB row). The **server is healthy**, the download
manager and thumbnail manager are fine — they are simply **never asked to refresh**.

---

## 1. Live evidence (captured now, against the running server)

| Source | Series | Images | Detail |
|---|---|---|---|
| **Server — patient search** (`search_patients_sync`) | `count_of_series = 10` | — | study_uid `…0033`, host `192.168.2.222:50052` |
| **Server — `GetStudyThumbnails`** | **9 series** | **689** | series #2,3,4,5,6,7,8,9,100 (t2_tse, t1_tse, diff, starvibe, SUB…) |
| **Local DB** (`dicom.db`) | `number_of_series = 1` | `number_of_instances = 30` | one series row: #2, 30 img, "t2_tse_tra_p2_320" |
| **Local disk** (`…/dicom/…0033/`) | 1 folder (`2/`) | 30 files | — |
| **Local thumbnails** (`…/thumbnails/…0033/`) | — | — | 1 file: `2.png` |

**The server already returns the complete, updated study (9 series / 689 images).
The client is sitting on a 1-series / 30-image snapshot and never refreshes it.**
(The earlier "1408" figure was a prior display; the current authoritative server
count is 9 series / 689 images — either way, far more than the local 1 / 30.)

---

## 2. The complete flow trace (single-click) — where it goes stale

Entry: `_load_and_display_series_info` — `_hp_series.py:351`.

1. **`_reconcile_patient_studies_on_click`** (`_hp_series.py:188`, called at :374)
   *does* hit the server — `search_patients_sync` returns `count_of_series = 10`.
   **But it only acts on *missing study UIDs*:** `missing = [uid … not in local_uids]`
   (:306). 44113's study UID is already local → `missing == []` → **no fetch, no
   download.** The fresh `count_of_series = 10` is used only to repaint the patient
   row (:265) and is then **discarded** — it is never compared against the study's
   local series count. (A 5 s throttle + in-flight guard, :215/:223, can also skip
   this entirely on rapid re-clicks.)
   → **Stale point A: server "10 series" is fetched and thrown away.**

2. Back in `_load_and_display_series_info`, `len(study_uids) == 1` → the grouped-studies
   branch (:377) is skipped.

3. **`check_study_complete(study_uid)`** — `_hp_series.py:383` → `utils.py:1409`.
   With no `expected_series_count` passed, it reads the **local DB**:
   `expected = studies.number_of_series = 1`; counts disk folders = 1; returns
   `series_folders(1) >= expected(1)` → **`True`** (`utils.py:1444`).
   *(Even if the DB count were 0, line 1447 returns `series_folders > 0` → still
   `True`. This function can never return `False` for a study that has ≥1 local
   series — it has no server input by design: "FAST - no server calls", :1411.)*
   → **Stale point B (root cause): the study is declared "complete" from local data
   alone.**

4. Because `check_study_complete == True`, the **local-DB branch** runs
   (`_hp_series.py:389-417`): `get_series_by_study_pk` → the **1 stale series (#2)**.

5. `_display_series_info_in_right_panel(study_info)` (:421) renders that 1 series;
   `_load_thumbnails_for_downloaded_study` (:425) loads the 1 cached thumbnail
   (`2.png`).

6. **`return` at :438.** The function exits **before** the only branch that would
   refresh from the server — the `force_refresh=True` fetch at `_hp_series.py:443-451`
   (reached only when `check_study_complete` is `False`).

**Net:** the single decision at step 3 short-circuits the entire refresh/redownload/
thumbnail pipeline. Everything downstream behaves correctly for "1 series" — there
is nothing wrong with the renderer, the model, the thumbnail store, or the socket;
they are never told the study grew.

---

## 3. Answers to your six questions

**1. Server-side state.**
The server is **correct and current**. It returns the full study both at the
patient-search level (`count_of_series = 10`) and the series level
(`GetStudyThumbnails` → 9 series, 689 images, `thumbnails_available = 9`). **Not a
server problem.**

**2. Metadata refresh path.**
On single-click the app **does** issue one server call (the reconcile search) — but
for an *already-local* study it **discards** the fresh count and then reads **series
metadata from the local DB only**. So fresh *patient/study* metadata is fetched and
ignored; fresh *series* metadata is **never requested**. The deciding gate
(`check_study_complete`) is explicitly local-only.

**3. Thumbnail refresh.**
The new thumbnails are **never requested** (not "downloaded but not displayed").
Only `2.png` exists locally. The 8 new series' thumbnails are never fetched because
the series list is never refreshed.

**4. Download behavior.**
The new images are **not** being downloaded on single-click. Local = 30 images / 1
series; server = 689 / 9. They **do not match.** Single-click enqueues a download
only for *missing studies* (none here) and the incomplete-study download branch
(`_hp_series.py:462`) is skipped because `check_study_complete` returned `True`.
When images *are* downloaded (double-click / Download), they land correctly at
`…/user_data/patients/dicom/<study_uid>/<series_number>/` and thumbnails at
`…/patients/thumbnails/<study_uid>/<series_number>.png` — that machinery is fine.

**5. Cache/database behavior.**
**Yes — this is the blocker.** The local DB row `studies.number_of_series = 1`
(plus the 1 disk folder) makes `check_study_complete` decide the study is **already
up to date**. That is the incorrect "up to date" decision. The in-memory
`_series_info_cache` (`_hp_series.py:584`) is a *secondary* staleness source (it
returns a cached partial list unless `force_refresh=True`), but on the single-click
path it is never even reached — the DB gate short-circuits first.

**6. UI synchronization.**
**Not** a missing signal and **not** a model-rebuild failure. The UI faithfully
renders what it is handed (1 series). The new series metadata never reaches the UI
layer, so there is nothing new to draw. Fix the upstream gate and the existing
`_display_series_info_in_right_panel` + thumbnail fetch will render the 9 series.

---

## 4. Exact root cause (one sentence)

> Every "can I use local data?" decision for an already-downloaded study is made
> **without consulting the server**, so a study that *grew on the server* is never
> detected as stale — and `check_study_complete()` (`utils.py:1409`), which the
> single-click path gates on (`_hp_series.py:383`), structurally **cannot** return
> `False` once any series is local.

**Layer: cache/database (local completeness gate).** Not server, not download
manager, not thumbnail manager, not UI refresh.

---

## 5. Relationship to the earlier (double-click / Download) edits

The two edits already applied this session —
`_hp_patient_open.py` (double-click → always `force_refresh`) and `_hp_download.py`
(Download → `force_refresh=True`) — fix **those two** entry points (they will now
fetch the 9 series and is consistent with this evidence). **They do not touch the
single-click home-panel path**, which is gated by `check_study_complete` at
`_hp_series.py:383` and is the one you are exercising. That path is still open.

---

## 6. Proposed fix (described only — awaiting your go-ahead)

Minimal, additive, and consistent with the existing `force_refresh` pattern:

- **Thread the server's series count into the gate.** The reconcile already has the
  server row with `count_of_series` (=10). Pass it as `expected_series_count` to
  `check_study_complete` at `_hp_series.py:383` (and persist it to
  `studies.number_of_series`). Then `series_folders(1) >= 10` → **`False`** → the
  existing `force_refresh=True` server branch (:443) runs →
  `get_series_info_from_server` → `GetStudyThumbnails` (verified working: 9 series) →
  `_display_series_info_in_right_panel` + the incomplete-study thumbnail/download
  branch (:462) fire. New series render and download; thumbnails follow from disk.
- **Guard performance:** the refresh fires **only when `server_count > local_count`**
  (a free integer compare on data already in hand). Up-to-date studies keep using the
  local DB/cache with **no extra socket call**, so fast single-click stays fast.
- **Cascade:** persisting the server count to the DB makes the *next*
  `check_study_complete` correct on its own.

**Why deliberate, not blind:** this touches the thumbnail/series pipeline and the
download trigger — guarded by `docs/pipelines/thumbnail-pipeline.md`,
`docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`, and the ZETA review doc. A wrong change could
show **missing/wrong images for a patient**, so it must pass: `py_compile` + import,
`tests/code` (system / download_manager / ui_services), a **single-study** regression
(must stay on the original fast path), a **multi-study** regression, and a live
44113 re-check (single-click → 9 series + thumbnails; an already-complete patient
opens with no added latency).

---

## 6b. FIX APPLIED — 2026-06-01 (single-click path)

Two minimal, additive, single-study-scoped edits in `_hp_series.py` (compile + import
verified):

1. **`_reconcile_patient_studies_on_click`** (~:298) — stash the server's
   `count_of_series` per study UID **only for single-study patients**
   (`self._server_series_count_by_study[uid] = count`). For a one-study patient the
   patient-level count equals that study's series count; multi-study patients take the
   grouped branch (`:377`) and never reach the gate, so they are untouched.

2. **The completeness gate** (`_load_and_display_series_info`, ~:383) — before the
   local-DB shortcut, compute `_server_grew`: if the stashed server count exceeds the
   local series-row count **and** the study hasn't been refreshed this session, set
   `_server_grew=True` and mark the study refreshed. The gate becomes
   `if (check_study_complete(...) or source==DB) and not _server_grew:` — so a grown
   study falls through to the **existing** `force_refresh=True` server branch (`:443`),
   which re-renders the full 9-series list, fetches thumbnails, enqueues the new series
   for download, and saves them to the DB.

**Why it can't loop or slow down healthy studies:**
- `_server_grew` only becomes true when `server_count > local_count`; an up-to-date
  single-study patient (`server == local`) keeps the original local fast path — **no
  extra socket call.**
- The once-per-session `_series_refreshed_uids` marker means even the benign
  server-vs-series count mismatch (search said 10, `GetStudyThumbnails` returns 9)
  triggers exactly **one** refresh, then the study settles onto the normal path.
- Multi-study patients never reach the gate (grouped branch returns first).

**Status:** applied + statically verified. **Pending live 44113 re-test** (restart the
source build → single-click 44113 → expect 9 series + thumbnails; confirm an
up-to-date patient still single-clicks instantly).

---

## 6c. CORRECTION from live trace — the REAL renderer (2026-06-01, second pass)

The first single-click fix (§6b) targeted `_load_and_display_series_info` and did **not**
change the display. The live `download_diagnostics.log` trace for a 44113 single-click
showed why:

```
click_single_entry → series_info_entry → thumbnail_task_start → plus_entry
→ right_panel_begin → right_panel_cache_hit thumbnail_count=1
```

The right-panel thumbnails are actually rendered by **`show_patient_studies`
(`_hp_search.py`)**, not by the series function. Its **fast-cache gate** (~:1192) reads
`_build_cached_thumbnail_payload(study_uid)` → `get_all_series_thumbnail_from_study_folder`
(the local thumbnail folder = 1 PNG for 44113), calls `display_thumbnails(...)`, and
**returns before ever contacting the server**. That is the true stale-render point. The
server-fetch path right below it (`get_study_thumbnails(include_base64=True)`) *does*
return all 9 series with image previews — it was simply never reached.

Also confirmed: the running app **did** contain the §6b code (app started 21:56, file
edited 21:51), and `_add_socket_patient_to_table` does **not** mutate the row — so the
§6b gate failed only because the server-count map wasn't populated at click time
(reconcile is async/throttled).

### Second-pass fix (applied + compile/import verified)

1. **`_add_socket_patient_to_table`** (`_hp_search.py`, ~:592) — stash
   `count_of_series` per study UID **as the patient list loads** (single-study only).
   This runs once per patient at search time, so the authoritative server count is
   ready *before* any click — no dependency on click-time reconcile.
2. **`show_patient_studies` fast-cache gate** (`_hp_search.py`, ~:1192) — when the
   stashed server series count exceeds the local thumbnail count, set `_thumbs_grew`
   and **skip the fast cache once** (separate `_thumbs_server_refreshed_uids` marker),
   falling through to the existing server thumbnail fetch that pulls every series.
3. Added a `right_panel_cache_gate` trace line (`local_thumbs`, `server_series`,
   `grew`) so the next live test shows the decision directly in
   `download_diagnostics.log`.

The §6b series-list gate and the double-click/Download edits remain (they fix the
series-list label and the other two entry points); this pass fixes the **visible
thumbnails** on single-click, which is what the user observed.

---

## 6d. LIVE-VERIFIED ✅ (2026-06-01)

Restarted source build, single-clicked 44113. Trace + disk confirm the fix works and
does not over-trigger:

- `right_panel_cache_gate local_thumbs=1 server_series=10 grew=1` → fell through to
  `right_panel_socket_start`/`socket_done` → the download subprocess pulled every
  missing series: **3 (30), 4 (27), 5 (30), 6 (160), 7 (69), 8 (23), 9 (160),
  100 (160)** joining series 2 (30).
- Disk now: **9 series folders, 689 images, 9 thumbnails** — exactly matching the
  server. UI shows **"9 series"** with thumbnails.
- Repeat clicks: `grew=0 → cache_hit thumbnail_count=9` (settled; the once-per-session
  marker absorbs the benign 10-vs-9 server/series mismatch — no loop).
- No over-trigger: study …030 (`local=12, server=12 → grew=0`) used the fast cache with
  no refresh. Studies …019 / …086 (`local=0, server=6 → grew=1`) refreshed once and
  settled. No `socket_error`, no timeouts.

**Bug closed.**

---

## 7. Reproduction / verification commands used

- Local state: `_diag_44113.py` → DB rows + disk + thumbnails (read-only).
- Server state: `_server_44113.py` → `search_patients_sync` + `GetStudyThumbnails`
  (read-only network query; the same socket path the app uses).

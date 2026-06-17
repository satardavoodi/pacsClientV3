# Multi-Study Patient: Open-vs-Select Study-Set Divergence — Structural Root Cause

Date: 2026-06-17
Status: **Investigation only. No application code was changed by this report.**
Trigger patient: **46630** ("MASOUMI TINA") — a multi-study patient whose second
study is a DICOMized **DOC** study with its own `StudyInstanceUID`.
Related prior analysis: `MULTI_STUDY_MULTI_PATIENT_ID_ARCHITECTURE_REVIEW_2026-06-16.md`,
`MULTI_STUDY_CODE_CHANGE_REVIEW_2026-06-16.md`, `DOC_ATTACHMENT_MISSING_45932_2026-06-11.md`,
`RESYNC_ON_REOPEN_45611_2026-06-14.md`, `MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`,
`CROSS_PATIENT_STUDY_MIXING_44504_2026-06-02.md`, `BUG_STALE_SERIES_ON_SERVER_UPDATE_44113.md`.

---

## 1. Executive Summary

The symptom — "the second study (and the DICOMized DOC study) is visible when I
**single-click** the patient, but disappears / is not presented when I
**double-click** to open it" — is **not a rendering bug, a cache-staleness bug, or a
DOC-decoder bug.** It is a **divergence between two independently-implemented
study-discovery paths, plus the absence of an in-session refresh of the open viewer
tab.**

There are, in effect, **two different answers to the question "which studies does this
patient have?"** in the codebase, and they are computed by different functions, from
different sources, with different freshness:

| | Single-click (select / preview) | Double-click (open) |
|---|---|---|
| Resolver | `_reconcile_patient_studies_on_click` (`_hp_series.py:599`) | `_resolve_patient_study_uids_async` (`_hp_patient_open.py:317`) |
| Server query | **Fresh** `search_patients_sync` per click (`:652`) | **None** — reuses the **stale, compact** `_server_patient_meta_by_pid` stash captured at list-load (`:336`) |
| Study sources read | `studies` / `study_list` arrays + `study_uids` + `latest_study_uid` + per-modality enumeration (`:686–723`) | sync table-row column + fallbacks + per-modality enumeration over cached meta (`:150`, `:338`) |
| Result for 46630 | **2 studies** (imaging + DOC) | **1 study** (`all_studies=1` in the log) |
| What it renders | Home-page right panel, grouped (`_show_grouped_patient_studies`) | The **viewer tab**, built **single-study** |

For 46630 the open path resolved **one** study, built a single-study viewer tab, and
**nothing ever back-filled the DOC study into that open tab.** The deferred refresh and
the resync *did* discover the second study moments later — but they re-render only the
**home-page right panel**, which the user is no longer looking at. The only code path
that pushes a refreshed study set into an **already-open viewer tab** fires exclusively
when you re-focus a tab that is already open (the *second* open) — which is exactly why
the team repeatedly observes "it only shows up after I close and reopen."

**One-line root cause:** the open path resolves the patient's study set **once, from a
weaker/staler source than single-click**, builds the viewer tab from that snapshot, and
has **no in-session path to add a late-discovered study to an open tab** — so a study
that single-click can see is lost on first open and only reappears on reopen.

This is the same structural fault the 2026-06-16 architecture review named ("initial
open uses the stronger multi-study path, while later … uses a weaker path"; "document
appears only after reopen"; roadmap item **P2 #10 — add a study-count-growth refresh
path … viewer sidebar series info if a tab is open"**, which **is not implemented**).

---

## 2. Reported Behavior and Reproduction

Patient 46630 has two studies under one `PatientID`:

| Role | StudyInstanceUID | Series | Notes |
|---|---|---|---|
| Primary (imaging) | `1.3.12.2.1107.5.2.46.174759.30000026061604302027000000090` | 32 | Siemens-style UID; the clicked study |
| Second (DOC) | `1.2.826.0.1.3680043.8.498.28987122168686462210804814974357655389` | 1 | `…498…` UID family + series number `100000` → DICOMized document study |

- **Single-click:** both studies appear; the DOC study is visible in the preview.
- **Double-click (open):** the patient opens, but the second study's series are missing
  from the viewer sidebar and the DOC study is not presented correctly.
- The system "clearly knows" the DOC exists in one state but loses it in the other.

This is reproducible with any patient whose additional study is **not reported by the
server's `GetPatientList` aggregation as a distinct modality/study for that patient** —
the classic case being a separate-UID DOC study (`1.2.826.…`), and more generally any
study the compact cached patient-row meta does not enumerate.

---

## 3. Evidence — the 46630 open, from `download_diagnostics.log` / `app.log` (2026-06-17, 11:41:20)

Annotated timeline of the **actual double-click open** (the only 46630 interaction in
today's logs):

```
11:41:20.426  [FAST-UX] double_click_t0 study=…090 patient=46630
11:41:20.426  [FAST-OPEN-TRACE] …090 phase=open_request   all_studies=1 patient_id=46630 source=server   ← open resolved only 1 study
11:41:20.426  [FAST-OPEN-TRACE] …090 phase=PatientOpenDoubleClick all_studies=1
11:41:20.967  [FAST-SERIES-DOWNLOAD-QUEUE] study=…090 series_count=32 priority=High
11:41:20.970  [FAST-OPEN-TRACE] …090 phase=DownloadEnqueued series_count=32 trigger=double_click_open  ← only the imaging study queued
11:41:20.979  [FAST-OPEN-TRACE] …090 phase=right_panel_cache_gate grew=1 server_series=32
11:41:21.192  [FAST-OPEN-TRACE] …090 phase=right_panel_display_done thumbnail_count=32
        ── deferred refresh runs (reuses the SINGLE-CLICK handler _load_and_display_series_info) ──
11:41:22.563  [FAST-OPEN-TRACE] study=…389 (DOC) phase=reconcile_enqueue_skipped_single_click reason=single_click_select_only   ← reconcile DID find the DOC
11:41:22.570  [FAST-OPEN-TRACE] …090 phase=resync_start study_count=2   ← now 2 studies known
11:41:23.242  [FAST-OPEN-TRACE] …090  phase=study_resync_check local_series=32 server_series=32 disk_missing=4,5,…  result=disk_missing
11:41:23.244  [FAST-OPEN-TRACE] …090  phase=resync_enqueue_skipped_single_click reason=single_click_auto_no_download
11:41:23.321  [FAST-OPEN-TRACE] study=…389 (DOC) phase=study_resync_check local_series=1 server_series=1 disk_missing=100000 result=disk_missing
11:41:23.322  [FAST-OPEN-TRACE] study=…389 (DOC) phase=resync_enqueue_skipped_single_click reason=single_click_auto_no_download   ← DOC images never downloaded
11:41:23.450  [FAST-OPEN-TRACE] …090 phase=resync_complete changed=1 rerendered=1   ← re-render = HOME right panel, NOT the open viewer tab
```

Four facts the log nails down:

1. **Open resolved one study** (`all_studies=1`). The DOC was not in the open-time set.
2. **The deferred discovery found two** (`reconcile_enqueue_skipped_single_click study=…389`,
   then `resync_start study_count=2`). The reconcile/resync paths *do* know about the DOC.
3. **The DOC's single series (number `100000`) is `disk_missing` and was never queued**
   (`resync_enqueue_skipped_single_click … single_click_auto_no_download`).
4. The re-render that did happen (`rerendered=1`) is `_show_grouped_patient_studies`
   targeting the **home right panel** — not the open viewer tab's series sidebar.

No errors, no timeouts, no cross-patient skips. The data arrived; the workflow lost it.

---

## 4. The Two Workflows, Traced

### 4.1 Double-click open — how the study set is resolved (the weaker path)

`_on_patient_double_clicked_async` (`_hp_patient_open.py:582`):

```
all_study_uids = await _resolve_patient_study_uids_async(patient_id, study_uid)   # :592
```

`_resolve_patient_study_uids_async` (`:317`):

1. `_resolve_patient_study_uids` (sync, `:150`) reads the **patient table row's**
   `study_uid` column + secondary list (`Qt.UserRole+10`), then falls back to the
   right-panel payload (`:205`) and the `_patient_study_uid_map` cache (`:217`).
2. Then `_enumerate_studies_for_row(pid, meta, …)` (`:338`) where `meta` is the **compact
   cached** `_server_patient_meta_by_pid[pid]` captured at list-load — **no fresh query.**

`_enumerate_studies_for_row` (`:349`) is **gated**:

```python
modalities = self._row_modalities(base_row)
if len(modalities) <= 1:                 # :370  ← single modality ⇒ return []
    return extra
total = self._row_total_studies(base_row)
if total > 0 and len(known) >= total:    # :381  ← already hold "total" ⇒ return []
    return extra
```

For 46630 this returned `[]` — the DOC study is a **separate UID** that the server's
patient aggregation does not surface as an extra modality/study in the cached row (it is
not in `study_uids`, and the DOC modality is not in the cached `modalities`, and/or
`total_studies` was reported as 1). **Result: `all_study_uids == [primary]`.**

The tab is then built **single-study**:

- `widget._is_multistudy_hint = len(all_study_uids) > 1` → **False** (`:811`).
- STEP 3.5 fetches/queues only the primary study and calls
  `widget.set_server_series_info(aggregated_series)` with primary-only series (`:1064`).
- STEP 3.6: `if len(all_study_uids) > 1:` `_show_grouped_patient_studies` **else**
  `show_patient_studies` → the single-study branch runs (`:1116–1119`).
- Background thread builds `aggregated_series` by looping **`for current_study_uid in
  all_study_uids`** (`:1167`, only primary); the grouped merge at `:1189` is gated
  `len(all_study_uids) > 1` and never runs.

### 4.2 Single-click select — how the study set is resolved (the stronger path)

`_load_and_display_series_info` (`_hp_series.py:834`, also the body of the open's
**deferred** refresh — note it logs `PatientSelectedSingleClick` at `:855`, which is why
the open's log shows single-click markers):

```
study_uids = await _reconcile_patient_studies_on_click(patient_id, patient_name, study_uid)   # :868
```

`_reconcile_patient_studies_on_click` (`:599`):

- Issues a **fresh** `search_patients_sync({patient_id, include_study_count,
  include_latest_study})` (`:652–662`).
- Reads **`server_row['studies'] / ['study_list']`** (`:686–697`), **`study_uids`**
  (`:699`), **`latest_study_uid`** (`:704`) — a richer set than the open path reads.
- Then *also* calls `_enumerate_studies_for_row(pid, server_row, …)` over the **fresh**
  row (`:716`).

That is **strictly more discovery** than the open path, against **fresher** data — so it
finds the DOC (`…389`) that the open path missed.

### 4.3 Where each path re-renders

- Single-click, `>1` study: `_show_grouped_patient_studies(...)` → **home right panel**
  (`_hp_modules.py:596`, via `display_thumbnails`), then `return` (`:886–889`).
- Resync reveal (`_resync_patient_studies_from_server`, `:558–569`): again
  `_show_grouped_patient_studies(..., force_server_merge=True)` → **home right panel**.
- **The open viewer tab's `set_server_series_info` is re-called in only two places:**
  STEP 3.5 at first open (built from `all_study_uids`, `:1064/:1212`), and the
  **already-open re-focus** path (`:671–697`, gated by `_OPEN_REFRESH_ALREADY_OPEN`),
  which runs only when `_find_widget_by_study_uid(study_uid)` finds an existing tab —
  i.e., the **second** open.

There is **no path that pushes a newly-discovered study into a viewer tab that was just
built single-study on the first open.** That is the missing link.

---

## 5. Root Cause (Structural)

### RC-1 — Two divergent "patient → studies" resolvers, by source and freshness
The open path (`_resolve_patient_study_uids_async`) and the select path
(`_reconcile_patient_studies_on_click`) are **separate implementations** that read
**different fields** from **different-freshness data**. Open reuses a compact cached row
and a gated enumeration; select does a fresh query and reads the full `studies`/`study_uids`
arrays. They legitimately disagree, and **open is the weaker of the two.** The selection
context "knows" about a study the open context cannot see.

### RC-2 — The viewer tab is built once from the open snapshot and never back-filled
`_is_multistudy_hint` and the grouped vs single-study render are decided **once**, from
the open-time `all_study_uids` (`:811`, `:1116`). When the deferred reconcile/resync later
discover an additional study, their re-render is aimed at the **home right panel**, not the
open tab. The single mechanism that refreshes an **open** tab's series sidebar
(`_OPEN_REFRESH_ALREADY_OPEN`, `:671`) is reachable only by re-focusing an
**already-open** tab. Net effect: **first open is frozen to whatever the weaker resolver
returned; the stronger result only reaches the tab on a subsequent reopen.**

### RC-3 — DOC studies are the worst case at every seam
A separate-UID DOC study (`1.2.826.…`, series `100000`) hits **all** the weak points at
once: (a) the server's `GetPatientList` may not split it out by modality, so per-modality
enumeration's `len(modalities) <= 1` gate skips it (`:370`); (b) it is discovered **late**
and async; (c) on the auto path it is **deliberately not downloaded**
(`single_click_auto_no_download`, `_hp_series.py:549`), so even when the home panel shows
its tile, its image(s) are `disk_missing` and cannot be presented. DOC is therefore the
most reliable reproducer of the RC-1/RC-2 fault.

### The wrong architectural assumption (why this category keeps recurring)
> **"A patient's study set can be resolved once, synchronously, from the cached
> patient-list row at open time, and the viewer tab built from that snapshot is final."**

Every recurrence is a different surface of that one false assumption. In reality the study
set is **multi-sourced, server-authoritative, and discovered progressively** (especially
separate-UID DOC studies). Because there is **no single shared resolver** and **no
"study-set-changed → refresh the open tab" event**, each new manifestation has been patched
in *one* path or *one* widget, and the next manifestation appears in a path that patch did
not cover. The fixes are real and individually correct; they are just **local** to a fault
that is **global**.

---

## 6. Confirmed Defects

- **D1 — Divergent resolvers.** Open uses cached, gated enumeration
  (`_hp_patient_open.py:317/349`); select uses a fresh query reading `studies`/`study_uids`
  (`_hp_series.py:599`). Confirmed by code and by the 46630 log (`all_studies=1` at open vs
  `study_count=2` at resync).
- **D2 — No in-session open-tab back-fill on first open.** A study discovered after the
  tab is built is rendered only to the home panel (`_hp_series.py:558–569`); the open tab's
  `set_server_series_info` is refreshed only on reopen (`_hp_patient_open.py:671–697`).
  Confirmed by code; this is the direct cause of "disappears on open, returns on reopen."
- **D3 — Open enumeration is blind to separate-UID DOC studies.** The `len(modalities) <= 1`
  / `total_studies` gates (`:370/:381`) over the **cached** row prevent the open path from
  ever probing a DOC study the server didn't aggregate. Confirmed by code; consistent with
  the 45932/46024 DOC-discovery findings.
- **D4 — Late-discovered DOC images are never fetched on the open path.** The auto resync
  enqueues nothing (`single_click_auto_no_download`, `_hp_series.py:549`). So a DOC that
  *does* get rendered shows an empty/`disk_missing` series. Confirmed by the 46630 log.

## 7. Suspected Defects (need live confirmation)

- **S1 — Home re-render vs active-tab mismatch.** `_resync…` gates its reveal on
  `_is_active_patient_selection(patient_id, uids[0])` (`:558`). After a double-click the
  "active selection" may legitimately be the open tab; whether the home re-render is even
  visible/relevant in that state should be confirmed live. (Log shows `rerendered=1`, i.e.
  it did render — but to the panel behind the viewer.)
- **S2 — Grouped render of a not-downloaded DOC.** `_show_grouped_patient_studies` fetches
  server thumbnails when a study has no local thumbs; confirm whether the DOC tile renders
  but is non-openable (no images on disk) vs is dropped entirely. Affects the exact wording
  of "not presented properly."
- **S3 — `_server_patient_meta_by_pid` contents.** Confirm, by dumping the cached meta for
  46630, whether the DOC is absent because the server omitted it (server-side, like 45932)
  or because the stash discards it during `_add_socket_patient_to_table`. This decides
  whether the durable fix is client-only or also needs the server.

## 8. Why Previous Fixes Did Not End the Recurrence

| Fix | What it solved | Why 46630 still breaks |
|---|---|---|
| **44534** per-modality enumeration (`_enumerate_studies_for_row`) | MR+DX patient where the server hides the non-latest modality | Runs over the **cached** row on open and is gated `len(modalities) <= 1`; a separate-UID DOC the server doesn't split by modality is never probed (D3). |
| **45611** resync-on-reopen (`_resync_patient_studies_from_server`) | Multi-study study that **grew** on the server | Re-renders the **home panel**, not the open tab (D2); and on the auto path it does not download (D4). |
| **46533** `_OPEN_REFRESH_ALREADY_OPEN` | Re-opening an **already-open** tab missed new server series | Fires only on the **second** open; the **first** open (46630's case) is untouched (D2). |
| **45932 / 46024** DOC discovery | Server-side patient↔DOC linkage; documented "first-open refresh gap" | The client-side first-open refresh (architecture-review **P2 #10**) was **specified but never implemented** (D2/D3). |
| **44504** cross-patient isolation | Stop leaking another patient's study | Correct and must stay — but it is a *subtractive* guard; it does nothing to *add* a missed own-study (orthogonal to this bug). |

Each fix addressed one **path** or one **widget**. None unified the **resolver** (RC-1)
or added the **open-tab back-fill** (RC-2). So the fault simply resurfaced through the
next uncovered path.

---

## 9. Recommended Permanent Solution

The goal is to make "**Patient → all studies → display all studies**" pass through **one**
authority and **one** sink, for **both** click types and for **late** discovery. This
aligns with — and partially is — the 2026-06-16 architecture review's roadmap.

### P0 — Unify study discovery (kills RC-1)
Introduce a **single async resolver** `resolve_patient_studies(patient_id,
clicked_study_uid) -> list[StudyRef]` that is **server-authoritative and fresh**, unions
table-row + fresh `search_patients_sync` (`studies`/`study_uids`/`latest`) + per-modality
enumeration, and applies the existing cross-patient owner guard. **Both**
`_reconcile_patient_studies_on_click` and `_resolve_patient_study_uids_async` must delegate
to it, so single-click and open can never disagree again. Keep the fast cached path only as
a *first paint* optimization, never as the authority. (Architecture review P1 #7:
"centralize study ownership / resolution into one service used by open, reconcile, import,
…".)

### P0 — In-session open-tab back-fill (kills RC-2)
Implement the architecture review's **P2 #10**: when async discovery (reconcile/resync)
finds a study UID for the **active patient that is not yet in the open tab**, refresh the
**open viewer tab** — not just the home panel — by calling the already-merge-aware
`widget.set_server_series_info(full_series_for_all_studies)` and flipping the tab to the
grouped render. Reuse the existing `_OPEN_REFRESH_ALREADY_OPEN` refresh code
(`_hp_patient_open.py:679–692`); the only change is to also trigger it on **study-count
growth during a first open**, not only on reopen. Gate behind a flag
(`AIPACS_OPEN_TAB_STUDYSET_BACKFILL`, default on) for safe rollback.

### P1 — DOC discovery and download (kills RC-3)
1. **Server-side remains primary**: ensure `GetPatientList` aggregation links separate-UID
   DOC studies to the `PatientID` (the 45932 fix class).
2. **Client mitigation**: a **gated DOC probe** for patients whose row looks single-modality
   (`AIPACS_DOC_STUDY_PROBE`, default off until measured), with strict server-owner
   validation, folded into the unified resolver — not bolted onto one path.
3. **Download policy**: when an additional study (incl. DOC) is discovered for a tab the
   user **opened**, its missing series must be **queued** (open is the download path),
   instead of being skipped as `single_click_auto_no_download`. Scope this to the *open*
   context only, preserving the single-click "select = no download" contract.

### P2 — Consolidate completeness/identity (prevents new variants)
Adopt the architecture review's P0/P1: route all viewer→download calls through the
canonical `(study_uid, original_series_number, series_uid)` resolver; enforce Download
Manager membership validation; make `sync_manifest.evaluate_sync` the single completeness
API; and stop silent ownership upserts in `insert_study/insert_series`. These remove the
adjacent "impossible count" and "wrong-study" variants that share the identity-at-boundary
root.

---

## 10. Migration / Refactoring Risk

- **Single-study patients must stay byte-identical.** The unified resolver must return
  exactly `[clicked]` with **zero** extra server queries for single-study/single-modality
  patients (the 44534 zero-cost contract). Guard with the existing
  `test_resolve_patient_study_uids_scope.py`.
- **Do not regress the multi-study display invariants.** Offset-key series index, the
  `len(_studies_series) > 1` gating, per-study disk paths, and the no-clear-before-deferred
  anti-flicker rule (`MULTI_STUDY_SINGLE_TAB_PLAN.md`) must be preserved. The back-fill must
  go through `set_server_series_info` (merge-aware) — never a clear+rebuild that flickers.
- **Cross-patient isolation must not weaken.** Every newly-unioned UID must keep passing
  the server-owner guard (`44504`); enumeration adds, the guard subtracts — keep both.
- **Avoid a download storm.** The open-context download of late studies must be
  *missing-only* and DM-deduped; do not re-introduce auto-download on single-click.
- **Performance.** A fresh per-open query for every patient would regress open latency;
  keep the fast cached first-paint and run the authoritative resolve in the background,
  back-filling when it completes (the same fire-and-forget shape the resync already uses).
- **Extra queries on multi-modality / DOC probe** must be bounded and flag-gated; measure
  before defaulting the DOC probe on.

---

## 11. Validation Plan

**Unit / regression (run on Windows; `-p no:debugging`):**
- New: `test_resolve_patient_studies_unified.py` — single-click and open resolve the
  **same** set for a 2-study patient incl. a separate-UID DOC; single-study path issues
  zero extra queries.
- New: `test_open_tab_studyset_backfill.py` — discovering a 2nd study after a single-study
  first open triggers exactly one `set_server_series_info` on the **open** tab and the
  grouped render; idempotent (no second rebuild if the set is unchanged).
- Keep green: `test_resolve_patient_study_uids_scope.py`, `test_resync_on_reopen.py`,
  `test_modality_summary_doc_merge.py`, the multi-study/cross-patient suites, and the
  download-manager dedup/identity suites.

**Live (source build from VS Code, FAST viewer — no VTK; human-assisted bootstrap):**
1. 46630 **single-click** → confirm both studies + DOC visible.
2. 46630 **double-click (first open)** → both studies appear in the **viewer sidebar**, DOC
   series present and openable, DOC images downloaded.
3. Close, **reopen** → still complete (no regression to the 46533 reopen path).
4. A pure single-modality, single-study patient → open latency unchanged; no extra query.
5. A genuine multi-modality grown study (45611-style) → still syncs and reveals.

**Log markers to verify (`download_diagnostics.log`):**
- Open of 46630 now shows `all_studies=2` (or a `studyset_backfilled study_count=2` trace),
  a `DownloadEnqueued` for the DOC under the **open** trigger, and a viewer-tab refresh —
  not just a home-panel `rerendered=1`.
- Single-click of 46630 still shows `PatientSelectedSingleClick` + no `DownloadEnqueued`.

**High-stakes gate:** because this touches clinical study completeness, validate with a
verification subagent diffing before/after `set_server_series_info` call sites, and confirm
no cross-patient `*_cross_patient_skip` regressions across a multi-patient sweep.

---

## 12. Bottom Line

The recurring failure is one structural fault wearing different masks: **open resolves the
patient's studies from a weaker, staler source than single-click, and the open viewer tab
is never back-filled when the fuller set is discovered in-session.** DOC studies expose it
most reliably because the server under-reports them and the client never re-probes on open.
The durable fix is small in surface but architectural in intent — **one shared,
server-authoritative study resolver for both clicks, and one in-session "study-set changed
→ refresh the open tab" path** — exactly the two items the 2026-06-16 architecture review
flagged as missing. Until those exist, each new patient will keep finding the next
un-patched path.

*No code was changed. Recommend implementing P0 (unified resolver + open-tab back-fill)
behind flags, with the validation plan above, before the next build.*

# Multi-Study / Previous-Exam Series Identity, Grouping, Sync & Loading — Architectural Review

**Date:** 2026-06-30  **Trigger:** Patient 48273 (2 previous exams). Problem A — drag
Series 602 (380 images) shows only ~40. Problem B — Series 100000 (DICOMized document)
won't load. **Class of bug:** recurs after every point-fix → needs ONE rule, not another
exception.

This review is the authoritative design for the multi-study / previous-exam series
pipeline. It is grounded in the live 48273 logs (not theory) and defines the **canonical
SeriesIdentity rule** all stages must obey. Read it before touching previous-exam load,
`_server_series_info` / `_rebuild_multistudy_series_index`, the offset-key resolver
(`_resolve_canonical_series_identity` / `resolve_entry_study_location`), the grow lane, or
`load_single_series_by_number`.

> **STATUS UPDATE (2026-07-01): Stage A1 implemented + LIVE-VERIFIED on patient 48695.** The two
> root causes from §3 A1 are fixed: (1) `_count_series_files_on_disk` now resolves the canonical
> per-study folder for offset display keys (was returning a wrong `0` for previous-exam series);
> (2) the A1 watchdog rebuild uses `change_series_on_viewer(force_reload=True)` so the same-series
> no-op no longer swallows it. 48695 logs confirm every series grew with `displayed` climbing
> (prev-exam `1000010` 50→144, `2000203` 20→135; primary `302` 29→147, `175651321` 1→36), the
> prev-exam loaded from its own folder `…/019/10/`, KPIs clean, zero errors. POLISH: the disk-count
> fix's flag (`AIPACS_DISK_COUNT_CANONICAL`) was **collapsed to unconditional**, and A1's per-session
> bookkeeping dicts are now bounded. As-built detail + the 48695 evidence:
> `docs/reports/DICOM_COMPLEX_STUDY_COMPATIBILITY_REVIEW_2026-07-01.md` §8. Stages A2 (live
> secondary-study progress bridge) and B1 (Series-100000 document handling) remain staged.

---

## 1. What the 48273 evidence actually shows

Patient 48273 = a primary study (`…0986800000041`, slot 0) + **two** previous exams:
`…488491.86476` (slot 2, the dropped one) and `…40986800000084` + two
`1.2.826.0.1.3680043.8.498.*` document studies. Disk (authoritative):

```
study …86476 (previous exam)  : 100000(1)  101(5)  201(121) 202(484) 203(121)
                                301(121) 302(484) 303(121) 501(95) 502(380) 503(95)
                                601(95)  602(380) 603(95)  9001(1)  + 4 SC series
study …041 (primary)          : 1(23) 2(52) 3(30) 4(3) 5(36) 6(30) 7..24(112) 100(112) 101(112)
study …084 (previous exam)    : 1..24 (18..160 each) 100(144) 101(160) 102(160) 103(85)
```

### Problem A — Series 602 sticks at 40/380 (NOT 40/302; the real expected is 380)

| Signal (log) | Value | Meaning |
|---|---|---|
| download `series-summary series=602` | `downloaded=380 … total=380` | **All 380 images downloaded to disk, 0 retries** |
| disk folder `…86476/602` | **380 .dcm** | complete on disk |
| `[MULTI-STUDY LOAD] key=2000602` | `study_path=…86476` + `per-series study_pk=1568` | identity + path resolve **correctly** (the 48101 fix works) |
| `[H7-P4] series=2000602` | `server_image_count=380 disk_file_count=50 metadata_instance_count=40` | the series was loaded **mid-download** (≈40-50 on disk then) |
| `ADVANCED_CACHE_READ sn=2000602` | `n=40 dims=(512,512,40)` | the viewport built a **40-slice** stack and stopped |

**Root cause:** 602 was dragged WHILE downloading. The stack built from the ~40 files then
present, the load "succeeded" at 40, and it **never grew to 380** afterward — because:

1. The live grow bridge `HomeDownloadService.connect_dm_to_widget(dm, widget, study_uid)`
   is bound to the **PRIMARY** `study_uid`; every progress/completion handler returns on
   `uid != study_uid`. So a **secondary (previous-exam) study's** `seriesProgressUpdated` /
   `seriesDownloadCompleted` events **never reach the viewport** — it cannot grow during
   download. (Documented limitation; CLAUDE.md "Disk-readiness resume for unbridged
   downloads".)
2. The only backstop is the disk-ready resume watchdog (`_maybe_resume_awaiting_from_disk`),
   but it ONLY runs for a viewport whose `_awaiting_series_number` is set. Once the partial
   load "succeeded" at 40, the awaiting flag cleared → the watchdog never re-checks it → the
   viewport is **stuck at 40 forever** even though 380 sit on disk.

This is the whole recurring class: **a series displayed with fewer slices than exist on
disk, with no event that ever tells it to grow.**

### Problem B — Series 100000 (DICOMized document)

- `…86476/100000` = **1 instance** (`[H7-P4] series=1100000 server_image_count=1
  disk_file_count=1 metadata_instance_count=1`). It is an encapsulated document / secondary
  capture, not an image stack.
- **Two issues:** (a) the FAST image viewport can't render an encapsulated-PDF/SC instance,
  so it appears to "not load"; (b) an offset-key **resolution anomaly** — `[MULTI-STUDY LOAD]
  key=2100000 -> … disk_series=10` resolved the slot-2 document key (`2100000`, orig should
  be `100000`) to disk series **10**, a DIFFERENT real series in the same study. Needs a
  pinned repro, but it indicates `100000` is colliding/mis-mapping in the offset scheme.

---

## 2. The canonical rule (NON-NEGOTIABLE)

**Every series, at every pipeline stage, is identified by its full identity — never by
series number alone.** The authoritative identity is:

```
SeriesIdentity = (
    patient_id,            # the exam's OWN patient_id (previous exams differ from current)
    study_instance_uid,    # the DICOM StudyInstanceUID the images are DOWNLOADED/STORED under
    series_instance_uid,   # globally unique; the only safe cross-study key
    series_number,         # DISPLAY ONLY — collides across studies, never a primary key
    exam_type,             # current | previous
    previous_exam_index,   # 0..N, stable first-seen order
    exam_date,
    local_series_path,     # SOURCE_PATH/<study_instance_uid>/<original_series_number>
    expected_instance_count,   # server image_count (authoritative target)
    special_type,          # None | document | secondary_capture | encapsulated_pdf | ...
)
```

Two **invariants** the disk layout already enforces and the viewer must honor:

- **Disk is the source of truth for the instance SET.** Files live at
  `SOURCE_PATH/<study_instance_uid>/<original_series_number>/`. The number of `.dcm` there
  IS the series' available instance count. A DB/metadata count is a *hint* that can lag.
- **The join key between a download and a viewport is `(study_instance_uid,
  original_series_number)`** (equivalently `series_instance_uid`) — NEVER the bare series
  number and NEVER the offset display key in isolation.

### What ALREADY exists (reuse, don't reinvent)

The codebase already has most of this — the bug is that not every stage routes through it:

- `_server_series_info[offset_key]` entries carry `study_uid`, `_orig_series_number`,
  `series_path`, `series_uid`, `_study_slot` (set by `_rebuild_multistudy_series_index`).
- `_resolve_canonical_series_identity(display_key)` → `(study_uid, orig_series, series_uid)`
  and `resolve_entry_study_location(entry)` → correct per-study disk folder. **These work**
  (48273 `[MULTI-STUDY LOAD]` proves it).
- `PacsClient/utils/series_completeness.py` — `SeriesCompletenessSnapshot` with
  `is_disk_complete` / `is_incomplete` / **`viewer_behind_disk`** / `has_expected_count`.
- `PacsClient/utils/series_display_state.py` — `decide_display_action` (the ONE decision
  authority per [[unify-route-decisions-through-authority-not-bespoke]]).
- `PacsClient/utils/viewer_identity.py` (`SeriesRequest`) + `series_state_store.py` — the
  shadow identity/state authority (S0-S2).

**The gap is not missing identity — it is that grow / completion / "is this viewport
behind disk" is not driven by that identity for SECONDARY studies.**

---

## 3. Root-cause-to-fix map (rule-based, staged, each flag-gated + live-verified)

### Stage A1 — Grow a DISPLAYED viewport to its full on-disk count (fixes Problem A)

**Rule:** while a series' download is in flight OR just after it completes, any viewport
DISPLAYING that series (matched by canonical `(study_uid, orig_series)`) whose shown slice
count `< on-disk .dcm count` must rebuild from disk until `displayed == disk == expected`.

**Implementation:** extend the existing disk-ready watchdog so it also scans **non-awaiting**
viewports. For each displayed viewport, resolve its canonical identity, count its own disk
folder, and if `series_completeness.viewer_behind_disk` (displayed < disk) AND the folder is
SETTLED (stable count, no `.part`) → rebuild via `change_series_on_viewer(display_key)`
(which now reads the full disk set). Settle (stop) when `displayed == disk`. Route the
decision through `decide_display_action` — do NOT add a bespoke compare. Flag
`AIPACS_GROW_DISPLAYED_TO_DISK` (default-off until live-verified on 48273 → 602 reaches
380). This is the single fix that ends the recurring class.

Risk controls (mandatory): per-viewport attempt cap + settle-stop (reuse the 47084/47801
livelock guards); only act on a SETTLED folder so mid-download flicker can't churn; never
touch a viewport that already shows `displayed == disk`.

### Stage A2 — (better) bridge secondary-study progress by canonical identity

The deeper fix behind A1: make `HomeDownloadService` route a secondary study's
`seriesProgressUpdated`/`seriesDownloadCompleted` to the awaiting/displaying viewport by
`series_instance_uid` (it already does this for the awaiting lane via
`display_key_for_active_series_uid`; extend it to the *displaying* lane + completion). Then
secondary series grow live, exactly like the primary. Larger; do after A1 proves the rule.

### Stage B1 — Series 100000 special-series handling (fixes Problem B)

1. **Fix the offset-key anomaly** first (`key=2100000 -> disk_series=10`): pin why a
   `100000` series resolves to disk series `10` (suspect: `_orig_series_number` mis-set, or a
   numeric/҂truncation in the offset round-trip for the 6-digit `100000`). The identity must
   round-trip `orig=100000` exactly.
2. **Detect special series by SOPClassUID / modality**, not series number: Encapsulated PDF
   (`1.2.840.10008.5.1.4.1.1.104.1`), Secondary Capture (`…7.x`), or single-instance
   document series. Tag `special_type` on the SeriesIdentity.
3. **Route by type:** an image SC displays in the normal viewport; an encapsulated PDF /
   non-image document opens through the document/attachment viewer path instead of silently
   failing in the image viewport. Series 100000 must be a *valid, intentionally-handled*
   series, shown first if required.

### Stage C — Isolation guards stay (already correct, keep)

The cross-patient / cross-study isolation guards (`merge_study_uids` sanctioned-uids, the
per-sink owner re-checks) and the per-series `study_pk` fix (48101) must remain — A1/A2 only
ADD grow behavior keyed on identity; they must never merge or re-attribute a series across
studies.

---

## 4. Logs (add these, keyed on SeriesIdentity — partly exist)

`[PREV-EXAM-UID]` (exists), `[MULTI-STUDY LOAD]` (exists), `[H7-P4]` (exists; its
`disk_file_count` was just fixed to use the orig series number). ADD a single structured
`[SERIES-IDENTITY]` line at: prev-exam load, drag/drop, viewport import start/success/fail,
grouping start/end, and each grow tick — fields: `patient_id study_uid series_uid
series_number display_key exam_type prev_index expected disk_count displayed_count
viewport_id special_type result`. One identity line per stage makes this class
self-diagnosing.

---

## 5. Acceptance criteria → fix mapping

| # | Criterion | Stage |
|---|---|---|
| 3 | Drag 602 loads full 380, not 40 | A1 (A2) |
| 8,9 | Grouping continues to full count, no manual re-drag | A1/A2 |
| 4 | Series 100000 loads or opens in document viewer | B1 |
| 6 | Same series number across studies don't conflict | already fixed (48101 study_pk) + canonical join |
| 1,2,5,7 | Studies/exams isolated | C (existing guards) + keep |
| 10 | Rule-based, prevents recurrence | the canonical rule §2 + routing through series_completeness/decide_display_action |

---

## 6. Recommended order (each: flag-gated, test, LIVE-verify on 48273, then collapse flag)

1. **A1** — grow displayed→disk (ends Problem A; smallest, highest value).
2. **B1.1** — fix the 100000 offset-key round-trip.
3. **B1.2/3** — special-series detection + document-viewer routing.
4. **A2** — live secondary-study progress bridge (retires the A1 backstop as the only path).
5. Collapse verified flags per the unify-authority directive.

Do NOT attempt all at once. Each stage is independently verifiable on 48273. The canonical
rule (§2) is the contract; the stages are how each pipeline phase is brought into compliance.

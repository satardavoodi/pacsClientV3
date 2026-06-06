# Missing same-patient study across modalities — 44534 (2026-06-02)

**Symptom:** patient `44534` (RAHIMI^FATEME) legitimately has **two studies of the
same patient** — an **MRI** and a **Radiography/X-ray (DX)**. Only the **DX** study
showed in AI-PACS; the **MRI was missing**. (This is the *opposite* problem to the
44504 case: here both studies genuinely belong to one patient and BOTH must show.)

## Diagnosis (evidence-based)

| Source | Result for 44534 |
|---|---|
| **Local DB** | 1 study only — `…20260602114328.0.98` (DX / HAND) under patient_pk 2683 |
| **Server** `GetPatientList(patient_id=44534)` | `total_studies=2`, `modalities=['MR','DX']`, but **`study_uids=[DX only]`** |
| **Server** `GetPatientList(patient_id=44534, modality='MR')` | returns the MR study `1.3.12.2.1107.5.2.46.174759.30000026060104193663400000099` ("UPPER EXTRIMITY^New Exam.M.") |
| **Server** study-info of the DX study | `patient_id = 44534` (so it is correctly this patient's) |

### Root cause
The external PACS server's **`GetPatientList` returns only ONE study UID per patient —
the latest** (the DX study) — even though the same response reports `total_studies=2`
and `modalities=['MR','DX']`. The server discriminates a patient's studies **by
modality**; the non-latest modality's study UID (the MRI) is **never present in the
default response**, so the app never learns the MRI exists. Local DB, thumbnails and
the viewer are all driven from that study-UID list, so the MRI is invisible
everywhere.

This is **not** a cross-patient guard side-effect: the MR study's server `patient_id`
is `44534`, so the 2026-06-02 isolation guards *keep* it (they only drop studies whose
server `patient_id` ≠ the target). The MRI was missing purely because its UID was never
discovered.

## Fix — per-modality study enumeration
When a patient row reports **more than one modality**, query the patient list **once
per modality** and union the additional study UIDs in. Every UID is fetched with the
server's `patient_id` filter **and** re-checked against `patient_id` locally
(`_row_for`), so only that patient's own studies are ever added — **strict
cross-patient separation is preserved and strengthened.**

Shared helper `_enumerate_studies_for_row(patient_id, base_row, already_have)` in
`_hp_patient_open.py`:
- Derives the modality set robustly (`_row_modalities`: a `modalities` list *or* a
  multi-valued `modality` string like `MR\DX`) and the study count (`_row_total_studies`).
- **Single modality ⇒ returns `[]` with ZERO server queries** (the common case).
- Skips the per-modality queries when we already hold ≥ `total_studies` UIDs (no
  redundant queries on re-open).
- Otherwise queries each modality and returns the new UIDs, logging
  `study_enumerated_by_modality`.

Integration (both click paths, so the studies both **display and download**):
- **Double-click open** — `_on_patient_double_clicked_async` resolves via the new async
  `_resolve_patient_study_uids_async`, which reads a **zero-cost stash**
  (`_server_patient_meta_by_pid`, populated as the list loads in
  `_add_socket_patient_to_table`) to decide whether to enumerate — so **single-study
  opens add no server query and no latency**. The unioned list feeds open STEP 3.5
  (download + viewer series map) and the grouped display.
- **Single-click reconcile** — `_reconcile_patient_studies_on_click` feeds its
  already-fetched `server_row` into `_enumerate_studies_for_row` (no extra query); the
  discovered UIDs join `server_uids` → `merged` → the "missing" download loop (which
  re-applies the cross-patient guard) and the grouped thumbnails.

### Why single-study patients are unaffected (responsiveness)
The decision uses the modality set already present in the list row. A single-modality
patient ⇒ `_row_modalities` length 1 ⇒ immediate `[]`, **no query, no added open
latency**. Only genuine multi-modality patients pay for the (rare) per-modality
queries, and only until all their studies are known locally.

## Files changed
- `PacsClient/.../home_panel/_hp_patient_open.py` — new `_row_modalities`,
  `_row_total_studies`, `_resolve_patient_study_uids_async`,
  `_enumerate_studies_for_row`; double-click call site now `await
  _resolve_patient_study_uids_async`.
- `PacsClient/.../home_panel/_hp_series.py` — reconcile enumerates per-modality from its
  `server_row` and unions into `server_uids` (kept `local_uids` sync so the
  missing/download semantics are unchanged).
- `PacsClient/.../home_panel/_hp_search.py` — `_add_socket_patient_to_table` stashes the
  compact per-patient meta (`_server_patient_meta_by_pid`) at list-load time (zero cost).

## Verification
- **Logic (real shipping code, exec-extracted, 7/7):** S1 44534 multi-modality →
  discovers the MR UID; S2 single-study/modality → 0 queries, no extras; S3 multi-study
  single-modality → 0 queries; S4 a modality query returning *another* patient's row →
  ignored (isolation); S5 re-open holding both → 0 queries; S6 robust `MR\DX` string →
  discovers MR; S7 total-unknown multi-modality → still discovers.
- **Syntax:** every edited region validated (`_hp_search.py` full compile;
  `_on_patient_double_clicked_async`, the reconcile method, and the new helpers
  extract-compile clean). NOTE: whole-file `py_compile` in the Linux sandbox failed only
  because the mount served **truncated** copies of the just-edited files
  (`sandbox_mount_stale_reads`) — not a real syntax error; the Read tool shows the files
  complete and well-formed.
- **Live (pending restart):** open 44534 → expect BOTH the MRI and the X-ray to display
  and download, plus a `study_enumerated_by_modality … modality=MR` line in
  `user_data/logs/download_diagnostics.log`; confirm single-study patients open with no
  added latency.

## Invariants (do not break)
- The authority for "which studies a patient has" when the server hides them is a
  **per-modality `GetPatientList` query**; the default response gives only the latest
  study UID per patient.
- Enumerated UIDs are **always** verified against the patient's own `patient_id`
  (server filter + `_row_for` re-check) before use — different Patient IDs must never be
  mixed.
- Single-modality / single-study patients must incur **zero** extra server queries and
  no added open latency (gate on the list-row modality set / the stash).
- The cross-patient persist/display guards (STEP 3.5, reconcile, grouped display) stay
  in place; enumeration adds studies, the guards remove foreign ones.

---

## Thumbnail refresh follow-up — 44323 / 44534 (same day)

After the enumeration fix, a re-click investigation on **44534** and **44323** surfaced two
**thumbnail-gate** defects (distinct from study discovery). Ground truth from the live DB +
disk + logs:

| Patient / study | DB series | Disk PNGs | Server fetch returned | Gate `server_series` |
|---|---|---|---|---|
| 44323 MRI `…026` | 20 | 20 | 20 (after 1→20) | **21** |
| 44534 DX `…0.98` | 3 | 3 | 3 | **10** |

So the locally-shown thumbnails were actually **complete for the studies that were loaded**
(44323 = 20/20, 44534 DX = 3/3). What the user saw as "missing MRI" on 44534 is the separate
MRI **study** that pre-fix code never discovered (the enumeration fix above). Two real gate
bugs were also found and fixed:

- **B1 — patient-aggregate count mis-attributed to one study.** The right-panel cache gate
  reads `_server_series_count_by_study[study]`, stashed in `_add_socket_patient_to_table`
  (and the reconcile) whenever `len(study_uids)==1`. For a multi-study patient the server
  returns only the latest UID (so that's true), but `count_of_series` is then the **patient
  total** — 44534 DX got `10` (DX 3 + MRI 7), not 3. That is a false "grew" signal. **Fix:**
  only stash when `total_studies <= 1` (genuinely single-study). Applied in `_hp_search.py`
  and `_hp_series.py`.
- **B2 — "refresh once" never recovers when the server grows.** The gate marks a study
  refreshed in `_thumbs_server_refreshed_uids` by **UID only**, so after the first refresh a
  later server-side growth (more series) is never re-fetched on re-click — the stale partial
  cache is pinned. **Fix:** key the marker by the server series **count**
  (`f"{uid}@{server_series}"`), so an unchanged study still hits the fast cache but a grown
  study gets a fresh key → exactly one re-fetch. Applied in `_hp_search.py`.

44323's residual `21` vs the real `20` is a benign server/disk off-by-one (the socket fetch
returns 20; the 21st series has no fetchable thumbnail). With B2 the gate stops re-fetching
once it has pulled all the server offers, yet still re-fetches if the count later truly grows.

**Note on "very delayed" (44323):** the socket thumbnail fetches themselves were fast
(~175–270 ms). The lag correlates with the right-panel deferral under an active download
(`should_defer_noncritical_open_network` + the 150 ms×8 then 700 ms poll). Re-observe after
restart; no further change made pending evidence that the delay persists with the gate fixes.

**Status:** B1 + B2 are code-complete and statically verified (extract-compile; whole-file
sandbox compile blocked only by the mount-truncation artifact). Like the enumeration fix they
are **not live until the source build is restarted** — the running instance (pid 126692) has
neither.

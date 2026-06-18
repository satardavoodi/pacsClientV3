# Unified Pipeline — Review & Test Report (2026-06-18)

**Scope:** download pipeline, thumbnail loading, single-click preview, double-click open,
server sync, metadata/header indexing, DB/cache usage, drag-and-drop, viewport loading,
multi-study handling — review of the recent unification work plus live + code + log testing.

**Build under test:** branch `beta-version`, HEAD `c2b0304d` (v3.3.3), source build launched
from VS Code (`python main.py`, PIDs 608184/609676).

**Change applied by this review:** **one** minimal, behaviour-preserving edit —
`socket_client.py` first-image-prime confirmation log raised `info`→`warning` so it is captured
in `download_diagnostics.log` (observability only; plugin mirror synced 389/389; prime tests
9/9 green). No functional/clinical logic was changed.

**Verdict:** the pipeline is **substantially unified and healthy** — no functional or clinical
regression. Study-set *resolution*, the *download payload*, the *viewer metadata sink*, and the
*thumbnail disk source* are single-authority. Multi-study (incl. patient 46713 DOC series
100000) works end-to-end live. 416 code tests pass.

> ### Correction note (post-verification) — supersedes the first draft
> The first draft of this report flagged the **first-image prime as "inert"**. On deeper
> verification that was a **FALSE ALARM**, caused by two compounding mistakes:
> 1. The prime's confirmation is logged at **INFO**, and `socket_client` INFO is **filtered out
>    of `download_diagnostics.log`** (only WARNING+ reaches it — proven: the always-run INFO
>    lines "Creating output directory" / "Will download in N batches" appear **0** times while
>    the WARNING "Downloading series" appears for every series). So "0 prime logs" measured the
>    log filter, not the feature.
> 2. The "`skipped=1`" I cited as a pre-seeded on-disk instance is actually an **end-of-download
>    server skip** (1 of 11 images the server didn't deliver). Disk inspection of the freshly
>    downloaded series showed **all** files written at bulk-download time — **no** pre-seed; the
>    prime's *start-of-download* `skipped_count` was **0**, i.e. the gate **was** satisfied.
>
> With `BATCH_SIZE = 10` (the persisted adaptive default), a fresh MR series has
> `skipped_count=0`, `batch_size>1`, not force-single → the prime **fires** (helper + wiring are
> unit-tested: `test_first_image_prime.py`, 9/9). **No gate change was made** (that would have
> "fixed" a non-bug and risked a regression). The only change is the observability tweak above
> so the prime can be validated on a slow link going forward.

---

## 1. Summary of the current unified pipeline

**Shared authority (new, pure):** `PacsClient/utils/patient_study_set.py` — stdlib-only
(verified: no Qt/VTK/numpy/pydicom import), unit-testable in isolation. Exposes
`merge_study_uids` (union + dedup + selected-first + cross-patient owner filter — the single
place that logic lives), `diff_study_uids`, `resolve_study_uids`, `build_download_payload`
(canonical DM `add_downloads` dict; emits both `description` and `study_description`), and the
`PatientStudySetService` facade.

**Clinical boundary (held):** the pipeline terminates at the metadata sink
`set_server_series_info` (`_pw_thumbnails.py:86`). It never reaches pixel data, IPP/IOP
geometry, slice ordering, orientation, VTK render windows, or MPR. Confirmed live (FAST drags
route to `backend=pydicom_qt`, the Lightweight-2D pipeline — no VTK render window).

**Behaviour flags (default to the safe/correct behaviour; legacy kept as kill-switch):**
`AIPACS_PSS_MERGE_RESOLVE`, `AIPACS_OPEN_TAB_STUDYSET_BACKFILL`, `AIPACS_OPEN_TAB_LATE_DOWNLOAD`,
`AIPACS_PATIENT_STUDY_SET_SHADOW` (off). Drag-drop view-intent flags: `AIPACS_FIRST_IMAGE_PRIME`,
`AIPACS_DRAGDROP_DEBOUNCE`, `AIPACS_DOWNLOAD_PROGRESS_TEXT`, `AIPACS_PROGRESSIVE_UID_BIND`,
`AIPACS_VIEWPORT_LOADING_PERSIST`, `AIPACS_VIEWPORT_DISK_READY_RESUME`.

**Thumbnails:** one canonical disk source `THUMBNAIL_PATH/<study_uid>/<series_number>.png`;
`ThumbnailStore` (in-memory, key `(study_uid, series_number)`) + `ThumbnailImageSourceService`;
the download manager write-through populates both. `ThumbnailBatchRunner` is dead code.

**Drag-drop is folded in as a "view series" intent:** first-image prime (verified firing),
global view-intent coalescing (last-write-wins), rich download notification (persistent spinner),
disk-ready resume for unbridged secondary-study downloads (46713), progressive uid-bind, and a
persistent viewport loading lifecycle (never blanks while awaiting).

**Runtime confirmation (today's `download_diagnostics.log`):** `right_panel_cache_gate` 416,
`right_panel_cache_hit` 301 (**72% cache hit**), `patient_study_set_viewer_backfill` 6,
`patient_study_set_late_download_enqueued` 4, `PatientSelectedSingleClick` 99 vs
`PatientOpenDoubleClick` 48, 75 single-click download-skip markers.

### Is it *truly* unified? — yes for resolution/sink/disk; partial on the consumer edges

| Dimension | Unified? | Evidence |
|---|---|---|
| Which studies belong to a patient | **Yes** | `merge_study_uids` authority; resolver tail + back-fill + reconcile/resync route through it. |
| Download payload shape | **Yes** | `build_download_payload` used by back-fill, resync, reconcile. |
| Viewer metadata entry point | **Yes** | All paths terminate at `set_server_series_info`. |
| Thumbnail **disk** source | **Yes** | Single canonical PNG path; DM write-through. |
| Thumbnail **read** path | **Partial** | Main Page = `QPixmap(disk PNG)` (`right_panel_widget.py:657`); Viewer = `ThumbnailImageSourceService`/`ThumbnailStore`. Same disk truth, different memory cache. |
| Study-source **gather** | **No (staged)** | Resolver still uses the legacy 3-tier gather; only the owner-filter tail is unified (doc §7.1). |
| Download **plan** object | **No (staged)** | No typed `DownloadPlan`; missing-only filtered at the DM queue, not the payload (§7.2). |
| Drag-drop download path | **No (staged)** | Still its own mini-workflow; not yet on `PatientStudySetService`/`build_download_payload` (§8). |

---

## 2. Still-existing parallel / legacy paths

**Staged consolidation (by design, doc §7–§8 — not active bugs):** (1) resolver *gather*;
(2) no typed `DownloadPlan`; (3) late back-fill uses `add_downloads` not
`start_priority_download_immediately`; (4) drag-drop not yet on the shared authority.

**Active asymmetries / gaps (low severity, see §6):** (5) Main-Page vs Viewer thumbnail *read*
path differs; (6) secondary-study download progress is not bridged to the viewer *during*
download (recovery via disk-ready resume after completion — the 46713 follow-up).

**Legacy kill-switches (present, OFF by default):** `AIPACS_PSS_MERGE_RESOLVE=0`,
`AIPACS_SINGLE_CLICK_DOWNLOAD=1`.

**Dead / quarantined:** `ThumbnailBatchRunner` (never instantiated);
`_download_series_on_demand` / `_download_series_fallback` (`NotImplementedError`).

No *unexpected* active parallel path was found — consumers were consolidated, not forked.

---

## 3. GUI / user-workflow test results (live, source build, Monitor A)

| # | Test | Result | Evidence |
|---|---|---|---|
| 1 | Search patient (ID `46713`) | **PASS** | ID search overrides the date filter; row shows "MR, DOC" (multi-modality at list level). |
| 2 | Single-click → thumbnails, **no download** | **PASS** | 36-series grouped preview; log = `PatientSelectedSingleClick` + `ThumbnailPreviewRequested` only (~2 ms), zero download markers; no viewer opened. Re-confirmed on undownloaded 47102. |
| 3 | Double-click open → open + sync only when appropriate | **PASS** | `PatientOpenDoubleClick all_studies=2` (both MR + DOC resolved up front), `tab_created`, `first_series_visible` 1.5 s, then `download_skipped_complete count=34` + `count=1` (both on disk → download skipped). |
| 4a | Drag **downloaded** series → viewport | **PASS** | Localizer rendered with full overlays; `ViewportLoadRequested` → `pydicom_qt` (FAST, no VTK) → `ViewportLoadingStateCleared` (+530 ms; raw load 8.5 ms). |
| 4b | Drag **not-yet-downloaded** series | **PASS** | 47102: open downloaded series under open intent (41–58 img/s); drag Series 5 → LSPINE T2 rendered (6/10). |
| 4c | Drag **same** series again | **PASS** | Viewport stable; no flicker/error/tear-down (idempotent). |
| 4d | Drag **different** series into occupied viewport | **PASS** | Localizer cleanly replaced by tirm_tra (14/27); overlays updated; no stale/mixed image. |
| 4e | Drag **second-study (DOC)** series | **PASS** | Study 2 / Series 100000 (4-page document) renders the Sonography Report (display key `1100000`); `lw2d-pipeline open_series slices=4`, `FAST:first_image_visible total_ms=164.9`, clean clear. |
| 5 | Multi-study / multi-modality / DICOMized doc | **PASS** | 46713 = MR (34 series) + DOC (1 series); both visible + loadable; two viewports show MR and the document independently. |
| — | Viewport resolves to image / error / cancel | **PASS (image/no-op observed)** | Every drag resolved to image or stable no-op; no hang/blank. Error/cancel paths are unit-test-covered, not force-triggered live. |

---

## 4. Code test results

`pytest … -p no:debugging` on `.venv` (Python 3.13.5):

| Suite | Result |
|---|---|
| `tests/code/ui_services` (patient_study_set, back-fill, scope, wiring guard) | 114 passed, 1 skipped* |
| `tests/code/viewer` guards (lifecycle, dragdrop coalesce, progress text, uid-bind) | 50 passed |
| `tests/code/download_manager` + `tests/code/network` | 230 passed |
| `tests/code/builder` parity + plugin-registry + unified wiring guard | 22 passed |
| `tests/code/download_manager/test_first_image_prime.py` (after the log change) | 9 passed |
| **Total** | **416 + 9 re-run, 0 failed** |

*Skip = the GUI-tier KPI walkthrough that hangs headless (expected). Plugin mirrors **389/389**;
release-parity **14/14**.

---

## 5. Performance / KPI findings (live + logs)

| KPI | Measured |
|---|---|
| Patient open → first series visible (46713, multi-study) | **586 ms** (hot-path complete 849 ms) |
| Patient open → 34 thumbnails displayed | **1.58 s** (server fetch; cache-hit opens sub-second) |
| Thumbnail fetch (server) | **314 ms (9) … 1.6 s (34)**; 72% of renders are cache hits |
| Drag downloaded series → image | **~530 ms** (FAST; raw load 8.5 ms) |
| DOC document series → first page | **165 ms** |
| Download throughput | **41–58 img/s** (47102: 6 series in ~2 s) |
| Single-click preview | **~2 ms** to enqueue thumbnail request; no download |

**UI-thread blocking (`MAIN_THREAD_STALL_TRACE`):** the long stalls are **not** in the reviewed
pipeline — startup license check `app_handler.py _update_license_info` (up to **~10 s**,
psutil-heavy), single-instance takeover psutil enumeration, the Secretary/EchoMind orb
`secretary_button_widget.py _rebuild_frames` (builds 121 animation frames; **one-time per widget
size** — already guarded by `if side == self._cached_side: return` and an icon cache from a prior
optimization, so not per-paint), and a ~498 ms document-raster on the DOC load. No
`database is locked`, `socket_error`, `45123` timeout, `cross_patient_skip`, or
`CriticalCountMismatch` in today's logs.

---

## 6. Bugs / findings (post-verification)

**No functional or clinical defect was found in the unified pipeline.** Single-click,
double-click, multi-study resolution, cross-patient isolation, drag-drop, and the DOC case all
behaved correctly live and in tests.

**F1 — First-image prime: NOT a bug (resolved).** See the Correction note. The prime fires for
fresh multi-image series; the apparent "0 occurrences" was a `socket_client`-INFO log filter, and
the "`skipped=1`" was a server-side end-of-download skip, not an on-disk pre-seed. **Fix applied:**
the prime confirmation is now logged at WARNING so it is observable in `download_diagnostics.log`
(behaviour unchanged; mirror synced; tests green). Validate on a throttled link to see
`⚡ First-image prime …`.

**F2 — Main-thread stalls in adjacent systems (Medium; OUT of the pipeline).** License startup
(~10 s) and single-instance takeover (psutil) freeze the GUI thread at startup; the Secretary orb
does a one-time 121-frame build per size. None is in the download/thumbnail/drag/viewport
pipeline, so the unification work did not introduce them. They are the dominant perceived
"freeze" moments. **Not patched** — these touch licensing / single-instance / an already-optimized
unrelated widget, so per the project's minimal-safe / no-unrelated-refactor rules they need a
scoped, separately-approved change (offered below), not a blind edit.

**F3 — Thumbnail read-path asymmetry (Low).** Main Page reads the disk PNG directly
(`right_panel_widget.py:657`); the Viewer reads via `ThumbnailStore`. Same disk truth + DM
write-through, so consistent; the store/disk seam is cosmetic-perf. Documented, not changed.

**F4 — DB warning `no such column: patient_uid` (Low; stale).** 3 occurrences total, last
2026-06-16, none since; caught in-transaction (WARNING). The column is referenced only in
peripheral modules (`module_system`, `ai_imaging`, `mpr`, `storage`), not the patient/pipeline
path. Documented, not changed (a peripheral-module edit is out of this review's safe scope).

**F5 — Secondary-study progress not bridged during download (Info; known follow-up).**
`home_download_service.on_series_progress` filters by the opened study's `study_uid`; recovery is
the disk-ready resume after completion. Deeper cross-layer change; documented.

---

## 7. Fixes / recommendations

**Applied this review (minimal, safe, reversible):**
- **F1 observability** — `socket_client.py` prime confirmation `info`→`warning` so the prime is
  visible in `download_diagnostics.log`. Plugin mirror synced (389/389); `test_first_image_prime.py`
  9/9. This is the only code change.

**Recommended, NOT applied (need a scoped, separately-approved change):**
1. **F2 (highest user-visible impact):** move the startup license check and single-instance
   psutil enumeration off the GUI thread (worker + signal); for the Secretary orb, build frames
   lazily / fewer frames / off-thread. These are unrelated to the pipeline and the project rules
   require explicit sign-off + validation before touching license / single-instance / the orb.
2. **F5:** bridge secondary-study progress by `series_uid` so a non-primary study binds
   progressively *during* download (not only on completion).
3. **F3:** optionally route the Main-Page right panel through `ThumbnailImageSourceService` for a
   single read API (low value).
4. **F4:** trace the `patient_uid` query in the peripheral modules and align it to the schema.

I can take on F2 (the real responsiveness win) as a focused, flag-gated, validated change on your
go-ahead.

---

## 8. Source-path / build-inclusion confirmation

- Active build branch **`beta-version`**, HEAD **`c2b0304d`** (v3.3.3). The unified-pipeline
  source is present and committed; this review added **one** uncommitted change
  (`socket_client.py` log level) plus its synced plugin mirror — ready to commit.
- Plugin mirrors **389/389** in sync (`verify_plugin_mirrors.py`) after the change.
- Release-parity guards **14/14**; source-wiring guard `test_unified_pipeline_wiring.py` passes —
  flags, functions, routing, and the legacy kill-switch tail are in the build; a stale build would
  fail the gate.

**Conclusion:** the unified pipeline is in the correct source path on the build branch and will
be included in the final build. The headline "prime inert" concern was a measurement artifact
(corrected here); the real remaining issue is out-of-pipeline UI-thread blocking (F2), offered as
a scoped follow-up. One minimal observability fix was applied, mirrored, and tested.

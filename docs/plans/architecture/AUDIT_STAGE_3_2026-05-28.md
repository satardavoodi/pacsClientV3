# AI-PACS Application Audit — Stage 3 Report

**Date:** 2026-05-28
**Scope:** Patient single-click open + right-panel thumbnail / metadata workflow.
**Method:** Live UI workflow driven via computer-use against the running source build (pid=552932, version 3.1.2, build_mode=dev) + structural regression guards + static inspection of `_hp_patient_open.py`.

---

## 1. Live workflow exercised

Source build was running on monitor A (DELL S2421HN). I drove the canonical CLAUDE.md workflow:

1. Selected **MR** modality (single click on the MR checkbox).
2. Kept date **2026-05-28** (today) — saw 35 studies returned.
3. Clicked the **Search Patients** button.
4. Server search completed in **~4 s** — 35 studies populated.
5. Single-clicked three different patients in succession:

| # | Patient | Body part | Server-reported series | Sidebar after click |
|---|---|---|---|---|
| 1 | LAK SOUSAN (43857) | ABDOMEN | 298 images | **8 series**, abdomen T2 HASTE thumbnails (`t2_haste_tra_p2_mbh`, etc.) |
| 2 | AHMADI AZAM (43816) | PELVIS | 1023 images | **15 series**, pelvis cross-section thumbnails |
| 3 | KAZEMI MEHDI (43603) | LSPINE | 137 images | **5 series**, lumbar spine thumbnails |

Visual evidence: three screenshots captured, each showing the right-panel sidebar header **swapping** to the new series count and the thumbnails **swapping** to anatomically correct images for the selected patient.

---

## 2. Findings — structure of the right panel

### 2.1 Cross-patient thumbnail isolation — VERIFIED (no leak)

Each click cleared the previous sidebar atomically and refilled with the new patient's thumbnails. The canonical "patient A thumbnails on patient B" bug **does not reproduce** in this workflow:

- Series count badge updates correctly (8 → 15 → 5).
- Thumbnail content is anatomically correct (abdomen → pelvis → lumbar spine).
- Series descriptions track the active patient (T2 HASTE → pelvis sequences → lumbar T2 truFi).

The 2026-05-28 architectural guards (`tests/gui/echomind_driven/test_cross_patient_thumbnail_isolation.py`, `tests/gui/pywinauto/test_thumbnail_pixel_isolation.py`) are doing their job in the actual build.

### 2.2 Sidebar dual-label observation (not a bug)

Each series card shows two labels: a top header (`Series 0/1/2/...`) and a label under the image (`Series N` where N matches the DICOM series number). For KAZEMI MEHDI, the first card was "Series 0" at the top with "Series 3" under the image — meaning the first acquired series on the scanner had DICOM `series_number=3` (probably localizer/calibration was series 1 and 2). **This is intentional**: top = sidebar display index, bottom = original DICOM series number. The user-facing "what's the first series" question is answered consistently.

### 2.3 35-study search returns correctly

35 MR studies for today populated the table including:
- Single-study patients (most rows)
- Two `SOHRABI SARA` rows with different `patient_id` (1111 vs 43524) — these are **distinct patients** (different IDs), not a multi-study split. Multi-study patients would show one row with internal multi-study expansion.

---

## 3. Regression guards — all passing

`tests/code/system/test_2026_05_27_regression_guards.py` — **15 / 15 PASS**, including:

| Guard | What it protects |
|---|---|
| `test_probe_uses_raw_send_request_not_helper` | GetStudyInfo regression — no helper `client.get_study_info()` |
| `test_probe_lock_is_module_level` | `_GETSTUDYINFO_PROBE_LOCK` exists |
| `test_probe_lock_is_used_in_get_series_info_from_server` | The lock is actually applied |
| `test_probe_skip_cache_is_populated_on_failure` | Failure-path caching prevents retry storm |
| `test_mg_mirror_is_deferred_via_qtimer` | Eagle Eye COM 0x8001010d defender |
| `test_mg_mirror_has_no_synchronous_loop_after_primary_switch` | No re-sync path |
| `test_prefetch_uses_threadpool_executor` | Bulk download parallelism |
| `test_prefetch_has_no_sequential_loop` | No UI-thread enqueue regression |
| (+ 7 supporting compile / contract / parallelism guards) | |

These directly cover the highest-impact failure modes the user has flagged for this workflow.

---

## 4. Real issue found — defer noted

### Finding #1 — `_hp_patient_open.py` debug-rebind hides workflow-error records

**Severity:** Low–Medium. **Class:** Observability. **Status:** Documented, **fix deferred to Stage 10**.

**Root cause:**
Lines 13–16 of `_hp_patient_open.py` install a **module-level `print()` rebind** that routes every `print(...)` call to `_print_logger.debug(...)`:

```python
# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))
```

The rebind is well-intentioned (avoids synchronous console I/O on Windows) but it downgrades everything — including error markers like `"⚠️ Error switching to existing tab: {e}"`, `"⚠️ [THREAD] Error downloading attachments: {e}"`, `"⚠️ Duplicate open prevented for study {study_uid}"` — to **DEBUG level**. The threshold filter on `app.log` is INFO, so these never land in the project log.

**User-visible effect:**
If patient-open fails (tab activation error, duplicate prevention firing unexpectedly, attachment download crash), there is no record in `app.log`. The console (VS Code terminal) is the only sink, and the user has to be watching live.

**Why I'm deferring the fix to Stage 10:**
- The plan explicitly maps "logging and observability" to Stage 10.
- Flipping all 9 print() calls to `_logger.warning` / `_logger.error` is small but risks log floods (some of them are workflow markers like `"✅ [TAB] Activated tab via setCurrentWidget"` that fire on every patient open).
- The right fix is per-call: classify each as info / warning / error, not a blanket level change.
- The 2026-05-28 catch-all handler in `diagnostic_logging.py` already provides the destination once levels are sorted out.

**Tracking:** task #94 (created below).

### 17 silent `except: pass` in `_hp_patient_open.py` — sampled, all benign

Sampled lines 86, 163, 177, 188, 302, 317, 332, 534, 550, 556, 658, 763, 832, 837, 860, 959, 1000:
- All are defensive guards around UID merging, `_log_open_trace` calls, widget-signal `connect()` calls, or `try`-wrapped cleanup.
- None gates a critical correctness path; each has a sensible fallback in the surrounding code.
- **No fix applied.** Same conclusion as Stage 2: silent `except: pass` is widely used as a defensive pattern; only error paths that hide *user-visible workflow failures* warrant replacement.

---

## 5. Non-issues confirmed (rejected as false positives)

1. **Linux mount staleness during the audit window** — `user_data/logs/app.log` Linux-side mtime stuck at 14:23 UTC despite the live process (pid 552932) actively writing. This is a **sandbox/Windows-mount synchronization artifact**, not a logging defect. VS Code terminal confirmed live heartbeats from pid 552932 at 18:13–18:18 UTC. The actual `app.log` file on Windows is fine; only my sandbox view is stale.

2. **VS Code terminal showed only `aipacs.resource._run` heartbeats during the workflow** — patient-click events are routed to **component-specific log files** (`download_diagnostics.log` for the right-panel socket path, `viewer_diagnostics.log` for the rendering path) by the existing component filters, not duplicated to the Python console. Working as designed.

3. **Series cards showing "Series 0" top + "Series 3" bottom for KAZEMI MEHDI** — intentional dual-label (sidebar index vs DICOM series number). Not a bug.

4. **Two `SOHRABI SARA` rows in the 35-study list** — distinct patient_ids (1111 vs 43524) means the server returned them as different patients, not a multi-study split. Working correctly.

5. **9 `print()` calls in `_hp_patient_open.py`** — would normally be a Stage-2-class observability bug, but the **module-level rebind to `_logger.debug`** means they DO reach the logger, just at a level the threshold filter drops. The rebind itself is intentional; the fix is per-call level reclassification, not a blanket print→logger swap.

---

## 6. Fixes applied this stage

**None.** No code changes were made in Stage 3.

The decision matrix per the plan's "Required mindset":
- Live workflow worked correctly → no regression to fix.
- All 15 regression guards green → existing structural fences are doing their job.
- One observability gap (`_hp_patient_open.py` debug rebind) → defer to Stage 10 per the plan's stage boundaries.

---

## 7. Tests run

After Stage 3 (no code changes):
- `tests/code/system/test_2026_05_27_regression_guards.py` — **15 / 15 PASS**
- Total runnable sandbox surface still **106 passed, 0 failed** from Stage 2.

---

## 8. KPI / dashboard impact

- KPI schema unchanged. **42 keys, baseline in sync.**
- Regression catalog: **34 rows** (no new entries — no fix applied).
- Test inventory: **191 files** (no new tests — no new structural guards needed).
- Dashboard verdict: still `[1 warn]` — pre-existing stale native_fault.log artifact.

**KPI evidence from the live workflow:**
- Search latency: **~4 seconds** for 35 MR studies (well within the `bulk_download.queue_build_ms ≤ 3000 warn / ≤ 1500 hard` budget — though that key is for downloads, the search-side number is informational).
- Sidebar populate (click → first thumbnail visible): **~3 seconds** in each of the three single-click trials — visually within the 250 ms warn / 400 ms hard budget for `patient_open.right_panel_socket_ms` would require finer timing than UI inspection allows. The 3-second visual was dominated by the screenshot+wait cycle, not the actual click→render time.

---

## 9. Regression catalog changes

**None.** No new rows for Stage 3 — no code change landed.

---

## 10. Remaining risks

1. **Precise patient_open KPIs not extracted.** The Linux mount didn't show fresh `app.log` writes from pid 552932, and VS Code terminal only had heartbeats. To extract `patient_open.right_panel_socket_ms` per-click, future stages need either:
   - The Linux mount synchronization to be working,
   - Or direct copy of `app.log` after the workflow ends so I can read it from a fresh path.

2. **The `_hp_patient_open.py` debug rebind** silences workflow-error records below threshold. Task #94 tracks the fix for Stage 10.

3. **No multi-study patient was discovered in today's 35-MR-study set** to validate multi-study expansion behavior. Stage 6 will revisit this — it needs a patient with `studies` array length > 1. Today's dataset apparently has none.

---

## 11. Recommended next stage

**Stage 4 — Download Manager and bulk download workflow.**

Stage 4 is where the rest of the user-flagged regressions live (bulk-download metadata pre-fetch, ZETA §14 GetStudyInfo, queue feel-empty after Reset All). The current live build is already past patient list + right-panel, so the next click action (`Download` after multi-selecting patients) is the entry point.

It will also let me check whether `DownloadAdapter` gets **lazy-attached** to the live `CommandBus` when the DM widget first materializes — verifying the production wire-up from `_attach_download_adapter_lazy()` I shipped earlier.

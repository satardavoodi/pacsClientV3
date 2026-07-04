# OPT-01 (main-thread) — dicom-only trim of the download-status refresh — 2026-07-03

**Backlog item:** OPT-01 (main-thread blocking) in
`docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` §9.
**Type:** minimal safe edit, flag-gated default-on, offscreen-verified. **Live-verify pending.**
**Kill switch:** `AIPACS_STATUS_REFRESH_DICOM_ONLY=0` → byte-identical legacy.

## Root cause (proven against current code)

The KPI review (`KPI_SESSION_REVIEW_2026-07-01.md`) tied main-thread stalls to the download-status
refresh path. The obvious hotspots there were already mitigated before this change: the refresh loop is
chunked (`AIPACS_STATUS_REFRESH_CHUNKED`), the manifest scan has a signature-keyed verdict cache
(`AIPACS_STUDY_STATE_CACHE`), the patient-close GC is deferred+coalesced (`AIPACS_DEFER_CLOSE_GC`), and
thumbnail disk save is async (P1.1).

The **residual** GUI-thread cost was a *second*, heavier scan that those fixes did not cover.
`update_study_download_status` (called per row by the chunked bulk refresh, and per series-completion
from `_hp_download.py`) did:

```
self._local_status_cache.pop(cache_key, None)            # force a full recompute
self.results_table.setCellWidget(row, COL['status'],
    self._build_local_status_widget(study_uid, patient_id))   # -> _compute_local_status_flags (MISS)
```

`_compute_local_status_flags` (patient_table_widget.py:2398) on a cache miss runs, **per row, on the GUI
thread**: `os.walk(ATTACHMENT_PATH/<study_uid>)` (whole attachment tree) + `_is_study_downloaded` +
reception/comment reads + **two DB queries** (`has_case_of_day_for_patient`, `is_study_printed`). The
explicit `pop` guaranteed the miss, so this ran on *every* refresh tick even though a DICOM download
cannot change the attachment- or DB-derived flags (docs / voice / ai / case-of-day / printed).

## Fix

Refresh only the flag that can actually change — `dicom` availability — in place, and keep the cached
attachment/DB flags, so the widget rebuild reads a fresh cache entry with **no attachment walk and no DB
query**. New helper `_refresh_local_status_dicom_flag(cache_key, study_uid)`:

- flag off / no cached entry yet / any error → returns `False` → caller does the legacy pop + full
  recompute (first population and the kill-switch path stay byte-identical);
- otherwise re-reads `dicom` from disk via `_is_study_downloaded` (kept authoritative — the download dot
  is never stale), copies the other flags forward, writes a fresh timestamp → the subsequent
  `_compute_local_status_flags` is a cache hit.

Call site (`update_study_download_status`):

```
if not self._refresh_local_status_dicom_flag(cache_key, study_uid):
    self._local_status_cache.pop(cache_key, None)
```

Storage-clear safety: `refresh_download_statuses_local_only` now also clears `_local_status_cache`, so a
storage clear (which can remove attachments too) falls through to a full recompute and stays fully
authoritative — not just the DICOM flag.

## Why it is safe

- **No threading, no new path** — extends the existing per-row update; only removes redundant recompute.
- **DICOM dot stays authoritative** (re-read from disk each refresh).
- The preserved flags (docs/voice/ai/case-of-day/printed) are not affected by a DICOM download; they are
  refreshed by their own creation flows and by the existing `_local_status_cache` TTL
  (`_cache_validity_seconds`) backstop. The one path where they *can* change en masse — a storage clear —
  now explicitly clears the cache.
- Flag-gated default-on; `=0` restores the exact legacy pop + full recompute.
- Single-study / first-population behavior unchanged (helper returns `False` when nothing is cached).

## What must NOT change

The manifest verdict cache, the chunking, the deferred-GC, and `_compute_local_status_flags` itself are
untouched. Cross-patient isolation and the status semantics (the `dicom` dot) are unchanged.

## Files changed

- `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py` — new
  `_refresh_local_status_dicom_flag`; gated call site in `update_study_download_status`;
  `_local_status_cache.clear()` added to `refresh_download_statuses_local_only`.
- `tests/code/ui_services/test_status_refresh_dicom_only.py` — new guard (source-pins + mirror-behavioral).

## Verification

- `py_compile` clean.
- Offscreen: `tests/code/ui_services/test_status_refresh_dicom_only.py` (8) +
  `test_status_refresh_chunked.py` (5) = **13 passed** (`-p no:debugging`).
- No existing test pins the old unconditional-pop behavior (grep of `tests/` for `_local_status_cache`).
- The 7 `ui_services` collection errors in the base sandbox are pre-existing `ModuleNotFoundError:
  PySide6` (environment), unrelated to this edit.

## Acceptance / rollback

- **Acceptance (live, source build):** during active downloading + a manual status refresh, the DICOM dot
  updates correctly; no per-row attachment-walk / DB query in the refresh; `MAIN_THREAD_STALL` /
  `TABLE_REFRESH`-correlated stalls reduced vs the §13 baseline; docs/voice/ai/case/print chips still
  appear (on their own cadence). Capture a fresh probe-enabled run (`AIPACS_MAIN_THREAD_TRACE=1`).
- **Rollback:** `AIPACS_STATUS_REFRESH_DICOM_ONLY=0` (or git revert the two files).

## Remaining OPT-01 work (still open)

DM table rebuild off the GUI thread; startup `add_AIPacs_tab`/EchoMind defer (P1.4); a fresh
probe-enabled stall trace to confirm the next top synchronous call. Tracked in master plan §9 (OPT-01)
and §10 (next safe phase).

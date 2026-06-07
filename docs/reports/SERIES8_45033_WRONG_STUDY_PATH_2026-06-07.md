# 45033 — Series 8 won't load into the viewport (wrong-study path scan)

**Date:** 2026-06-07 · **Commit:** `3d335db` · **Patient:** 45033 (multi-study:
MR `…0040` series 1–8 + DOC study `1.2.826…` single series 100000)

## What the user saw
Dropping/clicking Series 8 shows the loading spinner, then nothing — the
viewport never gets the image. Other series (5, 6, 7…) load fine.

## Log + disk forensics (pid 2748, 14:38–14:47)
1. Three attempts (14:39:00 / :05 / :28) each ran the full
   `change_series_on_viewer` flow and dispatched the on-demand load.
2. The disk loader logged
   `path_scan candidates=1 probes=0 matches=0 mode=not_found` — it iterated a
   study folder containing exactly **one** subdirectory whose name doesn't
   contain "8". That folder is the **DOC study** (sole series `100000`), not
   the MR study (which had 7 series folders at that moment).
   → The tab's `import_folder_path` pointed at the sibling DOC study while
   `study_uid` was the MR study (sidebar primary = MR; DOC = offset 1100000).
3. Series 8 also wasn't downloaded with the rest of the study: series 1–7
   landed at 14:21 (open), series 8 only at **14:39:29–30** — the drop itself
   triggered its download (24 files, complete). Correct behavior.
4. But every load attempt and every progressive retry
   (`progressive-target: series=8 not in cache after load — re-armed …
   retry 1/40, spinner kept`) kept scanning the DOC folder, so the load could
   never succeed even after the files existed. The DB fallback also missed
   (queried the wrong study's pk).

## Root cause
`_load_single_series_on_demand`'s multi-study resolution corrected the study
folder **only for offset keys** (`_study_slot > 0`). A *plain* primary-
numbered series (8) trusted the tab-level `study_path` blindly — and on this
tab that path was poisoned (DOC study). Per the multi-study invariant the
series' own `_server_series_info` entry (`series_path`) is the disk
authority; the plain-key path ignored it.

## Fix
`_resolve_plain_series_study_path(series_key, study_path, entry)` in
`_vc_load.py`: when the passed study path does **not** contain `<series>/`
on disk, adopt the entry's `series_path` parent (when it exists). Wired into
the multi-study block right after the offset-key resolution. Fail-open and
zero-cost for the healthy case (a single `exists()` check). Works for
not-yet-downloaded series too, so post-download retries look in the right
place.

## Verification
- `tests/code/viewer/test_plain_series_study_path.py` — 7 green, including
  the exact 45033 layout (DOC tab path + MR entry), the not-yet-downloaded
  case, fail-open cases, and a source-ordering guard.
- `test_viewport_drop_replacement.py` still 7/7 (yesterday's drop-identity
  fix unaffected).
- Live: after the next app restart, drop Series 8 of 45033 — expect
  `[MULTI-STUDY LOAD] key=8 -> study_path=…0040 (plain-key entry
  series_path; tab path lacked series)` in viewer_diagnostics.log followed by
  `first_image_visible`. (The files are already on disk from the 14:39
  download.)

## Follow-up (task #145)
How did `import_folder_path` get re-targeted to the sibling DOC study while
`study_uid` stayed MR? Suspects: the re-open of an existing tab at 14:38:33
(`study_uids_count=1`) updating study context without syncing
`import_folder_path`, or the progressive/_vc_switch folder repair
(`_vc_switch.py:794/808`) adopting a wrong candidate. The loader fix makes
series loads immune; the origin should still be closed.

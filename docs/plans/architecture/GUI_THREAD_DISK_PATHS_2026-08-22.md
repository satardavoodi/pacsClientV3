# Three GUI-thread disk paths — 2026-08-22

Follow-up to `IMPORT_FREEZE_AND_YBR_COLOR_2026-08-21.md`. The owner reported
that lag and freezes continued, and that the app closed once.

## First: yesterday's fix landed

Sessions from 2026-08-21 15:52 onward run the new code. Counting how often each
path appears in the sampled `[MAIN_THREAD_STALL_TRACE]` stacks:

| path in the stall stack | 08-19 | 08-20 | 08-21 | 08-22 |
|---|---:|---:|---:|---:|
| `_resolve_renderable_study_path` *(fixed 08-21)* | 0 | 0 | **104** | **0** |
| `_progressive_render_next` *(fixed 08-21)* | 0 | 0 | **123** | **0** |
| `_refresh_statuses_chunked` | 2 | 0 | 0 | **45** |
| `_check_study_download_status` | 2 | 0 | 0 | **43** |
| `sync_manifest` | 2 | 0 | 0 | **46** |
| `_add_socket_patient_to_table` | 3 | 0 | 4 | **22** |
| `local_storage_cleanup_manager` | 0 | 0 | 0 | **181** |
| `shutil _rmtree_unsafe` | 0 | 0 | 0 | **114** |

The fixed paths are gone. What remained were three *different* GUI-thread disk
scanners (`tools/analysis/oneoff/verify_list_fix_live_2026_08_22.py`).

## The app "closing" was not a crash

`pid 497328` shut down cleanly at 14:17:56 — `[SHUTDOWN-INITIATOR]` from
`mainwindow_ui.closeEvent`, then `QApplication.quit()`, instance-lock release and
agent-gateway stop, all logged. But it closed in the **last four seconds of a
3.5-minute stall storm** (14:14:30–14:18:00, peak 13.1 s). The app was frozen
and was closed — by the user or by Windows' "not responding" path.

There is a separate `Windows fatal exception: access violation` at 14:42:42 in
`thumbnail_manager.CircularProgressborder.__init__` (via
`right_panel_widget.display_thumbnails_immediately`) — a **unique** signature in
a 187-record `native_fault.log`. `pid 522184` survived it and was still running
an hour later, so it is a first-chance exception, not the close. **Left
unfixed** — one occurrence, no reproduction, and speculative changes to a
widget constructor are exactly the sort of edit that creates a new bug.

The other 143 `native_fault.log` records are `code 0x8001010d`
(`RPC_E_CANTCALLOUT_ININPUTSYNCCALL`), which the app already guards against in
`right_panel_widget` and which it survives; they cluster at shutdown.

---

## A — download badges: 3.5 minutes of stalls, peak 13.1 s

```
patient_table_widget._refresh_statuses_chunked
  -> update_study_download_status
    -> _check_study_download_status -> check_study_complete
      -> sync_manifest.evaluate_sync -> build_local_manifest -> _disk_series
```

The loop was already chunked at 2 studies per `singleShot(0)` tick, with a
source comment explaining that only the *scheduling* changed and that everything
stayed on the main thread "no worker threads and no cache races". **Chunking was
not enough**: a 13.1 s gap spans one chunk, i.e. **~6.5 s per study**, because
`build_local_manifest` counts every `.dcm` of every series folder.

### Fix

* New signal `downloadStatusReady(str, str, int)` and a dedicated
  2-worker `ThreadPoolExecutor` — the same shape as the existing
  `statusFlagsReady` machinery in the same file.
* `_compute_study_download_status` is the uncached disk work and runs on the
  worker. It touches no Qt, no widget and writes no cache.
* `_peek_download_status` is a cache-read that **never computes**.
* `_refresh_statuses_chunked_impl` now either applies a fresh cached verdict or
  fires a dispatch — both microseconds. Batch size rises to 40
  (`AIPACS_STATUS_REFRESH_DISPATCH`) because a dispatch is no longer expensive.
* `_on_download_status_ready` applies the answer on the GUI thread, dropping
  results from a superseded refresh (token) or a rebuilding table.
* `refresh_download_statuses_local_only` — a **synchronous** per-row loop that
  fires immediately after a storage clear, when every row is a guaranteed cache
  miss — now goes through the same chain.

The "no cache races" property is preserved by construction: the worker computes,
the GUI thread owns every write.

Kill switch: `AIPACS_STATUS_REFRESH_OFFTHREAD=0`.

---

## B — server search: 682.5 ms of disk per row

Full sampled stack (14.2 s gap, 15:36:58):

```
_hp_search.search_patients_from_server_async
  home_search_service.search_server
    _hp_search._add_socket_patient_to_table          :1452
      _hp_search.add_data2patient_list_table         :1553
        utils.get_study_download_status              :1618
          utils.count_subfolders_with_dicom          :925
            Path.rglob('*')  ->  glob.select_recursive
```

`count_subfolders_with_dicom` answered "does this series folder contain any
`.dcm`?" with `any(p.is_file() and p.suffix.lower() in exts for p in sub.rglob('*'))`.
`rglob` materialises the walk and costs an extra `stat` per yielded entry, so a
folder with **no** DICOM (thumbnails, a partial download) paid a full recursive
enumeration — and this ran once per row while the table was built.

### Measured

`tools/analysis/oneoff/bench_count_subfolders_2026_08_22.py`, over the local
study tree, cold:

| | total | per study |
|---|---:|---:|
| `rglob` (shipped) | 8 189.9 ms | **682.50 ms** |
| `os.scandir` early-exit | 17.4 ms | **1.45 ms** |

**470× faster, 0 verdict mismatches** across every local study. Warm, it is
still 2.4× faster (42.9 ms → 18.1 ms).

### Fix

`_subfolder_has_dicom` — an iterative `os.scandir` walk that checks a
directory's **files before descending** (which is where series files actually
live) and returns on the first hit. Semantics are unchanged: "at least one
`.dcm`/`.dicom` at any depth". Unreadable directories are skipped, not raised.

Kill switch: `AIPACS_DICOM_SCAN_FAST=0` restores the `rglob` walk verbatim.

---

## C — storage cleanup: 183 seconds frozen

```
storage_cleanup_panel._on_clear_patients_clicked
  _show_patient_cleanup_dialog -> _execute_patient_cleanup
    local_storage_cleanup_manager.cleanup_patients_folder
      _clear_paths -> _clear_directory_contents -> shutil.rmtree      (108 samples)
      _cleanup_patients_db                                            ( 45 samples)
```

One click, **183 seconds** of a dead UI at 10:04. 181 of that session's 514
stall samples were this single call.

### Fix

New `_CleanupWorker(QObject)` — a sibling of the `_FolderUsageWorker` already in
that file, which was added for exactly the same reason in April. The cleanup runs
on a `QThread` behind a modal indeterminate `QProgressDialog` (no Cancel button:
`rmtree` cannot be safely interrupted mid-tree), and the completion / failure
dialogs report exactly what they did before.

Both entry points now use it — the filtered patient dialog
(`_execute_patient_cleanup`) and the per-category rows (`_handle_cleanup_action`:
patients, education, cache, printing, offline-cloud), which had the identical
inline pattern.

Safety: the manager methods are pure filesystem + DB with no Qt, and
`database/_pool.py` keeps its connections in `threading.local`, so a worker gets
its own connection. A second cleanup while one is running is refused with a
message rather than queued.

Kill switch: `AIPACS_STORAGE_CLEANUP_OFFTHREAD=0`.

---

## Guards

`tests/code/ui_services/test_gui_thread_disk_paths.py` — 27 tests.
**19 of 27 fail against the HEAD sources**
(`tools/analysis/oneoff/verify_gui_disk_guard_fails_prefix_2026_08_22.py`, which
swaps in `git show HEAD:` copies and restores them in a `finally`). The 8 that
pass are the DICOM-scan semantics guards — they pin behaviour that must be
identical before and after, which is the point of them.

Load-bearing:

* `test_the_fast_scan_does_not_use_rglob` — monkeypatches `Path.rglob` to raise.
  This is the bug itself; a "cleanup" that reintroduces `rglob` is caught.
* `test_fast_and_legacy_scans_agree` and `test_nested_dicom_still_counts` — the
  two ways the 470× speedup could have been bought with a wrong answer.
* `test_a_cold_row_is_dispatched_not_walked_on_the_gui_thread` — the fix for A,
  asserting the blocking call is *not* made.
* `test_a_late_answer_from_a_superseded_refresh_is_dropped` — without the token
  check, a stale worker result repaints a row of a table that has moved on.
* `test_cleanup_worker_reports_failure_instead_of_raising` — an exception on a
  QThread with no handler terminates the run silently.

## Known-unfixed / follow-ups

1. **Not yet observed live.** All three fixes are verified by measurement and by
   test; the running app (pid 522184, up since 14:25) still carries the old code.
   The next restart picks them up, and the same
   `verify_list_fix_live_2026_08_22.py` table will show whether these three paths
   drop to zero the way the 08-21 ones did.
2. **The 14:42:42 access violation** in `thumbnail_manager` is unexplained and
   unfixed — see above.
3. **`list_subfolders_with_dicom`** (directly below the fixed function) still
   uses the `rglob` pattern. It did not appear in any sampled stall, so it was
   left alone rather than changed on speculation.
4. **`_disk_series` / `_count_disk_instances`** in `sync_manifest` still count
   every instance; that work is now merely off the GUI thread, not cheaper. If
   the badges take too long to settle after a refresh, that is the next thing to
   make faster.
5. Six pre-existing test failures remain — four stale pins in
   `tests/code/system/test_local_search_progressive.py` and two carried from
   earlier sessions; all proved to fail at HEAD.
6. **Run-order pollution between `tests/code/ui_services|system` and
   `tests/code/viewer/test_fast_viewer_pipeline.py`.** Running the folders in
   that order makes four `test_b41_*` tests fail; the file passes in isolation
   (170 passed) and
   `tools/analysis/oneoff/check_b41_order_pollution_2026_08_22.py` shows the
   identical four failures with the working tree and with the three changed
   files reverted to HEAD. Pre-existing, unfixed, and now recorded so the next
   person does not spend an hour on it.
7. **One test was corrected, not the code**:
   `test_status_refresh_dicom_only.py::test_storage_clear_still_full_recomputes`
   searched a fixed 1,800-character window from
   `def refresh_download_statuses_local_only`; the new docstring pushed the line
   it asserts on out of range while the assertion stayed true. Re-bounded at the
   next `def` — the fourth time this exact trap has been hit in this repo.

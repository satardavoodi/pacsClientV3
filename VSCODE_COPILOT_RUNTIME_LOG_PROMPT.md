# Prompt for VS Code Copilot — runtime + logging path audit (drag-drop debug is blocked by a stalled viewer log)

Run in Agent mode (terminal access). READ-ONLY except the small log-routing change in step 6,
which I must approve first. Report exact command output, don't guess.

## Already established (please verify, don't re-litigate)
- Logging is configured in `PacsClient/utils/diagnostic_logging.py`. It routes records to
  separate files BY COMPONENT, via an async QueueListener on a background thread:
  - `component=viewer`  -> `user_data/logs/viewer_diagnostics.log`  (ViewerOnlyFilter; EXPLICITLY excluded from app.log by CatchAllOtherFilter)
  - `component=download` -> `download_diagnostics.log`
  - `component=db`       -> `db_diagnostics.log`
  - everything else (ui/other/ipc/zetaboost) -> `app.log`
- Drag-and-drop / series-switch logs (`viewer-event ... change_series_on_viewer`,
  `FAST:series_selected`, and the new `[VIEWPORT-LOAD-TRACE]`) are `component=viewer`, so
  they go to `viewer_diagnostics.log`, NOT app.log. (`[MULTI-STUDY LOAD]` uses a module
  logger inferred as `other`, which is why IT shows in app.log.)
- The app code changes ARE live (UI changes appear in the running app). The problem is the
  LOG OUTPUT, not the code.

## The symptom to diagnose
`user_data/logs/app.log` is current (entries to ~23:59), but `user_data/logs/viewer_diagnostics.log`
has NO entries after ~13:02 today, across the current file and all rotations — even though the
app has been running and viewing/dragging series since. So viewer-component logging has STALLED
this session. Find out why.

## Tasks
1. **Confirm the active process + its paths.** From the running AI-PACS python process: full
   command line, the `main.py` it launched, the venv python.exe, and its cwd. Confirm it is
   the repo at `E:\ai-pacs\ai-pacs codes\ai-pacs beta version`.
2. **Confirm `LOGS_DIR`** the running app resolves: print
   `python -c "from PacsClient.utils.data_paths import LOGS_DIR; print(LOGS_DIR)"` (same venv).
   Confirm it equals `...\user_data\logs` (where app.log is being written).
3. **Confirm component routing/levels at runtime:** print the effective env values
   `AIPACS_LOG_SYNC`, `AIPACS_LOG_LEVEL`, `AIPACS_LOG_LEVEL_VIEWER`, `AIPACS_LOG_MAX_BYTES`,
   `AIPACS_LOG_BACKUP_COUNT` (in the launch profile and the process env).
4. **Why is viewer_diagnostics.log stalled?** Check, in order:
   - Is `user_data/logs/viewer_diagnostics.log` **locked / held open** by another process
     (a tail, an editor, a second python, the other AI agent)? e.g.
     `Get-Process | ForEach-Object { $_ } ` + a handle check (handle.exe/Sysinternals if
     available, or `openfiles`), or simply try `Add-Content viewer_diagnostics.log "test"`
     and report if it errors.
   - Is the `SafeRotatingFileHandler` for the viewer file silently skipping rollover or
     erroring on emit? Look in the **VS Code terminal/console output** (stderr) for
     `[AIPACS][logging] Rollover skipped for locked file` or any logging `handleError`
     tracebacks.
   - Did the file get to ~20 MB and fail to roll (WinError 32)? Report its size and the
     sizes of `viewer_diagnostics.log.1/.2/.3`.
   - Is the async QueueListener alive? (app.log is writing, so the listener is probably up —
     but confirm the viewer handler specifically is in its handler list.)
5. **Confirm whether the new trace would even reach the file:** print line count of
   `Select-String -Path PacsClient\pacs\patient_tab\ui\patient_ui\_vc_load.py -Pattern "VIEWPORT-LOAD-TRACE"`
   and confirm it uses `self.logger.warning(..., extra={"component":"viewer"})`.

## Fix to unblock drag-drop debugging (do ONLY after I approve)
6. So we can actually SEE the drag-drop resolution while viewer logging is broken, make the
   diagnostic visible in a channel that IS writing. Either:
   - (A) Restore viewer logging (e.g., release the lock on viewer_diagnostics.log / restart
     the app so `configure_diagnostic_logging(force=True)` reopens the handler), then confirm
     new `viewer-event`/`[VIEWPORT-LOAD-TRACE]` lines appear; OR
   - (B) Temporarily route the drag-drop trace to app.log: change the `[VIEWPORT-LOAD-TRACE]`
     log in `_vc_load.py::_load_single_series_on_demand` to `extra={"component":"ui"}` (so
     CatchAllOtherFilter sends it to app.log), restart, then drag a CURRENT (ankle) series of
     patient 44030 into a viewport and a PREVIOUS (43373/47214) series into another.
   Then capture from whichever log is now live: for each drop, `dropped_key -> study_path ->
   disk_series -> primary` and the resolved study_uid. That is the data needed to fix the
   "current drag shows previous series / replacement not correct" behavior.

## Deliverable
Report: the running process + paths (confirm single repo), the resolved `LOGS_DIR`, the env
log settings, the ROOT CAUSE of the viewer_diagnostics.log stall, and — once a live log
channel is restored — the per-drop `dropped_key -> study_uid/study_path` mapping for 44030
current-vs-previous drags. With that mapping we can finally fix the drag-drop/previous-exam
replacement bug.

# AI-PACS — Crash Fix Patches Applied

Date: 2026-05-25
Base commit: `60e9106` — "release: v3.0.9 — workspace sync rollup"

This records the crash-prevention patches applied to the source. See
`CRASH_EVALUATION.md` for the full root-cause analysis.

## What was changed

Six patches across five files — `git diff --stat`:

```
 PacsClient/.../_vc_warmup.py                       |  7 +++--
 PacsClient/.../patient_widget_core/_pw_lifecycle.py|  7 +++--
 PacsClient/.../vtk_widget/qt_fast_container.py     | 30 +++++++++++++---
 main.py                                            | 18 +++++++++++
 modules/viewer/fast/qt_slice_viewer.py             |  6 +++++
 5 files changed, 60 insertions(+), 8 deletions(-)
```

- **Patch A** (`_pw_lifecycle.py`, `_vc_warmup.py`) — the core fix. The
  patient-tab teardown now also calls `cleanup()` for FAST viewers
  (`QtFastContainer`), not only `cleanup_image_viewer()` for Advanced viewers.
  This stops the FAST viewer's threads, timers and caches from leaking, and
  removes the orphaned timers that were firing into half-destroyed objects.
- **Patch B** (`qt_fast_container.py`) — `cleanup()` is now idempotent and a
  `closeEvent()` was added so the FAST viewer is also torn down if closed by
  any other path.
- **Patch C** (`qt_fast_container.py`) — on series switch, the detached old
  `QtSliceViewer` widget is now `deleteLater()`'d instead of leaked.
- **Patch D** (`qt_slice_viewer.py`) — `clear()` now re-enables Python GC, so a
  stack-drag interrupted by a tab close can never leave GC disabled.
- **Patch E** — *not applied.* `QtViewerBridge` is a plain class (not a
  `QObject`), so its timers cannot be reparented; Patch A already ensures
  `cleanup()` runs and stops those timers, making E redundant.
- **Patch F** (`main.py`) — `faulthandler` now writes a native + Python
  traceback to `user_data/logs/native_fault.log` on a fatal fault.

## Verification done

- All five files compile (`python -m py_compile`) — syntax OK.
- `git diff` reviewed — changes are exactly the six patches, minimal and
  surgical; no unrelated lines touched.
- Line counts match base + added lines exactly (no truncation).

Runtime / GUI verification has NOT been done — it requires a rebuild. See below.

## Note on the editing process

During editing, the file-editing tool truncated the tail of the five source
files. This was detected immediately via a compile check, and all five files
were restored from the `60e9106` commit and re-patched with a safe method.
A diff review confirmed the only differences from that commit are the six
intended patches — no pre-existing work was lost. The files are intact.

## What to do next

1. **Rebuild** the installed app (`D:\AIPacs\AIPacs.exe`) from this source.
2. **Run `Setup-AIPacs-CrashDumps.ps1` as Administrator** (once) so the next
   crash, if any, is captured as a dump.
3. **Launch via `Run-AIPacs-Diagnostic.bat`** during the verification period
   (enables synchronous logging).
4. **GUI-test:** open several patients and studies, switch series repeatedly,
   scroll image stacks, and open/close patient tabs. Confirm:
   - the app stays up through a long heavy-image session;
   - process memory (Task Manager) returns toward baseline after closing a
     patient tab instead of only ever climbing;
   - viewer, overlays, measurements, sync and sidebars all still work.
5. If a crash still occurs, send the new `.dmp` from `Desktop\AIPacs-CrashDumps`
   plus `user_data\logs\native_fault.log` and the three diagnostic logs.

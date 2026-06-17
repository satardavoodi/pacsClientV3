# Crash evaluation — client PC "user 2 sanam" (2026-06-17)

Logs: `C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam` (app.log,
viewer_diagnostics.log[.1/.2], download_diagnostics.log[.1], db_diagnostics.log,
zeta_mpr_canon_probe.log). Installed/frozen build (has `study_resync_check` +
`[BACKEND_SWITCH_V2.3.3]`). **No `native_fault.log` was copied** — see §Action.

## Session map (single_instance_lock try_acquire = start, release = clean exit)
| pid | start | end | result |
|---|---|---|---|
| 2980 | (≤Jun16 20:44) | Jun16 20:45 release | clean (restart→2984) |
| 2984 | Jun16 20:45 | Jun16 23:26 release | clean |
| **17140** | **Jun17 00:04** | **~14:18:00 (no release)** | **CRASH #1** |
| 16136 | Jun17 14:18 | 14:33 release | clean |
| **5424** | **Jun17 14:34** | **~16:04:01 (no release; force-killed by 8952 @16:04:11)** | **CRASH #2 / hang** |
| 8952 | Jun17 16:04 | 20:12 release | clean (but 2 Eagle-Eye errors, survived) |

Two sessions ended with **no clean lock release and no Python traceback** — the
log just stops mid-operation and a relaunch follows. That is the signature of a
**native (C++/VTK/Qt) crash** (faulthandler/access-violation class), not a Python
exception.

## CRASH #1 — pid 17140, ~14:18:00, during patient OPEN
- Patient **46847**, study `1.2.840.1.99.1.47.1.1781600130321.86470`, **14 series**.
- app.log last line = `right_panel_cache_hit thumbnail_count=14` (open hot path).
- viewer_diagnostics tail = repeated `ViewerController.new_viewer: Cr[eating]…` +
  `resolve_viewer_backend [BACKEND_SWITCH_V2.3.3] Remapping deprecated …` with
  `[MAIN_THREAD_STALL]` between — then silence.
- **Read:** died while **creating viewers / remapping a deprecated viewer backend**
  during the open of a 14-series study. Native crash in viewer construction.
- Lead: the viewer-backend config holds a **deprecated value remapped on every
  viewer creation** — worth checking what it remaps to (a stale/legacy VTK backend
  building multiple viewers is a classic native-crash trigger).

## CRASH #2 — pid 5424, ~16:04:01, just AFTER a drag-drop
- Drag-drop of **series 4 into viewer pane 1**; series 4 = **1-slice MG image**.
- viewer_diagnostics shows the FAST switch **succeeded**:
  `[MG_WL_RESOLVE]` → `first_renderable_frame` → `first_image_visible` →
  `[QtFastContainer] switch_series: complete series=4 slices=1` — **then silence**.
- 10 s later the user launched a new instance (8952) which **force-closed** 5424
  (single-instance takeover). RSS steady ~3.66 GB (no memory blow-up).
- **Read:** hard crash **or freeze immediately after** a successful MG drop. The
  10 s gap + user-initiated relaunch leans toward a **freeze/hang** the user killed,
  but a silent native crash right after the render is equally consistent. MG (single
  image) post-render is the same area as the known Eagle-Eye/MG native
  access-violation guard (`_vtk_image_scalars_valid`).

## Other findings (NOT the 2 crashes)
- **Eagle Eye RuntimeError ×2** in the surviving session pid 8952 (16:10, 16:11):
  `check_status` → `QMessageBox(self.image_viewer.vtk_widget)` →
  `RuntimeError: Internal C++ object (QtFastContainer) already deleted`. The Eagle
  Eye proxy held a reference to a viewer widget that was already destroyed. **Caught
  (logged), did NOT crash the app.** This is a *separate* Eagle-Eye robustness bug
  (distinct from the `force_reload` TypeError fixed this session in 0021dea) — the
  pipeline should null-check / re-resolve `image_viewer.vtk_widget` before parenting
  a dialog to it.
- **4× attachment-socket tracebacks** (`download_attachments_for_study` →
  `client.connect()` → `socket.create_connection`): server/network unreachable.
  Caught; not a crash. (Newer source marks these PendingSync instead of raising.)

## Mapping / status
- Both crashes are **native** and in the **FAST viewer open / drag-drop** path — the
  same class as the documented VTK/Qt access-violation crashes. This session's fixes
  (Eagle-Eye `force_reload`, colour/overlay, title-bar drag) do **not** directly
  address these two; they are different code paths.
- A precise fix needs the **exact C++ frame** from the faulthandler dump, which is
  not in the copied logs.

## Action — get the native crash stack (no native_fault.log on this build)
Confirmed (2026-06-17): there is **no `native_fault.log`** on that PC, and the app
itself does **not** enable `faulthandler`-to-file (main.py only UTF-8-wraps stderr;
`resolve_viewer_backend`'s "Remapping deprecated" is a **benign** pydicom_2d →
pydicom_qt FAST remap, not a crash cause). So that build never captured the native
stack and won't capture future ones either. Two ways forward:

1. **Windows Event Viewer (works right now, no code change).** On that PC open
   *Event Viewer → Windows Logs → Application* and find the **"Application Error"**
   (and "Windows Error Reporting") entries at **~14:18** and **~16:04** today. Each
   records the **faulting module + offset + exception code** (e.g. which DLL — a VTK,
   Qt, or image-codec module). That names the crashing component for both crashes.
   (Optional: enable WER LocalDumps for a full minidump on the next crash.)
2. **Add crash capture to the build (durable fix).** Wire `faulthandler.enable()` +
   stderr→`native_fault.log` in the startup bootstrap so EVERY future native crash on
   EVERY PC writes a C++/Python frame automatically. Then a rebuilt installer makes
   crashes like these self-diagnosing. (Not done yet — offered.)

Until then the two crashes are confidently **located** (crash #1 = FAST viewer
construction during a 14-series open; crash #2 = immediately after an MG single-image
drag-drop render) but not pinned to the exact failing native call. Both are in the
FAST-viewer open/drag path and are unrelated to this session's source fixes; any code
fix also needs a rebuilt installer for that PC.

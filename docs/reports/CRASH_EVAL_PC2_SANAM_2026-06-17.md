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

## RESOLVED — Windows Event Log crash signatures (added 2026-06-17)
The user supplied the Windows Event Log (`ai-pacs log windows 17.evtx`). It contains
**exactly two `Application Error` (ID 1000) events today**, matching the timeline
above to the second, plus their WER (1001) APPCRASH records. **Both are identical:**

```
Faulting application : AIPacs.exe   version 3.3.2.0   (D:\AIPacs\AIPacs.exe)
Faulting module      : pyside6.abi3.dll
Exception code       : 0xc0000005   (ACCESS VIOLATION)
Fault offset         : 0x000000000001bbd8   (identical both crashes)
Fault bucket         : 1852635332239126229  (identical both crashes)
Crash #1  14:18:00   faulting pid 0x42F4 = 17140  (patient open)
Crash #2  16:04:01   faulting pid 0x1530 = 5424   (MG drag-drop)
```

**Root cause (now confirmed, unified):** both crashes are the **same** native
access violation **inside PySide6** (`pyside6.abi3.dll`) at the same offset — i.e.
a **use-after-free of a Qt object**: PySide6 dereferences a C++ object that has
already been deleted. The catchable Python form of the very same defect is in the
app log (`RuntimeError: Internal C++ object (QtFastContainer) already deleted`,
`ai_chat_interactorstyle.py:check_status`) — when the freed object is touched at the
C++ level instead of via the Python wrapper, it is a hard `0xc0000005` crash. The
two triggers are the FAST-viewer lifecycle: rapid viewer build/teardown on a
14-series open (#1) and the deferred drag-drop series-switch / dialog parenting (#2).

**Fix applied (this session):** `AIChatInteractorStyle._live_dialog_parent()` —
guards the three Eagle-Eye dialog-parent sites with the established
`shiboken6.isValid(...)` liveness check (same idiom as
`_hp_layout.py::_hide_loading_overlay`), so a dialog is never parented to a freed
viewer widget. This removes the one **corroborated** UAF site (the logged
RuntimeError) and reuses the proven pattern. Guard test
`tests/code/viewer/test_eagle_eye_dialog_parent_liveness.py` (3 green).
`modules/viewer` is not plugin-mirrored. Needs a rebuilt installer to reach that PC.

**Still open (needs the WER minidump to pin exactly):** the two HARD crashes were at
patient-open (#1) and the MG drag-drop (#2) — different sites from the (caught)
Eagle-Eye dialog one. Offset `0x1bbd8` resolves to a specific PySide6 call only with
the crash **minidump** (see below) + PySide6 symbols. The fix above is the same
*class* but not proven to be the exact #1/#2 site.

## Action — get the exact crashing call (minidump)
Confirmed (2026-06-17): there is **no `native_fault.log`** on that PC, and the app
itself does **not** enable `faulthandler`-to-file (main.py only UTF-8-wraps stderr;
`resolve_viewer_backend`'s "Remapping deprecated" is a **benign** pydicom_2d →
pydicom_qt FAST remap, not a crash cause). So that build never captured the native
stack and won't capture future ones either. Two ways forward:

WER already wrote **minidumps** for both crashes (referenced in the 1001 records).
On that PC, copy the two archives (each has a `.mdmp`):
`C:\ProgramData\Microsoft\Windows\WER\ReportArchive\AppCrash_AIPacs.exe_*` — the
ones with Report Ids `e3b51d5c-…` (14:18) and `a6b71d3b-…` (16:04). Opening a `.mdmp`
in WinDbg/Visual Studio with the build's PySide6 symbols resolves `pyside6.abi3.dll
+0x1bbd8` to the exact Qt call, which pins the #1 (open) and #2 (drag) sites so the
remaining UAF site(s) can be guarded precisely.

**Durable diagnosability (recommended):** the app does NOT enable
`faulthandler`-to-file, so this build never wrote `user_data\logs\native_fault.log`
(why none was found). Wiring `faulthandler.enable()` + a `native_fault.log` writer in
startup would make every future native crash self-record a frame on every PC. Offered,
not yet done.

Any code fix also needs a **rebuilt installer** to reach that 3.3.2.0 PC.

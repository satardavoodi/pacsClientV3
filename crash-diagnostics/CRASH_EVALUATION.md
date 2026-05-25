# AI-PACS — Crash-Prevention Evaluation

Date: 2026-05-25
Build evaluated: installed `D:\AIPacs\AIPacs.exe` (rebuilt 2026-05-25 09:57) and the
matching source tree at `E:\ai-pacs\ai-pacs codes\ai-pacs beta version`.
Scope: read-only evaluation. **No application code was changed.** The fixes below
are presented as ready-to-apply patches for your approval.

Companion document: `CRASH_ANALYSIS_2026-05-25.md` (workspace root) — the raw
log/crash-dump analysis. This document is the evaluation and the action plan.

---

## 1. Executive summary

The auto-close is a **real crash** (a hard, native-level process kill), not a normal
shutdown. The investigation found **one root cause** that explains both the crash and
the steadily-growing memory:

> **The FAST viewer is never cleaned up when a patient tab is closed.**
> Its background threads, timers and image caches are leaked, and orphaned timers
> keep firing into a half-destroyed viewer — which is what crashes the process.

This is a **code defect**, verified directly in the source (details in §3). It is
fixable with a small, low-risk change. Three secondary issues amplify it (§4).

Two things were done now, with no code change and no rebuild, so the **next** crash
is captured with certainty (§6): a crash-dump capture script and a diagnostic
launcher.

---

## 2. What the crash looks like (recap)

Three crashes were captured in one day's logs. Every one:

- ends **abruptly, mid-operation**, while switching series or scrolling the image
  stack — i.e. during heavy image work;
- leaves **no Python error and no shutdown marker** — the process is killed at the
  native level;
- follows a session in which **memory climbed continuously** (≈510 MB → 1 GB+ over
  the session, never falling back).

A crash dump on disk (from 2026-05-19/20) confirms the native signature:
exception **`0xC0000409` (fail-fast) inside `Qt6Core.dll`** — an instant, silent
process kill. The machine has 64 GB RAM, so this is **not** an out-of-memory by the
operating system; it is a software fault.

---

## 3. Root cause (CONFIRMED)

### The defect

When a patient tab closes, AI-PACS tears down each viewer cell here:

`PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_lifecycle.py:263`
```python
if vtk_widget is not None and hasattr(vtk_widget, 'cleanup_image_viewer'):
    try:
        vtk_widget.cleanup_image_viewer()
    except:
        pass
```
The same pattern exists in `_vc_warmup.py:867` (`cleanup_all_viewers`).

The teardown only ever calls a method named **`cleanup_image_viewer()`**. That method
belongs to the *Advanced* viewer (`VTKWidget`). But in **FAST mode** the viewer cell
is a different class — `QtFastContainer` — which was verified to be:

- `class QtFastContainer(QWidget)` — `qt_fast_container.py:103` — a plain widget,
  **not** a `VTKWidget`, so it does **not** inherit `cleanup_image_viewer`;
- its real teardown method is `cleanup()` — `qt_fast_container.py:1006` — which calls
  `self._qt_bridge.cleanup()` → the pipeline's `shutdown()`.

So for every FAST-mode patient, `hasattr(vtk_widget, 'cleanup_image_viewer')` is
**False**, the branch is skipped, and **`QtFastContainer.cleanup()` is never called.**
`QtFastContainer` also has no `closeEvent`, so nothing else triggers it either.

### Why this crashes the app

Because `cleanup()` never runs, each closed/switched FAST viewer leaves behind, still
alive and still running:

- the decode / frame / grow **thread pools** of the `Lightweight2DPipeline`;
- the **QTimers** `_interaction_settle_timer` and `_fast_render_clock_timer`
  (the render clock is repeating — it keeps firing);
- the in-memory **pixel/frame caches** (the pipeline's own header budgets these at up
  to ~384 MB per viewer).

The leaked timers and threads keep emitting Qt signals at objects whose underlying
C++ half is being destroyed by the layout teardown. Delivering a Qt event to an
already-deleted C++ object is an access-after-free — and Qt responds to that class of
fault with the exact `0xC0000409` fail-fast seen in the crash dump. The longer the
session and the more patients/series opened, the more orphaned timers exist and the
larger the leaked caches grow — which is precisely why the app survives a short
session but auto-closes after "a while with heavy images."

This single defect explains **both** symptoms: the monotonic memory growth (leaked
caches/threads) and the native crash (orphaned timers firing into dead objects).

---

## 4. Contributing issues (code audit)

These were identified in the code audit. They are real and worth fixing, but
secondary — fixing §3 is what stops the crash. Confirm each while patching.

**4a. Series switch drops the old viewer without `deleteLater()`** —
`qt_fast_container.py:356-364` and `481-489`. On each series switch the previous
`QtSliceViewer` widget is detached (`setParent(None)`) but never `deleteLater()`'d, so
its C++ object lingers and a late queued repaint/timer signal can hit it — another
access-after-free path, plus a per-switch widget leak.

**4b. `gc.disable()` can be left permanently off** —
`qt_slice_viewer.py` (`_begin_stack_drag_session` ~894, re-enabled only by a 1.5 s
timer). If the tab/viewer is destroyed during a stack drag or within that 1.5 s
window, the re-enable timer dies first and Python's garbage collector stays disabled
for the rest of the process — so every reference cycle leaks. A strong secondary
contributor to the memory growth.

**4c. Bridge QTimers created without a parent** —
`qt_viewer_bridge.py:624,630`. `_interaction_settle_timer` and
`_fast_render_clock_timer` are `QTimer()` with no parent, so Qt cannot stop/destroy
them with the bridge if `cleanup()` is skipped (§3). Parenting them to the bridge is a
cheap safety net.

---

## 5. What was checked and found SAFE

So the report is balanced — these were suspected but are **not** problems:

- **FAST mode does not instantiate VTK render windows.** `QtFastContainer` uses null
  stub objects for `render_window`/`renderer`/`interactor`
  (`qt_fast_container.py:153-154,238`). The project's FAST/VTK rule is being honoured.
- **The `QImage`-over-numpy-buffer pattern is correct.** `lightweight_2d_pipeline.py`
  pins the backing array (`qimg._np_buffer = arr`, lines 522/548) and the display copy
  goes through `QPixmap.fromImage()` (a deep copy). Not a crash source.
- **`DiskPixelCache` is properly LRU-bounded.** Not a leak source.
- **The existing crash handlers are well-built** — a `sys.excepthook` override and a
  `QApplication.notify()` wrapper (`main.py:706,797`) that capture Python tracebacks
  from Qt event dispatch. They are good. Their limits are covered in §6.

---

## 6. Done now — capturing the next crash (no code change, no rebuild)

Two files were created in this `crash-diagnostics\` folder. Together they guarantee
the next crash is fully diagnosable.

**`Setup-AIPacs-CrashDumps.ps1`** — run **once, as Administrator**. It registers
Windows Error Reporting "LocalDumps" for `AIPacs.exe`, so any future crash
automatically writes a `.dmp` file to `Desktop\AIPacs-CrashDumps`. That dump names the
exact faulting function. Fully reversible (the script prints the undo command).

**`Run-AIPacs-Diagnostic.bat`** — use this **instead of the normal shortcut** during
the diagnostic period. It sets `AIPACS_LOG_SYNC=1`, which makes the diagnostic logs
write synchronously. This matters: AI-PACS logs through an *asynchronous* background
queue, so on a hard crash the last records are still in memory and are lost — which is
**why the current logs go quiet instead of showing the crash**. With sync logging the
logs keep the true final events. (Minor side effect: slightly less smooth scrolling;
temporary.)

Why this is still worth doing even though the root cause is known: it converts a
"very likely" into a "certain", and it will confirm whether §4a/§4b also contribute.

A residual gap to be aware of: the existing crash handlers log through that same async
queue, and a **native** fail-fast bypasses Python handlers entirely. Patch F in §7
closes that gap for future builds.

---

## 7. Recommended fixes (patches for your approval — NOT yet applied)

Per the agreed scope, no clinical/viewer code was modified. Below are the proposed
changes. **Patch A is the fix**; the rest is hardening.

### Patch A — call the right teardown method for FAST viewers (THE fix)
`_pw_lifecycle.py:263` and `_vc_warmup.py:867` — broaden the guard:
```python
# before
if vtk_widget is not None and hasattr(vtk_widget, 'cleanup_image_viewer'):
    try:
        vtk_widget.cleanup_image_viewer()
    except:
        pass
# after
if vtk_widget is not None:
    try:
        if hasattr(vtk_widget, 'cleanup_image_viewer'):
            vtk_widget.cleanup_image_viewer()   # Advanced viewer (VTKWidget)
        elif hasattr(vtk_widget, 'cleanup'):
            vtk_widget.cleanup()                # FAST viewer (QtFastContainer)
    except Exception:
        pass
```
Minimal and regression-safe: the Advanced path is unchanged; FAST viewers finally get
torn down. This is the change that stops the leak and removes the orphaned timers.

### Patch B — belt-and-suspenders `closeEvent` on `QtFastContainer`
Add a `closeEvent` to `QtFastContainer` that calls `self.cleanup()`, so the FAST
viewer is also torn down if it is closed by any path other than §3's loop.

### Patch C — destroy the old viewer on series switch (§4a)
In `qt_fast_container.py` (~356-364 / ~481-489), after `cleanup()` and before the
reference is overwritten, call `old_qt_viewer.setParent(None); old_qt_viewer.deleteLater()`.

### Patch D — always re-enable GC (§4b)
In `QtSliceViewer.clear()` and in a cleanup/`closeEvent` hook, unconditionally call the
existing idempotent `_reenable_gc_after_drag()` so GC can never be left disabled.

### Patch E — parent the bridge timers (§4c)
In `qt_viewer_bridge.py:624,630`, construct the two timers as `QTimer(self)`.

### Patch F — native-fault logging for future builds
Early in `main.py`, add `faulthandler.enable(file=<crash log file>)` and route the
`aipacs.crash` logger to a small synchronous file handler. This makes even a native
fail-fast leave a trace on disk. Touches only crash/log code, not the viewer.

**Suggested order:** apply **A + B**, rebuild, and verify with the diagnostic launcher
that memory now returns to baseline after closing a patient tab and that the app
survives a long heavy-image session. Then apply C–F as hardening. Each should be
followed by the existing GUI/multi-patient/multi-study test workflow before shipping.

---

## 8. Honest statement of certainty

- **Certain:** FAST viewers are not torn down on tab close (verified in source); this
  causes the monotonic memory growth.
- **Certain:** the auto-close is a native `0xC0000409` fail-fast in Qt (crash dump).
- **Strong inference, not yet proven to the line:** that the orphaned FAST-viewer
  timers/threads firing into destroyed objects are what triggers that specific
  fail-fast. The crash-dump capture from §6 will confirm the exact faulting stack.
- Patch A addresses the verified defect regardless, and is low-risk on its own.

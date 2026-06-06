# AI-PACS Crash & Stability Investigation — 2026-06-03

**Scope:** thumbnail → patient-open → drag-and-drop → viewport pipeline, plus
multi-patient/MPR and the remote 150 %-scaling workstation.
**Method:** today's logs — `native_fault.log` (faulthandler dumps), `app.log`,
`viewer_diagnostics.log`, `download_diagnostics.log`, `com_trace.log` — plus targeted
source review. No code was changed in this pass; this is the requested report.

---

## Executive summary

- **161 app starts logged today** (`Logging configured`), i.e. the app was relaunched
  dozens of times — confirming the repeated closures.
- The crash log is **dominated by native `0x8001010d` (RPC_E_WRONGTHREAD — a COM object
  used from the wrong thread)**, with a secondary cluster of **`access violation`** faults
  in **background worker threads**, plus one **Qt event-dispatch exception cascade**
  (menu/teardown). These are three distinct root causes.
- **The COM tracer caught NO Python-level COM calls** off-thread — so `0x8001010d` is a
  **native/C++ COM violation** (Windows OLE drag-and-drop, or a Qt native-window/widget
  object touched from a non-GUI thread), not a `pythoncom`/`win32com` call.
- The **access violations** sit in concurrent download/cache workers
  (`disk_pixel_cache._write_worker`, `socket_client._recv_exact`,
  `upload_download_attchments._recvall`) — consistent with **use-after-free / object-
  lifecycle races during tab close/switch** (the multi-patient + MPR close scenario).
- **150 % scaling:** the app sets **no explicit high-DPI policy** anywhere in `main.py`;
  under Qt6 fractional scaling this is a plausible contributor to drag-target mismapping
  on the remote workstation, but it is **not** the dominant local crash cause.
- **Thumbnail ↔ double-click race:** confirmed mechanism — a new patient click
  **cancels the prior in-flight thumbnail fetch** (`_hp_series.py:913
  _current_thumbnail_task.cancel()`); on slow networks an interrupted fetch can leave
  thumbnails incomplete.
- Separately, the earlier **Proxifier `WinError 5` spawn crash** is environmental and was
  resolved by closing Proxifier (keep it off / exclude the venv python).

---

## 1. Crash inventory (2026-06-03)

| # | Crash family | Evidence | Severity | Reproducible |
|---|---|---|---|---|
| A | **`0x8001010d` COM wrong-thread** | Dominant signature in `native_fault.log` (most `Windows fatal exception` headers) | **Critical** | Intermittent under fast interaction / drag-drop / multi-patient |
| B | **`access violation`** in bg workers | dumps: `disk_pixel_cache._write_worker`, `socket_client._recv_exact`, `upload_download_attchments._recvall` under `_zb_workers._worker_loop` / `_hp_download._worker` | **Critical** | Multi-patient + MPR + close/switch while downloads/writes in flight |
| C | **Qt event-dispatch exception cascade** | `app.log` 15:48:48–50: flood of `EXCEPTION in Qt event dispatch (QMenu/QAction/QWidget…)` → `UNHANDLED EXCEPTION (will propagate to Qt)` | **High** | Context-menu / rapid UI during widget teardown |
| D | **`WinError 5` spawn (Proxifier)** | (earlier) `multiprocessing.spawn … Access is denied` | Critical (env) | **Resolved** by closing Proxifier |

This is a **long-standing** family, not new today: prior validation already recorded
`0x8001010d ×97`, and the Eagle-Eye/MG mirror was previously found to cause `0x8001010d`
and fixed by deferring the mirror via `QTimer.singleShot(0)`.

---

## 2. Crash A — `0x8001010d` (COM called from the wrong thread) — CRITICAL

**Finding.** The most frequent fatal exception today is `0x8001010d` (`RPC_E_WRONGTHREAD`):
a COM interface created on the main STA apartment was invoked (or released) from a
different thread.

**Root cause.** The dedicated `com_trace.log` wraps every Python COM entry point
(`pythoncom`/`win32com`/`comtypes`) and recorded **no off-thread Python COM call** — only
the install and a main-thread `CoInitialize`. Therefore the violation is in **native code**:
the most likely sources, given the workflow, are
(a) **Windows OLE drag-and-drop**, which is COM-based — a drag object created/owned by the
GUI thread being touched from a worker (or released during teardown on the wrong thread);
(b) a **Qt object backed by a native window/COM** (e.g. a widget, the system tray, a file
dialog, or clipboard) accessed from a background thread; or
(c) a **deferred callback** that runs on a worker and reaches into a GUI/COM object.

**Triggering workflow.** Drag-and-drop into a viewport, and rapid UI actions during
multi-patient use — exactly the paths flagged.

**Reproducibility.** Intermittent (timing/race dependent), more likely under fast user
interaction; the Eagle-Eye mirror precedent shows synchronous cross-thread/native work in
a drag path reproduces it.

**Recommended fixes (conservative, staged).**
1. **Marshal all GUI/COM touches to the main thread.** Audit drag-drop handlers, the
   Eagle-Eye/MG mirror, and any worker `done`/progress callback for direct calls into
   QWidgets / OLE drag objects; route them via `QTimer.singleShot(0, …)` or a queued
   signal (the proven pattern from the Eagle-Eye fix).
2. **Add a debug `qInstallMessageHandler` + keep the COM tracer**, and extend the native
   crash dump to record the **faulting thread's** stack distinctly (today the dump's
   "Current thread" was sometimes the stall-sampler, masking the true faulting frame).
3. **Verify the Eagle-Eye/MG deferred-mirror fix is still in place** (possible regression).

---

## 3. Crash B — access violations in background workers (use-after-free) — CRITICAL

**Finding.** Several `access violation` faults occurred inside background worker threads.
Representative stacks:

```
disk_pixel_cache.py:_write_worker
socket_client.py:_recv_exact ← send_request ← get_report_status
  ← _hp_download._download_reception_data_for_targets ← _zb_workers._worker_loop

_pw_thumbnails.py:_worker ← reception_data_service.run
  ← upload_download_attchments._recvall ← download_attachments_for_study
  ← _hp_patient_open._worker ← download_process_worker.run ← _zb_workers._worker_loop
```

**Root cause (most likely).** **Object-lifecycle / use-after-free race on tab close or
study switch.** Multiple long-lived worker pools (`_zb_workers`, `_hp_download._worker`,
`_pw_thumbnails._worker`, `reception_data_service`) hold references to buffers / pixel data
/ sockets that the **main thread frees** when a patient tab or viewer is torn down. If a
worker writes to `disk_pixel_cache` or recvs into a buffer that has just been freed, the
result is an access violation. `socket_client` itself holds an `RLock`, but the
**attachments path (`upload_download_attchments`) is a separate socket path** and the
disk-cache writer is a separate worker — so the protection is not uniform.

**Triggering workflow.** Multiple patients open + MPR + closing/switching tabs while
downloads, report-status fetches, attachment fetches, or pixel-cache writes are still in
flight — i.e. the exact "multi-patient / MPR → close → crash" scenario.

**Reproducibility.** Reproducible under load: open ≥2–3 patients, start MPR, then close a
tab while its series are still downloading.

**Recommended fixes (conservative).**
1. **Cancel + join workers before freeing their data on tab close.** In the patient-tab /
   viewer teardown, set a cancel flag, then ensure `disk_pixel_cache._write_worker`,
   reception/attachment workers, and `_zb_workers` for that study have stopped **before**
   releasing the pixel/VTK buffers and sockets they reference.
2. **Guard worker bodies against freed state.** In `_write_worker` / `_recv_exact` /
   `_recvall`, check a "still alive / not cancelled" flag and hold a strong reference to the
   target buffer for the duration of the write/recv (no reading through a weakref that the
   main thread may have cleared).
3. **Single owner for each socket.** Ensure the attachments/reception socket path is not
   shared across workers without a lock, mirroring `socket_client`'s `RLock`.

---

## 4. Crash C — Qt event-dispatch exception cascade — HIGH

**Finding.** At 15:48:48–50 the log shows a dense burst of
`EXCEPTION in Qt event dispatch (receiver=QMenu/QAction/QWidget/QWindow/QLineEdit, …)`
ending in `UNHANDLED EXCEPTION (will propagate to Qt)`.

**Root cause.** A single exception thrown while a **context menu / popup was being torn
down** kept re-raising as Qt delivered subsequent events (style/paint/hide/childRemoved)
to a **partially-deleted widget**. This is a deleted-C++-object access surfacing through
the Python event filter.

**Severity/repro.** High; reproduces when a menu/popup is dismissed during a state
transition (e.g. right-click then immediately switch patient/close).

**Recommended fix.** In the `QApplication.notify` override, swallow-and-log per-event
exceptions so one bad event cannot cascade; and ensure menus/popups are parented and
`deleteLater()`-d (not deleted synchronously) so in-flight events find a live object.

---

## 5. Remote workstation — 150 % Windows scaling — HIGH (on that machine)

**Finding.** `main.py` sets **no high-DPI policy** (no `AA_EnableHighDpiScaling`, no
`setHighDpiScaleFactorRoundingPolicy`, no DPI-awareness manifest found). Under Qt6,
high-DPI is on by default with **fractional** rounding (1.5×) permitted.

**Assessment.** Toolbar/popup positioning uses `mapToGlobal` (DPI-aware, fine). The risk is
**viewport drop hit-testing / drag-target calculation** under fractional 1.5× scaling: any
place that mixes raw device pixels with logical points (or assumes integer DPR) can mis-map
the drop point, so the series "drops" outside the target viewport — the series doesn't load,
and a bad coordinate can index out of range. Combined with the native OLE-drag COM (Crash A),
150 % amplifies instability on that machine. **It is a real contributor on the remote box,
but not the dominant local crash cause.**

**Recommended fixes.**
1. Set a **deterministic rounding policy** at startup
   (`QGuiApplication.setHighDpiScaleFactorRoundingPolicy(PassThrough)` — and keep it
   consistent), before `QApplication` is created.
2. **Audit the viewport drop path** to use Qt-native `mapFromGlobal`/widget-local
   coordinates and `devicePixelRatioF()` where pixel math is unavoidable; never assume DPR ∈ {1,2}.
3. Test at 100 %, 150 %, 200 % with the same drag workflow; confirm the drop lands in the
   viewport and no out-of-range index occurs.

---

## 6. Thumbnail ↔ double-click race (slow network) — MEDIUM

**Finding.** `_hp_series.py:907–921`: when a patient row is (single-)clicked, the handler
**cancels the previous in-flight thumbnail task** (`self._current_thumbnail_task.cancel()`)
before starting the new one. Qt delivers the first press of a double-click as a single
click, so a quick **click → double-click(open)** sequence can cancel a thumbnail fetch that
is still downloading; on a **slow network** the fetch is aborted mid-flight and the patient
opens before it completes.

**Root cause.** Thumbnail completion is coupled to Home-page interaction state: the fetch is
cancelled on the next click/transition, and the Home→Patient transition does not guarantee
the thumbnail load is re-driven to completion. (The patient-tab sidebar has an
18-attempt deferred re-poll, which usually recovers, but the **Home-page right-panel** fetch
is the one cancelled and not resumed.)

**Reproducibility.** Hard locally (fast LAN), easy on a throttled/slow link — matches the
report.

**Recommended fixes.**
1. **Do not cancel a thumbnail fetch for the patient that is being opened** — let it finish,
   or hand its result to the opening tab.
2. **Decouple thumbnail completion from Home-page residency:** the patient page should
   re-drive its own series-thumbnail load on open regardless of the Home fetch state
   (and it should not depend on a cancelled Home task's result).
3. Make the cancel **idempotent + resumable**: on cancel, record what was pending so the
   patient page can resume it instead of starting from zero.

---

## 7. Pipeline reliability review & prioritized recommendations

**Home → thumbnail request → display:** mostly healthy; the one defect is the cancel-on-
reclick race (§6). Fix = don't cancel the opening patient's fetch + re-drive on the tab.

**Home → double-click → open → download start:** functionally working (warmup, cross-patient
guard, preempt are in place from prior work); the risk here is the **open + drag-drop +
teardown** timing that feeds Crashes A/B.

**Viewer → drag-drop → escalation → viewport load:** this is where Crash A (native COM
wrong-thread) and the 150 % drag-target issue concentrate. Highest crash-resistance ROI.

**Viewer → MPR → multi-patient → close/open:** this is where Crash B (worker use-after-free)
concentrates. Cancel+join workers before freeing buffers is the key fix.

**Prioritized fix order (by crash-resistance ROI, all conservative):**

1. **(B) Cancel + join background workers before tab/viewer teardown frees their buffers.**
   Eliminates the access-violation family. Highest value, self-contained per teardown path.
2. **(A) Marshal every GUI/COM touch in drag-drop + worker callbacks to the main thread**
   (`singleShot(0)` / queued signal). Re-verify the Eagle-Eye deferred-mirror fix.
3. **(C) Make `QApplication.notify` swallow-and-log per-event exceptions** so a deleted-widget
   event can't cascade into a crash; `deleteLater()` menus/popups.
4. **(DPI) Set a deterministic high-DPI rounding policy + audit viewport drop hit-testing**
   for the 150 % machine.
5. **(Thumbnail race) Don't cancel the opening patient's thumbnail fetch; re-drive on the tab.**

**Verification approach (given the crash history):** apply ONE fix at a time, compile-check
on the venv, then a live multi-patient + drag + MPR + close soak with `native_fault.log`
watched — confirm the targeted family's signature count drops to zero before moving on.
Keep Proxifier OFF during testing (it independently injects `WinError 5` spawn crashes).

---

## Appendix — key evidence

- App starts today (`Logging configured`): **161** in the current tail (rapid clusters
  15:23–16:09).
- `native_fault.log`: 158 fatal/timeout markers, overwhelmingly `0x8001010d`, several
  `access violation`.
- `com_trace.log`: only `install:` lines + one main-thread `CoInitialize` test → **no
  off-thread Python COM** → native COM source.
- Access-violation worker stacks: `disk_pixel_cache._write_worker`,
  `socket_client._recv_exact`/`send_request`/`get_report_status`,
  `upload_download_attchments._recvall`, under `_zb_workers._worker_loop`.
- Qt cascade: `app.log` 15:48:48–50 (`QMenu`/`QAction`/`QWidget` exception flood).
- DPI: no high-DPI policy in `main.py`.
- Thumbnail cancel: `_hp_series.py:913 self._current_thumbnail_task.cancel()`.

---

## 8. Fix log — 2026-06-03 (Crash B, access-violation family)

The three worker leaves from §3 / Appendix were triaged individually — they are **not** the
same defect:

**(B1) `disk_pixel_cache._write_worker` — REAL use-after-free → FIXED (compile-verified, venv).**
`modules/viewer/fast/disk_pixel_cache.py`. `DiskPixelCache.put(defer=False)` enqueued the
**raw `arr` reference** onto `_write_queue`; the single writer thread copied it only after
dequeue (`arr.copy()`). In the window between enqueue and that copy, a viewer/tab teardown can
free the numpy pixel buffer, so the writer's later copy reads freed memory → access violation.
This leaf is on the FAST viewport/drag path.
*Fix (minimal, behaviour-preserving):* relocate the copy to **enqueue time** —
`np.ascontiguousarray(arr).copy()` inside `put()` — and drop the now-redundant worker-side
copy. Net copies stay at exactly one, moved to *before* the UAF window. The `defer=True`
(`_defer_write`) and `flush_deferred` producers already copied at enqueue, so all three
producers now hand the queue an independent, contiguous buffer. No teardown join was added:
the writer is a **singleton daemon** (not per-tab, nothing to join on tab close), and
`_write_file` writes atomically (`.part` → `os.replace`), so an abrupt daemon kill at
interpreter exit cannot corrupt the cache. **Live soak pending** (Proxifier OFF; watch
`native_fault.log` for recurrence of this leaf).

**(B2) `socket_client._recv_exact` — NOT A BUG (red herring).**
`modules/network/socket_client.py`. `disconnect()` (L69) and `send_request → _recv_exact`
(the `recv_into` at L96) share the **same per-client `threading.RLock`** (L34), so a
close-during-recv is already serialized — it cannot fault. `buf` is a per-call **local**
bytearray on the recv thread's stack, never shared. This leaf is simply a recv thread parked
in `recv_into` and captured in the all-thread fault dump while another thread faulted. No
change made.

**(B3) `upload_download_attchments._recvall` — latent UAF, OFF the crash path, deferred.**
`modules/network/upload_download_attchments.py` defines its own `SocketClient` (L21) with
**no lock**; `disconnect()` (L75) does `self.socket.close()` then `self.socket = None`, which
can deallocate the socket while another thread is blocked in `self.socket.recv()` (L69, GIL
released) → access violation. However this is the **attachments upload/download side-channel**,
not the thumbnail → open → drag → viewport path where the crashes cluster, and it touches
clinically-critical networking. Deferred to its own isolated change: first confirm whether a
single instance is used across threads, then guard with a lock and call
`socket.shutdown(SHUT_RDWR)` before `close()`. Tracked separately.

**Discipline:** one fix per live soak (batching multiple edits onto the crash-prone drag path
is what forced the 2026-05-31 reverts). Next per §7 order: **Crash A** (locate the concrete
off-main-thread GUI/COM touch in the drop handler / worker callback and defer it via
`QTimer.singleShot(0)`; re-verify the Eagle-Eye deferred mirror), then C, DPI, thumbnail race.

---

## 9. Crash A scoping — 2026-06-03 (read-only; fix candidate identified, NOT applied)

**native_fault is blind to this crash.** All 4 most-recent `0x8001010d` dumps contain only
three Python threads with frames: `main.py:1248 _f11_sampler` (stall sampler),
`diagnostic_logging.py:628 _run` (logger), and **`main.py:1497 <module>`** = the main thread
parked in `app.exec()`. faulthandler only dumps threads that hold a Python frame, so a native
(non-Python) faulting thread is invisible, and there is **no Python worker mid-GUI-call**. The
wrong-thread COM call is therefore in **native code** — consistent with §2.

**The drop side is clean.** `_vw_dragdrop.py::dropEvent` already defers the series switch via
`QTimer.singleShot(0, _do_series_switch)`; every handler runs on the GUI thread. Not the cause.

**Root mechanism (high confidence): the thumbnail→viewport drag does not arm the
`protected_drag` latch.** The drag SOURCE is `thumbnail_manager.py::mouseMoveEvent` (~L600),
which builds a `QDrag` and calls `drag.exec(Qt.CopyAction)` (~L620) on the main thread.
`drag.exec()` spins the **native OLE `DoDragDrop` nested modal loop**; while it runs, queued
timers and worker→main signals (download-complete → FAST grow / prefetch / viewport rebuild /
DM table refresh / thumbnail widget create+destroy) keep dispatching and re-enter native
window/COM operations inside the drag's OLE apartment → `0x8001010d` / access violations.
The codebase ALREADY has the right guard — `modules/viewer/fast/ui_throttle.py`
`record_protected_drag()/keepalive_protected_drag()/is_protected_drag_active()` — and it is
armed for the **FAST stack-drag** (`qt_slice_viewer.py:893 True / :940 False / :1739 keepalive`)
so those gates suppress re-entrant work during *that* drag. **It is NOT armed around the
thumbnail `drag.exec()`** — so the inter-widget drag (the user's exact repro) runs the OLE loop
fully unguarded.

**Fix candidate A2 (ready, conservative, reuses the proven API — NOT yet applied):** wrap the
thumbnail `drag.exec()` so the inter-widget drag becomes a protected drag like the stack-drag:
```python
from modules.viewer.fast import ui_throttle
ui_throttle.record_protected_drag(True, grace_ms=1500.0)
try:
    drag.exec(Qt.CopyAction)
finally:
    ui_throttle.record_protected_drag(False, grace_ms=250.0)
    self._drag_start_pos = None
```
Localized (one call site), no new mechanism, and the 250 ms tail keeps suppression active while
the deferred series-switch `QTimer(0)` runs. Existing `is_protected_drag_active()` gates then
suppress the re-entrant rebuilds during the OLE loop. The terminal/completion-signal path stays
open (`ui_throttle.py:430 if not terminal and is_protected_drag_active()`), so downloads still
complete; only non-terminal coalescible work is deferred.

**Parallel zero-risk step A1 (recommended first): make the faulting thread visible.** Current
dumps can't identify the native faulting thread, so A2 (and any COM fix) is an evidence-backed
hypothesis, not a stack-confirmed one. Extend the crash dump (Windows vectored-exception handler
logging the OS thread id + native backtrace for `0x8001010d`, and/or `qInstallMessageHandler`)
so the NEXT recurrence is actionable / confirms A2. Diagnostics only — no behaviour change.

**A3 note:** the `0x8001010d` "Eagle-Eye mirror" from memory ≠ the AI `_trigger_eagle_eye_
analysis_pipeline` (`toolbar_manager.py:7421`); the MG mirror path is separate. If A2 lands,
a mirror rebuild firing during the drag loop would already be suppressed by the armed latch, so
A3 is likely subsumed — confirm during the A2 soak rather than as a separate edit.

**Sequencing:** do NOT stack A2 onto the disk_pixel_cache (B1) soak — soak B1 first, then apply
A2 as its own iteration (optionally with the zero-risk A1 diagnostics alongside).

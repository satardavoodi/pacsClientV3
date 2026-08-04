# Eagle Eye mammography → server request can CRASH the Python process (OPT-51)

**Date:** 2026-08-03
**Reported:** "In some cases the Python process involved in Eagle Eye crashes while the request is
being executed… duplicate uploads / stuck requests / uncontrolled retries."
**Status:** FIXED, default-on (`AIPACS_EAGLE_WORKER_LIFECYCLE`), guard-tested. **NEEDS live verify.**
**File:** `modules/viewer/interactor_styles/ai_chat_interactorstyle.py` (**plugin-mirrored** — synced, 422/422).

---

## How the pipeline actually works (important for scoping)

The client does **NOT** prepare, decode, or upload mammography pixels. `start_mg_process` posts a tiny
JSON body `{study_id, det_eval_thr, aux_eval_thr, run_classification}` to
`{breast_url}/api/v1/run_full_analysis`; the **AI server pulls the DICOM from its own PACS**, runs the
model, and returns URLs to result CSVs which the worker then downloads. So of the areas asked about:

* **Preparing images / uploading multiple views / large image buffers / native image-decode crashes**
  → **not on the client at all.** There is no client-side `pixel_array` / `cv2` / `Image.open` in this
  path (verified). A client crash here is therefore **not** a native decode crash.
* **Building the payload / receiving + parsing the response** → correct and defensive: `run()` wraps
  everything in `try/except` and emits `error` (exceptions do **not** cross the thread boundary), the
  non-OK body is read before raising (the earlier 502 work), and bad JSON is handled.

The crash is in **worker lifecycle**, not networking or imaging.

## Root cause (regression-class): the QThread had ONE strong reference, no re-entrancy guard

`AIChatInteractorStyle._current_worker = worker` was the **only** strong reference to the running
`MamoWorker` / `BoneAgeWorker` QThread. It was **never cleared, never `deleteLater()`-d**, and there was
**no guard against starting a second run**. Two ways this aborts the interpreter with
**`QThread: Destroyed while thread is still running`** (a Qt `abort()` = "the Python process crashes"):

1. **Duplicate run.** The overlay auto-hid at **120 s** while the request's own read budget was **240 s**
   — so for up to 120 s the UI looked idle with a worker still alive. The user re-clicks Eagle Eye →
   `start_mg_process` runs again → `self._current_worker = worker` **overwrites** the reference to the
   first, still-running thread → its refcount hits 0 → Python GC finalizes a **running** QThread → abort.
2. **Teardown mid-request.** Closing the patient/tab deleted the style object, dropping the only ref to
   the running thread — same abort. (Same class as the EchoMind `_ORPHANED_WORKERS` fix and the
   curved-MPR deleted-object teardown crash already in `CLAUDE.md`.)

Amplifiers found in the same path: no duplicate-request guard (→ duplicate server jobs / "duplicate
uploads"), and a **scalar** `requests` timeout (`timeout=240` / `360`) that applies to **both** connect
and read, so a dead host hangs a worker thread for the full budget (a "stuck request").

## Fix (flag `AIPACS_EAGLE_WORKER_LIFECYCLE`, default ON; `=0` = byte-identical legacy)

1. **Process-level strong ref until the thread actually ends.** Every started worker is added to a
   module-level `_LIVE_AI_WORKERS` set and removed only when it emits `finished`/`error` (then
   `deleteLater()`-d). A worker can no longer be GC'd — or deleted with its parent — while running.
   Mirrors EchoMind's proven `_ORPHANED_WORKERS` detach-don't-wait idiom.
2. **Re-entrancy guard.** `start_mg_process` / `start_dx_process` refuse a new run while
   `_ai_worker_busy()` (the tracked worker `isRunning()`), showing "an analysis is already running".
   Kills the overwrite-while-running crash **and** duplicate server jobs. `_ai_worker_busy()` treats a
   dead C++ object (`isRunning()` → `RuntimeError`) as not-busy.
3. **Cleanup is exactly-once and on the GUI thread** (queued from the worker's own signals); it clears
   `self._current_worker` only if it still points at that worker, so a later run is never clobbered.
4. **Fail-fast timeouts:** `(10, 240)` for MG, `(10, 360)` for DX — a dead host fails in ~10 s instead
   of hanging the worker; the server still gets the full read budget.
5. **Overlay safety timer 120 s → 260 s** (> the 240 s read budget) so the modal overlay cannot vanish
   while the request is still alive and invite the re-click that caused crash path #1.

**Not changed (correct already):** `run()`'s try/except boundary; the non-OK-body-before-raise; the
atomic streamed download (`_save_binary` uses `with requests.get(... stream=True)` + `with open(...)` so
sockets and file handles are always closed); the resume/no-overwrite CSV naming.

## Tests

`tests/code/ai_imaging/test_eagle_worker_lifecycle.py` (11): flag default-on + kill switch; a running
worker is strongly referenced and reported busy; finished/error clear the ref + free the worker;
deleted-C++-object is not busy; a 2nd worker does not evict the 1st from the live set; source-pins for
the guard + registration in both start paths, the connect/read timeout tuples, and the 260 s overlay
timer. Full `tests/code/ai_imaging` = **236 passed, 8 xfailed**. Plugin mirror synced + verified 422/422.

## NEEDS live source-build verify

* Run Eagle Eye on an MG study → completes and shows the result (no behaviour change on the happy path).
* Click Eagle Eye a second time while the first is still running → "already running" message, **no
  second server job, no crash**.
* Point the breast URL at a dead host → controlled error in ~10 s (not a 4-minute hang, not a crash).
* Close the patient/tab while a request is in flight → no `QThread: Destroyed while thread is still
  running`, no process abort.

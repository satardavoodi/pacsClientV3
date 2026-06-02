# Single-Instance Application Guard — As-Built (2026-06-02)

Hardened the single-instance guard and the clean-termination path so only one
AIPacs process is ever active, a re-launch raises the existing window, crashes never
leave a stale lock, and closing the app leaves nothing behind in Task Manager.

## What was there before
`PacsClient/utils/single_instance_lock.py` used a **PID lock file** only. Weaknesses:
read-then-write **race** (two fast launches could both acquire); **broken bring-to-front**
(shelled out to PowerShell with a hardcoded **Qt5** window class — this is Qt6, so it
silently failed); default action was to **kill** the existing instance (risky in a
clinical app); recycled-PID risk.

## What changed

### 1. `single_instance_lock.py` — rewritten (interface preserved)
- **Primary mechanism: Qt `QLocalServer` / `QLocalSocket`** (a Windows *named pipe*).
  Only one process can `listen()` on the name → **atomic, race-free**. The OS releases
  the pipe when the owner dies → **no permanently-stale lock**. A second launch connects
  and sends `AIPACS_ACTIVATE`; the running instance's `newConnection` handler invokes a
  callback that **raises + focuses its window**. Connecting *is* the liveness check
  (a crashed owner isn't listening → the new launch becomes primary).
- **Secondary mechanism: PID lock file** (`%TEMP%/aipacs_locks/aipacs_instance.lock`) —
  records the owner PID for diagnostics and is the fallback guard if QtNetwork is
  unavailable (headless/test). Validates the PID is alive *and* looks like an AIPacs
  process before blocking.
- **Per-user, build-independent** server name (`AIPACS_SI_<md5(user)>`) → identical in a
  source run and a packaged build; a source run and a packaged run for the same user are
  correctly mutually exclusive.
- Safer default: a re-launch **raises the existing window and exits** (no killing).
- New `set_activate_callback(cb)`; `release()` closes the server + removes the lock file.

### 2. `main.py`
- After the main window is created, registers `_raise_existing_window()` as the activate
  callback (restore-if-minimized → `show` → `raise_` → `activateWindow`).
- **Shutdown clean-termination guarantee** (end of the run-loop `finally`, after the lock
  is released, DB WAL is checkpointed, and logs are flushed):
  - `terminate_all_download_subprocesses()` — kills any download subprocess still
    registered, so a download in flight at close can't orphan a `python.exe`.
  - `os._exit(0)` (guarded; escape hatch `AIPACS_NO_HARD_EXIT=1`) — guarantees the main
    process leaves Task Manager even if a non-daemon worker/socket thread is still alive
    (that wait-at-interpreter-exit is the "app stays in Task Manager" symptom). Safe:
    DICOM/thumbnail writes are atomic and the DB WAL was checkpointed first.

### 3. `_vw_globals.py`
- Added `terminate_all_download_subprocesses()` over the existing `_active_download_pids`
  registry (psutil terminate→kill, ctypes `TerminateProcess` fallback) + an `atexit`
  registration so it also runs on shutdown paths that bypass the explicit call.

## Verification (all passed)
- `py_compile` + import: `main.py`, `single_instance_lock.py`, `_vw_globals.py`.
- **Same-process:** first acquires; second blocked; release → re-acquire.
- **Two-process (faithful):** `PRIMARY_ACQUIRED=True`, **`ACTIVATED`** (bring-to-front IPC
  fired cross-process), `SECONDARY_ACQUIRED=False`.
- **Crash recovery:** force-killed the owner (`Stop-Process -Force`) → next launch
  `RECOVER_ACQUIRED=True` (no stale lock).
- **Regression:** `tests/code/download_manager + system` = **183 / 183, 0 errors**.

## Behaviour matrix (requirements → result)
| Requirement | Result |
|---|---|
| Only one instance runs | ✅ second launch blocked |
| Re-launch brings existing to front | ✅ ACTIVATE IPC raises the window |
| New process exits safely | ✅ `try_acquire()` → False → caller `sys.exit(0)` |
| Normal shutdown releases lock | ✅ `release()` closes server + removes PID file |
| Crash leaves no stale lock | ✅ OS releases the named pipe; verified |
| Detect previous actually alive | ✅ `connectToServer` succeeds only if listening |
| No lingering download subprocess | ✅ `terminate_all_download_subprocesses()` + atexit |
| App fully terminates (Task Manager) | ✅ guarded `os._exit(0)` after cleanup |
| Dev + packaged | ✅ pure Qt, per-user build-independent name |

## Note
Takes effect on the **next app launch** (the currently-running instance still has the old
guard). Transition is clean: the old instance releases its PID file on close; the new
guard is QLocalServer-authoritative and simply overwrites any leftover PID file.

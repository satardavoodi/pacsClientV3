# A0 — the patient-close path can hang, and nothing we own can see it

**2026-08-23.** Companion to `docs/reports/ENDUSER_SANAM_STABILITY_REVIEW_2026-08-23.md`.

## The incident

Windows Application log, end-user workstation "sanam":

```
Application Hang 1002 — AIPacs.exe 3.6.2.0 — pid 0x6078 (24696)
2026-08-23 00:47:02 local — hang type 41 (top-level window stopped responding)
```

The app's own logs stop **17 seconds earlier, at 00:46:45**, and the last thing
they record is a patient-tab close:

| time | line |
|---|---|
| 00:46:44 | `[VOICE-DELETE-GUARD] kept saved voice on non-user teardown` |
| 00:46:44 | `[B3.4_DIAG] BRIDGE_CLEANUP bridge=bfb250 viewer=q14680 slice=68` |
| 00:46:44 | `[B3.4_DIAG] BRIDGE_CLEANUP bridge=bfa5d0 viewer=q27f80 slice=134` |
| 00:46:44 | `[ZetaBoost] INACTIVE clear_cache=True` |
| 00:46:44 | `[ZetaBoostDisk] CLEAR_TAB` |
| 00:46:44–45 | `[SEED_CONFIG]` × 8 in one second |
| 00:46:45 | `[Socket] pooled connection has 1+ unread byte(s) (stream desync) — discarding` |
| 00:46:45 | `[ino-approval] reception=55359` |
| — | nothing further; process killed; recovery launch at 00:47:13 |

This is the failure the owner reported as *"after that update the application
still crashed once and closed unexpectedly"*. It is **not** the 06:00
disappearance seven hours later — that was an unexpected host power loss
(`EventLog 6008`, `Kernel-Power 41` with `BugcheckCode=0`).

## Why we were blind — and this is the real finding

We have two main-thread stall diagnostics. **Both are structurally incapable of
reporting this class of failure**, for different reasons.

### F8 `[MAIN_THREAD_STALL]` — a stall that never ends is never reported

```python
# main.py
def _probe_tick() -> None:
    now_ms = _probe_time.perf_counter() * 1000.0
    gap_ms = now_ms - _probe_state.last_fire_ms   # <- measured on the NEXT fire
```

It is a `QTimer` **on the main thread**. It computes the gap when it next gets
to run, so it can only describe a block that has already finished. A block that
runs until the process is killed produces no record at all.

pid 24696's worst recorded stall is **1 188 ms** — in a session that hung for 17
seconds. The number is not wrong; it is answering a different question.

### F11 `[MAIN_THREAD_STALL_TRACE]` — a Python thread cannot sample a held GIL

F11 exists precisely to catch an in-progress block: a daemon thread that polls
`_probe_state.last_fire_ms` every 50 ms and dumps `sys._current_frames()` once
the gap exceeds 400 ms. It does not wait for the block to end.

But it is a **Python** thread. It needs the GIL to execute a single bytecode.
While the main thread is inside a long C call — `gc.collect()` over a multi-GB
heap, a VTK render-window destructor, a GPU driver call — there is no bytecode
boundary, so the GIL is never released and F11 never runs.

**The silence of both probes is itself the evidence: the block was native and it
held the GIL.**

## What is actually on the close path

`_pw_lifecycle.exit_patient_widget` runs the whole teardown synchronously on the
GUI thread — `cleanup_all_viewers()`, `clear_all_caches_for_close()`, then per
viewer node `release_mpr_children()` followed by `cleanup_image_viewer()` /
`cleanup()`, then thumbnail VTK release — and finally schedules a `gc.collect()`
for 150 ms later.

Two properties of that module matter here:

1. **It logs nothing at INFO.** Every `print()` in `_pw_lifecycle.py` is
   redirected to `logger.debug` at the top of the file. So we could not even
   tell whether `exit_patient_widget` returned.
2. **`gc.collect()` is the only step that is unlogged, unbounded AND
   GIL-holding.**

| step | logs? | where in the function | verdict |
|---|---|---|---|
| `qt_viewer_bridge.cleanup` | yes | `BRIDGE_CLEANUP` emitted **first**, before `pipeline.shutdown()` and `qt_viewer.clear()` | proves entry, not completion — still a candidate |
| `ZetaBoostDisk.clear_tab` | yes | `CLEAR_TAB tab=… removed=N` emitted **last** | it completed; not the blocker this time |
| `seed_user_config_defaults` | yes, 8× | log at end of each call | each completed |
| **deferred `gc.collect()`** | **no** | — | **only step that can vanish silently** |

### The 2026-06-27 fix moved this freeze; it never shortened it

That fix's own comment is explicit: a synchronous `gc.collect()` on the GUI
thread cost *"up to ~3.7 s freeze on EVERY patient close"*, and the remedy was to
run **the same collect** 150 ms later via `QTimer.singleShot` so the close
*returns* instantly. The collect deliberately stays on the GUI thread, because
VTK render windows can only be destroyed there.

That was the right call for what it addressed — but the freeze was relocated,
not removed, and 150 ms after a close the user is still in front of the screen.
pid 24696's heap was **2 378 MB** when it collected, the fastest memory ramp in
the dataset (38 minutes).

The three `vtkCommonCore-9.6.1.dll c0000005` crashes at offset `0x1de9770`
(2026-08-03, 08-08, 08-11) are the same teardown family. A crash and a deadlock
are the two failure modes of the same unsafe VTK destruction, and a GC is what
triggers that destruction.

## What landed

Observation before treatment. The next field log has to be able to name the
blocking step instead of stopping mid-sentence.

### 1. `hang_watchdog` — a watchdog that works while the GIL is held

`PacsClient/utils/native_fault_log.py`. `faulthandler.dump_traceback_later()` is
implemented in C and runs its timer on its own **native** thread, so it fires
even though the GIL is held. Arm it around a section that must not block, cancel
it after; if the section overruns, every thread's Python stack — including the
stuck main thread's — lands in `native_fault.log` under a `Timeout (0:00:0N)!`
header.

```python
with hang_watchdog("deferred_close_gc"):
    gc.collect()
```

Design constraints, all guarded:

* `exit=False` — it observes, it never aborts the app.
* **Non-reentrant on purpose.** faulthandler keeps exactly ONE timer, so a
  nested arm would silently cancel the outer one and lose the dump we care
  about. The depth guard makes inner uses no-ops and they yield `False`.
* No-op when the fault log is disabled or unavailable; it never opens a second
  handle, and it reuses the process-lifetime handle already held by
  `enable_native_fault_log`.
* **Writes nothing unless it fires**, so routine closes neither pollute
  `native_fault.log` nor confuse the block parser in
  `tools/diagnostics/filter_native_fault.py`.
* Never raises — a patient close cannot fail because a diagnostic did. The
  import in `_pw_lifecycle` degrades to a no-op context manager.

### 2. `_close_step` — a breadcrumb before, not only after

`_pw_lifecycle.py`. The `start` line is the load-bearing half: a step the
process dies inside is now identifiable by having a start and no done.

```
[CLOSE_PATH] exit_patient_widget start
[CLOSE_PATH] exit_patient_widget done ms=143.2
[CLOSE_PATH] deferred_close_gc start
[CLOSE_PATH] deferred_close_gc done ms=812.4      <- WARNING above 250 ms
```

`exit_patient_widget` became a thin wrapper over an unchanged
`_exit_patient_widget_impl`, so the teardown body is untouched.

### 3. `seed_user_config_defaults` seeds once per `(src, dst)`

`aipacs_runtime.py`. Five `_config_root()` helpers — `server_profiles`,
`offline_cloud`, `Identity/config`, `cloud_consultation.feature_flags`,
`aipacs_chat.feature_flags` — call it on **every** call, plus three module-import
call sites. Reading a feature flag therefore re-scanned the roaming config
directory: `iterdir()` plus a `stat()` per file. Hence eight `[SEED_CONFIG]`
lines inside one second, on the GUI thread, during teardown.

Seeding is create-if-missing and the roots cannot change inside a process, so
repeating it can never produce a different answer. Memoised on the resolved
`(src, dst)` pair — not a bare bool — so tests seeding into different tmp dirs
still exercise a real pass, and recorded only after a **complete** pass so a run
that bailed on a missing bundled root is retried rather than memoised away.

### Kill switches

| flag | default | effect of `=0` |
|---|---|---|
| `AIPACS_HANG_WATCHDOG` | on | no watchdog is armed |
| `AIPACS_HANG_WATCHDOG_SECONDS` | 5.0 | timeout before the dump (garbage/non-positive falls back) |
| `AIPACS_CLOSE_PATH_TIMING` | on | silent legacy close path, no breadcrumbs, no watchdog |
| `AIPACS_CLOSE_PATH_WARN_MS` | 250 | threshold at which `done` logs at WARNING |
| `AIPACS_SEED_CONFIG_ONCE` | on | seed on every call, as before |

## Deliberately NOT changed

* **`ZetaBoostDisk.clear_tab` stays on the GUI thread.** The stability review had
  recommended moving it; reading it changed that. Its log line is emitted last,
  so it demonstrably completed during the incident, and moving it off-thread
  introduces a real race — a tab reopened under the same key could have its
  fresh entries deleted by a late clear. It also has a plugin-payload mirror
  that would have to move with it. It is still sqlite plus up to two `unlink()`
  per cached slice on the GUI thread; instrument, then decide.
* **The GC itself.** Making the collect cheaper — generational instead of full,
  or budgeted — is a behavioural change to a path whose entire purpose is
  destroying VTK render windows on the GUI thread. It deserves the measurement
  first.
* **Bridge teardown ordering.** Re-entering the event loop between the two
  bridges is the likely fix if the dump lands in `pipeline.shutdown()` or a VTK
  destructor. Not on speculation.

## Guards

`tests/code/system/test_close_path_hang_visibility.py` (14) and
`tests/code/runtime/test_seed_config_once.py` (12). **All 26 fail on the pre-fix
tree**, proved by
`tools/analysis/oneoff/verify_close_path_guard_fails_prefix_2026_08_23.py`.

That script does **not** use `git show HEAD:` — and that matters. This working
tree carries 389 lines of unrelated uncommitted work in `aipacs_runtime.py` and
17 in `_pw_lifecycle.py`, so restoring from HEAD would revert far more than A0
and the guards would "fail" for the wrong reason. It removes exactly the A0
additions instead, anchor-based, asserting every anchor before writing anything,
and restores in a `finally`.

The load-bearing guards:

* `test_watchdog_fires_on_an_overrunning_block` — **behavioural**: a 1.2 s block
  under a 0.2 s watchdog must leave a real stack dump on disk. This is the one
  guard that reproduces the actual failure mode.
* `test_watchdog_is_silent_when_the_block_completes` — the other half; a
  watchdog that dumps on every close is a watchdog people turn off.
* `test_watchdog_is_not_reentrant` — faulthandler's single-timer trap.
* `test_watchdog_uses_the_gil_independent_api` — a Python thread pretending to
  be a watchdog would pass every other test and fail in the field exactly as
  F11 did.
* `test_close_step_logs_before_the_body_runs` — asserts the ORDER, which is the
  whole mechanism.
* `test_close_path_never_depends_on_the_watchdog_importing` — a patient close
  must not fail because a diagnostic could not import.
* `test_a_failed_pass_is_not_memoised` — a missing bundled root is an install
  fault, not a settled answer; if the module install completes later the next
  call must still seed.

## Regression check

`tests/code/{system,runtime,utils,builder}` — **580 passed, 11 failed**. All 11
are pre-existing: `tools/analysis/oneoff/check_a0_regression_delta_2026_08_23.py`
runs the same file set with and without the A0 additions and gets **identical
failure sets** (6 × `test_nuitka_arm64_parity`, 4 × `test_local_search_progressive`,
1 × `test_release_parity_guards::test_plugin_mirrors_are_fresh`). **Caused by
A0: 0.** Those eleven are worth their own look — they are not this change.

## What answers this next

If a `[CLOSE_PATH] … start` line appears in a field log with no matching `done`,
the step is named. If the watchdog dump lands inside `gc.collect()`, the fix is
to stop doing a full collect on the close path. If it lands in
`pipeline.shutdown()` or a VTK destructor, the fix is to re-enter the event loop
between bridge teardowns.

**Honest caveat.** That `gc.collect()` is the only silent, unbounded,
GIL-holding step on the close path is established from the source. That it is
what actually hung pid 24696 is still inference — the watchdog exists so the
next occurrence answers it instead of anyone guessing.

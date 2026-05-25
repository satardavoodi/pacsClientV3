# AI-PACS Crash Analysis — 2026-05-25

Analysis of the three diagnostic logs supplied from the crashing **installed**
build (`C:\Users\Dr.Alizadeh\Desktop\crash folder`):
`viewer_diagnostics.log`, `download_diagnostics.log`, `db_diagnostics.log`.

## Short answer

The logs **do** reveal the failure *mode* but **not** the exact faulting line —
and they cannot, by design (see "Why the logs stop", below).

What is established with high confidence:

1. The application is being terminated by a **hard, native-level process kill** —
   not a Python exception, not a graceful shutdown, and **not** an operating-system
   out-of-memory.
2. There is a **real, separate memory leak**: process RSS climbs monotonically for
   the entire life of every session and never falls back. This matches the user's
   description exactly ("stays open a while with heavy images, then auto-closes").
3. A crash dump on disk proves the app's native crash signature is a
   **`0xC0000409` fail-fast inside `Qt6Core.dll`** — an immediate, silent kill that
   runs no cleanup and writes no traceback.

## Evidence

### 1. Three abrupt terminations during the captured period

The logs span a single day and contain four app sessions (identified by PID, which
changes on every relaunch). Three of them end abruptly:

| Session | PID    | Started   | Last log line | Duration | Ended during |
|---------|--------|-----------|---------------|----------|--------------|
| 1       | 2212   | 12:14:55  | 12:50:11      | ~35 min  | series switch (`change_series_on_viewer`) |
| 2       | 23524  | 12:53:16  | 14:07:32      | ~74 min  | stack drag + `disk_pixel_cache.clear` |
| 3       | 27380  | ~14:16:20 | 15:12:28      | ~56 min  | `new_viewer` / series switch |
| 4       | 25192  | 15:13:42  | 15:20:12      | (running when logs copied) | — |

Every terminated session ends **mid-operation, on an ordinary `INFO` line, with no
error, no traceback, no shutdown marker** (`SESSION_END` count = 0; the normal
"instance lock released" shutdown line is absent). All three deaths happen while the
FAST viewer is actively switching series or scrolling the image stack — i.e. during
heavy image work, consistent with the reported symptom.

### 2. Monotonic memory growth (a genuine leak)

`main_thread_probe` periodically logs `process_rss_mb`. Within every session RSS only
ever goes **up**:

- Session 2 (pid 23524): **514 MB → 1023 MB** over ~33 min of sampling, still
  climbing when sampling stopped ~10 min before the crash.
- Session 3 (pid 27380): **546 MB → 853 MB** over ~34 min.
- Session 4 (pid 25192): **529 MB → 609 MB** in the first ~3 min.

Every session starts at ~510–545 MB and never returns to baseline — memory is not
being released between patients/series. Heavier/larger image datasets enlarge each
increment, so the app reaches its failure point sooner — which is why the crash
feels tied to "large images" and "after a while".

Note: the machine has **63.8 GB RAM with 27.4 GB free**, and the process is **64-bit**.
~1 GB RSS is therefore *not* an OS out-of-memory. The leak is a contributing stressor
(more allocation churn, more GC pressure, more live Qt objects), not, by itself, the
kill mechanism.

### 3. The native crash signature (crash dump)

Local crash dumps exist in `%LOCALAPPDATA%\CrashDumps` — nine `python.exe` dumps from
**2026-05-19/20**. Parsing the most recent one (`python.exe.180996.dmp`):

```
exception code   : 0xC0000409  (STATUS_STACK_BUFFER_OVERRUN / __fastfail)
faulting module  : Qt6Core.dll  (offset +0x1BBD8)
```

`0xC0000409` is the Windows **fail-fast** code. Qt and the MSVC runtime raise it for a
family of fatal conditions — an unhandled C++ exception reaching `std::terminate`,
detected heap corruption, a GS/stack-cookie violation, or a `qFatal`. A fail-fast
**terminates the process instantly**: no C++ destructors, no Python `atexit`, no Qt
shutdown, no dump-from-cleanup. That is precisely the "the app just vanishes"
behaviour being reported.

No new crash dump and no Windows "Application Error" event were produced for *today's*
three terminations, but the fingerprint (silent, instant, mid-operation, no
traceback) is identical to this dump's fail-fast. The most reasonable reading is that
today's crashes are the **same fail-fast class**.

### 4. Why the logs stop where they do ("the logs don't show the crash")

`PacsClient/utils/diagnostic_logging.py` routes **all** file logging through an
**asynchronous** `QueueHandler` → background-thread `QueueListener`. Log calls only
do `queue.put_nowait()`; the actual disk write happens later on another thread.

When the process is killed by a `0xC0000409` fail-fast (or any native crash), **every
log record still sitting in that in-memory queue is lost** — it is never written to
disk. `atexit` flushing does not run for a fail-fast. So the logs are *guaranteed* to
be truncated by however much was buffered at the instant of death. The "last line" in
each log is therefore **not** the last thing that happened — it is simply the last
record that had already been flushed. This is why the logs end on a harmless `INFO`
line and show no error.

## Root-cause assessment

**High confidence:** the app is dying from a native fail-fast (`0xC0000409`,
`Qt6Core.dll`), repeatedly, during heavy FAST-viewer image interaction. There is also
a real memory leak in the per-session/per-series path.

**Moderate confidence:** the fail-fast trigger is a **QObject lifetime / event-delivery
fault** in the FAST 2D viewer path or in patient-tab teardown — e.g. a Qt event or
queued signal delivered to an already-deleted C++ object, or a C++/Python exception
crossing the Qt boundary and reaching `std::terminate`. This is supported by the
crash always landing on series-switch / stack-drag / tab churn, and by
`close_and_remove_patient_tab` appearing repeatedly in the main-thread stall traces.
The QImage construction in `lightweight_2d_pipeline.py` itself looks correct (it
retains the numpy buffer via `qimg._np_buffer`), so the raw "QImage over a freed
buffer" bug is not the obvious culprit.

**Cannot be determined from these logs alone:** the exact faulting call site. The
async-logging truncation removes the final moments, and the only dump on disk is five
days old and was only parsed for its exception record, not a full stack.

## Recommended next steps (diagnostic first — no risky code changes yet)

To convert "failure mode known" into "exact line known", capture the *next* crash
properly. None of these change application behaviour:

1. **Make logging synchronous for the diagnostic run.**
   `diagnostic_logging.py` already has an escape hatch — set environment variable
   `AIPACS_LOG_SYNC=1`. The logs will then contain the true final events before the
   crash instead of losing the queue.

2. **Enable a real crash dump for the installed build.** Add a WER LocalDumps key for
   the process image (`python.exe`, or the installed `.exe` name) so the next crash
   writes a full-memory `.dmp`. The faulting **thread stack** in that dump will name
   the exact subsystem.

3. **Arm `faulthandler`.** Running with `python -X faulthandler` (or
   `faulthandler.enable()` early in `main.py`) prints a native+Python stack to stderr
   on a fatal fault — cheap, and often enough on its own.

Once a crash is captured with (1)+(2), the faulting stack will tell us whether to fix
the viewer pipeline, tab teardown, or an image-decode path — and the fix can then be
minimal and targeted, per the project's regression rules.

In parallel, the **memory leak** is worth tracking independently: instrument what is
retained across patient/series switches (cached QImages/QPixmaps, decoded arrays, the
disk/memory pixel caches, viewer widgets not being destroyed). Reducing it will both
improve stability and lengthen the time-to-crash.

## What was NOT changed

This was a read-only investigation. No source files, configuration, database, or
viewer code were modified. No tests were run against application code. The crash logs
were copied to a scratch folder for analysis only.

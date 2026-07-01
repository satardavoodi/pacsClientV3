# 2D patient-tab open — remove PySide6 shibokensupport stall on warmup dispatch (2026-07-01)

Focused 2D optimization for **opening a patient tab**. **Flag-gated, default-on, byte-identical when
off.** Implemented + offscreen-verified + **LIVE-verified (pid 185640, 18:13–18:20)**.

## Live-verify result (pid 185640)

- `shibokensupport` / `is_dir` / `module_valid` / `_vc_load` warmup-dispatch stall frames:
  **0 in the stall traces** (was 2 in the pre-fix run) — the open-path framework stall is eliminated.
- Warmup intact — 30 ZetaBoost/warmup activity events in the run (behaviour preserved).
- No tracebacks; non-startup stalls ≥400 ms dropped to 1, and that one is unrelated to patient open
  (license check / download+resume watchdogs / single-instance takeover). **PASS.**

## Context — the 2D patient tab is already healthy

Latest run (pid 22796, ~16 min): first image display **TTFI p50 ≈ 20 ms** (well under the 80 ms
target); only **4 non-startup stalls ≥ 400 ms** in the whole session. Loading and thumbnails are not
the bottleneck. Of those 4 open-path stalls, **half trace through PySide6 framework overhead**, not
clinical logic.

## Root cause

On patient open, the viewer pipeline `POST_DOWNLOAD` callback (`_vc_load.py`) scheduled the ZetaBoost
warmup with:

```python
QMetaObject.invokeMethod(self.parent_widget,
                         lambda: QTimer.singleShot(500, self._start_open_tab_warmup),
                         Qt.ConnectionType.QueuedConnection)
```

`QMetaObject.invokeMethod` **with a Python callable** makes PySide6 run its `shibokensupport`
signature machinery, which validates modules by scanning `sys.path` with `is_dir`/`os.stat`. The
stall trace shows exactly that: `_vc_load` → `shibokensupport.signature.mapping.module_valid` →
`pathlib.is_dir` → `os.stat`, contributing a ~400 ms main-thread stall on patient open. And because
this callback runs on the **qasync GUI loop**, the cross-thread marshalling is **redundant** —
`invokeMethod` was only needed to hop threads.

## Change (minimal, contained)

When already on the UI thread (the common case, confirmed via the **existing** `_is_on_ui_thread()`
helper — no duplicated thread check), schedule the warmup **directly** with
`QTimer.singleShot(500, self._start_open_tab_warmup)` — same effect, no `invokeMethod`, no
shibokensupport scan. Off the UI thread (rare), the original `invokeMethod` + `except` fallback path
is used unchanged. Flag `AIPACS_WARMUP_DISPATCH_FAST` (default on); `=0` restores the original path.

## Why it is safe

- **Behaviour preserved**: the warmup still fires 500 ms later on the GUI thread — the direct
  `singleShot` and the `invokeMethod`→`singleShot` both schedule on the same (GUI) thread's event
  loop. ZetaBoost prefetch/warmup still runs.
- The fast path engages **only when `_is_on_ui_thread()` confirms the UI thread**; otherwise the
  original marshalling runs. Kill switch restores the exact prior code.
- No viewer geometry / rendering / data / cache change; FAST viewer untouched (no VTK).

## Verification done (offscreen)

- Edited block Read-confirmed valid (lines 1837–1858); guard test
  `tests/code/viewer/test_warmup_dispatch_fast.py` **4 passed** (flag default-on, fast path reuses the
  helper + avoids invokeMethod, kill switch preserves the invokeMethod path).
  (`py_compile` in the sandbox reported a spurious error — a torn FUSE mount read of the large file;
  the authoritative reader + grep + pytest all see valid syntax.)

## Live-verify checklist (source build)

1. Launch the source build; open several patients (single- and multi-study).
2. Warmup/prefetch still works — after open, scrolling/stacking is smooth (ZetaBoost warmed).
3. Run `.venv\Scripts\python.exe tools\performance\kpi_session_report.py --print` and inspect the
   stall traces: the patient-open `shibokensupport` / `is_dir` / `_vc_load` warmup stall should be
   **gone**; TTFI unchanged (~20 ms).
4. Kill-switch sanity: `AIPACS_WARMUP_DISPATCH_FAST=0` → original behaviour.

## Notes / follow-ups

- There are **3** callable-style `invokeMethod` sites in `patient_tab/ui`; this fixes the one in the
  observed patient-open path. `shibokensupport`'s module cache warms after first use, so the other two
  are cheap once warm. If a future run shows shibokensupport elsewhere on a hot path, add a one-time
  **startup pre-warm** (trigger the scan once at idle) as the global follow-up.
- Drag-drop still shows occasional tail lag (worst `ui_lag_max` ~728 ms this run) — a separate FAST
  stack-drag item, not this fix.

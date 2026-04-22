# AIPacs v2.3.7 Release Notes

**Release Date:** 2026-04-22
**Branch:** main
**Previous Stable:** v2.3.6 (2026-04-20) / v2.3.5 (2026-04-19)

---

## Summary

v2.3.7 finalizes the FAST-viewer stack-drag smoothness work started in v2.3.5
(async logging, GC suppression, queue-aware throttling) and v2.3.6 (Windows
process-priority boost, decode-worker cap). The focus of this point release is
**regression containment and hot-path tightening** after a failed experiment
with per-drag download-subprocess IDLE-priority (R13) surfaced a Windows
priority-inversion on the `multiprocessing.Queue` IPC mutex.

## Headline KPI (FAST stack drag, low-config Windows PC)

| Metric (worst across session)     | v2.3.4 | v2.3.5 | v2.3.6 | v2.3.7 (log 100) |
|-----------------------------------|-------:|-------:|-------:|-----------------:|
| `ui_lag_max_ms` (long drag >2s)   |  ~850  |  ~500  |  ~412  |        **~280**  |
| `ui_lag_max_ms` (short drag <1s)  |  ~400  |  ~200  |  ~150  |         **~60**  |
| `event_p95_ms`                    |  ~300  |  ~220  |  ~180  |        **~100**  |
| `handler_p95_ms`                  |   ~20  |   ~10  |    ~5  |           **~2** |
| `background_decode_count` (drag)  |  10-40 |   0-20 |   0-10 |         **0-23** |

Bars remain on: **R1** (surrogate staleness break), **R2** (protected-drag
latch + keepalive), **R3** (prefetch/cache-warm deny during drag), **R4**
(progressive grow defer), **R5** (DM `_apply_throttled_progress` skip),
**R6** (GC disable during drag), **R7** (async logging), **R8** (Windows
`ABOVE_NORMAL_PRIORITY_CLASS` on viewer process), **R9** (decode-workers
default 1), **R11** (startup refit dedup), **R12** (P1-neighbor prefetch
admitted during drag), **R14** (surrogate-index `getattr` guard).

## What changed vs. v2.3.6

### 1. R13 **reverted to opt-in** (critical correctness fix)

- **Background:** v2.3.6/v2.3.7-dev introduced R13: during a protected drag,
  drop the DICOM download subprocess to `IDLE_PRIORITY_CLASS` to free CPU for
  the viewer. A cross-process flag file (`{user_data}/cache/.drag_active`)
  signaled drag state; a 150 ms daemon poller flipped priority between IDLE
  (drag fresh) and BELOW_NORMAL (drag stale).
- **Log 99 regression:** After wiring the poller to the ACTIVE subprocess
  entry (`download_process_entry.py`), worst-case `ui_lag_max_ms` went
  **229 → 412 ms** on long drags under download overlap. `event_p95` peaked at
  376 ms while `handler_p95` stayed ~15 ms — classic **priority-inversion**
  signature (event loop stalled waiting on a lock held by a low-priority
  thread, not handler work).
- **Root cause:** The `multiprocessing.Queue` used for progress IPC has a
  shared OS mutex. Dropping the subprocess to IDLE while it holds this mutex
  causes the viewer thread (ABOVE_NORMAL) to block on lock acquisition until
  Windows' priority-boost mechanism lifts the IDLE thread — typically 100s of
  ms.
- **Fix:** R13 is now **disabled by default**. Set
  `AIPACS_DRAG_SUBPROC_THROTTLE=1` to explicitly opt in once a lock-free IPC
  channel is available (or to use `PROCESS_MODE_BACKGROUND_BEGIN` which lowers
  I/O priority without thread-priority demotion). Unconditional
  `BELOW_NORMAL_PRIORITY_CLASS` at subprocess startup is retained — it
  provides the actual viewer/download separation without mutex starvation.
- **Infrastructure kept:** The viewer-side `_touch_drag_flag()` call path and
  subprocess-side poller are both gated on the same env var and remain in the
  codebase for future re-activation. No code deletions.

### 2. `[SP]` subprocess logs now visible when R13 is enabled

- `_infer_component("download_process_entry")` returns `"download"` (string
  match) which has `logging.WARNING` threshold in `ComponentThresholdFilter`.
  All `logger.info("[SP] ...")` calls were being dropped silently — which is
  why log 97/98/99 showed zero `[SP]` lines even though the subprocess was
  running.
- Fix: every `[SP]` log call now passes
  `extra={"component": "ipc", "study_uid": ...}`, routing through the `ipc`
  component threshold (INFO). Matches the existing convention used by
  `socket_client.py` stage-timing logs.

### 3. Hot-path tightening — `ObjectCache` noop-probe

- `QtViewerBridge._apply_interaction_target()` was calling
  `pipeline.has_object()` + `pipeline.request_object()` for every item in
  `decision.work_items` (3–5 items per accepted drag target). Both methods
  route to `NoopObjectCache` by default, which returns `False` for everything
  — pure overhead in FAST mode.
- `modules/viewer/fast/object_cache.py` exposes a new
  `is_noop_object_cache()` probe. The drag-path loop skips the whole block
  when the default Noop cache is in place. Auto-reactivates if
  `set_object_cache()` wires a real implementation.
- Expected impact: 200–300 eliminated `hasattr`/method-dispatch/try-except
  calls per second during continuous drag; measurable but small (1–3 ms/drag).

### 4. New R13, R14 documentation in copilot-instructions

- R13 updated end-to-end to reflect the opt-in status, log 99 regression
  data, priority-inversion root cause, and the logger-visibility fix. Explicit
  guardrail: do NOT re-enable R13 by default without solving the IPC queue
  priority-inversion problem.
- R14 (new): `_last_surrogate_pixel_idx` hot-path reads use `getattr` to
  tolerate test stubs that bypass `__init__`. Codifies what broke 17 pipeline
  tests during v2.3.6 staging.

## Files changed (high level)

- `.github/copilot-instructions.md` — R13 rewrite; R14 added; stable-version
  header bumped to v2.3.7.
- `modules/download_manager/workers/download_process_entry.py` — R13 gated
  behind `AIPACS_DRAG_SUBPROC_THROTTLE`; `extra={"component": "ipc"}` added
  to every `[SP]` log site.
- `modules/download_manager/workers/download_subprocess.py` — LEGACY / dead
  copy; left untouched. Do NOT edit there.
- `modules/viewer/fast/ui_throttle.py` — `_get_drag_flag_path()` gated behind
  the same opt-in env var; default path disables fs writes on every
  mouse-move keepalive.
- `modules/viewer/fast/object_cache.py` — `is_noop_object_cache()` helper
  added; `__all__` extended.
- `modules/viewer/fast/qt_viewer_bridge.py` — drag hot-path skips the
  per-item `has_object`/`request_object` loop when Noop cache is active.
- `main.py`, `pyproject.toml`, `build_nuitka.py`,
  `builder/plugin package/**/module_package.json`,
  `builder/docs/WINDOWS_RELEASE_FLOW.md`,
  `builder/docs/INSTALLER_QA_CHECKLIST.md`, `README.md`, `docs/README.md` —
  version metadata bumped 2.3.5 → 2.3.7.

## Validation

- **168/168 tests passing** across:
  - `tests/viewer/test_fast_viewer_pipeline.py`
  - `tests/download_manager/test_priority_retry_dedup.py`
  - `tests/download_manager/test_socket_client_cancellation.py`
- Cross-PC cycle: changes developed and measured on PC A (dev).
  PC B (validation) pull + log 101 capture is the standard next step per
  `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md`.

## Cross-PC handoff for PC B

1. `git pull origin main` (or `git pull pacsclientv2 main`; both remotes are
   in sync after this release).
2. `git checkout v2.3.7` to pin to the exact release tag.
3. Run the standard drag scenario (scroll-stack on series 202 under download
   overlap) and capture `log 101`.
4. Compare `[FAST_DRAG_KPI]` lines against the log-100 baseline in the
   "Headline KPI" table above.
5. If `ui_lag_max_ms` on long drags stays ≤300 ms and `event_p95_ms` stays
   ≤120 ms, v2.3.7 is confirmed stable on PC B.
6. Expected stray noise: the `[SP]` logs will remain silent on PC B because
   R13 is opt-in. Set `AIPACS_DRAG_SUBPROC_THROTTLE=1` only for deliberate
   priority-inversion experiments.

## Rollback instructions

1. Checkout previous stable: `git checkout v2.3.6`.
2. Both remotes retain all prior tags (`v2.3.2`, `v2.3.3`, `v2.3.5`, `v2.3.6`,
   `v2.3.7`).
3. R13 opt-in env var has no effect on v2.3.6 (which shipped R13 still in
   dead code), so no environment cleanup is required.

## Known non-issues observed in log 100

- `event_p50_ms` occasionally sits at 60–70 ms on multi-second drags. This is
  **not** our handler cost (`handler_p50_ms ≈ 1.1 ms` on the same drags); it
  reflects Windows mouse-event delivery cadence at the OS level when the
  viewer has been ABOVE_NORMAL for several seconds.
- `background_decode_count` can reach 20+ on the first post-completion drag
  into an un-primed cache region. This is expected cache-warm behavior; the
  surrogate path (R1) keeps the image correct and the foreground set_slice
  sub-2 ms.

## Next planned perf work (not in this release)

- **QImage pre-scaling** to eliminate the 2–5 ms per-frame `QPainter` cost on
  long drags (would attack the residual 240 ms ui_lag peaks).
- **Lock-free IPC channel** for download progress so R13 can be safely
  re-enabled by default (would eliminate subprocess CPU contention during
  drag without priority-inversion risk).
- **Per-viewport decode-worker pool** instead of a single global worker, to
  better parallelize multi-viewer drag scenarios.

---

*For prior releases see `VERSION_2.3.5_RELEASE.md`, `VERSION_2.3.4_RELEASE.md`,
and the consolidated `RELEASE_NOTES.md`.*

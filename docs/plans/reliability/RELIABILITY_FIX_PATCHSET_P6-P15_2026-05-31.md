# AI-PACS Reliability Patchset Part 2 — P6–P15 + P8 (ready to apply) — 2026-05-31

Companion to `RELIABILITY_SOAK_AUDIT_2026-05-31.md` and
`RELIABILITY_FIX_PATCHSET_P1-P4_2026-05-31.md`. Exact diffs / precise guidance for the
remaining proposals, plus the full P8 treatment. Apply on the Windows source build, `py_compile`
each edited file, then `pytest tests\code -q`, then GUI/soak-verify per the relevant scenario.
Line numbers are from the 2026-05-31 tree — re-confirm before editing. **Two corrections vs the
audit doc are called out below (P8, P10): apply those as described here, not as originally worded.**

Priorities: **P6, P7, P9, P12 = Med · P11, P14 = Med · P13, P15 = Low · P8 = mostly already done · P10 = needs lifecycle check.**

---

## P6 — make the swallowed `_apply_loaded_series_data` error visible (Med)

**File:** `_vc_load.py:799-800`. A mid-cycle apply failure is logged at **DEBUG** and dropped, so
a half-applied series / stuck viewport gives no signal in `app.log`.

```python
# replace:
        except Exception as e:
            self.logger.debug(f"Error applying loaded series data: {e}")
# with:
        except Exception as e:
            # Was DEBUG (invisible). Elevate so a half-applied series is diagnosable;
            # exc_info gives the faulting line. series_number is in scope here.
            self.logger.warning(
                "Error applying loaded series data series=%s: %s",
                series_number, e, exc_info=True,
            )
```
**Safety:** logging-only; no control-flow change. **Verify:** none needed beyond `py_compile`;
watch for the new WARNING during S2.

---

## P7 — back off `_check_auto_retry` so a persistently failing server can't hot-loop (Med)

**File:** `modules/download_manager/ui/widget/_dm_workers.py:834-847`. FAILED studies are re-queued
to PENDING **immediately**, so a permanently failing server respawns workers at ~1 Hz.

```python
# replace the immediate re-queue (lines ~841-847):
                    # Increment retry count and move to PENDING for re-queue
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        retry_count=state.retry_count + 1,
                        error_message=None  # Clear error for fresh attempt
                    )
# with a delayed re-queue (exponential, capped):
                    from PySide6.QtCore import QTimer as _QTimer
                    _delay_ms = min(30000, 3000 * (state.retry_count + 1))  # 3s,6s,9s… cap 30s
                    _suid = state.study_uid
                    _rc = state.retry_count + 1
                    def _requeue(suid=_suid, rc=_rc):
                        try:
                            self.state_store.update(suid, status=DownloadStatus.PENDING,
                                                    retry_count=rc, error_message=None)
                        except Exception:
                            logger.exception("auto-retry deferred re-queue failed for %s", suid[:40])
                    _QTimer.singleShot(_delay_ms, _requeue)
```
**Safety:** only delays the re-queue; retry cap (`MAX_RETRIES`) unchanged. Runs on the UI thread
(QTimer) — `state_store.update` must be UI-thread-safe (it already is on this path). **Verify:**
point at an unreachable server; confirm worker respawns are spaced out, not ~1 Hz.

---

## P8 — dict_tabs_widget retention — MOSTLY ALREADY HANDLED (verify only)

**Correction to the audit doc.** `custom_tab_manager.close_patient_tab` (`:877-882`) **already**
calls `widget.close()` + `widget.deleteLater()` for non-service patient tabs, and its comment
(`:861-869`) documents that this exists precisely so the widget's `closeEvent` teardown runs when
a tab is closed from the tab bar. So:
- The dict_tabs_widget leak (R-6) is **largely mitigated already** — `widget.close()` →
  `_pw_lifecycle.closeEvent` → `exit_patient_widget`, which pops `dict_tabs_widget`.
- This also means **P1's `themeChanged` disconnects will actually run** (they live in those same
  teardown methods). No extra P8 diff is required.

**Verify only:** confirm `exit_patient_widget` (`_pw_lifecycle.py:~198`) does
`home_widget.dict_tabs_widget.pop(study_uid, None)` unconditionally (not guarded by a study_uid
match that can miss). If it is conditional, make the pop unconditional:
```python
        try:
            self.home_widget.dict_tabs_widget.pop(getattr(self, 'study_uid', None), None)
        except Exception:
            pass
```

---

## P9 — VoiceWidget never removes its event filters / disconnects (Med, fail-fast candidate)

**File:** `patient_toolbar/voice_tool_ui.py`. `__init__` does
`self._main_window.installEventFilter(self)` (`:58`), `self.patient_widget.installEventFilter(self)`
(`:62`), and `self._app.applicationStateChanged.connect(self._on_app_state_changed)` (`:67`).
There is **no** `closeEvent`/cleanup (grep shows only `stop_and_save_inline`), so on destruction Qt
can dispatch events to a dangling C++ filter — a `0x8001010d`/fail-fast candidate.

```python
# add to VoiceWidget:
    def closeEvent(self, event):
        try:
            self._cleanup_voice_widget()
        except Exception:
            pass
        super().closeEvent(event)

    def _cleanup_voice_widget(self):
        # remove event filters installed in __init__
        try:
            if getattr(self, '_main_window', None) is not None:
                self._main_window.removeEventFilter(self)
        except Exception:
            pass
        try:
            if getattr(self, 'patient_widget', None) is not None:
                self.patient_widget.removeEventFilter(self)
        except Exception:
            pass
        # disconnect the app-state signal
        try:
            if getattr(self, '_app', None) is not None:
                self._app.applicationStateChanged.disconnect(self._on_app_state_changed)
        except (TypeError, RuntimeError):
            pass
        # stop timer + release the audio stream
        try:
            if getattr(self, '_timer', None) is not None:
                self._timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, '_stream', None) is not None:
                self._stream.stop(); self._stream.close(); self._stream = None
        except Exception:
            pass
```
**Also** call `self._cleanup_voice_widget()` from the owning toolbar/patient-tab teardown if the
VoiceWidget can be discarded without a `close()` (e.g. parent destroyed). **Verify:** S3 (tools
loop) — no new `0x8001010d` entries in `native_fault.log`; voice tool still records after reopen.

---

## P10 — PyDicom2DBackend executor — DO NOT shut down in close_series (corrected)

**Correction to the audit doc.** `close_series()` (`pydicom_2d_backend.py:219`) clears `_slices`
and caches — it runs on **every series switch**, not just final teardown. The decode executor
`self._executor` (`:122`, created once in `__init__`) is **reused for the next series**, so calling
`self._executor.shutdown()` in `close_series()` would break decoding after the first switch — a
regression. **Do not do that.**

Correct fix: shut the executor down only when the backend instance itself is being destroyed.
```python
# add a dedicated teardown (call it from the backend/bridge destroy path, NOT close_series):
    def shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass
```
**First verify** the backend's real lifecycle: find where the `PyDicom2DBackend` instance is
discarded (bridge `cleanup()` / viewer teardown) and call `shutdown()` there. If the backend lives
for the whole app session (one per viewer, reused), the executor is bounded already and this is
optional. **Low priority** — confirm with the soak sampler whether `PyDicom2D` threads accumulate
before spending effort here.

---

## P11 — add a per-batch wall-clock deadline to the socket receive loop (Med)

**File:** `modules/network/socket_client.py` (receive loop ~`:781`, `recv` ~`:921`). The 30 s
`settimeout` is per-`recv`; a server that dribbles/stalls can keep the loop alive far longer.
Add a wall-clock deadline around the batch receive:

```python
# near the start of the batch-receive method:
        import time as _time
        _deadline = _time.monotonic() + float(os.getenv("AIPACS_RECV_BATCH_DEADLINE_S", "120") or "120")
# inside the receive while-loop, before/after each recv():
            if _time.monotonic() > _deadline:
                raise NetworkError("Receive batch exceeded wall-clock deadline")
```
**Safety:** purely a ceiling; normal batches finish well under 120 s. Tune the env default to your
slowest legitimate series. **Verify:** simulate a slow/half-open server; the series should fail
cleanly at ~120 s instead of hanging, and the existing retry/auto-retry takes over.

---

## P12 — cap the HomePanel ThreadPoolExecutor (Med)

**File:** `PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py:201`.

```python
# replace:
        self.thread_pool = ThreadPoolExecutor()
# with:
        # Default max_workers is min(32, cpu+4); cap it so rapid patient-list cycling
        # cannot spike concurrent DB queries that compete with the download subprocess.
        self.thread_pool = ThreadPoolExecutor(max_workers=4)
```
**Safety:** bounds concurrency; search/list still async. **Verify:** S4-adjacent — rapid search
typing + list refresh stays responsive; no DB-lock warnings appear.

---

## P13 — sweep stale `aipacs_lazy_*.bin` temp files (Low)

**File:** `modules/viewer/fast/pydicom_lazy_volume.py` writes
`NamedTemporaryFile(prefix="aipacs_lazy_", suffix=".bin", delete=False)` (`:130`).
`cleanup_stale_tmpfiles()` (`:45`) only removes paths this process registered and is **never called
in production**; on a fail-fast it can't run at all, so leftovers from crashed sessions accumulate.

Two parts:
```python
# (a) shutdown call — in mainwindow_ui.py closeEvent (the cleanup hub):
        try:
            from modules.viewer.fast.pydicom_lazy_volume import cleanup_stale_tmpfiles
            cleanup_stale_tmpfiles()
        except Exception:
            pass

# (b) startup cross-session sweep — early in main.py (guarded, best-effort):
        try:
            import glob as _glob, os as _os, time as _time, tempfile as _tf
            _cutoff = _time.time() - 6 * 3600   # only remove files older than 6h
            for _p in _glob.glob(_os.path.join(_tf.gettempdir(), "aipacs_lazy_*.bin")):
                try:
                    if _os.path.getmtime(_p) < _cutoff:
                        _os.remove(_p)
                except OSError:
                    pass
        except Exception:
            pass
```
**Safety:** the 6 h age cutoff avoids touching a concurrently-running instance's files (single-
instance is enforced anyway). **Verify:** S6 overnight — temp dir does not grow unbounded.

---

## P14 — DM close should not block on `worker.wait` (Low)

**File:** `modules/download_manager/ui/widget/widget.py:~449` (`cleanup()` → `worker_pool.stop_all()`).
`stop_all()` does `worker.wait(5000)` per worker → up to ~6 s blocking on close. A non-blocking
cancel already exists (`worker_pool.cancel_all_non_blocking()`, `worker_pool.py:~229`).

```python
# in cleanup():
# replace:
        self.worker_pool.stop_all()
# with:
        self.worker_pool.cancel_all_non_blocking()
```
**Verify the method name** against `worker_pool.py` first. Download subprocesses are daemonized, so
they're reaped on exit anyway. **Verify:** open/close the DM widget repeatedly with an active
download — no multi-second hang on close.

---

## P15 — floor the log rotation size (Low)

**File:** `PacsClient/utils/diagnostic_logging.py:466`.

```python
# replace:
    max_bytes = int(os.getenv("AIPACS_LOG_MAX_BYTES", str(20 * 1024 * 1024)) or str(20 * 1024 * 1024))
# with:
    # Floor at 1 MB so a misconfigured env value (e.g. "0") can't disable rotation,
    # which would let a single log file grow without bound.
    max_bytes = max(1024 * 1024, int(os.getenv("AIPACS_LOG_MAX_BYTES", str(20 * 1024 * 1024)) or str(20 * 1024 * 1024)))
```
**Safety:** trivial bound. **Verify:** `py_compile`.

---

## P-misc — clear per-tab accumulators on close (Low)

- **`_mask_actors`** (`_pw_lifecycle.py:~552`): in `cleanup_all_viewers()` / series-switch,
  `getattr(self.selected_widget, '_mask_actors', None)` → clear the list so AI-tool VTK actors don't
  accumulate across a session.
- **`_series_download_completed`** (`patient_widget_viewer_controller.py:~372`, "never cleared within
  controller lifetime"): reset this set in `clear_all_caches_for_close()` if the controller is reused
  across patient opens, so stale membership can't suppress progressive display on re-open.

Both are additive set/list clears in existing close paths; verify with S1 that the structures stay
bounded across cycles.

---

## Apply / verify summary

| Fix | File | Apply? | Verify scenario |
|---|---|---|---|
| P6 | `_vc_load.py:799` | yes | S2 (watch WARNING) |
| P7 | `_dm_workers.py:841` | yes | unreachable-server retry spacing |
| P8 | (close path) | **verify only** — already handled | S1 (RSS recovers) |
| P9 | `voice_tool_ui.py` | yes | S3 (no 0x8001010d) |
| P10 | `pydicom_2d_backend.py` | **only in real teardown, not close_series** | sampler: PyDicom2D thread count |
| P11 | `socket_client.py` | yes (tune deadline) | slow-server clean-fail |
| P12 | `home_panel/widget.py:201` | yes | rapid search responsiveness |
| P13 | `main.py` + `mainwindow_ui.py` | yes | S6 temp-dir bound |
| P14 | DM `widget.py:449` | yes (verify method) | DM close with active download |
| P15 | `diagnostic_logging.py:466` | yes | py_compile |
| P-misc | `_pw_lifecycle.py`, viewer_controller | optional | S1/S3 |

Run `pytest tests\code -q` after the batch; none of these remove a viewer feature, change the
socket protocol, or alter the DB schema.

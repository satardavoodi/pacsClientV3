# AI-PACS Reliability Patchset — P1–P4 (ready to apply) — 2026-05-31

Companion to `RELIABILITY_SOAK_AUDIT_2026-05-31.md`. These four fixes touch the
viewer/download/teardown paths, so they are delivered as **exact, reviewable diffs to apply on
the Windows source build and verify with the GUI + soak sampler** — not applied blind in this
pass. (P5, DB pool dead-thread eviction, was already applied to `database/_pool.py`; the five
§2 fixes in the audit doc are also already applied.)

Apply order: **P3 → P2 → P4 → P1** (lowest-risk/highest-certainty first). After each, run the
soak sampler (`tools/reliability/process_soak_sampler.py`) across scenario **S1/S2** and confirm
per-cycle RSS/thread growth drops. Line numbers are from the 2026-05-31 tree; re-confirm before
editing.

---

## P3 — `_worker` inflight guards can stay stuck → viewport stops switching (High)

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py` (~line 757, end of
`_schedule_async_load_and_switch._worker`).

**Root cause:** `inflight_key` is added to `self._async_switch_inflight` and
`self._interactive_load_in_progress=True` *before* the worker thread starts. They are cleared
**only** inside `_finish_on_ui`, which is marshalled to the UI thread by the **unguarded** call
`self._queue_on_ui_thread(_finish_on_ui)`. If that marshal raises (UI invoker gone, tab tearing
down), `_finish_on_ui` never runs, the key is never discarded, and the dedup guard at the top of
`_schedule_async_load_and_switch` (`if inflight_key in self._async_switch_inflight: return`)
**silently swallows every future series switch to that viewport for the rest of the session.**
(The new `threading.excepthook` will now at least log the worker crash.)

**Diff:**
```python
# _vc_switch.py — replace the single line:
            self._queue_on_ui_thread(_finish_on_ui)
# with:
            try:
                self._queue_on_ui_thread(_finish_on_ui)
            except Exception:
                # Last-resort cleanup: if _finish_on_ui can't be marshalled to the UI
                # thread, clear the inflight guards here so this viewer is not permanently
                # blocked from future series switches. (Set ops are atomic enough for this.)
                logger.exception("[ASYNC SWITCH] failed to queue _finish_on_ui series=%s", series_number)
                self._async_switch_inflight.discard(inflight_key)
                self._interactive_load_in_progress = False
                try:
                    self._set_zeta_external_interactive_busy(
                        bool(self._async_switch_inflight), reason="finish_queue_failed")
                except Exception:
                    pass
```
**Safety:** flag-cleanup only on the error path; no change to the success path, no locks added to
the render race (honors `NEXT_AGENT_DO_NOT_REPEAT.md`). **Verify:** scenario S2 (series-switch
storm) — no viewport should become unresponsive to switches after ~50 iterations.

---

## P2 — per-series `ThreadPoolExecutor` never shut down → thread leak (High)

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_series.py:~597`
(`_load_and_display_series_async`).

**Root cause:** a new `ThreadPoolExecutor(max_workers=1)` is created per series load and never
shut down; its worker thread lingers until GC. One per series × many patients = steady thread
growth (matches the observed 32→128 thread climb).

**Diff:**
```python
# _pw_series.py — replace:
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)

            # Run loading in background
            loop = asyncio.get_event_loop()
            loaded = await loop.run_in_executor(
                executor,
                self._load_single_series_on_demand,
                series_number
            )
# with:
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)

            # Run loading in background
            loop = asyncio.get_event_loop()
            try:
                loaded = await loop.run_in_executor(
                    executor,
                    self._load_single_series_on_demand,
                    series_number
                )
            finally:
                # One-shot pool: release its worker as soon as the await completes so it
                # cannot accumulate one live thread per series load across the session.
                executor.shutdown(wait=False)
```
**Safety:** the executor has exactly one job; shutting it down after the `await` is behaviour-
identical except the thread is released promptly. **Verify:** S1 — `thr` in the soak sampler
should return to baseline after each close.

> Optional hardening: promote to a single shared `self._series_executor` created once and shut
> down in `clear_all_caches_for_close()` (mirrors the `_header_fill_executor` fix already applied).

---

## P4 — synchronous task reconstruction freezes the UI up to ~16 s (High, freeze path F3)

**File:** `modules/download_manager/ui/widget/_dm_workers.py:~184` (`_start_download_worker`),
calling `_reconstruct_task_from_database` → `self.grpc_client.fetch_study_metadata_sync` (line 59),
which retries with blocking `time.sleep` (`network/grpc_client.py:135-152`).

**Root cause:** `_start_download_worker` runs on the Qt main thread; when a task is not in
`self._tasks`, it reconstructs **synchronously**, blocking the UI for up to ~16 s.

**Diff (offload + resume; preserves behaviour):**
```python
# _dm_workers.py — replace the `if not task:` block (~lines 179-193):
            if not task:
                logger.warning("🚀 [WORKER-START] ⚠️ Task not in memory; reconstructing OFF the UI thread...")
                # Do NOT call _reconstruct_task_from_database here — it does a synchronous
                # server metadata fetch with up to ~16 s of blocking retries on the UI thread.
                import threading as _thr
                from PySide6.QtCore import QTimer as _QTimer
                def _reconstruct_then_resume():
                    t = self._reconstruct_task_from_database(study_uid)
                    def _resume():
                        if t:
                            self._tasks[study_uid] = t
                            self._start_download_worker(study_uid)   # task now in memory
                        else:
                            logger.error("🚀 [WORKER-START] ❌ reconstruct failed; cannot start %s", study_uid[:40])
                    _QTimer.singleShot(0, _resume)                   # back to the UI thread
                _thr.Thread(target=_reconstruct_then_resume, daemon=True,
                            name=f"TaskReconstruct-{study_uid[:8]}").start()
                return False   # defer; the resumed call starts the worker
```
**Safety:** the download still starts; only the blocking fetch moves off the UI thread. **Verify
thread-affinity** of `_start_download_worker` re-entry (it must be safe to call from the UI thread
via `singleShot`, which it already is on the normal path). **Verify:** trigger a retry after
restart (task not in memory) — UI must stay responsive; `download_diagnostics.log` shows the
worker starting after reconstruction.

---

## P1 — `themeChanged` never disconnected on tab close → primary memory leak (Critical)

**Sites (10) — each connects a slot to the app-lifetime singleton `ThemeManager.themeChanged`:**

| File:line | Slot | Teardown hook to use |
|---|---|---|
| `patient_widget_viewer_controller.py:202` | `_on_theme_changed_refresh_viewports` | `clear_all_caches_for_close()` (`_vc_warmup.py:522`) |
| `patient_widget_core/widget.py:350` | `_on_app_theme_changed` | `closeEvent()` (`_pw_lifecycle.py:349`) / `exit_patient_widget()` |
| `utils/thumbnail_manager.py:696` | `_on_theme_changed` | `cleanup()` (`thumbnail_manager.py:259`) |
| `thumbnail_panel.py:69` | `_on_theme_changed` | `cleanup_timers()` (`:606`) |
| `header_widget.py:63` | `_on_theme_changed` | add/extend `closeEvent` |
| `reception_panel_widget.py:64` | `_on_theme_changed` | add/extend `closeEvent` |
| `patient_toolbar/toolbar_manager.py:757` | `_on_theme_changed` | its owner's cleanup |
| `patient_tab_widget.py:56` | `_on_theme_changed` | add/extend `closeEvent` |
| `sidebar_widget.py:79` | `_on_theme_changed` | add/extend `closeEvent` |
| `service_tab_widget.py:40` | `_on_theme_changed` | add/extend `closeEvent` |

**Uniform pattern** (idempotent — safe to call even if never connected or already torn down):
```python
        try:
            <theme_manager_ref>.themeChanged.disconnect(self._on_theme_changed)
        except (TypeError, RuntimeError):
            pass
```
Concrete examples:
```python
# patient_widget_viewer_controller — inside clear_all_caches_for_close() (_vc_warmup.py):
        try:
            self._theme_manager.themeChanged.disconnect(self._on_theme_changed_refresh_viewports)
        except (TypeError, RuntimeError):
            pass

# patient_widget_core — inside closeEvent()/exit_patient_widget() (_pw_lifecycle.py):
        try:
            if getattr(self, '_app_theme_manager', None) is not None:
                self._app_theme_manager.themeChanged.disconnect(self._on_app_theme_changed)
        except (TypeError, RuntimeError):
            pass

# thumbnail_manager — inside cleanup() (:259):
        try:
            self.theme_manager.themeChanged.disconnect(self._on_theme_changed)
        except (TypeError, RuntimeError):
            pass
```

**Prerequisite — make teardown actually run (P8).** This fix only helps if the tab's cleanup runs
and the widget graph is released. Today `home_widget.dict_tabs_widget[study_uid]` (set at open)
can retain the whole `PatientWidget` if the tab is closed via the tab-bar button before
`exit_patient_widget` runs (`home_panel/widget.py:158`). Apply alongside P1:
```python
# in the tab-bar close path (custom_tab_manager.close_patient_tab), before deleteLater():
        try:
            self.home_widget.dict_tabs_widget.pop(study_uid, None)
        except Exception:
            pass
```

**Verify (this is the headline leak):** with the soak sampler attached, run **S1** (30 patient
open/view/close cycles). Before: per-cycle RSS climbs and never recovers. After P1+P8: RSS should
return near baseline after each close, and the sampler's per-cycle verdict should read **OK**
(< 8 MB/cycle). Confirm theme switching still re-tints all open widgets (no lost functionality).

---

## After applying

```powershell
.venv\Scripts\python.exe -m py_compile <each edited file>
.venv\Scripts\python.exe -m pytest tests\code -q
```
Then launch the source build from VS Code, attach `process_soak_sampler.py`, and run S1+S2.
Record before/after per-cycle RSS and thread deltas in the audit doc's cumulative table.
None of these remove a viewer feature, change the socket protocol, or alter the DB schema.

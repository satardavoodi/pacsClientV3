"""
Backend binding and lazy-loader mixin for VTKWidget.
_bind_backend_from_metadata, _on_lazy_slice_ready, lazy loader lifecycle.
"""
from __future__ import annotations
import logging
import os
import threading
import time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from modules.viewer.fast.lazy_volume_registry import (
    acquire_loader,
    release_loader,
)
from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
from modules.viewer.fast._decode_guard import (
    backing_store_probe,
    h13_check_overlap_before_render,
    h13_get_decode_age_ms,
    h13_get_overlap_stats,
    _H13_RENDER_GATE,
    _H13_STALE_RENDER_ABORT,
)

logger = logging.getLogger(__name__)


class _VWBackendMixin:
    """Backend binding: viewer resolution, lazy loader, Qt bridge lifecycle."""

    def _extract_series_number(self, metadata) -> str:
        try:
            if isinstance(metadata, dict):
                return str((metadata.get("series", {}) or {}).get("series_number", "")).strip()
        except Exception:
            pass
        return ""

    def _log_backend_resolution(self, source: str, resolution: dict, metadata=None):
        try:
            series_number = self._extract_series_number(metadata) or "-"
            logger.info(
                "viewer-backend stage=resolve source=%s viewer=%s requested=%s chosen=%s "
                "metadata_backend=%s lazy_key=%s metadata_complete=%s force_vtk_fallback=%s series=%s",
                str(source or "unknown"),
                str(getattr(self, "id_vtk_widget", None)),
                str(resolution.get("requested_backend", BACKEND_VTK)),
                str(resolution.get("backend", BACKEND_VTK)),
                str(resolution.get("metadata_backend", "")),
                bool(str(resolution.get("lazy_loader_key", "") or "").strip()),
                bool(resolution.get("metadata_complete", True)),
                bool(resolution.get("force_vtk_fallback", False)),
                series_number,
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._bind_backend_from_metadata",
                    "stage": "backend_resolve",
                },
            )
        except Exception:
            pass

    def _log_gpu_boost_plan(self, source: str, plan: dict, metadata=None):
        try:
            series_number = self._extract_series_number(metadata) or "-"
            logger.info(
                "viewer-gpu stage=plan source=%s viewer=%s backend=%s requested=%s detected=%s active=%s "
                "device=%s fallback=%s series=%s",
                str(source or "unknown"),
                str(getattr(self, "id_vtk_widget", None)),
                str(plan.get("viewer_backend", "")),
                bool(plan.get("requested_gpu", False)),
                bool(plan.get("detected_gpu", False)),
                bool(plan.get("gpu_active", False)),
                str(plan.get("device_name", "") or "-"),
                str(plan.get("fallback_reason", "") or "-"),
                series_number,
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._log_gpu_boost_plan",
                    "stage": "gpu_plan",
                },
            )
        except Exception:
            pass

    def _log_slice_range(self, source: str = "unknown"):
        if self.image_viewer is None:
            return
        try:
            min_slice = int(self.image_viewer.GetSliceMin())
            max_slice = int(self.image_viewer.GetSliceMax())
        except Exception:
            min_slice = -1
            max_slice = -1
        try:
            effective_count = int(self.get_count_of_slices())
        except Exception:
            effective_count = -1
        try:
            dims = tuple(self.image_viewer.vtk_image_data.GetDimensions())
        except Exception:
            dims = ()
        lazy_count = 0
        try:
            lazy_count = int(getattr(self._lazy_loader, "slice_count", 0) or 0)
        except Exception:
            lazy_count = 0
        logger.info(
            "viewer-backend stage=slice_range source=%s backend=%s viewer=%s min=%d max=%d effective_count=%d dims=%s lazy_count=%d",
            str(source or "unknown"),
            str(self._active_backend),
            str(getattr(self, "id_vtk_widget", None)),
            int(min_slice),
            int(max_slice),
            int(effective_count),
            str(dims),
            int(lazy_count),
            extra={
                "component": "viewer",
                "function": "VTKWidget._log_slice_range",
                "stage": "slice_range",
            },
        )

    def _reset_lazy_metrics(self, dicom_read_ms: float = -1.0):
        self._lazy_metrics = {
            "series_start_ms": float(now_ms()),
            "time_to_first_frame_ms": -1.0,
            "dicom_read_ms": float(dicom_read_ms),
            "decode_ms_total": 0.0,
            "decode_count": 0,
            "wl_convert_ms_total": 0.0,
            "wl_convert_count": 0,
            "cache_requests": 0,
            "cache_hits": 0,
            "dropped_frames_count": 0,
        }
        self._lazy_drop_log_counter = 0
        self._lazy_metrics_last_log_ms = 0.0
        self._stack_event_count = 0
        self._stale_condition_count = 0   # H13-T6: stale/mismatch events (always-on, toggle-independent)
        self._stale_render_abort_count = 0  # H13-T6: actual aborts (only when toggle ON)

    def _mark_lazy_first_frame_if_needed(self):
        if self._active_backend != BACKEND_PYDICOM:
            return
        if float(self._lazy_metrics.get("time_to_first_frame_ms", -1.0)) >= 0.0:
            return
        start_ms = float(self._lazy_metrics.get("series_start_ms", 0.0) or 0.0)
        if start_ms <= 0.0:
            return
        self._lazy_metrics["time_to_first_frame_ms"] = max(0.0, float(now_ms()) - start_ms)

    def _log_lazy_metrics_if_due(self, force: bool = False):
        if self._active_backend != BACKEND_PYDICOM and not force:
            return
        now = float(now_ms())
        if not force and (now - float(self._lazy_metrics_last_log_ms or 0.0) < 1000.0):
            return
        self._lazy_metrics_last_log_ms = now

        requests = int(self._lazy_metrics.get("cache_requests", 0) or 0)
        hits = int(self._lazy_metrics.get("cache_hits", 0) or 0)
        cache_hit_rate = (float(hits) / float(requests)) if requests > 0 else 0.0
        decode_read_ms_total = 0.0
        decode_pixel_ms_total = 0.0
        decode_post_ms_total = 0.0

        loader = self._lazy_loader
        if loader is not None and hasattr(loader, "get_metrics_snapshot"):
            try:
                snap = loader.get_metrics_snapshot() or {}
                cache_hit_rate = float(snap.get("cache_hit_rate", cache_hit_rate))
                decode_read_ms_total = float(snap.get("decode_read_ms_total", 0.0) or 0.0)
                decode_pixel_ms_total = float(snap.get("decode_pixel_ms_total", 0.0) or 0.0)
                decode_post_ms_total = float(snap.get("decode_post_ms_total", 0.0) or 0.0)
            except Exception:
                pass

        wl_count = max(0, int(self._lazy_metrics.get("wl_convert_count", 0) or 0))
        wl_total = float(self._lazy_metrics.get("wl_convert_ms_total", 0.0) or 0.0)
        wl_convert_ms = (wl_total / float(wl_count)) if wl_count > 0 else 0.0

        logger.info(
            "viewer-lazy metrics viewport=%s time_to_first_frame_ms=%.2f dicom_read_ms=%.2f "
            "decode_ms=%.2f read_ms=%.2f pixel_ms=%.2f post_ms=%.2f wl_convert_ms=%.2f "
            "cache_hit_rate=%.3f dropped_frames_count=%d",
            str(self.id_vtk_widget),
            float(self._lazy_metrics.get("time_to_first_frame_ms", -1.0) or -1.0),
            float(self._lazy_metrics.get("dicom_read_ms", -1.0) or -1.0),
            float(self._lazy_metrics.get("decode_ms_total", 0.0) or 0.0),
            decode_read_ms_total,
            decode_pixel_ms_total,
            decode_post_ms_total,
            wl_convert_ms,
            cache_hit_rate,
            int(self._lazy_metrics.get("dropped_frames_count", 0) or 0),
        )
        # H13-P5: Pressure snapshot — worker count, queue depth, overlap stats
        try:
            loader = self._lazy_loader
            if loader is not None and hasattr(loader, "get_metrics_snapshot"):
                snap = loader.get_metrics_snapshot() or {}
                h13_oc, h13_max_ns = h13_get_overlap_stats()
                logger.info(
                    "[H13-P5] viewport=%s workers=%d qsize=%.0f pending=%.0f "
                    "overlap_count=%d overlap_max_ms=%.2f decode_count=%.0f decode_ms=%.1f "
                    "stale_cond_count=%d stale_abort_count=%d",
                    str(self.id_vtk_widget),
                    int(snap.get("h13_worker_count", 0)),
                    float(snap.get("h13_queue_depth", -1)),
                    float(snap.get("h13_pending_count", -1)),
                    h13_oc,
                    float(h13_max_ns) / 1_000_000.0,
                    float(snap.get("decode_count", 0)),
                    float(snap.get("decode_ms_total", 0)),
                    int(getattr(self, "_stale_condition_count", 0) or 0),
                    int(getattr(self, "_stale_render_abort_count", 0) or 0),
                )
        except Exception:
            pass

    def _disconnect_lazy_loader_signals(self, loader):
        if loader is None:
            return
        try:
            loader.slice_ready.disconnect(self._on_lazy_slice_ready)
        except Exception:
            pass
        try:
            loader.decode_failed.disconnect(self._on_lazy_decode_failed)
        except Exception:
            pass

    def _connect_lazy_loader_signals(self, loader):
        if loader is None:
            return
        self._disconnect_lazy_loader_signals(loader)
        try:
            loader.slice_ready.connect(self._on_lazy_slice_ready)
        except Exception:
            pass
        try:
            loader.decode_failed.connect(self._on_lazy_decode_failed)
        except Exception:
            pass

    def _release_bound_lazy_loader(self):
        old_loader = self._lazy_loader
        old_key = self._lazy_loader_key
        self._lazy_loader = None
        self._lazy_loader_key = None
        # v2.2.9.2: Block signals BEFORE disconnecting so that queued
        # slice_ready emissions from the worker thread are silently
        # discarded instead of being delivered to _on_lazy_slice_ready
        # after the loader QObject is destroyed.
        if old_loader is not None:
            try:
                old_loader.blockSignals(True)
            except Exception:
                pass
        self._disconnect_lazy_loader_signals(old_loader)
        if old_key:
            # Defer release_loader to next event-loop tick so that any
            # already-queued signals referencing the old loader's QObject
            # are processed (and dropped by blockSignals) before the
            # QObject is destroyed by close().  Without this deferral,
            # Qt delivers queued events to a deleted C++ object → segfault.
            _key = str(old_key)

            def _deferred_release(_k=_key):
                try:
                    release_loader(_k)
                except Exception as _e:
                    logger.debug(
                        "viewer-lazy: deferred release_loader failed for key %s: %s", _k, _e
                    )

            QTimer.singleShot(0, _deferred_release)

    def _schedule_force_vtk_reload(self, reason: str):
        viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
        if viewer_controller is None:
            return

        series_number = None
        for meta in (getattr(self, "_bound_backend_metadata", None), getattr(getattr(self, "image_viewer", None), "metadata", None)):
            if not isinstance(meta, dict):
                continue
            sn = str((meta.get("series", {}) or {}).get("series_number", "")).strip()
            if sn:
                series_number = sn
                break
        if not series_number:
            return

        study_path = getattr(self.patient_widget, "import_folder_path", None)
        series_arg = int(series_number) if str(series_number).isdigit() else series_number

        def _reload():
            try:
                viewer_controller._load_single_series_on_demand(
                    series_number=series_arg,
                    study_path=study_path,
                    target_vtk_widget=self,
                    allow_paired=False,
                    viewer_backend=BACKEND_VTK,
                    force_reload=True,
                )
            except Exception as e:
                logger.warning("Force VTK reload failed for series %s: %s", series_number, e)

        logger.warning("PyDicom lazy decode failed: %s. Scheduling VTK fallback reload.", reason)
        threading.Thread(target=_reload, daemon=True, name="LazyDecodeFallback").start()

    def _on_lazy_decode_failed(self, reason):
        """Qt signal slot. Exceptions must never propagate through Qt dispatch.
        Outer guard mirrors the Stage 4 pattern on _on_lazy_slice_ready. (v2.2.9.4 Stage 5 Step G)
        """
        try:
            self._on_lazy_decode_failed_impl(reason)
        except Exception as exc:
            logger.error(
                "viewer-lazy: unhandled exception in _on_lazy_decode_failed "
                "viewer=%s reason=%s backend=%s lazy_loader=%s: %s",
                getattr(self, "id_vtk_widget", "?"),
                reason,
                getattr(self, "_active_backend", "?"),
                "present" if getattr(self, "_lazy_loader", None) is not None else "None",
                exc,
                exc_info=True,
            )

    def _on_lazy_decode_failed_impl(self, reason):
        if self._lazy_fallback_in_progress:
            return
        self._lazy_fallback_in_progress = True

        for meta in (getattr(self, "_bound_backend_metadata", None), getattr(getattr(self, "image_viewer", None), "metadata", None)):
            if not isinstance(meta, dict):
                continue
            series_meta = meta.get("series")
            if not isinstance(series_meta, dict):
                continue
            series_meta["force_vtk_fallback"] = True
            series_meta["viewer_backend"] = BACKEND_VTK
            series_meta.pop("lazy_loader_key", None)

        self._active_backend = BACKEND_VTK
        self._update_backend_badge()
        self._release_bound_lazy_loader()
        self._log_lazy_metrics_if_due(force=True)
        self._schedule_force_vtk_reload(str(reason))

    def _on_lazy_slice_ready(self, slice_index, decode_ms, cache_hit):
        """Qt signal slot. Exceptions must never propagate through Qt dispatch.
        This is also the primary traceback-capture point for late-phase lazy-callback
        crashes — exc_info=True ensures the throwing line is logged. (v2.2.9.3)
        """
        try:
            self._on_lazy_slice_ready_impl(slice_index, decode_ms, cache_hit)
        except Exception as exc:
            _cur_sl = "?"
            try:
                _iv = getattr(self, "image_viewer", None)
                if _iv is not None:
                    _cur_sl = int(_iv.GetSlice())
            except Exception:
                pass
            logger.error(
                "viewer-lazy: unhandled exception in _on_lazy_slice_ready "
                "viewer=%s slice=%s decode_ms=%s cache_hit=%s "
                "current_slice=%s requested_slice=%s requested_gen=%s "
                "series_gen=%s backend=%s lazy_loader=%s: %s",
                getattr(self, "id_vtk_widget", "?"),
                slice_index,
                decode_ms,
                cache_hit,
                _cur_sl,
                getattr(self, "_lazy_requested_slice", "?"),
                getattr(self, "_lazy_requested_generation", "?"),
                getattr(self, "_series_generation_id", "?"),
                getattr(self, "_active_backend", "?"),
                "present" if getattr(self, "_lazy_loader", None) is not None else "None",
                exc,
                exc_info=True,
            )

    def _on_lazy_slice_ready_impl(self, slice_index, decode_ms, cache_hit):
        if self._active_backend != BACKEND_PYDICOM:
            return
        # [H10-1] Mismatch detection — lazy frame delivery (throttled)
        _h10_cnt = getattr(self, '_h10_lazy_log_count', 0) + 1
        self._h10_lazy_log_count = _h10_cnt
        if _h10_cnt <= 3 or _h10_cnt % 20 == 0:
            try:
                _vsn = str(getattr(getattr(self, 'image_viewer', None), 'metadata', {}).get('series', {}).get('series_number', '?'))
                _pw = getattr(self, 'patient_widget', None)
                _dm = getattr(_pw, '_h10_dm_active_series', '?') if _pw else '?'
                logger.info(
                    "[H10-1] fn=_on_lazy_slice_ready viewer_series=%s dm_active=%s gen=%s req_gen=%s progressive=%s n=%d",
                    _vsn, _dm, self._series_generation_id, self._lazy_requested_generation,
                    getattr(self, '_progressive_mode', '?'), _h10_cnt,
                )
            except Exception:
                pass
        # v2.2.9.2: Do NOT call self.sender() here.  When the old loader's
        # QObject has been destroyed (via release_loader → close()), sender()
        # dereferences a dangling C++ pointer → segfault.  The generation
        # guard below (should_render_ready_slice) is the correct check.
        if self._lazy_loader is None:
            return

        try:
            decode_ms_f = max(0.0, float(decode_ms))
        except Exception:
            decode_ms_f = 0.0
        if decode_ms_f > 0.0:
            self._lazy_metrics["decode_ms_total"] += decode_ms_f
            self._lazy_metrics["decode_count"] += 1

        if self._lazy_requested_slice is None:
            self._log_lazy_metrics_if_due()
            return

        current_slice = None
        if self.image_viewer is not None:
            try:
                current_slice = int(self.image_viewer.GetSlice())
            except Exception:
                current_slice = None
        guard_current_slice = current_slice
        if self._active_backend == BACKEND_PYDICOM and self._lazy_requested_slice is not None:
            # PyDicom lazy path can transiently report stale viewer slice indices;
            # guard against false drops by validating against the requested target.
            guard_current_slice = int(self._lazy_requested_slice)
        if not should_render_ready_slice(
            ready_slice=int(slice_index),
            requested_slice=self._lazy_requested_slice,
            current_slice=guard_current_slice,
            ready_generation=int(self._lazy_requested_generation),
            current_generation=int(self._series_generation_id),
        ):
            self._lazy_drop_log_counter = int(self._lazy_drop_log_counter or 0) + 1
            _log_drop = (self._lazy_drop_log_counter == 1) or (self._lazy_drop_log_counter % 10 == 0)
            _log_fn = logger.info if _log_drop else logger.debug
            _log_fn(
                "viewer-lazy frame_delivery action=drop viewer=%s slice=%s requested=%s current=%s guard_current=%s "
                "ready_gen=%s current_gen=%s cache_hit=%s decode_ms=%.2f",
                str(getattr(self, "id_vtk_widget", None)),
                int(slice_index),
                str(self._lazy_requested_slice),
                str(current_slice),
                str(guard_current_slice),
                int(self._lazy_requested_generation),
                int(self._series_generation_id),
                bool(cache_hit),
                float(decode_ms_f),
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._on_lazy_slice_ready",
                    "stage": "frame_delivery",
                },
            )
            self._lazy_metrics["dropped_frames_count"] += 1
            self._log_lazy_metrics_if_due()
            return

        # H13-T6 instrumentation-only (no behavior change):
        # fresh live-current re-read at the exact post-guard insertion point.
        _t6_toggle_on = bool(_H13_STALE_RENDER_ABORT)
        _t6_thread_id = int(threading.get_ident())
        _t6_live_current = None
        try:
            if self.image_viewer is not None:
                _t6_live_current = int(self.image_viewer.GetSlice())
        except Exception:
            _t6_live_current = None

        _t6_reason = "other"
        _t6_abort_decision = False
        _t6_ready = int(slice_index)
        _t6_req = int(self._lazy_requested_slice) if self._lazy_requested_slice is not None else None
        _t6_guard = int(guard_current_slice) if guard_current_slice is not None else None

        if _t6_live_current is None:
            _t6_reason = "other"
        elif _t6_live_current != _t6_ready:
            _t6_reason = "stale"
        elif _t6_req is not None and _t6_live_current != _t6_req:
            _t6_reason = "mismatch"
        else:
            _t6_reason = "other"

        # Always-on stale condition counter (toggle-independent — valid in both T6-ON and T6-OFF runs)
        if _t6_reason in ("stale", "mismatch"):
            self._stale_condition_count = int(getattr(self, "_stale_condition_count", 0) or 0) + 1

        if _t6_toggle_on and _t6_reason in ("stale", "mismatch"):
            _t6_abort_decision = True
            self._stale_render_abort_count = int(getattr(self, "_stale_render_abort_count", 0) or 0) + 1

        # Log at INFO only when stale/mismatch detected; debug otherwise to limit noise
        _t6_log = logger.info if _t6_reason in ("stale", "mismatch") else logger.debug
        _t6_log(
            "[H13-T6-DIAG] toggle_state=%s ready_slice=%s requested_slice=%s live_current_slice=%s "
            "guard_current_slice=%s abort_decision=%s reason=%s viewer_id=%s thread_id=%s",
            "on" if _t6_toggle_on else "off",
            _t6_ready,
            _t6_req,
            _t6_live_current,
            _t6_guard,
            bool(_t6_abort_decision),
            _t6_reason,
            str(getattr(self, "id_vtk_widget", None)),
            _t6_thread_id,
            extra={
                "component": "viewer",
                "function": "VTKWidget._on_lazy_slice_ready",
                "stage": "t6_diagnostics",
            },
        )

        try:
            _fast_ready = False
            if self._last_scroll_event_ms is not None:
                _fast_ready = (
                    max(0.0, now_ms() - float(self._last_scroll_event_ms))
                    <= float(self._fast_interaction_idle_window_ms)
                )
            _active_velocity_sps = float(
                getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0
            )
            # v2.2.5.1: Skip render deferral in the lazy-ready callback.
            # The decode has already completed and this IS the currently requested
            # slice.  Deferring it adds pointless latency (the user is waiting to
            # see this exact frame).  Coalesce-level pacing is still handled by
            # the wheel/coalesce path that queues the decode request.
            if False and _fast_ready and self._should_defer_fast_slice_render(
                velocity_sps=float(_active_velocity_sps),
                now_ms_value=now_ms(),
            ):
                self._last_set_slice_deferred_render = True
                self._pending_wheel_slice = int(slice_index)
                self._pending_scroll_source = "stack_drag"
                self._pending_scroll_direction = int(
                    getattr(self, "_active_interaction_direction", 0) or 0
                )
                self._pending_scroll_velocity_sps = float(_active_velocity_sps)
                try:
                    if not self._wheel_coalesce_timer.isActive():
                        since_last = max(
                            0.0, now_ms() - float(self._last_fast_render_ms or 0.0)
                        )
                        _effective_min_interval = float(
                            self._effective_fast_render_min_interval_ms()
                        )
                        remaining = max(
                            1, int(float(_effective_min_interval) - float(since_last))
                        )
                        self._wheel_coalesce_timer.setInterval(remaining)
                        self._wheel_coalesce_timer.start()
                except Exception:
                    pass
                self._lazy_metrics["dropped_frames_count"] += 1
                self._log_lazy_metrics_if_due()
                return
            # Ensure VTK pipeline sees freshly decoded lazy slice data before render.
            # H13-P1: Check for write/render overlap before entering render chain.
            h13_check_overlap_before_render(int(slice_index), "_on_lazy_slice_ready_impl")
            # H13-P3: Log decode-to-render age.
            _h13_age = h13_get_decode_age_ms(int(slice_index))
            if _h13_age >= 0.0 and _h13_age < 5.0:
                logger.info("[H13-AGE] tight decode-to-render age=%.2fms slice=%d caller=lazy_ready", _h13_age, int(slice_index))
            # H13-T4: Render-chain gate — acquire _load_lock around full render chain.
            _h13_gate_held = False
            if _H13_RENDER_GATE and self._lazy_loader is not None and hasattr(self._lazy_loader, "_load_lock"):
                self._lazy_loader._load_lock.acquire()
                _h13_gate_held = True
            try:
                if self._lazy_loader is not None and hasattr(self._lazy_loader, "mark_vtk_modified"):
                    try:
                        with backing_store_probe("vtk_render"):
                            self._lazy_loader.mark_vtk_modified()
                    except Exception:
                        pass
                # mark_vtk_modified() above already called vtk_image_data.Modified() on the
                # lazy source. For pydicom_2d the viewer is now wired directly to that source
                # (bypassing image_reslice), so VTK's trivial producer detects the MTime
                # increase on Render() and re-reads the numpy-backed scalars automatically.
                # No image_reslice.Update() or .Modified() is needed.
                self._call_image_viewer_set_slice(int(slice_index), fast_interaction=bool(_fast_ready))
            finally:
                if _h13_gate_held:
                    self._lazy_loader._load_lock.release()
            self.image_viewer.last_index_slice_saved = int(slice_index)
            if _fast_ready:
                self._last_fast_render_ms = now_ms()
                self._fast_render_skip_chain = 0
            wl_ms = float(getattr(self.image_viewer, "last_wl_convert_ms", 0.0) or 0.0)
            if wl_ms > 0.0:
                self._lazy_metrics["wl_convert_ms_total"] += wl_ms
                self._lazy_metrics["wl_convert_count"] += 1
            self._mark_lazy_first_frame_if_needed()
            logger.info(
                "viewer-lazy frame_delivery action=render viewer=%s slice=%s requested=%s current=%s guard_current=%s "
                "ready_gen=%s current_gen=%s cache_hit=%s decode_ms=%.2f",
                str(getattr(self, "id_vtk_widget", None)),
                int(slice_index),
                str(self._lazy_requested_slice),
                str(current_slice),
                str(guard_current_slice),
                int(self._lazy_requested_generation),
                int(self._series_generation_id),
                bool(cache_hit),
                float(decode_ms_f),
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._on_lazy_slice_ready",
                    "stage": "frame_delivery",
                },
            )
            self._lazy_drop_log_counter = 0
        except Exception as e:
            logger.warning(
                "[H13-S5] Lazy frame render exception idx=%s viewer=%s backend=%s "
                "gen=%s/%s progressive=%s: %s",
                slice_index,
                getattr(self, 'id_vtk_widget', '?'),
                getattr(self, '_active_backend', '?'),
                getattr(self, '_series_generation_id', '?'),
                getattr(self, '_lazy_requested_generation', '?'),
                bool(getattr(self, '_is_progressive_active', False)),
                e,
                exc_info=True,
            )

        self._log_lazy_metrics_if_due()

    def _h11_bind_snapshot(self, label, metadata=None):
        """H11 diagnostic: capture bind/rebind lifecycle state snapshot."""
        try:
            _v_sn = None
            try:
                _iv = getattr(self, 'image_viewer', None)
                if _iv is not None and hasattr(_iv, 'metadata') and isinstance(_iv.metadata, dict):
                    _v_sn = _iv.metadata.get('series', {}).get('series_number')
            except Exception:
                pass
            _m_sn = None
            _m_ic = None
            if isinstance(metadata, dict):
                _m_sn = metadata.get('series', {}).get('series_number')
                _m_ic = metadata.get('series', {}).get('image_count')
            _loader = self._lazy_loader
            logger.info(
                "[H11] %s viewer=%s viewer_sn=%s meta_sn=%s "
                "loader_id=%s loader_key=%s gen=%s req_gen=%s req_slice=%s "
                "backend=%s progressive=%s loader_slices=%s meta_ic=%s",
                label,
                str(getattr(self, 'id_vtk_widget', '?')),
                _v_sn, _m_sn,
                id(_loader) if _loader is not None else 'None',
                str(self._lazy_loader_key or 'None'),
                int(self._series_generation_id),
                int(self._lazy_requested_generation) if self._lazy_requested_generation is not None else 'None',
                self._lazy_requested_slice,
                str(self._active_backend or 'None'),
                bool(getattr(self, '_progressive_mode', False)),
                int(getattr(_loader, 'slice_count', 0) or 0) if _loader is not None else 'None',
                _m_ic,
            )
        except Exception as e:
            logger.debug("[H11] snapshot error: %s", e)

    def _bind_backend_from_metadata(self, metadata, force_vtk=False, source="bind"):
        # [H11] Probe 1: entry state before any mutation
        self._h11_bind_snapshot("BIND_ENTRY(%s)" % source, metadata)
        self._selected_backend = load_viewer_backend(default=BACKEND_VTK)
        self._bound_backend_metadata = metadata if isinstance(metadata, dict) else None
        series_meta = {}
        if isinstance(metadata, dict):
            series_meta = metadata.get("series", {}) or {}
        dicom_read_ms = float(series_meta.get("pydicom_lazy_build_ms", -1.0) or -1.0)

        requested_backend = BACKEND_VTK if force_vtk else self._selected_backend
        resolution = resolve_viewer_backend(metadata=metadata, settings=requested_backend)
        self._log_backend_resolution(source=source, resolution=resolution, metadata=metadata)
        chosen_backend = str(resolution.get("backend", BACKEND_VTK) or BACKEND_VTK)

        # v2.3.3 Stage 2 hardening: if BACKEND_PYDICOM leaked through the
        # resolver (should be impossible unless escape hatch is active),
        # log a warning so it's visible in diagnostics.
        if chosen_backend == BACKEND_PYDICOM and not force_vtk:
            _escape = os.environ.get("AIPACS_FORCE_PYDICOM_2D", "").strip() == "1"
            if not _escape:
                logger.error(
                    "[BACKEND_SWITCH] UNEXPECTED: BACKEND_PYDICOM leaked to binding "
                    "viewer=%s series=%s — this should not happen without the escape hatch. "
                    "Remapping to BACKEND_PYDICOM_QT.",
                    getattr(self, "id_vtk_widget", "?"),
                    self._extract_series_number(metadata) or "-",
                )
                chosen_backend = BACKEND_PYDICOM_QT

        logger.info(
            "[BACKEND_SWITCH] rebind viewer=%s series=%s resolved=%s force_vtk=%s",
            getattr(self, "id_vtk_widget", "?"),
            self._extract_series_number(metadata) or "-",
            chosen_backend,
            force_vtk,
        )
        self._gpu_boost_plan = resolve_gpu_boost_plan(viewer_backend=chosen_backend)
        self._log_gpu_boost_plan(source=source, plan=self._gpu_boost_plan, metadata=metadata)
        lazy_key = str(resolution.get("lazy_loader_key", "") or "").strip()
        metadata_complete = bool(resolution.get("metadata_complete", True))

        reuse_bound_loader = (
            chosen_backend == BACKEND_PYDICOM
            and bool(lazy_key)
            and self._lazy_loader is not None
            and str(self._lazy_loader_key or "") == lazy_key
        )
        # [H11] Probe 2: reuse decision
        logger.info(
            "[H11] REUSE_DECISION viewer=%s reuse=%s "
            "cond_backend_pydicom=%s cond_lazy_key=%s cond_loader_exists=%s cond_key_match=%s "
            "chosen=%s lazy_key=%s old_key=%s",
            str(getattr(self, 'id_vtk_widget', '?')),
            reuse_bound_loader,
            chosen_backend == BACKEND_PYDICOM,
            bool(lazy_key),
            self._lazy_loader is not None,
            str(self._lazy_loader_key or "") == lazy_key if lazy_key else False,
            chosen_backend, lazy_key, str(self._lazy_loader_key or ""),
        )
        if not reuse_bound_loader:
            self._release_bound_lazy_loader()
        self._series_generation_id += 1
        self._lazy_requested_generation = self._series_generation_id
        self._lazy_requested_slice = None
        self._lazy_fallback_in_progress = False
        self._reset_lazy_metrics(dicom_read_ms=dicom_read_ms)

        if reuse_bound_loader:
            self._active_backend = BACKEND_PYDICOM
            self._update_backend_badge()
            logger.info(
                "viewer-backend stage=bind_series backend=%s viewer=%s series=%s slices=%s lazy_loader_key=%s generation=%s reuse_loader=%s",
                BACKEND_PYDICOM,
                str(getattr(self, "id_vtk_widget", None)),
                self._extract_series_number(metadata) or "-",
                int(getattr(self._lazy_loader, "slice_count", 0) or 0) if self._lazy_loader is not None else 0,
                str(self._lazy_loader_key or ""),
                int(self._series_generation_id),
                True,
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._bind_backend_from_metadata",
                    "stage": "bind_series",
                },
            )
            # [H11] Probe 3: exit after reuse
            self._h11_bind_snapshot("BIND_EXIT(reuse)", metadata)
            return

        if chosen_backend == BACKEND_PYDICOM and lazy_key:
            loader = acquire_loader(lazy_key)
            if loader is not None:
                self._lazy_loader = loader
                self._lazy_loader_key = lazy_key
                self._connect_lazy_loader_signals(loader)
                self._active_backend = BACKEND_PYDICOM
                self._update_backend_badge()
                logger.info(
                    "viewer-backend stage=bind_series backend=%s viewer=%s series=%s slices=%s lazy_loader_key=%s generation=%s reuse_loader=%s",
                    BACKEND_PYDICOM,
                    str(getattr(self, "id_vtk_widget", None)),
                    self._extract_series_number(metadata) or "-",
                    int(getattr(loader, "slice_count", 0) or 0),
                    str(lazy_key),
                    int(self._series_generation_id),
                    False,
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget._bind_backend_from_metadata",
                        "stage": "bind_series",
                    },
                )
                # [H11] Probe 3: exit after new loader
                self._h11_bind_snapshot("BIND_EXIT(new_loader)", metadata)
                return

        # ظ¤ظ¤ Qt backend: no lazy_loader needed, just validate metadata ظ¤ظ¤
        if chosen_backend == BACKEND_PYDICOM_QT:
            instances = []
            if isinstance(metadata, dict):
                instances = metadata.get("instances") or []
            if instances:
                self._active_backend = BACKEND_PYDICOM_QT
                self._update_backend_badge()
                logger.info(
                    "viewer-backend stage=bind_series backend=%s viewer=%s slices=%d generation=%s",
                    BACKEND_PYDICOM_QT,
                    str(getattr(self, "id_vtk_widget", None)),
                    len(instances),
                    int(self._series_generation_id),
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget._bind_backend_from_metadata",
                        "stage": "bind_series",
                    },
                )
                # [H11] Probe 3: exit Qt backend
                self._h11_bind_snapshot("BIND_EXIT(qt)", metadata)
                return
            # No instances ظْ fall through to VTK
            logger.warning(
                "[FAST-WARN] Qt backend requested but no instances in metadata, falling back to VTK "
                "viewer=%s instances_type=%s instances_len=%s series_backend=%s",
                str(self.id_vtk_widget),
                type(instances).__name__,
                len(instances) if instances is not None else "None",
                (metadata.get("series", {}).get("viewer_backend") if isinstance(metadata, dict) else "N/A"),
            )  # CP2 [FAST-WARN]

        if chosen_backend == BACKEND_PYDICOM:
            if isinstance(series_meta, dict):
                series_meta["force_vtk_fallback"] = True
                series_meta["viewer_backend"] = BACKEND_VTK
                series_meta.pop("lazy_loader_key", None)
            logger.warning(
                "Backend fallback to VTK for viewer=%s (metadata_complete=%s, lazy_key=%s)",
                str(self.id_vtk_widget),
                metadata_complete,
                bool(lazy_key),
            )

        self._active_backend = BACKEND_VTK
        self._update_backend_badge()
        # [H11] Probe 3: exit VTK fallback
        self._h11_bind_snapshot("BIND_EXIT(vtk_fallback)", metadata)

        # v2.3.3 Stage 2: post-bind sanity log — BACKEND_PYDICOM should
        # never be the active backend at bind-exit unless the escape hatch
        # (AIPACS_FORCE_PYDICOM_2D=1) is active.
        if self._active_backend == BACKEND_PYDICOM:
            _escape = os.environ.get("AIPACS_FORCE_PYDICOM_2D", "").strip() == "1"
            if not _escape:
                logger.error(
                    "[BACKEND_SWITCH] POST-BIND VIOLATION: _active_backend == "
                    "BACKEND_PYDICOM after binding viewer=%s — expected "
                    "BACKEND_PYDICOM_QT or BACKEND_VTK",
                    getattr(self, "id_vtk_widget", "?"),
                )

    def _ensure_lazy_slice_loaded(self, slice_index, mark_current=True):
        loader = self._lazy_loader
        if loader is None:
            return False
        if mark_current:
            self._lazy_requested_generation = self._series_generation_id
            self._lazy_requested_slice = int(slice_index)

        self._lazy_metrics["cache_requests"] += 1
        cache_hit = False
        try:
            idx = int(slice_index)
            if hasattr(loader, "set_slice_index"):
                cache_hit = bool(loader.set_slice_index(idx))
            else:
                cache_hit = bool(loader.ensure_slice_loaded(idx))
            if cache_hit:
                self._lazy_metrics["cache_hits"] += 1
                if mark_current:
                    self._mark_lazy_first_frame_if_needed()
        except Exception as e:
            logger.warning("Lazy slice request failed at idx=%s: %s", slice_index, e)
        self._log_lazy_metrics_if_due()
        return bool(cache_hit)

    def _update_backend_badge(self):
        backend = self._active_backend or BACKEND_VTK
        requested_backend = getattr(self, "_selected_backend", "") or ""
        bound_metadata = getattr(self, "_bound_backend_metadata", None)

        # Empty viewers are created before series metadata arrives, so the
        # active backend intentionally falls back to VTK during widget init.
        # In FAST mode that transient fallback was surfacing an "advance"
        # badge above empty layouts, which is misleading because the viewer is
        # still configured for FAST mode and will bind to pydicom_qt once data
        # lands. Prefer the requested backend until real metadata is bound.
        if backend in (BACKEND_PYDICOM_QT, BACKEND_PYDICOM) or (
            not bound_metadata and requested_backend in (BACKEND_PYDICOM_QT, BACKEND_PYDICOM)
        ):
            text = "Fast"
        else:
            text = "advance"
        self._backend_badge.setText(text)
        self._backend_badge.adjustSize()
        margin = 8
        x = max(0, (self.width() - self._backend_badge.width()) // 2)
        self._backend_badge.move(x, margin)
        self._backend_badge.raise_()

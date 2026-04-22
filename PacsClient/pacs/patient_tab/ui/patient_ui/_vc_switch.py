"""
Series-switch mixin for ViewerController.
change_series_on_viewer, async load-and-switch, spinner helpers, first-display, request tokens.
"""
from __future__ import annotations
import os
import threading
import time
import copy
import traceback
import gc
import logging as _logging
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QSlider
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from modules.viewer.fast.lazy_volume_registry import get_loader as get_lazy_loader
from modules.viewer.viewer_backend_config import BACKEND_VTK, BACKEND_PYDICOM
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview
from modules.zeta_boost import ImageSliceBooster
from PacsClient.utils.diagnostic_logging import new_correlation_id, set_log_context
import logging

logger = logging.getLogger(__name__)

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))


class _VCSwitchMixin:
    """Auto-split mixin — see patient_widget_viewer_controller.py for history."""

    def _should_use_interactive_preview(self, expected_slices: int) -> bool:
        """Return True when uncached interactive loads should show a quick preview.

        Phase 4 policy: preview is most valuable for large/heavy series, so we
        no longer gate it away just because the series is bigger than an old
        threshold. Single-slice series skip preview because the full load is the
        first image already.
        """
        try:
            if not bool(getattr(self, '_interactive_preview_enabled', False)):
                return False
            count = int(expected_slices or 0)
        except Exception:
            count = 0
        if count == 1:
            return False
        return True

    def _interactive_preview_file_cap(self) -> int:
        """Bound preview work to a small file window regardless of series size."""
        try:
            configured = int(getattr(self, '_interactive_preview_max_slices', 8) or 8)
        except Exception:
            configured = 8
        return max(1, min(8, configured))

    def _requires_serialized_interactive_load(self, viewer_backend: str) -> bool:
        """Only heavyweight VTK/SimpleITK loads should wait behind the load gate.

        Phase 4: FAST metadata-first backends already avoid the heavy ITK/VTK
        pipeline, so forcing them to wait for warmup drain or the serialized
        full-load semaphore only delays first usable image work without reducing
        meaningful contention.
        """
        try:
            backend = str(viewer_backend or BACKEND_VTK)
        except Exception:
            backend = BACKEND_VTK
        return backend == BACKEND_VTK

    def change_series_on_viewer(self, series_index, flag_change_selected_widget=True,
                                vtk_widget: VTKWidget = None, slider: QSlider = None,
                                allow_paired: bool = True):
        """
        âڑ، OPTIMIZED: Switch series with O(1) lookup and minimal overhead.
        
        Performance improvements:
        - Uses hash-based series cache instead of linear search
        - Eliminates redundant metadata extraction
        - Fast paired series detection with index
        - Removes artificial delays
        """
        switch_key = None
        try:
            _t0 = time.perf_counter()
            t_change_ms = now_ms()
            self.notify_viewer_interaction(reason="change_series")
            series_number = str(series_index)
            viewer_event_id = new_correlation_id("view")
            study_uid = str(getattr(self.parent_widget, "study_uid", "-"))
            set_log_context(viewer_event_id=viewer_event_id, study_uid=study_uid, series_uid=series_number)
            self.logger.info(
                "viewer-event start change_series_on_viewer series=%s",
                series_number,
                extra={
                    "component": "viewer",
                    "viewer_event_id": viewer_event_id,
                    "study_uid": study_uid,
                    "series_uid": series_number,
                },
            )

            # ── FAST timeline: series-selected milestone ──
            _fast_mode = (str(self._get_requested_viewer_backend()) not in ("vtk", "simpleitk"))
            self.logger.info(
                "FAST:series_selected series=%s event_id=%s t+0ms fast_mode=%s study_uid=%s",
                series_number, viewer_event_id, _fast_mode, study_uid,
            )

            # ── FAST: ZetaBoost status snapshot at series selection ──
            if _fast_mode:
                try:
                    _zb = getattr(self, 'zeta_boost', None)
                    if _zb is not None:
                        _zb_active = getattr(_zb, '_active', None)
                        _zb_dl_complete = getattr(_zb, '_study_download_complete', None)
                        _zb_global_count = getattr(type(_zb), '_global_active_download_count', None)
                        _zb_q_warmup = len(getattr(_zb, '_queue', {}).get('warmup', []))
                        _zb_q_bg = len(getattr(_zb, '_queue', {}).get('background', []))
                        _zb_q_interactive = len(getattr(_zb, '_queue', {}).get('interactive', []))
                        _zb_inflight = sum(
                            len(v) for v in getattr(_zb, '_inflight', {}).values()
                        )
                        self.logger.info(
                            "FAST:zetaboost_snapshot series=%s active=%s "
                            "study_dl_complete=%s global_dl_count=%s "
                            "q(i/w/b)=%s/%s/%s inflight=%s",
                            series_number, _zb_active, _zb_dl_complete, _zb_global_count,
                            _zb_q_interactive, _zb_q_warmup, _zb_q_bg, _zb_inflight,
                        )
                        # Derive causal explanation
                        if not _zb_active:
                            _reason = "engine_not_active"
                        elif not _zb_dl_complete:
                            _reason = "study_download_pending(intentional)"
                        elif _zb_global_count and int(_zb_global_count) > 0:
                            _reason = f"global_download_active({_zb_global_count})(intentional)"
                        elif _zb_q_warmup == 0 and _zb_q_bg == 0:
                            _reason = "queue_empty_fast_mode(FAST_uses_lazy_volume_not_ITK)"
                        else:
                            _reason = "active"
                        self.logger.info(
                            "FAST:zetaboost_verdict series=%s status=%s "
                            "reason=%s intentional=%s",
                            series_number,
                            "inactive" if _reason != "active" else "active",
                            _reason,
                            str(_reason != "active" and "unexpected" not in _reason),
                        )
                except Exception:
                    pass

            target_widget_for_spinner = vtk_widget

            # Fail-safe: never let spinner run forever if switching stalls.
            self._arm_spinner_timeout(target_widget_for_spinner, timeout_ms=20000)
            
            # Initialize parent structures once
            if not hasattr(self.parent_widget, 'lst_thumbnails_data'):
                self.parent_widget.lst_thumbnails_data = []

            # âœ… ENSURE VIEWERS EXIST (fail-fast check)
            if not self.lst_nodes_viewer:
                try:
                    self.apply_multi_viewer((1, 1), modify_by_user=False)
                except Exception as e:
                    self.logger.error(f"Failed to create default viewers: {e}")
                    return

            # Resolve target viewport early so load/apply stages use a single request token.
            if flag_change_selected_widget:
                if self.selected_widget is None and self.lst_nodes_viewer:
                    self.set_viewer_to_main_viewer(self.lst_nodes_viewer[0])
                vtk_widget = self.selected_widget
                slider = getattr(self.parent_widget, 'slider', None) or (
                    self.lst_nodes_viewer[0].slider if self.lst_nodes_viewer else None
                )
                target_widget_for_spinner = vtk_widget

            if vtk_widget is None or slider is None:
                self.logger.warning("change-series: invalid target viewport for series %s", series_number)
                self._hide_spinner_for_widget(target_widget_for_spinner)
                return

            # Clear any previous awaiting marker from a prior drag-drop that
            # targeted this viewer.  A new series switch supersedes the old one.
            try:
                vtk_widget._awaiting_series_number = None
            except Exception:
                pass

            # Re-entrancy guard: prevent duplicate same-series switch requests from
            # overlapping on the same viewport during active downloads.
            try:
                viewer_id = self._get_viewer_id(vtk_widget)
                switch_key = (viewer_id, series_number)
                if switch_key in self._viewer_switch_inflight:
                    self.logger.debug("change-series: suppressed duplicate switch series=%s viewer=%s", series_number, viewer_id)
                    self._hide_spinner_for_widget(target_widget_for_spinner)
                    return
                self._viewer_switch_inflight.add(switch_key)
            except Exception:
                switch_key = None
            requested_backend = self._get_requested_viewer_backend()

            # Fast no-op path: same series already displayed on this viewport.
            # Prevents expensive load-on-demand + reset work on repeated drops.
            try:
                current_series_no = None
                current_metadata = None
                if getattr(vtk_widget, 'image_viewer', None) is not None:
                    current_metadata = getattr(vtk_widget.image_viewer, 'metadata', {}) or {}
                    current_series_no = str(
                        current_metadata.get('series', {}).get('series_number', '')
                    )
                if current_series_no and current_series_no == series_number:
                    backend_mismatch = (
                        str(getattr(vtk_widget, "_active_backend", BACKEND_VTK) or BACKEND_VTK)
                        != str(requested_backend or BACKEND_VTK)
                    )
                    rebuild_needed = self._needs_backend_rebuild(current_metadata, requested_backend)
                    # Stuck-slice guard: if disk has more files than the currently
                    # displayed metadata, the series has grown — skip no-op.
                    series_grew = False
                    series_incomplete = False
                    expected_instances = 0
                    displayed_count = 0
                    disk_count = 0
                    completeness = None
                    try:
                        displayed_count = len((current_metadata or {}).get("instances", []) or [])
                        disk_count = self._count_series_files_on_disk(series_number)
                        resolution = self._resolve_series_expected_count(series_number)
                        expected_instances = int(resolution.expected_count or 0)
                        completeness = resolution.to_completeness_snapshot(
                            metadata_count=displayed_count,
                            disk_count=disk_count,
                        )
                        series_grew = completeness.metadata_behind_disk
                        series_incomplete = completeness.is_incomplete
                    except Exception:
                        pass
                    if (not backend_mismatch) and (not rebuild_needed) and (not series_grew) and (not series_incomplete):
                        if hasattr(vtk_widget, '_finalize_pending_action'):
                            try:
                                vtk_widget._finalize_pending_action(series_index, phase="switch_series_noop_same")
                            except Exception:
                                pass
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        self.logger.debug("change-series: noop same-series series=%s total=%.1fms", series_number, (time.perf_counter() - _t0) * 1000)
                        return
                    if series_incomplete:
                        self.logger.info(
                            "change-series: same-series retry incomplete series=%s displayed=%s disk=%s expected=%s",
                            series_number, displayed_count, disk_count, expected_instances,
                        )
                        # Reassert critical download request for repeated drag/drop.
                        # _trigger_download_if_needed has its own short dedup window.
                        self._trigger_download_if_needed(series_number)
                    # Same series re-drop with growth: if a lazy loader is present,
                    # grow it in-place instead of doing an expensive full reload
                    # that would restart the volume from scratch.
                    if series_grew and (not backend_mismatch) and (not rebuild_needed):
                        _grew_ok = False
                        try:
                            loader = getattr(vtk_widget, "_lazy_loader", None)
                            if (getattr(vtk_widget, '_active_backend', None) == "pydicom_qt"  # CP6 [FAST-WARN]
                                    and loader is None):
                                self.logger.warning(
                                    "[FAST-WARN] change_series grow: backend=pydicom_qt but _lazy_loader=None "
                                    "series=%s displayed=%d disk=%d — QtViewerBridge.grow() will NOT be called",
                                    series_number, displayed_count, disk_count,
                                )
                            backend = getattr(loader, "backend", None) if loader else None
                            _has_grow = loader is not None and hasattr(loader, "grow")
                            _has_refresh = backend is not None and hasattr(backend, "refresh_file_list")
                            if _has_grow or _has_refresh:
                                # grow() first (preserves file-path snapshot integrity for
                                # interleaved DICOM); fall back to refresh_file_list() only
                                # when no grow() is available.
                                if _has_grow:
                                    new_count = loader.grow()
                                else:
                                    new_count = backend.refresh_file_list()
                                self._update_vtk_slice_range(vtk_widget, None, new_count, slider=slider)
                                self._refresh_and_sync_metadata(series_number, new_count)
                                _grew_ok = True
                                self.logger.debug(
                                    "change-series: in-place grow series=%s slices=%d total=%.1fms",
                                    series_number, new_count, (time.perf_counter() - _t0) * 1000,
                                )
                        except Exception as _grow_exc:
                            self.logger.debug("same-series in-place grow failed: %s", _grow_exc)
                        if _grew_ok:
                            self._hide_spinner_for_widget(target_widget_for_spinner)
                            return
                    self.logger.debug(
                        "change-series: backend-reload series=%s current=%s requested=%s rebuild_needed=%s",
                        series_number, getattr(vtk_widget, '_active_backend', BACKEND_VTK),
                        requested_backend, rebuild_needed,
                    )
            except Exception:
                pass

            # Attach pending UI action trace to target viewport (if provided by parent widget).
            current_action_id = None
            try:
                pending_action_id = getattr(self.parent_widget, '_pending_action_id', None)
                if pending_action_id and not getattr(vtk_widget, '_pending_action_id', None):
                    vtk_widget._pending_action_id = pending_action_id
                    pending_series = getattr(self.parent_widget, '_pending_action_series', None)
                    if pending_series is not None:
                        vtk_widget._pending_action_series = str(pending_series)
                    current_action_id = pending_action_id
                    # consume once to avoid cross-event contamination
                    self.parent_widget._pending_action_id = None
                    self.parent_widget._pending_action_series = None
            except Exception:
                pass

            if not current_action_id:
                try:
                    current_action_id = getattr(vtk_widget, '_pending_action_id', None)
                except Exception:
                    current_action_id = None

            # OFF-mode manual trigger: activate on explicit user view request
            # (drag/drop OR thumbnail click/double-click in Patient tab).
            if self._is_explicit_view_request(current_action_id, flag_change_selected_widget):
                trigger_reason = str(current_action_id or f"viewer_request series={series_number}")
                self._activate_zeta_manual_trigger(reason=trigger_reason)

                # Notify DM of viewed series so priority updates in the DM UI.
                # This ensures the drag-dropped / clicked series becomes CRITICAL
                # and other downloading series show their adjusted state.
                self._notify_dm_viewed_series(series_number)

            self._arm_spinner_timeout(vtk_widget, timeout_ms=20000)
            expected_token = self._next_request_token(vtk_widget)
            self.logger.info(
                "viewer-backend stage=route series=%s viewer=%s requested_backend=%s",
                series_number,
                str(getattr(vtk_widget, "id_vtk_widget", None)),
                requested_backend,
                extra={
                    "component": "viewer",
                    "function": "ViewerController.change_series_on_viewer",
                    "stage": "backend_route",
                },
            )

            # âڑ، FAST PATH: O(1) series lookup with caching
            vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_number)
            cache_hit = metadata is not None
            log_stage_timing(
                self.logger,
                component="viewer",
                function="ViewerController.change_series_on_viewer",
                stage="cache_lookup",
                start_ms=t_change_ms,
                cache_hit=str(cache_hit),
            )

            # ── Stuck-slice guard: verify cached instance count matches disk ──
            # If more files exist on disk than the cached metadata knows about,
            # the cache is stale (series was opened during partial download).
            # Show the stale cache IMMEDIATELY (no visual delay), then schedule
            # a background reload that silently refreshes the viewer when done.
            # IMPORTANT: do NOT block the drag-drop fast-path with a synchronous
            # reload — the user must see the image within 1 frame.
            if metadata is not None:
                try:
                    cached_instance_count = len(metadata.get("instances", []) or [])
                    disk_count = self._count_series_files_on_disk(series_number)
                    if disk_count > 0 and disk_count > cached_instance_count:
                        print(
                            f"🔄 [STALE_GUARD] series={series_number} "
                            f"cached_instances={cached_instance_count} disk_files={disk_count} → show stale + bg refresh"
                        )
                        # Schedule a background reload AFTER the switch completes.
                        # Use a short delay so the viewer first shows what it has.
                        _sn_stale = str(series_number)
                        _vw_stale = vtk_widget
                        _slider_stale = slider
                        _paired_stale = allow_paired
                        _token_stale = expected_token
                        _target_stale = target_widget_for_spinner
                        _t0_stale = _t0
                        _backend_stale = requested_backend

                        def _bg_stale_refresh():
                            try:
                                self._invalidate_series_caches(_sn_stale)
                                _study_path = self._get_correct_study_path()
                                self._schedule_async_load_and_switch(
                                    series_number=_sn_stale,
                                    study_path=_study_path,
                                    vtk_widget=_vw_stale,
                                    slider=_slider_stale,
                                    allow_paired=_paired_stale,
                                    expected_token=_token_stale,
                                    target_widget_for_spinner=_target_stale,
                                    total_start=_t0_stale,
                                    viewer_backend=_backend_stale,
                                    force_reload=True,
                                )
                            except Exception:
                                pass

                        QTimer.singleShot(150, _bg_stale_refresh)
                        # Fall through so the stale cache is used for immediate display
                except Exception:
                    pass

            # Canonicalize index before switching to avoid stale-index false no-op.
            if metadata is not None:
                canonical_idx = self._series_number_to_index.get(series_number)
                if canonical_idx is not None and int(canonical_idx) >= 0:
                    series_idx = int(canonical_idx)
                else:
                    for i, data in enumerate(self.parent_widget.lst_thumbnails_data):
                        if str(data.get('metadata', {}).get('series', {}).get('series_number')) == series_number:
                            series_idx = i
                            break
            
            # If not cached, search and cache (only one pass)
            if metadata is None:
                # Linear search only if not in any cache (happens once per series)
                for i, data in enumerate(self.parent_widget.lst_thumbnails_data):
                    if str(data.get('metadata', {}).get('series', {}).get('series_number')) == series_number:
                        vtk_image_data = data['vtk_image_data']
                        metadata = data['metadata']
                        series_idx = i
                        # Cache immediately for next access
                        self._series_cache[series_number] = (vtk_image_data, metadata, series_idx)
                        break

            # PyDicom mode guard: cached VTK payloads must be rebuilt with lazy metadata.
            if metadata is not None and self._needs_backend_rebuild(metadata, requested_backend):
                print(
                    f"[BACKEND_RELOAD] series={series_number} rebuilding payload for backend={requested_backend}"
                )
                self._series_cache.pop(series_number, None)
                self._hot_series_cache.pop(series_number, None)
                metadata = None
                vtk_image_data = None
                cache_hit = False
            
            # If still not found, try loading from disk
            if metadata is None:
                study_path = self._get_correct_study_path()
                # Show loading spinner and clear old image so the user doesn't
                # see stale content from a previous series while waiting.
                try:
                    if hasattr(vtk_widget, 'viewport_spinner'):
                        vtk_widget.viewport_spinner.show_loading(
                            f"Loading series {series_number}..."
                        )
                except Exception:
                    pass
                # Run heavy DICOM/ITK load in background to keep UI responsive.
                self._schedule_async_load_and_switch(
                    series_number=series_number,
                    study_path=study_path,
                    vtk_widget=vtk_widget,
                    slider=slider,
                    allow_paired=allow_paired,
                    expected_token=expected_token,
                    target_widget_for_spinner=target_widget_for_spinner,
                    total_start=_t0,
                    viewer_backend=requested_backend,
                    force_reload=(requested_backend == BACKEND_PYDICOM),
                )
                return

            # âڑ، PERFORM SWITCH WITH OPTIMIZED PAIRED SERIES LOOKUP
            self._perform_series_switch_optimized(vtk_widget, metadata, vtk_image_data, series_idx, slider,
                                                  allow_paired=allow_paired,
                                                  expected_token=expected_token)
            self._hide_spinner_for_widget(target_widget_for_spinner)
            if not bool(getattr(self, '_first_series_displayed', False)):
                self._mark_first_series_displayed()
            log_stage_timing(
                self.logger,
                component="viewer",
                function="ViewerController.change_series_on_viewer",
                stage="viewer_switch_apply",
                start_ms=t_change_ms,
                cache_hit=str(cache_hit),
            )
            print(
                f"[PROFILE] change_series_on_viewer: series={series_number} cache_hit={cache_hit} "
                f"total={(time.perf_counter() - _t0)*1000:.1f}ms"
            )

        except Exception as e:
            self.logger.error(f"Error switching series: {e}", exc_info=True)
            logger.error(f"â‌Œ [SWITCH FAIL] series={series_index} error={e}")
            try:
                self._hide_spinner_for_widget(vtk_widget)
            except Exception:
                pass
        finally:
            try:
                if switch_key is not None:
                    self._viewer_switch_inflight.discard(switch_key)
            except Exception:
                pass
            log_stage_timing(
                self.logger,
                component="viewer",
                function="ViewerController.change_series_on_viewer",
                stage="viewer_event_total",
                start_ms=t_change_ms,
                series=str(series_index),
            )
            self._interactive_load_in_progress = False
            self._set_zeta_external_interactive_busy(bool(self._async_switch_inflight), reason="switch_finally")

    def _schedule_async_load_and_switch(self, series_number: str, study_path: str,
                                        vtk_widget: VTKWidget, slider: QSlider,
                                        allow_paired: bool, expected_token,
                                        target_widget_for_spinner,
                                        total_start: float,
                                        viewer_backend: str = BACKEND_VTK,
                                        force_reload: bool = False):
        """Load uncached series in background and apply on UI thread when ready."""
        viewer_id = self._get_viewer_id(vtk_widget)
        inflight_key = (viewer_id, str(series_number))
        if inflight_key in self._async_switch_inflight:
            logger.debug(f"âڈ³ [ASYNC SWITCH] series={series_number} already in-flight for viewer={viewer_id}")
            return

        self._async_switch_inflight.add(inflight_key)
        self._interactive_load_in_progress = True
        self._set_zeta_external_interactive_busy(True, reason=f"series={series_number} viewer={viewer_id}")

        def _worker():
            _t_load = time.perf_counter()
            ok = False
            preview_applied = False

            # Preview-first path: show a very fast first-slice preview while full load runs.
            try:
                exp_slices = self._get_series_expected_slices(series_number)
                use_preview = self._should_use_interactive_preview(exp_slices)
                if use_preview:
                    preview = load_series_preview(
                        study_path=study_path,
                        series_number=int(series_number),
                        patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                        study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                        max_files=self._interactive_preview_file_cap(),
                    )
                    if preview:
                        vtk_prev, meta_prev, (p_pk, s_pk), _total_files = preview
                        if vtk_prev is not None and isinstance(meta_prev, dict):
                            def _apply_preview_ui():
                                try:
                                    if not self._is_request_current(vtk_widget, expected_token):
                                        return
                                    current_meta = getattr(getattr(vtk_widget, 'image_viewer', None), 'metadata', {}) or {}
                                    current_series = str(current_meta.get('series', {}).get('series_number', '') or '')
                                    current_is_preview = bool(current_meta.get('preview_only', False))
                                    if current_series == str(series_number) and not current_is_preview:
                                        logger.debug(
                                            "[ASYNC SWITCH] skip stale preview apply series=%s viewer=%s",
                                            series_number,
                                            viewer_id,
                                        )
                                        return
                                    vid = self._get_viewer_id(vtk_widget)
                                    self._apply_loaded_series_data(
                                        int(series_number),
                                        vtk_prev,
                                        meta_prev,
                                        p_pk,
                                        s_pk,
                                        refresh_viewer=True,
                                        target_viewer_id=vid,
                                        allow_paired=False,
                                        expected_token=expected_token,
                                    )
                                except Exception:
                                    pass
                            self._queue_on_ui_thread(_apply_preview_ui)
                            preview_applied = True
            except Exception:
                pass

            # Concurrent ITK guard: wait for any in-flight warmup/background ITK to
            # finish before starting this interactive ITK pipeline.  On weak hardware
            # (PC B, GLES2) two simultaneous ITK runs compete for CPU and each takes
            # 2x longer.  Waiting up to 3s for the current warmup to drain, then
            # running alone, is faster than 4-6s of concurrent execution.
            # _set_zeta_external_interactive_busy(True) already prevents NEW warmup
            # items from starting; this waits for the CURRENT inflight item to finish.
            if self._requires_serialized_interactive_load(viewer_backend):
                try:
                    if hasattr(self, 'zeta_boost') and self.zeta_boost is not None:
                        _drained = self.zeta_boost.wait_for_inflight_drain(timeout_sec=3.0)
                        if not _drained:
                            logger.debug(f"[ASYNC SWITCH] warmup still inflight after 3s, proceeding with contention for series={series_number}")
                except Exception:
                    pass

            try:
                ok = self._load_single_series_on_demand(
                    int(series_number),
                    study_path,
                    target_vtk_widget=vtk_widget,
                    allow_paired=allow_paired,
                    expected_token=expected_token,
                    viewer_backend=viewer_backend,
                    force_reload=force_reload,
                )
            except Exception as e:
                self.logger.debug(f"Async load failed for series {series_number}: {e}")
                ok = False

            def _finish_on_ui():
                try:
                    self._interactive_load_in_progress = False
                    self._async_switch_inflight.discard(inflight_key)
                    self._set_zeta_external_interactive_busy(bool(self._async_switch_inflight), reason="finish_async_switch")

                    # Guard: verify vtk_widget is still alive (could have been deleted
                    # if the user closed the tab or changed layout while load was running).
                    try:
                        _w_alive = vtk_widget.isVisible()
                    except RuntimeError:
                        logger.debug(f"âڑ ï¸ڈ [ASYNC SWITCH] vtk_widget deleted for series={series_number}, aborting apply")
                        return

                    if not self._is_request_current(vtk_widget, expected_token):
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        return

                    if not ok:
                        self._trigger_download_if_needed(series_number)
                        logger.error(f"[PROFILE] change_series_on_viewer: async load-on-demand FAILED for series {series_number} in {(time.perf_counter() - _t_load)*1000:.1f}ms")
                        if preview_applied:
                            logger.error(f"â„¹ï¸ڈ [ASYNC SWITCH] preview remained active for series={series_number} (full load failed)")
                        # Keep spinner visible and mark this viewer as awaiting
                        # the series download.  Progressive display will populate
                        # it once the first batch arrives from the DM.
                        try:
                            vtk_widget._awaiting_series_number = str(series_number)
                            if hasattr(vtk_widget, 'viewport_spinner'):
                                vtk_widget.viewport_spinner.show_loading(
                                    f"Downloading series {series_number}..."
                                )
                            print(
                                f"⏳ [AWAIT] viewer marked awaiting series={series_number} "
                                f"(spinner kept visible)"
                            )
                        except Exception:
                            self._hide_spinner_for_widget(target_widget_for_spinner)
                        return

                    logger.debug(f"[PROFILE] change_series_on_viewer: async load-on-demand OK for series {series_number} in {(time.perf_counter() - _t_load)*1000:.1f}ms")
                    _already_applied = False
                    try:
                        current_meta = getattr(getattr(vtk_widget, 'image_viewer', None), 'metadata', {}) or {}
                        current_series = str(current_meta.get('series', {}).get('series_number', '') or '')
                        current_is_preview = bool(current_meta.get('preview_only', False))
                        _already_applied = current_series == str(series_number) and not current_is_preview
                    except Exception:
                        _already_applied = False

                    if _already_applied:
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        if not bool(getattr(self, '_first_series_displayed', False)):
                            self._mark_first_series_displayed()
                        print(
                            f"[PROFILE] change_series_on_viewer: series={series_number} cache_hit=False "
                            f"total={(time.perf_counter() - total_start)*1000:.1f}ms "
                            f"finish_action=skip_duplicate_switch"
                        )
                        return

                    vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_number)
                    if metadata is None or vtk_image_data is None:
                        logger.debug(f"â‌Œ [SWITCH FAIL] series={series_number} not found in cache after async loading")
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        return

                    self._perform_series_switch_optimized(
                        vtk_widget,
                        metadata,
                        vtk_image_data,
                        series_idx,
                        slider,
                        allow_paired=allow_paired,
                        expected_token=expected_token,
                    )
                    self._hide_spinner_for_widget(target_widget_for_spinner)
                    if not bool(getattr(self, '_first_series_displayed', False)):
                        self._mark_first_series_displayed()
                    print(
                        f"[PROFILE] change_series_on_viewer: series={series_number} cache_hit=False "
                        f"total={(time.perf_counter() - total_start)*1000:.1f}ms "
                        f"finish_action=fallback_switch"
                    )
                except Exception as e:
                    logger.debug(f"â‌Œ [ASYNC SWITCH] _finish_on_ui crashed for series={series_number}: {e}")
                    import traceback; traceback.print_exc()
                finally:
                    self._interactive_load_in_progress = False
                    self._set_zeta_external_interactive_busy(bool(self._async_switch_inflight), reason="finish_async_switch_finally")

            self._queue_on_ui_thread(_finish_on_ui)

        threading.Thread(target=_worker, daemon=True, name=f"AsyncSwitchLoad-{series_number}-v{viewer_id}").start()

    def _ensure_import_folder_path(self) -> str:
        """Ensure parent_widget.import_folder_path is set and return the study path.

        During download-time viewing, the PatientWidget may have been created
        before any files landed on disk.  This helper resolves the path from
        SOURCE_PATH + study_uid and stamps it on the widget so that all
        downstream loaders (``_load_single_series_on_demand``, lazy backends,
        ZetaBoost) can find the series directories.

        Returns the study-level directory as a string, or None if unresolvable.
        """
        from pathlib import Path
        pw = self.parent_widget
        if pw.import_folder_path and Path(pw.import_folder_path).exists():
            return str(pw.import_folder_path)
        try:
            from PacsClient.utils.config import SOURCE_PATH
            study_uid = str(getattr(pw, 'study_uid', '') or '')
            if study_uid:
                candidate = Path(SOURCE_PATH) / study_uid
                if candidate.exists():
                    pw.import_folder_path = str(candidate)
                    self.logger.info(
                        "progressive: set import_folder_path=%s", candidate,
                    )
                    return str(candidate)
        except Exception:
            pass
        # Final fallback: try the existing resolver
        try:
            from PacsClient.pacs.patient_tab.utils import get_study_source_path
            study_uid = str(getattr(pw, 'study_uid', '') or '')
            if study_uid:
                resolved, _ = get_study_source_path(study_uid)
                if resolved:
                    pw.import_folder_path = str(resolved)
                    return str(resolved)
        except Exception:
            pass
        return None

    def _get_correct_study_path(self) -> str:
        """Get the correct study path, ensuring it's not pointing to a series subfolder"""
        try:
            resolver = getattr(self.parent_widget, "_get_correct_study_path", None)
            if callable(resolver):
                resolved = resolver()
                if resolved:
                    resolved_path = Path(str(resolved))
                    if resolved_path.exists():
                        return str(resolved_path)
        except Exception:
            pass

        try:
            import_path = getattr(self.parent_widget, 'import_folder_path', None)
            if import_path:
                import_path_obj = Path(str(import_path))
                if import_path_obj.exists():
                    return str(import_path_obj)
        except Exception:
            pass

        try:
            return self._ensure_import_folder_path()
        except Exception:
            return None

    def _perform_series_switch_optimized(self, vtk_widget, metadata, vtk_image_data, series_idx, slider,
                                         allow_paired: bool = True, expected_token=None):
        """
        âڑ، OPTIMIZED: Perform series switch with O(1) paired series lookup.
        
        Performance improvements:
        - Fast paired series detection using index
        - No redundant list iterations
        - Direct metadata access without nesting lookups
        - Shows loading spinner for series changes
        """
        try:
            if not self._is_request_current(vtk_widget, expected_token):
                return
            requested_backend = self._get_requested_viewer_backend()

            # Validate vtk_image_data before switching; attempt recovery if needed.
            if not vtk_image_data:
                logger.debug("âڑ ï¸ڈ [SWITCH RECOVERY] Invalid vtk_image_data (None), attempting recovery")
                series_no = str(metadata.get('series', {}).get('series_number', '')) if isinstance(metadata, dict) else ''
                if series_no.isdigit():
                    recovered = self._load_single_series_on_demand(
                        int(series_no),
                        self._get_correct_study_path(),
                        target_vtk_widget=vtk_widget,
                        allow_paired=allow_paired,
                        expected_token=expected_token,
                        viewer_backend=requested_backend,
                        force_reload=(requested_backend == BACKEND_PYDICOM),
                    )
                    if recovered:
                        vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_no)
                if not vtk_image_data:
                    logger.error("â‌Œ [SWITCH ABORT] Recovery failed: vtk_image_data still invalid")
                    return

            dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
            if not dims or int(dims[0]) <= 0 or int(dims[1]) <= 0 or int(dims[2]) <= 0:
                logger.debug(f"âڑ ï¸ڈ [SWITCH RECOVERY] Invalid dimensions {dims}, attempting recovery")
                series_no = str(metadata.get('series', {}).get('series_number', '')) if isinstance(metadata, dict) else ''
                if series_no.isdigit():
                    recovered = self._load_single_series_on_demand(
                        int(series_no),
                        self._get_correct_study_path(),
                        target_vtk_widget=vtk_widget,
                        allow_paired=allow_paired,
                        expected_token=expected_token,
                        viewer_backend=requested_backend,
                        force_reload=(requested_backend == BACKEND_PYDICOM),
                    )
                    if recovered:
                        vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_no)
                        dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
                if not dims or int(dims[0]) <= 0 or int(dims[1]) <= 0 or int(dims[2]) <= 0:
                    logger.error("â‌Œ [SWITCH ABORT] Recovery failed: invalid dimensions remain")
                    return

            metadata = self._clone_metadata_for_switch(metadata)
            series_number = str(metadata.get('series', {}).get('series_number', ''))
            series_name = str(metadata.get('series', {}).get('series_name', ''))
            _t_psso = time.perf_counter()

            # --- DEBUG: log series image counts (thumbnail vs viewer) ---
            try:
                dims = vtk_image_data.GetDimensions() if vtk_image_data is not None else (0, 0, 0)
                vtk_slice_count = int(dims[2]) if dims and len(dims) > 2 else 0
            except Exception:
                vtk_slice_count = 0

            expected_instances = 0
            try:
                expected_instances = len(metadata.get('instances', []) or [])
            except Exception:
                expected_instances = 0

            server_image_count = None
            try:
                series_info = getattr(self.parent_widget, '_server_series_info', {}).get(series_number)
                if series_info is not None:
                    server_image_count = series_info.get('image_count')
            except Exception:
                server_image_count = None

            print(
                f"ًں”ژ [SERIES COUNT] req_series={series_number} name='{series_name}' "
                f"instances={expected_instances} vtk_slices={vtk_slice_count} "
                f"thumb_image_count={server_image_count}"
            )
            
            # ًںژ¬ Show loading spinner before switch
            # The message is set in switch_series based on series size
            # but we can optionally enhance it here if needed
            
            # âڑ، FAST PAIRED SERIES LOOKUP: O(1) instead of linear search
            # âœ… CRITICAL FIX: Only pair series for MG (Mammography) modality
            # For other modalities, series with same name should NOT be combined
            vtk_widget_data_2 = None
            metadata_2 = None
            
            # Check if current series is MG modality
            current_modality = metadata.get('series', {}).get('modality', '').upper() if metadata else ''
            is_mg_modality = current_modality == 'MG'
            
            # Only pair series for MG modality
            if allow_paired and is_mg_modality and series_name in self._paired_series_map:
                # Find first paired series that's not the current one
                paired_list = self._paired_series_map[series_name]
                for paired_num in paired_list:
                    if str(paired_num) != series_number:
                        vtk_data, meta, _ = self._get_series_by_number_fast(str(paired_num))
                        if vtk_data is not None and meta is not None:
                            # Double-check that paired series is also MG modality
                            paired_modality = meta.get('series', {}).get('modality', '').upper() if meta else ''
                            if paired_modality == 'MG':
                                vtk_widget_data_2 = vtk_data
                                metadata_2 = self._clone_metadata_for_switch(meta)
                                break
            
            # Log debug info when pairing is skipped
            if allow_paired and not is_mg_modality and series_name in self._paired_series_map:
                print(
                    f"â„¹ï¸ڈ [PAIRED SKIP] series={series_number} modality={current_modality} - "
                    f"Skipping pairing (only MG modality uses paired series)"
                )

            if metadata_2 is not None:
                try:
                    paired_series_number = str(metadata_2.get('series', {}).get('series_number', ''))
                    paired_instances = len(metadata_2.get('instances', []) or [])
                    paired_dims = vtk_widget_data_2.GetDimensions() if vtk_widget_data_2 is not None else (0, 0, 0)
                    paired_slices = int(paired_dims[2]) if paired_dims and len(paired_dims) > 2 else 0
                    print(
                        f"ًں”— [SERIES COUNT] paired_series={paired_series_number} "
                        f"instances={paired_instances} vtk_slices={paired_slices}"
                    )
                except Exception:
                    pass
            
            # âڑ، PERFORM SWITCH (no delay, no blocking)
            _t_switch_ms = 0.0
            _t_reset_ms = 0.0
            _t_boost_ms = 0.0
            _t_corners_ms = 0.0
            _t_refline_ms = 0.0
            if hasattr(vtk_widget, 'switch_series'):
                _t0_sw = time.perf_counter()
                flag_switch = vtk_widget.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    vtk_widget_data_2,
                    metadata_2,
                    self.parent_widget.metadata_fixed
                )
                _t_switch_ms = (time.perf_counter() - _t0_sw) * 1000

                if flag_switch:
                    # Quick slider configuration (without blocking)
                    _t0_rs = time.perf_counter()
                    self.parent_widget.reset_slider(vtk_widget, slider)
                    _t_reset_ms = (time.perf_counter() - _t0_rs) * 1000
                    try:
                        vtk_widget._awaiting_series_number = None
                    except Exception:
                        pass
                    # Diagnostic: verify state after series switch
                    _cnt = vtk_widget.get_count_of_slices() if vtk_widget else 0
                    _iv_ok = (getattr(vtk_widget, 'image_viewer', None) is not None) if vtk_widget else False
                    _sl_ok = (getattr(vtk_widget, 'slider', None) is not None) if vtk_widget else False
                    print(f"[POST-SWITCH] viewer={getattr(vtk_widget,'id_vtk_widget','?')} "
                          f"image_viewer={'Y' if _iv_ok else 'N'} slider={'Y' if _sl_ok else 'N'} "
                          f"count_slices={_cnt}", flush=True)
                    self.parent_widget.toolbar_manager.turn_off_all_tools()

                    # Qt/FAST presentation repair: series switches can complete
                    # before the target viewport finishes its layout pass. When
                    # zoom-to-fit is computed against that stale child geometry,
                    # the image appears shrunk into a corner until a later UI
                    # event (often a click) triggers another presentation sync.
                    # Fresh Qt starts already perform their own zoom-to-fit
                    # inside _start_qt_viewer(); only in-place refreshes need
                    # a deferred follow-up refit here.
                    if (
                        getattr(vtk_widget, '_qt_bridge_active', False)
                        and hasattr(vtk_widget, '_sync_qt_viewer_presentation')
                        and not bool(getattr(vtk_widget, '_qt_switch_refit_applied', False))
                    ):
                        QTimer.singleShot(
                            0,
                            lambda vw=vtk_widget: vw._sync_qt_viewer_presentation(refit_view=True),
                        )

                    # Activate progressive mode if this series is still downloading
                    if series_number in self._progressive_series:
                        _prog_info = self._progressive_series[series_number]
                        _prog_total = _prog_info.get("total", 0)
                        if _prog_total > 0:
                            avail = vtk_widget.get_count_of_slices()
                            vtk_widget.enter_progressive_mode(_prog_total, series_number)
                            vtk_widget.update_available_slice_count(avail)
                            if slider is not None:
                                try:
                                    slider.blockSignals(True)
                                    slider.setMaximum(max(0, _prog_total - 1))
                                    slider.blockSignals(False)
                                except Exception:
                                    pass
                            self.logger.info(
                                "progressive: activated on user switch series=%s avail=%d total=%d",
                                series_number, avail, _prog_total,
                            )

                    # --- DEBUG: verify viewer count after switch ---
                    try:
                        viewer = getattr(vtk_widget, 'image_viewer', None)
                        viewer_type = type(viewer).__name__ if viewer is not None else 'None'
                        viewer_count = viewer.get_count_of_slices() if viewer is not None else 0
                        viewer_skip = getattr(viewer, 'skip_slices', None)
                        print(
                            f"âœ… [SERIES COUNT] viewer={viewer_type} series={series_number} "
                            f"viewer_slices={viewer_count} skip={viewer_skip}"
                        )
                        if metadata_2 is None and expected_instances and viewer_count and viewer_count != expected_instances:
                            print(
                                f"âڑ ï¸ڈ [SERIES COUNT MISMATCH] series={series_number} "
                                f"instances={expected_instances} viewer_slices={viewer_count}"
                            )
                    except Exception:
                        pass

                    # Independence contract: every successful viewer switch should
                    # opportunistically retain full-volume data for reuse, regardless
                    # of BoostViewer proactive warmup setting state.
                    try:
                        if self._is_full_volume_cache_candidate(series_number, vtk_image_data, metadata):
                            self._full_cache_put(series_number, vtk_image_data, metadata)
                    except Exception:
                        pass

                    # Image Slice Booster is only needed in Fast mode.
                    # In Advanced (VTK + SimpleITK) it adds background I/O
                    # without helping render path, and can contend with UI.
                    try:
                        if self._is_fast_viewer_mode():
                            _instances = metadata.get('instances') or []
                            _inst_paths = [
                                str(inst.get('instance_path', ''))
                                for inst in _instances
                                if inst.get('instance_path')
                            ]
                            _center = 0
                            try:
                                _viewer = getattr(vtk_widget, 'image_viewer', None)
                                if _viewer is not None:
                                    _center = max(0, int(_viewer.GetSlice()))
                            except Exception:
                                pass
                            if _inst_paths:
                                _t0_bst = time.perf_counter()
                                self._image_slice_booster.set_active(
                                    series_number, _inst_paths, _center
                                )
                                _t_boost_ms = (time.perf_counter() - _t0_bst) * 1000
                        else:
                            if self._image_slice_booster.is_active:
                                self._image_slice_booster.clear()
                    except Exception:
                        pass
                    self._hide_spinner_for_widget(vtk_widget)
                    self._schedule_post_switch_followups(
                        vtk_widget=vtk_widget,
                        series_number=series_number,
                    )
                    logger.info(
                        "[PERF] series_switch_breakdown series=%s "
                        "switch_series=%.1fms reset_slider=%.1fms boost_set=%.1fms "
                        "corners=%.1fms refline=%.1fms psso_total=%.1fms",
                        series_number, _t_switch_ms, _t_reset_ms, _t_boost_ms,
                        _t_corners_ms, _t_refline_ms,
                        (time.perf_counter() - _t_psso) * 1000,
                    )
                    logger.info(
                        "[UX_VIEWER_INTERACTIVE] series=%s psso_total_ms=%.1f",
                        series_number, (time.perf_counter() - _t_psso) * 1000,
                    )
        
        except Exception as e:
            self.logger.error(f"Error in series switch: {e}", exc_info=True)

    def _schedule_post_switch_followups(self, vtk_widget, series_number: str) -> None:
        """Defer non-essential follow-up work until after the first frame is stable.

        The visible series switch, spinner hide, and Qt refit stay immediate.
        Lower-priority UI refresh work runs on the next Qt tick so the switch
        path does not pay for corner-text / reference-line / protected-series
        bookkeeping before the user sees the image.
        """

        def _run_followups() -> None:
            try:
                self._refresh_zeta_protected_series()
            except Exception:
                pass

            try:
                if hasattr(vtk_widget, 'image_viewer') and vtk_widget.image_viewer:
                    vtk_widget.image_viewer.update_corners_actors()
            except Exception:
                pass

            # Recompute reference lines for ALL viewers after series change.
            # Without this, drag-drop series switches leave stale/missing
            # reference lines because only viewport-click and slider-scroll
            # previously triggered recalculation.
            try:
                self.parent_widget.manage_reference_line()
            except Exception as _rl_err:
                logger.error(f"âڑ ï¸ڈ [RL] manage_reference_line error after switch: {_rl_err}")

        try:
            QTimer.singleShot(0, _run_followups)
        except Exception:
            try:
                _run_followups()
            except Exception:
                pass

        # â”€â”€ Look-ahead warmup: pre-cache adjacent series â”€â”€
        # After every successful series switch, schedule warmup for
        # the next N adjacent series so they're ready when the doctor
        # drags-and-drops them.  This remains deferred beyond the next tick
        # so it stays out of the first-visible-image path.
        try:
            _la_sn = str(series_number)
            QTimer.singleShot(100, lambda sn=_la_sn: self._enqueue_lookahead_warmup(sn))
        except Exception:
            pass

    def _clone_metadata_for_switch(self, metadata):
        """Low-overhead metadata clone for switch path.

        Deep-copying large `instances` arrays adds avoidable latency for warmed-up series.
        Clone only top-level + `series`; keep heavy nested arrays by reference.
        """
        if not isinstance(metadata, dict):
            return metadata
        try:
            cloned = dict(metadata)
            series = metadata.get('series')
            if isinstance(series, dict):
                cloned['series'] = dict(series)
            return cloned
        except Exception:
            return metadata

    def _perform_series_switch(self, vtk_widget, metadata, vtk_image_data, series_idx, slider):
        """Legacy method - redirects to optimized version"""
        self._perform_series_switch_optimized(vtk_widget, metadata, vtk_image_data, series_idx, slider)

    def _show_loading_spinner(self, message="Loading..."):
        """ظ†ظ…ط§غŒط´ spinner ط¯ط± viewport ظپط¹ظ„غŒ"""
        try:
            if hasattr(self.parent_widget, 'selected_widget') and self.parent_widget.selected_widget:
                spinner = getattr(self.parent_widget.selected_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.show_loading(message)
        except Exception:
            pass

    def _hide_loading_spinner(self):
        """ظ…ط®ظپغŒ ع©ط±ط¯ظ† spinner ط¯ط± viewport ظپط¹ظ„غŒ"""
        try:
            if hasattr(self.parent_widget, 'selected_widget') and self.parent_widget.selected_widget:
                spinner = getattr(self.parent_widget.selected_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.hide_loading()
        except Exception:
            pass

    def _hide_spinner_for_widget(self, vtk_widget):
        """Hide spinner for a specific viewport widget (safe no-op)."""
        try:
            if vtk_widget is None:
                return
            spinner = getattr(vtk_widget, 'viewport_spinner', None)
            if spinner:
                spinner.hide_loading()
        except Exception:
            pass

    def _get_viewer_id(self, vtk_widget):
        try:
            if vtk_widget is None:
                return None
            return getattr(vtk_widget, 'id_vtk_widget', None)
        except Exception:
            return None

    def _next_request_token(self, vtk_widget):
        viewer_id = self._get_viewer_id(vtk_widget)
        if viewer_id is None:
            return None
        token = int(self._viewer_request_token.get(viewer_id, 0)) + 1
        self._viewer_request_token[viewer_id] = token
        return token

    def _is_request_current(self, vtk_widget, expected_token):
        if expected_token is None:
            return True
        viewer_id = self._get_viewer_id(vtk_widget)
        if viewer_id is None:
            return True
        return int(self._viewer_request_token.get(viewer_id, 0)) == int(expected_token)

    def _arm_spinner_timeout(self, vtk_widget, timeout_ms=20000):
        """Auto-hide spinner after timeout to avoid indefinite UI busy state."""
        try:
            if vtk_widget is None:
                return
            QTimer.singleShot(timeout_ms, lambda: self._hide_spinner_for_widget(vtk_widget))
        except Exception:
            pass

    def _show_viewer_loading_all(self):
        """Show loading spinner on all viewers."""
        try:
            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                spinner = getattr(vtk_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.show_loading("Loading...")
        except Exception:
            pass

    def _hide_viewer_loading_all(self):
        """Hide loading spinner on all viewers."""
        try:
            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                spinner = getattr(vtk_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.hide_loading()
        except Exception:
            pass

    def _display_first_series_in_viewer(self):
        """Display the first available series in the primary viewer."""
        try:
            if not self.parent_widget.lst_thumbnails_data:
                return False
            series_number = str(self.parent_widget.lst_thumbnails_data[0]['metadata']['series']['series_number'])
            if self._display_first_series_in_primary_viewer(series_number):
                self._mark_first_series_displayed()
                return True
            return False
        except Exception:
            return False

    def _mark_first_series_displayed(self):
        """Finalize first-series display: hide overlays and notify Home UI."""
        if self._first_series_displayed:
            return
        self._first_series_displayed = True
        self._prime_visible_series_to_full_cache()
        self._refresh_zeta_protected_series()
        self._hide_viewer_loading_all()
        self.parent_widget._hide_init_overlay()
        # Warm up next series immediately so first drag-drop behaves like subsequent ones.
        try:
            if not self._first_use_prime_started:
                self._first_use_prime_started = True
                QTimer.singleShot(0, self._start_background_prefetch)
        except Exception:
            pass
        # â”€â”€ Warmup safety-net â”€â”€
        # _start_open_tab_warmup may have exhausted its retry budget while
        # waiting for this flag.  Reset the counter and give warmup a fresh
        # chance now that the first series is visible.
        try:
            self._open_warmup_retry_count = 0
            self._warmup_gather_running = False  # allow a new worker
            QTimer.singleShot(200, self._start_open_tab_warmup)
        except Exception:
            pass
        try:
            self.parent_widget.loading_complete.emit()
        except Exception:
            pass

    def _prime_visible_series_to_full_cache(self):
        """Prime currently visible non-preview series into deterministic full cache."""
        try:
            primed = []
            seen_idx = set()
            for node in list(self.lst_nodes_viewer or []):
                vtk_w = getattr(node, 'vtk_widget', None)
                if vtk_w is None:
                    continue
                idx = getattr(vtk_w, 'last_series_show', None)
                if idx is None:
                    continue
                try:
                    idx = int(idx)
                except Exception:
                    continue
                if idx in seen_idx:
                    continue
                if idx < 0 or idx >= len(self.parent_widget.lst_thumbnails_data):
                    continue
                seen_idx.add(idx)
                item = self.parent_widget.lst_thumbnails_data[idx]
                vtk_data = item.get('vtk_image_data')
                meta = item.get('metadata')
                sn = str(meta.get('series', {}).get('series_number', '')) if isinstance(meta, dict) else ''
                if not sn:
                    continue
                if not self._is_full_volume_cache_candidate(sn, vtk_data, meta):
                    continue
                self._full_cache_put(sn, vtk_data, meta)
                primed.append(sn)
            if primed:
                print(
                    f"âœ… [ZetaBoost][PRIME_FIRST] primed_visible_series={len(primed)} "
                    f"series={primed[:12]}"
                )
        except Exception:
            pass

    def _start_background_prefetch(self):
        """Start low-priority full-series prefetch for likely next interactions."""
        try:
            if self._zeta_slice_focus_mode:
                return
            if not self._boostviewer_enabled:
                return
            # Fast mode uses only local ±20 ImageSliceBooster — skip series prefetch
            if self._is_fast_viewer_mode():
                return
            if not self._tab_active:
                return
            if not hasattr(self.parent_widget, 'lst_thumbnails_data') or not self.parent_widget.lst_thumbnails_data:
                return

            # avoid multiple workers for same tab
            if self._prefetch_thread and self._prefetch_thread.is_alive():
                return

            # candidate list (numeric sort when possible)
            candidates = []
            for item in self.parent_widget.lst_thumbnails_data:
                try:
                    sn = str(item.get('metadata', {}).get('series', {}).get('series_number', ''))
                    if sn:
                        candidates.append(sn)
                except Exception:
                    continue

            if not candidates:
                return

            def _sort_key(v):
                try:
                    return (0, int(v))
                except Exception:
                    return (1, str(v))

            candidates = sorted(list(dict.fromkeys(candidates)), key=_sort_key)

            # Primary series (first thumbnail) is usually loaded by pipeline/lazy-first;
            # keep warmup focused on *next* likely interactions.
            primary_series = None
            try:
                if self.parent_widget.lst_thumbnails_data:
                    primary_series = str(
                        self.parent_widget.lst_thumbnails_data[0].get('metadata', {}).get('series', {}).get('series_number', '')
                    )
            except Exception:
                primary_series = None

            # first visible/selected series should already be warm; skip it for prefetch
            selected_series = None
            try:
                if self.selected_widget is not None:
                    idx = getattr(self.selected_widget, 'last_series_show', None)
                    if idx is not None and 0 <= int(idx) < len(self.parent_widget.lst_thumbnails_data):
                        selected_series = str(
                            self.parent_widget.lst_thumbnails_data[int(idx)].get('metadata', {}).get('series', {}).get('series_number', '')
                        )
            except Exception:
                selected_series = None

            queue = [
                sn for sn in candidates
                if sn
                and sn != selected_series
                and sn != primary_series
                and sn not in self._zeta_boost_failed_series
                and (not self._is_series_in_memory_only(sn))
            ][: self._prefetch_max_series]
            queue = [sn for sn in queue if self._is_series_header_consistent_for_warmup(sn)]
            # Guard prefetch against very large stacks to keep startup stable.
            if self._prefetch_skip_slices_threshold > 0:
                _slice_counts = {sn: self._get_series_expected_slices(sn) for sn in queue}
                queue = [
                    sn for sn in queue
                    if _slice_counts.get(sn, 0) == 0
                    or _slice_counts.get(sn, 0) <= self._prefetch_skip_slices_threshold
                ]
            if not queue:
                return

            study_path = self._get_correct_study_path()
            if not study_path:
                return

            # Delegate low-priority preloading to ZetaBoost background lane.
            self.zeta_boost.enqueue_many_background(queue)
            logger.debug(f"âڑ، [PREFETCH] Started for {len(queue)} series: {queue}")
        except Exception as e:
            self.logger.debug(f"Error starting background prefetch: {e}")



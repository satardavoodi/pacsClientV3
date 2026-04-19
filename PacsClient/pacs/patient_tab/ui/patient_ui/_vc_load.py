"""
Series load and download-integration mixin for ViewerController.
load_single_series_on_demand, apply_loaded_series_data, download warmup subprocess, DM notify, load_series_on_demand, initial load helpers.
"""
from __future__ import annotations
import os
import threading
import time
import traceback
import json
import gc
import asyncio
from pathlib import Path
from collections import deque
from PySide6.QtCore import Qt, QTimer, QThread, QMetaObject
from PySide6.QtWidgets import QApplication, QProgressDialog
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
from PacsClient.pacs.patient_tab.utils import NodeViewer
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing, new_correlation_id, set_log_context
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, CallerTypes
from modules.download_manager.core.enums import DownloadPriority
from modules.zeta_boost.warmup_subprocess import (
    WarmupSubprocessManager, WarmupRequest, WarmupResult, result_to_vtk,
)
from modules.viewer.fast.lazy_volume_registry import get_loader as get_lazy_loader
from modules.viewer.viewer_backend_config import BACKEND_VTK, BACKEND_PYDICOM, load_viewer_backend, resolve_viewer_backend
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget, grow_vtk_inplace
from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview
from modules.zeta_boost import ZetaBoostEngine, ImageSliceBooster
from modules.viewer.pipeline import PipelineOrchestrator, PipelineState, LoadCoordinator, PreviewEngine
from PacsClient.utils.config import SOCKET_CONFIG_PATH as _SOCKET_CONFIG_PATH
from pathlib import Path as _Path
import logging as _logging
import logging

logger = logging.getLogger(__name__)

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))
GRID_CONFIG_PATH = _Path(_SOCKET_CONFIG_PATH) / 'modality_grid.json'


class _VCLoadMixin:
    """Auto-split mixin — see patient_widget_viewer_controller.py for history."""

    def _viewer_has_series_fully_visible(self, series_number: str, expected_count: int = 0) -> bool:
        """Return True when any viewer already shows the requested series at count.

        This is used to suppress redundant post-completion reloads after the
        progressive final-grow path has already caught a viewer up to disk.
        """
        sn = str(series_number)
        try:
            expected = int(expected_count or 0)
        except Exception:
            expected = 0

        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, 'vtk_widget', None)
            if vtk_w is None:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, 'metadata', {})
                    .get('series', {}).get('series_number', '')
                )
            except Exception:
                viewer_sn = ''
            if viewer_sn != sn:
                continue
            try:
                visible_count = int(vtk_w.get_count_of_slices() or 0)
            except Exception:
                visible_count = 0
            if expected <= 0:
                if visible_count > 0:
                    return True
            elif visible_count >= expected:
                return True
        return False

    def _is_viewer_fast_interacting(self, vtk_widget) -> bool:
        """True when a target viewer is actively wheel/stack interacting."""
        try:
            if vtk_widget is None:
                return False
            if bool(getattr(vtk_widget, '_in_fast_slice_interaction', False)):
                return True
            last_scroll_ms = getattr(vtk_widget, '_last_scroll_event_ms', None)
            if last_scroll_ms is None:
                return False
            idle_window_ms = max(
                60.0,
                float(getattr(vtk_widget, '_fast_interaction_idle_window_ms', 220.0) or 220.0),
            )
            return max(0.0, now_ms() - float(last_scroll_ms)) <= idle_window_ms
        except Exception:
            return False

    def _schedule_deferred_viewer_refresh(
        self,
        *,
        series_number,
        vtk_widget,
        metadata,
        vtk_image_data,
        series_idx,
        slider,
        allow_paired: bool,
        expected_token=None,
        attempt: int = 1,
    ):
        """Re-try a refresh after fast interaction settles, with a bounded retry budget."""
        try:
            delay_ms = max(
                80,
                min(
                    250,
                    int(getattr(vtk_widget, '_fast_interaction_idle_window_ms', 220) or 220),
                ),
            )
        except Exception:
            delay_ms = 180

        def _retry():
            try:
                if expected_token is not None and not self._is_request_current(vtk_widget, expected_token):
                    logger.debug(f"[APPLY STALE] deferred refresh skipped series={series_number} viewer={getattr(vtk_widget, 'id_vtk_widget', '?')}")
                    return
                if self._is_viewer_fast_interacting(vtk_widget) and attempt < 6:
                    self._schedule_deferred_viewer_refresh(
                        series_number=series_number,
                        vtk_widget=vtk_widget,
                        metadata=metadata,
                        vtk_image_data=vtk_image_data,
                        series_idx=series_idx,
                        slider=slider,
                        allow_paired=allow_paired,
                        expected_token=expected_token,
                        attempt=attempt + 1,
                    )
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
            except Exception:
                pass

        logger.debug(
            "[APPLY DEFER] series=%s viewer=%s attempt=%d delay_ms=%d",
            series_number,
            getattr(vtk_widget, 'id_vtk_widget', '?'),
            int(attempt),
            int(delay_ms),
        )
        QTimer.singleShot(int(delay_ms), _retry)

    def _load_single_series_on_demand(self, series_number: int, study_path: str = None,
                                      target_vtk_widget: VTKWidget = None,
                                      allow_paired: bool = True,
                                      expected_token=None,
                                      viewer_backend=None,
                                      force_reload: bool = False) -> bool:
        """
        Load a single series with correct path resolution
        """
        import time
        from pathlib import Path

        try:
            _start = time.perf_counter()
            t_load_total = now_ms()

            # âœ… FIX: Use provided study_path or correctly determine it
            if study_path is None:
                # Try parent widget's import folder first
                if self.parent_widget.import_folder_path and Path(self.parent_widget.import_folder_path).exists():
                    # Ensure we're using the study root folder, not a series subfolder
                    study_path_obj = Path(self.parent_widget.import_folder_path)
                    # If current path points to a series folder (has DICOM parent), go up
                    if (study_path_obj / str(series_number)).exists():
                        pass  # Already at study level
                    else:
                        # Check if current path is inside a series folder
                        parent = study_path_obj.parent
                        if parent.exists() and (parent / str(series_number)).exists():
                            study_path_obj = parent
                    study_path = str(study_path_obj)
                else:
                    logger.debug(f"â‌Œ No valid study path found")
                    return False

            logger.debug(f"ًں“‚ [LOAD] Loading series {series_number} from {study_path} (thread={threading.current_thread().name})")
            effective_viewer_backend = (
                viewer_backend
                or self._get_requested_viewer_backend()
                or BACKEND_VTK
            )
            self.logger.info(
                "viewer-backend stage=load_request series=%s backend=%s force_reload=%s",
                str(series_number),
                str(effective_viewer_backend),
                bool(force_reload),
                extra={
                    "component": "viewer",
                    "function": "ViewerController._load_single_series_on_demand",
                    "stage": "load_request",
                },
            )

            series_key = str(series_number)

            # Fast no-op: same series already displayed in target viewport.
            # Prevents duplicate full ITK pipeline when a second request arrives
            # while the first switch has already applied.
            try:
                if (not force_reload) and target_vtk_widget is not None and getattr(target_vtk_widget, 'image_viewer', None) is not None:
                    shown_series = str(
                        getattr(target_vtk_widget.image_viewer, 'metadata', {}).get('series', {}).get('series_number', '')
                    )
                    if shown_series and shown_series == str(series_number):
                        if int(target_vtk_widget.get_count_of_slices() or 0) > 0:
                            logger.debug(f"âڈ­ï¸ڈ [LOAD SKIP] same series already visible series={series_number}")
                            return True
            except Exception:
                pass

            # Bail out early if tab was deactivated while queued (e.g. user pressed F5).
            # Allow explicit user-driven loads even if tab_active flag is stale.
            if not self._tab_active and not self._interactive_load_in_progress:
                logger.debug(f"âڈ­ï¸ڈ [LOAD SKIP] tab inactive for series {series_number}")
                return False

            if force_reload:
                try:
                    self.zeta_boost.invalidate_series(series_key, clear_disk=True)
                except Exception:
                    pass

            # Deterministic full-series cache before any I/O work.
            _cache_probe_t = time.perf_counter()
            cached_full = None if force_reload else self._full_cache_get(str(series_number))
            _cache_probe_ms = (time.perf_counter() - _cache_probe_t) * 1000
            self.logger.info(
                "viewer-data stage=cache_lookup_fullcache duration_ms=%.2f hit=%s",
                _cache_probe_ms,
                str(cached_full is not None),
                extra={"component": "viewer", "function": "ViewerController._load_single_series_on_demand", "stage": "cache_lookup"},
            )
            if cached_full is not None:
                cached_vtk, cached_meta = cached_full[0], cached_full[1]
                if cached_vtk is not None and isinstance(cached_meta, dict):
                    if not self._tab_active:
                        return False
                    _apply_t = time.perf_counter()
                    self._apply_loaded_series_data_threadsafe(
                        series_number, cached_vtk, cached_meta,
                        self.parent_widget.metadata_fixed.get('patient_pk', None),
                        self.parent_widget.metadata_fixed.get('study_pk', None),
                        refresh_viewer=(target_vtk_widget is not None),
                        target_viewer_id=getattr(target_vtk_widget, 'id_vtk_widget', None),
                        allow_paired=allow_paired,
                        expected_token=expected_token,
                    )
                    _apply_ms = (time.perf_counter() - _apply_t) * 1000
                    logger.debug(f"âڑ، [CACHE HIT] full-series cache hit for {series_number} probe={_cache_probe_ms:.0f}ms apply={_apply_ms:.0f}ms")
                    return True
            elif _cache_probe_ms > 50:
                logger.debug(f"ًں”چ [CACHE MISS] series={series_number} probe took {_cache_probe_ms:.0f}ms")

            # Fast exit only when a full-volume payload is already loaded.
            # Preview-only payloads (z=1 with preview flag) must continue to full load,
            # otherwise heavy series can appear to never load.
            if not force_reload:
                try:
                    existing_vtk, existing_meta, _ = self._get_series_by_number_fast(str(series_number))
                    if existing_meta and existing_vtk is not None and self._is_full_volume_cache_candidate(str(series_number), existing_vtk, existing_meta):
                        return True
                except Exception:
                    pass

            # INTERACTIVE DEDUP: prevent two identical interactive drag-drops
            # from loading the same series twice.  ZetaBoost warmup is fully
            # independent (see _zeta_boost_load_series) and never participates
            # in this lock â€” the viewer never waits for warmup.
            load_event = None
            is_owner = False
            with self._series_load_lock:
                if series_key in self._loading_series_numbers:
                    load_event = self._series_load_events.get(series_key)
                    logger.debug(f"âڈ³ [LOAD] series={series_key} already loading interactively (thread={threading.current_thread().name})")
                else:
                    self._loading_series_numbers.add(series_key)
                    load_event = threading.Event()
                    self._series_load_events[series_key] = load_event
                    is_owner = True
                    logger.debug(f"ًں”‘ [LOAD] series={series_key} took ownership (thread={threading.current_thread().name})")

            if not is_owner:
                # âڑ، CRITICAL: NEVER block the Qt main thread on this wait.
                # load_series_immediately / load_first_series_only are called
                # from QTimer.singleShot callbacks (main thread).  If warmup
                # currently owns the lock the 10-second wait would freeze the
                # entire UI.  Return False so the caller can schedule a retry.
                if threading.current_thread() is threading.main_thread():
                    print(f"âڑ ï¸ڈ [LOAD] Main-thread call for series={series_key} is already in-flight "
                          f"(owned by warmup/background) â€” returning False for QTimer retry")
                    return False
                # Background thread: legitimate dedup wait.
                _wait_t = time.perf_counter()
                if load_event is not None:
                    load_event.wait(timeout=10.0)
                _wait_ms = (time.perf_counter() - _wait_t) * 1000
                logger.debug(f"âڈ³ [LOAD] series={series_key} interactive wait done {_wait_ms:.0f}ms (thread={threading.current_thread().name})")

                if not force_reload:
                    existing_vtk, existing_meta, _ = self._get_series_by_number_fast(series_key)
                    if existing_meta and existing_vtk is not None and self._is_full_volume_cache_candidate(series_key, existing_vtk, existing_meta):
                        return True

                    cached_full_after_wait = self._full_cache_get(series_key)
                    if cached_full_after_wait is not None:
                        cached_vtk, cached_meta = cached_full_after_wait[0], cached_full_after_wait[1]
                        if cached_vtk is not None and isinstance(cached_meta, dict):
                            if not self._tab_active:
                                return False
                            self._apply_loaded_series_data_threadsafe(
                                series_number, cached_vtk, cached_meta,
                                self.parent_widget.metadata_fixed.get('patient_pk', None),
                                self.parent_widget.metadata_fixed.get('study_pk', None),
                                refresh_viewer=(target_vtk_widget is not None),
                                target_viewer_id=getattr(target_vtk_widget, 'id_vtk_widget', None),
                                allow_paired=allow_paired,
                                expected_token=expected_token,
                            )
                            return True

                # Previous interactive loader finished without result â€” take over.
                with self._series_load_lock:
                    if series_key not in self._loading_series_numbers:
                        self._loading_series_numbers.add(series_key)
                        load_event = threading.Event()
                        self._series_load_events[series_key] = load_event
                        is_owner = True

                if not is_owner:
                    if not force_reload:
                        existing_vtk, existing_meta, _ = self._get_series_by_number_fast(series_key)
                        if existing_meta and existing_vtk is not None and self._is_full_volume_cache_candidate(series_key, existing_vtk, existing_meta):
                            return True
                    return False

            # Do NOT hard-fail on study_path/series_number existence.
            # Series folders may be UID-named; load_single_series_by_number()
            # has DB/alternative resolution logic.
            estimated_file_count = 0
            try:
                tentative_folder = Path(study_path) / str(series_number)
                if tentative_folder.exists() and tentative_folder.is_dir():
                    estimated_file_count = len(list(tentative_folder.glob("*.dcm"))) + len(list(tentative_folder.glob("*.DCM")))
            except Exception:
                estimated_file_count = 0

            max_itk_threads, max_pydicom_workers = self._get_interactive_load_limits(effective_viewer_backend)
            _gate_wait_start = time.perf_counter()
            self.logger.info("[UX_SERIES_LOAD_START] series=%s backend=%s", series_key, effective_viewer_backend)
            _use_serialized_gate = self._requires_serialized_interactive_load(effective_viewer_backend)
            _gate_wait_ms = 0.0
            if _use_serialized_gate:
                self._interactive_full_load_semaphore.acquire()
                _gate_wait_ms = (time.perf_counter() - _gate_wait_start) * 1000.0
            try:
                if target_vtk_widget is not None and not self._is_request_current(target_vtk_widget, expected_token):
                    return False

                # Load full series with correct path (preview path disabled by design).
                # Only heavyweight VTK/SimpleITK paths are serialized; FAST lazy/
                # metadata-first backends bypass the gate to preserve first-image speed.
                _dicom_t = time.perf_counter()
                result = load_single_series_by_number(
                    study_path=study_path,  # Pass correct study path, not series path
                    series_number=series_number,
                    patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                    study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
                    max_itk_threads=max_itk_threads,
                    max_pydicom_workers=max_pydicom_workers,
                    viewer_backend=effective_viewer_backend,
                    allow_lazy_backend=(effective_viewer_backend != BACKEND_VTK),
                )
            finally:
                if _use_serialized_gate:
                    self._interactive_full_load_semaphore.release()
            _dicom_ms = (time.perf_counter() - _dicom_t) * 1000
            logger.debug(f"ًں“ٹ [LOAD] DICOM+ITK for series={series_number} took {_dicom_ms:.0f}ms files~={estimated_file_count} (thread={threading.current_thread().name})")
            self.logger.info(
                "viewer-data stage=itk_pipeline_total duration_ms=%.2f files=%d gate_wait_ms=%.2f itk_threads=%d pydicom_workers=%d serialized_gate=%s",
                _dicom_ms,
                estimated_file_count,
                _gate_wait_ms,
                int(max_itk_threads),
                int(max_pydicom_workers),
                str(_use_serialized_gate),
                extra={"component": "viewer", "function": "ViewerController._load_single_series_on_demand", "stage": "itk_pipeline"},
            )

            if result is None:
                logger.debug(f"â‌Œ [LOAD FAIL] series={series_number} loader returned None")
                with self._series_load_lock:
                    evt = self._series_load_events.pop(series_key, None)
                    self._loading_series_numbers.discard(series_key)
                if evt is not None:
                    evt.set()
                return False

            # Process results; generator may be empty on path miss.
            loaded_any = False
            _last_vtk_data = None   # v2.2.5.2: keep ref for immediate cache put
            _last_meta = None       # v2.2.5.2: keep ref for immediate cache put
            for item in result:
                if not self._tab_active:
                    # Tab was deactivated while full load was in progress.
                    # Preserve loaded payload in full cache so re-activation can
                    # display immediately without re-running the ITK pipeline.
                    try:
                        _inactive_vtk, _inactive_meta, _ = item
                        if _inactive_vtk is not None and isinstance(_inactive_meta, dict):
                            self._full_cache_put(series_key, _inactive_vtk, _inactive_meta)
                    except Exception:
                        pass
                    logger.debug(f"âڈ­ï¸ڈ [LOAD SKIP] tab inactive during apply for series {series_number}")
                    return False
                if target_vtk_widget is not None and not self._is_request_current(target_vtk_widget, expected_token):
                    logger.debug(f"âڈ­ï¸ڈ [LOAD STALE] full series={series_number} ignored")
                    return False
                vtk_image_data, metadata, (patient_pk, study_pk) = item

                # [H7-P4] Series bind snapshot — 7-field comparison at metadata load time
                try:
                    _h7_sn = str(series_number)
                    _h7_instances = metadata.get('instances', []) if metadata else []
                    _h7_meta_count = len(_h7_instances)
                    _h7_server_count = 0
                    try:
                        _h7_ssi = getattr(self.parent_widget, '_server_series_info', None)
                        if _h7_ssi:
                            for _si in (_h7_ssi if isinstance(_h7_ssi, list) else _h7_ssi.values()):
                                if str(_si.get('series_number', '')) == _h7_sn:
                                    _h7_server_count = int(_si.get('image_count', 0))
                                    break
                    except Exception:
                        pass
                    _h7_disk_count = 0
                    try:
                        _h7_sp = Path(study_path) / _h7_sn
                        if _h7_sp.is_dir():
                            _h7_disk_count = sum(1 for f in os.scandir(str(_h7_sp)) if f.name.lower().endswith('.dcm'))
                    except Exception:
                        pass
                    logger.info(
                        "[H7-P4] series=%s server_image_count=%d disk_file_count=%d "
                        "metadata_instance_count=%d active_backend=%s",
                        _h7_sn, _h7_server_count, _h7_disk_count, _h7_meta_count,
                        effective_viewer_backend,
                    )
                except Exception:
                    pass

                _last_vtk_data = vtk_image_data
                _last_meta = metadata
                self._apply_loaded_series_data_threadsafe(
                    series_number, vtk_image_data, metadata, patient_pk, study_pk,
                    refresh_viewer=(target_vtk_widget is not None),
                    target_viewer_id=getattr(target_vtk_widget, 'id_vtk_widget', None),
                    allow_paired=allow_paired,
                    expected_token=expected_token,
                )
                loaded_any = True

            if not loaded_any:
                logger.debug(f"â‌Œ [LOAD FAIL] series={series_number} loader produced no items")
                with self._series_load_lock:
                    evt = self._series_load_events.pop(series_key, None)
                    self._loading_series_numbers.discard(series_key)
                if evt is not None:
                    evt.set()
                return False

            _elapsed = time.perf_counter() - _start
            logger.debug(f"âœ… [LOAD] Series {series_number} loaded in {_elapsed:.3f}s")
            log_stage_timing(
                self.logger,
                component="viewer",
                function="ViewerController._load_single_series_on_demand",
                stage="load_single_series_total",
                start_ms=t_load_total,
                series=str(series_number),
            )
            self._prefetch_loaded.add(series_key)
            # v2.2.5.2: Populate full-series cache DIRECTLY from the
            # loaded data instead of reading back from the UI list
            # (fire-and-forget _apply hasn't run on UI thread yet).
            # This ensures the waiting thread finds the data immediately.
            try:
                if _last_vtk_data is not None and isinstance(_last_meta, dict):
                    self._full_cache_put(series_key, _last_vtk_data, _last_meta)
                    logger.debug(f"\u2705 [CACHE PUT] series={series_key} cached directly from loader")
                else:
                    latest_vtk, latest_meta, _ = self._get_series_by_number_fast(series_key)
                    if latest_vtk is not None and isinstance(latest_meta, dict):
                        self._full_cache_put(series_key, latest_vtk, latest_meta)
            except Exception:
                pass
            with self._series_load_lock:
                evt = self._series_load_events.pop(series_key, None)
                self._loading_series_numbers.discard(series_key)
            if evt is not None:
                evt.set()
            return True

        except Exception as e:
            logger.error(f"â‌Œ [LOAD] Error loading series {series_number}: {e}")
            import traceback
            traceback.print_exc()
            with self._series_load_lock:
                evt = self._series_load_events.pop(str(series_number), None)
                self._loading_series_numbers.discard(str(series_number))
            if evt is not None:
                evt.set()
            return False

    def _apply_loaded_series_data(self, series_number, vtk_image_data, metadata, patient_pk, study_pk,
                                  refresh_viewer=False, target_viewer_id=None, allow_paired: bool = True,
                                  expected_token=None):
        try:
            _t_apply_start = time.perf_counter()
            dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
            incoming_count = 0
            try:
                incoming_count = len((metadata or {}).get('instances', []) or [])
            except Exception:
                incoming_count = 0
            if incoming_count <= 0:
                try:
                    incoming_count = int(dims[2]) if dims and len(dims) > 2 else 0
                except Exception:
                    incoming_count = 0
            logger.debug(f"ًں”„ [APPLY] series={series_number} refresh={refresh_viewer} dims={dims}")

            # Stale-request guard: if this apply was tied to a specific viewer request
            # token and that token is no longer current, skip list/index mutation.
            if refresh_viewer and (target_viewer_id is not None) and (expected_token is not None):
                target_widget = None
                for node in self.lst_nodes_viewer or []:
                    vtk_w = getattr(node, 'vtk_widget', None)
                    if vtk_w is not None and getattr(vtk_w, 'id_vtk_widget', None) == target_viewer_id:
                        target_widget = vtk_w
                        break
                if target_widget is not None and (not self._is_request_current(target_widget, expected_token)):
                    logger.debug(f"âڈ­ï¸ڈ [APPLY STALE] series={series_number} token no longer current, skipping mutation")
                    return

            # Populate metadata_fixed if needed
            if not self.parent_widget.metadata_fixed or len(self.parent_widget.metadata_fixed) < 3:
                if metadata and 'instances' in metadata and metadata['instances']:
                    first_instance_path = metadata['instances'][0].get('instance_path')
                    if first_instance_path and Path(first_instance_path).exists():
                        from PacsClient.pacs.patient_tab.utils.utils import get_meta_fixed
                        self.parent_widget.metadata_fixed = get_meta_fixed(first_instance_path)
                        if patient_pk:
                            self.parent_widget.metadata_fixed['patient_pk'] = patient_pk
                        if study_pk:
                            self.parent_widget.metadata_fixed['study_pk'] = study_pk

            file_path = metadata['series'].get('thumbnail_path', '')
            _t0_rsd = time.perf_counter()
            series_idx = self.parent_widget.replace_series_data(
                series_number=series_number,
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                file_path=file_path,
                allow_append_if_missing=True,
            )
            _t_rsd_ms = (time.perf_counter() - _t0_rsd) * 1000
            logger.debug(f"ًں”„ [APPLY] series={series_number} â†’ replace_series_data returned idx={series_idx}")

            # Update study path if needed — but ONLY if the new path actually
            # exists on disk.  Metadata may carry a stale legacy "source\"
            # path from the DB which no longer exists after migration to
            # user_data/patients/dicom/.  Overwriting import_folder_path with
            # a non-existent path breaks all subsequent series loads.
            if metadata.get('series', {}).get('series_path'):
                correct_path = Path(metadata['series']['series_path']).parent
                if correct_path.exists() and str(correct_path) != self.parent_widget.import_folder_path:
                    self.parent_widget.import_folder_path = str(correct_path)
                    logger.debug(f"   📄 Updated study path to: {correct_path}")
                elif not correct_path.exists():
                    logger.debug(f"   ❌ Ignored stale series_path from metadata: {correct_path}")

            if refresh_viewer and series_idx >= 0:
                # Update ALL viewers currently showing this series (not just selected)
                for vi, node_viewer in enumerate(self.lst_nodes_viewer or []):
                    vtk_w = getattr(node_viewer, 'vtk_widget', None)
                    if vtk_w is None:
                        continue
                    if target_viewer_id is not None and getattr(vtk_w, 'id_vtk_widget', None) != target_viewer_id:
                        continue
                    if expected_token is not None and not self._is_request_current(vtk_w, expected_token):
                        logger.debug(f"   âڈ­ï¸ڈ [APPLY STALE] viewer[{vi}] series={series_number} skipped")
                        continue
                    # last_series_show stores thumbnail *index*, not series number
                    current_idx = getattr(vtk_w, 'last_series_show', None)
                    logger.debug(f"   ًں”ژ viewer[{vi}] last_series_show={current_idx} vs series_idx={series_idx}")
                    if current_idx is not None and current_idx == series_idx:
                        try:
                            slider = getattr(node_viewer, 'slider', None)
                            viewer_meta = getattr(getattr(vtk_w, 'image_viewer', None), 'metadata', {}) or {}
                            viewer_series = str(viewer_meta.get('series', {}).get('series_number', '') or '')
                            viewer_backend = str(getattr(vtk_w, '_active_backend', BACKEND_VTK) or BACKEND_VTK)
                            incoming_is_preview = bool((metadata or {}).get('preview_only', False))
                            viewer_is_preview = bool(viewer_meta.get('preview_only', False))
                            if (
                                viewer_series == str(series_number)
                                and viewer_backend != BACKEND_VTK
                                and not incoming_is_preview
                                and not viewer_is_preview
                                and (
                                    bool(getattr(vtk_w, '_progressive_mode', False))
                                    or str(series_number) in getattr(self, '_progressive_series', {})
                                )
                            ):
                                self._update_vtk_slice_range(vtk_w, node_viewer, incoming_count, slider=slider)
                                self._refresh_and_sync_metadata(series_number, incoming_count)
                                self._hide_spinner_for_widget(vtk_w)
                                logger.info(
                                    "[PERF] apply_loaded series=%s replace_series_data=%.1fms "
                                    "perform_switch=0.0ms apply_total=%.1fms action=inplace_fast_sync",
                                    series_number,
                                    _t_rsd_ms,
                                    (time.perf_counter() - _t_apply_start) * 1000,
                                )
                                logger.debug(
                                    "[APPLY] same-series FAST sync only series=%s viewer=%s "
                                    "incoming_count=%s progressive=%s",
                                    series_number,
                                    getattr(vtk_w, 'id_vtk_widget', '?'),
                                    incoming_count,
                                    bool(getattr(vtk_w, '_progressive_mode', False)),
                                )
                                continue
                            logger.debug(f"   âœ… Refreshing viewer[{vi}] with full data (dims={dims})")
                            if self._is_viewer_fast_interacting(vtk_w):
                                self._schedule_deferred_viewer_refresh(
                                    series_number=series_number,
                                    vtk_widget=vtk_w,
                                    metadata=metadata,
                                    vtk_image_data=vtk_image_data,
                                    series_idx=series_idx,
                                    slider=slider,
                                    allow_paired=allow_paired,
                                    expected_token=expected_token,
                                )
                                continue
                            _t0_pso = time.perf_counter()
                            self._perform_series_switch_optimized(
                                vtk_w, metadata, vtk_image_data, series_idx, slider,
                                allow_paired=allow_paired,
                                expected_token=expected_token,
                            )
                            _t_pso_ms = (time.perf_counter() - _t0_pso) * 1000
                            logger.info(
                                "[PERF] apply_loaded series=%s replace_series_data=%.1fms "
                                "perform_switch=%.1fms apply_total=%.1fms",
                                series_number, _t_rsd_ms, _t_pso_ms,
                                (time.perf_counter() - _t_apply_start) * 1000,
                            )
                        except Exception:
                            pass

        except Exception as e:
            self.logger.debug(f"Error applying loaded series data: {e}")

    def _queue_on_ui_thread(self, func):
        """Run callable on the Qt UI thread, even when called from worker threads."""
        try:
            self._ui_invoker.invoke(func)
        except Exception:
            # Ultimate fallback
            try:
                QTimer.singleShot(0, func)
            except Exception:
                pass

    def _is_on_ui_thread(self) -> bool:
        try:
            app = QApplication.instance()
            if app is None:
                return False
            return QThread.currentThread() == app.thread()
        except Exception:
            return False

    def _apply_loaded_series_data_threadsafe(self, *args, **kwargs):
        """Apply loaded data on UI thread â€” fire-and-forget from worker threads.

        Previous implementation blocked the worker with done.wait(15s), causing
        cascading stalls when multiple series complete during downloads.
        Now we queue to UI thread and return immediately.
        """
        if self._is_on_ui_thread():
            self._apply_loaded_series_data(*args, **kwargs)
            return

        # Fire-and-forget: queue on UI thread without blocking the worker.
        def _ui_apply():
            try:
                self._apply_loaded_series_data(*args, **kwargs)
            except Exception as e:
                logger.error(f"âڑ ï¸ڈ [UI APPLY] error: {e}")

        self._queue_on_ui_thread(_ui_apply)

    def _set_zeta_external_interactive_busy(self, busy: bool, reason: str = ""):
        """Pause/resume warmup/background lane during user-driven loads."""
        try:
            new_state = bool(busy)
            if self._zeta_external_busy_last is not None and bool(self._zeta_external_busy_last) == new_state:
                return
            self._zeta_external_busy_last = new_state
            self.zeta_boost.set_external_interactive_busy(new_state)
            if reason:
                logger.debug(f"â„¹ï¸ڈ [ZetaBoost][INTERACTIVE_BUSY] busy={new_state} reason={reason}")
        except Exception:
            pass

    def notify_viewer_interaction(self, reason: str = "viewer_input"):
        """Viewer-first scheduling hook (reversible via env).

        During active user interaction (scroll/series switch), temporarily pause
        warmup/background lanes to reduce UI contention on weaker hardware.
        """
        try:
            self._last_user_interaction_ts = time.time()
            if not self._plan_a_viewer_first:
                return

            self._set_zeta_external_interactive_busy(True, reason=reason)
            self._interaction_release_token += 1
            token = self._interaction_release_token

            def _release_if_latest():
                try:
                    if token != self._interaction_release_token:
                        return
                    idle_ms = (time.time() - self._last_user_interaction_ts) * 1000.0
                    if idle_ms < self._viewer_interaction_pause_ms:
                        QTimer.singleShot(max(1, int(self._viewer_interaction_pause_ms - idle_ms)), _release_if_latest)
                        return
                    self._set_zeta_external_interactive_busy(False, reason="viewer_idle")
                except Exception:
                    pass

            QTimer.singleShot(max(1, self._viewer_interaction_pause_ms), _release_if_latest)
        except Exception:
            pass

    def _global_downloads_active(self) -> bool:
        """Best-effort check for any active download in the app."""
        try:
            return int(getattr(ZetaBoostEngine, '_global_active_download_count', 0) or 0) > 0
        except Exception:
            return False

    def _is_user_interaction_hot(self) -> bool:
        """True when the user has interacted recently (scroll/drag/switch)."""
        try:
            idle_s = max(0.0, time.time() - float(self._last_user_interaction_ts or 0.0))
            return idle_s < float(self._open_warmup_min_idle_sec)
        except Exception:
            return False

    def _get_interactive_load_limits(self, viewer_backend: str) -> tuple[int, int]:
        """
        Choose conservative loader limits while the user is actively interacting.

        For the Advanced VTK/SimpleITK path, background MR/CT series loads can
        still starve software VTK rendering if they overlap scrolling. During
        hot interaction we cut both ITK and pydicom worker counts to 1.
        """
        backend = str(viewer_backend or BACKEND_VTK)
        if backend != BACKEND_VTK:
            return 2, 2
        if self._is_user_interaction_hot():
            return 1, 1
        return 2, 2

    # â”€â”€ Per-series download warmup (controlled Mode B caching) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _enqueue_download_warmup(self, series_number: str, force: bool = False):
        """Queue a completed series for background warmup during active download.

        v2.2.3.2.3: Routes to subprocess (GIL-free) by default.
        Set AIPACS_DL_WARMUP_SUBPROCESS=0 to fall back to in-process thread.

        Strict controls:
        - Max ``_DL_WARMUP_MAX_CACHED`` series cached during a single download session.
        - Skips large series (> ``_DL_WARMUP_MAX_SLICES``).
        - Skips already-cached series.
        """
        try:
            # Keep slice-focus default behavior unless explicitly forced by
            # look-ahead logic for adjacent series.
            if self._zeta_slice_focus_mode and not bool(force):
                return
            if not self._tab_active or not self._boostviewer_enabled:
                return
            # Fast mode uses only local ±20 ImageSliceBooster — skip series warmup
            if self._is_fast_viewer_mode():
                return
            sn = str(series_number)
            with self._dl_warmup_lock:
                pending_count = 0
                if self._dl_warmup_use_subprocess and self._warmup_subprocess_mgr is not None:
                    pending_count = int(self._warmup_subprocess_mgr.pending_count or 0)
                elif not self._dl_warmup_use_subprocess:
                    pending_count = len(self._dl_warmup_queue)

                if (self._dl_warmup_cached_count + pending_count) >= self._DL_WARMUP_MAX_CACHED:
                    logger.debug(f"[DL_WARMUP] Skip series={sn} - max cached ({self._DL_WARMUP_MAX_CACHED}) reached")
                    return
                if sn in self._dl_warmup_enqueued:
                    return
                # Skip currently displayed series (already loaded interactively).
                try:
                    if self.parent_widget.lst_thumbnails_data:
                        primary_sn = str(
                            self.parent_widget.lst_thumbnails_data[0]
                            .get('metadata', {}).get('series', {}).get('series_number', '')
                        )
                        if sn == primary_sn:
                            return
                except Exception:
                    pass
                if self.zeta_boost.has_in_memory(sn):
                    return
                self._dl_warmup_enqueued.add(sn)

            # â”€â”€ v2.2.3.2.3: Subprocess path (default) â”€â”€
            if self._dl_warmup_use_subprocess:
                accepted = self._enqueue_warmup_subprocess(sn)
                if not accepted:
                    with self._dl_warmup_lock:
                        self._dl_warmup_enqueued.discard(sn)
                return

            # â”€â”€ Legacy thread path (fallback) â”€â”€
            with self._dl_warmup_lock:
                self._dl_warmup_queue.append(sn)
            logger.debug(f"[DL_WARMUP] Queued series={sn} (pending={len(self._dl_warmup_queue)})")
            if self._dl_warmup_thread is None or not self._dl_warmup_thread.is_alive():
                self._dl_warmup_stop.clear()
                self._dl_warmup_thread = threading.Thread(
                    target=self._dl_warmup_worker,
                    daemon=True,
                    name="DL-Warmup-Worker",
                )
                self._dl_warmup_thread.start()
        except Exception as e:
            logger.error(f"[DL_WARMUP] enqueue error: {e}")

    # â”€â”€ v2.2.3.2.3: Subprocess-based warmup (GIL-free) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _enqueue_warmup_subprocess(self, sn: str) -> bool:
        """Send a warmup request to the GIL-free subprocess."""
        try:
            # Slice count check (skip huge series)
            dcm_count = 0
            try:
                pw = self.parent_widget
                dcm_count = pw._get_expected_series_image_count(sn) if hasattr(pw, '_get_expected_series_image_count') else 0
            except Exception:
                pass
            if 0 < dcm_count > self._DL_WARMUP_MAX_SLICES:
                logger.debug(f"[DL_WARMUP_SUB] series={sn} too large ({dcm_count} > {self._DL_WARMUP_MAX_SLICES}), skip")
                return False

            study_path = self._get_correct_study_path()
            if not study_path:
                logger.debug(f"[DL_WARMUP_SUB] series={sn} no study_path, skip")
                return False

            # Lazy-start the subprocess and poll timer
            if self._warmup_subprocess_mgr is None:
                self._warmup_subprocess_mgr = WarmupSubprocessManager()
            if not self._warmup_subprocess_mgr.is_alive:
                self._warmup_subprocess_mgr.start()
            if self._warmup_result_timer is None:
                self._warmup_result_timer = QTimer(self.parent_widget)
                self._warmup_result_timer.setInterval(100)  # 100ms poll
                self._warmup_result_timer.timeout.connect(self._poll_warmup_subprocess_results)
            if not self._warmup_result_timer.isActive():
                self._warmup_result_timer.start()

            # v2.2.3.3.9: Reduce from 2â†’1 ITK threads in subprocess.
            # The subprocess is a separate process (no GIL contention) but
            # still competes for CPU cores and memory bandwidth, causing
            # VTK SetSlice to spike from ~14ms to ~50ms during scroll.
            # 1 thread halves bandwidth contention at the cost of ~50%
            # longer per-series warmup (acceptable tradeoff for smooth scroll).
            req = WarmupRequest(
                series_number=sn,
                study_path=str(study_path),
                patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
                max_itk_threads=1,
            )
            ok = self._warmup_subprocess_mgr.submit(req)
            if ok:
                logger.debug(f"[DL_WARMUP_SUB] Submitted series={sn} to subprocess (pending={self._warmup_subprocess_mgr.pending_count})")
                return True
            else:
                logger.debug(f"[DL_WARMUP_SUB] series={sn} submit skipped (dup or full)")
                return False
        except Exception as e:
            logger.error(f"[DL_WARMUP_SUB] enqueue error: {e}")
            return False

    def _poll_warmup_subprocess_results(self):
        """QTimer callback (100ms) â€” pick up completed results from subprocess.

        Runs on the Qt main thread.  result_to_vtk() is ~5-15ms (memcpy),
        then zeta_boost.put() stores the VTK image in the cache.

        v2.2.3.3.9: Defer processing while user is actively scrolling.
        result_to_vtk + put blocks the event loop for 5-15ms per result,
        plus CPU cache pollution increases the next SetSlice by ~30ms.
        Results stay in the subprocess queue and are picked up when
        scrolling pauses (< 300ms idle).
        """
        if self._warmup_subprocess_mgr is None:
            return

        # v2.2.3.3.9: Skip during active scroll to avoid main-thread blocking
        try:
            _idle_ms = (time.time() - (self._last_user_interaction_ts or 0.0)) * 1000.0
            if _idle_ms < 300:
                return  # defer â€” results accumulate in subprocess queue
        except Exception:
            pass

        # Process at most 1 result per tick (was 2) to limit main-thread
        # blocking to ~5-15ms instead of ~10-30ms.
        for _ in range(1):
            result = self._warmup_subprocess_mgr.try_get_result()
            if result is None:
                break

            sn = result.series_number
            if not result.success:
                logger.error(f"[DL_WARMUP_SUB] âœ— series={sn} failed: {result.error} ({result.elapsed_ms:.0f}ms)")
                continue

            try:
                with self._dl_warmup_lock:
                    if self._dl_warmup_cached_count >= self._DL_WARMUP_MAX_CACHED:
                        print(
                            f"[DL_WARMUP_SUB] drop series={sn} - cap reached "
                            f"({self._dl_warmup_cached_count}/{self._DL_WARMUP_MAX_CACHED})"
                        )
                        continue
                vtk_image, metadata = result_to_vtk(result)
                if vtk_image is None:
                    logger.error(f"[DL_WARMUP_SUB] âœ— series={sn} VTK reconstruction failed")
                    continue

                # Force-put into ZetaBoost cache (bypasses Mode B guard)
                self.zeta_boost.put(
                    sn, vtk_image, metadata,
                    persist_disk=True,
                    force_during_download=True,
                )
                with self._dl_warmup_lock:
                    self._dl_warmup_cached_count += 1
                print(
                    f"[DL_WARMUP_SUB] âœ“ Cached series={sn} in {result.elapsed_ms:.0f}ms "
                    f"(count={self._dl_warmup_cached_count}/{self._DL_WARMUP_MAX_CACHED})"
                )
            except Exception as e:
                logger.error(f"[DL_WARMUP_SUB] âœ— series={sn} cache error: {e}")

        # Stop polling when nothing is pending and subprocess has drained
        if (self._warmup_subprocess_mgr.pending_count <= 0
                and self._warmup_result_timer is not None
                and self._warmup_result_timer.isActive()):
            # Keep timer alive for a short grace period in case more series arrive
            pass  # timer will stop in _stop_download_warmup

    def _dl_warmup_worker(self):
        """Background thread â€” load completed series one at a time during download.

        Safety controls:
        1. Only 1 series loaded at a time (this thread is the only loader).
        2. ``_DL_WARMUP_INTER_DELAY`` seconds between series (CPU yield).
        3. Pauses while user is scrolling (``_is_user_interaction_hot``).
        4. Skips series with too many slices (> ``_DL_WARMUP_MAX_SLICES``).
        5. Stops when ``_dl_warmup_stop`` event is set (POST_DOWNLOAD cleanup).
        6. ITK thread cap is already set to 2 by v2.2.3.0.8.
        """
        import sys
        # Lower thread priority to avoid competing with download & UI.
        try:
            if sys.platform == 'win32':
                import ctypes
                handle = ctypes.windll.kernel32.GetCurrentThread()
                ctypes.windll.kernel32.SetThreadPriority(handle, -15)  # IDLE priority
        except Exception:
            pass

        logger.debug(f"[DL_WARMUP] Worker started (max={self._DL_WARMUP_MAX_CACHED}, max_slices={self._DL_WARMUP_MAX_SLICES}, delay={self._DL_WARMUP_INTER_DELAY}s)")

        while not self._dl_warmup_stop.is_set():
            # â”€â”€ Dequeue next series â”€â”€
            with self._dl_warmup_lock:
                if not self._dl_warmup_queue:
                    break
                if self._dl_warmup_cached_count >= self._DL_WARMUP_MAX_CACHED:
                    logger.debug(f"[DL_WARMUP] Max cached reached ({self._DL_WARMUP_MAX_CACHED}), stopping")
                    break
                sn = self._dl_warmup_queue.popleft()

            # Skip if tab went inactive.
            if not self._tab_active:
                logger.debug(f"[DL_WARMUP] Tab inactive, stopping")
                break

            # Skip if already cached.
            if self.zeta_boost.has_in_memory(sn):
                logger.debug(f"[DL_WARMUP] series={sn} already in memory, skip")
                continue

            # â”€â”€ Wait while user is interacting (avoid scroll stutter) â”€â”€
            _wait_count = 0
            while self._is_user_interaction_hot() and not self._dl_warmup_stop.is_set():
                time.sleep(0.3)
                _wait_count += 1
                if _wait_count > 30:  # ~9s max wait
                    break
            if self._dl_warmup_stop.is_set():
                break

            # â”€â”€ Get image count from reliable source (server/DB metadata) â”€â”€
            dcm_count = 0
            _series_desc = ""
            _series_modality = ""
            try:
                # Primary: parent_widget._get_expected_series_image_count (server + DB)
                pw = self.parent_widget
                dcm_count = pw._get_expected_series_image_count(sn) if hasattr(pw, '_get_expected_series_image_count') else 0
                # Also grab series description & modality for logging
                _sinfo = getattr(pw, '_server_series_info', {}).get(sn, {}) or {}
                _series_desc = _sinfo.get('series_description', '') or _sinfo.get('description', '') or ''
                _series_modality = _sinfo.get('modality', '') or ''
            except Exception:
                pass

            # Fallback: count DCM files on disk if metadata unavailable
            study_path = None
            if dcm_count <= 0:
                try:
                    study_path = self._get_correct_study_path()
                    if study_path:
                        series_dir = Path(study_path) / sn
                        if series_dir.is_dir():
                            dcm_count = sum(1 for f in series_dir.iterdir() if f.suffix.lower() == '.dcm')
                except Exception:
                    pass

            if dcm_count <= 0:
                logger.debug(f"[DL_WARMUP] series={sn} no image count available, skip")
                continue
            if dcm_count > self._DL_WARMUP_MAX_SLICES:
                logger.debug(f"[DL_WARMUP] series={sn} too large ({dcm_count} slices > {self._DL_WARMUP_MAX_SLICES}), skip")
                continue

            # Resolve study_path if not yet set (needed for load)
            if not study_path:
                try:
                    study_path = self._get_correct_study_path()
                except Exception:
                    pass
            if not study_path:
                logger.debug(f"[DL_WARMUP] series={sn} no study_path, skip")
                continue

            # â”€â”€ Load series (DICOM + ITK filter + VTK conversion) â”€â”€
            _desc_tag = f" [{_series_modality}] {_series_desc}" if _series_desc else ""
            logger.debug(f"[DL_WARMUP] Loading series={sn} ({dcm_count} slices){_desc_tag}...")
            _t0 = time.perf_counter()
            try:
                result_gen = load_single_series_by_number(
                    study_path=study_path,
                    series_number=int(sn),
                    patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                    study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
                    skip_fs_validation=True,
                    # v2.2.3.2.2: raised from 1â†’2 now that the stale-event drain guard
                    # (v2.2.3.2.1) + BELOW_NORMAL OS priority (v2.2.3.2.0) prevent ITK
                    # from competing with VTK scroll renders.  Halves warmup time:
                    # 24-slice MR 500أ—640 â†’ ~1.5s instead of ~3.0s.
                    max_itk_threads=2,
                    max_pydicom_workers=2,   # v2.2.3.2.5: cap GIL contention from pydicom
                )
                cached_ok = False
                for item in result_gen:
                    vtk_image_data, metadata, _patient_study = item
                    if vtk_image_data is None or not isinstance(metadata, dict):
                        continue
                    dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
                    if int(dims[0]) <= 0 or int(dims[1]) <= 0:
                        continue
                    # Force-put into cache, bypassing Mode B guard.
                    self.zeta_boost.put(
                        sn, vtk_image_data, metadata,
                        persist_disk=True,
                        force_during_download=True,
                    )
                    cached_ok = True
                    break  # Only first group

                _elapsed = (time.perf_counter() - _t0) * 1000
                if cached_ok:
                    with self._dl_warmup_lock:
                        self._dl_warmup_cached_count += 1
                    logger.debug(f"[DL_WARMUP] âœ“ Cached series={sn} in {_elapsed:.0f}ms (count={self._dl_warmup_cached_count}/{self._DL_WARMUP_MAX_CACHED})")
                else:
                    logger.debug(f"[DL_WARMUP] series={sn} load returned no data ({_elapsed:.0f}ms)")
            except Exception as e:
                logger.error(f"[DL_WARMUP] Error loading series={sn}: {e}")

            # â”€â”€ Generous inter-series delay (avoid CPU contention) â”€â”€
            for _ in range(int(self._DL_WARMUP_INTER_DELAY * 10)):
                if self._dl_warmup_stop.is_set():
                    break
                time.sleep(0.1)

        logger.debug(f"[DL_WARMUP] Worker finished. cached={self._dl_warmup_cached_count}/{self._DL_WARMUP_MAX_CACHED}")

    def _stop_download_warmup(self):
        """Stop the per-series download warmup and reset state.

        Called on POST_DOWNLOAD (normal warmup takes over) and tab deactivation.
        v2.2.3.2.3: Also stops subprocess result-poll timer and resets subprocess state.
        The subprocess itself is NOT killed here â€” it finishes its current item
        and then sits idle.  It will be reused if another download starts, or
        killed on tab close / app exit.
        """
        try:
            # â”€â”€ Stop subprocess poll timer â”€â”€
            if self._warmup_result_timer is not None:
                try:
                    self._warmup_result_timer.stop()
                except Exception:
                    pass

            # â”€â”€ Reset subprocess tracking (let current item finish) â”€â”€
            if self._warmup_subprocess_mgr is not None:
                try:
                    self._warmup_subprocess_mgr.reset()
                except Exception:
                    pass

            # â”€â”€ Legacy thread stop â”€â”€
            self._dl_warmup_stop.set()
            with self._dl_warmup_lock:
                self._dl_warmup_queue.clear()
                self._dl_warmup_cached_count = 0
                self._dl_warmup_enqueued.clear()
        except Exception:
            pass

    def _shutdown_warmup_subprocess(self):
        """Kill the warmup subprocess entirely.  Called on tab close / app exit."""
        try:
            if self._warmup_result_timer is not None:
                try:
                    self._warmup_result_timer.stop()
                except Exception:
                    pass
                self._warmup_result_timer = None

            if self._warmup_subprocess_mgr is not None:
                try:
                    self._warmup_subprocess_mgr.shutdown(timeout=2.0)
                except Exception:
                    pass
                self._warmup_subprocess_mgr = None
        except Exception:
            pass

    def _mark_download_active(self):
        """Signal the orchestrator that a download-completed series arrived.

        Each call records the series via the PipelineOrchestrator (which
        ensures DOWNLOADING state) and also sets the legacy engine flag
        for backward compatibility.  The old QTimer-based idle detection
        is removed â€” warmup/background lanes are unblocked exclusively
        by ``on_study_download_completed()`` via the orchestrator.
        """
        try:
            self.zeta_boost.set_download_active(True)
        except Exception:
            pass

    def _clear_download_active(self):
        """Legacy stub â€” warmup is now gated by PipelineOrchestrator.

        Kept for backward compatibility; does nothing harmful.
        """
        pass

    # â”€â”€ Pipeline orchestrator integration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def on_study_download_completed(self, study_uid: str = ""):
        """Called by home_ui when the entire study download finishes.

        This is the DEFINITIVE signal that unlocks ZetaBoost warmup.
        Unlike the old timer-based heuristic, this never misfires.
        """
        try:
            self.pipeline.on_study_download_completed(study_uid)
        except Exception:
            pass

    def _on_pipeline_state_changed(self, old_state, new_state):
        """Callback from PipelineOrchestrator on every state transition.

        Bridges the orchestrator's decisions to ZetaBoost engine,
        preview engine, and warmup scheduling.
        """
        try:
            if new_state == PipelineState.POST_DOWNLOAD:
                # Study download is definitively complete.
                # 0. Stop per-series download warmup (normal warmup takes over).
                self._stop_download_warmup()
                # 1. Unlock ZetaBoost warmup/background lanes.
                #    NOTE: In FAST mode (pydicom_qt), ZetaBoost RAM cache is
                #    architecturally empty (entries=0) because Lightweight2DPipeline
                #    decodes directly from DICOM files — no VTK put() ever runs.
                #    The unlock is still issued for correctness (Advanced mode uses it),
                #    but warmup lanes will find zero work items.
                self.zeta_boost.set_study_download_complete(True)
                self.zeta_boost.set_download_active(False)
                _zb_entries = len(getattr(self.zeta_boost, '_cache', {}))
                if _zb_entries == 0:
                    logger.debug(
                        "[Pipeline] POST_DOWNLOAD ZetaBoost entries=0 "
                        "(expected in FAST/pydicom_qt — RAM cache unused)"
                    )
                # 2. Exit Mode B: re-enable series-level RAM caching.
                self.zeta_boost.set_image_boost_mode(False)
                if not self._zeta_slice_focus_mode:
                    self._image_slice_booster.clear()
                # 3. Discard lightweight previews (full volumes coming soon).
                self._preview_engine.clear()
                # 4. Schedule warmup ONLY if this tab is currently visible.
                #    If the tab is inactive (physician viewing a different patient),
                #    warmup must NOT start in the background.  It will be triggered
                #    naturally by on_tab_activated when the physician opens this tab.
                if self._tab_active:
                    try:
                        QMetaObject.invokeMethod(
                            self.parent_widget,
                            lambda: QTimer.singleShot(500, self._start_open_tab_warmup),
                            Qt.ConnectionType.QueuedConnection,
                        )
                    except Exception:
                        # Fallback: direct call (may already be on UI thread)
                        QTimer.singleShot(500, self._start_open_tab_warmup)
                    logger.debug(f"[Pipeline] POST_DOWNLOAD â†’ warmup scheduled (tab active)")
                else:
                    logger.debug(f"[Pipeline] POST_DOWNLOAD â†’ warmup deferred (tab inactive â€” starts on next activation)")

            elif new_state == PipelineState.DOWNLOADING:
                # Downloads starting â€” block ZetaBoost warmup/background.
                self.zeta_boost.set_study_download_complete(False)
                self.zeta_boost.set_download_active(True)
                # Enter Mode B: disable series-level caching, activate
                # Image Slice Booster for the current active series instead.
                self.zeta_boost.set_image_boost_mode(True)
                # STRICT ISOLATION: if this tab is NOT currently visible,
                # stop all warmup workers entirely.  Workers serve no purpose
                # during downloading for an inactive tab; they waste GIL time
                # spinning in the BLOCKED state.  Workers are recreated when
                # the physician activates this tab via on_tab_activated.
                if not self._tab_active:
                    try:
                        self.zeta_boost.deactivate(clear_cache=False)
                    except Exception:
                        pass
                    logger.debug(f"[Pipeline] DOWNLOADING â†’ engine deactivated (tab inactive, all workers stopped)")
                else:
                    logger.debug(f"[Pipeline] DOWNLOADING â†’ warmup blocked, Image Boost active")

            elif new_state == PipelineState.READY:
                logger.debug(f"[Pipeline] READY â†’ all series cached")

            elif new_state == PipelineState.IDLE:
                self._stop_download_warmup()
                self.zeta_boost.set_study_download_complete(False)
                self.zeta_boost.set_download_active(False)
                self.zeta_boost.set_image_boost_mode(False)
                self._image_slice_booster.clear()
        except Exception as e:
            logger.error(f"[Pipeline] state change error: {e}")

    def _refresh_zeta_protected_series(self):
        """Protect currently displayed series so eviction prefers non-visible entries."""
        try:
            protected = []
            thumbs = getattr(self.parent_widget, 'lst_thumbnails_data', []) or []
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
                if idx < 0 or idx >= len(thumbs):
                    continue
                sn = str(thumbs[idx].get('metadata', {}).get('series', {}).get('series_number', '') or '')
                if sn:
                    protected.append(sn)
            self.zeta_boost.set_protected_series(protected)
        except Exception:
            pass

    # ── DM priority notification on viewer interaction ────────────────
    _DM_VIEWED_NOTIFY_COOLDOWN_MS = 500  # min interval between notifications per series

    def _notify_dm_viewed_series(self, series_number: str):
        """Notify the Download Manager that a series is being actively viewed.

        Called on drag-drop / thumbnail click so the DM can:
        - Set the viewed series to CRITICAL priority.
        - Pause / demote other series in the same study.
        - Update the DM UI to reflect the new priority grouping.

        NON-BLOCKING: the actual DM call is deferred via QTimer.singleShot(0)
        so it doesn't block the drag-drop / series-switch fast path.

        Has a per-series cooldown to avoid flooding the DM with duplicate
        calls during rapid drag-drops.
        """
        try:
            study_uid = str(getattr(self.parent_widget, 'study_uid', '') or '')
            if not study_uid:
                return

            # Per-series cooldown (fast check — stays on main thread)
            now = time.monotonic() * 1000
            cooldown_map = getattr(self, '_dm_viewed_notify_ts', None)
            if cooldown_map is None:
                self._dm_viewed_notify_ts = {}
                cooldown_map = self._dm_viewed_notify_ts
            last_ts = cooldown_map.get(series_number, 0)
            if (now - last_ts) < self._DM_VIEWED_NOTIFY_COOLDOWN_MS:
                return
            cooldown_map[series_number] = now

            # Defer the heavy DM work so the series switch isn't blocked
            _sn = str(series_number)
            _uid = study_uid

            def _deferred_dm_notify():
                try:
                    from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                    home = get_home_widget()
                    if not home:
                        return
                    # Fast path: only use an EXISTING DM tab — do NOT create one
                    # just for a priority notification.  Creating the DM widget on
                    # first call adds 100+ms and blocks the main thread.
                    dm = None
                    try:
                        from modules.download_manager.ui.main_widget import DownloadManagerWidget
                        tab_w = getattr(home, 'tab_widget', None)
                        if tab_w is not None:
                            for i in range(tab_w.count()):
                                w = tab_w.widget(i)
                                if isinstance(w, DownloadManagerWidget):
                                    dm = w
                                    break
                    except Exception:
                        pass
                    # Fallback: use the original helper if the fast scan failed
                    if dm is None and hasattr(home, '_get_or_create_download_manager_tab'):
                        dm = home._get_or_create_download_manager_tab(activate_tab=False)
                    if dm is None:
                        return

                    state = dm.state_store.get(_uid)
                    if not state:
                        return

                    if hasattr(dm, 'set_viewed_series'):
                        dm.set_viewed_series(_uid, _sn)
                        self.logger.info(
                            "dm-notify: viewed series=%s study=%s → CRITICAL",
                            _sn, _uid[:30],
                        )
                except Exception as exc:
                    self.logger.debug("dm-notify: deferred failed for series=%s: %s", _sn, exc)

            QTimer.singleShot(0, _deferred_dm_notify)
        except Exception as exc:
            self.logger.debug("dm-notify: failed for series=%s: %s", series_number, exc)

    def _trigger_download_if_needed(self, series_number: str):
        """Trigger server download if series not available locally"""
        try:
            series_number = self.parent_widget.resolve_series_key(series_number)
            series_uid = None
            if hasattr(self.parent_widget, '_server_series_info') and self.parent_widget._server_series_info:
                series_info = self.parent_widget._server_series_info.get(series_number)
                if isinstance(series_info, dict):
                    series_uid = str(series_info.get('series_uid') or series_info.get('series_instance_uid') or '') or None

            logger.debug(f"   ًں“¥ Triggering server download for series {series_number}")

            # Fallback: trigger per-series retry via Download Manager
            inflight = getattr(self.parent_widget, '_retry_series_inflight', None)
            if inflight is None:
                inflight = set()
                self.parent_widget._retry_series_inflight = inflight
            if series_number in inflight:
                return
            inflight.add(series_number)

            try:
                self.parent_widget._on_retry_series_download(
                    series_number=str(series_number),
                    study_uid=str(getattr(self.parent_widget, 'study_uid', '') or ''),
                    series_uid=series_uid,
                )
            finally:
                QTimer.singleShot(2000, lambda: inflight.discard(series_number))
        except Exception as e:
            logger.error(f"   âڑ ï¸ڈ Error triggering download: {e}")

    def load_series_on_demand(self, series_number: str):
        """
        Load a series on demand with simple queue-based coordination.
        
        Download completions go to **warmup** lane (background priority).
        Only user-initiated actions (drag-drop, thumbnail click) use
        interactive lane to avoid blocking the UI during bulk downloads.
        """
        try:
            # Active-tab policy: heavy on-demand loading should happen only for active patient tab.
            if not self._tab_active:
                try:
                    series_number_str = self.parent_widget.resolve_series_key(series_number)
                except Exception:
                    series_number_str = str(series_number)
                deferred = getattr(self, '_deferred_series_load_on_activation', None)
                if deferred is None:
                    deferred = []
                    self._deferred_series_load_on_activation = deferred
                if series_number_str not in deferred:
                    deferred.append(series_number_str)
                self.logger.info(
                    "Deferred load_series_on_demand until tab activation: series=%s",
                    series_number_str,
                )
                return

            # Check if widget is still valid
            try:
                if not self.parent_widget.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            series_number_str = self.parent_widget.resolve_series_key(series_number)

            def _mark_series_ready_only() -> None:
                try:
                    if hasattr(self.parent_widget, 'thumbnail_manager') and self.parent_widget.thumbnail_manager:
                        self.parent_widget.thumbnail_manager.set_series_ready(str(series_number_str))
                        self.parent_widget.thumbnail_manager.apply_border_states_new()
                except Exception:
                    pass

            def _has_awaiting_viewer() -> bool:
                for node in self.lst_nodes_viewer or []:
                    vtk_w = getattr(node, 'vtk_widget', None)
                    if vtk_w is None:
                        continue
                    if getattr(vtk_w, '_awaiting_series_number', None) == series_number_str:
                        return True
                return False

            def _has_series_viewer_interest() -> bool:
                for node in self.lst_nodes_viewer or []:
                    vtk_w = getattr(node, 'vtk_widget', None)
                    if vtk_w is None:
                        continue
                    if getattr(vtk_w, '_progressive_series_number', None) == series_number_str:
                        return True
                    try:
                        viewer_sn = str(
                            getattr(vtk_w.image_viewer, 'metadata', {})
                            .get('series', {}).get('series_number', '')
                        )
                    except Exception:
                        viewer_sn = ''
                    if viewer_sn == series_number_str:
                        return True
                return False

            # [H7-P5] Pipeline guard in load_series_on_demand
            _pipeline_state = self.pipeline.state
            _h7_skip_orchestrator = (_pipeline_state in (PipelineState.POST_DOWNLOAD, PipelineState.READY))
            logger.info(
                "[H7-P5] series=%s pipeline_state=%s skip_orchestrator=%s "
                "first_series_displayed=%s",
                series_number_str,
                _pipeline_state.name if hasattr(_pipeline_state, 'name') else _pipeline_state,
                _h7_skip_orchestrator,
                getattr(self, '_first_series_displayed', None),
            )

            # â”€â”€ Pipeline orchestrator signaling â”€â”€
            # Notify the orchestrator that a series download completed.
            # This keeps the pipeline in DOWNLOADING state (blocking warmup)
            # until the definitive study-complete signal arrives from home_ui.
            #
            # GUARD: Do NOT signal the orchestrator when Mode A is active
            # (POST_DOWNLOAD/READY).  In Mode A, local-first-series loads
            # emit series_downloaded which would corrupt the pipeline state
            # from POST_DOWNLOAD back to DOWNLOADING, permanently blocking
            # ZetaBoost warmup.  The orchestrator also guards internally.
            _pipeline_state = self.pipeline.state
            if _pipeline_state not in (PipelineState.POST_DOWNLOAD, PipelineState.READY):
                self.pipeline.on_series_download_completed(series_number_str)
                self._mark_download_active()

            _skip_untargeted_background_completion = (
                self._is_fast_viewer_mode()
                and bool(getattr(self, '_first_series_displayed', False))
                and not _has_awaiting_viewer()
                and not self._any_viewer_empty()
                and not _has_series_viewer_interest()
            )

            if _skip_untargeted_background_completion:
                try:
                    self._finalize_progressive_series(
                        series_number_str,
                        final_count=0,
                        source='load_series_on_demand_background_skip',
                    )
                except Exception:
                    pass
                _mark_series_ready_only()
                self.logger.info(
                    'load_series_on_demand: series=%s background-complete skip '
                    '-- no awaiting/empty/displayed viewer in FAST mode',
                    series_number_str,
                )
                return

            # Exit progressive mode for this series (fully downloaded now)
            self.on_series_download_fully_complete(series_number_str)

            try:
                _completed_disk_count = int(self._count_series_files_on_disk(series_number_str) or 0)
            except Exception:
                _completed_disk_count = 0
            if _completed_disk_count > 0 and self._viewer_has_series_fully_visible(
                series_number_str,
                _completed_disk_count,
            ):
                _mark_series_ready_only()
                self.logger.info(
                    "load_series_on_demand: series=%s already fully visible "
                    "(viewer_count>=%d) -- skipping redundant post-complete reload",
                    series_number_str,
                    _completed_disk_count,
                )
                return

            # â”€â”€ Dedup guard: prevent multiple concurrent loads of same series â”€â”€
            if series_number_str in getattr(self, '_first_series_loading', set()):
                logger.debug(f"âڈ­ï¸ڈ [DEDUP] series={series_number_str} already loading, skip")
                return

            # ZetaBoost path: the FIRST series bypasses ZetaBoost entirely
            # because the warmup callback only caches â€” it does not trigger
            # _display_first_series_in_all_viewers().  Instead, the first
            # series is loaded via _async_load_and_display_series.
            #
            # IMPORTANT: Subsequent download-completed series are NOT
            # enqueued to warmup during active downloads.  The orchestrator
            # blocks warmup/background lanes until the study-level
            # download-complete signal arrives.  At that point,
            # _on_pipeline_state_changed triggers _start_open_tab_warmup
            # which enqueues ALL series for warmup in the correct order.
            try:
                if self.zeta_boost.is_active():
                    if not self._first_series_displayed:
                        # Skip trivially-small series (localizers/scouts <4 slices) as
                        # first display.  They match the image-filter skip threshold and
                        # would confuse the user when shown instead of the intended
                        # diagnostic series that is still downloading.  Route to warmup
                        # so they are cached but not displayed as the first image.
                        try:
                            _exp_slices = self._get_series_expected_slices(series_number_str)
                            if _exp_slices > 0 and _exp_slices < 4:
                                self.logger.debug(
                                    f"load_series_on_demand: series={series_number_str} only "
                                    f"{_exp_slices} slice(s) â€” routing to warmup (skip first-display)"
                                )
                                self._enqueue_download_warmup(series_number_str)
                                return
                        except Exception:
                            pass
                        # First series: thread-based load + display (not ZetaBoost).
                        # Mark as loading to prevent duplicate triggering.
                        if not hasattr(self, '_first_series_loading'):
                            self._first_series_loading = set()
                        self._first_series_loading.add(series_number_str)
                        try:
                            loop = asyncio.get_running_loop()

                            async def _first_series_with_cleanup():
                                try:
                                    await self._async_load_and_display_series(series_number_str)
                                finally:
                                    getattr(self, '_first_series_loading', set()).discard(series_number_str)

                            task = asyncio.create_task(_first_series_with_cleanup())
                            self.parent_widget._background_tasks.add(task)
                            def _cleanup_first(t):
                                try:
                                    self.parent_widget._background_tasks.discard(t)
                                except Exception:
                                    pass
                            task.add_done_callback(_cleanup_first)
                            return
                        except RuntimeError:
                            getattr(self, '_first_series_loading', set()).discard(series_number_str)
                            pass  # No running loop â€” fall through to legacy path
                    else:
                        # Subsequent download completions: enqueue for controlled
                        # per-series warmup during active download.  This caches
                        # a limited number of small completed series so they are
                        # instantly available when the user switches to them,
                        # without waiting for the full study download to finish.
                        self._enqueue_download_warmup(series_number_str)
                        return
            except Exception:
                pass

            # Avoid duplicate loads
            if series_number_str in getattr(self.parent_widget, '_pending_series_loads', set()):
                self.logger.debug(f"Series {series_number_str} already queued for loading")
                return

            # Check if already loaded
            series_key = f"series_{series_number_str}"
            if series_key in self.parent_widget.lst_series_name:
                # Series data is loaded, but if first series hasn't been displayed
                # yet (e.g. loaded by show_exist_thumbnails but never shown on
                # viewer), trigger display now.
                if (not self._first_series_displayed) or self._any_viewer_empty():
                    self.logger.info(f"Series {series_number_str} already loaded but not displayed â€” showing now")
                    QTimer.singleShot(0, lambda sn=series_number_str: self._display_series_after_load(sn))
                    return

                # Stale-data guard: if disk has more files than the cached
                # metadata, a download completed since the series was first
                # loaded (e.g. progressive partial load or drag-drop during
                # download).  Invalidate the stale cache and fall through
                # to a full reload so the viewer shows all downloaded images.
                try:
                    _cached_count = 0
                    for _td in self.parent_widget.lst_thumbnails_data:
                        _td_sn = str(_td.get('metadata', {}).get('series', {}).get('series_number', ''))
                        if _td_sn == series_number_str:
                            _cached_count = len(_td.get('metadata', {}).get('instances', []) or [])
                            break
                    _disk_count = self._count_series_files_on_disk(series_number_str)
                    if _disk_count > 0 and _disk_count > _cached_count:
                        self.logger.info(
                            "load_series_on_demand: series=%s stale "
                            "(cached=%d, disk=%d) -- invalidating for reload",
                            series_number_str, _cached_count, _disk_count,
                        )
                        self._invalidate_series_caches(series_number_str)
                        try:
                            if isinstance(self.parent_widget.lst_series_name, set):
                                self.parent_widget.lst_series_name.discard(series_key)
                            else:
                                self.parent_widget.lst_series_name.remove(series_key)
                        except (ValueError, KeyError, AttributeError):
                            pass
                        # Fall through to full reload below
                    else:
                        self.logger.debug(f"Series {series_number_str} already loaded, skipping")
                        return
                except Exception:
                    self.logger.debug(f"Series {series_number_str} already loaded, skipping")
                    return

            # Mark as pending
            if not hasattr(self.parent_widget, '_pending_series_loads'):
                self.parent_widget._pending_series_loads = set()
            self.parent_widget._pending_series_loads.add(series_number_str)

            # Try async loading if event loop available
            try:
                loop = asyncio.get_running_loop()

                # Store the event loop reference for cleanup
                self.parent_widget._event_loop = loop

                async def _safe_async_load():
                    """Load series asynchronously without locks - preview-first strategy."""
                    try:
                        # âœ… OPTIMIZATION: ظ…ط±ط­ظ„ظ‡ 1 - Preview ط³ط±غŒط¹ (100-200ms)
                        # Run preview loading in a worker thread to avoid UI/event-loop stalls.
                        study_path = self._get_correct_study_path()
                        if study_path:
                            try:
                                vtk_preview, meta_preview = await asyncio.to_thread(
                                    self._load_series_preview_async,
                                    series_number_str,
                                    study_path,
                                )
                            except AttributeError:
                                loop = asyncio.get_event_loop()
                                vtk_preview, meta_preview = await loop.run_in_executor(
                                    None,
                                    self._load_series_preview_async,
                                    series_number_str,
                                    study_path,
                                )

                            if vtk_preview is not None and meta_preview is not None:
                                # Display preview ظپظˆط±غŒ
                                try:
                                    self._apply_loaded_series_data_threadsafe(
                                        series_number_str,
                                        vtk_preview,
                                        meta_preview,
                                        self.parent_widget.metadata_fixed.get('patient_pk', None),
                                        self.parent_widget.metadata_fixed.get('study_pk', None),
                                        refresh_viewer=False,
                                    )
                                    if (not self._first_series_displayed) or self._any_viewer_empty():
                                        self._queue_on_ui_thread(
                                            lambda sn=series_number_str: self._display_series_after_load(sn)
                                        )
                                    logger.debug(f"ًں“؛ [PREVIEW] displayed for series={series_number_str}")
                                except Exception as e:
                                    logger.error(f"âڑ ï¸ڈ [PREVIEW_APPLY] error: {e}")
                        
                        # Yield immediately to prevent blocking
                        await asyncio.sleep(0)

                        # âœ… OPTIMIZATION: ظ…ط±ط­ظ„ظ‡ 2 - Full volume ط¨ط§ط±ع¯ط°ط§ط±غŒ ظ…ظˆط§ط²غŒ
                        await self._async_load_and_display_series(series_number_str)
                        
                        # âœ… OPTIMIZATION: ظ…ط±ط­ظ„ظ‡ 3 - Prefetch ط³ط±غŒط²â€Œظ‡ط§غŒ ظ…ط¬ط§ظˆط±
                        # Run prefetch ط¯ط± background (non-blocking)
                        threading.Thread(
                            target=self._prefetch_adjacent_series,
                            args=(series_number_str,),
                            daemon=True
                        ).start()

                    except asyncio.CancelledError:
                        self.logger.debug(f"Load cancelled for series {series_number_str}")
                    except RuntimeError as e:
                        if "deleted" not in str(e).lower():
                            self.logger.warning(f"Runtime error loading series {series_number_str}: {e}")
                    except Exception as e:
                        self.logger.error(f"Error loading series {series_number_str}: {e}", exc_info=True)
                    finally:
                        # Remove from pending set
                        if hasattr(self.parent_widget, '_pending_series_loads'):
                            self.parent_widget._pending_series_loads.discard(series_number_str)

                # Create task - no locks, just schedule it
                task = asyncio.create_task(_safe_async_load())
                self.parent_widget._background_tasks.add(task)

                # Cleanup on completion
                def cleanup_task(t):
                    try:
                        self.parent_widget._background_tasks.discard(t)
                    except:
                        pass  # Ignore errors during cleanup

                task.add_done_callback(cleanup_task)

            except RuntimeError:
                # No event loop - use thread-based loading
                self.logger.debug(f"No event loop, loading series {series_number_str} in thread")

                def _thread_load():
                    try:
                        # Load synchronously in thread
                        self._load_single_series_on_demand(int(series_number_str))
                    except Exception as e:
                        self.logger.error(f"Error loading series in thread: {e}", exc_info=True)
                    finally:
                        if hasattr(self.parent_widget, '_pending_series_loads'):
                            self.parent_widget._pending_series_loads.discard(series_number_str)

                thread = threading.Thread(target=_thread_load, daemon=True, name=f"SeriesLoad-{series_number_str}")
                thread.start()

        except Exception as e:
            self.logger.error(f"Error in load_series_on_demand: {e}", exc_info=True)
            if hasattr(self.parent_widget, '_pending_series_loads'):
                self.parent_widget._pending_series_loads.discard(series_number_str)

    async def _async_load_and_display_series(self, series_number: str, progressive_total: int = 0):
        """
        âڑ، OPTIMIZED: Async series loading without unnecessary sleeps.
        
        Performance improvements:
        - Removed artificial asyncio.sleep(0) calls
        - Direct async thread execution
        - Immediate result handling
        """
        try:
            # Validate widget state (no sleep delay)
            try:
                if not self.parent_widget.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            # Parse series identifier (no sleep delay)
            try:
                series_int = int(series_number)
            except ValueError:
                # Search for series by UID in loaded data
                for idx, thumb_data in enumerate(self.parent_widget.lst_thumbnails_data):
                    series_uid = thumb_data.get('metadata', {}).get('series', {}).get('series_uid', '')
                    if series_uid == series_number:
                        series_int = idx + 1
                        break
                else:
                    self.logger.warning(f"Series {series_number} not found")
                    return

            # âڑ، OPTIMIZED: Use executor immediately without sleep
            try:
                success = await asyncio.to_thread(
                    self._load_single_series_on_demand,
                    series_int
                )
            except AttributeError:
                # Fallback for Python < 3.9
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self._load_single_series_on_demand,
                    series_int
                )

            if success:
                # Mark as ready immediately
                self._display_series_after_load(str(series_number), progressive_total=progressive_total)
                # If this was a progressive load, activate progressive mode on viewers
                if progressive_total > 0:
                    self._activate_progressive_mode_on_viewers(str(series_number), progressive_total)
        
        except asyncio.CancelledError:
            self.logger.debug(f"Load cancelled for series {series_number}")
            raise
        except Exception as e:
            self.logger.error(f"Error loading series {series_number}: {e}", exc_info=True)

    def _display_series_after_load(self, series_number: str, progressive_total: int = 0):
        """
        Mark series ready; for the first downloaded series, display it in all viewers
        and hide loading.
        """
        try:
            # Validate widget state
            if not self.parent_widget.isVisible():
                return

            if (not self._first_series_displayed) or self._any_viewer_empty():
                if self._display_first_series_in_all_viewers(series_number, progressive_total=progressive_total):
                    self._mark_first_series_displayed()
                    return

            # Mark as ready in thumbnail manager
            if hasattr(self.parent_widget, 'thumbnail_manager') and self.parent_widget.thumbnail_manager:
                self.parent_widget.thumbnail_manager.set_series_ready(str(series_number))
                self.parent_widget.thumbnail_manager.apply_border_states_new()
                self.logger.debug(f"Series {series_number} marked as ready")
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in _display_series_after_load: {e}")
        except Exception as e:
            self.logger.error(f"Error in _display_series_after_load: {e}", exc_info=True)
            traceback.print_exc()

    def _ensure_loading_dialog(self):
        if getattr(self.parent_widget, "_loading_dlg", None) is not None:
            return

        dlg = QProgressDialog("Processing...", None, 0, 0, self.parent_widget,
                              flags=Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.MSWindowsFixedSizeDialogHint)
        dlg.setWindowTitle("Please wait")
        dlg.setWindowModality(Qt.NonModal)  # ظپظ‚ط· ظ¾غŒط§ظ…ط› UI ظ‚ظپظ„ ظ†ط´ظ‡
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.resize(420, 120)

        # ًںژ¨ ط§ط³طھط§غŒظ„ طھغŒط±ظ‡ ظˆ ظ…غŒظ†غŒظ…ط§ظ„
        dlg.setStyleSheet("""
            QProgressDialog {
                background: #0b1220;
                border: 1px solid #223046;
                border-radius: 12px;
                color: #e5e7eb;
            }
            QProgressDialog QLabel {
                color: #e5e7eb;
                font-family: 'Segoe UI', 'Roboto';
                font-size: 14px;
                font-weight: 600;
                padding: 10px 14px;
                border: none;
                background: transparent;
            }
            /* ProgressBar ظ…ط§ط±ع©ظˆغŒ ظ†ط±ظ…ظگ ظ†ط§ظ…ط´ط®طµ */
            QProgressBar {
                border: 1px solid #2b3b55;
                border-radius: 8px;
                background: #0f172a;
                height: 14px;
                text-align: center;
                color: #94a3b8;
                padding: 0px;
                margin: 0 14px 14px 14px;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                             stop:0 #38bdf8, stop:1 #60a5fa);
            }
        """)

        # ط¬ط§غŒâ€Œع¯ط°ط§ط±غŒ ظˆط³ط·ظگ ظ¾ظ†ظ„ ظ…ط±ع©ط²غŒ ط§ع¯ط± ظ…ظˆط¬ظˆط¯ ط¨ظˆط¯
        try:
            parent_widget = getattr(self.parent_widget, "right_panel", None) or self.parent_widget
            g = parent_widget.frameGeometry()
            dlg.move(g.center() - dlg.rect().center())
        except Exception:
            pass

        self.parent_widget._loading_dlg = dlg
        self.parent_widget._loading_cnt = 0

    def _show_loading_msg(self, text="Applying layout..."):
        # COMMENTED OUT TO AVOID SHOWING LOADING MESSAGE TO USER
        # self._ensure_loading_dialog()
        # self.parent_widget._loading_cnt += 1
        # # غŒع© ظ…طھظ† ط¯ظˆط³طھط§ظ†ظ‡ ط¨ط§ ط§غŒظ…ظˆط¬غŒ طھع©â€Œط±ظ†ع¯ (ط±ظˆغŒ طھظ… طھغŒط±ظ‡ ط®ظˆط¨ ط¯غŒط¯ظ‡ ظ…غŒâ€Œط´ظˆط¯)
        # pretty = f"âڑ™ï¸ڈ  {text}\nThis may take a few secondsâ€¦"
        # self.parent_widget._loading_dlg.setLabelText(pretty)
        # self.parent_widget._loading_dlg.setRange(0, 0)  # ط­ط§ظ„طھ ظ†ط§ظ…ط´ط®طµ (ط§ط³ظ¾غŒظ†غŒظ†ع¯)
        # self.parent_widget._loading_dlg.show()
        # self.parent_widget._loading_dlg.raise_()

        # center = QApplication.primaryScreen().availableGeometry().center()
        # self.parent_widget._loading_dlg.move(center - self.parent_widget._loading_dlg.rect().center())

        # QApplication.processEvents()
        pass  # Do nothing to avoid showing loading message to user

    def _hide_loading_msg(self):
        # COMMENTED OUT TO MATCH _show_loading_msg BEING DISABLED
        # if getattr(self.parent_widget, "_loading_dlg", None) is None:
        #     return
        # self.parent_widget._loading_cnt = max(0, self.parent_widget._loading_cnt - 1)
        # if self.parent_widget._loading_cnt == 0:
        #     self.parent_widget._loading_dlg.hide()
        #     QApplication.processEvents()
        pass  # Do nothing to match _show_loading_msg being disabled

    def _get_default_layout_from_config(self, modality: str = None) -> tuple[int, int]:
        """Read layout from modality_grid.json based on modality (fallback to default then 1x2).
        
        Args:
            modality: Optional modality string (e.g., 'CT', 'MR'). If provided, tries to find
                     modality-specific layout first.
        
        Returns:
            tuple: (rows, cols) for viewer grid layout
        """
        try:
            self._ensure_grid_config_exists()
            if GRID_CONFIG_PATH.exists():
                with open(GRID_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 1. ط§ع¯ط± ظ…ظˆط¯ط§ظ„غŒطھغŒ ظ…ط´ط®طµ ط´ط¯ظ‡طŒ ط§ط¨طھط¯ط§ ط¯ط± modality_layouts ط¬ط³طھط¬ظˆ ظ…غŒâ€Œع©ظ†غŒظ…
                if modality:
                    # ط¬ط³طھط¬ظˆ ط¯ط± modality_layouts
                    modality_layouts = data.get('modality_layouts', {})
                    if modality in modality_layouts:
                        mod_cfg = modality_layouts[modality]
                        if isinstance(mod_cfg, dict):
                            rows = int(mod_cfg.get('rows', 1))
                            cols = int(mod_cfg.get('cols', 2))
                            logger.debug(f"âœ… Using layout for {modality}: {rows}x{cols}")
                            return (rows, cols)
                    
                    # ط§ع¯ط± ط¯ط± modality_layouts ظ†ط¨ظˆط¯طŒ ظ…ط³طھظ‚غŒظ… ط¯ط± root ط¬ط³طھط¬ظˆ ظ…غŒâ€Œع©ظ†غŒظ… (ط¨ط±ط§غŒ ط³ط§ط²ع¯ط§ط±غŒ ط¨ط§ ظپط§غŒظ„â€Œظ‡ط§غŒ ظ‚ط¯غŒظ…غŒ)
                    if modality in data:
                        mod_cfg = data[modality]
                        if isinstance(mod_cfg, dict):
                            rows = int(mod_cfg.get('rows', 1))
                            cols = int(mod_cfg.get('cols', 2))
                            logger.debug(f"âœ… Using layout for {modality} (legacy): {rows}x{cols}")
                            return (rows, cols)
                
                # 2. ط§ع¯ط± ظ…ظˆط¯ط§ظ„غŒطھغŒ ظ¾غŒط¯ط§ ظ†ط´ط¯ غŒط§ ظ…ط´ط®طµ ظ†ط´ط¯ظ‡طŒ ط§ط² default ط§ط³طھظپط§ط¯ظ‡ ظ…غŒâ€Œع©ظ†غŒظ…
                default_cfg = data.get('default') or data.get('DEFAULT')
                if isinstance(default_cfg, dict):
                    rows = int(default_cfg.get('rows', 1))
                    cols = int(default_cfg.get('cols', 2))
                    logger.debug(f"â„¹ï¸ڈ Using default layout: {rows}x{cols}")
                    return (rows, cols)
                    
        except Exception as e:
            logger.error(f"âڑ ï¸ڈ Error reading grid config: {e}")
        
        # 3. ط§ع¯ط± ظ‡ظ…ظ‡ ع†غŒط² ظ†ط§ظ…ظˆظپظ‚ ط¨ظˆط¯طŒ ط§ط² fallback ط§ط³طھظپط§ط¯ظ‡ ظ…غŒâ€Œع©ظ†غŒظ…
        logger.debug("â„¹ï¸ڈ Using fallback layout: 1x2")
        return (1, 2)

    def _load_first_series_sync(self, size_init_viewers):
        """Load first series synchronously when no event loop is available"""
        try:
            from PacsClient.pacs.patient_tab.utils import load_images

            print("ًں“‚ [SYNC_LOAD] Loading first series synchronously...") # ظ„ط§ع¯ ط§ط¶ط§ظپظ‡ ط´ط¯ظ‡

            first_series_loaded = False
            for vtk_image_data, metadata, patient_info in load_images(
                    self.parent_widget.import_folder_path,
                    patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                    study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.parent_widget.ordering_by_instances_number
            ):
                # âœ… FLICKER FIX: Only process events if not in initialization batch
                # NOTE: processEvents() removed â€” it caused re-entrancy during
                # initial load (download signals processed mid-initialization).
                # The batch update via setUpdatesEnabled(False) handles this.
                pass

                self.parent_widget.check_and_add_meta_fixed(patient_info)

                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}

                self.parent_widget.add_new_data_to_lst_thumbnails_data(new_data)

                if not first_series_loaded:
                    optimal_layout = self.parent_widget.get_optimal_layout_for_series(metadata)
                    print(f"âœ… [SYNC_LOAD] Determined optimal layout: {optimal_layout}") # ظ„ط§ع¯ ط§ط¶ط§ظپظ‡ ط´ط¯ظ‡

                    # âڑ، OPTIMIZATION: Removed processEvents() - use batch update instead
                    # Use synchronous viewer creation
                    self._apply_multi_viewer_sync(optimal_layout) # ط§غŒظ† طھط§ط¨ط¹ ظˆغŒظˆظˆط±ظ‡ط§ ط±ط§ طھظ†ط¸غŒظ… ظ…غŒ ع©ظ†ط¯

                    first_series_loaded = True
                    self._hide_loading_spinner()

                    series_no = metadata['series']['series_number']
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(series_no))
                    self.parent_widget.thumbnail_manager.set_series_ready(str(series_no))

                    if file_path and not self.parent_widget.logo_patient:
                        self.parent_widget.logo_patient = file_path
                        self.parent_widget.update_tab_manager()

                    print(f"âœ… [SYNC_LOAD] First series loaded: {series_no}. Breaking loop.") # ظ„ط§ع¯ ط§ط¶ط§ظپظ‡ ط´ط¯ظ‡
                    break  # ظپظ‚ط· ط§ظˆظ„غŒظ† ط³ط±غŒ ط±ط§ ط¨ط§ط±ع¯ط°ط§ط±غŒ ع©ظ†

        except Exception as e:
            print(f"â‌Œ [SYNC_LOAD] Error loading first series sync: {e}") # ظ„ط§ع¯ ط§ط¶ط§ظپظ‡ ط´ط¯ظ‡
            import traceback
            traceback.print_exc()

    def _apply_multi_viewer_sync(self, numbers):
        """âڑ، Optimized: Synchronous viewer layout without processEvents delays"""
        try:
            number_of_row, number_of_column = int(numbers[0]), int(numbers[1])

            self._current_layout = (number_of_row, number_of_column)

            # Cleanup old viewers
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()

            # Create new viewers
            count = number_of_row * number_of_column
            self.create_some_viewers(count)

            # Apply layout
            if (number_of_row, number_of_column) == (1, 1) and len(self.lst_nodes_viewer) > 0:
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.parent_widget.change_container_border(0)
            elif (number_of_row, number_of_column) == (2, 1) and len(self.lst_nodes_viewer) >= 2:
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
                self.parent_widget.change_container_border(0)
            elif (number_of_row, number_of_column) == (1, 2) and len(self.lst_nodes_viewer) >= 2:
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
                self.parent_widget.change_container_border(0)

            # âڑ، OPTIMIZATION: Removed processEvents() call - introduces unwanted delay

        except Exception as e:
            logger.error(f"â‌Œ Error applying viewer layout sync: {e}")
            import traceback
            traceback.print_exc()

    def load_first_series_only(self, folder_path, series_number):
        """
        Load only the first series when it's downloaded
        ط¨ط§ط±ع¯ط°ط§ط±غŒ ظپظ‚ط· ط§ظˆظ„غŒظ† ط³ط±غŒ ظˆظ‚طھغŒ ط¯ط§ظ†ظ„ظˆط¯ ط´ط¯

        This method is called by home_ui when the first series download completes.

        Args:
            folder_path: Path to the study folder
            series_number: The series number that was downloaded
        """
        try:
            logger.debug(f"ًںژ¯ load_first_series_only called: series {series_number}")

            # Update folder path if needed
            if folder_path and folder_path != self.parent_widget.import_folder_path:
                self.parent_widget.import_folder_path = folder_path

            # Check if we already have this series loaded
            series_key = f"series_{series_number}"
            if series_key in self.parent_widget.lst_series_name:
                logger.debug(f"âڈ­ï¸ڈ Series {series_number} already loaded")
                return

            # Phase 4: route first-series auto-display through the centralized
            # preview-first path instead of forcing a synchronous full-series load.
            try:
                self.load_series_on_demand(str(series_number))
                logger.debug(f"âœ… First-series load queued via preview-first path: {series_number}")
            except Exception as load_error:
                logger.error(f"â‌Œ Error queueing first series {series_number}: {load_error}")

        except Exception as e:
            logger.error(f"â‌Œ Error in load_first_series_only: {e}")
            import traceback
            traceback.print_exc()

    def load_series_immediately(self, series_number: str, series_dir: str):
        """
        Load a series immediately after download and display it automatically.

        Args:
            series_number: Can be either a simple series number (e.g., "1", "2")
                          or a Series Instance UID (e.g., "1.3.12.2.1107...")
            series_dir: Directory containing the series DICOM files
        """
        try:
            logger.debug(f"{'='*80}")
            logger.debug(f"ًں“¥ [PRIORITY LOAD] Loading series {series_number} (auto-display)")
            logger.debug(f"ًں“پ Directory: {series_dir}")
            logger.debug(f"{'='*80}")

            # Check DICOM files
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            if not dicom_files:
                logger.debug(f"â‌Œ No DICOM files found in {series_dir}")
                return

            # Keep import_folder_path at study level (not inside a series folder).
            try:
                resolved_study_path = str(series_path.parent) if series_path.parent.exists() else series_dir
                if resolved_study_path and resolved_study_path != self.parent_widget.import_folder_path:
                    self.parent_widget.import_folder_path = resolved_study_path
            except Exception:
                pass

            # Skip if already loaded
            series_key = f"series_{series_number}"
            if series_key in self.parent_widget.lst_series_name:
                logger.debug(f"âڈ­ï¸ڈ Series {series_number} already loaded")
                return

            # âœ… FIX: Handle both series numbers and Series Instance UIDs
            try:
                series_int = int(series_number)
            except ValueError:
                # Not a simple number - extract series number from directory name
                # Directory name should be the actual series number
                try:
                    series_int = int(series_path.name)
                    logger.debug(f"   ًں”چ Extracted series number {series_int} from directory name")
                except ValueError:
                    logger.debug(f"â‌Œ Cannot determine series number from UID {series_number} or directory {series_path.name}")
                    return

            # Phase 4: delegate to the centralized preview-first path so
            # auto-display downloads get the same fast first-image behavior as
            # interactive switching instead of blocking on a synchronous full load.
            self.load_series_on_demand(str(series_int))
            logger.debug(f"âœ… Series {series_int} queued for preview-first auto-display.")
        except Exception as e:
            logger.error(f"â‌Œ CRITICAL ERROR in load_series_immediately: {e}")
            import traceback
            traceback.print_exc()

    def _trigger_priority_display(self, series_key):
        """Mark series as ready; first-series display is handled by series_downloaded signal.

        Complete_series_download fires BOTH _trigger_priority_display AND
        series_downloaded.emit.  The first-series load is handled by
        load_series_on_demand (from the emit), so we must NOT call it again
        here to avoid duplicate loads that triple GIL contention.
        """
        try:
            series_key = self.parent_widget.resolve_series_key(series_key)

            # Just mark ready â€” load_series_on_demand handles display via signal
            if hasattr(self.parent_widget, 'thumbnail_manager') and self.parent_widget.thumbnail_manager:
                self.parent_widget.thumbnail_manager.set_series_ready(str(series_key))
                self.parent_widget.thumbnail_manager.apply_border_states_new()
        except Exception as e:
            logger.error(f"âڑ ï¸ڈ Error triggering priority display: {e}")

    def _distribute_series_to_viewers(self):
        """
        âڑ، OPTIMIZED: Distribute series to viewers with efficient tracking.
        
        Improvements:
        - Uses set-based deduplication instead of nested loops
        - Single pass through viewers
        - O(n) instead of O(nآ²)
        """
        if not self.parent_widget.lst_thumbnails_data or not self.lst_nodes_viewer:
            return

        try:
            # Track which series are already displayed (O(1) lookup)
            displayed_series = set()
            series_queue = list(range(len(self.parent_widget.lst_thumbnails_data)))
            
            for viewer_idx, node_viewer in enumerate(self.lst_nodes_viewer):
                # Check if viewer already has data
                if hasattr(node_viewer.vtk_widget, 'last_series_show') and node_viewer.vtk_widget.last_series_show is not None:
                    displayed_series.add(node_viewer.vtk_widget.last_series_show)
                    continue
                
                # âڑ، FAST: Find first undisplayed series
                series_idx = None
                for idx in series_queue:
                    if idx not in displayed_series:
                        series_idx = idx
                        break
                
                if series_idx is None and series_queue:
                    series_idx = series_queue[0]  # Reuse first if all claimed
                
                if series_idx is not None:
                    series_data = self.parent_widget.lst_thumbnails_data[series_idx]
                    series_num = series_data['metadata']['series']['series_number']
                    # Keep this set in thumbnail-index space for consistent comparisons
                    displayed_series.add(series_idx)
                    
                    # Display without redundant checks
                    if hasattr(node_viewer, 'vtk_widget'):
                        flag_switch = node_viewer.vtk_widget.switch_series(
                            series_data['vtk_image_data'],
                            series_data['metadata'],
                            series_idx,
                            metadata_fixed=self.parent_widget.metadata_fixed
                        )
                        
                        if flag_switch and viewer_idx == 0:
                            self.set_viewer_to_main_viewer(node_viewer)
                        
                        if flag_switch and hasattr(node_viewer, 'slider'):
                            self.parent_widget.reset_slider(node_viewer.vtk_widget, node_viewer.slider)
                            if node_viewer.vtk_widget.image_viewer:
                                node_viewer.vtk_widget.image_viewer.update_corners_actors()

            # Reference lines must be recalculated after all viewers are populated
            try:
                self.parent_widget.manage_reference_line()
            except Exception:
                pass
        
        except Exception as e:
            self.logger.error(f"Error distributing series: {e}", exc_info=True)
            logger.error(f"â‌Œ [DISTRIBUTE] Error distributing series to viewers: {e}")
            import traceback
            traceback.print_exc()

        # Hide loading spinner
        if hasattr(node_viewer.vtk_widget, 'viewport_spinner'):
            node_viewer.vtk_widget.viewport_spinner.hide_loading()

        # Update UI
        node_viewer.vtk_widget.show()
        node_viewer.vtk_widget.update()
        node_viewer.widget.show()
        node_viewer.widget.update()

        if node_viewer.vtk_widget.image_viewer:
            node_viewer.vtk_widget.image_viewer.Render()
            node_viewer.vtk_widget.render_window.Render()
            node_viewer.vtk_widget.GetRenderWindow().Render()

        logger.debug(f"   âœ… Viewer {viewer_idx} populated successfully")



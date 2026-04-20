"""
Warmup and prefetch mixin for ViewerController.
Background prefetch, open-tab warmup worker, deferred heavy warmup, cleanup helpers, first-display-in-all-viewers.
"""
from __future__ import annotations
import os
import threading
import time
import gc
import traceback
from modules.viewer.fast.ui_throttle import (
    clear_active_orchestrator as _clear_active_orchestrator,
    should_admit as _ui_should_admit,
)
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QSlider
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number, load_series_preview
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.pacs.patient_tab.utils import delete_widgets_in_layout
from modules.zeta_boost import ZetaBoostEngine, ImageSliceBooster
import logging

logger = logging.getLogger(__name__)


def _should_admit_warmup(obj, work_key: str) -> bool:
    """Admission front door for warmup-lane entry points."""
    return bool(_ui_should_admit(
        "cache_warm",
        {
            "key": f"warmup:{id(obj)}:{work_key}",
            "series_key": str(work_key),
        },
    ))


class _VCWarmupMixin:
    """Auto-split mixin — see patient_widget_viewer_controller.py for history."""

    def _start_open_tab_warmup(self):
        """On tab activation, immediately queue already-downloaded series for ZetaBoost caching."""
        try:
            if self._zeta_slice_focus_mode:
                return
            if not self._boostviewer_enabled:
                return
            # Fast mode uses only local ±20 ImageSliceBooster — skip series warmup
            if self._is_fast_viewer_mode():
                return
            if not self._tab_active:
                return
            if not self.zeta_boost.is_active():
                return
            if self._global_downloads_active():
                print(
                    f"[WARMUP] Skipped â€” global downloads active "
                    f"count={int(getattr(ZetaBoostEngine, '_global_active_download_count', 0) or 0)}"
                )
                return
            # STRICT ISOLATION: Never warm up while downloads are in progress.
            # The pipeline is authoritative: if it says warmup is not allowed
            # (IDLE or DOWNLOADING state), stop here without retry.
            if not self.pipeline.is_warmup_allowed:
                print(
                    f"[WARMUP] Skipped â€” pipeline={self.pipeline.state.name} "
                    f"(warmup only allowed in POST_DOWNLOAD/READY)"
                )
                return

            if not _should_admit_warmup(self, "open_tab"):
                if self._open_warmup_retry_count < 10:
                    self._open_warmup_retry_count += 1
                    QTimer.singleShot(350, self._start_open_tab_warmup)
                return

            # Let first visible series settle before warmup to keep tab-open responsive.
            try:
                if not bool(self._first_series_displayed):
                    if self._open_warmup_retry_count < 10:
                        self._open_warmup_retry_count += 1
                        QTimer.singleShot(300, self._start_open_tab_warmup)
                    return
            except Exception:
                pass

            # Keep warmup off while user is actively interacting to avoid
            # subtle stutter during download-time scrolling.
            if self._is_user_interaction_hot():
                if self._open_warmup_retry_count < 10:
                    self._open_warmup_retry_count += 1
                    QTimer.singleShot(350, self._start_open_tab_warmup)
                return

            # Ensure thumbnails are already visible before warmup starts.
            try:
                thumbs_visible = bool(getattr(self.parent_widget, '_thumbnails_shown', False))
                thumbs_ready = bool(getattr(getattr(self.parent_widget, 'thumbnail_manager', None), 'series_widgets', {}))
                if not (thumbs_visible and thumbs_ready):
                    if self._open_warmup_retry_count < 10:
                        self._open_warmup_retry_count += 1
                        QTimer.singleShot(300, self._start_open_tab_warmup)
                    return
            except Exception:
                pass

            # Avoid competing with initial viewer pipeline; retry shortly until ready.
            try:
                if bool(getattr(self.parent_widget, '_pipeline_running', False)):
                    if self._open_warmup_retry_count < 10:
                        self._open_warmup_retry_count += 1
                        print(
                            f"âڈ³ [ZetaBoost][OPEN_WARMUP] waiting pipeline retry="
                            f"{self._open_warmup_retry_count}/10 study={getattr(self.parent_widget, 'study_uid', 'unknown')}"
                        )
                        QTimer.singleShot(350, self._start_open_tab_warmup)
                    return
            except Exception:
                pass

            # ---- Heavy candidate gathering (filesystem scan, DICOM header reads,
            # SQLite manifest queries) MUST run off the UI thread to keep the
            # tab-open experience responsive.  Guards above ensure preconditions
            # are met; the actual work is delegated to a daemon thread. ----
            if getattr(self, '_warmup_gather_running', False):
                return  # A warmup-gather thread is already in-flight
            self._warmup_gather_running = True
            threading.Thread(
                target=self._open_tab_warmup_worker,
                daemon=True,
                name="ZetaBoost-WarmupGather",
            ).start()
        except Exception as e:
            self.logger.debug(f"Error in open-tab warmup: {e}")

    def _open_tab_warmup_worker(self):
        """[Background thread] Gather warmup candidates and enqueue to ZetaBoost."""
        try:
            # Re-check volatile state that may have changed since the UI-thread
            # guard ran (tab closed, engine deactivated, boostviewer toggled).
            if not self._boostviewer_enabled or not self._tab_active:
                self._warmup_gather_running = False
                return
            if not self.zeta_boost.is_active():
                self._warmup_gather_running = False
                return
            if self._global_downloads_active() or (not self.pipeline.is_warmup_allowed):
                self._warmup_gather_running = False
                return

            study_path = self._get_correct_study_path()
            if not study_path:
                return

            candidates = []
            # 1) Prefer discovered series from metadata thumbnails.
            if hasattr(self.parent_widget, 'lst_thumbnails_data') and self.parent_widget.lst_thumbnails_data:
                for item in self.parent_widget.lst_thumbnails_data:
                    try:
                        sn = str(item.get('metadata', {}).get('series', {}).get('series_number', ''))
                        if sn and sn.isdigit():
                            candidates.append(sn)
                    except Exception:
                        continue

            # 2) Fallback/augment from local downloaded folders.
            try:
                p = Path(study_path)
                if p.exists():
                    for d in p.iterdir():
                        if not d.is_dir() or not d.name.isdigit():
                            continue
                        has_dcm = bool(next(d.glob('*.dcm'), None) or next(d.glob('*.DCM'), None))
                        if has_dcm:
                            candidates.append(str(d.name))
            except Exception:
                pass

            # Deduplicate + sort numeric
            candidates = sorted(set(candidates), key=lambda x: int(x))
            total_candidates = len(candidates)

            # Primary series should not be warmup-loaded here; the main pipeline/lazy-first
            # path handles it and duplicate loading adds startup contention.
            primary_series = None
            try:
                if self.parent_widget.lst_thumbnails_data:
                    primary_series = str(
                        self.parent_widget.lst_thumbnails_data[0].get('metadata', {}).get('series', {}).get('series_number', '')
                    )
            except Exception:
                primary_series = None

            # Skip currently visible/active series to avoid duplicate startup work.
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

            filtered_candidates = []
            heavy_candidates = []
            skipped_active = 0
            skipped_primary = 0
            skipped_large = 0
            skipped_corrupt = 0
            skipped_failed = 0
            skipped_cached = 0
            skipped_non_image = 0
            _filter_details = []  # per-series filter trace
            for sn in candidates:
                if not sn:
                    continue
                sn_str = str(sn)  # Ensure string comparison
                if primary_series and sn_str == primary_series:
                    skipped_primary += 1
                    _filter_details.append(f"{sn}:primary")
                    continue
                if sn_str == selected_series:
                    skipped_active += 1
                    _filter_details.append(f"{sn}:active")
                    continue
                # --- Fast non-image gate (SOP Class + Rows/Cols) ---
                try:
                    if not self._is_series_image_type_for_warmup(sn):
                        skipped_non_image += 1
                        _filter_details.append(f"{sn}:non_image")
                        continue
                except Exception:
                    pass
                try:
                    if not self._is_series_header_consistent_for_warmup(sn):
                        skipped_corrupt += 1
                        self._warmup_corrupt_skip_counts[sn_str] = int(self._warmup_corrupt_skip_counts.get(sn_str, 0)) + 1
                        _filter_details.append(f"{sn}:corrupt")
                        continue
                except Exception:
                    pass
                if sn_str in self._zeta_boost_failed_series:
                    skipped_failed += 1
                    _filter_details.append(f"{sn}:failed")
                    continue
                _in_mem = self._is_series_in_memory_only(sn)
                if _in_mem:
                    skipped_cached += 1
                    _filter_details.append(f"{sn}:in_mem")
                    continue
                try:
                    exp_slices = self._get_series_expected_slices(sn)
                    if exp_slices > 0 and exp_slices > int(self._warmup_max_slices):
                        skipped_large += 1
                        heavy_candidates.append(sn)
                        _filter_details.append(f"{sn}:heavy({exp_slices})")
                        continue
                except Exception:
                    pass
                filtered_candidates.append(sn)
                _filter_details.append(f"{sn}:QUEUE")
            logger.debug(f"ًں”§ [WARMUP_FILTER] detail: {' | '.join(_filter_details[:40])}")
            candidates = filtered_candidates
            # Sort light candidates: small (fast-loading) series first so users get
            # near-instant access to them while slower series load in background.
            # e.g. series_8 (3 slices, ~0.2s ITK) before series_6 (20 slices, ~4s ITK).
            try:
                candidates.sort(key=lambda s: self._get_series_expected_slices(s) or 9999)
            except Exception:
                pass
            heavy_candidates = [
                sn for sn in heavy_candidates
                if sn not in self._zeta_boost_failed_series and (not self._is_series_in_memory_only(sn))
            ]

            admitted_heavy, dropped_heavy, current_bytes, budget_bytes, reserve_bytes = self._filter_heavy_candidates_by_capacity(heavy_candidates)
            heavy_candidates = admitted_heavy

            study_for_log = str(getattr(self.parent_widget, 'study_uid', '') or '').strip()
            try:
                import_path = str(getattr(self.parent_widget, 'import_folder_path', '') or '').strip()
                if import_path:
                    study_from_path = Path(import_path).name
                    # Prefer path-derived UID when runtime value looks malformed.
                    if (not study_for_log) or ('..' in study_for_log and '..' not in study_from_path):
                        study_for_log = study_from_path
            except Exception:
                pass
            if not study_for_log:
                study_for_log = 'unknown'

            print(
                f"â„¹ï¸ڈ [ZetaBoost][OPEN_WARMUP] filtered study={study_for_log} "
                f"total={total_candidates} skipped_active={skipped_active} skipped_primary={skipped_primary} "
                f"skipped_large={skipped_large} skipped_corrupt={skipped_corrupt} skipped_non_image={skipped_non_image} "
                f"skipped_failed={skipped_failed} skipped_cached={skipped_cached} "
                f"queued_light={len(candidates)} queued_heavy={len(heavy_candidates)}"
            )

            if dropped_heavy:
                print(
                    f"â„¹ï¸ڈ [ZetaBoost][HEAVY_ADMISSION] study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                    f"admitted={len(heavy_candidates)} dropped={len(dropped_heavy)} "
                    f"cache_bytes={current_bytes}/{budget_bytes} reserve={reserve_bytes} dropped_series={dropped_heavy[:12]}"
                )

            if not candidates and not heavy_candidates:
                # Nothing queueable because everything is already cached or intentionally skipped.
                # Do not keep retrying; retries here cause cache probe churn and UI stalls.
                if total_candidates > 0 and (
                    skipped_cached > 0
                    or (skipped_active + skipped_primary + skipped_large + skipped_corrupt + skipped_non_image + skipped_failed) >= total_candidates
                ):
                    print(
                        f"â„¹ï¸ڈ [ZetaBoost][OPEN_WARMUP] completed_noop study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                        f"reason=all_candidates_already_handled total={total_candidates}"
                    )
                    return

                # Tab may activate before thumbnails are populated; retry briefly.
                if self._open_warmup_retry_count < 6:
                    self._open_warmup_retry_count += 1
                    print(
                        f"âڈ³ [ZetaBoost][OPEN_WARMUP] no queueable series yet, retry="
                        f"{self._open_warmup_retry_count}/6 study={getattr(self.parent_widget, 'study_uid', 'unknown')}"
                    )
                    # QTimer must be scheduled on the UI thread.
                    self._queue_on_ui_thread(lambda: QTimer.singleShot(350, self._start_open_tab_warmup))
                return

            if candidates:
                self.zeta_boost.enqueue_many_warmup(candidates)
                print(
                    f"ًںڑ€ [ZetaBoost][OPEN_WARMUP] active_tab=True study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                    f"queued_light_series={len(candidates)} series={candidates[:12]}"
                )

            if heavy_candidates:
                self._deferred_heavy_warmup_series = list(heavy_candidates)
                self._deferred_heavy_warmup_retry_count = 0
                print(
                    f"âڈ³ [ZetaBoost][HEAVY_DEFER] scheduled study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                    f"queued_heavy_series={len(heavy_candidates)} delay_ms=1500 series={heavy_candidates[:12]}"
                )
                # QTimer must be scheduled on the UI thread.
                self._queue_on_ui_thread(lambda: QTimer.singleShot(1500, self._start_deferred_heavy_warmup))

            self._log_warmup_coverage(stage="after_open_warmup_schedule")
        except Exception as e:
            try:
                self.logger.debug(f"Error in open-tab warmup worker: {e}")
            except Exception:
                pass
        finally:
            self._warmup_gather_running = False

    def _start_deferred_heavy_warmup(self):
        """Second-phase warmup: enqueue large series after light warmup/initial UX settles.

        All eligible heavy series are queued at once so the engine's 2
        parallel background workers can overlap DICOM+ITK loads.  The
        engine internally respects max_parallel_loads and lane priority
        so interactive requests always preempt background work.
        """
        try:
            if self._zeta_slice_focus_mode:
                return
            if not self._boostviewer_enabled:
                return
            if not self._tab_active or not self.zeta_boost.is_active():
                return
            if not self._deferred_heavy_warmup_series:
                return

            if not _should_admit_warmup(self, "deferred_heavy"):
                if self._deferred_heavy_warmup_retry_count < 12:
                    self._deferred_heavy_warmup_retry_count += 1
                    QTimer.singleShot(800, self._start_deferred_heavy_warmup)
                return

            # Viewer-first guard: wait for a short idle window before heavy warmup.
            if self._plan_a_viewer_first:
                idle_sec = max(0.0, time.time() - float(self._last_user_interaction_ts or 0.0))
                if idle_sec < self._heavy_warmup_idle_sec:
                    if self._deferred_heavy_warmup_retry_count < 12:
                        self._deferred_heavy_warmup_retry_count += 1
                        QTimer.singleShot(800, self._start_deferred_heavy_warmup)
                    return

            # Only defer if the user is *actively* interacting right now.
            # Lane-level scheduling is handled by the engine; we don't
            # need to wait for lane-idle here.
            if bool(self._interactive_load_in_progress) or self.zeta_boost.has_lane_activity("interactive"):
                if self._deferred_heavy_warmup_retry_count < 12:
                    self._deferred_heavy_warmup_retry_count += 1
                    QTimer.singleShot(1000, self._start_deferred_heavy_warmup)
                return

            queue = []
            for sn in list(self._deferred_heavy_warmup_series):
                if not sn:
                    continue
                if sn in self._zeta_boost_failed_series:
                    continue
                if self._is_series_in_memory_only(sn):
                    continue
                try:
                    if not self._is_series_header_consistent_for_warmup(sn):
                        self._warmup_corrupt_skip_counts[sn] = int(self._warmup_corrupt_skip_counts.get(sn, 0)) + 1
                        continue
                except Exception:
                    pass
                queue.append(sn)

            self._deferred_heavy_warmup_series.clear()
            self._deferred_heavy_warmup_retry_count = 0

            if not queue:
                return

            # Enqueue ALL heavy series at once. The engine's background
            # workers (2 parallel) will process them with proper
            # scheduling, respecting max_parallel_loads and lane priority.
            # Queue heavy in warmup lane (not background) so they start
            # immediately after light series, without waiting for the warmupâ†’
            # background lane transition.  Light series are already at the
            # front of the warmup queue (FIFO), so ordering is preserved.
            self.zeta_boost.enqueue_many_warmup(queue)
            print(
                f"ًںڑ€ [ZetaBoost][HEAVY_DEFER] batch-queued(warmup) study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                f"series={queue[:12]} count={len(queue)}"
            )
            self._log_warmup_coverage(stage="after_heavy_warmup_queued")
        except Exception as e:
            self.logger.debug(f"Error in deferred heavy warmup: {e}")

    def _log_warmup_coverage(self, stage: str = ""):
        """Verification snapshot: warmed/cached coverage for the current study."""
        try:
            if not hasattr(self.parent_widget, 'lst_thumbnails_data'):
                return

            candidates = []
            for item in self.parent_widget.lst_thumbnails_data or []:
                try:
                    sn = str(item.get('metadata', {}).get('series', {}).get('series_number', ''))
                    if sn and sn.isdigit():
                        candidates.append(sn)
                except Exception:
                    continue
            candidates = sorted(set(candidates), key=lambda x: int(x))
            if not candidates:
                return

            primary_series = None
            try:
                primary_series = str(
                    self.parent_widget.lst_thumbnails_data[0].get('metadata', {}).get('series', {}).get('series_number', '')
                )
            except Exception:
                primary_series = None

            full_cached = []
            preview_flagged = []
            loaded_not_cached = []
            failed = []
            missing = []

            for sn in candidates:
                if sn in self._zeta_boost_failed_series:
                    failed.append(sn)
                    continue

                # IMPORTANT: verification must not trigger disk loads or cache churn.
                if self._is_series_cached_non_mutating(sn):
                    full_cached.append(sn)
                    continue

                vtk_data, meta, _ = self._get_series_by_number_fast(sn)
                if self._is_full_volume_cache_candidate(sn, vtk_data, meta):
                    loaded_not_cached.append(sn)
                elif isinstance(meta, dict) and bool(meta.get('preview_only', False)):
                    preview_flagged.append(sn)
                else:
                    missing.append(sn)

            coverage_pct = (100.0 * len(full_cached) / len(candidates)) if candidates else 0.0
            print(
                f"ًں“Œ [ZetaBoost][VERIFY] stage={stage or 'n/a'} study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                f"total={len(candidates)} full_cached={len(full_cached)} loaded_not_cached={len(loaded_not_cached)} "
                f"preview_flagged={len(preview_flagged)} failed={len(failed)} missing={len(missing)} "
                f"coverage={coverage_pct:.1f}% primary={primary_series or 'n/a'}"
            )
            if preview_flagged:
                logger.debug(f"âڑ ï¸ڈ [ZetaBoost][VERIFY] preview_flagged_series={preview_flagged[:12]}")
            if missing:
                logger.debug(f"âڈ³ [ZetaBoost][VERIFY] not_warmed_series={missing[:12]}")
        except Exception as e:
            self.logger.debug(f"Error in warmup verification log: {e}")

    def _stop_background_prefetch(self):
        try:
            try:
                self.zeta_boost.clear_pending()
            except Exception:
                pass
            self._prefetch_stop_event.set()
            self._prefetch_inflight.clear()
            self._loading_series_numbers.clear()
            for _k, _evt in list(self._series_load_events.items()):
                try:
                    _evt.set()
                except Exception:
                    pass
            self._series_load_events.clear()
        except Exception:
            pass

    def clear_all_caches_for_close(self):
        """Hard cache purge for patient-tab close to avoid cross-tab memory retention."""
        try:
            self._stop_background_prefetch()
        except Exception:
            pass
        try:
            self.zeta_boost.clear_all()
        except Exception:
            pass
        try:
            self._load_coordinator.cancel_all()
        except Exception:
            pass
        try:
            self._preview_engine.clear()
        except Exception:
            pass
        try:
            self.pipeline.reset()
        except Exception:
            pass

        try:
            self._progressive_grow_timer.stop()
        except Exception:
            pass

        try:
            self._series_cache.clear()
            self._series_name_cache.clear()
            self._series_number_to_index.clear()
            self._paired_series_map.clear()
            self._metadata_flat_cache.clear()
            self._hot_series_cache.clear()
            self._viewer_batch_queue.clear()
            self._viewer_request_token.clear()
            self._preload_queue.clear()
            self._prefetch_inflight.clear()
            self._prefetch_loaded.clear()
            self._async_switch_inflight.clear()
            self._loading_series_numbers.clear()
            self._series_load_events.clear()

            self._first_use_prime_started = False
            self._interactive_load_in_progress = False
            self._zeta_boost_failed_series.clear()
            self._series_warmup_eligibility_cache.clear()
            self._deferred_heavy_warmup_series.clear()
            self._deferred_heavy_warmup_retry_count = 0
        except Exception:
            pass

    def _display_first_series_in_all_viewers(self, series_number: str, progressive_total: int = 0) -> bool:
        """Display the first downloaded series in all viewers."""
        try:
            series_number = self.parent_widget.resolve_series_key(series_number)
            vtk_image_data = None
            metadata = None
            series_idx = None

            for idx, data in enumerate(self.parent_widget.lst_thumbnails_data):
                if str(data.get('metadata', {}).get('series', {}).get('series_number')) == str(series_number):
                    vtk_image_data = data.get('vtk_image_data')
                    metadata = data.get('metadata')
                    series_idx = idx
                    break

            if vtk_image_data is None or metadata is None or series_idx is None:
                logger.debug(f"â‌Œ [FIRST DISPLAY] series {series_number} not found in thumbnail cache")
                return False

            if self.lst_nodes_viewer and self.selected_widget is None:
                first_node = self.lst_nodes_viewer[0]
                self.selected_widget = getattr(first_node, 'vtk_widget', None)
                self.parent_widget.slider = getattr(first_node, 'slider', None)

            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                slider = getattr(node, 'slider', None)
                if vtk_widget is None:
                    continue
                self._display_loaded_series(
                    series_number=series_number,
                    series_idx=series_idx,
                    vtk_image_data=vtk_image_data,
                    metadata=metadata,
                    flag_change_selected_widget=False,
                    vtk_widget=vtk_widget,
                    slider=slider,
                    progressive_total=progressive_total,
                )

            self._mark_first_series_displayed()
            # v2.2.3.2.6: Yield to Qt event loop after first-series viewer
            # init.  The VTK switch_series + Render for 2 viewers can take
            # 200-500ms on software OpenGL.  Queued scroll events and
            # subsequent series_downloaded signals are starving.  A single
            # processEvents lets pending wheel-scroll timers fire before
            # the next completion handler runs.
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass
            return True
        except Exception as e:
            self.logger.debug(f"Error displaying first series: {e}")
            return False

    def _display_first_series_in_primary_viewer(self, series_number: str, progressive_total: int = 0) -> bool:
        """Display the first downloaded series only in the primary viewer.

        FAST progressive first-display should avoid fanning the same partially
        downloaded series into every viewer. That duplicate startup work creates
        multiple bridge/pipeline/bootstrap paths for the exact same series even
        though only one viewer is needed to make the study interactive.
        """
        try:
            series_number = self.parent_widget.resolve_series_key(series_number)
            vtk_image_data = None
            metadata = None
            series_idx = None

            for idx, data in enumerate(self.parent_widget.lst_thumbnails_data):
                if str(data.get('metadata', {}).get('series', {}).get('series_number')) == str(series_number):
                    vtk_image_data = data.get('vtk_image_data')
                    metadata = data.get('metadata')
                    series_idx = idx
                    break

            if vtk_image_data is None or metadata is None or series_idx is None:
                logger.debug(f"⛔ [FIRST DISPLAY PRIMARY] series {series_number} not found in thumbnail cache")
                return False

            if not self.lst_nodes_viewer:
                return False

            first_node = self.lst_nodes_viewer[0]
            vtk_widget = getattr(first_node, 'vtk_widget', None)
            slider = getattr(first_node, 'slider', None)
            if vtk_widget is None:
                return False

            if self.selected_widget is None:
                self.selected_widget = vtk_widget
                self.parent_widget.slider = slider

            self._display_loaded_series(
                series_number=series_number,
                series_idx=series_idx,
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                flag_change_selected_widget=False,
                vtk_widget=vtk_widget,
                slider=slider,
                progressive_total=progressive_total,
            )

            self._mark_first_series_displayed()
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass
            logger.info(
                "first-display: primary viewer only series=%s progressive_total=%d",
                series_number,
                int(progressive_total or 0),
            )
            return True
        except Exception as e:
            self.logger.debug(f"Error displaying first series in primary viewer: {e}")
            return False

    def _display_loaded_series(self, series_number, series_idx, vtk_image_data, metadata,
                               flag_change_selected_widget, vtk_widget, slider,
                               progressive_total: int = 0):
        """
        âڑ، OPTIMIZED: Display series with O(1) paired series lookup.
        
        Performance improvements:
        - Fast paired series detection using index
        - No redundant list iterations
        - Caching-aware lookups
        """
        try:
            # Quick setup
            if flag_change_selected_widget and self.selected_widget is None:
                if self.lst_nodes_viewer:
                    self.selected_widget = self.lst_nodes_viewer[0].vtk_widget
                    self.parent_widget.slider = self.lst_nodes_viewer[0].slider
                else:
                    return

            # âڑ، FAST PAIRED SERIES LOOKUP: O(1)
            # Keep first-display pairing rules aligned with the main switch path:
            # only MG series may be paired/combined by shared series_name.
            vtk_widget_data_2 = None
            metadata_2 = None

            series_name = str(metadata.get('series', {}).get('series_name', ''))
            current_modality = str(metadata.get('series', {}).get('modality', '') or '').upper()
            is_mg_modality = current_modality == 'MG'

            if is_mg_modality and series_name in self._paired_series_map:
                paired_list = self._paired_series_map[series_name]
                for paired_num in paired_list:
                    if str(paired_num) != str(series_number):
                        vtk_data, meta, _ = self._get_series_by_number_fast(str(paired_num))
                        if vtk_data is not None and meta is not None:
                            paired_modality = str(meta.get('series', {}).get('modality', '') or '').upper()
                            if paired_modality == 'MG':
                                vtk_widget_data_2 = vtk_data
                                if hasattr(self, '_clone_metadata_for_switch'):
                                    metadata_2 = self._clone_metadata_for_switch(meta)
                                else:
                                    metadata_2 = meta
                                break

            if (not is_mg_modality) and series_name in self._paired_series_map:
                logger.debug(
                    "[PAIRED SKIP] first-display series=%s modality=%s - skipping paired lookup (MG only)",
                    series_number,
                    current_modality or 'UNKNOWN',
                )

            # Perform switch
            target_widget = self.selected_widget if flag_change_selected_widget else vtk_widget
            target_slider = self.parent_widget.slider if flag_change_selected_widget else slider

            # Attach pending action trace to the effective target widget if available.
            try:
                pending_action_id = getattr(self.parent_widget, '_pending_action_id', None)
                if pending_action_id and target_widget is not None and not getattr(target_widget, '_pending_action_id', None):
                    target_widget._pending_action_id = pending_action_id
                    pending_series = getattr(self.parent_widget, '_pending_action_series', None)
                    if pending_series is not None:
                        target_widget._pending_action_series = str(pending_series)
                    # consume once to avoid stale replay on subsequent switches
                    self.parent_widget._pending_action_id = None
                    self.parent_widget._pending_action_series = None
            except Exception:
                pass
            
            if hasattr(target_widget, 'switch_series'):
                flag_switch = target_widget.switch_series(
                    vtk_image_data, metadata, series_idx,
                    vtk_widget_data_2, metadata_2,
                    self.parent_widget.metadata_fixed,
                    progressive_total=int(progressive_total),
                )
                
                if flag_switch:
                    self.parent_widget.reset_slider(target_widget, target_slider)
                    self.parent_widget.toolbar_manager.turn_off_all_tools()
                    if (
                        getattr(target_widget, '_qt_bridge_active', False)
                        and hasattr(target_widget, '_sync_qt_viewer_presentation')
                        and not bool(getattr(target_widget, '_qt_switch_refit_applied', False))
                    ):
                        QTimer.singleShot(
                            0,
                            lambda tw=target_widget: tw._sync_qt_viewer_presentation(refit_view=True),
                        )
                    elif (not getattr(target_widget, '_qt_bridge_active', False)) and hasattr(target_widget, 'resizeEvent'):
                        target_widget.resizeEvent(None)
                    if hasattr(target_widget, 'image_viewer') and target_widget.image_viewer:
                        target_widget.image_viewer.update_corners_actors()
                    # Reference lines must be recalculated after every series change
                    try:
                        self.parent_widget.manage_reference_line()
                    except Exception:
                        pass
                    try:
                        self._hide_spinner_for_widget(target_widget)
                    except Exception:
                        pass
        
        except Exception as e:
            self.logger.debug(f"Error displaying series: {e}")

    def _create_fallback_viewer(self):
        """Create dummy viewer for missing data - with full error handling"""
        try:
            from PacsClient.pacs.patient_tab.utils import NodeViewer

            logger.debug("   ًں“‌ [Fallback] Creating layout...")
            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)

            logger.debug("   ًں–¼ï¸ڈ [Fallback] Creating container...")
            container = QFrame()
            container.setLayout(layout)

            logger.debug("   ًںژ¨ [Fallback] Creating dummy VTK widget...")
            vtk_widget = self.create_dummy_vtk_widget()
            if vtk_widget is None:
                raise RuntimeError("create_dummy_vtk_widget failed")

            logger.debug("    ًں“ٹ [Fallback] Creating slider...")
            slider = QSlider(Qt.Vertical)

            logger.debug("   ًں”— [Fallback] Creating NodeViewer...")
            node = NodeViewer(container, vtk_widget, slider)
            if node is None:
                raise RuntimeError("NodeViewer creation failed")

            logger.debug("   âœ… [Fallback] Fallback viewer created successfully")
            return node

        except Exception as e:
            logger.error(f"   â‌Œ [Fallback] Error creating fallback viewer: {e}")
            self.logger.error(f"Fallback viewer creation failed: {e}", exc_info=True)
            return None

    def create_some_viewers(self, count):
        last_viewer_index = 0
        for i in range(count):
            try:
                # it's means we have series at enough
                self.new_viewer(i)
                last_viewer_index = i
            except:
                # we don't have series at enough. so we create from last series until row * col
                self.new_viewer(last_viewer_index)

    def cleanup_all_viewers(self):
        """طھظ…غŒط²â€Œع©ط±ط¯ظ† ط¨ظ‡غŒظ†ظ‡ظ” viewers ظˆ resources"""
        try:
            self._stop_background_prefetch()

            # Clean up VTK layout
            if hasattr(self.parent_widget, 'vtk_layout'):
                try:
                    delete_widgets_in_layout(self.parent_widget.vtk_layout)
                except:
                    pass

            # Clean up viewer nodes efficiently
            if hasattr(self, 'lst_nodes_viewer'):
                for node in list(self.lst_nodes_viewer):  # Use list() to avoid modification during iteration
                    try:
                        node: NodeViewer
                        vtk_widget: VTKWidget = getattr(node, 'vtk_widget', None)
                        if vtk_widget is not None and hasattr(vtk_widget, 'cleanup_image_viewer'):
                            try:
                                vtk_widget.cleanup_image_viewer()
                            except:
                                pass

                        # Safe cleanup: keep attributes but null them out to avoid AttributeError races
                        for attr in ('vtk_widget', 'widget', 'slider'):
                            try:
                                if hasattr(node, attr):
                                    setattr(node, attr, None)
                            except:
                                pass
                    except Exception as e:
                        self.logger.debug(f"Error cleaning up viewer node: {e}")

            # Clear caches to free memory - ط§ظ…ط§ ط¨ط§ ط§ط­طھغŒط§ط·
            if hasattr(self, '_series_cache'):
                self._series_cache.clear()
            if hasattr(self, '_series_name_cache'):
                self._series_name_cache.clear()
            if hasattr(self, '_viewer_batch_queue'):
                self._viewer_batch_queue.clear()
            if hasattr(self, '_viewer_request_token'):
                self._viewer_request_token.clear()
            if hasattr(self, '_prefetch_loaded'):
                self._prefetch_loaded.clear()
            if hasattr(self, '_series_load_events'):
                self._series_load_events.clear()

            self._render_batch_pending = False

            # v2.2.3.2.3: Kill warmup subprocess on tab close
            try:
                self._shutdown_warmup_subprocess()
            except Exception:
                pass

            # Stop live block telemetry heartbeat before tearing down shared state.
            try:
                timer = getattr(self, '_block_diag_timer', None)
                if timer is not None:
                    timer.stop()
            except Exception:
                pass

            # Ensure stale nodes are cleared after cleanup
            try:
                self.lst_nodes_viewer.clear()
            except Exception:
                pass

            # Unregister orchestrator from the shared throttle facade
            try:
                _clear_active_orchestrator(getattr(self, 'pipeline', None))
            except Exception:
                pass

            logger.debug("âœ… cleanup_all_viewers completed")
        except Exception as e:
            self.logger.error(f"Error in cleanup_all_viewers: {e}")

    def _load_series_preview_async(self, series_number: str, study_path: str) -> tuple:
        """
        Load preview (5-10 slices) for rapid display on drag & drop.
        
        Returns: (vtk_preview_data, metadata) or (None, None) on failure
        
        ظپط§غŒط¯ظ‡: ظ†ظ…ط§غŒط´ ظپظˆط±غŒ toggleظھ20ms طھط§ ط­ط§ظ„غŒ ع©ظ‡ full volume ظ…ظˆط§ط²غŒ ط¨ط§ط±ع¯ط°ط§ط±غŒ ظ…غŒâ€Œط´ظˆط¯
        """
        try:
            _preview_start = time.perf_counter()
            
            # ط³ط±غŒط¹ ظ…ط­ط§ط³ط¨ظ‡: ط¢غŒط§ ظ‚ط¨ظ„ط§ظ‹ ط«ط§ط¨طھ ع©ط§ط´ ط¯ط§ط±غŒظ…طں
            try:
                vtk_full, meta_full, _ = self._get_series_by_number_fast(str(series_number))
                if self._is_full_volume_cache_candidate(str(series_number), vtk_full, meta_full):
                    _ms = (time.perf_counter() - _preview_start) * 1000
                    logger.debug(f"âڑ، [PREVIEW] series={series_number} cached_full {_ms:.0f}ms")
                    return vtk_full, meta_full
            except Exception:
                pass
            
            # ط³ط±غŒط² ط§ط² disk ع©ط´ غŒط§ source ط¨ط§ط±ع¯ط°ط§ط±غŒ ع©ظ†
            from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview

            preview = load_series_preview(
                study_path=study_path,
                series_number=int(series_number),
                patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                max_files=(self._interactive_preview_file_cap() if hasattr(self, '_interactive_preview_file_cap') else 8),
            )

            if not preview:
                _elapsed = (time.perf_counter() - _preview_start) * 1000
                logger.error(f"âڑ ï¸ڈ [PREVIEW] series={series_number} failed {_elapsed:.0f}ms")
                return None, None

            vtk_preview, metadata, _patient_info, _total_files = preview
            
            _elapsed = (time.perf_counter() - _preview_start) * 1000
            if vtk_preview is not None:
                logger.debug(f"âڑ، [PREVIEW] series={series_number} loaded {_elapsed:.0f}ms")
                return vtk_preview, metadata
            else:
                logger.error(f"âڑ ï¸ڈ [PREVIEW] series={series_number} failed {_elapsed:.0f}ms")
                return None, None
                
        except Exception as e:
            logger.debug(f"âڑ ï¸ڈ [PREVIEW] exception: {e}")
            return None, None

    def _prefetch_adjacent_series(self, current_series_number: str):
        """
        ظ¾غŒط´â€Œط¨غŒظ†غŒ ط³ط±غŒط²â€Œظ‡ط§غŒ ظ…ط¬ط§ظˆط± ظˆ queue ط¨ط±ط§غŒ warmup lane.
        
        ط§غŒظ† ظ…طھط¯ ظ…ظˆط§ط²غŒâ€Œط·ظˆط±غŒ ط§ط¬ط±ط§ ظ…غŒâ€Œط´ظˆط¯طŒ ط¨ظ†ط§ط¨ط±ط§غŒظ† drag & drop ط¨ط¹ط¯غŒ
        < 50ms (cache hit) ط®ظˆط§ظ‡ط¯ ط¨ظˆط¯.
        """
        try:
            current_idx = None
            thumbs = getattr(self.parent_widget, 'lst_thumbnails_data', []) or []
            
            # ظ¾غŒط¯ط§ ع©ط±ط¯ظ† index ط³ط±غŒط² ط¬ط§ط±غŒ
            for idx, item in enumerate(thumbs):
                sn = str(item.get('metadata', {}).get('series', {}).get('series_number', '') or '')
                if sn == str(current_series_number):
                    current_idx = idx
                    break
            
            if current_idx is None:
                return
            
            # Prefetch immediate neighbors (next two series).
            prefetch_indices = []
            for offset in [1, 2]:
                candidate_idx = current_idx + offset
                if 0 <= candidate_idx < len(thumbs):
                    prefetch_indices.append(candidate_idx)
            
            queued_count = 0
            for idx in prefetch_indices:
                item = thumbs[idx]
                sn = str(item.get('metadata', {}).get('series', {}).get('series_number', '') or '')
                if not sn or sn in {str(current_series_number)}:
                    continue
                
                # Skip ط§ع¯ط± ظ‚ط¨ظ„ط§ظ‹ queued غŒط§ in-memory
                if self.zeta_boost.has_in_memory(sn):
                    continue
                
                # Queue ط¨ط±ط§غŒ warmup lane (ط¨ط¯ظˆظ† blocking interactive)
                try:
                    self.zeta_boost.enqueue(sn, lane="warmup")
                    queued_count += 1
                except Exception:
                    pass
            
            if queued_count > 0:
                logger.debug(f"ًں”¥ [PREFETCH] series={current_series_number} queued={queued_count} adjacent")
                
        except Exception as e:
            logger.error(f"âڑ ï¸ڈ [PREFETCH] error: {e}")

    def _any_viewer_empty(self) -> bool:
        """Return True if any viewer has not been initialized with image data."""
        try:
            if not self.lst_nodes_viewer:
                return True
            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                if vtk_widget is None:
                    return True
                if getattr(vtk_widget, 'image_viewer', None) is None:
                    return True
                try:
                    if vtk_widget.get_count_of_slices() == 0:
                        return True
                except Exception:
                    return True
            return False
        except Exception:
            return True



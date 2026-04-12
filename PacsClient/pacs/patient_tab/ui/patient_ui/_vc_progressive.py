"""
Progressive display mixin for ViewerController.
Handles incremental viewer updates during series download.
"""
from __future__ import annotations
import asyncio
import threading
import time
from PySide6.QtCore import QTimer
from modules.zeta_boost import ImageSliceBooster
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
import logging

logger = logging.getLogger(__name__)


def _h10_log_progressive_mutation(obj, fn_name: str, mutated_sn: str, action: str):
    """[H10-4] Module-level helper â€” log progressive lifecycle mutation with context."""
    try:
        _vsn = '?'
        for _n in (getattr(obj, 'lst_nodes_viewer', None) or []):
            _vw = getattr(_n, 'vtk_widget', None)
            if _vw is not None:
                _vsn = str(getattr(getattr(_vw, 'image_viewer', None), 'metadata', {}).get('series', {}).get('series_number', '?'))
                break
        _dm = getattr(obj, '_h10_dm_active_series', getattr(getattr(obj, 'parent_widget', None), '_h10_dm_active_series', '?'))
        _prog_keys = list(getattr(obj, '_progressive_series', {}).keys())
        _done = list(getattr(obj, '_progressive_display_done', set()))
        logger.info(
            "[H10-4] fn=%s action=%s sn=%s viewer_series=%s dm_active=%s prog_keys=%s done=%s",
            fn_name, action, mutated_sn, _vsn, _dm, _prog_keys, _done,
        )
    except Exception:
        pass


class _VCProgressiveMixin:
    """Auto-split mixin â€” see patient_widget_viewer_controller.py for history."""

    def on_series_images_progress(self, series_number: str, downloaded: int, total: int):
        """Qt signal slot: outer guard so exceptions never escape into Qt dispatch.

        Any unhandled exception in a Qt signal slot causes Qt's C++ abort() â€” a
        hard exit with no Python traceback that orphans the download subprocess.
        The real implementation is in ``_on_series_images_progress_impl``.
        """
        try:
            self._on_series_images_progress_impl(series_number, downloaded, total)
        except Exception as exc:
            try:
                viewer_count = len(self._find_progressive_viewers(str(series_number)))
            except Exception:
                viewer_count = -1
            try:
                fast_mode = self._is_fast_viewer_mode()
            except Exception:
                fast_mode = "?"
            self.logger.error(
                "progressive: unhandled error in on_series_images_progress "
                "series=%s downloaded=%d total=%d viewer_count=%d fast_mode=%s: %s",
                series_number, downloaded, total, viewer_count, fast_mode,
                exc, exc_info=True,
            )

    def _on_series_images_progress_impl(self, series_number: str, downloaded: int, total: int):
        """Called when new images for a series have been downloaded.

        Triggers progressive display: first batch opens the viewer, subsequent
        batches grow the volume in-place so the user sees progress live.

        Only active in FAST (PyDicom) mode.  In Advanced (VTK) mode the full
        series must be downloaded before display â€” series_downloaded handles that.

        Throttled to max once per 100ms per series to avoid CPU spikes when
        progress signals fire rapidly (one per downloaded file).
        """
        sn = str(series_number)
        if total <= 0 or downloaded <= 0:
            return

        # Advanced (VTK) mode: skip progressive display entirely.
        # The series will be loaded once via series_downloaded signal.
        if not self._is_fast_viewer_mode():
            return

        # H6 defense-in-depth: reject late progress signals for series that
        # have already completed.  Without this, late DM signals could
        # re-create _progressive_series tracking for a finished series.
        if sn in getattr(self, '_series_download_completed', set()):
            logger.info(
                "[H7-P7] series=%s downloaded=%d total=%d action=rejected_H6_completed",
                sn, downloaded, total,
            )
            return

        # [H7-P7] Entry log â€” captures all guard states at entry
        _done_set = getattr(self, '_progressive_display_done', set())
        _inflight_set = getattr(self, '_progressive_display_inflight', set())
        _viewers_prog = []
        _viewers_nonprog = []
        for _n in (self.lst_nodes_viewer or []):
            _vw = getattr(_n, "vtk_widget", None)
            if _vw is None:
                continue
            try:
                _vsn = str(
                    getattr(_vw.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                _vsn = ""
            if _vsn == sn:
                if _vw._progressive_mode:
                    _viewers_prog.append(_vsn)
                else:
                    _viewers_nonprog.append(_vsn)
        logger.info(
            "[H7-P7] series=%s downloaded=%d total=%d fast_mode=True "
            "in_completed_set=False in_done_set=%s in_inflight_set=%s "
            "in_progressive_series=%s viewers_prog=%d viewers_nonprog=%d",
            sn, downloaded, total,
            sn in _done_set, sn in _inflight_set,
            sn in self._progressive_series,
            len(_viewers_prog), len(_viewers_nonprog),
        )

        # Track this series for progressive updates
        if sn not in self._progressive_series:
            self._progressive_series[sn] = {"total": total, "last_grow_count": 0, "last_signal_ms": 0}
            _h10_log_progressive_mutation(self, 'on_series_images_progress_impl', sn, 'add_key')
        info = self._progressive_series[sn]
        info["total"] = max(info["total"], total)

        # â”€â”€ Throttle: skip if called less than 250ms ago for this series
        #    (always process 'download complete' signals though) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        now_ms_val = time.monotonic() * 1000
        if downloaded < total and (now_ms_val - info.get("last_signal_ms", 0)) < 100:
            return
        info["last_signal_ms"] = now_ms_val

        # Check if a viewer is already displaying this series in progressive mode
        viewers_showing = self._find_progressive_viewers(sn)
        if viewers_showing:
            # Only grow when enough NEW images arrived (batch boundary)
            delta = downloaded - info["last_grow_count"]
            if delta >= self._progressive_grow_batch_size or downloaded >= total:
                info["pending_downloaded"] = downloaded
                if not self._progressive_grow_timer.isActive():
                    self._progressive_grow_timer.start()
            return

        # Check if a viewer already shows this series (non-progressive, e.g. the
        # user drag-dropped during an active download so change_series_on_viewer
        # loaded whatever files were on disk at that moment without entering
        # progressive mode).  Two sub-cases:
        #
        #   downloaded < total  â€” still downloading: activate progressive mode
        #                         retroactively so future grow ticks will fire.
        #   downloaded >= total â€” download just completed: the last N images may
        #                         have all arrived in one batch so no intermediate
        #                         signal could activate progressive mode.  Do a
        #                         single final grow immediately to expose those
        #                         images.  The "live connection" between viewer
        #                         and download ends here â€” no more signals come.
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None or vtk_w._progressive_mode:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn != sn:
                continue

            if downloaded < total:
                # Still downloading â€” activate progressive mode retroactively
                avail = vtk_w.image_viewer.get_count_of_slices() if vtk_w.image_viewer else 0
                vtk_w.enter_progressive_mode(total, sn)
                vtk_w.update_available_slice_count(avail)
                slider = getattr(node, "slider", None)
                if slider is not None:
                    try:
                        slider.blockSignals(True)
                        slider.setMaximum(max(0, total - 1))
                        slider.blockSignals(False)
                    except Exception:
                        pass
                # Fast mode: activate آ±20 booster for the active series
                if self._is_fast_viewer_mode():
                    try:
                        loader = getattr(vtk_w, "_lazy_loader", None)
                        backend = getattr(loader, "backend", None) if loader is not None else None
                        if backend is not None:
                            paths = backend.get_file_paths()
                            if paths:
                                self._image_slice_booster.set_active(sn, paths, center_slice=0)
                    except Exception:
                        pass
                info["last_grow_count"] = avail
                self.logger.info(
                    "progressive: retroactive activate series=%s avail=%d total=%d",
                    sn, avail, total,
                )
            else:
                # Download COMPLETE â€” one-shot final grow so the viewer shows
                # all downloaded images (covers the "last batch arrived at once"
                # scenario that bypassed retroactive activation).
                self.logger.info(
                    "progressive: one-shot final grow series=%s downloaded=%d total=%d",
                    sn, downloaded, total,
                )
                self._grow_progressive_fast(sn, downloaded, [(vtk_w, node)])
            return  # Handled â€” exit after first matching viewer

        # No viewer showing this series yet â€” start first progressive display.
        # Guard: only trigger once per series to avoid spawning dozens of
        # concurrent load tasks that spike CPU.
        # _progressive_display_done persists beyond inflight to prevent re-entry
        # when the series download completes (downloaded==total) after the first
        # progressive display already succeeded.

        # Check for viewers awaiting this series (drag-drop while download
        # was still in progress â€” spinner is already visible).
        _awaiting_viewer = None
        _awaiting_node = None
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            if getattr(vtk_w, "_awaiting_series_number", None) == sn:
                _awaiting_viewer = vtk_w
                _awaiting_node = node
                break

        if downloaded >= self._progressive_grow_batch_size:
            done = getattr(self, '_progressive_display_done', None)
            if done is None:
                self._progressive_display_done = set()
                done = self._progressive_display_done
            if sn in done:
                # Already displayed once â€” grow path should handle updates.
                # Defensive: if progressive mode was lost (e.g. race between
                # threaded done.add and activation, or switch_series skipped
                # progressive entry), re-enter progressive mode so the grow
                # path works on the next signal.
                if downloaded < total:
                    for node in self.lst_nodes_viewer or []:
                        vtk_w = getattr(node, "vtk_widget", None)
                        if vtk_w is None or vtk_w._progressive_mode:
                            continue
                        try:
                            viewer_sn = str(
                                getattr(vtk_w.image_viewer, "metadata", {})
                                .get("series", {}).get("series_number", "")
                            )
                        except Exception:
                            viewer_sn = ""
                        if viewer_sn == sn:
                            avail = vtk_w.get_count_of_slices()
                            vtk_w.enter_progressive_mode(total, sn)
                            vtk_w.update_available_slice_count(avail)
                            info["last_grow_count"] = avail
                            self.logger.info(
                                "progressive: re-activated series=%s avail=%d (done-guard recovery)",
                                sn, avail,
                            )
                            return  # Will grow on next progress signal
                # downloaded < total but no viewer found â€” nothing further to do
                if downloaded < total:
                    return
                # downloaded >= total â€” completion signal.  If progressive mode was
                # exited prematurely (e.g. stale-grow exhaustion at fewer slices),
                # fire a one-shot grow so the viewer reaches the full file count.
                for _node in self.lst_nodes_viewer or []:
                    _vtk_w = getattr(_node, "vtk_widget", None)
                    if _vtk_w is None or _vtk_w._progressive_mode:
                        continue  # skip progressive viewers â€” handled by normal grow path
                    try:
                        _viewer_sn = str(
                            getattr(_vtk_w.image_viewer, "metadata", {})
                            .get("series", {}).get("series_number", "")
                        )
                    except Exception:
                        _viewer_sn = ""
                    if _viewer_sn != sn:
                        continue
                    _current_count = _vtk_w.get_count_of_slices()
                    if _current_count >= downloaded:
                        continue  # already showing full count â€” no action needed
                    self.logger.info(
                        "progressive: done-guard completion one-shot series=%s current=%d downloaded=%d",
                        sn, _current_count, downloaded,
                    )
                    _ps_info = self._progressive_series.get(sn)
                    if _ps_info is None:
                        self._progressive_series[sn] = {
                            "total": total,
                            "last_grow_count": _current_count,
                            "last_signal_ms": 0,
                            "pending_downloaded": downloaded,
                        }
                        _h10_log_progressive_mutation(self, 'done_guard_completion_oneshot', sn, 'add_key')
                    else:
                        _ps_info["pending_downloaded"] = downloaded
                        _ps_info["total"] = total
                    _viewers_shot = self._find_progressive_viewers(sn)
                    if not _viewers_shot:
                        # Re-enter progressive mode so _grow_progressive_fast locates the viewer
                        _vtk_w.enter_progressive_mode(total, sn)
                        _vtk_w.update_available_slice_count(_current_count)
                        _viewers_shot = [(_vtk_w, _node)]
                    self._grow_progressive_fast(sn, downloaded, _viewers_shot)
                    return
                # No viewer needs a grow for this completed series â€” nothing to do.
                # IMPORTANT: do NOT fall through to the inflight block below; that
                # would restart _start_progressive_display for an already-done series.
                return

            inflight = getattr(self, '_progressive_display_inflight', None)
            if inflight is None:
                self._progressive_display_inflight = set()
                inflight = self._progressive_display_inflight
            if sn not in inflight:
                inflight.add(sn)
                self._start_progressive_display(
                    sn, downloaded, total,
                    target_vtk_widget=_awaiting_viewer,
                    target_node=_awaiting_node,
                )

    def _find_progressive_viewers(self, series_number: str):
        """Find all VTK widgets currently in progressive mode for a series."""
        result = []
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            if (vtk_w._progressive_mode
                    and vtk_w._progressive_series_number == str(series_number)):
                result.append((vtk_w, node))
        return result

    def _start_progressive_display(self, series_number: str, downloaded: int, total: int,
                                    target_vtk_widget=None, target_node=None):
        """Display a partially downloaded series for the first time.

        If *target_vtk_widget* / *target_node* are provided, the first batch
        is loaded directly into that specific viewer (used when the user
        drag-dropped a series that wasn't on disk yet â€” the viewer is already
        showing a spinner waiting for this series).
        """
        self.logger.info(
            "progressive: START first display series=%s downloaded=%d total=%d target_viewer=%s",
            series_number, downloaded, total,
            getattr(target_vtk_widget, 'id_vtk_widget', None) if target_vtk_widget else None,
        )
        self._progressive_series.setdefault(series_number, {
            "total": total, "last_grow_count": 0,
        })

        # Ensure import_folder_path is set â€” during download the PatientWidget
        # may have been created before any files existed on disk.
        study_path = self._ensure_import_folder_path()
        if not study_path:
            self.logger.error(
                "progressive: cannot start series=%s â€” no valid study path",
                series_number,
            )
            inflight = getattr(self, '_progressive_display_inflight', None)
            if inflight is not None:
                inflight.discard(series_number)
            return

        async def _load_and_show():
            try:
                await self._async_load_and_display_series(
                    series_number,
                    progressive_total=total,
                )
                # If a specific target viewer was awaiting this series,
                # switch it to show the loaded data and hide the spinner.
                if target_vtk_widget is not None:
                    self._apply_progressive_to_target_viewer(
                        series_number, total, target_vtk_widget, target_node,
                    )
                # Mark done so on_series_images_progress won't re-start
                done = getattr(self, '_progressive_display_done', None)
                if done is not None:
                    done.add(series_number)
                    _h10_log_progressive_mutation(self, '_start_progressive_display', series_number, 'done_add')
            except Exception as e:
                self.logger.warning("progressive: first display failed: %s", e)
            finally:
                # Clear inflight guard so the series can be retried if needed
                inflight = getattr(self, '_progressive_display_inflight', None)
                if inflight is not None:
                    inflight.discard(series_number)

        try:
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(_load_and_show())
            self.parent_widget._background_tasks.add(task)
            task.add_done_callback(lambda t: self.parent_widget._background_tasks.discard(t))
        except RuntimeError:
            # No running asyncio loop â€” schedule via thread + QTimer callback
            self.logger.warning(
                "progressive: no asyncio loop â€” falling back to threaded load series=%s",
                series_number,
            )
            import threading

            def _threaded_load():
                try:
                    ok = self._load_single_series_on_demand(
                        int(series_number), study_path=study_path,
                    )
                    if ok:
                        _sn_local = str(series_number)
                        _total_local = total
                        _target_vw = target_vtk_widget
                        _target_nd = target_node

                        def _display_activate_and_mark_done():
                            """Display, activate progressive mode, THEN mark done.

                            Previously done.add() ran from the background thread
                            before these callbacks fired, causing a race where
                            subsequent progress signals hit the done-guard before
                            progressive mode was entered â€” killing the grow path.

                            H6 fix (v2.2.9.3): guard against post-completion
                            re-entry.  If the series completed while the threaded
                            load was running, this callback fires AFTER the
                            completion handler cleaned up.  Without this guard,
                            enter_progressive_mode re-enters progressive state on
                            a completed series â†’ crash during scroll.
                            Also wrapped in try/except so no exception can escape
                            to Qt's C++ dispatch (H6b â€” unguarded QTimer closure).
                            """
                            try:
                                # H6 guard: skip if series already completed
                                completed = getattr(self, '_series_download_completed', None)
                                if completed is not None and _sn_local in completed:
                                    self.logger.info(
                                        "progressive: skipping late activation for "
                                        "completed series=%s", _sn_local,
                                    )
                                    return
                                # If a specific viewer was awaiting this series (drag-drop
                                # before data existed), switch that viewer directly.
                                if _target_vw is not None:
                                    self._apply_progressive_to_target_viewer(
                                        _sn_local, _total_local, _target_vw, _target_nd,
                                    )
                                else:
                                    self._display_series_after_load(
                                        _sn_local, progressive_total=_total_local,
                                    )
                                self._activate_progressive_mode_on_viewers(
                                    _sn_local, _total_local,
                                )
                                # Mark done AFTER activation so grow path is reachable
                                done = getattr(self, '_progressive_display_done', None)
                                if done is not None:
                                    done.add(_sn_local)
                                    _h10_log_progressive_mutation(self, '_start_progressive_display_threaded', _sn_local, 'done_add')
                            except Exception as _cb_exc:
                                self.logger.error(
                                    "progressive: _display_activate_and_mark_done "
                                    "failed series=%s: %s",
                                    _sn_local, _cb_exc, exc_info=True,
                                )

                        QTimer.singleShot(0, _display_activate_and_mark_done)
                except Exception as exc:
                    self.logger.warning("progressive: threaded fallback failed: %s", exc)
                finally:
                    inflight = getattr(self, '_progressive_display_inflight', None)
                    if inflight is not None:
                        inflight.discard(series_number)

            thread = threading.Thread(
                target=_threaded_load,
                name="progressive-load-" + str(series_number),
                daemon=True,
            )
            thread.start()

    def _flush_progressive_grow(self):
        """Timer callback: grow all progressive viewers with newly downloaded images."""
        try:
            self._flush_progressive_grow_impl()
        except Exception as exc:
            self.logger.error(
                "progressive: unhandled error in _flush_progressive_grow: %s",
                exc, exc_info=True,
            )

    def _flush_progressive_grow_impl(self):
        """Inner implementation called by _flush_progressive_grow."""
        is_fast = self._is_fast_viewer_mode()

        for sn, info in list(self._progressive_series.items()):
            pending = info.get("pending_downloaded", 0)
            last_grow = info.get("last_grow_count", 0)
            if pending <= last_grow:
                continue  # nothing new to process
            total = info.get("total", 0)
            viewers = self._find_progressive_viewers(sn)
            if not viewers:
                continue

            if is_fast:
                # Fast mode: refresh backend file list + update available count
                # (no VTK volume reconstruction needed).
                # Guard: prevent exceptions from escaping the QTimer callback.
                # One-time-per-series traceback log avoids 150ms log spam.
                try:
                    self._grow_progressive_fast(sn, pending, viewers)
                    # Clear flags on success so a future re-occurrence is fully logged
                    info.pop("_grow_error_logged", None)
                    info.pop("_grow_error_count", None)
                except Exception as exc:
                    err_count = info.get("_grow_error_count", 0) + 1
                    info["_grow_error_count"] = err_count
                    _GROW_ERROR_MAX = 5
                    if not info.get("_grow_error_logged"):
                        info["_grow_error_logged"] = True
                        self.logger.error(
                            "progressive: _grow_progressive_fast failed series=%s: %s",
                            sn, exc, exc_info=True,
                        )
                    else:
                        self.logger.warning(
                            "progressive: _grow_progressive_fast still failing series=%s (%d/%d): %s",
                            sn, err_count, _GROW_ERROR_MAX, exc,
                        )
                    if err_count >= _GROW_ERROR_MAX:
                        # Bounded retry: after N consecutive failures, equalize
                        # pending to last_grow_count so the safety-net below
                        # does NOT re-arm the timer.  Prevents infinite storm.
                        info["pending_downloaded"] = info.get("last_grow_count", 0)
                        self.logger.error(
                            "progressive: grow retry exhausted series=%s after %d failures, "
                            "stopping timer re-arm",
                            sn, err_count,
                        )
            else:
                # Advanced (VTK) mode: reload from disk + grow VTK volume in-place
                async def _grow(series_number=sn, count=pending):
                    try:
                        await self._grow_progressive_viewer_async(series_number, count)
                    except Exception as e:
                        self.logger.warning("progressive: grow failed series=%s: %s", series_number, e)

                try:
                    loop = asyncio.get_running_loop()
                    task = asyncio.create_task(_grow())
                    self.parent_widget._background_tasks.add(task)
                    task.add_done_callback(lambda t: self.parent_widget._background_tasks.discard(t))
                except RuntimeError:
                    pass

        # Stale-grow safety net: restart the single-shot timer if any tracked
        # series still has pending_downloaded > last_grow_count after this
        # tick.  Prevents permanent "stuck" state when loader.grow() returned
        # a stale file count (OS flush delay) and closed the timer.
        if any(
            info.get("pending_downloaded", 0) > info.get("last_grow_count", 0)
            for info in self._progressive_series.values()
        ):
            if not self._progressive_grow_timer.isActive():
                self._progressive_grow_timer.start()

    def _grow_progressive_fast(self, series_number: str, pending_count: int,
                               viewers: list):
        """Fast mode growth: refresh PyDicom backend file list & update counts.

        Unlike the VTK path, no volume reconstruction is needed.  The PyDicom
        lazy backend already serves slices on-demand from disk.  We only need
        to tell it about new files so ``get_slice_count()`` returns the correct
        value, and update the ImageSliceBooster paths if the series is active.

        Also updates lst_thumbnails_data metadata so that re-dropping the series
        into another viewer will see the full file count (fixes stuck-slice bug).
        """
        info = self._progressive_series.get(series_number, {})
        total = info.get("total", 0)

        for vtk_w, node in viewers:
            new_count = pending_count  # fallback
            try:
                # 1. Refresh the PyDicom backend file list + grow lazy volume.
                #
                # IMPORTANT: call loader.grow() FIRST without pre-calling
                # backend.refresh_file_list() separately.  grow() snapshots
                # old_paths BEFORE refreshing, so it can correctly build the
                # old-index â†’ new-index remap for interleaved DICOM series.
                # Pre-calling refresh_file_list() here poisons that snapshot,
                # causing decoded pixels to land at wrong memmap positions when
                # instance numbers interleave across download batches.
                loader = getattr(vtk_w, "_lazy_loader", None)
                backend = getattr(loader, "backend", None) if loader is not None else None
                if loader is not None and hasattr(loader, "grow"):
                    # PyDicom lazy backend: grow() handles refresh + remap internally
                    try:
                        new_count = loader.grow()
                    except Exception as grow_exc:
                        self.logger.error(
                            "progressive-fast: loader.grow() failed series=%s: %s",
                            series_number, grow_exc,
                        )
                        raise
                    # v2.2.8.2: After grow(), the lazy volume's vtk_image_data now has
                    # new_count slices, but ImageReslice.SetOutputExtent() was set at
                    # construction time with the original (smaller) Z extent.  VTK's
                    # vtkResliceImageViewer clamps SetSlice(n) to the output extent max,
                    # so slices >= old_count are silently rendered as old_count-1.
                    # Fix: re-derive the output extent from the updated input dimensions.
                    # If preprocessing (e.g. CT XY-upsample) created a different object,
                    # reconnect reslice input to loader.vtk_image_data which has all slices.
                    try:
                        _iv = getattr(vtk_w, "image_viewer", None)
                        _reslice = getattr(_iv, "image_reslice", None) if _iv is not None else None
                        if _reslice is not None:
                            _raw_vtkdata = getattr(loader, "vtk_image_data", None)
                            _reslice_input = getattr(_reslice, "vtk_image_data", None)
                            if (_raw_vtkdata is not None and _reslice_input is not None
                                    and _reslice_input is not _raw_vtkdata):
                                # Preprocessing created a separate copy (e.g. CT upsample).
                                # Reconnect so the new slices in loader.vtk_image_data are
                                # reachable by the reslice pipeline.
                                _reslice.SetInputData(_raw_vtkdata)
                                _reslice.vtk_image_data = _raw_vtkdata
                            # Update output extent from current input dimensions (new_count).
                            if hasattr(_reslice, "_configure_output_from_input"):
                                _reslice._configure_output_from_input()
                            _reslice.Modified()
                            _reslice.Update()
                    except Exception as _reslice_exc:
                        self.logger.debug(
                            "progressive-fast: reslice extent update failed: %s", _reslice_exc
                        )
                elif backend is not None and hasattr(backend, "refresh_file_list"):
                    # Lazy loader without grow() â€“ fallback to direct backend refresh
                    new_count = backend.refresh_file_list()
                    if loader is not None and hasattr(loader, "slice_count"):
                        loader.slice_count = new_count
                elif getattr(vtk_w, "_qt_bridge_active", False):
                    # Qt bridge (PYDICOM_QT): grow the pipeline's file list so
                    # _slice_count on the bridge stays in sync with downloaded
                    # files.  Without this the bridge clamps set_slice() to the
                    # original batch size and the image appears "stuck".
                    bridge = getattr(vtk_w, "image_viewer", None)
                    if bridge is not None and hasattr(bridge, "grow"):
                        new_count = bridge.grow()
            except Exception as exc:
                self.logger.debug("progressive-fast: refresh_file_list/grow failed: %s", exc)

            # 2+3. Update slice count and slider max
            self._update_vtk_slice_range(vtk_w, node, new_count)

            # 4. Update ImageSliceBooster paths if active for this series
            try:
                loader = getattr(vtk_w, "_lazy_loader", None)
                backend = getattr(loader, "backend", None) if loader is not None else None
                if backend is not None:
                    updated_paths = backend.get_file_paths()
                else:
                    updated_paths = []
                if updated_paths and self._image_slice_booster.active_series == series_number:
                    self._image_slice_booster.update_paths(series_number, updated_paths)
            except Exception as exc:
                self.logger.debug("progressive-fast: booster update_paths failed: %s", exc)

        # 5+6. Update stored metadata and sync to live viewers
        self._refresh_and_sync_metadata(series_number, new_count)

        info["last_grow_count"] = new_count
        self.logger.info(
            "progressive-fast: grew series=%s available=%d/%d",
            series_number, new_count, total,
        )

        # â”€â”€ Stale-grow guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # loader.grow() may return fewer slices than expected if the OS has
        # not yet flushed all downloaded files to disk.  The single-shot
        # timer will not fire again on its own, so we must reschedule it.
        # Also handles the one-shot path where the viewer is not in
        # progressive mode â€” enter_progressive_mode() lets
        # _find_progressive_viewers() locate the viewer on the retry tick.
        # MAX = 5 retries (أ—150ms = 750ms window).  On exhaustion: accept
        # best-effort count, stop safety-net loop, exit progressive mode.
        # The done-guard completion one-shot will recover when DM sends the
        # final signal (after the OS has certainly flushed).
        _STALE_RETRY_MAX = 5
        if new_count < pending_count:
            _stale_retry = info.get("_stale_retry_count", 0)
            if _stale_retry < _STALE_RETRY_MAX:
                info["_stale_retry_count"] = _stale_retry + 1
                # Keep pending_downloaded set so _flush_progressive_grow retries
                info["pending_downloaded"] = pending_count
                # Enter progressive mode on non-progressive viewers (one-shot path)
                # so _find_progressive_viewers() can locate them on the retry tick
                for _vtk_w2, _ in viewers:
                    if not _vtk_w2._progressive_mode:
                        _vtk_w2.enter_progressive_mode(total, series_number)
                        _vtk_w2.update_available_slice_count(new_count)
                if not self._progressive_grow_timer.isActive():
                    self._progressive_grow_timer.start()
                self.logger.warning(
                    "progressive-fast: STALE grow series=%s got=%d expected=%d "
                    "(retry %d/%d in %dms)",
                    series_number, new_count, pending_count,
                    info["_stale_retry_count"], _STALE_RETRY_MAX,
                    self._progressive_grow_timer.interval(),
                )
            else:
                # Max retries exhausted â€” OS buffer not flushing in time.
                # Accept best-effort count: equalise pending to stop the
                # _flush_progressive_grow safety-net from looping, then
                # exit progressive mode so the viewer is usable at whatever
                # count is available.  The done-guard completion one-shot
                # will recover the remaining images when DM sends the final
                # completion signal.
                self.logger.error(
                    "progressive-fast: STALE-EXHAUSTED series=%s stuck at %d/%d after %d retries"
                    " â€” exiting progressive mode; done-guard will recover on completion signal",
                    series_number, new_count, pending_count, _stale_retry,
                )
                info["pending_downloaded"] = new_count  # stop safety-net loop
                self._progressive_series.pop(series_number, None)
                _h10_log_progressive_mutation(self, '_grow_progressive_fast', series_number, 'pop_stale_exhausted')
                for _vtk_w2, _n2 in viewers:
                    _sl2 = getattr(_n2, "slider", None)
                    if _sl2 is not None:
                        try:
                            _sl2.blockSignals(True)
                            _sl2.setMaximum(max(0, new_count - 1))
                            _sl2.blockSignals(False)
                        except Exception:
                            pass
                    try:
                        _vtk_w2.exit_progressive_mode()
                    except Exception as _epm_exc:
                        self.logger.warning(
                            "progressive-fast: exit_progressive_mode failed "
                            "viewer_id=%s series=%s (stale-exhausted): %s",
                            getattr(_vtk_w2, "id_vtk_widget", id(_vtk_w2)),
                            series_number, _epm_exc,
                        )
                    # Refresh corner text after exiting progressive mode
                    try:
                        _iv = getattr(_vtk_w2, "image_viewer", None)
                        if _iv is not None and hasattr(_iv, "update_corners_actors"):
                            _iv.update_corners_actors()
                    except Exception:
                        pass
                self._update_thumbnail_count(series_number, new_count)
                return  # don't fall through to step 6 (already cleaned up)

        # 6. Check if download completed
        if new_count >= total and total > 0:
            # Final refresh of stored metadata with complete file list
            self._refresh_and_sync_metadata(series_number, new_count)
            # Invalidate stale caches so next access rebuilds from full data
            self._invalidate_series_caches(series_number)

            for vtk_w, node in viewers:
                try:
                    vtk_w.exit_progressive_mode()
                except Exception as _epm_exc:
                    self.logger.warning(
                        "progressive-fast: exit_progressive_mode failed "
                        "viewer_id=%s series=%s (completion): %s",
                        getattr(vtk_w, "id_vtk_widget", id(vtk_w)),
                        series_number, _epm_exc,
                    )
                # Refresh corner text after exiting progressive mode
                try:
                    iv = getattr(vtk_w, "image_viewer", None)
                    if iv is not None and hasattr(iv, "update_corners_actors"):
                        iv.update_corners_actors()
                except Exception:
                    pass
            self._progressive_series.pop(series_number, None)
            _h10_log_progressive_mutation(self, '_grow_progressive_fast', series_number, 'pop_complete')
            self._update_thumbnail_count(series_number, new_count)
            self.logger.info(
                "progressive-fast: series=%s COMPLETE (%d slices)", series_number, new_count
            )

    async def _grow_progressive_viewer_async(self, series_number: str, expected_count: int):
        """Background: reload partial series from disk and grow viewers in-place."""
        study_path = self._get_correct_study_path()
        if not study_path:
            return

        # Load whatever files exist on disk (runs in executor to avoid blocking UI)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._load_partial_series_from_disk(series_number, study_path),
        )
        if result is None:
            return

        new_vtk_data, new_metadata = result
        new_dims = new_vtk_data.GetDimensions() if new_vtk_data else (0, 0, 0)
        new_z = int(new_dims[2]) if new_dims and len(new_dims) > 2 else 0

        if new_z <= 0:
            return

        # Apply growth on UI thread
        info = self._progressive_series.get(series_number, {})
        info["last_grow_count"] = new_z

        viewers = self._find_progressive_viewers(series_number)
        for vtk_w, node in viewers:
            try:
                grew = vtk_w.grow_progressive_series(new_vtk_data, new_metadata)
                if grew:
                    self.logger.info(
                        "progressive: grew series=%s slices=%d", series_number, new_z
                    )
                    # Also update the data in lst_thumbnails_data for consistency
                    self._apply_loaded_series_data(
                        series_number, new_vtk_data, new_metadata,
                        patient_pk=None, study_pk=None,
                        refresh_viewer=False,
                    )
            except Exception as e:
                self.logger.warning("progressive: grow viewer failed: %s", e)

        # If we reached total, exit progressive mode
        total = info.get("total", 0)
        if new_z >= total and total > 0:
            # Refresh stored metadata + invalidate stale caches
            self._refresh_and_sync_metadata(series_number, new_z)
            self._invalidate_series_caches(series_number)
            for vtk_w, node in viewers:
                vtk_w.exit_progressive_mode()
            self._progressive_series.pop(series_number, None)
            _h10_log_progressive_mutation(self, '_grow_progressive_fast', series_number, 'pop_total_reached')
            self.logger.info("progressive: series=%s COMPLETE (%d slices)", series_number, new_z)

    def _load_partial_series_from_disk(self, series_number: str, study_path: str):
        """Load whatever DICOM files currently exist on disk for a series.

        This is called from a background executor thread.
        Returns (vtk_image_data, metadata) or None.
        """
        try:
            from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
            result = load_single_series_by_number(
                study_path=study_path,
                series_number=series_number,
                patient_pk=getattr(self.parent_widget, 'patient_pk', None),
                study_pk=getattr(self.parent_widget, 'study_pk', None),
                allow_lazy_backend=False,  # Force VTK backend for partial loading
            )
            if result is None:
                return None
            # load_single_series_by_number is a generator yielding
            # (vtk_image_data, metadata, ...)
            for item in result:
                if item and len(item) >= 2:
                    return (item[0], item[1])
            return None
        except Exception as e:
            self.logger.warning("progressive: partial load failed series=%s: %s", series_number, e)
            return None

    def on_series_download_fully_complete(self, series_number: str):
        """Qt signal slot: outer guard so exceptions never escape into Qt dispatch."""
        try:
            self._on_series_download_fully_complete_impl(series_number)
        except Exception as exc:
            self.logger.error(
                "progressive: unhandled error in on_series_download_fully_complete "
                "series=%s: %s",
                series_number, exc, exc_info=True,
            )

    def _on_series_download_fully_complete_impl(self, series_number: str):
        """Called when a series finishes downloading completely.

        Performs a FINAL grow on all viewers showing this series to ensure
        every downloaded file is visible, then exits progressive mode.
        Also refreshes corner text ("X / Y") and thumbnail image count.
        Schedules a deferred verification (500ms) to catch OS-flush-delayed
        files that were not yet visible at the time of this call.

        v2.2.9.2 â€” only exits progressive mode if grow got all expected files.
        If the OS hasn't flushed the last batch yet, Layer 3 / Layer 4 handle
        the remaining images while progressive mode stays active.
        """
        sn = str(series_number)
        info = self._progressive_series.get(sn, {})
        expected_total = info.get("total", 0)
        final_count = 0
        all_viewers_complete = True

        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            # Match by progressive series number OR by displayed series metadata
            is_match = (vtk_w._progressive_series_number == sn)
            if not is_match:
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                    is_match = (viewer_sn == sn)
                except Exception:
                    pass
            if not is_match:
                continue

            # Final grow: pick up any remaining files before exiting progressive
            try:
                loader = getattr(vtk_w, "_lazy_loader", None)
                if loader is not None and hasattr(loader, "grow"):
                    new_count = loader.grow()
                    final_count = max(final_count, new_count)
                    self._update_vtk_slice_range(vtk_w, node, new_count)
                    self.logger.info(
                        "progressive: final grow on download-complete series=%s count=%d",
                        sn, new_count,
                    )
            except Exception as exc:
                self.logger.debug(
                    "progressive: final grow failed series=%s: %s", sn, exc
                )

            # v2.2.9.2 â€” only exit progressive if all expected files arrived.
            # If the OS hasn't flushed the last batch, keep progressive mode
            # so that Layer 3 (500ms verify) can pick up the remaining files.
            if expected_total > 0 and final_count < expected_total:
                all_viewers_complete = False
                self.logger.info(
                    "progressive: download-complete but grow incomplete series=%s "
                    "count=%d expected=%d â€” keeping progressive mode for Layer 3",
                    sn, final_count, expected_total,
                )
            else:
                try:
                    vtk_w.exit_progressive_mode()
                except Exception as _epm_fc:
                    self.logger.warning(
                        "progressive: exit_progressive_mode failed "
                        "viewer_id=%s series=%s (download-complete): %s",
                        getattr(vtk_w, "id_vtk_widget", id(vtk_w)), sn, _epm_fc,
                    )

            # Refresh corner text "Slice: X / Y" so it shows the final total
            try:
                iv = getattr(vtk_w, "image_viewer", None)
                if iv is not None and hasattr(iv, "update_corners_actors"):
                    iv.update_corners_actors()
            except Exception:
                pass

        # v2.2.9.2 â€” only pop tracking info if all viewers got all files.
        # Layer 3 / Layer 4 need the info to keep growing.
        if all_viewers_complete:
            # H6 fix (v2.2.9.3): mark series as completed BEFORE pop/discard.
            # This prevents the late _display_activate_and_mark_done callback
            # (from _start_progressive_display's threaded fallback) from
            # re-entering progressive mode after we clean up here.
            completed = getattr(self, '_series_download_completed', None)
            if completed is not None:
                completed.add(sn)
                self.logger.info(
                    "progressive: _series_download_completed.add series=%s", sn,
                )
            self._progressive_series.pop(sn, None)
            _h10_log_progressive_mutation(self, 'on_series_download_fully_complete', sn, 'pop_completed')
            # H4 fix (v2.2.9.2): discard the done-guard key so a future re-open
            # of the same series can start a fresh progressive display.
            # _progressive_display_done is a lifecycle guard, NOT a permanent cache.
            done = getattr(self, '_progressive_display_done', None)
            if done is not None:
                done.discard(sn)
                _h10_log_progressive_mutation(self, 'on_series_download_fully_complete', sn, 'done_discard')

        # Update stored metadata so re-drop and thumbnails use the final count
        if final_count > 0:
            self._refresh_and_sync_metadata(sn, final_count)
            self._invalidate_series_caches(sn)

        # FAST mode: promote completed lazy volume to ZetaBoost so re-visits
        # get an O(1) cache hit instead of re-decoding all slices from disk.
        # Must run AFTER _invalidate_series_caches (which clears stale entries)
        # and AFTER the final grow (which ensures all slices are decoded).
        if all_viewers_complete and final_count > 0 and self._is_fast_viewer_mode():
            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                loader = getattr(vtk_w, "_lazy_loader", None)
                if loader is None or not hasattr(loader, "vtk_image_data"):
                    continue
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                    if viewer_sn != sn:
                        continue
                    vtk_data = loader.vtk_image_data
                    meta = getattr(vtk_w.image_viewer, "metadata", None)
                    if vtk_data is not None and isinstance(meta, dict):
                        self._full_cache_put(sn, vtk_data, meta)
                        self.logger.info(
                            "progressive: promoted FAST lazy volume to ZetaBoost "
                            "series=%s slices=%d", sn, final_count,
                        )
                        break  # one promotion per series is enough
                except Exception as exc:
                    self.logger.debug(
                        "progressive: ZetaBoost promotion failed series=%s: %s",
                        sn, exc,
                    )

        # Update thumbnail label to show the definitive image count
        self._update_thumbnail_count(sn, final_count)

        # v2.2.9.2 â€” invalidate disk count cache so Layer 3 gets a fresh read.
        self._disk_count_cache.pop(sn, None)

        # Schedule deferred verification to catch OS-flush-delayed files.
        # Expected total comes from DICOM headers (set by DM progress signals).
        if expected_total > 0:
            QTimer.singleShot(
                500,
                lambda _sn=sn, _total=expected_total: self._completion_verify_series(_sn, _total),
            )
            # Also register for Layer 4 sweep in case Layer 3 retries exhaust
            self._completion_sweep_register(sn, expected_total)

    def _update_thumbnail_count(self, series_number: str, count: int):
        """Update the thumbnail image count label (blue text) for a series.

        Falls back gracefully if thumbnail_manager is unavailable.  Uses the
        disk file count if *count* is 0 (caller didn't have a final grow count).
        """
        sn = str(series_number)
        if count <= 0:
            try:
                count = self._count_series_files_on_disk(sn)
            except Exception:
                return
        if count <= 0:
            return
        try:
            tm = getattr(self.parent_widget, "thumbnail_manager", None)
            if tm is not None and hasattr(tm, "update_series_image_count"):
                tm.update_series_image_count(sn, count)
        except Exception:
            pass

    def _refresh_corner_text(self, series_number: str):
        """Refresh 'Slice: X / Y' corner text on all viewers showing *series_number*."""
        sn = str(series_number)
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn != sn:
                continue
            try:
                iv = getattr(vtk_w, "image_viewer", None)
                if iv is not None and hasattr(iv, "update_corners_actors"):
                    iv.update_corners_actors()
            except Exception:
                pass

    # â”€â”€ Layer 3: Deferred completion verification â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _COMPLETION_VERIFY_MAX_RETRIES = 3
    _COMPLETION_VERIFY_INTERVAL_MS = 500

    def _completion_verify_series(self, series_number: str, expected_total: int,
                                  _retry: int = 0):
        """QTimer.singleShot callback: outer guard so exceptions never propagate. (v2.2.9.3)"""
        try:
            self._completion_verify_series_impl(series_number, expected_total, _retry)
        except Exception as exc:
            self.logger.error(
                "progressive: unhandled exception in _completion_verify_series "
                "series=%s retry=%d: %s",
                series_number, _retry, exc, exc_info=True,
            )

    def _completion_verify_series_impl(self, series_number: str, expected_total: int,
                                       _retry: int = 0):
        """Deferred verification: ensure viewer shows all downloaded files.

        Called 500ms after on_series_download_fully_complete.  If the viewer
        still shows fewer slices than files on disk (OS flush delay), does
        one more loader.grow() + slider update and retries up to 3 times.

        v2.2.9.2 â€” invalidates disk count cache before checking to avoid
        stale 1s-TTL values.  Also exits progressive mode and cleans up
        tracking info when grow succeeds (Layer 2b may have left them active).
        """
        sn = str(series_number)
        # v2.2.9.2 â€” invalidate cache for fresh disk count
        self._disk_count_cache.pop(sn, None)
        try:
            disk_count = self._count_series_files_on_disk(sn)
        except Exception:
            disk_count = 0

        if disk_count <= 0:
            return  # no files at all â€” nothing to verify

        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn != sn:
                continue

            current_count = vtk_w.get_count_of_slices()
            if current_count >= disk_count:
                self.logger.debug(
                    "completion-verify: series=%s OK (viewer=%d disk=%d)",
                    sn, current_count, disk_count,
                )
                return  # viewer is up to date

            # Viewer is behind â€” do a catch-up grow
            self.logger.info(
                "completion-verify: series=%s viewer=%d < disk=%d â€” growing (retry %d/%d)",
                sn, current_count, disk_count, _retry + 1,
                self._COMPLETION_VERIFY_MAX_RETRIES,
            )
            try:
                loader = getattr(vtk_w, "_lazy_loader", None)
                if loader is not None and hasattr(loader, "grow"):
                    new_count = loader.grow()
                    self._update_vtk_slice_range(vtk_w, node, new_count)
                    self._refresh_and_sync_metadata(sn, new_count)
                    self.logger.info(
                        "completion-verify: series=%s grew to %d", sn, new_count,
                    )
                    if new_count >= disk_count:
                        # v2.2.9.2 â€” clean up progressive state left by Layer 2b
                        if vtk_w._progressive_mode:
                            vtk_w.exit_progressive_mode()
                        self._progressive_series.pop(sn, None)
                        _h10_log_progressive_mutation(self, '_completion_verify_series_impl', sn, 'pop_verified')
                        # H4 fix: Layer 3 must also clear done-guard (Layer 2b may
                        # not have fired yet in OS-flush-delayed scenarios).
                        done = getattr(self, '_progressive_display_done', None)
                        if done is not None:
                            done.discard(sn)
                            _h10_log_progressive_mutation(self, '_completion_verify_series_impl', sn, 'done_discard')
                        self._refresh_corner_text(sn)
                        self._update_thumbnail_count(sn, new_count)
                        return  # success
            except Exception as exc:
                self.logger.debug(
                    "completion-verify: grow failed series=%s: %s", sn, exc,
                )

            # Still behind â€” retry if allowed
            if _retry < self._COMPLETION_VERIFY_MAX_RETRIES - 1:
                QTimer.singleShot(
                    self._COMPLETION_VERIFY_INTERVAL_MS,
                    lambda _sn=sn, _t=expected_total, _r=_retry + 1:
                        self._completion_verify_series(_sn, _t, _r),
                )
            else:
                self.logger.warning(
                    "completion-verify: EXHAUSTED series=%s viewer still at %d vs disk=%d"
                    " after %d retries",
                    sn, vtk_w.get_count_of_slices(), disk_count,
                    self._COMPLETION_VERIFY_MAX_RETRIES,
                )
            return  # handled first matching viewer

    # â”€â”€ Layer 4: Completion sweep safety-net â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _completion_sweep_register(self, series_number: str, expected_total: int):
        """Register a series for periodic completion sweep verification."""
        self._completion_sweep_series_set.add((series_number, expected_total))
        if not self._completion_sweep_timer.isActive():
            self._completion_sweep_timer.start()

    def _completion_sweep_tick(self):
        """QTimer callback: outer guard so exceptions never escape into Qt dispatch."""
        try:
            self._completion_sweep_tick_impl()
        except Exception as exc:  # pragma: no cover
            self.logger.error(
                "progressive: unhandled error in _completion_sweep_tick: %s",
                exc, exc_info=True,
            )

    def _completion_sweep_tick_impl(self):
        """Periodic safety net: check all registered series for stale display.

        Runs every 3 seconds while there are series to verify.  For each
        series, compares viewer slice count against disk file count and
        triggers a catch-up grow if the viewer is behind.  Removes series
        from tracking once the viewer matches disk count or no viewer is
        showing it anymore.
        """
        resolved = set()
        for sn, expected_total in list(self._completion_sweep_series_set):
            # v2.2.9.2 â€” invalidate cache for fresh disk count
            self._disk_count_cache.pop(sn, None)
            try:
                disk_count = self._count_series_files_on_disk(sn)
            except Exception:
                disk_count = 0

            if disk_count <= 0:
                resolved.add((sn, expected_total))
                continue

            _found_viewer = False
            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                except Exception:
                    viewer_sn = ""
                if viewer_sn != sn:
                    continue

                _found_viewer = True
                current_count = vtk_w.get_count_of_slices()
                if current_count >= disk_count:
                    resolved.add((sn, expected_total))
                    break

                # Viewer behind â€” catch-up grow
                try:
                    loader = getattr(vtk_w, "_lazy_loader", None)
                    if loader is not None and hasattr(loader, "grow"):
                        new_count = loader.grow()
                        self._update_vtk_slice_range(vtk_w, node, new_count)
                        self._refresh_and_sync_metadata(sn, new_count)
                        self.logger.info(
                            "completion-sweep: grew series=%s from %d to %d (disk=%d)",
                            sn, current_count, new_count, disk_count,
                        )
                        if new_count >= disk_count:
                            # v2.2.9.2 â€” clean up progressive state left by Layer 2b
                            if vtk_w._progressive_mode:
                                vtk_w.exit_progressive_mode()
                            self._progressive_series.pop(sn, None)
                            _h10_log_progressive_mutation(self, '_completion_sweep_tick_impl', sn, 'pop_swept')
                            # H4 fix: Layer 4 must also clear done-guard so the
                            # series can restart progressive display on next open.
                            done = getattr(self, '_progressive_display_done', None)
                            if done is not None:
                                done.discard(sn)
                                _h10_log_progressive_mutation(self, '_completion_sweep_tick_impl', sn, 'done_discard')
                            self._refresh_corner_text(sn)
                            self._update_thumbnail_count(sn, new_count)
                            resolved.add((sn, expected_total))
                except Exception as exc:
                    self.logger.debug(
                        "completion-sweep: grow failed series=%s: %s", sn, exc,
                    )
                break  # handle first matching viewer only

            if not _found_viewer:
                resolved.add((sn, expected_total))

        self._completion_sweep_series_set -= resolved

        # Stop timer when nothing left to verify
        if not self._completion_sweep_series_set:
            self._completion_sweep_timer.stop()
            self.logger.debug("completion-sweep: all series verified â€” timer stopped")

    def _activate_progressive_mode_on_viewers(self, series_number: str, total_expected: int):
        """After first progressive display, mark viewers for progressive growth.

        In Fast mode, also activates the ImageSliceBooster for آ±20 prefetch.
        """
        is_fast = self._is_fast_viewer_mode()
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            # Find viewers showing this series
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn == str(series_number):
                avail = vtk_w.get_count_of_slices()  # Current VTK Z-dim
                vtk_w.enter_progressive_mode(total_expected, series_number)
                vtk_w.update_available_slice_count(avail)
                # Update slider to show full range
                slider = getattr(node, "slider", None)
                if slider is not None:
                    try:
                        slider.blockSignals(True)
                        slider.setMaximum(max(0, total_expected - 1))
                        slider.blockSignals(False)
                    except Exception:
                        pass

                # Fast mode: activate ImageSliceBooster for آ±20 prefetch
                if is_fast:
                    try:
                        loader = getattr(vtk_w, "_lazy_loader", None)
                        backend = getattr(loader, "backend", None) if loader is not None else None
                        if backend is not None:
                            paths = backend.get_file_paths()
                            if paths:
                                self._image_slice_booster.set_active(
                                    str(series_number), paths, center_slice=0,
                                )
                    except Exception as exc:
                        self.logger.debug("progressive: booster activation failed: %s", exc)

                self.logger.info(
                    "progressive: activated viewer series=%s avail=%d total=%d fast=%s",
                    series_number, avail, total_expected, is_fast,
                )

    def _apply_progressive_to_target_viewer(
        self, series_number: str, total: int, vtk_widget, node
    ):
        """Switch a specific viewer to a freshly loaded progressive series.

        Used when the user drag-dropped a series that wasn't on disk yet.
        The viewer was marked with ``_awaiting_series_number`` and a spinner
        was kept visible.  Now the first batch has been loaded â€” display it
        in that viewer, hide the spinner, and enter progressive mode.
        """
        try:
            # Clear the awaiting marker
            vtk_widget._awaiting_series_number = None

            # Look up loaded data from cache
            vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(
                str(series_number)
            )
            if metadata is None or vtk_image_data is None:
                self.logger.warning(
                    "progressive-target: series=%s not in cache after load", series_number
                )
                self._hide_spinner_for_widget(vtk_widget)
                return

            slider = getattr(node, "slider", None) if node else None

            # Display the series on the target viewer
            self._display_loaded_series(
                series_number=str(series_number),
                series_idx=series_idx,
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                flag_change_selected_widget=False,
                vtk_widget=vtk_widget,
                slider=slider,
                progressive_total=total,
            )

            # Enter progressive mode on this viewer
            avail = vtk_widget.get_count_of_slices()
            vtk_widget.enter_progressive_mode(total, str(series_number))
            vtk_widget.update_available_slice_count(avail)
            if slider is not None:
                try:
                    slider.blockSignals(True)
                    slider.setMaximum(max(0, total - 1))
                    slider.blockSignals(False)
                except Exception:
                    pass

            # Fast mode: activate ImageSliceBooster for آ±20 prefetch
            if self._is_fast_viewer_mode():
                try:
                    loader = getattr(vtk_widget, "_lazy_loader", None)
                    backend = getattr(loader, "backend", None) if loader else None
                    if backend is not None:
                        paths = backend.get_file_paths()
                        if paths:
                            self._image_slice_booster.set_active(
                                str(series_number), paths, center_slice=0,
                            )
                except Exception:
                    pass

            # Hide the spinner now that content is visible
            self._hide_spinner_for_widget(vtk_widget)

            self.logger.info(
                "progressive-target: displayed series=%s on awaiting viewer avail=%d total=%d",
                series_number, avail, total,
            )
        except Exception as exc:
            self.logger.warning("progressive-target: failed series=%s: %s", series_number, exc)
            self._hide_spinner_for_widget(vtk_widget)



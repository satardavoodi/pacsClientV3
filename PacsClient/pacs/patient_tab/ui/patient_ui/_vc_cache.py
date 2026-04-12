"""
Cache and metadata mixin for ViewerController.
Tab lifecycle, full-series cache, metadata refresh, disk file counts.
"""
from __future__ import annotations
import os
import threading
import time
import pydicom
from pathlib import Path
from PySide6.QtCore import QTimer
from modules.zeta_boost import ZetaBoostEngine
from modules.viewer.pipeline import PipelineState
import logging

logger = logging.getLogger(__name__)


class _VCCacheMixin:
    """Auto-split mixin — see patient_widget_viewer_controller.py for history."""

    def on_tab_activated(self):
        """Mark this patient tab as active and allow predictive prefetching."""
        self._tab_active = True
        self._open_warmup_retry_count = 0
        self._last_user_interaction_ts = time.time()
        self._boostviewer_enabled = self._is_boostviewer_enabled_runtime()
        self._zeta_manual_triggered = False

        if not self._boostviewer_enabled:
            # Manual-trigger mode: no proactive activation/warmup until drag/drop.
            try:
                self.zeta_boost.clear_pending()
            except Exception:
                pass
            try:
                # Keep previously cached data available for read fallback without
                # running background workers in OFF mode.
                self.zeta_boost.deactivate(clear_cache=False)
            except Exception:
                pass
            try:
                print(
                    f"âœ… [TAB-LIFECYCLE] ACTIVE(manual-trigger) study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                    f"boostviewer=False zeta_boost_active={self.zeta_boost.is_active()}"
                )
            except Exception:
                pass
            return

        # Auto mode: engine active + proactive warmup/prefetch allowed.
        try:
            self.zeta_boost.activate()
        except Exception:
            pass

        try:
            print(
                f"âœ… [TAB-LIFECYCLE] ACTIVE study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                f"zeta_boost_active={self.zeta_boost.is_active()}"
            )
        except Exception:
            pass
        try:
            if self._first_series_displayed:
                QTimer.singleShot(250, self._start_background_prefetch)
        except Exception:
            pass
        # Recovery path: if first-series display never completed (e.g. load finished
        # while tab was inactive), re-run the local-first-series signal route on
        # activation. This call is idempotent and exits quickly when already shown.
        if not self._first_series_displayed:
            try:
                QTimer.singleShot(120, self.parent_widget._check_and_load_local_first_series)
            except Exception:
                pass
        # Start warmup shortly after tab-open bootstrap to avoid competing with first render.
        try:
            # Mode A detection: only if all series are pre-downloaded (study complete)
            from PacsClient.pacs.patient_tab.utils.utils import check_study_complete, count_subfolders_with_dicom
            study_uid = getattr(self.parent_widget, 'study_uid', None)

            # [H7-P2] Study classification decision
            _h7_check_result = False
            _h7_folder_count = 0
            _h7_expected = 0
            _h7_dm_active = self._global_downloads_active()
            if study_uid:
                try:
                    from PacsClient.utils.config import SOURCE_PATH as _h7_src
                    from PacsClient.utils.db_manager import get_study_by_study_uid as _h7_get_study
                    _h7_study_path = _h7_src / study_uid
                    if _h7_study_path.exists():
                        _h7_folder_count = count_subfolders_with_dicom(_h7_study_path)
                    _h7_sdata = _h7_get_study(study_uid)
                    _h7_expected = int((_h7_sdata or {}).get('number_of_series', 0))
                except Exception:
                    pass
                _h7_check_result = check_study_complete(study_uid)

            _h7_action = 'skip'
            if self.pipeline.state == PipelineState.IDLE and study_uid and _h7_check_result:
                self.pipeline.mark_pre_downloaded()
                _h7_action = 'mark_pre_downloaded'

            logger.info(
                "[H7-P2] study=%s pipeline_state=%s check_study_complete=%s "
                "folder_count=%d expected=%d dm_active=%s action=%s",
                study_uid, self.pipeline.state.name if hasattr(self.pipeline.state, 'name') else self.pipeline.state,
                _h7_check_result, _h7_folder_count, _h7_expected, _h7_dm_active, _h7_action,
            )
            # Force-sync ZetaBoost engine flags with current pipeline state on every
            # activation.  Handles the case where download started while the tab was
            # inactive (engine was deactivated by _on_pipeline_state_changed).
            if self.pipeline.state in (PipelineState.POST_DOWNLOAD, PipelineState.READY):
                if not self._global_downloads_active():
                    self.zeta_boost.set_study_download_complete(True)
                    self.zeta_boost.set_download_active(False)
                else:
                    self.zeta_boost.set_study_download_complete(False)
                    self.zeta_boost.set_download_active(True)
            elif self.pipeline.state == PipelineState.DOWNLOADING:
                # Tab is being activated while a download is still in progress.
                # Sync engine flags so it knows warmup is blocked.  Workers are
                # alive again (activate() was called above) but gated by download_active.
                self.zeta_boost.set_study_download_complete(False)
                self.zeta_boost.set_download_active(True)
                self.zeta_boost.set_image_boost_mode(True)

            # [H7-P9] ZetaBoost/cache state after flag sync
            try:
                _h7_zb_complete = getattr(self.zeta_boost, '_study_download_complete', None)
                _h7_zb_dl_active = getattr(self.zeta_boost, '_download_active', None)
                logger.info(
                    "[H7-P9] study=%s zeta_study_download_complete=%s zeta_download_active=%s "
                    "pipeline_state=%s global_downloads_active=%s",
                    study_uid,
                    _h7_zb_complete, _h7_zb_dl_active,
                    self.pipeline.state.name if hasattr(self.pipeline.state, 'name') else self.pipeline.state,
                    self._global_downloads_active(),
                )
            except Exception:
                pass

            # Schedule warmup check.  _start_open_tab_warmup guards itself with
            # pipeline.is_warmup_allowed, so this is a no-op if downloading.
            if not self._global_downloads_active():
                QTimer.singleShot(900, self._start_open_tab_warmup)
            else:
                print(
                    f"[WARMUP] Activation warmup deferred â€” global downloads active "
                    f"count={int(getattr(ZetaBoostEngine, '_global_active_download_count', 0) or 0)}"
                )
        except Exception:
            pass

    def on_tab_deactivated(self):
        """Mark this patient tab as inactive and stop heavy background work."""
        self._tab_active = False
        self._open_warmup_retry_count = 0
        self._warmup_gather_running = False
        self._zeta_boost_failed_series.clear()
        self._warmup_corrupt_skip_counts.clear()
        self._series_warmup_eligibility_cache.clear()
        self._deferred_heavy_warmup_series.clear()
        self._deferred_heavy_warmup_retry_count = 0
        try:
            self._image_slice_booster.clear()
        except Exception:
            pass
        try:
            self.zeta_boost.deactivate(clear_cache=True)
        except Exception:
            pass
        try:
            print(
                f"ًں›‘ [TAB-LIFECYCLE] INACTIVE study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                f"zeta_boost_active={self.zeta_boost.is_active()}"
            )
        except Exception:
            pass
        self._stop_background_prefetch()
        self._trim_full_series_cache_for_inactive(keep_entries=0)

    def _trim_full_series_cache_for_inactive(self, keep_entries: int = 2):
        """Bound memory use for inactive tabs by trimming ZetaBoost cache."""
        try:
            self.zeta_boost.trim_keep(keep_entries)
        except Exception:
            pass

    def _full_cache_key(self, series_number: str):
        study_uid = str(getattr(self.parent_widget, 'study_uid', '') or '')
        return (study_uid, str(series_number))

    def _estimate_vtk_bytes(self, vtk_image_data):
        try:
            if vtk_image_data is None:
                return 0
            dims = vtk_image_data.GetDimensions()
            comps = int(vtk_image_data.GetNumberOfScalarComponents() or 1)
            scalar_size = int(vtk_image_data.GetScalarSize() or 2)
            voxels = max(1, int(dims[0])) * max(1, int(dims[1])) * max(1, int(dims[2]))
            return int(voxels * comps * scalar_size)
        except Exception:
            return 0

    def _full_cache_get(self, series_number: str):
        if self._zeta_slice_focus_mode:
            return None
        key_sn = str(series_number)
        # ALWAYS instant: use engine.query() for O(1) memory-only lookup.
        # Disk-cache promotion happens exclusively inside engine workers
        # (via _try_promote_disk_to_memory).  The viewer never touches
        # the disk cache â€” if ZetaBoost isn't ready, the viewer loads
        # its own data through the normal workflow.
        _fcg_start = time.perf_counter()
        try:
            val = self.zeta_boost.query(key_sn)
            if val is not None:
                try:
                    vtk_data, meta = val[0], val[1]
                except Exception:
                    vtk_data, meta = None, None
                if not self._is_full_volume_cache_candidate(key_sn, vtk_data, meta):
                    try:
                        self.zeta_boost.invalidate_series(key_sn, clear_disk=True)
                    except Exception:
                        pass
                    return None
                _fcg_ms = (time.perf_counter() - _fcg_start) * 1000
                if _fcg_ms > 50:
                    logger.debug(f"ًں”چ [CACHE_GET] series={key_sn} source=zeta_boost {_fcg_ms:.0f}ms")
                logger.info("[META_CACHE_HIT] series=%s elapsed_ms=%.1f", key_sn, _fcg_ms)
                return val
        except Exception:
            pass
        logger.info("[META_CACHE_MISS] series=%s", key_sn)
        return None

    def _is_full_volume_cache_candidate(self, series_number: str, vtk_image_data, metadata) -> bool:
        """True only for deterministic full-volume payloads (never preview-only)."""
        try:
            if vtk_image_data is None or not isinstance(metadata, dict):
                return False
            if bool(metadata.get('preview_only', False)):
                return False

            dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
            z = int(dims[2]) if dims and len(dims) > 2 else 0
            expected = int(self._get_series_expected_slices(str(series_number)) or 0)

            if expected > 1 and z <= 1:
                return False
            return z > 0
        except Exception:
            return False

    def _full_cache_put(self, series_number: str, vtk_image_data, metadata):
        if self._zeta_slice_focus_mode:
            return
        # OFF mode policy: write cache only after explicit manual trigger (drag/drop).
        if (not self._boostviewer_enabled) and (not self._zeta_manual_triggered):
            return
        if not self._is_full_volume_cache_candidate(str(series_number), vtk_image_data, metadata):
            return
        try:
            self.zeta_boost.put(series_number, vtk_image_data, metadata)
        except Exception:
            pass

    # ── Series cache invalidation (stuck-slice fix) ──────────────────────

    def _invalidate_series_caches(self, series_number: str):
        """Remove stale entries for *series_number* from ALL cache layers.

        Call this when the on-disk file count for a series has grown (progressive
        download) so that the next ``change_series_on_viewer`` / drag-drop will
        reload fresh data instead of returning a partial slice set.
        """
        sn = str(series_number)
        self._series_cache.pop(sn, None)
        self._hot_series_cache.pop(sn, None)
        self._metadata_flat_cache.pop(sn, None)
        try:
            self.zeta_boost.invalidate_series(sn, clear_disk=True)
        except Exception:
            pass
        self.logger.debug("cache-invalidate: series=%s cleared all cache layers", sn)

    # ── DICOM header extraction for progressive stubs ──────────────────

    @staticmethod
    def _fill_stub_from_dicom_header(stub: dict) -> None:
        """Read per-slice DICOM tags from the file header into *stub*.

        Uses ``pydicom.dcmread(stop_before_pixels=True)`` — reads only the
        header (~1-3ms per file), no pixel data.  Populates geometry fields
        (IPP, IOP, pixel_spacing) required by reference-line computation and
        display fields (W/L, rows, columns) for per-slice accuracy.

        If the file is missing or unreadable the stub keeps its template
        defaults — the viewer falls back to scalar-range auto-W/L and
        reference lines are silently skipped for that slice.
        """
        fpath = stub.get("instance_path")
        if not fpath:
            return
        try:
            ds = pydicom.dcmread(str(fpath), stop_before_pixels=True, force=True)
        except Exception:
            return

        # Vector tags → list of float
        for tag_name, key in (
            ("ImagePositionPatient",    "image_position_patient"),
            ("ImageOrientationPatient", "image_orientation_patient"),
            ("PixelSpacing",            "pixel_spacing"),
        ):
            raw = ds.get(tag_name)
            if raw is not None:
                try:
                    stub[key] = [float(v) for v in raw]
                except (TypeError, ValueError):
                    pass

        # Scalar tags
        for tag_name, key, conv in (
            ("WindowWidth",           "window_width",           float),
            ("WindowCenter",          "window_center",          float),
            ("Rows",                  "rows",                   int),
            ("Columns",               "columns",                int),
            ("SliceThickness",        "slice_thickness",        float),
            ("SpacingBetweenSlices",  "spacing_between_slices", float),
            ("RescaleSlope",          "rescale_slope",          float),
            ("RescaleIntercept",      "rescale_intercept",      float),
        ):
            raw = ds.get(tag_name)
            if raw is not None:
                try:
                    # Window tags may be multi-valued (VM=1-n); take first
                    val = raw
                    if hasattr(val, '__iter__') and not isinstance(val, (str, bytes)):
                        val = next(iter(val))
                    stub[key] = conv(val)
                except (TypeError, ValueError, StopIteration):
                    pass

    def _refresh_stored_metadata_instances(self, series_number: str,
                                           current_disk_count: int):
        """Sync lst_thumbnails_data metadata['instances'] with actual files on disk.

        When a series is opened during download, the metadata stored in
        ``lst_thumbnails_data`` captures only the instances that existed at
        that moment.  Without refreshing, every subsequent ``change_series_on_viewer``
        cache-hit returns the original (partial) count, making the series appear
        stuck at N/T slices.

        This method scans the series directory for new ``.dcm`` files, appends
        minimal instance dicts for each, and bumps the caches so code that reads
        ``metadata['instances']`` sees the correct count.
        """
        sn = str(series_number)
        try:
            # Find the stored metadata for this series
            idx = self._series_number_to_index.get(sn)
            if idx is None or idx >= len(self.parent_widget.lst_thumbnails_data):
                return
            item = self.parent_widget.lst_thumbnails_data[idx]
            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                return

            existing_instances = metadata.get("instances") or []
            existing_count = len(existing_instances)
            if existing_count >= current_disk_count:
                return  # already up-to-date

            # Resolve series path from metadata or study path
            series_path = (metadata.get("series", {}) or {}).get("series_path", "")
            if not series_path:
                study_path = self._get_correct_study_path()
                if study_path:
                    series_path = str(Path(study_path) / sn)
            if not series_path or not Path(series_path).is_dir():
                return

            # Fast pre-flight: TTL-cached scandir count avoids running the
            # expensive full iterdir scan when disk count hasn't grown yet
            # (e.g. OS hasn't flushed the downloaded files).  This is the
            # primary guard against per-grow-tick iterdir overhead.
            _fast_disk_count = self._count_series_files_on_disk(sn)
            if _fast_disk_count <= existing_count:
                return
            existing_paths = set()
            for inst in existing_instances:
                p = inst.get("instance_path", "")
                if p:
                    existing_paths.add(str(p).lower())

            # Scan disk for new files
            from natsort import natsorted
            all_dcm = natsorted(
                [f for f in Path(series_path).iterdir()
                 if f.is_file() and f.suffix.lower() in (".dcm", ".dicom")],
                key=lambda p: str(p),
            )

            # Build template from first complete instance so stubs inherit
            # shared per-series fields (window_width, rows, etc.).  Without
            # these the viewer's apply_default_window_level crashes KeyError.
            _TEMPLATE_KEYS = (
                "window_width", "window_center", "rows", "columns",
                "is_rgb", "pixel_spacing", "slice_thickness",
                "bits_allocated", "pixel_representation",
                "rescale_slope", "rescale_intercept",
                "photometric_interpretation", "samples_per_pixel",
                "image_orientation_patient",
            )
            template_fields: dict = {}
            for _inst in existing_instances:
                if _inst.get("window_width") is not None:
                    template_fields = {k: _inst[k] for k in _TEMPLATE_KEYS if k in _inst}
                    break

            new_instances = list(existing_instances)  # shallow copy
            for dcm_file in all_dcm:
                if str(dcm_file).lower() in existing_paths:
                    continue
                stub = {
                    "instance_number": len(new_instances),
                    "instance_path": str(dcm_file),
                }
                stub.update(template_fields)
                # Read per-slice DICOM geometry (IPP, IOP, pixel_spacing,
                # window_width/center) from the header.  Without this,
                # reference lines fail for new slices (IPP is None) and
                # per-slice W/L falls back to scalar-range auto-calc.
                # Reading is ~1-3ms per file (header only, no pixel data).
                self._fill_stub_from_dicom_header(stub)
                new_instances.append(stub)

            if len(new_instances) <= existing_count:
                return

            # Mutate the metadata in-place so all references see the updated list
            metadata["instances"] = new_instances
            # Also update series-level image_count so thumbnails show the
            # correct count (thumbnail reads this field, not len(instances))
            _series_meta = metadata.get("series")
            if isinstance(_series_meta, dict):
                _series_meta["image_count"] = len(new_instances)

            # Bump caches to reflect the updated metadata
            vtk_data = item.get("vtk_image_data")
            if vtk_data is not None:
                result = (vtk_data, metadata, idx)
                self._series_cache[sn] = result
                self._hot_series_cache[sn] = result

            self.logger.debug(
                "metadata-refresh: series=%s instances %d → %d",
                sn, existing_count, len(new_instances),
            )
        except Exception as exc:
            self.logger.debug("_refresh_stored_metadata_instances failed for %s: %s", sn, exc)

    def _sync_viewer_metadata_instances(self, series_number: str):
        """Sync ImageViewer2D.metadata['instances'] on live viewers with the
        refreshed source in lst_thumbnails_data.

        ImageViewer2D receives a deep-copied metadata dict at creation time.
        After ``_refresh_stored_metadata_instances`` replaces the ``instances``
        list on the source dict, the viewer's copy is stale.  This causes
        ``IndexError`` in ``apply_default_window_level(n)`` for any slice
        ``n >= original_count``, silently killing per-slice W/L and corners.

        Must be called AFTER ``_refresh_stored_metadata_instances`` on every
        grow path (progressive, completion, in-place re-drop).
        """
        sn = str(series_number)
        try:
            idx = self._series_number_to_index.get(sn)
            if idx is None or idx >= len(self.parent_widget.lst_thumbnails_data):
                return
            source_metadata = self.parent_widget.lst_thumbnails_data[idx].get("metadata")
            if not isinstance(source_metadata, dict):
                return
            source_instances = source_metadata.get("instances")
            if not source_instances:
                return

            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                iv = getattr(vtk_w, "image_viewer", None)
                if iv is None:
                    continue
                iv_meta = getattr(iv, "metadata", None)
                if not isinstance(iv_meta, dict):
                    continue
                try:
                    viewer_sn = str(
                        iv_meta.get("series", {}).get("series_number", "")
                    )
                except Exception:
                    viewer_sn = ""
                if viewer_sn != sn:
                    continue
                old_count = len(iv_meta.get("instances", []) or [])
                new_count = len(source_instances)
                if new_count >= old_count:
                    # Shallow copy — prevents cross-viewer mutation if any code
                    # later appends/pops on the list.  The dict *values* (per-
                    # instance metadata dicts) are still shared by reference,
                    # which is fine since they are read-only after creation.
                    iv_meta["instances"] = list(source_instances)
                    # Also sync series-level image_count
                    src_series = source_metadata.get("series")
                    iv_series = iv_meta.get("series")
                    if isinstance(src_series, dict) and isinstance(iv_series, dict):
                        ic = src_series.get("image_count")
                        if ic is not None:
                            iv_series["image_count"] = ic
                    self.logger.debug(
                        "viewer-metadata-sync: series=%s viewer instances %d → %d",
                        sn, old_count, new_count,
                    )
        except Exception as exc:
            self.logger.debug("_sync_viewer_metadata_instances failed for %s: %s", sn, exc)

    # ── Grow helpers ───────────────────────────────────────────────────────

    def _update_vtk_slice_range(self, vtk_w, node, new_count: int, *, slider=None):
        """Update VTK widget slice count and slider maximum after a grow.

        *slider* can be passed explicitly when the caller has it directly
        (e.g. ``change_series_on_viewer``).  Otherwise it is obtained from
        *node*.  Skips the Qt call when the maximum is already correct to
        avoid redundant work (~4000 calls/download otherwise).
        """
        try:
            vtk_w.update_available_slice_count(new_count)
        except Exception as _uasc_exc:
            self.logger.debug(
                "_update_vtk_slice_range: update_available_slice_count failed "
                "viewer_id=%s new_count=%d: %s",
                getattr(vtk_w, "id_vtk_widget", id(vtk_w)),
                new_count,
                _uasc_exc,
            )
        if slider is None:
            slider = getattr(node, "slider", None)
        if slider is not None:
            new_max = max(0, new_count - 1)
            try:
                current_max = slider.maximum()
            except Exception:
                current_max = None
            if current_max != new_max:
                try:
                    slider.blockSignals(True)
                    slider.setMaximum(new_max)
                    slider.blockSignals(False)
                except Exception:
                    pass

    def _refresh_and_sync_metadata(self, series_number, new_count: int):
        """Refresh source metadata instances AND sync to live viewers.

        Ensures ``_refresh_stored_metadata_instances`` and
        ``_sync_viewer_metadata_instances`` are always called as a pair.
        """
        self._refresh_stored_metadata_instances(series_number, new_count)
        self._sync_viewer_metadata_instances(series_number)

    def _count_series_files_on_disk(self, series_number: str) -> int:
        """Return the number of .dcm files on disk for *series_number*.

        Uses os.scandir (single syscall per entry) instead of Path.iterdir +
        stat for ~3-5x faster enumeration.  Results are cached for 1s to
        avoid redundant I/O when called multiple times in the same frame.
        """
        try:
            # 1-second TTL cache per series
            cache = getattr(self, '_disk_count_cache', None)
            if cache is None:
                self._disk_count_cache = {}
                cache = self._disk_count_cache
            _now = time.monotonic()
            key = str(series_number)
            entry = cache.get(key)
            if entry and (_now - entry[1]) < 1.0:
                return entry[0]

            study_path = self._get_correct_study_path()
            if not study_path:
                return 0
            series_dir = os.path.join(study_path, str(series_number))
            if not os.path.isdir(series_dir):
                return 0
            count = 0
            with os.scandir(series_dir) as it:
                for e in it:
                    if e.is_file(follow_symlinks=False):
                        name = e.name
                        if name.endswith('.dcm') or name.endswith('.dicom'):
                            count += 1
            cache[key] = (count, _now)
            return count
        except Exception:
            return 0

    # â”€â”€ Look-ahead warmup: pre-cache adjacent series after drag-drop â”€â”€
    _LOOKAHEAD_COUNT = 2  # number of adjacent series to pre-warm after drag-drop



"""
Backend / warmup-eligibility mixin for ViewerController.
Viewer backend selection, lookahead warmup, series index helpers.
"""
from __future__ import annotations
import json
import os
import time
import threading
import pydicom
from pathlib import Path
from PySide6.QtCore import QTimer
from modules.viewer.viewer_backend_config import (
    BACKEND_VTK,
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.boost_viewer_config import load_boost_viewer_enabled
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from PacsClient.utils.series_facts import resolve_series_expected_count
from modules.viewer.fast.lazy_volume_registry import get_loader as get_lazy_loader
import logging

logger = logging.getLogger(__name__)


class _VCBackendMixin:
    """Auto-split mixin — see patient_widget_viewer_controller.py for history."""

    def _resolve_series_expected_count(self, series_number: str):
        sn = str(series_number)
        scan_cap = max(int(self._warmup_max_slices or 0), int(self._prefetch_skip_slices_threshold or 0), 0) + 1

        def _disk_count_fallback(series_key: str) -> int:
            try:
                # Final fallback for non-hydrated metadata: lightweight capped on-disk count.
                # We intentionally stop at threshold+1, because warmup only needs large/not-large.
                study_path = self._get_correct_study_path()
                if study_path:
                    series_dir = Path(study_path) / str(series_key)
                    if series_dir.exists() and series_dir.is_dir():
                        cnt = 0
                        for p in series_dir.iterdir():
                            if not p.is_file():
                                continue
                            sfx = p.suffix.lower()
                            if sfx == '.dcm':
                                cnt += 1
                                if scan_cap > 0 and cnt >= scan_cap:
                                    return cnt
                        if cnt > 0:
                            return cnt
            except Exception:
                pass
            return 0

        return resolve_series_expected_count(
            sn,
            uid_to_number_map=getattr(self.parent_widget, '_series_uid_to_number', {}) or {},
            series_info_map=getattr(self.parent_widget, '_server_series_info', {}) or {},
            metadata_flat_map=getattr(self, '_metadata_flat_cache', {}) or {},
            thumbnail_items=getattr(self.parent_widget, 'lst_thumbnails_data', []) or [],
            series_number_to_index=getattr(self, '_series_number_to_index', {}) or {},
            disk_count_getter=_disk_count_fallback,
        )

    def _get_requested_viewer_backend(self) -> str:
        try:
            override_backend = str(
                getattr(self.parent_widget, "viewer_backend_override", "") or ""
            ).strip()
            if override_backend:
                return override_backend

            resolution = resolve_viewer_backend(
                metadata=None,
                settings=load_viewer_backend(default=BACKEND_PYDICOM_QT),
            )
            return str(resolution.get("requested_backend", BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT)
        except Exception:
            return BACKEND_PYDICOM_QT

    def _needs_backend_rebuild(self, metadata: dict, requested_backend: str) -> bool:
        """Return True when current payload cannot satisfy the requested backend."""
        if str(requested_backend or BACKEND_VTK) != BACKEND_PYDICOM:
            return False
        if not isinstance(metadata, dict):
            return True
        try:
            series_meta = metadata.get("series", {}) or {}
            # Decode failure should stay on deterministic VTK fallback.
            if bool(series_meta.get("force_vtk_fallback", False)):
                return False

            resolution = resolve_viewer_backend(metadata=metadata, settings=requested_backend)
            lazy_key = str(resolution.get("lazy_loader_key", "") or "").strip()
            if not lazy_key:
                return True
            return get_lazy_loader(lazy_key) is None
        except Exception:
            return True

    def apply_backend_setting_to_open_viewers(self):
        """Apply current backend setting to existing viewers via standard switch path."""
        requested_backend = self._get_requested_viewer_backend()
        self.logger.info(
            "viewer-backend stage=settings_apply requested_backend=%s open_viewers=%d",
            str(requested_backend),
            int(len(self.lst_nodes_viewer or [])),
            extra={
                "component": "viewer",
                "function": "ViewerController.apply_backend_setting_to_open_viewers",
                "stage": "settings_apply",
            },
        )

        for node in list(self.lst_nodes_viewer or []):
            vtk_widget = getattr(node, "vtk_widget", None)
            slider = getattr(node, "slider", None)
            if vtk_widget is None or slider is None:
                continue
            image_viewer = getattr(vtk_widget, "image_viewer", None)
            if image_viewer is None:
                continue

            metadata = getattr(image_viewer, "metadata", None)
            if not isinstance(metadata, dict):
                metadata = getattr(vtk_widget, "_bound_backend_metadata", None)
            if not isinstance(metadata, dict):
                continue

            series_number = str((metadata.get("series", {}) or {}).get("series_number", "")).strip()
            if not series_number:
                continue

            current_backend = str(getattr(vtk_widget, "_active_backend", BACKEND_VTK) or BACKEND_VTK)
            if current_backend == requested_backend and not self._needs_backend_rebuild(metadata, requested_backend):
                continue

            self.logger.info(
                "viewer-backend stage=settings_reload viewer=%s series=%s current=%s requested=%s",
                str(getattr(vtk_widget, "id_vtk_widget", None)),
                series_number,
                current_backend,
                requested_backend,
                extra={
                    "component": "viewer",
                    "function": "ViewerController.apply_backend_setting_to_open_viewers",
                    "stage": "settings_reload",
                },
            )
            self.change_series_on_viewer(
                series_number,
                flag_change_selected_widget=False,
                vtk_widget=vtk_widget,
                slider=slider,
                allow_paired=False,
            )

    def _enqueue_lookahead_warmup(self, series_number: str):
        """After a drag-drop displays series N, enqueue the next N adjacent series for warmup.

        This is the core of the "smart proactive" strategy: instead of trying
        to cache ALL series upfront (which fails for large studies), we cache
        on-demand with look-ahead.  The doctor will likely view adjacent series
        soon, so we prepare them while the current series is being reviewed.

        The look-ahead series are selected from the thumbnail list order (same
        order the doctor sees in the sidebar).
        """
        try:
            if not self.zeta_boost.is_active():
                return
            if not self._tab_active:
                return
            # Fast mode uses local slice boosting (±20) instead of series warmup.
            if self._is_fast_viewer_mode():
                return
            warmup_allowed = bool(self.pipeline.is_warmup_allowed)
            download_mode = not warmup_allowed

            sn = str(series_number)
            thumb_data = getattr(self.parent_widget, 'lst_thumbnails_data', None) or []
            if not thumb_data:
                return

            # Find the current series position in the thumbnail list
            current_idx = self._series_number_to_index.get(sn)
            if current_idx is None:
                for idx, item in enumerate(thumb_data):
                    try:
                        _sn = str(item.get('metadata', {}).get('series', {}).get('series_number', '') or '')
                        if _sn == sn:
                            current_idx = idx
                            break
                    except Exception:
                        continue
            if current_idx is None:
                return
            current_idx = int(current_idx)
            total = len(thumb_data)
            if total <= 1:
                return

            # Collect adjacent series: forward first (next N), then backward (prev N)
            # Forward is prioritized because doctors typically progress forward.
            lookahead_candidates = []

            # Forward look-ahead
            for offset in range(1, self._LOOKAHEAD_COUNT + 1):
                nxt = current_idx + offset
                if 0 <= nxt < total:
                    try:
                        nxt_sn = str(
                            thumb_data[nxt].get('metadata', {}).get('series', {}).get('series_number', '')
                        )
                        if nxt_sn and nxt_sn != sn:
                            lookahead_candidates.append(nxt_sn)
                    except Exception:
                        continue

            # Backward look-ahead (fill remaining slots only)
            remaining = self._LOOKAHEAD_COUNT - len(lookahead_candidates)
            if remaining > 0:
                for offset in range(1, remaining + 1):
                    prv = current_idx - offset
                    if 0 <= prv < total:
                        try:
                            prv_sn = str(
                                thumb_data[prv].get('metadata', {}).get('series', {}).get('series_number', '')
                            )
                            if prv_sn and prv_sn != sn and prv_sn not in lookahead_candidates:
                                lookahead_candidates.append(prv_sn)
                        except Exception:
                            continue

            if not lookahead_candidates:
                return

            # Filter candidates: skip already cached, non-image, failed, oversized
            queue = []
            for cand_sn in lookahead_candidates:
                try:
                    if self.zeta_boost.has_in_memory(cand_sn):
                        continue
                    if cand_sn in self._zeta_boost_failed_series:
                        continue
                    # Skip non-image series (SOP Class check)
                    if not self._is_series_image_type_for_warmup(cand_sn):
                        continue
                    # Skip oversized series (respect warmup_max_slices)
                    exp_slices = self._get_series_expected_slices(cand_sn)
                    if download_mode:
                        # During active download, use controlled per-series warmup
                        # limits and only queue series with local files available.
                        if exp_slices > 0 and exp_slices > int(self._DL_WARMUP_MAX_SLICES):
                            continue
                        if self._count_series_files_on_disk(cand_sn) <= 0:
                            continue
                    else:
                        if exp_slices > 0 and exp_slices > int(self._warmup_max_slices):
                            continue
                    queue.append(cand_sn)
                except Exception:
                    continue

            if queue:
                queue = queue[: self._LOOKAHEAD_COUNT]
                if download_mode:
                    for cand_sn in queue:
                        self._enqueue_download_warmup(cand_sn, force=True)
                    print(
                        f"[ZetaBoost][LOOKAHEAD][DL] series={sn} -> queued {len(queue)} adjacent: {queue}"
                    )
                else:
                    self.zeta_boost.enqueue_many_warmup(queue)
                    print(
                        f"[ZetaBoost][LOOKAHEAD] series={sn} -> pre-warming {len(queue)} adjacent: {queue}"
                    )
        except Exception as e:
            try:
                self.logger.debug(f"Look-ahead warmup error: {e}")
            except Exception:
                pass

    def _get_series_expected_slices(self, series_number: str) -> int:
        resolution = self._resolve_series_expected_count(series_number)
        return int(resolution.expected_count or 0)

    # SOP Class UID prefixes that never contain renderable image pixels.
    _NON_IMAGE_SOP_PREFIXES = (
        '1.2.840.10008.5.1.4.1.1.88.',    # Structured Report variants
        '1.2.840.10008.5.1.4.1.1.11.',    # Presentation State
        '1.2.840.10008.5.1.4.1.1.104.',   # Encapsulated PDF / CDA
        '1.2.840.10008.5.1.4.1.1.66.',    # Raw Data Storage
        '1.2.840.10008.5.1.4.1.1.9.',     # Waveform variants
        '1.2.840.10008.5.1.4.1.1.481.2',  # RT Dose
        '1.2.840.10008.5.1.4.1.1.481.3',  # RT Structure Set
        '1.2.840.10008.5.1.4.1.1.481.5',  # RT Plan
        '1.2.840.10008.5.1.4.1.1.481.8',  # RT Ion Plan
        '1.2.840.10008.5.1.4.34.',        # Unified Worklist / UPS
    )
    _NON_IMAGE_MODALITIES = frozenset({'SR', 'KO', 'PR', 'DOC', 'FID', 'PLAN', 'REG'})

    def _is_series_image_type_for_warmup(self, series_number: str) -> bool:
        """Fast pre-check: does the first DICOM file look like a renderable image?

        Returns False for Structured Reports, Presentation States, Dose Reports,
        Raw Data, Waveforms, and any DICOM without Rows/Columns pixel attributes.
        Cost: one pydicom header-only read (~0.5 ms).
        """
        sn = str(series_number)
        cache_key = f"{sn}_imgtype"
        cached = self._series_warmup_eligibility_cache.get(cache_key)
        if cached is not None:
            return bool(cached)
        try:
            study_path = self._get_correct_study_path()
            if not study_path:
                return True  # cannot check, let the loader decide
            series_dir = Path(study_path) / sn
            if not series_dir.exists() or not series_dir.is_dir():
                return True
            dcm_file = next(
                (p for p in series_dir.iterdir() if p.is_file() and p.suffix.lower() == '.dcm'),
                None,
            )
            if dcm_file is None:
                self._series_warmup_eligibility_cache[cache_key] = False
                return False
            ds = pydicom.dcmread(
                str(dcm_file), stop_before_pixels=True, force=True,
                specific_tags=['SOPClassUID', 'Rows', 'Columns', 'Modality'],
            )
            # Check SOP Class UID against known non-image prefixes.
            sop = str(getattr(ds, 'SOPClassUID', '') or '')
            for prefix in self._NON_IMAGE_SOP_PREFIXES:
                if sop.startswith(prefix):
                    self._series_warmup_eligibility_cache[cache_key] = False
                    return False
            # Check Modality tag.
            modality = str(getattr(ds, 'Modality', '') or '').upper().strip()
            if modality in self._NON_IMAGE_MODALITIES:
                self._series_warmup_eligibility_cache[cache_key] = False
                return False
            # Must have pixel dimensions.
            rows = int(getattr(ds, 'Rows', 0) or 0)
            cols = int(getattr(ds, 'Columns', 0) or 0)
            if rows <= 0 or cols <= 0:
                self._series_warmup_eligibility_cache[cache_key] = False
                return False
            self._series_warmup_eligibility_cache[cache_key] = True
            return True
        except Exception:
            return True  # cannot parse â†’ let the loader try

    def _is_series_header_consistent_for_warmup(self, series_number: str) -> bool:
        """
        Lightweight precheck to avoid warming known malformed mixed-size series.
        Reads a small capped subset of DICOM headers only (no pixel data).
        """
        sn = str(series_number)
        cached = self._series_warmup_eligibility_cache.get(sn)
        if cached is not None:
            return bool(cached)

        try:
            study_path = self._get_correct_study_path()
            if not study_path:
                self._series_warmup_eligibility_cache[sn] = True
                return True

            series_dir = Path(study_path) / sn
            if not series_dir.exists() or not series_dir.is_dir():
                self._series_warmup_eligibility_cache[sn] = True
                return True

            dcm_files = [p for p in series_dir.iterdir() if p.is_file() and p.suffix.lower() == '.dcm']
            if len(dcm_files) < 2:
                # Single-file series: image-type check already done by
                # _is_series_image_type_for_warmup; consistency is vacuously true.
                self._series_warmup_eligibility_cache[sn] = True
                return True

            dcm_files = sorted(dcm_files, key=lambda p: p.name)[:8]

            expected = None
            parsed = 0
            for fp in dcm_files:
                try:
                    ds = pydicom.dcmread(
                        str(fp),
                        stop_before_pixels=True,
                        force=True,
                        specific_tags=['Rows', 'Columns', 'SamplesPerPixel', 'BitsAllocated']
                    )
                    sig = (
                        int(getattr(ds, 'Rows', 0) or 0),
                        int(getattr(ds, 'Columns', 0) or 0),
                        int(getattr(ds, 'SamplesPerPixel', 1) or 1),
                        int(getattr(ds, 'BitsAllocated', 0) or 0),
                    )
                    if sig[0] <= 0 or sig[1] <= 0:
                        continue
                    parsed += 1
                    if expected is None:
                        expected = sig
                    elif sig != expected:
                        self._series_warmup_eligibility_cache[sn] = False
                        return False
                except Exception:
                    continue

            # If we couldn't parse enough headers, do not block warmup.
            ok = parsed < 2 or expected is not None
            self._series_warmup_eligibility_cache[sn] = bool(ok)
            return bool(ok)
        except Exception:
            self._series_warmup_eligibility_cache[sn] = True
            return True

    def _estimate_series_cache_bytes(self, series_number: str) -> int:
        """Estimate series memory footprint for warmup admission control."""
        sn = str(series_number)
        try:
            flat = self._metadata_flat_cache.get(sn) or {}
            inst = flat.get('instances') or []
            if isinstance(inst, list) and inst:
                first = inst[0] if isinstance(inst[0], dict) else {}
            else:
                first = {}

            rows = int(first.get('rows', 0) or 0)
            cols = int(first.get('columns', 0) or 0)
            samples = int(first.get('samples_per_pixel', 1) or 1)
            bits_allocated = int(first.get('bits_allocated', 16) or 16)
            bytes_per_sample = max(1, bits_allocated // 8)
            if rows <= 0 or cols <= 0:
                # Conservative default for unknown headers.
                rows, cols = 512, 512

            slices = int(self._get_series_expected_slices(sn) or 0)
            if slices <= 0:
                slices = 1

            est = int(rows * cols * slices * max(1, samples) * bytes_per_sample)
            return max(est, 1)
        except Exception:
            return 1

    def _is_series_cached_non_mutating(self, series_number: str) -> bool:
        """Check cache presence without triggering disk reads or cache churn."""
        sn = str(series_number)
        if not sn:
            return False
        try:
            if self.zeta_boost.has_any_cache_non_mutating(sn):
                return True
        except Exception:
            pass
        try:
            return self._full_cache_key(sn) in self._full_series_cache
        except Exception:
            return False

    def _is_series_in_memory_only(self, series_number: str) -> bool:
        """True only when series data is in RAM (instant access, no disk I/O).

        Use this in warmup/prefetch filtering instead of _is_series_cached_non_mutating
        so that disk-only entries ARE queued for memory promotion.
        """
        sn = str(series_number)
        if not sn:
            return False
        try:
            if self.zeta_boost.has_in_memory(sn):
                return True
        except Exception:
            pass
        try:
            return self._full_cache_key(sn) in self._full_series_cache
        except Exception:
            return False

    def _filter_heavy_candidates_by_capacity(self, heavy_candidates: list[str]) -> tuple[list[str], list[str], int, int, int]:
        """Capacity-aware admission for heavy warmup.

        Prevents structural churn where large background warmups evict each other
        before user interaction can benefit from them.

        SYSTEM RAM CHECK: If available system RAM is below a safety threshold,
        heavy warmup is skipped entirely so ZetaBoost doesn't pressure the system.
        ZetaBoost is a helper â€” it must never degrade the main workflow.
        """
        # â”€â”€ System RAM guard â”€â”€
        # Skip heavy warmup entirely if the OS is already under memory pressure.
        # This keeps ZetaBoost from pushing the system into swap / OOM territory.
        try:
            import psutil
            mem = psutil.virtual_memory()
            avail_mb = int(mem.available / (1024 * 1024))
            _system_reserve_mb = 1200  # keep at least 1.2 GB free for OS + app
            if avail_mb < _system_reserve_mb:
                print(
                    f"âڑ ï¸ڈ [ZetaBoost][RAM_GUARD] skipping heavy warmup â€” "
                    f"available={avail_mb}MB < reserve={_system_reserve_mb}MB"
                )
                return [], list(heavy_candidates), 0, 0, 0
        except Exception:
            pass  # psutil unavailable â†’ fall through to budget-based check

        try:
            snap = self.zeta_boost.get_capacity_snapshot()
            current_bytes = int(snap.get('bytes', 0) or 0)
            budget_bytes = int(snap.get('byte_budget', 0) or 0)
        except Exception:
            current_bytes = int(getattr(self, '_full_series_cache_bytes', 0) or 0)
            budget_bytes = int(getattr(self, '_full_series_cache_byte_budget', 0) or 0)

        if budget_bytes <= 0:
            return list(heavy_candidates), [], current_bytes, budget_bytes, 0

        # Keep safety headroom for interactive path + metadata/object overhead.
        reserve_bytes = max(int(budget_bytes * 0.15), 150 * 1024 * 1024)

        # Also cap budget vs system available RAM so we never push the system.
        try:
            import psutil
            avail_bytes = int(psutil.virtual_memory().available)
            # Don't let warmup consume more than 50% of available RAM.
            ram_ceiling = int(avail_bytes * 0.50)
            effective_budget = min(budget_bytes, current_bytes + ram_ceiling)
        except Exception:
            effective_budget = budget_bytes

        allowed_extra = max(0, effective_budget - current_bytes - reserve_bytes)

        if not heavy_candidates:
            return [], [], current_bytes, budget_bytes, reserve_bytes

        admitted = []
        dropped = []
        used_extra = 0

        for sn in heavy_candidates:
            est = self._estimate_series_cache_bytes(sn)
            if (used_extra + est) <= allowed_extra:
                admitted.append(sn)
                used_extra += est
            else:
                dropped.append(sn)

        # Ensure progress: if none admitted, allow one candidate to avoid starvation.
        if not admitted and heavy_candidates:
            admitted = [heavy_candidates[0]]
            dropped = heavy_candidates[1:]

        return admitted, dropped, current_bytes, budget_bytes, reserve_bytes

    # ===== OPTIMIZATION HELPER METHODS: FAST SERIES LOOKUP =====
    
    def _rebuild_series_index(self):
        """Rebuild fast lookup indices from lst_thumbnails_data (called once on data change)"""
        try:
            self._series_number_to_index.clear()
            self._paired_series_map.clear()
            self._metadata_flat_cache.clear()
            
            if not hasattr(self.parent_widget, 'lst_thumbnails_data'):
                return
            
            for idx, item in enumerate(self.parent_widget.lst_thumbnails_data):
                if not isinstance(item, dict):
                    continue
                metadata = item.get('metadata', {})
                series_info = metadata.get('series', {})
                series_number = str(series_info.get('series_number', ''))
                series_name = str(series_info.get('series_name', ''))
                
                if series_number:
                    # Fast index: series_number -> list index
                    self._series_number_to_index[series_number] = idx
                    
                    # Flat metadata cache for quick access without nested lookups
                    self._metadata_flat_cache[series_number] = {
                        'series_number': series_number,
                        'series_name': series_name,
                        'series_path': series_info.get('series_path', ''),
                        'instances': metadata.get('instances', []),
                    }
                    
                    # Paired series map: series_name -> list of numbers
                    if series_name:
                        if series_name not in self._paired_series_map:
                            self._paired_series_map[series_name] = []
                        if series_number not in self._paired_series_map[series_name]:
                            self._paired_series_map[series_name].append(series_number)
        except Exception as e:
            self.logger.debug(f"Error rebuilding series index: {e}")

    def _get_series_by_number_fast(self, series_number: str) -> tuple:
        """
        âڑ، Fast O(1) series lookup using index.
        Returns: (vtk_image_data, metadata, index) or (None, None, -1)
        """
        series_str = str(series_number)
        t_lookup = now_ms()

        def _entry_is_valid(entry) -> bool:
            try:
                if not isinstance(entry, tuple) or len(entry) < 3:
                    return False
                idx = int(entry[2])
                if idx < 0 or idx >= len(self.parent_widget.lst_thumbnails_data):
                    return False
                item = self.parent_widget.lst_thumbnails_data[idx]
                item_series = str(item.get('metadata', {}).get('series', {}).get('series_number', ''))
                if item_series != series_str:
                    return False

                # Critical staleness guard:
                # preview->full replacement keeps same index/series_number, so index-only
                # validation can return stale cached tuples forever.
                # Ensure cached tuple still points to the current list payload.
                cur_vtk = item.get('vtk_image_data')
                cur_meta = item.get('metadata')
                if entry[0] is not cur_vtk or entry[1] is not cur_meta:
                    return False

                return True
            except Exception:
                return False
        
        # 1. Check hot cache first (most recent access)
        if series_str in self._hot_series_cache:
            hot_entry = self._hot_series_cache[series_str]
            if _entry_is_valid(hot_entry):
                logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ HOT CACHE HIT")
                log_stage_timing(
                    self.logger,
                    component="viewer",
                    function="ViewerController._get_series_by_number_fast",
                    stage="cache_lookup",
                    start_ms=t_lookup,
                    cache_result="hot_hit",
                )
                return hot_entry
            self._hot_series_cache.pop(series_str, None)
            logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ hot cache stale, removed")
        
        # 2. Check main cache
        if series_str in self._series_cache:
            result = self._series_cache[series_str]
            if _entry_is_valid(result):
                self._hot_series_cache[series_str] = result
                logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ MAIN CACHE HIT")
                log_stage_timing(
                    self.logger,
                    component="viewer",
                    function="ViewerController._get_series_by_number_fast",
                    stage="cache_lookup",
                    start_ms=t_lookup,
                    cache_result="main_hit",
                )
                return result
            self._series_cache.pop(series_str, None)
            logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ main cache stale, removed")
        
        # 3. Check index for fallback
        if series_str in self._series_number_to_index:
            idx = self._series_number_to_index[series_str]
            logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ found in index, idx={idx}")
            if idx < len(self.parent_widget.lst_thumbnails_data):
                item = self.parent_widget.lst_thumbnails_data[idx]
                vtk_data = item.get('vtk_image_data')
                meta = item.get('metadata')
                logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ item retrieved: vtk={vtk_data is not None}, meta={meta is not None}")
                if vtk_data is not None and meta is not None:
                    result = (vtk_data, meta, idx)
                    self._series_cache[series_str] = result
                    if len(self._hot_series_cache) > 3:  # Keep hot cache small
                        self._hot_series_cache.pop(next(iter(self._hot_series_cache)))
                    self._hot_series_cache[series_str] = result
                    logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ RETURNING from index lookup")
                    log_stage_timing(
                        self.logger,
                        component="viewer",
                        function="ViewerController._get_series_by_number_fast",
                        stage="cache_lookup",
                        start_ms=t_lookup,
                        cache_result="index_hit",
                    )
                    return result
                else:
                    logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ item has None data, continuing to full cache")
            else:
                logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ idx {idx} >= list length {len(self.parent_widget.lst_thumbnails_data)}")
        else:
            logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ NOT in _series_number_to_index")

        # 4. Deterministic full-series cache fallback (survives index churn)
        cached_full = self._full_cache_get(series_str)
        if cached_full is not None:
            vtk_data, meta = cached_full[0], cached_full[1]
            logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ FULL CACHE HIT: vtk={vtk_data is not None}, meta={meta is not None}")
            if vtk_data is not None and isinstance(meta, dict):
                # Rehydrate parent/index caches on demand.
                # IMPORTANT: Never mutate PatientWidget list/index structures from a
                # worker thread. Non-UI writes can race with Qt/UI operations and
                # have caused unstable behavior during rapid drag-drop switching.
                idx = -1
                if self._is_on_ui_thread():
                    try:
                        idx = self.parent_widget.replace_series_data(
                            series_str,
                            vtk_data,
                            meta,
                            meta.get('series', {}).get('thumbnail_path', ''),
                            allow_append_if_missing=True,
                        )
                        logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ rehydrated to lst_thumbnails_data at idx={idx}")
                    except Exception as e:
                        logger.error(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ rehydrate FAILED: {e}")
                        idx = -1
                else:
                    # Worker thread: read-only best-effort index resolution.
                    try:
                        idx = int(self._series_number_to_index.get(series_str, -1))
                    except Exception:
                        idx = -1

                    if idx < 0:
                        try:
                            for i, item in enumerate(self.parent_widget.lst_thumbnails_data):
                                item_series = str(item.get('metadata', {}).get('series', {}).get('series_number', ''))
                                if item_series == series_str:
                                    idx = i
                                    break
                        except Exception:
                            idx = -1

                    # Schedule safe UI-thread rehydrate for subsequent requests.
                    try:
                        self._queue_on_ui_thread(
                            lambda sn=series_str, vd=vtk_data, md=meta: self.parent_widget.replace_series_data(
                                sn,
                                vd,
                                md,
                                md.get('series', {}).get('thumbnail_path', ''),
                                allow_append_if_missing=True,
                            )
                        )
                    except Exception:
                        pass

                if idx >= 0:
                    result = (vtk_data, meta, idx)
                    self._series_cache[series_str] = result
                    self._hot_series_cache[series_str] = result
                    logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ RETURNING from full cache")
                    log_stage_timing(
                        self.logger,
                        component="viewer",
                        function="ViewerController._get_series_by_number_fast",
                        stage="cache_lookup",
                        start_ms=t_lookup,
                        cache_result="full_cache_hit",
                    )
                    return result
        else:
            logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ NOT in full cache")
        
        logger.debug(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ FINAL RETURN: None, None, -1")
        log_stage_timing(
            self.logger,
            component="viewer",
            function="ViewerController._get_series_by_number_fast",
            stage="cache_lookup",
            start_ms=t_lookup,
            cache_result="miss",
        )
        return None, None, -1

    def _get_paired_series_fast(self, series_name: str, exclude_number: str = None) -> list:
        """
        âڑ، Get all paired series (same name, different data) in O(1) time.
        Returns list of (vtk_data, metadata, series_number) tuples
        """
        try:
            if series_name not in self._paired_series_map:
                return []
            
            exclude_number = str(exclude_number) if exclude_number else None
            results = []
            
            for series_num in self._paired_series_map[series_name]:
                if exclude_number and series_num == exclude_number:
                    continue
                
                vtk_data, metadata, _ = self._get_series_by_number_fast(series_num)
                if vtk_data is not None and metadata is not None:
                    results.append((vtk_data, metadata, series_num))
            
            return results
        except Exception as e:
            self.logger.debug(f"Error getting paired series: {e}")
            return []
    


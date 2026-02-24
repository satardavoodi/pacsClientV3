"""
Viewer Controller Module
Encapsulates all viewer-related responsibilities for PatientWidget
"""

import asyncio
import gc
import time
import os
import copy
from PySide6.QtWidgets import QWidget, QVBoxLayout
from pathlib import Path
import numpy as np
import vtk
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QThread, QMetaObject, Signal, Slot, QObject
from PySide6.QtWidgets import QHBoxLayout, QSlider, QLabel, QScrollArea, QGridLayout, QToolBar, QPushButton, \
    QButtonGroup, QStackedWidget, QSizePolicy, QFrame, QGroupBox, QMessageBox, QListWidget, QListWidgetItem, QSplitter, \
    QGraphicsOpacityEffect, QProgressDialog, QWidget, QApplication
from PySide6.QtGui import QPixmap, QColor, QPainter, QPen
import contextlib
import json
import pydicom
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor

from PacsClient.pacs.patient_tab.utils import load_images, save_image_as_png, delete_widgets_in_layout, NodeViewer, \
    get_count_dicom_files_exist, load_images_from_server, VerticalButton
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number, load_series_preview
from PacsClient.pacs.patient_tab.pipeline import (
    PipelineOrchestrator, PipelineState, LoadCoordinator, PreviewEngine,
)
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, CallerTypes
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget, grow_vtk_inplace
from PacsClient.pacs.patient_tab.ui.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.zeta_sync import (
    SyncManager,
    SyncContext,
    SyncMode,
    SyncTarget,
    map_ijk_between_vtk_images,
    build_ijk_to_world_matrix,
    world_to_ijk,
    ijk_to_world,
    is_ijk_in_bounds,
    log_image_orientation,
)
from PacsClient.zeta_download_manager.core.enums import DownloadPriority
from PacsClient.utils.config import SOCKET_CONFIG_PATH
from PacsClient.pacs.patient_tab.zeta_boost import ZetaBoostEngine, ImageSliceBooster
from PacsClient.utils.boost_viewer_config import load_boost_viewer_enabled

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"


class SliceTickSlider(QSlider):
    """
    Custom QSlider that paints per-slice tick marks along the groove.
    • Non-current ticks: thin, semi-transparent.
    • Current-position tick: wider, bright accent colour.
    All painting is done *after* the base QSlider paint so the handle
    is always drawn on top.
    """

    def __init__(self, orientation=Qt.Vertical, parent=None):
        super().__init__(orientation, parent)
        # Theme: muted purple-blue blend
        self._theme_r, self._theme_g, self._theme_b = 110, 90, 210
        self._unvisited_color = QColor(140, 140, 160, 80)   # gray for future slices
        self._current_tick_color = QColor(self._theme_r, self._theme_g, self._theme_b, 240)

    # ------------------------------------------------------------------ #
    def paintEvent(self, event):
        # Let Qt draw the normal slider first (groove + handle)
        super().paintEvent(event)

        total = self.maximum() - self.minimum()
        if total <= 0:
            return  # nothing to draw

        painter = QPainter(self)
        # Antialiasing OFF for tick lines so they stay crisp dashes, not blobs
        painter.setRenderHint(QPainter.Antialiasing, False)

        # Usable range (exclude top/bottom padding of 8 px matches stylesheet)
        pad = 8
        groove_top = pad
        groove_bottom = self.height() - pad
        groove_len = groove_bottom - groove_top
        if groove_len <= 0:
            painter.end()
            return

        # Decide max ticks to draw so we don't paint thousands of lines
        max_ticks = min(total + 1, 200)
        step = max(1, total // max_ticks)

        cur_val = self.value()
        inverted = self.invertedAppearance()

        tick_half_w = 4  # dash extends 4px each side of centre (clear line shape)
        cx = self.width() // 2

        # --- draw non-current ticks as flat dashes (never circles) ---
        for i in range(self.minimum(), self.maximum() + 1, step):
            if i == cur_val:
                continue  # draw current separately as dot

            frac = (i - self.minimum()) / total
            if inverted:
                y = int(groove_top + frac * groove_len)
            else:
                y = int(groove_bottom - frac * groove_len)

            passed = (i < cur_val)  # slices the user has scrolled past

            if passed:
                # Fade: slices close to current are vivid, distant ones fade out
                distance = cur_val - i  # always > 0
                alpha = max(40, int(200 - distance * 2.7))
                color = QColor(self._theme_r, self._theme_g, self._theme_b, alpha)
            else:
                # Future / unvisited slices — neutral gray
                color = self._unvisited_color

            pen = QPen(color, 1.0)
            pen.setCapStyle(Qt.FlatCap)  # flat ends → crisp dash, not rounded blob
            painter.setPen(pen)
            painter.drawLine(cx - tick_half_w, y, cx + tick_half_w, y)

        # --- current-position indicator: single filled circle / dot ---
        painter.setRenderHint(QPainter.Antialiasing, True)  # smooth circle only
        frac_cur = (cur_val - self.minimum()) / total
        if inverted:
            y_cur = int(groove_top + frac_cur * groove_len)
        else:
            y_cur = int(groove_bottom - frac_cur * groove_len)

        dot_radius = 5  # 10 px diameter — easy to see and grab
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._current_tick_color)
        painter.drawEllipse(cx - dot_radius, y_cur - dot_radius,
                            dot_radius * 2, dot_radius * 2)

        painter.end()
import logging


class _UISafeInvoker(QObject):
    """Thread-safe helper: emit from ANY thread, slot runs on the GUI thread."""
    _sig = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sig.connect(self._exec, Qt.QueuedConnection)

    @Slot(object)
    def _exec(self, fn):
        try:
            fn()
        except Exception:
            pass

    def invoke(self, fn):
        """Schedule *fn* to run on the GUI thread (safe from any thread)."""
        self._sig.emit(fn)


class ViewerController:
    """
    Encapsulates all viewer-related responsibilities for PatientWidget
    """
    
    def __init__(self, parent_widget):
        self.parent_widget = parent_widget
        self.logger = logging.getLogger(f"{__name__}.ViewerController")
        
        # Thread-safe UI invoker (must live on the GUI thread via parent)
        self._ui_invoker = _UISafeInvoker(parent_widget)
        
        # Viewer-related attributes
        self.lst_nodes_viewer = []
        self.selected_widget = None
        self.slider = None
        
        # Viewer creation protection
        self._max_viewers_per_session = 25
        self._viewer_creation_throttle = 0
        self._last_gc_time = 0
        
        # Memory pools
        self._metadata_pool = {}
        self._layout_pool = []
        
        # Viewer state
        self._first_series_displayed = False
        self._is_initializing = True
        
        # ===== OPTIMIZED PERFORMANCE CACHES =====
        # Series lookup index: series_number -> (vtk_data, metadata, index)
        self._series_cache = {}
        self._series_name_cache = {}
        
        # OPTIMIZATION: O(1) series number to list index lookup
        self._series_number_to_index = {}
        
        # OPTIMIZATION: Paired series mapping for fast grouped series lookup
        self._paired_series_map = {}  # series_name -> [series_numbers]
        
        # OPTIMIZATION: Fast metadata access without nested dict lookups
        self._metadata_flat_cache = {}  # series_number -> flattened metadata dict
        
        # OPTIMIZATION: Recently accessed series for quick re-access
        self._hot_series_cache = {}  # Most recently accessed (limited size)
        
        # OPTIMIZATION: Pre-load adjacent series in background
        self._preload_queue = []
        self._preload_thread = None
        
        self._viewer_batch_queue = []
        self._async_switch_inflight = set()  # {(viewer_id, series_number)}
        
        # Performance optimization flags
        self._critical_sections_running = 0
        self._render_batch_pending = False
        self._pending_thumbnail_updates = []
        self._image_cache_max_size = 10

        # Track current layout to avoid redundant re-applies
        self._current_layout = None

        # Per-viewport request/version state to avoid stale async apply
        self._viewer_request_token = {}  # viewer_id -> token

        # Opportunistic background prefetch (Step-4 warmup)
        self._prefetch_thread = None
        self._prefetch_stop_event = threading.Event()
        self._prefetch_inflight = set()  # {series_number}
        self._prefetch_loaded = set()    # {series_number}
        self._loading_series_numbers = set()  # protects duplicate interactive loads
        self._series_load_events = {}  # series_number -> threading.Event
        self._series_load_lock = threading.Lock()
        self._prefetch_max_series = 24

        self._prefetch_delay_ms = 120
        self._interactive_load_in_progress = False

        # ── Dynamic capacity: scale limits to system RAM ──
        _cap = self._compute_dynamic_capacity()
        self._capacity_tier = _cap  # keep for diagnostics

        # Guard against warmup overloading with very large stacks.
        self._warmup_max_slices = _cap['warmup_max_slices']
        # Fast precheck cache: series_number -> header-consistent bool
        self._series_warmup_eligibility_cache = {}
        # Two-phase warmup: light first, then heavy in deferred background.
        self._deferred_heavy_warmup_series = []
        self._deferred_heavy_warmup_retry_count = 0
        self._last_user_interaction_ts = time.time()
        self._heavy_warmup_idle_sec = 2.5

        # Deterministic full-series cache — now single-layer (ZetaBoost only).
        # Legacy dict fields kept as empty stubs for any residual references.
        self._full_series_cache = {}
        self._full_series_cache_order = []
        self._full_series_cache_max = _cap['max_entries']
        self._full_series_cache_bytes = 0
        self._full_series_cache_byte_budget = _cap['byte_budget']
        # Keep large stacks eligible for prefetch so first drag-drop can hit cache.
        self._prefetch_skip_slices_threshold = self._warmup_max_slices
        self._tab_active = False
        self._first_use_prime_started = False
        self._open_warmup_retry_count = 0
        self._warmup_gather_running = False
        self._zeta_boost_failed_series = set()
        self._warmup_corrupt_skip_counts = {}
        self._warmup_corrupt_skip_threshold = 3
        self._zeta_external_busy_last = None
        self._zeta_manual_triggered = False

        # ── Pipeline orchestrator (replaces timer-based download gating) ──
        self.pipeline = PipelineOrchestrator(
            on_state_changed=self._on_pipeline_state_changed,
            logger=self.logger,
        )
        self._load_coordinator = LoadCoordinator()
        self._preview_engine = PreviewEngine(logger=self.logger)

        # ZetaBoost: active-tab-only cache + serialized preloading.
        self.zeta_boost = ZetaBoostEngine(
            tab_key=str(getattr(parent_widget, 'study_uid', '') or 'unknown'),
            estimate_bytes_fn=self._estimate_vtk_bytes,
            load_series_callback=self._zeta_boost_load_series,
            max_entries=_cap['max_entries'],
            byte_budget=_cap['byte_budget'],
            max_parallel_loads=_cap['max_parallel_loads'],
            warmup_workers=_cap['warmup_workers'],
            background_workers=_cap['background_workers'],
            disk_persist_max_bytes=_cap['disk_persist_max'],
            logger=self.logger,
        )
        self._boostviewer_enabled = self._is_boostviewer_enabled_runtime()
        # Mode B: Image Slice Booster — lightweight ±20 slice window cache for
        # the single active series.  Zero RAM impact on other series.
        self._image_slice_booster: ImageSliceBooster = ImageSliceBooster(
            logger=self.logger
        )
        print(
            f"🔧 [ZetaBoost][CAPACITY] tier={_cap['tier']} RAM={_cap['total_ram_mb']}MB "
            f"budget={_cap['byte_budget']//(1024*1024)}MB entries={_cap['max_entries']} "
            f"parallel={_cap['max_parallel_loads']} warmup_workers={_cap['warmup_workers']} "
            f"heavy_threshold={_cap['warmup_max_slices']}slices "
            f"disk_persist_max={_cap['disk_persist_max']//(1024*1024)}MB"
        )

    def _ensure_grid_config_exists(self):
        """Create the modality grid config if missing."""
        if GRID_CONFIG_PATH.exists():
            return

        default_config = {
            "default": {"rows": 1, "cols": 2},
            "modality_layouts": {
                "CT": {"rows": 1, "cols": 2},
                "MR": {"rows": 1, "cols": 2},
                "MG": {"rows": 2, "cols": 2},
                "CR": {"rows": 1, "cols": 2},
                "DX": {"rows": 1, "cols": 2},
                "US": {"rows": 1, "cols": 2},
                "XA": {"rows": 1, "cols": 2},
                "RF": {"rows": 1, "cols": 2},
                "NM": {"rows": 1, "cols": 2},
                "PT": {"rows": 1, "cols": 2},
                "OT": {"rows": 1, "cols": 2}
            }
        }

        try:
            GRID_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(GRID_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            print(f"✅ Default modality grid config created: {GRID_CONFIG_PATH}")
        except Exception as e:
            print(f"⚠️ Could not create default grid config: {e}")

    def _is_boostviewer_enabled_runtime(self) -> bool:
        try:
            return bool(load_boost_viewer_enabled(default=True))
        except Exception:
            return True

    @staticmethod
    def _compute_dynamic_capacity() -> dict:
        """Scale ZetaBoost capacity to system RAM.

        Ensures high-capacity studies are handled without artificial limits:
        - 20+ series (cardiac/prostate MRI)
        - 700+ images per series (dynamic series)
        - 2000+ images per series (perfusion runs)

        Tiers (by total physical RAM):
            ≥30 GB  → 4 GB budget, 60 entries, 3 parallel, 3 warmup workers
            ≥15 GB  → 2.4 GB budget, 48 entries, 3 parallel, 3 warmup workers
            ≥7.5 GB → 1.6 GB budget, 36 entries, 2 parallel, 2 warmup workers
            <7.5 GB → 1.2 GB budget, 24 entries, 2 parallel, 2 warmup workers

        Runtime RAM guards (psutil in _filter_heavy_candidates_by_capacity and
        engine._check_system_memory_ok) still throttle if available RAM drops.
        """
        try:
            import psutil
            total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception:
            total_mb = 8192  # conservative fallback

        MB = 1024 * 1024

        if total_mb >= 30720:  # ≥30 GB
            return {
                'tier': '30GB+',
                'total_ram_mb': total_mb,
                'byte_budget': 2000 * MB,   # enough for 40+ typical CT series
                'max_entries': 40,           # cover large multi-series studies
                'max_parallel_loads': 1,     # NEVER run >1 concurrent ITK load
                'warmup_workers': 3,
                'background_workers': 2,
                'warmup_max_slices': 700,
                'disk_persist_max': 800 * MB,
            }
        elif total_mb >= 15360:  # ≥15 GB
            return {
                'tier': '15GB+',
                'total_ram_mb': total_mb,
                'byte_budget': 1200 * MB,   # ~24 series × 50 MB each
                'max_entries': 24,
                'max_parallel_loads': 1,
                'warmup_workers': 2,
                'background_workers': 1,
                'warmup_max_slices': 600,
                'disk_persist_max': 600 * MB,
            }
        elif total_mb >= 7680:  # ≥7.5 GB
            return {
                'tier': '8GB+',
                'total_ram_mb': total_mb,
                'byte_budget': 800 * MB,    # ~16 series × 50 MB each; safe on 8 GB
                'max_entries': 16,           # covers full 10-series study + headroom
                'max_parallel_loads': 1,     # single ITK load to avoid GIL contention
                'warmup_workers': 2,
                'background_workers': 1,
                'warmup_max_slices': 500,    # raised from 250 → series with 356 slices now eligible
                'disk_persist_max': 500 * MB,
            }
        else:  # <7.5 GB
            return {
                'tier': 'low',
                'total_ram_mb': total_mb,
                'byte_budget': 400 * MB,    # ~8 series × 50 MB each
                'max_entries': 8,
                'max_parallel_loads': 1,
                'warmup_workers': 1,
                'background_workers': 1,
                'warmup_max_slices': 250,
                'disk_persist_max': 300 * MB,
            }

    def _is_drag_drop_action_id(self, action_id) -> bool:
        try:
            aid = str(action_id or '')
            return aid.startswith('drag_drop-')
        except Exception:
            return False

    def _is_thumbnail_click_action_id(self, action_id) -> bool:
        try:
            aid = str(action_id or '')
            return aid.startswith('thumb_click-')
        except Exception:
            return False

    def _is_explicit_view_request(self, action_id, flag_change_selected_widget: bool) -> bool:
        """User-intent view request in Patient tab.

        Includes:
        - drag/drop (explicit action id)
        - thumbnail click/double-click path (selected-widget switch request)
        """
        try:
            if self._is_drag_drop_action_id(action_id):
                return True
            if self._is_thumbnail_click_action_id(action_id):
                return True
            return False
        except Exception:
            return False

    def _activate_zeta_manual_trigger(self, reason: str = ""):
        """Manual-trigger mode (BoostViewer OFF): activate cache engine on explicit user view requests."""
        try:
            if self._boostviewer_enabled:
                return
            if self._zeta_manual_triggered and self.zeta_boost.is_active():
                return
            self._zeta_manual_triggered = True
            self.zeta_boost.activate()
            if reason:
                print(
                    f"🚀 [ZetaBoost][MANUAL_TRIGGER] study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                    f"reason={reason}"
                )
        except Exception:
            pass

    def _zeta_boost_load_series(self, series_number: str):
        """Background worker callback used by ZetaBoost to warm/cache series.

        FULLY INDEPENDENT — no shared locks with the interactive/viewer path.
        The engine worker already attempts disk→memory promotion before
        calling this.  If we reach here, the series must be loaded from
        DICOM source.  If the interactive viewer is already loading the
        same series, this callback yields immediately (skip) so we never
        duplicate expensive I/O.
        """
        try:
            _cb_start = time.perf_counter()
            if not self._tab_active:
                print(f"🔧 [WARMUP_CB] series={series_number} → skip (tab inactive)")
                return True
            sn = str(series_number)
            if not sn.isdigit():
                return True

            # Avoid repeated expensive attempts for series that already failed deterministically.
            if sn in self._zeta_boost_failed_series:
                print(f"🔧 [WARMUP_CB] series={sn} → skip (previously failed)")
                return True

            # Check if engine’s disk promotion already placed it in memory
            # (fast O(1) memory-only check, no disk I/O).
            if self.zeta_boost.has_in_memory(sn):
                print(f"🔧 [WARMUP_CB] series={sn} → skip (already in memory) {(time.perf_counter()-_cb_start)*1000:.1f}ms")
                return True

            # Fast path: reuse already-loaded series data if available in thumbnail cache.
            try:
                vtk_existing, meta_existing, _idx = self._get_series_by_number_fast(sn)
                if vtk_existing is not None and isinstance(meta_existing, dict):
                    dims = vtk_existing.GetDimensions() if hasattr(vtk_existing, 'GetDimensions') else (0, 0, 0)
                    if (
                        dims and int(dims[0]) > 0 and int(dims[1]) > 0 and int(dims[2]) > 0
                        and self._is_full_volume_cache_candidate(sn, vtk_existing, meta_existing)
                    ):
                        self._full_cache_put(sn, vtk_existing, meta_existing)
                        print(f"🔧 [WARMUP_CB] series={sn} → reused from thumbnail cache {(time.perf_counter()-_cb_start)*1000:.1f}ms")
                        return True
            except Exception:
                pass
            print(f"🔧 [WARMUP_CB] series={sn} → starting DICOM load...")

            study_path = self._get_correct_study_path()
            if not study_path:
                return False

            # Yield to interactive via LoadCoordinator: if any path is
            # already loading this series, warmup skips to avoid duplicate I/O.
            _coord_status, _coord_event = self._load_coordinator.try_acquire(sn, owner='warmup')
            if _coord_status == 'skip':
                print(f"🔧 [WARMUP_CB] series={sn} → skip (another load in progress)")
                return True
            # Also check legacy dedup set for extra safety.
            with self._series_load_lock:
                if sn in self._loading_series_numbers:
                    self._load_coordinator.complete(sn)
                    print(f"🔧 [WARMUP_CB] series={sn} → skip (interactive is loading)")
                    return True

            # Load DICOM+ITK independently (no shared lock with viewer).
            result_gen = load_single_series_by_number(
                study_path=study_path,
                series_number=int(sn),
                patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
                skip_fs_validation=True,  # warmup: trust DB paths, skip glob+exists
            )

            def _mark_failed(reason: str):
                """Record the series as permanently failed with a reason tag."""
                self._zeta_boost_failed_series.add(sn)
                print(f"⚠️ [WARMUP_CB] series={sn} SKIP reason={reason}")

            cached_ok = False
            item_count = 0
            try:
                for item in result_gen:
                    item_count += 1
                    vtk_image_data, metadata, _patient_study = item
                    if vtk_image_data is None or not isinstance(metadata, dict):
                        continue
                    dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
                    if int(dims[0]) <= 0 or int(dims[1]) <= 0:
                        continue
                    self._full_cache_put(sn, vtk_image_data, metadata)
                    cached_ok = True
                    
                    # ✅ OPTIMIZATION: بعد از cache put، prefetch سریز مجاور بلافاصله
                    threading.Thread(
                        target=self._prefetch_adjacent_series,
                        args=(sn,),
                        daemon=True
                    ).start()
                    
                    break
            except Exception as iter_err:
                print(f"⚠️ [WARMUP_CB] series={sn} iteration error: {iter_err}")
            finally:
                # Release LoadCoordinator lock so interactive callers unblock.
                self._load_coordinator.complete(sn)

            _load_elapsed = (time.perf_counter() - _cb_start) * 1000
            if cached_ok:
                print(f"🔧 [WARMUP_CB] series={sn} → OK {_load_elapsed:.0f}ms")
                return True
            # ---- failure categorization ----
            if item_count == 0:
                _mark_failed("no_dicom_data")
                print(
                    f"🔧 [WARMUP_CB] series={sn} → FAILED(no_data) {_load_elapsed:.0f}ms "
                    f"reason: generator yielded nothing — non-image DICOM, missing files, or unsupported format"
                )
            else:
                _mark_failed("no_usable_vtk")
                print(
                    f"🔧 [WARMUP_CB] series={sn} → FAILED(no_usable_vtk) items={item_count} "
                    f"{_load_elapsed:.0f}ms reason: loaded but VTK data was None or had zero dimensions"
                )
            return False
        except Exception as e:
            try:
                self._load_coordinator.complete(str(series_number))
            except Exception:
                pass
            try:
                self._zeta_boost_failed_series.add(str(series_number))
            except Exception:
                pass
            self.logger.debug(f"ZetaBoost callback failed for series {series_number}: {e}")
            return False

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
                    f"✅ [TAB-LIFECYCLE] ACTIVE(manual-trigger) study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
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
                f"✅ [TAB-LIFECYCLE] ACTIVE study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                f"zeta_boost_active={self.zeta_boost.is_active()}"
            )
        except Exception:
            pass
        try:
            if self._first_series_displayed:
                QTimer.singleShot(250, self._start_background_prefetch)
        except Exception:
            pass
        # Start warmup shortly after tab-open bootstrap to avoid competing with first render.
        try:
            # Mode A detection: if pipeline is still IDLE when tab activates,
            # there's no download session — all series are pre-downloaded.
            # This unlocks ZetaBoost warmup immediately.
            if self.pipeline.state == PipelineState.IDLE:
                self.pipeline.mark_pre_downloaded()
            # Force-sync ZetaBoost engine flags with current pipeline state on every
            # activation.  Handles the case where download started while the tab was
            # inactive (engine was deactivated by _on_pipeline_state_changed).
            if self.pipeline.state in (PipelineState.POST_DOWNLOAD, PipelineState.READY):
                self.zeta_boost.set_study_download_complete(True)
                self.zeta_boost.set_download_active(False)
            elif self.pipeline.state == PipelineState.DOWNLOADING:
                # Tab is being activated while a download is still in progress.
                # Sync engine flags so it knows warmup is blocked.  Workers are
                # alive again (activate() was called above) but gated by download_active.
                self.zeta_boost.set_study_download_complete(False)
                self.zeta_boost.set_download_active(True)
                self.zeta_boost.set_image_boost_mode(True)
            # Schedule warmup check.  _start_open_tab_warmup guards itself with
            # pipeline.is_warmup_allowed, so this is a no-op if downloading.
            QTimer.singleShot(900, self._start_open_tab_warmup)
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
            self.zeta_boost.deactivate(clear_cache=True)
        except Exception:
            pass
        try:
            print(
                f"🛑 [TAB-LIFECYCLE] INACTIVE study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
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
        key_sn = str(series_number)
        # ALWAYS instant: use engine.query() for O(1) memory-only lookup.
        # Disk-cache promotion happens exclusively inside engine workers
        # (via _try_promote_disk_to_memory).  The viewer never touches
        # the disk cache — if ZetaBoost isn't ready, the viewer loads
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
                    print(f"🔍 [CACHE_GET] series={key_sn} source=zeta_boost {_fcg_ms:.0f}ms")
                return val
        except Exception:
            pass
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
        # OFF mode policy: write cache only after explicit manual trigger (drag/drop).
        if (not self._boostviewer_enabled) and (not self._zeta_manual_triggered):
            return
        if not self._is_full_volume_cache_candidate(str(series_number), vtk_image_data, metadata):
            return
        try:
            self.zeta_boost.put(series_number, vtk_image_data, metadata)
        except Exception:
            pass

    # ── Look-ahead warmup: pre-cache adjacent series after drag-drop ──
    _LOOKAHEAD_COUNT = 2  # number of adjacent series to pre-warm after drag-drop

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
            # Don't do look-ahead when ZetaBoost is not allowed to warm
            if not self.pipeline.is_warmup_allowed:
                return

            sn = str(series_number)
            thumb_data = getattr(self.parent_widget, 'lst_thumbnails_data', None) or []
            if not thumb_data:
                return

            # Find the current series position in the thumbnail list
            current_idx = self._series_number_to_index.get(sn)
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
                    if exp_slices > 0 and exp_slices > int(self._warmup_max_slices):
                        continue
                    queue.append(cand_sn)
                except Exception:
                    continue

            if queue:
                self.zeta_boost.enqueue_many_warmup(queue)
                print(
                    f"🔮 [ZetaBoost][LOOKAHEAD] series={sn} → pre-warming {len(queue)} adjacent: {queue}"
                )
        except Exception as e:
            try:
                self.logger.debug(f"Look-ahead warmup error: {e}")
            except Exception:
                pass

    def _get_series_expected_slices(self, series_number: str) -> int:
        sn = str(series_number)
        scan_cap = max(int(self._warmup_max_slices or 0), int(self._prefetch_skip_slices_threshold or 0), 0) + 1
        try:
            # Fast metadata-flat cache (doesn't require VTK loaded)
            flat = self._metadata_flat_cache.get(sn)
            if isinstance(flat, dict):
                if bool(flat.get('preview_only', False)):
                    ptotal = flat.get('preview_total_instances', 0)
                    try:
                        ptotal = int(ptotal)
                    except Exception:
                        ptotal = 0
                    if ptotal > 0:
                        return ptotal
                inst = flat.get('instances') or []
                if isinstance(inst, list) and len(inst) > 0:
                    return int(len(inst))
        except Exception:
            pass

        try:
            # Direct thumbnail metadata fallback (often contains image_count)
            idx = self._series_number_to_index.get(sn)
            if idx is not None and 0 <= int(idx) < len(self.parent_widget.lst_thumbnails_data):
                item = self.parent_widget.lst_thumbnails_data[int(idx)]
                meta = item.get('metadata') or {}
                if isinstance(meta, dict):
                    if bool(meta.get('preview_only', False)):
                        ptotal = meta.get('preview_total_instances', 0)
                        try:
                            ptotal = int(ptotal)
                        except Exception:
                            ptotal = 0
                        if ptotal > 0:
                            return ptotal
                    inst = meta.get('instances') or []
                    if isinstance(inst, list) and len(inst) > 0:
                        return int(len(inst))
                    series_info = meta.get('series') or {}
                    for key in ('image_count', 'number_of_instances', 'instances_count'):
                        val = series_info.get(key)
                        if val is not None:
                            try:
                                iv = int(val)
                                if iv > 0:
                                    return iv
                            except Exception:
                                pass
        except Exception:
            pass

        # NOTE: A previous "last resort" fallback called _get_series_by_number_fast(sn)
        # here.  That triggered _full_cache_get → zeta_boost.get(memory_only=False) on
        # background warmup threads, causing FULL disk decompression + VTK reconstruction
        # as a side effect of just counting slices.  This bypassed the engine's priority
        # queue entirely (every series was already in-memory by the time enqueue ran) and
        # eliminated the benefit of INTERACTIVE_BUSY.  Removed in favour of the lightweight
        # on-disk file-count below which is O(n) directory iter, no heavy I/O.

        try:
            # Final fallback for non-hydrated metadata: lightweight capped on-disk count.
            # We intentionally stop at threshold+1, because warmup only needs large/not-large.
            study_path = self._get_correct_study_path()
            if study_path:
                series_dir = Path(study_path) / sn
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
            return True  # cannot parse → let the loader try

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
        ZetaBoost is a helper — it must never degrade the main workflow.
        """
        # ── System RAM guard ──
        # Skip heavy warmup entirely if the OS is already under memory pressure.
        # This keeps ZetaBoost from pushing the system into swap / OOM territory.
        try:
            import psutil
            mem = psutil.virtual_memory()
            avail_mb = int(mem.available / (1024 * 1024))
            _system_reserve_mb = 1200  # keep at least 1.2 GB free for OS + app
            if avail_mb < _system_reserve_mb:
                print(
                    f"⚠️ [ZetaBoost][RAM_GUARD] skipping heavy warmup — "
                    f"available={avail_mb}MB < reserve={_system_reserve_mb}MB"
                )
                return [], list(heavy_candidates), 0, 0, 0
        except Exception:
            pass  # psutil unavailable → fall through to budget-based check

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
        ⚡ Fast O(1) series lookup using index.
        Returns: (vtk_image_data, metadata, index) or (None, None, -1)
        """
        series_str = str(series_number)

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
                print(f"🔍 [FAST_LOOKUP] series={series_str} → HOT CACHE HIT")
                return hot_entry
            self._hot_series_cache.pop(series_str, None)
            print(f"🔍 [FAST_LOOKUP] series={series_str} → hot cache stale, removed")
        
        # 2. Check main cache
        if series_str in self._series_cache:
            result = self._series_cache[series_str]
            if _entry_is_valid(result):
                self._hot_series_cache[series_str] = result
                print(f"🔍 [FAST_LOOKUP] series={series_str} → MAIN CACHE HIT")
                return result
            self._series_cache.pop(series_str, None)
            print(f"🔍 [FAST_LOOKUP] series={series_str} → main cache stale, removed")
        
        # 3. Check index for fallback
        if series_str in self._series_number_to_index:
            idx = self._series_number_to_index[series_str]
            print(f"🔍 [FAST_LOOKUP] series={series_str} → found in index, idx={idx}")
            if idx < len(self.parent_widget.lst_thumbnails_data):
                item = self.parent_widget.lst_thumbnails_data[idx]
                vtk_data = item.get('vtk_image_data')
                meta = item.get('metadata')
                print(f"🔍 [FAST_LOOKUP] series={series_str} → item retrieved: vtk={vtk_data is not None}, meta={meta is not None}")
                if vtk_data is not None and meta is not None:
                    result = (vtk_data, meta, idx)
                    self._series_cache[series_str] = result
                    if len(self._hot_series_cache) > 3:  # Keep hot cache small
                        self._hot_series_cache.pop(next(iter(self._hot_series_cache)))
                    self._hot_series_cache[series_str] = result
                    print(f"🔍 [FAST_LOOKUP] series={series_str} → RETURNING from index lookup")
                    return result
                else:
                    print(f"🔍 [FAST_LOOKUP] series={series_str} → item has None data, continuing to full cache")
            else:
                print(f"🔍 [FAST_LOOKUP] series={series_str} → idx {idx} >= list length {len(self.parent_widget.lst_thumbnails_data)}")
        else:
            print(f"🔍 [FAST_LOOKUP] series={series_str} → NOT in _series_number_to_index")

        # 4. Deterministic full-series cache fallback (survives index churn)
        cached_full = self._full_cache_get(series_str)
        if cached_full is not None:
            vtk_data, meta = cached_full[0], cached_full[1]
            print(f"🔍 [FAST_LOOKUP] series={series_str} → FULL CACHE HIT: vtk={vtk_data is not None}, meta={meta is not None}")
            if vtk_data is not None and isinstance(meta, dict):
                # Rehydrate parent/index caches on demand
                try:
                    idx = self.parent_widget.replace_series_data(series_str, vtk_data, meta, meta.get('series', {}).get('thumbnail_path', ''))
                    print(f"🔍 [FAST_LOOKUP] series={series_str} → rehydrated to lst_thumbnails_data at idx={idx}")
                except Exception as e:
                    print(f"🔍 [FAST_LOOKUP] series={series_str} → rehydrate FAILED: {e}")
                    idx = -1
                if idx >= 0:
                    result = (vtk_data, meta, idx)
                    self._series_cache[series_str] = result
                    self._hot_series_cache[series_str] = result
                    print(f"🔍 [FAST_LOOKUP] series={series_str} → RETURNING from full cache")
                    return result
        else:
            print(f"🔍 [FAST_LOOKUP] series={series_str} → NOT in full cache")
        
        print(f"🔍 [FAST_LOOKUP] series={series_str} → FINAL RETURN: None, None, -1")
        return None, None, -1

    def _get_paired_series_fast(self, series_name: str, exclude_number: str = None) -> list:
        """
        ⚡ Get all paired series (same name, different data) in O(1) time.
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
    
    def init_matrix_viewers(self, numbers=None):
        """Initialize matrix of viewers based on layout"""
        if numbers is not None:
            # set default-interactorstyle when app started
            self.apply_multi_viewer(numbers)
            if self.selected_widget:
                self.parent_widget.toolbar_manager.current_style = self.selected_widget.style
        else:
            # create dummy image for show until image downloaded.
            dummy_vtk_widget = self.create_dummy_vtk_widget()
            self.parent_widget.vtk_layout.addWidget(dummy_vtk_widget, 0, 0)

    def apply_multi_viewer(self, numbers, modify_by_user=False):
        """
        Apply multi-viewer layout with optimized batch processing
        Reuses existing data and caches when possible
        """
        try:
            rows, cols = int(numbers[0]), int(numbers[1])
            required_count = rows * cols
            current_count = len(self.lst_nodes_viewer)
            current_data_count = len(self.parent_widget.lst_thumbnails_data)

            self._current_layout = (rows, cols)

            print(f"🔧 [LAYOUT] Applying {rows}x{cols} layout (need {required_count} viewers, have {current_count})")

            # ✅ FLICKER FIX: Disable updates during batch viewer creation
            self.parent_widget.setUpdatesEnabled(False)
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(False)

            # 1. Cleanup existing viewers but preserve data
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()
            print("   ✅ cleanup_all_viewers completed")  # No processEvents here

            # 2. Create viewers with existing data assignments
            displayed_series_indices = set()

            for i in range(required_count):
                # Determine which series to show in this viewer
                series_to_show = 0  # Default to first

                # If we have enough data, distribute them
                if current_data_count > 0:
                    # Cycle through available series if more viewers than series
                    series_to_show = i % current_data_count

                try:
                    node = self.new_viewer(series_to_show)

                    # If we have data, display it immediately
                    if current_data_count > 0 and i < current_data_count:
                        data = self.parent_widget.lst_thumbnails_data[i]
                        if hasattr(node.vtk_widget, 'switch_series'):
                            # Only create, don't switch yet - will do in batch below
                            pass

                except Exception as e:
                    print(f"   ⚠️ Error creating viewer {i}: {e}")
                    # Create fallback viewer
                    node = self._create_fallback_viewer()
                    self.lst_nodes_viewer.append(node)

            # 3. Arrange in grid
            for i, node in enumerate(self.lst_nodes_viewer):
                if i >= required_count:
                    break
                row, col = divmod(i, cols)
                self.parent_widget.vtk_layout.addWidget(node.widget, row, col)

            # 4. Distribute series to viewers
            self._distribute_series_to_viewers()

            # 5. Set first viewer as active
            if self.lst_nodes_viewer:
                self.change_container_border(0)

            if modify_by_user:
                QTimer.singleShot(500, self._hide_loading_msg)

            print(f"✅ [LAYOUT] Applied {rows}x{cols} layout with {len(self.lst_nodes_viewer)} viewers")

        except Exception as e:
            print(f"❌ [LAYOUT] Error: {e}")
            import traceback
            traceback.print_exc()
            if modify_by_user:
                self._hide_loading_msg()
        finally:
            # ✅ FLICKER FIX: Re-enable updates after batch creation
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(True)
            self.parent_widget.setUpdatesEnabled(True)
            # Single repaint after all changes
            self.parent_widget.update()

    def new_viewer(self, default_thumb_index=0):
        print(f"\n{'='*80}")
        print(f"🔨 [new_viewer] START - thumb_index={default_thumb_index}")
        self.logger.info(f"Creating new viewer with thumb index {default_thumb_index}")

        # Count existing viewers - if too many, be more aggressive with cleanup
        viewer_count = len(self.lst_nodes_viewer)

        # Hard limit protection
        if viewer_count >= self._max_viewers_per_session:
            print(f"   ⚠️ PROTECTION: Reached max viewers limit ({viewer_count}/{self._max_viewers_per_session})")
            print("   ⚠️ Creating lightweight placeholder viewer instead")
            try:
                return self._create_fallback_viewer()
            except Exception as e:
                print(f"   ❌ Even fallback failed: {e}")
                self.logger.error(f"Max viewers exceeded and fallback failed: {e}", exc_info=True)
                raise

        # Aggressive cleanup for high viewer counts
        if viewer_count > 15:
            print(f"   ⚠️ WARNING: Already have {viewer_count} viewers - running lightweight cleanup")
            # REMOVED: gc.collect() was stop-the-world on UI thread causing user-visible freezes
            gc.collect(generation=0)  # generation=0 only: fast, collects young objects

        # Periodic cleanup
        import time
        current_time = time.time()
        if current_time - self._last_gc_time > 10.0 and viewer_count > 5:  # Every 10 seconds (was 2s)
            print(f"   🧹 [Periodic GC] Cleaning up ({viewer_count} viewers)")
            gc.collect(generation=0)  # generation=0 only for minimal UI impact
            self._last_gc_time = current_time

        vtk_widget = None
        slider = None

        try:
            # ✅ FLICKER FIX: Removed processEvents - batching UI updates instead
            # processEvents was causing thumbnail loading to interrupt viewer creation

            print("   📐 Creating grid layout...")
            try:
                layout = QGridLayout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                print("   ✅ Grid layout created")
            except Exception as le:
                print(f"   ⚠️ Layout creation warning: {le}")
                raise RuntimeError(f"Failed to create grid layout: {le}")

            # Check if we have thumbnail data
            print("   🔍 Checking thumbnail data...")
            try:
                has_data = (hasattr(self.parent_widget, 'lst_thumbnails_data') and
                           self.parent_widget.lst_thumbnails_data and
                           len(self.parent_widget.lst_thumbnails_data) > 0)
            except Exception as ce:
                print(f"   ⚠️ Data check warning: {ce}")
                has_data = False

            if not has_data:
                print("   📦 No thumbnail data, creating lightweight VTK widget...")
                try:
                    # ✅ FLICKER FIX: Use lightweight VTK widget with deferred rendering
                    vtk_widget = self._create_lightweight_vtk_placeholder()
                    if vtk_widget is None:
                        raise RuntimeError("_create_lightweight_vtk_placeholder returned None")
                    print("   ✅ Lightweight VTK widget created")
                except Exception as dwe:
                    print(f"   ❌ Lightweight VTK widget creation failed: {dwe}")
                    raise
            else:
                print(f"   ✅ Thumbnail data exists ({len(self.parent_widget.lst_thumbnails_data)} items)")
                print("   🎨 Creating new VTK widget...")
                try:
                    vtk_widget = self.create_new_vtk_widget(default_thumb_index)
                    if vtk_widget is None:
                        print("   ⚠️ create_new_vtk_widget returned None, using lightweight fallback")
                        vtk_widget = self._create_lightweight_vtk_placeholder()
                        if vtk_widget is None:
                            raise RuntimeError("Both create_new_vtk_widget and _create_lightweight_vtk_placeholder failed")
                    print("   ✅ VTK widget created")
                except Exception as vwe:
                    print(f"   ❌ VTK widget creation failed: {vwe}")
                    raise

            # Validate vtk_widget
            if vtk_widget is None:
                raise RuntimeError("vtk_widget is None after creation")

            # Ensure toolbar context is available for tool auto-deactivation
            if getattr(vtk_widget, 'patient_widget', None) is None:
                vtk_widget.patient_widget = self.parent_widget

            if not isinstance(vtk_widget, QWidget):
                raise RuntimeError(f"vtk_widget is not a QWidget, got {type(vtk_widget)}")

            print("   📊 Creating slider...")
            try:
                slider = SliceTickSlider(Qt.Vertical, vtk_widget)
                if slider is None:
                    raise RuntimeError("QSlider constructor returned None")
                slider.setInvertedAppearance(True)
                slider.setMaximumWidth(12)
                print("   ✅ Slider created")
            except Exception as se:
                print(f"   ❌ Slider creation failed: {se}")
                raise RuntimeError(f"Failed to create slider: {se}")

        except Exception as e:
            print(f"   ❌ ERROR in new_viewer setup: {e}")
            self.logger.error(f"Error in new_viewer setup: {e}", exc_info=True)

            # Try to return fallback viewer
            try:
                print("   🔄 Attempting fallback viewer creation...")
                fallback = self._create_fallback_viewer()
                if fallback:
                    print("   ✅ Fallback viewer created successfully")
                    return fallback
            except Exception as fe:
                print(f"   ❌ Fallback viewer also failed: {fe}")

            raise

        # Configure slider styling - Chrome-style minimalist scrollbar
        try:
            slider.setStyleSheet("""
                QSlider {
                    background: transparent;
                    border: none;
                    padding-top: 8px;
                    padding-bottom: 8px;
                    padding-left: 0px;
                    padding-right: 0px;
                    min-width: 10px;
                    max-width: 10px;
                }
                /* نوار عمودی (track) - سبک Chrome */
                QSlider::groove:vertical {
                    background: rgba(0, 0, 0, 0.1);
                    width: 10px;
                    border-radius: 5px;
                    margin: 0px 0px;
                    border: none;
                }
                /* دسته (thumb) - مستطیلی با گوشه گرد مثل Chrome */
                QSlider::handle:vertical {
                    background: rgba(128, 128, 128, 0.5);
                    width: 10px;
                    min-height: 40px;
                    border-radius: 5px;
                    margin: 0px 0px;
                    border: none;
                }
                /* حالت hover - تیره‌تر می‌شود */
                QSlider::handle:vertical:hover {
                    background: rgba(128, 128, 128, 0.7);
                }
                /* حالت فشرده شدن - خیلی تیره */
                QSlider::handle:vertical:pressed {
                    background: rgba(96, 96, 96, 0.9);
                }
                /* قسمت بالای thumb - شفاف */
                QSlider::sub-page:vertical {
                    background: transparent;
                    border: none;
                }
                /* قسمت پایین thumb - شفاف */
                QSlider::add-page:vertical {
                    background: transparent;
                    border: none;
                }
            """)
            
            # Force visibility and z-order
            slider.setVisible(True)
            slider.setAttribute(Qt.WA_TranslucentBackground, True)
            
            print("   ✅ Chrome-style scrollbar applied")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not apply slider styling: {e}")

        try:
            print("   📍 Adding widgets to layout...")
            # Add VTK widget to layout
            layout.addWidget(vtk_widget, 0, 0)
            
            print("   ✅ VTK widget added to layout")
        except Exception as e:
            print(f"   ❌ ERROR adding vtk widget to layout: {e}")
            self.logger.error(f"Error adding widgets to layout: {e}", exc_info=True)
            raise

        # Use QFrame instead of QWidget - QFrame is designed for borders!
        try:
            print("   🖼️ Creating container frame...")
            container = QFrame()
            container.setObjectName("ViewportContainer")
            container.setLayout(layout)
            container.setFrameStyle(QFrame.Box | QFrame.Plain)
            container.setLineWidth(2)  # Smaller border for inactive
            container.setProperty("active", False)
            container.setStyleSheet("""
                QFrame#ViewportContainer {
                    border: 2px solid #9ca3af;
                    border-radius: 2px;
                    background-color: transparent;
                }
            """)
            print("   ✅ Container created")
            
            # CRITICAL: Add slider as DIRECT CHILD of VTK widget (not container)
            # This ensures slider is ALWAYS on top of the image
            print("   📍 Adding Chrome-style slider overlay on VTK widget...")
            slider.setParent(vtk_widget)
            slider.setGeometry(
                vtk_widget.width() - 15,  # 15px from right edge (Chrome-style)
                5,  # 5px from top
                10,  # width (Chrome-style - 10px)
                vtk_widget.height() - 10  # height minus margins
            )
            
            # Force slider to be on top of everything with maximum z-order
            slider.raise_()
            slider.setVisible(True)
            slider.show()
            slider.update()
            
            # Connect resize event to reposition slider on VTK widget
            def reposition_slider():
                if slider and vtk_widget:
                    try:
                        slider.setGeometry(
                            vtk_widget.width() - 15,  # Chrome-style positioning
                            5,
                            10,
                            vtk_widget.height() - 10
                        )
                        slider.raise_()
                        slider.update()
                    except RuntimeError:
                        pass  # Widget might be deleted
            
            # Store original resizeEvent of VTK widget
            if hasattr(vtk_widget, 'resizeEvent'):
                original_vtk_resize = vtk_widget.resizeEvent
                def new_vtk_resize_event(event):
                    original_vtk_resize(event)
                    reposition_slider()
                vtk_widget.resizeEvent = new_vtk_resize_event
            
            print("   ✅ Thin slider added as OVERLAY directly on VTK widget (ALWAYS on top)")
            
        except Exception as e:
            print(f"   ❌ ERROR creating container: {e}")
            self.logger.error(f"Error creating container: {e}", exc_info=True)
            raise

        # Create NodeViewer
        try:
            print("   🔗 Creating NodeViewer...")
            new_node = NodeViewer(container, vtk_widget, slider)
            if new_node is None:
                raise RuntimeError("NodeViewer creation returned None")
            print("   ✅ NodeViewer created")
        except Exception as e:
            print(f"   ❌ ERROR creating NodeViewer: {e}")
            self.logger.error(f"Error creating NodeViewer: {e}", exc_info=True)
            raise

        # Set viewer ID and configure
        try:
            print("   🆔 Setting viewer ID...")
            viewer_index = len(self.lst_nodes_viewer)

            # Safely set ID attribute
            if hasattr(vtk_widget, '__dict__'):
                vtk_widget.id_vtk_widget = viewer_index
            else:
                setattr(vtk_widget, 'id_vtk_widget', viewer_index)
            print(f"   ✅ Viewer ID set to {viewer_index}")

            print("   📝 Appending to lst_nodes_viewer...")
            self.lst_nodes_viewer.append(new_node)
            print("   ✅ Appended")
        except Exception as e:
            print(f"   ❌ ERROR setting viewer ID: {e}")
            self.logger.error(f"Error setting viewer ID: {e}", exc_info=True)
            raise

        # Configure slider
        try:
            print("   🎚️ Configuring slider...")

            # FORCE SLIDER VISIBILITY - critical for always showing slider
            slider.setOrientation(Qt.Vertical)
            slider.setInvertedAppearance(True)
            slider.setInvertedControls(True)
            slider.setTickPosition(QSlider.NoTicks)  # ticks painted by SliceTickSlider
            slider.setTickInterval(0)
            slider.setSingleStep(1)
            slider.setPageStep(1)
            slider.setTracking(True)
            slider.setFocusPolicy(Qt.StrongFocus)
            slider.setMouseTracking(True)
            slider.setVisible(True)
            slider.show()
            slider.setEnabled(True)

            # ✅ CRITICAL: Block signals during slider setup to prevent image number flickering
            slider.blockSignals(True)

            # Check if methods exist
            if not hasattr(vtk_widget, 'set_slider'):
                print("   ⚠️ VTK widget doesn't have set_slider yet (placeholder mode)")
                # For placeholder widgets, just set slider to default values
                slider.setMinimum(0)
                slider.setMaximum(0)
                slider.setValue(0)
                print("   ✅ Slider configured in placeholder mode (0 slices) - VISIBLE")
            else:
                vtk_widget.set_slider(slider)

                if not hasattr(vtk_widget, 'get_count_of_slices'):
                    raise AttributeError("VTK widget doesn't have get_count_of_slices method")

                count_slices = vtk_widget.get_count_of_slices()
                mid_slices = 0
                last_slices = max(0, count_slices - 1)

                slider.setMinimum(0)
                slider.setMaximum(last_slices)
                slider.setValue(mid_slices)
                print(f"   ✅ Slider configured (slices: {count_slices}, current: {mid_slices}) - VISIBLE")
        except Exception as e:
            print(f"   ❌ ERROR configuring slider: {e}")
            # Don't raise - allow viewer creation to continue
            # Just set slider to defaults
            slider.setMinimum(0)
            slider.setMaximum(0)
            slider.setValue(0)
            print("   ⚠️ Slider set to default values after error")
        finally:
            # ✅ CRITICAL: Unblock signals after all slider configuration is complete
            slider.blockSignals(False)

        # Connect signals
        try:
            print("   🔗 Connecting slider signal...")
            self.parent_widget.on_slider_value_changed(vtk_widget, mid_slices)
            slider.valueChanged.connect(lambda val: self.parent_widget.on_slider_value_changed(vtk_widget, val))
            print("   ✅ Slider connected")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not connect slider signal: {e}")
            self.logger.warning(f"Warning connecting slider signal: {e}")

        # Set VTK widget methods
        try:
            print("   🔧 Setting VTK widget methods...")
            if hasattr(vtk_widget, 'set_method_change_series_on_drop'):
                vtk_widget.set_method_change_series_on_drop(self.parent_widget.change_series_on_viewer)
            if hasattr(vtk_widget, 'set_method_change_container_border'):
                vtk_widget.set_method_change_container_border(self.change_container_border)
            print("   ✅ Methods set")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not set VTK widget methods: {e}")
            self.logger.warning(f"Warning setting VTK widget methods: {e}")

        print(f"🔨 [new_viewer] END - Successfully created viewer with ID {viewer_index}")
        print(f"{'='*80}\n")
        return new_node

    def _create_lightweight_vtk_placeholder(self):
        """Create a lightweight VTK widget that defers rendering until data is loaded"""
        try:
            # Use parent_widget's create_dummy_vtk_widget if available (supports AIVTKWidget override)
            if hasattr(self.parent_widget, 'create_dummy_vtk_widget'):
                return self.parent_widget.create_dummy_vtk_widget()
            
            # Fallback to default VTKWidget creation
            height = self.parent_widget.sidebar.height() if hasattr(self.parent_widget, 'sidebar') and self.parent_widget.sidebar else 480
            vtk_widget = VTKWidget(height_viewer=height, patient_widget=self.parent_widget)

            if vtk_widget is None:
                raise RuntimeError("VTKWidget constructor returned None")

            # ✅ CRITICAL: Set solid background FIRST to prevent any flash
            if hasattr(vtk_widget, 'renderer'):
                vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)  # #1a1a2e in RGB
                # ❌ FLICKER FIX: DO NOT call Render() here - it causes initial flash
                # The background will be set when the widget is first shown

            # Minimize rendering updates until real data is loaded
            if hasattr(vtk_widget, 'render_window'):
                vtk_widget.render_window.SetDesiredUpdateRate(0.001)  # Very low update rate

            # Add a flag to indicate this is a placeholder
            vtk_widget._is_placeholder = True

            return vtk_widget
        except Exception as e:
            print(f"❌ Error creating lightweight VTK widget: {e}")
            self.logger.error(f"Error creating lightweight VTK widget: {e}", exc_info=True)
            return None

    def create_dummy_vtk_widget(self):
        """Legacy method - redirects to lightweight placeholder"""
        return self._create_lightweight_vtk_placeholder()

    def create_new_vtk_widget(self, default_thumb_index):
        """Create a new VTK widget with series data, with comprehensive error handling"""
        try:
            # Check if lst_thumbnails_data exists and has sufficient data
            if not hasattr(self.parent_widget, 'lst_thumbnails_data') or not self.parent_widget.lst_thumbnails_data or len(self.parent_widget.lst_thumbnails_data) <= default_thumb_index:
                print(f"⚠️ [create_new_vtk_widget] No thumbnail data at index {default_thumb_index}, using dummy")
                return self.create_dummy_vtk_widget()

            # Extract data safely
            try:
                thumbnail_item = self.parent_widget.lst_thumbnails_data[default_thumb_index]
                if not isinstance(thumbnail_item, dict) or 'vtk_image_data' not in thumbnail_item or 'metadata' not in thumbnail_item:
                    raise ValueError(f"Invalid thumbnail data structure at index {default_thumb_index}")

                vtk_widget_data = thumbnail_item['vtk_image_data']
                metadata = copy.deepcopy(thumbnail_item['metadata'])

                if vtk_widget_data is None or metadata is None:
                    raise ValueError("VTK data or metadata is None")

            except (IndexError, KeyError, TypeError) as e:
                print(f"⚠️ [create_new_vtk_widget] Error extracting thumbnail data: {e}")
                return self.create_dummy_vtk_widget()

            # Extract metadata safely
            try:
                series_name = metadata.get('series', {}).get('series_name', 'Unknown')
                series_number = metadata.get('series', {}).get('series_number', 0)
            except (AttributeError, TypeError) as e:
                print(f"⚠️ [create_new_vtk_widget] Error extracting series info: {e}")
                series_name = 'Unknown'
                series_number = 0

            # IMPORTANT: last_series_show must always store thumbnail/list index
            # (NOT series_number) so per-viewport state comparisons remain consistent.
            series_idx = default_thumb_index

            # Create VTK widget
            try:
                vtk_widget = self.creator_vtk_widget()
                if vtk_widget is None:
                    raise RuntimeError("creator_vtk_widget returned None")
            except Exception as e:
                print(f"❌ [create_new_vtk_widget] Error creating VTK widget: {e}")
                self.logger.error(f"Error creating VTK widget: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()

            # Look for combined series
            id_new_vtk_widget = len(self.lst_nodes_viewer)
            flag_open_combine_viewer = False
            vtk_widget_data_2 = None
            metadata_2 = None

            try:
                for i in range(len(self.parent_widget.lst_thumbnails_data)):
                    if i == default_thumb_index:
                        continue

                    try:
                        item = self.parent_widget.lst_thumbnails_data[i]
                        series_name_2 = item.get('metadata', {}).get('series', {}).get('series_name', '')

                        if series_name_2 == series_name:
                            flag_open_combine_viewer = True
                            vtk_widget_data_2 = item.get('vtk_image_data')
                            metadata_2 = copy.deepcopy(item.get('metadata'))
                            break
                    except (AttributeError, TypeError, IndexError):
                        continue
            except Exception as e:
                print(f"⚠️ [create_new_vtk_widget] Warning during combined series check: {e}")

            print(f'[create_new_vtk_widget] Series: {series_name}, Number: {series_number}, Combined: {flag_open_combine_viewer}')

            # Process series
            try:
                if flag_open_combine_viewer and vtk_widget_data_2 is not None and metadata_2 is not None:
                    vtk_widget.start_process_combine_series(
                        vtk_widget_data, metadata, vtk_widget_data_2, metadata_2, series_idx, id_new_vtk_widget,
                        metadata_fixed=self.parent_widget.metadata_fixed if hasattr(self.parent_widget, 'metadata_fixed') else {})
                else:
                    vtk_widget.start_process_series(
                        vtk_image_data=vtk_widget_data, metadata=metadata, series_index=series_idx,
                        id_vtk_widget=id_new_vtk_widget, metadata_fixed=self.parent_widget.metadata_fixed if hasattr(self.parent_widget, 'metadata_fixed') else {})

                return vtk_widget

            except Exception as e:
                print(f"❌ [create_new_vtk_widget] Error processing series: {e}")
                self.logger.error(f"Error processing series: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()

        except Exception as e:
            print(f"❌ [create_new_vtk_widget] Unexpected error: {e}")
            self.logger.error(f"Unexpected error in create_new_vtk_widget: {e}", exc_info=True)
            return self.create_dummy_vtk_widget()

    def creator_vtk_widget(self):
        try:
            # Use parent_widget's creator method if available (supports AIVTKWidget override)
            if hasattr(self.parent_widget, 'creator_vtk_widget'):
                return self.parent_widget.creator_vtk_widget()
            # Fallback to default VTKWidget creation
            height = self.parent_widget.sidebar.height() if hasattr(self.parent_widget, 'sidebar') and self.parent_widget.sidebar else 480
            return VTKWidget(height_viewer=height, patient_widget=self.parent_widget)
        except Exception as e:
            print(f"❌ Error in creator_vtk_widget: {e}")
            self.logger.error(f"Error in creator_vtk_widget: {e}", exc_info=True)
            return None

    def set_viewer_to_main_viewer(self, node_viewer: NodeViewer):
        if self.selected_widget == node_viewer.vtk_widget:
            # print('we clicked on the main viewer')
            return False

        # save tool activated
        tool_activated_method = self.parent_widget.toolbar_manager.get_tool_activated_method()

        # print(f'tool selected before: {self.parent_widget.toolbar_manager.tool_selected},, tool_activated_method before off:', tool_activated_method)
        self.parent_widget.toolbar_manager.check_and_deactivate_tools()
        # print(f'tool selected after: {self.parent_widget.toolbar_manager.tool_selected},,,,,, tool_activated_method after off:', self.parent_widget.toolbar_manager.get_tool_activated_method())

        # set new vtk_widget to main vtk_widget
        self.selected_widget: VTKWidget = node_viewer.vtk_widget
        self.slider = node_viewer.slider

        # print('************************************************')
        if tool_activated_method:
            # apply activated tool on new vtk_widget
            self.parent_widget.toolbar_manager.tool_selected = None
            tool_activated_method(self.selected_widget)

    def change_container_border(self, id_vtk_widget):
        # TODO: at first we must check last viewer selected. if the last viewed selected and id_vtk_widget are the
        #  same, skip the for (return)
        node_viewer_selected = self.lst_nodes_viewer[id_vtk_widget]
        for node_viewer in self.lst_nodes_viewer:
            node_viewer: NodeViewer

            if node_viewer_selected.widget == node_viewer.widget:
                # Active viewport - same size border, just different color (blue)
                node_viewer_selected.widget.setProperty("active", True)
                node_viewer_selected.widget.setFrameStyle(QFrame.Box | QFrame.Plain)
                node_viewer_selected.widget.setLineWidth(2)  # Same as inactive
                node_viewer_selected.widget.setStyleSheet("""
                    QFrame#ViewportContainer {
                        border: 2px solid #60a5fa;
                        border-radius: 2px;
                        background-color: transparent;
                    }
                """)
                self.set_viewer_to_main_viewer(node_viewer_selected)

            else:
                # Inactive viewport - same size border, different color (gray)
                node_viewer.widget.setProperty("active", False)
                node_viewer.widget.setFrameStyle(QFrame.Box | QFrame.Plain)
                node_viewer.widget.setLineWidth(2)  # Same as active
                node_viewer.widget.setStyleSheet("""
                    QFrame#ViewportContainer {
                        border: 2px solid #9ca3af;
                        border-radius: 2px;
                        background-color: transparent;
                    }
                """)

        self.parent_widget.manage_reference_line()

    def change_series_on_viewer(self, series_index, flag_change_selected_widget=True,
                                vtk_widget: VTKWidget = None, slider: QSlider = None,
                                allow_paired: bool = True):
        """
        ⚡ OPTIMIZED: Switch series with O(1) lookup and minimal overhead.
        
        Performance improvements:
        - Uses hash-based series cache instead of linear search
        - Eliminates redundant metadata extraction
        - Fast paired series detection with index
        - Removes artificial delays
        """
        try:
            _t0 = time.perf_counter()
            self._last_user_interaction_ts = time.time()
            series_number = str(series_index)
            target_widget_for_spinner = vtk_widget

            # Fail-safe: never let spinner run forever if switching stalls.
            self._arm_spinner_timeout(target_widget_for_spinner, timeout_ms=20000)
            
            # Initialize parent structures once
            if not hasattr(self.parent_widget, 'lst_thumbnails_data'):
                self.parent_widget.lst_thumbnails_data = []

            # ✅ ENSURE VIEWERS EXIST (fail-fast check)
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
                print(f"❌ [SWITCH FAIL] Invalid target viewport for series {series_number}")
                self._hide_spinner_for_widget(target_widget_for_spinner)
                return

            # Fast no-op path: same series already displayed on this viewport.
            # Prevents expensive load-on-demand + reset work on repeated drops.
            try:
                current_series_no = None
                if getattr(vtk_widget, 'image_viewer', None) is not None:
                    current_series_no = str(
                        getattr(vtk_widget.image_viewer, 'metadata', {}).get('series', {}).get('series_number', '')
                    )
                if current_series_no and current_series_no == series_number:
                    if hasattr(vtk_widget, '_finalize_pending_action'):
                        try:
                            vtk_widget._finalize_pending_action(series_index, phase="switch_series_noop_same")
                        except Exception:
                            pass
                    self._hide_spinner_for_widget(target_widget_for_spinner)
                    print(f"[PROFILE] change_series_on_viewer: noop same-series series={series_number} total={(time.perf_counter() - _t0)*1000:.1f}ms")
                    return
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

            self._arm_spinner_timeout(vtk_widget, timeout_ms=20000)
            expected_token = self._next_request_token(vtk_widget)

            # ⚡ FAST PATH: O(1) series lookup with caching
            vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_number)
            cache_hit = metadata is not None

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
            
            # If still not found, try loading from disk
            if metadata is None:
                study_path = self._get_correct_study_path()
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
                )
                return

            # ⚡ PERFORM SWITCH WITH OPTIMIZED PAIRED SERIES LOOKUP
            self._perform_series_switch_optimized(vtk_widget, metadata, vtk_image_data, series_idx, slider,
                                                  allow_paired=allow_paired,
                                                  expected_token=expected_token)
            print(
                f"[PROFILE] change_series_on_viewer: series={series_number} cache_hit={cache_hit} "
                f"total={(time.perf_counter() - _t0)*1000:.1f}ms"
            )

        except Exception as e:
            self.logger.error(f"Error switching series: {e}", exc_info=True)
            print(f"❌ [SWITCH FAIL] series={series_index} error={e}")
            try:
                self._hide_spinner_for_widget(vtk_widget)
            except Exception:
                pass
        finally:
            self._interactive_load_in_progress = False
            self._set_zeta_external_interactive_busy(bool(self._async_switch_inflight), reason="switch_finally")

    def _schedule_async_load_and_switch(self, series_number: str, study_path: str,
                                        vtk_widget: VTKWidget, slider: QSlider,
                                        allow_paired: bool, expected_token,
                                        target_widget_for_spinner,
                                        total_start: float):
        """Load uncached series in background and apply on UI thread when ready."""
        viewer_id = self._get_viewer_id(vtk_widget)
        inflight_key = (viewer_id, str(series_number))
        if inflight_key in self._async_switch_inflight:
            print(f"⏳ [ASYNC SWITCH] series={series_number} already in-flight for viewer={viewer_id}")
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
                use_preview = bool(exp_slices <= 0 or exp_slices <= 64)
                if use_preview:
                    preview = load_series_preview(
                        study_path=study_path,
                        series_number=int(series_number),
                        patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                        study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                        max_files=1,
                    )
                    if preview:
                        vtk_prev, meta_prev, (p_pk, s_pk), _total_files = preview
                        if vtk_prev is not None and isinstance(meta_prev, dict):
                            def _apply_preview_ui():
                                try:
                                    if not self._is_request_current(vtk_widget, expected_token):
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

            try:
                ok = self._load_single_series_on_demand(
                    int(series_number),
                    study_path,
                    target_vtk_widget=vtk_widget,
                    allow_paired=allow_paired,
                    expected_token=expected_token,
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
                        print(f"⚠️ [ASYNC SWITCH] vtk_widget deleted for series={series_number}, aborting apply")
                        return

                    if not self._is_request_current(vtk_widget, expected_token):
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        return

                    if not ok:
                        self._trigger_download_if_needed(series_number)
                        print(f"[PROFILE] change_series_on_viewer: async load-on-demand FAILED for series {series_number} in {(time.perf_counter() - _t_load)*1000:.1f}ms")
                        if preview_applied:
                            print(f"ℹ️ [ASYNC SWITCH] preview remained active for series={series_number} (full load failed)")
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        return

                    print(f"[PROFILE] change_series_on_viewer: async load-on-demand OK for series {series_number} in {(time.perf_counter() - _t_load)*1000:.1f}ms")
                    vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_number)
                    if metadata is None or vtk_image_data is None:
                        print(f"❌ [SWITCH FAIL] series={series_number} not found in cache after async loading")
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
                    print(
                        f"[PROFILE] change_series_on_viewer: series={series_number} cache_hit=False "
                        f"total={(time.perf_counter() - total_start)*1000:.1f}ms"
                    )
                except Exception as e:
                    print(f"❌ [ASYNC SWITCH] _finish_on_ui crashed for series={series_number}: {e}")
                    import traceback; traceback.print_exc()
                finally:
                    self._interactive_load_in_progress = False
                    self._set_zeta_external_interactive_busy(bool(self._async_switch_inflight), reason="finish_async_switch_finally")

            self._queue_on_ui_thread(_finish_on_ui)

        threading.Thread(target=_worker, daemon=True, name=f"AsyncSwitchLoad-{series_number}-v{viewer_id}").start()

    def _get_correct_study_path(self) -> str:
        """Get the correct study path, ensuring it's not pointing to a series subfolder"""
        from pathlib import Path

        if not self.parent_widget.import_folder_path:
            return None

        path = Path(self.parent_widget.import_folder_path)

        # If current path has numeric subfolders that are series, we're at study level
        # If current path is numeric and exists inside another folder, go up
        if path.name.isdigit() and path.parent.exists():
            # Check if parent has other series folders
            parent = path.parent
            series_folders = [d for d in parent.iterdir() if d.is_dir() and d.name.isdigit()]
            if len(series_folders) > 1:
                return str(parent)

        return str(path)

    def _perform_series_switch_optimized(self, vtk_widget, metadata, vtk_image_data, series_idx, slider,
                                         allow_paired: bool = True, expected_token=None):
        """
        ⚡ OPTIMIZED: Perform series switch with O(1) paired series lookup.
        
        Performance improvements:
        - Fast paired series detection using index
        - No redundant list iterations
        - Direct metadata access without nesting lookups
        - Shows loading spinner for series changes
        """
        try:
            if not self._is_request_current(vtk_widget, expected_token):
                return

            # Validate vtk_image_data before switching; attempt recovery if needed.
            if not vtk_image_data:
                print("⚠️ [SWITCH RECOVERY] Invalid vtk_image_data (None), attempting recovery")
                series_no = str(metadata.get('series', {}).get('series_number', '')) if isinstance(metadata, dict) else ''
                if series_no.isdigit():
                    recovered = self._load_single_series_on_demand(
                        int(series_no),
                        self._get_correct_study_path(),
                        target_vtk_widget=vtk_widget,
                        allow_paired=allow_paired,
                        expected_token=expected_token,
                    )
                    if recovered:
                        vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_no)
                if not vtk_image_data:
                    print("❌ [SWITCH ABORT] Recovery failed: vtk_image_data still invalid")
                    return

            dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
            if not dims or int(dims[0]) <= 0 or int(dims[1]) <= 0 or int(dims[2]) <= 0:
                print(f"⚠️ [SWITCH RECOVERY] Invalid dimensions {dims}, attempting recovery")
                series_no = str(metadata.get('series', {}).get('series_number', '')) if isinstance(metadata, dict) else ''
                if series_no.isdigit():
                    recovered = self._load_single_series_on_demand(
                        int(series_no),
                        self._get_correct_study_path(),
                        target_vtk_widget=vtk_widget,
                        allow_paired=allow_paired,
                        expected_token=expected_token,
                    )
                    if recovered:
                        vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_no)
                        dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
                if not dims or int(dims[0]) <= 0 or int(dims[1]) <= 0 or int(dims[2]) <= 0:
                    print("❌ [SWITCH ABORT] Recovery failed: invalid dimensions remain")
                    return

            metadata = self._clone_metadata_for_switch(metadata)
            series_number = str(metadata.get('series', {}).get('series_number', ''))
            series_name = str(metadata.get('series', {}).get('series_name', ''))

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
                f"🔎 [SERIES COUNT] req_series={series_number} name='{series_name}' "
                f"instances={expected_instances} vtk_slices={vtk_slice_count} "
                f"thumb_image_count={server_image_count}"
            )
            
            # 🎬 Show loading spinner before switch
            # The message is set in switch_series based on series size
            # but we can optionally enhance it here if needed
            
            # ⚡ FAST PAIRED SERIES LOOKUP: O(1) instead of linear search
            # ✅ CRITICAL FIX: Only pair series for MG (Mammography) modality
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
                    f"ℹ️ [PAIRED SKIP] series={series_number} modality={current_modality} - "
                    f"Skipping pairing (only MG modality uses paired series)"
                )

            if metadata_2 is not None:
                try:
                    paired_series_number = str(metadata_2.get('series', {}).get('series_number', ''))
                    paired_instances = len(metadata_2.get('instances', []) or [])
                    paired_dims = vtk_widget_data_2.GetDimensions() if vtk_widget_data_2 is not None else (0, 0, 0)
                    paired_slices = int(paired_dims[2]) if paired_dims and len(paired_dims) > 2 else 0
                    print(
                        f"🔗 [SERIES COUNT] paired_series={paired_series_number} "
                        f"instances={paired_instances} vtk_slices={paired_slices}"
                    )
                except Exception:
                    pass
            
            # ⚡ PERFORM SWITCH (no delay, no blocking)
            if hasattr(vtk_widget, 'switch_series'):
                flag_switch = vtk_widget.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    vtk_widget_data_2,
                    metadata_2,
                    self.parent_widget.metadata_fixed
                )
                
                if flag_switch:
                    # Quick slider configuration (without blocking)
                    self.parent_widget.reset_slider(vtk_widget, slider)
                    self.parent_widget.toolbar_manager.turn_off_all_tools()

                    # --- DEBUG: verify viewer count after switch ---
                    try:
                        viewer = getattr(vtk_widget, 'image_viewer', None)
                        viewer_type = type(viewer).__name__ if viewer is not None else 'None'
                        viewer_count = viewer.get_count_of_slices() if viewer is not None else 0
                        viewer_skip = getattr(viewer, 'skip_slices', None)
                        print(
                            f"✅ [SERIES COUNT] viewer={viewer_type} series={series_number} "
                            f"viewer_slices={viewer_count} skip={viewer_skip}"
                        )
                        if metadata_2 is None and expected_instances and viewer_count and viewer_count != expected_instances:
                            print(
                                f"⚠️ [SERIES COUNT MISMATCH] series={series_number} "
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

                    # Mode B — Image Slice Booster: activate \u00b120 slice window
                    # for the newly displayed series.  Only fires while a download
                    # is in progress; no-op in Mode A (post-download).
                    try:
                        if self.pipeline.is_download_active:
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
                                self._image_slice_booster.set_active(
                                    series_number, _inst_paths, _center
                                )
                    except Exception:
                        pass

                    self._refresh_zeta_protected_series()

                    # ── Look-ahead warmup: pre-cache adjacent series ──
                    # After every successful series switch, schedule warmup for
                    # the next N adjacent series so they're ready when the doctor
                    # drags-and-drops them.  This runs on a short deferred timer
                    # so it doesn't block the current render.
                    try:
                        _la_sn = str(series_number)
                        QTimer.singleShot(100, lambda sn=_la_sn: self._enqueue_lookahead_warmup(sn))
                    except Exception:
                        pass
                    
                    # Update UI elements (batch updates)
                    if hasattr(vtk_widget, 'image_viewer') and vtk_widget.image_viewer:
                        vtk_widget.image_viewer.update_corners_actors()

                    # Recompute reference lines for ALL viewers after series change.
                    # Without this, drag-drop series switches leave stale/missing
                    # reference lines because only viewport-click and slider-scroll
                    # previously triggered recalculation.
                    try:
                        self.parent_widget.manage_reference_line()
                    except Exception as _rl_err:
                        print(f"⚠️ [RL] manage_reference_line error after switch: {_rl_err}")
        
        except Exception as e:
            self.logger.error(f"Error in series switch: {e}", exc_info=True)

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
        """نمایش spinner در viewport فعلی"""
        try:
            if hasattr(self.parent_widget, 'selected_widget') and self.parent_widget.selected_widget:
                spinner = getattr(self.parent_widget.selected_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.show_loading(message)
        except Exception:
            pass

    def _hide_loading_spinner(self):
        """مخفی کردن spinner در viewport فعلی"""
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
        """Display the first available series in all viewers."""
        try:
            if not self.parent_widget.lst_thumbnails_data:
                return False
            series_number = str(self.parent_widget.lst_thumbnails_data[0]['metadata']['series']['series_number'])
            if self._display_first_series_in_all_viewers(series_number):
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
        # ── Warmup safety-net ──
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
                    f"✅ [ZetaBoost][PRIME_FIRST] primed_visible_series={len(primed)} "
                    f"series={primed[:12]}"
                )
        except Exception:
            pass

    def _start_background_prefetch(self):
        """Start low-priority full-series prefetch for likely next interactions."""
        try:
            if not self._boostviewer_enabled:
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
            print(f"⚡ [PREFETCH] Started for {len(queue)} series: {queue}")
        except Exception as e:
            self.logger.debug(f"Error starting background prefetch: {e}")

    def _start_open_tab_warmup(self):
        """On tab activation, immediately queue already-downloaded series for ZetaBoost caching."""
        try:
            if not self._boostviewer_enabled:
                return
            if not self._tab_active:
                return
            if not self.zeta_boost.is_active():
                return
            # STRICT ISOLATION: Never warm up while downloads are in progress.
            # The pipeline is authoritative: if it says warmup is not allowed
            # (IDLE or DOWNLOADING state), stop here without retry.
            if not self.pipeline.is_warmup_allowed:
                print(
                    f"[WARMUP] Skipped — pipeline={self.pipeline.state.name} "
                    f"(warmup only allowed in POST_DOWNLOAD/READY)"
                )
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
                            f"⏳ [ZetaBoost][OPEN_WARMUP] waiting pipeline retry="
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
            print(f"🔧 [WARMUP_FILTER] detail: {' | '.join(_filter_details[:40])}")
            candidates = filtered_candidates
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
                f"ℹ️ [ZetaBoost][OPEN_WARMUP] filtered study={study_for_log} "
                f"total={total_candidates} skipped_active={skipped_active} skipped_primary={skipped_primary} "
                f"skipped_large={skipped_large} skipped_corrupt={skipped_corrupt} skipped_non_image={skipped_non_image} "
                f"skipped_failed={skipped_failed} skipped_cached={skipped_cached} "
                f"queued_light={len(candidates)} queued_heavy={len(heavy_candidates)}"
            )

            if dropped_heavy:
                print(
                    f"ℹ️ [ZetaBoost][HEAVY_ADMISSION] study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
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
                        f"ℹ️ [ZetaBoost][OPEN_WARMUP] completed_noop study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                        f"reason=all_candidates_already_handled total={total_candidates}"
                    )
                    return

                # Tab may activate before thumbnails are populated; retry briefly.
                if self._open_warmup_retry_count < 6:
                    self._open_warmup_retry_count += 1
                    print(
                        f"⏳ [ZetaBoost][OPEN_WARMUP] no queueable series yet, retry="
                        f"{self._open_warmup_retry_count}/6 study={getattr(self.parent_widget, 'study_uid', 'unknown')}"
                    )
                    # QTimer must be scheduled on the UI thread.
                    self._queue_on_ui_thread(lambda: QTimer.singleShot(350, self._start_open_tab_warmup))
                return

            if candidates:
                self.zeta_boost.enqueue_many_warmup(candidates)
                print(
                    f"🚀 [ZetaBoost][OPEN_WARMUP] active_tab=True study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                    f"queued_light_series={len(candidates)} series={candidates[:12]}"
                )

            if heavy_candidates:
                self._deferred_heavy_warmup_series = list(heavy_candidates)
                self._deferred_heavy_warmup_retry_count = 0
                print(
                    f"⏳ [ZetaBoost][HEAVY_DEFER] scheduled study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
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
            if not self._boostviewer_enabled:
                return
            if not self._tab_active or not self.zeta_boost.is_active():
                return
            if not self._deferred_heavy_warmup_series:
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
            # immediately after light series, without waiting for the warmup→
            # background lane transition.  Light series are already at the
            # front of the warmup queue (FIFO), so ordering is preserved.
            self.zeta_boost.enqueue_many_warmup(queue)
            print(
                f"🚀 [ZetaBoost][HEAVY_DEFER] batch-queued(warmup) study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
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
                f"📌 [ZetaBoost][VERIFY] stage={stage or 'n/a'} study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                f"total={len(candidates)} full_cached={len(full_cached)} loaded_not_cached={len(loaded_not_cached)} "
                f"preview_flagged={len(preview_flagged)} failed={len(failed)} missing={len(missing)} "
                f"coverage={coverage_pct:.1f}% primary={primary_series or 'n/a'}"
            )
            if preview_flagged:
                print(f"⚠️ [ZetaBoost][VERIFY] preview_flagged_series={preview_flagged[:12]}")
            if missing:
                print(f"⏳ [ZetaBoost][VERIFY] not_warmed_series={missing[:12]}")
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

    def _display_first_series_in_all_viewers(self, series_number: str) -> bool:
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
                print(f"❌ [FIRST DISPLAY] series {series_number} not found in thumbnail cache")
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
                    slider=slider
                )

            self._mark_first_series_displayed()
            return True
        except Exception as e:
            self.logger.debug(f"Error displaying first series: {e}")
            return False

    def _display_loaded_series(self, series_number, series_idx, vtk_image_data, metadata,
                               flag_change_selected_widget, vtk_widget, slider):
        """
        ⚡ OPTIMIZED: Display series with O(1) paired series lookup.
        
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

            # ⚡ FAST PAIRED SERIES LOOKUP: O(1)
            vtk_widget_data_2 = None
            metadata_2 = None
            
            series_name = str(metadata.get('series', {}).get('series_name', ''))
            if series_name in self._paired_series_map:
                paired_list = self._paired_series_map[series_name]
                for paired_num in paired_list:
                    if str(paired_num) != str(series_number):
                        vtk_data, meta, _ = self._get_series_by_number_fast(str(paired_num))
                        if vtk_data is not None and meta is not None:
                            vtk_widget_data_2 = vtk_data
                            metadata_2 = meta
                            break

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
                    self.parent_widget.metadata_fixed
                )
                
                if flag_switch:
                    self.parent_widget.reset_slider(target_widget, target_slider)
                    self.parent_widget.toolbar_manager.turn_off_all_tools()
                    if hasattr(target_widget, 'resizeEvent'):
                        target_widget.resizeEvent(None)
                    if hasattr(target_widget, 'image_viewer') and target_widget.image_viewer:
                        target_widget.image_viewer.update_corners_actors()
                    # Reference lines must be recalculated after every series change
                    try:
                        self.parent_widget.manage_reference_line()
                    except Exception:
                        pass
        
        except Exception as e:
            self.logger.debug(f"Error displaying series: {e}")

    def _create_fallback_viewer(self):
        """Create dummy viewer for missing data - with full error handling"""
        try:
            from PacsClient.pacs.patient_tab.utils import NodeViewer

            print("   📝 [Fallback] Creating layout...")
            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)

            print("   🖼️ [Fallback] Creating container...")
            container = QFrame()
            container.setLayout(layout)

            print("   🎨 [Fallback] Creating dummy VTK widget...")
            vtk_widget = self.create_dummy_vtk_widget()
            if vtk_widget is None:
                raise RuntimeError("create_dummy_vtk_widget failed")

            print("    📊 [Fallback] Creating slider...")
            slider = QSlider(Qt.Vertical)

            print("   🔗 [Fallback] Creating NodeViewer...")
            node = NodeViewer(container, vtk_widget, slider)
            if node is None:
                raise RuntimeError("NodeViewer creation failed")

            print("   ✅ [Fallback] Fallback viewer created successfully")
            return node

        except Exception as e:
            print(f"   ❌ [Fallback] Error creating fallback viewer: {e}")
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
        """تمیز‌کردن بهینهٔ viewers و resources"""
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

            # Clear caches to free memory - اما با احتیاط
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

            # Ensure stale nodes are cleared after cleanup
            try:
                self.lst_nodes_viewer.clear()
            except Exception:
                pass

            print("✅ cleanup_all_viewers completed")
        except Exception as e:
            self.logger.error(f"Error in cleanup_all_viewers: {e}")

    def _load_series_preview_async(self, series_number: str, study_path: str) -> tuple:
        """
        Load preview (5-10 slices) for rapid display on drag & drop.
        
        Returns: (vtk_preview_data, metadata) or (None, None) on failure
        
        فایده: نمایش فوری toggle٪20ms تا حالی که full volume موازی بارگذاری می‌شود
        """
        try:
            _preview_start = time.perf_counter()
            
            # سریع محاسبه: آیا قبلاً ثابت کاش داریم؟
            try:
                vtk_full, meta_full, _ = self._get_series_by_number_fast(str(series_number))
                if vtk_full is not None and isinstance(meta_full, dict):
                    dims = vtk_full.GetDimensions() if hasattr(vtk_full, 'GetDimensions') else (0, 0, 0)
                    if int(dims[2]) > 1:  # full volume موجود
                        _ms = (time.perf_counter() - _preview_start) * 1000
                        print(f"⚡ [PREVIEW] series={series_number} cached_full {_ms:.0f}ms")
                        return vtk_full, meta_full
            except Exception:
                pass
            
            # سریز از disk کش یا source بارگذاری کن
            from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview
            
            vtk_preview, metadata = load_series_preview(
                study_path=study_path,
                series_number=int(series_number),
                max_slices=8  # max 8 slice برای preview
            )
            
            _elapsed = (time.perf_counter() - _preview_start) * 1000
            if vtk_preview is not None:
                print(f"⚡ [PREVIEW] series={series_number} loaded {_elapsed:.0f}ms")
                return vtk_preview, metadata
            else:
                print(f"⚠️ [PREVIEW] series={series_number} failed {_elapsed:.0f}ms")
                return None, None
                
        except Exception as e:
            print(f"⚠️ [PREVIEW] exception: {e}")
            return None, None

    def _prefetch_adjacent_series(self, current_series_number: str):
        """
        پیش‌بینی سریز‌های مجاور و queue برای warmup lane.
        
        این متد موازی‌طوری اجرا می‌شود، بنابراین drag & drop بعدی
        < 50ms (cache hit) خواهد بود.
        """
        try:
            current_idx = None
            thumbs = getattr(self.parent_widget, 'lst_thumbnails_data', []) or []
            
            # پیدا کردن index سریز جاری
            for idx, item in enumerate(thumbs):
                sn = str(item.get('metadata', {}).get('series', {}).get('series_number', '') or '')
                if sn == str(current_series_number):
                    current_idx = idx
                    break
            
            if current_idx is None:
                return
            
            # Prefetch 3 سریز بعدی + 1 سریز قبلی (اگر موجود باشند)
            prefetch_indices = []
            for offset in [-1, 1, 2, 3]:
                candidate_idx = current_idx + offset
                if 0 <= candidate_idx < len(thumbs):
                    prefetch_indices.append(candidate_idx)
            
            queued_count = 0
            for idx in prefetch_indices:
                item = thumbs[idx]
                sn = str(item.get('metadata', {}).get('series', {}).get('series_number', '') or '')
                if not sn or sn in {str(current_series_number)}:
                    continue
                
                # Skip اگر قبلاً queued یا in-memory
                if self.zeta_boost.has_in_memory(sn):
                    continue
                
                # Queue برای warmup lane (بدون blocking interactive)
                try:
                    self.zeta_boost.queue_load(sn, lane="warmup")
                    queued_count += 1
                except Exception:
                    pass
            
            if queued_count > 0:
                print(f"🔥 [PREFETCH] series={current_series_number} queued={queued_count} adjacent")
                
        except Exception as e:
            print(f"⚠️ [PREFETCH] error: {e}")

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

    def _load_single_series_on_demand(self, series_number: int, study_path: str = None,
                                      target_vtk_widget: VTKWidget = None,
                                      allow_paired: bool = True,
                                      expected_token=None) -> bool:
        """
        Load a single series with correct path resolution
        """
        import time
        from pathlib import Path

        try:
            _start = time.perf_counter()

            # ✅ FIX: Use provided study_path or correctly determine it
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
                    print(f"❌ No valid study path found")
                    return False

            print(f"📂 [LOAD] Loading series {series_number} from {study_path} (thread={threading.current_thread().name})")

            # Bail out early if tab was deactivated while queued (e.g. user pressed F5).
            # Allow explicit user-driven loads even if tab_active flag is stale.
            if not self._tab_active and not self._interactive_load_in_progress:
                print(f"⏭️ [LOAD SKIP] tab inactive for series {series_number}")
                return False

            # Deterministic full-series cache before any I/O work.
            _cache_probe_t = time.perf_counter()
            cached_full = self._full_cache_get(str(series_number))
            _cache_probe_ms = (time.perf_counter() - _cache_probe_t) * 1000
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
                        refresh_viewer=False
                    )
                    _apply_ms = (time.perf_counter() - _apply_t) * 1000
                    print(f"⚡ [CACHE HIT] full-series cache hit for {series_number} probe={_cache_probe_ms:.0f}ms apply={_apply_ms:.0f}ms")
                    return True
            elif _cache_probe_ms > 50:
                print(f"🔍 [CACHE MISS] series={series_number} probe took {_cache_probe_ms:.0f}ms")

            # Fast exit only when a full-volume payload is already loaded.
            # Preview-only payloads (z=1 with preview flag) must continue to full load,
            # otherwise heavy series can appear to never load.
            try:
                existing_vtk, existing_meta, _ = self._get_series_by_number_fast(str(series_number))
                if existing_meta and existing_vtk is not None and self._is_full_volume_cache_candidate(str(series_number), existing_vtk, existing_meta):
                    return True
            except Exception:
                pass

            # INTERACTIVE DEDUP: prevent two identical interactive drag-drops
            # from loading the same series twice.  ZetaBoost warmup is fully
            # independent (see _zeta_boost_load_series) and never participates
            # in this lock — the viewer never waits for warmup.
            series_key = str(series_number)
            load_event = None
            is_owner = False
            with self._series_load_lock:
                if series_key in self._loading_series_numbers:
                    load_event = self._series_load_events.get(series_key)
                    print(f"⏳ [LOAD] series={series_key} already loading interactively (thread={threading.current_thread().name})")
                else:
                    self._loading_series_numbers.add(series_key)
                    load_event = threading.Event()
                    self._series_load_events[series_key] = load_event
                    is_owner = True
                    print(f"🔑 [LOAD] series={series_key} took ownership (thread={threading.current_thread().name})")

            if not is_owner:
                # Another interactive load is already working on this series.
                # Wait for it (legitimate dedup — same user action).
                _wait_t = time.perf_counter()
                if load_event is not None:
                    load_event.wait(timeout=10.0)
                _wait_ms = (time.perf_counter() - _wait_t) * 1000
                print(f"⏳ [LOAD] series={series_key} interactive wait done {_wait_ms:.0f}ms (thread={threading.current_thread().name})")

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
                            refresh_viewer=False
                        )
                        return True

                # Previous interactive loader finished without result — take over.
                with self._series_load_lock:
                    if series_key not in self._loading_series_numbers:
                        self._loading_series_numbers.add(series_key)
                        load_event = threading.Event()
                        self._series_load_events[series_key] = load_event
                        is_owner = True

                if not is_owner:
                    existing_vtk, existing_meta, _ = self._get_series_by_number_fast(series_key)
                    if existing_meta and existing_vtk is not None and self._is_full_volume_cache_candidate(series_key, existing_vtk, existing_meta):
                        return True
                    return False

            # Verify series folder exists
            series_folder = Path(study_path) / str(series_number)
            if not series_folder.exists():
                print(f"❌ Series folder not found: {series_folder}")
                with self._series_load_lock:
                    evt = self._series_load_events.pop(series_key, None)
                    self._loading_series_numbers.discard(series_key)
                if evt is not None:
                    evt.set()
                return False

            # Check for DICOM files
            raw_dicom_files = list(series_folder.glob("*.dcm")) + list(series_folder.glob("*.DCM"))
            dicom_files = []
            seen_dcm = set()
            for _p in raw_dicom_files:
                _k = str(_p).lower()
                if _k in seen_dcm:
                    continue
                seen_dcm.add(_k)
                dicom_files.append(_p)
            if not dicom_files:
                print(f"❌ No DICOM files in {series_folder}")
                with self._series_load_lock:
                    evt = self._series_load_events.pop(series_key, None)
                    self._loading_series_numbers.discard(series_key)
                if evt is not None:
                    evt.set()
                return False

            # Load full series with correct path (preview path disabled by design)
            _dicom_t = time.perf_counter()
            result = load_single_series_by_number(
                study_path=study_path,  # Pass correct study path, not series path
                series_number=series_number,
                patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
            )
            _dicom_ms = (time.perf_counter() - _dicom_t) * 1000
            print(f"📊 [LOAD] DICOM+ITK for series={series_number} took {_dicom_ms:.0f}ms files={len(dicom_files)} (thread={threading.current_thread().name})")

            if not result:
                print(f"❌ [LOAD FAIL] series={series_number} no result from loader")
                with self._series_load_lock:
                    evt = self._series_load_events.pop(series_key, None)
                    self._loading_series_numbers.discard(series_key)
                if evt is not None:
                    evt.set()
                return False

            # Process results
            for item in result:
                if not self._tab_active:
                    print(f"⏭️ [LOAD SKIP] tab inactive during apply for series {series_number}")
                    return False
                if target_vtk_widget is not None and not self._is_request_current(target_vtk_widget, expected_token):
                    print(f"⏭️ [LOAD STALE] full series={series_number} ignored")
                    return False
                vtk_image_data, metadata, (patient_pk, study_pk) = item
                self._apply_loaded_series_data_threadsafe(series_number, vtk_image_data, metadata, patient_pk, study_pk)

            _elapsed = time.perf_counter() - _start
            print(f"✅ [LOAD] Series {series_number} loaded in {_elapsed:.3f}s")
            self._prefetch_loaded.add(series_key)
            # Keep full decoded series for repeat drag-drop.
            try:
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
            print(f"❌ [LOAD] Error loading series {series_number}: {e}")
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
            dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
            print(f"🔄 [APPLY] series={series_number} refresh={refresh_viewer} dims={dims}")

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
            series_idx = self.parent_widget.replace_series_data(
                series_number=series_number,
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                file_path=file_path
            )
            print(f"🔄 [APPLY] series={series_number} → replace_series_data returned idx={series_idx}")

            # Update study path if needed
            if metadata.get('series', {}).get('series_path'):
                correct_path = Path(metadata['series']['series_path']).parent
                if str(correct_path) != self.parent_widget.import_folder_path:
                    self.parent_widget.import_folder_path = str(correct_path)
                    print(f"   🔄 Updated study path to: {correct_path}")

            if refresh_viewer and series_idx >= 0:
                # Update ALL viewers currently showing this series (not just selected)
                for vi, node_viewer in enumerate(self.lst_nodes_viewer or []):
                    vtk_w = getattr(node_viewer, 'vtk_widget', None)
                    if vtk_w is None:
                        continue
                    if target_viewer_id is not None and getattr(vtk_w, 'id_vtk_widget', None) != target_viewer_id:
                        continue
                    if expected_token is not None and not self._is_request_current(vtk_w, expected_token):
                        print(f"   ⏭️ [APPLY STALE] viewer[{vi}] series={series_number} skipped")
                        continue
                    # last_series_show stores thumbnail *index*, not series number
                    current_idx = getattr(vtk_w, 'last_series_show', None)
                    print(f"   🔎 viewer[{vi}] last_series_show={current_idx} vs series_idx={series_idx}")
                    if current_idx is not None and current_idx == series_idx:
                        try:
                            slider = getattr(node_viewer, 'slider', None)
                            print(f"   ✅ Refreshing viewer[{vi}] with full data (dims={dims})")
                            self._perform_series_switch_optimized(
                                vtk_w, metadata, vtk_image_data, series_idx, slider,
                                allow_paired=allow_paired,
                                expected_token=expected_token,
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
        """Apply loaded data on UI thread — fire-and-forget from worker threads.

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
                print(f"⚠️ [UI APPLY] error: {e}")

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
                print(f"ℹ️ [ZetaBoost][INTERACTIVE_BUSY] busy={new_state} reason={reason}")
        except Exception:
            pass

    def _mark_download_active(self):
        """Signal the orchestrator that a download-completed series arrived.

        Each call records the series via the PipelineOrchestrator (which
        ensures DOWNLOADING state) and also sets the legacy engine flag
        for backward compatibility.  The old QTimer-based idle detection
        is removed — warmup/background lanes are unblocked exclusively
        by ``on_study_download_completed()`` via the orchestrator.
        """
        try:
            self.zeta_boost.set_download_active(True)
        except Exception:
            pass

    def _clear_download_active(self):
        """Legacy stub — warmup is now gated by PipelineOrchestrator.

        Kept for backward compatibility; does nothing harmful.
        """
        pass

    # ── Pipeline orchestrator integration ──────────────────────────

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
                # 1. Unlock ZetaBoost warmup/background lanes.
                self.zeta_boost.set_study_download_complete(True)
                self.zeta_boost.set_download_active(False)
                # 2. Exit Mode B: re-enable series-level RAM caching.
                self.zeta_boost.set_image_boost_mode(False)
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
                    print(f"[Pipeline] POST_DOWNLOAD → warmup scheduled (tab active)")
                else:
                    print(f"[Pipeline] POST_DOWNLOAD → warmup deferred (tab inactive — starts on next activation)")

            elif new_state == PipelineState.DOWNLOADING:
                # Downloads starting — block ZetaBoost warmup/background.
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
                    print(f"[Pipeline] DOWNLOADING → engine deactivated (tab inactive, all workers stopped)")
                else:
                    print(f"[Pipeline] DOWNLOADING → warmup blocked, Image Boost active")

            elif new_state == PipelineState.READY:
                print(f"[Pipeline] READY → all series cached")

            elif new_state == PipelineState.IDLE:
                self.zeta_boost.set_study_download_complete(False)
                self.zeta_boost.set_download_active(False)
                self.zeta_boost.set_image_boost_mode(False)
                self._image_slice_booster.clear()
        except Exception as e:
            print(f"[Pipeline] state change error: {e}")

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

    def _trigger_download_if_needed(self, series_number: str):
        """Trigger server download if series not available locally"""
        try:
            series_number = self.parent_widget.resolve_series_key(series_number)
            # Check if we have server info
            if hasattr(self.parent_widget, '_server_series_info') and self.parent_widget._server_series_info:
                if series_number in self.parent_widget._server_series_info:
                    print(f"   📥 Triggering server download for series {series_number}")
                    # Emit signal or call download method
                    if hasattr(self.parent_widget, 'series_downloaded'):
                        self.parent_widget.series_downloaded.emit(series_number)
                    return
            print(f"   ℹ️ No server info available for download")

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
                    series_uid=None,
                )
            finally:
                QTimer.singleShot(2000, lambda: inflight.discard(series_number))
        except Exception as e:
            print(f"   ⚠️ Error triggering download: {e}")

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
                self.logger.debug(f"Skip load_series_on_demand for inactive tab: series {series_number}")
                return

            # Check if widget is still valid
            try:
                if not self.parent_widget.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            series_number_str = self.parent_widget.resolve_series_key(series_number)

            # ── Pipeline orchestrator signaling ──
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

            # ── Dedup guard: prevent multiple concurrent loads of same series ──
            if series_number_str in getattr(self, '_first_series_loading', set()):
                print(f"⏭️ [DEDUP] series={series_number_str} already loading, skip")
                return

            # ZetaBoost path: the FIRST series bypasses ZetaBoost entirely
            # because the warmup callback only caches — it does not trigger
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
                            pass  # No running loop — fall through to legacy path
                    else:
                        # Subsequent download completions: do NOT enqueue warmup
                        # during active downloads.  The orchestrator will trigger
                        # _start_open_tab_warmup after study download completes.
                        # This prevents ZetaBoost from competing with downloads
                        # for GIL time.
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
                    self.logger.info(f"Series {series_number_str} already loaded but not displayed — showing now")
                    QTimer.singleShot(0, lambda sn=series_number_str: self._display_series_after_load(sn))
                else:
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
                        # ✅ OPTIMIZATION: مرحله 1 - Preview سریع (100-200ms)
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
                                # Display preview فوری
                                try:
                                    self._apply_loaded_series_data_threadsafe(
                                        series_number_str,
                                        vtk_preview,
                                        meta_preview,
                                        self.parent_widget.metadata_fixed.get('patient_pk', None),
                                        self.parent_widget.metadata_fixed.get('study_pk', None),
                                        refresh_viewer=False,
                                    )
                                    print(f"📺 [PREVIEW] displayed for series={series_number_str}")
                                except Exception as e:
                                    print(f"⚠️ [PREVIEW_APPLY] error: {e}")
                        
                        # Yield immediately to prevent blocking
                        await asyncio.sleep(0)

                        # ✅ OPTIMIZATION: مرحله 2 - Full volume بارگذاری موازی
                        await self._async_load_and_display_series(series_number_str)
                        
                        # ✅ OPTIMIZATION: مرحله 3 - Prefetch سریز‌های مجاور
                        # Run prefetch در background (non-blocking)
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

    async def _async_load_and_display_series(self, series_number: str):
        """
        ⚡ OPTIMIZED: Async series loading without unnecessary sleeps.
        
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

            # ⚡ OPTIMIZED: Use executor immediately without sleep
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
                self._display_series_after_load(str(series_number))
        
        except asyncio.CancelledError:
            self.logger.debug(f"Load cancelled for series {series_number}")
            raise
        except Exception as e:
            self.logger.error(f"Error loading series {series_number}: {e}", exc_info=True)

    def _display_series_after_load(self, series_number: str):
        """
        Mark series ready; for the first downloaded series, display it in all viewers
        and hide loading.
        """
        try:
            # Validate widget state
            if not self.parent_widget.isVisible():
                return

            if (not self._first_series_displayed) or self._any_viewer_empty():
                if self._display_first_series_in_all_viewers(series_number):
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
        dlg.setWindowModality(Qt.NonModal)  # فقط پیام؛ UI قفل نشه
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.resize(420, 120)

        # 🎨 استایل تیره و مینیمال
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
            /* ProgressBar مارکوی نرمِ نامشخص */
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

        # جای‌گذاری وسطِ پنل مرکزی اگر موجود بود
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
        # # یک متن دوستانه با ایموجی تک‌رنگ (روی تم تیره خوب دیده می‌شود)
        # pretty = f"⚙️  {text}\nThis may take a few seconds…"
        # self.parent_widget._loading_dlg.setLabelText(pretty)
        # self.parent_widget._loading_dlg.setRange(0, 0)  # حالت نامشخص (اسپینینگ)
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
                
                # 1. اگر مودالیتی مشخص شده، ابتدا در modality_layouts جستجو می‌کنیم
                if modality:
                    # جستجو در modality_layouts
                    modality_layouts = data.get('modality_layouts', {})
                    if modality in modality_layouts:
                        mod_cfg = modality_layouts[modality]
                        if isinstance(mod_cfg, dict):
                            rows = int(mod_cfg.get('rows', 1))
                            cols = int(mod_cfg.get('cols', 2))
                            print(f"✅ Using layout for {modality}: {rows}x{cols}")
                            return (rows, cols)
                    
                    # اگر در modality_layouts نبود، مستقیم در root جستجو می‌کنیم (برای سازگاری با فایل‌های قدیمی)
                    if modality in data:
                        mod_cfg = data[modality]
                        if isinstance(mod_cfg, dict):
                            rows = int(mod_cfg.get('rows', 1))
                            cols = int(mod_cfg.get('cols', 2))
                            print(f"✅ Using layout for {modality} (legacy): {rows}x{cols}")
                            return (rows, cols)
                
                # 2. اگر مودالیتی پیدا نشد یا مشخص نشده، از default استفاده می‌کنیم
                default_cfg = data.get('default') or data.get('DEFAULT')
                if isinstance(default_cfg, dict):
                    rows = int(default_cfg.get('rows', 1))
                    cols = int(default_cfg.get('cols', 2))
                    print(f"ℹ️ Using default layout: {rows}x{cols}")
                    return (rows, cols)
                    
        except Exception as e:
            print(f"⚠️ Error reading grid config: {e}")
        
        # 3. اگر همه چیز ناموفق بود، از fallback استفاده می‌کنیم
        print("ℹ️ Using fallback layout: 1x2")
        return (1, 2)

    def _load_first_series_sync(self, size_init_viewers):
        """Load first series synchronously when no event loop is available"""
        try:
            from PacsClient.pacs.patient_tab.utils import load_images

            print("📂 [SYNC_LOAD] Loading first series synchronously...") # لاگ اضافه شده

            first_series_loaded = False
            for vtk_image_data, metadata, patient_info in load_images(
                    self.parent_widget.import_folder_path,
                    patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                    study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.parent_widget.ordering_by_instances_number
            ):
                # ✅ FLICKER FIX: Only process events if not in initialization batch
                # NOTE: processEvents() removed — it caused re-entrancy during
                # initial load (download signals processed mid-initialization).
                # The batch update via setUpdatesEnabled(False) handles this.
                pass

                self.parent_widget.check_and_add_meta_fixed(patient_info)

                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}

                self.parent_widget.add_new_data_to_lst_thumbnails_data(new_data)

                if not first_series_loaded:
                    optimal_layout = self.parent_widget.get_optimal_layout_for_series(metadata)
                    print(f"✅ [SYNC_LOAD] Determined optimal layout: {optimal_layout}") # لاگ اضافه شده

                    # ⚡ OPTIMIZATION: Removed processEvents() - use batch update instead
                    # Use synchronous viewer creation
                    self._apply_multi_viewer_sync(optimal_layout) # این تابع ویوورها را تنظیم می کند

                    first_series_loaded = True
                    self._hide_loading_spinner()

                    series_no = metadata['series']['series_number']
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(series_no))
                    self.parent_widget.thumbnail_manager.set_series_ready(str(series_no))

                    if file_path and not self.parent_widget.logo_patient:
                        self.parent_widget.logo_patient = file_path
                        self.parent_widget.update_tab_manager()

                    print(f"✅ [SYNC_LOAD] First series loaded: {series_no}. Breaking loop.") # لاگ اضافه شده
                    break  # فقط اولین سری را بارگذاری کن

        except Exception as e:
            print(f"❌ [SYNC_LOAD] Error loading first series sync: {e}") # لاگ اضافه شده
            import traceback
            traceback.print_exc()

    def _apply_multi_viewer_sync(self, numbers):
        """⚡ Optimized: Synchronous viewer layout without processEvents delays"""
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

            # ⚡ OPTIMIZATION: Removed processEvents() call - introduces unwanted delay

        except Exception as e:
            print(f"❌ Error applying viewer layout sync: {e}")
            import traceback
            traceback.print_exc()

    def load_first_series_only(self, folder_path, series_number):
        """
        Load only the first series when it's downloaded
        بارگذاری فقط اولین سری وقتی دانلود شد

        This method is called by home_ui when the first series download completes.

        Args:
            folder_path: Path to the study folder
            series_number: The series number that was downloaded
        """
        try:
            print(f"🎯 load_first_series_only called: series {series_number}")

            # Update folder path if needed
            if folder_path and folder_path != self.parent_widget.import_folder_path:
                self.parent_widget.import_folder_path = folder_path

            # Check if we already have this series loaded
            series_key = f"series_{series_number}"
            if series_key in self.parent_widget.lst_series_name:
                print(f"⏭️ Series {series_number} already loaded")
                return

            # Load the series
            try:
                success = self._load_single_series_on_demand(int(series_number))

                if success:
                    self.parent_widget.lst_series_name.add(series_key)
                    print(f"✅ Series {series_number} loaded successfully")

                    # Display in viewer if it's the first series
                    if len(self.parent_widget.lst_series_name) == 1:
                        self._display_first_series_in_viewer()

                        # Hide any loading spinner
                        self._hide_loading_spinner()
                else:
                    print(f"⚠️ Failed to load series {series_number}")

            except Exception as load_error:
                print(f"❌ Error loading series {series_number}: {load_error}")

        except Exception as e:
            print(f"❌ Error in load_first_series_only: {e}")
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
            print(f"{'='*80}")
            print(f"📥 [PRIORITY LOAD] Loading series {series_number} (auto-display)")
            print(f"📁 Directory: {series_dir}")
            print(f"{'='*80}")

            # Update folder path if needed
            if series_dir and series_dir != self.parent_widget.import_folder_path:
                self.parent_widget.import_folder_path = series_dir

            # Check DICOM files
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            if not dicom_files:
                print(f"❌ No DICOM files found in {series_dir}")
                return

            # Skip if already loaded
            series_key = f"series_{series_number}"
            if series_key in self.parent_widget.lst_series_name:
                print(f"⏭️ Series {series_number} already loaded")
                return

            # ✅ FIX: Handle both series numbers and Series Instance UIDs
            try:
                series_int = int(series_number)
            except ValueError:
                # Not a simple number - extract series number from directory name
                # Directory name should be the actual series number
                try:
                    series_int = int(series_path.name)
                    print(f"   🔍 Extracted series number {series_int} from directory name")
                except ValueError:
                    print(f"❌ Cannot determine series number from UID {series_number} or directory {series_path.name}")
                    return

            # Load the series
            success = self._load_single_series_on_demand(series_int)
            if not success:
                print(f"❌ Failed to load series {series_int}")
                return

            # Auto-display in viewers
            if (not self._first_series_displayed) or self._any_viewer_empty():
                if self._display_first_series_in_all_viewers(str(series_int)):
                    self._mark_first_series_displayed()
            else:
                self.parent_widget.change_series_on_viewer(series_int, flag_change_selected_widget=True)

            # Mark as ready
            if hasattr(self.parent_widget, 'thumbnail_manager'):
                self.parent_widget.thumbnail_manager.set_series_ready(str(series_number))
                self.parent_widget.thumbnail_manager.apply_border_states_new()

            print(f"✅ Series {series_int} loaded and displayed.")
        except Exception as e:
            print(f"❌ CRITICAL ERROR in load_series_immediately: {e}")
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

            # Just mark ready — load_series_on_demand handles display via signal
            if hasattr(self.parent_widget, 'thumbnail_manager') and self.parent_widget.thumbnail_manager:
                self.parent_widget.thumbnail_manager.set_series_ready(str(series_key))
                self.parent_widget.thumbnail_manager.apply_border_states_new()
        except Exception as e:
            print(f"⚠️ Error triggering priority display: {e}")

    def _distribute_series_to_viewers(self):
        """
        ⚡ OPTIMIZED: Distribute series to viewers with efficient tracking.
        
        Improvements:
        - Uses set-based deduplication instead of nested loops
        - Single pass through viewers
        - O(n) instead of O(n²)
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
                
                # ⚡ FAST: Find first undisplayed series
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
            print(f"❌ [DISTRIBUTE] Error distributing series to viewers: {e}")
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

        print(f"   ✅ Viewer {viewer_idx} populated successfully")
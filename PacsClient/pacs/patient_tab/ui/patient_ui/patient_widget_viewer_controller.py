"""
Viewer Controller Module
Encapsulates all viewer-related responsibilities for PatientWidget
"""

import asyncio
import gc
import time
import os
import copy
from collections import deque
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
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget, grow_vtk_inplace
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
from PacsClient.pacs.patient_tab.zeta_boost.warmup_subprocess import (
    WarmupSubprocessManager, WarmupRequest, WarmupResult, result_to_vtk,
)
from PacsClient.utils.boost_viewer_config import load_boost_viewer_enabled
from PacsClient.utils.viewer_backend_config import (
    BACKEND_VTK,
    BACKEND_PYDICOM,
    load_viewer_backend,
    resolve_viewer_backend,
)
from PacsClient.pacs.patient_tab.viewers.backends.lazy_volume_registry import get_loader as get_lazy_loader
from PacsClient.utils.diagnostic_logging import new_correlation_id, set_log_context, now_ms, log_stage_timing

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"


class SliceTickSlider(QSlider):
    """
    Custom QSlider that paints per-slice tick marks along the groove.
    â€¢ Non-current ticks: thin, semi-transparent.
    â€¢ Current-position tick: wider, bright accent colour.
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
                # Future / unvisited slices â€” neutral gray
                color = self._unvisited_color

            pen = QPen(color, 1.0)
            pen.setCapStyle(Qt.FlatCap)  # flat ends â†’ crisp dash, not rounded blob
            painter.setPen(pen)
            painter.drawLine(cx - tick_half_w, y, cx + tick_half_w, y)

        # --- current-position indicator: single filled circle / dot ---
        painter.setRenderHint(QPainter.Antialiasing, True)  # smooth circle only
        frac_cur = (cur_val - self.minimum()) / total
        if inverted:
            y_cur = int(groove_top + frac_cur * groove_len)
        else:
            y_cur = int(groove_bottom - frac_cur * groove_len)

        dot_radius = 5  # 10 px diameter â€” easy to see and grab
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
        self._viewer_switch_inflight = set()  # {(viewer_id, series_number)}
        
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

        # â”€â”€ Dynamic capacity: scale limits to system RAM â”€â”€
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
        self._heavy_warmup_idle_sec = float(os.getenv("AIPACS_HEAVY_WARMUP_IDLE_SEC", "2.5") or "2.5")
        self._plan_a_viewer_first = os.getenv("AIPACS_PLAN_A_VIEWER_FIRST", "1") == "1"
        self._viewer_interaction_pause_ms = int(os.getenv("AIPACS_VIEWER_INTERACTION_PAUSE_MS", "350") or "350")
        self._open_warmup_min_idle_sec = max(0.0, float(os.getenv("AIPACS_OPEN_WARMUP_MIN_IDLE_SEC", "1.2") or "1.2"))
        self._interaction_release_token = 0
        self._interactive_preview_enabled = os.getenv("AIPACS_INTERACTIVE_PREVIEW_ENABLED", "0") == "1"
        self._interactive_preview_max_slices = max(1, int(os.getenv("AIPACS_INTERACTIVE_PREVIEW_MAX_SLICES", "64") or "64"))
        # Slice-focused architecture (default ON): keep Zeta focused on
        # active-series slice window (±20) instead of whole-series warmup.
        self._zeta_slice_focus_mode = os.getenv("AIPACS_ZETA_SLICE_FOCUS_MODE", "1") == "1"

        # Deterministic full-series cache â€” now single-layer (ZetaBoost only).
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

        # â”€â”€ Per-series download warmup (controlled Mode B caching) â”€â”€
        # v2.2.3.2.3: Moved from in-process thread to SEPARATE SUBPROCESS.
        # The old thread-based approach caused GIL contention even at IDLE
        # priority because pydicom header reads + SimpleITK wrapper calls
        # acquire/release the GIL at high frequency.  The subprocess has
        # its own GIL â€” zero contention with VTK render on the main thread.
        #
        # Legacy thread fields kept for fallback (AIPACS_DL_WARMUP_SUBPROCESS=0).
        self._dl_warmup_queue: deque = deque()
        self._dl_warmup_thread = None  # type: threading.Thread | None
        self._dl_warmup_lock = threading.Lock()
        self._dl_warmup_stop = threading.Event()
        self._dl_warmup_cached_count: int = 0
        _DL_WARMUP_MAX_CACHED = int(os.getenv("AIPACS_DL_WARMUP_MAX_CACHED", "4") or "4")
        _DL_WARMUP_MAX_SLICES = int(os.getenv("AIPACS_DL_WARMUP_MAX_SLICES", "200") or "200")
        _DL_WARMUP_INTER_DELAY = float(os.getenv("AIPACS_DL_WARMUP_INTER_DELAY", "1.5") or "1.5")
        self._DL_WARMUP_MAX_CACHED = max(1, _DL_WARMUP_MAX_CACHED)
        self._DL_WARMUP_MAX_SLICES = max(10, _DL_WARMUP_MAX_SLICES)
        self._DL_WARMUP_INTER_DELAY = max(1.0, _DL_WARMUP_INTER_DELAY)
        self._dl_warmup_enqueued = set()  # prevent duplicate enqueue

        # v2.2.3.2.3: Subprocess-based warmup (GIL-free Mode B caching)
        self._dl_warmup_use_subprocess = os.getenv("AIPACS_DL_WARMUP_SUBPROCESS", "1") == "1"
        if self._zeta_slice_focus_mode:
            # Whole-series download warmup is intentionally disabled in
            # slice-focused mode.
            self._dl_warmup_use_subprocess = False
        self._warmup_subprocess_mgr: WarmupSubprocessManager | None = None
        self._warmup_result_timer: QTimer | None = None

        # â”€â”€ Pipeline orchestrator (replaces timer-based download gating) â”€â”€
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
        # Mode B: Image Slice Booster â€” lightweight آ±20 slice window cache for
        # the single active series.  Zero RAM impact on other series.
        self._image_slice_booster: ImageSliceBooster = ImageSliceBooster(
            logger=self.logger
        )
        try:
            print(
                f"ℹ️ [ZetaBoost] slice_focus_mode={self._zeta_slice_focus_mode} "
                f"(active-series ±20 slice window)"
            )
        except Exception:
            pass
        print(
            f"ًں”§ [ZetaBoost][CAPACITY] tier={_cap['tier']} RAM={_cap['total_ram_mb']}MB "
            f"budget={_cap['byte_budget']//(1024*1024)}MB entries={_cap['max_entries']} "
            f"parallel={_cap['max_parallel_loads']} warmup_workers={_cap['warmup_workers']} "
            f"heavy_threshold={_cap['warmup_max_slices']}slices "
            f"disk_persist_max={_cap['disk_persist_max']//(1024*1024)}MB"
        )

        # -- Progressive series loading (incremental display during download) --
        self._progressive_series = {}  # series_number -> {total, last_grow_count}
        self._progressive_grow_timer = QTimer()
        self._progressive_grow_timer.setSingleShot(True)
        self._progressive_grow_timer.setInterval(500)
        self._progressive_grow_timer.timeout.connect(self._flush_progressive_grow)
        self._progressive_grow_batch_size = max(
            5, int(os.getenv("AIPACS_PROGRESSIVE_GROW_BATCH", "10") or "10")
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
            print(f"âœ… Default modality grid config created: {GRID_CONFIG_PATH}")
        except Exception as e:
            print(f"âڑ ï¸ڈ Could not create default grid config: {e}")

    def _is_boostviewer_enabled_runtime(self) -> bool:
        try:
            return bool(load_boost_viewer_enabled(default=True))
        except Exception:
            return True

    def _is_fast_viewer_mode(self) -> bool:
        """True when the unified viewer mode is Fast (PyDicom + local ±20 boost).
        In Fast mode, series-level warmup (Plan A/B) is skipped.
        The local ±20 ImageSliceBooster still runs normally."""
        try:
            return load_viewer_backend() in (BACKEND_PYDICOM, "pydicom_qt")
        except Exception:
            return False

    @staticmethod
    def _compute_dynamic_capacity() -> dict:
        """Scale ZetaBoost capacity to system RAM.

        Ensures high-capacity studies are handled without artificial limits:
        - 20+ series (cardiac/prostate MRI)
        - 700+ images per series (dynamic series)
        - 2000+ images per series (perfusion runs)

        Tiers (by total physical RAM):
            â‰¥30 GB  â†’ 4 GB budget, 60 entries, 3 parallel, 3 warmup workers
            â‰¥15 GB  â†’ 2.4 GB budget, 48 entries, 3 parallel, 3 warmup workers
            â‰¥7.5 GB â†’ 1.6 GB budget, 36 entries, 2 parallel, 2 warmup workers
            <7.5 GB â†’ 1.2 GB budget, 24 entries, 2 parallel, 2 warmup workers

        Runtime RAM guards (psutil in _filter_heavy_candidates_by_capacity and
        engine._check_system_memory_ok) still throttle if available RAM drops.
        """
        try:
            import psutil
            total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception:
            total_mb = 8192  # conservative fallback

        MB = 1024 * 1024

        if total_mb >= 30720:  # â‰¥30 GB
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
        elif total_mb >= 15360:  # â‰¥15 GB
            return {
                'tier': '15GB+',
                'total_ram_mb': total_mb,
                'byte_budget': 1200 * MB,   # ~24 series أ— 50 MB each
                'max_entries': 24,
                'max_parallel_loads': 2,  # v2.2.3.2.2: 2 parallel warmup workers (safe: BELOW_NORMAL priority + stale guard)
                'warmup_workers': 2,
                'background_workers': 1,
                'warmup_max_slices': 600,
                'disk_persist_max': 600 * MB,
            }
        elif total_mb >= 7680:  # â‰¥7.5 GB
            return {
                'tier': '8GB+',
                'total_ram_mb': total_mb,
                'byte_budget': 800 * MB,    # ~16 series أ— 50 MB each; safe on 8 GB
                'max_entries': 16,           # covers full 10-series study + headroom
                'max_parallel_loads': 2,     # v2.2.3.2.2: allow 2 parallel warmup loads (BELOW_NORMAL priority guards VTK)
                'warmup_workers': 2,
                'background_workers': 1,
                'warmup_max_slices': 500,    # raised from 250 â†’ series with 356 slices now eligible
                'disk_persist_max': 500 * MB,
            }
        else:  # <7.5 GB
            return {
                'tier': 'low',
                'total_ram_mb': total_mb,
                'byte_budget': 400 * MB,    # ~8 series أ— 50 MB each
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
                    f"ًںڑ€ [ZetaBoost][MANUAL_TRIGGER] study={getattr(self.parent_widget, 'study_uid', 'unknown')} "
                    f"reason={reason}"
                )
        except Exception:
            pass

    def _zeta_boost_load_series(self, series_number: str):
        """Background worker callback used by ZetaBoost to warm/cache series.

        FULLY INDEPENDENT â€” no shared locks with the interactive/viewer path.
        The engine worker already attempts diskâ†’memory promotion before
        calling this.  If we reach here, the series must be loaded from
        DICOM source.  If the interactive viewer is already loading the
        same series, this callback yields immediately (skip) so we never
        duplicate expensive I/O.
        """
        try:
            _cb_start = time.perf_counter()
            if not self._tab_active:
                print(f"ًں”§ [WARMUP_CB] series={series_number} â†’ skip (tab inactive)")
                return True
            sn = str(series_number)
            if not sn.isdigit():
                return True

            # Avoid repeated expensive attempts for series that already failed deterministically.
            if sn in self._zeta_boost_failed_series:
                print(f"ًں”§ [WARMUP_CB] series={sn} â†’ skip (previously failed)")
                return True

            # Check if engineâ€™s disk promotion already placed it in memory
            # (fast O(1) memory-only check, no disk I/O).
            if self.zeta_boost.has_in_memory(sn):
                print(f"ًں”§ [WARMUP_CB] series={sn} â†’ skip (already in memory) {(time.perf_counter()-_cb_start)*1000:.1f}ms")
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
                        print(f"ًں”§ [WARMUP_CB] series={sn} â†’ reused from thumbnail cache {(time.perf_counter()-_cb_start)*1000:.1f}ms")
                        return True
            except Exception:
                pass
            print(f"ًں”§ [WARMUP_CB] series={sn} â†’ starting DICOM load...")

            study_path = self._get_correct_study_path()
            if not study_path:
                return False

            # Yield to interactive via LoadCoordinator: if any path is
            # already loading this series, warmup skips to avoid duplicate I/O.
            _coord_status, _coord_event = self._load_coordinator.try_acquire(sn, owner='warmup')
            if _coord_status == 'skip':
                print(f"ًں”§ [WARMUP_CB] series={sn} â†’ skip (another load in progress)")
                return True
            # Also check legacy dedup set for extra safety.
            with self._series_load_lock:
                if sn in self._loading_series_numbers:
                    self._load_coordinator.complete(sn)
                    print(f"ًں”§ [WARMUP_CB] series={sn} â†’ skip (interactive is loading)")
                    return True

            # Load DICOM+ITK independently (no shared lock with viewer).
            # max_itk_threads=2: cap warmup to 2 ITK threads so background
            # loading doesn't saturate the CPU and cause VTK render spikes
            # during Mode A scrolling (same cap used for Mode B DL_WARMUP).
            result_gen = load_single_series_by_number(
                study_path=study_path,
                series_number=int(sn),
                patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
                skip_fs_validation=True,  # warmup: trust DB paths, skip glob+exists
                max_itk_threads=2,       # cap: keep CPU free for VTK render
                max_pydicom_workers=2,   # v2.2.3.2.5: cap pydicom threads to reduce GIL contention
            )

            def _mark_failed(reason: str):
                """Record the series as permanently failed with a reason tag."""
                self._zeta_boost_failed_series.add(sn)
                print(f"âڑ ï¸ڈ [WARMUP_CB] series={sn} SKIP reason={reason}")

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
                    
                    # âœ… OPTIMIZATION: ط¨ط¹ط¯ ط§ط² cache putطŒ prefetch ط³ط±غŒط² ظ…ط¬ط§ظˆط± ط¨ظ„ط§ظپط§طµظ„ظ‡
                    threading.Thread(
                        target=self._prefetch_adjacent_series,
                        args=(sn,),
                        daemon=True
                    ).start()
                    
                    break
            except Exception as iter_err:
                print(f"âڑ ï¸ڈ [WARMUP_CB] series={sn} iteration error: {iter_err}")
            finally:
                # Release LoadCoordinator lock so interactive callers unblock.
                self._load_coordinator.complete(sn)

            _load_elapsed = (time.perf_counter() - _cb_start) * 1000
            if cached_ok:
                print(f"ًں”§ [WARMUP_CB] series={sn} â†’ OK {_load_elapsed:.0f}ms")
                return True
            # ---- failure categorization ----
            if item_count == 0:
                _mark_failed("no_dicom_data")
                print(
                    f"ًں”§ [WARMUP_CB] series={sn} â†’ FAILED(no_data) {_load_elapsed:.0f}ms "
                    f"reason: generator yielded nothing â€” non-image DICOM, missing files, or unsupported format"
                )
            else:
                _mark_failed("no_usable_vtk")
                print(
                    f"ًں”§ [WARMUP_CB] series={sn} â†’ FAILED(no_usable_vtk) items={item_count} "
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

    # ================================================================
    # PROGRESSIVE SERIES LOADING — Incremental display during download
    # ================================================================

    def on_series_images_progress(self, series_number: str, downloaded: int, total: int):
        """Called when new images for a series have been downloaded.

        Triggers progressive display: first batch opens the viewer, subsequent
        batches grow the volume in-place so the user sees progress live.
        """
        sn = str(series_number)
        if total <= 0 or downloaded <= 0:
            return

        # Track this series for progressive updates
        if sn not in self._progressive_series:
            self._progressive_series[sn] = {"total": total, "last_grow_count": 0}
        info = self._progressive_series[sn]
        info["total"] = max(info["total"], total)

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

        # Check if a viewer already shows this series (non-progressive, e.g. user
        # clicked thumbnail before progress signals started).  If so, activate
        # progressive mode retroactively so grows will work.
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
                    # Fast mode: activate ±20 booster for the active series
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
                    return  # Will grow on next progress signal

        # No viewer showing this series yet — start first progressive display
        if not self._first_series_displayed and downloaded >= self._progressive_grow_batch_size:
            self._start_progressive_display(sn, downloaded, total)

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

    def _start_progressive_display(self, series_number: str, downloaded: int, total: int):
        """Display a partially downloaded series for the first time."""
        import asyncio
        self.logger.info(
            "progressive: START first display series=%s downloaded=%d total=%d",
            series_number, downloaded, total,
        )
        self._progressive_series.setdefault(series_number, {
            "total": total, "last_grow_count": 0,
        })

        async def _load_and_show():
            try:
                await self._async_load_and_display_series(
                    series_number,
                    progressive_total=total,
                )
            except Exception as e:
                self.logger.warning("progressive: first display failed: %s", e)

        try:
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(_load_and_show())
            self.parent_widget._background_tasks.add(task)
            task.add_done_callback(lambda t: self.parent_widget._background_tasks.discard(t))
        except RuntimeError:
            pass  # No event loop — fallback will happen via series_downloaded

    def _flush_progressive_grow(self):
        """Timer callback: grow all progressive viewers with newly downloaded images."""
        import asyncio

        is_fast = self._is_fast_viewer_mode()

        for sn, info in list(self._progressive_series.items()):
            pending = info.get("pending_downloaded", 0)
            if pending <= info.get("last_grow_count", 0):
                continue
            viewers = self._find_progressive_viewers(sn)
            if not viewers:
                continue

            if is_fast:
                # Fast mode: refresh backend file list + update available count
                # (no VTK volume reconstruction needed)
                self._grow_progressive_fast(sn, pending, viewers)
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
                # 1. Refresh the PyDicom backend file list + grow lazy volume
                loader = getattr(vtk_w, "_lazy_loader", None)
                backend = getattr(loader, "backend", None) if loader is not None else None
                if backend is not None and hasattr(backend, "refresh_file_list"):
                    new_count = backend.refresh_file_list()
                    # Grow the lazy volume memmap/VTK dims to match new file count
                    if loader is not None and hasattr(loader, "grow"):
                        new_count = loader.grow()
                    elif loader is not None and hasattr(loader, "slice_count"):
                        loader.slice_count = new_count
            except Exception as exc:
                self.logger.debug("progressive-fast: refresh_file_list/grow failed: %s", exc)

            # 2. Update available slice count on the widget
            vtk_w.update_available_slice_count(new_count)

            # 3. Update slider max (may have grown if get_count_of_slices uses
            #    progressive total — but in case it doesn't yet, force it)
            slider = getattr(node, "slider", None)
            if slider is not None:
                try:
                    slider.blockSignals(True)
                    slider.setMaximum(max(0, vtk_w.get_count_of_slices() - 1))
                    slider.blockSignals(False)
                except Exception:
                    pass

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

        # 5. Update stored metadata instances so re-drop sees the real count
        self._refresh_stored_metadata_instances(series_number, new_count)

        info["last_grow_count"] = new_count
        self.logger.info(
            "progressive-fast: grew series=%s available=%d/%d",
            series_number, new_count, total,
        )

        # 6. Check if download completed
        if new_count >= total and total > 0:
            # Final refresh of stored metadata with complete file list
            self._refresh_stored_metadata_instances(series_number, new_count)
            # Invalidate stale caches so next access rebuilds from full data
            self._invalidate_series_caches(series_number)

            for vtk_w, node in viewers:
                vtk_w.exit_progressive_mode()
            self._progressive_series.pop(series_number, None)
            self.logger.info(
                "progressive-fast: series=%s COMPLETE (%d slices)", series_number, new_count
            )

    async def _grow_progressive_viewer_async(self, series_number: str, expected_count: int):
        """Background: reload partial series from disk and grow viewers in-place."""
        import asyncio

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
            self._refresh_stored_metadata_instances(series_number, new_z)
            self._invalidate_series_caches(series_number)
            for vtk_w, node in viewers:
                vtk_w.exit_progressive_mode()
            self._progressive_series.pop(series_number, None)
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
        """Called when a series finishes downloading completely.

        Ensures progressive mode is exited and final data is loaded.
        """
        sn = str(series_number)
        self._progressive_series.pop(sn, None)
        # Exit progressive mode on any viewers showing this series
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is not None and vtk_w._progressive_series_number == sn:
                vtk_w.exit_progressive_mode()

    def _activate_progressive_mode_on_viewers(self, series_number: str, total_expected: int):
        """After first progressive display, mark viewers for progressive growth.

        In Fast mode, also activates the ImageSliceBooster for ±20 prefetch.
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

                # Fast mode: activate ImageSliceBooster for ±20 prefetch
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
        # Start warmup shortly after tab-open bootstrap to avoid competing with first render.
        try:
            # Mode A detection: only if all series are pre-downloaded (study complete)
            from PacsClient.pacs.patient_tab.utils.utils import check_study_complete
            study_uid = getattr(self.parent_widget, 'study_uid', None)
            if self.pipeline.state == PipelineState.IDLE and study_uid and check_study_complete(study_uid):
                self.pipeline.mark_pre_downloaded()
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
                    print(f"ًں”چ [CACHE_GET] series={key_sn} source=zeta_boost {_fcg_ms:.0f}ms")
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
        print(f"🗑️ [CACHE_INVALIDATE] series={sn} cleared all cache layers")

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

            # Collect existing instance paths for dedup
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
                new_instances.append(stub)

            if len(new_instances) <= existing_count:
                return

            # Mutate the metadata in-place so all references see the updated list
            metadata["instances"] = new_instances

            # Bump caches to reflect the updated metadata
            vtk_data = item.get("vtk_image_data")
            if vtk_data is not None:
                result = (vtk_data, metadata, idx)
                self._series_cache[sn] = result
                self._hot_series_cache[sn] = result

            print(
                f"📋 [METADATA_REFRESH] series={sn} instances {existing_count} → {len(new_instances)}"
            )
        except Exception as exc:
            self.logger.debug("_refresh_stored_metadata_instances failed for %s: %s", sn, exc)

    def _count_series_files_on_disk(self, series_number: str) -> int:
        """Return the number of .dcm files on disk for *series_number*."""
        try:
            study_path = self._get_correct_study_path()
            if not study_path:
                return 0
            series_dir = Path(study_path) / str(series_number)
            if not series_dir.is_dir():
                return 0
            return sum(1 for f in series_dir.iterdir()
                       if f.is_file() and f.suffix.lower() in (".dcm", ".dicom"))
        except Exception:
            return 0

    # â”€â”€ Look-ahead warmup: pre-cache adjacent series after drag-drop â”€â”€
    _LOOKAHEAD_COUNT = 2  # number of adjacent series to pre-warm after drag-drop

    def _get_requested_viewer_backend(self) -> str:
        try:
            resolution = resolve_viewer_backend(
                metadata=None,
                settings=load_viewer_backend(default=BACKEND_VTK),
            )
            return str(resolution.get("requested_backend", BACKEND_VTK) or BACKEND_VTK)
        except Exception:
            return BACKEND_VTK

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
            if self._zeta_slice_focus_mode:
                return
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
                    f"ًں”® [ZetaBoost][LOOKAHEAD] series={sn} â†’ pre-warming {len(queue)} adjacent: {queue}"
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
        # here.  That triggered _full_cache_get â†’ zeta_boost.get(memory_only=False) on
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
                print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ HOT CACHE HIT")
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
            print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ hot cache stale, removed")
        
        # 2. Check main cache
        if series_str in self._series_cache:
            result = self._series_cache[series_str]
            if _entry_is_valid(result):
                self._hot_series_cache[series_str] = result
                print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ MAIN CACHE HIT")
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
            print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ main cache stale, removed")
        
        # 3. Check index for fallback
        if series_str in self._series_number_to_index:
            idx = self._series_number_to_index[series_str]
            print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ found in index, idx={idx}")
            if idx < len(self.parent_widget.lst_thumbnails_data):
                item = self.parent_widget.lst_thumbnails_data[idx]
                vtk_data = item.get('vtk_image_data')
                meta = item.get('metadata')
                print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ item retrieved: vtk={vtk_data is not None}, meta={meta is not None}")
                if vtk_data is not None and meta is not None:
                    result = (vtk_data, meta, idx)
                    self._series_cache[series_str] = result
                    if len(self._hot_series_cache) > 3:  # Keep hot cache small
                        self._hot_series_cache.pop(next(iter(self._hot_series_cache)))
                    self._hot_series_cache[series_str] = result
                    print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ RETURNING from index lookup")
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
                    print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ item has None data, continuing to full cache")
            else:
                print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ idx {idx} >= list length {len(self.parent_widget.lst_thumbnails_data)}")
        else:
            print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ NOT in _series_number_to_index")

        # 4. Deterministic full-series cache fallback (survives index churn)
        cached_full = self._full_cache_get(series_str)
        if cached_full is not None:
            vtk_data, meta = cached_full[0], cached_full[1]
            print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ FULL CACHE HIT: vtk={vtk_data is not None}, meta={meta is not None}")
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
                            allow_append_if_missing=False,
                        )
                        print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ rehydrated to lst_thumbnails_data at idx={idx}")
                    except Exception as e:
                        print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ rehydrate FAILED: {e}")
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
                                allow_append_if_missing=False,
                            )
                        )
                    except Exception:
                        pass

                if idx >= 0:
                    result = (vtk_data, meta, idx)
                    self._series_cache[series_str] = result
                    self._hot_series_cache[series_str] = result
                    print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ RETURNING from full cache")
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
            print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ NOT in full cache")
        
        print(f"ًں”چ [FAST_LOOKUP] series={series_str} â†’ FINAL RETURN: None, None, -1")
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

            print(f"ًں”§ [LAYOUT] Applying {rows}x{cols} layout (need {required_count} viewers, have {current_count})")

            # âœ… FLICKER FIX: Disable updates during batch viewer creation
            self.parent_widget.setUpdatesEnabled(False)
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(False)

            # 1. Cleanup existing viewers but preserve data
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()
            print("   âœ… cleanup_all_viewers completed")  # No processEvents here

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
                    print(f"   âڑ ï¸ڈ Error creating viewer {i}: {e}")
                    # Create fallback viewer
                    node = self._create_fallback_viewer()
                    self.lst_nodes_viewer.append(node)

                # v2.2.3.2.7: Yield to Qt event loop between viewer creations.
                # On software OpenGL each VTK widget creation takes 5-15s.
                # Without this yield, scroll events and timers starve for
                # the entire creation loop (10-60s for 2-4 viewers).
                # setUpdatesEnabled(False) is still active so no flicker.
                if i < required_count - 1:
                    try:
                        from PySide6.QtWidgets import QApplication
                        QApplication.processEvents()
                    except Exception:
                        pass

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

            print(f"âœ… [LAYOUT] Applied {rows}x{cols} layout with {len(self.lst_nodes_viewer)} viewers")

        except Exception as e:
            print(f"â‌Œ [LAYOUT] Error: {e}")
            import traceback
            traceback.print_exc()
            if modify_by_user:
                self._hide_loading_msg()
        finally:
            # âœ… FLICKER FIX: Re-enable updates after batch creation
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(True)
            self.parent_widget.setUpdatesEnabled(True)
            # Single repaint after all changes
            self.parent_widget.update()

    def new_viewer(self, default_thumb_index=0):
        print(f"\n{'='*80}")
        print(f"ًں”¨ [new_viewer] START - thumb_index={default_thumb_index}")
        self.logger.info(f"Creating new viewer with thumb index {default_thumb_index}")

        # Count existing viewers - if too many, be more aggressive with cleanup
        viewer_count = len(self.lst_nodes_viewer)

        # Hard limit protection
        if viewer_count >= self._max_viewers_per_session:
            print(f"   âڑ ï¸ڈ PROTECTION: Reached max viewers limit ({viewer_count}/{self._max_viewers_per_session})")
            print("   âڑ ï¸ڈ Creating lightweight placeholder viewer instead")
            try:
                return self._create_fallback_viewer()
            except Exception as e:
                print(f"   â‌Œ Even fallback failed: {e}")
                self.logger.error(f"Max viewers exceeded and fallback failed: {e}", exc_info=True)
                raise

        # Aggressive cleanup for high viewer counts
        if viewer_count > 15:
            print(f"   âڑ ï¸ڈ WARNING: Already have {viewer_count} viewers - running lightweight cleanup")
            # REMOVED: gc.collect() was stop-the-world on UI thread causing user-visible freezes
            gc.collect(generation=0)  # generation=0 only: fast, collects young objects

        # Periodic cleanup
        import time
        current_time = time.time()
        if current_time - self._last_gc_time > 10.0 and viewer_count > 5:  # Every 10 seconds (was 2s)
            print(f"   ًں§¹ [Periodic GC] Cleaning up ({viewer_count} viewers)")
            gc.collect(generation=0)  # generation=0 only for minimal UI impact
            self._last_gc_time = current_time

        vtk_widget = None
        slider = None

        try:
            # âœ… FLICKER FIX: Removed processEvents - batching UI updates instead
            # processEvents was causing thumbnail loading to interrupt viewer creation

            print("   ًں“گ Creating grid layout...")
            try:
                layout = QGridLayout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                print("   âœ… Grid layout created")
            except Exception as le:
                print(f"   âڑ ï¸ڈ Layout creation warning: {le}")
                raise RuntimeError(f"Failed to create grid layout: {le}")

            # Check if we have thumbnail data
            print("   ًں”چ Checking thumbnail data...")
            try:
                has_data = (hasattr(self.parent_widget, 'lst_thumbnails_data') and
                           self.parent_widget.lst_thumbnails_data and
                           len(self.parent_widget.lst_thumbnails_data) > 0)
            except Exception as ce:
                print(f"   âڑ ï¸ڈ Data check warning: {ce}")
                has_data = False

            if not has_data:
                print("   ًں“¦ No thumbnail data, creating lightweight VTK widget...")
                try:
                    # âœ… FLICKER FIX: Use lightweight VTK widget with deferred rendering
                    vtk_widget = self._create_lightweight_vtk_placeholder()
                    if vtk_widget is None:
                        raise RuntimeError("_create_lightweight_vtk_placeholder returned None")
                    print("   âœ… Lightweight VTK widget created")
                except Exception as dwe:
                    print(f"   â‌Œ Lightweight VTK widget creation failed: {dwe}")
                    raise
            else:
                print(f"   âœ… Thumbnail data exists ({len(self.parent_widget.lst_thumbnails_data)} items)")
                print("   ًںژ¨ Creating new VTK widget...")
                try:
                    vtk_widget = self.create_new_vtk_widget(default_thumb_index)
                    if vtk_widget is None:
                        print("   âڑ ï¸ڈ create_new_vtk_widget returned None, using lightweight fallback")
                        vtk_widget = self._create_lightweight_vtk_placeholder()
                        if vtk_widget is None:
                            raise RuntimeError("Both create_new_vtk_widget and _create_lightweight_vtk_placeholder failed")
                    print("   âœ… VTK widget created")
                except Exception as vwe:
                    print(f"   â‌Œ VTK widget creation failed: {vwe}")
                    raise

            # Validate vtk_widget
            if vtk_widget is None:
                raise RuntimeError("vtk_widget is None after creation")

            # Ensure toolbar context is available for tool auto-deactivation
            if getattr(vtk_widget, 'patient_widget', None) is None:
                vtk_widget.patient_widget = self.parent_widget

            if not isinstance(vtk_widget, QWidget):
                raise RuntimeError(f"vtk_widget is not a QWidget, got {type(vtk_widget)}")

            print("   ًں“ٹ Creating slider...")
            try:
                slider = SliceTickSlider(Qt.Vertical, vtk_widget)
                if slider is None:
                    raise RuntimeError("QSlider constructor returned None")
                slider.setInvertedAppearance(True)
                slider.setMaximumWidth(12)
                print("   âœ… Slider created")
            except Exception as se:
                print(f"   â‌Œ Slider creation failed: {se}")
                raise RuntimeError(f"Failed to create slider: {se}")

        except Exception as e:
            print(f"   â‌Œ ERROR in new_viewer setup: {e}")
            self.logger.error(f"Error in new_viewer setup: {e}", exc_info=True)

            # Try to return fallback viewer
            try:
                print("   ًں”„ Attempting fallback viewer creation...")
                fallback = self._create_fallback_viewer()
                if fallback:
                    print("   âœ… Fallback viewer created successfully")
                    return fallback
            except Exception as fe:
                print(f"   â‌Œ Fallback viewer also failed: {fe}")

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
                /* ظ†ظˆط§ط± ط¹ظ…ظˆط¯غŒ (track) - ط³ط¨ع© Chrome */
                QSlider::groove:vertical {
                    background: rgba(0, 0, 0, 0.1);
                    width: 10px;
                    border-radius: 5px;
                    margin: 0px 0px;
                    border: none;
                }
                /* ط¯ط³طھظ‡ (thumb) - ظ…ط³طھط·غŒظ„غŒ ط¨ط§ ع¯ظˆط´ظ‡ ع¯ط±ط¯ ظ…ط«ظ„ Chrome */
                QSlider::handle:vertical {
                    background: rgba(128, 128, 128, 0.5);
                    width: 10px;
                    min-height: 40px;
                    border-radius: 5px;
                    margin: 0px 0px;
                    border: none;
                }
                /* ط­ط§ظ„طھ hover - طھغŒط±ظ‡â€Œطھط± ظ…غŒâ€Œط´ظˆط¯ */
                QSlider::handle:vertical:hover {
                    background: rgba(128, 128, 128, 0.7);
                }
                /* ط­ط§ظ„طھ ظپط´ط±ط¯ظ‡ ط´ط¯ظ† - ط®غŒظ„غŒ طھغŒط±ظ‡ */
                QSlider::handle:vertical:pressed {
                    background: rgba(96, 96, 96, 0.9);
                }
                /* ظ‚ط³ظ…طھ ط¨ط§ظ„ط§غŒ thumb - ط´ظپط§ظپ */
                QSlider::sub-page:vertical {
                    background: transparent;
                    border: none;
                }
                /* ظ‚ط³ظ…طھ ظ¾ط§غŒغŒظ† thumb - ط´ظپط§ظپ */
                QSlider::add-page:vertical {
                    background: transparent;
                    border: none;
                }
            """)
            
            # Force visibility and z-order
            slider.setVisible(True)
            slider.setAttribute(Qt.WA_TranslucentBackground, True)
            
            print("   âœ… Chrome-style scrollbar applied")
        except Exception as e:
            print(f"   âڑ ï¸ڈ Warning: Could not apply slider styling: {e}")

        try:
            print("   ًں“چ Adding widgets to layout...")
            # Add VTK widget to layout
            layout.addWidget(vtk_widget, 0, 0)
            
            print("   âœ… VTK widget added to layout")
        except Exception as e:
            print(f"   â‌Œ ERROR adding vtk widget to layout: {e}")
            self.logger.error(f"Error adding widgets to layout: {e}", exc_info=True)
            raise

        # Use QFrame instead of QWidget - QFrame is designed for borders!
        try:
            print("   ًں–¼ï¸ڈ Creating container frame...")
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
            print("   âœ… Container created")
            
            # CRITICAL: Add slider as DIRECT CHILD of VTK widget (not container)
            # This ensures slider is ALWAYS on top of the image
            print("   ًں“چ Adding Chrome-style slider overlay on VTK widget...")
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
            
            print("   âœ… Thin slider added as OVERLAY directly on VTK widget (ALWAYS on top)")
            
        except Exception as e:
            print(f"   â‌Œ ERROR creating container: {e}")
            self.logger.error(f"Error creating container: {e}", exc_info=True)
            raise

        # Create NodeViewer
        try:
            print("   ًں”— Creating NodeViewer...")
            new_node = NodeViewer(container, vtk_widget, slider)
            if new_node is None:
                raise RuntimeError("NodeViewer creation returned None")
            print("   âœ… NodeViewer created")
        except Exception as e:
            print(f"   â‌Œ ERROR creating NodeViewer: {e}")
            self.logger.error(f"Error creating NodeViewer: {e}", exc_info=True)
            raise

        # Set viewer ID and configure
        try:
            print("   ًں†” Setting viewer ID...")
            viewer_index = len(self.lst_nodes_viewer)

            # Safely set ID attribute
            if hasattr(vtk_widget, '__dict__'):
                vtk_widget.id_vtk_widget = viewer_index
            else:
                setattr(vtk_widget, 'id_vtk_widget', viewer_index)
            print(f"   âœ… Viewer ID set to {viewer_index}")

            print("   ًں“‌ Appending to lst_nodes_viewer...")
            self.lst_nodes_viewer.append(new_node)
            print("   âœ… Appended")
        except Exception as e:
            print(f"   â‌Œ ERROR setting viewer ID: {e}")
            self.logger.error(f"Error setting viewer ID: {e}", exc_info=True)
            raise

        # Configure slider
        try:
            print("   ًںژڑï¸ڈ Configuring slider...")

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

            # âœ… CRITICAL: Block signals during slider setup to prevent image number flickering
            slider.blockSignals(True)

            # Check if methods exist
            if not hasattr(vtk_widget, 'set_slider'):
                print("   âڑ ï¸ڈ VTK widget doesn't have set_slider yet (placeholder mode)")
                # For placeholder widgets, just set slider to default values
                slider.setMinimum(0)
                slider.setMaximum(0)
                slider.setValue(0)
                print("   âœ… Slider configured in placeholder mode (0 slices) - VISIBLE")
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
                print(f"   âœ… Slider configured (slices: {count_slices}, current: {mid_slices}) - VISIBLE")
        except Exception as e:
            print(f"   â‌Œ ERROR configuring slider: {e}")
            # Don't raise - allow viewer creation to continue
            # Just set slider to defaults
            slider.setMinimum(0)
            slider.setMaximum(0)
            slider.setValue(0)
            print("   âڑ ï¸ڈ Slider set to default values after error")
        finally:
            # âœ… CRITICAL: Unblock signals after all slider configuration is complete
            slider.blockSignals(False)

        # Connect signals
        try:
            print("   ًں”— Connecting slider signal...")
            self.parent_widget.on_slider_value_changed(vtk_widget, mid_slices)
            slider.valueChanged.connect(lambda val: self.parent_widget.on_slider_value_changed(vtk_widget, val))
            print("   âœ… Slider connected")
        except Exception as e:
            print(f"   âڑ ï¸ڈ Warning: Could not connect slider signal: {e}")
            self.logger.warning(f"Warning connecting slider signal: {e}")

        # Set VTK widget methods
        try:
            print("   ًں”§ Setting VTK widget methods...")
            if hasattr(vtk_widget, 'set_method_change_series_on_drop'):
                vtk_widget.set_method_change_series_on_drop(self.parent_widget.change_series_on_viewer)
            if hasattr(vtk_widget, 'set_method_change_container_border'):
                vtk_widget.set_method_change_container_border(self.change_container_border)
            print("   âœ… Methods set")
        except Exception as e:
            print(f"   âڑ ï¸ڈ Warning: Could not set VTK widget methods: {e}")
            self.logger.warning(f"Warning setting VTK widget methods: {e}")

        print(f"ًں”¨ [new_viewer] END - Successfully created viewer with ID {viewer_index}")
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

            # âœ… CRITICAL: Set solid background FIRST to prevent any flash
            if hasattr(vtk_widget, 'renderer'):
                vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)  # #1a1a2e in RGB
                # â‌Œ FLICKER FIX: DO NOT call Render() here - it causes initial flash
                # The background will be set when the widget is first shown

            # Minimize rendering updates until real data is loaded
            if hasattr(vtk_widget, 'render_window'):
                vtk_widget.render_window.SetDesiredUpdateRate(0.001)  # Very low update rate

            # Add a flag to indicate this is a placeholder
            vtk_widget._is_placeholder = True

            return vtk_widget
        except Exception as e:
            print(f"â‌Œ Error creating lightweight VTK widget: {e}")
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
                print(f"âڑ ï¸ڈ [create_new_vtk_widget] No thumbnail data at index {default_thumb_index}, using dummy")
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
                print(f"âڑ ï¸ڈ [create_new_vtk_widget] Error extracting thumbnail data: {e}")
                return self.create_dummy_vtk_widget()

            # Extract metadata safely
            try:
                series_name = metadata.get('series', {}).get('series_name', 'Unknown')
                series_number = metadata.get('series', {}).get('series_number', 0)
            except (AttributeError, TypeError) as e:
                print(f"âڑ ï¸ڈ [create_new_vtk_widget] Error extracting series info: {e}")
                series_name = 'Unknown'
                series_number = 0

            requested_backend = self._get_requested_viewer_backend()
            try:
                if self._needs_backend_rebuild(metadata, requested_backend):
                    print(
                        f"[BACKEND_RELOAD_INIT] series={series_number} rebuilding payload for backend={requested_backend}"
                    )
                    if str(series_number).isdigit():
                        self._load_single_series_on_demand(
                            int(series_number),
                            study_path=self._get_correct_study_path(),
                            target_vtk_widget=None,
                            allow_paired=False,
                            expected_token=None,
                            viewer_backend=requested_backend,
                            force_reload=(requested_backend == BACKEND_PYDICOM),
                        )
                        rebuilt_vtk, rebuilt_meta, rebuilt_idx = self._get_series_by_number_fast(str(series_number))
                        if rebuilt_vtk is not None and isinstance(rebuilt_meta, dict):
                            vtk_widget_data = rebuilt_vtk
                            metadata = copy.deepcopy(rebuilt_meta)
                            default_thumb_index = int(rebuilt_idx) if int(rebuilt_idx) >= 0 else default_thumb_index
            except Exception as e:
                print(f"âڑ ï¸ڈ [create_new_vtk_widget] backend rebuild check failed: {e}")

            # IMPORTANT: last_series_show must always store thumbnail/list index
            # (NOT series_number) so per-viewport state comparisons remain consistent.
            series_idx = default_thumb_index

            # Create VTK widget
            try:
                vtk_widget = self.creator_vtk_widget()
                if vtk_widget is None:
                    raise RuntimeError("creator_vtk_widget returned None")
            except Exception as e:
                print(f"â‌Œ [create_new_vtk_widget] Error creating VTK widget: {e}")
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
                print(f"âڑ ï¸ڈ [create_new_vtk_widget] Warning during combined series check: {e}")

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
                print(f"â‌Œ [create_new_vtk_widget] Error processing series: {e}")
                self.logger.error(f"Error processing series: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()

        except Exception as e:
            print(f"â‌Œ [create_new_vtk_widget] Unexpected error: {e}")
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
            print(f"â‌Œ Error in creator_vtk_widget: {e}")
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
                print(f"â‌Œ [SWITCH FAIL] Invalid target viewport for series {series_number}")
                self._hide_spinner_for_widget(target_widget_for_spinner)
                return

            # Re-entrancy guard: prevent duplicate same-series switch requests from
            # overlapping on the same viewport during active downloads.
            try:
                viewer_id = self._get_viewer_id(vtk_widget)
                switch_key = (viewer_id, series_number)
                if switch_key in self._viewer_switch_inflight:
                    print(f"âڈ³ [SWITCH DEDUP] Suppressed duplicate switch series={series_number} viewer={viewer_id}")
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
                    try:
                        displayed_count = len((current_metadata or {}).get("instances", []) or [])
                        disk_count = self._count_series_files_on_disk(series_number)
                        if disk_count > 0 and disk_count > displayed_count:
                            series_grew = True
                    except Exception:
                        pass
                    if (not backend_mismatch) and (not rebuild_needed) and (not series_grew):
                        if hasattr(vtk_widget, '_finalize_pending_action'):
                            try:
                                vtk_widget._finalize_pending_action(series_index, phase="switch_series_noop_same")
                            except Exception:
                                pass
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        print(f"[PROFILE] change_series_on_viewer: noop same-series series={series_number} total={(time.perf_counter() - _t0)*1000:.1f}ms")
                        return
                    # Same series re-drop with growth: if a lazy loader is present,
                    # grow it in-place instead of doing an expensive full reload
                    # that would restart the volume from scratch.
                    if series_grew and (not backend_mismatch) and (not rebuild_needed):
                        _grew_ok = False
                        try:
                            loader = getattr(vtk_widget, "_lazy_loader", None)
                            backend = getattr(loader, "backend", None) if loader else None
                            if backend is not None and hasattr(backend, "refresh_file_list"):
                                new_count = backend.refresh_file_list()
                                if loader is not None and hasattr(loader, "grow"):
                                    new_count = loader.grow()
                                vtk_widget.update_available_slice_count(new_count)
                                if slider is not None:
                                    try:
                                        slider.blockSignals(True)
                                        slider.setMaximum(max(0, vtk_widget.get_count_of_slices() - 1))
                                        slider.blockSignals(False)
                                    except Exception:
                                        pass
                                self._refresh_stored_metadata_instances(series_number, new_count)
                                _grew_ok = True
                                print(
                                    f"[PROFILE] change_series_on_viewer: in-place grow series={series_number} "
                                    f"slices={new_count} total={(time.perf_counter() - _t0)*1000:.1f}ms"
                                )
                        except Exception as _grow_exc:
                            self.logger.debug("same-series in-place grow failed: %s", _grow_exc)
                        if _grew_ok:
                            self._hide_spinner_for_widget(target_widget_for_spinner)
                            return
                    print(
                        f"[BACKEND_RELOAD_SAME_SERIES] series={series_number} current={getattr(vtk_widget, '_active_backend', BACKEND_VTK)} "
                        f"requested={requested_backend} rebuild_needed={rebuild_needed}"
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
            # Invalidate everything and force a fresh load directly from disk.
            # IMPORTANT: skip the lst_thumbnails_data linear scan — it would
            # return the same stale entry.  Go straight to async disk load.
            if metadata is not None:
                try:
                    cached_instance_count = len(metadata.get("instances", []) or [])
                    disk_count = self._count_series_files_on_disk(series_number)
                    if disk_count > 0 and disk_count > cached_instance_count:
                        print(
                            f"🔄 [STALE_GUARD] series={series_number} "
                            f"cached_instances={cached_instance_count} disk_files={disk_count} → forcing disk reload"
                        )
                        self._invalidate_series_caches(series_number)
                        study_path = self._get_correct_study_path()
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
                            force_reload=True,
                        )
                        return
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
            print(f"â‌Œ [SWITCH FAIL] series={series_index} error={e}")
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
            print(f"âڈ³ [ASYNC SWITCH] series={series_number} already in-flight for viewer={viewer_id}")
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
                use_preview = bool(
                    self._interactive_preview_enabled and
                    (exp_slices <= 0 or exp_slices <= self._interactive_preview_max_slices)
                )
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

            # Concurrent ITK guard: wait for any in-flight warmup/background ITK to
            # finish before starting this interactive ITK pipeline.  On weak hardware
            # (PC B, GLES2) two simultaneous ITK runs compete for CPU and each takes
            # 2x longer.  Waiting up to 3s for the current warmup to drain, then
            # running alone, is faster than 4-6s of concurrent execution.
            # _set_zeta_external_interactive_busy(True) already prevents NEW warmup
            # items from starting; this waits for the CURRENT inflight item to finish.
            try:
                if hasattr(self, 'zeta_boost') and self.zeta_boost is not None:
                    _drained = self.zeta_boost.wait_for_inflight_drain(timeout_sec=3.0)
                    if not _drained:
                        print(f"[ASYNC SWITCH] warmup still inflight after 3s, proceeding with contention for series={series_number}")
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
                        print(f"âڑ ï¸ڈ [ASYNC SWITCH] vtk_widget deleted for series={series_number}, aborting apply")
                        return

                    if not self._is_request_current(vtk_widget, expected_token):
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        return

                    if not ok:
                        self._trigger_download_if_needed(series_number)
                        print(f"[PROFILE] change_series_on_viewer: async load-on-demand FAILED for series {series_number} in {(time.perf_counter() - _t_load)*1000:.1f}ms")
                        if preview_applied:
                            print(f"â„¹ï¸ڈ [ASYNC SWITCH] preview remained active for series={series_number} (full load failed)")
                        self._hide_spinner_for_widget(target_widget_for_spinner)
                        return

                    print(f"[PROFILE] change_series_on_viewer: async load-on-demand OK for series {series_number} in {(time.perf_counter() - _t_load)*1000:.1f}ms")
                    vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_number)
                    if metadata is None or vtk_image_data is None:
                        print(f"â‌Œ [SWITCH FAIL] series={series_number} not found in cache after async loading")
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
                    print(f"â‌Œ [ASYNC SWITCH] _finish_on_ui crashed for series={series_number}: {e}")
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

        # If path itself is a series folder (numeric OR UID-named) and contains
        # DICOM files, use parent study folder.
        try:
            has_dicom = bool(next(path.glob("*.dcm"), None) or next(path.glob("*.DCM"), None))
        except Exception:
            has_dicom = False
        if has_dicom and path.parent.exists():
            return str(path.parent)

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
                print("âڑ ï¸ڈ [SWITCH RECOVERY] Invalid vtk_image_data (None), attempting recovery")
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
                    print("â‌Œ [SWITCH ABORT] Recovery failed: vtk_image_data still invalid")
                    return

            dims = vtk_image_data.GetDimensions() if hasattr(vtk_image_data, 'GetDimensions') else (0, 0, 0)
            if not dims or int(dims[0]) <= 0 or int(dims[1]) <= 0 or int(dims[2]) <= 0:
                print(f"âڑ ï¸ڈ [SWITCH RECOVERY] Invalid dimensions {dims}, attempting recovery")
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
                    print("â‌Œ [SWITCH ABORT] Recovery failed: invalid dimensions remain")
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

                    # Image Slice Booster: activate ±20 slice window for the
                    # newly displayed active series (Mode A + Mode B).
                    try:
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

                    # â”€â”€ Look-ahead warmup: pre-cache adjacent series â”€â”€
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
                        print(f"âڑ ï¸ڈ [RL] manage_reference_line error after switch: {_rl_err}")
        
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
            print(f"âڑ، [PREFETCH] Started for {len(queue)} series: {queue}")
        except Exception as e:
            self.logger.debug(f"Error starting background prefetch: {e}")

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
            print(f"ًں”§ [WARMUP_FILTER] detail: {' | '.join(_filter_details[:40])}")
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
                print(f"âڑ ï¸ڈ [ZetaBoost][VERIFY] preview_flagged_series={preview_flagged[:12]}")
            if missing:
                print(f"âڈ³ [ZetaBoost][VERIFY] not_warmed_series={missing[:12]}")
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
                print(f"â‌Œ [FIRST DISPLAY] series {series_number} not found in thumbnail cache")
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
                    self.parent_widget.metadata_fixed,
                    progressive_total=int(progressive_total),
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

            print("   ًں“‌ [Fallback] Creating layout...")
            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)

            print("   ًں–¼ï¸ڈ [Fallback] Creating container...")
            container = QFrame()
            container.setLayout(layout)

            print("   ًںژ¨ [Fallback] Creating dummy VTK widget...")
            vtk_widget = self.create_dummy_vtk_widget()
            if vtk_widget is None:
                raise RuntimeError("create_dummy_vtk_widget failed")

            print("    ًں“ٹ [Fallback] Creating slider...")
            slider = QSlider(Qt.Vertical)

            print("   ًں”— [Fallback] Creating NodeViewer...")
            node = NodeViewer(container, vtk_widget, slider)
            if node is None:
                raise RuntimeError("NodeViewer creation failed")

            print("   âœ… [Fallback] Fallback viewer created successfully")
            return node

        except Exception as e:
            print(f"   â‌Œ [Fallback] Error creating fallback viewer: {e}")
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

            # Ensure stale nodes are cleared after cleanup
            try:
                self.lst_nodes_viewer.clear()
            except Exception:
                pass

            print("âœ… cleanup_all_viewers completed")
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
                if vtk_full is not None and isinstance(meta_full, dict):
                    dims = vtk_full.GetDimensions() if hasattr(vtk_full, 'GetDimensions') else (0, 0, 0)
                    if int(dims[2]) > 1:  # full volume ظ…ظˆط¬ظˆط¯
                        _ms = (time.perf_counter() - _preview_start) * 1000
                        print(f"âڑ، [PREVIEW] series={series_number} cached_full {_ms:.0f}ms")
                        return vtk_full, meta_full
            except Exception:
                pass
            
            # ط³ط±غŒط² ط§ط² disk ع©ط´ غŒط§ source ط¨ط§ط±ع¯ط°ط§ط±غŒ ع©ظ†
            from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview
            
            vtk_preview, metadata = load_series_preview(
                study_path=study_path,
                series_number=int(series_number),
                max_slices=8  # max 8 slice ط¨ط±ط§غŒ preview
            )
            
            _elapsed = (time.perf_counter() - _preview_start) * 1000
            if vtk_preview is not None:
                print(f"âڑ، [PREVIEW] series={series_number} loaded {_elapsed:.0f}ms")
                return vtk_preview, metadata
            else:
                print(f"âڑ ï¸ڈ [PREVIEW] series={series_number} failed {_elapsed:.0f}ms")
                return None, None
                
        except Exception as e:
            print(f"âڑ ï¸ڈ [PREVIEW] exception: {e}")
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
            
            # Prefetch 3 ط³ط±غŒط² ط¨ط¹ط¯غŒ + 1 ط³ط±غŒط² ظ‚ط¨ظ„غŒ (ط§ع¯ط± ظ…ظˆط¬ظˆط¯ ط¨ط§ط´ظ†ط¯)
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
                
                # Skip ط§ع¯ط± ظ‚ط¨ظ„ط§ظ‹ queued غŒط§ in-memory
                if self.zeta_boost.has_in_memory(sn):
                    continue
                
                # Queue ط¨ط±ط§غŒ warmup lane (ط¨ط¯ظˆظ† blocking interactive)
                try:
                    self.zeta_boost.queue_load(sn, lane="warmup")
                    queued_count += 1
                except Exception:
                    pass
            
            if queued_count > 0:
                print(f"ًں”¥ [PREFETCH] series={current_series_number} queued={queued_count} adjacent")
                
        except Exception as e:
            print(f"âڑ ï¸ڈ [PREFETCH] error: {e}")

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
                    print(f"â‌Œ No valid study path found")
                    return False

            print(f"ًں“‚ [LOAD] Loading series {series_number} from {study_path} (thread={threading.current_thread().name})")
            self.logger.info(
                "viewer-backend stage=load_request series=%s backend=%s force_reload=%s",
                str(series_number),
                str(viewer_backend or BACKEND_VTK),
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
                            print(f"âڈ­ï¸ڈ [LOAD SKIP] same series already visible series={series_number}")
                            return True
            except Exception:
                pass

            # Bail out early if tab was deactivated while queued (e.g. user pressed F5).
            # Allow explicit user-driven loads even if tab_active flag is stale.
            if not self._tab_active and not self._interactive_load_in_progress:
                print(f"âڈ­ï¸ڈ [LOAD SKIP] tab inactive for series {series_number}")
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
                    print(f"âڑ، [CACHE HIT] full-series cache hit for {series_number} probe={_cache_probe_ms:.0f}ms apply={_apply_ms:.0f}ms")
                    return True
            elif _cache_probe_ms > 50:
                print(f"ًں”چ [CACHE MISS] series={series_number} probe took {_cache_probe_ms:.0f}ms")

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
                    print(f"âڈ³ [LOAD] series={series_key} already loading interactively (thread={threading.current_thread().name})")
                else:
                    self._loading_series_numbers.add(series_key)
                    load_event = threading.Event()
                    self._series_load_events[series_key] = load_event
                    is_owner = True
                    print(f"ًں”‘ [LOAD] series={series_key} took ownership (thread={threading.current_thread().name})")

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
                print(f"âڈ³ [LOAD] series={series_key} interactive wait done {_wait_ms:.0f}ms (thread={threading.current_thread().name})")

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

            # Load full series with correct path (preview path disabled by design)
            # v2.2.3.2.4: Cap ITK threads to 2 for in-process first-series loads.
            # Without this cap SimpleITK spawns N (= cpu_count) internal threads
            # during apply_filters(), each periodically acquiring the GIL.
            # With 8-16 ITK threads + 8 pydicom workers all in the viewer
            # process, the UI/render thread starves for GIL access, producing
            # the 50â€“60 ms scroll stalls seen in Mode B.  Capping to 2 threads
            # keeps filter throughput high while reducing GIL contention to a
            # level the Qt event loop can absorb without perceptible lag.
            _dicom_t = time.perf_counter()
            result = load_single_series_by_number(
                study_path=study_path,  # Pass correct study path, not series path
                series_number=series_number,
                patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
                max_itk_threads=2,
                max_pydicom_workers=2,
                viewer_backend=viewer_backend,
                allow_lazy_backend=(viewer_backend != BACKEND_VTK),
            )
            _dicom_ms = (time.perf_counter() - _dicom_t) * 1000
            print(f"ًں“ٹ [LOAD] DICOM+ITK for series={series_number} took {_dicom_ms:.0f}ms files~={estimated_file_count} (thread={threading.current_thread().name})")
            self.logger.info(
                "viewer-data stage=itk_pipeline_total duration_ms=%.2f files=%d",
                _dicom_ms,
                estimated_file_count,
                extra={"component": "viewer", "function": "ViewerController._load_single_series_on_demand", "stage": "itk_pipeline"},
            )

            if result is None:
                print(f"â‌Œ [LOAD FAIL] series={series_number} loader returned None")
                with self._series_load_lock:
                    evt = self._series_load_events.pop(series_key, None)
                    self._loading_series_numbers.discard(series_key)
                if evt is not None:
                    evt.set()
                return False

            # Process results; generator may be empty on path miss.
            loaded_any = False
            for item in result:
                if not self._tab_active:
                    print(f"âڈ­ï¸ڈ [LOAD SKIP] tab inactive during apply for series {series_number}")
                    return False
                if target_vtk_widget is not None and not self._is_request_current(target_vtk_widget, expected_token):
                    print(f"âڈ­ï¸ڈ [LOAD STALE] full series={series_number} ignored")
                    return False
                vtk_image_data, metadata, (patient_pk, study_pk) = item
                self._apply_loaded_series_data_threadsafe(
                    series_number, vtk_image_data, metadata, patient_pk, study_pk,
                    refresh_viewer=(target_vtk_widget is not None),
                    target_viewer_id=getattr(target_vtk_widget, 'id_vtk_widget', None),
                    allow_paired=allow_paired,
                    expected_token=expected_token,
                )
                loaded_any = True

            if not loaded_any:
                print(f"â‌Œ [LOAD FAIL] series={series_number} loader produced no items")
                with self._series_load_lock:
                    evt = self._series_load_events.pop(series_key, None)
                    self._loading_series_numbers.discard(series_key)
                if evt is not None:
                    evt.set()
                return False

            _elapsed = time.perf_counter() - _start
            print(f"âœ… [LOAD] Series {series_number} loaded in {_elapsed:.3f}s")
            log_stage_timing(
                self.logger,
                component="viewer",
                function="ViewerController._load_single_series_on_demand",
                stage="load_single_series_total",
                start_ms=t_load_total,
                series=str(series_number),
            )
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
            print(f"â‌Œ [LOAD] Error loading series {series_number}: {e}")
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
            print(f"ًں”„ [APPLY] series={series_number} refresh={refresh_viewer} dims={dims}")

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
                    print(f"âڈ­ï¸ڈ [APPLY STALE] series={series_number} token no longer current, skipping mutation")
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
            series_idx = self.parent_widget.replace_series_data(
                series_number=series_number,
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                file_path=file_path,
                allow_append_if_missing=bool(refresh_viewer),
            )
            print(f"ًں”„ [APPLY] series={series_number} â†’ replace_series_data returned idx={series_idx}")

            # Update study path if needed
            if metadata.get('series', {}).get('series_path'):
                correct_path = Path(metadata['series']['series_path']).parent
                if str(correct_path) != self.parent_widget.import_folder_path:
                    self.parent_widget.import_folder_path = str(correct_path)
                    print(f"   ًں”„ Updated study path to: {correct_path}")

            if refresh_viewer and series_idx >= 0:
                # Update ALL viewers currently showing this series (not just selected)
                for vi, node_viewer in enumerate(self.lst_nodes_viewer or []):
                    vtk_w = getattr(node_viewer, 'vtk_widget', None)
                    if vtk_w is None:
                        continue
                    if target_viewer_id is not None and getattr(vtk_w, 'id_vtk_widget', None) != target_viewer_id:
                        continue
                    if expected_token is not None and not self._is_request_current(vtk_w, expected_token):
                        print(f"   âڈ­ï¸ڈ [APPLY STALE] viewer[{vi}] series={series_number} skipped")
                        continue
                    # last_series_show stores thumbnail *index*, not series number
                    current_idx = getattr(vtk_w, 'last_series_show', None)
                    print(f"   ًں”ژ viewer[{vi}] last_series_show={current_idx} vs series_idx={series_idx}")
                    if current_idx is not None and current_idx == series_idx:
                        try:
                            slider = getattr(node_viewer, 'slider', None)
                            print(f"   âœ… Refreshing viewer[{vi}] with full data (dims={dims})")
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
                print(f"âڑ ï¸ڈ [UI APPLY] error: {e}")

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
                print(f"â„¹ï¸ڈ [ZetaBoost][INTERACTIVE_BUSY] busy={new_state} reason={reason}")
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

    # â”€â”€ Per-series download warmup (controlled Mode B caching) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _enqueue_download_warmup(self, series_number: str):
        """Queue a completed series for background warmup during active download.

        v2.2.3.2.3: Routes to subprocess (GIL-free) by default.
        Set AIPACS_DL_WARMUP_SUBPROCESS=0 to fall back to in-process thread.

        Strict controls:
        - Max ``_DL_WARMUP_MAX_CACHED`` series cached during a single download session.
        - Skips large series (> ``_DL_WARMUP_MAX_SLICES``).
        - Skips already-cached series.
        """
        try:
            if self._zeta_slice_focus_mode:
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
                    print(f"[DL_WARMUP] Skip series={sn} - max cached ({self._DL_WARMUP_MAX_CACHED}) reached")
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
            print(f"[DL_WARMUP] Queued series={sn} (pending={len(self._dl_warmup_queue)})")
            if self._dl_warmup_thread is None or not self._dl_warmup_thread.is_alive():
                self._dl_warmup_stop.clear()
                self._dl_warmup_thread = threading.Thread(
                    target=self._dl_warmup_worker,
                    daemon=True,
                    name="DL-Warmup-Worker",
                )
                self._dl_warmup_thread.start()
        except Exception as e:
            print(f"[DL_WARMUP] enqueue error: {e}")

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
                print(f"[DL_WARMUP_SUB] series={sn} too large ({dcm_count} > {self._DL_WARMUP_MAX_SLICES}), skip")
                return False

            study_path = self._get_correct_study_path()
            if not study_path:
                print(f"[DL_WARMUP_SUB] series={sn} no study_path, skip")
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
                print(f"[DL_WARMUP_SUB] Submitted series={sn} to subprocess (pending={self._warmup_subprocess_mgr.pending_count})")
                return True
            else:
                print(f"[DL_WARMUP_SUB] series={sn} submit skipped (dup or full)")
                return False
        except Exception as e:
            print(f"[DL_WARMUP_SUB] enqueue error: {e}")
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
                print(f"[DL_WARMUP_SUB] âœ— series={sn} failed: {result.error} ({result.elapsed_ms:.0f}ms)")
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
                    print(f"[DL_WARMUP_SUB] âœ— series={sn} VTK reconstruction failed")
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
                print(f"[DL_WARMUP_SUB] âœ— series={sn} cache error: {e}")

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

        print(f"[DL_WARMUP] Worker started (max={self._DL_WARMUP_MAX_CACHED}, max_slices={self._DL_WARMUP_MAX_SLICES}, delay={self._DL_WARMUP_INTER_DELAY}s)")

        while not self._dl_warmup_stop.is_set():
            # â”€â”€ Dequeue next series â”€â”€
            with self._dl_warmup_lock:
                if not self._dl_warmup_queue:
                    break
                if self._dl_warmup_cached_count >= self._DL_WARMUP_MAX_CACHED:
                    print(f"[DL_WARMUP] Max cached reached ({self._DL_WARMUP_MAX_CACHED}), stopping")
                    break
                sn = self._dl_warmup_queue.popleft()

            # Skip if tab went inactive.
            if not self._tab_active:
                print(f"[DL_WARMUP] Tab inactive, stopping")
                break

            # Skip if already cached.
            if self.zeta_boost.has_in_memory(sn):
                print(f"[DL_WARMUP] series={sn} already in memory, skip")
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
                print(f"[DL_WARMUP] series={sn} no image count available, skip")
                continue
            if dcm_count > self._DL_WARMUP_MAX_SLICES:
                print(f"[DL_WARMUP] series={sn} too large ({dcm_count} slices > {self._DL_WARMUP_MAX_SLICES}), skip")
                continue

            # Resolve study_path if not yet set (needed for load)
            if not study_path:
                try:
                    study_path = self._get_correct_study_path()
                except Exception:
                    pass
            if not study_path:
                print(f"[DL_WARMUP] series={sn} no study_path, skip")
                continue

            # â”€â”€ Load series (DICOM + ITK filter + VTK conversion) â”€â”€
            _desc_tag = f" [{_series_modality}] {_series_desc}" if _series_desc else ""
            print(f"[DL_WARMUP] Loading series={sn} ({dcm_count} slices){_desc_tag}...")
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
                    print(f"[DL_WARMUP] âœ“ Cached series={sn} in {_elapsed:.0f}ms (count={self._dl_warmup_cached_count}/{self._DL_WARMUP_MAX_CACHED})")
                else:
                    print(f"[DL_WARMUP] series={sn} load returned no data ({_elapsed:.0f}ms)")
            except Exception as e:
                print(f"[DL_WARMUP] Error loading series={sn}: {e}")

            # â”€â”€ Generous inter-series delay (avoid CPU contention) â”€â”€
            for _ in range(int(self._DL_WARMUP_INTER_DELAY * 10)):
                if self._dl_warmup_stop.is_set():
                    break
                time.sleep(0.1)

        print(f"[DL_WARMUP] Worker finished. cached={self._dl_warmup_cached_count}/{self._DL_WARMUP_MAX_CACHED}")

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
                self.zeta_boost.set_study_download_complete(True)
                self.zeta_boost.set_download_active(False)
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
                    print(f"[Pipeline] POST_DOWNLOAD â†’ warmup scheduled (tab active)")
                else:
                    print(f"[Pipeline] POST_DOWNLOAD â†’ warmup deferred (tab inactive â€” starts on next activation)")

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
                    print(f"[Pipeline] DOWNLOADING â†’ engine deactivated (tab inactive, all workers stopped)")
                else:
                    print(f"[Pipeline] DOWNLOADING â†’ warmup blocked, Image Boost active")

            elif new_state == PipelineState.READY:
                print(f"[Pipeline] READY â†’ all series cached")

            elif new_state == PipelineState.IDLE:
                self._stop_download_warmup()
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
            series_uid = None
            if hasattr(self.parent_widget, '_server_series_info') and self.parent_widget._server_series_info:
                series_info = self.parent_widget._server_series_info.get(series_number)
                if isinstance(series_info, dict):
                    series_uid = str(series_info.get('series_uid') or series_info.get('series_instance_uid') or '') or None

            print(f"   ًں“¥ Triggering server download for series {series_number}")

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
            print(f"   âڑ ï¸ڈ Error triggering download: {e}")

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

            # Exit progressive mode for this series (fully downloaded now)
            self.on_series_download_fully_complete(series_number_str)

            # â”€â”€ Dedup guard: prevent multiple concurrent loads of same series â”€â”€
            if series_number_str in getattr(self, '_first_series_loading', set()):
                print(f"âڈ­ï¸ڈ [DEDUP] series={series_number_str} already loading, skip")
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
                                    print(f"ًں“؛ [PREVIEW] displayed for series={series_number_str}")
                                except Exception as e:
                                    print(f"âڑ ï¸ڈ [PREVIEW_APPLY] error: {e}")
                        
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
                            print(f"âœ… Using layout for {modality}: {rows}x{cols}")
                            return (rows, cols)
                    
                    # ط§ع¯ط± ط¯ط± modality_layouts ظ†ط¨ظˆط¯طŒ ظ…ط³طھظ‚غŒظ… ط¯ط± root ط¬ط³طھط¬ظˆ ظ…غŒâ€Œع©ظ†غŒظ… (ط¨ط±ط§غŒ ط³ط§ط²ع¯ط§ط±غŒ ط¨ط§ ظپط§غŒظ„â€Œظ‡ط§غŒ ظ‚ط¯غŒظ…غŒ)
                    if modality in data:
                        mod_cfg = data[modality]
                        if isinstance(mod_cfg, dict):
                            rows = int(mod_cfg.get('rows', 1))
                            cols = int(mod_cfg.get('cols', 2))
                            print(f"âœ… Using layout for {modality} (legacy): {rows}x{cols}")
                            return (rows, cols)
                
                # 2. ط§ع¯ط± ظ…ظˆط¯ط§ظ„غŒطھغŒ ظ¾غŒط¯ط§ ظ†ط´ط¯ غŒط§ ظ…ط´ط®طµ ظ†ط´ط¯ظ‡طŒ ط§ط² default ط§ط³طھظپط§ط¯ظ‡ ظ…غŒâ€Œع©ظ†غŒظ…
                default_cfg = data.get('default') or data.get('DEFAULT')
                if isinstance(default_cfg, dict):
                    rows = int(default_cfg.get('rows', 1))
                    cols = int(default_cfg.get('cols', 2))
                    print(f"â„¹ï¸ڈ Using default layout: {rows}x{cols}")
                    return (rows, cols)
                    
        except Exception as e:
            print(f"âڑ ï¸ڈ Error reading grid config: {e}")
        
        # 3. ط§ع¯ط± ظ‡ظ…ظ‡ ع†غŒط² ظ†ط§ظ…ظˆظپظ‚ ط¨ظˆط¯طŒ ط§ط² fallback ط§ط³طھظپط§ط¯ظ‡ ظ…غŒâ€Œع©ظ†غŒظ…
        print("â„¹ï¸ڈ Using fallback layout: 1x2")
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
            print(f"â‌Œ Error applying viewer layout sync: {e}")
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
            print(f"ًںژ¯ load_first_series_only called: series {series_number}")

            # Update folder path if needed
            if folder_path and folder_path != self.parent_widget.import_folder_path:
                self.parent_widget.import_folder_path = folder_path

            # Check if we already have this series loaded
            series_key = f"series_{series_number}"
            if series_key in self.parent_widget.lst_series_name:
                print(f"âڈ­ï¸ڈ Series {series_number} already loaded")
                return

            # Load the series
            try:
                success = self._load_single_series_on_demand(int(series_number))

                # Warmup worker currently owns the lock â€” retry via QTimer.
                if not success and str(int(series_number)) in self._loading_series_numbers:
                    print(f"ًں”پ [FIRST-SERIES] Series {series_number} being cached by warmup â€” retrying in 250 ms")
                    QTimer.singleShot(250, lambda fp=folder_path, sn=series_number: self.load_first_series_only(fp, sn))
                    return

                if success:
                    self.parent_widget.lst_series_name.add(series_key)
                    print(f"âœ… Series {series_number} loaded successfully")

                    # Display in viewer if it's the first series
                    if len(self.parent_widget.lst_series_name) == 1:
                        self._display_first_series_in_viewer()

                        # Hide any loading spinner
                        self._hide_loading_spinner()
                else:
                    print(f"âڑ ï¸ڈ Failed to load series {series_number}")

            except Exception as load_error:
                print(f"â‌Œ Error loading series {series_number}: {load_error}")

        except Exception as e:
            print(f"â‌Œ Error in load_first_series_only: {e}")
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
            print(f"ًں“¥ [PRIORITY LOAD] Loading series {series_number} (auto-display)")
            print(f"ًں“پ Directory: {series_dir}")
            print(f"{'='*80}")

            # Check DICOM files
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            if not dicom_files:
                print(f"â‌Œ No DICOM files found in {series_dir}")
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
                print(f"âڈ­ï¸ڈ Series {series_number} already loaded")
                return

            # âœ… FIX: Handle both series numbers and Series Instance UIDs
            try:
                series_int = int(series_number)
            except ValueError:
                # Not a simple number - extract series number from directory name
                # Directory name should be the actual series number
                try:
                    series_int = int(series_path.name)
                    print(f"   ًں”چ Extracted series number {series_int} from directory name")
                except ValueError:
                    print(f"â‌Œ Cannot determine series number from UID {series_number} or directory {series_path.name}")
                    return

            # Load the series
            success = self._load_single_series_on_demand(series_int)
            if not success:
                # Warmup worker currently owns the load lock for this series.
                # Retry in 250 ms so the main thread is never blocked.
                if str(series_int) in self._loading_series_numbers:
                    print(f"ًں”پ [PRIORITY LOAD] Series {series_int} being cached by warmup â€” retrying in 250 ms")
                    QTimer.singleShot(250, lambda sn=series_number, sd=series_dir: self.load_series_immediately(sn, sd))
                    return
                print(f"â‌Œ Failed to load series {series_int}")
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

            print(f"âœ… Series {series_int} loaded and displayed.")
        except Exception as e:
            print(f"â‌Œ CRITICAL ERROR in load_series_immediately: {e}")
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
            print(f"âڑ ï¸ڈ Error triggering priority display: {e}")

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
            print(f"â‌Œ [DISTRIBUTE] Error distributing series to viewers: {e}")
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

        print(f"   âœ… Viewer {viewer_idx} populated successfully")


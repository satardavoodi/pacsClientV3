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
from modules.viewer.pipeline import (
    PipelineOrchestrator, PipelineState, LoadCoordinator, PreviewEngine,
)
from modules.viewer.fast.ui_throttle import (
    set_active_orchestrator as _set_active_orchestrator,
    clear_active_orchestrator as _clear_active_orchestrator,
    emit_live_block_telemetry as _emit_live_block_telemetry,
    get_live_block_telemetry_snapshot as _get_live_block_telemetry_snapshot,
)
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, CallerTypes
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget, grow_vtk_inplace
from modules.viewer.widgets import ViewportSpinner
from modules.zeta_sync import (
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
from modules.download_manager.core.enums import DownloadPriority
from PacsClient.utils.config import SOCKET_CONFIG_PATH
from modules.zeta_boost import ZetaBoostEngine, ImageSliceBooster
from modules.zeta_boost.warmup_subprocess import (
    WarmupSubprocessManager, WarmupRequest, WarmupResult, result_to_vtk,
)
from modules.viewer.boost_viewer_config import load_boost_viewer_enabled
from modules.viewer.viewer_backend_config import (
    BACKEND_VTK,
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.fast.lazy_volume_registry import get_loader as get_lazy_loader
from PacsClient.utils.diagnostic_logging import new_correlation_id, set_log_context, now_ms, log_stage_timing

# ── Mixin modules (split from this file in v2.2.9.0) ──────────────────────────
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive import _VCProgressiveMixin
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_cache import _VCCacheMixin
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_backend import _VCBackendMixin
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_layout import _VCLayoutMixin
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_switch import _VCSwitchMixin
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_warmup import _VCWarmupMixin
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_load import _VCLoadMixin
import logging as _logging

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))

# SliceTickSlider extracted to _slice_tick_slider.py (v2.2.9.0) to avoid
# circular imports between the hub and _vc_layout.py.
from PacsClient.pacs.patient_tab.ui.patient_ui._slice_tick_slider import SliceTickSlider  # noqa: E402

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


class ViewerController(
    _VCProgressiveMixin,
    _VCCacheMixin,
    _VCBackendMixin,
    _VCLayoutMixin,
    _VCSwitchMixin,
    _VCWarmupMixin,
    _VCLoadMixin,
):
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
        # 1s TTL disk file-count cache (series_number -> (count, monotonic_ts))
        # Must exist from init because progressive completion paths may invalidate
        # it before any call to _count_series_files_on_disk() lazily creates it.
        self._disk_count_cache = {}
        
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

        # Theme subscription — re-style all viewport containers when the
        # workstation theme switches mid-session. Without this, viewports
        # created under one theme keep their original accent border even
        # after the user picks a different theme.
        # NOTE: the `_on_theme_changed_refresh_viewports` method is defined
        # FAR below this __init__ — keep that placement; an earlier attempt
        # at putting it here in the middle of __init__ swallowed every line
        # below it into the method body and broke drag-drop / click-load.
        try:
            from PacsClient.utils.theme_manager import get_theme_manager
            self._theme_manager = get_theme_manager()
            self._theme_manager.themeChanged.connect(self._on_theme_changed_refresh_viewports)
        except Exception as theme_exc:
            self.logger.debug("Theme subscription unavailable: %s", theme_exc)
            self._theme_manager = None

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
        self._interactive_full_load_semaphore = threading.Semaphore(
            max(1, int(os.getenv("AIPACS_INTERACTIVE_FULL_LOADS_MAX", "1") or "1"))
        )
        self._prefetch_max_series = 24

        self._prefetch_delay_ms = 120
        self._interactive_load_in_progress = False
        self._deferred_series_load_on_activation = []

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
        # Phase 4: preview-first is now the default interactive policy for
        # uncached series loads. Keep the env var as an emergency off switch.
        self._interactive_preview_enabled = os.getenv("AIPACS_INTERACTIVE_PREVIEW_ENABLED", "1") == "1"
        # Compatibility note: this env var originally gated whether preview
        # was allowed for a series size. It now caps how many preview slices
        # we read for the first-image path while keeping the legacy name.
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
        _set_active_orchestrator(self.pipeline)
        self._block_diag_enabled = os.getenv("AIPACS_BLOCK_DIAG_ENABLED", "1") == "1"
        self._block_diag_interval_ms = max(
            500,
            int(os.getenv("AIPACS_BLOCK_DIAG_INTERVAL_MS", "2000") or "2000"),
        )
        self._last_block_diag_snapshot = {}
        self._block_diag_timer = QTimer()
        self._block_diag_timer.setInterval(self._block_diag_interval_ms)
        self._block_diag_timer.timeout.connect(self._emit_block_diag_heartbeat)
        if self._block_diag_enabled:
            self._block_diag_timer.start()
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
        # B4.2: disable booster for FAST mode — the pipeline's own
        # pixel_cache + disk_cache + prefetch fully supersede it.
        if self._is_fast_viewer_mode():
            self._image_slice_booster.disabled = True
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
        # H4 hygiene: explicit init so both guards have a known state from __init__
        # rather than lazy-init via getattr(). _progressive_display_done is a
        # lifecycle guard (NOT a permanent cache) — keys are discarded at
        # download-complete (Layer 2b/3/4); see _vc_progressive.py H4 fix.
        self._progressive_display_done: set = set()
        self._progressive_display_inflight: set = set()
        # H6 fix (v2.2.9.3): permanent guard preventing post-completion
        # progressive re-entry.  Keyed by str(series_number), same domain
        # as _progressive_series.  Never cleared within controller lifetime.
        self._series_download_completed: set = set()
        self._progressive_grow_timer = QTimer()
        self._progressive_grow_timer.setSingleShot(True)
        self._progressive_grow_timer_default_interval_ms = 150
        self._progressive_grow_timer.setInterval(self._progressive_grow_timer_default_interval_ms)   # was 500 — tightened for live feel
        self._progressive_grow_timer.timeout.connect(self._flush_progressive_grow)
        self._progressive_grow_batch_size = max(
            5, int(os.getenv("AIPACS_PROGRESSIVE_GROW_BATCH", "10") or "10")
        )
        self._progressive_admit_batch_size_default = 8
        self._progressive_admit_batch_size = max(
            1,
            int(
                os.getenv(
                    "AIPACS_PROGRESSIVE_ADMIT_BATCH",
                    str(self._progressive_admit_batch_size_default),
                )
                or str(self._progressive_admit_batch_size_default)
            ),
        )

        # -- Completion sweep safety-net timer (Layer 4) --
        # Periodically checks all viewers for stale display counts.
        # Only active when downloads triggered progressive display; stops
        # itself when no series are tracked.
        self._completion_sweep_series_set: set = set()   # series still to verify
        self._completion_sweep_timer = QTimer()
        self._completion_sweep_timer.setInterval(3000)   # 3 seconds
        self._completion_sweep_timer.timeout.connect(self._completion_sweep_tick)

    def _on_theme_changed_refresh_viewports(self, _theme: dict = None) -> None:
        """Re-apply each viewport container's stylesheet so its border picks
        up the new theme accent. Called by ThemeManager.themeChanged from
        the subscription wired at the bottom of __init__.

        IMPORTANT: this method MUST live outside __init__ (it was previously
        misplaced inside the constructor body, which swallowed every
        attribute-init line below it into the method and broke drag-drop /
        click-load in the viewer).
        """
        try:
            for node in (self.lst_nodes_viewer or []):
                container = getattr(node, 'widget', None)
                if container is None:
                    continue
                active = bool(container.property("active"))
                # `_viewport_container_styles` is a staticmethod on the
                # _VCLayoutMixin (which this class inherits), so calling it
                # via self is fine.
                try:
                    container.setStyleSheet(self._viewport_container_styles(active=active))
                except Exception:
                    pass
        except Exception:
            pass

    def _block_diag_label(self) -> str:
        try:
            study_uid = str(getattr(self.parent_widget, 'study_uid', '') or '')
            patient_pk = str(getattr(self.parent_widget, 'patient_pk', '') or '')
            parts = []
            if study_uid:
                parts.append(f"study={study_uid[:24]}")
            if patient_pk:
                parts.append(f"patient={patient_pk}")
            return ' '.join(parts)
        except Exception:
            return ""

    def _emit_block_diag_heartbeat(self):
        """QTimer wrapper: never let telemetry exceptions escape into Qt."""
        try:
            self._emit_block_diag_heartbeat_impl()
        except Exception:
            self.logger.error("Block telemetry heartbeat failed", exc_info=True)

    def _emit_block_diag_heartbeat_impl(self):
        snapshot = _get_live_block_telemetry_snapshot(label=self._block_diag_label())
        self._last_block_diag_snapshot = snapshot
        if self._block_diag_enabled:
            _emit_live_block_telemetry(
                self.logger,
                label=self._block_diag_label(),
                snapshot=snapshot,
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
            # A per-widget viewer_backend_override (e.g. Eagle Eye, which
            # forces VTK/Advanced) takes precedence over the global setting,
            # keeping this Fast gate consistent with _get_requested_viewer_backend().
            override = str(getattr(self.parent_widget, "viewer_backend_override", "") or "").strip()
            if override:
                return override in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT)
            return load_viewer_backend() in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT)
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


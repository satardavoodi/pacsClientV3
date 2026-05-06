"""
Download Manager Widget - Main UI component

Modern, polished download manager interface with:
- Priority-grouped queue display
- Real-time progress tracking
- Smooth animations
- Clean, professional aesthetic
"""

import logging
import re
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QSplitter, QFrame, QHeaderView, QAbstractItemView,
    QGroupBox, QScrollArea, QProgressBar, QComboBox, QTextEdit
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
import threading
import qtawesome as qta

from ...core.models import DownloadTask, DownloadState
from ...core.enums import DownloadPriority, DownloadStatus
from ...state.state_store import DownloadStateStore, get_state_store
from ...state.observers import UIObserver
from ...rules.rule_engine import DownloadRuleEngine
from ...download.executor import DownloadExecutor
from ...network.grpc_client import GrpcMetadataClient
from modules.ai_imaging.ai_module_ui.service_tab.reception_data_service import ReceptionDataService
from ...network.socket_client import SocketDicomClient
from ...storage.database_manager import DatabaseManager
from ...workers.worker_pool import WorkerPool
from ...workers.download_process_worker import DownloadProcessWorker as DownloadWorker
from ...coordinator import SeriesIntentCoordinator
from ..styles.theme import ModernTheme, get_current_theme
from ..styles.colors import ColorPalette
from ..components.priority_group import PriorityGroupHeader
from ..components.status_badge import StatusBadge
from PacsClient.utils.diagnostic_logging import now_ms
from PacsClient.utils.theme_manager import get_theme_manager

logger = logging.getLogger(__name__)


def _dm_theme_color_map(theme: Dict[str, str]) -> Dict[str, str]:
    """Map legacy hardcoded Download Manager colors to semantic theme colors."""
    return {
        "#0f1419": theme.get("panel_deep_bg", "#0f1419"),
        "#111827": theme.get("panel_deep_bg", "#111827"),
        "#1a202c": theme.get("panel_deep_bg", "#1a202c"),
        "#0f172a": theme.get("panel_deep_bg", "#0f172a"),
        "#1e293b": theme.get("menu_bg", "#1e293b"),
        "#1f2937": theme.get("panel_bg", "#1f2937"),
        "#2d3748": theme.get("panel_alt_bg", "#2d3748"),
        "#374151": theme.get("border", "#374151"),
        "#4a5568": theme.get("border", "#4a5568"),
        "#4b5563": theme.get("border", "#4b5563"),
        "#f7fafc": theme.get("text_primary", "#f7fafc"),
        "#e2e8f0": theme.get("text_primary", "#e2e8f0"),
        "#cbd5e1": theme.get("text_secondary", "#cbd5e1"),
        "#94a3b8": theme.get("text_secondary", "#94a3b8"),
        "#a0aec0": theme.get("text_muted", "#a0aec0"),
        "#64748b": theme.get("text_muted", "#64748b"),
        "#06b6d4": theme.get("info", "#06b6d4"),
        "#0891b2": theme.get("info_hover", "#0891b2"),
        "#3182ce": theme.get("accent", "#3182ce"),
    }


def _dm_retint_stylesheet(css: str, theme: Dict[str, str]) -> str:
    """Replace legacy hardcoded hex colors in a CSS string with theme values."""
    out = css
    for old, new in _dm_theme_color_map(theme).items():
        out = re.sub(re.escape(old), new, out, flags=re.IGNORECASE)
    return out


def _dm_retint_widget_tree(root: QWidget, theme: Dict[str, str]) -> None:
    """Walk a widget tree and replace legacy colors in all stylesheets."""
    if root is None:
        return
    own = root.styleSheet()
    if own:
        root.setStyleSheet(_dm_retint_stylesheet(own, theme))
    for widget in root.findChildren(QWidget):
        ss = widget.styleSheet()
        if ss:
            widget.setStyleSheet(_dm_retint_stylesheet(ss, theme))

# ── Mixin imports ──
from ._dm_ui_setup import _DMUISetupMixin
from ._dm_queue import _DMQueueMixin
from ._dm_controls import _DMControlsMixin
from ._dm_workers import _DMWorkersMixin
from ._dm_retry import _DMRetryMixin
from ._dm_details import _DMDetailsMixin
from ._dm_priority import _DMPriorityMixin
from ._dm_reception import _DMReceptionMixin
from ._dm_theming import _DMThemingMixin


class DownloadManagerWidget(_DMUISetupMixin, _DMQueueMixin, _DMControlsMixin, _DMWorkersMixin, _DMRetryMixin, _DMDetailsMixin, _DMPriorityMixin, _DMReceptionMixin, _DMThemingMixin, QWidget):
    """
    Main Download Manager Widget
    
    Features:
    - Priority-grouped queue display (R16, R18)
    - Real-time progress updates
    - Modern, polished UI
    - Responsive layout
    - Smooth animations
    
    Signals:
        download_completed: (study_uid)
        download_failed: (study_uid, error_message)
        priority_changed: (study_uid, new_priority)
    """
    
    # Signals
    download_completed = Signal(str)
    download_failed = Signal(str, str)
    priority_changed = Signal(str, int)
    studyProgressUpdated = Signal(str, int, int, float)  # study_uid, downloaded, total, percent
    seriesDownloadStarted = Signal(str, str, str)  # study_uid, series_uid, series_desc
    seriesProgressUpdated = Signal(str, str, int, int)  # study_uid, series_uid, downloaded, total
    seriesDownloadCompleted = Signal(str, str)  # study_uid, series_uid
    # F3.5.3 — emitted on Qt main thread when a priority-handoff retry chain
    # exhausts. Args: (study_uid, series_number, reason). UI can connect to
    # show a "stalled" indicator with click-to-retry. Always emitted unless
    # the env-gated DM observer is fully disabled (default-on).
    priorityHandoffFailed = Signal(str, str, str)

    def __init__(self, base_output_dir: Path, parent=None):
        """
        Initialize download manager widget
        
        Args:
            base_output_dir: Base directory for downloads
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.base_output_dir = Path(base_output_dir)
        
        # Initialize core components
        self.state_store = get_state_store()
        self.database_manager = DatabaseManager()
        
        # Read server host from SocketConfig (same source as socket client)
        from modules.network.socket_config import get_socket_server_settings
        from modules.download_manager.core.constants import DEFAULT_GRPC_PORT
        _srv = get_socket_server_settings()
        _grpc_host = _srv.get("host") or "localhost"
        logger.info("[DM-INIT] gRPC host from SocketConfig: %s:%s", _grpc_host, DEFAULT_GRPC_PORT)
        self.grpc_client = GrpcMetadataClient(
            host=_grpc_host,
            port=DEFAULT_GRPC_PORT,
        )
        self.rule_engine = DownloadRuleEngine(self.state_store, {})
        self.executor = DownloadExecutor(
            state_store=self.state_store,
            rule_engine=self.rule_engine,
            grpc_client=self.grpc_client,
            database_manager=self.database_manager,
            base_output_dir=self.base_output_dir
        )
        self.worker_pool = WorkerPool(
            max_workers=1,
            on_worker_removed=self._on_pool_slot_freed,
        )

        # Task storage - keep original tasks for worker creation
        self._tasks: Dict[str, DownloadTask] = {}  # study_uid -> DownloadTask

        # Additional task information (patient_age, patient_sex, body_part, etc.)
        self._additional_task_info: Dict[str, Dict] = {}  # study_uid -> {additional_info}

        self.intent_coordinator = SeriesIntentCoordinator(
            state_store=self.state_store,
            rule_engine=self.rule_engine,
            worker_pool=self.worker_pool,
            tasks_ref=self._tasks,
            pause_downloads_for_preemption=self._pause_downloads_for_preemption,
            start_download_worker=self._start_download_worker,
            start_next_pending=self._start_next_pending,
            refresh_table_order=self.refresh_table_order,
            check_auto_resume=self._check_auto_resume,
        )
        # F3.5.3 — register priority-handoff failure observer (default-on).
        # Set AIPACS_INTENT_HANDOFF_TOAST_DISABLE=1 to opt out (e.g. for
        # automated tests that want only the coordinator-side signal).
        # Stalled studies are tracked in `_stalled_priority_studies` so the
        # UI layer can inspect or re-render at any time, and a manual retry
        # is exposed via `retry_stalled_priority(study_uid)`.
        self._stalled_priority_studies: Dict[str, Dict[str, str]] = {}
        try:
            import os as _os_f353
            _toast_disabled = _os_f353.environ.get(
                "AIPACS_INTENT_HANDOFF_TOAST_DISABLE", "0"
            ).strip() == "1"
            if not _toast_disabled:
                self.intent_coordinator.register_priority_handoff_failed_callback(
                    self._on_priority_handoff_failed_from_coordinator
                )
                logger.info(
                    "[DM-INIT] Registered F3.5.3 priority-handoff failure observer"
                )
            else:
                logger.info(
                    "[DM-INIT] F3.5.3 priority-handoff failure observer disabled "
                    "via AIPACS_INTENT_HANDOFF_TOAST_DISABLE=1"
                )
        except Exception as exc:
            logger.warning(
                "[DM-INIT] Failed to register F3.5.3 failure observer: %s", exc
            )
        try:
            from modules.viewer.fast.object_cache import set_object_cache
            set_object_cache(self)
            logger.info("[DM-INIT] Registered Download Manager as FAST object cache")
        except Exception as exc:
            logger.debug("[DM-INIT] FAST object cache registration skipped: %s", exc)
        
        # Register UI observer
        ui_observer = UIObserver(self)
        self.state_store.register_observer(ui_observer)
        self._ui_observer = ui_observer
        
        # Theme
        self.theme = get_current_theme()
        
        # UI elements
        self.download_table = None
        self.status_label = None
        self.status_summary = None
        self.download_rows: Dict[str, int] = {}  # study_uid -> table row index
        self._speed_label_widgets: Dict[str, QLabel] = {}  # study_uid -> speed QLabel widget in table

        # Cache series image counts for fast overall progress calculations
        self._series_image_count_cache: Dict[str, Dict[str, int]] = {}
        
        # Priority grouping UI tracking
        self._priority_group_widgets = {}  # priority_name -> PriorityGroupHeader
        self._priority_group_rows = {}  # priority_name -> table row index
        self._collapsed_groups = set()  # Set of collapsed priority names
        self._show_empty_groups = True  # Whether to show empty priority groups
        
        # Details panel widgets
        self.patient_name_label = None
        self.patient_id_label = None
        self.patient_identifier_label = None
        self.requesting_physician_label = None
        self.reception_status_label = None
        self.url_label = None
        self.study_date_label = None
        self.modality_label = None
        self.study_desc_label = None
        self.size_label = None
        self.progress_bar = None
        self.progress_label = None
        self.speed_label = None
        self.eta_label = None
        self.series_container = None
        self.series_layout = None
        self.attachments_list = None
        self.log_text = None
        self.priority_combo = None
        self.start_btn = None
        self.pause_btn = None
        self.cancel_btn = None
        self.retry_btn = None
        
        # Currently selected download
        self._selected_study_uid = None
        self._suppressing_selection_signals = False

        # Reception data service/cache
        self._reception_service = ReceptionDataService()
        self._reception_service.data_received.connect(self._on_reception_data_received)
        self._reception_service.error_occurred.connect(self._on_reception_data_error)
        self._reception_cache: Dict[str, Dict] = {}
        
        # FIX: Use dictionary to track multiple concurrent reception data requests
        # Key: patient_id, Value: study_uid (to know which study requested this data)
        self._pending_reception_requests: Dict[str, str] = {}
        self._last_reception_patient_id: Optional[str] = None

        # Series progress tracking for signal emission
        self._last_series_number_by_study: Dict[str, str] = {}
        self._completed_series_emitted: Dict[str, set] = {}
        
        # Setup UI
        self._setup_ui()
        
        # Theme integration — retint after UI is built
        self._app_theme_manager = get_theme_manager()
        self._app_theme = self._app_theme_manager.current_theme()
        _dm_retint_widget_tree(self, self._app_theme)
        self._app_theme_manager.themeChanged.connect(self._on_app_theme_changed)
        
        # Initial table refresh to show empty priority groups
        QTimer.singleShot(100, self.refresh_table_order)
        
        # Pipeline health check timer - ensures queue never gets stuck
        # This is a backup mechanism that runs periodically to ensure forward progress
        self._health_check_timer = QTimer(self)
        self._health_check_timer.timeout.connect(self._pipeline_health_check)
        self._health_check_timer.start(5000)  # Check every 5 seconds
        
        # CRITICAL FIX: Progress throttle timer - prevents event loop flooding
        # Problem: Every downloaded image triggers _on_worker_progress()
        # Solution: Batch progress updates every 100ms instead of per-image
        # Result: 100x reduction in state updates (1000+ → ~10 per download)
        self._progress_throttle_timer = QTimer(self)
        self._progress_throttle_timer.timeout.connect(self._apply_throttled_progress)
        self._progress_throttle_timer.setInterval(100)  # Batch every 100ms
        
        # Store pending progress updates to batch them
        self._pending_progress: Dict[str, Dict] = {}
        self._cleaned_up = False
        
        # Speed update timer - updates speed and ETA labels every second
        self._speed_update_timer = QTimer(self)
        self._speed_update_timer.timeout.connect(self._update_speed_display)
        self._speed_update_timer.setInterval(1000)  # Update every 1 second
        self._speed_update_timer.start()
        
        logger.info("✅ DownloadManagerWidget initialized (v1.0.6 UI style)")
        logger.info("=" * 80)

    # ────────────────────────────────────────────────────────────────────
    # F3.5.3 — Priority-handoff failure UX guardrail
    # ────────────────────────────────────────────────────────────────────
    def _on_priority_handoff_failed_from_coordinator(
        self, study_uid: str, series_number: str, reason: str
    ) -> None:
        """Coordinator → DM observer entry point.

        Invoked from the coordinator's emit helper. May be called from any
        thread (the coordinator is plain Python and runs on whatever thread
        triggered the timer fallback). Marshal to the Qt main thread before
        emitting the widget-level signal.
        """
        try:
            QTimer.singleShot(
                0,
                lambda u=str(study_uid), s=str(series_number or ""), r=str(reason): (
                    self._handle_priority_handoff_failed_on_main(u, s, r)
                ),
            )
        except Exception:
            logger.exception(
                "[DM] Failed to marshal priority_handoff_failed to main thread"
            )

    def _handle_priority_handoff_failed_on_main(
        self, study_uid: str, series_number: str, reason: str
    ) -> None:
        """Main-thread handler for priority-handoff failure.

        Records the stalled study so the UI can render a "stalled — click to
        retry" indicator and emits ``priorityHandoffFailed`` for external
        observers (e.g. ViewerController passive logger).
        """
        try:
            self._stalled_priority_studies[str(study_uid)] = {
                "series_number": str(series_number or ""),
                "reason": str(reason or ""),
            }
        except Exception:
            pass
        try:
            self.priorityHandoffFailed.emit(
                str(study_uid), str(series_number or ""), str(reason or "")
            )
        except Exception:
            logger.exception(
                "[DM] priorityHandoffFailed signal emit failed for %s",
                study_uid,
            )
        logger.warning(
            "[DM] Priority handoff stalled for study=%s series=%s reason=%s",
            study_uid[:40] if study_uid else "",
            series_number,
            reason,
        )

    def retry_stalled_priority(self, study_uid: str) -> bool:
        """Manual retry of a stalled priority handoff (e.g. from a UI click).

        F3.5.3 contract:
        - Forces the V2 wall-clock retry path even when
          ``AIPACS_INTENT_HANDOFF_V2`` is unset/0, by calling the V2 entry
          point directly.
        - Bypasses the per-series viewer-notify cooldown — this is a manual
          user action, not an automatic drag-drop notification.
        - Clears the stalled-study record on successful chain start.
        """
        uid = str(study_uid or "").strip()
        if not uid:
            return False
        record = self._stalled_priority_studies.pop(uid, None)
        try:
            self.intent_coordinator._schedule_priority_start_retry_v2(uid)
        except Exception:
            logger.exception("[DM] retry_stalled_priority failed for %s", uid)
            # Restore record so user can retry again.
            if record is not None:
                self._stalled_priority_studies[uid] = record
            return False
        logger.info(
            "[DM] retry_stalled_priority dispatched V2 retry for study=%s",
            uid[:40],
        )
        return True

    def cleanup(self) -> None:
        """Release timers, observers, network clients, and active workers."""
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True

        for timer_name in (
            "_health_check_timer",
            "_progress_throttle_timer",
            "_speed_update_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is None:
                continue
            try:
                timer.stop()
            except Exception:
                pass

        try:
            self._pending_progress.clear()
        except Exception:
            pass

        try:
            self.worker_pool.stop_all()
        except Exception:
            logger.exception("[DM] Failed to stop worker pool during cleanup")

        try:
            ui_observer = getattr(self, "_ui_observer", None)
            if ui_observer is not None:
                self.state_store.unregister_observer(ui_observer)
        except Exception:
            logger.exception("[DM] Failed to unregister UI observer during cleanup")

        # F3.5.3 — unregister priority-handoff failure observer.
        try:
            coord = getattr(self, "intent_coordinator", None)
            if coord is not None:
                coord.unregister_priority_handoff_failed_callback(
                    self._on_priority_handoff_failed_from_coordinator
                )
        except Exception:
            logger.exception(
                "[DM] Failed to unregister F3.5.3 failure observer during cleanup"
            )

        try:
            self.grpc_client.close()
        except Exception:
            logger.exception("[DM] Failed to close gRPC client during cleanup")

        try:
            self._app_theme_manager.themeChanged.disconnect(self._on_app_theme_changed)
        except Exception:
            pass

        logger.info("[DM] DownloadManagerWidget cleanup complete")

    def closeEvent(self, event):
        try:
            self.cleanup()
        finally:
            super().closeEvent(event)

    def study_downloads(self):
        """Compatibility for legacy callers expecting a study_downloads list."""
        try:
            states = self.state_store.get_all()
        except Exception:
            return []

        return [
            SimpleNamespace(study_uid=state.study_uid, status=state.status.value)
            for state in states
        ]
        logger.info("🎯 ZETA DOWNLOAD MANAGER WITH V1.0.6 UI - VERIFIED LOADED")
        logger.info(f"   Has toolbar: {hasattr(self, 'start_all_btn')}")
        logger.info(f"   Has details panel: {hasattr(self, 'patient_name_label')}")
        logger.info(f"   Has priority grouping: {hasattr(self, '_priority_group_widgets')}")
        logger.info(f"   Has task storage: {hasattr(self, '_tasks')}")
        
        # Log information about loaded studies at initialization
        if hasattr(self, '_tasks') and self._tasks:
            logger.info(f"📊 [INITIAL_STUDIES] Studies loaded at initialization: {len(self._tasks)}")
            for idx, (study_uid, task) in enumerate(self._tasks.items()):
                logger.info(f"📊 [INITIAL_STUDIES] Study {idx+1}: {task.patient_name} (UID: {study_uid[:20]}...)")
        else:
            logger.info("📊 [INITIAL_STUDIES] No studies loaded at initialization")
        
        logger.info("=" * 80)


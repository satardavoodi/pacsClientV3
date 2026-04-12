"""
Download orchestration service for the Home panel.

Encapsulates the wiring between the Zeta Download Manager, series info
fetching, and the patient viewer widget.  This removes ~500 lines of
interleaved download + UI logic from HomePanelWidget.

Pattern: Service Layer
  HomePanelWidget (UI)  →  HomeDownloadService (orchestration)
                        →  DownloadManagerWidget (engine)
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QTabWidget

from PacsClient.utils.config import SOURCE_PATH
from modules.download_manager.ui.main_widget import DownloadManagerWidget

_logger = logging.getLogger(__name__)


class HomeDownloadService:
    """Orchestrates download-manager lifecycle and study download flow.

    Parameters
    ----------
    tab_widget : QTabWidget
        The main application tab bar (for DM tab creation).
    custom_tab_manager : object | None
        Optional custom tab manager for title-bar integration.
    """

    def __init__(self, tab_widget: QTabWidget, custom_tab_manager=None):
        self.tab_widget = tab_widget
        self.custom_tab_manager = custom_tab_manager
        # Connection key → True  (duplicate-guard)
        self._dm_widget_connections: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Download Manager tab lifecycle
    # ------------------------------------------------------------------

    def get_or_create_dm_tab(self, *, activate: bool = False) -> Optional[DownloadManagerWidget]:
        """Return the existing DM widget or create a new tab.

        This is the single authoritative factory for the Download Manager
        tab – all code paths must go through here.
        """
        try:
            from modules.network.zeta_adapter import get_zeta_download_manager_widget

            # 1. Existing tab
            for i in range(self.tab_widget.count()):
                w = self.tab_widget.widget(i)
                if isinstance(w, DownloadManagerWidget):
                    if activate:
                        self._activate_tab(i)
                    return w

            # 2. Create
            dm = get_zeta_download_manager_widget(base_output_dir=Path(SOURCE_PATH))

            if self.custom_tab_manager:
                self.custom_tab_manager.add_download_manager_tab(
                    widget=dm, activate=activate)
            else:
                self.tab_widget.addTab(dm, "Download Manager")
                if activate:
                    self.tab_widget.setCurrentWidget(dm)
            return dm

        except Exception as exc:
            print(f"[DM] Error creating download manager tab: {exc}")
            import traceback; traceback.print_exc()
            return None

    # ------------------------------------------------------------------
    # Signal wiring: DM ↔ patient widget
    # ------------------------------------------------------------------

    def connect_dm_to_widget(self, dm: DownloadManagerWidget, widget,
                             study_uid: str) -> None:
        """Wire Download Manager progress signals to a patient widget.

        Idempotent – duplicate calls for the same (study, widget) pair are
        no-ops.
        """
        connection_key = f"{study_uid}_{id(widget)}"
        if self._dm_widget_connections.get(connection_key):
            return
        try:
            import weakref

            widget_ref = weakref.ref(widget)
            _pending_completed: list[str] = []
            from PySide6.QtCore import QTimer
            _flush_timer = QTimer()
            _flush_timer.setSingleShot(True)
            _flush_timer.setInterval(100)
            _first_emitted = {"done": False}

            def _resolve_sn(series_uid_or_number):
                sn = str(series_uid_or_number)
                # 1. Quick check: already a known series-number key in thumbnails?
                w = widget_ref()
                if w and hasattr(w, "thumbnail_manager"):
                    tm = w.thumbnail_manager
                    if tm:
                        if sn in tm.series_widgets:
                            return sn
                        # 2. Try UID→number map populated during thumbnail creation
                        mapped = tm._series_uid_to_number.get(sn)
                        if mapped and str(mapped) in tm.series_widgets:
                            return str(mapped)
                # 3. Fallback: resolve via DM task series list (SeriesInfo dataclass)
                try:
                    task = dm._tasks.get(study_uid)
                    if task:
                        for s in getattr(task, 'series_list', []) or []:
                            if str(getattr(s, 'series_uid', '')) == sn:
                                s_num = str(getattr(s, 'series_number', ''))
                                if s_num:
                                    return s_num
                except Exception:
                    pass
                return sn

            def _resolve_series_total(sn_str):
                """Look up DICOM image_count for a series from the DM task."""
                try:
                    task = dm._tasks.get(study_uid)
                    if task:
                        for s in getattr(task, 'series_list', []) or []:
                            if str(getattr(s, 'series_number', '')) == sn_str:
                                return int(getattr(s, 'image_count', 0))
                except Exception:
                    pass
                return 0

            def _emit_final_progress(w, sn_str):
                """Emit series_images_progress(sn, total, total) — completion pulse."""
                if not hasattr(w, "series_images_progress"):
                    return
                total = _resolve_series_total(sn_str)
                if total > 0:
                    try:
                        w.series_images_progress.emit(sn_str, total, total)
                    except Exception:
                        pass

            def _flush():
                batch = list(_pending_completed)
                _pending_completed.clear()
                w = widget_ref()
                if not w:
                    return
                try:
                    _ = w.isVisible()
                except (RuntimeError, AttributeError):
                    return
                for sn in batch:
                    try:
                        if hasattr(w, "thumbnail_manager"):
                            w.thumbnail_manager.complete_series_download(sn)
                        _emit_final_progress(w, sn)
                        if hasattr(w, "series_downloaded"):
                            w.series_downloaded.emit(sn)
                    except (RuntimeError, AttributeError):
                        break
                    except Exception:
                        pass

            _flush_timer.timeout.connect(_flush)

            def on_study_progress(uid, current, total, percent):
                if uid != study_uid:
                    return
                w = widget_ref()
                if w and hasattr(w, "on_study_images_progress"):
                    try:
                        w.on_study_images_progress(current, total)
                    except Exception:
                        pass

            def on_series_started(uid, series_uid, series_desc):
                if uid != study_uid:
                    return
                sn = _resolve_sn(series_uid)
                _t_dl_start = _time.perf_counter()
                _logger.info(
                    "[FAST-SERIES-DOWNLOAD-START] study=%s series=%s desc=%s",
                    uid, sn, series_desc,
                )
                _logger.info(
                    "FAST:download_start study=%s series=%s series_uid=%s t_abs=%.6f"
                    " note=delta_from_series_selected_not_available_here",
                    uid, sn, series_uid, _t_dl_start,
                )
                w = widget_ref()
                if w and hasattr(w, "thumbnail_manager"):
                    try:
                        w.thumbnail_manager.start_series_download(sn)
                    except Exception:
                        pass

            def on_series_progress(uid, series_uid, current, total):
                if uid != study_uid:
                    return
                sn = _resolve_sn(series_uid)
                pct = (current / total * 100) if total > 0 else 0
                _logger.info(
                    "[FAST-SERIES-DOWNLOAD-PROGRESS] study=%s series=%s percent=%.0f images=%d/%d",
                    uid, sn, pct, current, total,
                )
                w = widget_ref()
                if not w:
                    return
                # [H10-3] Canonical DM active series — log on transition only
                _prev_dm = getattr(w, '_h10_dm_active_series', None)
                if _prev_dm != sn:
                    _logger.info(
                        "[H10-3] DM_SERIES_TRANSITION fn=on_series_progress prev=%s new=%s",
                        _prev_dm, sn,
                    )
                    w._h10_dm_active_series = sn
                # Update progressive viewer display via signal (the method
                # lives on viewer_controller, not on PatientWidget directly).
                if hasattr(w, "series_images_progress"):
                    try:
                        w.series_images_progress.emit(sn, int(current), int(total))
                        # [H7-P8-RECV] DM progress signal received and forwarded
                        _pip_st = getattr(getattr(w, 'pipeline', None), 'state', '?')
                        _logger.info(
                            "[H7-P8-RECV] series=%s downloaded=%d total=%d pipeline_state=%s",
                            sn, int(current), int(total),
                            _pip_st.name if hasattr(_pip_st, 'name') else _pip_st,
                        )
                    except Exception:
                        pass
                # Update thumbnail progress overlay (fixes 0% stuck bug)
                if hasattr(w, "thumbnail_manager") and w.thumbnail_manager:
                    try:
                        pct = (current / total * 100) if total > 0 else 0
                        w.thumbnail_manager.update_series_progress(
                            sn, pct, f"{current}/{total}")
                    except Exception:
                        pass

            def on_series_completed(uid, series_uid):
                if uid != study_uid or not widget_ref():
                    return
                sn = _resolve_sn(series_uid)
                _logger.info(
                    "[FAST-SERIES-DOWNLOAD-COMPLETE] study=%s series=%s",
                    uid, sn,
                )
                # [H10-3] Canonical DM active series — log completion transition
                w_c = widget_ref()
                if w_c:
                    _prev_dm = getattr(w_c, '_h10_dm_active_series', None)
                    if _prev_dm != sn:
                        _logger.info(
                            "[H10-3] DM_SERIES_TRANSITION fn=on_series_completed prev=%s new=%s",
                            _prev_dm, sn,
                        )
                    w_c._h10_dm_active_series = sn
                if not _first_emitted["done"]:
                    _first_emitted["done"] = True
                    _flush_timer.stop()
                    _pending_completed.clear()
                    try:
                        w = widget_ref()
                        if w:
                            if hasattr(w, "thumbnail_manager"):
                                w.thumbnail_manager.complete_series_download(sn)
                            _emit_final_progress(w, sn)
                            if hasattr(w, "series_downloaded"):
                                w.series_downloaded.emit(sn)
                    except Exception:
                        pass
                    return
                _pending_completed.append(sn)
                if not _flush_timer.isActive():
                    _flush_timer.start()

            dm.studyProgressUpdated.connect(on_study_progress)
            dm.seriesDownloadStarted.connect(on_series_started)
            dm.seriesProgressUpdated.connect(on_series_progress)
            dm.seriesDownloadCompleted.connect(on_series_completed)

            self._dm_widget_connections[connection_key] = True
            # [H7-P8] DM signal wiring checkpoint
            _has_workers = bool(getattr(dm, '_active_workers', None))
            _logger.info(
                "[H7-P8] study=%s wiring_complete=True dm_has_active_workers=%s "
                "connection_key=%s",
                study_uid, _has_workers, connection_key,
            )
        except Exception as exc:
            print(f"[DM] Error connecting signals: {exc}")

    # ------------------------------------------------------------------
    # Zeta-boost global flag
    # ------------------------------------------------------------------

    @staticmethod
    def refresh_global_download_flag() -> None:
        """Set/clear global download-active flag for ZetaBoost warmup throttle."""
        try:
            from modules.download_manager.state.state_store import get_state_store
            from modules.zeta_boost.engine import set_global_download_active
            active = bool(get_state_store().get_active_downloads())
            set_global_download_active(active)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _activate_tab(self, index: int) -> None:
        if self.custom_tab_manager:
            try:
                self.custom_tab_manager.set_tab_active_simple(index)
                return
            except Exception:
                pass
        self.tab_widget.setCurrentIndex(index)

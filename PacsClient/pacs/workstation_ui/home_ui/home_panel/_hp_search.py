"""Search & table population: local/server search, patient table delegates"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio
import logging
import time
import os
import threading
import traceback

import requests

_logger = logging.getLogger(__name__)

# ── Stage-1 lifecycle SHADOW observer (telemetry only; default OFF via env
#    AIPACS_LIFECYCLE_THUMBS). These calls NEVER raise and NEVER change behavior;
#    they run the canonical PatientLoadModel alongside the legacy path so its
#    correctness can be proven on the source build before any cutover. See
#    docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md §11.
try:
    from PacsClient.utils.lifecycle_shadow import get_lifecycle_shadow as _get_lifecycle_shadow
except Exception:  # pragma: no cover - telemetry import must never break this module
    def _get_lifecycle_shadow():
        return None


def _lc_shadow_note(method, *args, **kwargs):
    """Fire one shadow-observer method, swallowing everything (telemetry only)."""
    try:
        sh = _get_lifecycle_shadow()
        if sh is not None:
            getattr(sh, method)(*args, **kwargs)
    except Exception:
        pass


# ── Seam A CUTOVER (behaviour change; default OFF via AIPACS_LIFECYCLE_THUMBS_ACTIVE).
#    Legacy discards EVERY token-stale right-panel thumbnail result — including a
#    result for a study the user clicked BACK to (A->B->A), the Problem #1 loss.
#    When active, a token-stale result is RENDERED iff it is still the active
#    selection; cross-patient safety is unchanged (the _is_active_patient_selection
#    guard before display is untouched, and the result is re-checked there). Default
#    OFF = byte-identical legacy. NEEDS LIVE SOURCE-BUILD VERIFY before flipping on.
#    See docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md §16.
_LIFECYCLE_THUMBS_ACTIVE = os.getenv(
    "AIPACS_LIFECYCLE_THUMBS_ACTIVE", "1"
).strip().lower() in ("1", "true", "yes", "on")

try:
    from PacsClient.utils.patient_load_lifecycle import (
        resolve_stale_thumbnail_action as _resolve_stale_thumbnail_action,
    )
except Exception:  # pragma: no cover - a failed import must fall back to legacy discard
    def _resolve_stale_thumbnail_action(token_matches, is_active_selection, cutover_enabled):
        return "render" if token_matches else "discard"


# ── Patient image/series count = whole-patient total, applied ONCE (2026-06-17) ──
# The server's per-patient `count_of_instances` / `count_of_series` are WHOLE-PATIENT
# aggregates (see the documented `count_of_series`-is-patient-total caveat). They must
# never be summed once per study row: a multi-study patient (e.g. 46970, 2 studies)
# then shows N x the true total (5042 = 2 x 2521). This is unrelated to AcquisitionNumber.
# When ON (default) the authoritative patient total is used for the table's Images/Series
# columns; a per-study sum is only used when the server omits the patient-level total.
# Set AIPACS_PATIENT_COUNT_AUTHORITATIVE=0 to restore the legacy sum-first behaviour.
_PATIENT_COUNT_AUTHORITATIVE = os.getenv(
    "AIPACS_PATIENT_COUNT_AUTHORITATIVE", "1"
).strip().lower() not in ("0", "false", "no", "off")


def _resolve_patient_table_counts(unique_study_rows, patient, patient_id=None,
                                  total_studies=None, authoritative=None):
    """Resolve the patient-row Series/Images counts WITHOUT multiplying the
    whole-patient total by the number of studies.

    Root cause of the 46970 "Images 5042 = 2 x 2521" regression: each per-study row
    fell back to the PATIENT-level ``count_of_instances`` and the rows were summed,
    so an N-study patient showed N x the true total. (This is unrelated to
    AcquisitionNumber — that was never in any runtime path.)

    Rule (default, ``authoritative``): the server's per-patient ``count_of_instances`` /
    ``count_of_series`` are de-duplicated WHOLE-PATIENT aggregates and are used ONCE.
    A per-study sum is used only when the server omitted the patient-level total
    (rows must already carry study-OWN counts, 0 when unknown — never the patient
    fallback). ``authoritative=False`` restores the legacy sum-first behaviour.
    Returns ``(total_series, total_images)``.
    """
    if authoritative is None:
        authoritative = _PATIENT_COUNT_AUTHORITATIVE

    summed_series = 0
    summed_images = 0
    for row_data in (unique_study_rows or []):
        try:
            summed_series += int(row_data.get('series_count') or 0)
        except Exception:
            pass
        try:
            summed_images += int(row_data.get('images_count') or 0)
        except Exception:
            pass

    patient = patient if isinstance(patient, dict) else {}
    try:
        patient_series_total = int(patient.get('count_of_series') or patient.get('number_of_series') or 0)
    except Exception:
        patient_series_total = 0
    try:
        patient_images_total = int(patient.get('count_of_instances') or patient.get('number_of_instances') or 0)
    except Exception:
        patient_images_total = 0

    if authoritative:
        total_series = patient_series_total if patient_series_total > 0 else summed_series
        total_images = patient_images_total if patient_images_total > 0 else summed_images
    else:
        total_series = summed_series if summed_series > 0 else patient_series_total
        total_images = summed_images if summed_images > 0 else patient_images_total

    # Observe-only: a real per-study sum disagreeing with the patient aggregate
    # distinguishes a genuine SERVER-side double from the client-side per-row
    # fallback bug (now fixed).
    try:
        if summed_images and patient_images_total and summed_images != patient_images_total:
            _logger.info(
                "[PATIENT_IMAGE_COUNT] pid=%s studies=%s patient_total=%s summed=%s used=%s",
                patient_id, total_studies, patient_images_total, summed_images, total_images,
            )
    except Exception:
        pass

    return total_series, total_images

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

import qtawesome as qta

from PacsClient.utils.structured_logging import emit_ui_event, emit_download_event

from ..home_search_service import HomeSearchService
from modules.network.socket_client import PatientListSocketClient
from modules.network.reception_api_config import (
    get_reception_api_base_url, get_reception_api_timeout,
    reception_api_breaker_open, record_reception_api_failure, record_reception_api_success,
)
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from modules.offline_cloud_server.service import export_studies_to_offline_cloud, get_all_offline_cloud_servers, list_offline_cloud_studies, record_offline_cloud_sync_event, sync_offline_cloud_study_preview_to_local, sync_offline_cloud_study_to_local, validate_offline_cloud_package

from .widget import SourceOfPatientLoad

class _HPSearchMixin:
    @staticmethod
    def _is_probable_actor_id(value: str) -> bool:
        text = str(value or '').strip()
        return bool(text) and len(text) == 24 and all(ch in '0123456789abcdefABCDEF' for ch in text)

    @classmethod
    def _has_displayable_reporting_name(cls, value: str) -> bool:
        text = str(value or '').strip()
        if not text:
            return False
        if text.lower() in {'n/a', 'na', 'none', 'null', 'unknown', '-'}:
            return False
        if text.startswith('ID:'):
            return False
        if cls._is_probable_actor_id(text):
            return False
        return True

    """Search & table population: local/server search, patient table delegates"""

    @staticmethod
    def _extract_reporting_physician_name(source: dict) -> str:
        """Extract reporting physician name from mixed payload shapes."""
        if not isinstance(source, dict):
            return ""

        report_obj = source.get('report') if isinstance(source.get('report'), dict) else {}

        value = (
            source.get('radiologist_name')
            or source.get('radiologistName')
            or source.get('reporting_physician_name')
            or source.get('reporting_physician')
            or source.get('reportingPhysicianName')
            or source.get('ReportingPhysicianName')
            or source.get('reportingPhysician')
            or source.get('ReportingPhysician')
            or source.get('radiologist')
            or report_obj.get('radiologist_name')
            or report_obj.get('radiologistName')
            or report_obj.get('reporting_physician_name')
            or report_obj.get('reporting_physician')
            or report_obj.get('reportingPhysicianName')
            or report_obj.get('reportingPhysician')
            or report_obj.get('radiologist')
            or source.get('physician')
            or source.get('doctor')
        )

        if isinstance(value, dict):
            value = (
                value.get('FullName')
                or value.get('fullName')
                or value.get('full_name')
                or value.get('displayName')
                or value.get('name')
                or value.get('Name')
                or (str(value.get('firstName') or value.get('first_name') or '').strip()
                    + ' '
                    + str(value.get('lastName') or value.get('last_name') or '').strip()).strip()
                or value.get('username')
            )

        return str(value or '').strip()

    @staticmethod
    def _extract_report_comment_text(source: dict) -> str:
        if not isinstance(source, dict):
            return ""

        pacs_comment = source.get('pacsComment')
        if isinstance(pacs_comment, dict):
            pacs_comment = pacs_comment.get('text')

        return str(
            source.get('comment')
            or source.get('report_comment')
            or source.get('reportComment')
            or source.get('pacs_comment')
            or pacs_comment
            or ""
        ).strip()

    def perform_default_search(self):
        """Perform default search with today's date when page loads"""
        try:
            # Check Socket connection status first
            self.check_socket_connection_status()

            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if server:
                asyncio.create_task(self.search_patients_from_server_async())
        except Exception as e:
            # Was print() — failures here were invisible in app.log before
            # 2026-05-28. Default search runs at boot; a silent failure here
            # left a blank patient table with no diagnostic record.
            _logger.error("Error in default search: %s", e, exc_info=True)

    def _on_server_tab_changed(self, index):
        """Auto-trigger search when the user switches tabs in Server Selection.

        Switching TO Local auto-runs a local search (cheap, no round-trip).
        Switching TO Server/Import does NOT auto-query (a server search needs a
        selected server + a round-trip), so — to keep the visible results always
        matching the active data source — the table is cleared instead of
        leaving stale rows from the other source under the new tab.
        """
        tab_name = self.data_access_panel_widget.tabs.tabText(index).lower()
        if tab_name == 'local':
            self.patient_list_function_identifier('local')
        elif os.getenv("AIPACS_SEARCH_CLEAR_ON_MODE_SWITCH", "1") != "0":
            try:
                self.patient_table_widget.clear_table()
            except Exception:
                _logger.debug("clear_table on mode switch failed", exc_info=True)

    def patient_list_function_identifier(self, tab_selected: str):
        tab_selected = tab_selected.lower()

        # قبل از شروع هر سرچ، اگر تسک قبلی فعاله کنسلش کن
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

        # Set searching state and update UI
        self.patient_search_widget.set_searching_state(True)
        self._cancel_search_requested = False

        # First search → warm up the Download Manager in the background so the
        # first patient double-click doesn't pay the cold-start cost (the DM
        # singleton + worker pool + state store + socket client + UI are
        # otherwise built lazily on the first open). Downloads nothing; runs once
        # per session, deferred so it overlaps the search server round-trip.
        self._warmup_download_manager_once()

        if tab_selected == 'local':
            self.source_of_patient_load = SourceOfPatientLoad.DB
            # قبلاً sync بود؛ حالا async و قابل لغو:
            self._search_task = asyncio.create_task(self.search_patients_from_local_async())

        elif tab_selected == 'server':
            self.source_of_patient_load = SourceOfPatientLoad.SERVER
            self._search_task = asyncio.create_task(self.search_patients_from_server_async())

        elif tab_selected == 'import':
            self.source_of_patient_load = SourceOfPatientLoad.IMPORT
            pass

    def _on_advanced_search_requested(self, query: dict):
        """Run the structured advanced search from the Patient-ID filter popup.

        Mirrors patient_list_function_identifier's task handling: cancels any
        in-flight search task and flips the searching state, then routes by the
        ACTIVE data source (Local/Server tab) — Server mode → the selected
        server (search_server_advanced); Local/Import mode → the local DB
        (search_local); an import-date filter is always local (studies.imported_at
        has no server equivalent). Never crosses Local/Server.
        """
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

        self.patient_search_widget.set_searching_state(True)
        self._cancel_search_requested = False
        self._warmup_download_manager_once()

        # Advanced Search MUST follow the same data source as the normal search
        # (the Local/Server tab) and never cross over: a Local-mode advanced
        # query must never hit a server, and a Server-mode query must not read
        # the local DB. The authoritative selector is the DataAccessPanel tab —
        # get_result() — exactly what the normal search reads via
        # patient_list_function_identifier. Before the fix (2026-07-31) this
        # method ignored the mode and ALWAYS routed to the server (except the
        # import-date carve-out), so a Local-mode advanced search hit the PACS
        # server (or errored when no server was selected).
        _honor_mode = os.getenv("AIPACS_ADVANCED_SEARCH_HONORS_MODE", "1") != "0"
        try:
            _tab = str(self.data_access_panel_widget.get_result() or "").strip().lower()
        except Exception:
            _tab = ""
        _is_server_mode = (_tab == "server")

        # Import date is a LOCAL-only field (studies.imported_at — when the study
        # entered THIS database), with no server equivalent, so an import-date
        # filter always resolves against the local DB regardless of mode. This is
        # the "explicitly requested" local case even while in Server mode.
        _has_import_date = bool(query.get('import_date_from') or query.get('import_date_to'))

        # Route to the SERVER only when this is NOT an import-date query AND
        # either mode-honoring says the Server tab is active, or the kill switch
        # restores the legacy always-server behavior.
        _route_to_server = (not _has_import_date) and (
            (_honor_mode and _is_server_mode) or (not _honor_mode)
        )

        if _route_to_server:
            # search_server_advanced resolves get_server_selected() and targets
            # ONLY that server (it aborts if none is selected).
            self.source_of_patient_load = SourceOfPatientLoad.SERVER
            self._search_task = asyncio.create_task(
                self.search_service.search_server_advanced(query)
            )
            return

        # LOCAL (Local/Import tab, or an import-date filter): search ONLY the
        # local DB. Map the advanced fields the local query understands; body
        # part / age / physician have no local column and are not applied — the
        # server path refines those client-side, the local search does not.
        extra = self._advanced_query_to_local_criteria(query)
        self.source_of_patient_load = SourceOfPatientLoad.DB
        self._search_task = asyncio.create_task(
            self.search_service.search_local(extra_criteria=extra)
        )

    @staticmethod
    def _advanced_query_to_local_criteria(query: dict) -> dict:
        """Map an advanced-search query to ``search_patients_local`` criteria.

        Only the fields the local DB search supports are mapped. Body part, age
        and physician (server-side client-refinement fields) have no local
        column and are intentionally omitted.
        """
        extra: dict = {}
        if query.get('import_date_from'):
            extra['import_date_from'] = query.get('import_date_from')
        if query.get('import_date_to'):
            extra['import_date_to'] = query.get('import_date_to')
        _mods = query.get('modalities') or []
        if _mods:
            extra['modality'] = ",".join(_mods)
        _pids = query.get('patient_ids') or []
        if len(_pids) == 1:
            extra['patient_id'] = _pids[0]
        # Acquisition date range (study_date). search_local nulls the home-page
        # date fields, so pass these explicitly to honor the advanced filter.
        if query.get('date_from'):
            extra['date_from'] = query.get('date_from')
        if query.get('date_to'):
            extra['date_to'] = query.get('date_to')
        return extra

    def _warmup_download_manager_once(self) -> None:
        """Pre-build the Download Manager on the FIRST patient search so the first
        patient double-click doesn't pay the cold-start cost.

        Creating the DM singleton builds the worker pool, state store, rule
        engine, executor, intent coordinator, the socket metadata client and the
        DM UI — all otherwise constructed lazily on the first open (observed:
        "Created Zeta Download Manager widget singleton" fired during the first
        double-click, adding cold-start latency the 2nd/3rd patients never pay).
        This warmup downloads NO patient data; it only prepares that
        infrastructure.

        Idempotent + once per session. The DM is a QWidget (main-thread only) so
        this runs on the UI thread but is deferred (singleShot 0) so it overlaps
        the search server round-trip instead of blocking the first open.
        """
        if getattr(self, '_dm_warmup_started', False):
            return
        self._dm_warmup_started = True

        def _do_warmup():
            import time as _t
            _t0 = _t.perf_counter()
            try:
                from pathlib import Path as _P
                from PacsClient.utils.config import SOURCE_PATH as _SRC
                from modules.network.zeta_adapter import get_zeta_download_manager_widget
                get_zeta_download_manager_widget(base_output_dir=_P(_SRC))
                # Optional: pre-boot one idle download subprocess (flag-gated OFF
                # by default via AIPACS_DM_PREWARM) so the very first download also
                # skips the ~2 s Windows subprocess spawn.
                try:
                    from modules.download_manager.workers.prewarm import (
                        get_download_prewarm_pool, prewarm_enabled,
                    )
                    if prewarm_enabled():
                        get_download_prewarm_pool().ensure_warm()
                except Exception:
                    pass
                _logger.info(
                    "[DM-WARMUP] Download Manager warm in %.0fms (first-search trigger)",
                    (_t.perf_counter() - _t0) * 1000.0,
                )
            except Exception:
                _logger.warning("[DM-WARMUP] warmup failed (non-fatal)", exc_info=True)

            # Background: pre-read FAST-viewer source files into Python's linecache
            # so PySide6's shibokensupport feature-check (inspect.getsource →
            # linecache → tokenize.open → disk) does not pay a disk read while
            # creating viewer widgets on the drag/interaction path (measured ~1.9s
            # main-thread stall inside _create_qt_viewer). Pure read-into-cache on a
            # daemon thread — no behaviour change, never touches the UI / VTK.
            def _warm_viewer_linecache():
                try:
                    import linecache as _lc, os as _os
                    _here = _os.path.dirname(_os.path.abspath(__file__))
                    _pacs = _os.path.dirname(_os.path.dirname(_os.path.dirname(_here)))
                    _vdir = _os.path.join(_pacs, "patient_tab")
                    _n = 0
                    for _dp, _dn, _fns in _os.walk(_vdir):
                        for _fn in _fns:
                            if _fn.endswith(".py"):
                                try:
                                    _lc.getlines(_os.path.join(_dp, _fn))
                                    _n += 1
                                except Exception:
                                    pass
                    _logger.info(
                        "[DM-WARMUP] linecache pre-warmed %d viewer source files", _n
                    )
                except Exception:
                    pass
            try:
                import threading as _thr
                _thr.Thread(
                    target=_warm_viewer_linecache, name="linecache-warm", daemon=True
                ).start()
            except Exception:
                pass

            # Background: pay the heavy one-time MODULE IMPORTS off the GUI
            # thread (VS-2 / 2026-08-16). Live stall traces of a first series
            # open showed one contiguous ~9.1 s frozen UI whose samples landed
            # in, among others:
            #   cv2/__init__.py:181 <module> -> :153 bootstrap -> :88 import_module
            #     (~2 s — the OpenCV extension load, triggered by the first
            #      opencv_filter_pipeline call, i.e. the first filtered frame)
            #   dicom_windowing.auto_window_level_from_array -> np.percentile
            #     -> np.unique -> numpy/__init__.py:737 __getattr__
            #     (~1 s — numpy resolving its LAZY submodules on first use, not
            #      the percentile arithmetic itself)
            # Both are pure imports: no Qt object is created and nothing is
            # rendered, so doing them on a daemon thread is safe (Python's
            # import machinery is thread-safe; this is the same pattern the
            # QtWebEngine prewarm and the linecache warm above already use).
            # Worst case the user reaches a series first and simply pays the
            # cost where they do today — never worse, never a new block.
            # Kill switch: AIPACS_VIEWER_IMPORT_WARM=0.
            def _warm_viewer_imports():
                import time as _t2
                warmed = []
                _t0w = _t2.perf_counter()
                try:
                    import cv2  # noqa: F401  (the ~2 s extension load)
                    warmed.append("cv2")
                except Exception:
                    _logger.debug("[IMPORT-WARM] cv2 unavailable", exc_info=True)
                try:
                    # Force numpy's lazy submodules for the auto window/level
                    # path (percentile -> _quantile -> unique) on a 3-element
                    # array: microseconds of maths, but it resolves the
                    # imports that cost ~1 s on the GUI thread.
                    import numpy as _np
                    _tiny = _np.array([0, 1, 2], dtype=_np.int16)
                    _np.percentile(_tiny, 1.0)
                    _np.percentile(_tiny, 99.0)
                    _np.unique(_tiny)
                    warmed.append("numpy.percentile")
                except Exception:
                    _logger.debug("[IMPORT-WARM] numpy warm failed", exc_info=True)
                try:
                    # The module that actually calls cv2 on the render path.
                    from PacsClient.pacs.patient_tab.utils import (  # noqa: F401
                        opencv_filter_pipeline as _ofp,
                    )
                    warmed.append("opencv_filter_pipeline")
                except Exception:
                    _logger.debug("[IMPORT-WARM] filter pipeline import failed",
                                  exc_info=True)
                _logger.info(
                    "[IMPORT-WARM] viewer imports warmed in %.0f ms: %s",
                    (_t2.perf_counter() - _t0w) * 1000.0, ", ".join(warmed) or "none",
                )

            try:
                import os as _os_iw
                if (_os_iw.getenv("AIPACS_VIEWER_IMPORT_WARM", "1") or "1").strip() != "0":
                    import threading as _thr2
                    _thr2.Thread(
                        target=_warm_viewer_imports, name="viewer-import-warm",
                        daemon=True,
                    ).start()
            except Exception:
                pass

        try:
            from PySide6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(0, _do_warmup)
        except Exception:
            _do_warmup()

    def cancel_search(self):
        """Cancel the current search operation"""
        print(f"\n[CANCEL_SEARCH] 🛑 Cancel search requested by user")
        self._cancel_search_requested = True
        
        # Cancel the current search task if it exists
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
            print(f"[CANCEL_SEARCH] ✅ Search task cancelled")
        
        # Reset UI state
        self.patient_search_widget.set_searching_state(False)
        
        # Hide loading indicators
        self.hide_loading()
        self.search_progress.setVisible(False)
        
        # Reset connection indicator
        self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#6b7280').pixmap(12, 12))
        self.connection_indicator.setText(" Search Cancelled")
        self.connection_indicator.setStyleSheet("""
            QLabel { font-size: 14px; color: #6b7280; padding: 4px 8px;
                     background: rgba(107,114,128,.1); border:1px solid rgba(107,114,128,.3); border-radius:8px; }
        """)
        
        print(f"[CANCEL_SEARCH] ✅ UI state reset")

    async def search_patients_from_local_async(self):
        """Search local database — delegated to search service."""
        await self.search_service.search_local()

    async def search_patients_from_server_async(self):
        """Search remote PACS via Socket — delegated to search service."""
        await self.search_service.search_server()

    def _convert_search_data_to_socket_params(self, search_data):
        """Convert UI search data to Socket API parameters (delegates to service)."""
        return HomeSearchService._convert_search_data_to_socket_params(search_data)

    @staticmethod
    def _fetch_reception_patient_payload(patient_id: str) -> dict:
        """Hermes-aligned physician source: GET /api/pacs/patients/{patient_id}.

        Base URL is resolved from the configurable Reception/Workflow API
        endpoint (config/reception_api_config.json) - never a hard-coded IP.
        """
        pid = str(patient_id or '').strip()
        if not pid:
            return {}

        base_url = get_reception_api_base_url()
        timeout = get_reception_api_timeout()
        url = f"{base_url}/api/pacs/patients/{pid}"

        # Circuit breaker: when this center's Reception/API has been failing (e.g. an
        # unreachable endpoint on a poor link — Mehr 8800), skip the doomed REST call so
        # repeated searches don't re-hammer a dead endpoint with timeouts. Self-heals via the
        # half-open probe below. Background/non-clinical only — never touches imaging.
        try:
            if reception_api_breaker_open(base_url):
                emit_download_event(
                    _logger, 'reporter-hydration', phase='breaker_open',
                    pid=pid, base_url=base_url,
                )
                return {}
        except Exception:
            pass

        # The Reception/Workflow API is authenticated and shares the logged-in
        # user's token with the PACS socket channel (see the reception_api_config
        # module docstring). The reporting-physician / `report` block is gated
        # behind that auth, so the GET must carry the bearer token — an
        # anonymous request comes back as a record with no physician data,
        # which is exactly why the Report column kept showing the checkmarks.
        headers = {}
        try:
            from modules.network.socket_token_manager import get_socket_token_manager
            _token = get_socket_token_manager().get_token() or ''
            if _token:
                headers = {'Authorization': f'Bearer {_token}', 'token': _token}
        except Exception:
            headers = {}

        try:
            # Pooled keep-alive session (2026-07-14): the patient list issues one of
            # these per visible reception, and a bare requests.get() opened — and
            # discarded — a TCP connection every time. Reusing the connection cuts
            # ~30% off each call on the WAN link. AIPACS_HTTP_KEEPALIVE=0 = legacy.
            from modules.network.http_session import http_get
            response = http_get(url, base_url=base_url, timeout=timeout, headers=headers)
            status_code = response.status_code
            response.raise_for_status()
            # The endpoint answered (2xx) → it is reachable; close the breaker (self-heal).
            try:
                record_reception_api_success(base_url)
            except Exception:
                pass
            payload = response.json()
            if not isinstance(payload, dict):
                emit_download_event(
                    _logger, 'reporter-hydration', phase='rest_error',
                    pid=pid, status=status_code, result='non_dict_payload',
                )
                return {}
            data = payload.get('data', payload)
            if isinstance(data, list):
                data = data[0] if data else {}
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            emit_download_event(
                _logger, 'reporter-hydration', phase='rest_error',
                pid=pid, base_url=base_url,
                error=type(exc).__name__, detail=str(exc),
            )
            # Trip the breaker ONLY on a connection-level failure (the endpoint is
            # unreachable). An HTTP error status (4xx/5xx) means the server IS reachable, so
            # it must not open the breaker.
            try:
                _en = type(exc).__name__
                if _en in (
                    "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
                    "ConnectTimeoutError", "ReadTimeoutError", "ConnectionRefusedError",
                    "MaxRetryError", "NewConnectionError", "ProxyError", "SSLError",
                ):
                    record_reception_api_failure(base_url)
            except Exception:
                pass
            return {}

    @staticmethod
    def _extract_reporting_physician_from_reception_payload(patient_payload: dict) -> str:
        if not isinstance(patient_payload, dict):
            return ""
        report_obj = patient_payload.get('report') if isinstance(patient_payload.get('report'), dict) else {}

        candidates = [
            patient_payload.get('radiologist_name'),
            patient_payload.get('radiologistName'),
            patient_payload.get('reporting_physician_name'),
            patient_payload.get('reporting_physician'),
            patient_payload.get('reportingPhysicianName'),
            patient_payload.get('reportingPhysician'),
            patient_payload.get('radiologist'),
            report_obj.get('radiologist_name'),
            report_obj.get('radiologistName'),
            report_obj.get('reporting_physician_name'),
            report_obj.get('reporting_physician'),
            report_obj.get('reportingPhysicianName'),
            report_obj.get('reportingPhysician'),
            report_obj.get('radiologist'),
            # The server leaves `radiologist` null for completed studies; the
            # report's approver is the de-facto reporting physician.
            report_obj.get('approvedBy'),
        ]

        for value in candidates:
            if isinstance(value, dict):
                value = (
                    value.get('FullName')
                    or value.get('fullName')
                    or value.get('full_name')
                    or value.get('displayName')
                    or value.get('Name')
                    or value.get('name')
                    or (str(value.get('firstName') or value.get('first_name') or '').strip()
                        + ' '
                        + str(value.get('lastName') or value.get('last_name') or '').strip()).strip()
                    or value.get('username')
                )
            text_value = str(value or '').strip()
            if text_value:
                return text_value
        return ""

    # Reception/server report-state words → app report-status vocabulary
    # (REPORT_STATUSES in patient_table_widget). Conservative: unknown words
    # map to '' and the row's status is left untouched.
    _RECEPTION_REPORT_STATUS_MAP = {
        'pending': 'pending',
        'awaiting_approval': 'awaiting_approval',
        'awaiting_physician_approval': 'awaiting_physician_approval',
        'awaiting_physician': 'awaiting_physician_approval',
        'awaiting_doctor': 'awaiting_physician_approval',
        'awaiting_doctor_approval': 'awaiting_physician_approval',
        'awaiting_secretary_approval': 'awaiting_secretary_approval',
        'awaiting_secretary': 'awaiting_secretary_approval',
        'physician_approved': 'physician_approved',
        'doctor_approved': 'physician_approved',
        'reported': 'physician_approved',
        'secretary_approved': 'secretary_approved',
        'completed': 'completed',
        'complete': 'completed',
        'confirmed': 'completed',
        'approved': 'completed',
        'final': 'completed',
        'finalized': 'completed',
        'archived': 'archived',
    }

    @classmethod
    def _extract_report_status_from_reception_payload(cls, patient_payload: dict) -> str:
        """Best-effort report workflow status from the Reception payload.

        Checks the common status keys on the payload and its `report` block,
        normalizes (lowercase, spaces/dashes → underscores) and maps through
        _RECEPTION_REPORT_STATUS_MAP. Falls back to 'completed' when the
        report block carries an approver/approval timestamp but no explicit
        status. Returns '' when nothing recognizable is present.
        """
        if not isinstance(patient_payload, dict):
            return ""
        report_obj = patient_payload.get('report') if isinstance(patient_payload.get('report'), dict) else {}

        candidates = [
            report_obj.get('status'),
            report_obj.get('report_status'),
            report_obj.get('reportStatus'),
            report_obj.get('workflow_status'),
            report_obj.get('state'),
            patient_payload.get('report_status'),
            patient_payload.get('reportStatus'),
            patient_payload.get('workflow_status'),
        ]
        for value in candidates:
            text = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
            if not text:
                continue
            mapped = cls._RECEPTION_REPORT_STATUS_MAP.get(text, '')
            if mapped:
                return mapped

        # Approval evidence without an explicit status → completed.
        if report_obj.get('approvedBy') or report_obj.get('approved_by') or report_obj.get('approved_at'):
            return 'completed'
        return ""

    def _refresh_report_column_from_server(self):
        """Refresh button hook (2026-06-06): re-pull report workflow state +
        reporting physician for EVERY visible row.

        Clears the physician cache so the background hydration workers fetch
        fresh Reception data instead of serving cached names; statuses ride
        the same payload (see _queue_reporting_physician_hydration._worker).
        Non-blocking — workers are bounded (4 in flight) and marshal UI
        updates through queued signals.
        """
        try:
            cache = getattr(self, '_reporting_physician_cache', None)
            if cache:
                cache.clear()
            # Drop the TTL clocks too — an explicit refresh means "trust nothing
            # cached"; leaving stale timestamps would let a re-populated entry look
            # fresh and skip its revalidation.
            stamps = getattr(self, '_reporting_physician_cache_ts', None)
            if stamps:
                stamps.clear()
        except Exception:
            pass
        try:
            rows = self.patient_table_widget.collect_all_rows_for_report_refresh() or []
        except Exception:
            rows = []
        emit_download_event(
            _logger, 'reporter-hydration', phase='manual_refresh', rows=len(rows),
        )
        for patient_id, patient_name, study_uid in rows:
            self._queue_reporting_physician_hydration(patient_id, patient_name, study_uid)

    def _queue_assignment_hydration(self):
        """Pull the SERVER assignment for the visible receptions after a search.

        The assignment is server-owned state that another workstation can change at
        any time, so — like report status and the reporting physician — it must be
        re-read, not served from a local file forever. Off-thread and bounded; the
        patient_table_widget repaints the Assign + Report columns when it answers.
        `AIPACS_ASSIGN_HYDRATE_ON_SEARCH=0` limits assignment refresh to the button.
        """
        if (os.getenv('AIPACS_ASSIGN_HYDRATE_ON_SEARCH', '1') or '1').strip() == '0':
            return
        try:
            self.patient_table_widget._start_assignment_refresh()
        except Exception:
            pass

    # ── Cache freshness ──────────────────────────────────────────────────────
    # The caches exist to make search fast. They must NEVER become the authority
    # for data the server can change underneath us (report status, reporting
    # physician, assignment). TTL + revalidation keeps the speed while letting an
    # updated value through. `AIPACS_CACHE_REVALIDATE=0` restores the legacy
    # "a cache hit is final" behaviour.
    _REPORTER_CACHE_TTL_S = 60.0

    def _reporter_cache_ttl(self) -> float:
        try:
            return max(0.0, float(os.getenv('AIPACS_REPORTER_CACHE_TTL_S', '') or
                                  self._REPORTER_CACHE_TTL_S))
        except Exception:
            return self._REPORTER_CACHE_TTL_S

    def _reporter_cache_is_fresh(self, pid: str) -> bool:
        """True when the cached physician for *pid* is young enough to trust.

        Legacy mode (`AIPACS_CACHE_REVALIDATE=0`) always says fresh — i.e. a cache
        hit is final, exactly as before.
        """
        if (os.getenv('AIPACS_CACHE_REVALIDATE', '1') or '1').strip() == '0':
            return True
        stamps = getattr(self, '_reporting_physician_cache_ts', None)
        if not stamps:
            return False   # unknown age → revalidate once
        try:
            age = time.time() - float(stamps.get(pid) or 0.0)
        except Exception:
            return False
        return age < self._reporter_cache_ttl()

    def _mark_reporter_cached(self, pid: str) -> None:
        stamps = getattr(self, '_reporting_physician_cache_ts', None)
        if stamps is None:
            stamps = {}
            self._reporting_physician_cache_ts = stamps
        try:
            stamps[pid] = time.time()
        except Exception:
            pass

    def _queue_reporting_physician_hydration(self, patient_id: str, patient_name: str, study_uid: str = ""):
        pid = str(patient_id or '').strip()
        if not pid:
            return
        suid = str(study_uid or '').strip()

        cache = getattr(self, '_reporting_physician_cache', None)
        if cache is None:
            cache = {}
            self._reporting_physician_cache = cache

        cached_physician = str(cache.get(pid) or '').strip()
        if cached_physician and self._has_displayable_reporting_name(cached_physician):
            # STALE-WHILE-REVALIDATE (2026-07-14). This used to `return` here — a
            # cache hit was FINAL, and the entry was only ever dropped by the
            # Refresh button. So once a patient's physician/report was cached, a
            # plain SEARCH would keep re-displaying the stale value for the rest of
            # the session, and the cache had quietly become the source of truth for
            # data that changes on the server.
            #
            # Now: paint the cached value INSTANTLY (the search stays as fast as it
            # was), and if the entry is older than the TTL fall through to a
            # background re-fetch that corrects the row when the server answers.
            emit_download_event(
                _logger, 'reporter-hydration', phase='cache_hit',
                pid=pid, physician=cached_physician,
            )
            try:
                self.patient_table_widget.update_reporting_physician_for_patient(pid, patient_name, cached_physician)
            except Exception:
                pass
            if self._reporter_cache_is_fresh(pid):
                return
            emit_download_event(
                _logger, 'reporter-hydration', phase='revalidate', pid=pid,
            )
            # fall through → re-fetch from the server and update if it disagrees
        if cached_physician and not self._has_displayable_reporting_name(cached_physician):
            cache.pop(pid, None)

        inflight = getattr(self, '_reporting_physician_inflight', None)
        if inflight is None:
            inflight = set()
            self._reporting_physician_inflight = inflight
        # Reception hydration fan-out. Was hard-coded to 4; each worker is one
        # independent REST GET, so on a 24-row list this serialised into 6 waves.
        # Tunable via AIPACS_RECEPTION_WORKERS (same knob the assignment fetch uses).
        try:
            from modules.network.http_session import parallel_workers
            max_inflight = parallel_workers()
        except Exception:
            max_inflight = 4
        if len(inflight) >= max_inflight:
            QTimer.singleShot(
                120,
                lambda p=pid, n=patient_name, s=suid: self._queue_reporting_physician_hydration(p, n, s),
            )
            return
        if pid in inflight:
            return

        inflight.add(pid)

        def _worker():
            physician_name = ""
            try:
                payload = self._fetch_reception_patient_payload(pid)
                physician_name = self._extract_reporting_physician_from_reception_payload(payload)

                # Report workflow status rides the same payload (2026-06-06):
                # awaiting approval/secretary/doctor, reported, confirmed, ...
                # Queued signal → _update_report_status_in_table on the UI
                # thread. Only emitted when a status was recognized AND we
                # know which study row it belongs to.
                try:
                    if suid:
                        mapped_status = self._extract_report_status_from_reception_payload(payload)
                        if mapped_status:
                            emit_download_event(
                                _logger, 'reporter-hydration', phase='status_resolved',
                                pid=pid, study=suid, status=mapped_status,
                            )
                            self.patient_table_widget.reportStatusResolved.emit(suid, mapped_status)
                except Exception:
                    pass
                # If server gave only actor-id, resolve once to full name using existing widget resolver.
                if self._is_probable_actor_id(physician_name):
                    resolver = getattr(self.patient_table_widget, '_fetch_server_user_full_name', None)
                    if callable(resolver):
                        resolved_name = resolver(physician_name)
                        physician_name = str(resolved_name or '').strip()
                    else:
                        physician_name = ""

                # NOTE: deliberately no GetReportStatus socket fallback here.
                # The Reception API is the source of the reporting physician,
                # and the socket GetReportStatus endpoint does not respond on
                # this server — calling it blocked this worker for the full
                # connection timeout (~30s) per patient and stalled the
                # post-search column auto-fill. Patients with no physician on
                # the server simply keep the completed checkmarks.
                if self._has_displayable_reporting_name(physician_name):
                    cache[pid] = physician_name
                    self._mark_reporter_cached(pid)   # TTL clock for revalidation
                    emit_download_event(
                        _logger, 'reporter-hydration', phase='resolved',
                        pid=pid, physician=physician_name,
                    )
                    # Marshal the column update onto the UI thread via a Qt
                    # signal with a queued cross-thread connection. A direct
                    # call (or QTimer.singleShot) from this worker thread does
                    # not reach the UI thread — QTimer has no event loop here.
                    try:
                        self.patient_table_widget.reportingPhysicianResolved.emit(
                            pid, patient_name, physician_name,
                        )
                    except Exception:
                        pass
                else:
                    emit_download_event(
                        _logger, 'reporter-hydration', phase='unresolved',
                        pid=pid, raw_value=(physician_name or ''),
                    )
            except Exception as exc:
                emit_download_event(
                    _logger, 'reporter-hydration', phase='worker_error',
                    pid=pid, error=type(exc).__name__, detail=str(exc),
                )
            finally:
                inflight.discard(pid)

        threading.Thread(target=_worker, daemon=True).start()

    def _build_cached_thumbnail_payload(self, study_uid: str) -> dict:
        """Build right-panel thumbnail payload from local thumbnail files + DB series metadata.

        Robust DB lookup (2026-05-26 hardening): the previous implementation made
        one DB call per series via get_series_info_from_database (which casts
        int(series_number) and re-resolves study_pk every time). When the lookup
        miss-matched (filename had leading zeros, non-integer naming, transient
        study_pk resolution failure), it returned {} → image_count fell back to 0
        and the thumbnail renderer dropped the blue "N images" badge in favour of
        the grey "Series N" label, producing the visible footer overwrite reported
        for patient 43670 (and others).

        Fix: pull ALL series for the study in ONE call via get_series_by_study_uid,
        key them by string series_number (both with and without leading-zero
        normalisation), then look up each disk thumbnail tolerantly. This makes
        Path 1 (_load_thumbnails_for_downloaded_study, DB-driven) and Path 2
        (this method, disk-driven) produce identical metadata for the same
        underlying DB state — preserving image_count > 0 on the re-render so the
        blue badge stays put.
        """
        payload = {'thumbnails': []}

        # Build a tolerant series_number → row index once, so the second render
        # produces the SAME image_count / description as Path 1's DB render.
        series_index: dict = {}
        try:
            from database.manager import get_series_by_study_uid as _get_all_series
            for _row in (_get_all_series(study_uid) or []):
                sn_raw = _row.get('series_number', '')
                sn_str = str(sn_raw if sn_raw is not None else '').strip()
                if not sn_str:
                    continue
                series_index[sn_str] = _row
                # also index the leading-zero-stripped variant for disk-name mismatch
                stripped = sn_str.lstrip('0') or '0'
                series_index.setdefault(stripped, _row)
        except Exception:
            series_index = {}

        for series_path in get_all_series_thumbnail_from_study_folder(study_uid):
            series_number = get_name_file_from_path(series_path)
            sn_key = str(series_number or '').strip()
            series_info = series_index.get(sn_key) \
                or series_index.get(sn_key.lstrip('0') or '0') \
                or {}
            # Final safety net: if the bulk lookup truly missed (study_pk race,
            # orphan thumbnail file), fall back to the original per-series call
            # so we don't lose data that single-shot lookup could still find.
            if not series_info:
                try:
                    series_info = self.get_series_info_from_database(study_uid, series_number) or {}
                except Exception:
                    series_info = {}

            payload['thumbnails'].append(
                {
                    'file_path': series_path,
                    'series_number': series_number,
                    'modality': series_info.get('modality', 'Unknown'),
                    # Empty fallback (not 'Series N'): the renderer in
                    # thumbnail_manager only emits the blue "N images" badge when
                    # image_count>0 AND no description-already-rendered overlap.
                    # A literal 'Series N' description visually competes with the
                    # blue badge so we keep description blank when DB has no real
                    # value, letting image_count drive the footer.
                    'series_description': series_info.get('series_description', ''),
                    'image_count': series_info.get('image_count', 0),
                    'protocol_name': series_info.get('protocol_name', ''),
                    'body_part_examined': series_info.get('body_part_examined', ''),
                }
            )
        return payload

    def _is_open_flow_thumbnail_deferral_allowed(self, study_uid: str) -> bool:
        """Only allow right-panel network deferral during active double-click open flow."""
        try:
            study_key = str(study_uid or '')
            opening = getattr(self, '_opening_studies', None) or set()
            if study_key in opening:
                return True
            if not bool(getattr(self, '_double_click_loading_active', False)):
                return False
            active_widget = getattr(self, '_double_click_loading_widget', None)
            active_uid = str(getattr(active_widget, 'study_uid', '') or '') if active_widget else ''
            return bool(active_uid and active_uid == study_key)
        except Exception:
            return False

    def _add_socket_patient_to_table(self, patient):
        """
        Add Socket patient data to the patient table

        Args:
            patient (dict): Patient data from Socket API
        """
        try:
            # Extract patient information
            patient_id = patient.get('patient_id', 'N/A')
            patient_name = patient.get('patient_name', 'N/A')
            # Best-available-name fallback (44982, 2026-06-07): some devices
            # send an EMPTY PatientName, and the server then returns "" at
            # every level (patient list AND each study). A blank Name cell /
            # tab title looks like data loss — fall back to the patient ID so
            # the row and the tab opened from it stay identifiable. The raw
            # dict is not mutated; only the display/open value is repaired.
            if not str(patient_name or '').strip() or patient_name == 'N/A':
                _pid_str = str(patient_id or '').strip()
                if _pid_str and _pid_str != 'N/A':
                    patient_name = f"Patient {_pid_str}"
            study_uid = patient.get('latest_study_uid', 'N/A')
            raw_study_uids = patient.get('study_uids') or []
            if isinstance(raw_study_uids, str):
                study_uids = [raw_study_uids]
            else:
                study_uids = list(raw_study_uids) if isinstance(raw_study_uids, list) else []

            # Bugfix 44113: remember the server's series count per study so the
            # single-click thumbnail/series gates can detect a study that GREW on the
            # server (the local thumbnail/completeness caches are local-only and can't
            # see new server series). This runs for every patient as the list loads, so
            # the count is ready before any click. Single-study only — count_of_series
            # maps to that one study; multi-study patients render via the grouped path.
            try:
                _srv_cnt = int(patient.get('count_of_series') or 0)
                # `count_of_series` is the PATIENT-level series total. It equals the
                # single study's series count ONLY when the patient truly has one
                # study. For a multi-study patient the server still returns just the
                # latest study UID (so len(study_uids)==1), but count_of_series then
                # aggregates ALL the patient's studies (e.g. 44534: DX 3 + MRI 7 = 10)
                # and must NOT be stashed against the one returned study — that feeds a
                # false "grew" signal into the right-panel cache gate. Require the
                # patient to be genuinely single-study.
                _total_studies = int(patient.get('total_studies') or 0)
                if _srv_cnt > 0 and len(study_uids) == 1 and _total_studies <= 1:
                    if not hasattr(self, '_server_series_count_by_study'):
                        self._server_series_count_by_study = {}
                    _k = str(study_uids[0] or '').strip()
                    if _k:
                        self._server_series_count_by_study[_k] = _srv_cnt
            except Exception:
                pass

            # 44534 multi-modality completeness: stash a compact per-patient meta
            # (modality set + study count + known UIDs) as the list loads, so the
            # OPEN path can decide — with NO extra server query — whether to enumerate
            # the per-modality study UIDs the patient-list hid. GetPatientList returns
            # only the latest study UID per patient, so a same-patient study of a
            # different modality (e.g. an MRI when the latest is an X-ray) is otherwise
            # invisible. Zero cost: the data is already in this row. Read back in
            # _resolve_patient_study_uids_async via _server_patient_meta_by_pid.
            try:
                if not hasattr(self, '_server_patient_meta_by_pid'):
                    self._server_patient_meta_by_pid = {}
                _pid_meta_key = str(patient_id or '').strip()
                if _pid_meta_key:
                    self._server_patient_meta_by_pid[_pid_meta_key] = {
                        'total_studies': patient.get('total_studies', patient.get('study_count')),
                        'modalities': patient.get('modalities'),
                        'modality': patient.get('modality'),
                        'study_uids': list(study_uids),
                        'latest_study_uid': str(study_uid or '').strip(),
                        # Additive (2026-06-04, fidelity audit §4.2): carry the row's
                        # display fields so bus-driven open/select use production-
                        # identical arguments (real tab titles, real report_status).
                        'patient_name': str(patient_name or '').strip(),
                        'report_status': str(patient.get('report_status') or 'pending'),
                    }
            except Exception:
                pass

            studies = patient.get('studies') or patient.get('study_list') or []
            study_rows = []
            if isinstance(studies, list):
                for study in studies:
                    if not isinstance(study, dict):
                        continue
                    row_uid = (
                        study.get('study_uid')
                        or study.get('StudyInstanceUID')
                        or study.get('studyInstanceUid')
                        or ''
                    )
                    row_uid = str(row_uid or '').strip()
                    if not row_uid:
                        continue
                    row_date = (
                        study.get('study_date')
                        or study.get('StudyDate')
                        or patient.get('latest_study_date')
                        or 'N/A'
                    )
                    row_time = (
                        study.get('study_time')
                        or study.get('StudyTime')
                        or patient.get('latest_study_time')
                        or 'N/A'
                    )
                    row_desc = (
                        study.get('study_description')
                        or study.get('StudyDescription')
                        or patient.get('latest_study_description')
                        or 'N/A'
                    )
                    row_report_status = (
                        study.get('report_status')
                        or study.get('reportStatus')
                        or study.get('latest_study_report_status')
                        or patient.get('latest_study_report_status')
                        or patient.get('reportStatus')
                        or patient.get('report_status')
                        or 'pending'
                    )
                    # A study row carries ONLY its own per-study count (0 when the
                    # server didn't provide one). Do NOT fall back to the patient-level
                    # total here — summing patient totals across study rows is the
                    # 46970 "5042 = 2 x 2521" doubling. The patient total is applied
                    # once, authoritatively, in the aggregation block below.
                    row_series = (
                        study.get('count_of_series')
                        or study.get('total_series')
                        or 0
                    )
                    row_instances = (
                        study.get('count_of_instances')
                        or study.get('total_instances')
                        or 0
                    )
                    study_rows.append({
                        'study_uid': row_uid,
                        'study_date': row_date,
                        'study_time': row_time,
                        'study_description': row_desc,
                        'report_status': row_report_status,
                        'series_count': row_series,
                        'images_count': row_instances,
                        'comment': self._extract_report_comment_text(study),
                        'reporting_physician': self._extract_reporting_physician_name(study),
                    })

            if not study_uid or study_uid == 'N/A':
                if study_uids:
                    study_uid = str(study_uids[0] or 'N/A')

            if not study_rows:
                study_rows = [{
                    'study_uid': study_uid,
                    'study_date': patient.get('latest_study_date', 'N/A'),
                    'study_time': patient.get('latest_study_time', 'N/A'),
                    'study_description': patient.get('latest_study_description', 'N/A'),
                    'report_status': (
                        patient.get('latest_study_report_status')
                        or patient.get('reportStatus')
                        or patient.get('report_status')
                        or 'pending'
                    ),
                    'series_count': 0,  # placeholder row: per-study count unknown; patient total applied once below
                    'images_count': 0,  # placeholder row: per-study count unknown; patient total applied once below
                    'comment': self._extract_report_comment_text(patient),
                    'reporting_physician': self._extract_reporting_physician_name(patient),
                }]

            if study_uid and study_uid != 'N/A' and not any(str(r.get('study_uid') or '') == str(study_uid) for r in study_rows):
                study_rows.append({
                    'study_uid': study_uid,
                    'study_date': patient.get('latest_study_date', 'N/A'),
                    'study_time': patient.get('latest_study_time', 'N/A'),
                    'study_description': patient.get('latest_study_description', 'N/A'),
                    'report_status': (
                        patient.get('latest_study_report_status')
                        or patient.get('reportStatus')
                        or patient.get('report_status')
                        or 'pending'
                    ),
                    'series_count': 0,  # placeholder row: per-study count unknown; patient total applied once below
                    'images_count': 0,  # placeholder row: per-study count unknown; patient total applied once below
                    'comment': self._extract_report_comment_text(patient),
                    'reporting_physician': self._extract_reporting_physician_name(patient),
                })

            if study_uids:
                existing_uids = {str(r.get('study_uid') or '') for r in study_rows}
                for uid in study_uids:
                    uid_str = str(uid or '').strip()
                    if uid_str and uid_str not in existing_uids:
                        study_rows.append({
                            'study_uid': uid_str,
                            'study_date': patient.get('latest_study_date', 'N/A'),
                            'study_time': patient.get('latest_study_time', 'N/A'),
                            'study_description': patient.get('latest_study_description', 'N/A'),
                            'report_status': (
                                patient.get('latest_study_report_status')
                                or patient.get('reportStatus')
                                or patient.get('report_status')
                                or 'pending'
                            ),
                            'series_count': 0,  # placeholder row: per-study count unknown; patient total applied once below
                            'images_count': 0,  # placeholder row: per-study count unknown; patient total applied once below
                            'comment': self._extract_report_comment_text(patient),
                            'reporting_physician': self._extract_reporting_physician_name(patient),
                        })
                        existing_uids.add(uid_str)

            modality = ', '.join(patient.get('modalities', []))
            
            # Extract study time
            study_time = patient.get('latest_study_time', 'N/A')
            
            # Extract body part - سرور body_parts را به صورت array ارسال می‌کند
            body_parts = patient.get('body_parts', [])
            if isinstance(body_parts, list) and len(body_parts) > 0:
                # اگر array است، با کاما join کن
                body_part = ', '.join(str(bp) for bp in body_parts if bp)
            else:
                # اگر array نیست یا خالی است، از فیلد قدیمی استفاده کن
                body_part = patient.get('body_part_examined', 'N/A')
                if not body_part or body_part == 'N/A':
                    body_part = 'N/A'
            
            # Extract patient age
            age = patient.get('patient_age', 'N/A')

            # Reporting/referring physician can arrive in patient, latest_study, data, or per-study row objects.
            latest_study = patient.get('latest_study') or {}
            data_obj = patient.get('data') or {}
            common_reporting_physician = (
                self._extract_reporting_physician_name(patient)
                or self._extract_reporting_physician_name(latest_study)
                or self._extract_reporting_physician_name(data_obj)
            )
            common_comment = (
                self._extract_report_comment_text(patient)
                or self._extract_report_comment_text(latest_study)
                or self._extract_report_comment_text(data_obj)
            )

            valid_statuses = ['pending', 'awaiting_physician_approval', 
                            'awaiting_secretary_approval', 'awaiting_approval',
                            'physician_approved', 'secretary_approved', 
                            'completed', 'archived']

            unique_study_rows = []
            seen_study_uids = set()
            for study_row in study_rows:
                row_uid = str(study_row.get('study_uid') or '').strip()
                if not row_uid or row_uid in seen_study_uids:
                    continue
                seen_study_uids.add(row_uid)
                unique_study_rows.append(study_row)

            if not unique_study_rows:
                return

            primary_study = unique_study_rows[0]
            primary_uid = str(primary_study.get('study_uid') or '').strip()

            merged_study_uids = []
            for uid in [primary_uid, *study_uids]:
                uid_str = str(uid or '').strip()
                if uid_str and uid_str not in merged_study_uids:
                    merged_study_uids.append(uid_str)

            try:
                # Cache per-patient grouped studies for downstream open flow.
                patient_study_map = getattr(self, '_patient_study_uid_map', None)
                if patient_study_map is None:
                    patient_study_map = {}
                    self._patient_study_uid_map = patient_study_map
                pid_key = str(patient_id or '').strip()
                if pid_key:
                    patient_study_map[pid_key] = list(merged_study_uids)
            except Exception:
                pass

            row_date = primary_study.get('study_date', 'N/A')
            if row_date != 'N/A' and len(str(row_date)) == 8:
                try:
                    row_date = f"{str(row_date)[:4]}/{str(row_date)[4:6]}/{str(row_date)[6:8]}"
                except Exception:
                    pass

            total_studies = len(merged_study_uids) or len(unique_study_rows) or 1

            # Whole-patient totals applied ONCE (never multiplied by the number of
            # study rows). See _resolve_patient_table_counts — this is the 46970
            # "Images 5042 = 2 x 2521" doubling fix.
            total_series, total_images = _resolve_patient_table_counts(
                unique_study_rows, patient,
                patient_id=patient_id, total_studies=total_studies,
            )

            primary_desc = primary_study.get('study_description', 'N/A')
            description_parts = []
            if primary_desc and primary_desc != 'N/A':
                description_parts.append(primary_desc)
            if total_studies > 0:
                description_parts.append(f"Studies: {total_studies}")
            if total_series > 0:
                description_parts.append(f"Series: {total_series}")
            if total_images > 0:
                description_parts.append(f"Images: {total_images}")
            description = ' | '.join(description_parts) if description_parts else 'No description available'

            report_status = (
                primary_study.get('report_status')
                or primary_study.get('reportStatus')
                or patient.get('latest_study_report_status')
                or patient.get('reportStatus')
                or patient.get('report_status')
                or 'pending'
            )
            report_status = str(report_status or '').strip().lower()
            if report_status == 'complete':
                report_status = 'completed'
            if report_status not in valid_statuses:
                report_status = 'pending'

            row_reporting_physician = (
                str(primary_study.get('radiologist_name') or '').strip()
                or str(primary_study.get('radiologistName') or '').strip()
                or str(patient.get('radiologist_name') or '').strip()
                or str(patient.get('radiologistName') or '').strip()
                or self._extract_reporting_physician_name(primary_study)
                or str(primary_study.get('reporting_physician') or '').strip()
                or next((
                    str(study_row.get('radiologist_name') or study_row.get('radiologistName') or '').strip()
                    for study_row in unique_study_rows
                    if str(study_row.get('radiologist_name') or study_row.get('radiologistName') or '').strip()
                ), '')
                or next((
                    self._extract_reporting_physician_name(study_row)
                    for study_row in unique_study_rows
                    if self._extract_reporting_physician_name(study_row)
                ), '')
                or common_reporting_physician
            )
            row_comment = (
                self._extract_report_comment_text(primary_study)
                or str(primary_study.get('comment') or '').strip()
                or common_comment
            )

            self.add_data2patient_list_table(
                patient_id=patient_id,
                patient_name=patient_name,
                study_date=row_date,
                study_time=primary_study.get('study_time', 'N/A'),
                body_part=body_part,
                age=age,
                description=description,
                modality=modality,
                study_uid=primary_uid,
                study_uids=merged_study_uids,
                series_count=total_series,
                images_count=total_images,
                report_status=report_status,
                reporting_physician=row_reporting_physician,
                initial_comment=row_comment,
            )

            # Keep search path fast: do not trigger extra network hydration here.

        except Exception as e:
            # Was print() — per-row failures (malformed patient dict,
            # missing study_uid, type coercion error) caused patients to
            # silently drop from the patient table with no diagnostic
            # record. The catch-all app.log handler (2026-05-28) makes
            # this visible.
            _logger.error(
                "Error adding Socket patient to table (patient_id=%r): %s",
                patient.get('patient_id') if isinstance(patient, dict) else None,
                e, exc_info=True,
            )

    def _save_socket_patient_to_db(self, patient):
        """Save Socket patient data to local database (delegates to service)."""
        self.db_service.save_socket_patient_to_db(patient)

    def _sync_completed_reporting_physicians_after_search(self):
        """One-pass post-search hydration for completed rows still missing physician names."""
        emit_download_event(
            _logger, 'reporter-hydration', phase='trigger_start',
            endpoint=get_reception_api_base_url(),
        )
        try:
            collector = getattr(self.patient_table_widget, 'collect_completed_rows_missing_reporting_physician', None)
            if not callable(collector):
                emit_download_event(
                    _logger, 'reporter-hydration', phase='trigger_abort',
                    reason='collector_unavailable',
                )
                return

            pending_rows = collector() or []
            emit_download_event(
                _logger, 'reporter-hydration', phase='detected',
                completed_missing_physician=len(pending_rows),
            )
            queued = 0
            for patient_id, patient_name, study_uid in pending_rows:
                self._queue_reporting_physician_hydration(patient_id, patient_name, study_uid)
                queued += 1
            emit_download_event(
                _logger, 'reporter-hydration', phase='queued', queued=queued,
            )
            # The ASSIGNMENT is server-owned too — another workstation can change it
            # at any moment — so a search must re-read it rather than trust the local
            # file. Off-thread; repaints the Assign + Report columns when it answers.
            self._queue_assignment_hydration()
        except Exception as exc:
            emit_download_event(
                _logger, 'reporter-hydration', phase='trigger_error',
                error=type(exc).__name__, detail=str(exc),
            )
            _logger.warning(
                "[reporter-hydration] post-search sync failed\n%s",
                traceback.format_exc(),
            )

    def save_patient_and_study_on_db(self, dataset):
        """Persist patient + study from a pydicom Dataset (delegates to service)."""
        self.db_service.save_patient_and_study_on_db(dataset)

    def add_data2patient_list_table(self, **kwargs):
        '''
            add data to patient list (patient_table_widget) for show
        '''
        # Check download status from database
        study_uid = kwargs.get('study_uid')
        if study_uid:
            try:
                from PacsClient.pacs.patient_tab.utils.utils import get_study_download_status

                try:
                    # Check if is_downloaded is already set
                    is_downloaded = kwargs.get('is_downloaded')
                    if is_downloaded is not None:
                        # Convert bool to status string for backwards compatibility
                        kwargs['download_status'] = 'complete' if is_downloaded else 'not_downloaded'
                    else:
                        # Get expected series count from kwargs (from server response)
                        expected_series = kwargs.get('series_count') or kwargs.get('count_of_series') or 0
                        # Get detailed download status
                        download_status = get_study_download_status(study_uid, expected_series if expected_series > 0 else None)
                        kwargs['download_status'] = download_status
                        kwargs['is_downloaded'] = (download_status == 'complete')
                except Exception as ex:
                    # Was print() — failures here silently mark every row as
                    # not_downloaded, hiding storage-layer or DB lock issues.
                    _logger.warning(
                        "Error in download status check (study_uid=%r): %s",
                        study_uid, ex, exc_info=True,
                    )
                    kwargs['download_status'] = 'not_downloaded'
                    kwargs['is_downloaded'] = False
            except Exception as e:
                # Was print() — outer guard around download-status setup.
                _logger.error(
                    "Error checking download status: %s", e, exc_info=True,
                )
                kwargs['download_status'] = 'not_downloaded'
                kwargs['is_downloaded'] = False

        # Set default values for other status fields
        kwargs.setdefault('has_voice', False)
        kwargs.setdefault('is_reported', False)

        self.patient_table_widget.add_patient_data(**kwargs)

    def center_align_table_column(self, table_widget, column_index):
        """
        تنظیم وسط‌چین برای تمام سلول‌های یک ستون خاص

        Args:
            table_widget: جدول مورد نظر (QTableWidget)
            column_index: ایندکس ستون (از 0 شروع می‌شود)
        """
        if not table_widget or column_index < 0:
            return

        row_count = table_widget.rowCount()

        for row in range(row_count):
            item = table_widget.item(row, column_index)
            if item:
                item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)

            # اگر ویجت داخل سلول است (مثل چک‌باکس)
            widget = table_widget.cellWidget(row, column_index)
            if widget:
                from PySide6.QtWidgets import QHBoxLayout, QWidget, QCheckBox
                from PacsClient.utils.custom_checkbox import CustomCheckbox

                # اگر QCheckBox یا CustomCheckbox است
                if isinstance(widget, (QCheckBox, CustomCheckbox)):
                    # استفاده از استایل برای وسط‌چین کردن indicator چک‌باکس
                    widget.setStyleSheet("""
                        QCheckBox {
                            spacing: 0px;
                            margin: 0px;
                            padding: 0px;
                        }
                        QCheckBox::indicator {
                            subcontrol-position: center center;
                            subcontrol-origin: padding;
                            margin: 0px;
                            padding: 0px;
                        }
                    """)
                    # تنظیم alignment خود ویجت
                    widget.setAlignment(Qt.AlignCenter)
                else:
                    # برای سایر ویجت‌ها، استفاده از layout
                    parent = widget.parentWidget()
                    if not isinstance(parent, QWidget) or parent.layout() is None:
                        container = QWidget()
                        layout = QHBoxLayout(container)
                        layout.addWidget(widget)
                        layout.setAlignment(Qt.AlignCenter)
                        layout.setContentsMargins(0, 0, 0, 0)
                        table_widget.setCellWidget(row, column_index, container)

    def _update_results_count(self):
        """Update the results count label"""
        # This method is now handled by PatientTableWidget
        pass

    def cancel_current_search(self):
        """علامت لغو را ست می‌کند، تسک فعال را کنسل و UI را جمع می‌کند."""
        self._cancel_search_requested = True
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

        # بروزرسانی وضعیت
        try:
            self.search_progress.setVisible(False)
            self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
            self.connection_indicator.setText(" Socket Search Cancelled")
            self.connection_indicator.setStyleSheet("""
                QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;
                         background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }
            """)
        except Exception:
            pass

        # بستن دیالوگ لودینگ
        self.hide_loading()

    def _on_cancel_search_clicked(self):
        # جلوگیری از چندبار کلیک
        if hasattr(self, 'loading_cancel_btn') and self.loading_cancel_btn:
            self.loading_cancel_btn.setDisabled(True)
            self.loading_cancel_btn.setText("Cancelling...")
        self.cancel_current_search()

    def _animate_dots(self):
        """Animate the loading dots"""
        if not hasattr(self, 'dot_timer'):
            self.dot_timer = QTimer()
            self.dot_timer.timeout.connect(self._update_dots)
            self.dot_index = 0

        self.dot_timer.start(500)  # Update every 500ms

    def _update_dots(self):
        """Update dot animation"""
        if hasattr(self, 'status_dots') and self.status_dots:
            # Reset all dots
            for dot in self.status_dots:
                dot.setPixmap(qta.icon('fa5s.circle', color='rgba(59, 130, 246, 0.4)').pixmap(12, 12))

            # Highlight current dot
            if self.dot_index < len(self.status_dots):
                self.status_dots[self.dot_index].setPixmap(qta.icon('fa5s.circle', color='#3b82f6').pixmap(12, 12))

            self.dot_index = (self.dot_index + 1) % len(self.status_dots)

    async def show_patient_studies(self, patient_info):
        """Display patient studies asynchronously - Optimized for speed"""
        try:
            study_uid = patient_info['StudyInstanceUID']
            patient_id = patient_info['PatientID']
            study_uid_str = str(study_uid or '').strip()

            # Always reset stale sidebar content when the selected study changes.
            # This prevents previous-patient thumbnails from remaining visible while
            # new thumbnails are still loading or temporarily deferred.
            last_render_uid = str(getattr(self, '_right_panel_render_study_uid', '') or '').strip()
            if study_uid_str and study_uid_str != last_render_uid:
                try:
                    if hasattr(self, 'right_panel_widget') and self.right_panel_widget is not None:
                        self.right_panel_widget.clear_content()
                        if hasattr(self.right_panel_widget, 'count_label'):
                            self.right_panel_widget.count_label.setText('Loading...')
                except Exception:
                    pass
                self._right_panel_render_study_uid = study_uid_str

            inflight_uid = str(getattr(self, '_right_panel_fetch_inflight_uid', '') or '')
            if inflight_uid and inflight_uid == study_uid_str:
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_inflight_skip', patient_id=patient_id)
                return
            self._right_panel_fetch_inflight_uid = study_uid_str
            if hasattr(self, '_is_active_patient_selection') and not self._is_active_patient_selection(patient_id, study_uid):
                if hasattr(self, '_log_open_trace'):
                    try:
                        self._log_open_trace(study_uid, 'right_panel_inactive_skip_pre_fetch', patient_id=str(patient_id or ''))
                    except Exception:
                        pass
                return
            request_token = int(getattr(self, "_thumbnail_fetch_token", 0)) + 1
            self._thumbnail_fetch_token = request_token
            self._thumbnail_fetch_study_uid = study_uid_str
            db_cache_miss = False
            if hasattr(self, '_log_open_trace'):
                self._log_open_trace(study_uid, 'right_panel_begin', patient_id=patient_id)
            # SHADOW: record the selection in the canonical lifecycle model (no-op
            # unless AIPACS_LIFECYCLE_THUMBS is on). The right panel is a preview.
            _lc_shadow_note('note_selection', patient_id, study_uid, open_intent=False)

            if self.source_of_patient_load == SourceOfPatientLoad.OFFLINE_CLOUD:
                server = self.data_access_panel_widget.get_server_selected()
                if not server or server.get("server_type") != "offline_cloud":
                    return

                sync_result = await asyncio.to_thread(
                    sync_offline_cloud_study_preview_to_local,
                    server,
                    study_uid,
                )
                if not sync_result.get("ok"):
                    QMessageBox.warning(
                        self,
                        "Offline Cloud",
                        sync_result.get("error") or "Could not read the offline cloud package.",
                    )
                    return

                thumbnails = {'thumbnails': []}
                all_series_thumbnails = get_all_series_thumbnail_from_study_folder(study_uid)
                for series_path in all_series_thumbnails:
                    series_number = get_name_file_from_path(series_path)
                    series_info = self.get_series_info_from_database(study_uid, series_number)
                    thumbnails['thumbnails'].append(
                        {
                            'file_path': series_path,
                            'series_number': series_number,
                            'modality': series_info.get('modality', 'Unknown'),
                            'series_description': series_info.get('series_description', f'Series {series_number}'),
                            'image_count': series_info.get('image_count', 0),
                            'protocol_name': series_info.get('protocol_name', ''),
                            'body_part_examined': series_info.get('body_part_examined', ''),
                        }
                    )
                self.display_thumbnails(thumbnails.get('thumbnails', []), progressive=False)
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_offline_cloud_display', thumbnail_count=len(thumbnails.get('thumbnails', [])))
                return

            # Fast path: if local thumbnails exist, always show them immediately.
            # This keeps main-page thumbnails stable even when socket fetch is delayed or fails.
            if hasattr(self, '_log_open_trace'):
                try:
                    self._log_open_trace(study_uid, 'MainPageThumbnailRequested')
                except Exception:
                    pass
            local_payload = self._build_cached_thumbnail_payload(study_uid)
            _local_thumbs = len(local_payload.get('thumbnails', []) or [])
            # Bugfix 44113 — when the server now reports MORE series than the local
            # thumbnail cache holds, the fast-cache path would pin the stale (partial)
            # thumbnails forever. Skip it ONCE this session and fall through to the
            # server thumbnail fetch below (which pulls every series). The once-per-
            # session marker lets the study settle back onto the fast cache afterwards
            # and tolerates a benign server/series count mismatch.
            _server_series = 0
            _thumbs_grew = False
            try:
                _server_series = int(getattr(self, '_server_series_count_by_study', {}).get(study_uid_str, 0) or 0)
                if not hasattr(self, '_thumbs_server_refreshed_uids'):
                    self._thumbs_server_refreshed_uids = set()
                # Key the "already refreshed once" marker by the server's series COUNT,
                # not just the study UID. Otherwise the first refresh pins the study
                # forever and a later server-side growth (more series added) is never
                # picked up on re-click — the stale partial cache is served indefinitely
                # (the exact "thumbnails don't refresh when the server changed" symptom).
                # With the count in the key, an unchanged study still hits the fast cache
                # (same key → skip), but a grown study gets a fresh key → one refetch.
                _refresh_key = f"{study_uid_str}@{_server_series}"
                if study_uid_str and _refresh_key not in self._thumbs_server_refreshed_uids:
                    if _server_series > 0 and _server_series > _local_thumbs:
                        _thumbs_grew = True
                        self._thumbs_server_refreshed_uids.add(_refresh_key)
            except Exception:
                _thumbs_grew = False
            if hasattr(self, '_log_open_trace'):
                try:
                    self._log_open_trace(study_uid, 'right_panel_cache_gate',
                                         local_thumbs=_local_thumbs, server_series=_server_series,
                                         grew=int(_thumbs_grew))
                except Exception:
                    pass
            if local_payload.get('thumbnails') and not _thumbs_grew:
                if hasattr(self, '_is_active_patient_selection') and not self._is_active_patient_selection(patient_id, study_uid):
                    return
                self.display_thumbnails(local_payload.get('thumbnails', []), progressive=False)
                self._right_panel_render_study_uid = study_uid_str
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'ThumbnailCacheHit', thumbnail_count=len(local_payload.get('thumbnails', [])))
                    self._log_open_trace(study_uid, 'right_panel_cache_hit', thumbnail_count=len(local_payload.get('thumbnails', [])))
                # SHADOW: the sidebar rendered from the local cache — the model
                # reaches THUMBS_READY for this study (telemetry only).
                _lc_shadow_note('note_series_set', study_uid, local_payload.get('thumbnails', []))
                _lc_shadow_note('note_thumbs_rendered', study_uid)
                return
            if hasattr(self, '_log_open_trace'):
                try:
                    self._log_open_trace(study_uid, 'ThumbnailCacheMiss', local_thumbs=_local_thumbs, server_series=_server_series)
                except Exception:
                    pass

            # Prevent rapid retry storms for the same study when server/socket is degraded.
            retry_block_until = getattr(self, '_right_panel_retry_block_until', None)
            if retry_block_until is None:
                retry_block_until = {}
                self._right_panel_retry_block_until = retry_block_until
            block_until = float(retry_block_until.get(study_uid_str, 0.0) or 0.0)
            now_mono = time.monotonic()
            if block_until > now_mono:
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(
                        study_uid,
                        'right_panel_retry_blocked',
                        patient_id=patient_id,
                        retry_after_ms=round((block_until - now_mono) * 1000.0, 1),
                    )
                return

            # DB mode without thumbnail files: stop here to avoid unnecessary socket dependency.
            # NOTE: Do not gate on check_study_complete(study_uid) here.
            # A study may be marked complete while thumbnail cache is missing; in that case
            # we still need to fetch thumbnails from the server.
            if self.source_of_patient_load == SourceOfPatientLoad.DB:
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_cache_miss_local_mode')
                db_cache_miss = True

            # Server request only if not cached
            thumbnails = None

            try:
                from modules.viewer.fast.ui_throttle import should_defer_noncritical_open_network

                if self._is_open_flow_thumbnail_deferral_allowed(study_uid) and should_defer_noncritical_open_network(
                    first_series_visible=self._is_first_series_visible_for_study(study_uid)
                ):
                    self._defer_patient_studies_refresh(patient_info)
                    _logger.info(
                        "[FAST-OPEN-GATE] deferred right-panel remote thumbnails study=%s until first series visible",
                        study_uid,
                    )
                    return
            except Exception:
                pass

            try:
                server = self.data_access_panel_widget.get_server_selected()
                if not server:
                    if not db_cache_miss:
                        QMessageBox.warning(self, "Server Error", "No PACS server selected. Please select a server first.")
                    elif hasattr(self, '_log_open_trace'):
                        self._log_open_trace(study_uid, 'right_panel_no_server_after_db_cache_miss')
                    return

                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_socket_start', host=server.get('host'))
                emit_ui_event(
                    _logger,
                    "THUMBNAIL_FETCH_STARTED",
                    background=True,
                    study_uid=str(study_uid),
                    token=int(request_token),
                )

                def _fetch_in_background() -> dict | None:
                    host = server.get('host') or server.get('socket_host')
                    from modules.network.socket_config import get_socket_server_settings
                    port = int((get_socket_server_settings() or {}).get('port') or server.get('socket_port') or 50052)
                    if not host:
                        return None

                    def _normalize_payload(data_obj: dict | None) -> dict | None:
                        if not data_obj or not isinstance(data_obj, dict):
                            return None
                        out = {
                            'patient_name': data_obj.get('patient_name') or patient_info.get('PatientName', ''),
                            'patient_id': data_obj.get('patient_id') or patient_id,
                            'study_date': data_obj.get('study_date') or '',
                            # Never trust server-returned study UID for local save routing.
                            # Use the requested study UID to avoid cross-study thumbnail mixing.
                            'study_uid': str(study_uid),
                            'thumbnails': [],
                        }
                        series_items = (
                            data_obj.get('series_thumbnails')
                            or data_obj.get('series')
                            or data_obj.get('thumbnails')
                            or []
                        )
                        if isinstance(series_items, dict):
                            series_items = list(series_items.values())
                        for series in series_items:
                            if not isinstance(series, dict):
                                continue
                            series_uid = (
                                series.get('series_uid')
                                or series.get('series_instance_uid')
                                or series.get('SeriesInstanceUID')
                                or ''
                            )
                            series_number = (
                                series.get('series_number')
                                or series.get('SeriesNumber')
                                or ''
                            )
                            series_description = (
                                series.get('series_description')
                                or series.get('SeriesDescription')
                                or ''
                            )
                            modality = series.get('modality') or series.get('Modality') or ''
                            image_count = (
                                series.get('image_count')
                                or series.get('ImageCount')
                                or series.get('number_of_images')
                                or 0
                            )
                            thumbnail_data = (
                                series.get('thumbnail_data')
                                or series.get('thumbnail_base64')
                                or series.get('thumbnailBase64')
                                or series.get('thumbnailData')
                                or series.get('image_data')
                                or series.get('imageBase64')
                                or ''
                            )
                            out['thumbnails'].append({
                                'series_uid': series_uid,
                                'series_number': str(series_number),
                                'series_description': str(series_description),
                                'modality': str(modality),
                                'image_count': int(image_count or 0),
                                'thumbnail_path': series.get('thumbnail_path', ''),
                                'thumbnail_data': thumbnail_data,
                            })
                        return out if out.get('thumbnails') else None

                    # Endpoint timeout must cover server-side base64 thumbnail encoding for large studies.
                    # 12s was too aggressive for slower servers and caused right-panel to stay blank.
                    client = PatientListSocketClient(host=host, port=port, timeout=30)
                    try:
                        # Request base64 thumbnail images on the first call so every series
                        # card renders a real image preview. A metadata-only response leaves
                        # the cards as "Series N" placeholders. The 45 s asyncio timeout
                        # above still bounds a slow or unresponsive server.
                        data = client.get_study_thumbnails(
                            study_uid,
                            include_base64=True,
                            include_image_data=False,
                        )
                        out = _normalize_payload(data)

                        if not out:
                            # Some deployments expose richer series payload via QuerySeriesThumbnails.
                            data = client.query_series_thumbnails(
                                study_uid=study_uid,
                                patient_id=patient_id,
                            )
                            out = _normalize_payload(data)

                        if not out:
                            # Last fallback: some servers surface series payload under GetStudyInfo.
                            data = client.get_study_info(study_uid)
                            out = _normalize_payload(data)

                        if not out:
                            # Final attempt with base64 thumbnails (slow server path, kept for parity).
                            data = client.get_study_thumbnails(
                                study_uid,
                                include_base64=True,
                                include_image_data=False,
                            )
                            out = _normalize_payload(data)

                        return out
                    finally:
                        client.disconnect()

                _fetch_t0 = time.perf_counter()
                thumbnails = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_in_background),
                    timeout=45.0,
                )
                emit_ui_event(
                    _logger,
                    "THUMBNAIL_FETCH_COMPLETED",
                    background=True,
                    duration_ms=float((time.perf_counter() - _fetch_t0) * 1000.0),
                    study_uid=str(study_uid),
                    token=int(request_token),
                    has_data=bool(thumbnails),
                )

                _token_matches = (
                    int(getattr(self, "_thumbnail_fetch_token", 0)) == int(request_token)
                    and str(getattr(self, "_thumbnail_fetch_study_uid", "")) == str(study_uid)
                )
                if not _token_matches:
                    _still_active = bool(
                        hasattr(self, '_is_active_patient_selection')
                        and self._is_active_patient_selection(patient_id, study_uid)
                    )
                    if _resolve_stale_thumbnail_action(
                        _token_matches, _still_active, _LIFECYCLE_THUMBS_ACTIVE
                    ) == "discard":
                        emit_ui_event(
                            _logger,
                            "THUMBNAIL_FETCH_STALE_DISCARDED",
                            study_uid=str(study_uid),
                            token=int(request_token),
                        )
                        # SHADOW: legacy discards this result. Record that the model
                        # still holds the study PARKED (the Problem #1 evidence).
                        _lc_shadow_note('note_discard', study_uid, 'stale_token')
                        return
                    # CUTOVER (AIPACS_LIFECYCLE_THUMBS_ACTIVE=1): this token-stale
                    # result is still for the ACTIVE selection — render it instead of
                    # dropping (the A->B->A fix). The _is_active_patient_selection
                    # guard immediately before display_thumbnails is unchanged, so
                    # cross-patient safety is preserved.
                    _logger.info(
                        "[LIFECYCLE-CUTOVER] rendered token-stale ACTIVE thumbnail result "
                        "study=%s (legacy would_discard=1)", study_uid,
                    )

                if thumbnails:
                    retry_block_until.pop(study_uid_str, None)
                    thumbnails = self.save_thumbnail(thumbnails)

                    if thumbnails and 'thumbnails' in thumbnails:
                        self.save_series_info_to_database(study_uid, thumbnails['thumbnails'])
                        # Clear cache to ensure fresh data
                        clear_study_cache(study_uid)
                        if hasattr(self, '_log_open_trace'):
                            self._log_open_trace(study_uid, 'right_panel_socket_done', thumbnail_count=len(thumbnails['thumbnails']))
                else:
                    fallback_payload = self._build_cached_thumbnail_payload(study_uid)
                    if fallback_payload.get('thumbnails'):
                        retry_block_until.pop(study_uid_str, None)
                        thumbnails = fallback_payload
                        if hasattr(self, '_log_open_trace'):
                            self._log_open_trace(study_uid, 'right_panel_socket_empty_fallback_cache', thumbnail_count=len(fallback_payload.get('thumbnails', [])))
                    else:
                        retry_block_until[study_uid_str] = time.monotonic() + 2.5
                        if hasattr(self, '_log_open_trace'):
                            self._log_open_trace(study_uid, 'right_panel_socket_empty')

            except Exception as socket_error:
                retry_block_until[study_uid_str] = time.monotonic() + 2.5
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_socket_error', level='error', error=str(socket_error))
                # Was print() — duplicates the _log_open_trace path above but
                # also lands in app.log with stack so a regression like the
                # 2026-05-27 GetStudyInfo stall has a stack-trace record.
                _logger.error(
                    "Socket thumbnail error (study_uid=%r): %s",
                    study_uid, socket_error, exc_info=True,
                )

                fallback_payload = self._build_cached_thumbnail_payload(study_uid)
                if fallback_payload.get('thumbnails'):
                    retry_block_until.pop(study_uid_str, None)
                    thumbnails = fallback_payload
                    if hasattr(self, '_log_open_trace'):
                        self._log_open_trace(study_uid, 'right_panel_socket_error_fallback_cache', thumbnail_count=len(fallback_payload.get('thumbnails', [])))
                else:
                    thumbnails = None

            if not thumbnails:
                # Last-resort fallback: build study-specific placeholder rows from series metadata
                # so the sidebar never goes fully blank when thumbnail image bytes are unavailable.
                try:
                    study_info = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._get_or_fetch_series_info,
                            study_uid,
                            patient_id,
                            False,
                        ),
                        timeout=30.0,
                    )
                except Exception:
                    study_info = None

                series_items = []
                if isinstance(study_info, dict):
                    raw_series = study_info.get('series') or study_info.get('series_thumbnails') or []
                    if isinstance(raw_series, list):
                        series_items = [s for s in raw_series if isinstance(s, dict)]

                if series_items:
                    thumbnails = {
                        'study_uid': str(study_uid),
                        'thumbnails': [],
                    }
                    for idx, series in enumerate(series_items):
                        series_number = (
                            series.get('series_number')
                            or series.get('SeriesNumber')
                            or str(idx + 1)
                        )
                        thumbnails['thumbnails'].append(
                            {
                                'series_uid': series.get('series_uid') or series.get('series_instance_uid') or '',
                                'series_number': str(series_number),
                                'series_description': series.get('series_description') or series.get('SeriesDescription') or f'Series {series_number}',
                                'modality': series.get('modality') or series.get('Modality') or 'Unknown',
                                'image_count': int(series.get('image_count') or series.get('ImageCount') or 0),
                                'thumbnail_path': '',
                                'thumbnail_data': '',
                            }
                        )
                    if hasattr(self, '_log_open_trace'):
                        self._log_open_trace(
                            study_uid,
                            'right_panel_series_placeholder_fallback',
                            thumbnail_count=len(thumbnails.get('thumbnails', [])),
                        )

            if thumbnails:
                if hasattr(self, '_is_active_patient_selection') and not self._is_active_patient_selection(patient_id, study_uid):
                    # SHADOW: legacy abandons a COMPLETED fetch because the patient
                    # is no longer active. Record that the model retains it parked.
                    _lc_shadow_note('note_discard', study_uid, 'inactive_patient')
                    return
                if hasattr(self, '_log_open_trace'):
                    t_items = thumbnails.get('thumbnails', []) if isinstance(thumbnails, dict) else []
                    with_file_path = 0
                    with_inline_data = 0
                    for t in t_items:
                        if not isinstance(t, dict):
                            continue
                        if str(t.get('file_path') or t.get('thumbnail_path') or '').strip():
                            with_file_path += 1
                        if t.get('thumbnail_data') or t.get('thumbnail_base64') or t.get('thumbnailBase64') or t.get('thumbnailData') or t.get('image_data') or t.get('imageBase64'):
                            with_inline_data += 1
                    self._log_open_trace(
                        study_uid,
                        'right_panel_display_input',
                        thumbnail_count=len(t_items),
                        with_file_path=with_file_path,
                        with_inline_data=with_inline_data,
                    )
                self.display_thumbnails(thumbnails.get('thumbnails', []), progressive=False)
                self._right_panel_render_study_uid = study_uid_str
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_display_done', thumbnail_count=len(thumbnails.get('thumbnails', [])))
                # SHADOW: sidebar rendered from the server fetch — model reaches
                # THUMBS_READY for this study (telemetry only).
                _lc_shadow_note('note_series_set', study_uid, thumbnails.get('thumbnails', []))
                _lc_shadow_note('note_thumbs_rendered', study_uid)
            else:
                # All socket fetches and fallbacks failed — reset the stuck "Loading..."
                # label so the sidebar does not freeze in a loading state when the
                # server is unreachable.
                try:
                    if hasattr(self, 'right_panel_widget') and hasattr(self.right_panel_widget, 'count_label'):
                        self.right_panel_widget.count_label.setText('0 series')
                except Exception:
                    pass

        except Exception as e:
            if 'study_uid' in locals() and hasattr(self, '_log_open_trace'):
                self._log_open_trace(study_uid, 'right_panel_error', level='error', error=str(e))
            print(f"Error in show_patient_studies: {str(e)}")
            raise
        finally:
            try:
                if str(getattr(self, '_right_panel_fetch_inflight_uid', '') or '') == str(patient_info.get('StudyInstanceUID') or ''):
                    self._right_panel_fetch_inflight_uid = ''
            except Exception:
                pass

    def get_search_data(self):
        """Get search data from PatientSearchWidget"""
        return self.patient_search_widget.get_search_data()

    def clear_search_fields(self):
        """Clear all search fields"""
        self.patient_search_widget.clear_search_fields()

    def set_search_data(self, data):
        """Set search field values"""
        self.patient_search_widget.set_search_data(data)

    def has_search_criteria(self):
        """Check if any search criteria has been entered"""
        return self.patient_search_widget.has_search_criteria()

    def get_search_summary(self):
        """Get a summary of the current search criteria"""
        return self.patient_search_widget.get_search_summary()

    def validate_search_data(self):
        """Validate the search data for common format issues"""
        return self.patient_search_widget.validate_search_data()

    def clear_patient_table(self):
        """Clear all data from the patient table"""
        self.patient_table_widget.clear_table()

    def get_selected_patient_data(self):
        """Get data from the currently selected row in the patient table"""
        return self.patient_table_widget.get_selected_patient_data()

    def get_patient_data_by_row(self, row):
        """Get patient data from a specific row in the patient table"""
        return self.patient_table_widget.get_patient_data_by_row(row)

    def get_all_patient_data(self):
        """Get all patient data from the table"""
        return self.patient_table_widget.get_all_patient_data()

    def search_in_patient_table(self, search_text, column_index=None):
        """Search for text in the patient table"""
        return self.patient_table_widget.search_in_table(search_text, column_index)

    def highlight_patient_rows(self, row_indices):
        """Highlight specific rows in the patient table"""
        self.patient_table_widget.highlight_rows(row_indices)

    def get_patient_table_row_count(self):
        """Get the number of rows in the patient table"""
        return self.patient_table_widget.get_row_count()

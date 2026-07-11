"""Patient search service for HomePanelWidget.

Encapsulates local-DB and server (Socket) async search logic that was
previously inlined in HomePanelWidget.  Each public method is an
``async`` coroutine designed to run on the qasync event loop.

v2.2.8 architecture refactor.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QMessageBox
import qtawesome as qta

from PacsClient.utils import search_patients_local
from modules.offline_cloud_server.service import list_offline_cloud_studies
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.structured_logging import emit_download_event

if TYPE_CHECKING:
    from .home_ui import HomePanelWidget


_logger = logging.getLogger(__name__)

# Progressive Local-Search rendering is ON by default (render the first batch,
# lazy-load the rest on scroll). Escape hatch: AIPACS_PROGRESSIVE_LOCAL_SEARCH=0
# restores the legacy "render every row up front" path.
import os as _os


def _progressive_local_enabled() -> bool:
    return _os.environ.get("AIPACS_PROGRESSIVE_LOCAL_SEARCH", "").strip().lower() not in (
        "0", "false", "off",
    )


_LOCAL_SEARCH_BATCH = 100


# ── OPT-24 (2026-07-11): patient-search client-side waste removal ──────────────
# MEASURED (2026-07-11 logs): the ~5 s patient-list latency is SERVER-side —
# [NET_TIMING] endpoint=GetPatientList server_wait_ms=5016..5941 transfer_ms=0-1
# parse_ms=0, while a patient_id lookup on the SAME socket returns in 139 ms.
# The client cannot remove that. But our side was adding avoidable work to EVERY
# search, which is what these flags fix:
#   * test_connection() pre-flight = a FULL extra GetPatientList round-trip
#     (~125 ms). ~140 of 215 server calls in one session were just these probes.
#   * socket_service.cleanup() after each search closed all 5 pooled connections,
#     so the connection pool never actually pooled anything.
#   * the socket config FILE was rewritten to disk on each search (111 writes).
# Each is independently kill-switchable; all default ON.
def _env_on(name: str, default: str = "1") -> bool:
    return (_os.environ.get(name, default) or default).strip() != "0"


# How long a successful search lets us trust connectivity without re-probing.
_CONNECTIVITY_TTL_S = 300.0
# (OPT-24 shipped 2026-07-11 — see master plan §15.)


class HomeSearchService:
    """Async patient search (local + Socket server).

    The service borrows UI references from *home* (the owning
    ``HomePanelWidget``) so that it can update the progress bar,
    connection indicator, and patient table while searches run.

    Usage::

        svc = HomeSearchService(home_widget)
        asyncio.create_task(svc.search_local())
        asyncio.create_task(svc.search_server())
    """

    def __init__(self, home: "HomePanelWidget") -> None:
        self._home = home

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @property
    def _cancelled(self) -> bool:
        return self._home._cancel_search_requested

    def _thread_pool(self) -> ThreadPoolExecutor:
        return self._home.thread_pool

    # ── OPT-24b: connectivity freshness (avoids a probe round-trip per search) ──
    def _connectivity_is_fresh(self) -> bool:
        """True when a recent search proved the socket server is reachable."""
        try:
            import time as _t
            return _t.monotonic() < float(getattr(self, "_conn_ok_until", 0.0) or 0.0)
        except Exception:
            return False

    def _mark_connectivity(self, ok: bool) -> None:
        try:
            import time as _t
            self._conn_ok_until = (_t.monotonic() + _CONNECTIVITY_TTL_S) if ok else 0.0
        except Exception:
            pass

    # ── OPT-24d: one-shot enrich-cost A/B probe (diagnostic, no behaviour change) ──
    def _maybe_probe_enrich_cost(self, loop, socket_service, socket_params, search_ms: float) -> None:
        """Once per process, re-run the SAME query with include_study_count=False and
        log its server time next to the real search's, to settle whether the ~5 s is
        the per-patient ENRICHMENT or the date+modality SCAN.

        Fire-and-forget, off the UI thread, result discarded. Never raises.
        Kill switch: AIPACS_SEARCH_ENRICH_PROBE=0.
        """
        try:
            if not _env_on("AIPACS_SEARCH_ENRICH_PROBE"):
                return
            if getattr(self.__class__, "_enrich_probe_done", False):
                return
            if not socket_params or not socket_params.get("include_study_count"):
                return
            self.__class__._enrich_probe_done = True

            probe_params = dict(socket_params)
            probe_params["include_study_count"] = False

            def _probe() -> None:
                import time as _t
                t0 = _t.perf_counter()
                try:
                    rows = socket_service.search_patients_sync(probe_params)
                    enrich_ms = (_t.perf_counter() - t0) * 1000.0
                    saved = search_ms - enrich_ms
                    verdict = (
                        "ENRICHMENT is the cost -> lazy-enrich + background backfill is worth building"
                        if saved > 1000.0 else
                        "SCAN is the cost (not enrichment) -> needs a SERVER-side index; no client fix helps"
                    )
                    _logger.warning(
                        "[SEARCH-ENRICH-PROBE] with_study_count_ms=%.0f without_study_count_ms=%.0f "
                        "delta_ms=%.0f rows=%d -> %s",
                        search_ms, enrich_ms, saved, len(rows or []), verdict,
                    )
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("[SEARCH-ENRICH-PROBE] failed: %s", exc)

            loop.run_in_executor(self._thread_pool(), _probe)
        except Exception:
            pass

    @staticmethod
    def _backfill_missing_patient_fields(patients: list[dict] | None) -> list[dict]:
        """Backfill missing local-study fields away from the UI thread."""
        if not patients:
            return patients or []

        from PacsClient.utils.db_manager import find_study_pk_with_study_uid, update_study_missing_fields

        for patient in patients:
            try:
                study_uid = patient.get('study_uid')
                study_path = patient.get('study_path')
                if not study_path and study_uid:
                    study_path = str(SOURCE_PATH / study_uid)
                    patient['study_path'] = study_path

                modality = patient.get('modality')
                study_date = patient.get('study_date')
                if modality not in (None, '', 'Unknown') and study_date not in (None, '', 'Unknown'):
                    continue
                if not study_path:
                    continue

                HomeSearchService._backfill_modality_date(
                    patient,
                    study_path,
                    study_uid,
                    find_study_pk_with_study_uid,
                    update_study_missing_fields,
                )
            except Exception:
                continue

        return patients

    @staticmethod
    def _normalize_sort_date(value: object) -> str:
        """Return YYYYMMDD-like sortable string; unknown dates go to the end."""
        if value is None:
            return "99999999"
        s = str(value).strip()
        if not s:
            return "99999999"
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 8:
            return digits[:8]
        return "99999999"

    @staticmethod
    def _normalize_sort_time(value: object) -> str:
        """Return HHMMSS-like sortable string; unknown times default to start-of-day."""
        if value is None:
            return "000000"
        s = str(value).strip()
        if not s:
            return "000000"
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 6:
            return digits[:6]
        if len(digits) == 4:
            return digits + "00"
        if len(digits) == 2:
            return digits + "0000"
        return "000000"

    @classmethod
    def _sort_studies_by_date_time_ascending(cls, studies: list[dict] | None) -> list[dict]:
        """Default order for patient list: earliest study date/time first."""
        if not studies:
            return studies or []

        def _date_value(item: dict) -> object:
            return (
                item.get('study_date')
                or item.get('latest_study_date')
                or item.get('date')
            )

        def _time_value(item: dict) -> object:
            return (
                item.get('study_time')
                or item.get('latest_study_time')
                or item.get('time')
            )

        return sorted(
            studies,
            key=lambda item: (
                cls._normalize_sort_date(_date_value(item)),
                cls._normalize_sort_time(_time_value(item)),
            ),
        )

    # ------------------------------------------------------------------
    # Local DB search
    # ------------------------------------------------------------------

    async def search_local(self) -> None:
        """Search the local database — cancellable, chunk-based UI update."""
        home = self._home
        loop = asyncio.get_running_loop()
        home._cancel_search_requested = False

        try:
            home.show_loading("Local Search", "Searching local database...", cancellable=True)
            home.search_progress.setVisible(True)
            home.search_progress.setRange(0, 0)
            home._update_connection_indicator_by_status('busy', 'Searching local database...')

            home.patient_table_widget.clear_table()
            QApplication.processEvents()
            await asyncio.sleep(0)

            # Build search criteria
            search_data = home.patient_search_widget.get_search_data()
            search_data_local = search_data.copy()

            # For local search, always ignore date filters so all matching local studies are returned.
            search_data_local['date_from'] = None
            search_data_local['date_to'] = None

            # Patient ID search is GLOBAL (2026-06-06): same contract as the
            # server path — ignore modality checkboxes and name when an ID
            # is given, so the ID always finds the patient.
            if str(search_data_local.get('patient_id') or '').strip():
                search_data_local['modality'] = []
                search_data_local['patient_name'] = None

            patients = await loop.run_in_executor(self._thread_pool(), search_patients_local, search_data_local)

            if patients:
                patients = await loop.run_in_executor(
                    self._thread_pool(),
                    self._backfill_missing_patient_fields,
                    patients,
                )
                patients = await loop.run_in_executor(
                    self._thread_pool(),
                    self._sort_studies_by_date_time_ascending,
                    patients,
                )

            if self._cancelled:
                raise asyncio.CancelledError()

            total = len(patients or [])
            home.search_progress.setRange(0, max(1, total))
            home.search_progress.setValue(0)

            if patients:
                from PacsClient.pacs.patient_tab.utils.utils import has_subfolders, THUMBNAIL_PATH
                from PacsClient.utils.db_manager import find_study_pk_with_study_uid

                # Render exactly ONE study row; returns True if a row was added
                # (False = skipped: no DICOM/thumbnails on disk). Shared by the
                # progressive path AND the legacy render-all path so the
                # path-resolution + skip filtering lives in one place.
                def render_one(patient):
                    study_path = patient.get('study_path')
                    study_uid = patient.get('study_uid')

                    _need_fallback = False
                    if not study_path:
                        _need_fallback = True
                    elif study_uid:
                        try:
                            if not Path(study_path).exists():
                                _need_fallback = True
                        except Exception:
                            _need_fallback = True

                    if _need_fallback and study_uid:
                        try:
                            fallback_path = SOURCE_PATH / study_uid
                            if fallback_path.exists() and has_subfolders(fallback_path):
                                study_path = str(fallback_path)
                                patient['study_path'] = study_path
                                study_pk = find_study_pk_with_study_uid(study_uid)
                                if study_pk:
                                    from database.manager import force_update_study_path
                                    force_update_study_path(study_pk, study_path)
                        except Exception:
                            pass

                    if not study_path and study_uid:
                        study_path = str(SOURCE_PATH / study_uid)
                    if not study_path:
                        return False

                    _has_dicom = False
                    try:
                        _has_dicom = has_subfolders(study_path)
                    except Exception:
                        pass
                    if not _has_dicom:
                        _thumb_dir = THUMBNAIL_PATH / study_uid if study_uid else None
                        if not (_thumb_dir and _thumb_dir.exists() and any(_thumb_dir.iterdir())):
                            return False

                    home.add_data2patient_list_table(
                        patient_id=patient.get('patient_id'),
                        patient_name=patient.get('patient_name'),
                        study_date=patient.get('study_date'),
                        description=patient.get('study_description'),
                        modality=patient.get('modality'),
                        study_uid=patient.get('study_uid'),
                        series_count=patient.get('number_of_series'),
                        images_count=patient.get('number_of_instances'),
                        is_downloaded=True,
                        body_part=patient.get('body_part'),
                        study_time=patient.get('study_time'),
                        age=patient.get('age'),
                    )
                    return True

                if _progressive_local_enabled() and total > _LOCAL_SEARCH_BATCH:
                    # PROGRESSIVE: render the first batch immediately and lazy-
                    # load the rest on scroll — no per-row UI freeze, scales to
                    # very large local databases. The buffer is reversed to
                    # DISPLAY (date-descending = newest-first) order so the first
                    # batch is the newest studies (matches the table's default
                    # date-desc sort). Subsequent batches load on scroll-near-end.
                    patients_display = list(reversed(patients))
                    home.search_progress.setVisible(False)
                    home.patient_table_widget.load_progressive(
                        patients_display, render_one, _LOCAL_SEARCH_BATCH
                    )
                else:
                    # LEGACY: render every row up front, chunked + yielding so the
                    # UI stays responsive (small result sets, or gate off via
                    # AIPACS_PROGRESSIVE_LOCAL_SEARCH=0).
                    CHUNK = 10
                    home.patient_table_widget.begin_bulk_insert()
                    try:
                        for i, patient in enumerate(patients, start=1):
                            if self._cancelled:
                                raise asyncio.CancelledError()
                            render_one(patient)
                            if (i % CHUNK == 0) or (i == total):
                                home.patient_table_widget.end_bulk_insert()
                                home.search_progress.setValue(i)
                                await asyncio.sleep(0)
                                if i != total:
                                    home.patient_table_widget.begin_bulk_insert()
                    finally:
                        home.patient_table_widget.end_bulk_insert()

            home._update_connection_indicator_by_status('online', f'Local DB - Found {total} studies')

        except asyncio.CancelledError:
            try:
                home.search_progress.setVisible(False)
                home._update_connection_indicator_by_status('busy', 'Local Search Cancelled')
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(home, "Error", f"Error in local search: {str(e)}")
        finally:
            home.search_progress.setVisible(False)
            home.hide_loading()
            home.patient_search_widget.set_searching_state(False)

    # ------------------------------------------------------------------
    # Server (Socket) search
    # ------------------------------------------------------------------

    def _maybe_switch_profile_and_restart(self, home, server) -> bool:
        """Multi-server: if *server* is a DIFFERENT center than the active profile,
        set it active and restart.

        The clinical database, the download engine (subprocess) and the per-server
        data folder all resolve the ACTIVE profile at startup. A live "half switch"
        (repointing only the in-memory socket) makes the patient list show the new
        center but the download subprocess still binds to the OLD active profile —
        so downloads fail ("Failed to fetch metadata") or land in the wrong data
        folder. A proper switch therefore requires a restart.

        Returns True if the switch flow was triggered (caller must stop).
        """
        try:
            from PacsClient.utils import server_profiles as _sp
            if not _sp.server_profiles_enabled():
                return False
            prof = _sp.find_profile_for_server(server)
            if not prof or prof.id == _sp.get_active_profile_id():
                return False  # unknown, or same center — normal live search
            reply = QMessageBox.question(
                home, "Switch Server",
                f"Switch to {prof.display_name}?\n\nAI-PACS will reload to load "
                f"{prof.display_name}'s patients, downloads and its own data folder. "
                f"This takes a few seconds.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return True  # declined — do NOT perform a half-switch search
            _sp.set_active_profile_id(prof.id)
            # Controlled in-app reload: spawn a fresh instance (single-instance
            # takeover replaces this one) so the new center's data root, DB,
            # download engine and module endpoints rebind cleanly — the user does
            # NOT have to close + reopen manually.
            self._relaunch_application()
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
            return True
        except Exception as exc:
            print(f"[home] profile switch failed: {exc}")
            return False

    @staticmethod
    def _relaunch_application() -> None:
        """Spawn a fresh AI-PACS instance, then the caller quits this one.

        Single-instance takeover means the new process replaces the old, so the
        user gets a clean reload (data root / DB / download engine / endpoints all
        rebind to the newly-active server) without manually closing the app. Works
        for both the frozen build and the source run; never raises.
        """
        import os
        import sys
        try:
            from PySide6.QtCore import QProcess
            if getattr(sys, "frozen", False):
                QProcess.startDetached(sys.executable, list(sys.argv[1:]))
            else:
                script = os.path.abspath(sys.argv[0]) if sys.argv else ""
                args = [script, *sys.argv[1:]] if script else list(sys.argv)
                QProcess.startDetached(sys.executable, args, os.getcwd())
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[home] relaunch failed (user can reopen manually): {exc}")

    async def search_server(self) -> None:
        """Search the remote PACS via Socket — cancellable."""
        home = self._home
        loop = asyncio.get_running_loop()
        home._cancel_search_requested = False
        # Re-entrancy guard (2026-06-08, crash fix): `_cancelled` reads the shared
        # `home._cancel_search_requested`, which every search resets to False at
        # entry. So when a 2nd search starts while the 1st is still populating the
        # table (the loops below yield via `await asyncio.sleep(0)`), the 1st
        # search stopped seeing cancellation and kept calling add_patient_data on a
        # table the 2nd had already clear_table()'d → freed Qt cell-widget →
        # native access violation in patient_table_widget.add_patient_data. A
        # monotonic generation token lets a superseded population stop before
        # touching the (re)cleared table.
        home._search_generation = int(getattr(home, '_search_generation', 0)) + 1
        _my_search_gen = home._search_generation

        try:
            server = home.data_access_panel_widget.get_server_selected()
            if server and server.get("server_type") == "offline_cloud":
                home.source_of_patient_load = "offline_cloud"
                search_data = home.patient_search_widget.get_search_data()
                home.show_loading(
                    "Offline Cloud Search",
                    f"Reading studies from {server.get('name', 'Offline Cloud Server')}...",
                    cancellable=True,
                )
                home.patient_table_widget.clear_table()
                home.search_progress.setVisible(True)
                home.search_progress.setRange(0, 0)

                studies = await loop.run_in_executor(
                    self._thread_pool(),
                    lambda: list_offline_cloud_studies(server, search_data),
                )
                studies = await loop.run_in_executor(
                    self._thread_pool(),
                    self._sort_studies_by_date_time_ascending,
                    studies,
                )
                if self._cancelled:
                    raise asyncio.CancelledError()

                total = len(studies or [])
                home.search_progress.setRange(0, max(1, total))
                home.patient_table_widget.begin_bulk_insert()
                try:
                    for i, study in enumerate(studies or [], start=1):
                        if self._cancelled or home._search_generation != _my_search_gen:
                            raise asyncio.CancelledError()
                        home.add_data2patient_list_table(
                            patient_id=study.get("patient_id"),
                            patient_name=study.get("patient_name"),
                            study_date=study.get("study_date"),
                            study_time=study.get("study_time"),
                            description=study.get("description"),
                            modality=study.get("modality"),
                            study_uid=study.get("study_uid"),
                            series_count=study.get("series_count"),
                            images_count=study.get("images_count"),
                            body_part=study.get("body_part"),
                            report_status=study.get("report_status") or "pending",
                        )
                        home.search_progress.setValue(i)
                        if (i % 25 == 0) or (i == total):
                            home.patient_table_widget.end_bulk_insert()
                            await asyncio.sleep(0)
                            if i != total:
                                home.patient_table_widget.begin_bulk_insert()
                finally:
                    home.patient_table_widget.end_bulk_insert()

                if total:
                    home._update_connection_indicator_by_status(
                        "online",
                        f"Offline Cloud - Found {total} studies",
                        str(server.get("folder_path") or ""),
                    )
                else:
                    home._update_connection_indicator_by_status(
                        "busy",
                        "Offline Cloud - No studies found",
                        str(server.get("folder_path") or ""),
                    )
                return

            if not server or not all(k in server for k in ('host', 'port')):
                QMessageBox.warning(home, "Server Not Selected", "Please select a PACS server first.")
                return

            # Multi-server: selecting a DIFFERENT center is a deliberate switch.
            # The database, download engine and data folder all bind to the active
            # profile at STARTUP, so a live half-switch (socket only) downloads from
            # the wrong server / writes to the wrong data root. Set it active and
            # restart instead.
            if self._maybe_switch_profile_and_restart(home, server):
                return

            from modules.network.socket_config import update_socket_server_settings, get_socket_server_settings
            # Multi-server: use the SELECTED server's own socket port when server
            # profiles are enabled; otherwise keep the historical single global
            # socket port (byte-identical legacy behaviour when the feature is off).
            from PacsClient.utils.server_profiles import server_profiles_enabled, socket_port_for_server
            if server_profiles_enabled():
                socket_port = socket_port_for_server(server)
            else:
                socket_port = get_socket_server_settings()['port']
            update_socket_server_settings(host=server['host'], port=int(socket_port))

            server_name = server.get('name', server['host'])
            home.show_loading("Socket Server Search",
                              f"Searching {server_name} server via Socket...",
                              cancellable=True)

            # Keep current rows visible while the socket request is in-flight.
            # This avoids visible blank/flicker when server responses are slow.
            home.search_progress.setVisible(True)
            home.search_progress.setRange(0, 0)

            from modules.network.socket_patient_service import get_socket_patient_service
            socket_service = get_socket_patient_service()

            def _show_conn_failed() -> None:
                cfg = socket_service.config
                config_info = f"{cfg.get_socket_host()}:{cfg.get_socket_port()}"
                home._update_connection_indicator_by_status('offline', 'Socket Connection Failed', config_info)
                QMessageBox.critical(home, "Connection Failed",
                                     f"Failed to connect to Socket server at {config_info}")

            # OPT-24b: the pre-flight probe is NOT a cheap ping — test_connection()
            # does client.connect() + get_patient_list_safe(limit=1), i.e. a FULL extra
            # GetPatientList round-trip (~125 ms) before EVERY search. Skip it while
            # connectivity is FRESH (a recent search succeeded). We still probe on the
            # first search of a session, and AFTER an empty result, because
            # search_patients_sync() returns [] for BOTH "no patients" and "connection
            # dead" — so an empty result cannot be trusted without a probe.
            # Kill switch: AIPACS_SEARCH_SKIP_PROBE=0 -> probe every search (legacy).
            _probed = False
            if (not _env_on("AIPACS_SEARCH_SKIP_PROBE")) or (not self._connectivity_is_fresh()):
                _probed = True
                is_connected = await loop.run_in_executor(self._thread_pool(), socket_service.test_connection)
                if self._cancelled:
                    raise asyncio.CancelledError()
                if not is_connected:
                    self._mark_connectivity(False)
                    _show_conn_failed()
                    return
                self._mark_connectivity(True)

            search_data = home.patient_search_widget.get_search_data()
            socket_params = self._convert_search_data_to_socket_params(search_data)

            import time as _time
            _t_search0 = _time.perf_counter()
            patients = await loop.run_in_executor(
                self._thread_pool(),
                lambda: socket_service.search_patients_sync(socket_params),
            )
            _search_ms = (_time.perf_counter() - _t_search0) * 1000.0

            # Empty result while the probe was SKIPPED -> disambiguate "no patients"
            # from "connection dead" (the service returns [] for both).
            if (not patients) and (not _probed):
                still_ok = await loop.run_in_executor(self._thread_pool(), socket_service.test_connection)
                self._mark_connectivity(bool(still_ok))
                if not still_ok:
                    _show_conn_failed()
                    return
            elif patients:
                self._mark_connectivity(True)

            # OPT-24d [SEARCH-PERF]: the one line that tells us where the time went.
            # `search_ms` here is essentially all server_wait (transfer+parse are ~0),
            # so compare it against the enrich A/B probe below.
            try:
                _logger.info(
                    "[SEARCH-PERF] search_ms=%.0f rows=%d probed=%s params=%s",
                    _search_ms, len(patients or []), _probed,
                    {k: v for k, v in (socket_params or {}).items() if k != 'offset'},
                )
            except Exception:
                pass

            patients = await loop.run_in_executor(
                self._thread_pool(),
                self._sort_studies_by_date_time_ascending,
                patients,
            )
            if self._cancelled:
                raise asyncio.CancelledError()

            # OPT-24d: one-shot, background A/B probe — is the server's 5 s the
            # per-patient ENRICHMENT (include_study_count) or the date+modality SCAN?
            # Re-issues the SAME query with include_study_count=False and logs its
            # server time. Runs ONCE per process, off the UI thread, result discarded
            # (no behaviour change: we do NOT drop study_count from the real search,
            # because count_of_series feeds the documented right-panel "grew" gate).
            # If enrich_ms << search_ms  -> enrichment is the cost -> lazy-enrich +
            #    background backfill is worth building (big perceived win).
            # If enrich_ms ~= search_ms  -> it is the SCAN -> server-side index needed;
            #    no client change can help. Either way we get a definitive answer.
            # Kill switch: AIPACS_SEARCH_ENRICH_PROBE=0.
            self._maybe_probe_enrich_cost(loop, socket_service, socket_params, _search_ms)

            total = len(patients or [])
            home.search_progress.setRange(0, max(1, total))

            # Rows are inserted on the UI thread; the loop yields to the event
            # loop every CHUNK rows. Smaller chunk = shorter per-batch UI freeze
            # (each batch was stalling the main thread ~700-950ms at CHUNK=25).
            CHUNK = 10
            if patients:
                # Atomic swap: clear only when fresh results are ready.
                home.patient_table_widget.clear_table()
                home.patient_table_widget.begin_bulk_insert()
                try:
                    for i, patient in enumerate(patients, start=1):
                        if self._cancelled or home._search_generation != _my_search_gen:
                            raise asyncio.CancelledError()
                        home._add_socket_patient_to_table(patient)

                        if (i % CHUNK == 0) or (i == total):
                            home.search_progress.setValue(i)
                            await asyncio.sleep(0)

                finally:
                    home.patient_table_widget.end_bulk_insert()

                home._update_connection_indicator_by_status('online', f'Socket Connected - Found {total} patients')

                # N1: post-search reporting-physician hydration.
                # GetPatientList carries only latest_study_report_status (no reporter
                # name/ID), so completed rows missing a physician name are enriched
                # asynchronously from the configurable Reception/API endpoint. Runs
                # AFTER rows are inserted/displayed; queues background, throttled,
                # cached REST lookups and never blocks the search or the UI thread.
                try:
                    home._sync_completed_reporting_physicians_after_search()
                except Exception as exc:
                    # Was a bare 'except: pass' - a silent-fail window that hid
                    # hydration trigger-call failures (N1 diagnostic finding).
                    emit_download_event(
                        _logger, 'reporter-hydration',
                        phase='trigger_call_failed',
                        error=type(exc).__name__, detail=str(exc),
                    )
                    _logger.warning(
                        '[reporter-hydration] post-search trigger call failed',
                        exc_info=True,
                    )
            else:
                # No results from current query: clear old rows and show explicit state.
                home.patient_table_widget.clear_table()
                home._update_connection_indicator_by_status('busy', 'Socket Connected - No patients found')

            # OPT-24c: do NOT tear the shared service down after every search.
            # `socket_service` is a process-wide singleton whose SocketConnectionPool
            # holds up to 5 connections — but cleanup() -> disconnect_from_server() ->
            # connection_pool.close_all() closed ALL of them after each search, so the
            # pool never actually pooled anything and the next search paid 5 fresh TCP
            # handshakes (95 pool rebuilds in one observed session).
            # Keeping it warm is SAFE: SocketConnectionPool.get_connection() validates
            # each pooled client with is_connected() and transparently discards/replaces
            # a stale one, and the pool is closed properly at app shutdown
            # (mainwindow_ui -> socket_service.cleanup()).
            # Kill switch: AIPACS_SEARCH_KEEP_POOL=0 -> cleanup after each search (legacy).
            if not _env_on("AIPACS_SEARCH_KEEP_POOL"):
                try:
                    await loop.run_in_executor(self._thread_pool(), socket_service.cleanup)
                except Exception:
                    pass

        except asyncio.CancelledError:
            try:
                home.search_progress.setVisible(False)
                home.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
                home.connection_indicator.setText(" Socket Search Cancelled")
                home.connection_indicator.setStyleSheet(
                    "QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;"
                    " background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }"
                )
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(home, "Error", f"Error searching patients: {str(e)}")
        finally:
            home.search_progress.setVisible(False)
            home.hide_loading()
            home.patient_search_widget.set_searching_state(False)

    # ------------------------------------------------------------------
    # Advanced (structured) server search — 2026-06-06
    # ------------------------------------------------------------------

    async def search_server_advanced(self, query: dict) -> None:
        """Run a structured advanced query against the PACS socket server.

        ``query`` (built by AdvancedSearchDialog, versioned for extension):
            patient_ids: list[str]   — each searched server-side, results unioned
            date_from / date_to:     — 'yyyyMMdd' or None
            modalities: list[str]
            body_part / physician:   — str (client-side refinement)
            age_min / age_max:       — int or None (client-side refinement)

        Server-side: patient_id, dates, modality (what GetPatientList accepts).
        Client-side: body part / age / physician refine rows WHEN the row
        carries that data; rows without the field are kept (the server stays
        authoritative — refinement must never silently hide everything).
        """
        home = self._home
        loop = asyncio.get_running_loop()
        home._cancel_search_requested = False
        # Re-entrancy guard (2026-06-08, crash fix): `_cancelled` reads the shared
        # `home._cancel_search_requested`, which every search resets to False at
        # entry. So when a 2nd search starts while the 1st is still populating the
        # table (the loops below yield via `await asyncio.sleep(0)`), the 1st
        # search stopped seeing cancellation and kept calling add_patient_data on a
        # table the 2nd had already clear_table()'d → freed Qt cell-widget →
        # native access violation in patient_table_widget.add_patient_data. A
        # monotonic generation token lets a superseded population stop before
        # touching the (re)cleared table.
        home._search_generation = int(getattr(home, '_search_generation', 0)) + 1
        _my_search_gen = home._search_generation

        try:
            server = home.data_access_panel_widget.get_server_selected()
            if not server or not all(k in server for k in ('host', 'port')):
                QMessageBox.warning(home, "Server Not Selected",
                                    "Advanced search runs on the PACS server — please select a server first.")
                return

            # Multi-server: selecting a DIFFERENT center is a deliberate switch.
            # The database, download engine and data folder all bind to the active
            # profile at STARTUP, so a live half-switch (socket only) downloads from
            # the wrong server / writes to the wrong data root. Set it active and
            # restart instead.
            if self._maybe_switch_profile_and_restart(home, server):
                return

            from modules.network.socket_config import update_socket_server_settings, get_socket_server_settings
            # Multi-server: use the SELECTED server's own socket port when server
            # profiles are enabled; otherwise keep the historical single global
            # socket port (byte-identical legacy behaviour when the feature is off).
            from PacsClient.utils.server_profiles import server_profiles_enabled, socket_port_for_server
            if server_profiles_enabled():
                socket_port = socket_port_for_server(server)
            else:
                socket_port = get_socket_server_settings()['port']
            update_socket_server_settings(host=server['host'], port=int(socket_port))

            home.show_loading("Advanced Search",
                              f"Searching {server.get('name', server['host'])} with advanced filters...",
                              cancellable=True)
            home.search_progress.setVisible(True)
            home.search_progress.setRange(0, 0)

            from modules.network.socket_patient_service import get_socket_patient_service
            socket_service = get_socket_patient_service()

            # OPT-24b (same as search_server): skip the extra GetPatientList probe
            # round-trip while connectivity is fresh from a recent successful search.
            if (not _env_on("AIPACS_SEARCH_SKIP_PROBE")) or (not self._connectivity_is_fresh()):
                is_connected = await loop.run_in_executor(self._thread_pool(), socket_service.test_connection)
                if self._cancelled:
                    raise asyncio.CancelledError()
                if not is_connected:
                    self._mark_connectivity(False)
                    QMessageBox.critical(home, "Connection Failed", "Failed to connect to the PACS socket server.")
                    return
                self._mark_connectivity(True)

            param_sets = self._advanced_query_to_param_sets(query)
            merged: dict = {}
            for params in param_sets:
                if self._cancelled:
                    raise asyncio.CancelledError()
                batch = await loop.run_in_executor(
                    self._thread_pool(),
                    lambda p=params: socket_service.search_patients_sync(p),
                )
                for row in batch or []:
                    key = (
                        str(row.get('patient_id') or ''),
                        str(row.get('study_uid') or row.get('latest_study_uid') or ''),
                    )
                    merged.setdefault(key, row)

            rows = [r for r in merged.values()
                    if self._row_passes_advanced_client_filters(r, query)]
            rows = await loop.run_in_executor(
                self._thread_pool(), self._sort_studies_by_date_time_ascending, rows,
            )
            if self._cancelled:
                raise asyncio.CancelledError()

            total = len(rows)
            home.search_progress.setRange(0, max(1, total))
            home.patient_table_widget.clear_table()
            if rows:
                home.patient_table_widget.begin_bulk_insert()
                try:
                    for i, patient in enumerate(rows, start=1):
                        if self._cancelled or home._search_generation != _my_search_gen:
                            raise asyncio.CancelledError()
                        home._add_socket_patient_to_table(patient)
                        if (i % 10 == 0) or (i == total):
                            home.search_progress.setValue(i)
                            await asyncio.sleep(0)
                finally:
                    home.patient_table_widget.end_bulk_insert()
                home._update_connection_indicator_by_status(
                    'online', f'Advanced search - Found {total} result(s)')
                try:
                    home._sync_completed_reporting_physicians_after_search()
                except Exception:
                    pass
            else:
                home._update_connection_indicator_by_status(
                    'busy', 'Advanced search - No results')

        except asyncio.CancelledError:
            pass
        except Exception as e:
            QMessageBox.critical(home, "Error", f"Advanced search failed: {str(e)}")
        finally:
            home.search_progress.setVisible(False)
            home.hide_loading()
            home.patient_search_widget.set_searching_state(False)

    @staticmethod
    def _advanced_query_to_param_sets(query: dict) -> list:
        """Expand an advanced query into one socket param dict per server call.

        The socket GetPatientList accepts a single patient_id per request, so
        N patient IDs become N calls (bounded) whose results are unioned.
        """
        base = {
            "limit": 100,
            "offset": 0,
            "include_study_count": True,
            "include_latest_study": True,
        }
        if query.get('date_from'):
            base['date_from'] = query['date_from']
        if query.get('date_to'):
            base['date_to'] = query['date_to']
        if query.get('modalities'):
            base['modality'] = list(query['modalities'])

        ids = [str(p).strip() for p in (query.get('patient_ids') or []) if str(p).strip()]
        ids = ids[:20]  # bounded fan-out
        if not ids:
            return [base]
        param_sets = []
        for pid in ids:
            params = dict(base)
            params['patient_id'] = pid
            param_sets.append(params)
        return param_sets

    @staticmethod
    def _row_passes_advanced_client_filters(row: dict, query: dict) -> bool:
        """Client-side refinement for fields the server cannot filter.

        Conservative contract: a filter only EXCLUDES a row when the row
        actually carries the field and it does not match. Missing data keeps
        the row (never silently hide results the server returned).
        """
        if not isinstance(row, dict):
            return True

        def _first_text(*keys):
            for k in keys:
                v = row.get(k)
                if v not in (None, ''):
                    return str(v)
            return ''

        body_part = str(query.get('body_part') or '').strip().lower()
        if body_part:
            value = _first_text('body_part', 'BodyPart', 'body_part_examined',
                                'BodyPartExamined').strip().lower()
            if value and body_part not in value:
                return False

        physician = str(query.get('physician') or '').strip().lower()
        if physician:
            value = _first_text('radiologist_name', 'reporting_physician',
                                'reporting_physician_name', 'radiologist',
                                'referring_physician', 'physician').strip().lower()
            if value and physician not in value:
                return False

        age_min = query.get('age_min')
        age_max = query.get('age_max')
        if age_min is not None or age_max is not None:
            raw_age = _first_text('patient_age', 'age', 'PatientAge')
            age_years = HomeSearchService._parse_dicom_age_years(raw_age)
            if age_years is not None:
                if age_min is not None and age_years < int(age_min):
                    return False
                if age_max is not None and age_years > int(age_max):
                    return False

        return True

    @staticmethod
    def _parse_dicom_age_years(raw: str):
        """'042Y' / '42' / '006M' → years (float) or None when unparsable."""
        text = str(raw or '').strip().upper()
        if not text:
            return None
        try:
            if text.endswith('Y'):
                return float(text[:-1])
            if text.endswith('M'):
                return float(text[:-1]) / 12.0
            if text.endswith('W'):
                return float(text[:-1]) / 52.0
            if text.endswith('D'):
                return float(text[:-1]) / 365.0
            return float(text)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_search_data_to_socket_params(search_data: dict) -> dict:
        """Map UI search data dict to Socket API parameter dict.

        When searching by Patient ID the lookup is GLOBAL (2026-06-06):
        - Use exact match (no wildcards)
        - Ignore date filters AND date presets
        - Ignore modality checkboxes (previously still applied — the
          reported bug: an ID search returned nothing unless the patient's
          modality happened to be ticked)
        - Ignore patient name (ID is authoritative)
        - Keep normal list limit so all studies for that patient return
        """
        # Lazy-enrich probe (2026-06-09): a broad (100-row) result takes ~17s
        # server-side; the cost is the per-patient enrichment. `include_study_count`
        # makes the server count series across ALL of each patient's studies — the
        # suspected dominant cost — and it only feeds a thumbnail-cache HINT
        # (count_of_series/total_studies), so it is safe to defer. `include_latest_study`
        # is KEPT because the row needs latest_study_uid to be openable.
        # Flag default OFF = current behavior; AIPACS_SEARCH_LAZY_ENRICH=1 drops
        # study_count so we can measure the speedup before building the background fill.
        # Limit knob (default 100 = unchanged). Set AIPACS_SEARCH_LIMIT to a smaller
        # value to measure whether a CAPPED small page avoids the ~16s full-page
        # server cost (decides whether "load 20, then the rest" pagination helps).
        import os as _os
        try:
            _limit = int(_os.getenv("AIPACS_SEARCH_LIMIT", "100"))
        except Exception:
            _limit = 100
        socket_params = {
            "limit": _limit,
            "offset": 0,
            "include_study_count": True,
            "include_latest_study": True,
        }

        if str(search_data.get('patient_id') or '').strip():
            socket_params['patient_id'] = str(search_data['patient_id']).strip()
            # Global ID lookup: no dates, no modality, no name.
            return socket_params

        # Non-ID searches: include date filters
        if search_data.get('date_from'):
            socket_params['date_from'] = search_data['date_from']
        if search_data.get('date_to'):
            socket_params['date_to'] = search_data['date_to']

        if search_data.get('patient_name'):
            socket_params['patient_name'] = search_data['patient_name']
        if search_data.get('modality'):
            socket_params['modality'] = search_data['modality']

        return socket_params

    @staticmethod
    def _backfill_modality_date(patient: dict, study_path: str, study_uid: str,
                                find_study_pk_fn, update_fn) -> None:
        """Backfill missing modality/date from first DICOM on disk."""
        try:
            _sp = Path(study_path)
            _first_dcm = None
            for _sub in sorted(_sp.iterdir()):
                if _sub.is_dir():
                    for _f in sorted(_sub.iterdir()):
                        if _f.suffix.lower() in ('.dcm', '.dicom'):
                            _first_dcm = _f
                            break
                if _first_dcm:
                    break
            if not _first_dcm:
                return

            import pydicom
            _ds = pydicom.dcmread(str(_first_dcm), stop_before_pixels=True, force=True)

            _mod = patient.get('modality')
            _date = patient.get('study_date')
            if _mod in (None, '', 'Unknown'):
                raw = _ds.get('Modality', None)
                if raw:
                    patient['modality'] = str(raw)
            if _date in (None, '', 'Unknown'):
                raw = _ds.get('StudyDate', None)
                if raw:
                    patient['study_date'] = str(raw)

            if study_uid:
                _s_pk = find_study_pk_fn(study_uid)
                if _s_pk:
                    update_fn(
                        _s_pk,
                        modality=patient.get('modality') if patient.get('modality') not in (None, '', 'Unknown') else None,
                        study_date=patient.get('study_date') if patient.get('study_date') not in (None, '', 'Unknown') else None,
                    )
        except Exception:
            pass

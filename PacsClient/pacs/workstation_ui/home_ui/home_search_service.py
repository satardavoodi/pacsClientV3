"""Patient search service for HomePanelWidget.

Encapsulates local-DB and server (Socket) async search logic that was
previously inlined in HomePanelWidget.  Each public method is an
``async`` coroutine designed to run on the qasync event loop.

v2.2.8 architecture refactor.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QMessageBox
import qtawesome as qta

from PacsClient.utils import search_patients_local
from modules.offline_cloud_server.service import list_offline_cloud_studies
from PacsClient.utils.config import SOURCE_PATH

if TYPE_CHECKING:
    from .home_ui import HomePanelWidget


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
            
            # When searching by Patient ID, always ignore date filters (Patient ID is unique)
            # Otherwise, drop date filters for local search (local DB should return all local studies)
            search_data_local['date_from'] = None
            search_data_local['date_to'] = None

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

            CHUNK = 25
            added = 0
            skipped = 0

            if patients:
                from PacsClient.pacs.patient_tab.utils.utils import has_subfolders
                from PacsClient.utils.db_manager import find_study_pk_with_study_uid

                home.patient_table_widget.begin_bulk_insert()
                try:
                    for i, patient in enumerate(patients, start=1):
                        if self._cancelled:
                            raise asyncio.CancelledError()

                        study_path = patient.get('study_path')
                        study_uid = patient.get('study_uid')

                        # Fallback path resolution
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

                        if not study_path:
                            if study_uid:
                                study_path = str(SOURCE_PATH / study_uid)
                        if not study_path:
                            skipped += 1
                            continue

                        _has_dicom = False
                        try:
                            _has_dicom = has_subfolders(study_path)
                        except Exception:
                            pass
                        if not _has_dicom:
                            from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
                            _thumb_dir = THUMBNAIL_PATH / study_uid if study_uid else None
                            if not (_thumb_dir and _thumb_dir.exists() and any(_thumb_dir.iterdir())):
                                skipped += 1
                                continue

                        _disp_modality = patient.get('modality')
                        _disp_date = patient.get('study_date')

                        home.add_data2patient_list_table(
                            patient_id=patient.get('patient_id'),
                            patient_name=patient.get('patient_name'),
                            study_date=_disp_date,
                            description=patient.get('study_description'),
                            modality=_disp_modality,
                            study_uid=patient.get('study_uid'),
                            series_count=patient.get('number_of_series'),
                            images_count=patient.get('number_of_instances'),
                            is_downloaded=True,
                            body_part=patient.get('body_part'),
                            study_time=patient.get('study_time'),
                            age=patient.get('age'),
                        )
                        added += 1

                        if (i % CHUNK == 0) or (i == total):
                            home.patient_table_widget.end_bulk_insert()
                            home.search_progress.setValue(i)
                            QApplication.processEvents()
                            await asyncio.sleep(0)
                            if i != total:
                                home.patient_table_widget.begin_bulk_insert()
                finally:
                    home.patient_table_widget.end_bulk_insert()

            home._update_connection_indicator_by_status('online', f'Local DB - Found {added} studies')

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

    async def search_server(self) -> None:
        """Search the remote PACS via Socket — cancellable."""
        home = self._home
        loop = asyncio.get_running_loop()
        home._cancel_search_requested = False

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
                            QApplication.processEvents()
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

            from modules.network.socket_config import update_socket_server_settings, get_socket_server_settings
            socket_port = get_socket_server_settings()['port']
            update_socket_server_settings(host=server['host'], port=int(socket_port))

            server_name = server.get('name', server['host'])
            home.show_loading("Socket Server Search",
                              f"Searching {server_name} server via Socket...",
                              cancellable=True)

            home.patient_table_widget.clear_table()
            home.search_progress.setVisible(True)
            home.search_progress.setRange(0, 0)

            from modules.network.socket_patient_service import get_socket_patient_service
            socket_service = get_socket_patient_service()

            is_connected = await loop.run_in_executor(self._thread_pool(), socket_service.test_connection)
            if self._cancelled:
                raise asyncio.CancelledError()

            if not is_connected:
                cfg = socket_service.config
                config_info = f"{cfg.get_socket_host()}:{cfg.get_socket_port()}"
                home._update_connection_indicator_by_status('offline', 'Socket Connection Failed', config_info)
                QMessageBox.critical(home, "Connection Failed",
                                     f"Failed to connect to Socket server at {config_info}")
                return

            search_data = home.patient_search_widget.get_search_data()
            socket_params = self._convert_search_data_to_socket_params(search_data)

            patients = await loop.run_in_executor(
                self._thread_pool(),
                lambda: socket_service.search_patients_sync(socket_params),
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

            CHUNK = 25
            if patients:
                home.patient_table_widget.begin_bulk_insert()
                try:
                    for i, patient in enumerate(patients, start=1):
                        if self._cancelled:
                            raise asyncio.CancelledError()
                        home._add_socket_patient_to_table(patient)

                        if (i % CHUNK == 0) or (i == total):
                            home.patient_table_widget.end_bulk_insert()
                            home.search_progress.setValue(i)
                            QApplication.processEvents()
                            await asyncio.sleep(0)
                            if i != total:
                                home.patient_table_widget.begin_bulk_insert()

                finally:
                    home.patient_table_widget.end_bulk_insert()

                home._update_connection_indicator_by_status('online', f'Socket Connected - Found {total} patients')
            else:
                home._update_connection_indicator_by_status('busy', 'Socket Connected - No patients found')

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
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_search_data_to_socket_params(search_data: dict) -> dict:
        """Map UI search data dict to Socket API parameter dict.
        
        When searching by Patient ID:
        - Use exact match (no wildcards)
        - Ignore date filters (Patient ID is unique)
        - Set limit=1 to get the exact match
        """
        socket_params = {
            "limit": 100,
            "offset": 0,
            "include_study_count": True,
            "include_latest_study": True,
        }
        
        # When searching by Patient ID, use exact match and ignore dates
        if search_data.get('patient_id'):
            socket_params['patient_id'] = search_data['patient_id']
            # For Patient ID search, limit to 1 result (exact match expected)
            socket_params['limit'] = 1
            # Patient ID is unique, so ignore date filters entirely
        else:
            # For other searches, include date filters
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

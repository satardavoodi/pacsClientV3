"""Study/series save: save complete study info, series info DB/server"""
# Auto-generated from home_ui.py — Phase 3 split

import logging as _logging
import time
import traceback

# Redirect print() to logger to avoid synchronous console I/O on Windows.
# Console writes cost 1-5ms each and block the calling thread.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))

from PacsClient.utils import get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.db_manager import get_study_by_study_uid
from modules.network.socket_client import PatientListSocketClient
from modules.offline_cloud_server.service import export_studies_to_offline_cloud, get_all_offline_cloud_servers, list_offline_cloud_studies, record_offline_cloud_sync_event, sync_offline_cloud_study_preview_to_local, sync_offline_cloud_study_to_local, validate_offline_cloud_package

# Per-process record of (host, port) servers whose GetStudyInfo endpoint is
# unresponsive. The GetStudyInfo probe in get_series_info_from_server has a 3s
# timeout; on servers that never answer it, that 3s is wasted on EVERY study
# before the queue/Download-Manager path falls back to GetStudyThumbnails.
# After the first timeout the server is recorded here and the probe is skipped
# for the rest of the session. Cleared on restart, so a fixed server re-probes.
_GETSTUDYINFO_UNSUPPORTED = set()


class _HPStudySaveMixin:
    """Study/series save: save complete study info, series info DB/server"""

    def _fetch_study_thumbnails_from_socket(
        self,
        study_uid: str,
        *,
        include_base64: bool,
        include_image_data: bool,
    ):
        server = self.data_access_panel_widget.get_server_selected()
        if not server:
            return None

        host = server.get('host') or server.get('socket_host')
        from modules.network.socket_config import get_socket_server_settings
        port = int((get_socket_server_settings() or {}).get('port') or server.get('socket_port') or 50052)
        if not host:
            return None

        client = PatientListSocketClient(host=host, port=port, timeout=30)
        try:
            return client.get_study_thumbnails(
                study_uid,
                include_base64=include_base64,
                include_image_data=include_image_data,
            )
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def save_series_info_to_database(self, study_uid: str, series_thumbnails: list):
        """Save series info from gRPC response (delegates to service)."""
        return self.db_service.save_series_info_to_database(study_uid, series_thumbnails)

    def get_series_info_from_server(self, study_uid: str, patient_id: str = None):
        """
        Get detailed series information from PACS server using gRPC

        Args:
            study_uid: Study Instance UID
            patient_id: Patient ID (optional)

        Returns:
            dict: Series information or None if error
        """
        try:
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                return None

            if server.get("server_type") == "offline_cloud":
                sync_result = sync_offline_cloud_study_preview_to_local(
                    server,
                    study_uid,
                    actor=self._current_actor_identity(),
                )
                if not sync_result.get("ok"):
                    return None
                study_data = get_study_by_study_uid(study_uid)
                if not study_data:
                    return None
                from PacsClient.utils.db_manager import get_study_info_with_series
                return get_study_info_with_series(study_uid)

            # Prefer lightweight metadata endpoint first. This avoids oversized
            # thumbnail payloads that can exceed socket response limits.
            host = server.get('host') or server.get('socket_host')
            from modules.network.socket_config import get_socket_server_settings
            port = int((get_socket_server_settings() or {}).get('port') or server.get('socket_port') or 50052)
            if host and (host, port) not in _GETSTUDYINFO_UNSUPPORTED:
                # Keep this probe SHORT (3s): the GetStudyInfo endpoint is unsupported
                # on some PACS deployments and never responds — a long timeout stalls
                # the whole patient-open -> Download Manager path. Fail fast here, then
                # fall back to the reliable GetStudyThumbnails endpoint below.
                # If it times out, the server is added to _GETSTUDYINFO_UNSUPPORTED
                # so later studies skip this dead 3s probe entirely.
                client = PatientListSocketClient(host=host, port=port, timeout=3)
                _probe_started = time.monotonic()
                info_data = None
                try:
                    info_data = client.get_study_info(study_uid)
                except Exception:
                    info_data = None
                finally:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                _probe_elapsed = time.monotonic() - _probe_started

                if info_data:
                    raw_series = (
                        info_data.get('series')
                        or info_data.get('series_list')
                        or info_data.get('series_thumbnails')
                        or []
                    )
                    series_items = raw_series if isinstance(raw_series, list) else []

                    study_info = {
                        'study_uid': info_data.get('study_instance_uid') or info_data.get('study_uid') or study_uid,
                        'patient_id': info_data.get('patient_id') or patient_id or '',
                        'patient_name': info_data.get('patient_name') or '',
                        'study_date': info_data.get('study_date') or '',
                        'study_time': info_data.get('study_time') or '',
                        'study_description': info_data.get('study_description') or info_data.get('description') or '',
                        'count_of_series': int(
                            info_data.get('count_of_series')
                            or info_data.get('total_series')
                            or len(series_items)
                        ),
                        'thumbnails_available': bool(info_data.get('thumbnails_available', True)),
                        'series': [],
                    }

                    for series in series_items:
                        if not isinstance(series, dict):
                            continue
                        study_info['series'].append({
                            'series_uid': str(series.get('series_uid') or series.get('series_instance_uid') or ''),
                            'series_number': str(series.get('series_number') or ''),
                            'series_description': str(series.get('series_description') or ''),
                            'modality': str(series.get('modality') or ''),
                            'image_count': int(series.get('image_count') or 0),
                            'protocol_name': str(series.get('protocol_name') or ''),
                            'body_part_examined': str(series.get('body_part_examined') or series.get('BodyPartExamined') or ''),
                            'manufacturer': str(series.get('manufacturer') or ''),
                            'institution_name': str(series.get('institution_name') or ''),
                        })

                    if study_info['series']:
                        return study_info

                # GetStudyInfo yielded no usable series. If the call was slow it
                # almost certainly timed out — record this server so subsequent
                # studies skip the dead 3s probe and go straight to the
                # GetStudyThumbnails fallback below.
                if _probe_elapsed >= 2.5:
                    _GETSTUDYINFO_UNSUPPORTED.add((host, port))
                    _print_logger.info(
                        "[series-info] GetStudyInfo unresponsive on %s:%s (%.1fs) — "
                        "skipping that probe for the rest of this session",
                        host, port, _probe_elapsed,
                    )

            response = self._fetch_study_thumbnails_from_socket(
                study_uid,
                include_base64=False,
                include_image_data=False,
            )
            if not response:
                # Some servers return series only when base64 thumbnail payload is requested.
                response = self._fetch_study_thumbnails_from_socket(
                    study_uid,
                    include_base64=True,
                    include_image_data=False,
                )
            if (not response) and host:
                client = PatientListSocketClient(host=host, port=port, timeout=30)
                try:
                    response = client.query_series_thumbnails(study_uid=study_uid, patient_id=patient_id)
                finally:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
            if not response:
                return None

            # Extract study information
            study_info = {
                'study_uid': response.get('study_instance_uid') or study_uid,
                'patient_id': response.get('patient_id') or patient_id or '',
                'patient_name': response.get('patient_name') or '',
                'study_date': response.get('study_date') or '',
                'study_time': response.get('study_time') or '',
                'study_description': response.get('study_description') or '',
                'count_of_series': int(
                    response.get('count_of_series')
                    or response.get('total_series')
                    or len(response.get('series_thumbnails') or response.get('series') or [])
                ),
                'thumbnails_available': bool(response.get('thumbnails_available', True)),
                'series': []
            }

            # Extract series information
            for series in (response.get('series_thumbnails') or response.get('series') or []):
                if not isinstance(series, dict):
                    continue
                series_info = {
                    'series_uid': str(series.get('series_uid') or series.get('series_instance_uid') or ''),
                    'series_number': str(series.get('series_number') or ''),
                    'series_description': str(series.get('series_description') or ''),
                    'modality': str(series.get('modality') or ''),
                    'image_count': int(series.get('image_count') or 0),
                    'protocol_name': str(series.get('protocol_name') or ''),
                    'body_part_examined': str(series.get('body_part_examined') or series.get('BodyPartExamined') or ''),
                    'manufacturer': str(series.get('manufacturer') or ''),
                    'institution_name': str(series.get('institution_name') or '')
                }
                study_info['series'].append(series_info)
            if not study_info['series']:
                return None
            return study_info

        except Exception as e:
            print(f"Error getting series info: {str(e)}")
            return None

    def get_series_info_from_database(self, study_uid: str, series_number: str):
        """Get series info from database (delegates to service)."""
        return self.db_service.get_series_info_from_database(study_uid, series_number)

    def save_complete_study_info(self, study_uid: str, patient_id: str = None, study_info: dict = None):
        """
        Get complete study and series information and save to database

        Args:
            study_uid: Study Instance UID
            patient_id: Patient ID (optional)
            study_info: Pre-fetched study info (optional, to avoid double fetch)
        """
        try:
            print(f"[SAVE_COMPLETE] Starting to save study {study_uid}...")
            print(f"[SAVE_COMPLETE] study_info provided: {study_info is not None}")

            # Get detailed information from server only if not provided
            if not study_info:
                print(f"[SAVE_COMPLETE] Fetching from server...")
                study_info = self.get_series_info_from_server(study_uid, patient_id)
                print(f"[SAVE_COMPLETE] Server returned: {study_info}")
            else:
                print(f"[SAVE_COMPLETE] Using cached study_info")
            
            if not study_info:
                print(f"[SAVE_COMPLETE] ❌ No study_info available")
                return False

            # Validate required fields
            patient_id_val = study_info.get('patient_id')
            patient_name_val = study_info.get('patient_name')
            
            if not patient_id_val:
                print(f"[SAVE_COMPLETE] ❌ Missing patient_id in study_info")
                print(f"[SAVE_COMPLETE] Available keys: {study_info.keys()}")
                return False
            
            if not patient_name_val:
                patient_name_val = 'Unknown Patient'
                print(f"[SAVE_COMPLETE] ⚠️ Missing patient_name, using default")

            print(f"[SAVE_COMPLETE] Patient: {patient_name_val} ({patient_id_val})")

            # Save study information if not exists
            print(f"[SAVE_COMPLETE] Looking for existing patient...")
            patient_pk = find_patient_pk(patient_id_val)
            if not patient_pk:
                print(f"[SAVE_COMPLETE] Creating new patient record...")
                # Create patient record
                patient_pk = insert_patient(
                    patient_id=patient_id_val,
                    name=patient_name_val,
                    birth_date=None,
                    sex=None,
                    age=None,
                    patient_weight=None
                )
                print(f"[SAVE_COMPLETE] ✓ Created patient (pk={patient_pk})")
            else:
                print(f"[SAVE_COMPLETE] ✓ Found existing patient (pk={patient_pk})")

            # Check if study exists
            print(f"[SAVE_COMPLETE] Looking for existing study...")
            study_pk = find_study_pk_with_study_uid(study_uid)
            if not study_pk:
                static_data: dict = study_info['series'][0] if study_info.get('series') else {}
                study_path = SOURCE_PATH / study_uid
                study_path.mkdir(parents=True, exist_ok=True)

                print(f"[SAVE_COMPLETE] Creating new study record...")
                # Create study record
                study_pk = insert_study(
                    study_uid=study_uid,
                    patient_fk=patient_pk,
                    study_date=study_info.get('study_date', ''),
                    study_time=study_info.get('study_time', ''),  # Add study_time
                    study_description=study_info.get('study_description', ''),
                    institution_name=static_data.get('institution_name', None),
                    modality=static_data.get('modality', None),
                    body_part=static_data.get('body_part_examined', None),
                    number_of_series=study_info.get('count_of_series', len(study_info.get('series', []))),
                    number_of_instances=sum(s.get('image_count', 0) for s in study_info.get('series', [])),
                    study_path=str(study_path)
                )
                print(f"[SAVE_COMPLETE] ✓ Created study record (pk={study_pk}) at {study_path}")
            else:
                print(f"[SAVE_COMPLETE] ✓ Found existing study (pk={study_pk})")
                # Update study_path if it doesn't exist
                from PacsClient.utils.db_manager import update_study_missing_fields
                study_path = SOURCE_PATH / study_uid
                study_path.mkdir(parents=True, exist_ok=True)
                update_study_missing_fields(
                    study_pk,
                    study_path=str(study_path),
                    study_date=study_info.get('study_date', ''),
                    study_time=study_info.get('study_time', ''),
                    number_of_series=study_info.get('count_of_series', len(study_info.get('series', []))),
                    number_of_instances=sum(s.get('image_count', 0) for s in study_info.get('series', []))
                )
                print(f"✅ Updated study record with study_path: {study_path}")

            # Save series information
            saved_series = 0
            print(f"[SAVE_SERIES] Saving {len(study_info.get('series', []))} series...")
            for series in study_info.get('series', []):
                try:
                    # Check if series exists
                    series_uid = series.get('series_uid', '')
                    if not series_uid:
                        print(f"[SAVE_SERIES] ⚠️ Skipping series with no UID")
                        continue
                    
                    series_number = series.get('series_number', 'unknown')
                    print(f"[SAVE_SERIES] Processing series {series_number}...")
                        
                    existing_series_pk = find_series_pk(series_uid)
                    if existing_series_pk:
                        print(f"[SAVE_SERIES] ✓ Series {series_number} already in database (pk={existing_series_pk})")
                        continue

                    # Build series path
                    series_path_name = str(series.get('series_path_name') or series_number)
                    series_path = SOURCE_PATH / study_uid / series_path_name
                    series_path.mkdir(parents=True, exist_ok=True)

                    # Create series record with full information
                    series_pk = insert_series(
                        series_uid=series_uid,
                        study_fk=study_pk,
                        series_name=f"Series {series_number}",
                        series_number=str(series_number),
                        series_description=series.get('series_description', ''),
                        modality=series.get('modality', ''),
                        image_count=series.get('image_count', 0),
                        protocol_name=series.get('protocol_name', ''),
                        body_part_examined=series.get('body_part_examined', ''),
                        manufacturer=series.get('manufacturer', ''),
                        institution_name=series.get('institution_name', ''),
                        main_thumbnail=False,  # Will be updated when thumbnails are saved
                        thumbnail_path=None,
                        series_path=str(series_path)
                    )

                    saved_series += 1
                    print(f"[SAVE_SERIES] ✅ Saved series {series_number} (pk={series_pk})")
                    
                    # ===== SAVE INSTANCES FOR THIS SERIES =====
                    print(f"[SAVE_INSTANCES] Processing instances for series {series_number}...")
                    try:
                        from pathlib import Path
                        import natsort
                        from PacsClient.utils.database import insert_instances_batch
                        
                        # Get instances from disk
                        instance_count = series.get('image_count', 0)
                        print(f"[SAVE_INSTANCES] Series {series_number} has {instance_count} images in metadata")
                        
                        # Scan series directory for DICOM files
                        series_path = SOURCE_PATH / study_uid / series_path_name
                        dicom_files = sorted([
                            f for f in series_path.glob('*.dcm') if f.is_file()
                        ], key=lambda x: natsort.natsort_keygen()(x.name))
                        
                        print(f"[SAVE_INSTANCES] Found {len(dicom_files)} DICOM files on disk for series {series_number}")
                        
                        if dicom_files:
                            instances_to_save = []
                            for idx, dcm_file in enumerate(dicom_files):
                                try:
                                    from pydicom import dcmread
                                    dcm = dcmread(str(dcm_file))
                                    
                                    # Extract instance information
                                    sop_uid = getattr(dcm, 'SOPInstanceUID', f'unknown_{idx}')
                                    instance_number = getattr(dcm, 'InstanceNumber', idx + 1)
                                    rows = getattr(dcm, 'Rows', 512)
                                    columns = getattr(dcm, 'Columns', 512)
                                    
                                    # Extract window/level from DICOM tags
                                    window_width = None
                                    window_center = None
                                    try:
                                        ww = getattr(dcm, 'WindowWidth', None)
                                        wc = getattr(dcm, 'WindowCenter', None)
                                        if ww is not None and wc is not None:
                                            window_width = float(ww[0]) if hasattr(ww, '__iter__') and not isinstance(ww, str) else float(ww)
                                            window_center = float(wc[0]) if hasattr(wc, '__iter__') and not isinstance(wc, str) else float(wc)
                                    except (ValueError, TypeError, IndexError):
                                        pass
                                    
                                    instances_to_save.append({
                                        'sop_uid': str(sop_uid),
                                        'series_fk': series_pk,
                                        'instance_path': str(dcm_file),
                                        'instance_number': instance_number,
                                        'rows': rows,
                                        'columns': columns,
                                        'window_width': window_width,
                                        'window_center': window_center
                                    })
                                    
                                except Exception as dcm_err:
                                    print(f"[SAVE_INSTANCES] ⚠️ Error reading DICOM {dcm_file.name}: {dcm_err}")
                                    continue
                            
                            # Batch insert instances
                            if instances_to_save:
                                inserted = insert_instances_batch(instances_to_save)
                                print(f"[SAVE_INSTANCES] ✅ Saved {inserted} instances for series {series_number}")
                            else:
                                print(f"[SAVE_INSTANCES] ⚠️ No instances to save for series {series_number}")
                        else:
                            print(f"[SAVE_INSTANCES] ⚠️ No DICOM files found in {series_path}")
                    
                    except Exception as inst_err:
                        print(f"[SAVE_INSTANCES] ❌ Error saving instances for series {series_number}: {inst_err}")
                        import traceback
                        traceback.print_exc()

                except Exception as e:
                    print(f"[SAVE_SERIES] ❌ Error saving series {series_number}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            print(f"[SAVE_SERIES] ✅ Complete: {saved_series}/{len(study_info.get('series', []))} series saved")
            print(f"[SAVE_INSTANCES] ✅ All instances saved to database")
            return True
        except Exception as e:
            print(f"[SAVE_COMPLETE] ❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

from . import config
from . import utils
from .utils import get_server, get_all_servers, get_all_patients, search_patients_local, CallerTypes, list_files_in_folder
from .database import load_token_usage, save_token_usage
from .db_manager import get_connection_database, insert_patient, insert_study, insert_series, insert_instance, \
    find_patient_pk, find_study_pk, find_series_pk, find_instance_pk,\
    get_patient_by_patient_pk, get_patient_by_study_uid, get_studies_by_patient_pk, get_series_by_study_pk, get_instances_by_series_pk,\
    get_series_by_series_pk, update_series_thumbnail_path, get_series_thumbnail_path, find_study_pk_with_study_uid,\
    get_count_instances_in_study, get_study_by_study_uid, update_study_counts_by_uid,\
    update_patient_missing_fields, update_study_missing_fields, update_series_missing_fields,\
    update_instance_missing_fields, get_attachments_uploaded, append_attachments_uploaded, get_series_path_with_study_pk_and_series_number,\
    get_visit_status, set_visit_status, ensure_visit_status_column, get_study_info_with_series

# --- AI Chat exports (روی همان DB اصلی) ---
from .db_manager import (
    # schema
    ai_ensure_schema,

    # sessions (scoped by study)
    ai_upsert_session,
    ai_update_session_title,
    ai_set_server_sid,
    ai_get_server_sid,
    ai_fetch_sid_pairs,
    ai_fetch_sessions_by_study,           # NEW
    ai_set_last_session_for_study,        # NEW
    ai_get_last_session_for_study,        # NEW

    # messages
    ai_append_message,
    ai_update_message,
    ai_fetch_messages_full,
    ai_fetch_messages,

    # listing / last selected (global fallback)
    ai_fetch_all_sessions,
    ai_set_last_session,
    ai_get_last_session,

    # reassign / migrate
    ai_reassign_session,
    ai_reassign_sid,
)

# Reception reports (from database.py)
from .database import (
    ai_save_reception_report,
    ai_get_reception_reports,
    ai_mark_reception_report_read,
    ai_update_reception_report_status,
    ai_delete_reception_report,
    ai_get_pending_reception_reports_count,
)




from .config import ICON_PATH, IMAGES_LOGIN_PATH
"""database.core â€” backward-compatible re-export shim.

All public symbols are imported from the six domain modules.
No behaviour changes; import paths that use ``database.core`` or
``PacsClient.utils.database`` or ``database`` continue to work unchanged.

Split performed in v2.2.9.0.  See docs/refactoring/database-split.md.
"""

# â”€â”€ Pool infrastructure â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from database._pool import (  # noqa: F401
    _get_diag,
    now_ms,
    log_stage_timing,
    _local,
    _db_lock,
    _connection_pool,
    _pool_lock,
    _max_pool_size,
    logger,
    get_db_connection,
    _get_pooled_connection,
    _return_to_pool,
    _create_sqlite_connection,
    _PooledConnection,
    get_connection_database,
    cleanup_connection_pools,
)

# â”€â”€ DICOM CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from database.dicom_db import (  # noqa: F401
    init_database,
    ensure_report_status_schema,
    insert_patient,
    insert_study,
    migrate_fix_null_study_paths,
    insert_series,
    insert_instances_batch,
    insert_instance,
    deserialize_instance_metadata,
    get_all_patients,
    search_patients_local,
    get_patient_by_id,
    find_patient_pk,
    find_study_pk,
    find_study_pk_with_study_uid,
    find_series_pk,
    find_series_pk_by_number,
    find_instance_pk,
    find_instances_by_sop_uids,
    bulk_insert_instances,
    bulk_update_instances,
    get_patients_ordered_by_date,
    get_patient_storage_info,
    delete_patient_cascade,
    get_patients_by_date_range,
)

# â”€â”€ Token / transcript usage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from database.token_usage_db import (  # noqa: F401
    load_token_usage,
    save_token_usage,
    _ensure_token_usage_tables,
    add_token_usage_delta,
    _mask_api_key,
    _hash_api_key,
    _hash_and_mask_api_key,
    add_api_token_usage_delta,
    load_api_token_usage,
    load_api_token_usage_for_key,
    _ensure_transcript_usage_tables,
    add_transcript_usage_delta,
    add_api_transcript_usage_delta,
    load_api_transcript_usage_for_key,
    get_api_usage_rows,
    get_api_usage_rows_for_key,
    get_api_usage_summary_html,
)

# â”€â”€ AI sessions / messages / reports / secretary log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from database.ai_sessions_db import (  # noqa: F401
    ai_ensure_schema,
    ai_backfill_sessions_from_messages,
    ai_upsert_session,
    ai_fetch_sessions_by_study,
    ai_set_last_session_for_study,
    ai_get_last_session_for_study,
    ai_update_session_title,
    ai_set_server_sid,
    ai_get_server_sid,
    ai_fetch_sid_pairs,
    ai_append_message,
    ai_update_message,
    ai_fetch_messages_full,
    ai_fetch_messages,
    ai_reassign_session,
    ai_fetch_all_sessions,
    ai_is_pinned,
    ai_set_pinned,
    ai_toggle_pinned,
    ai_fetch_pinned_sids,
    ai_set_pinned_bulk,
    ai_delete_session_and_messages,
    ai_set_last_session,
    ai_get_last_session,
    ai_insert_report,
    ai_fetch_reports_for_session,
    ai_fetch_reports_map_for_session,
    ai_fetch_reports_for_study,
    ai_log_secretary_action_start,
    ai_log_secretary_action_end,
    ai_fetch_secretary_actions,
)

# â”€â”€ AI reception reports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from database.ai_reception_db import (  # noqa: F401
    ai_save_reception_report,
    ai_get_reception_reports,
    ai_mark_reception_report_read,
    ai_update_reception_report_status,
    ai_delete_reception_report,
    ai_get_pending_reception_reports_count,
)

# â”€â”€ Download progress tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from database.download_progress_db import (  # noqa: F401
    insert_download_progress,
    get_download_progress,
    complete_download_progress,
    delete_download_progress,
    clear_all_download_progress,
    get_all_download_progress,
    get_incomplete_downloads,
)

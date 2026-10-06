"""Present execution receipts without duplicating the visible patient table."""


def format_result(result):
    action = str(result.get('action') or '')
    message = str(result.get('message') or '').strip()
    if action == 'chitchat':
        return message or 'How can I help?'
    if result.get('error_code') == 'CONFIRM_REQUIRED':
        steps = (result.get('data') or {}).get('steps', []) if isinstance(result.get('data'), dict) else []
        labels = {'advanced_search_patients':'apply your patient search filters', 'read_patients':'check the matching studies', 'download_selection_status':'check download progress', 'select_patients':'select the requested studies', 'download_patient':'download the study',
                  'download_selection':'download the selected studies', 'media_drives':'check available disc drives',
                  'prepare_selection_media':'prepare the disc-writing job', 'write_selection_media':'write the selected studies to disc'}
        operations = [labels[step] for step in steps if isinstance(step, str) and step in labels]
        detail = 'I will ' + ', then '.join(operations) + '. ' if operations else ''
        return detail + 'Please confirm this request in the confirmation window. No action has been completed yet.'
    if not result.get('ok'):

        return message or 'I could not complete the requested action.'
    data = result.get('data')
    payload = data if isinstance(data, dict) else {}
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_MODELS
    if action in SETTINGS_CONTROL_MODELS:
        return 'The settings operation has started. I will check the actual result before reporting completion.'
    if action in ('list_patients', 'read_patients', 'advanced_search', 'search_patients'):
        if payload.get('state') in ('searching', 'pending', 'running'):
            return 'The patient search has started. Results are still loading.'
        count = payload.get('count')
        if type(count) is int and count >= 0:
            if count == 0:
                return 'The search completed. No matching studies were found.'
            return f'The search completed. {count} studies are displayed in the patient list.'
        return 'The patient list is ready on screen.'
    if action in ('release_memory', 'get_viewer_preferences', 'set_viewer_preferences', 'diagnose_resources'):
        return 'The operation has started. I will check its result before reporting completion.'
    if action == 'configure_personal_ai':
        return 'AI settings are open. Enter your personal key and prompt locally, then save and test the connection.'
    if action == 'open_settings':
        return 'The requested Settings page is open. No configuration has been changed; review and save changes locally.'
    if action == 'configure_image_quality':
        return 'The requested image settings are open. Review the controls before saving changes.'
    if action == 'request_storage_cleanup':
        return 'Review and confirm the cleanup scope in Settings. No deletion is complete yet.'
    if action == 'get_storage_cleanup_status':
        state = payload.get('state')
        if state == 'succeeded':
            return f"Cleanup completed. {payload.get('files_deleted', 0)} local files were removed."
        if state == 'completed_with_warnings':
            return 'Cleanup finished with warnings. Review the Storage report for items that could not be removed.'
        if state == 'cancelled_or_blocked':
            return 'Cleanup was cancelled or blocked by active work.'
        return 'Cleanup is still awaiting confirmation or running.'
    if action == 'settings_operation_status':
        state = payload.get('state')
        if state == 'failed':
            return payload.get('message') or 'The settings operation could not be completed.'
        if state != 'succeeded':
            return 'The settings operation is still in progress.'
        values = payload.get('data') or {}
        if payload.get('kind') == 'verify_settings_server':
            summaries = [f"Port {entry['port']}: " + ('C-ECHO succeeded' if entry.get('echo_success') else 'C-ECHO failed')
                         for entry in values.get('results', [])]
            return '; '.join(summaries) + '. No connection settings were changed.'
        if payload.get('kind') in SETTINGS_CONTROL_MODELS:
            if payload.get('kind') == 'set_voice_to_text_preferences' and values.get('saved'):
                from modules.EchoMind.voice_transcription import provider_label
                return f"Voice to Text was saved and checked: {provider_label(values['provider'])}. It applies to new recordings in EchoMind Chat and Secretary."
            if payload.get('kind') == 'verify_eagle_eye_connection':
                return 'The authenticated Eagle Eye connection passed its compatibility check. No connection settings were changed.'
            if values.get('saved'):
                if not values.get('restart_required'):
                    return 'The requested AI settings were saved and checked. They apply to new requests.'
                return 'The requested settings were saved and checked. Restart the application to refresh all Settings forms and apply them.'
            return 'The current settings have been read.'
        if payload.get('kind') == 'memory_release':
            amount = values.get('released_resident_bytes', 0) / (1024 * 1024)
            return f'Memory release completed. Application resident memory decreased by {amount:.1f} MB.'
        if payload.get('kind') == 'resources':
            free = (values.get('ram') or {}).get('available_bytes', 0) / (1024 ** 3)
            disk = (values.get('app_storage_drive') or {}).get('free_bytes', 0) / (1024 ** 3)
            return f'{free:.1f} GB RAM is available; {disk:.1f} GB is free on the application storage drive.'
        if values.get('restart_required'):
            return 'Viewer preferences were saved. Restart the application to apply them.'
        return 'The settings operation completed.'
    if action == '__workflow__':
        steps = payload.get('steps') or []
        labels = {
            'list_patients': 'updated the patient list',
            'advanced_search': 'applied the search filters',
            'sort_patients': 'sorted the patient list',
            'select_patients': 'selected the requested studies',
        }
        completed = [labels[step['tool']] for step in steps
                     if isinstance(step, dict) and step.get('ok')
                     and step.get('verified') and step.get('tool') in labels]
        if completed:
            return 'I ' + ', then '.join(completed) + '.'
        return 'The requested steps were completed.'
    if action == 'open_patient':
        return 'The requested study is open.'
    if action == 'sort_patients':
        return 'The patient list has been sorted.'
    return message or 'The requested action was completed.'


def confirmation_request(payload, confirmed):
    """A confirmation must resolve the exact pending request's session."""
    return {'text':'yes' if confirmed else 'no',
            '_preplanned':False, '_confirmation_response':True,
            'session_id':payload['session_id'],
            'source_scope':payload.get('source_scope'),
            'interaction_mode':payload.get('interaction_mode', 'act')}

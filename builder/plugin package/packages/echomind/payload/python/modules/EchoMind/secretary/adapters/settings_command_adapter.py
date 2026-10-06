"""Bounded settings actions shared by Secretary and MCP; no secret transport."""
from ..command_envelope import CommandResult
from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_MODELS

SETTINGS_ACTIONS = {name: name for name in (
    'open_settings', 'get_settings_capabilities', 'get_theme', 'set_theme',
    'diagnose_resources', 'release_memory', 'get_viewer_preferences', 'set_viewer_preferences', 'settings_operation_status', 'request_storage_cleanup',
    'get_storage_cleanup_status', 'configure_personal_ai', 'configure_image_quality')}
SETTINGS_ACTIONS.update({name:name for name in SETTINGS_CONTROL_MODELS})

SETTINGS_SECTIONS = ('server', 'viewer', 'tools', 'image_filter', 'storage',
                     'echomind', 'eagle_eye', 'agent', 'installation', 'education')


class SettingsCommandAdapter:
    def __init__(self, host_getter):
        self._get_host = host_getter

    def _result(self, plan, data=None, error=None):
        return CommandResult(ok=error is None, action=plan.action, data=data,
                             error_code=error, message={
                                 'SETTINGS_UNAVAILABLE':'Settings are not available in the current window.',
                                 'SECTION_UNAVAILABLE':'The requested settings page is not installed or available.',
                                 'INVALID_ARGUMENTS':'The requested setting or cleanup scope is invalid, or another operation is already pending.',
                                 'SETTINGS_ACTION_FAILED':'The settings operation could not be started. Review the local Settings status.'
                             }.get(error, error or ''))

    def _open(self, plan, section):
        host = self._get_host()
        if host is None:
            return self._result(plan, error='SETTINGS_UNAVAILABLE')
        if not host.open_assistant_settings(section):
            return self._result(plan, error='SECTION_UNAVAILABLE')
        return self._result(plan, {'section':section, 'state':'opened'})

    def open_settings(self, plan, state):
        return self._open(plan, plan.entities.get('section', 'viewer'))

    def get_settings_capabilities(self, plan, state):
        return self._result(plan, {'sections': list(SETTINGS_SECTIONS),
            'actions': list(SETTINGS_ACTIONS), 'credential_entry':'local_only',
            'cleanup_requires_local_confirmation':True,
            'quality_changes':'typed_scalar_settings_and_local_handoff',
            'configuration_refresh':'restart_for_existing_settings_forms_and_active_images',
            'patient_cleanup_strategies':['all','delete_oldest_count','older_than_days'],
            'memory_release':'process_working_set_only',
            'viewer_preferences':['backend','gpu_boost'],
            'company_ai_configuration':'server_owned',
            'resource_diagnosis':'ram_and_app_storage_drive'})

    def _service(self, plan, method, *args):
        host = self._get_host()
        if host is None:
            return self._result(plan, error='SETTINGS_UNAVAILABLE')
        try:
            data = getattr(host.assistant_settings_service, method)(*args)
        except ValueError:
            return self._result(plan, error='INVALID_ARGUMENTS')
        except Exception:
            # Do not echo configuration, filesystem paths or credentials.
            return self._result(plan, error='SETTINGS_ACTION_FAILED')
        return self._result(plan, data)

    def get_theme(self, plan, state):
        return self._service(plan, 'get_theme')

    def _control(self, plan, state):
        return self._service(plan, 'settings_control', plan.action, plan.entities)

    get_settings_snapshot = _control
    verify_settings_server = _control
    clone_settings_server = _control
    remove_settings_modalities = _control
    set_settings_tool_style = _control
    set_settings_filter_parameter = _control
    get_ai_settings = _control
    set_voice_to_text_preferences = _control
    set_ai_proxy_preferences = _control
    set_personal_ai_preferences = _control
    verify_eagle_eye_connection = _control
    set_eagle_eye_connection = _control

    def set_theme(self, plan, state):
        return self._service(plan, 'set_theme', plan.entities.get('theme', ''))

    def diagnose_resources(self, plan, state):
        return self._service(plan, 'diagnose_resources')

    def settings_operation_status(self, plan, state):
        return self._service(plan, 'operation_status', plan.entities.get('operation_id', ''))

    def configure_personal_ai(self, plan, state):
        result = self._open(plan, 'echomind')
        if result.ok:
            host = self._get_host()
            prepare = getattr(host, 'prepare_personal_ai_configuration', None)
            if not callable(prepare) or not prepare():
                return self._result(plan, error='SECTION_UNAVAILABLE')
            result.data.update(state='awaiting_local_input', connected=False,
                required=['personal_api_key', 'user_defined_prompt'],
                message='Enter credentials and your own prompt in the local settings form, then save and test there.')
        return result

    def configure_image_quality(self, plan, state):
        section = plan.entities.get('section', 'image_filter')
        result = self._open(plan, section)
        if result.ok:
            result.data.update(state='awaiting_local_input', changed=False,
                message='Review display or filter settings. No image data or diagnostic preset was changed.')
        return result

    def request_storage_cleanup(self, plan, state):
        result = self._open(plan, 'storage')
        if not result.ok:
            return result
        return self._service(plan, 'request_cleanup', plan.entities.get('category', 'cache'),
                             plan.entities.get('strategy'), plan.entities.get('value'))

    def get_storage_cleanup_status(self, plan, state):
        return self._service(plan, 'cleanup_status')


    def release_memory(self, plan, state):
        return self._service(plan, 'release_memory')

    def get_viewer_preferences(self, plan, state):
        return self._service(plan, 'get_viewer_preferences')

    def set_viewer_preferences(self, plan, state):
        return self._service(plan, 'set_viewer_preferences', plan.entities.get('backend'), plan.entities.get('gpu_boost'))

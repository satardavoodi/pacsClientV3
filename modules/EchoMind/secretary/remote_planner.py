"""Worker-only Secretary data transport; execution remains client-owned."""
from __future__ import annotations

from datetime import datetime
import json
from uuid import uuid4

from modules.ai_imaging.eagle_eye_remote.client import Client, ServerHTTPError
from modules.EchoMind.settings_store import get_llm_backend, get_prompt_settings
from .validator import validate_plan, validate_steps

MAX_BODY = 128 * 1024
MAX_RESPONSE = 256 * 1024
_FIELDS = {'conversation', 'modules', 'memory_context', 'invalid_plan', 'validation_errors',
           'execution_error', 'attempt', 'max_attempts', 'runtime_capabilities', 'interaction_mode', 'question_context', 'ui_image', 'session_sources'}


class RemotePlanningError(RuntimeError):
    def __init__(self, message, *, error_code='SERVER_PLANNING_FAILED', diagnostic=None):
        super().__init__(message)
        self.error_code = error_code
        from .patient_list_receipt import safe_planning_diagnostic
        self.diagnostic = safe_planning_diagnostic(diagnostic) if diagnostic is not None else None


def planning_preflight(body):
    """Pure worker preflight matching existing server schema and actual wire bytes."""
    from pydantic import ValidationError
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Request
    from modules.ai_imaging.eagle_eye_remote.secretary.session_sources import MAX_BODY as SOURCE_BODY
    from .patient_list_receipt import safe_planning_diagnostic
    descriptor={'stage':'valid','valid':True}
    try:
        descriptor['wire_bytes']=len(json.dumps(body,allow_nan=False).encode('utf-8'))
    except (ValueError,TypeError,OverflowError):
        return safe_planning_diagnostic(dict(descriptor,stage='schema',valid=False,error_type='serialization_error'))
    try:
        request=Request.model_validate(body)
    except ValidationError as error:
        first=error.errors(include_input=False,include_context=False,include_url=False)[0]
        loc=first.get('loc',())
        return safe_planning_diagnostic(dict(descriptor,stage='schema',valid=False,
            field_root=loc[0] if loc else 'unknown',error_type=first.get('type')))
    limit=SOURCE_BODY if request.session_sources else 512*1024 if request.ui_image is not None else MAX_BODY
    descriptor['limit_bytes']=limit
    if descriptor['wire_bytes']>limit:
        return safe_planning_diagnostic(dict(descriptor,stage='body_bounds',valid=False))
    if request.ui_image is not None:
        context=request.question_context.get('ui_controls',{})
        if (request.phase=='route' or not isinstance(context,dict)
                or context.get('snapshot_id')!=request.ui_image.snapshot_id
                or context.get('context_digest')!=request.ui_image.context_digest):
            return safe_planning_diagnostic(dict(descriptor,stage='ui_binding',valid=False,field_root='ui_image'))
    return safe_planning_diagnostic(descriptor)


def _require_preflight(body):
    descriptor=planning_preflight(body)
    if not descriptor['valid']:
        large=descriptor['stage']=='body_bounds'
        raise RemotePlanningError('Secretary request context is too large.' if large else
            'Secretary request context failed local validation.',
            error_code='SERVER_REQUEST_TOO_LARGE' if large else 'UI_CONTEXT_MISMATCH' if
            descriptor['stage']=='ui_binding' else 'SERVER_REQUEST_INVALID', diagnostic=descriptor)
    return descriptor


def uses_server():
    return get_llm_backend() != 'openai'


def personal_prompt(key):
    if uses_server():
        raise RemotePlanningError('Company Secretary prompts are owned by Eagle Eye Server.')
    value = str(get_prompt_settings().get(key) or '').strip()
    if not value:
        raise RemotePlanningError('Define your own Secretary prompt in personal OpenAI settings before sending.')
    return value


def memory_data(value):
    """Remove the legacy client instruction header, leaving quoted cycle data."""
    value = str(value or '')
    if value.startswith('=== CONVERSATION MEMORY ==='):
        start = value.find('--- Cycle')
        return value[start:].removesuffix('=== END MEMORY ===').strip() if start >= 0 else ''
    return value


def validate_proposal(plan):
    if plan is None:
        return None
    if not isinstance(plan, dict):
        raise RemotePlanningError('Eagle Eye returned an invalid Secretary proposal.')
    if plan.get('action') == 'unknown':
        if not isinstance(plan.get('reason'), str) or len(plan['reason']) > 2000:
            raise RemotePlanningError('Eagle Eye returned an invalid clarification.')
        from modules.ai_imaging.eagle_eye_remote.secretary.clarification import validate_clarification
        try:
            clarification = validate_clarification(plan.get('clarification'))
        except ValueError:
            raise RemotePlanningError('Eagle Eye returned invalid clarification choices.') from None
        return {'action': 'unknown', 'entities': {}, 'confidence': 0.0,
                'needs_confirmation': False, 'reason': plan['reason'],
                **({'clarification': clarification} if clarification else {})}
    if plan.get('action') == '__workflow__':
        steps = plan.get('steps')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20 or not all(isinstance(s, dict) for s in steps):
            raise RemotePlanningError('Eagle Eye returned an invalid Secretary workflow.')
        normalized, errors = validate_steps(steps)
        if errors:
            raise RemotePlanningError('Eagle Eye returned an unsupported Secretary workflow.')
        return {**plan, 'steps': normalized,
                'needs_confirmation': any(step.get('needs_confirmation') for step in normalized)}
    normalized, errors = validate_plan(plan)
    if errors or normalized is None:
        raise RemotePlanningError('Eagle Eye returned an unsupported Secretary action.')
    return normalized


def validate_runtime_proposal(plan, capabilities):
    """Server proposals may only name actions present in this request snapshot."""
    if plan is None or plan.get('action')=='unknown':
        return plan
    known = {item['action'] for item in capabilities['actions'] if item['assistant_allowed']}
    steps = plan.get('steps', []) if plan.get('action')=='__workflow__' else [plan]
    if any(step.get('action') not in known for step in steps):
        raise RemotePlanningError('Eagle Eye proposed an action unavailable on this workstation.')
    from .command_envelope import validate_action_entities
    try:
        for step in steps:
            validate_action_entities(step['action'], step.get('entities') or {})
    except (ValueError, TypeError):
        raise RemotePlanningError('Eagle Eye proposed invalid runtime action arguments.') from None
    return plan


def request(phase, text, *, language='auto', language_preference=None, timeout=90, **fields):
    from .credential_guard import contains_api_credential, LOCAL_ENTRY_MESSAGE
    if contains_api_credential(text):
        raise RemotePlanningError(LOCAL_ENTRY_MESSAGE)
    if contains_api_credential(fields.get('memory_context', '')):
        raise RemotePlanningError(LOCAL_ENTRY_MESSAGE)
    if contains_api_credential(json.dumps(fields, default=str)):
        raise RemotePlanningError(LOCAL_ENTRY_MESSAGE)
    from PySide6.QtCore import QCoreApplication, QThread
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        raise RemotePlanningError('Secretary planning must run in the background worker.')
    if phase not in ('route', 'plan', 'repair') or language not in ('fa', 'en', 'auto'):
        raise RemotePlanningError('Invalid Secretary planning phase or language.')
    if language_preference is not None and language_preference not in ('fa', 'en'):
        raise RemotePlanningError('Invalid Secretary language preference.')
    if not isinstance(text, str) or not text.strip() or len(text) > 20000 or set(fields) - _FIELDS:
        raise RemotePlanningError('Enter a Secretary request of at most 20,000 characters.')
    if 'memory_context' in fields:
        fields['memory_context'] = memory_data(fields['memory_context'])
        if len(fields['memory_context']) > 20000:
            raise RemotePlanningError('Secretary conversation memory is too large. Start a new conversation.')
    if fields.get('conversation') is not None and 'session_sources' not in fields:
        from .session_files import SessionFiles
        try:
            fields['session_sources'] = SessionFiles().snapshot(fields['conversation']['id'])
        except (ValueError, OSError) as exc:
            raise RemotePlanningError(str(exc), error_code='SESSION_FILES_INVALID') from None
    body = dict(protocol=1, request_id=str(uuid4()), phase=phase, text=text,
                language=language, client_time=datetime.now().astimezone().isoformat(), **fields)
    preflight = _require_preflight(body)
    try:
        client=Client()
        if language_preference is not None:
            advertised = client.json('/v1/capabilities')
            policy = advertised.get('request_language') if isinstance(advertised, dict) else None
            if (isinstance(policy, dict) and type(policy.get('protocol')) is int and policy.get('protocol') == 1
                    and policy.get('preference_field') == 'language_preference'
                    and isinstance(policy.get('supported_preferences'), list)
                    and all(isinstance(value, str) for value in policy['supported_preferences'])
                    and {'fa', 'en'}.issubset(policy['supported_preferences'])
                    and isinstance(policy.get('workflows'), list)
                    and all(isinstance(value, str) for value in policy['workflows'])
                    and 'secretary' in policy.get('workflows', [])):
                body['language_preference'] = language_preference
        if fields.get('session_sources'):
            capability = client.json('/v1/capabilities').get('secretary') or {}
            if capability.get('session_sources', {}).get('version') != 1:
                raise RemotePlanningError('Update Eagle Eye Server before using session files.', error_code='SESSION_FILES_UNSUPPORTED')
        if fields.get('ui_image') is not None:
            from modules.ai_imaging.eagle_eye_remote.secretary.ui_observation import UiImage
            UiImage.model_validate(fields['ui_image'])
            capabilities=client.json('/v1/capabilities')
            capability=capabilities.get('secretary') if isinstance(capabilities,dict) else None
            observation=capability.get('ui_observation') if isinstance(capability,dict) else None
            if not isinstance(observation,dict) or observation.get('version') != 1:
                raise RemotePlanningError('Update Eagle Eye Server before including screen context.',error_code='UI_OBSERVATION_UNSUPPORTED')
        preflight = _require_preflight(body)
        with client.open('/v1/secretary/plan', body, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise RemotePlanningError('Secretary server response is too large.')
        result = json.loads(raw)
        if fields.get('session_sources'):
            expected = [(s['name'],s['sha256']) for s in fields['session_sources']]
            received = result.get('session_sources') if isinstance(result,dict) else None
            if not isinstance(received,list) or [(s.get('name'),s.get('sha256')) for s in received] != expected or any(s.get('status')!='extracted' for s in received):
                raise RemotePlanningError('The server did not acknowledge the current session files.', error_code='SESSION_FILES_MISMATCH')
        if fields.get('ui_image') is not None:
            from modules.ai_imaging.eagle_eye_remote.secretary.ui_observation import UiImage,receipt
            if not isinstance(result,dict) or result.get('ui_observation') != receipt(UiImage.model_validate(fields['ui_image'])):
                raise RemotePlanningError('The server did not acknowledge this screen context.',error_code='UI_CONTEXT_MISMATCH')
        if (not isinstance(result, dict) or type(result.get('protocol')) is not int or result['protocol'] != 1
                or result.get('request_id') != body['request_id'] or result.get('phase') != phase):
            raise RemotePlanningError('Secretary server response does not match this request.')
        if fields.get('conversation') is not None:
            from modules.ai_imaging.eagle_eye_remote.secretary.conversation import Conversation
            try:
                incoming = Conversation.model_validate(result.get('conversation')).model_dump()
                if incoming['id'] != fields['conversation']['id'] or incoming['mode'] != fields.get('interaction_mode', 'act'):
                    raise ValueError('Conversation identity mismatch')
                result['conversation'] = incoming
            except (ValueError, TypeError):
                raise RemotePlanningError('Update Eagle Eye Server: conversation identity was not acknowledged.', error_code='CONVERSATION_CONTEXT_MISMATCH') from None
        route = result.get('route')
        if not isinstance(route, dict) or not isinstance(route.get('modules'), list) or len(route['modules']) > 30:
            raise RemotePlanningError('Secretary server returned an invalid route.')
        from .brain.catalog_loader import list_available_module_ids
        available = set(list_available_module_ids())
        if (not all(isinstance(m, str) and m in available for m in route['modules'])
                or not isinstance(route.get('reason'), str) or len(route['reason']) > 4000
                or 'plan' not in result or (phase == 'route' and result['plan'] is not None)):
            raise RemotePlanningError('Secretary server returned an unsupported route.')
        mode = fields.get('interaction_mode', 'act')
        if mode != 'act':
            answer = result.get('answer')
            if result.get('interaction_mode') != mode or result.get('plan') is not None or not isinstance(answer, str) or not answer.strip() or len(answer) > 16000:
                raise RemotePlanningError('Update Eagle Eye Server: selected Secretary mode was not acknowledged.')
            if result.get('tutorial_id') is not None and (fields.get('interaction_mode') != 'guide' or result['tutorial_id'] not in fields.get('question_context', {}).get('tutorials', {})):
                raise RemotePlanningError('Eagle Eye proposed an unavailable tutorial target.')
            if fields.get('interaction_mode') == 'help_ticket':
                ticket = result.get('ticket')
                if (not isinstance(ticket, dict) or not {'category', 'description'}.issubset(ticket)
                        or set(ticket) - {'category', 'description', 'operation'}
                        or ticket.get('operation', 'prepare') not in ('prepare', 'retry', 'status')
                        or ticket['category'] not in ('error', 'crash', 'hang', 'other')
                        or not isinstance(ticket['description'], str) or not 5 <= len(ticket['description']) <= 4000):
                    raise RemotePlanningError('Eagle Eye returned an invalid Help Ticket draft.')
            return {**result, 'plan': None}
        proposal = validate_proposal(result['plan'])
        runtime = fields.get('runtime_capabilities')
        if runtime is not None:
            if result.get('capability_digest') != runtime['digest']:
                raise RemotePlanningError('Update Eagle Eye Server: the runtime capability contract was not acknowledged.')
            validate_runtime_proposal(proposal, runtime)
        return {**result, 'plan':proposal}
    except ServerHTTPError as exc:
        specifics = {
            'SERVER_SESSION_FILES_INVALID':'Eagle Eye could not read the session files. Use up to 12 supported files (8 MiB total), unencrypted PDFs of at most 20 pages, or export complex Office documents to PDF.',
            'SERVER_INVALID_JSON':'Eagle Eye returned invalid response JSON. Please retry the question.',
            'SERVER_ROUTE_INVALID':'Eagle Eye could not identify a valid software module for this question.',
            'SERVER_ANSWER_INVALID':'Eagle Eye returned an invalid answer format. No control action was executed.',
            'SERVER_UPSTREAM_FAILED':'Eagle Eye could not obtain an answer from its configured AI service.',
        }
        from modules.ai_imaging.eagle_eye_remote.secretary_errors import safe_code
        code = getattr(exc, 'error_code', None)
        from modules.ai_imaging.eagle_eye_remote.secretary_errors import safe_rejection
        rejection = safe_rejection(getattr(exc, 'rejection', None))
        if code == 'SERVER_PLAN_INVALID' and rejection is not None:
            preflight = dict(preflight, rejection=rejection)
        if code in specifics:
            raise RemotePlanningError(specifics[code], error_code=code, diagnostic=preflight) from None
        messages = {401: 'Sign in to PACS or Reception before using Secretary.',
                    403: 'Your Eagle Eye user or Secretary access has not been approved. Contact the server administrator.',
                    404: 'Update Eagle Eye Server to support Secretary planning.',
                    422: 'Eagle Eye rejected the Secretary request contract.',
                    429: 'Eagle Eye Server is busy. Try again later.',
                    502: 'Eagle Eye could not complete Secretary planning.',
                    503: 'Secretary planning is unavailable on Eagle Eye Server.'}
        raise RemotePlanningError(messages.get(exc.status, 'Eagle Eye Secretary request failed.'),
                                  error_code=safe_code(code) or 'SERVER_HTTP_'+str(exc.status), diagnostic=preflight) from None
    except RemotePlanningError as error:
        if error.diagnostic is None:
            error.diagnostic = preflight
        raise
    except (RuntimeError, OSError, ValueError, TypeError):
        raise RemotePlanningError('Check the Eagle Eye connection and TLS pairing. No provider fallback was sent.',
                                  diagnostic=preflight) from None

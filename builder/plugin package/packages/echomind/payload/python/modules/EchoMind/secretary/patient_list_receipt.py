"""Aggregate-only patient-list receipts; never infer image download completion."""
PATIENT_LIST_ACTIONS = frozenset({'advanced_search_patients', 'list_patients', 'read_patients',
                                  'advanced_search', 'search_patients'})


def safe_provenance(value):
    """Validate executed bounds, never infer dates from prose or the clock."""
    from datetime import datetime
    if not isinstance(value, dict):
        return {}
    bounds = {key: value.get(key) for key in ('date_from', 'date_to')}
    try:
        for date in bounds.values():
            if not isinstance(date, str) or len(date) != 8 or not date.isascii() or not date.isdigit():
                return {}
            if datetime.strptime(date, '%Y%m%d').strftime('%Y%m%d') != date:
                return {}
        return bounds if bounds['date_from'] <= bounds['date_to'] else {}
    except ValueError:
        return {}


def terminal_provenance(result):
    if (terminal_receipt(result) and result.get('action') in PATIENT_LIST_ACTIONS):
        return safe_provenance(result.get('provenance'))
    if not terminal_receipt(result) or result.get('action') != '__workflow__':
        return {}
    for step in reversed(result['data'].get('steps', [])):
        if isinstance(step, dict) and step.get('tool') in PATIENT_LIST_ACTIONS:
            return safe_provenance(step.get('provenance'))
    return {}


def safe_receipt(value):
    if not isinstance(value, dict) or value.get('state') != 'ready':
        return {}
    count = value.get('count')
    if type(count) is not int or count < 0:
        return {}
    source = value.get('source')
    return {'state': 'ready', 'count': count,
            'source': source if source in ('local', 'server') else 'unknown'}


def terminal_receipt(result):
    """Read only explicit ready/count or verified workflow probe receipts."""
    if not isinstance(result, dict) or result.get('ok') is not True:
        return {}
    if result.get('action') in PATIENT_LIST_ACTIONS:
        return safe_receipt(result.get('data'))
    if result.get('action') == '__workflow__':
        data = result.get('data')
        steps = data.get('steps', []) if isinstance(data, dict) else []
        for step in reversed(steps):
            if isinstance(step, dict) and step.get('tool') in PATIENT_LIST_ACTIONS:
                # A later unverified search invalidates an earlier count.
                return (safe_receipt(step.get('receipt')) if step.get('ok') is True
                        and step.get('verified') is True else {})
    return {}


def is_patient_list_result(result):
    if result.get('action') in PATIENT_LIST_ACTIONS:
        return True
    data = result.get('data')
    return (result.get('action') == '__workflow__' and isinstance(data, dict)
            and any(isinstance(step, dict) and step.get('tool') in PATIENT_LIST_ACTIONS
                    for step in data.get('steps', [])))


def aggregate_text(result):
    """No patient rows, raw engine messages, identifiers or model prose."""
    if result.get('ok') is not True:
        return 'The patient search could not be verified. Check the native patient list for its current status.'
    receipt = terminal_receipt(result)
    if receipt:
        count = receipt['count']
        if count == 0:
            return 'The search completed. No matching studies were found.'
        if receipt['source'] == 'server':
            return f'The search completed. Metadata for {count} studies was fetched into the patient list.'
        if receipt['source'] == 'local':
            return f'The search completed. {count} locally indexed studies are displayed in the patient list.'
        return f'The search completed. {count} studies are displayed in the patient list.'
    data = result.get('data')
    if isinstance(data, dict) and data.get('state') in ('searching', 'pending', 'running'):
        return 'The patient search has started. Results are still loading.'
    return 'The patient search result has not been verified yet.'


DIAGNOSTIC_STATES = frozenset({'ready','searching','pending','running','failed','superseded','cancelled'})
EXECUTION_CODES = frozenset({'NO_HOME_WIDGET', 'INVALID_DATE_RANGE', 'SEARCH_FAILED',
    'WORKFLOW_FAILED', 'VERIFY_FAILED', 'STEP_EXC', 'EXECUTION_FAILED',
    'PERMISSION_DENIED', 'ACTION_UNAVAILABLE', 'UNSUPPORTED_ACTION'})

def _enum(value, allowed):
    return value if isinstance(value,str) and value in allowed else 'unknown'

def _bool_type(value):
    return 'true' if value is True else 'false' if value is False else 'unknown'

def _diagnostic_receipt_present(result):
    try:
        return bool(terminal_receipt(result))
    except (TypeError, ValueError, AttributeError):
        return False

PLANNING_STAGES = frozenset({'valid','schema','body_bounds','ui_binding','modules','unknown'})
PLANNING_ROOTS = frozenset({'protocol','interaction_mode','question_context','ui_image','request_id',
    'phase','text','language','language_preference','client_time','modules','memory_context','conversation',
    'session_sources','invalid_plan','validation_errors','execution_error','attempt','max_attempts',
    'runtime_capabilities','unknown'})
PLANNING_TYPES = frozenset({'missing','extra_forbidden','literal_error','string_type','string_too_long',
    'string_too_short','string_pattern_mismatch','value_error','dict_type','list_type','int_type',
    'bool_type','too_long','too_short','serialization_error','unknown'})
PLANNING_CODES = frozenset({'SERVER_REQUEST_INVALID','SERVER_REQUEST_TOO_LARGE','UI_CONTEXT_MISMATCH',
    'SERVER_PLANNING_FAILED','SERVER_SESSION_FILES_INVALID','SERVER_INVALID_JSON','SERVER_ROUTE_INVALID',
    'SERVER_PLAN_INVALID','SERVER_WORKFLOW_INVALID','SERVER_CLARIFICATION_INVALID','SERVER_CONVERSATION_INVALID',
    'SERVER_ANSWER_INVALID','SERVER_UPSTREAM_FAILED','SESSION_FILES_INVALID','SESSION_FILES_UNSUPPORTED',
    'SESSION_FILES_MISMATCH','UI_OBSERVATION_UNSUPPORTED','CONVERSATION_CONTEXT_MISMATCH',
    'SERVER_HTTP_401','SERVER_HTTP_403','SERVER_HTTP_404','SERVER_HTTP_422','SERVER_HTTP_429',
    'SERVER_HTTP_500','SERVER_HTTP_502','SERVER_HTTP_503'})


def safe_planning_diagnostic(value):
    value = value if isinstance(value,dict) else {}
    def size(key):
        number=value.get(key)
        return min(number,12*1024*1024+1) if type(number) is int and number>=0 else 0
    result = {'stage':_enum(value.get('stage'),PLANNING_STAGES),
        'field_root':_enum(value.get('field_root'),PLANNING_ROOTS),
        'error_type':_enum(value.get('error_type'),PLANNING_TYPES),
        'valid':value.get('valid') is True,'wire_bytes':size('wire_bytes'),'limit_bytes':size('limit_bytes')}
    from modules.ai_imaging.eagle_eye_remote.secretary_errors import safe_rejection
    rejection = safe_rejection(value.get('rejection'))
    if rejection is not None:
        result['rejection'] = rejection
    return result


def result_diagnostic(result):
    """Fixed shape only: no messages, identifiers, row data or count values."""
    result = result if isinstance(result,dict) else {}
    data = result.get('data') if isinstance(result.get('data'),dict) else {}
    step = {}
    steps = data.get('steps') if isinstance(data.get('steps'),list) else []
    for item in reversed(steps[-256:]):
        if isinstance(item,dict) and _enum(item.get('tool'),PATIENT_LIST_ACTIONS) != 'unknown':
            step=item
            break
    count=data.get('count')
    descriptor = {'action':_enum(result.get('action'),PATIENT_LIST_ACTIONS | {'__workflow__'}),
        'ok_type':_bool_type(result.get('ok')),
        'execution_error_code':_enum(result.get('error_code'), EXECUTION_CODES | PLANNING_CODES),
        'data_state':_enum(data.get('state'),DIAGNOSTIC_STATES),
        'count_type':'integer' if type(count) is int else 'missing' if 'count' not in data else 'unknown',
        'terminal_receipt_present':_diagnostic_receipt_present(result),
        'patient_step_action':_enum(step.get('tool'),PATIENT_LIST_ACTIONS),
        'patient_step_error_code':_enum(step.get('error_code'), EXECUTION_CODES),
        'step_ok_type':_bool_type(step.get('ok')),
        'step_verified_type':_bool_type(step.get('verified')),
        'step_receipt_present':bool(safe_receipt(step.get('receipt')))}
    if isinstance(result.get('_planning_diagnostic'),dict):
        descriptor['planning']=safe_planning_diagnostic(result['_planning_diagnostic'])
    return descriptor

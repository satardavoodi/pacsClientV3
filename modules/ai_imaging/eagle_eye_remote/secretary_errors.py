"""Fixed Secretary diagnostic codes, independent of localized display or payloads."""
MESSAGES = {
    'Invalid Secretary request fields.': 'SERVER_REQUEST_INVALID',
    'Session files could not be read. Use supported, unencrypted files within the published limits; export complex Office documents to PDF.': 'SERVER_SESSION_FILES_INVALID',
    'Secretary returned invalid JSON.': 'SERVER_INVALID_JSON',
    'Secretary returned an invalid route.': 'SERVER_ROUTE_INVALID',
    'Unsupported Secretary module.': 'SERVER_ROUTE_INVALID',
    'Invalid conversation description.': 'SERVER_CONVERSATION_INVALID',
    'Secretary returned an invalid plan.': 'SERVER_PLAN_INVALID',
    'Secretary returned an invalid clarification.': 'SERVER_CLARIFICATION_INVALID',
    'Secretary returned invalid clarification choices.': 'SERVER_CLARIFICATION_INVALID',
    'Secretary returned an invalid workflow.': 'SERVER_WORKFLOW_INVALID',
    'Secretary returned unsupported workflow actions.': 'SERVER_WORKFLOW_INVALID',
    'Secretary returned an unsupported or malformed action plan.': 'SERVER_PLAN_INVALID',
    'Secretary answer mode returned an executable or unsupported response.': 'SERVER_ANSWER_INVALID',
    'Invalid Secretary answer.': 'SERVER_ANSWER_INVALID',
    'Tutorial target is unavailable.': 'SERVER_ANSWER_INVALID',
    'Invalid Help Ticket draft.': 'SERVER_ANSWER_INVALID',
    'Secretary server could not complete planning.': 'SERVER_UPSTREAM_FAILED',
}
CODES = frozenset(MESSAGES.values())


def safe_code(value):
    return value if isinstance(value, str) and value in CODES else None


def classify(error):
    return safe_code(getattr(error, 'error_code', None)) or MESSAGES.get(str(error))


def envelope(error):
    """Keep existing display compatibility; add only a known bounded code."""
    result = {'error': str(error)}
    code = classify(error)
    if code is not None:
        result['error_code'] = code
    rejection = safe_rejection(getattr(error, 'rejection', None))
    if code == 'SERVER_PLAN_INVALID' and rejection is not None:
        result['rejection'] = rejection
    return result


REJECTION_BRANCHES = frozenset({'completion_type_or_bounds','json_not_object','plan_validation'})
REJECTION_FIELDS = frozenset({'plan','action','entities','confidence','needs_confirmation','reason','unknown'})
REJECTION_CODES = frozenset({'INVALID_ACTION','MISSING_FIELD','INVALID_TYPE','INVALID_VALUE','INVALID_ENTITY','UNSUPPORTED_ENTITY','unknown'})


def safe_rejection(value):
    """Accept only a fixed diagnostic descriptor, never values or messages."""
    if not isinstance(value, dict) or set(value) != {'branch','field_root','validation_code'}:
        return None
    for key, allowed in (('branch',REJECTION_BRANCHES),('field_root',REJECTION_FIELDS),('validation_code',REJECTION_CODES)):
        if not isinstance(value[key],str) or value[key] not in allowed:
            return None
    return dict(value)

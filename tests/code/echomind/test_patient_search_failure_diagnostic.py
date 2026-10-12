from modules.EchoMind.secretary.patient_list_receipt import result_diagnostic


def test_search_failure_diagnostic_preserves_only_allowlisted_code():
    result = result_diagnostic({'action': 'list_patients', 'ok': False,
        'error_code': 'SEARCH_FAILED', 'message': 'synthetic private details'})
    assert result['execution_error_code'] == 'SEARCH_FAILED'
    assert 'synthetic private details' not in str(result)


def test_workflow_search_failure_exposes_fixed_step_code():
    result = result_diagnostic({'action': '__workflow__', 'ok': False,
        'error_code': 'WORKFLOW_FAILED', 'data': {'steps': [
            {'tool': 'list_patients', 'ok': False, 'error_code': 'INVALID_DATE_RANGE'}]}})
    assert result['execution_error_code'] == 'WORKFLOW_FAILED'
    assert result['patient_step_error_code'] == 'INVALID_DATE_RANGE'


def test_untrusted_failure_codes_do_not_leak_into_diagnostic():
    result = result_diagnostic({'action': 'list_patients', 'ok': False,
        'error_code': 'synthetic private details'})
    assert result['execution_error_code'] == 'unknown'
    assert 'synthetic private details' not in str(result)

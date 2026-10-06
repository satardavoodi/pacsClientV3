from PacsClient.pacs.workstation_ui.home_ui.secretary_result_text import format_result


def test_search_receipt_does_not_repeat_patient_rows():
    text = format_result({'ok': True, 'action': 'list_patients',
        'data': {'state': 'ready', 'count': 12, 'rows': [{'patient_name': 'Synthetic Person', 'patient_id': 'FAKE-ID'}]}})
    assert '12 studies' in text
    assert 'Synthetic Person' not in text and 'FAKE-ID' not in text
    assert 'Selected' not in text


def test_pending_search_is_not_reported_complete():
    text = format_result({'ok': True, 'action': 'list_patients', 'data': {'state': 'searching', 'count': 0}})
    assert 'still loading' in text and 'completed' not in text


def test_empty_and_failed_search_are_distinct():
    assert 'No matching' in format_result({'ok': True, 'action': 'list_patients', 'data': {'count': 0}})
    assert format_result({'ok': False, 'action': 'list_patients', 'message': 'Search unavailable.'}) == 'Search unavailable.'


def test_workflow_reports_only_verified_actions():
    text = format_result({'ok': True, 'action': '__workflow__', 'data': {'steps': [
        {'tool': 'advanced_search', 'ok': True, 'verified': True},
        {'tool': 'sort_patients', 'ok': True, 'verified': False}]}})
    assert 'applied the search filters' in text and 'sorted' not in text


def test_confirmation_hides_internal_goal_and_corrupted_legacy_text():
    result = {'ok':False, 'action':'__workflow__', 'error_code':'CONFIRM_REQUIRED',
        'message':'Internal media_drives plan: \u00c3\u00a2\u20ac',
        'data':{'steps':['select_patients','download_patient','media_drives','prepare_selection_media']}}
    text = format_result(result)
    assert 'confirmation window' in text and 'No action has been completed' in text
    assert 'media_drives' not in text and '\u00c3' not in text
    assert 'check available disc drives' in text


def test_confirmation_keeps_pending_session_and_mode():
    from PacsClient.pacs.workstation_ui.home_ui.secretary_result_text import confirmation_request
    request = confirmation_request({'session_id':'synthetic-session:act', 'interaction_mode':'act', 'source_scope':'server'}, True)
    assert request == {'text':'yes','session_id':'synthetic-session:act','interaction_mode':'act','source_scope':'server','_preplanned':False,'_confirmation_response':True}
    assert confirmation_request({'session_id':'synthetic-session:act'}, False)['text'] == 'no'


def test_actual_confirmation_dialog_omits_corrupt_truncation_and_raw_goal():
    from PySide6.QtWidgets import QApplication, QLabel
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryConfirmDialog
    app = QApplication.instance() or QApplication([])
    dialog = SecretaryConfirmDialog({'action':'__workflow__','error_code':'CONFIRM_REQUIRED',
        'message':'Raw internal advanced_search_patients '+('Synthetic long text '*30),
        'data':{'steps':['advanced_search_patients','read_patients','select_patients','download_selection','prepare_selection_media']}})
    labels = '\n'.join(label.text() for label in dialog.findChildren(QLabel))
    assert 'apply your patient search filters' in labels
    assert 'download the selected studies' in labels
    assert 'advanced_search_patients' not in labels and 'Raw internal' not in labels
    assert labels.isascii()
    dialog.close()


def test_confirmation_outer_frame_is_transparent():
    from PySide6.QtWidgets import QApplication, QFrame
    from PySide6.QtCore import Qt
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryConfirmDialog
    app = QApplication.instance() or QApplication([])
    dialog = SecretaryConfirmDialog({'action':'__workflow__', 'data':{'steps':['select_patients']}})
    outer = dialog.findChild(QFrame, 'secretaryConfirmOuter')
    assert outer is not None
    assert 'background: transparent' in outer.styleSheet()
    assert 'border: none' in outer.styleSheet()
    assert dialog.testAttribute(Qt.WA_TranslucentBackground)
    assert dialog.isModal()
    dialog.close()

"""Synthetic bounded clarification transport and user selection."""
import pytest
from modules.EchoMind.secretary.remote_planner import validate_proposal
from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator


def proposal(n=2):
    return {'action':'unknown','reason':'Which scope do you mean?',
            'clarification': {'question':'Which scope do you mean?',
            'options':[{'id':str(i),'label':f'Scope {i}'} for i in range(n)]}}


@pytest.mark.parametrize('n', [1, 2, 3])
def test_options_survive_transport_and_result(n):
    plan=validate_proposal(proposal(n))
    assert plan['clarification']==proposal(n)['clarification']
    engine=object.__new__(SecretaryOrchestrator)
    result=engine._clarify_result(plan)
    assert result['message']==plan['clarification']['question']
    assert result['data']['clarification']==plan['clarification']


@pytest.mark.parametrize('n',[0,4])
def test_invalid_option_count_is_rejected(n):
    with pytest.raises(Exception):
        validate_proposal(proposal(n))


def test_reply_preserves_session_and_requires_new_plan():
    import json
    from PacsClient.pacs.workstation_ui.home_ui.secretary_clarification_dialog import clarification_reply
    payload={'text':'Remove unused modality options.', 'session_id':'synthetic:act',
             'interaction_mode':'act','_preplanned':{'action':'old'},'_confirmation_response':True}
    reply=clarification_reply(payload,proposal()['clarification'],'Change Settings')
    assert reply['session_id']==payload['session_id']
    assert '_preplanned' not in reply and '_confirmation_response' not in reply
    assert json.loads(reply['text'])['original_request']==payload['text']
    assert json.loads(reply['text'])['user_answer']=='Change Settings'


@pytest.mark.parametrize('n',[1,2,3])
def test_dialog_buttons_select_meaning_or_cancel(n):
    from PySide6.QtWidgets import QApplication,QPushButton,QDialog
    from PacsClient.pacs.workstation_ui.home_ui.secretary_clarification_dialog import SecretaryClarificationDialog
    app=QApplication.instance() or QApplication([])
    value=proposal(n)['clarification']
    dialog=SecretaryClarificationDialog(value)
    buttons=dialog.findChildren(QPushButton)
    assert [b.text() for b in buttons[:n]]==[o['label'] for o in value['options']]
    buttons[n-1].click()
    assert dialog.result()==QDialog.Accepted
    assert dialog.answer==value['options'][-1]['label']
    dialog.close()
    cancelled=SecretaryClarificationDialog(value)
    cancelled.reject()
    assert cancelled.answer is None
    cancelled.close()


def test_duplicate_options_and_executable_option_fields_rejected():
    from modules.ai_imaging.eagle_eye_remote.secretary.clarification import validate_clarification
    value=proposal()['clarification']
    value['options'][1]['id']=value['options'][0]['id']
    with pytest.raises(ValueError): validate_clarification(value)
    value=proposal()['clarification']; value['options'][0]['action']='delete'
    with pytest.raises(ValueError): validate_clarification(value)


def test_text_only_question_has_answerable_dialog():
    from PySide6.QtWidgets import QApplication,QDialog,QPushButton
    from PacsClient.pacs.workstation_ui.home_ui.secretary_clarification_dialog import SecretaryClarificationDialog, clarification_reply, question_from_result
    app=QApplication.instance() or QApplication([])
    value=question_from_result({'error_code':'NEEDS_CLARIFICATION','message':'Which page?',
        'data':{'reason':'Which page?','clarification':None}})
    assert value=={'question':'Which page?','options':[]}
    dialog=SecretaryClarificationDialog(value)
    dialog.custom.setText('Settings')
    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Send answer').click()
    assert dialog.result()==QDialog.Accepted and dialog.answer=='Settings'
    reply=clarification_reply({'text':'Change options','session_id':'test:act'},value,dialog.answer)
    assert reply['session_id']=='test:act'
    dialog.close()


def test_clarification_status_is_waiting_not_working():
    from PySide6.QtWidgets import QApplication,QLabel,QPlainTextEdit
    from types import SimpleNamespace
    from PacsClient.pacs.workstation_ui.home_ui.secretary_compact_ui import update_companion_status
    app=QApplication.instance() or QApplication([])
    box=QPlainTextEdit()
    widget=SimpleNamespace(log_box=box,_status_icon=QLabel(),_status_hint=QLabel(),
                           _set_log_box_text=box.setPlainText)
    update_companion_status(widget,'Awaiting answer')
    assert box.toPlainText()=='Your answer needed'
    assert 'question' in widget._status_hint.text()

"""Sequential workflows bind actual handles and wait for terminal receipts."""
from modules.EchoMind.secretary.workflow import build_plan, WorkflowExecutor


def test_comment_handle_is_bound_and_delivery_is_verified():
    calls=[]
    def run(action, args):
        calls.append((action,args))
        if action=='prepare_patient_comment':
            return {'ok':True,'data':{'draft_id':'actual-draft'}}
        if action=='sync_patient_comment':
            assert args['draft_id']=='actual-draft'
            return {'ok':True,'data':{'operation_id':'actual-operation','state':'running'}}
        if action=='patient_comment_status':
            return {'ok':True,'data':{'state':'succeeded','data':{'delivered':True}}}
        return {'ok':True}
    plan=build_plan('Synthetic comment then follow-up',[
        {'action':'prepare_patient_comment','entities':{'study_uid':'1.2.3','comment':'Synthetic'}},
        {'action':'sync_patient_comment','entities':{'draft_id':'$draft_id'}},
        {'action':'get_recent_function_results','entities':{}}])
    result=WorkflowExecutor(run,sleep=lambda _:None).run(plan)
    assert result.ok is True
    assert [a for a,_ in calls]==['prepare_patient_comment','sync_patient_comment',
                                 'patient_comment_status','get_recent_function_results']


def test_unknown_delivery_stops_later_steps():
    calls=[]
    def run(action,args):
        calls.append(action)
        if action=='sync_patient_comment':
            return {'ok':True,'data':{'operation_id':'actual-operation','state':'running'}}
        if action=='patient_comment_status':
            return {'ok':True,'data':{'state':'succeeded','data':{'delivered':False}}}
        return {'ok':True}
    plan=build_plan('Synthetic',[
        {'action':'sync_patient_comment','entities':{'draft_id':'actual-draft'}},
        {'action':'get_recent_function_results','entities':{}}])
    result=WorkflowExecutor(run,sleep=lambda _:None).run(plan)
    assert result.ok is False
    assert 'get_recent_function_results' not in calls


def test_missing_reference_never_reaches_dispatch():
    calls=[]
    plan=build_plan('Synthetic',[{'action':'sync_patient_comment','entities':{'draft_id':'$missing'}}])
    result=WorkflowExecutor(lambda *a:calls.append(a),sleep=lambda _:None).run(plan)
    assert not calls
    assert result.steps[0].error_code=='MISSING_CONTEXT'

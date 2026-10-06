from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan

class Home:
    def __init__(self): self.query=None; self._search_task=None
    def _on_advanced_search_requested(self,query): self.query=query

def test_body_and_age_use_existing_advanced_filter_route():
    home=Home();adapter=HomeWidgetAdapter(home_widget=home)
    adapter._set_active_source=lambda source:None
    adapter.start_search('server',{'modality':'MR','body_part':'KNEE','age_min':12,'date_from':'20260701','date_to':'20260731'})
    assert home.query['body_part']=='KNEE'
    assert home.query['modalities']==['MR']
    assert home.query['age_min']==12
    assert home.query['date_from']=='20260701'

class Search:
    def is_available(self): return True
    def start_search(self,source,criteria): self.criteria=criteria
    def list_rows(self): return []

def test_shared_adapter_preserves_advanced_fields():
    home=Search();adapter=HomeCommandAdapter(home)
    result=adapter.list_patients(CommandPlan(action='list_patients',entities={'body_part':'KNEE','age_min':12}),{})
    assert result.ok
    assert home.criteria['body_part']=='KNEE'
    assert home.criteria['age_min']==12

def test_ready_read_receipt_covers_full_order_before_truncation():
    from modules.EchoMind.secretary.adapters.home_selection_adapter import list_identity
    from modules.EchoMind.secretary.workflow import _verify_search_ready
    home=Search()
    rows=[{'patient_id':f'synthetic-{i}','study_uid':f'1.2.3.{i}'} for i in range(30)]
    home.list_rows=lambda:rows
    result=HomeCommandAdapter(home).read_patients(
        CommandPlan(action='read_patients',entities={'limit':5}),{})
    assert result.data['list_id']==list_identity(rows,'unknown')
    assert len(result.data['rows'])==5
    assert _verify_search_ready(result.model_dump(),{})

def test_workflow_refreshes_order_receipt_after_sort_before_selection():
    from modules.EchoMind.secretary.workflow import WorkflowExecutor,build_plan
    order='before'
    def run(action,entities):
        nonlocal order
        if action=='sort_patients':
            order='after'
            return {'ok':True,'data':{}}
        if action=='read_patients':
            return {'ok':True,'data':{'state':'ready','list_id':order}}
        assert action=='select_patients'
        return {'ok':entities['list_id']==order,'data':{'selected_count':3}}
    plan=build_plan('Synthetic sorted selection',[
        {'action':'read_patients','entities':{}},
        {'action':'sort_patients','entities':{'sort_by':'images_count','order':'desc'}},
        {'action':'select_patients','entities':{'list_id':'$list_id','row_indices':[1,3,5]}}])
    assert WorkflowExecutor(run).run(plan).ok

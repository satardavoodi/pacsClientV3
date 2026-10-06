from types import SimpleNamespace
import pytest
from modules.EchoMind.secretary.command_envelope import HomeOpenEntities, CommandPlan
from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
from modules.EchoMind.secretary.adapters.home_selection_adapter import list_identity


@pytest.mark.parametrize('entities', [{'row_index':1}, {'row_index':True,'list_id':'x'}, {'row_index':0,'list_id':'x'}, {'row_index':1,'list_id':'x','patient_id':'synthetic'}])
def test_schema_rejects_unbound_or_conflicting_ordinal(entities):
    with pytest.raises(ValueError): HomeOpenEntities(**entities)


def test_bus_opens_identity_from_bound_list_and_rejects_changed_order():
    rows = [{'patient_id':'synthetic-a','study_uid':'1.2.3.1'}, {'patient_id':'synthetic-b','study_uid':'1.2.3.2'}]
    table = SimpleNamespace(results_table=SimpleNamespace(rowCount=lambda:len(rows)), get_patient_data_by_row=lambda i:rows[i])
    home = SimpleNamespace(patient_table_widget=table, data_access_panel_widget=SimpleNamespace(get_result=lambda:'server'))
    opened = []
    class Adapter:
        def __init__(self): self.home=home
        def is_available(self): return True
        def open_patient(self, patient_id, patient_name, study_uid, status): opened.append((patient_id,study_uid))
    adapter = HomeCommandAdapter(Adapter())
    entities=HomeOpenEntities(row_index=1,list_id=list_identity(rows,'server')).model_dump()
    plan=CommandPlan(action='open_patient',entities=entities)
    result=adapter.open_patient(plan,{})
    assert result.ok and result.data['study_uid']=='1.2.3.1'
    assert opened==[('synthetic-a','1.2.3.1')]
    rows.reverse()
    assert adapter.open_patient(plan,{}).error_code=='STALE_LIST'
    assert len(opened)==1

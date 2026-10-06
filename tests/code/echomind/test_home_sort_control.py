from modules.EchoMind.secretary.bus_factory import build_command_bus
from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan

class Home:
    def is_available(self): return True
    def search(self, **kwargs): self.search_called=True
    def list_rows(self): return []
    def sort_patients(self,column,order):
        self.called=(column,order)
        return True

def test_sort_registered_in_runtime_snapshot():
    bus=build_command_bus(home_widget=object())
    assert 'sort_patients' in bus.actions()

def test_sort_dispatches_validated_column_and_order():
    home=Home();adapter=HomeCommandAdapter(home)
    result=adapter.sort_patients(CommandPlan(action='sort_patients',entities={'column':'images_count','order':'desc'}),{})
    assert result.ok and home.called==('images_count','desc')
    result=adapter.sort_patients(CommandPlan(action='sort_patients',entities={'column':'date','order':'wrong'}),{})
    assert not result.ok

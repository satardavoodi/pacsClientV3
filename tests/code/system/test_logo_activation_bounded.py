"""Tab activation should not repeat a stylesheet rebuild or synchronous paint."""
import ast
from pathlib import Path
from types import SimpleNamespace


def test_activation_only_repolishes_on_state_transition():
    source = Path(__file__).resolve().parents[3] / 'PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'set_logo_active')
    ns = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), ns)
    calls = []
    class Button:
        state = None
        def property(self, name): return self.state
        def setProperty(self, name, value): self.state = value
        def style(self): return self
        def unpolish(self, obj): calls.append('unpolish')
        def polish(self, obj): calls.append('polish')
        def update(self): calls.append('update')
        def repaint(self): calls.append('sync_paint')
    owner = SimpleNamespace(logo_button=Button(), _apply_logo_logotype_style=lambda: calls.append('rebuild_style'))
    activate = ns['set_logo_active']
    activate(owner, True)
    activate(owner, True)
    activate(owner, False)
    activate(owner, False)
    assert owner.logo_button.state is False
    assert calls == ['unpolish', 'polish', 'update'] * 2

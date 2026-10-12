"""Field regression: tool diagnostics must not dereference a deleted viewport."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import delete, isValid


def ruler_method():
    source = Path('PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ToolbarManager')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'toggle_ruler')
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), 'exec'), namespace)
    return namespace['toggle_ruler']


@pytest.mark.parametrize('missing', [False, True])
def test_retired_target_is_rejected_before_repr_or_tool_work(missing):
    app = QApplication.instance() or QApplication([])
    target = QWidget()
    delete(target)
    assert not isValid(target)
    manager = SimpleNamespace(tool_selected='RULER', check_and_deactivate_tools=Mock())
    ruler_method()(manager, None if missing else target)
    manager.check_and_deactivate_tools.assert_not_called()
    assert manager.tool_selected == 'RULER'
    assert app is not None


def test_live_report_target_keeps_document_opt_out():
    app = QApplication.instance() or QApplication([])
    target = QWidget()
    target._structured_report_active = True
    ruler_method()(SimpleNamespace(), target)
    assert isValid(target)
    delete(target)

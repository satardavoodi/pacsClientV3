"""Execute the real launcher without importing pages or opening a database."""
import ast
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication


@pytest.mark.parametrize('mode', ['created', 'reused', 'failed'])
def test_education_launcher_records_import_construct_and_event_loop(monkeypatch, caplog, mode):
    app = QApplication.instance() or QApplication([])
    path = Path('PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py')
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == 'open_education_module')
    module = ModuleType('modules.education.education_module_redesigned')
    def construct(**kwargs):
        if mode == 'failed':
            raise RuntimeError('synthetic-private-error')
        from PacsClient.utils.diagnostic_logging import content_diagnostic_phase, content_diagnostic_work
        with content_diagnostic_phase('library_construct'):
            content_diagnostic_work('library_query', lambda: [])
        return SimpleNamespace()
    module.EducationModuleRedesigned = construct
    monkeypatch.setitem(sys.modules, module.__name__, module)
    existing = SimpleNamespace()
    def activate(*args, **kwargs):
        return existing if mode == 'reused' else kwargs['widget_factory']()
    namespace = dict(activate_or_create_module_tab=activate)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    owner = SimpleNamespace(tab_widget=object(), custom_tab_manager=object())
    caplog.set_level(logging.INFO)
    result = namespace['open_education_module'](owner)
    records = [r for r in caplog.records if str(r.msg).startswith('[CONTENT-DIAG]')]
    if mode != 'failed':
        assert not any(r.stage == 'completed' for r in records)
    app.processEvents()
    records = [r for r in caplog.records if str(r.msg).startswith('[CONTENT-DIAG]')]
    stages = [r.stage for r in records]
    assert stages[:3] == ['requested', 'module_import_start', 'module_import_end']
    assert stages.count('failed' if mode == 'failed' else 'completed') == 1
    assert ('module_construct_start' in stages) == (mode != 'reused')
    assert ('library_construct_end' in stages) == (mode == 'created')
    assert (result is None) == (mode == 'failed')
    assert 'synthetic-private' not in ' '.join(r.getMessage() for r in records)

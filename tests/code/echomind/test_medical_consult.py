"""Synthetic consultation checks without importing clinical database modules."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path('modules/EchoMind/viewer_chat')


def method(file, name, namespace=None):
    tree = ast.parse((ROOT / file).read_text(encoding='utf-8'))
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert matches, f'Missing {name}'
    scope = dict(namespace or {})
    exec(compile(ast.Module(body=[matches[0]], type_ignores=[]), '<consult-test>', 'exec'), scope)
    return scope[name]


def test_assist_hides_only_report_tabs():
    visibility = {}
    switched = []
    composer = SimpleNamespace(_active_tab='correction',
        _tab_index_by_key={'transcribe': 0, 'normal_template': 1, 'correction': 2, 'standard': 3},
        mode_tabs=SimpleNamespace(setTabVisible=lambda index, visible: visibility.update({index: visible})),
        switch_tab=switched.append)
    method('ai_chat_widgets.py', 'set_reference_mode')(composer, True)
    assert visibility == {1: False, 2: False}
    assert switched == ['transcribe']


def test_consult_uses_current_visible_report_not_stale_raw():
    from PySide6.QtGui import QTextDocument
    sent = []
    page = SimpleNamespace(medicalConsultRequested=SimpleNamespace(emit=sent.append))
    bubble = SimpleNamespace(get_html=lambda: '<p>Current synthetic finding.</p>', raw_report_json='Stale finding')
    method('ai_chat_pages.py', '_medical_consult', {'QTextDocument': QTextDocument})(page, bubble)
    assert sent == ['Current synthetic finding.']


def test_consult_preserves_report_and_opens_fresh_assist(monkeypatch):
    from modules.EchoMind import remote_backend
    monkeypatch.setattr(remote_backend, 'selected', lambda: True)
    calls, back = [], []
    class Page:
        def __init__(self, **kwargs):
            calls.append(('create', kwargs))
            self.btn_back = SimpleNamespace(setText=lambda text: None)
            self.backRequested = SimpleNamespace(connect=back.append)
            self.composer = SimpleNamespace(set_tab_text=lambda *args: None,
                switch_tab=lambda *args: None, box=SimpleNamespace(setPlainText=lambda text: None))
        def _new_chat(self): calls.append(('new',))
        def _send_with_mode(self, text, mode): calls.append(('send', text, mode))
    original = object()
    visible = []
    viewer = SimpleNamespace(_page=original, study_uid='synthetic-study',
        _close_consult_page=lambda: None,
        stack=SimpleNamespace(addWidget=lambda page: None, setCurrentWidget=visible.append))
    method('ai_chat_viewer.py', '_open_medical_consult', {'OneChatPage': Page})(viewer, 'Selected report')
    assert viewer._page is original
    assert calls == [('create', {'study_uid': 'synthetic-study', 'page_mode': 'Assist'}),
                     ('new',), ('send', 'Selected report', 'Web Search')]
    back[0]()
    assert visible[-1] is original


def test_consult_is_wired_for_live_and_restored_reports():
    source = (ROOT / 'ai_chat_pages.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and any(k.arg == 'on_medical_consult' for k in n.keywords)]
    assert len(calls) == 4
    for call in calls:
        callback = next(k.value for k in call.keywords if k.arg == 'on_medical_consult')
        if isinstance(callback, ast.IfExp):
            condition = ast.unparse(callback.test)
            assert "origin == 'report'" in condition and 'not is_user' in condition

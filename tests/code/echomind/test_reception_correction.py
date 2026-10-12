"""Reception sources use exact case identity and preserve report text."""
import json
import base64
from modules.EchoMind.correction_source import unpack
from modules.EchoMind.reception_correction import report_items


def test_no_unscoped_query():
    assert report_items('', '', lambda **kw: (_ for _ in ()).throw(AssertionError())) == []


def test_identity_html_and_duplicate_handling():
    rows = [
        {'id': 1, 'study_uid': 'study-a', 'html_content': '<style>hidden</style><p>EF 60%</p><p>No effusion.</p>'},
        {'id': 2, 'study_uid': 'study-b', 'patient_id': 'patient-a', 'html_content': 'Wrong study'},
        {'id': 3, 'patient_id': 'patient-b', 'html_content': 'Wrong patient'},
        {'id': 4, 'patient_id': 'patient-a', 'html_content': '<table><tr><td>Length</td><td>24 mm</td></tr></table>'},
    ]
    calls = []
    def fetch(**kw):
        calls.append(kw)
        return rows
    items = report_items('study-a', 'patient-a', fetch)
    assert len(items) == 2
    assert b'EF 60%' in base64.b64decode(unpack(items[0][0])['data'])
    assert b'24 mm' in base64.b64decode(unpack(items[1][0])['data'])
    assert items[0][1] == 'Reception report 1'
    assert calls == [{'study_uid': 'study-a', 'limit': 100}, {'patient_id': 'patient-a', 'limit': 100}]


def test_async_result_cannot_cross_sessions():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    tree = ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_load_reception_correction_reports')
    received = []
    composer = SimpleNamespace(cmb_corr_reports=SimpleNamespace(setCurrentIndex=lambda _: None),
        get_selected_correction_report_text=lambda: '', register_correction_report=lambda raw, **kw: received.append(raw))
    owner = SimpleNamespace(study_uid='study-a', current_session_id='new-session', composer=composer)
    callback = next(n for n in method.body if isinstance(n, ast.FunctionDef) and n.name == 'ok')
    scope = dict(self=owner, study_uid='study-a', session_id='old-session')
    exec(compile(ast.Module(body=[callback], type_ignores=[]), '<callback>', 'exec'), scope)
    scope['ok']({'items': [('synthetic', 'Reception report')], 'errors': []})
    assert received == []
    owner.current_session_id = 'old-session'
    scope['ok']({'items': [('synthetic', 'Reception report')], 'errors': []})
    assert received == ['synthetic']

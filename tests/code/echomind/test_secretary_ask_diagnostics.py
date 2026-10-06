"""Read-only download questions receive bounded facts and explicit failure results."""
from types import SimpleNamespace
import pytest


def test_widget_ask_captures_state_on_gui_and_reads_logs_on_worker(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
    from PacsClient.utils import data_paths
    app = QApplication.instance() or QApplication([])
    gui_thread = threading.get_ident()
    monkeypatch.setenv('AIPACS_ECHOMIND_SECRETARY_ASYNC', '1')
    monkeypatch.setattr(data_paths, 'LOGS_DIR', tmp_path)
    monkeypatch.setattr('PacsClient.utils.secretary_question_context.collect_settings_report', lambda: {'scope':'synthetic'})
    (tmp_path / 'download_diagnostics.log').write_text('ERROR Synthetic diagnostic\n', encoding='utf-8')
    widget = SecretaryButtonWidget()
    captured, scheduled, rendered = [], [], []
    def execute(plan):
        assert threading.get_ident() == gui_thread
        return SimpleNamespace(ok=True, data={'total':2, 'active':1, 'downloading':1})
    def preplan(payload):
        assert threading.get_ident() != gui_thread
        captured.append(payload['question_context'])
        return {'_mode':'ask', '_mode_reply':'Synthetic download assessment'}
    widget._secretary_orchestrator = SimpleNamespace(
        executor=SimpleNamespace(_resolve_bus=lambda:SimpleNamespace(execute=execute)), preplan=preplan)
    widget._ensure_secretary_runtime = lambda:True
    widget._run_worker = lambda work, done, failed:scheduled.append((work, done))
    widget._secretary_execute_and_render = rendered.append
    widget.mode_selector.setCurrentIndex(widget.mode_selector.findData('ask'))
    try:
        widget._secretary_transcript_ready({'ok':True, 'transcript':'Check download health.'})
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(scheduled[0][0]).result()
        scheduled[0][1](result)
        assert captured[0]['download_state']['active'] == 1
        assert captured[0]['diagnostics']['logs']['sources'][2]['errors'] == 1
        assert rendered[0]['_preplanned']['_mode_reply'] == 'Synthetic download assessment'
    finally:
        widget.cleanup()
        widget.close()


def test_ask_snapshot_uses_shared_read_only_download_counts_and_worker_log_projection(tmp_path):
    from PacsClient.utils.secretary_question_context import capture_question_context, collect_question_evidence
    calls=[]
    def execute(plan):
        calls.append(plan['action'])
        if plan['action']=='get_loaded_study_summary':
            return SimpleNamespace(ok=True,data={'scope':'loaded_studies','loaded_studies':0})
        return SimpleNamespace(ok=True,data={'total':3,'active':2,'downloading':1,
            'by_status':{'completed':1,'downloading':1,'queued':1},'private_field':'Synthetic secret'})
    captured=capture_question_context(SimpleNamespace(execute=execute))
    (tmp_path/'download_diagnostics.log').write_text('2026-10-04 ERROR Synthetic private patient message\n',encoding='utf-8')
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(collect_question_evidence,captured,tmp_path).result()
    assert calls==['get_loaded_study_summary','download_statistics']
    assert result['download_state']['downloading']==1
    assert result['diagnostics']['logs']['sources'][2]['errors']==1
    assert result['diagnostics']['logs']['scope']=='bounded_tail_not_time_window'
    assert 'private' not in str(result).lower()
    assert not result['diagnostics']['logs']['raw_text_exported']


def test_question_preplanning_failure_survives_to_response_without_control_execution(monkeypatch):
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    from modules.EchoMind.secretary import remote_planner
    instance=object.__new__(SecretaryOrchestrator)
    instance.executor=SimpleNamespace(_resolve_bus=lambda:None)
    instance._get_memory_store_safe=lambda:None
    monkeypatch.setattr(remote_planner,'uses_server',lambda:True)
    monkeypatch.setattr(remote_planner,'request',lambda *a,**k:(_ for _ in ()).throw(
        remote_planner.RemotePlanningError('Eagle Eye could not complete the answer.')))
    cmd={'text':'Check download health.','interaction_mode':'ask'}
    plan=instance._parse_plan(cmd)
    work=instance._handle_steps(dict(cmd,_preplanned=plan))
    with pytest.raises(StopIteration) as ended: next(work)
    result=ended.value.value
    assert not result['ok'] and result['error_code']!='MODE_RESPONSE_REQUIRED'
    assert 'Eagle Eye' in result['message']


def test_fast_transient_answer_error_retries_once_on_same_server(monkeypatch):
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    from modules.EchoMind.secretary import remote_planner
    instance=object.__new__(SecretaryOrchestrator)
    instance.executor=SimpleNamespace(_resolve_bus=lambda:None)
    monkeypatch.setattr(remote_planner,'uses_server',lambda:True)
    calls=[]
    def request(*a,**k):
        calls.append(k)
        if len(calls)==1:
            error=remote_planner.RemotePlanningError('Eagle Eye returned invalid answer JSON.')
            error.error_code='SERVER_INVALID_JSON'
            raise error
        return {'route':{'modules':['download'],'reason':'Synthetic'},'answer':'One active download; sampled log has one error.'}
    monkeypatch.setattr(remote_planner,'request',request)
    context={'download_state':{'active':1}}
    result=instance._parse_plan({'text':'Check download health.','interaction_mode':'ask','question_context':context})
    assert result['_mode_reply'].startswith('One active')
    assert len(calls)==2 and calls[0]==calls[1]


@pytest.mark.parametrize('message,expected', [
    ('Secretary returned invalid JSON.','SERVER_INVALID_JSON'),
    ('Unsupported Secretary module.','SERVER_ROUTE_INVALID'),
    ('Secretary server could not complete planning.','SERVER_UPSTREAM_FAILED'),
    ('Synthetic private provider detail',None),
])
def test_http_error_exports_only_fixed_safe_codes(message,expected):
    import io,json,urllib.error
    from modules.ai_imaging.eagle_eye_remote.client import Client,ServerHTTPError
    class Opener:
        def open(self,*a,**k):
            raise urllib.error.HTTPError('https://synthetic.invalid',422,'Synthetic',{},
                io.BytesIO(json.dumps({'error':message}).encode()))
    client=object.__new__(Client)
    client.url='https://synthetic.invalid'; client.token='synthetic-token'; client.opener=Opener()
    with pytest.raises(ServerHTTPError) as ended: client.open('/v1/secretary/plan',{})
    assert ended.value.error_code==expected
    assert str(ended.value)=='EchoMind server request failed.'


def test_repeated_failure_is_bounded_and_never_switches_provider(monkeypatch):
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    from modules.EchoMind.secretary import remote_planner
    instance=object.__new__(SecretaryOrchestrator)
    instance.executor=SimpleNamespace(_resolve_bus=lambda:None)
    monkeypatch.setattr(remote_planner,'uses_server',lambda:True)
    calls=[]
    def failed(*a,**k):
        calls.append(k)
        raise remote_planner.RemotePlanningError('Invalid server JSON.',error_code='SERVER_INVALID_JSON')
    monkeypatch.setattr(remote_planner,'request',failed)
    result=instance._parse_plan({'text':'Synthetic question','interaction_mode':'ask'})
    assert len(calls)==2
    assert result['_mode_error']['error_code']=='SERVER_INVALID_JSON'

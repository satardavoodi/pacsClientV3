"""Synthetic support transport, privacy and retry contract."""
import json
from uuid import UUID, uuid4
import pytest

from PacsClient.utils.support_issue_reporting import IssueReporter, diagnostic_bundle


class Store:
    def __init__(self):
        self.value = None
    def load(self):
        return self.value
    def save(self, value):
        self.value = json.loads(json.dumps(value))
    def clear(self):
        self.value = None


class Client:
    base_url = 'https://synthetic.invalid/consult-form'
    support_identity_binding = 'synthetic-credential-binding'
    def __init__(self):
        self.calls = []
        self.fail = False
    def request_json(self, method, path, json_body=None, allow_redirects=None, timeout=None):
        assert allow_redirects is False
        self.calls.append(json_body)
        if self.fail:
            raise TimeoutError('Sensitive exception details')
        return {'state': 'received', 'issue_id': '4b8b9df2-4874-45c7-adc7-7bff88fbcf97',
                'client_issue_id': json_body['client_issue_id'], 'status': 'new'}


@pytest.mark.parametrize('http_status', [None, 401, 403, 422])
@pytest.mark.parametrize('payload_size', [100, 100000])
def test_chunk_origin_retry_only_follows_transport_failure(tmp_path, http_status, payload_size):
    from modules.Identity.providers.aipacs_web import AipacsWebError
    class OriginClient(Client):
        def request_json(self, method, path, json_body=None, **kwargs):
            if path.endswith('/upload-capabilities'):
                return {'protocol':1,'chunk_bytes':49152,'max_bytes':16*1024*1024,
                        'origin_ipv4':'46.202.158.216'}
            self.calls.append(('edge',path,json_body))
            raise AipacsWebError('Synthetic network failure',status_code=http_status)
        def request_support_json(self, path, body, origin_ipv4, timeout):
            assert origin_ipv4 == '46.202.158.216'
            self.calls.append(('origin',path,body))
            if '/chunks/' in path:
                return {'state':'chunk_received','position':int(path.rsplit('/',1)[1])}
            return {'state':'received','issue_id':str(uuid4()),'client_issue_id':identifier}
    client = OriginClient()
    reporter = IssueReporter('synthetic-user',client,Store(),tmp_path)
    identifier = str(uuid4())
    result = reporter._send({'client_issue_id':identifier,'synthetic':'a'*payload_size})
    if http_status is None:
        assert result['state'] == 'received'
        assert client.calls[0][2] == client.calls[1][2]
        assert sum(item[0]=='edge' for item in client.calls) == 1
        assert len(client.calls) == (5 if payload_size > 49152 else 2)
    else:
        assert result['state'] == 'pending'
        assert all(item[0]=='edge' for item in client.calls)


def test_large_delivery_uses_bounded_verified_chunks_and_retry_identity(tmp_path):
    import base64
    from hashlib import sha256
    class ChunkClient(Client):
        def __init__(self):
            super().__init__()
            self.parts = {}
            self.headers = []
        def request_json(self, method, path, json_body=None, **kwargs):
            if path.endswith('/upload-capabilities'):
                return {'protocol':1, 'chunk_bytes':49152, 'max_bytes':16*1024*1024}
            if '/chunks/' in path:
                assert len(json.dumps(json_body).encode()) < 70000
                position = int(path.rsplit('/',1)[1])
                content = base64.b64decode(json_body['data'])
                assert self.parts.get(position,content) == content
                self.parts[position] = content
                self.headers.append((json_body['sha256'],json_body['bytes'],json_body['count']))
                return {'state':'chunk_received','position':position}
            assert path.endswith('/complete')
            raw = b''.join(self.parts[p] for p in sorted(self.parts))
            assert sha256(raw).hexdigest() == json_body['sha256']
            received = json.loads(raw)
            return {'state':'received','issue_id':str(uuid4()),'client_issue_id':received['client_issue_id']}
    client, store = ChunkClient(), Store()
    reporter = IssueReporter('synthetic-user',client,store,tmp_path)
    payload = {'client_issue_id':str(uuid4()),'ticket_package':{'base64':'a'*180000}}
    result = reporter._send(payload)
    assert result['state'] == 'received'
    assert len(client.parts) >= 4
    assert len(set(client.headers)) == 1


def test_secretary_submit_restored_ticket_uses_retry_after_local_review():
    from types import SimpleNamespace
    from modules.EchoMind.secretary.adapters.support_command_adapter import SupportCommandAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    calls = []
    button = lambda enabled: SimpleNamespace(isEnabled=lambda:enabled)
    dialog = SimpleNamespace(isVisible=lambda:True,consent=SimpleNamespace(isChecked=lambda:True),
        send=button(False), retry=button(True), public_result={'state':'pending'},
        _submit=lambda:calls.append('send'),_retry=lambda:calls.append('retry'))
    adapter = SupportCommandAdapter(SimpleNamespace(_support_issue_dialog=dialog))
    result = adapter.submit_help_ticket(CommandPlan(action='submit_help_ticket'),None)
    assert result.ok and calls == ['retry']
    assert result.data['ticket_submitted'] is False


def test_confirmed_delivery_survives_restart_and_is_credential_bound(tmp_path):
    client, history = Client(), Store()
    reporter = IssueReporter('synthetic-user',client,Store(),tmp_path,receipt_store=history)
    reporter.submit('Synthetic issue request.','error',False,{'app_version':'3.7.0','pacs_user':'synthetic-user'})
    restarted = IssueReporter('synthetic-user',client,Store(),tmp_path,receipt_store=history)
    assert restarted.last_receipt()['state'] == 'received'
    client.support_identity_binding = 'another-account'
    other = IssueReporter('synthetic-user',client,Store(),tmp_path,receipt_store=history)
    assert other.last_receipt() is None


def test_secretary_feedback_requires_actual_receipt_and_distinguishes_pending():
    from PacsClient.utils.support_ticket_feedback import ticket_feedback
    assert ticket_feedback({'state':'running'})[0].startswith('Working')
    assert ticket_feedback({'state':'pending'})[0] == 'Failed'
    assert ticket_feedback({'state':'received','ticket_submitted':True,'issue_id':'invalid'})[0] == 'Failed'
    stage, text = ticket_feedback({'state':'received','ticket_submitted':True,'issue_id':str(uuid4())})
    assert stage == 'Done' and 'received' in text


def test_pending_receipt_preserves_safe_http_diagnostics(tmp_path):
    from modules.Identity.providers.aipacs_web import AipacsWebError
    class RejectedClient(Client):
        def request_json(self, *args, **kwargs):
            raise AipacsWebError('Sensitive response body', status_code=422)
    store = Store()
    result = IssueReporter('synthetic-user', RejectedClient(), store, tmp_path).submit(
        'Synthetic issue description.', 'error', False,
        {'app_version': '3.7.0', 'pacs_user': 'synthetic-user'})
    assert result['http_status'] == 422
    assert result['failure_stage'] == 'http_response'
    assert result['error_code'] == 'ISSUE_REJECTED'
    assert 'Sensitive' not in json.dumps(result)
    assert store.value is not None


def test_bundle_never_exports_raw_patient_or_secret_text(tmp_path):
    (tmp_path/'app.log').write_text('ERROR PatientName=Sensitive token=synthetic-secret RuntimeError\n')
    data = diagnostic_bundle(tmp_path, False)
    text = json.dumps(data)
    assert 'Sensitive' not in text and 'synthetic-secret' not in text
    assert data['logs'][0]['errors'] == 1
    assert data['logs'][0]['exception_signals']['RuntimeError'] == 1
    assert data['windows_state'] == 'not_requested'


def test_source_stack_projection_verifies_module_and_omits_external_paths(tmp_path):
    from PacsClient.utils.support_diagnostics import project_source_frames
    module = tmp_path/'modules'/'synthetic.py'
    module.parent.mkdir()
    module.write_text('# Synthetic code\n')
    text = 'File "C:/private/repo/modules/synthetic.py", line 12, in run\nValueError: private-patient\nFile "C:/patient/secrets.py", line 2, in run\nFile "C:/repo/modules/missing.py", line 2, in run'
    frames = project_source_frames(text, tmp_path)
    assert frames == [{'module':'modules/synthetic.py','line':12,'function':'run'}]
    assert 'private' not in json.dumps(frames) and 'patient' not in json.dumps(frames)


def test_native_fault_files_are_bounded_and_omit_raw_messages_and_legacy_files(tmp_path):
    from PacsClient.utils.support_issue_reporting import collect_native_evidence
    source = tmp_path/'source'
    (source/'modules').mkdir(parents=True)
    (source/'modules'/'synthetic.py').write_text('# Synthetic code\n')
    logs = tmp_path/'logs'
    logs.mkdir()
    (logs/'native_fault.log').write_text('Forbidden legacy content')
    for index in range(5):
        (logs/f'native_fault.{100+index}.{index:032x}.log').write_text(
            'Windows fatal exception: access violation\nPatientName=Private synthetic patient\n'
            'File "C:/repo/modules/synthetic.py", line 12 in run\n')
    result = collect_native_evidence(logs, source)
    assert result['state'] == 'sampled' and len(result['logs']) == 3
    assert result['logs'][0]['signals']['access_violation'] == 1
    assert result['logs'][0]['frames'] == [{'module':'modules/synthetic.py','line':12,'function':'run'}]
    assert 'Private' not in json.dumps(result) and 'Forbidden' not in json.dumps(result)


def test_receipt_and_retry_keep_same_frozen_payload(tmp_path):
    client, store = Client(), Store()
    reporter = IssueReporter('synthetic-user', client, store, tmp_path)
    client.fail = True
    result = reporter.submit('Synthetic freeze occurred.', 'hang', False,
                             {'app_version':'3.7.0', 'pacs_user':'synthetic-user'})
    assert result['state'] == 'pending' and 'Sensitive' not in json.dumps(result)
    UUID(store.value['payload']['client_issue_id'])
    client.fail = False
    recovered = IssueReporter('synthetic-user', client, store, tmp_path)
    result = recovered.retry()
    assert result['state'] == 'received' and store.value is None
    assert client.calls[0] == client.calls[1]


def test_cross_account_or_endpoint_retry_is_refused(tmp_path):
    client, store = Client(), Store()
    client.fail = True
    reporter = IssueReporter('synthetic-user', client, store, tmp_path)
    reporter.submit('Synthetic problem.', 'error', False, {'app_version':'3.7.0','pacs_user':'synthetic-user'})
    with pytest.raises(ValueError):
        IssueReporter('other-user', client, store, tmp_path).retry()
    client.base_url = 'https://other.invalid'
    with pytest.raises(ValueError):
        reporter.retry()


def test_unconfirmed_receipt_is_not_delivery(tmp_path):
    client, store = Client(), Store()
    client.request_json = lambda *a, **kw: {'state':'received', 'issue_id':'invented'}
    result = IssueReporter('synthetic-user', client, store, tmp_path).submit(
        'Synthetic problem.', 'error', False, {'app_version':'3.7.0','pacs_user':'synthetic-user'})
    assert result['state'] == 'pending' and store.value is not None


def test_plain_http_is_only_allowed_on_loopback(tmp_path):
    client = Client()
    client.base_url = 'http://remote.invalid'
    with pytest.raises(ValueError):
        IssueReporter('synthetic-user', client, Store(), tmp_path)


def test_submission_refuses_to_overwrite_pending_issue(tmp_path):
    client, store = Client(), Store()
    client.fail = True
    reporter = IssueReporter('synthetic-user', client, store, tmp_path)
    reporter.submit('Synthetic first issue.', 'error', False, {'app_version':'3.7.0','pacs_user':'synthetic-user'})
    original = store.value
    with pytest.raises(ValueError):
        reporter.submit('Synthetic second issue.', 'hang', False, {'app_version':'3.7.0','pacs_user':'synthetic-user'})
    assert store.value == original


def test_changed_website_credential_refuses_replay(tmp_path):
    client, store = Client(), Store()
    client.fail = True
    reporter = IssueReporter('synthetic-user', client, store, tmp_path)
    reporter.submit('Synthetic issue.', 'error', False, {'app_version':'3.7.0','pacs_user':'synthetic-user'})
    client.support_identity_binding = 'another-credential'
    with pytest.raises(ValueError):
        reporter.retry()


def test_windows_outbox_is_encrypted_and_atomic(tmp_path):
    import os
    if os.name != 'nt':
        pytest.skip('Windows DPAPI')
    from PacsClient.utils.support_issue_reporting import ProtectedOutbox
    store = ProtectedOutbox('synthetic-user', tmp_path)
    store.save({'description':'Synthetic private issue'})
    assert b'Synthetic private issue' not in store.path.read_bytes()
    assert store.load() == {'description':'Synthetic private issue'}
    assert not list(tmp_path.glob('*.tmp'))
    store.clear()
    assert store.load() is None


def test_issue_action_is_typed_local_review_and_has_no_auto_send():
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.EchoMind.secretary.command_envelope import validate_action_entities, CommandPlan
    from modules.EchoMind.secretary.validator import validate_plan
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.validator import validate_plan as server_validate
    from modules.EchoMind.secretary.registry import AdapterRegistry
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.adapters.support_command_adapter import SupportCommandAdapter, SUPPORT_ACTIONS
    assert 'open_support_issue' not in build_command_bus().actions()
    registry = AdapterRegistry()
    registry.register('support', SupportCommandAdapter(), actions=SUPPORT_ACTIONS)
    bus = CommandBus(registry=registry)
    actions = bus.capabilities()['actions']
    action = next(a for a in actions if a['action'] == 'open_support_issue')
    assert action['side_effect'] == 'ui_navigation'
    validate_action_entities('open_support_issue', {'description':'Synthetic issue'})
    with pytest.raises(ValueError):
        validate_action_entities('open_support_issue', {'path':'C:/private'})
    plan = {'action':'open_support_issue','entities':{'description':'Synthetic issue'},'confidence':1.0,
            'needs_confirmation':False, 'reason':'User requested an issue form'}
    assert not validate_plan(plan)[1] and not server_validate(plan)[1]
    result = bus.execute(CommandPlan(action='open_support_issue'))
    assert result.ok is False and result.error_code == 'SUPPORT_FORM_UNAVAILABLE'


def test_form_send_needs_local_review_and_all_io_is_on_worker(monkeypatch):
    import threading
    import time
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PacsClient.utils import support_issue_reporting as reporting
    from PacsClient.pacs.workstation_ui.home_ui.support_issue_dialog import SupportIssueDialog
    from modules.Identity.providers import aipacs_web
    main_thread = threading.get_ident()
    app = QApplication.instance() or QApplication([])
    def wait_until(predicate):
        deadline = time.monotonic()+5
        while not predicate() and time.monotonic()<deadline:
            app.processEvents()
            QTest.qWait(20)
        assert predicate()
    monkeypatch.setattr(reporting.ProtectedOutbox, 'load', lambda self: None)
    observed = []
    class Reporter:
        def __init__(self, *a, **kw):
            observed.append(threading.get_ident())
        def submit(self, text, category, windows, context, occurred_at=None, include_log_archive=False, recordings=()):
            observed.append(threading.get_ident())
            return {'state':'received', 'issue_id':'4b8b9df2-4874-45c7-adc7-7bff88fbcf97','status':'new'}
    monkeypatch.setattr(reporting, 'IssueReporter', Reporter)
    monkeypatch.setattr(aipacs_web, 'get_aipacs_web_client', lambda user: Client())
    import PacsClient.utils
    monkeypatch.setattr(PacsClient.utils, 'get_selectable_server', lambda name: None)
    dialog = SupportIssueDialog('synthetic-user', 'Synthetic center', 'Synthetic problem.')
    events = []
    dialog.deliveryChanged.connect(lambda value: events.append(dict(value)))
    from types import SimpleNamespace
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
    replies, stages = [], []
    observer = SimpleNamespace(_secretary_busy=False,append_output=replies.append,_set_thinking_status=stages.append)
    observer._on_help_ticket_update = lambda value: SecretaryButtonWidget._on_help_ticket_update(observer,value)
    SecretaryButtonWidget._watch_help_ticket(observer,dialog)
    wait_until(lambda: dialog._operation is None)
    assert not dialog.send.isEnabled() and observed == []
    dialog.consent.setChecked(True)
    assert dialog.send.isEnabled()
    dialog.send.click()
    wait_until(lambda: dialog.public_result.get('state') == 'received')
    assert all(t != main_thread for t in observed)
    assert dialog.public_result['ticket_submitted'] is True
    assert 'Synthetic problem' not in json.dumps(dialog.public_result)
    assert not dialog.send.isEnabled()
    assert events[0]['state'] == 'running'
    assert events[-1]['state'] == 'received'
    assert events[-1]['ticket_submitted'] is True
    assert stages[-1] == 'Done'
    assert 'received by AI-PACS support' in replies[-1]
    dialog.close()


def test_future_incident_and_expired_retry_are_refused(tmp_path):
    from datetime import datetime, timedelta, timezone
    client, store = Client(), Store()
    reporter = IssueReporter('synthetic-user', client, store, tmp_path)
    context = {'app_version':'3.7.0','pacs_user':'synthetic-user'}
    with pytest.raises(ValueError):
        reporter.submit('Synthetic issue.', 'error', False, context,
                        occurred_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    assert store.value is None
    client.fail = True
    reporter.submit('Synthetic issue.', 'error', False, context)
    store.value['expires_at'] = (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        reporter.retry()
    assert store.value is None


def test_local_form_rechecks_account_and_connection(monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtTest import QTest
    from PacsClient.utils.support_issue_reporting import ProtectedOutbox
    from PacsClient.pacs.workstation_ui.home_ui.support_issue_dialog import SupportIssueDialog
    monkeypatch.setattr(ProtectedOutbox, 'load', lambda self: None)
    app = QApplication.instance() or QApplication([])
    home = QWidget()
    home.auth_user = {'username':'synthetic-user'}
    home.data_access_panel_widget = SimpleNamespace(server_selected='synthetic-center')
    dialog = SupportIssueDialog('synthetic-user', 'synthetic-center', parent=home)
    assert dialog._context_is_current(True)
    home.auth_user = {'username':'other-user'}
    assert not dialog._context_is_current()
    home.auth_user = {'username':'synthetic-user'}
    home.data_access_panel_widget.server_selected = 'other-center'
    assert not dialog._context_is_current(True)
    QTest.qWait(250)
    app.processEvents()
    dialog.close()
    home.close()


def test_support_mcp_form_uses_assistant_mode_and_status_is_read_only(monkeypatch):
    from tools.testing.aipacs_control_mcp import server
    calls = []
    def send(action, entities, **kwargs):
        calls.append((action, entities, kwargs))
        return {'ok':True}
    monkeypatch.setattr(server, '_send', send)
    assert json.loads(server.support_control('open_support_issue', description='Synthetic issue.'))['ok']
    assert calls[-1] == ('open_support_issue', {'description':'Synthetic issue.'}, {'mode':'assistant'})
    server.support_control('support_issue_status')
    assert calls[-1] == ('support_issue_status', {}, {'mode':'read_only'})


@pytest.fixture(autouse=True)
def isolate_ticket_archive(monkeypatch, tmp_path):
    from PacsClient.utils import data_paths
    monkeypatch.setattr(data_paths, 'USER_DATA_ROOT', tmp_path / 'user-data')


def test_local_ticket_package_retains_audio_logs_and_retry_receipt(tmp_path):
    import base64
    from zipfile import ZipFile
    from PacsClient.utils.support_issue_reporting import HelpTicketArchive
    root = tmp_path / 'help-ticket'
    archive = HelpTicketArchive(root)
    identifier = str(uuid4())
    payload = {'client_issue_id':identifier, 'description':'Synthetic request',
               'diagnostics':{'logs':[]}, 'log_archive':{'base64':base64.b64encode(b'synthetic ZIP').decode()}}
    folder = archive.prepare(payload, (b'RIFFsynthetic recording',))
    archive.receipt(identifier, {'state':'pending'})
    archive.receipt(identifier, {'state':'received'})
    assert identifier in folder.name
    assert json.loads((folder / 'receipt.json').read_text())['state'] == 'received'
    with ZipFile(folder / 'ticket.zip') as package:
        assert package.read('voice-1.wav') == b'RIFFsynthetic recording'
        assert package.read('logs.zip') == b'synthetic ZIP'
        assert package.read('description.txt') == b'Synthetic request'
        assert json.loads(package.read('request.json')) == payload


def test_packaging_failure_prevents_network_submission(tmp_path, monkeypatch):
    client, store = Client(), Store()
    reporter = IssueReporter('synthetic-user', client, store, tmp_path, archive_root=tmp_path / 'archive')
    def fail(*args):
        raise OSError('Synthetic disk failure')
    monkeypatch.setattr(reporter.archive, 'prepare', fail)
    with pytest.raises(OSError):
        reporter.submit('Synthetic issue request.', 'error', False,
                        {'app_version':'3.7.0', 'pacs_user':'synthetic-user'})
    assert not client.calls and store.value is None


def test_package_hash_matches_bytes_and_audio_is_not_in_wire_payload(tmp_path):
    from hashlib import sha256
    client, store = Client(), Store()
    root = tmp_path / 'archive'
    reporter = IssueReporter('synthetic-user', client, store, tmp_path, archive_root=root)
    reporter.submit('Synthetic issue request.', 'error', False,
                    {'app_version':'3.7.0', 'pacs_user':'synthetic-user'}, recordings=(b'RIFFsynthetic',))
    folder, = root.iterdir()
    metadata = json.loads((folder / 'package.json').read_text())
    assert metadata['sha256'] == sha256((folder / 'ticket.zip').read_bytes()).hexdigest()
    assert 'recordings' not in client.calls[0]
    assert not (folder / 'ticket.zip.tmp').exists()

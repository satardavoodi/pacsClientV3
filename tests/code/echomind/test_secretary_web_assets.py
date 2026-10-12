"""Server web retrieval is bounded, session scoped and never executes page text."""
import base64
import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image


def png():
    stream = io.BytesIO()
    Image.new('RGB', (40, 30), 'navy').save(stream, 'PNG')
    return stream.getvalue()


def test_public_url_rejects_private_addresses_and_credentials(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.secretary.web_assets import public_address
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError):
        public_address('https://example.org/image.png')
    with pytest.raises(ValueError):
        public_address('https://user:secret@example.org/image.png')


def test_download_delivers_exact_verified_bytes_and_provenance(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.secretary.web_assets import WebAssets
    raw = png()
    service = WebAssets(tmp_path, fetch=lambda url: (url, 'image/png', raw))
    request = dict(action='server_web_download', session_id='00000000-0000-0000-0000-000000000001',
                   url='https://example.org/image.png')
    result = service.run('owner-one', request)
    file = result['file']
    assert base64.b64decode(file['data']) == raw
    assert file['sha256'] == hashlib.sha256(raw).hexdigest()
    assert file['source_url'] == request['url']
    assert file['name'].endswith('.png')
    assert 'path' not in file
    assert len(list(tmp_path.rglob('*.png'))) == 1


def test_page_result_is_inert_bounded_text_and_actual_links(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.secretary.web_assets import WebAssets
    raw = b'<title>Example</title><script>steal()</script><p>Evidence</p><a href="/figure.png">Figure</a>'
    service = WebAssets(tmp_path, fetch=lambda url: (url, 'text/html', raw))
    result = service.run('owner', dict(action='server_web_read',
        session_id='00000000-0000-0000-0000-000000000001', url='https://example.org/paper'))
    assert 'Evidence' in result['text']
    assert 'steal()' not in result['text']
    assert result['links'][0]['url'] == 'https://example.org/figure.png'


def test_download_rejects_active_content_and_wrong_magic(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.secretary.web_assets import WebAssets
    service = WebAssets(tmp_path, fetch=lambda url: (url, 'image/png', b'<script>run()</script>'))
    with pytest.raises(ValueError):
        service.run('owner', dict(action='server_web_download',
            session_id='00000000-0000-0000-0000-000000000001', url='https://example.org/fake.png'))
    assert not list(tmp_path.rglob('*.png'))


def test_server_web_schemas_have_real_mcp_contracts():
    from modules.EchoMind.secretary.command_envelope import action_entity_schema
    schema = action_entity_schema('server_web_download')
    assert schema and schema['additionalProperties'] is False
    assert 'url' in schema['properties']


@pytest.mark.parametrize('module',[
    'modules.EchoMind.secretary.validator',
    'modules.ai_imaging.eagle_eye_remote.secretary.validation.validator'])
def test_typed_workflow_requires_preceding_actual_receipt_producers(module):
    import importlib
    validator=importlib.import_module(module)
    steps=[{'action':'inspect_course_content','entities':{'course_pk':1}},
           {'action':'server_web_download','entities':{'url':'https://example.org/figure.png'}},
           {'action':'attach_course_asset','entities':{'course_pk':1,'slide_pk':1,
               'expected_digest':'$expected_digest','sha256':'$sha256','purpose':'image'}}]
    normalized,errors=validator.validate_steps(steps)
    assert not errors
    assert normalized[-1]['entities']['sha256']=='$sha256'
    assert validator.validate_steps(steps[-1:])[1]
    assert validator.validate_plan({'action':'server_web_download','entities':{
        'url':'https://example.org/figure.png','path':'arbitrary'},'confidence':1.0,
        'needs_confirmation':False,'reason':'Synthetic'})[1]


def test_workflow_binds_only_completed_operation_checksums():
    from modules.EchoMind.secretary.workflow import build_plan,WorkflowExecutor
    digest='a'*64;sha='b'*64;calls=[]
    def run(action,entities):
        calls.append((action,entities))
        if action=='content_asset_status':
            handle=entities['operation_id']
            return {'ok':True,'data':{'state':'succeeded',**(
                {'content_digest':digest} if handle=='inspect_course_content' else
                {'sha256':sha,'delivered':True} if handle=='server_web_download' else
                {'content_digest':'c'*64,'content_verified':True})}}
        if action=='attach_course_asset':
            assert entities['expected_digest']==digest and entities['sha256']==sha
        return {'ok':True,'data':{'operation_id':action,'state':'pending'}}
    plan=build_plan('Synthetic verified asset',[
        {'action':'inspect_course_content','entities':{'course_pk':1}},
        {'action':'server_web_download','entities':{'url':'https://example.org/image.png'}},
        {'action':'attach_course_asset','entities':{'course_pk':1,'slide_pk':1,
            'expected_digest':'$expected_digest','sha256':'$sha256','purpose':'image'}}])
    assert WorkflowExecutor(run).run(plan).ok
    assert sum(a=='content_asset_status' for a,e in calls)==3


def test_mcp_discovery_exposes_registered_content_handlers():
    from types import SimpleNamespace
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.agent_gateway.mcp_bridge import McpBridge
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.content_assets import CONTENT_ASSET_MODELS
    bus=build_command_bus(orchestrator=SimpleNamespace(_memory_store=None))
    try:
        bridge=McpBridge(list_actions=bus.actions,execute=lambda *a,**k:None)
        assert set(CONTENT_ASSET_MODELS)<=set(t['name'] for t in bridge._tools())
    finally:
        bus.registry._adapters['content_assets'].close()


def test_dynamic_backend_is_explicit_and_isolated_from_file_download(tmp_path):
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.secretary.web_assets import WebAssets
    browser=SimpleNamespace(read=lambda url:{'url':url,'text':'Rendered evidence','backend':'server_playwright'})
    service=WebAssets(tmp_path,browser=browser,fetch=lambda u:(u,'image/png',png()))
    request={'session_id':'00000000-0000-0000-0000-000000000001','url':'https://example.org/figure'}
    assert service.run('owner',dict(request,action='server_web_read'))['backend']=='server_playwright'
    assert service.run('owner',dict(request,action='server_web_download'))['file']['origin']=='public_web_download'


def test_unavailable_browser_does_not_claim_static_page_is_dynamic(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.secretary.web_browser import ServerBrowser
    monkeypatch.setattr('importlib.util.find_spec',lambda name:None)
    browser=ServerBrowser(lambda url:pytest.fail('No network before runtime check'))
    assert not browser.available
    with pytest.raises(ValueError,match='not installed'):
        browser.read('https://example.org')


def test_windows_storage_uses_extended_paths_for_long_session_names(tmp_path):
    import os
    from modules.ai_imaging.eagle_eye_remote.secretary.web_assets import WebAssets
    service=WebAssets(tmp_path/('long-server-data-'*7),fetch=lambda url:(url,'image/png',png()))
    if os.name=='nt':assert str(service.root).startswith('\\\\?\\')
    result=service.run('synthetic-owner',{'action':'server_web_download',
        'session_id':'00000000-0000-0000-0000-000000000001','url':'https://example.org/image.png'})
    assert result['file']['sha256']==hashlib.sha256(png()).hexdigest()


def test_failed_asset_operation_is_terminal_for_workflow_verification():
    from concurrent.futures import Future
    from types import SimpleNamespace
    from modules.EchoMind.secretary.adapters.content_assets_adapter import ContentAssetsAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    from modules.EchoMind.secretary.workflow import build_plan,WorkflowExecutor
    memory=SimpleNamespace(get_conversation=lambda:{'id':'session'})
    adapter=ContentAssetsAdapter(lambda:memory)
    future=Future();future.set_exception(ValueError('Synthetic retrieval failure'))
    adapter.operations['actual-operation']=('session',future)
    calls=[]
    def run(action,entities):
        calls.append(action)
        if action=='content_asset_status':
            return adapter.execute(CommandPlan(action=action,entities=entities),{}).model_dump()
        return {'ok':True,'data':{'operation_id':'actual-operation','state':'pending'}}
    try:
        result=WorkflowExecutor(run).run(build_plan('Synthetic failed asset',[
            {'action':'server_web_download','entities':{'url':'https://example.org/image.png'}}]))
        assert not result.ok and calls==['server_web_download','content_asset_status']
    finally:
        adapter.close()

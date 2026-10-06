"""UI discovery must be bounded, privacy preserving and distinct from execution."""
from types import SimpleNamespace
import pytest


def test_ui_catalog_uses_registered_schemas_not_arbitrary_callbacks():
    from modules.EchoMind.secretary.adapters.ui_observation_adapter import UiObservationAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    bus=SimpleNamespace(capabilities=lambda:{'actions':[{'action':'advanced_search_patients',
        'entities_schema':{'type':'object','properties':{'modality':{'type':'string'}}},
        'typed_entities':True,'assistant_allowed':True,'confirmation_required':False}]})
    adapter=UiObservationAdapter(lambda:None,lambda:bus)
    result=adapter.get_ui_control_catalog(CommandPlan(action='get_ui_control_catalog'),{})
    assert result.ok
    assert result.data['executable_contracts'][0]['action']=='advanced_search_patients'
    assert 'discovery_is_not_execution' in result.data['limits']


def test_screenshot_contract_rejects_remote_urls_and_invalid_pixels():
    from modules.ai_imaging.eagle_eye_remote.secretary.ui_observation import UiImage
    with pytest.raises(ValueError):UiImage.model_validate({'image':'https://synthetic.invalid/screen.png'})


def sample_image():
    import base64,hashlib,io
    from PIL import Image
    from uuid import uuid4
    buffer=io.BytesIO();Image.new('RGB',(32,24),'navy').save(buffer,format='PNG')
    raw=buffer.getvalue()
    return dict(version=1,snapshot_id=str(uuid4()),context_digest='a'*64,
        sha256=hashlib.sha256(raw).hexdigest(),width=32,height=24,
        scope='redacted_controls_only_no_clinical_images',image=base64.b64encode(raw).decode())


def test_live_controls_and_pixels_exclude_sensitive_values_and_clinical_canvas():
    from concurrent.futures import ThreadPoolExecutor
    from PySide6.QtGui import QPixmap,QColor
    from PySide6.QtWidgets import QApplication,QWidget,QPushButton,QLineEdit,QComboBox,QLabel
    from PacsClient.utils.secretary_ui_observation import capture,encode,collect
    from modules.ai_imaging.eagle_eye_remote.secretary.ui_observation import UiImage
    app=QApplication.instance() or QApplication([])
    root=QWidget();root.resize(500,300)
    root.search_btn=QPushButton('Search Patients',root);root.search_btn.setGeometry(20,20,150,30)
    root.patient_id_input=QLineEdit(root);root.patient_id_input.setGeometry(20,65,150,30)
    root.patient_id_input.setText('synthetic-private-patient')
    root.secret=QLineEdit(root);root.secret.setGeometry(20,105,150,30)
    root.secret.setEchoMode(QLineEdit.Password);root.secret.setText('synthetic-secret')
    root.modality=QComboBox(root);root.modality.setGeometry(20,150,150,30)
    root.modality.addItems(['MR','CT','synthetic-private-name'])
    canvas=QLabel(root);canvas.setGeometry(250,50,150,150)
    pixmap=QPixmap(150,150);pixmap.fill(QColor('red'));canvas.setPixmap(pixmap)
    root.show();app.processEvents()
    try:
        metadata,image=capture(root)
        assert 'synthetic-private' not in str(metadata) and 'synthetic-secret' not in str(metadata)
        assert image.pixelColor(300,100)!=QColor('red')
        assert image.pixelColor(30,75)==QColor('#26364a')
        before=metadata['context_digest']
        root.patient_id_input.setText('different-synthetic-patient')
        assert collect(root)[0]['context_digest']!=before
        with ThreadPoolExecutor(max_workers=1) as pool:wire=pool.submit(encode,metadata,image).result()
        assert UiImage.model_validate(wire).width==500
    finally:root.close()


@pytest.mark.parametrize('mutation', ['digest','size','mime','image','extra'])
def test_image_validation_is_strict_and_integrity_bound(mutation):
    from modules.ai_imaging.eagle_eye_remote.secretary.ui_observation import UiImage
    wire=sample_image()
    if mutation=='digest':wire['sha256']='b'*64
    if mutation=='size':wire['width']=1000
    if mutation=='mime':wire['scope']='clinical_dicom'
    if mutation=='image':wire['image']='https://synthetic.invalid/x'
    if mutation=='extra':wire['path']='C:/synthetic.png'
    with pytest.raises(ValueError):UiImage.model_validate(wire)


def test_server_completion_receives_actual_pixels_and_history_excludes_base64(tmp_path,monkeypatch):
    import json
    from uuid import uuid4
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind,RequestFailed
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary
    from modules.ai_imaging.eagle_eye_remote.secretary import service
    (tmp_path/'settings.json').write_text('{}')
    echo=EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'echo')},['synthetic'])
    hosted=Secretary({'history_dir':str(tmp_path/'secretary')},echo)
    wire=sample_image();messages=[];history=[]
    monkeypatch.setattr(hosted,'_route',lambda _: {'modules':['settings'],'reason':'Synthetic'})
    original_begin=hosted.history.begin
    def begin(*args):history.append(args[-1]);return original_begin(*args)
    monkeypatch.setattr(hosted.history,'begin',begin)
    def completion(**kwargs):
        messages.append(kwargs['messages'])
        return json.dumps({'answer':'Synthetic UI explanation'})
    monkeypatch.setattr(service.llm_client,'gapgpt_chat',completion)
    request=dict(protocol=1,request_id=str(uuid4()),phase='plan',text='Explain the current settings UI.',
        language='en',client_time='2026-10-04T12:00:00+03:30',interaction_mode='ask',
        ui_image=wire,question_context={'ui_controls':{'snapshot_id':wire['snapshot_id'],'context_digest':wire['context_digest']}})
    response=hosted.process('synthetic',request)
    assert messages[0][1]['content'][1]['image_url']['url']=='data:image/png;base64,'+wire['image']
    assert response['ui_observation']['sha256']==wire['sha256']
    assert 'image' not in history[0]['ui_image']
    request['request_id']=str(uuid4());request['question_context']['ui_controls']['context_digest']='b'*64
    with pytest.raises(RequestFailed):hosted.process('synthetic',request)


def test_mcp_returns_real_image_content_instead_of_windows_path():
    from modules.agent_gateway.mcp_bridge import McpBridge
    wire=sample_image()
    bridge=McpBridge(list_actions=lambda:['ui_context_status'],execute=lambda *a,**k:{
        'ok':True,'action':'ui_context_status','data':{'state':'ready','ui_image':wire}})
    response=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
        'params':{'name':'ui_context_status','arguments':{'entities':{'snapshot_id':wire['snapshot_id']}}}})
    result=response['result']
    assert result['content'][1]['type']=='image'
    assert result['content'][1]['data']==wire['image']
    assert 'image' not in result['structuredContent']['data']['ui_image']


def test_image_requires_supported_server_before_post(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner
    class Client:
        def json(self,path):return {'secretary':{}}
        def open(self,*a,**k):raise AssertionError('Unsupported image contract must not post')
    monkeypatch.setattr(remote_planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(remote_planner.RemotePlanningError) as error:
            pool.submit(remote_planner.request,'plan','Synthetic',ui_image=sample_image()).result()
    assert error.value.error_code=='UI_OBSERVATION_UNSUPPORTED'


def test_changed_page_and_expiration_invalidate_capture():
    from concurrent.futures import Future
    from PySide6.QtWidgets import QApplication,QWidget,QLineEdit
    from PacsClient.utils.secretary_ui_observation import collect
    from modules.EchoMind.secretary.adapters.ui_observation_adapter import UiObservationAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    import time
    app=QApplication.instance() or QApplication([])
    root=QWidget();root.resize(400,100)
    root.patient_id_input=QLineEdit(root);root.patient_id_input.setText('Synthetic')
    root.show();app.processEvents()
    adapter=UiObservationAdapter(lambda:root,lambda:None)
    metadata,_=collect(root);future=Future();future.set_result(sample_image())
    adapter.pending={'metadata':metadata,'future':future,'created':time.monotonic()}
    plan=CommandPlan(action='ui_context_status',entities={'snapshot_id':metadata['snapshot_id']})
    try:
        root.patient_id_input.setText('Changed')
        assert adapter.ui_context_status(plan,{}).error_code=='UI_CONTEXT_STALE'
        metadata,_=collect(root);plan.entities['snapshot_id']=metadata['snapshot_id']
        adapter.pending={'metadata':metadata,'future':future,'created':time.monotonic()-91}
        assert adapter.ui_context_status(plan,{}).error_code=='UI_CONTEXT_STALE'
    finally:root.close();adapter.pool.shutdown(wait=False)


def test_ui_action_entities_are_strict_and_bounded():
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.ui_controls import UI_CONTROL_MODELS
    for name,invalid in [('get_ui_control_catalog',{'limit':101}),
                         ('get_ui_control_catalog',{'area':'arbitrary_process'}),
                         ('inspect_ui_controls',{'execute_callback':'remove'}),
                         ('capture_ui_context',{'patient_images':True}),
                         ('ui_context_status',{'snapshot_id':'x'*37})]:
        with pytest.raises(ValueError):UI_CONTROL_MODELS[name].model_validate(invalid)


def test_test_mcp_image_return_and_log_redaction(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('ui_test_mcp',Path('tools/testing/aipacs_control_mcp/server.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    wire=sample_image();records=[]
    monkeypatch.setattr(module,'_get_client',lambda:SimpleNamespace(send=lambda *a,**k:
        {'ok':True,'data':{'state':'ready','ui_image':wire}}))
    monkeypatch.setattr(module,'_record',lambda kind,value:records.append(value))
    blocks=module.ui_context_status(wire['snapshot_id'])
    assert blocks[1].type=='image' and blocks[1].data==wire['image']
    assert wire['image'] not in str(records)


@pytest.mark.parametrize('module',['modules.EchoMind.secretary.validator','modules.ai_imaging.eagle_eye_remote.secretary.validation.validator'])
def test_both_planning_validators_accept_ui_actions_and_reject_unknown_fields(module):
    import importlib
    validator=importlib.import_module(module)
    for action,entities in [('get_ui_control_catalog',{'area':'settings','limit':20}),
                            ('inspect_ui_controls',{}),('capture_ui_context',{}),
                            ('ui_context_status',{'snapshot_id':'synthetic-id'})]:
        assert validator.validate_plan_semantics({'action':action,'entities':entities})==[]
        assert validator.validate_plan_semantics({'action':action,'entities':dict(entities,execute='remove')})


def test_inventory_excludes_field_values_secrets_and_generated_trees(tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('catalog_builder',Path('tools/dev/build_secretary_ui_catalog.py'))
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    monkeypatch.setattr(builder,'ROOT',tmp_path)
    folder=tmp_path/'modules/mpr';folder.mkdir(parents=True)
    source=folder/'controls.py'
    source.write_text("def ui(self):\n    self.patient_id_input=QLineEdit()\n    self.patient_id_input.setText('synthetic-private')\n    self.password_input=QComboBox()\n    self.password_input.addItems(['synthetic-secret'])\n    self.modality=QComboBox()\n    self.modality.addItems(['MR','CT'])\n",encoding='utf-8')
    build=folder/'build';build.mkdir();(build/'generated.py').write_text('not valid Python')
    result=builder.build()
    assert result['parse_errors']==[] and len(result['controls'])==3
    assert 'synthetic-private' not in str(result) and 'synthetic-secret' not in str(result)
    assert next(c for c in result['controls'] if c['name']=='self.modality')['options']==['MR','CT']


def test_response_without_same_image_receipt_is_rejected(monkeypatch):
    import io,json
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner
    wire=sample_image()
    class Client:
        def json(self,path):return {'secretary':{'ui_observation':{'version':1}}}
        def open(self,path,body,**kwargs):
            return io.BytesIO(json.dumps({'protocol':1,'request_id':body['request_id'],'phase':'plan',
                'route':{'modules':['homepage'],'reason':'Synthetic'},'plan':None}).encode())
    monkeypatch.setattr(remote_planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(remote_planner.RemotePlanningError) as error:
            pool.submit(remote_planner.request,'plan','Synthetic',ui_image=wire).result()
    assert error.value.error_code=='UI_CONTEXT_MISMATCH'


def test_screen_context_is_an_explicit_user_opt_in():
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app=QApplication.instance() or QApplication([])
    panel=SecretaryResponsePanel(speech_factory=lambda _:None)
    try:
        assert panel.include_screen.text()=='Include screen context'
        assert not panel.include_screen.isChecked()
        panel.include_screen.setChecked(True)
        assert panel.include_screen.isChecked()
    finally:panel.close()

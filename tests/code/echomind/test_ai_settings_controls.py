"""AI settings contracts use temporary settings, no credentials or provider calls."""
import pytest
from PacsClient.utils.assistant_settings_repository import SettingsRepository


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from modules.EchoMind import settings_store
    monkeypatch.setattr(settings_store,'_config_path',lambda:tmp_path/'echomind_settings.json')
    settings_store.save_settings({'stt_provider':'auto','stt_auth_token':'synthetic-secret',
        'stt_custom_base_url':'http://localhost:7777','stt_custom_port':7777})
    return SettingsRepository(tmp_path), settings_store


def test_voice_selection_persists_preserves_private_fields_and_safe_snapshot(isolated):
    repo, store = isolated
    result = repo.execute('set_voice_to_text_preferences', {'provider':'v2t'})
    assert result['saved'] and result['provider'] == 'v2t'
    assert store.get_stt_settings()['auth_token'] == 'synthetic-secret'
    assert store.get_stt_settings()['custom_port'] == 7777
    snapshot = repo.execute('get_ai_settings', {})
    assert snapshot['voice_to_text']['provider'] == 'v2t'
    assert 'synthetic-secret' not in str(snapshot)


def test_company_models_cannot_be_written_as_personal_preferences(isolated):
    repo, store = isolated
    with pytest.raises(ValueError):
        repo.execute('set_personal_ai_preferences', {'secretary_model':'test-model'})
    assert store.get_llm_backend() == 'company'


def test_personal_options_preserve_other_fields_and_require_own_prompt(isolated):
    repo, store = isolated
    store.save_settings({'llm_backend':'openai','openai_api_key':'synthetic-personal-key','openai_base_url':'http://localhost:9999'})
    with pytest.raises(ValueError):
        repo.execute('set_personal_ai_preferences', {'secretary_model':'test-model'})
    store.save_settings({'prompt_secretary_action':'Synthetic user-defined prompt'})
    before = store.get_openai_settings()
    result = repo.execute('set_personal_ai_preferences', {'secretary_model':'test-model','temperature':0.0})
    assert result['saved']
    assert store.get_openai_settings()['secretary_model'] == 'test-model'
    assert store.get_openai_settings()['api_key'] == before['api_key']
    assert store.get_openai_settings()['temperature'] == 0.0


def test_proxy_setting_persists(isolated):
    repo, store = isolated
    result = repo.execute('set_ai_proxy_preferences', {'connection_type':'direct','proxy_port':2082})
    assert result['saved'] and store.get_proxy_settings()['connection_type'] == 'direct'


@pytest.mark.parametrize('action,entities', [
    ('get_ai_settings',{}), ('verify_eagle_eye_connection',{}),
    ('set_voice_to_text_preferences',{'provider':'v2t'}),
    ('set_ai_proxy_preferences',{'connection_type':'socks5','proxy_port':2082}),
    ('set_personal_ai_preferences',{'secretary_model':'test-model'}),
    ('set_eagle_eye_connection',{'url':'https://localhost:8002'}),
])
def test_ai_actions_registered_typed_confirmed_and_polled(action, entities):
    import importlib
    from types import SimpleNamespace
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.EchoMind.secretary.workflow import _default_verify
    from modules.EchoMind.secretary.permissions import decide
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_WRITES
    assert action in build_command_bus(home_widget=SimpleNamespace()).actions()
    for module in ('modules.EchoMind.secretary.validator','modules.ai_imaging.eagle_eye_remote.secretary.validation.validator'):
        plan, errors = importlib.import_module(module).validate_plan(dict(action=action,entities=entities,
            confidence=1.0,needs_confirmation=False,reason='Synthetic request'))
        assert not errors
        assert plan['needs_confirmation'] == (action in SETTINGS_CONTROL_WRITES)
    if action in SETTINGS_CONTROL_WRITES:
        assert not decide(action,mode='read_only',confirmed=True).allowed
        assert decide(action,mode='assistant').requires_confirmation
    assert _default_verify(action,entities).probe_action == 'settings_operation_status'


@pytest.mark.parametrize('action,entities', [
    ('set_voice_to_text_preferences',{'provider':'v2t','auth_token':'blocked'}),
    ('set_voice_to_text_preferences',{'provider':'custom','custom_base_url':'http://example.invalid'}),
    ('set_personal_ai_preferences',{'api_key':'blocked'}),
    ('set_ai_proxy_preferences',{'connection_type':'socks5','proxy_port':99}),
    ('set_eagle_eye_connection',{'url':'https://user:password@example.invalid'}),
    ('set_eagle_eye_connection',{'url':'http://example.invalid'}),
])
def test_ai_credentials_paths_and_unsafe_values_rejected(isolated, action, entities):
    repo,store = isolated
    before = store.load_settings()
    with pytest.raises(ValueError):
        repo.execute(action,entities)
    assert before == store.load_settings()


def test_eagle_connection_verifies_before_saving_and_preserves_pairing(isolated, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    repo,_ = isolated
    original={'url':'https://localhost:8002','token_file':'synthetic-private-file'}
    snapshot={'role':'client','path':'synthetic-path','revision':'synthetic-revision','value':original}
    calls=[]
    monkeypatch.setattr(admin,'load_settings',lambda:snapshot)
    def probe(value):
        calls.append('probe')
        assert value['token_file'] == original['token_file']
        return {'modules':[],'protocol':1}
    def save(path, revision, changes):
        calls.append('save')
        assert changes == {'url':'https://localhost:8003'}
        snapshot['value']={**original,**changes}
    monkeypatch.setattr(admin,'probe_connection',probe)
    monkeypatch.setattr(admin,'save_connection',save)
    result=repo.execute('set_eagle_eye_connection',{'url':'https://localhost:8003'})
    assert calls == ['probe','save'] and result['saved'] and result['credentials_changed'] is False


def test_failed_eagle_probe_never_saves(isolated, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    repo,_=isolated
    monkeypatch.setattr(admin,'load_settings',lambda:{'role':'client','value':{},'path':'unused','revision':None})
    monkeypatch.setattr(admin,'probe_connection',lambda _:(_ for _ in ()).throw(ValueError('Synthetic trust failure')))
    saves=[]
    monkeypatch.setattr(admin,'save_connection',lambda *args:saves.append(args))
    with pytest.raises(ValueError):
        repo.execute('set_eagle_eye_connection',{'url':'https://localhost:8003'})
    assert not saves


def test_ai_form_applies_only_verified_fields_without_secret_reload():
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication,QComboBox,QSpinBox,QDoubleSpinBox,QLabel,QLineEdit
    from PacsClient.pacs.workstation_ui.settings_ui.echomind_settings import EchoMindSettingsWidget
    app=QApplication.instance() or QApplication([])
    provider=QComboBox()
    provider.addItem('Automatic','auto'); provider.addItem('Google','v2t')
    reasoning=QComboBox(); reasoning.addItem('Default','')
    temperature=QDoubleSpinBox(); temperature.setRange(0,2)
    tokens=QSpinBox(); tokens.setRange(1,32000)
    form=SimpleNamespace(provider_combo=provider,stt_timeout_input=QSpinBox(),stt_status=QLabel(),
        openai_reasoning_combo=reasoning,openai_temperature_spin=temperature,openai_max_tokens_spin=tokens,
        openai_eagle_diagnosis_input=QLineEdit(),openai_eagle_screening_input=QLineEdit())
    form.stt_timeout_input.setRange(5,600)
    method=EchoMindSettingsWidget.apply_assistant_preferences
    method(form,'set_voice_to_text_preferences',{'provider':'v2t','timeout_seconds':120})
    assert provider.currentData() == 'v2t' and form.stt_timeout_input.value() == 120
    method(form,'set_personal_ai_preferences',{'preferences':{'reasoning_effort':'high','temperature':0.0,'max_output_tokens':50000}})
    assert reasoning.currentData() == 'high' and temperature.value() == 0
    assert tokens.value() == 50000
    method(form,'set_personal_ai_preferences',{'preferences':{'eagle_eye_model':'test-verify','eagle_eye_screening_model':'test-screen'}})
    assert form.openai_eagle_diagnosis_input.text() == 'test-verify'
    assert form.openai_eagle_screening_input.text() == 'test-screen'
    assert not hasattr(form,'openai_api_key_input')


def test_initial_ai_form_load_keeps_zero_temperature(monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit
    from PacsClient.pacs.workstation_ui.settings_ui import echomind_settings as module
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_openai_settings',lambda:{'temperature':0.0})
    form=SimpleNamespace(_set_combo_value=lambda *args:None,_update_openai_status=lambda:None)
    for name in ('api_key','base_url','eagle_screening','eagle_diagnosis','org','project'):
        setattr(form,'openai_'+name+'_input',QLineEdit())
    for name in ('text_model','report_model','vision_model','secretary_model','transcription_model'):
        setattr(form,'openai_'+name+'_input',QComboBox())
    form.openai_temperature_spin=QDoubleSpinBox(); form.openai_temperature_spin.setRange(0,2)
    form.openai_max_tokens_spin=QSpinBox(); form.openai_max_tokens_spin.setRange(1,100000)
    form.openai_timeout_spin=QSpinBox(); form.openai_timeout_spin.setRange(5,600)
    form.openai_reasoning_combo=QComboBox()
    module.EchoMindSettingsWidget._load_openai_state(form)
    assert form.openai_temperature_spin.value() == 0.0

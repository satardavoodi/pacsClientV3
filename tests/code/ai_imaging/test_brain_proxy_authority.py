"""Shared Brain proxy is revision-bound and cannot be bypassed by caller options."""
import pytest
from modules.ai_imaging.eagle_eye_remote import brain_administration as admin, brain_connection as brain
from modules.ai_imaging.eagle_eye_remote.echomind import runtime

def test_proxy_save_is_revision_bound(tmp_path,monkeypatch):
    import json
    (tmp_path/'settings.json').write_text(json.dumps({'connection_type':'direct','proxy_port':2080}))
    monkeypatch.setattr(admin,'directory',lambda:tmp_path)
    old=admin.snapshot()
    value=admin.save_proxy(old['revision'],{'connection_type':'socks5','proxy_port':2082})
    assert value['proxy']=={'connection_type':'socks5','proxy_port':2082}
    with pytest.raises(ValueError,match='changed'):
        admin.save_proxy(old['revision'],{'connection_type':'direct','proxy_port':2080})

@pytest.mark.parametrize('selected',['server_1','custom'])
def test_selected_proxy_overrides_caller_direct(tmp_path,monkeypatch,selected):
    monkeypatch.setattr(runtime,'company_identity',lambda:('Synthetic','synthetic-key'))
    settings={'brain_server':selected,'connection_type':'socks5','proxy_port':2082,'openai_base_url':'https://example.invalid/v1','openai_api_key':'synthetic','openai_text_model':'own','brain_workflow':'chat','prompt_report_generation':'Own prompt'}
    options={'proxies':{},'json':{'messages':[{'role':'user','content':'Synthetic'}]}}
    class Reply:
        status_code=200
        def json(self):return {}
    def operation():
        assert options['proxies']=={'http':'socks5://127.0.0.1:2082','https':'socks5://127.0.0.1:2082'}
        return Reply()
    with runtime.configuration(tmp_path),runtime.request_context(base=settings):
        brain.send('https://api.gapgpt.app/v1/chat/completions',operation,options=options)

def test_proxy_failure_never_retries_direct(tmp_path,monkeypatch):
    monkeypatch.setattr(runtime,'company_identity',lambda:('Synthetic','synthetic-key'))
    calls=[]
    options={}
    def operation():
        calls.append(dict(options['proxies']))
        raise OSError('Synthetic proxy unavailable')
    with runtime.configuration(tmp_path),runtime.request_context(base={'connection_type':'socks5','proxy_port':2082}):
        with pytest.raises(OSError):
            brain.send('https://api.gapgpt.app/v1/chat/completions',operation,options=options)
    assert calls==[{'http':'socks5://127.0.0.1:2082','https':'socks5://127.0.0.1:2082'}]

@pytest.mark.parametrize('options',[{'connection_type':'invalid','proxy_port':2082},{'connection_type':'socks5','proxy_port':True},{'connection_type':'socks5','proxy_port':0}])
def test_invalid_proxy_is_not_direct_fallback(options):
    with pytest.raises(ValueError):admin.proxy_settings(options)

def test_brain_proxy_ui_roundtrip_and_server_legacy_hidden(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui import brain_connection_settings as ui, echomind_settings as echo
    from modules.ai_imaging.eagle_eye_remote import administration
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui.BrainConnectionWidget,'load',lambda self:None)
    widget=ui.BrainConnectionWidget()
    saved=[]
    monkeypatch.setattr(widget,'execute',lambda operation:saved.append(operation()))
    monkeypatch.setattr(admin,'save_proxy',lambda revision, options: (revision,options))
    widget.snapshot={'revision':'synthetic-revision'}
    widget.proxy_type.setCurrentIndex(widget.proxy_type.findData('socks5'))
    widget.proxy_port.setValue(2082)
    widget.save_proxy()
    assert saved==[('synthetic-revision',{'connection_type':'socks5','proxy_port':2082})]
    monkeypatch.setattr(administration,'settings_role',lambda:'server')
    monkeypatch.setattr(echo.EchoMindSettingsWidget,'_load_initial_state',lambda self:None)
    old=echo.EchoMindSettingsWidget(separate_connections=True)
    assert old.proxy_group.isHidden()
    widget.deleteLater();old.deleteLater();app.processEvents()

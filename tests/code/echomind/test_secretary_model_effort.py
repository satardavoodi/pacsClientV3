"""Synthetic server-owned reasoning payload compatibility; no live credentials."""
import json
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('provider', ['company', 'openai'])
def test_explicit_reasoning_is_sent_without_temperature(monkeypatch, provider):
    from modules.ai_imaging.eagle_eye_remote.echomind.core import llm_client as llm
    session = llm.BackendSession(provider, 'Synthetic', 'synthetic-token', 'https://synthetic.invalid/chat/completions')
    monkeypatch.setattr(llm, '_resolve_active_backend', lambda **kw: session)
    monkeypatch.setattr(llm, '_ensure_socks_proxy_support', lambda *a: None)
    monkeypatch.setattr(llm, '_get_requests_proxies', lambda: None)
    monkeypatch.setattr(llm, '_log_usage', lambda **kw: None)
    sent = []
    def post(url, **kw):
        sent.append(kw['json'])
        return SimpleNamespace(status_code=200, json=lambda: {'choices':[{'message':{'content':'{}'}}],'usage':{}})
    monkeypatch.setattr(llm.echomind_http, 'post', post)
    llm.chat_completion([{'role':'user','content':'Synthetic.'}], model='gpt-6-luna',
                        max_tokens=512, temperature=0, reasoning_effort='low')
    assert sent[0]['reasoning_effort'] == 'low'
    assert 'temperature' not in sent[0]
    assert sent[0]['max_tokens' if provider=='company' else 'max_completion_tokens'] == 512


def test_legacy_company_payload_is_unchanged_without_effort(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.core import llm_client as llm
    monkeypatch.setattr(llm, '_resolve_active_backend', lambda **kw:
        llm.BackendSession('company','Synthetic','synthetic-token','https://synthetic.invalid'))
    monkeypatch.setattr(llm, '_ensure_socks_proxy_support', lambda *a: None)
    monkeypatch.setattr(llm, '_get_requests_proxies', lambda: None)
    monkeypatch.setattr(llm, '_log_usage', lambda **kw: None)
    sent=[]
    monkeypatch.setattr(llm.echomind_http,'post',lambda url,**kw:
        (sent.append(kw['json']) or SimpleNamespace(status_code=200,json=lambda:
        {'choices':[{'message':{'content':'{}'}}]})))
    llm.chat_completion([{'role':'user','content':'Synthetic.'}],model='gpt-5.2',max_tokens=512)
    assert sent[0]['temperature'] == 0.0
    assert 'reasoning_effort' not in sent[0]


def test_secretary_server_config_supplies_effort(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary, llm_client
    (tmp_path/'settings.json').write_text('{}')
    echo=EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'echo')},['synthetic'])
    host=Secretary({'model':'gpt-6-luna','reasoning_effort':'low','history_dir':str(tmp_path/'secretary')},echo)
    sent=[]
    monkeypatch.setattr(llm_client,'gapgpt_chat',lambda **kw:(sent.append(kw) or json.dumps({'modules':['homepage'],'reason':'Synthetic.'})))
    host._completion('Synthetic system.',{'synthetic':True},route=True)
    assert sent[0]['model']=='gpt-6-luna'
    assert sent[0]['reasoning_effort']=='low'
    assert sent[0]['temperature'] is None
    with pytest.raises(ValueError):
        Secretary({'reasoning_effort':'untrusted','history_dir':str(tmp_path/'bad')},echo)

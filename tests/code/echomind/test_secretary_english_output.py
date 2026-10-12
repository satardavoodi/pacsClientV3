"""Input language must never select Secretary output language."""
import json
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

def test_server_company_completion_enforces_english(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.secretary import service
    captured=[]
    def chat(**kwargs):captured.append(kwargs);return '{"answer":"Synthetic answer"}'
    monkeypatch.setattr(service.llm_client,'gapgpt_chat',chat)
    owner=object.__new__(service.Secretary);owner.model='synthetic';owner.reasoning_effort=None
    owner._completion('Synthetic system',{'language':'fa','question':'Synthetic input'})
    messages=captured[0]['messages']
    assert 'English' in messages[0]['content']
    assert 'clarification' in messages[0]['content']
    assert json.loads(messages[1]['content'])['language']=='en'




def test_client_requests_english_even_for_auto_or_fa(monkeypatch):
    import pytest
    from modules.EchoMind.secretary import remote_planner
    captured=[]
    class Client:
        def open(self,path,body,**kwargs):
            captured.append(body)
            raise RuntimeError('Synthetic transport stop')
    monkeypatch.setattr(remote_planner,'Client',Client)
    for language in ('auto','fa','en'):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(Exception):pool.submit(remote_planner.request,'plan','Synthetic unchanged input',language=language).result()
        assert captured[-1]['language']=='en'
        assert captured[-1]['text']=='Synthetic unchanged input'

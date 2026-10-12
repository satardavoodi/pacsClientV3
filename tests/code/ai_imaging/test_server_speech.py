"""Synthetic audio only; no external speech calls or clinical fixtures."""
import base64
from contextlib import nullcontext
from uuid import uuid4

import pytest
from modules.ai_imaging.eagle_eye_remote import speech
from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed


def payload():
    return dict(protocol=1, request_id=str(uuid4()), feature='echomind',
                audio_base64=base64.b64encode(b'synthetic-audio').decode(),
                format='wav', quality_mode='clear')


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setattr(speech, 'configuration', lambda path: nullcontext())
    monkeypatch.setattr(speech, 'request_context', lambda: nullcontext())
    monkeypatch.setattr(speech, 'company_identity', lambda: ('synthetic-center', 'synthetic-key'))
    return speech.Speech(tmp_path)


def test_server_continuation_order_and_redacted_response(service, monkeypatch):
    calls=[]
    def attempt(provider, key, audio, body):
        calls.append(provider)
        assert audio==b'synthetic-audio'
        if provider!='company_1': raise RuntimeError('sensitive upstream details')
        return dict(transcript='Synthetic transcript', accepted=True)
    monkeypatch.setattr(service, '_attempt', attempt)
    result=service.process(payload())
    assert calls==['whisper','company_1']
    assert result['route_used']=='company_1'
    assert 'synthetic-key' not in repr(result)


def test_quality_rejection_does_not_repeat_recognition(service, monkeypatch):
    calls=[]
    monkeypatch.setattr(service, '_attempt', lambda provider,*args:
        calls.append(provider) or dict(transcript='Synthetic transcript',accepted=False))
    assert service.process(payload())['accepted'] is False
    assert calls==['whisper']


@pytest.mark.parametrize('changes', [{'audio_base64':'***'}, {'format':'exe'},
    {'feature':'unknown'}, {'request_id':'invalid'}, {'url':'https://untrusted.invalid'},
    {'audio_base64':''}, {'protocol':2}, {'protocol':True}])
def test_invalid_audio_contract_never_calls_upstream(service, monkeypatch, changes):
    monkeypatch.setattr(service, '_attempt', lambda *args: pytest.fail('Unexpected upstream'))
    with pytest.raises(RequestFailed) as error: service.process({**payload(),**changes})
    assert error.value.status==422


def test_credentials_missing_is_redacted_and_slot_released(service, monkeypatch):
    def unavailable(): raise ValueError('private credential detail')
    monkeypatch.setattr(speech, 'company_identity', unavailable)
    for _ in range(3):
        with pytest.raises(RequestFailed) as error: service.process(payload())
        assert error.value.status==503
        assert 'private' not in str(error.value)


def test_all_failures_return_no_provider_details(service, monkeypatch):
    calls=[]
    monkeypatch.setattr(service, '_attempt', lambda provider,*args: calls.append(provider))
    with pytest.raises(RequestFailed) as error: service.process(payload())
    assert calls==['whisper','company_1','company_2']
    assert error.value.status==503


@pytest.mark.parametrize('provider', ['whisper','company_1','company_2'])
def test_upstream_wire_uses_server_selected_origin_and_audio_only(monkeypatch, provider):
    calls=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'text':'Synthetic','transcript':'Synthetic','private':'discard'}
        def close(self): calls.append('closed')
    def post(url,**kwargs):
        assert 'synthetic-key' not in url
        assert kwargs['headers']=={'Authorization':'Bearer synthetic-key'}
        assert kwargs['timeout']==45
        if provider=='whisper':
            assert url=='https://api.gapgpt.app/v1/audio/transcriptions'
            assert kwargs['files']['file'][1]==b'synthetic-audio'
            assert kwargs['data']=={'model':'gapgpt/whisper-1'}
        else:
            assert url.endswith('/generate_transcript')
            assert kwargs['files'][0][0]=='audio_files'
            assert kwargs['data']=={'quality_mode':'clear'}
        return Response()
    monkeypatch.setattr(speech.echomind_http,'post',post)
    result=speech.Speech._attempt(provider,'synthetic-key',b'synthetic-audio',payload())
    assert result=={'transcript':'Synthetic','accepted':True}
    assert calls==['closed']

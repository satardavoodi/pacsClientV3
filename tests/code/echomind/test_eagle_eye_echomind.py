"""Synthetic acceptance of EchoMind on the authenticated Eagle Eye listener."""
from http.server import ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request

import pytest

from modules.ai_imaging.eagle_eye_remote import server


@pytest.fixture
def endpoint():
    class Jobs:
        def recent(self, owner):
            return []

    class EchoMind:
        capabilities = {'workflows': ['report', 'web_search', 'standardize_assist']}

        def process(self, owner, body):
            assert owner == 'synthetic-client'
            return {'content': 'Synthetic response.', 'workflow': body['workflow']}

    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(
        Jobs(), {'synthetic-client': 'test-token'}, echomind=EchoMind()))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}'
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)


def call(endpoint, path, body=None, token='test-token'):
    request = urllib.request.Request(endpoint + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


@pytest.mark.parametrize('workflow', ['report', 'web_search', 'standardize_assist'])
def test_eagle_eye_listener_accepts_server_owned_echomind(endpoint, workflow):
    body = call(endpoint, '/v1/echomind/process', {'text': 'Synthetic.', 'workflow': workflow})
    assert body == {'content': 'Synthetic response.', 'workflow': workflow}


def test_capabilities_declare_echomind_without_removing_models(endpoint):
    value = call(endpoint, '/v1/capabilities')
    assert 'web_search' in value['echomind']['workflows']
    assert len(value['modules']) == 7
    assert value['interactive_edits'] is True


def test_echomind_cannot_bypass_eagle_eye_authentication(endpoint):
    with pytest.raises(urllib.error.HTTPError) as error:
        call(endpoint, '/v1/echomind/process', {'text': 'Synthetic.', 'workflow': 'report'}, token='wrong')
    assert error.value.code == 401


def test_client_does_not_authenticate_to_the_old_pacs_endpoint(monkeypatch):
    from modules.EchoMind import remote_backend as remote
    from modules.ai_imaging.eagle_eye_remote.client import Client
    import io
    calls = []

    monkeypatch.setattr(remote, 'selected', lambda: True)
    monkeypatch.setattr(Client, '__init__', lambda self: None)

    def opened(self, path, body=None, method=None, *, timeout=30):
        calls.append((path, body, timeout))
        return io.BytesIO(b'{"content":"Synthetic."}')

    monkeypatch.setattr(Client, 'open', opened)
    monkeypatch.setattr(remote.requests.Session, 'post', lambda *a, **kw: pytest.fail('Legacy PACS request'))
    assert remote.web_search('Synthetic.')['content'] == 'Synthetic.'
    assert calls == [('/v1/echomind/process', {'text': 'Synthetic.', 'provider': 'company',
                      'workflow': 'web_search', 'response_format': 'json'}, 360)]

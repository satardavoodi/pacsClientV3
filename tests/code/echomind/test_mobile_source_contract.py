"""Android-shaped requests exercise the real authenticated host and source parser."""
import base64
import io
import json
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from modules.ai_imaging.eagle_eye_remote import server
from modules.ai_imaging.eagle_eye_remote.echomind import hosting, service
from tests.code.ai_imaging.human_access_fixture import human_access, session_headers


def source(ext):
    data = b'Synthetic measurement 24 mm.'
    if ext == 'json':
        data = b'{"Report":"Synthetic measurement 24 mm."}'
    elif ext == 'html':
        data = b'<p>Synthetic measurement 24 mm.</p>'
    elif ext == 'png':
        stream = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(stream, format='PNG')
        data = stream.getvalue()
    elif ext == 'pdf':
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 10 200 Td (Synthetic measurement 24 mm.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        data = output.getvalue()
    return {'name': 'eagle-eye-report.' + ext, 'data': base64.b64encode(data).decode()}


@pytest.fixture
def endpoint(tmp_path, monkeypatch, human_access):
    (tmp_path / 'settings.json').write_text('{}')
    host = hosting.EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'history')}, ['android-test'])
    calls = []
    def reporter(text, modality, template, **kw):
        calls.append(('report', kw['attachment_parts']))
        return {'content': json.dumps([{'Report': 'Synthetic result'}])}
    def correction(text, note, **kw):
        calls.append(('correction', text))
        assert '24 mm' in text
        assert note == 'Improve wording only.'
        return {'content': [{'Report': 'Synthetic corrected result'}]}
    monkeypatch.setattr(service.company, 'reporter', reporter)
    monkeypatch.setattr(service.company, 'correction', correction)
    class Jobs:
        def submit(self, *args, **kwargs):
            pytest.fail('EchoMind must not submit imaging jobs')
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(
        Jobs(), {'android-test': 'synthetic-token'}, echomind=host, license_guard=lambda: True,
        user_authority=human_access))
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    headers = session_headers(f'http://127.0.0.1:{http.server_port}', 'synthetic-token')
    def call(path, payload=None, token='synthetic-token'):
        request = Request(f'http://127.0.0.1:{http.server_port}' + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={**headers, 'Authorization': 'Bearer ' + token})
        with urlopen(request, timeout=5) as response:
            return json.load(response)
    try:
        yield call, calls
    finally:
        http.shutdown()
        http.server_close()
        thread.join(5)


@pytest.mark.parametrize('workflow', ['report', 'turbo'])
@pytest.mark.parametrize('ext', ['txt', 'pdf', 'png'])
def test_mobile_report_upload(endpoint, workflow, ext):
    call, calls = endpoint
    caps = call('/v1/capabilities')
    assert 'report_attachments_v1' in caps['echomind']['features']
    result = call('/v1/echomind/process', {'text': 'Prepare report.', 'workflow': workflow,
        'provider': 'company', 'response_format': 'json', 'attachments': [source(ext)]})
    assert result['content'] and result['request_id']
    assert json.loads(result['content']) == [{'Report': 'Synthetic result'}]
    assert calls[0][1][0]['type'] == ('image_url' if ext == 'png' else 'text')


@pytest.mark.parametrize('ext', ['json', 'html', 'txt', 'pdf'])
def test_mobile_saved_correction(endpoint, ext):
    call, calls = endpoint
    assert 'correction_sources_v1' in call('/v1/capabilities')['echomind']['features']
    result = call('/v1/echomind/process', {'text': 'Correct saved source.', 'workflow': 'correction',
        'provider': 'company', 'correction_note': 'Improve wording only.', 'correction_source': source(ext)})
    assert result['content'] and len(calls) == 1


def test_mobile_source_requires_auth(endpoint):
    call, calls = endpoint
    with pytest.raises(HTTPError) as error:
        call('/v1/echomind/process', {'text': 'Prepare report.', 'attachments': [source('txt')]}, token='invalid')
    assert error.value.code == 401
    assert not calls

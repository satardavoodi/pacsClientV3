"""Saved source bytes reach server normalization and the existing correction model."""
import base64
import json
import pytest
from modules.EchoMind.correction_source import pack, unpack
from modules.ai_imaging.eagle_eye_remote.echomind import service


@pytest.mark.parametrize('name,data,expected', [
    ('report.json', b'{"Report":"EF 60%"}', 'EF 60%'),
    ('report.html', b'<style>hidden</style><p>EF 60%</p>', 'EF 60%'),
    ('report.txt', b'No effusion.', 'No effusion.'),
])
@pytest.mark.parametrize('turbo', [False, True])
def test_server_correction_receives_decoded_report(monkeypatch, name, data, expected, turbo):
    seen = {}
    def correction(report, note, **options):
        seen.update(report=report, note=note, **options)
        return {'content': report}
    monkeypatch.setattr(service.company, 'correction', correction)
    request = service.ProcessRequest(text='Uploaded source', workflow='correction',
        correction_note='Correct the wording.', turbo_correction=turbo,
        correction_source=unpack(pack(name, data)))
    service._process(request)
    assert expected in seen['report']
    assert 'hidden' not in seen['report']
    assert seen['note'] == 'Correct the wording.'
    assert 'unverified source findings' in seen['system_prompt_prefix']


def test_client_passes_original_bytes(monkeypatch):
    from modules.EchoMind import remote_backend
    seen = {}
    def request(workflow, text, **fields):
        seen.update(fields)
        assert workflow == 'correction'
        return {'content': 'Synthetic corrected report'}
    monkeypatch.setattr(remote_backend, '_request', request)
    remote_backend.correction(pack('report.html', b'<p>Original</p>'), 'Fix wording')
    assert base64.b64decode(seen['correction_source']['data']) == b'<p>Original</p>'


def test_source_rejected_outside_correction():
    with pytest.raises(service.WorkflowError):
        service._process(service.ProcessRequest(text='test', correction_source=unpack(pack('report.txt', b'test'))))


def test_unreadable_pdf_fails_before_provider(monkeypatch):
    monkeypatch.setattr(service.company, 'correction', lambda *a, **k: pytest.fail('Must not call provider'))
    with pytest.raises(service.WorkflowError, match='Cannot read'):
        service._process(service.ProcessRequest(text='test', workflow='correction', correction_note='Fix',
            correction_source=unpack(pack('report.pdf', b'invalid pdf'))))

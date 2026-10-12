"""Synthetic attachment parsing and server routing; no patient data or live AI."""
import base64
import io
import zipfile

import pytest
from PIL import Image
from modules.EchoMind.report_attachments import encode_attachments
from modules.ai_imaging.eagle_eye_remote.echomind.attachments import Attachment, content_parts
from modules.ai_imaging.eagle_eye_remote.echomind import service


def item(name, raw):
    return Attachment(name=name, data=base64.b64encode(raw).decode())


def test_text_docx_and_image(tmp_path):
    path = tmp_path / 'source.txt'
    path.write_text('Synthetic measurement: 24 x 34 mm.', encoding='utf-8')
    assert '24 x 34 mm' in content_parts([Attachment(**encode_attachments([path])[0])])[0]['text']
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>EF 60%</w:t></w:r></w:p></w:body></w:document>')
    assert 'EF 60%' in content_parts([item('source.docx', raw.getvalue())])[0]['text']
    image = io.BytesIO()
    Image.new('RGB', (10, 10), 'white').save(image, format='PNG')
    assert content_parts([item('source.png', image.getvalue())])[0]['image_url']['url'].startswith('data:image/jpeg;base64,')


@pytest.mark.parametrize('name,raw', [('bad.pdf', b'not pdf'), ('bad.docx', b'not zip'),
    ('bad.png', b'not image'), ('bad.txt', b'\xff'), ('empty.txt', b''), ('bad.doc', b'legacy')])
def test_invalid_files_fail_explicitly(name, raw):
    with pytest.raises(Exception):
        content_parts([item(name, raw)])


def test_no_silent_truncation_or_path_fetch(tmp_path):
    path = tmp_path / 'large.txt'
    path.write_bytes(b'x' * (1024 * 1024 + 1))
    with pytest.raises(ValueError):
        encode_attachments([path])
    with pytest.raises(ValueError):
        encode_attachments([path] * 7)
    with pytest.raises(ValueError):
        content_parts([item('long.txt', b'x' * 100001)])
    with pytest.raises(ValueError):
        Attachment(name='url.txt', data='abc', url='https://example.invalid')


@pytest.mark.parametrize('workflow', ['report', 'turbo'])
def test_server_owns_prompt_and_receives_parts(monkeypatch, workflow):
    captured = {}
    def reporter(text, modality, template, **kwargs):
        captured.update(kwargs)
        return {'content': 'Synthetic report'}
    monkeypatch.setattr(service.company, 'reporter', reporter)
    request = service.ProcessRequest(text='Analyze source', workflow=workflow,
        attachments=[item('source.txt', b'EF 60%')])
    assert service._process(request)['content'] == 'Synthetic report'
    assert 'EF 60%' in captured['attachment_parts'][0]['text']
    assert 'system_prompt_override' in captured
    assert captured['system_prompt_override']


def test_unsupported_workflow_never_drops_files():
    with pytest.raises(service.WorkflowError):
        service._process(service.ProcessRequest(text='test', workflow='correction',
            attachments=[item('source.txt', b'test')]))


def test_client_upload_is_worker_prepared(monkeypatch, tmp_path):
    from modules.EchoMind import remote_backend
    captured = {}
    path = tmp_path / 'source.txt'
    path.write_text('Synthetic')
    def request(workflow, text, **fields):
        captured.update(fields)
        assert text
        return {'content': 'Synthetic response'}
    monkeypatch.setattr(remote_backend, '_request', request)
    remote_backend.reporter('', attachment_paths=[path])
    assert base64.b64decode(captured['attachments'][0]['data']) == b'Synthetic'


def test_composer_clipboard_and_document_lifecycle(tmp_path):
    from PySide6.QtWidgets import QApplication
    from modules.EchoMind.viewer_chat.ai_chat_widgets import UnifiedComposer
    app = QApplication.instance() or QApplication([])
    composer = UnifiedComposer()
    app.clipboard().setText('Synthetic physician dictation')
    composer.copy_from_clipboard()
    assert composer.box.toPlainText() == 'Synthetic physician dictation'
    path = str(tmp_path / 'source.docx')
    composer._choose_file(path)
    assert composer.get_report_attachments() == (path,)
    assert composer.get_all_image_attachments() == []
    composer.clear_image_attachments()
    assert not composer.get_report_attachments()
    composer.close()
    composer.deleteLater()


def test_source_prompt_preserves_reporting_role():
    from modules.ai_imaging.eagle_eye_remote.echomind.attachments import REPORT_SOURCE_INSTRUCTIONS
    assert 'equivalent to a dictated transcript' in REPORT_SOURCE_INSTRUCTIONS
    assert 'OCR visible writing' in REPORT_SOURCE_INSTRUCTIONS
    assert 'not a file summary' in REPORT_SOURCE_INSTRUCTIONS
    assert 'do not infer new findings from scan pixels' in REPORT_SOURCE_INSTRUCTIONS

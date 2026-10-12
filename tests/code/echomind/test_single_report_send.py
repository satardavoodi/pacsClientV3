"""One report Send action; server owns upstream selection and fallback."""
import ast
from pathlib import Path

import pytest
from tests.code.echomind.test_remote_backend import transport


def test_composer_has_one_labeled_send_and_no_turbo():
    from PySide6.QtWidgets import QApplication, QToolButton
    from modules.EchoMind.viewer_chat.ai_chat_widgets import UnifiedComposer
    app = QApplication.instance() or QApplication([])
    composer = UnifiedComposer()
    try:
        assert composer.btn_send.text() == 'Send'
        assert composer.btn_send.accessibleName() == 'Send'
        assert not hasattr(composer, 'btn_all_modality_hq')
        assert all('turbo' not in button.text().lower() for button in composer.findChildren(QToolButton))
        composer.set_enabled(False)
        assert not composer.btn_send.isEnabled()
        composer.set_enabled(True)
        assert composer.btn_send.isEnabled()
    finally:
        composer.deleteLater()
        app.processEvents()


def test_page_has_no_separate_turbo_handler_or_signal():
    source = Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert '_on_hq_all_modality_clicked' not in names
    assert '_turbo_correction' not in names
    assert 'btn_all_modality_hq' not in source


def test_company_report_is_one_normal_request_with_no_client_selection(monkeypatch):
    from modules.EchoMind import remote_backend
    calls = []
    monkeypatch.setattr(remote_backend, '_request', lambda workflow, text, **fields:
        (calls.append((workflow, text, fields)), dict(content='Synthetic report'))[1])
    remote_backend.reporter('Synthetic dictation', 'MR')
    assert calls == [('report', 'Synthetic dictation', dict(modality='MR', normal_template=''))]
    with pytest.raises(TypeError):
        remote_backend.reporter('Synthetic dictation', 'MR', workflow='turbo')
    assert len(calls) == 1


def test_company_failure_never_sends_second_client_report(monkeypatch):
    from modules.EchoMind import remote_backend
    calls = []
    def failed(*args, **kwargs):
        calls.append(args)
        raise remote_backend.RemoteError('Synthetic upstream failure')
    monkeypatch.setattr(remote_backend, '_request', failed)
    with pytest.raises(remote_backend.RemoteError):
        remote_backend.reporter('Synthetic dictation', 'CT')
    assert len(calls) == 1


def test_attachment_failure_is_actionable_and_never_drops_sources(monkeypatch):
    from modules.EchoMind import remote_backend, report_attachments
    calls = []
    monkeypatch.setattr(report_attachments, 'encode_attachments', lambda paths: ['synthetic-source'])
    def failed(*args, **fields):
        calls.append(fields)
        raise remote_backend.RemoteError('Synthetic upstream failure', status=502)
    monkeypatch.setattr(remote_backend, '_request', failed)
    with pytest.raises(remote_backend.RemoteError, match='attachments remain') as failure:
        remote_backend.reporter('Synthetic dictation', 'CT', attachment_paths=['synthetic.pdf'])
    assert failure.value.status == 502
    assert calls == [dict(modality='CT', normal_template='', attachments=['synthetic-source'])]


@pytest.mark.parametrize('workflow,expected', [('report', 480), ('chat', 360), ('correction', 360)])
def test_only_company_report_has_two_upstream_time_budget(transport, workflow, expected):
    from modules.EchoMind import remote_backend
    remote_backend._request(workflow, 'Synthetic request')
    assert len(transport) == 1
    assert transport[0][1]['timeout'] == expected

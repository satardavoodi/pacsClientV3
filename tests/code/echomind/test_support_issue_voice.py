"""Synthetic microphone/STT tests; no real audio device or network."""
import struct
import threading
from pathlib import Path
import time

from PacsClient.utils.support_issue_voice import IssueVoiceTake


def install_audio(monkeypatch, take, calls):
    import sounddevice
    from modules.EchoMind.voice_transcription import VoiceTranscriptionService

    class Stream:
        def __init__(self, **options):
            self.callback = options['callback']
            calls.append(('microphone', threading.get_ident()))
        def __enter__(self):
            self.callback(struct.pack('<h', 1200)*16000, 16000, None, None)
            take.stop()
        def __exit__(self, *args):
            calls.append(('closed', threading.get_ident()))

    def transcribe(self, paths, **options):
        path = Path(paths[0])
        assert path.is_file()
        assert options == {'quality_mode':'clear', 'timeout':120}
        calls.append(('transcription', threading.get_ident(), path))
        return {'ok':True, 'transcript':'Synthetic application stopped responding.'}

    monkeypatch.setattr(sounddevice, 'RawInputStream', Stream)
    monkeypatch.setattr(VoiceTranscriptionService, 'transcribe', transcribe)


def test_voice_capture_and_stt_stay_on_worker_and_wav_is_removed(monkeypatch):
    take, calls, result = IssueVoiceTake(), [], []
    install_audio(monkeypatch, take, calls)
    owner = threading.get_ident()
    worker = threading.Thread(target=lambda: result.append(take.run()))
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    assert result[0] == {'state':'voice_transcribed', 'text':'Synthetic application stopped responding.'}
    assert all(item[1] != owner for item in calls)
    assert not calls[-1][2].exists()


def test_cancelled_take_never_transcribes(monkeypatch):
    take, calls = IssueVoiceTake(), []
    install_audio(monkeypatch, take, calls)
    take.cancel()
    assert take.run() == {'state':'voice_cancelled'}
    assert not any(item[0] == 'transcription' for item in calls)


def test_bad_quality_text_is_not_accepted_and_errors_do_not_expose_details(monkeypatch):
    from modules.EchoMind.voice_transcription import VoiceTranscriptionService
    take, calls = IssueVoiceTake(), []
    install_audio(monkeypatch, take, calls)
    monkeypatch.setattr(VoiceTranscriptionService, 'transcribe', lambda *a, **k: {'ok':True, 'accepted':False, 'transcript':'Unsafe uncertain text'})
    assert take.run() == {'state':'voice_failed'}


def test_form_voice_populates_text_requires_new_consent_and_never_submits(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PacsClient.utils import support_issue_voice, support_issue_reporting
    from PacsClient.pacs.workstation_ui.home_ui.support_issue_dialog import SupportIssueDialog
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(support_issue_reporting.ProtectedOutbox, 'load', lambda self: None)
    observed = []

    class Take(IssueVoiceTake):
        def run(self):
            observed.append(threading.get_ident())
            self.stopped.wait(5)
            return {'state':'voice_transcribed', 'text':'Synthetic dictated issue.'}

    monkeypatch.setattr(support_issue_voice, 'IssueVoiceTake', Take)
    dialog = SupportIssueDialog('synthetic-user', description='Existing text.')
    def wait(predicate):
        deadline = time.monotonic()+5
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(20)
        assert predicate()
    wait(lambda: dialog._operation is None)
    assert not dialog.voice.icon().isNull()
    dialog.consent.setChecked(True)
    dialog.voice.click()
    assert not dialog.send.isEnabled()
    assert dialog.voice.text() == 'Stop and transcribe'
    dialog.voice.click()
    wait(lambda: dialog._operation is None)
    assert dialog.description.toPlainText() == 'Existing text.\n\nSynthetic dictated issue.'
    assert not dialog.consent.isChecked() and not dialog.send.isEnabled()
    assert observed[0] != threading.get_ident()
    assert dialog.public_result['ticket_submitted'] is False
    dialog.close()


def test_changed_account_discards_transcript_and_close_cancels_recording(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PacsClient.utils import support_issue_voice, support_issue_reporting
    from PacsClient.pacs.workstation_ui.home_ui.support_issue_dialog import SupportIssueDialog
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(support_issue_reporting.ProtectedOutbox, 'load', lambda self: None)
    takes = []
    class Take(IssueVoiceTake):
        def __init__(self):
            super().__init__()
            takes.append(self)
        def run(self):
            self.stopped.wait(5)
            return {'state':'voice_transcribed', 'text':'Stale transcript'}
    monkeypatch.setattr(support_issue_voice, 'IssueVoiceTake', Take)
    def wait(predicate):
        deadline = time.monotonic()+5
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(20)
        assert predicate()
    dialog = SupportIssueDialog('synthetic-user', description='Existing text.')
    wait(lambda: dialog._operation is None)
    dialog.voice.click()
    dialog.user = 'changed-account'
    dialog.voice.click()
    wait(lambda: dialog._operation is None)
    assert dialog.description.toPlainText() == 'Existing text.'
    dialog.voice.click()
    dialog.close()
    assert takes[-1].cancelled.is_set()
    assert not dialog._timer.isActive()


def test_retained_ticket_audio_survives_temporary_file_cleanup(monkeypatch):
    take, calls = IssueVoiceTake(retain_audio=True), []
    install_audio(monkeypatch, take, calls)
    result = take.run()
    assert result['recording'].startswith(b'RIFF')
    assert result['text'] == 'Synthetic application stopped responding.'
    assert not calls[-1][2].exists()

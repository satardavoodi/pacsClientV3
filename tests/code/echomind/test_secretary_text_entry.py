"""Typed commands reuse the post-transcription Secretary pipeline."""
from types import SimpleNamespace


def test_typed_input_reuses_shared_callback_without_recording():
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
    received=[]
    host=SimpleNamespace(_rec_running=False,_secretary_busy=False,
                         _secretary_transcript_ready=received.append)
    assert SecretaryButtonWidget.submit_text_command(host,'Synthetic command')
    assert host._secretary_busy
    assert received[0]['transcript']=='Synthetic command'
    assert received[0]['stt_req']['route']=='typed'


def test_recording_or_busy_pipeline_rejects_concurrent_text():
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
    for recording,busy in ((True,False),(False,True)):
        host=SimpleNamespace(_rec_running=recording,_secretary_busy=busy)
        assert not SecretaryButtonWidget.submit_text_command(host,'Synthetic command')

"""Exact synthetic voice/report retrieval, unsafe inventory and case denial."""
import base64
from pathlib import Path

import pytest
from modules.ai_imaging.eagle_eye_remote.pacs_resources import PacsResources

CASE = {'study_uid': '1.2.3', 'patient_id': 'synthetic'}


class Resources(PacsResources):
    def __init__(self):
        super().__init__(CASE, 'synthetic', 50052, 'synthetic-token')
        self.row = dict(file_name='synthetic.wav', file_size=9, attachment_type='audio')
        self.identity = dict(CASE)
        self.requests = []
    def request(self, endpoint, params, **kwargs):
        self.requests.append((endpoint, params))
        if endpoint == 'GetWorkflowStates':
            return dict(realtime_version=1, states=[self.identity])
        return dict(self.identity, attachments=[dict(self.row,
            attachment_data=base64.b64encode(b'synthetic').decode())])


def test_original_voice_is_selected_verified_and_published_atomically(tmp_path):
    resources = Resources()
    row = resources.inventory('audio')[0]
    file = Path(resources.download(row, tmp_path))
    assert file.read_bytes() == b'synthetic'
    assert resources.requests[-1][1]['names'] == ['synthetic.wav']
    assert Path(resources.download(row, tmp_path)) == file
    assert len(list(tmp_path.glob('*.wav'))) == 1
    assert not list(tmp_path.glob('*.partial'))


def test_patient_change_prevents_file_read_and_publication(tmp_path):
    resources = Resources()
    resources.identity['patient_id'] = 'other'
    with pytest.raises(ValueError):
        resources.download(resources.row, tmp_path)
    assert not list(tmp_path.iterdir())
    assert all(endpoint == 'GetWorkflowStates' for endpoint, _ in resources.requests)


@pytest.mark.parametrize('name', ['../synthetic.wav', 'C:/synthetic.wav', 'synthetic.exe', 'a\\b.wav'])
def test_unsafe_server_file_names_are_not_downloadable(name):
    resources = Resources()
    resources.row['file_name'] = name
    assert resources.inventory() == []


def test_legacy_study_recording_is_verified_again_before_publication(tmp_path):
    resources = Resources()
    original = resources.request
    resources.identity['legacy_audio'] = True
    def request(endpoint, params, **kwargs):
        if endpoint == 'GetStudyAudio':
            return dict(audio_data=base64.b64encode(b'synthetic').decode(),
                        audio_format='wav', audio_file_size=9)
        return original(endpoint, params, **kwargs)
    resources.request = request
    rows = resources.inventory('audio')
    assert rows[-1]['legacy'] is True
    file = Path(resources.download(rows[-1], tmp_path))
    assert file.read_bytes() == b'synthetic'
    assert sum(endpoint == 'GetWorkflowStates' for endpoint, _ in resources.requests) == 3
